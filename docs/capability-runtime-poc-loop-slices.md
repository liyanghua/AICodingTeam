# 能力运行时 PoC 闭环：实现切片清单

配套文档：`docs/capability-runtime-poc-loop-design.md`  
状态：草案 v0.1（待评审；切片粒度按 Codex slice-loop 单次可消化）  
默认选项（来自设计文档 §9，可单点翻）：
- 闭环胶水位置：根仓库 `glue/`
- profile 阈值粒度：仅覆盖 `rule_id → threshold_value`
- `regression_cases.jsonl` 落位：`runs/<ts>/`（不污染 `generated_skill_pack/`）
- 失败注入：纳入 PoC（至少跑一条 FailingBackend 路径）
- **claim_pack / negative_cases 缺失策略**（评审 1 冻结）：placeholder + warning。缺失字段以显式 sentinel `<MISSING:source_field>` 写入产物，同时在 `runs/<run_id>/missing_fields_report.md` 留一行（含 `source_field / required_min / actual_count / seed_file_ref`），compile **不阻塞**；hard_gate `knowledge_contract_grounded` 若实际计数不足按原 gate 规则失败（与 placeholder 策略解耦）
- **rule condition evaluator 白名单**（评审 2 冻结）：`count(...) >= N` / `>=` / `<=` / `>` / `<` / `==` / `!=` / `and` / `or` / `field_ref`；不支持 `not` / `in` / 算术运算；超出白名单的 condition 标 `rule_hit=unevaluated` 但不阻塞 step
- **feedback fixture 反馈类型**（评审 3 冻结）：PoC 仅支持 `adopt / reject / edit` 三类，`business_outcome` 留 P1。`edit` 必须携带 `original_text / edited_text / target_path`；其余字段（`reason / reviewer_id / timestamp`）三类共用
- **PR-1 切分粒度**（评审 4 冻结）：不拆 emitter 为独立 PR；按 `skill_pack_emitters/` 子包一次性合并（slice 1.1~1.8 仍按现粒度走 Codex slice-loop）
- placeholder ≠ 编造：sentinel 必须形如 `<MISSING:...>`，禁止生成"35%""GMV 1.2 亿"等具体业务数值；编造业务字段值仍是 stop condition

---

## 0. 切片总览

```text
PR-1  编译器骨架对齐 (compile_to_benchmark_shape)
PR-2  工具层增强    (ToolRegistry + MockToolBackend + ToolResolver.resolve_all)
PR-3  Runtime 升级  (拓扑/tool接入/evidence/trace)
PR-4  闭环胶水      (glue/run_loop + benchmark_runner + feedback_ingestor + profile)
```

依赖：PR-1 → PR-2 → PR-3 → PR-4（严格串行）。前一个 PR 的契约不稳定，后一个不能开工。

通用规则（每个 PR 都遵守）：
- 不删旧 API；新方法/新类并存；旧测试零回归
- 不引入新外部依赖（已有：`pydantic / pyyaml`）
- 每个 PR 自带一组单测；至少一个 fixture-driven 集成测试
- 所有文件路径用 `pathlib.Path`；所有 fixture 用 deterministic seed
- Codex slice 产出严格走结构化 JSON（summary / files_changed / tests_run / risk_events / blockers / next_action）

---

## PR-1 编译器骨架对齐到 benchmark expected_file_tree

**目标**：让 `SkillCompiler` 输出的目录 = `benchmarks/.../expected_file_tree.yaml`，11 个 hard_gates 中文件结构相关的 5 个全部 pass。

**允许改动路径**：
- `document-to-skill-engineering-package/src/doc_to_skill/compiler.py`（新增方法）
- `document-to-skill-engineering-package/src/doc_to_skill/skill_pack_emitters/`（新增子包）
- `document-to-skill-engineering-package/tests/test_compiler_benchmark_shape.py`（新增）
- `document-to-skill-engineering-package/tests/fixtures/opportunity_insight_seeds/`（新增，软链或复制 benchmark `input/` 子集）

**禁止改动**：`parser.py`、`schemas.py`、`runtime.py`、旧 `compile()`、`build/` 目录、`skills/` 目录。

### PR-1 切片细分

| Slice | 目标 | 关键产物 | 验收 |
|---|---|---|---|
| 1.1 | 抽出 `SkillPackEmitter` 协议 | `skill_pack_emitters/base.py`：`Emitter` ABC，统一 `emit(ir, ctx, out_dir)` 签名 | 旧 `compile()` 不变；新模块可被 import |
| 1.2 | 实现 `_emit_skill_md` / `_emit_skill_yaml` / `_emit_readme` | `skill_pack_emitters/entry.py` | 输出文件与 benchmark `reference_skill_pack/{SKILL.md,skill.yaml,README.md}` 同一 schema |
| 1.3 | 实现 `contracts/` 全套 6 文件 | `skill_pack_emitters/contracts.py` | hard_gate `data_contract_complete`、`opportunity_card_schema_present`、`tool_contract_defined` 通过 |
| 1.4 | 实现 `knowledge/` 三文件（claim_pack/strategy_rules/negative_cases） | `skill_pack_emitters/knowledge.py` | hard_gate `knowledge_contract_grounded`（≥5 claims, ≥3 negative） 通过；**字段缺失 = placeholder + warning**：缺失项以 `<MISSING:source_field>` 落产物 + 一行写入 `runs/<run_id>/missing_fields_report.md`，**不抛异常**；严禁用具体业务数值兜底 |
| 1.5 | 实现 `prompts/` 四文件 | `skill_pack_emitters/prompts.py` | 正文 grep 不应命中具体业务结论；只包含 `rule_id` / `data_requirement_id` / `output_id` / `claim_id` 的引用 |
| 1.6 | 实现 `tools/tool_manifest.yaml` + `runtime/{execution_plan,error_policy,guardrails}.yaml` | `skill_pack_emitters/runtime.py` | hard_gate `execution_plan_ordered`、`no_unsafe_action` 通过 |
| 1.7 | 实现 `examples/` + `evals/` + `app/` | `skill_pack_emitters/examples_evals_app.py` | hard_gate `eval_defined`、`rsi_feedback_defined` 通过 |
| 1.8 | 串接 `compile_to_benchmark_shape(ir, output_dir, seeds)` | `compiler.py` 新方法 | 一次性产出完整目录；和 expected_file_tree 完全一致 |

### PR-1 验收

- `pytest document-to-skill-engineering-package/tests/test_compiler_benchmark_shape.py` 全绿
- 集成断言：`set(产出文件) >= set(expected_file_tree.required_files)`
- 11 个 hard_gates 中 7 个文件结构相关的 gate 全 pass（剩 4 个需 PR-2/3/4）：
  `required_file_tree_created` `has_skill_entry` `data_contract_complete` `knowledge_contract_grounded` `tool_contract_defined` `execution_plan_ordered` `opportunity_card_schema_present` `eval_defined` `rsi_feedback_defined` `no_unsafe_action`
- 风险：claim_pack/negative_cases 走 placeholder + warning：所有 `<MISSING:...>` sentinel 必须可被 grep 出来（CI 检查），`runs/<run_id>/missing_fields_report.md` 至少含一行 header + 每个 missing 字段一行（`source_field / required_min / actual_count / seed_file_ref`）

### PR-1 Codex prompt 边界

```text
goal: 把 SkillCompiler 输出对齐到 benchmark expected_file_tree
allowed_paths:
  - document-to-skill-engineering-package/src/doc_to_skill/compiler.py
  - document-to-skill-engineering-package/src/doc_to_skill/skill_pack_emitters/**
  - document-to-skill-engineering-package/tests/test_compiler_benchmark_shape.py
  - document-to-skill-engineering-package/tests/fixtures/opportunity_insight_seeds/**
forbidden_paths:
  - document-to-skill-engineering-package/src/doc_to_skill/parser.py
  - document-to-skill-engineering-package/src/doc_to_skill/schemas.py
  - document-to-skill-engineering-package/src/doc_to_skill/runtime.py
  - benchmarks/**
acceptance:
  - 11 个 hard_gates 中文件结构相关 5 项全 pass
  - 旧 compile() 测试零回归
verification:
  - pytest document-to-skill-engineering-package/tests/ -k 'compiler'
stop_conditions:
  - 任何 emitter 试图编造业务字段值 → 失败
  - 任何 prompts/*.md 含具体业务结论字串 → 失败
```

---

## PR-2 工具层：MockToolBackend + ToolResolver.resolve_all

**目标**：让任何 `data_requirement` 都能 deterministic 地拿到 mock 数据，并把可消费的 `tool_manifest` 产出来。

**允许改动路径**：
- `document-to-skill-engineering-package/src/doc_to_skill/tool_registry.py`（增强）
- `document-to-skill-engineering-package/src/doc_to_skill/tool_resolver.py`（增强）
- `document-to-skill-engineering-package/src/doc_to_skill/tool_backends/`（新增子包）
- `document-to-skill-engineering-package/tests/test_tool_resolver.py`（增强）
- `document-to-skill-engineering-package/tests/test_tool_backends.py`（新增）

**禁止改动**：`runtime.py`、`compiler.py`、`schemas.py` 中已存在字段。允许在 `schemas.py` **追加** `ToolCallResult` / `ToolResolutionReport` / `MockToolBackendSpec`（向后兼容字段追加）。

### PR-2 切片细分

| Slice | 目标 | 关键产物 | 验收 |
|---|---|---|---|
| 2.1 | 新增 `ToolCallResult` / `ToolResolutionReport` / `MockToolBackendSpec` 三个 Pydantic 模型 | `schemas.py` 末尾追加 | 旧模型 import 不破；新模型字段对齐设计文档 §3.2/§3.4 |
| 2.2 | `MockToolBackend` 协议（Protocol/ABC 二选一，选 Protocol 更轻） | `tool_backends/base.py` | 含 `invoke / deterministic_seed / declares()` 方法 |
| 2.3 | `EchoBackend` + `FixtureBackend` + `FailingBackend` 三个内置实现 | `tool_backends/{echo,fixture,failing}.py` | `FixtureBackend` 输入：`(fixture_dir, tool_id→file_glob 映射)`；失败时抛 `ToolBackendError` |
| 2.4 | `ToolRegistry` 内置注入接口 `register_backend(tool_id, backend)` + `invoke(tool_id, inputs, run_ctx)` | `tool_registry.py` 增强 | backend 优先级：显式注入 > FixtureBackend(默认) > EchoBackend(兜底)；invoke 永远不会异常逃逸，统一回 `ToolCallResult(status=...)` |
| 2.5 | `ToolResolver.resolve_all(requirements)` → `ToolResolutionReport` | `tool_resolver.py` 增强 | 输出 manifest 直接可写成 benchmark 期望的 `tools/tool_manifest.yaml` |
| 2.6 | 失败注入测试 + 回放测试 | `tests/test_tool_backends.py` | 同一 `(tool_id, inputs)` 两次 invoke，outputs_hash 相等；FailingBackend 命中后 fallback 链能继续 |

### PR-2 验收

- `pytest document-to-skill-engineering-package/tests/test_tool_resolver.py tests/test_tool_backends.py` 全绿
- `ToolResolutionReport.tool_manifest` 直接序列化得到的 yaml 通过 benchmark 的 `tool_contract_defined` gate
- `missing_tools` 不为空时仍能产出 manifest（兜底走 EchoBackend，标 `mode: mock_echo`）
- 旧 `resolve(requirement)` 签名保留，行为不变

### PR-2 Codex prompt 边界

```text
goal: 让 ToolRegistry/ToolResolver 支持 deterministic mock invoke + 完整 manifest 产出
allowed_paths:
  - document-to-skill-engineering-package/src/doc_to_skill/tool_registry.py
  - document-to-skill-engineering-package/src/doc_to_skill/tool_resolver.py
  - document-to-skill-engineering-package/src/doc_to_skill/tool_backends/**
  - document-to-skill-engineering-package/src/doc_to_skill/schemas.py   # 仅追加
  - document-to-skill-engineering-package/tests/test_tool_*.py
forbidden_paths:
  - document-to-skill-engineering-package/src/doc_to_skill/runtime.py
  - document-to-skill-engineering-package/src/doc_to_skill/compiler.py
  - benchmarks/**
acceptance:
  - resolve_all 输出的 manifest 通过 benchmark tool_contract_defined gate
  - 同一 (tool_id, inputs) 两次 invoke 结果一致
verification:
  - pytest document-to-skill-engineering-package/tests/ -k 'tool'
stop_conditions:
  - schemas.py 修改了任何已有字段 → 失败
  - invoke 路径出现 raise 逃逸 → 失败
```

---

## PR-3 Runtime 升级：拓扑 + tool 接入 + evidence + trace

**目标**：`MockRuntimeExecutor.execute(skill_pack_dir, skill_inputs, profile)` 跑出可 diff 的 trace + evidence，命中 §8 验收清单第 4 条。

**允许改动路径**：
- `document-to-skill-engineering-package/src/doc_to_skill/runtime.py`（重写）
- `document-to-skill-engineering-package/src/doc_to_skill/runtime_rules.py`（新增：白名单算子的 condition evaluator）
- `document-to-skill-engineering-package/src/doc_to_skill/schemas.py`（追加 `NodeTrace` 字段扩展 / `RuntimeResult` / `EvidencePack` 字段不动）
- `document-to-skill-engineering-package/tests/test_runtime.py`（新增/替换）

**禁止改动**：`compiler.py`、`parser.py`、`tool_*` 模块。

### PR-3 切片细分

| Slice | 目标 | 关键产物 | 验收 |
|---|---|---|---|
| 3.1 | 拓扑排序 + 失败传播 | `runtime.py::_toposort`、`_propagate_skip` | 给定环或缺前置依赖立即 `RuntimeResult(status=invalid)` 不执行 |
| 3.2 | step 执行四件套：拉数据 / 触发规则 / 写 evidence / 写 trace | `runtime.py::_execute_step` | 每 step 至少一条 `tool_call` 和一条 `evidence_id`（若 step 不需要数据，evidence 仍要落一条 schema=`derived`） |
| 3.3 | rule condition 白名单 evaluator | `runtime_rules.py` | 支持 `count(...) >= N` / `>= < <= ==` / 字段引用；不支持的 condition → `rule_hit=unevaluated` 不阻塞 |
| 3.4 | trace + evidence + outputs 落盘到 `runs/<run_id>/` | `runtime.py::_persist` | 文件路径与设计文档 §3.5 一致；都是 jsonl/json，不写 pickle |
| 3.5 | clock 注入 + deterministic run_id | `runtime.py::Clock` | 同一 `(skill_pack, skill_inputs, profile, seed)` 两次跑，trace 文件 byte-diff 仅 timestamp 字段不同 |
| 3.6 | 失败注入路径 e2e | `tests/test_runtime.py::test_failing_backend_fallback` | 前置 step 注入 FailingBackend；trace 显示 fallback 工具被命中，后续 step 不被错误 skip |

### PR-3 验收

- `pytest document-to-skill-engineering-package/tests/test_runtime.py` 全绿
- 给一份 PR-1 产出的 `generated_skill_pack` 直接跑通；trace 含 ≥6 succeeded step / ≥1 tool_call/step / ≥1 evidence/step
- 两次重跑 trace diff 仅时间字段
- 失败注入路径 trace 中 `fallback_tool_used=true`

### PR-3 Codex prompt 边界

```text
goal: 把 MockRuntimeExecutor 升级到能消费 generated_skill_pack 并落 trace+evidence
allowed_paths:
  - document-to-skill-engineering-package/src/doc_to_skill/runtime.py
  - document-to-skill-engineering-package/src/doc_to_skill/runtime_rules.py
  - document-to-skill-engineering-package/src/doc_to_skill/schemas.py   # 仅扩展 NodeTrace/RuntimeResult
  - document-to-skill-engineering-package/tests/test_runtime.py
forbidden_paths:
  - document-to-skill-engineering-package/src/doc_to_skill/compiler.py
  - document-to-skill-engineering-package/src/doc_to_skill/parser.py
  - document-to-skill-engineering-package/src/doc_to_skill/tool_*.py
  - benchmarks/**
acceptance:
  - 两次重跑 trace 仅时间字段不同
  - 失败注入路径 fallback 链可见
verification:
  - pytest document-to-skill-engineering-package/tests/ -k 'runtime'
stop_conditions:
  - 任何 step 在 condition 不支持时 raise → 失败（应记 unevaluated）
  - run_id 生成依赖系统时间而非注入 Clock → 失败
```

---

## PR-4 闭环胶水：glue/ + benchmark_runner + feedback_ingestor + profile

**目标**：`python -m glue.run_loop --benchmark <path>` 一键跑通设计文档 §4 的 step1..step8，命中 §8 全部 6 条验收。

**允许改动路径**：
- `glue/__init__.py` / `glue/run_loop.py` / `glue/benchmark_runner.py` / `glue/feedback_ingestor.py`（新增）
- `glue/profiles/default/thresholds.yaml`（新增）
- `glue/fixtures/feedback_seed.jsonl`（新增，PoC 用伪造反馈）
- `tests/test_run_loop.py`（新增，根 `tests/`）
- `runs/`（自动创建，不入版本）

**禁止改动**：`document-to-skill-engineering-package/**`、`benchmarks/**`、`growth_dev/team/**`。

### PR-4 切片细分

| Slice | 目标 | 关键产物 | 验收 |
|---|---|---|---|
| 4.1 | `benchmark_runner.check(skill_pack_dir, expected_dir, eval_dir)` | `glue/benchmark_runner.py` | 输出 `benchmark_report.json` + `benchmark_report.md`；含 `file_tree_pass / hard_gates / dimension_scores / total` |
| 4.2 | `run_loop.py` step1..step5 串接 | `glue/run_loop.py` | CLI 跑通到 step5，落 `runs/<ts>/generated_skill_pack` + `benchmark_report` + `trace + evidence` |
| 4.3 | `feedback_ingestor.ingest(trace, feedback_jsonl)` | `glue/feedback_ingestor.py` | 输入 jsonl 每条 `kind ∈ {adopt, reject, edit}`；`edit` 需带 `original_text / edited_text / target_path`；遇到 `business_outcome` 等未知 kind 走 `skipped_unsupported` 计数器且不阻塞；输出 `runs/<ts>/regression_cases.jsonl` + `runs/<ts>/profiles/<id>/thresholds.yaml` |
| 4.4 | profile override 接入编译 | `compile_to_benchmark_shape(..., profile=...)` 已在 PR-1 预留参数 | profile 仅覆盖 `rule_id → threshold_value`，不覆盖 condition；测试用对比 yaml diff |
| 4.5 | step6..step8 二轮闭环 | `glue/run_loop.py` | 注入 reject 反馈后第二轮 trace 的 `rule_hits[strong_hot_gene]` 数量下降；report 维度分变化可解释 |
| 4.6 | CLI smoke 测试 | `tests/test_run_loop.py` | 子进程拉起 `python -m glue.run_loop`，校验 `runs/<ts>/` 必备文件 |

### PR-4 验收

- 设计文档 §8 6 条全部 ✅
- 第一轮 `benchmark_report.json.total >= 70`
- 第二轮报告 vs 第一轮报告 dimension diff 至少命中 `knowledge_contract_quality` 或 `rsi_feedback_design` 之一
- `runs/<ts>/` 不进 git（验证 `.gitignore` 已含 `runs/`，若无则新增）

### PR-4 Codex prompt 边界

```text
goal: 在根仓库 glue/ 下实现 PoC 闭环胶水，串通编译/评测/runtime/反馈回流
allowed_paths:
  - glue/**
  - tests/test_run_loop.py
  - .gitignore   # 仅追加 runs/
forbidden_paths:
  - document-to-skill-engineering-package/**
  - benchmarks/**
  - growth_dev/team/**
  - docs/**
acceptance:
  - 设计文档 §8 验收清单 6 条全部 pass
  - 第二轮报告 dimension diff 可解释
verification:
  - pytest tests/test_run_loop.py
  - python -m glue.run_loop --benchmark benchmarks/opportunity_insight_benchmark_pack/benchmarks/skill_creator/opportunity_insight/
stop_conditions:
  - feedback_ingestor 试图改 generated_skill_pack/ 内任何文件 → 失败
  - run_loop 把任何反馈内容写进 prompts/*.md → 失败
```

---

## 跨 PR 检查表

每个 PR 合并前必过：

- [ ] 仅修改"允许改动路径"，没有动"禁止改动"列表
- [ ] 新增依赖数 = 0
- [ ] 单测覆盖：本 PR 引入的每个公共方法至少一条快乐路径 + 一条失败路径
- [ ] 集成断言：本 PR 的输出能被下一个 PR 直接消费（fixture 共享 schema）
- [ ] 没有把"业务结论"硬编码进任何代码或 prompt
- [ ] 没有引入需要联网的测试

---

## 时间预估（粗）

| PR | 预估 Codex slice 轮次 | 主要风险 |
|---|---|---|
| PR-1 | 6-8 | placeholder sentinel 规则要严格执行；CI 必须能 grep 出所有 `<MISSING:...>` |
| PR-2 | 3-4 | FixtureBackend 的 tool_id→file 映射规则要预先冻结 |
| PR-3 | 5-7 | condition evaluator 白名单边界容易膨胀，要按"只支持 reference 已有 condition"原则克制 |
| PR-4 | 4-5 | 第二轮"差异可解释"的判定逻辑要先冻结一份 diff schema |

---

## 评审征求意见（新增）

1. ~~PR-1 Slice 1.4：claim_pack/negative_cases 字段缺失时是 **fail-compile** 还是 **placeholder + warning**？~~ **已冻结：placeholder + warning（评审 1）**。缺失字段写 `<MISSING:source_field>` sentinel + `runs/<run_id>/missing_fields_report.md`，compile 不阻塞；hard_gate `knowledge_contract_grounded` 按原 gate 规则独立判定。
2. ~~PR-3 Slice 3.3：condition evaluator 白名单允许的算子集合是否冻结？~~ **已冻结（评审 2）**：`{count, >=, <=, >, <, ==, !=, and, or, field_ref}`；不支持 `not` / `in` / 算术；超出白名单标 `rule_hit=unevaluated` 不阻塞。
3. ~~PR-4 Slice 4.3：feedback fixture 是否需要也支持"业务结果反馈"（business_outcome）？~~ **已冻结（评审 3）**：PoC 仅 `adopt / reject / edit`，`business_outcome` 留 P1。`edit` 必带 `original_text / edited_text / target_path`。
4. ~~是否需要把 PR-1 拆得更细（每个 emitter 独立 PR）？~~ **已冻结（评审 4）**：不拆，按"emitter 子包"一次性合并；slice 1.1~1.8 仍按现粒度走 Codex slice-loop。