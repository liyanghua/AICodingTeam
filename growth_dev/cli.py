from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from .adapters.base import MockAdapter
from .benchmark import DEFAULT_FRAMEWORKS, benchmark, load_task, run_framework, run_mock
from .mock_site import MockServer
from .models import TaskSpec
from .reporting import write_report
from .tasks import default_task_spec, write_task_package
from .utils import ensure_dir, now_iso, read_json, timestamp_slug, write_json


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
    team_run.set_defaults(func=_cmd_team_run)

    team_status = team_sub.add_parser("status", help="Show a team run record status")
    team_status.add_argument("--run-id", required=True)
    team_status.add_argument("--runs-dir", default="runs")
    team_status.set_defaults(func=_cmd_team_status)

    team_report = team_sub.add_parser("report", help="Show the final report for a team run")
    team_report.add_argument("--run-id", required=True)
    team_report.add_argument("--runs-dir", default="runs")
    team_report.set_defaults(func=_cmd_team_report)

    return parser


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
    )
    record = runtime.run(args.brief, inputs=inputs, run_id=args.run_id)
    print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2))
    return 0 if record.status == "completed" else 1


def _cmd_team_status(args: argparse.Namespace) -> int:
    from .team.runtime import TeamRuntime

    record_path = Path(args.runs_dir) / args.run_id / "team_run_record.json"
    if not record_path.exists():
        print(f"Team run record not found: {record_path}", file=sys.stderr)
        return 1
    record = TeamRuntime.load_record(args.run_id, runs_dir=Path(args.runs_dir))
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


def _parse_inputs_json(value: str) -> dict:
    if not value:
        return {}
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError("--inputs-json must decode to a JSON object")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
