from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path


@contextlib.contextmanager
def _captured_output():
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        yield stdout, stderr


def _write_retrospective_run(
    runs_dir: Path,
    run_id: str,
    *,
    status: str = "completed",
    risk_events: list[str] | None = None,
    secret: str = "sk-should-not-export",
) -> Path:
    run_dir = runs_dir / run_id
    codex_dir = run_dir / "codex"
    acceptance_dir = run_dir / "acceptance"
    codex_dir.mkdir(parents=True)
    acceptance_dir.mkdir()
    record = {
        "run_id": run_id,
        "team_id": "ai_native_engineering_team",
        "domain_id": "web_monitoring",
        "brief": f"给 {run_id} 增加 Dashboard 可观测能力",
        "status": status,
        "run_dir": str(run_dir),
        "started_at": "2026-05-28T00:00:00+00:00",
        "finished_at": "" if status == "running" else "2026-05-28T00:03:00+00:00",
        "executor": "codex",
        "executor_config": {
            "model": "gpt-5.5",
            "provider": {"name": "aicodemirror", "env_key": "AICODEMIRROR_KEY", "secret_configured": True},
            "api_key": secret,
        },
        "agent_runs": [
            {
                "agent_id": "product",
                "status": "completed",
                "started_at": "a",
                "finished_at": "b",
                "risk_events": [],
                "output_paths": ["prd.md"],
                "message": "prd created",
                "metadata": {},
            },
            {
                "agent_id": "coder",
                "status": "failed" if status == "failed" else ("running" if status == "running" else "completed"),
                "started_at": "c",
                "finished_at": "" if status == "running" else "d",
                "risk_events": risk_events or [],
                "output_paths": ["coding_prompt.md", "codex/diff.patch", "codex/implementation_trace.json"],
                "message": "codex finished",
                "metadata": {"files_changed": ["dashboard/app.js"], "failure_category": "runtime_error" if status == "failed" else ""},
            },
            {
                "agent_id": "reviewer",
                "status": "completed" if status != "running" else "pending",
                "started_at": "e",
                "finished_at": "f" if status != "running" else "",
                "risk_events": [],
                "output_paths": ["review_report.md"],
                "message": "reviewed",
                "metadata": {},
            },
            {
                "agent_id": "verifier",
                "status": "completed" if status == "completed" else "pending",
                "started_at": "g",
                "finished_at": "h" if status == "completed" else "",
                "risk_events": [],
                "output_paths": ["test_report.md"],
                "message": "tested",
                "metadata": {},
            },
        ],
        "gate_results": [
            {
                "gate_id": "before_coding",
                "status": "passed",
                "required_artifacts": ["prd.md", "tech_spec.md", "ui_spec.md", "eval.md"],
                "missing_artifacts": [],
                "checked_at": "2026-05-28T00:00:10+00:00",
                "before_agent": "coder",
            }
        ],
        "artifacts": {
            "prd.md": "prd.md",
            "tech_spec.md": "tech_spec.md",
            "ui_spec.md": "ui_spec.md",
            "eval.md": "eval.md",
            "diff.patch": "codex/diff.patch",
            "implementation_trace.json": "codex/implementation_trace.json",
            "review_report.md": "review_report.md",
            "test_report.md": "test_report.md",
            "final_report.md": "final_report.md",
        },
        "risk_events": risk_events or [],
    }
    (run_dir / "team_run_record.json").write_text(json.dumps(record), encoding="utf-8")
    (run_dir / "events.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"event": "run_started", "run_id": run_id}),
                json.dumps({"event": "agent_started", "agent_id": "coder"}),
                json.dumps({"event": "run_failed" if status == "failed" else "run_completed", "run_id": run_id}),
                json.dumps({"event": "secret", "value": f"token={secret}"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "prd.md").write_text("# PRD\n\n目标是改善 Dashboard 可观测验收。\n", encoding="utf-8")
    (run_dir / "tech_spec.md").write_text("# Tech Spec\n\n修改 dashboard 状态模型。\n", encoding="utf-8")
    (run_dir / "ui_spec.md").write_text("# UI Spec\n\nDashboard 增加友好提示。\n", encoding="utf-8")
    (run_dir / "eval.md").write_text("# Eval\n\n运行 dashboard 单测。\n", encoding="utf-8")
    (run_dir / "review_report.md").write_text("# Review Report\n\nNo blocking bugs.\n", encoding="utf-8")
    (run_dir / "test_report.md").write_text("# Test Report\n\npython3 -m unittest tests.test_dashboard -v -> exit 0。\n", encoding="utf-8")
    (run_dir / "final_report.md").write_text("# Final Report\n\n交付可采纳。\n", encoding="utf-8")
    (codex_dir / "implementation_trace.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "completed" if status == "completed" else status,
                "evidence": {
                    "changed_files": ["dashboard/app.js"],
                    "tests_run": ["python3 -m unittest tests.test_dashboard -v"],
                    "diff_path": "codex/diff.patch",
                    "exit_code": 0 if status == "completed" else 1,
                },
                "risk_events": risk_events or [],
                "blockers": ["codex_exit_code:1"] if status == "failed" else [],
                "next_action": "review",
            }
        ),
        encoding="utf-8",
    )
    (codex_dir / "diff.patch").write_text(
        "\n".join(
            [
                "diff --git a/dashboard/app.js b/dashboard/app.js",
                "--- a/dashboard/app.js",
                "+++ b/dashboard/app.js",
                "@@ -1 +1 @@",
                f"-old {secret}",
                "+new value",
            ]
        ),
        encoding="utf-8",
    )
    (codex_dir / "stdout.jsonl").write_text(f"raw stdout {secret}\n", encoding="utf-8")
    (run_dir / "coding_prompt.md").write_text(f"# Prompt\n\n{secret}\n", encoding="utf-8")
    (acceptance_dir / "status.json").write_text(
        json.dumps({"schema_version": 1, "status": "completed" if status == "completed" else "not_started", "applied": status == "completed"}),
        encoding="utf-8",
    )
    return run_dir


class TeamRetrospectiveTests(unittest.TestCase):
    def test_generate_run_retrospective_writes_markdown_and_learning_summary(self) -> None:
        from growth_dev.team.retrospective import generate_run_retrospective

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            _write_retrospective_run(runs_dir, "retro-run-1")

            result = generate_run_retrospective("retro-run-1", runs_dir=runs_dir)
            run_dir = runs_dir / "retro-run-1"
            learning = json.loads((run_dir / "learning_summary.json").read_text(encoding="utf-8"))
            retrospective = (run_dir / "retrospective.md").read_text(encoding="utf-8")
            combined = json.dumps(learning, ensure_ascii=False) + retrospective

        self.assertEqual(result["run_id"], "retro-run-1")
        self.assertEqual(result["artifacts"]["retrospective"], "retrospective.md")
        self.assertEqual(result["artifacts"]["learning_summary"], "learning_summary.json")
        for key in (
            "schema_version",
            "run_id",
            "domain_id",
            "status",
            "task_type",
            "outcome",
            "quality_findings",
            "implementation_findings",
            "review_test_findings",
            "failure_modes",
            "recommended_skills",
            "reusable_context",
            "avoid_context",
            "next_time_checklist",
            "source_artifacts",
        ):
            self.assertIn(key, learning)
        for section in (
            "## 本次任务类型",
            "## 结果结论",
            "## 关键证据",
            "## 成功因素 / 失败原因",
            "## 产物质量观察",
            "## AI 实现观察",
            "## Review/Test 观察",
            "## 推荐 Project Skills",
            "## 下次上下文策略",
            "## 可沉淀经验",
        ):
            self.assertIn(section, retrospective)
        self.assertIn("context_engineering", learning["recommended_skills"])
        self.assertIn("code_review_and_quality", learning["recommended_skills"])
        self.assertNotIn("sk-should-not-export", combined)
        self.assertNotIn("raw stdout sk-", combined)
        self.assertNotIn("-old", combined)
        self.assertNotIn("# Prompt", combined)

    def test_generate_run_retrospective_marks_running_runs_incomplete_and_failed_runs_with_failure_mode(self) -> None:
        from growth_dev.team.retrospective import generate_run_retrospective

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            _write_retrospective_run(runs_dir, "running-run", status="running")
            _write_retrospective_run(runs_dir, "failed-run", status="failed", risk_events=["codex_exit_code:1"])

            running = generate_run_retrospective("running-run", runs_dir=runs_dir)["learning_summary"]
            failed = generate_run_retrospective("failed-run", runs_dir=runs_dir)["learning_summary"]

        self.assertEqual(running["outcome"], "incomplete_observation")
        self.assertIn("incomplete_observation", running["failure_modes"])
        self.assertEqual(failed["outcome"], "failed_needs_recovery")
        self.assertIn("codex_exit_code:1", failed["failure_modes"])
        self.assertIn("debugging_and_error_recovery", failed["recommended_skills"])

    def test_generate_run_retrospective_writes_finish_learning_suggestions(self) -> None:
        from growth_dev.team.retrospective import generate_run_retrospective

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = _write_retrospective_run(runs_dir, "finish-learning-run")
            requirements_dir = run_dir / "requirements"
            requirements_dir.mkdir(exist_ok=True)
            (requirements_dir / "capability_boundary.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": "finish-learning-run",
                        "change_type": "extend_existing_capability",
                        "required_new_capabilities": [{"id": "task_workspace", "summary": "Expose task workspace."}],
                    }
                ),
                encoding="utf-8",
            )

            result = generate_run_retrospective("finish-learning-run", runs_dir=runs_dir)
            suggestions = json.loads((run_dir / "finish_learning_suggestions.json").read_text(encoding="utf-8"))
            suggestions_md = (run_dir / "finish_learning_suggestions.md").read_text(encoding="utf-8")
            retrospective = (run_dir / "retrospective.md").read_text(encoding="utf-8")

        self.assertEqual(result["artifacts"]["finish_learning_suggestions"], "finish_learning_suggestions.md")
        self.assertTrue((suggestions["capability_update_suggestions"]))
        self.assertTrue((suggestions["skill_update_suggestions"]))
        self.assertIn("Capability / Skill Update Suggestions", suggestions_md)
        self.assertIn("## Capability / Skill Update Suggestions", retrospective)

    def test_recommended_skills_are_registered_active_skill_ids(self) -> None:
        from growth_dev.team.retrospective import generate_run_retrospective

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            _write_retrospective_run(runs_dir, "skill-run")

            learning = generate_run_retrospective("skill-run", runs_dir=runs_dir)["learning_summary"]

        registry_text = (Path(__file__).resolve().parents[1] / "skills" / "registry.yaml").read_text(encoding="utf-8")
        active_ids = set()
        for line in registry_text.splitlines():
            if line.startswith("  - id: "):
                active_ids.add(line.removeprefix("  - id: ").strip())
        self.assertTrue(set(learning["recommended_skills"]).issubset(active_ids))

    def test_cli_retrospective_generate_run_id_and_all(self) -> None:
        from growth_dev.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            _write_retrospective_run(runs_dir, "old-run", status="completed")
            _write_retrospective_run(runs_dir, "new-run", status="completed")

            with _captured_output() as (stdout, stderr):
                exit_code = main(["team", "retrospective", "generate", "--run-id", "new-run", "--runs-dir", str(runs_dir)])
            new_exists_after_single = (runs_dir / "new-run" / "retrospective.md").exists()
            with _captured_output() as (all_stdout, all_stderr):
                all_exit_code = main(["team", "retrospective", "generate", "--all", "--limit", "2", "--runs-dir", str(runs_dir)])
            new_exists_after_all = (runs_dir / "new-run" / "retrospective.md").exists()
            old_exists_after_all = (runs_dir / "old-run" / "learning_summary.json").exists()

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("new-run", stdout.getvalue())
        self.assertTrue(new_exists_after_single)
        self.assertEqual(all_exit_code, 0)
        self.assertEqual(all_stderr.getvalue(), "")
        self.assertIn("old-run", all_stdout.getvalue())
        self.assertTrue(new_exists_after_all)
        self.assertTrue(old_exists_after_all)


if __name__ == "__main__":
    unittest.main()
