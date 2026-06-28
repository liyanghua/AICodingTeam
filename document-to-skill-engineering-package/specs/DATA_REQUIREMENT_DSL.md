# Data Requirement DSL

Data Requirement 是策略文档到工具执行之间的关键中间层。

## 原则

业务文档中出现的“获取数据”表达，不直接转为浏览器动作，而是转为标准数据需求。

## 示例

业务表达：

```text
下载类目 TOP300 关键词。
```

Data Requirement：

```yaml
id: category_keywords_top300
description: 获取类目TOP300关键词及搜索人气、增长率、竞争度
required_fields:
  - keyword
  - search_popularity
  - growth_rate
  - competition_index
freshness: 30d
preferred_sources:
  - internal_dw.category_keyword_rank
  - bi_api.category_keywords
  - browser.sycm_keyword_export
fallback_sources:
  - manual_upload.keyword_excel
evidence_required:
  - source_name
  - query_params
  - fetched_at
  - raw_response_id
```

## 字段说明

- `id`：全局唯一。
- `description`：业务含义。
- `required_fields`：必须字段。
- `freshness`：数据新鲜度。
- `preferred_sources`：优先数据源。
- `fallback_sources`：兜底数据源。
- `evidence_required`：证据要求。
