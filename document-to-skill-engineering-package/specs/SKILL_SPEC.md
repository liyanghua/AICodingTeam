# Skill 包规范

一个 Skill 包必须包含以下文件：

```text
SKILL.md
skill.yaml
workflow.dag.yaml
data_requirements.yaml
tool_bindings.yaml
output_schemas/
eval_rules.yaml
evidence_schema.yaml
```

## SKILL.md

给 Agent 读取的人类可读执行指南。

必须包含：

- Purpose
- When to use
- Required inputs
- Workflow
- Data policy
- Evidence policy
- Output policy
- Failure handling

## skill.yaml

机器可读的 Skill 元信息。

```yaml
skill_id: market_insight
name: 市场洞察 Skill
version: 0.1.0
input_schema: {}
outputs: []
workflow_file: workflow.dag.yaml
data_requirements_file: data_requirements.yaml
tool_bindings_file: tool_bindings.yaml
eval_rules_file: eval_rules.yaml
```

## workflow.dag.yaml

可执行 DAG。

```yaml
nodes:
  - id: collect_top_products
    type: data_collect
    depends_on: [define_scope]
    data_requirement: category_top_products_300
    output: top_300_product_analysis_table
```
