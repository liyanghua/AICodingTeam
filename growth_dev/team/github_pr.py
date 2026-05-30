from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from ..utils import ensure_dir, now_iso, read_json, write_json
from .release import _parse_diff_summary  # Reuse the local release diff parser.


GITHUB_PR_JSON = "github_pr.json"
GITHUB_PR_MD = "github_pr.md"
CI_STATUS_JSON = "ci_status.json"
CI_STATUS_MD = "ci_status.md"

SECRET_REPLACEMENTS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{6,}"), "<redacted-secret>"),
    (re.compile(r"(?i)(AICODEMIRROR_KEY\s*[:=]\s*)[^\s,;'\"]+"), r"\1<redacted>"),
    (re.compile(r"(?i)((api[_-]?key|secret|token|password)\s*[:=]\s*)[^\s,;'\"]+"), r"\1<redacted>"),
    (re.compile(r"\.env"), "<env-file>"),
]


def create_draft_pr(
    run_id: str,
    *,
    runs_dir: Path = Path("runs"),
    repo_root: Path = Path("."),
    base: str = "main",
    push: bool = False,
    command_runner: Any | None = None,
) -> dict[str, Any]:
    command_runner = command_runner or subprocess.run
    runs_dir = Path(runs_dir)
    repo_root = Path(repo_root)
    run_dir = runs_dir / run_id
    readiness = _read_json(run_dir / "release_readiness.json")
    pr_draft_path = run_dir / "pr_draft.md"
    result = _initial_pr_status(run_id, base=base)
    result["status"] = "running"
    _write_pr_artifacts(run_dir, result)

    blockers = _preflight_blockers(run_id, run_dir, readiness, pr_draft_path)
    if blockers:
        result.update(
            {
                "status": "failed",
                "release_decision": str(readiness.get("release_decision", "")),
                "blockers": _dedupe(blockers),
                "next_action": "先处理发布准备阻塞，再重试创建 Draft PR。",
            }
        )
        _write_pr_artifacts(run_dir, result)
        return _redact(result)

    branch = _git_stdout(["git", "branch", "--show-current"], repo_root, command_runner, blockers)
    remote = _git_stdout(["git", "remote", "get-url", "origin"], repo_root, command_runner, blockers)
    if branch:
        result["pr"]["head"] = branch
        if branch == base:
            blockers.append(f"当前分支 `{branch}` 与 base `{base}` 相同，不能创建有效 PR。")
    if remote and "github.com" not in remote:
        blockers.append("origin remote is not a GitHub remote.")
    expected_files = _expected_files(readiness, run_dir)
    blockers.extend(_working_tree_blockers(repo_root, expected_files, command_runner, result["warnings"]))
    _check_gh_auth(repo_root, command_runner, blockers)

    if blockers:
        result.update(
            {
                "status": "failed",
                "release_decision": str(readiness.get("release_decision", "")),
                "blockers": _dedupe(blockers),
                "next_action": "处理 GitHub PR 创建阻塞后重试。",
            }
        )
        _write_pr_artifacts(run_dir, result)
        return _redact(result)

    result["release_decision"] = str(readiness.get("release_decision", ""))
    result["warnings"].extend(str(item) for item in readiness.get("warnings", []) if item)
    existing = _existing_pr(branch, repo_root, command_runner)
    if existing:
        result.update(existing)
        _write_pr_artifacts(run_dir, result)
        return _redact(result)

    if push:
        push_command = ["git", "push", "-u", "origin", branch]
        result["commands"].append(_command_text(push_command))
        completed = _run(command_runner, push_command, repo_root)
        if completed.returncode != 0:
            result.update(
                {
                    "status": "failed",
                    "blockers": [f"git push failed: {_command_error(completed)}"],
                    "next_action": "处理 push 失败后重新创建 Draft PR。",
                }
            )
            _write_pr_artifacts(run_dir, result)
            return _redact(result)

    body_path = _write_pr_body(run_dir, readiness)
    title = _pr_title(readiness, run_id)
    command = [
        "gh",
        "pr",
        "create",
        "--draft",
        "--base",
        base,
        "--head",
        branch,
        "--title",
        title,
        "--body-file",
        str(body_path),
    ]
    result["commands"].append(_command_text(command))
    completed = _run(command_runner, command, repo_root)
    if completed.returncode != 0:
        result.update(
            {
                "status": "failed",
                "blockers": [f"gh pr create failed: {_command_error(completed)}"],
                "next_action": "查看 GitHub CLI 输出，处理权限或网络问题后重试。",
            }
        )
        _write_pr_artifacts(run_dir, result)
        return _redact(result)

    url = _extract_pr_url(completed.stdout)
    result["status"] = "created"
    result["pr"].update(
        {
            "number": _pr_number(url),
            "url": url,
            "title": title,
            "state": "OPEN",
            "is_draft": True,
            "base": base,
            "head": branch,
        }
    )
    result["next_action"] = "刷新 PR/CI 状态，观察 GitHub checks 是否通过。"
    _write_pr_artifacts(run_dir, result)
    return _redact(result)


def refresh_ci_status(
    run_id: str,
    *,
    runs_dir: Path = Path("runs"),
    repo_root: Path = Path("."),
    command_runner: Any | None = None,
) -> dict[str, Any]:
    command_runner = command_runner or subprocess.run
    runs_dir = Path(runs_dir)
    repo_root = Path(repo_root)
    run_dir = runs_dir / run_id
    pr_status = _read_json(run_dir / GITHUB_PR_JSON)
    pr = pr_status.get("pr") if isinstance(pr_status.get("pr"), dict) else {}
    pr_ref = str(pr.get("url") or pr.get("number") or "")
    result = _initial_ci_status(run_id, pr_url=str(pr.get("url", "")))
    if not pr_ref:
        result.update({"status": "not_started", "blockers": ["GitHub Draft PR 尚未创建。"], "next_action": "先创建 GitHub Draft PR。"})
        _write_ci_artifacts(run_dir, result)
        return _redact(result)

    command = ["gh", "pr", "checks", pr_ref, "--json", "name,workflow,status,conclusion,link,startedAt,completedAt"]
    completed = _run(command_runner, command, repo_root)
    if completed.returncode != 0:
        result.update(
            {
                "status": "unknown",
                "blockers": [f"gh pr checks failed: {_command_error(completed)}"],
                "next_action": "确认 gh 已登录且有仓库权限后刷新 CI 状态。",
            }
        )
        _write_ci_artifacts(run_dir, result)
        return _redact(result)

    checks = _parse_checks(completed.stdout)
    status, warnings, blockers = _ci_rollup(checks)
    result.update(
        {
            "status": status,
            "checks": checks,
            "summary": _ci_summary(status, checks),
            "warnings": warnings,
            "blockers": blockers,
            "next_action": _ci_next_action(status),
        }
    )
    _write_ci_artifacts(run_dir, result)
    return _redact(result)


def format_pr_status(result: dict[str, Any]) -> str:
    pr = result.get("pr", {}) if isinstance(result.get("pr"), dict) else {}
    lines = [
        f"Run: {result.get('run_id', '')}",
        f"Status: {result.get('status', '')}",
        f"PR: {pr.get('url', '') or 'not created'}",
        f"Base/Head: {pr.get('base', '')} <- {pr.get('head', '')}",
    ]
    blockers = [str(item) for item in result.get("blockers", [])]
    warnings = [str(item) for item in result.get("warnings", [])]
    if blockers:
        lines.extend(["Blockers:", *[f"- {item}" for item in blockers]])
    if warnings:
        lines.extend(["Warnings:", *[f"- {item}" for item in warnings]])
    if result.get("next_action"):
        lines.extend(["Next action:", f"- {result.get('next_action')}"])
    return "\n".join(lines).rstrip() + "\n"


def format_ci_status(result: dict[str, Any]) -> str:
    lines = [
        f"Run: {result.get('run_id', '')}",
        f"CI status: {result.get('status', '')}",
        f"Summary: {result.get('summary', '')}",
    ]
    for check in result.get("checks", []):
        if isinstance(check, dict):
            lines.append(f"- {check.get('name', '')}: {check.get('status', '')}/{check.get('conclusion', '')}")
    blockers = [str(item) for item in result.get("blockers", [])]
    warnings = [str(item) for item in result.get("warnings", [])]
    if blockers:
        lines.extend(["Blockers:", *[f"- {item}" for item in blockers]])
    if warnings:
        lines.extend(["Warnings:", *[f"- {item}" for item in warnings]])
    if result.get("next_action"):
        lines.extend(["Next action:", f"- {result.get('next_action')}"])
    return "\n".join(lines).rstrip() + "\n"


def _preflight_blockers(run_id: str, run_dir: Path, readiness: dict[str, Any], pr_draft_path: Path) -> list[str]:
    blockers: list[str] = []
    if not readiness:
        blockers.append("release_readiness.json is missing.")
    elif readiness.get("release_decision") == "blocked":
        blockers.append("release_readiness is blocked.")
        blockers.extend(str(item) for item in readiness.get("blockers", []) if item)
    if not pr_draft_path.exists():
        blockers.append("pr_draft.md is missing.")
    if not (run_dir / "team_run_record.json").exists():
        blockers.append(f"team_run_record.json not found for run {run_id}.")
    return blockers


def _git_stdout(command: list[str], repo_root: Path, command_runner: Any, blockers: list[str]) -> str:
    completed = _run(command_runner, command, repo_root)
    if completed.returncode != 0:
        blockers.append(f"{_command_text(command)} failed: {_command_error(completed)}")
        return ""
    value = str(completed.stdout or "").strip()
    if command[:3] == ["git", "branch", "--show-current"] and not value:
        blockers.append("当前不在普通 git branch 上。")
    return _redact_text(value)


def _check_gh_auth(repo_root: Path, command_runner: Any, blockers: list[str]) -> None:
    try:
        completed = _run(command_runner, ["gh", "auth", "status"], repo_root)
    except FileNotFoundError:
        blockers.append("gh CLI is not installed or not on PATH.")
        return
    if completed.returncode != 0:
        blockers.append(f"gh auth status failed: {_command_error(completed)}")


def _working_tree_blockers(repo_root: Path, expected_files: list[str], command_runner: Any, warnings: list[str]) -> list[str]:
    completed = _run(command_runner, ["git", "status", "--porcelain"], repo_root)
    if completed.returncode != 0:
        return [f"git status failed: {_command_error(completed)}"]
    expected = set(expected_files)
    tracked: list[str] = []
    untracked: list[str] = []
    for line in str(completed.stdout or "").splitlines():
        if not line:
            continue
        if line.startswith("?? "):
            untracked.append(_normalize_repo_path(line[3:]))
        else:
            tracked.append(_normalize_repo_path(_porcelain_path(line[3:])))
    unrelated = [path for path in _dedupe(tracked) if path and path not in expected]
    if untracked:
        warnings.append(f"存在未跟踪文件，未计入 PR 范围：{', '.join(_dedupe(untracked)[:6])}")
    if unrelated:
        return [f"当前 tracked/staged 变更包含 run 预期 changed files 之外的文件：{', '.join(unrelated)}"]
    return []


def _expected_files(readiness: dict[str, Any], run_dir: Path) -> list[str]:
    evidence = readiness.get("evidence") if isinstance(readiness.get("evidence"), dict) else {}
    files = [str(item) for item in evidence.get("changed_files", []) if item]
    if files:
        return _dedupe([_normalize_repo_path(item) for item in files])
    diff = _read_text(run_dir / "codex" / "diff.patch")
    return [str(item) for item in _parse_diff_summary(diff).get("changed_files", [])]


def _existing_pr(branch: str, repo_root: Path, command_runner: Any) -> dict[str, Any] | None:
    command = ["gh", "pr", "view", branch, "--json", "number,url,title,state,isDraft,baseRefName,headRefName"]
    completed = _run(command_runner, command, repo_root)
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or not payload.get("url"):
        return None
    return {
        "status": "created",
        "pr": {
            "number": payload.get("number"),
            "url": str(payload.get("url", "")),
            "title": str(payload.get("title", "")),
            "state": str(payload.get("state", "")),
            "is_draft": bool(payload.get("isDraft", True)),
            "base": str(payload.get("baseRefName", "")),
            "head": str(payload.get("headRefName", branch)),
        },
        "next_action": "已存在 Draft PR，可刷新 PR/CI 状态。",
    }


def _write_pr_body(run_dir: Path, readiness: dict[str, Any]) -> Path:
    source = _read_text(run_dir / "pr_draft.md")
    lines = [
        source.rstrip(),
        "",
        "## Release Readiness",
        "",
        f"- Decision: `{readiness.get('release_decision', '')}`",
    ]
    warnings = readiness.get("warnings", []) if isinstance(readiness.get("warnings"), list) else []
    blockers = readiness.get("blockers", []) if isinstance(readiness.get("blockers"), list) else []
    if warnings:
        lines.append("- Warnings:")
        lines.extend(f"  - {item}" for item in warnings[:6])
    if blockers:
        lines.append("- Blockers:")
        lines.extend(f"  - {item}" for item in blockers[:6])
    lines.extend(
        [
            "",
            "## Local Validation",
            "",
            "- `python3 -m unittest discover -s tests -v`",
            "- Local artifacts remain under this run directory.",
        ]
    )
    body_path = run_dir / "github_pr_body.md"
    body_path.write_text(_redact_text("\n".join(lines).rstrip() + "\n"), encoding="utf-8")
    return body_path


def _parse_checks(stdout: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(stdout or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    checks: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        checks.append(
            {
                "name": _redact_text(str(item.get("name", ""))),
                "workflow": _redact_text(str(item.get("workflow", ""))),
                "status": _redact_text(str(item.get("status", ""))),
                "conclusion": _redact_text(str(item.get("conclusion", ""))),
                "url": _redact_text(str(item.get("link") or item.get("url") or "")),
                "started_at": _redact_text(str(item.get("startedAt") or item.get("started_at") or "")),
                "completed_at": _redact_text(str(item.get("completedAt") or item.get("completed_at") or "")),
            }
        )
    return checks


def _ci_rollup(checks: list[dict[str, Any]]) -> tuple[str, list[str], list[str]]:
    if not checks:
        return "unknown", ["尚未发现 CI checks，可能是仓库没有 workflow 或 GitHub 尚未生成 checks。"], []
    statuses = [str(item.get("status", "")).upper() for item in checks]
    conclusions = [str(item.get("conclusion", "")).upper() for item in checks]
    if any(value in {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"} for value in conclusions):
        failed = [str(item.get("name", "")) for item in checks if str(item.get("conclusion", "")).upper() in {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}]
        return "failed", [], [f"CI checks failed: {', '.join(failed)}"]
    if all(status in {"COMPLETED", "SUCCESS"} for status in statuses) and all(value in {"SUCCESS", "SKIPPED", "NEUTRAL", ""} for value in conclusions):
        return "passed", [], []
    if any(status in {"IN_PROGRESS", "PENDING", "QUEUED", "REQUESTED", "WAITING"} for status in statuses):
        return "running", ["CI checks 仍在运行。"], []
    return "pending", ["CI checks 尚未完成。"], []


def _ci_summary(status: str, checks: list[dict[str, Any]]) -> str:
    if status == "passed":
        return f"{len(checks)} 个 CI check 已通过。"
    if status == "failed":
        return "存在失败的 CI check，需要处理后再进入合并。"
    if status == "running":
        return "CI 正在运行，请稍后刷新。"
    if status == "unknown":
        return "尚未发现可用 CI checks。"
    return "CI checks 尚未完成。"


def _ci_next_action(status: str) -> str:
    if status == "passed":
        return "可以进行人工 Review，确认后再决定是否 ready for review 或合并。"
    if status == "failed":
        return "打开失败 check，修复后重新推送或重新运行 CI。"
    if status == "running":
        return "稍后刷新 PR/CI 状态。"
    return "确认仓库是否配置 GitHub Actions，或稍后刷新。"


def _write_pr_artifacts(run_dir: Path, result: dict[str, Any]) -> None:
    ensure_dir(run_dir)
    write_json(run_dir / GITHUB_PR_JSON, _redact(result))
    (run_dir / GITHUB_PR_MD).write_text(_pr_markdown(_redact(result)), encoding="utf-8")


def _write_ci_artifacts(run_dir: Path, result: dict[str, Any]) -> None:
    ensure_dir(run_dir)
    write_json(run_dir / CI_STATUS_JSON, _redact(result))
    (run_dir / CI_STATUS_MD).write_text(_ci_markdown(_redact(result)), encoding="utf-8")


def _pr_markdown(result: dict[str, Any]) -> str:
    pr = result.get("pr", {}) if isinstance(result.get("pr"), dict) else {}
    lines = [
        "# GitHub Draft PR",
        "",
        f"- Run: `{result.get('run_id', '')}`",
        f"- Status: `{result.get('status', '')}`",
        f"- Release decision: `{result.get('release_decision', '')}`",
        f"- PR: {pr.get('url', '') or 'not created'}",
        f"- Base/head: `{pr.get('base', '')}` <- `{pr.get('head', '')}`",
        "",
        "## Blockers",
        "",
        *([f"- {item}" for item in result.get("blockers", [])] or ["暂无硬阻塞。"]),
        "",
        "## Warnings",
        "",
        *([f"- {item}" for item in result.get("warnings", [])] or ["暂无 warning。"]),
        "",
        "## Next Action",
        "",
        result.get("next_action", "") or "暂无下一步。",
    ]
    return _redact_text("\n".join(lines).rstrip() + "\n")


def _ci_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# CI Status",
        "",
        f"- Run: `{result.get('run_id', '')}`",
        f"- Status: `{result.get('status', '')}`",
        f"- Summary: {result.get('summary', '')}",
        f"- PR: {result.get('pr_url', '') or 'not created'}",
        "",
        "## Checks",
        "",
    ]
    checks = result.get("checks", []) if isinstance(result.get("checks"), list) else []
    if checks:
        lines.extend(["| Check | Status | Conclusion | URL |", "| --- | --- | --- | --- |"])
        for check in checks:
            if isinstance(check, dict):
                lines.append(f"| {check.get('name', '')} | `{check.get('status', '')}` | `{check.get('conclusion', '')}` | {check.get('url', '')} |")
    else:
        lines.append("暂无 CI checks。")
    lines.extend(["", "## Next Action", "", result.get("next_action", "") or "暂无下一步。"])
    return _redact_text("\n".join(lines).rstrip() + "\n")


def _initial_pr_status(run_id: str, *, base: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "status": "not_started",
        "generated_at": now_iso(),
        "pr": {"number": None, "url": "", "title": "", "state": "", "is_draft": True, "base": base, "head": ""},
        "release_decision": "",
        "warnings": [],
        "blockers": [],
        "commands": [],
        "next_action": "",
    }


def _initial_ci_status(run_id: str, *, pr_url: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "status": "not_started",
        "generated_at": now_iso(),
        "pr_url": pr_url,
        "checks": [],
        "summary": "",
        "warnings": [],
        "blockers": [],
        "next_action": "",
    }


def _run(command_runner: Any, command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return command_runner(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)


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


def _pr_title(readiness: dict[str, Any], run_id: str) -> str:
    pr = readiness.get("pr_draft") if isinstance(readiness.get("pr_draft"), dict) else {}
    return _redact_text(str(pr.get("title") or run_id).strip() or run_id)


def _extract_pr_url(stdout: str) -> str:
    match = re.search(r"https://github\.com/[^\s]+/pull/\d+", stdout or "")
    return match.group(0) if match else str(stdout or "").strip()


def _pr_number(url: str) -> int | None:
    match = re.search(r"/pull/(\d+)", url or "")
    return int(match.group(1)) if match else None


def _command_text(command: list[str]) -> str:
    return " ".join(command)


def _command_error(completed: subprocess.CompletedProcess[str]) -> str:
    return _redact_text(str(completed.stderr or completed.stdout or f"exit {completed.returncode}").strip())


def _porcelain_path(value: str) -> str:
    path = value.strip()
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return path.strip('"')


def _normalize_repo_path(value: str) -> str:
    return str(value).strip().strip('"').replace("\\", "/")


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
