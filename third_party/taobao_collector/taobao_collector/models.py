from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_TAOBAO_PACKAGE = "com.taobao.taobao"
DEFAULT_OUTPUT_ROOT = Path("runs/taobao_collector")
DEFAULT_COORDINATE_PROFILE = Path("config/taobao_coordinates.json")
DEFAULT_REMOTE_IMAGE_DIR = "/sdcard/Pictures/taobao_collector"
MODES = {"image_search", "keyword_search", "both"}


@dataclass(frozen=True)
class TaobaoConfig:
    taobao_package: str = DEFAULT_TAOBAO_PACKAGE
    device_serial: str | None = None
    mode: str = "keyword_search"
    top_n: int = 5
    output_root: Path = DEFAULT_OUTPUT_ROOT
    coordinate_profile: Path = DEFAULT_COORDINATE_PROFILE
    remote_image_dir: str = DEFAULT_REMOTE_IMAGE_DIR
    wait_timeout_seconds: float = 10.0
    app_start_wait_seconds: float = 5.0
    throttle_seconds: float = 1.0
    detail_extra_top_n: int = 1
    detail_media_scan_max: int = 5
    detail_media_swipe_start: tuple[float, float] = (0.82, 0.35)
    detail_media_swipe_end: tuple[float, float] = (0.18, 0.35)
    max_result_scrolls: int = 10
    result_page_scroll_start: tuple[float, float] = (0.5, 0.78)
    result_page_scroll_end: tuple[float, float] = (0.5, 0.34)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TaobaoConfig":
        payload = data or {}
        config = cls(
            taobao_package=str(
                payload.get("taobao_package", DEFAULT_TAOBAO_PACKAGE)
            ).strip()
            or DEFAULT_TAOBAO_PACKAGE,
            device_serial=_optional_str(payload.get("device_serial")),
            mode=str(payload.get("mode", "keyword_search")).strip()
            or "keyword_search",
            top_n=int(payload.get("top_n", 5)),
            output_root=Path(payload.get("output_root", DEFAULT_OUTPUT_ROOT)),
            coordinate_profile=Path(
                payload.get("coordinate_profile", DEFAULT_COORDINATE_PROFILE)
            ),
            remote_image_dir=str(
                payload.get("remote_image_dir", DEFAULT_REMOTE_IMAGE_DIR)
            ).rstrip("/"),
            wait_timeout_seconds=float(payload.get("wait_timeout_seconds", 10.0)),
            app_start_wait_seconds=float(payload.get("app_start_wait_seconds", 5.0)),
            throttle_seconds=float(payload.get("throttle_seconds", 1.0)),
            detail_extra_top_n=int(payload.get("detail_extra_top_n", 1)),
            detail_media_scan_max=int(payload.get("detail_media_scan_max", 5)),
            detail_media_swipe_start=_point(
                payload.get("detail_media_swipe_start", [0.82, 0.35]),
                "detail_media_swipe_start",
            ),
            detail_media_swipe_end=_point(
                payload.get("detail_media_swipe_end", [0.18, 0.35]),
                "detail_media_swipe_end",
            ),
            max_result_scrolls=int(payload.get("max_result_scrolls", 10)),
            result_page_scroll_start=_point(
                payload.get("result_page_scroll_start", [0.5, 0.78]),
                "result_page_scroll_start",
            ),
            result_page_scroll_end=_point(
                payload.get("result_page_scroll_end", [0.5, 0.34]),
                "result_page_scroll_end",
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.mode not in MODES:
            allowed = ", ".join(sorted(MODES))
            raise ValueError(f"mode must be one of: {allowed}")
        if self.top_n < 1:
            raise ValueError("top_n must be >= 1")
        if self.wait_timeout_seconds < 0:
            raise ValueError("wait_timeout_seconds must be >= 0")
        if self.app_start_wait_seconds < 0:
            raise ValueError("app_start_wait_seconds must be >= 0")
        if self.throttle_seconds < 0:
            raise ValueError("throttle_seconds must be >= 0")
        if self.detail_extra_top_n < 0:
            raise ValueError("detail_extra_top_n must be >= 0")
        if self.detail_media_scan_max < 1:
            raise ValueError("detail_media_scan_max must be >= 1")
        if self.max_result_scrolls < 0:
            raise ValueError("max_result_scrolls must be >= 0")
        _validate_ratio_point(self.detail_media_swipe_start, "detail_media_swipe_start")
        _validate_ratio_point(self.detail_media_swipe_end, "detail_media_swipe_end")
        _validate_ratio_point(self.result_page_scroll_start, "result_page_scroll_start")
        _validate_ratio_point(self.result_page_scroll_end, "result_page_scroll_end")
        if not self.taobao_package:
            raise ValueError("taobao_package must not be empty")
        if not self.remote_image_dir.startswith("/sdcard/"):
            raise ValueError("remote_image_dir must be under /sdcard")


@dataclass(frozen=True)
class TaobaoRequest:
    mode: str
    input_image: Path | None = None
    keyword: str = ""
    keywords: list[str] = field(default_factory=list)
    top_n: int = 5

    def normalized_keywords(self) -> list[str]:
        candidates = [self.keyword, *self.keywords]
        return [value for value in (" ".join(item.split()) for item in candidates) if value]


@dataclass
class TaobaoAsset:
    asset_id: str
    channel: str
    mode: str
    source_item_id: str
    query: str
    stage: str
    rank: int
    local_path: Path
    content_sha256: str
    image_type: str
    status: str = "available"
    message: str = ""


@dataclass
class TaobaoManifest:
    run_id: str
    channel: str
    mode: str
    status: str
    output_dir: Path
    request: TaobaoRequest
    config: TaobaoConfig
    assets: list[TaobaoAsset] = field(default_factory=list)
    risk_events: list[dict[str, Any]] = field(default_factory=list)
    step_count: int = 0


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _point(value: Any, name: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{name} must be [x_ratio, y_ratio]")
    return float(value[0]), float(value[1])


def _validate_ratio_point(point: tuple[float, float], name: str) -> None:
    for value in point:
        if not 0 <= value <= 1:
            raise ValueError(f"{name} ratios must be between 0 and 1")
