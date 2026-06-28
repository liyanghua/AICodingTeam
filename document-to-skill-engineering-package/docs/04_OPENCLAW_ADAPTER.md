# OpenClaw Adapter 设计

## 目标

将生成的 Skill 包挂载到 OpenClaw / 本地 Agent Runtime，使其能执行市场洞察流程。

## 适配方式

```text
skills/market_insight/SKILL.md     → Agent 读取的技能说明
skills/market_insight/skill.yaml   → Runtime 读取的元数据
workflow.dag.yaml                  → Runtime DAG
工具层                             → MCP / OpenAPI / Python 函数
```

## 推荐封装

```python
class OpenClawSkillAdapter:
    def load_skill(self, skill_dir): ...
    def validate_inputs(self, inputs): ...
    def run(self, inputs): ...
    def emit_evidence(self, evidence): ...
```

## Runtime 节点映射

| DAG Node Type | OpenClaw 执行方式 |
|---|---|
| form_collect | 表单/用户上下文 |
| data_collect | Tool call |
| browser_collect | Browser Skill |
| external_research | Exa/Web Skill |
| compute | Python function |
| llm_structuring | LLM call with schema |
| scoring | Python function + rules |
| business_plan_generation | LLM generation + evidence check |
