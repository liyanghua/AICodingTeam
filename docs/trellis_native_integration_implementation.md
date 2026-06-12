# Trellis-Inspired Native Integration 实施规范

## 背景

本规范用于把 Trellis 的 Plan / Implement / Verify / Finish 循环思想原生吸收到当前 AI-Team Runtime 中。本项目不直接引入 Trellis CLI，也不创建 `.trellis/` 目录，而是在现有 `runs/<run_id>/`、`domains/`、`skills/`、Dashboard 和 Codex executor 基础上增加任务连续性与可观测层。

## 目标

实现三个新增能力：

- `task_workspace`：回答当前 run 处在哪一步、关注什么、下一步是什么。
- `task_journal`：记录从需求到交付的结构化任务日记。
- `tool_context/codex.md`：从 official artifacts 生成 coding 工具可读上下文，但不替代现有 Codex prompt bundle。

## 非目标

- 不接入 Trellis CLI。
- 不创建 `.trellis/`。
- 不改变现有 Codex executor 核心执行策略。
- 不自动把 historical memory 注入 Codex prompt。
- 不自动修改 `domains/<domain_id>/capabilities.yaml` 或 Project Skills。
- 不改变 Release / PR / CI / Staging / Production Gate 行为。

## Loop 映射规范

| Loop Phase | AI-Team 对应阶段 | 核心产物 |
|---|---|---|
| Plan | 需求理解、能力边界、AC、coverage、TDD plan、slices | `requirements/*`, `acceptance_criteria.md`, `planning/*`, `slices/*.yaml` |
| Implement | Codex coding、slice-loop、diff、trace | `codex/*`, `codex/slices/*/slice_trace.json` |
| Verify | completion gate、review、test、publish gate | `implementation_completion_gate.*`, `review_report.md`, `test_report.md` |
| Finish | acceptance、retrospective、memory、release/staging/production 判断 | `final_report.md`, `learning_summary.json`, `memory_recall.*`, readiness artifacts |

## Artifact Contract

### `task_workspace.json`

```json
{
  "schema_version": 1,
  "run_id": "",
  "generated_at": "",
  "loop_phase": "plan|implement|verify|finish",
  "objective": "",
  "domain_id": "",
  "task_type": "",
  "current_focus": "",
  "acceptance_criteria": [],
  "capability_boundary": {},
  "slices": {
    "active": null,
    "completed": [],
    "pending": [],
    "blocked": []
  },
  "gates": [],
  "blockers": [],
  "warnings": [],
  "verification_commands": [],
  "artifact_links": [],
  "next_actions": []
}
```

### `task_journal.jsonl`

每行一个事件：

```json
{
  "schema_version": 1,
  "run_id": "",
  "timestamp": "",
  "loop_phase": "plan|implement|verify|finish",
  "event": "",
  "status": "",
  "summary": "",
  "evidence": [],
  "blockers": [],
  "warnings": []
}
```

### `tool_context/codex.md`

必须包含：

- Overall goal
- Current loop phase
- Current slice
- Acceptance criteria
- Capability boundary
- Allowed paths
- Stop conditions
- Verification commands
- Blockers / warnings
- Artifact links

不得包含：

- raw prompt
- raw stdout/stderr
- full diff
- `.env`
- token / API key / DSN / provider secret

## 实施任务拆解

### Task 1：定义 Workspace / Journal 基础模块

输入：现有 run artifact 结构、loop 映射、安全脱敏规则。

过程：新增 workspace 生成模块，定义 contract 常量，实现基础 redaction helper，为缺失 artifact 提供 warning。

输出：Workspace / Journal contract、redaction helper、初始单测。

验收：contract 字段完整；缺失 artifact 不导致崩溃；secret/redaction 测试通过。

### Task 2：生成 `task_workspace.json/md`

输入：`team_run_record.json`、`requirements/*`、`acceptance_criteria.md`、`planning/*`、`slices/*.yaml`、`codex/slice_loop_state.json` 和后续 gate/report artifacts。

过程：聚合 run 当前状态，推导 `loop_phase`，汇总 slices、gates、blockers、warnings、next actions，并输出 JSON 和 Markdown。

输出：`runs/<run_id>/task_workspace.json`、`runs/<run_id>/task_workspace.md`。

验收：completed run 能展示完整主线；failed run 能展示失败阶段和下一步；输出不包含 raw logs、full diff、raw prompt、secret。

### Task 3：生成 `task_journal.jsonl/md`

输入：run events、slice-loop state、gate/report artifacts、acceptance/release/staging/production artifacts。

过程：从 artifacts 提取关键阶段事件，写入结构化 journal，实现幂等刷新，生成 Markdown 时间线。

输出：`runs/<run_id>/task_journal.jsonl`、`runs/<run_id>/task_journal.md`。

验收：多次 refresh 不重复写事件；journal 能还原主线执行过程；failed / blocked / completed run 都有可读摘要。

### Task 4：生成 `tool_context/codex.md`

输入：`task_workspace.json`、official requirements/planning artifacts、current slice / allowed paths / verification commands。

过程：从 workspace 生成 Codex 可读上下文，不改变现有 Codex prompt bundle。

输出：`runs/<run_id>/tool_context/codex.md`。

验收：文件能独立说明当前 coding 任务上下文；不包含 raw memory、raw prompt、full diff、secret；Codex executor 现有行为不变。

### Task 5：新增 CLI

输入：`run_id`、`runs_dir`、workspace generator。

过程：增加 `team workspace refresh` 和 `team workspace show`，支持 `--json`，缺失 run 返回明确错误。

输出：

```bash
python3 -m growth_dev.cli team workspace refresh --run-id <run_id>
python3 -m growth_dev.cli team workspace show --run-id <run_id>
python3 -m growth_dev.cli team workspace show --run-id <run_id> --json
```

验收：`refresh` 生成 workspace、journal、tool context；`show --json` 输出符合 schema；缺失 run 非 0 退出且错误清晰。

### Task 6：接入 Dashboard

输入：workspace artifacts、Dashboard run state、timeline nodes。

过程：`GET /api/runs/<run_id>` 返回 `task_workspace` 和 `task_journal` 摘要；Artifact list 增加 workspace、journal、tool context；Timeline 节点展示对应 phase 的 workspace 信息。

输出：Dashboard 中每个流程节点都有任务上下文摘要，中间详情区能看到当前关注点、阻塞和下一步。

验收：需求理解、方案设计、AI 实现、质量检查、交付验收节点都有对应 workspace 信息；失败节点能清楚显示 blocker 和 next action；Dashboard 不因 workspace 缺失而报错。

### Task 7：增强 Finish Learning Loop

输入：retrospective、learning summary、capability boundary、failure classification。

过程：在 Finish 阶段生成能力更新建议、Project Skill hint 建议和 failure classification 建议；不自动修改正式规则文件。

输出：`finish_learning_suggestions.json`、`finish_learning_suggestions.md`。

验收：completed run 能看到沉淀建议；failed run 能看到失败分类建议；不自动改 `domains/` 或 `skills/`。

## 测试规范

定向测试：

```bash
python3 -m unittest tests.test_team_workspace -v
python3 -m unittest tests.test_team_runtime -v
python3 -m unittest tests.test_dashboard -v
```

回归测试：

```bash
python3 -m unittest tests.test_team_memory -v
python3 -m unittest tests.test_codex_executor -v
python3 -m unittest discover -s tests -v
```

必测场景：

- 空 run / artifact 缺失。
- completed run。
- failed run。
- blocked requirement gate。
- slice-loop failed。
- release/staging/production artifacts 已存在。
- 输出脱敏。
- CLI JSON schema。
- Dashboard timeline 展示。

## 验收标准

- 新 run 自动或手动 refresh 后能生成 `task_workspace.json/md`、`task_journal.jsonl/md` 和 `tool_context/codex.md`。
- Dashboard 能在流程节点内展示任务工作台摘要。
- CLI 能查看 workspace。
- Finish 阶段能生成学习沉淀建议。
- 不引入 Trellis runtime dependency。
- 全量测试通过。
