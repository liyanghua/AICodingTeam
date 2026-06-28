from __future__ import annotations

import json
import hashlib
import base64
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import parse_qs, quote, unquote, urlparse

from ..utils import ensure_dir, now_iso, read_json, timestamp_slug, write_json
from .models import TeamRunRecord
from .quality import evaluate_run_quality, summarize_run_health, summarize_run_logs
from .release import generate_production_readiness, generate_release_readiness, generate_staging_readiness
from .github_pr import create_draft_pr, refresh_ci_status
from .staging import run_staging_rehearsal
from . import preview


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


APP_GENERATION_DOMAIN_ID = "app_generation"
APP_GENERATION_WORKBENCH_NODES = [
    {
        "id": "skill_routing",
        "title": "Skill 路由",
        "summary": "选择 PRD 生成链路需要使用的 Project Skills。",
        "primary_skill": "using_agent_skills",
        "companion_skills": [],
        "inputs": ["input_prd.md", "domain_spec.json"],
        "outputs": ["requirements/brief_analysis.json", "memory_recall.json"],
        "agents": ["requirements"],
    },
    {
        "id": "prd_input",
        "title": "PRD 输入",
        "summary": "固化原始 PRD，校验 app_slug，并保留可审计输入。",
        "primary_skill": "spec_driven_development",
        "companion_skills": [],
        "inputs": [],
        "outputs": ["input_prd.md"],
        "agents": ["requirements"],
    },
    {
        "id": "prd_normalization",
        "title": "标准化 PRD",
        "summary": "把原始 PRD 规范化为目标、范围、状态和假设。",
        "primary_skill": "spec_driven_development",
        "companion_skills": ["context_engineering"],
        "inputs": ["input_prd.md"],
        "outputs": ["requirements/normalized_prd.md"],
        "agents": ["requirements"],
    },
    {
        "id": "context_contract",
        "title": "上下文与应用契约",
        "summary": "形成 Codex 可消费的上下文包和本地应用契约。",
        "primary_skill": "context_engineering",
        "companion_skills": [],
        "inputs": ["requirements/normalized_prd.md", "domain_spec.json"],
        "outputs": ["context_pack.md", "app_contract.json", "requirements/capability_boundary.json"],
        "agents": ["requirements"],
    },
    {
        "id": "planning_tdd",
        "title": "验收与 TDD 规划",
        "summary": "生成验收标准、coverage matrix、TDD 计划和 slices。",
        "primary_skill": "planning_and_task_breakdown",
        "companion_skills": ["test_driven_development"],
        "inputs": ["input_prd.md", "requirements/normalized_prd.md", "context_pack.md", "app_contract.json"],
        "outputs": ["acceptance_criteria.md", "planning/acceptance_coverage_matrix.json", "planning/tdd_plan.json"],
        "agents": ["requirements"],
    },
    {
        "id": "implementation",
        "title": "应用实现",
        "summary": "使用 Codex/LLM 在隔离 worktree 生成本地应用代码。",
        "primary_skill": "incremental_implementation",
        "companion_skills": [],
        "inputs": ["input_prd.md", "context_pack.md", "app_contract.json", "planning/tdd_plan.json"],
        "outputs": ["codex/implementation_trace.json", "codex/diff.patch", "code_run_record.json"],
        "agents": ["coder"],
    },
    {
        "id": "review_quality",
        "title": "评审与质量",
        "summary": "检查 diff、风险、路径边界和 AI coding 质量。",
        "primary_skill": "code_review_and_quality",
        "companion_skills": ["ai_coding_quality_review"],
        "inputs": ["codex/diff.patch", "code_run_record.json", "acceptance_criteria.md"],
        "outputs": ["review_report.md", "codex/failure_classification.json", "implementation_completion_gate.json"],
        "agents": ["reviewer"],
    },
    {
        "id": "verification",
        "title": "验证",
        "summary": "运行 Node 语法检查和项目测试，记录验证证据。",
        "primary_skill": "test_driven_development",
        "companion_skills": ["debugging_and_error_recovery"],
        "inputs": ["app_contract.json", "codex/diff.patch"],
        "outputs": ["test_report.md", "codex/verification_record.json"],
        "agents": ["verifier"],
    },
    {
        "id": "preview_delivery",
        "title": "预览与交付",
        "summary": "提供本地预览说明和最终交付结论。",
        "primary_skill": "code_review_and_quality",
        "companion_skills": ["run_retrospective"],
        "inputs": ["app_contract.json", "test_report.md", "codex/verification_record.json"],
        "outputs": ["preview_instructions.md", "final_report.md"],
        "agents": ["publisher"],
    },
]

APP_GENERATION_NODE_BY_ID = {item["id"]: item for item in APP_GENERATION_WORKBENCH_NODES}


APP_GENERATION_NODE_PHASE_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "skill_routing": [
        {"id": "select_skills", "label": "选择 Skill", "artifacts": ["requirements/brief_analysis.json", "memory_recall.json"]},
    ],
    "prd_input": [
        {"id": "persist_prd", "label": "固化 PRD", "artifacts": ["input_prd.md"]},
    ],
    "prd_normalization": [
        {"id": "normalize_prd", "label": "标准化 PRD", "artifacts": ["requirements/normalized_prd.md"]},
    ],
    "context_contract": [
        {"id": "context_pack", "label": "生成上下文包", "artifacts": ["context_pack.md"]},
        {"id": "app_contract", "label": "生成应用契约", "artifacts": ["app_contract.json"]},
        {"id": "capability_boundary", "label": "能力边界", "artifacts": ["requirements/capability_boundary.json"]},
        {"id": "benchmark_context", "label": "Benchmark 能力契约", "artifacts": ["benchmark_context.md", "reference_app_index.md"]},
    ],
    "planning_tdd": [
        {"id": "acceptance", "label": "验收标准", "artifacts": ["acceptance_criteria.md"]},
        {"id": "coverage_matrix", "label": "覆盖矩阵", "artifacts": ["planning/acceptance_coverage_matrix.json"]},
        {"id": "tdd_plan", "label": "TDD 计划", "artifacts": ["planning/tdd_plan.json"]},
    ],
    "review_quality": [
        {"id": "review_report", "label": "评审报告", "artifacts": ["review_report.md"]},
        {"id": "failure_classification", "label": "失败分类", "artifacts": ["codex/failure_classification.json"]},
        {"id": "completion_gate", "label": "完成门", "artifacts": ["implementation_completion_gate.json"]},
    ],
    "verification": [
        {"id": "test_report", "label": "测试报告", "artifacts": ["test_report.md"]},
        {"id": "verification_record", "label": "验证记录", "artifacts": ["codex/verification_record.json"]},
    ],
    "preview_delivery": [
        {"id": "preview_instructions", "label": "预览说明", "artifacts": ["preview_instructions.md"]},
        {"id": "final_report", "label": "最终交付", "artifacts": ["final_report.md"]},
    ],
}


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
    requirements_env_file: str = ""


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


def read_app_generation_artifact_preview(
    run_id: str,
    artifact_path: str,
    *,
    runs_dir: Path = Path("runs"),
    repo_root: Path = Path("."),
    max_bytes: int = 300_000,
) -> dict[str, Any]:
    run_dir = _safe_run_dir(Path(runs_dir), run_id)
    rel = Path(artifact_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("Artifact path escapes run directory.")
    if len(rel.parts) < 3 or rel.parts[0] != "artifacts":
        raise ValueError("file_preview can only read artifacts/<node>/* paths.")
    target = _safe_child(run_dir, artifact_path)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"Artifact not found: {artifact_path}")

    size = target.stat().st_size
    mime_type = _preview_mime_type(target)
    kind = _preview_kind(target, mime_type)
    preview = {
        "path": artifact_path,
        "scope": "run",
        "title": _artifact_title(artifact_path),
        "kind": "too_large" if size > max_bytes else kind,
        "mime_type": mime_type,
        "size_bytes": size,
        "content_hash": _file_hash(target),
        "inline": size <= max_bytes and kind in {"text", "code", "image", "pdf"},
        "content": "",
        "data_url": "",
        "message": "",
    }
    if size > max_bytes:
        preview["message"] = "文件超过预览大小限制，仅显示元信息。"
        return preview
    if kind in {"text", "code"}:
        preview["content"] = target.read_text(encoding="utf-8", errors="replace")
    elif kind in {"image", "pdf"}:
        data = base64.b64encode(target.read_bytes()).decode("ascii")
        preview["data_url"] = f"data:{mime_type};base64,{data}"
    else:
        preview["inline"] = False
        preview["message"] = "此文件类型暂不支持内联预览。"
    return preview


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
    requirements_env_file = str(payload.get("requirements_env_file") or config.requirements_env_file or "")
    if requirements_env_file:
        command.extend(["--requirements-env-file", requirements_env_file])
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


def list_app_generation_runs(runs_dir: Path = Path("runs"), limit: int = 50) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for run in list_dashboard_runs(runs_dir, limit=max(limit * 3, 60)):
        run_id = str(run.get("run_id", ""))
        if str(run.get("domain_id", "")) != APP_GENERATION_DOMAIN_ID:
            continue
        run_dir = _safe_run_dir(Path(runs_dir), run_id)
        record = _safe_read_json(run_dir / "team_run_record.json")
        process = _safe_read_json(run_dir / "process.json")
        inputs = record.get("inputs") if isinstance(record.get("inputs"), dict) else {}
        contract = _safe_read_json(run_dir / "app_contract.json")
        app_slug = str(inputs.get("app_slug") or contract.get("app_slug") or _slug_from_contract(contract))
        comparison_group_id = str(inputs.get("comparison_group_id") or f"cmp-{app_slug or run_id}")
        source_run_id = str(inputs.get("source_run_id") or "")
        rerun_from_node = str(inputs.get("rerun_from_node") or "")
        run.update(
            {
                "app_slug": app_slug,
                "executor": str(record.get("executor", "")),
                "comparison_group_id": comparison_group_id,
                "source_run_id": source_run_id,
                "rerun_from_node": rerun_from_node,
                "selected_variant": str(inputs.get("selected_variant") or "codex"),
                "is_rerun": bool(source_run_id or rerun_from_node),
                "updated_at": str(run.get("updated_at") or process.get("last_seen_at") or _mtime_iso(run_dir)),
                "publish_status": _app_generation_publish_status(run_dir, app_slug),
            }
        )
        runs.append(_redact(run))
    runs.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
    return runs[:limit]


def build_app_generation_nodes(
    run_id: str,
    *,
    runs_dir: Path = Path("runs"),
    repo_root: Path = Path("."),
) -> dict[str, Any]:
    runs_dir = Path(runs_dir).resolve()
    repo_root = Path(repo_root).resolve()
    run_dir = _safe_run_dir(runs_dir, run_id)
    if not run_dir.exists():
        raise FileNotFoundError(f"Run not found: {run_id}")
    record = _safe_read_json(run_dir / "team_run_record.json")
    if str(record.get("domain_id", "")) != APP_GENERATION_DOMAIN_ID:
        raise ValueError(f"Run is not app_generation: {run_id}")
    process = _safe_read_json(run_dir / "process.json")
    inputs = record.get("inputs") if isinstance(record.get("inputs"), dict) else {}
    contract = _safe_read_json(run_dir / "app_contract.json")
    comparison_group_id = str(inputs.get("comparison_group_id") or f"cmp-{str(inputs.get('app_slug') or contract.get('app_slug') or run_id)}")
    source_run_id = str(inputs.get("source_run_id") or "")
    nodes = [_build_app_generation_node(definition, run_dir, repo_root, record, process, comparison_group_id) for definition in APP_GENERATION_WORKBENCH_NODES]
    return _redact(
        {
            "schema_version": 1,
            "run": {
                "run_id": run_id,
                "domain_id": APP_GENERATION_DOMAIN_ID,
                "brief": str(record.get("brief", "")),
                "status": str(record.get("status", process.get("status", "unknown"))),
                "app_slug": str(inputs.get("app_slug") or contract.get("app_slug") or _slug_from_contract(contract)),
                "executor": str(record.get("executor", "")),
                "comparison_group_id": comparison_group_id,
                "source_run_id": source_run_id,
                "rerun_from_node": str(inputs.get("rerun_from_node") or ""),
                "selected_variant": str(inputs.get("selected_variant") or "codex"),
                "is_rerun": bool(source_run_id or inputs.get("rerun_from_node")),
                "publish_status": _app_generation_publish_status(
                    run_dir,
                    str(inputs.get("app_slug") or contract.get("app_slug") or _slug_from_contract(contract)),
                ),
            },
            "provider_statuses": _app_generation_provider_statuses(repo_root=repo_root),
            "nodes": nodes,
        }
    )


def build_app_generation_node_context(
    run_id: str,
    node_id: str,
    *,
    selected_variant: str = "codex",
    runs_dir: Path = Path("runs"),
    repo_root: Path = Path("."),
    user_overrides: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    run_dir = _safe_run_dir(Path(runs_dir).resolve(), run_id)
    state = build_app_generation_nodes(run_id, runs_dir=runs_dir, repo_root=repo_root)
    node = next((item for item in state.get("nodes", []) if item.get("id") == node_id), None)
    if not isinstance(node, dict):
        raise ValueError(f"Unknown app_generation node: {node_id}")
    run = state.get("run") if isinstance(state.get("run"), dict) else {}
    overrides = user_overrides or []
    base_context = {
        "schema_version": 1,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "comparison_group_id": str(run.get("comparison_group_id", "")),
        "source_run_id": str(run.get("source_run_id", "")),
        "node_id": node_id,
        "node_title": str(node.get("title") or APP_GENERATION_NODE_BY_ID.get(node_id, {}).get("title") or node_id),
        "node_summary": str(node.get("summary") or APP_GENERATION_NODE_BY_ID.get(node_id, {}).get("summary") or ""),
        "status": str(node.get("status") or "unknown"),
        "selected_variant": selected_variant,
        "app_slug": str(run.get("app_slug", "")),
        "brief": str(run.get("brief", "")),
        "inputs": node.get("inputs", []),
        "outputs": node.get("outputs", []),
        "skills": node.get("skills", []),
        "tool_calls": node.get("tool_calls", []),
        "usage": _variant_usage(node, selected_variant),
        "scores": node.get("scores", {}),
        "risks": node.get("risks", []),
        "user_overrides": overrides,
        "available_actions": _node_available_actions(node_id),
    }
    revision_payload = {
        "run_id": run_id,
        "node_id": node_id,
        "selected_variant": selected_variant,
        "inputs": _revision_artifacts(base_context["inputs"]),
        "outputs": _revision_artifacts(base_context["outputs"]),
        "skills": [{"id": item.get("id"), "status": item.get("status")} for item in base_context["skills"] if isinstance(item, dict)],
        "tool_calls": [{"tool_call_id": item.get("tool_call_id"), "status": item.get("status")} for item in base_context["tool_calls"] if isinstance(item, dict)],
        "risks": base_context["risks"],
        "user_overrides": overrides,
    }
    revision = "sha256:" + hashlib.sha256(json.dumps(revision_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    context_id = f"{run_id}:{node_id}:{selected_variant}:{revision}"
    return _redact({**base_context, "context_id": context_id, "context_revision": revision})


def handle_app_generation_agent_message(
    payload: dict[str, Any],
    *,
    runs_dir: Path = Path("runs"),
    repo_root: Path = Path("."),
) -> dict[str, Any]:
    context = payload.get("node_context")
    if not isinstance(context, dict):
        raise ValueError("node_context is required")
    provider = str(payload.get("provider") or "codex")
    mode = str(payload.get("mode") or "explain")
    intent = str(payload.get("intent") or mode or "auto")
    message = str(payload.get("message") or "")
    interaction_context = payload.get("interaction_context")
    if not isinstance(interaction_context, dict):
        interaction_context = None
    node_id = str(context.get("node_id") or "")
    run_id = str(context.get("run_id") or "")
    selected_variant = str(context.get("selected_variant") or "codex")
    if not run_id or not node_id:
        raise ValueError("node_context must include run_id and node_id")

    current_context = build_app_generation_node_context(
        run_id,
        node_id,
        selected_variant=selected_variant,
        runs_dir=runs_dir,
        repo_root=repo_root,
        user_overrides=context.get("user_overrides") if isinstance(context.get("user_overrides"), list) else None,
    )
    requested_revision = context.get("context_revision")
    interaction_revision = interaction_context.get("context_revision") if interaction_context else ""
    if (
        (requested_revision and requested_revision != current_context.get("context_revision"))
        or (interaction_revision and interaction_revision != current_context.get("context_revision"))
    ):
        return _redact(
            {
                "provider": provider,
                "status": "context_stale",
                "message": "当前 NodeContext 已过期，请刷新节点后再继续。",
                "actions": [],
                "tool_calls": [],
                "usage": {"prompt_tokens": "unknown", "completion_tokens": "unknown", "total_tokens": "unknown", "estimated_cost": "unknown"},
                "risk_events": [{"id": "context_stale", "severity": "warning", "summary": "Agent 请求携带了旧 context_revision。"}],
            }
        )

    provider_status = next((item for item in _app_generation_provider_statuses(repo_root=repo_root) if item.get("provider") == provider), None)
    if not provider_status or provider_status.get("status") != "ready":
        label = "PI-Agent" if provider == "pi_agent" else provider
        return _redact(
            {
                "provider": provider,
                "status": str(provider_status.get("status", "not_configured")) if provider_status else "not_configured",
                "message": str(provider_status.get("message", f"{label} is not configured.")) if provider_status else f"{label} is not configured.",
                "actions": [],
                "tool_calls": [],
                "usage": {"prompt_tokens": "unknown", "completion_tokens": "unknown", "total_tokens": "unknown", "estimated_cost": "unknown"},
                "risk_events": [],
            }
        )

    from growth_dev.team.agent_bridge import send_agent_message

    response = send_agent_message(
        provider_id=provider,
        node_context=current_context,
        mode=mode,
        message=message,
        repo_root=repo_root,
        interaction_context=interaction_context,
        intent=intent,
    )
    return _redact(response)


def stream_app_generation_agent_message(
    payload: dict[str, Any],
    *,
    runs_dir: Path = Path("runs"),
    repo_root: Path = Path("."),
) -> Iterator[dict[str, Any]]:
    """Yield SSE-ready StreamEvents for the right-panel agent dialog.

    Validates context_revision freshness like the non-streaming
    ``handle_app_generation_agent_message``; on staleness or provider
    misconfiguration, yields a single terminal event so the SSE channel still
    closes deterministically.
    """
    context = payload.get("node_context")
    if not isinstance(context, dict):
        raise ValueError("node_context is required")
    provider = str(payload.get("provider") or "codex")
    mode = str(payload.get("mode") or "explain")
    intent = str(payload.get("intent") or mode or "auto")
    message = str(payload.get("message") or "")
    interaction_context = payload.get("interaction_context")
    if not isinstance(interaction_context, dict):
        interaction_context = None
    node_id = str(context.get("node_id") or "")
    run_id = str(context.get("run_id") or "")
    selected_variant = str(context.get("selected_variant") or "codex")
    if not run_id or not node_id:
        raise ValueError("node_context must include run_id and node_id")

    current_context = build_app_generation_node_context(
        run_id,
        node_id,
        selected_variant=selected_variant,
        runs_dir=runs_dir,
        repo_root=repo_root,
        user_overrides=context.get("user_overrides") if isinstance(context.get("user_overrides"), list) else None,
    )
    requested_revision = context.get("context_revision")
    interaction_revision = interaction_context.get("context_revision") if interaction_context else ""
    if (
        (requested_revision and requested_revision != current_context.get("context_revision"))
        or (interaction_revision and interaction_revision != current_context.get("context_revision"))
    ):
        yield {
            "type": "upstream_error",
            "payload": {
                "phase": "context_stale",
                "errorMessage": "当前 NodeContext 已过期，请刷新节点后再继续。",
                "hint": "upstream_unknown",
            },
        }
        return

    provider_status = next(
        (item for item in _app_generation_provider_statuses(repo_root=repo_root) if item.get("provider") == provider),
        None,
    )
    if not provider_status or provider_status.get("status") != "ready":
        label = "PI-Agent" if provider == "pi_agent" else provider
        yield {
            "type": "upstream_error",
            "payload": {
                "phase": "not_configured",
                "errorMessage": str(provider_status.get("message")) if provider_status else f"{label} is not configured.",
                "hint": "auth_invalid",
            },
        }
        return

    from growth_dev.team.agent_bridge import stream_agent_message

    saw_terminal_event = False
    for event in stream_agent_message(
        provider_id=provider,
        node_context=current_context,
        mode=mode,
        message=message,
        repo_root=repo_root,
        interaction_context=interaction_context,
        intent=intent,
    ):
        if event.get("type") in {"agent_end", "upstream_error"}:
            saw_terminal_event = True
        yield event
    if not saw_terminal_event:
        yield {
            "type": "upstream_error",
            "payload": {
                "phase": "stream_closed",
                "errorMessage": "Provider stream ended without agent_end",
                "hint": "upstream_unknown",
            },
        }


def start_app_generation_rerun(config: DashboardConfig, payload: dict[str, Any]) -> dict[str, Any]:
    source_run_id = str(payload.get("source_run_id") or "").strip()
    node_id = str(payload.get("rerun_from_node") or payload.get("node_id") or "").strip()
    selected_variant = str(payload.get("selected_variant") or "codex").strip()
    override_instructions = str(payload.get("override_instructions") or "").strip()
    if not source_run_id:
        raise ValueError("source_run_id is required")
    if node_id not in APP_GENERATION_NODE_BY_ID:
        raise ValueError(f"Unknown app_generation node: {node_id}")
    if selected_variant not in {"rule", "codex", "llm", "pi_agent"}:
        raise ValueError(f"Unsupported selected_variant: {selected_variant}")

    runs_dir = Path(config.runs_dir).resolve()
    repo_root = Path(config.repo_root).resolve()
    source_dir = _safe_run_dir(runs_dir, source_run_id)
    if not source_dir.exists():
        raise FileNotFoundError(f"Run not found: {source_run_id}")
    source_record = _safe_read_json(source_dir / "team_run_record.json")
    if str(source_record.get("domain_id", "")) != APP_GENERATION_DOMAIN_ID:
        raise ValueError(f"Run is not app_generation: {source_run_id}")
    source_inputs = source_record.get("inputs") if isinstance(source_record.get("inputs"), dict) else {}
    contract = _safe_read_json(source_dir / "app_contract.json")
    app_slug = str(source_inputs.get("app_slug") or contract.get("app_slug") or _slug_from_contract(contract) or "generated-app")
    comparison_group_id = str(payload.get("comparison_group_id") or source_inputs.get("comparison_group_id") or f"cmp-{app_slug}")
    base_prd = str(source_inputs.get("prd_text") or "")
    if not base_prd and (source_dir / "input_prd.md").exists():
        base_prd = (source_dir / "input_prd.md").read_text(encoding="utf-8", errors="replace")
    prd_text = base_prd.strip()
    if override_instructions:
        prd_text = f"{prd_text}\n\n## Workbench Override Instructions\n\n{override_instructions}\n".strip()

    if payload.get("context_revision"):
        current_context = build_app_generation_node_context(
            source_run_id,
            node_id,
            selected_variant=selected_variant,
            runs_dir=runs_dir,
            repo_root=repo_root,
        )
        if payload.get("context_revision") != current_context.get("context_revision"):
            raise ValueError("context_revision is stale; refresh the node before rerun.")

    new_run_id = str(payload.get("run_id") or f"app_generation-rerun-{timestamp_slug()}")
    rerun_payload = {
        "run_id": new_run_id,
        "brief": str(source_record.get("brief") or f"根据 PRD 生成本地应用：{app_slug}"),
        "domain": APP_GENERATION_DOMAIN_ID,
        "executor": str(payload.get("executor") or config.executor or "codex"),
        "model": str(payload.get("model") or config.model),
        "codex_provider": str(payload.get("codex_provider") or config.codex_provider),
        "inputs_json": {
            "app_slug": app_slug,
            "prd_text": prd_text,
            "source_run_id": source_run_id,
            "rerun_from_node": node_id,
            "selected_variant": selected_variant,
            "override_instructions": override_instructions,
            "comparison_group_id": comparison_group_id,
            "context_revision": str(payload.get("context_revision") or ""),
        },
    }
    result = start_dashboard_run(config, rerun_payload)
    return _redact(
        {
            **result,
            "source_run_id": source_run_id,
            "rerun_from_node": node_id,
            "selected_variant": selected_variant,
            "comparison_group_id": comparison_group_id,
        }
    )


def _app_generation_publish_status(run_dir: Path, app_slug: str = "") -> dict[str, Any]:
    published_apps_dir = run_dir / "generated_apps"
    if not published_apps_dir.exists():
        return {"status": "not_published", "app_slug": app_slug, "message": "尚未发布应用快照。"}

    slug = str(app_slug or "").strip()
    if not slug:
        published_apps = [d for d in published_apps_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        if len(published_apps) == 1:
            slug = published_apps[0].name
        elif len(published_apps) > 1:
            return {"status": "ambiguous", "app_slug": "", "message": "存在多个已发布应用，需要指定 app_slug。"}
        else:
            return {"status": "not_published", "app_slug": "", "message": "尚未发布应用快照。"}

    publish_record_path = published_apps_dir / slug / "app_publish.json"
    if not publish_record_path.exists():
        return {"status": "missing_publish_record", "app_slug": slug, "message": "应用快照缺少发布记录。"}

    publish_record = _safe_read_json(publish_record_path)
    patches_index = _safe_read_json(run_dir / "app_patches" / "index.json")
    patches = patches_index.get("patches") if isinstance(patches_index.get("patches"), list) else []
    return {
        "status": "published",
        "app_slug": str(publish_record.get("app_slug") or slug),
        "published_at": str(publish_record.get("published_at") or ""),
        "source_commit": str(publish_record.get("source_commit") or "unknown"),
        "worktree_clean": publish_record.get("worktree_clean", "unknown"),
        "app_patches_count": len(patches),
        "message": "应用快照已发布，可以启动预览。",
    }


def publish_app_generation_run(config: DashboardConfig, payload: dict[str, Any]) -> dict[str, Any]:
    import shutil

    run_id = str(payload.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("run_id is required")
    
    runs_dir = Path(config.runs_dir).resolve()
    run_dir = _safe_run_dir(runs_dir, run_id)
    if not run_dir.exists():
        raise FileNotFoundError(f"Run not found: {run_id}")

    worktree_apps_dir = run_dir / "worktree" / "generated_apps"
    if not worktree_apps_dir.exists():
        raise FileNotFoundError(f"No worktree generated_apps found: {run_id}")
    
    app_slug = str(payload.get("app_slug") or "").strip()
    if not app_slug:
        subdirs = [d for d in worktree_apps_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        if len(subdirs) == 0:
            raise ValueError(f"No apps found in worktree/generated_apps: {run_id}")
        if len(subdirs) > 1:
            raise ValueError(f"multiple_apps_found: {[d.name for d in subdirs]}. Specify app_slug.")
        app_slug = subdirs[0].name
    
    source_dir = worktree_apps_dir / app_slug
    if not source_dir.exists():
        raise FileNotFoundError(f"App not found in worktree: {app_slug}")

    record = _safe_read_json(run_dir / "team_run_record.json")
    coder_runs = [
        item
        for item in record.get("agent_runs", [])
        if isinstance(item, dict) and str(item.get("agent_id", "")) == "coder"
    ]
    if not coder_runs or not any(str(item.get("status", "")) in {"completed", "warning"} for item in coder_runs):
        raise ValueError("implementation_not_complete: cannot publish before implementation completes")
    
    target_parent = run_dir / "generated_apps"
    target_parent.mkdir(parents=True, exist_ok=True)
    target_dir = target_parent / app_slug
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir, target_dir)
    
    files_count = sum(1 for _ in target_dir.rglob("*") if _.is_file())
    published_at = now_iso()
    worktree_root = run_dir / "worktree"
    source_commit = "unknown"
    worktree_clean: bool | str = "unknown"
    if worktree_root.exists():
        try:
            commit_result = subprocess.run(
                ["git", "-C", str(worktree_root), "rev-parse", "HEAD"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if commit_result.returncode == 0:
                source_commit = commit_result.stdout.strip() or "unknown"
            status_result = subprocess.run(
                ["git", "-C", str(worktree_root), "status", "--porcelain"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if status_result.returncode == 0:
                worktree_clean = status_result.stdout.strip() == ""
        except Exception:
            source_commit = "unknown"
            worktree_clean = "unknown"
    
    publish_record = {
        "published_at": published_at,
        "source_commit": source_commit,
        "app_slug": app_slug,
        "files_count": files_count,
        "app_patches_count_at_publish": 0,
        "worktree_path": _relative_to(source_dir, run_dir),
        "worktree_clean": worktree_clean,
    }
    write_json(target_dir / "app_publish.json", publish_record)
    
    return _redact({
        "published_at": published_at,
        "app_slug": app_slug,
        "files_count": files_count,
        "source_commit": source_commit,
    })


def start_app_generation_preview(config: DashboardConfig, payload: dict[str, Any]) -> dict[str, Any]:
    run_id = str(payload.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("run_id is required")
    
    runs_dir = Path(config.runs_dir).resolve()
    repo_root = Path(config.repo_root).resolve()
    run_dir = _safe_run_dir(runs_dir, run_id)
    if not run_dir.exists():
        raise FileNotFoundError(f"Run not found: {run_id}")
    
    published_apps_dir = run_dir / "generated_apps"
    if not published_apps_dir.exists():
        raise ValueError("app_not_published: Please publish the app first")
    
    app_slug = str(payload.get("app_slug") or "").strip()
    if not app_slug:
        subdirs = [d for d in published_apps_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        if len(subdirs) == 0:
            raise ValueError("app_not_published: No published apps found")
        if len(subdirs) > 1:
            raise ValueError(f"multiple_apps_found: {[d.name for d in subdirs]}. Specify app_slug.")
        app_slug = subdirs[0].name
    
    published_app_dir = published_apps_dir / app_slug
    if not published_app_dir.exists():
        raise ValueError(f"app_not_published: {app_slug}")
    
    publish_record_path = published_app_dir / "app_publish.json"
    if not publish_record_path.exists():
        raise ValueError("missing_publish_record: app_publish.json not found")
    
    record_path = run_dir / "preview" / "preview_run_record.json"
    if record_path.exists():
        old_record = _safe_read_json(record_path)
        if old_record.get("stopped_at") is None:
            preview.stop_preview(record_path)
    
    preferred_port = int(payload.get("preferred_port") or 8788)
    inject_env = bool(payload.get("inject_env", payload.get("sync_env", True)))
    request = preview.PreviewRunRequest(
        run_id=run_id,
        app_slug=app_slug,
        generated_app_dir=published_app_dir,
        preview_command=["node", "server.js"],
        preferred_port=preferred_port,
        health_path="/",
        health_timeout_seconds=5.0,
        repo_root=repo_root,
        inject_env=inject_env,
    )
    
    result = preview.start_preview(request, runs_dir=runs_dir)
    
    return _redact({
        "status": result.status,
        "run_id": run_id,
        "app_slug": app_slug,
        "url": result.url,
        "port": result.port,
        "pid": result.pid,
        "health_status": result.health_status,
        "health_message": result.message,
        "record_path": str(result.record_path) if result.record_path else None,
        "log_path": str(result.log_path) if result.log_path else None,
        "risk_events": result.risk_events,
        "inject_env": inject_env,
    })


def stop_app_generation_preview(config: DashboardConfig, payload: dict[str, Any]) -> dict[str, Any]:
    run_id = str(payload.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("run_id is required")
    
    runs_dir = Path(config.runs_dir).resolve()
    run_dir = _safe_run_dir(runs_dir, run_id)
    record_path = run_dir / "preview" / "preview_run_record.json"
    
    if not record_path.exists():
        return {"status": "not_running", "run_id": run_id}
    
    record = _safe_read_json(record_path)
    if record.get("stopped_at") is not None:
        return {"status": "stopped", "run_id": run_id, "pid": record.get("pid")}
    
    result = preview.stop_preview(record_path)
    return _redact({**result, "run_id": run_id})


def get_app_generation_preview_status(config: DashboardConfig, run_id: str) -> dict[str, Any]:
    runs_dir = Path(config.runs_dir).resolve()
    run_dir = _safe_run_dir(runs_dir, run_id)
    record_path = run_dir / "preview" / "preview_run_record.json"
    
    if not record_path.exists():
        return {"status": "not_running", "run_id": run_id}
    
    record = _safe_read_json(record_path)
    
    status = "stopped" if record.get("stopped_at") else "running"
    pid = record.get("pid")
    if pid and status == "running":
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            status = "stale"
    
    return _redact({
        "status": status,
        "run_id": record.get("run_id", run_id),
        "app_slug": record.get("app_slug"),
        "pid": pid,
        "port": record.get("port"),
        "url": record.get("url"),
        "health_status": record.get("health_status"),
        "started_at": record.get("started_at"),
        "stopped_at": record.get("stopped_at"),
    })


def get_app_generation_preview_logs(config: DashboardConfig, run_id: str, tail: int = 200) -> dict[str, Any]:
    runs_dir = Path(config.runs_dir).resolve()
    run_dir = _safe_run_dir(runs_dir, run_id)
    log_path = run_dir / "preview" / "preview.log"
    
    if not log_path.exists():
        return {"lines": [], "total_lines": 0, "tail": tail}
    
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        total = len(all_lines)
        lines = all_lines[-tail:] if tail > 0 else all_lines
        return {"lines": [line.rstrip("\n\r") for line in lines], "total_lines": total, "tail": tail}
    except Exception as exc:
        return {"error": f"Failed to read log: {exc}", "lines": [], "total_lines": 0, "tail": tail}


def _restart_preview_two_stage(
    run_dir: Path,
    runs_dir: Path,
    repo_root: Path,
    run_id: str,
) -> dict[str, Any]:
    record_path = run_dir / "preview" / "preview_run_record.json"
    if not record_path.exists():
        return {"status": "skipped", "reason": "no_active_preview"}
    
    old_record = _safe_read_json(record_path)
    if old_record.get("stopped_at") is not None:
        return {"status": "skipped", "reason": "no_active_preview"}
    
    old_pid = old_record.get("pid")
    old_port = old_record.get("port")
    app_slug = old_record.get("app_slug")
    if not isinstance(old_pid, int) or not isinstance(old_port, int) or not app_slug:
        return {"status": "skipped", "reason": "no_active_preview"}
    
    published_app_dir = run_dir / "generated_apps" / app_slug
    if not published_app_dir.exists():
        return {"status": "skipped", "reason": "no_published_app"}
    
    new_port = preview.allocate_port(old_port + 1)
    if new_port == old_port:
        new_port = preview.allocate_port(old_port + 2)
    
    request = preview.PreviewRunRequest(
        run_id=run_id,
        app_slug=app_slug,
        generated_app_dir=published_app_dir,
        preview_command=list(old_record.get("command") or ["node", "server.js"]),
        preferred_port=new_port,
        health_path="/",
        health_timeout_seconds=5.0,
        repo_root=repo_root,
    )
    new_result = preview.start_preview(request, runs_dir=runs_dir)
    
    if new_result.health_status != "ok" or new_result.pid is None:
        failed_at = now_iso()
        old_record["last_patch_restart_error"] = {
            "phase": "new_process_health_check",
            "message": new_result.message,
            "checked_at": failed_at,
        }
        write_json(record_path, old_record)
        return {
            "status": "failed",
            "phase": "new_process_health_check",
            "error": new_result.message,
            "old_pid": old_pid,
            "old_port": old_port,
            "url": old_record.get("url"),
        }
    
    switched_at = now_iso()
    new_record = dict(old_record)
    new_record.update({
        "pid": new_result.pid,
        "port": new_result.port,
        "url": new_result.url,
        "previous_pid": old_pid,
        "previous_port": old_port,
        "switched_at": switched_at,
        "health_status": new_result.health_status,
    })
    write_json(record_path, new_record)
    
    preview._kill_pid(old_pid)
    
    return {
        "status": "switched",
        "old_pid": old_pid,
        "old_port": old_port,
        "new_pid": new_result.pid,
        "new_port": new_result.port,
        "new_url": new_result.url,
        "url": new_result.url,
        "switched_at": switched_at,
    }


def _apply_edit(
    original: str,
    edit_kind: str,
    new_content: str,
    anchor: str = "",
    old_content: str = "",
) -> str:
    if edit_kind == "create_file":
        return new_content
    if edit_kind == "append":
        if original and not original.endswith("\n"):
            return original + "\n" + new_content
        return original + new_content
    if edit_kind == "replace_text":
        if not old_content:
            raise ValueError("replace_text requires old_content")
        count = original.count(old_content)
        if count == 0:
            raise ValueError(f"old_content_not_found: {old_content[:80]}")
        if count > 1:
            raise ValueError(f"ambiguous_match: old_content appears {count} times")
        return original.replace(old_content, new_content)
    if edit_kind == "replace_block":
        if not anchor:
            raise ValueError("anchor is required for replace_block")
        start_idx = original.find(anchor)
        if start_idx == -1:
            raise ValueError(f"anchor_not_found: {anchor}")
        end_anchor = anchor.replace("START", "END")
        end_idx = original.find(end_anchor, start_idx + len(anchor))
        if end_idx == -1:
            raise ValueError(f"end_anchor_not_found: {end_anchor}")
        return (
            original[: start_idx + len(anchor)]
            + "\n" + new_content + "\n"
            + original[end_idx:]
        )
    raise ValueError(f"unknown_edit_kind: {edit_kind}")


def _normalized_patch_payloads(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_patches = payload.get("patches")
    if isinstance(raw_patches, list):
        patches = [entry for entry in raw_patches if isinstance(entry, dict)]
        if len(patches) != len(raw_patches):
            raise ValueError("patches must contain objects only")
        if not patches:
            raise ValueError("patches must not be empty")
        return patches
    return [
        {
            "target_path": payload.get("target_path"),
            "edit_kind": payload.get("edit_kind"),
            "new_content": payload.get("new_content", ""),
            "anchor": payload.get("anchor", ""),
            "old_content": payload.get("old_content", ""),
            "summary": payload.get("summary", ""),
        }
    ]


def _validate_patch_target(run_dir: Path, rel_raw: str) -> tuple[Path, str, str]:
    rel = Path(rel_raw)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("target_path_outside_generated_apps: path traversal not allowed")
    if not rel.parts or rel.parts[0] != "generated_apps":
        raise ValueError("target_path_outside_generated_apps: must start with generated_apps/")
    if len(rel.parts) < 3:
        raise ValueError("target_path_outside_generated_apps: must include slug + file")
    app_slug = rel.parts[1]
    published_app_dir = run_dir / "generated_apps" / app_slug
    target_file = (run_dir / rel).resolve()
    try:
        target_file.relative_to(published_app_dir.resolve())
    except ValueError as exc:
        raise ValueError("target_path_outside_generated_apps: escapes published dir") from exc
    return target_file, app_slug, str(rel.relative_to(Path("generated_apps") / app_slug))


def _run_patch_verification(app_dir: Path, commands: list[Any]) -> dict[str, Any]:
    allowed = {
        "node --check server.js": ["node", "--check", "server.js"],
        "node --check public/app.js": ["node", "--check", "public/app.js"],
        "node runtime_smoke.js": ["node", "runtime_smoke.js"],
    }
    results: list[dict[str, Any]] = []
    risk_events: list[str] = []
    for command in commands:
        command_text = str(command).strip()
        if not command_text:
            continue
        if command_text == "GET /api/health":
            results.append({
                "command": command_text,
                "status": "skipped",
                "reason": "requires_running_preview",
            })
            continue
        argv = allowed.get(command_text)
        if argv is None:
            risk_events.append(f"verification_command_not_allowed:{command_text}")
            results.append({
                "command": command_text,
                "status": "rejected",
                "reason": "not_allowlisted",
            })
            continue
        completed = subprocess.run(
            argv,
            cwd=app_dir,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        results.append({
            "command": command_text,
            "status": "passed" if completed.returncode == 0 else "failed",
            "exit_code": completed.returncode,
            "stdout": completed.stdout[-1000:],
            "stderr": completed.stderr[-1000:],
        })
    failed = any(item.get("status") in {"failed", "rejected"} for item in results)
    return {
        "status": "failed" if failed else "passed",
        "commands": results,
        "risk_events": risk_events,
    }


def patch_app_generation_run(config: DashboardConfig, payload: dict[str, Any]) -> dict[str, Any]:
    import difflib

    run_id = str(payload.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("run_id is required")
    summary = str(payload.get("summary") or "").strip()
    action_id = str(payload.get("action_id") or "").strip()
    dry_run = bool(payload.get("dry_run") or False)
    preserve_capabilities = payload.get("preserve_capabilities")
    verification_commands = payload.get("verification")
    problem_source = str(payload.get("problem_source") or "").strip()
    patch_set_id = str(payload.get("patch_set_id") or uuid.uuid4()).strip()
    if not isinstance(preserve_capabilities, list):
        preserve_capabilities = []
    if not isinstance(verification_commands, list):
        verification_commands = []

    runs_dir = Path(config.runs_dir).resolve()
    repo_root = Path(config.repo_root).resolve()
    run_dir = _safe_run_dir(runs_dir, run_id)
    if not run_dir.exists():
        raise FileNotFoundError(f"Run not found: {run_id}")

    patch_payloads = _normalized_patch_payloads(payload)
    prepared: list[dict[str, Any]] = []
    app_slug = ""
    merged_diff_parts: list[str] = []
    seen_targets: set[Path] = set()
    for patch in patch_payloads:
        target_path_raw = str(patch.get("target_path") or "").strip()
        if not target_path_raw:
            raise ValueError("target_path is required")
        edit_kind = str(patch.get("edit_kind") or "").strip()
        if edit_kind not in {"append", "replace_block", "create_file", "replace_text"}:
            raise ValueError(f"unsupported edit_kind: {edit_kind}")
        target_file, target_app_slug, rel_file = _validate_patch_target(run_dir, target_path_raw)
        if target_file in seen_targets:
            raise ValueError("duplicate_patch_target: each file may appear only once per PatchSet")
        seen_targets.add(target_file)
        if app_slug and app_slug != target_app_slug:
            raise ValueError("patchset_multiple_apps_not_supported")
        app_slug = target_app_slug
        published_app_dir = run_dir / "generated_apps" / app_slug
        if not published_app_dir.exists():
            raise ValueError("app_not_published: published snapshot not found")
        publish_record_path = published_app_dir / "app_publish.json"
        if not publish_record_path.exists():
            raise ValueError("app_not_published: app_publish.json missing")

        if edit_kind == "create_file" and target_file.exists():
            raise ValueError("file_already_exists: use replace_block or append")
        original = target_file.read_text(encoding="utf-8") if target_file.exists() else ""
        new_content = str(patch.get("new_content") or "")
        anchor = str(patch.get("anchor") or "").strip()
        old_content = str(patch.get("old_content") or "")
        updated = _apply_edit(original, edit_kind, new_content, anchor, old_content)
        diff_lines = list(difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"a/{target_path_raw}",
            tofile=f"b/{target_path_raw}",
        ))
        diff_text = "".join(diff_lines)
        merged_diff_parts.append(diff_text)
        prepared.append({
            "target_path": target_path_raw,
            "target_file": target_file,
            "rel_file": rel_file,
            "edit_kind": edit_kind,
            "original": original,
            "updated": updated,
            "diff": diff_text,
            "summary": str(patch.get("summary") or summary).strip(),
        })

    if not prepared:
        raise ValueError("patches must not be empty")
    diff_text = "\n".join(part for part in merged_diff_parts if part)
    first_patch = prepared[0]

    if dry_run:
        return _redact({
            "status": "dry_run",
            "run_id": run_id,
            "app_slug": app_slug,
            "target_path": first_patch["target_path"],
            "patch_set_id": patch_set_id,
            "patches": [
                {
                    "target_path": item["target_path"],
                    "edit_kind": item["edit_kind"],
                    "summary": item["summary"],
                }
                for item in prepared
            ],
            "diff": diff_text,
            "edit_kind": first_patch["edit_kind"],
            "summary": summary,
        })

    patches_dir = run_dir / "app_patches"
    patches_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    index_path = patches_dir / "index.json"
    if index_path.exists():
        index = _safe_read_json(index_path) or {"patches": []}
        if not isinstance(index.get("patches"), list):
            index = {"patches": []}
    else:
        index = {"patches": []}
    backups: dict[Path, str | None] = {
        item["target_file"]: (item["target_file"].read_text(encoding="utf-8") if item["target_file"].exists() else None)
        for item in prepared
    }
    written_diffs: list[Path] = []
    applied_at = now_iso()
    try:
        for item in prepared:
            item["target_file"].parent.mkdir(parents=True, exist_ok=True)
            item["target_file"].write_text(item["updated"], encoding="utf-8")
        for index_no, item in enumerate(prepared, start=1):
            safe_file = re.sub(r"[^a-zA-Z0-9._-]", "_", item["rel_file"])
            diff_filename = f"{ts}__app__{index_no:02d}__{safe_file}.diff"
            diff_path = patches_dir / diff_filename
            diff_path.write_text(item["diff"], encoding="utf-8")
            written_diffs.append(diff_path)
            index["patches"].append({
                "ts": ts,
                "node": "app",
                "app_slug": app_slug,
                "file": item["rel_file"],
                "diff_path": diff_filename,
                "summary": item["summary"] or summary,
                "action_id": action_id,
                "patch_set_id": patch_set_id,
                "applied_at": applied_at,
                "edit_kind": item["edit_kind"],
                "problem_source": problem_source,
                "preserve_capabilities": preserve_capabilities,
                "verification": verification_commands,
            })
        write_json(index_path, index)
    except Exception:
        for target, original_text in backups.items():
            if original_text is None:
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass
            else:
                target.write_text(original_text, encoding="utf-8")
        for diff_path in written_diffs:
            try:
                diff_path.unlink()
            except FileNotFoundError:
                pass
        raise

    published_app_dir = run_dir / "generated_apps" / app_slug
    verification_result = _run_patch_verification(published_app_dir, verification_commands)

    restart_info = _restart_preview_two_stage(run_dir, runs_dir, repo_root, run_id)

    return _redact({
        "status": "applied",
        "run_id": run_id,
        "app_slug": app_slug,
        "target_path": first_patch["target_path"],
        "patch_set_id": patch_set_id,
        "patches": [
            {
                "target_path": item["target_path"],
                "edit_kind": item["edit_kind"],
                "summary": item["summary"],
            }
            for item in prepared
        ],
        "diff_paths": [str(path.relative_to(run_dir)) for path in written_diffs],
        "diff_path": str(written_diffs[0].relative_to(run_dir)) if written_diffs else "",
        "applied_at": applied_at,
        "summary": summary,
        "verification": verification_result,
        "restart": restart_info,
    })


def start_app_generation_delegate_repair(config: DashboardConfig, payload: dict[str, Any]) -> dict[str, Any]:
    import shutil

    from .code_agent_executor import run_repair
    from .codex import CodexExecutorConfig, load_aicodemirror_provider_from_env

    run_id = str(payload.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("run_id is required")
    repair_request = payload.get("repair_request")
    if not isinstance(repair_request, dict):
        raise ValueError("repair_request is required")

    runs_dir = Path(config.runs_dir).resolve()
    repo_root = Path(config.repo_root).resolve()
    run_dir = _safe_run_dir(runs_dir, run_id)
    if not run_dir.exists():
        raise FileNotFoundError(f"Run not found: {run_id}")

    app_slug = str(repair_request.get("app_slug") or payload.get("app_slug") or "").strip()
    if not app_slug:
        raise ValueError("app_slug is required")
    repair_request = {**repair_request, "app_slug": app_slug}
    published_app_dir = run_dir / "generated_apps" / app_slug
    if not published_app_dir.exists() or not (published_app_dir / "app_publish.json").exists():
        raise ValueError("app_not_published: published snapshot not found")

    provider_config = None
    if config.codex_provider == "aicodemirror":
        env_path = Path(config.env_file)
        if not env_path.is_absolute():
            env_path = repo_root / env_path
        provider_config = load_aicodemirror_provider_from_env(env_path)
    elif config.codex_provider not in {"", "default"}:
        raise ValueError(f"Unsupported codex provider: {config.codex_provider}")
    codex_config = CodexExecutorConfig(
        binary=config.codex_binary,
        model=config.model,
        reasoning_effort=config.reasoning_effort,
        provider=provider_config,
    )
    repair_id = str(payload.get("repair_id") or f"repair-{timestamp_slug()}-{uuid.uuid4().hex[:8]}")
    result = run_repair(repair_request, run_dir=run_dir, repo_root=repo_root, config=codex_config)

    repairs_dir = run_dir / "app_repairs" / repair_id
    repairs_dir.mkdir(parents=True, exist_ok=True)
    write_json(repairs_dir / "repair_request.json", repair_request)
    write_json(repairs_dir / "repair_result.json", result.to_dict())
    diff_path = run_dir / result.diff_path if result.diff_path else None
    copied_diff = ""
    diff_text = ""
    if diff_path and diff_path.exists():
        copied = repairs_dir / "candidate.diff"
        shutil.copyfile(diff_path, copied)
        copied_diff = str(copied.relative_to(run_dir))
        diff_text = copied.read_text(encoding="utf-8", errors="replace")
    active_record = {
        "repair_id": repair_id,
        "app_slug": app_slug,
        "status": result.status,
        "created_at": now_iso(),
        "candidate_dir": result.candidate_dir,
        "diff_path": copied_diff or result.diff_path,
        "repair_request_path": str((repairs_dir / "repair_request.json").relative_to(run_dir)),
        "repair_result_path": str((repairs_dir / "repair_result.json").relative_to(run_dir)),
    }
    write_json(run_dir / "app_repairs" / "active.json", active_record)

    return _redact({
        "status": result.status,
        "run_id": run_id,
        "repair_id": repair_id,
        "app_slug": app_slug,
        "repair_request": repair_request,
        "candidate_dir": result.candidate_dir,
        "diff_path": copied_diff or result.diff_path,
        "diff": diff_text,
        "changed_files": result.changed_files,
        "verification": result.verification_results,
        "risk_events": result.risk_events,
        "blockers": result.blockers,
        "codex_artifacts": result.codex_artifacts,
        "message": result.message,
    })


def apply_app_generation_delegate_repair(config: DashboardConfig, payload: dict[str, Any]) -> dict[str, Any]:
    import shutil

    run_id = str(payload.get("run_id") or "").strip()
    repair_id = str(payload.get("repair_id") or "").strip()
    if not run_id:
        raise ValueError("run_id is required")
    if not repair_id:
        raise ValueError("repair_id is required")

    runs_dir = Path(config.runs_dir).resolve()
    repo_root = Path(config.repo_root).resolve()
    run_dir = _safe_run_dir(runs_dir, run_id)
    if not run_dir.exists():
        raise FileNotFoundError(f"Run not found: {run_id}")
    active_path = run_dir / "app_repairs" / "active.json"
    active = _safe_read_json(active_path)
    if str(active.get("repair_id") or "") != repair_id:
        raise ValueError("repair_candidate_stale: active repair id does not match")
    app_slug = str(active.get("app_slug") or "").strip()
    if not app_slug:
        raise ValueError("app_slug is required")
    repairs_dir = run_dir / "app_repairs" / repair_id
    result = _safe_read_json(repairs_dir / "repair_result.json")
    if str(result.get("status") or "") != "prepared":
        raise ValueError("repair_not_prepared: prepare did not produce an applyable candidate")
    candidate_dir = run_dir / str(active.get("candidate_dir") or result.get("candidate_dir") or "")
    if not candidate_dir.exists() or not candidate_dir.is_dir():
        raise FileNotFoundError(f"Repair candidate not found: {candidate_dir}")

    published_parent = run_dir / "generated_apps"
    published_parent.mkdir(parents=True, exist_ok=True)
    published_dir = published_parent / app_slug
    backup_dir = run_dir / "app_repairs" / f"{repair_id}__published_backup"
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    if published_dir.exists():
        shutil.copytree(published_dir, backup_dir)
        shutil.rmtree(published_dir)
    try:
        shutil.copytree(candidate_dir, published_dir, ignore=shutil.ignore_patterns("app_publish.json", "app_patches", "node_modules", ".env", ".env.*"))
        diff_rel = str(active.get("diff_path") or result.get("diff_path") or "")
        diff_text = (run_dir / diff_rel).read_text(encoding="utf-8") if diff_rel and (run_dir / diff_rel).exists() else ""
        applied_at = now_iso()
        publish_record = {
            "published_at": applied_at,
            "source_commit": "repair",
            "app_slug": app_slug,
            "files_count": sum(1 for path in published_dir.rglob("*") if path.is_file()),
            "worktree_path": str(candidate_dir.relative_to(run_dir)) if candidate_dir.is_relative_to(run_dir) else str(candidate_dir),
            "repair_id": repair_id,
            "repair_request_path": str((repairs_dir / "repair_request.json").relative_to(run_dir)),
        }
        write_json(published_dir / "app_publish.json", publish_record)

        patches_dir = run_dir / "app_patches"
        patches_dir.mkdir(parents=True, exist_ok=True)
        index_path = patches_dir / "index.json"
        index = _safe_read_json(index_path) if index_path.exists() else {"patches": []}
        if not isinstance(index.get("patches"), list):
            index = {"patches": []}
        safe_repair_id = re.sub(r"[^a-zA-Z0-9._-]", "_", repair_id)
        diff_name = f"{int(time.time())}__delegate__{safe_repair_id}.diff"
        (patches_dir / diff_name).write_text(diff_text, encoding="utf-8")
        repair_request = _safe_read_json(repairs_dir / "repair_request.json")
        verification_commands = repair_request.get("verification") if isinstance(repair_request.get("verification"), list) else []
        index["patches"].append({
            "ts": int(time.time()),
            "node": "app",
            "app_slug": app_slug,
            "file": "*",
            "diff_path": diff_name,
            "summary": str(payload.get("summary") or repair_request.get("problem") or "delegate_code_repair"),
            "action_id": str(payload.get("action_id") or ""),
            "patch_set_id": repair_id,
            "applied_at": applied_at,
            "edit_kind": "delegate_code_repair",
            "problem_source": "app_preview",
            "repair_request": repair_request,
            "verification": verification_commands,
        })
        write_json(index_path, index)
    except Exception:
        if published_dir.exists():
            shutil.rmtree(published_dir)
        if backup_dir.exists():
            shutil.copytree(backup_dir, published_dir)
        raise

    verification_result = _run_patch_verification(published_dir, verification_commands)
    restart_info = _restart_preview_two_stage(run_dir, runs_dir, repo_root, run_id)
    adjustment = {
        "event_id": f"adjustment-{timestamp_slug()}",
        "type": "app_adjustment",
        "run_id": run_id,
        "app_slug": app_slug,
        "resolved_intent": "delegate_code_repair",
        "agent_provider": str(payload.get("agent_provider") or "unknown"),
        "patch_status": "applied",
        "verification_status": verification_result.get("status", "unknown"),
        "rollback_available": backup_dir.exists(),
        "repair_id": repair_id,
        "diff_refs": [str((patches_dir / diff_name).relative_to(run_dir))],
        "preview_status": restart_info,
        "created_at": now_iso(),
    }
    events_path = run_dir / "adjustment_events.jsonl"
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(adjustment, ensure_ascii=False) + "\n")
    active["status"] = "applied"
    active["applied_at"] = adjustment["created_at"]
    write_json(active_path, active)

    return _redact({
        "status": "applied",
        "run_id": run_id,
        "repair_id": repair_id,
        "app_slug": app_slug,
        "diff_path": str((patches_dir / diff_name).relative_to(run_dir)),
        "verification": verification_result,
        "restart": restart_info,
        "adjustment_event": adjustment,
    })


def stream_app_generation_run_events(
    run_id: str,
    *,
    runs_dir: Path = Path("runs"),
    repo_root: Path = Path("."),
    poll_interval: float = 1.0,
    max_iterations: int | None = None,
    sleeper: Any = None,
) -> Iterator[dict[str, Any]]:
    """Yield SSE-ready events tracking an app_generation run's progress.

    Event shape (matches the right-dialog StreamEvent shape):
      - ``snapshot``: full run + 6-node view (sent once at subscribe time)
      - ``node_state``: emitted whenever a node's ``status`` changes
      - ``run_finished``: emitted when record.status transitions to a terminal
        state (completed | failed). Generator returns afterwards.

    Computation is **derived** from ``team_run_record.json`` + ``process.json`` +
    artifact presence on disk; no runtime mutation is required. Backed off via
    ``sleeper`` to keep tests deterministic without sleeping in real time.
    """
    runs_dir = Path(runs_dir).resolve()
    repo_root = Path(repo_root).resolve()
    run_dir = _safe_run_dir(runs_dir, run_id)
    if not run_dir.exists():
        raise FileNotFoundError(f"Run not found: {run_id}")

    sleep_fn = sleeper if sleeper is not None else lambda _seconds: None

    snapshot = build_app_generation_nodes(run_id, runs_dir=runs_dir, repo_root=repo_root)
    yield {"type": "snapshot", "payload": snapshot}
    last_status_by_node: dict[str, str] = {
        str(node.get("id")): str(node.get("status") or "")
        for node in snapshot.get("nodes", [])
        if isinstance(node, dict)
    }
    last_run_status = str(snapshot.get("run", {}).get("status") or "")
    if last_run_status in {"completed", "failed"}:
        yield {
            "type": "run_finished",
            "payload": {"run_id": run_id, "status": last_run_status},
        }
        return

    iteration = 0
    while True:
        iteration += 1
        if max_iterations is not None and iteration > max_iterations:
            return
        sleep_fn(poll_interval)
        try:
            current = build_app_generation_nodes(run_id, runs_dir=runs_dir, repo_root=repo_root)
        except FileNotFoundError:
            return

        for node in current.get("nodes", []):
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id") or "")
            status = str(node.get("status") or "")
            if node_id and status and last_status_by_node.get(node_id) != status:
                last_status_by_node[node_id] = status
                yield {
                    "type": "node_state",
                    "payload": {
                        "run_id": run_id,
                        "node_id": node_id,
                        "status": status,
                        "outputs": node.get("outputs", []),
                        "output_summary": node.get("output_summary", {}),
                        "phases": node.get("phases", []),
                        "risks": node.get("risks", []),
                        "selected_variant": node.get("selected_variant"),
                    },
                }

        run_status = str(current.get("run", {}).get("status") or "")
        if run_status in {"completed", "failed"} and run_status != last_run_status:
            last_run_status = run_status
            yield {
                "type": "run_finished",
                "payload": {"run_id": run_id, "status": run_status},
            }
            return
        last_run_status = run_status


def start_app_generation_run(config: DashboardConfig, payload: dict[str, Any]) -> dict[str, Any]:
    """Create a fresh app_generation run from a PRD upload payload.

    Required:
      - prd_text (str): the PRD body, used verbatim as the run input.
    Optional:
      - prd_filename (str): used to derive a default app_slug when missing.
      - app_slug (str): overrides default slug derivation; normalized + validated.
      - executor (str): "codex" | "llm" | "rule" — per-run executor picker.
      - comparison_group_id (str): groups multi-variant runs for the workbench.
      - brief (str): overrides the auto-composed brief.
    Returns the same shape as ``start_dashboard_run`` plus ``app_slug`` and
    ``comparison_group_id`` so the workbench frontend can subscribe to the
    correct SSE channel immediately.
    """
    from growth_dev.team.app_generation import validate_app_slug

    prd_text = str(payload.get("prd_text") or "").strip()
    if not prd_text:
        raise ValueError("prd_text is required")

    raw_slug = str(
        payload.get("app_slug")
        or _derive_app_slug_from_filename(str(payload.get("prd_filename") or ""))
        or _derive_app_slug_from_prd(prd_text)
        or "generated-app"
    )
    app_slug = validate_app_slug(_normalize_app_slug(raw_slug))

    executor = str(payload.get("executor") or config.executor or "codex").strip() or "codex"
    if executor not in {"codex", "llm", "rule"}:
        raise ValueError(f"Unsupported executor: {executor}")

    comparison_group_id = str(payload.get("comparison_group_id") or f"cmp-{app_slug}")
    brief = str(payload.get("brief") or f"根据 PRD 生成本地应用：{app_slug}").strip()
    new_run_id = str(payload.get("run_id") or f"{APP_GENERATION_DOMAIN_ID}-{timestamp_slug()}")

    run_payload = {
        "run_id": new_run_id,
        "brief": brief,
        "domain": APP_GENERATION_DOMAIN_ID,
        "executor": executor,
        "model": str(payload.get("model") or config.model),
        "codex_provider": str(payload.get("codex_provider") or config.codex_provider),
        "inputs_json": {
            "app_slug": app_slug,
            "prd_text": prd_text,
            "comparison_group_id": comparison_group_id,
            "prd_filename": str(payload.get("prd_filename") or ""),
        },
    }
    result = start_dashboard_run(config, run_payload)
    return _redact(
        {
            **result,
            "app_slug": app_slug,
            "comparison_group_id": comparison_group_id,
            "executor": executor,
        }
    )


def _derive_app_slug_from_filename(filename: str) -> str:
    name = filename.strip()
    if not name:
        return ""
    stem = Path(name).stem
    return _normalize_app_slug(stem)


def _derive_app_slug_from_prd(prd_text: str) -> str:
    for line in prd_text.splitlines():
        cleaned = line.strip().lstrip("# ").strip()
        if cleaned:
            return _normalize_app_slug(cleaned)
    return ""


def _normalize_app_slug(value: str) -> str:
    text = value.strip().lower()
    out: list[str] = []
    last_dash = False
    for ch in text:
        if ch.isalnum() and ord(ch) < 128:
            out.append(ch)
            last_dash = False
        elif ch in {" ", "_", "-", "/", "."}:
            if not last_dash and out:
                out.append("-")
                last_dash = True
    slug = "".join(out).strip("-")
    return slug[:63] if slug else ""


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
                if path == "/api/app-generation/runs":
                    self._send_json({"runs": list_app_generation_runs(config.runs_dir)})
                    return
                if path.startswith("/api/app-generation/runs/"):
                    self._handle_app_generation_get(path, parsed.query)
                    return
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
            if len(parts) == 3 and parts[:2] == ["api", "app-generation"] and parts[2] == "runs":
                try:
                    length = int(self.headers.get("Content-Length") or "0")
                    raw = self.rfile.read(length).decode("utf-8") if length else "{}"
                    payload = json.loads(raw or "{}")
                    if not isinstance(payload, dict):
                        raise ValueError("JSON object is required")
                    self._send_json(start_app_generation_run(config, payload), status=HTTPStatus.ACCEPTED)
                except FileNotFoundError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                except Exception as exc:  # noqa: BLE001 - dashboard should return a visible failure.
                    self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if len(parts) == 3 and parts[:2] == ["api", "app-generation"] and parts[2] == "rerun":
                try:
                    length = int(self.headers.get("Content-Length") or "0")
                    raw = self.rfile.read(length).decode("utf-8") if length else "{}"
                    payload = json.loads(raw or "{}")
                    if not isinstance(payload, dict):
                        raise ValueError("JSON object is required")
                    self._send_json(start_app_generation_rerun(config, payload), status=HTTPStatus.ACCEPTED)
                except FileNotFoundError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                except Exception as exc:  # noqa: BLE001 - dashboard should return a visible failure.
                    self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if len(parts) == 4 and parts[:3] == ["api", "app-generation", "agent"] and parts[3] == "message":
                try:
                    length = int(self.headers.get("Content-Length") or "0")
                    raw = self.rfile.read(length).decode("utf-8") if length else "{}"
                    payload = json.loads(raw or "{}")
                    if not isinstance(payload, dict):
                        raise ValueError("JSON object is required")
                    self._send_json(handle_app_generation_agent_message(payload, runs_dir=config.runs_dir, repo_root=config.repo_root), status=HTTPStatus.OK)
                except FileNotFoundError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                except Exception as exc:  # noqa: BLE001 - dashboard should return a visible failure.
                    self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if len(parts) == 4 and parts[:3] == ["api", "app-generation", "agent"] and parts[3] == "stream":
                try:
                    length = int(self.headers.get("Content-Length") or "0")
                    raw = self.rfile.read(length).decode("utf-8") if length else "{}"
                    payload = json.loads(raw or "{}")
                    if not isinstance(payload, dict):
                        raise ValueError("JSON object is required")
                    events = stream_app_generation_agent_message(
                        payload, runs_dir=config.runs_dir, repo_root=config.repo_root
                    )
                    self._send_sse_stream(events)
                except FileNotFoundError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                except Exception as exc:  # noqa: BLE001 - dashboard should return a visible failure.
                    self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if len(parts) == 5 and parts[:3] == ["api", "app-generation", "runs"] and parts[4] == "publish-app":
                try:
                    length = int(self.headers.get("Content-Length") or "0")
                    raw = self.rfile.read(length).decode("utf-8") if length else "{}"
                    payload = json.loads(raw or "{}")
                    if not isinstance(payload, dict):
                        raise ValueError("JSON object is required")
                    payload["run_id"] = parts[3]
                    self._send_json(publish_app_generation_run(config, payload), status=HTTPStatus.OK)
                except FileNotFoundError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                except ValueError as exc:
                    error_msg = str(exc)
                    if "multiple_apps_found" in error_msg:
                        self._send_json({"error": error_msg}, status=HTTPStatus.UNPROCESSABLE_ENTITY)
                    else:
                        self._send_json({"error": error_msg}, status=HTTPStatus.BAD_REQUEST)
                except Exception as exc:  # noqa: BLE001 - dashboard should return a visible failure.
                    self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if len(parts) == 6 and parts[:3] == ["api", "app-generation", "runs"] and parts[4:] == ["preview", "start"]:
                try:
                    length = int(self.headers.get("Content-Length") or "0")
                    raw = self.rfile.read(length).decode("utf-8") if length else "{}"
                    payload = json.loads(raw or "{}")
                    if not isinstance(payload, dict):
                        raise ValueError("JSON object is required")
                    payload["run_id"] = parts[3]
                    self._send_json(start_app_generation_preview(config, payload), status=HTTPStatus.OK)
                except FileNotFoundError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                except ValueError as exc:
                    error_msg = str(exc)
                    if "app_not_published" in error_msg or "missing_publish_record" in error_msg:
                        self._send_json({"error": error_msg}, status=HTTPStatus.PRECONDITION_FAILED)
                    elif "multiple_apps_found" in error_msg:
                        self._send_json({"error": error_msg}, status=HTTPStatus.UNPROCESSABLE_ENTITY)
                    else:
                        self._send_json({"error": error_msg}, status=HTTPStatus.BAD_REQUEST)
                except Exception as exc:  # noqa: BLE001 - dashboard should return a visible failure.
                    self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if len(parts) == 6 and parts[:3] == ["api", "app-generation", "runs"] and parts[4:] == ["preview", "stop"]:
                try:
                    length = int(self.headers.get("Content-Length") or "0")
                    raw = self.rfile.read(length).decode("utf-8") if length else "{}"
                    payload = json.loads(raw or "{}")
                    if not isinstance(payload, dict):
                        raise ValueError("JSON object is required")
                    payload["run_id"] = parts[3]
                    self._send_json(stop_app_generation_preview(config, payload), status=HTTPStatus.OK)
                except FileNotFoundError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                except Exception as exc:  # noqa: BLE001 - dashboard should return a visible failure.
                    self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if len(parts) == 5 and parts[:3] == ["api", "app-generation", "runs"] and parts[4] == "patch-app":
                try:
                    length = int(self.headers.get("Content-Length") or "0")
                    raw = self.rfile.read(length).decode("utf-8") if length else "{}"
                    payload = json.loads(raw or "{}")
                    if not isinstance(payload, dict):
                        raise ValueError("JSON object is required")
                    payload["run_id"] = parts[3]
                    self._send_json(patch_app_generation_run(config, payload), status=HTTPStatus.OK)
                except FileNotFoundError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                except ValueError as exc:
                    error_msg = str(exc)
                    if "app_not_published" in error_msg:
                        self._send_json({"error": error_msg}, status=HTTPStatus.PRECONDITION_FAILED)
                    elif "target_path_outside_generated_apps" in error_msg or "anchor_not_found" in error_msg:
                        self._send_json({"error": error_msg}, status=HTTPStatus.UNPROCESSABLE_ENTITY)
                    else:
                        self._send_json({"error": error_msg}, status=HTTPStatus.BAD_REQUEST)
                except Exception as exc:  # noqa: BLE001 - dashboard should return a visible failure.
                    self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if len(parts) == 5 and parts[:3] == ["api", "app-generation", "runs"] and parts[4] == "delegate-code-repair":
                try:
                    length = int(self.headers.get("Content-Length") or "0")
                    raw = self.rfile.read(length).decode("utf-8") if length else "{}"
                    payload = json.loads(raw or "{}")
                    if not isinstance(payload, dict):
                        raise ValueError("JSON object is required")
                    payload["run_id"] = parts[3]
                    self._send_json(start_app_generation_delegate_repair(config, payload), status=HTTPStatus.OK)
                except FileNotFoundError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                except ValueError as exc:
                    error_msg = str(exc)
                    if "app_not_published" in error_msg:
                        self._send_json({"error": error_msg}, status=HTTPStatus.PRECONDITION_FAILED)
                    elif "repair" in error_msg:
                        self._send_json({"error": error_msg}, status=HTTPStatus.UNPROCESSABLE_ENTITY)
                    else:
                        self._send_json({"error": error_msg}, status=HTTPStatus.BAD_REQUEST)
                except Exception as exc:  # noqa: BLE001 - dashboard should return a visible failure.
                    self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if len(parts) == 6 and parts[:3] == ["api", "app-generation", "runs"] and parts[4:] == ["delegate-code-repair", "apply"]:
                try:
                    length = int(self.headers.get("Content-Length") or "0")
                    raw = self.rfile.read(length).decode("utf-8") if length else "{}"
                    payload = json.loads(raw or "{}")
                    if not isinstance(payload, dict):
                        raise ValueError("JSON object is required")
                    payload["run_id"] = parts[3]
                    self._send_json(apply_app_generation_delegate_repair(config, payload), status=HTTPStatus.OK)
                except FileNotFoundError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                except ValueError as exc:
                    error_msg = str(exc)
                    if "stale" in error_msg:
                        self._send_json({"error": error_msg}, status=HTTPStatus.CONFLICT)
                    elif "not_prepared" in error_msg:
                        self._send_json({"error": error_msg}, status=HTTPStatus.PRECONDITION_FAILED)
                    else:
                        self._send_json({"error": error_msg}, status=HTTPStatus.BAD_REQUEST)
                except Exception as exc:  # noqa: BLE001 - dashboard should return a visible failure.
                    self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "acceptance":
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

        def _handle_app_generation_get(self, path: str, query: str) -> None:
            parts = [part for part in path.split("/") if part]
            if len(parts) < 4:
                self._send_json({"error": "Run id is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            run_id = parts[3]
            if len(parts) == 4:
                self._send_json(build_app_generation_nodes(run_id, runs_dir=config.runs_dir, repo_root=config.repo_root))
                return
            if len(parts) == 6 and parts[4] == "artifacts" and parts[5] == "preview":
                params = parse_qs(query)
                artifact_path = (params.get("path") or [""])[0]
                self._send_json(
                    read_app_generation_artifact_preview(
                        run_id,
                        artifact_path,
                        runs_dir=config.runs_dir,
                        repo_root=config.repo_root,
                    )
                )
                return
            if len(parts) == 6 and parts[4] == "events" and parts[5] == "stream":
                events = stream_app_generation_run_events(
                    run_id,
                    runs_dir=config.runs_dir,
                    repo_root=config.repo_root,
                )
                self._send_sse_stream(events)
                return
            if len(parts) == 5 and parts[4] == "context":
                params = parse_qs(query)
                node_id = (params.get("node_id") or [""])[0]
                selected_variant = (params.get("selected_variant") or ["codex"])[0]
                if not node_id:
                    self._send_json({"error": "node_id query parameter is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                self._send_json(
                    build_app_generation_node_context(
                        run_id,
                        node_id,
                        selected_variant=selected_variant,
                        runs_dir=config.runs_dir,
                        repo_root=config.repo_root,
                    )
                )
                return
            if len(parts) == 6 and parts[4:] == ["preview", "status"]:
                try:
                    self._send_json(get_app_generation_preview_status(config, run_id))
                except FileNotFoundError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                except Exception as exc:  # noqa: BLE001 - dashboard should return a visible failure.
                    self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if len(parts) == 6 and parts[4:] == ["preview", "logs"]:
                try:
                    query_params = parse_qs(query)
                    tail = int(query_params.get("tail", ["200"])[0])
                    self._send_json(get_app_generation_preview_logs(config, run_id, tail=tail))
                except FileNotFoundError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                except Exception as exc:  # noqa: BLE001 - dashboard should return a visible failure.
                    self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
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

        def _send_sse_stream(self, events: Iterable[dict[str, Any]]) -> None:
            """Send a server-sent events stream.

            Each item must be a dict with ``type`` and ``payload`` (the same
            shape as ``agent_bridge.StreamEvent``). Items are serialized as
            ``data: <json>\\n\\n``. Connection stays open until the iterator
            terminates or the client disconnects.
            """
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            try:
                for event in events:
                    payload = _redact(event)
                    line = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    try:
                        self.wfile.write(line.encode("utf-8"))
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return
            except Exception:  # noqa: BLE001
                return

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
        ("input_prd.md", "Input PRD", "run"),
        ("requirements/brief_analysis.json", "Requirement Analysis", "run"),
        ("requirements/normalized_prd.md", "Normalized PRD", "run"),
        ("benchmark_context.md", "Benchmark Context", "run"),
        ("benchmark_context.json", "Benchmark Context JSON", "run"),
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
        ("app_contract.json", "App Contract", "run"),
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
        ("benchmark_diff.md", "Benchmark Diff", "run"),
        ("agqs_score.json", "AGQS Score", "run"),
        ("review_report.md", "Review Report", "run"),
        ("test_report.md", "Test Report", "run"),
        ("preview_instructions.md", "Preview Instructions", "run"),
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


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item is not None]
    if isinstance(value, dict):
        return [str(item) for item in value.values() if item is not None]
    return [str(value)]


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = str(item)
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _relative_to(path: Path, base: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(base).resolve())).replace("\\", "/")
    except (ValueError, OSError):
        return str(path)


_ARTIFACT_TITLES: dict[str, str] = {
    "input_prd.md": "原始 PRD",
    "requirements/normalized_prd.md": "标准化 PRD",
    "benchmark_context.md": "Benchmark 上下文",
    "benchmark_context.json": "Benchmark 上下文 JSON",
    "context_pack.md": "上下文打包",
    "app_contract.json": "应用契约",
    "acceptance_criteria.md": "验收标准",
    "planning/acceptance_coverage_matrix.json": "验收覆盖矩阵",
    "planning/tdd_plan.json": "TDD 计划",
    "codex/implementation_trace.json": "实现追踪",
    "codex/diff.patch": "实现 Diff",
    "benchmark_diff.md": "Benchmark 能力差距",
    "agqs_score.json": "AGQS 评分",
    "codex/verification_record.json": "验证记录",
    "review_report.md": "评审报告",
    "test_report.md": "测试报告",
    "preview_instructions.md": "预览说明",
    "final_report.md": "最终报告",
    "AGENTS.md": "AGENTS 守则",
    "DESIGN.md": "设计约定",
}


def _artifact_title(path: str) -> str:
    text = str(path)
    if text in _ARTIFACT_TITLES:
        return _ARTIFACT_TITLES[text]
    return Path(text).name or text


def _artifact_summary(path: Path) -> str:
    try:
        if not path.exists() or not path.is_file():
            return "未生成"
        size = path.stat().st_size
        if size == 0:
            return "空文件"
        if path.suffix.lower() == ".json":
            payload = _safe_read_json(path)
            if isinstance(payload, dict):
                keys = ", ".join(list(payload.keys())[:6])
                return f"JSON · {len(payload)} keys · {keys}"
            if isinstance(payload, list):
                return f"JSON · {len(payload)} items"
            return "JSON 产物"
        if path.suffix.lower() in {".md", ".txt", ".yaml", ".yml"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
            return (first_line[:120] + "…") if len(first_line) > 120 else (first_line or f"{size} bytes")
        return f"{size} bytes"
    except OSError:
        return "无法读取"


_SKILL_STAGES: dict[str, str] = {
    "using_agent_skills": "route",
    "spec_driven_development": "spec",
    "context_engineering": "context",
    "planning_and_task_breakdown": "plan",
    "incremental_implementation": "implement",
    "test_driven_development": "verify",
    "code_review_and_quality": "review",
    "ai_coding_quality_review": "review",
    "debugging_and_error_recovery": "recover",
}


_SKILL_REASONS: dict[str, str] = {
    "using_agent_skills": "为本次生成链路选择合适的 skill 组合。",
    "spec_driven_development": "把 PRD 拆成可验证的目标、范围、假设和验收口径。",
    "context_engineering": "压缩上下文，避免把长文直接喂给 LLM。",
    "planning_and_task_breakdown": "把验收标准拆成可执行 slices 和 TDD plan。",
    "incremental_implementation": "按 slice 受控生成代码，保持隔离 worktree。",
    "test_driven_development": "验证生成应用满足验收标准。",
    "code_review_and_quality": "评审 diff、产物质量与发布就绪。",
    "ai_coding_quality_review": "审视 AI 生成代码的架构、契约和安全漂移。",
    "debugging_and_error_recovery": "verification 失败时定位根因并恢复。",
}


def _skill_stage(skill_id: str) -> str:
    return _SKILL_STAGES.get(skill_id, "stage")


def _skill_reason(skill_id: str) -> str:
    return _SKILL_REASONS.get(skill_id, f"Apply {skill_id} for this node.")


def _coverage_score(run_dir: Path) -> float:
    matrix = _safe_read_json(run_dir / "planning" / "acceptance_coverage_matrix.json")
    if not isinstance(matrix, dict):
        return 0.6 if (run_dir / "acceptance_criteria.md").exists() else 0.4
    rows = matrix.get("rows") if isinstance(matrix.get("rows"), list) else matrix.get("coverage")
    if not isinstance(rows, list) or not rows:
        return 0.7
    covered = sum(1 for row in rows if isinstance(row, dict) and row.get("status") in {"covered", "passed", "ok"})
    return max(0.5, min(1.0, covered / len(rows))) if rows else 0.7


def _engineering_score(run_dir: Path, outputs: list[dict[str, Any]], risks: list[dict[str, Any]]) -> float:
    contract_ok = (run_dir / "app_contract.json").exists()
    trace_ok = (run_dir / "codex" / "implementation_trace.json").exists()
    plan_ok = (run_dir / "planning" / "tdd_plan.json").exists()
    output_ready = sum(1 for item in outputs if isinstance(item, dict) and item.get("exists")) / max(1, len(outputs))
    base = 0.5 + 0.15 * contract_ok + 0.15 * trace_ok + 0.1 * plan_ok + 0.1 * output_ready
    base -= 0.05 * min(3, len(risks))
    return max(0.4, min(1.0, base))


def _scope_boundary_score(run_dir: Path) -> float:
    contract = _safe_read_json(run_dir / "app_contract.json")
    if not isinstance(contract, dict):
        return 0.55
    fixed = sum(1 for key in ("frontend", "backend", "storage", "database") if str(contract.get(key, "")))
    return max(0.5, min(1.0, 0.55 + 0.1 * fixed))


def _file_hash(path: Path) -> str:
    try:
        if not path.exists() or not path.is_file():
            return ""
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()
    except OSError:
        return ""


def _slug_from_contract(contract: dict[str, Any]) -> str:
    if not isinstance(contract, dict):
        return ""
    slug = str(contract.get("app_slug") or "").strip()
    if slug:
        return slug
    name = str(contract.get("app_name") or "").strip().lower()
    if not name:
        return ""
    cleaned: list[str] = []
    for ch in name:
        if ch.isalnum():
            cleaned.append(ch)
        elif ch in {" ", "_", "-"}:
            cleaned.append("-")
    slug = "".join(cleaned).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug


def _app_generation_provider_statuses(*, repo_root: Path = Path(".")) -> list[dict[str, Any]]:
    from growth_dev.team.agent_bridge import provider_status

    return [
        provider_status("codex", repo_root=repo_root),
        provider_status("pi_agent", repo_root=repo_root),
        provider_status("llm", repo_root=repo_root),
    ]


def _variant_usage(node: dict[str, Any], selected_variant: str) -> dict[str, Any]:
    variants = node.get("variants") if isinstance(node, dict) else []
    if isinstance(variants, list):
        for variant in variants:
            if isinstance(variant, dict) and str(variant.get("variant_id", "")) == selected_variant:
                usage = variant.get("usage")
                if isinstance(usage, dict):
                    return dict(usage)
    node_usage = node.get("usage") if isinstance(node, dict) else None
    if isinstance(node_usage, dict):
        return dict(node_usage)
    return {
        "prompt_tokens": "unknown",
        "completion_tokens": "unknown",
        "total_tokens": "unknown",
        "estimated_cost": "unknown",
        "usage_source": "none",
    }


def _node_available_actions(node_id: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = [
        {"type": "explain_node", "target_node_id": node_id, "label": "解释当前节点"},
        {"type": "compare_variants", "target_node_id": node_id, "variants": ["rule", "codex"], "label": "对比 rule 与 codex"},
        {"type": "suggest_input_patch", "target_node_id": node_id, "label": "建议调整节点输入"},
        {"type": "rerun_from_node", "target_node_id": node_id, "label": "从此节点重跑"},
        {"type": "patch_app", "target_node_id": node_id, "label": "修改已发布应用"},
        {"type": "delegate_code_repair", "target_node_id": node_id, "label": "委托 Code Agent 修复应用"},
    ]
    if node_id != "implementation":
        actions.insert(3, {"type": "select_variant", "target_node_id": node_id, "label": "选择下游使用的 variant"})
    return actions


def _revision_artifacts(items: list[Any]) -> list[dict[str, Any]]:
    revisions: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return revisions
    for item in items:
        if not isinstance(item, dict):
            continue
        revisions.append(
            {
                "path": str(item.get("path", "")),
                "status": str(item.get("status", "")),
                "content_hash": str(item.get("content_hash", "")),
                "title": str(item.get("title", "")),
                "summary": str(item.get("summary", "")),
                "preview": dict(item.get("preview") or {}),
            }
        )
    return revisions


def _agent_actions_for_mode(mode: str, context: dict[str, Any], message: str) -> list[dict[str, Any]]:
    node_id = str(context.get("node_id", "")) if isinstance(context, dict) else ""
    source_run_id = str(context.get("run_id", "")) if isinstance(context, dict) else ""
    comparison_group_id = str(context.get("comparison_group_id", "")) if isinstance(context, dict) else ""
    selected_variant = str(context.get("selected_variant", "codex")) if isinstance(context, dict) else "codex"
    if mode == "compare":
        return [
            {
                "type": "compare_variants",
                "target_node_id": node_id,
                "variants": ["rule", "codex"],
                "summary": "对比 rule 与 codex 在此节点的输出和 usage。",
            }
        ]
    if mode == "edit":
        return [
            {
                "type": "suggest_input_patch",
                "target_node_id": node_id,
                "patch_summary": message[:80] or "建议调整节点输入。",
                "override_instructions": message,
            }
        ]
    if mode == "rerun":
        return [
            {
                "type": "rerun_from_node",
                "source_run_id": source_run_id,
                "rerun_from_node": node_id,
                "selected_variant": selected_variant,
                "override_instructions": message,
                "comparison_group_id": comparison_group_id,
            }
        ]
    if mode == "clarify":
        return [
            {
                "type": "ask_clarification",
                "target_node_id": node_id,
                "question": message or "需要补充哪些上下文？",
            }
        ]
    return [
        {
            "type": "explain_node",
            "target_node_id": node_id,
            "summary": f"节点 {node_id} 的输入、过程、输出与风险摘要。",
        }
    ]


def _agent_response_message(mode: str, context: dict[str, Any], message: str) -> str:
    node_id = str(context.get("node_id", "")) if isinstance(context, dict) else ""
    selected_variant = str(context.get("selected_variant", "codex")) if isinstance(context, dict) else "codex"
    app_slug = str(context.get("app_slug", "")) if isinstance(context, dict) else ""
    inputs = context.get("inputs", []) if isinstance(context, dict) else []
    outputs = context.get("outputs", []) if isinstance(context, dict) else []
    ready_outputs = [item for item in outputs if isinstance(item, dict) and item.get("status") == "ready"]
    risk_count = len(context.get("risks", [])) if isinstance(context, dict) else 0
    head = f"应用 {app_slug} · 节点 {node_id} · variant={selected_variant}"
    if mode == "compare":
        return f"{head}\n对比说明：rule 提供确定性 baseline；codex 提供更细致的实现细节。当前节点有 {len(ready_outputs)} 份产物已就绪。"
    if mode == "edit":
        return f"{head}\n收到调整诉求：{message[:120]}。已生成 suggest_input_patch 待你确认后写入新 run inputs。"
    if mode == "rerun":
        return f"{head}\n已准备从该节点创建新 run 的说明，不会修改旧 run。"
    if mode == "clarify":
        return f"{head}\n需要澄清：{message[:120]}"
    return f"{head}\n该节点有 {len(inputs)} 项输入、{len(ready_outputs)} 项就绪输出、{risk_count} 项风险记录。"


def _node_phases(
    node_id: str,
    process_state: dict[str, Any],
    tool_calls: list[dict[str, Any]],
    output_refs: list[dict[str, Any]],
    run_dir: Path,
) -> list[dict[str, Any]]:
    """Derive phase-level timeline for a node.

    For ``implementation`` nodes: parse ``implementation_trace.json`` steps.
    For other nodes: use ``APP_GENERATION_NODE_PHASE_TEMPLATES`` + artifact existence.
    """

    if node_id == "implementation":
        return _implementation_phases(run_dir, tool_calls, output_refs)
    template = APP_GENERATION_NODE_PHASE_TEMPLATES.get(node_id)
    if not template:
        return _fallback_phase(node_id, process_state, output_refs)
    phases: list[dict[str, Any]] = []
    output_map = {str(ref.get("path")): ref for ref in output_refs if isinstance(ref, dict)}
    for spec in template:
        phase_id = str(spec.get("id", ""))
        label = str(spec.get("label", phase_id))
        artifact_paths = [str(p) for p in spec.get("artifacts", [])]
        matched_artifacts = [p for p in artifact_paths if output_map.get(p, {}).get("exists")]
        all_exist = all(output_map.get(p, {}).get("exists") for p in artifact_paths)
        any_exist = any(output_map.get(p, {}).get("exists") for p in artifact_paths)
        status = "completed" if all_exist else ("running" if any_exist else "pending")
        phases.append({
            "id": phase_id,
            "label": label,
            "status": status,
            "started_at": "",
            "finished_at": "",
            "summary": f"{len(matched_artifacts)}/{len(artifact_paths)} 产物就绪" if artifact_paths else label,
            "artifacts": matched_artifacts,
        })
    return phases


def _implementation_phases(run_dir: Path, tool_calls: list[dict[str, Any]], output_refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse ``implementation_trace.json`` steps as phases for the ``implementation`` node."""

    trace = _read_implementation_trace(run_dir)
    if not isinstance(trace, dict) or not trace.get("steps"):
        return _fallback_phase("implementation", {}, output_refs)
    phases: list[dict[str, Any]] = []
    for step in trace.get("steps", []):
        if not isinstance(step, dict):
            continue
        phases.append({
            "id": str(step.get("id", "")),
            "label": str(step.get("title", "")),
            "status": str(step.get("status", "pending")),
            "started_at": str(step.get("started_at", "")),
            "finished_at": str(step.get("finished_at", "")),
            "summary": str(step.get("summary", "")),
            "artifacts": [str(p) for p in step.get("artifacts", []) if p],
        })
    fix_slice_path = run_dir / "codex" / "fix_slice_record.json"
    if fix_slice_path.exists():
        fix_record = _safe_read_json(fix_slice_path)
        status = "completed" if fix_record.get("status") == "completed" else "failed"
        phases.append({
            "id": "fix_slice",
            "label": "Benchmark Fix Slice",
            "status": status,
            "started_at": str(fix_record.get("started_at", "")),
            "finished_at": str(fix_record.get("finished_at", "")),
            "summary": f"{len(fix_record.get('remediated_capabilities', []))} 能力修复" if status == "completed" else "修复失败",
            "artifacts": ["codex/fix_slice_prompt.md", "codex/fix_slice_record.json"],
        })
    return phases


def _fallback_phase(node_id: str, process_state: dict[str, Any], output_refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Single-phase fallback when no template is available."""

    any_output = any(ref.get("exists") for ref in output_refs if isinstance(ref, dict))
    status = "completed" if any_output else ("running" if process_state.get("status") == "running" else "pending")
    return [{
        "id": "execute",
        "label": "执行节点",
        "status": status,
        "started_at": "",
        "finished_at": "",
        "summary": f"{sum(1 for ref in output_refs if ref.get('exists'))}/{len(output_refs)} 产物就绪" if output_refs else "执行中",
        "artifacts": [str(ref.get("path")) for ref in output_refs if ref.get("exists")],
    }]


def _build_app_generation_node(
    definition: dict[str, Any],
    run_dir: Path,
    repo_root: Path,
    record: dict[str, Any],
    process: dict[str, Any],
    comparison_group_id: str,
) -> dict[str, Any]:
    node_id = str(definition["id"])
    input_refs = [_app_artifact_ref(path, run_dir, repo_root) for path in definition.get("inputs", [])]
    output_refs = [_app_artifact_ref(path, run_dir, repo_root) for path in _node_output_paths(definition, run_dir)]
    process_state = _node_process(definition, run_dir, record, process)
    risks = _node_risks(node_id, record, process_state, output_refs, run_dir)
    _annotate_validation_status(input_refs, risks)
    _annotate_validation_status(output_refs, risks)
    usage = _node_usage(node_id, run_dir, record)
    scores = _node_scores(node_id, run_dir, output_refs, risks)
    tool_calls = _node_tool_calls(node_id, run_dir, record)
    status = _node_status(input_refs, output_refs, process_state, risks, record)
    selected_variant = "codex" if node_id == "implementation" or str(record.get("executor", "")) == "codex" else "rule"
    variants = _node_variants(node_id, output_refs, usage, scores, risks, selected_variant)
    phases = _node_phases(node_id, process_state, tool_calls, output_refs, run_dir)
    return {
        "id": node_id,
        "title": str(definition.get("title", node_id)),
        "summary": str(definition.get("summary", "")),
        "status": status,
        "selected_variant": selected_variant,
        "inputs": input_refs,
        "process": process_state,
        "outputs": output_refs,
        "output_summary": _output_summary(output_refs),
        "phases": phases,
        "skills": _node_skills(definition),
        "tool_calls": tool_calls,
        "usage": usage,
        "scores": scores,
        "risks": risks,
        "variants": variants,
        "comparison": _node_comparison(node_id, variants, selected_variant),
        "comparison_group_id": comparison_group_id,
    }


def _node_output_paths(definition: dict[str, Any], run_dir: Path) -> list[str]:
    outputs = [str(item) for item in definition.get("outputs", [])]
    node_id = str(definition.get("id", ""))
    if node_id == "context_contract":
        for path in ("benchmark_context.md", "benchmark_context.json"):
            if (run_dir / path).exists():
                outputs.append(path)
    if node_id == "planning_tdd":
        slices_dir = run_dir / "slices"
        if slices_dir.exists():
            outputs.extend(_relative_to(path, run_dir) for path in sorted(slices_dir.glob("*.yaml")))
    if node_id == "implementation":
        for path in ("benchmark_diff.md", "agqs_score.json"):
            if (run_dir / path).exists():
                outputs.append(path)
        contract = _safe_read_json(run_dir / "app_contract.json")
        generated_dir = str(contract.get("generated_app_dir", ""))
        worktree_dir = run_dir / "worktree" / generated_dir
        for relative in _string_list(contract.get("required_files", [])):
            outputs.append(f"worktree/{generated_dir}/{relative}" if generated_dir else f"worktree/{relative}")
        if worktree_dir.exists():
            for path in sorted(worktree_dir.rglob("*")):
                if path.is_file():
                    outputs.append(_relative_to(path, run_dir))
    return _dedupe_strings(outputs)


def _app_artifact_ref(path: str, run_dir: Path, repo_root: Path) -> dict[str, Any]:
    scope = "repo" if path in {"AGENTS.md", "DESIGN.md"} else "run"
    target = repo_root / path if scope == "repo" else run_dir / path
    exists = target.exists() and target.is_file()
    size = target.stat().st_size if exists else 0
    content_hash = _file_hash(target) if exists else ""
    summary = _artifact_summary(target) if exists else "未生成"
    read_url = ""
    if exists and scope == "run":
        read_url = f"/api/runs/{quote(run_dir.name)}/artifact?path={quote(path)}"
    preview = _app_artifact_preview_ref(path, target, run_dir.name, exists, scope, size)
    return {
        "path": path,
        "scope": scope,
        "title": _artifact_title(path),
        "status": "ready" if exists else "missing",
        "validation_status": "success" if exists else "pending",
        "summary": summary,
        "content_hash": content_hash,
        "read_url": read_url,
        "preview": preview,
        "exists": exists,
        "size_bytes": size,
    }


def _annotate_validation_status(refs: list[dict[str, Any]], risks: list[dict[str, Any]]) -> None:
    """Mutate ``refs`` so each artifact carries an evidence-driven ``validation_status``.

    Rules:
      - missing artifact (``exists=False``) stays ``pending``.
      - existing artifact referenced by a ``blocked`` risk becomes ``error``.
      - existing artifact referenced by a ``warning`` risk becomes ``warning``
        (but not downgraded from ``error``).
      - otherwise existing artifact is ``success``.
    Risks attach to artifacts via ``risk.artifact_refs`` (list of paths).
    """

    blocked_paths: set[str] = set()
    warning_paths: set[str] = set()
    for risk in risks:
        if not isinstance(risk, dict):
            continue
        severity = str(risk.get("severity", "")).strip()
        refs_list = risk.get("artifact_refs", [])
        if not isinstance(refs_list, list):
            continue
        for entry in refs_list:
            ref_path = str(entry).strip()
            if not ref_path:
                continue
            if severity == "blocked":
                blocked_paths.add(ref_path)
            elif severity == "warning":
                warning_paths.add(ref_path)
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        if not ref.get("exists"):
            ref["validation_status"] = "pending"
            continue
        path = str(ref.get("path", ""))
        if path in blocked_paths:
            ref["validation_status"] = "error"
        elif path in warning_paths:
            ref["validation_status"] = "warning"
        else:
            ref["validation_status"] = "success"


def _output_summary(refs: list[dict[str, Any]]) -> dict[str, int]:
    """Aggregate validation outcomes across ``refs`` for compact node badges."""

    summary = {"total": 0, "ready": 0, "success": 0, "warning": 0, "error": 0, "pending": 0}
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        summary["total"] += 1
        if ref.get("exists"):
            summary["ready"] += 1
        status = str(ref.get("validation_status", "pending"))
        if status in summary:
            summary[status] += 1
    return summary


def _app_artifact_preview_ref(path: str, target: Path, run_id: str, exists: bool, scope: str, size: int) -> dict[str, Any]:
    if not exists or scope != "run" or not path.startswith("artifacts/"):
        return {"enabled": False, "kind": "missing", "mime_type": "", "size_bytes": size, "read_url": ""}
    mime_type = _preview_mime_type(target)
    return {
        "enabled": True,
        "kind": _preview_kind(target, mime_type),
        "mime_type": mime_type,
        "size_bytes": size,
        "read_url": f"/api/app-generation/runs/{quote(run_id)}/artifacts/preview?path={quote(path)}",
    }


def _preview_mime_type(path: Path) -> str:
    guessed, _encoding = mimetypes.guess_type(str(path))
    if guessed:
        return guessed
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "text/markdown"
    if suffix in {".json"}:
        return "application/json"
    if suffix in {".yaml", ".yml"}:
        return "application/yaml"
    if suffix in {".js", ".mjs"}:
        return "text/javascript"
    return "application/octet-stream"


def _preview_kind(path: Path, mime_type: str) -> str:
    suffix = path.suffix.lower()
    if mime_type.startswith("image/"):
        return "image"
    if mime_type == "application/pdf" or suffix == ".pdf":
        return "pdf"
    if suffix in {".js", ".mjs", ".ts", ".tsx", ".jsx", ".css", ".html", ".json", ".yaml", ".yml", ".py", ".sh"}:
        return "code"
    if mime_type.startswith("text/") or suffix in {".md", ".markdown", ".txt", ".log"}:
        return "text"
    return "binary"


def _node_process(definition: dict[str, Any], run_dir: Path, record: dict[str, Any], process: dict[str, Any]) -> dict[str, Any]:
    agent_ids = [str(item) for item in definition.get("agents", [])]
    agent_runs = [item for item in record.get("agent_runs", []) if isinstance(item, dict) and str(item.get("agent_id", "")) in agent_ids]
    events = [
        event
        for event in _read_events(run_dir)
        if str(event.get("agent_id", "")) in agent_ids or _event_matches_node(str(definition.get("id", "")), event)
    ][-8:]
    logs = _latest_log_lines(run_dir, max_lines=6)
    statuses = [str(item.get("status", "")) for item in agent_runs if item.get("status")]
    record_status = str(record.get("status", ""))
    process_status = str(process.get("status", ""))
    if any(status in {"failed", "blocked"} for status in statuses):
        status = "blocked"
    elif statuses and all(status == "completed" for status in statuses):
        status = "completed"
    elif any(status == "running" for status in statuses) or (
        record_status not in {"completed", "failed", "blocked"}
        and process_status in {"running", "starting"}
        and str(definition.get("id")) == "implementation"
    ):
        status = "running"
    else:
        status = "not_started"
    return {
        "status": status,
        "agent_ids": agent_ids,
        "agent_runs": [_redact(item) for item in agent_runs],
        "events": events,
        "logs": logs,
        "summary": _node_process_summary(str(definition.get("id", "")), status),
    }


def _event_matches_node(node_id: str, event: dict[str, Any]) -> bool:
    event_name = str(event.get("event", ""))
    return (
        node_id in {"skill_routing", "prd_input", "prd_normalization", "context_contract", "planning_tdd"}
        and event_name in {"complex_task_artifacts_generated", "memory_recall_generated"}
    ) or (node_id == "preview_delivery" and event_name == "run_completed")


def _node_process_summary(node_id: str, status: str) -> str:
    labels = {
        "completed": "节点已有可审计产物。",
        "running": "节点正在执行或等待后台进程结束。",
        "blocked": "节点存在阻塞或风险事件。",
        "not_started": "尚未观察到该节点执行证据。",
    }
    return f"{node_id}: {labels.get(status, '状态未知。')}"


def _node_skills(definition: dict[str, Any]) -> list[dict[str, Any]]:
    primary = str(definition.get("primary_skill", ""))
    companions = [str(item) for item in definition.get("companion_skills", [])]
    result: list[dict[str, Any]] = []
    if primary:
        result.append(
            {
                "id": primary,
                "stage": _skill_stage(primary),
                "priority": "P0",
                "role": "primary",
                "why": _skill_reason(primary),
                "inputs": [str(item) for item in definition.get("inputs", [])],
                "outputs": [str(item) for item in definition.get("outputs", [])],
                "status": "used",
            }
        )
    for skill in companions:
        result.append(
            {
                "id": skill,
                "stage": _skill_stage(skill),
                "priority": "P0",
                "role": "companion",
                "why": _skill_reason(skill),
                "inputs": [str(item) for item in definition.get("inputs", [])],
                "outputs": [str(item) for item in definition.get("outputs", [])],
                "status": "recommended",
            }
        )
    return result


def _node_tool_calls(node_id: str, run_dir: Path, record: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    trace = _read_implementation_trace(run_dir)
    if node_id == "implementation" and trace:
        for step in trace.get("steps", []) if isinstance(trace.get("steps"), list) else []:
            if not isinstance(step, dict):
                continue
            step_id = str(step.get("id", ""))
            if step_id == "codex_running":
                calls.append(
                    {
                        "tool_call_id": "codex_exec_001",
                        "tool_name": "codex exec",
                        "provider": "codex",
                        "node_id": node_id,
                        "status": str(step.get("status", trace.get("status", "unknown"))),
                        "started_at": str(step.get("started_at", "")),
                        "finished_at": str(step.get("finished_at", "")),
                        "input_summary": "使用 prompt bundle 生成本地应用。",
                        "output_summary": str(step.get("summary", "生成 diff 和 implementation trace。")),
                        "artifact_refs": ["codex/implementation_trace.json", "codex/diff.patch"],
                        "risk_events": _string_list(trace.get("risk_events", [])),
                    }
                )
    if node_id == "verification":
        verification = _safe_read_json(run_dir / "codex" / "verification_record.json")
        for index, command in enumerate(verification.get("commands", []) if isinstance(verification.get("commands"), list) else [], start=1):
            if not isinstance(command, dict):
                continue
            calls.append(
                {
                    "tool_call_id": f"verification_command_{index:03d}",
                    "tool_name": "verification command",
                    "provider": "local",
                    "node_id": node_id,
                    "status": "completed" if command.get("exit_code") == 0 else "failed",
                    "started_at": str(command.get("started_at", "")),
                    "finished_at": str(command.get("finished_at", "")),
                    "input_summary": str(command.get("command", "")),
                    "output_summary": f"exit_code={command.get('exit_code')}",
                    "artifact_refs": ["codex/verification_record.json", "test_report.md"],
                    "risk_events": _string_list(verification.get("risk_events", [])),
                }
            )
    if not calls:
        events = _read_events(run_dir)
        for index, event in enumerate(events[-4:], start=1):
            if _event_matches_node(node_id, event):
                calls.append(
                    {
                        "tool_call_id": f"run_event_{index:03d}",
                        "tool_name": str(event.get("event", "run event")),
                        "provider": "team_runtime",
                        "node_id": node_id,
                        "status": str(event.get("status", "observed")),
                        "started_at": str(event.get("created_at", "")),
                        "finished_at": str(event.get("created_at", "")),
                        "input_summary": "",
                        "output_summary": str(event.get("summary", event.get("event", ""))),
                        "artifact_refs": [],
                        "risk_events": [],
                    }
                )
    return calls


def _node_usage(node_id: str, run_dir: Path, record: dict[str, Any]) -> dict[str, Any]:
    if node_id in {"skill_routing", "prd_input", "prd_normalization", "context_contract", "planning_tdd", "review_quality", "verification", "preview_delivery"}:
        base = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated_cost": "unknown", "usage_source": "rule", "confidence": "baseline"}
    else:
        base = {"prompt_tokens": "unknown", "completion_tokens": "unknown", "total_tokens": "unknown", "estimated_cost": "unknown", "usage_source": "none", "confidence": "missing"}
    observed = _parse_observed_usage(run_dir)
    if node_id == "implementation" and observed:
        return observed
    return base


def _parse_observed_usage(run_dir: Path) -> dict[str, Any]:
    stdout_path = run_dir / "codex" / "stdout.jsonl"
    if stdout_path.exists():
        for line in stdout_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else payload.get("token_usage")
            if isinstance(usage, dict):
                normalized = _normalize_usage(usage)
                normalized["usage_source"] = "codex/stdout.jsonl"
                normalized["confidence"] = "observed"
                return normalized
    for path in (run_dir / "codex" / "last_message.json", run_dir / "code_run_record.json", run_dir / "codex" / "implementation_trace.json"):
        payload = _safe_read_json(path)
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        if usage:
            normalized = _normalize_usage(usage)
            normalized["usage_source"] = _relative_to(path, run_dir)
            normalized["confidence"] = "observed"
            return normalized
    return {}


def _normalize_usage(usage: dict[str, Any]) -> dict[str, Any]:
    prompt = usage.get("prompt_tokens", usage.get("input_tokens", "unknown"))
    completion = usage.get("completion_tokens", usage.get("output_tokens", "unknown"))
    total = usage.get("total_tokens", "unknown")
    if total == "unknown" and isinstance(prompt, int | float) and isinstance(completion, int | float):
        total = int(prompt) + int(completion)
    return {
        "prompt_tokens": prompt if prompt != "" else "unknown",
        "completion_tokens": completion if completion != "" else "unknown",
        "total_tokens": total if total != "" else "unknown",
        "elapsed_ms": usage.get("elapsed_ms", "unknown"),
        "estimated_cost": usage.get("estimated_cost", "unknown"),
        "model": usage.get("model", "unknown"),
        "provider": usage.get("provider", "codex"),
    }


def _node_scores(node_id: str, run_dir: Path, outputs: list[dict[str, Any]], risks: list[dict[str, Any]]) -> dict[str, Any]:
    existing = [item for item in outputs if item.get("exists")]
    completeness = len(existing) / max(1, len(outputs))
    coverage = _coverage_score(run_dir)
    engineering = _engineering_score(run_dir, outputs, risks)
    ui_fit = 0.8 if (run_dir / "worktree").exists() else (0.55 if node_id == "implementation" else 0.7)
    risk_score = min(1.0, len(risks) * 0.2)
    scores = {
        "goal_clarity": round(max(0.5, completeness), 2),
        "scope_boundary": round(_scope_boundary_score(run_dir), 2),
        "acceptance_coverage": round(coverage, 2),
        "engineering_readiness": round(engineering, 2),
        "ui_fit": round(ui_fit, 2),
        "product_effect": round((completeness + coverage + engineering + ui_fit) / 4, 2),
        "risk_score": round(risk_score, 2),
        "score_source": "deterministic_rubric_v1",
    }
    agqs = _safe_read_json(run_dir / "agqs_score.json")
    if node_id in {"implementation", "review_quality", "verification", "preview_delivery"} and agqs:
        capability_items = agqs.get("capability_coverage", []) if isinstance(agqs.get("capability_coverage"), list) else []
        covered = sum(1 for item in capability_items if isinstance(item, dict) and item.get("status") == "covered")
        total = len(capability_items)
        scores.update(
            {
                "benchmark_agqs": agqs.get("overall_agqs", "unknown"),
                "benchmark_hard_gate": agqs.get("hard_gate_status", "unknown"),
                "benchmark_capability_coverage": round(covered / total, 2) if total else "unknown",
                "score_source": "deterministic_rubric_v1+agqs_static_parity",
            }
        )
    return scores


def _node_risks(node_id: str, record: dict[str, Any], process_state: dict[str, Any], outputs: list[dict[str, Any]], run_dir: Path) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    for index, risk in enumerate(_string_list(record.get("risk_events", [])), start=1):
        risks.append({"id": f"record_risk_{index}", "severity": "warning", "summary": risk, "artifact_refs": []})
    missing = [item["path"] for item in outputs if not item.get("exists")]
    if missing and node_id not in {"implementation"}:
        risks.append({"id": "missing_outputs", "severity": "warning", "summary": "部分节点输出尚未生成。", "artifact_refs": missing[:6]})
    contract = _safe_read_json(run_dir / "app_contract.json")
    if node_id in {"context_contract", "implementation", "verification"} and contract:
        target_stack = contract.get("target_stack") if isinstance(contract.get("target_stack"), dict) else {}
        if target_stack.get("database") not in {"none", None}:
            risks.append({"id": "database_not_allowed", "severity": "blocked", "summary": "v1 不允许生成数据库依赖。", "artifact_refs": ["app_contract.json"]})
        if target_stack.get("storage") not in {"localStorage", None}:
            risks.append({"id": "storage_not_localstorage", "severity": "blocked", "summary": "v1 持久化层只能是浏览器 localStorage。", "artifact_refs": ["app_contract.json"]})
    if node_id in {"implementation", "review_quality", "verification", "preview_delivery"}:
        agqs = _safe_read_json(run_dir / "agqs_score.json")
        if agqs:
            for event in _string_list(agqs.get("blocking_events", [])):
                risks.append(
                    {
                        "id": _risk_id(event),
                        "severity": "blocked",
                        "summary": _benchmark_risk_summary(event),
                        "artifact_refs": ["benchmark_diff.md", "agqs_score.json"],
                    }
                )
            for warning in _string_list(agqs.get("warnings", [])):
                risks.append(
                    {
                        "id": _risk_id(warning),
                        "severity": "warning",
                        "summary": _benchmark_risk_summary(warning),
                        "artifact_refs": ["benchmark_diff.md", "agqs_score.json"],
                    }
                )
    return risks


def _risk_id(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", str(value)).strip("_").lower()
    return text or "risk"


def _benchmark_risk_summary(value: str) -> str:
    text = str(value)
    prefix = "benchmark_parity_missing:"
    if text.startswith(prefix):
        return f"Benchmark 能力缺失：{text[len(prefix):]}"
    return text


def _node_status(
    inputs: list[dict[str, Any]],
    outputs: list[dict[str, Any]],
    process_state: dict[str, Any],
    risks: list[dict[str, Any]],
    record: dict[str, Any],
) -> str:
    if any(item.get("severity") == "blocked" for item in risks):
        return "blocked"
    if process_state.get("status") == "running":
        return "running"
    if process_state.get("status") == "blocked":
        return "blocked"
    if outputs and all(item.get("exists") for item in outputs[: max(1, min(3, len(outputs)))]):
        return "warning" if risks else "completed"
    if inputs and all(item.get("exists") for item in inputs):
        return "ready"
    if str(record.get("status", "")) in {"failed", "blocked"}:
        return "blocked"
    return "not_started"


def _node_variants(
    node_id: str,
    outputs: list[dict[str, Any]],
    codex_usage: dict[str, Any],
    scores: dict[str, Any],
    risks: list[dict[str, Any]],
    selected_variant: str,
) -> list[dict[str, Any]]:
    rule_outputs = outputs if node_id != "implementation" else [item for item in outputs if item["path"] in {"app_contract.json", "planning/tdd_plan.json"}]
    codex_status = "completed" if outputs and any(item.get("exists") for item in outputs) else "not_available"
    return [
        {
            "variant_id": "rule",
            "strategy": "rule",
            "status": "completed" if rule_outputs else "not_available",
            "outputs": rule_outputs,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated_cost": "unknown", "usage_source": "rule"},
            "scores": scores,
            "risks": risks,
        },
        {
            "variant_id": "codex",
            "strategy": "codex",
            "status": codex_status if node_id == "implementation" else ("completed" if selected_variant == "codex" else "not_available"),
            "outputs": outputs,
            "usage": codex_usage if node_id == "implementation" else {"prompt_tokens": "unknown", "completion_tokens": "unknown", "total_tokens": "unknown", "estimated_cost": "unknown", "usage_source": "none"},
            "scores": scores,
            "risks": risks,
        },
    ]


def _node_comparison(node_id: str, variants: list[dict[str, Any]], selected_variant: str) -> dict[str, Any]:
    if node_id == "implementation":
        summary = "代码实现节点固定走 Codex/LLM；rule 只作为路径、契约、风险和评分 baseline。"
    else:
        summary = "rule 提供确定性 baseline；Codex/LLM 可作为解释、建议和后续重跑来源。"
    return {
        "summary": summary,
        "recommended_variant": selected_variant,
        "reasons": [
            "rule token 成本为 0，用于结构化检查。",
            "Codex/LLM usage 缺失时显示 unknown，不做估算。",
        ],
    }


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
    text = re.sub(r"(?<!process)\.env\b", "<env-file>", text)
    return text
