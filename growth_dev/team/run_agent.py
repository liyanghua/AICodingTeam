from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RunAgentContext:
    app_config_ref: str
    current_focus: dict[str, Any] = field(default_factory=dict)
    runs_snapshot: dict[str, Any] = field(default_factory=dict)
    safety_capsule: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunAgentRoute:
    route: str
    reason: str
    node_id: str = ""


@dataclass(frozen=True)
class ActionValidation:
    status: str
    reason: str = ""


def dispatch_free_text(user_input: str, context: RunAgentContext) -> RunAgentRoute:
    """Route right-side RunAgent free text deterministically before LLM handling."""
    text = (user_input or "").strip().lower()
    node_id = str((context.current_focus or {}).get("node_id") or "")
    if any(keyword in text for keyword in ("修 bug", "bug", "改 shell", "规则引擎", "server.js", "崩溃")):
        return RunAgentRoute(route="delegate_code_repair", reason="complex_code_repair", node_id=node_id)
    if any(keyword in text for keyword in ("重跑", "重新计算", "换文件", "重新上传", "rerun")) and node_id:
        return RunAgentRoute(route="rerun_node", reason="focused_node_rerun", node_id=node_id)
    if any(keyword in text for keyword in ("改", "补字段", "加按钮", "改文案", "调整", "patch")):
        return RunAgentRoute(route="patch_app_proposal", reason="small_app_adjustment", node_id=node_id)
    if any(keyword in text for keyword in ("解释", "这是什么", "为什么", "说明", "explain")):
        return RunAgentRoute(route="explain", reason="explanation_request", node_id=node_id)
    return RunAgentRoute(route="explain", reason="default_explain", node_id=node_id)


def validate_action_request(action: dict[str, Any]) -> ActionValidation:
    action_type = str(action.get("type") or "")
    if action_type == "rerun_node":
        node_id = str(action.get("node_id") or "")
        if node_id and _safe_id(node_id):
            return ActionValidation(status="ok")
        return ActionValidation(status="rejected", reason="invalid_node_id")
    if action_type == "patch_app":
        return _validate_patch_targets(action, _is_allowed_app_patch_path)
    if action_type == "patch_artifact":
        return _validate_patch_targets(action, _is_allowed_artifact_patch_path)
    return ActionValidation(status="rejected", reason="unsupported_action_type")


def _validate_patch_targets(action: dict[str, Any], predicate: Any) -> ActionValidation:
    patches = action.get("patches")
    if not isinstance(patches, list) or not patches:
        return ActionValidation(status="rejected", reason="missing_patches")
    for patch in patches:
        if not isinstance(patch, dict):
            return ActionValidation(status="rejected", reason="invalid_patch")
        target_path = str(patch.get("target_path") or "")
        if not predicate(target_path):
            return ActionValidation(status="rejected", reason="patch_out_of_scope")
    return ActionValidation(status="ok")


def _is_allowed_app_patch_path(target_path: str) -> bool:
    parts = target_path.split("/")
    if len(parts) < 3 or parts[0] != "generated_apps":
        return False
    if any(part in ("", ".", "..") for part in parts):
        return False
    if parts[2] == "app.config.json":
        return True
    return len(parts) >= 4 and parts[2] == "custom"


def _is_allowed_artifact_patch_path(target_path: str) -> bool:
    parts = target_path.split("/")
    if len(parts) < 3 or parts[0] != "artifacts":
        return False
    return not any(part in ("", ".", "..") for part in parts)


def _safe_id(value: str) -> bool:
    return bool(value) and all(ch.isalnum() or ch in "_.-" for ch in value)
