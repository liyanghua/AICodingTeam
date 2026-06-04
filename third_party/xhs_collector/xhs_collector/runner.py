from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import re
import shutil
from dataclasses import replace
from pathlib import Path

from .artifacts import (
    append_jsonl,
    touch_log,
    write_item_metadata,
    write_manifest,
)
from .config import load_config
from .deterministic_device import write_default_coordinate_profile
from .deterministic_flow import run_deterministic_collect
from .device import AndroidCollectorDevice
from .excel_reader import read_input_excel
from .media_store import DryRunMediaStore, MediaStore
from .models import (
    CollectedImage,
    CollectorConfig,
    InputItem,
    ItemResult,
    RunManifest,
)
from .xhs_flow import collect_item_with_mobilerun


def make_run_id(now: dt.datetime | None = None) -> str:
    value = now or dt.datetime.now(dt.UTC)
    return value.strftime("%Y%m%dT%H%M%S%fZ")


def validate_input(
    input_path: Path, config: CollectorConfig | None = None
) -> list[InputItem]:
    effective_config = config or CollectorConfig.from_dict({})
    return read_input_excel(
        input_path, Path("/tmp/xhs_collector_validate"), effective_config.image_top_n
    )


def run_dry_collect(
    input_path: Path,
    config_path: Path | None = None,
    top_n: int | None = None,
    keyword_top_n: int | None = None,
    image_top_n: int | None = None,
    keyword_result_top_n: int | None = None,
) -> RunManifest:
    config = _config_with_overrides(
        load_config(config_path),
        top_n=top_n,
        keyword_top_n=keyword_top_n,
        image_top_n=image_top_n,
        keyword_result_top_n=keyword_result_top_n,
    )
    output_dir = config.output_root / make_run_id()
    _prepare_output_dir(output_dir)
    items = _load_items(input_path, output_dir, config)
    manifest = RunManifest(
        run_id=output_dir.name,
        status="running",
        output_dir=output_dir,
        input_path=input_path,
        config=config,
        mode="dry-run",
    )
    write_manifest(manifest)

    dry_store = DryRunMediaStore()
    for item in items:
        result = _dry_collect_item(item, output_dir, dry_store)
        manifest.results.append(result)
        write_item_metadata(output_dir, item.item_id, result)
    manifest.status = "completed"
    write_manifest(manifest)
    return manifest


def run_dry_collect_items(
    items: list[InputItem],
    input_path: Path,
    config_path: Path | None = None,
    top_n: int | None = None,
    keyword_top_n: int | None = None,
    image_top_n: int | None = None,
    keyword_result_top_n: int | None = None,
) -> RunManifest:
    config = _config_with_overrides(
        load_config(config_path),
        top_n=top_n,
        keyword_top_n=keyword_top_n,
        image_top_n=image_top_n,
        keyword_result_top_n=keyword_result_top_n,
    )
    output_dir = config.output_root / make_run_id()
    _prepare_output_dir(output_dir)
    normalized_items = _copy_direct_items_to_output(items, output_dir)
    if config.max_items_per_run is not None:
        normalized_items = normalized_items[: config.max_items_per_run]
    manifest = RunManifest(
        run_id=output_dir.name,
        status="running",
        output_dir=output_dir,
        input_path=input_path,
        config=config,
        mode="dry-run",
    )
    write_manifest(manifest)
    dry_store = DryRunMediaStore()
    for item in normalized_items:
        result = _dry_collect_item(item, output_dir, dry_store)
        manifest.results.append(result)
        write_item_metadata(output_dir, item.item_id, result)
    manifest.status = "completed"
    write_manifest(manifest)
    return manifest


async def run_collect_async(
    input_path: Path,
    config_path: Path | None = None,
    top_n: int | None = None,
    mode: str | None = None,
    keyword_top_n: int | None = None,
    image_top_n: int | None = None,
    keyword_result_top_n: int | None = None,
    cancel_token=None,
) -> RunManifest:
    config = _config_with_overrides(
        load_config(config_path),
        top_n=top_n,
        keyword_top_n=keyword_top_n,
        image_top_n=image_top_n,
        keyword_result_top_n=keyword_result_top_n,
        mode=mode,
    )
    output_dir = config.output_root / make_run_id()
    _prepare_output_dir(output_dir)
    items = _load_items(input_path, output_dir, config)
    return await _run_loaded_items_async(
        items=items,
        input_path=input_path,
        config=config,
        output_dir=output_dir,
        cancel_token=cancel_token,
    )


async def run_collect_items_async(
    items: list[InputItem],
    input_path: Path,
    config_path: Path | None = None,
    top_n: int | None = None,
    mode: str | None = None,
    keyword_top_n: int | None = None,
    image_top_n: int | None = None,
    keyword_result_top_n: int | None = None,
    search_mode: str | None = None,
    cancel_token=None,
) -> RunManifest:
    config = _config_with_overrides(
        load_config(config_path),
        top_n=top_n,
        keyword_top_n=keyword_top_n,
        image_top_n=image_top_n,
        keyword_result_top_n=keyword_result_top_n,
        mode=mode,
        search_mode=search_mode,
    )
    output_dir = config.output_root / make_run_id()
    _prepare_output_dir(output_dir)
    normalized_items = _copy_direct_items_to_output(items, output_dir)
    if config.max_items_per_run is not None:
        normalized_items = normalized_items[: config.max_items_per_run]
    return await _run_loaded_items_async(
        items=normalized_items,
        input_path=input_path,
        config=config,
        output_dir=output_dir,
        cancel_token=cancel_token,
    )


async def run_collect_keyword_async(
    keyword: str,
    config_path: Path | None = None,
    top_n: int | None = None,
    *,
    mode: str | None = None,
    cancel_token=None,
) -> RunManifest:
    query = " ".join(keyword.split())
    if not query:
        raise ValueError("keyword must not be empty")
    effective_mode = mode or "deterministic"
    if effective_mode != "deterministic":
        raise ValueError("run-keyword currently supports deterministic mode only")
    base_config = load_config(config_path)
    target_count = top_n if top_n is not None else base_config.top_n
    config = _config_with_overrides(
        base_config,
        top_n=target_count,
        keyword_top_n=1,
        keyword_result_top_n=target_count,
        mode=effective_mode,
        search_mode="keyword_only",
    )
    output_dir = config.output_root / make_run_id()
    _prepare_output_dir(output_dir)
    item = InputItem(
        item_id=_keyword_item_id(query),
        keyword=query,
        keyword_candidates=[query],
        top_n=target_count,
        reference_image=Path(),
    )
    normalized_items = _copy_direct_items_to_output([item], output_dir)
    return await _run_loaded_items_async(
        items=normalized_items,
        input_path=Path("keyword_input"),
        config=config,
        output_dir=output_dir,
        cancel_token=cancel_token,
    )


async def _run_loaded_items_async(
    *,
    items: list[InputItem],
    input_path: Path,
    config: CollectorConfig,
    output_dir: Path,
    cancel_token=None,
) -> RunManifest:
    manifest = RunManifest(
        run_id=output_dir.name,
        status="running",
        output_dir=output_dir,
        input_path=input_path,
        config=config,
        mode=config.mode,
        coordinate_profile=(
            config.deterministic.coordinate_profile
            if config.mode == "deterministic"
            else None
        ),
    )
    write_manifest(manifest)

    if config.mode == "deterministic":
        def write_result(result: ItemResult) -> None:
            manifest.results.append(result)
            manifest.step_count += result.step_count
            manifest.template_hits.extend(result.template_hits)
            if result.risk_events:
                manifest.risk_events.extend(result.risk_events)
                for event in result.risk_events:
                    append_jsonl(output_dir / "risk_events.jsonl", event)
            write_item_metadata(output_dir, result.item_id, result)
            write_manifest(manifest)

        run_deterministic_collect(
            items=items,
            config=config,
            output_dir=output_dir,
            manifest=manifest,
            write_result=write_result,
            cancel_token=cancel_token,
        )
        manifest.status = _manifest_status_from_results(
            manifest.results, manifest.risk_events
        )
        write_manifest(manifest)
        return manifest

    device = AndroidCollectorDevice(config)
    await device.connect()
    await device.start_xhs()
    media_store = MediaStore(device.adb_device)

    for item in items:
        if _cancel_requested(cancel_token):
            result = _canceled_result(item)
            manifest.results.append(result)
            manifest.risk_events.extend(result.risk_events)
            append_jsonl(output_dir / "risk_events.jsonl", result.risk_events[0])
            write_item_metadata(output_dir, item.item_id, result)
            write_manifest(manifest)
            break
        append_jsonl(
            output_dir / "events.jsonl",
            {"event": "item.started", "item_id": item.item_id, "keyword": item.keyword},
        )
        item_dir = output_dir / "items" / item.item_id
        try:
            remote_reference = await device.push_reference_image(
                item.reference_image, item.item_id
            )
            images, message = await collect_item_with_mobilerun(
                item, config, remote_reference, item_dir, media_store
            )
            status = "completed" if len(images) >= item.top_n else "partial"
            result = ItemResult(
                item_id=item.item_id,
                keyword=item.keyword,
                status=status,
                keyword_candidates=item.keyword_candidates,
                collected_count=len(images),
                images=images,
                message=message,
            )
        except Exception as exc:
            risk = {
                "event": "item.failed",
                "item_id": item.item_id,
                "reason": str(exc),
            }
            append_jsonl(output_dir / "risk_events.jsonl", risk)
            manifest.risk_events.append(risk)
            result = ItemResult(
                item_id=item.item_id,
                keyword=item.keyword,
                status="failed",
                keyword_candidates=item.keyword_candidates,
                message=str(exc),
                risk_events=[risk],
            )
        manifest.results.append(result)
        write_item_metadata(output_dir, item.item_id, result)
        write_manifest(manifest)
        if _cancel_requested(cancel_token):
            break

    manifest.status = _manifest_status_from_results(manifest.results, manifest.risk_events)
    write_manifest(manifest)
    return manifest


def _manifest_status_from_results(
    results: list[ItemResult], risk_events: list[dict] | None = None
) -> str:
    if not results:
        return "failed" if risk_events else "completed"
    if all(result.status == "canceled" for result in results):
        if any(result.collected_count for result in results):
            return "partial"
        return "canceled"
    if all(result.status == "failed" and result.collected_count == 0 for result in results):
        return "failed"
    if all(result.status == "completed" for result in results):
        return "completed"
    return "partial"


def _cancel_requested(cancel_token) -> bool:
    return bool(
        cancel_token is not None and getattr(cancel_token, "is_cancel_requested")()
    )


def _canceled_result(item: InputItem) -> ItemResult:
    event = {"event": "collection_canceled", "item_id": item.item_id}
    return ItemResult(
        item_id=item.item_id,
        keyword=item.keyword,
        status="canceled",
        keyword_candidates=item.keyword_candidates,
        collected_count=0,
        message="canceled",
        risk_events=[event],
    )


def run_collect(
    input_path: Path,
    config_path: Path | None = None,
    top_n: int | None = None,
    mode: str | None = None,
    keyword_top_n: int | None = None,
    image_top_n: int | None = None,
    keyword_result_top_n: int | None = None,
    cancel_token=None,
) -> RunManifest:
    return asyncio.run(
        run_collect_async(
            input_path,
            config_path,
            top_n,
            mode=mode,
            keyword_top_n=keyword_top_n,
            image_top_n=image_top_n,
            keyword_result_top_n=keyword_result_top_n,
            cancel_token=cancel_token,
        )
    )


def run_collect_items(
    items: list[InputItem],
    input_path: Path,
    config_path: Path | None = None,
    top_n: int | None = None,
    mode: str | None = None,
    keyword_top_n: int | None = None,
    image_top_n: int | None = None,
    keyword_result_top_n: int | None = None,
    search_mode: str | None = None,
    cancel_token=None,
) -> RunManifest:
    return asyncio.run(
        run_collect_items_async(
            items=items,
            input_path=input_path,
            config_path=config_path,
            top_n=top_n,
            mode=mode,
            keyword_top_n=keyword_top_n,
            image_top_n=image_top_n,
            keyword_result_top_n=keyword_result_top_n,
            search_mode=search_mode,
            cancel_token=cancel_token,
        )
    )


def run_collect_keyword(
    keyword: str,
    config_path: Path | None = None,
    top_n: int | None = None,
    *,
    mode: str | None = None,
    cancel_token=None,
) -> RunManifest:
    return asyncio.run(
        run_collect_keyword_async(
            keyword,
            config_path,
            top_n,
            mode=mode,
            cancel_token=cancel_token,
        )
    )


def calibrate(output_path: Path) -> Path:
    write_default_coordinate_profile(output_path)
    return output_path


def _prepare_output_dir(output_dir: Path) -> None:
    (output_dir / "inputs").mkdir(parents=True, exist_ok=True)
    (output_dir / "items").mkdir(parents=True, exist_ok=True)
    (output_dir / "screenshots").mkdir(parents=True, exist_ok=True)
    touch_log(output_dir / "events.jsonl")
    touch_log(output_dir / "risk_events.jsonl")


def _load_items(
    input_path: Path, output_dir: Path, config: CollectorConfig
) -> list[InputItem]:
    items = read_input_excel(input_path, output_dir / "inputs", config.image_top_n)
    if config.max_items_per_run is not None:
        items = items[: config.max_items_per_run]
    return items


def _copy_direct_items_to_output(
    items: list[InputItem], output_dir: Path
) -> list[InputItem]:
    normalized: list[InputItem] = []
    for item in items:
        source = item.reference_image
        target_dir = output_dir / "inputs" / item.item_id
        target_dir.mkdir(parents=True, exist_ok=True)
        if not str(source) or not source.is_file():
            normalized.append(item)
            continue
        target = target_dir / f"reference{source.suffix or '.jpg'}"
        if source.exists() and source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        elif source.exists() and not target.exists():
            shutil.copyfile(source, target)
        normalized.append(replace(item, reference_image=target))
    return normalized


def _keyword_item_id(keyword: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", keyword).strip("-")
    slug = slug[:40] or "keyword"
    digest = hashlib.sha1(keyword.encode("utf-8")).hexdigest()[:8]
    return f"keyword-{slug}-{digest}"


def _dry_collect_item(
    item: InputItem, output_dir: Path, dry_store: DryRunMediaStore
) -> ItemResult:
    images: list[CollectedImage] = []
    item_dir = output_dir / "items" / item.item_id
    for rank in range(1, item.top_n + 1):
        target_path = item_dir / f"rank_{rank:03d}{item.reference_image.suffix or '.jpg'}"
        dry_store.copy_ranked_image(item.reference_image, target_path)
        images.append(
            CollectedImage(
                rank=rank,
                local_path=target_path,
                device_path=f"dry-run://{item.item_id}/{rank}",
            )
        )
    return ItemResult(
        item_id=item.item_id,
        keyword=item.keyword,
        status="completed",
        keyword_candidates=item.keyword_candidates,
        collected_count=len(images),
        images=images,
        message="dry-run generated local ranked image copies",
    )


def _config_with_overrides(
    config: CollectorConfig,
    top_n: int | None = None,
    keyword_top_n: int | None = None,
    image_top_n: int | None = None,
    keyword_result_top_n: int | None = None,
    mode: str | None = None,
    search_mode: str | None = None,
) -> CollectorConfig:
    if (
        top_n is None
        and keyword_top_n is None
        and image_top_n is None
        and keyword_result_top_n is None
        and mode is None
        and search_mode is None
    ):
        return config
    data = {
        "device_serial": config.device_serial,
        "xhs_package": config.xhs_package,
        "top_n": top_n if top_n is not None else config.top_n,
        "image_top_n": (
            image_top_n if image_top_n is not None else config.image_top_n
        ),
        "keyword_top_n": (
            keyword_top_n if keyword_top_n is not None else config.keyword_top_n
        ),
        "keyword_result_top_n": (
            keyword_result_top_n
            if keyword_result_top_n is not None
            else config.keyword_result_top_n
        ),
        "mode": mode or config.mode,
        "search_mode": search_mode or config.search_mode,
        "keyword_template": config.keyword_template,
        "target_category": config.target_category,
        "target_category_keywords": config.target_category_keywords,
        "vision_only": config.vision_only,
        "throttle_seconds": config.throttle_seconds,
        "max_items_per_run": config.max_items_per_run,
        "download_mode": config.download_mode,
        "output_root": str(config.output_root),
        "remote_image_dir": config.remote_image_dir,
        "deterministic": {
            "coordinate_profile": str(config.deterministic.coordinate_profile),
            "template_dir": str(config.deterministic.template_dir),
            "match_threshold": config.deterministic.match_threshold,
            "wait_timeout_seconds": config.deterministic.wait_timeout_seconds,
            "app_start_wait_seconds": config.deterministic.app_start_wait_seconds,
            "subject_recognition_wait_seconds": (
                config.deterministic.subject_recognition_wait_seconds
            ),
            "max_result_scrolls": config.deterministic.max_result_scrolls,
            "save_action": config.deterministic.save_action,
        },
    }
    return CollectorConfig.from_dict(data)
