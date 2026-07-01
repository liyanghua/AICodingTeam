# APP-generation Runway Timeline 体验规范

## 状态

本文档定义 `APP-generation` Dashboard 从当前 V1/V2 混合页面收敛到 **Runway Timeline** 主体验的规范。当前处于 **spec-first / 待实现** 阶段，不代表前端、API、AgentBridge 或 CanvasProjection 已完整实现本文档描述的全部能力。

Runway Timeline 的参考原型是：

```text
design-demos/app-generation-runway-timeline.html
```

本文档不是新增运行时内核，也不是引入 n8n、LangGraph 或自由拖拽画布。它是在现有 Team Runtime、run artifacts、CanvasProjection、NodeContext、AgentBridge、CodeAgentExecutor、preview runner 和人工确认 gate 之上，定义一个更稳定、业务化、可观测的产品主视图。

## 目标

Runway Timeline 解决当前 `PRD -> 可预览应用` 体验中的四类问题：

1. 页面同时暴露 V1 工程节点流和 V2 画布流，用户分不清主线。
2. 业务流程和工程证据混在一起，用户很难理解 PRD 如何一步步变成应用。
3. `implementation` / Code Agent 执行耗时最长，但用户只看到运行中，不知道当前在做什么。
4. 右侧 Agent 经常解释节点，而不是围绕当前步骤或预览问题形成可执行修复。

升级后的默认心智必须是：

```text
PRD 输入
-> 理解业务目标
-> 编译业务规格
-> 规划应用结构
-> 生成应用原型
-> 验证业务能力
-> 输出可交付版本
-> 可预览应用
-> 右侧 Agent 增量修复 / 重跑 / 证据查看
```

## 产品原则

- **业务流程优先**：默认主视图只展示业务步骤，工程 node id、artifact path、executor、provider、raw JSON 进入证据层。
- **单一主叙事**：生产页面不得同时把 V1 工程节点流和 V2 业务流程作为两个并列主流程。
- **步骤即对象**：用户点击任意步骤后，详情区必须展示该步骤的输入、执行过程、输出、可操作项、当前对象和工程证据。
- **长过程可理解**：Code Agent 执行不能只显示 spinner，必须展示业务化阶段、最近事件、等待提示和日志入口。
- **Agent 围绕选择工作**：右侧 Agent 必须围绕当前 `BusinessStep` 或 `CanvasObject` 工作，不能只围绕内部 node id。
- **修复不重写全流程**：应用预览中的高频问题默认走 `delegate_code_repair` 或受控 `patch_app`，不是默认重跑完整 PRD 流程。
- **证据不消失**：工程证据仍可查、可预览、可复制，但默认折叠，不压过业务叙事。

## 页面结构

Runway Timeline 使用三栏主结构：

```text
┌────────────────────┬──────────────────────────────────────────┬────────────────────┐
│ 任务列表 / 新建任务 │ Runway Timeline + 当前步骤详情             │ 右侧 Agent 协作区    │
│                    │ ┌─────────────┬────────────────────────┐ │                    │
│ 历史 run            │ │ 竖向业务流程 │ 步骤详情 / 证据 / 预览   │ │ 对话 / 动作 / 修复进度 │
│ 对比组              │ │ 当前状态     │ 当前步骤对象            │ │ 可确认 action card     │
└────────────────────┴──────────────────────────────────────────┴────────────────────┘
```

### 左侧任务区

左侧只承担任务选择和创建入口：

- 历史 run 列表。
- comparison group。
- 刷新。
- `新建任务`。
- run 状态摘要。

左侧不得再作为主要 PRD 输入区。PRD 上传和粘贴属于 `PRD 输入` 步骤详情。

### 中间区

中间区必须拆成两列：

- 左列：竖向 Runway Timeline。
- 右列：当前 `BusinessStep` 详情。

左列业务流程是页面主线。右列详情随选中步骤变化。

默认不得展示独立的 V1 工程节点主流程。工程节点必须作为当前步骤的证据层出现，提供“展开工程证据”入口。

### 右侧 Agent 区

右侧 Agent 固定显示，不被预览 iframe 或中间区压缩成窄条。

右侧 Agent 展示：

- 当前选择上下文。
- 对话日志。
- 可确认动作卡片。
- `delegate_code_repair` 或 `patch_app` 执行进度。
- diff / dry-run / verify / rollback 摘要。

## BusinessStep 契约

`/canvas` 必须返回 `flow_steps[]`，用于渲染 Runway Timeline。第一阶段固定 8 个步骤：

| step_id | 标题 | 类型 | 是否对应 runtime node |
| --- | --- | --- | --- |
| `prd_entry` | PRD 输入 | ui | 否 |
| `business_goal_understanding` | 理解业务目标 | business | 是 |
| `business_spec_compilation` | 编译业务规格 | business | 是 |
| `app_structure_planning` | 规划应用结构 | business | 是 |
| `prototype_generation` | 生成应用原型 | business | 是 |
| `capability_verification` | 验证业务能力 | business | 是 |
| `delivery_version` | 输出可交付版本 | business | 是 |
| `app_preview` | 可预览应用 | ui | 否 |

每个 `BusinessStep` 至少包含：

```json
{
  "id": "prototype_generation",
  "title": "生成应用原型",
  "step_type": "business",
  "status": "running",
  "input_summary": [],
  "process_summary": [],
  "output_summary": [],
  "available_actions": [],
  "runtime_nodes": ["implementation"],
  "evidence_refs": [],
  "object_counts": {},
  "latest_event": "",
  "execution_progress": {}
}
```

字段规则：

- `id` 使用稳定英文 id。
- `title` 使用业务中文。
- `step_type` 只能是 `ui` 或 `business`。
- `status` 使用统一状态机。
- `runtime_nodes` 只作为证据映射，不在默认 UI 暴露。
- `evidence_refs` 只包含可受控预览的摘要引用。
- `execution_progress` 只用于长过程摘要，不替代 run 事实状态。

## 步骤状态机

Runway Timeline 使用业务状态，不直接暴露内部 node status：

| 状态 | 文案 | 含义 |
| --- | --- | --- |
| `not_started` | 未开始 | 等待上游步骤完成 |
| `ready` | 可开始 | 输入已就绪，可启动或等待 runtime |
| `running` | 进行中 | 对应节点或流程正在执行 |
| `generated` | 已生成 | 产物存在，但未必完成验收 |
| `verified` | 已验证 | 有验证证据通过 |
| `needs_attention` | 需关注 | 有 warning、能力缺口或用户反馈问题 |
| `blocked` | 已阻塞 | 缺少必要输入、验证失败或安全风险 |
| `delivered` | 已交付 | 已形成可交付版本或可预览应用 |

UI 不能仅凭前端渲染成功把步骤标为 `verified` 或 `delivered`。状态必须从 run artifacts、preview record、verification record、patch/repair record 或 run record 推导。

## 步骤详情结构

点击任意步骤后，详情区必须按固定顺序展示：

1. **输入**：本步骤消费的 PRD、规格、计划、应用、预览或用户反馈。
2. **执行过程**：业务化过程摘要、当前进度、最近事件、风险或等待提示。
3. **输出**：本步骤产生的业务对象、artifact、应用代码、验证记录或交付结果。
4. **你可以让 Agent 做什么**：解释、查看输入输出、查看证据、重跑、修复、验证。
5. **当前步骤对象**：该步骤相关 `CanvasObject` 摘要。
6. **工程证据**：对应 runtime nodes、artifact refs、日志、diff、verification，默认折叠。

所有区域必须有明确的换行、截断或滚动策略，路径、错误、JSON 和长中文段落不得溢出边框。

## PRD 输入步骤

`prd_entry` 是用户发起任务的起点，不新增 Team Runtime node。

详情展示：

- 输入：PRD 文本、PRD 文件。
- 执行过程：选择 executor、provider、model、app slug、comparison group。
- 输出：新 run、`input_prd.md`、进入下一步。
- 可操作项：启动生成、检查 PRD、补充生成约束。
- 工程证据：生成前为空；生成后显示 run record 和输入 artifact。

新建任务规则：

- 点击左侧 `新建任务` 只进入本地 UI 初始态，不创建 run。
- 点击 `启动生成` 后才创建真实 app_generation run。
- 成功后自动选中新 run 并订阅 SSE。
- 失败时停留在 `PRD 输入`，展示可行动错误。

## 生成应用原型步骤

`prototype_generation` 是用户等待最长的步骤，必须重点可观测。

详情必须展示：

- 当前 Code Agent 阶段。
- 最近 3-5 条业务进度。
- 已运行多久。
- 最近产物或文件变更摘要。
- 最近验证命令摘要。
- `30 秒无新事件` 提示。
- blocker / warning。
- 证据入口：`codex/coder_progress.jsonl`、`codex/coder_progress_status.json`、`codex/diff.patch`、`codex/app_runtime_verification.json`。

业务化阶段示例：

| 事件 | 展示文案 |
| --- | --- |
| prompt ready | 正在准备应用生成上下文 |
| process started | Code Agent 已启动 |
| file change | 正在生成或修改应用文件 |
| node --check | 正在检查应用代码语法 |
| runtime smoke | 正在模拟用户操作 |
| verification | 正在验证业务能力 |
| diff ready | 候选改动已准备好 |
| no event 30s | Code Agent 仍在运行，暂无新输出 |

不得默认展示完整 stdout、完整 prompt、完整源码或 secret。

## 可预览应用步骤

`app_preview` 是生成流程终点，不新增 Team Runtime node。

详情展示：

- 输入：已生成应用、验证记录、交付报告。
- 执行过程：发布快照、启动预览、健康检查、日志。
- 输出：preview URL、端口、进程、可试用应用。
- 可操作项：发布应用、启动预览、停止预览、刷新、外部打开、查看日志、修复预览问题。
- 工程证据：`app_publish.json`、`preview/preview_run_record.json`、preview logs、repair records。

状态规则：

```text
未生成 -> 未发布 -> 已发布·已停止 -> 启动中 -> 运行 / 降级 / 失败
```

未发布时 `启动预览` 必须禁用，并提示先发布。关闭 iframe 不等于停止 preview 进程。

## Agent 联动

前端发送 Agent 请求时必须携带当前步骤选择：

```json
{
  "selection_type": "flow_step",
  "step_id": "app_preview",
  "step_type": "ui",
  "title": "可预览应用",
  "status": "needs_attention",
  "runtime_nodes": ["preview_delivery"],
  "allowed_actions": [
    "explain_step",
    "explain_step_io",
    "inspect_evidence",
    "delegate_code_repair"
  ]
}
```

路由规则：

| 用户说法 | 默认 intent/action |
| --- | --- |
| “这一步在干什么” | `explain_step` |
| “输入输出是什么” | `explain_step_io` |
| “看证据 / 日志 / 产物” | `inspect_evidence` |
| “重新跑这一步” | `rerun_step`，映射到最小可执行 runtime node |
| “预览报错 / 按钮没反应 / 模型不对 / 生图失败” | `delegate_code_repair` 优先，简单锚点问题可 `patch_app` |

当选择具体 `CanvasObject` 时，`canvas_object` 优先于 `flow_step`。也就是说，用户选中能力缺口后说“修复这个”，应围绕该缺口生成 `repair_generated_app`，不是泛泛解释步骤。

## 工程证据层

工程证据层是默认折叠的事实层。它必须按当前步骤过滤：

```text
工程证据
- 对应工程节点
- 输入 artifact
- 执行进度 / 日志 / tool calls
- 输出 artifact
- 风险 / blocker / verification
```

提供“查看全部工程节点”开关，但默认关闭。

工程证据可以包含内部 `node_id`、artifact path、JSON、stdout 摘要和 diff 引用。它不得展示 secret、完整 `.env`、未授权文件正文或完整 prompt。

## 分阶段实施

Runway Timeline 作为 V2.1.6 / V2.2 主视图收敛，按四个可审核切片实施：

1. **主视图收敛**：三栏结构、竖向 Runway Timeline、步骤详情、工程证据折叠。
2. **BusinessStep 投影补齐**：`flow_steps[]` 8 步契约、状态机、输入/过程/输出/动作/证据。
3. **长过程与预览终点**：`prototype_generation` Code Agent 进度、`app_preview` 发布/启动/iframe/日志/修复入口。
4. **Agent 操作台**：`flow_step` selection、`delegate_code_repair` 优先路由、action card、repair progress、验证结果。

每个切片必须能独立回归。任何切片都不得要求引入新编排内核或重写 Team Runtime。

## 验收标准

### AC-RUNWAY-001 单一主流程

页面默认只展示 Runway Timeline 作为主流程，不同时展示 V1 工程节点流作为并列主流程。

### AC-RUNWAY-002 8 个 BusinessStep

`/canvas` 返回 8 个 `flow_steps`，包含 `prd_entry` 和 `app_preview` 两个 UI 步骤，以及 6 个业务步骤。

### AC-RUNWAY-003 步骤详情完整

点击任意步骤后，详情区展示输入、执行过程、输出、可操作项、当前步骤对象和工程证据。

### AC-RUNWAY-004 PRD 输入是起点

新建任务进入 `PRD 输入` 初始态；点击 `启动生成` 前不创建 run。

### AC-RUNWAY-005 app_preview 是终点

发布、启动预览、iframe、日志和修复入口都位于 `可预览应用` 步骤详情。

### AC-RUNWAY-006 Code Agent 长过程可理解

`生成应用原型` 步骤展示业务化进度、最近事件、运行时长和 30 秒无新输出提示。

### AC-RUNWAY-007 Agent 围绕步骤工作

选中 `flow_step` 后，Agent 请求携带 `CanvasSelectionContext.selection_type="flow_step"`，并能解析解释、输入输出、证据、重跑和修复类请求。

### AC-RUNWAY-008 工程证据默认折叠

工程 node id、artifact path、raw JSON、stdout 和 diff 不出现在默认主流程中，但可在当前步骤证据层中查看。

### AC-RUNWAY-009 内容不溢出

步骤标题、路径、错误、JSON、日志摘要、Agent action card 和对象详情都必须在容器内换行、截断或滚动。

### AC-RUNWAY-010 不改变事实源

Runway Timeline 是投影和交互层。事实状态仍以 run artifacts、run record、verification、preview record、patch/repair record 为准。
