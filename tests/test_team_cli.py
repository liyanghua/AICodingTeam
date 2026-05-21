from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
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
            ["team", "status", "--run-id", "team-run-1"],
            ["team", "status", "--run-id", "team-run-1", "--summary"],
            ["team", "report", "--run-id", "team-run-1"],
            ["team", "diff", "--run-id", "team-run-1"],
            ["team", "apply", "--run-id", "team-run-1"],
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
            ["review", "--run-id", "team-run-1"],
            ["test", "--run-id", "team-run-1"],
            ["report", "--run-id", "team-run-1"],
        ]

        for argv in examples:
            with self.subTest(argv=argv):
                args = parser.parse_args(argv)
                self.assertTrue(callable(args.func))

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
            (codex_dir / "stdout.jsonl").write_text("line 1\nline 2\n", encoding="utf-8")
            (codex_dir / "stderr.log").write_text("warn from provider\n", encoding="utf-8")
            (codex_dir / "diff.patch").write_text("diff --git a/a.txt b/a.txt\n+hello\n", encoding="utf-8")
            (codex_dir / "git_status.txt").write_text(" M a.txt\n", encoding="utf-8")

            with _captured_stdout() as output:
                exit_code = main(["team", "status", "--run-id", "team-run-1", "--runs-dir", str(runs_dir), "--summary"])

        self.assertEqual(exit_code, 0)
        text = output.getvalue()
        self.assertIn("team-run-1", text)
        self.assertIn("Current agent: coder", text)
        self.assertIn("warn from provider", text)
        self.assertIn("diff.patch: 2 lines", text)

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


if __name__ == "__main__":
    unittest.main()
