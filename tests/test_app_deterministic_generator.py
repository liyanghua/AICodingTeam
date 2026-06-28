from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class DeterministicGeneratorTests(unittest.TestCase):
    def test_generate_deterministic_app_creates_five_required_files(self) -> None:
        from growth_dev.team.app_generation import generate_deterministic_app_files

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run"
            run_dir.mkdir()
            app_slug = "todo-prototype"
            prd_text = "# Todo Prototype\n\n用户可以新增、完成、筛选待办，状态只保存在浏览器本地。"
            contract = {
                "app_slug": app_slug,
                "generated_app_dir": f"generated_apps/{app_slug}",
                "preview": {"url": "http://127.0.0.1:8788", "command": "node server.js"},
            }

            files_changed = generate_deterministic_app_files(
                run_dir=run_dir,
                app_slug=app_slug,
                prd_text=prd_text,
                contract=contract,
                repo_root=run_dir,
            )

            app_dir = run_dir / "generated_apps" / app_slug
            public_dir = app_dir / "public"

            self.assertEqual(len(files_changed), 5)
            self.assertTrue((app_dir / "server.js").exists())
            self.assertTrue((app_dir / "README.md").exists())
            self.assertTrue((public_dir / "index.html").exists())
            self.assertTrue((public_dir / "styles.css").exists())
            self.assertTrue((public_dir / "app.js").exists())

    def test_server_js_uses_node_stdlib_and_extracts_port_from_env(self) -> None:
        from growth_dev.team.app_generation import generate_deterministic_app_files

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run"
            run_dir.mkdir()
            contract = {
                "app_slug": "test-app",
                "generated_app_dir": "generated_apps/test-app",
                "preview": {"url": "http://127.0.0.1:9000", "command": "node server.js"},
            }

            generate_deterministic_app_files(
                run_dir=run_dir,
                app_slug="test-app",
                prd_text="# Test",
                contract=contract,
                repo_root=run_dir,
            )

            server_js = (run_dir / "generated_apps" / "test-app" / "server.js").read_text(encoding="utf-8")

        self.assertIn("require('http')", server_js)
        self.assertIn("require('fs')", server_js)
        self.assertIn("require('path')", server_js)
        self.assertIn("process.env.PREVIEW_PORT", server_js)
        self.assertIn("127.0.0.1", server_js)
        self.assertNotIn("0.0.0.0", server_js)

    def test_index_html_has_doctype_and_app_mount(self) -> None:
        from growth_dev.team.app_generation import generate_deterministic_app_files

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run"
            run_dir.mkdir()
            contract = {"app_slug": "test", "generated_app_dir": "generated_apps/test", "preview": {"url": "http://127.0.0.1:8788"}}

            generate_deterministic_app_files(
                run_dir=run_dir,
                app_slug="test",
                prd_text="# My App\n\nDescription.",
                contract=contract,
                repo_root=run_dir,
            )

            html = (run_dir / "generated_apps" / "test" / "public" / "index.html").read_text(encoding="utf-8")

        self.assertIn("<!doctype html>", html.lower())
        self.assertIn('<div id="app">', html)
        self.assertIn('<script src="app.js">', html)
        self.assertIn("<title>", html)

    def test_app_js_uses_localstorage_with_app_slug_key(self) -> None:
        from growth_dev.team.app_generation import generate_deterministic_app_files

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run"
            run_dir.mkdir()
            contract = {"app_slug": "todo-app", "generated_app_dir": "generated_apps/todo-app", "preview": {"url": "http://127.0.0.1:8788"}}

            generate_deterministic_app_files(
                run_dir=run_dir,
                app_slug="todo-app",
                prd_text="# Todo",
                contract=contract,
                repo_root=run_dir,
            )

            app_js = (run_dir / "generated_apps" / "todo-app" / "public" / "app.js").read_text(encoding="utf-8")

        self.assertIn("localStorage", app_js)
        self.assertIn("todo-app-state", app_js)
        self.assertIn("window.app", app_js)

    def test_styles_css_has_reset_and_basic_layout(self) -> None:
        from growth_dev.team.app_generation import generate_deterministic_app_files

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run"
            run_dir.mkdir()
            contract = {"app_slug": "test", "generated_app_dir": "generated_apps/test", "preview": {"url": "http://127.0.0.1:8788"}}

            generate_deterministic_app_files(
                run_dir=run_dir,
                app_slug="test",
                prd_text="# Test",
                contract=contract,
                repo_root=run_dir,
            )

            css = (run_dir / "generated_apps" / "test" / "public" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("box-sizing", css)
        self.assertIn("margin", css)
        self.assertIn("padding", css)

    def test_readme_contains_run_instructions_and_prd_summary(self) -> None:
        from growth_dev.team.app_generation import generate_deterministic_app_files

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run"
            run_dir.mkdir()
            prd_text = "# My Todo App\n\n这是一个待办应用。\n\n用户可以新增和完成待办。"
            contract = {"app_slug": "my-todo", "generated_app_dir": "generated_apps/my-todo", "preview": {"url": "http://127.0.0.1:8788"}}

            generate_deterministic_app_files(
                run_dir=run_dir,
                app_slug="my-todo",
                prd_text=prd_text,
                contract=contract,
                repo_root=run_dir,
            )

            readme = (run_dir / "generated_apps" / "my-todo" / "README.md").read_text(encoding="utf-8")

        self.assertIn("my-todo", readme)
        self.assertIn("node server.js", readme)
        self.assertIn("127.0.0.1", readme)
        self.assertIn("待办", readme)

    def test_deterministic_coder_calls_generator_for_app_generation_domain(self) -> None:
        from growth_dev.team.agents import AgentContext, run_deterministic_agent
        from growth_dev.team.domain import load_domain_spec
        from growth_dev.team.models import AgentSpec, TeamRunRecord
        from growth_dev.team.runtime import default_team_spec

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run"
            run_dir.mkdir()
            (run_dir / "input_prd.md").write_text("# Todo\n\n待办应用", encoding="utf-8")
            (run_dir / "app_contract.json").write_text(
                json.dumps({"app_slug": "todo", "generated_app_dir": "generated_apps/todo", "preview": {"url": "http://127.0.0.1:8788"}}),
                encoding="utf-8",
            )

            domain = load_domain_spec("app_generation", domains_dir=Path("domains"))
            record = TeamRunRecord(
                run_id="test-run",
                domain_id="app_generation",
                brief="测试",
                status="running",
                executor="deterministic",
            )
            context = AgentContext(
                run_id="test-run",
                brief="测试",
                team=default_team_spec(),
                domain=domain,
                record=record,
                inputs={"app_slug": "todo"},
                run_dir=run_dir,
                repo_root=Path(temp_dir),
                executor="deterministic",
            )

            agent_run = run_deterministic_agent(AgentSpec(id="coder", outputs=["coding_prompt.md", "code_run_record.json"]), context)

            app_dir = run_dir / "generated_apps" / "todo"
            code_record = json.loads((run_dir / "code_run_record.json").read_text(encoding="utf-8"))

            self.assertEqual(agent_run.status, "completed")
            self.assertTrue((app_dir / "server.js").exists())
            self.assertTrue((app_dir / "public" / "index.html").exists())
            self.assertEqual(code_record["executor"], "deterministic")
            self.assertEqual(len(code_record["files_changed"]), 5)
            self.assertTrue(all(path.startswith("generated_apps/todo/") for path in code_record["files_changed"]))


if __name__ == "__main__":
    unittest.main()