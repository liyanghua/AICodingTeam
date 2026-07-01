# PRD 生成应用 NodeContext 契约

## 状态

本文档定义 `NodeContext`，用于连接 `PRD生成应用` 工作台的中间节点区和右侧 Agent 区。该契约处于 spec-first 阶段，当前仓库尚未实现对应 API 或前端状态同步。

`NodeContext` 是 Agent 与节点事实层之间唯一共享上下文。右侧 Agent 不应直接读取浏览器临时状态，也不应直接写 run artifacts。

`AgentInteractionContext` 是 `NodeContext` 的配套请求上下文，用于描述右侧 Agent 当前讨论的 UI 焦点，例如当前详情卡片、当前 artifact、选中文本和允许操作。它不属于节点事实源，不参与 run artifact 写入。

## 设计目标

- 让中间节点区和右侧 Agent 区共享同一份可审计上下文。
- 让 Agent 能解释、对比、建议和触发重跑，但不能悄悄覆盖旧产物。
- 让 Codex、PI-Agent 和其他 LLM 使用同一个上下文格式。
- 通过 `context_revision` 防止基于旧上下文误操作。

## NodeContext JSON

```json
{
  "schema_version": 1,
  "context_id": "app_generation-20260625:planning_tdd:codex:revision",
  "run_id": "app_generation-20260625",
  "comparison_group_id": "cmp-20260625-001",
  "source_run_id": "",
  "node_id": "planning_tdd",
  "selected_variant": "codex",
  "context_revision": "sha256:...",
  "app_slug": "todo-prototype",
  "brief": "根据 PRD 生成本地应用：todo-prototype",
  "inputs": [],
  "outputs": [],
  "skills": [],
  "tool_calls": [],
  "usage": {},
  "scores": {},
  "risks": [],
  "preview_status": {},
  "preview_url": "",
  "preview_health": {},
  "provider_health": {},
  "generated_app_capability_gaps": [],
  "execution_progress": {},
  "code_repair_progress": {},
  "app_patch_targets": [],
  "adjustment_events": [],
  "user_overrides": [],
  "available_actions": []
}
```

## 字段定义

### 标识字段

- `schema_version`：契约版本。v1 固定为 `1`。
- `context_id`：`run_id:node_id:selected_variant:context_revision` 的稳定标识。
- `run_id`：当前 run。
- `comparison_group_id`：同一 PRD 或同一重跑实验的对比分组。
- `source_run_id`：如果当前 run 来自重跑，记录源 run。
- `node_id`：当前节点。
- `selected_variant`：当前选中变体，常见值为 `rule`、`codex`、`llm`、`pi_agent`。
- `context_revision`：上下文哈希。节点切换、variant 切换、artifact 引用变化或用户 override 变化时必须更新。

### Preview 摘要字段

`NodeContext` 可以携带应用预览和生成应用能力缺口摘要，用于右侧 Agent 增量优化生成结果。

```json
{
  "preview_status": {
    "status": "running",
    "port": 8799,
    "log_path": "preview/preview.log",
    "record_path": "preview/preview_run_record.json"
  },
  "preview_url": "http://127.0.0.1:8799",
  "preview_health": {
    "health_status": "ok",
    "health_message": "GET / returned 200",
    "checked_at": "2026-06-27T10:00:00Z"
  },
  "provider_health": {
    "configured": false,
    "provider": "openrouter",
    "image_model": "openai/gpt-5.4-image-2",
    "message": "未检测到 OPENROUTER_API_KEY"
  },
  "generated_app_capability_gaps": [
    {
      "id": "image_generation_button_missing",
      "severity": "blocking",
      "summary": "预览页面未发现单张生图按钮。",
      "evidence_refs": ["generated_apps/input-prd/public/index.html"]
    }
  ]
}
```

规则：

- `preview_status` 只来自 `preview/preview_run_record.json` 或 preview status API。
- `preview_url` 只能是 `http://127.0.0.1:<port>` 形式的本地 URL。
- `preview_health` 是健康检查摘要，不包含响应正文。
- `provider_health` 只能包含 provider 是否配置、provider 名称、模型名、错误摘要；不得包含 API key、完整 `.env` 或进程环境。
- `generated_app_capability_gaps` 是能力扫描摘要，用于指导 Agent 增量优化；不得把它当作最终评分事实，最终评分仍以评估器和 run artifacts 为准。
- 打开、刷新或关闭应用预览不改变 `context_revision`。
- preview record、provider health、能力扫描结果或用户 override 发生变化时，必须更新 `context_revision`。
- iframe 内容不注入 `NodeContext`。Agent 如果需要分析页面，只能使用 preview status、能力扫描、artifact 预览或用户描述。

### Execution Progress 摘要字段

`execution_progress` 描述当前节点最近的 Codex 执行进度，用于让右侧 Agent 和中间节点详情理解“现在执行到哪里”。它只包含摘要和引用，不包含完整 stdout、prompt、源码或 secret。

```json
{
  "execution_progress": {
    "operation_id": "implementation-coder",
    "status": "running",
    "current_title": "运行命令",
    "current_summary": "Code Agent 正在运行 node --check server.js。",
    "latest_event_at": "2026-06-28T12:01:10Z",
    "elapsed_ms": 70000,
    "progress_refs": [
      "codex/coder_progress.jsonl",
      "codex/coder_progress_status.json"
    ],
    "latest_events": [
      {
        "event_type": "codex_item_completed",
        "title": "修改文件",
        "summary": "已更新 generated_apps/input-prd/server.js。"
      }
    ]
  }
}
```

规则：

- `execution_progress` 来自 [`docs/app_generation_codex_observability_spec.md`](app_generation_codex_observability_spec.md) 的 `CodexProgressEvent` 聚合。
- 只保留最近少量事件摘要；完整进度通过 `progress_refs` 受控读取。
- 30 秒无新事件且终态未出现时，UI 显示“Code Agent 仍在运行，暂无新输出”。
- `execution_progress` 不改变 run 事实状态；最终状态仍以 run record 和验证产物为准。

### Code Repair Progress 摘要字段

`code_repair_progress` 描述右侧 Agent 触发 `delegate_code_repair` 后的 CodeAgentExecutor 执行进度。

```json
{
  "code_repair_progress": {
    "repair_id": "repair-20260628-abc123",
    "status": "running",
    "current_title": "启动 Code Agent",
    "current_summary": "Codex 已启动，正在读取已发布应用快照。",
    "latest_event_at": "2026-06-28T12:02:00Z",
    "result_ready": false,
    "diff_ready": false,
    "progress_refs": [
      "app_repairs/repair-20260628-abc123/progress.jsonl",
      "app_repairs/repair-20260628-abc123/progress_status.json"
    ]
  }
}
```

规则：

- `code_repair_progress` 只用于对话协作和 UI 展示，不授权 Agent 直接写文件。
- `diff_ready=true` 只表示候选 diff 可供用户确认，不等于已 apply。
- `status=failed` 时必须带可行动摘要和 risk refs，旧已发布应用不得被修改。
- 不注入完整 repair prompt、完整 stdout、完整源码、`.env` 或 API key。

### AppPreviewContext

`focus.card="app_preview"` 时，后端必须从 `NodeContext` 派生 `AppPreviewContext` 注入 Agent prompt。该对象用于让 Agent 理解“当前运行应用发生了什么”，不是 iframe DOM 镜像。

```json
{
  "preview_url": "http://127.0.0.1:8799",
  "preview_status": {
    "status": "running",
    "published_at": "2026-06-27T10:00:00Z",
    "source_commit": "unknown",
    "app_patches_count": 2,
    "invalidated_by_rerun": false
  },
  "preview_health": {
    "health_status": "ok",
    "health_message": "GET / returned 200"
  },
  "provider_health": {
    "configured": false,
    "provider": "openrouter",
    "image_model": "openai/gpt-5.4-image-2",
    "message": "OPENROUTER_API_KEY 未配置或不可用"
  },
  "generated_app_capability_gaps": []
}
```

规则：

- `AppPreviewContext` 不包含 iframe DOM、完整页面 HTML、完整 `.env`、API key 或进程环境。
- provider/model 错误可以进入 `provider_health.message`，但必须脱敏。
- 预览日志只允许进入摘要或最近错误行，且必须过 secret redaction。
- 用户报告的错误文本可以作为本轮 `AgentMessage.message` 使用，但不得写入 `NodeContext` 事实字段，除非框架产生了对应 `AdjustmentEvent`。

### app_patch_targets

`app_patch_targets` 告诉 Agent 当前已发布应用哪些文件可被 `patch_app` 修改。它是安全摘要，不是完整文件内容。

```json
{
  "path": "generated_apps/input-prd/public/app.js",
  "kind": "code",
  "size_bytes": 18420,
  "content_hash": "sha256:...",
  "summary": "前端交互逻辑，包含模型选择和单张/批量生成请求。",
  "agent_edit_anchors": [
    {
      "id": "generation-client",
      "start": "// === AGENT_EDIT:generation-client START ===",
      "end": "// === AGENT_EDIT:generation-client END ===",
      "summary": "图片生成请求逻辑"
    }
  ],
  "patchable": true
}
```

规则：

- 只列出 `runs/<run_id>/generated_apps/<slug>/` 下允许修改的文件。
- 不列出 `app_publish.json`、`.env`、`node_modules`、二进制大文件或任何 secret 文件。
- 可以包含 AGENT_EDIT 锚点和短摘要；不得默认包含完整文件正文。
- Agent 需要完整内容时，必须通过受控 app file read 或 dry-run 机制请求，且读取结果只作为 tool evidence。

### code_repair_context

`code_repair_context` 告诉右侧 Agent 何时应把修复请求委托给 Code Agent，而不是继续直接构造 `patch_app`。

```json
{
  "target": "published_app",
  "app_slug": "input-prd",
  "published_app_root": "generated_apps/input-prd",
  "repairable_by_code_agent": true,
  "code_agent_executor": {
    "default_provider": "codex",
    "available_providers": ["codex", "pi_code"]
  },
  "recommended_action": "delegate_code_repair",
  "reason": "同一文件需要多处联动修改，无法用一个稳定 AGENT_EDIT 区间表达。",
  "safe_context_refs": [
    "app_publish.json",
    "generated_apps/input-prd/server.js",
    "generated_apps/input-prd/public/app.js",
    "app_patches/index.json",
    "preview/status.json"
  ],
  "verification": ["node --check server.js", "node --check public/app.js", "node runtime_smoke.js"]
}
```

规则：

- `code_repair_context` 只包含摘要、文件引用、hash、验证命令和安全约束，不包含完整源码、iframe DOM、完整 `.env`、API key 或未脱敏日志。
- 当问题需要完整代码上下文、同一文件多处联动修改、跨文件行为理解或 provider 协议重写时，右侧 Agent 应输出 `delegate_code_repair`，由 `CodeAgentExecutor` 读取受控上下文并生成 patch。
- `delegate_code_repair` 修复目标仍是当前已发布快照 `runs/<run_id>/generated_apps/<slug>/`，不是 worktree，也不是 `codex/` 原始输出。
- Code Agent 输出仍必须走 dry-run diff、用户确认、apply、验证、证据记录和预览重启闭环；不得绕过 AgentAction。

### adjustment_events

`adjustment_events` 记录用户通过右侧 Agent 对已发布应用进行的高频调优。

```json
{
  "event_id": "adjustment-20260627T120000Z",
  "type": "app_adjustment",
  "user_message": "把单张生图模型改成 gpt-5.4-image-2",
  "resolved_intent": "patch_app",
  "patch_status": "applied",
  "verification_status": "passed",
  "rollback_available": true,
  "diff_refs": ["app_patches/20260627__server_js.diff"]
}
```

规则：

- `adjustment_events` 是用户调优历史摘要，用于节点流和 Agent 上下文。
- 事件必须可由 `runs/<run_id>/app_patches/`、验证记录和 preview record 重放或解释。
- 高频调整不是新 run；它修改的是已发布快照。
- 如果后续 implementation 重跑，旧 adjustment events 必须标记 `invalidated_by_rerun=true`，但不得删除证据。

### Artifact 引用

`inputs` 和 `outputs` 使用相同结构。

```json
{
  "path": "requirements/normalized_prd.md",
  "scope": "run",
  "title": "标准化 PRD",
  "status": "ready",
  "summary": "包含目标、范围、状态和假设。",
  "content_hash": "sha256:...",
  "read_url": "/api/runs/<run_id>/artifact?path=requirements/normalized_prd.md"
}
```

规则：

- Agent 默认只接收 `summary`、`path`、`status` 和 `content_hash`。
- Agent 需要完整内容时，必须通过受控 artifact read API 拉取。
- 不允许把大体量 artifact 全量塞进所有 Agent message。
- `scope=repo` 只能用于已允许的仓库级文件，例如 `AGENTS.md`。
- UI 可以使用 artifact 引用打开只读文件预览，但预览读取不等同于 Agent 上下文注入。
- 预览读取不得写入 `user_overrides`，不得触发重跑，除非 artifact 引用或 `content_hash` 变化，否则不得改变 `context_revision`。

### Agent Prompt 摘要要求

`NodeContext` 是事实源，但 Provider 不应直接把完整 `NodeContext` 原样拼成自然语言 prompt。后端必须派生 `AgentPromptContext`，把业务用户关心的信息明确传给 Agent。该派生摘要至少包含：

- 当前节点的业务标题、业务摘要和状态。
- 当前选中 variant、comparison group 和 source run 信息。
- `inputs` 列表：每项 artifact 的 `title`、`path`、`status`、`summary`、`content_hash`。
- `outputs` 列表：每项 artifact 的 `title`、`path`、`status`、`summary`、`content_hash`。
- 当前 `AgentInteractionContext.focus`：卡片、artifact、选中文本和 view mode。
- Project Skills 摘要：skill 名称、角色、为什么使用、状态。
- Tool calls 摘要：工具名、输入摘要、输出摘要、状态和相关 artifact。
- Usage / Scores / Risks 的业务友好摘要。
- 应用预览摘要：`preview_status`、`preview_url`、`preview_health`。
- Provider 配置摘要：`provider_health`，必须脱敏。
- 生成应用能力缺口：`generated_app_capability_gaps`。
- `allowed_operations` 和 `resolved_intent`。

禁止只传以下低信息量字段作为 Provider prompt：

- 仅传 `node_id` 而不传业务标题。
- 仅传输入/输出数量而不传输入/输出列表。
- 仅传 artifact path 而不传 title 和 summary。
- 仅传“当前节点有 N 个风险”而不传风险摘要。

完整 artifact 正文读取规则：

- 默认不读取完整正文，避免 prompt 膨胀和意外泄露。
- 用户明确要求“读这个文件 / 解释当前产物 / 看选中文本”时，AgentBridge 可生成 `read_artifact` 动作。
- `read_artifact` 成功后，读取结果作为右侧 tool evidence 注入下一轮 Agent prompt，仍不改变 `NodeContext.context_revision`。
- 超大文件只能注入元信息、截断提示和可读片段摘要。

### App Preview Focus

当用户打开应用预览时，前端必须通过 `AgentInteractionContext` 表达当前讨论对象：

```json
{
  "focus": {
    "card": "app_preview",
    "view_mode": "app_preview",
    "artifact_ref": "",
    "selected_text": ""
  },
  "allowed_operations": [
    "explain",
    "suggest_input_patch",
    "patch_artifact",
    "patch_app",
    "rerun_from_node"
  ]
}
```

`focus.card="app_preview"` 时，Agent 默认围绕当前运行应用、预览状态和能力缺口回答。用户要求修改时，Agent 必须输出 `patch_app` action，而不是完整替换 PRD 或重写所有节点。

预览 URL、状态和健康信息只在 `NodeContext.preview_status` / `preview_url` / `preview_health` 中维护；`focus` 只表达 UI 焦点，不重复 preview 字段。`AgentPromptContext.app_preview` 直接从 `NodeContext` 派生，避免 focus 与 NodeContext 出现不一致的预览状态来源。

### Artifact Preview 引用

artifact refs 可以包含预览所需的只读元信息。

```json
{
  "path": "generated_apps/todo-prototype/public/app.js",
  "scope": "generated_app",
  "title": "前端交互代码",
  "status": "ready",
  "summary": "实现任务新增、完成、筛选和本地保存。",
  "content_hash": "sha256:...",
  "preview": {
    "enabled": true,
    "kind": "code",
    "mime_type": "text/javascript",
    "size_bytes": 18420,
    "read_url": "/api/app-generation/runs/<run_id>/artifacts/preview?path=generated_apps/todo-prototype/public/app.js"
  }
}
```

预览类型：

- `text`：纯文本、Markdown、日志和说明文档。
- `code`：JSON、YAML、HTML、CSS、JS 和其他代码文件。
- `image`：可内联展示的图片。
- `pdf`：浏览器可内嵌展示的 PDF。
- `binary`：未知二进制，只展示元信息。
- `too_large`：超过预览大小限制，只展示元信息和大小限制提示。

`preview.read_url` 必须是受控只读接口，不得暴露本机绝对路径。Agent 默认不会自动读取 `preview.read_url`；只有用户明确要求解释完整文件，或 AgentBridge 发起受控 artifact read 时，才读取完整内容。

### Skills

```json
{
  "id": "planning_and_task_breakdown",
  "stage": "plan",
  "priority": "P0",
  "role": "primary",
  "why": "将验收标准拆成可执行 slices。",
  "inputs": ["acceptance_criteria.md", "context_pack.md"],
  "outputs": ["planning/acceptance_coverage_matrix.json", "planning/tdd_plan.json"],
  "status": "recommended"
}
```

`status` 可为：

- `recommended`
- `used`
- `deferred`
- `not_applicable`
- `unknown`

### Tool Calls

```json
{
  "tool_call_id": "codex_exec_001",
  "tool_name": "codex exec",
  "provider": "codex",
  "node_id": "implementation",
  "status": "completed",
  "started_at": "",
  "finished_at": "",
  "input_summary": "使用 prompt bundle 生成本地应用。",
  "output_summary": "生成 diff 和 implementation trace。",
  "artifact_refs": ["codex/implementation_trace.json", "codex/diff.patch"],
  "risk_events": []
}
```

如果没有工具调用证据，节点必须显示 `未记录`。

### Usage

```json
{
  "prompt_tokens": "unknown",
  "completion_tokens": "unknown",
  "total_tokens": "unknown",
  "elapsed_ms": 1200,
  "estimated_cost": "unknown",
  "usage_source": "codex/stdout.jsonl"
}
```

规则：

- `rule` variant token 固定为 `0`。
- Codex/LLM usage 只使用真实可解析数据。
- 无 usage 记录时使用字符串 `unknown`。
- 不得根据字符数伪造 token 消耗。

### Scores

```json
{
  "product_effect": 0.82,
  "engineering_readiness": 0.9,
  "acceptance_coverage": 0.86,
  "risk_score": 0.1,
  "score_source": "deterministic_rubric_v1"
}
```

评分来源必须明确。v1 默认使用 deterministic rubric，不默认调用 LLM judge。

### Risks

```json
{
  "id": "no_secret_persistence",
  "severity": "warning",
  "summary": "PRD 中出现疑似 token，摘要已脱敏。",
  "artifact_refs": ["input_prd.md", "requirements/normalized_prd.md"]
}
```

风险不得隐藏在自然语言摘要中。

### Artifact Patch 契约

右侧 Agent 可直接改写 `runs/<run_id>/artifacts/<node>/*` 原文件。改写前必须写证据到 `runs/<run_id>/artifact_patches/<ts>__<node>__<file>.diff`，保留可回放记录。

```json
{
  "patch_id": "patch-artifact-001",
  "created_at": "2026-06-27T10:00:00Z",
  "target_node": "implementation",
  "target_file": "app_contract.json",
  "target_path": "artifacts/implementation/app_contract.json",
  "diff_path": "artifact_patches/1719478800__implementation__app_contract.json.diff",
  "summary": "修正路由缺失：新增 /api/health 和 /api/images/generate",
  "action_id": "abc123"
}
```

证据目录 `runs/<run_id>/artifact_patches/index.json`：

```json
{
  "patches": [
    {
      "ts": 1719478800,
      "node": "implementation",
      "file": "app_contract.json",
      "diff_path": "1719478800__implementation__app_contract.json.diff",
      "summary": "修正路由缺失",
      "action_id": "abc123",
      "applied_at": "2026-06-27T10:00:00Z"
    }
  ]
}
```

规则：

- Agent 焦点 = `file_preview` 时，可产出 `patch_artifact` action。
- `target_path` 必须在 `runs/<run_id>/artifacts/` 下；**禁止**改写 `runs/<run_id>/codex/` 目录下文件（Codex 内部状态不可直改，需走 `rerun_from_node`）。
- 改写前后端先写 diff 到 `artifact_patches/<ts>__<node>__<file>.diff`，更新 `index.json`。
- 下游节点读取时按 artifact 最新状态；rerun 上游节点会覆盖 artifacts/，但 `artifact_patches/` 保留可回放记录。
- `runs/<run_id>/app_patches/` 结构相同，`node` 字段固定为 `"app"`，用于记录应用预览增量修改（见 [`docs/app_generation_agent_bridge_spec.md`](docs/app_generation_agent_bridge_spec.md) § patch_app 契约）。

### Preview Status 扩展

当 `focus.card="app_preview"` 时，NodeContext 必须包含应用预览扩展字段，让 Agent 知道当前预览快照对应哪次发布 + 累计了多少 patch：

```json
{
  "preview_status": "running",
  "preview_url": "http://127.0.0.1:8788",
  "preview_health": "ok",
  "published_at": "2026-06-27T09:30:00Z",
  "source_commit": "abc123def",
  "app_patches_count": 3,
  "app_patches_invalidated": false
}
```

状态枚举：

- `not_published`：worktree 有应用但未发布到 `generated_apps/<slug>/`
- `stopped`：已发布但预览未启动
- `starting`：正在启动 server.js
- `running`：预览正常运行
- `degraded`：预览进程在但健康检查失败
- `failed`：启动失败

`app_patches_invalidated` 标记：

- rerun `implementation` 节点后，Codex 只更新 `runs/<run_id>/worktree/generated_apps/<slug>/`；已发布快照 `runs/<run_id>/generated_apps/<slug>/` 保持不变，但 `preview_status` 退回「未发布」，旧 `app_patches/` 保留但标记 `invalidated_by_rerun=true`。
- 用户需重新点「发布到预览」将新 worktree 拷到快照，才能启动预览。
- 前端预览面板显示「N 个历史补丁因重新生成已失效」。

Agent 转成 `AgentAction` 时的具体 action type（`patch_artifact` / `patch_app` / `rerun_from_node` / `suggest_input_patch`）选择规则见 [`docs/app_generation_agent_bridge_spec.md`](docs/app_generation_agent_bridge_spec.md) § 增量优化动作契约 → Action Type 选择规则。

## Context Revision

`context_revision` 必须由以下内容的稳定序列化结果计算：

- `run_id`
- `node_id`
- `selected_variant`
- 输入 artifact path 和 `content_hash`
- 输出 artifact path 和 `content_hash`
- skill ids 和状态
- tool call ids 和状态
- risks
- user overrides

用途：

- Agent message 必须携带 `context_revision`。
- 后端处理 Agent action 时必须检查 revision 是否仍然匹配。
- 如果 revision 过期，返回 `context_stale`，要求前端刷新。

## Agent Message 请求

```json
{
  "provider": "codex",
  "intent": "auto",
  "mode": "explain",
  "message": "帮我解释这个节点为什么验收覆盖不足。",
  "node_context": {
    "schema_version": 1,
    "context_id": "...",
    "context_revision": "sha256:..."
  },
  "interaction_context": {
    "schema_version": 1,
    "run_id": "app_generation-20260625",
    "node_id": "planning_tdd",
    "context_revision": "sha256:...",
    "focus": {
      "card": "outputs",
      "artifact_ref": "planning/tdd_plan.json",
      "selected_text": "",
      "view_mode": "artifact_preview"
    },
    "allowed_operations": [
      "explain",
      "read_artifact",
      "suggest_input_patch",
      "patch_artifact",
      "rerun_from_node"
    ]
  }
}
```

`mode` 是兼容字段。新实现应优先使用 `intent` 和 `interaction_context`。`intent` 可为：

- `auto`：让 AgentBridge 根据用户消息和当前 focus 决定操作。
- `explain`：解释当前节点、卡片或 artifact。
- `compare`：对比 variant 或产物。
- `edit`：建议修改输入或 override。
- `rerun`：建议从当前节点重跑。
- `clarify`：提出澄清问题。

`intent=auto` 的解析结果必须写入 `resolved_intent`。`resolved_intent` 是后端内部字段，可进入调试 metadata 或测试断言，不要求前端直接暴露。允许值包括：

- `explain_node`
- `explain_inputs`
- `explain_outputs`
- `read_artifact`
- `compare_variants`
- `suggest_input_patch`
- `patch_artifact`
- `patch_app`
- `rerun_from_node`
- `ask_clarification`

路由必须同时参考用户消息、`focus.card`、`focus.artifact_ref`、`selected_text` 和 `allowed_operations`。如果用户说“重新跑这个节点”，即使当前 `mode=explain`，只要 `rerun_from_node` 在 allowed operations 中，也必须解析为 `rerun_from_node`，不得继续按普通解释处理。

兼容 `mode` 可为：

- `explain`
- `compare`
- `edit`
- `rerun`
- `clarify`

## AgentInteractionContext

`AgentInteractionContext` 描述用户在中间区当前指向的对象。它解决“Agent 到底在回答哪个东西”的问题。

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
    "selected_text": "移动端空状态",
    "view_mode": "artifact_preview"
  },
  "allowed_operations": [
    "explain",
    "compare",
    "read_artifact",
    "suggest_input_patch",
    "patch_artifact",
    "select_variant",
    "rerun_from_node",
    "ask_clarification"
  ]
}
```

### Focus

`focus.card` 可为：

- `node_summary`：节点总览。
- `skill_routing`：Skill 路由卡片。
- `variants`：变体与对比卡片。
- `project_skills`：Project Skills 卡片。
- `inputs`：输入卡片。
- `outputs`：输出卡片。
- `tool_usage_scores_risks`：工具、usage、评分和风险卡片。
- `artifact_preview`：文件预览竖栏。

`focus.artifact_ref` 必须引用当前 `NodeContext.inputs` 或 `NodeContext.outputs` 中存在的 artifact。没有选中文件时为空。

`selected_text` 是用户在预览或卡片中选择的文本片段。它用于缩小讨论范围，不作为事实源。

### Allowed Operations

`allowed_operations` 由工作台根据当前节点、卡片、artifact 状态和权限计算。Provider 不得自行扩权。

| 操作 | 含义 | 是否改变事实源 |
| --- | --- | --- |
| `explain` | 解释当前节点、卡片或 artifact 摘要 | 否 |
| `compare` | 对比 variant、输入或输出 | 否 |
| `read_artifact` | 通过受控 artifact read 读取完整内容 | 否 |
| `suggest_input_patch` | 建议修改节点输入或 override | 否，确认后进入新 run 输入 |
| `patch_artifact` | 直接修改 `artifacts/<node>/<file>` | 是，确认后写 `artifact_patches/` 证据并覆写文件 |
| `patch_app` | 直接修改 `generated_apps/<slug>/<file>`（需先发布） | 是，确认后写 `app_patches/` 证据并触发两阶段重启 |
| `delegate_code_repair` | 把复杂应用修复委托给 Code Agent 生成可确认 patch | 是，确认后进入 CodeAgentExecutor，再回到 patch/diff/验证闭环 |
| `select_variant` | 选择当前显示或下游使用的 variant | 否，除非后续确认重跑 |
| `rerun_from_node` | 从节点创建新 run | 是，必须确认 |
| `ask_clarification` | 向用户提问 | 否 |

### 与 Context Revision 的关系

`AgentInteractionContext.context_revision` 必须等于 `NodeContext.context_revision`。如果不一致，后端返回 `context_stale`。

交互焦点变化本身不改变 `NodeContext.context_revision`，因为它不是节点事实源。只有 artifact 引用、hash、variant 或 override 变化时，`NodeContext.context_revision` 才变化。

## V2 Canvas Context 扩展

V2 生成画布规范见 [`docs/app_generation_canvas_experience_spec.md`](app_generation_canvas_experience_spec.md)，Runway Timeline 主体验规范见 [`docs/app_generation_runway_timeline_spec.md`](app_generation_runway_timeline_spec.md)。V2 在 `NodeContext` 之上增加只读画布投影、选中步骤上下文和选中对象上下文。

### CanvasObject 摘要

`NodeContext` 可以携带当前节点相关的 `canvas_objects` 摘要，用于右侧 Agent 和对象详情区理解业务对象。`canvas_objects` 是从 run artifacts 投影出来的只读摘要，不是新的事实源。

```json
{
  "canvas_objects": [
    {
      "object_id": "capability:image_generation.single",
      "object_type": "capability",
      "title": "单张图片生成",
      "summary": "用户可以基于选中的 Prompt 生成单张主图。",
      "status": "needs_attention",
      "owner_business_node": "验证业务能力",
      "source_refs": ["input_prd.md", "app_contract.json"],
      "artifact_refs": ["generated_apps/input-prd/public/app.js"],
      "evidence_refs": ["codex/app_runtime_verification.json"],
      "actions": ["explain_object", "repair_generated_app", "verify_capability"]
    }
  ]
}
```

规则：

- `canvas_objects` 只包含摘要和 refs，不包含完整源码、完整 artifact、完整 stdout、完整 prompt 或 secret。
- `object_id` 必须稳定，可跨节点引用。
- `object_type` 必须来自 V2 规范的固定枚举。
- `status` 必须来自 artifacts、preview status、evaluation artifacts 或 adjustment events，不得由前端随意伪造。
- 对象摘要变化不一定改变节点事实；只有其底层 artifact refs、hash、override 或 evaluation 变化时，`context_revision` 才变化。

### CanvasSelectionContext

`CanvasSelectionContext` 是 `AgentInteractionContext` 的 V2 扩展，用于描述用户当前选中的 BusinessStep 或业务对象。

```json
{
  "canvas_selection": {
    "selection_id": "capability:image_generation.single",
    "selection_type": "canvas_object",
    "object_type": "capability",
    "business_node": "验证业务能力",
    "focus_surface": "object_detail",
    "selected_text": "",
    "visible_related_objects": [
      "provider_config:openrouter",
      "preview_session:current",
      "capability_gap:gpt-image-1-not-configured"
    ],
    "allowed_actions": [
      "explain_object",
      "repair_generated_app",
      "verify_capability",
      "compare_versions"
    ]
  }
}
```

当用户选中 Runway Timeline 步骤时，`selection_type` 必须是 `flow_step`：

```json
{
  "canvas_selection": {
    "selection_id": "app_preview",
    "selection_type": "flow_step",
    "step_id": "app_preview",
    "step_type": "ui",
    "title": "可预览应用",
    "status": "needs_attention",
    "focus_surface": "step_detail",
    "runtime_nodes": ["preview_delivery"],
    "input_summary": [],
    "process_summary": [],
    "output_summary": [],
    "evidence_refs": ["app_publish.json", "preview/preview_run_record.json"],
    "visible_related_objects": [
      "preview_session:current",
      "capability_gap:gpt-image-1-not-configured"
    ],
    "allowed_actions": [
      "explain_step",
      "explain_step_io",
      "inspect_evidence",
      "delegate_code_repair"
    ]
  }
}
```

规则：

- `CanvasSelectionContext` 不属于节点事实源，焦点变化不写 run artifacts。
- `selection_id` 必须引用当前 run 的 `BusinessStep` 或 `CanvasObject`，不得引用跨 run 或未授权对象。
- `allowed_actions` 必须由 Dashboard 根据对象类型、run 状态、preview 状态和权限计算；Provider 不得自行扩权。
- 当 `selection_type="flow_step"` 时，右侧 Agent 默认围绕步骤的输入、执行过程、输出、证据和可操作项回答，而不是退回到内部工程 node id 解释。
- 当 `selection_type="canvas_object"` 时，右侧 Agent 默认围绕对象回答，而不是退回到节点解释。
- 用户编辑业务对象时，Agent 只能生成 `suggest_object_patch` / `edit_business_object`，确认后进入 user override 或新 run；不能直接覆盖旧 artifact。
- 用户在 `app_preview` step 报告运行错误、provider/model、生图、按钮、下载或局部迭代问题时，Agent 默认生成 `delegate_code_repair` 或受控 `patch_app`，不得只解释 `preview_delivery` 节点。

### 与 V1 字段关系

| V1 字段 | V2 投影 |
| --- | --- |
| `inputs` / `outputs` | `artifact` 对象、source refs、evidence refs |
| `skills` | `tool_call` / `tool_capability` 对象 |
| `tool_calls` | `tool_call` 对象 |
| `usage` | 对象详情的成本/耗时摘要 |
| `scores` | `capability`、`delivery_version` 或 `benchmark_result` 对象评分 |
| `risks` | `capability_gap` 或 `risk` 摘要 |
| `preview_status` | `preview_session` 对象 |
| `generated_app_capability_gaps` | `capability_gap` 对象 |
| `execution_progress` | `生成应用原型` 业务节点进度 |
| `code_repair_progress` | `repair_candidate` 对象进度 |

## Agent Message 响应

```json
{
  "message": "当前 planning_tdd 节点缺少移动端空状态验收。",
  "actions": [
    {
      "type": "suggest_input_patch",
      "target_node_id": "planning_tdd",
      "patch_summary": "补充移动端空状态验收。",
      "override_instructions": "在验收标准中增加移动端空状态和错误状态。"
    }
  ],
  "tool_calls": [],
  "usage": {
    "total_tokens": "unknown"
  }
}
```

Agent action 必须经过用户确认后才能进入 rerun payload。

## AgentAction 边界

AgentAction 是工作台可执行动作的唯一入口。右侧 Agent、Codex、PI-Agent 或其他 LLM 都只能提出动作，不能直接覆盖旧 artifact。

规则：

- 输入类变更进入 `user_overrides` 或新 run inputs。
- 输出和中间产物是事实 artifact；修改必须走 `patch_artifact`（先写 `artifact_patches/<ts>__<node>__<file>.diff` 证据，再覆写 `artifacts/<node>/<file>`）或 `rerun_from_node`（创建新 run）。
- 直接对已发布生成应用的修改必须走 `patch_app`（先写 `app_patches/<ts>__<file>.diff` 证据，再覆写 `generated_apps/<slug>/<file>` 并触发两阶段重启）。
- 复杂已发布应用修复必须走 `delegate_code_repair`，由 `CodeAgentExecutor` 读取完整受控上下文后生成可确认 patch；右侧 Agent 不直接写代码。
- 节点重跑必须创建新 run，并保留旧 run。
- PI Agent 的 tool call 结果只作为右侧 tool evidence，除非被归一化为 AgentAction 并由用户确认，否则不进入节点事实层。
