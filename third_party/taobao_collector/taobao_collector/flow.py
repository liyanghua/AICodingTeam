from __future__ import annotations

import datetime as dt
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Protocol

from .artifacts import (
    append_jsonl,
    write_captured_asset,
    write_exports,
    write_file_asset,
    write_manifest,
)
from .coordinates import CoordinateProfile
from .media_store import DryRunMediaStore, SyncMediaStore, diff_new_media, suffix_for_media
from .models import TaobaoConfig, TaobaoManifest, TaobaoRequest


HOME_MARKERS = ("淘宝", "搜索")
KEYWORD_INPUT_MARKERS = ("输入商品", "搜索发现", "猜你想搜", "搜索推荐", "历史搜索")
ALBUM_MARKERS = ("相册", "全部照片", "最近项目", "允许访问", "RecyclerView")
ALBUM_CONFIRM_MARKERS = ("确定", "预览", "完成")
RESULT_MARKERS = ("综合", "销量", "商品", "店铺", "宝贝")
RESULT_LIST_MARKERS = (
    "全部",
    "品牌",
    "官方自营",
    "已售",
    "人加购",
    "¥",
    "国补专区",
    "旗舰店",
    "店",
)
DETAIL_MARKERS = ("宝贝详情", "评价", "店铺", "加入购物车", "立即购买")
DETAIL_VIDEO_MARKERS = ("视频", "播放", "暂停", "播放器", "player", "Player")
SAVE_MENU_MARKERS = ("保存图片", "保存到相册")
SEARCH_AI_TIP_MARKERS = ("万能搜升级", "购物有疑问找AI助手")
SEARCH_AI_TIP_CONFIRM_MARKERS = ("知道了",)
RISK_DIRECT_MARKERS = (
    "请登录",
    "验证码",
    "安全验证",
    "滑块",
    "确认订单",
    "提交订单",
    "下单",
)
RISK_LOGIN_MARKERS = (
    "登录/注册",
    "账号登录",
    "短信登录",
    "手机号登录",
    "密码登录",
)
RISK_PAYMENT_MARKERS = (
    "立即支付",
    "去支付",
    "确认付款",
    "订单支付",
    "支付方式",
    "收银台",
)
RISK_CART_CONTEXT_MARKERS = ("结算", "全选", "编辑商品", "失效宝贝")
RISK_DETAIL_BUY_MARKERS = ("加入购物车", "立即购买")
RISK_MARKERS = (
    RISK_DIRECT_MARKERS
    + RISK_LOGIN_MARKERS
    + RISK_PAYMENT_MARKERS
    + ("购物车",)
    + RISK_DETAIL_BUY_MARKERS
)


class TaobaoDevice(Protocol):
    def current_package(self) -> str: ...

    def start_app(self, package: str) -> None: ...

    def dump_hierarchy(self) -> str: ...

    def tap_profile_point(self, name: str, point: tuple[float, float]) -> None: ...

    def long_press_profile_point(
        self, name: str, point: tuple[float, float], duration: float = 1.0
    ) -> None: ...

    def swipe_profile_points(
        self,
        name: str,
        start: tuple[float, float],
        end: tuple[float, float],
        duration: float = 0.3,
    ) -> None: ...

    def set_text(self, text: str) -> None: ...

    def press_enter(self) -> None: ...

    def press_back(self) -> None: ...

    def save_screenshot(self, path: Path) -> None: ...


class TaobaoMediaStore(Protocol):
    def snapshot(self) -> list[str]: ...

    def pull(self, remote_path: str, target_path: Path) -> Path: ...

    def refresh(self) -> None: ...


def run_taobao_flow(
    request: TaobaoRequest,
    config: TaobaoConfig,
    device: TaobaoDevice,
    *,
    run_id: str | None = None,
    media_store: TaobaoMediaStore | None = None,
) -> TaobaoManifest:
    effective_request = _request_with_config_defaults(request, config)
    profile = CoordinateProfile.load(config.coordinate_profile)
    output_dir = config.output_root / (run_id or make_run_id())
    _prepare_output_dir(output_dir)
    manifest = TaobaoManifest(
        run_id=output_dir.name,
        channel="taobao",
        mode=effective_request.mode,
        status="running",
        output_dir=output_dir,
        request=effective_request,
        config=config,
    )
    write_manifest(manifest)
    effective_media_store = media_store or _default_media_store(device)

    try:
        _run_requested_modes(
            manifest,
            effective_request,
            config,
            device,
            profile,
            effective_media_store,
        )
    except _TaobaoRiskStop as exc:
        manifest.risk_events.append(exc.event)
        append_jsonl(manifest.output_dir / "risk_events.jsonl", exc.event)
        _event(manifest, exc.event["event"], exc.event)
        _save_debug(device, manifest.output_dir, exc.event["event"])
    except Exception as exc:
        event = {"event": "taobao_collection_failed", "reason": str(exc)}
        manifest.risk_events.append(event)
        append_jsonl(manifest.output_dir / "risk_events.jsonl", event)
        _event(manifest, "taobao_collection_failed", event)
        _save_debug(device, manifest.output_dir, "taobao_collection_failed")

    if manifest.risk_events and not manifest.assets:
        manifest.status = "failed"
    elif manifest.risk_events:
        manifest.status = "partial"
    else:
        manifest.status = "completed"
    write_manifest(manifest)
    write_exports(manifest)
    return manifest


def make_run_id(now: dt.datetime | None = None) -> str:
    value = now or dt.datetime.now(dt.UTC)
    return value.strftime("%Y%m%dT%H%M%S%fZ")


def _run_requested_modes(
    manifest: TaobaoManifest,
    request: TaobaoRequest,
    config: TaobaoConfig,
    device: TaobaoDevice,
    profile: CoordinateProfile,
    media_store: TaobaoMediaStore,
) -> None:
    _ensure_taobao_ready(manifest, config, device)
    if request.mode in {"image_search", "both"}:
        _run_image_search(manifest, request, config, device, profile, media_store)
    if request.mode in {"keyword_search", "both"}:
        queries = request.normalized_keywords()
        if not queries:
            raise ValueError("keyword or --keywords is required for keyword_search/both")
        for index, query in enumerate(queries, start=1):
            _run_keyword_search(manifest, query, index, config, device, profile, media_store)


def _run_image_search(
    manifest: TaobaoManifest,
    request: TaobaoRequest,
    config: TaobaoConfig,
    device: TaobaoDevice,
    profile: CoordinateProfile,
    media_store: TaobaoMediaStore,
) -> None:
    if request.input_image is None:
        raise ValueError("--input-image is required for image_search/both")
    if not request.input_image.exists():
        raise FileNotFoundError(f"input image not found: {request.input_image}")
    _check_risk(device)
    _push_reference_if_supported(device, request.input_image, manifest.run_id, config)
    _tap(manifest, device, profile, "image_search_button")
    if not _wait_for_markers(device, ALBUM_MARKERS, config.wait_timeout_seconds):
        _event(
            manifest,
            "taobao_image_search_button_not_on_album_page",
            {"expected_markers": list(ALBUM_MARKERS)},
        )
        raise _TaobaoRiskStop(
            {
                "event": "taobao_image_search_album_not_reached",
                "reason": "image search button did not enter album page",
            }
        )
    _event(manifest, "taobao_album_page_reached", {})
    _tap(manifest, device, profile, "album_entry")
    _tap(manifest, device, profile, "first_album_image")
    if not _wait_for_markers(device, ALBUM_CONFIRM_MARKERS, config.wait_timeout_seconds):
        raise _TaobaoRiskStop(
            {
                "event": "taobao_album_confirm_not_reached",
                "reason": "reference image was not selected",
            }
        )
    _tap(manifest, device, profile, "album_confirm")
    if not _wait_for_markers(device, RESULT_MARKERS, config.wait_timeout_seconds):
        raise _TaobaoRiskStop(
            {
                "event": "taobao_image_search_results_not_reached",
                "reason": "image search results did not load",
            }
        )
    _event(manifest, "taobao_image_search_results_reached", {})
    _collect_result_cards(
        manifest,
        query=request.input_image.name,
        stage="image_search",
        top_n=request.top_n,
        device=device,
        profile=profile,
        config=config,
        media_store=media_store,
    )


def _run_keyword_search(
    manifest: TaobaoManifest,
    query: str,
    query_index: int,
    config: TaobaoConfig,
    device: TaobaoDevice,
    profile: CoordinateProfile,
    media_store: TaobaoMediaStore,
) -> None:
    _ensure_taobao_ready(manifest, config, device)
    _check_risk(device)
    if not _open_keyword_input_page(manifest, device, profile, config, query):
        state = classify_page_state(device.dump_hierarchy())
        raise _TaobaoRiskStop(
            {
                "event": "taobao_search_page_not_reached",
                "query": query,
                "reason": "home search box did not open search page",
                "page_state": state,
            }
        )
    _event(
        manifest,
        "taobao_search_page_reached",
        {"query": query, "page_state": classify_page_state(device.dump_hierarchy())},
    )
    _check_risk(device)
    try:
        device.set_text(query)
    except Exception as exc:
        raise _TaobaoRiskStop(
            {
                "event": "taobao_keyword_text_input_failed",
                "query": query,
                "reason": str(exc),
            }
        ) from exc
    _event(manifest, "taobao_set_keyword_search_text", {"query": query})
    device.press_enter()
    _event(
        manifest,
        "taobao_submit_keyword_search",
        {"query": query, "query_index": query_index},
    )
    if not _wait_for_result_page(device, config.wait_timeout_seconds, manifest=manifest):
        hierarchy = device.dump_hierarchy()
        state = classify_page_state(hierarchy)
        if state["state"] == "recommendation":
            raise _TaobaoRiskStop(
                {
                    "event": "taobao_keyword_search_stuck_on_recommendations",
                    "query": query,
                    "reason": "keyword submit did not reach result list",
                    "page_state": state,
                }
            )
        raise _TaobaoRiskStop(
            {
                "event": "taobao_keyword_search_results_not_reached",
                "query": query,
                "reason": "keyword search result page markers not recognized",
                "page_state": state,
            }
        )
    _event(
        manifest,
        "taobao_keyword_search_results_reached",
        {"query": query, "page_state": classify_page_state(device.dump_hierarchy())},
    )
    _collect_result_cards(
        manifest,
        query=query,
        stage="keyword_search",
        top_n=manifest.request.top_n,
        device=device,
        profile=profile,
        config=config,
        media_store=media_store,
    )


def _collect_result_cards(
    manifest: TaobaoManifest,
    *,
    query: str,
    stage: str,
    top_n: int,
    device: TaobaoDevice,
    profile: CoordinateProfile,
    config: TaobaoConfig,
    media_store: TaobaoMediaStore,
) -> None:
    if classify_page_state(device.dump_hierarchy())["state"] != "result_list":
        raise _TaobaoRiskStop(
            {
                "event": "taobao_result_list_not_ready",
                "query": query,
                "stage": stage,
                "page_state": classify_page_state(device.dump_hierarchy()),
            }
        )
    card_slots = profile.result_card_slots()
    current_page_index = 0
    for rank in range(1, top_n + 1):
        _check_risk(device, allow_detail_buy_markers=False)
        desired_page_index = (rank - 1) // len(card_slots)
        while current_page_index < desired_page_index:
            if current_page_index >= config.max_result_scrolls:
                raise _TaobaoRiskStop(
                    {
                        "event": "taobao_result_page_scroll_budget_exhausted",
                        "query": query,
                        "stage": stage,
                        "rank": rank,
                        "max_result_scrolls": config.max_result_scrolls,
                    }
                )
            if not _scroll_result_page(manifest, device, config, query):
                raise _TaobaoRiskStop(
                    {
                        "event": "taobao_result_page_scroll_failed",
                        "query": query,
                        "stage": stage,
                        "rank": rank,
                        "page_index": current_page_index + 1,
                    }
                )
            current_page_index += 1
        result_payload = _capture(device, manifest.output_dir, f"{stage}_rank_{rank:03d}")
        write_captured_asset(
            manifest=manifest,
            source_item_id=f"{stage}-{rank:03d}",
            query=query,
            stage=stage,
            rank=rank,
            image_type="result_card",
            payload=result_payload,
        )
        slot_name, point = card_slots[(rank - 1) % len(card_slots)]
        device.tap_profile_point(slot_name, point)
        _event(
            manifest,
            "taobao_tap_result_card",
            {
                "stage": stage,
                "rank": rank,
                "page_index": current_page_index,
                "slot": slot_name,
            },
        )
        if not _wait_for_markers(device, DETAIL_MARKERS, config.wait_timeout_seconds):
            raise _TaobaoRiskStop(
                {
                    "event": "taobao_detail_page_not_reached",
                    "stage": stage,
                    "rank": rank,
                    "query": query,
                }
            )
        detail_failure = _save_detail_main_image(
            manifest=manifest,
            source_item_id=f"{stage}-{rank:03d}",
            query=query,
            rank=rank,
            device=device,
            profile=profile,
            config=config,
            media_store=media_store,
        )
        if detail_failure is not None:
            if detail_failure.get("event") == "taobao_detail_save_login_triggered":
                raise _TaobaoRiskStop(detail_failure)
            manifest.risk_events.append(detail_failure)
            append_jsonl(manifest.output_dir / "risk_events.jsonl", detail_failure)
            _save_debug(device, manifest.output_dir, detail_failure["event"])
        _tap(manifest, device, profile, "detail_back_button", {"rank": rank})
        _wait_for_result_page(device, config.wait_timeout_seconds, manifest=manifest)
        write_manifest(manifest)


def _ensure_taobao_ready(
    manifest: TaobaoManifest, config: TaobaoConfig, device: TaobaoDevice
) -> None:
    package = device.current_package()
    if package != config.taobao_package:
        _event(
            manifest,
            "taobao_start_app",
            {"current_package": package, "target_package": config.taobao_package},
        )
        device.start_app(config.taobao_package)
        if config.app_start_wait_seconds:
            time.sleep(min(config.app_start_wait_seconds, 1.0))
    hierarchy = device.dump_hierarchy()
    matched_risks = _matched_risk_markers(hierarchy)
    if matched_risks:
        raise _TaobaoRiskStop(
            {
                "event": "taobao_risk_prompt_detected",
                "matched_markers": matched_risks,
            }
        )
    if is_home_page(hierarchy):
        _event(manifest, "taobao_home_ready", {})
        return
    device.press_back()
    _event(manifest, "taobao_back_to_home_attempt", {})
    if is_home_page(device.dump_hierarchy()):
        _event(manifest, "taobao_home_ready", {"recovered": True})
        return
    device.start_app(config.taobao_package)
    if not _wait_for_home_page(device, config.wait_timeout_seconds):
        raise _TaobaoRiskStop(
            {
                "event": "taobao_home_not_ready",
                "reason": "home markers not found after app start",
            }
        )
    _event(manifest, "taobao_home_ready", {"restarted": True})


def _tap(
    manifest: TaobaoManifest,
    device: TaobaoDevice,
    profile: CoordinateProfile,
    point_name: str,
    payload: dict | None = None,
) -> None:
    device.tap_profile_point(point_name, profile.point(point_name))
    _event(manifest, f"taobao_tap_{point_name}", payload or {})


def _save_detail_main_image(
    *,
    manifest: TaobaoManifest,
    source_item_id: str,
    query: str,
    rank: int,
    device: TaobaoDevice,
    profile: CoordinateProfile,
    config: TaobaoConfig,
    media_store: TaobaoMediaStore,
) -> dict | None:
    selection_failure = _select_first_non_video_detail_image(
        manifest=manifest,
        device=device,
        config=config,
        rank=rank,
        query=query,
    )
    if selection_failure is not None:
        return selection_failure
    before = media_store.snapshot()
    save_failure = _attempt_detail_image_save(
        manifest=manifest,
        device=device,
        profile=profile,
        config=config,
        media_store=media_store,
        rank=rank,
        query=query,
        save_attempt=1,
    )
    if save_failure is not None:
        return save_failure
    remote_path = _wait_for_new_media(
        media_store=media_store,
        before=before,
        timeout_seconds=config.wait_timeout_seconds,
    )
    if remote_path is None:
        _event(
            manifest,
            "taobao_retry_detail_save_after_no_new_media",
            {"rank": rank, "query": query, "save_attempt": 2},
        )
        save_failure = _attempt_detail_image_save(
            manifest=manifest,
            device=device,
            profile=profile,
            config=config,
            media_store=media_store,
            rank=rank,
            query=query,
            save_attempt=2,
        )
        if save_failure is not None:
            return save_failure
        remote_path = _wait_for_new_media(
            media_store=media_store,
            before=before,
            timeout_seconds=config.wait_timeout_seconds,
        )
    if remote_path is None:
        return {
            "event": "taobao_detail_save_no_new_media",
            "rank": rank,
            "query": query,
            "reason": "no new media detected after detail image save",
        }
    target_path = (
        manifest.output_dir
        / "images"
        / f"{source_item_id}_detail_rank_{rank:03d}_detail_main{suffix_for_media(remote_path)}"
    )
    local_path = media_store.pull(remote_path, target_path)
    write_file_asset(
        manifest=manifest,
        source_item_id=source_item_id,
        query=query,
        stage="detail",
        rank=rank,
        image_type="detail_main",
        local_path=local_path,
    )
    _event(
        manifest,
        "taobao_pull_saved_detail_image",
        {
            "rank": rank,
            "query": query,
            "device_path": remote_path,
            "local_path": str(local_path),
        },
    )
    return None


def _select_first_non_video_detail_image(
    *,
    manifest: TaobaoManifest,
    device: TaobaoDevice,
    config: TaobaoConfig,
    rank: int,
    query: str,
) -> dict | None:
    for scan_index in range(1, config.detail_media_scan_max + 1):
        hierarchy = device.dump_hierarchy()
        _check_risk(device, allow_detail_buy_markers=True)
        if not is_detail_video_media(hierarchy):
            _event(
                manifest,
                "taobao_detail_non_video_image_selected",
                {"rank": rank, "query": query, "scan_index": scan_index},
            )
            return None
        _event(
            manifest,
            "taobao_detail_media_video_detected",
            {"rank": rank, "query": query, "scan_index": scan_index},
        )
        if scan_index >= config.detail_media_scan_max:
            break
        device.swipe_profile_points(
            "detail_media_next",
            config.detail_media_swipe_start,
            config.detail_media_swipe_end,
            duration=0.3,
        )
        _event(
            manifest,
            "taobao_swipe_detail_media_next",
            {
                "rank": rank,
                "query": query,
                "scan_index": scan_index,
                "start": list(config.detail_media_swipe_start),
                "end": list(config.detail_media_swipe_end),
            },
        )
        if config.throttle_seconds:
            time.sleep(min(config.throttle_seconds, 0.5))
    return {
        "event": "taobao_detail_non_video_image_not_found",
        "rank": rank,
        "query": query,
        "scan_max": config.detail_media_scan_max,
    }


def _attempt_detail_image_save(
    *,
    manifest: TaobaoManifest,
    device: TaobaoDevice,
    profile: CoordinateProfile,
    config: TaobaoConfig,
    media_store: TaobaoMediaStore,
    rank: int,
    query: str,
    save_attempt: int,
) -> dict | None:
    target = _wait_for_stable_detail_image(
        manifest=manifest,
        device=device,
        profile=profile,
        config=config,
        rank=rank,
        query=query,
        save_attempt=save_attempt,
    )
    if isinstance(target, dict):
        return target
    point_name, point_source, point = target
    device.tap_profile_point(point_name, point)
    _event(
        manifest,
        "taobao_tap_detail_main_image",
        {
            "rank": rank,
            "query": query,
            "point": list(point),
            "point_source": point_source,
            "save_attempt": save_attempt,
        },
    )
    if config.throttle_seconds:
        time.sleep(min(config.throttle_seconds, 0.5))
    login_failure = _detail_save_login_failure_if_risk(
        device,
        rank=rank,
        query=query,
        save_attempt=save_attempt,
        phase="activation_tap",
    )
    if login_failure is not None:
        return login_failure
    device.long_press_profile_point(point_name, point, duration=1.0)
    _event(
        manifest,
        "taobao_long_press_detail_main_image",
        {
            "rank": rank,
            "query": query,
            "point": list(point),
            "point_source": point_source,
            "save_attempt": save_attempt,
        },
    )
    if config.throttle_seconds:
        time.sleep(min(config.throttle_seconds, 0.5))
    login_failure = _detail_save_login_failure_if_risk(
        device,
        rank=rank,
        query=query,
        save_attempt=save_attempt,
        phase="long_press",
    )
    if login_failure is not None:
        return login_failure
    hierarchy = device.dump_hierarchy()
    if not _has_any(hierarchy, SAVE_MENU_MARKERS):
        return {
            "event": "taobao_detail_save_menu_not_found",
            "rank": rank,
            "query": query,
            "save_attempt": save_attempt,
            "reason": "save image menu markers not found",
        }
    save_point = detect_save_image_menu_point(hierarchy)
    if save_point is not None:
        device.tap_profile_point("save_image_button_detected", save_point)
        click_source = "detected_save_menu"
    else:
        save_point = profile.point("save_image_button")
        device.tap_profile_point("save_image_button", save_point)
        click_source = "profile"
    _event(
        manifest,
        "taobao_tap_save_image_button",
        {
            "rank": rank,
            "query": query,
            "point": [round(save_point[0], 4), round(save_point[1], 4)],
            "click_source": click_source,
            "save_attempt": save_attempt,
        },
    )
    record = getattr(media_store, "record_saved_image", None)
    if record is not None:
        record()
    return None


def _wait_for_stable_detail_image(
    *,
    manifest: TaobaoManifest,
    device: TaobaoDevice,
    profile: CoordinateProfile,
    config: TaobaoConfig,
    rank: int,
    query: str,
    save_attempt: int,
) -> tuple[str, str, tuple[float, float]] | dict:
    deadline = time.monotonic() + min(config.wait_timeout_seconds, 1.0)
    while True:
        hierarchy = device.dump_hierarchy()
        login_failure = _detail_save_login_failure_from_hierarchy(
            hierarchy,
            rank=rank,
            query=query,
            save_attempt=save_attempt,
            phase="stable_gate",
        )
        if login_failure is not None:
            return login_failure
        detected_point = detect_detail_main_image_point(hierarchy)
        has_detail_surface = _has_any(hierarchy, DETAIL_MARKERS) or detected_point is not None
        if has_detail_surface and not is_detail_video_media(hierarchy):
            if detected_point is not None:
                point_name = "detail_main_image_detected"
                point_source = "detected_hero_image"
                point = detected_point
            else:
                point_name = "detail_main_image"
                point_source = "coordinate_profile"
                point = profile.point("detail_main_image")
            _event(
                manifest,
                "taobao_detail_image_stable_before_save",
                {
                    "rank": rank,
                    "query": query,
                    "point": [round(point[0], 4), round(point[1], 4)],
                    "point_source": point_source,
                    "save_attempt": save_attempt,
                },
            )
            return point_name, point_source, point
        if config.wait_timeout_seconds <= 0 or time.monotonic() >= deadline:
            return {
                "event": "taobao_detail_save_menu_not_found",
                "rank": rank,
                "query": query,
                "save_attempt": save_attempt,
                "reason": "detail image was not stable before save",
            }
        time.sleep(0.25)


def _detail_save_login_failure_if_risk(
    device: TaobaoDevice,
    *,
    rank: int,
    query: str,
    save_attempt: int,
    phase: str,
) -> dict | None:
    return _detail_save_login_failure_from_hierarchy(
        device.dump_hierarchy(),
        rank=rank,
        query=query,
        save_attempt=save_attempt,
        phase=phase,
    )


def _detail_save_login_failure_from_hierarchy(
    hierarchy: str,
    *,
    rank: int,
    query: str,
    save_attempt: int,
    phase: str,
) -> dict | None:
    matched_risks = _matched_risk_markers(hierarchy, allow_detail_buy_markers=True)
    if not matched_risks:
        return None
    return {
        "event": "taobao_detail_save_login_triggered",
        "rank": rank,
        "query": query,
        "save_attempt": save_attempt,
        "phase": phase,
        "matched_markers": matched_risks,
        "reason": "login or security prompt appeared during detail image save",
    }


def is_detail_video_media(hierarchy: str) -> bool:
    if not hierarchy:
        return False
    try:
        root = ET.fromstring(hierarchy)
    except ET.ParseError:
        root = None
    if root is not None:
        structured_result = _classify_detail_media_from_xml(root)
        if structured_result is not None:
            return structured_result
    if _has_any(hierarchy, DETAIL_VIDEO_MARKERS):
        return True
    return bool(re.search(r"\b\d{1,2}:\d{2}\b", hierarchy))


def _classify_detail_media_from_xml(root: ET.Element) -> bool | None:
    selected_labels: list[str] = []
    has_hero_image = False
    has_hero_video_signal = False
    for node in root.iter():
        if node.attrib.get("package") not in {"", "com.taobao.taobao"}:
            continue
        text = node.attrib.get("text", "")
        desc = node.attrib.get("content-desc", "")
        resource_id = node.attrib.get("resource-id", "")
        label = f"{text} {desc}".strip()
        if node.attrib.get("selected") == "true" and label:
            selected_labels.append(label)
        if desc == "商品图片" or resource_id.endswith(":id/iv_image_content"):
            has_hero_image = True
        if _is_hero_video_node(node, label, resource_id):
            has_hero_video_signal = True
    for label in selected_labels:
        if "图集" in label or "图片" in label:
            return False
        if "视频" in label:
            return True
    if has_hero_image:
        return False
    if has_hero_video_signal:
        return True
    return None


def _is_hero_video_node(node: ET.Element, label: str, resource_id: str) -> bool:
    bounds = _parse_bounds(node.attrib.get("bounds", ""))
    if bounds is not None:
        x1, y1, x2, y2 = bounds
        # Ignore lower-page labels and thumbnails. Hero media lives in the top
        # square region on detail pages.
        if y1 > 1250 or y2 < 0 or x2 <= x1 or y2 <= y1:
            return False
    resource_id_lower = resource_id.lower()
    if "video" in resource_id_lower and "mini_video_container" not in resource_id_lower:
        return True
    return any(marker in label for marker in DETAIL_VIDEO_MARKERS) or bool(
        re.search(r"\b\d{1,2}:\d{2}\b", label)
    )


def detect_detail_main_image_point(hierarchy: str) -> tuple[float, float] | None:
    try:
        root = ET.fromstring(hierarchy)
    except ET.ParseError:
        return None
    screen = _screen_size_from_xml(root)
    if screen is None:
        return None
    width, height = screen
    for node in root.iter():
        if node.attrib.get("package") not in {"", "com.taobao.taobao"}:
            continue
        if node.attrib.get("visible-to-user") == "false":
            continue
        desc = node.attrib.get("content-desc", "")
        resource_id = node.attrib.get("resource-id", "")
        if desc != "商品图片" and not resource_id.endswith(":id/iv_image_content"):
            continue
        bounds = _parse_bounds(node.attrib.get("bounds", ""))
        if bounds is None:
            continue
        x1, y1, x2, y2 = bounds
        if x2 <= x1 or y2 <= y1:
            continue
        center_x = (x1 + x2) / 2 / width
        center_y = (y1 + y2) / 2 / height
        if center_y >= 0.8:
            continue
        return center_x, center_y
    return None


def detect_save_image_menu_point(hierarchy: str) -> tuple[float, float] | None:
    try:
        root = ET.fromstring(hierarchy)
    except ET.ParseError:
        return None
    screen = _screen_size_from_xml(root)
    if screen is None:
        return None
    width, height = screen
    for node in root.iter():
        text = node.attrib.get("text", "")
        desc = node.attrib.get("content-desc", "")
        if not any(marker in text or marker in desc for marker in SAVE_MENU_MARKERS):
            continue
        bounds = _parse_bounds(node.attrib.get("bounds", ""))
        if bounds is None:
            continue
        x1, y1, x2, y2 = bounds
        if x2 <= x1 or y2 <= y1:
            continue
        return ((x1 + x2) / 2 / width, (y1 + y2) / 2 / height)
    return None


def detect_search_ai_tip_confirm_point(hierarchy: str) -> tuple[float, float] | None:
    if not _has_any(hierarchy, SEARCH_AI_TIP_MARKERS):
        return None
    try:
        root = ET.fromstring(hierarchy)
    except ET.ParseError:
        return None
    screen = _screen_size_from_xml(root)
    if screen is None:
        return None
    width, height = screen
    for node in root.iter():
        if node.attrib.get("package") not in {"", "com.taobao.taobao"}:
            continue
        text = node.attrib.get("text", "")
        desc = node.attrib.get("content-desc", "")
        resource_id = node.attrib.get("resource-id", "")
        is_confirm = (
            any(marker in text or marker in desc for marker in SEARCH_AI_TIP_CONFIRM_MARKERS)
            or resource_id.endswith(":id/tv_confirm")
        )
        if not is_confirm:
            continue
        bounds = _parse_bounds(node.attrib.get("bounds", ""))
        if bounds is None:
            continue
        x1, y1, x2, y2 = bounds
        if x2 <= x1 or y2 <= y1:
            continue
        return ((x1 + x2) / 2 / width, (y1 + y2) / 2 / height)
    return None


def _dismiss_search_ai_tip_if_present(
    manifest: TaobaoManifest, device: TaobaoDevice, hierarchy: str
) -> bool:
    point = detect_search_ai_tip_confirm_point(hierarchy)
    if point is None:
        return False
    device.tap_profile_point("search_ai_tip_confirm", point)
    _event(
        manifest,
        "taobao_dismiss_search_ai_tip",
        {"point": [round(point[0], 4), round(point[1], 4)]},
    )
    return True


def _wait_for_new_media(
    *,
    media_store: TaobaoMediaStore,
    before: list[str],
    timeout_seconds: float,
) -> str | None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        new_media = diff_new_media(before, media_store.snapshot())
        if new_media:
            return new_media[-1]
        if timeout_seconds <= 0 or time.monotonic() >= deadline:
            break
        time.sleep(0.25)
    refresh = getattr(media_store, "refresh", None)
    if refresh is None:
        return None
    refresh()
    new_media = diff_new_media(before, media_store.snapshot())
    return new_media[-1] if new_media else None


def _default_media_store(device: TaobaoDevice) -> TaobaoMediaStore:
    adb = getattr(device, "adb", None)
    if adb is None:
        return DryRunMediaStore()
    return SyncMediaStore(adb)


def _open_keyword_input_page(
    manifest: TaobaoManifest,
    device: TaobaoDevice,
    profile: CoordinateProfile,
    config: TaobaoConfig,
    query: str,
) -> bool:
    for attempt in _home_search_open_attempts(device, profile, query):
        payload = {
            "query": query,
            "point_source": attempt.point_source,
        }
        if attempt.point is not None:
            payload["point"] = [
                round(attempt.point[0], 4),
                round(attempt.point[1], 4),
            ]
        _event(manifest, "taobao_tap_home_search_box", payload)
        attempt()
        if _wait_for_keyword_input_page(device, min(config.wait_timeout_seconds, 1.0)):
            return True
        _event(
            manifest,
            "taobao_home_search_box_click_not_on_input_page",
            {
                "query": query,
                "point_source": attempt.point_source,
                "page_state": classify_page_state(device.dump_hierarchy()),
            },
        )
    return _wait_for_keyword_input_page(device, config.wait_timeout_seconds)


def _home_search_open_attempts(
    device: TaobaoDevice,
    profile: CoordinateProfile,
    _query: str,
) -> list[_HomeSearchOpenAttempt]:
    hierarchy = device.dump_hierarchy()
    attempts: list[_HomeSearchOpenAttempt] = []
    tap_by_description = getattr(device, "tap_by_description", None)
    if tap_by_description is not None and 'content-desc="搜索栏"' in hierarchy:
        attempts.append(
            _HomeSearchOpenAttempt(
                point_source="accessibility_search_bar",
                action=lambda: tap_by_description("搜索栏"),
            )
        )
    detected_point = detect_home_search_bar_point(hierarchy)
    if detected_point is not None:
        attempts.append(
            _HomeSearchOpenAttempt(
                point_source="detected_home_search_bar",
                point=detected_point,
                action=lambda: device.tap_profile_point(
                    "home_search_box_detected", detected_point
                ),
            )
        )
    attempts.append(
        _HomeSearchOpenAttempt(
            point_source="coordinate_profile",
            point=profile.point("home_search_box"),
            action=lambda: device.tap_profile_point(
                "home_search_box", profile.point("home_search_box")
            ),
        )
    )
    adb_tap = getattr(device, "tap_profile_point_adb", None)
    if adb_tap is not None:
        if detected_point is not None:
            attempts.append(
                _HomeSearchOpenAttempt(
                    point_source="detected_home_search_bar_adb",
                    point=detected_point,
                    action=lambda: adb_tap("home_search_box_detected_adb", detected_point),
                )
            )
        attempts.append(
            _HomeSearchOpenAttempt(
                point_source="coordinate_profile_adb",
                point=profile.point("home_search_box"),
                action=lambda: adb_tap("home_search_box_adb", profile.point("home_search_box")),
            )
        )
    return attempts


class _HomeSearchOpenAttempt:
    def __init__(
        self,
        *,
        point_source: str,
        action,
        point: tuple[float, float] | None = None,
    ) -> None:
        self.point_source = point_source
        self._action = action
        self.point = point

    def __call__(self) -> None:
        self._action()


def _capture(device: TaobaoDevice, output_dir: Path, name: str) -> bytes:
    target = output_dir / "debug" / f"{name}.png"
    device.save_screenshot(target)
    return target.read_bytes()


def _save_debug(device: TaobaoDevice, output_dir: Path, name: str) -> None:
    try:
        screenshot = output_dir / "debug" / f"{name}.png"
        device.save_screenshot(screenshot)
        (output_dir / "debug" / f"{name}.xml").write_text(
            device.dump_hierarchy(), encoding="utf-8"
        )
    except Exception:
        return


def _wait_for_markers(
    device: TaobaoDevice, markers: tuple[str, ...], timeout_seconds: float
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while True:
        hierarchy = device.dump_hierarchy()
        matched_risks = _matched_risk_markers(hierarchy)
        if matched_risks:
            raise _TaobaoRiskStop(
                {
                    "event": "taobao_risk_prompt_detected",
                    "matched_markers": matched_risks,
                }
            )
        if _has_any(hierarchy, markers):
            return True
        if timeout_seconds <= 0 or time.monotonic() >= deadline:
            return False
        time.sleep(0.25)


def _wait_for_result_page(
    device: TaobaoDevice,
    timeout_seconds: float,
    *,
    manifest: TaobaoManifest | None = None,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while True:
        hierarchy = device.dump_hierarchy()
        matched_risks = _matched_risk_markers(hierarchy)
        if matched_risks:
            raise _TaobaoRiskStop(
                {
                    "event": "taobao_risk_prompt_detected",
                    "matched_markers": matched_risks,
                }
            )
        if manifest is not None and _dismiss_search_ai_tip_if_present(
            manifest, device, hierarchy
        ):
            continue
        if classify_page_state(hierarchy)["state"] == "result_list":
            return True
        if timeout_seconds <= 0 or time.monotonic() >= deadline:
            return False
        time.sleep(0.25)


def _wait_for_home_page(device: TaobaoDevice, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while True:
        hierarchy = device.dump_hierarchy()
        matched_risks = _matched_risk_markers(hierarchy)
        if matched_risks:
            raise _TaobaoRiskStop(
                {
                    "event": "taobao_risk_prompt_detected",
                    "matched_markers": matched_risks,
                }
            )
        if is_home_page(hierarchy):
            return True
        if timeout_seconds <= 0 or time.monotonic() >= deadline:
            return False
        time.sleep(0.25)


def _wait_for_keyword_input_page(device: TaobaoDevice, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while True:
        hierarchy = device.dump_hierarchy()
        matched_risks = _matched_risk_markers(hierarchy)
        if matched_risks:
            raise _TaobaoRiskStop(
                {
                    "event": "taobao_risk_prompt_detected",
                    "matched_markers": matched_risks,
                }
            )
        if is_keyword_input_page(hierarchy):
            return True
        if timeout_seconds <= 0 or time.monotonic() >= deadline:
            return False
        time.sleep(0.25)


def _check_risk(device: TaobaoDevice, *, allow_detail_buy_markers: bool = True) -> None:
    hierarchy = device.dump_hierarchy()
    matched_risks = _matched_risk_markers(
        hierarchy, allow_detail_buy_markers=allow_detail_buy_markers
    )
    if matched_risks:
        raise _TaobaoRiskStop(
            {
                "event": "taobao_risk_prompt_detected",
                "matched_markers": matched_risks,
            }
        )


def _has_risk_marker(
    hierarchy: str, *, allow_detail_buy_markers: bool = True
) -> bool:
    return bool(
        _matched_risk_markers(
            hierarchy, allow_detail_buy_markers=allow_detail_buy_markers
        )
    )


def _matched_risk_markers(
    hierarchy: str, *, allow_detail_buy_markers: bool = True
) -> list[str]:
    text = _risk_detection_text(hierarchy)
    matched = _matched_markers(text, RISK_DIRECT_MARKERS)
    matched.extend(marker for marker in RISK_LOGIN_MARKERS if marker in text)
    matched.extend(marker for marker in RISK_PAYMENT_MARKERS if marker in text)
    if "购物车" in text and _has_any(text, RISK_CART_CONTEXT_MARKERS):
        matched.append("购物车")
    if not allow_detail_buy_markers:
        matched.extend(marker for marker in RISK_DETAIL_BUY_MARKERS if marker in text)
    return _dedupe_preserve_order(matched)


def _risk_detection_text(hierarchy: str) -> str:
    try:
        root = ET.fromstring(hierarchy)
    except ET.ParseError:
        return hierarchy
    values: list[str] = []
    for node in root.iter():
        package = node.attrib.get("package", "")
        if package and package != "com.taobao.taobao":
            continue
        for key in ("text", "content-desc", "hint"):
            value = node.attrib.get(key, "")
            if value:
                values.append(value)
    return "\n".join(values) if values else hierarchy


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _has_any(hierarchy: str, markers: tuple[str, ...]) -> bool:
    return any(marker and marker in hierarchy for marker in markers)


def classify_page_state(hierarchy: str) -> dict:
    matched = _matched_markers(hierarchy, RESULT_MARKERS + RESULT_LIST_MARKERS)
    matched_risks = _matched_risk_markers(hierarchy)
    if matched_risks:
        return {"state": "risk", "matched_markers": matched_risks}
    if _has_selected_home_tab(hierarchy):
        return {"state": "home", "matched_markers": _matched_markers(hierarchy, HOME_MARKERS)}
    if is_keyword_input_page(hierarchy):
        return {
            "state": "keyword_input",
            "matched_markers": _matched_markers(hierarchy, KEYWORD_INPUT_MARKERS),
        }
    if _has_any(hierarchy, ("猜你想搜", "搜索推荐", "历史搜索")):
        return {
            "state": "recommendation",
            "matched_markers": _matched_markers(
                hierarchy, ("猜你想搜", "搜索推荐", "历史搜索")
            ),
        }
    if _is_result_list_hierarchy(hierarchy):
        return {"state": "result_list", "matched_markers": matched}
    if is_home_page(hierarchy):
        return {"state": "home", "matched_markers": _matched_markers(hierarchy, HOME_MARKERS)}
    return {"state": "unknown", "matched_markers": matched}


def is_keyword_input_page(hierarchy: str) -> bool:
    if _has_risk_marker(hierarchy):
        return False
    if _has_editable_input(hierarchy):
        return True
    if _is_result_list_hierarchy(hierarchy) or is_home_page(hierarchy):
        return False
    has_cancel = "取消" in hierarchy
    has_input_signal = _has_any(hierarchy, KEYWORD_INPUT_MARKERS)
    return has_cancel and has_input_signal


def is_home_page(hierarchy: str) -> bool:
    if not hierarchy:
        return False
    if "search_bar_container" in hierarchy or 'content-desc="搜索栏"' in hierarchy:
        return True
    if 'content-desc="首页"' in hierarchy and 'selected="true"' in hierarchy:
        return True
    return "淘宝" in hierarchy and "搜索" in hierarchy and ("拍照" in hierarchy or "首页" in hierarchy)


def _has_selected_home_tab(hierarchy: str) -> bool:
    return 'content-desc="首页"' in hierarchy and 'selected="true"' in hierarchy


def detect_home_search_bar_point(hierarchy: str) -> tuple[float, float] | None:
    try:
        root = ET.fromstring(hierarchy)
    except ET.ParseError:
        return _detect_home_search_bar_point_with_regex(hierarchy)
    screen = _screen_size_from_xml(root)
    if screen is None:
        return None
    width, height = screen
    for node in root.iter():
        if node.attrib.get("content-desc") != "搜索栏":
            continue
        bounds = _parse_bounds(node.attrib.get("bounds", ""))
        if bounds is None:
            continue
        x1, y1, x2, y2 = bounds
        if x2 <= x1 or y2 <= y1:
            continue
        return ((x1 + x2) / 2 / width, (y1 + y2) / 2 / height)
    return None


def _is_result_list_hierarchy(hierarchy: str) -> bool:
    if _has_any(hierarchy, ("综合", "销量")) and _has_any(hierarchy, ("店铺", "宝贝", "商品")):
        return True
    matched = set(_matched_markers(hierarchy, RESULT_LIST_MARKERS))
    has_commerce_signal = bool(matched & {"¥", "已售", "人加购"})
    has_filter_signal = bool(matched & {"全部", "品牌", "官方自营"})
    has_shop_signal = bool(matched & {"旗舰店", "店", "国补专区"})
    return sum([has_commerce_signal, has_filter_signal, has_shop_signal]) >= 2


def _matched_markers(hierarchy: str, markers: tuple[str, ...]) -> list[str]:
    return [marker for marker in markers if marker and marker in hierarchy]


def _has_editable_input(hierarchy: str) -> bool:
    try:
        root = ET.fromstring(hierarchy)
    except ET.ParseError:
        if "android.widget.EditText" in hierarchy:
            return True
        return 'focused="true"' in hierarchy and (
            "输入商品" in hierarchy
            or "搜索宝贝" in hierarchy
            or "搜索商品" in hierarchy
            or "searchEdit" in hierarchy
        )
    for node in root.iter():
        package = node.attrib.get("package", "")
        if package and package != "com.taobao.taobao":
            continue
        class_name = node.attrib.get("class", "")
        resource_id = node.attrib.get("resource-id", "")
        if class_name == "android.widget.EditText":
            return True
        if resource_id.endswith(":id/searchEdit") and node.attrib.get("focused") == "true":
            return True
    return False


def _screen_size_from_xml(root: ET.Element) -> tuple[int, int] | None:
    max_x = 0
    max_y = 0
    for node in root.iter():
        bounds = _parse_bounds(node.attrib.get("bounds", ""))
        if bounds is None:
            continue
        _, _, x2, y2 = bounds
        max_x = max(max_x, x2)
        max_y = max(max_y, y2)
    if max_x <= 0 or max_y <= 0:
        return None
    return max_x, max_y


def _parse_bounds(value: str) -> tuple[int, int, int, int] | None:
    match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", value.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _detect_home_search_bar_point_with_regex(hierarchy: str) -> tuple[float, float] | None:
    search_match = re.search(
        r'content-desc="搜索栏"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        hierarchy,
    )
    if search_match is None:
        return None
    screen_match = re.search(r'bounds="\[0,0\]\[(\d+),(\d+)\]"', hierarchy)
    if screen_match is None:
        return None
    x1, y1, x2, y2 = (int(part) for part in search_match.groups())
    width, height = (int(part) for part in screen_match.groups())
    if width <= 0 or height <= 0:
        return None
    return ((x1 + x2) / 2 / width, (y1 + y2) / 2 / height)


def _push_reference_if_supported(
    device: TaobaoDevice, image_path: Path, run_id: str, config: TaobaoConfig
) -> None:
    push = getattr(device, "push_reference_image", None)
    if push is None:
        return
    push(image_path, run_id, config.remote_image_dir)


def _event(manifest: TaobaoManifest, name: str, payload: dict) -> None:
    manifest.step_count += 1
    event = {"source": "taobao_collector", "event": name, **payload}
    append_jsonl(manifest.output_dir / "step_events.jsonl", event)


def _prepare_output_dir(output_dir: Path) -> None:
    (output_dir / "images").mkdir(parents=True, exist_ok=True)
    (output_dir / "debug").mkdir(parents=True, exist_ok=True)
    (output_dir / "step_events.jsonl").touch()
    (output_dir / "risk_events.jsonl").touch()


def _request_with_config_defaults(
    request: TaobaoRequest, config: TaobaoConfig
) -> TaobaoRequest:
    mode = request.mode or config.mode
    if mode not in {"image_search", "keyword_search", "both"}:
        raise ValueError("mode must be one of: both, image_search, keyword_search")
    top_n = request.top_n if request.top_n > 0 else config.top_n
    return TaobaoRequest(
        mode=mode,
        input_image=request.input_image,
        keyword=request.keyword,
        keywords=request.keywords,
        top_n=top_n,
    )


def _scroll_result_page(
    manifest: TaobaoManifest,
    device: TaobaoDevice,
    config: TaobaoConfig,
    query: str,
) -> bool:
    device.swipe_profile_points(
        "result_page_next",
        config.result_page_scroll_start,
        config.result_page_scroll_end,
        duration=0.35,
    )
    _event(
        manifest,
        "taobao_scroll_result_page_next",
        {
            "query": query,
            "start": list(config.result_page_scroll_start),
            "end": list(config.result_page_scroll_end),
        },
    )
    if config.throttle_seconds:
        time.sleep(min(config.throttle_seconds, 0.5))
    if _wait_for_result_page(device, config.wait_timeout_seconds, manifest=manifest):
        _event(
            manifest,
            "taobao_result_page_reached_after_scroll",
            {"query": query, "page_state": classify_page_state(device.dump_hierarchy())},
        )
        return True
    return False


class _TaobaoRiskStop(Exception):
    def __init__(self, event: dict) -> None:
        super().__init__(event.get("event", "taobao_risk_stop"))
        self.event = event
