from __future__ import annotations

import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

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
        (codex_dir / "stdout.jsonl").write_text("coding started\ncoding finished\n", encoding="utf-8")
        (codex_dir / "stderr.log").write_text("provider warning\n", encoding="utf-8")
        (codex_dir / "diff.patch").write_text("diff --git a/a b/a\n+dashboard\n", encoding="utf-8")
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
        self.assertEqual(state["diff_summary"]["lines"], 2)
        self.assertEqual(state["apply_gate"]["status"], "passed")
        self.assertNotIn("sk-should-not-leak", payload)
        self.assertNotIn(".env", payload)

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
        for stage in ("requirement", "design", "implementation", "quality", "delivery"):
            self.assertIn(stage, payload["stages"])
            self.assertIn("title", payload["stages"][stage])

    def test_dashboard_html_defaults_to_business_copy_and_hides_engineering_controls(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "dashboard" / "index.html").read_text(encoding="utf-8")

        self.assertIn("data-i18n", html)
        self.assertIn("advanced-settings", html)
        for engineering_copy in ("Pipeline", "Gates", "Logs", "Artifacts", "Executor", "Provider", "Model"):
            self.assertNotIn(engineering_copy, html)

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
                {"label": "Diff Evidence", "path": "codex/diff.patch", "scope": "run", "exists": True},
            ],
            "risk_events": [],
            "next_actions": ["python -m growth_dev.cli team apply --run-id biz-run-1"],
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
        self.assertEqual(vm["deliverables"][3]["title"], "代码差异")

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
