# API Doc Matcher

`api_doc_matcher/` 是一个独立的 deterministic CLI 能力包，用来验证：

```text
两份数仓 API 文档
  -> parse
  -> index
  -> 业务语言匹配 API
  -> 业务字段匹配 API 返回字段
  -> business_field_coverage_score
```

P0 不调用真实 API，不读取 `.env`，不做 live probe，不依赖 `app_generation`。

## 输入文档

默认验收使用：

- `/Users/yichen/Desktop/OntologyBrain/PI_AGENT/db-archaeologist-pi-spec-pack/docs/data_api/智能体数仓完整接口文档_修复后逐接口完整格式版.md`
- `/Users/yichen/Desktop/OntologyBrain/PI_AGENT/db-archaeologist-pi-spec-pack/docs/data_api/智能体数仓完整接口文档_全量验证版.md`

可以通过环境变量覆盖：

```bash
DETAIL_DOC=/path/to/detail.md \
VALIDATION_DOC=/path/to/validation.md \
bash api_doc_matcher/accept_cli.sh
```

## CLI

生成索引：

```bash
python3 -m api_doc_matcher.cli build-index \
  --detail-doc "$DETAIL_DOC" \
  --validation-doc "$VALIDATION_DOC" \
  --out api_doc_matcher/build
```

业务语言匹配 API：

```bash
python3 -m api_doc_matcher.cli match-api \
  --index api_doc_matcher/build/api_doc_index.json \
  --query "行业大盘与热销商品分析，需要类目排行和商品排行" \
  --top-k 5
```

业务字段匹配 API 返回字段：

```bash
python3 -m api_doc_matcher.cli match-fields \
  --index api_doc_matcher/build/api_doc_index.json \
  --fields "排名,商品名,店铺名,价格,支付买家数,交易指数" \
  --api-ids "top300_product_analysis,data_ads_rpt_category_top300_analysis"
```

一键 smoke：

```bash
bash api_doc_matcher/accept_cli.sh
```

从业务文档流程段落自动匹配 API 和字段：

```bash
python3 -m api_doc_matcher.cli match-section \
  --index api_doc_matcher/build/api_doc_index.json \
  --source-doc document-to-skill-engineering-package/examples/source_docs/20260519市场分析洞察元策略.md \
  --section-title "流程2：行业大盘与热销商品分析" \
  --strategy compare \
  --top-k 8
```

## 产物

默认生成到 `api_doc_matcher/build/`：

- `api_doc_index.json`
- `api_field_index.json`
- `api_doc_chunks.jsonl`
- `api_doc_index_report.md`
- `match_api_smoke.json`
- `match_fields_smoke.json`
- `match_section_smoke.json`

## 评价指标

`business_field_coverage_score` 衡量业务产物字段被 API 返回字段覆盖的程度：

```text
business_field_coverage_score =
  0.5 * required_field_coverage_rate
+ 0.3 * high_confidence_mapping_rate
+ 0.2 * confirmed_or_reviewable_rate
```

验收门槛：

```text
P0 smoke >= 0.60
可进入人工工作台 >= 0.75
可推荐为默认映射 >= 0.85
```

所有字段映射结果都只是建议，不自动 confirmed。

## Agent 封装入口

后续 Agent 不需要直接调用 CLI，可以使用：

- `api_doc_matcher.agent_adapter.match_business_api_requirement`
- `api_doc_matcher.agent_adapter.match_business_fields_to_api_fields`
- `api_doc_matcher.agent_adapter.match_business_section_to_api_fields`

这些函数消费 `api_doc_index.json`，返回稳定 JSON 结构。
