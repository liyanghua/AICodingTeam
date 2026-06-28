# PRD 生成应用对比与 Usage 规范

## 状态

本文档定义 `PRD生成应用` 工作台的 rule vs Codex/LLM 对比、产品效果评分和 token/usage 统计口径。该能力处于 spec-first 阶段，当前仓库尚未实现 comparison API、usage 聚合或产品效果评分 UI。

## 对比目标

用户需要知道每个节点为什么得出当前结果，以及不同执行策略在产品效果、工程可执行性、风险和成本上的差异。

对比不是为了让 rule 生成最终应用代码。代码实现节点固定走 Codex 或 LLM。rule 只用于 baseline、结构化检查、评分、风险扫描和对照。

## Variant

每个节点可有多个 variant。

- `rule`：确定性规则产物或检查结果。
- `codex`：Codex executor 产物。
- `llm`：通用 LLM 产物。
- `pi_agent`：spec-only 占位。PI 仅作为右侧 Agent 对话 Provider，不参与节点编排，节点对比表中该列值固定为 `not_available`。

v1 必须至少支持 `rule` 和 `codex` 的展示口径。缺少真实 agent 产物时，显示 `not_available`，不得伪造。

## 节点对比结构

```json
{
  "node_id": "planning_tdd",
  "title": "验收与 TDD 规划",
  "selected_variant": "codex",
  "variants": [
    {
      "variant_id": "rule",
      "strategy": "rule",
      "status": "completed",
      "outputs": [],
      "usage": {},
      "scores": {},
      "risks": []
    },
    {
      "variant_id": "codex",
      "strategy": "codex",
      "status": "completed",
      "outputs": [],
      "usage": {},
      "scores": {},
      "risks": []
    }
  ],
  "comparison": {
    "summary": "codex 输出更细，rule 更稳定且无 token 成本。",
    "recommended_variant": "codex",
    "reasons": []
  }
}
```

## Rule 职责

rule 可以做：

- artifact 是否存在。
- schema 是否可解析。
- `app_contract.json` 是否符合 v1 技术形态。
- allowed paths 是否越界。
- secret、数据库、外部部署、隐藏网络调用风险扫描。
- 验收标准覆盖矩阵基础评分。
- usage baseline：token 为 0。

rule 不做：

- 生成最终应用代码。
- 替代 Codex/LLM 的实现节点。
- 覆盖旧 artifact。
- 声称具备真实模型理解能力。

## Codex/LLM 职责

Codex/LLM 可以做：

- 增强 PRD 理解候选。
- 对节点产物提出改写建议。
- 在 `implementation` 节点生成本地应用代码。
- 对 rule 与 agent 输出做解释和对比。
- 生成待确认的重跑说明。

Codex/LLM 不得：

- 绕过 isolated worktree。
- 绕过 review、verification 或 apply gate。
- 直接写旧 run artifacts。
- 在 usage 不存在时伪造 token。

## Usage 口径

### Usage JSON

```json
{
  "prompt_tokens": 1200,
  "completion_tokens": 800,
  "total_tokens": 2000,
  "elapsed_ms": 8400,
  "estimated_cost": "unknown",
  "model": "gpt-5.3-codex",
  "provider": "codex",
  "usage_source": "codex/stdout.jsonl",
  "confidence": "observed"
}
```

### 规则

- `rule` variant：`prompt_tokens=0`、`completion_tokens=0`、`total_tokens=0`。
- Codex/LLM：只使用 provider 或 CLI 输出中的真实 usage。
- 缺失 usage：字段值为 `unknown`。
- 估算成本缺少价格表时为 `unknown`。
- 不得根据字符数或文件大小伪造 token。

### 优先来源

Codex usage 优先解析：

1. `codex/stdout.jsonl`
2. `codex/last_message.json`
3. `codex/implementation_trace.json`
4. `code_run_record.json`

Requirements model usage 优先解析：

1. `requirements/requirements_model_response.json`
2. `requirements/requirements_model_error.json`
3. `requirements/brief_analysis.json`

PI-Agent usage 分两条独立路径，互不混算：

- **节点 variant `pi_agent`（中栏对比表）**：v1 保持 spec-only，节点流不调用 PI；该列值固定为 `not_available`，不参与节点对比的 `recommended_variant` 计算。
- **右侧对话 usage**：由 `PiAgentProvider` 从 `agent_end.payload.usage` 解析（pi 透传的真实 provider usage，例如 anthropic / openai / aicodemirror 上报的 prompt/completion/total tokens）。

右侧对话 usage 解析优先来源：

1. `agent_end.payload.usage`：pi 在每个回合终态吐出的 usage 包，含 provider 真实 token 统计。
2. `response{success:true}` 包顶层 usage 字段（pi 协议演进保留位）。
3. 以上都缺失时 `unknown`，**不得** 用字符长度或 message_delta 数量近似。

右侧对话 usage 不写入 `runs/<id>/usage_summary.json`，不进入节点聚合，仅显示在右侧 Agent 区的当前回合气泡上。

## Usage Summary

后续实现可生成聚合 artifact：

```json
{
  "schema_version": 1,
  "run_id": "app_generation-20260625",
  "total_usage": {
    "total_tokens": "unknown",
    "elapsed_ms": 12000,
    "estimated_cost": "unknown"
  },
  "nodes": []
}
```

`usage_summary.json` 是聚合结果，不替代原始 provider 记录。

## 产品效果评分

v1 默认使用 deterministic rubric。

评分维度：

- `goal_clarity`：目标是否清晰。
- `scope_boundary`：范围内、范围外、假设、blocker 是否明确。
- `acceptance_coverage`：验收标准是否覆盖 PRD 关键路径。
- `engineering_readiness`：是否具备可实现输入、allowed paths 和验证命令。
- `ui_fit`：生成 UI 是否贴近 PRD 的核心流程和状态。
- `risk_score`：风险事件和 blocker 数量及严重度。

聚合分：

```json
{
  "product_effect": 0.82,
  "engineering_readiness": 0.9,
  "acceptance_coverage": 0.86,
  "ui_fit": 0.78,
  "risk_score": 0.1,
  "score_source": "deterministic_rubric_v1"
}
```

## LLM Judge

LLM judge 是后续增强，不是 v1 默认能力。

如果接入 LLM judge，必须：

- 单独记录 judge prompt。
- 单独记录 usage。
- 明确 judge 只是评分建议，不替代 deterministic gates。
- 不把 judge 结论作为 apply gate 的唯一依据。

## Comparison Group

同一 PRD 的多次 run、不同节点重跑、不同 Provider 输出必须归入 comparison group。

字段：

- `comparison_group_id`
- `source_run_id`
- `rerun_from_node`
- `selected_variant`
- `override_instructions`

comparison group 只用于对照和追踪，不改变 Team Runtime 的确定性执行边界。

