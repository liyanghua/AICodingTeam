# TOP N 商品表缺失字段修复计划

## 状态

本文档记录流程2运行后 TOP N 商品表字段缺失的定位结论和后续修复计划。目标是让数据分析节点在 live 模式下尽可能生成可审核的 TOP N 商品表：API 原生字段优先，确定性派生字段其次，Agent/PI 只负责扩展字段和低置信字段草稿，所有非事实值保持人工确认边界。

本文档不要求修改 `tasks/current/*`，不手改历史 `runs/.../generated_apps/...`，不复制外部 PI spec-pack 内容进仓库。

## 当前问题定位

当前 live run 并不是完全没有取到数据。`top300_product_analysis` 已经返回 50 行，并能填充店铺名、商品主图、销量/支付买家数、GMV/交易指数、产品类型、是否高增速等字段。

仍然缺失的字段主要来自四类问题：

- 类目 ID 参数错误：`data_ads_ind_sycm_speed_category_goods_m` 等接口需要 `cid`，但当前把中文类目名 `桌垫` 直接绑定到 `cid`，导致接口返回 `{totalNum:0,result:[]}`。
- 行提取误判：分页壳 `{data:{pageNum,pageSize,totalNum,result:[]}}` 被当成一行，trace 误报 `rows_returned=1`。
- 运行时缺少值感知修复：`排名` 可以由 TOP N 行号确定性生成，`商品链接` 可由 `commodity_id` 生成待确认链接，但当前仍报 missing。
- 派生字段未写入逐行草稿：`功能`、`风格`、`主图元素`、`爆款原因` 只生成字段级 advice，没有形成 cell-level draft。

## P0 修复目标

点击“运行当前节点”后，流程2应生成 TOP 50 商品列表草稿：

- API 原生可取字段直接填充。
- `排名` 由主 API 行号确定性派生。
- `商品链接` 由商品 ID 确定性派生并标记待人工确认。
- `材质`、`场景`、`主卖点` 如果 API 原生为空，进入 empty/needs_agent_fill，而不是误报 API missing。
- `功能`、`风格`、`主图元素`、`爆款原因` 进入右侧 Agent/PI 草稿填充，不再是 `not_called`。
- 不再把中文类目名错误传给 `cid/category_id/cate_id` 类型参数。

## Category Resolver

类目名称到类目 ID 的解析必须作为取数前置层，而不是靠 API worker 猜测。

### 参数语义识别

请求参数按语义分为两类：

- 类目名称参数：`category_name`、`cate_name`、`tertiary_category`，或描述包含“类目名称/三级类目/叶子类目名称”。这类参数可以直接绑定业务输入里的中文类目名。
- 类目 ID 参数：`cid`、`cate_id`、`category_id`、`cat_id`，或描述包含“类目ID”。这类参数必须绑定真实 ID，不能绑定中文类目名。

绑定规则：

```text
known_params.category = "桌垫"

API param = category_name / tertiary_category / cate_name
  -> params[param] = "桌垫"

API param = cid / cate_id / category_id / cat_id
  -> 先查 known_params.cid/category_id/cate_id
  -> 没有 ID 时进入 Category Resolver
  -> 解析失败则 blocked: category_id_required
```

### 类目解析输入输出

新增运行时解析结果结构：

```json
{
  "schema_version": "category-resolution-v1",
  "status": "resolved | needs_input | blocked",
  "category_name": "桌垫",
  "category_id": "",
  "source_api_id": "",
  "source_field_paths": {
    "name": "data.result[].cate_name",
    "id": "data.result[].cate_id"
  },
  "confidence": 0,
  "alternatives": [],
  "evidence_ref": "",
  "blocked_reason": ""
}
```

解析优先级：

1. 直接使用上游或用户输入的 `cid`、`category_id`、`cate_id`、`cat_id`。
2. 如果目标 API 支持类目名称参数，直接绑定中文类目名，不做 ID 解析。
3. 从 `api_doc_index` 查找同时返回类目名称字段和类目 ID 字段的候选 API，例如返回 `cate_name/cate_id`、`category_name/cid`、`category_name/category_id` 的接口。
4. live 模式下调用可用的类目解析候选 API，并用类目名称做精确或规范化匹配。
5. 如果候选 API 本身也必须依赖未知 `cid`，不得递归乱调；该候选标记 `resolver_requires_category_id`。
6. 解析失败时，目标 API 调用计划标记 blocked，并输出 `category_id_required`，同时建议改用接受类目名称的 API 或让用户手工选择类目 ID。

### API 选择策略

字段覆盖阶段应记录每个候选 API 的类目参数类型：

- `category_binding_mode=name_supported`：可直接用类目名取数，优先作为 live 验收 API。
- `category_binding_mode=id_required_resolvable`：需要先解析 ID，解析成功后可调用。
- `category_binding_mode=id_required_unresolved`：缺少 ID，默认 blocked。
- `category_binding_mode=not_category_scoped`：不依赖类目参数。

对于 TOP N 商品表，运行时优先使用能稳定返回商品行的主 API；如果某个高匹配 API 因 `category_id_required` blocked，不能让它造成整表 missing，应使用已成功返回商品行的主 API 做值感知回退。

## 行提取和投影修复

`rowsFromProbePayload` 需要识别常见响应结构：

- `payload.response.top[]`
- `payload.response.data.result[]`
- `payload.response.response.top[]`
- `top[0].result[]`
- 空分页壳 `{totalNum:0,result:[]}` 返回 `[]`，不能返回分页壳对象。

投影前必须记录每个 API 的真实行数。只有真实商品行参与 `row_index_alignment`，空分页 API 不参与合并，也不触发 `row_index_merge_requires_review`。

## 值感知字段修复

字段覆盖计划是 schema 级匹配，运行时还需要检查真实返回值：

- 如果字段映射到的 API 没有真实行，尝试在已调用且有行的 API 中寻找同名、别名或候选字段。
- 如果字段路径存在但所有值为空，标记 `empty`，不要标记 `missing`。
- `客单价` 优先使用实际有值的 `unit_price`，避免选中全 0 的 `previous_customer_unit_price`。
- `价格带` 可优先使用 API 原生 `price_band`；没有时基于 `unit_price` 生成待确认派生价格带。

确定性派生规则：

- `排名`：主 API 有 TOP N 行时，`排名 = row_index + 1`，`source_kind=deterministic_derived`，`derivation_method=row_index_rank`。
- `商品链接`：如果有 `commodity_id`、`goods_id` 或 `item_id`，生成 `https://item.taobao.com/item.htm?id=<id>`，`source_kind=deterministic_derived`，`human_confirmation.status=unconfirmed`。

## Agent/PI 逐行草稿填充

右侧 Agent 只处理以下字段：

- API 原生为空的字段：如 `材质`、`场景`、`主卖点`。
- 派生字段：如 `功能`、`风格`、`主图元素`、`爆款原因`。
- 低置信或用户指出错配的字段。

`derived_field_fill` 应返回逐行草稿，而不是只返回字段级建议：

```json
{
  "schema_version": "derived-field-fill-v1",
  "node_id": "collect_top_products",
  "rows": [
    {
      "row_index": 0,
      "fields": {
        "功能": {"draft_value": "", "confidence": 0.6, "evidence_fields": ["商品标题", "商品主图"]},
        "爆款原因": {"draft_value": "", "confidence": 0.5, "evidence_fields": ["销量/支付买家数", "GMV/交易指数"]}
      }
    }
  ],
  "human_confirmation": {"status": "unconfirmed"}
}
```

前端展示为“草稿/待确认”，不能显示为 confirmed，也不能自动进入下游事实源。

## 需要修改的模块

- `api_doc_matcher/service.py`
  - 增加类目参数语义识别。
  - 增加 `resolve_category` 或等价 helper。
  - `bind_request_params` 对 `cid/category_id/cate_id` 不再绑定中文类目名。
- `api_doc_matcher/matcher.py`
  - 调整 `排名`、`客单价`、`价格带`、`商品链接` 的匹配优先级。
  - 保留派生字段为 `derived_or_manual_required`，不强行误配。
- `shells/report_generator/server/server.js`
  - 修复 `rowsFromProbePayload`。
  - 在 `groupedApiPlansForCoverage` 或执行器中接入 Category Resolver。
  - 增加值感知字段修复和确定性派生。
  - 让 PI `derived_field_fill` 支持逐行草稿写回。
- `shells/report_generator/web/app.js`
  - 商品表展示 `api_native`、`deterministic_derived`、`pi_derived_draft`、`empty`、`needs_review` 状态。
  - 请求调试区展示 category resolution 结果和 blocked reason。
- `tests/test_api_doc_matcher_service.py`
  - 覆盖类目名参数直接绑定、类目 ID 参数阻断、已有 ID 直接绑定。
- `tests/test_shell_server.py`
  - 覆盖空分页壳、排名派生、商品链接派生、空值状态、category_id_required、逐行派生草稿。

## 验收标准

静态和单测：

```bash
python3 -m py_compile api_doc_matcher/service.py api_doc_matcher/matcher.py
node --check shells/report_generator/server/server.js
node --check shells/report_generator/web/app.js
python3 -m unittest tests.test_api_doc_matcher_service tests.test_shell_server tests.test_report_generator_shell -v
```

应用端验收：

1. 重新生成一个 app_generation run，确保使用最新 `api_doc_index.json`。
2. 用 `DB_ARCHAEOLOGIST_SPEC_PACK` 和 `DBA_LIVE_PROBE=1` 启动 preview。
3. 打开流程2“行业大盘与热销商品分析”。
4. 点击运行当前节点。
5. 请求调试区不能再出现 `cid=桌垫`。
6. 如果没有可解析的类目 ID，应显示 `category_id_required`，并说明可改用类目名称参数 API 或人工选择 ID。
7. TOP 50 商品表应展示 50 行。
8. `排名` 应为 `1..50`。
9. `商品链接` 应由商品 ID 派生并标记待确认。
10. API 原生为空的字段进入 `empty/needs_agent_fill`，不再被误判成 API missing。
11. 派生字段显示 Agent 草稿或待填草稿状态，不再是 `not_called`。

## 边界

- 本轮不做复杂依赖式多 API join，例如先拿 `goods_id_list` 再批量查详情；可作为 P1.5/P2。
- 类目解析失败时宁可 blocked，也不发送错误参数。
- Agent/PI 草稿必须保留证据字段和人工确认状态。
- 不读取或暴露 `.env` secrets。
