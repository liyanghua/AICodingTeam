from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_XHS_PACKAGE = "com.xingin.xhs"
DEFAULT_DOWNLOAD_MODE = "in_app_save"
DEFAULT_OUTPUT_ROOT = Path("runs/xhs_collector")
DEFAULT_REMOTE_IMAGE_DIR = "/sdcard/Pictures/xhs_collector"
DEFAULT_MODE = "mobilerun"
DEFAULT_SEARCH_MODE = "image_then_keyword"
SEARCH_MODES = {"image_then_keyword", "keyword_only"}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class DeterministicConfig:
    coordinate_profile: Path = Path("config/xhs_coordinates.json")
    template_dir: Path = Path("templates/xhs")
    match_threshold: float = 0.86
    wait_timeout_seconds: float = 10.0
    app_start_wait_seconds: float = 6.0
    subject_recognition_wait_seconds: float = 5.0
    max_result_scrolls: int = 5
    save_action: str = "long_press_then_save"

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "DeterministicConfig":
        payload = data or {}
        config = cls(
            coordinate_profile=Path(
                payload.get("coordinate_profile", "config/xhs_coordinates.json")
            ),
            template_dir=Path(payload.get("template_dir", "templates/xhs")),
            match_threshold=float(payload.get("match_threshold", 0.86)),
            wait_timeout_seconds=float(payload.get("wait_timeout_seconds", 10.0)),
            app_start_wait_seconds=float(
                payload.get("app_start_wait_seconds", 6.0)
            ),
            subject_recognition_wait_seconds=float(
                payload.get("subject_recognition_wait_seconds", 5.0)
            ),
            max_result_scrolls=int(payload.get("max_result_scrolls", 5)),
            save_action=str(payload.get("save_action", "long_press_then_save")),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not 0 <= self.match_threshold <= 1:
            raise ValueError("match_threshold must be between 0 and 1")
        if self.wait_timeout_seconds < 0:
            raise ValueError("wait_timeout_seconds must be >= 0")
        if self.app_start_wait_seconds < 0:
            raise ValueError("app_start_wait_seconds must be >= 0")
        if self.subject_recognition_wait_seconds < 0:
            raise ValueError("subject_recognition_wait_seconds must be >= 0")
        if self.max_result_scrolls < 1:
            raise ValueError("max_result_scrolls must be >= 1")
        if self.save_action != "long_press_then_save":
            raise ValueError("save_action must be long_press_then_save")


@dataclass(frozen=True)
class CollectorConfig:
    device_serial: str | None = None
    xhs_package: str = DEFAULT_XHS_PACKAGE
    top_n: int = 5
    image_top_n: int = 5
    keyword_top_n: int = 3
    keyword_result_top_n: int = 5
    mode: str = DEFAULT_MODE
    search_mode: str = DEFAULT_SEARCH_MODE
    keyword_template: str = "{keyword} {description}"
    target_category: str = ""
    target_category_keywords: list[str] = field(default_factory=list)
    vision_only: bool = True
    throttle_seconds: float = 2.0
    max_items_per_run: int | None = None
    download_mode: str = DEFAULT_DOWNLOAD_MODE
    output_root: Path = DEFAULT_OUTPUT_ROOT
    remote_image_dir: str = DEFAULT_REMOTE_IMAGE_DIR
    deterministic: DeterministicConfig = field(default_factory=DeterministicConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CollectorConfig":
        top_n = int(data.get("top_n", 5))
        config = cls(
            device_serial=_optional_str(data.get("device_serial")),
            xhs_package=str(data.get("xhs_package", DEFAULT_XHS_PACKAGE)).strip()
            or DEFAULT_XHS_PACKAGE,
            top_n=top_n,
            image_top_n=int(data.get("image_top_n", top_n)),
            keyword_top_n=int(data.get("keyword_top_n", 3)),
            keyword_result_top_n=int(data.get("keyword_result_top_n", top_n)),
            mode=str(data.get("mode", DEFAULT_MODE)).strip() or DEFAULT_MODE,
            search_mode=str(data.get("search_mode", DEFAULT_SEARCH_MODE)).strip()
            or DEFAULT_SEARCH_MODE,
            keyword_template=str(
                data.get("keyword_template", "{keyword} {description}")
            ),
            target_category=str(data.get("target_category", "")).strip(),
            target_category_keywords=_string_list(
                data.get("target_category_keywords", [])
            ),
            vision_only=_as_bool(data.get("vision_only", True)),
            throttle_seconds=float(data.get("throttle_seconds", 2.0)),
            max_items_per_run=_optional_int(data.get("max_items_per_run")),
            download_mode=str(data.get("download_mode", DEFAULT_DOWNLOAD_MODE)).strip()
            or DEFAULT_DOWNLOAD_MODE,
            output_root=Path(data.get("output_root", DEFAULT_OUTPUT_ROOT)),
            remote_image_dir=str(
                data.get("remote_image_dir", DEFAULT_REMOTE_IMAGE_DIR)
            ).rstrip("/"),
            deterministic=DeterministicConfig.from_dict(data.get("deterministic")),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.top_n < 1:
            raise ValueError("top_n must be >= 1")
        if self.image_top_n < 1:
            raise ValueError("image_top_n must be >= 1")
        if self.keyword_top_n < 0:
            raise ValueError("keyword_top_n must be >= 0")
        if self.keyword_result_top_n < 0:
            raise ValueError("keyword_result_top_n must be >= 0")
        if self.throttle_seconds < 0:
            raise ValueError("throttle_seconds must be >= 0")
        if self.max_items_per_run is not None and self.max_items_per_run < 1:
            raise ValueError("max_items_per_run must be >= 1")
        if self.download_mode != DEFAULT_DOWNLOAD_MODE:
            raise ValueError("download_mode must be in_app_save")
        if self.mode not in {"mobilerun", "deterministic"}:
            raise ValueError("mode must be mobilerun or deterministic")
        if self.search_mode not in SEARCH_MODES:
            allowed = ", ".join(sorted(SEARCH_MODES))
            raise ValueError(f"search_mode must be one of: {allowed}")
        if not self.xhs_package:
            raise ValueError("xhs_package must not be empty")
        if not self.remote_image_dir.startswith("/sdcard/"):
            raise ValueError("remote_image_dir must be under /sdcard")


@dataclass(frozen=True)
class InputItem:
    item_id: str
    keyword: str
    keyword_candidates: list[str] = field(default_factory=list)
    description: str = ""
    reference_image: Path = Path()
    top_n: int = 5
    source_row: int = 0

    def formatted_keywords(self, template: str) -> str:
        if self.keyword_candidates:
            return "\n".join(self.keyword_candidates)
        return " ".join(
            template.format(keyword=self.keyword, description=self.description).split()
        )


@dataclass(frozen=True)
class CollectedImage:
    rank: int
    local_path: Path
    device_path: str
    source: str = DEFAULT_DOWNLOAD_MODE
    stage: str = ""
    query: str = ""
    keyword_index: int | None = None


@dataclass
class ItemResult:
    item_id: str
    keyword: str
    status: str
    keyword_candidates: list[str] = field(default_factory=list)
    collected_count: int = 0
    images: list[CollectedImage] = field(default_factory=list)
    message: str = ""
    risk_events: list[dict[str, Any]] = field(default_factory=list)
    step_count: int = 0
    template_hits: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RunManifest:
    run_id: str
    status: str
    output_dir: Path
    input_path: Path
    config: CollectorConfig
    results: list[ItemResult] = field(default_factory=list)
    risk_events: list[dict[str, Any]] = field(default_factory=list)
    mode: str = DEFAULT_MODE
    coordinate_profile: Path | None = None
    template_hits: list[dict[str, Any]] = field(default_factory=list)
    step_count: int = 0


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _optional_int(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(value)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = re_split_keywords(value)
    elif isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            parts.extend(re_split_keywords(str(item)))
    else:
        parts = re_split_keywords(str(value))
    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        text = " ".join(part.split())
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def re_split_keywords(value: str) -> list[str]:
    import re

    return re.split(r"[,，\n\r]+", value)
