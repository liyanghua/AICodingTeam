from __future__ import annotations

import re
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .deterministic_device import (
    CoordinateProfile,
    DeterministicDevice,
    SUPPORTED_POINTS,
)

BOUNDS_RE = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
POINT_PATTERNS = {
    "search_box": re.compile(r"<node\b[^>]*(?:搜索|search)[^>]*/?>", re.I),
    "image_search_button": re.compile(
        r"<node\b[^>]*(?:相机|拍照|图片|图搜|扫一扫|camera|image)[^>]*/?>",
        re.I,
    ),
    "album_entry": re.compile(
        r"<node\b[^>]*(?:相册|选择图片|从相册|album|gallery)[^>]*/?>",
        re.I,
    ),
    "album_confirm": re.compile(
        r"<node\b[^>]*(?:完成|确定|确认|下一步|使用|done|ok|confirm|next)[^>]*/?>",
        re.I,
    ),
    "save_image_menu_item": re.compile(
        r"<node\b[^>]*(?:保存图片|保存到相册|保存|save)[^>]*/?>",
        re.I,
    ),
    "keyword_search_box": re.compile(
        r"<node\b[^>]*(?:搜索|search|EditText|search_edit)[^>]*/?>",
        re.I,
    ),
    "keyword_search_submit": re.compile(
        r"<node\b[^>]*(?:搜索|search|提交|确定|完成)[^>]*/?>",
        re.I,
    ),
    "note_back_button": re.compile(
        r"<node\b[^>]*(?:返回|back)[^>]*/?>",
        re.I,
    ),
}
VISUAL_HINTS = {
    "search_box": {
        "hint": "home_top_right_search_icon",
        "ratio": (0.9325, 0.0749),
        "fallback_ratios": (
            (0.9, 0.0749),
            (0.955, 0.0749),
            (0.9333, 0.06),
            (0.9333, 0.09),
        ),
        "reason": "XHS home page search entry is the top-right magnifier",
    },
    "image_search_button": {
        "hint": "search_page_camera_icon",
        "ratio": (0.7683, 0.0794),
        "fallback_ratios": (
            (0.75, 0.0794),
            (0.79, 0.0794),
            (0.7683, 0.065),
            (0.7683, 0.095),
        ),
        "reason": "XHS search page image-search entry is the camera icon in the search box",
    },
    "album_entry": {
        "hint": "xhs_camera_page_album_expand",
        "ratio": (0.925, 0.8468),
        "fallback_ratios": (
            (0.9, 0.8468),
            (0.95, 0.8468),
            (0.925, 0.825),
            (0.925, 0.87),
        ),
        "reason": "XHS image-search camera page opens the album grid via the bottom-right expand button",
    },
    "first_album_image": {
        "hint": "expanded_album_grid_first_tile",
        "ratio": (0.125, 0.1948),
        "fallback_ratios": (
            (0.17, 0.24),
            (0.125, 0.24),
            (0.17, 0.1948),
            (0.3, 0.1948),
        ),
        "reason": "Expanded XHS album picker usually places the newest image in the top-left grid tile",
    },
    "album_confirm": {
        "hint": "album_picker_bottom_right_confirm",
        "ratio": (0.88, 0.965),
        "fallback_ratios": (
            (0.8958, 0.9682),
            (0.92, 0.965),
            (0.88, 0.94),
            (0.92, 0.94),
        ),
        "reason": "XHS album picker confirmation is usually in the bottom-right corner after selecting an image",
    },
    "results_panel_swipe_start": {
        "hint": "image_search_results_panel_bottom",
        "ratio": (0.5, 0.82),
        "reason": "Start near the lower results panel and swipe upward to fullscreen the result list",
    },
    "results_panel_swipe_end": {
        "hint": "image_search_results_panel_top",
        "ratio": (0.5, 0.18),
        "reason": "End near the upper screen to expand the result list",
    },
    "result_card_1": {
        "hint": "fullscreen_results_first_card",
        "ratio": (0.25, 0.3),
        "reason": "First visible result card in the expanded two-column result list",
    },
    "result_card_2": {
        "hint": "fullscreen_results_second_card",
        "ratio": (0.75, 0.3),
        "reason": "Second visible result card in the expanded two-column result list",
    },
    "result_card_3": {
        "hint": "fullscreen_results_third_card",
        "ratio": (0.25, 0.58),
        "reason": "Third visible result card in the expanded two-column result list",
    },
    "note_main_image": {
        "hint": "note_detail_main_image",
        "ratio": (0.5, 0.4),
        "reason": "Main image area in an opened XHS note detail page",
    },
    "keyword_search_box": {
        "hint": "search_results_top_search_box",
        "ratio": (0.12, 0.08),
        "reason": "Search results pages usually keep the query input at the top",
    },
    "keyword_search_submit": {
        "hint": "search_results_top_submit",
        "ratio": (0.88, 0.08),
        "reason": "Search submit action is usually on the right side of the top input",
    },
    "save_image_menu_item": {
        "hint": "save_image_bottom_sheet_item",
        "ratio": (0.5, 0.82),
        "reason": "Save image action in the bottom menu after long-pressing a note image",
    },
    "note_back_button": {
        "hint": "note_detail_back_button",
        "ratio": (0.06, 0.07),
        "reason": "Back button in the top-left of a note detail page",
    },
}
POINT_VERIFICATION_TEXTS = {
    "search_box": (
        "取消",
        "搜索历史",
        "综合",
        "用户",
        "商品",
        "搜索小红书",
        "search_edit",
        "searchEdit",
        "android.widget.EditText",
        "EditText",
    ),
    "image_search_button": (
        "相册",
        "最近项目",
        "全部照片",
        "照片",
        "图片",
        "选择",
        "允许访问",
        "android.widget.GridView",
        "RecyclerView",
        "album",
        "gallery",
    ),
    "album_entry": (
        "最近项目",
        "全部照片",
        "照片",
        "图片",
        "选择",
        "完成",
        "android.widget.GridView",
        "RecyclerView",
        "album",
        "gallery",
    ),
    "first_album_image": (
        "完成",
        "确定",
        "确认",
        "下一步",
        "使用",
        "已选择",
        "done",
        "ok",
        "confirm",
        "next",
    ),
    "album_confirm": (
        "图搜",
        "结果",
        "相关",
        "相似",
        "笔记",
        "搜索",
        "loading",
        "result",
    ),
    "save_image_menu_item": (
        "保存图片",
        "保存到相册",
        "保存",
        "save",
    ),
    "keyword_search_box": (
        "搜索",
        "搜索小红书",
        "android.widget.EditText",
        "EditText",
        "search_edit",
        "searchEdit",
    ),
    "keyword_search_submit": (
        "搜索",
        "确定",
        "完成",
        "search",
    ),
}
DEFAULT_FLOW_POINTS = [
    "search_box",
    "image_search_button",
    "album_entry",
    "first_album_image",
    "album_confirm",
    "results_anchor",
    "results_panel_swipe_start",
    "results_panel_swipe_end",
    "result_card_1",
    "result_card_2",
    "result_card_3",
    "note_main_image",
    "keyword_search_box",
    "keyword_search_submit",
    "save_image_menu_item",
    "note_back_button",
]


def find_point_ratio(
    point_name: str, hierarchy: str, window_size: tuple[int, int]
) -> tuple[float, float] | None:
    _validate_point_name(point_name)
    pattern = POINT_PATTERNS.get(point_name)
    if pattern is None:
        return None
    return _find_ratio_by_pattern(pattern, hierarchy, window_size)


def find_search_box_ratio(
    hierarchy: str, window_size: tuple[int, int]
) -> tuple[float, float] | None:
    return find_point_ratio("search_box", hierarchy, window_size)


def build_point_suggestion(
    point_name: str, preview: dict[str, Any], window_size: tuple[int, int]
) -> dict[str, Any]:
    _validate_point_name(point_name)
    visual_hint = VISUAL_HINTS.get(point_name)
    if visual_hint is not None:
        ratio = visual_hint["ratio"]
        pixel = _ratio_to_pixel(ratio, window_size)
        suggestion = {
            "status": "ok",
            "point": point_name,
            "source": "visual_hint",
            "hint": visual_hint["hint"],
            "reason": visual_hint["reason"],
            point_name: list(ratio),
            "pixel": list(pixel),
            "grid": preview["grid"],
        }
        if preview["status"] == "ok":
            suggestion["secondary"] = _suggestion_from_preview(
                point_name, preview, window_size
            )
        return suggestion
    if preview["status"] == "ok":
        return _suggestion_from_preview(point_name, preview, window_size)
    return preview


def _find_ratio_by_pattern(
    pattern: re.Pattern[str], hierarchy: str, window_size: tuple[int, int]
) -> tuple[float, float] | None:
    width, height = window_size
    for node in pattern.findall(hierarchy):
        match = BOUNDS_RE.search(node)
        if not match:
            continue
        left, top, right, bottom = (int(value) for value in match.groups())
        center_x = (left + right) / 2
        center_y = (top + bottom) / 2
        return round(center_x / width, 4), round(center_y / height, 4)
    return None


def calibrate_point(
    *,
    point_name: str,
    device,
    profile_path: Path,
    output_dir: Path,
    xhs_package: str,
    pixel_x: int | None = None,
    pixel_y: int | None = None,
    click: bool = True,
    start_app: bool = False,
    wait_seconds: float = 2.0,
    sleep_func: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    _validate_point_name(point_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    if start_app:
        device.start_app(xhs_package)
        _sleep_if_needed(wait_seconds, sleep_func)
    screenshot_path = output_dir / f"{point_name}.png"
    screenshot_path.write_bytes(device.screenshot())
    grid_path = output_dir / f"{point_name}_grid.png"
    _write_grid_image(screenshot_path, grid_path)

    window_size = device.window_size()
    source = "pixel"
    if pixel_x is not None and pixel_y is not None:
        ratio = (
            round(pixel_x / window_size[0], 4),
            round(pixel_y / window_size[1], 4),
        )
    else:
        ratio = find_point_ratio(point_name, device.dump_hierarchy(), window_size)
        source = "ui_hierarchy"

    if ratio is None:
        return {
            "status": "needs_manual_point",
            "point": point_name,
            "screenshot": str(screenshot_path),
            "grid": str(grid_path),
            "message": f"{point_name} was not found in UI hierarchy; rerun with --x and --y",
        }

    profile = CoordinateProfile.load(profile_path)
    points = dict(profile.points)
    points[point_name] = ratio
    CoordinateProfile(points=points).write(profile_path)
    if click:
        device.click_ratio(*ratio)
    return {
        "status": "ok",
        "point": point_name,
        "source": source,
        point_name: list(ratio),
        "coordinate_profile": str(profile_path),
        "screenshot": str(screenshot_path),
        "grid": str(grid_path),
    }


def calibrate_search_box(
    *,
    device,
    profile_path: Path,
    output_dir: Path,
    xhs_package: str,
    pixel_x: int | None = None,
    pixel_y: int | None = None,
    click: bool = True,
    wait_seconds: float = 2.0,
    sleep_func: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    return calibrate_point(
        point_name="search_box",
        device=device,
        profile_path=profile_path,
        output_dir=output_dir,
        xhs_package=xhs_package,
        pixel_x=pixel_x,
        pixel_y=pixel_y,
        click=click,
        start_app=True,
        wait_seconds=wait_seconds,
        sleep_func=sleep_func,
    )


def calibrate_point_on_device(
    *,
    point_name: str,
    profile_path: Path,
    output_dir: Path,
    xhs_package: str,
    device_serial: str | None,
    pixel_x: int | None = None,
    pixel_y: int | None = None,
    click: bool = True,
    start_app: bool = False,
    wait_seconds: float = 2.0,
) -> dict[str, Any]:
    return calibrate_point(
        point_name=point_name,
        device=DeterministicDevice.connect(device_serial),
        profile_path=profile_path,
        output_dir=output_dir,
        xhs_package=xhs_package,
        pixel_x=pixel_x,
        pixel_y=pixel_y,
        click=click,
        start_app=start_app,
        wait_seconds=wait_seconds,
    )


def calibrate_search_box_on_device(
    *,
    profile_path: Path,
    output_dir: Path,
    xhs_package: str,
    device_serial: str | None,
    pixel_x: int | None = None,
    pixel_y: int | None = None,
    click: bool = True,
    wait_seconds: float = 2.0,
) -> dict[str, Any]:
    return calibrate_point_on_device(
        point_name="search_box",
        profile_path=profile_path,
        output_dir=output_dir,
        xhs_package=xhs_package,
        device_serial=device_serial,
        pixel_x=pixel_x,
        pixel_y=pixel_y,
        click=click,
        start_app=True,
        wait_seconds=wait_seconds,
    )


def calibrate_flow(
    *,
    device,
    profile_path: Path,
    output_dir: Path,
    xhs_package: str,
    points: Sequence[str] = DEFAULT_FLOW_POINTS,
    input_func: Callable[[str], str] = input,
    output_func: Callable[[str], None] = print,
    before_point: Callable[[str], None] | None = None,
    wait_seconds: float = 2.0,
    sleep_func: Callable[[float], None] = time.sleep,
    start_app: bool = True,
) -> dict[str, Any]:
    completed: list[dict[str, Any]] = []
    if start_app:
        device.start_app(xhs_package)
        _sleep_if_needed(wait_seconds, sleep_func)
    for point_name in points:
        _validate_point_name(point_name)
        if before_point:
            before_point(point_name)
        step_dir = output_dir / point_name
        preview = calibrate_point(
            point_name=point_name,
            device=device,
            profile_path=profile_path,
            output_dir=step_dir,
            xhs_package=xhs_package,
            click=False,
            start_app=False,
        )
        suggestion = build_point_suggestion(point_name, preview, device.window_size())
        output_func(_format_flow_prompt(point_name, suggestion))
        answer = input_func(f"{point_name}> ").strip()
        if answer.lower() in {"q", "quit", "exit"}:
            return {"status": "aborted", "completed": completed, "point": point_name}
        if answer:
            pixel_x, pixel_y = _parse_pixel_answer(answer)
            result = calibrate_point(
                point_name=point_name,
                device=device,
                profile_path=profile_path,
                output_dir=step_dir,
                xhs_package=xhs_package,
                pixel_x=pixel_x,
                pixel_y=pixel_y,
                click=True,
                start_app=False,
            )
        elif suggestion["status"] == "ok":
            ratio = tuple(suggestion[point_name])
            profile = CoordinateProfile.load(profile_path)
            points_by_name = dict(profile.points)
            points_by_name[point_name] = ratio
            CoordinateProfile(points=points_by_name).write(profile_path)
            device.click_ratio(*ratio)
            result = suggestion
        else:
            output_func(f"{point_name}: manual x,y is required")
            return {
                "status": "needs_manual_point",
                "completed": completed,
                "point": point_name,
                "preview": suggestion,
            }
        result = _verify_or_retry_flow_point(
            point_name=point_name,
            result=result,
            device=device,
            profile_path=profile_path,
            step_dir=step_dir,
            wait_seconds=wait_seconds,
            sleep_func=sleep_func,
            output_func=output_func,
        )
        if result["status"] == "verification_failed":
            return {
                "status": "verification_failed",
                "completed": completed,
                "point": point_name,
                "result": result,
            }
        completed.append(result)
        if not _point_needs_verification(point_name):
            _sleep_if_needed(wait_seconds, sleep_func)
    return {"status": "completed", "completed": completed}


def calibrate_flow_on_device(
    *,
    profile_path: Path,
    output_dir: Path,
    xhs_package: str,
    device_serial: str | None,
    points: Sequence[str] = DEFAULT_FLOW_POINTS,
    wait_seconds: float = 2.0,
    start_app: bool = True,
) -> dict[str, Any]:
    return calibrate_flow(
        device=DeterministicDevice.connect(device_serial),
        profile_path=profile_path,
        output_dir=output_dir,
        xhs_package=xhs_package,
        points=points,
        wait_seconds=wait_seconds,
        start_app=start_app,
    )


def _sleep_if_needed(
    wait_seconds: float, sleep_func: Callable[[float], None] = time.sleep
) -> None:
    if wait_seconds > 0:
        sleep_func(wait_seconds)


def _verify_or_retry_flow_point(
    *,
    point_name: str,
    result: dict[str, Any],
    device,
    profile_path: Path,
    step_dir: Path,
    wait_seconds: float,
    sleep_func: Callable[[float], None],
    output_func: Callable[[str], None],
) -> dict[str, Any]:
    if not _point_needs_verification(point_name):
        return result
    _sleep_if_needed(wait_seconds, sleep_func)
    hierarchy = device.dump_hierarchy()
    _write_verification_hierarchy(step_dir, point_name, hierarchy)
    if _point_verification_passed(point_name, hierarchy):
        result["verified"] = True
        return result
    for fallback_ratio in _fallback_ratios_for_point(point_name):
        if list(fallback_ratio) == result.get(point_name):
            continue
        pixel = _ratio_to_pixel(fallback_ratio, device.window_size())
        output_func(
            f"{point_name}: verification did not pass; trying fallback "
            f"{pixel[0]},{pixel[1]}"
        )
        device.click_ratio(*fallback_ratio)
        _sleep_if_needed(wait_seconds, sleep_func)
        hierarchy = device.dump_hierarchy()
        _write_verification_hierarchy(step_dir, point_name, hierarchy)
        if _point_verification_passed(point_name, hierarchy):
            profile = CoordinateProfile.load(profile_path)
            points_by_name = dict(profile.points)
            points_by_name[point_name] = fallback_ratio
            CoordinateProfile(points=points_by_name).write(profile_path)
            return {
                "status": "ok",
                "point": point_name,
                "source": "visual_hint_fallback",
                "hint": VISUAL_HINTS[point_name]["hint"],
                point_name: list(fallback_ratio),
                "pixel": list(pixel),
                "verified": True,
            }
    return {
        **result,
        "status": "verification_failed",
        "verified": False,
        "message": f"{point_name} click did not reach the expected page",
    }


def _point_needs_verification(point_name: str) -> bool:
    return point_name in POINT_VERIFICATION_TEXTS


def _point_verification_passed(point_name: str, hierarchy: str) -> bool:
    return any(token in hierarchy for token in POINT_VERIFICATION_TEXTS[point_name])


def _fallback_ratios_for_point(point_name: str) -> tuple[tuple[float, float], ...]:
    hint = VISUAL_HINTS.get(point_name)
    if hint is None:
        return ()
    return hint.get("fallback_ratios", ())


def _write_verification_hierarchy(
    step_dir: Path, point_name: str, hierarchy: str
) -> None:
    step_dir.mkdir(parents=True, exist_ok=True)
    (step_dir / f"{point_name}_after_click.xml").write_text(
        hierarchy, encoding="utf-8"
    )


def _validate_point_name(point_name: str) -> None:
    if point_name not in SUPPORTED_POINTS:
        raise ValueError(f"unsupported calibration point: {point_name}")


def _parse_pixel_answer(answer: str) -> tuple[int, int]:
    parts = [part.strip() for part in answer.replace("，", ",").split(",")]
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError("manual point must be formatted as x,y")
    return int(parts[0]), int(parts[1])


def _format_flow_prompt(point_name: str, preview: dict[str, Any]) -> str:
    if preview["status"] == "ok":
        pixel = preview.get("pixel")
        source = preview["source"]
        source_label = f"{source} {preview['hint']}" if "hint" in preview else source
        lines = [
            f"{point_name}:",
            f"Recommended: {pixel[0]},{pixel[1]} from {source_label}",
        ]
        secondary = preview.get("secondary")
        if secondary is not None:
            secondary_pixel = secondary["pixel"]
            lines.append(
                f"Secondary UI candidate: {secondary_pixel[0]},{secondary_pixel[1]} "
                f"from {secondary['source']}"
            )
        lines.extend(
            [
                f"Grid: {preview['grid']}",
                "Press Enter to accept recommended, type x,y to override, or q to quit.",
            ]
        )
        return "\n".join(lines)
    return (
        f"{point_name}: no candidate found. Type x,y to set manually, or q to quit. "
        f"Grid: {preview['grid']}"
    )


def _suggestion_from_preview(
    point_name: str, preview: dict[str, Any], window_size: tuple[int, int]
) -> dict[str, Any]:
    ratio = tuple(preview[point_name])
    return {
        "status": "ok",
        "point": point_name,
        "source": preview["source"],
        point_name: list(ratio),
        "pixel": list(_ratio_to_pixel(ratio, window_size)),
        "grid": preview["grid"],
    }


def _ratio_to_pixel(
    ratio: tuple[float, float] | list[float], window_size: tuple[int, int]
) -> tuple[int, int]:
    width, height = window_size
    return round(width * ratio[0]), round(height * ratio[1])


def _write_grid_image(source_path: Path, target_path: Path) -> None:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        target_path.write_bytes(source_path.read_bytes())
        return
    try:
        image = Image.open(source_path).convert("RGB")
        width, height = image.size
        draw = ImageDraw.Draw(image)
        for index in range(1, 10):
            x = round(width * index / 10)
            y = round(height * index / 10)
            draw.line((x, 0, x, height), fill=(255, 0, 0), width=2)
            draw.text((x + 4, 8), f"x={index / 10:.1f}", fill=(255, 0, 0))
            draw.line((0, y, width, y), fill=(255, 0, 0), width=2)
            draw.text((8, y + 4), f"y={index / 10:.1f}", fill=(255, 0, 0))
        image.save(target_path)
    except Exception:
        target_path.write_bytes(source_path.read_bytes())
