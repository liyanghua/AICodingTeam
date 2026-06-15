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

    def test_runtime_writes_task_workspace_artifacts(self) -> None:
        from growth_dev.team.models import AgentSpec, DomainSpec, TeamSpec
        from growth_dev.team.runtime import TeamRuntime

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = TeamRuntime(
                team=TeamSpec(team_id="team", agents=[AgentSpec(id="orchestrator", outputs=["task.yaml", "context.md"])]),
                domain=DomainSpec(domain_id="demo"),
                runs_dir=root / "runs",
            )

            record = runtime.run("demo", run_id="workspace-runtime-run")
            run_dir = root / "runs" / "workspace-runtime-run"
            workspace = json.loads((run_dir / "task_workspace.json").read_text(encoding="utf-8"))
            workspace_md_exists = (run_dir / "task_workspace.md").exists()
            journal_json_exists = (run_dir / "task_journal.jsonl").exists()
            journal_md_exists = (run_dir / "task_journal.md").exists()
            tool_context_exists = (run_dir / "tool_context" / "codex.md").exists()

        self.assertEqual(record.status, "completed")
        self.assertEqual(workspace["run_id"], "workspace-runtime-run")
        self.assertTrue(workspace_md_exists)
        self.assertTrue(journal_json_exists)
        self.assertTrue(journal_md_exists)
        self.assertTrue(tool_context_exists)

    def test_runtime_keeps_run_status_when_task_workspace_refresh_fails(self) -> None:
        from growth_dev.team.models import AgentSpec, DomainSpec, TeamSpec
        from growth_dev.team.runtime import TeamRuntime

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = TeamRuntime(
                team=TeamSpec(team_id="team", agents=[AgentSpec(id="orchestrator", outputs=["task.yaml", "context.md"])]),
                domain=DomainSpec(domain_id="demo"),
                runs_dir=root / "runs",
            )

            with patch("growth_dev.team.runtime.refresh_task_workspace", side_effect=RuntimeError("workspace failed")):
                record = runtime.run("demo", run_id="workspace-failure-run")

            events = [json.loads(line) for line in (root / "runs" / "workspace-failure-run" / "events.jsonl").read_text(encoding="utf-8").splitlines()]

        self.assertEqual(record.status, "completed")
        self.assertIn("task_workspace_failed", [event["event"] for event in events])

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

    def test_runtime_stops_before_coding_when_requirement_gate_has_blocking_question(self) -> None:
        from growth_dev.team.runtime import TeamRuntime

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            team_spec, domain_spec = _load_specs(root)
            runtime = TeamRuntime(team_spec=team_spec, domain_spec=domain_spec, runs_dir=root / "runs")

            record = runtime.run(
                "实现复杂 Dashboard 交互，但还有阻塞问题",
                inputs={"force_blocking_question": True},
                run_id="blocking-requirement-run",
            )

            run_dir = root / "runs" / "blocking-requirement-run"
            quality = json.loads((run_dir / "requirements" / "requirement_quality_report.json").read_text(encoding="utf-8"))
            events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            agent_ids = [agent.agent_id for agent in record.agent_runs]
            gate_statuses = {gate.gate_id: gate.status for gate in record.gate_results}

        self.assertEqual(record.status, "failed")
        self.assertEqual(agent_ids, ["orchestrator", "requirements"])
        self.assertNotIn("coder", agent_ids)
        self.assertEqual(quality["status"], "failed")
        self.assertIn("blocking_questions_present", quality["blockers"])
        self.assertEqual(gate_statuses["requirement_quality"], "failed")
        self.assertEqual(events[-1]["event"], "run_failed")
        self.assertEqual(events[-1]["reason"], "requirement_quality_gate_failed")

    def test_complex_task_writes_candidate_capability_boundary_and_tdd_plan(self) -> None:
        from growth_dev.team.models import DomainSpec
        from growth_dev.team.runtime import TeamRuntime

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            team_spec, _ = _load_specs(root)
            domain_spec = DomainSpec.from_dict(
                {
                    "domain_id": "xhs_mobile_collection",
                    "summary": "XHS collector domain",
                    "risk_rules": ["manual_login_only", "no_captcha_bypass"],
                    "evaluation_rules": ["keyword_only_search_does_not_use_image_search"],
                    "capabilities": {
                        "supported": [
                            {
                                "id": "image_then_keyword_collection",
                                "summary": "Excel/reference image flow can run image search then keyword search.",
                                "evidence": ["third_party/xhs_collector/README.md"],
                            }
                        ],
                        "unsupported": [
                            {
                                "id": "workbench_keyword_ui",
                                "summary": "Workbench UI does not expose keyword-only collection yet.",
                            }
                        ],
                    },
                }
            )
            runtime = TeamRuntime(
                team_spec=team_spec,
                domain_spec=domain_spec,
                runs_dir=root / "runs",
                planning_mode="llm_assisted",
                requirements_model="gpt-5.5",
            )

            record = runtime.run(
                "给 xhs_collector 增加纯关键词采集能力，不走图搜，过滤视频，下载 TOP N 图文笔记图片。",
                inputs={
                    "allowed_paths": ["third_party/xhs_collector/", "tests/test_xhs_collector.py"],
                    "verification_commands": ["python3 -m unittest tests.test_xhs_collector -v"],
                },
                run_id="xhs-keyword-plan",
            )

            run_dir = root / "runs" / "xhs-keyword-plan"
            candidate = json.loads((run_dir / "requirements" / "requirement_understanding.candidate.json").read_text(encoding="utf-8"))
            boundary = json.loads((run_dir / "requirements" / "capability_boundary.json").read_text(encoding="utf-8"))
            tdd_plan = json.loads((run_dir / "planning" / "tdd_plan.json").read_text(encoding="utf-8"))
            requirement_quality = json.loads((run_dir / "requirements" / "requirement_quality_report.json").read_text(encoding="utf-8"))
            planning_quality = json.loads((run_dir / "planning" / "planning_quality_report.json").read_text(encoding="utf-8"))
            prd_draft = (run_dir / "requirements" / "prd.draft.md").read_text(encoding="utf-8")
            user_stories_draft = (run_dir / "requirements" / "user_stories.draft.md").read_text(encoding="utf-8")
            prd_red_team = (run_dir / "requirements" / "prd_red_team.md").read_text(encoding="utf-8")
            test_scenarios_draft = (run_dir / "planning" / "test_scenarios.draft.md").read_text(encoding="utf-8")
            boundary_md_exists = (run_dir / "requirements" / "capability_boundary.md").exists()
            tdd_md_exists = (run_dir / "planning" / "tdd_plan.md").exists()

        self.assertEqual(record.status, "completed")
        self.assertEqual(candidate["model"], "gpt-5.5")
        self.assertIn("业务目标", candidate["clarification_angles"])
        self.assertIn("PM Skills-inspired", candidate["method_source"])
        self.assertIn("User Stories", prd_draft)
        self.assertIn("US-001", user_stories_draft)
        self.assertIn("Load-Bearing Assumptions", prd_red_team)
        self.assertIn("SCN-001", test_scenarios_draft)
        self.assertIn("image_then_keyword_collection", {item["id"] for item in boundary["existing_capabilities"]})
        self.assertIn("workbench_keyword_ui", {item["id"] for item in boundary["unsupported_capabilities"]})
        self.assertEqual(boundary["change_type"], "extend_existing_capability")
        self.assertTrue(boundary_md_exists)
        self.assertTrue(tdd_md_exists)
        self.assertTrue(tdd_plan["test_cases"])
        self.assertTrue(all(item["acceptance_criteria_ids"] for item in tdd_plan["test_cases"]))
        tdd_text = json.dumps(tdd_plan, ensure_ascii=False)
        self.assertIn("run-keyword", tdd_text)
        self.assertIn("search_mode=keyword_only", tdd_text)
        self.assertIn("不走图搜", tdd_text)
        self.assertIn("skip_video_note_card", tdd_text)
        quality_check_ids = [item["id"] for item in requirement_quality["checks"]]
        self.assertIn("capability_boundary_ready", quality_check_ids)
        self.assertIn("user_stories_are_structured", quality_check_ids)
        self.assertIn("prd_separates_facts_assumptions_questions", quality_check_ids)
        self.assertIn("test_scenarios_map_to_acceptance", quality_check_ids)
        self.assertIn("red_team_risks_addressed", quality_check_ids)
        self.assertIn("tdd_plan_ready", planning_quality["checks"])

    def test_complex_task_uses_default_capability_boundary_for_generic_domain(self) -> None:
        from growth_dev.team.runtime import TeamRuntime

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            team_spec, domain_spec = _load_specs(root)
            runtime = TeamRuntime(
                team_spec=team_spec,
                domain_spec=domain_spec,
                runs_dir=root / "runs",
            )

            record = runtime.run(
                "监控目标网页里关键词是否发生变化",
                inputs={"verification_commands": ["python3 -m unittest discover -s tests -v"]},
                run_id="generic-capability-run",
            )

            run_dir = root / "runs" / "generic-capability-run"
            boundary = json.loads((run_dir / "requirements" / "capability_boundary.json").read_text(encoding="utf-8"))
            quality = json.loads((run_dir / "requirements" / "requirement_quality_report.json").read_text(encoding="utf-8"))

        self.assertEqual(record.status, "completed")
        self.assertEqual(boundary["existing_capabilities"][0]["id"], f"{domain_spec.domain_id}_baseline")
        self.assertEqual(boundary["existing_capabilities"][0]["source"], "domain_pack_default")
        self.assertIn("domain.yaml", boundary["source_artifacts"])
        self.assertNotIn("capabilities.yaml", boundary["source_artifacts"])
        self.assertEqual(quality["status"], "passed")

    def test_default_before_coding_gate_requires_capability_boundary_and_tdd_plan(self) -> None:
        from growth_dev.team.runtime import check_gate, default_team_spec

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            for relative in (
                "prd.md",
                "tech_spec.md",
                "ui_spec.md",
                "eval.md",
                "acceptance_criteria.md",
                "context_pack.md",
                "planning/acceptance_coverage_matrix.json",
                "planning/planning_quality_report.json",
            ):
                path = run_dir / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("ok\n", encoding="utf-8")

            gate = default_team_spec().gate_by_id("before_coding")
            result = check_gate(gate, run_dir)

        self.assertEqual(result.status, "failed")
        self.assertIn("requirements/capability_boundary.json", result.missing_artifacts)
        self.assertIn("planning/tdd_plan.json", result.missing_artifacts)

    def test_complex_task_artifacts_redact_secrets_from_brief_and_inputs(self) -> None:
        from growth_dev.team.runtime import TeamRuntime

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            team_spec, domain_spec = _load_specs(root)
            runtime = TeamRuntime(
                team_spec=team_spec,
                domain_spec=domain_spec,
                runs_dir=root / "runs",
                planning_mode="llm_assisted",
                requirements_model="gpt-5.3",
            )

            record = runtime.run(
                "优化 Dashboard 流程 api_key=brief-secret sk-briefsecret123",
                inputs={
                    "api_key": "input-secret",
                    "token": "input-token",
                    "verification_commands": ["echo token=command-secret"],
                    "blocking_questions": ["是否允许使用 password=question-secret？"],
                },
                run_id="redacted-complex-run",
            )

            run_dir = root / "runs" / "redacted-complex-run"
            artifact_text = "\n".join(
                [
                    (run_dir / "requirements" / "brief_analysis.json").read_text(encoding="utf-8"),
                    (run_dir / "requirements" / "clarification.md").read_text(encoding="utf-8"),
                    (run_dir / "requirements" / "open_questions.md").read_text(encoding="utf-8"),
                    (run_dir / "acceptance_criteria.md").read_text(encoding="utf-8"),
                    (run_dir / "context_pack.md").read_text(encoding="utf-8"),
                    (run_dir / "planning" / "acceptance_coverage_matrix.json").read_text(encoding="utf-8"),
                    (run_dir / "slices" / "slice-001.yaml").read_text(encoding="utf-8"),
                ]
            )

        self.assertEqual(record.status, "failed")
        self.assertNotIn("brief-secret", artifact_text)
        self.assertNotIn("sk-briefsecret123", artifact_text)
        self.assertNotIn("input-secret", artifact_text)
        self.assertNotIn("input-token", artifact_text)
        self.assertNotIn("command-secret", artifact_text)
        self.assertNotIn("question-secret", artifact_text)
        self.assertIn("<redacted", artifact_text)

    def test_runtime_writes_ordered_events_jsonl(self) -> None:
        from growth_dev.team.runtime import TeamRuntime

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            team_spec, domain_spec = _load_specs(root)
            runtime = _new_runtime(team_spec, domain_spec, root / "runs")
            historical_dir = root / "runs" / "historical-run"
            historical_dir.mkdir(parents=True)
            (historical_dir / "learning_summary.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": "historical-run",
                        "domain_id": "xhs_browser_benchmark",
                        "status": "completed",
                        "task_type": "dashboard_ui_change",
                        "outcome": "accepted_and_verified",
                        "quality_findings": {"summary": "历史任务贴合 Dashboard 需求。"},
                        "implementation_findings": {"changed_files": ["dashboard/app.js"], "tests_run": []},
                        "review_test_findings": {"review_summary": "通过", "test_summary": "通过"},
                        "failure_modes": [],
                        "recommended_skills": ["context_engineering"],
                        "reusable_context": ["dashboard/app.js"],
                        "avoid_context": ["raw stdout/stderr"],
                        "next_time_checklist": ["复用历史 Dashboard 验收经验。"],
                        "source_artifacts": ["learning_summary.json"],
                    }
                ),
                encoding="utf-8",
            )

            record = runtime.run("demo", run_id="run-1")

            events_path = root / "runs" / "run-1" / "events.jsonl"
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
            retrospective_exists = (root / "runs" / "run-1" / "retrospective.md").exists()
            learning_exists = (root / "runs" / "run-1" / "learning_summary.json").exists()
            recall_exists = (root / "runs" / "run-1" / "memory_recall.json").exists()
            recall = json.loads((root / "runs" / "run-1" / "memory_recall.json").read_text(encoding="utf-8"))

        self.assertEqual(record.status, "completed")
        self.assertEqual(events[0]["event"], "run_started")
        self.assertEqual(events[1]["event"], "memory_recall_generated")
        self.assertIn("agent_started", [event["event"] for event in events])
        self.assertIn("gate_checked", [event["event"] for event in events])
        self.assertEqual(events[-1]["event"], "run_completed")
        self.assertTrue(recall_exists)
        self.assertIn("memory_recall.json", record.output_paths)
        self.assertEqual(record.artifacts["memory_recall.json"], "memory_recall.json")
        self.assertTrue(any(match["run_id"] == "historical-run" for match in recall["matches"]))
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

    def test_runtime_keeps_run_status_when_memory_recall_generation_fails(self) -> None:
        from growth_dev.team.runtime import TeamRuntime

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            team_spec, domain_spec = _load_specs(root)
            runtime = _new_runtime(team_spec, domain_spec, root / "runs")

            with patch("growth_dev.team.runtime.generate_memory_recall", side_effect=RuntimeError("recall failed")):
                record = runtime.run("demo", run_id="run-1")

            events_path = root / "runs" / "run-1" / "events.jsonl"
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(record.status, "completed")
        self.assertIn("memory_recall_failed", [event["event"] for event in events])


if __name__ == "__main__":
    unittest.main()
