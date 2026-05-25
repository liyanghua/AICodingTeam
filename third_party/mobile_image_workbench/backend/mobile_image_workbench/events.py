from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


DEFAULT_RISK_MESSAGES = {
    "login_required": "需要人工处理：请在手机上完成小红书登录",
    "captcha_required": "需要人工处理：手机上出现验证码或安全验证",
    "risk_control": "需要人工处理：平台提示账号或操作风险",
    "permission_prompt": "需要人工处理：请在手机上确认照片/相册权限",
    "device_input_permission_required": "需要人工处理：新手机未允许自动点击，请开启 USB 调试相关安全权限后重试",
}

DEFAULT_STEP_MESSAGES = {
    "job_started": "采集任务已启动，正在准备输入文件",
    "prepare_config_file": "正在读取项目文件夹和 Excel 配置",
    "prepare_uploaded_images": "正在整理上传的参考图片",
    "collector_config_ready": "采集参数已准备完成",
    "collector_started": "正在启动手机采集引擎",
    "collector_completed": "采集已完成，正在生成下载结果",
    "result_exports_ready": "结果文件已生成，可以下载查看",
    "asset_center_ready": "采集图片已进入素材中心",
    "start_app": "正在打开小红书",
    "wait_app_start_settle": "等待小红书首页加载完成",
    "push_reference": "正在把参考图发送到手机相册",
    "tap_search_box": "正在进入搜索",
    "wait_search_page_after_search_box": "正在确认搜索页是否打开",
    "search_box_click_not_on_search_page": "搜索入口没有打开搜索页，正在重试",
    "back_after_search_box_miss": "已返回首页，准备重新进入搜索",
    "search_page_not_reached_after_retries": "多次尝试后仍未进入搜索页，请检查搜索入口坐标或首页加载状态",
    "tap_image_search_button": "正在打开小红书图搜",
    "wait_album_page_after_image_search_button": "正在确认图搜相册页是否打开",
    "image_search_button_click_not_on_album_page": "图搜入口没有打开相册页，正在重试",
    "back_after_image_search_button_miss": "已返回搜索页，准备重新打开图搜",
    "image_search_album_not_reached_after_retries": "多次尝试后仍未进入图搜相册页，请检查图搜按钮坐标",
    "tap_album_entry": "正在打开手机相册",
    "tap_first_album_image": "正在选择参考图",
    "tap_album_confirm": "正在确认选择图片",
    "album_grid_not_ready": "手机相册没有加载完成",
    "album_thumbnail_not_found": "没有识别到相册中的参考图缩略图",
    "album_image_not_selected": "参考图没有被选中，请检查相册缩略图位置",
    "album_confirm_failed": "选择图片确认失败",
    "wait_image_search_results": "等待小红书生成图搜结果",
    "wait_subject_recognition": "等待小红书完成主体识别",
    "swipe_image_search_results_panel_fullscreen": "正在展开图搜笔记结果列表",
    "swipe_keyword_search_results_panel_fullscreen": "正在展开关键词笔记结果列表",
    "duplicate_saved_media": "发现重复图片，已跳过",
    "save_rank_failed": "当前笔记无法保存，继续下一张",
    "stage_scroll_limit_reached": "已达到翻页上限，本阶段部分完成",
    "stage_download_limit_reached": "本阶段采集数量已达目标",
    "keyword_search_plan": "正在确认是否需要关键词筛选",
    "keyword_search_results_reached": "关键词结果页已打开",
    "back_to_results": "正在返回笔记列表",
    "item.started": "开始处理原图",
}


def _load_i18n(locale: str) -> dict[str, Any]:
    config_path = (
        Path(__file__).resolve().parents[2] / "config" / "i18n" / f"{locale}.json"
    )
    if not config_path.exists():
        return {}
    return json.loads(config_path.read_text(encoding="utf-8"))


_LOCALE = "zh-CN"
_I18N = _load_i18n(_LOCALE)
RISK_MESSAGES = {**DEFAULT_RISK_MESSAGES, **(_I18N.get("risk") or {})}
STEP_MESSAGES = {**DEFAULT_STEP_MESSAGES, **(_I18N.get("steps") or {})}
FALLBACK_MESSAGES = {
    "unknown_step": "正在执行采集步骤",
    **(_I18N.get("fallback") or {}),
}


def translate_event(raw: dict[str, Any]) -> dict[str, Any]:
    event_name = str(raw.get("name") or raw.get("event") or "event")
    source = str(raw.get("source") or "collector")
    level = "info"
    if _is_attention_event(event_name, raw):
        level = "needs_attention"
    elif event_name in {
        "save_rank_failed",
        "duplicate_saved_media",
        "stage_scroll_limit_reached",
        "note_card_not_opened",
        "album_grid_not_ready",
        "album_thumbnail_not_found",
        "album_image_not_selected",
        "album_confirm_failed",
        "image_search_button_click_not_on_album_page",
        "image_search_album_not_reached_after_retries",
        "skip_result_card_category_mismatch",
        "job_failed",
    }:
        level = "warning"
    message = _message_for(event_name, raw)
    return {
        "eventKey": event_key_for(raw),
        "source": source,
        "name": event_name,
        "level": level,
        "message": message,
        "itemId": raw.get("item_id"),
        "stage": raw.get("stage"),
        "rank": raw.get("rank"),
        "query": raw.get("query"),
        "raw": raw,
    }


def read_translated_events(run_dir: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for log_name, source in (
        ("events.jsonl", "collector"),
        ("step_events.jsonl", "collector"),
        ("risk_events.jsonl", "risk"),
    ):
        log_path = run_dir / log_name
        if not log_path.exists():
            continue
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            raw.setdefault("source", source)
            events.append(translate_event(raw))
    return events


def event_key_for(raw: dict[str, Any]) -> str:
    event_name = str(raw.get("name") or raw.get("event") or "event")
    return "|".join(
        str(part or "")
        for part in (
            raw.get("source") or "collector",
            event_name,
            raw.get("step"),
            raw.get("item_id") or raw.get("itemId"),
            raw.get("stage"),
            raw.get("rank"),
            raw.get("query"),
        )
    )


def _message_for(event_name: str, raw: dict[str, Any]) -> str:
    if event_name in RISK_MESSAGES:
        return RISK_MESSAGES[event_name]
    if _is_input_injection_permission_failure(raw):
        return RISK_MESSAGES["device_input_permission_required"]
    dynamic_message = _dynamic_message_for(event_name, raw)
    if dynamic_message is not None:
        return dynamic_message
    if event_name == "job_failed":
        return f"采集任务失败：{raw.get('message') or raw.get('reason') or '请检查任务配置'}"
    if event_name == "item.started":
        keyword = raw.get("keyword") or raw.get("item_id") or ""
        return f"开始处理原图：{keyword}".strip("：")
    if event_name == "start_keyword_search_query":
        return f"开始关键词筛选：{raw.get('query') or ''}".strip("：")
    if event_name == "finish_keyword_search_query":
        query = raw.get("query") or ""
        count = raw.get("downloaded_count", 0)
        return f"关键词「{query}」采集完成，已保存 {count} 张"
    download = re.match(r"download_(image_search|keyword_search)_rank_(\d+)", event_name)
    if download:
        stage, rank = download.groups()
        if stage == "keyword_search":
            query = raw.get("query") or ""
            return f"已保存关键词「{query}」结果第 {int(rank)} 张"
        return f"已保存图搜结果第 {int(rank)} 张"
    if event_name == "save_rank_failed":
        reason = raw.get("reason")
        if reason == "download_permission_disabled":
            return "作者关闭下载权限，已记录并继续下一张"
    if event_name == "duplicate_saved_media":
        return "发现重复图片，已跳过"
    if event_name == "note_card_not_opened":
        return "当前笔记卡片未能打开，已跳过"
    return STEP_MESSAGES.get(event_name, FALLBACK_MESSAGES["unknown_step"])


def _dynamic_message_for(event_name: str, raw: dict[str, Any]) -> str | None:
    stable = re.match(r"wait_(image_search|keyword_search)_result_list_stable", event_name)
    if stable:
        stage = stable.group(1)
        return f"正在等待{_stage_label(stage)}笔记列表加载完成"
    open_card = re.match(
        r"open_(image_search|keyword_search)_result_card_rank_(\d+)", event_name
    )
    if open_card:
        stage, rank = open_card.groups()
        return f"正在打开{_stage_label(stage)}结果第 {int(rank)} 条笔记"
    retry_card = re.match(
        r"retry_open_(image_search|keyword_search)_result_card_rank_(\d+)",
        event_name,
    )
    if retry_card:
        stage, rank = retry_card.groups()
        return f"正在重新打开{_stage_label(stage)}结果第 {int(rank)} 条笔记"
    pull_saved = re.match(r"pull_saved_image_rank_(\d+)", event_name)
    if pull_saved:
        return f"正在把手机保存的第 {int(pull_saved.group(1))} 张图片同步到本地"
    wait_back = re.match(
        r"wait_back_to_(image_search|keyword_search)_result_list_rank_(\d+)",
        event_name,
    )
    if wait_back:
        stage, _rank = wait_back.groups()
        return f"正在确认已回到{_stage_label(stage)}笔记列表"
    scroll = re.match(r"scroll_(image_search|keyword_search)_result_list", event_name)
    if scroll:
        return f"正在翻页寻找更多{_stage_label(scroll.group(1))}笔记"
    return None


def _stage_label(stage: str) -> str:
    return "图搜" if stage == "image_search" else "关键词"


def _is_attention_event(event_name: str, raw: dict[str, Any]) -> bool:
    return (
        event_name in RISK_MESSAGES
        or event_name.endswith("_required")
        or _is_input_injection_permission_failure(raw)
    )


def _is_input_injection_permission_failure(raw: dict[str, Any]) -> bool:
    text = f"{raw.get('reason') or ''} {raw.get('message') or ''}"
    return "INJECT_EVENTS" in text or "Injecting input events" in text
