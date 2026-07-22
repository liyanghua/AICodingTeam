from __future__ import annotations

import json
import unittest
from pathlib import Path


class ReportGeneratorShellTests(unittest.TestCase):
    def test_hot_product_gene_node_has_dedicated_observable_workspace(self) -> None:
        app_js = Path("shells/report_generator/web/app.js").read_text(encoding="utf-8")

        for marker in [
            "function isHotProductGeneNode",
            "function renderHotProductGeneWorkspace",
            "爆款基因执行监视器",
            "逐商品九维画像",
            "聚合爆款基因组合",
            "确认爆款基因并进入下一步",
            "gene-analysis",
            "gene_analysis_update",
            "hot-product-gene-analysis-confirmed-v1",
        ]:
            self.assertIn(marker, app_js)
        renderer = app_js.split("function renderHotProductGeneWorkspace", 1)[1].split("function renderBusinessContext", 1)[0]
        self.assertNotIn("LLM processing not yet implemented", renderer)
        self.assertIn("source_status", renderer)
        self.assertIn("matched_count", renderer)
        self.assertIn("geneRunErrorMessage", renderer)
        self.assertIn("source_table_not_confirmed", app_js)
        self.assertIn("请先在流程2确认 TOP N 商品表", app_js)

    def test_hot_product_gene_workspace_exposes_nine_dimensions_and_signal_availability(self) -> None:
        app_js = Path("shells/report_generator/web/app.js").read_text(encoding="utf-8")
        for dimension in ["产品类型", "材质", "功能", "风格", "人群", "场景", "价格带", "视觉表达", "流量入口"]:
            self.assertIn(dimension, app_js)
        for status in ["matched", "not_matched", "unavailable", "insufficient_sample"]:
            self.assertIn(status, app_js)

    def test_hot_product_gene_routes_extract_execution_id_before_operation(self) -> None:
        server_js = Path("shells/report_generator/server/server.js").read_text(encoding="utf-8")
        api_handler = server_js.split("async function handleGeneAnalysisApi", 1)[1].split("async function handleCollaborationApi", 1)[0]
        sse_handler = server_js.split("function handleGeneAnalysisSse", 1)[1].split("function serveStatic", 1)[0]
        self.assertGreaterEqual(api_handler.count("pathname.split('/')[5]"), 2)
        self.assertIn("parts[5]", sse_handler)
        self.assertNotIn("parts[6]", sse_handler)

    def test_agent_progress_uses_local_monitor_updates_and_preserves_manual_scroll(self) -> None:
        app_js = Path("shells/report_generator/web/app.js").read_text(encoding="utf-8")

        timer = app_js.split("function observeAgentCall(nodeId, callId)", 1)[1].split(
            "async function retryAgentCall", 1
        )[0]
        self.assertIn("patchAgentExecutionMonitor(nodeId)", timer)
        self.assertNotIn("state.piAgentBusy[nodeId]) render()", timer)
        self.assertNotIn("agentThread.scrollTop = agentThread.scrollHeight", app_js)
        for helper in [
            "captureAgentInteractionState",
            "restoreAgentInteractionState",
            "agentThreadNearBottom",
            "data-agent-new-results",
        ]:
            self.assertIn(helper, app_js)

    def test_editable_table_and_right_agent_expose_current_page_batch_review(self) -> None:
        app_js = Path("shells/report_generator/web/app.js").read_text(encoding="utf-8")
        for label in [
            "当前页一键填充",
            "当前页批量填充",
            "进入一键复核",
            "应用所选建议",
            "选择当前全部可应用建议",
            "已生成建议",
        ]:
            self.assertIn(label, app_js)
        for contract in [
            "analysis-agent-batch-v1",
            "/agent-thread/batches",
            "agent_batch_update",
            "data-agent-batch-review",
        ]:
            self.assertIn(contract, app_js)

        review_renderer = app_js.split("function renderAgentBatchReview(nodeId)", 1)[1].split(
            "function renderAgentBatchMonitorArea", 1
        )[0]
        self.assertIn('data-agent-batch-review-panel=', review_renderer)
        self.assertNotIn('<section class="agent-batch-review" data-agent-batch-review=', review_renderer)

    def test_confirmed_data_table_advances_with_effective_workspace_artifact(self) -> None:
        app_js = Path("shells/report_generator/web/app.js").read_text(encoding="utf-8")

        self.assertIn("确认当前表格并进入下一步", app_js)
        self.assertIn("/data-table-workspace/confirm", app_js)
        confirmation = app_js.split("async function confirmDataTableAndAdvance", 1)[1].split(
            "async function startAgentBatch", 1
        )[0]
        self.assertIn("rememberNodeArtifact(node.id, response.artifact)", confirmation)
        self.assertIn("state.nodeStatus[node.id] = 'done'", confirmation)
        self.assertIn("advanceToNextNode(node.id)", confirmation)
        self.assertIn("refreshConfirmedUpstreamArtifacts", app_js)

        artifact_renderer = app_js.split("function renderArtifactRowsTable(artifact)", 1)[1].split(
            "function renderDraftArtifactTable", 1
        )[0]
        self.assertIn("data-table-confirmed-v1", artifact_renderer)
        self.assertIn("artifact.fields", artifact_renderer)
        self.assertIn("renderPreviewCell", artifact_renderer)

    def test_top_products_node_submits_selected_top_n_preset(self) -> None:
        app_js = Path("shells/report_generator/web/app.js").read_text(encoding="utf-8")

        for value in ["10", "20", "30", "50"]:
            self.assertIn(f'<option value="{value}"', app_js)
        self.assertIn("TOP N", app_js)
        self.assertIn("data-analysis-top-n", app_js)
        self.assertIn("dataAnalysisTopN: {}", app_js)
        payload_builder = app_js.split("function buildNodeRunPayload(node, draft)", 1)[1].split(
            "function isCompletedResult", 1
        )[0]
        self.assertIn("payload.top_n = selectedDataAnalysisTopN(node.id)", payload_builder)
        self.assertIn("? value : 20", app_js.split("function selectedDataAnalysisTopN", 1)[1].split("function", 1)[0])

    def test_node_selection_waits_for_collaboration_workspace_before_render(self) -> None:
        app_js = Path("shells/report_generator/web/app.js").read_text(encoding="utf-8")
        bind_events = app_js.split("function bindEvents()", 1)[1].split("const runButton", 1)[0]

        self.assertIn("button.addEventListener('click', async () => {", bind_events)
        self.assertIn(
            "await refreshCollaborationWorkspaces(state.selectedNodeId, { render: false });",
            bind_events,
        )
        self.assertLess(
            bind_events.index("await refreshCollaborationWorkspaces"),
            bind_events.index("render();"),
        )

    def test_editable_table_uses_business_field_name_as_row_key(self) -> None:
        app_js = Path("shells/report_generator/web/app.js").read_text(encoding="utf-8")
        helper = app_js.split("function collaborationFieldPath(field)", 1)[1].split(
            "function tableCellKey", 1
        )[0]

        self.assertIn("field?.field_name || field?.title || field?.field_path", helper)

    def test_analysis_workspace_renders_one_persisted_table_after_page_reload(self) -> None:
        app_js = Path("shells/report_generator/web/app.js").read_text(encoding="utf-8")
        workspace_renderer = app_js.split("function renderDataAnalysisTableSection(node)", 1)[1].split(
            "function renderDataAnalysisNodeWorkspace", 1
        )[0]

        self.assertIn("const workspacePayload = state.dataTableWorkspaces[node.id]", workspace_renderer)
        self.assertIn("renderEditableDataTableWorkspace(node.id, workspacePayload)", workspace_renderer)
        self.assertEqual(workspace_renderer.count("renderEditableDataTableWorkspace(node.id, workspacePayload)"), 1)

    def test_data_analysis_ui_uses_unified_agent_thread_and_no_duplicate_outputs(self) -> None:
        app_js = Path("shells/report_generator/web/app.js").read_text(encoding="utf-8")
        analysis_detail = app_js.split("if (isDataAnalysisNode(node)) {", 1)[1].split("  return `", 1)[0]
        agent_renderer = app_js.split("function renderAnalysisCollaborationAgent(node)", 1)[1].split(
            "function renderAgentPanel", 1
        )[0]

        for removed in ["输出结果", "数据表产物", "节点运行输出"]:
            self.assertNotIn(removed, analysis_detail)
        self.assertNotIn("data-agent-mode", agent_renderer)
        self.assertNotIn("data-agent-insight-select", agent_renderer)
        self.assertIn("data-agent-insight-question", agent_renderer)
        self.assertIn("data-agent-thread-input", agent_renderer)
        self.assertIn("data-agent-proposal-apply", app_js)
        self.assertIn("加入 Agent 对话", app_js)
        self.assertIn("analysis-collaboration-thread-v1", app_js)

    def test_shell_layout_and_schema_define_app_config_contract(self) -> None:
        root = Path("shells/report_generator")
        schema_path = root / "contract.schema.json"

        self.assertTrue((root / "server").is_dir())
        self.assertTrue((root / "web").is_dir())
        self.assertTrue((root / "engine").is_dir())
        self.assertTrue((root / "README.md").is_file())
        self.assertTrue((root / "version.txt").is_file())
        self.assertTrue(schema_path.is_file())

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["schema_version"]["const"], "app-config-v1")
        self.assertEqual(schema["properties"]["shell_kind"]["enum"], ["report_generator"])
        node_kind = schema["properties"]["nodes"]["items"]["properties"]["kind"]
        self.assertEqual(node_kind["enum"], ["form", "data", "compute", "llm", "aggregate"])
        node_properties = schema["properties"]["nodes"]["items"]["properties"]
        for field in [
            "input_model",
            "output_model",
            "execution_model",
            "evidence_model",
            "tool_model",
            "source_trace",
            "business_context",
            "node_execution_view",
            "analysis_node_view",
        ]:
            self.assertIn(field, node_properties)
        tool_mode = schema["properties"]["tool_bindings"]["items"]["properties"]["effective_mode"]
        self.assertEqual(tool_mode["const"], "manual_upload_only")
        app_js = (root / "web" / "app.js").read_text(encoding="utf-8")
        for label in ["节点目标", "输入准备", "字段覆盖", "执行动作", "保存并生成产物", "字段", "填写内容", "填写要求", "输入", "依赖数据", "产物", "Schema", "Evidence", "Tool", "业务上下文", "Source Trace"]:
            self.assertIn(label, app_js)
        for label in ["分析协作 Agent", "业务分析问题", "加入 Agent 对话", "回填此单元格", "保存为结论草稿", "确认此结论"]:
            self.assertIn(label, app_js)
        self.assertNotIn("<h3>缺口助手</h3>", app_js)
        for label in ["字段覆盖工作台", "覆盖状态", "来源 API", "API 字段", "候选字段", "一键生成字段覆盖方案", "PI 建议"]:
            self.assertIn(label, app_js)
        for removed_label in ["派生字段分析", "生成派生字段填充方案", "批量确认高置信字段", "确认映射合同", "审核后确认合同", "RunAgent 通道已预留", "应用高置信建议 ≥0.9"]:
            self.assertNotIn(removed_label, app_js)
        self.assertNotIn('data-workbench-action="derived-analysis"', app_js)
        self.assertNotIn('data-workbench-action="confirm-high-confidence"', app_js)
        self.assertNotIn('id="confirm-field-mapping-contract"', app_js)
        for label in ["浏览返回字段", "筛选 API 返回字段", "应用选中字段", "mapping_correction", "conversation_history", "target_field", "agentThreads"]:
            self.assertIn(label, app_js)
        self.assertNotIn("collaborationThreads", app_js)
        self.assertNotIn("一键生成字段覆盖方案 / 智能匹配字段（PI 增强）", app_js)
        self.assertNotIn("function renderWorkbenchApiPlanning", app_js)
        self.assertNotIn("API 覆盖计划", app_js)
        self.assertNotIn("推荐候选 API", app_js)
        workbench_body = app_js.split("function renderOutputFieldMappingWorkbench(node)", 1)[1].split("function renderEvidenceModel(node)", 1)[0]
        self.assertIn("直接自动选择 API 并填充字段", workbench_body)
        self.assertNotIn("高级：多 API 合并口径", app_js)
        self.assertNotIn("data-join-plan-field", app_js)
        for removed_label in ["1. 理解业务输入", "2. 映射数仓 API", "加入覆盖计划 / 查看返回字段", "映射到字段", "回填到中间表格"]:
            self.assertNotIn(removed_label, app_js)
        for label in ["派生/人工", "source_kind"]:
            self.assertIn(label, app_js)
        for label in ["PI runtime", "requires_human_confirmation", "field_advice", "pi-data-mapping-advice-v1"]:
            self.assertIn(label, app_js)
        for label in ["首选模型", "请求模型", "实际模型", "aicodemirror/gpt-5.6-sol", "deepseek/deepseek-v4-pro", "function selectedPiModel", "data-pi-model-select"]:
            self.assertIn(label, app_js)
        for label in ["本次提交内容", "执行阶段", "重试当前模型", "切换模型后重试", "继续人工填写"]:
            self.assertIn(label, app_js)
        self.assertIn("new EventSource", app_js)
        self.assertIn("/agent-thread/calls/", app_js)
        self.assertIn("/events", app_js)
        self.assertNotIn("PI 未返回有效内容，已用确定性规则兜底。", app_js)
        server_js = (root / "server" / "server.js").read_text(encoding="utf-8")
        self.assertIn("text/event-stream", server_js)
        self.assertIn("agent_call_update", server_js)
        self.assertIn("handleAgentCallSse", server_js)
        for label in ["请求参数绑定", "取值状态", "value_status", "request_param_mapping", "api_execution_plan", "data-analysis-execution-v1"]:
            self.assertIn(label, app_js)
        for label in ["标准类目", "类目证据", "范围校验", "有效行", "商品 ID 合并", "key_join"]:
            self.assertIn(label, app_js)
        for label in ["执行角色", "数据月份", "月份探测", "selected_data_month", "date_attempts", "缺值"]:
            self.assertIn(label, app_js)
        for label in ["商品详情补全", "计划", "成功", "空结果", "失败", "材质覆盖", "场景覆盖", "pi_derived_unconfirmed"]:
            self.assertIn(label, app_js)
        for label in ["运行时身份注入", "已注入（脱敏）", "主榜单逐行绑定", "运行时数据源校准", "最近可用快照", "月份不可验证"]:
            self.assertIn(label, app_js)
        self.assertIn("function renderCategoryResolutionSummary", app_js)
        self.assertIn("function renderKeywordCategoryAttempts", app_js)
        self.assertIn("关键词类目取数", app_js)
        self.assertIn("empty_data", app_js)
        self.assertIn("规范化关键词", app_js)
        self.assertIn("function renderProductDetailEnrichmentSummary", app_js)
        self.assertNotIn("多个 API 按行号对齐", app_js)
        for label in ["TOP N 可编辑数据表", "可编辑数据表", "请求 URL", "请求 query", "data-table-workspace-page"]:
            self.assertIn(label, app_js)
        for label in ["类目解析", "解析 API", "字段路径", "function isImagePreviewField", "function renderPreviewCell"]:
            self.assertIn(label, app_js)
        self.assertNotIn("字段来源", app_js)
        self.assertIn("product-thumb", app_js)
        for fn in [
            "function isDataAnalysisNode",
            "function analysisNodeViewFor",
            "function renderDataAnalysisNodeWorkspace",
            "function renderAnalysisPurpose",
            "function renderAnalysisInputReadiness",
            "function renderAnalysisFieldCoverage",
            "function renderAnalysisExecutionPlan",
            "function renderDataAnalysisExecutionResult",
            "function renderApiExecutionPlan",
            "function renderValueStatusTable",
            "function renderEditableDataTableWorkspace",
            "function renderAnalysisCollaborationAgent",
        ]:
            self.assertIn(fn, app_js)
        self.assertNotIn("function renderDataTablePreview", app_js)
        self.assertIn("function buildNodeDraftArtifact", app_js)
        self.assertIn("function renderDraftArtifactTable", app_js)
        self.assertIn("function isDataMappingNode", app_js)
        self.assertIn("function renderOutputFieldMappingWorkbench", app_js)
        self.assertIn("function fetchPiAgentStatus", app_js)
        self.assertIn("function queryPiAgent", app_js)
        self.assertIn("function queryDbAgent", app_js)
        self.assertNotIn("function renderFieldMapResult", app_js)
        self.assertNotIn("function renderDataMappingContract", app_js)
        self.assertNotIn("function renderContractCandidateApis", app_js)
        self.assertNotIn("function renderContractRequestParams", app_js)
        self.assertNotIn("function renderContractResponseFields", app_js)
        self.assertNotIn("function renderBusinessInputResult", app_js)
        self.assertNotIn("function renderDbAgentResult", app_js)
        self.assertIn("function contractFromDbAgentResult", app_js)
        self.assertIn("function workbenchStorageKey", app_js)
        self.assertIn("function loadWorkbenchState", app_js)
        self.assertIn("function saveWorkbenchState", app_js)
        self.assertIn("function layoutStorageKey", app_js)
        self.assertIn("function bindLayoutResizers", app_js)
        self.assertIn("data-layout-resizer", app_js)
        self.assertIn("function suggestFieldMappingWithPi", app_js)
        suggest_body = app_js.split("async function suggestFieldMappingWithPi()", 1)[1].split("// 写入或更新单个字段草稿", 1)[0]
        self.assertIn("await queryDbAgent('suggest_multi_api_mapping')", suggest_body)
        self.assertNotIn("await queryPiAgent", suggest_body)
        query_body = app_js.split("async function queryDbAgent(action, options = {})", 1)[1].split("function manualMappingForNode(node)", 1)[0]
        self.assertIn("auto_select_apis", query_body)
        self.assertIn("delete state.fieldMappingDrafts[node.id]", query_body)
        self.assertNotIn("body.field_coverage_plan = currentFieldMappingOverlay(node)", query_body)
        self.assertIn("action === 'suggest_multi_api_mapping' && payload.payload?.field_coverage_plan", query_body)
        self.assertIn("payload.payload?.coverage_summary || payload.data_mapping_contract?.coverage_summary", query_body)
        self.assertIn("payload.payload?.field_coverage_plan", query_body)
        self.assertNotIn("body.selected_apis = selectedApisForNode(node)", query_body)
        self.assertNotIn("body.selected_api_asset_cards = assetCardsForNode(node)", query_body)
        self.assertNotIn("function applyHighConfidenceAdvice", app_js)
        self.assertIn("function applyAdviceAction", app_js)
        self.assertIn("function apiResponseFieldCatalogForNode", app_js)
        self.assertIn("function renderApiFieldBrowser", app_js)
        self.assertIn("function applyApiFieldBrowserSelection", app_js)
        for function_name in ["addSelectedCellToAgent", "sendUnifiedAgentMessage", "actOnAgentThread", "renderUnifiedAgentThread"]:
            self.assertIn(f"function {function_name}", app_js)
        for removed_function in ["sendTableEditAdvice", "sendInsightCollaboration", "applyTableAgentProposal", "patchInsightWorkspace"]:
            self.assertNotIn(f"function {removed_function}", app_js)
        self.assertIn("function renderAnalysisCollaborationAgent", app_js)
        self.assertIn("/agent-thread/query", app_js)
        self.assertIn("字段覆盖工作台", app_js)
        self.assertIn("suggest_multi_api_mapping", app_js)
        self.assertIn("field_coverage_plan", app_js)
        self.assertNotIn("Join / 粒度确认", app_js)
        self.assertNotIn("Join / 粒度计划", app_js)
        self.assertNotIn("function renderApiResponseFields", app_js)
        self.assertNotIn("data-map-api-field", app_js)
        self.assertNotIn("function applyApiFieldMapping", app_js)
        self.assertNotIn("function selectedApiCardsForNode", app_js)
        self.assertNotIn("function assetCardsForNode", app_js)
        self.assertNotIn("function collectJoinPlanDraft", app_js)
        self.assertNotIn("data-select-api", app_js)
        self.assertIn("output_field_requirements", app_js)
        self.assertNotIn("save_field_mapping", app_js)
        self.assertNotIn("confirm_mapping", app_js)
        self.assertIn("data_mapping_contract", app_js)
        self.assertIn("MARKET_SCOPE_FIELD_FALLBACKS", app_js)
        self.assertIn("function nodeActionFields", app_js)
        self.assertIn("function upstreamArtifactsFor", app_js)
        self.assertIn("function buildNodeRunPayload", app_js)
        self.assertIn("completeNodeRun", app_js)
        completed_body = app_js.split("function isCompletedResult(result)", 1)[1].split("function completeNodeRun", 1)[0]
        self.assertIn("partial_data_table_ready", completed_body)
        self.assertIn("advanceToNextNode", app_js)
        self.assertIn("upstream_artifacts", app_js)
        self.assertIn("handleSaveNodeDraft", app_js)
        self.assertIn("browser_manual_form_save", app_js)
        self.assertIn("/run", app_js)
        self.assertIn("function renderMarkdownTable", app_js)
        self.assertIn("</tbody>", app_js)
        self.assertIn("</table>", app_js)
        self.assertIn("renderMarkdown", app_js)
        self.assertNotIn("replace(/<\\/tbody>$/", app_js)

        server_js = (root / "server" / "server.js").read_text(encoding="utf-8")
        self.assertIn("/api/db-agent/status", server_js)
        self.assertIn("/api/db-agent/query", server_js)
        self.assertIn("/api/pi-agent/status", server_js)
        self.assertIn("/api/pi-agent/query", server_js)
        self.assertIn("DB_ARCHAEOLOGIST_SPEC_PACK", server_js)
        self.assertIn("api_doc_index_ready", server_js)
        self.assertIn("derived_field_advice", server_js)
        self.assertIn("api_matching_strategy_results", server_js)
        self.assertIn("DBA_LIVE_PROBE", server_js)
        self.assertIn("match_business_context", server_js)
        for removed in ["localMatchFields", "localSectionMatchForNode", "scoreOutputFieldMatch", "scoreFieldMatch", "localToolPlanPayload"]:
            self.assertNotIn(removed, server_js)
        self.assertIn("submittedArtifact", server_js)
        self.assertIn("upstreamArtifacts", server_js)
        self.assertIn("upstream_artifacts", server_js)
        self.assertIn("artifact_title", server_js)
        self.assertIn("artifact_path", server_js)
        self.assertIn("data-table-workspace", server_js)
        self.assertIn("insight-workspace", server_js)
        self.assertIn("agent-thread", server_js)
        self.assertIn("table_edit_advice", server_js)
        self.assertIn("insight_collaboration", server_js)
        collaboration_js = (root / "server" / "collaboration_store.js").read_text(encoding="utf-8")
        for contract in ["data-table-workspace-v1", "data-table-edit-patch-v1", "insight-collaboration-v1", "analysis-collaboration-thread-v1", "revision_conflict"]:
            self.assertIn(contract, collaboration_js)

        css = (root / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("--left-panel-width", css)
        self.assertIn("--right-panel-width", css)
        self.assertIn("grid-template-columns: var(--left-panel-width", css)
        self.assertIn(".panel-resizer", css)
        self.assertIn("cursor: col-resize", css)
        self.assertIn("touch-action: none", css)
        self.assertIn(".layout > .panel.agent-panel", css)
        self.assertIn("max-height: calc(100vh - 96px)", css)
        self.assertIn("overflow-x: auto", css)
        self.assertIn("overflow-wrap: anywhere", css)
        self.assertIn("word-break: break-word", css)
        self.assertIn("@media (max-width: 1180px)", css)
        self.assertIn(".artifact-table", css)
        self.assertIn(".save-status.done", css)
        self.assertIn(".upstream-artifact", css)
        self.assertIn(".editable-data-table", css)
        self.assertIn(".table-cell-selected", css)
        self.assertIn(".cell-action-bar", css)
        self.assertIn(".agent-insight-link", css)
        self.assertIn(".agent-context-card", css)

        index_html = (root / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('src="app.js?v=', index_html)
        self.assertIn('href="styles.css?v=', index_html)
        server_js = (root / "server" / "server.js").read_text(encoding="utf-8")
        self.assertIn("Cache-Control", server_js)
        self.assertIn("no-store", server_js)

    def test_acceptance_script_requires_api_doc_inputs_for_field_mapping(self) -> None:
        script = Path("scripts/accept_app_generation_cli_baseline.sh").read_text(encoding="utf-8")

        self.assertIn("check_api_doc_inputs", script)
        self.assertIn("API doc index is required for field mapping acceptance", script)
        self.assertIn('run_step "Check API doc matcher inputs"', script)


if __name__ == "__main__":
    unittest.main()
