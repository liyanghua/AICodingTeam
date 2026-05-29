from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests.test_team_models import DOMAIN_YAML, TEAM_YAML, _field, _load_with_model


def _load_specs(temp_dir: Path) -> tuple[Any, Any]:
    from growth_dev.team.models import DomainSpec, TeamSpec

    team_path = temp_dir / "team.yaml"
    domain_path = temp_dir / "domain.yaml"
    team_path.write_text(TEAM_YAML, encoding="utf-8")
    domain_path.write_text(DOMAIN_YAML, encoding="utf-8")
    return _load_with_model(TeamSpec, team_path), _load_with_model(DomainSpec, domain_path)


def _new_runtime(team_spec: Any, domain_spec: Any, runs_dir: Path) -> Any:
    from growth_dev.team.runtime import TeamRuntime

    try:
        return TeamRuntime(team_spec=team_spec, domain_spec=domain_spec, runs_dir=runs_dir)
    except TypeError:
        return TeamRuntime(team_spec, domain_spec, runs_dir)


def _check_gate(runtime: Any, run_dir: Path, gate_id: str) -> None:
    for method_name in ("check_gate", "enforce_gate", "run_gate"):
        method = getattr(runtime, method_name, None)
        if method is not None:
            method(run_dir, gate_id)
            return
    raise AssertionError("TeamRuntime needs a public gate-checking method")


class TeamRuntimeTests(unittest.TestCase):
    def test_gate_fails_when_required_artifact_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            team_spec, domain_spec = _load_specs(root)
            runtime = _new_runtime(team_spec, domain_spec, root / "runs")
            run_dir = root / "run"
            run_dir.mkdir()
            (run_dir / "prd.md").write_text("# PRD\n", encoding="utf-8")
            (run_dir / "tech_spec.md").write_text("# Technical Spec\n", encoding="utf-8")
            (run_dir / "ui_spec.md").write_text("# UI Spec\n", encoding="utf-8")

            with self.assertRaises(Exception) as raised:
                _check_gate(runtime, run_dir, "before_coding")

        self.assertIn("eval.md", str(raised.exception))

    def test_gate_passes_when_all_required_artifacts_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            team_spec, domain_spec = _load_specs(root)
            runtime = _new_runtime(team_spec, domain_spec, root / "runs")
            run_dir = root / "run"
            run_dir.mkdir()
            for name in ("prd.md", "tech_spec.md", "ui_spec.md", "eval.md"):
                (run_dir / name).write_text(f"# {name}\n", encoding="utf-8")

            _check_gate(runtime, run_dir, "before_coding")

    def test_team_run_record_round_trips_through_dict(self) -> None:
        from growth_dev.team.models import AgentRun, TeamRunRecord

        agent_run = AgentRun(
            agent_id="product",
            status="completed",
            started_at="2026-05-20T00:00:00Z",
            finished_at="2026-05-20T00:00:01Z",
            risk_events=[],
            output_paths=["prd.md"],
        )
        record = TeamRunRecord(
            run_id="team-run-1",
            domain_id="xhs_browser_benchmark",
            brief="对比 5 个浏览器自动化框架完成小红书采集任务",
            status="completed",
            started_at="2026-05-20T00:00:00Z",
            finished_at="2026-05-20T00:00:09Z",
            agent_runs=[agent_run],
            output_paths=["final_report.md"],
            risk_events=[],
            run_dir="runs/team-run-1",
        )

        payload = record.to_dict()
        restored = TeamRunRecord.from_dict(payload)

        self.assertEqual(_field(restored, "run_id"), "team-run-1")
        self.assertEqual(_field(restored, "domain_id"), "xhs_browser_benchmark")
        self.assertEqual(_field(restored, "status"), "completed")
        self.assertEqual(_field(_field(restored, "agent_runs")[0], "output_paths"), ["prd.md"])

    def test_runtime_normalizes_relative_runs_dir_to_absolute_record_path(self) -> None:
        from growth_dev.team.models import AgentSpec, DomainSpec, TeamSpec
        from growth_dev.team.runtime import TeamRuntime

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = TeamRuntime(
                team=TeamSpec(team_id="team", agents=[AgentSpec(id="orchestrator", outputs=["task.yaml", "context.md"])]),
                domain=DomainSpec(domain_id="demo"),
                runs_dir=Path("runs"),
                repo_root=root,
            )

            record = runtime.run("demo", run_id="run-1")

        self.assertTrue(record.run_dir.is_absolute())
        self.assertTrue(str(record.run_dir).endswith("runs/run-1"))

    def test_runtime_persists_running_agent_before_stage_completes(self) -> None:
        from growth_dev.team.models import AgentRun, AgentSpec, DomainSpec, TeamRunRecord
        from growth_dev.team.runtime import TeamRuntime

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "runs" / "run-1"
            runtime = TeamRuntime(
                team_spec=type(
                    "Team",
                    (),
                    {
                        "team_id": "team",
                        "agents": [AgentSpec(id="slow", outputs=["slow.md"])],
                        "gates": [],
                        "to_dict": lambda self: {"team_id": "team", "agents": [], "gates": []},
                        "gates_before": lambda self, agent_id: [],
                    },
                )(),
                domain_spec=DomainSpec(domain_id="demo"),
                runs_dir=root / "runs",
            )

            def slow_agent(agent, context):
                payload = TeamRunRecord.from_dict(json.loads((run_dir / "team_run_record.json").read_text(encoding="utf-8")))
                self.assertEqual(payload.agent_runs[-1].agent_id, "slow")
                self.assertEqual(payload.agent_runs[-1].status, "running")
                return AgentRun(agent_id="slow", status="completed", output_paths=[context.write_text("slow.md", "# Slow\n")], message="slow finished")

            with patch("growth_dev.team.runtime.run_deterministic_agent", side_effect=slow_agent):
                record = runtime.run("demo", run_id="run-1")

        self.assertEqual(record.status, "completed")
        self.assertEqual(len(record.agent_runs), 1)
        self.assertEqual(record.agent_runs[-1].status, "completed")

    def test_runtime_writes_ordered_events_jsonl(self) -> None:
        from growth_dev.team.runtime import TeamRuntime

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            team_spec, domain_spec = _load_specs(root)
            runtime = _new_runtime(team_spec, domain_spec, root / "runs")

            record = runtime.run("demo", run_id="run-1")

            events_path = root / "runs" / "run-1" / "events.jsonl"
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
            retrospective_exists = (root / "runs" / "run-1" / "retrospective.md").exists()
            learning_exists = (root / "runs" / "run-1" / "learning_summary.json").exists()

        self.assertEqual(record.status, "completed")
        self.assertEqual(events[0]["event"], "run_started")
        self.assertIn("agent_started", [event["event"] for event in events])
        self.assertIn("gate_checked", [event["event"] for event in events])
        self.assertEqual(events[-1]["event"], "run_completed")
        self.assertTrue(retrospective_exists)
        self.assertTrue(learning_exists)

    def test_runtime_writes_failed_gate_event_with_missing_artifacts(self) -> None:
        from growth_dev.team.models import AgentSpec, DomainSpec, GateSpec, TeamSpec
        from growth_dev.team.runtime import TeamRuntime

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            team = TeamSpec(
                team_id="team",
                agents=[AgentSpec(id="coder", outputs=["coding_prompt.md"])],
                gates=[GateSpec(id="before_coding", before_agent="coder", required_artifacts=["prd.md"])],
            )
            runtime = TeamRuntime(team_spec=team, domain_spec=DomainSpec(domain_id="demo"), runs_dir=root / "runs")

            record = runtime.run("demo", run_id="run-1")

            events_path = root / "runs" / "run-1" / "events.jsonl"
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
            gate_events = [event for event in events if event["event"] == "gate_checked"]
            retrospective_exists = (root / "runs" / "run-1" / "retrospective.md").exists()
            learning_exists = (root / "runs" / "run-1" / "learning_summary.json").exists()

        self.assertEqual(record.status, "failed")
        self.assertEqual(gate_events[0]["status"], "failed")
        self.assertEqual(gate_events[0]["missing_artifacts"], ["prd.md"])
        self.assertEqual(events[-1]["event"], "run_failed")
        self.assertTrue(retrospective_exists)
        self.assertTrue(learning_exists)

    def test_runtime_keeps_run_status_when_retrospective_generation_fails(self) -> None:
        from growth_dev.team.runtime import TeamRuntime

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            team_spec, domain_spec = _load_specs(root)
            runtime = _new_runtime(team_spec, domain_spec, root / "runs")

            with patch("growth_dev.team.runtime.generate_run_retrospective", side_effect=RuntimeError("retro failed")):
                record = runtime.run("demo", run_id="run-1")

            events_path = root / "runs" / "run-1" / "events.jsonl"
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(record.status, "completed")
        self.assertIn("retrospective_failed", [event["event"] for event in events])


if __name__ == "__main__":
    unittest.main()
