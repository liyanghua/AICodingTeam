# PRD 生成应用 Agent 驱动修复闭环规范

## 状态

本文档定义 `PRD生成应用` 工作台中“用户通过右侧 Agent 对话修复不可用应用”的规范。当前仍是规范阶段；除非对应 API、前端和测试明确实现，否则不得在 UI 中暗示能力已经可用。

本规范不是手工修复指南。用户对已发布应用的调整必须通过右侧 Agent 产生结构化动作，再由工作台框架执行、验证、记录和回滚。

## 目标

- 让用户在预览应用出错时，通过自然语言提出修复诉求。
- 让右侧 Agent 把诉求归一化为可确认的 `AgentAction`。
- 让框架负责 dry-run、diff、用户确认、apply、验证、预览重启、证据记录和回滚。
- 让高频应用调整沉淀为可观察的 `adjustment_events`，而不是只留在聊天记录中。
- 让成功的局部修复可以被用户选择“提升为生成规则”，用于后续模板、benchmark 或 verifier 改进。

## 职责边界

### Agent 负责

- 理解用户反馈，例如“单张图报 `gpt-image-1 · not configured`，改成 `openai/gpt-5.4-image-2`”。
- 结合 `NodeContext`、`AgentInteractionContext`、`AppPreviewContext` 判断问题来源。
- 选择最小动作：当前预览应用问题默认 `patch_app`；节点产物问题走 `patch_artifact`；PRD、契约或规划缺失才 `rerun_from_node`。
- 生成结构化 `AgentIntent` 和 `AgentAction`，包括 PatchSet 目标、保留能力、风险摘要和验证方式。
- 解释 dry-run diff，帮助用户决定是否确认。
- 在 patch 成功后建议是否提升为上游生成规则。

### 框架负责

- 提供事实源：run、节点、产物、预览状态、provider health、日志摘要、能力缺口和可 patch 文件清单。
- 控制读取边界：默认只给 Agent 摘要和引用，完整文件通过受控读取。
- 执行 patch：路径校验、dry-run、diff、用户确认、事务写入和证据落盘。
- 执行验证：语法检查、runtime smoke、preview health、provider health 和能力扫描。
- 管理预览：patch 后两阶段重启；新版本启动失败时保留旧预览。
- 记录历史：写入 `app_patches/`、`adjustment_events`、验证结果和 rollback 信息。
- 执行回滚：用户确认后恢复到 patch 前快照。

Agent 不直接写文件，不直接启动进程，不直接读取 secret，不直接修改 worktree 或 `codex/` 原始输出。

## 修复闭环

标准流程：

1. 用户打开应用预览，`focus.card="app_preview"`。
2. 用户描述问题，例如“生成单张图时报 `gpt-image-1 · not configured`”。
3. AgentBridge 根据 focus 和文本解析 `AgentIntent`。
4. Provider 生成自然语言回复和结构化动作；若 Provider 只返回自然语言建议，AgentBridge 必须用 deterministic fallback 生成可执行动作。
5. 框架对 `PatchSet` 执行 dry-run，返回整体 diff、目标文件、风险和验证计划。
6. 用户确认。
7. 框架应用 patch，写 `app_patches/` 证据。
8. 若 preview 正在运行，框架执行两阶段重启。
9. 框架执行验证并写 `VerificationResult`。
10. 工作台新增 `AdjustmentEvent`，节点流展示“应用调优”。
11. 成功后，Agent 可建议 `promote_patch_to_generation_rule`，但必须由用户确认。

## AgentIntent

`intent=auto` 时，AgentBridge 必须优先根据 `AgentInteractionContext.focus` 判断问题对象。

| Intent | 触发场景 | 默认动作 |
| --- | --- | --- |
| `diagnose_app_bug` | app preview 下报告运行错误、按钮无响应、下载失败、局部迭代失败 | 先诊断，再给 `patch_app` 或 `verify_patch` |
| `patch_app` | app preview 下要求改模型、provider、按钮、文案、UI、小范围交互 | `patch_app` |
| `verify_patch` | 用户要求“验证一下”“跑 smoke”“看看修好没” | `verify_patch` |
| `rollback_patch` | 用户要求“撤回刚才修改”“恢复上一版” | `rollback_patch` |
| `promote_patch_to_generation_rule` | 用户要求“以后生成也这样”“沉淀到模板” | `promote_patch_to_generation_rule` |
| `rerun_from_node` | PRD、契约、规划或实现节点本身缺能力 | `rerun_from_node` |

典型关键词：

- 运行错误：`报错`、`not configured`、`timeout`、`500`、`按钮没反应`。
- 图片生成：`生图`、`生成单张图`、`批量生成`、`模型`、`OpenRouter`、`API key`。
- 高频微调：`改文案`、`加选项`、`换默认值`、`下载失败`、`局部迭代`、`样式不对`。

当 `focus.card="app_preview"` 且用户消息命中以上任一类，`auto` 不得退化为 `explain_node`。

## PatchSet

`patch_app` 可以是单文件动作，也可以携带 `patches[]` 批量动作。批量动作必须作为一个事务执行。

```json
{
  "type": "patch_app",
  "summary": "修复图片 provider/model 默认配置",
  "source": "agent_bridge",
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

规则：

- `target_path` 必须以 `generated_apps/<slug>/` 开头，且不得指向 `app_publish.json`、`codex/`、worktree 或仓库任意路径。
- `edit_kind` v1 支持 `replace_block`、`append`、`create_file`、`replace_text`。
- `replace_text` 必须精确匹配 `old_content`，否则整个 PatchSet dry-run 失败。
- dry-run 不写文件，只返回 diff、风险和验证计划。
- apply 必须先校验所有 patch，再写任何文件；任一 patch 失败则不写文件。
- apply 成功后写 `runs/<run_id>/app_patches/<ts>__<file>.diff` 和 `app_patches/index.json`。
- patch 后若 preview 正在运行，必须触发两阶段重启。

## AdjustmentEvent

每次用户通过 Agent 调优应用，都必须写入可观察事件。

```json
{
  "schema_version": 1,
  "event_id": "adjustment-20260627T120000Z",
  "type": "app_adjustment",
  "run_id": "app_generation-...",
  "app_slug": "input-prd",
  "user_message": "把单张生图模型改成 gpt-5.4-image-2",
  "resolved_intent": "patch_app",
  "agent_provider": "pi_agent",
  "patch_status": "applied",
  "verification_status": "passed",
  "rollback_available": true,
  "diff_refs": ["app_patches/20260627__server_js.diff"],
  "preview_status": {
    "restart_status": "switched",
    "url": "http://127.0.0.1:8799"
  }
}
```

工作台节点流应把 `AdjustmentEvent` 展示为“应用调优”事件。用户点击后可以查看用户输入、Agent 判断、PatchSet diff、验证结果、预览状态和回滚入口。

## Provider/Model 配置修复案例

`gpt-image-1 · not configured` 是通用 provider/model 配置问题，不是 Dingdang 专用逻辑。

目标修复行为：

- 服务端读取 `IMAGE_PROVIDER=openrouter`。
- 服务端优先使用 `OPENROUTER_IMAGE_MODEL=openai/gpt-5.4-image-2`。
- 前端模型下拉能显示并选择 `openai/gpt-5.4-image-2`。
- `/api/health` 返回 provider、configured、model 和可行动错误摘要。
- API key 只从服务端环境读取，不进入前端、localStorage、Agent prompt、run artifacts、logs API 或 SSE。

若 patch 成功，Agent 可以建议“提升为生成规则”，让后续 app_generation 模板、benchmark metadata 和 verifier 默认覆盖该规则。

## 回滚

`rollback_patch` 必须是用户确认动作。

规则：

- 回滚目标来自 `app_patches/index.json` 中的 patch 记录。
- 回滚前生成 reverse diff dry-run。
- 用户确认后恢复文件，写 `rollback` 类型的 `AdjustmentEvent`。
- 若 preview 正在运行，回滚后也走两阶段重启。
- 回滚失败不得删除原始 patch 证据。

## 提升为生成规则

`promote_patch_to_generation_rule` 不直接修改上游代码。它只创建候选记录，用于后续人工审核或专门实现任务。

候选记录至少包含：

- 原始用户问题。
- PatchSet 摘要。
- 成功验证结果。
- 适用条件，例如“图片生成类 PRD + OpenRouter provider”。
- 建议修改位置，例如模板、benchmark capability、verifier 或 docs。

该动作不得自动改 `growth_dev/team/app_generation.py`、benchmark metadata 或测试代码。
