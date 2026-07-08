# TDD Cases: 市场分析洞察报告生成器

> 与 [`eval.md`](eval.md) 一一对应；本文件是测试代码骨架的索引，提供 ID、断言要点与覆盖目标，便于 Code Agent 派生 coverage matrix。

## 命名约定

`MIR-<area>-<n>`：area ∈ { CSV, RULE, EVID, SCHEMA, DAG, UI, E2E, HARD }。

## 1. CSV schema 校验

| ID | 输入 | 断言 |
| --- | --- | --- |
| MIR-CSV-1 | full fixture 6 个 CSV | 全部 schema 校验 pass |
| MIR-CSV-2 | TOP300 缺 `gmv_or_transaction_index` 列 | fail，错误信息含字段名 |
| MIR-CSV-3 | TOP300 用别名「成交买家数」 | pass，归一化为 `sales_or_pay_buyer_count` |
| MIR-CSV-4 | 关键词表数值列含空字符串 | fail，行号 + 列名 |
| MIR-CSV-5 | 跨平台 CSV 完全缺失 | run 仍可启动，`collect_cross_platform_trends` 进入 degraded |

## 2. 规则引擎

### 2.1 `strong_hot_gene`

| ID | TOP50 / TOP100 / 买家 / GMV | 期望 |
| --- | --- | --- |
| MIR-RULE-SH-1 | 0.10 / 0.05 / 0.10 / 0.10 | 不触发 |
| MIR-RULE-SH-2 | 0.30 / 0.05 / 0.10 / 0.10 | 不触发（仅 1 项） |
| MIR-RULE-SH-3 | 0.30 / 0.20 / 0.10 / 0.10 | 触发（恰 2 项） |
| MIR-RULE-SH-4 | 0.29 / 0.19 / 0.29 / 0.29 | 不触发（边界负向） |
| MIR-RULE-SH-5 | 0.40 / 0.30 / 0.40 / 0.40 | 触发，metrics 含 4 项 |

### 2.2 `trend_hot_gene`

| ID | high_growth_product / keyword_growth / buyer_growth_30d / cross_platform_hot | 期望 |
| --- | --- | --- |
| MIR-RULE-TR-1 | 0.30 / 0.20 / 0.50 / true | 触发 |
| MIR-RULE-TR-2 | 0.30 / 0.19 / 0.49 / false | 不触发 |
| MIR-RULE-TR-3 | 0.30 / 0.20 / null / null | 视缺失为不满足；触发条件检查 < 2 → 不触发 |

### 2.3 `differentiated_opportunity_gene`

| ID | review_painpoint / qa_concern / top50_supply_count / price_band_supply_ratio / buyer_ratio | 期望 |
| --- | --- | --- |
| MIR-RULE-DF-1 | 0.10 / 0.10 / 4 / 0.10 / 0.30 | 触发（恰 2 项） |
| MIR-RULE-DF-2 | 0.09 / 0.09 / 5 / 0.16 / 0.24 | 不触发（4 项均不达） |
| MIR-RULE-DF-3 | 缺评价数据 | 痛点 + QA 两项视为不满足；其他独立判定 |

### 2.4 `opportunity_score`

| ID | 总分 | 期望档位 |
| --- | --- | --- |
| MIR-RULE-OS-1 | 100 | 立项 |
| MIR-RULE-OS-2 | 85 | 立项 |
| MIR-RULE-OS-3 | 84 | 测试 |
| MIR-RULE-OS-4 | 70 | 测试 |
| MIR-RULE-OS-5 | 69 | 观察 |
| MIR-RULE-OS-6 | 60 | 观察 |
| MIR-RULE-OS-7 | 59 | 不开发 |
| MIR-RULE-OS-8 | 0 | 不开发 |
| MIR-RULE-OS-9 | 缺跨平台维度（该项 0 分） | 总分扣 15 上限；档位按实际总分判定；`degraded_dimensions` 含 `cross_platform` |

## 3. Evidence Pack

| ID | 场景 | 断言 |
| --- | --- | --- |
| MIR-EVID-1 | CSV 上传成功 | 生成 `evidence/<id>.json`，含 4 个必备字段 |
| MIR-EVID-2 | 结论的 evidence_ids 为空 | 节点 status = failed，整体 hard_requirements 标记不满足 |
| MIR-EVID-3 | 结论的 evidence_ids 指向不存在的 evidence | 节点 status = failed |
| MIR-EVID-4 | 同一 CSV 二次上传 | 旧 Evidence Pack 失效，新 Pack 替换；run artifact 可追溯历史 |

## 4. Output Schema 契约

| ID | 输入 | 断言 |
| --- | --- | --- |
| MIR-SCHEMA-1 | full fixture 跑完 | 10 个 `outputs/<schema_id>.json` 全部通过 `output_schemas/*.json` 校验 |
| MIR-SCHEMA-2 | LLM 归类输出含未知字段 | 校验 fail；整节点 failed |
| MIR-SCHEMA-3 | 表格 row 缺必填字段 | 校验 fail |

## 5. DAG 行为

| ID | 场景 | 断言 |
| --- | --- | --- |
| MIR-DAG-1 | full fixture | 节点按拓扑顺序变 ok；最终 10/10 |
| MIR-DAG-2 | missing_top_products | `collect_top_products = failed`；下游 5 节点全部 failed；`generate_listing_plan` 不执行 |
| MIR-DAG-3 | missing_reviews | `analyze_competitors / collect_reviews_qa = degraded`；`differentiated_opportunity_gene` 不触发；整体不进 failed |
| MIR-DAG-4 | missing_cross_platform | `collect_cross_platform_trends = degraded`；`score_opportunities.degraded_dimensions = [cross_platform]`；整体 ok |

## 6. UI 行为

| ID | 场景 | 断言 |
| --- | --- | --- |
| MIR-UI-1 | 进度条点击节点 | 中间工作区切换到对应节点视图 |
| MIR-UI-2 | 节点 failed | 阻断对话框显示缺失字段列表 |
| MIR-UI-3 | 任一节点 degraded | 顶部黄色横幅出现 |
| MIR-UI-4 | `score_opportunities` 未 ok | 导出按钮灰显 |
| MIR-UI-5 | Evidence 抽屉 | 任意结论点击 evidence 链接可弹出抽屉，关闭后工作区状态不变 |
| MIR-UI-6 | 用例预设切换 | 表单默认值与节点排序变化，DAG 拓扑不变 |

## 7. 端到端

| ID | 场景 | 断言 |
| --- | --- | --- |
| MIR-E2E-1 | full fixture 全流程 | 生成 `final_report.md`，含 10 章 + 评分 + 链接规划 + Evidence 索引 |
| MIR-E2E-2 | missing_reviews 全流程 | 报告中评价相关章节标注「数据不全」；其他章节正常 |
| MIR-E2E-3 | 重复 10 次相同输入 | 报告 hash 一致（LLM 部分由 stub 注入） |

## 8. 硬性约束

| ID | hard_requirement | 断言 |
| --- | --- | --- |
| MIR-HARD-1 | required_outputs_present | full fixture 跑完后，10 张 schema + opportunity_scores + listing_plan 文件齐全 |
| MIR-HARD-2 | evidence_required_for_each_conclusion | 任意结论 `evidence_ids` 非空 |
| MIR-HARD-3 | score_formula_required | `opportunity_scores.formula` 含 6 项权重 |
| MIR-HARD-4 | no_data_no_strong_claim | 任一降级 fixture 跑完后，「强 / 趋势 / 差异」三类基因结论不触发 |

## 覆盖矩阵摘要

| 覆盖维度 | 必备用例 |
| --- | --- |
| 阈值边界 | MIR-RULE-SH-3/4, MIR-RULE-TR-1/2, MIR-RULE-DF-1/2, MIR-RULE-OS-2~7 |
| 数据缺失 | MIR-CSV-5, MIR-DAG-2/3/4, MIR-EVID-2 |
| 安全约束 | 无电商 API / 无登录 / LLM 不出数（隐式：通过代码静态检查 + MIR-SCHEMA-2） |
| 用户可见性 | MIR-UI-2/3/4 |
| 端到端可重现 | MIR-E2E-3 |