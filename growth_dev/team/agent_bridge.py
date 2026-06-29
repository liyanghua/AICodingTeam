"""Agent Bridge for app_generation workbench right panel.

Provides Provider abstraction (codex, pi_agent) for the Agent collaboration layer.

Design contract (see docs/app_generation_agent_bridge_spec.md):
- Middle node area is the source of truth; the right Agent area is a collaboration layer.
- Agent receives NodeContext and returns a message plus confirmable AgentActions.
- AgentActions are deterministic and structured; the conversational message may come
  from a real LLM when credentials are configured.
- codex is the default Provider and is always available via a deterministic baseline.
  When .env credentials exist, the conversational message is upgraded by a real LLM call.
- pi_agent is a switchable Provider that reports not_configured until wired.
- usage must reflect the real provider response; missing values render as "unknown".
"""

import atexit
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator
from urllib import error, request

SECRET_REPLACEMENTS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{6,}"), "<redacted-secret>"),
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{6,}"), "<redacted-secret>"),
    (re.compile(r"(?i)(AICODEMIRROR_KEY\s*[:=]\s*)[^\s,;'\"\n]+"), r"\1<redacted>"),
    (re.compile(r"(?i)((api[_-]?key|secret|token|password|anthropic[_-]?api[_-]?key|openai[_-]?api[_-]?key)\s*[:=]\s*)[^\s,;'\"\n]+"), r"\1<redacted>"),
]

UNKNOWN_USAGE = {
    "prompt_tokens": "unknown",
    "completion_tokens": "unknown",
    "total_tokens": "unknown",
    "estimated_cost": "unknown",
}


# Right-side dialog boundary: PI = understand + suggest. Suggestions reach the
# workbench as confirmable AgentActions, never as autonomous side effects. The
# protocol below is appended to every pi prompt so the model knows how to emit
# structured suggestions the Provider can parse without prose heuristics.
PI_ALLOWED_ACTION_TYPES: tuple[str, ...] = (
    "explain_node",
    "explain_step",
    "explain_step_io",
    "inspect_evidence",
    "rerun_step",
    "compare_variants",
    "read_artifact",
    "suggest_input_patch",
    "suggest_artifact_patch",
    "suggest_artifact_regeneration",
    "rerun_from_node",
    "select_variant",
    "ask_clarification",
    "patch_app",
    "delegate_code_repair",
    "patch_artifact",
    "diagnose_app_bug",
    "verify_patch",
    "rollback_patch",
    "promote_patch_to_generation_rule",
)

_PI_TRAILING_ACTIONS_PROTOCOL = (
    "结构化建议协议（可选，但强烈建议）：\n"
    "- 给出自然语言解释后，在回答最末输出一个 fenced JSON 块：\n"
    "  ```json\n"
    "  {\"actions\": [{\"type\": \"...\", \"summary\": \"...\", \"requires_confirmation\": true}]}\n"
    "  ```\n"
    f"- type 必须取自：{', '.join(PI_ALLOWED_ACTION_TYPES)}。\n"
    "- app_preview 下遇到报错、not configured、timeout、模型、provider、API key、生图、按钮、下载、局部迭代，优先输出 patch_app 或 delegate_code_repair，不要只解释节点。\n"
    "- 路由：单 token / 单锚点可逐字定位（换模型名、改文案、单点配置）→ patch_app；多文件 / 加功能 / 改逻辑 / 跨函数联动 / 说不清具体行 → delegate_code_repair。\n"
    "- patch_app 使用 PatchSet：{\"type\":\"patch_app\",\"patches\":[{\"target_path\":\"generated_apps/<slug>/server.js\",\"edit_kind\":\"replace_text\",\"old_content\":\"从 app_patch_targets.agent_edit_anchors 逐字复制\",\"new_content\":\"修改后内容\"}],\"preserve_capabilities\":[\"已通过能力\"],\"verification\":[\"node --check server.js\",\"GET /api/health\"],\"problem_source\":\"app_preview\",\"requires_confirmation\":true}。\n"
    "- old_content 必须从 AgentPromptContext.app_patch_targets[].agent_edit_anchors[].old_content 逐字复制，不允许凭空生造。\n"
    "- delegate_code_repair 只描述问题与目标，不写 diff：{\"type\":\"delegate_code_repair\",\"target\":\"published_app\",\"problem_source\":\"app_preview\",\"repair_request\":{\"app_slug\":\"<slug>\",\"problem\":\"问题陈述\",\"constraints\":[\"只修改当前已发布应用\",\"不重跑 PRD\",\"保留现有工作流\"],\"expected_behavior\":[\"期望行为\"],\"verification\":[\"node --check server.js\"]},\"requires_confirmation\":true}。\n"
    "- 无法定位唯一锚点、或改动跨多处时，输出 delegate_code_repair 交给 Code Agent，不要输出空 patches 的 patch_app，也不要硬凑多个 replace_text。\n"
    "- 不要在回答中夹带或复述完整文件原文；建议改动放进 PatchSet。\n"
    "- 若没有可执行建议，省略该 JSON 块即可。"
)


_TRAILING_JSON_RE = re.compile(
    r"```json\s*(\{(?:[^`]|`(?!``))*?\})\s*```\s*$",
    re.DOTALL,
)


def _parse_trailing_actions(
    text: str,
    *,
    context_revision: str = "",
) -> tuple[str, list[dict[str, Any]] | None]:
    """Strip the trailing ```json {"actions":[...]} ``` block from PI's answer.

    Returns (cleaned_text, actions_or_none). actions_or_none is None when there
    is no parseable block at the tail; an empty list signals "model explicitly
    said: no suggestion". Unknown action types are filtered, not raised, so a
    typo in PI's output degrades to the deterministic baseline at the call site
    instead of crashing the turn.
    """
    if not text:
        return text, None
    match = _TRAILING_JSON_RE.search(text)
    if not match:
        return text, None
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        return text, None
    if not isinstance(parsed, dict):
        return text, None
    raw_actions = parsed.get("actions")
    if not isinstance(raw_actions, list):
        return text, None
    cleaned: list[dict[str, Any]] = []
    for entry in raw_actions:
        if not isinstance(entry, dict):
            continue
        action_type = entry.get("type")
        if action_type not in PI_ALLOWED_ACTION_TYPES:
            continue
        normalized: dict[str, Any] = {
            k: v for k, v in entry.items() if isinstance(k, str)
        }
        normalized["type"] = action_type
        normalized.setdefault("requires_confirmation", True)
        normalized.setdefault("source", "pi_agent")
        if context_revision and not normalized.get("context_revision"):
            normalized["context_revision"] = context_revision
        cleaned.append(normalized)
    return text[: match.start()].rstrip(), cleaned


def _patch_app_action_is_executable(action: dict[str, Any]) -> bool:
    if action.get("type") != "patch_app":
        return True
    patches = action.get("patches")
    if isinstance(patches, list) and patches:
        return all(
            isinstance(patch, dict)
            and bool(str(patch.get("target_path") or "").strip())
            and bool(str(patch.get("edit_kind") or "").strip())
            for patch in patches
        )
    return bool(str(action.get("target_path") or "").strip() and str(action.get("edit_kind") or "").strip())


def _actions_have_patch_app(actions: list[dict[str, Any]]) -> bool:
    return any(action.get("type") == "patch_app" and _patch_app_action_is_executable(action) for action in actions)


def _safe_actions_with_patch_fallback(
    *,
    actions: list[dict[str, Any]],
    node_context: dict[str, Any],
    interaction_context: dict[str, Any] | None,
    resolved_intent: str,
    user_message: str,
    provider_text: str,
    prompt_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    safe_actions = [action for action in actions if _patch_app_action_is_executable(action)]
    if resolved_intent == "patch_app" and not _actions_have_patch_app(safe_actions):
        fallback_actions = _fallback_actions_for_provider_text(
            node_context=node_context,
            interaction_context=interaction_context,
            resolved_intent=resolved_intent,
            user_message=user_message,
            provider_text=provider_text,
            prompt_context=prompt_context,
        )
        if fallback_actions:
            if _actions_have_patch_app(fallback_actions):
                return [action for action in safe_actions if action.get("type") != "patch_app"] + fallback_actions
            return safe_actions or fallback_actions
        return safe_actions
    if resolved_intent == "delegate_code_repair" and not any(
        action.get("type") == "delegate_code_repair" for action in safe_actions
    ):
        fallback_actions = _fallback_actions_for_provider_text(
            node_context=node_context,
            interaction_context=interaction_context,
            resolved_intent=resolved_intent,
            user_message=user_message,
            provider_text=provider_text,
            prompt_context=prompt_context,
        )
        if fallback_actions:
            return safe_actions + [
                action for action in fallback_actions if action.get("type") == "delegate_code_repair"
            ]
    return safe_actions


def _redact_text(value: str) -> str:
    redacted = str(value)
    for pattern, replacement in SECRET_REPLACEMENTS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _read_env_file_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _codex_credentials(repo_root: Path) -> tuple[str, str]:
    env_values = _read_env_file_values(repo_root / ".env")
    base_url = (
        env_values.get("AICODEMIRROR_BASE_URL")
        or env_values.get("aicodemirror_base_url")
        or os.environ.get("AICODEMIRROR_BASE_URL", "")
    )
    api_key = (
        env_values.get("AICODEMIRROR_KEY")
        or env_values.get("aicodemirror_key")
        or os.environ.get("AICODEMIRROR_KEY", "")
    )
    return base_url, api_key


def _extract_model_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
            if isinstance(first.get("text"), str):
                return first["text"]
    if isinstance(payload.get("content"), str):
        return str(payload["content"])
    return ""


def _extract_usage(payload: dict[str, Any]) -> dict[str, Any]:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if isinstance(usage, dict):
        return {
            "prompt_tokens": usage.get("prompt_tokens", "unknown"),
            "completion_tokens": usage.get("completion_tokens", "unknown"),
            "total_tokens": usage.get("total_tokens", "unknown"),
            "estimated_cost": "unknown",
            "usage_source": "provider_api",
        }
    return {**UNKNOWN_USAGE, "usage_source": "unavailable"}


# ---------------------------------------------------------------------------
# Deterministic baseline (always available).
# ---------------------------------------------------------------------------


def _interaction_focus(interaction_context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(interaction_context, dict):
        return {}
    focus = interaction_context.get("focus")
    return focus if isinstance(focus, dict) else {}


def _canvas_selection(interaction_context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(interaction_context, dict):
        return {}
    selection = interaction_context.get("canvas_selection")
    if not isinstance(selection, dict):
        return {}
    if str(selection.get("selection_type") or "") not in {"canvas_object", "flow_step"}:
        return {}
    return selection


def _allowed_operations(interaction_context: dict[str, Any] | None) -> set[str]:
    if not isinstance(interaction_context, dict):
        return set()
    allowed: set[str] = set()
    operations = interaction_context.get("allowed_operations")
    if isinstance(operations, list):
        allowed.update(str(item) for item in operations)
    selection = _canvas_selection(interaction_context)
    selection_actions = selection.get("allowed_actions")
    if isinstance(selection_actions, list):
        allowed.update(str(item) for item in selection_actions)
    return allowed


def _focused_artifact(interaction_context: dict[str, Any] | None) -> str:
    focus = _interaction_focus(interaction_context)
    return str(focus.get("artifact_ref") or "").strip()


def _operation_allowed(allowed: set[str], operation: str) -> bool:
    return not allowed or operation in allowed


def _annotate_actions_with_canvas(actions: list[dict[str, Any]], interaction_context: dict[str, Any] | None) -> list[dict[str, Any]]:
    selection = _canvas_selection(interaction_context)
    if not selection:
        return actions
    annotated: list[dict[str, Any]] = []
    selection_type = str(selection.get("selection_type") or "")
    for action in actions:
        if not isinstance(action, dict):
            continue
        enriched = dict(action)
        if selection_type == "flow_step":
            enriched.setdefault("source_step_id", selection.get("step_id", ""))
            enriched.setdefault("source_step_type", selection.get("step_type", ""))
            enriched.setdefault("source_step_title", selection.get("title", ""))
            runtime_nodes = selection.get("runtime_nodes")
            if isinstance(runtime_nodes, list):
                enriched.setdefault("source_runtime_nodes", runtime_nodes)
        else:
            enriched.setdefault("source_object_id", selection.get("selection_id", ""))
            enriched.setdefault("source_object_type", selection.get("object_type", ""))
            enriched.setdefault("source_object_title", selection.get("title", ""))
            enriched.setdefault("source_business_node", selection.get("business_node", ""))
            enriched.setdefault("source_business_node_id", selection.get("business_node_id", ""))
        annotated.append(enriched)
    return annotated


def _resolve_intent(
    node_context: dict[str, Any],
    mode: str,
    message: str,
    interaction_context: dict[str, Any] | None = None,
    intent: str = "",
) -> str:
    requested = (intent or mode or "auto").strip()
    allowed = _allowed_operations(interaction_context)
    artifact_ref = _focused_artifact(interaction_context)
    canvas_selection = _canvas_selection(interaction_context)
    text = message.lower()

    def allowed_or_clarify(operation: str) -> str:
        return operation if _operation_allowed(allowed, operation) else "ask_clarification"

    def resolve_canvas_object_repair() -> str:
        if _mentions_complex_repair(message) and _operation_allowed(allowed, "delegate_code_repair"):
            return "delegate_code_repair"
        if _operation_allowed(allowed, "patch_app"):
            return "patch_app"
        if _operation_allowed(allowed, "delegate_code_repair"):
            return "delegate_code_repair"
        if _operation_allowed(allowed, "repair_generated_app"):
            return "repair_generated_app"
        return "ask_clarification"

    def resolve_flow_step_repair() -> str:
        if _operation_allowed(allowed, "delegate_code_repair"):
            return "delegate_code_repair"
        if _operation_allowed(allowed, "patch_app"):
            return "patch_app"
        if _operation_allowed(allowed, "diagnose_app_bug"):
            return "diagnose_app_bug"
        return "ask_clarification"

    if canvas_selection and _is_canvas_object_focus(interaction_context) and _mentions_app_repair(message):
        return resolve_canvas_object_repair()
    if canvas_selection and _is_flow_step_focus(interaction_context):
        step_id = str(canvas_selection.get("step_id") or "")
        repair_step = step_id in {"app_preview", "prototype_generation", "capability_verification", "delivery_version"}
        if _mentions_app_repair(message) and (repair_step or _is_app_preview_focus(interaction_context)):
            return resolve_flow_step_repair()

    if requested and requested != "auto":
        explicit = {
            "compare": "compare_variants",
            "edit": "suggest_input_patch",
            "rerun": "rerun_from_node",
            "clarify": "ask_clarification",
        }.get(requested)
        if explicit:
            return allowed_or_clarify(explicit)
        if requested == "explain":
            # Keep explain mode explain-first, except for clear natural language
            # commands such as rerun/read that users often type without changing
            # the mode dropdown.
            requested = "auto"

    if canvas_selection and _is_canvas_object_focus(interaction_context):
        if any(token in message for token in ("验证", "检查", "跑一下", "验收")) or "verify" in text or "check" in text:
            return allowed_or_clarify("verify_capability")
        if _mentions_app_repair(message):
            return resolve_canvas_object_repair()
        if any(token in message for token in ("修改", "补充", "调整", "改一下", "改成")) or "patch" in text or "override" in text:
            return allowed_or_clarify("suggest_input_patch")
        return allowed_or_clarify("explain_object")

    if canvas_selection and _is_flow_step_focus(interaction_context):
        step_id = str(canvas_selection.get("step_id") or "")
        step_type = str(canvas_selection.get("step_type") or "")
        repair_step = step_id in {"app_preview", "prototype_generation", "capability_verification", "delivery_version"}
        if _mentions_app_repair(message) and (repair_step or _is_app_preview_focus(interaction_context)):
            return resolve_flow_step_repair()
        if any(token in message for token in ("重跑", "重新生成", "重新跑", "再生成", "再跑", "重新执行")) or "rerun" in text:
            return allowed_or_clarify("rerun_step")
        if any(token in message for token in ("证据", "工程", "日志", "查看", "打开", "看一下")) or "evidence" in text:
            return allowed_or_clarify("inspect_evidence")
        if any(token in message for token in ("输入", "输出", "上游", "下游", "产物", "文件")) or "input" in text or "output" in text or "artifact" in text:
            return allowed_or_clarify("explain_step_io")
        if step_type == "terminal" and _mentions_app_repair(message):
            return allowed_or_clarify("delegate_code_repair")
        return allowed_or_clarify("explain_step")

    negates_rerun = any(token in message for token in ("不重跑", "不要重跑", "别重跑", "不用重跑")) or "do not rerun" in text or "don't rerun" in text
    wants_rerun = (
        not negates_rerun
        and (any(token in message for token in ("重跑", "重新生成", "重新跑", "再生成", "再跑")) or "rerun" in text)
    )
    if wants_rerun:
        artifact_words = any(token in message for token in ("文件", "产物", "基于这个", "当前"))
        if artifact_ref and _operation_allowed(allowed, "suggest_artifact_regeneration") and (
            artifact_words or not _operation_allowed(allowed, "rerun_from_node")
        ):
            return "suggest_artifact_regeneration"
        return allowed_or_clarify("rerun_from_node")
    if any(token in message for token in ("输入", "上游", "依赖")) or "input" in text:
        return "explain_inputs"
    if any(token in message for token in ("输出", "产物", "文件")) or "output" in text or "artifact" in text:
        if artifact_ref and _operation_allowed(allowed, "read_artifact"):
            return "read_artifact"
        return "explain_outputs"
    if any(token in message for token in ("读一下", "打开", "看一下这个", "解释当前产物")) or "read" in text:
        if artifact_ref:
            return allowed_or_clarify("read_artifact")
        return "explain_outputs"
    if any(token in message for token in ("对比", "差异", "哪个更好", "成本")) or "compare" in text or "usage" in text or "token" in text:
        return allowed_or_clarify("compare_variants")
    if _mentions_app_repair(message):
        if _mentions_complex_repair(message) and _operation_allowed(allowed, "delegate_code_repair"):
            return "delegate_code_repair"
        if _operation_allowed(allowed, "patch_app"):
            return "patch_app"
        if _operation_allowed(allowed, "delegate_code_repair"):
            return "delegate_code_repair"
        if _is_app_preview_focus(interaction_context) and _operation_allowed(allowed, "diagnose_app_bug"):
            return "diagnose_app_bug"
        if _is_app_preview_focus(interaction_context):
            return "ask_clarification"
    if any(token in message for token in ("修改", "补充", "调整", "改一下", "改成")) or "patch" in text or "override" in text:
        if artifact_ref and _operation_allowed(allowed, "suggest_artifact_patch"):
            return "suggest_artifact_patch"
        return allowed_or_clarify("suggest_input_patch")
    if any(token in message for token in ("澄清", "不确定", "需要问")):
        return "ask_clarification"
    return "explain_node"


def _artifact_prompt_items(items: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "path": item.get("path", ""),
                "title": item.get("title") or item.get("path", ""),
                "status": item.get("status", "unknown"),
                "summary": item.get("summary", ""),
                "content_hash": item.get("content_hash", ""),
            }
        )
    return result


def _is_app_preview_focus(interaction_context: dict[str, Any] | None) -> bool:
    focus = _interaction_focus(interaction_context)
    return str(focus.get("card", "")) == "app_preview" or str(focus.get("view_mode", "")) == "app_preview"


def _is_canvas_object_focus(interaction_context: dict[str, Any] | None) -> bool:
    focus = _interaction_focus(interaction_context)
    selection = _canvas_selection(interaction_context)
    return bool(selection) and (
        str(selection.get("selection_type") or "") == "canvas_object"
        and (
            str(focus.get("card", "")) == "canvas_object"
            or str(focus.get("view_mode", "")) == "canvas_object_detail"
        )
    )


def _is_flow_step_focus(interaction_context: dict[str, Any] | None) -> bool:
    focus = _interaction_focus(interaction_context)
    selection = _canvas_selection(interaction_context)
    return bool(selection) and (
        str(selection.get("selection_type") or "") == "flow_step"
        and (
            str(focus.get("card", "")) == "flow_step"
            or str(focus.get("view_mode", "")) == "business_step_detail"
        )
    )


def _mentions_app_repair(message: str) -> bool:
    text = message.lower()
    chinese_tokens = ("修复", "报错", "模型", "生图", "按钮", "下载", "局部迭代", "没反应", "无法", "失败", "换成", "改成")
    english_tokens = ("not configured", "timeout", "provider", "api key", "openrouter", "gpt-image", "gpt-5.4", "button", "download", "error")
    return any(token in message for token in chinese_tokens) or any(token in text for token in english_tokens)


def _mentions_complex_repair(message: str) -> bool:
    """复杂修复语义：跨多处 / 加功能 / 改逻辑 / 说不清具体行，应委托 Code Agent。"""
    text = message.lower()
    chinese_tokens = (
        "新增", "增加", "加一个", "加个", "添加", "功能", "重构", "逻辑", "流程",
        "联动", "上传", "状态", "步骤", "改写", "支持", "集成", "校验", "重试",
        "多处", "多个文件", "整体", "交互", "跨文件",
    )
    english_tokens = ("refactor", "feature", "implement", "workflow", "retry", "validation", "integrate")
    return any(token in message for token in chinese_tokens) or any(token in text for token in english_tokens)


def _file_summary(rel_path: str) -> str:
    if rel_path == "server.js":
        return "Node 本地服务入口，通常包含 health、静态资源和图片生成路由。"
    if rel_path == "public/app.js":
        return "前端交互逻辑，通常包含模型选择、按钮事件和 API 调用。"
    if rel_path == "public/index.html":
        return "前端页面结构，通常包含表单、按钮和模型选择控件。"
    if rel_path == "public/styles.css":
        return "前端样式文件。"
    if rel_path == ".env.example":
        return "服务端环境变量占位模板，不应包含真实 secret。"
    if rel_path == "README.md":
        return "生成应用的本地运行和配置说明。"
    return "可 patch 的已发布应用文本文件。"


def _anchor_purpose(line: str) -> str:
    lowered = line.lower()
    if "gpt-image-1" in lowered or "openrouter_image_model" in lowered or "openai_image_model" in lowered:
        return "图片模型默认值"
    if "image_provider" in lowered or "openrouter_api_key" in lowered or "openai_api_key" in lowered:
        return "图片 provider 配置"
    if "/api/images/generate" in lowered or "/api/health" in lowered:
        return "服务端图片/健康检查接口"
    if "button" in lowered or "生图" in line or "生成" in line:
        return "前端按钮或生成交互"
    if "download" in lowered:
        return "下载交互"
    return "可疑修复锚点"


def _build_app_patch_targets(node_context: dict[str, Any]) -> list[dict[str, Any]]:
    run_dir_raw = node_context.get("run_dir")
    app_slug = str(node_context.get("app_slug", "")).strip()
    if not run_dir_raw or not app_slug:
        return []
    run_dir = Path(str(run_dir_raw)).resolve()
    app_dir = (run_dir / "generated_apps" / app_slug).resolve()
    try:
        app_dir.relative_to(run_dir.resolve())
    except ValueError:
        return []
    candidates = [
        "server.js",
        "public/index.html",
        "public/app.js",
        "public/styles.css",
        ".env.example",
        "README.md",
    ]
    keywords = (
        "gpt-image-1",
        "OPENROUTER_IMAGE_MODEL",
        "OPENAI_IMAGE_MODEL",
        "IMAGE_PROVIDER",
        "/api/images/generate",
        "/api/health",
        "生成",
        "生图",
        "download",
        "model",
        "provider",
        "button",
    )
    targets: list[dict[str, Any]] = []
    for rel_path in candidates:
        path = (app_dir / rel_path).resolve()
        if not path.exists() or not path.is_file():
            continue
        try:
            path.relative_to(app_dir)
        except ValueError:
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if len(raw) > 256_000:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        anchors: list[dict[str, Any]] = []
        lines = text.splitlines()
        for line_no, line in enumerate(lines, start=1):
            if any(keyword in line for keyword in keywords) or any(keyword.lower() in line.lower() for keyword in keywords):
                anchors.append(
                    {
                        "anchor_id": f"{Path(rel_path).stem}_{line_no}",
                        "line_start": line_no,
                        "line_end": line_no,
                        "purpose": _anchor_purpose(line),
                        "old_content": line,
                    }
                )
            if len(anchors) >= 12:
                break
        targets.append(
            {
                "path": f"generated_apps/{app_slug}/{rel_path}",
                "size_bytes": len(raw),
                "content_hash": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "file_type": path.suffix.lstrip(".") or path.name,
                "summary": _file_summary(rel_path),
                "agent_edit_anchors": anchors,
            }
        )
    return targets


def _build_patch_app_fallback(
    *,
    user_message: str,
    provider_text: str,
    app_patch_targets: list[dict[str, Any]],
    context_revision: str = "",
) -> dict[str, Any] | None:
    combined = f"{user_message}\n{provider_text}"
    if not _mentions_app_repair(combined):
        return None
    target_model = ""
    if "gpt-5.4-image-2" in combined:
        target_model = "openai/gpt-5.4-image-2"
    if not target_model:
        return None
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for target in app_patch_targets:
        if not isinstance(target, dict):
            continue
        for anchor in target.get("agent_edit_anchors", []):
            if not isinstance(anchor, dict):
                continue
            old_content = str(anchor.get("old_content", ""))
            if "gpt-image-1" in old_content:
                matches.append((target, anchor))
    if len(matches) != 1:
        return None
    target, anchor = matches[0]
    old_content = str(anchor.get("old_content", ""))
    new_content = old_content.replace("openai/gpt-image-1", target_model).replace("gpt-image-1", target_model)
    if new_content == old_content:
        return None
    action: dict[str, Any] = {
        "type": "patch_app",
        "summary": f"将图片默认模型调整为 {target_model}",
        "source": "provider_text_fallback",
        "problem_source": "app_preview",
        "patches": [
            {
                "target_path": target.get("path", ""),
                "edit_kind": "replace_text",
                "old_content": old_content,
                "new_content": new_content,
            }
        ],
        "preserve_capabilities": ["已通过的应用流程", "服务端读取 API key", "localStorage 不保存 secret"],
        "verification": ["node --check server.js", "GET /api/health"],
        "requires_confirmation": True,
    }
    if context_revision:
        action["context_revision"] = context_revision
    return action


def _build_delegate_code_repair_action(
    *,
    node_context: dict[str, Any],
    user_message: str,
    context_revision: str = "",
) -> dict[str, Any]:
    app_slug = str(node_context.get("app_slug", "")).strip()
    problem = (user_message or "").strip() or "已发布应用存在需要代码修复的问题。"
    action: dict[str, Any] = {
        "type": "delegate_code_repair",
        "summary": f"委托 Code Agent 修复已发布应用 {app_slug}".strip(),
        "source": "agent_bridge",
        "target": "published_app",
        "problem_source": "app_preview",
        "repair_request": {
            "app_slug": app_slug,
            "problem": problem,
            "constraints": ["只修改当前已发布应用", "不重跑 PRD", "保留现有工作流", "API key 只从服务端环境读取"],
            "expected_behavior": [],
            "verification": ["node --check server.js", "node --check public/app.js"],
        },
        "requires_confirmation": True,
    }
    if context_revision:
        action["context_revision"] = context_revision
    return action


def _fallback_actions_for_provider_text(
    *,
    node_context: dict[str, Any],
    interaction_context: dict[str, Any] | None,
    resolved_intent: str,
    user_message: str,
    provider_text: str,
    prompt_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]] | None:
    if resolved_intent not in ("patch_app", "delegate_code_repair"):
        return None
    prompt_context = prompt_context or _agent_prompt_context(node_context, interaction_context, resolved_intent)
    context_revision = str(node_context.get("context_revision", ""))
    if resolved_intent == "delegate_code_repair":
        return [
            _build_delegate_code_repair_action(
                node_context=node_context,
                user_message=user_message,
                context_revision=context_revision,
            )
        ]
    action = _build_patch_app_fallback(
        user_message=user_message,
        provider_text=provider_text,
        app_patch_targets=prompt_context.get("app_patch_targets", []) if isinstance(prompt_context, dict) else [],
        context_revision=context_revision,
    )
    if action:
        return [action]
    allowed = _allowed_operations(interaction_context)
    if _operation_allowed(allowed, "delegate_code_repair"):
        return [
            _build_delegate_code_repair_action(
                node_context=node_context,
                user_message=user_message,
                context_revision=context_revision,
            )
        ]
    return [
        {
            "type": "diagnose_app_bug",
            "summary": "已识别为应用预览修复问题，但当前上下文无法安全定位唯一目标文件和 old_content。请打开相关文件预览或补充具体错误位置。",
            "source": "provider_text_fallback",
            "requires_confirmation": False,
            "context_revision": context_revision,
        }
    ]


def _agent_prompt_context(
    node_context: dict[str, Any],
    interaction_context: dict[str, Any] | None,
    resolved_intent: str,
) -> dict[str, Any]:
    focus = _interaction_focus(interaction_context)
    canvas_selection = _canvas_selection(interaction_context)
    context = {
        "schema_version": 1,
        "run": {
            "run_id": node_context.get("run_id", ""),
            "app_slug": node_context.get("app_slug", ""),
            "comparison_group_id": node_context.get("comparison_group_id", ""),
            "selected_variant": node_context.get("selected_variant", ""),
            "source_run_id": node_context.get("source_run_id", ""),
        },
        "node": {
            "node_id": node_context.get("node_id", ""),
            "title": node_context.get("node_title") or node_context.get("title") or node_context.get("node_id", ""),
            "summary": node_context.get("node_summary") or node_context.get("summary", ""),
            "status": node_context.get("status", "unknown"),
        },
        "focus": {
            "card": focus.get("card", ""),
            "artifact_ref": focus.get("artifact_ref", ""),
            "artifact_title": focus.get("artifact_title", ""),
            "selected_text": focus.get("selected_text", ""),
            "view_mode": focus.get("view_mode", ""),
        },
        "canvas_selection": _prompt_canvas_selection(canvas_selection) if canvas_selection else {},
        "inputs": _artifact_prompt_items(node_context.get("inputs", [])),
        "outputs": _artifact_prompt_items(node_context.get("outputs", [])),
        "skills": node_context.get("skills", []) if isinstance(node_context.get("skills"), list) else [],
        "tool_calls": node_context.get("tool_calls", []) if isinstance(node_context.get("tool_calls"), list) else [],
        "usage": node_context.get("usage", {}) if isinstance(node_context.get("usage"), dict) else {},
        "scores": node_context.get("scores", {}) if isinstance(node_context.get("scores"), dict) else {},
        "risks": node_context.get("risks", []) if isinstance(node_context.get("risks"), list) else [],
        "allowed_operations": sorted(_allowed_operations(interaction_context)),
        "resolved_intent": resolved_intent,
    }
    if _is_app_preview_focus(interaction_context) or resolved_intent in ("patch_app", "delegate_code_repair"):
        context["app_patch_targets"] = _build_app_patch_targets(node_context)
    return context


def _prompt_canvas_selection(selection: dict[str, Any]) -> dict[str, Any]:
    if str(selection.get("selection_type") or "") == "flow_step":
        return {
            "selection_type": "flow_step",
            "step_id": selection.get("step_id", ""),
            "step_type": selection.get("step_type", ""),
            "title": selection.get("title", ""),
            "status": selection.get("status", ""),
            "runtime_nodes": selection.get("runtime_nodes", []) if isinstance(selection.get("runtime_nodes"), list) else [],
            "input_summary": selection.get("input_summary", []) if isinstance(selection.get("input_summary"), list) else [],
            "process_summary": selection.get("process_summary", []) if isinstance(selection.get("process_summary"), list) else [],
            "output_summary": selection.get("output_summary", []) if isinstance(selection.get("output_summary"), list) else [],
            "evidence_refs": selection.get("evidence_refs", []) if isinstance(selection.get("evidence_refs"), list) else [],
            "allowed_actions": selection.get("allowed_actions", []) if isinstance(selection.get("allowed_actions"), list) else [],
        }
    return {
        "selection_type": "canvas_object",
        "selection_id": selection.get("selection_id", ""),
        "object_type": selection.get("object_type", ""),
        "title": selection.get("title", ""),
        "status": selection.get("status", ""),
        "business_node": selection.get("business_node", ""),
        "business_node_id": selection.get("business_node_id", ""),
        "allowed_actions": selection.get("allowed_actions", []) if isinstance(selection.get("allowed_actions"), list) else [],
    }


def _baseline_actions(
    node_context: dict[str, Any],
    mode: str,
    message: str,
    interaction_context: dict[str, Any] | None = None,
    intent: str = "",
    resolved_intent: str = "",
) -> list[dict[str, Any]]:
    node_id = str(node_context.get("node_id", "")) if isinstance(node_context, dict) else ""
    source_run_id = str(node_context.get("run_id", "")) if isinstance(node_context, dict) else ""
    comparison_group_id = str(node_context.get("comparison_group_id", "")) if isinstance(node_context, dict) else ""
    selected_variant = str(node_context.get("selected_variant", "codex")) if isinstance(node_context, dict) else "codex"
    effective_intent = resolved_intent or _resolve_intent(node_context, mode, message, interaction_context, intent)
    focus = _interaction_focus(interaction_context)
    allowed = _allowed_operations(interaction_context)
    artifact_ref = _focused_artifact(interaction_context)
    message_l = message.lower()
    wants_rerun = any(token in message for token in ("重跑", "重新生成", "重新跑", "再生成")) or "rerun" in message_l
    actions: list[dict[str, Any]] = []
    canvas_selection = _canvas_selection(interaction_context)
    if canvas_selection and _is_flow_step_focus(interaction_context):
        step_title = str(canvas_selection.get("title") or canvas_selection.get("step_id") or "当前步骤")
        runtime_nodes = canvas_selection.get("runtime_nodes")
        runtime_node_id = ""
        if isinstance(runtime_nodes, list):
            runtime_node_id = next((str(item) for item in runtime_nodes if str(item).strip()), "")
        if effective_intent == "explain_step":
            return _annotate_actions_with_canvas(
                [
                    {
                        "type": "explain_step",
                        "target_node_id": runtime_node_id or node_id,
                        "summary": f"解释业务步骤「{step_title}」的目标、状态和当前产出。",
                        "requires_confirmation": False,
                        "context_revision": node_context.get("context_revision", ""),
                    }
                ],
                interaction_context,
            )
        if effective_intent == "explain_step_io":
            return _annotate_actions_with_canvas(
                [
                    {
                        "type": "explain_step_io",
                        "target_node_id": runtime_node_id or node_id,
                        "summary": f"说明业务步骤「{step_title}」的输入、执行过程和输出。",
                        "requires_confirmation": False,
                        "context_revision": node_context.get("context_revision", ""),
                    }
                ],
                interaction_context,
            )
        if effective_intent == "inspect_evidence":
            return _annotate_actions_with_canvas(
                [
                    {
                        "type": "inspect_evidence",
                        "target_node_id": runtime_node_id or node_id,
                        "evidence_refs": canvas_selection.get("evidence_refs", []) if isinstance(canvas_selection.get("evidence_refs"), list) else [],
                        "summary": f"查看业务步骤「{step_title}」对应的工程证据。",
                        "requires_confirmation": False,
                        "context_revision": node_context.get("context_revision", ""),
                    }
                ],
                interaction_context,
            )
        if effective_intent == "rerun_step":
            return _annotate_actions_with_canvas(
                [
                    {
                        "type": "rerun_step",
                        "source_run_id": source_run_id,
                        "rerun_from_node": runtime_node_id or node_id,
                        "selected_variant": selected_variant,
                        "override_instructions": message,
                        "comparison_group_id": comparison_group_id,
                        "summary": f"从业务步骤「{step_title}」对应的工程节点重新执行。",
                        "requires_confirmation": True,
                        "context_revision": node_context.get("context_revision", ""),
                    }
                ],
                interaction_context,
            )
    if artifact_ref and (not allowed or "read_artifact" in allowed) and effective_intent in {"read_artifact", "explain_node", "explain_outputs", "compare_variants", "suggest_artifact_regeneration"}:
        actions.append(
            {
                "type": "read_artifact",
                "target_node_id": node_id,
                "target_artifact": artifact_ref,
                "reason": message or f"读取当前 {focus.get('card', 'artifact')} 以便解释。",
                "requires_confirmation": False,
                "context_revision": node_context.get("context_revision", ""),
            }
        )
    if artifact_ref and (wants_rerun or effective_intent == "suggest_artifact_regeneration") and (not allowed or "suggest_artifact_regeneration" in allowed):
        actions.append(
            {
                "type": "suggest_artifact_regeneration",
                "target_node_id": node_id,
                "target_artifact": artifact_ref,
                "patch_summary": message[:80] or "建议基于当前中间产物重新生成。",
                "override_instructions": message or f"基于 {artifact_ref} 重新生成当前节点产物。",
                "requires_confirmation": True,
                "context_revision": node_context.get("context_revision", ""),
                "source": "agent_bridge",
            }
        )
    if actions:
        return actions
    if effective_intent in ("patch_app", "delegate_code_repair"):
        fallback = _fallback_actions_for_provider_text(
            node_context=node_context,
            interaction_context=interaction_context,
            resolved_intent=effective_intent,
            user_message=message,
            provider_text="",
        )
        return fallback or [
            {
                "type": "diagnose_app_bug",
                "target_node_id": node_id,
                "summary": "已识别为应用预览修复问题，但还需要定位具体文件和锚点。",
                "requires_confirmation": False,
                "context_revision": node_context.get("context_revision", ""),
            }
        ]
    if effective_intent == "compare_variants" or mode == "compare":
        return [
            {
                "type": "compare_variants",
                "target_node_id": node_id,
                "variants": ["rule", "codex"],
                "summary": "对比 rule 与 codex 在此节点的输出和 usage。",
                "requires_confirmation": False,
            }
        ]
    if effective_intent == "suggest_input_patch" or mode == "edit":
        return [
            {
                "type": "suggest_input_patch",
                "target_node_id": node_id,
                "patch_summary": message[:80] or "建议调整节点输入。",
                "override_instructions": message,
                "requires_confirmation": True,
                "context_revision": node_context.get("context_revision", ""),
            }
        ]
    if effective_intent == "rerun_from_node" or mode == "rerun":
        return [
            {
                "type": "rerun_from_node",
                "source_run_id": source_run_id,
                "rerun_from_node": node_id,
                "selected_variant": selected_variant,
                "override_instructions": message,
                "comparison_group_id": comparison_group_id,
                "requires_confirmation": True,
                "context_revision": node_context.get("context_revision", ""),
            }
        ]
    if effective_intent == "ask_clarification" or mode == "clarify":
        return [
            {
                "type": "ask_clarification",
                "target_node_id": node_id,
                "question": message or "需要补充哪些上下文？",
                "requires_confirmation": False,
            }
        ]
    if effective_intent == "explain_object":
        selection = _canvas_selection(interaction_context)
        return _annotate_actions_with_canvas(
            [
                {
                    "type": "explain_object",
                    "target_node_id": node_id,
                    "summary": f"解释业务对象：{selection.get('title') or selection.get('selection_id') or '当前对象'}。",
                    "requires_confirmation": False,
                    "context_revision": node_context.get("context_revision", ""),
                }
            ],
            interaction_context,
        )
    if effective_intent == "verify_capability":
        selection = _canvas_selection(interaction_context)
        return _annotate_actions_with_canvas(
            [
                {
                    "type": "verify_capability",
                    "target_node_id": node_id,
                    "summary": f"验证业务能力：{selection.get('title') or selection.get('selection_id') or '当前能力'}。",
                    "verification": ["preview health", "runtime smoke", "capability evidence review"],
                    "requires_confirmation": False,
                    "context_revision": node_context.get("context_revision", ""),
                }
            ],
            interaction_context,
        )
    return [
        {
            "type": "explain_node",
            "target_node_id": node_id,
            "summary": f"节点 {node_id} 的输入、过程、输出与风险摘要。",
            "requires_confirmation": False,
        }
    ]


def _baseline_message(
    node_context: dict[str, Any],
    mode: str,
    message: str,
    interaction_context: dict[str, Any] | None = None,
) -> str:
    node_id = str(node_context.get("node_id", "")) if isinstance(node_context, dict) else ""
    selected_variant = str(node_context.get("selected_variant", "codex")) if isinstance(node_context, dict) else "codex"
    app_slug = str(node_context.get("app_slug", "")) if isinstance(node_context, dict) else ""
    inputs = node_context.get("inputs", []) if isinstance(node_context, dict) else []
    outputs = node_context.get("outputs", []) if isinstance(node_context, dict) else []
    ready_outputs = [item for item in outputs if isinstance(item, dict) and item.get("status") == "ready"]
    risk_count = len(node_context.get("risks", [])) if isinstance(node_context, dict) else 0
    head = f"应用 {app_slug} · 节点 {node_id} · variant={selected_variant}"
    artifact_ref = _focused_artifact(interaction_context)
    if artifact_ref:
        head = f"{head} · 当前产物 {artifact_ref}"
    canvas_selection = _canvas_selection(interaction_context)
    if canvas_selection and _is_canvas_object_focus(interaction_context):
        head = f"{head} · 当前对象 {canvas_selection.get('title') or canvas_selection.get('selection_id')}"
    if canvas_selection and _is_flow_step_focus(interaction_context):
        head = f"{head} · 当前业务步骤 {canvas_selection.get('title') or canvas_selection.get('step_id')}"
    if mode == "compare":
        return f"{head}\n对比说明：rule 提供确定性 baseline；codex 提供更细致的实现细节。当前节点有 {len(ready_outputs)} 份产物已就绪。"
    if mode == "edit":
        return f"{head}\n收到调整诉求：{message[:120]}。已生成 suggest_input_patch 待你确认后写入新 run inputs。"
    if mode == "rerun":
        return f"{head}\n已准备从该节点创建新 run 的说明，不会修改旧 run。"
    if mode == "clarify":
        return f"{head}\n需要澄清：{message[:120]}"
    return f"{head}\n该节点有 {len(inputs)} 项输入、{len(ready_outputs)} 项就绪输出、{risk_count} 项风险记录。"


# ---------------------------------------------------------------------------
# PI prompt builder.
# ---------------------------------------------------------------------------


def _pi_prompt_text(
    node_context: dict[str, Any],
    mode: str,
    message: str,
    interaction_context: dict[str, Any] | None = None,
    intent: str = "",
    resolved_intent: str = "",
) -> str:
    """Build a plain-text prompt for pi based on node context and mode."""
    node_id = str(node_context.get("node_id", ""))
    run_id = str(node_context.get("run_id", ""))
    app_slug = str(node_context.get("app_slug", ""))
    selected_variant = str(node_context.get("selected_variant", "codex"))
    inputs = node_context.get("inputs", [])
    outputs = node_context.get("outputs", [])
    ready_outputs = [
        item for item in outputs if isinstance(item, dict) and item.get("status") == "ready"
    ]
    risk_count = len(node_context.get("risks", [])) if isinstance(node_context, dict) else 0
    effective_intent = resolved_intent or _resolve_intent(node_context, mode, message, interaction_context, intent)
    prompt_context = _agent_prompt_context(node_context, interaction_context, effective_intent)

    context_parts = [
        f"应用 {app_slug} · run {run_id} · 节点 {node_id} · variant={selected_variant}",
        f"该节点有 {len(inputs)} 项输入、{len(ready_outputs)} 项就绪输出、{risk_count} 项风险记录。",
        f"用户意图：{intent or mode}",
        f"解析意图：{effective_intent}",
        "",
        "AgentPromptContext：",
        json.dumps(prompt_context, ensure_ascii=False, sort_keys=True),
        "",
    ]
    if mode == "compare":
        context_parts.append("请对比 rule 和 codex 在此节点的输出与 usage 差异。")
    elif mode == "edit":
        context_parts.append(f"用户希望调整节点输入：{message}")
    elif mode == "rerun":
        context_parts.append(f"用户希望从当前节点重跑，override 说明：{message}")
    elif mode == "clarify":
        context_parts.append(f"用户希望澄清：{message}")
    else:
        context_parts.append("请解释当前节点的输入、过程、输出与风险。")

    if message and mode not in {"edit", "rerun", "clarify"}:
        context_parts.append("")
        context_parts.append(f"用户问题：{message}")

    context_parts.append("")
    context_parts.append(_PI_TRAILING_ACTIONS_PROTOCOL)
    return "\n".join(context_parts)


# ---------------------------------------------------------------------------
# Provider abstraction.
# ---------------------------------------------------------------------------


class AgentProvider:
    provider_id = "base"

    def status(self, *, repo_root: Path) -> dict[str, Any]:
        return {
            "provider": self.provider_id,
            "status": "not_configured",
            "message": f"{self.provider_id} is not configured.",
            "capabilities": [],
        }

    def send_message(
        self,
        *,
        node_context: dict[str, Any],
        mode: str,
        message: str,
        repo_root: Path,
        interaction_context: dict[str, Any] | None = None,
        intent: str = "",
    ) -> dict[str, Any]:
        del interaction_context, intent
        status = self.status(repo_root=repo_root)
        return {
            "provider": self.provider_id,
            "status": status.get("status", "not_configured"),
            "message": status.get("message", f"{self.provider_id} is not configured."),
            "actions": [],
            "tool_calls": [],
            "usage": dict(UNKNOWN_USAGE),
            "risk_events": [],
        }

    def stream_message(
        self,
        *,
        node_context: dict[str, Any],
        mode: str,
        message: str,
        repo_root: Path,
        interaction_context: dict[str, Any] | None = None,
        intent: str = "",
    ) -> Iterator[dict[str, Any]]:
        """Default streaming impl: emit the non-streaming response as one event.

        Providers that natively stream (PiAgentProvider) override this.
        """
        response = self.send_message(
            node_context=node_context,
            mode=mode,
            message=message,
            repo_root=repo_root,
            interaction_context=interaction_context,
            intent=intent,
        )
        yield {
            "type": "agent_end",
            "payload": response,
            "ts": time.time(),
        }


class CodexProvider(AgentProvider):
    """Codex provider.

    Always reports `ready` because deterministic baseline message and actions are
    available without external dependencies. When .env contains aicodemirror
    credentials the conversational message is upgraded by a real LLM call; on
    failure it falls back to the deterministic baseline plus a redacted risk_event.
    """

    provider_id = "codex"

    def __init__(self, http_caller: Callable[[str, dict[str, str], bytes], dict[str, Any]] | None = None):
        self._http_caller = http_caller

    def status(self, *, repo_root: Path) -> dict[str, Any]:
        base_url, api_key = _codex_credentials(repo_root)
        configured = bool(base_url and api_key)
        return {
            "provider": "codex",
            "status": "ready",
            "message": "Codex executor is ready." + (" Real LLM credentials detected." if configured else " Using deterministic baseline (no LLM credentials)."),
            "capabilities": ["explain", "compare", "suggest_input_patch", "rerun_from_node"],
            "llm_configured": configured,
        }

    def send_message(
        self,
        *,
        node_context: dict[str, Any],
        mode: str,
        message: str,
        repo_root: Path,
        interaction_context: dict[str, Any] | None = None,
        intent: str = "",
    ) -> dict[str, Any]:
        resolved_intent = _resolve_intent(node_context, mode, message, interaction_context, intent)
        actions = _baseline_actions(node_context, mode, message, interaction_context, intent, resolved_intent)
        actions = _annotate_actions_with_canvas(actions, interaction_context)
        baseline_message = _baseline_message(node_context, mode, message, interaction_context)
        base_url, api_key = _codex_credentials(repo_root)

        if not base_url or not api_key:
            return {
                "provider": "codex",
                "status": "completed",
                "message": baseline_message,
                "actions": actions,
                "tool_calls": [],
                "usage": {**UNKNOWN_USAGE, "usage_source": "deterministic_baseline"},
                "risk_events": [],
                "context_revision": node_context.get("context_revision", ""),
                "resolved_intent": resolved_intent,
            }

        try:
            payload = self._invoke_llm(
                base_url,
                api_key,
                node_context,
                mode,
                message,
                baseline_message,
                interaction_context,
                intent,
                resolved_intent,
            )
        except Exception as exc:  # OSError, URLError, JSONDecodeError, anything from urllib
            return {
                "provider": "codex",
                "status": "completed",
                "message": baseline_message,
                "actions": actions,
                "tool_calls": [],
                "usage": {**UNKNOWN_USAGE, "usage_source": "llm_unavailable"},
                "risk_events": [
                    {
                        "id": "codex_llm_unavailable",
                        "severity": "warning",
                        "summary": f"Codex LLM 调用失败，已回退到确定性回复：{_redact_text(type(exc).__name__)}",
                    }
                ],
                "context_revision": node_context.get("context_revision", ""),
                "resolved_intent": resolved_intent,
            }

        content = _extract_model_content(payload).strip()
        usage = _extract_usage(payload)
        final_message = content if content else baseline_message
        cleaned_message, parsed_actions = _parse_trailing_actions(
            final_message,
            context_revision=str(node_context.get("context_revision", "")),
        )
        if parsed_actions:
            prompt_context = _agent_prompt_context(node_context, interaction_context, resolved_intent)
            actions = _safe_actions_with_patch_fallback(
                actions=parsed_actions,
                node_context=node_context,
                interaction_context=interaction_context,
                resolved_intent=resolved_intent,
                user_message=message,
                provider_text=cleaned_message or content,
                prompt_context=prompt_context,
            )
            final_message = cleaned_message or baseline_message
        elif content:
            prompt_context = _agent_prompt_context(node_context, interaction_context, resolved_intent)
            fallback_actions = _fallback_actions_for_provider_text(
                node_context=node_context,
                interaction_context=interaction_context,
                resolved_intent=resolved_intent,
                user_message=message,
                provider_text=content,
                prompt_context=prompt_context,
            )
            if fallback_actions:
                actions = fallback_actions
        actions = _annotate_actions_with_canvas(actions, interaction_context)
        return {
            "provider": "codex",
            "status": "completed",
            "message": final_message,
            "actions": actions,
            "tool_calls": [],
            "usage": usage,
            "risk_events": [],
            "context_revision": node_context.get("context_revision", ""),
            "resolved_intent": resolved_intent,
        }

    def _invoke_llm(
        self,
        base_url: str,
        api_key: str,
        node_context: dict[str, Any],
        mode: str,
        message: str,
        baseline_message: str,
        interaction_context: dict[str, Any] | None = None,
        intent: str = "",
        resolved_intent: str = "",
    ) -> dict[str, Any]:
        request_payload = {
            "model": os.environ.get("AICODEMIRROR_MODEL", "gpt-5-codex"),
            "messages": [
                {"role": "system", "content": _system_prompt()},
                {
                    "role": "user",
                    "content": _user_prompt(
                        node_context,
                        mode,
                        message,
                        baseline_message,
                        interaction_context,
                        intent,
                        resolved_intent,
                    ),
                },
            ],
            "max_tokens": 1024,
            "temperature": 0.2,
        }
        body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if self._http_caller is not None:
            return self._http_caller(base_url.rstrip("/") + "/chat/completions", headers, body)
        req = request.Request(
            base_url.rstrip("/") + "/chat/completions",
            data=body,
            headers=headers,
            method="POST",
        )
        with request.urlopen(req, timeout=30) as response:  # nosec - URL is user-configured provider endpoint.
            return json.loads(response.read().decode("utf-8"))


class PiAgentProvider(AgentProvider):
    """Real PiAgent provider via ``pi --mode rpc`` subprocess JSONL stdio.

    See docs/app_generation_agent_bridge_spec.md `### pi_agent` for protocol.

    - ``status`` short-circuits on ``shutil.which(PI_BIN)``; no subprocess is
      started just to probe.
    - ``stream_message`` returns an iterator of StreamEvents (message_delta,
      tool_call, tool_result, agent_end, upstream_error, auto_retry_start,
      extension_ui_request).
    - ``send_message`` folds the stream into a non-streaming AgentResponse for
      backward-compatible callers; the canonical path for UI is
      ``stream_message``.
    - A single :class:`PiRpcClient` instance is reused per provider object;
      dashboard creates and disposes it via :func:`shutdown_pi_provider`.
    """

    provider_id = "pi_agent"

    def __init__(
        self,
        *,
        subprocess_launcher: "Callable[[list[str], dict[str, str], Path], Any] | None" = None,
        event_parser: "Callable[[str], list[dict[str, Any]]] | None" = None,
        redactor: "Callable[[str], str]" = _redact_text,
        client_factory: "Callable[..., Any] | None" = None,
        status_probe: "Callable[..., dict[str, Any]] | None" = None,
    ) -> None:
        from growth_dev.team import pi_rpc

        self._pi_rpc = pi_rpc
        self._subprocess_launcher = subprocess_launcher
        self._event_parser = event_parser
        self._redactor = redactor
        self._client_factory = client_factory or pi_rpc.PiRpcClient
        self._status_probe = status_probe
        self._client: Any = None
        self._client_repo_root: Path | None = None
        self._client_lock = threading.Lock()

    def status(self, *, repo_root: Path) -> dict[str, Any]:
        if self._status_probe is not None:
            return self._status_probe(redactor=self._redactor)
        return self._pi_rpc.pi_status(redactor=self._redactor)

    def _get_or_create_client(self, repo_root: Path) -> Any:
        with self._client_lock:
            if self._client is None or self._client_repo_root != repo_root.resolve():
                if self._client is not None:
                    try:
                        self._client.close()
                    except Exception:  # pragma: no cover - defensive
                        pass
                kwargs: dict[str, Any] = {
                    "repo_root": repo_root.resolve(),
                    "redactor": self._redactor,
                }
                if self._subprocess_launcher is not None:
                    kwargs["subprocess_launcher"] = self._subprocess_launcher
                if self._event_parser is not None:
                    kwargs["event_parser"] = self._event_parser
                self._client = self._client_factory(**kwargs)
                self._client_repo_root = repo_root.resolve()
                atexit.register(self._safe_close)
            return self._client

    def _safe_close(self) -> None:
        with self._client_lock:
            client = self._client
            self._client = None
        if client is None:
            return
        try:
            client.close()
        except Exception:  # pragma: no cover - defensive
            pass

    def stream_message(
        self,
        *,
        node_context: dict[str, Any],
        mode: str,
        message: str,
        repo_root: Path,
        interaction_context: dict[str, Any] | None = None,
        intent: str = "",
    ) -> Iterator[dict[str, Any]]:
        status = self.status(repo_root=repo_root)
        if status.get("status") != "ready":
            yield {
                "type": "upstream_error",
                "payload": {
                    "phase": "not_configured",
                    "errorMessage": status.get("message", "pi binary not on PATH"),
                    "hint": "auth_invalid",
                },
                "ts": time.time(),
            }
            return
        try:
            client = self._get_or_create_client(repo_root)
        except RuntimeError as exc:
            yield {
                "type": "upstream_error",
                "payload": {
                    "phase": "boot_failed",
                    "errorMessage": self._redactor(str(exc)),
                    "hint": "upstream_unknown",
                },
                "ts": time.time(),
            }
            return

        resolved_intent = _resolve_intent(node_context, mode, message, interaction_context, intent)
        prompt_context = _agent_prompt_context(node_context, interaction_context, resolved_intent)
        prompt = _pi_prompt_text(node_context, mode, message, interaction_context, intent, resolved_intent)
        actions = _baseline_actions(node_context, mode, message, interaction_context, intent, resolved_intent)
        actions = _annotate_actions_with_canvas(actions, interaction_context)
        context_revision = str(node_context.get("context_revision", "")) if isinstance(node_context, dict) else ""
        answer_buffer: list[str] = []
        saw_terminal_event = False
        for event in client.send_prompt(prompt):
            event_type = event.get("type")
            if event_type == "message_delta":
                payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                answer_buffer.append(str(payload.get("text", "")))
            if event_type in {"agent_end", "upstream_error"}:
                saw_terminal_event = True
            if event_type == "agent_end":
                payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                cleaned_message, parsed_actions = _parse_trailing_actions(
                    "".join(answer_buffer),
                    context_revision=context_revision,
                )
                resolved_actions = payload.get("actions")
                if not isinstance(resolved_actions, list):
                    if parsed_actions:
                        resolved_actions = _safe_actions_with_patch_fallback(
                            actions=parsed_actions,
                            node_context=node_context,
                            interaction_context=interaction_context,
                            resolved_intent=resolved_intent,
                            user_message=message,
                            provider_text=cleaned_message,
                            prompt_context=prompt_context,
                        )
                        actions_source = "pi_structured"
                    else:
                        fallback_actions = _fallback_actions_for_provider_text(
                            node_context=node_context,
                            interaction_context=interaction_context,
                            resolved_intent=resolved_intent,
                            user_message=message,
                            provider_text=cleaned_message,
                            prompt_context=prompt_context,
                        )
                        resolved_actions = fallback_actions if fallback_actions else actions
                        actions_source = "provider_text_fallback" if fallback_actions else "deterministic_baseline"
                else:
                    resolved_actions = _safe_actions_with_patch_fallback(
                        actions=[action for action in resolved_actions if isinstance(action, dict)],
                        node_context=node_context,
                        interaction_context=interaction_context,
                        resolved_intent=resolved_intent,
                        user_message=message,
                        provider_text=cleaned_message,
                        prompt_context=prompt_context,
                    )
                    actions_source = "provider_payload"
                resolved_actions = _annotate_actions_with_canvas(resolved_actions, interaction_context)
                event = {
                    **event,
                    "payload": {
                        **payload,
                        "actions": resolved_actions,
                        "cleaned_message": self._redactor(cleaned_message),
                        "actions_source": actions_source,
                        "context_revision": payload.get("context_revision") or context_revision,
                        "resolved_intent": payload.get("resolved_intent") or resolved_intent,
                    },
                }
            yield event
        if not saw_terminal_event:
            yield {
                "type": "upstream_error",
                "payload": {
                    "phase": "stream_closed",
                    "errorMessage": "pi stream ended without agent_end",
                    "hint": "upstream_unknown",
                },
                "ts": time.time(),
            }

    def send_message(
        self,
        *,
        node_context: dict[str, Any],
        mode: str,
        message: str,
        repo_root: Path,
        interaction_context: dict[str, Any] | None = None,
        intent: str = "",
    ) -> dict[str, Any]:
        deltas: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        tool_results: dict[str, dict[str, Any]] = {}
        resolved_intent = _resolve_intent(node_context, mode, message, interaction_context, intent)
        actions = _baseline_actions(node_context, mode, message, interaction_context, intent, resolved_intent)
        actions = _annotate_actions_with_canvas(actions, interaction_context)
        usage: dict[str, Any] = dict(UNKNOWN_USAGE)
        usage["usage_source"] = "pi_agent_end_missing"
        risk_events: list[dict[str, Any]] = []
        status_terminal = "completed"
        cleaned_message_from_stream: str | None = None

        for event in self.stream_message(
            node_context=node_context,
            mode=mode,
            message=message,
            repo_root=repo_root,
            interaction_context=interaction_context,
            intent=intent,
        ):
            event_type = event.get("type")
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            if event_type == "message_delta":
                deltas.append(str(payload.get("text", "")))
            elif event_type == "tool_call":
                tool_calls.append(
                    {
                        "tool_call_id": payload.get("tool_call_id", ""),
                        "name": payload.get("name", ""),
                        "input": payload.get("input", {}),
                        "status": "started",
                    }
                )
            elif event_type == "tool_result":
                tool_call_id = str(payload.get("tool_call_id", ""))
                tool_results[tool_call_id] = {
                    "output": payload.get("output", ""),
                    "is_error": bool(payload.get("is_error", False)),
                }
            elif event_type == "agent_end":
                if isinstance(payload.get("actions"), list):
                    actions = payload["actions"]
                if isinstance(payload.get("cleaned_message"), str):
                    cleaned_message_from_stream = payload["cleaned_message"]
                raw_usage = payload.get("usage")
                if isinstance(raw_usage, dict) and raw_usage:
                    usage = {
                        "prompt_tokens": raw_usage.get("prompt_tokens", raw_usage.get("input_tokens", "unknown")),
                        "completion_tokens": raw_usage.get("completion_tokens", raw_usage.get("output_tokens", "unknown")),
                        "total_tokens": raw_usage.get("total_tokens", "unknown"),
                        "estimated_cost": "unknown",
                        "usage_source": "pi_agent_end",
                    }
                else:
                    usage = {**UNKNOWN_USAGE, "usage_source": "pi_agent_end_empty"}
            elif event_type == "upstream_error":
                status_terminal = "error"
                risk_events.append(
                    {
                        "id": "pi_upstream_error",
                        "severity": "error",
                        "summary": self._redactor(str(payload.get("errorMessage", "pi upstream error"))),
                        "hint": str(payload.get("hint", "upstream_unknown")),
                        "phase": str(payload.get("phase", "")),
                    }
                )

        for call in tool_calls:
            result = tool_results.get(str(call.get("tool_call_id", "")))
            if result is not None:
                call["output"] = result["output"]
                call["is_error"] = result["is_error"]
                call["status"] = "error" if result["is_error"] else "completed"

        if cleaned_message_from_stream is not None:
            final_message = cleaned_message_from_stream.strip() or _baseline_message(
                node_context, mode, message, interaction_context
            )
        else:
            final_message = "".join(deltas).strip() or _baseline_message(
                node_context, mode, message, interaction_context
            )
        return {
            "provider": "pi_agent",
            "status": status_terminal,
            "message": self._redactor(final_message),
            "actions": actions,
            "tool_calls": tool_calls,
            "usage": usage,
            "risk_events": risk_events,
            "context_revision": node_context.get("context_revision", ""),
            "resolved_intent": resolved_intent,
        }


class GenericLlmProvider(AgentProvider):
    provider_id = "llm"

    def status(self, *, repo_root: Path) -> dict[str, Any]:
        configured = bool(
            os.environ.get("APP_GENERATION_LLM_BASE_URL")
            or os.environ.get("APP_GENERATION_LLM_API_KEY")
            or os.environ.get("LLM_BASE_URL")
            or os.environ.get("LLM_API_KEY")
        )
        if not configured:
            return {
                "provider": "llm",
                "status": "not_configured",
                "message": "Generic LLM provider is not configured.",
                "capabilities": [],
            }
        return {
            "provider": "llm",
            "status": "ready",
            "message": "Generic LLM provider is configured; actions remain confirm-only.",
            "capabilities": ["explain", "compare", "suggest_input_patch", "rerun_from_node"],
        }

    def send_message(
        self,
        *,
        node_context: dict[str, Any],
        mode: str,
        message: str,
        repo_root: Path,
        interaction_context: dict[str, Any] | None = None,
        intent: str = "",
    ) -> dict[str, Any]:
        status = self.status(repo_root=repo_root)
        resolved_intent = _resolve_intent(node_context, mode, message, interaction_context, intent)
        if status.get("status") != "ready":
            return {
                "provider": "llm",
                "status": status.get("status", "not_configured"),
                "message": status.get("message", "Generic LLM provider is not configured."),
                "actions": [],
                "tool_calls": [],
                "usage": dict(UNKNOWN_USAGE),
                "risk_events": [],
            }
        return {
            "provider": "llm",
            "status": "completed",
            "message": _baseline_message(node_context, mode, message, interaction_context),
            "actions": _baseline_actions(node_context, mode, message, interaction_context, intent, resolved_intent),
            "tool_calls": [],
            "usage": {**UNKNOWN_USAGE, "usage_source": "generic_llm_bridge_placeholder"},
            "risk_events": [],
            "context_revision": node_context.get("context_revision", ""),
            "resolved_intent": resolved_intent,
        }


# ---------------------------------------------------------------------------
# Prompts.
# ---------------------------------------------------------------------------


def _system_prompt() -> str:
    return (
        "你是 PRD 生成应用工作台中右侧 Agent 区的协作助手。"
        "你只解释、对比、建议调整或澄清。"
        "禁止伪造产物内容，禁止覆盖中间节点事实，禁止越过用户确认。"
        "请用中文简洁回答，分点说明结论与下一步。"
    )


def _user_prompt(
    node_context: dict[str, Any],
    mode: str,
    message: str,
    baseline_message: str,
    interaction_context: dict[str, Any] | None = None,
    intent: str = "",
    resolved_intent: str = "",
) -> str:
    effective_intent = resolved_intent or _resolve_intent(node_context, mode, message, interaction_context, intent)
    prompt_context = _agent_prompt_context(node_context, interaction_context, effective_intent)
    parts = [
        f"模式：{mode}",
        f"解析意图：{effective_intent}",
        f"用户消息：{message or '(无)'}",
        "AgentPromptContext：",
        json.dumps(prompt_context, ensure_ascii=False, sort_keys=True),
        "确定性 baseline 已经生成的回复（可参考、可改写）：",
        baseline_message,
        "请基于上述上下文，给出更具体的中文协作回复。如需澄清请提问，但不要执行任何写文件动作。",
    ]
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Public entry points.
# ---------------------------------------------------------------------------


_PROVIDER_REGISTRY: dict[str, Callable[[], AgentProvider]] = {
    "codex": CodexProvider,
    "pi_agent": PiAgentProvider,
    "llm": GenericLlmProvider,
}

_PROVIDER_SINGLETONS: dict[str, AgentProvider] = {}
_PROVIDER_SINGLETON_LOCK = threading.Lock()
# Providers that hold long-lived resources (e.g. subprocess) must be reused
# rather than instantiated per request.
_SINGLETON_PROVIDER_IDS = {"pi_agent"}


def get_provider(provider_id: str) -> AgentProvider:
    if provider_id in _SINGLETON_PROVIDER_IDS:
        with _PROVIDER_SINGLETON_LOCK:
            existing = _PROVIDER_SINGLETONS.get(provider_id)
            if existing is not None:
                return existing
            factory = _PROVIDER_REGISTRY.get(provider_id)
            if factory is None:
                provider = AgentProvider()
                provider.provider_id = provider_id
                _PROVIDER_SINGLETONS[provider_id] = provider
                return provider
            provider = factory()
            _PROVIDER_SINGLETONS[provider_id] = provider
            return provider
    factory = _PROVIDER_REGISTRY.get(provider_id)
    if factory is None:
        provider = AgentProvider()
        provider.provider_id = provider_id
        return provider
    return factory()


def reset_provider_singletons() -> None:
    """Reset cached singleton providers; used in tests to swap injections."""
    with _PROVIDER_SINGLETON_LOCK:
        for provider in _PROVIDER_SINGLETONS.values():
            close = getattr(provider, "_safe_close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # pragma: no cover - defensive
                    pass
        _PROVIDER_SINGLETONS.clear()


def register_provider_singleton(provider_id: str, provider: AgentProvider) -> None:
    """Inject a custom provider instance as the singleton; used in tests."""
    with _PROVIDER_SINGLETON_LOCK:
        existing = _PROVIDER_SINGLETONS.get(provider_id)
        if existing is not None:
            close = getattr(existing, "_safe_close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # pragma: no cover - defensive
                    pass
        _PROVIDER_SINGLETONS[provider_id] = provider


def provider_status(provider_id: str, *, repo_root: Path) -> dict[str, Any]:
    return get_provider(provider_id).status(repo_root=repo_root)


def send_agent_message(
    *,
    provider_id: str,
    node_context: dict[str, Any],
    mode: str,
    message: str,
    repo_root: Path,
    interaction_context: dict[str, Any] | None = None,
    intent: str = "",
) -> dict[str, Any]:
    provider = get_provider(provider_id)
    return provider.send_message(
        node_context=node_context,
        mode=mode,
        message=message,
        repo_root=repo_root,
        interaction_context=interaction_context,
        intent=intent,
    )


def stream_agent_message(
    *,
    provider_id: str,
    node_context: dict[str, Any],
    mode: str,
    message: str,
    repo_root: Path,
    interaction_context: dict[str, Any] | None = None,
    intent: str = "",
) -> Iterator[dict[str, Any]]:
    """Stream StreamEvents from the chosen provider.

    Dashboard's POST /api/app-generation/agent/stream consumes this generator.
    Providers without native streaming fall back to a single agent_end event.
    """
    provider = get_provider(provider_id)
    yield from provider.stream_message(
        node_context=node_context,
        mode=mode,
        message=message,
        repo_root=repo_root,
        interaction_context=interaction_context,
        intent=intent,
    )
