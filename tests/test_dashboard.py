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
        self.assertIn("human_approval", stage_ids)
        self.assertIn("before_coding", gate_ids)
        self.assertIn("ci_gate", gate_ids)
        self.assertIn("coding finished", "\n".join(state["logs"]))
        self.assertIn("health_summary", state)
        self.assertIn("quality_report", state)
        self.assertEqual(state["implementation_trace"]["status"], "completed")
        self.assertTrue(any(item["path"] == "codex/implementation_trace.json" for item in state["artifacts"]))
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

        for section in ("app", "status", "stages", "agents", "gates", "artifacts", "events", "actions"):
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
        for stage in ("requirement", "design", "implementation", "quality", "delivery"):
            self.assertIn(stage, payload["stages"])
            self.assertIn("title", payload["stages"][stage])

    def test_dashboard_html_defaults_to_business_copy_and_hides_engineering_controls(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "dashboard" / "index.html").read_text(encoding="utf-8")

        self.assertIn("data-i18n", html)
        self.assertIn("advanced-settings", html)
        self.assertIn('id="deliverables-panel"', html)
        self.assertIn('id="acceptance-panel"', html)
        self.assertIn('id="acceptance-action"', html)
        self.assertIn('id="acceptance-steps"', html)
        self.assertIn('id="stage-detail-panel"', html)
        self.assertIn('class="panel deliverables-panel"', html)
        self.assertIn('class="deliverables-grid"', html)
        self.assertIn('class="engineering-rail"', html)
        self.assertNotIn('app.acceptanceSummary', html)
        self.assertNotIn('app.acceptanceSummaryHint', html)
        self.assertNotIn("engineering-panel", html)
        self.assertLess(html.index('id="artifact-actions"'), html.index('id="artifact-preview"'))
        self.assertEqual(html.count('id="deliverables"'), 0)
        self.assertLess(html.index('id="business-stages"'), html.index('id="stage-detail-panel"'))
        self.assertLess(html.index('id="stage-detail-panel"'), html.index('id="health-summary"'))
        for engineering_copy in ("Pipeline", "Gates", "Logs", "Artifacts", "Executor", "Provider", "Model"):
            self.assertNotIn(engineering_copy, html)

    def test_dashboard_engineering_details_are_third_column_cards(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "dashboard" / "index.html").read_text(encoding="utf-8")

        rail_start = html.index('class="engineering-rail"')
        for engineering_id in ("engineering-run", "engineering-events", "engineering-logs", "engineering-diff"):
            self.assertGreater(html.index(f'id="{engineering_id}"'), rail_start)
        self.assertEqual(html.count('class="engineering-card"'), 4)

    def test_dashboard_deliverables_panel_uses_list_and_preview_columns(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "dashboard" / "index.html").read_text(encoding="utf-8")

        panel_start = html.index('id="deliverables-panel"')
        list_start = html.index('class="deliverables-list-pane"', panel_start)
        preview_start = html.index('class="deliverables-preview-pane"', panel_start)
        self.assertLess(list_start, preview_start)
        self.assertGreater(html.index('id="artifact-actions"', list_start), list_start)
        self.assertGreater(html.index('id="next-actions"', list_start), list_start)
        self.assertGreater(html.index('id="artifact-preview"', preview_start), preview_start)

    def test_dashboard_quality_gates_use_compact_two_column_grid(self) -> None:
        root = Path(__file__).resolve().parents[1]
        css = (root / "dashboard" / "styles.css").read_text(encoding="utf-8")

        self.assertIn(".gate-list", css)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr));", css)
        self.assertIn(".gate-card p {\n  grid-column: 1 / -1;", css)

    def test_dashboard_stage_detail_has_i18n_and_render_helpers(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "dashboard" / "app.js").read_text(encoding="utf-8")
        i18n = json.loads((root / "dashboard" / "i18n" / "zh-CN.json").read_text(encoding="utf-8"))

        self.assertIn("selectedStageDetail", app_js)
        self.assertIn("renderStageDetail", app_js)
        self.assertIn("renderStageDeliverables", app_js)
        self.assertIn("renderStageEngineering", app_js)
        self.assertIn("renderImplementationFlow", app_js)
        self.assertIn("filterEngineeringForStage", app_js)
        self.assertIn("loadArtifactContent", app_js)
        self.assertIn("stageDetail", i18n)
        self.assertIn("implementationFlow", i18n)
        for key in (
            "deliverablesSuffix",
            "engineeringSuffix",
            "emptyDeliverables",
            "emptyEngineering",
            "openGlobalDeliverables",
            "openGlobalEngineering",
        ):
            self.assertIn(key, i18n["stageDetail"])

    def test_dashboard_stage_detail_content_is_bounded_inside_card(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "dashboard" / "app.js").read_text(encoding="utf-8")
        css = (root / "dashboard" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('body.className = `stage-detail-body ${selection.mode === "engineering" ? "engineering-mode" : "deliverables-mode"}`', app_js)
        self.assertIn('list.className = "stage-detail-list"', app_js)
        self.assertIn(".stage-detail-panel {\n  display: grid;", css)
        self.assertIn("grid-template-rows: auto minmax(0, 1fr);", css)
        self.assertIn("max-height: min(620px, 72vh);", css)
        self.assertIn(".stage-detail-body.engineering-mode {\n  display: flex;\n  flex-direction: column;", css)
        self.assertIn("overflow: auto;", css)
        self.assertIn("align-items: stretch;", css)
        self.assertIn(".implementation-flow", css)
        self.assertIn("max-height: none;", css)
        self.assertIn("min-height: auto;", css)
        self.assertIn("overflow: visible;", css)
        self.assertIn(".stage-detail-body.engineering-mode > .stage-detail-block", css)
        self.assertIn("width: 100%;", css)
        self.assertIn("white-space: nowrap;", css)
        self.assertIn(".stage-detail-list li", css)
        self.assertIn("overflow-wrap: anywhere;", css)

    def test_dashboard_stage_detail_scroll_is_preserved_during_polling_refresh(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "dashboard" / "app.js").read_text(encoding="utf-8")

        self.assertIn("stageDetailScroll", app_js)
        self.assertIn("function stageDetailKey", app_js)
        self.assertIn("function captureStageDetailScroll", app_js)
        self.assertIn("function restoreStageDetailScroll", app_js)
        self.assertIn("captureStageDetailScroll();", app_js)
        self.assertIn('body.addEventListener("scroll"', app_js)
        self.assertIn("restoreStageDetailScroll(body);", app_js)
        self.assertIn('state.stageDetailScroll = { key: "", top: 0 };', app_js)

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
        self.assertIn('focusSection("deliverables-panel")', app_js)
        self.assertIn('focusSection("engineering-rail")', app_js)
        self.assertIn('toggleStageDetail(stage, "deliverables")', app_js)
        self.assertIn('toggleStageDetail(stage, "engineering")', app_js)
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
        self.assertIn("startAcceptance", app_js)
        self.assertIn('/acceptance"', app_js)
        self.assertIn("acceptance-action", app_js)
        self.assertIn("acceptance-step", app_js)
        self.assertIn(".acceptance-panel", css)
        self.assertIn(".acceptance-step", css)

    def test_business_view_model_translates_run_to_five_business_stages(self) -> None:
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
        design_stage = vm["stages"][1]
        implementation_stage = vm["stages"][2]
        self.assertEqual(design_stage["agentIds"], ["product", "architect", "ux", "qa"])
        self.assertTrue(any(artifact["path"] == "prd.md" for artifact in design_stage["artifacts"]))
        self.assertTrue(any(artifact["path"] == "codex/implementation_trace.json" for artifact in implementation_stage["artifacts"]))
        self.assertTrue(any(artifact["path"] == "codex/diff.patch" for artifact in implementation_stage["artifacts"]))
        self.assertEqual(design_stage["artifacts"][0]["title"], "PRD")
        self.assertIn("代码差异", {artifact["title"] for artifact in implementation_stage["artifacts"]})

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
