# Data Asset Card 规范

用于描述内部数仓 API、BI 数据集、文件型数据集的业务语义。

```yaml
api_asset_id: dw.category_keyword_rank
name: 类目关键词排行
owner: data_team
domain: market_insight
entity: keyword
grain: category_id + keyword + date
freshness: daily

dimensions:
  - category_id
  - keyword
  - demand_type
  - period

metrics:
  - search_popularity
  - search_growth_rate
  - competition_index
  - click_rate
  - conversion_rate

business_mapping:
  supports:
    - 关键词需求分析
    - 需求强度计算
    - 趋势词发现

quality:
  freshness_sla: 24h
  null_rate_threshold: 5%
  min_row_count: 100

tool_wrappers:
  - internal_api.get_category_keywords
```
