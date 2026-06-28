# 技术规格

## 1. Python 包

核心包：`doc_to_skill`

### 子模块

- `schemas.py`：Pydantic 数据模型。
- `parser.py`：文档解析。
- `compiler.py`：Skill 编译。
- `tool_registry.py`：工具注册表。
- `tool_resolver.py`：工具匹配。
- `runtime.py`：Runtime mock。
- `evidence.py`：证据包。
- `evals.py`：评测。
- `cli.py`：命令行。

## 2. 输入

```bash
python -m doc_to_skill.cli compile --input <doc.md> --output <dir>
```

## 3. 输出

```text
<output>/
├── SKILL.md
├── skill.yaml
├── workflow.dag.yaml
├── data_requirements.yaml
├── tool_bindings.yaml
├── evidence_schema.yaml
├── eval_rules.yaml
└── output_schemas/
```

## 4. 错误处理

- 文档为空：报错。
- 无法识别流程：生成 fallback workflow，并标记 `needs_human_review=true`。
- 无法识别数据需求：生成 `missing_data_requirements.md`。
- 无法匹配工具：生成 `missing_tools_report.md`。

## 5. 质量门槛

- Workflow 至少 3 个节点。
- 每个 data_collect 节点必须绑定 Data Requirement。
- 每个 output 必须有 Schema。
- 每个评分规则必须可追溯。
