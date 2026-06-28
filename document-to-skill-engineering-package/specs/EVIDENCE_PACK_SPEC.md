# Evidence Pack 规范

每一个业务结论、评分、建议都必须有 Evidence Pack。

```yaml
evidence_id: ev_001
skill_run_id: run_001
step_id: analyze_hot_product_genes
claim: 某材质是当前类目的主流热销材质
evidence_type: computed_statistic
source_data:
  - source_system: internal_dw.category_top_products
    raw_response_id: api_resp_123
    fetched_at: 2026-06-18T10:00:00
    period: 30d
    fields:
      - material
      - pay_buyer_count
      - gmv
computation:
  metric: top50_material_ratio
  formula: count(material=X in top50) / 50
  value: 0.34
rule_hit:
  rule_id: mainstream_material
  threshold: top50_ratio >= 0.30
confidence: 0.88
```

## 证据类型

- `raw_api_response`
- `browser_export_file`
- `screenshot`
- `computed_statistic`
- `llm_classification`
- `human_review`

## 证据硬规则

- 没有 source，不得输出结论。
- 没有 formula，不得输出计算分数。
- 浏览器采集必须保存截图或导出文件引用。
- LLM 归类必须保存输入样本和分类 prompt 版本。
