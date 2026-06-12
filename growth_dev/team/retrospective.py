from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..utils import now_iso, read_json, write_json
from .models import TeamRunRecord
from .quality import evaluate_run_quality


ACTIVE_SKILL_IDS = {
    "using_agent_skills",
    "spec_driven_development",
    "context_engineering",
    "planning_and_task_breakdown",
    "incremental_implementation",
    "test_driven_development",
    "debugging_and_error_recovery",
    "code_review_and_quality",
}

RETROSPECTIVE_SECTIONS = (
    "本次任务类型",
    "结果结论",
    "关键证据",
    "成功因素 / 失败原因",
    "产物质量观察",
    "AI 实现观察",
    "Review/Test 观察",
    "推荐 Project Skills",
    "下次上下文策略",
    "可沉淀经验",
)

SECRET_REPLACEMENTS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{6,}"), "<redacted-secret>"),
    (re.compile(r"(?i)(AICODEMIRROR_KEY\s*[:=]\s*)[^\s,;'\"\n]+"), r"\1<redacted>"),
    (re.compile(r"(?i)((api[_-]?key|secret|token|password)\s*[:=]\s*)[^\s,;'\"\n]+"), r"\1<redacted>"),
]


def generate_run_retrospective(run_id: str, *, runs_dir: Path = Path("runs")) -> dict[str, Any]:
    run_dir = _safe_run_dir(Path(runs_dir), run_id)
    record_path = run_dir / "team_run_record.json"
    if not record_path.exists():
        raise FileNotFoundError(f"team_run_record.json not found: {record_path}")
    record = TeamRunRecord.from_dict(read_json(record_path))
    learning = _learning_summary(record, run_dir)
    suggestions = _finish_learning_suggestions(learning, run_dir)
    markdown = _retrospective_markdown(learning, suggestions)
    write_json(run_dir / "learning_summary.json", learning)
    write_json(run_dir / "finish_learning_suggestions.json", suggestions)
    (run_dir / "finish_learning_suggestions.md").write_text(_finish_learning_suggestions_markdown(suggestions), encoding="utf-8")
    (run_dir / "retrospective.md").write_text(markdown, encoding="utf-8")
    return {
        "run_id": record.run_id,
        "artifacts": {
            "retrospective": "retrospective.md",
            "learning_summary": "learning_summary.json",
            "finish_learning_suggestions": "finish_learning_suggestions.md",
            "finish_learning_suggestions_json": "finish_learning_suggestions.json",
        },
        "learning_summary": learning,
        "finish_learning_suggestions": suggestions,
    }


def generate_recent_run_retrospectives(*, runs_dir: Path = Path("runs"), limit: int = 50) -> dict[str, Any]:
    selected = _discover_runs(Path(runs_dir))[: max(limit, 0)]
    results = [generate_run_retrospective(run_id, runs_dir=Path(runs_dir)) for run_id in selected]
    return {
        "run_ids": [result["run_id"] for result in results],
        "artifacts": [result["artifacts"] for result in results],
    }


def ensure_run_retrospective(run_id: str, *, runs_dir: Path = Path("runs")) -> dict[str, Any]:
    run_dir = _safe_run_dir(Path(runs_dir), run_id)
    if (run_dir / "retrospective.md").exists() and (run_dir / "learning_summary.json").exists() and (run_dir / "finish_learning_suggestions.json").exists():
        learning = read_json(run_dir / "learning_summary.json")
        suggestions = read_json(run_dir / "finish_learning_suggestions.json")
        return {
            "run_id": run_id,
            "artifacts": {
                "retrospective": "retrospective.md",
                "learning_summary": "learning_summary.json",
                "finish_learning_suggestions": "finish_learning_suggestions.md",
                "finish_learning_suggestions_json": "finish_learning_suggestions.json",
            },
            "learning_summary": learning if isinstance(learning, dict) else {},
            "finish_learning_suggestions": suggestions if isinstance(suggestions, dict) else {},
        }
    return generate_run_retrospective(run_id, runs_dir=runs_dir)


def _learning_summary(record: TeamRunRecord, run_dir: Path) -> dict[str, Any]:
    implementation = _implementation_trace(run_dir)
    acceptance = _safe_json(run_dir / "acceptance" / "status.json")
    changed_files = _changed_files(record, implementation)
    risk_events = _risk_events(record, implementation)
    blockers = _blockers(record, implementation)
    quality = evaluate_run_quality(record, run_dir).to_dict()
    outcome = _outcome(record, acceptance, blockers)
    failure_modes = _failure_modes(record, risk_events, blockers, outcome)
    recommended_skills = _recommended_skills(record, outcome, failure_modes)
    source_artifacts = _source_artifacts(run_dir)
    task_type = _task_type(record, changed_files)

    return _redact_payload(
        {
            "schema_version": 1,
            "run_id": record.run_id,
            "domain_id": record.domain_id,
            "status": record.status,
            "task_type": task_type,
            "outcome": outcome,
            "quality_findings": {
                "status": quality.get("status", "unknown"),
                "score": quality.get("score"),
                "summary": quality.get("summary", ""),
                "failed_checks": [
                    {
                        "id": check.get("id", ""),
                        "artifact": check.get("artifact", ""),
                        "detail": check.get("detail", ""),
                    }
                    for check in quality.get("checks", [])
                    if isinstance(check, dict) and check.get("status") == "failed"
                ][:6],
            },
            "implementation_findings": {
                "changed_files": changed_files,
                "tests_run": _tests_run(implementation),
                "blockers": blockers,
                "risk_events": risk_events,
                "exit_code": ((implementation.get("evidence") or {}).get("exit_code") if isinstance(implementation.get("evidence"), dict) else None),
            },
            "review_test_findings": {
                "review_summary": _summarize_text(run_dir / "review_report.md"),
                "test_summary": _summarize_text(run_dir / "test_report.md"),
                "acceptance_status": str(acceptance.get("status", "not_started")) if isinstance(acceptance, dict) else "not_started",
                "applied": bool(acceptance.get("applied")) if isinstance(acceptance, dict) else False,
            },
            "failure_modes": failure_modes,
            "recommended_skills": recommended_skills,
            "reusable_context": _reusable_context(record, source_artifacts, changed_files),
            "avoid_context": _avoid_context(record, failure_modes),
            "next_time_checklist": _next_time_checklist(outcome, recommended_skills, failure_modes),
            "source_artifacts": source_artifacts,
        }
    )


def _retrospective_markdown(learning: dict[str, Any], suggestions: dict[str, Any] | None = None) -> str:
    quality = learning.get("quality_findings") if isinstance(learning.get("quality_findings"), dict) else {}
    implementation = learning.get("implementation_findings") if isinstance(learning.get("implementation_findings"), dict) else {}
    review_test = learning.get("review_test_findings") if isinstance(learning.get("review_test_findings"), dict) else {}
    lines = [
        f"# Run Retrospective: {learning.get('run_id', '')}",
        "",
        "## 本次任务类型",
        "",
        f"- `{learning.get('task_type', 'unknown')}`",
        f"- Domain: `{learning.get('domain_id', '')}`",
        "",
        "## 结果结论",
        "",
        f"- Status: `{learning.get('status', '')}`",
        f"- Outcome: `{learning.get('outcome', '')}`",
        "",
        "## 关键证据",
        "",
        *_list_lines("Changed files", implementation.get("changed_files", [])),
        *_list_lines("Source artifacts", learning.get("source_artifacts", [])),
        "",
        "## 成功因素 / 失败原因",
        "",
        *_list_lines("Failure modes", learning.get("failure_modes", []), empty="暂无失败模式。"),
        "",
        "## 产物质量观察",
        "",
        f"- {quality.get('summary', '暂无质量信息。')}",
        *_list_lines("Failed checks", [item.get("detail", "") for item in quality.get("failed_checks", []) if isinstance(item, dict)], empty="暂无失败质量检查。"),
        "",
        "## AI 实现观察",
        "",
        *_list_lines("Tests run", implementation.get("tests_run", []), empty="暂无实现阶段测试记录。"),
        *_list_lines("Blockers", implementation.get("blockers", []), empty="暂无实现阻塞。"),
        "",
        "## Review/Test 观察",
        "",
        f"- Review: {review_test.get('review_summary', '暂无 Review 摘要。') or '暂无 Review 摘要。'}",
        f"- Test: {review_test.get('test_summary', '暂无 Test 摘要。') or '暂无 Test 摘要。'}",
        f"- Acceptance: `{review_test.get('acceptance_status', 'not_started')}`",
        "",
        "## 推荐 Project Skills",
        "",
        *_list_lines("Skills", learning.get("recommended_skills", [])),
        "",
        "## 下次上下文策略",
        "",
        *_list_lines("Reusable context", learning.get("reusable_context", []), empty="暂无可复用上下文。"),
        *_list_lines("Avoid context", learning.get("avoid_context", []), empty="暂无需要排除的上下文。"),
        "",
        "## 可沉淀经验",
        "",
        *_list_lines("Checklist", learning.get("next_time_checklist", [])),
        "",
        "## Capability / Skill Update Suggestions",
        "",
        *_list_lines("Capability updates", (suggestions or {}).get("capability_update_suggestions", []), empty="暂无能力边界更新建议。"),
        *_list_lines("Skill updates", (suggestions or {}).get("skill_update_suggestions", []), empty="暂无 Project Skill 更新建议。"),
        *_list_lines("Failure classification", (suggestions or {}).get("failure_classification_suggestions", []), empty="暂无失败分类更新建议。"),
    ]
    return "\n".join(lines).rstrip() + "\n"


def _finish_learning_suggestions(learning: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    boundary = _safe_json(run_dir / "requirements" / "capability_boundary.json")
    required_new = boundary.get("required_new_capabilities", []) if isinstance(boundary, dict) else []
    capability_updates: list[str] = []
    for item in required_new if isinstance(required_new, list) else []:
        if isinstance(item, dict):
            capability_id = str(item.get("id", "")).strip()
            summary = str(item.get("summary", "")).strip()
            if capability_id or summary:
                capability_updates.append(f"Review whether `{capability_id or summary}` should be promoted into domain capabilities.")
    if not capability_updates and learning.get("outcome") in {"accepted_and_verified", "completed_waiting_acceptance"}:
        domain_id = str(learning.get("domain_id", ""))
        if domain_id:
            capability_updates.append(f"Review `{domain_id}` domain capabilities if this run introduced reusable behavior.")

    skill_updates: list[str] = []
    for skill in learning.get("recommended_skills", []) if isinstance(learning.get("recommended_skills"), list) else []:
        skill_updates.append(f"Keep `{skill}` as a candidate hint for similar runs.")
    if learning.get("outcome") == "accepted_and_verified":
        skill_updates.append("Consider adding a skill hint only after the same pattern repeats across multiple accepted runs.")

    failure_updates: list[str] = []
    for mode in learning.get("failure_modes", []) if isinstance(learning.get("failure_modes"), list) else []:
        failure_updates.append(f"Consider a failure classification rule for `{mode}` if it recurs.")
    if not failure_updates:
        failure_updates.append("No new failure classification rule suggested from this run.")

    return _redact_payload(
        {
            "schema_version": 1,
            "run_id": learning.get("run_id", ""),
            "generated_at": now_iso(),
            "policy": "Suggestions only; do not automatically edit domains or Project Skills.",
            "capability_update_suggestions": _dedupe(capability_updates),
            "skill_update_suggestions": _dedupe(skill_updates),
            "failure_classification_suggestions": _dedupe(failure_updates),
            "source_artifacts": [path for path in ("requirements/capability_boundary.json", "learning_summary.json", "retrospective.md") if (run_dir / path).exists()],
        }
    )


def _finish_learning_suggestions_markdown(suggestions: dict[str, Any]) -> str:
    lines = [
        f"# Capability / Skill Update Suggestions: {suggestions.get('run_id', '')}",
        "",
        f"- Policy: {suggestions.get('policy', '')}",
        "",
        "## Capability Updates",
        "",
        *_list_lines("Suggestions", suggestions.get("capability_update_suggestions", []), empty="暂无能力边界更新建议。"),
        "",
        "## Skill Updates",
        "",
        *_list_lines("Suggestions", suggestions.get("skill_update_suggestions", []), empty="暂无 Project Skill 更新建议。"),
        "",
        "## Failure Classification",
        "",
        *_list_lines("Suggestions", suggestions.get("failure_classification_suggestions", []), empty="暂无失败分类更新建议。"),
        "",
        "## Source Artifacts",
        "",
        *_list_lines("Sources", suggestions.get("source_artifacts", []), empty="暂无来源产物。"),
    ]
    return "\n".join(lines).rstrip() + "\n"


def _safe_run_dir(runs_dir: Path, run_id: str) -> Path:
    base = Path(runs_dir).resolve()
    target = (base / run_id).resolve()
    if base != target and base not in target.parents:
        raise ValueError("Run id escapes runs directory.")
    return target


def _discover_runs(runs_dir: Path) -> list[str]:
    if not runs_dir.exists():
        return []
    records: list[tuple[str, str]] = []
    for run_dir in runs_dir.iterdir():
        record_path = run_dir / "team_run_record.json"
        if not record_path.exists():
            continue
        payload = _safe_json(record_path)
        if not isinstance(payload, dict):
            continue
        recency = str(payload.get("started_at") or payload.get("finished_at") or run_dir.stat().st_mtime_ns)
        records.append((recency, run_dir.name))
    records.sort(reverse=True)
    return [run_id for _, run_id in records]


def _implementation_trace(run_dir: Path) -> dict[str, Any]:
    payload = _safe_json(run_dir / "codex" / "implementation_trace.json")
    return payload if isinstance(payload, dict) else {}


def _safe_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {}


def _changed_files(record: TeamRunRecord, implementation: dict[str, Any]) -> list[str]:
    files: list[str] = []
    evidence = implementation.get("evidence") if isinstance(implementation.get("evidence"), dict) else {}
    if isinstance(evidence.get("changed_files"), list):
        files.extend(str(item) for item in evidence.get("changed_files", []))
    for agent_run in record.agent_runs:
        for key in ("files_changed", "changed_files"):
            value = agent_run.metadata.get(key)
            if isinstance(value, list):
                files.extend(str(item) for item in value)
    return _dedupe([_redact_text(item) for item in files])


def _tests_run(implementation: dict[str, Any]) -> list[str]:
    evidence = implementation.get("evidence") if isinstance(implementation.get("evidence"), dict) else {}
    tests = evidence.get("tests_run") or evidence.get("verification_commands") or []
    return [_redact_text(str(item)) for item in tests if str(item).strip()] if isinstance(tests, list) else []


def _risk_events(record: TeamRunRecord, implementation: dict[str, Any]) -> list[str]:
    events = list(record.risk_events)
    for agent_run in record.agent_runs:
        events.extend(agent_run.risk_events)
    value = implementation.get("risk_events")
    if isinstance(value, list):
        events.extend(str(item) for item in value)
    return _dedupe([_redact_text(item) for item in events])


def _blockers(record: TeamRunRecord, implementation: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    value = implementation.get("blockers")
    if isinstance(value, list):
        blockers.extend(str(item) for item in value)
    for agent_run in record.agent_runs:
        if agent_run.status == "failed":
            blockers.append(str(agent_run.metadata.get("failure_category") or agent_run.message or f"agent_failed:{agent_run.agent_id}"))
    return _dedupe([_redact_text(item) for item in blockers if item])


def _outcome(record: TeamRunRecord, acceptance: Any, blockers: list[str]) -> str:
    if record.status in {"running", "starting", "pending"}:
        return "incomplete_observation"
    if record.status == "failed" or blockers:
        return "failed_needs_recovery"
    if isinstance(acceptance, dict) and acceptance.get("status") == "completed":
        return "accepted_and_verified"
    if record.status == "completed":
        return "completed_waiting_acceptance"
    return "unknown"


def _failure_modes(record: TeamRunRecord, risk_events: list[str], blockers: list[str], outcome: str) -> list[str]:
    modes = _dedupe([*risk_events, *blockers])
    if outcome == "incomplete_observation":
        modes.append("incomplete_observation")
    if record.status == "failed" and not modes:
        modes.append("run_failed")
    return _dedupe(modes)


def _recommended_skills(record: TeamRunRecord, outcome: str, failure_modes: list[str]) -> list[str]:
    skills = ["context_engineering", "code_review_and_quality"]
    if record.status in {"running", "starting", "pending"}:
        skills.insert(0, "using_agent_skills")
    if failure_modes or outcome == "failed_needs_recovery":
        skills.append("debugging_and_error_recovery")
    if record.status == "completed":
        skills.append("test_driven_development")
    return [skill for skill in _dedupe(skills) if skill in ACTIVE_SKILL_IDS]


def _reusable_context(record: TeamRunRecord, source_artifacts: list[str], changed_files: list[str]) -> list[str]:
    context = [artifact for artifact in source_artifacts if artifact in {"prd.md", "tech_spec.md", "ui_spec.md", "eval.md", "retrospective.md"}]
    context.extend(changed_files[:5])
    if record.domain_id:
        context.append(f"domains/{record.domain_id}/")
    return _dedupe(context)


def _avoid_context(record: TeamRunRecord, failure_modes: list[str]) -> list[str]:
    avoid = ["raw stdout/stderr", "full diff", "raw coding prompt", ".env/provider secrets"]
    if "context_leakage" in " ".join(failure_modes):
        avoid.append("stale domain artifacts")
    if record.domain_id:
        avoid.append(f"unrelated domains outside {record.domain_id}")
    return _dedupe(avoid)


def _next_time_checklist(outcome: str, recommended_skills: list[str], failure_modes: list[str]) -> list[str]:
    checklist = [
        "先确认 brief、PRD、Tech/UI/Eval 是否同题。",
        "只给 coding agent 注入本次任务必要上下文。",
        "采纳前检查 Review、Test、Diff 和 Acceptance 状态。",
    ]
    if "debugging_and_error_recovery" in recommended_skills or failure_modes:
        checklist.insert(0, "失败或阻塞时先分类，再生成最小修复计划。")
    if outcome == "incomplete_observation":
        checklist.insert(0, "等待 run 终态后重新生成复盘。")
    return checklist


def _source_artifacts(run_dir: Path) -> list[str]:
    candidates = [
        "team_run_record.json",
        "events.jsonl",
        "prd.md",
        "tech_spec.md",
        "ui_spec.md",
        "eval.md",
        "codex/implementation_trace.json",
        "review_report.md",
        "test_report.md",
        "final_report.md",
        "acceptance/status.json",
    ]
    return [path for path in candidates if (run_dir / path).exists()]


def _task_type(record: TeamRunRecord, changed_files: list[str]) -> str:
    text = f"{record.brief} {' '.join(changed_files)}".lower()
    if "dashboard" in text or "ui" in text or "页面" in text:
        return "dashboard_ui_change"
    if "bug" in text or "修复" in text or "失败" in text:
        return "bugfix"
    if "domain" in text:
        return "domain_pack_change"
    return "feature_or_pipeline_change"


def _summarize_text(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    lines: list[str] = []
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(_redact_text(line))
        if len(lines) >= 2:
            break
    summary = " ".join(lines)
    return summary[:177].rstrip() + "..." if len(summary) > 180 else summary


def _list_lines(label: str, values: Any, *, empty: str = "暂无记录。") -> list[str]:
    if not isinstance(values, list) or not values:
        return [f"- {empty}"]
    return [f"- {label}: `{_redact_text(str(value))}`" for value in values]


def _redact_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {str(key): _redact_payload(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_redact_payload(item) for item in payload]
    if isinstance(payload, str):
        return _redact_text(payload)
    return payload


def _redact_text(value: str) -> str:
    redacted = str(value)
    for pattern, replacement in SECRET_REPLACEMENTS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
