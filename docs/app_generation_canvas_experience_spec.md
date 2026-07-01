# PRD 生成应用 V2 生成画布体验规范

## 状态

本文档定义 `PRD生成应用` V2 生成画布体验。当前处于 **spec-first / 待实现** 阶段，不代表前端、API、AgentBridge、CodeAgentExecutor 或评估器已经具备本文档描述的全部能力。

V2 生成画布不是替代现有 Team Runtime，也不是新增一套平行编排器。它是在现有 `app_generation` domain、run artifacts、Dashboard API、`NodeContext`、AgentBridge、Codex/CodeAgentExecutor、preview runner 和人工确认 gate 之上，增加一个面向业务用户的对象化体验层。

技术落地方案见 [`docs/app_generation_canvas_technical_plan.md`](app_generation_canvas_technical_plan.md)。

Runway Timeline 是 V2 在当前 Dashboard 中的主体验收敛形态，规范见 [`docs/app_generation_runway_timeline_spec.md`](app_generation_runway_timeline_spec.md)。V2 后续不再把自由拖拽对象画布作为第一阶段默认主视图；第一阶段主视图必须是竖向业务流程 + 当前步骤详情 + 右侧 Agent 协作区。对象化能力作为步骤详情和证据层能力逐步增强。

现有 V1 工作台仍是基础事实层：

- [`docs/app_generation_workbench_spec.md`](app_generation_workbench_spec.md)：V1 三栏工作台、节点流、文件/应用预览、右侧 Agent。
- [`docs/app_generation_node_context_contract.md`](app_generation_node_context_contract.md)：`NodeContext`、`AgentInteractionContext` 和 Agent 共享上下文。
- [`docs/app_generation_agent_bridge_spec.md`](app_generation_agent_bridge_spec.md)：Agent Provider、动作协议和右侧对话边界。
- [`docs/app_generation_codex_observability_spec.md`](app_generation_codex_observability_spec.md)：Code Agent 执行过程可观测。
- [`docs/app_generation_agent_driven_repair_spec.md`](app_generation_agent_driven_repair_spec.md)：Agent 驱动应用修复闭环。

V2 生成画布的目标是把这些工程事实转换成业务可理解、可编辑、可回放、可修复的产品体验。

## 设计目标

用户在 `PRD -> 应用` 的过程中不应该只看到工程节点和文件路径，而应该看到：

- 系统如何理解业务目标。
- 需求如何被编译成应用规格。
- 应用结构如何形成。
- Code Agent 生成应用时正在处理哪些业务能力。
- 哪些能力已经验证通过，哪些仍有缺口。
- 当前预览应用的问题如何通过右侧 Agent 形成可确认修复。
- 业务场景、样例数据、依赖知识、工具调用和用户反馈如何进入生成上下文。

V2 必须回答五个核心问题：

1. **业务语言**：节点和执行过程必须用业务用户能理解的话表达。
2. **对象化**：PRD、业务目标、页面、能力、数据、工具、验证和修复都必须成为可选中的画布对象。
3. **可观测**：长耗时 Code Agent 过程必须有状态机、进度摘要、等待提示和证据链接。
4. **可协作**：右侧 Agent 必须围绕当前画布对象工作，而不是只解释当前工程节点。
5. **可扩展上下文**：PRD 之外的业务场景、数据、知识和工具调用必须能作为上下文对象参与生成。

## 借鉴 Penpot 的产品思想

V2 生成画布借鉴 Penpot 的不是视觉风格，而是产品结构思想：

- **对象化画布**：用户在画布上选择对象，再在属性/详情面板里理解和修改对象。
- **设计与代码可互读**：设计对象、组件、样式、token 和代码交付之间保持结构化关系。
- **开放标准和可检查性**：画布对象能被 inspect、导出、引用和自动化处理。
- **协作层独立**：协作者可以评论、调整、检查对象，但不绕过事实源和版本边界。
- **插件/API/MCP 思路**：外部工具、知识源和自动化能力通过明确接口进入画布，而不是隐式注入。

在本项目中，对应关系如下：

| Penpot 思想 | 生成画布对应物 |
| --- | --- |
| Frame / Board | 生成 run / 业务流程画布 |
| Layer / Object | 业务目标、页面、能力、数据、工具调用、验证结果 |
| Inspect | 对象详情、证据、artifact preview、diff preview |
| Design Tokens | 业务规则、UI 风格约束、provider 配置、能力契约 |
| Components / Variants | 页面模块、功能能力、候选方案、修复版本 |
| Collaboration | 右侧 Agent、用户确认动作、AdjustmentEvent |
| Plugin / API | Project Skills、工具调用、知识源、数据源、CodeAgentExecutor |

## V1 到 V2 的体验变化

V1 工作台以节点和 artifacts 为中心：

```text
任务列表 -> 节点流 -> 节点详情 / 文件预览 -> 右侧 Agent
```

V2 生成画布以业务流程、业务对象和状态流为中心。当前 Dashboard 的默认落地形态是 Runway Timeline：

```text
任务/版本列表
-> Runway Timeline
   -> PRD 输入
   -> 业务步骤轨道
   -> 当前步骤详情 / 对象 / 证据 / 预览
-> 右侧 Agent 协作区
```

V2 不删除节点流，而是把节点流降级为“工程证据层”。用户默认看到业务步骤和步骤对象，技术节点、raw artifact、executor、provider 和 JSON 证据只在当前步骤的展开证据中出现。

## 页面结构

### 总体布局

V2 默认仍保留三大区，但中间区从“节点列表 + 节点详情”升级为 Runway Timeline：

```text
┌──────────────────┬─────────────────────────────────────────────┬──────────────────┐
│ 任务 / 版本列表   │ Runway Timeline                            │ 右侧 Agent        │
│                  │ ┌──────────────┬──────────────────────────┐ │                  │
│ runs             │ │ 竖向业务流程   │ 当前步骤详情              │ │ 对话 / 动作确认    │
│ versions         │ │ 状态时间线     │ 对象 / 预览 / 证据 / diff │ │ 修复 / 解释 / 对比  │
└──────────────────┴─────────────────────────────────────────────┴──────────────────┘
```

中间 Runway Timeline 包含三个区域：

- **竖向业务流程**：展示从 PRD 到可预览应用的业务过程。
- **当前步骤详情**：展示选中步骤的输入、执行过程、输出、可操作项、对象和工程证据。
- **对象/证据层**：在步骤详情内展示当前 run 的业务对象、依赖关系、状态、能力缺口和 evidence refs。

文件预览、应用预览和 diff 预览仍是可打开的辅助视图，不能挤压右侧 Agent 到不可用状态。

### 响应式规则

- 桌面宽屏：左侧任务列表 + 中间生成画布 + 右侧 Agent。
- 中等宽度：左侧可折叠，中间画布保持主视图，右侧 Agent 保持固定最小宽度。
- 窄屏：任务列表、画布、Agent 以 tabs 切换；不允许把 Agent 压成一条线。
- 预览栏打开时，优先占用中间画布的伸缩空间，不压缩左侧任务标题和右侧 Agent。

## Runway Timeline 业务流程

V2 默认只展示业务友好步骤标题。内部 node id 仍保留，用于映射现有 runtime artifacts。Runway Timeline 第一阶段固定展示 8 个 `BusinessStep`，其中 `PRD 输入` 和 `可预览应用` 是 UI flow step，不新增 Team Runtime agent。

| Runway 步骤 | 业务含义 | 对应 V1 / Runtime 事实源 |
| --- | --- | --- |
| PRD 输入 | 用户上传或粘贴 PRD，设置生成参数并启动 run | `input_prd.md`、`team_run_record.json` |
| 1. 理解业务目标 | 识别用户目标、用户角色、业务场景、输入输出和成功标准 | `prd_input`、`skill_routing`、`requirements/brief_analysis.json` |
| 2. 编译业务规格 | 把 PRD 转成标准化需求、范围边界、能力清单和验收标准 | `prd_normalization`、`app_contract.json`、`acceptance_criteria.md` |
| 3. 规划应用结构 | 规划页面、流程、数据对象、状态、API 和测试切片 | `planning_tdd`、`planning/*`、`slices/*` |
| 4. 生成应用原型 | Code Agent 生成本地 SPA、server、样式、交互和 smoke test | `implementation`、`codex/*`、`generated_apps/<slug>/` |
| 5. 验证业务能力 | 验证按钮、流程、provider、下载、局部迭代和 benchmark 能力 | `review_test`、`app_runtime_verification.json`、`benchmark_diff.md`、`agqs_score.json` |
| 6. 输出可交付版本 | 形成交付说明、已知限制、修复记录和下一步建议 | `preview_delivery`、`final_report.md` |
| 可预览应用 | 发布快照、启动本地预览、健康检查和应用修复 | `app_publish.json`、`preview/preview_run_record.json`、`app_repairs/*` |

下表保留历史 6 个业务节点映射，供 runtime aggregation 使用：

| V2 业务节点 | 业务含义 | 对应 V1 / Runtime 事实源 |
| --- | --- | --- |
| 1. 理解业务目标 | 识别用户目标、用户角色、业务场景、输入输出和成功标准 | `prd_input`、`skill_routing`、`requirements/brief_analysis.json` |
| 2. 编译业务规格 | 把 PRD 转成标准化需求、范围边界、能力清单和验收标准 | `prd_normalization`、`app_contract.json`、`acceptance_criteria.md` |
| 3. 规划应用结构 | 规划页面、流程、数据对象、状态、API 和测试切片 | `planning_tdd`、`planning/*`、`slices/*` |
| 4. 生成应用原型 | Code Agent 生成本地 SPA、server、样式、交互和 smoke test | `implementation`、`codex/*`、`generated_apps/<slug>/` |
| 5. 验证业务能力 | 验证按钮、流程、provider、下载、局部迭代和 benchmark 能力 | `review_test`、`app_runtime_verification.json`、`benchmark_diff.md`、`agqs_score.json` |
| 6. 输出可交付版本 | 形成预览、发布快照、交付说明、修复记录和下一步建议 | `preview_delivery`、`final_report.md`、`app_publish.json`、`adjustment_events.jsonl` |

节点卡片展示：

- 业务标题。
- 当前状态。
- 一句话进展。
- 主要对象数量，例如“3 个业务目标、8 个应用能力、2 个缺口”。
- 最近事件，例如“Code Agent 正在验证应用按钮”。

节点默认不展示：

- `node_id`
- artifact path
- raw JSON
- stdout
- provider 内部字段

这些字段只能放入开发者详情、证据预览或复制上下文中。

## 画布对象模型

V2 的核心是 `CanvasObject`。节点负责生产、更新或验证对象；右侧 Agent 围绕对象解释和修改。

### CanvasObject

```json
{
  "schema_version": 1,
  "object_id": "capability:image_generation.single",
  "object_type": "capability",
  "title": "单张图片生成",
  "summary": "用户可以基于选中的 Prompt 生成单张主图。",
  "status": "needs_attention",
  "owner_node": "生成应用原型",
  "source_refs": ["input_prd.md", "app_contract.json"],
  "artifact_refs": ["generated_apps/input-prd/public/app.js"],
  "evidence_refs": ["codex/app_runtime_verification.json"],
  "editable_fields": ["summary", "acceptance", "priority"],
  "actions": ["explain_object", "repair_generated_app", "verify_capability"],
  "risks": [],
  "updated_at": "2026-06-28T12:00:00Z"
}
```

字段规则：

- `object_id` 必须稳定，支持跨节点引用。
- `object_type` 必须来自固定枚举。
- `title` 和 `summary` 使用业务语言。
- `source_refs` 指向需求、上下文或用户输入。
- `artifact_refs` 指向实现或产物。
- `evidence_refs` 指向验证、评审、日志、diff 或评分。
- `editable_fields` 只声明用户可编辑的业务字段，不代表可直接改代码。
- `actions` 必须受 AgentBridge allowed operations 限制。

### 对象类型

| object_type | 中文名 | 用途 |
| --- | --- | --- |
| `business_goal` | 业务目标 | 用户想解决什么问题，如何判断成功 |
| `user_persona` | 用户角色 | 谁使用应用，角色关注点是什么 |
| `scenario` | 业务场景 | 典型任务、触发条件、输入输出和流程 |
| `capability` | 应用能力 | 生成应用必须支持的功能能力 |
| `page_flow` | 页面流程 | 页面、步骤、导航、表单和按钮 |
| `data_object` | 数据对象 | 本地状态、表单数据、上传文件、生成结果 |
| `provider_config` | 服务配置 | OpenRouter、模型、超时、健康检查等配置摘要 |
| `knowledge_source` | 依赖知识 | 用户补充资料、benchmark、参考应用、领域规则 |
| `tool_call` | 工具调用 | Project Skill、Codex、PI-Agent、文件读取、验证命令 |
| `artifact` | 中间产物 | PRD、规格、计划、代码、报告、diff、截图 |
| `preview_session` | 应用预览 | 当前预览 URL、状态、日志、健康检查 |
| `capability_gap` | 能力缺口 | 应用缺失、错误、未验证或用户反馈的问题 |
| `repair_candidate` | 修复候选 | patch、delegate_code_repair 候选 diff、验证计划 |
| `delivery_version` | 可交付版本 | 发布快照、版本说明、验收状态 |

## 对象状态机

所有画布对象都必须有业务状态。

| 状态 | 业务文案 | 含义 |
| --- | --- | --- |
| `not_started` | 未开始 | 对象已识别但未处理 |
| `understanding` | 理解中 | 正在从 PRD、场景或用户输入中提取 |
| `drafted` | 已形成草案 | 有初步对象，但未验证 |
| `planned` | 已纳入规划 | 已进入应用结构或测试计划 |
| `generating` | 正在生成 | Code Agent 或工具正在生成相关产物 |
| `generated` | 已生成 | 有实现或产物 |
| `verifying` | 正在验证 | 正在运行检查、预览、能力扫描或评审 |
| `verified` | 已验证 | 有证据证明通过 |
| `needs_attention` | 需关注 | 有 warning、缺口或未确认项 |
| `blocked` | 已阻塞 | 缺少输入、能力缺失、验证失败或安全风险 |
| `patched` | 已修复 | 用户确认 patch 后对象更新 |
| `delivered` | 已交付 | 进入发布快照或最终交付版本 |

状态来源必须可追溯。UI 不得仅凭前端临时状态标记为 `verified` 或 `delivered`。

## 每个业务节点的可观测内容

### 1. 理解业务目标

展示对象：

- 业务目标。
- 用户角色。
- 业务场景。
- 输入材料。
- 关键成功标准。
- 需澄清问题。

用户可编辑：

- 业务目标摘要。
- 用户角色描述。
- 场景优先级。
- 明确排除范围。

可观测证据：

- 原始 PRD 引用。
- 标准化摘要。
- Project Skills 路由结果。
- 用户补充上下文。

### 2. 编译业务规格

展示对象：

- 应用能力清单。
- 范围边界。
- 验收标准。
- 数据边界。
- 安全边界。
- provider / 模型配置要求。

用户可编辑：

- 能力优先级。
- 验收标准。
- 必须保留 / 不允许改变的能力。

可观测证据：

- `normalized_prd.md`
- `app_contract.json`
- `acceptance_criteria.md`
- capability gap 初始清单。

### 3. 规划应用结构

展示对象：

- 页面流程。
- 数据对象。
- API/本地服务。
- 状态持久化策略。
- TDD / slice 计划。
- 预期验证命令。

用户可编辑：

- 页面流程顺序。
- 能力和页面的映射。
- 验证优先级。

可观测证据：

- `planning/tdd_plan.json`
- `planning/acceptance_coverage_matrix.json`
- `slices/*.yaml`

### 4. 生成应用原型

展示对象：

- 生成应用文件。
- 页面模块。
- 交互按钮。
- provider 配置读取。
- runtime smoke。
- Code Agent 进度。

用户可编辑：

- 不能直接编辑未发布 worktree。
- 可通过右侧 Agent 提出修复意图。
- 发布后可以通过 `patch_app` 或 `delegate_code_repair` 修复当前快照。

可观测证据：

- `codex/coder_progress.jsonl`
- `codex/coder_progress_status.json`
- `codex/diff.patch`
- `codex/app_runtime_verification.json`
- `generated_apps/<slug>/`

### 5. 验证业务能力

展示对象：

- 能力覆盖矩阵。
- 预览健康状态。
- provider health。
- 按钮/流程 smoke 结果。
- benchmark parity 结果。
- AGQS 评分。
- 风险和阻塞项。

用户可编辑：

- 标记能力是否符合预期。
- 添加人工验收记录。
- 触发针对缺口的修复。

可观测证据：

- `test_report.md`
- `benchmark_diff.md`
- `agqs_score.json`
- `preview/preview_run_record.json`
- `adjustment_events.jsonl`

### 6. 输出可交付版本

展示对象：

- 发布快照。
- 预览入口。
- 交付说明。
- 已知限制。
- 修复历史。
- 下一步建议。

用户可编辑：

- 发布说明。
- 已知限制。
- 是否将成功修复提升为生成规则。

可观测证据：

- `final_report.md`
- `preview_instructions.md`
- `generated_apps/<slug>/app_publish.json`
- `app_patches/index.json`
- `app_repairs/<repair_id>/repair_result.json`

## Code Agent 长过程表达

Code Agent 是用户等待时间最长、焦虑最高的环节。V2 必须把工程事件转成业务进度。

### 业务进度阶段

| 工程事件 | 业务表达 |
| --- | --- |
| prompt/state summary ready | 正在准备应用生成上下文 |
| Codex process started | Code Agent 已启动 |
| file_change started | 正在生成或修改应用文件 |
| command_execution node --check | 正在检查应用代码语法 |
| runtime_smoke.js | 正在模拟用户操作 |
| test command running | 正在验证业务能力 |
| diff ready | 候选改动已准备好 |
| app runtime verification passed | 应用基础自检通过 |
| benchmark gap found | 发现能力缺口 |
| no new event for 30s | Code Agent 仍在运行，暂无新输出 |

### 进度卡片

生成应用原型节点必须展示“Code Agent 进度卡片”：

- 当前阶段。
- 最近动作。
- 已耗时。
- 最近改动文件摘要。
- 最近验证命令摘要。
- 产物引用。
- 是否仍在运行。
- 是否需要用户确认。

卡片不得默认展示完整 stdout、完整 prompt、完整源码或 secret。

### 等待体验

当执行超过 30 秒：

- 显示“仍在运行”的明确提示。
- 展示最近一次事件时间。
- 展示最近 3-5 条业务进度。
- 提供“查看详细日志”入口。
- 不允许只显示 spinner。

当执行超过 5 分钟：

- 显示当前最长耗时阶段。
- 提供“查看 Codex 进度文件”。
- 提供“继续等待 / 取消当前 run / 在右侧 Agent 询问当前状态”的入口。

## 右侧 Agent 与画布联动

右侧 Agent 的默认工作对象不再是“当前节点”，而是“当前选中的画布对象”。

### CanvasSelectionContext

前端必须在 Agent 请求中携带 `CanvasSelectionContext`：

```json
{
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
```

`CanvasSelectionContext` 是 `AgentInteractionContext` 的 V2 扩展。它描述用户当前看着哪个业务对象、处在哪个画布表面、允许 Agent 做什么。

### AgentIntent V2

| Intent | 触发场景 | 默认动作 |
| --- | --- | --- |
| `explain_object` | 用户问“这个能力是什么”“这个输入从哪来” | 解释当前对象和证据 |
| `edit_business_object` | 用户说“把目标改成…”“这个场景补充…” | 生成业务对象 patch，待确认 |
| `repair_generated_app` | 用户在预览中报告按钮、模型、provider、下载、局部迭代问题 | 优先 `delegate_code_repair`，简单锚点问题可 `patch_app` |
| `verify_capability` | 用户要求验证某个能力 | 运行受控验证或生成验证计划 |
| `compare_versions` | 用户要求比较两个版本/变体 | 读取版本对象和评分对象 |
| `promote_to_generation_rule` | 用户要求“以后也这样生成” | 形成候选规则，待确认写入模板/benchmark/verifier |
| `ask_clarification` | 业务输入不足或风险太高 | 提问，不执行修改 |

### AgentAction V2

V2 保留现有动作，并新增对象化动作：

- `explain_object`
- `suggest_object_patch`
- `apply_object_patch`
- `repair_generated_app`
- `verify_capability`
- `compare_canvas_objects`
- `promote_to_generation_rule`
- `delegate_code_repair`
- `rerun_business_node`

所有动作必须满足：

- 带 `source_object_id`。
- 带 `problem_source`。
- 带 `preserve_capabilities`。
- 带 `verification`。
- 需要修改事实源时必须 `requires_confirmation=true`。
- 不得直接修改 `codex/` 原始输出、worktree 或 secret。

## 业务场景、数据、知识和工具

PRD 只能承载一部分上下文。V2 生成画布必须支持额外上下文对象。

### ContextObject

```json
{
  "context_id": "scenario:buyer-uploads-reference-image",
  "context_type": "scenario",
  "title": "用户上传产品图和参考图",
  "summary": "商家上传产品图，选择参考图后生成主图方案。",
  "source": "user_input",
  "confidence": "confirmed",
  "used_by_nodes": ["理解业务目标", "编译业务规格", "验证业务能力"],
  "linked_objects": ["capability:reference_image_upload"],
  "artifact_refs": []
}
```

### 上下文类型

| context_type | 中文名 | 示例 |
| --- | --- | --- |
| `scenario` | 业务场景 | 商家上传产品图后生成 8 张主图 |
| `sample_data` | 样例数据 | 示例商品图、CSV、JSON、表单样例 |
| `domain_knowledge` | 领域知识 | 电商主图规则、平台限制、品牌规范 |
| `reference_app` | 参考应用 | benchmark reference app、历史成功 run |
| `user_feedback` | 用户反馈 | 预览后指出“按钮没反应” |
| `tool_capability` | 工具能力 | OpenRouter 生图、文件预览、截图、评估器 |
| `policy_constraint` | 策略约束 | 不保存 secret、不自动部署、不隐藏网络调用 |

规则：

- 上下文对象必须有来源和可信度。
- 用户手动确认的上下文优先于模型推断。
- 上下文对象被节点使用时必须留下引用。
- 上下文不得包含 API key、完整 `.env`、未授权文件正文或隐私数据。

## 画布事实源和协议关系

V2 新增体验层，但事实源仍然是现有 artifacts。

```text
run artifacts
-> NodeContext
-> CanvasObject projection
-> CanvasSelectionContext
-> AgentPromptContext
-> AgentAction
-> confirmed API action
-> updated run artifacts / adjustment events
-> refreshed CanvasObject projection
```

### 新增投影层

后续实现应新增只读投影：

```text
CanvasProjection = f(run artifacts, NodeContext, preview status, evaluation, adjustment events)
```

`CanvasProjection` 不写入事实源。它可以缓存，但必须可从 artifacts 重建。

建议 API：

- `GET /api/app-generation/runs/<run_id>/canvas`
- `GET /api/app-generation/runs/<run_id>/canvas/objects/<object_id>`
- `POST /api/app-generation/runs/<run_id>/canvas/actions`

V2 不要求第一阶段实现所有 API；但协议字段必须稳定，避免前端和 Agent 各自拼上下文。

## 对象编辑规则

用户编辑分三类：

| 编辑类型 | 目标 | 执行方式 |
| --- | --- | --- |
| 业务对象编辑 | 目标、场景、能力、验收标准、优先级 | 生成 `user_override` 或 `object_patch`，再从最小影响节点重跑 |
| 已发布应用修复 | 当前 `generated_apps/<slug>/` 快照 | `patch_app` 或 `delegate_code_repair`，确认后 apply |
| 生成规则提升 | 模板、benchmark、verifier、scaffold 规则 | 生成候选规则，用户确认后进入后续实施计划 |

禁止：

- 右侧 Agent 直接改 worktree。
- 右侧 Agent 直接覆盖 `codex/` 原始输出。
- 业务对象编辑悄悄改旧 artifact。
- 未确认动作直接 apply。
- 把 API key 注入 Agent prompt、artifact、logs、SSE 或 localStorage。

## 版本和回放

V2 画布必须把一次生成和多次修复串成版本线。

版本对象包括：

- 初始生成版本。
- 发布快照版本。
- 每次 `patch_app` 后的应用版本。
- 每次 `delegate_code_repair` 候选版本。
- 每次用户确认后的 adjustment event。

用户必须能看到：

- 这个版本从哪个 run / patch / repair 来。
- 改了哪些对象和文件。
- 哪些能力变好，哪些风险新增。
- 是否可回滚。
- 是否建议沉淀为生成规则。

## 验收标准

### AC-CANVAS-001 业务节点语言

默认节点轨道只展示业务语言。Runway Timeline 主体验展示 8 个 `BusinessStep`：

1. PRD 输入
2. 理解业务目标
3. 编译业务规格
4. 规划应用结构
5. 生成应用原型
6. 验证业务能力
7. 输出可交付版本
8. 可预览应用

其中 6 个 runtime 聚合业务节点为：

1. 理解业务目标
2. 编译业务规格
3. 规划应用结构
4. 生成应用原型
5. 验证业务能力
6. 输出可交付版本

内部 `node_id` 只在开发者详情中出现。

### AC-CANVAS-002 对象画布

用户选择 run 后，可以看到业务对象列表或画布，包括业务目标、场景、能力、页面流程、数据对象、provider 配置、能力缺口、预览会话和修复候选。

### AC-CANVAS-003 对象详情

点击任意对象后，详情区展示：

- 业务摘要。
- 来源。
- 相关节点。
- 输入和输出。
- 证据引用。
- 当前状态。
- 可执行动作。

### AC-CANVAS-004 Code Agent 业务进度

生成应用原型节点必须把 `CodexProgressEvent` 转成业务进度；30 秒无新事件时显示“仍在运行，暂无新输出”；不得只展示 spinner 或 raw stdout。

### AC-CANVAS-005 Agent 围绕对象协作

右侧 Agent 请求必须带 `CanvasSelectionContext`。用户问“这个能力为什么没过”“修复这个预览错误”时，Agent 围绕当前对象和证据回答，不退化为泛泛解释当前节点。

### AC-CANVAS-006 上下文对象

PRD 之外的场景、样例数据、参考应用、领域知识、用户反馈和工具能力必须能作为 `ContextObject` 被记录、引用和展示。

### AC-CANVAS-007 受控编辑

业务对象编辑、应用修复和生成规则提升必须走不同动作协议，并且都需要用户确认后才改变事实源。

### AC-CANVAS-008 版本回放

用户必须能查看初始生成、发布快照、patch、delegate repair 和回滚记录，并能看到每次调整影响了哪些对象和能力。

### AC-CANVAS-009 Secret 边界

画布对象、Agent prompt、SSE、日志摘要、preview status 和 diff 预览不得包含 API key、完整 `.env`、未授权文件内容或 secret。

### AC-CANVAS-010 可从 artifacts 重建

`CanvasProjection` 必须能从 run artifacts、preview record、evaluation artifacts 和 adjustment events 重建，不得依赖浏览器本地临时状态作为唯一事实源。

## 分阶段实施建议

### V2.0：对象化投影，不大改布局

- 新增 `CanvasObject` 投影 API。
- 在现有中间区右列增加“业务对象”tab。
- 六个 runtime 聚合业务节点替换默认工程节点标题。
- Code Agent 进度卡片业务化。
- 右侧 Agent 带 `CanvasSelectionContext`。

### V2.1：Runway Timeline 主视图

- 中间区改为竖向 Runway Timeline + 当前 `BusinessStep` 详情。
- `flow_steps[]` 增加 `prd_entry` 和 `app_preview` 两个 UI step，形成 8 步主流程。
- 对象、能力缺口、预览和 diff 进入当前步骤详情，不作为并列主流程。
- 支持对象选中、对象详情、相关对象跳转。
- 能力缺口和修复候选进入当前步骤对象列表。
- 预览和 diff 与对象联动。

### V2.2：上下文对象和版本回放

- 支持用户上传/登记样例数据、参考应用、领域知识。
- 建立上下文对象和生成对象的引用关系。
- 增加版本线和 adjustment replay。
- 支持“提升为生成规则”的候选对象。

## 后续需要更新的规范

实现 V2 前，需要同步更新：

- `docs/app_generation_workbench_spec.md`：标注 V1 工作台与 V2 画布关系。
- `docs/app_generation_node_context_contract.md`：补 `CanvasSelectionContext` 和 `CanvasObject` 摘要字段。
- `docs/app_generation_agent_bridge_spec.md`：补 `AgentIntent V2` 和对象化 `AgentAction`。
- `docs/app_generation_acceptance_and_testing.md`：新增 `AC-CANVAS-*` 测试验收。
- `docs/app_generation_implementation_task_plan.md`：新增 V2.0 / V2.1 / V2.2 实施任务。

## 明确不做

V2 生成画布第一阶段不做：

- 不引入数据库。
- 不引入多人实时协作后端。
- 不引入 Docker 作为预览基础。
- 不把右侧 Agent 变成第二套代码修改系统。
- 不让浏览器 localStorage 成为画布事实源。
- 不把 PRD 之外的上下文隐式注入模型，必须有对象、来源和引用。
