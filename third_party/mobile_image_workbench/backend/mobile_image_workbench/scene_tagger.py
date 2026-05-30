from __future__ import annotations

import base64
import hashlib
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from .asset_library import AssetLibrary


PROMPT_VERSION = "v2"
DEFAULT_QWEN_VL_MODEL = "qwen-vl-max"
DEFAULT_DASHSCOPE_COMPATIBLE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
SYSTEM_PROMPT = (
    "你是素材中心的图片场景标签助手。只识别图片场景，不判断品类。"
    "必须输出 JSON，包含 primary_scene、scene_tags、confidence。"
)


@dataclass(frozen=True)
class SceneTagResult:
    scene_tags: list[str]
    confidence: str = "medium"
    raw_response: dict[str, Any] | None = None
    primary_scene: str = ""


@dataclass(frozen=True)
class SceneTagInput:
    asset_id: str
    category: str
    query: str
    source_keyword: str
    filename: str
    mime_type: str
    image_bytes: bytes
    object_key: str = ""


class SceneTagger(Protocol):
    model: str
    prompt_version: str

    def tag(self, payload: SceneTagInput) -> SceneTagResult:
        ...


class StaticSceneTagger:
    def __init__(
        self,
        result: SceneTagResult,
        *,
        model: str = "static-scene-tagger",
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        self.result = result
        self.model = model
        self.prompt_version = prompt_version

    def tag(self, payload: SceneTagInput) -> SceneTagResult:
        return self.result


class RuleSceneTagger:
    def __init__(
        self, *, model: str = "rule-scene-tagger", prompt_version: str = PROMPT_VERSION
    ) -> None:
        self.model = model
        self.prompt_version = prompt_version

    def tag(self, payload: SceneTagInput) -> SceneTagResult:
        text = f"{payload.query} {payload.source_keyword} {payload.filename}"
        tags: list[str] = []
        if any(token in text for token in ("买家秀", "实拍", "晒图")):
            tags.append("买家秀")
        if any(token in text for token in ("白底", "白色背景")):
            tags.append("白底展示")
        if any(token in text for token in ("餐桌", "餐厅", "桌面")):
            tags.append("餐桌布置")
        if any(token in text for token in ("红格", "格纹", "格子")):
            tags.append("红白格")
        if not tags:
            tags.append("未识别场景")
        normalized = _normalize_tags(tags)
        return SceneTagResult(normalized, "medium", {"scene_tags": tags}, normalized[0])


class OpenAICompatibleSceneTagger:
    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        prompt_version: str = PROMPT_VERSION,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.model = model
        self.api_key = (
            api_key
            or os.environ.get("DASHSCOPE_API_KEY")
            or os.environ.get("QWEN_API_KEY")
            or os.environ.get("VLM_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        )
        self.base_url = (base_url or default_vlm_base_url(self.model)).rstrip("/")
        self.prompt_version = prompt_version
        self.timeout_seconds = timeout_seconds

    def tag(self, payload: SceneTagInput) -> SceneTagResult:
        if not self.api_key:
            raise RuntimeError(
                "missing VLM API key; set DASHSCOPE_API_KEY, QWEN_API_KEY, VLM_API_KEY, or OPENAI_API_KEY"
            )
        request_payload = self._request_payload(payload)
        request = urllib.request.Request(
            self._endpoint(),
            data=json.dumps(request_payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"VLM request failed: {exc}") from exc
        content = (
            response_payload.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "{}")
        )
        parsed = _parse_json_object(content)
        primary_scene = _normalize_one_tag(parsed.get("primary_scene"))
        return SceneTagResult(
            _normalize_tags(parsed.get("scene_tags") or parsed.get("tags") or []),
            str(parsed.get("confidence") or "medium"),
            response_payload,
            primary_scene,
        )

    def debug_request(
        self, payload: SceneTagInput, *, local_image_path: str = ""
    ) -> dict[str, Any]:
        image_url = _data_url(payload.image_bytes, payload.mime_type)
        prefix = _data_url_prefix(payload.mime_type)
        system_prompt, user_text = _scene_prompt(payload)
        return {
            "model": self.model,
            "endpoint": self._endpoint(),
            "assetId": payload.asset_id,
            "objectKey": payload.object_key,
            "category": payload.category,
            "query": payload.query,
            "sourceKeyword": payload.source_keyword,
            "filename": payload.filename,
            "mimeType": payload.mime_type or "image/jpeg",
            "localImagePath": local_image_path,
            "promptVersion": self.prompt_version,
            "prompt": {
                "system": system_prompt,
                "userText": user_text,
            },
            "imageBytes": _image_bytes_debug(payload.image_bytes),
            "imageUrl": {
                "prefix": prefix,
                "totalLength": len(image_url),
                "preview": f"{prefix}<redacted:{max(0, len(image_url) - len(prefix))} chars>",
            },
        }

    def _endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _request_payload(self, payload: SceneTagInput) -> dict[str, Any]:
        system_prompt, user_text = _scene_prompt(payload)
        return {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": _data_url(payload.image_bytes, payload.mime_type)
                            },
                        },
                    ],
                },
            ],
        }


def build_scene_tagger(provider: str, *, model: str) -> SceneTagger:
    if provider == "rule":
        return RuleSceneTagger(model=model or "rule-scene-tagger")
    if provider == "openai_compatible":
        return OpenAICompatibleSceneTagger(model=model or default_vlm_model())
    raise ValueError(f"unsupported scene tagger provider: {provider}")


def default_vlm_model() -> str:
    return (
        os.environ.get("DASHSCOPE_VLM_MODEL")
        or os.environ.get("QWEN_VLM_MODEL")
        or os.environ.get("VLM_MODEL")
        or DEFAULT_QWEN_VL_MODEL
    )


def default_vlm_base_url(model: str | None = None) -> str:
    explicit_dashscope = os.environ.get("DASHSCOPE_BASE_URL") or os.environ.get(
        "QWEN_BASE_URL"
    )
    if explicit_dashscope:
        return explicit_dashscope
    model_name = (model or default_vlm_model()).lower()
    uses_qwen = model_name.startswith("qwen") or bool(
        os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY")
    )
    if uses_qwen:
        return DEFAULT_DASHSCOPE_COMPATIBLE_BASE_URL
    return os.environ.get("OPENAI_BASE_URL") or DEFAULT_DASHSCOPE_COMPATIBLE_BASE_URL


def tag_missing_scene_assets(
    library: AssetLibrary,
    tagger: SceneTagger,
    *,
    category: str = "",
    run_id: str = "",
    job_id: str = "",
    limit: int = 100,
    dry_run: bool = False,
    retry_failed: bool = False,
    force: bool = False,
    debug_request: bool = False,
) -> dict[str, Any]:
    candidates = library.scene_tag_candidates(
        category=category,
        run_id=run_id,
        job_id=job_id,
        limit=limit,
        retry_failed=retry_failed,
        force=force,
    )
    summary = {
        "dry_run": dry_run,
        "candidates": len(candidates),
        "tagged": 0,
        "failed": 0,
        "cache_hits": 0,
        "vlm_calls": 0,
        "debug_requests": [],
        "assets": [],
    }
    for candidate in candidates:
        asset_id = str(candidate["assetId"])
        image_bytes: bytes | None = None
        payload: SceneTagInput | None = None
        if debug_request:
            try:
                image_bytes = library.asset_image_bytes(asset_id)
                payload = _scene_tag_input_from_candidate(
                    candidate,
                    image_bytes,
                    category=category,
                )
                summary["debug_requests"].append(
                    _safe_debug_request(
                        tagger,
                        payload,
                        local_image_path=library.asset_local_path(asset_id),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - keep debugging side-effect safe
                summary["debug_requests"].append(
                    {
                        "assetId": asset_id,
                        "objectKey": str(candidate.get("objectKey") or ""),
                        "error": str(exc),
                    }
                )
        if dry_run and debug_request:
            if payload is None:
                summary["failed"] += 1
                summary["assets"].append(
                    {
                        "assetId": asset_id,
                        "status": "failed",
                        "reason": "debug request could not be built",
                    }
                )
            else:
                summary["assets"].append(
                    {"assetId": asset_id, "status": "debugged"}
                )
            continue
        tags = None
        if not force:
            tags = library.cached_scene_tags(
                str(candidate["contentSha256"]),
                model=tagger.model,
                prompt_version=tagger.prompt_version,
            )
        raw_response: dict[str, Any] | None = None
        if tags:
            summary["cache_hits"] += 1
            confidence = "cached"
        else:
            try:
                image_bytes = image_bytes or library.asset_image_bytes(asset_id)
                payload = payload or _scene_tag_input_from_candidate(
                    candidate,
                    image_bytes,
                    category=category,
                )
                result = tagger.tag(payload)
                tags = _scene_tag_set(
                    result.primary_scene,
                    result.scene_tags,
                    category=str(candidate.get("category") or category),
                )
                raw_response = result.raw_response or {
                    "primary_scene": tags[0] if tags else "",
                    "scene_tags": tags,
                    "confidence": result.confidence,
                }
                confidence = result.confidence
                summary["vlm_calls"] += 1
            except Exception as exc:  # noqa: BLE001 - record per-asset failure and continue
                summary["failed"] += 1
                summary["assets"].append(
                    {"assetId": asset_id, "status": "failed", "reason": str(exc)}
                )
                if not dry_run:
                    library.mark_scene_tag_failed(
                        asset_id,
                        model=tagger.model,
                        prompt_version=tagger.prompt_version,
                        reason=str(exc),
                    )
                continue
        if not dry_run:
            library.apply_scene_tags(
                asset_id,
                tags,
                model=tagger.model,
                prompt_version=tagger.prompt_version,
                raw_response=raw_response or {"scene_tags": tags, "confidence": confidence},
            )
            summary["tagged"] += 1
        summary["assets"].append(
            {"assetId": asset_id, "status": "tagged", "sceneTags": tags}
        )
    return summary


def _data_url(payload: bytes, mime_type: str) -> str:
    return f"{_data_url_prefix(mime_type)}{base64.b64encode(payload).decode('ascii')}"


def _data_url_prefix(mime_type: str) -> str:
    return f"data:{mime_type or 'image/jpeg'};base64,"


def _image_bytes_debug(payload: bytes) -> dict[str, Any]:
    return {
        "length": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _scene_prompt(payload: SceneTagInput) -> tuple[str, str]:
    return (
        SYSTEM_PROMPT,
        (
            f"固定品类：{payload.category or '未指定'}。\n"
            f"关键词线索：{payload.query or payload.source_keyword or '无'}。\n"
            "请只识别场景和画面特征，不判断品类。\n"
            "请返回 JSON："
            "{\"primary_scene\":\"稳定主场景\","
            "\"scene_tags\":[\"细标签1\",\"细标签2\"],"
            "\"confidence\":\"high|medium|low\"}。\n"
            "primary_scene 只能选 1 个中文短词，例如：餐桌布置、厨房台面、买家秀实拍、白底展示、节日布置、户外露台。\n"
            "scene_tags 返回 4-6 个中文短标签，使用半受控维度：空间/用途、展示方式、颜色图案、材质质感、构图氛围。\n"
            "优先输出具体词，例如：红白格、桌面俯拍、自然光、棉麻质感、暖色家居、近景细节。\n"
            "不要输出品类词本身，例如桌垫、餐垫、桌布；不要输出长句；同义词合并为一个短词。"
        ),
    )


def _scene_tag_input_from_candidate(
    candidate: dict[str, Any], image_bytes: bytes, *, category: str
) -> SceneTagInput:
    return SceneTagInput(
        asset_id=str(candidate["assetId"]),
        object_key=str(candidate.get("objectKey") or ""),
        category=str(candidate.get("category") or category),
        query=str(candidate.get("query") or ""),
        source_keyword=str(candidate.get("sourceKeyword") or ""),
        filename=str(candidate.get("filename") or ""),
        mime_type=str(candidate.get("mimeType") or "image/jpeg"),
        image_bytes=image_bytes,
    )


def _safe_debug_request(
    tagger: SceneTagger, payload: SceneTagInput, *, local_image_path: str = ""
) -> dict[str, Any]:
    debug_builder = getattr(tagger, "debug_request", None)
    if callable(debug_builder):
        return debug_builder(payload, local_image_path=local_image_path)
    return {
        "model": tagger.model,
        "assetId": payload.asset_id,
        "objectKey": payload.object_key,
        "category": payload.category,
        "query": payload.query,
        "sourceKeyword": payload.source_keyword,
        "filename": payload.filename,
        "mimeType": payload.mime_type or "image/jpeg",
        "localImagePath": local_image_path,
        "promptVersion": tagger.prompt_version,
        "imageBytes": _image_bytes_debug(payload.image_bytes),
        "imageUrl": {
            "prefix": _data_url_prefix(payload.mime_type),
            "totalLength": len(_data_url(payload.image_bytes, payload.mime_type)),
            "preview": (
                f"{_data_url_prefix(payload.mime_type)}"
                f"<redacted:{len(base64.b64encode(payload.image_bytes).decode('ascii'))} chars>"
            ),
        },
    }


def _parse_json_object(value: str) -> dict[str, Any]:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        start = value.find("{")
        end = value.rfind("}")
        if start >= 0 and end > start:
            return json.loads(value[start : end + 1])
        raise


def _normalize_tags(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        tag = " ".join(str(value).strip().split())
        if not tag or tag in seen:
            continue
        seen.add(tag)
        result.append(tag)
        if len(result) >= 6:
            break
    return result or ["未识别场景"]


def _normalize_one_tag(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _scene_tag_set(
    primary_scene: str, scene_tags: list[str], *, category: str = ""
) -> list[str]:
    blocked = {_normalize_one_tag(category), "桌垫", "餐垫", "桌布"}
    result: list[str] = []
    seen: set[str] = set()
    for value in [primary_scene, *scene_tags]:
        tag = _normalize_one_tag(value)
        if not tag or tag in blocked or tag in seen:
            continue
        seen.add(tag)
        result.append(tag)
        if len(result) >= 7:
            break
    return result or ["未识别场景"]
