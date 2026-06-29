# PRD 生成应用可观测工作台规范

## 状态

本文档定义 `PRD -> 本地应用生成` 的后续工作台能力。当前文档描述下一轮工作台 UI 与可观测能力升级规范；未明确标记为已实现的前端、API、Artifact Preview Rail、PRD 上传入口、节点 SSE / 右侧对话 SSE 通道或 PI-Agent bridge 能力，仍视为待实现能力。

工作台必须继续复用现有 `app_generation` domain、Agent Team Runtime、Dashboard API、run artifacts、Codex executor、review、verification 和人工确认 apply gate。

## 产品目标

`PRD生成应用` 工作台用于验证生成过程质量，而不只查看最终应用。用户需要看到 PRD 从输入到本地应用交付的每个节点、每个节点的输入、执行过程、输出、中间产物、Project Skills、tool calls、usage、评分、风险和重跑关系。

目标不是把 Dashboard 变成另一个自由聊天工具。中间节点区是事实源，右侧 Agent 区是协作层。Agent 可以解释、对比、建议调整和触发新 run，但不能直接覆盖旧 run artifacts。

## 目标用户

- 产品负责人：比较不同节点输出的产品质量，判断 PRD 是否被正确理解。
- AI-Team 操作者：查看节点、skills、tool calls、usage 和风险，定位生成链路中的问题。
- 工程评审者：检查 Codex/LLM 生成代码是否符合路径、安全、测试和 apply gate。
- 后续实施者：基于本文档实现 Dashboard 页面、聚合 API 和 Agent bridge。

## 三栏布局

### 左侧：任务和实验列表

左侧只展示 `domain_id=app_generation` 的 run 和 comparison group。

必须展示：

- run id、brief、状态、更新时间。
- `app_slug`。
- executor：`deterministic`、`codex` 或其他后续 LLM 执行器。
- comparison group id。
- 是否由节点重跑产生。
- 源 run：`source_run_id`。
- 重跑起点：`rerun_from_node`。

### 中间：节点与产区

中间区域展示节点流和当前节点详情。节点区是工作台事实源。

中间区域内部必须拆成两列：

- 左列：竖排节点流，按 PRD 到应用交付的先后顺序从上到下展示。
- 右列：当前节点详情、中间产物、可点击文件引用和重跑入口。

中间区域的列宽必须支持伸缩。左列节点流和右列详情区都允许在合理范围内拉伸或收缩，但左侧任务列表不得被压缩到影响可读性。右侧 Agent 协作区保持独立固定，不随预览栏打开而向左挤压。文件预览竖栏打开时，应插在中间区与右侧 Agent 之间，优先占用中间区可伸缩空间，不压缩左侧任务列表。

左列节点只展示业务友好的中文标题、业务状态和简短摘要。默认视图不得展示英文 `node_id`、executor、provider、artifact path 或技术解释。内部 `node_id` 只允许出现在调试、复制上下文或开发者详情中。

右列节点详情必须使用卡片化展示。固定卡片为：

- `Skill 路由`
- `变体与对比`
- `Project Skills`
- `输入`
- `输出`
- `Tool calls · Usage · Scores · 风险`

每个节点必须展示：

- 输入：上游 artifacts、用户 override、选中的 variant。
- 执行过程：阶段状态、日志摘要、tool calls、risk events、blockers。
- 输出：本节点 artifacts、diff、报告或预览说明。
- Project Skills：候选 skill、实际使用 skill、使用原因。
- usage：token、耗时、估算成本。
- scores：产品效果、工程可执行性、验收覆盖、风险。

`implementation` 节点的执行过程必须支持 Codex 实时进度展示，规范见 [`docs/app_generation_codex_observability_spec.md`](app_generation_codex_observability_spec.md)。执行过程卡片不得只显示“运行中”；当 Codex 已启动但尚未产出最终 diff 时，必须展示最近的 `CodexProgressEvent`，例如“启动 Code Agent”“运行命令”“修改文件”“运行验证”“生成候选 diff”。如果 30 秒没有新事件且最终状态未出现，显示“Code Agent 仍在运行，暂无新输出”。

点击任意节点后，中间区域必须切换到该节点详情，右侧 Agent 区必须同步当前 `NodeContext`。

点击任意详情卡片或中间产物文件时，右侧 Agent 区还必须同步 `AgentInteractionContext`：

- 点击 `输入` 卡片：`focus.card="inputs"`。
- 点击 `输出` 卡片：`focus.card="outputs"`。
- 点击 `Tool calls · Usage · Scores · 风险` 卡片：`focus.card="tool_usage_scores_risks"`。
- 打开文件预览：`focus.card="artifact_preview"`，并设置 `focus.artifact_ref`。
- 用户选择预览文本：设置 `focus.selected_text`，用于缩小 Agent 回答范围。

`NodeContext` 描述节点事实，`AgentInteractionContext` 描述用户当前正在讨论的对象。两者必须一起发送给右侧 Agent。

节点和详情卡片都是给业务用户、产品负责人和工程评审者阅读的内容。页面必须先展示业务解释，再在可展开详情里展示原始技术字段。所有文本容器必须设置明确的换行、截断或滚动策略，确保节点标题、摘要、路径、错误信息、JSON 片段和风险描述不溢出边框。

### 详情卡片规则

详情卡片用于解释“这个节点用了什么、做了什么、产出了什么、有什么风险”。卡片应使用和页面背景不同的浅色表面，可使用蓝色边框突出当前选中节点相关信息，但不得使用大面积强色背景。

卡片内容规则：

- `Skill 路由`：说明本节点为什么需要这些 Project Skills，哪些已使用，哪些只是推荐。
- `变体与对比`：展示 rule、Codex、LLM 或 PI-Agent 变体的质量、成本和风险差异。
- `Project Skills`：展示 skill 名称、角色、使用原因、输入和输出，不把 skill 文档当作运行结果。
- `输入`：展示本节点消费的 PRD、上游 artifact、用户调整说明和选中 variant。
- `输出`：展示本节点生成的业务产物、文件引用、报告、diff 或预览说明。
- `Tool calls · Usage · Scores · 风险`：集中展示工具调用证据、token/耗时/成本、产品效果评分和风险事件。

每张卡片必须有清晰标题和卡片详情。标题使用业务词，详情默认展示摘要；原始路径、JSON、日志和 diff 放在可展开区域或文件预览中。

### 业务友好语言

工作台默认文案必须从技术字段转换为业务友好语言。

| 技术字段 | 默认展示 |
| --- | --- |
| `prompt_tokens` | 输入 Token |
| `completion_tokens` | 输出 Token |
| `total_tokens` | 总 Token |
| `estimated_cost` | 预估成本 |
| `tool_name` | 调用工具 |
| `input_summary` | 输入摘要 |
| `output_summary` | 输出摘要 |
| `artifact_refs` | 相关产物 |
| `risk_events` | 风险事件 |
| `warning` | 需关注 |
| `blocked` | 已阻塞 |
| `unknown` | 未记录 |

业务文案不得伪造事实。没有 usage、tool call、score 或 artifact 证据时，显示 `未记录` 或 `unknown`，并保留原始状态。

### 文件预览竖栏

中间产物中的文件引用必须支持打开文件预览。文件预览以额外竖栏展示，位置位于节点流/详情区与右侧 Agent 协作区之间，但不得替代或覆盖工作台右侧 Agent 协作区。

预览竖栏职责：

- 展示当前选中文件的文件名、来源节点、大小、类型、hash 和路径摘要。
- 预览文本、代码、Markdown、JSON、YAML、HTML、CSS、JS、图片和 PDF。
- 对未知二进制或超大文件展示元信息和不可内联预览提示。
- 提供关闭预览、复制路径、在产物列表中定位的操作。

预览竖栏只读取 `runs/<run_id>/artifacts/<node>/` 下登记的产物文件（节点运行时产物）。**禁止**触达 `runs/<run_id>/worktree/`、`runs/<run_id>/generated_apps/<slug>/` 或 `runs/<run_id>/codex/`。file_preview 不修改 artifact，不进入 `user_overrides`，不触发重跑，也不改变右侧 Agent 的 Provider 状态。Agent 焦点 = `file_preview` 时改 artifact 走 `patch_artifact` action（见 [`docs/app_generation_agent_bridge_spec.md`](docs/app_generation_agent_bridge_spec.md) § patch_artifact 契约）。

### 应用预览模式

预览竖栏必须同时支持文件预览和应用预览两种模式。应用预览用于一键启动生成应用并以内嵌浏览器查看真实运行效果。

应用预览模式要求：

- 复用现有文件预览竖栏，不新增常驻第四栏。
- `file_preview` 与 `app_preview` 互斥切换；打开应用预览会替换当前文件预览内容。
- 应用预览竖栏位于中间节点区与右侧 Agent 区之间。
- 右侧 Agent 面板保持固定可用宽度，不被 iframe 压缩成窄条。
- 左侧任务列表保持最小可读宽度。
- 窄屏可降级为单列或抽屉，但桌面默认必须保持任务列表、节点区、预览竖栏、Agent 区的顺序。

应用预览 UI 至少包含：

- `发布到预览`：将 `runs/<run_id>/worktree/generated_apps/<slug>/` 拷贝到 `runs/<run_id>/generated_apps/<slug>/` 作为稳定快照（见 [`docs/app_preview_runner_spec.md`](docs/app_preview_runner_spec.md) § 应用发布契约）。
- `启动预览`：调用 preview start API；未发布时此按钮置灰，tooltip 提示「请先点发布到预览」。
- `停止`：调用 preview stop API。
- `刷新`：刷新 iframe 或重新读取 preview status。
- `外部打开`：用新标签页打开 preview URL。
- iframe：加载 `http://127.0.0.1:<port>`，`sandbox="allow-scripts allow-forms allow-same-origin"`。
- 状态摘要（状态机详见下方）。
- 端口、健康检查信息、启动时间、日志路径、发布时间、historical app_patches 计数。

应用预览状态机：

```
未生成 (implementation 节点未完成)
   ↓ implementation 完成
未发布 (worktree 有应用，generated_apps/<slug>/ 不存在或 app_publish.json 缺失)
   ↓ 用户点「发布到预览」
已发布·已停止 (快照存在，server.js 进程不在)
   ↓ 用户点「启动预览」
启动中 → 运行 (server.js 健康检查通过) → 降级 (健康检查失败但进程在) / 停止 / 失败
   ↓ rerun implementation 节点会回到「未发布」状态，旧 app_patches 标记 invalidated_by_rerun=true
```

启动失败时，UI 必须显示可行动错误，例如：

- 未发布：返回 412 `app_not_published`，提示「请先点发布到预览」。
- 缺少发布记录：返回 412 `missing_publish_record`，提示「重新发布」。
- 本机环境不允许绑定 localhost：提示可在用户终端手动运行 preview 命令。
- 端口附近无可用端口：提示换端口或停止旧预览。
- 健康检查超时：展示 `preview/preview.log` 可预览入口。

打开应用预览后，右侧 Agent 的 `AgentInteractionContext` 必须更新：

```json
{
  "focus": {
    "card": "app_preview",
    "view_mode": "app_preview",
    "artifact_ref": "",
    "selected_text": ""
  }
}
```

预览 URL、状态、发布时间、source_commit、`app_patches_count` 等信息从 NodeContext.preview_status / preview_url / preview_health 派生（见 [`docs/app_generation_node_context_contract.md`](docs/app_generation_node_context_contract.md) § Preview Status 扩展），不在 focus 中重复。Agent 焦点 = `app_preview` 时改应用走 `patch_app` action（见 [`docs/app_generation_agent_bridge_spec.md`](docs/app_generation_agent_bridge_spec.md) § patch_app 契约）。

关闭预览竖栏只隐藏 iframe，不停止 preview 进程。停止 preview 必须是显式动作，避免用户关闭文件栏时误杀正在验证的应用。

### 右侧：Agent 协作区

右侧 Agent 区默认 Provider 是 `codex`，可切换到 `pi_agent` 或 `llm`。未配置的 Provider 必须显示清晰不可用状态，不影响默认 Codex。

右侧 Agent 可以执行：

- 解释当前节点、当前详情卡片或当前 artifact。
- 读取并解释当前中间产物。
- 对比 rule 与 Codex/LLM 输出。
- 对比输入、输出、variant 或 artifact 版本。
- 直接 patch 当前 artifact（落 `artifact_patches/` 证据，见 [`docs/app_generation_agent_bridge_spec.md`](docs/app_generation_agent_bridge_spec.md) § patch_artifact 契约）。
- 直接 patch 已发布应用（落 `app_patches/` 证据，见同文档 § patch_app 契约）。
- 建议修改节点输入或 override。
- 选择某个 variant 作为下游输入。
- 从当前节点触发重跑。
- 向用户提出澄清问题。

当右侧 Agent 触发 `delegate_code_repair` 时，右侧 Agent 区必须展示「Code Agent 修复进度」卡片。该卡片从 `app_repairs/<repair_id>/progress_status.json` 和 `progress.jsonl` 读取状态，展示已接收修复请求、已复制发布快照、已启动 Codex、正在执行、正在验证、候选 diff 已生成或失败原因。该卡片只展示摘要和受控日志引用，不展示完整 prompt、源码、stdout 或 secret。

Agent 输出只能成为可确认动作或可追溯 patch；任何对 artifact 或已发布应用的修改必须先落 patch 文件再覆写，禁止无证据原地覆盖。禁止直接修改 `runs/<run_id>/codex/` 原始 Codex 输出。

右侧 Agent 的请求必须包含：

- `NodeContext`：当前节点事实。
- `AgentInteractionContext`：当前 UI 焦点、选中 artifact、选中文本和允许操作。
- 用户消息。
- Provider 和 intent。

默认 `intent=auto`。AgentBridge 根据用户消息和 `focus` 判断是解释、读取 artifact、建议修改、建议重跑还是澄清。

右侧 Agent 返回两类结果：

- 自然语言消息：用于解释和对话。
- `AgentAction[]`：可确认动作，例如 `read_artifact`、`patch_artifact`、`patch_app`、`suggest_input_patch`、`rerun_from_node`、`compare_variants`。

任何改变 artifact、已发布应用、节点输入、variant、重跑或文件状态的动作都必须进入待确认区。未确认前不得修改 run artifacts 或已发布应用。`patch_artifact` 与 `patch_app` 在用户确认后将先写入对应 `artifact_patches/` 或 `app_patches/` 证据，再覆写目标文件。

### 右侧 Agent 理解能力

右侧 Agent 必须能理解用户围绕当前节点的常见业务问题，而不是只解释节点摘要。`intent=auto` 下的最低行为要求如下：

| 用户问题 | 当前 focus | 期望行为 |
| --- | --- | --- |
| “这个节点是干啥的？” | 任意 | 解释节点业务目标、上游输入、下游输出和风险，不只复述内部 `node_id` |
| “输入是什么？” | `node_summary` 或 `inputs` | 列出当前节点输入 artifact 的业务名称、摘要、状态和路径摘要 |
| “输出是什么？” | `node_summary` 或 `outputs` | 列出当前节点输出 artifact 的业务名称、摘要、状态和可预览入口 |
| “读一下这个产物” | `artifact_preview` | 返回 `read_artifact`，读取结果作为右侧 tool evidence |
| “这段是什么意思？” | `artifact_preview` + `selected_text` | 只围绕选中文本解释，并说明它属于哪个 artifact |
| “重新跑这个节点” | 任意 | 返回待确认 `rerun_from_node`，创建新 run，不修改旧 run |
| “基于这个文件重新生成” | `artifact_preview` | 返回待确认 `patch_artifact` 或 `rerun_from_node` |
| “对比 rule 和 Codex” | `variants` 或节点 | 返回 `compare_variants`，同时展示质量、风险和 usage |

AgentBridge 必须先解析 `resolved_intent`，再调用 Provider。Provider 的自然语言回答可以更聪明，但不得改变已解析的权限和确认边界。

PI-Agent 的 prompt 必须包含业务节点标题、节点摘要、输入列表、输出列表、当前卡片、当前 artifact、选中文本、usage、scores、risks 和 allowed operations。不得只传“输入数量/输出数量/风险数量”，否则用户询问输入输出时会继续答非所问。

### 右侧 Agent 增量优化生成应用

右侧 Agent 用于协作优化生成过程，但默认必须是增量优化，而不是重写完整 PRD 或重构整个生成流程。

当用户在应用预览中发现问题，例如“缺少生图按钮”“需要模型选择”“API Key 怎么配”“这个预览哪里不对”，Agent 必须：

- 先基于当前 `app_preview` focus、当前节点、当前 artifact、能力扫描结果和用户消息定位具体缺口。
- 生成最小必要修改建议，不改写无关流程。
- 明确保留已通过能力，例如四阶段工作流、产品图上传、方案单选、Prompt 生成、localStorage 状态和已通过测试。
- 把建议转成待确认 `AgentAction`：
  - 若用户在 `app_preview` focus 下要求改已发布应用 UI/功能，返回 `patch_app` action（直接修改 `runs/<run_id>/generated_apps/<slug>/`，落 `app_patches/` 证据）。
  - 若用户在 `file_preview` focus 下要求改某节点产物，返回 `patch_artifact` action（直接修改 `runs/<run_id>/artifacts/<node>/<file>`，落 `artifact_patches/` 证据）。
  - 若缺口只在实现层但需要整个节点重新生成（例如整体架构调整），从 `implementation` 节点 `rerun_from_node`。
  - 只有当缺口来自 PRD 表述不清、标准化 PRD 漏需求或应用契约缺能力时，才建议回到 `prd_input`、`prd_normalization` 或 `context_contract`。
- 禁止直接覆写 `runs/<run_id>/codex/` 原始 Codex 输出。
- 禁止直接覆写 `runs/<run_id>/worktree/` 源码（worktree 只能由上游节点重跑刷新）。

Agent 生成的增量修改示例：

```text
基于当前预览和能力扫描，直接在已发布应用中补齐图片生成能力：

action: patch_app
target_path: generated_apps/<slug>/public/app.js
patch_diff: |
  新增 callImageModel(prompt) 函数，调用 /api/images/generate
  新增模型选择 UI 逻辑和 provider 配置状态查询

需依次修改的其他文件（每次对应一次 patch_app action）：
  - generated_apps/<slug>/public/index.html: 模型选择 select + 生图按钮
  - generated_apps/<slug>/server.js: GET /api/health + POST /api/images/generate
  - generated_apps/<slug>/.env.example: OPENROUTER_API_KEY 占位
  - generated_apps/<slug>/README.md: 服务端 API Key 配置说明段落

保留现有四阶段工作流、产品图上传、方案单选、Prompt 生成和 localStorage 状态。
API Key 只从服务端 process.env 读取，不进入前端和 localStorage。

patch_app 支持 PatchSet：Agent 可以一次返回多个文件级 patch；框架必须先完成全部 dry-run 和路径校验，再写任何文件。任一 patch 校验或写入失败时，目标文件保持原样；全部成功后，每个目标文件写入一条 `app_patches/<ts>__<file>.diff`，并用同一个 patch_set_id 串联。
```

### 右侧 Agent 调优 UX

应用预览中的高频调整必须以“可确认动作卡片”呈现，而不是只给自然语言建议。动作卡片至少包含：

- 用户反馈来源：预览错误、用户描述、能力扫描、日志摘要或 artifact 引用。
- Agent 判断：归一化 `AgentIntent`，例如 `diagnose_app_bug` 或 `patch_app`。
- PatchSet dry-run diff：目标文件、修改摘要、风险、保留能力清单和预计验证命令。
- 确认入口：用户确认后才执行 apply；未确认不得写文件或重启预览。
- 执行结果：patch 证据路径、验证结果、预览重启状态和 rollback 入口。

中间节点流必须增加“应用调优”事件轨道。每次用户通过右侧 Agent 修复已发布应用，都产生一条 `AdjustmentEvent`，点击后在节点详情区展示：用户原始输入、Agent 解析意图、PatchSet diff、dry-run / apply / verify 结果、预览状态、是否可回滚、是否建议提升为生成规则。

高频应用调整不是新 run，不修改 `worktree/`，也不修改 `codex/` 原始输出。它是在当前已发布快照 `runs/<run_id>/generated_apps/<slug>/` 上的可观察增量变更。只有用户明确选择 `rerun_from_node` 或“提升为生成规则”后，才进入上游生成链路。

成功 patch 可以提示「提升为生成规则」，但必须由用户确认后才创建 `promote_patch_to_generation_rule` 动作。该动作只记录候选和证据，不自动修改 benchmark、模板、runtime 或 Codex prompt。

禁止的 Agent 行为：

- 把“补一个按钮”扩展成“重写整个应用”。
- 把“API Key 配置”改成前端输入并持久化到 localStorage。
- 删除已生成且已通过的流程节点。
- 原地覆盖 artifact 或已发布应用而不落 patch 证据。
- 修改 `codex/` 原始输出或 `worktree/` 源码。
- 跳过用户确认直接调用重跑或 apply。

### PI-Agent 分工边界

`PiAgentProvider` 是工作台到 PI Agent runtime 的薄桥接层。它负责启动 PI、注入模型配置、传递 `NodeContext` / `AgentInteractionContext`、转译 JSONL/SSE、脱敏、归一化 usage、展示 tool calls 和归一化动作。

底层 PI Agent 负责推理、对话和工具决策。PI Agent 的工具调用结果必须作为右侧 tool evidence 展示；除非被转换为可确认 `AgentAction` 并由用户确认，否则不得写入节点事实层。

v1 推荐 read / inspect / suggest-first。若启用 PI 的 write/edit/bash 工具，UI 必须显式展示工具副作用、路径、命令、diff 或输出摘要，并标记为不属于 run artifacts 的右侧 Agent 证据。

### Agent 可操作对象

| 对象 | Agent 可做 | 禁止 |
| --- | --- | --- |
| 节点 | 解释、对比、建议重跑、提出澄清问题 | 直接改节点状态 |
| 输入 | 解释、建议 patch、生成 override instruction | 覆盖旧输入 artifact 而不落证据 |
| 输出 / 节点产物 | 解释、对比、`patch_artifact` 直改并落 `artifact_patches/` 证据、建议重生成 | 原地覆盖文件而不落证据 |
| 已发布应用 (`generated_apps/<slug>/`) | 在 `app_preview` focus 下 `patch_app` 直改并落 `app_patches/` 证据 | 改未发布的 worktree 或 codex/ 原始输出 |
| worktree (`runs/<run_id>/worktree/`) | 只读引用 | Agent 不得直接修改，只能由上游节点重跑刷新 |
| codex 原始输出 (`runs/<run_id>/codex/`) | 只读引用 | 任何修改一律禁止 |
| 中间产物预览 | 预览、读取、解释、诊断、建议重跑 | 在没有 patch 证据的情况下覆盖 |
| Tool calls / Usage / Scores / 风险 | 解释、诊断、指出异常 | 伪造 usage 或隐藏风险 |

## 固定节点

v1 工作台使用固定节点列表。

| 用户可见标题 | 内部 node_id | 目标 | 主要输入 | 主要输出 |
| --- | --- | --- | --- | --- |
| Skill 路由 | `skill_routing` | 选择本次生成链路的 Project Skills | PRD、domain、当前 artifacts | skill 应用计划 |
| PRD 输入 | `prd_input` | 固化 PRD 和校验 `app_slug` | `prd_text`、`prd_file`、`app_slug` | `input_prd.md` |
| PRD 标准化 | `prd_normalization` | 标准化 PRD | `input_prd.md` | `requirements/normalized_prd.md` |
| 应用契约 | `context_contract` | 形成上下文与应用契约 | 标准化 PRD、domain defaults | `context_pack.md`、`app_contract.json` |
| 规划与验收 | `planning_tdd` | 生成验收、coverage 和 TDD 计划 | PRD、contract、context | `acceptance_criteria.md`、`planning/acceptance_coverage_matrix.json`、`planning/tdd_plan.json` |
| 应用实现 | `implementation` | 生成应用代码 | PRD、contract、allowed paths、verification commands | `codex/implementation_trace.json`、`codex/diff.patch`、`generated_apps/<app_slug>/...` |
| 质量评审 | `review_quality` | 评审实现质量 | diff、changed files、acceptance criteria | `review_report.md`、质量评审结果 |
| 验证结果 | `verification` | 验证生成应用 | worktree、verification commands | `test_report.md`、`codex/verification_record.json` |
| 预览交付 | `preview_delivery` | 形成预览和交付结论 | verification、contract、reports | `preview_instructions.md`、`final_report.md` |

用户可见标题是默认 UI 文案。内部 `node_id` 用于 API、run artifacts、NodeContext 和测试断言，不得替代用户可见标题。

## Skill 映射

工作台必须能展示每个节点可应用的 Project Skills。v1 映射如下。

| 节点 | 默认 Skill | Companion |
| --- | --- | --- |
| `skill_routing` | `using_agent_skills` | 无 |
| `prd_input` | `spec_driven_development` | 无 |
| `prd_normalization` | `spec_driven_development` | `context_engineering` |
| `context_contract` | `context_engineering` | 无 |
| `planning_tdd` | `planning_and_task_breakdown` | `test_driven_development` |
| `implementation` | `incremental_implementation` | 无 |
| `review_quality` | `code_review_and_quality` | `ai_coding_quality_review` |
| `verification` | `test_driven_development` | `debugging_and_error_recovery` when failed |
| `preview_delivery` | `code_review_and_quality` | `run_retrospective` future optional |

Skill 是方法层，不替代 run artifacts。工作台必须显示 skill 的来源、输入、输出和使用理由，不得把 skill 文档当成运行结果。

## 节点状态

节点状态必须从 artifacts 和 run record 推导。

- `not_started`：关键输入不存在。
- `ready`：输入已存在，可以执行。
- `running`：对应 agent 或 process 正在执行。
- `completed`：关键输出已存在且无阻塞。
- `warning`：输出存在，但有 warning 或非阻塞风险。
- `blocked`：缺少必要 artifact、gate failed、risk event 或 provider 不可用。
- `unknown`：无法从现有 artifacts 判断。

不得因为页面能渲染就把节点显示为 completed。

## Tool Calls 观测

工作台必须展示已记录的工具调用和执行证据。

优先来源：

- `events.jsonl`
- `task_journal.jsonl`
- `codex/implementation_trace.json`
- `codex/slices/*/slice_trace.json`
- `codex/verification_record.json`
- `team_run_record.json`
- `code_run_record.json`

如果某个节点没有工具调用记录，显示 `未记录`，不得伪造 tool call。

## PRD 上传与自动节点流

工作台必须在中间区域内联（in-workbench）入口让用户直接上传 PRD 并启动一次完整节点流，不跳出页面、不依赖 CLI。

### 上传入口

- 触发位置：中间节点区顶部的「新建 run」面板。
- 输入字段：
  - `prd_text`：可粘贴的纯文本 PRD（任意大小，无前端硬限制）。
  - `prd_file`：可拖入的 `.md` / `.txt` 文件，前端读为 UTF-8 文本注入 `prd_text`。
  - `app_slug`：可选，留空时由 `prd_normalization` 节点生成。
  - `executor`：用户每次自选，候选来自 `dashboard` 暴露的执行器列表（v1 至少 `deterministic` 与 `codex`）。
  - `comparison_group_id`：可选，留空时新建。
- 元数据流：用户输入直接进入新建的 `team_run_record.json`，dashboard 不在上传阶段做任何标准化或截断（标准化交由 `prd_normalization` 节点完成）。

### 上传 API

```text
POST /api/app-generation/runs
Content-Type: application/json

{
  "prd_text": "...",
  "prd_filename": "feature_x.md",
  "executor": "deterministic",
  "app_slug": "feature_x",
  "comparison_group_id": null
}
```

响应：

```json
{
  "run_id": "app_generation-20260625-001",
  "runs_dir": "runs/app_generation-20260625-001",
  "events_stream": "/api/app-generation/runs/app_generation-20260625-001/events/stream"
}
```

dashboard 接到请求后：

1. 创建 `runs/<run_id>/`，写入 `team_run_record.json`、`input_prd.md`。
2. 在后台线程启动 `runtime` 跑完 6 个固定节点（按 `## 固定节点` 表）。
3. 同步返回 `run_id` + `events_stream` URL，前端立即订阅 SSE。

### 节点 SSE 通道

```text
GET /api/app-generation/runs/<run_id>/events/stream
Accept: text/event-stream
```

事实源永远是 `runs/<run_id>/events.jsonl` + `runs/<run_id>/team_run_record.json`，dashboard 是 tail + 广播角色。

事件类型（每条 SSE message 形如 `data: <json>\n\n`）：

| event | payload | 触发时机 |
| --- | --- | --- |
| `snapshot` | `{run_id, run_record, nodes: [{node_id, status, updated_at}]}` | 订阅时首帧；客户端断线重连后立即重发当前快照 |
| `node_state` | `{node_id, status, started_at?, ended_at?, summary?, artifact_refs?, usage?}` | 任一节点状态变化（`not_started → ready → running → completed/warning/blocked`） |
| `agent_event` | `{node_id, event_type, payload}` | runtime 在节点内部写入 `events.jsonl` 的关键事件（tool call、risk event、score 更新等） |
| `run_finished` | `{run_id, terminal_status, ended_at}` | 所有节点终态后由 dashboard 收尾发出 |

心跳：dashboard 每 15s 发送一条 `:heartbeat` 注释行，前端用于检测连接存活。

观测粒度：`node_level`，每个固定节点至少产出 `running` 与 `completed/warning/blocked` 各 1 条 `node_state`；节点内部细粒度变化通过 `agent_event` 透传，前端可选择是否展开。

事件来源边界：节点 SSE 流的所有事件必须可由 `runs/<run_id>/` 重放复现；任何无法从文件系统重放的运行时副作用都不允许出现在该流中（PI 右侧对话产生的事件走独立通道，见下一节）。

### 断线重连

- 前端使用 `EventSource`；连接断开时 `onerror` 自动 5s 内重连。
- 重连成功后 dashboard 重发一次 `snapshot`，前端用该快照覆盖本地节点状态；增量 `node_state` 不依赖客户端持久化游标。
- `run_finished` 收到后前端关闭订阅。

## 右侧对话 SSE

右侧 Agent 协作区使用与节点流 **完全独立** 的 SSE 通道，用于把 Provider 的实时事件（特别是 `pi_agent` 的工具调用流）透传给前端。

### 通道分工

| 通道 | URL | 事实源 | Provider |
| --- | --- | --- | --- |
| 节点流 | `GET /api/app-generation/runs/<run_id>/events/stream` | `runs/<id>/events.jsonl` | 不涉及 Provider |
| 右侧对话流 | `POST /api/app-generation/agent/stream` | Provider stream（CodexProvider 单事件，PiAgentProvider 子进程 JSONL） | `codex` / `pi_agent` / `llm` |

两条通道互不依赖：节点 SSE 不因右侧 Provider 状态变化而中断；右侧对话 SSE 不写入 `runs/<id>/`，不修改任何 artifact。

### 对话 API

非流式（保留兼容，CodexProvider 主用）：

```text
POST /api/app-generation/agent/message
{provider, mode, message, node_context_snapshot}
→ {provider, status, message, actions, tool_calls, usage, risk_events}
```

流式（PiAgentProvider 主用，CodexProvider 也支持折叠为单事件）：

```text
POST /api/app-generation/agent/stream
{provider, mode, message, node_context_snapshot}
→ text/event-stream
```

事件契约见 `docs/app_generation_agent_bridge_spec.md` 「流式增强」节，类型集合：

- `message_delta`
- `tool_call`
- `tool_result`
- `auto_retry_start`
- `agent_end`（含最终 `usage` 与 `actions`）
- `upstream_error`
- `extension_ui_request`（v1 自动取消）

### 断线重连

- 前端使用 `fetch + ReadableStream` 读取（POST + SSE 风格）；断开后由用户决定是否重新发起请求，**不自动重连**（流式对话不可幂等重放）。
- 后端在 stream 关闭前若没有发出 `agent_end`，必须补发 `upstream_error{phase:"stream_closed"}`，前端据此把当前回合气泡标记为「已中断」。

### Provider 切换

- 切换 Provider 不影响当前 run 的节点流。
- 切换 Provider 立即更新右侧 `providerStatuses`，按 `docs/app_generation_agent_bridge_spec.md` 的 `status(repo_root)` 判定显示 `ready / not_configured / unavailable / error`。
- `pi_agent` 不可用时，右侧降级到非流式 `send_message`（用 codex 完成），前端在工具卡区域显示「PI 不可用，已回落到 codex」。

## 重跑原则

从任意节点重跑时必须创建新 run，不覆盖旧 run。

新 run 必须记录：

- `source_run_id`
- `rerun_from_node`
- `selected_variant`
- `override_instructions`
- `comparison_group_id`

v1 重跑语义是“从指定节点的调整说明开始，生成一个完整新 run”。旧 run 作为对照和审计来源保留。

## V2 生成画布关系

V2 生成画布规范见 [`docs/app_generation_canvas_experience_spec.md`](app_generation_canvas_experience_spec.md)。V2 不废弃本文档定义的 V1 工作台，而是在 V1 的节点事实层、Artifact Preview Rail、应用预览、AgentBridge 和 `NodeContext` 之上增加业务对象投影。

V1 与 V2 的关系：

- V1 节点流仍是运行事实的直接呈现。
- V2 业务节点轨道是 V1 节点流的业务语言投影。
- V1 详情卡片仍提供输入、输出、工具、usage、风险和 evidence。
- V2 对象画布把这些 evidence 投影为 `CanvasObject`，例如业务目标、场景、能力、页面流程、数据对象、provider 配置、能力缺口、预览会话和修复候选。
- V2 右侧 Agent 默认围绕当前 `CanvasObject` 协作，而不是只围绕当前 `node_id`。

V2 默认业务节点必须固定为：

1. 理解业务目标
2. 编译业务规格
3. 规划应用结构
4. 生成应用原型
5. 验证业务能力
6. 输出可交付版本

V2 生成画布不得引入新的事实源。`CanvasProjection` 必须能从 run artifacts、`NodeContext`、preview status、evaluation artifacts 和 `adjustment_events` 重建。浏览器本地状态只能保存 UI 偏好，例如选中对象、折叠状态和画布缩放，不得作为业务事实。

V2 实施初期允许在现有中间区增加“业务对象”tab；完整画布化应作为后续阶段实现，避免一次性推翻 V1 已有可观测链路。

## 安全边界

- Agent 不直接写旧 artifact。
- Agent 不绕过 review、verification 或 apply gate。
- PI-Agent 未配置时不得阻塞 Codex 默认路径。
- 任何 Provider 都不得持久化 secret。
- usage 缺失时显示 `unknown`，不得估算成真实 token。
- 中间节点区是事实源，右侧 Agent 区是协作层。
