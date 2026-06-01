from __future__ import annotations

import json
import subprocess
import tempfile
import time
import unittest
from http import HTTPStatus
from pathlib import Path
from unittest import mock

from tests.test_team_models import TEAM_YAML


WEB_MONITORING_DOMAIN_YAML = """\
domain_id: web_monitoring
input_schema:
  target_url: string
  keyword: string
output_schema: WebMonitoringResult
risk_rules:
  - no_private_data_collection
"""


class DashboardTests(unittest.TestCase):
    def _business_view_model(self, run: dict[str, object]) -> dict[str, object]:
        root = Path(__file__).resolve().parents[1]
        i18n_path = root / "dashboard" / "i18n" / "zh-CN.json"
        module_path = root / "dashboard" / "business_view.js"
        script = f"""
const fs = require('fs');
const {{ toBusinessViewModel }} = require({json.dumps(str(module_path))});
const i18n = JSON.parse(fs.readFileSync({json.dumps(str(i18n_path))}, 'utf8'));
const vm = toBusinessViewModel({json.dumps(run)}, i18n);
console.log(JSON.stringify(vm));
"""
        completed = subprocess.run(["node", "-e", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return json.loads(completed.stdout)

    def _write_completed_run(self, runs_dir: Path, run_id: str = "dashboard-run-1") -> Path:
        run_dir = runs_dir / run_id
        codex_dir = run_dir / "codex"
        codex_dir.mkdir(parents=True)
        record = {
            "run_id": run_id,
            "team_id": "ai_native_engineering_team",
            "domain_id": "web_monitoring",
            "brief": "给 dashboard 增加可视化闭环",
            "status": "completed",
            "run_dir": str(run_dir),
            "started_at": "2026-05-23T00:00:00+00:00",
            "finished_at": "2026-05-23T00:01:00+00:00",
            "agent_runs": [
                {"agent_id": "orchestrator", "status": "completed", "started_at": "a", "finished_at": "b", "risk_events": [], "output_paths": ["task.yaml", "context.md"], "message": "created", "metadata": {}},
                {"agent_id": "product", "status": "completed", "started_at": "b", "finished_at": "c", "risk_events": [], "output_paths": ["prd.md"], "message": "created", "metadata": {}},
                {"agent_id": "architect", "status": "completed", "started_at": "c", "finished_at": "d", "risk_events": [], "output_paths": ["tech_spec.md"], "message": "created", "metadata": {}},
                {"agent_id": "ux", "status": "completed", "started_at": "d", "finished_at": "e", "risk_events": [], "output_paths": ["ui_spec.md"], "message": "created", "metadata": {}},
                {"agent_id": "qa", "status": "completed", "started_at": "e", "finished_at": "f", "risk_events": [], "output_paths": ["eval.md"], "message": "created", "metadata": {}},
                {"agent_id": "coder", "status": "completed", "started_at": "f", "finished_at": "g", "risk_events": [], "output_paths": ["coding_prompt.md", "codex/diff.patch"], "message": "coded", "metadata": {}},
                {"agent_id": "reviewer", "status": "completed", "started_at": "g", "finished_at": "h", "risk_events": [], "output_paths": ["review_report.md"], "message": "reviewed", "metadata": {}},
                {"agent_id": "verifier", "status": "completed", "started_at": "h", "finished_at": "i", "risk_events": [], "output_paths": ["test_report.md"], "message": "tested", "metadata": {}},
                {"agent_id": "publisher", "status": "completed", "started_at": "i", "finished_at": "j", "risk_events": [], "output_paths": ["final_report.md"], "message": "published", "metadata": {}},
            ],
            "gate_results": [
                {"gate_id": "before_coding", "status": "passed", "required_artifacts": ["prd.md", "tech_spec.md", "ui_spec.md", "eval.md"], "missing_artifacts": [], "checked_at": "now", "before_agent": "coder"},
                {"gate_id": "before_publish", "status": "passed", "required_artifacts": ["review_report.md", "test_report.md"], "missing_artifacts": [], "checked_at": "now", "before_agent": "publisher"},
            ],
            "artifacts": {
                "prd.md": "prd.md",
                "tech_spec.md": "tech_spec.md",
                "ui_spec.md": "ui_spec.md",
                "eval.md": "eval.md",
                "coding_prompt.md": "coding_prompt.md",
                "diff.patch": "codex/diff.patch",
                "review_report.md": "review_report.md",
                "test_report.md": "test_report.md",
                "final_report.md": "final_report.md",
            },
            "risk_events": [],
            "executor": "codex",
            "executor_config": {
                "provider": {
                    "name": "aicodemirror",
                    "base_url": "https://example.invalid",
                    "env_key": "AICODEMIRROR_KEY",
                    "secret_configured": True,
                    "api_key": "sk-should-not-leak",
                }
            },
        }
        (run_dir / "team_run_record.json").write_text(json.dumps(record), encoding="utf-8")
        (run_dir / "process.json").write_text(
            json.dumps({"run_id": run_id, "pid": 12345, "status": "running", "command": ["python", "-m", "growth_dev.cli", "--env-file", "<env-file>"]}),
            encoding="utf-8",
        )
        (run_dir / "events.jsonl").write_text(
            "\n".join(
                [
                    json.dumps({"event": "run_started", "run_id": run_id}),
                    json.dumps({"event": "agent_started", "agent_id": "coder"}),
                    json.dumps({"event": "gate_checked", "gate_id": "before_coding", "status": "passed"}),
                    json.dumps({"event": "run_completed", "run_id": run_id}),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        (run_dir / "prd.md").write_text("# PRD\n", encoding="utf-8")
        (run_dir / "tech_spec.md").write_text("# Tech Spec\n", encoding="utf-8")
        (run_dir / "ui_spec.md").write_text("# UI Spec\n", encoding="utf-8")
        (run_dir / "eval.md").write_text("# Eval\n", encoding="utf-8")
        (run_dir / "final_report.md").write_text("# Final Report\n", encoding="utf-8")
        requirements_dir = run_dir / "requirements"
        planning_dir = run_dir / "planning"
        slices_dir = run_dir / "slices"
        requirements_dir.mkdir(parents=True, exist_ok=True)
        planning_dir.mkdir(parents=True, exist_ok=True)
        slices_dir.mkdir(parents=True, exist_ok=True)
        (requirements_dir / "brief_analysis.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "domain_id": "web_monitoring",
                    "brief": "给 dashboard 增加可视化闭环",
                    "planning_mode": "auto",
                    "requirements_model": "gpt-5.3",
                    "complexity": "complex",
                    "llm_draft_requested": True,
                    "blocking_questions": [],
                    "assumptions": ["使用 web_monitoring 作为任务边界。"],
                    "recommended_skills": ["spec_driven_development", "context_engineering", "planning_and_task_breakdown"],
                }
            ),
            encoding="utf-8",
        )
        (requirements_dir / "requirement_quality_report.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "passed",
                    "summary": "Requirement understanding is ready for planning.",
                    "blockers": [],
                    "warnings": ["llm_draft_channel_used_but_not_promoted"],
                    "checks": [{"id": "stable_acceptance_ids", "status": "passed"}],
                }
            ),
            encoding="utf-8",
        )
        (requirements_dir / "clarification.md").write_text("# Requirement Clarification\n", encoding="utf-8")
        (requirements_dir / "acceptance_criteria.draft.md").write_text("# Draft Acceptance Criteria\n", encoding="utf-8")
        (requirements_dir / "open_questions.md").write_text("# Open Questions\n", encoding="utf-8")
        (requirements_dir / "assumptions.md").write_text("# Assumptions\n", encoding="utf-8")
        (run_dir / "acceptance_criteria.md").write_text("# Acceptance Criteria\n\n- `AC-001` 覆盖 Dashboard 可视化闭环。\n", encoding="utf-8")
        (run_dir / "context_pack.md").write_text("# Context Pack\n", encoding="utf-8")
        (planning_dir / "acceptance_coverage_matrix.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "acceptance_criteria": [
                        {
                            "id": "AC-001",
                            "description": "覆盖 Dashboard 可视化闭环。",
                            "covering_slice_ids": ["slice-001"],
                            "status": "planned",
                        }
                    ],
                    "slices": [
                        {
                            "id": "slice-001",
                            "title": "展示复杂任务闭环",
                            "acceptance_criteria_ids": ["AC-001"],
                            "verification_commands": ["python3 -m unittest tests.test_dashboard -v"],
                            "status": "planned",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (planning_dir / "acceptance_coverage_matrix.md").write_text("# Acceptance Coverage Matrix\n", encoding="utf-8")
        (planning_dir / "planning_quality_report.json").write_text(
            json.dumps({"schema_version": 1, "status": "passed", "summary": "Planning is ready for implementation.", "blockers": []}),
            encoding="utf-8",
        )
        (slices_dir / "slice-001.yaml").write_text(
            "slice_id: slice-001\ntitle: 展示复杂任务闭环\nacceptance_criteria_ids:\n  - AC-001\nverification_commands:\n  - python3 -m unittest tests.test_dashboard -v\n",
            encoding="utf-8",
        )
        (run_dir / "memory_recall.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "query": "给 dashboard 增加可视化闭环",
                    "run_id": run_id,
                    "domain_id": "web_monitoring",
                    "generated_at": "2026-05-23T00:00:05+00:00",
                    "matches": [
                        {
                            "run_id": "historical-dashboard-run",
                            "domain_id": "web_monitoring",
                            "task_type": "dashboard_ui_change",
                            "status": "completed",
                            "outcome": "accepted_and_verified",
                            "score": 0.91,
                            "reasons": ["same_domain", "matched_reusable_context"],
                            "recommended_skills": ["context_engineering"],
                            "reusable_context": ["dashboard/index.html"],
                            "avoid_context": ["raw stdout/stderr"],
                            "failure_modes": [],
                            "source_artifacts": ["learning_summary.json"],
                        }
                    ],
                    "recommended_skills": [
                        {
                            "id": "context_engineering",
                            "confidence": 0.91,
                            "source_run_ids": ["historical-dashboard-run"],
                            "why": "历史相似任务需要收窄 Dashboard 上下文。",
                        }
                    ],
                    "context_strategy": {
                        "reuse": ["dashboard/index.html"],
                        "avoid": ["raw stdout/stderr"],
                        "checklist": ["复用历史 Dashboard 验收经验。"],
                    },
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "memory_recall.md").write_text("# Historical Task Recall\n", encoding="utf-8")
        (codex_dir / "implementation_trace.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "stage": "coder",
                    "status": "completed",
                    "current_step": "finalize_result",
                    "updated_at": "2026-05-23T00:00:30+00:00",
                    "inputs": [{"title": "PRD", "path": "prd.md", "scope": "run", "exists": True}],
                    "steps": [
                        {"id": "prepare_context", "title": "准备上下文", "status": "completed", "summary": "已生成上下文。"},
                        {"id": "codex_running", "title": "启动 AI coding", "status": "completed", "summary": "AI coding 已完成。"},
                    ],
                    "evidence": {
                        "changed_files": ["dashboard/app.js"],
                        "tests_run": ["python3 -m unittest tests.test_dashboard -v"],
                        "verification_commands": ["python3 -m unittest tests.test_dashboard -v"],
                        "diff_path": "codex/diff.patch",
                        "exit_code": 0,
                    },
                    "risk_events": [],
                    "blockers": [],
                    "next_action": "review",
                }
            ),
            encoding="utf-8",
        )
        (codex_dir / "slice_loop_state.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "stage": "coder",
                    "enabled": True,
                    "status": "completed",
                    "execution_strategy": "single_codex_pass_over_planned_slices_v1",
                    "completed_slice_ids": ["slice-001"],
                    "pending_slice_ids": [],
                    "slices": [
                        {
                            "id": "slice-001",
                            "title": "展示复杂任务闭环",
                            "status": "completed",
                            "acceptance_criteria_ids": ["AC-001"],
                            "verification_commands": ["python3 -m unittest tests.test_dashboard -v"],
                        }
                    ],
                    "blockers": [],
                    "risk_events": [],
                    "next_action": "Ready for review.",
                }
            ),
            encoding="utf-8",
        )
        (codex_dir / "slices" / "slice-001").mkdir(parents=True, exist_ok=True)
        (codex_dir / "slices" / "slice-001" / "slice_trace.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "slice_id": "slice-001",
                    "status": "completed",
                    "acceptance_criteria_ids": ["AC-001"],
                    "evidence": {"changed_files": ["dashboard/app.js"], "tests_run": ["python3 -m unittest tests.test_dashboard -v"]},
                    "blockers": [],
                    "risk_events": [],
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "implementation_completion_gate.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "status": "passed",
                    "summary": "Implementation is ready for review.",
                    "checks": [{"id": "all_slices_completed", "status": "passed", "reason": "Check passed.", "evidence": ["slice-001"]}],
                    "evidence": {
                        "completed_slice_ids": ["slice-001"],
                        "covered_acceptance_criteria_ids": ["AC-001"],
                        "changed_files": ["dashboard/app.js"],
                        "tests_run": ["python3 -m unittest tests.test_dashboard -v"],
                    },
                    "blockers": [],
                    "next_action": "Proceed to review and verifier.",
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "implementation_completion_gate.md").write_text("# Implementation Completion Gate\n", encoding="utf-8")
        (codex_dir / "stdout.jsonl").write_text("coding started\ncoding finished\n", encoding="utf-8")
        (codex_dir / "stderr.log").write_text("provider warning\n", encoding="utf-8")
        (codex_dir / "diff.patch").write_text(
            "\n".join(
                [
                    "diff --git a/dashboard/app.js b/dashboard/app.js",
                    "index 1111111..2222222 100644",
                    "--- a/dashboard/app.js",
                    "+++ b/dashboard/app.js",
                    "@@ -1,3 +1,4 @@",
                    " const state = {};",
                    "-oldLine();",
                    "+newLine();",
                    "+extraLine();",
                    " keepLine();",
                    "diff --git a/tests/test_dashboard.py b/tests/test_dashboard.py",
                    "new file mode 100644",
                    "index 0000000..3333333",
                    "--- /dev/null",
                    "+++ b/tests/test_dashboard.py",
                    "@@ -0,0 +1,2 @@",
                    "+def test_diff_view():",
                    "+    assert True",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        (run_dir / "release_readiness.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "generated_at": "2026-05-23T00:02:00+00:00",
                    "release_decision": "ready_for_pr_ci",
                    "summary": "采纳验收、Review/Test 和变更边界均通过，值得进入 PR/CI。",
                    "gates": [{"id": "acceptance_tests", "status": "passed", "reason": "全量测试通过。", "evidence": ["tests.exit_code=0"]}],
                    "evidence": {"changed_files": ["dashboard/app.js"], "tests_run": ["python3 -m unittest discover -s tests -v"]},
                    "pr_draft": {"title": "web_monitoring: Dashboard 状态修复", "body": "## Why This Should Enter PR/CI\n\n本地验收通过。"},
                    "blockers": [],
                    "warnings": [],
                    "next_actions": ["python3 -m unittest discover -s tests -v"],
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "release_readiness.md").write_text("# Release Readiness\n", encoding="utf-8")
        (run_dir / "pr_draft.md").write_text("# PR Title\n\nweb_monitoring: Dashboard 状态修复\n", encoding="utf-8")
        (run_dir / "github_pr.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "status": "created",
                    "generated_at": "2026-05-23T00:03:00+00:00",
                    "pr": {
                        "number": 42,
                        "url": "https://github.com/example/project/pull/42",
                        "title": "web_monitoring: Dashboard 状态修复",
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
        (run_dir / "ci_status.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "status": "passed",
                    "generated_at": "2026-05-23T00:04:00+00:00",
                    "pr_url": "https://github.com/example/project/pull/42",
                    "checks": [{"name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS", "url": ""}],
                    "summary": "1 个 CI check 已通过。",
                    "warnings": [],
                    "blockers": [],
                    "next_action": "可以进行人工 Review。",
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "github_pr.md").write_text("# GitHub Draft PR\n", encoding="utf-8")
        (run_dir / "ci_status.md").write_text("# CI Status\n", encoding="utf-8")
        (run_dir / "staging_readiness.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "generated_at": "2026-05-23T00:05:00+00:00",
                    "staging_decision": "ready_for_staging",
                    "summary": "PR 和 CI 已通过，可以进入 staging。",
                    "gates": [{"id": "ci_passed", "status": "passed", "reason": "CI passed.", "evidence": ["ci.status=passed"]}],
                    "evidence": {
                        "release_decision": "ready_for_pr_ci",
                        "pr_url": "https://github.com/example/project/pull/42",
                        "ci_status": "passed",
                        "ci_summary": "1 个 CI check 已通过。",
                        "checks": [{"name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS", "url": ""}],
                        "acceptance_status": "completed",
                        "changed_files": ["dashboard/app.js"],
                    },
                    "blockers": [],
                    "warnings": [],
                    "next_actions": ["人工确认 staging 环境。"],
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "staging_readiness.md").write_text("# Staging Readiness\n", encoding="utf-8")
        (run_dir / "staging_rehearsal.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "status": "completed",
                    "generated_at": "2026-05-23T00:06:00+00:00",
                    "summary": "Staging 本地演练已完成，全量测试通过。",
                    "staging_readiness_decision": "ready_for_staging",
                    "steps": [
                        {"id": "readiness", "status": "passed", "reason": "ready_for_staging"},
                        {
                            "id": "full_tests",
                            "status": "completed",
                            "command": "python3 -m unittest discover -s tests -v",
                            "exit_code": 0,
                        },
                    ],
                    "evidence": {
                        "changed_files": ["dashboard/app.js"],
                        "git_status": [" M dashboard/app.js"],
                        "tests_stdout_log": "staging_rehearsal/tests_stdout.log",
                        "tests_stderr_log": "staging_rehearsal/tests_stderr.log",
                    },
                    "blockers": [],
                    "warnings": [],
                    "next_actions": ["可以进入真实 staging 前人工审批。"],
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "staging_rehearsal.md").write_text("# Staging Rehearsal\n", encoding="utf-8")
        return run_dir

    def test_dashboard_state_serializes_run_without_secrets(self) -> None:
        from growth_dev.team.dashboard import build_dashboard_state

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            self._write_completed_run(runs_dir)

            state = build_dashboard_state("dashboard-run-1", runs_dir=runs_dir, repo_root=root)
            payload = json.dumps(state, ensure_ascii=False)

        stage_ids = [stage["id"] for stage in state["stages"]]
        gate_ids = [gate["id"] for gate in state["gates"]]
        self.assertEqual(state["run_id"], "dashboard-run-1")
        self.assertIn("orchestrator", stage_ids)
        self.assertIn("requirements", stage_ids)
        self.assertIn("human_approval", stage_ids)
        self.assertIn("before_coding", gate_ids)
        self.assertIn("ci_gate", gate_ids)
        self.assertIn("coding finished", "\n".join(state["logs"]))
        self.assertIn("health_summary", state)
        self.assertIn("quality_report", state)
        self.assertEqual(state["implementation_trace"]["status"], "completed")
        self.assertEqual(state["memory_recall"]["matches"][0]["run_id"], "historical-dashboard-run")
        self.assertEqual(state["release_readiness"]["release_decision"], "ready_for_pr_ci")
        self.assertEqual(state["github_pr"]["status"], "created")
        self.assertEqual(state["ci_status"]["status"], "passed")
        self.assertEqual(state["staging_readiness"]["staging_decision"], "ready_for_staging")
        self.assertEqual(state["staging_rehearsal"]["status"], "completed")
        self.assertTrue(any(item["path"] == "codex/implementation_trace.json" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "requirements/requirement_quality_report.json" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "memory_recall.md" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "memory_recall.json" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "retrospective.md" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "learning_summary.json" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "release_readiness.md" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "release_readiness.json" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "pr_draft.md" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "github_pr.md" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "github_pr.json" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "ci_status.md" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "ci_status.json" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "staging_readiness.md" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "staging_readiness.json" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "staging_rehearsal.md" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "staging_rehearsal.json" for item in state["artifacts"]))
        self.assertIn(state["health_summary"]["status"], {"completed_ready", "completed_with_warnings"})
        self.assertTrue(state["quality_report"]["checks"])
        self.assertEqual(state["diff_summary"]["files_changed"], 2)
        self.assertEqual(state["diff_summary"]["additions"], 4)
        self.assertEqual(state["diff_summary"]["deletions"], 1)
        self.assertEqual(state["diff_summary"]["files"][0]["path"], "dashboard/app.js")
        self.assertEqual(state["diff_summary"]["files"][0]["status"], "modified")
        self.assertEqual(state["diff_summary"]["files"][0]["additions"], 2)
        self.assertEqual(state["diff_summary"]["files"][0]["deletions"], 1)
        self.assertEqual(state["diff_summary"]["files"][1]["status"], "added")
        self.assertEqual(state["apply_gate"]["status"], "passed")
        self.assertNotIn("sk-should-not-leak", payload)
        self.assertNotIn(".env", payload)

    def test_dashboard_acceptance_runner_records_successful_apply_and_tests(self) -> None:
        from growth_dev.team.dashboard import run_dashboard_acceptance_once

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            self._write_completed_run(runs_dir)
            calls: list[list[str]] = []

            def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                calls.append(command)
                if command[:5] == ["python3", "-m", "growth_dev.cli", "team", "apply"]:
                    return subprocess.CompletedProcess(command, 0, "applied from .env with sk-should-not-leak\n", "")
                return subprocess.CompletedProcess(command, 0, "Ran 23 tests\nOK\n", "checked .env and sk-should-not-leak\n")

            result = run_dashboard_acceptance_once("dashboard-run-1", runs_dir=runs_dir, repo_root=root, command_runner=fake_run)
            payload = json.dumps(result, ensure_ascii=False)

            self.assertEqual(result["status"], "completed")
            self.assertTrue(result["applied"])
            self.assertEqual(result["steps"][0]["id"], "apply")
            self.assertEqual(result["steps"][0]["exit_code"], 0)
            self.assertEqual(result["steps"][1]["id"], "tests")
            self.assertEqual(result["steps"][1]["exit_code"], 0)
            self.assertIn("已采纳且测试通过", result["conclusion"])
            self.assertEqual(calls[0][:5], ["python3", "-m", "growth_dev.cli", "team", "apply"])
            self.assertEqual(calls[1], ["python3", "-m", "unittest", "discover", "-s", "tests", "-v"])
            self.assertNotIn(".env", payload)
            self.assertNotIn("sk-should-not-leak", payload)
            status_path = runs_dir / "dashboard-run-1" / "acceptance" / "status.json"
            self.assertTrue(status_path.exists())
            apply_log = (runs_dir / "dashboard-run-1" / "acceptance" / "apply_stdout.log").read_text(encoding="utf-8")
            tests_log = (runs_dir / "dashboard-run-1" / "acceptance" / "tests_stderr.log").read_text(encoding="utf-8")
            self.assertNotIn(".env", apply_log)
            self.assertNotIn("sk-should-not-leak", apply_log)
            self.assertNotIn(".env", tests_log)
            self.assertNotIn("sk-should-not-leak", tests_log)

    def test_dashboard_acceptance_runner_keeps_applied_changes_when_tests_fail(self) -> None:
        from growth_dev.team.dashboard import run_dashboard_acceptance_once

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            self._write_completed_run(runs_dir)

            def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                if command[:5] == ["python3", "-m", "growth_dev.cli", "team", "apply"]:
                    return subprocess.CompletedProcess(command, 0, "applied\n", "")
                return subprocess.CompletedProcess(command, 1, "FAILED tests\n", "failure detail\n")

            result = run_dashboard_acceptance_once("dashboard-run-1", runs_dir=runs_dir, repo_root=root, command_runner=fake_run)

        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["applied"])
        self.assertEqual(result["steps"][1]["exit_code"], 1)
        self.assertIn("已采纳但测试失败", result["conclusion"])
        self.assertIn("不自动回滚", result["next_action"])

    def test_dashboard_acceptance_runner_stops_when_apply_fails(self) -> None:
        from growth_dev.team.dashboard import run_dashboard_acceptance_once

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            self._write_completed_run(runs_dir)
            calls: list[list[str]] = []

            def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                calls.append(command)
                return subprocess.CompletedProcess(command, 1, "", "git apply failed\n")

            result = run_dashboard_acceptance_once("dashboard-run-1", runs_dir=runs_dir, repo_root=root, command_runner=fake_run)

        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["applied"])
        self.assertEqual(result["current_step"], "apply")
        self.assertEqual(len(calls), 1)
        self.assertIn("采纳失败", result["conclusion"])

    def test_dashboard_acceptance_post_requires_passed_apply_gate(self) -> None:
        from growth_dev.team.dashboard import start_dashboard_acceptance

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = self._write_completed_run(runs_dir)
            record = json.loads((run_dir / "team_run_record.json").read_text(encoding="utf-8"))
            record["status"] = "failed"
            (run_dir / "team_run_record.json").write_text(json.dumps(record), encoding="utf-8")

            with self.assertRaises(ValueError):
                start_dashboard_acceptance("dashboard-run-1", runs_dir=runs_dir, repo_root=root)

        self.assertFalse((runs_dir / "dashboard-run-1" / "acceptance" / "status.json").exists())

    def test_dashboard_pr_endpoints_delegate_to_github_pr_layer(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, create_dashboard_handler

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            self._write_completed_run(runs_dir)
            handler = create_dashboard_handler(DashboardConfig(runs_dir=runs_dir, repo_root=root, dashboard_dir=Path("dashboard")))

            with mock.patch("growth_dev.team.dashboard.create_draft_pr") as create_mock:
                create_mock.return_value = {"status": "created"}
                request = handler.__new__(handler)
                request.path = "/api/runs/dashboard-run-1/pr/draft"
                request._send_json = mock.Mock()
                request.do_POST()
                draft_payload = request._send_json.call_args.args[0]

            with mock.patch("growth_dev.team.dashboard.refresh_ci_status") as status_mock:
                status_mock.return_value = {"status": "passed"}
                request = handler.__new__(handler)
                request.path = "/api/runs/dashboard-run-1/pr/status"
                request._send_json = mock.Mock()
                request.do_POST()
                status_payload = request._send_json.call_args.args[0]

            with mock.patch("growth_dev.team.dashboard.generate_staging_readiness") as staging_mock:
                staging_mock.return_value = {"staging_decision": "ready_for_staging"}
                request = handler.__new__(handler)
                request.path = "/api/runs/dashboard-run-1/staging-readiness"
                request._send_json = mock.Mock()
                request.do_POST()
                staging_payload = request._send_json.call_args.args[0]

            with mock.patch("growth_dev.team.dashboard.run_staging_rehearsal") as rehearsal_mock:
                rehearsal_mock.return_value = {"status": "completed"}
                request = handler.__new__(handler)
                request.path = "/api/runs/dashboard-run-1/staging-rehearsal"
                request._send_json = mock.Mock()
                request.do_POST()
                rehearsal_payload = request._send_json.call_args.args[0]

        self.assertEqual(draft_payload["status"], "created")
        self.assertEqual(status_payload["status"], "passed")
        self.assertEqual(staging_payload["staging_decision"], "ready_for_staging")
        self.assertEqual(rehearsal_payload["status"], "completed")

    def test_dashboard_acceptance_rejects_run_id_path_escape(self) -> None:
        from growth_dev.team.dashboard import start_dashboard_acceptance

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            self._write_completed_run(runs_dir)

            with self.assertRaises(ValueError):
                start_dashboard_acceptance("../dashboard-run-1", runs_dir=runs_dir, repo_root=root)

        self.assertFalse((root / "dashboard-run-1" / "acceptance" / "status.json").exists())

    def test_dashboard_artifact_reader_is_confined_to_allowed_paths(self) -> None:
        from growth_dev.team.dashboard import read_dashboard_artifact

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            self._write_completed_run(runs_dir)
            (root / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")

            prd = read_dashboard_artifact("dashboard-run-1", "prd.md", runs_dir=runs_dir, repo_root=root)
            agents = read_dashboard_artifact("dashboard-run-1", "AGENTS.md", runs_dir=runs_dir, repo_root=root, scope="repo")

            with self.assertRaises(ValueError):
                read_dashboard_artifact("dashboard-run-1", "../secret.txt", runs_dir=runs_dir, repo_root=root)
            with self.assertRaises(ValueError):
                read_dashboard_artifact("dashboard-run-1", "README.md", runs_dir=runs_dir, repo_root=root, scope="repo")

        self.assertIn("# PRD", prd["content"])
        self.assertIn("# AGENTS", agents["content"])

    def test_dashboard_frontend_assets_live_outside_backend_package(self) -> None:
        root = Path(__file__).resolve().parents[1]
        dashboard_dir = root / "dashboard"

        self.assertTrue((dashboard_dir / "index.html").exists())
        self.assertTrue((dashboard_dir / "app.js").exists())
        self.assertTrue((dashboard_dir / "business_view.js").exists())
        self.assertTrue((dashboard_dir / "styles.css").exists())
        self.assertFalse(str(dashboard_dir).startswith(str(root / "growth_dev")))

    def test_dashboard_i18n_schema_contains_business_language_sections(self) -> None:
        root = Path(__file__).resolve().parents[1]
        i18n_path = root / "dashboard" / "i18n" / "zh-CN.json"

        payload = json.loads(i18n_path.read_text(encoding="utf-8"))

        for section in ("app", "status", "stages", "agents", "gates", "artifacts", "events", "actions", "memoryRecall", "releaseReadiness", "stagingReadiness"):
            self.assertIn(section, payload)
        for status in ("not_started", "processing", "completed", "needs_attention", "waiting_confirmation", "planned"):
            self.assertIn(status, payload["status"])
            self.assertNotIn(status, payload["status"][status]["label"])
        for row_label in ("done", "attention", "next"):
            self.assertIn(row_label, payload["stages"]["rowLabels"])
        for app_key in ("engineeringRun", "engineeringEvents", "engineeringLog", "engineeringDiff"):
            self.assertIn(app_key, payload["app"])
        for action_key in ("artifactPending", "readyForConfirmation", "noNextAction"):
            self.assertIn(action_key, payload["actions"])
        self.assertIn("acceptance", payload)
        for acceptance_key in ("title", "confirmButton", "running", "completed", "failed", "notStarted"):
            self.assertIn(acceptance_key, payload["acceptance"])
        for readiness_key in ("title", "generateButton", "empty", "decision", "gates", "prDraft", "nextActions"):
            self.assertIn(readiness_key, payload["releaseReadiness"])
        for staging_key in ("title", "generateButton", "empty", "decision", "gates", "nextActions"):
            self.assertIn(staging_key, payload["stagingReadiness"])
        for stage in ("requirement", "design", "implementation", "quality", "delivery"):
            self.assertIn(stage, payload["stages"])
            self.assertIn("title", payload["stages"][stage])

    def test_dashboard_acceptance_empty_state_explains_confirmed_apply_and_full_tests(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "dashboard" / "index.html").read_text(encoding="utf-8")
        i18n = json.loads((root / "dashboard" / "i18n" / "zh-CN.json").read_text(encoding="utf-8"))

        expected = "确认后会应用本次代码变更，并自动运行全量测试。"

        self.assertEqual(i18n["acceptance"]["notStarted"], expected)
        self.assertIn(expected, html)

    def test_dashboard_html_uses_three_column_flow_workspace(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "dashboard" / "index.html").read_text(encoding="utf-8")

        self.assertIn('class="workspace"', html)
        self.assertIn('class="task-list"', html)
        self.assertIn('class="flow-main"', html)
        self.assertIn('class="flow-timeline"', html)
        self.assertLess(html.index('class="task-list"'), html.index('class="flow-main"'))
        self.assertLess(html.index('class="flow-main"'), html.index('class="flow-timeline"'))
        self.assertLess(html.index('class="summary-band"'), html.index('id="flow-node-detail"'))
        self.assertLess(html.index('id="flow-node-detail"'), html.index('class="request-panel"'))
        self.assertIn('id="flow-nodes"', html)
        self.assertIn('id="flow-node-detail"', html)
        self.assertIn('id="flow-artifact-actions"', html)
        self.assertIn('id="flow-artifact-preview"', html)
        self.assertIn('id="flow-engineering-evidence"', html)

    def test_dashboard_html_defaults_to_business_copy_and_hides_engineering_controls(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "dashboard" / "index.html").read_text(encoding="utf-8")

        self.assertIn("data-i18n", html)
        self.assertNotIn("advanced-settings", html)
        self.assertIn('class="config-grid"', html)
        self.assertIn('id="acceptance-action"', html)
        self.assertIn('id="flow-node-detail"', html)
        self.assertNotIn('id="deliverables-panel"', html)
        self.assertNotIn('id="acceptance-panel"', html)
        self.assertNotIn('class="engineering-rail"', html)
        self.assertNotIn('app.acceptanceSummary', html)
        self.assertNotIn('app.acceptanceSummaryHint', html)
        self.assertNotIn("engineering-panel", html)
        self.assertNotIn('id="business-stages"', html)
        self.assertNotIn('id="health-summary"', html)
        self.assertNotIn('id="quality-gates"', html)
        for engineering_copy in ("Pipeline", "Gates", "Logs", "Artifacts", "Executor", "Provider", "Model"):
            self.assertNotIn(engineering_copy, html)

    def test_dashboard_flow_detail_uses_compact_artifact_and_evidence_layout(self) -> None:
        root = Path(__file__).resolve().parents[1]
        css = (root / "dashboard" / "styles.css").read_text(encoding="utf-8")

        self.assertIn(".flow-main", css)
        self.assertIn(".flow-timeline", css)
        self.assertIn(".flow-node-detail", css)
        self.assertIn(".flow-detail-grid", css)
        self.assertIn(".flow-artifact-grid", css)
        self.assertIn(".flow-engineering-evidence", css)
        self.assertIn(".flow-node-button.selected", css)
        self.assertIn(".task-list {\n  position: sticky;", css)
        self.assertIn("#runs {\n  overflow: auto;", css)
        self.assertIn(".flow-main {\n  display: grid;\n  grid-template-rows: auto minmax(0, 1fr) auto;", css)
        self.assertIn(".request-panel {\n  position: sticky;", css)

    def test_dashboard_flow_detail_has_i18n_and_render_helpers(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "dashboard" / "app.js").read_text(encoding="utf-8")
        i18n = json.loads((root / "dashboard" / "i18n" / "zh-CN.json").read_text(encoding="utf-8"))

        self.assertIn("selectedFlowNodeId", app_js)
        self.assertIn("renderFlowTimeline", app_js)
        self.assertIn("renderSelectedFlowNode", app_js)
        self.assertIn("renderFlowNodeArtifacts", app_js)
        self.assertIn("renderFlowNodeEngineering", app_js)
        self.assertIn("renderImplementationFlow", app_js)
        self.assertIn("loadArtifactContent", app_js)
        self.assertIn("flow", i18n)
        self.assertIn("implementationFlow", i18n)
        for key in (
            "timelineTitle",
            "detailTitle",
            "artifacts",
            "engineeringEvidence",
            "allArtifacts",
            "emptyArtifacts",
        ):
            self.assertIn(key, i18n["flow"])

    def test_dashboard_stage_detail_content_is_bounded_inside_card(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "dashboard" / "app.js").read_text(encoding="utf-8")
        css = (root / "dashboard" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('list.className = "flow-evidence-list"', app_js)
        self.assertIn(".flow-node-detail {\n  display: grid;", css)
        self.assertIn("grid-template-columns: minmax(0, 1fr);", css)
        self.assertIn("max-height: none;", css)
        self.assertIn(".flow-detail-grid", css)
        self.assertIn("overflow: auto;", css)
        self.assertIn(".implementation-flow", css)
        self.assertIn(".flow-evidence-list li", css)
        self.assertIn("width: 100%;", css)
        self.assertIn("overflow-wrap: anywhere;", css)

    def test_dashboard_flow_detail_scroll_is_preserved_during_polling_refresh(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "dashboard" / "app.js").read_text(encoding="utf-8")

        self.assertIn("flowDetailScroll", app_js)
        self.assertIn("function flowDetailKey", app_js)
        self.assertIn("function captureFlowDetailScroll", app_js)
        self.assertIn("function restoreFlowDetailScroll", app_js)
        self.assertIn("captureFlowDetailScroll();", app_js)
        self.assertIn('detail.addEventListener("scroll"', app_js)
        self.assertIn("restoreFlowDetailScroll(detail);", app_js)
        self.assertIn('state.flowDetailScroll = { key: "", top: 0 };', app_js)

    def test_dashboard_frontend_display_copy_comes_from_i18n(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "dashboard" / "app.js").read_text(encoding="utf-8")
        business_view_js = (root / "dashboard" / "business_view.js").read_text(encoding="utf-8")

        forbidden_display_literals = (
            "已完成什么",
            "需要关注什么",
            "下一步",
            "结果已准备好，等待人工确认是否采纳。",
            "（未生成）",
            "暂无可查看产物",
            "暂无风险",
        )
        for literal in forbidden_display_literals:
            self.assertNotIn(literal, app_js)
            self.assertNotIn(literal, business_view_js)

    def test_dashboard_frontend_tracks_selected_artifact_and_avoids_raw_warning_panel(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "dashboard" / "app.js").read_text(encoding="utf-8")

        self.assertIn("selectedArtifactPath", app_js)
        self.assertIn("artifact-button selected", app_js)
        self.assertIn("warningGroups", app_js)
        self.assertIn(".slice(0, 3)", app_js)
        self.assertIn("raw_warnings", app_js)
        self.assertIn("rawWarningsLabel", app_js)
        self.assertIn("renderFlowNodeEngineering", app_js)
        self.assertIn("renderAllArtifactsNode", app_js)
        self.assertIn("selectFlowNode", app_js)
        self.assertNotIn("for (const warning of health.warnings", app_js)

    def test_dashboard_diff_view_uses_file_grouped_codex_style_preview(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "dashboard" / "app.js").read_text(encoding="utf-8")
        css = (root / "dashboard" / "styles.css").read_text(encoding="utf-8")
        i18n = json.loads((root / "dashboard" / "i18n" / "zh-CN.json").read_text(encoding="utf-8"))

        self.assertIn("selectedDiffFilePath", app_js)
        self.assertIn("renderDiffArtifact", app_js)
        self.assertIn("parseUnifiedDiff", app_js)
        self.assertIn("renderDiffSummary", app_js)
        self.assertIn('artifact.path === "codex/diff.patch"', app_js)
        self.assertNotIn('JSON.stringify(vm.engineering.diffSummary || {}, null, 2)', app_js)
        self.assertIn("diffView", i18n)
        for key in ("changedFiles", "additions", "deletions", "empty", "binaryOrNoText"):
            self.assertIn(key, i18n["diffView"])
        for class_name in (
            ".diff-view",
            ".diff-file-list",
            ".diff-file-button",
            ".diff-preview",
            ".diff-line-add",
            ".diff-line-remove",
            ".diff-line-meta",
        ):
            self.assertIn(class_name, css)

    def test_dashboard_acceptance_frontend_exposes_button_and_renderer(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "dashboard" / "app.js").read_text(encoding="utf-8")
        css = (root / "dashboard" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("renderAcceptance", app_js)
        self.assertIn("renderMemoryRecall", app_js)
        self.assertIn("renderReleaseReadiness", app_js)
        self.assertIn("startAcceptance", app_js)
        self.assertIn("startReleaseReadiness", app_js)
        self.assertIn('/acceptance"', app_js)
        self.assertIn('/release/readiness"', app_js)
        self.assertIn("acceptance-action", app_js)
        self.assertIn("release-readiness-action", app_js)
        self.assertIn("acceptance-step", app_js)
        self.assertIn(".acceptance-step", css)
        self.assertIn(".release-gate-row", css)

    def test_dashboard_pr_ci_frontend_exposes_button_renderer_and_i18n(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "dashboard" / "index.html").read_text(encoding="utf-8")
        app_js = (root / "dashboard" / "app.js").read_text(encoding="utf-8")
        css = (root / "dashboard" / "styles.css").read_text(encoding="utf-8")
        i18n = json.loads((root / "dashboard" / "i18n" / "zh-CN.json").read_text(encoding="utf-8"))

        self.assertIn('id="github-pr-action"', html)
        self.assertIn('id="github-ci-action"', html)
        self.assertIn("renderGithubPrCi", app_js)
        self.assertIn("startGithubDraftPr", app_js)
        self.assertIn("refreshGithubCi", app_js)
        self.assertIn('/pr/draft"', app_js)
        self.assertIn('/pr/status"', app_js)
        self.assertIn(".github-check", css)
        self.assertIn("githubPr", i18n)
        for key in ("title", "createDraftButton", "refreshCiButton", "notReady", "noPr"):
            self.assertIn(key, i18n["githubPr"])

    def test_dashboard_staging_readiness_frontend_exposes_card_endpoint_and_i18n(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "dashboard" / "index.html").read_text(encoding="utf-8")
        app_js = (root / "dashboard" / "app.js").read_text(encoding="utf-8")
        i18n = json.loads((root / "dashboard" / "i18n" / "zh-CN.json").read_text(encoding="utf-8"))

        self.assertIn('id="staging-readiness-action"', html)
        self.assertIn('id="staging-rehearsal-action"', html)
        self.assertIn("renderStagingReadiness", app_js)
        self.assertIn("renderStagingRehearsal", app_js)
        self.assertIn("startStagingReadiness", app_js)
        self.assertIn("startStagingRehearsal", app_js)
        self.assertIn('/staging-readiness"', app_js)
        self.assertIn('/staging-rehearsal"', app_js)
        self.assertIn("stagingReadiness", i18n)
        self.assertIn("stagingRehearsal", i18n)
        for key in ("title", "generateButton", "empty", "decision", "gates", "nextActions"):
            self.assertIn(key, i18n["stagingReadiness"])
        for key in ("title", "runButton", "empty", "status", "logs", "nextActions"):
            self.assertIn(key, i18n["stagingRehearsal"])
        self.assertIn('id="flow-node-detail"', html)

    def test_dashboard_pr_ci_empty_state_explains_draft_pr_next_step(self) -> None:
        root = Path(__file__).resolve().parents[1]
        i18n = json.loads((root / "dashboard" / "i18n" / "zh-CN.json").read_text(encoding="utf-8"))

        self.assertIn(
            "发布准备通过后，可以推送当前分支并创建 GitHub Draft PR",
            i18n["githubPr"]["noPr"],
        )

    def test_business_view_model_translates_run_to_extended_flow_nodes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        i18n_path = root / "dashboard" / "i18n" / "zh-CN.json"
        module_path = root / "dashboard" / "business_view.js"
        run = {
            "run_id": "biz-run-1",
            "brief": "做一个业务页面",
            "status": "completed",
            "stages": [
                {"id": "orchestrator", "status": "completed", "outputs": ["task.yaml", "context.md"]},
                {"id": "product", "status": "completed", "outputs": ["prd.md"]},
                {"id": "architect", "status": "completed", "outputs": ["tech_spec.md"]},
                {"id": "ux", "status": "completed", "outputs": ["ui_spec.md"]},
                {"id": "qa", "status": "completed", "outputs": ["eval.md"]},
                {"id": "coder", "status": "completed", "outputs": ["coding_prompt.md", "codex/diff.patch"]},
                {"id": "reviewer", "status": "completed", "outputs": ["review_report.md"]},
                {"id": "verifier", "status": "completed", "outputs": ["test_report.md"]},
                {"id": "publisher", "status": "completed", "outputs": ["final_report.md"]},
            ],
            "gates": [
                {"id": "before_coding", "status": "passed", "missing_artifacts": []},
                {"id": "before_publish", "status": "passed", "missing_artifacts": []},
            ],
            "apply_gate": {"status": "passed", "reason": "ready"},
            "artifacts": [
                {"label": "Task Package", "path": "task.yaml", "scope": "run", "exists": True},
                {"label": "PRD", "path": "prd.md", "scope": "run", "exists": True},
                {"label": "Architecture Diagram", "path": "architecture_diagram.md", "scope": "run", "exists": False},
                {"label": "Implementation Trace", "path": "codex/implementation_trace.json", "scope": "run", "exists": True},
                {"label": "Diff Evidence", "path": "codex/diff.patch", "scope": "run", "exists": True},
            ],
            "implementation_trace": {
                "status": "completed",
                "current_step": "finalize_result",
                "steps": [{"id": "finalize_result", "title": "生成实现结果", "status": "completed"}],
                "evidence": {"changed_files": ["dashboard/app.js"], "tests_run": ["python3 -m unittest tests.test_dashboard -v"]},
                "blockers": [],
                "risk_events": [],
            },
            "risk_events": [],
            "next_actions": ["python -m growth_dev.cli team apply --run-id biz-run-1"],
            "health_summary": {"status": "completed_ready", "label": "已完成可采纳", "summary": "结果已通过关键检查。", "warnings": [], "blockers": []},
            "quality_report": {
                "status": "passed",
                "score": 1.0,
                "summary": "文件产物贴合需求。",
                "checks": [{"id": "prd.md.specificity", "title": "需求贴题度", "status": "passed", "detail": "通过", "artifact": "prd.md"}],
            },
            "memory_recall": {
                "matches": [
                    {
                        "run_id": "similar-run",
                        "domain_id": "web_monitoring",
                        "task_type": "dashboard_ui_change",
                        "score": 0.84,
                        "reasons": ["same_domain"],
                        "recommended_skills": ["context_engineering"],
                    }
                ],
                "recommended_skills": [
                    {
                        "id": "context_engineering",
                        "confidence": 0.84,
                        "source_run_ids": ["similar-run"],
                        "why": "历史任务需要收窄上下文。",
                    }
                ],
                "context_strategy": {
                    "reuse": ["dashboard/app.js"],
                    "avoid": ["raw stdout/stderr"],
                    "checklist": ["先看历史验收。"],
                },
            },
        }
        script = f"""
const fs = require('fs');
const {{ toBusinessViewModel }} = require({json.dumps(str(module_path))});
const i18n = JSON.parse(fs.readFileSync({json.dumps(str(i18n_path))}, 'utf8'));
const vm = toBusinessViewModel({json.dumps(run)}, i18n);
console.log(JSON.stringify(vm));
"""
        completed = subprocess.run(["node", "-e", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        vm = json.loads(completed.stdout)

        self.assertEqual(
            [node["id"] for node in vm["flowNodes"]],
            ["requirement", "design", "implementation", "quality", "delivery", "release", "github_pr_ci", "staging"],
        )
        self.assertEqual(vm["recommendedFlowNodeId"], "delivery")
        self.assertEqual([stage["id"] for stage in vm["stages"]], ["requirement", "design", "implementation", "quality", "delivery"])
        self.assertEqual(vm["stages"][0]["title"], "需求理解")
        self.assertEqual(vm["stages"][1]["statusLabel"], "已完成")
        self.assertEqual(vm["stages"][4]["status"], "waiting_confirmation")
        self.assertEqual(vm["stages"][4]["statusLabel"], "等待确认")
        self.assertEqual(vm["deliverables"][0]["title"], "任务包")
        self.assertEqual(vm["deliverables"][2]["title"], "架构图")
        self.assertEqual(vm["deliverables"][3]["title"], "AI 实现流程")
        self.assertEqual(vm["health"]["label"], "已完成可采纳")
        self.assertEqual(vm["artifactQuality"]["status"], "passed")
        self.assertEqual(vm["implementationFlow"]["status"], "completed")
        self.assertEqual(vm["memoryRecall"]["matches"][0]["run_id"], "similar-run")
        self.assertEqual(vm["memoryRecall"]["recommendedSkills"][0]["id"], "context_engineering")
        design_stage = vm["stages"][1]
        implementation_stage = vm["stages"][2]
        self.assertEqual(design_stage["agentIds"], ["product", "architect", "ux", "qa"])
        self.assertTrue(any(artifact["path"] == "prd.md" for artifact in design_stage["artifacts"]))
        self.assertTrue(any(artifact["path"] == "codex/implementation_trace.json" for artifact in implementation_stage["artifacts"]))
        self.assertTrue(any(artifact["path"] == "codex/diff.patch" for artifact in implementation_stage["artifacts"]))
        self.assertEqual(design_stage["artifacts"][0]["title"], "PRD")
        self.assertIn("代码差异", {artifact["title"] for artifact in implementation_stage["artifacts"]})
        delivery_node = vm["flowNodes"][4]
        release_node = vm["flowNodes"][5]
        github_node = vm["flowNodes"][6]
        staging_node = vm["flowNodes"][7]
        self.assertEqual(delivery_node["status"], "waiting_confirmation")
        self.assertTrue(any(action["id"] == "acceptance" for action in delivery_node["actions"]))
        self.assertTrue(any(artifact["path"] == "final_report.md" for artifact in delivery_node["artifacts"]))
        self.assertTrue(any(action["id"] == "release_readiness" for action in release_node["actions"]))
        self.assertTrue(any(action["id"] == "github_pr" for action in github_node["actions"]))
        self.assertTrue(any(action["id"] == "github_ci" for action in github_node["actions"]))
        self.assertTrue(any(action["id"] == "staging_readiness" for action in staging_node["actions"]))
        self.assertTrue(any(action["id"] == "staging_rehearsal" for action in staging_node["actions"]))
        self.assertIn("engineeringEvidence", vm["flowNodes"][2])
        self.assertTrue(vm["flowNodes"][2]["engineeringEvidence"]["events"])

    def test_business_view_model_marks_requirement_stage_failed_from_requirement_gate(self) -> None:
        run = {
            "run_id": "blocked-requirement-run",
            "brief": "需求还有阻塞问题",
            "status": "failed",
            "stages": [
                {"id": "orchestrator", "status": "completed", "outputs": ["task.yaml", "context.md"]},
                {
                    "id": "requirements",
                    "status": "failed",
                    "outputs": ["requirements/brief_analysis.json", "requirements/requirement_quality_report.json"],
                },
            ],
            "gates": [{"id": "requirement_quality", "status": "failed", "missing_artifacts": ["blocking_questions_present"]}],
            "requirement_understanding": {
                "brief_analysis": {"blocking_questions": ["请补充目标用户。"], "planning_mode": "auto"},
                "quality_report": {
                    "status": "failed",
                    "summary": "Requirement understanding needs more input.",
                    "blockers": ["blocking_questions_present"],
                },
            },
            "artifacts": [
                {"label": "Requirement Analysis", "path": "requirements/brief_analysis.json", "scope": "run", "exists": True},
                {
                    "label": "Requirement Quality Report",
                    "path": "requirements/requirement_quality_report.json",
                    "scope": "run",
                    "exists": True,
                },
            ],
            "risk_events": ["blocking_questions_present"],
        }

        vm = self._business_view_model(run)
        requirement_stage = vm["stages"][0]

        self.assertEqual(vm["status"], "needs_attention")
        self.assertEqual(vm["recommendedFlowNodeId"], "requirement")
        self.assertEqual(requirement_stage["status"], "needs_attention")
        self.assertEqual(requirement_stage["statusLabel"], "需要处理")
        self.assertTrue(any(artifact["path"] == "requirements/brief_analysis.json" for artifact in requirement_stage["artifacts"]))

    def test_business_view_model_marks_delivery_completed_after_acceptance_success(self) -> None:
        run = {
            "run_id": "accepted-run-1",
            "brief": "验收成功后更新交付阶段",
            "status": "completed",
            "stages": [{"id": "publisher", "status": "completed", "outputs": ["final_report.md"]}],
            "gates": [],
            "apply_gate": {"status": "passed", "reason": "ready"},
            "acceptance": {"status": "completed", "applied": True, "conclusion": "已采纳且测试通过。"},
            "artifacts": [{"label": "Final", "path": "final_report.md", "scope": "run", "exists": True}],
            "risk_events": [],
        }

        vm = self._business_view_model(run)
        delivery_stage = vm["stages"][4]

        self.assertEqual(vm["status"], "completed")
        self.assertEqual(vm["statusLabel"], "已完成")
        self.assertEqual(delivery_stage["status"], "completed")
        self.assertEqual(delivery_stage["statusLabel"], "已完成")

    def test_business_view_model_marks_delivery_needs_attention_after_acceptance_failure(self) -> None:
        run = {
            "run_id": "accepted-run-2",
            "brief": "验收失败后提示处理",
            "status": "completed",
            "stages": [{"id": "publisher", "status": "completed", "outputs": ["final_report.md"]}],
            "gates": [],
            "apply_gate": {"status": "passed", "reason": "ready"},
            "acceptance": {"status": "failed", "applied": True, "conclusion": "已采纳但测试失败，需修复后再验证。"},
            "artifacts": [{"label": "Final", "path": "final_report.md", "scope": "run", "exists": True}],
            "risk_events": [],
        }

        vm = self._business_view_model(run)
        delivery_stage = vm["stages"][4]

        self.assertEqual(vm["status"], "needs_attention")
        self.assertEqual(vm["statusLabel"], "需要处理")
        self.assertEqual(delivery_stage["status"], "needs_attention")
        self.assertEqual(delivery_stage["statusLabel"], "需要处理")

    def test_business_view_model_groups_health_warnings_and_recommends_default_artifact(self) -> None:
        root = Path(__file__).resolve().parents[1]
        i18n_path = root / "dashboard" / "i18n" / "zh-CN.json"
        module_path = root / "dashboard" / "business_view.js"
        run = {
            "run_id": "biz-run-2",
            "brief": "小改动",
            "status": "completed",
            "apply_gate": {"status": "passed", "reason": "ready"},
            "stages": [],
            "gates": [],
            "artifacts": [
                {"label": "PRD", "path": "prd.md", "scope": "run", "exists": True},
                {"label": "Review", "path": "review_report.md", "scope": "run", "exists": True},
                {"label": "Final", "path": "final_report.md", "scope": "run", "exists": True},
            ],
            "risk_events": [],
            "next_actions": [],
            "health_summary": {
                "status": "completed_with_warnings",
                "label": "已完成但有警告",
                "summary": "存在 2 类非阻塞系统提示，未影响 Review/Test/Report。",
                "warnings": [],
                "warning_groups": [
                    {"id": "plugin_sync", "title": "插件同步提示", "count": 2, "severity": "info"},
                    {"id": "telemetry", "title": "遥测提示", "count": 1, "severity": "info"},
                ],
                "blockers": [],
            },
        }
        script = f"""
const fs = require('fs');
const {{ toBusinessViewModel }} = require({json.dumps(str(module_path))});
const i18n = JSON.parse(fs.readFileSync({json.dumps(str(i18n_path))}, 'utf8'));
const vm = toBusinessViewModel({json.dumps(run)}, i18n);
console.log(JSON.stringify(vm));
"""
        completed = subprocess.run(["node", "-e", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        vm = json.loads(completed.stdout)

        self.assertEqual(vm["health"]["warningGroups"][0]["title"], "插件同步提示")
        self.assertEqual(vm["recommendedArtifact"]["path"], "final_report.md")

    def test_business_view_model_marks_permission_error_as_needs_attention(self) -> None:
        root = Path(__file__).resolve().parents[1]
        i18n_path = root / "dashboard" / "i18n" / "zh-CN.json"
        module_path = root / "dashboard" / "business_view.js"
        run = {
            "run_id": "permission-run-1",
            "brief": "demo",
            "status": "failed",
            "failure_category": "permission_error",
            "stages": [{"id": "coder", "status": "running", "outputs": []}],
            "gates": [],
            "artifacts": [],
            "risk_events": ["permission_error"],
            "logs": ["PermissionError"],
        }
        script = f"""
const fs = require('fs');
const {{ toBusinessViewModel }} = require({json.dumps(str(module_path))});
const i18n = JSON.parse(fs.readFileSync({json.dumps(str(i18n_path))}, 'utf8'));
const vm = toBusinessViewModel({json.dumps(run)}, i18n);
console.log(JSON.stringify(vm));
"""
        completed = subprocess.run(["node", "-e", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        vm = json.loads(completed.stdout)

        self.assertEqual(vm["status"], "needs_attention")
        self.assertIn("运行环境权限异常", vm["headline"])
        self.assertEqual(vm["stages"][2]["status"], "needs_attention")

    def test_team_serve_dashboard_cli_is_registered(self) -> None:
        from growth_dev.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["team", "serve-dashboard", "--host", "127.0.0.1", "--port", "8790"])

        self.assertTrue(callable(args.func))

    def test_dashboard_handler_factory_exposes_get_and_post_methods(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, create_dashboard_handler

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            self._write_completed_run(runs_dir)
            handler = create_dashboard_handler(DashboardConfig(runs_dir=runs_dir, repo_root=root, dashboard_dir=Path("dashboard")))

        self.assertTrue(callable(getattr(handler, "do_GET")))
        self.assertTrue(callable(getattr(handler, "do_POST")))

    def test_dashboard_start_run_creates_background_deterministic_run(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, start_dashboard_run

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            domains_dir = root / "domains"
            domain_dir = domains_dir / "web_monitoring"
            domain_dir.mkdir(parents=True)
            (domain_dir / "domain.yaml").write_text(WEB_MONITORING_DOMAIN_YAML, encoding="utf-8")
            (domain_dir / "team.yaml").write_text(TEAM_YAML, encoding="utf-8")
            runs_dir = root / "runs"
            repo_root = Path(__file__).resolve().parents[1]
            response = start_dashboard_run(
                DashboardConfig(
                    runs_dir=runs_dir,
                    domains_dir=domains_dir,
                    repo_root=repo_root,
                    dashboard_dir=repo_root / "dashboard",
                    executor="deterministic",
                ),
                {"run_id": "posted-run-1", "brief": "验证 dashboard POST", "domain": "web_monitoring", "executor": "deterministic"},
            )
            record_path = runs_dir / "posted-run-1" / "team_run_record.json"
            deadline = time.time() + 5
            while time.time() < deadline and not record_path.exists():
                time.sleep(0.05)
            process = json.loads((runs_dir / "posted-run-1" / "process.json").read_text(encoding="utf-8"))
            record_exists = record_path.exists()

        self.assertEqual(response["run_id"], "posted-run-1")
        self.assertTrue(record_exists)
        self.assertEqual(process["run_id"], "posted-run-1")
        self.assertIn("--planning-mode", process["command"])
        self.assertIn("auto", process["command"])
        self.assertNotIn(".env", json.dumps(process, ensure_ascii=False))

    def test_dashboard_start_run_uses_absolute_paths_in_process_record_and_command(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, start_dashboard_run

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            domains_dir = root / "domains"
            domain_dir = domains_dir / "web_monitoring"
            domain_dir.mkdir(parents=True)
            (domain_dir / "domain.yaml").write_text(WEB_MONITORING_DOMAIN_YAML, encoding="utf-8")
            (domain_dir / "team.yaml").write_text(TEAM_YAML, encoding="utf-8")
            runs_dir = root / "runs"
            repo_root = Path(__file__).resolve().parents[1]

            start_dashboard_run(
                DashboardConfig(
                    runs_dir=Path("runs"),
                    domains_dir=domains_dir,
                    repo_root=repo_root,
                    dashboard_dir=repo_root / "dashboard",
                    executor="deterministic",
                ),
                {
                    "run_id": "absolute-run-1",
                    "brief": "验证绝对路径",
                    "domain": "web_monitoring",
                    "executor": "deterministic",
                    "runs_dir": runs_dir,
                },
            )
            process = json.loads((runs_dir / "absolute-run-1" / "process.json").read_text(encoding="utf-8"))

        command = process["command"]
        self.assertTrue(Path(process["run_dir"]).is_absolute())
        self.assertTrue(Path(command[command.index("--runs-dir") + 1]).is_absolute())
        self.assertTrue(Path(command[command.index("--domains-dir") + 1]).is_absolute())
        self.assertTrue(Path(command[command.index("--repo-root") + 1]).is_absolute())

    def test_dashboard_state_marks_background_permission_error_as_failed(self) -> None:
        from growth_dev.team.dashboard import build_dashboard_state

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "permission-run-1"
            run_dir.mkdir(parents=True)
            (run_dir / "team_run_record.json").write_text(
                json.dumps(
                    {
                        "run_id": "permission-run-1",
                        "domain_id": "web_monitoring",
                        "brief": "demo",
                        "status": "running",
                        "run_dir": str(run_dir),
                        "agent_runs": [{"agent_id": "coder", "status": "running", "started_at": "a", "finished_at": "", "risk_events": [], "output_paths": [], "message": "agent started", "metadata": {}}],
                        "risk_events": [],
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "process.json").write_text(
                json.dumps({"run_id": "permission-run-1", "pid": 999999, "status": "running", "run_dir": str(run_dir)}),
                encoding="utf-8",
            )
            (run_dir / "background_stderr.log").write_text(
                "PermissionError: [Errno 1] Operation not permitted: 'runs/permission-run-1/team_run_record.json'\n",
                encoding="utf-8",
            )

            state = build_dashboard_state("permission-run-1", runs_dir=runs_dir, repo_root=root)

        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["failure_category"], "permission_error")
        self.assertIn("permission_error", state["risk_events"])

    def test_dashboard_run_list_marks_background_permission_error_as_failed(self) -> None:
        from growth_dev.team.dashboard import list_dashboard_runs

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "permission-run-1"
            run_dir.mkdir(parents=True)
            (run_dir / "team_run_record.json").write_text(
                json.dumps(
                    {
                        "run_id": "permission-run-1",
                        "domain_id": "web_monitoring",
                        "brief": "demo",
                        "status": "running",
                        "run_dir": str(run_dir),
                        "agent_runs": [{"agent_id": "coder", "status": "running", "started_at": "a", "finished_at": "", "risk_events": [], "output_paths": [], "message": "agent started", "metadata": {}}],
                        "risk_events": [],
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "process.json").write_text(
                json.dumps({"run_id": "permission-run-1", "pid": 999999, "status": "running", "run_dir": str(run_dir)}),
                encoding="utf-8",
            )
            (run_dir / "background_stderr.log").write_text(
                "PermissionError: [Errno 1] Operation not permitted: 'runs/permission-run-1/team_run_record.json'\n",
                encoding="utf-8",
            )

            runs = list_dashboard_runs(runs_dir)

        self.assertEqual(runs[0]["status"], "failed")
        self.assertEqual(runs[0]["failure_category"], "permission_error")
