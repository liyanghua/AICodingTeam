# 数据分析节点生成模型与技术合同

## 状态

本文档是 `app_generation` 数据分析节点的技术设计，配套产品规范见 [`app_generation_data_analysis_node_spec.md`](app_generation_data_analysis_node_spec.md)。

本文档只定义后续实现目标和接口合同，不声明当前代码已经完整实现。本文档不要求修改 `tasks/current/*`，不默认启用真实数仓 live probe，不手改历史生成应用。

## 目标

生成应用需要把业务策略文档中的数据分析流程转译为统一节点视图模型。该模型必须能回答：

- 节点为什么要运行。
- 节点需要哪些输入。
- 节点按什么步骤运行。
- 节点产出什么结构化数据表。
- 节点如何形成分析结论。
- 哪些结果已经被用户确认，哪些仍是草稿或建议。

为此，新增语义层模型 `analysis_node_view`。它不是替代现有底层模型，而是把 `node_execution_view`、`output_field_requirements`、`data_mapping_context`、`data_mapping_contract-v2` 和业务文档片段组织成用户可理解的数据分析节点。

## 生成链路

```text
业务策略文档流程段
  -> document-to-skill / Strategy KB / Skill snapshot
  -> workflow node + data_requirements + output_schemas
  -> app_generation node config
  -> analysis_node_view
  -> report_generator 中间工作区
```

生成阶段必须保留来源追踪，避免把业务文档直接压成不可追溯 prompt。

## `analysis_node_view`

最小结构：

```json
{
  "schema_version": "analysis-node-view-v1",
  "node_id": "collect_top_products",
  "node_kind": "data_analysis",
  "purpose_model": {},
  "input_model": {},
  "execution_plan": {},
  "data_output_model": {},
  "insight_output_model": {},
  "verification_model": {},
  "source_trace": {}
}
```

字段说明：

- `node_kind`：语义层判定，取值 `data_analysis` 或 `standard`。它与节点顶层 `kind`（执行类型枚举 `form`/`data`/`compute`/`llm`/`aggregate`）正交，不复用、不覆盖、也不依赖顶层 `kind`。`data_analysis` 的判定条件是节点同时具备 `data_requirements` 和非空 `output_field_requirements`，与顶层 `kind` 取值无关。
- `purpose_model`：业务目的和验收意图。
- `input_model`：数据来源、上游产物、业务参数、缺口。
- `execution_plan`：执行动作拆解后的步骤清单。
- `data_output_model`：数据表产物字段、字段覆盖和来源 API。
- `insight_output_model`：分析结论要求、证据依赖和结论草稿。
- `verification_model`：字段完整性、数据证据、结论确认的检查项。
- `source_trace`：原始业务文档、Skill snapshot、output schema、data requirement、API doc index 的引用。

## `purpose_model`

```json
{
  "title": "行业大盘与热销商品分析",
  "purpose": "了解谁涨得快、谁稳定、谁赚钱，并判断流行趋势和机会点。",
  "business_questions": [
    "哪些商品在当前类目中增长最快？",
    "哪些价格带和产品类型更值得关注？"
  ],
  "success_criteria": [
    "能生成行业前300商品分析表",
    "能形成有数据证据的机会判断"
  ],
  "source_ref": "business_doc:流程2.1"
}
```

生成规则：

- 优先从业务文档 `目的` 小节抽取。
- 若没有独立目的小节，可从 workflow node title、business_context、data requirement 描述中降级生成。
- 不得把 Agent 后续聊天内容写入 `purpose_model`。

## `input_model`

```json
{
  "data_sources": [
    {
      "name": "生意参谋类目排行",
      "description": "获取类目排行和商品排行",
      "source_ref": "business_doc:流程2.2"
    }
  ],
  "upstream_artifacts": [
    {
      "node_id": "define_market_scope",
      "artifact_title": "市场洞察项目定义表",
      "required_fields": ["分析类目", "分析周期", "分析产品线"]
    }
  ],
  "known_params": {},
  "missing_params": [],
  "data_requirement_ids": ["category_top_products_300"],
  "api_matching": {
    "provider": "api_doc_matcher",
    "strategy": "field_coverage_rerank",
    "status": "not_started"
  }
}
```

生成规则：

- `data_sources` 来自业务文档 `数据来源`。
- `upstream_artifacts` 来自 DAG 依赖和上游节点产物声明。
- `data_requirement_ids` 来自 Skill snapshot 的 data requirements。
- `known_params` 可以在运行时由上游 artifact 填充，生成时只放声明和来源。

## `execution_plan`

```json
{
  "steps": [
    {
      "step_id": "resolve_scope",
      "title": "确定类目和周期",
      "instruction": "从市场洞察项目定义表读取分析类目、产品线和周期。",
      "requires": ["upstream_artifact:market_insight_project_definition"],
      "produces": ["known_params"],
      "human_review_required": false,
      "source_ref": "business_doc:流程2.3"
    },
    {
      "step_id": "map_fields",
      "title": "匹配数据字段",
      "instruction": "根据表格字段要求匹配真实 API 返回字段。",
      "requires": ["output_field_requirements", "api_doc_index"],
      "produces": ["data_mapping_contract"],
      "human_review_required": true
    }
  ]
}
```

生成规则：

- 优先从业务文档 `执行动作` 抽取。
- 表格中的动作、编号动作、自然语言动作都应规范化为 step。
- 每个 step 必须声明依赖和产物，缺失时用空数组而不是省略。
- `human_review_required` 对字段映射、派生字段和结论确认默认为 true。

## `data_output_model`

```json
{
  "output_id": "top_300_product_analysis_table",
  "title": "行业前300商品分析表",
  "fields": [
    {
      "field_path": "items.properties.商品主图",
      "field_name": "商品主图",
      "description": "看视觉表达",
      "required": true,
      "source_schema_ref": "skill_snapshot/output_schemas/top_300_product_analysis_table.json",
      "mapping_status": "unmapped",
      "source_api_id": "",
      "source_field_path": "",
      "source_kind": ""
    }
  ],
  "coverage_summary": {
    "total": 17,
    "mapped": 0,
    "derived_or_manual_required": 0,
    "missing_required": 17
  },
  "contract_ref": ""
}
```

生成规则：

- `fields` 由 `output_field_requirements` 生成，必须保留中文业务字段名和字段说明。
- 字段覆盖结果运行时来自 `api_doc_matcher.service match_business_context`。
- 派生字段使用 `source_kind=pi_derived|manual|derived`，不得强行标记为 API 原生覆盖。
- `contract_ref` 指向确认后的 `data_mapping_contract-v2` evidence；未确认时为空。

## `insight_output_model`

```json
{
  "title": "行业大盘与热销商品分析结论",
  "requirements": [
    {
      "question": "哪些商品具备爆款机会？",
      "required_evidence_fields": ["排名", "销量/支付买家数", "GMV/交易指数", "是否高增速", "爆款原因"],
      "source_ref": "business_doc:分析结论"
    }
  ],
  "draft": {
    "status": "not_started",
    "text": "",
    "evidence_refs": [],
    "risks": []
  },
  "human_confirmation": {
    "status": "unconfirmed",
    "confirmed_by": "",
    "confirmed_at": ""
  }
}
```

生成规则：

- `requirements` 来自业务文档 `分析结论` 小节；没有独立小节时，可从 `判断标准`、`产出`、执行动作中的“分析/判断/结论”语句降级生成。
- 结论草稿必须引用 `data_output_model.fields`、上游 artifact 或样例行证据。
- 没有数据证据时，Agent 只能输出分析方案或问题清单，不能输出事实结论。
- 人工确认前，`draft.status` 不得等同于 confirmed。

## `verification_model`

```json
{
  "checks": [
    {
      "check_id": "required_fields_covered",
      "title": "必填字段已覆盖",
      "status": "pending",
      "evidence_refs": []
    },
    {
      "check_id": "insight_has_evidence",
      "title": "分析结论有证据引用",
      "status": "pending",
      "evidence_refs": []
    }
  ]
}
```

检查项建议：

- 必填字段覆盖率。
- API 字段来源可追溯。
- 派生字段有处理方案。
- 数据表产物已生成或明确处于未取数状态。
- 分析结论引用了数据字段或证据。
- 用户确认状态明确。

## 与现有模型对齐

`analysis_node_view` 不替代以下字段：

- `node_execution_view`：仍保存从 workflow section 抽取的目标、动作、验证、产物。
- `output_field_requirements`：仍作为字段要求的底层事实。
- `data_mapping_context`：仍作为 API/字段匹配上下文。
- `data_mapping_contract-v2`：仍作为字段映射确认合同。
- `data-table-confirmation-v1`：记录确认时的 workspace revision、行列数、空值数、覆盖值数及忽略的待采纳建议数。
- `data-table-confirmed-v1`：固化当前 `effective_rows`、字段、行身份和覆盖审计，作为下一节点读取的表格产物；后续编辑会使该确认失效。

确认接口：

```text
POST /api/nodes/:node_id/data-table-workspace/confirm
```

请求必须携带 `base_revision`。运行中的 Agent batch 返回 `409 agent_batch_running`；revision 不一致返回 `409 revision_conflict`；空表返回 `409 data_table_empty`。成功后写入 `artifacts/<node_id>.confirmed_data_table.json` 与 `evidence/<node_id>.data_table_confirmation.json`，前端保存返回 artifact、标记当前节点完成并进入下一节点。
- `business_context`：仍保存 Strategy KB 命中的原文片段。
- `node.kind`：仍是节点顶层执行类型枚举 `form`/`data`/`compute`/`llm`/`aggregate`。`analysis_node_view.node_kind` 是独立的语义层判定，不修改也不读取顶层 `kind`；判断某节点是否为数据分析节点只看 `data_requirements` 和 `output_field_requirements`，不看顶层 `kind`。

`analysis_node_view` 的职责是组织这些底层对象，让前端按数据分析节点范式渲染，而不是让用户直接理解底层合同。

## API 与服务边界

字段覆盖：

- 由 `api_doc_matcher.service match_business_context` 负责。
- 输入包含节点业务上下文、数据来源、输出字段、上游参数。
- 输出 `field_coverage_plan`、`candidate_apis`、`coverage_summary` 和派生字段计划。

右侧 Agent：

- 可读取 `analysis_node_view`、字段覆盖草稿和结论草稿。
- 只能返回建议，例如字段纠错、派生字段分析方案、结论草稿建议。
- 不得直接写 confirmed 状态。

真实取数：

- 不在 P0 默认路径，P1 才进入节点执行链路。
- 必须受 `DBA_LIVE_PROBE=1` 控制；未开启时返回 blocked，不生成假数据。
- 样例/真实数据只能作为 evidence 或草稿产物，用户确认前不得成为 confirmed 事实。

## P1 `data_analysis_execution`

P1 新增运行时结果合同 `data_analysis_execution`，由 `/api/nodes/:id/run` 在数据分析节点上生成。该合同描述一次节点执行，而不是字段映射合同。

最小结构：

```json
{
  "schema_version": "data-analysis-execution-v1",
  "node_id": "collect_top_products",
  "status": "blocked",
  "known_params": {
    "category": "入户地垫",
    "period": "近30天",
    "product_line": "地垫"
  },
  "execution_steps": [
    {
      "step_id": "resolve_scope",
      "status": "done",
      "evidence_refs": ["artifacts/define_scope.json"]
    }
  ],
  "api_execution_plan": [
    {
      "api_id": "top300_product_analysis",
      "source_fields": ["排名", "店铺名", "商品链接"],
      "request_param_mapping": [
        {
          "api_param": "cat_id",
          "api_param_path": "query.cat_id",
          "business_param": "category",
          "business_param_label": "分析类目",
          "source": "upstream_artifact",
          "source_ref": "artifacts/define_scope.json#分析类目",
          "value": "入户地垫",
          "required": true,
          "status": "bound",
          "binding_method": "deterministic_alias",
          "confidence": 0.92,
          "human_confirmed": false
        },
        {
          "api_param": "date_range",
          "api_param_path": "query.date_range",
          "business_param": "period",
          "business_param_label": "分析周期",
          "source": "upstream_artifact",
          "source_ref": "artifacts/define_scope.json#分析周期",
          "value": "近30天",
          "required": true,
          "status": "manual_required",
          "binding_method": "api_doc_matcher",
          "confidence": 0.74,
          "human_confirmed": false
        }
      ],
      "params": {
        "cat_id": "入户地垫"
      },
      "missing_required_params": ["date_range"],
      "status": "blocked"
    }
  ],
  "data_table_ref": "",
  "insight_draft_ref": "",
  "execution_trace_ref": "evidence/collect_top_products.execution_trace.json"
}
```

状态取值：

- `blocked`：缺字段覆盖、缺参数、未开启 live probe、数仓助手不可用。
- `degraded`：部分 API 成功、部分失败，或只能生成取数计划。
- `partial_data_table_ready`：已生成部分字段数据表，仍有必填字段未取回。
- `data_table_ready`：API 原生字段已按覆盖方案投影为数据表草稿。
- `insight_draft_ready`：数据表草稿与分析结论草稿都已生成。

## P1 参数绑定合同

取数链路必须显式完成“业务语义参数 -> API 请求参数”的绑定，不能把 `known_params` 原样透传给 worker 后依赖下游猜测。

输入来源：

- `known_params`：从上游 artifact、当前节点表单和人工补充中提取的业务参数，例如 `category`、`period`、`product_line`。
- API asset card：来自本地 `api_doc_index` 或 db-agent 的 `request_schema`、`request_params`、required 列表和参数说明。
- `data_mapping_contract-v2`：字段覆盖合同中的 `selected_apis[]`、`field_coverage_plan[]` 和人工备注。

输出结构落在 `api_execution_plan[].request_param_mapping[]`：

```json
{
  "api_param": "cat_id",
  "api_param_path": "query.cat_id",
  "api_param_type": "string",
  "business_param": "category",
  "business_param_label": "分析类目",
  "source": "upstream_artifact | node_input | user_override | default | derived",
  "source_ref": "artifacts/define_scope.json#分析类目",
  "value": "入户地垫",
  "required": true,
  "status": "bound | missing | manual_required | unsupported",
  "binding_method": "deterministic_alias | api_doc_matcher | db_agent | pi_advice | manual",
  "confidence": 0.92,
  "missing_reason": "",
  "human_confirmed": false
}
```

绑定规则：

- 先使用确定性别名表和 API 文档参数说明匹配，例如 `分析类目/category/类目` 对 `cat_id/category_id/category_name`，`分析周期/period/time_window` 对 `date_range/start_date/end_date`。
- `api_doc_matcher.service bind_request_params` 是本地 API 索引模式下的请求参数绑定事实源。它输入 `api_id`、`known_params`、`execution_date` 和 `timezone`，输出 `request-param-binding-v1`，其中包含 `params`、`request_param_mapping[]`、`missing_required_params[]`、`dropped_optional_params[]` 和 `normalized_period`。
- 日期类参数必须结合 API 参数名、参数说明和日期角色转换，不能把 `period` 原样透传给所有时间字段：
  - `deal_date`、`biz_date`、`dt`、`date`、`day` 绑定为单日，默认取规范化周期的 `end_date`，格式为 `YYYY-MM-DD`。
  - `start_date`、`begin_date`、`from_date` 绑定为规范化周期的 `start_date`，格式为 `YYYY-MM-DD`。
  - `end_date`、`to_date` 绑定为规范化周期的 `end_date`，格式为 `YYYY-MM-DD`。
  - `date_range`、`time_range`、`period` 绑定为 `start_date,end_date`。
  - `statist_date`、`statistics_date`、`biz_month`、`month` 等月度参数绑定为 `YYYY-MM`。
  - `update_time`、`created_at`、`modified_time`、`sync_time` 等审计时间字段不能自动绑定业务分析周期，除非用户直接提供同名 API 参数或人工确认。
- 周期归一化默认使用 `Asia/Shanghai` 与当前执行日期；例如 `execution_date=2026-07-09` 且 `period=近30天` 时，`start_date=2026-06-10`、`end_date=2026-07-09`、`month=2026-07`。
- `api_doc_matcher.service match_business_context` 负责字段覆盖与 API 候选；db-agent/PI 可以补充建议，但不能在无证据时静默写入必填参数。
- API required 参数缺失时，该 API 的 `status=blocked`，`missing_required_params[]` 必须列出缺口，并在中间工作区显示可行动问题。
- P1 只支持由当前 `known_params` 直接绑定的独立 API 调用。需要先调用另一个 API 才能得到的参数，例如 `product_id[]`、`shop_id[]`，标记为 `unsupported/dependency_required`，进入 P2。
- 只有 `status=bound` 或经人工确认的 `manual_required` 参数才能写入 `api_execution_plan[].params`。

## P1 字段投影粒度

字段覆盖必须精确到可投影的 response path。`field_coverage_plan[]` 中每个 API 原生字段至少包含：

```json
{
  "field_name": "排名",
  "source_kind": "api_doc_index",
  "source_api_id": "top300_product_analysis",
  "source_api_name": "行业前300商品分析",
  "source_field_path": "data.result[].rank",
  "source_field_name": "rank",
  "mapping_status": "mapped",
  "confidence": 0.91
}
```

约束：

- `source_api_id` 只说明来源 API，不足以执行投影。
- `source_field_path` 缺失时，该字段不能参与数据表投影，字段状态应为 `source_path_missing` 或 `manual_required`。
- `source_field_path` 应使用 API asset card 的 response schema 或 response field catalog 生成，例如 `data.result[].rank`、`data.rows[].item.title`。
- 派生字段可以没有 `source_field_path`，但必须进入 `derived_field_plan[]`，并声明所需证据字段。

## P1 产物合同

数据表草稿：

```json
{
  "schema_version": "data-table-draft-v1",
  "node_id": "collect_top_products",
  "title": "行业前300商品分析表",
  "status": "draft",
  "fields": [],
  "rows": [],
  "field_sources": [
    {
      "field_name": "排名",
      "source_kind": "api_doc_index",
      "source_api_id": "top300_product_analysis",
      "source_field_path": "data.result[].rank",
      "evidence_ref": "evidence/collect_top_products.db_agent.probe_sample.json",
      "mapping_status": "mapped",
      "api_call_status": "called",
      "value_status": "present",
      "rows_with_value": 300,
      "rows_missing_value": 0
    }
  ],
  "derived_fields": [],
  "risks": []
}
```

分析结论草稿：

```json
{
  "schema_version": "insight-draft-v1",
  "node_id": "collect_top_products",
  "status": "draft",
  "requirements": [],
  "text": "",
  "evidence_refs": [],
  "evidence_fields": [],
  "risks": [],
  "human_confirmation": {
    "status": "unconfirmed"
  }
}
```

执行轨迹：

```json
{
  "schema_version": "data-analysis-execution-trace-v1",
  "node_id": "collect_top_products",
  "created_at": "",
  "known_params": {},
  "field_coverage_ref": "",
  "api_calls": [],
  "pi_calls": [],
  "blocked_reasons": [],
  "artifact_refs": []
}
```

落盘路径：

- `artifacts/<node_id>.data_table.json`
- `artifacts/<node_id>.insight_draft.json`
- `evidence/<node_id>.execution_trace.json`

`field_sources[].value_status` 用于区分字段覆盖和真实取值：

- `present`：API 已调用，投影后至少一行有值。
- `missing`：API 已调用，但 response 中没有该字段。
- `empty`：字段存在但值为空。
- `source_path_missing`：字段覆盖缺少 `source_field_path`，不能投影。
- `not_called`：来源 API 因参数、live probe 或 worker 状态未调用。
- `join_blocked`：字段来自另一个 API，但 P1 无法完成 join。

必填字段出现 `missing`、`source_path_missing`、`not_called` 或 `join_blocked` 时，执行结果不能是 `data_table_ready`，应为 `partial_data_table_ready`、`blocked` 或 `degraded`，并写入 `risks[]`。

## P1 执行流程

`/api/nodes/:id/run` 对 `analysis_node_view.node_kind=data_analysis` 的节点执行以下流程：

1. 从 `upstream_artifacts` 和本地 artifacts 提取 known params。
2. 加载当前字段覆盖计划；若不存在，调用 `api_doc_matcher.service match_business_context` 生成。
3. 校验 `field_coverage_plan[]` 是否具备 `source_api_id + source_field_path`；缺路径的字段不投影，写入字段风险。
4. 按 `field_coverage_plan[].source_api_id` 聚合 API 调用计划。
5. 基于 API asset card 的 request schema 和 `known_params` 构建 `request_param_mapping[]` 与 `params`。
6. required 参数缺失的 API 标记为 blocked；若所有 API 都 blocked，则返回 blocked 并写执行轨迹。
7. 若 `DBA_LIVE_PROBE=1` 且 db-agent worker ready，调用既有 `/api/db-agent/query action=probe_sample`；否则返回 blocked，并写执行轨迹。
8. 将 API response rows 按 `source_field_path` 投影到中文业务字段，并计算每个字段的 `value_status`。
9. 写入原始数据表、空的兼容结论草稿和执行轨迹 artifacts；节点运行不得自动调用 PI。
10. `derived_or_manual_required` 字段保持 `not_called/needs_evidence`，等待用户从单元格操作条加入右侧 Agent 对话。
11. 用户点击分析问题文字链接后，右侧 Agent 才按当前表格 revision 生成结论提案。

`probe_sample` 复用现有 db-agent 行为，不另起一套取数 worker：

- worker 白名单已有 `probe_sample`，P1 执行器通过 `/api/db-agent/query` 调用。
- 当 `api_id` 缺失时，兼容现有服务端兜底：先运行 `tool_plan` 并取第一个来源 API；但数据分析执行器优先传入已确认的 `source_api_id`。
- 当 `DBA_LIVE_PROBE != 1` 时，现有 worker 返回 `live_probe_disabled`，服务端映射为 `status=blocked`；执行器应引用该 blocked 结果，不生成假数据。
- 当 `workerResponse.ok` 时，沿用现有 `persistDbAgentArtifact` 落盘结果；`data_analysis_execution` 通过 evidence/artifact ref 引用该结果，不重复写一份 probe artifact。

多 API join 的 P1 默认策略：

- P1 默认只支持“独立取数”：每个 API 都能从当前 `known_params` 直接绑定 required params。
- 调用顺序使用确定性串行顺序，先主 API，再按覆盖必填字段数和 API id 排序，便于 trace 和复现。
- 主 API 选择覆盖必填字段最多、且返回行最多的 API。
- 只有所有参与 API 都返回共同 key 时才尝试轻量合并；优先使用 `product_id`、`item_id`、`goods_id`、`product_url`、`rank`。
- 某个 API 需要另一个 API 的输出作为入参时，标记 `dependency_required`，不在 P1 执行。
- 无共同 key 时不合并数据，不填假值；相关字段标记 `join_blocked`。

## PI Agent P1 intents

右侧统一协作主流程使用：

- `table_edit_advice`：用户发送带 `cell_context` 的问题后，输出待显式回填的单元格 patch。
- `insight_collaboration`：用户点击分析问题或继续追问后，输出按 `requirement_id` 保存的结论提案。
- `free_chat`：不带单元格或分析要求时，基于当前表格进行自由问答。

以下旧 intents 保持接口兼容，但不再由 `/api/nodes/:id/run` 自动调用：

- `derived_field_fill`：输入数据表草稿、派生字段列表、字段证据，输出 `derived_cell_values[]`、证据字段、风险。
- `insight_draft`：输入数据表草稿、分析结论要求、字段证据，输出结论草稿、证据引用、风险和待确认问题。

PI 输出边界：

- 不写 `confirmed`。
- 无证据时不生成事实值，只生成填充方案或问题。
- 派生字段草稿值必须带 `source_kind=pi_derived` 和 evidence refs。
- 节点取数结束不触发 PI；只有用户显式发送右侧对话才产生模型调用。

建议批量参数：

- `PI_DERIVED_BATCH_SIZE=20`
- `PI_DERIVED_MAX_ROWS=300`

## Preview 与 PI 配置

`app preview start` 必须把仓库根 `.env` 注入生成应用进程，而不是读取 `runs/<run_id>/.env`。否则 `AICODEMIRROR_API_KEY` 已在仓库根配置时，生成应用仍会显示 `aicodemirror/gpt-5.6-sol` 未配置。

P1 要求：

- `app preview start` 增加或修正 `--repo-root`，默认当前仓库根目录。
- preview env 白名单包含 `AICODEMIRROR_API_KEY`、`AICODEMIRROR_KEY`、`AICODEMIRROR_BASE_URL`、`DEEPSEEK_API_KEY`、`PI_BIN`、`PI_MODEL`、`PI_DEFAULT_MODEL`、`DB_ARCHAEOLOGIST_SPEC_PACK`、`DBA_LIVE_PROBE`。
- `/api/pi-agent/status` 区分：
  - `pi_binary_not_found`
  - `model_key_not_configured`
  - `ready`
- 默认模型为 `aicodemirror/gpt-5.6-sol`。`deepseek/deepseek-v4-pro` 仅作为用户显式切换选项，不允许在调用失败后静默降级。

## 中间工作区渲染要求

前端应按以下顺序渲染数据分析节点：

1. `purpose_model` -> 节点目标。
2. `input_model` -> 输入准备。
3. `data_output_model.fields` + 字段覆盖合同 -> 字段覆盖。
4. `execution_plan.steps` -> 执行动作。
5. 运行工具条 + `data-table-workspace-v1` -> 唯一可编辑数据表。
6. 折叠工程证据 -> 类目解析、API 调用、详情补全、逐字段状态和风险。

渲染约束：

- 字段名优先显示业务中文名。
- 右侧 Agent 不渲染真实取数或 API 匹配主流程按钮。
- 长 API ID、字段路径、Agent 回复必须换行或在局部滚动。
- 中间工作区不得重复渲染数据表，也不得设置独立分析结论块。
- 单元格操作条固定在唯一表格下方；所有单元格都允许人工保存、恢复来源或加入 Agent 对话。
- `insight_output_model.requirements` 在右侧渲染为文字链接，不使用 tab 或 select。

## 统一协作 Thread

数据分析节点使用 `analysis-collaboration-thread-v1` 作为右侧对话事实源：

```json
{
  "schema_version": "analysis-collaboration-thread-v1",
  "node_id": "collect_top_products",
  "revision": 3,
  "preferred_model": "aicodemirror/gpt-5.6-sol",
  "agent_calls": [],
  "active_context_message_id": "context-xxx",
  "active_requirement_id": "insight_2",
  "messages": []
}
```

- 保存至 `artifacts/<node_id>.agent_thread.json`，审计保存至 `evidence/<node_id>.agent_thread_history.json`。
- 最多持久化 200 条消息；发送给 PI 时只取最近 20 条，并附加当前经过校验的单元格或分析要求上下文。
- PI 表格上下文由服务端从 `data-table-workspace-v1` 计算：使用 API 原值与人工/已应用提案合并后的 effective rows，并在每行注入 `row_meta` 对应的稳定 `row_id`。`table_edit_advice` 只发送选中 `row_id` 对应的行、行元数据和覆盖层；`insight_collaboration` 与 `free_chat` 最多发送 100 行。不得直接发送无身份的原始 API 行，也不得把数组下标当作证据 ID。
- 超过 100 行时只发送截断后的有效行和确定性字段统计，并在 evidence summary 标记 `evidence_truncated`；PI 返回的表格 patch 与结论 evidence binding 必须引用已发送且仍存在于当前 revision 的 `row_id + field_path`。
- `cell_context` 由服务端从 `data-table-workspace-v1` 重建，前端不得提交 API 凭据、完整请求 URL 或无关行。
- `agent-thread/query` 只写用户消息和待处理 Agent 提案，不直接修改表格或确认结论。
- `agent-thread/action` 委托既有表格 patch 和 insight patch/confirm 合同；表格 revision 变化时旧提案返回 `409 revision_conflict`。
- 分析问题共享节点级时间线，但草稿和确认状态继续按稳定 `requirement_id` 存储在 `insight-collaboration-v1`。
- 新版 thread 不写入或迁移旧 localStorage 对话。
- `preferred_model` 是节点 thread 的持久化首选模型；每次调用分别记录 `requested_model`、PI runtime 明确报告的 `actual_model` 和 `matched|substituted|unknown`。没有 runtime 证据时不得把请求模型展示成实际模型。
- `agent_calls[]` 保存脱敏 `context_snapshot`、公开阶段时间线、首段内容时间、耗时、失败原因和未完成输出。单元格快照必须包含实际提交的目标商品、字段、API 原值和材质/场景/主卖点等相关证据，不得包含凭据、Header、完整内部 URL、无关行或原始全量响应。
- 新版前端以异步 query 创建 `call_id`，再通过 `GET /api/nodes/:node_id/agent-thread/calls/:call_id/events` 的 SSE 观察阶段。`thinking_*` 事件只能归一成“Agent 正在分析证据”，不得保存或展示隐藏思维文本。
- PI 使用单次 `pi --mode rpc --no-session` 流调用：写入 prompt 后必须保持 stdin 打开，直到收到 `agent_end`；`response success` 只表示请求已受理，不能作为完成信号。
- 右侧协作 PI 显式使用 `--no-tools --no-skills --no-context-files --no-prompt-templates --no-extensions`，只允许返回建议合同，不能通过工具绕过工作区 patch/confirm 边界。
- 退出码为 0 但没有 assistant 正文时返回 `degraded/pi_empty_response`；正文存在但缺少 `agent_end` 时返回 `degraded/pi_incomplete_response`，不得把确定性 fallback 标记为 Agent 成功。
- 协作超时默认值：`table_edit_advice/free_chat=120s`，`insight_collaboration=180s`；`PI_RPC_TIMEOUT_MS` 可统一覆盖。超时、空响应、不完整响应和无效结构只生成失败卡片，不生成可应用 proposal，不自动切换模型。

## 运行时状态

### 当前页 Agent 批量填充

数据表工作区固定使用 10 行一页。`POST /api/nodes/:node_id/agent-thread/batches` 只接受 `base_revision`、`page_number` 和 `page_size=10`，服务端重新从当前 `data-table-workspace-v1` 计算这一页的 `row_id`、空值目标字段和证据，不信任前端上传的任意商品行。

批次产物使用 `analysis-agent-batch-v1`，保存至 `artifacts/<node_id>.agent_batch.<batch_id>.json`，线程只保留最近 20 个摘要。每个商品只创建一个 `table_edit_advice` 子调用，包含该行全部待补字段，最大并发 2；子调用超时 120 秒，批次总上限 10 分钟。批次只生成待审核 `proposals[]`，不直接修改表格，不自动重试，也不自动切换模型。

执行状态通过 `GET /api/nodes/:node_id/agent-thread/batches/:batch_id/events` 发布公开阶段和计数：正在校验当前页、正在构造商品证据、正在处理商品、正在聚合结构化建议、等待用户复核。PI 隐藏思维事件只转换为公开阶段，不保存或展示原文。

复核通过 `POST .../batches/:batch_id/apply` 一次原子写入所选 proposal。请求必须带当前 `base_revision`；每个 patch 必须属于批次页、目标字段、原值为空且当前值仍等于 `expected_value`。成功后覆盖层记录 `source_kind=pi_derived`、批次 ID、proposal ID、模型、理由、置信度和证据；冲突返回 `409 revision_conflict`，任何所选建议都不写入。

### 右侧固定监视器与滚动契约

右侧 Agent 分为固定执行监视器和独立滚动聊天区。批次/SSE/计时器只能局部更新 `[data-agent-execution-monitor]`，不能因每秒计时重建整个右栏。全局重绘前保存聊天 `scrollTop`、是否接近底部、输入值和焦点；用户查看历史消息时保持位置并显示“有新结果”，只有用户发送消息或原本在底部时才滚动到底部。

建议状态枚举：

- `not_started`
- `input_ready`
- `field_mapping_suggested`
- `field_mapping_reviewed`
- `data_table_ready`
- `data_table_blocked`
- `partial_data_table_ready`
- `insight_draft_ready`
- `insight_confirmed`
- `blocked`
- `degraded`

状态转换原则：

- 字段映射建议不自动变成 reviewed。
- 数据表未生成时，结论只能是分析方案或草稿。
- 结论草稿必须经人工确认才能进入 confirmed。
- 外部工具不可用时，节点应 degraded，而不是阻断基础应用浏览。

## Source Trace

## 流程3专用执行合同

`analyze_hot_product_genes` 不走通用 `node.kind=llm` 的 `mock_llm` 分支。专用执行器先校验 `artifacts/collect_top_products.confirmed_data_table.json` 和对应 confirmation revision，再以最多2个并发的单商品 PI 调用生成规范化及派生草稿。每个请求只包含一个商品，模型默认 `aicodemirror/gpt-5.6-sol`；失败商品不阻断其它画像。

主产物为 `hot-product-gene-analysis-v1`，包含 `product_profiles`、`dimension_findings`、`gene_groups`、`coverage`、`progress`、`risks` 和未确认状态。事实值与规范化值分开存储，每个维度保留 `raw_value / normalized_tags / source_status / confidence / evidence_fields`。

服务端负责确定性分组、占比和规则调用。`shells/report_generator/engine/rules.py` 是唯一规则事实源，`rule_engine.py` 仅保留 CLI facade。规则输入缺失时生成 unavailable signal；TOP50信号要求 `sample_size >= 50`；支付买家数区间和交易指数不能作为正式比例输入。

接口：

```text
POST /api/nodes/analyze_hot_product_genes/run
GET  /api/nodes/analyze_hot_product_genes/gene-analysis
GET  /api/nodes/analyze_hot_product_genes/gene-analysis/:execution_id/events
POST /api/nodes/analyze_hot_product_genes/gene-analysis/:execution_id/retry
POST /api/nodes/analyze_hot_product_genes/gene-analysis/:execution_id/cancel
POST /api/nodes/analyze_hot_product_genes/gene-analysis/:execution_id/confirm
```

运行请求返回 `202 + execution_id`。进度和中间结果原子写入 artifact，并通过 SSE 发布公开阶段；刷新后 GET 接口恢复当前状态。确认请求必须携带 execution ID 和 source revision，成功后写入 `hot-product-gene-analysis-confirmed-v1`。上游 revision 不一致时 GET 返回 stale 视图，不能继续作为下游事实。

`source_trace` 至少应包含：

```json
{
  "business_doc_refs": ["source_docs/20260519市场分析洞察元策略.md#流程2"],
  "strategy_kb_refs": [],
  "workflow_ref": "skill_snapshot/workflow.dag.yaml",
  "data_requirement_refs": ["skill_snapshot/data_requirements.yaml#category_top_products_300"],
  "output_schema_refs": ["skill_snapshot/output_schemas/top_300_product_analysis_table.json"],
  "api_doc_index_ref": "data/api_doc_index.json"
}
```

所有从业务文档转译出的目标、数据来源、动作、字段和结论要求，都必须能追溯到上述来源之一。

`api_doc_index_ref` 是运行期解析路径，非固定单一文件：服务端按 `data/api_doc_index.json` 与 `data_capability/api_doc_index.json` 二选一探测（见 `shells/report_generator/server/server.js`），且该索引是生成应用的运行期产物，仓库源码树中默认不存在。`source_trace` 记录时应写实际命中的路径，不应硬编码为 `data/api_doc_index.json`。

## 验收要求

### 关键词分析运行合同

关键词分析复用 `business-category-context-v1`。流程2完成类目验证后写入请求名称、标准名称、类目 ID、确认别名、来源节点 revision 和 evidence ref；关键词节点在字段匹配前加载该合同，并按“标准名称、原始名称、确认别名”依次调用接受 `tertiary_category` 的 API。只有请求无法发出才是 `blocked`；请求成功但全部候选返回零行必须返回 `empty_data`，同时保留每次类目参数、API、行数和脱敏请求证据。

关键词明细使用规范化关键词做跨 API `key_join`。`keyword/keywords`、`search_popularity`、`search_growth_rate`、`competition_index`、`click_rate`、`conversion_rate/pay_rate` 是 API 事实字段；`root_terms` 和 `demand_type` 是受保护的语义字段，只能保存为 PI/确定性派生草稿并等待人工确认，任何把它们映射到点击率等数值指标的覆盖方案都必须在 matcher 和 server 两层拒绝。

节点同时生成 `keyword_demand_breakdown_table` 和 `keyword-root-top20-v1`。当 API 明细已经存在但词根或需求分类未完成时，节点状态为 `agent_enrichment_pending`；词根 TOP20 草稿不得把缺失值当作零或生成伪造标签。

生成验收：

- 数据分析节点包含 `analysis_node_view.schema_version=analysis-node-view-v1`。
- 流程2节点能生成目的、数据来源、执行动作、全部表格字段（当前 17 个，数量以 `output_field_requirements` 为准）和分析结论要求。
- `data_output_model.fields` 与 `output_field_requirements` 数量一致。
- 中文字段名和字段说明未丢失。

交互验收：

- 中间工作区按“节点目标、输入准备、字段覆盖、执行动作、运行工具条、唯一数据表、工程证据”展示。
- 字段覆盖调用 `api_doc_matcher`，前端不实现独立匹配算法。
- 页面只出现一张 TOP N 表格，刷新后从 `data-table-workspace-v1` 恢复。
- 右侧 Agent 使用单一服务端 thread；分析要求以文字链接展示。
- PI 请求包含最多 100 行带稳定 `row_id` 的当前有效数据；单元格建议和结论证据不能引用未知行或未知字段。
- 右侧 Agent 建议可在聊天内显式回填到单元格或保存为结论草稿，但不能自动确认事实。

安全验收：

- 未确认字段映射不得写为节点事实。
- 未引用证据的分析结论不得写为 confirmed。
- 默认不进行真实数仓 live probe。
- 不保存或展示 secret、cookie、数据库连接串或完整环境变量。

## 后续实现切片建议

P0：

- 在生成阶段构建 `analysis_node_view`。
- 中间工作区按五段渲染数据分析节点。
- 流程2完成字段覆盖和分析结论要求展示。

P1：

- 数据分析节点执行器。
- 显式 live probe 后生成数据表草稿。
- 派生字段草稿填充。
- 结论草稿生成与证据引用。
- 修复 preview env 注入，确保 AICodeMirror GPT-5.6 Sol 配置可被生成应用识别。

P2：

- 多 API join 与真实数据合并。
- 结论确认后的下游节点事实传播。

## 与实施计划关系

- [`app_generation_data_analysis_node_spec.md`](app_generation_data_analysis_node_spec.md) 定义产品/交互范式，说明业务文档 `目的 / 数据来源 / 执行动作 / 表格字段 / 分析结论` 如何映射到中间工作区。
- 本文档定义 `analysis_node_view`、生成链路、字段覆盖、分析结论、事实边界和服务边界。
- [`app_generation_data_analysis_node_implementation_plan.md`](app_generation_data_analysis_node_implementation_plan.md) 定义具体实施顺序、历史逻辑退场范围、修改文件清单、测试命令和应用端验收步骤。
