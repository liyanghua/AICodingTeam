# 能力运行时 PoC 闭环设计：Skill 编译 + Mock Runtime + 反馈回流

状态：草案 v0.1（待评审）  
范围：document-to-skill 编译器 + opportunity_insight benchmark + MockRuntimeExecutor + 反馈回流，一次性 PoC 玻璃箱  
不在本期做：真实数据源接入、生产化调度、LLM 在线生成、Eval 自动化平台

---

## 0. 文档目的

把"老师方法 → Skill 骨架"和"商家反馈 → Eval 样本 / 圈层参数"两条链路，在现有三件资产之间打通一个**确定性闭环**：

```text
benchmark.yaml + input/   ──①编译──▶  generated_skill_pack/  ──②评测──▶  benchmark_report
                                                │
                                                ③runtime
                                                ▼
                                          trace + evidence
                                                │
                                                ④反馈伪造
                                                ▼
                                  regression_cases.jsonl + profile/*
                                                │
                                                ⑤回流再编译
                                                ▼
                                       回到①（带新的阈值/规则/样本）
```

闭环目标只有一个：**在不接真实数据的前提下，让 rules / data_requirements / thresholds 的每次修改，可以被一份 benchmark 报告 + 一份 trace 报告稳定鉴别出来**。

---

## 1. 现状落差快照

### 1.1 编译器骨架落差

| 维度 | 现状（`document-to-skill` 旧编译器） | 期望（benchmark expected_file_tree） |
|---|---|---|
| 根目录 | `build/market_insight_skill/` | `generated_skills/ecommerce/opportunity_insight/` |
| 入口 | `SKILL.md` / `skill.yaml` | 一致 |
| 执行计划 | `workflow.dag.yaml` | `runtime/execution_plan.yaml` |
| 数据契约 | `data_requirements.yaml` | `contracts/data_contract.json` |
| 工具契约 | `tool_bindings.yaml` | `contracts/tool_contract.json` + `tools/tool_manifest.yaml` |
| 评测 | `eval_rules.yaml` | `evals/scoring_rubric.yaml` + `contracts/eval_contract.json` |
| 输出契约 | `output_schemas/*.json` | `contracts/output_schema.json` (单一聚合) |
| 知识层 | — | `knowledge/{claim_pack.md, strategy_rules.yaml, negative_cases.md}` |
| Prompt 层 | — | `prompts/{planner, executor, reviewer, failure_triage}.md` |
| 例子层 | — | `examples/{sample_input.json, sample_output.md, *_cases.jsonl}` |
| 错误策略 | — | `runtime/error_policy.yaml`、`runtime/guardrails.yaml` |
| App 层 | — | `app/{app_spec_template.json, ui_components.yaml}` |

结论：**IR 字段够，骨架展开缺**。本期只改"展开器"，不改 IR、不改 parser。

### 1.2 Runtime 落差

| 维度 | 现状 | 期望（本期） |
|---|---|---|
| 调度 | 顺序遍历 nodes，全部 success | 按 `depends_on` 拓扑序、保留 `pending/success/failed/skipped` |
| 数据获取 | 不调任何 tool，节点直接吐 `mock=true` | 节点声明 `data_requirement_ids` → 经 ToolResolver → 调 mock tool → 拿假数据 |
| Evidence | 无 | 每节点产 evidence stub，落 `runs/<run_id>/evidence/*.json` |
| Trace | `NodeTrace`（start/end/status） | 加 `tool_calls[]`、`evidence_ids[]`、`rule_hits[]`、`data_quality[]` |
| 失败降级 | 无 | `preferred → fallback → manual_upload`，命中 `error_policy.yaml` |
| 反馈回流 | 无 | trace + feedback fixture → `regression_cases.jsonl` / `profile/<id>/thresholds.yaml` |

---

## 2. 设计原则

- **IR 是收口，骨架是展开**：所有 benchmark 期望文件的字段，必须能从 `StrategyIR` 的现有字段派生；派生不出来的字段（如 `claim_pack.md` 正文）暂时走"种子文件直接拷贝 + 占位补全"，留 `TODO(parser-v0.2)` 标记。
- **Prompts 不直接说业务知识**：planner/executor/reviewer 的 prompt 只能引用 `rule_id` / `data_requirement_id` / `output_id` / `claim_id`，禁止内嵌业务结论。
- **Runtime 完全确定性**：mock tool 的输出由 `(tool_id, input_hash)` 决定，时间戳走注入的 clock，便于 trace 可 diff。
- **反馈不进 prompt**：商家反馈只落 `regression_cases.jsonl` 和 `profile/*/thresholds.yaml`，下一轮通过"改 IR 或改阈值"参与编译。
- **三件资产边界**：document-to-skill 只管编译；benchmarks/ 只管期望与样例数据；runtime + 反馈回流先放在 `glue/`（一次性 PoC），不进 `growth_dev/team/`。

---

## 3. 模块改造范围

### 3.1 SkillCompiler.compile_to_benchmark_shape()

- 新增方法（不删旧 `compile()`），位置 `document-to-skill-engineering-package/src/doc_to_skill/compiler.py`。
- 入参：`ir: StrategyIR`、`output_dir: Path`、`seeds: dict[str, Path]`（来自 benchmark `input/` 的种子文件）。
- 内部由若干 `_emit_*` 子例程组成，每个子例程对应 expected_file_tree 中一类文件，互相不共享可变状态。

```text
compile_to_benchmark_shape(ir, output_dir, seeds)
├─ _emit_skill_md(ir, output_dir/"SKILL.md")
├─ _emit_skill_yaml(ir, ...)
├─ _emit_readme(ir, ...)
├─ _emit_contracts/
│    ├─ input_schema.json     ← from ir.skill_inputs (新增, parser v0.2 之前用模板)
│    ├─ output_schema.json    ← 聚合 opportunity_card + evidence + score_breakdown + actions
│    ├─ data_contract.json    ← from ir.data_requirements
│    ├─ tool_contract.json    ← 由 data_contract 推导 + seeds/tool_manifest 增补
│    ├─ knowledge_contract.yaml ← 引用 claim_pack / rules id
│    └─ eval_contract.json    ← hard_gates + rubric 维度
├─ _emit_knowledge/
│    ├─ claim_pack.md         ← seeds["claim_pack_seed"] 拷贝 + 头部 id 列表
│    ├─ strategy_rules.yaml   ← from ir.rules
│    └─ negative_cases.md     ← seeds["negative_cases_seed"] 或占位
├─ _emit_prompts/{planner, executor, reviewer, failure_triage}.md
│    ← 全部从 ir 字段 + 模板渲染，正文只允许引用 id
├─ _emit_tools/tool_manifest.yaml   ← 从 ir.data_requirements + tool_resolver 结果生成
├─ _emit_examples/{sample_input.json, sample_output.md}
│    ← 取 seeds/sample_inputs/* 转成 contracts/input_schema 形状
├─ _emit_evals/{scoring_rubric.yaml, benchmark.yaml}
├─ _emit_runtime/{execution_plan.yaml, error_policy.yaml, guardrails.yaml}
└─ _emit_app/{app_spec_template.json, ui_components.yaml}
```

兼容旧 `compile()`：保留不动，旧测试不受影响；新增 `tests/test_compiler_benchmark_shape.py`。

### 3.2 ToolResolver 增强

- 位置：`document-to-skill-engineering-package/src/doc_to_skill/tool_resolver.py`
- 现状：只回 `selected_tool / fallback_tools / status`，不产 manifest。
- 增强：
  - 新增 `resolve_all(requirements) -> ToolResolutionReport`，输出可序列化的报告对象。
  - `ToolResolutionReport` 字段：

```text
ToolResolutionReport
├─ resolutions[]                  按 requirement.id 一条
│   ├─ data_requirement_id
│   ├─ preferred_tool_id / status (matched / missing_tool / mock_only)
│   ├─ fallback_tool_ids[]
│   └─ tool_contract_ref          指向 tool_registry 里的 tool_id
├─ tool_manifest                  适配 benchmark tool_manifest.yaml 的结构
│   └─ tools{tool_id: {mode, input_schema, output_schema, failure_modes, governance}}
└─ missing_tools[]                没有任何 registry 命中的 requirement
```

- `tool_manifest` 直接写到 `generated_skill_pack/tools/tool_manifest.yaml`。
- `missing_tools[]` 写到 `runs/<run_id>/missing_tools_report.md`，作为编译期警告，不阻塞。

### 3.3 ToolRegistry 扩展

- 位置：`document-to-skill-engineering-package/src/doc_to_skill/tool_registry.py`
- 现状：从 yaml 加载 `ToolContract`，按 tool_id 查找。
- 增强：
  - 新增 `MockToolBackend` 协议：

```text
MockToolBackend
├─ tool_id : str
├─ input_schema / output_schema : dict
├─ invoke(inputs: dict, run_ctx: RunContext) -> ToolCallResult
└─ deterministic_seed(tool_id, inputs) -> bytes   用于回放
```

  - 内置 backend：
    - `FixtureBackend(fixture_dir)`：从 `benchmarks/.../input/sample_inputs/*` 按 tool_id 映射读固定文件
    - `EchoBackend()`：把 inputs 原样 echo + 加 `mock=true` 标记
    - `FailingBackend(failure_mode)`：用于失败注入测试
  - Registry 内部维护 `{tool_id: ToolContract, backend?: MockToolBackend}`。

### 3.4 MockRuntimeExecutor 升级

- 位置：`document-to-skill-engineering-package/src/doc_to_skill/runtime.py`
- 现状：顺序遍历，全部 success，无 tool 调用。
- 升级要点：
  - 解析 `runtime/execution_plan.yaml` 的 `steps[]` 取代旧 `workflow["nodes"]`。
  - 拓扑排序 + 失败传播（前置 failed → 后置 skipped）。
  - 每个 step 执行四件事：
    1. 拉数据：根据 `data_requirement_ids` 找 ToolResolver 给出的 `tool_id`，调 backend。
    2. 触发规则：用 `step.rules` 中引用的 `rule_id` 跑确定性规则评估（先实现简单的 `count(...) >= N` 形式）。
    3. 生成 evidence：每个 claim 落 `EvidencePack` stub，写到 `runs/<run_id>/evidence/<step_id>/<evidence_id>.json`。
    4. 写 trace：升级 `NodeTrace` 字段。
  - 新 `NodeTrace`：

```text
NodeTrace
├─ node_id / status / started_at / ended_at
├─ tool_calls[]                每次工具调用
│   ├─ tool_id / inputs_hash / outputs_ref / latency_ms / status / error
├─ evidence_ids[]              本步产出的 evidence_id
├─ rule_hits[]                 命中的 rule_id 列表
├─ data_quality[]              required_fields 缺失数、null_ratio
└─ skip_reason / error
```

  - 新 `RuntimeResult`：

```text
RuntimeResult
├─ skill_run_id
├─ skill_pack_ref              指向哪个 generated_skill_pack
├─ profile_id                  本次跑用的圈层 profile（默认 default）
├─ traces[]
├─ outputs{step_id: ref}
├─ summary
│   ├─ steps_total / succeeded / failed / skipped
│   ├─ tool_calls_total / missing_tools
│   ├─ evidence_total
│   └─ rule_hit_total
└─ artifacts_dir               runs/<run_id>/
```

- 入口签名（建议）：

```python
MockRuntimeExecutor(registry: ToolRegistry, clock: Clock).execute(
    skill_pack_dir: Path,
    skill_inputs: dict,
    profile: Profile | None = None,
) -> RuntimeResult
```

### 3.5 Profile + 反馈回流（PoC 范围最薄）

- 位置：`glue/feedback/`（PoC 期一次性脚本，不进 `growth_dev/team/`）。
- 数据形状：

```text
runs/<run_id>/
├─ generated_skill_pack/              ① 编译产物
├─ benchmark_report.{json,md}         ② benchmark 评估
├─ evidence/                          ③ runtime 落的证据
├─ trace/run_trace.json               ③ runtime 落的 trace
├─ feedback/feedback.jsonl            ④ 伪造的商家反馈
├─ regression_cases.jsonl             ⑤ 由反馈派生的 eval 样本
└─ profiles/<profile_id>/
    ├─ thresholds.yaml                ⑤ 该圈层的阈值 override
    └─ scoring_rubric.override.yaml   ⑤ 该圈层评分维度权重 override
```

- `feedback.jsonl` 每条结构：

```text
feedback record
├─ run_id / skill_pack_ref / opportunity_card_id
├─ profile_id
├─ feedback_type            adopt / reject / edit / outcome
├─ targets[]                被反馈的 rule_id / data_requirement_id / output_field
├─ business_outcome?        7d/30d 的实际结果（GMV / 转化 / 售罄）
└─ note                     人工备注
```

- `feedback ingestor` 做的事：
  - 按 `feedback_type` 分桶 → 写 `evals/regression_cases.jsonl`（positive / negative / edge）。
  - 按 `targets` 聚合 → 修改 `profiles/<profile_id>/thresholds.yaml`（提供"+1/-1"档位变化，不做精算）。
  - 不动 IR、不动 prompts。下一轮编译时由 `compile_to_benchmark_shape` 合并 profile override。

---

## 4. 一次性闭环脚本 `glue/run_loop.py`

```text
run_loop.py（一次性 PoC，CLI: python -m glue.run_loop --benchmark <path>）
  step1  load benchmark.yaml + input/*
  step2  parser.parse(input/scenario_brief.md or business_context.md) → IR
  step3  SkillCompiler.compile_to_benchmark_shape(ir, runs/<ts>/generated_skill_pack, seeds=input/*)
  step4  BenchmarkRunner.check(generated_skill_pack, expected/, eval/)
            → benchmark_report.{json,md}
  step5  ToolRegistry.load_default_mocks(seeds=input/sample_inputs/)
         MockRuntimeExecutor.execute(generated_skill_pack, sample_input, profile=default)
            → trace + evidence + outputs
  step6  feedback fixture（人手写或脚本生成）→ feedback.jsonl
  step7  feedback_ingestor.ingest(trace, feedback) →
            regression_cases.jsonl + profiles/<id>/thresholds.yaml
  step8  rerun step3..step5 with profile override
            → 第二份 benchmark_report + 第二份 trace
            → diff 两轮报告，确认反馈是否真的改变了维度得分
```

成功判据（PoC 等级）：
- 两轮 benchmark_report 的 `dimension_scores` 有可解释的差异，且差异点恰好命中反馈所指 `targets`。
- 两轮 trace 的 `rule_hits` / `evidence_total` 有可解释的差异。
- 没有任何环节读 prompt 模板里被硬编码的业务结论。

---

## 5. 目录与依赖关系图

```text
repo root
├─ benchmarks/opportunity_insight_benchmark_pack/
│   └─ benchmarks/skill_creator/opportunity_insight/
│       ├─ benchmark.yaml / input/ / expected/ / eval/   ← 真理源（场景+期望）
│       └─ reference_skill_pack/                          ← 仅作 reference，不参与生成
│
├─ document-to-skill-engineering-package/
│   └─ src/doc_to_skill/
│       ├─ parser.py            （本期不动）
│       ├─ schemas.py           （本期不动；如需新增 SkillInputSpec 等再说）
│       ├─ compiler.py          （+ compile_to_benchmark_shape）
│       ├─ tool_registry.py     （+ MockToolBackend 协议、内置 backend）
│       ├─ tool_resolver.py     （+ resolve_all / ToolResolutionReport）
│       └─ runtime.py           （重写 MockRuntimeExecutor）
│
├─ glue/                                                  ← 新增，PoC 一次性胶水
│   ├─ run_loop.py
│   ├─ benchmark_runner.py     （读 benchmark.yaml / expected_file_tree / hard_gates / rubric）
│   ├─ feedback_ingestor.py
│   └─ profiles/
│       └─ default/thresholds.yaml
│
└─ runs/<ts>/                                             ← 每次跑产物
    ├─ generated_skill_pack/
    ├─ benchmark_report.{json,md}
    ├─ evidence/ / trace/ / feedback/
    └─ profiles/<id>/
```

依赖方向（单向）：

```text
benchmarks(真理源) ──▶ doc-to-skill(编译器+runtime) ──▶ glue(闭环胶水) ──▶ runs/(产物)
       ▲                                                                       │
       └────────── 反馈回流改 profile/regression_cases，不改 benchmarks ◀───────┘
```

---

## 6. 数据契约要点（写给 compiler 的检查表）

1. `contracts/data_contract.json` 必须含 `keyword_dataset` 与 `competitor_dataset` 的 required fields（hard_gates: `data_contract_complete`）。
2. `contracts/output_schema.json` 必须含机会卡字段：`title / target_audience / scene / pain_points / evidence / score / actions / risks`（hard_gates: `opportunity_card_schema_present`）。
3. `knowledge/claim_pack.md` 至少 5 条 claim，`knowledge/negative_cases.md` 至少 3 条（hard_gates: `knowledge_contract_grounded`）。
4. `tools/tool_manifest.yaml` 每个 tool 必须给 `input_schema / output_schema / failure_modes`（hard_gates: `tool_contract_defined`）。
5. `runtime/execution_plan.yaml` 必须按 "数据校验 → 标准化 → 分析 → 证据 → 机会卡 → 推荐" 顺序（hard_gates: `execution_plan_ordered`）。
6. `skill.yaml` 必须含 `rsi_feedback`（hard_gates: `rsi_feedback_defined`）。
7. `runtime/guardrails.yaml` 必须列禁止动作（hard_gates: `no_unsafe_action`）。

---

## 7. 风险与未解决问题

- **R-1（高）**：`StrategyIR` 当前没有 `skill_inputs / claims / negative_cases` 字段，benchmark 期望的 `input_schema` 与 `knowledge/*` 只能走"种子文件透传"。本期接受；下一期 parser v0.2 再补到 IR。
- **R-2（中）**：`rules.condition` 是字符串（如 `count(...) >= 2`），runtime 要在不引入新表达式引擎的前提下评估。本期实现"白名单算子 + 字段引用解析"的最小子集，复杂 condition 标记 `unevaluated` 不阻塞。
- **R-3（中）**：MockRuntime 的 `FixtureBackend` 输出格式与真实工具不同步会发散。约束：fixture 直接复用 benchmark `input/sample_inputs/*`，由 ToolContract 出口 schema 校验，错则报失败。
- **R-4（低）**：圈层 profile 与主 skill 的合并顺序需要明确。本期约定：`profile.thresholds.yaml` 在编译期覆盖 `strategy_rules.yaml` 的同 `rule_id` 阈值，不覆盖 rule.condition 表达式本身。

---

## 8. 验收清单（PoC 等级）

- [ ] `python -m glue.run_loop --benchmark benchmarks/opportunity_insight_benchmark_pack/benchmarks/skill_creator/opportunity_insight/` 一键跑通。
- [ ] `runs/<ts>/generated_skill_pack/` 通过 expected_file_tree 和 11 个 hard_gates 全部 pass。
- [ ] `runs/<ts>/benchmark_report.json` 总分 ≥ 70（PoC 阈值，低于线上 80）。
- [ ] `runs/<ts>/trace/run_trace.json` 中至少 6 个 step success、每步含 ≥1 tool_call 和 ≥1 evidence_id。
- [ ] 注入一条 `feedback_type=reject, targets=[rule:strong_hot_gene]` 的反馈后，第二轮 trace 的 `rule_hits` 中 `strong_hot_gene` 数量下降，benchmark `dimension:knowledge_contract_quality` 得分变化可解释。
- [ ] 全程未让 LLM 输出业务结论；所有结论字段都能追溯到 `tool_call → evidence → rule_hit` 的链路。

---

## 9. 评审征求意见

1. 闭环胶水 `glue/` 放根仓库，还是放 `document-to-skill-engineering-package/examples/loop/`？倾向前者（跨包胶水）。
2. `profiles/default/thresholds.yaml` 的字段粒度：是只覆盖 `rule_id → threshold_value`，还是允许覆盖 `rule_id → condition` 整段？倾向前者，更安全。
3. `feedback_ingestor` 写出的 `regression_cases.jsonl` 是放 `generated_skill_pack/evals/`（污染产物）还是放 `runs/<ts>/`（与生成物分离）？倾向后者，编译器永远不读 runs/。
4. MockRuntime 的失败注入策略是否纳入 PoC？建议纳入：至少跑一条 `FailingBackend` 路径，验证 `error_policy.yaml` 的 fallback 链。