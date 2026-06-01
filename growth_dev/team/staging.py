from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from ..utils import ensure_dir, now_iso, read_json, write_json
from .release import generate_staging_readiness


REHEARSAL_JSON = "staging_rehearsal.json"
REHEARSAL_MD = "staging_rehearsal.md"
REHEARSAL_DIR = "staging_rehearsal"
TESTS_STDOUT_LOG = "tests_stdout.log"
TESTS_STDERR_LOG = "tests_stderr.log"
FULL_TEST_COMMAND = ["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]
GIT_STATUS_COMMAND = ["git", "status", "--short"]

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]

SECRET_REPLACEMENTS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{6,}"), "<redacted-secret>"),
    (re.compile(r"(?i)(AICODEMIRROR_KEY\s*[:=]\s*)[^\s,;'\"]+"), r"\1<redacted>"),
    (re.compile(r"(?i)((api[_-]?key|secret|token|password)\s*[:=]\s*)[^\s,;'\"]+"), r"\1<redacted>"),
    (re.compile(r"\.env"), "<env-file>"),
]


def run_staging_rehearsal(
    run_id: str,
    *,
    runs_dir: Path = Path("runs"),
    repo_root: Path = Path("."),
    command_runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    runs_dir = Path(runs_dir)
    repo_root = Path(repo_root)
    run_dir = runs_dir / run_id
    if not (run_dir / "team_run_record.json").exists():
        raise FileNotFoundError(f"team_run_record.json not found: {run_dir / 'team_run_record.json'}")

    staging_readiness = _read_or_generate_staging_readiness(run_id, runs_dir)
    result = _initial_result(run_id, staging_readiness)
    _write_artifacts(run_dir, result)

    decision = str(staging_readiness.get("staging_decision", "not_generated"))
    changed_files = _changed_files(staging_readiness)
    result["evidence"]["changed_files"] = changed_files
    if decision != "ready_for_staging":
        result["status"] = "blocked"
        result["summary"] = _blocked_summary(decision, staging_readiness)
        result["steps"] = [
            {"id": "readiness", "status": "blocked", "reason": result["summary"]},
            {"id": "full_tests", "status": "skipped", "command": _command_text(FULL_TEST_COMMAND), "exit_code": None, "reason": "staging_readiness is not ready_for_staging"},
        ]
        result["blockers"] = _dedupe([result["summary"], *[str(item) for item in staging_readiness.get("blockers", []) if item]])
        result["warnings"] = [str(item) for item in staging_readiness.get("warnings", []) if item]
        result["next_actions"] = _next_actions(run_id, "blocked")
        result = _redact(result)
        _write_artifacts(run_dir, result)
        return result

    result["steps"] = [{"id": "readiness", "status": "passed", "reason": "staging_readiness is ready_for_staging"}]
    result["evidence"]["git_status"] = _git_status(repo_root, command_runner, result["warnings"])
    test_step = _run_full_tests(run_dir, repo_root, command_runner)
    result["steps"].append(test_step)

    if int(test_step.get("exit_code") or 0) == 0:
        result["status"] = "completed"
        result["summary"] = "Staging 本地演练已完成：ready_for_staging 已复核，全量测试通过。"
        result["next_actions"] = _next_actions(run_id, "completed")
    else:
        result["status"] = "failed"
        result["summary"] = "Staging 本地演练未通过：全量测试失败，暂不建议进入真实 staging。"
        result["blockers"] = ["全量测试未通过，请先修复失败用例后重新运行 Staging 本地演练。"]
        result["next_actions"] = _next_actions(run_id, "failed")

    result = _redact(result)
    _write_artifacts(run_dir, result)
    return result


def format_staging_rehearsal(result: dict[str, Any]) -> str:
    lines = [
        f"Run: {result.get('run_id', '')}",
        f"Status: {result.get('status', '')}",
        f"Summary: {result.get('summary', '')}",
        f"Staging readiness: {result.get('staging_readiness_decision', '')}",
        "",
        "Steps:",
    ]
    for step in result.get("steps", []):
        if isinstance(step, dict):
            line = f"- {step.get('id', '')}: {step.get('status', '')}"
            if step.get("exit_code") is not None:
                line += f" (exit {step.get('exit_code')})"
            reason = str(step.get("reason", ""))
            if reason:
                line += f" - {reason}"
            lines.append(line)
    blockers = [str(item) for item in result.get("blockers", []) if item]
    warnings = [str(item) for item in result.get("warnings", []) if item]
    next_actions = [str(item) for item in result.get("next_actions", []) if item]
    if blockers:
        lines.extend(["", "Blockers:", *[f"- {item}" for item in blockers]])
    if warnings:
        lines.extend(["", "Warnings:", *[f"- {item}" for item in warnings]])
    if next_actions:
        lines.extend(["", "Next actions:", *[f"- {item}" for item in next_actions]])
    return "\n".join(lines).rstrip() + "\n"


def _read_or_generate_staging_readiness(run_id: str, runs_dir: Path) -> dict[str, Any]:
    path = runs_dir / run_id / "staging_readiness.json"
    if path.exists():
        payload = _read_json(path)
        if payload:
            return payload
    return generate_staging_readiness(run_id, runs_dir=runs_dir)


def _initial_result(run_id: str, staging_readiness: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "status": "running",
        "generated_at": now_iso(),
        "summary": "正在执行 Staging 本地演练。",
        "staging_readiness_decision": str(staging_readiness.get("staging_decision", "not_generated")),
        "steps": [],
        "evidence": {
            "changed_files": [],
            "git_status": [],
            "tests_stdout_log": f"{REHEARSAL_DIR}/{TESTS_STDOUT_LOG}",
            "tests_stderr_log": f"{REHEARSAL_DIR}/{TESTS_STDERR_LOG}",
        },
        "blockers": [],
        "warnings": [],
        "next_actions": [],
    }


def _changed_files(staging_readiness: dict[str, Any]) -> list[str]:
    evidence = staging_readiness.get("evidence") if isinstance(staging_readiness.get("evidence"), dict) else {}
    return _dedupe([str(item) for item in evidence.get("changed_files", []) if item])


def _git_status(repo_root: Path, command_runner: CommandRunner, warnings: list[str]) -> list[str]:
    completed = command_runner(
        GIT_STATUS_COMMAND,
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        message = _redact_text(completed.stderr or completed.stdout or "git status failed")
        warnings.append(f"git status unavailable: {message}")
        return []
    return [_redact_text(line) for line in completed.stdout.splitlines() if line.strip()]


def _run_full_tests(run_dir: Path, repo_root: Path, command_runner: CommandRunner) -> dict[str, Any]:
    rehearsal_dir = ensure_dir(run_dir / REHEARSAL_DIR)
    completed = command_runner(
        FULL_TEST_COMMAND,
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    stdout = _redact_text(completed.stdout or "")
    stderr = _redact_text(completed.stderr or "")
    (rehearsal_dir / TESTS_STDOUT_LOG).write_text(stdout, encoding="utf-8")
    (rehearsal_dir / TESTS_STDERR_LOG).write_text(stderr, encoding="utf-8")
    status = "completed" if completed.returncode == 0 else "failed"
    return {
        "id": "full_tests",
        "status": status,
        "command": _command_text(FULL_TEST_COMMAND),
        "exit_code": int(completed.returncode),
        "stdout_tail": _tail_lines(stdout),
        "stderr_tail": _tail_lines(stderr),
    }


def _write_artifacts(run_dir: Path, result: dict[str, Any]) -> None:
    ensure_dir(run_dir)
    write_json(run_dir / REHEARSAL_JSON, _redact(result))
    (run_dir / REHEARSAL_MD).write_text(_markdown(_redact(result)), encoding="utf-8")


def _markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Staging Rehearsal",
        "",
        f"- Run: `{result.get('run_id', '')}`",
        f"- Status: `{result.get('status', '')}`",
        f"- Staging readiness: `{result.get('staging_readiness_decision', '')}`",
        f"- Summary: {result.get('summary', '')}",
        "",
        "## Steps",
        "",
        "| Step | Status | Exit Code | Reason |",
        "| --- | --- | --- | --- |",
    ]
    for step in result.get("steps", []):
        if not isinstance(step, dict):
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    str(step.get("id", "")),
                    str(step.get("status", "")),
                    "" if step.get("exit_code") is None else str(step.get("exit_code")),
                    str(step.get("reason", "")),
                ]
            )
            + " |"
        )
    evidence = result.get("evidence", {}) if isinstance(result.get("evidence"), dict) else {}
    changed_files = [str(item) for item in evidence.get("changed_files", []) if item]
    git_status = [str(item) for item in evidence.get("git_status", []) if item]
    lines.extend(
        [
            "",
            "## Evidence",
            "",
            "Changed files:",
            *([f"- `{item}`" for item in changed_files] or ["- 暂无记录。"]),
            "",
            "Git status:",
            *([f"- `{item}`" for item in git_status] or ["- 暂无变更或未记录。"]),
            "",
            "Logs:",
            f"- `{evidence.get('tests_stdout_log', '')}`",
            f"- `{evidence.get('tests_stderr_log', '')}`",
        ]
    )
    blockers = [str(item) for item in result.get("blockers", []) if item]
    warnings = [str(item) for item in result.get("warnings", []) if item]
    next_actions = [str(item) for item in result.get("next_actions", []) if item]
    lines.extend(["", "## Blockers", "", *([f"- {item}" for item in blockers] or ["- 暂无。"])])
    lines.extend(["", "## Warnings", "", *([f"- {item}" for item in warnings] or ["- 暂无。"])])
    lines.extend(["", "## Next Actions", "", *([f"- {item}" for item in next_actions] or ["- 暂无。"])])
    return _redact_text("\n".join(lines).rstrip() + "\n")


def _blocked_summary(decision: str, staging_readiness: dict[str, Any]) -> str:
    summary = str(staging_readiness.get("summary", ""))
    if summary:
        return f"Staging readiness 为 `{decision}`，本地演练已阻塞：{summary}"
    return f"Staging readiness 为 `{decision}`，未达到 ready_for_staging，本地演练已阻塞。"


def _next_actions(run_id: str, status: str) -> list[str]:
    if status == "completed":
        return [
            "人工确认 staging 变更窗口、回滚方式和责任人；第一版不会自动部署。",
            f"python3 -m growth_dev.cli team release staging-rehearsal --run-id {run_id}",
        ]
    if status == "failed":
        return [
            "先修复全量测试失败，再重新运行本地演练。",
            "python3 -m unittest discover -s tests -v",
            f"python3 -m growth_dev.cli team release staging-rehearsal --run-id {run_id}",
        ]
    return [
        "先处理 staging_readiness.md 中的 blockers 或等待 CI 通过。",
        f"python3 -m growth_dev.cli team release staging-readiness --run-id {run_id}",
    ]


def _command_text(command: list[str]) -> str:
    return " ".join(command)


def _tail_lines(text: str, max_lines: int = 12) -> list[str]:
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-max_lines:]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = read_json(path)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


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
