from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .config import load_config
from .device import UiautomatorTaobaoDevice
from .flow import run_taobao_flow
from .models import TaobaoConfig, TaobaoManifest, TaobaoRequest


def run(
    request: TaobaoRequest,
    config_path: Path | None = None,
    *,
    device=None,
    mode: str | None = None,
    top_n: int | None = None,
    output_root: Path | None = None,
    coordinate_profile: Path | None = None,
    device_serial: str | None = None,
) -> TaobaoManifest:
    config = _config_with_overrides(
        load_config(config_path),
        mode=mode,
        top_n=top_n,
        output_root=output_root,
        coordinate_profile=coordinate_profile,
        device_serial=device_serial,
    )
    effective_request = replace(
        request,
        mode=mode or request.mode or config.mode,
        top_n=top_n if top_n is not None else request.top_n,
    )
    effective_device = device or UiautomatorTaobaoDevice.connect(config.device_serial)
    return run_taobao_flow(effective_request, config, effective_device)


def _config_with_overrides(
    config: TaobaoConfig,
    *,
    mode: str | None = None,
    top_n: int | None = None,
    output_root: Path | None = None,
    coordinate_profile: Path | None = None,
    device_serial: str | None = None,
) -> TaobaoConfig:
    if (
        mode is None
        and top_n is None
        and output_root is None
        and coordinate_profile is None
        and device_serial is None
    ):
        return config
    return TaobaoConfig.from_dict(
        {
            "taobao_package": config.taobao_package,
            "device_serial": device_serial if device_serial is not None else config.device_serial,
            "mode": mode or config.mode,
            "top_n": top_n if top_n is not None else config.top_n,
            "output_root": str(output_root or config.output_root),
            "coordinate_profile": str(coordinate_profile or config.coordinate_profile),
            "remote_image_dir": config.remote_image_dir,
            "wait_timeout_seconds": config.wait_timeout_seconds,
            "app_start_wait_seconds": config.app_start_wait_seconds,
            "throttle_seconds": config.throttle_seconds,
            "detail_extra_top_n": config.detail_extra_top_n,
            "detail_media_scan_max": config.detail_media_scan_max,
            "detail_media_swipe_start": list(config.detail_media_swipe_start),
            "detail_media_swipe_end": list(config.detail_media_swipe_end),
        }
    )
