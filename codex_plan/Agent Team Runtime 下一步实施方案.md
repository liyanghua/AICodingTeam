# Agent Team Runtime 下一步实施方案

## Summary
下一步不要继续只做“小红书采集器”，而是把当前 `growth_dev` 升级成一个可复用的 **Agent Team Runtime**。目标是：用户输入一次业务需求，系统自动生成任务包、分配角色、执行阶段、跑 Gate、输出报告；小红书五框架对比只是第一个 domain pack，以后换任务时复用同一套 team runtime。

默认路线：先做本地、文件驱动、确定性状态机版本，不引入 CrewAI/LangGraph 这类重框架。原因是当前项目是 Python stdlib 骨架，依赖少、可测、可控，最适合先把工程生产线跑通。

## Key Changes
新增三层抽象：

- **Team Runtime**
  - 新增 `growth-dev team run --brief "..."`
  - 负责读取需求、创建 run、调度 agents、执行 gates、生成报告。
  - 输出到 `runs/<run_id>/`，不直接混在 `tasks/current/`。

- **Agent Contract**
  - 每个 agent 是一个明确输入输出的 worker，不是自由聊天。
  - v1 agents：`orchestrator`、`product`、`architect`、`ux`、`qa`、`coder`、`reviewer`、`verifier`、`publisher`。
  - 每个 agent 必须输出固定 artifact，例如 `prd.md`、`tech_spec.md`、`ui_spec.md`、`eval.md`、`coding_prompt.md`。

- **Domain Pack**
  - 小红书任务变成第一个 domain：`domains/xhs_browser_benchmark/`。
  - 后续新任务只新增 domain pack，不重写 team runtime。
  - domain pack 定义输入 schema、输出 schema、评测规则、adapter 列表、风险规则。

## Implementation Plan
第一阶段：补齐标准工程任务包

- 把当前 `tasks/current/tdd_cases.md` 和 `review_checklist.md` 合并/映射成 `eval.md`，保留旧文件但让 `eval.md` 成为主入口。
- 新增 `tasks/current/team.yaml`，定义 agent 角色、执行顺序、输入输出、gate。
- 新增 `tasks/current/domain.yaml`，定义当前小红书 benchmark 的领域配置。
- 更新 `growth_dev/tasks.py`，让 `growth-dev xhs init` 生成完整八件套：
  - `task.yaml`
  - `context.md`
  - `prd.md`
  - `tech_spec.md`
  - `ui_spec.md`
  - `eval.md`
  - `coding_prompt.md`
  - `team.yaml`

第二阶段：实现 Team Runtime

- 新增 `growth_dev/team/models.py`
  - `TeamSpec`
  - `AgentSpec`
  - `AgentRun`
  - `GateSpec`
  - `TeamRunRecord`
- 新增 `growth_dev/team/runtime.py`
  - 负责按 `team.yaml` 执行 agent。
  - 每一步读取上游 artifacts，写入下游 artifacts。
  - 每一步记录 `status`、`started_at`、`finished_at`、`risk_events`、`output_paths`。
- 新增 `growth_dev/team/agents.py`
  - v1 先实现 deterministic/file-based agents。
  - agent 不调用真实 LLM，只根据 template 和上下文生成可执行文档。
  - 之后再替换为 Codex CLI / Claude Code / Hermes Skill runner。
- CLI 新增：
  - `growth-dev team init --domain xhs_browser_benchmark`
  - `growth-dev team run --brief "..."`
  - `growth-dev team status --run-id ...`
  - `growth-dev team report --run-id ...`

第三阶段：把小红书 benchmark 接入 Team Runtime

- 当前 `growth_dev/benchmark.py` 变成 `coder/verifier` 阶段的一部分。
- `orchestrator` 根据 brief 创建任务树。
- `product` 生成 PRD。
- `architect` 生成技术方案和数据契约。
- `ux` 生成 mock 页面/交互要求。
- `qa` 生成 `eval.md`。
- `coder` 生成或调用 adapter runner。
- `reviewer` 检查安全边界、schema、风险事件。
- `verifier` 跑 mock benchmark 和测试。
- `publisher` 生成最终 report。

第四阶段：验证复用性

- 保留小红书 benchmark 作为第一个 domain pack。
- 再新增一个最小第二任务，例如 `domains/web_monitoring/`：
  - 输入关键词和目标网页。
  - 输出页面摘要、变更检测、截图证据。
- 用同一个 `growth-dev team run` 跑第二任务。
- 验收标准：不修改 team runtime，只新增 domain pack 就能跑通第二类任务。

## Public Interfaces
新增命令：

```bash
growth-dev team init --domain xhs_browser_benchmark
growth-dev team run --brief "对比 5 个浏览器自动化框架完成小红书采集任务"
growth-dev team status --run-id <run_id>
growth-dev team report --run-id <run_id>
```

新增配置：

```yaml
# team.yaml
team_id: ai_native_engineering_team
agents:
  - id: orchestrator
    outputs: [task.yaml, context.md]
  - id: product
    outputs: [prd.md]
  - id: architect
    outputs: [tech_spec.md]
  - id: ux
    outputs: [ui_spec.md]
  - id: qa
    outputs: [eval.md]
  - id: coder
    outputs: [coding_prompt.md, code_run_record.json]
  - id: reviewer
    outputs: [review_report.md]
  - id: verifier
    outputs: [test_report.md]
  - id: publisher
    outputs: [final_report.md]
gates:
  before_coding: [prd.md, tech_spec.md, ui_spec.md, eval.md]
  before_publish: [review_report.md, test_report.md]
```

```yaml
# domain.yaml
domain_id: xhs_browser_benchmark
input_schema:
  keyword: string
  top_n: integer
  frameworks: list
risk_rules:
  - no_captcha_bypass
  - no_fingerprint_spoofing
  - no_proxy_rotation
  - manual_login_only
```

## Test Plan
- Unit tests
  - parse `team.yaml`
  - validate missing agent outputs
  - gate fails when required artifact is missing
  - gate passes when required artifacts exist
  - team run record serializes/deserializes correctly

- Integration tests
  - `growth-dev team init --domain xhs_browser_benchmark`
  - `growth-dev team run --brief "..."`
  - verify generated artifacts include the full eight-piece task pack
  - verify `review_report.md` flags missing live framework packages
  - verify `publisher` creates final report

- Reuse test
  - add a minimal second domain pack
  - run same team runtime
  - confirm no team runtime code changes are needed

## Assumptions
- v1 使用本地 deterministic agents，不直接调用真实 LLM。
- v2 再接 Codex CLI、Claude Code 或 Hermes。
- 小红书真实采集仍保持安全边界：人工登录、低频、遇到验证立即暂停。
- 当前五个浏览器框架 runner 先作为 coder/verifier 的工具层，不直接承担 orchestration。
- 目标不是“多 Agent 聊天”，而是“多 Agent 产物流水线”。
