from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from ..utils import ensure_dir, now_iso, read_json, timestamp_slug, write_json


_DASHBOARD_PROCESSES: list[subprocess.Popen] = []


STAGE_DEFINITIONS = [
    {"id": "orchestrator", "label": "Orchestrator", "phase": "Plan", "artifact_hints": ["task.yaml", "context.md"]},
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
    run_dir = runs_dir / run_id
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
    gates.append({"id": "apply_gate", "label": "Apply Gate", "status": apply_status, "reason": apply_reason})
    gates.extend(
        [
            {"id": "ci_gate", "label": "CI Gate", "status": "planned", "reason": "Reserved for GitHub Actions integration."},
            {"id": "deploy_gate", "label": "Deploy Gate", "status": "planned", "reason": "Reserved for staging deploy integration."},
            {"id": "human_release_gate", "label": "Human Release Gate", "status": "planned", "reason": "Reserved for production approval."},
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
        run_dir = (runs_dir / run_id).resolve()
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
    run_dir = ensure_dir(runs_dir / run_id)
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
                self._send_text(_read_diff(config.runs_dir / run_id), content_type="text/plain; charset=utf-8")
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
        ("task.yaml", "Task Package", "run"),
        ("context.md", "Context", "run"),
        ("prd.md", "PRD", "run"),
        ("tech_spec.md", "Tech Spec", "run"),
        ("architecture_diagram.md", "Architecture Diagram", "run"),
        ("AGENTS.md", "AGENTS.md", "repo"),
        ("ui_spec.md", "UI Spec", "run"),
        ("eval.md", "Eval / TDD", "run"),
        ("coding_prompt.md", "Coding Prompt", "run"),
        ("codex/diff.patch", "Diff Evidence", "run"),
        ("review_report.md", "Review Report", "run"),
        ("test_report.md", "Test Report", "run"),
        ("final_report.md", "Final Report", "run"),
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
    paths = [
        run_dir / "background_stdout.log",
        run_dir / "background_stderr.log",
        run_dir / "codex" / "stdout.jsonl",
        run_dir / "codex" / "stderr.log",
        run_dir / "codex" / "reviewer_stdout.log",
        run_dir / "codex" / "reviewer_stderr.log",
    ]
    lines: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        for line in _tail_lines(path, max_lines=3):
            lines.append(f"{path.name}: {line}")
    return [_redact_text(line) for line in lines[-max_lines:]]


def _diff_summary(run_dir: Path) -> dict[str, Any]:
    diff = _read_diff(run_dir)
    changed_files = re.findall(r"^diff --git a/(.*?) b/", diff, flags=re.MULTILINE)
    return {"lines": len(diff.splitlines()), "changed_files": changed_files, "available": bool(diff.strip())}


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
