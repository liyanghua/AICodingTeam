from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


@contextlib.contextmanager
def _captured_output():
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        yield stdout, stderr


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _init_git_repo(root: Path) -> None:
    (root / "dashboard").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / "dashboard" / "app.js").write_text("const oldValue = true;\n", encoding="utf-8")
    (root / "tests" / "test_dashboard.py").write_text("def test_existing():\n    assert True\n", encoding="utf-8")
    _run(["git", "init", "-q"], root)
    _run(["git", "add", "."], root)
    _run(["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "init"], root)


def _write_ready_run(runs_dir: Path, run_id: str = "release-run-1") -> Path:
    run_dir = runs_dir / run_id
    codex_dir = run_dir / "codex"
    acceptance_dir = run_dir / "acceptance"
    codex_dir.mkdir(parents=True)
    acceptance_dir.mkdir(parents=True)
    record = {
        "run_id": run_id,
        "team_id": "ai_native_engineering_team",
        "domain_id": "web_monitoring",
        "brief": "修复 Dashboard 交付验收状态显示",
        "status": "completed",
        "run_dir": str(run_dir),
        "started_at": "2026-05-28T00:00:00+00:00",
        "finished_at": "2026-05-28T00:05:00+00:00",
        "agent_runs": [
            {"agent_id": "product", "status": "completed", "risk_events": [], "output_paths": ["prd.md"], "message": "prd", "metadata": {}},
            {
                "agent_id": "coder",
                "status": "completed",
                "risk_events": [],
                "output_paths": ["coding_prompt.md", "codex/diff.patch"],
                "message": "coded",
                "metadata": {"files_changed": ["dashboard/app.js", "tests/test_dashboard.py"]},
            },
            {"agent_id": "reviewer", "status": "completed", "risk_events": [], "output_paths": ["review_report.md"], "message": "reviewed", "metadata": {}},
            {"agent_id": "verifier", "status": "completed", "risk_events": [], "output_paths": ["test_report.md"], "message": "tested", "metadata": {}},
            {"agent_id": "publisher", "status": "completed", "risk_events": [], "output_paths": ["final_report.md"], "message": "published", "metadata": {}},
        ],
        "gate_results": [
            {"gate_id": "before_coding", "status": "passed", "required_artifacts": ["prd.md"], "missing_artifacts": [], "checked_at": "now", "before_agent": "coder"},
            {"gate_id": "before_publish", "status": "passed", "required_artifacts": ["review_report.md", "test_report.md"], "missing_artifacts": [], "checked_at": "now", "before_agent": "publisher"},
        ],
        "artifacts": {
            "prd.md": "prd.md",
            "tech_spec.md": "tech_spec.md",
            "ui_spec.md": "ui_spec.md",
            "eval.md": "eval.md",
            "review_report.md": "review_report.md",
            "test_report.md": "test_report.md",
            "final_report.md": "final_report.md",
            "diff.patch": "codex/diff.patch",
        },
        "risk_events": [],
        "executor": "codex",
    }
    (run_dir / "team_run_record.json").write_text(json.dumps(record), encoding="utf-8")
    (run_dir / "prd.md").write_text(
        "# PRD\n\n背景：web_monitoring Dashboard 需要正确展示交付验收状态。\n\n目标：采纳通过后显示已完成。\n\n范围：仅调整 Dashboard 状态映射。\n\n验收：全量测试通过。\n",
        encoding="utf-8",
    )
    (run_dir / "tech_spec.md").write_text(
        "# Tech Spec\n\n技术：修改 dashboard business view 状态映射。\n\n接口：复用 acceptance.status。\n\n边界：不改变后端 schema。\n\n数据：读取 acceptance/status.json。\n",
        encoding="utf-8",
    )
    (run_dir / "ui_spec.md").write_text(
        "# UI Spec\n\nUI：Dashboard 展示交付验收状态。\n\n状态：完成、失败、等待确认。\n\n交互：用户点击确认后状态更新。\n",
        encoding="utf-8",
    )
    (run_dir / "eval.md").write_text(
        "# Eval\n\nweb_monitoring Dashboard 验收：采纳完成后状态为已完成。\n\n测试：运行全量 unittest。\n\n评审：确认无阻塞。\n\n关卡：before_publish 通过。\n",
        encoding="utf-8",
    )
    (run_dir / "final_report.md").write_text(
        "# Final Report\n\n需求：修复 Dashboard 交付验收状态。\n\n结果：状态修复已完成。\n\n建议：进入发布准备。\n\n关卡：Review/Test 已通过。\n",
        encoding="utf-8",
    )
    (run_dir / "review_report.md").write_text("# Review Report\n\nNo blocking bugs or regressions were identified.\n", encoding="utf-8")
    (run_dir / "test_report.md").write_text("# Test Report\n\n- `python3 -m unittest discover -s tests -v` -> exit `0`\n\nOK\n", encoding="utf-8")
    (codex_dir / "implementation_trace.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_id,
                "stage": "coder",
                "status": "completed",
                "evidence": {
                    "changed_files": ["dashboard/app.js", "tests/test_dashboard.py"],
                    "tests_run": ["python3 -m unittest tests.test_dashboard -v"],
                    "verification_commands": ["python3 -m unittest tests.test_dashboard -v"],
                    "diff_path": "codex/diff.patch",
                    "exit_code": 0,
                },
                "risk_events": [],
                "blockers": [],
                "next_action": "release_readiness",
            }
        ),
        encoding="utf-8",
    )
    (codex_dir / "diff.patch").write_text(
        "\n".join(
            [
                "diff --git a/dashboard/app.js b/dashboard/app.js",
                "--- a/dashboard/app.js",
                "+++ b/dashboard/app.js",
                "@@ -1 +1 @@",
                "-const oldValue = true;",
                "+const oldValue = false;",
                "diff --git a/tests/test_dashboard.py b/tests/test_dashboard.py",
                "--- a/tests/test_dashboard.py",
                "+++ b/tests/test_dashboard.py",
                "@@ -1,2 +1,5 @@",
                " def test_existing():",
                "     assert True",
                "+",
                "+def test_delivery_done():",
                "+    assert True",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (acceptance_dir / "status.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_id,
                "status": "completed",
                "applied": True,
                "conclusion": "已采纳且测试通过。",
                "steps": [
                    {"id": "apply", "status": "completed", "exit_code": 0, "command": "python3 -m growth_dev.cli team apply --run-id release-run-1"},
                    {"id": "tests", "status": "completed", "exit_code": 0, "command": "python3 -m unittest discover -s tests -v"},
                ],
            }
        ),
        encoding="utf-8",
    )
    return run_dir


class TeamReleaseTests(unittest.TestCase):
    def test_release_readiness_ready_for_pr_ci_when_acceptance_review_tests_and_diff_are_clean(self) -> None:
        from growth_dev.team.release import generate_release_readiness

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "repo"
            repo_root.mkdir()
            _init_git_repo(repo_root)
            runs_dir = root / "runs"
            _write_ready_run(runs_dir)
            (repo_root / "dashboard" / "app.js").write_text("const oldValue = false;\n", encoding="utf-8")
            (repo_root / "tests" / "test_dashboard.py").write_text(
                "def test_existing():\n    assert True\n\ndef test_delivery_done():\n    assert True\n",
                encoding="utf-8",
            )

            result = generate_release_readiness("release-run-1", runs_dir=runs_dir, repo_root=repo_root)
            readiness_json_exists = (runs_dir / "release-run-1" / "release_readiness.json").exists()
            readiness_md_exists = (runs_dir / "release-run-1" / "release_readiness.md").exists()
            pr_draft_exists = (runs_dir / "release-run-1" / "pr_draft.md").exists()
            pr_draft = (runs_dir / "release-run-1" / "pr_draft.md").read_text(encoding="utf-8")

        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["release_decision"], "ready_for_pr_ci")
        self.assertEqual(result["blockers"], [])
        self.assertTrue(any(gate["id"] == "acceptance_tests" and gate["status"] == "passed" for gate in result["gates"]))
        self.assertIn("dashboard/app.js", result["evidence"]["changed_files"])
        self.assertIn("tests/test_dashboard.py", result["evidence"]["working_tree"]["tracked_changed_files"])
        self.assertTrue(readiness_json_exists)
        self.assertTrue(readiness_md_exists)
        self.assertTrue(pr_draft_exists)
        self.assertIn("## Why This Should Enter PR/CI", pr_draft)
        self.assertIn("## Verification", pr_draft)
        self.assertIn("python3 -m unittest discover -s tests -v", pr_draft)

    def test_release_readiness_blocks_when_acceptance_is_missing_or_tests_failed(self) -> None:
        from growth_dev.team.release import generate_release_readiness

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "repo"
            repo_root.mkdir()
            _init_git_repo(repo_root)
            runs_dir = root / "runs"
            run_dir = _write_ready_run(runs_dir)
            status_path = run_dir / "acceptance" / "status.json"
            acceptance = json.loads(status_path.read_text(encoding="utf-8"))
            acceptance["steps"][1]["exit_code"] = 1
            acceptance["status"] = "failed"
            status_path.write_text(json.dumps(acceptance), encoding="utf-8")

            result = generate_release_readiness("release-run-1", runs_dir=runs_dir, repo_root=repo_root)

        self.assertEqual(result["release_decision"], "blocked")
        self.assertTrue(any("acceptance" in blocker for blocker in result["blockers"]))
        self.assertTrue(any(gate["id"] == "acceptance_tests" and gate["status"] == "blocked" for gate in result["gates"]))

    def test_release_readiness_blocks_on_risk_events_or_implementation_blockers(self) -> None:
        from growth_dev.team.release import generate_release_readiness

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "repo"
            repo_root.mkdir()
            _init_git_repo(repo_root)
            runs_dir = root / "runs"
            run_dir = _write_ready_run(runs_dir)
            record_path = run_dir / "team_run_record.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["risk_events"] = ["review_blocker:missing_state"]
            record_path.write_text(json.dumps(record), encoding="utf-8")
            trace_path = run_dir / "codex" / "implementation_trace.json"
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            trace["blockers"] = ["schema_mismatch"]
            trace_path.write_text(json.dumps(trace), encoding="utf-8")

            result = generate_release_readiness("release-run-1", runs_dir=runs_dir, repo_root=repo_root)

        self.assertEqual(result["release_decision"], "blocked")
        self.assertIn("review_blocker:missing_state", result["blockers"])
        self.assertIn("schema_mismatch", result["blockers"])

    def test_release_readiness_warns_on_quality_needs_attention_only(self) -> None:
        from growth_dev.team.release import generate_release_readiness

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "repo"
            repo_root.mkdir()
            _init_git_repo(repo_root)
            runs_dir = root / "runs"
            run_dir = _write_ready_run(runs_dir)
            (run_dir / "ui_spec.md").write_text("# UI Spec\n\nxhs_browser_benchmark stale context.\n", encoding="utf-8")
            (repo_root / "dashboard" / "app.js").write_text("const oldValue = false;\n", encoding="utf-8")
            (repo_root / "tests" / "test_dashboard.py").write_text(
                "def test_existing():\n    assert True\n\ndef test_delivery_done():\n    assert True\n",
                encoding="utf-8",
            )

            result = generate_release_readiness("release-run-1", runs_dir=runs_dir, repo_root=repo_root)

        self.assertEqual(result["release_decision"], "ready_with_warnings")
        self.assertTrue(any("文件质量" in warning for warning in result["warnings"]))

    def test_release_readiness_blocks_unrelated_tracked_files_and_warns_untracked_files(self) -> None:
        from growth_dev.team.release import generate_release_readiness

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "repo"
            repo_root.mkdir()
            _init_git_repo(repo_root)
            runs_dir = root / "runs"
            _write_ready_run(runs_dir)
            (repo_root / "dashboard" / "app.js").write_text("const oldValue = false;\n", encoding="utf-8")
            (repo_root / "README.md").write_text("unrelated tracked file\n", encoding="utf-8")
            _run(["git", "add", "README.md"], repo_root)
            (repo_root / "scratch.log").write_text("local note\n", encoding="utf-8")

            result = generate_release_readiness("release-run-1", runs_dir=runs_dir, repo_root=repo_root)

        self.assertEqual(result["release_decision"], "blocked")
        self.assertIn("README.md", result["evidence"]["working_tree"]["unrelated_tracked_files"])
        self.assertIn("scratch.log", result["evidence"]["working_tree"]["untracked_files"])
        self.assertTrue(any("未跟踪文件" in warning for warning in result["warnings"]))

    def test_pr_draft_redacts_raw_diff_logs_env_and_secrets(self) -> None:
        from growth_dev.team.release import generate_release_readiness

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "repo"
            repo_root.mkdir()
            _init_git_repo(repo_root)
            runs_dir = root / "runs"
            run_dir = _write_ready_run(runs_dir)
            (run_dir / "test_report.md").write_text("# Test\n\nOK\n\n.env sk-should-not-leak api_key=secret\n", encoding="utf-8")
            (run_dir / "codex" / "diff.patch").write_text("+raw diff secret sk-should-not-leak\n", encoding="utf-8")

            result = generate_release_readiness("release-run-1", runs_dir=runs_dir, repo_root=repo_root)
            payload = json.dumps(result, ensure_ascii=False)
            draft = (run_dir / "pr_draft.md").read_text(encoding="utf-8")

        self.assertNotIn("sk-should-not-leak", payload)
        self.assertNotIn("sk-should-not-leak", draft)
        self.assertNotIn("api_key=secret", payload)
        self.assertNotIn("raw diff secret", draft)
        self.assertNotIn(".env", draft)

    def test_cli_release_readiness_generates_artifacts_and_json_output(self) -> None:
        from growth_dev.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "repo"
            repo_root.mkdir()
            _init_git_repo(repo_root)
            runs_dir = root / "runs"
            _write_ready_run(runs_dir)
            (repo_root / "dashboard" / "app.js").write_text("const oldValue = false;\n", encoding="utf-8")
            (repo_root / "tests" / "test_dashboard.py").write_text(
                "def test_existing():\n    assert True\n\ndef test_delivery_done():\n    assert True\n",
                encoding="utf-8",
            )

            with _captured_output() as (stdout, stderr):
                exit_code = main(["team", "release", "readiness", "--run-id", "release-run-1", "--runs-dir", str(runs_dir), "--repo-root", str(repo_root)])
            with _captured_output() as (json_stdout, json_stderr):
                json_exit = main(
                    [
                        "team",
                        "release",
                        "readiness",
                        "--run-id",
                        "release-run-1",
                        "--runs-dir",
                        str(runs_dir),
                        "--repo-root",
                        str(repo_root),
                        "--json",
                    ]
                )
            parsed = json.loads(json_stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("ready_for_pr_ci", stdout.getvalue())
        self.assertEqual(json_exit, 0)
        self.assertEqual(parsed["release_decision"], "ready_for_pr_ci")

    def test_cli_release_readiness_reports_missing_run(self) -> None:
        from growth_dev.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"

            with _captured_output() as (stdout, stderr):
                exit_code = main(["team", "release", "readiness", "--run-id", "missing-run", "--runs-dir", str(runs_dir), "--repo-root", str(root)])

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("team_run_record.json not found", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
