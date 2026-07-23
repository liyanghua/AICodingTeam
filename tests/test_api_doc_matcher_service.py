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

from tests.test_api_doc_matcher import (
    CATEGORY_DETAIL_DOC,
    CATEGORY_VALIDATION_DOC,
    DETAIL_DOC,
    SOURCE_DOC,
    VALIDATION_DOC,
)


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

    def _append_monthly_hot_goods_apis(self) -> None:
        index_path = Path(self.index_path)
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        common_request_params = [
            {"name": "cid", "type": "string", "required": True, "description": "类目ID"},
            {"name": "pageNum", "type": "integer", "required": True, "description": "页码"},
            {"name": "pageSize", "type": "integer", "required": True, "description": "每页条数"},
            {"name": "start_date", "type": "string", "required": True, "description": "开始日期"},
            {"name": "end_date", "type": "string", "required": True, "description": "结束日期"},
        ]
        common_response_fields = [
            {"path": "data.result[].rank", "name": "rank", "type": "number", "description": "排名"},
            {"path": "data.result[].goods_id", "name": "goods_id", "type": "string", "description": "商品ID"},
            {"path": "data.result[].goods_url", "name": "goods_url", "type": "string", "description": "商品链接"},
            {"path": "data.result[].goods_img", "name": "goods_img", "type": "string", "description": "商品主图"},
            {"path": "data.result[].shop_name", "name": "shop_name", "type": "string", "description": "店铺名称"},
            {"path": "data.result[].num_payers_interval", "name": "num_payers_interval", "type": "string", "description": "支付买家数区间"},
            {"path": "data.result[].sales_revenue", "name": "sales_revenue", "type": "string", "description": "销售额/GMV"},
            {"path": "data.result[].unit_price", "name": "unit_price", "type": "string", "description": "件单价/客单价"},
            {"path": "data.result[].selling_point", "name": "selling_point", "type": "string", "description": "主卖点"},
            {"path": "data.result[].category_name", "name": "category_name", "type": "string", "description": "类目名称"},
            {"path": "data.result[].cid", "name": "cid", "type": "string", "description": "类目ID"},
            {"path": "data.result[].statist_date", "name": "statist_date", "type": "string", "description": "统计月份"},
        ]
        payload["apis"].extend(
            [
                {
                    "api_id": "data_ads_ind_trade_category_goods_m",
                    "source_seq": 1199,
                    "name": "月-热销商品-按交易总量排序",
                    "module": "行业商品",
                    "business_module": "热销商品",
                    "analysis_domain": "类目商品排行",
                    "method": "POST",
                    "path": "/data/ads_ind_trade_category_goods_m",
                    "verified_status": "success",
                    "request_params": common_request_params,
                    "request_headers": [],
                    "response_fields": common_response_fields,
                    "source_refs": {},
                    "parse_warnings": [],
                },
                {
                    "api_id": "data_ads_ind_sycm_speed_category_goods_m",
                    "source_seq": 1200,
                    "name": "月-热销商品-按交易增速排序",
                    "module": "行业商品",
                    "business_module": "热销商品",
                    "analysis_domain": "类目商品排行",
                    "method": "POST",
                    "path": "/data/ads_ind_sycm_speed_category_goods_m",
                    "verified_status": "success",
                    "request_params": common_request_params,
                    "request_headers": [],
                    "response_fields": [
                        *common_response_fields,
                        {"path": "data.result[].speed_type", "name": "speed_type", "type": "string", "description": "交易增速类型"},
                        {"path": "data.result[].last_month_rank", "name": "last_month_rank", "type": "number", "description": "上月排名"},
                    ],
                    "source_refs": {},
                    "parse_warnings": [],
                },
            ]
        )
        index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _append_product_detail_api(self) -> None:
        index_path = Path(self.index_path)
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        payload["apis"].append(
            {
                "api_id": "data_goods_ads_ind_goods_detail_info_m",
                "source_seq": 1201,
                "name": "商品详情信息查询接口",
                "module": "行业商品",
                "business_module": "商品详情补充",
                "analysis_domain": "商品域",
                "method": "POST",
                "path": "/data/goods/ads_ind_goods_detail_info_m",
                "verified_status": "success",
                "verified_url_path": "/openApi/api/abc/5/data/goods/ads_ind_goods_detail_info_m",
                "response_root": "data.result[]",
                "default_params": {"data_source": "qbt"},
                "request_params": [
                    {"name": "tenantId", "type": "string", "required": True, "description": "租户 ID", "position": "query"},
                    {"name": "goods_id", "type": "string", "required": True, "description": "商品 ID", "position": "query"},
                    {"name": "userId", "type": "string", "required": True, "description": "用户 ID", "position": "query"},
                    {"name": "data_source", "type": "string", "required": True, "description": "数据来源", "position": "query"},
                ],
                "request_headers": ["x-ca-appCodeKey", "x-ca-appCode", "Content-Type"],
                "response_fields": [
                    {"path": "data.result[].goods_id", "name": "goods_id", "type": "string", "description": "商品 ID"},
                    {"path": "data.result[].goods_name", "name": "goods_name", "type": "string", "description": "商品名称"},
                    {"path": "data.result[].core_material", "name": "core_material", "type": "string", "description": "核心材质"},
                    {"path": "data.result[].usage_scene", "name": "usage_scene", "type": "string", "description": "使用场景"},
                    {"path": "data.result[].selling_point_summary", "name": "selling_point_summary", "type": "string", "description": "卖点总结"},
                    {"path": "data.result[].goods_spec_params", "name": "goods_spec_params", "type": "string", "description": "商品规格参数"},
                    {"path": "data.result[].goods_img", "name": "goods_img", "type": "string", "description": "商品图片地址"},
                ],
                "source_refs": {"detail_doc": {"path": "商品详情信息查询接口文档.md", "line": 1}},
                "parse_warnings": [],
            }
        )
        index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _append_product_feedback_apis(self) -> None:
        index_path = Path(self.index_path)
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        common_params = [
            {"name": "goods_id", "type": "string", "required": True, "description": "商品ID"},
            {"name": "goods_id_list", "type": "string/array", "required": True, "description": "商品ID列表"},
            {"name": "pageNum", "type": "integer", "required": True, "description": "页码"},
            {"name": "pageSize", "type": "integer", "required": True, "description": "每页条数"},
        ]
        payload["apis"].extend(
            [
                {
                    "api_id": "get_positive_comment_data",
                    "source_seq": 1250,
                    "name": "获取商品好评数据",
                    "module": "商品反馈",
                    "business_module": "商品评价",
                    "analysis_domain": "评价与问大家",
                    "method": "POST",
                    "path": "/get_positive_comment_data",
                    "verified_status": "success",
                    "request_params": [common_params[1]],
                    "request_headers": [],
                    "response_fields": [
                        {"path": "data.result[].goods_id", "name": "goods_id", "type": "string", "description": "商品ID"},
                        {"path": "data.result[].comment", "name": "comment", "type": "string", "description": "好评内容"},
                    ],
                    "source_refs": {},
                    "parse_warnings": [],
                },
                {
                    "api_id": "product_comment_content2",
                    "source_seq": 1251,
                    "name": "获取商品评论数据",
                    "module": "商品反馈",
                    "business_module": "商品评价",
                    "analysis_domain": "评价与问大家",
                    "method": "POST",
                    "path": "/product_comment_content2",
                    "verified_status": "success",
                    "request_params": common_params,
                    "request_headers": [],
                    "response_fields": [
                        {"path": "data.result[].goods_id", "name": "goods_id", "type": "string", "description": "商品ID"},
                        {"path": "data.result[].comment", "name": "comment", "type": "string", "description": "评论内容"},
                    ],
                    "source_refs": {},
                    "parse_warnings": [],
                },
                {
                    "api_id": "product_question_content2",
                    "source_seq": 1252,
                    "name": "获取问大家分析数据",
                    "module": "商品反馈",
                    "business_module": "问大家",
                    "analysis_domain": "评价与问大家",
                    "method": "POST",
                    "path": "/product_question_content2",
                    "verified_status": "success",
                    "request_params": common_params,
                    "request_headers": [],
                    "response_fields": [
                        {"path": "data.result[].goods_id", "name": "goods_id", "type": "string", "description": "商品ID"},
                        {"path": "data.result[].question_content", "name": "question_content", "type": "string", "description": "问大家问题内容"},
                        {"path": "data.result[].answer_count", "name": "answer_count", "type": "string", "description": "回答数量"},
                    ],
                    "source_refs": {},
                    "parse_warnings": [],
                },
            ]
        )
        index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _append_competitor_landscape_apis(self) -> None:
        index_path = Path(self.index_path)
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        common_request_params = [
            {"name": "cid", "type": "string", "required": True, "description": "类目ID"},
            {"name": "business_date", "type": "string", "required": True, "description": "业务日期"},
            {"name": "start_date", "type": "string", "required": True, "description": "开始日期"},
            {"name": "end_date", "type": "string", "required": True, "description": "结束日期"},
            {"name": "pageNum", "type": "integer", "required": True, "description": "页码"},
            {"name": "pageSize", "type": "integer", "required": True, "description": "每页条数"},
            {"name": "statist_date", "type": "string", "required": True, "description": "统计日期"},
        ]
        response_fields = [
            {"path": "data.result[].goods_id", "name": "goods_id", "type": "string", "description": "商品ID"},
            {"path": "data.result[].shop_name", "name": "shop_name", "type": "string", "description": "店铺名称"},
            {"path": "data.result[].goods_href", "name": "goods_href", "type": "string", "description": "商品链接"},
            {"path": "data.result[].price", "name": "price", "type": "number", "description": "商品价格"},
            {"path": "data.result[].main_sku", "name": "main_sku", "type": "string", "description": "主销SKU"},
            {"path": "data.result[].main_selling_point", "name": "main_selling_point", "type": "string", "description": "主卖点"},
            {"path": "data.result[].main_image_url", "name": "main_image_url", "type": "string", "description": "商品主图"},
            {"path": "data.result[].main_color", "name": "main_color", "type": "string", "description": "主色调"},
            {"path": "data.result[].sales_total", "name": "sales_total", "type": "number", "description": "销量"},
            {"path": "data.result[].sales_ratio", "name": "sales_ratio", "type": "number", "description": "销售占比"},
        ]
        for source_seq, api_id, name in [
            (1260, "data_shop_competition_pattern_analysis_v3", "竞争格局分析-商品查询"),
            (1261, "data_competition_pattern_analysis_v3", "竞争格局分析V3"),
        ]:
            payload["apis"].append(
                {
                    "api_id": api_id,
                    "source_seq": source_seq,
                    "name": name,
                    "module": "竞争格局",
                    "business_module": "竞品分析",
                    "analysis_domain": "竞品与竞店格局分析",
                    "method": "POST",
                    "path": f"/data/{api_id.removeprefix('data_')}",
                    "verified_status": "success",
                    "response_root": "data.result[]",
                    "request_params": common_request_params,
                    "request_headers": [],
                    "response_fields": response_fields,
                    "source_refs": {},
                    "parse_warnings": [],
                }
            )
        payload["apis"].append(
            {
                "api_id": "data_ads_goods_price_range_rank_m",
                "source_seq": 1262,
                "name": "价格带竞争对手分析-商品",
                "module": "价格带",
                "business_module": "价格分析",
                "analysis_domain": "价格带",
                "method": "POST",
                "path": "/data/ads_goods_price_range_rank_m",
                "verified_status": "success",
                "request_params": common_request_params,
                "request_headers": [],
                "response_fields": [
                    {"path": "data.result[].max_price", "name": "max_price", "type": "number", "description": "最高价格"},
                    {"path": "data.result[].shop_name", "name": "shop_name", "type": "string", "description": "店铺名称"},
                ],
                "source_refs": {},
                "parse_warnings": [],
            }
        )
        index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

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

    def test_keyword_semantic_fields_cannot_map_to_numeric_api_metrics(self) -> None:
        proc = _run_service({
            "op": "match_fields",
            "index_path": self.index_path,
            "fields": ["root_terms", "demand_type"],
        })
        self.assertEqual(0, proc.returncode, proc.stderr)
        matches = {item["business_field"]: item for item in json.loads(proc.stdout)["matches"]}
        for field_name in ("root_terms", "demand_type"):
            self.assertEqual("derived_or_manual_required", matches[field_name]["status"])
            self.assertEqual("", matches[field_name]["api_id"])
            self.assertEqual("", matches[field_name]["api_field_path"])

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
        self._append_monthly_hot_goods_apis()
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
            "known_params": {"category": "桌布", "cid": "121458013", "period": "近30天"},
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
        self.assertIn("api_response_field_catalog", response)
        self.assertGreater(len(response["api_response_field_catalog"]), 0)
        self.assertTrue(coverage["商品主图"]["candidate_field_options"])
        self.assertTrue(
            any(
                "pic" in item["source_field_path"].lower()
                or "image" in item["source_field_path"].lower()
                or "picture" in item["source_field_path"].lower()
                or "img" in item["source_field_path"].lower()
                for item in coverage["商品主图"]["candidate_field_options"]
            )
        )
        derived_names = {item["field_name"] for item in response["derived_field_plan"]}
        self.assertEqual(derived_names, {"价格带", "产品类型", "材质", "功能", "风格", "场景", "主图元素", "爆款原因"})

    def test_match_business_context_prefers_category_scoped_api_for_execution(self) -> None:
        index_path = Path(self.index_path)
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        payload["category_entities"] = [
            {
                "canonical_name": "桌布",
                "category_id": "121458013",
                "aliases": [],
                "evidence_count": 2,
                "evidence_texts": ["学生书桌垫桌布", "防水餐桌垫桌布"],
                "evidence_sources": [{"api_id": "data_dim_goods_info"}],
            }
        ]
        index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self._append_monthly_hot_goods_apis()

        proc = _run_service({
            "op": "match_business_context",
            "index_path": self.index_path,
            "top_k": 8,
            "business_context": {
                "node_id": "collect_top_products",
                "title": "行业大盘与热销商品分析",
                "purpose": "输出指定类目的热销商品排行",
                "data_sources": ["行业商品数据"],
                "actions": ["导出类目商品榜单"],
            },
            "output_fields": [
                {"field_name": "排名", "description": "行业排名", "required": True},
                {"field_name": "商品链接", "description": "分析对象", "required": True},
                {"field_name": "GMV/交易指数", "description": "判断体量", "required": True},
                {"field_name": "客单价", "description": "判断价格带", "required": True},
                {"field_name": "价格带", "description": "低/中/高价格分层", "required": True},
                {"field_name": "是否高增速", "description": "排名提升明显", "required": True},
            ],
            "known_params": {"category": "桌垫", "period": "近30天"},
        })

        self.assertEqual(0, proc.returncode, proc.stderr)
        response = json.loads(proc.stdout)
        self.assertEqual(
            ["data_ads_ind_trade_category_goods_m", "data_ads_ind_sycm_speed_category_goods_m"],
            response["selected_api_ids"][:2],
        )
        self.assertNotIn("top300_product_analysis", response["selected_api_ids"])
        applicability = response["api_applicability"]["data_ads_ind_sycm_speed_category_goods_m"]
        self.assertEqual("category_id_required", applicability["category_scope"])
        self.assertTrue(applicability["category_resolution_ready"])
        coverage = {item["field_name"]: item for item in response["field_coverage_plan"]}
        self.assertEqual("data_ads_ind_trade_category_goods_m", coverage["排名"]["source_api_id"])
        self.assertEqual("data.result[].rank", coverage["排名"]["source_field_path"])
        self.assertEqual("data_ads_ind_trade_category_goods_m", coverage["商品链接"]["source_api_id"])
        self.assertEqual("data.result[].sales_revenue", coverage["GMV/交易指数"]["source_field_path"])
        self.assertEqual("data.result[].unit_price", coverage["客单价"]["source_field_path"])
        self.assertEqual("derived_or_manual_required", coverage["价格带"]["mapping_status"])
        self.assertEqual("", coverage["价格带"]["source_field_path"])
        self.assertEqual("data_ads_ind_sycm_speed_category_goods_m", coverage["是否高增速"]["source_api_id"])
        self.assertEqual("data.result[].speed_type", coverage["是否高增速"]["source_field_path"])

    def test_match_business_context_adds_dependent_product_detail_enrichment(self) -> None:
        self._append_monthly_hot_goods_apis()
        self._append_product_detail_api()
        proc = _run_service({
            "op": "match_business_context",
            "index_path": self.index_path,
            "top_k": 8,
            "business_context": {
                "node_id": "collect_top_products",
                "title": "行业大盘与热销商品分析",
                "purpose": "输出指定类目的热销商品排行并补充商品属性",
                "data_sources": ["行业商品数据", "商品详情"],
                "actions": ["导出类目商品榜单", "逐个补充商品属性字段"],
            },
            "output_fields": [
                {"field_name": "排名", "description": "行业排名", "required": True},
                {"field_name": "材质", "description": "核心材质", "required": True},
                {"field_name": "场景", "description": "使用场景", "required": True},
                {"field_name": "功能", "description": "商品功能", "required": True},
                {"field_name": "风格", "description": "商品风格", "required": True},
                {"field_name": "主图元素", "description": "背景构图文案", "required": True},
            ],
            "known_params": {"category": "桌垫", "cid": "121458013", "period": "近30天"},
        })

        self.assertEqual(0, proc.returncode, proc.stderr)
        response = json.loads(proc.stdout)
        self.assertEqual(
            ["data_ads_ind_trade_category_goods_m", "data_ads_ind_sycm_speed_category_goods_m", "data_goods_ads_ind_goods_detail_info_m"],
            response["selected_api_ids"][:3],
        )
        applicability = response["api_applicability"]["data_goods_ads_ind_goods_detail_info_m"]
        self.assertEqual("product_detail_enrichment", applicability["execution_role"])
        self.assertEqual("topn_trade_total_primary", applicability["depends_on_role"])
        self.assertEqual({"goods_id": "primary_rows[].goods_id"}, applicability["input_binding"])
        coverage = {item["field_name"]: item for item in response["field_coverage_plan"]}
        self.assertEqual("data.result[].core_material", coverage["材质"]["source_field_path"])
        self.assertEqual("data.result[].usage_scene", coverage["场景"]["source_field_path"])
        for name in ("功能", "风格", "主图元素"):
            self.assertEqual("derived_or_manual_required", coverage[name]["mapping_status"])
            self.assertTrue(coverage[name]["evidence_field_paths"])
        derived = {item["field_name"]: item for item in response["derived_field_plan"]}
        self.assertIn("data.result[].selling_point_summary", derived["功能"]["evidence_field_paths"])
        self.assertIn("data.result[].usage_scene", derived["风格"]["evidence_field_paths"])

    def test_match_business_context_adds_dependent_product_feedback_enrichment(self) -> None:
        self._append_product_feedback_apis()
        proc = _run_service({
            "op": "match_business_context",
            "index_path": self.index_path,
            "top_k": 8,
            "business_context": {
                "node_id": "collect_reviews_qa",
                "title": "评价与问大家痛点分析",
                "purpose": "分析同类型排名前10竞品的评价与问大家",
                "data_sources": ["竞品评价", "问大家"],
                "actions": ["下载评论", "下载问大家", "归类痛点"],
            },
            "output_fields": [
                {"field_name": "competitor_product_url", "description": "竞品链接", "required": True},
                {"field_name": "review_text", "description": "评价原文", "required": True},
                {"field_name": "sentiment", "description": "正负向", "required": True},
                {"field_name": "qa_question", "description": "问题原文", "required": True},
                {"field_name": "painpoint_type", "description": "痛点分类", "required": True},
            ],
            "known_params": {"category": "桌布"},
        })

        self.assertEqual(0, proc.returncode, proc.stderr)
        response = json.loads(proc.stdout)
        self.assertEqual(
            ["get_positive_comment_data", "product_comment_content2", "product_question_content2"],
            [api_id for api_id in response["selected_api_ids"] if api_id in {
                "get_positive_comment_data", "product_comment_content2", "product_question_content2"
            }],
        )
        for api_id in ("get_positive_comment_data", "product_comment_content2", "product_question_content2"):
            applicability = response["api_applicability"][api_id]
            self.assertEqual("product_feedback_enrichment", applicability["execution_role"])
            self.assertEqual("confirmed_top_products", applicability["depends_on_role"])
            self.assertEqual("confirmed_rows[].goods_id", applicability["input_binding"]["goods_id"])

        coverage = {item["field_name"]: item for item in response["field_coverage_plan"]}
        self.assertEqual("data.result[].comment", coverage["review_text"]["source_field_path"])
        self.assertEqual("data.result[].question_content", coverage["qa_question"]["source_field_path"])
        for field_name in ("competitor_product_url", "sentiment", "painpoint_type"):
            self.assertEqual("derived_or_manual_required", coverage[field_name]["mapping_status"])

    def test_bind_request_params_defers_product_feedback_goods_ids(self) -> None:
        self._append_product_feedback_apis()
        proc = _run_service({
            "op": "bind_request_params",
            "index_path": self.index_path,
            "api_id": "product_question_content2",
            "known_params": {"category": "桌布"},
        })

        self.assertEqual(0, proc.returncode, proc.stderr)
        response = json.loads(proc.stdout)
        self.assertEqual([], response["missing_required_params"])
        mapping = {item["api_param"]: item for item in response["request_param_mapping"]}
        self.assertEqual("deferred", mapping["goods_id"]["status"])
        self.assertEqual("deferred", mapping["goods_id_list"]["status"])
        self.assertEqual(1, response["params"]["pageNum"])
        self.assertEqual(300, response["params"]["pageSize"])

    def test_match_business_context_prefers_competitor_landscape_and_protects_semantic_fields(self) -> None:
        self._append_competitor_landscape_apis()
        proc = _run_service({
            "op": "match_business_context",
            "index_path": self.index_path,
            "top_k": 8,
            "business_context": {
                "node_id": "analyze_competitors",
                "title": "竞品与竞店格局分析",
                "purpose": "筛选直接竞品、学习竞品、防御竞品并分析竞争强度",
                "data_sources": ["竞品基础信息、价格、SKU、卖点、视觉、评价和流量结构"],
                "actions": ["从行业商品排行榜筛选同类型产品", "确定竞品类型和竞争强度"],
            },
            "output_fields": [
                {"field_name": "competitor_type", "description": "竞品类型", "required": True},
                {"field_name": "shop_name", "description": "店铺名称", "required": True},
                {"field_name": "product_url", "description": "商品链接", "required": True},
                {"field_name": "price", "description": "商品价格", "required": True},
                {"field_name": "sku_count", "description": "SKU数量", "required": True},
                {"field_name": "main_selling_point", "description": "主卖点", "required": True},
                {"field_name": "visual_structure", "description": "视觉结构", "required": True},
                {"field_name": "review_painpoints", "description": "评价痛点", "required": True},
                {"field_name": "traffic_structure", "description": "流量结构", "required": True},
                {"field_name": "competitor_strength", "description": "竞争强度", "required": True},
            ],
            "known_params": {"category": "桌布", "cid": "121458013", "period": "近30天"},
        })

        self.assertEqual(0, proc.returncode, proc.stderr)
        response = json.loads(proc.stdout)
        self.assertEqual(["data_shop_competition_pattern_analysis_v3"], response["selected_api_ids"])
        applicability = response["api_applicability"]["data_shop_competition_pattern_analysis_v3"]
        self.assertEqual("competitor_landscape_primary", applicability["execution_role"])
        coverage = {item["field_name"]: item for item in response["field_coverage_plan"]}
        self.assertEqual("data.result[].shop_name", coverage["shop_name"]["source_field_path"])
        self.assertEqual("data.result[].goods_href", coverage["product_url"]["source_field_path"])
        self.assertEqual("data.result[].price", coverage["price"]["source_field_path"])
        self.assertEqual("data.result[].main_selling_point", coverage["main_selling_point"]["source_field_path"])
        for field_name in ("competitor_type", "visual_structure", "review_painpoints", "competitor_strength"):
            self.assertEqual("derived_or_manual_required", coverage[field_name]["mapping_status"])
            self.assertNotEqual("data.result[].max_price", coverage[field_name]["source_field_path"])
        for field_name in ("sku_count", "traffic_structure"):
            self.assertEqual("missing", coverage[field_name]["mapping_status"])
            self.assertEqual("", coverage[field_name]["source_field_path"])

    def test_bind_request_params_defers_product_detail_data_source_to_runtime(self) -> None:
        self._append_product_detail_api()
        proc = _run_service({
            "op": "bind_request_params",
            "index_path": self.index_path,
            "api_id": "data_goods_ads_ind_goods_detail_info_m",
            "known_params": {"category": "桌布", "cid": "121458013", "period": "近30天"},
            "execution_date": "2026-07-15",
            "timezone": "Asia/Shanghai",
        })

        self.assertEqual(0, proc.returncode, proc.stderr)
        response = json.loads(proc.stdout)
        self.assertNotIn("data_source", response["params"])
        mapping = {item["api_param"]: item for item in response["request_param_mapping"]}
        self.assertEqual("runtime_resolved", mapping["data_source"]["status"])
        self.assertEqual("detail_source_calibration", mapping["data_source"]["binding_method"])
        self.assertEqual(["sycm", "qbt"], mapping["data_source"]["candidate_values"])
        self.assertNotIn("data_source", response["missing_required_params"])

    def test_bind_request_params_uses_latest_complete_month_for_monthly_hot_goods_api(self) -> None:
        self._append_monthly_hot_goods_apis()

        proc = _run_service({
            "op": "bind_request_params",
            "index_path": self.index_path,
            "api_id": "data_ads_ind_trade_category_goods_m",
            "known_params": {"category": "桌布", "cid": "121458013", "period": "近30天"},
            "execution_date": "2026-07-15",
            "timezone": "Asia/Shanghai",
        })

        self.assertEqual(0, proc.returncode, proc.stderr)
        response = json.loads(proc.stdout)
        self.assertEqual("2026-06-01", response["params"]["start_date"])
        self.assertEqual("2026-06-01", response["params"]["end_date"])
        self.assertEqual("month", response["normalized_period"]["grain"])
        self.assertEqual("latest_complete_month", response["normalized_period"]["source"])
        self.assertEqual(6, response["normalized_period"]["max_fallback_months"])

    def test_bind_request_params_normalizes_deal_date_from_period(self) -> None:
        proc = _run_service({
            "op": "bind_request_params",
            "index_path": self.index_path,
            "api_id": "top300_product_analysis",
            "known_params": {"period": "近30天"},
            "execution_date": "2026-07-09",
            "timezone": "Asia/Shanghai",
        })

        self.assertEqual(0, proc.returncode, proc.stderr)
        response = json.loads(proc.stdout)
        self.assertEqual("request-param-binding-v1", response["schema_version"])
        self.assertEqual("2026-07-09", response["params"]["deal_date"])
        self.assertEqual(1, response["params"]["pageNum"])
        self.assertEqual(300, response["params"]["pageSize"])
        self.assertEqual([], response["missing_required_params"])
        mapping = {item["api_param"]: item for item in response["request_param_mapping"]}
        self.assertEqual("api_doc_matcher_date_normalization", mapping["deal_date"]["binding_method"])
        self.assertEqual("single_date", mapping["deal_date"]["date_conversion_rule"])
        self.assertEqual("2026-06-10", mapping["deal_date"]["normalized_period"]["start_date"])

    def test_discover_category_resolver_finds_name_id_response_fields(self) -> None:
        index_path = Path(self.index_path)
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        payload["apis"].extend(
            [
                {
                    "api_id": "category_resolver_fixture",
                    "source_seq": 1001,
                    "name": "类目名称 ID 解析",
                    "module": "fixture",
                    "business_module": "类目解析",
                    "analysis_domain": "类目域",
                    "method": "POST",
                    "path": "/category_resolver_fixture",
                    "verified_status": "success",
                    "request_params": [
                        {"name": "pageNum", "type": "integer", "required": True, "description": "页码"},
                        {"name": "pageSize", "type": "integer", "required": True, "description": "每页条数"},
                    ],
                    "request_headers": [],
                    "response_fields": [
                        {"path": "data.result[].cate_name", "name": "cate_name", "type": "string", "description": "类目名称"},
                        {"path": "data.result[].cate_id", "name": "cate_id", "type": "string", "description": "类目ID"},
                    ],
                    "source_refs": {},
                    "parse_warnings": [],
                },
                {
                    "api_id": "category_resolver_requires_cid",
                    "source_seq": 1002,
                    "name": "需要 CID 的类目详情",
                    "module": "fixture",
                    "business_module": "类目解析",
                    "analysis_domain": "类目域",
                    "method": "POST",
                    "path": "/category_resolver_requires_cid",
                    "verified_status": "success",
                    "request_params": [
                        {"name": "cid", "type": "string", "required": True, "description": "类目ID"},
                    ],
                    "request_headers": [],
                    "response_fields": [
                        {"path": "data.result[].cate_name", "name": "cate_name", "type": "string", "description": "类目名称"},
                        {"path": "data.result[].cate_id", "name": "cate_id", "type": "string", "description": "类目ID"},
                    ],
                    "source_refs": {},
                    "parse_warnings": [],
                },
            ]
        )
        index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        proc = _run_service({
            "op": "discover_category_resolver",
            "index_path": self.index_path,
            "direction": "name_to_id",
            "category_name": "桌垫",
            "known_params": {"category": "桌垫", "period": "近30天"},
            "top_k": 5,
        })

        self.assertEqual(0, proc.returncode, proc.stderr)
        response = json.loads(proc.stdout)
        self.assertEqual("category-resolver-discovery-v1", response["schema_version"])
        self.assertEqual("api_doc_matcher", response["provider"])
        candidates = response["candidates"]
        self.assertGreaterEqual(len(candidates), 1)
        by_id = {item["api_id"]: item for item in candidates}
        self.assertIn("category_resolver_fixture", by_id)
        self.assertNotIn("category_resolver_requires_cid", by_id)
        fixture = by_id["category_resolver_fixture"]
        self.assertEqual("data.result[].cate_name", fixture["name_field_path"])
        self.assertEqual("data.result[].cate_id", fixture["id_field_path"])
        self.assertEqual("ready", fixture["request_binding"]["status"])

    def test_discover_category_resolver_excludes_semantically_unrelated_apis(self) -> None:
        index_path = Path(self.index_path)
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        common_fields = [
            {"path": "data.result[].cate_name", "name": "cate_name", "type": "string", "description": "类目名称"},
            {"path": "data.result[].cate_id", "name": "cate_id", "type": "string", "description": "类目ID"},
        ]
        payload["apis"].extend(
            [
                {
                    "api_id": "category_dictionary",
                    "source_seq": 1101,
                    "name": "类目字典列表",
                    "module": "类目",
                    "business_module": "类目经营分析",
                    "analysis_domain": "类目结构",
                    "method": "GET",
                    "path": "/category_dictionary",
                    "verified_status": "success",
                    "request_params": [
                        {"name": "pageNum", "type": "integer", "required": True, "description": "页码"},
                        {"name": "pageSize", "type": "integer", "required": True, "description": "每页条数"},
                    ],
                    "request_headers": [],
                    "response_fields": common_fields,
                    "source_refs": {},
                    "parse_warnings": [],
                },
                {
                    "api_id": "data_source_relation",
                    "source_seq": 1102,
                    "name": "类目-数据来源关系",
                    "module": "数据治理",
                    "business_module": "数据治理配置",
                    "analysis_domain": "数据来源/指标关系",
                    "method": "POST",
                    "path": "/data_source_relation",
                    "verified_status": "success",
                    "request_params": [
                        {"name": "page_module", "type": "string", "required": True, "description": "页面模块"},
                        {"name": "date_type", "type": "string", "required": True, "description": "日期类型"},
                    ],
                    "request_headers": [],
                    "response_fields": common_fields,
                    "source_refs": {},
                    "parse_warnings": [],
                },
                {
                    "api_id": "social_persona",
                    "source_seq": 1103,
                    "name": "社媒人群汇总分析",
                    "module": "社媒",
                    "business_module": "社媒洞察",
                    "analysis_domain": "社媒人群画像",
                    "method": "POST",
                    "path": "/social_persona",
                    "verified_status": "success",
                    "request_params": [
                        {"name": "category_name", "type": "string", "required": True, "description": "类目名称"},
                    ],
                    "request_headers": [],
                    "response_fields": common_fields,
                    "source_refs": {},
                    "parse_warnings": [],
                },
            ]
        )
        index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        proc = _run_service({
            "op": "discover_category_resolver",
            "index_path": self.index_path,
            "category_name": "桌垫",
            "known_params": {"category": "桌垫", "period": "近30天"},
        })

        self.assertEqual(0, proc.returncode, proc.stderr)
        response = json.loads(proc.stdout)
        by_id = {item["api_id"]: item for item in response["candidates"]}
        self.assertIn("category_dictionary", by_id)
        self.assertEqual("unfiltered_category_dictionary", by_id["category_dictionary"]["resolver_mode"])
        self.assertNotIn("data_source_relation", by_id)
        self.assertNotIn("social_persona", by_id)
        rejected = {item["api_id"]: item["reason"] for item in response["rejected_candidates"]}
        self.assertEqual("unrelated_business_domain", rejected["data_source_relation"])
        self.assertEqual("unrelated_business_domain", rejected["social_persona"])

    def test_resolve_category_candidates_uses_product_title_api_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            build_index(
                detail_markdown=CATEGORY_DETAIL_DOC,
                validation_markdown=CATEGORY_VALIDATION_DOC,
                out_dir=Path(tmp),
                detail_source_path="detail.md",
                validation_source_path="validation.md",
            )
            index_path = str(Path(tmp) / "api_doc_index.json")

            proc = _run_service({
                "op": "resolve_category_candidates",
                "index_path": index_path,
                "category_name": "桌垫",
            })

        self.assertEqual(0, proc.returncode, proc.stderr)
        response = json.loads(proc.stdout)
        self.assertEqual("business-category-resolution-v2", response["schema_version"])
        self.assertEqual("resolved", response["status"])
        self.assertEqual("桌垫", response["requested_name"])
        self.assertEqual("桌布", response["canonical_name"])
        self.assertEqual("121458013", response["category_id"])
        self.assertEqual("product_title_evidence", response["match_kind"])
        self.assertGreaterEqual(response["confidence"], 0.9)
        self.assertTrue(response["evidence_sources"])

    def test_bind_request_params_requires_category_id_for_cid_params(self) -> None:
        proc = _run_service({
            "op": "bind_request_params",
            "index_path": self.index_path,
            "api_id": "data_ads_rpt_category_top300_analysis",
            "known_params": {"category": "入户地垫", "period": "近30天"},
            "execution_date": "2026-07-09",
        })

        self.assertEqual(0, proc.returncode, proc.stderr)
        response = json.loads(proc.stdout)
        self.assertNotIn("cid", response["params"])
        self.assertEqual("2026-07", response["params"]["statist_date"])
        self.assertIn("cid", response["missing_required_params"])
        self.assertEqual("category_id_required", response["category_resolution"]["blocked_reason"])
        mapping = {item["api_param"]: item for item in response["request_param_mapping"]}
        self.assertEqual("month", mapping["statist_date"]["date_conversion_rule"])
        self.assertEqual("category", mapping["cid"]["business_param"])
        self.assertEqual("category_id", mapping["cid"]["category_param_role"])
        self.assertEqual("missing", mapping["cid"]["status"])
        self.assertIn("缺少类目ID", mapping["cid"]["missing_reason"])

    def test_bind_request_params_binds_existing_category_id_for_cid_params(self) -> None:
        proc = _run_service({
            "op": "bind_request_params",
            "index_path": self.index_path,
            "api_id": "data_ads_rpt_category_top300_analysis",
            "known_params": {"category": "入户地垫", "cid": "50020776", "period": "近30天"},
            "execution_date": "2026-07-09",
        })

        self.assertEqual(0, proc.returncode, proc.stderr)
        response = json.loads(proc.stdout)
        self.assertEqual("50020776", response["params"]["cid"])
        self.assertEqual([], response["missing_required_params"])
        self.assertEqual("resolved", response["category_resolution"]["status"])
        mapping = {item["api_param"]: item for item in response["request_param_mapping"]}
        self.assertEqual("category_id", mapping["cid"]["category_param_role"])
        self.assertEqual("direct_api_param", mapping["cid"]["binding_method"])

    def test_bind_request_params_binds_category_name_params_directly(self) -> None:
        index_path = Path(self.index_path)
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        payload["apis"].append(
            {
                "api_id": "category_name_fixture_api",
                "source_seq": 1000,
                "name": "类目名称测试 API",
                "module": "fixture",
                "business_module": "测试",
                "analysis_domain": "测试域",
                "method": "POST",
                "path": "/category_name_fixture_api",
                "verified_status": "success",
                "request_params": [
                    {"name": "category_name", "type": "string", "required": True, "description": "类目名称"},
                    {"name": "pageNum", "type": "integer", "required": True, "description": "页码"},
                ],
                "request_headers": [],
                "response_fields": [{"path": "data.rows[].id", "name": "id", "type": "string", "description": "ID"}],
                "source_refs": {},
                "parse_warnings": [],
            }
        )
        index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        proc = _run_service({
            "op": "bind_request_params",
            "index_path": self.index_path,
            "api_id": "category_name_fixture_api",
            "known_params": {"category": "入户地垫"},
            "execution_date": "2026-07-09",
        })

        self.assertEqual(0, proc.returncode, proc.stderr)
        response = json.loads(proc.stdout)
        self.assertEqual("入户地垫", response["params"]["category_name"])
        mapping = {item["api_param"]: item for item in response["request_param_mapping"]}
        self.assertEqual("category_name", mapping["category_name"]["category_param_role"])
        self.assertEqual("category_name_direct", mapping["category_name"]["binding_method"])

    def test_bind_request_params_normalizes_range_params_and_skips_update_time(self) -> None:
        index_path = Path(self.index_path)
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        payload["apis"].append(
            {
                "api_id": "range_fixture_api",
                "source_seq": 999,
                "name": "日期区间测试 API",
                "module": "fixture",
                "business_module": "测试",
                "analysis_domain": "测试域",
                "method": "POST",
                "path": "/range_fixture_api",
                "verified_status": "success",
                "request_params": [
                    {"name": "start_date", "type": "string", "required": True, "description": "开始日期"},
                    {"name": "end_date", "type": "string", "required": True, "description": "结束日期"},
                    {"name": "date_range", "type": "string", "required": True, "description": "日期范围"},
                    {"name": "update_time", "type": "string", "required": False, "description": "更新时间"},
                ],
                "request_headers": [],
                "response_fields": [{"path": "data.rows[].id", "name": "id", "type": "string", "description": "ID"}],
                "source_refs": {},
                "parse_warnings": [],
            }
        )
        index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        proc = _run_service({
            "op": "bind_request_params",
            "index_path": self.index_path,
            "api_id": "range_fixture_api",
            "known_params": {"period": "近30天"},
            "execution_date": "2026-07-09",
        })

        self.assertEqual(0, proc.returncode, proc.stderr)
        response = json.loads(proc.stdout)
        self.assertEqual("2026-06-10", response["params"]["start_date"])
        self.assertEqual("2026-07-09", response["params"]["end_date"])
        self.assertEqual("2026-06-10,2026-07-09", response["params"]["date_range"])
        self.assertNotIn("update_time", response["params"])
        mapping = {item["api_param"]: item for item in response["request_param_mapping"]}
        self.assertEqual("optional", mapping["update_time"]["status"])
        self.assertNotEqual("period", mapping["update_time"]["business_param"])

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
