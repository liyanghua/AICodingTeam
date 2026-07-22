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

    def test_report_generator_shell_config_instantiates_shell_app(self) -> None:
        from growth_dev.team.app_generation import generate_deterministic_app_files

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run"
            run_dir.mkdir()
            output_schema = {
                "id": "top_products_table",
                "status": "available",
                "source": "test",
                "schema": {
                    "type": "object",
                    "properties": {
                        "rows": {"type": "array", "items": {"type": "object"}},
                        "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "summary": {
                    "id": "top_products_table",
                    "status": "available",
                    "source": "test",
                    "title": "TOP 商品表",
                    "description": "测试产物",
                    "properties": ["evidence_ids", "rows"],
                    "required": [],
                },
            }
            output_model = {
                "outputs": [
                    {
                        "id": "top_products_table",
                        "title": "TOP 商品表",
                        "description": "测试产物",
                        "status": "available",
                        "source": "test",
                        "schema": output_schema["schema"],
                        "summary": output_schema["summary"],
                    }
                ]
            }
            required_data = {
                "id": "top_products_csv",
                "status": "available",
                "description": "TOP 商品 CSV",
                "required_fields": ["rank", "product_url"],
                "freshness": "30d",
                "effective_mode": "manual_upload_only",
                "evidence_required": ["source_name"],
                "preferred_sources": ["internal_dw.top_products"],
                "fallback_sources": ["manual_upload.top_products_csv"],
                "tool_binding": {
                    "data_requirement_id": "top_products_csv",
                    "declared_primary_tool": "internal_dw.top_products",
                    "declared_fallback_tools": ["manual_upload.top_products_csv"],
                    "effective_mode": "manual_upload_only",
                    "status": "available",
                },
            }
            view_model = {
                "input_model": {"mode": "manual_upload", "required_data": [required_data], "fields": []},
                "output_model": output_model,
                "execution_model": {
                    "state_machine": ["idle", "waiting_input", "running", "done", "degraded", "failed"],
                    "can_run_when": ["required_data_uploaded"],
                    "degraded_when": ["missing_data"],
                },
                "evidence_model": {"contract": {"required": ["source_data"]}, "required": ["source_data"]},
                "tool_model": {"effective_mode": "manual_upload_only", "bindings": [required_data["tool_binding"]]},
                "source_trace": {
                    "workflow_ref": "skill_snapshot/workflow.dag.yaml",
                    "data_requirement_refs": ["skill_snapshot/data_requirements.yaml#top_products_csv"],
                    "output_schema_refs": ["skill_snapshot/output_schemas/top_products_table.json"],
                    "tool_binding_refs": ["skill_snapshot/tool_bindings.yaml#top_products_csv"],
                    "evidence_ref": "skill_snapshot/evidence_schema.yaml",
                },
                "business_context": {
                    "status": "missing",
                    "query": "流程1:上传 TOP 商品的具体内容",
                    "mode": "local-skills.strategy_kb_search",
                    "kb_manifest": "",
                    "collection_id": "",
                    "backend": "",
                    "results": [],
                    "warnings": ["strategy_kb_not_configured"],
                },
                "node_execution_view": {
                    "status": "missing",
                    "workflow_no": 1,
                    "workflow_title": "上传 TOP 商品",
                    "goal": {"title": "目的", "markdown": ""},
                    "action": {"title": "执行动作", "markdown": "", "steps": [], "fields": []},
                    "verification": {"title": "验证标准", "markdown": "", "checks": []},
                    "artifact": {"title": "TOP 商品表", "markdown": "", "outputs": output_model["outputs"]},
                    "agent_assist": {"mode": "context_only", "prompt": "辅助用户完成节点。", "suggested_questions": []},
                    "source": {"doc_id": "", "doc_title": "", "source_path": "", "kb_page_id": "", "citation_id": ""},
                },
            }
            app_config = {
                "schema_version": "app-config-v1",
                "app_slug": "market-insight",
                "shell_kind": "report_generator",
                "shell_version": "0.1.0",
                "data_capability_index": {
                    "provider": "api_doc_index",
                    "status": "available",
                    "source_index_ref": "data_capability/api_doc_index.json",
                    "runtime_index_ref": "data/api_doc_index.json",
                    "default_strategy": "field_coverage_rerank",
                    "stats": {"api_count": 1, "field_count": 2},
                    "sources": [],
                },
                "skill_ref": {"skill_id": "market_insight_skill", "snapshot_dir": "skill_snapshot"},
                "task_ref": {"task_id": "market-insight", "title": "市场洞察报告"},
                "scope_form": {"fields": []},
                "nodes": [
                    {
                        "id": "top_products",
                        "name": "上传 TOP 商品",
                        "kind": "data",
                        "depends_on": [],
                        "data_requirements": ["top_products_csv"],
                        "outputs": ["top_products_table"],
                        "output_schema": [output_schema],
                        "state_machine": ["idle", "waiting_input", "running", "done", "degraded", "failed"],
                        **view_model,
                    },
                ],
                "aggregate": {"node_id": "final_report"},
                "data_requirements": [{"id": "top_products_csv", "title": "TOP 商品 CSV"}],
                "rules": {"hard_requirements": [], "registry": []},
                "tool_bindings": [{"data_requirement_id": "top_products_csv", "effective_mode": "manual_upload_only"}],
                "evidence": {"schema": {}},
                "safety": {"forbidden": ["database"]},
                "customizations": [],
            }
            ensure_index_dir = run_dir / "data_capability"
            ensure_index_dir.mkdir()
            (ensure_index_dir / "api_doc_index.json").write_text(
                json.dumps(
                    {
                        "schema_version": "api-doc-index-v1",
                        "apis": [
                            {
                                "api_id": "top300_product_analysis",
                                "source_seq": 1,
                                "name": "类目前300商品分析",
                                "module": "fixture",
                                "business_module": "商品分析",
                                "analysis_domain": "商品域",
                                "method": "POST",
                                "path": "/top300_product_analysis",
                                "verified_status": "success",
                                "request_params": [{"name": "deal_date", "type": "string", "required": True, "description": "交易日期"}],
                                "request_headers": [],
                                "response_fields": [
                                    {"path": "data.result[].rank", "name": "rank", "type": "number", "description": "排名"},
                                    {"path": "data.result[].product_url", "name": "product_url", "type": "string", "description": "商品链接"},
                                ],
                                "source_refs": {},
                                "parse_warnings": [],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (run_dir / "app.config.json").write_text(json.dumps(app_config), encoding="utf-8")
            contract = {
                "app_slug": "market-insight",
                "generated_app_dir": "generated_apps/market-insight",
                "shell_kind": "report_generator",
                "app_config_ref": "app.config.json",
                "preview": {"url": "http://127.0.0.1:8788", "command": "node server.js"},
            }

            files_changed = generate_deterministic_app_files(
                run_dir=run_dir,
                app_slug="market-insight",
                prd_text="# 市场洞察报告",
                contract=contract,
                repo_root=run_dir,
            )

            app_dir = run_dir / "generated_apps" / "market-insight"
            server_js = (app_dir / "server.js").read_text(encoding="utf-8")
            app_js = (app_dir / "public" / "app.js").read_text(encoding="utf-8")
            copied_config = json.loads((app_dir / "app.config.json").read_text(encoding="utf-8"))
            generated_files_exist = {
                "index": (app_dir / "public" / "index.html").exists(),
                "styles": (app_dir / "public" / "styles.css").exists(),
                "db_worker": (app_dir / "db_archaeologist_worker.mjs").exists(),
                "collaboration_store": (app_dir / "collaboration_store.js").exists(),
                "gene_analysis_store": (app_dir / "gene_analysis_store.js").exists(),
                "engine": (app_dir / "engine" / "rules.py").exists(),
                "runtime_smoke": (app_dir / "runtime_smoke.js").exists(),
                "api_doc_index": (app_dir / "data" / "api_doc_index.json").exists(),
                "fixture_artifacts": (app_dir / "artifacts" / "fixture_outputs.json").exists(),
                "evidence_pack": (app_dir / "evidence" / "evidence_pack.json").exists(),
                "final_report": (app_dir / "final_report.md").exists(),
            }
            fixture_artifacts = json.loads((app_dir / "artifacts" / "fixture_outputs.json").read_text(encoding="utf-8"))
            evidence_pack = json.loads((app_dir / "evidence" / "evidence_pack.json").read_text(encoding="utf-8"))
            final_report = (app_dir / "final_report.md").read_text(encoding="utf-8")
            runtime_smoke = (app_dir / "runtime_smoke.js").read_text(encoding="utf-8")

        self.assertIn("api/config", server_js)
        self.assertIn("/api/db-agent/status", server_js)
        self.assertIn("/api/db-agent/query", server_js)
        self.assertIn("renderNodeList", app_js)
        self.assertIn("renderInputModel", app_js)
        self.assertIn("renderOutputModel", app_js)
        self.assertIn("renderExecutionView", app_js)
        self.assertIn("renderAnalysisCollaborationAgent", app_js)
        self.assertIn("分析协作 Agent", app_js)
        self.assertIn("nodeDrafts", app_js)
        self.assertIn("Source Trace", app_js)
        self.assertEqual(copied_config["shell_kind"], "report_generator")
        self.assertEqual(copied_config["data_capability_index"]["runtime_index_ref"], "data/api_doc_index.json")
        self.assertEqual(copied_config["data_capability_index"]["provider"], "api_doc_index")
        self.assertIn("input_model", copied_config["nodes"][0])
        self.assertTrue(copied_config["nodes"][0]["input_model"]["required_data"])
        nodes_with_field_requirements = [
            node for node in copied_config["nodes"]
            if node.get("output_field_requirements")
        ]
        self.assertTrue(nodes_with_field_requirements)
        first_requirement = nodes_with_field_requirements[0]["output_field_requirements"][0]
        for field in ["output_id", "field_path", "field_name", "title", "description", "type", "required", "source_schema_ref"]:
            self.assertIn(field, first_requirement)
        self.assertIn("data_mapping_context", nodes_with_field_requirements[0])
        analysis_nodes = [
            node for node in copied_config["nodes"]
            if node.get("analysis_node_view", {}).get("node_kind") == "data_analysis"
        ]
        self.assertTrue(analysis_nodes)
        analysis_view = analysis_nodes[0]["analysis_node_view"]
        self.assertEqual(analysis_view["schema_version"], "analysis-node-view-v1")
        self.assertIn("purpose_model", analysis_view)
        self.assertIn("input_model", analysis_view)
        self.assertIn("execution_plan", analysis_view)
        self.assertIn("data_output_model", analysis_view)
        self.assertIn("insight_output_model", analysis_view)
        self.assertTrue(generated_files_exist["index"])
        self.assertTrue(generated_files_exist["styles"])
        self.assertTrue(generated_files_exist["db_worker"])
        self.assertTrue(generated_files_exist["collaboration_store"])
        self.assertTrue(generated_files_exist["engine"])
        self.assertTrue(generated_files_exist["runtime_smoke"])
        self.assertTrue(generated_files_exist["api_doc_index"])
        self.assertTrue(generated_files_exist["fixture_artifacts"])
        self.assertTrue(generated_files_exist["evidence_pack"])
        self.assertTrue(generated_files_exist["final_report"])
        self.assertEqual(fixture_artifacts["schema_version"], 1)
        self.assertEqual(evidence_pack["schema_version"], 1)
        self.assertIn("final_report", final_report)
        self.assertIn("assertNodeViewModel", runtime_smoke)
        self.assertIn("output_model", runtime_smoke)
        self.assertIn("required_data", runtime_smoke)
        self.assertIn("node_execution_view", runtime_smoke)
        self.assertIn("buildSmokeArtifact", runtime_smoke)
        self.assertIn("assertUpstreamPropagation", runtime_smoke)
        self.assertIn("upstream_artifacts", runtime_smoke)
        self.assertIn("assertDbAgentStatus", runtime_smoke)
        self.assertIn("assertDataCapabilityIndex", runtime_smoke)
        self.assertIn("api_doc_index", runtime_smoke)
        self.assertIn("assertOutputFieldRequirements", runtime_smoke)
        self.assertIn("assertAnalysisNodeView", runtime_smoke)
        self.assertIn("analysis_node_view", runtime_smoke)
        self.assertIn("output_field_requirements", runtime_smoke)
        self.assertIn("asset_card", runtime_smoke)
        self.assertIn("/api/db-agent/status", runtime_smoke)
        self.assertIn("data_mapping_contract", runtime_smoke)
        self.assertIn("data-mapping-contract-v2", runtime_smoke)
        self.assertIn("suggest_multi_api_mapping", runtime_smoke)
        self.assertIn("field_coverage_plan", runtime_smoke)
        self.assertIn("assertPiAgentAdvice", runtime_smoke)
        self.assertIn("pi-data-mapping-advice-v1", runtime_smoke)
        self.assertIn("/api/pi-agent/query", runtime_smoke)
        self.assertIn("missing-pi-runtime-smoke", runtime_smoke)
        self.assertIn("generated_apps/market-insight/app.config.json", files_changed)
        self.assertIn("generated_apps/market-insight/db_archaeologist_worker.mjs", files_changed)
        self.assertIn("generated_apps/market-insight/gene_analysis_store.js", files_changed)
        self.assertIn("generated_apps/market-insight/shell_version.txt", files_changed)
        self.assertIn("generated_apps/market-insight/runtime_smoke.js", files_changed)
        self.assertIn("generated_apps/market-insight/data/api_doc_index.json", files_changed)
        self.assertIn("generated_apps/market-insight/artifacts/fixture_outputs.json", files_changed)
        self.assertIn("generated_apps/market-insight/evidence/evidence_pack.json", files_changed)
        self.assertIn("generated_apps/market-insight/final_report.md", files_changed)

    def test_report_generator_shell_backfills_legacy_data_requirements_for_analysis_view(self) -> None:
        from growth_dev.team.app_generation import generate_deterministic_app_files

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run"
            run_dir.mkdir()
            output_schema = {
                "id": "top_products_table",
                "status": "available",
                "source": "legacy-fixture",
                "schema": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["rank", "product_url"],
                        "properties": {
                            "rank": {"type": "number", "title": "排名", "description": "商品排名"},
                            "product_url": {"type": "string", "title": "商品链接", "description": "商品详情页"},
                        },
                    },
                },
                "summary": {
                    "id": "top_products_table",
                    "status": "available",
                    "source": "legacy-fixture",
                    "title": "TOP 商品表",
                    "description": "旧 config 产物",
                    "properties": ["rank", "product_url"],
                    "required": ["rank", "product_url"],
                },
            }
            app_config = {
                "schema_version": "app-config-v1",
                "app_slug": "legacy-market-insight",
                "shell_kind": "report_generator",
                "shell_version": "0.1.0",
                "skill_ref": {"skill_id": "legacy_skill", "snapshot_dir": "skill_snapshot"},
                "task_ref": {"task_id": "legacy-market-insight", "title": "市场洞察报告"},
                "scope_form": {"fields": []},
                "nodes": [
                    {
                        "id": "top_products",
                        "name": "上传 TOP 商品",
                        "kind": "data",
                        "depends_on": [],
                        "data_requirements": ["top_products_csv"],
                        "outputs": ["top_products_table"],
                        "output_schema": [output_schema],
                        "output_model": {
                            "outputs": [
                                {
                                    "id": "top_products_table",
                                    "title": "TOP 商品表",
                                    "description": "旧 config 产物",
                                    "status": "available",
                                    "source": "legacy-fixture",
                                    "schema": output_schema["schema"],
                                    "summary": output_schema["summary"],
                                }
                            ]
                        },
                        "input_model": {"mode": "manual_upload", "required_data": [], "fields": []},
                        "execution_model": {"state_machine": [], "can_run_when": [], "degraded_when": []},
                        "evidence_model": {"contract": {}, "required": []},
                        "tool_model": {"effective_mode": "manual_upload_only", "bindings": []},
                        "source_trace": {
                            "workflow_ref": "skill_snapshot/workflow.dag.yaml",
                            "data_requirement_refs": ["skill_snapshot/data_requirements.yaml#top_products_csv"],
                            "output_schema_refs": ["skill_snapshot/output_schemas/top_products_table.json"],
                            "tool_binding_refs": [],
                            "evidence_ref": "skill_snapshot/evidence_schema.yaml",
                        },
                        "business_context": {"status": "missing", "query": "流程1:上传 TOP 商品", "results": []},
                        "node_execution_view": {
                            "status": "missing",
                            "workflow_no": 1,
                            "workflow_title": "上传 TOP 商品",
                            "goal": {"title": "目的", "markdown": ""},
                            "action": {"title": "执行动作", "markdown": "", "steps": [], "fields": []},
                            "verification": {"title": "验证标准", "markdown": "", "checks": []},
                            "artifact": {"title": "TOP 商品表", "markdown": "", "outputs": []},
                            "source": {},
                        },
                    }
                ],
                "aggregate": {"node_id": "final_report"},
                "data_requirements": [
                    {
                        "id": "top_products_csv",
                        "description": "TOP 商品 CSV",
                        "required_fields": ["rank", "product_url"],
                        "freshness": "30d",
                        "evidence_required": ["source_name"],
                        "preferred_sources": ["internal_dw.top_products"],
                        "fallback_sources": ["manual_upload.top_products_csv"],
                    }
                ],
                "rules": {"hard_requirements": [], "registry": []},
                "tool_bindings": [{"data_requirement_id": "top_products_csv", "effective_mode": "manual_upload_only"}],
                "evidence": {"schema": {}},
                "safety": {},
                "customizations": [],
            }
            (run_dir / "app.config.json").write_text(json.dumps(app_config), encoding="utf-8")
            contract = {
                "app_slug": "legacy-market-insight",
                "generated_app_dir": "generated_apps/legacy-market-insight",
                "shell_kind": "report_generator",
                "app_config_ref": "app.config.json",
                "preview": {"url": "http://127.0.0.1:8788", "command": "node server.js"},
            }

            generate_deterministic_app_files(
                run_dir=run_dir,
                app_slug="legacy-market-insight",
                prd_text="# 市场洞察报告",
                contract=contract,
                repo_root=run_dir,
            )

            copied_config = json.loads(
                (run_dir / "generated_apps" / "legacy-market-insight" / "app.config.json").read_text(encoding="utf-8")
            )

        node = copied_config["nodes"][0]
        self.assertTrue(node["input_model"]["required_data"])
        self.assertEqual(node["input_model"]["required_data"][0]["id"], "top_products_csv")
        self.assertEqual(node["analysis_node_view"]["node_kind"], "data_analysis")
        self.assertEqual(
            len(node["analysis_node_view"]["data_output_model"]["fields"]),
            len(node["output_field_requirements"]),
        )


if __name__ == "__main__":
    unittest.main()
