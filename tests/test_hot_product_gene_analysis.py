from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class HotProductGeneAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.app_root = Path(self.temp_dir.name)
        (self.app_root / "artifacts").mkdir()
        (self.app_root / "evidence").mkdir()
        self.runner = self.app_root / "run_gene_analysis.js"
        module_path = Path("shells/report_generator/server/gene_analysis_store.js").resolve()
        self.runner.write_text(
            f"""
const {{ createHotProductGeneAnalysisStore }} = require({json.dumps(str(module_path))});
const fs = require('fs');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const store = createHotProductGeneAnalysisStore({{
  appRoot: payload.app_root,
  artifactsDir: payload.app_root + '/artifacts',
  evidenceDir: payload.app_root + '/evidence',
  defaultAgentModel: 'aicodemirror/gpt-5.6-sol',
}});
const responses = payload.responses || {{}};
const callAgent = async (_node, request) => {{
  const rowId = request.gene_product_context.row_id;
  const value = responses[rowId];
  if (value && value.throw) throw new Error(value.throw);
  return value || {{ ok: false, reason: 'pi_unavailable' }};
}};
(async () => {{
  let result;
  if (payload.action === 'run') result = await store.run(payload.node || {{
    id: 'analyze_hot_product_genes',
    source_trace: {{ workflow_ref: 'skill_snapshot/workflow.dag.yaml', output_schema_refs: ['skill_snapshot/output_schemas/hot_product_gene_table.json'] }},
    analysis_node_view: {{ source_trace: {{
      workflow_ref: 'skill_snapshot/workflow.dag.yaml',
      output_schema_refs: ['skill_snapshot/output_schemas/hot_product_gene_table.json'],
      business_doc_refs: ['business.md#流程3'],
      strategy_kb_refs: ['strategy-ir-flow-3'],
      api_doc_index_ref: 'data/api_doc_index.json'
    }} }}
  }}, callAgent);
  else if (payload.action === 'retry') result = await store.retry(payload.node || {{ id: 'analyze_hot_product_genes' }}, payload.execution_id, callAgent);
  else if (payload.action === 'get') result = store.analysisResponse('analyze_hot_product_genes');
  else if (payload.action === 'confirm') result = store.confirm('analyze_hot_product_genes', payload.confirm || {{}});
  else throw new Error('unknown action');
  process.stdout.write(JSON.stringify({{ ok: true, result }}));
}})().catch(error => {{
  process.stdout.write(JSON.stringify({{ ok: false, code: error.code || error.message, status: error.statusCode || 500 }}));
}});
""",
            encoding="utf-8",
        )

    def _confirmed_table(self, count: int = 10, revision: int = 3) -> dict:
        rows = []
        row_meta = []
        for index in range(count):
            goods_id = str(700000 + index)
            rows.append(
                {
                    "排名": str(index + 1),
                    "商品链接": f"https://item.test/?id={goods_id}",
                    "产品类型": "透明桌垫" if index < 6 else "学生桌垫",
                    "材质": "PVC" if index < 6 else "硅胶",
                    "功能": "防水、防油" if index < 6 else "护眼、防滑",
                    "风格": "简约",
                    "场景": "餐桌" if index < 6 else "书桌",
                    "客单价": str(50 + index),
                    "主卖点": "食品级无味，防油易清洁",
                    "主图元素": "白底产品特写",
                    "是否高增速": "高增" if index < 4 else "微涨",
                    "销量/支付买家数": "2.5万 ~ 5万",
                    "GMV/交易指数": str(1000 - index),
                }
            )
            row_meta.append({"row_id": f"goods:{goods_id}", "source_identity": goods_id, "source_index": index})
        return {
            "schema_version": "data-table-confirmed-v1",
            "node_id": "collect_top_products",
            "status": "confirmed",
            "workspace_revision": revision,
            "rows": rows,
            "row_meta": row_meta,
            "row_count": count,
        }

    def _write_source(self, table: dict) -> None:
        (self.app_root / "artifacts" / "collect_top_products.confirmed_data_table.json").write_text(
            json.dumps(table, ensure_ascii=False), encoding="utf-8"
        )
        (self.app_root / "evidence" / "collect_top_products.data_table_confirmation.json").write_text(
            json.dumps(
                {
                    "schema_version": "data-table-confirmation-v1",
                    "status": "confirmed",
                    "workspace_revision": table.get("workspace_revision"),
                }
            ),
            encoding="utf-8",
        )

    def _call(self, action: str, **extra):
        payload = {"action": action, "app_root": str(self.app_root), **extra}
        completed = subprocess.run(
            ["node", str(self.runner)],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(completed.stdout)

    def _assert_top_level_schema_contract(self, instance: dict) -> None:
        schema = json.loads(
            Path(
                "document-to-skill-engineering-package/skills/market_insight/output_schemas/hot_product_gene_table.json"
            ).read_text(encoding="utf-8")
        )
        self.assertLessEqual(set(schema["required"]), set(instance))
        self.assertLessEqual(set(instance), set(schema["properties"]))
        trace_schema = schema["$defs"]["source_trace"]
        self.assertLessEqual(set(trace_schema["required"]), set(instance["source_trace"]))

    def test_rejects_missing_or_stale_confirmed_source(self) -> None:
        missing = self._call("run")
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["code"], "source_table_not_confirmed")

        table = self._confirmed_table()
        self._write_source(table)
        confirmation = self.app_root / "evidence" / "collect_top_products.data_table_confirmation.json"
        confirmation.write_text(json.dumps({"status": "stale", "workspace_revision": 3}), encoding="utf-8")
        stale = self._call("run")
        self.assertFalse(stale["ok"])
        self.assertEqual(stale["code"], "source_table_not_confirmed")

    def test_builds_nine_dimensions_without_allowing_agent_to_overwrite_facts(self) -> None:
        self._write_source(self._confirmed_table())
        responses = {
            "goods:700000": {
                "ok": True,
                "actual_model": "aicodemirror/gpt-5.6-sol",
                "response_text": json.dumps(
                    {
                        "schema_version": "hot-product-gene-product-proposal-v1",
                        "row_id": "goods:700000",
                        "normalized_dimensions": {
                            "产品类型": ["恶意覆盖产品"],
                            "材质": ["金属"],
                            "功能": ["防油", "防水"],
                            "风格": ["极简"],
                            "人群": ["母婴家庭"],
                            "场景": ["餐桌"],
                            "价格带": ["低价"],
                            "视觉表达": ["白底产品特写"],
                            "流量入口": ["搜索：防油桌垫"],
                        },
                        "derived_fields": {
                            "人群": {"value": "母婴家庭", "confidence": 0.7, "evidence_fields": ["主卖点"]},
                            "流量入口": {"value": "搜索：防油桌垫", "confidence": 0.5, "evidence_fields": ["功能"]},
                        },
                    },
                    ensure_ascii=False,
                ),
            }
        }
        result = self._call("run", responses=responses)["result"]
        self.assertEqual(result["schema_version"], "hot-product-gene-analysis-v1")
        self.assertEqual(result["sample_size"], 10)
        self.assertEqual(result["classification_status"], "insufficient_sample")
        profile = result["product_profiles"][0]
        self.assertEqual(set(profile["dimensions"]), {"产品类型", "材质", "功能", "风格", "人群", "场景", "价格带", "视觉表达", "流量入口"})
        self.assertEqual(profile["dimensions"]["产品类型"]["raw_value"], "透明桌垫")
        self.assertNotIn("恶意覆盖产品", profile["dimensions"]["产品类型"]["normalized_tags"])
        self.assertEqual(profile["dimensions"]["人群"]["source_status"], "pi_derived_unconfirmed")
        self.assertEqual(profile["dimensions"]["流量入口"]["source_status"], "pi_derived_unconfirmed")
        self.assertEqual(profile["dimensions"]["价格带"]["source_status"], "deterministic_relative_band")
        self.assertTrue(all(label["status"] == "insufficient_sample" for group in result["gene_groups"] for label in group["classifications"]))
        strong = next(item for item in result["gene_groups"][0]["classifications"] if item["rule_id"] == "strong_hot_gene")
        self.assertEqual(strong["signals"]["top50_ratio"]["status"], "insufficient_sample")
        self.assertEqual(result["source_trace"]["workflow_ref"], "skill_snapshot/workflow.dag.yaml")
        self.assertEqual(result["source_trace"]["business_doc_refs"], ["business.md#流程3"])
        self.assertEqual(result["source_trace"]["strategy_kb_refs"], ["strategy-ir-flow-3"])
        self.assertEqual(result["source_trace"]["api_doc_index_ref"], "data/api_doc_index.json")

    def test_partial_agent_failure_preserves_profiles_and_marks_missing_derivations(self) -> None:
        self._write_source(self._confirmed_table(count=2))
        result = self._call(
            "run",
            responses={
                "goods:700000": {"ok": False, "reason": "pi_rpc_timeout"},
                "goods:700001": {"throw": "pi crashed"},
            },
        )["result"]
        self.assertEqual(len(result["product_profiles"]), 2)
        self.assertEqual(result["progress"]["failed_products"], 2)
        self.assertEqual(result["product_profiles"][0]["dimensions"]["人群"]["source_status"], "missing")
        self.assertIn("partial_pi_failure", result["risks"])

    def test_strict_metrics_do_not_treat_ranges_or_transaction_index_as_ratios(self) -> None:
        self._write_source(self._confirmed_table(count=50))
        result = self._call("run")["result"]
        group = result["gene_groups"][0]
        self.assertIsNone(group["metrics"]["buyer_ratio"])
        self.assertIsNone(group["metrics"]["gmv_ratio"])
        strong = next(item for item in group["classifications"] if item["rule_id"] == "strong_hot_gene")
        self.assertEqual(strong["signals"]["buyer_ratio"]["status"], "unavailable")
        self.assertEqual(strong["signals"]["gmv_ratio"]["status"], "unavailable")

    def test_retry_only_calls_failed_products_and_preserves_successes(self) -> None:
        self._write_source(self._confirmed_table(count=2))
        first = self._call(
            "run",
            responses={
                "goods:700000": {
                    "ok": True,
                    "response_text": json.dumps(
                        {
                            "row_id": "goods:700000",
                            "derived_fields": {"人群": {"value": "办公人群", "confidence": 0.7, "evidence_fields": ["场景"]}},
                        },
                        ensure_ascii=False,
                    ),
                },
                "goods:700001": {"ok": False, "reason": "pi_rpc_timeout"},
            },
        )["result"]
        self.assertEqual(first["progress"]["completed_products"], 1)
        self.assertEqual(first["progress"]["failed_products"], 1)

        retried = self._call(
            "retry",
            execution_id=first["execution_id"],
            responses={
                "goods:700001": {
                    "ok": True,
                    "response_text": json.dumps(
                        {
                            "row_id": "goods:700001",
                            "derived_fields": {"人群": {"value": "家庭用户", "confidence": 0.7, "evidence_fields": ["场景"]}},
                        },
                        ensure_ascii=False,
                    ),
                }
            },
        )["result"]
        self.assertEqual(retried["product_profiles"][0]["agent_status"], "completed")
        self.assertEqual(retried["product_profiles"][0]["dimensions"]["人群"]["raw_value"], "办公人群")
        self.assertEqual(retried["product_profiles"][1]["agent_status"], "completed")
        self.assertEqual(retried["progress"]["failed_products"], 0)

    def test_retry_does_not_requeue_cancelled_or_completed_profiles(self) -> None:
        self._write_source(self._confirmed_table(count=2))
        first = self._call("run", responses={"goods:700000": {"ok": False}, "goods:700001": {"ok": False}})["result"]
        artifact_path = self.app_root / "artifacts" / "analyze_hot_product_genes.gene_analysis.json"
        stored = json.loads(artifact_path.read_text(encoding="utf-8"))
        stored["product_profiles"][0]["agent_status"] = "cancelled"
        stored["product_profiles"][1]["agent_status"] = "failed"
        artifact_path.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")
        retried = self._call(
            "retry",
            execution_id=first["execution_id"],
            responses={
                "goods:700001": {"ok": True, "response_text": json.dumps({"row_id": "goods:700001", "derived_fields": {}})}
            },
        )["result"]
        self.assertEqual(retried["product_profiles"][0]["agent_status"], "cancelled")
        self.assertEqual(retried["product_profiles"][1]["agent_status"], "completed")

    def test_confirmation_persists_and_becomes_stale_after_source_revision_changes(self) -> None:
        table = self._confirmed_table()
        self._write_source(table)
        draft = self._call("run")["result"]
        confirmed = self._call(
            "confirm",
            confirm={"execution_id": draft["execution_id"], "source_revision": 3, "confirmed_by": "local_user"},
        )["result"]
        self.assertEqual(confirmed["artifact"]["schema_version"], "hot-product-gene-analysis-confirmed-v1")
        self.assertEqual(confirmed["artifact"]["human_confirmation"]["status"], "confirmed")
        self._assert_top_level_schema_contract(confirmed["artifact"])

        table["workspace_revision"] = 4
        self._write_source(table)
        restored = self._call("get")["result"]
        self.assertEqual(restored["analysis"]["status"], "stale")
        self.assertEqual(restored["confirmed_artifact"]["status"], "stale")
        persisted = json.loads(
            (self.app_root / "artifacts" / "analyze_hot_product_genes.confirmed_gene_analysis.json").read_text(encoding="utf-8")
        )
        self.assertEqual(persisted["status"], "stale")
        self.assertEqual(persisted["human_confirmation"]["status"], "stale")

    def test_retry_rejects_changed_source_revision(self) -> None:
        table = self._confirmed_table(count=2, revision=3)
        self._write_source(table)
        first = self._call("run", responses={"goods:700000": {"ok": False}, "goods:700001": {"ok": False}})["result"]
        table["workspace_revision"] = 4
        self._write_source(table)
        retried = self._call("retry", execution_id=first["execution_id"], responses={})
        self.assertFalse(retried["ok"])
        self.assertEqual(retried["code"], "gene_analysis_source_revision_conflict")


if __name__ == "__main__":
    unittest.main()
