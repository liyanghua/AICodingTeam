# Review Checklist: 市场分析洞察报告生成器

评审者对照本清单逐条勾选。任一条 NO 视为评审未通过。

## 1. PRD 引用与一致性

- [ ] PRD 8 节齐全，且每节四栏（来自 Skill / 标准段 / 定制段 / 禁止包含）非空。
- [ ] PRD 没有重述 `workflow.dag.yaml / data_requirements.yaml / output_schemas / eval_rules.yaml` 的字段内容，只引用。
- [ ] PRD 阈值与 `eval_rules.yaml` 完全一致，未二次发明。
- [ ] PRD 列出了 `customizations[]`，每条含「位置 / 行为 / 验收」三件套。
- [ ] PRD 顶部声明了应用形态 `report_generator`。

## 2. Skill 制品对齐

- [ ] `skill_ref/` 是 `document-to-skill-engineering-package/build/market_insight_skill/` 的只读拷贝或 symlink，版本号已记录在 `runs/<run_id>/meta.json`。
- [ ] DAG 节点拓扑、节点 type、依赖关系与 `workflow.dag.yaml` 完全一致。
- [ ] 6 个 `data_requirements` 的 required_fields 在 CSV schema 校验代码中完整覆盖。
- [ ] 10 个 `output_schemas/*.json` 在前端卡片绑定中完整覆盖。

## 3. 规则引擎正确性

- [ ] `strong_hot_gene / trend_hot_gene / differentiated_opportunity_gene` 三条规则在边界值（恰好触发 / 恰好不触发）测试通过。
- [ ] `opportunity_score` 的 6 项加权 + 4 档位判定与 `eval_rules.yaml` 公式一致；边界 85/84/70/69/60/59 测试通过。
- [ ] 阈值常量从 `eval_rules.yaml` 读取，未在源码中硬编码数值。
- [ ] 规则越线与档位判定不调用 LLM。

## 4. Evidence 与硬性约束

- [ ] 每条 CSV 上传都生成 Evidence Pack，字段含 `source_name / query_params / fetched_at / raw_response_id`。
- [ ] 任意 conclusion 的 `evidence_ids` 非空（违反则节点 failed）。
- [ ] `opportunity_scores.formula` 字段在 run artifact 中可追溯。
- [ ] 降级或缺数据的维度不参与「强 / 趋势 / 差异」基因结论。

## 5. 数据来源与安全

- [ ] 代码中无任何电商平台 API URL、SDK 引用、登录脚本。
- [ ] 没有新增 `requests / httpx / aiohttp` 等出网客户端依赖。
- [ ] LLM 调用点仅出现在两处（商品文本归类、评价文本痛点分类），且输出经过 schema 校验。
- [ ] 不读取或写入工作区以外的路径。

## 6. UI 与降级可见性

- [ ] 左侧节点进度条按 DAG 拓扑顺序展示 10 个节点。
- [ ] 节点 5 状态色（灰 / 蓝 / 绿 / 黄 / 红）正确实现。
- [ ] 失败时弹阻断对话框，含缺失字段列表。
- [ ] 降级时顶部横幅说明缺失维度。
- [ ] 导出报告按钮在 `score_opportunities` 未 `ok` 时灰显。

## 7. 测试覆盖

- [ ] `eval.md` 的 4 个 fixture（full / missing_reviews / missing_top_products / missing_cross_platform）全部跑通。
- [ ] 阈值边界用例 100% 通过。
- [ ] `output_schema_validity` = 1.00。
- [ ] `evidence_completeness` ≥ 0.95；`workflow_node_success_rate` ≥ 0.95。

## 8. 定制段映射

- [ ] PRD `customizations[]` 8 项全部实现，且每项行为 / 验收能在测试中追溯。
- [ ] 未新增 PRD 未声明的定制行为。
- [ ] 标准段代码（Shell + DAG runner 绑定 + 表 schema 渲染）在 deterministic fallback 模板下可重生（即移除定制段后，标准段仍可独立运行并产生最小化报告骨架）。

## 9. 方法论对齐

- [ ] 评审者已经按 `docs/business_doc_to_prd_method.md` 的「PRD 自检清单」逐条对照过。
- [ ] 评审过程发现的偏差已在评审报告中标注、推回 PRD 修订（而不是绕开 PRD 在代码层"修复"）。