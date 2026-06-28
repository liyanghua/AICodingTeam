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
    "compare_variants",
    "read_artifact",
    "suggest_input_patch",
    "suggest_artifact_patch",
    "suggest_artifact_regeneration",
    "rerun_from_node",
    "select_variant",
    "ask_clarification",
)

_PI_TRAILING_ACTIONS_PROTOCOL = (
    "结构化建议协议（可选，但强烈建议）：\n"
    "- 给出自然语言解释后，在回答最末输出一个 fenced JSON 块：\n"
    "  ```json\n"
    "  {\"actions\": [{\"type\": \"...\", \"summary\": \"...\", \"requires_confirmation\": true}]}\n"
    "  ```\n"
    f"- type 必须取自：{', '.join(PI_ALLOWED_ACTION_TYPES)}。\n"
    "- 不要在回答中夹带或复述文件原文；建议改动放进 patch_summary / override_instructions。\n"
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


def _allowed_operations(interaction_context: dict[str, Any] | None) -> set[str]:
    if not isinstance(interaction_context, dict):
        return set()
    operations = interaction_context.get("allowed_operations")
    if not isinstance(operations, list):
        return set()
    return {str(item) for item in operations}


def _focused_artifact(interaction_context: dict[str, Any] | None) -> str:
    focus = _interaction_focus(interaction_context)
    return str(focus.get("artifact_ref") or "").strip()


def _operation_allowed(allowed: set[str], operation: str) -> bool:
    return not allowed or operation in allowed


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
    text = message.lower()

    def allowed_or_clarify(operation: str) -> str:
        return operation if _operation_allowed(allowed, operation) else "ask_clarification"

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

    wants_rerun = any(token in message for token in ("重跑", "重新生成", "重新跑", "再生成", "再跑")) or "rerun" in text
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


def _agent_prompt_context(
    node_context: dict[str, Any],
    interaction_context: dict[str, Any] | None,
    resolved_intent: str,
) -> dict[str, Any]:
    focus = _interaction_focus(interaction_context)
    return {
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
        prompt = _pi_prompt_text(node_context, mode, message, interaction_context, intent, resolved_intent)
        actions = _baseline_actions(node_context, mode, message, interaction_context, intent, resolved_intent)
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
                    resolved_actions = parsed_actions if parsed_actions else actions
                event = {
                    **event,
                    "payload": {
                        **payload,
                        "actions": resolved_actions,
                        "cleaned_message": self._redactor(cleaned_message),
                        "actions_source": (
                            "pi_structured" if parsed_actions else "deterministic_baseline"
                        ),
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
