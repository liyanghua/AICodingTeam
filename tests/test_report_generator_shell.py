from __future__ import annotations

import json
import unittest
from pathlib import Path


class ReportGeneratorShellTests(unittest.TestCase):
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
        ]:
            self.assertIn(field, node_properties)
        tool_mode = schema["properties"]["tool_bindings"]["items"]["properties"]["effective_mode"]
        self.assertEqual(tool_mode["const"], "manual_upload_only")
        app_js = (root / "web" / "app.js").read_text(encoding="utf-8")
        for label in ["分析目标", "执行动作", "用户填写区", "验证标准", "中间产物", "保存并生成产物", "字段", "填写内容", "填写要求", "输入", "依赖数据", "产物", "Schema", "Evidence", "Tool", "业务上下文", "Source Trace"]:
            self.assertIn(label, app_js)
        for label in ["缺口助手", "待处理字段", "派生字段", "生成派生字段填充方案"]:
            self.assertIn(label, app_js)
        for label in ["字段覆盖工作台", "覆盖状态", "来源 API", "API 字段", "候选字段", "一键生成字段覆盖方案", "批量确认高置信字段", "确认映射合同", "应用高置信建议 ≥0.9", "PI 建议"]:
            self.assertIn(label, app_js)
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
        for label in ["派生字段分析", "派生/人工", "derived_field_analysis", "source_kind"]:
            self.assertIn(label, app_js)
        for label in ["PI runtime", "requires_human_confirmation", "field_advice", "pi-data-mapping-advice-v1"]:
            self.assertIn(label, app_js)
        self.assertIn("function buildNodeDraftArtifact", app_js)
        self.assertIn("function renderDraftArtifactTable", app_js)
        self.assertIn("function isDataMappingNode", app_js)
        self.assertIn("function renderOutputFieldMappingWorkbench", app_js)
        self.assertIn("function saveFieldMappingDraft", app_js)
        self.assertIn("function confirmFieldMappingContract", app_js)
        self.assertIn("function fetchPiAgentStatus", app_js)
        self.assertIn("function queryPiAgent", app_js)
        self.assertIn("function queryDbAgent", app_js)
        self.assertIn("function renderFieldMapResult", app_js)
        self.assertIn("function renderDataMappingContract", app_js)
        self.assertIn("function contractFromDbAgentResult", app_js)
        self.assertIn("function rememberDbAgentEvidence", app_js)
        self.assertIn("function workbenchStorageKey", app_js)
        self.assertIn("function loadWorkbenchState", app_js)
        self.assertIn("function saveWorkbenchState", app_js)
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
        self.assertIn("function applyHighConfidenceAdvice", app_js)
        self.assertIn("function applyAdviceAction", app_js)
        self.assertIn("function renderGapAgentPanel", app_js)
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
        self.assertNotIn("selected_api_asset_cards", app_js)
        self.assertIn("output_field_requirements", app_js)
        self.assertIn("save_field_mapping", app_js)
        self.assertIn("confirm_mapping", app_js)
        self.assertIn("data_mapping_contract", app_js)
        self.assertIn("MARKET_SCOPE_FIELD_FALLBACKS", app_js)
        self.assertIn("function nodeActionFields", app_js)
        self.assertIn("function upstreamArtifactsFor", app_js)
        self.assertIn("function buildNodeRunPayload", app_js)
        self.assertIn("completeNodeRun", app_js)
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

        css = (root / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("minmax(0, 1fr)", css)
        self.assertIn(".layout > .panel:nth-child(3)", css)
        self.assertIn("max-height: calc(100vh - 96px)", css)
        self.assertIn("overflow-x: auto", css)
        self.assertIn("@media (max-width: 1180px)", css)
        self.assertIn(".artifact-table", css)
        self.assertIn(".save-status.done", css)
        self.assertIn(".upstream-artifact", css)

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
