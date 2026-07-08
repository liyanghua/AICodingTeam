"""api_doc_matcher/service.py 传输层契约测试。

service.py 是 node 生成 app 以子进程形式复用 matcher.py 的边界；这里验证：
1. stdin/stdout JSON 契约（真实子进程 round-trip）。
2. match_fields 结果与直接调用 match_business_fields 逐字段一致（service 不引入任何自有逻辑）。
3. 主卖点命中 selling_point 别名（命中即填语义）。
4. 派生字段返回 derived_or_manual_required（交由 LLM 派生语义）。
5. 非法请求写 stderr 且非零退出，供 node 侧回退 JS。
6. match_api / match_section 两个 op 的 schema 契约。

fixture 复用 tests/test_api_doc_matcher.py 的文档常量，经 build_index 落盘出真实 api_doc_index.json。
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from api_doc_matcher.agent_adapter import load_api_entries
from api_doc_matcher.indexer import build_index
from api_doc_matcher.matcher import match_business_fields

from api_doc_matcher.section_parser import parse_business_section

from tests.test_api_doc_matcher import DETAIL_DOC, SOURCE_DOC, VALIDATION_DOC


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_service(request: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "api_doc_matcher.service"],
        input=json.dumps(request, ensure_ascii=False),
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


class ApiDocMatcherServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        build_index(
            detail_markdown=DETAIL_DOC,
            validation_markdown=VALIDATION_DOC,
            out_dir=Path(self._tmp.name),
            detail_source_path="detail.md",
            validation_source_path="validation.md",
        )
        self.index_path = str(Path(self._tmp.name) / "api_doc_index.json")

    def test_match_fields_matches_direct_call(self) -> None:
        fields = ["排名", "商品名", "店铺名", {"name": "主卖点", "description": "商品主要卖点"}, "功能"]
        proc = _run_service({"op": "match_fields", "index_path": self.index_path, "fields": fields})
        self.assertEqual(0, proc.returncode, proc.stderr)
        response = json.loads(proc.stdout)

        entries = load_api_entries(self.index_path)
        expected = match_business_fields(entries, fields).to_dict()

        self.assertEqual("business-field-match-v1", response["schema_version"])
        self.assertEqual(expected["matches"], response["matches"])
        self.assertEqual(expected["business_field_coverage_score"], response["business_field_coverage_score"])

    def test_selling_point_matches_and_fills(self) -> None:
        proc = _run_service({
            "op": "match_fields",
            "index_path": self.index_path,
            "fields": [{"name": "主卖点", "description": "商品主要卖点"}],
        })
        self.assertEqual(0, proc.returncode, proc.stderr)
        match = json.loads(proc.stdout)["matches"][0]
        self.assertEqual("主卖点", match["business_field"])
        self.assertEqual("matched", match["status"])
        self.assertEqual("selling_point", match["api_field_name"])
        self.assertTrue(match["api_field_path"])

    def test_derived_field_flagged_for_llm(self) -> None:
        proc = _run_service({
            "op": "match_fields",
            "index_path": self.index_path,
            "fields": ["功能"],
        })
        self.assertEqual(0, proc.returncode, proc.stderr)
        match = json.loads(proc.stdout)["matches"][0]
        self.assertEqual("功能", match["business_field"])
        self.assertEqual("derived_or_manual_required", match["status"])
        self.assertEqual("", match["api_id"])

    def test_match_api_contract(self) -> None:
        proc = _run_service({
            "op": "match_api",
            "index_path": self.index_path,
            "query": "行业大盘与热销商品分析，需要类目排行和商品排行",
            "top_k": 2,
        })
        self.assertEqual(0, proc.returncode, proc.stderr)
        response = json.loads(proc.stdout)
        self.assertEqual("business-api-match-v1", response["schema_version"])
        self.assertGreaterEqual(len(response["matches"]), 1)
        self.assertIn("api_id", response["matches"][0])

    def test_match_section_contract(self) -> None:
        proc = _run_service({
            "op": "match_section",
            "index_path": self.index_path,
            "top_k": 5,
            "section": {
                "title": "商品排行分析",
                "purpose": "输出热销商品排行",
                "output_fields": [
                    {"name": "排名", "description": "商品排名"},
                    {"name": "主卖点", "description": "商品主要卖点"},
                ],
            },
        })
        self.assertEqual(0, proc.returncode, proc.stderr)
        response = json.loads(proc.stdout)
        self.assertIn("business_field_coverage_score", json.dumps(response, ensure_ascii=False))

    def test_match_business_context_returns_complete_field_coverage_plan(self) -> None:
        section = parse_business_section(SOURCE_DOC, "流程2：行业大盘与热销商品分析")
        output_fields = [
            {
                "output_id": "top_300_product_analysis_table",
                "field_path": f"items.properties.field_{index}",
                "field_name": field.name,
                "title": field.name,
                "description": field.description,
                "required": field.required,
                "source_schema_ref": "skill_snapshot/output_schemas/top_300_product_analysis_table.json",
            }
            for index, field in enumerate(section.output_fields)
        ]

        proc = _run_service({
            "op": "match_business_context",
            "index_path": self.index_path,
            "top_k": 5,
            "business_context": {
                "node_id": "collect_top_products",
                "title": section.title,
                "document_text": SOURCE_DOC,
                "purpose": section.purpose,
                "data_sources": section.data_sources,
                "actions": section.actions,
            },
            "output_fields": output_fields,
            "known_params": {"category": "入户地垫", "period": "近30天"},
        })

        self.assertEqual(0, proc.returncode, proc.stderr)
        response = json.loads(proc.stdout)
        self.assertEqual("business-context-field-mapping-v1", response["schema_version"])
        self.assertEqual("collect_top_products", response["node_id"])
        self.assertEqual(17, response["coverage_summary"]["total"])
        self.assertEqual(17, response["coverage_summary"]["mapped"])
        self.assertEqual(0, response["coverage_summary"]["missing_required"])
        self.assertGreaterEqual(len(response["selected_api_ids"]), 1)
        self.assertTrue(response["selected_api_assets"])

        coverage = {item["field_name"]: item for item in response["field_coverage_plan"]}
        self.assertEqual("看视觉表达", coverage["商品主图"]["description"])
        self.assertEqual("api_doc_index", coverage["排名"]["source_kind"])
        self.assertTrue(coverage["排名"]["source_field_path"])
        derived_names = {item["field_name"] for item in response["derived_field_plan"]}
        self.assertEqual(derived_names, {"功能", "风格", "主图元素", "爆款原因"})

    def test_invalid_op_exits_nonzero(self) -> None:
        proc = _run_service({"op": "no_such_op", "index_path": self.index_path})
        self.assertNotEqual(0, proc.returncode)
        self.assertEqual("", proc.stdout)
        self.assertIn("unknown op", proc.stderr)

    def test_missing_index_path_exits_nonzero(self) -> None:
        proc = _run_service({"op": "match_fields", "fields": ["排名"]})
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("index_path is required", proc.stderr)

    def test_nonexistent_index_exits_nonzero(self) -> None:
        proc = _run_service({"op": "match_fields", "index_path": "/no/such/index.json", "fields": ["排名"]})
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("index not found", proc.stderr)


if __name__ == "__main__":
    unittest.main()
