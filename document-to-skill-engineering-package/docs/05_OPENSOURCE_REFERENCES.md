# 开源方案借鉴

## 文档解析

- Docling：复杂 PDF / Office / 表格 / 版面解析。
- MarkItDown：多格式文档快速转 Markdown。
- Unstructured：非结构化文档切分与预处理。

## Skill 生成

- book-to-skill：长文档/书籍转 Agent Skill 的整体思路。
- Anthropic skill-creator：Skill 编写、测试、迭代流程。
- agent-skills：生产级 Skill 结构、验证 gate、反自嗨表。

## Runtime

- LangGraph：状态机、DAG、人审、可恢复执行。
- OpenClaw：本地 Skill 执行环境。
- LlamaIndex Workflows：事件驱动 step workflow。
- Dify / Flowise：快速原型与可视化编排。

## Tool 协议

- MCP：AI 应用和工具/数据源的连接协议。
- Playwright MCP：浏览器自动化工具协议。
- OpenAPI / FastAPI：内部 API 工具化。

## 浏览器和外部数据

- Playwright：稳定浏览器自动化底座。
- Stagehand：AI + 代码混合浏览器自动化。
- browser-use：通用浏览器 Agent POC。
- Exa Agent / Websets：外部 Web research、enrichment、趋势信号。

## 数据治理和语义层

- OpenMetadata / DataHub：数据资产、血缘、治理。
- dbt + MetricFlow：指标语义层。
- Great Expectations / Soda：数据质量。

## 评测和观测

- DeepEval：LLM/Agent 输出测试。
- Ragas：RAG 和 grounding 评测。
- Phoenix：Trace、tool call、retrieval、LLM observability。
