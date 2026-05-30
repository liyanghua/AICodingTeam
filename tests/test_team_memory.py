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


def _write_run(
    runs_dir: Path,
    run_id: str,
    *,
    status: str = "completed",
    domain_id: str = "web_monitoring",
    started_at: str = "2026-05-21T05:35:29+00:00",
    finished_at: str = "2026-05-21T05:40:25+00:00",
    changed_files: list[str] | None = None,
    risk_events: list[str] | None = None,
) -> Path:
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    record = {
        "run_id": run_id,
        "team_id": "ai_native_engineering_team",
        "domain_id": domain_id,
        "brief": f"实现 {run_id} 的业务需求",
        "status": status,
        "run_dir": str(run_dir),
        "started_at": started_at,
        "finished_at": finished_at,
        "executor": "codex",
        "executor_config": {
            "model": "gpt-5.5",
            "provider": {
                "name": "aicodemirror",
                "env_key": "AICODEMIRROR_KEY",
                "secret_configured": True,
            },
            "api_key": "api_key=should-not-export",
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
                "status": "completed" if status != "running" else "running",
                "started_at": "c",
                "finished_at": "d" if status != "running" else "",
                "risk_events": risk_events or [],
                "output_paths": ["coding_prompt.md", "code_run_record.json"],
                "message": "code changed",
                "metadata": {"files_changed": changed_files or ["growth_dev/team/memory.py", "tests/test_team_memory.py"]},
            },
            {
                "agent_id": "verifier",
                "status": "completed",
                "started_at": "e",
                "finished_at": "f",
                "risk_events": [],
                "output_paths": ["test_report.md"],
                "message": "tests passed",
                "metadata": {},
            },
        ],
        "gate_results": [
            {
                "gate_id": "before_coding",
                "status": "passed",
                "required_artifacts": ["prd.md", "tech_spec.md", "ui_spec.md", "eval.md"],
                "missing_artifacts": [],
                "checked_at": "2026-05-21T05:35:30+00:00",
                "before_agent": "coder",
            }
        ],
        "artifacts": {
            "prd.md": "prd.md",
            "tech_spec.md": "tech_spec.md",
            "ui_spec.md": "ui_spec.md",
            "eval.md": "eval.md",
            "review_report.md": "review_report.md",
            "test_report.md": "test_report.md",
            "final_report.md": "final_report.md",
            "stdout.jsonl": "codex/stdout.jsonl",
            "diff.patch": "codex/diff.patch",
        },
        "risk_events": risk_events or [],
    }
    (run_dir / "team_run_record.json").write_text(json.dumps(record), encoding="utf-8")
    (run_dir / "events.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"event": "run_started", "run_id": run_id, "created_at": started_at}),
                json.dumps({"event": "agent_started", "agent_id": "coder", "created_at": started_at}),
                json.dumps({"event": "gate_checked", "gate_id": "before_coding", "status": "passed"}),
                json.dumps({"event": "run_completed", "run_id": run_id, "created_at": finished_at}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "prd.md").write_text("# PRD\n\n业务目标已明确。\n", encoding="utf-8")
    (run_dir / "tech_spec.md").write_text("# Tech Spec\n\n使用现有 team runtime。\n", encoding="utf-8")
    (run_dir / "ui_spec.md").write_text("# UI Spec\n\n展示项目演进时间线。\n", encoding="utf-8")
    (run_dir / "eval.md").write_text("# Eval\n\n运行全量 unittest。\n", encoding="utf-8")
    (run_dir / "review_report.md").write_text("# Review\n\nNo findings.\n", encoding="utf-8")
    (run_dir / "test_report.md").write_text("# Test\n\n47 tests passed.\n", encoding="utf-8")
    (run_dir / "final_report.md").write_text("# Final\n\nAICODEMIRROR_KEY=secret-value\n", encoding="utf-8")
    codex_dir = run_dir / "codex"
    codex_dir.mkdir()
    (codex_dir / "stdout.jsonl").write_text("raw secret token=raw-log-secret\n", encoding="utf-8")
    (codex_dir / "diff.patch").write_text("+raw diff line that should not be copied\n", encoding="utf-8")
    (run_dir / "release_readiness.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_id,
                "release_decision": "ready_with_warnings",
                "summary": "核心验收通过，但存在 warning。",
                "blockers": [],
                "warnings": ["文件质量存在 needs_attention"],
                "next_actions": ["人工阅读 pr_draft.md"],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "release_readiness.md").write_text("# Release Readiness\n\nDo not copy full readiness body.\n", encoding="utf-8")
    (run_dir / "pr_draft.md").write_text("# PR Title\n\nDo not copy full PR draft body.\n", encoding="utf-8")
    (run_dir / "github_pr.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_id,
                "status": "created",
                "pr": {"number": 42, "url": "https://github.com/example/project/pull/42", "base": "main", "head": "feature/demo"},
                "warnings": [],
                "blockers": [],
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
                "pr_url": "https://github.com/example/project/pull/42",
                "summary": "1 个 CI check 已通过。",
                "checks": [{"name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS", "url": "https://github.com/example/project/actions/runs/1"}],
                "warnings": [],
                "blockers": [],
                "next_action": "可以进行人工 Review。",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "github_pr.md").write_text("# GitHub Draft PR\n\nDo not copy full PR body.\n", encoding="utf-8")
    (run_dir / "ci_status.md").write_text("# CI Status\n\nDo not copy raw CI logs.\n", encoding="utf-8")
    return run_dir


def _write_learning_summary(
    run_dir: Path,
    *,
    run_id: str,
    domain_id: str = "web_monitoring",
    task_type: str = "dashboard_ui_change",
    outcome: str = "accepted_and_verified",
    recommended_skills: list[str] | None = None,
    reusable_context: list[str] | None = None,
    avoid_context: list[str] | None = None,
    failure_modes: list[str] | None = None,
) -> None:
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "domain_id": domain_id,
        "status": "completed",
        "task_type": task_type,
        "outcome": outcome,
        "quality_findings": {
            "status": "passed",
            "summary": "Dashboard 交付验收状态和空态提示贴合需求。",
            "failed_checks": [],
        },
        "implementation_findings": {
            "changed_files": ["dashboard/index.html", "dashboard/app.js", "tests/test_dashboard.py"],
            "tests_run": ["python3 -m unittest tests.test_dashboard -v"],
            "blockers": [],
            "risk_events": [],
        },
        "review_test_findings": {
            "review_summary": "Review 通过。",
            "test_summary": "Dashboard tests passed.",
            "acceptance_status": "completed",
            "applied": True,
        },
        "failure_modes": failure_modes or [],
        "recommended_skills": recommended_skills or ["context_engineering", "code_review_and_quality", "unknown_skill"],
        "reusable_context": reusable_context or ["dashboard/index.html", "dashboard/app.js", "tests/test_dashboard.py"],
        "avoid_context": avoid_context or ["raw stdout/stderr", ".env/provider secrets"],
        "next_time_checklist": ["先复用 Dashboard 采纳验收状态用例。", "避免注入无关 domain。"],
        "source_artifacts": ["learning_summary.json", "retrospective.md"],
    }
    (run_dir / "learning_summary.json").write_text(json.dumps(payload), encoding="utf-8")


class TeamMemoryTests(unittest.TestCase):
    def test_memory_search_recalls_matching_learning_summaries_and_recommends_active_skills(self) -> None:
        from growth_dev.team.memory_recall import search_memory

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            matching = _write_run(runs_dir, "dashboard-run")
            _write_learning_summary(matching, run_id="dashboard-run")
            unrelated = _write_run(runs_dir, "collector-run", domain_id="xhs_browser_benchmark")
            _write_learning_summary(
                unrelated,
                run_id="collector-run",
                domain_id="xhs_browser_benchmark",
                task_type="collector_fix",
                reusable_context=["growth_dev/xhs_collector.py"],
            )

            result = search_memory(
                "Dashboard 交付验收状态",
                runs_dir=runs_dir,
                domain_id="web_monitoring",
                limit=5,
            )
            payload = json.dumps(result, ensure_ascii=False)

        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["query"], "Dashboard 交付验收状态")
        self.assertEqual(result["matches"][0]["run_id"], "dashboard-run")
        self.assertIn("same_domain", result["matches"][0]["reasons"])
        self.assertIn("context_engineering", [item["id"] for item in result["recommended_skills"]])
        self.assertNotIn("unknown_skill", [item["id"] for item in result["recommended_skills"]])
        self.assertIn("dashboard/index.html", result["context_strategy"]["reuse"])
        self.assertIn("raw stdout/stderr", result["context_strategy"]["avoid"])
        self.assertNotIn("raw diff line", payload)
        self.assertNotIn(".env", payload)

    def test_memory_search_can_refresh_missing_learning_summaries_only_when_requested(self) -> None:
        from growth_dev.team.memory_recall import search_memory

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = _write_run(runs_dir, "missing-summary-run")

            without_refresh = search_memory("memory dashboard", runs_dir=runs_dir, refresh_missing=False)
            exists_without_refresh = (run_dir / "learning_summary.json").exists()
            with_refresh = search_memory("memory dashboard", runs_dir=runs_dir, refresh_missing=True)
            exists_with_refresh = (run_dir / "learning_summary.json").exists()

        self.assertEqual(without_refresh["matches"], [])
        self.assertFalse(exists_without_refresh)
        self.assertTrue(exists_with_refresh)
        self.assertTrue(any(match["run_id"] == "missing-summary-run" for match in with_refresh["matches"]))

    def test_memory_recall_writes_json_and_markdown_artifacts(self) -> None:
        from growth_dev.team.memory_recall import generate_memory_recall

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            source = _write_run(runs_dir, "source-run")
            _write_learning_summary(source, run_id="source-run")
            current = _write_run(runs_dir, "current-run")

            result = generate_memory_recall(
                "Dashboard 交付验收状态",
                run_id="current-run",
                runs_dir=runs_dir,
                domain_id="web_monitoring",
            )
            recall_json = json.loads((current / "memory_recall.json").read_text(encoding="utf-8"))
            recall_md = (current / "memory_recall.md").read_text(encoding="utf-8")

        self.assertEqual(result["artifacts"]["memory_recall"], "memory_recall.md")
        self.assertEqual(recall_json["run_id"], "current-run")
        self.assertTrue(any(match["run_id"] == "source-run" for match in recall_json["matches"]))
        self.assertIn("## 相似历史任务", recall_md)
        self.assertIn("## 推荐 Project Skills", recall_md)
        self.assertIn("source-run", recall_md)

    def test_cli_memory_search_outputs_human_and_json_results(self) -> None:
        from growth_dev.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = _write_run(runs_dir, "cli-memory-run")
            _write_learning_summary(run_dir, run_id="cli-memory-run")

            with _captured_output() as (stdout, stderr):
                exit_code = main(
                    [
                        "team",
                        "memory",
                        "search",
                        "--query",
                        "Dashboard 交付验收状态",
                        "--runs-dir",
                        str(runs_dir),
                    ]
                )
            with _captured_output() as (json_stdout, json_stderr):
                json_exit_code = main(
                    [
                        "team",
                        "memory",
                        "search",
                        "--query",
                        "Dashboard 交付验收状态",
                        "--runs-dir",
                        str(runs_dir),
                        "--json",
                    ]
                )
            parsed = json.loads(json_stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("cli-memory-run", stdout.getvalue())
        self.assertIn("推荐 Project Skills", stdout.getvalue())
        self.assertEqual(json_exit_code, 0)
        self.assertEqual(json_stderr.getvalue(), "")
        self.assertEqual(parsed["matches"][0]["run_id"], "cli-memory-run")

    def test_export_run_writes_obsidian_notes_with_business_sections(self) -> None:
        from growth_dev.team.memory import export_run_to_obsidian

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            vault_dir = root / "vault"
            run_dir = _write_run(runs_dir, "memory-run-1")

            result = export_run_to_obsidian("memory-run-1", runs_dir=runs_dir, vault_dir=vault_dir)

            note_path = vault_dir / "AI Coding Memory" / "Runs" / "memory-run-1.md"
            note_exists = note_path.exists()
            note = note_path.read_text(encoding="utf-8")
            retrospective_exists = (run_dir / "retrospective.md").exists()
            learning_exists = (run_dir / "learning_summary.json").exists()

        self.assertIn("memory-run-1", result["run_ids"])
        self.assertTrue(note_exists)
        self.assertIn("run_id: \"memory-run-1\"", note)
        self.assertIn("domain_id: \"web_monitoring\"", note)
        self.assertIn("status: \"completed\"", note)
        self.assertIn("changed_files:", note)
        self.assertIn("growth_dev/team/memory.py", note)
        self.assertIn("## 本次需求", note)
        self.assertIn("## 阶段时间线", note)
        self.assertIn("## 质量检查与关卡", note)
        self.assertIn("## 任务复盘", note)
        self.assertIn("## 历史任务召回", note)
        self.assertIn("## 发布准备", note)
        self.assertIn("## GitHub PR / CI", note)
        self.assertIn("## 推荐 Project Skills", note)
        self.assertIn("## 下次上下文策略", note)
        self.assertIn("## 本地产物链接", note)
        self.assertIn(run_dir.resolve().as_uri(), note)
        self.assertIn("ready_with_warnings", note)
        self.assertIn("release_readiness.md", note)
        self.assertIn("pr_draft.md", note)
        self.assertIn("https://github.com/example/project/pull/42", note)
        self.assertIn("ci_status.md", note)
        self.assertNotIn("Do not copy full PR draft body", note)
        self.assertNotIn("Do not copy raw CI logs", note)
        self.assertTrue(retrospective_exists)
        self.assertTrue(learning_exists)

    def test_export_redacts_secrets_and_does_not_copy_raw_logs_or_diff(self) -> None:
        from growth_dev.team.memory import export_run_to_obsidian

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            vault_dir = root / "vault"
            _write_run(runs_dir, "safe-run-1", risk_events=["api_key=event-secret"])

            export_run_to_obsidian("safe-run-1", runs_dir=runs_dir, vault_dir=vault_dir)

            memory_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (vault_dir / "AI Coding Memory").rglob("*.md")
            )

        self.assertNotIn("should-not-export", memory_text)
        self.assertNotIn("secret-value", memory_text)
        self.assertNotIn("raw-log-secret", memory_text)
        self.assertNotIn("event-secret", memory_text)
        self.assertNotIn("raw diff line", memory_text)
        self.assertIn("env_key", memory_text)
        self.assertIn("AICODEMIRROR_KEY", memory_text)

    def test_export_supports_failed_and_running_runs(self) -> None:
        from growth_dev.team.memory import export_run_to_obsidian

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            vault_dir = root / "vault"
            _write_run(runs_dir, "failed-run", status="failed", risk_events=["review_failed"])
            _write_run(runs_dir, "running-run", status="running", finished_at="")

            export_run_to_obsidian("failed-run", runs_dir=runs_dir, vault_dir=vault_dir)
            export_run_to_obsidian("running-run", runs_dir=runs_dir, vault_dir=vault_dir)

            failed_note = (vault_dir / "AI Coding Memory" / "Runs" / "failed-run.md").read_text(encoding="utf-8")
            running_note = (vault_dir / "AI Coding Memory" / "Runs" / "running-run.md").read_text(encoding="utf-8")

        self.assertIn('status: "failed"', failed_note)
        self.assertIn("review_failed", failed_note)
        self.assertIn('status: "running"', running_note)
        self.assertIn('finished_at: ""', running_note)

    def test_export_is_idempotent_and_updates_index_timeline_and_domain_notes(self) -> None:
        from growth_dev.team.memory import export_run_to_obsidian

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            vault_dir = root / "vault"
            _write_run(runs_dir, "memory-run-1")

            export_run_to_obsidian("memory-run-1", runs_dir=runs_dir, vault_dir=vault_dir)
            export_run_to_obsidian("memory-run-1", runs_dir=runs_dir, vault_dir=vault_dir)

            base = vault_dir / "AI Coding Memory"
            index = (base / "Index.md").read_text(encoding="utf-8")
            timeline = (base / "Timeline" / "2026-05.md").read_text(encoding="utf-8")
            domain = (base / "Domains" / "web_monitoring.md").read_text(encoding="utf-8")

        self.assertEqual(index.count("[[Runs/memory-run-1|memory-run-1]]"), 1)
        self.assertEqual(timeline.count("[[Runs/memory-run-1|memory-run-1]]"), 1)
        self.assertEqual(domain.count("[[Runs/memory-run-1|memory-run-1]]"), 1)

    def test_export_all_respects_limit_and_recency_order(self) -> None:
        from growth_dev.team.memory import export_recent_runs_to_obsidian

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            vault_dir = root / "vault"
            _write_run(runs_dir, "old-run", started_at="2026-05-01T00:00:00+00:00")
            _write_run(runs_dir, "middle-run", started_at="2026-05-02T00:00:00+00:00")
            _write_run(runs_dir, "new-run", started_at="2026-05-03T00:00:00+00:00")

            result = export_recent_runs_to_obsidian(runs_dir=runs_dir, vault_dir=vault_dir, limit=2)

            base = vault_dir / "AI Coding Memory"
            new_exists = (base / "Runs" / "new-run.md").exists()
            middle_exists = (base / "Runs" / "middle-run.md").exists()
            old_exists = (base / "Runs" / "old-run.md").exists()

        self.assertEqual(result["run_ids"], ["new-run", "middle-run"])
        self.assertTrue(new_exists)
        self.assertTrue(middle_exists)
        self.assertFalse(old_exists)

    def test_cli_memory_export_run_id_and_missing_record(self) -> None:
        from growth_dev.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            vault_dir = root / "vault"
            _write_run(runs_dir, "cli-run-1")

            with _captured_output() as (stdout, stderr):
                exit_code = main(
                    [
                        "team",
                        "memory",
                        "export",
                        "--run-id",
                        "cli-run-1",
                        "--runs-dir",
                        str(runs_dir),
                        "--vault-dir",
                        str(vault_dir),
                    ]
                )
            with _captured_output() as (missing_stdout, missing_stderr):
                missing_exit_code = main(
                    [
                        "team",
                        "memory",
                        "export",
                        "--run-id",
                        "missing-run",
                        "--runs-dir",
                        str(runs_dir),
                        "--vault-dir",
                        str(vault_dir),
                    ]
                )
            cli_note_exists = (vault_dir / "AI Coding Memory" / "Runs" / "cli-run-1.md").exists()

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("cli-run-1", stdout.getvalue())
        self.assertTrue(cli_note_exists)
        self.assertEqual(missing_exit_code, 1)
        self.assertIn("team_run_record.json not found", missing_stderr.getvalue())
        self.assertEqual(missing_stdout.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
