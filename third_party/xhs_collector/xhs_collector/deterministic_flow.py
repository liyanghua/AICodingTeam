from __future__ import annotations

import hashlib
import html
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

from .artifacts import append_jsonl
from .deterministic_device import CoordinateProfile, DOWNLOAD_POINTS, DeterministicDevice
from .media_store import SyncMediaStore, diff_new_media
from .models import CollectedImage, InputItem, ItemResult
from .template_matcher import TemplateMatcher

RISK_TEXTS = {
    "login_required": ["登录", "手机号", "验证码登录"],
    "captcha_required": ["验证码", "滑块", "安全验证"],
    "risk_control": ["风险", "异常", "违规"],
    "permission_prompt": ["允许访问", "照片和视频", "权限"],
}
ALBUM_GRID_MARKERS = ("全部照片", "收起", "RecyclerView", "GridView")
HOME_PAGE_MARKERS = ("首页", "发现", "关注", "推荐")
SEARCH_PAGE_MARKERS = (
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
)
IMAGE_ANALYSIS_MARKERS = (
    "输入关于图片的问题",
    "图片分析中",
    "试试单击图片任意位置搜索",
)
ALBUM_CONFIRM_MARKERS = ("完成", "确定", "确认", "下一步", "使用", "done", "ok", "next")
RESULT_PAGE_MARKERS = ("图搜", "结果", "相关", "相似", "笔记", "搜索", "result")
NOTE_DETAIL_MARKERS = ("评论", "说点什么", "点赞", "收藏", "分享", "关注")
KEYWORD_SEARCH_MARKERS = ("AI回答", "AI 回答", "笔记", "搜索结果", "综合", "相关")
SAVE_MENU_MARKERS = ("保存图片", "保存到相册", "保存")
DOWNLOAD_PERMISSION_DISABLED_MARKERS = (
    "作者已关闭下载权限",
    "作者已关闭下载",
    "关闭下载权限",
    "不允许保存",
    "无法保存",
    "保存失败",
    "禁止保存",
    "不可保存",
    "下载权限",
)
BACK_BUTTON_TEXTS = ("<", "‹", "←")
BACK_BUTTON_MARKERS = ("返回上一页", "返回", "关闭", "back", "close")
KEYWORD_SEARCH_BOX_CLASSES = ("EditText", "SearchView")
BOUNDS_RE = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')


class DeterministicRiskError(RuntimeError):
    def __init__(self, event: str, item_id: str) -> None:
        super().__init__(event)
        self.event = event
        self.item_id = item_id


def detect_risk_text(ui_text: str) -> str | None:
    if _download_permission_hint(ui_text):
        return None
    for event, keywords in RISK_TEXTS.items():
        if any(keyword in ui_text for keyword in keywords):
            return event
    return None


def run_deterministic_item(
    item: InputItem,
    device,
    media_store,
    profile: CoordinateProfile,
    output_item_dir: Path,
    output_dir: Path,
    xhs_package: str,
    remote_image_dir: str,
    throttle_seconds: float,
    app_start_wait_seconds: float | None = None,
    on_after_save: Callable[[], None] | None = None,
    template_matcher=None,
    template_dir: Path | None = None,
    save_poll_seconds: float = 10.0,
    subject_recognition_wait_seconds: float = 5.0,
    max_result_scrolls: int = 5,
    image_top_n: int | None = None,
    keyword_top_n: int = 3,
    keyword_result_top_n: int | None = None,
    target_category: str = "",
    target_category_keywords: list[str] | tuple[str, ...] | None = None,
    sleep_func: Callable[[float], None] = time.sleep,
) -> ItemResult:
    step_count = 0
    template_hits: list[dict] = []
    images: list[CollectedImage] = []
    rank_failures: list[dict] = []
    image_target_count = item.top_n if image_top_n is None else image_top_n
    keyword_target_count = (
        item.top_n if keyword_result_top_n is None else keyword_result_top_n
    )

    def step(name: str, payload: dict | None = None) -> None:
        nonlocal step_count
        step_count += 1
        append_jsonl(
            output_dir / "step_events.jsonl",
            {"step": step_count, "name": name, "item_id": item.item_id, **(payload or {})},
        )
        save_debug = getattr(device, "save_debug_artifacts", None)
        if save_debug is not None:
            save_debug(output_dir, f"{item.item_id}_{step_count:03d}_{name}")

    def tap_profile(point_name: str, event_name: str, payload: dict | None = None) -> None:
        try:
            device.click_ratio(*profile.point(point_name))
            step(event_name, payload)
        except Exception as exc:
            hit = _tap_template_fallback(
                device=device,
                matcher=template_matcher,
                template_dir=template_dir,
                output_dir=output_dir,
                item_id=item.item_id,
                template_name=point_name,
                event_name=event_name,
                reason=str(exc),
            )
            if hit is None:
                raise
            template_hits.append(hit)
            step(event_name, {**(payload or {}), "template_hit": hit})

    device.start_app(xhs_package)
    step("start_app", {"package": xhs_package})
    start_settle_seconds = (
        throttle_seconds
        if app_start_wait_seconds is None
        else max(throttle_seconds, app_start_wait_seconds)
    )
    if start_settle_seconds:
        sleep_func(start_settle_seconds)
        step("wait_app_start_settle", {"seconds": start_settle_seconds})
    risk = detect_risk_text(device.dump_hierarchy())
    if risk:
        return ItemResult(
            item_id=item.item_id,
            keyword=item.keyword,
            status="failed",
            keyword_candidates=item.keyword_candidates,
            message=risk,
            risk_events=[{"event": risk, "item_id": item.item_id}],
            step_count=step_count,
        )

    remote_reference = device.push_reference_image(
        item.reference_image, item.item_id, remote_image_dir
    )
    step("push_reference", {"remote_reference": remote_reference})
    media_scan_wait_seconds = min(1.0, save_poll_seconds) if save_poll_seconds else 0
    if media_scan_wait_seconds:
        sleep_func(media_scan_wait_seconds)
    step("wait_reference_media_scanned", {"seconds": media_scan_wait_seconds})

    if not _tap_search_box_until_search_page(
        device=device,
        profile=profile,
        xhs_package=xhs_package,
        timeout_seconds=save_poll_seconds,
        sleep_func=sleep_func,
        item_id=item.item_id,
        tap_profile=tap_profile,
        step=step,
    ):
        return _failed_item(
            item=item,
            message="search_page_not_reached_after_retries",
            event="search_page_not_reached_after_retries",
            step_count=step_count,
            template_hits=template_hits,
        )

    for point_name in ("image_search_button", "album_entry"):
        tap_profile(point_name, f"tap_{point_name}")

    album_image_targets = _wait_for_album_thumbnail_targets(
        device=device,
        profile=profile,
        timeout_seconds=save_poll_seconds,
        sleep_func=sleep_func,
        item_id=item.item_id,
        limit=3,
    )
    if not album_image_targets:
        hierarchy = device.dump_hierarchy()
        has_album_grid = _hierarchy_has_marker_group(
            "album_grid", ALBUM_GRID_MARKERS, hierarchy
        )
        event_name = "album_thumbnail_not_found" if has_album_grid else "album_grid_not_ready"
        step(
            event_name,
            {
                "expected_markers": list(ALBUM_GRID_MARKERS),
                "message": (
                    "album thumbnail candidate not found"
                    if has_album_grid
                    else "album grid not ready"
                ),
            },
        )
        return _failed_item(
            item=item,
            message=event_name,
            event=event_name,
            step_count=step_count,
            template_hits=template_hits,
        )

    image_state = None
    attempted_album_targets: list[dict] = []
    attempted_signatures: set[str] = set()
    for attempt_index, album_image_target in enumerate(album_image_targets, start=1):
        if attempt_index > 3:
            break
        _click_target(device, album_image_target)
        attempt_payload = {
            "attempt": attempt_index,
            "click_source": album_image_target["click_source"],
            "point": album_image_target["point"],
            "click_point": album_image_target.get("click_point"),
            "album_image_bounds": album_image_target.get("bounds"),
        }
        attempted_album_targets.append(
            {
                "attempt": attempt_index,
                "click_source": album_image_target["click_source"],
                "point": album_image_target["point"],
                "click_point": album_image_target.get("click_point"),
                "bounds": album_image_target.get("bounds"),
            }
        )
        attempted_signatures.add(_album_target_signature(album_image_target))
        step("tap_first_album_image", attempt_payload)
        image_state = _wait_for_first_match(
            device=device,
            marker_groups={
                "image_analysis": IMAGE_ANALYSIS_MARKERS,
                "album_confirm": ALBUM_CONFIRM_MARKERS,
            },
            timeout_seconds=save_poll_seconds,
            sleep_func=sleep_func,
            item_id=item.item_id,
        )
        if image_state in {"image_analysis", "album_confirm"}:
            break
        hierarchy = device.dump_hierarchy()
        state = (
            "album_grid"
            if _hierarchy_has_marker_group("album_grid", ALBUM_GRID_MARKERS, hierarchy)
            else image_state or "timeout"
        )
        step(
            "album_thumbnail_candidate_not_selected",
            {
                **attempt_payload,
                "state": state,
                "message": "album thumbnail candidate click did not select reference image",
            },
        )
        if attempt_index < len(album_image_targets):
            continue
        refreshed_targets = _wait_for_album_thumbnail_targets(
            device=device,
            profile=profile,
            timeout_seconds=save_poll_seconds,
            sleep_func=sleep_func,
            item_id=item.item_id,
            limit=3,
        )
        for refreshed_target in refreshed_targets:
            signature = _album_target_signature(refreshed_target)
            if signature in attempted_signatures:
                continue
            album_image_targets.append(refreshed_target)
            break
    if image_state == "album_confirm":
        tap_profile("album_confirm", "tap_album_confirm")
        if not _wait_for_markers(
            device=device,
            markers=IMAGE_ANALYSIS_MARKERS + RESULT_PAGE_MARKERS,
            timeout_seconds=save_poll_seconds,
            sleep_func=sleep_func,
            item_id=item.item_id,
        ):
            step(
                "album_confirm_failed",
                {
                    "expected_markers": list(
                        IMAGE_ANALYSIS_MARKERS + RESULT_PAGE_MARKERS
                    )
                },
            )
            return _failed_item(
                item=item,
                message="album_confirm_failed",
                event="album_confirm_failed",
                step_count=step_count,
                template_hits=template_hits,
            )
    elif image_state != "image_analysis":
        hierarchy = device.dump_hierarchy()
        state = (
            "album_grid"
            if _hierarchy_has_marker_group("album_grid", ALBUM_GRID_MARKERS, hierarchy)
            else image_state or "timeout"
        )
        step(
            "album_thumbnail_candidates_exhausted",
            {
                "state": state,
                "attempted_candidates": attempted_album_targets,
                "candidate_count": len(attempted_album_targets),
                "message": "all album thumbnail candidates failed to select reference image",
            },
        )
        return _failed_item(
            item=item,
            message="album_thumbnail_candidates_exhausted",
            event="album_thumbnail_candidates_exhausted",
            step_count=step_count,
            template_hits=template_hits,
        )

    if throttle_seconds:
        sleep_func(throttle_seconds)
    step("wait_image_search_results", {"mode": "wait_only"})
    if not _wait_for_markers(
        device=device,
        markers=IMAGE_ANALYSIS_MARKERS + RESULT_PAGE_MARKERS,
        timeout_seconds=save_poll_seconds,
        sleep_func=sleep_func,
        item_id=item.item_id,
    ):
        step(
            "image_search_results_not_reached",
            {"expected_markers": list(IMAGE_ANALYSIS_MARKERS + RESULT_PAGE_MARKERS)},
        )
        return _failed_item(
            item=item,
            message="image_search_results_not_reached",
            event="image_search_results_not_reached",
            step_count=step_count,
            template_hits=template_hits,
        )

    if media_store is None:
        return ItemResult(
            item_id=item.item_id,
            keyword=item.keyword,
            status="completed",
            keyword_candidates=item.keyword_candidates,
            collected_count=0,
            images=images,
            message="image search results reached",
            step_count=step_count,
            template_hits=template_hits,
        )

    profile.require_points(DOWNLOAD_POINTS)
    _check_risk_or_raise(device, item.item_id)
    step("wait_subject_recognition", {"seconds": subject_recognition_wait_seconds})
    if subject_recognition_wait_seconds:
        sleep_func(subject_recognition_wait_seconds)
    _check_risk_or_raise(device, item.item_id)

    seen_image_hashes: set[str] = set()
    image_results, image_failures = _download_visible_note_results(
        stage="image_search",
        query="",
        filename_prefix="rank",
        target_count=image_target_count,
        item=item,
        device=device,
        media_store=media_store,
        profile=profile,
        output_item_dir=output_item_dir,
        save_poll_seconds=save_poll_seconds,
        sleep_func=sleep_func,
        on_after_save=on_after_save,
        max_result_scrolls=max_result_scrolls,
        seen_image_hashes=seen_image_hashes,
        target_category=target_category,
        target_category_keywords=target_category_keywords,
        step=step,
    )
    images.extend(image_results)
    rank_failures.extend(image_failures)

    keyword_queries = _keyword_queries(item, keyword_top_n)
    image_stage_blocked = any(
        failure.get("event") == "result_list_not_restored_after_back"
        for failure in image_failures
    )
    if keyword_queries:
        if not image_stage_blocked:
            if image_failures:
                step(
                    "continue_keyword_search_after_image_download_failures",
                    {
                        "event": "continue_keyword_search_after_image_download_failures",
                        "item_id": item.item_id,
                        "query": keyword_queries[0],
                        "image_downloaded_count": len(image_results),
                        "image_failure_count": len(image_failures),
                    },
                )
            total_keyword_queries = len(keyword_queries)
            for keyword_index, keyword_query in enumerate(keyword_queries, start=1):
                filename_prefix = (
                    "keyword_rank"
                    if total_keyword_queries == 1
                    else f"keyword_{keyword_index:03d}_rank"
                )
                step(
                    "start_keyword_search_query",
                    {
                        "keyword_index": keyword_index,
                        "query": keyword_query,
                        "filename_prefix": filename_prefix,
                    },
                )
                keyword_started = _perform_keyword_search(
                    query=keyword_query,
                    item=item,
                    device=device,
                    profile=profile,
                    save_poll_seconds=save_poll_seconds,
                    sleep_func=sleep_func,
                    step=step,
                )
                if not keyword_started:
                    failure = {
                        "event": "keyword_search_failed",
                        "item_id": item.item_id,
                        "query": keyword_query,
                        "keyword_index": keyword_index,
                    }
                    rank_failures.append(failure)
                    step("skip_keyword_query_due_to_blocked_state", failure)
                    break
                keyword_results, keyword_failures = _download_visible_note_results(
                    stage="keyword_search",
                    query=keyword_query,
                    filename_prefix=filename_prefix,
                    target_count=keyword_target_count,
                    item=item,
                    device=device,
                    media_store=media_store,
                    profile=profile,
                    output_item_dir=output_item_dir,
                    save_poll_seconds=save_poll_seconds,
                    sleep_func=sleep_func,
                    on_after_save=on_after_save,
                    max_result_scrolls=max_result_scrolls,
                    seen_image_hashes=seen_image_hashes,
                    keyword_index=keyword_index,
                    target_category=target_category,
                    target_category_keywords=target_category_keywords,
                    step=step,
                )
                images.extend(keyword_results)
                rank_failures.extend(keyword_failures)
                keyword_stage_blocked = any(
                    failure.get("event") == "result_list_not_restored_after_back"
                    for failure in keyword_failures
                )
                step(
                    "finish_keyword_search_query",
                    {
                        "keyword_index": keyword_index,
                        "query": keyword_query,
                        "filename_prefix": filename_prefix,
                        "downloaded_count": len(keyword_results),
                        "failure_count": len(keyword_failures),
                        "blocked": keyword_stage_blocked,
                    }
                )
                if keyword_stage_blocked:
                    if keyword_index < total_keyword_queries:
                        step(
                            "skip_keyword_query_due_to_blocked_state",
                            {
                                "event": "skip_keyword_query_due_to_blocked_state",
                                "item_id": item.item_id,
                                "keyword_index": keyword_index + 1,
                                "query": keyword_queries[keyword_index],
                                "blocked_by_keyword_index": keyword_index,
                            },
                        )
                    break
        elif image_stage_blocked:
            skip_event = {
                "event": "skip_keyword_search_due_to_result_list_not_restored",
                "item_id": item.item_id,
                "query": keyword_queries[0],
            }
            step("skip_keyword_search_due_to_result_list_not_restored", skip_event)
            rank_failures.append(skip_event)

    expected_count = image_target_count + keyword_target_count * len(keyword_queries)
    status = "completed" if len(images) >= expected_count else "partial"
    message = (
        f"downloaded {len(images)} of {expected_count} image search and keyword results"
        if expected_count
        else "image search results reached"
    )
    result = ItemResult(
        item_id=item.item_id,
        keyword=item.keyword,
        status=status,
        keyword_candidates=item.keyword_candidates,
        collected_count=len(images),
        images=images,
        message=message,
        risk_events=rank_failures,
        step_count=step_count,
        template_hits=template_hits,
    )
    return result


def run_deterministic_collect(
    *,
    items: list[InputItem],
    config,
    output_dir: Path,
    manifest,
    write_result: Callable[[ItemResult], None],
) -> None:
    profile = CoordinateProfile.load(config.deterministic.coordinate_profile)
    device = DeterministicDevice.connect(config.device_serial)
    media_store = SyncMediaStore(device.adb_device)
    template_matcher = TemplateMatcher(config.deterministic.match_threshold)
    for item in items:
        item_dir = output_dir / "items" / item.item_id
        try:
            result = run_deterministic_item(
                item=item,
                device=device,
                media_store=media_store,
                profile=profile,
                output_item_dir=item_dir,
                output_dir=output_dir,
                xhs_package=config.xhs_package,
                remote_image_dir=config.remote_image_dir,
                throttle_seconds=config.throttle_seconds,
                app_start_wait_seconds=config.deterministic.app_start_wait_seconds,
                template_matcher=template_matcher,
                template_dir=config.deterministic.template_dir,
                save_poll_seconds=config.deterministic.wait_timeout_seconds,
                subject_recognition_wait_seconds=(
                    config.deterministic.subject_recognition_wait_seconds
                ),
                max_result_scrolls=config.deterministic.max_result_scrolls,
                image_top_n=config.image_top_n,
                keyword_top_n=config.keyword_top_n,
                keyword_result_top_n=config.keyword_result_top_n,
                target_category=config.target_category,
                target_category_keywords=config.target_category_keywords,
            )
        except DeterministicRiskError as exc:
            result = ItemResult(
                item_id=item.item_id,
                keyword=item.keyword,
                status="failed",
                keyword_candidates=item.keyword_candidates,
                message=exc.event,
                risk_events=[{"event": exc.event, "item_id": exc.item_id}],
            )
        except Exception as exc:
            result = ItemResult(
                item_id=item.item_id,
                keyword=item.keyword,
                status="failed",
                keyword_candidates=item.keyword_candidates,
                message=str(exc),
                risk_events=[{"event": "deterministic_failed", "reason": str(exc)}],
            )
        write_result(result)


def _best_keyword_hit(candidates: list[str], ui_text: str) -> str:
    for candidate in candidates:
        if candidate and candidate in ui_text:
            return candidate
    return ""


def _keyword_queries(item: InputItem, keyword_top_n: int) -> list[str]:
    if keyword_top_n <= 0:
        return []
    candidates = item.keyword_candidates or [item.keyword]
    queries: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        query = " ".join(candidate.split())
        if not query or query in seen:
            continue
        seen.add(query)
        queries.append(query)
        if len(queries) >= keyword_top_n:
            break
    return queries


def _failed_item(
    *,
    item: InputItem,
    message: str,
    event: str,
    step_count: int,
    template_hits: list[dict],
) -> ItemResult:
    return ItemResult(
        item_id=item.item_id,
        keyword=item.keyword,
        status="failed",
        keyword_candidates=item.keyword_candidates,
        message=message,
        risk_events=[{"event": event, "item_id": item.item_id}],
        step_count=step_count,
        template_hits=template_hits,
    )


def _tap_search_box_until_search_page(
    *,
    device,
    profile: CoordinateProfile,
    xhs_package: str,
    timeout_seconds: float,
    sleep_func: Callable[[float], None],
    item_id: str,
    tap_profile: Callable[[str, str, dict | None], None],
    step: Callable[[str, dict | None], None],
    max_attempts: int = 3,
) -> bool:
    for attempt in range(1, max_attempts + 1):
        tap_profile("search_box", "tap_search_box", {"attempt": attempt})
        reached = _wait_for_search_page(
            device=device,
            timeout_seconds=timeout_seconds,
            sleep_func=sleep_func,
            item_id=item_id,
        )
        step(
            "wait_search_page_after_search_box",
            {
                "attempt": attempt,
                "reached": reached,
                "expected_markers": list(SEARCH_PAGE_MARKERS),
            },
        )
        if reached:
            return True
        step(
            "search_box_click_not_on_search_page",
            {
                "attempt": attempt,
                "max_attempts": max_attempts,
                "expected_markers": list(SEARCH_PAGE_MARKERS),
            },
        )
        if attempt >= max_attempts:
            break
        back_event = _recover_home_after_search_box_miss(
            device=device,
            xhs_package=xhs_package,
            timeout_seconds=timeout_seconds,
            sleep_func=sleep_func,
            item_id=item_id,
        )
        step(
            "back_after_search_box_miss",
            {
                "attempt": attempt,
                **back_event,
            },
        )
    step(
        "search_page_not_reached_after_retries",
        {
            "attempts": max_attempts,
            "expected_markers": list(SEARCH_PAGE_MARKERS),
        },
    )
    return False


def _wait_for_search_page(
    *,
    device,
    timeout_seconds: float,
    sleep_func: Callable[[float], None],
    item_id: str,
) -> bool:
    return _wait_for_markers(
        device=device,
        markers=SEARCH_PAGE_MARKERS,
        timeout_seconds=timeout_seconds,
        sleep_func=sleep_func,
        item_id=item_id,
    )


def _recover_home_after_search_box_miss(
    *,
    device,
    xhs_package: str,
    timeout_seconds: float,
    sleep_func: Callable[[float], None],
    item_id: str,
) -> dict:
    press_back = getattr(device, "press_back", None)
    if press_back is not None:
        press_back()
        back_source = "press_back"
    else:
        device.start_app(xhs_package)
        back_source = "start_app"
    wait_seconds = min(1.0, timeout_seconds) if timeout_seconds else 0
    home_reached = False
    if wait_seconds:
        home_reached = _wait_for_home_page(
            device=device,
            timeout_seconds=wait_seconds,
            sleep_func=sleep_func,
            item_id=item_id,
        )
    return {
        "back_source": back_source,
        "wait_seconds": wait_seconds,
        "home_reached": home_reached,
    }


def _wait_for_home_page(
    *,
    device,
    timeout_seconds: float,
    sleep_func: Callable[[float], None],
    item_id: str,
) -> bool:
    return _wait_for_markers(
        device=device,
        markers=HOME_PAGE_MARKERS,
        timeout_seconds=timeout_seconds,
        sleep_func=sleep_func,
        item_id=item_id,
    )


def _wait_for_markers(
    *,
    device,
    markers: tuple[str, ...],
    timeout_seconds: float,
    sleep_func: Callable[[float], None],
    item_id: str,
) -> bool:
    return (
        _wait_for_first_match(
            device=device,
            marker_groups={"target": markers},
            timeout_seconds=timeout_seconds,
            sleep_func=sleep_func,
            item_id=item_id,
        )
        == "target"
    )


def _wait_for_first_match(
    *,
    device,
    marker_groups: dict[str, tuple[str, ...]],
    timeout_seconds: float,
    sleep_func: Callable[[float], None],
    item_id: str,
) -> str | None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        hierarchy = device.dump_hierarchy()
        for name, markers in marker_groups.items():
            if _hierarchy_has_marker_group(name, markers, hierarchy):
                return name
        risk = detect_risk_text(hierarchy)
        if risk:
            raise DeterministicRiskError(risk, item_id)
        if timeout_seconds <= 0 or time.monotonic() >= deadline:
            return None
        sleep_func(min(0.5, timeout_seconds))


def _hierarchy_has_marker_group(
    group_name: str, markers: tuple[str, ...], hierarchy: str
) -> bool:
    if group_name == "album_confirm":
        return _hierarchy_has_album_confirm_marker(hierarchy)
    return any(marker in hierarchy for marker in markers)


def _hierarchy_has_album_confirm_marker(hierarchy: str) -> bool:
    labels = _non_system_ui_labels(hierarchy)
    if not labels:
        return any(marker in hierarchy for marker in ALBUM_CONFIRM_MARKERS)
    for label in labels:
        normalized = " ".join(label.strip().split())
        lower = normalized.lower()
        if normalized in {"完成", "确定", "确认", "下一步", "使用"}:
            return True
        if any(text in normalized for text in ("使用照片", "使用图片")):
            return True
        if lower in {"done", "ok", "next", "use"}:
            return True
    return False


def _non_system_ui_labels(hierarchy: str) -> list[str]:
    if "<" not in hierarchy:
        return []
    try:
        root = ET.fromstring(hierarchy)
    except ET.ParseError:
        return []
    labels: list[str] = []
    for node in root.iter():
        if node.attrib.get("package") == "com.android.systemui":
            continue
        for key in ("text", "content-desc", "hint"):
            value = node.attrib.get(key, "").strip()
            if value:
                labels.append(value)
    return labels


def _wait_for_album_thumbnail_target(
    *,
    device,
    profile: CoordinateProfile,
    timeout_seconds: float,
    sleep_func: Callable[[float], None],
    item_id: str,
) -> dict | None:
    targets = _wait_for_album_thumbnail_targets(
        device=device,
        profile=profile,
        timeout_seconds=timeout_seconds,
        sleep_func=sleep_func,
        item_id=item_id,
        limit=1,
    )
    return targets[0] if targets else None


def _wait_for_album_thumbnail_targets(
    *,
    device,
    profile: CoordinateProfile,
    timeout_seconds: float,
    sleep_func: Callable[[float], None],
    item_id: str,
    limit: int = 3,
) -> list[dict]:
    deadline = time.monotonic() + timeout_seconds
    window_size = getattr(device, "window_size", None)
    saw_album_grid = False
    while True:
        hierarchy = device.dump_hierarchy()
        has_album_grid = _hierarchy_has_marker_group(
            "album_grid", ALBUM_GRID_MARKERS, hierarchy
        )
        saw_album_grid = saw_album_grid or has_album_grid
        if window_size is not None:
            targets = _find_album_thumbnail_targets(hierarchy, window_size(), limit=limit)
            if targets:
                return targets
        elif has_album_grid:
            return [_coordinate_profile_album_thumbnail_target(profile)]
        risk = detect_risk_text(hierarchy)
        if risk:
            raise DeterministicRiskError(risk, item_id)
        if timeout_seconds <= 0 or time.monotonic() >= deadline:
            if saw_album_grid:
                return [_coordinate_profile_album_thumbnail_target(profile)]
            return []
        sleep_func(min(0.5, timeout_seconds))


def _album_target_signature(target: dict) -> str:
    bounds = target.get("bounds")
    if bounds:
        return "bounds:" + ",".join(str(value) for value in bounds)
    return "point:" + ",".join(str(value) for value in target.get("point", []))


def _coordinate_profile_album_thumbnail_target(profile: CoordinateProfile) -> dict:
    point = profile.point("first_album_image")
    return {
        "click_source": "coordinate_profile",
        "click_point": None,
        "point": [round(point[0], 4), round(point[1], 4)],
        "bounds": None,
        "matched_marker": "first_album_image",
    }


def _find_album_thumbnail_target(
    hierarchy: str, window_size: tuple[int, int]
) -> dict | None:
    targets = _find_album_thumbnail_targets(hierarchy, window_size, limit=1)
    return targets[0] if targets else None


def _find_album_thumbnail_targets(
    hierarchy: str, window_size: tuple[int, int], limit: int = 3
) -> list[dict]:
    width, height = window_size
    if width <= 0 or height <= 0:
        return []
    candidates: list[list[int]] = []
    min_side = max(160, round(min(width, height) * 0.12))
    max_top_control_bottom = height * 0.16
    for node in re.findall(r"<node\b[^>]*(?:/?>)", hierarchy):
        if _node_attr(node, "package") != "com.xingin.xhs":
            continue
        if _node_attr(node, "class") != "android.widget.ImageView":
            continue
        if _node_attr(node, "clickable") != "true":
            continue
        match = BOUNDS_RE.search(node)
        if match is None:
            continue
        x1, y1, x2, y2 = (int(value) for value in match.groups())
        item_width = x2 - x1
        item_height = y2 - y1
        if item_width < min_side or item_height < min_side:
            continue
        if y2 <= max_top_control_bottom:
            continue
        if abs(item_width - item_height) > max(36, round(max(item_width, item_height) * 0.18)):
            continue
        if x1 < 0 or y1 < 0 or x2 > width or y2 > height:
            continue
        candidates.append([x1, y1, x2, y2])
    if not candidates:
        return []
    candidates.sort(key=lambda bounds: (bounds[1], bounds[0]))
    targets = []
    for bounds in candidates[: max(1, limit)]:
        target = _target_from_bounds(bounds, window_size)
        target["matched_marker"] = "album_thumbnail"
        targets.append(target)
    return targets


def _download_visible_note_results(
    *,
    stage: str,
    query: str,
    filename_prefix: str,
    target_count: int | None = None,
    item: InputItem,
    device,
    media_store,
    profile: CoordinateProfile,
    output_item_dir: Path,
    save_poll_seconds: float,
    sleep_func: Callable[[float], None],
    on_after_save: Callable[[], None] | None,
    step: Callable[[str, dict | None], None],
    max_result_scrolls: int = 5,
    seen_image_hashes: set[str] | None = None,
    keyword_index: int | None = None,
    target_category: str = "",
    target_category_keywords: list[str] | tuple[str, ...] | None = None,
) -> tuple[list[CollectedImage], list[dict]]:
    _check_risk_or_raise(device, item.item_id)
    swipe_start = profile.point("results_panel_swipe_start")
    swipe_end = profile.point("results_panel_swipe_end")
    device.swipe_ratio(*swipe_start, *swipe_end, duration=0.7)
    step(
        f"swipe_{stage}_results_panel_fullscreen",
        {
            "stage": stage,
            "query": query,
            "keyword_index": keyword_index,
            "filename_prefix": filename_prefix,
            "start": list(swipe_start),
            "end": list(swipe_end),
        },
    )
    if save_poll_seconds:
        sleep_func(min(1.0, save_poll_seconds))
    candidate_count = _note_card_candidate_count(device)
    step(
        f"wait_{stage}_result_list_stable",
        {"stage": stage, "candidate_count": candidate_count},
    )

    images: list[CollectedImage] = []
    failures: list[dict] = []
    target_count = item.top_n if target_count is None else target_count
    seen_card_signatures: set[str] = set()
    image_hashes = seen_image_hashes if seen_image_hashes is not None else set()
    category_keywords = _normalize_category_keywords(target_category_keywords)
    scroll_count = 0
    fallback_rank = 1
    while len(images) < target_count:
        _check_risk_or_raise(device, item.item_id)
        candidates = _note_card_candidates(device)
        next_candidate = _next_unseen_note_card(
            candidates=candidates,
            seen_card_signatures=seen_card_signatures,
            scroll_count=scroll_count,
            stage=stage,
            query=query,
            keyword_index=keyword_index,
            target_category=target_category,
            target_category_keywords=category_keywords,
            step=step,
        )
        if next_candidate is None:
            if _can_use_coordinate_card_fallback(
                device, fallback_rank, category_filter_enabled=bool(category_keywords)
            ):
                card_target = None
                attempted_rank = fallback_rank
                fallback_rank += 1
            else:
                if scroll_count >= max_result_scrolls:
                    failure = {
                        "event": "stage_scroll_limit_reached",
                        "item_id": item.item_id,
                        "stage": stage,
                        "query": query,
                        "keyword_index": keyword_index,
                        "filename_prefix": filename_prefix,
                        "downloaded_count": len(images),
                        "target_count": target_count,
                        "scroll_count": scroll_count,
                        "candidate_count": len(candidates),
                    }
                    step("stage_scroll_limit_reached", failure)
                    failures.append(failure)
                    break
                device.swipe_ratio(*swipe_start, *swipe_end, duration=0.7)
                scroll_count += 1
                step(
                    f"scroll_{stage}_result_list",
                    {
                        "stage": stage,
                        "query": query,
                        "keyword_index": keyword_index,
                        "filename_prefix": filename_prefix,
                        "scroll_count": scroll_count,
                        "downloaded_count": len(images),
                        "target_count": target_count,
                        "candidate_count": len(candidates),
                        "start": list(swipe_start),
                        "end": list(swipe_end),
                    },
                )
                if save_poll_seconds:
                    sleep_func(min(1.0, save_poll_seconds))
                continue
        else:
            card_target = next_candidate
            attempted_rank = None
        output_rank = len(images) + 1
        result = _download_ranked_result(
            rank=output_rank,
            fallback_rank=attempted_rank,
            card_target=card_target,
            stage=stage,
            query=query,
            filename_prefix=filename_prefix,
            item=item,
            device=device,
            media_store=media_store,
            profile=profile,
            output_item_dir=output_item_dir,
            save_poll_seconds=save_poll_seconds,
            sleep_func=sleep_func,
            on_after_save=on_after_save,
            keyword_index=keyword_index,
            step=step,
        )
        if isinstance(result, CollectedImage):
            image_hash = _file_sha256(result.local_path)
            if image_hash in image_hashes:
                duplicate_event = {
                    "event": "duplicate_saved_media",
                    "item_id": item.item_id,
                    "stage": stage,
                    "rank": output_rank,
                    "query": query,
                    "keyword_index": keyword_index,
                    "filename_prefix": filename_prefix,
                    "local_path": str(result.local_path),
                    "device_path": result.device_path,
                    "sha256": image_hash,
                }
                step("duplicate_saved_media", duplicate_event)
                failures.append(duplicate_event)
                try:
                    result.local_path.unlink()
                except FileNotFoundError:
                    pass
            else:
                image_hashes.add(image_hash)
                images.append(result)
                step(
                    f"download_{stage}_rank_{output_rank}",
                    {
                        "stage": stage,
                        "rank": output_rank,
                        "local_path": str(result.local_path),
                        "query": query,
                        "keyword_index": keyword_index,
                        "filename_prefix": filename_prefix,
                    },
                )
        else:
            failures.append(result)
        if _result_attempt_returned_to_results(result):
            restore_result = _wait_for_result_list_stable(
                device=device,
                timeout_seconds=save_poll_seconds,
                sleep_func=sleep_func,
                item_id=item.item_id,
            )
            step(
                f"wait_back_to_{stage}_result_list_rank_{output_rank}",
                {
                    "stage": stage,
                    "rank": output_rank,
                    "query": query,
                    "keyword_index": keyword_index,
                    "candidate_count": restore_result["candidate_count"],
                    "restored": restore_result["restored"],
                },
            )
            if not restore_result["restored"]:
                failure = {
                    "event": "result_list_not_restored_after_back",
                    "item_id": item.item_id,
                    "stage": stage,
                    "rank": output_rank,
                    "query": query,
                    "keyword_index": keyword_index,
                    "candidate_count": restore_result["candidate_count"],
                    "blocking": True,
                }
                step("result_list_not_restored_after_back", failure)
                failures.append(failure)
                break
    if len(images) >= target_count:
        step(
            "stage_download_limit_reached",
            {
                "stage": stage,
                "query": query,
                "keyword_index": keyword_index,
                "filename_prefix": filename_prefix,
                "downloaded_count": len(images),
                "target_count": target_count,
                "scroll_count": scroll_count,
            },
        )
    return images, failures


def _result_attempt_returned_to_results(result: CollectedImage | dict) -> bool:
    if isinstance(result, CollectedImage):
        return True
    return result.get("event") == "save_rank_failed"


def _wait_for_result_list_stable(
    *,
    device,
    timeout_seconds: float,
    sleep_func: Callable[[float], None],
    item_id: str,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    has_window_size = getattr(device, "window_size", None) is not None
    while True:
        hierarchy = device.dump_hierarchy()
        risk = detect_risk_text(hierarchy)
        if risk:
            raise DeterministicRiskError(risk, item_id)
        candidate_count = _note_card_candidate_count(device)
        if candidate_count > 0:
            return {"restored": True, "candidate_count": candidate_count}
        if not has_window_size and any(marker in hierarchy for marker in RESULT_PAGE_MARKERS):
            return {"restored": True, "candidate_count": candidate_count}
        if timeout_seconds <= 0 or time.monotonic() >= deadline:
            return {"restored": False, "candidate_count": candidate_count}
        sleep_func(min(0.5, timeout_seconds))


def _note_card_candidate_count(device) -> int:
    return len(_note_card_candidates(device))


def _note_card_candidates(device) -> list[dict]:
    window_size = getattr(device, "window_size", None)
    if window_size is None:
        return []
    return _find_note_card_candidates(device.dump_hierarchy(), window_size())


def _next_unseen_note_card(
    *,
    candidates: list[dict],
    seen_card_signatures: set[str],
    scroll_count: int,
    stage: str,
    query: str,
    keyword_index: int | None = None,
    target_category: str = "",
    target_category_keywords: list[str] | tuple[str, ...] | None = None,
    step: Callable[[str, dict | None], None],
) -> dict | None:
    category_keywords = _normalize_category_keywords(target_category_keywords)
    for candidate in candidates:
        signature = candidate.get("signature")
        signature_source = candidate.get("signature_source", "")
        dedupe_signature = _candidate_dedupe_signature(candidate, scroll_count)
        if dedupe_signature in seen_card_signatures:
            step(
                "skip_duplicate_note_card",
                {
                    "stage": stage,
                    "query": query,
                    "signature": signature,
                    "signature_source": signature_source,
                    "card_bounds": candidate.get("bounds"),
                    "scroll_count": scroll_count,
                },
            )
            continue
        seen_card_signatures.add(dedupe_signature)
        if category_keywords:
            card_text = str(candidate.get("text") or "")
            matched_keyword = _matched_category_keyword(card_text, category_keywords)
            if matched_keyword is None:
                step(
                    "skip_result_card_category_mismatch",
                    {
                        "stage": stage,
                        "query": query,
                        "keyword_index": keyword_index,
                        "target_category": target_category,
                        "target_category_keywords": list(category_keywords),
                        "matched_keyword": None,
                        "card_bounds": candidate.get("bounds"),
                        "card_signature": signature,
                        "card_signature_source": signature_source,
                        "card_text": _truncate_text(card_text),
                        "scroll_count": scroll_count,
                    },
                )
                continue
            candidate = dict(candidate)
            candidate["category_match"] = True
            candidate["matched_keyword"] = matched_keyword
            candidate["target_category"] = target_category
        return candidate
    return None


def _candidate_dedupe_signature(candidate: dict, scroll_count: int) -> str:
    signature = str(candidate.get("signature") or "")
    if candidate.get("signature_source") == "bounds":
        return f"visible:{scroll_count}:{signature}"
    return signature


def _normalize_category_keywords(
    keywords: list[str] | tuple[str, ...] | None,
) -> list[str]:
    if not keywords:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        text = " ".join(str(keyword).split())
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _matched_category_keyword(card_text: str, keywords: list[str]) -> str | None:
    normalized_text = " ".join(card_text.split()).lower()
    if not normalized_text:
        return None
    for keyword in keywords:
        if keyword.lower() in normalized_text:
            return keyword
    return None


def _truncate_text(text: str, limit: int = 160) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _can_use_coordinate_card_fallback(
    device, fallback_rank: int, *, category_filter_enabled: bool = False
) -> bool:
    if fallback_rank > 3:
        return False
    if category_filter_enabled:
        return False
    return getattr(device, "window_size", None) is None


def _note_card_click_target(
    *,
    device,
    profile: CoordinateProfile,
    rank: int,
    card_target: dict | None = None,
) -> dict:
    if card_target is not None:
        center_x, center_y = card_target["center"]
        width, height = device.window_size()
        return {
            "click_source": "ui_hierarchy",
            "click_point": card_target["center"],
            "point": [
                round(center_x / width, 4),
                round(center_y / height, 4),
            ],
            "card_bounds": card_target["bounds"],
            "card_signature": card_target.get("signature"),
            "card_signature_source": card_target.get("signature_source"),
            "card_text": card_target.get("text"),
            "matched_keyword": card_target.get("matched_keyword"),
            "target_category": card_target.get("target_category"),
        }
    window_size = getattr(device, "window_size", None)
    if window_size is not None:
        size = window_size()
        candidates = _find_note_card_candidates(device.dump_hierarchy(), size)
        if len(candidates) >= rank:
            candidate = candidates[rank - 1]
            center_x, center_y = candidate["center"]
            width, height = size
            return {
                "click_source": "ui_hierarchy",
                "click_point": candidate["center"],
                "point": [
                    round(center_x / width, 4),
                    round(center_y / height, 4),
                ],
                "card_bounds": candidate["bounds"],
                "card_signature": candidate.get("signature"),
                "card_signature_source": candidate.get("signature_source"),
                "card_text": candidate.get("text"),
                "matched_keyword": candidate.get("matched_keyword"),
                "target_category": candidate.get("target_category"),
            }
    point = profile.point(f"result_card_{rank}")
    click_point = None
    if window_size is not None:
        width, height = window_size()
        click_point = [round(width * point[0]), round(height * point[1])]
    return {
        "click_source": "coordinate_profile",
        "click_point": click_point,
        "point": list(point),
        "card_bounds": None,
        "card_signature": None,
        "card_signature_source": None,
        "card_text": None,
        "matched_keyword": None,
        "target_category": None,
    }


def _click_note_card_target(device, click_target: dict) -> None:
    if click_target["click_source"] == "ui_hierarchy":
        click_point = getattr(device, "click_point", None)
        if click_point is not None:
            x, y = click_target["click_point"]
            click_point(x, y)
            return
    device.click_ratio(*click_target["point"])


def _click_target(device, click_target: dict) -> None:
    if click_target["click_source"] == "ui_hierarchy":
        click_point = getattr(device, "click_point", None)
        if click_point is not None:
            x, y = click_target["click_point"]
            click_point(x, y)
            return
    device.click_ratio(*click_target["point"])


def _save_menu_click_target(device, profile: CoordinateProfile) -> dict:
    window_size = getattr(device, "window_size", None)
    if window_size is not None:
        target = _find_click_target_by_markers(
            device.dump_hierarchy(), SAVE_MENU_MARKERS, window_size()
        )
        if target is not None:
            return target
    point = profile.point("save_image_menu_item")
    click_point = None
    if window_size is not None:
        width, height = window_size()
        click_point = [round(width * point[0]), round(height * point[1])]
    return {
        "click_source": "coordinate_profile",
        "click_point": click_point,
        "point": list(point),
        "bounds": None,
        "matched_marker": None,
    }


def _back_button_click_target(device, profile: CoordinateProfile) -> dict | None:
    window_size = getattr(device, "window_size", None)
    if window_size is not None:
        target = _find_back_button_target(device.dump_hierarchy(), window_size())
        if target is not None:
            return target
    point = profile.point("note_back_button")
    click_point = None
    if window_size is not None:
        width, height = window_size()
        click_point = [round(width * point[0]), round(height * point[1])]
    return {
        "click_source": "coordinate_profile",
        "click_point": click_point,
        "point": list(point),
        "bounds": None,
        "matched_marker": "note_back_button",
    }


def _find_back_button_target(
    hierarchy: str, window_size: tuple[int, int]
) -> dict | None:
    width, height = window_size
    if width <= 0 or height <= 0:
        return None
    max_right = width * 0.35
    max_bottom = height * 0.18
    for node in re.findall(r"<node\b[^>]*(?:/?>)", hierarchy):
        match = BOUNDS_RE.search(node)
        if match is None:
            continue
        x1, y1, x2, y2 = (int(value) for value in match.groups())
        if x1 > max_right or y1 > max_bottom or x2 > max_right or y2 > max_bottom:
            continue
        text = _node_attr(node, "text").strip()
        content_desc = _node_attr(node, "content-desc").strip()
        resource_id = _node_attr(node, "resource-id").strip()
        label = " ".join(value for value in (text, content_desc, resource_id) if value)
        if not (
            text in BACK_BUTTON_TEXTS
            or content_desc in BACK_BUTTON_TEXTS
            or any(marker in label for marker in BACK_BUTTON_MARKERS)
        ):
            continue
        center_x = round((x1 + x2) / 2)
        center_y = round((y1 + y2) / 2)
        return {
            "click_source": "ui_hierarchy",
            "click_point": [center_x, center_y],
            "point": [
                round(center_x / width, 4),
                round(center_y / height, 4),
            ],
            "bounds": [x1, y1, x2, y2],
            "matched_marker": text or content_desc or resource_id,
        }
    return None


def _find_click_target_by_markers(
    hierarchy: str, markers: tuple[str, ...], window_size: tuple[int, int]
) -> dict | None:
    width, height = window_size
    if width <= 0 or height <= 0:
        return None
    for node in re.findall(r"<node\b[^>]*(?:/?>)", hierarchy):
        matched_marker = next((marker for marker in markers if marker in node), None)
        if matched_marker is None:
            continue
        match = BOUNDS_RE.search(node)
        if match is None:
            continue
        x1, y1, x2, y2 = (int(value) for value in match.groups())
        center_x = round((x1 + x2) / 2)
        center_y = round((y1 + y2) / 2)
        return {
            "click_source": "ui_hierarchy",
            "click_point": [center_x, center_y],
            "point": [
                round(center_x / width, 4),
                round(center_y / height, 4),
            ],
            "bounds": [x1, y1, x2, y2],
            "matched_marker": matched_marker,
        }
    return None


def _return_to_result_list(
    *,
    device,
    profile: CoordinateProfile,
    item_id: str,
    timeout_seconds: float,
    sleep_func: Callable[[float], None],
) -> dict:
    target = _back_button_click_target(device, profile)
    attempts: list[dict] = []
    if target is not None:
        _click_target(device, target)
        attempts.append(
            {
                "source": target["click_source"],
                "point": target["point"],
                "click_point": target["click_point"],
                "bounds": target["bounds"],
                "matched_marker": target["matched_marker"],
            }
        )
        if _wait_for_result_list_stable(
            device=device,
            timeout_seconds=min(0.8, timeout_seconds),
            sleep_func=sleep_func,
            item_id=item_id,
        )["restored"]:
            return {
                "back_source": target["click_source"],
                "back_point": target["point"],
                "back_click_point": target["click_point"],
                "back_bounds": target["bounds"],
                "matched_marker": target["matched_marker"],
                "back_swipe": None,
                "back_attempts": attempts,
            }

    system_back_available = _perform_system_back(device)
    attempts.append({"source": "system_back", "available": system_back_available})
    return {
        "back_source": "system_back",
        "back_point": None,
        "back_click_point": None,
        "back_bounds": None,
        "matched_marker": None,
        "back_swipe": None,
        "back_attempts": attempts,
    }


def _perform_system_back(device) -> bool:
    press_back = getattr(device, "press_back", None)
    if press_back is None:
        return False
    press_back()
    return True


def _download_permission_hint(ui_text: str) -> str | None:
    for node in re.findall(r"<node\b[^>]*(?:/?>)", ui_text):
        for attr_name in ("text", "content-desc"):
            value = _node_attr(node, attr_name)
            if any(marker in value for marker in DOWNLOAD_PERMISSION_DISABLED_MARKERS):
                return value
    for marker in DOWNLOAD_PERMISSION_DISABLED_MARKERS:
        if marker in ui_text:
            return marker
    return None


def _save_rank_failure(
    *,
    device,
    item: InputItem,
    stage: str,
    rank: int,
    query: str,
    keyword_index: int | None = None,
) -> dict:
    permission_hint = _download_permission_hint(device.dump_hierarchy())
    failure = {
        "event": "save_rank_failed",
        "item_id": item.item_id,
        "stage": stage,
        "rank": rank,
        "query": query,
        "keyword_index": keyword_index,
        "reason": (
            "download_permission_disabled"
            if permission_hint
            else "no new media detected after save"
        ),
    }
    if permission_hint:
        failure["permission_hint"] = permission_hint
    return failure


def _find_note_card_candidates(
    hierarchy: str, window_size: tuple[int, int]
) -> list[dict]:
    width, height = window_size
    if width <= 0 or height <= 0:
        return []
    nodes = _hierarchy_nodes(hierarchy)
    min_width = width * 0.3
    min_height = height * 0.12
    min_top = height * 0.12
    candidates: list[dict] = []
    for node in nodes:
        raw_node = node["raw"]
        if _node_attr(raw_node, "clickable") != "true":
            continue
        if _node_attr(raw_node, "long-clickable") != "true":
            continue
        bounds = node["bounds"]
        if bounds is None:
            continue
        x1, y1, x2, y2 = bounds
        node_width = x2 - x1
        node_height = y2 - y1
        if node_width < min_width or node_height < min_height:
            continue
        if y1 < min_top:
            continue
        signature, signature_source = _note_card_signature(
            raw_node, [x1, y1, x2, y2], nodes
        )
        card_text = _note_card_text(raw_node, [x1, y1, x2, y2], nodes)
        candidates.append(
            {
                "bounds": [x1, y1, x2, y2],
                "center": [round((x1 + x2) / 2), round((y1 + y2) / 2)],
                "row_bucket": y1 // 160,
                "signature": signature,
                "signature_source": signature_source,
                "text": card_text,
            }
        )
    candidates.sort(key=lambda candidate: (candidate["row_bucket"], candidate["bounds"][0]))
    for candidate in candidates:
        candidate.pop("row_bucket", None)
    return candidates


def _hierarchy_nodes(hierarchy: str) -> list[dict]:
    nodes: list[dict] = []
    for raw_node in re.findall(r"<node\b[^>]*(?:/?>)", hierarchy):
        nodes.append({"raw": raw_node, "bounds": _node_bounds(raw_node)})
    return nodes


def _node_bounds(node: str) -> list[int] | None:
    match = BOUNDS_RE.search(node)
    if match is None:
        return None
    return [int(value) for value in match.groups()]


def _note_card_signature(
    card_node: str, card_bounds: list[int], nodes: list[dict]
) -> tuple[str, str]:
    labels: list[str] = []
    for value in (
        _node_attr(card_node, "text"),
        _node_attr(card_node, "content-desc"),
        _node_attr(card_node, "resource-id"),
    ):
        _append_signature_label(labels, value)
    for node in nodes:
        bounds = node["bounds"]
        if bounds is None or not _bounds_inside(bounds, card_bounds):
            continue
        raw_node = node["raw"]
        for value in (
            _node_attr(raw_node, "text"),
            _node_attr(raw_node, "content-desc"),
        ):
            _append_signature_label(labels, value)
    if labels:
        deduped_labels = list(dict.fromkeys(labels))
        return "text:" + "|".join(deduped_labels), "text"
    return "bounds:" + ",".join(str(value) for value in card_bounds), "bounds"


def _note_card_text(card_node: str, card_bounds: list[int], nodes: list[dict]) -> str:
    labels: list[str] = []
    for value in (
        _node_attr(card_node, "text"),
        _node_attr(card_node, "content-desc"),
    ):
        _append_signature_label(labels, value)
    for node in nodes:
        bounds = node["bounds"]
        if bounds is None or not _bounds_inside(bounds, card_bounds):
            continue
        raw_node = node["raw"]
        for value in (
            _node_attr(raw_node, "text"),
            _node_attr(raw_node, "content-desc"),
        ):
            _append_signature_label(labels, value)
    return " ".join(dict.fromkeys(labels))


def _append_signature_label(labels: list[str], value: str) -> None:
    normalized = " ".join(html.unescape(value).split())
    if normalized:
        labels.append(normalized)


def _bounds_inside(bounds: list[int], container: list[int]) -> bool:
    x1, y1, x2, y2 = bounds
    left, top, right, bottom = container
    return left <= x1 and y1 >= top and x2 <= right and y2 <= bottom


def _node_attr(node: str, name: str) -> str:
    match = re.search(rf'{re.escape(name)}="([^"]*)"', node)
    return match.group(1) if match else ""


def _download_ranked_result(
    *,
    rank: int,
    fallback_rank: int | None = None,
    card_target: dict | None = None,
    stage: str,
    query: str,
    filename_prefix: str,
    item: InputItem,
    device,
    media_store,
    profile: CoordinateProfile,
    output_item_dir: Path,
    save_poll_seconds: float,
    sleep_func: Callable[[float], None],
    on_after_save: Callable[[], None] | None,
    keyword_index: int | None = None,
    step: Callable[[str, dict | None], None],
) -> CollectedImage | dict:
    click_target = _note_card_click_target(
        device=device,
        profile=profile,
        rank=fallback_rank or rank,
        card_target=card_target,
    )
    retry_count = 0
    opened = False
    for attempt in range(2):
        _click_note_card_target(device, click_target)
        step(
            f"open_{stage}_result_card_rank_{rank}",
            {
                "stage": stage,
                "rank": rank,
                "point": click_target["point"],
                "click_point": click_target["click_point"],
                "click_source": click_target["click_source"],
                "card_bounds": click_target["card_bounds"],
                "card_signature": click_target["card_signature"],
                "card_signature_source": click_target["card_signature_source"],
                "card_text": _truncate_text(str(click_target.get("card_text") or "")),
                "matched_keyword": click_target.get("matched_keyword"),
                "target_category": click_target.get("target_category"),
                "query": query,
                "keyword_index": keyword_index,
                "attempt": attempt + 1,
            },
        )
        opened = _wait_for_markers(
            device=device,
            markers=NOTE_DETAIL_MARKERS,
            timeout_seconds=save_poll_seconds,
            sleep_func=sleep_func,
            item_id=item.item_id,
        )
        if opened:
            break
        if attempt == 0:
            retry_count = 1
            step(
                f"retry_open_{stage}_result_card_rank_{rank}",
                {
                    "stage": stage,
                    "rank": rank,
                    "click_point": click_target["click_point"],
                    "click_source": click_target["click_source"],
                    "card_bounds": click_target["card_bounds"],
                    "card_signature": click_target["card_signature"],
                    "card_signature_source": click_target["card_signature_source"],
                    "card_text": _truncate_text(str(click_target.get("card_text") or "")),
                    "matched_keyword": click_target.get("matched_keyword"),
                    "target_category": click_target.get("target_category"),
                    "query": query,
                    "keyword_index": keyword_index,
                },
            )
    if not opened:
        failure = {
            "event": "note_card_not_opened",
            "item_id": item.item_id,
            "stage": stage,
            "rank": rank,
            "query": query,
            "keyword_index": keyword_index,
            "card_bounds": click_target["card_bounds"],
            "click_point": click_target["click_point"],
            "click_source": click_target["click_source"],
            "card_signature": click_target["card_signature"],
            "card_signature_source": click_target["card_signature_source"],
            "card_text": _truncate_text(str(click_target.get("card_text") or "")),
            "matched_keyword": click_target.get("matched_keyword"),
            "target_category": click_target.get("target_category"),
            "retry_count": retry_count,
        }
        step("note_card_not_opened", failure)
        return failure
    try:
        _check_risk_or_raise(device, item.item_id)
        before = media_store.snapshot()
        _attempt_note_image_save(
            device=device,
            profile=profile,
            item=item,
            stage=stage,
            rank=rank,
            query=query,
            keyword_index=keyword_index,
            save_attempt=1,
            on_after_save=on_after_save,
            step=step,
        )
        remote_path = _wait_for_new_media(
            media_store=media_store,
            before=before,
            timeout_seconds=save_poll_seconds,
            sleep_func=sleep_func,
        )
        if remote_path is None and _download_permission_hint(device.dump_hierarchy()) is None:
            step(
                "retry_save_after_no_new_media",
                {"stage": stage, "rank": rank, "query": query, "save_attempt": 2},
            )
            _attempt_note_image_save(
                device=device,
                profile=profile,
                item=item,
                stage=stage,
                rank=rank,
                query=query,
                keyword_index=keyword_index,
                save_attempt=2,
                on_after_save=on_after_save,
                step=step,
            )
            remote_path = _wait_for_new_media(
                media_store=media_store,
                before=before,
                timeout_seconds=save_poll_seconds,
                sleep_func=sleep_func,
            )
        if remote_path is None:
            failure = _save_rank_failure(
                device=device,
                item=item,
                stage=stage,
                rank=rank,
                query=query,
                keyword_index=keyword_index,
            )
            step("save_rank_failed", failure)
            return failure
        target_path = (
            output_item_dir
            / f"{filename_prefix}_{rank:03d}{_suffix_for_media(remote_path)}"
        )
        local_path = media_store.pull(remote_path, target_path)
        step(
            f"pull_saved_image_rank_{rank}",
            {
                "stage": stage,
                "rank": rank,
                "device_path": remote_path,
                "local_path": str(local_path),
                "query": query,
                "keyword_index": keyword_index,
            },
        )
        return CollectedImage(
            rank=rank,
            local_path=local_path,
            device_path=remote_path,
            stage=stage,
            query=query,
            keyword_index=keyword_index,
        )
    finally:
        back_event = _return_to_result_list(
            device=device,
            profile=profile,
            item_id=item.item_id,
            timeout_seconds=save_poll_seconds,
            sleep_func=sleep_func,
        )
        step(
            "back_to_results",
            {
                "stage": stage,
                "rank": rank,
                "query": query,
                "keyword_index": keyword_index,
                **back_event,
            },
        )


def _attempt_note_image_save(
    *,
    device,
    profile: CoordinateProfile,
    item: InputItem,
    stage: str,
    rank: int,
    query: str,
    keyword_index: int | None,
    save_attempt: int,
    on_after_save: Callable[[], None] | None,
    step: Callable[[str, dict | None], None],
) -> None:
    main_image = profile.point("note_main_image")
    device.long_press_ratio(*main_image, duration=1.0)
    step(
        "long_press_note_main_image",
        {
            "stage": stage,
            "rank": rank,
            "point": list(main_image),
            "query": query,
            "keyword_index": keyword_index,
            "save_attempt": save_attempt,
        },
    )
    _check_risk_or_raise(device, item.item_id)
    save_target = _save_menu_click_target(device, profile)
    _click_target(device, save_target)
    if on_after_save is not None:
        on_after_save()
    step(
        "tap_save_image_menu_item",
        {
            "stage": stage,
            "rank": rank,
            "point": save_target["point"],
            "click_point": save_target["click_point"],
            "save_click_source": save_target["click_source"],
            "save_bounds": save_target["bounds"],
            "matched_marker": save_target["matched_marker"],
            "query": query,
            "keyword_index": keyword_index,
            "save_attempt": save_attempt,
        },
    )


def _perform_keyword_search(
    *,
    query: str,
    item: InputItem,
    device,
    profile: CoordinateProfile,
    save_poll_seconds: float,
    sleep_func: Callable[[float], None],
    step: Callable[[str, dict | None], None],
) -> bool:
    if not query:
        return False
    search_box_target = _keyword_search_box_click_target(device, profile)
    if search_box_target is None:
        step("keyword_search_box_not_found", {"query": query})
        return False
    _click_target(device, search_box_target)
    step(
        "tap_keyword_search_box",
        {
            "query": query,
            "keyword_box_source": search_box_target["click_source"],
            "point": search_box_target["point"],
            "click_point": search_box_target["click_point"],
            "keyword_box_bounds": search_box_target["bounds"],
        },
    )
    set_text = getattr(device, "set_text", None)
    if set_text is None:
        step("keyword_search_text_input_unavailable", {"query": query})
        return False
    set_text(query)
    step("set_keyword_search_text", {"query": query})
    submit_target = _keyword_search_submit_click_target(device, profile)
    if submit_target is None:
        step("keyword_search_submit_not_found", {"query": query})
        return False
    _click_target(device, submit_target)
    step(
        "tap_keyword_search_submit",
        {
            "query": query,
            "keyword_submit_source": submit_target["click_source"],
            "point": submit_target["point"],
            "click_point": submit_target["click_point"],
            "keyword_submit_bounds": submit_target["bounds"],
            "matched_marker": submit_target["matched_marker"],
        },
    )
    if not _wait_for_markers(
        device=device,
        markers=KEYWORD_SEARCH_MARKERS + RESULT_PAGE_MARKERS,
        timeout_seconds=save_poll_seconds,
        sleep_func=sleep_func,
        item_id=item.item_id,
    ):
        step(
            "keyword_search_results_not_reached",
            {"query": query, "expected_markers": list(KEYWORD_SEARCH_MARKERS)},
        )
        return False
    step("keyword_search_results_reached", {"query": query})
    return True


def _keyword_search_box_click_target(device, profile: CoordinateProfile) -> dict | None:
    window_size = getattr(device, "window_size", None)
    if window_size is not None:
        target = _find_keyword_search_box_target(device.dump_hierarchy(), window_size())
        if target is not None:
            return target
    return _coordinate_click_target(profile, "keyword_search_box")


def _keyword_search_submit_click_target(device, profile: CoordinateProfile) -> dict | None:
    window_size = getattr(device, "window_size", None)
    if window_size is not None:
        target = _find_keyword_search_submit_target(device.dump_hierarchy(), window_size())
        if target is not None:
            return target
    return _coordinate_click_target(profile, "keyword_search_submit")


def _coordinate_click_target(
    profile: CoordinateProfile, point_name: str
) -> dict | None:
    point = profile.points.get(point_name)
    if point is None:
        return None
    return {
        "click_source": "coordinate_profile",
        "click_point": None,
        "point": list(point),
        "bounds": None,
        "matched_marker": point_name,
    }


def _find_keyword_search_box_target(
    hierarchy: str, window_size: tuple[int, int]
) -> dict | None:
    width, height = window_size
    if width <= 0 or height <= 0:
        return None
    for node in re.findall(r"<node\b[^>]*(?:/?>)", hierarchy):
        if not any(marker in _node_attr(node, "class") for marker in KEYWORD_SEARCH_BOX_CLASSES):
            continue
        target = _top_click_target(node, window_size)
        if target is not None:
            target["matched_marker"] = _node_attr(node, "class")
            return target
    return None


def _find_keyword_search_submit_target(
    hierarchy: str, window_size: tuple[int, int]
) -> dict | None:
    width, height = window_size
    if width <= 0 or height <= 0:
        return None
    min_left = width * 0.65
    max_bottom = height * 0.18
    for node in re.findall(r"<node\b[^>]*(?:/?>)", hierarchy):
        if _node_attr(node, "text").strip() != "搜索":
            continue
        match = BOUNDS_RE.search(node)
        if match is None:
            continue
        x1, y1, x2, y2 = (int(value) for value in match.groups())
        if x1 < min_left or y2 > max_bottom:
            continue
        target = _target_from_bounds([x1, y1, x2, y2], window_size)
        target["matched_marker"] = "搜索"
        return target
    return None


def _top_click_target(node: str, window_size: tuple[int, int]) -> dict | None:
    width, height = window_size
    match = BOUNDS_RE.search(node)
    if match is None:
        return None
    x1, y1, x2, y2 = (int(value) for value in match.groups())
    if y2 > height * 0.18:
        return None
    return _target_from_bounds([x1, y1, x2, y2], (width, height))


def _target_from_bounds(bounds: list[int], window_size: tuple[int, int]) -> dict:
    x1, y1, x2, y2 = bounds
    width, height = window_size
    center_x = round((x1 + x2) / 2)
    center_y = round((y1 + y2) / 2)
    return {
        "click_source": "ui_hierarchy",
        "click_point": [center_x, center_y],
        "point": [
            round(center_x / width, 4),
            round(center_y / height, 4),
        ],
        "bounds": bounds,
        "matched_marker": None,
    }


def _tap_ui_or_profile(
    *,
    device,
    profile: CoordinateProfile,
    point_name: str,
    fallback_point: str | None,
    markers: tuple[str, ...],
) -> bool:
    window_size = getattr(device, "window_size", None)
    if window_size is not None:
        ratio = _find_ratio_by_markers(device.dump_hierarchy(), markers, window_size())
        if ratio is not None:
            device.click_ratio(*ratio)
            return True
    point = profile.points.get(point_name)
    if point is None and fallback_point is not None:
        point = profile.points.get(fallback_point)
    if point is None:
        return False
    device.click_ratio(*point)
    return True


def _find_ratio_by_markers(
    hierarchy: str, markers: tuple[str, ...], window_size: tuple[int, int]
) -> tuple[float, float] | None:
    width, height = window_size
    if width <= 0 or height <= 0:
        return None
    for node in re.findall(r"<node\b[^>]*(?:/?>)", hierarchy):
        if not any(marker in node for marker in markers):
            continue
        match = BOUNDS_RE.search(node)
        if match is None:
            continue
        x1, y1, x2, y2 = (int(value) for value in match.groups())
        return (
            round(((x1 + x2) / 2) / width, 4),
            round(((y1 + y2) / 2) / height, 4),
        )
    return None


def _wait_for_new_media(
    *,
    media_store,
    before: list[str],
    timeout_seconds: float,
    sleep_func: Callable[[float], None],
) -> str | None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        new_media = diff_new_media(before, media_store.snapshot())
        if new_media:
            return new_media[-1]
        if timeout_seconds <= 0 or time.monotonic() >= deadline:
            break
        sleep_func(min(0.5, timeout_seconds))
    refresh = getattr(media_store, "refresh", None)
    if refresh is None:
        return None
    refresh()
    new_media = diff_new_media(before, media_store.snapshot())
    if new_media:
        return new_media[-1]
    if timeout_seconds <= 0:
        return None
    grace_deadline = time.monotonic() + min(5.0, max(2.0, timeout_seconds * 0.5))
    while True:
        if time.monotonic() >= grace_deadline:
            return None
        sleep_func(min(0.5, timeout_seconds))
        new_media = diff_new_media(before, media_store.snapshot())
        if new_media:
            return new_media[-1]


def _suffix_for_media(remote_path: str) -> str:
    suffix = Path(remote_path).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp"} else ".jpg"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_risk_or_raise(device, item_id: str) -> None:
    risk = detect_risk_text(device.dump_hierarchy())
    if risk:
        raise DeterministicRiskError(risk, item_id)


def _tap_template_fallback(
    *,
    device,
    matcher,
    template_dir: Path | None,
    output_dir: Path,
    item_id: str,
    template_name: str,
    event_name: str,
    reason: str,
) -> dict | None:
    if matcher is None or template_dir is None:
        return None
    screenshot_dir = output_dir / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = screenshot_dir / f"{item_id}_{event_name}_fallback.png"
    screenshot_path.write_bytes(device.screenshot())
    matches = [
        match
        for match in matcher.match_files(screenshot_path, template_dir)
        if match.name == template_name
    ]
    if not matches:
        return None
    match = matches[0]
    center_x, center_y = match.center
    device.click_point(center_x, center_y)
    return {
        "item_id": item_id,
        "step": event_name,
        "template": match.name,
        "score": match.score,
        "x": center_x,
        "y": center_y,
        "fallback_reason": reason,
    }
