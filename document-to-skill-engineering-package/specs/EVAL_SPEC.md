# Eval 规范

## 1. 文档编译质量

| 指标 | 目标 |
|---|---|
| workflow_coverage | >= 0.9 |
| output_schema_coverage | >= 0.9 |
| data_requirement_coverage | >= 0.8 |
| rule_extraction_coverage | >= 0.6 |

## 2. Skill 执行质量

| 指标 | 目标 |
|---|---|
| dag_success_rate | >= 0.95 |
| tool_resolution_rate | >= 0.9 |
| evidence_completeness | >= 0.95 |
| replay_success_rate | >= 0.9 |

## 3. 业务输出质量

| 指标 | 目标 |
|---|---|
| recommendation_actionability | >= 0.85 |
| grounding_score | >= 0.9 |
| hallucination_risk | <= 0.05 |
| missing_required_output_count | 0 |

## 4. 市场洞察专用评测

- 必须输出 10 类成果。
- 每个机会点必须至少命中需求、增长、竞争、利润、供应链、差异化中的 3 个维度。
- 产品开发与链接规划必须包含目标人群、场景、定位、卖点、价格、竞品、主图方向、测试指标。
