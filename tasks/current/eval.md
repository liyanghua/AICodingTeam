# Eval Plan: 市场分析洞察报告生成器

> 评测目标：保证 PRD §8 验收成立。引用 `eval_rules.yaml` 的 hard_requirements 与 quality_metrics。

## 1. 测试金字塔

| 层级 | 范围 | 工具 |
| --- | --- | --- |
| 单元 | csv_io / rules / evidence pack | pytest |
| 契约 | output schema 校验 | pytest + jsonschema |
| 集成 | DAG runner 全链路 | pytest + 合成 fixture |
| 端到端 | SPA + FastAPI + 规则引擎 | pytest + httpx + 浏览器 headless（可选） |

## 2. Fixture

`tests/fixtures/market_insight/full/` 提供 6 个 CSV，对应 `data_requirements` 6 项；
`tests/fixtures/market_insight/missing_reviews/` 缺 `competitor_reviews_qa`；
`tests/fixtures/market_insight/missing_top_products/` 缺 `category_top_products_300`；
`tests/fixtures/market_insight/missing_cross_platform/` 缺 `cross_platform_trend_signals`。

合成数据要刻意触发规则阈值边界：

- 一组 TOP50 占比 = 0.30（恰好触发 `strong_hot_gene`）
- 一组 TOP50 占比 = 0.29（恰好不触发）
- 一组机会评分 = 85（恰好立项）
- 一组机会评分 = 84（测试）
- 一组机会评分 = 60（观察）
- 一组机会评分 = 59（不开发）

## 3. 单元测试

### 3.1 CSV schema 校验

| 用例 | 期望 |
| --- | --- |
| 全字段齐全 | pass |
| 缺一必填字段 | fail，返回字段名 |
| 列名走别名（aliases.py） | pass，归一化为标准字段 |
| 列名走未知别名 | warn but pass，记录 unknown_columns |
| 数值列非数字 | fail，行号 + 列名 |

### 3.2 规则引擎

`strong_hot_gene`：

| 用例 | 期望 |
| --- | --- |
| 4 项中 0 项满足 | 不触发 |
| 4 项中 1 项满足 | 不触发 |
| 4 项中 2 项满足 | 触发，`supporting_metrics` 含触发的 2 项 |
| 4 项中 4 项满足 | 触发，`supporting_metrics` 含 4 项 |
| 任一项数据缺失 | 该项视为不满足；若总满足 < 2 → 不触发 |

`trend_hot_gene` / `differentiated_opportunity_gene` 同结构覆盖。

`opportunity_score`：

| 输入 | 期望档位 |
| --- | --- |
| 85 | 立项 |
| 84 | 测试 |
| 70 | 测试 |
| 69 | 观察 |
| 60 | 观察 |
| 59 | 不开发 |

边界 100 / 0 也要覆盖。

### 3.3 Evidence Pack

| 用例 | 期望 |
| --- | --- |
| 每次 CSV 上传成功 | 生成一个 Evidence Pack 文件，含 source_name / query_params / fetched_at / raw_response_id |
| 结论生成时 evidence_ids 为空 | 整体 fail，触发 hard_requirements.evidence_required_for_each_conclusion |

## 4. 契约测试

每个 `output_schemas/*.json` 的输出文件用 `jsonschema` 校验。任一字段缺失或类型不符 → fail。

`output_schema_validity` 指标必须 = 1.00。

## 5. 集成测试

### 5.1 全链路通过

输入：`tests/fixtures/market_insight/full/`。
期望：

- 10 节点全部 `ok`。
- 10 张 schema 输出文件齐全。
- `opportunity_scores` 与 `listing_plan` 生成。
- `quality_metrics.workflow_node_success_rate` = 1.0。
- `final_report.md` 存在，含 10 章 + 评分 + 链接规划 + Evidence 索引。

### 5.2 降级（缺评价）

输入：`tests/fixtures/market_insight/missing_reviews/`。
期望：

- `analyze_competitors.status = degraded`。
- `differentiated_opportunity_gene` 不触发。
- 整体不进入 failed。
- 顶部横幅出现。

### 5.3 降级（缺跨平台）

输入：`tests/fixtures/market_insight/missing_cross_platform/`。
期望：

- `collect_cross_platform_trends.status = degraded`。
- `score_opportunities.degraded_dimensions` 含 `cross_platform`。
- 报告中机会评分注明该维度未参与。

### 5.4 阻断（缺 TOP300）

输入：`tests/fixtures/market_insight/missing_top_products/`。
期望：

- `collect_top_products.status = failed`。
- 下游 5 节点全部为 `failed`。
- UI 阻断对话框字段列表完整。

## 6. 端到端测试

- 启动 FastAPI（test client） + 浏览器 headless（可选 Playwright，仅用于本地测试，不在 v1 默认 CI）。
- 模拟：填表单 → 上传 6 CSV → 等待节点完成 → 触发导出。
- 断言：`final_report.md` 内容包含必备章节标题与 evidence 索引段。

## 7. 硬性约束自检

PRD §8.1 四条硬性约束逐条对照：

- `required_outputs_present`：检查 run artifact 中 10 张 schema + opportunity_scores + listing_plan 文件存在。
- `evidence_required_for_each_conclusion`：遍历所有 conclusions，断言 `evidence_ids` 非空。
- `score_formula_required`：检查 `opportunity_scores.formula` 字段含 6 项权重与公式。
- `no_data_no_strong_claim`：对降级 fixture 断言「强 / 趋势 / 差异」三类基因结论不触发。

## 8. 性能与稳定性

- 单 run 全链路（合成 fixture，约 300 行 × 6 表）执行时间 < 10s。
- 重复 10 次相同输入，结果 hash 一致（规则与 schema 决定性输出；LLM 归类部分由 fixture stub 替代以保证决定性）。

## 9. 报告

`runs/<run_id>/test_report.md` 输出：

- 单元 / 契约 / 集成 / 端到端 通过数 / 失败数
- 4 项 quality_metrics 实际值
- 4 项 hard_requirements 是否满足