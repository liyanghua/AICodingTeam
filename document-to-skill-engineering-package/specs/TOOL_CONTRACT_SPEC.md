# Tool Contract 规范

Tool 不是简单 API wrapper，而是 Agent-first business tool。

## Tool Contract

```yaml
tool_id: internal_api.get_category_top_products
name: 获取类目TOP商品榜单
type: internal_data_tool
domain: market_insight

input_schema:
  category_id:
    type: string
    required: true
  period:
    type: string
    enum: [7d, 30d, monthly]
  limit:
    type: integer
    default: 300

output_schema:
  rows:
    type: array
    items:
      rank: integer
      product_url: string
      shop_name: string
      pay_buyer_count: number
      gmv: number
      price: number
      growth_30d: number

business_semantics:
  supports_questions:
    - 这个类目现在什么东西卖得好？
    - 哪些商品涨得快？
  used_by_skills:
    - market_insight

quality_checks:
  - row_count >= 50
  - required_fields_not_null_ratio >= 0.95

evidence:
  required:
    - source_system
    - query_params
    - fetched_at
    - raw_response_id

governance:
  auth_scope: market_insight.read
  pii_risk: low
  cost_level: low

fallback_tools:
  - browser.sycm_market_rank_export
  - manual_upload.top_product_excel
```
