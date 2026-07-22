# 数据分析节点执行取数与字段填充策略实施计划

## 状态

本文档补齐 [`app_generation_data_analysis_node_spec.md`](app_generation_data_analysis_node_spec.md)、[`app_generation_data_analysis_node_technical_design.md`](app_generation_data_analysis_node_technical_design.md) 和 [`app_generation_topn_product_table_missing_fields_fix_plan.md`](app_generation_topn_product_table_missing_fields_fix_plan.md) 之间的执行策略空白。

当前主过程已经基本形成：

```text
业务输出字段列表
-> API 匹配
-> API response 字段匹配
-> 字段覆盖/填充计划 field_coverage_plan
```

但执行取数阶段还需要收口：

```text
field_coverage_plan
-> 按来源 API 生成取数计划
-> 绑定业务参数到 API 请求参数
-> live probe 取真实数据
-> 按 source_field_path 投影成业务中文字段表
-> 派生/扩展字段交给 Agent 生成草稿
```

本文档不修改 `tasks/current/*`，不手改历史 `runs/.../generated_apps/...`，不复制外部 spec-pack 内容。执行策略必须通过生成链路和 `report_generator` shell 生效。

## 核心结论

数据分析节点需要明确拆成两个阶段：

1. **字段覆盖/填充计划阶段**：解决“业务字段应该来自哪个 API、哪个 response 字段”。唯一事实源是 `api_doc_matcher.service match_business_context` 及用户在中间工作区审核后的 overlay/contract。
2. **执行取数/填充结果阶段**：解决“按已经选定的 API 和字段路径，如何取真实数据并填成结果表”。执行阶段只消费字段覆盖计划，不重新做 API/字段匹配。

因此，执行策略不是第二套 matcher，也不是右侧 Agent 对话。它是一个 deterministic runtime plan：把已审核的 `field_coverage_plan` 转成 `data_fetch_strategy`、`api_execution_plan`、`field_fill_strategy` 和 `data-table-draft-v1`。

## 目标

P0 目标：

- 点击“运行当前节点”时，系统使用当前中间工作区字段覆盖计划，而不是重新匹配 API。
- 字段覆盖计划中涉及多个 API 时，执行策略能生成多个 API 调用计划，并说明每个 API 是 `called`、`blocked`、`empty` 还是 `skipped`。
- 最终 TOP N 数据表只展示业务输出字段，不再追加宽的 `字段来源` 列。
- 字段来源保留在结构化 `field_sources[]`、取值状态区、字段详情或 tooltip 中。
- 如果只有一个 API 被调用，页面必须说明其它 API 为什么未调用，不能只显示 `merge: single_api` 让用户猜。
- 派生/扩展字段由右侧 Agent/PI 基于已取回数据生成草稿，不自动确认事实。

P1 目标：

- 支持更多独立 API 的多源填充。
- 支持轻量行级合并策略，例如共同 `product_id/item_id/goods_id/product_url/rank`。
- 支持用户对低置信字段、空值字段、派生字段进行人工修正后重新运行。

## 两阶段运行模型

### 阶段 1：字段覆盖/填充计划

输入：

- 节点业务上下文：目的、数据来源、执行动作、表格字段、分析结论。
- `output_field_requirements[]`：业务文档表格字段，保留中文字段名和说明。
- `data_mapping_context`：业务参数、上游产物和数据需求。
- 本地 `api_doc_index.json`。

输出：

- `field_coverage_plan[]`
- `candidate_apis[]`
- `selected_api_ids[]`
- `derived_field_plan[]`
- `coverage_summary`

约束：

- 字段匹配只由 `api_doc_matcher` 或明确的字段修正 overlay 产生。
- 前端不实现独立评分、rerank 或 fallback matcher。
- 派生字段不能强行匹配为 API 原生字段，应标记为 `derived_or_manual_required`。
- 每个 API 原生字段必须精确到 `source_api_id + source_field_path`，否则不能进入取数投影。

### 阶段 2：执行取数/填充结果

输入优先级：

1. 中间工作区当前字段覆盖 overlay。
2. 已保存的 `data_mapping_contract-v2.field_coverage_plan`。
3. 仅在前两者不存在时，调用 `api_doc_matcher.service match_business_context` 生成 baseline。

输出：

- `data_fetch_strategy-v1`
- `api_execution_plan[]`
- `data-table-draft-v1`
- `insight-draft-v1`
- `data-analysis-execution-trace-v1`

约束：

- 执行阶段不重新选择 API，不重新做字段匹配。
- 执行阶段可以做 value-aware repair，但必须记录为 `runtime_repair`，并标记置信度和人工复核状态。
- API required 参数缺失时，该 API `blocked`，不能把中文类目名塞进 ID 参数。
- 未开启 `DBA_LIVE_PROBE=1` 时只生成计划和 blocked 原因，不生成假数据。

## 数据合同

### `data_fetch_strategy-v1`

执行器在运行节点时生成，用于解释“为什么这样取数和填表”。

```json
{
  "schema_version": "data-fetch-strategy-v1",
  "node_id": "collect_top_products",
  "coverage_source": {
    "source_type": "workspace_overlay | confirmed_contract | matcher_baseline",
    "source_ref": "",
    "field_count": 17,
    "selected_api_ids": []
  },
  "known_params": {},
  "planned_api_calls": [],
  "field_fill_strategy": [],
  "merge_strategy": {
    "mode": "single_api | row_index_alignment | key_join | no_join | blocked",
    "primary_api_id": "",
    "join_keys": [],
    "review_required": false,
    "reason": ""
  },
  "source_display_policy": {
    "table_column_enabled": false,
    "details_panel_enabled": true
  },
  "risks": []
}
```

### `planned_api_calls[]`

由 `field_coverage_plan[].source_api_id` 聚合而来。

每个 API 调用计划至少包含：

- `api_id`
- `api_name`
- `covered_fields[]`
- `request_param_mapping[]`
- `params`
- `status`: `planned | called | blocked | skipped | empty`
- `blocked_reason`
- `rows_returned`
- `request_debug`
- `evidence_ref`

执行器必须能回答：

- 这个 API 为什么需要调用？
- 绑定了哪些请求参数？
- 哪些 required 参数缺失？
- 请求是否真的发出？
- 返回了多少行？
- 这个 API 覆盖的字段最终有没有填到表里？

### `field_fill_strategy[]`

每个业务输出字段一条。

```json
{
  "field_name": "商品主图",
  "field_description": "看视觉表达",
  "required": true,
  "fill_mode": "api_native | deterministic_derived | pi_derived_draft | manual_required | not_available",
  "source_api_id": "top300_product_analysis",
  "source_field_path": "data.result[].pic_url",
  "value_status": "present | empty | missing | source_path_missing | not_called | join_blocked",
  "rows_with_value": 50,
  "rows_missing_value": 0,
  "runtime_repair": null,
  "human_review_required": false
}
```

`field_fill_strategy[]` 是执行阶段的核心解释层。最终表不再用 `字段来源` 列承载来源信息，而是通过该结构展示取值状态和来源详情。

## 执行流程

`/api/nodes/:id/run` 遇到 `analysis_node_view.node_kind=data_analysis` 时：

1. 从上游 artifacts、当前节点输入和用户补充中提取 `known_params`。
2. 读取当前字段覆盖计划，记录 `coverage_source`。
3. 校验字段覆盖计划是否包含可投影的 `source_api_id + source_field_path`。
4. 按 `source_api_id` 聚合 `planned_api_calls[]`。
5. 使用 `api_doc_matcher.service bind_request_params` 绑定请求参数。
6. 类目 ID 参数先走 category resolver，解析失败则该 API blocked。
7. `DBA_LIVE_PROBE=1` 且 db-agent worker ready 时调用 `probe_sample`。
8. 从每个 API response 中提取真实 rows，空分页壳必须识别为 `[]`。
9. 按 `field_coverage_plan.source_field_path` 投影 API 原生字段。
10. 对 `排名`、`商品链接`、`价格带` 等允许的确定性字段执行 derived fill，并标记 `deterministic_derived`。
11. 对 `derived_or_manual_required`、空值字段和低置信字段调用右侧 Agent/PI 生成草稿建议。
12. 生成 `data-table-draft-v1`、`data_fetch_strategy-v1` 和 execution trace。

## 多 API 填充策略

P0 支持“独立 API 取数 + 明确合并状态”。

- 如果字段覆盖计划只涉及一个成功 API：`merge_strategy.mode=single_api`。
- 如果多个 API 都返回行，且无共同 key：使用 `row_index_alignment`，但必须 `review_required=true`，并在风险区显示“按行号对齐需人工复核”。
- 行号对齐时若副 API 行数少于主 API：超出的行不写入该副 API 字段（保持字段缺失），不得伪造或回填值；同时副 API 已取到的字段 `value_status` 仍按实际取数结果判定（如 `present`），不得因越界行而整体误判为 `missing`。
- 如果多个 API 有共同 key：使用 `key_join`，优先 key 为 `product_id`、`item_id`、`goods_id`、`product_url`、`rank`。
- 如果某 API 需要另一个 API 的返回值作为入参：该 API 标记 `blocked/dependency_required`，进入 P2。
- 如果某 API 返回空行：该 API `status=empty`，它覆盖的字段 `value_status=not_called` 或 `empty`，不得误判为其它 API 字段 missing。

执行阶段不能因为某 API blocked 就静默把字段改成别的 API 字段。若要改，必须走 runtime repair，并在中间工作区显示“建议修复，待人工确认”。

## 前端交互

中间工作区保留主流程：

1. 字段覆盖/填充计划。
2. 运行当前节点。
3. 取数与填充策略。
4. 数据表草稿。
5. 分析结论草稿。

### 字段覆盖区

- 展示业务字段、字段说明、来源 API、response 字段路径、覆盖状态。
- 用户可修正错配字段。
- 一键生成字段覆盖方案只调用 matcher，不触发真实取数。

### 取数与填充策略区

新增一个可折叠区，展示：

- 本次使用的 `coverage_source`。
- 每个 API 的调用状态、参数绑定状态、请求 debug、返回行数。
- 每个字段的 `fill_mode` 和 `value_status`。
- `merge_strategy` 的可读解释，例如“仅一个 API 成功返回商品行”或“两个 API 按行号对齐，需人工复核”。

### 数据表草稿区

- 只展示业务输出字段，不显示 `字段来源` 列。
- `商品主图` 等图片 URL 渲染为缩略图。
- 字段来源通过字段详情、tooltip 或“取值状态/字段来源”折叠区查看。
- TOP N 支持分页，默认 50 行。
- API 原生空值显示为空值状态，不伪造内容。

### 右侧 Agent

右侧 Agent 只处理：

- 缺失字段解释。
- 低置信字段纠错。
- API 原生为空字段的补充建议。
- 派生字段逐行草稿。
- 分析结论草稿。

右侧 Agent 不负责：

- 主 API 选择。
- 字段覆盖主流程。
- 合同确认。
- 默认 live probe。

## 需要修改的模块

### 文档

- 新增本文档。
- `PROJECT_OVERVIEW.md` 增加本文档入口。
- 后续可将关键合同同步回 technical design，避免执行策略散落在多份文档。

### Server

修改 `shells/report_generator/server/server.js`：

- 新增或补强 `buildDataFetchStrategy(...)`。
- `runDataAnalysisNode(...)` 使用 `coverage_source`，并产出 `data_fetch_strategy`。
- `projectRowsForApiFieldCoverage(...)` 继续按 API 分别投影，但把来源解释交给 `field_fill_strategy[]`。
- 删除最终行里的 `字段来源` 注入逻辑；保留 `field_sources[]`。
- 多 API 未合并时明确输出 `row_index_alignment` 或 `join_blocked`，不能退化成误导性的 missing。

### Frontend

修改 `shells/report_generator/web/app.js`：

- 数据表预览不再特殊展示 `字段来源` 列。
- 新增或补强“取数与填充策略”面板。
- `merge_strategy` 显示为可读解释，不用裸露 `merge：single_api`。
- 字段来源从表格列迁移到字段状态详情。

### Styles

修改 `shells/report_generator/web/styles.css`：

- 数据表保持紧凑，图片缩略图固定尺寸。
- 取值状态/来源详情支持横向滚动或折叠。
- 长 API id、字段路径、request URL 自动换行，不撑破三栏布局。

### Tests

更新：

- `tests/test_shell_server.py`
- `tests/test_report_generator_shell.py`
- 必要时更新 `tests/test_api_doc_matcher_service.py`

## 实施任务

### Task 1：执行策略合同

- [ ] 增加 `data-fetch-strategy-v1` 结构生成。
- [ ] 记录 `coverage_source`：workspace overlay、confirmed contract 或 matcher baseline。
- [ ] 将 `field_coverage_plan` 聚合成 `planned_api_calls[]`。
- [ ] 将字段投影结果整理成 `field_fill_strategy[]`。
- [ ] 单测覆盖：2 个 API 的字段覆盖计划必须生成 2 个 planned calls。

### Task 2：执行阶段只消费字段覆盖计划

- [ ] 确认 `/api/nodes/:id/run` 请求携带当前 overlay。
- [ ] 执行器优先使用 overlay，其次合同，最后 matcher baseline。
- [ ] 禁止执行阶段做独立 API rerank 或字段 matcher fallback。
- [ ] 单测覆盖：有 overlay 时不会调用 matcher baseline。

### Task 3：多 API 取数状态解释

- [ ] 每个 API 记录 `planned/called/blocked/skipped/empty`。
- [ ] `single_api` 时说明只有哪个 API 成功返回行，以及其它 API 为什么未参与。
- [ ] 多 API 无 join key 时标记 `row_index_alignment` 且 `review_required=true`。
- [ ] 行号对齐时副 API 行数不足：越界行不伪造值，副 API 已取字段不被误判为 `missing`（回归测试覆盖）。
- [ ] 依赖另一个 API 输出作为入参时标记 `dependency_required`。

### Task 4：最终表移除 `字段来源` 列

- [ ] 删除 server 侧给每行注入 `字段来源` 的逻辑。
- [ ] 删除 frontend 侧 `字段来源` 作为 preview field 的特殊处理。
- [ ] 保留 `field_sources[]`、`field_fill_strategy[]` 和 evidence ref。
- [ ] 前端增加字段来源详情区或 tooltip。
- [ ] 单测覆盖：data table rows 不包含 `字段来源`，但 result 仍包含 `field_sources[]`。

### Task 5：取数与填充策略 UI

- [ ] 中间工作区新增“取数与填充策略”区。
- [ ] 显示 coverage source、API 调用状态、参数绑定、返回行数。
- [ ] 显示字段取值状态和来源详情。
- [ ] 将裸露 `merge：single_api` 替换成中文解释。

### Task 6：验收和回归

- [ ] `node --check shells/report_generator/server/server.js`
- [ ] `node --check shells/report_generator/web/app.js`
- [ ] `python3 -m unittest tests.test_shell_server tests.test_report_generator_shell -v`
- [ ] live preview 验收流程2：一键字段覆盖 -> 运行当前节点 -> TOP N 表格只显示业务字段 -> 来源在详情区可查。

## 验收标准

静态验收：

```bash
node --check shells/report_generator/server/server.js
node --check shells/report_generator/web/app.js
python3 -m unittest tests.test_shell_server tests.test_report_generator_shell -v
```

应用端验收：

1. 重新生成一个 app_generation run。
2. 用最新 shell 启动 preview。
3. 打开“行业大盘与热销商品分析”。
4. 点击“一键生成字段覆盖方案”，确认 17 个业务字段形成覆盖/派生计划。
5. 点击“运行当前节点”。
6. 查看“取数与填充策略”：
   - 能看到本次使用的 coverage source。
   - 能看到所有 planned API。
   - 能看到每个 API 的 called/blocked/empty/skipped 状态。
   - 如果显示 single API，必须解释其它 API 为什么未调用或未返回行。
7. 查看 TOP N 数据表：
   - 表格不包含 `字段来源` 列。
   - 图片字段显示缩略图。
   - 字段来源可在详情区查看。
   - 空值、missing、not_called、join_blocked 状态可追踪。
8. 派生/扩展字段：
   - 右侧 Agent 只生成草稿建议。
   - 无证据时不生成事实值。
   - 任何 Agent 结果都不自动 confirmed。

## 边界

- P0 不做复杂依赖式 API 编排，例如先查商品 ID 列表再批量查详情。
- P0 不把来源信息塞回最终数据表列。
- P0 不自动确认字段覆盖、派生字段或分析结论。
- live probe 未开启时不生成假数据。
- API/字段匹配仍以 `api_doc_matcher` 为唯一事实源。
