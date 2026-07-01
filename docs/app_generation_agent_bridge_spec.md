# PRD 生成应用 Agent Bridge 规范

## 状态

本文档定义 `PRD生成应用` 工作台右侧 Agent 区的 Provider 与 Bridge 契约。

当前实现进度：

- Provider 抽象与 `CodexProvider` 已实现，并通过 `tests.test_agent_bridge` 与 dashboard agent 路由测试。
- `PiAgentProvider` 占位实现已上线（未配置时返回 `not_configured`），真实接入按本文档 `### pi_agent` 节的「子进程 RPC + JSONL stdio」范式落地。
- 右侧对话 SSE 通道与节点 SSE 通道为 spec-first 待实现，由 `docs/app_generation_workbench_spec.md` 与 `docs/app_generation_implementation_task_plan.md` 跟踪。

默认 Provider 是 `codex`。`pi_agent` 是可切换 Provider，统一通过 `AgentBridge` 接入。`llm` 保留为未来通用 OpenAI-compatible Provider 占位，本轮不实现。

## 设计原则

- 中间节点区是事实源，右侧 Agent 区是协作层。
- Agent 接收 `NodeContext`，返回消息和可确认动作。
- Agent 不直接覆盖旧 artifact。
- Agent 对生成应用的修改建议必须是增量优化，不得默认改写完整 PRD、重构全流程或替换所有节点产物。
- Provider 切换不改变中间节点事实，只改变右侧响应来源和可用能力。
- PI-Agent 未配置时必须清晰显示不可用，不影响 Codex 默认路径。
- `PiAgentProvider` 是薄适配层，不是第二套 Agent runtime。它只负责启动、上下文注入、事件转译、脱敏、usage 归一、tool call 可观测和动作归一化；推理、对话和工具决策由底层 PI Agent 完成。
- 右侧 Agent 的默认工作不只是解释节点。它必须能围绕当前节点、当前详情卡片、当前 artifact 和用户输入，执行解释、读取、对比、建议调整、建议重跑和澄清。

## Provider

### `codex`

默认 Provider。用于围绕当前节点解释、对比、建议调整、生成重跑说明，也可以在实现节点触发 Codex/LLM 代码生成 run。

要求：

- 使用现有 Codex executor 配置和 redaction 规则。
- 上下文来自 `NodeContext` 和 run artifacts，不来自历史聊天。
- 输出必须转换为 `AgentAction`。

### `pi_agent`

接入用户机器上已安装的 `pi` CLI（参考实现：[pi-mono](https://github.com/earendil-works/pi-mono)）。Dashboard 通过子进程 + JSONL stdio 调用 pi，不再通过 HTTP gateway 转发。

#### Wire protocol

- 启动方式：`subprocess.Popen([pi_bin, "--mode", "rpc", *extra_args], stdin=PIPE, stdout=PIPE, stderr=PIPE, cwd=repo_root, env=parent_env)`，长驻单例子进程。
- stdin 写入 JSONL，例如 prompt 命令：

```json
{"type": "prompt", "id": "uuid", "message": "...", "streamingBehavior": "followUp"}
```

- 其他控制命令：`{"type": "abort"}`、`{"type": "new_session"}`、`{"type": "switch_session", "sessionPath": "..."}`、`{"type": "set_model", "provider": "...", "modelId": "..."}`、`{"type": "set_thinking_level", "level": "low|medium|high"}`、`{"type": "get_state"}`、`{"type": "get_session_stats"}`。
- stdout 流式输出 JSONL，三类顶层包：
  - `{"type": "response", "id": "...", "success": true|false, ...}`：与同 id 的 prompt 命令一一匹配的最终回执。
  - `{"type": "agent_event", ...}` 形式的实时事件，子类型见下文「流式事件契约」。
  - `{"type": "extension_ui_request", ...}`：pi 反向请求 UI 兜底交互（v1 不实现，原样丢弃并记录 risk_event）。
- stderr 收集为 risk 信号；非 0 退出码触发 `provider_status=error`。
- 参考实现：`PI_AGENT/db-archaeologist-pi-spec-pack/web/lib/rpc-bridge.mjs`。

#### 启动参数与默认值

| 参数 | 来源 | 默认 | 说明 |
| --- | --- | --- | --- |
| `--mode rpc` | 固定 | 必填 | 锁定 JSONL stdio 模式 |
| `--model <provider/id>` | env `PI_DEFAULT_MODEL` | 空 → 沿用 pi 内置默认 | 例如 `aicodemirror/gpt-5.5`、`anthropic/claude-sonnet-4.5` |
| `--thinking <level>` | env `PI_DEFAULT_THINKING` | 空 → off | `off | minimal | low | medium | high | xhigh` |
| `--exclude-tools <names>` | env `PI_EXCLUDE_TOOLS` | 空 | 默认放开 pi 内置 read/write/edit/bash 工具；如需收紧再用此项 |

未来如需注册 app_generation 业务工具，可在仓库根加 `.pi/extensions/*.extension.ts` + `.pi/skills/*/SKILL.md`，pi 会自动发现，无需改 Dashboard。

#### 凭据来源

Dashboard 不持有 pi 凭据。pi 子进程从父进程 env 继承，再自行解析以下任一：

- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `AICODEMIRROR_API_KEY`
- `OPENROUTER_API_KEY`
- `DEEPSEEK_API_KEY`
- 或落地在 `~/.pi/agent/auth.json` 的 OAuth 凭据（`pi /login` 产物）

仓库 `.env` 若存在并被 dashboard 加载（沿用 codex executor 的 `_read_env_file_values` + 大写归一），其大写后的键值会注入子进程 env；不在 dashboard 日志、响应、SSE 事件中回显。

#### Provider 配置 env

| 键 | 作用 | 默认 |
| --- | --- | --- |
| `PI_BIN` | pi 可执行路径 | `pi`（从 PATH 解析） |
| `PI_DEFAULT_MODEL` | 启动时的默认 model | 空 |
| `PI_DEFAULT_THINKING` | 启动时的默认 thinking level | 空 |
| `PI_RPC_TIMEOUT_SEC` | 单条 prompt 的 response 超时 | `60` |
| `PI_RPC_BOOT_TIMEOUT_SEC` | 子进程首次 ready 超时 | `15` |
| `PI_OFFLINE` | 跳过 pi 启动期版本检查 | 未设 |

#### `status(repo_root)` 判定

按以下顺序短路返回：

1. `shutil.which(PI_BIN)` 命中 → `ready`，`message="pi available at {abs_path}"`，`capabilities=["chat", "tool_calls", "stream"]`。
2. 未命中 → `not_configured`，`message="PI-Agent (pi) binary not found on PATH; install via npm i -g @earendil-works/pi-coding-agent"`，`capabilities=[]`。
3. 子进程已启动但最后一次 `--mode rpc` boot 超时或异常退出 → `error`，`message` 携带 redacted stderr 摘要。

不再检查 `PI_AGENT_BASE_URL`/`PI_AGENT_API_KEY`，pi 自管 LLM 鉴权。

#### 流式事件契约

dashboard 把 pi 子进程 stdout 的 `agent_event` 包归一化后透传给前端 SSE。归一化后的事件类型与字段如下，前端按这套契约渲染：

| 事件 | pi 原始 type | 关键字段 | UI 行为 |
| --- | --- | --- | --- |
| `message_delta` | `message_delta` / 文本增量 | `{text}` | 追加到当前 assistant 气泡 |
| `tool_call` | `tool_call` / `tool_use` | `{tool_call_id, name, input}` | 渲染一张工具卡（折叠原始 input） |
| `tool_result` | `tool_result` | `{tool_call_id, output, is_error}` | 在对应工具卡补结果或错误 |
| `agent_end` | `agent_end` / `message_end` / `response{success:true}` | `{stop_reason, usage, willRetry}` | 关闭当前回合气泡，写入 usage |
| `auto_retry_start` | `auto_retry_start` | `{attempt, maxAttempts, delayMs, errorMessage}` | 显示「正在重试 i/n」 |
| `upstream_error` | `agent_end{willRetry:false, error}` 或 `message_end{stopReason:"error"}` | `{phase, errorMessage, hint}` | 错误吐司，hint 由 dashboard 根据 errorMessage 归类（`network_unreachable | auth_invalid | rate_limited | upstream_timeout | upstream_unknown`） |
| `extension_ui_request` | `extension_ui_request` | `{request_id, prompt}` | v1 自动应答取消，记 risk_event |

`response{success:true}` 如果没有配套 `agent_end` / `message_end`，dashboard 必须合成为 `agent_end{stop_reason:"response_success"}`。`response{success:false}` 归一化为 `upstream_error{phase:"response_error"}`。

终态规则：

- `agent_end` 是正常终态。
- 合成的 `agent_end{stop_reason:"response_success"}` 也是正常终态。
- `upstream_error` 是错误终态。
- 外层包装看到 `agent_end` 或 `upstream_error` 后不得再次追加 `stream_closed`。
- `stream_closed` 只表示没有 `agent_end`、没有成功 `response`，且 stdout / SSE 确实异常结束。

#### Provider 边界

- `pi_agent` 仅作为右侧 Agent 协作 Provider。
- 不替代 codex executor，不进入 runtime 节点编排，不写 `runs/<id>/` 任何 artifact。
- pi 子进程的内置工具调用只作为右侧对话 tool evidence 展示，不自动成为节点事实源。
- v1 推荐以 read / inspect / suggest 为主。若启用 write/edit/bash，前端必须展示路径、命令、diff 或输出摘要，并标记为右侧 Agent 工具副作用；这些副作用不写入 `runs/<id>/`，不改变节点状态，不绕过用户确认。
- 任何会影响生成链路的变化都必须转换为 `AgentAction`，由用户确认后走 rerun、override 或 apply gate。

#### 扩展点

`PiAgentProvider` 构造函数允许注入：

- `subprocess_launcher(cmd, env, cwd) -> Popen`：测试时替换为 in-process fake，输入预设 JSONL 序列。
- `event_parser(jsonl_line) -> Event | None`：未来 pi 协议演进时归一化层只改这里，不影响 Bridge 抽象。
- `redactor(text) -> text`：复用 codex 的 `_redact_text`，确保 SSE 事件、status message、stderr 摘要里没有 api key 明文。

### `llm`

通用 LLM Provider，用于后续接 OpenAI-compatible endpoint 或其他模型服务。

要求：

- 输入仍为 `NodeContext`。
- 输出仍为 `AgentAction`。
- usage 必须来自真实 provider response，缺失时显示 `unknown`。

## AgentBridge 接口

```text
AgentBridge
  provider_id: string
  status(config) -> AgentProviderStatus
  send_message(NodeContext, AgentMessage) -> AgentResponse              # 非流式，CodexProvider 主用
  stream_message(NodeContext, AgentMessage) -> Iterator[StreamEvent]    # 流式，PiAgentProvider 主用
  normalize_tool_calls(raw_events) -> ToolCall[]
  normalize_usage(raw_response) -> Usage
```

约束：

- 任一 Provider 至少实现 `send_message` 与 `stream_message` 之一；未实现的方法以默认实现降级（`stream_message` 默认实现把 `send_message` 包成单事件流，`send_message` 默认实现把 `stream_message` 折叠为最终 `AgentResponse`）。
- `status` 不发起任何远端调用，只做本地探测（PATH 命中、env 检查、子进程健康）。
- `stream_message` 产出的 `StreamEvent` 字段与 `### pi_agent` 节「流式事件契约」一致；CodexProvider 走非流式时由 dashboard 把 `AgentResponse` 折叠为单个 `agent_end` 事件。

### AgentProviderStatus

```json
{
  "provider": "pi_agent",
  "status": "ready",
  "message": "pi available at /opt/homebrew/bin/pi",
  "capabilities": ["chat", "tool_calls", "stream"]
}
```

`status` 可为：

- `ready`
- `not_configured`
- `unavailable`
- `error`

各 Provider 的默认状态判定：

- `codex`：始终 `ready`，deterministic baseline 不依赖 .env；.env 命中时 capabilities 增加 `["llm_upgrade"]`。
- `pi_agent`：见 `### pi_agent` 节「`status(repo_root)` 判定」，按 `shutil.which(PI_BIN)` 命中与否短路。
- `llm`：未实现，始终 `not_configured`。

### AgentMessage

```json
{
  "intent": "compare",
  "mode": "compare",
  "message": "对比 rule 和 codex 在这个节点的输出。",
  "context_revision": "sha256:...",
  "interaction_context": {
    "focus": {
      "card": "outputs",
      "artifact_ref": "planning/tdd_plan.json",
      "selected_text": "",
      "view_mode": "artifact_preview"
    },
    "allowed_operations": ["explain", "read_artifact", "suggest_input_patch", "rerun_from_node"]
  }
}
```

`mode` 是旧字段，保留兼容；新实现应优先使用 `intent`。`intent=auto` 时，由 AgentBridge 基于 `interaction_context.focus` 和用户消息选择解释、读取、对比、修改建议或重跑建议。

## Agent Prompt Context Envelope

Provider 不得只把 `node_id`、artifact 数量或风险数量传给底层模型。`AgentBridge` 在调用 Codex、PI-Agent 或通用 LLM 前，必须把 `NodeContext` 和 `AgentInteractionContext` 转换为一个业务友好的 `AgentPromptContext`。该对象是右侧 Agent 理解“用户正在问哪个节点、哪张卡片、哪个产物”的最小上下文包。

`AgentPromptContext` 必须包含：

```json
{
  "schema_version": 1,
  "run": {
    "run_id": "app_generation-20260625",
    "app_slug": "todo-prototype",
    "comparison_group_id": "cmp-todo-prototype",
    "selected_variant": "codex"
  },
  "node": {
    "node_id": "planning_tdd",
    "title": "规划与验收",
    "summary": "生成验收标准、coverage matrix、TDD 计划和 slices。",
    "status": "completed"
  },
  "focus": {
    "card": "outputs",
    "artifact_ref": "planning/tdd_plan.json",
    "artifact_title": "TDD 计划",
    "selected_text": "移动端空状态",
    "view_mode": "artifact_preview"
  },
  "app_preview": {
    "preview_status": "running",
    "preview_url": "http://127.0.0.1:8799",
    "preview_health": "ok",
    "provider_health": "未检测到 OPENROUTER_API_KEY",
    "generated_app_capability_gaps": ["缺少单张生图按钮"]
  },
  "inputs": [
    {
      "path": "requirements/normalized_prd.md",
      "title": "标准化 PRD",
      "status": "ready",
      "summary": "包含目标、范围、状态和假设。",
      "content_hash": "sha256:..."
    }
  ],
  "outputs": [
    {
      "path": "planning/tdd_plan.json",
      "title": "TDD 计划",
      "status": "ready",
      "summary": "包含功能、状态和验证命令。",
      "content_hash": "sha256:..."
    }
  ],
  "skills": [],
  "tool_calls": [],
  "usage": {},
  "scores": {},
  "risks": [],
  "allowed_operations": ["explain", "read_artifact", "rerun_from_node"]
}
```

上下文注入规则：

- `node.title` 和 `node.summary` 必须使用业务友好中文，不得只传内部 `node_id`。
- `inputs` / `outputs` 必须传入 path、title、status、summary、content_hash；默认不传完整正文。
- 当前 `focus.artifact_ref` 对应的 artifact 必须在 `inputs` 或 `outputs` 中能找到；找不到时返回 `context_invalid`，不得让 Agent 猜测。
- `skills`、`tool_calls`、`usage`、`scores`、`risks` 至少传摘要和状态。没有记录时明确传空数组或 `unknown`，不得伪造。
- `selected_text` 只用于缩小讨论范围，不作为独立事实源。
- `app_preview` 只传预览摘要、provider 配置摘要和能力缺口，不传 iframe DOM、完整 `.env` 或 API key。
- 大文件、代码、PDF、图片正文只能通过受控 `read_artifact` 动作读取，不得默认塞进 prompt。

PI-Agent prompt 必须包含 `AgentPromptContext` 的结构化 JSON 摘要，再附上用户原话。PI-Agent 的底层工具调用结果只作为右侧 tool evidence；要影响生成链路，仍必须归一化成 `AgentAction`。

## Auto Intent Routing

`intent=auto` 时，AgentBridge 必须在调用 Provider 前先做轻量意图路由，输出 `resolved_intent`。该路由不是第二套 Agent runtime，只负责把用户自然语言映射到工作台已允许的操作，避免用户必须手动切换 mode。

### Intent 枚举

| `resolved_intent` | 触发语义 | 默认动作 |
| --- | --- | --- |
| `explain_node` | “这个节点干啥”“解释一下当前节点”“为什么这样做” | `explain_node` |
| `explain_inputs` | “输入是什么”“上游依赖是什么”“PRD 输入是什么” | 解释 `NodeContext.inputs`，必要时建议 `read_artifact` |
| `explain_outputs` | “输出是什么”“产物是什么”“生成了哪些文件” | 解释 `NodeContext.outputs`，必要时建议 `read_artifact` |
| `read_artifact` | “打开/读一下这个文件”“解释当前产物”“看这段选中文本” | `read_artifact`，不改变事实源 |
| `compare_variants` | “对比 rule 和 codex”“哪个更好”“成本差异” | `compare_variants` |
| `suggest_input_patch` | “帮我改输入”“补充需求”“调整 PRD/验收” | `suggest_input_patch` |
| `patch_artifact` | “这个 artifact 改一下”“补一段” + 当前 focus 是 file_preview | `patch_artifact`（直改 artifact + 落 `artifact_patches/`） |
| `patch_app` | “加按钮”“改文案”“补接口” + 当前 focus 是 app_preview 且已发布 | `patch_app`（直改 generated_apps/<slug>/* + 落 `app_patches/`） |
| `rerun_from_node` | “重跑这个节点”“从这里重跑”“基于这个文件重新生成” | `rerun_from_node` |
| `ask_clarification` | 用户问题缺少目标、对象或权限 | `ask_clarification` |

### 路由规则

- 用户消息包含“重跑 / 重新跑 / 重新生成 / 再跑 / rerun / 基于这个文件重跑”且当前节点允许 `rerun_from_node` 时，解析为 `rerun_from_node`。
- 用户消息包含“输入 / 上游 / 依赖 / input”时，解析为 `explain_inputs`。
- 用户消息包含“输出 / 产物 / 文件 / output / artifact”时，解析为 `explain_outputs` 或 `read_artifact`，取决于是否存在 `focus.artifact_ref`。
- 用户消息包含“对比 / 差异 / 哪个好 / cost / token / usage”时，解析为 `compare_variants`。
- 用户消息包含“改 / 补充 / 调整 / patch / override”时，根据当前 focus 解析：无 focus → `suggest_input_patch`；`focus.card="file_preview"` → `patch_artifact`；`focus.card="app_preview"` 且已发布 → `patch_app`。
- 用户消息包含“生图按钮 / 模型选择 / API Key / 预览哪里不对 / 能真实生图”且 `focus.card="app_preview"` 时，解析为增量优化动作，默认目标为 `implementation`。
- 路由结果必须受 `AgentInteractionContext.allowed_operations` 限制；不允许的动作必须降级为解释或澄清。
- 路由结果、触发原因和降级原因必须进入 AgentResponse 的 debug-safe metadata 或 tool evidence，便于验收，但不得泄露 secret。

### Provider 关系

- CodexProvider、PiAgentProvider 和 GenericLlmProvider 都接收同一个 `resolved_intent` 与 `AgentPromptContext`。
- `PiAgentProvider` 不重新实现业务路由，只消费 `resolved_intent` 和上下文包，并把底层 PI 输出归一化。
- Provider 可以生成更好的自然语言回答，但不得绕过 AgentBridge 已解析出的权限边界和确认规则。

### AgentInteractionContext

`AgentInteractionContext` 描述右侧 Agent 当前正在讨论什么。它不替代 `NodeContext`，而是把中间区的 UI 焦点、选中的 artifact 和允许操作补充给 Agent。

```json
{
  "schema_version": 1,
  "run_id": "app_generation-20260625",
  "node_id": "planning_tdd",
  "context_revision": "sha256:...",
  "focus": {
    "card": "outputs",
    "artifact_ref": "planning/tdd_plan.json",
    "artifact_title": "TDD 计划",
    "selected_text": "",
    "view_mode": "artifact_preview"
  },
  "allowed_operations": [
    "explain",
    "compare",
    "read_artifact",
    "suggest_input_patch",
    "patch_artifact",
    "patch_app",
    "select_variant",
    "rerun_from_node",
    "ask_clarification"
  ]
}
```

`focus.card` 可为：

- `skill_routing`
- `variants`
- `project_skills`
- `inputs`
- `outputs`
- `tool_usage_scores_risks`
- `artifact_preview`
- `app_preview`
- `node_summary`

`allowed_operations` 由工作台根据当前节点、卡片、artifact 状态和用户权限计算。Provider 不得自行扩权。

当 `focus.card="app_preview"` 时，预览 URL、运行状态、健康检查信息只来自 `NodeContext.preview_status` / `preview_url` / `preview_health`，不在 `focus` 中重复字段；`AgentPromptContext.app_preview` 直接从 `NodeContext` 派生。`focus` 仅承担 UI 焦点定位，避免出现两个不一致的预览状态来源。

## 增量优化动作契约

右侧 Agent 对生成应用提出修改时，必须遵守增量优化原则。增量优化是指：只围绕当前预览、当前节点、当前 artifact 或用户明确指出的问题提出最小必要修改，并保留已通过的能力。

### 触发场景

以下用户消息必须进入增量优化路径，而不是完整重写路径：

- “缺少生图按钮”
- “加模型选择”
- “API Key 怎么配置”
- “这个预览哪里不对”
- “基于当前预览优化一下”
- “让这个应用能真实生图”

### 最小影响节点选择

AgentBridge 必须根据问题来源选择最小重跑节点：

| 问题来源 | 默认 target_node_id | 说明 |
| --- | --- | --- |
| 预览中缺按钮、接口、状态、错误提示 | `implementation` | 实现层缺口，不回到 PRD |
| 生成应用能力扫描发现缺 route/UI | `implementation` | 只补生成代码 |
| artifact 内容需要小改 | 当前 artifact 所属节点 | 例如只补 TDD 验收或契约字段 |
| PRD 没写清需求 | `prd_input` 或 `prd_normalization` | 需要用户补充需求事实 |
| 应用契约缺少能力声明 | `context_contract` | 需要补 contract 后再实现 |

如果缺口只在实现层，默认不得选择 `prd_input` 或 `prd_normalization`，避免把局部问题扩大成全流程重跑。

### Action Type 选择规则

AgentBridge 根据问题来源、当前焦点和改动范围选择合适的 action type：

| 问题来源 | 优先 action type | target 说明 |
| --- | --- | --- |
| 节点产物需小改 | `patch_artifact` | 直改 `artifacts/<node>/<file>`，写 `artifact_patches/` 证据 |
| 预览应用需局部改 | `patch_app` | 直改 `generated_apps/<slug>/<file>`，写 `app_patches/` 证据 |
| 预览缺能力（实现层） | `rerun_from_node` | `target=implementation`，覆盖 worktree + 需重新发布 |
| PRD 没写清 | `suggest_input_patch` | `target=prd_input`，改输入后 rerun |
| 契约缺能力声明 | `suggest_input_patch` | `target=context_contract`，补契约后 rerun |

`rerun_from_node` 用于重跑单节点：`target=implementation` 覆盖 worktree（需要重新发布才进预览），`target=prd_input` / `prd_normalization` / `context_contract` 等用于改上游后重新执行下游。

### patch_artifact 契约

Agent 焦点 = `file_preview` 时，可输出 `patch_artifact` action 直接改写节点产物：

```json
{
  "type": "patch_artifact",
  "requires_confirmation": true,
  "target_node": "implementation",
  "target_file": "app_contract.json",
  "target_path": "artifacts/implementation/app_contract.json",
  "edit_kind": "replace_block|append|create_file",
  "anchor": "// === AGENT_EDIT:routes START ===",
  "new_content": "...",
  "summary": "修正路由缺失：新增 /api/health 和 /api/images/generate"
}
```

后端处理：

1. 校验 `target_path` 在 `runs/<run_id>/artifacts/` 下（**禁止** `runs/<run_id>/codex/` 或其它路径，越界返回 422）。
2. 应用前先读取原文件，生成 unified diff。
3. 写 `runs/<run_id>/artifact_patches/<ts>__<node>__<file>.diff`。
4. 更新 `runs/<run_id>/artifact_patches/index.json`（结构见 [`docs/app_generation_node_context_contract.md`](docs/app_generation_node_context_contract.md) § Artifact Patch 契约）。
5. 覆盖原 artifact 文件。
6. SSE 推 `artifact_patch_applied` 事件，前端 file_preview 重新加载。

### patch_app 契约

Agent 焦点 = `app_preview` 时，可输出 `patch_app` action 直接改写**发布快照**：

```json
{
  "type": "patch_app",
  "requires_confirmation": true,
  "target_path": "generated_apps/<slug>/public/app.js",
  "edit_kind": "replace_block|append|create_file",
  "anchor": "// === AGENT_EDIT:image-button START ===",
  "new_content": "...",
  "summary": "把生图按钮文案改成出图"
}
```

后端处理：

1. 校验 `target_path` 在 `runs/<run_id>/generated_apps/<slug>/` 下（**禁止** `runs/<run_id>/worktree/` 或其它路径）。
2. 校验 `runs/<run_id>/generated_apps/<slug>/app_publish.json` 存在（未发布则返回 412 + `app_not_published`，引导用户先点「发布到预览」）。
3. 生成 unified diff，写 `runs/<run_id>/app_patches/<ts>__app__<file>.diff` 与 `index.json`。
4. 覆盖发布快照中的文件。
5. **触发两阶段自动重启**（新端口先起 + 健康检查 + 通过后切流量再停旧；详见 [`docs/app_preview_runner_spec.md`](docs/app_preview_runner_spec.md) § 自动重启流程（两阶段））。
6. 重启成功（健康通过、新进程接管 + 旧进程已优雅停止）：SSE 推 `app_patch_applied` + `preview_url_changed` + `preview_restarted`，前端 iframe 按新 URL 刷新，banner「应用已更新」。
7. 重启失败（新进程健康检查不通过）：新进程立即回收，**旧进程保持原状继续服务**，`preview_status.last_patch_restart_error` 写入失败阶段；SSE 推 `preview_restart_failed`，前端 banner「补丁已落盘但新版本启动失败，当前预览仍为旧版本」，补丁文件仍保留。

### 禁止行为

Agent 不得：

- 把局部 UI/接口缺口扩展为「重写整个应用」。
- 要求重新生成完整 PRD，除非用户明确要求或 PRD 确实缺失需求事实。
- 删除已通过能力或已验证路径。
- 把 API Key 放入前端、localStorage、run artifacts 或 SSE。
- 改写 `runs/<run_id>/codex/` 目录下文件（Codex 内部状态需走 `rerun_from_node`）。
- 改写 `runs/<run_id>/worktree/` 目录下文件（worktree 是 Codex 工作空间，不是预览源）。
- 未经用户确认调用 rerun。

### Provider 一致性

CodexProvider、PiAgentProvider 和 GenericLlmBridge 都必须输出同一套增量动作结构。Provider 可以生成更详细的解释，但 AgentBridge 必须负责：

- 解析 `resolved_intent`。
- 过滤不允许的操作。
- 给缺失的 action 补齐 `requires_confirmation=true`。
- 对 action 文本做 secret redaction。
- 在 action 缺少最小修改信息时降级为 `ask_clarification`。

### AgentResponse

```json
{
  "provider": "codex",
  "status": "completed",
  "message": "Codex 输出覆盖更多 UI 状态，但成本更高。",
  "actions": [],
  "tool_calls": [],
  "usage": {
    "total_tokens": "unknown"
  },
  "risk_events": []
}
```

流式 Provider 必须在终态 `agent_end.payload` 中带上可确认 `actions`，或返回空数组。`message_delta` 只负责自然语言增量，不承载可执行动作。

## AgentAction

Agent 只能返回动作建议。动作必须由前端展示并等待用户确认。

动作通用字段：

```json
{
  "type": "rerun_from_node",
  "requires_confirmation": true,
  "context_revision": "sha256:...",
  "source": "pi_agent"
}
```

规则：

- `requires_confirmation` 对所有会改变 run、variant、override、文件或重跑状态的动作必须为 `true`。
- 后端执行动作前必须校验 `context_revision`。
- AgentAction 不得包含真实 secret。
- PI Agent 的自然语言建议只有被归一化为 AgentAction 后，才能显示在待确认动作区。

### `explain_node`

解释当前节点输入、输出、风险和下一步。

```json
{
  "type": "explain_node",
  "target_node_id": "context_contract",
  "summary": "app_contract 固定了 v1 技术形态。"
}
```

### `compare_variants`

对比 rule、codex、llm 或 pi_agent variant。

```json
{
  "type": "compare_variants",
  "target_node_id": "planning_tdd",
  "variants": ["rule", "codex"],
  "summary": "rule 覆盖稳定，codex 更细但 usage 更高。"
}
```

### `suggest_input_patch`

建议修改节点输入或 override instruction。

```json
{
  "type": "suggest_input_patch",
  "target_node_id": "prd_normalization",
  "patch_summary": "补充目标用户。",
  "override_instructions": "将目标用户明确为运营同学和产品负责人。"
}
```

### `read_artifact`

请求读取当前 artifact 的完整内容，用于解释、诊断或对比。该动作可以由 AgentBridge 自动执行，也可以由前端在用户确认后执行，具体取决于 artifact 大小和权限。

```json
{
  "type": "read_artifact",
  "target_node_id": "planning_tdd",
  "target_artifact": "planning/tdd_plan.json",
  "reason": "用户询问该中间产物是否覆盖移动端验收。",
  "requires_confirmation": false
}
```

读取规则：

- 只能读取当前 run artifacts 或允许的 generated app 文件。
- 读取结果作为右侧 Agent tool evidence，不改变 `NodeContext.context_revision`。
- 超大文件必须先返回元信息和截断提示。

### `select_variant`

选择某个 variant 作为下游输入。

```json
{
  "type": "select_variant",
  "target_node_id": "planning_tdd",
  "selected_variant": "codex"
}
```

### `rerun_from_node`

从某节点创建新 run。

```json
{
  "type": "rerun_from_node",
  "source_run_id": "app_generation-20260625",
  "rerun_from_node": "planning_tdd",
  "selected_variant": "codex",
  "override_instructions": "补充移动端验收。",
  "comparison_group_id": "cmp-20260625-001"
}
```

### `ask_clarification`

向用户提出澄清问题。

```json
{
  "type": "ask_clarification",
  "question": "是否需要移动端适配作为验收标准？"
}
```

## 中间区联动

中间区订阅 AgentResponse 中的 actions。

- `explain_node`：只显示解释，不改变节点状态。
- `compare_variants`：更新对比摘要。
- `read_artifact`：通过受控 artifact read 读取完整内容，并作为右侧 tool evidence 展示。
- `suggest_input_patch`：进入右侧待确认调整。
- `patch_artifact`：进入右侧待确认 diff，确认后写 `artifact_patches/` + 覆写 artifact。
- `patch_app`：进入右侧待确认 diff，确认后写 `app_patches/` + 覆写已发布应用 + 触发两阶段重启。
- `rerun_from_node`：进入右侧待确认重跑建议，确认后覆写 worktree（implementation）或上游输入。
- `select_variant`：更新当前 selected variant，但不重跑。
- `rerun_from_node`：用户确认后调用 rerun API。
- `ask_clarification`：显示待回答问题。

任何动作都不得绕过用户确认。

联动规则：

- 点击节点只切换 `NodeContext`。
- 点击详情卡片会更新 `AgentInteractionContext.focus.card`。
- 点击文件预览会更新 `focus.artifact_ref` 和 `focus.view_mode="artifact_preview"`。
- 用户在右侧输入消息时，前端必须同时发送当前 `NodeContext` 和 `AgentInteractionContext`。
- Agent 回答必须基于当前 `context_revision`；revision 过期时返回 `context_stale`。

## 流式增强

`stream_message` 产出的 `StreamEvent` 序列定义如下（与 `### pi_agent` 节「流式事件契约」对齐）：

```text
StreamEvent
  type: "message_delta" | "tool_call" | "tool_result"
       | "agent_end" | "auto_retry_start" | "upstream_error"
       | "extension_ui_request"
  payload: object   # 见 pi_agent 节字段表
  ts: float         # epoch seconds，dashboard 端补
```

dashboard 透传规则：

- 每个 `StreamEvent` 直接序列化为一行 `data: <json>\n\n` SSE 事件。
- CodexProvider 在 `send_message` 完成后吐出单个 `{type: "agent_end", payload: AgentResponse}` 事件，前端用统一渲染管线。
- `tool_call` / `tool_result` 之外的 `AgentAction` 统一在 `agent_end.payload.actions` 中返回，以避免与 pi 的实时工具调用流混淆。
- 流式通道断开时，dashboard 必须立即发送 `upstream_error{phase:"stream_closed"}`，由前端决定是否重连。

## Agent 驱动修复扩展

本节补充右侧 Agent 对已发布应用进行高频修复的协议。总流程见 [`docs/app_generation_agent_driven_repair_spec.md`](app_generation_agent_driven_repair_spec.md)。

### AgentIntent 扩展

`intent=auto` 时，AgentBridge 必须先结合 `AgentInteractionContext.focus` 做轻量意图路由，再调用 Provider。Provider 可以生成更好的自然语言回答，但不得绕过已解析出的权限边界。

新增 intent：

| Intent | 场景 | 默认动作 |
| --- | --- | --- |
| `diagnose_app_bug` | app preview 下报告运行错误、按钮无响应、下载失败、局部迭代失败 | 诊断后给 `patch_app` 或 `verify_patch` |
| `patch_app` | app preview 下要求改模型、provider、按钮、文案、UI、小范围交互 | `patch_app` |
| `verify_patch` | 用户要求验证刚才修改或重跑 smoke | `verify_patch` |
| `rollback_patch` | 用户要求撤回已应用 patch | `rollback_patch` |
| `promote_patch_to_generation_rule` | 用户要求以后生成也遵守本次修复 | `promote_patch_to_generation_rule` |
| `delegate_code_repair` | 修复需要完整代码上下文、同文件多处联动修改或无法用单个稳定锚点表达 | 委托 Code Agent 生成 patch |

当 `focus.card="app_preview"` 且用户消息包含“报错 / not configured / timeout / 模型 / provider / API key / 生图 / 按钮 / 下载 / 局部迭代”等信号时，`auto` 必须优先解析为 `patch_app` 或 `diagnose_app_bug`，不得只解释当前节点。

短期实现中，`patch_app` 只用于锚点明确的小范围已发布应用修复。若修复需要对同一个文件多个分散区域做联动修改，右侧 Agent 不应继续构造多个 `replace_text`，而应输出 `delegate_code_repair` 或使用单个 `replace_block` 重写一个已存在的 `AGENT_EDIT` 区间。

### PatchSet action

`patch_app` 支持单文件和批量 PatchSet。批量 PatchSet 用同一个 `AgentAction` 表达，前端只展示一次确认 diff。

```json
{
  "type": "patch_app",
  "summary": "修复图片 provider/model 默认配置",
  "requires_confirmation": true,
  "problem_source": "app_preview",
  "preserve_capabilities": ["四阶段工作流", "产品图上传", "Prompt 下载", "localStorage 状态"],
  "verification": ["node --check server.js", "node --check public/app.js", "node runtime_smoke.js", "GET /api/health"],
  "patches": [
    {
      "target_path": "generated_apps/input-prd/server.js",
      "edit_kind": "replace_text",
      "old_content": "const model = process.env.OPENAI_IMAGE_MODEL || \"gpt-image-1\";",
      "new_content": "const model = process.env.OPENROUTER_IMAGE_MODEL || process.env.OPENAI_IMAGE_MODEL || \"openai/gpt-5.4-image-2\";"
    }
  ]
}
```

PatchSet 规则：

- `target_path` 必须是完整 run-relative 路径 `generated_apps/<slug>/<file>`，例如 `generated_apps/input-prd/server.js`。不得写成 `<slug>/server.js`、`server.js`、`worktree/generated_apps/<slug>/server.js` 或绝对路径。
- `target_path` 不得指向 worktree、`codex/`、仓库源码、`.env`、`node_modules`、`app_publish.json` 或任意 secret 文件。
- v1 `edit_kind` 支持 `replace_block`、`append`、`create_file`、`replace_text`。
- `replace_text` 必须精确匹配 `old_content`；任一 patch 不匹配则整个 PatchSet dry-run 失败。
- 短期实现要求一个 PatchSet 内同一 `target_path` 只能出现一次。多处修改同一文件时，必须合并为单个 patch。
- 同一文件多处修改的首选方式是 `replace_block`，以一个 `// === AGENT_EDIT:<id> START ===` 锚点替换整个区间。不要输出多个指向同一文件的 `replace_text`。
- dry-run 不写文件，只返回整体 diff、风险和验证计划。
- apply 必须先校验全部 patch，再写任何文件；任一失败时保持原文件不变。
- apply 成功后写 `app_patches/` 证据，触发验证；若 preview 正在运行，触发两阶段重启。

### delegate_code_repair action

`delegate_code_repair` 是长期修复路径。它把右侧 Agent 理解到的问题交给中间 Code Agent，由 Code Agent 读取完整应用上下文并生成可确认 patch。

```json
{
  "type": "delegate_code_repair",
  "summary": "委托 Code Agent 修复图片模型配置",
  "target": "published_app",
  "problem_source": "app_preview",
  "requires_confirmation": true,
  "repair_request": {
    "app_slug": "input-prd",
    "problem": "单张生图仍使用 gpt-image-1，未读取 OPENROUTER_IMAGE_MODEL",
    "constraints": ["只修改当前已发布应用", "不重跑 PRD", "保留现有工作流"],
    "expected_behavior": ["服务端优先读取 OPENROUTER_IMAGE_MODEL", "前端请求不得覆盖服务端模型"],
    "verification": ["node --check server.js", "node --check public/app.js", "node runtime_smoke.js"]
  }
}
```

协议边界：

- 右侧 PI-Agent 只产出 `repair_request`，不直接写文件。
- Code Agent 是唯一代码修改执行者；Codex、PI-code 或其他 provider 必须统一挂到 `CodeAgentExecutor`。
- Code Agent 输出仍必须走 dry-run diff、用户确认、apply、验证、证据记录和预览重启。
- `delegate_code_repair` 不等于 `rerun_from_node`：它修的是当前已发布快照，不重跑完整 PRD 流程。

### verify / rollback / promote actions

```json
{
  "type": "verify_patch",
  "target": "latest_app_patch",
  "commands": ["node --check server.js", "node runtime_smoke.js"],
  "requires_confirmation": false
}
```

```json
{
  "type": "rollback_patch",
  "patch_id": "20260627T120000Z__server_js",
  "requires_confirmation": true
}
```

```json
{
  "type": "promote_patch_to_generation_rule",
  "patch_id": "20260627T120000Z__provider_model",
  "candidate_scope": "image_generation_provider_defaults",
  "requires_confirmation": true
}
```

`promote_patch_to_generation_rule` 只创建候选记录，不自动修改模板、benchmark、verifier 或测试代码。

### PI-Agent fallback 要求

PI-Agent 的自然语言回复如果指出了正确修复方向，但没有返回结构化 `AgentAction`，AgentBridge 必须根据 `resolved_intent`、`AppPreviewContext` 和可 patch 文件摘要生成 deterministic fallback action。这样用户不会停在“建议正确但不知道怎么改”的状态。

## V2 生成画布 Agent 契约

V2 生成画布规范见 [`docs/app_generation_canvas_experience_spec.md`](app_generation_canvas_experience_spec.md)，Runway Timeline 主体验规范见 [`docs/app_generation_runway_timeline_spec.md`](app_generation_runway_timeline_spec.md)。V2 中右侧 Agent 的默认协作对象从“当前工程节点”升级为“当前选中的 BusinessStep 或画布对象”。V1 的 `NodeContext` 仍然是事实上下文，V2 的 `CanvasSelectionContext` 用于描述 UI 焦点和对象权限。

### AgentPromptContext V2

AgentBridge 调用 Provider 前必须把以下上下文合成为 `AgentPromptContext`：

- 当前 run、当前 Runway `BusinessStep` 和业务节点摘要。
- 当前 `CanvasObject` 摘要。
- 当前对象的 source refs、artifact refs、evidence refs。
- 当前对象状态和能力缺口。
- 当前 preview/provider/repair 进度摘要。
- 当前 allowed actions。
- 不能改变的已通过能力。
- 需要用户确认的动作边界。

默认不得注入：

- 完整 artifact 正文。
- 完整源码。
- 完整 stdout/stderr。
- 完整 prompt。
- API key、完整 `.env` 或进程环境。
- iframe DOM。

### AgentIntent V2

| Intent | 触发场景 | 默认动作 |
| --- | --- | --- |
| `explain_step` | 用户选中 Runway 步骤后问“这一步在干什么” | 解释步骤目标、输入、执行过程、输出和风险 |
| `explain_step_io` | 用户选中 Runway 步骤后问“输入输出是什么” | 列出步骤输入/输出摘要和证据入口 |
| `inspect_evidence` | 用户要求查看证据、日志、产物、diff | 展开当前步骤工程证据或读取受控 artifact |
| `rerun_step` | 用户要求“重新跑这一步” | 映射到该步骤第一个最小可执行 runtime node，并创建新 run |
| `explain_object` | 用户问“这个能力是什么”“这个输入从哪来”“为什么这个对象需要关注” | 解释当前对象、来源和证据 |
| `edit_business_object` | 用户要求调整目标、场景、能力、验收标准或优先级 | `suggest_object_patch`，确认后进入 override 或新 run |
| `repair_generated_app` | 用户在应用预览中报告运行错误、按钮无响应、模型/provider 错误、下载失败、局部迭代失败 | 简单锚点问题 `patch_app`；复杂问题 `delegate_code_repair` |
| `verify_capability` | 用户要求“验证这个能力”“看看修好没” | 运行受控验证或生成验证计划 |
| `compare_canvas_objects` | 用户要求比较能力、版本、变体、修复前后 | 读取对象摘要和 evidence refs |
| `promote_to_generation_rule` | 用户要求“以后生成都这样”“沉淀为规则” | 生成候选规则，待确认 |
| `rerun_business_node` | 缺口来自业务输入、规格或规划，不适合直接修已发布应用 | 创建新 run，记录业务节点起点 |
| `ask_clarification` | 输入不足或风险太高 | 提问，不执行修改 |

当 `CanvasSelectionContext.selection_type="flow_step"` 时，`intent=auto` 必须优先按当前步骤和用户消息解析。选中 `app_preview` 且用户消息包含“报错 / not configured / timeout / 模型 / provider / API key / 生图 / 按钮 / 下载 / 局部迭代”等信号时，默认解析为 `repair_generated_app` 或 `delegate_code_repair`，不得只解释 `preview_delivery`。

当 `CanvasSelectionContext.selection_type="canvas_object"` 时，`intent=auto` 必须优先按对象类型和用户消息解析。只有没有选中步骤/对象或对象上下文不可用时，才退回 V1 的节点解释策略。

### AgentAction V2

V2 新增或规范化以下对象化动作：

```json
{
  "type": "suggest_object_patch",
  "source_object_id": "capability:image_generation.single",
  "summary": "补充单张生图验收标准",
  "patch": {
    "field": "acceptance",
    "operation": "append",
    "value": "用户点击单张生图后，服务端使用 OPENROUTER_IMAGE_MODEL 生成图片或返回可行动错误。"
  },
  "requires_confirmation": true,
  "verification": ["更新后从 编译业务规格 节点重跑"]
}
```

```json
{
  "type": "repair_generated_app",
  "source_object_id": "capability_gap:gpt-image-1-not-configured",
  "strategy": "delegate_code_repair",
  "problem_source": "app_preview",
  "preserve_capabilities": ["四阶段工作流", "Prompt 下载", "localStorage 状态"],
  "repair_request": {
    "app_slug": "input-prd",
    "problem": "单张生图仍使用 gpt-image-1，未读取 OPENROUTER_IMAGE_MODEL",
    "constraints": ["只修改当前已发布应用", "不重跑完整 PRD"],
    "verification": ["node --check server.js", "node runtime_smoke.js"]
  },
  "requires_confirmation": true
}
```

```json
{
  "type": "verify_capability",
  "source_object_id": "capability:image_generation.single",
  "verification": ["node runtime_smoke.js", "GET /api/health"],
  "requires_confirmation": false
}
```

所有 V2 action 必须包含：

- `source_object_id`
- `summary`
- `requires_confirmation`
- `verification` 或明确说明无需验证
- `preserve_capabilities`，当动作会影响已发布应用或生成规则时必填

### V1 / V2 动作映射

| V2 action | V1 / 后端动作 |
| --- | --- |
| `explain_step` | `explain` + `flow_step` context |
| `explain_step_io` | `explain` + step input/output refs |
| `inspect_evidence` | artifact preview / developer evidence foldout |
| `rerun_step` | `rerun_from_node` + step 到 runtime node 映射 |
| `explain_object` | `explain` |
| `suggest_object_patch` | `suggest_input_patch` 或新 run override |
| `repair_generated_app(strategy=patch_app)` | `patch_app` |
| `repair_generated_app(strategy=delegate_code_repair)` | `delegate_code_repair` |
| `verify_capability` | 受控 verification / preview health / capability scanner |
| `compare_canvas_objects` | `compare` + artifact/evaluation refs |
| `promote_to_generation_rule` | 候选规则记录，后续实施确认 |
| `rerun_business_node` | `rerun_from_node` + 业务节点到 runtime node 映射 |

V2 action 只是更业务友好的协议层。真正修改应用、重跑节点或提升规则时，仍必须进入 V1 受控 API 和人工确认 gate。
