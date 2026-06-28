# AGENTS.md

## 项目目标

构建 Document-to-Skill Compiler，将业务策略文档转换为 Agent Runtime 可执行的 Skill 包。

当前 MVP 聚焦“市场洞察元策略”文档，后续扩展到竞品分析、价格带布局、产品升级、主图策划、达人建联等业务策略文档。

## AI-coding 角色要求

你是一个资深 Agent Runtime / 数据平台 / 电商经营分析系统工程师。编码时必须遵守以下原则：

1. **文档不直接变 Prompt**：必须先转成 Strategy IR。
2. **数据来源不直接变浏览器操作**：必须先转成 Data Requirement。
3. **Tool 必须有 Contract**：输入、输出、业务语义、质量检查、权限、失败恢复、证据记录。
4. **每个结论必须可追溯**：最终输出必须绑定 Evidence Pack。
5. **LLM 不负责事实真实性**：LLM 只做结构化、分类、归纳、生成；事实来自 API、文件、浏览器或可引用数据。
6. **Runtime 必须可回放**：每次执行保留 node trace、tool call、raw data ref、computed metrics。

## 当前优先级

### P0

- 完成 `StrategyIR` 数据结构。
- 完成 `DocumentParser` 基础 Markdown 解析。
- 完成 `SkillCompiler` 生成 Skill 包。
- 完成市场洞察样例 Skill。
- 完成基础测试。

### P1

- 实现 Tool Registry。
- 实现 Tool Resolver。
- 实现 Evidence Store。
- 实现 Workflow Executor mock。

### P2

- 接入真实内部 API。
- 接入 Playwright / Stagehand 浏览器工具。
- 接入 Exa / Web Intelligence 工具。
- 接入 DeepEval / Ragas / Phoenix。

## 代码风格

- Python 3.11+。
- 使用 Pydantic 定义 Schema。
- 使用 `pathlib.Path` 处理路径。
- 所有外部 Tool 都先 mock，再实现真实 backend。
- 测试优先：任何核心编译逻辑都要有单元测试。

## 禁止事项

- 禁止把长文档直接塞给 LLM 生成最终报告。
- 禁止在没有数据证据时生成经营结论。
- 禁止把浏览器底层 click/type 暴露给业务 Runtime。
- 禁止 Tool 输出无 Schema 的自由文本。
- 禁止编造字段、指标、销量、GMV、增长率。
