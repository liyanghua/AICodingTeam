# CodeAgentExecutor 执行契约规范

## 状态

本规范把 `app_generation_agent_driven_repair_spec.md` 与 `app_generation_architecture.md` 已声明、但停在契约层的 `delegate_code_repair` 长期路线，落到可实现的执行契约。

本规范不引入新的代码修改权威。`CodeAgentExecutor` 是唯一代码修改执行层，Codex 是其默认且当前唯一 Provider；PI-code 或通用 LLM-code 未来必须作为同一抽象的 Provider 接入，不得在右侧对话面板里另起一套写文件链路。

当前基础实现已落地：Codex Provider、prepare/apply 端点、前端确认流和核心回归测试已经接入。后续 Provider 扩展、rollback 与提升为生成规则仍按本文契约继续演进；未实现的扩展能力不得在 UI 中暗示已经可用。

## 与既有规范的关系

- 路由与边界沿用 `app_generation_agent_bridge_spec.md`：trivial、单锚点可逐字定位的问题走 `patch_app`；复杂修复走 `delegate_code_repair`。
- 动作契约沿用 `app_generation_agent_bridge_spec.md` 的 `delegate_code_repair` / `repair_request` 与 `app_generation_acceptance_and_testing.md` AC-066。
- 修复目标沿用 `app_generation_node_context_contract.md`：当前已发布快照 `runs/<run_id>/generated_apps/<slug>/`，不是 worktree，也不是 `codex/` 原始输出。
- 证据与事件沿用 AC-063：每次成功 apply 写一条 `AdjustmentEvent`。
- 隔离 worktree、prompt/state/schema/stdout/stderr/diff/review/verification 落盘沿用 `AGENTS.md` Codex 编码规则与 `runs/<run_id>/codex/` 约定。

## CodeAgentExecutor 抽象

唯一接口：

```text
run_repair(repair_request, *, run_dir, repo_root, config) -> RepairResult
```

`repair_request`（由右侧 PI-Agent 产出，不含 old/new 字节）：

- `app_slug`：目标已发布应用。
- `problem`：用户反馈归纳出的问题陈述。
- `constraints`：硬约束，例如「只修改当前已发布应用」「不重跑 PRD」「保留现有工作流」「API key 只从服务端环境读取」。
- `expected_behavior`：期望可观察行为列表。
- `verification`：建议验证命令，取自 allowlist。

`RepairResult`：

- `status`：`prepared`（候选 diff 就绪，待 apply）/ `review_failed` / `failed`。
- `candidate_dir`：worktree 内被修改的 app 目录（`worktree/generated_apps/<slug>/`）。
- `diff_path`：候选 diff 文件路径。
- `changed_files`：本次改动文件相对路径列表。
- `verification_results`：每条验证命令的 `status` / `exit_code` / 截断输出。
- `risk_events`：脱敏后的风险事件。
- `blockers`：阻塞原因（缺二进制、worktree 准备失败、review 不过等）。
- `codex_artifacts`：`implementation_trace` / `slice_loop_state` / `stdout` / `stderr` 的 run-relative 引用。

Provider 注册：`{"codex": CodexCodeAgentProvider}`。Codex Provider 内部复用 `CodexExecutor`，不复制 worktree、子进程、diff 逻辑。

## 两阶段执行模型

代码修改权威唯一，但用户确认必须落在「看得到要改什么」之后。因此执行分两段，对应 `worktree -> promote` 写回方式。

### 阶段一 prepare（用户确认委托后触发）

1. 校验 `runs/<run_id>/generated_apps/<slug>/app_publish.json` 存在，否则返回 412 `app_not_published`。
2. 前端生成 `repair_id` 并传入 prepare 请求；后端立即写 `app_repairs/<repair_id>/progress_status.json` 和 `progress.jsonl`，使右侧 Agent 区可以在 prepare 长请求期间轮询进度。
3. `prepare_worktree()` 拿到隔离 worktree 后，把已发布 `generated_apps/<slug>/` 复制进 `worktree/generated_apps/<slug>/`，**排除 `app_publish.json` 与 `app_patches/`**（元数据不交给 Code Agent）。
4. 以 `allowed_paths=["generated_apps/<slug>"]` 运行 Code Agent 修复 coder。goal = `repair_request.problem` + `expected_behavior`，`constraints` 注入 prompt；上下文全部来自已发布源码与 run artifacts，不来自聊天历史。
5. 运行 allowlist 验证命令（`node --check server.js` 等）。
6. 产出 worktree diff = 候选 diff，等价于 dry-run，**未触碰 run 级 `generated_apps`**。
7. 返回 `RepairResult`（候选 diff + 验证结果 + codex trace 引用）。本阶段**不 promote、不重启 preview、不写 AdjustmentEvent**。

Prepare 期间的可观测契约见 [`docs/app_generation_codex_observability_spec.md`](app_generation_codex_observability_spec.md)。实现必须写入：

- `runs/<run_id>/app_repairs/<repair_id>/progress.jsonl`
- `runs/<run_id>/app_repairs/<repair_id>/progress_status.json`

右侧工作台通过以下只读 API 轮询：

```text
GET /api/app-generation/runs/<run_id>/delegate-code-repair/status?repair_id=<repair_id>
```

### 阶段二 apply（用户审完候选 diff 再次确认后触发）

7. 把 `worktree/generated_apps/<slug>/` promote 回 `runs/<run_id>/generated_apps/<slug>/`，复用 `publish_app_generation_run` 的拷贝逻辑。
8. 写证据：`runs/<run_id>/app_patches/<ts>__delegate.diff` 与更新 `app_patches/index.json`（记 `provider=codex`、`repair_request`、`verification`）。
9. Dashboard 重写 `app_publish.json` 追加 repair 溯源。该文件由框架维护，Code Agent 不得改动。
10. 若 preview 正在运行，执行两阶段重启；新版本起不来则保留旧 preview（`restart_keep_old_state`）。
11. 写 `AdjustmentEvent`：`resolved_intent=delegate_code_repair`、`patch_status=applied`、`verification_status`、`rollback_available`、`diff_refs`、`preview_status`。

## 失败与安全语义

- 阶段一失败（codex 缺二进制 / review 不过 / 验证失败）：`status=failed|review_failed`，返回 `risk_events` 与 `blockers`，**不进入阶段二，旧 `generated_apps/<slug>/` 原样不动**。
- 用户在阶段二前取消：丢弃 worktree 候选，不写任何成功态证据，不写 `AdjustmentEvent` 成功态。
- 候选过期：若同一应用发起了新的 prepare，旧候选作废；旧候选的 apply 返回 409。
- Code Agent 禁止触碰：`app_publish.json`、`codex/`、worktree 外路径、`.env`、仓库源码、`node_modules`；越权路径在 `allowed_paths` 校验处拒绝。
- Code Agent 如果修改 `worktree/tests/`、仓库源码或其他 `worktree/generated_apps/<slug>/` 之外的文件，prepare 必须失败并记录 `outside_repair_scope_changes`，旧已发布应用保持不变。
- secret 不进 prompt、不进 run artifacts、不进 diff、不进前端。

## 端点契约

- `POST /api/app-generation/runs/<run_id>/delegate-code-repair`（阶段一 prepare）→ 候选 diff + `RepairResult`。
- `GET /api/app-generation/runs/<run_id>/delegate-code-repair/status?repair_id=<repair_id>`（prepare 可观测）→ progress status + latest events。
- `POST /api/app-generation/runs/<run_id>/delegate-code-repair/apply`（阶段二）→ promote + verify + 两阶段重启 + `AdjustmentEvent`。
- 错误码：412 `app_not_published`；409 候选过期（worktree 被新 prepare 覆盖）。

## 与 patch_app 的分界（不变）

| 场景 | 路径 | 确认 |
| --- | --- | --- |
| trivial 单 token / 单锚点可逐字定位（换模型名、改文案、单点配置） | `patch_app` 字符串替换 fast-path | 单次确认 |
| 多文件 / 加功能 / 改逻辑 / 跨函数联动 / 说不清具体行 | `delegate_code_repair` + CodeAgentExecutor | 两段确认（委托 + 候选 diff） |

右侧 PI-Agent 在两条路径中都只产出结构化动作，不直接写文件、不直接起进程、不直接读 secret、不直接改 worktree 或 `codex/` 原始输出。

## 范围外

- 本规范不覆盖 `rollback_patch` 与 `promote_patch_to_generation_rule` 的执行细节（沿用 `app_generation_agent_driven_repair_spec.md`，单独实现）。
- 本规范不引入除 Codex 外的 Code Agent Provider；新增 Provider 时必须满足同一 `run_repair` 接口与两阶段语义。
