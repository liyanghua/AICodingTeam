from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .settings import JobSettings

try:
    from xhs_collector.models import InputItem, RunManifest
    from xhs_collector.runner import (
        run_collect,
        run_collect_items,
        run_dry_collect,
        run_dry_collect_items,
    )
except ImportError:  # pragma: no cover - used from the monorepo without install
    from third_party.xhs_collector.xhs_collector.models import InputItem, RunManifest
    from third_party.xhs_collector.xhs_collector.runner import (
        run_collect,
        run_collect_items,
        run_dry_collect,
        run_dry_collect_items,
    )


def build_collector_config_payload(
    settings: JobSettings,
    output_root: Path,
    base_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(base_config or {})
    payload.update(
        {
            "mode": "deterministic" if settings.deterministic_mode else "mobilerun",
            "top_n": settings.image_top_n,
            "image_top_n": settings.image_top_n,
            "keyword_top_n": settings.keyword_top_n,
            "keyword_result_top_n": settings.keyword_result_top_n,
            "target_category": settings.target_category,
            "target_category_keywords": settings.effective_target_category_keywords,
            "throttle_seconds": settings.throttle_seconds,
            "output_root": str(output_root),
        }
    )
    if settings.device_serial:
        payload["device_serial"] = settings.device_serial
    deterministic = dict(payload.get("deterministic") or {})
    deterministic["max_result_scrolls"] = settings.max_result_scrolls
    deterministic["subject_recognition_wait_seconds"] = (
        settings.subject_recognition_wait_seconds
    )
    payload["deterministic"] = deterministic
    return payload


def write_collector_config(
    settings: JobSettings,
    output_root: Path,
    target_path: Path,
    base_config_path: Path | None = None,
) -> Path:
    base_config = _read_json(base_config_path) if base_config_path else {}
    if base_config_path is not None:
        _resolve_base_config_paths(base_config, base_config_path.parent)
    payload = build_collector_config_payload(settings, output_root, base_config)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target_path


def run_config_file_collect(
    input_path: Path,
    config_path: Path,
    settings: JobSettings,
    cancel_token: Any | None = None,
) -> RunManifest:
    if settings.dry_run:
        return run_dry_collect(
            input_path,
            config_path,
            image_top_n=settings.image_top_n,
            keyword_top_n=settings.keyword_top_n,
            keyword_result_top_n=settings.keyword_result_top_n,
        )
    return run_collect(
        input_path,
        config_path,
        mode="deterministic" if settings.deterministic_mode else "mobilerun",
        image_top_n=settings.image_top_n,
        keyword_top_n=settings.keyword_top_n,
        keyword_result_top_n=settings.keyword_result_top_n,
        cancel_token=cancel_token,
    )


def run_direct_items_collect(
    items: list[InputItem],
    input_path: Path,
    config_path: Path,
    settings: JobSettings,
    cancel_token: Any | None = None,
) -> RunManifest:
    if settings.dry_run:
        return run_dry_collect_items(
            items,
            input_path,
            config_path,
            image_top_n=settings.image_top_n,
            keyword_top_n=settings.keyword_top_n,
            keyword_result_top_n=settings.keyword_result_top_n,
        )
    return run_collect_items(
        items,
        input_path,
        config_path,
        mode="deterministic" if settings.deterministic_mode else "mobilerun",
        image_top_n=settings.image_top_n,
        keyword_top_n=settings.keyword_top_n,
        keyword_result_top_n=settings.keyword_result_top_n,
        cancel_token=cancel_token,
    )


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_base_config_paths(payload: dict[str, Any], base_dir: Path) -> None:
    deterministic = payload.get("deterministic")
    if not isinstance(deterministic, dict):
        return
    for key in ("coordinate_profile", "template_dir"):
        value = deterministic.get(key)
        if not value:
            continue
        path = Path(value)
        if not path.is_absolute():
            deterministic[key] = str((base_dir / path).resolve())
