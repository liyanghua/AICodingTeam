# PI 数据映射建议可视化实现文档

## 状态

本文档是 `report_generator` 生成应用中“API 建议 -> 字段映射 -> PI 建议 -> 人工确认”链路的独立实现文档。

它承接以下已存在设计：

- [`app_generation_right_agent_data_mapping_spec.md`](app_generation_right_agent_data_mapping_spec.md)：右侧 Agent 数据需求映射产品规范。
- [`app_generation_right_agent_data_mapping_technical_design.md`](app_generation_right_agent_data_mapping_technical_design.md)：`data_mapping_contract`、db-agent actions、持久化和安全边界。
- [`pi_right_agent_protocol_spec.md`](pi_right_agent_protocol_spec.md)：右侧 PI Agent Provider 的协议边界。

本文档只定义后续实现范围，不修改 `tasks/current/*`，不手改已生成的 `runs/.../generated_apps/...` 作为最终方案。所有能力必须从 `report_generator` shell 和 deterministic generator 生效。

## 背景与问题

当前多 API 字段映射工作台已经把问题从“选一个 API”升级为“多个数仓 API 共同覆盖一个节点产物字段列表”。但用户验收时仍有一个关键断点：

- 右侧 Agent 能给出候选 API 和字段列表，但 PI 给出的判断与建议不可见或不可操作。
- 用户无法看到 PI 为什么认为某个 API 可用、某个字段应该映射到哪个返回字段、哪些字段需要人工确认。
- 中间字段覆盖工作台和右侧 PI 建议之间没有清晰的“建议 -> 应用草稿 -> 人工确认”流转。
- 如果 PI 不可用，页面容易退化成 raw error，而不是展示可继续操作的降级状态。

本次实现目标是把 PI 从“聊天回答”收敛为“结构化数据映射建议提供者”。PI 可以帮助理解和建议，但不能直接确认合同、不能直接写节点事实、不能默认触发 live probe。

## 目标

P0 目标：

- 用户在流程节点中选择多个候选 API 并查看返回字段后，可以点击右侧 Agent 获取 PI 的结构化建议。
- PI 建议必须在右侧以可读结构展示：API 评估、字段建议、join/粒度建议、风险、下一步问题。
- 中间字段覆盖工作台能显示 PI 建议标记，并允许用户把建议应用为草稿 overlay。
- 只有用户在中间工作台点击确认后，才生成或更新 `data_mapping_contract` 的确认版本。
- PI 不可用、未配置或返回纯文本时，系统仍返回可展示的 `pi-data-mapping-advice-v1` fallback。

P0 不做：

- 不做真实多 API join 数据合并。
- 不默认 live probe。
- 不让 PI 直接调用真实数仓。
- 不让 PI 自动确认字段映射合同。
- 不把 PI 原始长文本直接作为节点事实源。

## 用户工作流

### 设计原则：一次生成建议，内联决策

旧版工作流有两个断点导致体验差：

1. 用户要分别触发“智能匹配字段”和“获取 PI 建议”两次，语义重叠、等待两次。
2. PI 建议展示在右侧，应用操作却要回到中间工作台，用户来回切换 7-9 次。

本版把这两个动作合并为一次“智能匹配字段（PI 增强）”，并把 PI 建议内联到中间工作台每个字段行，用户无需跨区切换。

### 简化后的目标交互链路（7 步）

```text
业务文档节点产物字段要求
-> 中间字段覆盖工作台显示字段列表
-> 右侧 Agent 推荐候选 API，用户选择一个或多个
-> 用户点击“智能匹配字段（PI 增强）”
     -> Server 先跑确定性规则匹配形成 baseline
     -> Server 把 baseline + 候选 API 完整 schema + 上游业务参数交给 PI
     -> PI 返回 pi-data-mapping-advice-v1（逐字段判断、置信度、理由、更优字段）
-> 中间工作台每行字段内联显示 PI 徽标、理由和快捷操作（应用/忽略/人工）
-> 用户批量“应用高置信建议”或逐字段决策
-> 用户点击“确认映射合同”
-> 合同写入 evidence
```

### 页面责任划分

- 中间工作区是唯一确认入口，也是 PI 建议的展示与决策入口：负责字段覆盖计划、内联 PI 建议、批量编辑、join plan 和合同确认。
- 右侧 Agent 只保留业务理解、API 推荐、asset card 查看和触发“智能匹配字段（PI 增强）”；不再单独展示 PI 文本建议，不再有独立的“获取 PI 建议”按钮。
- Server 负责组织 PI 输入上下文（含 API 完整 schema）、跑确定性 baseline、归一 PI 输出为结构化 advice、保存 PI advice evidence。

## 核心数据合同

### `pi-data-mapping-advice-v1`

新增结构化 PI 建议合同。它不是 `data_mapping_contract` 的替代品，而是围绕当前合同草稿给出的可审计建议。

```json
{
  "schema_version": "pi-data-mapping-advice-v1",
  "node_id": "collect_top_products",
  "advice_id": "pi-advice-20260706-000001",
  "created_at": "2026-07-06T00:00:00Z",
  "input_refs": {
    "data_mapping_contract_status": "suggested",
    "selected_api_count": 2,
    "field_coverage_count": 18,
    "confirmed_field_count": 0
  },
  "summary": {
    "status": "needs_review",
    "text": "当前字段覆盖基本可用，但商品唯一键、时间窗口和部分增长指标口径需要确认。"
  },
  "api_review": [
    {
      "api_id": "/api/category/top-products",
      "api_name": "类目商品排行",
      "judgement": "useful",
      "reason": "覆盖排名、商品基础信息、价格、交易指数等核心排行字段。"
    }
  ],
  "field_advice": [
    {
      "field_path": "items.properties.rank",
      "field_name": "rank",
      "current_source_api_id": "/api/category/top-products",
      "current_source_field_path": "data.rows.rank",
      "judgement": "ok",
      "confidence": 0.95,
      "suggested_action": "keep",
      "reason": "字段语义和粒度一致。",
      "suggested_source_api_id": "/api/category/top-products",
      "suggested_source_field_path": "data.rows.rank"
    }
  ],
  "join_advice": {
    "judgement": "needs_input",
    "recommended_primary_api_id": "/api/category/top-products",
    "recommended_join_keys": ["product_id"],
    "grain": "product",
    "time_window": "近30天",
    "risks": [
      "当前候选 API 未全部确认 product_id 字段，不能保证多 API 行级合并。"
    ]
  },
  "questions_for_user": [
    "商品唯一键使用 product_id 还是 item_id？",
    "分析周期是否统一为近30天？"
  ],
  "applicable_actions": [
    {
      "action_id": "apply-rank-field",
      "type": "update_field_mapping",
      "field_path": "items.properties.rank",
      "patch": {
        "mapping_status": "suggested",
        "human_note": "PI 建议保留当前映射。"
      }
    }
  ],
  "requires_human_confirmation": true
}
```

字段约束：

- `schema_version` 固定为 `pi-data-mapping-advice-v1`。
- `node_id` 必须等于当前节点。
- `summary.status` 可取 `ok`、`needs_review`、`needs_input`、`blocked`、`unavailable`。
- `api_review[].judgement` 可取 `useful`、`partial`、`risky`、`not_recommended`。
- `field_advice[].judgement` 可取 `ok`、`needs_review`、`missing`、`better_alternative`。
- `field_advice[].confidence` 为 0-1 浮点数，表示 PI 对该字段建议的置信度。缺失时 normalizer 补 0。
- `field_advice[].suggested_action` 可取 `keep`、`change_source`、`manual_fill`、`ask_user`、`ignore`。
- `join_advice.judgement` 可取 `ok`、`needs_input`、`risky`、`not_needed`。
- `applicable_actions` 只能更新前端草稿 overlay，不得直接确认合同。
- `requires_human_confirmation` 必须为 `true`，除非只是不可用状态说明。

### 置信度与批量应用规则（P0）

置信度决定字段建议能否被批量应用，是避免“一键应用全部建议”误操作的核心闸门：

- `judgement=ok` 且 `confidence >= 0.9`：高置信，可被“应用高置信建议”批量采纳。
- `0.7 <= confidence < 0.9`：中置信，只允许逐字段手动应用，不进入批量应用。
- `confidence < 0.7`，或 `judgement` 为 `needs_review` / `missing` / `better_alternative`：强制人工确认，批量应用必须跳过。
- 批量应用只写 draft overlay 的 `mapping_status=suggested`，不置 `human_confirmed=true`；用户仍需在中间工作台确认合同。
- 前端“应用高置信建议”按钮必须显示阈值（例如 `≥0.9`），并在应用后提示“跳过 N 个低置信字段，需人工处理”。

### 与 `data_mapping_contract-v2` 的关系

`data_mapping_contract-v2` 仍是字段映射事实合同：

- `selected_apis[]`：用户选择的 API 集合。
- `field_coverage_plan[]`：输出字段覆盖计划。
- `join_plan`：主 API、join key、粒度、时间口径和风险。
- `coverage_summary`：覆盖统计。

`pi-data-mapping-advice-v1` 只引用和评估当前合同草稿：

- 可以建议修改 `field_coverage_plan[]`。
- 可以建议补充 `join_plan`。
- 可以提示用户缺参数、缺字段、口径不一致。
- 不得把 `data_mapping_contract.status` 改成 `confirmed`。

## Server 实现

修改 `shells/report_generator/server/server.js`。

### `POST /api/pi-agent/query`

请求体扩展：

```json
{
  "node_id": "collect_top_products",
  "message": "请评估当前 API 和字段映射是否合理",
  "data_mapping_contract": {},
  "selected_api_asset_cards": [],
  "field_coverage_plan": [],
  "join_plan": {},
  "business_context": {},
  "upstream_artifacts": []
}
```

响应体扩展：

```json
{
  "ok": true,
  "status": "ok",
  "provider": "pi_agent",
  "response_text": "",
  "advice": {},
  "evidence_ref": "evidence/collect_top_products.pi_mapping_advice.json"
}
```

实现要求：

- `piPromptForDataMapping()` 必须把以下上下文注入 PI prompt：
  - 当前节点标题、业务片段、执行动作、判断标准和产物要求。
  - `data_mapping_contract` 当前状态。
  - `selected_apis[]` 和对应 asset cards 的**完整 request/response schema**（字段名、路径、类型、描述），而不是只给 `api_id`。这是 PI 能做语义匹配而非空猜的前提。
  - `field_coverage_plan[]` baseline，包含输出字段、确定性规则匹配出的来源 API、字段路径、匹配分数、确认状态。PI 在此基础上纠错和增强，而不是从零开始。
  - `join_plan`，包含主 API、join key、粒度、时间窗口和风险。
  - 上游 artifacts 摘要，例如第一步《市场洞察项目定义表》，用于补齐类目、周期、产品线等业务参数。
  - 用户当前消息。
- PI prompt 必须明确要求 PI 输出 `pi-data-mapping-advice-v1` JSON，并附带一份 few-shot 示例，锚定输出结构；如果无法完整判断，输出 `questions_for_user`。
- PI prompt 必须要求 PI 对每个字段给出 `judgement`、`confidence`（0-1）、`reason`，以及在有更优字段时给出 `suggested_source_api_id` / `suggested_source_field_path`。
- PI prompt 必须禁止只输出“请确认”“建议人工核对”之类无信息量的通用文本。
- PI prompt 必须明确禁止：
  - 直接确认合同。
  - 直接调用 live probe。
  - 编造不存在的 API 字段。
  - 输出 secret、凭据、完整环境变量。

### Advice normalizer

新增 `normalizePiMappingAdvice(raw, context)`。

归一规则：

- 如果 PI 返回合法 JSON 且包含 `schema_version=pi-data-mapping-advice-v1`，按白名单字段归一。
- 如果 PI 返回 JSON 但字段缺失，补齐 `advice_id`、`created_at`、`input_refs`、`requires_human_confirmation`。
- 如果 PI 返回纯文本，把文本放入 `summary.text`，`summary.status=needs_review`，并基于当前合同生成 deterministic fallback。
- 如果 PI 未配置、超时或调用失败，返回：

```json
{
  "schema_version": "pi-data-mapping-advice-v1",
  "summary": {
    "status": "unavailable",
    "text": "PI Agent 未就绪，仍可在中间工作台手动确认字段映射。"
  },
  "requires_human_confirmation": true
}
```

fallback 生成规则：

- 对已映射字段生成 `field_advice.judgement=needs_review`。
- 对未覆盖必填字段生成 `field_advice.judgement=missing` 和 `suggested_action=ask_user`。
- 如果存在多个 selected APIs 且没有 join key，生成 `join_advice.judgement=needs_input`。
- 如果没有 selected APIs，生成 `summary.status=needs_input` 和问题“请先选择候选 API”。

### Evidence 持久化

每次 PI 建议调用写入：

```text
evidence/<node_id>.pi_mapping_advice.json
```

保存内容：

```json
{
  "node_id": "collect_top_products",
  "created_at": "2026-07-06T00:00:00Z",
  "request_summary": {
    "selected_api_count": 2,
    "field_coverage_count": 18,
    "confirmed_field_count": 0
  },
  "advice": {},
  "source": {
    "provider": "pi_agent",
    "degraded": false
  }
}
```

不得保存：

- `.env` 内容。
- API key、cookie、token、数据库密码。
- 完整进程环境。
- PI scratch 中无关文件全文。

## Frontend 实现

修改 `shells/report_generator/web/app.js`。

### 中间工作台内联 PI 建议（替代旧的右侧 PI 面板）

不再在右侧 Agent 中单独渲染“PI 建议结果”区块。PI 建议直接内联到中间字段覆盖工作台，每个字段行就地展示判断和操作。

工作台顶部状态栏：

- 覆盖摘要：`字段 N · 已覆盖 M · 已确认 K · 必填未覆盖 X · PI 待处理 P`。
- 批量操作按钮：
  - `应用高置信建议 (≥0.9)`：只应用 `judgement=ok && confidence>=0.9` 的字段。
  - `批量确认已审核字段`：把已 `suggested/mapped` 的字段一次性置为确认草稿。
  - `确认映射合同`：人工触发，生成 confirmed 合同。
- PI 摘要一行：`advice.summary.text` + 状态徽标（`ok`/`needs_review`/`needs_input`/`blocked`/`unavailable`）。

每行字段就地展示：

- PI 徽标：`PI: 可保留` / `PI: 建议换字段` / `PI: 缺口` / `PI: 需复核`。
- PI 置信度：显示 `confidence`，低于阈值高亮提示需人工。
- PI 理由：短文本，长文本 `<details>` 折叠。
- 行级快捷操作：`应用` / `忽略` / `人工`。

Join 区：内联 PI 推荐的主 API、join key、grain、time window 和风险。

UI 文案原则：

- 使用“PI 建议”，不要使用“PI 已确认”。
- 使用“应用为草稿”，不要使用“保存为事实”。
- 使用“需要你确认”，不要把缺口显示为不可行动 raw error。
- PI 不可用时展示“仍可手动完成映射”，而不是阻断页面。

### `queryPiEnhancedMapping()`

合并旧的 `suggest_multi_api_mapping` 触发和 `queryPiAgent`。由中间工作台“智能匹配字段（PI 增强）”按钮触发，一次请求完成 baseline 匹配 + PI 增强。

请求必须携带完整结构化上下文：

- `data_mapping_contract`：当前草稿合同。
- `selected_api_asset_cards`：用户已选择 API 的 asset card（完整 request/response schema）。
- `field_coverage_plan`：中间工作区当前 overlay，作为 baseline。
- `join_plan`：中间工作区当前 join 草稿。
- `business_context`：节点业务片段和数据需求上下文。
- `upstream_artifacts`：上游节点产物摘要。

响应写入 `state.piAgentResults[node.id]`，并把 baseline `field_coverage_plan` 写入 `state.fieldMappingDrafts[node.id]`，供内联渲染叠加 PI 徽标。

### 应用 PI 建议

行级和批量操作统一走前端 draft overlay：

- `applyHighConfidenceAdvice()`：遍历 `field_advice`，只对 `judgement=ok && confidence>=0.9` 的字段写 `suggested`，其余跳过并提示待人工数。
- `applyFieldAdvice(fieldPath)`：单字段应用 PI 建议来源和字段路径。
- `ignoreFieldAdvice(fieldPath)`：保持原值，标记已处理。
- `markFieldManual(fieldPath)`：把字段标记为 `manual_fill` 草稿。
- `confirmAllReviewed()`：把已 `suggested/mapped` 的字段批量置为确认草稿。

约束：

- 所有操作只能改浏览器中的 draft overlay。
- 操作不能调用 `confirm_mapping`。
- 操作不能把字段 `human_confirmed` 直接置为 `true`。
- 用户仍需在中间工作台点击“确认映射合同”。

## 中间字段覆盖工作台实现

中间工作台是主操作区，也是 PI 建议的唯一展示区。

新增展示：

- 每行字段显示 PI 建议徽标：
  - `PI: 可保留`
  - `PI: 建议换字段`
  - `PI: 缺口`
  - `PI: 需复核`
- 每行显示 PI 建议置信度和原因短文本，长文本可展开。
- 覆盖摘要增加“PI 建议待处理数”。
- Join 区显示 PI 推荐主 API、join key、grain、time window 和风险。

批量更新：

- `应用高置信建议 (≥0.9)`：只写高置信字段。
- `批量确认已审核字段`：把 `suggested/mapped` 字段一次性置为确认草稿。
- 批量操作只更新 draft overlay。
- 确认合同仍需要独立点击“确认映射合同”。

本地保存：

- 字段覆盖 draft、selected APIs、asset cards、join plan、PI advice 可写入 `localStorage`，key 必须按 `run/app/node` 分区，避免不同 run 污染。
- 不得保存 secret 或真实样例数据。
- 页面刷新后应恢复未确认草稿，并提示“草稿未确认”。

## Generated App 链路

deterministic generator 必须继续复制新版 shell 文件，确保新生成应用天然具备能力：

- `app.config.json` 中已有 `output_field_requirements` 和 `data_mapping_context`。
- `report_generator` server 提供 PI advice query。
- `report_generator` web 展示 PI 建议和中间工作台 overlay。
- `runtime_smoke.js` 不依赖真实 PI 或真实数仓，也能验证 fallback 行为。

不得通过手改 `runs/<run_id>/generated_apps/<slug>/...` 作为最终修复。

## 测试计划

静态检查：

```bash
node --check shells/report_generator/server/server.js
node --check shells/report_generator/web/app.js
python3 -m py_compile growth_dev/team/app_generation.py growth_dev/team/complex_task.py growth_dev/cli.py
bash -n scripts/accept_app_generation_cli_baseline.sh
```

Server 单测：

- PI 未配置时，`POST /api/pi-agent/query` 返回 `pi-data-mapping-advice-v1`，`summary.status=unavailable`。
- PI 返回纯文本时，server 包装为结构化 advice。
- PI 返回合法 JSON 时，server 归一、补齐字段并保存 evidence。
- PI advice 中的 `applicable_actions` 不会修改 confirmed contract。
- advice evidence 不包含 secret、完整 env 或真实凭据。

Frontend 静态测试：

- 中间工作台包含 PI 徽标、置信度、行级“应用/忽略/人工”操作。
- 页面包含 API review、field advice、join advice、questions 的内联展示逻辑。
- 页面包含“应用高置信建议 (≥0.9)”和“批量确认已审核字段”。
- 页面不包含“PI 自动确认”类交互，也不再有独立的右侧“PI 建议结果”面板。
- 批量应用只写高置信字段，低置信字段被跳过。

Runtime smoke：

- `/api/pi-agent/status` 返回可解释状态。
- `/api/pi-agent/query` 在 PI 未配置时仍返回 `advice.schema_version=pi-data-mapping-advice-v1`。
- PI advice 不会把 `data_mapping_contract.status` 改为 `confirmed`。
- 至少一个节点存在 `output_field_requirements` 和 `data_mapping_context.multi_api_mapping.enabled=true`。

CLI 验收：

```bash
PATH="document-to-skill-engineering-package/.venv/bin:$PATH" \
RUN_ID=app-generation-pi-advice-accept-20260706-01 \
APP_SLUG=market-insight-pi-advice-01 \
BUILD_STRATEGY_KB=0 \
bash scripts/accept_app_generation_cli_baseline.sh
```

人工验收：

1. 启动新生成应用 preview。
2. 打开“流程2：行业大盘与热销商品分析”。
3. 中间字段覆盖工作台显示完整输出字段列表。
4. 右侧 Agent 推荐多个候选 API。
5. 用户选择多个 API 并查看返回字段。
6. 点击“智能匹配字段（PI 增强）”，一次完成 baseline 匹配和 PI 增强。
7. 中间工作台每行字段就地显示 PI 徽标、置信度和理由，无需切换到右侧。
8. 点击“应用高置信建议 (≥0.9)”，低置信字段保持未映射并提示待人工数。
9. 逐字段用行级“应用/忽略/人工”处理剩余字段，或批量确认已审核字段。
10. 确认字段和 join plan。
11. 点击“确认映射合同”。
12. 生成 `evidence/collect_top_products.data_mapping_contract.json`。

## 失败与降级状态

| 场景 | UI 状态 | 用户下一步 |
| --- | --- | --- |
| PI 未配置 | `unavailable` | 继续手动确认字段映射 |
| PI 返回纯文本 | `needs_review` | 查看摘要和 fallback 建议 |
| 未选择 API | `needs_input` | 先选择候选 API |
| 必填字段未覆盖 | `needs_review` | 手动补字段或标记人工补充 |
| 多 API 无 join key | `needs_input` | 确认主 API 和 join key |
| PI 超时 | `blocked` 或 `unavailable` | 重试或手动完成 |
| spec-pack 未配置 | db-agent `degraded` | 配置 `DB_ARCHAEOLOGIST_SPEC_PACK` 或使用手动映射 |

所有失败状态必须展示可行动说明，不得只展示 `action_not_allowed`、`api_id_required`、`spec_pack_not_configured` 这类 raw code。

## 安全边界

- PI 只负责理解和建议。
- 中间工作区用户确认是唯一事实入口。
- 未确认 advice 不进入节点事实源。
- `DBA_LIVE_PROBE=1` 只影响后续样例取数，不影响 PI 建议。
- 不复制外部 PI spec-pack 内容进本仓库。
- 不保存或展示 secret。
- 不默认调用真实数仓。
- 不把样例数据解释成业务结论。

## 实施顺序

### P0.1 Server advice 合同

- 增强 `piPromptForDataMapping()`：注入候选 API 完整 schema、baseline `field_coverage_plan`、上游业务参数、few-shot 示例。
- 实现 `pi-data-mapping-advice-v1` normalizer，含逐字段 `confidence`。
- 实现 PI 未配置、纯文本、JSON 三类 fallback；纯文本/未配置时用确定性 baseline 生成 `field_advice`。
- 保存 `evidence/<node_id>.pi_mapping_advice.json`。
- 增加 server 单测。

### P0.2 合并 baseline 与 PI 调用

- `suggest_multi_api_mapping` 分支先跑确定性 baseline，再调用 PI 增强，同时返回 `data_mapping_contract` 和 `pi_advice`。
- PI 增强失败时降级为 baseline-only，`summary.status` 明确标注。
- 前端“智能匹配字段（PI 增强）”一次触发完成 baseline + PI。

### P0.3 中间工作台内联建议

- 字段覆盖表内联 PI 徽标、置信度、理由和行级“应用/忽略/人工”。
- 覆盖摘要增加“PI 待处理数”。
- `应用高置信建议 (≥0.9)` 只写高置信字段，低置信跳过并提示。
- `批量确认已审核字段` 批量置确认草稿。
- join plan 内联 PI 建议。
- 删除右侧独立 PI 面板，确认合同逻辑保持人工触发。

### P0.4 生成链路和验收

- 确保 deterministic generator 复制新版 shell。
- 更新 runtime smoke 的 PI advice fallback 断言。
- 跑静态检查、单测和 CLI 验收。

## 后续增强

P1：

- PI runtime 真机状态检测和流式建议展示。
- PI 对每个字段给出更细的匹配置信度和替代字段排序。
- 从 asset card 的 request/response schema 自动生成更强的字段相似度特征。

P2：

- 合同确认后触发可选 live probe。
- 多 API 样例数据 join 草稿。
- 用真实返回样例反校字段映射风险。

P3：

- 将可复用字段映射沉淀为跨 run 的 mapping memory。
- 对相同业务文档/相同 API 复用历史确认结果，但必须保留用户确认 gate。
