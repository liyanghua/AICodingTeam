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


def _write_github_pr_status(run_dir: Path, *, status: str = "created") -> None:
    (run_dir / "github_pr.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_dir.name,
                "status": status,
                "generated_at": "2026-05-28T00:06:00+00:00",
                "pr": {
                    "number": 42,
                    "url": "https://github.com/example/project/pull/42",
                    "title": "demo",
                    "state": "OPEN",
                    "is_draft": True,
                    "base": "main",
                    "head": "feature/demo",
                },
                "release_decision": "ready_for_pr_ci",
                "warnings": [],
                "blockers": [],
                "commands": [],
                "next_action": "刷新 PR/CI 状态。",
            }
        ),
        encoding="utf-8",
    )


def _write_ci_status(run_dir: Path, *, status: str = "passed") -> None:
    checks = [{"name": "Python unittest", "workflow": "CI", "status": "SUCCESS", "conclusion": "pass", "url": "https://github.com/example/project/actions/runs/1"}] if status == "passed" else []
    blockers = ["CI checks failed: Python unittest"] if status == "failed" else []
    warnings = ["CI checks 仍在运行。"] if status in {"running", "pending"} else ["尚未发现 CI checks，可能是仓库没有 workflow 或 GitHub 尚未生成 checks。"] if status == "unknown" else []
    (run_dir / "ci_status.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_dir.name,
                "status": status,
                "generated_at": "2026-05-28T00:07:00+00:00",
                "pr_url": "https://github.com/example/project/pull/42",
                "checks": checks,
                "summary": "1 个 CI check 已通过。" if status == "passed" else "存在失败的 CI check，需要处理后再进入合并。" if status == "failed" else "CI 正在运行，请稍后刷新。" if status == "running" else "尚未发现可用 CI checks。",
                "warnings": warnings,
                "blockers": blockers,
                "next_action": "可以进行人工 Review。" if status == "passed" else "处理 CI 状态后重试。",
            }
        ),
        encoding="utf-8",
    )


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

    def test_release_readiness_adds_ci_gate_and_blocks_only_failed_ci(self) -> None:
        from growth_dev.team.release import generate_release_readiness

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "repo"
            repo_root.mkdir()
            _init_git_repo(repo_root)
            runs_dir = root / "runs"
            passed_run = _write_ready_run(runs_dir, "ci-passed-run")
            failed_run = _write_ready_run(runs_dir, "ci-failed-run")
            unknown_run = _write_ready_run(runs_dir, "ci-unknown-run")
            for run_dir in (passed_run, failed_run, unknown_run):
                (repo_root / "dashboard" / "app.js").write_text("const oldValue = false;\n", encoding="utf-8")
                (repo_root / "tests" / "test_dashboard.py").write_text(
                    "def test_existing():\n    assert True\n\ndef test_delivery_done():\n    assert True\n",
                    encoding="utf-8",
                )
            _write_ci_status(passed_run, status="passed")
            _write_ci_status(failed_run, status="failed")
            _write_ci_status(unknown_run, status="unknown")

            passed = generate_release_readiness("ci-passed-run", runs_dir=runs_dir, repo_root=repo_root)
            failed = generate_release_readiness("ci-failed-run", runs_dir=runs_dir, repo_root=repo_root)
            unknown = generate_release_readiness("ci-unknown-run", runs_dir=runs_dir, repo_root=repo_root)

        self.assertTrue(any(gate["id"] == "ci_status" and gate["status"] == "passed" for gate in passed["gates"]))
        self.assertEqual(passed["evidence"]["ci_status"], "passed")
        self.assertEqual(failed["release_decision"], "blocked")
        self.assertTrue(any(gate["id"] == "ci_status" and gate["status"] == "blocked" for gate in failed["gates"]))
        self.assertTrue(any("CI" in blocker for blocker in failed["blockers"]))
        self.assertNotEqual(unknown["release_decision"], "blocked")
        self.assertTrue(any(gate["id"] == "ci_status" and gate["status"] == "warning" for gate in unknown["gates"]))

    def test_staging_readiness_requires_pr_and_passed_ci(self) -> None:
        from growth_dev.team.release import generate_release_readiness, generate_staging_readiness

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "repo"
            repo_root.mkdir()
            _init_git_repo(repo_root)
            runs_dir = root / "runs"
            run_dir = _write_ready_run(runs_dir)
            (repo_root / "dashboard" / "app.js").write_text("const oldValue = false;\n", encoding="utf-8")
            (repo_root / "tests" / "test_dashboard.py").write_text(
                "def test_existing():\n    assert True\n\ndef test_delivery_done():\n    assert True\n",
                encoding="utf-8",
            )
            _write_github_pr_status(run_dir)
            _write_ci_status(run_dir, status="passed")
            generate_release_readiness("release-run-1", runs_dir=runs_dir, repo_root=repo_root)

            result = generate_staging_readiness("release-run-1", runs_dir=runs_dir)
            artifact = json.loads((run_dir / "staging_readiness.json").read_text(encoding="utf-8"))
            note = (run_dir / "staging_readiness.md").read_text(encoding="utf-8")

        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["staging_decision"], "ready_for_staging")
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["evidence"]["ci_status"], "passed")
        self.assertTrue(any(gate["id"] == "ci_passed" and gate["status"] == "passed" for gate in result["gates"]))
        self.assertEqual(artifact["staging_decision"], "ready_for_staging")
        self.assertIn("# Staging Readiness", note)

    def test_staging_readiness_waits_for_running_or_unknown_ci_and_blocks_failed_ci(self) -> None:
        from growth_dev.team.release import generate_release_readiness, generate_staging_readiness

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "repo"
            repo_root.mkdir()
            _init_git_repo(repo_root)
            runs_dir = root / "runs"
            running_run = _write_ready_run(runs_dir, "ci-running-run")
            failed_run = _write_ready_run(runs_dir, "ci-failed-run")
            for run_dir in (running_run, failed_run):
                (repo_root / "dashboard" / "app.js").write_text("const oldValue = false;\n", encoding="utf-8")
                (repo_root / "tests" / "test_dashboard.py").write_text(
                    "def test_existing():\n    assert True\n\ndef test_delivery_done():\n    assert True\n",
                    encoding="utf-8",
                )
                _write_github_pr_status(run_dir)
            _write_ci_status(running_run, status="running")
            _write_ci_status(failed_run, status="failed")
            generate_release_readiness("ci-running-run", runs_dir=runs_dir, repo_root=repo_root)
            generate_release_readiness("ci-failed-run", runs_dir=runs_dir, repo_root=repo_root)

            running = generate_staging_readiness("ci-running-run", runs_dir=runs_dir)
            failed = generate_staging_readiness("ci-failed-run", runs_dir=runs_dir)

        self.assertEqual(running["staging_decision"], "waiting_for_ci")
        self.assertTrue(any(gate["id"] == "ci_passed" and gate["status"] == "warning" for gate in running["gates"]))
        self.assertEqual(failed["staging_decision"], "blocked")
        self.assertTrue(any(gate["id"] == "ci_passed" and gate["status"] == "blocked" for gate in failed["gates"]))

    def test_staging_readiness_blocks_missing_pr_or_release_readiness(self) -> None:
        from growth_dev.team.release import generate_release_readiness, generate_staging_readiness

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "repo"
            repo_root.mkdir()
            _init_git_repo(repo_root)
            runs_dir = root / "runs"
            no_pr_run = _write_ready_run(runs_dir, "no-pr-run")
            no_release_run = _write_ready_run(runs_dir, "no-release-run")
            (repo_root / "dashboard" / "app.js").write_text("const oldValue = false;\n", encoding="utf-8")
            (repo_root / "tests" / "test_dashboard.py").write_text(
                "def test_existing():\n    assert True\n\ndef test_delivery_done():\n    assert True\n",
                encoding="utf-8",
            )
            _write_ci_status(no_pr_run, status="passed")
            generate_release_readiness("no-pr-run", runs_dir=runs_dir, repo_root=repo_root)

            missing_pr = generate_staging_readiness("no-pr-run", runs_dir=runs_dir)
            missing_release = generate_staging_readiness("no-release-run", runs_dir=runs_dir)

        self.assertEqual(missing_pr["staging_decision"], "blocked")
        self.assertTrue(any("Draft PR" in blocker for blocker in missing_pr["blockers"]))
        self.assertEqual(missing_release["staging_decision"], "blocked")
        self.assertTrue(any("release_readiness" in blocker for blocker in missing_release["blockers"]))

    def test_staging_rehearsal_completes_when_ready_and_full_tests_pass(self) -> None:
        from growth_dev.team.release import generate_release_readiness, generate_staging_readiness
        from growth_dev.team.staging import run_staging_rehearsal

        calls: list[list[str]] = []

        def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            if command[:2] == ["git", "status"]:
                return subprocess.CompletedProcess(command, 0, stdout=" M dashboard/app.js\n", stderr="")
            if command[:3] == ["python3", "-m", "unittest"]:
                return subprocess.CompletedProcess(command, 0, stdout="OK\n.env sk-should-not-leak api_key=secret\n", stderr="")
            raise AssertionError(f"unexpected command: {command}")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "repo"
            repo_root.mkdir()
            _init_git_repo(repo_root)
            runs_dir = root / "runs"
            run_dir = _write_ready_run(runs_dir)
            (repo_root / "dashboard" / "app.js").write_text("const oldValue = false;\n", encoding="utf-8")
            (repo_root / "tests" / "test_dashboard.py").write_text(
                "def test_existing():\n    assert True\n\ndef test_delivery_done():\n    assert True\n",
                encoding="utf-8",
            )
            _write_github_pr_status(run_dir)
            _write_ci_status(run_dir, status="passed")
            generate_release_readiness("release-run-1", runs_dir=runs_dir, repo_root=repo_root)
            generate_staging_readiness("release-run-1", runs_dir=runs_dir)

            result = run_staging_rehearsal("release-run-1", runs_dir=runs_dir, repo_root=repo_root, command_runner=fake_run)
            artifact = json.loads((run_dir / "staging_rehearsal.json").read_text(encoding="utf-8"))
            note = (run_dir / "staging_rehearsal.md").read_text(encoding="utf-8")
            stdout_log = (run_dir / "staging_rehearsal" / "tests_stdout.log").read_text(encoding="utf-8")

        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["staging_readiness_decision"], "ready_for_staging")
        self.assertTrue(any(step["id"] == "readiness" and step["status"] == "passed" for step in result["steps"]))
        self.assertTrue(any(step["id"] == "full_tests" and step["status"] == "completed" and step["exit_code"] == 0 for step in result["steps"]))
        self.assertIn("dashboard/app.js", result["evidence"]["changed_files"])
        self.assertIn(["git", "status", "--short"], calls)
        self.assertIn(["python3", "-m", "unittest", "discover", "-s", "tests", "-v"], calls)
        self.assertEqual(artifact["status"], "completed")
        self.assertIn("# Staging Rehearsal", note)
        payload = json.dumps(result, ensure_ascii=False) + note + stdout_log
        self.assertNotIn("sk-should-not-leak", payload)
        self.assertNotIn("api_key=secret", payload)
        self.assertNotIn(".env", payload)

    def test_staging_rehearsal_blocks_when_readiness_is_not_ready_and_skips_tests(self) -> None:
        from growth_dev.team.release import generate_release_readiness, generate_staging_readiness
        from growth_dev.team.staging import run_staging_rehearsal

        calls: list[list[str]] = []

        def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            if command[:2] == ["git", "status"]:
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            if command[:3] == ["python3", "-m", "unittest"]:
                raise AssertionError("full tests should be skipped when staging readiness is not ready")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "repo"
            repo_root.mkdir()
            _init_git_repo(repo_root)
            runs_dir = root / "runs"
            run_dir = _write_ready_run(runs_dir)
            _write_github_pr_status(run_dir)
            _write_ci_status(run_dir, status="running")
            generate_release_readiness("release-run-1", runs_dir=runs_dir, repo_root=repo_root)
            generate_staging_readiness("release-run-1", runs_dir=runs_dir)

            result = run_staging_rehearsal("release-run-1", runs_dir=runs_dir, repo_root=repo_root, command_runner=fake_run)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["staging_readiness_decision"], "waiting_for_ci")
        self.assertTrue(any(step["id"] == "full_tests" and step["status"] == "skipped" for step in result["steps"]))
        self.assertFalse(any(command[:3] == ["python3", "-m", "unittest"] for command in calls))

    def test_staging_rehearsal_fails_when_full_tests_fail(self) -> None:
        from growth_dev.team.release import generate_release_readiness, generate_staging_readiness
        from growth_dev.team.staging import run_staging_rehearsal

        def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            if command[:2] == ["git", "status"]:
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            if command[:3] == ["python3", "-m", "unittest"]:
                return subprocess.CompletedProcess(command, 1, stdout="Ran 1 test\n", stderr="FAILED\n")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "repo"
            repo_root.mkdir()
            _init_git_repo(repo_root)
            runs_dir = root / "runs"
            run_dir = _write_ready_run(runs_dir)
            _write_github_pr_status(run_dir)
            _write_ci_status(run_dir, status="passed")
            generate_release_readiness("release-run-1", runs_dir=runs_dir, repo_root=repo_root)
            generate_staging_readiness("release-run-1", runs_dir=runs_dir)

            result = run_staging_rehearsal("release-run-1", runs_dir=runs_dir, repo_root=repo_root, command_runner=fake_run)
            stderr_log = (run_dir / "staging_rehearsal" / "tests_stderr.log").read_text(encoding="utf-8")

        self.assertEqual(result["status"], "failed")
        self.assertTrue(any(step["id"] == "full_tests" and step["status"] == "failed" and step["exit_code"] == 1 for step in result["steps"]))
        self.assertTrue(any("全量测试" in blocker for blocker in result["blockers"]))
        self.assertIn("FAILED", stderr_log)

    def test_staging_rehearsal_generates_missing_readiness(self) -> None:
        from growth_dev.team.release import generate_release_readiness
        from growth_dev.team.staging import run_staging_rehearsal

        def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            if command[:2] == ["git", "status"]:
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            if command[:3] == ["python3", "-m", "unittest"]:
                return subprocess.CompletedProcess(command, 0, stdout="OK\n", stderr="")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "repo"
            repo_root.mkdir()
            _init_git_repo(repo_root)
            runs_dir = root / "runs"
            run_dir = _write_ready_run(runs_dir)
            _write_github_pr_status(run_dir)
            _write_ci_status(run_dir, status="passed")
            generate_release_readiness("release-run-1", runs_dir=runs_dir, repo_root=repo_root)
            self.assertFalse((run_dir / "staging_readiness.json").exists())

            result = run_staging_rehearsal("release-run-1", runs_dir=runs_dir, repo_root=repo_root, command_runner=fake_run)
            staging_readiness_exists = (run_dir / "staging_readiness.json").exists()

        self.assertEqual(result["status"], "completed")
        self.assertTrue(staging_readiness_exists)
        self.assertEqual(result["staging_readiness_decision"], "ready_for_staging")

    def test_cli_staging_rehearsal_generates_artifacts_and_json_output(self) -> None:
        from growth_dev.cli import main
        from growth_dev.team.release import generate_release_readiness, generate_staging_readiness

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "repo"
            repo_root.mkdir()
            _init_git_repo(repo_root)
            runs_dir = root / "runs"
            run_dir = _write_ready_run(runs_dir)
            (repo_root / "dashboard" / "app.js").write_text("const oldValue = false;\n", encoding="utf-8")
            (repo_root / "tests" / "test_dashboard.py").write_text(
                "import unittest\n\nclass DemoTest(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            _write_github_pr_status(run_dir)
            _write_ci_status(run_dir, status="passed")
            generate_release_readiness("release-run-1", runs_dir=runs_dir, repo_root=repo_root)
            generate_staging_readiness("release-run-1", runs_dir=runs_dir)

            with _captured_output() as (stdout, stderr):
                exit_code = main(
                    [
                        "team",
                        "release",
                        "staging-rehearsal",
                        "--run-id",
                        "release-run-1",
                        "--runs-dir",
                        str(runs_dir),
                        "--repo-root",
                        str(repo_root),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            rehearsal_json_exists = (run_dir / "staging_rehearsal.json").exists()
            rehearsal_md_exists = (run_dir / "staging_rehearsal.md").exists()

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(payload["status"], "completed")
        self.assertTrue(rehearsal_json_exists)
        self.assertTrue(rehearsal_md_exists)

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

    def test_cli_staging_readiness_generates_artifacts_and_json_output(self) -> None:
        from growth_dev.cli import main
        from growth_dev.team.release import generate_release_readiness

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / "repo"
            repo_root.mkdir()
            _init_git_repo(repo_root)
            runs_dir = root / "runs"
            run_dir = _write_ready_run(runs_dir)
            (repo_root / "dashboard" / "app.js").write_text("const oldValue = false;\n", encoding="utf-8")
            (repo_root / "tests" / "test_dashboard.py").write_text(
                "def test_existing():\n    assert True\n\ndef test_delivery_done():\n    assert True\n",
                encoding="utf-8",
            )
            _write_github_pr_status(run_dir)
            _write_ci_status(run_dir, status="passed")
            generate_release_readiness("release-run-1", runs_dir=runs_dir, repo_root=repo_root)

            with _captured_output() as (stdout, stderr):
                exit_code = main(["team", "release", "staging-readiness", "--run-id", "release-run-1", "--runs-dir", str(runs_dir), "--json"])
            staging_json_exists = (runs_dir / "release-run-1" / "staging_readiness.json").exists()
            staging_md_exists = (runs_dir / "release-run-1" / "staging_readiness.md").exists()

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["staging_decision"], "ready_for_staging")
        self.assertEqual(stderr.getvalue(), "")
        self.assertTrue(staging_json_exists)
        self.assertTrue(staging_md_exists)

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
