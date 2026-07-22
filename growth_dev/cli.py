from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any

from .adapters.base import MockAdapter
from .benchmark import DEFAULT_FRAMEWORKS, benchmark, load_task, run_framework, run_mock
from .mock_site import MockServer
from .models import TaskSpec
from .reporting import write_report
from .tasks import default_task_spec, write_task_package
from .utils import ensure_dir, now_iso, read_json, timestamp_slug, write_json
from .team.yaml_io import load_yaml_subset

_BACKGROUND_PROCESSES: list[subprocess.Popen] = []


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="growth-dev")
    subparsers = parser.add_subparsers(dest="command", required=True)

    xhs = subparsers.add_parser("xhs", help="XHS benchmark commands")
    xhs_sub = xhs.add_subparsers(dest="xhs_command", required=True)

    init_cmd = xhs_sub.add_parser("init", help="Write the task package")
    init_cmd.add_argument("--output", default="tasks/current")
    init_cmd.set_defaults(func=_cmd_init)

    auth_cmd = xhs_sub.add_parser("auth", help="Prepare the browser profile folder")
    auth_cmd.add_argument("--framework", required=True)
    auth_cmd.add_argument("--profile-dir", default=".local/browser-profiles/xhs")
    auth_cmd.add_argument("--open-browser", action="store_true")
    auth_cmd.set_defaults(func=_cmd_auth)

    serve_cmd = xhs_sub.add_parser("serve-mock", help="Run the local mock site")
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=int, default=8787)
    serve_cmd.add_argument("--open-browser", action="store_true")
    serve_cmd.set_defaults(func=_cmd_serve_mock)

    run_cmd = xhs_sub.add_parser("run", help="Run a single framework")
    run_cmd.add_argument("--framework", required=True)
    run_cmd.add_argument("--task-path", default="tasks/current/task.yaml")
    run_cmd.add_argument("--runs-dir", default="runs")
    run_cmd.add_argument("--keyword", default=None)
    run_cmd.add_argument("--top-n", type=int, default=None)
    run_cmd.add_argument("--candidate-pool", type=int, default=None)
    run_cmd.set_defaults(func=_cmd_run)

    bench_cmd = xhs_sub.add_parser("benchmark", help="Run the comparison suite")
    bench_cmd.add_argument("--suite", default="pilot")
    bench_cmd.add_argument("--task-path", default="tasks/current/task.yaml")
    bench_cmd.add_argument("--runs-dir", default="runs")
    bench_cmd.add_argument("--frameworks", default="")
    bench_cmd.set_defaults(func=_cmd_benchmark)

    report_cmd = xhs_sub.add_parser("report", help="Generate a report from a run directory")
    report_cmd.add_argument("--run-id", required=True)
    report_cmd.add_argument("--runs-dir", default="runs")
    report_cmd.set_defaults(func=_cmd_report)

    team = subparsers.add_parser("team", help="Agent team runtime commands")
    team_sub = team.add_subparsers(dest="team_command", required=True)

    team_init = team_sub.add_parser("init", help="Write a domain-backed task package")
    team_init.add_argument("--domain", default="xhs_browser_benchmark")
    team_init.add_argument("--domains-dir", default="domains")
    team_init.add_argument("--output", default="tasks/current")
    team_init.set_defaults(func=_cmd_team_init)

    team_run = team_sub.add_parser("run", help="Run the deterministic agent team")
    team_run.add_argument("--brief", required=True)
    team_run.add_argument("--domain", default="xhs_browser_benchmark")
    team_run.add_argument("--domains-dir", default="domains")
    team_run.add_argument("--runs-dir", default="runs")
    team_run.add_argument("--run-id", default=None)
    team_run.add_argument("--inputs-json", default="")
    team_run.add_argument("--executor", choices=["deterministic", "codex"], default="deterministic")
    team_run.add_argument("--model", default="gpt-5.3-codex")
    team_run.add_argument("--reasoning-effort", default="medium")
    team_run.add_argument("--codex-binary", default="codex")
    team_run.add_argument("--codex-provider", choices=["default", "aicodemirror"], default="default")
    team_run.add_argument("--env-file", default=".env")
    team_run.add_argument("--repo-root", default=".")
    team_run.add_argument("--task-yaml-path", default="")
    team_run.add_argument("--domain-yaml-path", default="")
    team_run.add_argument("--skill-dir", default="")
    _add_complex_task_args(team_run)
    team_run.set_defaults(func=_cmd_team_run)

    team_status = team_sub.add_parser("status", help="Show a team run record status")
    team_status.add_argument("--run-id", required=True)
    team_status.add_argument("--runs-dir", default="runs")
    team_status.add_argument("--summary", action="store_true", help="Show a compact human-readable status")
    team_status.set_defaults(func=_cmd_team_status)

    team_workspace = team_sub.add_parser("workspace", help="Show or refresh task workspace artifacts")
    team_workspace_sub = team_workspace.add_subparsers(dest="workspace_command", required=True)
    team_workspace_refresh = team_workspace_sub.add_parser("refresh", help="Refresh task workspace, journal, and tool context artifacts")
    team_workspace_refresh.add_argument("--run-id", required=True)
    team_workspace_refresh.add_argument("--runs-dir", default="runs")
    team_workspace_refresh.add_argument("--json", action="store_true", dest="json_output")
    team_workspace_refresh.set_defaults(func=_cmd_team_workspace_refresh)
    team_workspace_show = team_workspace_sub.add_parser("show", help="Show task workspace artifacts")
    team_workspace_show.add_argument("--run-id", required=True)
    team_workspace_show.add_argument("--runs-dir", default="runs")
    team_workspace_show.add_argument("--json", action="store_true", dest="json_output")
    team_workspace_show.set_defaults(func=_cmd_team_workspace_show)

    team_report = team_sub.add_parser("report", help="Show the final report for a team run")
    team_report.add_argument("--run-id", required=True)
    team_report.add_argument("--runs-dir", default="runs")
    team_report.set_defaults(func=_cmd_team_report)

    team_watch = team_sub.add_parser("watch", help="Watch a team run status, logs, gates, and next actions")
    team_watch.add_argument("--run-id", required=True)
    team_watch.add_argument("--runs-dir", default="runs")
    team_watch.add_argument("--interval", type=float, default=1.5)
    team_watch.add_argument("--once", action="store_true")
    team_watch.set_defaults(func=_cmd_team_watch)

    team_diff = team_sub.add_parser("diff", help="Show the uncommitted diff from a run worktree")
    team_diff.add_argument("--run-id", required=True)
    team_diff.add_argument("--runs-dir", default="runs")
    team_diff.set_defaults(func=_cmd_team_diff)

    team_apply = team_sub.add_parser("apply", help="Apply a completed run worktree diff to the repository")
    team_apply.add_argument("--run-id", required=True)
    team_apply.add_argument("--runs-dir", default="runs")
    team_apply.add_argument("--repo-root", default=".")
    team_apply.set_defaults(func=_cmd_team_apply)

    team_release = team_sub.add_parser("release", help="Generate release readiness reports")
    team_release_sub = team_release.add_subparsers(dest="release_command", required=True)
    team_release_readiness = team_release_sub.add_parser("readiness", help="Generate local release readiness and PR draft artifacts")
    team_release_readiness.add_argument("--run-id", required=True)
    team_release_readiness.add_argument("--runs-dir", default="runs")
    team_release_readiness.add_argument("--repo-root", default=".")
    team_release_readiness.add_argument("--json", action="store_true", dest="json_output")
    team_release_readiness.set_defaults(func=_cmd_team_release_readiness)
    team_release_staging = team_release_sub.add_parser("staging-readiness", help="Generate staging readiness gate artifacts")
    team_release_staging.add_argument("--run-id", required=True)
    team_release_staging.add_argument("--runs-dir", default="runs")
    team_release_staging.add_argument("--json", action="store_true", dest="json_output")
    team_release_staging.set_defaults(func=_cmd_team_release_staging_readiness)
    team_release_production = team_release_sub.add_parser("production-readiness", help="Generate production readiness gate artifacts")
    team_release_production.add_argument("--run-id", required=True)
    team_release_production.add_argument("--runs-dir", default="runs")
    team_release_production.add_argument("--json", action="store_true", dest="json_output")
    team_release_production.set_defaults(func=_cmd_team_release_production_readiness)
    team_release_rehearsal = team_release_sub.add_parser("staging-rehearsal", help="Run local staging rehearsal after staging readiness")
    team_release_rehearsal.add_argument("--run-id", required=True)
    team_release_rehearsal.add_argument("--runs-dir", default="runs")
    team_release_rehearsal.add_argument("--repo-root", default=".")
    team_release_rehearsal.add_argument("--json", action="store_true", dest="json_output")
    team_release_rehearsal.set_defaults(func=_cmd_team_release_staging_rehearsal)

    team_pr = team_sub.add_parser("pr", help="Create GitHub draft PRs and observe CI checks")
    team_pr_sub = team_pr.add_subparsers(dest="pr_command", required=True)
    team_pr_draft = team_pr_sub.add_parser("draft", help="Push the current branch when requested and create a GitHub Draft PR")
    team_pr_draft.add_argument("--run-id", required=True)
    team_pr_draft.add_argument("--runs-dir", default="runs")
    team_pr_draft.add_argument("--repo-root", default=".")
    team_pr_draft.add_argument("--base", default="main")
    team_pr_draft.add_argument("--push", action="store_true")
    team_pr_draft.add_argument("--json", action="store_true", dest="json_output")
    team_pr_draft.set_defaults(func=_cmd_team_pr_draft)

    team_pr_status = team_pr_sub.add_parser("status", help="Refresh GitHub PR checks and write CI status artifacts")
    team_pr_status.add_argument("--run-id", required=True)
    team_pr_status.add_argument("--runs-dir", default="runs")
    team_pr_status.add_argument("--repo-root", default=".")
    team_pr_status.add_argument("--json", action="store_true", dest="json_output")
    team_pr_status.set_defaults(func=_cmd_team_pr_status)

    team_retrospective = team_sub.add_parser("retrospective", help="Generate deterministic run retrospectives")
    team_retrospective_sub = team_retrospective.add_subparsers(dest="retrospective_command", required=True)
    team_retrospective_generate = team_retrospective_sub.add_parser("generate", help="Generate retrospective artifacts")
    retrospective_target = team_retrospective_generate.add_mutually_exclusive_group(required=True)
    retrospective_target.add_argument("--run-id", default=None)
    retrospective_target.add_argument("--all", dest="generate_all", action="store_true")
    team_retrospective_generate.add_argument("--runs-dir", default="runs")
    team_retrospective_generate.add_argument("--limit", type=int, default=50)
    team_retrospective_generate.set_defaults(func=_cmd_team_retrospective_generate)

    team_memory = team_sub.add_parser("memory", help="Export team run memory to Obsidian Markdown")
    team_memory_sub = team_memory.add_subparsers(dest="memory_command", required=True)
    team_memory_export = team_memory_sub.add_parser("export", help="Export run summaries to an Obsidian vault")
    memory_target = team_memory_export.add_mutually_exclusive_group(required=True)
    memory_target.add_argument("--run-id", default=None)
    memory_target.add_argument("--all", dest="export_all", action="store_true")
    team_memory_export.add_argument("--runs-dir", default="runs")
    team_memory_export.add_argument("--vault-dir", required=True)
    team_memory_export.add_argument("--limit", type=int, default=50)
    team_memory_export.set_defaults(func=_cmd_team_memory_export)

    team_memory_search = team_memory_sub.add_parser("search", help="Search historical learning summaries")
    team_memory_search.add_argument("--query", required=True)
    team_memory_search.add_argument("--runs-dir", default="runs")
    team_memory_search.add_argument("--domain-id", default="")
    team_memory_search.add_argument("--task-type", default="")
    team_memory_search.add_argument("--limit", type=int, default=5)
    team_memory_search.add_argument("--refresh-missing", action="store_true")
    team_memory_search.add_argument("--json", action="store_true", dest="json_output")
    team_memory_search.set_defaults(func=_cmd_team_memory_search)

    team_dashboard = team_sub.add_parser("serve-dashboard", help="Run the local Agent Team dashboard")
    team_dashboard.add_argument("--host", default="127.0.0.1")
    team_dashboard.add_argument("--port", type=int, default=8790)
    team_dashboard.add_argument("--runs-dir", default="runs")
    team_dashboard.add_argument("--domains-dir", default="domains")
    team_dashboard.add_argument("--dashboard-dir", default="dashboard")
    team_dashboard.add_argument("--repo-root", default=".")
    team_dashboard.add_argument("--codex-binary", default="codex")
    team_dashboard.add_argument("--codex-provider", choices=["default", "aicodemirror"], default="default")
    team_dashboard.add_argument("--env-file", default=".env")
    team_dashboard.add_argument("--model", default="gpt-5.3-codex")
    team_dashboard.add_argument("--reasoning-effort", default="medium")
    team_dashboard.add_argument("--executor", choices=["deterministic", "codex"], default="codex")
    _add_complex_task_args(team_dashboard)
    team_dashboard.add_argument("--open-browser", action="store_true")
    team_dashboard.set_defaults(func=_cmd_team_serve_dashboard)

    app = subparsers.add_parser("app", help="Application generation commands")
    app_sub = app.add_subparsers(dest="app_command", required=True)
    app_generate = app_sub.add_parser("generate", help="Generate a local prototype app from a PRD")
    app_generate.add_argument("--prd-file", default="")
    app_generate.add_argument("--prd-text", default="")
    app_generate.add_argument("--app-slug", required=True)
    app_generate.add_argument("--ui-style", default="")
    app_generate.add_argument("--runs-dir", default="runs")
    app_generate.add_argument("--domains-dir", default="domains")
    app_generate.add_argument("--run-id", default=None)
    app_generate.add_argument("--executor", choices=["deterministic", "codex"], default="codex")
    app_generate.add_argument("--model", default="gpt-5.3-codex")
    app_generate.add_argument("--reasoning-effort", default="medium")
    app_generate.add_argument("--codex-binary", default="codex")
    app_generate.add_argument("--codex-provider", choices=["default", "aicodemirror"], default="default")
    app_generate.add_argument("--env-file", default=".env")
    app_generate.add_argument("--repo-root", default=".")
    app_generate.add_argument("--task-yaml-path", default="")
    app_generate.add_argument("--domain-yaml-path", default="")
    app_generate.add_argument("--skill-dir", default="")
    app_generate.add_argument("--strategy-kb", default="", help="Strategy KB manifest path used to enrich node business context.")
    app_generate.add_argument("--strategy-kb-query-script", default="", help="Path to local-skills query_strategy_kb.py.")
    app_generate.add_argument("--strategy-kb-python", default="python3", help="Python executable used to run the Strategy KB query script.")
    app_generate.add_argument("--strategy-kb-top-k", type=int, default=3, help="Number of Strategy KB passages to attach per node.")
    app_generate.add_argument("--api-doc-index", default="", help="Prebuilt api_doc_matcher api_doc_index.json to snapshot into generated apps.")
    app_generate.add_argument("--api-detail-doc", default="", help="API detail markdown doc used to build an api_doc_matcher index during generation.")
    app_generate.add_argument("--api-validation-doc", default="", help="API validation markdown doc used to build an api_doc_matcher index during generation.")
    app_generate.add_argument("--api-extra-detail-doc", action="append", default=[], help="Additional standalone API detail markdown doc; repeat for multiple docs.")
    app_generate.add_argument("--shell-kind", default="", help="Shell kind (e.g., report_generator). If not provided, will be inferred from task/domain/skill.")
    _add_complex_task_args(app_generate)
    app_generate.add_argument("--foreground", action="store_true")
    app_generate.set_defaults(func=_cmd_app_generate)

    app_preview = app_sub.add_parser("preview", help="Manage app preview servers")
    app_preview_sub = app_preview.add_subparsers(dest="preview_command", required=True)

    app_preview_start = app_preview_sub.add_parser("start", help="Start a preview server for a generated app")
    app_preview_start.add_argument("--run-id", required=True)
    app_preview_start.add_argument("--runs-dir", default="runs")
    app_preview_start.add_argument("--port", type=int, default=8788)
    app_preview_start.set_defaults(func=_cmd_app_preview_start)

    app_preview_stop = app_preview_sub.add_parser("stop", help="Stop a running preview server")
    app_preview_stop.add_argument("--run-id", required=True)
    app_preview_stop.add_argument("--runs-dir", default="runs")
    app_preview_stop.set_defaults(func=_cmd_app_preview_stop)

    app_preview_list = app_preview_sub.add_parser("list", help="List active preview servers")
    app_preview_list.add_argument("--runs-dir", default="runs")
    app_preview_list.set_defaults(func=_cmd_app_preview_list)

    appcheck = app_sub.add_parser("appcheck", help="Validate generated app config and acceptance contracts")
    appcheck_sub = appcheck.add_subparsers(dest="appcheck_command", required=True)
    appcheck_config = appcheck_sub.add_parser("config", help="Validate app.config.json")
    appcheck_config.add_argument("--run-id", required=True)
    appcheck_config.add_argument("--runs-dir", default="runs")
    appcheck_config.set_defaults(func=_cmd_appcheck_config)
    appcheck_acceptance = appcheck_sub.add_parser("acceptance", help="Validate app acceptance derivation")
    appcheck_acceptance.add_argument("--run-id", required=True)
    appcheck_acceptance.add_argument("--runs-dir", default="runs")
    appcheck_acceptance.set_defaults(func=_cmd_appcheck_acceptance)

    code_cmd = subparsers.add_parser("code", help="Run the Codex-backed coding loop")
    _add_team_run_args(code_cmd)
    code_cmd.set_defaults(func=_cmd_code_alias)

    review_cmd = subparsers.add_parser("review", help="Show a run review report")
    review_cmd.add_argument("--run-id", required=True)
    review_cmd.add_argument("--runs-dir", default="runs")
    review_cmd.set_defaults(func=_cmd_review_alias)

    test_cmd = subparsers.add_parser("test", help="Show a run test report")
    test_cmd.add_argument("--run-id", required=True)
    test_cmd.add_argument("--runs-dir", default="runs")
    test_cmd.set_defaults(func=_cmd_test_alias)

    report_alias = subparsers.add_parser("report", help="Show a team run final report")
    report_alias.add_argument("--run-id", required=True)
    report_alias.add_argument("--runs-dir", default="runs")
    report_alias.set_defaults(func=_cmd_team_report)

    return parser


def _add_team_run_args(command: argparse.ArgumentParser) -> None:
    command.add_argument("--brief", required=True)
    command.add_argument("--domain", default="xhs_browser_benchmark")
    command.add_argument("--domains-dir", default="domains")
    command.add_argument("--runs-dir", default="runs")
    command.add_argument("--run-id", default=None)
    command.add_argument("--inputs-json", default="")
    command.add_argument("--executor", choices=["deterministic", "codex"], default="codex")
    command.add_argument("--model", default="gpt-5.3-codex")
    command.add_argument("--reasoning-effort", default="medium")
    command.add_argument("--codex-binary", default="codex")
    command.add_argument("--codex-provider", choices=["default", "aicodemirror"], default="default")
    command.add_argument("--env-file", default=".env")
    command.add_argument("--repo-root", default=".")
    _add_complex_task_args(command)
    command.add_argument("--foreground", action="store_true")


def _add_complex_task_args(command: argparse.ArgumentParser) -> None:
    command.add_argument("--planning-mode", choices=["deterministic", "llm_assisted", "auto"], default="auto")
    command.add_argument("--requirements-model", default="")
    command.add_argument("--requirements-reasoning-effort", choices=["low", "medium", "high"], default="medium")
    command.add_argument("--requirements-env-file", default="", help="Optional env file for the requirements model provider; defaults to --env-file when omitted")


def _load_task(path_value: str | None) -> TaskSpec:
    if path_value and Path(path_value).exists():
        return load_task(Path(path_value))
    return default_task_spec()


def _cmd_init(args: argparse.Namespace) -> int:
    files = write_task_package(Path(args.output))
    for name, path in files.items():
        print(f"{name}: {path}")
    return 0


def _cmd_auth(args: argparse.Namespace) -> int:
    profile_dir = ensure_dir(Path(args.profile_dir) / args.framework)
    state = {
        "framework": args.framework,
        "logged_in": False,
        "manual_login_required": True,
        "profile_dir": str(profile_dir),
        "updated_at": now_iso(),
        "notes": "Open the real browser for manual login when the framework runner is wired.",
    }
    write_json(profile_dir / "session_state.json", state)
    print(f"Profile prepared at {profile_dir}")
    print("Manual login is required when a real runner is connected.")
    if args.open_browser:
        webbrowser.open("http://127.0.0.1:8787/")
    return 0


def _cmd_serve_mock(args: argparse.Namespace) -> int:
    server = MockServer(host=args.host, port=args.port)
    base_url = server.start()
    print(f"Mock site running at {base_url}")
    if args.open_browser:
        webbrowser.open(base_url)
    try:
        while True:
            import time

            time.sleep(0.5)
    except KeyboardInterrupt:
        server.stop()
        return 0


def _task_override(task: TaskSpec, args: argparse.Namespace) -> TaskSpec:
    if args.keyword is not None:
        task.keyword = args.keyword
    if args.top_n is not None:
        task.top_n = args.top_n
    if args.candidate_pool is not None:
        task.candidate_pool = args.candidate_pool
    return task


def _cmd_run(args: argparse.Namespace) -> int:
    task = _task_override(_load_task(args.task_path), args)
    runs_dir = ensure_dir(Path(args.runs_dir))
    run_dir = ensure_dir(runs_dir / f"{task.task_id}-{timestamp_slug()}-{args.framework}")
    if args.framework == "mock":
        result = run_mock(task, run_dir)
    else:
        result = run_framework(task, args.framework, run_dir)
    write_json(run_dir / "result.json", result.to_dict())
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _cmd_benchmark(args: argparse.Namespace) -> int:
    task = _load_task(args.task_path)
    if args.frameworks:
        frameworks = [item.strip() for item in args.frameworks.split(",") if item.strip()]
    elif args.suite == "mock":
        frameworks = ["mock"]
    else:
        frameworks = DEFAULT_FRAMEWORKS
    outcome = benchmark(task, frameworks=frameworks, runs_dir=Path(args.runs_dir), suite=args.suite)
    print(outcome.artifacts["report_md"])
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    runs_dir = Path(args.runs_dir)
    run_dir = runs_dir / args.run_id
    run_record_path = run_dir / "run_record.json"
    if not run_record_path.exists():
        print(f"Run record not found: {run_record_path}", file=sys.stderr)
        return 1
    payload = read_json(run_record_path)
    from .models import RunRecord, TaskSpec
    from .scoring import framework_score

    record = RunRecord(
        run_id=payload["run_id"],
        task=TaskSpec.from_dict(payload["task"]),
        adapter_results=[],
        started_at=payload.get("started_at", ""),
        finished_at=payload.get("finished_at", ""),
        base_dir=Path(payload.get("base_dir", "runs")),
    )
    for result_payload in payload.get("adapter_results", []):
        from .models import AdapterResult

        record.adapter_results.append(AdapterResult.from_dict(result_payload))

    from .benchmark import expected_notes

    expected = expected_notes(record.task)
    scores = [framework_score(result, expected) for result in record.adapter_results]
    artifacts = write_report(record, scores, run_dir)
    print(artifacts["report_md"])
    return 0


def _cmd_team_init(args: argparse.Namespace) -> int:
    files = write_task_package(
        Path(args.output),
        domain_id=args.domain,
        domains_dir=Path(args.domains_dir),
    )
    for name, path in files.items():
        print(f"{name}: {path}")
    return 0


def _cmd_team_run(args: argparse.Namespace) -> int:
    from .team.runtime import TeamRuntime

    inputs = _parse_inputs_json(args.inputs_json)
    if str(getattr(args, "domain", "")) == "app_generation":
        repo_root = Path(str(getattr(args, "repo_root", "") or "."))
        path_error = _augment_app_generation_inputs(inputs, args, repo_root)
        if path_error:
            print(path_error, file=sys.stderr)
            return 2
    runtime = TeamRuntime.from_domain(
        args.domain,
        domains_dir=Path(args.domains_dir),
        runs_dir=Path(args.runs_dir),
        repo_root=Path(args.repo_root),
        executor=args.executor,
        codex_binary=args.codex_binary,
        codex_model=args.model,
        codex_reasoning_effort=args.reasoning_effort,
        codex_provider=args.codex_provider,
        codex_env_file=Path(args.env_file),
        planning_mode=args.planning_mode,
        requirements_model=args.requirements_model,
        requirements_reasoning_effort=args.requirements_reasoning_effort,
        requirements_env_file=Path(args.requirements_env_file) if args.requirements_env_file else None,
    )
    record = runtime.run(args.brief, inputs=inputs, run_id=args.run_id)
    print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2))
    return 0 if record.status == "completed" else 1


def _cmd_app_preview_start(args: argparse.Namespace) -> int:
    from .team.preview import PreviewRunRequest, start_preview

    runs_dir = Path(args.runs_dir)
    run_dir = runs_dir / args.run_id
    contract_path = run_dir / "app_contract.json"
    if not contract_path.exists():
        print(f"App contract not found: {contract_path}", file=sys.stderr)
        return 1

    contract = read_json(contract_path)
    app_slug = str(contract.get("app_slug") or "")
    generated_app_dir_value = str(contract.get("generated_app_dir") or "")
    if not app_slug or not generated_app_dir_value:
        print("app_contract.json missing app_slug or generated_app_dir", file=sys.stderr)
        return 1

    app_dir = (run_dir / generated_app_dir_value).resolve()
    if not app_dir.exists():
        print(f"Generated app directory not found: {app_dir}", file=sys.stderr)
        return 1

    preview = contract.get("preview") if isinstance(contract.get("preview"), dict) else {}
    command_value = preview.get("command") or "node server.js"
    if isinstance(command_value, list):
        preview_command = [str(item) for item in command_value]
    else:
        preview_command = str(command_value).split()

    request = PreviewRunRequest(
        run_id=args.run_id,
        app_slug=app_slug,
        generated_app_dir=app_dir,
        preview_command=preview_command,
        preferred_port=args.port,
        repo_root=runs_dir.resolve().parent,
    )
    result = start_preview(request, runs_dir=runs_dir)

    print(f"Status: {result.status}")
    print(f"PID: {result.pid}")
    print(f"URL: {result.url}")
    print(f"Log: {result.log_path}")
    print(f"Health: {result.health_status} ({result.message})")
    print(f"Record: {result.record_path}")
    return 0 if result.status == "running" else 1


def _cmd_app_preview_stop(args: argparse.Namespace) -> int:
    from .team.preview import stop_preview

    record_path = Path(args.runs_dir) / args.run_id / "preview" / "preview_run_record.json"
    if not record_path.exists():
        print(f"Preview record not found: {record_path}", file=sys.stderr)
        return 1
    result = stop_preview(record_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_app_preview_list(args: argparse.Namespace) -> int:
    from .team.preview import list_active_previews

    active = list_active_previews(Path(args.runs_dir))
    if not active:
        print("No active previews.")
        return 0
    for record in active:
        print(
            f"{record.get('run_id')}\t{record.get('app_slug')}\t"
            f"pid={record.get('pid')}\tport={record.get('port')}\t"
            f"url={record.get('url')}"
        )
    return 0


def _cmd_code_alias(args: argparse.Namespace) -> int:
    if getattr(args, "foreground", False):
        return _cmd_team_run(args)
    return _cmd_code_background(args)


def _augment_app_generation_inputs(inputs: dict, args: argparse.Namespace, repo_root: Path) -> str:
    """Assemble four-source paths into ``inputs`` for app_generation runs.

    Skips assembly when the caller already supplied any four-source key (e.g. the
    Dashboard透传). Returns an error string when path validation fails, else "".
    """
    if any(key in inputs for key in ("task_yaml_path", "domain_yaml_path", "skill_dir")):
        return ""
    task_raw = str(getattr(args, "task_yaml_path", "") or "").strip()
    domain_raw = str(getattr(args, "domain_yaml_path", "") or "").strip()
    skill_arg_raw = str(getattr(args, "skill_dir", "") or "").strip()
    if not any((task_raw, domain_raw, skill_arg_raw)):
        return ""
    task_yaml_path = _resolve_app_input_path(task_raw or "tasks/current/task.yaml", repo_root)
    domain_yaml_path = _resolve_app_input_path(domain_raw or "tasks/current/domain.yaml", repo_root)
    skill_dir_raw = skill_arg_raw or str(_derive_skill_dir(task_yaml_path)).strip()
    skill_dir = _resolve_app_input_path(skill_dir_raw, repo_root) if skill_dir_raw else Path("")
    path_error = _validate_app_generation_input_paths(task_yaml_path, domain_yaml_path, skill_dir)
    if path_error:
        return path_error
    inputs["task_yaml_path"] = str(task_yaml_path)
    inputs["domain_yaml_path"] = str(domain_yaml_path)
    inputs["skill_dir"] = str(skill_dir)
    return ""


def _augment_strategy_kb_inputs(inputs: dict[str, Any], args: argparse.Namespace, repo_root: Path) -> str:
    kb_raw = str(getattr(args, "strategy_kb", "") or "").strip()
    script_raw = str(getattr(args, "strategy_kb_query_script", "") or "").strip()
    python_raw = str(getattr(args, "strategy_kb_python", "") or "python3").strip() or "python3"
    top_k = int(getattr(args, "strategy_kb_top_k", 3) or 3)
    if not any((kb_raw, script_raw)):
        return ""
    if not kb_raw or not script_raw:
        return "strategy_kb and strategy_kb_query_script must be provided together"
    if top_k < 1:
        return "strategy_kb_top_k must be >= 1"
    kb_path = _resolve_app_input_path(kb_raw, repo_root)
    query_script = _resolve_app_input_path(script_raw, repo_root)
    if not kb_path.exists() or not kb_path.is_file():
        return f"strategy_kb not found: {kb_path}"
    if not query_script.exists() or not query_script.is_file():
        return f"strategy_kb_query_script not found: {query_script}"
    inputs["strategy_kb"] = str(kb_path)
    inputs["strategy_kb_query_script"] = str(query_script)
    inputs["strategy_kb_python"] = python_raw
    inputs["strategy_kb_top_k"] = top_k
    return ""


def _augment_api_doc_inputs(inputs: dict[str, Any], args: argparse.Namespace, repo_root: Path) -> str:
    index_raw = str(getattr(args, "api_doc_index", "") or "").strip()
    detail_raw = str(getattr(args, "api_detail_doc", "") or "").strip()
    validation_raw = str(getattr(args, "api_validation_doc", "") or "").strip()
    extra_detail_raw = [str(item or "").strip() for item in getattr(args, "api_extra_detail_doc", []) if str(item or "").strip()]
    if not any((index_raw, detail_raw, validation_raw, extra_detail_raw)):
        return ""
    if index_raw:
        index_path = _resolve_app_input_path(index_raw, repo_root)
        if not index_path.exists() or not index_path.is_file():
            return f"api_doc_index not found: {index_path}"
        inputs["api_doc_index"] = str(index_path)
    if detail_raw or validation_raw:
        if not detail_raw or not validation_raw:
            return "api_detail_doc and api_validation_doc must be provided together"
        detail_path = _resolve_app_input_path(detail_raw, repo_root)
        validation_path = _resolve_app_input_path(validation_raw, repo_root)
        if not detail_path.exists() or not detail_path.is_file():
            return f"api_detail_doc not found: {detail_path}"
        if not validation_path.exists() or not validation_path.is_file():
            return f"api_validation_doc not found: {validation_path}"
        inputs["api_detail_doc"] = str(detail_path)
        inputs["api_validation_doc"] = str(validation_path)
    if extra_detail_raw:
        extra_paths = [_resolve_app_input_path(item, repo_root) for item in extra_detail_raw]
        missing_extra = next((path for path in extra_paths if not path.exists() or not path.is_file()), None)
        if missing_extra:
            return f"api_extra_detail_doc not found: {missing_extra}"
        inputs["api_extra_detail_docs"] = [str(path) for path in extra_paths]
    return ""


def _cmd_app_generate(args: argparse.Namespace) -> int:
    prd_text = str(getattr(args, "prd_text", "") or "").strip()
    prd_file = str(getattr(args, "prd_file", "") or "").strip()
    if not prd_text and not prd_file:
        print("PRD input is required: pass --prd-text or --prd-file", file=sys.stderr)
        return 2
    repo_root = Path(str(getattr(args, "repo_root", "") or "."))
    inputs: dict[str, Any] = {
        "app_slug": args.app_slug,
    }
    path_error = _augment_app_generation_inputs(inputs, args, repo_root)
    if path_error:
        print(path_error, file=sys.stderr)
        return 2
    path_error = _augment_strategy_kb_inputs(inputs, args, repo_root)
    if path_error:
        print(path_error, file=sys.stderr)
        return 2
    path_error = _augment_api_doc_inputs(inputs, args, repo_root)
    if path_error:
        print(path_error, file=sys.stderr)
        return 2
    if prd_text:
        inputs["prd_text"] = prd_text
    if prd_file:
        inputs["prd_file"] = prd_file
    if getattr(args, "ui_style", ""):
        inputs["ui_style"] = args.ui_style
    if getattr(args, "shell_kind", ""):
        inputs["shell_kind"] = args.shell_kind
    args.brief = f"根据 PRD 生成本地应用：{args.app_slug}"
    args.domain = "app_generation"
    args.inputs_json = json.dumps(inputs, ensure_ascii=False)
    return _cmd_code_alias(args)


def _resolve_app_input_path(value: str, repo_root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return repo_root / path


def _derive_skill_dir(task_yaml_path: Path) -> str:
    if not task_yaml_path.exists() or not task_yaml_path.is_file():
        return ""
    try:
        task = load_yaml_subset(task_yaml_path)
    except Exception:
        return ""
    explicit = str(task.get("skill_artifact_dir") or "").strip()
    if explicit:
        candidate = Path(explicit)
        return str(candidate if candidate.is_absolute() else task_yaml_path.parent.parent.parent / candidate)
    skill_ref = task.get("skill_ref") if isinstance(task.get("skill_ref"), dict) else {}
    ref_dir = str(skill_ref.get("dir") or "").strip()
    if ref_dir:
        candidate = Path(ref_dir)
        return str(candidate if candidate.is_absolute() else task_yaml_path.parent.parent.parent / candidate)
    skill_id = str(task.get("skill_id") or "").strip()
    if skill_id:
        return str(Path("document-to-skill-engineering-package") / "build" / skill_id)
    return ""


def _validate_app_generation_input_paths(task_yaml_path: Path, domain_yaml_path: Path, skill_dir: Path) -> str:
    if not task_yaml_path.exists() or not task_yaml_path.is_file():
        return f"task_yaml_path not found: {task_yaml_path}"
    if not domain_yaml_path.exists() or not domain_yaml_path.is_file():
        return f"domain_yaml_path not found: {domain_yaml_path}"
    if not str(skill_dir):
        return "skill_dir is required or must be derivable from task yaml"
    if not skill_dir.exists() or not skill_dir.is_dir():
        return f"skill_dir not found: {skill_dir}"
    return ""


def _cmd_appcheck_config(args: argparse.Namespace) -> int:
    from .team.app_generation import validate_app_config

    run_dir = Path(args.runs_dir) / str(args.run_id)
    errors = validate_app_config(run_dir)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"app.config.json ok: {args.run_id}")
    return 0


def _cmd_appcheck_acceptance(args: argparse.Namespace) -> int:
    from .team.app_generation import validate_app_acceptance

    run_dir = Path(args.runs_dir) / str(args.run_id)
    errors = validate_app_acceptance(run_dir)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"acceptance ok: {args.run_id}")
    return 0


def _cmd_code_background(args: argparse.Namespace) -> int:
    run_id = args.run_id or f"{args.domain}-{timestamp_slug()}"
    runs_dir = Path(args.runs_dir)
    run_dir = ensure_dir(runs_dir / run_id)
    command = _background_team_run_command(args, run_id)
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
    stdout_path = run_dir / "background_stdout.log"
    stderr_path = run_dir / "background_stderr.log"
    stdout_handle = stdout_path.open("a", encoding="utf-8")
    stderr_handle = stderr_path.open("a", encoding="utf-8")
    try:
        process = subprocess.Popen(
            command,
            cwd=Path(args.repo_root),
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
    _BACKGROUND_PROCESSES.append(process)
    if args.executor == "deterministic":
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
    print(f"Run started: {run_id}")
    print(f"PID: {process.pid}")
    print(f"Watch: python -m growth_dev.cli team watch --run-id {run_id}")
    print(f"Artifacts: {run_dir}/")
    return 0


def _background_team_run_command(args: argparse.Namespace, run_id: str) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "growth_dev.cli",
        "team",
        "run",
        "--run-id",
        run_id,
        "--brief",
        args.brief,
        "--domain",
        args.domain,
        "--domains-dir",
        args.domains_dir,
        "--runs-dir",
        args.runs_dir,
        "--inputs-json",
        args.inputs_json,
        "--executor",
        args.executor,
        "--model",
        args.model,
        "--reasoning-effort",
        args.reasoning_effort,
        "--codex-binary",
        args.codex_binary,
        "--codex-provider",
        args.codex_provider,
        "--env-file",
        args.env_file,
        "--repo-root",
        args.repo_root,
        "--planning-mode",
        args.planning_mode,
        "--requirements-model",
        args.requirements_model,
        "--requirements-reasoning-effort",
        args.requirements_reasoning_effort,
    ]
    if args.requirements_env_file:
        command.extend(["--requirements-env-file", args.requirements_env_file])
    return command


def _redacted_command(command: list[str]) -> list[str]:
    redacted: list[str] = []
    skip_next = False
    for index, item in enumerate(command):
        if skip_next:
            skip_next = False
            continue
        if item in {"--env-file", "--requirements-env-file"} and index + 1 < len(command):
            redacted.extend([item, "<env-file>"])
            skip_next = True
        else:
            redacted.append(item)
    return redacted


def _cmd_team_status(args: argparse.Namespace) -> int:
    from .team.runtime import TeamRuntime

    record_path = Path(args.runs_dir) / args.run_id / "team_run_record.json"
    if not record_path.exists():
        print(f"Team run record not found: {record_path}", file=sys.stderr)
        return 1
    record = TeamRuntime.load_record(args.run_id, runs_dir=Path(args.runs_dir))
    if getattr(args, "summary", False):
        print(_team_status_summary(record, Path(args.runs_dir) / args.run_id))
    else:
        print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _cmd_team_report(args: argparse.Namespace) -> int:
    run_dir = Path(args.runs_dir) / args.run_id
    report_path = run_dir / "final_report.md"
    if not report_path.exists():
        print(f"Final report not found: {report_path}", file=sys.stderr)
        return 1
    print(report_path.read_text(encoding="utf-8"))
    return 0


def _cmd_team_watch(args: argparse.Namespace) -> int:
    run_dir = Path(args.runs_dir) / args.run_id
    if not run_dir.exists():
        print(f"Run not found: {run_dir}", file=sys.stderr)
        return 1
    while True:
        snapshot = _team_watch_snapshot(args.run_id, run_dir)
        print(snapshot)
        if args.once or _watch_terminal_state(run_dir):
            return 0
        time.sleep(max(args.interval, 0.1))


def _cmd_review_alias(args: argparse.Namespace) -> int:
    return _print_run_artifact(Path(args.runs_dir) / args.run_id, "review_report.md", "Review report")


def _cmd_test_alias(args: argparse.Namespace) -> int:
    return _print_run_artifact(Path(args.runs_dir) / args.run_id, "test_report.md", "Test report")


def _cmd_team_diff(args: argparse.Namespace) -> int:
    run_dir = Path(args.runs_dir) / args.run_id
    worktree_dir = run_dir / "worktree"
    diff = _worktree_diff(worktree_dir)
    if diff is None:
        print(f"Run worktree not found or not a git worktree: {worktree_dir}", file=sys.stderr)
        return 1
    print(diff, end="" if diff.endswith("\n") else "\n")
    return 0


def _cmd_team_apply(args: argparse.Namespace) -> int:
    from .team.runtime import TeamRuntime

    runs_dir = Path(args.runs_dir)
    run_dir = runs_dir / args.run_id
    record_path = run_dir / "team_run_record.json"
    if not record_path.exists():
        print(f"Team run record not found: {record_path}", file=sys.stderr)
        return 1
    record = TeamRuntime.load_record(args.run_id, runs_dir=runs_dir)
    allowed, reason = _run_can_apply(record)
    if not allowed:
        print(reason, file=sys.stderr)
        return 1
    worktree_dir = run_dir / "worktree"
    diff = _worktree_diff(worktree_dir)
    if diff is None:
        print(f"Run worktree not found or not a git worktree: {worktree_dir}", file=sys.stderr)
        return 1
    if not diff.strip():
        print("No worktree diff to apply.")
        return 0

    repo_root = Path(args.repo_root)
    completed = subprocess.run(
        ["git", "apply", "--index", "-"],
        input=diff,
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        completed = subprocess.run(
            ["git", "apply", "-"],
            input=diff,
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    if completed.returncode != 0:
        print(completed.stderr or completed.stdout or "git apply failed", file=sys.stderr)
        return 1
    print(f"Applied diff from run {args.run_id} to {repo_root}.")
    return 0


def _cmd_team_memory_export(args: argparse.Namespace) -> int:
    from .team.memory import export_recent_runs_to_obsidian, export_run_to_obsidian

    try:
        if getattr(args, "export_all", False):
            result = export_recent_runs_to_obsidian(
                runs_dir=Path(args.runs_dir),
                vault_dir=Path(args.vault_dir),
                limit=args.limit,
            )
        else:
            result = export_run_to_obsidian(
                str(args.run_id),
                runs_dir=Path(args.runs_dir),
                vault_dir=Path(args.vault_dir),
            )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_team_memory_search(args: argparse.Namespace) -> int:
    from .team.memory_recall import format_memory_search_result, search_memory

    result = search_memory(
        str(args.query),
        runs_dir=Path(args.runs_dir),
        domain_id=str(args.domain_id or ""),
        task_type=str(args.task_type or ""),
        limit=int(args.limit),
        refresh_missing=bool(args.refresh_missing),
    )
    if getattr(args, "json_output", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_memory_search_result(result), end="")
    return 0


def _cmd_team_release_readiness(args: argparse.Namespace) -> int:
    from .team.release import format_release_readiness, generate_release_readiness

    try:
        result = generate_release_readiness(str(args.run_id), runs_dir=Path(args.runs_dir), repo_root=Path(args.repo_root))
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if getattr(args, "json_output", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_release_readiness(result), end="")
    return 0


def _cmd_team_workspace_refresh(args: argparse.Namespace) -> int:
    from .team.workspace import format_task_workspace, refresh_task_workspace

    try:
        result = refresh_task_workspace(str(args.run_id), runs_dir=Path(args.runs_dir))
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if getattr(args, "json_output", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_task_workspace(result["task_workspace"]), end="")
    return 0


def _cmd_team_workspace_show(args: argparse.Namespace) -> int:
    from .team.workspace import TASK_WORKSPACE_JSON, format_task_workspace, refresh_task_workspace

    run_dir = Path(args.runs_dir) / str(args.run_id)
    try:
        if not (run_dir / TASK_WORKSPACE_JSON).exists():
            result = refresh_task_workspace(str(args.run_id), runs_dir=Path(args.runs_dir))
        else:
            result = refresh_task_workspace(str(args.run_id), runs_dir=Path(args.runs_dir))
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if getattr(args, "json_output", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_task_workspace(result["task_workspace"]), end="")
    return 0


def _cmd_team_release_staging_readiness(args: argparse.Namespace) -> int:
    from .team.release import format_staging_readiness, generate_staging_readiness

    try:
        result = generate_staging_readiness(str(args.run_id), runs_dir=Path(args.runs_dir))
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if getattr(args, "json_output", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_staging_readiness(result), end="")
    return 0


def _cmd_team_release_production_readiness(args: argparse.Namespace) -> int:
    from .team.release import format_production_readiness, generate_production_readiness

    try:
        result = generate_production_readiness(str(args.run_id), runs_dir=Path(args.runs_dir))
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if getattr(args, "json_output", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_production_readiness(result), end="")
    return 0


def _cmd_team_release_staging_rehearsal(args: argparse.Namespace) -> int:
    from .team.staging import format_staging_rehearsal, run_staging_rehearsal

    try:
        result = run_staging_rehearsal(str(args.run_id), runs_dir=Path(args.runs_dir), repo_root=Path(args.repo_root))
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if getattr(args, "json_output", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_staging_rehearsal(result), end="")
    return 0 if result.get("status") == "completed" else 1


def _cmd_team_pr_draft(args: argparse.Namespace) -> int:
    from .team.github_pr import create_draft_pr, format_pr_status

    try:
        result = create_draft_pr(
            str(args.run_id),
            runs_dir=Path(args.runs_dir),
            repo_root=Path(args.repo_root),
            base=str(args.base),
            push=bool(args.push),
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if getattr(args, "json_output", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_pr_status(result), end="")
    return 0 if result.get("status") == "created" else 1


def _cmd_team_pr_status(args: argparse.Namespace) -> int:
    from .team.github_pr import format_ci_status, refresh_ci_status

    try:
        result = refresh_ci_status(str(args.run_id), runs_dir=Path(args.runs_dir), repo_root=Path(args.repo_root))
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if getattr(args, "json_output", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_ci_status(result), end="")
    return 0 if result.get("status") in {"passed", "running", "pending", "unknown"} else 1


def _cmd_team_retrospective_generate(args: argparse.Namespace) -> int:
    from .team.retrospective import generate_recent_run_retrospectives, generate_run_retrospective

    try:
        if getattr(args, "generate_all", False):
            result = generate_recent_run_retrospectives(runs_dir=Path(args.runs_dir), limit=args.limit)
        else:
            result = generate_run_retrospective(str(args.run_id), runs_dir=Path(args.runs_dir))
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_team_serve_dashboard(args: argparse.Namespace) -> int:
    from .team.dashboard import DashboardConfig, run_dashboard_server

    config = DashboardConfig(
        host=args.host,
        port=args.port,
        runs_dir=Path(args.runs_dir),
        domains_dir=Path(args.domains_dir),
        dashboard_dir=Path(args.dashboard_dir),
        repo_root=Path(args.repo_root),
        codex_binary=args.codex_binary,
        codex_provider=args.codex_provider,
        env_file=args.env_file,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        executor=args.executor,
        planning_mode=args.planning_mode,
        requirements_model=args.requirements_model,
        requirements_reasoning_effort=args.requirements_reasoning_effort,
        requirements_env_file=args.requirements_env_file,
    )
    run_dashboard_server(config, open_browser=args.open_browser)
    return 0


def _parse_inputs_json(value: str) -> dict:
    if not value:
        return {}
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError("--inputs-json must decode to a JSON object")
    return payload


def _print_run_artifact(run_dir: Path, artifact: str, label: str) -> int:
    path = run_dir / artifact
    if not path.exists():
        print(f"{label} not found: {path}", file=sys.stderr)
        return 1
    print(path.read_text(encoding="utf-8"))
    return 0


def _team_status_summary(record, run_dir: Path) -> str:
    from .team.quality import evaluate_run_quality, summarize_run_health

    current = _current_agent(record)
    health = summarize_run_health(record, run_dir)
    quality = evaluate_run_quality(record, run_dir)
    lines = [
        f"Run: {record.run_id}",
        f"Status: {record.status}",
        f"Run health: {health.label} - {health.summary}",
        f"Artifact quality: {quality.status} ({quality.score:.0%}) - {quality.summary}",
        f"Domain: {record.domain_id}",
        f"Executor: {record.executor}",
        f"Current agent: {current.agent_id if current else 'none'}",
    ]
    if health.warnings:
        lines.extend(["Warnings:", *[f"- {warning}" for warning in health.warnings[:3]]])
    if health.blockers:
        lines.extend(["Blockers:", *[f"- {blocker}" for blocker in health.blockers[:3]]])
    if current:
        lines.extend(
            [
                f"Agent status: {current.status}",
                f"Agent elapsed: {_elapsed_label(current.started_at, current.finished_at)}",
            ]
        )
        failure_category = (current.metadata or {}).get("failure_category")
        if failure_category:
            lines.append(f"Failure category: {failure_category}")
    if record.risk_events:
        lines.extend(["Risk events:", *[f"- {event}" for event in record.risk_events]])
    gate_lines = _gate_lines(record)
    if gate_lines:
        lines.extend(["Gates:", *[f"- {line}" for line in gate_lines]])
    apply_status, apply_reason = _apply_gate_status(record)
    lines.extend(["Apply gate:", f"- {apply_status}: {apply_reason}"])
    latest_logs = _latest_log_lines(run_dir)
    if latest_logs:
        lines.extend(["Latest logs:", *[f"- {line}" for line in latest_logs]])
    diff_summary = _diff_summary(run_dir)
    if diff_summary:
        lines.extend(["Diff summary:", *[f"- {line}" for line in diff_summary]])
    return "\n".join(lines).rstrip() + "\n"


def _team_watch_snapshot(run_id: str, run_dir: Path) -> str:
    from .team.runtime import TeamRuntime

    record_path = run_dir / "team_run_record.json"
    if record_path.exists():
        record = TeamRuntime.load_record(run_id, runs_dir=run_dir.parent)
        lines = [_team_status_summary(record, run_dir).rstrip()]
    else:
        lines = [f"Run: {run_id}", "Status: starting"]
    process_path = run_dir / "process.json"
    if process_path.exists():
        process = read_json(process_path)
        status = _process_status(process)
        process["status"] = status
        process["last_seen_at"] = now_iso()
        write_json(process_path, process)
        lines.extend(["Process:", f"- pid: {process.get('pid', 0)}", f"- status: {status}"])
    events = _read_events(run_dir)
    if events:
        lines.extend(["Recent events:", *[f"- {event.get('event', '')}: {_event_label(event)}" for event in events[-5:]]])
    if record_path.exists():
        record = TeamRuntime.load_record(run_id, runs_dir=run_dir.parent)
        if record.status == "completed":
            lines.extend(
                [
                    "Next actions:",
                    f"- python -m growth_dev.cli team diff --run-id {run_id}",
                    f"- python -m growth_dev.cli review --run-id {run_id}",
                    f"- python -m growth_dev.cli test --run-id {run_id}",
                    f"- python -m growth_dev.cli report --run-id {run_id}",
                    f"- python -m growth_dev.cli team apply --run-id {run_id}",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def _watch_terminal_state(run_dir: Path) -> bool:
    record_path = run_dir / "team_run_record.json"
    if not record_path.exists():
        return False
    payload = read_json(record_path)
    return payload.get("status") in {"completed", "failed"}


def _read_events(run_dir: Path) -> list[dict]:
    events_path = run_dir / "events.jsonl"
    if not events_path.exists():
        return []
    events: list[dict] = []
    for line in events_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _event_label(event: dict) -> str:
    if event.get("agent_id"):
        return str(event.get("agent_id"))
    if event.get("gate_id"):
        missing = event.get("missing_artifacts") or []
        suffix = f" missing={','.join(missing)}" if missing else ""
        return f"{event.get('gate_id')} {event.get('status', '')}{suffix}".strip()
    return str(event.get("status") or event.get("reason") or event.get("run_id") or "")


def _process_status(process: dict) -> str:
    status = str(process.get("status", "unknown"))
    pid = int(process.get("pid") or 0)
    run_dir = process.get("run_dir")
    if run_dir:
        record_path = Path(str(run_dir)) / "team_run_record.json"
        if record_path.exists():
            record_status = str(read_json(record_path).get("status", ""))
            if record_status in {"completed", "failed"}:
                return record_status
    if status == "running" and pid and not _pid_is_running(pid):
        return "exited"
    return status


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _gate_lines(record) -> list[str]:
    return [
        f"{gate.gate_id}: {gate.status} before {gate.before_agent}"
        + (f" missing {', '.join(gate.missing_artifacts)}" if gate.missing_artifacts else "")
        for gate in record.gate_results
    ]


def _apply_gate_status(record) -> tuple[str, str]:
    allowed, reason = _run_can_apply(record)
    if allowed:
        return "passed", "run completed, no risk events, verifier completed"
    return "blocked", reason


def _current_agent(record):
    if not record.agent_runs:
        return None
    for agent_run in reversed(record.agent_runs):
        if agent_run.status == "running":
            return agent_run
    return record.agent_runs[-1]


def _elapsed_label(started_at: str, finished_at: str) -> str:
    if not started_at:
        return "unknown"
    if finished_at:
        return f"{started_at} -> {finished_at}"
    return f"since {started_at}"


def _latest_log_lines(run_dir: Path, max_lines: int = 6) -> list[str]:
    from .team.quality import summarize_run_logs

    return summarize_run_logs(run_dir, max_lines=max_lines)


def _tail_lines(path: Path, max_lines: int = 5) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return [line for line in text.splitlines() if line.strip()][-max_lines:]


def _diff_summary(run_dir: Path) -> list[str]:
    lines: list[str] = []
    diff_path = run_dir / "codex" / "diff.patch"
    status_path = run_dir / "codex" / "git_status.txt"
    if diff_path.exists():
        count = len(diff_path.read_text(encoding="utf-8", errors="replace").splitlines())
        lines.append(f"diff.patch: {count} lines")
    if status_path.exists():
        status = ", ".join(_tail_lines(status_path, max_lines=5))
        if status:
            lines.append(f"git_status.txt: {status}")
    return lines


def _run_can_apply(record) -> tuple[bool, str]:
    if record.status != "completed":
        return False, f"Cannot apply run {record.run_id}: status is {record.status}, expected completed."
    if record.risk_events:
        return False, f"Cannot apply run {record.run_id}: risk events are present."
    verifier_runs = [agent_run for agent_run in record.agent_runs if agent_run.agent_id == "verifier"]
    if not verifier_runs or verifier_runs[-1].status != "completed":
        return False, f"Cannot apply run {record.run_id}: verifier did not complete."
    if verifier_runs[-1].risk_events:
        return False, f"Cannot apply run {record.run_id}: verifier risk events are present."
    return True, ""


def _worktree_diff(worktree_dir: Path) -> str | None:
    if not (worktree_dir.exists() and ((worktree_dir / ".git").exists() or (worktree_dir / ".git").is_file())):
        return None
    parts = [
        _git_output(["git", "diff", "--patch", "--binary"], worktree_dir, allow_diff=True),
        _git_output(["git", "diff", "--cached", "--patch", "--binary"], worktree_dir, allow_diff=True),
    ]
    for file_name in _git_output(["git", "ls-files", "--others", "--exclude-standard"], worktree_dir).splitlines():
        file_name = file_name.strip()
        if not file_name:
            continue
        file_path = worktree_dir / file_name
        if file_path.is_file() and file_path.stat().st_size <= 200_000:
            parts.append(_git_output(["git", "diff", "--no-index", "--", "/dev/null", file_name], worktree_dir, allow_diff=True))
    return "\n".join(part for part in parts if part).strip() + ("\n" if any(part for part in parts) else "")


def _git_output(command: list[str], cwd: Path, *, allow_diff: bool = False) -> str:
    completed = subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if completed.returncode == 0 or (allow_diff and completed.returncode == 1):
        return completed.stdout
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
