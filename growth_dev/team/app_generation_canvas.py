from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ..utils import read_json


APP_GENERATION_DOMAIN_ID = "app_generation"


BUSINESS_NODE_MAP: list[dict[str, Any]] = [
    {
        "id": "business_goal_understanding",
        "title": "理解业务目标",
        "runtime_nodes": ["skill_routing", "prd_input"],
        "artifact_refs": ["input_prd.md", "requirements/brief_analysis.json"],
    },
    {
        "id": "business_spec_compilation",
        "title": "编译业务规格",
        "runtime_nodes": ["prd_normalization", "context_contract"],
        "artifact_refs": ["requirements/normalized_prd.md", "app_contract.json", "requirements/capability_boundary.json"],
    },
    {
        "id": "app_structure_planning",
        "title": "规划应用结构",
        "runtime_nodes": ["planning_tdd"],
        "artifact_refs": ["acceptance_criteria.md", "planning/acceptance_coverage_matrix.json", "planning/tdd_plan.json"],
    },
    {
        "id": "prototype_generation",
        "title": "生成应用原型",
        "runtime_nodes": ["implementation"],
        "artifact_refs": ["codex/implementation_trace.json", "codex/diff.patch", "code_run_record.json"],
    },
    {
        "id": "capability_verification",
        "title": "验证业务能力",
        "runtime_nodes": ["review_quality", "verification"],
        "artifact_refs": ["review_report.md", "test_report.md", "codex/verification_record.json", "benchmark_diff.md", "agqs_score.json"],
    },
    {
        "id": "delivery_version",
        "title": "输出可交付版本",
        "runtime_nodes": ["preview_delivery"],
        "artifact_refs": ["preview_instructions.md", "final_report.md", "preview/preview_run_record.json"],
    },
]

BUSINESS_STEP_DETAILS: dict[str, dict[str, list[str]]] = {
    "business_goal_understanding": {
        "input_summary": ["用户上传的 PRD 原文", "项目 Skill 路由结果"],
        "process_summary": ["识别业务目标、用户角色、核心场景和成功标准"],
        "output_summary": ["业务目标摘要", "原始 PRD artifact", "待澄清或待确认的问题"],
        "available_actions": ["explain_step", "explain_step_io", "inspect_evidence", "suggest_input_patch"],
    },
    "business_spec_compilation": {
        "input_summary": ["业务目标", "原始 PRD", "业务上下文"],
        "process_summary": ["将 PRD 编译成标准化需求、能力边界和应用契约"],
        "output_summary": ["标准化 PRD", "能力清单", "应用契约", "安全与范围边界"],
        "available_actions": ["explain_step", "explain_step_io", "inspect_evidence", "suggest_input_patch", "rerun_step"],
    },
    "app_structure_planning": {
        "input_summary": ["应用契约", "能力清单", "验收标准"],
        "process_summary": ["规划页面流程、数据对象、状态流转和验证路径"],
        "output_summary": ["TDD 计划", "验收覆盖矩阵", "应用结构规划"],
        "available_actions": ["explain_step", "explain_step_io", "inspect_evidence", "rerun_step"],
    },
    "prototype_generation": {
        "input_summary": ["应用契约", "TDD 计划", "上下文包", "允许路径边界"],
        "process_summary": ["Code Agent 生成本地 SPA、Node 服务、样式、交互和 smoke 验证"],
        "output_summary": ["生成应用代码", "实现 diff", "运行记录", "runtime smoke 结果"],
        "available_actions": ["explain_step", "explain_step_io", "inspect_evidence", "rerun_step", "delegate_code_repair"],
    },
    "capability_verification": {
        "input_summary": ["生成应用", "验收标准", "测试报告", "可选 benchmark 证据"],
        "process_summary": ["验证业务能力、检查缺口、评估风险和可运行性"],
        "output_summary": ["验证记录", "测试报告", "能力缺口", "评分或风险摘要"],
        "available_actions": ["explain_step", "explain_step_io", "inspect_evidence", "verify_capability", "delegate_code_repair"],
    },
    "delivery_version": {
        "input_summary": ["验证结果", "生成应用", "交付说明"],
        "process_summary": ["整理交付报告、预览说明、修复记录和下一步建议"],
        "output_summary": ["最终报告", "预览说明", "可交付版本摘要"],
        "available_actions": ["explain_step", "explain_step_io", "inspect_evidence", "rerun_step"],
    },
}

ENTRY_STEP = {
    "id": "prd_entry",
    "title": "PRD 输入",
    "step_type": "ui",
    "runtime_nodes": [],
    "input_summary": ["用户输入 PRD 文本或上传 PRD 文件"],
    "process_summary": ["选择生成配置并创建 app_generation run"],
    "output_summary": ["原始 PRD artifact", "新的生成任务", "进入业务理解步骤"],
    "available_actions": ["start_generation", "explain_prd_requirements", "suggest_input_patch"],
}

PREVIEW_STEP = {
    "id": "app_preview",
    "title": "可预览应用",
    "step_type": "ui",
    "runtime_nodes": [],
    "input_summary": ["已生成应用原型", "验证记录", "交付报告"],
    "process_summary": ["发布应用快照、启动本地预览进程并检查健康状态"],
    "output_summary": ["可访问的本地预览 URL", "端口与进程状态", "预览日志"],
    "available_actions": ["publish_app", "start_preview", "stop_preview", "inspect_evidence", "delegate_code_repair"],
}


OBJECT_ACTIONS: dict[str, list[str]] = {
    "business_goal": ["explain_object", "suggest_object_patch", "rerun_business_node"],
    "scenario": ["explain_object", "suggest_object_patch", "rerun_business_node"],
    "capability": ["explain_object", "verify_capability", "repair_generated_app"],
    "page_flow": ["explain_object", "suggest_object_patch", "rerun_business_node"],
    "data_object": ["explain_object", "suggest_object_patch"],
    "provider_config": ["explain_object", "repair_generated_app", "verify_capability"],
    "artifact": ["explain_object"],
    "preview_session": ["explain_object", "repair_generated_app", "verify_capability"],
    "capability_gap": ["explain_object", "repair_generated_app", "verify_capability"],
    "repair_candidate": ["explain_object", "repair_generated_app"],
    "delivery_version": ["explain_object"],
}


SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password)(\s*[:=]\s*)([^\s\"',}]+)"),
]


def build_canvas_projection(run_id: str, *, runs_dir: Path = Path("runs"), repo_root: Path = Path(".")) -> dict[str, Any]:
    runs_dir = Path(runs_dir).resolve()
    repo_root = Path(repo_root).resolve()
    run_dir = _safe_run_dir(runs_dir, run_id)
    if not run_dir.exists():
        raise FileNotFoundError(f"Run not found: {run_id}")
    record = _safe_read_json(run_dir / "team_run_record.json")
    if str(record.get("domain_id", "")) != APP_GENERATION_DOMAIN_ID:
        process_for_domain = _safe_read_json(run_dir / "process.json")
        if not record and _process_domain_id(process_for_domain) == APP_GENERATION_DOMAIN_ID:
            record = _pending_app_generation_record(run_id, process_for_domain)
        else:
            raise ValueError(f"Run is not app_generation: {run_id}")

    process = _safe_read_json(run_dir / "process.json")
    contract = _safe_read_json(run_dir / "app_contract.json")
    inputs = record.get("inputs") if isinstance(record.get("inputs"), dict) else {}
    app_slug = str(inputs.get("app_slug") or contract.get("app_slug") or _slug_from_contract(contract) or run_id)
    warnings: list[dict[str, str]] = []
    quality_mode = _quality_mode(run_dir)
    run_status_value = str(record.get("status") or process.get("status") or "unknown")
    _terminal_statuses = {"completed", "failed", "blocked", "cancelled", "delivered"}
    run_active = run_status_value not in _terminal_statuses and run_status_value not in {"unknown", "draft", ""}
    objects = _build_canvas_objects(run_dir, app_slug, warnings)
    nodes = _build_business_nodes(run_dir, objects, quality_mode=quality_mode, run_active=run_active)
    current_business_node_id = next(
        (str(node["id"]) for node in nodes if node.get("is_current")), ""
    )
    flow_steps = _build_flow_steps(run_dir, nodes)
    classification_summary = _build_classification_summary(run_dir)
    projection = {
        "schema_version": 1,
        "run": {
            "run_id": run_id,
            "domain_id": APP_GENERATION_DOMAIN_ID,
            "app_slug": app_slug,
            "brief": str(record.get("brief", "")),
            "status": run_status_value,
            "quality_mode": quality_mode,
            "classification_summary": classification_summary,
        },
        "current_business_node_id": current_business_node_id,
        "flow_steps": flow_steps,
        "business_nodes": nodes,
        "objects": objects,
        "edges": _build_edges(objects),
        "versions": _build_versions(run_dir),
        "context_objects": _build_context_objects(run_dir, warnings),
        "warnings": warnings,
        "updated_at": _mtime_iso(run_dir),
    }
    return _redact(projection)


def build_canvas_object_detail(
    run_id: str,
    object_id: str,
    *,
    runs_dir: Path = Path("runs"),
    repo_root: Path = Path("."),
) -> dict[str, Any]:
    projection = build_canvas_projection(run_id, runs_dir=runs_dir, repo_root=repo_root)
    objects = projection.get("objects") if isinstance(projection.get("objects"), list) else []
    context_objects = projection.get("context_objects") if isinstance(projection.get("context_objects"), list) else []
    pool = [*objects, *context_objects]
    current = next((item for item in pool if isinstance(item, dict) and item.get("object_id") == object_id), None)
    if not isinstance(current, dict):
        raise ValueError(f"Unknown canvas object: {object_id}")
    edges = [edge for edge in projection.get("edges", []) if isinstance(edge, dict)]
    downstream_ids = {edge.get("to"): edge.get("type") for edge in edges if edge.get("from") == object_id}
    upstream_ids = {edge.get("from"): edge.get("type") for edge in edges if edge.get("to") == object_id}
    related_ids = set(downstream_ids) | set(upstream_ids)
    by_id = {item.get("object_id"): item for item in pool if isinstance(item, dict)}

    def _brief(object_id: str, relation: str | None) -> dict[str, Any]:
        item = by_id.get(object_id, {})
        return {
            "object_id": object_id,
            "object_type": item.get("object_type"),
            "title": item.get("title"),
            "status": item.get("status"),
            "relation": relation,
        }

    related = [_brief(oid, downstream_ids.get(oid) or upstream_ids.get(oid)) for oid in related_ids if oid in by_id]
    upstream = [_brief(oid, rel) for oid, rel in upstream_ids.items() if oid in by_id]
    downstream = [_brief(oid, rel) for oid, rel in downstream_ids.items() if oid in by_id]
    return _redact(
        {
            **current,
            "related_objects": related,
            "upstream_objects": upstream,
            "downstream_objects": downstream,
            "developer_refs": {
                "source_refs": current.get("source_refs", []),
                "artifact_refs": current.get("artifact_refs", []),
                "evidence_refs": current.get("evidence_refs", []),
            },
            "preview_refs": _preview_refs(current),
        }
    )


PIPELINE_ENTRY_LABEL = "PRD 输入"
PIPELINE_TERMINAL_LABEL = "可预览应用"


_CODER_BUSINESS_STATUS = {
    "pending": "未开始",
    "running": "执行中",
    "completed": "已完成",
    "prepared": "已生成候选改动",
    "failed": "失败",
}


def _read_progress_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    events: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


def _coder_tool_names(run_dir: Path) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for event in _read_progress_jsonl(run_dir / "codex" / "coder_progress.jsonl"):
        calls = event.get("tool_calls")
        if not isinstance(calls, list):
            continue
        for call in calls:
            if isinstance(call, dict):
                name = str(call.get("name") or call.get("tool") or call.get("type") or "").strip()
            else:
                name = str(call).strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
    return names


def _coder_progress_for_node(run_dir: Path, node_id: str) -> dict[str, Any]:
    if node_id != "prototype_generation":
        return {}
    events = _read_progress_jsonl(run_dir / "codex" / "coder_progress.jsonl")
    status = _safe_read_json(run_dir / "codex" / "coder_progress_status.json")
    if not events and not status:
        return {}
    changed_files: set[str] = set()
    tool_calls = 0
    steps: list[dict[str, Any]] = []
    for event in events:
        for change in event.get("file_changes", []) if isinstance(event.get("file_changes"), list) else []:
            if isinstance(change, dict):
                path = str(change.get("path") or change.get("file") or "").strip()
                if path:
                    changed_files.add(path)
        calls = event.get("tool_calls")
        if isinstance(calls, list):
            tool_calls += len(calls)
        steps.append(
            {
                "title": str(event.get("title") or ""),
                "business_status": str(event.get("business_status") or ""),
                "elapsed_ms": event.get("elapsed_ms", 0),
            }
        )
    latest = events[-1] if events else {}
    operation_status = str(status.get("status") or latest.get("status") or "unknown")
    business_status = str(
        latest.get("business_status")
        or _CODER_BUSINESS_STATUS.get(operation_status, operation_status)
    )
    return {
        "operation_status": operation_status,
        "business_status": business_status,
        "current_title": str(status.get("current_title") or latest.get("title") or ""),
        "current_summary": str(status.get("current_summary") or latest.get("summary") or ""),
        "files_changed": len(changed_files),
        "tool_calls": tool_calls,
        "elapsed_ms": status.get("elapsed_ms", latest.get("elapsed_ms", 0)),
        "steps": steps[-6:],
        "progress_refs": ["codex/coder_progress.jsonl", "codex/coder_progress_status.json"],
    }


def _context_object(
    context_id: str,
    context_type: str,
    title: str,
    summary: str,
    owner_node_id: str,
    *,
    source_refs: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "object_id": context_id,
        "object_type": context_type,
        "title": title,
        "summary": summary,
        "status": "context",
        "owner_node_id": owner_node_id,
        "owner_node": _business_node_title(owner_node_id),
        "source_refs": source_refs or [],
        "artifact_refs": [],
        "evidence_refs": [],
        "editable_fields": [],
        "actions": ["explain_object"],
        "risks": [],
        "is_context": True,
    }


def _build_context_objects(run_dir: Path, warnings: list[dict[str, str]]) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []

    boundary = _safe_read_json(run_dir / "requirements" / "capability_boundary.json")
    scenario_caps = _capability_items(boundary)
    if (run_dir / "requirements" / "normalized_prd.md").exists() or scenario_caps:
        cap_titles = "、".join(
            str(item.get("summary") or item.get("label") or item.get("id") or "")
            for item in scenario_caps[:3]
            if isinstance(item, dict)
        )
        summary = cap_titles or _text_summary(
            run_dir / "requirements" / "normalized_prd.md", "PRD 描述的业务场景与使用范围。"
        )
        contexts.append(
            _context_object(
                "scenario:business",
                "scenario",
                "业务场景",
                _truncate(summary, 160),
                "business_spec_compilation",
                source_refs=["requirements/normalized_prd.md", "requirements/capability_boundary.json"],
            )
        )

    contract = _safe_read_json(run_dir / "app_contract.json", warnings, "app_contract.json")
    if contract:
        target_stack = contract.get("target_stack") if isinstance(contract.get("target_stack"), dict) else {}
        contexts.append(
            _context_object(
                "data:target_stack",
                "data_object",
                "数据与存储依赖",
                f"前端：{target_stack.get('frontend') or 'native_spa'}；服务端：{target_stack.get('backend') or 'node_stdlib'}；"
                f"存储：{target_stack.get('storage') or 'localStorage'}；数据库：{target_stack.get('database') or 'none'}。",
                "business_spec_compilation",
                source_refs=["app_contract.json"],
            )
        )

    if (run_dir / "context_pack.md").exists():
        contexts.append(
            _context_object(
                "knowledge:context_pack",
                "knowledge_source",
                "场景依赖知识",
                _text_summary(run_dir / "context_pack.md", "为生成提供的领域知识与上下文。"),
                "business_goal_understanding",
                source_refs=["context_pack.md"],
            )
        )

    tool_names = _coder_tool_names(run_dir)
    if tool_names:
        contexts.append(
            _context_object(
                "tool:code_agent",
                "tool_call",
                "工具调用",
                f"Code Agent 调用工具：{'、'.join(tool_names[:6])}。",
                "prototype_generation",
                source_refs=["codex/coder_progress.jsonl"],
            )
        )
    return contexts


def _build_business_nodes(
    run_dir: Path,
    objects: list[dict[str, Any]],
    *,
    quality_mode: str,
    run_active: bool = False,
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    total = len(BUSINESS_NODE_MAP)
    current_assigned = False
    for index, definition in enumerate(BUSINESS_NODE_MAP):
        artifact_refs = [str(path) for path in definition.get("artifact_refs", [])]
        required_refs = _required_artifact_refs(str(definition["id"]), artifact_refs, quality_mode)
        existing = [path for path in artifact_refs if (run_dir / path).exists()]
        required_existing = [path for path in required_refs if (run_dir / path).exists()]
        node_objects = [item for item in objects if item.get("owner_node_id") == definition["id"]]
        ready = len(required_existing)
        required = len(required_refs)
        input_from = BUSINESS_NODE_MAP[index - 1]["title"] if index > 0 else PIPELINE_ENTRY_LABEL
        output_to = BUSINESS_NODE_MAP[index + 1]["title"] if index < total - 1 else PIPELINE_TERMINAL_LABEL
        step_details = BUSINESS_STEP_DETAILS.get(str(definition["id"]), {})
        incomplete = required <= 0 or ready < required
        is_current = run_active and incomplete and not current_assigned
        if is_current:
            current_assigned = True
        node_status = "running" if is_current else _business_node_status(definition["id"], ready, required)
        nodes.append(
            {
                "id": definition["id"],
                "title": definition["title"],
                "step_type": "business",
                "stage_index": index + 1,
                "stage_total": total,
                "is_entry": index == 0,
                "is_terminal": index == total - 1,
                "is_current": is_current,
                "input_from": input_from,
                "output_to": output_to,
                "runtime_nodes": definition["runtime_nodes"],
                "status": node_status,
                "summary": _business_node_summary(str(definition["id"]), len(node_objects), ready, required),
                "input_summary": list(step_details.get("input_summary", [])),
                "process_summary": list(step_details.get("process_summary", [])),
                "output_summary": list(step_details.get("output_summary", [])),
                "available_actions": list(step_details.get("available_actions", ["explain_step", "inspect_evidence"])),
                "object_count": len(node_objects),
                "object_counts": _count_by_type(node_objects),
                "progress": {
                    "ready_artifacts": ready,
                    "required_artifacts": required,
                    "ratio": round(ready / required, 3) if required else 0.0,
                },
                "coder_progress": _coder_progress_for_node(run_dir, str(definition["id"])),
                "latest_event": _latest_event_for_node(run_dir, str(definition["id"])),
                "artifact_refs": artifact_refs,
                "evidence_refs": existing,
            }
        )
    return nodes


def _required_artifact_refs(node_id: str, artifact_refs: list[str], quality_mode: str) -> list[str]:
    if node_id == "capability_verification" and quality_mode != "benchmark_parity":
        return [path for path in artifact_refs if path not in {"benchmark_diff.md", "agqs_score.json"}]
    return artifact_refs


def _build_flow_steps(run_dir: Path, business_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    steps.append(_entry_flow_step(run_dir))
    for node in business_nodes:
        steps.append(dict(node))
    steps.append(_preview_flow_step(run_dir))
    total = len(steps)
    for index, step in enumerate(steps):
        step["stage_index"] = index + 1
        step["stage_total"] = total
        step["is_entry"] = index == 0
        step["is_terminal"] = index == total - 1
    return steps


def _entry_flow_step(run_dir: Path) -> dict[str, Any]:
    step = dict(ENTRY_STEP)
    exists = (run_dir / "input_prd.md").exists()
    step.update(
        {
            "status": "drafted" if exists else "ready",
            "summary": "用户输入 PRD 并发起应用生成。",
            "input_from": "用户",
            "output_to": "理解业务目标",
            "object_count": 1 if exists else 0,
            "object_counts": {"business_goal": 1} if exists else {},
            "progress": {"ready_artifacts": 1 if exists else 0, "required_artifacts": 1, "ratio": 1.0 if exists else 0.0},
            "coder_progress": {},
            "latest_event": "PRD 已进入生成任务。" if exists else "",
            "artifact_refs": ["input_prd.md"],
            "evidence_refs": ["input_prd.md"] if exists else [],
        }
    )
    return step


def _preview_flow_step(run_dir: Path) -> dict[str, Any]:
    step = dict(PREVIEW_STEP)
    preview_record = _safe_read_json(run_dir / "preview" / "preview_run_record.json")
    publish_record = _safe_read_json(run_dir / "app_publish.json")
    evidence_refs: list[str] = []
    if publish_record:
        evidence_refs.append("app_publish.json")
    if preview_record:
        evidence_refs.append("preview/preview_run_record.json")
    status = "not_published"
    latest_event = ""
    if preview_record:
        raw = str(preview_record.get("status") or "")
        status = "running" if raw in {"running", "ready"} else (raw or "published")
        latest_event = f"预览状态：{status}。"
    elif publish_record:
        status = "published"
        latest_event = "应用快照已发布。"
    step.update(
        {
            "status": status,
            "summary": "发布快照并启动本地预览。",
            "input_from": "输出可交付版本",
            "output_to": "用户可试用应用",
            "object_count": 1 if evidence_refs else 0,
            "object_counts": {"preview_session": 1} if preview_record else {},
            "progress": {"ready_artifacts": len(evidence_refs), "required_artifacts": 2, "ratio": round(len(evidence_refs) / 2, 3)},
            "coder_progress": {},
            "latest_event": latest_event,
            "artifact_refs": ["app_publish.json", "preview/preview_run_record.json"],
            "evidence_refs": evidence_refs,
        }
    )
    return step


def _build_canvas_objects(run_dir: Path, app_slug: str, warnings: list[dict[str, str]]) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    if (run_dir / "input_prd.md").exists():
        objects.append(
            _canvas_object(
                "business_goal:primary",
                "business_goal",
                "业务目标",
                _text_summary(run_dir / "input_prd.md", "从 PRD 中识别用户目标和成功标准。"),
                "drafted",
                "business_goal_understanding",
                source_refs=["input_prd.md"],
            )
        )
    if (run_dir / "requirements" / "normalized_prd.md").exists():
        objects.append(
            _canvas_object(
                "scenario:normalized_scope",
                "scenario",
                "标准化业务场景",
                _text_summary(run_dir / "requirements" / "normalized_prd.md", "已形成标准化需求和范围边界。"),
                "drafted",
                "business_spec_compilation",
                source_refs=["requirements/normalized_prd.md"],
            )
        )

    boundary = _safe_read_json(run_dir / "requirements" / "capability_boundary.json", warnings, "requirements/capability_boundary.json")
    for capability in _capability_items(boundary):
        capability_id = _slug(str(capability.get("id") or capability.get("summary") or "capability"))
        objects.append(
            _canvas_object(
                f"capability:{capability_id}",
                "capability",
                str(capability.get("label") or capability.get("title") or capability.get("id") or "应用能力"),
                str(capability.get("summary") or capability.get("description") or "PRD 要求生成应用支持该能力。"),
                "planned",
                "business_spec_compilation",
                source_refs=["requirements/capability_boundary.json", "app_contract.json"],
                evidence_refs=["planning/acceptance_coverage_matrix.json"],
            )
        )

    contract = _safe_read_json(run_dir / "app_contract.json", warnings, "app_contract.json")
    if contract:
        target_stack = contract.get("target_stack") if isinstance(contract.get("target_stack"), dict) else {}
        provider = contract.get("provider") if isinstance(contract.get("provider"), dict) else {}
        objects.append(
            _canvas_object(
                "data_object:local_state",
                "data_object",
                "本地状态数据",
                f"持久化方式：{target_stack.get('storage') or 'localStorage'}；数据库：{target_stack.get('database') or 'none'}。",
                "planned",
                "business_spec_compilation",
                source_refs=["app_contract.json"],
            )
        )
        objects.append(
            _canvas_object(
                "provider_config:runtime",
                "provider_config",
                "服务与模型配置",
                _provider_summary(provider, target_stack),
                "planned",
                "business_spec_compilation",
                source_refs=["app_contract.json"],
            )
        )

    if (run_dir / "planning" / "tdd_plan.json").exists():
        objects.append(
            _canvas_object(
                "page_flow:planned_app",
                "page_flow",
                "应用结构与验证计划",
                _tdd_summary(run_dir / "planning" / "tdd_plan.json", warnings),
                "planned",
                "app_structure_planning",
                source_refs=["planning/tdd_plan.json", "planning/acceptance_coverage_matrix.json"],
            )
        )

    if (run_dir / "codex" / "implementation_trace.json").exists() or (run_dir / "codex" / "diff.patch").exists():
        objects.append(
            _canvas_object(
                "artifact:generated_app",
                "artifact",
                "已生成应用原型",
                f"生成目录：generated_apps/{app_slug}。",
                "generated",
                "prototype_generation",
                artifact_refs=[f"generated_apps/{app_slug}", "codex/implementation_trace.json", "codex/diff.patch"],
            )
        )

    if (run_dir / "codex" / "verification_record.json").exists() or (run_dir / "test_report.md").exists():
        objects.append(
            _canvas_object(
                "artifact:verification",
                "artifact",
                "业务能力验证证据",
                _verification_summary(run_dir, warnings),
                "verified",
                "capability_verification",
                evidence_refs=["codex/verification_record.json", "test_report.md"],
            )
        )

    preview_record = _safe_read_json(run_dir / "preview" / "preview_run_record.json", warnings, "preview/preview_run_record.json")
    if preview_record:
        objects.append(
            _canvas_object(
                "preview_session:current",
                "preview_session",
                "当前应用预览",
                f"预览状态：{preview_record.get('status', 'unknown')}；地址：{preview_record.get('url', '未记录')}。",
                "generated" if str(preview_record.get("status")) in {"running", "ready"} else "needs_attention",
                "delivery_version",
                evidence_refs=["preview/preview_run_record.json"],
            )
        )

    agqs = _safe_read_json(run_dir / "agqs_score.json", warnings, "agqs_score.json")
    for event in _string_list(agqs.get("blocking_events")):
        gap_id = _slug(event)
        objects.append(
            _canvas_object(
                f"capability_gap:{gap_id}",
                "capability_gap",
                "能力缺口",
                event,
                "blocked",
                "capability_verification",
                evidence_refs=["agqs_score.json", "benchmark_diff.md"],
            )
        )

    for repair_path in sorted((run_dir / "app_repairs").glob("*/repair_result.json")):
        repair = _safe_read_json(repair_path, warnings, str(repair_path.relative_to(run_dir)))
        if not repair:
            continue
        repair_id = _slug(str(repair.get("repair_id") or repair_path.parent.name))
        objects.append(
            _canvas_object(
                f"repair_candidate:{repair_id}",
                "repair_candidate",
                "修复候选",
                str(repair.get("summary") or repair.get("status") or "Code Agent 已生成修复候选。"),
                "drafted" if str(repair.get("status")) in {"prepared", "dry_run"} else "needs_attention",
                "delivery_version",
                evidence_refs=[str(repair_path.relative_to(run_dir))],
            )
        )

    if (run_dir / "final_report.md").exists():
        objects.append(
            _canvas_object(
                "delivery_version:latest",
                "delivery_version",
                "可交付版本",
                _text_summary(run_dir / "final_report.md", "已形成交付说明。"),
                "delivered",
                "delivery_version",
                evidence_refs=["final_report.md", "preview_instructions.md"],
            )
        )
    return objects


def _canvas_object(
    object_id: str,
    object_type: str,
    title: str,
    summary: str,
    status: str,
    owner_node_id: str,
    *,
    source_refs: list[str] | None = None,
    artifact_refs: list[str] | None = None,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "object_id": object_id,
        "object_type": object_type,
        "title": title,
        "summary": summary,
        "status": status,
        "owner_node_id": owner_node_id,
        "owner_node": _business_node_title(owner_node_id),
        "source_refs": source_refs or [],
        "artifact_refs": artifact_refs or [],
        "evidence_refs": evidence_refs or [],
        "editable_fields": _editable_fields(object_type),
        "actions": OBJECT_ACTIONS.get(object_type, ["explain_object"]),
        "risks": [],
    }


def _capability_items(boundary: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key in ("required_new_capabilities", "existing_capabilities", "capabilities"):
        value = boundary.get(key)
        if isinstance(value, list):
            items.extend(item for item in value if isinstance(item, dict))
    return items


def _build_edges(objects: list[dict[str, Any]]) -> list[dict[str, str]]:
    ids = {str(item.get("object_id")) for item in objects}
    capabilities = [str(item.get("object_id")) for item in objects if item.get("object_type") == "capability"]
    gaps = [str(item.get("object_id")) for item in objects if item.get("object_type") == "capability_gap"]
    repairs = [str(item.get("object_id")) for item in objects if item.get("object_type") == "repair_candidate"]
    edges: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def link(src: str, dst: str, edge_type: str) -> None:
        if src not in ids or dst not in ids or src == dst:
            return
        key = (src, dst, edge_type)
        if key in seen:
            return
        seen.add(key)
        edges.append({"from": src, "to": dst, "type": edge_type})

    upstream_for_capability = (
        "scenario:normalized_scope" if "scenario:normalized_scope" in ids else "business_goal:primary"
    )
    link("business_goal:primary", "scenario:normalized_scope", "requires")
    for capability in capabilities:
        link(upstream_for_capability, capability, "requires")
        link(capability, "page_flow:planned_app", "produces")
        link(capability, "data_object:local_state", "produces")
        if "page_flow:planned_app" not in ids:
            link(capability, "artifact:generated_app", "produces")
    link("page_flow:planned_app", "artifact:generated_app", "produces")
    link("provider_config:runtime", "artifact:generated_app", "requires")
    link("artifact:generated_app", "artifact:verification", "evidenced_by")
    link("artifact:generated_app", "preview_session:current", "produces")
    for gap in gaps:
        link("artifact:generated_app", gap, "evidenced_by")
    for repair in repairs:
        link("artifact:generated_app", repair, "produces")
    for upstream in ("artifact:verification", "preview_session:current"):
        link(upstream, "delivery_version:latest", "produces")
    return edges


def _build_versions(run_dir: Path) -> list[dict[str, Any]]:
    versions: list[dict[str, Any]] = []
    publish = _safe_read_json(run_dir / "app_publish.json")
    if publish:
        versions.append({"id": "publish:latest", "type": "publish", "title": "发布快照", "status": publish.get("status", "published"), "evidence_refs": ["app_publish.json"]})
    patch_index = _safe_read_json(run_dir / "app_patches" / "index.json")
    patches = patch_index.get("patches") if isinstance(patch_index.get("patches"), list) else []
    for item in patches:
        if isinstance(item, dict):
            versions.append({"id": f"patch:{item.get('patch_id') or len(versions)}", "type": "patch", "title": "应用补丁", "status": item.get("status", "unknown"), "evidence_refs": ["app_patches/index.json"]})
    for repair_path in sorted((run_dir / "app_repairs").glob("*/repair_result.json")):
        repair = _safe_read_json(repair_path)
        if repair:
            versions.append({"id": f"repair:{repair_path.parent.name}", "type": "repair", "title": "Code Agent 修复", "status": repair.get("status", "unknown"), "evidence_refs": [str(repair_path.relative_to(run_dir))]})
    return versions


def _safe_run_dir(runs_dir: Path, run_id: str) -> Path:
    candidate = Path(str(run_id))
    if candidate.is_absolute() or len(candidate.parts) != 1 or candidate.name != str(run_id) or candidate.name in {"", ".", ".."}:
        raise ValueError("Run id must identify one directory inside runs.")
    return _safe_child(Path(runs_dir).resolve(), candidate.name)


def _safe_child(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts or not str(candidate):
        raise ValueError("Path must stay inside the allowed directory.")
    target = (root / candidate).resolve()
    root_resolved = root.resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise ValueError("Path escapes the allowed directory.")
    return target


def _safe_read_json(path: Path, warnings: list[dict[str, str]] | None = None, rel_path: str | None = None) -> dict[str, Any]:
    try:
        payload = read_json(path)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        if warnings is not None:
            warnings.append({"id": "artifact_json_invalid", "path": rel_path or str(path), "summary": str(exc)})
        return {}
    return payload if isinstance(payload, dict) else {}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if _looks_secret_key(str(key)):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        text = value
        for pattern in SECRET_PATTERNS:
            if pattern.pattern.startswith("(?i)"):
                text = pattern.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)
            else:
                text = pattern.sub("[REDACTED]", text)
        return text
    return value


def _looks_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in ("api_key", "apikey", "secret", "token", "password"))


def _text_summary(path: Path, fallback: str) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return fallback
    lines = [line.strip("#- \t") for line in text.splitlines() if line.strip()]
    return _truncate("；".join(lines[:2]) or fallback, 160)


def _tdd_summary(path: Path, warnings: list[dict[str, str]]) -> str:
    payload = _safe_read_json(path, warnings, "planning/tdd_plan.json")
    cases = payload.get("test_cases") if isinstance(payload.get("test_cases"), list) else []
    return f"已规划 {len(cases)} 个验证用例。" if cases else "已生成应用结构和验证计划。"


def _verification_summary(run_dir: Path, warnings: list[dict[str, str]]) -> str:
    payload = _safe_read_json(run_dir / "codex" / "verification_record.json", warnings, "codex/verification_record.json")
    commands = payload.get("commands") if isinstance(payload.get("commands"), list) else []
    status = str(payload.get("status") or "unknown")
    return f"验证状态：{status}；命令数：{len(commands)}。"


def _provider_summary(provider: dict[str, Any], target_stack: dict[str, Any]) -> str:
    provider_name = str(provider.get("name") or provider.get("provider") or "未声明")
    frontend = str(target_stack.get("frontend") or "native_spa")
    backend = str(target_stack.get("backend") or "node_stdlib")
    return f"Provider：{provider_name}；前端：{frontend}；服务端：{backend}。"


def _business_node_status(node_id: str, existing_count: int, total_count: int) -> str:
    if total_count <= 0 or existing_count <= 0:
        return "not_started"
    if existing_count < total_count:
        return "generating"
    return {
        "business_goal_understanding": "drafted",
        "business_spec_compilation": "drafted",
        "app_structure_planning": "planned",
        "prototype_generation": "generated",
        "capability_verification": "verified",
        "delivery_version": "delivered",
    }.get(node_id, "generated")


def _business_node_summary(node_id: str, object_count: int, existing_count: int, total_count: int) -> str:
    title = _business_node_title(node_id)
    return f"{title}已关联 {object_count} 个业务对象，{existing_count}/{total_count} 个关键产物可用。"


def _business_node_title(node_id: str) -> str:
    return next((item["title"] for item in BUSINESS_NODE_MAP if item["id"] == node_id), node_id)


def _latest_event_for_node(run_dir: Path, node_id: str) -> str:
    if node_id == "prototype_generation":
        trace = _safe_read_json(run_dir / "codex" / "implementation_trace.json")
        steps = trace.get("steps") if isinstance(trace.get("steps"), list) else []
        if steps and isinstance(steps[-1], dict):
            return str(steps[-1].get("summary") or steps[-1].get("title") or "应用实现已有进展。")
    if node_id == "delivery_version" and (run_dir / "preview" / "preview_run_record.json").exists():
        return "应用预览记录已生成。"
    return ""


def _count_by_type(objects: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in objects:
        key = str(item.get("object_type") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _editable_fields(object_type: str) -> list[str]:
    if object_type in {"business_goal", "scenario", "capability", "page_flow"}:
        return ["summary", "acceptance", "priority"]
    if object_type == "provider_config":
        return ["summary"]
    return []


def _preview_refs(canvas_object: dict[str, Any]) -> list[dict[str, str]]:
    refs = []
    for path in canvas_object.get("artifact_refs", []) + canvas_object.get("evidence_refs", []):
        refs.append({"path": str(path), "read_mode": "artifact_preview"})
    return refs


def _quality_mode(run_dir: Path) -> str:
    benchmark = _safe_read_json(run_dir / "benchmark_context.json")
    return str(benchmark.get("quality_mode") or "prototype")


def _process_command(process: dict[str, Any]) -> list[str]:
    command = process.get("command") if isinstance(process, dict) else []
    return [str(item) for item in command] if isinstance(command, list) else []


def _process_command_arg(process: dict[str, Any], flag: str) -> str:
    command = _process_command(process)
    for index, item in enumerate(command):
        if item == flag and index + 1 < len(command):
            return command[index + 1]
    return ""


def _process_domain_id(process: dict[str, Any]) -> str:
    return _process_command_arg(process, "--domain")


def _process_inputs_json(process: dict[str, Any]) -> dict[str, Any]:
    raw = _process_command_arg(process, "--inputs-json")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _pending_app_generation_record(run_id: str, process: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "domain_id": APP_GENERATION_DOMAIN_ID,
        "brief": _process_command_arg(process, "--brief"),
        "status": str(process.get("status") or "starting") if isinstance(process, dict) else "starting",
        "inputs": _process_inputs_json(process),
        "agent_runs": [],
        "risk_events": [],
    }


def _slug_from_contract(contract: dict[str, Any]) -> str:
    generated = str(contract.get("generated_app_dir") or "")
    if generated:
        return Path(generated).name
    return ""


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if isinstance(value, str) and value:
        return [value]
    return []


def _slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("_")
    return normalized[:96] or hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(limit - 1, 0)] + "…"


def _mtime_iso(path: Path) -> str:
    try:
        return str(path.stat().st_mtime)
    except OSError:
        return ""


def _build_classification_summary(run_dir: Path) -> dict[str, Any]:
    classification = _safe_read_json(run_dir / "codex" / "failure_classification.json")
    if not isinstance(classification, dict) or not classification:
        return {"decision": "", "primary_reason": "", "blocker_preview": "", "blocking_count": 0, "warnings_count": 0}
    decision = str(classification.get("classification_decision") or "")
    blocking_events = _string_list(classification.get("blocking_events"))
    warnings_list = _string_list(classification.get("warnings"))
    evidence = classification.get("evidence") if isinstance(classification.get("evidence"), dict) else {}
    codex_blockers = _string_list(evidence.get("codex_blockers"))
    primary_reason = str(classification.get("primary_reason") or "")
    preview_source = codex_blockers[0] if codex_blockers else (warnings_list[0] if warnings_list else primary_reason)
    blocker_preview = _truncate(preview_source, 120) if preview_source else ""
    return {
        "decision": decision,
        "primary_reason": primary_reason,
        "blocker_preview": blocker_preview,
        "blocking_count": len(blocking_events),
        "warnings_count": len(warnings_list),
        "artifact_path": "codex/failure_classification.md",
    }
