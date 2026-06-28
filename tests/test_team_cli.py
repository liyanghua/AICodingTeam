from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from tests.test_team_models import DOMAIN_YAML, TEAM_YAML


WEB_MONITORING_DOMAIN_YAML = """\
domain_id: web_monitoring
input_schema:
  target_url: string
  keyword: string
output_schema: WebMonitoringResult
risk_rules:
  - no_private_data_collection
  - screenshot_evidence_only
"""


def _write_domain_pack(root: Path, domain_id: str, domain_yaml: str) -> Path:
    domain_dir = root / domain_id
    domain_dir.mkdir(parents=True)
    (domain_dir / "domain.yaml").write_text(domain_yaml, encoding="utf-8")
    (domain_dir / "team.yaml").write_text(TEAM_YAML, encoding="utf-8")
    return domain_dir


@contextlib.contextmanager
def _captured_stdout():
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        yield buffer


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _init_git_repo(root: Path) -> None:
    (root / "a.txt").write_text("base\n", encoding="utf-8")
    _run(["git", "init", "-q"], root)
    _run(["git", "add", "."], root)
    _run(["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "init"], root)


class TeamCliTests(unittest.TestCase):
    def test_team_subcommands_are_registered(self) -> None:
        from growth_dev.cli import _build_parser

        parser = _build_parser()
        examples = [
            ["team", "init", "--domain", "xhs_browser_benchmark"],
            ["team", "run", "--brief", "对比 5 个浏览器自动化框架完成小红书采集任务"],
            ["team", "run", "--brief", "接入 Codex", "--executor", "codex", "--model", "gpt-5.3-codex", "--reasoning-effort", "medium"],
            ["team", "run", "--brief", "接入第三方 Codex provider", "--executor", "codex", "--codex-provider", "aicodemirror", "--env-file", ".env"],
            [
                "team",
                "run",
                "--brief",
                "复杂 Dashboard 需求",
                "--planning-mode",
                "llm_assisted",
                "--requirements-model",
                "gpt-5.3",
                "--requirements-reasoning-effort",
                "high",
                "--requirements-env-file",
                ".env.requirements",
            ],
            ["team", "status", "--run-id", "team-run-1"],
            ["team", "status", "--run-id", "team-run-1", "--summary"],
            ["team", "report", "--run-id", "team-run-1"],
            ["team", "watch", "--run-id", "team-run-1", "--once"],
            ["team", "diff", "--run-id", "team-run-1"],
            ["team", "apply", "--run-id", "team-run-1"],
            ["team", "release", "readiness", "--run-id", "team-run-1"],
            ["team", "release", "readiness", "--run-id", "team-run-1", "--json"],
            ["team", "release", "staging-readiness", "--run-id", "team-run-1"],
            ["team", "release", "staging-rehearsal", "--run-id", "team-run-1"],
            ["team", "release", "staging-rehearsal", "--run-id", "team-run-1", "--json"],
        ]

        for argv in examples:
            with self.subTest(argv=argv):
                args = parser.parse_args(argv)
                self.assertTrue(callable(args.func))

    def test_week_2_root_aliases_are_registered(self) -> None:
        from growth_dev.cli import _build_parser

        parser = _build_parser()
        examples = [
            ["code", "--brief", "实现一个小改动"],
            ["app", "generate", "--prd-text", "# Todo App", "--app-slug", "todo-prototype"],
            ["review", "--run-id", "team-run-1"],
            ["test", "--run-id", "team-run-1"],
            ["report", "--run-id", "team-run-1"],
        ]

        for argv in examples:
            with self.subTest(argv=argv):
                args = parser.parse_args(argv)
                self.assertTrue(callable(args.func))

    def test_app_generate_cli_foreground_runs_app_generation_domain(self) -> None:
        from growth_dev.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"

            exit_code = main(
                [
                    "app",
                    "generate",
                    "--foreground",
                    "--executor",
                    "deterministic",
                    "--prd-text",
                    "# Todo Prototype\n\n用户可以新增和完成待办。",
                    "--app-slug",
                    "todo-prototype",
                    "--runs-dir",
                    str(runs_dir),
                    "--run-id",
                    "app-cli-run",
                    "--repo-root",
                    str(Path.cwd()),
                ]
            )

            run_dir = runs_dir / "app-cli-run"
            record = json.loads((run_dir / "team_run_record.json").read_text(encoding="utf-8"))
            contract = json.loads((run_dir / "app_contract.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(record["domain_id"], "app_generation")
        self.assertEqual(record["inputs"]["app_slug"], "todo-prototype")
        self.assertEqual(contract["generated_app_dir"], "generated_apps/todo-prototype")

    def test_app_generate_cli_requires_prd_input(self) -> None:
        from growth_dev.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            exit_code = main(
                [
                    "app",
                    "generate",
                    "--foreground",
                    "--executor",
                    "deterministic",
                    "--app-slug",
                    "todo-prototype",
                    "--runs-dir",
                    str(root / "runs"),
                ]
            )

        self.assertEqual(exit_code, 2)

    def test_team_init_cli_generates_eval_and_team_yaml(self) -> None:
        from growth_dev.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            domains_dir = root / "domains"
            _write_domain_pack(domains_dir, "xhs_browser_benchmark", DOMAIN_YAML)
            output_dir = root / "tasks" / "current"

            exit_code = main(
                [
                    "team",
                    "init",
                    "--domain",
                    "xhs_browser_benchmark",
                    "--domains-dir",
                    str(domains_dir),
                    "--output",
                    str(output_dir),
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue((output_dir / "eval.md").exists())
            self.assertTrue((output_dir / "team.yaml").exists())
            self.assertTrue((output_dir / "domain.yaml").exists())

    def test_team_run_cli_supports_second_domain_pack(self) -> None:
        from growth_dev.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            domains_dir = root / "domains"
            runs_dir = root / "runs"
            _write_domain_pack(domains_dir, "web_monitoring", WEB_MONITORING_DOMAIN_YAML)

            exit_code = main(
                [
                    "team",
                    "run",
                    "--domain",
                    "web_monitoring",
                    "--domains-dir",
                    str(domains_dir),
                    "--runs-dir",
                    str(runs_dir),
                    "--brief",
                    "监控目标网页里关键词是否发生变化",
                ]
            )

            self.assertEqual(exit_code, 0)
            run_dirs = [path for path in runs_dir.iterdir() if path.is_dir()]
            self.assertEqual(len(run_dirs), 1)
            record_path = run_dirs[0] / "team_run_record.json"
            self.assertTrue(record_path.exists())
            payload = json.loads(record_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["domain_id"], "web_monitoring")
            self.assertEqual(payload["status"], "completed")
            self.assertTrue((run_dirs[0] / "final_report.md").exists())

    def test_team_run_cli_writes_complex_task_planning_artifacts(self) -> None:
        from growth_dev.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            domains_dir = root / "domains"
            runs_dir = root / "runs"
            _write_domain_pack(domains_dir, "web_monitoring", WEB_MONITORING_DOMAIN_YAML)

            exit_code = main(
                [
                    "team",
                    "run",
                    "--domain",
                    "web_monitoring",
                    "--domains-dir",
                    str(domains_dir),
                    "--runs-dir",
                    str(runs_dir),
                    "--run-id",
                    "complex-run-1",
                    "--brief",
                    "优化 Dashboard 交付验收流程，展示需求理解、覆盖矩阵和 slice 执行。",
                    "--planning-mode",
                    "llm_assisted",
                    "--requirements-model",
                    "gpt-5.3",
                    "--requirements-reasoning-effort",
                    "high",
                    "--requirements-env-file",
                    str(root / ".env.requirements"),
                ]
            )

            run_dir = runs_dir / "complex-run-1"
            payload = json.loads((run_dir / "team_run_record.json").read_text(encoding="utf-8"))
            analysis = json.loads((run_dir / "requirements" / "brief_analysis.json").read_text(encoding="utf-8"))
            draft_exists = (run_dir / "requirements" / "acceptance_criteria.draft.md").exists()
            coverage_exists = (run_dir / "planning" / "acceptance_coverage_matrix.json").exists()
            slice_exists = (run_dir / "slices" / "slice-001.yaml").exists()

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["executor_config"]["complex_task"]["planning_mode"], "llm_assisted")
        self.assertEqual(payload["executor_config"]["complex_task"]["requirements_model"], "gpt-5.3")
        self.assertEqual(payload["executor_config"]["complex_task"]["requirements_reasoning_effort"], "high")
        self.assertEqual(payload["executor_config"]["complex_task"]["requirements_env_file"], str(root / ".env.requirements"))
        self.assertTrue(draft_exists)
        self.assertTrue(coverage_exists)
        self.assertTrue(slice_exists)
        self.assertTrue(analysis["llm_draft_requested"])

    def test_team_status_summary_includes_current_agent_logs_and_diff(self) -> None:
        from growth_dev.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "team-run-1"
            codex_dir = run_dir / "codex"
            codex_dir.mkdir(parents=True)
            record = {
                "run_id": "team-run-1",
                "team_id": "ai_native_engineering_team",
                "domain_id": "web_monitoring",
                "brief": "demo",
                "status": "running",
                "run_dir": str(run_dir),
                "started_at": "2026-05-21T00:00:00+00:00",
                "agent_runs": [
                    {
                        "agent_id": "coder",
                        "status": "running",
                        "started_at": "2026-05-21T00:00:01+00:00",
                        "finished_at": "",
                        "risk_events": [],
                        "output_paths": ["codex/stdout.jsonl", "codex/diff.patch"],
                        "message": "coding",
                        "metadata": {},
                    }
                ],
                "artifacts": {
                    "stdout.jsonl": "codex/stdout.jsonl",
                    "stderr.log": "codex/stderr.log",
                    "diff.patch": "codex/diff.patch",
                    "git_status.txt": "codex/git_status.txt",
                },
            }
            (run_dir / "team_run_record.json").write_text(json.dumps(record), encoding="utf-8")
            (codex_dir / "stdout.jsonl").write_text(
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "agent_message",
                            "text": json.dumps(
                                {
                                    "summary": "Implemented web monitoring update.",
                                    "files_changed": ["a.txt"],
                                    "tests_run": ["python3 -m unittest tests.test_demo -v"],
                                    "risk_events": [],
                                }
                            ),
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (codex_dir / "stderr.log").write_text("warn from provider\n", encoding="utf-8")
            (codex_dir / "diff.patch").write_text("diff --git a/a.txt b/a.txt\n+hello\n", encoding="utf-8")
            (codex_dir / "git_status.txt").write_text(" M a.txt\n", encoding="utf-8")

            with _captured_stdout() as output:
                exit_code = main(["team", "status", "--run-id", "team-run-1", "--runs-dir", str(runs_dir), "--summary"])

        self.assertEqual(exit_code, 0)
        text = output.getvalue()
        self.assertIn("team-run-1", text)
        self.assertIn("Run health:", text)
        self.assertIn("Current agent: coder", text)
        self.assertIn("Codex summary: Implemented web monitoring update.", text)
        self.assertIn("warn from provider", text)
        self.assertIn("diff.patch: 2 lines", text)
        self.assertNotIn('{"type"', text)

    def test_team_diff_prints_worktree_diff(self) -> None:
        from growth_dev.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            worktree = runs_dir / "team-run-1" / "worktree"
            worktree.mkdir(parents=True)
            _init_git_repo(worktree)
            (worktree / "a.txt").write_text("changed\n", encoding="utf-8")

            with _captured_stdout() as output:
                exit_code = main(["team", "diff", "--run-id", "team-run-1", "--runs-dir", str(runs_dir)])

        self.assertEqual(exit_code, 0)
        self.assertIn("-base", output.getvalue())
        self.assertIn("+changed", output.getvalue())

    def test_team_apply_refuses_non_completed_runs(self) -> None:
        from growth_dev.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "team-run-1"
            run_dir.mkdir(parents=True)
            (run_dir / "team_run_record.json").write_text(
                json.dumps({"run_id": "team-run-1", "domain_id": "demo", "brief": "demo", "status": "failed", "run_dir": str(run_dir)}),
                encoding="utf-8",
            )

            exit_code = main(["team", "apply", "--run-id", "team-run-1", "--runs-dir", str(runs_dir), "--repo-root", str(root)])

        self.assertEqual(exit_code, 1)

    def test_team_apply_applies_completed_worktree_diff_to_repo(self) -> None:
        from growth_dev.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "repo"
            repo_root.mkdir()
            _init_git_repo(repo_root)
            runs_dir = root / "runs"
            run_dir = runs_dir / "team-run-1"
            worktree = run_dir / "worktree"
            run_dir.mkdir(parents=True)
            _run(["git", "worktree", "add", "--detach", str(worktree), "HEAD"], repo_root)
            (worktree / "a.txt").write_text("changed\n", encoding="utf-8")
            (run_dir / "team_run_record.json").write_text(
                json.dumps(
                    {
                        "run_id": "team-run-1",
                        "domain_id": "demo",
                        "brief": "demo",
                        "status": "completed",
                        "run_dir": str(run_dir),
                        "agent_runs": [
                            {"agent_id": "verifier", "status": "completed", "risk_events": [], "output_paths": ["test_report.md"]}
                        ],
                        "risk_events": [],
                    }
                ),
                encoding="utf-8",
            )

            exit_code = main(["team", "apply", "--run-id", "team-run-1", "--runs-dir", str(runs_dir), "--repo-root", str(repo_root)])

            self.assertEqual(exit_code, 0)
            self.assertEqual((repo_root / "a.txt").read_text(encoding="utf-8"), "changed\n")

    def test_code_alias_starts_background_run_and_writes_process_record(self) -> None:
        from growth_dev.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            domains_dir = root / "domains"
            runs_dir = root / "runs"
            _write_domain_pack(domains_dir, "web_monitoring", WEB_MONITORING_DOMAIN_YAML)
            run_id = "background-run-1"

            with _captured_stdout() as output:
                exit_code = main(
                    [
                        "code",
                        "--run-id",
                        run_id,
                        "--domain",
                        "web_monitoring",
                        "--domains-dir",
                        str(domains_dir),
                        "--runs-dir",
                        str(runs_dir),
                        "--brief",
                        "后台运行测试",
                        "--executor",
                        "deterministic",
                    ]
                )
            process_path = runs_dir / run_id / "process.json"
            deadline = time.time() + 5
            while time.time() < deadline and not (runs_dir / run_id / "team_run_record.json").exists():
                time.sleep(0.05)

            process_record = json.loads(process_path.read_text(encoding="utf-8"))
            command_text = json.dumps(process_record, ensure_ascii=False)

        self.assertEqual(exit_code, 0)
        self.assertIn("Run started: background-run-1", output.getvalue())
        self.assertIn("Watch: python -m growth_dev.cli team watch --run-id background-run-1", output.getvalue())
        self.assertEqual(process_record["run_id"], run_id)
        self.assertGreater(process_record["pid"], 0)
        self.assertIn(process_record["status"], {"running", "completed"})
        self.assertIn("--planning-mode", process_record["command"])
        self.assertIn("auto", process_record["command"])
        self.assertNotIn("sk-", command_text)

    def test_team_watch_once_shows_events_gates_logs_and_next_actions(self) -> None:
        from growth_dev.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "team-run-1"
            codex_dir = run_dir / "codex"
            codex_dir.mkdir(parents=True)
            record = {
                "run_id": "team-run-1",
                "team_id": "ai_native_engineering_team",
                "domain_id": "web_monitoring",
                "brief": "demo",
                "status": "completed",
                "run_dir": str(run_dir),
                "started_at": "2026-05-21T00:00:00+00:00",
                "finished_at": "2026-05-21T00:00:05+00:00",
                "agent_runs": [
                    {"agent_id": "coder", "status": "completed", "started_at": "a", "finished_at": "b", "risk_events": [], "output_paths": [], "message": "", "metadata": {"failure_category": ""}},
                    {"agent_id": "verifier", "status": "completed", "started_at": "c", "finished_at": "d", "risk_events": [], "output_paths": ["test_report.md"], "message": "", "metadata": {}},
                ],
                "gate_results": [
                    {
                        "gate_id": "before_coding",
                        "status": "passed",
                        "required_artifacts": ["prd.md"],
                        "missing_artifacts": [],
                        "checked_at": "now",
                        "before_agent": "coder",
                    }
                ],
                "risk_events": [],
                "executor": "codex",
            }
            (run_dir / "team_run_record.json").write_text(json.dumps(record), encoding="utf-8")
            (run_dir / "process.json").write_text(
                json.dumps({"run_id": "team-run-1", "pid": 12345, "status": "running", "run_dir": str(run_dir)}),
                encoding="utf-8",
            )
            (run_dir / "events.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"event": "run_started", "run_id": "team-run-1"}),
                        json.dumps({"event": "agent_started", "agent_id": "coder"}),
                        json.dumps({"event": "gate_checked", "gate_id": "before_coding", "status": "passed"}),
                        json.dumps({"event": "run_completed", "run_id": "team-run-1"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (codex_dir / "stdout.jsonl").write_text(
                json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({"summary": "finished"})}})
                + "\n",
                encoding="utf-8",
            )
            (codex_dir / "diff.patch").write_text("+hello\n", encoding="utf-8")

            with _captured_stdout() as output:
                exit_code = main(["team", "watch", "--run-id", "team-run-1", "--runs-dir", str(runs_dir), "--once"])

        text = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("Run: team-run-1", text)
        self.assertIn("Run health:", text)
        self.assertIn("before_coding: passed", text)
        self.assertIn("agent_started", text)
        self.assertIn("Codex summary: finished", text)
        self.assertIn("Process:", text)
        self.assertIn("Apply gate:", text)
        self.assertIn("Next actions:", text)

    def test_team_status_summary_shows_failure_category(self) -> None:
        from growth_dev.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "team-run-1"
            run_dir.mkdir(parents=True)
            record = {
                "run_id": "team-run-1",
                "team_id": "ai_native_engineering_team",
                "domain_id": "web_monitoring",
                "brief": "demo",
                "status": "failed",
                "run_dir": str(run_dir),
                "agent_runs": [
                    {
                        "agent_id": "coder",
                        "status": "failed",
                        "started_at": "a",
                        "finished_at": "b",
                        "risk_events": ["codex_exit_code:1"],
                        "output_paths": [],
                        "message": "failed",
                        "metadata": {"failure_category": "provider_error"},
                    }
                ],
                "risk_events": ["codex_exit_code:1"],
                "executor": "codex",
            }
            (run_dir / "team_run_record.json").write_text(json.dumps(record), encoding="utf-8")

            with _captured_stdout() as output:
                exit_code = main(["team", "status", "--run-id", "team-run-1", "--runs-dir", str(runs_dir), "--summary"])

        self.assertEqual(exit_code, 0)
        self.assertIn("Failure category: provider_error", output.getvalue())


if __name__ == "__main__":
    unittest.main()
