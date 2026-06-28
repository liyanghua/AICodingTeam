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
                    "candidate_source": "model",
                    "requirements_model": "gpt-5.3",
                    "candidate_validation": {"status": "passed", "blockers": [], "warnings": []},
                    "blockers": [],
                    "warnings": ["llm_draft_channel_used_but_not_promoted"],
                    "checks": [{"id": "stable_acceptance_ids", "status": "passed"}],
                }
            ),
            encoding="utf-8",
        )
        (requirements_dir / "clarification.md").write_text("# Requirement Clarification\n", encoding="utf-8")
        (requirements_dir / "prd.draft.md").write_text("# PM PRD Draft\n", encoding="utf-8")
        (requirements_dir / "user_stories.draft.md").write_text("# User Stories Draft\n", encoding="utf-8")
        (requirements_dir / "prd_red_team.md").write_text("# PRD Red-Team Draft\n", encoding="utf-8")
        (requirements_dir / "acceptance_criteria.draft.md").write_text("# Draft Acceptance Criteria\n", encoding="utf-8")
        (requirements_dir / "open_questions.md").write_text("# Open Questions\n", encoding="utf-8")
        (requirements_dir / "assumptions.md").write_text("# Assumptions\n", encoding="utf-8")
        (requirements_dir / "requirement_understanding.candidate.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "model": "gpt-5.3",
                    "candidate_source": "model",
                    "validation": {"status": "passed", "blockers": [], "warnings": []},
                    "clarification_angles": ["业务目标", "输入输出", "可观测验收"],
                    "blocking_questions": [],
                }
            ),
            encoding="utf-8",
        )
        (requirements_dir / "capability_boundary.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "change_type": "extend_existing_capability",
                    "existing_capabilities": [{"id": "dashboard_business_view", "summary": "Dashboard can render flow nodes."}],
                    "required_new_capabilities": [{"id": "capability_boundary_view", "summary": "Dashboard shows capability boundary."}],
                    "unsupported_capabilities": [],
                }
            ),
            encoding="utf-8",
        )
        (requirements_dir / "capability_boundary.md").write_text("# Capability Boundary\n", encoding="utf-8")
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
        (planning_dir / "test_scenarios.draft.md").write_text("# PM Test Scenarios Draft\n", encoding="utf-8")
        (planning_dir / "planning_quality_report.json").write_text(
            json.dumps({"schema_version": 1, "status": "passed", "summary": "Planning is ready for implementation.", "blockers": []}),
            encoding="utf-8",
        )
        (planning_dir / "tdd_plan.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "status": "passed",
                    "test_cases": [
                        {
                            "id": "TDD-001",
                            "acceptance_criteria_ids": ["AC-001"],
                            "test_intent": "Dashboard shows capability boundary artifacts.",
                            "expected_red_failure": "artifact missing before implementation",
                            "verification_command": "python3 -m unittest tests.test_dashboard -v",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (planning_dir / "tdd_plan.md").write_text("# TDD Plan\n", encoding="utf-8")
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
        (run_dir / "finish_learning_suggestions.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "capability_update_suggestions": ["Review domain capability updates."],
                    "skill_update_suggestions": ["Keep context_engineering as hint."],
                    "failure_classification_suggestions": ["No new rule."],
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "finish_learning_suggestions.md").write_text("# Capability / Skill Update Suggestions\n", encoding="utf-8")
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
        (codex_dir / "failure_classification.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "stage": "coder",
                    "classification_decision": "passed",
                    "summary": "AI implementation completed without blocking failure evidence.",
                    "primary_reason": "No blocking failure evidence.",
                    "events": [],
                    "evidence": {"exit_code": 0, "schema_valid": True, "changed_files": ["dashboard/app.js"]},
                    "blocking_events": [],
                    "warnings": [],
                    "next_actions": ["Proceed to review."],
                }
            ),
            encoding="utf-8",
        )
        (codex_dir / "failure_classification.md").write_text("# Failure Classification\n", encoding="utf-8")
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
        (run_dir / "production_readiness.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "generated_at": "2026-05-23T00:07:00+00:00",
                    "production_decision": "ready_for_manual_production",
                    "summary": "生产准备证据齐备，可进入人工生产确认。",
                    "gates": [{"id": "collector_smoke", "status": "passed", "reason": "top-n=1 smoke passed.", "evidence": ["result_count=1"]}],
                    "evidence": {
                        "staging_decision": "ready_for_staging",
                        "staging_rehearsal_status": "completed",
                        "mac_mini": {"status": "ok", "launch_agent": "running"},
                        "cloud_asset_center": {"status": "ok"},
                        "collector_smoke": {"status": "completed", "result_count": 1},
                        "cloud_sync": {"status": "ok", "synced_assets": 1},
                    },
                    "blockers": [],
                    "warnings": [],
                    "next_actions": ["人工确认生产窗口。"],
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "production_readiness.md").write_text("# Production Readiness\n", encoding="utf-8")
        (run_dir / "deployment_runbook.md").write_text("# 手机采集生产部署 Runbook\n", encoding="utf-8")
        return run_dir

    def _write_app_generation_workbench_run(self, runs_dir: Path, run_id: str = "app-generation-workbench") -> Path:
        run_dir = runs_dir / run_id
        requirements_dir = run_dir / "requirements"
        planning_dir = run_dir / "planning"
        codex_dir = run_dir / "codex"
        worktree_app_dir = run_dir / "worktree" / "generated_apps" / "todo-prototype"
        (worktree_app_dir / "public").mkdir(parents=True)
        requirements_dir.mkdir(parents=True)
        planning_dir.mkdir(parents=True)
        codex_dir.mkdir(parents=True)
        record = {
            "run_id": run_id,
            "team_id": "ai_native_engineering_team",
            "domain_id": "app_generation",
            "brief": "根据 PRD 生成本地应用：todo-prototype",
            "status": "completed",
            "run_dir": str(run_dir),
            "started_at": "2026-06-25T00:00:00+00:00",
            "finished_at": "2026-06-25T00:03:00+00:00",
            "inputs": {
                "app_slug": "todo-prototype",
                "prd_text": "# Todo PRD\n\n用户可以新增、完成、筛选待办，状态保存在浏览器本地。",
                "comparison_group_id": "cmp-todo-prototype",
            },
            "agent_runs": [
                {
                    "agent_id": "requirements",
                    "status": "completed",
                    "started_at": "a",
                    "finished_at": "b",
                    "risk_events": [],
                    "output_paths": [
                        "input_prd.md",
                        "requirements/brief_analysis.json",
                        "requirements/normalized_prd.md",
                        "context_pack.md",
                        "app_contract.json",
                        "acceptance_criteria.md",
                        "planning/acceptance_coverage_matrix.json",
                        "planning/tdd_plan.json",
                    ],
                    "message": "complex task artifacts generated",
                    "metadata": {},
                },
                {
                    "agent_id": "coder",
                    "status": "completed",
                    "started_at": "b",
                    "finished_at": "c",
                    "risk_events": [],
                    "output_paths": ["code_run_record.json", "codex/implementation_trace.json", "codex/diff.patch"],
                    "message": "coded",
                    "metadata": {},
                },
                {
                    "agent_id": "reviewer",
                    "status": "completed",
                    "started_at": "c",
                    "finished_at": "d",
                    "risk_events": [],
                    "output_paths": ["review_report.md"],
                    "message": "reviewed",
                    "metadata": {},
                },
                {
                    "agent_id": "verifier",
                    "status": "completed",
                    "started_at": "d",
                    "finished_at": "e",
                    "risk_events": [],
                    "output_paths": ["test_report.md", "codex/verification_record.json"],
                    "message": "tested",
                    "metadata": {},
                },
                {
                    "agent_id": "publisher",
                    "status": "completed",
                    "started_at": "e",
                    "finished_at": "f",
                    "risk_events": [],
                    "output_paths": ["preview_instructions.md", "final_report.md"],
                    "message": "published",
                    "metadata": {},
                },
            ],
            "gate_results": [
                {"gate_id": "requirement_quality", "status": "passed", "required_artifacts": ["input_prd.md"], "missing_artifacts": []},
                {"gate_id": "planning_quality", "status": "passed", "required_artifacts": ["planning/tdd_plan.json"], "missing_artifacts": []},
                {"gate_id": "complex_task_ready", "status": "passed", "required_artifacts": ["input_prd.md", "app_contract.json"], "missing_artifacts": []},
                {"gate_id": "before_publish", "status": "passed", "required_artifacts": ["review_report.md", "test_report.md"], "missing_artifacts": []},
            ],
            "artifacts": {},
            "risk_events": [],
            "executor": "codex",
            "executor_config": {"binary": "codex", "model": "gpt-5.3-codex", "reasoning_effort": "medium"},
        }
        (run_dir / "team_run_record.json").write_text(json.dumps(record), encoding="utf-8")
        (run_dir / "process.json").write_text(json.dumps({"run_id": run_id, "pid": 1234, "status": "completed"}), encoding="utf-8")
        (run_dir / "events.jsonl").write_text(
            "\n".join(
                [
                    json.dumps({"event": "run_started", "run_id": run_id}),
                    json.dumps({"event": "complex_task_artifacts_generated", "status": "completed"}),
                    json.dumps({"event": "agent_started", "agent_id": "coder"}),
                    json.dumps({"event": "run_completed", "run_id": run_id}),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        (run_dir / "task_journal.jsonl").write_text(
            json.dumps({"event": "slice_loop_observed", "loop_phase": "implement", "summary": "Codex slice loop completed."}) + "\n",
            encoding="utf-8",
        )
        (run_dir / "input_prd.md").write_text("# Input PRD\n\n# Todo PRD\n\n用户可以新增、完成、筛选待办。\n", encoding="utf-8")
        (requirements_dir / "brief_analysis.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "domain_id": "app_generation",
                    "recommended_skills": ["spec_driven_development", "context_engineering", "planning_and_task_breakdown"],
                    "llm_draft_requested": True,
                    "complexity": "complex",
                }
            ),
            encoding="utf-8",
        )
        (requirements_dir / "normalized_prd.md").write_text(
            "# Normalized PRD\n\n## Scope Boundaries\n\n- localStorage only\n- no database\n",
            encoding="utf-8",
        )
        (requirements_dir / "capability_boundary.json").write_text(
            json.dumps({"schema_version": 1, "unsupported_capabilities": [], "required_new_capabilities": [{"id": "local_todo"}]}),
            encoding="utf-8",
        )
        (run_dir / "context_pack.md").write_text("# Context Pack\n\nUse native SPA and Node stdlib.\n", encoding="utf-8")
        (run_dir / "app_contract.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "app_slug": "todo-prototype",
                    "target_stack": {"frontend": "native_spa", "backend": "node_stdlib", "storage": "localStorage", "database": "none"},
                    "generated_app_dir": "generated_apps/todo-prototype",
                    "required_files": ["server.js", "public/index.html", "public/styles.css", "public/app.js", "README.md"],
                    "verification_commands": ["node --check generated_apps/todo-prototype/server.js", "python3 -m unittest discover -s tests -v"],
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "acceptance_criteria.md").write_text("# Acceptance Criteria\n\n- `AC-001` Todo localStorage flow.\n", encoding="utf-8")
        (planning_dir / "acceptance_coverage_matrix.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "acceptance_criteria": [{"id": "AC-001", "description": "Todo localStorage flow.", "covering_slice_ids": ["slice-001"]}],
                    "slices": [{"id": "slice-001", "acceptance_criteria_ids": ["AC-001"], "verification_commands": ["node --check generated_apps/todo-prototype/server.js"]}],
                }
            ),
            encoding="utf-8",
        )
        (planning_dir / "tdd_plan.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "passed",
                    "test_cases": [{"id": "TDD-001", "acceptance_criteria_ids": ["AC-001"], "verification_command": "node --check generated_apps/todo-prototype/server.js"}],
                }
            ),
            encoding="utf-8",
        )
        (codex_dir / "implementation_trace.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "stage": "coder",
                    "status": "completed",
                    "current_step": "finalize_result",
                    "steps": [
                        {"id": "prepare_context", "title": "准备上下文", "status": "completed", "summary": "上下文已准备。"},
                        {"id": "codex_running", "title": "运行 Codex", "status": "completed", "summary": "应用代码已生成。"},
                    ],
                    "evidence": {
                        "changed_files": ["generated_apps/todo-prototype/server.js", "generated_apps/todo-prototype/public/app.js"],
                        "tests_run": ["node --check generated_apps/todo-prototype/server.js"],
                        "verification_commands": ["node --check generated_apps/todo-prototype/server.js"],
                        "diff_path": "codex/diff.patch",
                    },
                    "risk_events": [],
                    "blockers": [],
                    "next_action": "review",
                }
            ),
            encoding="utf-8",
        )
        (codex_dir / "diff.patch").write_text("diff --git a/generated_apps/todo-prototype/server.js b/generated_apps/todo-prototype/server.js\n", encoding="utf-8")
        (codex_dir / "stdout.jsonl").write_text(json.dumps({"event": "exec.completed"}) + "\n", encoding="utf-8")
        (codex_dir / "verification_record.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "completed",
                    "commands": [{"command": "node --check generated_apps/todo-prototype/server.js", "exit_code": 0}],
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "code_run_record.json").write_text(
            json.dumps({"executor": "codex", "files_changed": ["generated_apps/todo-prototype/server.js"], "provider": {"name": "default"}, "artifacts": {}}),
            encoding="utf-8",
        )
        (run_dir / "review_report.md").write_text("# Review\n\nNo blocking issues.\n", encoding="utf-8")
        (run_dir / "test_report.md").write_text("# Test\n\nnode --check generated_apps/todo-prototype/server.js\n", encoding="utf-8")
        (run_dir / "preview_instructions.md").write_text("cd generated_apps/todo-prototype\nnode server.js\n", encoding="utf-8")
        (run_dir / "final_report.md").write_text("# Final\n\ngenerated_apps/todo-prototype/server.js\n", encoding="utf-8")
        (worktree_app_dir / "server.js").write_text("console.log('todo');\n", encoding="utf-8")
        (worktree_app_dir / "README.md").write_text("# Todo Prototype\n", encoding="utf-8")
        (worktree_app_dir / "public" / "index.html").write_text("<main id=\"app\"></main>\n", encoding="utf-8")
        (worktree_app_dir / "public" / "styles.css").write_text("body { font-family: sans-serif; }\n", encoding="utf-8")
        (worktree_app_dir / "public" / "app.js").write_text("localStorage.setItem('todo', '[]');\n", encoding="utf-8")
        return run_dir

    def test_dashboard_state_serializes_run_without_secrets(self) -> None:
        from growth_dev.team.dashboard import build_dashboard_state
        from growth_dev.team.workspace import refresh_task_workspace

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            self._write_completed_run(runs_dir)
            refresh_task_workspace("dashboard-run-1", runs_dir=runs_dir)

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
        self.assertEqual(state["failure_classification"]["classification_decision"], "passed")
        self.assertEqual(state["requirement_understanding"]["candidate"]["model"], "gpt-5.3")
        self.assertEqual(state["requirement_understanding"]["quality_report"]["candidate_source"], "model")
        self.assertEqual(state["requirement_understanding"]["capability_boundary"]["change_type"], "extend_existing_capability")
        self.assertTrue(state["requirement_understanding"]["draft_artifacts"]["pm_prd_draft"])
        self.assertTrue(state["requirement_understanding"]["draft_artifacts"]["user_stories_draft"])
        self.assertTrue(state["requirement_understanding"]["draft_artifacts"]["prd_red_team"])
        self.assertEqual(state["tdd_plan"]["status"], "passed")
        self.assertEqual(state["memory_recall"]["matches"][0]["run_id"], "historical-dashboard-run")
        self.assertEqual(state["release_readiness"]["release_decision"], "ready_for_pr_ci")
        self.assertEqual(state["github_pr"]["status"], "created")
        self.assertEqual(state["ci_status"]["status"], "passed")
        self.assertEqual(state["staging_readiness"]["staging_decision"], "ready_for_staging")
        self.assertEqual(state["staging_rehearsal"]["status"], "completed")
        self.assertEqual(state["production_readiness"]["production_decision"], "ready_for_manual_production")
        self.assertEqual(state["task_workspace"]["loop_phase"], "finish")
        self.assertTrue(any(item["event"] == "run_completed" for item in state["task_journal"]["events"]))
        self.assertTrue(any(item["path"] == "codex/implementation_trace.json" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "codex/failure_classification.json" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "codex/failure_classification.md" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "requirements/requirement_quality_report.json" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "requirements/requirement_understanding.candidate.json" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "requirements/prd.draft.md" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "requirements/user_stories.draft.md" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "requirements/prd_red_team.md" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "requirements/capability_boundary.md" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "requirements/capability_boundary.json" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "planning/test_scenarios.draft.md" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "planning/tdd_plan.md" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "planning/tdd_plan.json" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "memory_recall.md" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "memory_recall.json" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "retrospective.md" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "learning_summary.json" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "finish_learning_suggestions.md" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "finish_learning_suggestions.json" for item in state["artifacts"]))
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
        self.assertTrue(any(item["path"] == "production_readiness.md" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "production_readiness.json" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "deployment_runbook.md" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "task_workspace.md" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "task_workspace.json" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "task_journal.md" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "task_journal.jsonl" for item in state["artifacts"]))
        self.assertTrue(any(item["path"] == "tool_context/codex.md" for item in state["artifacts"]))
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

    def test_dashboard_state_includes_app_generation_artifacts(self) -> None:
        from growth_dev.team.dashboard import build_dashboard_state

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "app-generation-dashboard"
            (run_dir / "requirements").mkdir(parents=True)
            record = {
                "run_id": "app-generation-dashboard",
                "team_id": "ai_native_engineering_team",
                "domain_id": "app_generation",
                "brief": "根据 PRD 生成本地应用：todo-prototype",
                "status": "completed",
                "run_dir": str(run_dir),
                "agent_runs": [],
                "gate_results": [
                    {
                        "gate_id": "complex_task_ready",
                        "status": "passed",
                        "required_artifacts": ["input_prd.md", "requirements/normalized_prd.md", "app_contract.json"],
                        "missing_artifacts": [],
                    }
                ],
                "artifacts": {},
                "risk_events": [],
            }
            (run_dir / "team_run_record.json").write_text(json.dumps(record), encoding="utf-8")
            (run_dir / "input_prd.md").write_text("# Todo PRD\n", encoding="utf-8")
            (run_dir / "requirements" / "normalized_prd.md").write_text("# 标准化 PRD\n", encoding="utf-8")
            (run_dir / "app_contract.json").write_text(json.dumps({"generated_app_dir": "generated_apps/todo-prototype"}), encoding="utf-8")
            (run_dir / "preview_instructions.md").write_text("node generated_apps/todo-prototype/server.js\n", encoding="utf-8")

            state = build_dashboard_state("app-generation-dashboard", runs_dir=runs_dir, repo_root=root)

        artifacts = {item["path"]: item for item in state["artifacts"]}
        for path in ("input_prd.md", "requirements/normalized_prd.md", "app_contract.json", "preview_instructions.md"):
            with self.subTest(path=path):
                self.assertIn(path, artifacts)
                self.assertTrue(artifacts[path]["exists"])

    def test_app_generation_workbench_lists_only_app_generation_runs(self) -> None:
        from growth_dev.team.dashboard import list_app_generation_runs

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            self._write_app_generation_workbench_run(runs_dir)
            self._write_completed_run(runs_dir, run_id="web-monitoring-run")

            runs = list_app_generation_runs(runs_dir)

        self.assertEqual([run["run_id"] for run in runs], ["app-generation-workbench"])
        self.assertEqual(runs[0]["domain_id"], "app_generation")
        self.assertEqual(runs[0]["app_slug"], "todo-prototype")
        self.assertEqual(runs[0]["comparison_group_id"], "cmp-todo-prototype")
        self.assertFalse(runs[0]["is_rerun"])

    def test_app_generation_workbench_nodes_expose_observable_contract(self) -> None:
        from growth_dev.team.dashboard import build_app_generation_nodes

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            self._write_app_generation_workbench_run(runs_dir)

            state = build_app_generation_nodes("app-generation-workbench", runs_dir=runs_dir, repo_root=root)

        expected_ids = [
            "skill_routing",
            "prd_input",
            "prd_normalization",
            "context_contract",
            "planning_tdd",
            "implementation",
            "review_quality",
            "verification",
            "preview_delivery",
        ]
        nodes = state["nodes"]
        self.assertEqual([node["id"] for node in nodes], expected_ids)
        self.assertEqual(state["run"]["app_slug"], "todo-prototype")
        for node in nodes:
            with self.subTest(node=node["id"]):
                for key in ("inputs", "process", "outputs", "skills", "tool_calls", "usage", "scores", "risks", "variants", "comparison"):
                    self.assertIn(key, node)
                self.assertTrue(any(skill["id"] for skill in node["skills"]))
                self.assertIn("rule", [variant["variant_id"] for variant in node["variants"]])
                self.assertIn("codex", [variant["variant_id"] for variant in node["variants"]])
        implementation = next(node for node in nodes if node["id"] == "implementation")
        variants = {variant["variant_id"]: variant for variant in implementation["variants"]}
        self.assertEqual(variants["rule"]["usage"]["total_tokens"], 0)
        self.assertEqual(variants["codex"]["usage"]["total_tokens"], "unknown")
        self.assertTrue(any(call["tool_name"] == "codex exec" for call in implementation["tool_calls"]))
        self.assertGreaterEqual(implementation["scores"]["engineering_readiness"], 0.8)
        app_js_output = next(item for item in implementation["outputs"] if item["path"].endswith("public/app.js"))
        self.assertFalse(app_js_output["preview"]["enabled"])
        self.assertEqual(app_js_output["preview"]["kind"], "missing")
        self.assertEqual(app_js_output["preview"]["size_bytes"], app_js_output["size_bytes"])

    def test_app_generation_node_exposes_phases_and_output_summary(self) -> None:
        """节点契约扩展：每个 node 必须带 phases + output_summary；implementation 节点 phases 复用 implementation_trace.steps。"""

        from growth_dev.team.dashboard import build_app_generation_nodes

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            self._write_app_generation_workbench_run(runs_dir)
            state = build_app_generation_nodes("app-generation-workbench", runs_dir=runs_dir, repo_root=root)

        nodes = {node["id"]: node for node in state["nodes"]}
        for node_id, node in nodes.items():
            with self.subTest(node=node_id):
                self.assertIn("phases", node)
                self.assertIsInstance(node["phases"], list)
                self.assertGreaterEqual(len(node["phases"]), 1)
                for phase in node["phases"]:
                    for key in ("id", "label", "status", "started_at", "finished_at", "summary", "artifacts"):
                        self.assertIn(key, phase)
                    self.assertIn(phase["status"], {"pending", "running", "completed", "failed"})
                self.assertIn("output_summary", node)
                summary = node["output_summary"]
                for key in ("total", "ready", "success", "warning", "error", "pending"):
                    self.assertIn(key, summary)
                self.assertEqual(
                    summary["success"] + summary["warning"] + summary["error"] + summary["pending"],
                    summary["total"],
                )

        impl_phases = nodes["implementation"]["phases"]
        impl_phase_ids = [phase["id"] for phase in impl_phases]
        self.assertIn("prepare_context", impl_phase_ids)
        self.assertIn("codex_running", impl_phase_ids)
        running_phase = next(phase for phase in impl_phases if phase["id"] == "codex_running")
        self.assertEqual(running_phase["status"], "completed")

    def test_app_generation_artifact_validation_status_reflects_existence_and_risks(self) -> None:
        """artifact validation_status：未生成→pending；存在且无 risk→success；存在且 risk severity=blocked→error。"""

        from growth_dev.team.dashboard import build_app_generation_nodes

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = self._write_app_generation_workbench_run(runs_dir)
            # 注入 agqs_score.json 触发 blocked risk，artifact_refs 关联 benchmark_diff.md / agqs_score.json
            (run_dir / "agqs_score.json").write_text(
                json.dumps({"schema_version": 1, "blocking_events": ["benchmark_parity_missing:cap_x"], "warnings": []}),
                encoding="utf-8",
            )
            (run_dir / "benchmark_diff.md").write_text("# Benchmark Diff\n", encoding="utf-8")
            state = build_app_generation_nodes("app-generation-workbench", runs_dir=runs_dir, repo_root=root)

        impl = next(node for node in state["nodes"] if node["id"] == "implementation")
        outputs_by_path = {ref["path"]: ref for ref in impl["outputs"]}
        # 存在 + 关联 blocked risk → error
        self.assertEqual(outputs_by_path["agqs_score.json"]["validation_status"], "error")
        self.assertEqual(outputs_by_path["benchmark_diff.md"]["validation_status"], "error")
        # 存在 + 无 risk → success
        diff_ref = outputs_by_path.get("codex/diff.patch")
        self.assertIsNotNone(diff_ref)
        self.assertEqual(diff_ref["validation_status"], "success")
        # output_summary 反映 error
        self.assertGreaterEqual(impl["output_summary"]["error"], 1)

    def test_app_generation_node_phases_fallback_to_artifact_existence_for_non_implementation_nodes(self) -> None:
        """非 implementation 节点：phase 状态根据模板 + 产物存在性推导（all exist→completed；部分→running；都缺→pending）。"""

        from growth_dev.team.dashboard import build_app_generation_nodes

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            self._write_app_generation_workbench_run(runs_dir)
            state = build_app_generation_nodes("app-generation-workbench", runs_dir=runs_dir, repo_root=root)

        planning = next(node for node in state["nodes"] if node["id"] == "planning_tdd")
        phase_status_by_id = {phase["id"]: phase["status"] for phase in planning["phases"]}
        # fixture 已写入 acceptance_criteria.md, planning/acceptance_coverage_matrix.json, planning/tdd_plan.json
        self.assertEqual(phase_status_by_id.get("acceptance"), "completed")
        self.assertEqual(phase_status_by_id.get("coverage_matrix"), "completed")
        self.assertEqual(phase_status_by_id.get("tdd_plan"), "completed")

    def test_app_generation_workbench_surfaces_benchmark_parity_artifacts(self) -> None:
        from growth_dev.team.dashboard import build_app_generation_nodes

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = self._write_app_generation_workbench_run(runs_dir)
            (run_dir / "benchmark_context.md").write_text("# Benchmark Context\n\n## Benchmark Parity\n", encoding="utf-8")
            (run_dir / "benchmark_context.json").write_text(json.dumps({"quality_mode": "benchmark_parity"}), encoding="utf-8")
            (run_dir / "benchmark_diff.md").write_text("# Benchmark Diff\n\n- missing: product_image_upload\n", encoding="utf-8")
            (run_dir / "agqs_score.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "overall_agqs": 66.67,
                        "hard_gate_status": "failed",
                        "capability_coverage": [
                            {"id": "product_image_upload", "label": "产品图上传", "status": "missing"},
                            {"id": "reference_image_upload", "label": "参考图上传", "status": "covered"},
                        ],
                        "blocking_events": ["benchmark_parity_missing:product_image_upload"],
                        "warnings": ["provider_setup_error_needs_manual_review"],
                    }
                ),
                encoding="utf-8",
            )

            state = build_app_generation_nodes("app-generation-workbench", runs_dir=runs_dir, repo_root=root)

        context_node = next(node for node in state["nodes"] if node["id"] == "context_contract")
        implementation = next(node for node in state["nodes"] if node["id"] == "implementation")
        output_paths = {item["path"] for item in implementation["outputs"]}
        context_paths = {item["path"] for item in context_node["outputs"]}
        risk_ids = {item["id"] for item in implementation["risks"]}

        self.assertIn("benchmark_context.md", context_paths)
        self.assertIn("benchmark_diff.md", output_paths)
        self.assertIn("agqs_score.json", output_paths)
        self.assertEqual(implementation["scores"]["benchmark_agqs"], 66.67)
        self.assertEqual(implementation["scores"]["benchmark_hard_gate"], "failed")
        self.assertIn("benchmark_parity_missing_product_image_upload", risk_ids)

    def test_app_generation_node_context_has_revision_and_action_contract(self) -> None:
        from growth_dev.team.dashboard import build_app_generation_node_context

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            self._write_app_generation_workbench_run(runs_dir)

            context = build_app_generation_node_context(
                "app-generation-workbench",
                "planning_tdd",
                selected_variant="codex",
                runs_dir=runs_dir,
                repo_root=root,
            )

        self.assertEqual(context["schema_version"], 1)
        self.assertEqual(context["run_id"], "app-generation-workbench")
        self.assertEqual(context["node_id"], "planning_tdd")
        self.assertEqual(context["selected_variant"], "codex")
        self.assertEqual(context["app_slug"], "todo-prototype")
        self.assertTrue(context["context_revision"].startswith("sha256:"))
        self.assertIn(context["context_revision"], context["context_id"])
        self.assertTrue(context["inputs"])
        self.assertTrue(context["outputs"])
        self.assertTrue(all(item["content_hash"].startswith("sha256:") or item["content_hash"] == "" for item in context["inputs"] + context["outputs"]))
        self.assertTrue(any(item["read_url"].startswith("/api/runs/app-generation-workbench/artifact") for item in context["outputs"] if item["read_url"]))
        self.assertFalse(any(item["path"].startswith(("worktree/", "generated_apps/", "codex/")) and item.get("preview", {}).get("enabled") for item in context["outputs"]))
        action_types = [action["type"] for action in context["available_actions"]]
        self.assertIn("explain_node", action_types)
        self.assertIn("compare_variants", action_types)
        self.assertIn("rerun_from_node", action_types)

    def test_app_generation_run_exposes_publish_status(self) -> None:
        from growth_dev.team.dashboard import build_app_generation_nodes

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            self._write_app_generation_workbench_run(runs_dir)
            published = runs_dir / "app-generation-workbench" / "generated_apps" / "todo-prototype"
            published.mkdir(parents=True)
            (published / "app_publish.json").write_text(
                json.dumps(
                    {
                        "app_slug": "todo-prototype",
                        "published_at": "2026-01-01T00:00:00Z",
                        "source_commit": "abc123",
                    }
                ),
                encoding="utf-8",
            )

            state = build_app_generation_nodes(
                "app-generation-workbench",
                runs_dir=runs_dir,
                repo_root=root,
            )

        self.assertEqual(state["run"]["publish_status"]["status"], "published")
        self.assertEqual(state["run"]["publish_status"]["app_slug"], "todo-prototype")
        self.assertEqual(state["run"]["publish_status"]["source_commit"], "abc123")

    def test_app_generation_artifact_preview_is_typed_and_path_confined(self) -> None:
        from growth_dev.team.dashboard import read_app_generation_artifact_preview

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            self._write_app_generation_workbench_run(runs_dir)
            artifact_path = runs_dir / "app-generation-workbench" / "artifacts" / "context_contract"
            artifact_path.mkdir(parents=True)
            (artifact_path / "app_contract.json").write_text(
                json.dumps({"app_slug": "todo-prototype"}), encoding="utf-8"
            )
            preview = read_app_generation_artifact_preview(
                "app-generation-workbench",
                "artifacts/context_contract/app_contract.json",
                runs_dir=runs_dir,
                repo_root=root,
            )
            (artifact_path / "pixel.png").write_bytes(
                b"\x89PNG\r\n\x1a\n"
            )
            image_preview = read_app_generation_artifact_preview(
                "app-generation-workbench",
                "artifacts/context_contract/pixel.png",
                runs_dir=runs_dir,
                repo_root=root,
            )

            with self.assertRaises(ValueError):
                read_app_generation_artifact_preview("app-generation-workbench", "../secret.txt", runs_dir=runs_dir, repo_root=root)
            with self.assertRaises(ValueError):
                read_app_generation_artifact_preview(
                    "app-generation-workbench",
                    "worktree/generated_apps/todo-prototype/public/app.js",
                    runs_dir=runs_dir,
                    repo_root=root,
                )

        self.assertEqual(preview["kind"], "code")
        self.assertEqual(preview["mime_type"], "application/json")
        self.assertIn("todo-prototype", preview["content"])
        self.assertEqual(image_preview["kind"], "image")
        self.assertTrue(image_preview["data_url"].startswith("data:image/png;base64,"))

    def test_app_generation_agent_bridge_uses_node_context_and_handles_unconfigured_pi_agent(self) -> None:
        from growth_dev.team.dashboard import build_app_generation_node_context, handle_app_generation_agent_message

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            self._write_app_generation_workbench_run(runs_dir)
            context = build_app_generation_node_context(
                "app-generation-workbench",
                "planning_tdd",
                selected_variant="codex",
                runs_dir=runs_dir,
                repo_root=root,
            )

            codex_response = handle_app_generation_agent_message(
                {
                    "provider": "codex",
                    "mode": "compare",
                    "message": "对比 rule 和 codex 在这个节点的输出。",
                    "node_context": context,
                },
                runs_dir=runs_dir,
                repo_root=root,
            )
            with mock.patch.dict("os.environ", {}, clear=True):
                pi_response = handle_app_generation_agent_message(
                    {
                        "provider": "pi_agent",
                        "mode": "explain",
                        "message": "解释当前节点。",
                        "node_context": context,
                    },
                    runs_dir=runs_dir,
                    repo_root=root,
                )

        self.assertEqual(codex_response["provider"], "codex")
        self.assertEqual(codex_response["status"], "completed")
        self.assertTrue(any(action["type"] == "compare_variants" for action in codex_response["actions"]))
        self.assertEqual(codex_response["usage"]["total_tokens"], "unknown")
        self.assertEqual(pi_response["provider"], "pi_agent")
        self.assertEqual(pi_response["status"], "not_configured")
        self.assertIn("PI-Agent", pi_response["message"])

    def test_app_generation_agent_stream_yields_codex_agent_end_event(self) -> None:
        from growth_dev.team.dashboard import (
            build_app_generation_node_context,
            stream_app_generation_agent_message,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            self._write_app_generation_workbench_run(runs_dir)
            context = build_app_generation_node_context(
                "app-generation-workbench",
                "planning_tdd",
                selected_variant="codex",
                runs_dir=runs_dir,
                repo_root=root,
            )
            events = list(
                stream_app_generation_agent_message(
                    {
                        "provider": "codex",
                        "mode": "explain",
                        "message": "解释当前节点",
                        "node_context": context,
                    },
                    runs_dir=runs_dir,
                    repo_root=root,
                )
            )

        types = [event.get("type") for event in events]
        self.assertEqual(types, ["agent_end"])
        agent_end_payload = events[0]["payload"]
        self.assertEqual(agent_end_payload["provider"], "codex")
        self.assertEqual(agent_end_payload["status"], "completed")
        self.assertTrue(any(a["type"] == "explain_node" for a in agent_end_payload["actions"]))

    def test_app_generation_agent_stream_uses_interaction_context_for_artifact_actions(self) -> None:
        from growth_dev.team.dashboard import (
            build_app_generation_node_context,
            stream_app_generation_agent_message,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            self._write_app_generation_workbench_run(runs_dir)
            context = build_app_generation_node_context(
                "app-generation-workbench",
                "planning_tdd",
                selected_variant="codex",
                runs_dir=runs_dir,
                repo_root=root,
            )
            events = list(
                stream_app_generation_agent_message(
                    {
                        "provider": "codex",
                        "intent": "auto",
                        "mode": "explain",
                        "message": "这个中间产物是否需要重跑？",
                        "node_context": context,
                        "interaction_context": {
                            "context_revision": context["context_revision"],
                            "focus": {
                                "card": "artifact_preview",
                                "artifact_ref": "planning/tdd_plan.json",
                                "selected_text": "mobile empty state",
                                "view_mode": "artifact_preview",
                            },
                            "allowed_operations": ["explain", "read_artifact", "suggest_artifact_regeneration"],
                        },
                    },
                    runs_dir=runs_dir,
                    repo_root=root,
                )
            )

        self.assertEqual([event.get("type") for event in events], ["agent_end"])
        actions = events[0]["payload"]["actions"]
        action_types = [action["type"] for action in actions]
        self.assertIn("read_artifact", action_types)
        self.assertIn("suggest_artifact_regeneration", action_types)

    def test_app_generation_agent_stream_emits_upstream_error_for_not_configured_pi(self) -> None:
        from growth_dev.team.dashboard import (
            build_app_generation_node_context,
            stream_app_generation_agent_message,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            self._write_app_generation_workbench_run(runs_dir)
            context = build_app_generation_node_context(
                "app-generation-workbench",
                "planning_tdd",
                selected_variant="codex",
                runs_dir=runs_dir,
                repo_root=root,
            )
            with mock.patch.dict("os.environ", {"PATH": "/nonexistent"}, clear=False):
                with mock.patch("shutil.which", return_value=None):
                    events = list(
                        stream_app_generation_agent_message(
                            {
                                "provider": "pi_agent",
                                "mode": "explain",
                                "message": "解释当前节点",
                                "node_context": context,
                            },
                            runs_dir=runs_dir,
                            repo_root=root,
                        )
                    )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "upstream_error")
        self.assertEqual(events[0]["payload"]["phase"], "not_configured")

    def test_app_generation_agent_stream_routes_pi_provider_through_fake_subprocess(self) -> None:
        import json as _json
        import threading
        import time
        from growth_dev.team import agent_bridge
        from growth_dev.team.dashboard import (
            build_app_generation_node_context,
            stream_app_generation_agent_message,
        )
        from tests.test_agent_bridge_pi_rpc import (
            FakeProcess,
            _agent_end,
            _text_delta,
            _tool_end,
            _tool_start,
        )

        fake_proc = FakeProcess()

        def launcher(cmd, env, cwd):
            return fake_proc

        def ready_probe(**_kwargs):
            return {
                "provider": "pi_agent",
                "status": "ready",
                "message": "fake pi ready",
                "capabilities": ["chat", "tool_calls", "stream"],
            }

        pi_provider = agent_bridge.PiAgentProvider(
            subprocess_launcher=launcher, status_probe=ready_probe
        )
        agent_bridge.register_provider_singleton("pi_agent", pi_provider)
        self.addCleanup(agent_bridge.reset_provider_singletons)

        def producer() -> None:
            time.sleep(0.05)
            fake_proc.emit(_text_delta("hi"))
            fake_proc.emit(_tool_start("t1", "read", {"path": "x"}))
            fake_proc.emit(_tool_end("t1", "ok", is_error=False))
            fake_proc.emit(_agent_end(usage={"total_tokens": 42}))

        threading.Thread(target=producer, daemon=True).start()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            self._write_app_generation_workbench_run(runs_dir)
            context = build_app_generation_node_context(
                "app-generation-workbench",
                "planning_tdd",
                selected_variant="codex",
                runs_dir=runs_dir,
                repo_root=root,
            )
            with mock.patch(
                "growth_dev.team.dashboard._app_generation_provider_statuses",
                return_value=[ready_probe(), {"provider": "codex", "status": "ready"}],
            ):
                events = list(
                    stream_app_generation_agent_message(
                        {
                            "provider": "pi_agent",
                            "mode": "explain",
                            "message": "请读一个文件",
                            "node_context": context,
                        },
                        runs_dir=runs_dir,
                        repo_root=root,
                    )
                )

        types = [e["type"] for e in events]
        self.assertIn("message_delta", types)
        self.assertIn("tool_call", types)
        self.assertIn("tool_result", types)
        self.assertEqual(types[-1], "agent_end")
        agent_end = events[-1]
        self.assertEqual(agent_end["payload"]["usage"]["total_tokens"], 42)

    def test_app_generation_agent_stream_does_not_duplicate_pi_stream_closed_error(self) -> None:
        import json as _json
        import threading
        import time
        from growth_dev.team import agent_bridge
        from growth_dev.team.dashboard import (
            build_app_generation_node_context,
            stream_app_generation_agent_message,
        )
        from tests.test_agent_bridge_pi_rpc import FakeProcess, _text_delta

        fake_proc = FakeProcess()

        def launcher(cmd, env, cwd):
            return fake_proc

        def ready_probe(**_kwargs):
            return {
                "provider": "pi_agent",
                "status": "ready",
                "message": "fake pi ready",
                "capabilities": ["chat", "tool_calls", "stream"],
            }

        pi_provider = agent_bridge.PiAgentProvider(
            subprocess_launcher=launcher, status_probe=ready_probe
        )
        agent_bridge.register_provider_singleton("pi_agent", pi_provider)
        self.addCleanup(agent_bridge.reset_provider_singletons)

        def producer() -> None:
            time.sleep(0.05)
            fake_proc.emit(_text_delta("partial"))
            fake_proc.close_stdout()

        threading.Thread(target=producer, daemon=True).start()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            self._write_app_generation_workbench_run(runs_dir)
            context = build_app_generation_node_context(
                "app-generation-workbench",
                "planning_tdd",
                selected_variant="codex",
                runs_dir=runs_dir,
                repo_root=root,
            )
            with mock.patch(
                "growth_dev.team.dashboard._app_generation_provider_statuses",
                return_value=[ready_probe(), {"provider": "codex", "status": "ready"}],
            ):
                events = list(
                    stream_app_generation_agent_message(
                        {
                            "provider": "pi_agent",
                            "mode": "explain",
                            "message": "请继续",
                            "node_context": context,
                        },
                        runs_dir=runs_dir,
                        repo_root=root,
                    )
                )

        types = [e["type"] for e in events]
        self.assertIn("message_delta", types)
        self.assertEqual(types.count("upstream_error"), 1)
        self.assertEqual(events[-1]["payload"]["phase"], "stream_closed")

    def test_app_generation_rerun_creates_new_run_without_mutating_source(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, build_app_generation_node_context, start_app_generation_rerun

        class FakeProcess:
            pid = 9876

            def wait(self, timeout: float | None = None) -> int:
                return 0

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            repo_root = Path(__file__).resolve().parents[1]
            source_dir = self._write_app_generation_workbench_run(runs_dir)
            source_record_before = (source_dir / "team_run_record.json").read_text(encoding="utf-8")
            context = build_app_generation_node_context(
                "app-generation-workbench",
                "planning_tdd",
                selected_variant="codex",
                runs_dir=runs_dir,
                repo_root=root,
            )

            with mock.patch("growth_dev.team.dashboard.subprocess.Popen", return_value=FakeProcess()):
                result = start_app_generation_rerun(
                    DashboardConfig(
                        runs_dir=runs_dir,
                        domains_dir=repo_root / "domains",
                        repo_root=repo_root,
                        dashboard_dir=repo_root / "dashboard",
                        executor="codex",
                    ),
                    {
                        "source_run_id": "app-generation-workbench",
                        "rerun_from_node": "planning_tdd",
                        "selected_variant": "codex",
                        "context_revision": context["context_revision"],
                        "override_instructions": "增加移动端空状态验收。",
                    },
                )

            process = json.loads((runs_dir / result["run_id"] / "process.json").read_text(encoding="utf-8"))
            command = process["command"]
            inputs = json.loads(command[command.index("--inputs-json") + 1])
            source_record_after = (source_dir / "team_run_record.json").read_text(encoding="utf-8")

        self.assertNotEqual(result["run_id"], "app-generation-workbench")
        self.assertEqual(result["source_run_id"], "app-generation-workbench")
        self.assertEqual(result["rerun_from_node"], "planning_tdd")
        self.assertEqual(inputs["source_run_id"], "app-generation-workbench")
        self.assertEqual(inputs["rerun_from_node"], "planning_tdd")
        self.assertEqual(inputs["selected_variant"], "codex")
        self.assertEqual(inputs["comparison_group_id"], "cmp-todo-prototype")
        self.assertIn("增加移动端空状态验收", inputs["override_instructions"])
        self.assertIn("Workbench Override Instructions", inputs["prd_text"])
        self.assertEqual(source_record_before, source_record_after)

    def test_start_app_generation_run_writes_inputs_and_invokes_cli_with_executor(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, start_app_generation_run

        class FakeProcess:
            pid = 4242

            def wait(self, timeout: float | None = None) -> int:
                return 0

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            repo_root = Path(__file__).resolve().parents[1]
            captured: dict[str, Any] = {}

            def fake_popen(command, **kwargs):
                captured["command"] = list(command)
                captured["cwd"] = str(kwargs.get("cwd") or "")
                return FakeProcess()

            with mock.patch("growth_dev.team.dashboard.subprocess.Popen", side_effect=fake_popen):
                result = start_app_generation_run(
                    DashboardConfig(
                        runs_dir=runs_dir,
                        domains_dir=repo_root / "domains",
                        repo_root=repo_root,
                        dashboard_dir=repo_root / "dashboard",
                        executor="codex",
                    ),
                    {
                        "prd_text": "# Todo App\n\n用户可以添加、完成和删除待办事项。",
                        "prd_filename": "todo-app.md",
                        "executor": "llm",
                    },
                )

            run_id = result["run_id"]
            process = json.loads((runs_dir / run_id / "process.json").read_text(encoding="utf-8"))
            command = captured["command"]
            inputs = json.loads(command[command.index("--inputs-json") + 1])
            executor_arg = command[command.index("--executor") + 1]
            domain_arg = command[command.index("--domain") + 1]

        self.assertTrue(run_id.startswith("app_generation-"))
        self.assertEqual(result["executor"], "llm")
        self.assertEqual(executor_arg, "llm")
        self.assertEqual(domain_arg, "app_generation")
        self.assertEqual(result["app_slug"], "todo-app")
        self.assertEqual(result["comparison_group_id"], "cmp-todo-app")
        self.assertEqual(inputs["app_slug"], "todo-app")
        self.assertEqual(inputs["prd_text"], "# Todo App\n\n用户可以添加、完成和删除待办事项。")
        self.assertEqual(inputs["comparison_group_id"], "cmp-todo-app")
        self.assertEqual(inputs["prd_filename"], "todo-app.md")
        self.assertIn(process["status"], {"starting", "running"})

    def test_start_app_generation_run_rejects_missing_prd_and_bad_executor(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, start_app_generation_run

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cfg = DashboardConfig(
                runs_dir=root / "runs",
                domains_dir=root / "domains",
                repo_root=root,
                dashboard_dir=root / "dashboard",
                executor="codex",
            )
            with self.assertRaises(ValueError):
                start_app_generation_run(cfg, {"prd_text": "   "})
            with self.assertRaises(ValueError):
                start_app_generation_run(cfg, {"prd_text": "ok", "executor": "vibe-coding"})

    def test_stream_app_generation_run_events_yields_snapshot_then_run_finished_for_completed_run(self) -> None:
        from growth_dev.team.dashboard import stream_app_generation_run_events

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            self._write_app_generation_workbench_run(runs_dir)
            events = list(
                stream_app_generation_run_events(
                    "app-generation-workbench",
                    runs_dir=runs_dir,
                    repo_root=root,
                    poll_interval=0,
                    max_iterations=1,
                )
            )

        self.assertGreaterEqual(len(events), 2)
        self.assertEqual(events[0]["type"], "snapshot")
        self.assertEqual(events[0]["payload"]["run"]["run_id"], "app-generation-workbench")
        self.assertEqual(len(events[0]["payload"]["nodes"]), 9)
        self.assertEqual(events[-1]["type"], "run_finished")
        self.assertEqual(events[-1]["payload"]["status"], "completed")

    def test_stream_app_generation_run_events_emits_node_state_diff_when_status_changes(self) -> None:
        from growth_dev.team import dashboard as dashboard_module

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "in-flight-run"
            run_dir.mkdir(parents=True)
            (run_dir / "team_run_record.json").write_text(
                json.dumps({"run_id": "in-flight-run", "domain_id": "app_generation", "status": "running"}),
                encoding="utf-8",
            )

            snapshots = [
                {
                    "run": {"run_id": "in-flight-run", "status": "running"},
                    "nodes": [
                        {"id": "prd_input", "status": "completed", "outputs": [], "risks": [], "selected_variant": "rule"},
                        {"id": "implementation", "status": "running", "outputs": [], "risks": [], "selected_variant": "codex"},
                    ],
                },
                {
                    "run": {"run_id": "in-flight-run", "status": "running"},
                    "nodes": [
                        {"id": "prd_input", "status": "completed", "outputs": [], "risks": [], "selected_variant": "rule"},
                        {"id": "implementation", "status": "completed", "outputs": [{"path": "codex/diff.patch"}], "risks": [], "selected_variant": "codex"},
                    ],
                },
                {
                    "run": {"run_id": "in-flight-run", "status": "completed"},
                    "nodes": [
                        {"id": "prd_input", "status": "completed", "outputs": [], "risks": [], "selected_variant": "rule"},
                        {"id": "implementation", "status": "completed", "outputs": [], "risks": [], "selected_variant": "codex"},
                    ],
                },
            ]
            call_seq = iter(snapshots)

            def fake_build(run_id: str, *, runs_dir: Path, repo_root: Path) -> dict:
                return next(call_seq)

            with mock.patch.object(dashboard_module, "build_app_generation_nodes", side_effect=fake_build):
                events = list(
                    dashboard_module.stream_app_generation_run_events(
                        "in-flight-run",
                        runs_dir=runs_dir,
                        repo_root=root,
                        poll_interval=0,
                        max_iterations=4,
                    )
                )

        types = [e["type"] for e in events]
        self.assertEqual(types[0], "snapshot")
        node_state_events = [e for e in events if e["type"] == "node_state"]
        self.assertEqual(len(node_state_events), 1)
        self.assertEqual(node_state_events[0]["payload"]["node_id"], "implementation")
        self.assertEqual(node_state_events[0]["payload"]["status"], "completed")
        self.assertEqual(types[-1], "run_finished")
        self.assertEqual(events[-1]["payload"]["status"], "completed")

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

            with mock.patch("growth_dev.team.dashboard.generate_production_readiness") as production_mock:
                production_mock.return_value = {"production_decision": "ready_for_manual_production"}
                request = handler.__new__(handler)
                request.path = "/api/runs/dashboard-run-1/production-readiness"
                request._send_json = mock.Mock()
                request.do_POST()
                production_payload = request._send_json.call_args.args[0]

        self.assertEqual(draft_payload["status"], "created")
        self.assertEqual(status_payload["status"], "passed")
        self.assertEqual(staging_payload["staging_decision"], "ready_for_staging")
        self.assertEqual(rehearsal_payload["status"], "completed")
        self.assertEqual(production_payload["production_decision"], "ready_for_manual_production")

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
        self.assertLess(html.index('id="flow-node-detail"'), html.index('class="request-panel"'))
        self.assertIn('id="flow-nodes"', html)
        self.assertIn('id="flow-node-detail"', html)
        self.assertIn('id="flow-artifact-actions"', html)
        self.assertIn('id="flow-artifact-preview"', html)
        self.assertIn('id="flow-engineering-evidence"', html)
        self.assertNotIn('class="summary-band"', html)
        self.assertNotIn('id="current-task"', html)
        self.assertNotIn('id="task-headline"', html)
        self.assertNotIn('id="status-pill"', html)

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

    def test_dashboard_html_exposes_prd_app_generation_mode(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "dashboard" / "index.html").read_text(encoding="utf-8")
        i18n = json.loads((root / "dashboard" / "i18n" / "zh-CN.json").read_text(encoding="utf-8"))

        self.assertIn('id="request-mode"', html)
        self.assertIn('value="app_generation"', html)
        self.assertIn('id="app-slug"', html)
        self.assertIn("requestModeLabel", i18n["app"])
        self.assertIn("appSlugLabel", i18n["app"])

    def test_dashboard_exposes_app_generation_workbench_entry(self) -> None:
        root = Path(__file__).resolve().parents[1]
        index_html = (root / "dashboard" / "index.html").read_text(encoding="utf-8")
        page_html = (root / "dashboard" / "app_generation.html").read_text(encoding="utf-8")
        page_js = (root / "dashboard" / "app_generation.js").read_text(encoding="utf-8")
        page_css = (root / "dashboard" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('href="/app_generation.html"', index_html)
        self.assertIn("PRD生成应用", index_html)
        for token in (
            'id="app-generation-workbench"',
            'id="app-generation-task-list"',
            'id="app-generation-node-workspace"',
            'id="app-generation-node-list"',
            'id="app-generation-node-detail"',
            'id="app-generation-skill-routing"',
            'id="app-generation-preview-rail"',
            'id="app-generation-preview-content"',
            'id="app-generation-agent-panel"',
            'id="app-generation-provider"',
            'id="app-generation-rerun"',
        ):
            self.assertIn(token, page_html)
        self.assertLess(page_html.index('id="app-generation-node-workspace"'), page_html.index('id="app-generation-preview-rail"'))
        self.assertLess(page_html.index('id="app-generation-preview-rail"'), page_html.index('id="app-generation-agent-panel"'))
        for token in (
            "/api/app-generation/runs",
            "/api/app-generation/runs/",
            "/api/app-generation/rerun",
            "/api/app-generation/agent/message",
            "buildAgentInteractionContext",
            "interaction_context",
            "handleAgentAction",
            "read_artifact",
            "suggest_artifact_regeneration",
            "context_revision",
            "selectedVariant",
            "localStorage",
            "previewRequestSeq",
            'event.key === "Escape"',
            "BUSINESS_NODE_TITLES",
            "DETAIL_CARD_TITLES",
            "openArtifactPreview",
            "输入 Token",
            "未记录",
        ):
            self.assertIn(token, page_js)
        for token in (
            ".app-generation-workbench",
            ".app-generation-task-list",
            ".app-generation-node-workspace",
            ".app-generation-shell {",
            "display: flex",
            "overflow-x: auto",
            "flex: 0 0 clamp(260px, 24vw, 320px)",
            "flex: 1 1 clamp(720px, 52vw, 1000px)",
            "flex: 0 0 clamp(300px, 24vw, 360px)",
            "flex: 0 0 clamp(320px, 26vw, 380px)",
            ".app-generation-preview-rail[hidden]",
            "display: none !important",
            ".app-generation-agent-panel",
            ".app-generation-preview-rail",
            ".app-generation-detail-card",
            ".app-generation-node-card",
            ".app-generation-node-detail",
            "overflow-wrap: anywhere",
        ):
            self.assertIn(token, page_css)

    def test_dashboard_frontend_builds_app_generation_payload_from_prd_mode(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "dashboard" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function buildRunPayload", app_js)
        self.assertIn('mode === "app_generation"', app_js)
        self.assertIn('domain: "app_generation"', app_js)
        self.assertIn("inputs_json: { app_slug: appSlug, prd_text: prdText }", app_js)
        self.assertIn("根据 PRD 生成本地应用：", app_js)

    def test_app_generation_frontend_does_not_auto_publish_on_preview_start(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = (root / "dashboard" / "app_generation.js").read_text(encoding="utf-8")
        html = (root / "dashboard" / "app_generation.html").read_text(encoding="utf-8")
        start_fn = script[
            script.index("async function startAppPreviewFromUI") : script.index("async function stopAppPreviewFromUI")
        ]

        self.assertNotIn("await publishAppFromUI(runId)", start_fn)
        self.assertNotIn("未发布，正在先发布再启动", start_fn)
        self.assertIn('id="app-generation-preview-btn" type="button" class="primary small" disabled', html)
        self.assertIn("function renderPreviewControls", script)
        self.assertIn('previewBtn.disabled = !state.selectedRunId || !isPublished', script)
        self.assertIn('publishStatus.status !== "published"', start_fn)

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
        self.assertIn(".flow-main {\n  display: grid;\n  grid-template-rows: minmax(0, 1fr) auto;", css)
        self.assertIn(".request-panel {\n  position: sticky;", css)

    def test_dashboard_task_records_are_compact_and_flow_detail_is_pinned(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "dashboard" / "app.js").read_text(encoding="utf-8")
        css = (root / "dashboard" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("function taskRecordSummary", app_js)
        self.assertIn("function truncateTaskSummary", app_js)
        self.assertIn("（...）", app_js)
        self.assertIn('title.className = "task-card-title"', app_js)
        self.assertIn("button.title = run.brief || run.run_id || \"\";", app_js)
        self.assertIn(".task-card-title", css)
        self.assertIn(".flow-detail-header {\n  position: sticky;", css)

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
        self.assertIn('id="production-readiness-action"', html)
        self.assertIn("renderStagingReadiness", app_js)
        self.assertIn("renderStagingRehearsal", app_js)
        self.assertIn("renderProductionReadiness", app_js)
        self.assertIn("startStagingReadiness", app_js)
        self.assertIn("startStagingRehearsal", app_js)
        self.assertIn("startProductionReadiness", app_js)
        self.assertIn('/staging-readiness"', app_js)
        self.assertIn('/staging-rehearsal"', app_js)
        self.assertIn('/production-readiness"', app_js)
        self.assertIn("stagingReadiness", i18n)
        self.assertIn("stagingRehearsal", i18n)
        self.assertIn("productionReadiness", i18n)
        for key in ("title", "generateButton", "empty", "decision", "gates", "nextActions"):
            self.assertIn(key, i18n["stagingReadiness"])
        for key in ("title", "runButton", "empty", "status", "logs", "nextActions"):
            self.assertIn(key, i18n["stagingRehearsal"])
        for key in ("title", "generateButton", "empty", "decision", "gates", "nextActions"):
            self.assertIn(key, i18n["productionReadiness"])
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
            "requirement_understanding": {
                "brief_analysis": {"complexity": "complex", "planning_mode": "llm_assisted", "llm_draft_requested": True},
                "candidate": {"candidate_source": "model", "model": "gpt-5.3", "validation": {"status": "passed"}},
                "quality_report": {
                    "status": "passed",
                    "summary": "Requirement understanding is ready for planning.",
                    "candidate_source": "model",
                    "requirements_model": "gpt-5.3",
                    "candidate_validation": {"status": "passed"},
                    "blockers": [],
                    "warnings": [],
                },
            },
            "apply_gate": {"status": "passed", "reason": "ready"},
            "artifacts": [
                {"label": "Task Package", "path": "task.yaml", "scope": "run", "exists": True},
                {"label": "PRD", "path": "prd.md", "scope": "run", "exists": True},
                {"label": "Architecture Diagram", "path": "architecture_diagram.md", "scope": "run", "exists": False},
                {"label": "Implementation Trace", "path": "codex/implementation_trace.json", "scope": "run", "exists": True},
                {"label": "Failure Classification", "path": "codex/failure_classification.json", "scope": "run", "exists": True},
                {"label": "Diff Evidence", "path": "codex/diff.patch", "scope": "run", "exists": True},
                {"label": "Task Workspace", "path": "task_workspace.md", "scope": "run", "exists": True},
                {"label": "Task Journal", "path": "task_journal.md", "scope": "run", "exists": True},
                {"label": "Codex Tool Context", "path": "tool_context/codex.md", "scope": "run", "exists": True},
            ],
            "task_workspace": {
                "loop_phase": "finish",
                "current_focus": "Run is completed; review finish artifacts and next release gates.",
                "next_actions": ["生成发布准备判断"],
                "slices": {"active": None, "completed": [{"id": "slice-001"}], "pending": [], "blocked": []},
                "verification_commands": ["python3 -m unittest tests.test_dashboard -v"],
            },
            "task_journal": {
                "events": [
                    {"loop_phase": "finish", "event": "run_completed", "status": "completed", "summary": "Run completed."},
                    {"loop_phase": "implement", "event": "slice_loop_observed", "status": "available", "summary": "Slice loop observed."},
                ]
            },
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
            ["requirement", "design", "implementation", "quality", "delivery", "release", "github_pr_ci", "staging", "production"],
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
        self.assertEqual(vm["requirementUnderstanding"]["candidateSource"], "model")
        self.assertEqual(vm["requirementUnderstanding"]["requirementsModel"], "gpt-5.3")
        self.assertEqual(vm["requirementUnderstanding"]["candidateValidationStatus"], "passed")
        self.assertEqual(vm["memoryRecall"]["matches"][0]["run_id"], "similar-run")
        self.assertEqual(vm["memoryRecall"]["recommendedSkills"][0]["id"], "context_engineering")
        design_stage = vm["stages"][1]
        implementation_stage = vm["stages"][2]
        self.assertEqual(design_stage["agentIds"], ["product", "architect", "ux", "qa"])
        self.assertTrue(any(artifact["path"] == "prd.md" for artifact in design_stage["artifacts"]))
        self.assertTrue(any(artifact["path"] == "codex/implementation_trace.json" for artifact in implementation_stage["artifacts"]))
        self.assertTrue(any(artifact["path"] == "codex/failure_classification.json" for artifact in implementation_stage["artifacts"]))
        self.assertTrue(any(artifact["path"] == "codex/diff.patch" for artifact in implementation_stage["artifacts"]))
        self.assertTrue(any(artifact["path"] == "tool_context/codex.md" for artifact in implementation_stage["artifacts"]))
        self.assertEqual(design_stage["artifacts"][0]["title"], "PRD")
        self.assertIn("代码差异", {artifact["title"] for artifact in implementation_stage["artifacts"]})
        delivery_node = vm["flowNodes"][4]
        release_node = vm["flowNodes"][5]
        github_node = vm["flowNodes"][6]
        staging_node = vm["flowNodes"][7]
        production_node = vm["flowNodes"][8]
        self.assertEqual(delivery_node["status"], "waiting_confirmation")
        self.assertTrue(any(action["id"] == "acceptance" for action in delivery_node["actions"]))
        self.assertTrue(any(artifact["path"] == "final_report.md" for artifact in delivery_node["artifacts"]))
        self.assertTrue(any(artifact["path"] == "task_workspace.md" for artifact in delivery_node["artifacts"]))
        self.assertIn("当前关注", "\n".join(delivery_node["insights"]))
        self.assertTrue(any(action["id"] == "release_readiness" for action in release_node["actions"]))
        self.assertTrue(any(action["id"] == "github_pr" for action in github_node["actions"]))
        self.assertTrue(any(action["id"] == "github_ci" for action in github_node["actions"]))
        self.assertTrue(any(action["id"] == "staging_readiness" for action in staging_node["actions"]))
        self.assertTrue(any(action["id"] == "staging_rehearsal" for action in staging_node["actions"]))
        self.assertTrue(any(action["id"] == "production_readiness" for action in production_node["actions"]))
        self.assertIn("engineeringEvidence", vm["flowNodes"][2])
        self.assertTrue(vm["flowNodes"][2]["engineeringEvidence"]["events"])
        self.assertTrue(vm["flowNodes"][2]["engineeringEvidence"]["journalEvents"])

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
        self.assertEqual(vm["requirementUnderstanding"]["candidateSource"], "deterministic_only")
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

    def test_publish_app_copies_worktree_to_generated_apps_with_record(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, publish_app_generation_run

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = self._write_app_generation_workbench_run(runs_dir, "app-gen-001")
            worktree_app = run_dir / "worktree" / "generated_apps" / "todo-prototype"
            (worktree_app / "updated.txt").write_text("updated content\n", encoding="utf-8")

            result = publish_app_generation_run(
                DashboardConfig(
                    runs_dir=runs_dir,
                    domains_dir=root / "domains",
                    repo_root=root,
                    dashboard_dir=root / "dashboard",
                    executor="codex",
                ),
                {"run_id": "app-gen-001"},
            )

            published_dir = run_dir / "generated_apps" / "todo-prototype"
            publish_record_path = published_dir / "app_publish.json"

            self.assertEqual(result["app_slug"], "todo-prototype")
            self.assertIn("published_at", result)
            self.assertGreater(result["files_count"], 0)
            self.assertTrue(published_dir.exists())
            self.assertTrue(publish_record_path.exists())
            self.assertTrue((published_dir / "updated.txt").exists())
            self.assertEqual((published_dir / "updated.txt").read_text(encoding="utf-8"), "updated content\n")
            publish_record = json.loads(publish_record_path.read_text(encoding="utf-8"))
            self.assertEqual(publish_record["app_slug"], "todo-prototype")
            self.assertIn("published_at", publish_record)
            self.assertEqual(publish_record["files_count"], result["files_count"])
            self.assertEqual(publish_record["worktree_path"], "worktree/generated_apps/todo-prototype")
            self.assertIn("source_commit", publish_record)
            self.assertIn("worktree_clean", publish_record)

    def test_publish_app_rejects_incomplete_implementation(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, publish_app_generation_run

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = self._write_app_generation_workbench_run(runs_dir, "app-gen-incomplete")
            record_path = run_dir / "team_run_record.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            for agent_run in record["agent_runs"]:
                if agent_run.get("agent_id") == "coder":
                    agent_run["status"] = "failed"
            record_path.write_text(json.dumps(record), encoding="utf-8")

            with self.assertRaises(ValueError) as ctx:
                publish_app_generation_run(
                    DashboardConfig(
                        runs_dir=runs_dir,
                        domains_dir=root / "domains",
                        repo_root=root,
                        dashboard_dir=root / "dashboard",
                        executor="codex",
                    ),
                    {"run_id": "app-gen-incomplete"},
                )

        self.assertIn("implementation_not_complete", str(ctx.exception))

    def test_publish_app_returns_multiple_apps_found_when_ambiguous(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, publish_app_generation_run

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "app-gen-002"
            (run_dir / "worktree" / "generated_apps" / "app-a").mkdir(parents=True)
            (run_dir / "worktree" / "generated_apps" / "app-b").mkdir(parents=True)
            (run_dir / "worktree" / "generated_apps" / "app-a" / "file.txt").write_text("a", encoding="utf-8")
            (run_dir / "worktree" / "generated_apps" / "app-b" / "file.txt").write_text("b", encoding="utf-8")

            with self.assertRaises(ValueError) as ctx:
                publish_app_generation_run(
                    DashboardConfig(
                        runs_dir=runs_dir,
                        domains_dir=root / "domains",
                        repo_root=root,
                        dashboard_dir=root / "dashboard",
                        executor="codex",
                    ),
                    {"run_id": "app-gen-002"},
                )

        self.assertIn("multiple_apps_found", str(ctx.exception))

    def test_start_preview_rejects_unpublished_run_with_412(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, start_app_generation_preview

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = self._write_app_generation_workbench_run(runs_dir, "app-gen-003")

            with self.assertRaises(ValueError) as ctx:
                start_app_generation_preview(
                    DashboardConfig(
                        runs_dir=runs_dir,
                        domains_dir=root / "domains",
                        repo_root=root,
                        dashboard_dir=root / "dashboard",
                        executor="codex",
                    ),
                    {"run_id": "app-gen-003"},
                )

        self.assertIn("app_not_published", str(ctx.exception))

    def test_start_preview_invokes_preview_runner_after_publish(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, publish_app_generation_run, start_app_generation_preview

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = self._write_app_generation_workbench_run(runs_dir, "app-gen-004")
            publish_app_generation_run(
                DashboardConfig(
                    runs_dir=runs_dir,
                    domains_dir=root / "domains",
                    repo_root=root,
                    dashboard_dir=root / "dashboard",
                    executor="codex",
                ),
                {"run_id": "app-gen-004"},
            )

            class FakePreviewResult:
                status = "running"
                pid = 12345
                port = 8799
                url = "http://127.0.0.1:8799"
                health_status = "ok"
                started_at = "2026-01-01T00:00:00Z"
                log_path = Path("preview/preview.log")
                record_path = Path("preview/preview_run_record.json")
                risk_events = []
                message = "ok"

            with mock.patch("growth_dev.team.dashboard.preview.start_preview", return_value=FakePreviewResult()):
                result = start_app_generation_preview(
                    DashboardConfig(
                        runs_dir=runs_dir,
                        domains_dir=root / "domains",
                        repo_root=root,
                        dashboard_dir=root / "dashboard",
                        executor="codex",
                    ),
                    {"run_id": "app-gen-004", "preferred_port": 8799},
                )

        self.assertEqual(result["status"], "running")
        self.assertEqual(result["port"], 8799)
        self.assertEqual(result["url"], "http://127.0.0.1:8799")
        self.assertEqual(result["health_status"], "ok")

    def test_stop_preview_handles_missing_record_as_not_running(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, stop_app_generation_preview

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "app-gen-005"
            run_dir.mkdir(parents=True)

            result = stop_app_generation_preview(
                DashboardConfig(
                    runs_dir=runs_dir,
                    domains_dir=root / "domains",
                    repo_root=root,
                    dashboard_dir=root / "dashboard",
                    executor="codex",
                ),
                {"run_id": "app-gen-005"},
            )

        self.assertEqual(result["status"], "not_running")

    def test_get_preview_status_returns_record_without_env(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, get_app_generation_preview_status

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "app-gen-006"
            preview_dir = run_dir / "preview"
            preview_dir.mkdir(parents=True)
            record = {
                "run_id": "app-gen-006",
                "pid": 99999,
                "port": 8788,
                "url": "http://127.0.0.1:8788",
                "stopped_at": None,
                "health_status": "ok",
            }
            (preview_dir / "preview_run_record.json").write_text(json.dumps(record), encoding="utf-8")

            result = get_app_generation_preview_status(
                DashboardConfig(
                    runs_dir=runs_dir,
                    domains_dir=root / "domains",
                    repo_root=root,
                    dashboard_dir=root / "dashboard",
                    executor="codex",
                ),
                "app-gen-006",
            )

        self.assertEqual(result["run_id"], "app-gen-006")
        self.assertEqual(result["port"], 8788)
        self.assertIn("status", result)

    def test_get_preview_logs_returns_tail_lines_and_total_count(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, get_app_generation_preview_logs

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "app-gen-logs-001"
            preview_dir = run_dir / "preview"
            preview_dir.mkdir(parents=True)
            log_lines = [f"line-{i:04d}" for i in range(500)]
            (preview_dir / "preview.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")

            config = DashboardConfig(
                runs_dir=runs_dir,
                domains_dir=root / "domains",
                repo_root=root,
                dashboard_dir=root / "dashboard",
                executor="codex",
            )

            result = get_app_generation_preview_logs(config, "app-gen-logs-001", tail=100)
            self.assertEqual(result["total_lines"], 500)
            self.assertEqual(result["tail"], 100)
            self.assertEqual(len(result["lines"]), 100)
            self.assertEqual(result["lines"][0], "line-0400")
            self.assertEqual(result["lines"][-1], "line-0499")

    def test_get_preview_logs_returns_empty_when_log_missing(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, get_app_generation_preview_logs

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "app-gen-logs-002"
            (run_dir / "preview").mkdir(parents=True)

            config = DashboardConfig(
                runs_dir=runs_dir,
                domains_dir=root / "domains",
                repo_root=root,
                dashboard_dir=root / "dashboard",
                executor="codex",
            )

            result = get_app_generation_preview_logs(config, "app-gen-logs-002")
            self.assertEqual(result["lines"], [])
            self.assertEqual(result["total_lines"], 0)

    def test_preview_logs_route_parses_tail_query(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, create_dashboard_handler

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            preview_dir = runs_dir / "app-gen-logs-route" / "preview"
            preview_dir.mkdir(parents=True)
            (preview_dir / "preview.log").write_text("first\nsecond\n", encoding="utf-8")
            handler = create_dashboard_handler(
                DashboardConfig(
                    runs_dir=runs_dir,
                    domains_dir=root / "domains",
                    repo_root=root,
                    dashboard_dir=root / "dashboard",
                    executor="codex",
                )
            )

            request = handler.__new__(handler)
            request.path = "/api/app-generation/runs/app-gen-logs-route/preview/logs?tail=1"
            request._send_json = mock.Mock()
            request.do_GET()
            payload = request._send_json.call_args.args[0]

        self.assertEqual(payload["tail"], 1)
        self.assertEqual(payload["total_lines"], 2)
        self.assertEqual(payload["lines"], ["second"])

    def test_patch_app_rejects_unpublished_with_412(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, patch_app_generation_run

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "app-patch-001"
            run_dir.mkdir(parents=True)

            with self.assertRaises(ValueError) as ctx:
                patch_app_generation_run(
                    DashboardConfig(
                        runs_dir=runs_dir,
                        domains_dir=root / "domains",
                        repo_root=root,
                        dashboard_dir=root / "dashboard",
                        executor="codex",
                    ),
                    {
                        "run_id": "app-patch-001",
                        "target_path": "generated_apps/todo-prototype/public/app.js",
                        "edit_kind": "append",
                        "new_content": "// patch\n",
                        "summary": "test",
                    },
                )

        self.assertIn("app_not_published", str(ctx.exception))

    def test_patch_app_rejects_path_outside_generated_apps(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, patch_app_generation_run

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "app-patch-002"
            published = run_dir / "generated_apps" / "todo-prototype"
            published.mkdir(parents=True)
            (published / "app_publish.json").write_text(json.dumps({"app_slug": "todo-prototype"}), encoding="utf-8")
            (published / "public").mkdir()
            (published / "public" / "app.js").write_text("// orig\n", encoding="utf-8")

            with self.assertRaises(ValueError) as ctx:
                patch_app_generation_run(
                    DashboardConfig(
                        runs_dir=runs_dir,
                        domains_dir=root / "domains",
                        repo_root=root,
                        dashboard_dir=root / "dashboard",
                        executor="codex",
                    ),
                    {
                        "run_id": "app-patch-002",
                        "target_path": "worktree/generated_apps/todo-prototype/public/app.js",
                        "edit_kind": "append",
                        "new_content": "// hack\n",
                        "summary": "outside",
                    },
                )

        self.assertIn("target_path_outside_generated_apps", str(ctx.exception))

    def test_patch_app_append_writes_diff_and_index_and_overwrites_file(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, patch_app_generation_run

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "app-patch-003"
            published = run_dir / "generated_apps" / "todo-prototype"
            (published / "public").mkdir(parents=True)
            (published / "public" / "app.js").write_text("// original line\n", encoding="utf-8")
            (published / "app_publish.json").write_text(
                json.dumps({"app_slug": "todo-prototype", "published_at": "2026-01-01T00:00:00Z", "files_count": 1}),
                encoding="utf-8",
            )

            result = patch_app_generation_run(
                DashboardConfig(
                    runs_dir=runs_dir,
                    domains_dir=root / "domains",
                    repo_root=root,
                    dashboard_dir=root / "dashboard",
                    executor="codex",
                ),
                {
                    "run_id": "app-patch-003",
                    "target_path": "generated_apps/todo-prototype/public/app.js",
                    "edit_kind": "append",
                    "new_content": "// appended line\n",
                    "summary": "append a line",
                    "action_id": "act-001",
                },
            )

            patches_dir = run_dir / "app_patches"
            index_path = patches_dir / "index.json"
            updated = (published / "public" / "app.js").read_text(encoding="utf-8")

            self.assertEqual(result["status"], "applied")
            self.assertTrue(index_path.exists())
            self.assertIn("// appended line", updated)
            self.assertIn("// original line", updated)
            index = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(len(index["patches"]), 1)
            self.assertEqual(index["patches"][0]["node"], "app")
            self.assertEqual(index["patches"][0]["file"], "public/app.js")
            self.assertEqual(index["patches"][0]["action_id"], "act-001")
            diff_files = list(patches_dir.glob("*.diff"))
            self.assertEqual(len(diff_files), 1)
            self.assertIn("appended line", diff_files[0].read_text(encoding="utf-8"))

    def test_patch_app_replace_block_uses_anchor(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, patch_app_generation_run

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "app-patch-004"
            published = run_dir / "generated_apps" / "todo-prototype"
            (published / "public").mkdir(parents=True)
            (published / "public" / "app.js").write_text(
                "before\n// === AGENT_EDIT:btn START ===\nOLD BTN\n// === AGENT_EDIT:btn END ===\nafter\n",
                encoding="utf-8",
            )
            (published / "app_publish.json").write_text(
                json.dumps({"app_slug": "todo-prototype"}), encoding="utf-8"
            )

            result = patch_app_generation_run(
                DashboardConfig(
                    runs_dir=runs_dir,
                    domains_dir=root / "domains",
                    repo_root=root,
                    dashboard_dir=root / "dashboard",
                    executor="codex",
                ),
                {
                    "run_id": "app-patch-004",
                    "target_path": "generated_apps/todo-prototype/public/app.js",
                    "edit_kind": "replace_block",
                    "anchor": "// === AGENT_EDIT:btn START ===",
                    "new_content": "NEW BTN CONTENT",
                    "summary": "swap btn",
                },
            )

            updated = (published / "public" / "app.js").read_text(encoding="utf-8")
            self.assertEqual(result["status"], "applied")
            self.assertIn("NEW BTN CONTENT", updated)
            self.assertNotIn("OLD BTN", updated)
            self.assertIn("before", updated)
            self.assertIn("after", updated)

    def test_patch_app_no_active_preview_skips_restart(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, patch_app_generation_run

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "app-patch-005"
            published = run_dir / "generated_apps" / "todo-prototype"
            (published / "public").mkdir(parents=True)
            (published / "public" / "app.js").write_text("orig\n", encoding="utf-8")
            (published / "app_publish.json").write_text(
                json.dumps({"app_slug": "todo-prototype"}), encoding="utf-8"
            )

            result = patch_app_generation_run(
                DashboardConfig(
                    runs_dir=runs_dir,
                    domains_dir=root / "domains",
                    repo_root=root,
                    dashboard_dir=root / "dashboard",
                    executor="codex",
                ),
                {
                    "run_id": "app-patch-005",
                    "target_path": "generated_apps/todo-prototype/public/app.js",
                    "edit_kind": "append",
                    "new_content": "added\n",
                    "summary": "skip restart",
                },
            )

            self.assertEqual(result["status"], "applied")
            self.assertEqual(result["restart"]["status"], "skipped")
            self.assertIn("no_active_preview", result["restart"].get("reason", ""))

    def test_patch_app_two_stage_restart_switches_on_health_ok(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, patch_app_generation_run

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "app-patch-006"
            published = run_dir / "generated_apps" / "todo-prototype"
            (published / "public").mkdir(parents=True)
            (published / "public" / "app.js").write_text("orig\n", encoding="utf-8")
            (published / "app_publish.json").write_text(
                json.dumps({"app_slug": "todo-prototype"}), encoding="utf-8"
            )
            preview_dir = run_dir / "preview"
            preview_dir.mkdir(parents=True)
            old_record = {
                "run_id": "app-patch-006",
                "app_slug": "todo-prototype",
                "pid": 11111,
                "port": 8800,
                "url": "http://127.0.0.1:8800",
                "stopped_at": None,
                "health_status": "ok",
                "command": ["node", "server.js"],
            }
            (preview_dir / "preview_run_record.json").write_text(json.dumps(old_record), encoding="utf-8")

            class FakeNewPreview:
                status = "running"
                pid = 22222
                port = 8801
                url = "http://127.0.0.1:8801"
                health_status = "ok"
                started_at = "2026-01-01T00:00:01Z"
                log_path = Path("preview/preview.log")
                record_path = preview_dir / "preview_run_record.json"
                risk_events = []
                message = "ok"

            with mock.patch("growth_dev.team.dashboard.preview.start_preview", return_value=FakeNewPreview()), \
                 mock.patch("growth_dev.team.dashboard.preview._kill_pid", return_value=True) as kill_mock, \
                 mock.patch("growth_dev.team.dashboard.preview.allocate_port", return_value=8801):
                result = patch_app_generation_run(
                    DashboardConfig(
                        runs_dir=runs_dir,
                        domains_dir=root / "domains",
                        repo_root=root,
                        dashboard_dir=root / "dashboard",
                        executor="codex",
                    ),
                    {
                        "run_id": "app-patch-006",
                        "target_path": "generated_apps/todo-prototype/public/app.js",
                        "edit_kind": "append",
                        "new_content": "added\n",
                        "summary": "with restart",
                    },
                )

            self.assertEqual(result["status"], "applied")
            self.assertEqual(result["restart"]["status"], "switched")
            self.assertEqual(result["restart"]["new_port"], 8801)
            self.assertEqual(result["restart"]["old_pid"], 11111)
            kill_mock.assert_called_once_with(11111)
            record = json.loads((preview_dir / "preview_run_record.json").read_text(encoding="utf-8"))
            self.assertEqual(record["pid"], 22222)
            self.assertEqual(record["port"], 8801)
            self.assertEqual(record["previous_pid"], 11111)

    def test_patch_app_two_stage_restart_keeps_old_pid_on_health_failure(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, patch_app_generation_run

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "app-patch-007"
            published = run_dir / "generated_apps" / "todo-prototype"
            (published / "public").mkdir(parents=True)
            (published / "public" / "app.js").write_text("orig\n", encoding="utf-8")
            (published / "app_publish.json").write_text(
                json.dumps({"app_slug": "todo-prototype"}), encoding="utf-8"
            )
            preview_dir = run_dir / "preview"
            preview_dir.mkdir(parents=True)
            old_record = {
                "run_id": "app-patch-007",
                "app_slug": "todo-prototype",
                "pid": 33333,
                "port": 8800,
                "url": "http://127.0.0.1:8800",
                "stopped_at": None,
                "health_status": "ok",
                "command": ["node", "server.js"],
            }
            (preview_dir / "preview_run_record.json").write_text(json.dumps(old_record), encoding="utf-8")

            class FakeFailedPreview:
                status = "timeout"
                pid = None
                port = None
                url = None
                health_status = "failed"
                started_at = "2026-01-01T00:00:01Z"
                log_path = Path("preview/preview.log")
                record_path = preview_dir / "preview_run_record.json"
                risk_events = ["health_check_failed_killing_process"]
                message = "health check timeout"

            def failed_start_preview(*_args, **_kwargs):
                (preview_dir / "preview_run_record.json").write_text(
                    json.dumps(
                        {
                            "run_id": "app-patch-007",
                            "app_slug": "todo-prototype",
                            "pid": 44444,
                            "port": 8801,
                            "url": "http://127.0.0.1:8801",
                            "stopped_at": None,
                            "health_status": "failed",
                        }
                    ),
                    encoding="utf-8",
                )
                return FakeFailedPreview()

            with mock.patch("growth_dev.team.dashboard.preview.start_preview", side_effect=failed_start_preview), \
                 mock.patch("growth_dev.team.dashboard.preview._kill_pid", return_value=True) as kill_mock, \
                 mock.patch("growth_dev.team.dashboard.preview.allocate_port", return_value=8801):
                result = patch_app_generation_run(
                    DashboardConfig(
                        runs_dir=runs_dir,
                        domains_dir=root / "domains",
                        repo_root=root,
                        dashboard_dir=root / "dashboard",
                        executor="codex",
                    ),
                    {
                        "run_id": "app-patch-007",
                        "target_path": "generated_apps/todo-prototype/public/app.js",
                        "edit_kind": "append",
                        "new_content": "added\n",
                        "summary": "with failed restart",
                    },
                )

            self.assertEqual(result["status"], "applied")
            self.assertEqual(result["restart"]["status"], "failed")
            self.assertEqual(result["restart"]["phase"], "new_process_health_check")
            kill_mock.assert_not_called()
            record = json.loads((preview_dir / "preview_run_record.json").read_text(encoding="utf-8"))
            self.assertEqual(record["pid"], 33333)
            self.assertEqual(record["port"], 8800)

    def test_dashboard_start_run_passes_app_generation_inputs_json(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, start_dashboard_run

        class FakeProcess:
            pid = 4321

            def wait(self, timeout: float | None = None) -> int:
                return 0

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            repo_root = Path(__file__).resolve().parents[1]
            with mock.patch("growth_dev.team.dashboard.subprocess.Popen", return_value=FakeProcess()):
                start_dashboard_run(
                    DashboardConfig(
                        runs_dir=runs_dir,
                        domains_dir=repo_root / "domains",
                        repo_root=repo_root,
                        dashboard_dir=repo_root / "dashboard",
                        executor="codex",
                    ),
                    {
                        "run_id": "app-generation-post",
                        "brief": "根据 PRD 生成本地应用：todo-prototype",
                        "domain": "app_generation",
                        "executor": "codex",
                        "inputs_json": {"app_slug": "todo-prototype", "prd_text": "# Todo PRD"},
                    },
                )
            process = json.loads((runs_dir / "app-generation-post" / "process.json").read_text(encoding="utf-8"))

        command = process["command"]
        inputs = json.loads(command[command.index("--inputs-json") + 1])
        self.assertEqual(command[command.index("--domain") + 1], "app_generation")
        self.assertEqual(inputs["app_slug"], "todo-prototype")
        self.assertEqual(inputs["prd_text"], "# Todo PRD")

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

    def test_patch_app_dry_run_returns_diff_without_writing(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, patch_app_generation_run

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "app-patch-dry-001"
            published = run_dir / "generated_apps" / "todo-prototype"
            (published / "public").mkdir(parents=True)
            (published / "public" / "app.js").write_text("// original line\n", encoding="utf-8")
            (published / "app_publish.json").write_text(
                json.dumps({"app_slug": "todo-prototype", "published_at": "2026-01-01T00:00:00Z"}),
                encoding="utf-8",
            )

            result = patch_app_generation_run(
                DashboardConfig(
                    runs_dir=runs_dir,
                    domains_dir=root / "domains",
                    repo_root=root,
                    dashboard_dir=root / "dashboard",
                    executor="codex",
                ),
                {
                    "run_id": "app-patch-dry-001",
                    "target_path": "generated_apps/todo-prototype/public/app.js",
                    "edit_kind": "append",
                    "new_content": "// appended line\n",
                    "summary": "append a line",
                    "action_id": "act-dry-001",
                    "dry_run": True,
                },
            )

            patches_dir = run_dir / "app_patches"
            updated = (published / "public" / "app.js").read_text(encoding="utf-8")

            self.assertEqual(result["status"], "dry_run")
            self.assertEqual(result["app_slug"], "todo-prototype")
            self.assertIn("diff", result)
            self.assertIn("// appended line", result["diff"])
            self.assertNotIn("// appended line", updated)
            self.assertFalse(patches_dir.exists())

    def test_patch_app_dry_run_does_not_update_index(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, patch_app_generation_run

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "app-patch-dry-002"
            published = run_dir / "generated_apps" / "todo-prototype"
            (published / "public").mkdir(parents=True)
            (published / "public" / "app.js").write_text("// original\n", encoding="utf-8")
            (published / "app_publish.json").write_text(
                json.dumps({"app_slug": "todo-prototype"}), encoding="utf-8"
            )
            patches_dir = run_dir / "app_patches"
            patches_dir.mkdir(parents=True)
            index_path = patches_dir / "index.json"
            index_path.write_text(json.dumps({"patches": [{"ts": 1000, "node": "app"}]}), encoding="utf-8")

            patch_app_generation_run(
                DashboardConfig(
                    runs_dir=runs_dir,
                    domains_dir=root / "domains",
                    repo_root=root,
                    dashboard_dir=root / "dashboard",
                    executor="codex",
                ),
                {
                    "run_id": "app-patch-dry-002",
                    "target_path": "generated_apps/todo-prototype/public/app.js",
                    "edit_kind": "append",
                    "new_content": "// new line\n",
                    "summary": "test",
                    "dry_run": True,
                },
            )

            index = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(len(index["patches"]), 1)
            self.assertEqual(index["patches"][0]["ts"], 1000)

    def test_patch_app_dry_run_validates_unpublished_app(self) -> None:
        from growth_dev.team.dashboard import DashboardConfig, patch_app_generation_run

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "app-patch-dry-003"
            run_dir.mkdir(parents=True)

            with self.assertRaises(ValueError) as ctx:
                patch_app_generation_run(
                    DashboardConfig(
                        runs_dir=runs_dir,
                        domains_dir=root / "domains",
                        repo_root=root,
                        dashboard_dir=root / "dashboard",
                        executor="codex",
                    ),
                    {
                        "run_id": "app-patch-dry-003",
                        "target_path": "generated_apps/todo-prototype/public/app.js",
                        "edit_kind": "append",
                        "new_content": "test",
                        "dry_run": True,
                    },
                )
            self.assertIn("app_not_published", str(ctx.exception))
