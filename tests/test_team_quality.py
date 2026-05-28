from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from growth_dev.team.models import TeamRunRecord
from growth_dev.team.quality import evaluate_run_quality, summarize_run_health, summarize_run_logs


def _write_record(run_dir: Path, *, status: str = "completed") -> TeamRunRecord:
    record = {
        "run_id": run_dir.name,
        "team_id": "ai_native_engineering_team",
        "domain_id": "web_monitoring",
        "brief": "给 web_monitoring domain 增加截图证据字段，并补充对应测试",
        "status": status,
        "run_dir": str(run_dir),
        "agent_runs": [
            {"agent_id": "coder", "status": "completed", "started_at": "a", "finished_at": "b", "risk_events": [], "output_paths": [], "message": "", "metadata": {}},
            {"agent_id": "verifier", "status": "completed", "started_at": "c", "finished_at": "d", "risk_events": [], "output_paths": ["test_report.md"], "message": "", "metadata": {}},
        ],
        "risk_events": [],
        "executor": "codex",
    }
    (run_dir / "team_run_record.json").write_text(json.dumps(record), encoding="utf-8")
    return TeamRunRecord.from_dict(record)


class TeamQualityTests(unittest.TestCase):
    def test_quality_report_flags_stale_domain_leakage_and_weak_task_specificity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "bad-run"
            run_dir.mkdir()
            record = _write_record(run_dir)
            (run_dir / "prd.md").write_text(
                "# PRD\n\n## Goal\n给 web_monitoring domain 增加截图证据字段。\n\n## Scope\nCompare Playwright MCP, Stagehand, Skyvern, HyperAgent, and browser-use against an XHS benchmark.\n",
                encoding="utf-8",
            )
            (run_dir / "tech_spec.md").write_text("# Technical Spec\n\n## Runtime Architecture\nXHS benchmark harness.\n", encoding="utf-8")
            (run_dir / "ui_spec.md").write_text("# UI Spec\n\nBenchmark report states.\n", encoding="utf-8")
            (run_dir / "eval.md").write_text("# Eval\n\n## Review Gate\nGeneric runtime checks.\n", encoding="utf-8")
            (run_dir / "final_report.md").write_text("# Final Report\n\n## Recommendation\nUse Playwright MCP baseline.\n", encoding="utf-8")

            report = evaluate_run_quality(record, run_dir)

        payload = report.to_dict()
        self.assertEqual(payload["status"], "needs_attention")
        self.assertIn("旧领域上下文污染", payload["summary"])
        failed_ids = {check["id"] for check in payload["checks"] if check["status"] == "failed"}
        self.assertIn("prd.md.context_leakage", failed_ids)
        self.assertIn("ui_spec.md.no_ui_impact", failed_ids)

    def test_quality_report_passes_task_specific_non_ui_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "good-run"
            run_dir.mkdir()
            record = _write_record(run_dir)
            (run_dir / "prd.md").write_text(
                "# PRD\n\n## Background\nweb_monitoring 需要记录截图证据。\n\n## Goal\n增加 screenshot_evidence 字段。\n\n## Scope\n只修改 domain schema 和测试。\n\n## Acceptance Criteria\n字段存在且测试通过。\n",
                encoding="utf-8",
            )
            (run_dir / "tech_spec.md").write_text("# Technical Spec\n\n## Data Contract\nweb_monitoring 输出包含 screenshot_evidence。\n\n## Gates\n运行 domain 测试。\n", encoding="utf-8")
            (run_dir / "ui_spec.md").write_text("# UI Spec\n\n无 UI 影响。本次只改变 web_monitoring domain schema 和测试。\n", encoding="utf-8")
            (run_dir / "eval.md").write_text("# Eval\n\n## Acceptance Criteria\n验证 screenshot_evidence 字段和 evaluation rule。\n\n## Test Commands\npython3 -m unittest discover -s tests -v\n", encoding="utf-8")
            (run_dir / "final_report.md").write_text("# Final Report\n\n## Brief\n增加截图证据字段。\n\n## Gate Results\n通过。\n\n## Recommendation\n可以采纳。\n", encoding="utf-8")

            report = evaluate_run_quality(record, run_dir)

        self.assertEqual(report.status, "passed")
        self.assertGreaterEqual(report.score, 0.9)

    def test_completed_run_with_non_blocking_stderr_warning_is_not_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "warning-run"
            codex_dir = run_dir / "codex"
            codex_dir.mkdir(parents=True)
            record = _write_record(run_dir)
            (codex_dir / "stderr.log").write_text(
                'ERROR codex_models_manager::manager: failed to refresh available models: {"code":"SETTLEMENT_UNKNOWN_MODEL"}\n',
                encoding="utf-8",
            )

            health = summarize_run_health(record, run_dir)

        self.assertEqual(health.status, "completed_with_warnings")
        self.assertIn("非阻塞警告", health.summary)
        self.assertFalse(health.blockers)

    def test_completed_run_with_non_blocking_risk_notes_is_warning_not_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "risk-note-run"
            run_dir.mkdir()
            record = _write_record(run_dir)
            record.agent_runs[0].metadata["non_blocking_risk_events"] = [
                "No scraping, login, captcha, proxy, fingerprinting, anti-detect, or private API behavior was added."
            ]

            health = summarize_run_health(record, run_dir)

        self.assertEqual(health.status, "completed_with_warnings")
        self.assertFalse(health.blockers)
        self.assertTrue(any("执行边界说明" in warning for warning in health.warnings))

    def test_non_blocking_codex_warnings_are_grouped_for_business_health(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "grouped-warning-run"
            codex_dir = run_dir / "codex"
            codex_dir.mkdir(parents=True)
            record = _write_record(run_dir)
            (codex_dir / "stderr.log").write_text(
                "\n".join(
                    [
                        "WARN codex_core_plugins::startup_remote_sync: startup remote plugin sync failed; will retry on next app-server start",
                        "WARN codex_core_plugins::remote::remote_installed_plugin_sync: remote installed plugin bundle sync failed",
                        "WARN codex_otel::events::session_telemetry: metrics counter [codex.skill.injected] failed",
                        "WARN codex_core::session::turn: stream disconnected - retrying sampling request (1/5 in 207ms)",
                        "WARN codex_rmcp_client::stdio_server_launcher: Failed to kill MCP process group 47328: No such process",
                        "WARN codex_protocol::openai_models: Model personality requested but model_messages is missing",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            health = summarize_run_health(record, run_dir)
            payload = health.to_dict()

        self.assertEqual(health.status, "completed_with_warnings")
        self.assertIn("5 类非阻塞系统提示", health.summary)
        self.assertFalse(health.blockers)
        group_ids = [group["id"] for group in payload["warning_groups"]]
        self.assertEqual(group_ids[:3], ["plugin_sync", "telemetry", "network_retry"])
        self.assertIn("raw_warnings", payload)
        self.assertTrue(payload["raw_warnings"])

    def test_codex_jsonl_is_summarized_without_raw_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "log-run"
            codex_dir = run_dir / "codex"
            codex_dir.mkdir(parents=True)
            (codex_dir / "stdout.jsonl").write_text(
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "agent_message",
                            "text": json.dumps(
                                {
                                    "summary": "Added screenshot evidence.",
                                    "files_changed": ["domains/web_monitoring/domain.yaml"],
                                    "tests_run": ["python3 -m unittest tests.test_web_monitoring_domain -v"],
                                    "risk_events": [],
                                }
                            ),
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            lines = summarize_run_logs(run_dir)

        rendered = "\n".join(lines)
        self.assertIn("Codex summary: Added screenshot evidence.", rendered)
        self.assertIn("Changed files: domains/web_monitoring/domain.yaml", rendered)
        self.assertNotIn('{"type"', rendered)


if __name__ == "__main__":
    unittest.main()
