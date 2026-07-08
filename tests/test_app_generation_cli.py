from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def _market_skill_fixture() -> str:
    primary = Path("document-to-skill-engineering-package/build/market_insight_skill")
    fallback = Path("document-to-skill-engineering-package/build/market_insight_skill_cli_acceptance")
    return str(primary if primary.exists() else fallback)


class AppGenerationCliTests(unittest.TestCase):
    def test_app_generate_passes_task_domain_and_skill_paths_to_inputs(self) -> None:
        from growth_dev import cli

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prd_path = root / "prd.md"
            task_path = root / "task.yaml"
            domain_path = root / "domain.yaml"
            skill_dir = root / "skill-build"
            prd_path.write_text("# PRD\n", encoding="utf-8")
            task_path.write_text("task_id: demo-app\n", encoding="utf-8")
            domain_path.write_text("domain_id: demo\n", encoding="utf-8")
            skill_dir.mkdir()

            captured: dict[str, object] = {}

            def fake_code_alias(args: object) -> int:
                captured["inputs_json"] = getattr(args, "inputs_json")
                captured["domain"] = getattr(args, "domain")
                captured["brief"] = getattr(args, "brief")
                return 0

            with mock.patch.object(cli, "_cmd_code_alias", side_effect=fake_code_alias):
                exit_code = cli.main(
                    [
                        "app",
                        "generate",
                        "--prd-file",
                        str(prd_path),
                        "--app-slug",
                        "demo-app",
                        "--task-yaml-path",
                        str(task_path),
                        "--domain-yaml-path",
                        str(domain_path),
                        "--skill-dir",
                        str(skill_dir),
                    ]
                )

        inputs = json.loads(str(captured["inputs_json"]))
        self.assertEqual(exit_code, 0)
        self.assertEqual(captured["domain"], "app_generation")
        self.assertEqual(captured["brief"], "根据 PRD 生成本地应用：demo-app")
        self.assertEqual(inputs["task_yaml_path"], str(task_path))
        self.assertEqual(inputs["domain_yaml_path"], str(domain_path))
        self.assertEqual(inputs["skill_dir"], str(skill_dir))

    def test_app_generate_passes_strategy_kb_paths_to_inputs(self) -> None:
        from growth_dev import cli

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prd_path = root / "prd.md"
            task_path = root / "task.yaml"
            domain_path = root / "domain.yaml"
            skill_dir = root / "skill-build"
            kb_path = root / "kb_manifest.json"
            query_script = root / "query_strategy_kb.py"
            prd_path.write_text("# PRD\n", encoding="utf-8")
            task_path.write_text("task_id: demo-app\n", encoding="utf-8")
            domain_path.write_text("domain_id: demo\n", encoding="utf-8")
            skill_dir.mkdir()
            kb_path.write_text("{}", encoding="utf-8")
            query_script.write_text("print('{}')\n", encoding="utf-8")

            captured: dict[str, object] = {}

            def fake_code_alias(args: object) -> int:
                captured["inputs_json"] = getattr(args, "inputs_json")
                return 0

            with mock.patch.object(cli, "_cmd_code_alias", side_effect=fake_code_alias):
                exit_code = cli.main(
                    [
                        "app",
                        "generate",
                        "--prd-file",
                        str(prd_path),
                        "--app-slug",
                        "demo-app",
                        "--task-yaml-path",
                        str(task_path),
                        "--domain-yaml-path",
                        str(domain_path),
                        "--skill-dir",
                        str(skill_dir),
                        "--strategy-kb",
                        str(kb_path),
                        "--strategy-kb-query-script",
                        str(query_script),
                        "--strategy-kb-python",
                        sys.executable,
                        "--strategy-kb-top-k",
                        "3",
                    ]
                )

        inputs = json.loads(str(captured["inputs_json"]))
        self.assertEqual(exit_code, 0)
        self.assertEqual(inputs["strategy_kb"], str(kb_path))
        self.assertEqual(inputs["strategy_kb_query_script"], str(query_script))
        self.assertEqual(inputs["strategy_kb_python"], sys.executable)
        self.assertEqual(inputs["strategy_kb_top_k"], 3)

    def test_app_generate_passes_api_doc_index_inputs(self) -> None:
        from growth_dev import cli

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prd_path = root / "prd.md"
            task_path = root / "task.yaml"
            domain_path = root / "domain.yaml"
            skill_dir = root / "skill-build"
            index_path = root / "api_doc_index.json"
            prd_path.write_text("# PRD\n", encoding="utf-8")
            task_path.write_text("task_id: demo-app\n", encoding="utf-8")
            domain_path.write_text("domain_id: demo\n", encoding="utf-8")
            skill_dir.mkdir()
            index_path.write_text('{"apis":[]}', encoding="utf-8")

            captured: dict[str, object] = {}

            def fake_code_alias(args: object) -> int:
                captured["inputs_json"] = getattr(args, "inputs_json")
                return 0

            with mock.patch.object(cli, "_cmd_code_alias", side_effect=fake_code_alias):
                exit_code = cli.main(
                    [
                        "app",
                        "generate",
                        "--prd-file",
                        str(prd_path),
                        "--app-slug",
                        "demo-app",
                        "--task-yaml-path",
                        str(task_path),
                        "--domain-yaml-path",
                        str(domain_path),
                        "--skill-dir",
                        str(skill_dir),
                        "--api-doc-index",
                        str(index_path),
                    ]
                )

        inputs = json.loads(str(captured["inputs_json"]))
        self.assertEqual(exit_code, 0)
        self.assertEqual(inputs["api_doc_index"], str(index_path))

    def test_app_generate_derives_default_skill_dir_from_task_yaml(self) -> None:
        from growth_dev import cli

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task_path = root / "tasks" / "current" / "task.yaml"
            domain_path = root / "tasks" / "current" / "domain.yaml"
            skill_dir = root / "build" / "market_insight_skill"
            task_path.parent.mkdir(parents=True)
            skill_dir.mkdir(parents=True)
            task_path.write_text(
                "task_id: market-insight-report-app\nskill_artifact_dir: build/market_insight_skill\n",
                encoding="utf-8",
            )
            domain_path.write_text("domain_id: market_insight\n", encoding="utf-8")

            captured: dict[str, object] = {}

            def fake_code_alias(args: object) -> int:
                captured["inputs_json"] = getattr(args, "inputs_json")
                return 0

            with mock.patch.object(cli, "_cmd_code_alias", side_effect=fake_code_alias):
                exit_code = cli.main(
                    [
                        "app",
                        "generate",
                        "--prd-text",
                        "# PRD",
                        "--app-slug",
                        "market-insight-report-app",
                        "--task-yaml-path",
                        str(task_path),
                        "--domain-yaml-path",
                        str(domain_path),
                    ]
                )

        inputs = json.loads(str(captured["inputs_json"]))
        self.assertEqual(exit_code, 0)
        self.assertEqual(inputs["skill_dir"], str(skill_dir))

    def test_app_generate_prd_only_does_not_require_default_skill_package(self) -> None:
        from growth_dev import cli

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task_path = root / "tasks" / "current" / "task.yaml"
            domain_path = root / "tasks" / "current" / "domain.yaml"
            task_path.parent.mkdir(parents=True)
            task_path.write_text(
                "task_id: market-insight-report-app\nskill_artifact_dir: missing/skill-build\n",
                encoding="utf-8",
            )
            domain_path.write_text("domain_id: market_insight\n", encoding="utf-8")

            captured: dict[str, object] = {}

            def fake_code_alias(args: object) -> int:
                captured["inputs_json"] = getattr(args, "inputs_json")
                return 0

            with mock.patch.object(cli, "_cmd_code_alias", side_effect=fake_code_alias):
                exit_code = cli.main(
                    [
                        "app",
                        "generate",
                        "--repo-root",
                        str(root),
                        "--prd-text",
                        "# PRD",
                        "--app-slug",
                        "prd-only-app",
                    ]
                )

        inputs = json.loads(str(captured["inputs_json"]))
        self.assertEqual(exit_code, 0)
        self.assertNotIn("task_yaml_path", inputs)
        self.assertNotIn("domain_yaml_path", inputs)
        self.assertNotIn("skill_dir", inputs)

    def test_app_generate_rejects_missing_task_domain_or_skill_path(self) -> None:
        from growth_dev import cli

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task_path = root / "missing-task.yaml"
            domain_path = root / "domain.yaml"
            skill_dir = root / "skill-build"
            domain_path.write_text("domain_id: demo\n", encoding="utf-8")
            skill_dir.mkdir()

            with mock.patch.object(cli, "_cmd_code_alias") as code_alias:
                exit_code = cli.main(
                    [
                        "app",
                        "generate",
                        "--prd-text",
                        "# PRD",
                        "--app-slug",
                        "demo-app",
                        "--task-yaml-path",
                        str(task_path),
                        "--domain-yaml-path",
                        str(domain_path),
                        "--skill-dir",
                        str(skill_dir),
                    ]
                )

        self.assertEqual(exit_code, 2)
        code_alias.assert_not_called()

    def test_appcheck_config_and_acceptance_validate_generated_contract(self) -> None:
        from growth_dev import cli
        from growth_dev.team.app_generation import prepare_app_generation_artifacts

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "market-run"
            prepare_app_generation_artifacts(
                run_id="market-run",
                run_dir=run_dir,
                inputs={
                    "app_slug": "market-insight-report-app",
                    "prd_text": "# 市场分析洞察报告生成器\n\ncustomizations 清单：\n- 位置：aggregate 报告顶部\n- 行为：展示本次分析范围摘要\n- 验收：用户能看到类目与价格带",
                    "task_yaml_path": "tasks/current/task.yaml",
                    "domain_yaml_path": "tasks/current/domain.yaml",
                    "skill_dir": _market_skill_fixture(),
                },
            )

            config_exit = cli.main(["app", "appcheck", "config", "--run-id", "market-run", "--runs-dir", str(runs_dir)])
            acceptance_exit = cli.main(["app", "appcheck", "acceptance", "--run-id", "market-run", "--runs-dir", str(runs_dir)])

        self.assertEqual(config_exit, 0)
        self.assertEqual(acceptance_exit, 0)

    def test_appcheck_config_rejects_rule_registry_drift(self) -> None:
        from growth_dev import cli
        from growth_dev.team.app_generation import prepare_app_generation_artifacts

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_dir = root / "runs"
            run_dir = runs_dir / "market-run"
            prepare_app_generation_artifacts(
                run_id="market-run",
                run_dir=run_dir,
                inputs={
                    "app_slug": "market-insight-report-app",
                    "prd_text": "# PRD",
                    "task_yaml_path": "tasks/current/task.yaml",
                    "domain_yaml_path": "tasks/current/domain.yaml",
                    "skill_dir": _market_skill_fixture(),
                },
            )
            config_path = run_dir / "app.config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["rules"]["registry"][0]["condition"] = "changed threshold >= 999"
            config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

            exit_code = cli.main(["app", "appcheck", "config", "--run-id", "market-run", "--runs-dir", str(runs_dir)])

        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
