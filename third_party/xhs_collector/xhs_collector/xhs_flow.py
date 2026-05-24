from __future__ import annotations

import asyncio
from pathlib import Path

from .device import ensure_mobilerun_import_path
from .media_store import MediaStore, diff_new_media
from .models import CollectedImage, CollectorConfig, InputItem


SAFETY_TEXT = (
    "安全边界：只能使用用户已经手动登录的小红书账号；遇到登录页、验证码、风控、"
    "权限弹窗或需要人工确认的步骤，立即停止并说明原因。不要绕过平台安全，不要收集"
    "账号密码，不要使用代理、指纹伪装或任何反爬规避。"
)
LOW_QUALITY_FILTER_TEXT = "过滤低质结果：主图、详情页、白底图、摄影棚、效果图、渲染图、商拍、海报。"


def _keyword_block(item: InputItem) -> str:
    candidates = item.keyword_candidates or [item.keyword]
    return "\n".join(f"{index}. {keyword}" for index, keyword in enumerate(candidates, 1))


def build_xhs_prompt(item: InputItem, remote_reference_path: str) -> str:
    keyword_line = _keyword_block(item)
    return (
        f"{SAFETY_TEXT}\n\n"
        "任务：在小红书 App 内使用图搜图能力采集相似图。\n"
        f"参考图已放在手机相册路径：{remote_reference_path}\n"
        f"TOP 关键词组合，用于筛选结果：\n{keyword_line}\n"
        f"{LOW_QUALITY_FILTER_TEXT}\n"
        "优先保存视觉相似、命中任一 TOP 关键词组合，并且是真实买家秀/实拍/居家场景的结果。"
        f"按质量保存 TOP {item.top_n} 张图片到系统相册。\n"
        "只使用 App 内公开可见的保存图片能力。如果没有保存入口或结果不足，保存能确认的图片后结束。"
    )


def build_xhs_rank_prompt(
    item: InputItem, remote_reference_path: str, rank: int, already_saved: int
) -> str:
    keyword_line = _keyword_block(item)
    return (
        f"{SAFETY_TEXT}\n\n"
        "任务：继续在小红书 App 内使用图搜图结果保存一张图片。\n"
        f"参考图手机相册路径：{remote_reference_path}\n"
        f"TOP 关键词组合，用于筛选结果：\n{keyword_line}\n"
        f"{LOW_QUALITY_FILTER_TEXT}\n"
        f"目标：保存 TOP {item.top_n} 中第 {rank} 张候选图；此前已保存 {already_saved} 张。\n"
        "如果当前不在图搜图结果页，请回到图搜图并选择参考图。"
        "只保存一张新的、与参考图视觉相似、命中任一 TOP 关键词组合、且是真实买家秀/实拍/居家场景的图片到系统相册，然后结束。"
        "如果遇到登录、验证码、风控、权限弹窗或没有保存入口，立即停止并说明原因。"
    )


async def collect_item_with_mobilerun(
    item: InputItem,
    config: CollectorConfig,
    remote_reference_path: str,
    output_item_dir: Path,
    media_store: MediaStore,
) -> tuple[list[CollectedImage], str]:
    ensure_mobilerun_import_path()
    from mobilerun import MobileAgent, MobileConfig

    config_obj = MobileConfig()
    config_obj.agent.vision_only = bool(config.vision_only)
    config_obj.agent.fast_agent.vision = True
    config_obj.device.serial = config.device_serial

    images: list[CollectedImage] = []
    previous_snapshot = await media_store.snapshot()

    for rank in range(1, item.top_n + 1):
        prompt = build_xhs_rank_prompt(
            item, remote_reference_path, rank=rank, already_saved=len(images)
        )
        agent = MobileAgent(goal=prompt, config=config_obj, timeout=1000)
        result = await agent.run()
        if not result.success:
            return images, str(result.reason)
        await asyncio.sleep(config.throttle_seconds)
        current_snapshot = await media_store.snapshot()
        new_paths = diff_new_media(previous_snapshot, current_snapshot)
        if not new_paths:
            return images, "no new saved image was detected after agent step"
        remote_path = new_paths[0]
        suffix = Path(remote_path).suffix or ".jpg"
        local_path = output_item_dir / f"rank_{rank:03d}{suffix}"
        await media_store.pull(remote_path, local_path)
        images.append(
            CollectedImage(rank=rank, local_path=local_path, device_path=remote_path)
        )
        previous_snapshot = current_snapshot
    return images, f"saved {len(images)} image(s)"
