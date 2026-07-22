# 数据分析节点生成规范实施计划

## 状态

本文档把 [`app_generation_data_analysis_node_spec.md`](app_generation_data_analysis_node_spec.md) 和 [`app_generation_data_analysis_node_technical_design.md`](app_generation_data_analysis_node_technical_design.md) 落到可实施的工程计划。

产品规范定义“业务策略文档中的数据分析流程应该如何被用户理解和操作”。技术设计定义 `analysis_node_view`、字段覆盖、分析结论、事实边界和服务边界。本文档回答：当前代码应如何改、哪些历史逻辑应退场、哪些兼容层暂时保留，以及验收时看什么。

本文档不要求修改 `tasks/current/*`，不手改历史 `runs/.../generated_apps/...`，不默认启用真实数仓 live probe。

当前分期：

- P0：节点视图、五段工作区、字段覆盖和右侧 Agent 收口。
- P1：按执行动作运行数据分析节点，显式 live probe 后生成数据表草稿、派生字段草稿和分析结论草稿，并修复 PI Agent GPT-5.5 配置识别。
- P2：复杂多 API join、结论确认后的下游事实传播和更完整的真实数据合并。

## 目标

生成应用里的数据分析节点不再只是“字段覆盖表”或“右侧 Agent 查 API”。它必须在中间工作区展示一个清晰的业务运行范式：

1. 节点目标：来自业务文档 `目的`。
2. 输入准备：来自 `数据来源`、上游产物和数据需求。
3. 字段覆盖：来自 `表格字段` 和 `api_doc_matcher` 字段匹配结果。
4. 执行动作：来自业务文档 `执行动作`。
5. 输出结果：分为数据表产物和分析结论。

右侧 Agent 只做辅助：错配字段纠正、未覆盖字段解释、派生字段方案、分析结论草稿建议。主流程、字段审核和事实确认都在中间工作区完成。

## 实施原则

- `analysis_node_view` 是新增语义层，不替代 `node_execution_view`、`output_field_requirements`、`data_mapping_context` 和 `data_mapping_contract-v2`。
- `api_doc_matcher.service match_business_context` 是 API/字段匹配唯一事实源，前端不实现独立匹配算法。
- 字段名优先保留业务文档原始中文表达，不能因为 schema 或检索字段而英文化。
- 派生字段不能强行误配成 API 原生字段，应进入 Agent/人工处理。
- 未确认字段映射不得成为数据表事实；未引用证据的分析结论不得成为 confirmed。
- 旧的“右侧选 API、看合同、确认合同、Join 粒度”主流程应从普通用户界面退场。

## 关键改造

### 1. 生成过程新增 `analysis_node_view`

修改 `growth_dev/team/app_generation.py`。

新增生成函数：

- `_node_analysis_node_view(...)`
- `_analysis_purpose_model(...)`
- `_analysis_input_model(...)`
- `_analysis_execution_plan(...)`
- `_analysis_data_output_model(...)`
- `_analysis_insight_output_model(...)`
- `_analysis_verification_model(...)`

接入规则：

- 在 `_compile_app_config_nodes()` 中为节点写入 `analysis_node_view`。
- `analysis_node_view.node_kind` 与节点顶层 `kind`（`form`/`data`/`compute`/`llm`/`aggregate`）是两套正交概念，不复用、不覆盖顶层 `kind`。
- 数据分析节点的判定只看语义条件：同时具备 `data_requirements` 和非空 `output_field_requirements` 的节点，`analysis_node_view.node_kind=data_analysis`。判定不依赖顶层 `kind` 取值。
- 其余节点 `analysis_node_view.node_kind=standard`，不启用数据分析五段工作区。
- `data_output_model.fields` 复用 `output_field_requirements`，并保留字段中文名、字段说明、source schema 和 source trace。
- `insight_output_model.requirements` 优先从业务文档 `分析结论` 抽取；缺失时从 `判断标准`、`产出`、执行动作里的“分析/判断/结论”语句降级生成。
- `source_trace` 指向业务文档、workflow、data requirement、output schema、api doc index。

### 2. 契约和校验

节点契约校验目前分散在三处，`analysis_node_view` 落地时必须三处同步，否则会出现"一处校验通过、另一处不认"的偏差：

- `shells/report_generator/contract.schema.json`：JSON Schema 层。
- `growth_dev/team/app_generation.py` 的 `validate_app_config()`：Python 生成侧校验。
- `growth_dev/team/app_generation.py` 内嵌的 JS 契约校验（`requiredFields` 列表与 `node_execution_view` 相关的 `throw new Error(...)`，约 3097–3158 行）：注入到生成应用里的前端校验。

契约要求：

- node schema 增加 `analysis_node_view`。
- `node_kind=data_analysis` 时必须包含 `schema_version`、`node_id`、`node_kind`、`purpose_model`、`input_model`、`execution_plan`、`data_output_model`、`insight_output_model`、`verification_model`、`source_trace`。
- 上述"当 `node_kind=data_analysis` 时必填一组字段"是条件必填。当前 `contract.schema.json` 是扁平 `required` 结构，未使用条件构造，需要引入 `if/then` 或 `allOf` 表达该条件必填，这是实施时的真实工作量点。
- `data_output_model.fields.length` 必须等于 `output_field_requirements.length`。
- 数据分析节点必须能保留中文字段名和字段说明。

验收重点：

- 流程2“行业大盘与热销商品分析”能生成目的、数据来源、执行动作、全部表格字段（当前业务文档为 17 个，实际数量以 `output_field_requirements` 为准）、分析结论要求。
- `analysis_node_view` 与现有底层字段保持一致，不引入第二套字段事实。

### 3. 中间工作区五段式渲染

修改 `shells/report_generator/web/app.js`。

新增渲染模块：

- `isDataAnalysisNode(node)`
- `analysisNodeViewFor(node)`
- `renderDataAnalysisNodeWorkspace(node)`
- `renderAnalysisPurpose(view)`
- `renderAnalysisInputReadiness(view)`
- `renderAnalysisFieldCoverage(node, view)`
- `renderAnalysisExecutionPlan(view)`
- `renderAnalysisOutputs(node, view)`

交互规则：

- `renderNodeDetail()` 遇到 `analysis_node_view.node_kind === "data_analysis"` 时使用五段式中间工作区。
- 字段覆盖区只提供“一键生成字段覆盖方案”主入口。
- 一键生成只调用 `/api/db-agent/query` 的 `suggest_multi_api_mapping`。
- 字段覆盖表只展示后端返回的 `field_coverage_plan` 和用户草稿 overlay。
- 输出结果分区展示“数据表产物”和“分析结论”。
- 未真实取数时只显示字段覆盖状态，不生成伪造数据行。
- 分析结论区域显示结论要求、草稿状态、证据引用和人工确认状态。

### 4. 历史前端逻辑收口

以下旧逻辑从普通用户主流程中移除或降级为调试态：

- 右侧 Agent 里的 API 推荐主流程。
- 独立的候选 API 列表。
- 独立的 API asset card 查看入口。
- 独立的请求参数映射、响应字段映射合同详情。
- Join / 粒度确认 UI。
- “批量确认高置信字段”按钮。
- “确认映射合同”按钮。
- “派生字段分析”主按钮。

可删除或不再作为主渲染路径的前端函数：

- `renderDataMappingContract`
- `renderContractCandidateApis`
- `renderContractRequestParams`
- `renderContractResponseFields`
- `renderBusinessInputResult`
- `renderFieldMapResult`
- `renderDbAgentResult`

保留但换位置：

- API 返回字段浏览能力保留在字段行内，用于未覆盖或错配字段的人工筛选。
- 字段草稿保存由中间工作区自动保存 overlay，不让用户面对底层合同。
- 右侧 Agent 读取当前字段覆盖草稿，只给纠错和补充建议。

### 5. 服务端兼容层

修改 `shells/report_generator/server/server.js`。

主流程保留：

- `suggest_multi_api_mapping`：生成字段覆盖方案。
- `save_field_mapping`：保存字段覆盖草稿。
- `confirm_mapping`：保存人工确认后的合同。只允许在用户已显式确认字段覆盖后触发，并写入确认证据。不得由"节点完成/产物确认"隐式触发，也不得绕过人工确认门自动写 `confirmed`。
- `asset_card`：仅作为字段行人工筛选 API 返回字段的辅助能力。

兼容但不作为主流程：

- `tool_plan`
- `field_map`
- `domain_apis`
- `probe_sample`
- `selected_api`
- `selected_apis`
- `response_field_mapping`
- `join_plan`

服务端要求：

- `suggest_multi_api_mapping` 必须通过 `api_doc_matcher.service match_business_context`。
- matcher 失败时返回 `degraded/matcher_service_unavailable`，不能静默生成 `0/N` 覆盖（`N=output_field_requirements.length`）。
- `/api/pi-agent/query` 输入带上 `analysis_node_view`、当前字段覆盖草稿、派生字段和结论要求。
- PI 只能返回 advice，不写 confirmed 状态。

### 6. 右侧 Agent 收口

右侧 Agent 只保留四类能力：

- 字段纠错：用户指出某字段匹配错了，Agent 给出可应用建议。
- 缺口解释：解释字段为什么缺失、当前 API 为什么不足。
- 派生字段建议：说明派生字段需要哪些证据、如何分析、风险是什么。
- 结论草稿建议：基于已确认字段和证据给出草稿，不能自动确认。

右侧 Agent 不再承担：

- API 推荐主流程。
- 字段映射主流程。
- 合同确认主流程。
- Join / 粒度配置。
- 默认 live probe。

### 7. 样式和布局

修改 `shells/report_generator/web/styles.css`。

- 三栏继续可拖动。
- 中间工作区按五段分区展示。
- 字段表格允许横向滚动，不挤压右侧 Agent。
- 右侧 Agent 长文本、API 字段路径、多轮对话自动换行或局部滚动，不能溢出栏目。
- 不使用过重卡片嵌套；五段工作区应是清晰的操作区，而不是合同调试页。

## P1：节点执行与草稿产物

P1 的目标是把“字段覆盖完成”升级为“运行当前节点能拿到可审核产物”。执行入口仍在中间工作区，右侧 Agent 只提供派生字段和结论建议。

### 1. 数据分析节点执行器

修改 `shells/report_generator/server/server.js`。

- 新增数据分析节点运行分支：`analysis_node_view.node_kind === "data_analysis"` 时由专用执行器处理。
- 执行器读取：
  - `analysis_node_view.execution_plan.steps`
  - `field_coverage_plan`
  - `upstream_artifacts`
  - `insight_output_model.requirements`
- 执行器输出 `data_analysis_execution-v1`，写入 `evidence/<node_id>.execution_trace.json`。
- 当字段覆盖缺失时，先调用 `api_doc_matcher.service match_business_context` 生成覆盖方案；matcher 失败时返回 degraded，不继续取数。

### 2. 数仓 API 取数

修改 `shells/report_generator/server/server.js`。

- 按 `field_coverage_plan[].source_api_id` 聚合 API 调用计划。
- 在聚合前校验每个 API 原生字段都有 `source_api_id + source_field_path`；缺少 `source_field_path` 的字段不能投影，标记 `source_path_missing`。
- 基于 `known_params + API asset_card.request_schema/request_params` 构建 `request_param_mapping[]`。
- 将业务语义参数绑定到 API 真实请求参数，例如 `category/分析类目` -> `cat_id/category_id/category_name`，`period/分析周期` -> `date_range/start_date/end_date`。
- 只有已绑定或人工确认的参数进入 `api_execution_plan[].params`；required 参数缺失时该 API 标记 blocked，并写入 `missing_required_params[]`。
- P1 只支持独立 API 调用；如果 API 需要先从另一个 API 得到 `product_id/shop_id` 等入参，标记 `dependency_required`，不执行该 API。
- `DBA_LIVE_PROBE=1` 且 `DB_ARCHAEOLOGIST_SPEC_PACK` ready 时才调用 `probe_sample`。
- 通过现有 `/api/db-agent/query action=probe_sample` 调用数仓助手；复用既有 `live_probe_disabled -> blocked`、`persistDbAgentArtifact` 落盘和 evidence/artifact refs，不另写一套 probe artifact。
- 未开启 live probe 时返回 blocked，写明下一步配置，不生成假数据。
- 取数成功后把 API response rows 按 `source_field_path` 投影到中文业务字段。
- 投影后逐字段计算 `value_status=present|missing|empty|source_path_missing|not_called|join_blocked`。
- API 返回成功但必填字段没有真实值时，状态应为 `partial_data_table_ready` 或 blocked/degraded，并写入 `risks`。
- 多 API P1 join 只支持轻量确定性 key：`product_id/item_id/goods_id/product_url/rank`；无 key 时标记 `join_blocked`。

### 3. 数据表和结论草稿 artifacts

修改 `shells/report_generator/server/server.js` 和前端输出区。

- 写入 `artifacts/<node_id>.data_table.json`：
  - `schema_version=data-table-draft-v1`
  - `fields`
  - `rows`
  - `field_sources`
  - `derived_fields`
  - `risks`
- 写入 `artifacts/<node_id>.insight_draft.json`：
  - `schema_version=insight-draft-v1`
  - `requirements`
  - `text`
  - `evidence_refs`
  - `risks`
  - `human_confirmation.status=unconfirmed`
- 前端“输出结果”区展示数据表草稿和分析结论草稿；草稿状态不能显示为 confirmed。

### 4. 派生字段和分析结论 PI intents

修改 `shells/report_generator/server/server.js` 和 `shells/report_generator/web/app.js`。

- 新增 PI intent `derived_field_fill`：
  - 输入：数据表草稿、派生字段计划、字段证据。
  - 输出：派生字段草稿值、证据字段、风险。
- 新增 PI intent `insight_draft`：
  - 输入：数据表草稿、分析结论要求、证据字段。
  - 输出：结论草稿、证据引用、风险和待确认问题。
- PI 不可用时：
  - 派生字段只生成填充方案，不生成事实值。
  - 分析结论只生成问题和证据缺口。

### 5. PI Agent GPT-5.5 配置修复

修改 `growth_dev/cli.py`、`growth_dev/team/preview.py`、`shells/report_generator/server/server.js`。

- `app preview start` 使用仓库根 `.env` 注入生成应用进程，不再默认读取 `runs/<run_id>/.env`。
- 增加或修正 `--repo-root` 参数，默认 `.`。
- preview env 白名单加入：
  - `DB_ARCHAEOLOGIST_SPEC_PACK`
  - `DBA_LIVE_PROBE`
  - `AICODEMIRROR_API_KEY`
  - `AICODEMIRROR_KEY`
  - `AICODEMIRROR_BASE_URL`
  - `DEEPSEEK_API_KEY`
  - `PI_BIN`
  - `PI_MODEL`
  - `PI_DEFAULT_MODEL`
- `/api/pi-agent/status` 区分 binary 和 key：
  - binary 不存在：`not_configured/pi_binary_not_found`
  - binary 存在但模型 key 缺失：`degraded/model_key_not_configured`
  - key 存在：`ready`
- 模型优先级：`aicodemirror/gpt-5.5` -> `deepseek/deepseek-v4-pro`。

### 6. 前端执行状态

修改 `shells/report_generator/web/app.js` 和 `shells/report_generator/web/styles.css`。

- “执行动作”区显示每个步骤状态：待执行、执行中、已完成、受阻、降级。
- “运行当前节点”后展示：
  - known params。
  - 每个 API 的请求参数绑定状态和缺口问题。
  - API 调用计划。
  - 取数结果状态。
  - 每个字段的真实取值状态。
  - 派生字段草稿状态。
  - 分析结论草稿状态。
- 右侧 Agent 继续只显示派生字段、错配纠正和结论建议，不新增 API 选择主流程。

## 修改文件清单

P0 必改：

- `growth_dev/team/app_generation.py`（含生成侧 `validate_app_config()` 与注入生成应用的内嵌 JS 契约校验，约 3097–3158 行两处都要同步 `analysis_node_view`）
- `shells/report_generator/contract.schema.json`
- `shells/report_generator/web/app.js`
- `shells/report_generator/web/styles.css`
- `shells/report_generator/server/server.js`
- `scripts/accept_app_generation_cli_baseline.sh`

P0 测试同步：

- `tests/test_app_generation.py`
- `tests/test_app_deterministic_generator.py`
- `tests/test_report_generator_shell.py`
- `tests/test_shell_server.py`

P1 可能改：

- `growth_dev/cli.py`：修复 preview `--repo-root` / env 注入入口。
- `growth_dev/team/preview.py`：扩展 env 白名单并确保读取仓库根 `.env`。
- `shells/report_generator/server/server.js`：数据分析节点执行器、probe_sample 编排、PI intents、artifact 落盘。
- `shells/report_generator/web/app.js`：执行状态、数据表草稿、结论草稿展示。
- `shells/report_generator/web/styles.css`：执行步骤和输出草稿样式。
- `tests/test_app_preview_runner.py`：preview env 注入回归。
- `tests/test_shell_server.py`：数据分析执行器、blocked/live/PI fallback 回归。
- `tests/test_shell_server.py`：业务参数到 API 请求参数绑定、required 参数缺失 blocked、`source_field_path` 缺失不投影、复用 `probe_sample` artifact ref、字段值缺失产生 `partial_data_table_ready`。
- `tests/test_report_generator_shell.py`：前端执行状态和右侧 Agent 边界静态回归。

## 验收标准

### 静态验收

```bash
python3 -m py_compile growth_dev/team/app_generation.py growth_dev/cli.py
node --check shells/report_generator/server/server.js
node --check shells/report_generator/web/app.js
bash -n scripts/accept_app_generation_cli_baseline.sh
```

### 单测验收

```bash
python3 -m unittest tests.test_app_generation tests.test_app_deterministic_generator -v
python3 -m unittest tests.test_report_generator_shell tests.test_shell_server -v
python3 -m unittest tests.test_api_doc_matcher tests.test_api_doc_matcher_service -v
```

### 应用端验收

1. 重新生成新 run，不手改历史 `runs/.../generated_apps/...`。
2. 打开流程2“行业大盘与热销商品分析”。
3. 中间工作区显示五段：节点目标、输入准备、字段覆盖、执行动作、输出结果。
4. 字段覆盖区显示全部中文业务字段，数量与 `output_field_requirements` 一致（流程2当前为 17 个）。
5. 点击“一键生成字段覆盖方案”后，覆盖数应显示 `N/N`（`N` 为字段总数）或明确 degraded 原因，不能静默 `0/N`。
6. 右侧 Agent 只显示未覆盖、低置信、派生字段和纠错对话。
7. 页面不再出现“推荐候选 API / Join 粒度 / 确认映射合同 / 批量确认高置信字段”等旧主流程入口。
8. 输出结果区明确区分数据表产物和分析结论，且分析结论未确认前不能进入节点事实。

### P1 应用端验收

1. 在仓库根 `.env` 配置 `AICODEMIRROR_API_KEY`、`PI_BIN`、`DB_ARCHAEOLOGIST_SPEC_PACK`，并按需要设置 `DBA_LIVE_PROBE=1`。
2. 使用 `app preview start --run-id <run_id> --port <port> --repo-root .` 启动应用。
3. 打开流程2，确认右侧 PI Agent 显示 `aicodemirror/gpt-5.5` 为 configured；若 key 缺失，应显示 `model_key_not_configured`。
4. 在流程1保存类目、周期和产品线。
5. 在流程2点击“一键生成字段覆盖方案”，确认 `N/N` 覆盖。
6. 点击“运行当前节点”。
7. 页面展示每个 API 的请求参数绑定状态；缺 required 参数时显示可行动问题，并阻断对应 API。
8. 未开启 `DBA_LIVE_PROBE=1` 时，页面应显示 blocked 和取数计划，不生成假数据。
9. 开启 live probe 且数仓助手 ready 时，应复用 `/api/db-agent/query action=probe_sample` 取数，并生成 `artifacts/<node_id>.data_table.json` 和 `evidence/<node_id>.execution_trace.json`。
10. 数据表字段展示 `value_status`；API 返回但字段值缺失时，必填字段进入风险区，节点不能显示为完整 ready。
11. 派生字段生成草稿或缺证据说明，来源标记为 PI/LLM 或人工。
12. 分析结论区生成草稿、证据字段和风险，但状态仍为 unconfirmed。

## 分阶段实施

P0：

- 生成 `analysis_node_view`。
- 中间工作区五段式渲染。
- 字段覆盖只走 `api_doc_matcher`。
- 移除旧右侧主流程 UI。
- 流程2完成全部字段（当前 17 个，以 `output_field_requirements` 为准）、目的、数据来源、执行动作、分析结论要求展示。

P1：

- 数据分析节点执行器。
- 业务参数到 API 请求参数绑定。
- 显式 live probe 后复用既有 `probe_sample` 从数仓 API 取数并生成数据表草稿。
- 逐字段真实取值状态和缺口风险。
- 派生字段由 PI/LLM 生成草稿值或缺证据说明。
- 生成分析结论草稿和证据引用。
- 修复 GPT-5.5 配置识别，确保 preview 读取仓库根 `.env`。

P2：

- 多 API join 与真实数据合并。
- 结论确认后的下游事实传播。
- 更完整的人工确认和审计体验。

## 与规范文档的关系

- 产品规范定义“用户在应用里应该如何理解和操作数据分析节点”。
- 技术设计定义“生成配置和运行时合同应该长什么样”。
- 本实施计划定义“现有代码如何改、历史逻辑如何退场、验收怎么跑”。
