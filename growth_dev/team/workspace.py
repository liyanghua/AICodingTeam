from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..utils import ensure_dir, now_iso, read_json, write_json

TASK_WORKSPACE_JSON = "task_workspace.json"
TASK_WORKSPACE_MD = "task_workspace.md"
TASK_JOURNAL_JSONL = "task_journal.jsonl"
TASK_JOURNAL_MD = "task_journal.md"
TOOL_CONTEXT_CODEX = "tool_context/codex.md"

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"(?i)(AICODEMIRROR_KEY\s*[:=]\s*)[^\s,;'\"\n]+"),
    re.compile(r"(?i)((api[_-]?key|secret|token|password|dsn)\s*[:=]\s*)[^\s,;'\"\n]+"),
    re.compile(r"(?i)(postgres(?:ql)?://)[^\s,;'\"\n]+"),
    re.compile(r"\.env(?:\.[A-Za-z0-9_-]+)?"),
]


def refresh_task_workspace(run_id: str, *, runs_dir: Path = Path("runs")) -> dict[str, Any]:
    run_dir = _safe_run_dir(Path(runs_dir), run_id)
    if not run_dir.exists():
        raise FileNotFoundError(f"Run not found: {run_id}")
    workspace = build_task_workspace(run_id, runs_dir=runs_dir)
    journal_events = build_task_journal(run_id, runs_dir=runs_dir, workspace=workspace)
    write_json(run_dir / TASK_WORKSPACE_JSON, workspace)
    (run_dir / TASK_WORKSPACE_MD).write_text(format_task_workspace(workspace), encoding="utf-8")
    merged_journal_events = _write_journal(run_dir, journal_events)
    (run_dir / TASK_JOURNAL_MD).write_text(format_task_journal(merged_journal_events), encoding="utf-8")
    context_path = run_dir / TOOL_CONTEXT_CODEX
    ensure_dir(context_path.parent)
    context_path.write_text(format_codex_tool_context(workspace), encoding="utf-8")
    return {
        "run_id": run_id,
        "artifacts": {
            "task_workspace": TASK_WORKSPACE_MD,
            "task_workspace_json": TASK_WORKSPACE_JSON,
            "task_journal": TASK_JOURNAL_MD,
            "task_journal_jsonl": TASK_JOURNAL_JSONL,
            "codex_tool_context": TOOL_CONTEXT_CODEX,
        },
        "task_workspace": workspace,
        "task_journal": {"events": merged_journal_events},
    }


def build_task_workspace(run_id: str, *, runs_dir: Path = Path("runs")) -> dict[str, Any]:
    run_dir = _safe_run_dir(Path(runs_dir), run_id)
    record = _safe_json(run_dir / "team_run_record.json")
    if not isinstance(record, dict):
        record = {}
    coverage = _safe_json(run_dir / "planning" / "acceptance_coverage_matrix.json")
    if not isinstance(coverage, dict):
        coverage = {}
    boundary = _safe_json(run_dir / "requirements" / "capability_boundary.json")
    if not isinstance(boundary, dict):
        boundary = {}
    slice_loop = _safe_json(run_dir / "codex" / "slice_loop_state.json")
    if not isinstance(slice_loop, dict):
        slice_loop = {}
    completion_gate = _safe_json(run_dir / "implementation_completion_gate.json")
    if not isinstance(completion_gate, dict):
        completion_gate = {}

    warnings = _artifact_warnings(
        run_dir,
        [
            "team_run_record.json",
            "acceptance_criteria.md",
            "requirements/capability_boundary.json",
            "planning/acceptance_coverage_matrix.json",
            "planning/tdd_plan.json",
            "codex/slice_loop_state.json",
            "implementation_completion_gate.json",
        ],
    )
    blockers = _dedupe(_string_list(record.get("risk_events")) + _extract_blockers(record) + _string_list(slice_loop.get("blockers")) + _string_list(completion_gate.get("blockers")))
    verification_commands = _dedupe(_verification_commands(coverage, slice_loop, run_dir))
    workspace = {
        "schema_version": 1,
        "run_id": str(record.get("run_id") or run_id),
        "generated_at": now_iso(),
        "loop_phase": _loop_phase(run_dir, record, slice_loop, completion_gate),
        "objective": _redact_text(str(record.get("brief", ""))),
        "domain_id": _redact_text(str(record.get("domain_id", ""))),
        "task_type": _task_type(record),
        "current_focus": _current_focus(record, slice_loop, completion_gate, blockers),
        "acceptance_criteria": _acceptance_criteria(run_dir, coverage),
        "capability_boundary": _redact(boundary),
        "slices": _slice_summary(coverage, slice_loop),
        "gates": _gate_summary(record, completion_gate),
        "blockers": [_redact_text(item) for item in blockers],
        "warnings": [_redact_text(item) for item in warnings],
        "verification_commands": verification_commands,
        "artifact_links": _artifact_links(run_dir),
        "next_actions": _next_actions(record, slice_loop, completion_gate, blockers),
    }
    return _redact(workspace)


def build_task_journal(run_id: str, *, runs_dir: Path = Path("runs"), workspace: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    run_dir = _safe_run_dir(Path(runs_dir), run_id)
    workspace = workspace or build_task_workspace(run_id, runs_dir=runs_dir)
    events: list[dict[str, Any]] = []
    for event in _read_events(run_dir):
        name = str(event.get("event", ""))
        if name == "gate_checked":
            gate_id = str(event.get("gate_id", ""))
            status = str(event.get("status", ""))
            normalized = f"{gate_id}_gate_{'passed' if status == 'passed' else 'blocked'}" if gate_id else "gate_checked"
            events.append(_journal_event(run_id, _event_time(event), _phase_for_event(normalized, workspace), normalized, status, f"Gate `{gate_id}` {status}.", [gate_id], _string_list(event.get("missing_artifacts")), []))
        elif name in {"run_started", "run_completed", "run_failed", "complex_task_artifacts_generated", "memory_recall_generated", "agent_started", "agent_completed", "risk_event"}:
            status = str(event.get("status") or event.get("reason") or "")
            summary = _event_summary(name, event)
            blockers = _string_list(event.get("risk_event")) + _string_list(event.get("reason"))
            events.append(_journal_event(run_id, _event_time(event), _phase_for_event(name, workspace), name, status, summary, _event_evidence(event), blockers, []))

    for phase_event, artifact in [
        ("plan_artifacts_ready", "planning/acceptance_coverage_matrix.json"),
        ("slice_loop_observed", "codex/slice_loop_state.json"),
        ("verify_completed", "implementation_completion_gate.json"),
        ("finish_learning_ready", "learning_summary.json"),
    ]:
        if (run_dir / artifact).exists():
            events.append(_journal_event(run_id, _mtime_or_now(run_dir / artifact), _phase_for_event(phase_event, workspace), phase_event, "available", f"`{artifact}` is available.", [artifact], [], []))
    return _dedupe_events([_redact(event) for event in events])


def format_task_workspace(workspace: dict[str, Any]) -> str:
    slices = workspace.get("slices") if isinstance(workspace.get("slices"), dict) else {}
    lines = [
        f"# Task Workspace: {workspace.get('run_id', '')}",
        "",
        f"- Loop phase: `{workspace.get('loop_phase', '')}`",
        f"- Domain: `{workspace.get('domain_id', '')}`",
        f"- Task type: `{workspace.get('task_type', '')}`",
        f"- Current focus: {workspace.get('current_focus', '') or '暂无'}",
        "",
        "## Objective",
        "",
        str(workspace.get("objective") or "暂无目标。"),
        "",
        "## Slices",
        "",
        f"- Active: `{(slices.get('active') or {}).get('id', '') if isinstance(slices.get('active'), dict) else ''}`",
        *_list_lines("Completed", [str(item.get("id", "")) for item in slices.get("completed", []) if isinstance(item, dict)]),
        *_list_lines("Pending", [str(item.get("id", "")) for item in slices.get("pending", []) if isinstance(item, dict)]),
        *_list_lines("Blocked", [str(item.get("id", "")) for item in slices.get("blocked", []) if isinstance(item, dict)]),
        "",
        "## Gates",
        "",
        *_list_lines("Gates", [f"{item.get('id', '')}: {item.get('status', '')}" for item in workspace.get("gates", []) if isinstance(item, dict)], empty="暂无 Gate 信息。"),
        "",
        "## Blockers / Warnings",
        "",
        *_list_lines("Blockers", workspace.get("blockers", []), empty="暂无阻塞。"),
        *_list_lines("Warnings", workspace.get("warnings", []), empty="暂无 warning。"),
        "",
        "## Verification",
        "",
        *_list_lines("Commands", workspace.get("verification_commands", []), empty="暂无验证命令。"),
        "",
        "## Next Actions",
        "",
        *_list_lines("Next", workspace.get("next_actions", []), empty="暂无下一步。"),
    ]
    return "\n".join(lines).rstrip() + "\n"


def format_task_journal(events: list[dict[str, Any]]) -> str:
    lines = ["# Task Journal", ""]
    if not events:
        lines.append("暂无任务事件。")
        return "\n".join(lines).rstrip() + "\n"
    for event in events:
        lines.extend(
            [
                f"## {event.get('timestamp', '')} · {event.get('event', '')}",
                "",
                f"- Phase: `{event.get('loop_phase', '')}`",
                f"- Status: `{event.get('status', '')}`",
                f"- Summary: {event.get('summary', '')}",
                *_list_lines("Evidence", event.get("evidence", []), empty=""),
                *_list_lines("Blockers", event.get("blockers", []), empty=""),
                *_list_lines("Warnings", event.get("warnings", []), empty=""),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def format_codex_tool_context(workspace: dict[str, Any]) -> str:
    slices = workspace.get("slices") if isinstance(workspace.get("slices"), dict) else {}
    active = slices.get("active") if isinstance(slices.get("active"), dict) else {}
    lines = [
        "# Codex Tool Context",
        "",
        "## Overall goal",
        "",
        str(workspace.get("objective") or "No objective recorded."),
        "",
        "## Current loop phase",
        "",
        f"`{workspace.get('loop_phase', '')}`",
        "",
        "## Current slice",
        "",
        f"- `{active.get('id', '')}` {active.get('title', '')}" if active else "- No active slice.",
        "",
        "## Acceptance criteria",
        "",
        *_list_lines("AC", [f"{item.get('id', '')}: {item.get('description', '')}" for item in workspace.get("acceptance_criteria", []) if isinstance(item, dict)], empty="No acceptance criteria recorded."),
        "",
        "## Capability boundary",
        "",
        json.dumps(workspace.get("capability_boundary", {}), ensure_ascii=False, indent=2),
        "",
        "## Allowed paths",
        "",
        *_list_lines("Paths", _allowed_paths(workspace), empty="Use paths declared by the current run artifacts."),
        "",
        "## Stop conditions",
        "",
        *_list_lines("Stop", workspace.get("blockers", []), empty="Stop if new blockers, safety risks, or unrelated changes appear."),
        "",
        "## Verification commands",
        "",
        *_list_lines("Commands", workspace.get("verification_commands", []), empty="No verification commands recorded."),
        "",
        "## Blockers / warnings",
        "",
        *_list_lines("Blockers", workspace.get("blockers", []), empty="No blockers recorded."),
        *_list_lines("Warnings", workspace.get("warnings", []), empty="No warnings recorded."),
        "",
        "## Artifact links",
        "",
        *_list_lines("Artifacts", [str(item.get("path", "")) for item in workspace.get("artifact_links", []) if isinstance(item, dict)], empty="No artifact links recorded."),
    ]
    return _redact_text("\n".join(lines).rstrip() + "\n")


def _write_journal(run_dir: Path, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing = _read_journal(run_dir)
    merged = _dedupe_events([*existing, *events])
    (run_dir / TASK_JOURNAL_JSONL).write_text("\n".join(json.dumps(event, ensure_ascii=False, sort_keys=True) for event in merged) + ("\n" if merged else ""), encoding="utf-8")
    return merged


def _read_journal(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / TASK_JOURNAL_JSONL
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _safe_run_dir(runs_dir: Path, run_id: str) -> Path:
    base = Path(runs_dir).resolve()
    target = (base / run_id).resolve()
    if base != target and base not in target.parents:
        raise ValueError("Run id escapes runs directory.")
    return target


def _safe_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return read_json(path)
    except (json.JSONDecodeError, OSError):
        return {}


def _read_events(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "events.jsonl"
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _loop_phase(run_dir: Path, record: dict[str, Any], slice_loop: dict[str, Any], completion_gate: dict[str, Any]) -> str:
    if (run_dir / "learning_summary.json").exists() or (run_dir / "retrospective.md").exists() or (run_dir / "final_report.md").exists() or record.get("status") == "completed":
        return "finish"
    if completion_gate:
        return "verify"
    if slice_loop or (run_dir / "codex").exists():
        return "implement"
    return "plan"


def _task_type(record: dict[str, Any]) -> str:
    text = f"{record.get('brief', '')} {record.get('domain_id', '')}".lower()
    if "dashboard" in text or "ui" in text or "页面" in text:
        return "dashboard_ui_change"
    if "bug" in text or "修复" in text:
        return "bugfix"
    if "domain" in text:
        return "domain_pack_change"
    return "feature_or_pipeline_change"


def _current_focus(record: dict[str, Any], slice_loop: dict[str, Any], completion_gate: dict[str, Any], blockers: list[str]) -> str:
    if blockers:
        return f"Resolve blocker: {blockers[0]}"
    current_slice = str(slice_loop.get("current_slice_id", ""))
    if current_slice:
        return f"Implement current slice `{current_slice}`."
    if completion_gate:
        return str(completion_gate.get("next_action") or completion_gate.get("summary") or "Verify implementation completion.")
    status = str(record.get("status", ""))
    if status == "completed":
        return "Run is completed; review finish artifacts and next release gates."
    if status:
        return f"Run status is `{status}`."
    return "Gather plan artifacts."


def _acceptance_criteria(run_dir: Path, coverage: dict[str, Any]) -> list[dict[str, str]]:
    criteria: list[dict[str, str]] = []
    for item in coverage.get("acceptance_criteria", []) if isinstance(coverage.get("acceptance_criteria"), list) else []:
        if isinstance(item, dict):
            criteria.append({"id": _redact_text(str(item.get("id", ""))), "description": _redact_text(str(item.get("description", "")))})
    if criteria:
        return criteria
    path = run_dir / "acceptance_criteria.md"
    if not path.exists():
        return []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.search(r"`([^`]+)`\s*(.*)", line)
        if match:
            criteria.append({"id": _redact_text(match.group(1)), "description": _redact_text(match.group(2).strip(" -"))})
    return criteria


def _slice_summary(coverage: dict[str, Any], slice_loop: dict[str, Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    if isinstance(slice_loop.get("slices"), list):
        for item in slice_loop.get("slices", []):
            if isinstance(item, dict):
                items.append(_slice_item(item))
    elif isinstance(coverage.get("slices"), list):
        for item in coverage.get("slices", []):
            if isinstance(item, dict):
                items.append(_slice_item(item))
    current_id = str(slice_loop.get("current_slice_id", ""))
    completed_ids = set(_string_list(slice_loop.get("completed_slice_ids")))
    pending_ids = set(_string_list(slice_loop.get("pending_slice_ids")))
    active = next((item for item in items if item.get("id") == current_id), None)
    completed = [item for item in items if item.get("id") in completed_ids or item.get("status") == "completed"]
    blocked = [item for item in items if item.get("status") in {"failed", "blocked"}]
    pending = [item for item in items if item not in completed and item not in blocked and item != active]
    if pending_ids:
        pending = [item for item in items if item.get("id") in pending_ids and item not in completed and item not in blocked]
    return {"active": active, "completed": completed, "pending": pending, "blocked": blocked}


def _slice_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _redact_text(str(item.get("id") or item.get("slice_id") or "")),
        "title": _redact_text(str(item.get("title", ""))),
        "status": _redact_text(str(item.get("status", ""))),
        "acceptance_criteria_ids": [_redact_text(value) for value in _string_list(item.get("acceptance_criteria_ids"))],
        "verification_commands": [_redact_text(value) for value in _string_list(item.get("verification_commands"))],
    }


def _gate_summary(record: dict[str, Any], completion_gate: dict[str, Any]) -> list[dict[str, str]]:
    gates: list[dict[str, str]] = []
    for item in record.get("gate_results", []) if isinstance(record.get("gate_results"), list) else []:
        if isinstance(item, dict):
            gates.append({"id": str(item.get("gate_id", "")), "status": str(item.get("status", "")), "reason": ", ".join(_string_list(item.get("missing_artifacts")))})
    if completion_gate:
        gates.append({"id": "implementation_completion", "status": str(completion_gate.get("status", "")), "reason": str(completion_gate.get("summary", ""))})
    return [_redact(gate) for gate in gates]


def _verification_commands(coverage: dict[str, Any], slice_loop: dict[str, Any], run_dir: Path) -> list[str]:
    commands: list[str] = []
    for source in (coverage.get("slices"), slice_loop.get("slices")):
        if not isinstance(source, list):
            continue
        for item in source:
            if isinstance(item, dict):
                commands.extend(_string_list(item.get("verification_commands")))
    tdd_plan = _safe_json(run_dir / "planning" / "tdd_plan.json")
    if isinstance(tdd_plan, dict):
        for item in tdd_plan.get("test_cases", []) if isinstance(tdd_plan.get("test_cases"), list) else []:
            if isinstance(item, dict):
                commands.extend(_string_list(item.get("verification_command")))
    return _dedupe([_redact_text(item) for item in commands if item.strip()])


def _artifact_warnings(run_dir: Path, paths: list[str]) -> list[str]:
    return [f"missing_artifact:{path}" for path in paths if not (run_dir / path).exists()]


def _artifact_links(run_dir: Path) -> list[dict[str, str]]:
    candidates = [
        "task_workspace.md",
        "task_journal.md",
        "requirements/brief_analysis.json",
        "requirements/capability_boundary.md",
        "planning/acceptance_coverage_matrix.md",
        "planning/tdd_plan.md",
        "codex/slice_loop_state.json",
        "implementation_completion_gate.md",
        "review_report.md",
        "test_report.md",
        "final_report.md",
        "retrospective.md",
        "learning_summary.json",
    ]
    return [{"path": path, "exists": (run_dir / path).exists()} for path in candidates if (run_dir / path).exists()]


def _next_actions(record: dict[str, Any], slice_loop: dict[str, Any], completion_gate: dict[str, Any], blockers: list[str]) -> list[str]:
    if blockers:
        return [f"Resolve blocker: {blockers[0]}"]
    if isinstance(slice_loop.get("next_action"), str) and slice_loop.get("next_action"):
        return [_redact_text(str(slice_loop.get("next_action")))]
    if isinstance(completion_gate.get("next_action"), str) and completion_gate.get("next_action"):
        return [_redact_text(str(completion_gate.get("next_action")))]
    if record.get("status") == "completed":
        return ["Review finish artifacts and decide whether to proceed to release readiness."]
    return ["Continue the current AI-Team run."]


def _extract_blockers(record: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for agent in record.get("agent_runs", []) if isinstance(record.get("agent_runs"), list) else []:
        if isinstance(agent, dict) and str(agent.get("status", "")) == "failed":
            blockers.append(str(agent.get("message") or f"agent_failed:{agent.get('agent_id', '')}"))
        if isinstance(agent, dict):
            blockers.extend(_string_list(agent.get("risk_events")))
    return _dedupe(blockers)


def _journal_event(
    run_id: str,
    timestamp: str,
    phase: str,
    event: str,
    status: str,
    summary: str,
    evidence: list[str],
    blockers: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "timestamp": timestamp,
        "loop_phase": phase,
        "event": event,
        "status": _redact_text(status),
        "summary": _redact_text(summary),
        "evidence": [_redact_text(item) for item in evidence],
        "blockers": [_redact_text(item) for item in blockers],
        "warnings": [_redact_text(item) for item in warnings],
    }


def _event_time(event: dict[str, Any]) -> str:
    return str(event.get("created_at") or event.get("timestamp") or now_iso())


def _mtime_or_now(path: Path) -> str:
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return now_iso()


def _phase_for_event(event: str, workspace: dict[str, Any]) -> str:
    if event in {"run_started", "complex_task_artifacts_generated", "plan_artifacts_ready", "requirement_quality_gate_passed", "planning_quality_gate_passed"}:
        return "plan"
    if event in {"agent_started", "agent_completed", "slice_loop_observed"}:
        return "implement"
    if event in {"before_coding_gate_passed", "before_coding_gate_blocked", "before_publish_gate_passed", "before_publish_gate_blocked", "verify_completed"}:
        return "verify"
    if event in {"run_completed", "finish_learning_ready"}:
        return "finish"
    if event == "run_failed":
        return str(workspace.get("loop_phase", "plan"))
    return str(workspace.get("loop_phase", "plan"))


def _event_summary(name: str, event: dict[str, Any]) -> str:
    if name == "run_started":
        return "Run started."
    if name == "run_completed":
        return "Run completed."
    if name == "run_failed":
        return f"Run failed: {event.get('reason', '')}."
    if name == "agent_started":
        return f"Agent `{event.get('agent_id', '')}` started."
    if name == "agent_completed":
        return f"Agent `{event.get('agent_id', '')}` completed with status `{event.get('status', '')}`."
    if name == "risk_event":
        return f"Risk event: {event.get('risk_event', '')}."
    if name == "complex_task_artifacts_generated":
        return f"Complex task artifacts generated with status `{event.get('status', '')}`."
    if name == "memory_recall_generated":
        return f"Memory recall generated with {event.get('match_count', 0)} matches."
    return name


def _event_evidence(event: dict[str, Any]) -> list[str]:
    evidence: list[str] = []
    for key in ("agent_id", "gate_id", "output_paths"):
        value = event.get(key)
        if isinstance(value, list):
            evidence.extend(str(item) for item in value)
        elif value:
            evidence.append(str(value))
    return evidence


def _dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for event in events:
        key = (str(event.get("loop_phase", "")), str(event.get("event", "")), str(event.get("status", "")), "|".join(_string_list(event.get("evidence"))))
        if key in seen:
            continue
        seen.add(key)
        result.append(event)
    result.sort(key=lambda item: str(item.get("timestamp", "")))
    return result


def _allowed_paths(workspace: dict[str, Any]) -> list[str]:
    boundary = workspace.get("capability_boundary") if isinstance(workspace.get("capability_boundary"), dict) else {}
    paths: list[str] = []
    paths.extend(_string_list(boundary.get("allowed_paths")))
    for item in boundary.get("required_new_capabilities", []) if isinstance(boundary.get("required_new_capabilities"), list) else []:
        if isinstance(item, dict):
            paths.extend(_string_list(item.get("evidence")))
    return _dedupe(paths)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _list_lines(label: str, items: Any, *, empty: str = "暂无。") -> list[str]:
    values = _string_list(items)
    if not values:
        return [f"- {empty}"] if empty else []
    return [f"- {label}: `{item}`" for item in values]


def _redact(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {str(key): _redact(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_redact(item) for item in payload]
    if isinstance(payload, str):
        return _redact_text(payload)
    return payload


def _redact_text(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("<redacted>", redacted)
    return redacted
