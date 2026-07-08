from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


def _market_skill_fixture() -> str:
    primary = Path("document-to-skill-engineering-package/build/market_insight_skill")
    fallback = Path("document-to-skill-engineering-package/build/market_insight_skill_cli_acceptance")
    return str(primary if primary.exists() else fallback)


class AppGenerationTests(unittest.TestCase):
    def test_app_generation_domain_pack_declares_local_spa_contract(self) -> None:
        from growth_dev.team.domain import load_domain_spec

        domain = load_domain_spec("app_generation", domains_dir=Path("domains"))

        self.assertEqual(domain.domain_id, "app_generation")
        self.assertEqual(domain.defaults["frontend"], "native_spa")
        self.assertEqual(domain.defaults["backend"], "node_stdlib")
        self.assertEqual(domain.defaults["storage"], "localStorage")
        self.assertEqual(domain.defaults["database"], "none")
        self.assertIn("no_database", domain.risk_rules)
        self.assertIn("local_storage_only", domain.risk_rules)
        self.assertIn("generated_apps/", domain.metadata["allowed_paths"])
        self.assertIn("input_prd.md", domain.metadata["required_before_coding_artifacts"])
        self.assertIn("app_contract.json", domain.metadata["required_before_coding_artifacts"])

    def test_app_slug_validation_rejects_path_traversal(self) -> None:
        from growth_dev.team.app_generation import validate_app_slug

        self.assertEqual(validate_app_slug("todo-prototype-1"), "todo-prototype-1")
        for value in ("", "Todo", "../todo", "todo/app", "todo_app", ".todo", "todo.", "todo app", "a" * 65):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_app_slug(value)

    def test_prd_input_writes_input_prd_and_redacts_summary(self) -> None:
        from growth_dev.team.app_generation import prepare_app_generation_artifacts

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            result = prepare_app_generation_artifacts(
                run_id="app-gen-input",
                run_dir=run_dir,
                inputs={
                    "app_slug": "todo-prototype",
                    "prd_text": "# Todo Prototype\n\nUse API_KEY=sk-test-secret123 for the external service.",
                },
            )

            input_prd = (run_dir / "input_prd.md").read_text(encoding="utf-8")
            normalized = (run_dir / "requirements" / "normalized_prd.md").read_text(encoding="utf-8")
            contract = json.loads((run_dir / "app_contract.json").read_text(encoding="utf-8"))

        self.assertIn("Todo Prototype", input_prd)
        self.assertIn("sk-test-secret123", input_prd)
        self.assertIn("Todo Prototype", normalized)
        self.assertNotIn("sk-test-secret123", result["summary"])
        self.assertEqual(result["app_slug"], "todo-prototype")
        self.assertEqual(contract["target_stack"]["frontend"], "native_spa")
        self.assertEqual(contract["target_stack"]["backend"], "node_stdlib")
        self.assertEqual(contract["target_stack"]["storage"], "localStorage")
        self.assertEqual(contract["target_stack"]["database"], "none")
        self.assertIn("runtime_smoke.js", contract["required_files"])
        self.assertIn("node generated_apps/todo-prototype/runtime_smoke.js", contract["verification_commands"])

    def test_benchmark_prd_writes_parity_context(self) -> None:
        from growth_dev.team.app_generation import prepare_app_generation_artifacts

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            result = prepare_app_generation_artifacts(
                run_id="dingdang-benchmark",
                run_dir=run_dir,
                inputs={
                    "app_slug": "dingdang-main-image-agent",
                    "prd_file": "benchmarks/app_generation/dingdang_main_image_agent/input_prd.md",
                },
            )

            benchmark_context = json.loads((run_dir / "benchmark_context.json").read_text(encoding="utf-8"))
            benchmark_markdown = (run_dir / "benchmark_context.md").read_text(encoding="utf-8")
            contract = json.loads((run_dir / "app_contract.json").read_text(encoding="utf-8"))

        self.assertEqual(result["quality_mode"], "benchmark_parity")
        self.assertEqual(benchmark_context["benchmark_id"], "dingdang_main_image_agent")
        self.assertEqual(benchmark_context["quality_mode"], "benchmark_parity")
        self.assertIn("product_image_upload", {item["id"] for item in benchmark_context["required_capabilities"]})
        self.assertIn("reference_image_upload", {item["id"] for item in benchmark_context["required_capabilities"]})
        self.assertIn("image_download", {item["id"] for item in benchmark_context["required_capabilities"]})
        self.assertIn("https://openrouter.ai/api/v1/images", "\n".join(benchmark_context["instructions"]))
        self.assertIn("input_references", "\n".join(benchmark_context["instructions"]))
        self.assertIn("openai/gpt-5.4-image-2", "\n".join(benchmark_context["instructions"]))
        self.assertIn("第 X 张第 Y 层", "\n".join(benchmark_context["instructions"]))
        self.assertIn("Benchmark Parity", benchmark_markdown)
        self.assertIn("https://openrouter.ai/api/v1/images", benchmark_markdown)
        self.assertIn("input_references", benchmark_markdown)
        self.assertIn("第 X 张第 Y 层", benchmark_markdown)
        self.assertEqual(contract["quality_mode"], "benchmark_parity")
        self.assertIn("benchmark_context.json", result["output_paths"])

    def test_prepare_app_generation_artifacts_writes_four_source_config(self) -> None:
        from growth_dev.team.app_generation import prepare_app_generation_artifacts

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "run"
            result = prepare_app_generation_artifacts(
                run_id="market-insight-run",
                run_dir=run_dir,
                inputs={
                    "app_slug": "market-insight-report-app",
                    "prd_text": "# 市场分析洞察报告生成器\n\ncustomizations 清单：\n- 位置：aggregate 报告顶部\n- 行为：展示本次分析范围摘要\n- 验收：用户能看到类目与价格带",
                    "task_yaml_path": "tasks/current/task.yaml",
                    "domain_yaml_path": "tasks/current/domain.yaml",
                    "skill_dir": _market_skill_fixture(),
                },
            )

            app_config = json.loads((run_dir / "app.config.json").read_text(encoding="utf-8"))
            contract = json.loads((run_dir / "app_contract.json").read_text(encoding="utf-8"))
            snapshot_exists = {
                "input_task": (run_dir / "input_task.yaml").exists(),
                "input_domain": (run_dir / "input_domain.yaml").exists(),
                "skill_md": (run_dir / "skill_snapshot" / "SKILL.md").exists(),
                "top_300_schema": (run_dir / "skill_snapshot" / "output_schemas" / "top_300_product_analysis_table.json").exists(),
                "acceptance": (run_dir / "acceptance_criteria.md").exists(),
            }

        self.assertTrue(snapshot_exists["input_task"])
        self.assertTrue(snapshot_exists["input_domain"])
        self.assertTrue(snapshot_exists["skill_md"])
        self.assertTrue(snapshot_exists["top_300_schema"])
        self.assertIn("app.config.json", result["output_paths"])
        self.assertEqual(app_config["schema_version"], "app-config-v1")
        self.assertEqual(app_config["app_slug"], "market-insight-report-app")
        self.assertEqual(app_config["shell_kind"], "report_generator")
        self.assertEqual(len(app_config["nodes"]), 10)
        self.assertEqual(len(app_config["data_requirements"]), 6)
        self.assertEqual(
            [item["id"] for item in app_config["rules"]["hard_requirements"]],
            [
                "required_outputs_present",
                "evidence_required_for_each_conclusion",
                "score_formula_required",
                "no_data_no_strong_claim",
            ],
        )
        self.assertTrue(all(item["effective_mode"] == "manual_upload_only" for item in app_config["tool_bindings"]))
        self.assertEqual(contract["schema_version"], 2)
        self.assertEqual(contract["app_config_ref"], "app.config.json")
        self.assertTrue(snapshot_exists["acceptance"])
        self.assertGreaterEqual(len(contract["acceptance_criteria"]), 4)
        self.assertEqual(
            [
                schema["id"]
                for node in app_config["nodes"]
                for schema in node.get("output_schema", [])
                if schema.get("status") == "missing"
            ],
            [],
        )
        self.assertTrue(
            all(
                schema.get("summary", {}).get("status") == "available"
                for node in app_config["nodes"]
                for schema in node.get("output_schema", [])
            )
        )
        self.assertEqual(app_config["evidence"]["contract"]["required"], app_config["evidence"]["schema"]["required"])
        self.assertIn("source_data", app_config["evidence"]["contract"]["required"])
        data_node = next(node for node in app_config["nodes"] if node["kind"] == "data")
        self.assertIn("input_model", data_node)
        self.assertIn("output_model", data_node)
        self.assertIn("execution_model", data_node)
        self.assertIn("evidence_model", data_node)
        self.assertIn("tool_model", data_node)
        self.assertIn("source_trace", data_node)
        self.assertEqual(data_node["input_model"]["mode"], "manual_upload")
        self.assertTrue(data_node["input_model"]["required_data"])
        self.assertIsInstance(data_node["input_model"]["required_data"][0], dict)
        self.assertEqual(data_node["input_model"]["required_data"][0]["effective_mode"], "manual_upload_only")
        self.assertTrue(data_node["output_model"]["outputs"])
        self.assertIn("schema", data_node["output_model"]["outputs"][0])
        self.assertEqual(data_node["tool_model"]["effective_mode"], "manual_upload_only")
        self.assertTrue(data_node["tool_model"]["bindings"])
        self.assertIn("workflow_ref", data_node["source_trace"])
        self.assertIn("output_schema_refs", data_node["source_trace"])
        self.assertIn("source_data", data_node["evidence_model"]["required"])
        top_products_node = next(node for node in app_config["nodes"] if node["id"] == "collect_top_products")
        business_fields = top_products_node["output_field_requirements"]
        self.assertEqual(
            [field["field_name"] for field in business_fields],
            [
                "排名",
                "店铺名",
                "商品链接",
                "商品主图",
                "销量/支付买家数",
                "GMV/交易指数",
                "客单价",
                "价格带",
                "产品类型",
                "材质",
                "功能",
                "风格",
                "场景",
                "主卖点",
                "主图元素",
                "是否高增速",
                "爆款原因",
            ],
        )
        self.assertTrue(all(field["source"] == "business_doc_output_table" for field in business_fields))
        self.assertEqual(business_fields[3]["description"], "看视觉表达")
        self.assertEqual(business_fields[3]["canonical_field_name"], "product_image")
        self.assertIn("business_doc_ref", business_fields[0]["source_trace"])

    def test_prepare_app_generation_artifacts_adds_strategy_kb_business_context(self) -> None:
        from growth_dev.team.app_generation import prepare_app_generation_artifacts

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            kb_path = root / "kb_manifest.json"
            query_script = root / "query_strategy_kb.py"
            kb_path.write_text("{}", encoding="utf-8")
            query_script.write_text(
                "\n".join(
                    [
                        "import argparse, json",
                        "parser = argparse.ArgumentParser()",
                        "parser.add_argument('--kb')",
                        "parser.add_argument('--query')",
                        "parser.add_argument('--top-k')",
                        "args = parser.parse_args()",
                        "print(json.dumps({",
                        "    'success': True,",
                        "    'query': args.query,",
                        "    'backend': 'openkb',",
                        "    'mode': 'local-artifact-search',",
                        "    'kb_manifest': args.kb,",
                        "    'collection_id': 'marketing-insight-test',",
                        "    'results': [{",
                        "        'rank': 1,",
                        "        'score': 1.0,",
                        "        'doc_id': 'main',",
                        "        'doc_title': '20260519市场分析洞察元策略',",
                        "        'source_path': 'docs/biz_spec/marketing_insight/main.md',",
                        "        'kb_page_id': 'openkb-page-main',",
                        "        'citation_id': 'cite-main-001',",
                        "        'section': '五、具体流程及执行步骤',",
                        "        'passage': '## 流程1：确定分析边界\\n\\n### 1.1 目的\\n\\n先明确分析对象。\\n\\n### 1.2 执行动作\\n\\n先填写《市场洞察项目定义表》。\\n\\n| 字段 | 填写要求 |\\n| --- | --- |\\n| 分析类目 | 精确到三级类目或最小叶子类目 |\\n| 分析产品线 | 例如沙发垫、桌垫、防晒衣、假发、地垫 |\\n| 店铺阶段 | 新店 / 成长期店铺 / 爆款店铺 / 多链接店铺 |\\n| 当前目标 | 新品开发 / 爆款挖掘 / 产品升级 / 竞品突破 |\\n| 当前资源 | 供应链、价格、视觉、投放、品牌、客服等优势 |\\n| 目标价格带 | 低价 / 中价 / 高价 / 生意参谋6个价格带 |\\n| 目标人群 | 已知人群 / 待分析人群 |\\n| 分析周期 | 近7天 / 近30天 / 月维度 / 季节维度 |\\n\\n### 1.3 判断标准\\n\\n| 判断项 | 可落地标准 |\\n| --- | --- |\\n| 类目是否清楚 | 必须精确到三级类目或最小可比类目 |\\n| 产品是否清楚 | 必须明确是做新品、老品升级，还是价格带补位 |\\n| 分析周期是否清楚 | 趋势看7天/30天，主流结构看月度，季节品看去年同期和当季 |\\n| 目标是否清楚 | 最终必须落到做什么产品/怎么定价/怎么表达/打谁 |\\n\\n### 1.4 产出\\n\\n《市场洞察项目定义表》。',",
                        "        'matched_terms': ['确定分析边界'],",
                        "        'page_type': 'workflow_section',",
                        "        'workflow_section': {",
                        "            'workflow_no': 1,",
                        "            'workflow_title': '确定分析边界',",
                        "            'heading': '流程1：确定分析边界',",
                        "            'markdown': '## 流程1：确定分析边界\\n\\n### 1.1 目的\\n\\n先明确分析对象。\\n\\n### 1.2 执行动作\\n\\n先填写《市场洞察项目定义表》。\\n\\n| 字段 | 填写要求 |\\n| --- | --- |\\n| 分析类目 | 精确到三级类目或最小叶子类目 |\\n| 分析产品线 | 例如沙发垫、桌垫、防晒衣、假发、地垫 |\\n| 店铺阶段 | 新店 / 成长期店铺 / 爆款店铺 / 多链接店铺 |\\n| 当前目标 | 新品开发 / 爆款挖掘 / 产品升级 / 竞品突破 |\\n| 当前资源 | 供应链、价格、视觉、投放、品牌、客服等优势 |\\n| 目标价格带 | 低价 / 中价 / 高价 / 生意参谋6个价格带 |\\n| 目标人群 | 已知人群 / 待分析人群 |\\n| 分析周期 | 近7天 / 近30天 / 月维度 / 季节维度 |\\n\\n### 1.3 判断标准\\n\\n| 判断项 | 可落地标准 |\\n| --- | --- |\\n| 类目是否清楚 | 必须精确到三级类目或最小可比类目 |\\n| 产品是否清楚 | 必须明确是做新品、老品升级，还是价格带补位 |\\n| 分析周期是否清楚 | 趋势看7天/30天，主流结构看月度，季节品看去年同期和当季 |\\n| 目标是否清楚 | 最终必须落到做什么产品/怎么定价/怎么表达/打谁 |\\n\\n### 1.4 产出\\n\\n《市场洞察项目定义表》。',",
                        "            'subsections': [",
                        "                {'title': '1.1 目的', 'markdown': '先明确分析对象。'},",
                        "                {'title': '1.2 执行动作', 'markdown': '先填写《市场洞察项目定义表》。\\n\\n| 字段 | 填写要求 |\\n| --- | --- |\\n| 分析类目 | 精确到三级类目或最小叶子类目 |\\n| 分析产品线 | 例如沙发垫、桌垫、防晒衣、假发、地垫 |\\n| 店铺阶段 | 新店 / 成长期店铺 / 爆款店铺 / 多链接店铺 |\\n| 当前目标 | 新品开发 / 爆款挖掘 / 产品升级 / 竞品突破 |\\n| 当前资源 | 供应链、价格、视觉、投放、品牌、客服等优势 |\\n| 目标价格带 | 低价 / 中价 / 高价 / 生意参谋6个价格带 |\\n| 目标人群 | 已知人群 / 待分析人群 |\\n| 分析周期 | 近7天 / 近30天 / 月维度 / 季节维度 |'},",
                        "                {'title': '1.3 判断标准', 'markdown': '| 判断项 | 可落地标准 |\\n| --- | --- |\\n| 类目是否清楚 | 必须精确到三级类目或最小可比类目 |\\n| 产品是否清楚 | 必须明确是做新品、老品升级，还是价格带补位 |\\n| 分析周期是否清楚 | 趋势看7天/30天，主流结构看月度，季节品看去年同期和当季 |\\n| 目标是否清楚 | 最终必须落到做什么产品/怎么定价/怎么表达/打谁 |'},",
                        "                {'title': '1.4 产出', 'markdown': '《市场洞察项目定义表》。'}",
                        "            ],",
                        "            'source_line_start': 111,",
                        "            'source_line_end': 149",
                        "        }",
                        "    }],",
                        "    'warnings': []",
                        "}, ensure_ascii=False))",
                    ]
                ),
                encoding="utf-8",
            )

            run_dir = root / "run"
            prepare_app_generation_artifacts(
                run_id="market-insight-run",
                run_dir=run_dir,
                inputs={
                    "app_slug": "market-insight-report-app",
                    "prd_text": "# 市场分析洞察报告生成器",
                    "task_yaml_path": "tasks/current/task.yaml",
                    "domain_yaml_path": "tasks/current/domain.yaml",
                    "skill_dir": _market_skill_fixture(),
                    "strategy_kb": str(kb_path),
                    "strategy_kb_query_script": str(query_script),
                    "strategy_kb_python": sys.executable,
                    "strategy_kb_top_k": 3,
                },
            )

            app_config = json.loads((run_dir / "app.config.json").read_text(encoding="utf-8"))

        first_node = app_config["nodes"][0]
        context = first_node["business_context"]
        self.assertEqual(context["status"], "available")
        self.assertEqual(context["mode"], "local-skills.strategy_kb_search")
        self.assertEqual(context["query"], "流程1:确定分析边界的具体内容")
        self.assertIn("确定分析边界", context["results"][0]["passage"])
        self.assertEqual(first_node["source_trace"]["strategy_kb_ref"], str(kb_path))
        self.assertEqual(first_node["source_trace"]["strategy_kb_citation_refs"], ["cite-main-001"])
        view = first_node["node_execution_view"]
        self.assertEqual(view["status"], "available")
        self.assertIn("先明确分析对象", view["goal"]["markdown"])
        self.assertEqual(view["action"]["title"], "1.2 执行动作")
        self.assertEqual(
            [field["id"] for field in view["action"]["fields"]],
            ["分析类目", "分析产品线", "店铺阶段", "当前目标", "当前资源", "目标价格带", "目标人群", "分析周期"],
        )
        self.assertEqual(view["artifact"]["title"], "《市场洞察项目定义表》")
        self.assertIn("类目是否清楚", [check["id"] for check in view["verification"]["checks"]])
        self.assertEqual(view["source"]["citation_id"], "cite-main-001")

    def test_prepare_app_generation_artifacts_requires_complete_skill_snapshot(self) -> None:
        from growth_dev.team.app_generation import prepare_app_generation_artifacts

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            skill_dir = root / "skill"
            shutil.copytree(_market_skill_fixture(), skill_dir)
            (skill_dir / "eval_rules.yaml").unlink()
            task_path = root / "task.yaml"
            domain_path = root / "domain.yaml"
            task_path.write_text(Path("tasks/current/task.yaml").read_text(encoding="utf-8"), encoding="utf-8")
            domain_path.write_text(Path("tasks/current/domain.yaml").read_text(encoding="utf-8"), encoding="utf-8")

            with self.assertRaises(ValueError) as ctx:
                prepare_app_generation_artifacts(
                    run_id="market-insight-run",
                    run_dir=root / "run",
                    inputs={
                        "app_slug": "market-insight-report-app",
                        "prd_text": "# PRD",
                        "task_yaml_path": str(task_path),
                        "domain_yaml_path": str(domain_path),
                        "skill_dir": str(skill_dir),
                    },
                )

        self.assertIn("eval_rules.yaml", str(ctx.exception))

    def test_benchmark_parity_verifier_recognizes_realistic_generated_app(self) -> None:
        from growth_dev.team.app_generation import evaluate_benchmark_parity, prepare_app_generation_artifacts

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "run"
            worktree_dir = root / "worktree"
            run_dir.mkdir()
            result = prepare_app_generation_artifacts(
                run_id="dingdang-benchmark",
                run_dir=run_dir,
                inputs={
                    "app_slug": "dingdang-main-image-agent",
                    "prd_file": "benchmarks/app_generation/dingdang_main_image_agent/input_prd.md",
                },
            )
            contract = result["app_contract"]
            app_dir = worktree_dir / contract["generated_app_dir"]
            (app_dir / "public").mkdir(parents=True)
            (app_dir / ".env.example").write_text(
                "\n".join(
                    [
                        "IMAGE_PROVIDER=openai",
                        "OPENAI_API_KEY=sk-your-openai-key",
                        "OPENROUTER_API_KEY=sk-or-your-openrouter-key",
                    ]
                ),
                encoding="utf-8",
            )
            (app_dir / "public" / "index.html").write_text(
                """
                <input id="product-image-input" type="file" aria-label="产品图">
                <input id="reference-image-input" type="file" aria-label="参考图">
                <button class="generate-single">生成当前图片</button>
                <button id="batch-generate">批量生成</button>
                <button class="download-prompt">下载 Prompt</button>
                <button class="download-image">下载图片</button>
                """,
                encoding="utf-8",
            )
            (app_dir / "public" / "app.js").write_text(
                """
                async function generateImage(imageId) {
                  await fetch("/api/images/generate", { method: "POST" });
                }
                async function batchGenerate() {
                  for (const item of getImagePlan()) await generateImage(item.id);
                }
                function renderProviderStatus(status) {
                  return status.configured ? "已配置" : "未配置";
                }
                function downloadPrompt() {}
                function downloadImage() {}
                const productImage = "";
                const referenceImage = "";
                // 四阶段工作流: 需求诊断 / 创意方案 / 策略落地 / Prompt 生成
                const stage = { current: "stage_workflow" };
                const taskType = { value: "完整 8 张主图", label: "任务类型" };
                let selectedConcept = null;
                const platforms = ["天猫", "淘宝", "抖音", "拼多多"];
                const main_image_plan = new Array(8); // 8 张主图
                const prompt_layer = { layer1: "", negative_prompt: "" };
                function regenerate_layer(imageIndex, layerIndex) { /* 局部迭代 */ }
                """,
                encoding="utf-8",
            )
            (app_dir / "server.js").write_text(
                """
                const openai = process.env.OPENAI_API_KEY;
                const openrouter = process.env.OPENROUTER_API_KEY;
                const openrouterBase = process.env.OPENROUTER_API_BASE_URL || "https://openrouter.ai/api/v1";
                const body = { input_references: [], model: process.env.OPENROUTER_IMAGE_MODEL || "openai/gpt-5.4-image-2" };
                const path = "/api/v1/images";
                function chooseProvider(provider) {
                  if (!openai && !openrouter) throw new Error("PROVIDER_NOT_CONFIGURED: provider is not configured");
                }
                // POST /api/images/generate
                // GET /api/images/download
                """,
                encoding="utf-8",
            )
            evaluation = evaluate_benchmark_parity(run_dir=run_dir, worktree_dir=worktree_dir, contract=contract)
            agqs = json.loads((run_dir / "agqs_score.json").read_text(encoding="utf-8"))

        self.assertEqual(evaluation["blocking_events"], [])
        self.assertEqual(agqs["hard_gate_status"], "passed")

    def test_benchmark_parity_blocks_openrouter_chat_completions_image_protocol(self) -> None:
        from growth_dev.team.app_generation import evaluate_benchmark_parity, prepare_app_generation_artifacts

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "run"
            worktree_dir = root / "worktree"
            run_dir.mkdir()
            result = prepare_app_generation_artifacts(
                run_id="dingdang-benchmark",
                run_dir=run_dir,
                inputs={
                    "app_slug": "dingdang-main-image-agent",
                    "prd_file": "benchmarks/app_generation/dingdang_main_image_agent/input_prd.md",
                },
            )
            contract = result["app_contract"]
            app_dir = worktree_dir / contract["generated_app_dir"]
            (app_dir / "public").mkdir(parents=True)
            (app_dir / "public" / "index.html").write_text(
                "<input type=\"file\" aria-label=\"产品图\"><input type=\"file\" aria-label=\"参考图\">",
                encoding="utf-8",
            )
            (app_dir / "public" / "app.js").write_text(
                """
                function generateImage(){ return fetch('/api/images/generate'); }
                function batchGenerate(){ return generateImage(); }
                function downloadPrompt(){} function downloadImage(){}
                const stage='需求诊断 创意方案 策略落地';
                const taskType='完整 8 张主图';
                const selectedConcept='A';
                const platforms=['天猫','淘宝','抖音','拼多多'];
                const main_image_plan='8 张';
                const prompt_layer='negative_prompt';
                function regenerate_layer(){ return '局部迭代 第 X 张 第 Y 层 iteration-feedback 重新生成'; }
                """,
                encoding="utf-8",
            )
            (app_dir / "server.js").write_text(
                """
                // POST /api/images/generate via openrouter
                const endpoint = "https://openrouter.ai/api/v1/chat/completions";
                const body = { modalities: ["image", "text"] };
                function setupError(){ throw new Error("PROVIDER_NOT_CONFIGURED: provider is not configured"); }
                """,
                encoding="utf-8",
            )
            (app_dir / ".env.example").write_text("OPENROUTER_API_KEY=sk-or-your-openrouter-key\n", encoding="utf-8")
            evaluation = evaluate_benchmark_parity(run_dir=run_dir, worktree_dir=worktree_dir, contract=contract)

        self.assertIn("benchmark_parity_missing:openrouter_images_endpoint", evaluation["blocking_events"])

    def test_benchmark_parity_accepts_openrouter_base_url_images_composition(self) -> None:
        from growth_dev.team.app_generation import evaluate_benchmark_parity, prepare_app_generation_artifacts

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "run"
            worktree_dir = root / "worktree"
            run_dir.mkdir()
            result = prepare_app_generation_artifacts(
                run_id="dingdang-benchmark",
                run_dir=run_dir,
                inputs={
                    "app_slug": "dingdang-main-image-agent",
                    "prd_file": "benchmarks/app_generation/dingdang_main_image_agent/input_prd.md",
                },
            )
            contract = result["app_contract"]
            app_dir = worktree_dir / contract["generated_app_dir"]
            (app_dir / "public").mkdir(parents=True)
            (app_dir / "public" / "index.html").write_text(
                "<input type=\"file\" aria-label=\"产品图\"><input type=\"file\" aria-label=\"参考图\">",
                encoding="utf-8",
            )
            (app_dir / "public" / "app.js").write_text(
                """
                function generateImage(){ return fetch('/api/images/generate'); }
                function batchGenerate(){ return generateImage(); }
                function downloadPrompt(){} function downloadImage(){}
                const stage='需求诊断 创意方案 策略落地';
                const taskType='完整 8 张主图';
                const selectedConcept='A';
                const platforms=['天猫','淘宝','抖音','拼多多'];
                const main_image_plan='8 张';
                const prompt_layer='negative_prompt';
                function regenerate_layer(){ return '局部迭代 第 X 张 第 Y 层 iteration-feedback 重新生成'; }
                """,
                encoding="utf-8",
            )
            (app_dir / "server.js").write_text(
                """
                // POST /api/images/generate via openrouter
                const OPENROUTER_API_BASE_URL = process.env.OPENROUTER_API_BASE_URL || "https://openrouter.ai/api/v1";
                const endpoint = OPENROUTER_API_BASE_URL + "/images";
                const body = { input_references: [], model: process.env.OPENROUTER_IMAGE_MODEL || "openai/gpt-5.4-image-2" };
                function setupError(){ throw new Error("PROVIDER_NOT_CONFIGURED: provider is not configured"); }
                """,
                encoding="utf-8",
            )
            (app_dir / ".env.example").write_text("OPENROUTER_API_KEY=sk-or-your-openrouter-key\n", encoding="utf-8")
            evaluation = evaluate_benchmark_parity(run_dir=run_dir, worktree_dir=worktree_dir, contract=contract)

        self.assertNotIn("benchmark_parity_missing:openrouter_images_endpoint", evaluation["blocking_events"])

    def test_team_runtime_generates_app_artifacts_before_coding(self) -> None:
        from growth_dev.team.runtime import TeamRuntime

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = TeamRuntime.from_domain(
                "app_generation",
                domains_dir=Path("domains"),
                runs_dir=root / "runs",
                repo_root=Path.cwd(),
            )

            record = runtime.run(
                "根据 PRD 生成本地 Todo 原型应用",
                inputs={
                    "app_slug": "todo-prototype",
                    "prd_text": "# Todo Prototype\n\n用户可以新增、完成、筛选待办，状态保存在浏览器本地。",
                },
                run_id="app-generation-plan",
            )

            run_dir = root / "runs" / "app-generation-plan"
            contract = json.loads((run_dir / "app_contract.json").read_text(encoding="utf-8"))
            coverage = json.loads((run_dir / "planning" / "acceptance_coverage_matrix.json").read_text(encoding="utf-8"))
            gate = next(item for item in record.gate_results if item.gate_id == "complex_task_ready")
            input_prd_exists = (run_dir / "input_prd.md").exists()
            normalized_prd_exists = (run_dir / "requirements" / "normalized_prd.md").exists()

        self.assertEqual(record.status, "completed")
        self.assertTrue(input_prd_exists)
        self.assertTrue(normalized_prd_exists)
        self.assertEqual(contract["generated_app_dir"], "generated_apps/todo-prototype")
        self.assertIn("input_prd.md", gate.required_artifacts)
        self.assertIn("app_contract.json", gate.required_artifacts)
        self.assertTrue(any(item["id"] == "AC-006" for item in coverage["acceptance_criteria"]))

    def test_team_runtime_stops_when_prd_is_missing(self) -> None:
        from growth_dev.team.runtime import TeamRuntime

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = TeamRuntime.from_domain(
                "app_generation",
                domains_dir=Path("domains"),
                runs_dir=root / "runs",
                repo_root=Path.cwd(),
            )

            record = runtime.run(
                "根据 PRD 生成本地应用",
                inputs={"app_slug": "missing-prd"},
                run_id="app-generation-missing-prd",
            )

        self.assertEqual(record.status, "failed")
        self.assertEqual(record.agent_runs[-1].agent_id, "requirements")
        self.assertTrue(record.agent_runs[-1].risk_events)
        self.assertIn("PRD input is required", record.agent_runs[-1].risk_events[0])


if __name__ == "__main__":
    unittest.main()
