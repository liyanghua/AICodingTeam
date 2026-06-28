from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.test_codex_executor import _init_repo, _run, _write_app_generation_fake_codex


class AppGenerationE2ETests(unittest.TestCase):
    def test_app_generate_cli_runs_codex_e2e_with_local_app_artifacts(self) -> None:
        from growth_dev.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_repo(root)
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_placeholder.py").write_text(
                "import unittest\n\n\nclass PlaceholderTests(unittest.TestCase):\n    def test_placeholder(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            _run(["git", "add", "."], root)
            _run(["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "add tests"], root)
            fake_codex = _write_app_generation_fake_codex(root)
            runs_dir = root / "runs"

            exit_code = main(
                [
                    "app",
                    "generate",
                    "--foreground",
                    "--executor",
                    "codex",
                    "--prd-text",
                    "# Todo Prototype\n\n用户可以新增、完成、筛选待办，状态只保存在浏览器本地。",
                    "--app-slug",
                    "todo-prototype",
                    "--runs-dir",
                    str(runs_dir),
                    "--domains-dir",
                    str(Path.cwd() / "domains"),
                    "--run-id",
                    "app-generation-e2e",
                    "--repo-root",
                    str(root),
                    "--codex-binary",
                    str(fake_codex),
                ]
            )

            run_dir = runs_dir / "app-generation-e2e"
            worktree_app_dir = run_dir / "worktree" / "generated_apps" / "todo-prototype"
            record = json.loads((run_dir / "team_run_record.json").read_text(encoding="utf-8"))
            contract = json.loads((run_dir / "app_contract.json").read_text(encoding="utf-8"))
            code_record = json.loads((run_dir / "code_run_record.json").read_text(encoding="utf-8"))
            verification = json.loads((run_dir / "codex" / "verification_record.json").read_text(encoding="utf-8"))
            preview = (run_dir / "preview_instructions.md").read_text(encoding="utf-8")
            final_report = (run_dir / "final_report.md").read_text(encoding="utf-8")
            app_js = (worktree_app_dir / "public" / "app.js").read_text(encoding="utf-8")
            generated_file_exists = {
                relative_path: (worktree_app_dir / relative_path).exists()
                for relative_path in (
                    "server.js",
                    "README.md",
                    "public/index.html",
                    "public/styles.css",
                    "public/app.js",
                )
            }

        self.assertEqual(exit_code, 0)
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["domain_id"], "app_generation")
        self.assertEqual(contract["target_stack"]["frontend"], "native_spa")
        self.assertEqual(contract["target_stack"]["backend"], "node_stdlib")
        self.assertEqual(contract["target_stack"]["storage"], "localStorage")
        self.assertEqual(contract["target_stack"]["database"], "none")
        self.assertEqual(contract["generated_app_dir"], "generated_apps/todo-prototype")
        for relative_path, exists in generated_file_exists.items():
            with self.subTest(relative_path=relative_path):
                self.assertTrue(exists)
        self.assertTrue(all(path.startswith("generated_apps/todo-prototype/") for path in code_record["files_changed"]))
        self.assertNotIn(".env", "\n".join(code_record["files_changed"]))
        self.assertEqual(verification["status"], "completed")
        self.assertIn("node --check generated_apps/todo-prototype/server.js", [item["command"] for item in verification["commands"]])
        self.assertIn("localStorage", app_js)
        self.assertNotIn("sqlite", app_js.lower())
        self.assertIn("cd generated_apps/todo-prototype", preview)
        self.assertIn("generated_apps/todo-prototype/server.js", final_report)
        self.assertIn("node --check generated_apps/todo-prototype/server.js", final_report)


if __name__ == "__main__":
    unittest.main()
