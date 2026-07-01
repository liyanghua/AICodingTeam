# PRD 生成轻量本地应用验收与测试策略

## 状态

本文档定义已实现 v1 `app_generation` 能力的验收和测试策略。当前仓库已有 domain pack、CLI、Dashboard PRD 模式、Codex fake 生成测试和端到端验收测试。

## 验收标准

### AC-001 原始 PRD 可审计

用户通过 PRD 文本或 PRD 文件提交需求后，系统必须在 run 目录写入 `input_prd.md`。该 artifact 是后续需求理解和评审的来源之一。

验证信号：

- `input_prd.md` 存在。
- run record 的 artifact 列表包含 `input_prd.md`。
- 摘要、报告和 Dashboard 不泄露 secret。

### AC-002 标准化 PRD 明确边界

系统必须生成 `requirements/normalized_prd.md`，并明确目标用户、核心流程、页面状态、数据对象、范围内、范围外、假设和 blocker。

验证信号：

- 标准化 PRD 包含业务目标、用户、主流程、非目标和安全约束。
- 阻塞问题不会被当作事实实现。

### AC-003 应用契约固定 v1 技术形态

系统必须生成 `app_contract.json`，并声明默认技术形态：

- `frontend=native_spa`
- `backend=node_stdlib`
- `storage=localStorage`
- `database=none`

验证信号：

- `app_contract.json` 可解析。
- 契约包含 `generated_app_dir`、`required_files`、`preview.command`、`preview.url`。

### AC-004 生成代码路径受控

生成代码必须位于 `generated_apps/<app_slug>/`，不得写入未允许路径。

验证信号：

- changed files 全部位于允许路径。
- `app_slug` 校验拒绝路径穿越、空白、`.`、`..`、斜杠和反斜杠。
- Codex boundary violation 会导致失败或 blocker。

### AC-005 本地应用可预览

生成应用必须包含最小文件结构：

```text
generated_apps/<app_slug>/
  README.md
  server.js
  public/index.html
  public/styles.css
  public/app.js
```

验证信号：

- `server.js` 通过 `node --check`。
- `preview_instructions.md` 包含本地启动命令和预览地址。
- `README.md` 说明应用用途、运行方式和限制。

### AC-006 持久化只使用 localStorage

浏览器端状态只能保存在 `localStorage`。不得生成数据库、数据库连接、迁移、真实后端持久化或 secret storage。

验证信号：

- 生成代码不包含数据库依赖、连接字符串或迁移文件。
- `public/app.js` 使用 `localStorage` 时不保存 secret。
- 风险扫描没有发现 secret persistence。

### AC-007 风险和 blocker 不隐藏

PRD 中无法实现或不应实现的部分必须被记录为 blocker、assumption 或 mocked behavior，不能静默跳过。

验证信号：

- `code_run_record.json`、`review_report.md`、`test_report.md` 或 `final_report.md` 包含风险事件。
- Dashboard 能展示风险事件和 blocker。

### AC-008 README 不误导

README 只能声明当前真实可用的 v1 本地原型能力，不能暗示生产级应用交付、数据库、自动部署、公开托管或绕过人工 apply gate。

验证信号：

- README 中的 `app generate` 示例与真实 CLI 参数一致。
- README 明确说明生成代码仍在隔离 worktree 中接受 review、verification 和人工 apply。

### AC-009 工作台节点可观测

`PRD生成应用` 后续工作台必须能展示从 PRD 到交付的固定节点列表，并允许用户点击任意节点查看输入、执行过程和输出。

验证信号：

- 页面或 API 返回固定节点：`skill_routing`、`prd_input`、`prd_normalization`、`context_contract`、`planning_tdd`、`implementation`、`review_quality`、`verification`、`preview_delivery`。
- 每个节点包含 inputs、process、outputs。
- 缺失 artifact 时显示未生成、等待执行或 blocked，不显示 completed。

### AC-010 Skill、tool call 和 usage 可见

工作台必须展示每个节点关联的 Project Skills、已记录 tool calls 和 usage。

验证信号：

- 节点能展示 skill id、角色、使用原因和输入输出。
- tool calls 从现有 run artifacts 聚合；缺失时显示 `未记录`。
- rule variant token 为 0。
- Codex/LLM usage 缺失时显示 `unknown`，不得伪造 token。

### AC-011 右侧 Agent Provider 可切换

右侧 Agent 区默认 Provider 为 `codex`，可切换到 `pi_agent` 或 `llm`。Provider 切换不得改变中间节点事实。

验证信号：

- 默认 Provider 是 Codex。
- PI-Agent 未配置时返回清晰 `not_configured` 状态。
- 切换 Provider 后仍使用当前 `NodeContext`。
- Agent 返回的是可确认动作，不直接写 artifact。

### AC-012 从节点重跑保留旧 run

用户可以从任意节点基于调整说明触发重跑。重跑必须创建新 run，并保留旧 run。

验证信号：

- rerun payload 包含 `source_run_id`、`rerun_from_node`、`selected_variant`、`override_instructions`、`comparison_group_id`。
- 源 run artifacts 不被修改。
- 新 run 出现在同一 comparison group 中。

### AC-013 业务友好节点标题和详情文案

工作台默认展示必须面向业务用户。节点流只展示中文业务标题、状态和摘要，不用英文 `node_id` 或技术字段作为主要文案。

验证信号：

- 固定节点默认标题为：`Skill 路由`、`PRD 输入`、`PRD 标准化`、`应用契约`、`规划与验收`、`应用实现`、`质量评审`、`验证结果`、`预览交付`。
- `node_id`、executor、provider、artifact path、raw JSON 和日志只出现在开发者详情、文件预览或可展开原始信息中。
- usage 文案使用 `输入 Token`、`输出 Token`、`总 Token`、`预估成本` 等业务可读标签。
- 风险状态使用 `需关注`、`已阻塞`、`未记录` 等业务可读表达。

### AC-014 中间区两列布局与详情卡片

工作台中间区域必须拆成两列：左列为按顺序竖排的节点流，右列为当前节点详情和中间产物。

验证信号：

- 节点流按 PRD 到交付顺序纵向排列，不使用横向 wrap 作为默认布局。
- 点击节点后，右列展示对应节点详情，不覆盖左侧任务列表和右侧 Agent 协作区。
- 节点详情固定包含卡片：`Skill 路由`、`变体与对比`、`Project Skills`、`输入`、`输出`、`Tool calls · Usage · Scores · 风险`。
- 详情卡片使用和背景不同的浅色表面，可用蓝色边框强调当前节点信息。
- 卡片标题和卡片详情均为业务友好语言，原始技术信息放入可展开详情。

### AC-015 文件预览竖栏和多类型预览

中间产物中的文件引用必须支持只读文件预览。文件预览以额外竖栏展示，不替代右侧 Agent 协作区。

验证信号：

- 文件预览只能读取当前 run artifacts 或允许的 `generated_apps/<app_slug>/` 文件。
- preview path 拒绝绝对路径、路径穿越、跨 run 读取和未允许仓库路径。
- 文本、代码、Markdown、JSON、YAML、HTML、CSS 和 JS 支持文本或代码预览，JSON 可格式化展示。
- 图片支持内联预览。
- PDF 支持浏览器内嵌预览。
- 未知二进制显示文件名、大小、类型和不可内联预览提示。
- 超大文件只显示元信息和大小限制提示，不默认加载正文。
- 打开或关闭预览不改变 `NodeContext.context_revision`，除非 artifact 引用或 hash 变化。

### AC-016 节点与卡片文字不得溢出边框

节点流、详情卡片、文件列表、风险描述、路径、JSON 片段和错误信息不得出现文字溢出边框或遮挡其他内容。

验证信号：

- 节点标题、摘要和状态在窄屏和宽屏下均不溢出节点容器。
- 卡片内长单词、路径、URL、JSON key、错误栈和日志片段有换行、截断或内部滚动策略。
- 按钮、状态徽标和卡片标题不会因为长文本改变稳定布局。
- 文件预览竖栏中的长路径和二进制提示不遮挡关闭、复制或定位操作。

### AC-017 列宽可伸缩且预览位于中间与 Agent 之间

工作台布局必须支持列宽伸缩。中间节点区可按需伸缩，文件预览竖栏位于中间区与右侧 Agent 协作区之间，右侧 Agent 保持固定可用宽度，左侧任务列表不得被压缩到影响可读性。

验证信号：

- 中间区列宽不是单一固定像素值，存在可伸缩的布局约束。
- 文件预览竖栏打开后出现在中间区和 Agent 区之间，而不是覆盖 Agent 面板。
- 左侧任务列表在预览开启后仍保持最小可读宽度。
- 右侧 Agent 面板在预览开启后仍保持可输入、可对话、可选择 Provider。
- 窄屏下允许降级为单列，但桌面视图默认遵循左侧任务列表、中间节点/预览、右侧 Agent 的顺序。

### AC-044 一键启动应用预览

工作台必须能从 `app_generation` run 一键启动生成应用预览，并记录独立 preview 进程状态。

验证信号：

- 启动前必须先完成「发布到预览」，将 `runs/<run_id>/worktree/generated_apps/<app_slug>/` 拷贝快照到 `runs/<run_id>/generated_apps/<app_slug>/`；未发布时返回 412 + `{"error": "app_not_published", "hint": "请先点「发布到预览」"}`。
- `POST /api/app-generation/runs/{run_id}/preview/start` 从 `runs/<run_id>/generated_apps/<app_slug>/` 唯一定位应用目录（不再读 worktree）。
- 缺少 `app_publish.json` 时返回 412 + `{"error": "missing_publish_record", "hint": "请重新发布"}`。
- preview runner 同时注入 `PORT` 和 `PREVIEW_PORT`。
- 启动成功后写入 `preview/preview_run_record.json` 和 `preview/preview.log`。
- 同一 run 重复启动 preview 时，旧 preview 被停止或标记 stale，不残留多个 active preview。
- 启动失败时返回可行动错误，不改变 run status。

### AC-045 内嵌浏览器打开生成应用

一键预览成功后，工作台必须在预览竖栏内嵌浏览器打开生成应用。

验证信号：

- 应用预览复用文件预览竖栏，`file_preview` 与 `app_preview` 互斥切换。
- iframe `src` 使用 preview start API 返回的本地 URL。
- 预览竖栏展示状态、端口、健康检查信息、启动时间和日志路径。
- `停止` 按钮调用 stop API 并回收进程。
- `刷新` 刷新 iframe 或重新读取 preview status。
- `外部打开` 在新标签页打开 preview URL。
- 关闭预览竖栏只隐藏 iframe，不停止 preview 进程。
- 右侧 Agent 不被预览栏压缩成窄条。

### AC-046 Preview path confinement 与 secret redaction

一键预览必须保持路径和 secret 安全边界。

验证信号：

- preview path 拒绝绝对路径、路径穿越、跨 run 读取和非 `generated_apps/` 目录。
- preview command 只允许白名单可执行文件。
- `.env` 同步只复制图片 provider 白名单字段。
- API response、SSE、preview record、日志摘要和 Agent prompt 不包含真实 API key。
- `.env.example` 只能包含占位 key。

### AC-047 图片类 PRD 必须生成生图能力

当 PRD 要求图片生成、主图生成、生图、模型选择或图片 provider 时，生成应用必须包含图片生成用户路径。

验证信号：

- 前端存在单张生图按钮；PRD 要求批量时存在批量生图按钮。
- 前端显示模型选择或当前模型。
- 前端显示 provider 配置状态和错误提示。
- 服务端存在 `GET /api/health`。
- 服务端存在 `POST /api/images/generate`。
- OpenRouter 使用 `/api/v1/images` + `input_references`。
- API key 只从服务端 `.env` 或进程环境读取，不进入前端、localStorage、run artifacts 或日志。

### AC-048 Agent 聚焦 app_preview 后能生成 patch_app 动作

用户打开应用预览后，右侧 Agent 必须能基于 `app_preview` focus、preview status、provider health 和生成应用能力缺口直接生成 `patch_app` 动作。

验证信号：

- `NodeContext` 包含 `preview_status`、`preview_url`、`preview_health`、`provider_health`、`generated_app_capability_gaps` 摘要，且 `preview_status` 含 `published_at`、`source_commit`、`app_patches_count`、`invalidated_by_rerun`。
- `AgentInteractionContext.focus.card="app_preview"`。
- 用户说“缺少生图按钮”“加模型选择”“API Key 怎么配”“这个预览哪里不对”时，`intent=auto` 解析为 `patch_app` action。
- `patch_app` 必须列出 `target_path`（run-relative，例如 `generated_apps/<slug>/public/app.js`）、`patch_diff`、保留能力清单和验证方式。
- 用户确认后，dashboard 先把 patch 写入 `runs/<run_id>/app_patches/<ts>__<file>.diff`，再覆写 `runs/<run_id>/generated_apps/<slug>/` 下目标文件，并更新 `app_patches/index.json`。
- 写 patch 失败或覆写失败时，原文件保持不变；Agent 返回 422 + 错误原因。

### AC-049 Agent 增量修改不得重写完整流程

右侧 Agent 的优化动作必须是最小必要修改。

验证信号：

- 对“加生图按钮”这类局部问题，Agent 不要求重写完整 PRD，不触发整节点 rerun。
- Agent action 明确保留已有四阶段工作流、产品图上传、方案单选、Prompt 生成和 localStorage 状态。
- Agent 不删除或覆盖已通过 artifact 而不落 `artifact_patches/` 证据。
- Agent 不把 API key 放入前端或 localStorage。
- 未经用户确认，不调用 rerun、patch_artifact、patch_app 或 apply。
- Agent 不修改 `runs/<run_id>/codex/` 或 `runs/<run_id>/worktree/`。

### AC-050 Stop preview 可回收进程

应用预览必须可停止并回收本地进程。

验证信号：

- `POST /api/app-generation/runs/{run_id}/preview/stop` 根据 `preview_run_record.json` 停止进程。
- stop 后 record 写入 `stopped_at`。
- stop 不改变 run status、节点状态或 artifacts。
- 无 active preview 时 stop 返回可理解状态，不报 500。

### AC-026 Provider prompt 包含业务上下文摘要

右侧 Agent 调用 Codex、PI-Agent 或其他 LLM 时，Provider prompt 必须包含足够业务上下文，确保 Agent 能回答“这个节点干什么、输入是什么、输出是什么、当前产物是什么”。

验证信号：

- prompt 包含节点业务标题和节点摘要，不只包含内部 `node_id`。
- prompt 包含当前节点输入 artifact 的 title、path、summary、status 和 content_hash。
- prompt 包含当前节点输出 artifact 的 title、path、summary、status 和 content_hash。
- prompt 包含当前 `focus.card`、`focus.artifact_ref`、`selected_text` 和 `allowed_operations`。
- prompt 包含 usage、scores、risks 的业务友好摘要，缺失时显示 `unknown` 或空数组。
- 默认不把完整 artifact 正文塞进 prompt；完整读取必须走受控 `read_artifact`。

### AC-027 intent=auto 可识别解释输入、解释输出和重跑节点

右侧 Agent 默认 `intent=auto` 时，必须能根据用户自然语言和当前 focus 解析操作意图，不要求用户手动切换 mode。

验证信号：

- 用户问“这个节点是干啥的”，返回 `resolved_intent=explain_node`，并解释节点目标、输入、输出和风险。
- 用户问“输入是什么”，返回 `resolved_intent=explain_inputs`，并列出输入 artifact 摘要。
- 用户问“输出是什么”或“产物是什么”，返回 `resolved_intent=explain_outputs`，并列出输出 artifact 摘要。
- 用户聚焦 artifact 并问“读一下这个产物”，返回 `read_artifact`，且 `requires_confirmation=false`。
- 用户在 `mode=explain` 下说“重新跑这个节点”，只要 `rerun_from_node` 被允许，就返回待确认 `rerun_from_node`，不得继续只返回 `explain_node`。
- 用户聚焦 artifact 并说"基于这个文件重新生成"，返回待确认 `rerun_from_node`（从 artifact 所属节点重跑）。
- 不在 `allowed_operations` 中的动作必须降级为解释或澄清。

### AC-051 图片能力缺口扫描可用于 Agent 优化

工作台必须能为生成应用产出能力缺口摘要，供右侧 Agent 增量优化使用。

验证信号：

- 缺少 `GET /api/health` 时产生 `health_route_missing`。
- 缺少 `POST /api/images/generate` 时产生 `image_generate_route_missing`。
- 缺少生图按钮时产生 `image_generation_button_missing`。
- 缺少模型选择或模型显示时产生 `image_model_control_missing`。
- 缺少 `.env.example` 时产生 `env_example_missing`。
- 检测到前端或 localStorage 保存 API key 时产生 blocking risk。
- capability gap 只作为摘要进入 `NodeContext`，不伪造成最终评分。

### AC-018 Benchmark 目录可审计

评估体系必须支持 `benchmarks/app_generation/<benchmark_id>/` 目录契约。benchmark 必须包含原始 PRD、验收标准、机器可读能力清单、评分 rubric 和可选参考应用。

验证信号：

- `benchmark.yaml` 声明 `benchmark_id`、输入 PRD、参考应用角色、约束和默认验证命令。
- `input_prd.md` 是原始输入事实源。
- `acceptance_criteria.md`、`expected_capabilities.json`、`scoring_rubric.json` 存在且可审。
- `.env`、`.DS_Store`、`node_modules/` 不进入 benchmark。

### AC-019 AGQS 评分可解释

评估报告必须使用 AGQS 100 分制，并把分数拆到 PRD 理解、验收覆盖、产品流程、UI 交互、工程可运行、安全边界和成本效率。

验证信号：

- 每个维度包含分数、满分、证据引用、评分理由和风险。
- hard gate 可以限制总分或直接失败。
- 评分不能只看最终页面截图，必须引用节点产物或验证记录。

### AC-020 Dingdang benchmark 覆盖关键产品规则

`dingdang_main_image_agent` benchmark 必须覆盖 PRD 中的关键产品规则。

验证信号：

- 四阶段流程可见：需求诊断、创意方案、策略落地、Prompt 生成与执行。
- Stage 1 有任务类型确认阻断。
- Stage 2 是方案单选且禁止混搭。
- 有 8 张主图规划、平台策略差异、Prompt 分层和“第 X 张第 Y 层”局部迭代。
- 参考应用只能作为对照参考，不作为唯一标准答案。

### AC-028 Benchmark parity 模式可识别

当 `prd_file` 位于 `benchmarks/app_generation/<benchmark_id>/input_prd.md` 时，runtime 必须进入 `benchmark_parity` 模式。

验证信号：

- run 目录包含 `benchmark_context.json` 和 `benchmark_context.md`。
- `app_contract.json` 包含 `quality_mode=benchmark_parity` 和 `benchmark_id`。
- Codex prompt 包含 benchmark 必需能力和 reference app 能力基线说明。

### AC-029 Dingdang 必须支持产品图和参考图上传

Dingdang benchmark parity 生成应用必须支持产品图上传和参考图上传。

验证信号：

- 前端至少有两个文件上传控件，分别用于产品图和参考图。
- 产品图是调用图片生成前的必填输入。
- 参考图可选，但上传后必须进入参考图判断、Prompt 或 provider 请求。

### AC-030 Dingdang 必须支持显式图片 provider

Dingdang benchmark parity 生成应用必须提供显式图片 provider 代理，至少支持 OpenAI 或 OpenRouter 之一。

验证信号：

- 本地 Node server 暴露 `/api/health` 和 `/api/images/generate`。
- `.env.example` 只包含占位 key。
- API key 只在服务端读取，前端和 localStorage 不保存 secret。
- 未配置 provider、模型不支持或请求超时时，UI 显示清晰错误。

### AC-031 Prompt 与图片下载必须可用

Dingdang benchmark parity 生成应用必须支持下载 Prompt 和生成图片。

验证信号：

- 每张图有下载 Prompt 操作。
- 每张已生成图片有下载图片操作。
- provider 返回远程 URL 时，下载链路不得静默失败；可通过 server-side proxy 或 blob 化处理。

### AC-032 非阻断风险不得误判为 failed

Codex 返回的风险事件必须区分 blocking 和 warning。

验证信号：

- `exit_code=0`、schema valid、changed files 存在、无测试失败、无路径越界、无 secret 泄露时，sandbox preview EPERM 不导致 coder failed。
- provider 未配置但应用显示清晰 setup error 时，记录 warning，不阻断。
- benchmark parity 必需能力缺失仍然阻断。

### AC-021 Auto-Research 优化不直接改事实源

auto-research 风格优化必须以 benchmark run 为实验对象，输出对比、弱节点诊断和待确认优化建议，不得自动覆盖旧 run artifacts 或主工作区代码。

验证信号：

- 每次优化实验保留旧 run，并进入 comparison group。
- 优化建议能追溯到 benchmark、节点分、usage、hard gate 和证据引用。
- 对 runtime、prompt、verifier 或 UI 的改动必须经过人工确认 apply gate。
- 不得为单个 benchmark 把特例写死到通用 runtime。

### AC-022 AgentInteractionContext 联动当前卡片和产物

右侧 Agent 请求必须同时携带 `NodeContext` 和 `AgentInteractionContext`。`AgentInteractionContext` 必须描述当前详情卡片、当前 artifact、选中文本和允许操作。

验证信号：

- 点击节点只更新 `NodeContext`。
- 点击详情卡片更新 `interaction_context.focus.card`。
- 打开文件预览更新 `focus.card="artifact_preview"` 和 `focus.artifact_ref`。
- 用户选择预览文本时，`focus.selected_text` 随请求发送。
- `interaction_context.context_revision` 与 `node_context.context_revision` 不一致时返回 `context_stale`。

### AC-023 AgentAction 是改变事实源的唯一入口

右侧 Agent 可以解释、读取、对比、建议修改、建议重跑和澄清，但任何会改变输入、variant、重跑、文件或 run 状态的操作都必须转换为可确认 `AgentAction`。

验证信号：

- `read_artifact` 只读取受控 artifact，不改变 `context_revision`。
- `suggest_input_patch` 进入待确认动作区，不直接写旧输入。
- `patch_artifact` 和 `patch_app` 不覆盖旧版本：先写 `artifact_patches/<ts>__<node>__<file>.diff` 或 `app_patches/<ts>__<file>.diff` 证据，再覆写目标文件；任一步失败保持原文件不变。
- `rerun_from_node` 确认后创建新 run，旧 run 不变。
- 未确认动作不会调用 rerun、patch 或 apply gate。

### AC-024 PiAgentProvider 是薄桥接层

`PiAgentProvider` 必须只承担 PI runtime 桥接和治理职责，不实现第二套 Agent 编排。

验证信号：

- `PiAgentProvider` 负责 env/model 注入、JSONL/SSE 转译、redaction、usage、tool call 和 action 归一化。
- 业务推理、工具决策和自然语言回答由底层 PI Agent 完成。
- PI tool calls 只作为右侧 tool evidence 展示，未确认前不写 run artifacts。
- PI write/edit/bash 副作用必须在 UI 中显示路径、命令、diff 或输出摘要，并标记为不属于节点事实源。

### AC-025 PI stream 终态归一

PI-Agent 流式通道必须正确处理不同 PI runtime 的终态事件，避免重复或误报 `stream_closed`。

验证信号：

- `agent_end` 是正常终态。
- `response{success:true}` 且没有 `agent_end` 时合成为 `agent_end{stop_reason:"response_success"}`。
- `upstream_error` 是错误终态，外层不得再追加 `stream_closed`。
- 只有没有 `agent_end`、没有成功 `response` 且 stream 确实异常关闭时，才显示 `stream_closed`。

## 测试策略

### 单元测试

当前覆盖：

- `test_app_slug_validation_rejects_path_traversal`
- `test_prd_input_writes_input_prd_artifact`
- `test_app_contract_defaults_to_native_spa_node_local_storage`
- `test_app_generation_domain_pack_loads`
- `test_allowed_paths_restrict_generated_app_output`
- `test_secret_like_prd_content_is_redacted_from_summaries`

### Runtime 测试

当前覆盖：

- deterministic run 能生成 `input_prd.md`、`normalized_prd.md`、`app_contract.json` 和规划 artifacts。
- before-coding gate 在缺少关键 artifact 时失败。
- fake Codex 只在 `generated_apps/<app_slug>/` 下写文件。
- fake Codex 写到 README 或其他未允许路径时，run 记录 boundary violation。
- verifier 执行 `node --check generated_apps/<app_slug>/server.js` 并记录结果。

### Dashboard 测试

当前覆盖：

- PRD 输入模式提交 `domain=app_generation`。
- Dashboard 展示原始 PRD、标准化 PRD、coverage、slice-loop、preview instructions、diff 和风险事件。
- Dashboard 不把未通过 apply gate 的生成结果显示为已应用。

后续工作台测试应覆盖：

- 能看到节点列表。
- 能点击节点查看输入、执行过程和输出。
- 能看到 skill、tool call、usage、scores 和 risks。
- 能切换 Agent Provider。
- 能从节点重跑并保留旧 run。
- PI-Agent 未配置时不影响默认 Codex。
- 节点默认展示业务友好中文标题。
- 中间区域采用竖排节点流加节点详情的两列布局。
- 节点详情卡片完整展示固定卡片集合。
- 文件预览竖栏支持文本、JSON、图片、PDF、未知二进制和超大文件降级策略。
- 节点、卡片、文件预览中的长文本不溢出边框。
- 列宽可伸缩，预览位于中间与 Agent 之间，左侧任务列表不被压缩。
- PRD 上传 API `POST /api/app-generation/runs` 在合法 payload 下返回 `run_id` + `events_stream`，并落盘 `input_prd.md`。
- 节点 SSE `GET /api/app-generation/runs/<id>/events/stream` 首帧 `snapshot`、节点级 `node_state`、`run_finished` 顺序正确，断线重连重发 `snapshot`。
- 右侧对话 SSE `POST /api/app-generation/agent/stream` 透传 `message_delta` / `tool_call` / `tool_result` / `agent_end`，stream 关闭前缺 `agent_end` 时必发 `upstream_error{phase:"stream_closed"}`。
- 右侧对话请求携带 `NodeContext` + `AgentInteractionContext`，能根据当前卡片、artifact 和选中文本改变 Agent 回答范围。
- `agent_end.payload.actions` 能进入待确认动作区，未确认前不改变事实源。

### Benchmark 与评估测试

后续实现评估 runner 后应覆盖：

- benchmark loader 能读取 `benchmark.yaml`、`input_prd.md`、`acceptance_criteria.md`、`expected_capabilities.json` 和 `scoring_rubric.json`。
- loader 拒绝或标记 `.env`、真实 secret、`node_modules/` 和路径穿越。
- AGQS scorer 能输出总分、分维度评分、证据引用和 hard gate 状态。
- Dingdang benchmark 能检查四阶段流程、阻断点、方案单选、8 张图规划、平台策略、Prompt 分层和局部迭代。
- usage 缺失时显示 `unknown`，不伪造 token。
- auto-research 实验只产生 comparison report 和待确认建议，不修改旧 run artifacts。

### PI 子进程测试合约

PiAgentProvider 真实接入必须支持 in-process fake，不依赖系统 `pi`：

- 构造函数允许注入 `subprocess_launcher(cmd, env, cwd) -> Popen-like`。fake 实现读取预设 JSONL 序列作为 stdout，并把 stdin 写入收集到 buffer 用于断言。
- 测试场景：
  - `status_ready_when_pi_on_path`：PATH 命中时 `status=ready`，capabilities 含 `chat / tool_calls / stream`。
  - `status_not_configured_when_pi_missing`：PATH 不命中时 `status=not_configured`，message 提示 `npm i`。
  - `stream_message_emits_message_delta_and_agent_end`：fake 注入 `message_delta` × N + `agent_end` JSONL，provider 产出对应 `StreamEvent` 序列。
  - `success_response_without_agent_end_is_treated_as_terminal_agent_end`：fake 注入 `message_delta` + `response{success:true}`，provider 合成 `agent_end{stop_reason:"response_success"}`，不得显示 `stream_closed`。
  - `stream_message_passes_through_tool_call_and_result`：fake 注入 `tool_call` 与配对 `tool_result`，provider 透传到 StreamEvent。
  - `stream_message_emits_upstream_error_on_stream_closed`：fake 在未发 `agent_end` 且未发成功 `response` 时关闭 stdout，provider 必须补发且只补发一次 `upstream_error{phase:"stream_closed"}`。
  - `stream_message_redacts_api_key_substrings`：fake 注入含 `sk-ant-...` 的文本，provider 输出经过 `_redact_text` 处理。
  - `subprocess_terminated_on_provider_close`：provider 关闭时对 fake `Popen` 调用 `terminate()`。
- 真实 `pi` 二进制的端到端测试不进入单元测试集合，留作可选 manual smoke。

### SSE tailing 测试

节点 SSE 通道使用 `runs/<id>/events.jsonl` 作为事实源；测试以纯文件驱动，不启动真实 dashboard server：

- 直接构造 `runs/<id>/events.jsonl` + `team_run_record.json`，调用 `_stream_app_generation_events(run_id)` 生成器，断言：
  - 首帧为 `snapshot`，包含全部 6 个节点。
  - 文件追加新事件后，生成器在 polling 周期内吐出对应 `node_state`。
  - 写入终态后吐出 `run_finished`，生成器自然结束。
  - 中途 truncate 文件不会导致重复事件。

### PRD 上传测试

- `test_post_runs_creates_run_dir`：POST 合法 payload，断言 `runs/<run_id>/input_prd.md` 与 `team_run_record.json` 内容与请求字段一致。
- `test_post_runs_rejects_path_traversal_app_slug`：`app_slug=../foo` 必须 422。
- `test_post_runs_no_size_limit`：5 MB PRD 文本可成功上传并落盘，无前端 / 后端硬截断。
- `test_post_runs_starts_runtime_in_background`：返回 `run_id` 后短时间内 `events.jsonl` 出现 `run_started` 事件。

### 文档测试

文档和 README 更新后至少应通过：

```bash
python3 -m unittest tests.test_project_skills -v
python3 -m unittest tests.test_design_contract -v
```

如修改 README，还应人工检查 README 只声明 v1 已实现边界，不包含未实现能力承诺。

## 默认验证命令

`app_generation` domain pack 默认声明：

```bash
node --check generated_apps/<app_slug>/server.js
python3 -m unittest discover -s tests -v
```

当 Node 不可用时，verifier 应记录清晰 blocker，而不是把语法检查视为通过。

## 示例验收场景

### 场景一：Todo PRD 生成原型

输入：一个描述 Todo 列表、筛选、完成状态和本地保存的 PRD。

预期：

- 生成 `input_prd.md`。
- 生成 `app_contract.json`，声明 `localStorage` 和无数据库。
- fake Codex 或真实 Codex 生成 `generated_apps/todo-prototype/`。
- `server.js` 通过 `node --check`。
- `preview_instructions.md` 包含 `node server.js` 和本地 URL。

### 场景二：PRD 要求数据库

输入：PRD 要求用户数据写入 Postgres。

预期：

- 标准化 PRD 记录数据库需求。
- `app_contract.json` 仍声明 v1 `database=none`。
- 生成结果用 `localStorage` 或 mock 表示，并记录 assumption 或 blocker。
- 不生成数据库连接、迁移或 secret。

### 场景三：PRD 包含外部 API token

输入：PRD 中粘贴了疑似 token。

预期：

- 摘要和报告中脱敏。
- 记录风险事件。
- 不把 token 写入生成代码、run artifact 摘要或 localStorage。

### 场景四：工作台对比 rule 与 Codex

输入：同一 Todo PRD 产生 rule baseline 和 Codex 实现节点输出。

预期：

- 工作台展示两个 variant。
- rule usage tokens 为 0。
- Codex usage 来自真实记录；无记录时显示 `unknown`。
- `implementation` 节点说明代码实现来自 Codex/LLM，不来自 rule。
- 用户能选择 Codex variant 作为下游输入。

### 场景五：PI-Agent 右侧对话与工具调用流

输入：右侧 Agent Provider 切换到 `pi_agent`，`pi` 已安装在系统 PATH。用户发送一条需要读取仓库文件并执行 bash 的消息（例如「读 README.md 第一节，运行 ls runs/ 给我列表」）。

预期：

- 切换 Provider 后状态显示 `ready`，`message` 包含 `pi available at <abs_path>`。
- 1s 内收到首个 `message_delta` 事件，前端开始渲染 assistant 气泡。
- 整个回合内至少出现 1 次 `tool_call` + 配对 `tool_result`（来自 pi 内置 `read` 或 `bash` 工具），前端工具卡显示路径或命令与结果摘要。
- 回合结束时收到 `agent_end`，`payload.usage` 含真实 provider 上报的 token（无 token 信息时为 `unknown` 而非 0）。
- 中间节点流（runs/<id>/events.jsonl）未被写入任何新事件，节点状态保持不变。
- 切换回 `codex` 后仍可正常对话，不需要重启 dashboard。

边界场景：`pi` 未安装时，Provider 状态显示 `not_configured`，`message` 提示 `npm i -g @earendil-works/pi-coding-agent`，默认 Codex Provider 不受影响。

### 场景六：PRD 上传触发节点 SSE

输入：用户在工作台「新建 run」面板粘贴一段 PRD（或拖入 .md 文件），选择 `executor=deterministic`，点击「开始」。

预期：

- `POST /api/app-generation/runs` 在 1s 内返回 `run_id` 与 `events_stream` URL；`runs/<run_id>/input_prd.md` 与 `team_run_record.json` 已落盘。
- 前端立即订阅节点 SSE，收到首帧 `snapshot`，6 个固定节点全部在快照中，状态分布合理（前置节点 `ready`，其余 `not_started`）。
- deterministic 路径下 ~3s 内收到 `run_finished`，期间每个节点至少产出 1 条 `running` + 1 条 `completed/warning/blocked` 的 `node_state` 事件。
- 中途强制断开 SSE 连接 3s 后由前端自动重连，dashboard 重发当前 `snapshot`，前端节点状态与 `runs/<run_id>/team_run_record.json` 完全一致，无重复也无丢失。
- 上传的 PRD 文本未在任何 SSE 事件、dashboard 日志或 redacted 字段中泄露 secret 样式串。

边界场景：上传超大 PRD（例如 5 MB 纯文本）不应被前端或后端硬截断；deterministic runtime 可正常生成所有 artifact，节点流仍在 SSE 协议时间窗内完成。

### 场景七：右侧对话 SSE 断线与降级

输入：用户用 `pi_agent` 发送一条长消息，中途主动断开 `POST /api/app-generation/agent/stream` 的连接（或 dashboard 子进程被 SIGTERM）。

预期：

- 后端在 stream 关闭前未发出 `agent_end` 时，必须补发 `upstream_error{phase:"stream_closed"}`，前端把当前回合气泡标记为「已中断」，不影响历史气泡。
- 前端 **不** 自动重连同一请求；用户重新发送时新建一条对话回合，不复用上一回合的 `tool_call` 卡。
- 已经落地的 `message_delta` 内容保留在 UI 上，对应的未结束工具卡显示 `interrupted` 状态。
- `pi` 子进程异常退出时，下一次 send 触发 PiAgentProvider 重启子进程；如果连续 3 次启动失败，状态切到 `error`，前端在工具卡区域显示「PI 不可用，已回落到 codex」，用户继续发送时由 CodexProvider 接管该回合。
- 节点 SSE 通道不受右侧对话流中断影响，仍正常推送 `node_state`。

### AC-052 发布到预览按钮与状态机

工作台必须支持用户显式「发布到预览」，将 worktree 应用拷贝到独立快照。

验证信号：

- `POST /api/app-generation/runs/{run_id}/publish-app` 将 `runs/<run_id>/worktree/generated_apps/<app_slug>/` 拷贝到 `runs/<run_id>/generated_apps/<app_slug>/`，写入 `app_publish.json`（含 `published_at`、`source_commit`、`slug`、`worktree_path`）。
- 发布前检查 worktree dirty 状态；implementation 节点失败或不存在时返回 412 + `{"error": "implementation_not_complete"}`。
- 发布成功后 `preview_status` 从「未发布」转到「已发布·已停止」，「启动预览」按钮从置灰变为可点击。
- implementation 节点重跑会将 `preview_status` 退回「未发布」，旧 `app_patches/index.json` 内所有记录标记 `invalidated_by_rerun=true`。

### AC-053 file_preview 不触发代码修改

文件预览竖栏只读取节点产物，不进入 worktree、generated_apps 快照或 codex 原始输出。

验证信号：

- 文件预览读取来源限定为 `runs/<run_id>/artifacts/<node>/*`。
- file_preview focus 下 Agent 解释、对比或建议修改时，不直接覆写文件。
- Agent 在 `file_preview` focus 下返回 `patch_artifact` action 时，必须先落 `runs/<run_id>/artifact_patches/<ts>__<node>__<file>.diff`，再覆写 `runs/<run_id>/artifacts/<node>/<file>`，并更新 `artifact_patches/index.json`。
- 试图读取 `runs/<run_id>/worktree/`、`runs/<run_id>/generated_apps/`、`runs/<run_id>/codex/` 时返回 403 + `{"error": "path_out_of_scope"}`。

### AC-054 patch_artifact 落证据与 index.json

Agent 修改节点产物必须先写 patch 证据，再覆盖目标文件。

验证信号：

- `patch_artifact` 确认后，dashboard 先写 `runs/<run_id>/artifact_patches/<ts>__<node>__<file>.diff`，格式为 unified diff。
- 写 diff 成功后覆写 `runs/<run_id>/artifacts/<node>/<file>`。
- 更新 `runs/<run_id>/artifact_patches/index.json`，新增记录 `{"timestamp", "node_id", "file", "operation": "patch", "diff_path", "agent_action_id"}`。
- 覆写失败时回滚 diff 文件，返回 422 + 失败原因；已覆写成功的其他文件不回滚，已落地的 diff 与 index.json 保留为证据。
- 禁止修改 `runs/<run_id>/codex/` 下任何文件；尝试时返回 403 + `{"error": "codex_immutable"}`。

### AC-055 patch_app 自动重启预览

Agent 修改已发布应用后，预览必须自动重启加载新代码。

验证信号：

- `patch_app` 确认后，dashboard 先写 `runs/<run_id>/app_patches/<ts>__<file>.diff`，再覆写 `runs/<run_id>/generated_apps/<slug>/<file>`，更新 `app_patches/index.json`。
- 覆写成功且当前 preview 处于 `running` 状态时，dashboard 自动触发两阶段重启：新端口先起 + 健康检查 + 通过后切流量再停旧。
- 重启成功后 `preview_status.app_patches_count` 递增，SSE 推 `preview_url_changed` + `preview_restarted`，前端 iframe 按新 URL 刷新。
- 重启失败时保留旧 server 进程，`preview_status.last_patch_restart_error` 记录错误，SSE 推 `preview_restart_failed`，UI banner 提示用户当前预览仍为旧版本，建议手动停止后重新启动。
- preview 未启动时覆写不触发重启；下次用户点「启动预览」会加载最新代码。

### AC-056 重启失败保留旧进程

两阶段重启的健康检查阶段失败时，新进程必须被回收，旧进程继续提供服务。

验证信号：

- 新端口启动后健康检查失败时，dashboard 立即对 `new_pid` 执行 `SIGTERM`（3 秒）→ `SIGKILL`，不调用 `process.kill(old_pid)`。
- `preview_run_record.json` 的 `pid`、`port`、`url` 保持指向旧进程，不写入 `previous_pid` / `switched_at`。
- `preview_status` 保持 `running`，新增 `last_patch_restart_error = {"phase": "new_process_health_check", "error": "...", "ts": "..."}`。
- SSE 推 `preview_restart_failed`，前端 banner「补丁已落盘但新版本启动失败，当前预览仍为旧版本」。
- iframe URL 不变化（旧端口持续服务），用户当前可见的预览不被打断。
- 用户手动点「停止」再「启动预览」可加载最新 patch 后的代码。

### AC-057 codex 原始输出禁止修改

任何 Agent action 都不得修改 `runs/<run_id>/codex/` 下文件。

验证信号：

- `patch_artifact` 或 `patch_app` 的 `target_path` 若指向 `codex/` 路径，返回 403 + `{"error": "codex_immutable", "hint": "Codex 原始输出不可修改，请改用 rerun_from_node 或 patch_artifact 修改 artifacts/<node>/*"}`。
- Agent prompt 明确说明 codex/ 目录只读，不应出现在 patch 目标列表中。
- 手动文件操作或 apply gate 尝试覆写 `codex/` 时，dashboard 拦截并记录风险事件。

### AC-058 app_preview 运行错误默认转成 patch_app

用户在应用预览中反馈运行错误、按钮无响应、模型未配置、provider 错误、生图失败、下载失败或局部迭代不可用时，`intent=auto` 必须优先诊断当前已发布应用，并生成 `patch_app` 或 `diagnose_app_bug` 后接 `patch_app`，而不是默认解释当前节点。

验证信号：

- `focus.card="app_preview"` 且用户说“生成单张图时报 gpt-image-1 not configured”时，返回 `resolved_intent="patch_app"` 或 `resolved_intent="diagnose_app_bug"`，并给出可确认 PatchSet。
- PatchSet 的 `problem_source` 指向 `preview_error`、`provider_health`、`preview_log_summary` 或 `generated_app_capability_gaps`。
- PatchSet 明确保留已通过能力，不要求重写完整 PRD，不默认触发 `rerun_from_node`。
- 如果缺口来自 PRD / app_contract 漏需求，才允许升级为 `patch_artifact` 或 `rerun_from_node`。

### AC-059 PI-Agent 自然语言建议可 fallback 成可执行动作

PI-Agent 或其他 Provider 只返回自然语言建议时，AgentBridge 必须使用确定性 fallback 将其归一化为待确认 `AgentAction`，避免“建议正确但用户不能执行”。

验证信号：

- PI-Agent 回复“建议把默认模型从 gpt-image-1 改为 gpt-5.4-image-2”但未返回 JSON action 时，Bridge 生成 `patch_app` draft，并标记 `source="provider_text_fallback"`。
- fallback action 仍必须通过路径白名单、PatchSet dry-run、secret 扫描和用户确认。
- fallback 不能凭空生成 API key，不能把 `.env` 内容注入 prompt 或 patch。
- 无法确定目标文件时，fallback 返回 `clarify_question` 或 `diagnose_app_bug`，不得盲目写文件。

### AC-060 PatchSet dry-run 不写文件

`patch_app` 和 `patch_artifact` 必须先执行 dry-run。dry-run 只能计算目标文件、diff、风险、冲突和验证命令，不得修改任何文件、preview 进程或 run 状态。

验证信号：

- dry-run 前后目标文件 hash 不变。
- dry-run 输出包含 `patch_set_id`、`target_files`、`diff_preview`、`risk_events`、`verification_plan` 和 `requires_confirmation=true`。
- 任何 target path 越界、缺少 AGENT_EDIT 锚点、文件过大、二进制不可 patch 或 secret 风险，dry-run 返回失败且不写 patch 证据。
- 用户取消确认后不写 `app_patches/`、`artifact_patches/` 或 `adjustment_events` 成功态。

### AC-061 Patch apply 后验证、重启和 rollback

用户确认 PatchSet 后，框架负责 apply、验证、预览重启和 rollback 入口，Agent 不直接绕过框架写文件。

验证信号：

- apply 先写 `app_patches/<ts>__<file>.diff` 或 `artifact_patches/<ts>__<node>__<file>.diff`，再覆写目标文件，并更新对应 `index.json`。
- 批量 PatchSet apply 前必须完成全部目标文件校验；任一校验失败时不写任何目标文件。
- apply 后运行 action 中声明的最小验证，例如 `node --check server.js`、`node --check public/app.js`、`node runtime_smoke.js` 或 provider health mock。
- 当前 preview running 时触发两阶段重启；重启失败时保留旧进程，符合 AC-056。
- 每个成功 apply 的 PatchSet 都提供 `rollback_patch` action；rollback 也必须 dry-run、用户确认、落证据和验证。

### AC-062 Preview env 注入不泄露 secret

一键预览必须从仓库根 `.env` 读取图片 provider 白名单字段并注入子进程环境，同时对所有外显通道做 secret redaction。

验证信号：

- 支持注入 `IMAGE_PROVIDER`、`OPENROUTER_API_KEY`、`OPENROUTER_API_BASE_URL`、`OPENROUTER_IMAGE_MODEL`、`OPENROUTER_IMAGE_SIZE`、`OPENROUTER_IMAGE_QUALITY`、`OPENROUTER_IMAGE_OUTPUT_FORMAT` 和 `IMAGE_REQUEST_TIMEOUT_MS`。
- preview record、logs API、SSE、Agent context、run artifact 摘要和 UI 文案不包含 API key 原文。
- Agent 可看到 provider/model 摘要，例如“OpenRouter 已配置，模型 openai/gpt-5.4-image-2”，但看不到 `.env` 正文。
- 生成应用读取服务端 env；前端不得要求用户输入 API key，也不得把 key 写入 localStorage。

### AC-063 高频应用调整记录为 AdjustmentEvent

每次用户通过右侧 Agent 对已发布应用做调优，都必须形成可审计 `AdjustmentEvent`，用于中间节点流“应用调优”事件轨道展示。

验证信号：

- `adjustment_events` 至少记录 `event_id`、`user_message`、`resolved_intent`、`patch_set_id`、`target_files`、`dry_run_status`、`apply_status`、`verify_status`、`preview_restart_status`、`rollback_available` 和时间戳。
- 点击事件轨道可查看用户输入、Agent 判断、PatchSet diff、验证结果和预览状态。
- `implementation` 重跑后，旧 adjustment event 保留但标记 `invalidated_by_rerun=true`。
- 成功 patch 可生成 `promote_patch_to_generation_rule` 候选，但必须用户确认，不自动修改上游模板、benchmark 或 runtime。

### AC-064 图片模型配置错误可通过 Agent 闭环修复

`gpt-image-1 · not configured` 这类模型配置错误必须作为通用 provider/model 修复场景覆盖，不得写成 Dingdang 特例。

验证信号：

- 当仓库根 `.env` 含 `IMAGE_PROVIDER=openrouter` 与 `OPENROUTER_IMAGE_MODEL=openai/gpt-5.4-image-2`，而预览应用仍显示 `gpt-image-1 · not configured`，Agent 生成 `patch_app` PatchSet 修复默认模型、健康检查显示或服务端读取逻辑。
- PatchSet 不包含真实 API key，不要求用户在前端输入 API key。
- 修复后 provider 状态显示当前模型来自服务端配置，模型下拉或模型显示不再只写死 `gpt-image-1`。
- 若 provider 实际不可用，UI 显示可行动错误，例如 `provider/model unavailable` 或 `request timeout`，不得伪造成功。

### AC-065 短期 patch_app 使用单文件单 patch 和 AGENT_EDIT 区间

短期 `patch_app` 必须遵守当前 patch engine 的可执行边界，避免让 PI-Agent 猜测底层限制。

验证信号：

- `target_path` 必须使用 `generated_apps/<slug>/<file>`，例如 `generated_apps/input-prd/server.js`。
- `target_path` 写成 `<slug>/server.js`、`server.js`、绝对路径、`worktree/...` 或 `codex/...` 时必须被拒绝。
- 一个 PatchSet 内同一 `target_path` 不得出现多次；同一文件多处修改必须合并为一个 patch。
- 同一文件多处修改的首选方式是单个 `replace_block`，使用已存在的 `// === AGENT_EDIT:<id> START ===` 锚点。
- PI-Agent 不得对同一个 `server.js` 输出多个 `replace_text` 来完成 provider/model 修复。

### AC-066 复杂修复委托 Code Agent 而非 PI 直接改代码

当用户诉求需要完整代码上下文、多处联动修改、跨文件行为理解或无法用一个稳定 `AGENT_EDIT` 区间表达时，右侧 Agent 必须输出 `delegate_code_repair`，而不是继续直接生成 `patch_app`。

验证信号：

- `delegate_code_repair` action 包含 `repair_request.problem`、`constraints`、`expected_behavior` 和 `verification`。
- 右侧 PI-Agent 不直接写文件，也不直接调用 write/edit/bash 修改 `generated_apps/`。
- Code Agent 是唯一代码修改执行者；Codex、PI-code 或其他 provider 必须通过同一个 `CodeAgentExecutor` 抽象接入。
- `delegate_code_repair` 修的是当前已发布快照，不等于 `rerun_from_node`，也不重跑完整 PRD 流程。
- Code Agent 输出仍必须进入 dry-run diff、用户确认、apply、验证、证据记录和预览重启闭环。

### AC-067 delegate_code_repair 两阶段执行（prepare/apply）

`delegate_code_repair` 的执行必须分两段，对应 `docs/app_generation_code_agent_executor_spec.md` 的 `CodeAgentExecutor` 执行契约：阶段一 prepare 在隔离 worktree 产出候选 diff；阶段二 apply 才 promote 回已发布快照。

验证信号：

- 阶段一 prepare 在未发布应用上触发时返回 412 `app_not_published`。
- prepare 把已发布 `generated_apps/<slug>/`（排除 `app_publish.json`、`app_patches/`）复制进 `worktree/generated_apps/<slug>/`，以 `allowed_paths=["generated_apps/<slug>"]` 运行 Code Agent。
- prepare 阶段**不修改 run 级 `generated_apps/<slug>/`**，只返回候选 diff、验证结果和 codex trace 引用。
- 阶段二 apply 才 promote worktree 候选回已发布快照，写 `app_patches/` 证据，触发两阶段重启并写 `AdjustmentEvent`。
- prepare 失败（缺二进制、review 不过、验证失败）或用户在 apply 前取消时，旧 `generated_apps/<slug>/` 原样不动，不写成功态证据与 `AdjustmentEvent`。
- 候选过期（同一应用发起了新的 prepare）时，旧候选 apply 返回 409。
- Code Agent 不得改动 `app_publish.json`、`codex/`、worktree 外路径、`.env` 或仓库源码；越权路径被拒绝。

### AC-068 implementation 节点 Codex 实时进度可见

`implementation` 节点运行中时，工作台必须展示 Codex 执行过程，而不是只显示“运行中”。

验证信号：

- 生成 `codex/coder_progress.jsonl` 和 `codex/coder_progress_status.json`。
- run SSE 推送 `node_progress` 事件，payload 包含 `node_id="implementation"` 和最近 `CodexProgressEvent`。
- 节点详情「执行过程」timeline 展示启动 Codex、命令执行、文件修改、验证和 diff 生成等业务友好步骤。
- 30 秒无新事件且终态未出现时，UI 显示“Code Agent 仍在运行，暂无新输出”。

### AC-069 delegate repair prepare 期间 Code Agent 修复进度可见

右侧 Agent 触发 `delegate_code_repair` 后，prepare 长请求期间必须能看到 Code Agent 修复进度。

验证信号：

- 前端发起 prepare 前生成 `repair_id`。
- 后端在进入 Codex 前写 `app_repairs/<repair_id>/progress.jsonl` 和 `progress_status.json`。
- `GET /api/app-generation/runs/<run_id>/delegate-code-repair/status?repair_id=<repair_id>` 返回 `status`、`latest_events`、`result_ready`、`diff_ready`、`risk_events` 和 `blockers`。
- 右侧 Agent 区展示「Code Agent 修复进度」卡片，直到 prepare 返回候选 diff 或失败。

### AC-070 progress 事件脱敏、截断且不替代事实源

Codex progress 事件是可观测信号，不是最终事实源。

验证信号：

- progress 事件不包含 API key、完整 `.env`、完整 prompt、完整源码或完整 stdout。
- 命令输出摘要默认截断到 2KB。
- 完整日志只能通过受控 artifact preview 读取。
- 最终成功/失败仍以 `team_run_record.json`、`codex/verification_record.json`、`codex/app_repair_result.json` 和验证产物为准。

### AC-071 app repair 越界修改会失败且旧应用不变

`delegate_code_repair` 只允许修改当前候选目录 `worktree/generated_apps/<slug>/`。

验证信号：

- fake Codex 修改 `worktree/tests/` 或仓库源码时，prepare 失败。
- 返回 risk event `outside_repair_scope_changes`。
- `runs/<run_id>/generated_apps/<slug>/` 保持不变。
- 右侧 Agent 进度展示“Code Agent 尝试修改修复范围外文件，旧应用未修改”。

### AC-072 Codex stdout JSONL 映射为业务友好进度

后端必须把 Codex stdout JSONL 转成业务友好进度事件。

验证信号：

- `item.started command_execution` 显示为“运行命令”。
- `item.completed command_execution` 显示命令名、exit_code 和截断输出。
- `item.completed file_change` 只显示文件路径和 kind，不显示完整源码。
- `agent_message` 只提取 summary、next_action、blockers 和 risk_events。
- 未识别事件降级为“Code Agent 有新输出”，不导致进度流中断。

### AC-073 文档静态验收

本轮文档升级完成后运行：

```bash
rg -n "CodexProgressEvent|coder_progress|progress_status|node_progress|code_repair_progress|delegate-code-repair/status|outside_repair_scope_changes|仍在运行|30 秒|secret" docs/app_generation*.md
git diff -- docs/app_generation*.md
```

后续进入实现阶段再运行：

```bash
python3 -m unittest tests.test_codex_executor tests.test_dashboard -v
node --check dashboard/app_generation.js
```

## V2 生成画布验收标准

### AC-074 Runway Timeline 业务主流程

Dashboard 默认只展示 Runway Timeline 作为主流程，包含 8 个 `BusinessStep`：PRD 输入、理解业务目标、编译业务规格、规划应用结构、生成应用原型、验证业务能力、输出可交付版本、可预览应用。内部 runtime node id 只在当前步骤工程证据或开发者详情中出现。

验证信号：

- UI 默认节点标题为业务中文。
- `/canvas` 返回 8 个 `flow_steps`。
- `prd_entry` 和 `app_preview` 是 UI step，不要求 runtime node。
- 每个业务节点可映射到现有 V1 runtime artifacts。
- 业务节点卡片展示状态、摘要、对象数量和最近事件。
- `node_id`、artifact path、raw JSON 不作为默认主文案。

### AC-075 CanvasObject 投影可从 artifacts 重建

Dashboard 必须能从 run artifacts、`NodeContext`、preview status、evaluation artifacts 和 `adjustment_events` 生成 `CanvasObject` 投影。

验证信号：

- 同一 run 在刷新页面后对象列表一致。
- 删除浏览器 localStorage 后对象事实不丢失。
- `CanvasObject` 包含 `object_id`、`object_type`、`title`、`summary`、`status`、`source_refs`、`artifact_refs`、`evidence_refs` 和 `actions`。
- 投影层不写入事实源；事实仍以 artifacts 为准。

### AC-076 CanvasSelectionContext 注入右侧 Agent

用户点击任意 Runway 步骤或画布对象后，右侧 Agent 请求必须携带 `CanvasSelectionContext`。

验证信号：

- 选中步骤时，请求中包含 `selection_type="flow_step"`、`step_id`、`title`、`runtime_nodes`、`focus_surface`、`visible_related_objects` 和 `allowed_actions`。
- 选中对象时，请求中包含 `selection_type="canvas_object"`、`selection_id`、`object_type`、`business_node`、`focus_surface`、`visible_related_objects` 和 `allowed_actions`。
- `selection_id` 必须引用当前 run 的对象，不允许跨 run 引用。
- Agent 回答围绕当前步骤/对象和证据，不退化为泛泛解释当前工程节点。

### AC-077 Code Agent 过程业务化表达

生成应用原型节点必须把 `CodexProgressEvent` 映射成业务进度。

验证信号：

- `command_execution` 显示为“正在检查应用代码语法”“正在模拟用户操作”“正在验证业务能力”等业务文案。
- 30 秒无新事件时显示“Code Agent 仍在运行，暂无新输出”。
- 超过 5 分钟时展示最长耗时阶段、最近事件时间和查看日志入口。
- 不默认展示完整 stdout、prompt、源码或 secret。

### AC-078 对象化 AgentAction

右侧 Agent 必须支持 Runway 步骤动作和 V2 对象化动作：`explain_step`、`explain_step_io`、`inspect_evidence`、`rerun_step`、`explain_object`、`suggest_object_patch`、`repair_generated_app`、`verify_capability`、`compare_canvas_objects`、`promote_to_generation_rule` 和 `rerun_business_node`。

验证信号：

- 所有 V2 action 包含 `source_object_id`。
- 修改事实源的 action 必须 `requires_confirmation=true`。
- `repair_generated_app` 必须映射到 `patch_app` 或 `delegate_code_repair`，不能直接写文件。
- `suggest_object_patch` 不直接改旧 artifact，只进入 override 或新 run。

### AC-079 ContextObject 支持 PRD 之外上下文

工作台必须能记录和展示 PRD 之外的上下文对象，包括业务场景、样例数据、领域知识、参考应用、用户反馈、工具能力和策略约束。

验证信号：

- `ContextObject` 包含 `context_id`、`context_type`、`title`、`summary`、`source`、`confidence`、`used_by_nodes` 和 `linked_objects`。
- 用户确认的上下文优先于模型推断。
- 上下文对象被节点使用时留下引用。
- 上下文对象不得包含 API key、完整 `.env` 或未授权文件正文。

### AC-080 版本和调优回放

生成画布必须能展示初始生成、发布快照、patch、delegate repair、回滚和规则提升候选。

验证信号：

- 每次 `patch_app` 或 `delegate_code_repair` 成功后形成可点击版本事件。
- 版本事件展示用户输入、Agent 判断、diff、验证结果、预览状态和是否可回滚。
- 成功修复可建议 `promote_to_generation_rule`，但不自动修改模板、benchmark 或 verifier。

### AC-081 画布对象编辑边界

业务对象编辑、已发布应用修复和生成规则提升必须走不同协议。

验证信号：

- 业务对象编辑生成 `object_patch` / `user_override`，需要从最小影响业务节点重跑。
- 已发布应用修复走 `patch_app` 或 `delegate_code_repair`。
- 生成规则提升只创建候选记录，必须用户确认后进入后续实施。
- 任何路径都不得直接覆盖 `codex/` 原始输出或 worktree。

### AC-082 V2 Secret 边界

画布对象、Agent prompt、SSE、日志摘要、preview status 和 diff 预览不得泄露 secret。

验证信号：

- API key、完整 `.env`、进程环境和未授权文件正文不会进入 `CanvasObject`、`ContextObject` 或 `CanvasSelectionContext`。
- provider health 只展示配置状态、provider 名和模型名。
- 日志和 progress 默认截断并脱敏。

### AC-083 V2 分阶段实施可验收

V2 生成画布必须按 V2.0、V2.1、V2.2 分阶段交付，每个阶段都有独立输入、输出、验证命令和停止条件。

验证信号：

- V2.0 至少交付 `CanvasProjectionBuilder`、只读 Canvas API、6 个 runtime 聚合业务节点、对象列表、对象详情和 `CanvasSelectionContext`。
- V2.1 至少交付 Runway Timeline 主视图、8 个 `flow_steps`、Code Agent 业务进度卡、步骤/对象化 AgentAction、确认卡，以及 `patch_app` / `delegate_code_repair` 映射。
- V2.2 至少交付 `ContextObject`、版本回放、规则提升候选、secret/path 安全回归和端到端验收记录。
- `docs/app_generation_implementation_task_plan.md` 必须包含 T29.0 到 T31.6 的子任务，每个子任务包含输入、中间过程、输出、验证命令和停止条件。
- 任何子任务不得要求引入数据库、替换 Team Runtime、绕过人工确认 gate 或直接修改 `codex/` 原始输出。

### AC-084 V2 任务与验收覆盖矩阵

实施前必须能从文档追踪每个关键验收标准对应的任务切片，避免出现“有验收无任务”或“有任务无验收”。

验证信号：

- AC-074 由 T29.3、T29.7、T30.6 覆盖。
- AC-075 由 T29.1、T29.2、T29.4、T29.5 覆盖。
- AC-076 由 T30.3、T30.4、T30.6 覆盖。
- AC-077 由 T30.1、T30.2 覆盖。
- AC-078 由 T30.4、T30.5、T30.7 覆盖。
- AC-079 由 T31.1、T31.2 覆盖。
- AC-080 由 T31.3、T31.4、T31.6 覆盖。
- AC-081 由 T30.5、T30.7、T31.4 覆盖。
- AC-082 由 T31.5 覆盖。
- AC-083 由 T29.0 到 T31.6 的任务表覆盖。

### AC-085 V2 文档静态验收

文档同步完成后运行：

```bash
rg -n "Runway Timeline|BusinessStep|flow_steps|T29.0|T29.7|T30.7|T31.6|CanvasProjectionBuilder|CanvasSelectionContext|ContextObject|Code Agent 长过程|规则提升|AC-074|AC-085" docs/app_generation*.md
git diff -- docs/app_generation*.md
```
