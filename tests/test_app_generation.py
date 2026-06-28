from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


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
