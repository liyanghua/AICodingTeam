from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from tests.test_team_release import _init_git_repo, _write_ready_run


@contextlib.contextmanager
def _captured_output():
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        yield stdout, stderr


def _write_readiness(root: Path, *, decision: str = "ready_for_pr_ci") -> tuple[Path, Path]:
    repo_root = root / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    subprocess.run(["git", "remote", "add", "origin", "git@github.com:example/project.git"], cwd=repo_root, check=True)
    runs_dir = root / "runs"
    run_dir = _write_ready_run(runs_dir, "release-run-1")
    (repo_root / "dashboard" / "app.js").write_text("const oldValue = false;\n", encoding="utf-8")
    (repo_root / "tests" / "test_dashboard.py").write_text(
        "def test_existing():\n    assert True\n\ndef test_delivery_done():\n    assert True\n",
        encoding="utf-8",
    )
    from growth_dev.team.release import generate_release_readiness

    readiness = generate_release_readiness("release-run-1", runs_dir=runs_dir, repo_root=repo_root)
    if decision != readiness["release_decision"]:
        readiness["release_decision"] = decision
        if decision == "blocked":
            readiness["blockers"] = ["blocked by test"]
        (run_dir / "release_readiness.json").write_text(json.dumps(readiness), encoding="utf-8")
    return runs_dir, repo_root


class TeamGitHubPrTests(unittest.TestCase):
    def test_create_draft_pr_blocks_when_release_readiness_is_blocked(self) -> None:
        from growth_dev.team.github_pr import create_draft_pr

        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir, repo_root = _write_readiness(Path(temp_dir), decision="blocked")

            result = create_draft_pr("release-run-1", runs_dir=runs_dir, repo_root=repo_root)
            artifact = json.loads((runs_dir / "release-run-1" / "github_pr.json").read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("blocked" in item for item in result["blockers"]))
        self.assertEqual(artifact["status"], "failed")

    def test_create_draft_pr_pushes_branch_and_writes_artifacts_with_fake_gh(self) -> None:
        from growth_dev.team.github_pr import create_draft_pr

        calls: list[list[str]] = []

        def fake_run(command, **kwargs):
            calls.append(list(command))
            if command[:3] == ["git", "branch", "--show-current"]:
                return subprocess.CompletedProcess(command, 0, stdout="feature/demo\n", stderr="")
            if command[:3] == ["git", "remote", "get-url"]:
                return subprocess.CompletedProcess(command, 0, stdout="git@github.com:example/project.git\n", stderr="")
            if command[:2] == ["git", "status"]:
                return subprocess.CompletedProcess(command, 0, stdout=" M dashboard/app.js\n M tests/test_dashboard.py\n", stderr="")
            if command[:2] == ["git", "push"]:
                return subprocess.CompletedProcess(command, 0, stdout="pushed\n", stderr="")
            if command[:3] == ["gh", "auth", "status"]:
                return subprocess.CompletedProcess(command, 0, stdout="Logged in\n", stderr="")
            if command[:3] == ["gh", "pr", "view"]:
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="no pull requests found\n")
            if command[:3] == ["gh", "pr", "create"]:
                return subprocess.CompletedProcess(command, 0, stdout="https://github.com/example/project/pull/42\n", stderr="")
            raise AssertionError(f"unexpected command: {command}")

        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir, repo_root = _write_readiness(Path(temp_dir))

            result = create_draft_pr("release-run-1", runs_dir=runs_dir, repo_root=repo_root, base="main", push=True, command_runner=fake_run)
            status = json.loads((runs_dir / "release-run-1" / "github_pr.json").read_text(encoding="utf-8"))
            note = (runs_dir / "release-run-1" / "github_pr.md").read_text(encoding="utf-8")

        self.assertEqual(result["status"], "created")
        self.assertEqual(result["pr"]["number"], 42)
        self.assertEqual(result["pr"]["head"], "feature/demo")
        self.assertTrue(any(call[:2] == ["git", "push"] for call in calls))
        self.assertTrue(any(call[:3] == ["gh", "pr", "create"] and "--draft" in call for call in calls))
        self.assertEqual(status["pr"]["url"], "https://github.com/example/project/pull/42")
        self.assertIn("Draft PR", note)

    def test_create_draft_pr_records_missing_gh_as_failed_artifact(self) -> None:
        from growth_dev.team.github_pr import create_draft_pr

        def fake_run(command, **kwargs):
            if command[:3] == ["git", "branch", "--show-current"]:
                return subprocess.CompletedProcess(command, 0, stdout="feature/demo\n", stderr="")
            if command[:3] == ["git", "remote", "get-url"]:
                return subprocess.CompletedProcess(command, 0, stdout="git@github.com:example/project.git\n", stderr="")
            if command[:2] == ["git", "status"]:
                return subprocess.CompletedProcess(command, 0, stdout=" M dashboard/app.js\n M tests/test_dashboard.py\n", stderr="")
            if command[:3] == ["gh", "auth", "status"]:
                raise FileNotFoundError("gh")
            raise AssertionError(f"unexpected command: {command}")

        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir, repo_root = _write_readiness(Path(temp_dir))

            result = create_draft_pr("release-run-1", runs_dir=runs_dir, repo_root=repo_root, command_runner=fake_run)

        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("gh CLI" in item for item in result["blockers"]))

    def test_refresh_ci_status_maps_passed_failed_running_and_empty_checks(self) -> None:
        from growth_dev.team.github_pr import refresh_ci_status

        def runner_for(stdout: str):
            def fake_run(command, **kwargs):
                if command[:3] == ["gh", "pr", "checks"]:
                    return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")
                raise AssertionError(f"unexpected command: {command}")

            return fake_run

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir, repo_root = _write_readiness(root)
            pr_status = {
                "schema_version": 1,
                "run_id": "release-run-1",
                "status": "created",
                "pr": {"url": "https://github.com/example/project/pull/42", "number": 42, "title": "demo", "state": "OPEN", "is_draft": True, "base": "main", "head": "feature/demo"},
                "release_decision": "ready_for_pr_ci",
                "warnings": [],
                "blockers": [],
                "commands": [],
                "next_action": "",
            }
            (runs_dir / "release-run-1" / "github_pr.json").write_text(json.dumps(pr_status), encoding="utf-8")

            passed = refresh_ci_status("release-run-1", runs_dir=runs_dir, repo_root=repo_root, command_runner=runner_for(json.dumps([{"name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS"}])))
            failed = refresh_ci_status("release-run-1", runs_dir=runs_dir, repo_root=repo_root, command_runner=runner_for(json.dumps([{"name": "tests", "status": "COMPLETED", "conclusion": "FAILURE"}])))
            running = refresh_ci_status("release-run-1", runs_dir=runs_dir, repo_root=repo_root, command_runner=runner_for(json.dumps([{"name": "tests", "status": "IN_PROGRESS", "conclusion": ""}])))
            empty = refresh_ci_status("release-run-1", runs_dir=runs_dir, repo_root=repo_root, command_runner=runner_for("[]"))

        self.assertEqual(passed["status"], "passed")
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(running["status"], "running")
        self.assertEqual(empty["status"], "unknown")
        self.assertTrue(empty["warnings"])

    def test_refresh_ci_status_accepts_current_gh_state_and_bucket_fields(self) -> None:
        from growth_dev.team.github_pr import refresh_ci_status

        captured_commands: list[list[str]] = []

        def fake_run(command, **kwargs):
            captured_commands.append(list(command))
            if command[:3] == ["gh", "pr", "checks"]:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps(
                        [
                            {
                                "name": "tests",
                                "workflow": "CI",
                                "state": "SUCCESS",
                                "bucket": "pass",
                                "link": "https://github.com/example/project/actions/runs/1",
                            }
                        ]
                    ),
                    stderr="",
                )
            raise AssertionError(f"unexpected command: {command}")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir, repo_root = _write_readiness(root)
            pr_status = {
                "schema_version": 1,
                "run_id": "release-run-1",
                "status": "created",
                "pr": {"url": "https://github.com/example/project/pull/42", "number": 42, "title": "demo", "state": "OPEN", "is_draft": True, "base": "main", "head": "feature/demo"},
                "release_decision": "ready_for_pr_ci",
                "warnings": [],
                "blockers": [],
                "commands": [],
                "next_action": "",
            }
            (runs_dir / "release-run-1" / "github_pr.json").write_text(json.dumps(pr_status), encoding="utf-8")

            result = refresh_ci_status("release-run-1", runs_dir=runs_dir, repo_root=repo_root, command_runner=fake_run)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["checks"][0]["status"], "SUCCESS")
        self.assertEqual(result["checks"][0]["conclusion"], "pass")
        fields = captured_commands[0][-1]
        self.assertIn("state", fields)
        self.assertIn("bucket", fields)
        self.assertNotIn("status", fields)
        self.assertNotIn("conclusion", fields)

    def test_refresh_ci_status_treats_no_checks_reported_as_warning(self) -> None:
        from growth_dev.team.github_pr import refresh_ci_status

        def fake_run(command, **kwargs):
            if command[:3] == ["gh", "pr", "checks"]:
                return subprocess.CompletedProcess(
                    command,
                    1,
                    stdout="",
                    stderr="no checks reported on the 'feature/demo' branch\n",
                )
            raise AssertionError(f"unexpected command: {command}")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir, repo_root = _write_readiness(root)
            pr_status = {
                "schema_version": 1,
                "run_id": "release-run-1",
                "status": "created",
                "pr": {"url": "https://github.com/example/project/pull/42", "number": 42, "title": "demo", "state": "OPEN", "is_draft": True, "base": "main", "head": "feature/demo"},
                "release_decision": "ready_for_pr_ci",
                "warnings": [],
                "blockers": [],
                "commands": [],
                "next_action": "",
            }
            (runs_dir / "release-run-1" / "github_pr.json").write_text(json.dumps(pr_status), encoding="utf-8")

            result = refresh_ci_status("release-run-1", runs_dir=runs_dir, repo_root=repo_root, command_runner=fake_run)
            artifact = json.loads((runs_dir / "release-run-1" / "ci_status.json").read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["checks"], [])
        self.assertEqual(result["blockers"], [])
        self.assertTrue(result["warnings"])
        self.assertIn("尚未发现", result["summary"])
        self.assertEqual(artifact["blockers"], [])

    def test_cli_pr_draft_and_status_commands(self) -> None:
        from growth_dev import cli

        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir, repo_root = _write_readiness(Path(temp_dir))
            with mock.patch("growth_dev.team.github_pr.subprocess.run") as run_mock:
                run_mock.side_effect = [
                    subprocess.CompletedProcess(["git"], 0, stdout="feature/demo\n", stderr=""),
                    subprocess.CompletedProcess(["git"], 0, stdout="git@github.com:example/project.git\n", stderr=""),
                    subprocess.CompletedProcess(["git"], 0, stdout=" M dashboard/app.js\n M tests/test_dashboard.py\n", stderr=""),
                    subprocess.CompletedProcess(["gh"], 0, stdout="Logged in\n", stderr=""),
                    subprocess.CompletedProcess(["gh"], 1, stdout="", stderr="no pull requests found\n"),
                    subprocess.CompletedProcess(["git"], 0, stdout="pushed\n", stderr=""),
                    subprocess.CompletedProcess(["gh"], 0, stdout="https://github.com/example/project/pull/42\n", stderr=""),
                ]
                with _captured_output() as (stdout, stderr):
                    draft_exit = cli.main(["team", "pr", "draft", "--run-id", "release-run-1", "--runs-dir", str(runs_dir), "--repo-root", str(repo_root), "--base", "main", "--push"])

            with mock.patch("growth_dev.team.github_pr.subprocess.run") as run_mock:
                run_mock.return_value = subprocess.CompletedProcess(["gh"], 0, stdout=json.dumps([{"name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS"}]), stderr="")
                with _captured_output() as (json_stdout, json_stderr):
                    status_exit = cli.main(["team", "pr", "status", "--run-id", "release-run-1", "--runs-dir", str(runs_dir), "--repo-root", str(repo_root), "--json"])

        self.assertEqual(draft_exit, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("created", stdout.getvalue())
        self.assertEqual(status_exit, 0)
        self.assertEqual(json.loads(json_stdout.getvalue())["status"], "passed")


if __name__ == "__main__":
    unittest.main()
