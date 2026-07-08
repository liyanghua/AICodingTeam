# 右侧 Agent 数据需求映射技术设计

## 状态

本文档定义右侧 Agent 数据需求映射的技术合同，配套产品规范见 [`app_generation_right_agent_data_mapping_spec.md`](app_generation_right_agent_data_mapping_spec.md)。

当前文档是 spec-first 设计，用于指导后续实现。本文档不声明当前代码已经完整实现 `data_mapping_contract` 持久化，也不要求修改 `tasks/current/*`。

## 目标架构

数据需求映射链路位于生成应用 `report_generator` 的右侧 Agent 面板中，作为节点事实层之外的协作能力。

```text
当前节点 app.config.json
  + node_execution_view
  + input_model.required_data
  + output_model.outputs[].schema
  + 上游 artifacts
  + 用户补充输入
        |
        v
右侧 Agent 数据映射流程
        |
        v
db_archaeologist bridge
  -> select_tools_for_task
  -> ask_api_catalog
  -> get_api_asset_card
  -> probe_api_sample (optional, DBA_LIVE_PROBE=1 only)
        |
        v
data_mapping_contract
        |
        v
本节点 evidence/artifacts
```

右侧 Agent 不直接成为节点执行器。它只能把外部数据能力映射结果保存为可追溯证据，供节点后续执行或人工验收使用。

## 现有接口对齐

### `GET /api/db-agent/status`

用途：检测数仓助手 bridge 是否可用。

响应必须继续包含：

```json
{
  "status": "ok",
  "reason": "ready",
  "spec_pack_configured": true,
  "spec_pack_root": "/path/to/db-archaeologist-pi-spec-pack",
  "worker_available": true,
  "loader_available": true,
  "live_probe_enabled": false,
  "allowed_tools": [
    "ask_api_catalog",
    "select_tools_for_task",
    "list_domain_apis",
    "get_api_asset_card",
    "probe_api_sample"
  ]
}
```

约束：

- `status` 可为 `ok` 或 `degraded`。
- 未配置 `DB_ARCHAEOLOGIST_SPEC_PACK` 时返回 `degraded/spec_pack_not_configured`，不得阻断基础应用。
- 不返回 `.env`、secret、完整环境变量或数据库凭据。
- `live_probe_enabled` 只由 `DBA_LIVE_PROBE=1` 控制。

### `POST /api/db-agent/query`

用途：执行单次数据映射动作。

请求：

```json
{
  "node_id": "collect_top_products",
  "action": "field_map",
  "known_params": {
    "category": "入户地垫",
    "period": "近30天",
    "product_line": "地垫"
  },
  "upstream_artifacts": [],
  "api_id": "/api/category/top-products"
}
```

支持 action：

- `understand_input`
- `tool_plan`
- `field_map`
- `probe_sample`

后续可以保留现有扩展 action，如 `catalog`、`domain_apis`、`asset_card`，但 P0 产品流程只依赖上面四个。

响应兼容策略：

- 保留现有 `ok`、`status`、`action`、`known_params`、`payload`、`evidence_ref` 字段。
- 新增或派生 `data_mapping_contract` 字段。
- 旧前端读取 `payload` 不应被破坏。

示例响应：

```json
{
  "ok": true,
  "status": "ok",
  "node_id": "collect_top_products",
  "action": "field_map",
  "known_params": {
    "category": "入户地垫",
    "period": "近30天"
  },
  "payload": {},
  "data_mapping_contract": {},
  "evidence_ref": "evidence/collect_top_products.db_agent.field_map.json"
}
```

## `data_mapping_contract`

`data_mapping_contract` 是数据需求映射流程的稳定产物。它应该能从任意一次 `understand_input`、`tool_plan`、`field_map` 或 `probe_sample` 响应中渐进构建。

最小结构：

```json
{
  "schema_version": "data-mapping-contract-v1",
  "node_id": "collect_top_products",
  "business_requirement": {
    "title": "行业大盘与热销商品分析",
    "description": "获取三级类目的类目排行和商品排行，生成行业前300商品分析表。",
    "required_outputs": ["top_300_product_analysis_table"],
    "required_fields": ["rank", "shop_name", "product_url", "price"],
    "source_text": ""
  },
  "source_context_refs": [
    {
      "kind": "node_execution_view",
      "ref": "app.config.json:nodes.collect_top_products.node_execution_view",
      "summary": "节点执行动作和产物要求"
    }
  ],
  "known_params": {
    "category": "入户地垫",
    "period": "近30天",
    "product_line": "地垫"
  },
  "candidate_apis": [
    {
      "api_id": "/api/category/top-products",
      "name": "类目商品排行",
      "domain": "商品域",
      "capability": "商品分析",
      "quality_score": 0.91,
      "missing_params": [],
      "risks": []
    }
  ],
  "selected_api": {
    "api_id": "/api/category/top-products",
    "name": "类目商品排行",
    "method": "POST",
    "path": "/api/category/top-products",
    "domain": "商品域",
    "capability": "商品分析"
  },
  "request_param_mapping": [
    {
      "business_param": "分析类目",
      "api_param": "category",
      "value": "入户地垫",
      "source": "upstream_artifact",
      "status": "filled_from_business_input"
    }
  ],
  "response_field_mapping": [
    {
      "business_field": "rank",
      "api_field_path": "data.rows.rank",
      "api_field_name": "rank",
      "api_field_type": "number",
      "confidence": 1,
      "status": "matched",
      "match_basis": "name/path/description synonym match"
    }
  ],
  "unmatched_fields": [],
  "human_decisions": [
    {
      "decision_id": "confirm-selected-api",
      "decision": "confirmed",
      "target": "selected_api",
      "note": "用户确认使用类目商品排行接口。",
      "created_at": "2026-07-06T00:00:00Z"
    }
  ],
  "evidence_refs": [
    "evidence/collect_top_products.db_agent.field_map.json"
  ],
  "status": "confirmed"
}
```

字段规则：

- `schema_version` 固定为 `data-mapping-contract-v1`。
- `node_id` 必须等于当前节点 ID。
- `business_requirement` 必须来自节点业务上下文、数据需求和产物 schema，不得只复述用户一句查询。
- `source_context_refs` 必须记录来源，至少包含当前节点或上游 artifact。
- `known_params` 是业务参数归一结果，不保存 secret。
- `candidate_apis` 来自 tool selector 或 catalog。
- `selected_api` 必须有 `api_id` 才能进入 `confirmed` 或 `sample_ready`。
- `request_param_mapping` 记录请求参数来自哪里，缺失时 status 为 `missing`。
- `response_field_mapping` 记录业务字段到 API 字段路径的映射。
- `unmatched_fields` 非空时，合同状态不得自动变成 `confirmed`，除非 `human_decisions` 明确记录替代口径或暂缺处理方式。
- `evidence_refs` 指向生成应用本地 evidence/artifacts 相对路径。

## 状态机

```text
draft
  -> suggested
  -> needs_input
  -> confirmed
  -> sample_ready

draft/suggested/needs_input -> rejected
any -> blocked
any -> degraded
```

状态含义：

- `draft`：只有初始业务输入或节点上下文，还没有候选 API。
- `suggested`：已有候选 API、工具链或字段匹配建议。
- `needs_input`：缺少必要参数、API ID、字段口径或用户确认。
- `confirmed`：用户确认合同可作为本节点输入/证据。
- `rejected`：用户拒绝当前建议。
- `sample_ready`：已基于确认合同生成样例取数证据。
- `blocked`：live probe 未开启、工具被禁用、权限不足或外部调用失败。
- `degraded`：spec-pack 未配置或 bridge 不可用，但基础应用仍可运行。

转换规则：

- `probe_sample` 只能从 `confirmed` 或明确传入 `api_id` 的 `suggested` 状态尝试。
- `probe_sample` 在 `DBA_LIVE_PROBE` 未开启时返回 `blocked/live_probe_disabled`。
- `api_id_required` 类错误必须转换为 `needs_input`，并给出“请选择候选 API 或先执行 API 映射”的下一步提示。
- 用户确认是从 `suggested` 或 `needs_input` 进入 `confirmed` 的唯一入口。

## 构建流程

### `understand_input`

输入：

- `node_id`
- `known_params`
- `upstream_artifacts`
- 当前节点视图模型

输出合同片段：

- `business_requirement`
- `source_context_refs`
- `known_params`
- `status=draft` 或 `needs_input`

### `tool_plan`

输入：

- 上一步合同片段。
- 当前节点标题、数据需求 ID、输出 schema 摘要。

输出合同片段：

- `candidate_apis`
- `known_params`
- `status=suggested` 或 `needs_input`

### `field_map`

输入：

- 候选或选中 `api_id`。
- API asset card。
- 节点 required fields。

输出合同片段：

- `selected_api`
- `request_param_mapping`
- `response_field_mapping`
- `unmatched_fields`
- `status=suggested`、`needs_input` 或 `blocked`

### `confirm`

P0 可以由“保存为本节点输入/证据”承载，后续可独立成 action。

输入：

- 当前合同草稿。
- 用户确认、替代口径或缺口处理决策。

输出：

- `human_decisions`
- `status=confirmed`
- `evidence_ref`

### `probe_sample`

输入：

- 已确认合同。
- `selected_api.api_id`。
- 已填请求参数。

输出：

- 样例取数 evidence。
- 可选草稿 artifact。
- `status=sample_ready` 或 `blocked`。

## 持久化约定

生成应用本地目录：

```text
generated_apps/<app_slug>/
  evidence/
    <node_id>.data_mapping_contract.json
    <node_id>.db_agent.<action>.json
  artifacts/
    <node_id>.db_agent.json
```

规则：

- 每次工具调用原始归一结果保存为 `evidence/<node_id>.db_agent.<action>.json`。
- 用户确认后的合同保存为 `evidence/<node_id>.data_mapping_contract.json`。
- live probe 返回 rows 时，可以生成 `artifacts/<node_id>.db_agent.json` 草稿产物。
- 只有 `data_mapping_contract.status=confirmed|sample_ready` 的结果可以作为本节点输入/证据供后续节点消费。
- 不覆盖旧 run，不写 `tasks/current/*`。

## 前端状态模型

右侧 Agent 前端应维护每个节点的映射状态：

```json
{
  "node_id": "collect_top_products",
  "current_action": "field_map",
  "busy": false,
  "last_result": {},
  "data_mapping_contract": {},
  "selected_api_id": "/api/category/top-products",
  "pending_user_decisions": []
}
```

渲染区块：

- 业务输入理解。
- 候选 API/工具链。
- 请求参数映射。
- 响应字段映射。
- 未匹配字段和下一步问题。
- 人工确认区。
- 可选样例取数区。

按钮约束：

- `匹配字段` 在没有候选 API 时仍可执行，但必须返回 `needs_input` 和候选 API 选择提示。
- `拉取样例数据` 在合同未确认或 live probe 未开启时置灰或返回可行动阻断。
- `保存为本节点输入/证据` 必须保存合同摘要，不应只保存 raw worker response。

## 错误处理

错误必须转成用户可行动状态。

| 原因 | 用户可见状态 | 下一步 |
| --- | --- | --- |
| `spec_pack_not_configured` | 数仓助手未配置 | 配置 `DB_ARCHAEOLOGIST_SPEC_PACK` 或继续手工上传 |
| `ts_loader_not_found` | 数仓助手加载器不可用 | 检查 spec-pack 安装 |
| `api_id_required` | 需要选择 API | 先执行“映射数仓 API”或手动选择候选 API |
| `api_id_required_for_field_map` | 字段匹配缺少 API | 从候选 API 中选择一个 |
| `live_probe_disabled` | 样例取数未开启 | 设置 `DBA_LIVE_PROBE=1` 后重启应用 |
| `worker_error` | 数仓工具调用失败 | 展示错误摘要和 evidence ref |

raw JSON 可以放入可展开调试区，但默认 UI 必须展示业务语言。

## 安全与权限

- worker 白名单只允许调用数据能力查询相关工具。
- `probe_api_sample` 必须由 `DBA_LIVE_PROBE=1` 显式开启。
- 不把 spec-pack 内容复制进本仓库或生成应用。
- 不持久化 secret。
- 不把工具结果自动写成最终业务结论。
- 不允许右侧 Agent 绕过用户确认改变节点事实。

## 测试计划

文档静态检查：

```bash
test -f docs/app_generation_right_agent_data_mapping_spec.md
test -f docs/app_generation_right_agent_data_mapping_technical_design.md
rg "app_generation_right_agent_data_mapping" docs/PROJECT_OVERVIEW.md
```

后续实现回归：

```bash
node --check shells/report_generator/server/server.js
node --check shells/report_generator/web/app.js
python3 -m unittest tests.test_shell_server.DbAgentApiTests tests.test_report_generator_shell.ReportGeneratorShellTests -v
```

API 场景：

- 未配置 `DB_ARCHAEOLOGIST_SPEC_PACK` 时，`GET /api/db-agent/status` 返回 `degraded`，基础应用仍可运行。
- `tool_plan` 能从上游《市场洞察项目定义表》提取 `category`、`period`、`product_line`。
- fake spec-pack 下，`field_map` 返回 `data_mapping_contract.response_field_mapping` 和 `unmatched_fields`。
- 没有 `api_id` 时，`field_map` 返回 `needs_input`，而不是让用户看到不可行动错误。
- `DBA_LIVE_PROBE` 未开启时，`probe_sample` 返回 `blocked/live_probe_disabled`。
- live probe 返回 rows 时，生成样例 artifact，合同状态进入 `sample_ready`。

人工验收：

- 用户点击第二步节点后，右侧 Agent 显示业务输入、候选 API、字段匹配、人工确认和样例取数区。
- 未确认合同前，样例取数不可直接作为节点完成状态。
- 保存后，本节点证据能追溯到业务文档片段、上游 artifact、候选 API 和字段映射。

## 后续增强

- 增加独立 `confirm_mapping` action。
- 支持用户在 UI 中手动编辑字段映射。
- 支持多 API 组合完成一个节点产物。
- 将 `data_mapping_contract` 纳入 runtime smoke 断言。
- 将合同升级为跨节点可复用的数据能力记忆，而不是仅保存在单个生成应用中。
