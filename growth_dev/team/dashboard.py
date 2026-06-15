from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from ..utils import ensure_dir, now_iso, read_json, timestamp_slug, write_json
from .models import TeamRunRecord
from .quality import evaluate_run_quality, summarize_run_health, summarize_run_logs
from .release import generate_production_readiness, generate_release_readiness, generate_staging_readiness
from .github_pr import create_draft_pr, refresh_ci_status
from .staging import run_staging_rehearsal


_DASHBOARD_PROCESSES: list[subprocess.Popen] = []
_ACCEPTANCE_THREADS: list[threading.Thread] = []


STAGE_DEFINITIONS = [
    {"id": "orchestrator", "label": "Orchestrator", "phase": "Plan", "artifact_hints": ["task.yaml", "context.md"]},
    {"id": "requirements", "label": "Requirements", "phase": "Plan", "artifact_hints": ["requirements/brief_analysis.json", "requirements/requirement_quality_report.json"]},
    {"id": "product", "label": "Product", "phase": "Spec", "artifact_hints": ["prd.md"]},
    {"id": "architect", "label": "Architect", "phase": "Spec", "artifact_hints": ["tech_spec.md", "architecture_diagram.md"]},
    {"id": "ux", "label": "UX", "phase": "Spec", "artifact_hints": ["ui_spec.md"]},
    {"id": "qa", "label": "QA", "phase": "Spec", "artifact_hints": ["eval.md"]},
    {"id": "coder", "label": "AI Coding", "phase": "Build", "artifact_hints": ["coding_prompt.md", "codex/diff.patch"]},
    {"id": "reviewer", "label": "Review", "phase": "Guard", "artifact_hints": ["review_report.md"]},
    {"id": "verifier", "label": "TDD / Test", "phase": "Guard", "artifact_hints": ["test_report.md"]},
    {"id": "publisher", "label": "Report", "phase": "Publish", "artifact_hints": ["final_report.md"]},
    {"id": "ci", "label": "CI", "phase": "Future", "artifact_hints": []},
    {"id": "deploy", "label": "Deploy", "phase": "Future", "artifact_hints": []},
    {"id": "human_approval", "label": "Human Approval", "phase": "Future", "artifact_hints": []},
]


@dataclass(slots=True)
class DashboardConfig:
    host: str = "127.0.0.1"
    port: int = 8790
    runs_dir: Path = Path("runs")
    domains_dir: Path = Path("domains")
    dashboard_dir: Path = Path("dashboard")
    repo_root: Path = Path(".")
    codex_binary: str = "codex"
    codex_provider: str = "default"
    env_file: str = ".env"
    model: str = "gpt-5.3-codex"
    reasoning_effort: str = "medium"
    executor: str = "codex"
    planning_mode: str = "auto"
    requirements_model: str = ""
    requirements_reasoning_effort: str = "medium"


def list_dashboard_runs(runs_dir: Path = Path("runs"), limit: int = 30) -> list[dict[str, Any]]:
    runs_dir = Path(runs_dir).resolve()
    if not runs_dir.exists():
        return []
    runs: list[dict[str, Any]] = []
    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir():
            continue
        record_path = run_dir / "team_run_record.json"
        process_path = run_dir / "process.json"
        payload: dict[str, Any] = {"run_id": run_dir.name, "status": "starting", "updated_at": _mtime_iso(run_dir)}
        record: dict[str, Any] = {}
        process: dict[str, Any] = {}
        if record_path.exists():
            record = _safe_read_json(record_path)
            payload.update(
                {
                    "run_id": str(record.get("run_id", run_dir.name)),
                    "status": str(record.get("status", "unknown")),
                    "domain_id": str(record.get("domain_id", "")),
                    "brief": str(record.get("brief", "")),
                    "started_at": str(record.get("started_at", "")),
                    "finished_at": str(record.get("finished_at", "")),
                }
            )
            payload["updated_at"] = _mtime_iso(record_path)
        elif process_path.exists():
            process = _safe_read_json(process_path)
            payload.update(
                {
                    "run_id": str(process.get("run_id", run_dir.name)),
                    "status": str(process.get("status", "starting")),
                    "started_at": str(process.get("started_at", "")),
                    "updated_at": str(process.get("last_seen_at", "")) or _mtime_iso(process_path),
                }
            )
        if process_path.exists() and not process:
            process = _safe_read_json(process_path)
        background_failure = _background_failure(run_dir, record, process)
        if background_failure:
            payload["status"] = background_failure["status"]
            payload["failure_category"] = background_failure["failure_category"]
        runs.append(_redact(payload))
    runs.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
    return runs[:limit]


def build_dashboard_state(run_id: str, *, runs_dir: Path = Path("runs"), repo_root: Path = Path(".")) -> dict[str, Any]:
    runs_dir = Path(runs_dir).resolve()
    repo_root = Path(repo_root).resolve()
    run_dir = _safe_run_dir(runs_dir, run_id)
    if not run_dir.exists():
        raise FileNotFoundError(f"Run not found: {run_id}")

    record = _safe_read_json(run_dir / "team_run_record.json") if (run_dir / "team_run_record.json").exists() else {}
    process = _safe_read_json(run_dir / "process.json") if (run_dir / "process.json").exists() else {}
    events = _read_events(run_dir)
    agent_runs = [item for item in record.get("agent_runs", []) if isinstance(item, dict)]
    agent_by_id = {str(item.get("agent_id", "")): item for item in agent_runs}
    background_failure = _background_failure(run_dir, record, process)
    risk_events = [str(item) for item in record.get("risk_events", [])]
    if background_failure and background_failure["risk_event"] not in risk_events:
        risk_events.append(background_failure["risk_event"])

    gates = _build_gate_view(record)
    apply_status, apply_reason = _apply_gate(record)
    record_object = _team_record_from_dashboard_payload(record, run_id, run_dir, process, background_failure)
    health_summary = summarize_run_health(record_object, run_dir).to_dict()
    quality_report = evaluate_run_quality(record_object, run_dir).to_dict()
    gates.append({"id": "apply_gate", "label": "Apply Gate", "status": apply_status, "reason": apply_reason})
    ci_status = _read_ci_status(run_dir)
    staging_readiness = _read_staging_readiness(run_dir)
    production_readiness = _read_production_readiness(run_dir)
    gates.extend(
        [
            _ci_gate_view(ci_status),
            _deploy_gate_view(staging_readiness),
            _production_gate_view(production_readiness),
        ]
    )

    state = {
        "run_id": run_id,
        "status": background_failure["status"] if background_failure else str(record.get("status", process.get("status", "starting"))),
        "failure_category": background_failure["failure_category"] if background_failure else _failure_category(record),
        "team_id": str(record.get("team_id", "ai_native_engineering_team")),
        "domain_id": str(record.get("domain_id", "")),
        "brief": str(record.get("brief", "")),
        "executor": str(record.get("executor", "")),
        "started_at": str(record.get("started_at", process.get("started_at", ""))),
        "finished_at": str(record.get("finished_at", "")),
        "process": _redact(process),
        "stages": _build_stage_view(agent_by_id, record),
        "gates": gates,
        "apply_gate": {"status": apply_status, "reason": apply_reason},
        "health_summary": health_summary,
        "quality_report": quality_report,
        "requirement_understanding": _read_requirement_understanding(run_dir),
        "acceptance_coverage": _read_acceptance_coverage(run_dir),
        "tdd_plan": _read_tdd_plan(run_dir),
        "implementation_trace": _read_implementation_trace(run_dir),
        "failure_classification": _read_failure_classification(run_dir),
        "slice_loop": _read_slice_loop_state(run_dir),
        "implementation_completion_gate": _read_implementation_completion_gate(run_dir),
        "task_workspace": _read_task_workspace(run_dir),
        "task_journal": _read_task_journal(run_dir),
        "memory_recall": _read_memory_recall(run_dir),
        "release_readiness": _read_release_readiness(run_dir),
        "github_pr": _read_github_pr(run_dir),
        "ci_status": ci_status,
        "staging_readiness": staging_readiness,
        "staging_rehearsal": _read_staging_rehearsal(run_dir),
        "production_readiness": production_readiness,
        "acceptance": _read_acceptance_status(run_dir),
        "artifacts": _build_artifact_view(run_dir, repo_root, record),
        "events": events[-50:],
        "logs": _latest_log_lines(run_dir),
        "diff_summary": _diff_summary(run_dir),
        "next_actions": _next_actions(run_id, str(record.get("status", process.get("status", "starting"))), apply_status),
        "risk_events": risk_events,
    }
    return _redact(state)


def read_dashboard_artifact(
    run_id: str,
    artifact_path: str,
    *,
    runs_dir: Path = Path("runs"),
    repo_root: Path = Path("."),
    scope: str = "run",
    max_bytes: int = 300_000,
) -> dict[str, str]:
    if scope == "repo":
        if artifact_path != "AGENTS.md":
            raise ValueError("Only AGENTS.md is readable from repository scope.")
        root = repo_root.resolve()
        target = (root / artifact_path).resolve()
        if target.parent != root:
            raise ValueError("Artifact path escapes repository root.")
    else:
        run_dir = _safe_run_dir(Path(runs_dir), run_id)
        target = _safe_child(run_dir, artifact_path)

    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"Artifact not found: {artifact_path}")
    if target.stat().st_size > max_bytes:
        raise ValueError(f"Artifact is too large to preview: {artifact_path}")
    return {"path": artifact_path, "scope": scope, "content": target.read_text(encoding="utf-8", errors="replace")}


def start_dashboard_run(config: DashboardConfig, payload: dict[str, Any]) -> dict[str, Any]:
    brief = str(payload.get("brief", "")).strip()
    if not brief:
        raise ValueError("brief is required")
    domain = str(payload.get("domain") or payload.get("domain_id") or "xhs_browser_benchmark")
    run_id = str(payload.get("run_id") or f"{domain}-{timestamp_slug()}")
    executor = str(payload.get("executor") or config.executor)
    model = str(payload.get("model") or config.model)
    provider = str(payload.get("codex_provider") or payload.get("provider") or config.codex_provider)
    inputs_json = payload.get("inputs_json", "")
    if isinstance(inputs_json, dict):
        inputs_json = json.dumps(inputs_json, ensure_ascii=False)
    inputs_json = str(inputs_json or "")

    repo_root = Path(config.repo_root).resolve()
    runs_dir = Path(payload.get("runs_dir") or config.runs_dir)
    if not runs_dir.is_absolute():
        runs_dir = repo_root / runs_dir
    runs_dir = runs_dir.resolve()
    domains_dir = Path(config.domains_dir)
    if not domains_dir.is_absolute():
        domains_dir = repo_root / domains_dir
    domains_dir = domains_dir.resolve()
    run_dir = ensure_dir(_safe_run_dir(runs_dir, run_id))
    command = [
        sys.executable,
        "-m",
        "growth_dev.cli",
        "team",
        "run",
        "--run-id",
        run_id,
        "--brief",
        brief,
        "--domain",
        domain,
        "--domains-dir",
        str(domains_dir),
        "--runs-dir",
        str(runs_dir),
        "--inputs-json",
        inputs_json,
        "--executor",
        executor,
        "--model",
        model,
        "--reasoning-effort",
        str(payload.get("reasoning_effort") or config.reasoning_effort),
        "--codex-binary",
        str(payload.get("codex_binary") or config.codex_binary),
        "--codex-provider",
        provider,
        "--env-file",
        str(payload.get("env_file") or config.env_file),
        "--repo-root",
        str(repo_root),
        "--planning-mode",
        str(payload.get("planning_mode") or config.planning_mode),
        "--requirements-model",
        str(payload.get("requirements_model") or config.requirements_model),
        "--requirements-reasoning-effort",
        str(payload.get("requirements_reasoning_effort") or config.requirements_reasoning_effort),
    ]
    process_record = {
        "run_id": run_id,
        "pid": 0,
        "status": "starting",
        "started_at": now_iso(),
        "last_seen_at": now_iso(),
        "command": _redacted_command(command),
        "run_dir": str(run_dir),
    }
    write_json(run_dir / "process.json", process_record)
    stdout_handle = (run_dir / "background_stdout.log").open("a", encoding="utf-8")
    stderr_handle = (run_dir / "background_stderr.log").open("a", encoding="utf-8")
    try:
        process = subprocess.Popen(
            command,
            cwd=repo_root,
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
            start_new_session=True,
        )
    finally:
        stdout_handle.close()
        stderr_handle.close()
    process_record.update({"pid": process.pid, "status": "running", "last_seen_at": now_iso()})
    write_json(run_dir / "process.json", process_record)
    _DASHBOARD_PROCESSES.append(process)
    if executor == "deterministic":
        try:
            exit_code = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        else:
            process_record.update(
                {
                    "status": "completed" if exit_code == 0 else "failed",
                    "exit_code": exit_code,
                    "last_seen_at": now_iso(),
                }
            )
            write_json(run_dir / "process.json", process_record)
    return _redact(
        {
            "run_id": run_id,
            "pid": process.pid,
            "status": "running",
            "watch": f"python -m growth_dev.cli team watch --run-id {run_id}",
            "artifacts": str(run_dir),
        }
    )


def start_dashboard_acceptance(run_id: str, *, runs_dir: Path = Path("runs"), repo_root: Path = Path(".")) -> dict[str, Any]:
    runs_dir = Path(runs_dir).resolve()
    repo_root = Path(repo_root).resolve()
    run_dir = _safe_run_dir(runs_dir, run_id)
    if not run_dir.exists():
        raise FileNotFoundError(f"Run not found: {run_id}")
    record = _safe_read_json(run_dir / "team_run_record.json")
    apply_status, apply_reason = _apply_gate(record)
    if apply_status != "passed":
        raise ValueError(apply_reason)

    status = _read_acceptance_status(run_dir)
    if status.get("status") in {"queued", "running", "completed", "failed"}:
        return status

    status = _initial_acceptance_status(run_id, runs_dir, repo_root)
    _write_acceptance_status(run_dir, status)
    thread = threading.Thread(
        target=run_dashboard_acceptance_once,
        kwargs={"run_id": run_id, "runs_dir": runs_dir, "repo_root": repo_root},
        daemon=True,
    )
    thread.start()
    _ACCEPTANCE_THREADS.append(thread)
    return _redact(status)


def run_dashboard_acceptance_once(
    run_id: str,
    *,
    runs_dir: Path = Path("runs"),
    repo_root: Path = Path("."),
    command_runner: Any = subprocess.run,
) -> dict[str, Any]:
    runs_dir = Path(runs_dir).resolve()
    repo_root = Path(repo_root).resolve()
    run_dir = _safe_run_dir(runs_dir, run_id)
    if not run_dir.exists():
        raise FileNotFoundError(f"Run not found: {run_id}")
    record = _safe_read_json(run_dir / "team_run_record.json")
    apply_status, apply_reason = _apply_gate(record)
    if apply_status != "passed":
        raise ValueError(apply_reason)

    status = _initial_acceptance_status(run_id, runs_dir, repo_root)
    status.update({"status": "running", "current_step": "apply", "started_at": now_iso(), "summary": "正在应用代码变更。"})
    _mark_acceptance_step_running(status, "apply")
    _write_acceptance_status(run_dir, status)

    apply_command = [
        "python3",
        "-m",
        "growth_dev.cli",
        "team",
        "apply",
        "--run-id",
        run_id,
        "--runs-dir",
        str(runs_dir),
        "--repo-root",
        str(repo_root),
    ]
    apply_result = _run_acceptance_command(
        command_runner,
        apply_command,
        cwd=repo_root,
        stdout_path=run_dir / "acceptance" / "apply_stdout.log",
        stderr_path=run_dir / "acceptance" / "apply_stderr.log",
    )
    _update_acceptance_step(status, "apply", apply_result)
    if apply_result.returncode != 0:
        status.update(
            {
                "status": "failed",
                "current_step": "apply",
                "finished_at": now_iso(),
                "applied": False,
                "conclusion": "采纳失败，代码变更未完成应用。",
                "next_action": "请查看 apply 日志，处理冲突或缺失后重新确认采纳。",
                "summary": "采纳失败。",
            }
        )
        _write_acceptance_status(run_dir, status)
        return _redact(status)

    status.update({"applied": True, "current_step": "tests", "summary": "代码已应用，正在运行全量测试。"})
    _mark_acceptance_step_running(status, "tests")
    _write_acceptance_status(run_dir, status)
    tests_command = ["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]
    tests_result = _run_acceptance_command(
        command_runner,
        tests_command,
        cwd=repo_root,
        stdout_path=run_dir / "acceptance" / "tests_stdout.log",
        stderr_path=run_dir / "acceptance" / "tests_stderr.log",
    )
    _update_acceptance_step(status, "tests", tests_result)
    if tests_result.returncode != 0:
        status.update(
            {
                "status": "failed",
                "current_step": "tests",
                "finished_at": now_iso(),
                "conclusion": "已采纳但测试失败，需修复后再验证。",
                "next_action": "变更已保留，不自动回滚。请修复失败用例后运行 python3 -m unittest discover -s tests -v。",
                "summary": "代码已应用，但全量测试未通过。",
            }
        )
        _write_acceptance_status(run_dir, status)
        return _redact(status)

    status.update(
        {
            "status": "completed",
            "current_step": "completed",
            "finished_at": now_iso(),
            "conclusion": "已采纳且测试通过。",
            "next_action": "可以继续人工检查、提交或进入后续发布流程。",
            "summary": "代码已应用，全量测试通过。",
        }
    )
    _write_acceptance_status(run_dir, status)
    return _redact(status)


def create_dashboard_handler(config: DashboardConfig) -> type[BaseHTTPRequestHandler]:
    config.repo_root = Path(config.repo_root).resolve()
    config.runs_dir = _resolve_under(config.repo_root, config.runs_dir)
    config.domains_dir = _resolve_under(config.repo_root, config.domains_dir)
    config.dashboard_dir = _resolve_under(config.repo_root, config.dashboard_dir)

    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "GrowthDevDashboard/1.0"

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            try:
                if path == "/api/runs":
                    self._send_json({"runs": list_dashboard_runs(config.runs_dir)})
                    return
                if path.startswith("/api/runs/"):
                    self._handle_run_get(path, parsed.query)
                    return
                self._serve_static(path)
            except FileNotFoundError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except Exception as exc:  # noqa: BLE001 - dashboard should return a visible failure.
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            parsed = urlparse(self.path)
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "acceptance":
                try:
                    self._send_json(
                        start_dashboard_acceptance(parts[2], runs_dir=config.runs_dir, repo_root=config.repo_root),
                        status=HTTPStatus.ACCEPTED,
                    )
                except FileNotFoundError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                except Exception as exc:  # noqa: BLE001 - dashboard should return a visible failure.
                    self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if len(parts) == 5 and parts[:2] == ["api", "runs"] and parts[3:] == ["release", "readiness"]:
                try:
                    self._send_json(
                        generate_release_readiness(parts[2], runs_dir=config.runs_dir, repo_root=config.repo_root),
                        status=HTTPStatus.OK,
                    )
                except FileNotFoundError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                except Exception as exc:  # noqa: BLE001 - dashboard should return a visible failure.
                    self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if len(parts) == 5 and parts[:2] == ["api", "runs"] and parts[3:] == ["pr", "draft"]:
                try:
                    self._send_json(
                        create_draft_pr(parts[2], runs_dir=config.runs_dir, repo_root=config.repo_root, base="main", push=True),
                        status=HTTPStatus.ACCEPTED,
                    )
                except FileNotFoundError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                except Exception as exc:  # noqa: BLE001 - dashboard should return a visible failure.
                    self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if len(parts) == 5 and parts[:2] == ["api", "runs"] and parts[3:] == ["pr", "status"]:
                try:
                    self._send_json(
                        refresh_ci_status(parts[2], runs_dir=config.runs_dir, repo_root=config.repo_root),
                        status=HTTPStatus.OK,
                    )
                except FileNotFoundError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                except Exception as exc:  # noqa: BLE001 - dashboard should return a visible failure.
                    self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "staging-readiness":
                try:
                    self._send_json(
                        generate_staging_readiness(parts[2], runs_dir=config.runs_dir),
                        status=HTTPStatus.OK,
                    )
                except FileNotFoundError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                except Exception as exc:  # noqa: BLE001 - dashboard should return a visible failure.
                    self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "staging-rehearsal":
                try:
                    self._send_json(
                        run_staging_rehearsal(parts[2], runs_dir=config.runs_dir, repo_root=config.repo_root),
                        status=HTTPStatus.OK,
                    )
                except FileNotFoundError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                except Exception as exc:  # noqa: BLE001 - dashboard should return a visible failure.
                    self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "production-readiness":
                try:
                    self._send_json(
                        generate_production_readiness(parts[2], runs_dir=config.runs_dir),
                        status=HTTPStatus.OK,
                    )
                except FileNotFoundError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                except Exception as exc:  # noqa: BLE001 - dashboard should return a visible failure.
                    self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if parsed.path != "/api/runs":
                self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length") or "0")
                raw = self.rfile.read(length).decode("utf-8") if length else "{}"
                payload = json.loads(raw or "{}")
                if not isinstance(payload, dict):
                    raise ValueError("JSON object is required")
                self._send_json(start_dashboard_run(config, payload), status=HTTPStatus.ACCEPTED)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except Exception as exc:  # noqa: BLE001 - dashboard should return a visible failure.
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
            return

        def _handle_run_get(self, path: str, query: str) -> None:
            parts = [part for part in path.split("/") if part]
            if len(parts) < 3:
                self._send_json({"error": "Run id is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            run_id = parts[2]
            if len(parts) == 3:
                self._send_json(build_dashboard_state(run_id, runs_dir=config.runs_dir, repo_root=config.repo_root))
                return
            if len(parts) == 4 and parts[3] == "artifact":
                params = parse_qs(query)
                artifact_path = (params.get("path") or [""])[0]
                scope = (params.get("scope") or ["run"])[0]
                self._send_json(read_dashboard_artifact(run_id, artifact_path, runs_dir=config.runs_dir, repo_root=config.repo_root, scope=scope))
                return
            if len(parts) == 4 and parts[3] == "diff":
                self._send_text(_read_diff(_safe_run_dir(config.runs_dir, run_id)), content_type="text/plain; charset=utf-8")
                return
            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

        def _serve_static(self, path: str) -> None:
            relative = "index.html" if path in {"", "/"} else path.lstrip("/")
            target = _safe_child(config.dashboard_dir.resolve(), relative)
            if target.is_dir():
                target = target / "index.html"
            if not target.exists() or not target.is_file():
                raise FileNotFoundError(f"Static asset not found: {relative}")
            content_type = _content_type(target)
            if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
                self._send_text(target.read_text(encoding="utf-8"), content_type=f"{content_type}; charset=utf-8")
            else:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.end_headers()
                self.wfile.write(target.read_bytes())

        def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            data = json.dumps(_redact(payload), ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_text(self, text: str, *, content_type: str) -> None:
            data = text.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return DashboardHandler


def run_dashboard_server(config: DashboardConfig, *, open_browser: bool = False) -> None:
    handler = create_dashboard_handler(config)
    server = ThreadingHTTPServer((config.host, config.port), handler)
    url = f"http://{config.host}:{server.server_address[1]}"
    print(f"Agent Team Dashboard running at {url}")
    print(f"Artifacts: {Path(config.runs_dir).resolve()}/")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _build_stage_view(agent_by_id: dict[str, dict[str, Any]], record: dict[str, Any]) -> list[dict[str, Any]]:
    status = str(record.get("status", "starting"))
    stages: list[dict[str, Any]] = []
    for definition in STAGE_DEFINITIONS:
        stage_id = definition["id"]
        agent = agent_by_id.get(stage_id)
        if agent:
            stage_status = str(agent.get("status", "unknown"))
            message = str(agent.get("message", ""))
            started_at = str(agent.get("started_at", ""))
            finished_at = str(agent.get("finished_at", ""))
            risk_events = [str(item) for item in agent.get("risk_events", [])]
            outputs = [str(item) for item in agent.get("output_paths", [])]
        elif stage_id in {"ci", "deploy", "human_approval"}:
            stage_status = "planned"
            message = "Reserved for Week 4 integration."
            started_at = ""
            finished_at = ""
            risk_events = []
            outputs = []
        else:
            stage_status = "pending" if status in {"starting", "running", "pending"} else "not_run"
            message = ""
            started_at = ""
            finished_at = ""
            risk_events = []
            outputs = []
        stages.append(
            {
                **definition,
                "status": stage_status,
                "message": message,
                "started_at": started_at,
                "finished_at": finished_at,
                "risk_events": risk_events,
                "outputs": outputs,
            }
        )
    return stages


def _build_gate_view(record: dict[str, Any]) -> list[dict[str, Any]]:
    gates: list[dict[str, Any]] = []
    for gate in record.get("gate_results", []):
        if not isinstance(gate, dict):
            continue
        gate_id = str(gate.get("gate_id", ""))
        gates.append(
            {
                "id": gate_id,
                "label": gate_id.replace("_", " ").title(),
                "status": str(gate.get("status", "unknown")),
                "required_artifacts": [str(item) for item in gate.get("required_artifacts", [])],
                "missing_artifacts": [str(item) for item in gate.get("missing_artifacts", [])],
                "before_agent": str(gate.get("before_agent", "")),
                "checked_at": str(gate.get("checked_at", "")),
            }
        )
    return gates


def _build_artifact_view(run_dir: Path, repo_root: Path, record: dict[str, Any]) -> list[dict[str, Any]]:
    declared = dict(record.get("artifacts") or {})
    ordered = [
        ("task_workspace.md", "Task Workspace", "run"),
        ("task_workspace.json", "Task Workspace JSON", "run"),
        ("task_journal.md", "Task Journal", "run"),
        ("task_journal.jsonl", "Task Journal JSONL", "run"),
        ("tool_context/codex.md", "Codex Tool Context", "run"),
        ("task.yaml", "Task Package", "run"),
        ("context.md", "Context", "run"),
        ("requirements/brief_analysis.json", "Requirement Analysis", "run"),
        ("requirements/requirement_understanding.candidate.json", "Requirement Understanding Candidate", "run"),
        ("requirements/requirement_quality_report.json", "Requirement Quality Report", "run"),
        ("requirements/clarification.md", "Requirement Clarification", "run"),
        ("requirements/prd.draft.md", "PM PRD Draft", "run"),
        ("requirements/user_stories.draft.md", "User Stories Draft", "run"),
        ("requirements/prd_red_team.md", "PRD Red-Team Draft", "run"),
        ("requirements/acceptance_criteria.draft.md", "Draft Acceptance Criteria", "run"),
        ("requirements/open_questions.md", "Open Questions", "run"),
        ("requirements/assumptions.md", "Assumptions", "run"),
        ("requirements/capability_boundary.md", "Capability Boundary", "run"),
        ("requirements/capability_boundary.json", "Capability Boundary JSON", "run"),
        ("acceptance_criteria.md", "Acceptance Criteria", "run"),
        ("context_pack.md", "Context Pack", "run"),
        ("planning/acceptance_coverage_matrix.md", "Acceptance Coverage Matrix", "run"),
        ("planning/acceptance_coverage_matrix.json", "Acceptance Coverage Matrix JSON", "run"),
        ("planning/test_scenarios.draft.md", "PM Test Scenarios Draft", "run"),
        ("planning/tdd_plan.md", "TDD Plan", "run"),
        ("planning/tdd_plan.json", "TDD Plan JSON", "run"),
        ("planning/planning_quality_report.json", "Planning Quality Report", "run"),
        ("prd.md", "PRD", "run"),
        ("tech_spec.md", "Tech Spec", "run"),
        ("architecture_diagram.md", "Architecture Diagram", "run"),
        ("AGENTS.md", "AGENTS.md", "repo"),
        ("ui_spec.md", "UI Spec", "run"),
        ("eval.md", "Eval / TDD", "run"),
        ("coding_prompt.md", "Coding Prompt", "run"),
        ("codex/implementation_trace.json", "Implementation Trace", "run"),
        ("codex/failure_classification.md", "Failure Classification", "run"),
        ("codex/failure_classification.json", "Failure Classification JSON", "run"),
        ("codex/slice_loop_state.json", "Slice Loop State", "run"),
        ("implementation_completion_gate.md", "Implementation Completion Gate", "run"),
        ("implementation_completion_gate.json", "Implementation Completion Gate JSON", "run"),
        ("codex/diff.patch", "Diff Evidence", "run"),
        ("review_report.md", "Review Report", "run"),
        ("test_report.md", "Test Report", "run"),
        ("final_report.md", "Final Report", "run"),
        ("memory_recall.md", "Historical Task Recall", "run"),
        ("memory_recall.json", "Memory Recall JSON", "run"),
        ("retrospective.md", "Run Retrospective", "run"),
        ("learning_summary.json", "Learning Summary", "run"),
        ("finish_learning_suggestions.md", "Finish Learning Suggestions", "run"),
        ("finish_learning_suggestions.json", "Finish Learning Suggestions JSON", "run"),
        ("release_readiness.md", "Release Readiness", "run"),
        ("release_readiness.json", "Release Readiness JSON", "run"),
        ("pr_draft.md", "PR Draft", "run"),
        ("github_pr.md", "GitHub Draft PR", "run"),
        ("github_pr.json", "GitHub Draft PR JSON", "run"),
        ("ci_status.md", "CI Status", "run"),
        ("ci_status.json", "CI Status JSON", "run"),
        ("staging_readiness.md", "Staging Readiness", "run"),
        ("staging_readiness.json", "Staging Readiness JSON", "run"),
        ("staging_rehearsal.md", "Staging Rehearsal", "run"),
        ("staging_rehearsal.json", "Staging Rehearsal JSON", "run"),
        ("production_readiness.md", "Production Readiness", "run"),
        ("production_readiness.json", "Production Readiness JSON", "run"),
        ("deployment_runbook.md", "Deployment Runbook", "run"),
    ]
    seen: set[tuple[str, str]] = set()
    artifacts: list[dict[str, Any]] = []
    for path, label, scope in ordered:
        actual = declared.get(Path(path).name, path)
        item = _artifact_item(label, str(actual), scope, run_dir, repo_root)
        artifacts.append(item)
        seen.add((item["scope"], item["path"]))
    for name, path in declared.items():
        key = ("run", str(path))
        if key in seen:
            continue
        artifacts.append(_artifact_item(str(name), str(path), "run", run_dir, repo_root))
    return artifacts


def _artifact_item(label: str, path: str, scope: str, run_dir: Path, repo_root: Path) -> dict[str, Any]:
    exists = (repo_root / path).exists() if scope == "repo" else (run_dir / path).exists()
    return {"label": label, "path": path, "scope": scope, "exists": exists}


def _read_events(run_dir: Path) -> list[dict[str, Any]]:
    events_path = run_dir / "events.jsonl"
    if not events_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in events_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(_redact(payload))
    return events


def _background_failure(run_dir: Path, record: dict[str, Any], process: dict[str, Any]) -> dict[str, str] | None:
    status = str(record.get("status", process.get("status", "")))
    if status not in {"running", "starting"}:
        return None
    stderr_path = run_dir / "background_stderr.log"
    if not stderr_path.exists():
        return None
    stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
    if "PermissionError" in stderr_text or "Operation not permitted" in stderr_text:
        return {"status": "failed", "failure_category": "permission_error", "risk_event": "permission_error"}
    return None


def _failure_category(record: dict[str, Any]) -> str:
    for agent_run in reversed([item for item in record.get("agent_runs", []) if isinstance(item, dict)]):
        metadata = agent_run.get("metadata") if isinstance(agent_run.get("metadata"), dict) else {}
        failure_category = metadata.get("failure_category")
        if failure_category:
            return str(failure_category)
    return ""


def _latest_log_lines(run_dir: Path, max_lines: int = 12) -> list[str]:
    return summarize_run_logs(run_dir, max_lines=max_lines)


def _read_implementation_trace(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "codex" / "implementation_trace.json"
    if not path.exists():
        return {}
    payload = _safe_read_json(path)
    return payload if isinstance(payload, dict) else {}


def _read_failure_classification(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "codex" / "failure_classification.json"
    if not path.exists():
        return {}
    payload = _safe_read_json(path)
    return _redact(payload) if isinstance(payload, dict) else {}


def _read_requirement_understanding(run_dir: Path) -> dict[str, Any]:
    analysis = _safe_read_json(run_dir / "requirements" / "brief_analysis.json")
    candidate = _safe_read_json(run_dir / "requirements" / "requirement_understanding.candidate.json")
    quality = _safe_read_json(run_dir / "requirements" / "requirement_quality_report.json")
    capability_boundary = _safe_read_json(run_dir / "requirements" / "capability_boundary.json")
    return _redact(
        {
            "brief_analysis": analysis if isinstance(analysis, dict) else {},
            "candidate": candidate if isinstance(candidate, dict) else {},
            "quality_report": quality if isinstance(quality, dict) else {},
            "capability_boundary": capability_boundary if isinstance(capability_boundary, dict) else {},
            "draft_artifacts": {
                "requirement_candidate": (run_dir / "requirements" / "requirement_understanding.candidate.json").exists(),
                "clarification": (run_dir / "requirements" / "clarification.md").exists(),
                "pm_prd_draft": (run_dir / "requirements" / "prd.draft.md").exists(),
                "user_stories_draft": (run_dir / "requirements" / "user_stories.draft.md").exists(),
                "prd_red_team": (run_dir / "requirements" / "prd_red_team.md").exists(),
                "acceptance_criteria_draft": (run_dir / "requirements" / "acceptance_criteria.draft.md").exists(),
                "open_questions": (run_dir / "requirements" / "open_questions.md").exists(),
                "assumptions": (run_dir / "requirements" / "assumptions.md").exists(),
                "capability_boundary": (run_dir / "requirements" / "capability_boundary.json").exists(),
            },
        }
    )


def _read_acceptance_coverage(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "planning" / "acceptance_coverage_matrix.json"
    if not path.exists():
        return {}
    payload = _safe_read_json(path)
    return _redact(payload) if isinstance(payload, dict) else {}


def _read_tdd_plan(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "planning" / "tdd_plan.json"
    if not path.exists():
        return {}
    payload = _safe_read_json(path)
    return _redact(payload) if isinstance(payload, dict) else {}


def _read_slice_loop_state(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "codex" / "slice_loop_state.json"
    if not path.exists():
        return {}
    payload = _safe_read_json(path)
    return _redact(payload) if isinstance(payload, dict) else {}


def _read_implementation_completion_gate(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "implementation_completion_gate.json"
    if not path.exists():
        return {}
    payload = _safe_read_json(path)
    return _redact(payload) if isinstance(payload, dict) else {}


def _read_task_workspace(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "task_workspace.json"
    if not path.exists():
        return {}
    payload = _safe_read_json(path)
    return _redact(payload) if isinstance(payload, dict) else {}


def _read_task_journal(run_dir: Path, *, limit: int = 40) -> dict[str, Any]:
    path = run_dir / "task_journal.jsonl"
    if not path.exists():
        return {"events": []}
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(_redact(payload))
    return {"events": events[-limit:]}


def _read_memory_recall(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "memory_recall.json"
    if not path.exists():
        return {}
    payload = _safe_read_json(path)
    return _redact(payload) if isinstance(payload, dict) else {}


def _read_release_readiness(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "release_readiness.json"
    if not path.exists():
        return {}
    payload = _safe_read_json(path)
    return _redact(payload) if isinstance(payload, dict) else {}


def _read_github_pr(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "github_pr.json"
    if not path.exists():
        return {"schema_version": 1, "status": "not_started", "pr": {}, "warnings": [], "blockers": []}
    payload = _safe_read_json(path)
    return _redact(payload) if isinstance(payload, dict) else {"schema_version": 1, "status": "not_started", "pr": {}, "warnings": [], "blockers": []}


def _read_ci_status(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "ci_status.json"
    if not path.exists():
        return {"schema_version": 1, "status": "not_started", "checks": [], "warnings": [], "blockers": []}
    payload = _safe_read_json(path)
    return _redact(payload) if isinstance(payload, dict) else {"schema_version": 1, "status": "not_started", "checks": [], "warnings": [], "blockers": []}


def _read_staging_readiness(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "staging_readiness.json"
    if not path.exists():
        return {}
    payload = _safe_read_json(path)
    return _redact(payload) if isinstance(payload, dict) else {}


def _read_staging_rehearsal(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "staging_rehearsal.json"
    if not path.exists():
        return {"schema_version": 1, "status": "not_started", "steps": [], "blockers": [], "warnings": [], "next_actions": []}
    payload = _safe_read_json(path)
    return _redact(payload) if isinstance(payload, dict) else {"schema_version": 1, "status": "not_started", "steps": [], "blockers": [], "warnings": [], "next_actions": []}


def _read_production_readiness(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "production_readiness.json"
    if not path.exists():
        return {}
    payload = _safe_read_json(path)
    return _redact(payload) if isinstance(payload, dict) else {}


def _ci_gate_view(ci_status: dict[str, Any]) -> dict[str, str]:
    status = str(ci_status.get("status", "not_started")) if ci_status else "not_started"
    if status == "passed":
        return {"id": "ci_gate", "label": "CI Gate", "status": "passed", "reason": str(ci_status.get("summary", "CI checks passed."))}
    if status == "failed":
        return {"id": "ci_gate", "label": "CI Gate", "status": "blocked", "reason": str(ci_status.get("summary", "CI checks failed."))}
    if status in {"running", "pending", "unknown"}:
        return {"id": "ci_gate", "label": "CI Gate", "status": "warning", "reason": str(ci_status.get("summary", "CI checks are not complete."))}
    return {"id": "ci_gate", "label": "CI Gate", "status": "planned", "reason": "Reserved for GitHub Actions integration."}


def _deploy_gate_view(staging_readiness: dict[str, Any]) -> dict[str, str]:
    decision = str(staging_readiness.get("staging_decision", ""))
    if decision == "ready_for_staging":
        return {"id": "deploy_gate", "label": "Deploy Gate", "status": "passed", "reason": str(staging_readiness.get("summary", "Ready for staging."))}
    if decision == "waiting_for_ci":
        return {"id": "deploy_gate", "label": "Deploy Gate", "status": "warning", "reason": str(staging_readiness.get("summary", "Waiting for CI."))}
    if decision == "blocked":
        return {"id": "deploy_gate", "label": "Deploy Gate", "status": "blocked", "reason": str(staging_readiness.get("summary", "Staging is blocked."))}
    return {"id": "deploy_gate", "label": "Deploy Gate", "status": "planned", "reason": "Reserved for staging deploy integration."}


def _production_gate_view(production_readiness: dict[str, Any]) -> dict[str, str]:
    decision = str(production_readiness.get("production_decision", ""))
    if decision == "ready_for_manual_production":
        return {"id": "human_release_gate", "label": "Human Release Gate", "status": "passed", "reason": str(production_readiness.get("summary", "Ready for manual production confirmation."))}
    if decision == "waiting_for_manual_check":
        return {"id": "human_release_gate", "label": "Human Release Gate", "status": "warning", "reason": str(production_readiness.get("summary", "Waiting for manual production evidence."))}
    if decision == "blocked":
        return {"id": "human_release_gate", "label": "Human Release Gate", "status": "blocked", "reason": str(production_readiness.get("summary", "Production readiness is blocked."))}
    return {"id": "human_release_gate", "label": "Human Release Gate", "status": "planned", "reason": "Reserved for production approval."}


def _read_acceptance_status(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "acceptance" / "status.json"
    if not path.exists():
        return {"schema_version": 1, "status": "not_started", "steps": [], "applied": False}
    payload = _safe_read_json(path)
    return _redact(payload) if isinstance(payload, dict) else {"schema_version": 1, "status": "not_started", "steps": [], "applied": False}


def _initial_acceptance_status(run_id: str, runs_dir: Path, repo_root: Path) -> dict[str, Any]:
    apply_command = f"python3 -m growth_dev.cli team apply --run-id {run_id}"
    tests_command = "python3 -m unittest discover -s tests -v"
    return {
        "schema_version": 1,
        "run_id": run_id,
        "status": "queued",
        "current_step": "queued",
        "started_at": "",
        "finished_at": "",
        "applied": False,
        "summary": "等待确认采纳。",
        "conclusion": "",
        "next_action": "确认后会应用代码变更并运行全量测试。",
        "commands": {
            "apply": apply_command,
            "tests": tests_command,
        },
        "steps": [
            _acceptance_step("apply", "应用代码变更", apply_command, "acceptance/apply_stdout.log", "acceptance/apply_stderr.log"),
            _acceptance_step("tests", "运行全量测试", tests_command, "acceptance/tests_stdout.log", "acceptance/tests_stderr.log"),
        ],
        "metadata": {
            "runs_dir": str(runs_dir),
            "repo_root": str(repo_root),
            "rollback_policy": "not_automatic",
        },
    }


def _acceptance_step(step_id: str, title: str, command: str, stdout_path: str, stderr_path: str) -> dict[str, Any]:
    return {
        "id": step_id,
        "title": title,
        "status": "queued",
        "command": command,
        "exit_code": None,
        "started_at": "",
        "finished_at": "",
        "stdout_tail": [],
        "stderr_tail": [],
        "log_paths": {"stdout": stdout_path, "stderr": stderr_path},
    }


def _write_acceptance_status(run_dir: Path, status: dict[str, Any]) -> None:
    acceptance_dir = ensure_dir(run_dir / "acceptance")
    write_json(acceptance_dir / "status.json", _redact(status))


def _run_acceptance_command(
    command_runner: Any,
    command: list[str],
    *,
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
) -> subprocess.CompletedProcess[str]:
    ensure_dir(stdout_path.parent)
    completed = command_runner(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    stdout_path.write_text(_redact_text(str(completed.stdout or "")), encoding="utf-8")
    stderr_path.write_text(_redact_text(str(completed.stderr or "")), encoding="utf-8")
    return completed


def _update_acceptance_step(status: dict[str, Any], step_id: str, completed: subprocess.CompletedProcess[str]) -> None:
    now = now_iso()
    step = next((item for item in status.get("steps", []) if isinstance(item, dict) and item.get("id") == step_id), None)
    if not step:
        return
    step["status"] = "completed" if completed.returncode == 0 else "failed"
    step["exit_code"] = completed.returncode
    step["finished_at"] = now
    if not step.get("started_at"):
        step["started_at"] = now
    stdout_path = step.get("log_paths", {}).get("stdout", "") if isinstance(step.get("log_paths"), dict) else ""
    stderr_path = step.get("log_paths", {}).get("stderr", "") if isinstance(step.get("log_paths"), dict) else ""
    run_dir = Path(str(status.get("metadata", {}).get("runs_dir", ""))) / str(status.get("run_id", ""))
    if stdout_path:
        target = run_dir / stdout_path
        if target.exists():
            step["stdout_tail"] = _tail_lines(target, max_lines=12)
    if stderr_path:
        target = run_dir / stderr_path
        if target.exists():
            step["stderr_tail"] = _tail_lines(target, max_lines=12)


def _mark_acceptance_step_running(status: dict[str, Any], step_id: str) -> None:
    for step in status.get("steps", []):
        if not isinstance(step, dict):
            continue
        if step.get("id") == step_id:
            step["status"] = "running"
            step["started_at"] = now_iso()
        elif step.get("status") == "queued":
            step["status"] = "pending"


def _team_record_from_dashboard_payload(
    record: dict[str, Any],
    run_id: str,
    run_dir: Path,
    process: dict[str, Any],
    background_failure: dict[str, str] | None,
) -> TeamRunRecord:
    if record:
        payload = dict(record)
    else:
        payload = {
            "run_id": run_id,
            "domain_id": "",
            "brief": "",
            "status": str(process.get("status", "starting")),
            "run_dir": str(run_dir),
            "agent_runs": [],
            "risk_events": [],
        }
    if background_failure:
        payload["status"] = background_failure["status"]
        risk_events = [str(item) for item in payload.get("risk_events", [])]
        if background_failure["risk_event"] not in risk_events:
            risk_events.append(background_failure["risk_event"])
        payload["risk_events"] = risk_events
    return TeamRunRecord.from_dict(payload)


def _diff_summary(run_dir: Path) -> dict[str, Any]:
    diff = _read_diff(run_dir)
    return _parse_diff_summary(diff)


def _parse_diff_summary(diff: str) -> dict[str, Any]:
    lines = diff.splitlines()
    files: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_hunk = False

    def finish_current() -> None:
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

    for line in lines:
        if line.startswith("diff --git "):
            finish_current()
            old_path, new_path = _parse_diff_git_paths(line)
            current = {
                "path": new_path or old_path,
                "old_path": old_path,
                "new_path": new_path,
                "status": "modified",
                "additions": 0,
                "deletions": 0,
            }
            in_hunk = False
            continue

        if current is None:
            continue

        if line.startswith("new file mode"):
            current["status"] = "added"
            continue
        if line.startswith("deleted file mode"):
            current["status"] = "deleted"
            continue
        if line.startswith("rename from "):
            current["status"] = "renamed"
            current["old_path"] = line.removeprefix("rename from ").strip()
            continue
        if line.startswith("rename to "):
            current["status"] = "renamed"
            renamed_path = line.removeprefix("rename to ").strip()
            current["new_path"] = renamed_path
            current["path"] = renamed_path
            continue
        if line.startswith("--- "):
            old_path = _normalize_diff_path(line.removeprefix("--- "))
            if old_path == "/dev/null":
                current["status"] = "added"
            elif old_path:
                current["old_path"] = old_path
            continue
        if line.startswith("+++ "):
            new_path = _normalize_diff_path(line.removeprefix("+++ "))
            if new_path == "/dev/null":
                current["status"] = "deleted"
                current["path"] = current.get("old_path") or current.get("path") or ""
            elif new_path:
                current["new_path"] = new_path
                current["path"] = new_path
            continue
        if line.startswith("@@"):
            in_hunk = True
            continue

        if in_hunk and line.startswith("+") and not line.startswith("+++"):
            current["additions"] = int(current.get("additions") or 0) + 1
        elif in_hunk and line.startswith("-") and not line.startswith("---"):
            current["deletions"] = int(current.get("deletions") or 0) + 1

    finish_current()
    additions = sum(int(item.get("additions") or 0) for item in files)
    deletions = sum(int(item.get("deletions") or 0) for item in files)
    return {
        "lines": len(lines),
        "changed_files": [str(item.get("path", "")) for item in files],
        "files_changed": len(files),
        "additions": additions,
        "deletions": deletions,
        "files": files,
        "available": bool(diff.strip()),
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
        return path[2:]
    return path


def _read_diff(run_dir: Path) -> str:
    diff_path = run_dir / "codex" / "diff.patch"
    if diff_path.exists():
        return diff_path.read_text(encoding="utf-8", errors="replace")
    worktree = run_dir / "worktree"
    if not (worktree.exists() and ((worktree / ".git").exists() or (worktree / ".git").is_file())):
        return ""
    completed = subprocess.run(
        ["git", "diff", "--patch", "--binary"],
        cwd=worktree,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return completed.stdout if completed.returncode in {0, 1} else ""


def _apply_gate(record: dict[str, Any]) -> tuple[str, str]:
    run_id = str(record.get("run_id", ""))
    if record.get("status") != "completed":
        return "blocked", f"Run {run_id} is not completed."
    if record.get("risk_events"):
        return "blocked", "Risk events are present."
    verifier_runs = [item for item in record.get("agent_runs", []) if isinstance(item, dict) and item.get("agent_id") == "verifier"]
    if not verifier_runs or verifier_runs[-1].get("status") != "completed":
        return "blocked", "Verifier did not complete."
    if verifier_runs[-1].get("risk_events"):
        return "blocked", "Verifier risk events are present."
    return "passed", "Run completed, no risk events, verifier completed."


def _next_actions(run_id: str, status: str, apply_status: str) -> list[str]:
    actions = [f"python -m growth_dev.cli team status --run-id {run_id} --summary"]
    if status == "completed":
        actions.extend(
            [
                f"python -m growth_dev.cli team diff --run-id {run_id}",
                f"python -m growth_dev.cli review --run-id {run_id}",
                f"python -m growth_dev.cli test --run-id {run_id}",
                f"python -m growth_dev.cli report --run-id {run_id}",
            ]
        )
        if apply_status == "passed":
            actions.append(f"python -m growth_dev.cli team apply --run-id {run_id}")
    return actions


def _safe_child(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts or not str(candidate):
        raise ValueError("Artifact path must stay inside the allowed directory.")
    target = (root / candidate).resolve()
    root_resolved = root.resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise ValueError("Artifact path escapes the allowed directory.")
    return target


def _safe_run_dir(runs_dir: Path, run_id: str) -> Path:
    candidate = Path(str(run_id))
    if candidate.is_absolute() or len(candidate.parts) != 1 or not str(candidate):
        raise ValueError("Run id must identify one directory inside runs.")
    if candidate.name in {"", ".", ".."} or candidate.name != str(run_id):
        raise ValueError("Run id must identify one directory inside runs.")
    return _safe_child(Path(runs_dir).resolve(), candidate.name)


def _resolve_under(repo_root: Path, value: Path | str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _safe_read_json(path: Path) -> dict[str, Any]:
    try:
        payload = read_json(path)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _tail_lines(path: Path, max_lines: int = 5) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()][-max_lines:]


def _mtime_iso(path: Path) -> str:
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime))
    except OSError:
        return ""


def _content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".html": "text/html",
        ".css": "text/css",
        ".js": "application/javascript",
        ".json": "application/json",
        ".svg": "image/svg+xml",
        ".png": "image/png",
    }.get(suffix, "application/octet-stream")


def _redacted_command(command: list[str]) -> list[str]:
    redacted: list[str] = []
    skip_next = False
    for index, item in enumerate(command):
        if skip_next:
            skip_next = False
            continue
        if item == "--env-file" and index + 1 < len(command):
            redacted.extend([item, "<env-file>"])
            skip_next = True
        else:
            redacted.append(_redact_text(item))
    return redacted


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lower = key_text.lower()
            if lower in {"api_key", "apikey", "access_token", "refresh_token", "password", "token", "key"}:
                redacted[key_text] = "<redacted>"
            elif "secret" in lower and lower != "secret_configured":
                redacted[key_text] = "<redacted>"
            else:
                redacted[key_text] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_text(value: str) -> str:
    text = re.sub(r"sk-[A-Za-z0-9_\-]+", "<redacted>", value)
    text = text.replace(".env", "<env-file>")
    return text
