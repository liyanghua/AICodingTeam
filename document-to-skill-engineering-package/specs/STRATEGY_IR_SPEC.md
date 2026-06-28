# Strategy IR 规范

Strategy IR 是业务文档到 Skill 的中间表示。

## 顶层结构

```yaml
strategy_id: market_insight
name: 市场洞察元策略
version: 0.1.0
source_doc: 20260519市场分析洞察元策略.md
business_scenes: []
business_questions: []
outputs: []
workflow_steps: []
data_requirements: []
rules: []
templates: []
```

## workflow_step

```yaml
step_id: collect_keywords
title: 关键词需求分析
purpose: 通过关键词判断需求结构、人群需求、场景需求、功能需求、属性需求
step_type: data_collect_and_analysis
depends_on:
  - define_scope
data_requirement_ids:
  - category_keywords_top300
outputs:
  - keyword_demand_breakdown_table
  - keyword_root_top20_table
rules:
  - keyword_demand_classification_rule
```

## rule

```yaml
rule_id: trend_keyword_rule
description: 判断趋势关键词
inputs:
  - search_growth_rate
  - search_popularity
condition: search_growth_rate >= 0.20
output_label: 趋势关键词
```
