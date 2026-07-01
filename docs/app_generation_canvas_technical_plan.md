# PRD 生成应用 V2 生成画布技术方案

## 状态

本文档是 [`docs/app_generation_canvas_experience_spec.md`](app_generation_canvas_experience_spec.md) 的技术落地方案。当前处于设计阶段，不表示相关 API、前端组件或 AgentBridge 已实现。

目标是在不引入数据库、不替代 Team Runtime、不破坏现有 V1 工作台的前提下，把 `PRD -> 应用` 过程升级为对象化生成画布。

## 技术目标

- 将 run artifacts 投影为业务对象，而不是让前端直接理解所有工程文件。
- 将 Runway Timeline 的 8 个 `BusinessStep` 作为默认用户视图，同时保留 V1 runtime node 事实源。
- 将 Code Agent 长过程转成业务进度卡片。
- 将右侧 Agent 的上下文从 `NodeContext` 扩展到 `CanvasSelectionContext`。
- 支持 PRD 之外的业务场景、样例数据、领域知识、工具能力和用户反馈作为上下文对象。
- 保持 secret 边界、路径边界、人工确认 gate 和可回放证据。

## 架构概览

```text
runs/<run_id> artifacts
  -> AppGenerationStateBuilder
  -> NodeContext
  -> CanvasProjectionBuilder
  -> Canvas API
  -> Dashboard Canvas UI
  -> CanvasSelectionContext
  -> AgentBridge
  -> AgentAction
  -> Existing controlled APIs
     - patch_app
     - delegate_code_repair
     - rerun_from_node
     - preview
     - artifact preview
```

V2 的核心新增层是 `CanvasProjectionBuilder`。它只读 artifacts，生成可重建的 `CanvasProjection`。

## 后端设计

### 1. CanvasProjectionBuilder

建议新增模块：

```text
growth_dev/team/app_generation_canvas.py
```

职责：

- 读取当前 run 的 artifacts。
- 生成 Runway Timeline `flow_steps[]`，包含 2 个 UI step 和 6 个 runtime 聚合业务 step。
- 生成 `CanvasObject[]`。
- 生成对象之间的引用关系。
- 聚合 preview、provider、capability gap、repair、patch 和 evaluation 摘要。
- 做统一脱敏和路径归一。

不负责：

- 修改 artifacts。
- 启动 preview。
- 调用 Agent。
- 运行 Code Agent。
- 保存浏览器 UI 状态。

核心函数：

```python
def build_canvas_projection(run_id: str, *, runs_dir: Path, repo_root: Path) -> dict[str, Any]:
    ...

def build_canvas_object_detail(run_id: str, object_id: str, *, runs_dir: Path, repo_root: Path) -> dict[str, Any]:
    ...
```

### 2. CanvasProjection JSON

```json
{
  "schema_version": 1,
  "run": {
    "run_id": "app_generation-...",
    "app_slug": "input-prd",
    "status": "completed",
    "quality_mode": "benchmark_parity"
  },
  "flow_steps": [],
  "business_nodes": [],
  "objects": [],
  "edges": [],
  "versions": [],
  "context_objects": [],
  "updated_at": "2026-06-28T12:00:00Z"
}
```

### 3. API

新增只读 API：

```text
GET /api/app-generation/runs/<run_id>/canvas
GET /api/app-generation/runs/<run_id>/canvas/objects/<object_id>
```

可选动作 API：

```text
POST /api/app-generation/runs/<run_id>/canvas/actions
```

第一阶段可以不实现统一 actions API，先把 V2 action 映射到现有 API：

- `repair_generated_app(strategy=patch_app)` -> `POST /patch-app`
- `repair_generated_app(strategy=delegate_code_repair)` -> `POST /delegate-code-repair`
- `rerun_business_node` -> `POST /rerun`
- `verify_capability` -> 现有 preview health / runtime smoke / 后续 capability scanner

### 4. Runway Timeline 与业务节点映射

后端维护固定 `flow_steps[]`。其中 `prd_entry` 和 `app_preview` 是 UI step，不新增 Team Runtime agent；其余 6 个步骤映射到现有 runtime facts：

```python
RUNWAY_FLOW_STEPS = [
    {
        "id": "prd_entry",
        "title": "PRD 输入",
        "step_type": "ui",
        "runtime_nodes": [],
    },
    {
        "id": "business_goal_understanding",
        "title": "理解业务目标",
        "step_type": "business",
        "runtime_nodes": ["skill_routing", "prd_input"],
    },
    {
        "id": "business_spec_compilation",
        "title": "编译业务规格",
        "step_type": "business",
        "runtime_nodes": ["prd_normalization", "context_contract"],
    },
    {
        "id": "app_structure_planning",
        "title": "规划应用结构",
        "step_type": "business",
        "runtime_nodes": ["planning_tdd"],
    },
    {
        "id": "prototype_generation",
        "title": "生成应用原型",
        "step_type": "business",
        "runtime_nodes": ["implementation"],
    },
    {
        "id": "capability_verification",
        "title": "验证业务能力",
        "step_type": "business",
        "runtime_nodes": ["review_quality", "verification"],
    },
    {
        "id": "delivery_version",
        "title": "输出可交付版本",
        "step_type": "business",
        "runtime_nodes": ["preview_delivery"],
    },
    {
        "id": "app_preview",
        "title": "可预览应用",
        "step_type": "ui",
        "runtime_nodes": [],
    },
]
```

后端仍可维护 6 个 runtime 聚合业务节点，用于对象归属、状态聚合和历史兼容：

```python
BUSINESS_NODE_MAP = [
    {
        "id": "business_goal_understanding",
        "title": "理解业务目标",
        "runtime_nodes": ["skill_routing", "prd_input"],
    },
    {
        "id": "business_spec_compilation",
        "title": "编译业务规格",
        "runtime_nodes": ["prd_normalization", "app_contract"],
    },
    {
        "id": "app_structure_planning",
        "title": "规划应用结构",
        "runtime_nodes": ["planning_tdd"],
    },
    {
        "id": "prototype_generation",
        "title": "生成应用原型",
        "runtime_nodes": ["implementation"],
    },
    {
        "id": "capability_verification",
        "title": "验证业务能力",
        "runtime_nodes": ["review_test"],
    },
    {
        "id": "delivery_version",
        "title": "输出可交付版本",
        "runtime_nodes": ["preview_delivery"],
    },
]
```

### 5. 对象抽取规则

第一阶段按文件存在和结构化 artifact 抽取：

| artifact | 对象 |
| --- | --- |
| `input_prd.md` | `business_goal`、`scenario` 候选 |
| `requirements/normalized_prd.md` | 标准化目标和范围对象 |
| `app_contract.json` | `capability`、`provider_config`、`data_object` |
| `planning/tdd_plan.json` | `page_flow`、`data_object`、测试计划 |
| `planning/acceptance_coverage_matrix.json` | capability 到验证覆盖关系 |
| `codex/coder_progress_status.json` | `prototype_generation` 进度 |
| `codex/app_runtime_verification.json` | `capability_verification` 证据 |
| `benchmark_diff.md` / `agqs_score.json` | `capability_gap`、评分对象 |
| `preview/preview_run_record.json` | `preview_session` |
| `app_patches/index.json` | patch 版本对象 |
| `app_repairs/<repair_id>/repair_result.json` | `repair_candidate` |
| `adjustment_events.jsonl` | 用户调优事件和版本线 |

对象抽取失败时不得阻断 run 展示；应生成 warning，并保留 V1 节点详情。

## 前端设计

### 文件组织

建议保持现有 `dashboard/app_generation.js`，但抽出纯渲染 helpers：

```text
dashboard/app_generation_canvas.js
dashboard/app_generation_canvas_render.js
dashboard/app_generation_canvas_agent.js
```

若不做拆分，第一阶段可以先在 `app_generation.js` 内新增小范围函数，但必须避免继续把文件变成单体。

### 状态结构

```js
state.canvas = {
  projection: null,
  selectedObjectId: "",
  selectedBusinessNodeId: "",
  viewMode: "objects",
  filters: {
    objectType: "all",
    status: "all"
  }
};
```

### UI 区域

第一阶段：

- 左侧：保持 run 列表。
- 中间：在现有节点详情上方或旁边增加“业务对象”tab。
- 右侧：Agent panel 显示当前 object id、business node 和 allowed actions。

第二阶段：

- 中间主视图替换为业务节点轨道 + 对象画布。
- 对象详情区替代现有部分详情卡。
- V1 节点详情放入“开发者详情”或“工程证据”tab。

### Code Agent 进度表达

前端读取：

- `node_progress` SSE。
- `canvas.objects` 中的进度对象。
- `execution_progress` 和 `code_repair_progress`。

统一渲染为：

- 当前业务阶段。
- 最近动作。
- 已耗时。
- 最近验证。
- 证据入口。
- 30 秒无事件提示。

## AgentBridge 设计

### 请求上下文

前端发送 Agent 请求时增加：

```json
{
  "node_context": {},
  "interaction_context": {
    "focus": {},
    "canvas_selection": {}
  }
}
```

后端生成 `AgentPromptContext` 时：

- 优先注入 `canvas_selection` 指向的对象摘要。
- 注入对象 source/evidence refs。
- 注入 allowed actions。
- 注入不能改变的已通过能力。
- 不注入完整文件正文，除非通过受控 artifact read。

### Intent 选择

`intent=auto` 解析优先级：

1. `canvas_selection` 对象和用户消息。
2. `focus.card`。
3. `app_preview` / preview health / capability gaps。
4. V1 node context。

示例：

- 选中 `capability_gap:gpt-image-1-not-configured`，用户说“修复这个”：`repair_generated_app`。
- 选中 `capability:image_generation.single`，用户说“验证一下”：`verify_capability`。
- 选中 `scenario:buyer-upload-reference`，用户说“这个场景补充…”：`edit_business_object`。

## 数据与持久化

V2 不引入数据库。

事实源仍是：

- `runs/<run_id>/team_run_record.json`
- `runs/<run_id>/app_contract.json`
- `runs/<run_id>/planning/*`
- `runs/<run_id>/codex/*`
- `runs/<run_id>/generated_apps/<slug>/`
- `runs/<run_id>/app_patches/*`
- `runs/<run_id>/app_repairs/*`
- `runs/<run_id>/adjustment_events.jsonl`

可选缓存：

```text
runs/<run_id>/canvas_projection.json
```

缓存必须可删除重建，不得作为唯一事实源。

## 分阶段实施路线

V2 生成画布按三个可验收阶段实施。每一阶段都必须能独立演示、独立回归，并保留 V1 工作台作为降级路径。

### V2.0：业务节点轨道与对象投影

目标：把现有 run artifacts 转成业务用户能理解的 runtime 聚合业务节点和 `CanvasObject` 列表，先不做自由拖拽画布。

输入：

- 现有 run artifacts、`NodeContext`、preview status、evaluation artifacts 和 adjustment events。
- V1 节点事实层、文件预览、应用预览和右侧 Agent。
- `docs/app_generation_canvas_experience_spec.md` 中的业务节点、对象状态机和安全边界。

中间过程：

1. 建立 `CanvasProjectionBuilder`，只读 artifacts，生成 `CanvasProjection`。
2. 固定 6 个 runtime 聚合业务节点，并维护 V1 runtime node 到 V2 业务节点的映射。
3. 从 PRD、规格、规划、实现、验证、预览、patch 和 repair 产物抽取 `CanvasObject`。
4. 暴露只读 Canvas API。
5. 前端增加业务对象视图、对象详情和 `CanvasSelectionContext` 状态。
6. 右侧 Agent 请求携带当前选中对象摘要，但仍复用现有 AgentBridge。

输出：

- `CanvasProjection` API。
- 业务节点轨道和对象详情。
- `CanvasObject` 列表和对象详情。
- Agent 请求中的 `CanvasSelectionContext`。

验收：

- 页面默认展示中文业务节点，而不是工程 node id。
- 删除浏览器 localStorage 后，业务节点和对象仍可从 artifacts 重建。
- 点击对象后，右侧 Agent 请求包含 `CanvasSelectionContext`。
- 投影层不读取 secret、不修改 artifacts、不启动 preview、不调用 Agent。

### V2.1：Runway Timeline 主视图与 Agent 动作闭环

目标：把中间区升级为“竖向 Runway Timeline + 当前 BusinessStep 详情”，并让右侧 Agent 围绕选中步骤或对象生成可确认动作。

输入：

- V2.0 的 `CanvasProjection`、`CanvasObject` 和 `CanvasSelectionContext`。
- 现有 `patch_app`、`delegate_code_repair`、`rerun_from_node`、preview 和 artifact preview API。
- `docs/app_generation_agent_bridge_spec.md` 中的 V2 AgentIntent / AgentAction 契约。

中间过程：

1. 将中间主视图从工程节点详情升级为 Runway Timeline，保留开发者详情入口。
2. `flow_steps[]` 增加 `prd_entry` 和 `app_preview` 两个 UI step，形成 8 步主流程。
3. 在当前步骤详情内按对象类型、状态和业务节点展示能力、页面、数据、provider、预览、缺口和修复候选。
4. `intent=auto` 优先读取选中步骤/对象和用户消息，再回退 V1 node context。
5. 将 `repair_generated_app` 映射到 `patch_app` 或 `delegate_code_repair`。
6. 将 `verify_capability` 映射到 preview health、runtime smoke 或后续 capability scanner。
7. 对修改事实源的动作展示确认卡、diff、验证计划和回滚入口。

输出：

- Runway Timeline 主视图。
- 对象化 AgentAction 卡片。
- Code Agent 修复进度卡片。
- patch / repair / rollback / promotion candidate 的版本事件。

验收：

- 用户选中能力缺口后说“修复这个”，Agent 生成 `repair_generated_app`，不是泛泛解释节点。
- 用户选中应用能力后说“验证一下”，Agent 生成 `verify_capability`。
- 复杂代码修改统一委托 `CodeAgentExecutor`，PI-Agent 不直接写代码。
- 确认前不写文件；确认后有 progress、diff、验证结果和证据落盘。

### V2.2：ContextObject、版本回放与规则提升

目标：让 PRD 之外的业务场景、样例数据、领域知识、参考应用、工具能力和用户反馈成为可追踪上下文对象，并支持版本回放和规则提升候选。

输入：

- V2.1 的对象画布和对象化 AgentAction。
- benchmark metadata、reference app、用户反馈、Project Skills、工具调用和调优事件。
- `app_patches/*`、`app_repairs/*`、`adjustment_events.jsonl`、publish records。

中间过程：

1. 抽取或登记 `ContextObject`，记录来源、可信度、使用节点和关联对象。
2. 把 benchmark、reference app、用户反馈和 preview 缺口关联到能力对象。
3. 构建版本线：初始生成、发布快照、patch、delegate repair、rollback 和 promotion candidate。
4. 成功修复只生成“提升为生成规则”的候选记录，不自动修改模板、benchmark 或 verifier。
5. 所有上下文和版本对象都必须脱敏，并能从 artifacts 重建。

输出：

- `ContextObject` 投影和登记入口。
- 版本回放时间线。
- 规则提升候选对象。
- 上下文到业务节点、能力对象和证据的引用关系。

验收：

- 用户能看到“哪些场景/知识/工具影响了这个能力”。
- 每次 patch / repair 都能回放用户输入、Agent 判断、diff、验证结果和预览状态。
- 规则提升必须等待用户确认，不能自动修改上游生成规则。
- `ContextObject` 不包含 API key、完整 `.env` 或未授权文件正文。

## 关键任务输入输出契约

| 任务 | 输入 | 中间过程 | 输出 | 可验收信号 |
| --- | --- | --- | --- | --- |
| `CanvasProjectionBuilder` | run artifacts、preview status、evaluation、adjustment events | 只读聚合、脱敏、路径归一、状态映射 | `CanvasProjection` | 同一 run 多次构建稳定；缺非关键 artifact 降级 warning |
| Canvas API | projection builder、run id、object id | path confinement、redaction、404/403 处理 | `/canvas`、`/canvas/objects/<object_id>` | 跨 run object 被拒绝；API 不泄露 secret |
| 业务节点轨道 | `business_nodes[]` | 中文业务文案、对象计数、最近事件 | 中间区业务节点视图 | 默认不显示英文 node id |
| 对象详情 | `CanvasObject`、artifact refs、evidence refs | 摘要、证据、可编辑字段、可执行动作 | 对象详情卡 | artifact 可预览，长文本不溢出 |
| Code Agent 进度 | progress artifacts、SSE、repair status | stdout JSONL 到业务事件映射 | timeline / 进度卡 | 30 秒无事件有明确等待提示 |
| Agent 对象联动 | `CanvasSelectionContext`、用户消息 | intent 路由、allowed actions 过滤 | AgentAction | 修复类请求进入 `patch_app` 或 `delegate_code_repair` |
| ContextObject | 用户补充、benchmark、skills、工具调用 | 脱敏、来源记录、引用关联 | context objects | 可解释上下文如何影响能力 |
| 版本回放 | publish、patch、repair、rollback、adjustment events | 版本事件聚合、证据引用 | version timeline | patch/repair 可回放且旧证据保留 |

## 安全边界

- Canvas API 只读，除非显式调用受控 action。
- `CanvasObject` 和 `ContextObject` 只包含摘要和 refs。
- 不读取 `.env` 原文。
- 不把 API key 注入 Agent prompt。
- 不允许 canvas action 直接写 worktree 或 `codex/`。
- 已发布应用修改仍走 `patch_app` / `delegate_code_repair`。
- 业务对象编辑进入 override 或新 run，不覆盖旧 artifact。

## 测试策略

### 单元测试

- `CanvasProjectionBuilder` 能从 fixture run 生成 8 个 `flow_steps` 和 6 个 runtime 聚合业务节点。
- `CanvasObject` 包含稳定 id、类型、状态、refs。
- 缺 artifact 时降级为 warning，不崩溃。
- secret 样式字符串被脱敏。
- `CanvasSelectionContext` 拒绝跨 run object id。

### Dashboard 测试

- Canvas API 返回 projection。
- 前端 JS 包含 canvas state、fetch、render 和 selection handling。
- 点击对象后右侧 Agent payload 包含 `canvas_selection`。
- V2 action 映射到现有 patch/reair/rerun API。

### AgentBridge 测试

- 选中 capability gap + “修复这个” -> `repair_generated_app`。
- 选中 capability + “验证一下” -> `verify_capability`。
- 选中 scenario + “补充这个场景” -> `edit_business_object`。
- 未选对象时回退 V1 node intent。

### 回归命令

```bash
python3 -m unittest tests.test_dashboard tests.test_agent_bridge tests.test_codex_executor tests.test_app_generation -v
node --check dashboard/app_generation.js
```

## 实施顺序

推荐按可回滚切片推进：

1. V2.0 基线：fixture、schema 测试、`CanvasProjectionBuilder`、只读 API。
2. V2.0 UI：业务节点轨道、对象列表、对象详情、`CanvasSelectionContext`。
3. V2.1 可观测：Code Agent 进度业务化、右侧修复进度卡片。
4. V2.1 Agent：对象化 intent/action、确认卡、`patch_app` / `delegate_code_repair` 映射。
5. V2.1 主视图：Runway Timeline、当前步骤详情、状态筛选、证据预览和版本事件入口。
6. V2.2 上下文：`ContextObject` 投影、上下文登记、引用关系。
7. V2.2 回放：版本时间线、规则提升候选、安全回归和端到端验收。

## 主要风险

- **风险：对象投影和 runtime facts 不一致。**
  - 缓解：投影只读、可重建、附 evidence refs。
- **风险：前端文件继续膨胀。**
  - 缓解：拆分 canvas render / state / agent helpers。
- **风险：Agent 绕过确认修改事实源。**
  - 缓解：V2 action 映射到 V1 受控 API。
- **风险：业务文案掩盖真实失败。**
  - 缓解：对象详情保留 evidence、risk 和开发者详情入口。
- **风险：上下文对象泄露 secret。**
  - 缓解：只保存摘要、来源、引用和脱敏内容。
