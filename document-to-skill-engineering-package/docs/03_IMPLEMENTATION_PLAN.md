# 实施计划

## Phase 0：工程初始化

- 初始化 Python 项目。
- 编写基础 Schema。
- 编写 CLI。
- 添加测试。

## Phase 1：市场洞察文档编译

- 解析业务场景。
- 解析 8 个经营问题。
- 解析 10 类输出物。
- 解析 10 步流程。
- 解析数据来源。
- 解析判断标准。

## Phase 2：Skill 包生成

- 生成 `SKILL.md`。
- 生成 `skill.yaml`。
- 生成 `workflow.dag.yaml`。
- 生成 `data_requirements.yaml`。
- 生成 `output_schemas/*.json`。
- 生成 `eval_rules.yaml`。

## Phase 3：Tool Registry

- 定义 Tool Contract。
- Mock 内部 API 工具。
- Mock 浏览器工具。
- Mock 外部 Web 工具。
- 实现 Tool Resolver。

## Phase 4：Runtime Execution

- 实现 DAG executor mock。
- 实现 node trace。
- 实现 evidence pack。
- 实现 replay artifact。

## Phase 5：真实工具接入

- 内部数仓 API。
- Playwright/Stagehand 浏览器采集。
- Exa/Web Intelligence。
- 文件上传型工具。

## Phase 6：评测闭环

- 输出质量评测。
- 数据完整度评测。
- 证据完整度评测。
- 业务 outcome 评测。
