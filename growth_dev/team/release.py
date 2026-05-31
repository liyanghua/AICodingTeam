from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from ..utils import ensure_dir, now_iso, read_json, write_json
from .models import TeamRunRecord
from .quality import evaluate_run_quality, summarize_run_health


READINESS_JSON = "release_readiness.json"
READINESS_MD = "release_readiness.md"
PR_DRAFT_MD = "pr_draft.md"
STAGING_READINESS_JSON = "staging_readiness.json"
STAGING_READINESS_MD = "staging_readiness.md"

SECRET_REPLACEMENTS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{6,}"), "<redacted-secret>"),
    (re.compile(r"(?i)(AICODEMIRROR_KEY\s*[:=]\s*)[^\s,;'\"]+"), r"\1<redacted>"),
    (re.compile(r"(?i)((api[_-]?key|secret|token|password)\s*[:=]\s*)[^\s,;'\"]+"), r"\1<redacted>"),
    (re.compile(r"\.env"), "<env-file>"),
]


def generate_release_readiness(
    run_id: str,
    *,
    runs_dir: Path = Path("runs"),
    repo_root: Path = Path("."),
) -> dict[str, Any]:
    runs_dir = Path(runs_dir)
    repo_root = Path(repo_root)
    run_dir = runs_dir / run_id
    record_path = run_dir / "team_run_record.json"
    if not record_path.exists():
        raise FileNotFoundError(f"team_run_record.json not found: {record_path}")

    record = TeamRunRecord.from_dict(read_json(record_path))
    acceptance = _read_json(run_dir / "acceptance" / "status.json")
    trace = _read_json(run_dir / "codex" / "implementation_trace.json")
    diff_summary = _parse_diff_summary(_read_text(run_dir / "codex" / "diff.patch"))
    expected_changed_files = _expected_changed_files(record, trace, diff_summary)
    working_tree = _working_tree_summary(repo_root, expected_changed_files)
    quality = evaluate_run_quality(record, run_dir).to_dict()
    health = summarize_run_health(record, run_dir).to_dict()
    ci_status = _read_json(run_dir / "ci_status.json")

    gates: list[dict[str, Any]] = []
    blockers: list[str] = []
    warnings: list[str] = []

    _add_run_status_gate(record, gates, blockers)
    _add_acceptance_gate(acceptance, gates, blockers)
    _add_domain_gate_results(record, gates, blockers)
    _add_review_test_gates(run_dir, gates, blockers)
    _add_risk_gates(record, trace, gates, blockers)
    _add_change_evidence_gate(expected_changed_files, diff_summary, gates, blockers)
    _add_working_tree_gate(working_tree, gates, blockers, warnings)
    _add_ci_status_gate(ci_status, gates, blockers, warnings)
    _add_quality_warning(quality, gates, warnings)
    _add_health_warnings(health, gates, warnings)

    tests_run = _tests_run(acceptance, trace)
    review_status = _report_status(run_dir / "review_report.md")
    acceptance_status = str(acceptance.get("status", "not_started"))
    pr_title = _pr_title(record)
    pr_body = _pr_body(
        record=record,
        decision="blocked" if blockers else "ready_with_warnings" if warnings else "ready_for_pr_ci",
        changed_files=expected_changed_files,
        tests_run=tests_run,
        blockers=blockers,
        warnings=warnings,
        run_dir=run_dir,
    )
    if _draft_is_short(record, expected_changed_files):
        warnings.append("PR draft 业务背景较短，进入 PR 前建议人工补充背景。")

    release_decision = "blocked" if blockers else "ready_with_warnings" if warnings else "ready_for_pr_ci"
    summary = _decision_summary(release_decision, blockers, warnings)
    pr_body = _pr_body(
        record=record,
        decision=release_decision,
        changed_files=expected_changed_files,
        tests_run=tests_run,
        blockers=blockers,
        warnings=warnings,
        run_dir=run_dir,
    )
    pr_draft = {"title": pr_title, "body": pr_body}
    result = {
        "schema_version": 1,
        "run_id": record.run_id,
        "generated_at": now_iso(),
        "release_decision": release_decision,
        "summary": summary,
        "gates": gates,
        "evidence": {
            "changed_files": expected_changed_files,
            "tests_run": tests_run,
            "review_status": review_status,
            "acceptance_status": acceptance_status,
            "ci_status": str(ci_status.get("status", "not_started")) if ci_status else "",
            "ci_summary": str(ci_status.get("summary", "")) if ci_status else "",
            "ci_checks": ci_status.get("checks", []) if isinstance(ci_status.get("checks"), list) else [],
            "working_tree": working_tree,
        },
        "pr_draft": pr_draft,
        "blockers": blockers,
        "warnings": warnings,
        "next_actions": _next_actions(record.run_id, release_decision),
    }
    result = _redact(result)
    _write_artifacts(run_dir, result)
    return result


def format_release_readiness(result: dict[str, Any]) -> str:
    lines = [
        f"Run: {result.get('run_id', '')}",
        f"Decision: {result.get('release_decision', '')}",
        f"Summary: {result.get('summary', '')}",
        "",
        "Gates:",
    ]
    for gate in result.get("gates", []):
        if not isinstance(gate, dict):
            continue
        lines.append(f"- {gate.get('id', '')}: {gate.get('status', '')} - {gate.get('reason', '')}")
    blockers = [str(item) for item in result.get("blockers", [])]
    warnings = [str(item) for item in result.get("warnings", [])]
    if blockers:
        lines.extend(["", "Blockers:", *[f"- {item}" for item in blockers]])
    if warnings:
        lines.extend(["", "Warnings:", *[f"- {item}" for item in warnings]])
    next_actions = [str(item) for item in result.get("next_actions", [])]
    if next_actions:
        lines.extend(["", "Next actions:", *[f"- {item}" for item in next_actions]])
    return "\n".join(lines).rstrip() + "\n"


def generate_staging_readiness(
    run_id: str,
    *,
    runs_dir: Path = Path("runs"),
) -> dict[str, Any]:
    runs_dir = Path(runs_dir)
    run_dir = runs_dir / run_id
    record_path = run_dir / "team_run_record.json"
    if not record_path.exists():
        raise FileNotFoundError(f"team_run_record.json not found: {record_path}")

    record = TeamRunRecord.from_dict(read_json(record_path))
    acceptance = _read_json(run_dir / "acceptance" / "status.json")
    release = _read_json(run_dir / READINESS_JSON)
    github_pr = _read_json(run_dir / "github_pr.json")
    ci_status = _read_json(run_dir / "ci_status.json")
    trace = _read_json(run_dir / "codex" / "implementation_trace.json")
    diff_summary = _parse_diff_summary(_read_text(run_dir / "codex" / "diff.patch"))
    changed_files = _expected_changed_files(record, trace, diff_summary)

    gates: list[dict[str, Any]] = []
    blockers: list[str] = []
    warnings: list[str] = []

    _add_staging_acceptance_gate(acceptance, gates, blockers)
    _add_staging_release_gate(release, gates, blockers, warnings)
    _add_staging_pr_gate(github_pr, gates, blockers)
    _add_staging_ci_gate(ci_status, gates, blockers, warnings)
    _add_staging_risk_gate(record, trace, ci_status, gates, blockers)

    if blockers:
        decision = "blocked"
    elif any(gate.get("id") == "ci_passed" and gate.get("status") == "warning" for gate in gates):
        decision = "waiting_for_ci"
    else:
        decision = "ready_for_staging"

    result = {
        "schema_version": 1,
        "run_id": record.run_id,
        "generated_at": now_iso(),
        "staging_decision": decision,
        "summary": _staging_summary(decision, blockers, warnings),
        "gates": gates,
        "evidence": {
            "release_decision": str(release.get("release_decision", "")),
            "pr_url": _pr_url(github_pr),
            "ci_status": str(ci_status.get("status", "not_started")) if ci_status else "not_started",
            "ci_summary": str(ci_status.get("summary", "")) if ci_status else "",
            "checks": ci_status.get("checks", []) if isinstance(ci_status.get("checks"), list) else [],
            "acceptance_status": str(acceptance.get("status", "not_started")),
            "changed_files": changed_files,
        },
        "blockers": _dedupe(blockers),
        "warnings": _dedupe(warnings),
        "next_actions": _staging_next_actions(record.run_id, decision),
    }
    result = _redact(result)
    _write_staging_artifacts(run_dir, result)
    return result


def format_staging_readiness(result: dict[str, Any]) -> str:
    lines = [
        f"Run: {result.get('run_id', '')}",
        f"Decision: {result.get('staging_decision', '')}",
        f"Summary: {result.get('summary', '')}",
        "",
        "Gates:",
    ]
    for gate in result.get("gates", []):
        if isinstance(gate, dict):
            lines.append(f"- {gate.get('id', '')}: {gate.get('status', '')} - {gate.get('reason', '')}")
    blockers = [str(item) for item in result.get("blockers", [])]
    warnings = [str(item) for item in result.get("warnings", [])]
    if blockers:
        lines.extend(["", "Blockers:", *[f"- {item}" for item in blockers]])
    if warnings:
        lines.extend(["", "Warnings:", *[f"- {item}" for item in warnings]])
    next_actions = [str(item) for item in result.get("next_actions", [])]
    if next_actions:
        lines.extend(["", "Next actions:", *[f"- {item}" for item in next_actions]])
    return "\n".join(lines).rstrip() + "\n"


def _write_artifacts(run_dir: Path, result: dict[str, Any]) -> None:
    ensure_dir(run_dir)
    write_json(run_dir / READINESS_JSON, result)
    (run_dir / READINESS_MD).write_text(_readiness_markdown(result), encoding="utf-8")
    (run_dir / PR_DRAFT_MD).write_text(_pr_draft_markdown(result), encoding="utf-8")


def _write_staging_artifacts(run_dir: Path, result: dict[str, Any]) -> None:
    ensure_dir(run_dir)
    write_json(run_dir / STAGING_READINESS_JSON, result)
    (run_dir / STAGING_READINESS_MD).write_text(_staging_markdown(result), encoding="utf-8")


def _readiness_markdown(result: dict[str, Any]) -> str:
    evidence = result.get("evidence", {}) if isinstance(result.get("evidence"), dict) else {}
    working_tree = evidence.get("working_tree", {}) if isinstance(evidence.get("working_tree"), dict) else {}
    lines = [
        "# Release Readiness",
        "",
        f"- Run: `{result.get('run_id', '')}`",
        f"- Decision: `{result.get('release_decision', '')}`",
        f"- Summary: {result.get('summary', '')}",
        "",
        "## Gates",
        "",
        "| Gate | Status | Reason |",
        "| --- | --- | --- |",
    ]
    for gate in result.get("gates", []):
        if not isinstance(gate, dict):
            continue
        reason = str(gate.get("reason", "")).replace("|", "\\|")
        lines.append(f"| `{gate.get('id', '')}` | `{gate.get('status', '')}` | {reason} |")
    lines.extend(["", "## Evidence", ""])
    lines.append(f"- Changed files: {', '.join(f'`{item}`' for item in evidence.get('changed_files', []) or []) or 'none'}")
    lines.append(f"- Tests run: {', '.join(f'`{item}`' for item in evidence.get('tests_run', []) or []) or 'none'}")
    lines.append(f"- Review status: `{evidence.get('review_status', '')}`")
    lines.append(f"- Acceptance status: `{evidence.get('acceptance_status', '')}`")
    if evidence.get("ci_status"):
        lines.append(f"- CI status: `{evidence.get('ci_status', '')}`")
        lines.append(f"- CI summary: {evidence.get('ci_summary', '') or 'none'}")
    lines.append(f"- Tracked working tree files: {', '.join(f'`{item}`' for item in working_tree.get('tracked_changed_files', []) or []) or 'none'}")
    lines.extend(["", "## Blockers", ""])
    lines.extend([f"- {item}" for item in result.get("blockers", [])] or ["暂无硬阻塞。"])
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {item}" for item in result.get("warnings", [])] or ["暂无 warning。"])
    lines.extend(["", "## Next Actions", ""])
    lines.extend([f"- `{item}`" for item in result.get("next_actions", [])] or ["暂无下一步动作。"])
    lines.extend(["", "## PR Draft", "", "- Source: [pr_draft.md](pr_draft.md)"])
    return _redact_text("\n".join(lines).rstrip() + "\n")


def _pr_draft_markdown(result: dict[str, Any]) -> str:
    pr = result.get("pr_draft", {}) if isinstance(result.get("pr_draft"), dict) else {}
    title = str(pr.get("title", "")).strip()
    body = str(pr.get("body", "")).strip()
    return _redact_text(f"# PR Title\n\n{title}\n\n{body}\n").rstrip() + "\n"


def _staging_markdown(result: dict[str, Any]) -> str:
    evidence = result.get("evidence", {}) if isinstance(result.get("evidence"), dict) else {}
    lines = [
        "# Staging Readiness",
        "",
        f"- Run: `{result.get('run_id', '')}`",
        f"- Decision: `{result.get('staging_decision', '')}`",
        f"- Summary: {result.get('summary', '')}",
        "",
        "## Gates",
        "",
        "| Gate | Status | Reason |",
        "| --- | --- | --- |",
    ]
    for gate in result.get("gates", []):
        if not isinstance(gate, dict):
            continue
        reason = str(gate.get("reason", "")).replace("|", "\\|")
        lines.append(f"| `{gate.get('id', '')}` | `{gate.get('status', '')}` | {reason} |")
    lines.extend(["", "## Evidence", ""])
    lines.append(f"- Release decision: `{evidence.get('release_decision', '')}`")
    lines.append(f"- PR: {evidence.get('pr_url', '') or 'not created'}")
    lines.append(f"- CI status: `{evidence.get('ci_status', '')}`")
    lines.append(f"- CI summary: {evidence.get('ci_summary', '') or 'none'}")
    lines.append(f"- Acceptance status: `{evidence.get('acceptance_status', '')}`")
    lines.append(f"- Changed files: {', '.join(f'`{item}`' for item in evidence.get('changed_files', []) or []) or 'none'}")
    lines.extend(["", "## Blockers", ""])
    lines.extend([f"- {item}" for item in result.get("blockers", [])] or ["暂无硬阻塞。"])
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {item}" for item in result.get("warnings", [])] or ["暂无 warning。"])
    lines.extend(["", "## Next Actions", ""])
    lines.extend([f"- `{item}`" for item in result.get("next_actions", [])] or ["暂无下一步动作。"])
    return _redact_text("\n".join(lines).rstrip() + "\n")


def _add_run_status_gate(record: TeamRunRecord, gates: list[dict[str, Any]], blockers: list[str]) -> None:
    if record.status == "completed":
        gates.append(_gate("run_completed", "passed", "Run 已完成。", [record.status]))
        return
    reason = f"Run status is `{record.status}`, not `completed`."
    gates.append(_gate("run_completed", "blocked", reason, [record.status]))
    blockers.append(reason)


def _add_acceptance_gate(acceptance: dict[str, Any], gates: list[dict[str, Any]], blockers: list[str]) -> None:
    status = str(acceptance.get("status", "not_started"))
    applied = bool(acceptance.get("applied", False))
    test_step = _step_by_id(acceptance, "tests")
    test_exit = test_step.get("exit_code") if test_step else None
    if status == "completed" and applied and test_exit == 0:
        gates.append(_gate("acceptance_tests", "passed", "采纳已完成，且全量测试退出码为 0。", [f"acceptance.status={status}", "tests.exit_code=0"]))
        return
    reason = f"acceptance not ready: status={status}, applied={applied}, tests_exit_code={test_exit}"
    gates.append(_gate("acceptance_tests", "blocked", reason, [f"acceptance.status={status}", f"applied={applied}", f"tests.exit_code={test_exit}"]))
    blockers.append(reason)


def _add_domain_gate_results(record: TeamRunRecord, gates: list[dict[str, Any]], blockers: list[str]) -> None:
    required = {"before_coding", "before_publish"}
    seen = {gate.gate_id: gate for gate in record.gate_results}
    for gate_id in sorted(required):
        gate = seen.get(gate_id)
        if gate and gate.status == "passed":
            gates.append(_gate(gate_id, "passed", f"{gate_id} 已通过。", gate.required_artifacts))
            continue
        reason = f"{gate_id} gate failed or missing."
        if gate and gate.missing_artifacts:
            reason = f"{gate_id} gate failed, missing: {', '.join(gate.missing_artifacts)}"
        gates.append(_gate(gate_id, "blocked", reason, gate.missing_artifacts if gate else []))
        blockers.append(reason)


def _add_review_test_gates(run_dir: Path, gates: list[dict[str, Any]], blockers: list[str]) -> None:
    for report_name, gate_id in (("review_report.md", "review_report"), ("test_report.md", "test_report")):
        path = run_dir / report_name
        if not path.exists():
            reason = f"{report_name} is missing."
            gates.append(_gate(gate_id, "blocked", reason, [report_name]))
            blockers.append(reason)
            continue
        status = _report_status(path)
        if status == "failed":
            reason = f"{report_name} explicitly reports failure."
            gates.append(_gate(gate_id, "blocked", reason, [report_name]))
            blockers.append(reason)
        else:
            gates.append(_gate(gate_id, "passed", f"{report_name} 已生成且无明确失败结论。", [report_name]))


def _add_risk_gates(record: TeamRunRecord, trace: dict[str, Any], gates: list[dict[str, Any]], blockers: list[str]) -> None:
    risks: list[str] = []
    risks.extend(record.risk_events)
    for agent in record.agent_runs:
        risks.extend(agent.risk_events)
    risks.extend(str(item) for item in trace.get("risk_events", []) if item)
    implementation_blockers = [str(item) for item in trace.get("blockers", []) if item]
    if risks or implementation_blockers:
        items = _dedupe([*risks, *implementation_blockers])
        gates.append(_gate("risk_and_blockers", "blocked", "存在未清零的风险或阻塞。", items))
        blockers.extend(items)
    else:
        gates.append(_gate("risk_and_blockers", "passed", "未发现未清零风险或实现阻塞。", []))


def _add_change_evidence_gate(
    changed_files: list[str],
    diff_summary: dict[str, Any],
    gates: list[dict[str, Any]],
    blockers: list[str],
) -> None:
    if changed_files or diff_summary.get("available"):
        evidence = changed_files or diff_summary.get("changed_files", [])
        gates.append(_gate("change_evidence", "passed", "存在可进入 PR 的代码变化证据。", evidence))
        return
    reason = "No changed files or diff evidence is available."
    gates.append(_gate("change_evidence", "blocked", reason, []))
    blockers.append(reason)


def _add_working_tree_gate(
    working_tree: dict[str, Any],
    gates: list[dict[str, Any]],
    blockers: list[str],
    warnings: list[str],
) -> None:
    unrelated = [str(item) for item in working_tree.get("unrelated_tracked_files", [])]
    if unrelated:
        reason = f"Tracked/staged changes include files outside expected run changes: {', '.join(unrelated)}"
        gates.append(_gate("working_tree_scope", "blocked", reason, unrelated))
        blockers.append(reason)
    elif working_tree.get("git_status_available") is False:
        reason = "当前 git status 不可用，发布前需人工确认工作区边界。"
        gates.append(_gate("working_tree_scope", "warning", reason, []))
        warnings.append(reason)
    else:
        gates.append(_gate("working_tree_scope", "passed", "当前 tracked/staged 变更未超出本次 run 预期文件。", working_tree.get("tracked_changed_files", [])))
    untracked = [str(item) for item in working_tree.get("untracked_files", [])]
    if untracked:
        warnings.append(f"存在未跟踪文件，未计入 PR 范围：{', '.join(untracked[:6])}")


def _add_ci_status_gate(
    ci_status: dict[str, Any],
    gates: list[dict[str, Any]],
    blockers: list[str],
    warnings: list[str],
) -> None:
    if not ci_status:
        return
    status = str(ci_status.get("status", "unknown"))
    summary = str(ci_status.get("summary", "")) or _ci_status_reason(status)
    checks = _ci_check_names(ci_status)
    if status == "passed":
        gates.append(_gate("ci_status", "passed", summary or "CI checks 已通过。", checks))
        return
    if status == "failed":
        reason = summary or "CI checks failed."
        ci_blockers = [str(item) for item in ci_status.get("blockers", []) if item]
        gates.append(_gate("ci_status", "blocked", reason, ci_blockers or checks))
        blockers.extend(ci_blockers or [f"CI 未通过：{reason}"])
        return
    reason = summary or _ci_status_reason(status)
    gates.append(_gate("ci_status", "warning", reason, checks))
    warnings.append(f"CI 尚未形成可放行结论：{reason}")


def _add_quality_warning(quality: dict[str, Any], gates: list[dict[str, Any]], warnings: list[str]) -> None:
    status = str(quality.get("status", "unknown"))
    if status == "passed":
        gates.append(_gate("artifact_quality", "passed", str(quality.get("summary", "文件质量通过。")), []))
    elif status == "needs_attention":
        warning = f"文件质量存在 needs_attention：{quality.get('summary', '')}"
        gates.append(_gate("artifact_quality", "warning", warning, []))
        warnings.append(warning)
    else:
        warning = "文件质量状态未知，进入 PR 前建议人工检查。"
        gates.append(_gate("artifact_quality", "warning", warning, []))
        warnings.append(warning)


def _add_health_warnings(health: dict[str, Any], gates: list[dict[str, Any]], warnings: list[str]) -> None:
    warning_groups = health.get("warning_groups", [])
    if isinstance(warning_groups, list) and warning_groups:
        summary = f"存在 {len(warning_groups)} 类 Codex/系统非阻塞提示。"
        gates.append(_gate("non_blocking_warnings", "warning", summary, [str(item.get("id", "")) for item in warning_groups if isinstance(item, dict)]))
        warnings.append(summary)
    else:
        gates.append(_gate("non_blocking_warnings", "passed", "未发现 Codex 非阻塞 warning。", []))


def _add_staging_acceptance_gate(acceptance: dict[str, Any], gates: list[dict[str, Any]], blockers: list[str]) -> None:
    status = str(acceptance.get("status", "not_started"))
    applied = bool(acceptance.get("applied", False))
    test_step = _step_by_id(acceptance, "tests")
    test_exit = test_step.get("exit_code") if test_step else None
    if status == "completed" and applied and test_exit == 0:
        gates.append(_gate("acceptance_completed", "passed", "采纳验收已完成，且全量测试通过。", [f"tests.exit_code={test_exit}"]))
        return
    reason = f"采纳验收未完成或测试未通过：status={status}, applied={applied}, tests_exit_code={test_exit}"
    gates.append(_gate("acceptance_completed", "blocked", reason, [status, str(applied), str(test_exit)]))
    blockers.append(reason)


def _add_staging_release_gate(
    release: dict[str, Any],
    gates: list[dict[str, Any]],
    blockers: list[str],
    warnings: list[str],
) -> None:
    decision = str(release.get("release_decision", ""))
    if not release:
        reason = "release_readiness.json is missing."
        gates.append(_gate("release_readiness", "blocked", reason, [READINESS_JSON]))
        blockers.append(reason)
        return
    if decision == "blocked":
        reason = "release_readiness is blocked."
        gates.append(_gate("release_readiness", "blocked", reason, release.get("blockers", []) if isinstance(release.get("blockers"), list) else []))
        blockers.append(reason)
        blockers.extend(str(item) for item in release.get("blockers", []) if item)
        return
    if decision == "ready_with_warnings":
        reason = "发布准备可进入 PR/CI，但仍有 warning。"
        gates.append(_gate("release_readiness", "warning", reason, release.get("warnings", []) if isinstance(release.get("warnings"), list) else []))
        warnings.append(reason)
        warnings.extend(str(item) for item in release.get("warnings", []) if item)
        return
    if decision == "ready_for_pr_ci":
        gates.append(_gate("release_readiness", "passed", "发布准备已通过。", [decision]))
        return
    reason = f"release_readiness decision is `{decision or 'missing'}`."
    gates.append(_gate("release_readiness", "blocked", reason, [decision]))
    blockers.append(reason)


def _add_staging_pr_gate(github_pr: dict[str, Any], gates: list[dict[str, Any]], blockers: list[str]) -> None:
    pr = github_pr.get("pr") if isinstance(github_pr.get("pr"), dict) else {}
    status = str(github_pr.get("status", "not_started"))
    url = str(pr.get("url", ""))
    if status == "created" and url:
        gates.append(_gate("draft_pr_created", "passed", "GitHub Draft PR 已创建。", [url]))
        return
    reason = "GitHub Draft PR has not been created."
    gates.append(_gate("draft_pr_created", "blocked", reason, [status]))
    blockers.append(reason)


def _add_staging_ci_gate(
    ci_status: dict[str, Any],
    gates: list[dict[str, Any]],
    blockers: list[str],
    warnings: list[str],
) -> None:
    status = str(ci_status.get("status", "not_started")) if ci_status else "not_started"
    summary = str(ci_status.get("summary", "")) if ci_status else ""
    checks = _ci_check_names(ci_status)
    if status == "passed":
        gates.append(_gate("ci_passed", "passed", summary or "CI checks 已通过。", checks))
        return
    if status == "failed":
        reason = summary or "CI checks failed."
        ci_blockers = [str(item) for item in ci_status.get("blockers", []) if item]
        gates.append(_gate("ci_passed", "blocked", reason, ci_blockers or checks))
        blockers.extend(ci_blockers or [f"CI 未通过：{reason}"])
        return
    reason = summary or _ci_status_reason(status)
    gates.append(_gate("ci_passed", "warning", reason, checks))
    warnings.append(f"CI 尚未通过：{reason}")


def _add_staging_risk_gate(
    record: TeamRunRecord,
    trace: dict[str, Any],
    ci_status: dict[str, Any],
    gates: list[dict[str, Any]],
    blockers: list[str],
) -> None:
    risks: list[str] = []
    risks.extend(record.risk_events)
    for agent in record.agent_runs:
        risks.extend(agent.risk_events)
    risks.extend(str(item) for item in trace.get("risk_events", []) if item)
    risks.extend(str(item) for item in trace.get("blockers", []) if item)
    risks.extend(str(item) for item in ci_status.get("blockers", []) if item)
    risks = _dedupe(risks)
    if risks:
        gates.append(_gate("risk_and_blockers", "blocked", "存在未清零风险或阻塞。", risks))
        blockers.extend(risks)
    else:
        gates.append(_gate("risk_and_blockers", "passed", "未发现未清零风险或阻塞。", []))


def _gate(gate_id: str, status: str, reason: str, evidence: list[Any]) -> dict[str, Any]:
    return {
        "id": gate_id,
        "status": status,
        "reason": _redact_text(reason),
        "evidence": [_redact_text(str(item)) for item in evidence if str(item)],
    }


def _expected_changed_files(record: TeamRunRecord, trace: dict[str, Any], diff_summary: dict[str, Any]) -> list[str]:
    files: list[str] = []
    evidence = trace.get("evidence") if isinstance(trace.get("evidence"), dict) else {}
    files.extend(str(item) for item in evidence.get("changed_files", []) if item)
    for agent in record.agent_runs:
        for key in ("files_changed", "changed_files"):
            value = agent.metadata.get(key)
            if isinstance(value, list):
                files.extend(str(item) for item in value if item)
    files.extend(str(item) for item in diff_summary.get("changed_files", []) if item)
    return _dedupe([_normalize_repo_path(item) for item in files if _normalize_repo_path(item)])


def _tests_run(acceptance: dict[str, Any], trace: dict[str, Any]) -> list[str]:
    commands: list[str] = []
    for step in acceptance.get("steps", []):
        if isinstance(step, dict) and step.get("command"):
            commands.append(str(step.get("command")))
    evidence = trace.get("evidence") if isinstance(trace.get("evidence"), dict) else {}
    for key in ("tests_run", "verification_commands"):
        value = evidence.get(key)
        if isinstance(value, list):
            commands.extend(str(item) for item in value if item)
    return _dedupe([_redact_text(item) for item in commands])


def _working_tree_summary(repo_root: Path, expected_files: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    expected = set(expected_files)
    if completed.returncode != 0:
        return {
            "git_status_available": False,
            "tracked_changed_files": [],
            "untracked_files": [],
            "unrelated_tracked_files": [],
            "status_error": _redact_text(completed.stderr or completed.stdout or "git status failed"),
        }
    tracked: list[str] = []
    untracked: list[str] = []
    for line in completed.stdout.splitlines():
        if not line:
            continue
        if line.startswith("?? "):
            untracked.append(_normalize_repo_path(line[3:]))
            continue
        path = _porcelain_path(line[3:])
        if path:
            tracked.append(_normalize_repo_path(path))
    tracked = _dedupe([item for item in tracked if item])
    untracked = _dedupe([item for item in untracked if item])
    unrelated = [path for path in tracked if path not in expected]
    return {
        "git_status_available": True,
        "tracked_changed_files": tracked,
        "untracked_files": untracked,
        "unrelated_tracked_files": unrelated,
    }


def _porcelain_path(value: str) -> str:
    path = value.strip()
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return path.strip('"')


def _report_status(path: Path) -> str:
    if not path.exists():
        return "missing"
    text = _read_text(path).lower()
    clean_markers = ("no blocking", "no blockers", "exit `0`", "exit 0", "ok", "passed", "通过")
    failure_markers = ("blocking bug", "blocker", "failed", "failure", "未通过", "失败", "exit `1`", "exit 1")
    if any(marker in text for marker in clean_markers):
        return "passed"
    if any(marker in text for marker in failure_markers):
        return "failed"
    return "passed"


def _step_by_id(acceptance: dict[str, Any], step_id: str) -> dict[str, Any]:
    for step in acceptance.get("steps", []):
        if isinstance(step, dict) and step.get("id") == step_id:
            return step
    return {}


def _pr_title(record: TeamRunRecord) -> str:
    brief = " ".join(record.brief.strip().split())
    if len(brief) > 54:
        brief = brief[:51].rstrip() + "..."
    prefix = record.domain_id or "agent-team"
    return _redact_text(f"{prefix}: {brief or record.run_id}")


def _pr_body(
    *,
    record: TeamRunRecord,
    decision: str,
    changed_files: list[str],
    tests_run: list[str],
    blockers: list[str],
    warnings: list[str],
    run_dir: Path,
) -> str:
    readiness_line = {
        "ready_for_pr_ci": "本地采纳验收、Review/Test 证据和变更边界均已通过，建议进入 PR/CI。",
        "ready_with_warnings": "核心验收通过，但存在 warning，建议人工快速复核后进入 PR/CI。",
        "blocked": "当前存在硬阻塞，不建议进入 PR/CI。",
    }.get(decision, "需要人工确认是否进入 PR/CI。")
    changed_lines = [f"- `{path}`" for path in changed_files] or ["- 暂无记录的代码变化文件。"]
    test_lines = [f"- `{cmd}`" for cmd in tests_run] or ["- 暂无测试命令记录。"]
    blocker_lines = [f"- {item}" for item in blockers] or ["- 暂无硬阻塞。"]
    warning_lines = [f"- {item}" for item in warnings] or ["- 暂无 warning。"]
    artifact_lines = [
        "- `release_readiness.md`",
        "- `review_report.md`",
        "- `test_report.md`",
        "- `final_report.md`",
        "- `codex/diff.patch`",
    ]
    body_lines = [
        "## Why This Should Enter PR/CI",
        "",
        readiness_line,
        "",
        f"业务需求：{record.brief or record.run_id}",
        "",
        "## What Changed",
        "",
        *changed_lines,
        "",
        "## Verification",
        "",
        *test_lines,
        "",
        "## Risk / Rollback",
        "",
        *blocker_lines,
        *warning_lines,
        "",
        "Rollback: revert the PR branch or discard the listed local file changes before merge.",
        "",
        "## Reviewer Checklist",
        "",
        "- [ ] 变更文件均属于本次 run 的预期范围。",
        "- [ ] Review/Test 报告无阻塞问题。",
        "- [ ] Dashboard 或业务 UI 变更已人工看过关键状态。",
        "- [ ] 若存在 warning，已判断不影响进入 PR/CI。",
        "",
        "## Local Artifacts",
        "",
        *artifact_lines,
        "",
        f"Run directory: `{run_dir}`",
    ]
    return _redact_text("\n".join(body_lines).rstrip() + "\n")


def _draft_is_short(record: TeamRunRecord, changed_files: list[str]) -> bool:
    return len(record.brief.strip()) < 12 or not changed_files


def _decision_summary(decision: str, blockers: list[str], warnings: list[str]) -> str:
    if decision == "ready_for_pr_ci":
        return "采纳验收、Review/Test 和变更边界均通过，值得进入 PR/CI。"
    if decision == "ready_with_warnings":
        return f"核心验收通过，但存在 {len(warnings)} 条 warning，建议人工复核后进入 PR/CI。"
    return f"存在 {len(blockers)} 个硬阻塞，暂不建议进入 PR/CI。"


def _next_actions(run_id: str, decision: str) -> list[str]:
    actions = [
        f"python3 -m growth_dev.cli team release readiness --run-id {run_id}",
        "python3 -m unittest discover -s tests -v",
    ]
    if decision == "blocked":
        actions.append("先处理 release_readiness.md 中的 blockers，再重新生成发布准备报告。")
    else:
        actions.append(f"python3 -m growth_dev.cli team pr draft --run-id {run_id} --base main --push")
        actions.append(f"python3 -m growth_dev.cli team pr status --run-id {run_id}")
    return actions


def _staging_summary(decision: str, blockers: list[str], warnings: list[str]) -> str:
    if decision == "ready_for_staging":
        return "采纳验收、发布准备、Draft PR 和 CI 均已通过，可以进入 staging 判断下一步。"
    if decision == "waiting_for_ci":
        return f"本地与 PR 条件基本齐备，但 CI 尚未形成通过结论，存在 {len(warnings)} 条等待项。"
    return f"存在 {len(blockers)} 个硬阻塞，暂不能进入 staging。"


def _staging_next_actions(run_id: str, decision: str) -> list[str]:
    if decision == "ready_for_staging":
        return [
            f"python3 -m growth_dev.cli team release staging-readiness --run-id {run_id}",
            "人工确认 staging 变更窗口、回滚方式和责任人；第一版不会自动部署。",
        ]
    if decision == "waiting_for_ci":
        return [
            f"python3 -m growth_dev.cli team pr status --run-id {run_id}",
            f"python3 -m growth_dev.cli team release staging-readiness --run-id {run_id}",
        ]
    return [
        "先处理 staging_readiness.md 中的 blockers。",
        f"python3 -m growth_dev.cli team release readiness --run-id {run_id}",
        f"python3 -m growth_dev.cli team release staging-readiness --run-id {run_id}",
    ]


def _ci_status_reason(status: str) -> str:
    if status in {"running", "pending"}:
        return "CI checks 尚未完成。"
    if status == "unknown":
        return "CI 状态未知或尚未发现 checks。"
    if status == "not_started":
        return "CI 状态尚未刷新。"
    return f"CI status is `{status}`."


def _ci_check_names(ci_status: dict[str, Any]) -> list[str]:
    checks = ci_status.get("checks", []) if isinstance(ci_status.get("checks"), list) else []
    names: list[str] = []
    for check in checks:
        if isinstance(check, dict):
            name = str(check.get("name", ""))
            status = str(check.get("status", ""))
            conclusion = str(check.get("conclusion", ""))
            names.append(" / ".join(item for item in (name, status, conclusion) if item))
    return names


def _pr_url(github_pr: dict[str, Any]) -> str:
    pr = github_pr.get("pr") if isinstance(github_pr.get("pr"), dict) else {}
    return str(pr.get("url", ""))


def _parse_diff_summary(diff: str) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_hunk = False

    def finish() -> None:
        nonlocal current
        if current is None:
            return
        files.append(
            {
                "path": str(current.get("path") or current.get("new_path") or current.get("old_path") or ""),
                "status": str(current.get("status") or "modified"),
                "additions": int(current.get("additions") or 0),
                "deletions": int(current.get("deletions") or 0),
            }
        )
        current = None

    for line in diff.splitlines():
        if line.startswith("diff --git "):
            finish()
            old_path, new_path = _parse_diff_git_paths(line)
            current = {"path": new_path or old_path, "old_path": old_path, "new_path": new_path, "status": "modified", "additions": 0, "deletions": 0}
            in_hunk = False
            continue
        if current is None:
            continue
        if line.startswith("new file mode"):
            current["status"] = "added"
        elif line.startswith("deleted file mode"):
            current["status"] = "deleted"
        elif line.startswith("rename from "):
            current["status"] = "renamed"
            current["old_path"] = _normalize_repo_path(line.removeprefix("rename from "))
        elif line.startswith("rename to "):
            current["status"] = "renamed"
            current["new_path"] = _normalize_repo_path(line.removeprefix("rename to "))
            current["path"] = current["new_path"]
        elif line.startswith("--- "):
            old_path = _normalize_diff_path(line.removeprefix("--- "))
            if old_path == "/dev/null":
                current["status"] = "added"
            elif old_path:
                current["old_path"] = old_path
        elif line.startswith("+++ "):
            new_path = _normalize_diff_path(line.removeprefix("+++ "))
            if new_path == "/dev/null":
                current["status"] = "deleted"
                current["path"] = current.get("old_path") or current.get("path") or ""
            elif new_path:
                current["new_path"] = new_path
                current["path"] = new_path
        elif line.startswith("@@"):
            in_hunk = True
        elif in_hunk and line.startswith("+") and not line.startswith("+++"):
            current["additions"] = int(current.get("additions") or 0) + 1
        elif in_hunk and line.startswith("-") and not line.startswith("---"):
            current["deletions"] = int(current.get("deletions") or 0) + 1
    finish()
    return {
        "available": bool(diff.strip()),
        "changed_files": [str(item.get("path", "")) for item in files if item.get("path")],
        "files_changed": len(files),
        "additions": sum(int(item.get("additions") or 0) for item in files),
        "deletions": sum(int(item.get("deletions") or 0) for item in files),
        "files": files,
    }


def _parse_diff_git_paths(line: str) -> tuple[str, str]:
    match = re.match(r"^diff --git a/(.*?) b/(.*)$", line)
    if not match:
        return "", ""
    return _normalize_diff_path(match.group(1)), _normalize_diff_path(match.group(2))


def _normalize_diff_path(value: str) -> str:
    path = value.strip().strip('"')
    if path in {"/dev/null", "dev/null"}:
        return "/dev/null"
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    return _normalize_repo_path(path)


def _normalize_repo_path(value: str) -> str:
    path = str(value).strip().strip('"')
    if not path or path == "/dev/null":
        return path
    return path.replace("\\", "/")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = read_json(path)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_text(value: str) -> str:
    text = str(value)
    for pattern, replacement in SECRET_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return text


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
