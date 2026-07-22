from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from api_doc_matcher.indexer import build_index
from api_doc_matcher.matcher import match_api_requirement, match_business_fields
from api_doc_matcher.parse_detail_doc import parse_detail_doc
from api_doc_matcher.parse_validation_doc import parse_validation_doc
from api_doc_matcher.section_matcher import match_section
from api_doc_matcher.section_parser import parse_business_section


DETAIL_DOC = """# 智能体数仓完整接口文档_修复后逐接口完整格式版

## 2. 生意参谋昨日蓝海关键词分析

> 验证状态：**成功**
> 验证信息：code=200; msg=成功

```shell
curl -X POST "http://example.test/openApi/api/abc/5/top300_product_analysis?userId=secret-user&tenantId=572130&pageNum=1&pageSize=2&deal_date=2026-05-01" \\
-H "x-ca-appCodeKey: secret-key" -H "x-ca-appCode: secret-code" -H "Content-Type: application/json" \\
-d "{\\"pageNum\\":1,\\"pageSize\\":2,\\"deal_date\\":\\"2026-05-01\\"}"
```

### 参数字段说明

| 参数字段 | 数据类型 | 是否必填 | 说明 | 备注 |
| --- | --- | --- | --- | --- |
| pageNum | integer | 是 | 页码 | 第1页开始 |
| pageSize | integer | 是 | 每页条数 | 建议测试用 2 |
| deal_date | string | 是 | 交易日期 | yyyy-mm-dd |

### 返回格式

```json
{
  "code": "200",
  "msg": "成功",
  "data": {
    "result": [
      {
        "rank": 1,
        "commodity": "抱枕",
        "store_name": "乐兜家居旗舰店",
        "unit_price": "325.00",
        "trade_index": "12345",
        "pictures_linking": "https://img.example.test/item.jpg",
        "material": "冰丝",
        "scene": "家用",
        "selling_point": "防滑",
        "num_payers_interval": "50 ~ 100"
      }
    ]
  }
}
```

### 返回字段说明

| 字段名称 | 数据类型 | 说明 | 对象ID/类型 | 可打属性/状态标签 | 可打诊断标签 | 可打动作标签 | 适用场景 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| data.result[].rank | integer | 排名 | 商品指标 | — | — | — | 商品排行 | — |
| data.result[].commodity | string | 商品名称/商品标题 | 商品属性 | — | — | — | 商品排行 | — |
| data.result[].store_name | string | 店铺名称 | 店铺属性 | — | — | — | 商品排行 | — |
| data.result[].unit_price | string | 件单价/价格 | 商品指标 | — | — | — | 商品排行 | — |
| data.result[].trade_index | string | 交易指数/GMV体量 | 商品指标 | — | — | — | 商品排行 | — |
| data.result[].pictures_linking | string | 商品主图图片链接 | 商品视觉 | — | — | — | 商品排行 | — |
| data.result[].material | string | 材质 | 商品属性 | — | — | — | 商品排行 | — |
| data.result[].scene | string | 使用场景 | 商品属性 | — | — | — | 商品排行 | — |
| data.result[].selling_point | string | 主卖点 | 商品属性 | — | — | — | 商品排行 | — |
| data.result[].num_payers_interval | string | 支付买家数区间 | 商品指标 | — | — | — | 商品排行 | — |

> 验证状态：**成功**
> 验证信息：code=200; msg=成功

```shell
curl -X POST "http://example.test/openApi/api/abc/5/data/ads_rpt_category_top300_analysis?userId=secret-user&tenantId=572130" \\
-H "x-ca-appCodeKey: secret-key" -H "x-ca-appCode: secret-code" -H "Content-Type: application/json" \\
-d "{\\"cid\\":\\"50020776\\",\\"statist_date\\":\\"2026-05\\",\\"pageNum\\":\\"1\\",\\"pageSize\\":\\"10\\"}"
```

### 参数字段说明

| 参数字段 | 数据类型 | 是否必填 | 说明 | 备注 |
| --- | --- | --- | --- | --- |
| cid | string | 是 | 类目ID | — |
| statist_date | string | 是 | 统计月份 | yyyy-mm |

### 返回格式

```json
{
  "code": "200",
  "data": {
    "result": [
      {
        "top3_category_name": "抱枕",
        "total_products": "300",
        "yoy_sales_volume": "10.1"
      }
    ]
  }
}
```

### 返回字段说明

| 字段名称 | 数据类型 | 说明 | 对象ID/类型 | 可打属性/状态标签 | 可打诊断标签 | 可打动作标签 | 适用场景 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| data.result[].top3_category_name | string | top3类目字段名称 | 类目属性 | — | — | — | 类目分析 | — |
| data.result[].total_products | string | 总商品数 | 类目指标 | — | — | — | 类目分析 | — |
| data.result[].yoy_sales_volume | string | 销量同比 | 类目指标 | — | — | — | 类目分析 | — |
"""


PRODUCT_DETAIL_DOC = """# 商品详情信息查询接口文档

| 项目 | 内容 |
|---|---|
| 接口名称 | 商品详情信息查询接口 |

```bash
curl -X POST "http://example.test/openApi/api/abc/5/data/goods/ads_ind_goods_detail_info_m?tenantId=572130&goods_id=654397227320&userId=1983420822379380738&data_source=qbt" \\
  -H "x-ca-appCodeKey: <appCodeKey>" \\
  -H "x-ca-appCode: <appCode>" \\
  -H "Content-Type: application/json" \\
  --data "{}"
```

### 5.1 Query 参数

| 参数名 | 类型 | 是否必填 | 示例值 | 说明 |
|---|---|---:|---|---|
| `tenantId` | string | 是 | 572130 | 租户 ID |
| `goods_id` | string | 是 | 654397227320 | 商品 ID |
| `userId` | string | 是 | 1983420822379380738 | 用户 ID |
| `data_source` | string | 是 | qbt | 数据来源 |

### 7.4 测试结果

```json
{"code":"200","msg":"成功","data":{"result":[{"goods_name":"床头靠垫","goods_url":"https://item.test/654397227320","category_name":"床头靠垫","goods_code":null,"goods_id":"654397227320","price_band":"50-100","unit_price":"86.12","shop_name":"测试店铺","applicable_crowd":null,"usage_scene":"家用","selling_point_summary":"舒适支撑","shop_id":"194118212","goods_spec_params":null,"category_id":"201304232","brand_cn_name":"测试品牌","brand_en_name":null,"core_material":"化纤","goods_img":"https://item.test/654397227320"}]}}
```

### 8.2 `data.result[]` 字段说明

| 字段名 | 类型 | 示例值 | 说明 |
|---|---|---|---|
| goods_name | string | 床头靠垫 | 商品名称 |
| goods_url | string | https://item.test/654397227320 | 商品链接 |
| category_name | string | 床头靠垫 | 类目名称 |
| goods_code | string / null | null | 商品编码 |
| goods_id | string | 654397227320 | 商品 ID |
| price_band | string | 50-100 | 价格带 |
| unit_price | string | 86.12 | 商品单价 |
| shop_name | string | 测试店铺 | 店铺名称 |
| applicable_crowd | string / null | null | 适用人群 |
| usage_scene | string | 家用 | 使用场景 |
| selling_point_summary | string | 舒适支撑 | 卖点总结 |
| shop_id | string | 194118212 | 店铺 ID |
| goods_spec_params | string / null | null | 商品规格参数 |
| category_id | string | 201304232 | 类目 ID |
| brand_cn_name | string | 测试品牌 | 中文品牌名 |
| brand_en_name | string / null | null | 英文品牌名 |
| `core_material` | string | 化纤 | 核心材质 |
| `goods_img` | string | https://item.test/654397227320 | 商品图片地址 |
"""


CATEGORY_DETAIL_DOC = DETAIL_DOC + """

> 验证状态：**成功**
> 验证信息：code=200; msg=成功

```shell
curl -X POST "http://example.test/openApi/api/abc/5/data/dim_goods_info?userId=secret-user&tenantId=572130&goods_id=1011965092050&pageNum=1&pageSize=2" \\
-H "x-ca-appCodeKey: secret-key" -H "x-ca-appCode: secret-code" -H "Content-Type: application/json" \\
-d "{\"goods_id\":\"1011965092050\",\"pageNum\":1,\"pageSize\":2}"
```

### 参数字段说明

| 参数字段 | 数据类型 | 是否必填 | 说明 | 备注 |
| --- | --- | --- | --- | --- |
| goods_id | string | 是 | 商品ID | — |
| pageNum | integer | 是 | 页码 | — |
| pageSize | integer | 是 | 每页条数 | — |

### 返回格式

```json
{
  "code": "200",
  "data": {
    "result": [
      {
        "goods_name": "学生书桌垫儿童学习桌垫桌布桌面垫",
        "category_name": "桌布",
        "category_id": "121458013",
        "goods_id": "1011965092050"
      },
      {
        "goods_name": "防水防油餐桌垫免洗桌布",
        "category_name": "桌布",
        "category_id": "121458013",
        "goods_id": "1000418279010"
      }
    ]
  }
}
```

### 返回字段说明

| 字段名称 | 数据类型 | 说明 |
| --- | --- | --- |
| data.result[].goods_name | string | 商品名称 |
| data.result[].category_name | string | 类目名称 |
| data.result[].category_id | string | 类目ID |
| data.result[].goods_id | string | 商品ID |
"""


VALIDATION_DOC = """# 智能体数仓完整接口文档_全量验证版

**总计：2个接口**

## 🎯 所有接口列表（修复后验证结果）

| 序号 | 模块 | 业务模块 | 分析域 | 接口名称 | 方法 | 原URL/Path | 修复后状态 | 修复后可用URL | 修复后入参 | 说明/验证信息 |
|------:|------|------|------|----------|------|-----|------|------|------|---------------|
| 21 | 智能体API迁移版本 | 关键词分析 | 搜索词/词根/需求趋势 | 类目前300商品分析 | POST | `/top300_product_analysis` | ✅ 成功 | `http://example.test/openApi/api/abc/5/top300_product_analysis?userId=secret-user&tenantId=572130&pageNum=1&pageSize=2&deal_date=2026-05-01` | `{"pageNum":1,"pageSize":2,"deal_date":"2026-05-01"}` | code=200; msg=成功 |
| 91 | 经营增长体系2.0 | 类目经营分析 | 类目结构/行业商品 | 类目前300分析 | POST | `/data/ads_rpt_category_top300_analysis` | ✅ 成功 | `http://example.test/openApi/api/abc/5/data/ads_rpt_category_top300_analysis?userId=secret-user&tenantId=572130` | `{"cid":"50020776","statist_date":"2026-05","pageNum":"1","pageSize":"10"}` | code=200; msg=成功 |

## 🧾 逐接口标题完整列表及备注

| 序号 | 逐接口标题 | 逐接口文档行号 | 全量版接口名称 | 状态 | 备注 |
| 21 | 类目前300商品分析 | 100 | 类目前300商品分析 | 成功 | 不应重复计数 |
"""


CATEGORY_VALIDATION_DOC = VALIDATION_DOC.replace(
    "\n## 🧾 逐接口标题完整列表及备注",
    "\n| 99 | 经营增长体系2.0 | 类目经营分析 | 类目结构/行业商品 | 商品信息 | POST | `/data/dim_goods_info` | ✅ 成功 | `http://example.test/openApi/api/abc/5/data/dim_goods_info` | `{\"goods_id\":\"1011965092050\",\"pageNum\":1,\"pageSize\":2}` | code=200; msg=成功 |\n\n## 🧾 逐接口标题完整列表及备注",
)


SOURCE_DOC = """# 20260519市场分析洞察元策略

## 流程1：确定分析边界

### 1.1 目的

确定分析对象。

## 流程2：行业大盘与热销商品分析

### 2.1 目的

判断这个类目当前的主流产品、主流价格、主流卖点、主流视觉和趋势变化。

《市场洞察报告》分析市场的目的是了解“谁涨得快、谁稳定、谁赚钱”，并通过行业数据判断流行趋势和机会点。

### 2.2 数据来源

1. 生意参谋：市场 → 市场排行 → 三级类目 → 商品排行榜
2. 店透视：一键分析 → 加载全部 → 导出表格
3. 边界BI：市场洞察 → 类目排行榜
4. 行业前300商品数据

### 2.3 执行动作

第一步：导出行业前300商品榜单。
第二步：删除无效列，例如日期、类目名称、图片链接。
第三步：把商品主图嵌入单元格，方便横向对比。
第四步：逐个补充商品属性字段。
第五步：按产品类型、价格带、材质、功能、场景、风格、卖点做分类统计。
第六步：找出高销量、高增长、高客单、高利润、低竞争的商品。

### 2.4 表格字段

| 字段 | 说明 |
| --- | --- |
| 排名 | 行业排名 |
| 店铺名 | 对手是谁 |
| 商品链接 | 分析对象 |
| 商品主图 | 看视觉表达 |
| 销量/支付买家数 | 判断真实销售能力 |
| GMV/交易指数 | 判断体量 |
| 客单价 | 判断价格带 |
| 价格带 | 低/中/高（生意参谋6个价格带） |
| 产品类型 | 品类/款式/形态 |
| 材质 | 例如半边绒、冰丝、羊羔绒 |
| 功能 | 防水、防滑、抗菌、护眼、显白等 |
| 风格 | 奶油风、轻奢风、复古风、简约风 |
| 场景 | 家用、宿舍、母婴、户外、通勤 |
| 主卖点 | 第一卖点是什么 |
| 主图元素 | 背景、构图、文案、场景、人物 |
| 是否高增速 | 近7天/近30天排名提升明显 |
| 爆款原因 | 为什么卖得好 |

## 流程3：爆款基因提炼

### 3.1 目的

从热销商品中提炼可复制规律。
"""


class ApiDocMatcherTests(unittest.TestCase):
    def test_parse_validation_doc_only_reads_target_table(self) -> None:
        parsed = parse_validation_doc(VALIDATION_DOC, source_path="validation.md")

        self.assertEqual(2, len(parsed.entries))
        self.assertEqual("top300_product_analysis", parsed.entries[0].api_id)
        self.assertEqual("success", parsed.entries[0].verified_status)

    def test_parse_detail_doc_uses_curl_blocks_and_redacts_secret_headers(self) -> None:
        parsed = parse_detail_doc(DETAIL_DOC, source_path="detail.md")

        self.assertEqual(2, len(parsed.entries))
        first = parsed.entries[0]
        self.assertEqual("POST", first.method)
        self.assertEqual("/top300_product_analysis", first.path)
        self.assertIn("x-ca-appCodeKey", first.request_headers)
        self.assertNotIn("secret-key", json.dumps(first.to_dict(), ensure_ascii=False))
        self.assertTrue(any(field.name == "commodity" for field in first.response_fields))

    def test_parse_detail_doc_keeps_structured_response_examples(self) -> None:
        parsed = parse_detail_doc(CATEGORY_DETAIL_DOC, source_path="detail.md")

        category_api = next(entry for entry in parsed.entries if entry.api_id == "data_dim_goods_info")
        self.assertEqual(1, len(category_api.response_examples))
        rows = category_api.response_examples[0]["data"]["result"]
        self.assertEqual("桌布", rows[0]["category_name"])
        self.assertEqual("121458013", rows[0]["category_id"])

    def test_parse_detail_doc_supports_standalone_product_detail_template(self) -> None:
        parsed = parse_detail_doc(PRODUCT_DETAIL_DOC, source_path="商品详情信息查询接口文档.md")

        self.assertEqual(1, len(parsed.entries))
        entry = parsed.entries[0]
        self.assertEqual("data_goods_ads_ind_goods_detail_info_m", entry.api_id)
        self.assertEqual("商品详情信息查询接口", entry.api_name)
        self.assertEqual("POST", entry.method)
        self.assertEqual("/data/goods/ads_ind_goods_detail_info_m", entry.path)
        self.assertEqual(["tenantId", "goods_id", "userId", "data_source"], [item.name for item in entry.request_params])
        self.assertTrue(all(item.position == "query" for item in entry.request_params))
        self.assertEqual(18, len(entry.response_fields))
        self.assertIn("data.result[].core_material", [item.path for item in entry.response_fields])
        self.assertEqual(1, len(entry.response_examples))
        self.assertEqual("success", entry.verified_status)

    def test_parse_standalone_detail_reads_query_table_before_curl(self) -> None:
        query_start = PRODUCT_DETAIL_DOC.index("### 5.1 Query 参数")
        query_end = PRODUCT_DETAIL_DOC.index("### 7.4 测试结果")
        query_block = PRODUCT_DETAIL_DOC[query_start:query_end]
        without_query = PRODUCT_DETAIL_DOC[:query_start] + PRODUCT_DETAIL_DOC[query_end:]
        curl_start = without_query.index("```bash")
        reordered = without_query[:curl_start] + query_block + "\n" + without_query[curl_start:]

        parsed = parse_detail_doc(reordered, source_path="query-before-curl.md")

        self.assertEqual(["tenantId", "goods_id", "userId", "data_source"], [item.name for item in parsed.entries[0].request_params])
        self.assertTrue(all(item.position == "query" for item in parsed.entries[0].request_params))

    def test_build_index_joins_detail_and_validation_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = build_index(
                detail_markdown=DETAIL_DOC,
                validation_markdown=VALIDATION_DOC,
                out_dir=Path(tmp),
                detail_source_path="detail.md",
                validation_source_path="validation.md",
            )

            self.assertEqual(2, len(result.api_entries))
            self.assertGreaterEqual(result.join_hit_count, 2)
            index_file = Path(tmp) / "api_doc_index.json"
            field_file = Path(tmp) / "api_field_index.json"
            report_file = Path(tmp) / "api_doc_index_report.md"
            self.assertTrue(index_file.exists())
            self.assertTrue(field_file.exists())
            self.assertTrue(report_file.exists())
            self.assertNotIn("secret-key", index_file.read_text(encoding="utf-8"))

    def test_build_index_merges_repeatable_extra_detail_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = build_index(
                detail_markdown=DETAIL_DOC,
                validation_markdown=VALIDATION_DOC,
                out_dir=Path(tmp),
                detail_source_path="detail.md",
                validation_source_path="validation.md",
                extra_detail_documents=[("商品详情信息查询接口文档.md", PRODUCT_DETAIL_DOC)],
            )

            detail = next(item for item in result.api_entries if item.api_id == "data_goods_ads_ind_goods_detail_info_m")
            self.assertEqual("商品详情信息查询接口", detail.name)
            self.assertEqual("success", detail.verified_status)
            self.assertIn("data.result[].usage_scene", [item.path for item in detail.response_fields])
            payload = json.loads((Path(tmp) / "api_doc_index.json").read_text(encoding="utf-8"))
            self.assertEqual(3, payload["api_count"])
            self.assertIn("商品详情信息查询接口文档.md", json.dumps(payload, ensure_ascii=False))

    def test_build_index_emits_category_entities_from_api_examples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            build_index(
                detail_markdown=CATEGORY_DETAIL_DOC,
                validation_markdown=CATEGORY_VALIDATION_DOC,
                out_dir=Path(tmp),
                detail_source_path="detail.md",
                validation_source_path="validation.md",
            )

            payload = json.loads((Path(tmp) / "api_doc_index.json").read_text(encoding="utf-8"))
            self.assertEqual("api-doc-index-v2", payload["schema_version"])
            entity = next(item for item in payload["category_entities"] if item["category_id"] == "121458013")
            self.assertEqual("桌布", entity["canonical_name"])
            self.assertEqual(2, entity["evidence_count"])
            self.assertTrue(any("桌垫" in text for text in entity["evidence_texts"]))
            self.assertEqual("data_dim_goods_info", entity["evidence_sources"][0]["api_id"])

    def test_match_api_requirement_finds_top300_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = build_index(
                detail_markdown=DETAIL_DOC,
                validation_markdown=VALIDATION_DOC,
                out_dir=Path(tmp),
                detail_source_path="detail.md",
                validation_source_path="validation.md",
            )

            matches = match_api_requirement(
                result.api_entries,
                "行业大盘与热销商品分析，需要类目排行和商品排行",
                top_k=2,
            )

            self.assertEqual("top300_product_analysis", matches[0].api_id)
            self.assertGreater(matches[0].score, 0)

    def test_match_business_fields_returns_coverage_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = build_index(
                detail_markdown=DETAIL_DOC,
                validation_markdown=VALIDATION_DOC,
                out_dir=Path(tmp),
                detail_source_path="detail.md",
                validation_source_path="validation.md",
            )

            field_result = match_business_fields(
                result.api_entries,
                ["排名", "商品名", "店铺名", "价格", "支付买家数", "交易指数"],
                api_ids=["top300_product_analysis", "data_ads_rpt_category_top300_analysis"],
            )

            self.assertGreaterEqual(field_result.business_field_coverage_score, 0.60)
            self.assertNotIn("交易指数", field_result.missing_required_fields)
            mapped = {match.business_field: match for match in field_result.matches}
            self.assertEqual("matched", mapped["商品名"].status)
            self.assertEqual("data.result[].commodity", mapped["商品名"].api_field_path)

    def test_parse_business_section_extracts_flow2_context_and_fields(self) -> None:
        section = parse_business_section(SOURCE_DOC, "流程2：行业大盘与热销商品分析")

        self.assertEqual("流程2：行业大盘与热销商品分析", section.title)
        self.assertIn("主流产品", section.purpose)
        self.assertEqual(4, len(section.data_sources))
        self.assertEqual(6, len(section.actions))
        self.assertEqual(17, len(section.output_fields))
        self.assertEqual("商品主图", section.output_fields[3].name)
        self.assertEqual("看视觉表达", section.output_fields[3].description)

    def test_match_section_compares_three_strategies_and_marks_derived_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = build_index(
                detail_markdown=DETAIL_DOC,
                validation_markdown=VALIDATION_DOC,
                out_dir=Path(tmp),
                detail_source_path="detail.md",
                validation_source_path="validation.md",
            )

            section_result = match_section(
                result.api_entries,
                parse_business_section(SOURCE_DOC, "流程2：行业大盘与热销商品分析"),
                top_k=5,
            )

            self.assertIn("title_only", section_result.strategy_results)
            self.assertIn("enriched_context", section_result.strategy_results)
            self.assertIn("field_coverage_rerank", section_result.strategy_results)
            title_score = section_result.strategy_results["title_only"].business_field_coverage_score
            rerank_score = section_result.strategy_results["field_coverage_rerank"].business_field_coverage_score
            self.assertGreaterEqual(rerank_score, title_score)
            self.assertGreaterEqual(section_result.business_field_coverage_score, 0.75)

            mapped = {match.business_field: match for match in section_result.field_mapping.matches}
            self.assertEqual("data.result[].pictures_linking", mapped["商品主图"].api_field_path)
            self.assertIn(mapped["商品主图"].status, {"matched", "suggested_needs_review"})
            self.assertEqual("derived_or_manual_required", mapped["功能"].status)
            self.assertEqual("derived_or_manual_required", mapped["风格"].status)
            self.assertEqual("derived_or_manual_required", mapped["主图元素"].status)
            self.assertEqual("derived_or_manual_required", mapped["爆款原因"].status)

    def test_match_section_exports_field_mapping_for_each_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = build_index(
                detail_markdown=DETAIL_DOC,
                validation_markdown=VALIDATION_DOC,
                out_dir=Path(tmp),
                detail_source_path="detail.md",
                validation_source_path="validation.md",
            )

            section_result = match_section(
                result.api_entries,
                parse_business_section(SOURCE_DOC, "流程2：行业大盘与热销商品分析"),
                top_k=5,
            ).to_dict()

            mappings = section_result["strategy_field_mappings"]
            self.assertIn("title_only", mappings)
            self.assertIn("enriched_context", mappings)
            self.assertIn("field_coverage_rerank", mappings)
            title_candidates = mappings["title_only"]["matches"][0]["candidate_api_ids"]
            enriched_candidates = mappings["enriched_context"]["matches"][0]["candidate_api_ids"]
            self.assertEqual(
                section_result["strategy_results"]["title_only"]["selected_api_ids"],
                title_candidates,
            )
            self.assertEqual(
                section_result["strategy_results"]["enriched_context"]["selected_api_ids"],
                enriched_candidates,
            )
            self.assertEqual("title_only", mappings["title_only"]["matches"][0]["source_strategy"])
            self.assertEqual("enriched_context", mappings["enriched_context"]["matches"][0]["source_strategy"])


if __name__ == "__main__":
    unittest.main()
