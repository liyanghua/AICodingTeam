# PRD 生成轻量本地应用实施任务计划

## 状态

本文档是已执行的 v1 实施任务计划，用于说明 `app_generation` 从规范到实现的任务拆分、输入/输出和验证口径。它基于以下规范文档拆分任务：

- `docs/app_generation_prd_to_local_app_spec.md`
- `docs/app_generation_architecture.md`
- `docs/app_generation_acceptance_and_testing.md`

当前仓库已完成 T1-T9 的 v1 实现：domain pack、PRD artifact、app contract、CLI、Codex prompt/verifier、Dashboard PRD 模式、端到端 fake Codex 验收和文档收口。后续迭代仍应沿用本文的输入/输出/验证格式拆分增量任务。

本文档新增 T10-T27 作为后续 `PRD生成应用` 可观测工作台、PI-Agent 联动、节点流、评估体系、benchmark、右侧 Agent 操作协议和 Agent 驱动修复闭环的 spec-first 实施计划。T10-T27 尚未完整实现，必须先完成文档评审，再进入前端、API、AgentBridge、Artifact Preview Rail、评估 runner、auto-research、Agent action bridge 或 CodeAgentExecutor 实施。

## 实施目标

实现 `app_generation` 能力：用户输入 PRD 文本或 PRD 文件，并指定 `app_slug` 后，系统通过现有 Agent Team Runtime 生成一个轻量本地原型应用。v1 默认技术形态为原生 SPA + Node stdlib 本地服务，无数据库，浏览器 `localStorage` 作为唯一持久化层。

生成过程必须复用现有 run artifacts、Codex 隔离 worktree、review、verification 和人工确认 apply gate。

## 验收覆盖矩阵

| 验收标准 | 覆盖任务 |
| --- | --- |
| AC-001 原始 PRD 可审计 | T2, T4, T8 |
| AC-002 标准化 PRD 明确边界 | T3, T8 |
| AC-003 应用契约固定 v1 技术形态 | T1, T3, T8 |
| AC-004 生成代码路径受控 | T1, T5, T8 |
| AC-005 本地应用可预览 | T5, T6, T8 |
| AC-006 持久化只使用 localStorage | T1, T3, T5, T8 |
| AC-007 风险和 blocker 不隐藏 | T3, T5, T6, T7, T8 |
| AC-008 README 不误导 | T9 |
| AC-009 工作台节点可观测 | T10, T11, T14 |
| AC-010 Skill、tool call 和 usage 可见 | T10, T11, T12, T14 |
| AC-011 右侧 Agent Provider 可切换 | T12, T14 |
| AC-012 从节点重跑保留旧 run | T13, T14 |
| AC-013 业务友好节点标题和详情文案 | T14, T15 |
| AC-014 中间区两列布局与详情卡片 | T15 |
| AC-015 文件预览竖栏和多类型预览 | T16 |
| AC-016 节点与卡片文字不得溢出边框 | T15, T16 |
| AC-017 列宽可伸缩且预览位于中间与 Agent 之间 | T17 |
| AC-018 Benchmark 目录可审计 | T21 |
| AC-019 AGQS 评分可解释 | T21 |
| AC-020 Dingdang benchmark 覆盖关键产品规则 | T21 |
| AC-021 Auto-Research 优化不直接改事实源 | T21 |
| AC-022 AgentInteractionContext 联动当前卡片和产物 | T22 |
| AC-023 AgentAction 是改变事实源的唯一入口 | T22 |
| AC-024 PiAgentProvider 是薄桥接层 | T22 |
| AC-025 PI stream 终态归一 | T18, T19, T22, T23 |
| AC-026 Provider prompt 包含业务上下文摘要 | T24 |
| AC-027 intent=auto 可识别解释输入、解释输出和重跑节点 | T24 |
| AC-065 短期 patch_app 单文件单 patch | T26 |
| AC-066 复杂修复委托 Code Agent | T27 |

## T1: 定义 app_generation domain pack

### 输入

- `docs/app_generation_prd_to_local_app_spec.md`
- `docs/app_generation_architecture.md`
- `docs/app_generation_acceptance_and_testing.md`
- 现有 `DomainSpec` 结构
- 现有 domain pack 示例

### 中间过程

1. 创建 `domains/app_generation/domain.yaml`。
2. 声明输入 schema：`prd_text`、`prd_file`、`app_slug`、`ui_style`、`seed_data`。
3. 声明默认值：`output_root=generated_apps`、`frontend=native_spa`、`backend=node_stdlib`、`storage=localStorage`、`database=none`。
4. 声明 `allowed_paths`、`risk_rules`、`evaluation_rules` 和默认 `verification_commands`。
5. 确认 domain pack 不引入数据库、部署、凭证采集或隐藏网络调用。

### 输出

- `domains/app_generation/domain.yaml`

### 评估与验证

- domain pack 可被 `load_domain_spec("app_generation")` 解析。
- defaults、allowed paths、risk rules、evaluation rules 与规范一致。
- 验证命令：

```bash
python3 -m unittest tests.test_team_models tests.test_team_runtime -v
```

### 停止条件

- domain schema 无法被现有 `DomainSpec` 表达。
- allowed paths 无法精确限制到生成应用路径和必要支持路径。

## T2: PRD 输入与 app_slug 校验

### 输入

- `prd_text`
- `prd_file`
- `app_slug`
- `run_dir`

### 中间过程

1. 新增 `growth_dev/team/app_generation.py`。
2. 实现 PRD 读取逻辑：`prd_text` 和 `prd_file` 至少提供一个。
3. 当二者同时存在时，`prd_file` 是原始来源，`prd_text` 是补充说明。
4. 校验 `app_slug`：只允许小写字母、数字和连字符。
5. 拦截路径穿越、空白、`.`、`..`、斜杠和反斜杠。
6. 对疑似 secret、token、password、DSN 的摘要做脱敏。
7. 写入 `input_prd.md`。

### 输出

- `input_prd.md`
- 校验后的 `app_slug`
- 脱敏后的 PRD 摘要

### 评估与验证

- 覆盖 `prd_text`、`prd_file`、二者同时存在、缺失 PRD、非法 slug、疑似 secret 的测试。
- 验证命令：

```bash
python3 -m unittest tests.test_app_generation -v
```

### 停止条件

- PRD 内容需要读取工作区外文件且无法安全限制。
- PRD 中出现疑似 secret 且无法在 artifact 摘要中安全脱敏。

## T3: 生成标准化 PRD 与 app_contract

### 输入

- `input_prd.md`
- `DomainSpec`
- 用户 inputs
- 现有 `generate_complex_task_artifacts`

### 中间过程

1. 在 complex task 生成阶段识别 `domain_id=app_generation`。
2. 生成 `requirements/normalized_prd.md`。
3. 生成 `app_contract.json`。
4. 确保 `app_contract.json` 声明 `native_spa`、`node_stdlib`、`localStorage`、`database=none`。
5. 把 domain-specific required artifacts 加入 before-coding gate。
6. 继续生成官方 `acceptance_criteria.md`、`context_pack.md`、coverage matrix、TDD plan 和 slices。

### 输出

- `requirements/normalized_prd.md`
- `app_contract.json`
- `acceptance_criteria.md`
- `context_pack.md`
- `planning/acceptance_coverage_matrix.json`
- `planning/tdd_plan.json`
- `slices/*.yaml`

### 评估与验证

- deterministic run 能在 coder 前产出全部 required artifacts。
- 缺少 `input_prd.md`、`normalized_prd.md` 或 `app_contract.json` 时 gate 失败。
- 验证命令：

```bash
python3 -m unittest tests.test_team_runtime tests.test_app_generation -v
```

### 停止条件

- before-coding gate 仍无法区分 domain-specific required artifacts。
- 标准化 PRD 不能明确范围边界、假设和 blocker。

## T4: 增加 CLI 入口

### 输入

- `--prd-file`
- `--prd-text`
- `--app-slug`
- Codex/provider/planning 参数

### 中间过程

1. 在 `growth_dev/cli.py` 增加 `app generate` 子命令。
2. 将 PRD 参数转换为 `inputs_json`。
3. 内部调用现有 `team run --domain app_generation` 路径。
4. 默认后台运行，输出 run id、watch 命令和 artifact 目录。
5. 保留 `--foreground` 用于同步运行。
6. 对 `--env-file`、`--requirements-env-file` 等敏感参数继续使用现有 redaction 逻辑。

### 输出

- 后台模式：run id、pid、watch 命令、artifact 目录。
- 前台模式：TeamRunRecord JSON。

### 评估与验证

- CLI 测试覆盖参数解析、缺失 PRD、缺失 slug、后台 command redaction。
- 验证命令：

```bash
python3 -m unittest tests.test_team_cli -v
```

### 停止条件

- 新 CLI 必须绕开现有 TeamRuntime 才能工作。
- 新 CLI 被要求暴露部署、数据库或远端发布等 v1 范围外能力。

## T5: Codex prompt 与路径边界

### 输入

- `input_prd.md`
- `requirements/normalized_prd.md`
- `app_contract.json`
- `acceptance_criteria.md`
- `planning/acceptance_coverage_matrix.json`
- `planning/tdd_plan.json`
- `slices/*.yaml`
- allowed paths
- verification commands

### 中间过程

1. 扩展 Codex prompt bundle，把 app-generation artifacts 纳入 state summary。
2. 确保 prompt 明确生成应用路径：`generated_apps/<app_slug>/`。
3. 确保 allowed paths 包含精确生成目录和必要支持路径。
4. 禁止写 `.env`、run artifacts、第三方数据目录和未声明路径。
5. fake Codex 测试中分别模拟合法写入和越界写入。

### 输出

- `codex/codex_prompt.md`
- `codex/state_summary.md`
- `code_run_record.json`
- `codex/diff.patch`
- boundary violation 记录

### 评估与验证

- fake Codex 写入 `generated_apps/demo/` 时通过。
- fake Codex 写入 README 或 `.env` 时失败并记录 boundary violation。
- 验证命令：

```bash
python3 -m unittest tests.test_codex_executor -v
```

### 停止条件

- Codex 可以在未声明路径写入代码且不触发风险。
- prompt 未包含 PRD、app contract 或 verification commands。

## T6: 预览说明与 verifier

### 输入

- 生成应用目录
- `app_contract.json`
- Codex changed files
- verification commands

### 中间过程

1. verifier 读取 `app_contract.json`。
2. 检查 `generated_apps/<app_slug>/server.js` 是否存在。
3. 执行 `node --check generated_apps/<app_slug>/server.js`。
4. 生成 `preview_instructions.md`。
5. Node 不可用时记录 `node_binary_missing` blocker。
6. 缺少 `server.js` 或 preview 信息时记录 blocker。

### 输出

- `preview_instructions.md`
- `test_report.md`
- `codex/verification_record.json`

### 评估与验证

- 有 Node 时 syntax check 退出 0。
- 无 Node 或缺 `server.js` 时失败并记录 blocker。
- 验证命令：

```bash
python3 -m unittest tests.test_codex_executor tests.test_team_runtime -v
```

### 停止条件

- verifier 把 Node 缺失或 `server.js` 缺失误判为通过。
- preview instructions 没有明确本地命令和 URL。

## T7: Dashboard PRD 生成模式

### 输入

- PRD 文本
- `app_slug`
- 当前 Dashboard config
- run state API

### 中间过程

1. 在 Dashboard 增加“PRD 生成本地应用”模式。
2. 提交 payload 时使用 `domain=app_generation`。
3. 将 PRD 文本和 `app_slug` 放入 inputs。
4. 详情页展示原始 PRD、标准化 PRD、coverage、slice-loop、preview instructions、diff、风险和 blocker。
5. 未通过 apply gate 的生成结果不得显示为已应用。

### 输出

- Dashboard PRD 输入 UI
- Dashboard run payload
- Dashboard artifact 展示状态

### 评估与验证

- Dashboard 测试覆盖 payload、artifact 展示、风险展示和 apply 状态。
- 验证命令：

```bash
python3 -m unittest tests.test_dashboard -v
```

### 停止条件

- Dashboard 隐藏 risk events 或 blockers。
- Dashboard 将未 apply 的 worktree diff 表示为主工作区已变更。

## T8: 端到端验收场景

### 输入

- Todo PRD fixture
- fake Codex binary
- 临时 repo
- 临时 run_dir

### 中间过程

1. 通过 CLI 或 TeamRuntime 启动 `app_generation` run。
2. fake Codex 生成 `server.js`、`index.html`、`styles.css`、`app.js`。
3. verifier 执行 syntax check。
4. 生成 preview instructions。
5. final report 汇总生成文件、测试、风险和下一步动作。
6. 检查无数据库、无 secret、只使用 `localStorage`。

### 输出

- 完整 run artifacts
- worktree diff
- `preview_instructions.md`
- `final_report.md`

### 评估与验证

- 覆盖 AC-001 到 AC-007。
- changed files 全部位于 allowed paths。
- 验证命令：

```bash
python3 -m unittest tests.test_app_generation_e2e -v
```

### 停止条件

- 端到端 run 不能产生可审计 artifact 链路。
- 生成结果缺失本地预览路径或无法解释 blocker。

## T9: 文档与 README 收口

### 输入

- 真实 CLI 行为
- 真实 domain pack
- 真实 run artifacts
- 真实验证命令

### 中间过程

1. 根据实现结果更新三份 app-generation 文档。
2. 将“规划中”状态改为与实际实现一致的状态。
3. 只在功能真实可用后，才在 README 增加实际命令示例。
4. 确认 README 不声明未实现能力。

### 输出

- 更新后的 `docs/app_generation_*.md`
- 更新后的 `README.md`

### 评估与验证

- README 不误导。
- 文档中的命令与实际 CLI 一致。
- 验证命令：

```bash
python3 -m unittest tests.test_project_skills tests.test_design_contract -v
```

### 停止条件

- 文档描述与真实功能不一致。
- README 出现无法运行的命令示例。

## T10: 工作台节点与 NodeContext 聚合

### 输入

- `team_run_record.json`
- `events.jsonl`
- `task_journal.jsonl`
- `input_prd.md`
- `requirements/normalized_prd.md`
- `context_pack.md`
- `app_contract.json`
- `acceptance_criteria.md`
- `planning/acceptance_coverage_matrix.json`
- `planning/tdd_plan.json`
- `codex/implementation_trace.json`
- `codex/verification_record.json`
- `review_report.md`
- `test_report.md`
- `preview_instructions.md`
- `final_report.md`

### 中间过程

1. 定义固定节点列表。
2. 将现有 artifacts 映射到每个节点的 inputs、process 和 outputs。
3. 为每个节点补充 Project Skill 映射。
4. 从现有 trace、events 和 run record 聚合 tool calls。
5. 计算 `context_revision`。
6. 输出 `NodeContext`。

### 输出

- `NodeContext` API response。
- 节点状态列表。
- 节点 artifact refs。

### 评估与验证

- 每个固定节点都能返回。
- 缺失 artifact 不会被标记为 completed。
- `context_revision` 在节点、variant、override 或 artifact hash 变化时变化。
- 验证命令：

```bash
python3 -m unittest tests.test_dashboard -v
```

### 停止条件

- 无法从 artifacts 构造稳定节点状态。
- NodeContext 需要读取未允许路径。

## T11: Rule vs Codex/LLM 对比与 usage 聚合

### 输入

- NodeContext。
- Codex stdout / last message / implementation trace。
- requirements model artifacts。
- run record。

### 中间过程

1. 定义 variant：`rule`、`codex`、`llm`、`pi_agent`。
2. rule variant token 固定为 0。
3. Codex/LLM usage 只从真实记录解析。
4. usage 缺失时显示 `unknown`。
5. 用 deterministic rubric 计算产品效果评分。
6. 生成 comparison summary。

### 输出

- `usage_summary.json` 后续可选聚合 artifact。
- `comparison_summary.json` 后续可选聚合 artifact。
- 节点 variants 和 scores。

### 评估与验证

- rule token 为 0。
- 缺失 usage 时为 `unknown`。
- `implementation` 节点不会声明 rule 生成代码。
- 验证命令：

```bash
python3 -m unittest tests.test_dashboard -v
```

### 停止条件

- 需要伪造 token 才能展示 usage。
- 产品效果评分无法解释来源。

## T12: 右侧 AgentBridge 与 Provider 切换

### 输入

- NodeContext。
- Agent message。
- Provider config。

### 中间过程

1. 定义 `AgentBridge` 抽象。
2. 实现默认 `CodexBridge` 占位或受控调用。
3. 预留 `PiAgentBridge` 配置检查。
4. 预留 `GenericLlmBridge`。
5. 统一 AgentResponse 和 AgentAction。
6. 未配置 PI-Agent 时返回 `not_configured`。

### 输出

- Agent provider status。
- Agent response。
- Agent actions。
- tool call 和 usage 归一化结果。

### 评估与验证

- 默认 Provider 是 Codex。
- PI-Agent 未配置不影响 Codex。
- Agent action 不直接写旧 artifact。
- 验证命令：

```bash
python3 -m unittest tests.test_dashboard -v
```

### 停止条件

- PI-Agent 接入要求 Dashboard 硬编码其内部实现。
- Agent 可以绕过 NodeContext 直接修改 artifacts。

## T13: 从节点重跑与 comparison group

### 输入

- `source_run_id`
- `rerun_from_node`
- `selected_variant`
- `override_instructions`
- `comparison_group_id`
- 原始 PRD 和 app_slug。

### 中间过程

1. 校验 source run 存在且为 `app_generation`。
2. 校验节点 id 和 variant。
3. 将 override instructions 写入新 run inputs。
4. 创建新 run，不修改旧 run。
5. 将新 run 归入 comparison group。

### 输出

- 新 run id。
- rerun metadata。
- comparison group 关系。

### 评估与验证

- 旧 run artifacts 未变化。
- 新 run payload 包含完整 rerun metadata。
- 左侧任务列表能展示重跑关系。
- 验证命令：

```bash
python3 -m unittest tests.test_dashboard tests.test_team_cli -v
```

### 停止条件

- 重跑必须覆盖旧 run 才能工作。
- override instructions 被当作事实直接写入旧 artifact。

## T14: 三栏工作台前端

### 输入

- `/api/app-generation/runs`
- `/api/app-generation/runs/<run_id>/nodes`
- `/api/app-generation/runs/<run_id>/context`
- `/api/app-generation/agent/message`
- `/api/app-generation/rerun`

### 中间过程

1. 新增 `PRD生成应用` 入口。
2. 新增三栏页面。
3. 左侧展示 runs 和 comparison groups。
4. 中间接入节点事实层数据，先展示节点列表和当前节点摘要。
5. 右侧展示 Provider 选择和 Agent 对话。
6. 点击节点时刷新右侧 NodeContext。
7. Agent 返回 action 后进入待确认区。
8. 用户确认后触发 rerun。

### 输出

- Dashboard 工作台页面。
- 三栏布局骨架。
- Agent 协作 UI。
- rerun 操作 UI。

### 评估与验证

- 能看到节点列表。
- 能点击节点查看输入、执行过程、输出。
- 能看到 skill、tool call、usage 和 scores。
- 能切换 Agent Provider。
- 能从节点重跑并保留旧 run。
- 验证命令：

```bash
python3 -m unittest tests.test_dashboard -v
```

### 停止条件

- UI 隐藏风险事件。
- UI 将 Agent 建议表现为已应用事实。
- UI 将未 apply 的 worktree diff 表示为主工作区已变更。

## T15: 中间区信息架构、业务语言和详情卡片

### 输入

- T10 输出的节点列表和 `NodeContext`。
- T11 输出的 variants、usage 和 scores。
- T14 工作台页面骨架。
- `docs/app_generation_workbench_spec.md`
- `docs/app_generation_acceptance_and_testing.md`
- `DESIGN.md`

### 中间过程

1. 将中间区域拆成两列：左列竖排节点流，右列节点详情和中间产物。
2. 为固定节点建立业务友好中文标题映射。
3. 默认隐藏英文 `node_id`、executor、provider、artifact path、raw JSON 和日志。
4. 将技术字段映射为业务文案，例如 `prompt_tokens` 展示为 `输入 Token`。
5. 将节点详情拆成固定卡片：`Skill 路由`、`变体与对比`、`Project Skills`、`输入`、`输出`、`Tool calls · Usage · Scores · 风险`。
6. 为卡片使用浅色表面和可辨识边框，保持与 `DESIGN.md` tokens 一致。
7. 为节点、卡片、路径、JSON、日志和风险文本设置换行、截断或内部滚动策略。
8. 点击节点时只更新中间详情和右侧 `NodeContext`，不改变 run artifacts。

### 输出

- 中间两列布局。
- 业务友好节点标题和字段文案。
- 固定详情卡片集合。
- 长文本不溢出的 UI 规则。

### 评估与验证

- 节点流按业务顺序竖排展示。
- 默认节点标题为 `Skill 路由`、`PRD 输入`、`PRD 标准化`、`应用契约`、`规划与验收`、`应用实现`、`质量评审`、`验证结果`、`预览交付`。
- 节点详情包含六类固定卡片。
- usage、tool call、risk 和 score 使用业务友好标签。
- 长路径、URL、JSON、错误信息和日志片段不溢出边框。
- 验证命令：

```bash
python3 -m unittest tests.test_dashboard -v
```

### 停止条件

- 默认 UI 使用英文 `node_id` 替代业务标题。
- 卡片隐藏风险、blocker、usage unknown 或 tool call 缺失状态。
- 中间区布局遮挡左侧任务列表或右侧 Agent 区。
- 长文本溢出卡片边框或遮挡相邻内容。

## T16: Artifact Preview Rail 与受控文件预览

### 输入

- T10 输出的 artifact refs。
- T15 输出的节点详情和中间产物文件引用。
- `docs/app_generation_workbench_spec.md`
- `docs/app_generation_architecture.md`
- `docs/app_generation_node_context_contract.md`
- `docs/app_generation_acceptance_and_testing.md`

### 中间过程

1. 为 artifact refs 增加 preview 元信息：类型、大小、hash、来源节点和只读读取地址。
2. 增加只读 artifact preview 读取能力，路径限制在当前 run artifacts 或允许的 `generated_apps/<app_slug>/` 文件。
3. 拒绝绝对路径、路径穿越、跨 run 读取和未允许仓库路径。
4. 在工作台中增加文件预览竖栏，从中间产物文件引用打开。
5. 支持文本、代码、Markdown、JSON、YAML、HTML、CSS、JS、图片和 PDF 预览。
6. 未知二进制只展示元信息和不可内联预览提示。
7. 超大文件只展示元信息和大小限制提示，不默认加载正文。
8. 关闭或切换预览不改变 `NodeContext.context_revision`，除非 artifact 引用或 hash 变化。

### 输出

- 只读 artifact preview 契约。
- 文件预览竖栏 UI。
- 多文件类型预览策略。
- 文件预览路径安全校验。

### 评估与验证

- 当前 run artifact 可以从节点详情打开预览。
- 文本、JSON、图片、PDF、未知二进制和超大文件都有明确展示策略。
- preview path 安全校验覆盖路径穿越、绝对路径和跨 run 读取。
- 文件预览栏不替代右侧 Agent 协作区。
- 打开预览不写入 `user_overrides`，不触发重跑。
- 验证命令：

```bash
python3 -m unittest tests.test_dashboard -v
python3 -m unittest tests.test_app_generation -v
```

### 停止条件

- 文件预览可以读取未允许路径。
- 文件预览把未知二进制当作可执行内容处理。
- 文件预览覆盖或破坏右侧 Agent 对话区。
- 打开文件预览改变节点事实、variant 或用户 override。

## T17: 列宽伸缩与预览插位

### 输入

- T14 工作台骨架。
- T15 中间区信息架构。
- T16 文件预览竖栏。
- `docs/app_generation_workbench_spec.md`
- `docs/app_generation_architecture.md`
- `docs/app_generation_acceptance_and_testing.md`
- `DESIGN.md`

### 中间过程

1. 将左侧任务列表设为最小可读宽度，不允许被预览栏挤压到破坏扫描。
2. 为中间区两列增加可伸缩宽度约束，保留左列节点流和右列详情的弹性。
3. 让文件预览栏插入中间区与右侧 Agent 之间，默认占用中间区可伸缩空间。
4. 固定右侧 Agent 协作区的宽度和交互位置，保持 Provider、对话和动作区稳定。
5. 在窄屏下定义响应式降级顺序，优先保持任务列表和 Agent 面板可用。

### 输出

- 可伸缩布局约束。
- 预览栏插位规则。
- 左侧任务列表最小可读宽度规则。
- 右侧 Agent 固定宽度规则。

### 评估与验证

- 预览开启后左侧任务列表不被压缩。
- 预览栏出现在中间区和 Agent 区之间。
- 右侧 Agent 保持固定可用。
- 验证命令：

```bash
python3 -m unittest tests.test_dashboard -v
```

### 停止条件

- 预览栏覆盖右侧 Agent。
- 左侧任务列表因预览打开而不可读。
- 中间区无法伸缩，或所有列都固定死宽。

## T18: PiAgentProvider 真实接入（subprocess JSONL）

### 输入

- T13 输出的 `growth_dev/team/agent_bridge.py`（Provider 抽象 + CodexProvider + 占位 PiAgentProvider）。
- `docs/app_generation_agent_bridge_spec.md` `### pi_agent` 节（subprocess RPC + JSONL stdio 契约）。
- `docs/app_generation_acceptance_and_testing.md` 场景五。
- 参考实现：`PI_AGENT/db-archaeologist-pi-spec-pack/web/lib/rpc-bridge.mjs`。

### 中间过程

1. 在 `agent_bridge.py` 中把 `PiAgentProvider` 占位实现替换为真实 subprocess 实现：
   - 构造函数接受可注入的 `subprocess_launcher(cmd, env, cwd) -> Popen` 与 `event_parser(line) -> StreamEvent | None`，默认使用 `subprocess.Popen` + 内置解析。
   - `status(repo_root)` 按 `shutil.which(PI_BIN)` 命中与否判定，不再读 `PI_AGENT_BASE_URL` / `PI_AGENT_API_KEY`；env 由父进程透传。
   - 新增 `stream_message(node_context, agent_message)` 生成器：长驻单例子进程 `pi --mode rpc`，stdin 写一行 prompt JSONL（id 用 uuid），stdout 按行解析 `agent_event` / `response`，归一化为 `StreamEvent`。
   - 写写锁（threading.Lock）防止并发 prompt 串行化；按 id 维护 pending 队列与 `response` 配对。
   - 子进程异常退出 / 启动超时 → `status=error`，并对当前 pending prompt 补发 `upstream_error{phase:"stream_closed"}`。
   - 所有透传文本与 status message 经 `_redact_text` 处理。
2. 在 dashboard 关闭时回收子进程：注册 atexit hook 调 `terminate()`，超时后 `kill()`。
3. 不修改 CodexProvider；不写 `runs/<id>/` 任何 artifact；不改 runtime。

### 输出

- 真实 `PiAgentProvider`。
- 子进程生命周期管理（启动 / 健康检查 / 回收）。
- `StreamEvent` 序列符合 `agent_bridge_spec.md` 「流式增强」节。

### 评估与验证

- `pi` 在 PATH 时 `status=ready`，否则 `not_configured`。
- `tests/test_agent_bridge_pi_rpc.py` 覆盖 `docs/app_generation_acceptance_and_testing.md` 「PI 子进程测试合约」全部场景（fake launcher，不依赖系统 `pi`）。
- CodexProvider 原有 7 个测试不退化。
- 验证命令：

```bash
python3 -m unittest tests.test_agent_bridge -v
python3 -m unittest tests.test_agent_bridge_pi_rpc -v
python3 -m unittest tests.test_dashboard -v
```

### 停止条件

- dashboard 持有 PI 凭据或把 pi 凭据写入日志 / 响应 / artifact。
- pi 子进程在 dashboard 关闭后泄露成孤儿进程。
- PiAgentProvider 写入 `runs/<id>/` 或绕过 codex apply gate。
- 任一 SSE 事件未经 `_redact_text` 处理。

## T19: 右侧对话 SSE 通道

### 输入

- T18 输出的 `PiAgentProvider.stream_message`。
- `docs/app_generation_workbench_spec.md` 「右侧对话 SSE」节。
- `docs/app_generation_agent_bridge_spec.md` 「流式增强」节。
- `docs/app_generation_acceptance_and_testing.md` 场景七。

### 中间过程

1. 在 `dashboard.py` 新增 `POST /api/app-generation/agent/stream` 路由：
   - 解析 `{provider, mode, message, node_context_snapshot}`。
   - 调 `AgentBridge.get_provider(provider).stream_message(...)`。
   - 用 `_send_sse(generator)` helper 把每个 `StreamEvent` 序列化为 `data: <json>\n\n`。
   - 流关闭前若未发出 `agent_end`，必发 `upstream_error{phase:"stream_closed"}`。
2. 保留 `POST /api/app-generation/agent/message` 非流式路由不变（CodexProvider 主用，向后兼容）。
3. 在 `dashboard/app_generation.js` 中把右侧对话改造为 `fetch + ReadableStream`：
   - 增量渲染 `message_delta` 到当前 assistant 气泡。
   - `tool_call` 渲染工具卡（折叠 input），`tool_result` 补结果或错误。
   - `agent_end` 写入 usage 并关闭回合气泡。
   - `upstream_error` 标记当前回合为「已中断」，工具卡显示 `interrupted`。
   - 不自动重连；用户重发即新建回合。
4. Provider 切换逻辑：`pi_agent` 走 stream 路由，`codex` 仍走非流式；如 `pi_agent` 状态非 `ready`，前端在工具卡区域显示「PI 不可用，已回落到 codex」并把请求改投非流式路由。

### 输出

- `POST /api/app-generation/agent/stream` 路由。
- `_send_sse` 通用 helper（节点 SSE 也会复用，见 T20）。
- 右侧对话前端流式渲染。
- Provider 降级 UX。

### 评估与验证

- `fetch + ReadableStream` 在 PiAgentProvider 下能稳定收齐 `message_delta` × N → `tool_call`/`tool_result` → `agent_end`。
- 强制断开 stream 后，前端工具卡 / 回合气泡进入 `interrupted` 状态，历史气泡不受影响。
- 切换到 codex 后非流式 `agent/message` 仍可工作。
- 验证命令：

```bash
python3 -m unittest tests.test_dashboard -v
python3 -m unittest tests.test_agent_bridge_pi_rpc -v
```

### 停止条件

- stream 路由写入 `runs/<id>/`。
- 前端把 `message_delta` 累计为 usage 近似值。
- 流关闭未发 `upstream_error` 时，前端误把回合标记为 `completed`。

## T20: PRD 上传 + 节点 SSE 流

### 输入

- T19 输出的 `_send_sse` helper。
- `docs/app_generation_workbench_spec.md` 「PRD 上传与自动节点流」节。
- `docs/app_generation_acceptance_and_testing.md` 场景六、PRD 上传测试合约、SSE tailing 测试合约。
- 现有 `runtime.py`（已写 `runs/<id>/events.jsonl` 与 `team_run_record.json`）。

### 中间过程

1. 在 `dashboard.py` 新增 `POST /api/app-generation/runs`：
   - 解析 `{prd_text, prd_filename?, executor, app_slug?, comparison_group_id?}`。
   - 无任何 size 硬限制；`app_slug` 走 v1 校验拒路径穿越。
   - 创建 `runs/<run_id>/` 与 `input_prd.md`，初始化 `team_run_record.json`。
   - 后台线程启动 `runtime.run_team(...)`。
   - 同步返回 `{run_id, runs_dir, events_stream}`。
2. 新增 `GET /api/app-generation/runs/<run_id>/events/stream`：
   - 调用新增的 `_stream_app_generation_events(run_id)` 生成器。
   - 首帧从 `team_run_record.json` 计算 `snapshot`（6 个固定节点 + 当前状态）。
   - poll `events.jsonl` tail（每 250ms），把新行归一化为 `node_state` 或 `agent_event`。
   - 所有节点到终态后发 `run_finished` 并自然结束。
   - 心跳：每 15s 一条 `:heartbeat`。
3. 在 `runtime.py` 6 个固定节点边界处补 `workbench_node_started/completed` 事件（写入 `events.jsonl`），保留 `node_id` 字段；不修改既有 `run_started/run_failed` 事件。
4. 在 `dashboard/app_generation.js` 添加「新建 run」面板：
   - 文本框 + 拖入 `.md/.txt` 文件（前端读为 UTF-8）。
   - executor 下拉来自 `state.executors`（dashboard `_app_generation_executor_options` 暴露）。
   - 提交后用 `EventSource` 订阅 `events_stream`，把 `snapshot` 覆盖到本地节点状态，`node_state` 增量更新。
   - 断线 `onerror` 自动 5s 重连，重连后用新的 `snapshot` 覆盖。
   - 收到 `run_finished` 后关闭订阅。
5. 节点 SSE 不依赖右侧 Provider 状态；右侧对话流断开不影响节点流。

### 输出

- `POST /api/app-generation/runs` 上传 API。
- `GET /api/app-generation/runs/<run_id>/events/stream` 节点 SSE 通道。
- runtime 6 节点边界事件。
- 「新建 run」前端面板 + 节点流增量渲染。

### 评估与验证

- 上传合法 PRD → `runs/<run_id>/input_prd.md` 内容与请求一致。
- deterministic 路径 ≤ 3s 完成所有节点，`run_finished` 含 `terminal_status=completed`。
- 5 MB PRD 文本可成功上传并完整落盘，无截断。
- 强制断开 SSE 3s 后前端自动重连，`snapshot` 与 `team_run_record.json` 一致。
- 节点 SSE 流的事件可由 `runs/<id>/` 完整重放。
- 验证命令：

```bash
python3 -m unittest tests.test_dashboard -v
python3 -m unittest tests.test_runtime -v
python3 -m unittest tests.test_app_generation -v
```

### 停止条件

- 上传 API 静默截断 PRD。
- 节点 SSE 引入无法由 `runs/<id>/` 重放的事件来源（例如直接读 PI 子进程状态）。
- `EventSource` 重连后丢失某个节点的最终状态。
- runtime 在 6 节点边界外随意发 `node_state` 事件（事件源失真）。

## T21: 评估体系与 Dingdang Benchmark

### 输入

- `docs/app_generation_evaluation_and_benchmark_spec.md`
- `benchmarks/app_generation/dingdang_main_image_agent/input_prd.md`
- `benchmarks/app_generation/dingdang_main_image_agent/benchmark.yaml`
- `benchmarks/app_generation/dingdang_main_image_agent/acceptance_criteria.md`
- `benchmarks/app_generation/dingdang_main_image_agent/expected_capabilities.json`
- `benchmarks/app_generation/dingdang_main_image_agent/scoring_rubric.json`
- 可选参考应用：`benchmarks/app_generation/dingdang_main_image_agent/reference_app/`
- 一个或多个 `app_generation` run artifacts

### 中间过程

1. 读取 benchmark manifest，校验 `benchmark_id`、输入 PRD、验收标准、能力清单和 scoring rubric。
2. 校验 benchmark 目录不包含 `.env`、`.DS_Store`、`node_modules/`、真实 secret 或路径穿越引用。
3. 读取 run artifacts 和 NodeContext，抽取节点产物、tool calls、usage、scores、risks 和 generated app 文件引用。
4. 运行 AGQS scorer，输出 7 个维度的分数、证据引用、评分理由和风险。
5. 运行 hard gate checker，限制总分或标记失败。
6. 针对 Dingdang benchmark 检查四阶段流程、Stage 1 阻断、Stage 2 单选且禁止混搭、8 张图规划、平台策略、Prompt 分层和局部迭代。
7. 聚合 usage 和成本。rule token 为 0；Codex/LLM/PI-Agent 使用真实 usage；缺失时显示 `unknown`。
8. 生成 comparison report 和 top gaps。
9. auto-research 模式只输出优化假设和待确认动作，不修改旧 run artifacts 或主工作区代码。

### 输出

- benchmark loader 结果。
- AGQS 评分报告。
- hard gate 报告。
- Dingdang capability coverage。
- usage / cost summary。
- comparison report。
- auto-research 优化建议。

### 评估与验证

- benchmark 目录契约可被静态检查。
- `expected_capabilities.json` 和 `scoring_rubric.json` 可解析。
- `.env`、`.DS_Store` 和 `node_modules/` 不存在于 benchmark。
- Dingdang 关键规则都有验收标准和机器可读 capability。
- usage 缺失时为 `unknown`，不得伪造。
- 验证命令：

```bash
rg -n "AGQS|benchmark|auto-research|Dingdang|hard gate|scoring_rubric" docs benchmarks
find benchmarks/app_generation/dingdang_main_image_agent -name ".env" -o -name ".DS_Store" -o -name "node_modules"
python3 -m json.tool benchmarks/app_generation/dingdang_main_image_agent/expected_capabilities.json
python3 -m json.tool benchmarks/app_generation/dingdang_main_image_agent/scoring_rubric.json
```

### 停止条件

- benchmark 需要包含真实 `.env` 或凭证才能运行。
- 评分体系必须依赖人工主观印象且无法引用证据。
- auto-research 需要自动覆盖旧 run 或绕过人工 apply gate。
- 为 Dingdang benchmark 写死通用 runtime 逻辑。

## T22: 右侧 Agent 操作协议与 PI-Agent 分工收口

### 输入

- `docs/app_generation_agent_bridge_spec.md`
- `docs/app_generation_node_context_contract.md`
- `docs/app_generation_workbench_spec.md`
- `docs/app_generation_architecture.md`
- `docs/app_generation_acceptance_and_testing.md`
- T10 输出的 `NodeContext`
- T16 输出的 artifact preview refs
- T18/T19 输出的 `PiAgentProvider` 和右侧对话 SSE

### 中间过程

1. 在前端状态中维护 `AgentInteractionContext`：当前详情卡片、当前 artifact、选中文本、view mode 和 allowed operations。
2. 右侧 Agent 请求同时发送 `NodeContext` 与 `AgentInteractionContext`，默认 `intent=auto`。
3. AgentBridge 根据 focus 和用户消息构造 Provider prompt，不再只写死“解释节点”。
4. 为 PI-Agent stream 终态归一：`agent_end`、`response{success:true}` 和 `upstream_error` 都是终态；只有真实异常关闭才显示 `stream_closed`。
5. 将 Provider 输出归一为 `message` + `AgentAction[]`。流式 Provider 的 actions 放在 `agent_end.payload.actions`。
6. 实现或预留受控 `read_artifact` 动作，只能读取当前 run artifact 或允许 generated app 文件。
7. `suggest_input_patch`、`patch_artifact`、`patch_app` 和 `rerun_from_node` 全部进入待确认动作区。
8. 用户确认后才调用 override、rerun 或 apply gate；未确认前不得修改旧 run artifacts。
9. PI tool calls 只作为右侧 tool evidence 展示；未转成 AgentAction 并确认前，不进入节点事实层。

### 输出

- `AgentInteractionContext` 前端状态与请求 payload。
- AgentBridge focus-aware prompt / action bridge。
- `AgentAction` 待确认区。
- 受控 artifact read 动作。
- PI stream 终态归一测试。
- PI-Agent Provider 薄桥接边界测试。

### 评估与验证

- 点击节点、详情卡片、文件预览和选中文本会改变 `interaction_context.focus`。
- PI-Agent 在 `intent=auto` 下能围绕当前 artifact 回答，而不是只解释节点摘要。
- `read_artifact` 不改变 `context_revision`。
- `suggest_*` 动作不写旧 artifact。
- `rerun_from_node` 确认后创建新 run，旧 run 保持不变。
- `response{success:true}` 无 `agent_end` 时合成为正常终态。
- `upstream_error` 不被外层重复包装。
- 验证命令：

```bash
python3 -m unittest tests.test_agent_bridge_pi_rpc -v
python3 -m unittest tests.test_agent_bridge -v
python3 -m unittest tests.test_dashboard -v
```

### 停止条件

- 右侧 Agent 必须直接覆盖 artifact 才能完成操作。
- Provider 需要实现第二套业务 Agent 逻辑。
- PI tool call 副作用无法在 UI 中展示或审计。
- Agent action 无法绑定 `context_revision`。

## T23: PI RPC 真实事件协议对齐

### 输入

- `docs/app_generation_agent_bridge_spec.md`
- 当前 `growth_dev/team/pi_rpc.py`
- 真实 `pi --mode rpc` stdout JSONL 样例
- `tests/test_agent_bridge_pi_rpc.py`

### 中间过程

1. 用真实 PI JSONL 格式重写 `default_event_parser`：
   - `message_update.assistantMessageEvent.text_delta` → `message_delta`。
   - `thinking_delta` / `thinking_start` / `thinking_end` 不进入答案文本，可作为折叠 thinking evidence。
   - `tool_execution_start` → `tool_call`。
   - `tool_execution_end` → `tool_result`。
   - `agent_end` / `turn_end` / `response` 归一为终态。
2. 将 `PiRpcClient` 路由改为单活跃 prompt 模型：
   - 无 id 的流事件投递到当前 active queue。
   - `response{id}` 只负责命令回执和终态确认。
   - stdout 关闭时只向 active prompt 发送 `stream_closed`。
3. 改写测试 fixture，禁止继续使用虚构 `agent_event/event_type/id` 作为唯一协议样例。
4. 真机探测真实 stdout 字段和时序，记录 PI_DEFAULT_THINKING 哪个档位稳定输出正式 `text_delta`。

### 输出

- 真实 PI 协议解析器。
- 单活跃 prompt 路由。
- 真实协议测试 fixture。
- 真机探测记录。

### 评估与验证

- 正式答案进入 `message_delta`，thinking 不进入答案气泡。
- 无 id 流事件不会被丢弃。
- `tool_execution_start/end` 能显示为 tool call / tool result。
- `response{success:false}` 归一为 `upstream_error`。
- 验证命令：

```bash
python3 -m unittest tests.test_agent_bridge_pi_rpc -v
python3 -m unittest tests.test_agent_bridge tests.test_dashboard -v
```

### 停止条件

- 无法取得真实 PI stdout 样例。
- PI 多 prompt 并发成为硬需求，单活跃 prompt 模型不再成立。
- thinking 与正式答案无法从协议字段区分。

## T24: Provider 上下文增强与 auto 意图路由

### 输入

- `docs/app_generation_agent_bridge_spec.md`
- `docs/app_generation_node_context_contract.md`
- `docs/app_generation_workbench_spec.md`
- T10/T11 输出的节点 view model 与 `NodeContext`
- T22 输出的 `AgentInteractionContext`
- T23 输出的 PI stream 真实协议

### 中间过程

1. 新增 `AgentPromptContext` 构造函数，把 `NodeContext` + `AgentInteractionContext` 派生为业务友好上下文包。
2. `AgentPromptContext` 必须包含节点标题、节点摘要、输入列表、输出列表、当前 focus、artifact title/path/summary/hash、skills、tool calls、usage、scores、risks 和 allowed operations。
3. 禁止 Provider prompt 只传节点 id、输入数量、输出数量或风险数量。
4. 新增轻量 `resolve_intent(message, interaction_context, node_context)`：
   - “这个节点干啥” → `explain_node`。
   - “输入是什么” → `explain_inputs`。
   - “输出/产物是什么” → `explain_outputs`。
   - “读这个文件/解释当前产物” → `read_artifact`。
   - “对比/哪个更好/usage/token” → `compare_variants`。
   - “改/补充/调整” → 无 focus 时 `suggest_input_patch`；`focus.card="file_preview"` 时 `patch_artifact`；`focus.card="app_preview"` 且已发布时 `patch_app`。
   - “重跑/重新生成/再跑/rerun/基于这个文件重新生成” → `rerun_from_node`（target 为当前节点或 artifact 所属节点）。
5. 路由结果必须受 `allowed_operations` 限制；不允许的动作降级为解释或澄清。
6. CodexProvider、PiAgentProvider、GenericLlmProvider 使用同一个 `resolved_intent` 与 `AgentPromptContext`。
7. 为 `read_artifact` 设计两步流：先返回 action，读取结果作为 tool evidence 注入下一轮 prompt，不改变 `context_revision`。

### 输出

- `AgentPromptContext` 构造和测试。
- `resolved_intent` 路由和测试。
- PI prompt 上下文增强。
- Codex/LLM prompt 上下文增强。
- `read_artifact` 二段式上下文注入规范或实现。

### 评估与验证

- 用户问“这个节点干啥”时，Provider prompt 包含业务标题和节点摘要。
- 用户问“输入是什么”时，Provider prompt 包含输入 artifact 的 title/path/summary/status。
- 用户问“输出是什么”时，Provider prompt 包含输出 artifact 的 title/path/summary/status。
- 用户在 `mode=explain` 下说“重新跑这个节点”，`resolved_intent=rerun_from_node`，返回待确认 `rerun_from_node`。
- 用户聚焦 artifact 并说"基于这个文件重新生成"，返回待确认 `rerun_from_node`（target 为 artifact 所属节点）。
- 不在 `allowed_operations` 中的动作不会被返回。
- 验证命令：

```bash
python3 -m unittest tests.test_agent_bridge -v
python3 -m unittest tests.test_agent_bridge_pi_rpc -v
python3 -m unittest tests.test_dashboard -v
```

### 停止条件

- 业务节点标题和 artifact 摘要无法从现有 Dashboard view model 取得。
- `allowed_operations` 无法可靠计算。
- 完整 artifact 读取无法被路径边界限制。

## T25: Benchmark parity 生成质量门禁

### 输入

- `docs/app_generation_evaluation_and_benchmark_spec.md`
- `benchmarks/app_generation/dingdang_main_image_agent/`
- 已有 `app_generation` runtime、Codex prompt bundle 和 failure classification。

### 中间过程

1. 将普通 PRD 的 `prototype` 模式与 benchmark PRD 的 `benchmark_parity` 模式分开。
2. 当 `prd_file` 命中 `benchmarks/app_generation/<benchmark_id>/input_prd.md` 时，读取 benchmark manifest、验收标准、能力清单和 rubric。
3. 写入 `benchmark_context.json` 与 `benchmark_context.md`，并注入 Codex state summary。
4. Dingdang benchmark parity 下，把产品图上传、参考图上传、图片 provider、单张/批量出图、Prompt 下载、图片下载和 provider setup error 作为必需能力。
5. 生成完成后输出 `benchmark_diff.md` 和 `agqs_score.json`。
6. 修复 failure classification，sandbox preview EPERM 和 provider setup warning 不得误判为 blocking。

### 输出

- benchmark context artifacts。
- benchmark diff 和 AGQS 初评分 artifacts。
- 更新后的 Dingdang benchmark metadata。
- 静态 parity 检查和 warning/blocking 分类测试。

### 评估与验证

```bash
python3 -m unittest tests.test_app_generation tests.test_codex_executor -v
python3 -m unittest tests.test_dashboard tests.test_team_cli -v
```

### 停止条件

- 为单个 benchmark 写死 runtime 逻辑。
- 生成应用必须保存真实 secret 才能通过测试。
- 普通 PRD 被强制要求图片 provider。

## T26: 短期 patch_app 稳定化

### 输入

- `docs/app_generation_agent_driven_repair_spec.md`
- `docs/app_generation_agent_bridge_spec.md`
- `docs/app_generation_node_context_contract.md`
- 当前 Dashboard `patch_app` dry-run/apply API。
- 当前 AgentBridge provider prompt 和 action fallback。

### 中间过程

1. 收紧 PI-Agent / LLM action protocol：`target_path` 必须使用 `generated_apps/<slug>/<file>`。
2. 在 prompt 与 deterministic fallback 中明确：同一文件多处修改必须使用单个 `replace_block` 和已存在 `AGENT_EDIT` 区间。
3. 在后端 action validation 中拒绝同一 PatchSet 内重复 `target_path`，并返回可行动错误，提示改用 `replace_block` 或 `delegate_code_repair`。
4. 确保 `app_patch_targets` 在 `patch_app` intent 下始终注入，包括用户当前聚焦 `implementation` 或 `preview_delivery` 节点但诉求明显指向已发布应用时。
5. 对 `process.env`、`.env`、API key 和日志脱敏做回归，避免 redaction 破坏 `old_content`。
6. dry-run 失败时，右侧 Agent 展示失败原因、目标文件、建议下一步，而不是只显示底层错误。

### 输出

- 更新后的 AgentBridge action protocol。
- `patch_app` validation 和错误映射。
- 前端 dry-run 失败展示。
- 单文件单 patch、重复 target、target path 越界、redaction 回归测试。

### 评估与验证

```bash
python3 -m unittest tests.test_agent_bridge tests.test_dashboard -v
node --check dashboard/app_generation.js
```

验收信号：

- `generated_apps/input-prd/server.js` 可通过 `patch_app` dry-run。
- `<slug>/server.js`、`server.js`、`worktree/...` 和 `codex/...` 被拒绝。
- 同一个 PatchSet 对同一文件输出多个 patch 时，被拒绝并提示“合并为单个 replace_block 或委托 Code Agent”。
- `process.env.OPENROUTER_IMAGE_MODEL` 不会被 redaction 改坏。

### 停止条件

- 已发布应用没有任何 `AGENT_EDIT` 锚点，且目标修改不是唯一文本替换。
- 需要跨文件或跨函数理解才能修复。
- Agent 无法构造精确 `old_content` 或稳定 `replace_block`。

## T27: 长期 delegate_code_repair 与 CodeAgentExecutor

### 输入

- T26 的 `patch_app` 稳定化结果。
- `docs/app_generation_agent_driven_repair_spec.md` 的 `delegate_code_repair` 契约。
- 当前 Codex executor、run artifacts、preview runner 和 app patch APIs。

### 中间过程

1. 新增 `delegate_code_repair` AgentAction，并在右侧 Agent 待确认动作区展示 repair request。
2. 新增 `CodeAgentExecutor` 抽象，Codex 作为默认 provider；未来 PI-code 或通用 LLM-code 必须作为 provider 接入同一抽象。
3. Code Agent 只读取当前已发布快照 `runs/<run_id>/generated_apps/<slug>/`、允许的 patch 历史、preview 状态、日志摘要和用户 repair request。
4. Code Agent 输出 PatchSet 或 unified diff，不直接写文件。
5. 框架复用现有 dry-run、用户确认、apply、验证、证据记录和预览重启流程。
6. repair run 写入 `app_repairs/<repair_id>/`，包含 prompt、context summary、diff、verification 和 usage。
7. 成功修复后写 `AdjustmentEvent`，并允许用户选择 `promote_patch_to_generation_rule`。

### 输出

- `delegate_code_repair` API / SSE 事件。
- `CodeAgentExecutor` provider 抽象和 Codex provider。
- repair artifacts：`app_repairs/<repair_id>/context.md`、`diff.patch`、`verification.json`。
- 前端 repair action card、diff 预览、确认、验证和回滚入口。

### 评估与验证

```bash
python3 -m unittest tests.test_agent_bridge tests.test_codex_executor tests.test_dashboard -v
python3 -m unittest tests.test_app_preview_runner -v
```

验收信号：

- 用户说“只修改当前已发布应用，不重跑 PRD”时，复杂修复生成 `delegate_code_repair`，不是 `rerun_from_node`。
- Code Agent 修复目标限制在 `generated_apps/<slug>/`。
- Code Agent 输出仍需用户确认后才 apply。
- 修复后执行语法检查、runtime smoke、preview health，并写 `AdjustmentEvent`。
- 失败时保留旧预览进程和旧文件，diff 和错误可见。

### 停止条件

- 无法把 Code Agent 的文件读取限制在当前已发布快照。
- Code Agent 需要真实 API key 才能生成 patch。
- repair 输出不能回到统一 PatchSet/diff/确认闭环。

## T28: Codex 执行过程可观测

### 输入

- T27 的 `CodeAgentExecutor` 和 `delegate_code_repair` 两阶段执行模型。
- `docs/app_generation_codex_observability_spec.md` 的 `CodexProgressEvent` 契约。
- 现有 `CodexExecutor` stdout/stderr 落盘、run SSE 和 Dashboard 节点详情 UI。

### 中间过程

1. 为 Codex 执行阶段增加 progress recorder，把 stdout JSONL、阶段开始/完成、验证和 diff 生成转换为业务友好的 `CodexProgressEvent`。
2. `implementation` 节点写 `codex/coder_progress.jsonl` 和 `codex/coder_progress_status.json`。
3. `delegate_code_repair` prepare 写 `app_repairs/<repair_id>/progress.jsonl` 和 `progress_status.json`。
4. 扩展 run SSE，新增 `node_progress` 事件，用于推送 implementation 节点的实时执行过程。
5. 新增 `delegate-code-repair/status?repair_id=<repair_id>` 只读 API，供右侧 Agent 区在 prepare 长请求期间轮询。
6. 前端节点详情「执行过程」卡片展示实时 timeline，右侧 Agent 区展示「Code Agent 修复进度」卡片。
7. 增加 app repair 越界修改检测：候选修改超出 `worktree/generated_apps/<slug>/` 时 prepare failed，旧应用不变。

### 输出

- progress artifacts：`coder_progress.jsonl`、`coder_progress_status.json`、`app_repairs/<repair_id>/progress.jsonl`、`progress_status.json`。
- API / SSE：`node_progress`、`delegate-code-repair/status`。
- UI：implementation 实时执行 timeline、右侧 Code Agent 修复进度卡片。
- 风险事件：`outside_repair_scope_changes`。

### 评估与验证

```bash
python3 -m unittest tests.test_codex_executor tests.test_dashboard -v
node --check dashboard/app_generation.js
```

验收信号：

- 用户等待 implementation 节点时能看到 Codex 最近执行的命令、文件修改和验证状态。
- 用户等待 `delegate_code_repair` prepare 时能看到 Code Agent 修复进度，而不是只看到“正在准备候选 diff”。
- 30 秒无新事件时显示“Code Agent 仍在运行，暂无新输出”。
- progress 事件脱敏、截断，不包含 API key、完整 `.env`、完整 prompt 或完整源码。
- Codex 修改 repair 范围外文件时 prepare failed，旧应用不变。

### 停止条件

- 无法从 Codex stdout JSONL 稳定解析 progress 事件。
- 进度事件可能泄露 secret 或完整源码。
- `delegate_code_repair` 的 progress API 需要引入数据库或外部队列。

## T29: V2.0 CanvasObject 投影与业务节点轨道

### 输入

- `docs/app_generation_canvas_experience_spec.md` 的 V2.0 范围。
- 现有 `build_app_generation_nodes()`、`build_app_generation_node_context()`、run artifacts、preview status 和 evaluation artifacts。
- AC-074、AC-075、AC-076、AC-077。

### 中间过程

1. 新增只读 `CanvasProjection` 聚合层，从 run artifacts 投影业务节点和 `CanvasObject`。
2. 固定六个业务节点：理解业务目标、编译业务规格、规划应用结构、生成应用原型、验证业务能力、输出可交付版本。
3. 建立 V1 runtime node 到 V2 业务节点的映射表。
4. 从 `input_prd.md`、`app_contract.json`、`planning/*`、`generated_apps/<slug>/`、`codex/app_runtime_verification.json`、`benchmark_diff.md`、`agqs_score.json`、`adjustment_events.jsonl` 提取对象摘要。
5. 新增只读 API：`GET /api/app-generation/runs/<run_id>/canvas`。
6. 前端在现有中间区增加“业务对象”视图，不大改布局。
7. Code Agent 进度卡片使用业务文案映射，不默认展示 raw stdout。

### 输出

- `CanvasObject` 投影 API。
- 业务节点轨道数据结构。
- 前端业务对象 tab / panel。
- `CanvasSelectionContext` 前端状态。

### 评估与验证

```bash
python3 -m unittest tests.test_dashboard tests.test_codex_executor -v
node --check dashboard/app_generation.js
```

验收信号：

- 页面刷新后对象投影可从 artifacts 重建。
- 业务节点默认展示中文标题。
- 点击对象后右侧 Agent 请求带 `CanvasSelectionContext`。
- 30 秒无 Codex progress 事件时展示业务等待提示。

### 停止条件

- 对象投影需要依赖浏览器 localStorage 才能重建。
- 对象投影需要读取 secret、完整 `.env`、完整源码或完整 stdout。
- 无法稳定映射 V1 node 到六个业务节点。

### 可执行子任务

| 子任务 | 输入 | 中间过程 | 输出 | 验证命令 | 停止条件 |
| --- | --- | --- | --- | --- | --- |
| T29.0 固化 V2 fixture run | 历史 app generation run、Dingdang benchmark run、成功/失败 repair 样本 | 整理最小 fixture：PRD、contract、planning、codex progress、verification、preview、patch/repair record | 可复用 fixture helper | `python3 -m unittest tests.test_app_generation_canvas -v` | fixture 缺少 implementation、preview 或 repair 主路径 |
| T29.1 Canvas schema 测试 | V2 体验规范、技术方案、AC-074 到 AC-077 | 先写失败测试，覆盖 projection、business node、object、redaction 和状态枚举 | `tests/test_app_generation_canvas.py` | `python3 -m unittest tests.test_app_generation_canvas -v` | 测试失败原因不是缺实现，而是 fixture 或断言不稳定 |
| T29.2 `CanvasProjectionBuilder` | run artifacts、preview status、evaluation、adjustment events | 新增只读 builder，聚合、脱敏、路径归一、生成 warning | `CanvasProjection` dict | `python3 -m unittest tests.test_app_generation_canvas -v` | builder 需要写事实源或读取 secret |
| T29.3 六个业务节点映射 | V1 runtime nodes、`build_app_generation_nodes()` 输出 | 固定中文业务节点，维护 runtime refs、状态、摘要、对象计数、最近事件 | `business_nodes[]` | `python3 -m unittest tests.test_app_generation_canvas -v` | 默认 UI 仍必须展示英文 node id 才能理解状态 |
| T29.4 `CanvasObject` 抽取 | PRD、contract、planning、codex、verification、preview、patch、repair artifacts | 抽取业务目标、场景、能力、页面、数据、provider、预览、缺口、修复候选 | `objects[]`、`edges[]` | `python3 -m unittest tests.test_app_generation_canvas -v` | object id 不能稳定重建或对象摘要需要完整源码 |
| T29.5 对象详情构建 | `object_id`、projection、artifact/evidence refs | 校验当前 run、返回摘要、证据、可编辑字段、allowed actions、受控 preview refs | `CanvasObjectDetail` | `python3 -m unittest tests.test_dashboard -v` | 跨 run object id 无法拒绝 |
| T29.6 Canvas API | projection builder、run id、object id | 增加只读路由、404/403、path confinement 和 redaction | `/canvas`、`/canvas/objects/<object_id>` | `python3 -m unittest tests.test_dashboard -v` | API 会泄露 `.env`、API key 或未授权路径 |
| T29.7 V2.0 前端入口 | Canvas API、现有 V1 中间区 | 增加业务对象视图、对象选择状态、详情面板和 V1 降级 | 业务节点轨道 + 对象详情 | `node --check dashboard/app_generation.js` | Canvas API 失败会导致 V1 工作台不可用 |

## T30: V2.1 生成画布主视图与对象化 AgentAction

### 输入

- T29 的 `CanvasProjection` 和 `CanvasSelectionContext`。
- `docs/app_generation_agent_bridge_spec.md` 的 V2 AgentIntent / AgentAction。
- AC-078、AC-080、AC-081。

### 中间过程

1. 将中间区主视图升级为“业务节点轨道 + 对象画布 + 对象详情”。
2. 支持对象选中、相关对象跳转、对象状态筛选和证据预览。
3. AgentBridge 在 `AgentPromptContext` 中注入当前 `CanvasObject` 和 `CanvasSelectionContext`。
4. 扩展 `intent=auto`：对象选中时优先解析为 `explain_object`、`repair_generated_app`、`verify_capability`、`compare_canvas_objects` 或 `edit_business_object`。
5. 将 `repair_generated_app` 映射到现有 `patch_app` / `delegate_code_repair`。
6. 将 `suggest_object_patch` 映射到 user override 或最小业务节点重跑。
7. 在画布中展示 patch、repair、回滚和规则提升候选事件。

### 输出

- 生成画布主视图。
- 对象详情区。
- 对象化 AgentAction 渲染和确认卡。
- 版本/调优事件轨道。

### 评估与验证

```bash
python3 -m unittest tests.test_agent_bridge tests.test_dashboard -v
node --check dashboard/app_generation.js
```

验收信号：

- 用户点击能力缺口后询问“修复这个问题”，Agent 生成 `repair_generated_app`，不是泛泛解释节点。
- 用户点击业务能力后询问“验证一下”，Agent 生成 `verify_capability`。
- 修改事实源的动作必须出现确认卡。
- `patch_app` / `delegate_code_repair` 仍走 V1 受控 API 和证据落盘。

### 停止条件

- V2 action 绕过 V1 受控 API。
- Agent 可以直接写 worktree、`codex/` 或 secret 文件。
- 对象画布无法解释 action 对哪个对象生效。

### 可执行子任务

| 子任务 | 输入 | 中间过程 | 输出 | 验证命令 | 停止条件 |
| --- | --- | --- | --- | --- | --- |
| T30.1 Code Agent 业务进度卡 | `codex/coder_progress*.json`、SSE `node_progress`、`execution_progress` | 将命令/验证/stdout 事件映射为业务文案，增加 30 秒无事件提示 | implementation timeline | `python3 -m unittest tests.test_codex_executor tests.test_dashboard -v` | 进度事件可能泄露完整 prompt、源码或 secret |
| T30.2 修复进度卡 | `app_repairs/<repair_id>/progress*.json`、delegate repair status | 展示“准备候选 diff / 正在验证 / diff ready / failed” | 右侧 Code Agent 修复进度卡 | `python3 -m unittest tests.test_dashboard -v` | delegate repair 等待期间仍只有静态“执行中” |
| T30.3 `CanvasSelectionContext` 注入 | selected object、business node、surface、allowed actions | 前端 Agent 请求携带 canvas selection，后端校验 selection 属于当前 run | Agent interaction payload | `python3 -m unittest tests.test_agent_bridge tests.test_dashboard -v` | 可以引用跨 run object 或未授权 object |
| T30.4 对象化 intent 路由 | selection context、用户消息、provider | `intent=auto` 优先按对象和消息解析，失败再回退 V1 node context | `explain_object`、`repair_generated_app`、`verify_capability` 等 action | `python3 -m unittest tests.test_agent_bridge -v` | “修复这个预览错误”仍被解释成节点说明 |
| T30.5 CodeAgentExecutor 权威收口 | AgentAction、patch/delegate APIs | 复杂代码修改走 `delegate_code_repair`，简单补丁走受控 `patch_app`，均需确认和证据 | 可确认 repair action | `python3 -m unittest tests.test_agent_bridge tests.test_dashboard -v` | PI-Agent 直接生成并执行代码修改 |
| T30.6 对象画布主视图 | `business_nodes[]`、`objects[]`、`edges[]` | 渲染对象簇、状态筛选、相关对象跳转、证据入口 | 生成画布主视图 | `node --check dashboard/app_generation.js` | 右侧 Agent 被预览或画布压缩到不可用 |
| T30.7 对象化确认卡 | AgentAction、selected object、diff/verification plan | 展示问题来源、影响对象、最小修改目标、确认/取消/回滚入口 | action card | `python3 -m unittest tests.test_dashboard -v` | 确认前会写文件或确认后无验证证据 |

## T31: V2.2 ContextObject、版本回放与规则提升候选

### 输入

- T29/T30 的画布对象和对象化 AgentAction。
- `docs/app_generation_canvas_experience_spec.md` 的 `ContextObject`、版本和回放契约。
- AC-079、AC-080、AC-082。

### 中间过程

1. 新增 `ContextObject` 投影，支持业务场景、样例数据、领域知识、参考应用、用户反馈、工具能力和策略约束。
2. 支持用户在工作台登记上下文对象，并记录来源、可信度、使用节点和关联对象。
3. 将 benchmark、reference app、用户反馈和 preview 缺口转为上下文或能力缺口对象。
4. 增加版本线：初始生成、发布快照、patch、delegate repair、rollback 和 promote candidate。
5. `promote_to_generation_rule` 只创建候选记录，不自动改模板、benchmark 或 verifier。
6. 所有上下文和版本对象都必须脱敏并可从 artifacts 重建。

### 输出

- `ContextObject` 投影和登记 API。
- 版本回放 UI。
- 规则提升候选记录。
- 上下文对象与业务节点/能力对象的引用关系。

### 评估与验证

```bash
python3 -m unittest tests.test_dashboard tests.test_agent_bridge tests.test_app_generation -v
node --check dashboard/app_generation.js
```

验收信号：

- PRD 之外的场景、样例数据和用户反馈可作为对象展示。
- 上下文对象被节点使用时能看到引用。
- 版本线展示每次 patch/repair 的用户输入、diff、验证结果和预览状态。
- 规则提升必须是候选状态，不能自动修改上游生成规则。

### 停止条件

- 上下文对象可能泄露 API key 或未授权文件正文。
- 版本回放无法从 artifacts 重建。
- 规则提升绕过用户确认或直接改上游代码。

### 可执行子任务

| 子任务 | 输入 | 中间过程 | 输出 | 验证命令 | 停止条件 |
| --- | --- | --- | --- | --- | --- |
| T31.1 `ContextObject` 投影 | PRD、benchmark、reference app、用户反馈、Project Skills、工具调用 | 抽取场景、样例数据、知识、工具能力和策略约束，记录来源和可信度 | `context_objects[]` | `python3 -m unittest tests.test_app_generation_canvas tests.test_dashboard -v` | 上下文对象需要保存 API key 或未授权正文 |
| T31.2 上下文登记入口 | 用户补充信息、当前 selected object | 记录用户确认的 context，关联 used_by_nodes 和 linked_objects | context registration artifact/API | `python3 -m unittest tests.test_dashboard -v` | 用户上下文只能存在浏览器本地 |
| T31.3 版本线聚合 | publish record、patch index、repair result、rollback、adjustment events | 生成初始生成、发布、patch、repair、rollback、promotion candidate 事件 | `versions[]` | `python3 -m unittest tests.test_app_generation_canvas -v` | 版本事件无法从 artifacts 重建 |
| T31.4 规则提升候选 | 成功 patch/repair、能力缺口、验证结果、用户确认 | 创建候选记录，描述适用条件、来源和验证证据，不改上游规则 | promotion candidate object | `python3 -m unittest tests.test_dashboard tests.test_agent_bridge -v` | 候选创建会自动修改模板、benchmark 或 verifier |
| T31.5 Secret 与路径边界回归 | projection、context、Agent payload、preview/repair logs | 增加泄露样本和越界路径测试 | 安全回归测试 | `python3 -m unittest tests.test_app_generation_canvas tests.test_dashboard -v` | 任一接口暴露 `.env`、API key、完整 prompt 或越界文件 |
| T31.6 端到端验收 | Dingdang run、普通 PRD run、一次失败后修复 run | 打开 run、查看业务节点、选中缺口、Agent 修复、Code Agent diff、确认、预览验证 | V2 验收记录 | `python3 -m unittest discover -s tests -v` | 用户必须理解工程 node id 才能完成修复闭环 |

## 总体验证门

所有任务完成后运行：

```bash
python3 -m unittest discover -s tests -v
```

通过标准：

- 全部测试通过。
- 生成应用代码只位于允许路径。
- `app_generation` run artifacts 可从 PRD 追溯到生成 diff、review、verification 和 final report。
- risk events 和 blockers 不被隐藏。
- apply gate 仍需人工确认。

## 实施顺序

推荐顺序：

```text
T1 -> T2 -> T3 -> T4 -> T5 -> T6 -> T7 -> T8 -> T9 -> T10 -> T11 -> T12 -> T13 -> T14 -> T15 -> T16 -> T17 -> T18 -> T19 -> T20 -> T21 -> T22 -> T23 -> T24 -> T25 -> T26 -> T27 -> T28 -> T29 -> T30 -> T31
```

T1 到 T3 建立 artifact 和 gate 基础；T4 暴露 CLI；T5 和 T6 让 Codex 生成结果可控且可验证；T7 补 Dashboard 操作面；T8 做端到端验收；T9 用真实实现回写文档。T10 到 T13 建立工作台节点、对比、AgentBridge 和重跑基础；T14 建立三栏工作台；T15 打磨中间节点事实层的信息架构；T16 增加受控文件预览能力；T17 补列宽伸缩和预览插位规则。T18 把 PiAgentProvider 从占位升级为 `pi --mode rpc` 子进程真实接入；T19 让右侧对话走 SSE 通道并支持工具调用流；T20 提供 in-workbench PRD 上传与节点 SSE 实时观测，闭合 PRD → 节点流 → Agent 协作的完整链路；T21 建立 AGQS 评估体系、Dingdang benchmark 和 auto-research 优化闭环，为后续多 variant 对比提供可审计基准；T22 收口右侧 Agent 操作协议，让 PI-Agent 围绕当前卡片和中间产物协作，并通过可确认 AgentAction 改变生成链路；T23 对齐真实 PI RPC 事件协议，避免答案文本、thinking 和 tool call 被错误丢弃或误渲染；T24 补齐 Provider 上下文增强和 `intent=auto` 路由，让右侧 Agent 能回答节点、输入、输出和重跑类自然语言请求；T25 把 benchmark parity 变成可注入、可评分、可阻断的生成质量门禁；T26 先把短期 `patch_app` 做到可预测、可失败、可解释；T27 再把复杂应用修复收敛到唯一 `CodeAgentExecutor`，让右侧 PI-Agent 从“尝试写代码”变成“理解诉求并委托代码修复”；T28 让 Code Agent 长过程可观测；T29-T31 将 V1 工作台逐步升级为 V2 生成画布。
