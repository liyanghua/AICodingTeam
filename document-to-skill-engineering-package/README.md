# Document-to-Skill Compiler 工程包

本工程包用于把业务策略文档编译成 Agent Runtime（OpenClaw / LangGraph / 自研 Runtime）可执行的 Skill。

当前样例基于 `examples/source_docs/20260519市场分析洞察元策略.md`，目标是将“市场洞察元策略”转成：

- `SKILL.md`：给 Agent Runtime 使用的技能说明。
- `skill.yaml`：Skill 元数据、输入输出、业务目标。
- `workflow.dag.yaml`：可执行流程 DAG。
- `data_requirements.yaml`：每个流程节点需要的数据资产。
- `tool_bindings.yaml`：数据需求到工具的绑定。
- `output_schemas/*.json`：结构化输出表 Schema。
- `eval_rules.yaml`：质量评测规则。
- `evidence_schema.yaml`：证据包 Schema。

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]

# 运行样例编译
python -m doc_to_skill.cli compile \
  --input examples/source_docs/20260519市场分析洞察元策略.md \
  --output build/market_insight_skill

# 查看生成结果
find build/market_insight_skill -maxdepth 3 -type f | sort

# 运行测试
pytest -q
```

## 核心理念

不要把文档直接变 Prompt。正确链路是：

```text
业务文档 → Strategy IR → Skill Spec → Workflow DAG → Data Requirement → Tool Binding → Evidence Pack → Eval
```

数据获取也不要直接变浏览器动作。文档中的“生意参谋、店透视、边界 BI、小红书、抖音”等数据源，需要先抽象成 Data Requirement，再由 Tool Resolver 决定使用内部 API、浏览器自动化、外部 Web Intelligence 或人工上传。

## 推荐 AI-coding 实施顺序

1. 跑通 `python -m doc_to_skill.cli compile`。
2. 完善 `src/doc_to_skill/parser.py`，支持更复杂的章节、表格、公式抽取。
3. 完善 `src/doc_to_skill/compiler.py`，把 Strategy IR 编译成 DAG、Schema、规则。
4. 接入真实 Tool Registry：内部数仓 API、Playwright/Stagehand、Exa/Web 工具。
5. 实现 Runtime Executor：按 `workflow.dag.yaml` 逐节点执行。
6. 实现 Evidence Pack 和 Eval Runner。
7. 将生成的 Skill 封装给 OpenClaw 或 LangGraph 调用。

## 目录结构

```text
.
├── AGENTS.md
├── README.md
├── pyproject.toml
├── docs/
├── specs/
├── src/doc_to_skill/
├── skills/market_insight/
├── tools/
├── examples/
└── tests/
```
