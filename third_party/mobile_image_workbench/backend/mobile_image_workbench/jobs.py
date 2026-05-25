from __future__ import annotations

import datetime as dt
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .asset_library import AssetBlob, AssetLibrary
from .collector_bridge import (
    run_config_file_collect,
    run_direct_items_collect,
    write_collector_config,
)
from .events import read_translated_events, translate_event
from .exports import write_result_exports
from .inputs import (
    create_items_from_uploaded_images,
    uploaded_images_from_payload,
    write_config_file_from_payload,
)
from .settings import JobSettings
from .storage import FilesystemObjectStorageClient


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    status: str
    job_dir: Path
    settings: JobSettings
    collector_run_dir: Path | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "jobId": self.job_id,
            "status": self.status,
            "jobDir": str(self.job_dir),
            "settings": self.settings.to_dict(),
            "collectorRunDir": (
                str(self.collector_run_dir) if self.collector_run_dir else None
            ),
            "message": self.message,
        }


class JobManager:
    def __init__(
        self,
        root_dir: Path,
        base_collector_config: Path | None = None,
        asset_library: AssetLibrary | None = None,
    ) -> None:
        self.root_dir = root_dir
        self.base_collector_config = base_collector_config
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.asset_library = asset_library or AssetLibrary(
            self.root_dir / "asset_center.sqlite3",
            FilesystemObjectStorageClient(
                self.root_dir / "object_storage",
                bucket="mobile-image-assets",
            ),
        )

    def create_job(self, payload: dict[str, Any], *, start: bool = True) -> JobRecord:
        settings = JobSettings.from_payload(payload)
        job_id = _make_job_id()
        job_dir = self.root_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        (job_dir / "request.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        record = JobRecord(
            job_id=job_id,
            status="queued",
            job_dir=job_dir,
            settings=settings,
        )
        self._write_record(record)
        if start:
            thread = threading.Thread(target=self.run_job, args=(job_id,), daemon=True)
            thread.start()
        return record

    def run_job(self, job_id: str) -> JobRecord:
        record = self.get_job(job_id)
        payload = json.loads((record.job_dir / "request.json").read_text(encoding="utf-8"))
        record = _replace_record(record, status="running", message="采集任务运行中")
        self._write_record(record)
        self._append_job_event(
            record.job_dir, {"name": "job_started", "phase": "prepare"}
        )
        try:
            collector_output_root = record.job_dir / "collector_runs"
            config_path = write_collector_config(
                record.settings,
                collector_output_root,
                record.job_dir / "collector_config.json",
                self.base_collector_config,
            )
            self._append_job_event(
                record.job_dir, {"name": "collector_config_ready", "phase": "prepare"}
            )
            if record.settings.mode == "config_file":
                self._append_job_event(
                    record.job_dir, {"name": "prepare_config_file", "phase": "prepare"}
                )
                input_path = write_config_file_from_payload(payload, record.job_dir)
                self._append_job_event(
                    record.job_dir, {"name": "collector_started", "phase": "prepare"}
                )
                manifest = run_config_file_collect(input_path, config_path, record.settings)
            else:
                self._append_job_event(
                    record.job_dir,
                    {"name": "prepare_uploaded_images", "phase": "prepare"},
                )
                images = uploaded_images_from_payload(payload)
                if record.settings.mode == "single_image":
                    images = images[:1]
                items = create_items_from_uploaded_images(
                    images, record.job_dir, record.settings.image_top_n
                )
                input_path = record.job_dir / "generated_inputs.json"
                input_path.write_text(
                    json.dumps(
                        [
                            {
                                "item_id": item.item_id,
                                "reference_image": str(item.reference_image),
                                "keyword_candidates": item.keyword_candidates,
                            }
                            for item in items
                        ],
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                self._append_job_event(
                    record.job_dir, {"name": "collector_started", "phase": "prepare"}
                )
                manifest = run_direct_items_collect(
                    items, input_path, config_path, record.settings
                )
            self._append_job_event(
                record.job_dir, {"name": "collector_completed", "phase": "finish"}
            )
            write_result_exports(manifest.output_dir)
            self._append_job_event(
                record.job_dir, {"name": "result_exports_ready", "phase": "finish"}
            )
            self.ingest_assets(
                manifest.output_dir,
                job_id=record.job_id,
                category=record.settings.target_category,
                scene="",
                input_mode=record.settings.mode,
            )
            self._append_job_event(
                record.job_dir, {"name": "asset_center_ready", "phase": "finish"}
            )
            status = _job_status_from_manifest(manifest.status)
            updated = _replace_record(
                record,
                status=status,
                collector_run_dir=manifest.output_dir,
                message="采集完成" if status == "completed" else "采集部分完成",
            )
            self._write_record(updated)
            return updated
        except Exception as exc:
            failed = _replace_record(record, status="failed", message=str(exc))
            self._write_record(failed)
            self._append_job_event(
                record.job_dir,
                {
                    "event": "job_failed",
                    "message": str(exc),
                    "phase": "finish",
                },
            )
            return failed

    def get_job(self, job_id: str) -> JobRecord:
        path = self.root_dir / job_id / "job.json"
        if not path.exists():
            raise FileNotFoundError(f"job not found: {job_id}")
        return _record_from_payload(json.loads(path.read_text(encoding="utf-8")))

    def translated_events(self, job_id: str) -> list[dict[str, Any]]:
        record = self.get_job(job_id)
        events = _read_job_events(record.job_dir, phase="prepare")
        collector_run_dir = record.collector_run_dir
        if collector_run_dir is None or not collector_run_dir.exists():
            collector_run_dir = _latest_active_collector_run_dir(record.job_dir)
        if collector_run_dir and collector_run_dir.exists():
            events.extend(read_translated_events(collector_run_dir))
        events.extend(_read_job_events(record.job_dir, phase="finish"))
        return events

    def doctor(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "message": "工作台服务已启动；真机检查请在采集前确认 adb devices 可见手机。",
            "safety": "仅支持手动登录，不处理账号密码、验证码绕过或私有接口。",
        }

    def ingest_assets(
        self,
        run_dir: Path,
        *,
        job_id: str = "",
        category: str = "",
        scene: str = "",
        input_mode: str = "",
        uploaded_by: str = "",
    ) -> dict[str, int]:
        return self.asset_library.ingest_run(
            run_dir,
            job_id=job_id,
            category=category,
            scene=scene,
            input_mode=input_mode,
            uploaded_by=uploaded_by,
        )

    def search_assets(self, filters: dict[str, Any]) -> dict[str, Any]:
        return self.asset_library.search_payload(filters)

    def asset_blob(self, asset_id: str) -> AssetBlob:
        return self.asset_library.read_asset_blob(asset_id)

    def object_blob(self, bucket: str, key: str) -> AssetBlob:
        return self.asset_library.read_object_blob(bucket, key)

    def sync_job_to_cloud(
        self,
        job_id: str,
        *,
        scene_tagger: Any | None = None,
        cloud_sync: Any | None = None,
    ) -> dict[str, Any]:
        record = self.get_job(job_id)
        if record.status not in {"completed", "partial"}:
            raise ValueError("job must be completed or partial before cloud sync")
        if record.collector_run_dir is None or not record.collector_run_dir.exists():
            raise FileNotFoundError("collector run directory is not ready")
        server_url = os.environ.get("MWB_CLOUD_SERVER_URL", "").strip()
        token = os.environ.get("MWB_CLOUD_SYNC_TOKEN", "").strip()
        collector_id = os.environ.get("MWB_COLLECTOR_ID", "").strip()
        if not server_url:
            raise ValueError("MWB_CLOUD_SERVER_URL is required")
        if not token:
            raise ValueError("MWB_CLOUD_SYNC_TOKEN is required")
        if not collector_id:
            raise ValueError("MWB_COLLECTOR_ID is required")

        from .cloud_sync import sync_cloud_bundle
        from .scene_tagger import (
            build_scene_tagger,
            default_vlm_model,
            tag_missing_scene_assets,
        )

        category = record.settings.target_category
        self._append_job_event(
            record.job_dir, {"name": "cloud_sync_started", "phase": "finish"}
        )
        ingest_summary = self.ingest_assets(
            record.collector_run_dir,
            job_id=record.job_id,
            category=category,
            scene="",
            input_mode=record.settings.mode,
        )
        tagger = scene_tagger or build_scene_tagger(
            os.environ.get("MWB_SCENE_TAG_PROVIDER", "openai_compatible"),
            model=os.environ.get("MWB_SCENE_TAG_MODEL") or default_vlm_model(),
        )
        tag_summary = tag_missing_scene_assets(
            self.asset_library,
            tagger,
            category=category,
            job_id=record.job_id,
            limit=_env_int("MWB_SCENE_TAG_LIMIT", 200),
        )
        self._append_job_event(
            record.job_dir,
            {
                "name": "scene_tagging_completed",
                "phase": "finish",
                "tagged": tag_summary.get("tagged", 0),
                "failed": tag_summary.get("failed", 0),
            },
        )
        sync_runner = cloud_sync or sync_cloud_bundle
        cloud_summary = sync_runner(
            runs_root=self.root_dir,
            server_url=server_url,
            token=token,
            collector_id=collector_id,
            category=category,
            job_id=record.job_id,
            batch_size=_env_int("MWB_SYNC_BATCH_SIZE", 100),
        )
        self._append_job_event(
            record.job_dir,
            {
                "name": "cloud_sync_completed",
                "phase": "finish",
                "assets": cloud_summary.get("assets", 0),
                "sourceImages": cloud_summary.get("sourceImages", 0),
            },
        )
        return {
            "status": "completed",
            "jobId": record.job_id,
            "ingest": ingest_summary,
            "tagScenes": tag_summary,
            "cloudSync": cloud_summary,
        }

    def _write_record(self, record: JobRecord) -> None:
        record.job_dir.mkdir(parents=True, exist_ok=True)
        (record.job_dir / "job.json").write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _append_job_event(self, job_dir: Path, event: dict[str, Any]) -> None:
        with (job_dir / "job_events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def _read_job_events(job_dir: Path, phase: str | None = None) -> list[dict[str, Any]]:
    job_events_path = job_dir / "job_events.jsonl"
    if not job_events_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in job_events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            raw = {"name": "job_event", "message": line}
        raw.setdefault("source", "job")
        raw_phase = _job_event_phase(raw)
        if phase is not None and raw_phase != phase:
            continue
        raw.setdefault("phase", raw_phase)
        events.append(translate_event(raw))
    return events


def _job_event_phase(raw: dict[str, Any]) -> str:
    explicit_phase = str(raw.get("phase") or "").strip()
    if explicit_phase in {"prepare", "finish"}:
        return explicit_phase
    event_name = str(raw.get("name") or raw.get("event") or "")
    if event_name in {"collector_completed", "result_exports_ready", "job_failed"}:
        return "finish"
    return "prepare"


def _latest_active_collector_run_dir(job_dir: Path) -> Path | None:
    collector_root = job_dir / "collector_runs"
    if not collector_root.exists():
        return None
    candidates = [
        path
        for path in collector_root.iterdir()
        if path.is_dir()
        and any(
            (path / filename).exists()
            for filename in ("step_events.jsonl", "risk_events.jsonl", "manifest.json")
        )
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: path.name)[-1]


def _make_job_id() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _job_status_from_manifest(status: str) -> str:
    if status == "completed":
        return "completed"
    if status == "partial":
        return "partial"
    return "failed"


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    return int(value)


def _record_from_payload(payload: dict[str, Any]) -> JobRecord:
    settings = JobSettings.from_payload(
        {"settings": payload.get("settings") or {}, "mode": payload["settings"]["mode"]}
    )
    collector_run_dir = payload.get("collectorRunDir")
    return JobRecord(
        job_id=payload["jobId"],
        status=payload["status"],
        job_dir=Path(payload["jobDir"]),
        settings=settings,
        collector_run_dir=Path(collector_run_dir) if collector_run_dir else None,
        message=payload.get("message") or "",
    )


def _replace_record(record: JobRecord, **updates: Any) -> JobRecord:
    data = {
        "job_id": record.job_id,
        "status": record.status,
        "job_dir": record.job_dir,
        "settings": record.settings,
        "collector_run_dir": record.collector_run_dir,
        "message": record.message,
    }
    data.update(updates)
    return JobRecord(**data)
