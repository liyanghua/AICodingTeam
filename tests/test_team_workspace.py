from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


def _write_run_fixture(root: Path, *, run_id: str = "workspace-run", status: str = "completed") -> Path:
    run_dir = root / "runs" / run_id
    requirements_dir = run_dir / "requirements"
    planning_dir = run_dir / "planning"
    slices_dir = run_dir / "slices"
    codex_dir = run_dir / "codex"
    trace_dir = codex_dir / "slices" / "slice-001"
    trace_dir.mkdir(parents=True)
    requirements_dir.mkdir(parents=True)
    planning_dir.mkdir(parents=True)
    slices_dir.mkdir(parents=True)
    record = {
        "run_id": run_id,
        "team_id": "team",
        "domain_id": "web_monitoring",
        "brief": "Build workspace view with token=sk-should-not-leak",
        "status": status,
        "started_at": "2026-06-01T00:00:00+00:00",
        "finished_at": "2026-06-01T00:05:00+00:00" if status == "completed" else "",
        "run_dir": str(run_dir),
        "agent_runs": [
            {"agent_id": "orchestrator", "status": "completed", "started_at": "a", "finished_at": "b", "risk_events": [], "output_paths": ["task.yaml"], "message": "ok", "metadata": {}},
            {"agent_id": "coder", "status": "completed", "started_at": "c", "finished_at": "d", "risk_events": [], "output_paths": ["codex/diff.patch"], "message": "ok", "metadata": {}},
        ],
        "gate_results": [
            {"gate_id": "before_coding", "status": "passed", "required_artifacts": ["prd.md"], "missing_artifacts": [], "checked_at": "now", "before_agent": "coder"}
        ],
        "artifacts": {"diff.patch": "codex/diff.patch"},
        "risk_events": [],
    }
    (run_dir / "team_run_record.json").write_text(json.dumps(record), encoding="utf-8")
    (run_dir / "events.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"event": "run_started", "run_id": run_id, "created_at": "2026-06-01T00:00:00+00:00"}),
                json.dumps({"event": "gate_checked", "gate_id": "before_coding", "status": "passed", "created_at": "2026-06-01T00:01:00+00:00"}),
                json.dumps({"event": "run_completed", "run_id": run_id, "created_at": "2026-06-01T00:05:00+00:00"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "acceptance_criteria.md").write_text("# Acceptance Criteria\n\n- `AC-001` Workspace is visible.\n", encoding="utf-8")
    (requirements_dir / "brief_analysis.json").write_text(
        json.dumps({"schema_version": 1, "run_id": run_id, "domain_id": "web_monitoring", "blocking_questions": []}),
        encoding="utf-8",
    )
    (requirements_dir / "capability_boundary.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_id,
                "change_type": "extend_existing_capability",
                "existing_capabilities": [{"id": "dashboard_flow", "summary": "Dashboard has flow nodes."}],
                "required_new_capabilities": [{"id": "task_workspace", "summary": "Dashboard shows task workspace."}],
            }
        ),
        encoding="utf-8",
    )
    (planning_dir / "acceptance_coverage_matrix.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_id,
                "acceptance_criteria": [{"id": "AC-001", "description": "Workspace is visible.", "covering_slice_ids": ["slice-001"]}],
                "slices": [{"id": "slice-001", "title": "Workspace summary", "acceptance_criteria_ids": ["AC-001"], "verification_commands": ["python3 -m unittest tests.test_team_workspace -v"]}],
            }
        ),
        encoding="utf-8",
    )
    (planning_dir / "tdd_plan.json").write_text(
        json.dumps({"schema_version": 1, "run_id": run_id, "status": "passed", "test_cases": [{"verification_command": "python3 -m unittest tests.test_team_workspace -v"}]}),
        encoding="utf-8",
    )
    (slices_dir / "slice-001.yaml").write_text(
        "slice_id: slice-001\ntitle: Workspace summary\nacceptance_criteria_ids:\n  - AC-001\nverification_commands:\n  - python3 -m unittest tests.test_team_workspace -v\n",
        encoding="utf-8",
    )
    (codex_dir / "slice_loop_state.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_id,
                "enabled": True,
                "status": "completed",
                "current_slice_id": "",
                "completed_slice_ids": ["slice-001"],
                "pending_slice_ids": [],
                "slices": [{"id": "slice-001", "title": "Workspace summary", "status": "completed", "verification_commands": ["python3 -m unittest tests.test_team_workspace -v"]}],
                "blockers": [],
                "risk_events": [],
            }
        ),
        encoding="utf-8",
    )
    (trace_dir / "slice_trace.json").write_text(json.dumps({"schema_version": 1, "slice_id": "slice-001", "status": "completed"}), encoding="utf-8")
    (run_dir / "implementation_completion_gate.json").write_text(
        json.dumps({"schema_version": 1, "run_id": run_id, "status": "passed", "checks": [{"id": "all_slices_completed", "status": "passed"}], "blockers": [], "next_action": "review"}),
        encoding="utf-8",
    )
    (codex_dir / "diff.patch").write_text("+api_key = 'sk-should-not-leak'\n", encoding="utf-8")
    return run_dir


class TeamWorkspaceTests(unittest.TestCase):
    def test_refresh_writes_workspace_journal_and_tool_context_with_redaction(self) -> None:
        from growth_dev.team.workspace import refresh_task_workspace

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = _write_run_fixture(root)
            result = refresh_task_workspace("workspace-run", runs_dir=root / "runs")
            workspace = json.loads((run_dir / "task_workspace.json").read_text(encoding="utf-8"))
            journal_lines = (run_dir / "task_journal.jsonl").read_text(encoding="utf-8").splitlines()
            tool_context = (run_dir / "tool_context" / "codex.md").read_text(encoding="utf-8")
            payload = json.dumps(result, ensure_ascii=False) + tool_context + "\n".join(journal_lines)

        self.assertEqual(workspace["schema_version"], 1)
        self.assertEqual(workspace["run_id"], "workspace-run")
        self.assertEqual(workspace["loop_phase"], "finish")
        self.assertEqual(workspace["slices"]["completed"][0]["id"], "slice-001")
        self.assertIn("python3 -m unittest tests.test_team_workspace -v", workspace["verification_commands"])
        self.assertTrue(any(event["event"] == "run_completed" for event in [json.loads(line) for line in journal_lines]))
        self.assertIn("Overall goal", tool_context)
        self.assertIn("Current loop phase", tool_context)
        self.assertNotIn("sk-should-not-leak", payload)
        self.assertNotIn(".env", payload)
        self.assertEqual(result["artifacts"]["task_workspace"], "task_workspace.md")

    def test_refresh_is_idempotent_for_journal_events(self) -> None:
        from growth_dev.team.workspace import refresh_task_workspace

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = _write_run_fixture(root)
            refresh_task_workspace("workspace-run", runs_dir=root / "runs")
            refresh_task_workspace("workspace-run", runs_dir=root / "runs")
            journal_lines = (run_dir / "task_journal.jsonl").read_text(encoding="utf-8").splitlines()

        events = [json.loads(line)["event"] for line in journal_lines]
        self.assertEqual(events.count("run_completed"), 1)
        self.assertEqual(events.count("before_coding_gate_passed"), 1)

    def test_missing_artifacts_still_generate_warning_workspace(self) -> None:
        from growth_dev.team.workspace import refresh_task_workspace

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "runs" / "missing-run"
            run_dir.mkdir(parents=True)
            (run_dir / "team_run_record.json").write_text(
                json.dumps({"run_id": "missing-run", "domain_id": "demo", "brief": "demo", "status": "running", "agent_runs": [], "gate_results": [], "risk_events": []}),
                encoding="utf-8",
            )

            result = refresh_task_workspace("missing-run", runs_dir=root / "runs")

        self.assertEqual(result["task_workspace"]["loop_phase"], "plan")
        self.assertTrue(result["task_workspace"]["warnings"])

    def test_cli_workspace_refresh_and_show_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_run_fixture(root)

            refresh = subprocess.run(
                ["python3", "-m", "growth_dev.cli", "team", "workspace", "refresh", "--run-id", "workspace-run", "--runs-dir", str(root / "runs")],
                cwd=Path(__file__).resolve().parents[1],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            show = subprocess.run(
                ["python3", "-m", "growth_dev.cli", "team", "workspace", "show", "--run-id", "workspace-run", "--runs-dir", str(root / "runs"), "--json"],
                cwd=Path(__file__).resolve().parents[1],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

        self.assertEqual(refresh.returncode, 0, refresh.stderr)
        self.assertEqual(show.returncode, 0, show.stderr)
        payload = json.loads(show.stdout)
        self.assertEqual(payload["task_workspace"]["run_id"], "workspace-run")

    def test_cli_workspace_missing_run_is_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = subprocess.run(
                ["python3", "-m", "growth_dev.cli", "team", "workspace", "show", "--run-id", "missing-run", "--runs-dir", str(root / "runs")],
                cwd=Path(__file__).resolve().parents[1],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Run not found", result.stderr)


if __name__ == "__main__":
    unittest.main()
