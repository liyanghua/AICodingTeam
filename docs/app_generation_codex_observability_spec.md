# Codex 执行过程可观测规范

## 状态

本文档定义 `PRD生成应用` 工作台中 Codex 执行过程的可观测契约。该能力用于解释两个长等待点：

- `implementation` 节点中 Codex 生成应用代码的过程。
- 右侧 Agent 触发 `delegate_code_repair` 后，CodeAgentExecutor 委托 Codex 修复已发布应用的过程。

本规范只定义可观测层。`CodexProgressEvent` 不是最终事实源；最终状态仍以 `team_run_record.json`、`codex/verification_record.json`、`codex/app_repair_result.json`、`codex/app_repair_verification.json` 和 apply/preview 结果为准。

## 目标

用户等待 Codex 时，工作台必须回答四个问题：

- 当前处于哪个阶段。
- Codex 最近做了什么。
- 产物、日志和候选 diff 在哪里。
- 是仍在运行、已失败，还是已完成并等待用户确认。

可观测层不得扩大代码修改权威。右侧 PI-Agent 仍只负责理解用户诉求并产出结构化动作；复杂代码修改仍由 `CodeAgentExecutor` 执行。

## CodexProgressEvent

统一事件结构：

```json
{
  "schema_version": 1,
  "event_id": "progress-20260628T120000Z-0001",
  "run_id": "app_generation-20260628T120000Z",
  "operation_id": "implementation-coder",
  "operation_type": "implementation",
  "node_id": "implementation",
  "stage": "coder",
  "event_type": "codex_item_completed",
  "status": "completed",
  "title": "运行验证命令",
  "summary": "node --check server.js 已完成，exit_code=0。",
  "business_status": "已完成",
  "artifact_refs": ["codex/stdout.jsonl"],
  "file_changes": [],
  "tool_calls": [],
  "usage": {},
  "risk_events": [],
  "started_at": "2026-06-28T12:00:00Z",
  "finished_at": "2026-06-28T12:00:04Z",
  "elapsed_ms": 4000
}
```

字段规则：

- `operation_type`：`implementation`、`delegate_code_repair`、`benchmark_fix_slice` 或后续扩展值。
- `operation_id`：同一执行过程内稳定，例如 `implementation-coder` 或 `repair-<id>`。
- `event_type`：必须来自本文档固定集合。
- `title` 和 `summary`：面向业务用户，不直接暴露原始 JSON 事件名。
- `artifact_refs`：只放 run-relative path，不放完整文件内容。
- `usage` 缺失时为空对象，不得估算或伪造。
- 所有文本必须经过 secret redaction。

## 事件类型

| event_type | 含义 | 默认业务标题 |
| --- | --- | --- |
| `stage_started` | 阶段开始，准备 prompt、state summary、worktree 或 repair context | 准备执行 |
| `process_started` | Codex 子进程已启动 | 启动 Code Agent |
| `codex_item_started` | Codex stdout 中一个 item 开始，例如命令执行、文件读取、文件修改 | 正在执行 |
| `codex_item_completed` | Codex stdout 中一个 item 完成 | 执行完成 |
| `agent_message` | Codex 输出阶段性说明或结构化 next_action | Code Agent 说明 |
| `verification_started` | 开始运行 allowlist 验证命令 | 开始验证 |
| `verification_completed` | 验证命令完成 | 验证完成 |
| `diff_ready` | 候选 diff 已生成 | 候选改动已生成 |
| `stage_completed` | 阶段完成 | 执行完成 |
| `stage_failed` | 阶段失败 | 执行失败 |

## Progress Artifacts

应用实现节点：

- `runs/<run_id>/codex/coder_progress.jsonl`
- `runs/<run_id>/codex/coder_progress_status.json`

右侧委托修复：

- `runs/<run_id>/app_repairs/<repair_id>/progress.jsonl`
- `runs/<run_id>/app_repairs/<repair_id>/progress_status.json`

`progress_status.json` 保存最新状态摘要：

```json
{
  "schema_version": 1,
  "operation_id": "repair-20260628-abc123",
  "operation_type": "delegate_code_repair",
  "status": "running",
  "current_title": "运行验证命令",
  "current_summary": "Code Agent 正在运行 node --check server.js。",
  "latest_event_id": "progress-20260628T120000Z-0012",
  "latest_event_at": "2026-06-28T12:01:10Z",
  "started_at": "2026-06-28T12:00:00Z",
  "elapsed_ms": 70000,
  "result_ready": false,
  "diff_ready": false,
  "artifact_refs": ["codex/app_repair_stdout.log"],
  "risk_events": [],
  "blockers": []
}
```

状态可为：

- `pending`
- `running`
- `waiting_for_codex`
- `verifying`
- `prepared`
- `failed`
- `applied`
- `cancelled`

## stdout JSONL 映射

Codex stdout 原始事件必须转换为业务友好进度：

- `thread.started` → `process_started`
- `turn.started` → `stage_started`
- `item.started` + `command_execution` → `codex_item_started`，标题为“运行命令”
- `item.completed` + `command_execution` → `codex_item_completed`，摘要包含命令名、exit_code 和截断输出
- `item.started` + `file_change` → `codex_item_started`，标题为“准备修改文件”
- `item.completed` + `file_change` → `codex_item_completed`，摘要只列文件路径和 kind
- `agent_message` → `agent_message`，只提取 `summary`、`next_action`、`blockers`、`risk_events`

无法识别的 stdout 事件不丢弃，降级为：

```json
{
  "event_type": "codex_item_completed",
  "title": "Code Agent 有新输出",
  "summary": "原始输出已更新，可在受控日志预览中查看。"
}
```

## UI 展示规则

节点详情「执行过程」卡片必须展示实时 timeline：

- 最近 running 事件高亮。
- 已完成事件折叠为简短摘要。
- 命令执行可展开查看脱敏、截断后的 stdout/stderr 摘要。
- 文件修改只显示路径、kind 和数量，不显示完整源码。
- 30 秒没有新事件且最终状态未出现时，显示“Code Agent 仍在运行，暂无新输出”。

右侧 Agent 区在 `delegate_code_repair` prepare 期间展示「Code Agent 修复进度」：

- 已接收修复请求。
- 已复制当前发布应用快照。
- 已启动 Codex。
- Codex 正在读取、修改或验证。
- 候选 diff 已生成。
- 验证完成，等待用户确认 apply。

## API 契约

主生成链路复用现有 run SSE：

```text
GET /api/app-generation/runs/<run_id>/events/stream
```

新增事件：

```json
{
  "type": "node_progress",
  "payload": {
    "run_id": "app_generation-...",
    "node_id": "implementation",
    "operation_id": "implementation-coder",
    "event": {}
  }
}
```

右侧委托修复增加只读 status API：

```text
GET /api/app-generation/runs/<run_id>/delegate-code-repair/status?repair_id=<repair_id>
```

返回：

```json
{
  "run_id": "app_generation-...",
  "repair_id": "repair-...",
  "status": "running",
  "latest_events": [],
  "progress_status": {},
  "result_ready": false,
  "diff_ready": false,
  "risk_events": [],
  "blockers": []
}
```

前端必须在发起 prepare 前生成 `repair_id` 并传给 `POST /delegate-code-repair`，然后并行轮询 status API。prepare 请求返回后，仍沿用候选 diff、用户确认和 apply 流程。

## 安全与截断

- Progress 不得包含 API key、完整 `.env`、完整 prompt、完整源码或完整 stdout。
- 命令输出摘要默认截断到 2KB。
- 文件内容只能通过受控 artifact preview 读取，且遵守已有 path confinement。
- `CodexProgressEvent` 不改变 run 状态，不触发 apply，不改变 `context_revision`；只有 artifact refs、验证结果、patch 或用户 override 变化时才更新事实上下文。

## App Repair 边界

`delegate_code_repair` 的候选修改必须限制在：

```text
worktree/generated_apps/<slug>/
```

禁止修改：

- `worktree/tests/`
- 仓库源码
- `runs/<run_id>/codex/`
- `.env` 或 `.env.*`
- `node_modules/`
- `app_publish.json`

如果 Codex 修改了允许目录之外的文件，prepare 必须失败，返回 risk event：

```text
outside_repair_scope_changes
```

旧 `runs/<run_id>/generated_apps/<slug>/` 必须保持不变，右侧 Agent 进度展示“Code Agent 尝试修改修复范围外文件，旧应用未修改”。

