from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


def _write_canvas_run(runs_dir: Path, run_id: str = "canvas-run-1") -> Path:
    run_dir = runs_dir / run_id
    (run_dir / "requirements").mkdir(parents=True)
    (run_dir / "planning").mkdir(parents=True)
    (run_dir / "codex").mkdir(parents=True)
    (run_dir / "preview").mkdir(parents=True)
    (run_dir / "app_repairs" / "repair-1").mkdir(parents=True)
    record = {
        "run_id": run_id,
        "domain_id": "app_generation",
        "brief": "根据 PRD 生成本地应用：todo-prototype sk-should-not-leak",
        "status": "completed",
        "inputs": {"app_slug": "todo-prototype", "comparison_group_id": "cmp-todo"},
        "agent_runs": [],
        "risk_events": [],
    }
    (run_dir / "team_run_record.json").write_text(json.dumps(record), encoding="utf-8")
    (run_dir / "process.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    (run_dir / "input_prd.md").write_text("# Todo PRD\n\n用户可以新增、完成、筛选待办。\n", encoding="utf-8")
    (run_dir / "requirements" / "normalized_prd.md").write_text("# 标准化 PRD\n\nlocalStorage only\n", encoding="utf-8")
    (run_dir / "requirements" / "capability_boundary.json").write_text(
        json.dumps({"required_new_capabilities": [{"id": "local_todo", "summary": "用户管理本地待办"}]}),
        encoding="utf-8",
    )
    (run_dir / "context_pack.md").write_text("# Context\n", encoding="utf-8")
    (run_dir / "app_contract.json").write_text(
        json.dumps(
            {
                "app_slug": "todo-prototype",
                "generated_app_dir": "generated_apps/todo-prototype",
                "target_stack": {"frontend": "native_spa", "backend": "node_stdlib", "storage": "localStorage", "database": "none"},
                "provider": {"name": "openrouter", "api_key": "sk-should-not-leak"},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "acceptance_criteria.md").write_text("# AC\n\n- `AC-001` Todo flow.\n", encoding="utf-8")
    (run_dir / "planning" / "tdd_plan.json").write_text(
        json.dumps({"test_cases": [{"id": "TDD-001", "description": "Todo flow"}]}),
        encoding="utf-8",
    )
    (run_dir / "planning" / "acceptance_coverage_matrix.json").write_text(
        json.dumps({"acceptance_criteria": [{"id": "AC-001", "description": "Todo flow"}]}),
        encoding="utf-8",
    )
    (run_dir / "codex" / "implementation_trace.json").write_text(
        json.dumps({"status": "completed", "steps": [{"id": "codex_running", "status": "completed", "summary": "应用代码已生成"}]}),
        encoding="utf-8",
    )
    (run_dir / "codex" / "verification_record.json").write_text(
        json.dumps({"status": "completed", "commands": [{"command": "node --check server.js", "exit_code": 0}]}),
        encoding="utf-8",
    )
    (run_dir / "codex" / "diff.patch").write_text("diff --git a/server.js b/server.js\n", encoding="utf-8")
    (run_dir / "test_report.md").write_text("# Test\n\npassed\n", encoding="utf-8")
    (run_dir / "preview_instructions.md").write_text("node server.js\n", encoding="utf-8")
    (run_dir / "final_report.md").write_text("# Final\n", encoding="utf-8")
    (run_dir / "preview" / "preview_run_record.json").write_text(
        json.dumps({"status": "running", "url": "http://127.0.0.1:8799"}),
        encoding="utf-8",
    )
    (run_dir / "agqs_score.json").write_text(
        json.dumps({"blocking_events": ["benchmark_parity_missing:image_download"], "overall_agqs": 72}),
        encoding="utf-8",
    )
    (run_dir / "app_repairs" / "repair-1" / "repair_result.json").write_text(
        json.dumps({"repair_id": "repair-1", "status": "prepared", "summary": "补齐下载按钮"}),
        encoding="utf-8",
    )
    return run_dir


class AppGenerationCanvasTests(unittest.TestCase):
    def test_canvas_projection_builds_business_nodes_and_objects_without_secrets(self) -> None:
        from growth_dev.team.app_generation_canvas import build_canvas_projection

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            _write_canvas_run(runs_dir)

            projection = build_canvas_projection("canvas-run-1", runs_dir=runs_dir, repo_root=root)

        self.assertEqual(projection["schema_version"], 1)
        self.assertEqual(
            [node["title"] for node in projection["business_nodes"]],
            ["理解业务目标", "编译业务规格", "规划应用结构", "生成应用原型", "验证业务能力", "输出可交付版本"],
        )
        self.assertEqual(
            [step["title"] for step in projection["flow_steps"]],
            ["PRD 输入", "理解业务目标", "编译业务规格", "规划应用结构", "生成应用原型", "验证业务能力", "输出可交付版本", "可预览应用"],
        )
        self.assertEqual(projection["flow_steps"][0]["id"], "prd_entry")
        self.assertEqual(projection["flow_steps"][0]["runtime_nodes"], [])
        self.assertEqual(projection["flow_steps"][-1]["id"], "app_preview")
        self.assertEqual(projection["flow_steps"][-1]["runtime_nodes"], [])
        for step in projection["flow_steps"]:
            self.assertIn("input_summary", step)
            self.assertIn("process_summary", step)
            self.assertIn("output_summary", step)
            self.assertIn("available_actions", step)
            self.assertIn("evidence_refs", step)
        self.assertEqual(
            [node["stage_index"] for node in projection["business_nodes"]],
            [1, 2, 3, 4, 5, 6],
        )
        first_node = projection["business_nodes"][0]
        last_node = projection["business_nodes"][-1]
        self.assertTrue(first_node["is_entry"])
        self.assertEqual(first_node["input_from"], "PRD 输入")
        self.assertTrue(last_node["is_terminal"])
        self.assertEqual(last_node["output_to"], "可预览应用")
        for node in projection["business_nodes"]:
            self.assertIn("ready_artifacts", node["progress"])
            self.assertIn("required_artifacts", node["progress"])
        self.assertTrue(projection["edges"])
        self.assertTrue(
            {edge["type"] for edge in projection["edges"]} <= {"requires", "produces", "evidenced_by"}
        )
        object_types = {item["object_type"] for item in projection["objects"]}
        self.assertIn("business_goal", object_types)
        self.assertIn("capability", object_types)
        self.assertIn("provider_config", object_types)
        self.assertIn("preview_session", object_types)
        self.assertIn("capability_gap", object_types)
        self.assertIn("repair_candidate", object_types)
        encoded = json.dumps(projection, ensure_ascii=False)
        self.assertNotIn("sk-should-not-leak", encoded)
        self.assertIn("[REDACTED]", encoded)

    def test_canvas_projection_does_not_require_benchmark_artifacts_for_prototype_runs(self) -> None:
        from growth_dev.team.app_generation_canvas import build_canvas_projection

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = _write_canvas_run(runs_dir)
            (run_dir / "agqs_score.json").unlink()

            projection = build_canvas_projection("canvas-run-1", runs_dir=runs_dir, repo_root=root)

        verification_step = next(step for step in projection["flow_steps"] if step["id"] == "capability_verification")
        self.assertEqual(verification_step["progress"]["required_artifacts"], 3)
        self.assertEqual(verification_step["progress"]["ready_artifacts"], 2)
        self.assertNotIn("agqs_score.json", verification_step["evidence_refs"])

    def test_canvas_projection_accepts_process_only_pending_app_generation_run(self) -> None:
        from growth_dev.team.app_generation_canvas import build_canvas_projection

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "app_generation-pending"
            run_dir.mkdir(parents=True)
            (run_dir / "process.json").write_text(
                json.dumps(
                    {
                        "run_id": "app_generation-pending",
                        "status": "running",
                        "command": [
                            "python3",
                            "-m",
                            "growth_dev.cli",
                            "team",
                            "run",
                            "--run-id",
                            "app_generation-pending",
                            "--brief",
                            "根据 PRD 生成本地应用：pending-app",
                            "--domain",
                            "app_generation",
                            "--inputs-json",
                            json.dumps({"app_slug": "pending-app", "comparison_group_id": "cmp-pending"}, ensure_ascii=False),
                            "--executor",
                            "codex",
                        ],
                    }
                ),
                encoding="utf-8",
            )

            projection = build_canvas_projection("app_generation-pending", runs_dir=runs_dir, repo_root=root)

        self.assertEqual(projection["run"]["domain_id"], "app_generation")
        self.assertEqual(projection["run"]["app_slug"], "pending-app")
        self.assertEqual(projection["run"]["status"], "running")
        self.assertEqual(len(projection["flow_steps"]), 8)
        self.assertEqual(projection["current_business_node_id"], "business_goal_understanding")
        running_nodes = [node for node in projection["business_nodes"] if node["status"] == "running"]
        self.assertEqual([node["id"] for node in running_nodes], ["business_goal_understanding"])
        self.assertTrue(running_nodes[0]["is_current"])
        self.assertTrue(all(not node["is_current"] for node in projection["business_nodes"][1:]))

    def test_canvas_object_detail_rejects_unknown_or_cross_run_object(self) -> None:
        from growth_dev.team.app_generation_canvas import build_canvas_object_detail, build_canvas_projection

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            _write_canvas_run(runs_dir)
            projection = build_canvas_projection("canvas-run-1", runs_dir=runs_dir, repo_root=root)
            object_id = projection["objects"][0]["object_id"]

            detail = build_canvas_object_detail("canvas-run-1", object_id, runs_dir=runs_dir, repo_root=root)

            with self.assertRaises(ValueError):
                build_canvas_object_detail("canvas-run-1", "other-run:capability:x", runs_dir=runs_dir, repo_root=root)

        self.assertEqual(detail["object_id"], object_id)
        self.assertIn("related_objects", detail)
        self.assertIn("upstream_objects", detail)
        self.assertIn("downstream_objects", detail)

    def test_canvas_projection_exposes_classification_summary_for_warnings_and_failures(self) -> None:
        from growth_dev.team.app_generation_canvas import build_canvas_projection

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = _write_canvas_run(runs_dir)
            (run_dir / "codex" / "failure_classification.json").write_text(
                json.dumps(
                    {
                        "classification_decision": "passed_with_warnings",
                        "primary_reason": "codex_unrelated_test_blocker",
                        "blocking_events": [],
                        "warnings": ["codex_unrelated_test_blocker"],
                        "evidence": {
                            "codex_blockers": [
                                "Declared full suite fails in unrelated `tests/test_taobao_collector.py`; isolated rerun fails the same way."
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )

            projection = build_canvas_projection("canvas-run-1", runs_dir=runs_dir, repo_root=root)

        summary = projection["run"]["classification_summary"]
        self.assertEqual(summary["decision"], "passed_with_warnings")
        self.assertEqual(summary["blocking_count"], 0)
        self.assertEqual(summary["warnings_count"], 1)
        self.assertIn("isolated rerun", summary["blocker_preview"])
        self.assertEqual(summary["artifact_path"], "codex/failure_classification.md")

    def test_canvas_projection_classification_summary_is_empty_without_artifact(self) -> None:
        from growth_dev.team.app_generation_canvas import build_canvas_projection

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            _write_canvas_run(runs_dir)

            projection = build_canvas_projection("canvas-run-1", runs_dir=runs_dir, repo_root=root)

        summary = projection["run"]["classification_summary"]
        self.assertEqual(summary["decision"], "")
        self.assertEqual(summary["blocking_count"], 0)
        self.assertEqual(summary["warnings_count"], 0)


if __name__ == "__main__":
    unittest.main()
