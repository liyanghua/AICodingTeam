from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .runtime import (
    MobilerunAdapter,
    RecognitionRequest,
    TargetRecognitionRuntime,
)


class FakeTaobaoImageSearchDevice:
    def __init__(self) -> None:
        self.state = "home"
        self.actions: list[dict[str, Any]] = []

    def tap_bounds(self, name: str, bounds: list[float]) -> None:
        self.actions.append({"action": "tap", "name": name, "bounds": bounds})
        if name == "image_search_button":
            self.state = "album"
        elif name == "album_entry":
            self.state = "album"
        elif name == "first_album_image":
            self.state = "results"

    def page_has_album_markers(self) -> bool:
        return self.state == "album"

    def page_has_result_markers(self) -> bool:
        return self.state == "results"


def run_taobao_image_search_eval(
    *,
    output_root: Path,
    reference_image: Path,
    adapter: MobilerunAdapter,
    device: FakeTaobaoImageSearchDevice,
    run_id: str = "",
) -> dict[str, Any]:
    if not reference_image.exists():
        raise FileNotFoundError(f"reference image not found: {reference_image}")
    output_dir = output_root / (run_id or "taobao-image-search-eval")
    runtime = TargetRecognitionRuntime(output_dir, adapter)

    summary: dict[str, Any] = {
        "status": "running",
        "run_id": output_dir.name,
        "reference_image": str(reference_image),
        "output_dir": str(output_dir),
    }
    image_result = runtime.recognize(
        RecognitionRequest(
            item_id=output_dir.name,
            stage="home",
            target_type="image_search_button",
            prompt="Find the Taobao image search camera entry on the current home page.",
        )
    )
    if not image_result.allowed or image_result.response is None:
        return _finish(output_dir, summary, "failed", image_result.event)
    device.tap_bounds("image_search_button", image_result.response.bounds)
    _append_jsonl(output_dir / "step_events.jsonl", {"event": "taobao_image_search_button_tapped"})

    album_result = runtime.recognize(
        RecognitionRequest(
            item_id=output_dir.name,
            stage="album",
            target_type="album_entry",
            prompt="Find the album entry or album grid after entering Taobao image search.",
        )
    )
    if not album_result.allowed or album_result.response is None:
        return _finish(output_dir, summary, "failed", album_result.event)
    device.tap_bounds("album_entry", album_result.response.bounds)
    if not device.page_has_album_markers():
        return _finish(output_dir, summary, "failed", "taobao_album_gate_failed")
    _append_jsonl(output_dir / "step_events.jsonl", {"event": "taobao_album_page_reached"})

    first_image_result = runtime.recognize(
        RecognitionRequest(
            item_id=output_dir.name,
            stage="album",
            target_type="first_album_image",
            prompt="Find the first selectable reference image in the album grid.",
        )
    )
    if not first_image_result.allowed or first_image_result.response is None:
        return _finish(output_dir, summary, "failed", first_image_result.event)
    device.tap_bounds("first_album_image", first_image_result.response.bounds)
    if not device.page_has_result_markers():
        return _finish(output_dir, summary, "failed", "taobao_image_search_results_not_reached")
    _append_jsonl(output_dir / "step_events.jsonl", {"event": "taobao_image_search_results_reached"})
    return _finish(output_dir, summary, "completed", "")


def _finish(
    output_dir: Path,
    summary: dict[str, Any],
    status: str,
    failure_event: str,
) -> dict[str, Any]:
    summary["status"] = status
    if failure_event:
        summary["failure_event"] = failure_event
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
