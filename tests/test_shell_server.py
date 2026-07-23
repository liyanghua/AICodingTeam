"""Tests for report_generator shell server API endpoints."""
import json
import os
import re
import shutil
import shlex
import socket
import subprocess
import tempfile
import time
from pathlib import Path
import unittest
import urllib.request
import urllib.error


def can_bind_localhost() -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
        return True
    except PermissionError:
        return False


CAN_BIND = can_bind_localhost()


@unittest.skipUnless(CAN_BIND, "sandbox forbids socket.bind on 127.0.0.1")
class ShellServerTests(unittest.TestCase):
    """Test report_generator shell server."""

    @classmethod
    def setUpClass(cls):
        """Start shell server with test config."""
        cls.temp_dir = tempfile.mkdtemp()
        cls.app_root = Path(cls.temp_dir)
        cls.config_path = cls.app_root / "app.config.json"
        
        # Create minimal test config
        test_config = {
            "schema_version": "app-config-v1",
            "app_slug": "test-app",
            "shell_kind": "report_generator",
            "shell_version": "0.1.0",
            "skill_ref": {"skill_id": "test_skill"},
            "task_ref": {"task_id": "test_task"},
            "scope_form": {"fields": []},
            "nodes": [
                {
                    "id": "test_node",
                    "name": "Test Node",
                    "kind": "form",
                    "depends_on": [],
                    "outputs": ["test_output"],
                    "state_machine": []
                }
            ],
            "aggregate": {},
            "data_requirements": [],
            "rules": {"hard_requirements": [], "registry": {}},
            "tool_bindings": [],
            "evidence": {"schema": {}},
            "safety": {},
            "customizations": []
        }
        
        cls.config_path.write_text(json.dumps(test_config, indent=2))
        
        # Start server
        server_js = Path(__file__).parent.parent / "shells" / "report_generator" / "server" / "server.js"
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        env = os.environ.copy()
        env.update({"PORT": str(cls.port), "APP_ROOT": str(cls.app_root)})
        cls.process = subprocess.Popen(
            [shutil.which("node") or "/opt/homebrew/bin/node", str(server_js), str(cls.config_path)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        
        # Wait for server to start
        time.sleep(1.5)
        
        cls.base_url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        """Stop shell server."""
        if cls.process:
            cls.process.terminate()
            cls.process.wait(timeout=5)

    def _get(self, path):
        """HTTP GET helper."""
        url = self.base_url + path
        try:
            with urllib.request.urlopen(url) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read()) if e.code < 500 else {"error": str(e)}

    def _post(self, path, payload):
        """HTTP POST helper."""
        url = self.base_url + path
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read()) if e.code < 500 else {"error": str(e)}

    def test_health_endpoint_returns_ok(self):
        """Test /api/health returns server status."""
        status, data = self._get("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["shell_kind"], "report_generator")
        self.assertEqual(data["app_slug"], "test-app")
        self.assertEqual(data["nodes_count"], 1)
        self.assertTrue(data["config_loaded"])

    def test_config_endpoint_returns_full_config(self):
        """Test /api/config returns app.config.json."""
        status, data = self._get("/api/config")
        self.assertEqual(status, 200)
        self.assertEqual(data["schema_version"], "app-config-v1")
        self.assertEqual(data["app_slug"], "test-app")
        self.assertEqual(len(data["nodes"]), 1)

    def test_nodes_endpoint_returns_nodes_list(self):
        """Test /api/nodes returns nodes array."""
        status, data = self._get("/api/nodes")
        self.assertEqual(status, 200)
        self.assertIn("nodes", data)
        self.assertEqual(len(data["nodes"]), 1)
        self.assertEqual(data["nodes"][0]["id"], "test_node")

    def test_node_detail_endpoint_returns_single_node(self):
        """Test /api/nodes/:id returns specific node."""
        status, data = self._get("/api/nodes/test_node")
        self.assertEqual(status, 200)
        self.assertEqual(data["id"], "test_node")
        self.assertEqual(data["kind"], "form")

    def test_node_detail_endpoint_404_for_missing_node(self):
        """Test /api/nodes/:id returns 404 for unknown node."""
        status, data = self._get("/api/nodes/missing_node")
        self.assertEqual(status, 404)
        self.assertEqual(data["error"], "node_not_found")

    def test_node_run_endpoint_accepts_form_input(self):
        """Test /api/nodes/:id/run executes form node."""
        status, data = self._post("/api/nodes/test_node/run", {"inputs": {"field1": "value1"}})
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "done")
        self.assertEqual(data["node_id"], "test_node")
        self.assertEqual(data["kind"], "form")
        self.assertIn("result", data)
        self.assertIn("evidence_ref", data)


class DbAgentApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.app_root = Path(self.temp_dir.name)
        self.config_path = self.app_root / "app.config.json"
        self.direct_runner = self.app_root / "direct_request.js"
        self.config_path.write_text(
            json.dumps(
                {
                    "schema_version": "app-config-v1",
                    "app_slug": "test-app",
                    "shell_kind": "report_generator",
                    "shell_version": "0.1.0",
                    "skill_ref": {"skill_id": "test_skill"},
                    "task_ref": {"task_id": "test_task"},
                    "scope_form": {"fields": []},
                    "nodes": [
                        {
                            "id": "define_scope",
                            "name": "确定分析边界",
                            "kind": "form",
                            "depends_on": [],
                            "outputs": ["market_insight_project_definition"],
                            "state_machine": [],
                        },
                        {
                            "id": "collect_top_products",
                            "name": "行业大盘与热销商品分析",
                            "kind": "data",
                            "depends_on": ["define_scope"],
                            "data_requirements": ["category_top_products_300"],
                            "outputs": ["top_300_product_analysis_table"],
                            "input_model": {
                                "mode": "manual_upload",
                                "required_data": [
                                    {
                                        "id": "category_top_products_300",
                                        "required_fields": [
                                            "rank",
                                            "shop_name",
                                            "product_url",
                                            "product_image",
                                            "sales_or_pay_buyer_count",
                                            "price",
                                            "main_selling_point",
                                        ],
                                    }
                                ],
                                "fields": [],
                            },
                            "output_model": {
                                "outputs": [
                                    {
                                        "id": "top_300_product_analysis_table",
                                        "title": "行业前300商品分析表",
                                        "description": "热销商品排行字段要求",
                                        "schema": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "required": ["rank", "shop_name", "product_url", "price"],
                                                "properties": {
                                                    "rank": {"type": "number", "description": "排名"},
                                                    "shop_name": {"type": "string", "description": "店铺名称"},
                                                    "product_url": {"type": "string", "description": "商品链接"},
                                                    "price": {"type": "number", "description": "商品价格"},
                                                    "main_selling_point": {"type": "string", "description": "主卖点"},
                                                },
                                            },
                                        },
                                        "summary": {"type": "array"},
                                    }
                                ]
                            },
                            "state_machine": [],
                        },
                        {
                            "id": "analyze_hot_product_genes",
                            "name": "爆款基因提炼",
                            "kind": "llm",
                            "depends_on": ["collect_top_products"],
                            "outputs": ["hot_product_gene_table"],
                            "analysis_node_view": {"node_kind": "llm"},
                            "state_machine": [],
                        },
                        {
                            "id": "collect_keywords",
                            "name": "关键词需求分析",
                            "kind": "data",
                            "depends_on": ["define_scope"],
                            "data_requirements": ["category_keywords_top300"],
                            "outputs": ["keyword_demand_breakdown_table", "keyword_root_top20_table"],
                            "input_model": {
                                "mode": "api_collect",
                                "required_data": [
                                    {
                                        "id": "category_keywords_top300",
                                        "required_fields": [
                                            "keyword",
                                            "search_popularity",
                                            "growth_rate",
                                            "competition_index",
                                            "click_rate",
                                            "conversion_rate",
                                            "root_terms",
                                            "demand_type",
                                        ],
                                    }
                                ],
                                "fields": [],
                            },
                            "state_machine": [],
                        },
                    ],
                    "aggregate": {},
                    "data_requirements": [],
                    "rules": {"hard_requirements": [], "registry": {}},
                    "tool_bindings": [],
                    "evidence": {"schema": {}},
                    "safety": {},
                    "customizations": [],
                }
            ),
            encoding="utf-8",
        )
        os.environ["APP_ROOT"] = str(self.app_root)
        os.environ.pop("DB_ARCHAEOLOGIST_SPEC_PACK", None)
        os.environ.pop("DBA_LIVE_PROBE", None)
        self.server_module = self._load_server_module()
        self.function_runner = self.app_root / "function_request.js"
        self.direct_runner.write_text(
            """
const path = require('path');
const EventEmitter = require('events');

const serverPath = process.argv[2];
const route = process.argv[3];
const method = process.argv[4];
const payload = process.argv[5] ? JSON.parse(process.argv[5]) : undefined;

process.argv[2] = path.join(process.env.APP_ROOT, 'app.config.json');
const serverModule = require(serverPath);

function directRequest(handleApi, method, route, payload) {
  return new Promise((resolve, reject) => {
    const body = payload === undefined ? '' : JSON.stringify(payload);
    const req = new EventEmitter();
    req.method = method;
    const chunks = [];
    const res = {
      statusCode: 200,
      headers: {},
      setHeader(name, value) { this.headers[String(name).toLowerCase()] = value; },
      writeHead(status, headers) {
        this.statusCode = status;
        this.headers = { ...this.headers, ...(headers || {}) };
      },
      write(chunk) {
        if (chunk !== undefined) chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk)));
      },
      end(chunk) {
        if (chunk !== undefined) chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk)));
        const raw = Buffer.concat(chunks).toString('utf8');
        let parsed = {};
        try { parsed = raw ? JSON.parse(raw) : {}; }
        catch (error) {
          reject(new Error(`Invalid JSON from ${route}: ${error.message}; body=${raw}`));
          return;
        }
        resolve({ status: this.statusCode, body: parsed });
      },
    };
    Promise.resolve(handleApi(req, res, route)).catch(reject);
    process.nextTick(() => {
      if (body) req.emit('data', body);
      req.emit('end');
    });
  });
}

directRequest(serverModule.handleApi, method, route, payload)
  .then(result => {
    process.stdout.write(JSON.stringify(result));
  })
  .catch(error => {
    process.stderr.write(String(error && error.stack || error));
    process.exit(1);
  });
""",
            encoding="utf-8",
        )
        self.function_runner.write_text(
            """
const path = require('path');

const serverPath = process.argv[2];
const fn = process.argv[3];
const payload = process.argv[4] ? JSON.parse(process.argv[4]) : {};

process.argv[2] = path.join(process.env.APP_ROOT, 'app.config.json');
const serverModule = require(serverPath);
const testApi = serverModule.__test || {};

function rowsMapFromObject(value) {
  return new Map(Object.entries(value || {}));
}

let result;
if (fn === 'bindApiRequestParams') {
  result = testApi.bindApiRequestParams(payload.api_request_params || [], payload.known_params || {});
} else if (fn === 'rowsFromProbePayload') {
  result = { rows: testApi.rowsFromProbePayload(payload.payload || {}) };
} else if (fn === 'requestDebugFromProbePayload') {
  result = { request_debug: testApi.requestDebugFromProbePayload(payload.payload || {}) };
} else if (fn === 'fieldSourceStatuses') {
  const rowsByApi = rowsMapFromObject(payload.rows_by_api || {});
  const coverage = testApi.repairFieldCoverageWithRuntimeRows(payload.field_coverage_plan || [], rowsByApi);
  const projection = testApi.projectRowsForApiFieldCoverage(
    rowsByApi,
    coverage,
    payload.api_execution_plan || [],
  );
  const fieldSources = testApi.buildFieldSources(
    coverage,
    payload.api_execution_plan || [],
    projection.rows,
    {
      rowsByApi,
      primaryApiId: projection.primary_api_id,
      joinBlockedApiIds: projection.join_blocked_api_ids,
    },
  );
  result = { projection, field_sources: fieldSources, field_coverage_plan: coverage };
} else if (fn === 'competitorProjection') {
  result = testApi.projectCompetitorRows(
    payload.source_products || [],
    payload.competitor_rows || [],
    payload.review_rows || [],
  );
} else {
  throw new Error(`Unknown test function: ${fn}`);
}

process.stdout.write(JSON.stringify(result));
""",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        os.environ.pop("APP_ROOT", None)
        os.environ.pop("DB_ARCHAEOLOGIST_SPEC_PACK", None)
        os.environ.pop("DBA_LIVE_PROBE", None)

    def _load_server_module(self):
        server_js = Path(__file__).parent.parent / "shells" / "report_generator" / "server" / "server.js"
        return server_js

    def _serve_once(self, env_extra=None):
        server_js = self.server_module
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = os.environ.copy()
        env.update({"PORT": str(port), "APP_ROOT": str(self.app_root)})
        if env_extra:
            env.update(env_extra)
        process = subprocess.Popen(
            [shutil.which("node") or "/opt/homebrew/bin/node", str(server_js), str(self.config_path)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.addCleanup(lambda: process.poll() is None and process.terminate())
        time.sleep(1.0)
        return port, process

    def _get(self, port, path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def _post(self, port, path, payload):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def _direct(self, method, path, payload=None, env_extra=None):
        env = os.environ.copy()
        env.update({"APP_ROOT": str(self.app_root)})
        if env_extra:
            env.update(env_extra)
        result = subprocess.run(
            [
                shutil.which("node") or "/opt/homebrew/bin/node",
                str(self.direct_runner),
                str(self.server_module),
                path,
                method,
                json.dumps(payload) if payload is not None else "",
            ],
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        parsed = json.loads(result.stdout)
        return parsed["status"], parsed["body"]

    def _function(self, fn, payload=None, env_extra=None):
        env = os.environ.copy()
        env.update({"APP_ROOT": str(self.app_root)})
        if env_extra:
            env.update(env_extra)
        result = subprocess.run(
            [
                shutil.which("node") or "/opt/homebrew/bin/node",
                str(self.function_runner),
                str(self.server_module),
                fn,
                json.dumps(payload or {}, ensure_ascii=False),
            ],
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(result.stdout)

    def _write_collaboration_fixture(self) -> None:
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        node = next(item for item in config["nodes"] if item["id"] == "collect_top_products")
        node["analysis_node_view"] = {
            "schema_version": "analysis-node-view-v1",
            "node_id": "collect_top_products",
            "node_kind": "data_analysis",
            "insight_output_model": {
                "requirements": [
                    {
                        "requirement_id": "insight_1",
                        "question": "当前行业热卖产品分为哪几类？",
                        "required_evidence_fields": ["产品类型"],
                        "source_ref": "business_doc:分析结论",
                    },
                    {
                        "requirement_id": "insight_2",
                        "question": "哪些产品涨得快，原因是什么？",
                        "required_evidence_fields": ["是否高增速", "爆款原因"],
                        "source_ref": "business_doc:分析结论",
                    },
                ]
            },
        }
        self.config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        artifacts = self.app_root / "artifacts"
        artifacts.mkdir(exist_ok=True)
        table = {
            "schema_version": "data-table-draft-v1",
            "node_id": "collect_top_products",
            "execution_id": "exec-fixture-1",
            "fields": [
                {"field_path": "产品类型", "field_name": "产品类型", "title": "产品类型", "type": "string", "required": True},
                {"field_path": "功能", "field_name": "功能", "title": "功能", "type": "string", "required": True},
                {"field_path": "商品主图", "field_name": "商品主图", "title": "商品主图", "type": "string", "required": True},
            ],
            "rows": [
                {
                    "产品类型": "桌垫",
                    "功能": "",
                    "商品主图": "https://fixture.test/desk-1.jpg",
                    "材质": "PVC",
                    "场景": "书房、办公桌",
                    "主卖点": "防滑、防水、保护桌面",
                },
                {"产品类型": "桌垫", "功能": "防水", "商品主图": "https://fixture.test/desk-2.jpg"},
            ],
            "row_meta": [
                {"row_id": "goods:desk-1", "source_identity": "desk-1"},
                {"row_id": "goods:desk-2", "source_identity": "desk-2"},
            ],
            "field_sources": [
                {
                    "field_name": "功能",
                    "field_path": "功能",
                    "source_api_id": "data_goods_ads_ind_goods_detail_info_m",
                    "source_field_path": "data.result[].selling_point_summary",
                    "source_kind": "pi_derived",
                    "value_status": "pi_derived_unconfirmed",
                    "evidence_ref": "evidence/detail-enrichment.json",
                }
            ],
            "derived_fields": [
                {"field_name": "功能", "evidence_field_paths": ["selling_point_summary", "core_material", "usage_scene"]}
            ],
            "risks": [],
        }
        (artifacts / "collect_top_products.data_table.json").write_text(
            json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _write_keyword_collaboration_fixture(self, count=10) -> None:
        artifacts = self.app_root / "artifacts"
        artifacts.mkdir(exist_ok=True)
        rows = []
        row_meta = []
        for index in range(1, count + 1):
            keyword = f"防水桌布{index}"
            rows.append(
                {
                    "keyword": keyword,
                    "search_popularity": str(1000 + index),
                    "growth_rate": "0.12",
                    "competition_index": "0.45",
                    "click_rate": "0.08",
                    "conversion_rate": "0.06",
                    "root_terms": [],
                    "demand_type": "",
                }
            )
            row_meta.append(
                {"row_id": f"keyword:{keyword}", "source_identity": keyword}
            )
        fields = [
            {"field_path": name, "field_name": name, "title": name, "type": field_type, "required": True}
            for name, field_type in [
                ("keyword", "string"),
                ("search_popularity", "number"),
                ("growth_rate", "number"),
                ("competition_index", "number"),
                ("click_rate", "number"),
                ("conversion_rate", "number"),
                ("root_terms", "array"),
                ("demand_type", "string"),
            ]
        ]
        table = {
            "schema_version": "data-table-draft-v1",
            "node_id": "collect_keywords",
            "execution_id": "exec-keyword-fixture-1",
            "fields": fields,
            "rows": rows,
            "row_meta": row_meta,
            "field_sources": [
                {
                    "field_name": "root_terms",
                    "field_path": "root_terms",
                    "source_kind": "pi_derived",
                    "mapping_status": "derived_or_manual_required",
                    "value_status": "pi_derived_unconfirmed",
                    "evidence_field_paths": ["keyword"],
                },
                {
                    "field_name": "demand_type",
                    "field_path": "demand_type",
                    "source_kind": "pi_derived",
                    "mapping_status": "derived_or_manual_required",
                    "value_status": "pi_derived_unconfirmed",
                    "evidence_field_paths": ["keyword", "root_terms"],
                },
            ],
            "derived_fields": [
                {"field_name": "root_terms", "evidence_field_paths": ["keyword"]},
                {"field_name": "demand_type", "evidence_field_paths": ["keyword", "root_terms"]},
            ],
            "category_context": {
                "schema_version": "business-category-context-v1",
                "requested_name": "桌垫",
                "canonical_name": "桌布",
                "category_id": "121458013",
                "status": "resolved",
            },
            "status": "agent_enrichment_pending",
            "risks": [],
        }
        (artifacts / "collect_keywords.data_table.json").write_text(
            json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _write_gene_analysis_source_fixture(self, count=2, revision=1) -> None:
        artifacts = self.app_root / "artifacts"
        evidence = self.app_root / "evidence"
        artifacts.mkdir(exist_ok=True)
        evidence.mkdir(exist_ok=True)
        rows = []
        row_meta = []
        for index in range(count):
            goods_id = f"gene-{index + 1}"
            rows.append(
                {
                    "排名": str(index + 1),
                    "商品链接": f"https://fixture.test/?id={goods_id}",
                    "产品类型": "透明桌垫",
                    "材质": "PVC",
                    "功能": "防水、防油",
                    "风格": "简约",
                    "场景": "餐桌",
                    "客单价": str(50 + index),
                    "主卖点": "食品级无味，防油易清洁",
                    "主图元素": "白底产品特写",
                    "是否高增速": "高增" if index == 0 else "微涨",
                }
            )
            row_meta.append({"row_id": f"goods:{goods_id}", "source_identity": goods_id, "source_index": index})
        (artifacts / "collect_top_products.confirmed_data_table.json").write_text(
            json.dumps(
                {
                    "schema_version": "data-table-confirmed-v1",
                    "node_id": "collect_top_products",
                    "status": "confirmed",
                    "workspace_revision": revision,
                    "rows": rows,
                    "row_meta": row_meta,
                    "row_count": count,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (evidence / "collect_top_products.data_table_confirmation.json").write_text(
            json.dumps({"schema_version": "data-table-confirmation-v1", "status": "confirmed", "workspace_revision": revision}),
            encoding="utf-8",
        )

    def test_hot_product_gene_run_requires_confirmed_topn_source(self):
        status, response = self._direct("POST", "/api/nodes/analyze_hot_product_genes/run", {})
        self.assertEqual(status, 409)
        self.assertEqual(response["error"], "source_table_not_confirmed")

    def test_hot_product_gene_run_is_observable_and_confirmable(self):
        self._write_gene_analysis_source_fixture()
        prompt_capture = self.app_root / "gene_prompts.ndjson"
        fake_pi = self.app_root / "fake_pi_gene"
        fake_pi.write_text(
            "#!/usr/bin/env node\n"
            "const fs = require('fs');\n"
            "let request = '';\n"
            "process.stdin.setEncoding('utf8');\n"
            "process.stdin.once('data', chunk => {\n"
            "  request += chunk;\n"
            "  const command = JSON.parse(request.trim());\n"
            "  const match = command.message.match(/\\\"row_id\\\"\\s*:\\s*\\\"([^\\\"]+)/);\n"
            "  const rowId = match ? match[1] : '';\n"
            f"  fs.appendFileSync({json.dumps(str(prompt_capture))}, command.message + '\\n---CALL---\\n');\n"
            "  const proposal = { schema_version: 'hot-product-gene-product-proposal-v1', row_id: rowId, normalized_dimensions: {}, derived_fields: { '人群': { value: '家庭用户', confidence: 0.7, evidence_fields: ['场景'] } } };\n"
            "  process.stdout.write(JSON.stringify({ type: 'agent_start', model: 'aicodemirror/gpt-5.6-sol' }) + '\\n');\n"
            "  process.stdout.write(JSON.stringify({ type: 'message_update', assistantMessageEvent: { type: 'text_delta', delta: JSON.stringify(proposal) } }) + '\\n');\n"
            "  process.stdout.write(JSON.stringify({ type: 'agent_end', messages: [], willRetry: false }) + '\\n');\n"
            "});\n",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)
        env_extra = {
            "PI_BIN": str(fake_pi),
            "AICODEMIRROR_API_KEY": "sk-test",
            "PI_DEFAULT_MODEL": "aicodemirror/gpt-5.6-sol",
            "PI_RPC_TIMEOUT_MS": "3000",
        }
        status, started = self._direct("POST", "/api/nodes/analyze_hot_product_genes/run", {}, env_extra=env_extra)
        self.assertEqual(status, 202)
        self.assertEqual(started["status"], "running")

        analysis = None
        for _ in range(50):
            status, snapshot = self._direct("GET", "/api/nodes/analyze_hot_product_genes/gene-analysis", env_extra=env_extra)
            self.assertEqual(status, 200)
            analysis = snapshot.get("analysis")
            if analysis and analysis.get("status") == "draft_ready":
                break
            time.sleep(0.05)
        self.assertIsNotNone(analysis)
        self.assertEqual(analysis["status"], "draft_ready")
        self.assertEqual(analysis["progress"]["completed_products"], 2)
        self.assertEqual(analysis["product_profiles"][0]["dimensions"]["人群"]["raw_value"], "家庭用户")
        prompts = prompt_capture.read_text(encoding="utf-8").split("---CALL---")
        prompt_bodies = [item for item in prompts if item.strip()]
        self.assertEqual(len(prompt_bodies), 2)
        self.assertTrue(all(body.count('"row_id"') == 1 for body in prompt_bodies))

        status, confirmed = self._direct(
            "POST",
            f"/api/nodes/analyze_hot_product_genes/gene-analysis/{analysis['execution_id']}/confirm",
            {"execution_id": analysis["execution_id"], "source_revision": 1, "confirmed_by": "local_user"},
            env_extra=env_extra,
        )
        self.assertEqual(status, 200)
        self.assertEqual(confirmed["artifact"]["schema_version"], "hot-product-gene-analysis-confirmed-v1")

    def test_data_table_workspace_patch_is_revisioned_and_restores_api_value(self):
        self._write_collaboration_fixture()

        status, initial = self._direct("GET", "/api/nodes/collect_top_products/data-table-workspace")
        self.assertEqual(status, 200)
        self.assertEqual(initial["workspace"]["schema_version"], "data-table-workspace-v1")
        self.assertEqual(initial["workspace"]["revision"], 0)
        self.assertEqual(initial["effective_rows"][0]["功能"], "")

        status, updated = self._direct(
            "POST",
            "/api/nodes/collect_top_products/data-table-workspace/patch",
            {
                "schema_version": "data-table-edit-patch-v1",
                "base_revision": 0,
                "operations": [
                    {
                        "operation": "set_cell",
                        "row_id": "goods:desk-1",
                        "field_path": "功能",
                        "expected_value": "",
                        "new_value": "防滑、桌面保护",
                        "source_kind": "manual",
                        "reason": "人工修正",
                    }
                ],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["workspace"]["revision"], 1)
        self.assertEqual(updated["effective_rows"][0]["功能"], "防滑、桌面保护")
        override = updated["workspace"]["cell_overrides"]["goods:desk-1"]["功能"]
        self.assertEqual(override["original_value"], "")
        self.assertEqual(override["source_kind"], "manual")

        status, restored = self._direct(
            "POST",
            "/api/nodes/collect_top_products/data-table-workspace/patch",
            {
                "schema_version": "data-table-edit-patch-v1",
                "base_revision": 1,
                "operations": [
                    {
                        "operation": "restore_source",
                        "row_id": "goods:desk-1",
                        "field_path": "功能",
                        "expected_value": "防滑、桌面保护",
                    }
                ],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(restored["workspace"]["revision"], 2)
        self.assertEqual(restored["effective_rows"][0]["功能"], "")

    def test_data_table_workspace_edits_business_field_name_when_schema_path_differs(self):
        self._write_collaboration_fixture()
        table_path = self.app_root / "artifacts" / "collect_top_products.data_table.json"
        table = json.loads(table_path.read_text(encoding="utf-8"))
        function_field = next(item for item in table["fields"] if item["field_name"] == "功能")
        function_field["field_path"] = "items.properties.function"
        table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")

        status, initial = self._direct("GET", "/api/nodes/collect_top_products/data-table-workspace")
        self.assertEqual(status, 200)
        self.assertEqual(initial["effective_rows"][1]["功能"], "防水")

        status, updated = self._direct(
            "POST",
            "/api/nodes/collect_top_products/data-table-workspace/patch",
            {
                "schema_version": "data-table-edit-patch-v1",
                "base_revision": 0,
                "operations": [
                    {
                        "operation": "set_cell",
                        "row_id": "goods:desk-2",
                        "field_path": "功能",
                        "expected_value": "防水",
                        "new_value": "防水、防滑",
                        "source_kind": "manual",
                    }
                ],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["effective_rows"][1]["功能"], "防水、防滑")

    def test_data_table_workspace_rejects_revision_and_expected_value_conflicts(self):
        self._write_collaboration_fixture()
        self._direct("GET", "/api/nodes/collect_top_products/data-table-workspace")
        patch = {
            "schema_version": "data-table-edit-patch-v1",
            "base_revision": 0,
            "operations": [
                {
                    "operation": "set_cell",
                    "row_id": "goods:desk-2",
                    "field_path": "功能",
                    "expected_value": "防水",
                    "new_value": "防水、防滑",
                    "source_kind": "manual",
                }
            ],
        }
        status, _ = self._direct("POST", "/api/nodes/collect_top_products/data-table-workspace/patch", patch)
        self.assertEqual(status, 200)

        status, conflict = self._direct("POST", "/api/nodes/collect_top_products/data-table-workspace/patch", patch)
        self.assertEqual(status, 409)
        self.assertEqual(conflict["error"], "revision_conflict")
        self.assertEqual(conflict["current_revision"], 1)

        patch["base_revision"] = 1
        patch["operations"][0]["expected_value"] = "错误旧值"
        status, conflict = self._direct("POST", "/api/nodes/collect_top_products/data-table-workspace/patch", patch)
        self.assertEqual(status, 409)
        self.assertEqual(conflict["error"], "cell_value_conflict")
        self.assertEqual(conflict["conflicts"][0]["current_value"], "防水、防滑")

    def test_data_table_workspace_supports_extension_fields_and_undo(self):
        self._write_collaboration_fixture()
        self._direct("GET", "/api/nodes/collect_top_products/data-table-workspace")
        status, updated = self._direct(
            "POST",
            "/api/nodes/collect_top_products/data-table-workspace/patch",
            {
                "schema_version": "data-table-edit-patch-v1",
                "base_revision": 0,
                "operations": [
                    {
                        "operation": "add_extension_field",
                        "field_path": "人工标签",
                        "title": "人工标签",
                        "field_type": "single_select",
                        "options": ["重点", "观察"],
                    },
                    {
                        "operation": "set_cell",
                        "row_id": "goods:desk-1",
                        "field_path": "人工标签",
                        "expected_value": "",
                        "new_value": "重点",
                        "source_kind": "manual",
                    },
                ],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["effective_rows"][0]["人工标签"], "重点")
        self.assertEqual(updated["workspace"]["extension_fields"][0]["type"], "single_select")

        status, undone = self._direct(
            "POST",
            "/api/nodes/collect_top_products/data-table-workspace/undo",
            {"base_revision": 1},
        )
        self.assertEqual(status, 200)
        self.assertEqual(undone["workspace"]["revision"], 2)
        self.assertEqual(undone["workspace"]["extension_fields"], [])
        self.assertNotIn("人工标签", undone["effective_rows"][0])

    def test_data_table_workspace_confirmation_persists_effective_rows_for_downstream(self):
        self._write_collaboration_fixture()
        self._direct("GET", "/api/nodes/collect_top_products/data-table-workspace")
        status, _ = self._direct(
            "POST",
            "/api/nodes/collect_top_products/data-table-workspace/patch",
            {
                "schema_version": "data-table-edit-patch-v1",
                "base_revision": 0,
                "operations": [
                    {
                        "operation": "set_cell",
                        "row_id": "goods:desk-1",
                        "field_path": "功能",
                        "expected_value": "",
                        "new_value": "防滑、桌面保护",
                        "source_kind": "manual",
                    }
                ],
            },
        )
        self.assertEqual(status, 200)

        status, confirmed = self._direct(
            "POST",
            "/api/nodes/collect_top_products/data-table-workspace/confirm",
            {"base_revision": 1, "confirmed_by": "local_user"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(confirmed["confirmation"]["schema_version"], "data-table-confirmation-v1")
        self.assertEqual(confirmed["artifact"]["schema_version"], "data-table-confirmed-v1")
        self.assertEqual(confirmed["artifact"]["rows"][0]["功能"], "防滑、桌面保护")
        self.assertEqual(confirmed["artifact"]["workspace_revision"], 1)
        self.assertEqual(confirmed["artifact"]["row_count"], 2)
        self.assertEqual(confirmed["artifact"]["status"], "confirmed")
        persisted = json.loads(
            (self.app_root / "artifacts" / "collect_top_products.confirmed_data_table.json").read_text(encoding="utf-8")
        )
        self.assertEqual(persisted["rows"][0]["功能"], "防滑、桌面保护")

        status, edited = self._direct(
            "POST",
            "/api/nodes/collect_top_products/data-table-workspace/patch",
            {
                "schema_version": "data-table-edit-patch-v1",
                "base_revision": 1,
                "operations": [
                    {
                        "operation": "set_cell",
                        "row_id": "goods:desk-1",
                        "field_path": "功能",
                        "expected_value": "防滑、桌面保护",
                        "new_value": "防滑、防水、桌面保护",
                        "source_kind": "manual",
                    }
                ],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(edited["confirmation"]["status"], "stale")
        self.assertIsNone(edited["confirmed_artifact"])

    def test_data_table_workspace_confirmation_blocks_running_batch_and_ignores_pending_proposals(self):
        self._write_collaboration_fixture()
        self._direct("GET", "/api/nodes/collect_top_products/data-table-workspace")
        artifacts = self.app_root / "artifacts"
        thread = {
            "schema_version": "analysis-collaboration-thread-v1",
            "node_id": "collect_top_products",
            "messages": [],
            "agent_calls": [],
            "agent_batches": [{"batch_id": "batch-confirm-1", "status": "running"}],
        }
        (artifacts / "collect_top_products.agent_thread.json").write_text(
            json.dumps(thread, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        batch = {
            "schema_version": "analysis-agent-batch-v1",
            "batch_id": "batch-confirm-1",
            "node_id": "collect_top_products",
            "base_revision": 0,
            "status": "running",
            "page": {"row_ids": ["goods:desk-1"]},
            "progress": {},
            "items": [],
            "proposals": [],
        }
        batch_path = artifacts / "collect_top_products.agent_batch.batch-confirm-1.json"
        batch_path.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")

        status, blocked = self._direct(
            "POST",
            "/api/nodes/collect_top_products/data-table-workspace/confirm",
            {"base_revision": 0},
        )
        self.assertEqual(status, 409)
        self.assertEqual(blocked["error"], "agent_batch_running")

        batch["status"] = "review_ready"
        batch["proposals"] = [
            {
                "proposal_id": "proposal-pending-1",
                "row_id": "goods:desk-1",
                "field_path": "功能",
                "old_value": "",
                "new_value": "防滑",
                "status": "pending",
            }
        ]
        batch_path.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
        thread["agent_batches"][0]["status"] = "review_ready"
        (artifacts / "collect_top_products.agent_thread.json").write_text(
            json.dumps(thread, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        status, confirmed = self._direct(
            "POST",
            "/api/nodes/collect_top_products/data-table-workspace/confirm",
            {"base_revision": 0},
        )
        self.assertEqual(status, 200)
        self.assertEqual(confirmed["confirmation"]["ignored_pending_proposals"], 1)
        saved_batch = json.loads(batch_path.read_text(encoding="utf-8"))
        self.assertEqual(saved_batch["proposals"][0]["status"], "ignored_on_finalize")

    def test_insight_workspace_requires_evidence_and_becomes_stale_after_relevant_edit(self):
        self._write_collaboration_fixture()
        status, initial = self._direct("GET", "/api/nodes/collect_top_products/insight-workspace")
        self.assertEqual(status, 200)
        self.assertEqual(initial["workspace"]["schema_version"], "insight-collaboration-v1")
        block = initial["workspace"]["blocks"][0]
        requirement_id = block["requirement_id"]

        status, rejected = self._direct(
            "POST",
            "/api/nodes/collect_top_products/insight-workspace/confirm",
            {"base_revision": 0, "requirement_id": requirement_id},
        )
        self.assertEqual(status, 409)
        self.assertEqual(rejected["error"], "evidence_required")

        status, patched = self._direct(
            "POST",
            "/api/nodes/collect_top_products/insight-workspace/patch",
            {
                "base_revision": 0,
                "requirement_id": requirement_id,
                "draft_text": "桌垫是当前主要产品类型。",
                "evidence_bindings": [
                    {"kind": "field", "field_path": "产品类型"},
                    {"kind": "row", "row_id": "goods:desk-1", "field_path": "产品类型"},
                ],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(patched["workspace"]["revision"], 1)

        status, confirmed = self._direct(
            "POST",
            "/api/nodes/collect_top_products/insight-workspace/confirm",
            {"base_revision": 1, "requirement_id": requirement_id},
        )
        self.assertEqual(status, 200)
        self.assertEqual(confirmed["block"]["status"], "confirmed")

        status, table = self._direct("GET", "/api/nodes/collect_top_products/data-table-workspace")
        self.assertEqual(status, 200)
        status, _ = self._direct(
            "POST",
            "/api/nodes/collect_top_products/data-table-workspace/patch",
            {
                "schema_version": "data-table-edit-patch-v1",
                "base_revision": table["workspace"]["revision"],
                "operations": [
                    {
                        "operation": "set_cell",
                        "row_id": "goods:desk-1",
                        "field_path": "产品类型",
                        "expected_value": "桌垫",
                        "new_value": "异形桌垫",
                        "source_kind": "manual",
                    }
                ],
            },
        )
        self.assertEqual(status, 200)
        _, stale = self._direct("GET", "/api/nodes/collect_top_products/insight-workspace")
        stale_block = next(item for item in stale["workspace"]["blocks"] if item["requirement_id"] == requirement_id)
        self.assertEqual(stale_block["status"], "stale")
        self.assertEqual(stale_block["human_confirmation"]["status"], "stale")
        status, rejected = self._direct(
            "POST",
            "/api/nodes/collect_top_products/insight-workspace/confirm",
            {"base_revision": stale["workspace"]["revision"], "requirement_id": requirement_id},
        )
        self.assertEqual(status, 409)
        self.assertEqual(rejected["error"], "insight_stale")

    def test_data_table_workspace_migrates_overrides_by_row_id_after_rerun(self):
        self._write_collaboration_fixture()
        _, initial = self._direct("GET", "/api/nodes/collect_top_products/data-table-workspace")
        status, _ = self._direct(
            "POST",
            "/api/nodes/collect_top_products/data-table-workspace/patch",
            {
                "schema_version": "data-table-edit-patch-v1",
                "base_revision": initial["workspace"]["revision"],
                "operations": [
                    {"operation": "set_cell", "row_id": "goods:desk-1", "field_path": "功能", "expected_value": "", "new_value": "保留值", "source_kind": "manual"},
                    {"operation": "set_cell", "row_id": "goods:desk-2", "field_path": "功能", "expected_value": "防水", "new_value": "孤立值", "source_kind": "manual"},
                ],
            },
        )
        self.assertEqual(status, 200)

        table_path = self.app_root / "artifacts" / "collect_top_products.data_table.json"
        table = json.loads(table_path.read_text(encoding="utf-8"))
        table["execution_id"] = "exec-fixture-2"
        table["rows"] = [
            {"产品类型": "桌垫", "功能": "API 新值", "商品主图": "https://fixture.test/desk-1-new.jpg"},
            {"产品类型": "桌布", "功能": "", "商品主图": "https://fixture.test/desk-3.jpg"},
        ]
        table["row_meta"] = [
            {"row_id": "goods:desk-1", "source_identity": "desk-1"},
            {"row_id": "goods:desk-3", "source_identity": "desk-3"},
        ]
        table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")

        status, migrated = self._direct("GET", "/api/nodes/collect_top_products/data-table-workspace")
        self.assertEqual(status, 200)
        self.assertEqual(migrated["effective_rows"][0]["功能"], "保留值")
        self.assertEqual(migrated["effective_rows"][1]["功能"], "")
        self.assertIn("goods:desk-1", migrated["workspace"]["cell_overrides"])
        self.assertNotIn("goods:desk-2", migrated["workspace"]["cell_overrides"])
        self.assertEqual(migrated["workspace"]["orphaned_patches"][-1]["row_id"], "goods:desk-2")

    def test_pi_table_edit_advice_filters_patches_outside_selected_cells(self):
        self._write_collaboration_fixture()
        proposal = {
            "schema_version": "pi-data-mapping-advice-v1",
            "node_id": "collect_top_products",
            "summary": {"status": "needs_review", "text": "已检查选区"},
            "field_advice": [],
            "table_edit_proposal": {
                "schema_version": "data-table-edit-proposal-v1",
                "summary": "补齐功能",
                "patches": [
                    {"row_id": "goods:desk-1", "field_path": "功能", "old_value": "", "new_value": "防滑", "reason": "卖点证据", "confidence": 0.9},
                    {"row_id": "goods:desk-2", "field_path": "产品类型", "old_value": "桌垫", "new_value": "其它", "reason": "越界修改", "confidence": 0.6},
                ],
            },
        }
        event = {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": json.dumps(proposal, ensure_ascii=False)}}
        fake_pi = self.app_root / "fake_pi_table_edit"
        fake_pi.write_text(
            "#!/bin/sh\nIFS= read -r _request\nprintf '%s\\n' "
            + shlex.quote(json.dumps(event, ensure_ascii=False))
            + "\nprintf '%s\\n' '{\"type\":\"agent_end\",\"messages\":[],\"willRetry\":false}'\n",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)

        status, data = self._direct(
            "POST",
            "/api/pi-agent/query",
            {
                "node_id": "collect_top_products",
                "intent": "table_edit_advice",
                "message": "补齐选中单元格",
                "table_workspace": {
                    "revision": 0,
                    "fields": [{"field_path": "产品类型"}, {"field_path": "功能"}],
                    "row_meta": [{"row_id": "goods:desk-1"}, {"row_id": "goods:desk-2"}],
                },
                "table_selection": {
                    "scope_mode": "cells",
                    "cells": [{"row_id": "goods:desk-1", "field_path": "功能", "effective_value": "", "source_kind": "api"}],
                },
                "conversation_history": [{"role": "user", "content": "只改选中格"}],
            },
            env_extra={"PI_BIN": str(fake_pi), "AICODEMIRROR_API_KEY": "sk-test", "PI_RPC_TIMEOUT_MS": "3000"},
        )
        self.assertEqual(status, 200)
        table_proposal = data["advice"]["table_edit_proposal"]
        self.assertEqual(table_proposal["schema_version"], "data-table-edit-proposal-v1")
        self.assertEqual(table_proposal["workspace_revision"], 0)
        self.assertEqual(len(table_proposal["patches"]), 1)
        self.assertEqual(table_proposal["raw_patch_count"], 2)
        self.assertEqual(table_proposal["accepted_patch_count"], 1)
        self.assertEqual(table_proposal["rejected_patch_count"], 1)
        self.assertEqual(
            table_proposal["rejected_patch_refs"],
            [{
                "row_id": "goods:desk-2",
                "field_path": "产品类型",
                "reason": "outside_selection",
                "patch_keys": ["confidence", "field_path", "new_value", "old_value", "reason", "row_id"],
            }],
        )
        self.assertEqual(table_proposal["patches"][0]["row_id"], "goods:desk-1")
        self.assertIn("patch_outside_selection_rejected", table_proposal["risks"])
        self.assertTrue(table_proposal["requires_human_application"])

    def test_pi_table_edit_advice_maps_source_identity_and_schema_path_to_selected_cell(self):
        proposal = {
            "schema_version": "pi-data-mapping-advice-v1",
            "node_id": "collect_top_products",
            "summary": {"status": "needs_review", "text": "补齐功能"},
            "field_advice": [],
            "table_edit_proposal": {
                "schema_version": "data-table-edit-proposal-v1",
                "summary": "补齐功能",
                "patches": [
                    {
                        "row_id": "desk-1",
                        "field": "功能",
                        "old_value": "",
                        "new_value": "防油、耐黄变、无味、易清洁",
                        "reason": "材质、场景和主卖点证据",
                        "confidence": 0.86,
                        "evidence_refs": [
                            {"row_id": "goods:desk-1", "field_path": "材质"},
                            {"ref": "evidence/detail.json"},
                        ],
                    }
                ],
            },
        }
        event = {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": json.dumps(proposal, ensure_ascii=False)}}
        fake_pi = self.app_root / "fake_pi_table_edit_schema_path"
        fake_pi.write_text(
            "#!/bin/sh\nIFS= read -r _request\nprintf '%s\\n' "
            + shlex.quote(json.dumps(event, ensure_ascii=False))
            + "\nprintf '%s\\n' '{\"type\":\"agent_end\",\"messages\":[],\"willRetry\":false}'\n",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)

        status, data = self._direct(
            "POST",
            "/api/pi-agent/query",
            {
                "node_id": "collect_top_products",
                "intent": "table_edit_advice",
                "message": "补齐选中单元格",
                "table_workspace": {
                    "revision": 1,
                    "fields": [
                        {
                            "field_path": "items.properties.function",
                            "field_name": "功能",
                            "title": "功能",
                        }
                    ],
                    "row_meta": [{"row_id": "goods:desk-1", "source_identity": "desk-1"}],
                },
                "table_selection": {
                    "scope_mode": "cells",
                    "cells": [{"row_id": "goods:desk-1", "field_path": "功能", "effective_value": "", "source_kind": "missing"}],
                },
            },
            env_extra={"PI_BIN": str(fake_pi), "AICODEMIRROR_API_KEY": "sk-test", "PI_RPC_TIMEOUT_MS": "3000"},
        )
        self.assertEqual(status, 200)
        table_proposal = data["advice"]["table_edit_proposal"]
        self.assertEqual(table_proposal["status"], "pending")
        self.assertEqual(table_proposal["patches"][0]["row_id"], "goods:desk-1")
        self.assertEqual(table_proposal["patches"][0]["field_path"], "功能")
        self.assertEqual(
            table_proposal["patches"][0]["evidence_refs"],
            ["goods:desk-1 · 材质", "evidence/detail.json"],
        )
        self.assertNotIn("patch_outside_selection_rejected", table_proposal["risks"])

    def test_agent_thread_starts_empty_and_persists_validated_cell_context(self):
        self._write_collaboration_fixture()

        status, initial = self._direct("GET", "/api/nodes/collect_top_products/agent-thread")
        self.assertEqual(status, 200)
        self.assertEqual(initial["thread"]["schema_version"], "analysis-collaboration-thread-v1")
        self.assertEqual(initial["thread"]["messages"], [])

        status, attached = self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/context",
            {
                "context_type": "cell_context",
                "row_id": "goods:desk-1",
                "field_path": "功能",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(attached["thread"]["messages"]), 1)
        context = attached["thread"]["messages"][0]
        self.assertEqual(context["role"], "context")
        self.assertEqual(context["intent"], "cell_context")
        self.assertEqual(context["context_refs"][0]["effective_value"], "")
        self.assertEqual(context["context_refs"][0]["original_value"], "")
        self.assertEqual(context["context_refs"][0]["source_kind"], "missing")
        self.assertEqual(context["context_refs"][0]["source_api_id"], "data_goods_ads_ind_goods_detail_info_m")
        self.assertEqual(context["context_refs"][0]["source_field_path"], "data.result[].selling_point_summary")
        self.assertIn("core_material", context["context_refs"][0]["related_evidence_fields"])
        self.assertIn("evidence/detail-enrichment.json", context["context_refs"][0]["evidence_refs"])
        self.assertNotIn("request_url", json.dumps(context, ensure_ascii=False))

        status, reloaded = self._direct("GET", "/api/nodes/collect_top_products/agent-thread")
        self.assertEqual(status, 200)
        self.assertEqual(reloaded["thread"]["messages"][0]["message_id"], context["message_id"])
        self.assertTrue((self.app_root / "artifacts" / "collect_top_products.agent_thread.json").exists())

        status, invalid = self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/context",
            {"context_type": "cell_context", "row_id": "goods:not-found", "field_path": "功能"},
        )
        self.assertEqual(status, 400)
        self.assertEqual(invalid["error"], "row_not_found")

    def test_agent_thread_query_persists_messages_and_keeps_table_proposal_pending(self):
        self._write_collaboration_fixture()
        proposal = {
            "schema_version": "pi-data-mapping-advice-v1",
            "node_id": "collect_top_products",
            "summary": {"status": "needs_review", "text": "建议补充防滑功能"},
            "field_advice": [],
            "table_edit_proposal": {
                "schema_version": "data-table-edit-proposal-v1",
                "summary": "补齐功能",
                "patches": [
                    {
                        "row_id": "goods:desk-1",
                        "field_path": "功能",
                        "old_value": "",
                        "new_value": "防滑",
                        "reason": "商品详情卖点证据",
                        "confidence": 0.9,
                        "evidence_refs": ["evidence/detail.json"],
                    }
                ],
            },
        }
        event = {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": json.dumps(proposal, ensure_ascii=False)}}
        fake_pi = self.app_root / "fake_pi_agent_thread"
        fake_pi.write_text(
            "#!/bin/sh\nIFS= read -r _request\nprintf '%s\\n' "
            + shlex.quote(json.dumps(event, ensure_ascii=False))
            + "\nprintf '%s\\n' '{\"type\":\"agent_end\",\"messages\":[],\"willRetry\":false}'\n",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)

        self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/context",
            {"context_type": "cell_context", "row_id": "goods:desk-1", "field_path": "功能"},
        )
        status, queried = self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/query",
            {"message": "请根据证据补齐这个单元格", "model": "aicodemirror/gpt-5.6-sol"},
            env_extra={"PI_BIN": str(fake_pi), "AICODEMIRROR_API_KEY": "sk-test", "PI_RPC_TIMEOUT_MS": "3000"},
        )
        self.assertEqual(status, 200)
        self.assertEqual([item["role"] for item in queried["thread"]["messages"]], ["context", "user", "assistant"])
        assistant = queried["thread"]["messages"][-1]
        self.assertEqual(assistant["intent"], "cell_context")
        self.assertEqual(assistant["proposal"]["schema_version"], "data-table-edit-proposal-v1")
        self.assertEqual(assistant["proposal_status"], "pending")

        _, table = self._direct("GET", "/api/nodes/collect_top_products/data-table-workspace")
        self.assertEqual(table["effective_rows"][0]["功能"], "")
        self.assertEqual(table["workspace"]["revision"], 0)

    def test_agent_thread_persists_preferred_model_and_uses_it_for_calls(self):
        self._write_collaboration_fixture()
        status, updated = self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/model",
            {"preferred_model": "aicodemirror/gpt-5.6-sol"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["thread"]["preferred_model"], "aicodemirror/gpt-5.6-sol")
        self.assertEqual(updated["thread"]["model_updated_by"], "user")

        status, reloaded = self._direct("GET", "/api/nodes/collect_top_products/agent-thread")
        self.assertEqual(status, 200)
        self.assertEqual(reloaded["thread"]["preferred_model"], "aicodemirror/gpt-5.6-sol")

    def test_agent_thread_call_audits_submitted_cell_context_and_actual_model(self):
        self._write_collaboration_fixture()
        fake_pi = self.app_root / "fake_pi_observable"
        events = [
            {"type": "agent_start", "model": "deepseek/deepseek-v4-flash"},
            {"type": "thinking_start"},
            {
                "type": "message_update",
                "assistantMessageEvent": {
                    "type": "text_delta",
                    "delta": json.dumps(
                        {
                            "schema_version": "pi-data-mapping-advice-v1",
                            "node_id": "collect_top_products",
                            "summary": {"status": "needs_review", "text": "建议使用防滑、桌面保护"},
                            "field_advice": [],
                            "table_edit_proposal": {
                                "schema_version": "data-table-edit-proposal-v1",
                                "patches": [
                                    {
                                        "row_id": "goods:desk-1",
                                        "field_path": "功能",
                                        "old_value": "",
                                        "new_value": "防滑、桌面保护",
                                        "reason": "材质、场景和主卖点证据",
                                        "confidence": 0.9,
                                        "evidence_refs": ["evidence/detail-enrichment.json"],
                                    }
                                ],
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            },
            {"type": "agent_end", "messages": [], "willRetry": False},
        ]
        fake_pi.write_text(
            "#!/bin/sh\nIFS= read -r _request\n"
            + "".join(f"printf '%s\\n' {shlex.quote(json.dumps(event, ensure_ascii=False))}\n" for event in events),
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)
        self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/context",
            {"context_type": "cell_context", "row_id": "goods:desk-1", "field_path": "功能"},
        )
        status, queried = self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/query",
            {"message": "请根据这个商品的材质、场景和主卖点补齐功能字段，只给出有证据支持的简洁描述。"},
            env_extra={
                "PI_BIN": str(fake_pi),
                "AICODEMIRROR_API_KEY": "sk-test",
                "PI_DEFAULT_MODEL": "aicodemirror/gpt-5.6-sol",
                "PI_RPC_TIMEOUT_MS": "3000",
            },
        )
        self.assertEqual(status, 200)
        call = queried["thread"]["agent_calls"][-1]
        self.assertEqual(call["requested_model"], "aicodemirror/gpt-5.6-sol")
        self.assertEqual(call["actual_model"], "deepseek/deepseek-v4-flash")
        self.assertEqual(call["model_resolution_status"], "substituted")
        self.assertEqual(call["status"], "completed")
        snapshot = call["context_snapshot"]
        self.assertEqual(snapshot["target_field"], "功能")
        self.assertEqual(snapshot["evidence_values"]["材质"], "PVC")
        self.assertEqual(snapshot["evidence_values"]["场景"], "书房、办公桌")
        self.assertEqual(snapshot["evidence_values"]["主卖点"], "防滑、防水、保护桌面")
        serialized = json.dumps(call, ensure_ascii=False)
        self.assertNotIn("sk-test", serialized)
        self.assertNotIn("thinking_delta", serialized)
        stages = [item["stage"] for item in call["timeline"]]
        for stage in ["context_prepared", "process_started", "agent_started", "analyzing", "first_text", "completed"]:
            self.assertIn(stage, stages)

    def test_agent_thread_timeout_is_transparent_and_has_no_deterministic_fallback(self):
        self._write_collaboration_fixture()
        fake_pi = self.app_root / "fake_pi_timeout"
        fake_pi.write_text("#!/bin/sh\nIFS= read -r _request\nsleep 1\n", encoding="utf-8")
        fake_pi.chmod(0o755)
        self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/context",
            {"context_type": "cell_context", "row_id": "goods:desk-1", "field_path": "功能"},
        )
        status, queried = self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/query",
            {"message": "补齐功能"},
            env_extra={
                "PI_BIN": str(fake_pi),
                "AICODEMIRROR_API_KEY": "sk-test",
                "PI_DEFAULT_MODEL": "aicodemirror/gpt-5.6-sol",
                "PI_RPC_TIMEOUT_MS": "50",
            },
        )
        self.assertEqual(status, 200)
        call = queried["thread"]["agent_calls"][-1]
        self.assertEqual(call["status"], "timed_out")
        self.assertEqual(call["failure_reason"], "pi_rpc_timeout")
        assistant = queried["thread"]["messages"][-1]
        self.assertEqual(assistant["failure_reason"], "pi_rpc_timeout")
        self.assertIsNone(assistant["proposal"])
        serialized = json.dumps(queried, ensure_ascii=False)
        self.assertNotIn("确定性规则兜底", serialized)
        self.assertNotIn("确定性规则生成", serialized)

    def test_agent_thread_async_query_returns_call_id_and_persists_terminal_call(self):
        self._write_collaboration_fixture()
        fake_pi = self.app_root / "fake_pi_async"
        proposal = {
            "schema_version": "pi-data-mapping-advice-v1",
            "node_id": "collect_top_products",
            "summary": {"status": "needs_review", "text": "建议补齐防滑功能"},
            "field_advice": [],
            "table_edit_proposal": {
                "schema_version": "data-table-edit-proposal-v1",
                "patches": [
                    {
                        "row_id": "goods:desk-1",
                        "field_path": "功能",
                        "old_value": "",
                        "new_value": "防滑",
                        "reason": "主卖点证据",
                        "confidence": 0.9,
                        "evidence_refs": [],
                    }
                ],
            },
        }
        fake_pi.write_text(
            "#!/bin/sh\nIFS= read -r _request\n"
            + f"printf '%s\\n' {shlex.quote(json.dumps({'type': 'agent_start', 'model': 'aicodemirror/gpt-5.6-sol'}))}\n"
            + f"printf '%s\\n' {shlex.quote(json.dumps({'type': 'message_update', 'assistantMessageEvent': {'type': 'text_delta', 'delta': json.dumps(proposal, ensure_ascii=False)}}, ensure_ascii=False))}\n"
            + "printf '%s\\n' '{\"type\":\"agent_end\",\"messages\":[],\"willRetry\":false}'\n",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)
        self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/context",
            {"context_type": "cell_context", "row_id": "goods:desk-1", "field_path": "功能"},
        )
        status, accepted = self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/query",
            {"async": True, "message": "补齐功能"},
            env_extra={
                "PI_BIN": str(fake_pi),
                "AICODEMIRROR_API_KEY": "sk-test",
                "PI_DEFAULT_MODEL": "aicodemirror/gpt-5.6-sol",
                "PI_RPC_TIMEOUT_MS": "3000",
            },
        )
        self.assertEqual(status, 202)
        self.assertTrue(accepted["call_id"].startswith("call-"))
        self.assertEqual(accepted["thread"]["agent_calls"][-1]["context_snapshot"]["target_field"], "功能")

        status, call = self._direct(
            "GET",
            f"/api/nodes/collect_top_products/agent-thread/calls/{accepted['call_id']}",
        )
        self.assertEqual(status, 200)
        self.assertEqual(call["call"]["status"], "completed")
        self.assertEqual(call["call"]["actual_model"], "aicodemirror/gpt-5.6-sol")

    def test_agent_thread_treats_provider_omitted_runtime_model_as_matched(self):
        self._write_collaboration_fixture()
        fake_pi = self.app_root / "fake_pi_provider_omitted"
        proposal = {
            "schema_version": "pi-data-mapping-advice-v1",
            "node_id": "collect_top_products",
            "summary": {"status": "needs_review", "text": "建议补齐功能"},
            "field_advice": [],
            "table_edit_proposal": {
                "schema_version": "data-table-edit-proposal-v1",
                "patches": [],
            },
        }
        fake_pi.write_text(
            "#!/bin/sh\nIFS= read -r _request\n"
            + f"printf '%s\\n' {shlex.quote(json.dumps({'type': 'agent_start', 'model': 'gpt-5.6-sol'}))}\n"
            + f"printf '%s\\n' {shlex.quote(json.dumps({'type': 'message_update', 'assistantMessageEvent': {'type': 'text_delta', 'delta': json.dumps(proposal, ensure_ascii=False)}}, ensure_ascii=False))}\n"
            + "printf '%s\\n' '{\"type\":\"agent_end\",\"messages\":[],\"willRetry\":false}'\n",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)
        self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/context",
            {"context_type": "cell_context", "row_id": "goods:desk-1", "field_path": "功能"},
        )
        status, queried = self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/query",
            {"message": "补齐功能"},
            env_extra={
                "PI_BIN": str(fake_pi),
                "AICODEMIRROR_API_KEY": "sk-test",
                "PI_DEFAULT_MODEL": "aicodemirror/gpt-5.6-sol",
                "PI_RPC_TIMEOUT_MS": "3000",
            },
        )
        self.assertEqual(status, 200)
        call = queried["thread"]["agent_calls"][-1]
        self.assertEqual(call["actual_model"], "gpt-5.6-sol")
        self.assertEqual(call["model_resolution_status"], "matched")
        self.assertEqual(call["model_comparison_reason"], "provider_omitted")

    def test_keyword_agent_batch_exposes_two_fillable_fields_per_row_and_validates_output(self):
        self._write_keyword_collaboration_fixture(count=10)
        status, workspace = self._direct(
            "GET", "/api/nodes/collect_keywords/data-table-workspace"
        )
        self.assertEqual(status, 200)
        self.assertEqual(workspace["agent_enrichment"]["subject_kind"], "keyword")
        self.assertEqual(
            workspace["agent_enrichment"]["fillable_fields"],
            ["root_terms", "demand_type"],
        )
        self.assertEqual(workspace["agent_enrichment"]["remaining_cells"], 20)
        self.assertEqual(workspace["agent_enrichment"]["status"], "agent_enrichment_pending")

        prompt_capture = self.app_root / "keyword_agent_batch_prompts.jsonl"
        fake_pi = self.app_root / "fake_pi_keyword_agent_batch"
        fake_pi.write_text(
            "#!/usr/bin/env node\n"
            "const fs = require('fs');\n"
            "let request = '';\n"
            "process.stdin.setEncoding('utf8');\n"
            "process.stdin.once('data', chunk => { request += chunk;\n"
            "  const payload = JSON.parse(request.trim());\n"
            f"  fs.appendFileSync({json.dumps(str(prompt_capture))}, JSON.stringify(payload) + '\\n');\n"
            "  const rowId = (payload.message.match(/\\\"row_id\\\": \\\"([^\\\"]+)/) || [])[1] || '';\n"
            "  const proposal = {schema_version:'pi-data-mapping-advice-v1',node_id:'collect_keywords',summary:{status:'needs_review',text:'关键词语义建议'},field_advice:[],table_edit_proposal:{schema_version:'data-table-edit-proposal-v1',patches:[\n"
            "    {row_id:rowId,field_path:'root_terms',old_value:[],new_value:['防水','桌布','防水'],reason:'关键词拆解',confidence:0.9,evidence_refs:[]},\n"
            "    {row_id:rowId,field_path:'demand_type',old_value:'',new_value:'功能需求',reason:'防水表达功能诉求',confidence:0.9,evidence_refs:[]},\n"
            "    {row_id:rowId,field_path:'click_rate',old_value:'0.08',new_value:'0.99',reason:'越界修改',confidence:1,evidence_refs:[]}\n"
            "]}};\n"
            "  process.stdout.write(JSON.stringify({type:'agent_start',model:'gpt-5.6-sol'}) + '\\n');\n"
            "  process.stdout.write(JSON.stringify({type:'message_update',assistantMessageEvent:{type:'text_delta',delta:JSON.stringify(proposal)}}) + '\\n');\n"
            "  process.stdout.write('{\"type\":\"agent_end\",\"messages\":[],\"willRetry\":false}\\n');\n"
            "});\n",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)
        status, started = self._direct(
            "POST",
            "/api/nodes/collect_keywords/agent-thread/batches",
            {"base_revision": 0, "page_number": 1, "page_size": 10},
            env_extra={
                "PI_BIN": str(fake_pi),
                "AICODEMIRROR_API_KEY": "sk-test",
                "PI_DEFAULT_MODEL": "aicodemirror/gpt-5.6-sol",
                "PI_RPC_TIMEOUT_MS": "3000",
            },
        )
        self.assertEqual(status, 202)
        status, loaded = self._direct(
            "GET",
            f"/api/nodes/collect_keywords/agent-thread/batches/{started['batch_id']}",
        )
        self.assertEqual(status, 200)
        batch = loaded["batch"]
        self.assertEqual(batch["subject_kind"], "keyword")
        self.assertEqual(batch["progress"]["eligible_products"], 10)
        self.assertEqual(batch["progress"]["target_cells"], 20)
        self.assertEqual(batch["progress"]["proposed_cells"], 20, json.dumps(batch, ensure_ascii=False))
        self.assertTrue(all(item["model_resolution_status"] == "matched" for item in batch["items"]))
        self.assertTrue(all(item["model_comparison_reason"] == "provider_omitted" for item in batch["items"]))
        root_proposals = [item for item in batch["proposals"] if item["field_path"] == "root_terms"]
        self.assertEqual(len(root_proposals), 10)
        self.assertTrue(all(item["new_value"] == ["防水", "桌布"] for item in root_proposals))
        self.assertFalse(any(item["field_path"] == "click_rate" for item in batch["proposals"]))

        prompts = [json.loads(line) for line in prompt_capture.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(prompts), 10)
        for prompt in prompts:
            self.assertIn("八类需求标准", prompt["message"])
            self.assertIn("品类需求", prompt["message"])
            self.assertIn("定制需求", prompt["message"])
            match = re.search(r'"row_id": "(keyword:防水桌布\d+)"', prompt["message"])
            self.assertIsNotNone(match)
            self.assertEqual(prompt["message"].count(match.group(1)), 1)

        proposal_ids = [item["proposal_id"] for item in batch["proposals"]]
        status, applied = self._direct(
            "POST",
            f"/api/nodes/collect_keywords/agent-thread/batches/{started['batch_id']}/apply",
            {"base_revision": 0, "proposal_ids": proposal_ids},
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            applied["table_workspace"]["agent_enrichment"]["status"],
            "agent_enrichment_complete",
        )
        self.assertEqual(
            applied["table_workspace"]["effective_rows"][0]["root_terms"],
            ["防水", "桌布"],
        )

        revision = applied["table_workspace"]["workspace"]["revision"]
        status, confirmed = self._direct(
            "POST",
            "/api/nodes/collect_keywords/data-table-workspace/confirm",
            {"base_revision": revision},
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            confirmed["keyword_root_top20"]["status"], "draft_ready"
        )
        root_artifact = json.loads(
            (self.app_root / "artifacts" / "collect_keywords.keyword_root_top20.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(root_artifact["source_revision"], revision)
        self.assertEqual(root_artifact["rows"][0]["root_term"], "防水")

    def test_keyword_workspace_reports_partial_after_some_fields_are_filled(self):
        self._write_keyword_collaboration_fixture(count=2)
        status, patched = self._direct(
            "POST",
            "/api/nodes/collect_keywords/data-table-workspace/patch",
            {
                "schema_version": "data-table-edit-patch-v1",
                "base_revision": 0,
                "operations": [
                    {
                        "operation": "set_cell",
                        "row_id": "keyword:防水桌布1",
                        "field_path": "root_terms",
                        "expected_value": [],
                        "new_value": ["防水", "桌布"],
                        "source_kind": "manual",
                        "reason": "人工复核词根",
                    }
                ],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            patched["agent_enrichment"]["status"], "agent_enrichment_partial"
        )
        self.assertEqual(patched["agent_enrichment"]["remaining_cells"], 3)

    def test_keyword_agent_batch_normalizes_flat_and_field_value_patch_shapes(self):
        self._write_keyword_collaboration_fixture(count=2)
        fake_pi = self.app_root / "fake_pi_keyword_patch_shapes"
        fake_pi.write_text(
            "#!/usr/bin/env node\n"
            "let request = '';\n"
            "process.stdin.setEncoding('utf8');\n"
            "process.stdin.once('data', chunk => { request += chunk;\n"
            "  const payload = JSON.parse(request.trim());\n"
            "  const rowId = (payload.message.match(/\\\"row_id\\\": \\\"([^\\\"]+)/) || [])[1] || '';\n"
            "  const patches = rowId.endsWith('1')\n"
            "    ? [{row_id:rowId,root_terms:'防水，桌布，防水',demand_type:'功能'}]\n"
            "    : [\n"
            "        {row_id:rowId,field:'root_terms',value:['加厚','桌布','加厚']},\n"
            "        {row_id:rowId,field_name:'demand_type',value:'场景'}\n"
            "      ];\n"
            "  const proposal = {schema_version:'pi-data-mapping-advice-v1',node_id:'collect_keywords',summary:{status:'needs_review',text:'关键词语义建议'},field_advice:[],table_edit_proposal:{schema_version:'data-table-edit-proposal-v1',patches}};\n"
            "  process.stdout.write(JSON.stringify({type:'agent_start',model:'gpt-5.6-sol'}) + '\\n');\n"
            "  process.stdout.write(JSON.stringify({type:'message_update',assistantMessageEvent:{type:'text_delta',delta:JSON.stringify(proposal)}}) + '\\n');\n"
            "  process.stdout.write('{\"type\":\"agent_end\",\"messages\":[],\"willRetry\":false}\\n');\n"
            "});\n",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)
        status, started = self._direct(
            "POST",
            "/api/nodes/collect_keywords/agent-thread/batches",
            {"base_revision": 0, "page_number": 1, "page_size": 10},
            env_extra={
                "PI_BIN": str(fake_pi),
                "AICODEMIRROR_API_KEY": "sk-test",
                "PI_DEFAULT_MODEL": "aicodemirror/gpt-5.6-sol",
                "PI_RPC_TIMEOUT_MS": "3000",
            },
        )
        self.assertEqual(status, 202)
        _, loaded = self._direct(
            "GET", f"/api/nodes/collect_keywords/agent-thread/batches/{started['batch_id']}"
        )
        batch = loaded["batch"]
        self.assertEqual(batch["progress"]["proposed_cells"], 4, json.dumps(batch, ensure_ascii=False))
        self.assertEqual(batch["progress"]["rejected_cells"], 0)
        self.assertTrue(all(not item["proposal_risks"] for item in batch["items"]))
        self.assertEqual(
            [diagnostic["patch_format"] for diagnostic in batch["items"][0]["patch_diagnostics"]],
            ["flat_keyword_patch", "flat_keyword_patch"],
        )
        self.assertEqual(
            [diagnostic["patch_format"] for diagnostic in batch["items"][1]["patch_diagnostics"]],
            ["field_value_patch", "field_value_patch"],
        )
        proposals = {
            (item["row_id"], item["field_path"]): item["new_value"]
            for item in batch["proposals"]
        }
        self.assertEqual(proposals[("keyword:防水桌布1", "root_terms")], ["防水", "桌布"])
        self.assertEqual(proposals[("keyword:防水桌布1", "demand_type")], "功能需求")
        self.assertEqual(proposals[("keyword:防水桌布2", "root_terms")], ["加厚", "桌布"])
        self.assertEqual(proposals[("keyword:防水桌布2", "demand_type")], "场景需求")

    def test_keyword_agent_batch_rejects_unknown_demand_type(self):
        self._write_keyword_collaboration_fixture(count=1)
        fake_pi = self.app_root / "fake_pi_keyword_invalid_demand"
        proposal = {
            "schema_version": "pi-data-mapping-advice-v1",
            "node_id": "collect_keywords",
            "summary": {"status": "needs_review", "text": "错误分类"},
            "field_advice": [],
            "table_edit_proposal": {
                "schema_version": "data-table-edit-proposal-v1",
                "patches": [
                    {
                        "row_id": "keyword:防水桌布1",
                        "field": "root_terms",
                        "value": {"unexpected": "object"},
                        "reason": "错误的词根结构",
                        "confidence": 0.8,
                        "evidence_refs": [],
                    },
                    {
                        "row_id": "keyword:防水桌布1",
                        "field_path": "demand_type",
                        "old_value": "",
                        "new_value": "其它需求",
                        "reason": "不在枚举中",
                        "confidence": 0.8,
                        "evidence_refs": [],
                    }
                ],
            },
        }
        fake_pi.write_text(
            "#!/bin/sh\nIFS= read -r _request\n"
            + f"printf '%s\\n' {shlex.quote(json.dumps({'type': 'agent_start', 'model': 'gpt-5.6-sol'}))}\n"
            + f"printf '%s\\n' {shlex.quote(json.dumps({'type': 'message_update', 'assistantMessageEvent': {'type': 'text_delta', 'delta': json.dumps(proposal, ensure_ascii=False)}}, ensure_ascii=False))}\n"
            + "printf '%s\\n' '{\"type\":\"agent_end\",\"messages\":[],\"willRetry\":false}'\n",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)
        status, started = self._direct(
            "POST",
            "/api/nodes/collect_keywords/agent-thread/batches",
            {"base_revision": 0, "page_number": 1, "page_size": 10},
            env_extra={
                "PI_BIN": str(fake_pi),
                "AICODEMIRROR_API_KEY": "sk-test",
                "PI_DEFAULT_MODEL": "aicodemirror/gpt-5.6-sol",
                "PI_RPC_TIMEOUT_MS": "3000",
            },
        )
        self.assertEqual(status, 202)
        _, loaded = self._direct(
            "GET", f"/api/nodes/collect_keywords/agent-thread/batches/{started['batch_id']}"
        )
        batch = loaded["batch"]
        self.assertEqual(batch["progress"]["proposed_cells"], 0)
        self.assertIn("invalid_root_terms_rejected", batch["items"][0]["proposal_risks"])
        self.assertIn("invalid_demand_type_rejected", batch["items"][0]["proposal_risks"])
        self.assertNotIn("patch_outside_selection_rejected", batch["items"][0]["proposal_risks"])

    def test_agent_batch_uses_only_page_two_rows_and_one_product_per_prompt(self):
        self._write_collaboration_fixture()
        table_path = self.app_root / "artifacts" / "collect_top_products.data_table.json"
        table = json.loads(table_path.read_text(encoding="utf-8"))
        next(field for field in table["fields"] if field["field_name"] == "功能")["field_path"] = "items.properties.function"
        table["rows"] = [
            {
                "商品名": f"桌垫商品{i}",
                "goods_id": f"desk-{i}",
                "功能": "",
                "材质": "PVC",
                "场景": "办公桌",
                "主卖点": f"防滑卖点{i}",
            }
            for i in range(1, 13)
        ]
        table["row_meta"] = [
            {"row_id": f"goods:desk-{i}", "source_identity": f"desk-{i}"}
            for i in range(1, 13)
        ]
        table["derived_fields"] = [
            {"field_name": "功能", "evidence_field_paths": ["材质", "场景", "主卖点"]}
        ]
        table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")

        prompt_capture = self.app_root / "agent_batch_prompts.jsonl"
        proposal = {
            "schema_version": "pi-data-mapping-advice-v1",
            "node_id": "collect_top_products",
            "summary": {"status": "needs_review", "text": "批量建议"},
            "field_advice": [],
            "table_edit_proposal": {
                "schema_version": "data-table-edit-proposal-v1",
                "patches": [
                    {
                        "row_id": "desk-11",
                        "field_path": "items.properties.function",
                        "old_value": "",
                        "new_value": "防滑、桌面保护",
                        "reason": "材质、场景和主卖点证据",
                        "confidence": 0.9,
                        "evidence_refs": [],
                    }
                ],
            },
        }
        fake_pi = self.app_root / "fake_pi_agent_batch"
        fake_pi.write_text(
            "#!/usr/bin/env node\n"
            "const fs = require('fs');\n"
            "let request = '';\n"
            "process.stdin.setEncoding('utf8');\n"
            "process.stdin.once('data', chunk => { request += chunk;\n"
            f"  fs.appendFileSync({json.dumps(str(prompt_capture))}, request.trim() + '\\n');\n"
            f"  process.stdout.write({json.dumps(json.dumps({'type': 'agent_start', 'model': 'aicodemirror/gpt-5.6-sol'}))} + '\\n');\n"
            f"  process.stdout.write({json.dumps(json.dumps({'type': 'message_update', 'assistantMessageEvent': {'type': 'text_delta', 'delta': json.dumps(proposal, ensure_ascii=False)}}, ensure_ascii=False))} + '\\n');\n"
            "  process.stdout.write('{\"type\":\"agent_end\",\"messages\":[],\"willRetry\":false}\\n');\n"
            "});\n",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)

        status, started = self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/batches",
            {"base_revision": 0, "page_number": 2, "page_size": 10},
            env_extra={
                "PI_BIN": str(fake_pi),
                "AICODEMIRROR_API_KEY": "sk-test",
                "PI_DEFAULT_MODEL": "aicodemirror/gpt-5.6-sol",
                "PI_RPC_TIMEOUT_MS": "3000",
            },
        )
        self.assertEqual(status, 202)
        self.assertEqual(started["batch"]["page"]["row_ids"], ["goods:desk-11", "goods:desk-12"])

        loaded = {}
        status = 0
        for _ in range(60):
            status, loaded = self._direct(
                "GET",
                f"/api/nodes/collect_top_products/agent-thread/batches/{started['batch_id']}",
            )
            if loaded.get("batch", {}).get("status") == "review_ready":
                break
            time.sleep(0.05)
        self.assertEqual(status, 200)
        batch = loaded["batch"]
        self.assertEqual(batch["schema_version"], "analysis-agent-batch-v1")
        self.assertEqual(batch["status"], "review_ready")
        self.assertEqual(batch["progress"]["eligible_products"], 2)
        self.assertEqual(batch["progress"]["completed_products"], 2)
        self.assertEqual(batch["progress"]["proposed_cells"], 1)
        accepted_item = next(item for item in batch["items"] if item["row_id"] == "goods:desk-11")
        self.assertEqual(accepted_item["raw_patch_count"], 1)
        self.assertEqual(accepted_item["accepted_patch_count"], 1)
        self.assertEqual(accepted_item["proposal_status"], "completed_with_proposals")
        rejected_item = next(item for item in batch["items"] if item["row_id"] == "goods:desk-12")
        self.assertEqual(rejected_item["raw_patch_count"], 1)
        self.assertEqual(rejected_item["accepted_patch_count"], 0)
        self.assertEqual(rejected_item["proposal_status"], "completed_no_applicable_patch")
        self.assertIn("patch_outside_selection_rejected", rejected_item["proposal_risks"])
        self.assertEqual(batch["progress"]["rejected_cells"], 1)
        prompts = [json.loads(line)["message"] for line in prompt_capture.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(prompts), 2)
        prompt_by_row = {
            row_id: next(prompt for prompt in prompts if f'"row_id": "{row_id}"' in prompt)
            for row_id in ["goods:desk-11", "goods:desk-12"]
        }
        self.assertNotIn('"row_id": "goods:desk-12"', prompt_by_row["goods:desk-11"])
        self.assertNotIn('"row_id": "goods:desk-11"', prompt_by_row["goods:desk-12"])
        self.assertIn('"材质": "PVC"', prompt_by_row["goods:desk-11"])
        self.assertIn('"场景": "办公桌"', prompt_by_row["goods:desk-11"])
        self.assertIn('"主卖点": "防滑卖点11"', prompt_by_row["goods:desk-11"])
        self.assertNotIn("sk-test", json.dumps(batch, ensure_ascii=False))

    def test_agent_batch_apply_only_selected_proposals_and_marks_remaining_proposals_stale(self):
        self._write_collaboration_fixture()
        artifacts = self.app_root / "artifacts"
        batch_id = "batch-review-1"
        batch = {
            "schema_version": "analysis-agent-batch-v1",
            "batch_id": batch_id,
            "node_id": "collect_top_products",
            "base_revision": 0,
            "status": "review_ready",
            "requested_model": "aicodemirror/gpt-5.6-sol",
            "page": {"number": 1, "size": 10, "row_ids": ["goods:desk-1"]},
            "progress": {"eligible_products": 1, "completed_products": 1, "target_cells": 2, "proposed_cells": 2},
            "items": [],
            "proposals": [
                {"proposal_id": "batch-proposal-1", "row_id": "goods:desk-1", "field_path": "功能", "old_value": "", "new_value": "防滑", "reason": "卖点证据", "confidence": 0.9, "evidence_refs": [], "status": "pending"},
                {"proposal_id": "batch-proposal-2", "row_id": "goods:desk-1", "field_path": "商品主图", "old_value": "https://fixture.test/desk-1.jpg", "new_value": "伪造值", "reason": "不应覆盖", "confidence": 0.9, "evidence_refs": [], "status": "pending"},
            ],
        }
        (artifacts / f"collect_top_products.agent_batch.{batch_id}.json").write_text(
            json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        status, applied = self._direct(
            "POST",
            f"/api/nodes/collect_top_products/agent-thread/batches/{batch_id}/apply",
            {"base_revision": 0, "proposal_ids": ["batch-proposal-1"]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(applied["table_workspace"]["effective_rows"][0]["功能"], "防滑")
        self.assertEqual(applied["table_workspace"]["effective_rows"][0]["商品主图"], "https://fixture.test/desk-1.jpg")
        override = applied["table_workspace"]["workspace"]["cell_overrides"]["goods:desk-1"]["功能"]
        self.assertEqual(override["source_kind"], "pi_derived")
        self.assertEqual(override["batch_id"], batch_id)

        status, conflict = self._direct(
            "POST",
            f"/api/nodes/collect_top_products/agent-thread/batches/{batch_id}/apply",
            {"base_revision": 0, "proposal_ids": ["batch-proposal-2"]},
        )
        self.assertEqual(status, 409)
        self.assertEqual(conflict["error"], "agent_batch_stale")
        self.assertEqual(conflict["base_revision"], 0)
        self.assertEqual(conflict["current_revision"], 1)

        status, loaded = self._direct(
            "GET",
            f"/api/nodes/collect_top_products/agent-thread/batches/{batch_id}",
        )
        self.assertEqual(status, 200)
        self.assertEqual(loaded["batch"]["status"], "stale")
        self.assertEqual(loaded["batch"]["previous_status"], "review_ready")
        self.assertEqual(loaded["batch"]["freshness_status"], "stale")
        remaining = next(
            proposal for proposal in loaded["batch"]["proposals"]
            if proposal["proposal_id"] == "batch-proposal-2"
        )
        self.assertEqual(remaining["status"], "stale")

    def test_agent_batch_response_marks_rerun_batch_stale_and_excludes_it_from_enrichment_status(self):
        self._write_keyword_collaboration_fixture(count=1)
        status, workspace_payload = self._direct(
            "GET", "/api/nodes/collect_keywords/data-table-workspace"
        )
        self.assertEqual(status, 200)
        workspace = workspace_payload["workspace"]
        self.assertEqual(workspace["revision"], 0)

        artifacts = self.app_root / "artifacts"
        batch_id = "batch-keyword-before-rerun"
        batch = {
            "schema_version": "analysis-agent-batch-v1",
            "batch_id": batch_id,
            "node_id": "collect_keywords",
            "base_revision": 0,
            "base_execution_id": workspace["base_execution_id"],
            "status": "review_ready",
            "subject_kind": "keyword",
            "requested_model": "aicodemirror/gpt-5.6-sol",
            "page": {"number": 1, "size": 10, "row_ids": ["keyword:防水桌布1"]},
            "progress": {"eligible_products": 1, "completed_products": 1, "target_cells": 2, "proposed_cells": 2},
            "items": [],
            "proposals": [
                {"proposal_id": "keyword-proposal-root", "row_id": "keyword:防水桌布1", "field_path": "root_terms", "old_value": [], "new_value": ["防水", "桌布"], "status": "pending"},
                {"proposal_id": "keyword-proposal-demand", "row_id": "keyword:防水桌布1", "field_path": "demand_type", "old_value": "", "new_value": "功能需求", "status": "pending"},
            ],
        }
        (artifacts / f"collect_keywords.agent_batch.{batch_id}.json").write_text(
            json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        thread = {
            "schema_version": "analysis-collaboration-thread-v1",
            "node_id": "collect_keywords",
            "revision": 0,
            "messages": [],
            "agent_calls": [],
            "agent_batches": [{
                "batch_id": batch_id,
                "schema_version": "analysis-agent-batch-v1",
                "status": "review_ready",
                "base_revision": 0,
                "base_execution_id": workspace["base_execution_id"],
                "page": batch["page"],
                "progress": batch["progress"],
            }],
            "preferred_model": "aicodemirror/gpt-5.6-sol",
        }
        (artifacts / "collect_keywords.agent_thread.json").write_text(
            json.dumps(thread, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        table_path = artifacts / "collect_keywords.data_table.json"
        table = json.loads(table_path.read_text(encoding="utf-8"))
        table["execution_id"] = "exec-keyword-fixture-2"
        table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")

        status, current_workspace = self._direct(
            "GET", "/api/nodes/collect_keywords/data-table-workspace"
        )
        self.assertEqual(status, 200)
        self.assertEqual(current_workspace["workspace"]["revision"], 1)
        self.assertEqual(
            current_workspace["agent_enrichment"]["status"],
            "agent_enrichment_pending",
        )

        status, loaded = self._direct(
            "GET", f"/api/nodes/collect_keywords/agent-thread/batches/{batch_id}"
        )
        self.assertEqual(status, 200)
        stale = loaded["batch"]
        self.assertEqual(stale["status"], "stale")
        self.assertEqual(stale["previous_status"], "review_ready")
        self.assertEqual(stale["freshness_status"], "stale")
        self.assertEqual(stale["stale_reason"], "source_execution_changed")
        self.assertEqual(stale["current_revision"], 1)
        self.assertEqual(stale["current_execution_id"], "exec-keyword-fixture-2")
        self.assertTrue(all(item["status"] == "stale" for item in stale["proposals"]))

        status, rejected = self._direct(
            "POST",
            f"/api/nodes/collect_keywords/agent-thread/batches/{batch_id}/apply",
            {"base_revision": 1, "proposal_ids": ["keyword-proposal-root"]},
        )
        self.assertEqual(status, 409)
        self.assertEqual(rejected["error"], "agent_batch_stale")
        self.assertEqual(rejected["base_execution_id"], "exec-keyword-fixture-1")
        self.assertEqual(rejected["current_execution_id"], "exec-keyword-fixture-2")

    def test_new_agent_batch_binds_current_workspace_execution(self):
        self._write_keyword_collaboration_fixture(count=1)
        status, started = self._direct(
            "POST",
            "/api/nodes/collect_keywords/agent-thread/batches",
            {"base_revision": 0, "page_number": 1, "page_size": 10},
            env_extra={"PI_BIN": "/bin/false", "PI_RPC_TIMEOUT_MS": "100"},
        )
        self.assertEqual(status, 202)
        batch = started["batch"]
        self.assertEqual(batch["base_execution_id"], "exec-keyword-fixture-1")
        self.assertEqual(batch["freshness_status"], "current")
        self.assertEqual(batch["current_revision"], 0)
        self.assertEqual(batch["current_execution_id"], "exec-keyword-fixture-1")

    def test_agent_thread_cell_query_only_sends_selected_rows_to_pi(self):
        self._write_collaboration_fixture()
        prompt_capture = self.app_root / "agent_cell_context_prompt.jsonl"
        event = {
            "type": "message_update",
            "assistantMessageEvent": {
                "type": "text_delta",
                "delta": json.dumps(
                    {
                        "schema_version": "pi-data-mapping-advice-v1",
                        "node_id": "collect_top_products",
                        "summary": {"status": "needs_review", "text": "请审核建议"},
                        "field_advice": [],
                        "table_edit_proposal": {"schema_version": "data-table-edit-proposal-v1", "patches": []},
                    },
                    ensure_ascii=False,
                ),
            },
        }
        fake_pi = self.app_root / "fake_pi_cell_context_prompt"
        fake_pi.write_text(
            f"#!/bin/sh\nIFS= read -r _request\nprintf '%s\\n' \"$_request\" > {shlex.quote(str(prompt_capture))}\nprintf '%s\\n' {shlex.quote(json.dumps(event, ensure_ascii=False))}\nprintf '%s\\n' '{{\"type\":\"agent_end\",\"messages\":[],\"willRetry\":false}}'\n",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)

        self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/context",
            {"context_type": "cell_context", "row_id": "goods:desk-1", "field_path": "功能"},
        )
        status, _ = self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/query",
            {"message": "补齐这个单元格"},
            env_extra={"PI_BIN": str(fake_pi), "AICODEMIRROR_API_KEY": "sk-test", "PI_RPC_TIMEOUT_MS": "3000"},
        )
        self.assertEqual(status, 200)
        prompt = json.loads(prompt_capture.read_text(encoding="utf-8"))["message"]
        self.assertIn('"row_id": "goods:desk-1"', prompt)
        self.assertNotIn('"row_id": "goods:desk-2"', prompt)

    def test_agent_thread_action_applies_cell_proposal_and_rejects_stale_revision(self):
        self._write_collaboration_fixture()
        store_path = self.app_root / "artifacts" / "collect_top_products.agent_thread.json"
        store_path.parent.mkdir(exist_ok=True)
        store_path.write_text(
            json.dumps(
                {
                    "schema_version": "analysis-collaboration-thread-v1",
                    "node_id": "collect_top_products",
                    "revision": 1,
                    "messages": [
                        {
                            "message_id": "assistant-proposal-1",
                            "role": "assistant",
                            "text": "建议补齐防滑",
                            "intent": "cell_context",
                            "table_revision": 0,
                            "proposal_status": "pending",
                            "proposal": {
                                "schema_version": "data-table-edit-proposal-v1",
                                "proposal_id": "chat-proposal-1",
                                "workspace_revision": 0,
                                "patches": [
                                    {
                                        "operation": "set_cell",
                                        "row_id": "goods:desk-1",
                                        "field_path": "功能",
                                        "old_value": "",
                                        "new_value": "防滑",
                                        "reason": "详情证据",
                                        "confidence": 0.9,
                                        "evidence_refs": [],
                                    }
                                ],
                            },
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        status, applied = self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/action",
            {"action": "apply_cell_proposal", "message_id": "assistant-proposal-1", "patch_indices": [0]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(applied["table_workspace"]["effective_rows"][0]["功能"], "防滑")
        self.assertEqual(applied["thread"]["messages"][0]["proposal_status"], "applied")

        store = json.loads(store_path.read_text(encoding="utf-8"))
        stale_message = dict(store["messages"][0])
        stale_message["message_id"] = "assistant-proposal-stale"
        stale_message["proposal_status"] = "pending"
        stale_message["table_revision"] = 0
        stale_message["proposal"] = dict(stale_message["proposal"], proposal_id="chat-proposal-stale", workspace_revision=0)
        store["messages"].append(stale_message)
        store_path.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")

        status, stale = self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/action",
            {"action": "apply_cell_proposal", "message_id": "assistant-proposal-stale", "patch_indices": [0]},
        )
        self.assertEqual(status, 409)
        self.assertEqual(stale["error"], "revision_conflict")

    def test_agent_thread_cell_proposal_can_apply_multiple_patches_incrementally(self):
        self._write_collaboration_fixture()
        thread_path = self.app_root / "artifacts" / "collect_top_products.agent_thread.json"
        thread_path.parent.mkdir(exist_ok=True)
        thread_path.write_text(
            json.dumps(
                {
                    "schema_version": "analysis-collaboration-thread-v1",
                    "node_id": "collect_top_products",
                    "revision": 1,
                    "messages": [
                        {
                            "message_id": "multi-cell-proposal",
                            "role": "assistant",
                            "text": "两项建议",
                            "intent": "cell_context",
                            "table_revision": 0,
                            "proposal_status": "pending",
                            "proposal": {
                                "schema_version": "data-table-edit-proposal-v1",
                                "proposal_id": "multi-proposal-1",
                                "workspace_revision": 0,
                                "patches": [
                                    {"operation": "set_cell", "row_id": "goods:desk-1", "field_path": "功能", "old_value": "", "new_value": "防滑", "reason": "证据1"},
                                    {"operation": "set_cell", "row_id": "goods:desk-2", "field_path": "功能", "old_value": "防水", "new_value": "防水、防滑", "reason": "证据2"},
                                ],
                            },
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        status, first = self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/action",
            {"action": "apply_cell_proposal", "message_id": "multi-cell-proposal", "patch_indices": [0]},
        )
        self.assertEqual(status, 200)
        message = first["thread"]["messages"][0]
        self.assertEqual(message["proposal_status"], "partially_applied")
        self.assertEqual(message["table_revision"], 1)

        status, second = self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/action",
            {"action": "apply_cell_proposal", "message_id": "multi-cell-proposal", "patch_indices": [1]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(second["thread"]["messages"][0]["proposal_status"], "applied")
        self.assertEqual(second["table_workspace"]["effective_rows"][0]["功能"], "防滑")
        self.assertEqual(second["table_workspace"]["effective_rows"][1]["功能"], "防水、防滑")

    def test_agent_thread_can_ignore_remaining_patches_after_partial_application(self):
        self._write_collaboration_fixture()
        thread_path = self.app_root / "artifacts" / "collect_top_products.agent_thread.json"
        thread_path.parent.mkdir(exist_ok=True)
        thread_path.write_text(
            json.dumps(
                {
                    "schema_version": "analysis-collaboration-thread-v1",
                    "node_id": "collect_top_products",
                    "revision": 2,
                    "messages": [
                        {
                            "message_id": "partial-proposal",
                            "role": "assistant",
                            "text": "部分已应用",
                            "intent": "cell_context",
                            "table_revision": 1,
                            "proposal_status": "partially_applied",
                            "applied_patch_indices": [0],
                            "proposal": {
                                "schema_version": "data-table-edit-proposal-v1",
                                "proposal_id": "partial-proposal-1",
                                "workspace_revision": 1,
                                "patches": [
                                    {"row_id": "goods:desk-1", "field_path": "功能", "old_value": "", "new_value": "防滑"},
                                    {"row_id": "goods:desk-2", "field_path": "功能", "old_value": "防水", "new_value": "防水、防滑"},
                                ],
                            },
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        _, initial = self._direct("GET", "/api/nodes/collect_top_products/data-table-workspace")
        self._direct(
            "POST",
            "/api/nodes/collect_top_products/data-table-workspace/patch",
            {
                "schema_version": "data-table-edit-patch-v1",
                "base_revision": initial["workspace"]["revision"],
                "operations": [
                    {"operation": "set_cell", "row_id": "goods:desk-1", "field_path": "功能", "expected_value": "", "new_value": "防滑", "source_kind": "pi_derived"}
                ],
            },
        )

        status, ignored = self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/action",
            {"action": "ignore_proposal", "message_id": "partial-proposal"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(ignored["thread"]["messages"][0]["proposal_status"], "partially_applied_ignored")

    def test_agent_thread_insight_action_saves_draft_then_requires_evidence_to_confirm(self):
        self._write_collaboration_fixture()
        thread_path = self.app_root / "artifacts" / "collect_top_products.agent_thread.json"
        thread_path.parent.mkdir(exist_ok=True)
        thread_path.write_text(
            json.dumps(
                {
                    "schema_version": "analysis-collaboration-thread-v1",
                    "node_id": "collect_top_products",
                    "revision": 1,
                    "messages": [
                        {
                            "message_id": "insight-message-1",
                            "role": "assistant",
                            "text": "桌垫为主要产品类型。",
                            "intent": "insight_requirement",
                            "requirement_id": "insight_1",
                            "table_revision": 0,
                            "proposal_status": "pending",
                            "proposal": {
                                "schema_version": "insight-edit-proposal-v1",
                                "proposal_id": "insight-chat-proposal-1",
                                "requirement_id": "insight_1",
                                "proposed_text": "桌垫为主要产品类型。",
                                "evidence_bindings": [{"kind": "field", "field_path": "产品类型"}],
                                "risks": [],
                                "questions_for_user": [],
                            },
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        status, saved = self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/action",
            {
                "action": "save_insight_draft",
                "message_id": "insight-message-1",
                "requirement_id": "insight_1",
                "draft_text": "桌垫为主要产品类型。",
                "evidence_bindings": [{"kind": "field", "field_path": "产品类型"}],
            },
        )
        self.assertEqual(status, 200)
        block = saved["insight_workspace"]["workspace"]["blocks"][0]
        self.assertEqual(block["status"], "draft_ready")
        self.assertEqual(block["human_confirmation"]["status"], "unconfirmed")
        self.assertEqual(saved["thread"]["messages"][0]["proposal_status"], "saved_as_draft")

        status, confirmed = self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/action",
            {"action": "confirm_insight", "message_id": "insight-message-1", "requirement_id": "insight_1"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(confirmed["insight_workspace"]["block"]["status"], "confirmed")

        _, table = self._direct("GET", "/api/nodes/collect_top_products/data-table-workspace")
        self._direct(
            "POST",
            "/api/nodes/collect_top_products/data-table-workspace/patch",
            {
                "schema_version": "data-table-edit-patch-v1",
                "base_revision": table["workspace"]["revision"],
                "operations": [
                    {
                        "operation": "set_cell",
                        "row_id": "goods:desk-1",
                        "field_path": "产品类型",
                        "expected_value": "桌垫",
                        "new_value": "异形桌垫",
                        "source_kind": "manual",
                    }
                ],
            },
        )
        _, insight = self._direct("GET", "/api/nodes/collect_top_products/insight-workspace")
        self.assertEqual(insight["workspace"]["blocks"][0]["status"], "stale")

    def test_agent_thread_rejects_insight_proposal_after_table_revision_changes(self):
        self._write_collaboration_fixture()
        thread_path = self.app_root / "artifacts" / "collect_top_products.agent_thread.json"
        thread_path.parent.mkdir(exist_ok=True)
        thread_path.write_text(
            json.dumps(
                {
                    "schema_version": "analysis-collaboration-thread-v1",
                    "node_id": "collect_top_products",
                    "revision": 1,
                    "messages": [
                        {
                            "message_id": "stale-insight-message",
                            "role": "assistant",
                            "text": "旧数据结论",
                            "intent": "insight_requirement",
                            "requirement_id": "insight_1",
                            "table_revision": 0,
                            "proposal_status": "pending",
                            "proposal": {
                                "schema_version": "insight-edit-proposal-v1",
                                "requirement_id": "insight_1",
                                "proposed_text": "桌垫为主要类型。",
                                "evidence_bindings": [{"kind": "field", "field_path": "产品类型"}],
                            },
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        _, table = self._direct("GET", "/api/nodes/collect_top_products/data-table-workspace")
        self._direct(
            "POST",
            "/api/nodes/collect_top_products/data-table-workspace/patch",
            {
                "schema_version": "data-table-edit-patch-v1",
                "base_revision": table["workspace"]["revision"],
                "operations": [
                    {"operation": "set_cell", "row_id": "goods:desk-1", "field_path": "产品类型", "expected_value": "桌垫", "new_value": "异形桌垫", "source_kind": "manual"}
                ],
            },
        )

        status, stale = self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/action",
            {"action": "save_insight_draft", "message_id": "stale-insight-message", "requirement_id": "insight_1"},
        )
        self.assertEqual(status, 409)
        self.assertEqual(stale["error"], "revision_conflict")

    def test_agent_thread_caps_messages_at_200_and_pi_history_at_20(self):
        self._write_collaboration_fixture()
        thread_path = self.app_root / "artifacts" / "collect_top_products.agent_thread.json"
        thread_path.parent.mkdir(exist_ok=True)
        thread_path.write_text(
            json.dumps(
                {
                    "schema_version": "analysis-collaboration-thread-v1",
                    "node_id": "collect_top_products",
                    "revision": 201,
                    "messages": [
                        {"message_id": f"m-{index}", "role": "user", "text": f"历史消息 {index}", "intent": "free_chat"}
                        for index in range(201)
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        prompt_capture = self.app_root / "agent_thread_prompt.txt"
        fake_pi = self.app_root / "fake_pi_thread_history"
        response = {
            "type": "message_update",
            "assistantMessageEvent": {
                "type": "text_delta",
                "delta": json.dumps(
                    {
                        "schema_version": "pi-data-mapping-advice-v1",
                        "node_id": "collect_top_products",
                        "summary": {"status": "needs_review", "text": "ok"},
                        "field_advice": [],
                    },
                    ensure_ascii=False,
                ),
            },
        }
        fake_pi.write_text(
            f"#!/bin/sh\nIFS= read -r _request\nprintf '%s\\n' \"$_request\" > {shlex.quote(str(prompt_capture))}\nprintf '%s\\n' {shlex.quote(json.dumps(response, ensure_ascii=False))}\nprintf '%s\\n' '{{\"type\":\"agent_end\",\"messages\":[],\"willRetry\":false}}'\n",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)

        status, queried = self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/query",
            {"message": "继续分析"},
            env_extra={"PI_BIN": str(fake_pi), "AICODEMIRROR_API_KEY": "sk-test", "PI_RPC_TIMEOUT_MS": "3000"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(queried["thread"]["messages"]), 200)
        prompt = json.loads(prompt_capture.read_text(encoding="utf-8"))["message"]
        self.assertNotIn("历史消息 180", prompt)
        self.assertIn("历史消息 200", prompt)

        history = json.loads((self.app_root / "evidence" / "collect_top_products.agent_thread_history.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(history["records"]), 2)

    def test_agent_thread_free_chat_uses_data_analysis_context_not_mapping_flow(self):
        self._write_collaboration_fixture()
        table_path = self.app_root / "artifacts" / "collect_top_products.data_table.json"
        table = json.loads(table_path.read_text(encoding="utf-8"))
        table["fields"].extend(
            [
                {"field_path": "材质", "field_name": "材质", "title": "材质", "type": "string", "required": True},
                {"field_path": "场景", "field_name": "场景", "title": "场景", "type": "string", "required": True},
                {"field_path": "主卖点", "field_name": "主卖点", "title": "主卖点", "type": "string", "required": True},
            ]
        )
        table["rows"][0].update({"材质": "硅藻泥", "场景": "玄关", "主卖点": "吸水防滑且易清洁"})
        table_path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
        prompt_capture = self.app_root / "agent_free_chat_prompt.txt"
        fake_pi = self.app_root / "fake_pi_free_chat"
        event = {
            "type": "message_update",
            "assistantMessageEvent": {
                "type": "text_delta",
                "delta": json.dumps(
                    {
                        "schema_version": "pi-data-mapping-advice-v1",
                        "node_id": "collect_top_products",
                        "summary": {"status": "needs_review", "text": "请说明希望分析的业务问题。"},
                        "field_advice": [],
                    },
                    ensure_ascii=False,
                ),
            },
        }
        fake_pi.write_text(
            f"#!/bin/sh\nIFS= read -r _request\nprintf '%s\\n' \"$_request\" > {shlex.quote(str(prompt_capture))}\nprintf '%s\\n' {shlex.quote(json.dumps(event, ensure_ascii=False))}\nprintf '%s\\n' '{{\"type\":\"agent_end\",\"messages\":[],\"willRetry\":false}}'\n",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)

        status, response = self._direct(
            "POST",
            "/api/nodes/collect_top_products/agent-thread/query",
            {"message": "这批商品还有哪些值得关注的异常？"},
            env_extra={"PI_BIN": str(fake_pi), "AICODEMIRROR_API_KEY": "sk-test", "PI_RPC_TIMEOUT_MS": "3000"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(response["thread"]["messages"][-1]["intent"], "free_chat")
        prompt = json.loads(prompt_capture.read_text(encoding="utf-8"))["message"]
        self.assertIn("意图：free_chat", prompt)
        self.assertIn("当前数据表协作工作区", prompt)
        self.assertIn("当前数据表有效数据", prompt)
        self.assertIn('"row_id": "goods:desk-1"', prompt)
        self.assertIn("吸水防滑且易清洁", prompt)
        self.assertIn("这批商品还有哪些值得关注的异常", prompt)

    def test_table_agent_proposal_is_pending_until_explicit_application(self):
        self._write_collaboration_fixture()
        _, initial = self._direct("GET", "/api/nodes/collect_top_products/data-table-workspace")
        status, proposed = self._direct(
            "POST",
            "/api/nodes/collect_top_products/data-table-workspace/proposal",
            {
                "base_revision": initial["workspace"]["revision"],
                "proposal": {
                    "schema_version": "data-table-edit-proposal-v1",
                    "proposal_id": "table-proposal-1",
                    "patches": [
                        {"operation": "set_cell", "row_id": "goods:desk-1", "field_path": "功能", "old_value": "", "new_value": "防滑", "reason": "卖点证据", "confidence": 0.9}
                    ],
                    "summary": "补齐功能",
                },
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(proposed["effective_rows"][0]["功能"], "")
        self.assertEqual(proposed["workspace"]["pending_agent_proposals"][0]["status"], "pending")

        status, applied = self._direct(
            "POST",
            "/api/nodes/collect_top_products/data-table-workspace/patch",
            {
                "schema_version": "data-table-edit-patch-v1",
                "base_revision": proposed["workspace"]["revision"],
                "proposal_id": "table-proposal-1",
                "proposal_patch_indices": [0],
                "operations": [
                    {"operation": "set_cell", "row_id": "goods:desk-1", "field_path": "功能", "expected_value": "", "new_value": "防滑", "source_kind": "pi_derived", "reason": "卖点证据", "confidence": 0.9}
                ],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(applied["effective_rows"][0]["功能"], "防滑")
        self.assertEqual(applied["workspace"]["pending_agent_proposals"][0]["status"], "applied")

    def test_legacy_pi_collaboration_intents_keep_compatibility_fallback(self):
        self._write_collaboration_fixture()
        status, table = self._direct(
            "POST",
            "/api/pi-agent/query",
            {
                "node_id": "collect_top_products",
                "intent": "table_edit_advice",
                "table_workspace": {"revision": 0, "fields": [{"field_path": "功能"}], "row_meta": [{"row_id": "goods:desk-1"}]},
                "table_selection": {"scope_mode": "cells", "cells": [{"row_id": "goods:desk-1", "field_path": "功能", "effective_value": ""}]},
            },
            env_extra={"PI_BIN": str(self.app_root / "missing-pi")},
        )
        self.assertEqual(status, 200)
        self.assertEqual(table["advice"]["table_edit_proposal"]["schema_version"], "data-table-edit-proposal-v1")
        self.assertEqual(table["advice"]["table_edit_proposal"]["patches"], [])

        status, insight = self._direct(
            "POST",
            "/api/pi-agent/query",
            {
                "node_id": "collect_top_products",
                "intent": "insight_collaboration",
                "selected_requirement": {"requirement_id": "insight_1", "question": "当前行业热卖产品分为哪几类？"},
                "table_workspace": {"revision": 0, "fields": [{"field_path": "产品类型"}], "row_meta": [{"row_id": "goods:desk-1"}]},
            },
            env_extra={"PI_BIN": str(self.app_root / "missing-pi")},
        )
        self.assertEqual(status, 200)
        self.assertEqual(insight["advice"]["insight_collaboration_proposal"]["schema_version"], "insight-edit-proposal-v1")
        self.assertEqual(insight["advice"]["insight_collaboration_proposal"]["status"], "needs_evidence")

    def test_pi_insight_collaboration_rejects_unknown_evidence_references(self):
        self._write_collaboration_fixture()
        proposal = {
            "schema_version": "pi-data-mapping-advice-v1",
            "node_id": "collect_top_products",
            "summary": {"status": "needs_review", "text": "结论建议"},
            "field_advice": [],
            "insight_collaboration_proposal": {
                "requirement_id": "insight_1",
                "proposed_text": "未知字段支持该结论。",
                "evidence_bindings": [
                    {"kind": "row", "row_id": "goods:not-found", "field_path": "不存在字段"}
                ],
            },
        }
        event = {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": json.dumps(proposal, ensure_ascii=False)}}
        fake_pi = self.app_root / "fake_pi_insight_edit"
        fake_pi.write_text(
            "#!/bin/sh\nIFS= read -r _request\nprintf '%s\\n' "
            + shlex.quote(json.dumps(event, ensure_ascii=False))
            + "\nprintf '%s\\n' '{\"type\":\"agent_end\",\"messages\":[],\"willRetry\":false}'\n",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)

        status, data = self._direct(
            "POST",
            "/api/pi-agent/query",
            {
                "node_id": "collect_top_products",
                "intent": "insight_collaboration",
                "message": "形成第一条结论",
                "selected_requirement": {"requirement_id": "insight_1", "question": "当前行业热卖产品分为哪几类？"},
                "table_workspace": {
                    "revision": 0,
                    "fields": [{"field_path": "产品类型"}, {"field_path": "功能"}],
                    "row_meta": [{"row_id": "goods:desk-1"}, {"row_id": "goods:desk-2"}],
                },
                "evidence_summary": {"insight_1": []},
            },
            env_extra={"PI_BIN": str(fake_pi), "AICODEMIRROR_API_KEY": "sk-test", "PI_RPC_TIMEOUT_MS": "3000"},
        )
        self.assertEqual(status, 200)
        insight_proposal = data["advice"]["insight_collaboration_proposal"]
        self.assertEqual(insight_proposal["status"], "invalid_evidence")
        self.assertEqual(insight_proposal["evidence_bindings"], [])
        self.assertIn("unknown_evidence_reference_rejected", insight_proposal["risks"])
        self.assertTrue(insight_proposal["requires_human_application"])

    def _create_fake_spec_pack(self) -> Path:
        root = self.app_root / "fake-spec-pack"
        (root / "scripts").mkdir(parents=True)
        (root / "src" / "tools").mkdir(parents=True)
        (root / "scripts" / "ts_loader.mjs").write_text("", encoding="utf-8")
        (root / "src" / "tools" / "select_tools_for_task.mjs").write_text(
            """
export function selectToolsForTask(args) {
  return {
    task: args.task,
    intent: '类目 | 商品',
    recommended_tools: [
      {
        tool_id: 'auto_关键词域_关键词分析',
        call_order: 1,
        reason: 'first fixture has no concrete API',
        required_params: ['category_id'],
        missing_params: ['category_id'],
        source_apis: [],
        quality_score: 0.5,
        risks: []
      },
      {
        tool_id: 'auto_商品域_商品分析',
        call_order: 2,
        reason: 'fake fixture match',
        required_params: ['category', 'period'],
        missing_params: [],
        source_apis: ['/api/category/top-products'],
        quality_score: 0.91,
        risks: []
      }
    ],
    blocked_or_deprioritized: [],
    next_question: '已就绪，可直接调用。'
  };
}
""",
            encoding="utf-8",
        )
        (root / "src" / "tools" / "probe_api_sample.mjs").write_text(
            """
const detailAttempts = new Map();
export async function probeApiSampleTool(args) {
  const top = Number(args.top || 10);
  if (args.api_id === 'data_goods_ads_ind_goods_detail_info_m') {
    const goodsId = String(args.params && args.params.goods_id || '');
    const dataSource = String(args.params && args.params.data_source || '');
    const attempts = (detailAttempts.get(goodsId) || 0) + 1;
    detailAttempts.set(goodsId, attempts);
    if (process.env.TEST_DETAIL_RETRY === '1' && goodsId === 'desk-2' && attempts === 1) {
      return {
        kind: 'api_probe_result', api_id: args.api_id, method: 'POST', path: args.api_id,
        request: { url: `https://fixture.test/detail?goods_id=${goodsId}`, query: args.params || {}, body: {}, headers_keys: [], auth_inject: {} },
        status: { state: 'timeout', elapsed_ms: 10 },
        response: { total: 0, truncated: false, top: [] }
      };
    }
    let rows = process.env.TEST_DETAIL_PARTIAL === '1' && goodsId === 'desk-3'
      ? []
      : [{
          goods_id: goodsId,
          goods_name: `桌布详情 ${goodsId}`,
          core_material: goodsId === 'desk-1' ? '硅藻泥' : 'PVC',
          usage_scene: '\\n 家用  玄关 \\n',
          selling_point_summary: '防水防滑易清洁',
          goods_spec_params: '加厚款',
          goods_img: `https://item.taobao.com/item.htm?id=${goodsId}`
        }];
    if (process.env.TEST_DETAIL_QBT_EMPTY === '1' && dataSource === 'qbt') rows = [];
    if (process.env.TEST_DETAIL_DATED_ROWS === '1' && dataSource === 'sycm') {
      rows = [
        { goods_id: goodsId, statist_date: '2026-04-01', core_material: 'PVC-April', usage_scene: '四月场景' },
        { goods_id: goodsId, statist_date: '2026-05-01', core_material: 'PVC-May', usage_scene: '五月场景' }
      ];
    }
    if (process.env.TEST_DETAIL_LARGE_PAYLOAD === '1') {
      rows = rows.map(row => ({ ...row, large_blob: 'x'.repeat(40000) }));
    }
    return {
      kind: 'api_probe_result', api_id: args.api_id, method: 'POST', path: args.api_id,
      request: { url: `https://fixture.test/detail?goods_id=${goodsId}`, query: args.params || {}, body: {}, headers_keys: [], auth_inject: {} },
      status: { state: 'ok', http: 200, elapsed_ms: 2 },
      response: { total: rows.length, truncated: rows.length > top, top: rows.slice(0, top) }
    };
  }
  if (args.api_id === 'category_resolver_api') {
    if (process.env.TEST_RESOLVER_FAIL === '1') {
      throw new Error('fixture resolver request failed');
    }
    const resolverRows = process.env.TEST_RESOLVER_BLANK_NAME === '1'
      ? [
          { cate_name: '', cate_id: 'wrong-empty-name-id' },
          { cate_name: '空名称边界类目', cate_id: 'correct-category-id' }
        ]
      : [
          { cate_name: '沙发垫', cate_id: '50020776' },
          { cate_name: '桌垫', cate_id: '50030001' }
        ];
    const secret = process.env.ZICHEN_APP_CODE_KEY || '';
    return {
      kind: 'api_probe_result',
      api_id: args.api_id,
      method: 'POST',
      path: args.api_id,
      mode: 'fake_probe',
      request: {
        url: `https://fixture.test${args.api_id}?resolver=1&app_code_key=${encodeURIComponent(secret)}`,
        query: { ...(args.params || {}), app_code_key: secret },
        body: null,
        headers_keys: [],
        auth_inject: { header: [], body: [], query: [{ name: 'app_code_key', value: secret }] }
      },
      status: { state: process.env.LIVE_PROBE === 'true' ? 'ok' : 'missing_live_probe_env' },
      response: {
        total: 2,
        truncated: false,
        top: resolverRows
      }
    };
  }
  if (args.api_id === 'agent_sycm_keyword' || args.api_id === 'agent_xiaowan_keywords') {
    const category = String(args.params && args.params.tertiary_category || '');
    const shouldReturnRows = process.env.TEST_KEYWORD_ALL_EMPTY !== '1' && category === '桌布';
    const rows = !shouldReturnRows
      ? []
      : args.api_id === 'agent_sycm_keyword'
        ? [{
            keywords: '防水桌布',
            search_popularity: '1200',
            search_growth_rate: '0.35',
            click_rate: '0.21',
            pay_rate: '0.06',
            tertiary_category: category
          }]
        : [{
            keyword: ' 防水桌布 ',
            competition_index: '320',
            click_rate: '0.19',
            conversion_rate: '0.05',
            tertiary_category: category
          }];
    return {
      kind: 'api_probe_result',
      api_id: args.api_id,
      method: 'POST',
      path: args.api_id,
      mode: 'fake_probe',
      request: {
        url: `https://fixture.test/${args.api_id}?tertiary_category=${encodeURIComponent(category)}`,
        query: { ...(args.params || {}) },
        body: { ...(args.params || {}) },
        headers_keys: [],
        auth_inject: {}
      },
      status: { state: 'ok', http: 200, elapsed_ms: 2 },
      response: { total: rows.length, truncated: false, top: rows }
    };
  }
  if (['get_positive_comment_data', 'product_comment_content2', 'product_question_content2'].includes(args.api_id)) {
    const goodsId = String(args.params && (args.params.goods_id || (args.params.goods_id_list || [])[0]) || '');
    const row = args.api_id === 'product_question_content2'
      ? { goods_id: goodsId, question_content: `问题-${goodsId}`, answer_count: '3' }
      : { goods_id: goodsId, comment: `${args.api_id === 'get_positive_comment_data' ? '好评' : '评论'}-${goodsId}` };
    return {
      kind: 'api_probe_result', api_id: args.api_id, method: 'POST', path: args.api_id,
      request: { url: `https://fixture.test/${args.api_id}`, query: args.params || {}, body: args.params || {}, headers_keys: [], auth_inject: {} },
      status: { state: 'ok', http: 200, elapsed_ms: 2 },
      response: { total: 1, truncated: false, top: [row] }
    };
  }
  if (args.api_id === 'data_shop_competition_pattern_analysis_v3') {
    const rows = process.env.TEST_COMPETITOR_EMPTY === '1'
      ? []
      : ['gene-2', 'gene-1'].map((goodsId, index) => ({
          goods_id: goodsId,
          shop_name: `竞品店铺-${goodsId}`,
          goods_href: `https://fixture.test/competitor/${goodsId}`,
          price: 80 + index,
          main_selling_point: `竞品卖点-${goodsId}`,
          main_sku: '大号',
          main_image_url: `https://fixture.test/competitor/${goodsId}.jpg`,
          main_color: '透明',
          sales_total: 1000 - index,
          sales_ratio: 0.2 - index * 0.01,
          cid: String(args.params && args.params.cid || ''),
          category_name: '桌布'
        }));
    return {
      kind: 'api_probe_result', api_id: args.api_id, method: 'POST', path: args.api_id,
      request: { url: `https://fixture.test/${args.api_id}`, query: args.params || {}, body: args.params || {}, headers_keys: [], auth_inject: {} },
      status: { state: 'ok', http: 200, elapsed_ms: 2 },
      response: { total: rows.length, truncated: false, top: rows }
    };
  }
  const secret = process.env.ZICHEN_APP_CODE_KEY || '';
  const rows = args.api_id === 'top300_product_analysis'
    ? Array.from({ length: Math.max(1, Math.min(top, 60)) }, (_, index) => ({
        rank: index + 1,
        commodity_id: `global-${index + 1}`,
        commodity: `抱枕 ${index + 1}`,
        requested_top: top,
        source_api_id: args.api_id
      }))
    : args.api_id === 'data_ads_ind_trade_category_goods_m'
      ? process.env.TEST_MONTHLY_LATEST_EMPTY === '1' && args.params && args.params.start_date === '2026-06-01'
        ? []
        : Array.from({ length: Math.max(1, Math.min(top, 60)) }, (_, index) => ({
            rank: index + 1,
            goods_id: `desk-${index + 1}`,
            goods_name: `桌布交易总量商品 ${index + 1}`,
            goods_url: `https://fixture.test/desk/${index + 1}`,
            goods_img: `https://fixture.test/desk/${index + 1}.jpg`,
            shop_name: `桌布店铺 ${index + 1}`,
            num_payers_interval: '1000 ~ 2000',
            sales_revenue: String(100000 - index),
            unit_price: String(99 - index),
            selling_point: '防水易清洁',
            category_name: '桌布',
            cid: String(args.params && args.params.cid || ''),
            statist_date: args.params && args.params.start_date,
            requested_top: top,
            source_api_id: args.api_id
          }))
    : args.api_id === 'data_ads_ind_sycm_speed_category_goods_m'
      ? Array.from({ length: Math.max(1, Math.min(top, 60)) }, (_, index) => ({
          rank: index + 1,
          last_month_rank: index + 1,
          speed_type: index < 5 ? '2' : '5',
          goods_id: `desk-${index + 1}`,
          goods_name: `桌垫商品 ${index + 1}`,
          goods_url: `https://fixture.test/desk/${index + 1}`,
          category_name: '桌布',
          cid: String(args.params && args.params.cid || ''),
          requested_top: top,
          requested_page_size: args.params && args.params.pageSize,
          requested_cid: args.params && args.params.cid,
          source_api_id: args.api_id
        }))
      : Array.from({ length: Math.max(1, Math.min(top, 60)) }, (_, index) => ({
          rank: index + 1,
          title: `沙发垫 ${index + 1}`,
          empty_required: '',
          price: 99 - index,
          goods_url: `https://fixture.test/item/${index + 1}`,
          requested_top: top,
          requested_page_size: args.params && args.params.pageSize,
          requested_cid: args.params && args.params.cid,
          source_api_id: args.api_id
        }));
  return {
    kind: 'api_probe_result',
    api_id: args.api_id,
    method: 'POST',
    path: args.api_id,
    mode: 'fake_probe',
    request: {
      url: `https://fixture.test${args.api_id}?top=${top}&app_code_key=${encodeURIComponent(secret)}`,
      query: { ...(args.params || {}), app_code_key: secret },
      body: null,
      headers_keys: [],
      auth_inject: { header: [], body: [], query: [{ name: 'app_code_key', value: secret }] }
    },
    status: { state: process.env.LIVE_PROBE === 'true' ? 'ok' : 'missing_live_probe_env' },
    response: {
      total: rows.length,
      truncated: false,
      top: rows
    }
  };
}
""",
            encoding="utf-8",
        )
        (root / "src" / "tools" / "get_api_asset_card.mjs").write_text(
            """
export function getApiAssetCard(args) {
  return {
    found: true,
    card: {
      api_id: args.api_id,
      name: '类目商品排行',
      method: 'POST',
      path: args.api_id,
      domain: '商品域',
      capability: '商品分析',
      quality_score: 0.91,
      request_schema: {
        query: [
          { name: 'category', type: 'string', required: true, desc: '三级类目' },
          { name: 'start_date', type: 'string', required: true, desc: '开始日期' },
          { name: 'end_date', type: 'string', required: true, desc: '结束日期' }
        ]
      },
      response_schema: {
        root: 'data.rows[]',
        fields: [
          { path: 'data.rows.rank', name: 'rank', type: 'number', desc: '排名' },
          { path: 'data.rows.shop_name', name: 'shop_name', type: 'string', desc: '店铺名称' },
          { path: 'data.rows.product_url', name: 'product_url', type: 'string', desc: '商品链接' },
          { path: 'data.rows.price', name: 'price', type: 'number', desc: '商品价格' },
          { path: 'data.rows.pay_buyer_count', name: 'pay_buyer_count', type: 'number', desc: '支付买家数' }
        ]
      }
    },
    lineage_text: 'BusinessQuestion -> Tool -> API -> Field'
  };
}
""",
            encoding="utf-8",
        )
        return root

    def test_db_worker_probe_api_batch_retries_timeout_and_keeps_partial_results(self):
        fake_spec_pack = self._create_fake_spec_pack()
        worker_path = Path(__file__).parent.parent / "shells" / "report_generator" / "server" / "db_archaeologist_worker.mjs"
        env = os.environ.copy()
        env.update({
            "DBA_LIVE_PROBE": "1",
            "LIVE_PROBE": "true",
            "TEST_DETAIL_RETRY": "1",
            "TEST_DETAIL_PARTIAL": "1",
        })
        request = {
            "spec_pack_root": str(fake_spec_pack),
            "tool": "probe_api_batch",
            "args": {
                "api_id": "data_goods_ads_ind_goods_detail_info_m",
                "items": [
                    {"correlation_id": "desk-1", "params": {"goods_id": "desk-1", "data_source": "qbt"}},
                    {"correlation_id": "desk-2", "params": {"goods_id": "desk-2", "data_source": "qbt"}},
                    {"correlation_id": "desk-3", "params": {"goods_id": "desk-3", "data_source": "qbt"}},
                ],
                "concurrency": 2,
                "retry": 1,
                "timeout_ms": 8000,
            },
        }

        proc = subprocess.run(
            [shutil.which("node") or "/opt/homebrew/bin/node", "--import", str(fake_spec_pack / "scripts" / "ts_loader.mjs"), str(worker_path)],
            input=json.dumps(request),
            env=env,
            text=True,
            capture_output=True,
        )

        self.assertEqual(0, proc.returncode, proc.stderr)
        response = json.loads(proc.stdout)
        self.assertTrue(response["ok"])
        batch = response["payload"]
        self.assertEqual("api_probe_batch_result", batch["kind"])
        self.assertEqual({"requested": 3, "success": 2, "empty": 1, "failed": 0}, batch["summary"])
        by_id = {item["correlation_id"]: item for item in batch["items"]}
        self.assertEqual(2, by_id["desk-2"]["attempts"])
        self.assertEqual("empty", by_id["desk-3"]["status"])

    def _write_local_api_doc_index(self) -> Path:
        data_dir = self.app_root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        index_path = data_dir / "api_doc_index.json"
        index_path.write_text(
            json.dumps(
                {
                    "schema_version": "api-doc-index-v2",
                    "summary": {"api_count": 4, "field_count": 31},
                    "category_entity_count": 1,
                    "category_entities": [
                        {
                            "canonical_name": "桌布",
                            "category_id": "121458013",
                            "aliases": [],
                            "evidence_count": 2,
                            "evidence_texts": ["学生书桌垫儿童学习桌垫", "防水防油餐桌垫免洗桌布"],
                            "evidence_sources": [
                                {
                                    "api_id": "data_dim_goods_info",
                                    "source_ref": {"path": "fixture-detail.md", "line": 1},
                                    "name_field_path": "category_name",
                                    "id_field_path": "category_id",
                                    "evidence_text_field": "goods_name",
                                    "evidence_kind": "api_response_example",
                                }
                            ],
                        }
                    ],
                    "apis": [
                        {
                            "api_id": "category_resolver_api",
                            "source_seq": 0,
                            "name": "类目名称到ID解析",
                            "module": "fixture",
                            "business_module": "类目解析",
                            "analysis_domain": "类目域",
                            "method": "POST",
                            "path": "/category_resolver_api",
                            "verified_status": "success",
                            "request_params": [
                                {"name": "pageNum", "type": "integer", "required": True, "description": "页码"},
                                {"name": "pageSize", "type": "integer", "required": True, "description": "每页条数"},
                            ],
                            "request_headers": [],
                            "response_fields": [
                                {"path": "data.result[].cate_name", "name": "cate_name", "type": "string", "description": "类目名称"},
                                {"path": "data.result[].cate_id", "name": "cate_id", "type": "string", "description": "类目ID"},
                            ],
                            "source_refs": {"detail": "fixture-detail.md"},
                            "parse_warnings": [],
                        },
                        {
                            "api_id": "top300_product_analysis",
                            "source_seq": 1,
                            "name": "类目前300商品分析",
                            "module": "fixture",
                            "business_module": "商品分析",
                            "analysis_domain": "商品域",
                            "method": "POST",
                            "path": "/top300_product_analysis",
                            "verified_status": "success",
                            "request_params": [
                                {"name": "deal_date", "type": "string", "required": True, "description": "交易日期"},
                                {"name": "pageNum", "type": "integer", "required": True, "description": "页码"},
                            ],
                            "request_headers": [],
                            "response_fields": [
                                {"path": "data.result[].rank", "name": "rank", "type": "number", "description": "行业排名"},
                                {"path": "data.result[].commodity", "name": "commodity", "type": "string", "description": "商品名称/商品标题"},
                                {"path": "data.result[].store_name", "name": "store_name", "type": "string", "description": "店铺名称"},
                                {"path": "data.result[].product_url", "name": "product_url", "type": "string", "description": "商品链接"},
                                {"path": "data.result[].pictures_linking", "name": "pictures_linking", "type": "string", "description": "商品主图图片链接"},
                                {"path": "data.result[].unit_price", "name": "unit_price", "type": "number", "description": "件单价/价格"},
                                {"path": "data.result[].price_band", "name": "price_band", "type": "string", "description": "价格带"},
                                {"path": "data.result[].trade_index", "name": "trade_index", "type": "string", "description": "交易指数/GMV体量"},
                                {"path": "data.result[].material", "name": "material", "type": "string", "description": "材质"},
                                {"path": "data.result[].scene", "name": "scene", "type": "string", "description": "使用场景"},
                                {"path": "data.result[].num_payers_interval", "name": "num_payers_interval", "type": "string", "description": "支付买家数区间"},
                                {"path": "data.result[].selling_point", "name": "selling_point", "type": "string", "description": "主卖点"},
                            ],
                            "source_refs": {"detail": "fixture-detail.md"},
                            "parse_warnings": [],
                        },
                        {
                            "api_id": "data_ads_ind_trade_category_goods_m",
                            "source_seq": 2,
                            "name": "月-热销商品-按交易总量排序",
                            "module": "fixture",
                            "business_module": "热销商品",
                            "analysis_domain": "商品域",
                            "method": "POST",
                            "path": "/data/ads_ind_trade_category_goods_m",
                            "verified_status": "success",
                            "request_params": [
                                {"name": "cid", "type": "string", "required": True, "description": "类目ID"},
                                {"name": "pageNum", "type": "integer", "required": True, "description": "页码"},
                                {"name": "pageSize", "type": "integer", "required": True, "description": "每页条数"},
                                {"name": "start_date", "type": "string", "required": True, "description": "开始日期"},
                                {"name": "end_date", "type": "string", "required": True, "description": "结束日期"},
                            ],
                            "request_headers": [],
                            "response_fields": [
                                {"path": "data.result[].rank", "name": "rank", "type": "number", "description": "排名"},
                                {"path": "data.result[].goods_id", "name": "goods_id", "type": "string", "description": "商品ID"},
                                {"path": "data.result[].goods_url", "name": "goods_url", "type": "string", "description": "商品链接"},
                                {"path": "data.result[].goods_img", "name": "goods_img", "type": "string", "description": "商品主图"},
                                {"path": "data.result[].shop_name", "name": "shop_name", "type": "string", "description": "店铺名称"},
                                {"path": "data.result[].num_payers_interval", "name": "num_payers_interval", "type": "string", "description": "支付买家数区间"},
                                {"path": "data.result[].sales_revenue", "name": "sales_revenue", "type": "string", "description": "销售额/GMV"},
                                {"path": "data.result[].unit_price", "name": "unit_price", "type": "string", "description": "件单价/客单价"},
                                {"path": "data.result[].selling_point", "name": "selling_point", "type": "string", "description": "主卖点"},
                                {"path": "data.result[].category_name", "name": "category_name", "type": "string", "description": "类目名称"},
                                {"path": "data.result[].cid", "name": "cid", "type": "string", "description": "类目ID"},
                                {"path": "data.result[].statist_date", "name": "statist_date", "type": "string", "description": "统计月份"},
                            ],
                            "source_refs": {"detail": "fixture-detail.md"},
                            "parse_warnings": [],
                        },
                        {
                            "api_id": "data_ads_ind_sycm_speed_category_goods_m",
                            "source_seq": 3,
                            "name": "月-热销商品-按交易增速排序",
                            "module": "fixture",
                            "business_module": "热销商品",
                            "analysis_domain": "商品域",
                            "method": "POST",
                            "path": "/data/ads_ind_sycm_speed_category_goods_m",
                            "verified_status": "success",
                            "request_params": [
                                {"name": "cid", "type": "string", "required": True, "description": "类目ID"},
                                {"name": "pageNum", "type": "integer", "required": True, "description": "页码"},
                                {"name": "pageSize", "type": "integer", "required": True, "description": "每页条数"},
                                {"name": "start_date", "type": "string", "required": True, "description": "开始日期"},
                                {"name": "end_date", "type": "string", "required": True, "description": "结束日期"},
                            ],
                            "request_headers": [],
                            "response_fields": [
                                {"path": "data.result[].last_month_rank", "name": "last_month_rank", "type": "number", "description": "上月排名"},
                                {"path": "data.result[].speed_type", "name": "speed_type", "type": "string", "description": "交易增速类型"},
                                {"path": "data.result[].goods_id", "name": "goods_id", "type": "string", "description": "商品ID"},
                                {"path": "data.result[].goods_url", "name": "goods_url", "type": "string", "description": "商品链接"},
                                {"path": "data.result[].pay_buyer_count", "name": "pay_buyer_count", "type": "number", "description": "支付买家数"},
                                {"path": "data.result[].top3_category_name", "name": "top3_category_name", "type": "string", "description": "top3类目字段名称"},
                                {"path": "data.result[].yoy_sales_volume", "name": "yoy_sales_volume", "type": "string", "description": "销量同比/增速"},
                            ],
                            "source_refs": {"detail": "fixture-detail.md"},
                            "parse_warnings": [],
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        config["data_capability_index"] = {
            "provider": "api_doc_index",
            "status": "available",
            "runtime_index_ref": "data/api_doc_index.json",
            "default_strategy": "field_coverage_rerank",
            "stats": {"api_count": 2, "field_count": 8},
            "sources": [],
        }
        node = config["nodes"][1]
        business_fields = [
            ("排名", "行业排名", "rank"),
            ("店铺名", "对手是谁", "shop_name"),
            ("商品链接", "分析对象", "product_url"),
            ("商品主图", "看视觉表达", "product_image"),
            ("销量/支付买家数", "判断真实销售能力", "sales_or_pay_buyer_count"),
            ("GMV/交易指数", "判断体量", "gmv_or_transaction_index"),
            ("客单价", "判断价格带", "price"),
            ("价格带", "低/中/高（生意参谋6个价格带）", "price_band"),
            ("产品类型", "品类/款式/形态", "product_type"),
            ("材质", "例如半边绒、冰丝、羊羔绒", "material"),
            ("功能", "防水、防滑、抗菌、护眼、显白等", "function"),
            ("风格", "奶油风、轻奢风、复古风、简约风", "style"),
            ("场景", "家用、宿舍、母婴、户外、通勤", "scene"),
            ("主卖点", "第一卖点是什么", "main_selling_point"),
            ("主图元素", "背景、构图、文案、场景、人物", "main_image_elements"),
            ("是否高增速", "近7天/近30天排名提升明显", "growth_flag"),
            ("爆款原因", "为什么卖得好", "hot_sale_reason"),
        ]
        node["output_field_requirements"] = [
            {
                "output_id": "top_300_product_analysis_table",
                "field_path": f"items.properties.{canonical}",
                "field_name": name,
                "title": name,
                "description": desc,
                "canonical_field_name": canonical,
                "type": "unknown",
                "required": True,
                "source_schema_ref": "skill_snapshot/output_schemas/top_300_product_analysis_table.json",
                "source": "business_doc_output_table",
            }
            for name, desc, canonical in business_fields
        ]
        self.config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        return index_path

    def _append_keyword_apis_to_local_index(self) -> None:
        index_path = self.app_root / "data" / "api_doc_index.json"
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        payload["apis"].extend(
            [
                {
                    "api_id": "agent_sycm_keyword",
                    "source_seq": 4,
                    "name": "生意参谋关键词",
                    "module": "fixture",
                    "business_module": "关键词分析",
                    "analysis_domain": "搜索词/词根/需求趋势",
                    "method": "POST",
                    "path": "/agent/sycm_keyword",
                    "verified_status": "success",
                    "response_root": "data.result[]",
                    "request_params": [
                        {"name": "tertiary_category", "type": "string", "required": True, "description": "三级类目/类目名称"}
                    ],
                    "request_headers": [],
                    "response_fields": [
                        {"path": "data.result[].keywords", "name": "keywords", "type": "string", "description": "关键词"},
                        {"path": "data.result[].search_popularity", "name": "search_popularity", "type": "string", "description": "搜索人气"},
                        {"path": "data.result[].search_growth_rate", "name": "search_growth_rate", "type": "string", "description": "搜索增长率"},
                        {"path": "data.result[].click_rate", "name": "click_rate", "type": "string", "description": "点击率"},
                        {"path": "data.result[].pay_rate", "name": "pay_rate", "type": "string", "description": "支付转化率"},
                        {"path": "data.result[].tertiary_category", "name": "tertiary_category", "type": "string", "description": "三级类目"},
                    ],
                    "source_refs": {},
                    "parse_warnings": [],
                },
                {
                    "api_id": "agent_xiaowan_keywords",
                    "source_seq": 5,
                    "name": "直通车-小万关键词",
                    "module": "fixture",
                    "business_module": "关键词分析",
                    "analysis_domain": "搜索词/词根/需求趋势",
                    "method": "POST",
                    "path": "/agent/xiaowan_keywords",
                    "verified_status": "success",
                    "response_root": "data.result[]",
                    "request_params": [
                        {"name": "tertiary_category", "type": "string", "required": True, "description": "三级类目/类目名称"}
                    ],
                    "request_headers": [],
                    "response_fields": [
                        {"path": "data.result[].keyword", "name": "keyword", "type": "string", "description": "关键词"},
                        {"path": "data.result[].competition_index", "name": "competition_index", "type": "string", "description": "竞争指数"},
                        {"path": "data.result[].click_rate", "name": "click_rate", "type": "string", "description": "点击率"},
                        {"path": "data.result[].conversion_rate", "name": "conversion_rate", "type": "string", "description": "转化率"},
                        {"path": "data.result[].tertiary_category", "name": "tertiary_category", "type": "string", "description": "三级类目"},
                    ],
                    "source_refs": {},
                    "parse_warnings": [],
                },
            ]
        )
        keyword_fields = [
            ("keyword", "keyword"),
            ("search_popularity", "search_popularity"),
            ("growth_rate", "growth_rate"),
            ("competition_index", "competition_index"),
            ("click_rate", "click_rate"),
            ("conversion_rate", "conversion_rate"),
            ("root_terms", "root_terms"),
            ("demand_type", "demand_type"),
        ]
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        node = next(item for item in config["nodes"] if item["id"] == "collect_keywords")
        node["output_field_requirements"] = [
            {
                "output_id": "keyword_demand_breakdown_table",
                "field_path": f"items.properties.{canonical}",
                "field_name": name,
                "title": name,
                "description": "关键词需求分析字段",
                "canonical_field_name": canonical,
                "type": "unknown",
                "required": True,
                "source_schema_ref": "fixture",
                "source": "data_requirement_fallback",
            }
            for name, canonical in keyword_fields
        ]
        self.config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _append_product_detail_to_local_index(self) -> None:
        index_path = self.app_root / "data" / "api_doc_index.json"
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        payload["apis"].append(
            {
                "api_id": "data_goods_ads_ind_goods_detail_info_m",
                "source_seq": 4,
                "name": "商品详情信息查询接口",
                "module": "fixture",
                "business_module": "商品详情补充",
                "analysis_domain": "商品域",
                "method": "POST",
                "path": "/data/goods/ads_ind_goods_detail_info_m",
                "verified_status": "success",
                "verified_url_path": "/openApi/api/fixture/5/data/goods/ads_ind_goods_detail_info_m",
                "response_root": "data.result[]",
                "default_params": {"data_source": "qbt"},
                "request_params": [
                    {"name": "tenantId", "type": "string", "required": True, "description": "租户ID", "position": "query"},
                    {"name": "goods_id", "type": "string", "required": True, "description": "商品ID", "position": "query"},
                    {"name": "userId", "type": "string", "required": True, "description": "用户ID", "position": "query"},
                    {"name": "data_source", "type": "string", "required": True, "description": "数据来源", "position": "query"},
                ],
                "request_headers": [],
                "response_fields": [
                    {"path": "data.result[].goods_id", "name": "goods_id", "type": "string", "description": "商品ID"},
                    {"path": "data.result[].goods_name", "name": "goods_name", "type": "string", "description": "商品名称"},
                    {"path": "data.result[].core_material", "name": "core_material", "type": "string", "description": "核心材质"},
                    {"path": "data.result[].usage_scene", "name": "usage_scene", "type": "string", "description": "使用场景"},
                    {"path": "data.result[].selling_point_summary", "name": "selling_point_summary", "type": "string", "description": "卖点总结"},
                    {"path": "data.result[].goods_spec_params", "name": "goods_spec_params", "type": "string", "description": "商品规格参数"},
                    {"path": "data.result[].goods_img", "name": "goods_img", "type": "string", "description": "商品图片地址"},
                ],
                "source_refs": {"detail_doc": {"path": "商品详情信息查询接口文档.md", "line": 1}},
                "parse_warnings": [],
            }
        )
        index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _append_product_feedback_to_local_index(self) -> None:
        index_path = self.app_root / "data" / "api_doc_index.json"
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        common_params = [
            {"name": "goods_id", "type": "string", "required": True, "description": "商品ID"},
            {"name": "goods_id_list", "type": "string/array", "required": True, "description": "商品ID列表"},
            {"name": "pageNum", "type": "integer", "required": True, "description": "页码"},
            {"name": "pageSize", "type": "integer", "required": True, "description": "每页条数"},
        ]
        payload["apis"].extend(
            [
                {
                    "api_id": "get_positive_comment_data", "source_seq": 20, "name": "获取商品好评数据",
                    "module": "商品反馈", "business_module": "商品评价", "analysis_domain": "评价与问大家",
                    "method": "POST", "path": "/get_positive_comment_data", "verified_status": "success",
                    "response_root": "data.result[]", "request_params": [common_params[1]], "request_headers": [],
                    "response_fields": [
                        {"path": "data.result[].goods_id", "name": "goods_id", "type": "string", "description": "商品ID"},
                        {"path": "data.result[].comment", "name": "comment", "type": "string", "description": "好评内容"},
                    ], "source_refs": {}, "parse_warnings": [],
                },
                {
                    "api_id": "product_comment_content2", "source_seq": 21, "name": "获取商品评论数据",
                    "module": "商品反馈", "business_module": "商品评价", "analysis_domain": "评价与问大家",
                    "method": "POST", "path": "/product_comment_content2", "verified_status": "success",
                    "response_root": "data.result[]", "request_params": common_params, "request_headers": [],
                    "response_fields": [
                        {"path": "data.result[].goods_id", "name": "goods_id", "type": "string", "description": "商品ID"},
                        {"path": "data.result[].comment", "name": "comment", "type": "string", "description": "评论内容"},
                    ], "source_refs": {}, "parse_warnings": [],
                },
                {
                    "api_id": "product_question_content2", "source_seq": 22, "name": "获取问大家分析数据",
                    "module": "商品反馈", "business_module": "问大家", "analysis_domain": "评价与问大家",
                    "method": "POST", "path": "/product_question_content2", "verified_status": "success",
                    "response_root": "data.result[]", "request_params": common_params, "request_headers": [],
                    "response_fields": [
                        {"path": "data.result[].goods_id", "name": "goods_id", "type": "string", "description": "商品ID"},
                        {"path": "data.result[].question_content", "name": "question_content", "type": "string", "description": "问大家问题内容"},
                        {"path": "data.result[].answer_count", "name": "answer_count", "type": "string", "description": "回答数量"},
                    ], "source_refs": {}, "parse_warnings": [],
                },
            ]
        )
        index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        fields = [
            ("competitor_product_url", "竞品链接"), ("review_text", "评价原文"),
            ("sentiment", "正负向"), ("rating", "评分"), ("qa_question", "问题原文"),
            ("qa_answer", "竞品回答"), ("painpoint_type", "痛点分类"),
            ("sku_name", "SKU名称"), ("created_at", "反馈时间"),
        ]
        config["nodes"].append(
            {
                "id": "collect_reviews_qa", "name": "评价与问大家痛点分析", "kind": "data",
                "depends_on": ["collect_top_products"], "data_requirements": ["competitor_reviews_qa"],
                "outputs": ["review_qa_painpoint_table"],
                "analysis_node_view": {
                    "node_kind": "data_analysis",
                    "purpose_model": {"purpose": "分析同类型排名前10竞品的评价与问大家"},
                    "input_model": {"data_sources": [{"description": "同类型排名前10竞品评价与问大家"}]},
                    "execution_plan": {"steps": [{"instruction": "下载评价与问大家并归类痛点"}]},
                    "data_output_model": {"fields": []},
                },
                "output_field_requirements": [
                    {
                        "output_id": "review_qa_painpoint_table", "field_path": f"items.properties.{name}",
                        "field_name": name, "title": name, "description": description,
                        "canonical_field_name": name, "type": "unknown", "required": True,
                    }
                    for name, description in fields
                ],
                "state_machine": [],
            }
        )
        self.config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

    def _append_competitor_analysis_to_local_index(self) -> None:
        index_path = self.app_root / "data" / "api_doc_index.json"
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        payload["apis"].append(
            {
                "api_id": "data_shop_competition_pattern_analysis_v3",
                "source_seq": 30,
                "name": "竞争格局分析-商品查询",
                "module": "竞争格局",
                "business_module": "竞品分析",
                "analysis_domain": "竞品与竞店格局分析",
                "method": "POST",
                "path": "/data/shop_competition_pattern_analysis_v3",
                "verified_status": "success",
                "response_root": "data.result[]",
                "request_params": [
                    {"name": "cid", "type": "string", "required": True, "description": "类目ID"},
                    {"name": "start_date", "type": "string", "required": True, "description": "开始日期"},
                    {"name": "end_date", "type": "string", "required": True, "description": "结束日期"},
                    {"name": "pageNum", "type": "integer", "required": True, "description": "页码"},
                    {"name": "pageSize", "type": "integer", "required": True, "description": "每页条数"},
                ],
                "request_headers": [],
                "response_fields": [
                    {"path": "data.result[].goods_id", "name": "goods_id", "type": "string", "description": "商品ID"},
                    {"path": "data.result[].shop_name", "name": "shop_name", "type": "string", "description": "店铺名称"},
                    {"path": "data.result[].goods_href", "name": "goods_href", "type": "string", "description": "商品链接"},
                    {"path": "data.result[].price", "name": "price", "type": "number", "description": "商品价格"},
                    {"path": "data.result[].main_sku", "name": "main_sku", "type": "string", "description": "主销SKU"},
                    {"path": "data.result[].main_selling_point", "name": "main_selling_point", "type": "string", "description": "主卖点"},
                    {"path": "data.result[].main_image_url", "name": "main_image_url", "type": "string", "description": "商品主图"},
                    {"path": "data.result[].main_color", "name": "main_color", "type": "string", "description": "主色调"},
                    {"path": "data.result[].sales_total", "name": "sales_total", "type": "number", "description": "销量"},
                    {"path": "data.result[].sales_ratio", "name": "sales_ratio", "type": "number", "description": "销售占比"},
                    {"path": "data.result[].cid", "name": "cid", "type": "string", "description": "类目ID"},
                    {"path": "data.result[].category_name", "name": "category_name", "type": "string", "description": "类目名称"},
                ],
                "source_refs": {},
                "parse_warnings": [],
            }
        )
        index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        fields = [
            "competitor_type", "shop_name", "product_url", "price", "sku_count",
            "main_selling_point", "visual_structure", "review_painpoints",
            "traffic_structure", "competitor_strength",
        ]
        config["nodes"].append(
            {
                "id": "analyze_competitors", "name": "竞品与竞店格局分析", "kind": "data",
                "source_type": "multi_source_analysis", "depends_on": ["collect_top_products", "collect_reviews_qa"],
                "data_requirements": ["competitor_landscape"], "outputs": ["competitor_landscape_table"],
                "analysis_node_view": {
                    "node_kind": "data_analysis",
                    "purpose_model": {"purpose": "分析竞品与竞店格局"},
                    "input_model": {"data_sources": [{"description": "竞品格局与评价"}]},
                    "execution_plan": {"steps": [{"instruction": "按商品ID合并竞品与评价"}]},
                    "data_output_model": {"fields": []},
                },
                "output_field_requirements": [
                    {
                        "output_id": "competitor_landscape_table", "field_path": f"items.properties.{name}",
                        "field_name": name, "title": name, "description": name,
                        "canonical_field_name": name, "type": "unknown", "required": True,
                    }
                    for name in fields
                ],
                "state_machine": [],
            }
        )
        self.config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

    def _write_confirmed_competitor_reviews(self) -> None:
        artifacts = self.app_root / "artifacts"
        artifacts.mkdir(exist_ok=True)
        (artifacts / "collect_reviews_qa.confirmed_data_table.json").write_text(
            json.dumps(
                {
                    "schema_version": "data-table-confirmed-v1",
                    "node_id": "collect_reviews_qa",
                    "status": "confirmed",
                    "workspace_revision": 2,
                    "rows": [
                        {"goods_id": "gene-1", "review_text": "气味较重"},
                        {"goods_id": "gene-2", "review_text": "容易卷边"},
                        {"goods_id": "gene-2", "qa_question": "尺寸有误差吗"},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def test_review_qa_node_uses_confirmed_top_products_for_feedback_enrichment(self):
        self._write_local_api_doc_index()
        self._append_product_feedback_to_local_index()
        self._write_gene_analysis_source_fixture(count=2, revision=3)
        fake_spec_pack = self._create_fake_spec_pack()

        status, data = self._direct(
            "POST",
            "/api/nodes/collect_reviews_qa/run",
            {"known_params": {"category": "桌布"}, "top_n": 10},
            {"DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack), "DBA_LIVE_PROBE": "1"},
        )

        self.assertEqual(200, status)
        result = data["result"]
        self.assertNotIn("missing_required_params", result["blocked_reasons"])
        feedback_plans = [
            item for item in result["api_execution_plan"]
            if item["execution_role"] == "product_feedback_enrichment"
        ]
        self.assertEqual(3, len(feedback_plans))
        self.assertTrue(all(item["status"] == "called" for item in feedback_plans))
        self.assertTrue(all(item["batch_summary"] == {"requested": 2, "success": 2, "empty": 0, "failed": 0} for item in feedback_plans))
        for plan in feedback_plans:
            self.assertEqual("confirmed_top_products", plan["depends_on_role"])
            self.assertEqual(2, plan["request_debug"]["requested_count"])
            for request in plan["request_debug"]["sample_requests"]:
                query = request.get("query") or request.get("body") or {}
                self.assertEqual(1, len(query.get("goods_id_list") or []))
                if plan["api_id"] != "get_positive_comment_data":
                    self.assertEqual([query.get("goods_id")], query.get("goods_id_list"))

        table = json.loads((self.app_root / result["data_table_ref"]).read_text(encoding="utf-8"))
        self.assertEqual(6, len(table["rows"]))
        self.assertEqual(
            {"好评-gene-1", "评论-gene-1"},
            {row.get("review_text") for row in table["rows"] if row.get("goods_id") == "gene-1" and row.get("review_text")},
        )
        question_row = next(row for row in table["rows"] if row.get("qa_question") == "问题-gene-1")
        self.assertEqual("https://fixture.test/?id=gene-1", question_row["competitor_product_url"])
        self.assertNotIn("sentiment", question_row)
        self.assertNotIn("rating", question_row)
        self.assertEqual(6, len({item["row_id"] for item in table["row_meta"]}))
        link_source = next(item for item in table["field_sources"] if item["field_name"] == "competitor_product_url")
        self.assertEqual("upstream_artifact", link_source["source_kind"])
        self.assertEqual("confirmed_product_identity_join", link_source["derivation_method"])

    def test_review_qa_node_blocks_without_confirmed_top_products(self):
        self._write_local_api_doc_index()
        self._append_product_feedback_to_local_index()
        fake_spec_pack = self._create_fake_spec_pack()

        status, data = self._direct(
            "POST",
            "/api/nodes/collect_reviews_qa/run",
            {"known_params": {"category": "桌布"}, "top_n": 10},
            {"DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack), "DBA_LIVE_PROBE": "1"},
        )

        self.assertEqual(200, status)
        result = data["result"]
        self.assertEqual("blocked", result["status"])
        self.assertIn("source_table_not_confirmed", result["blocked_reasons"])
        self.assertEqual([], json.loads((self.app_root / result["execution_trace_ref"]).read_text(encoding="utf-8"))["api_calls"])

    def test_bind_api_request_params_uses_exact_tokens_and_tracks_dropped_optional_params(self):
        result = self._function(
            "bindApiRequestParams",
            {
                "api_request_params": [
                    {"name": "category_id", "type": "string", "required": True, "description": "类目ID"},
                    {"name": "pageSize", "type": "integer", "required": False, "description": "每页条数"},
                    {"name": "pageNum", "type": "integer", "required": False, "description": "页码"},
                    {"name": "start_date", "type": "string", "required": False, "description": "开始日期"},
                    {"name": "update_time", "type": "string", "required": False, "description": "更新时间"},
                    {"name": "tenant_code", "type": "string", "required": True, "description": "租户编码"},
                ],
                "known_params": {"category": "入户地垫", "period": "近30天"},
            },
        )

        self.assertNotIn("category_id", result["params"])
        self.assertEqual(result["params"]["pageSize"], 300)
        self.assertEqual(result["params"]["pageNum"], 1)
        mappings = {item["api_param"]: item for item in result["request_param_mapping"]}
        self.assertEqual(mappings["category_id"]["business_param"], "category")
        self.assertEqual(mappings["category_id"]["category_param_role"], "category_id")
        self.assertEqual(mappings["category_id"]["status"], "missing")
        self.assertIn("缺少类目ID", mappings["category_id"]["missing_reason"])
        self.assertEqual(mappings["pageSize"]["business_param"], "page_size")
        self.assertEqual(mappings["pageNum"]["business_param"], "page")
        self.assertEqual(mappings["start_date"]["status"], "manual_required")
        self.assertIn("start_date", result["dropped_optional_params"])
        self.assertEqual(mappings["update_time"]["status"], "optional")
        self.assertNotEqual(mappings["update_time"]["business_param"], "period")
        self.assertNotIn("update_time", result["params"])
        self.assertIn("tenant_code", result["missing_required_params"])
        self.assertEqual(result["category_resolution"]["blocked_reason"], "category_id_required")

    def test_bind_api_request_params_binds_category_name_directly(self):
        result = self._function(
            "bindApiRequestParams",
            {
                "api_request_params": [
                    {"name": "tertiary_category", "type": "string", "required": True, "description": "三级类目/类目名称"},
                ],
                "known_params": {"category": "入户地垫"},
            },
        )

        self.assertEqual(result["params"]["tertiary_category"], "入户地垫")
        mappings = {item["api_param"]: item for item in result["request_param_mapping"]}
        self.assertEqual(mappings["tertiary_category"]["category_param_role"], "category_name")
        self.assertEqual(mappings["tertiary_category"]["binding_method"], "category_name_direct")

    def test_rows_from_probe_payload_flattens_paging_wrappers(self):
        empty = self._function(
            "rowsFromProbePayload",
            {
                "payload": {
                    "response": {
                        "root": "data",
                        "top": [{"pageNum": 1, "pageSize": 50, "totalNum": 0, "result": []}],
                    }
                }
            },
        )
        self.assertEqual(empty["rows"], [])

        non_empty = self._function(
            "rowsFromProbePayload",
            {
                "payload": {
                    "response": {
                        "data": {"pageNum": 1, "pageSize": 50, "totalNum": 1, "result": [{"rank": 1}]}
                    }
                }
            },
        )
        self.assertEqual(non_empty["rows"], [{"rank": 1}])

        data_rows = self._function(
            "rowsFromProbePayload",
            {
                "payload": {
                    "response": {
                        "data": {"rows": [{"rank": 2}, {"rank": 3}]}
                    }
                }
            },
        )
        self.assertEqual(data_rows["rows"], [{"rank": 2}, {"rank": 3}])

    def test_request_debug_redacts_app_code_key_query_params(self):
        result = self._function(
            "requestDebugFromProbePayload",
            {
                "payload": {
                    "request": {
                        "url": "https://fixture.test/api?app_code_key=secret-value&appCodeKey=camel-secret&safe=value",
                        "query": {
                            "app_code_key": "secret-value",
                            "appCodeKey": "camel-secret",
                            "safe": "value",
                        },
                    }
                }
            },
        )

        request_debug = result["request_debug"]
        self.assertNotIn("secret-value", json.dumps(request_debug))
        self.assertNotIn("camel-secret", json.dumps(request_debug))
        self.assertIn("safe=value", request_debug["url"])
        self.assertEqual(request_debug["query"]["app_code_key"], "[REDACTED]")
        self.assertEqual(request_debug["query"]["appCodeKey"], "[REDACTED]")

    def test_build_field_sources_reports_value_statuses_without_socket(self):
        result = self._function(
            "fieldSourceStatuses",
            {
                "rows_by_api": {
                    "api_present": [{"rank": 1, "empty_name": ""}, {"rank": "", "empty_name": ""}],
                    "api_empty": [],
                },
                "api_execution_plan": [
                    {"api_id": "api_present", "status": "called", "source_path_missing_fields": [], "evidence_ref": "evidence/present.json"},
                    {"api_id": "api_empty", "status": "called", "source_path_missing_fields": [], "evidence_ref": "evidence/empty.json"},
                    {"api_id": "api_not_called", "status": "blocked", "source_path_missing_fields": [], "evidence_ref": ""},
                ],
                "field_coverage_plan": [
                    {
                        "field_name": "排名",
                        "field_path": "items.properties.rank",
                        "required": True,
                        "mapping_status": "mapped",
                        "source_api_id": "api_present",
                        "source_field_path": "data.rows.rank",
                    },
                    {
                        "field_name": "不存在字段",
                        "field_path": "items.properties.missing_field",
                        "required": True,
                        "mapping_status": "mapped",
                        "source_api_id": "api_present",
                        "source_field_path": "data.rows.missing_field",
                    },
                    {
                        "field_name": "空 API 字段",
                        "field_path": "items.properties.empty_api_field",
                        "required": True,
                        "mapping_status": "mapped",
                        "source_api_id": "api_empty",
                        "source_field_path": "data.rows.rank",
                    },
                    {
                        "field_name": "缺 source path",
                        "field_path": "items.properties.no_source_path",
                        "required": True,
                        "mapping_status": "mapped",
                        "source_api_id": "api_present",
                        "source_field_path": "",
                    },
                    {
                        "field_name": "未调用字段",
                        "field_path": "items.properties.not_called",
                        "required": True,
                        "mapping_status": "mapped",
                        "source_api_id": "api_not_called",
                        "source_field_path": "data.rows.value",
                    },
                ],
            },
        )

        by_field = {item["field_name"]: item for item in result["field_sources"]}
        self.assertEqual(by_field["排名"]["value_status"], "partial")
        self.assertEqual(by_field["排名"]["rows_with_value"], 1)
        self.assertEqual(by_field["排名"]["rows_missing_value"], 1)
        self.assertEqual(by_field["不存在字段"]["value_status"], "missing")
        self.assertEqual(by_field["空 API 字段"]["value_status"], "empty")
        self.assertEqual(by_field["缺 source path"]["value_status"], "source_path_missing")
        self.assertEqual(by_field["未调用字段"]["value_status"], "not_called")

    def test_multi_api_projection_without_join_key_blocks_secondary_instead_of_row_alignment(self):
        result = self._function(
            "fieldSourceStatuses",
            {
                "rows_by_api": {
                    "api_rank": [{"rank": 1}, {"rank": 2}],
                    "api_sales": [{"pay_buyer_count": 100}, {"pay_buyer_count": 80}],
                },
                "api_execution_plan": [
                    {"api_id": "api_rank", "status": "called", "source_path_missing_fields": [], "evidence_ref": "evidence/rank.json"},
                    {"api_id": "api_sales", "status": "called", "source_path_missing_fields": [], "evidence_ref": "evidence/sales.json"},
                ],
                "field_coverage_plan": [
                    {
                        "field_name": "排名",
                        "field_path": "items.properties.rank",
                        "required": True,
                        "mapping_status": "mapped",
                        "source_api_id": "api_rank",
                        "source_field_path": "data.rows.rank",
                    },
                    {
                        "field_name": "销量/支付买家数",
                        "field_path": "items.properties.sales_or_pay_buyer_count",
                        "required": True,
                        "mapping_status": "mapped",
                        "source_api_id": "api_sales",
                        "source_field_path": "data.rows.pay_buyer_count",
                    },
                ],
            },
        )

        self.assertEqual(result["projection"]["primary_api_id"], "api_rank")
        self.assertEqual(result["projection"]["join_blocked_api_ids"], ["api_sales"])
        self.assertEqual(result["projection"]["row_index_merged_api_ids"], [])
        self.assertEqual(result["projection"]["merge_strategy"], "single_api")
        self.assertEqual(result["projection"]["rows"][0]["排名"], 1)
        self.assertNotIn("销量/支付买家数", result["projection"]["rows"][0])
        by_field = {item["field_name"]: item for item in result["field_sources"]}
        self.assertEqual(by_field["排名"]["value_status"], "present")
        self.assertEqual(by_field["销量/支付买家数"]["value_status"], "join_blocked")
        self.assertEqual(by_field["销量/支付买家数"]["rows_with_value"], 0)
        self.assertEqual(by_field["销量/支付买家数"]["rows_missing_value"], 2)

    def test_multi_api_projection_uses_product_id_key_join(self):
        result = self._function(
            "fieldSourceStatuses",
            {
                "rows_by_api": {
                    "api_rank": [
                        {"commodity_id": "1001", "rank": 1},
                        {"commodity_id": "1002", "rank": 2},
                        {"commodity_id": "1003", "rank": 3},
                    ],
                    "api_sales": [
                        {"goods_id": "1002", "pay_buyer_count": 80},
                        {"goods_id": "1001", "pay_buyer_count": 100},
                    ],
                },
                "api_execution_plan": [
                    {"api_id": "api_rank", "status": "called", "source_path_missing_fields": [], "evidence_ref": "evidence/rank.json"},
                    {"api_id": "api_sales", "status": "called", "source_path_missing_fields": [], "evidence_ref": "evidence/sales.json"},
                ],
                "field_coverage_plan": [
                    {
                        "field_name": "排名",
                        "field_path": "items.properties.rank",
                        "required": True,
                        "mapping_status": "mapped",
                        "source_api_id": "api_rank",
                        "source_field_path": "data.rows.rank",
                    },
                    {
                        "field_name": "销量/支付买家数",
                        "field_path": "items.properties.sales_or_pay_buyer_count",
                        "required": True,
                        "mapping_status": "mapped",
                        "source_api_id": "api_sales",
                        "source_field_path": "data.rows.pay_buyer_count",
                    },
                ],
            },
        )

        projection = result["projection"]
        self.assertEqual(len(projection["rows"]), 3)
        self.assertEqual(projection["merge_strategy"], "key_join")
        self.assertEqual(projection["join_keys"], ["product_id"])
        self.assertEqual(projection["key_joined_api_ids"], ["api_sales"])
        self.assertEqual(projection["row_index_merged_api_ids"], [])
        self.assertEqual(projection["rows"][0]["销量/支付买家数"], 100)
        self.assertEqual(projection["rows"][1]["销量/支付买家数"], 80)
        self.assertNotIn("销量/支付买家数", projection["rows"][2])
        by_field = {item["field_name"]: item for item in result["field_sources"]}
        self.assertEqual(by_field["销量/支付买家数"]["value_status"], "partial")
        self.assertEqual(by_field["销量/支付买家数"]["rows_with_value"], 2)
        self.assertEqual(by_field["销量/支付买家数"]["rows_missing_value"], 1)

    def test_projection_prefers_category_verified_api_over_unscoped_api(self):
        result = self._function(
            "fieldSourceStatuses",
            {
                "rows_by_api": {
                    "top300_product_analysis": [
                        {"commodity_id": "global-1", "rank": 1, "commodity": "抱枕"},
                        {"commodity_id": "global-2", "rank": 2, "commodity": "沙发垫"},
                    ],
                    "data_ads_ind_sycm_speed_category_goods_m": [
                        {"goods_id": "desk-1", "rank": 1, "goods_name": "桌垫商品", "cid": "121458013", "category_name": "桌布"},
                    ],
                },
                "api_execution_plan": [
                    {
                        "api_id": "top300_product_analysis",
                        "status": "called",
                        "category_scope": "unscoped",
                        "scope_validation_status": "unverified",
                        "source_fields": ["排名", "商品名", "店铺名", "商品主图"],
                        "source_path_missing_fields": [],
                    },
                    {
                        "api_id": "data_ads_ind_sycm_speed_category_goods_m",
                        "status": "called",
                        "category_scope": "category_id_required",
                        "scope_validation_status": "matched",
                        "source_fields": ["商品名"],
                        "source_path_missing_fields": [],
                    },
                ],
                "field_coverage_plan": [
                    {
                        "field_name": "商品名",
                        "field_path": "items.properties.product_name",
                        "required": True,
                        "mapping_status": "mapped",
                        "source_api_id": "data_ads_ind_sycm_speed_category_goods_m",
                        "source_field_path": "data.result[].goods_name",
                    },
                    {
                        "field_name": "排名",
                        "field_path": "items.properties.rank",
                        "required": True,
                        "mapping_status": "mapped",
                        "source_api_id": "top300_product_analysis",
                        "source_field_path": "data.result[].rank",
                    },
                ],
            },
        )

        projection = result["projection"]
        self.assertEqual("data_ads_ind_sycm_speed_category_goods_m", projection["primary_api_id"])
        self.assertEqual("桌垫商品", projection["rows"][0]["商品名"])
        self.assertNotIn("抱枕", json.dumps(projection["rows"], ensure_ascii=False))
        self.assertEqual(["top300_product_analysis"], projection["join_blocked_api_ids"])

    def test_projection_derives_rank_and_product_url_from_primary_rows(self):
        result = self._function(
            "fieldSourceStatuses",
            {
                "rows_by_api": {
                    "top300_product_analysis": [
                        {"commodity_id": "1001", "store_name": "A店"},
                        {"commodity_id": "1002", "store_name": "B店"},
                    ],
                },
                "api_execution_plan": [
                    {"api_id": "top300_product_analysis", "status": "called", "source_path_missing_fields": [], "evidence_ref": "evidence/top300.json"},
                ],
                "field_coverage_plan": [
                    {
                        "field_name": "排名",
                        "field_path": "items.properties.rank",
                        "required": True,
                        "mapping_status": "mapped",
                        "source_api_id": "top300_product_analysis",
                        "source_field_path": "data.result[].rank",
                    },
                    {
                        "field_name": "商品链接",
                        "field_path": "items.properties.product_url",
                        "required": True,
                        "mapping_status": "mapped",
                        "source_api_id": "top300_product_analysis",
                        "source_field_path": "data.result[].goods_url",
                    },
                    {
                        "field_name": "店铺名",
                        "field_path": "items.properties.shop_name",
                        "required": True,
                        "mapping_status": "mapped",
                        "source_api_id": "top300_product_analysis",
                        "source_field_path": "data.result[].store_name",
                    },
                ],
            },
        )

        self.assertEqual(result["projection"]["rows"][0]["排名"], 1)
        self.assertEqual(result["projection"]["rows"][1]["排名"], 2)
        self.assertEqual(result["projection"]["rows"][0]["商品链接"], "https://item.taobao.com/item.htm?id=1001")
        by_field = {item["field_name"]: item for item in result["field_sources"]}
        self.assertEqual(by_field["排名"]["value_status"], "present")
        self.assertEqual(by_field["排名"]["source_kind"], "deterministic_derived")
        self.assertEqual(by_field["排名"]["derivation_method"], "row_index_rank")
        self.assertEqual(by_field["商品链接"]["value_status"], "present")
        self.assertEqual(by_field["商品链接"]["source_kind"], "deterministic_derived")
        self.assertEqual(by_field["商品链接"]["derivation_method"], "commodity_id_url")

    def test_runtime_repair_uses_candidate_field_with_live_values(self):
        result = self._function(
            "fieldSourceStatuses",
            {
                "rows_by_api": {
                    "api_empty": [],
                    "api_primary": [{"unit_price": "325.00"}, {"unit_price": "199.00"}],
                },
                "api_execution_plan": [
                    {"api_id": "api_empty", "status": "called", "source_path_missing_fields": [], "evidence_ref": "evidence/empty.json"},
                    {"api_id": "api_primary", "status": "called", "source_path_missing_fields": [], "evidence_ref": "evidence/primary.json"},
                ],
                "field_coverage_plan": [
                    {
                        "field_name": "客单价",
                        "field_path": "items.properties.price",
                        "required": True,
                        "mapping_status": "mapped",
                        "source_api_id": "api_empty",
                        "source_field_path": "data.result[].previous_customer_unit_price",
                        "candidate_field_options": [
                            {
                                "source_api_id": "api_primary",
                                "source_api_name": "主 API",
                                "source_field_path": "data.result[].unit_price",
                                "confidence": 0.9,
                            }
                        ],
                    },
                ],
            },
        )

        self.assertEqual(result["projection"]["rows"][0]["客单价"], "325.00")
        repaired = result["field_coverage_plan"][0]
        self.assertEqual(repaired["source_api_id"], "api_primary")
        self.assertEqual(repaired["source_field_path"], "data.result[].unit_price")
        by_field = {item["field_name"]: item for item in result["field_sources"]}
        self.assertEqual(by_field["客单价"]["value_status"], "present")
        self.assertEqual(by_field["客单价"]["runtime_repair"]["previous_source_api_id"], "api_empty")

    def test_runtime_repair_does_not_replace_agent_derived_fields(self):
        result = self._function(
            "fieldSourceStatuses",
            {
                "rows_by_api": {
                    "growth_api": [{"category_name": "桌布"}],
                },
                "api_execution_plan": [
                    {"api_id": "growth_api", "status": "called", "source_path_missing_fields": [], "evidence_ref": "evidence/growth.json"},
                ],
                "field_coverage_plan": [
                    {
                        "field_name": "产品类型",
                        "field_path": "items.properties.product_type",
                        "required": True,
                        "mapping_status": "derived_or_manual_required",
                        "source_kind": "pi_derived",
                        "source_api_id": "",
                        "source_field_path": "",
                        "candidate_field_options": [
                            {
                                "source_api_id": "growth_api",
                                "source_api_name": "增速 API",
                                "source_field_path": "data.result[].category_name",
                                "confidence": 0.9,
                            }
                        ],
                    },
                ],
            },
        )

        repaired = result["field_coverage_plan"][0]
        self.assertEqual("", repaired["source_api_id"])
        self.assertEqual("", repaired["source_field_path"])
        self.assertNotIn("runtime_repair", repaired)
        self.assertEqual({}, result["projection"]["rows"][0])
        by_field = {item["field_name"]: item for item in result["field_sources"]}
        self.assertEqual("not_called", by_field["产品类型"]["value_status"])

    def test_secondary_join_field_status_uses_projected_overlap(self):
        result = self._function(
            "fieldSourceStatuses",
            {
                "rows_by_api": {
                    "trade_api": [{"goods_id": "a", "rank": 1}, {"goods_id": "b", "rank": 2}],
                    "growth_api": [{"goods_id": "a", "speed_type": "2"}, {"goods_id": "c", "speed_type": "1"}],
                },
                "api_execution_plan": [
                    {"api_id": "trade_api", "execution_role": "topn_trade_total_primary", "status": "called", "source_path_missing_fields": []},
                    {"api_id": "growth_api", "execution_role": "growth_enrichment", "status": "called", "source_path_missing_fields": []},
                ],
                "field_coverage_plan": [
                    {
                        "field_name": "排名",
                        "mapping_status": "mapped",
                        "source_api_id": "trade_api",
                        "source_field_path": "data.result[].rank",
                    },
                    {
                        "field_name": "是否高增速",
                        "mapping_status": "mapped",
                        "source_api_id": "growth_api",
                        "source_field_path": "data.result[].speed_type",
                    },
                ],
            },
        )

        self.assertEqual("高增", result["projection"]["rows"][0]["是否高增速"])
        self.assertNotIn("是否高增速", result["projection"]["rows"][1])
        by_field = {item["field_name"]: item for item in result["field_sources"]}
        self.assertEqual("partial", by_field["是否高增速"]["value_status"])
        self.assertEqual(1, by_field["是否高增速"]["rows_with_value"])
        self.assertEqual(1, by_field["是否高增速"]["rows_missing_value"])

    def test_speed_type_projection_displays_enum_labels_and_keeps_high_growth_semantics(self):
        result = self._function(
            "fieldSourceStatuses",
            {
                "rows_by_api": {
                    "trade_api": [{"goods_id": str(index), "rank": index} for index in range(1, 7)],
                    "growth_api": [{"goods_id": str(index), "speed_type": str(index)} for index in range(1, 7)],
                },
                "api_execution_plan": [
                    {"api_id": "trade_api", "execution_role": "topn_trade_total_primary", "status": "called", "source_path_missing_fields": []},
                    {"api_id": "growth_api", "execution_role": "growth_enrichment", "status": "called", "source_path_missing_fields": []},
                ],
                "field_coverage_plan": [
                    {
                        "field_name": "是否高增速",
                        "mapping_status": "mapped",
                        "source_api_id": "growth_api",
                        "source_field_path": "data.result[].speed_type",
                    },
                ],
            },
        )

        self.assertEqual(
            ["暴涨", "高增", "潜力", "微涨", "持平", "下降"],
            [row["是否高增速"] for row in result["projection"]["rows"]],
        )
        source = result["field_sources"][0]
        self.assertEqual("speed_type_enum", source["value_semantics"]["kind"])
        self.assertEqual(["1", "2", "3"], source["value_semantics"]["high_growth_values"])
        self.assertEqual(["4", "5", "6"], source["value_semantics"]["non_high_growth_values"])

    def test_db_agent_status_degrades_when_spec_pack_is_not_configured(self):
        status, data = self._direct("GET", "/api/db-agent/status")

        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "degraded")
        self.assertEqual(data["reason"], "spec_pack_not_configured")

    def test_db_agent_query_returns_readable_error_when_spec_pack_is_not_configured(self):
        status, data = self._direct("POST", "/api/db-agent/query", {"node_id": "collect_top_products", "action": "tool_plan"})

        self.assertEqual(status, 200)
        self.assertFalse(data["ok"])
        self.assertEqual(data["status"], "degraded")
        self.assertEqual(data["reason"], "spec_pack_not_configured")
        self.assertEqual(data["data_mapping_contract"]["schema_version"], "data-mapping-contract-v2")
        self.assertEqual(data["data_mapping_contract"]["status"], "degraded")
        self.assertEqual(data["data_mapping_contract"]["node_id"], "collect_top_products")
        self.assertIn("field_coverage_plan", data["data_mapping_contract"])

    def test_db_agent_uses_local_api_doc_index_when_spec_pack_is_not_configured(self):
        self._write_local_api_doc_index()

        status, status_body = self._direct("GET", "/api/db-agent/status")
        self.assertEqual(status, 200)
        self.assertEqual(status_body["status"], "ok")
        self.assertEqual(status_body["provider"], "api_doc_index")
        self.assertEqual(status_body["reason"], "api_doc_index_ready")

        status, tool_plan = self._direct(
            "POST",
            "/api/db-agent/query",
            {
                "node_id": "collect_top_products",
                "action": "tool_plan",
                "known_params": {"category": "入户地垫", "period": "近30天"},
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(tool_plan["ok"])
        self.assertEqual(tool_plan["provider"], "api_doc_index")
        self.assertIn("strategy_results", tool_plan["payload"])
        self.assertIn("field_coverage_rerank", tool_plan["payload"]["strategy_results"])
        contract = tool_plan["data_mapping_contract"]
        self.assertIn("api_matching_strategy_results", contract)
        self.assertIn("business_field_coverage_metrics", contract)

        selected_api_ids = tool_plan["payload"]["strategy_results"]["field_coverage_rerank"]["selected_api_ids"]
        self.assertEqual(selected_api_ids[:2], [
            "data_ads_ind_trade_category_goods_m",
            "data_ads_ind_sycm_speed_category_goods_m",
        ])
        self.assertNotIn("top300_product_analysis", selected_api_ids)
        selected_api = "data_ads_ind_trade_category_goods_m"
        status, asset_card = self._direct(
            "POST",
            "/api/db-agent/query",
            {"node_id": "collect_top_products", "action": "asset_card", "api_id": selected_api},
        )
        self.assertEqual(status, 200)
        self.assertTrue(asset_card["ok"])
        api_fields = {item["path"] for item in asset_card["payload"]["api_response_fields"]}
        self.assertIn("data.result[].rank", api_fields)

        status, mapping = self._direct(
            "POST",
            "/api/db-agent/query",
            {
                "node_id": "collect_top_products",
                "action": "suggest_multi_api_mapping",
                "known_params": {"category": "入户地垫", "period": "近30天"},
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(mapping["ok"])
        mapping_contract = mapping["data_mapping_contract"]
        self.assertEqual(len(mapping_contract["field_coverage_plan"]), 17)
        self.assertEqual(mapping["payload"]["coverage_summary"]["total"], 17)
        self.assertEqual(mapping["payload"]["coverage_summary"]["mapped"], 17)
        self.assertEqual(mapping["payload"]["coverage_summary"]["missing_required"], 0)
        self.assertEqual(
            tool_plan["payload"]["selected_api_ids"],
            mapping["payload"]["selected_api_ids"],
        )
        self.assertEqual(mapping_contract["field_coverage_plan"][0]["field_name"], "排名")
        self.assertEqual(mapping_contract["field_coverage_plan"][3]["description"], "看视觉表达")
        self.assertEqual(mapping_contract["field_coverage_plan"][0]["source_kind"], "api_doc_index")
        self.assertTrue(mapping["payload"]["selected_api_asset_cards"])
        self.assertTrue(mapping["payload"]["api_response_field_catalog"])
        self.assertTrue(mapping_contract["api_response_field_catalog"])
        first_with_candidates = next(
            item for item in mapping_contract["field_coverage_plan"]
            if item["field_name"] == "商品主图"
        )
        self.assertTrue(first_with_candidates["candidate_field_options"])
        self.assertTrue(
            any(
                "pic" in candidate["source_field_path"].lower()
                or "image" in candidate["source_field_path"].lower()
                or "picture" in candidate["source_field_path"].lower()
                or "img" in candidate["source_field_path"].lower()
                for candidate in first_with_candidates["candidate_field_options"]
            )
        )
        self.assertIn("derived_field_plan", mapping_contract)
        derived_names = {item["field_name"] for item in mapping_contract["derived_field_plan"]}
        self.assertEqual(derived_names, {"价格带", "产品类型", "材质", "功能", "风格", "场景", "主图元素", "爆款原因"})

    def test_db_agent_does_not_fallback_to_empty_mapping_when_matcher_service_fails(self):
        self._write_local_api_doc_index()
        fake_root = self.app_root / "fake-matcher-root"
        (fake_root / "api_doc_matcher").mkdir(parents=True)
        (fake_root / "api_doc_matcher" / "__init__.py").write_text("", encoding="utf-8")

        status, data = self._direct(
            "POST",
            "/api/db-agent/query",
            {"node_id": "collect_top_products", "action": "suggest_multi_api_mapping"},
            {"API_DOC_MATCHER_ROOT": str(fake_root)},
        )

        self.assertEqual(status, 200)
        self.assertFalse(data["ok"])
        self.assertEqual(data["status"], "degraded")
        self.assertEqual(data["reason"], "matcher_service_unavailable")
        self.assertEqual(data["data_mapping_contract"]["status"], "degraded")
        self.assertNotIn("payload", data)

    def test_db_agent_query_uses_fake_spec_pack_tool_selector(self):
        fake_spec_pack = self._create_fake_spec_pack()
        upstream_artifacts = [
            {
                "source_node_id": "define_scope",
                "artifact": {
                    "title": "《市场洞察项目定义表》",
                    "rows": [
                        {"label": "分析类目", "value": "入户地垫"},
                        {"label": "分析周期", "value": "近30天"},
                        {"label": "分析产品线", "value": "地垫"},
                    ],
                },
            }
        ]

        status, data = self._direct(
            "POST",
            "/api/db-agent/query",
            {"node_id": "collect_top_products", "action": "tool_plan", "upstream_artifacts": upstream_artifacts},
            {"DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack)},
        )

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["action"], "tool_plan")
        self.assertEqual(data["known_params"]["category"], "入户地垫")
        self.assertEqual(data["known_params"]["period"], "近30天")
        self.assertEqual(data["payload"]["recommended_tools"][1]["tool_id"], "auto_商品域_商品分析")
        contract = data["data_mapping_contract"]
        self.assertEqual(contract["schema_version"], "data-mapping-contract-v2")
        self.assertEqual(contract["status"], "suggested")
        self.assertEqual(contract["known_params"]["category"], "入户地垫")
        self.assertEqual(contract["candidate_apis"][0]["api_id"], "/api/category/top-products")
        self.assertIn("source_context_refs", contract)
        self.assertIn("coverage_summary", contract)
        self.assertIn("join_plan", contract)

    def test_db_agent_probe_sample_derives_first_available_api(self):
        fake_spec_pack = self._create_fake_spec_pack()
        upstream_artifacts = [
            {
                "source_node_id": "define_scope",
                "artifact": {
                    "title": "《市场洞察项目定义表》",
                    "rows": [
                        {"label": "分析类目", "value": "沙发垫"},
                        {"label": "分析周期", "value": "近30天"},
                    ],
                },
            }
        ]

        status, data = self._direct(
            "POST",
            "/api/db-agent/query",
            {"node_id": "collect_top_products", "action": "probe_sample", "upstream_artifacts": upstream_artifacts},
            {"DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack), "DBA_LIVE_PROBE": "1"},
        )

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["action"], "probe_sample")
        self.assertEqual(data["payload"]["api_id"], "/api/category/top-products")
        self.assertEqual(len(data["artifact"]["rows"]), 2)
        self.assertEqual(data["data_mapping_contract"]["status"], "sample_ready")
        self.assertEqual(data["data_mapping_contract"]["selected_api"]["api_id"], "/api/category/top-products")
        self.assertIn(data["evidence_ref"], data["data_mapping_contract"]["evidence_refs"])

    def test_db_agent_field_map_matches_required_data_to_api_fields(self):
        fake_spec_pack = self._create_fake_spec_pack()
        upstream_artifacts = [
            {
                "source_node_id": "define_scope",
                "artifact": {
                    "title": "《市场洞察项目定义表》",
                    "rows": [
                        {"label": "分析类目", "value": "沙发垫"},
                        {"label": "分析周期", "value": "近30天"},
                    ],
                },
            }
        ]

        status, data = self._direct(
            "POST",
            "/api/db-agent/query",
            {"node_id": "collect_top_products", "action": "field_map", "upstream_artifacts": upstream_artifacts},
            {"DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack)},
        )

        self.assertEqual(status, 200)
        self.assertFalse(data["ok"])
        self.assertEqual(data["action"], "field_map")
        self.assertEqual(data["status"], "degraded")
        self.assertEqual(data["reason"], "matcher_service_unavailable")
        self.assertEqual(data["matcher_reason"], "api_doc_index_not_configured")
        contract = data["data_mapping_contract"]
        self.assertEqual(contract["status"], "degraded")
        self.assertIn("field_coverage_plan", contract)

    def test_db_agent_asset_card_returns_field_options_for_manual_mapping(self):
        fake_spec_pack = self._create_fake_spec_pack()

        status, data = self._direct(
            "POST",
            "/api/db-agent/query",
            {"node_id": "collect_top_products", "action": "asset_card", "api_id": "/api/category/top-products"},
            {"DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack)},
        )

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["action"], "asset_card")
        self.assertEqual(data["payload"]["selected_api"]["api_id"], "/api/category/top-products")
        api_fields = data["payload"]["api_response_fields"]
        self.assertIn("data.rows.rank", {item["path"] for item in api_fields})
        self.assertIn("rank", {item["field_name"] for item in data["payload"]["output_field_requirements"]})
        self.assertEqual(data["data_mapping_contract"]["selected_api"]["api_id"], "/api/category/top-products")
        self.assertIn("selected_api_asset_card", data["data_mapping_contract"])
        self.assertIn("/api/category/top-products", {item["api_id"] for item in data["data_mapping_contract"]["selected_apis"]})

    def test_db_agent_suggests_and_confirms_multi_api_field_coverage_contract(self):
        self._write_local_api_doc_index()

        status, suggested = self._direct(
            "POST",
            "/api/db-agent/query",
            {
                "node_id": "collect_top_products",
                "action": "suggest_multi_api_mapping",
            },
        )

        self.assertEqual(status, 200)
        self.assertTrue(suggested["ok"])
        contract = suggested["data_mapping_contract"]
        self.assertEqual(contract["schema_version"], "data-mapping-contract-v2")
        self.assertGreaterEqual(len(contract["selected_apis"]), 1)
        coverage_by_field = {item["field_name"]: item for item in contract["field_coverage_plan"]}
        self.assertEqual(coverage_by_field["排名"]["source_api_id"], "data_ads_ind_trade_category_goods_m")
        self.assertEqual(coverage_by_field["主卖点"]["source_field_path"], "data.result[].selling_point")
        self.assertIn("coverage_summary", contract)
        self.assertEqual(contract["coverage_summary"]["total"], 17)
        self.assertEqual(contract["coverage_summary"]["mapped"], 17)
        self.assertEqual(contract["coverage_summary"]["missing_required"], 0)

        status, confirmed = self._direct(
            "POST",
            "/api/db-agent/query",
            {
                "node_id": "collect_top_products",
                "action": "confirm_mapping",
                "selected_apis": contract["selected_apis"],
                "field_coverage_plan": contract["field_coverage_plan"],
                "human_decisions": [{"decision": "confirmed", "target": "multi_api_field_coverage"}],
            },
        )

        self.assertEqual(status, 200)
        self.assertTrue(confirmed["ok"])
        confirmed_contract = confirmed["data_mapping_contract"]
        self.assertEqual(confirmed_contract["schema_version"], "data-mapping-contract-v2")
        self.assertEqual(confirmed_contract["status"], "confirmed")
        self.assertEqual(confirmed_contract["selected_api"]["api_id"], "top300_product_analysis")
        contract_path = self.app_root / "evidence" / "collect_top_products.data_mapping_contract.json"
        self.assertTrue(contract_path.exists())

    def test_db_agent_save_and_confirm_manual_field_mapping_contract(self):
        mapping = [
            {
                "output_id": "top_300_product_analysis_table",
                "field_path": "items.properties.rank",
                "field_name": "rank",
                "api_field_path": "data.rows.rank",
                "api_field_name": "rank",
                "api_field_type": "number",
                "source_api_id": "/api/category/top-products",
                "source_api_name": "类目商品排行",
                "source_field_path": "data.rows.rank",
                "status": "mapped",
                "human_note": "排名字段确认",
            }
        ]

        status, draft = self._direct(
            "POST",
            "/api/db-agent/query",
            {
                "node_id": "collect_top_products",
                "action": "save_field_mapping",
                "api_id": "/api/category/top-products",
                "manual_response_field_mapping": mapping,
            },
        )

        self.assertEqual(status, 200)
        self.assertTrue(draft["ok"])
        self.assertEqual(draft["data_mapping_contract"]["status"], "suggested")
        overlay = draft["data_mapping_contract"]["output_field_mapping_overlay"]
        self.assertEqual(overlay[0]["api_field_path"], "data.rows.rank")
        draft_path = self.app_root / "evidence" / "collect_top_products.data_mapping_contract.draft.json"
        self.assertTrue(draft_path.exists())

        status, confirmed = self._direct(
            "POST",
            "/api/db-agent/query",
            {
                "node_id": "collect_top_products",
                "action": "confirm_mapping",
                "api_id": "/api/category/top-products",
                "manual_response_field_mapping": mapping,
                "human_decisions": [{"decision": "confirmed", "target": "response_field_mapping"}],
            },
        )

        self.assertEqual(status, 200)
        self.assertTrue(confirmed["ok"])
        self.assertEqual(confirmed["data_mapping_contract"]["status"], "confirmed")
        self.assertIn("evidence/collect_top_products.data_mapping_contract.json", confirmed["data_mapping_contract"]["evidence_refs"])
        contract_path = self.app_root / "evidence" / "collect_top_products.data_mapping_contract.json"
        self.assertTrue(contract_path.exists())

    def test_db_agent_field_map_without_source_api_returns_needs_input_contract(self):
        fake_spec_pack = self._create_fake_spec_pack()
        (fake_spec_pack / "src" / "tools" / "select_tools_for_task.mjs").write_text(
            """
export function selectToolsForTask(args) {
  return {
    task: args.task,
    intent: '类目 | 商品',
    recommended_tools: [
      {
        tool_id: 'auto_商品域_待选工具',
        call_order: 1,
        reason: 'fixture intentionally has no concrete API',
        required_params: ['category'],
        missing_params: [],
        source_apis: [],
        quality_score: 0.4,
        risks: ['no source api']
      }
    ],
    blocked_or_deprioritized: [],
    next_question: '请选择可用 API。'
  };
}
""",
            encoding="utf-8",
        )

        status, data = self._direct(
            "POST",
            "/api/db-agent/query",
            {"node_id": "collect_top_products", "action": "field_map", "known_params": {"category": "沙发垫"}},
            {"DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack)},
        )

        self.assertEqual(status, 200)
        self.assertFalse(data["ok"])
        self.assertEqual(data["status"], "degraded")
        self.assertEqual(data["reason"], "matcher_service_unavailable")
        self.assertEqual(data["matcher_reason"], "api_doc_index_not_configured")
        self.assertEqual(data["data_mapping_contract"]["status"], "degraded")

    def test_db_agent_probe_sample_without_live_probe_returns_blocked_contract(self):
        fake_spec_pack = self._create_fake_spec_pack()

        status, data = self._direct(
            "POST",
            "/api/db-agent/query",
            {"node_id": "collect_top_products", "action": "probe_sample", "known_params": {"category": "沙发垫"}},
            {"DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack)},
        )

        self.assertEqual(status, 200)
        self.assertFalse(data["ok"])
        self.assertEqual(data["status"], "blocked")
        self.assertEqual(data["reason"], "live_probe_disabled")
        self.assertEqual(data["next_step"], "设置 DBA_LIVE_PROBE=1 并重启应用后再尝试样例取数。")
        self.assertEqual(data["data_mapping_contract"]["status"], "blocked")

    def test_data_analysis_node_run_builds_execution_plan_without_fake_rows(self):
        self._write_local_api_doc_index()
        upstream_artifacts = [
            {
                "source_node_id": "define_scope",
                "artifact": {
                    "title": "《市场洞察项目定义表》",
                    "rows": [
                        {"label": "分析类目", "value": "入户地垫"},
                        {"label": "分析周期", "value": "近30天"},
                        {"label": "分析产品线", "value": "地垫"},
                    ],
                },
            }
        ]

        status, data = self._direct(
            "POST",
            "/api/nodes/collect_top_products/run",
            {"upstream_artifacts": upstream_artifacts, "execution_date": "2026-07-09"},
        )

        self.assertEqual(status, 200)
        result = data["result"]
        self.assertEqual(result["schema_version"], "data-analysis-execution-v1")
        self.assertEqual(result["node_id"], "collect_top_products")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["known_params"]["category"], "入户地垫")
        self.assertTrue(result["api_execution_plan"])
        first_plan = result["api_execution_plan"][0]
        self.assertIn("request_param_mapping", first_plan)
        self.assertIn("params", first_plan)
        self.assertTrue(
            any(item["business_param"] in {"category", "period", "page"} for item in first_plan["request_param_mapping"])
        )
        trade_plan = next(item for item in result["api_execution_plan"] if item["api_id"] == "data_ads_ind_trade_category_goods_m")
        self.assertEqual(trade_plan["request_param_binding_provider"], "api_doc_matcher")
        self.assertEqual(trade_plan["params"]["start_date"], "2026-06-01")
        self.assertEqual(trade_plan["params"]["end_date"], "2026-06-01")
        self.assertEqual(trade_plan["params"]["pageNum"], 1)
        self.assertEqual(trade_plan["params"]["pageSize"], 20)
        start_date_mapping = next(item for item in trade_plan["request_param_mapping"] if item["api_param"] == "start_date")
        self.assertEqual(start_date_mapping["binding_method"], "api_doc_matcher_date_normalization")
        self.assertEqual(start_date_mapping["date_conversion_rule"], "start_date")
        self.assertEqual(start_date_mapping["normalized_period"]["grain"], "month")
        self.assertTrue(result["data_table_ref"])
        table_path = self.app_root / result["data_table_ref"]
        self.assertTrue(table_path.exists())
        table = json.loads(table_path.read_text(encoding="utf-8"))
        self.assertEqual(table["schema_version"], "data-table-draft-v1")
        self.assertEqual(table["rows"], [])
        self.assertTrue(table["field_sources"])
        self.assertTrue(all(item["value_status"] == "not_called" for item in table["field_sources"] if item["mapping_status"] in {"mapped", "suggested"}))
        self.assertTrue((self.app_root / result["execution_trace_ref"]).exists())

    def test_legacy_llm_kind_with_data_analysis_view_uses_data_executor(self):
        self._write_local_api_doc_index()
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        config["nodes"].append(
            {
                "id": "analyze_competitors",
                "name": "竞品与竞店格局分析",
                "kind": "llm",
                "source_type": "multi_source_analysis",
                "depends_on": ["collect_top_products"],
                "data_requirements": ["competitor_landscape"],
                "outputs": ["competitor_landscape_table"],
                "output_field_requirements": [
                    {
                        "output_id": "competitor_landscape_table",
                        "field_path": "items.properties.shop_name",
                        "field_name": "shop_name",
                        "title": "shop_name",
                        "description": "店铺名称",
                        "canonical_field_name": "shop_name",
                        "type": "string",
                        "required": True,
                    }
                ],
                "analysis_node_view": {
                    "schema_version": "analysis-node-view-v1",
                    "node_id": "analyze_competitors",
                    "node_kind": "data_analysis",
                    "purpose_model": {"purpose": "分析竞品格局"},
                    "input_model": {"data_sources": [{"description": "竞品格局"}]},
                    "execution_plan": {"steps": [{"instruction": "获取竞品数据"}]},
                    "data_output_model": {"fields": []},
                },
                "state_machine": [],
            }
        )
        self.config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

        status, data = self._direct(
            "POST",
            "/api/nodes/analyze_competitors/run",
            {
                "known_params": {"category": "桌布", "cid": "121458013", "period": "近30天"},
                "execution_date": "2026-07-09",
            },
        )

        self.assertEqual(200, status)
        self.assertNotEqual("mock_llm", data["result"]["status"])
        self.assertEqual("data-analysis-execution-v1", data["result"]["schema_version"])

    def test_competitor_projection_preserves_top_product_order_and_joins_by_goods_id(self):
        result = self._function(
            "competitorProjection",
            {
                "source_products": [
                    {
                        "goods_id": "goods-2",
                        "product_url": "https://fixture.test/?id=goods-2",
                        "row": {"店铺名": "上游店2", "客单价": "52", "主卖点": "上游卖点2", "主图元素": "白底"},
                        "row_meta": {"row_id": "goods:goods-2"},
                    },
                    {
                        "goods_id": "goods-1",
                        "product_url": "https://fixture.test/?id=goods-1",
                        "row": {"店铺名": "上游店1", "客单价": "51", "主卖点": "上游卖点1"},
                        "row_meta": {"row_id": "goods:goods-1"},
                    },
                ],
                "competitor_rows": [
                    {
                        "goods_id": "goods-1", "shop_name": "API店1", "goods_href": "https://api.test/goods-1",
                        "price": 61, "main_selling_point": "API卖点1", "main_sku": "大号", "sales_total": 100,
                    },
                    {
                        "goods_id": "goods-2", "shop_name": "API店2", "goods_href": "https://api.test/goods-2",
                        "price": 62, "main_selling_point": "API卖点2", "main_color": "透明", "sales_total": 200,
                    },
                ],
                "review_rows": [
                    {"goods_id": "goods-2", "review_text": "容易卷边"},
                    {"goods_id": "goods-2", "qa_question": "尺寸有误差吗"},
                    {"goods_id": "goods-1", "review_text": "气味较重"},
                ],
            },
        )

        self.assertEqual(["goods-2", "goods-1"], result["row_identities"])
        self.assertEqual(2, len(result["rows"]))
        self.assertEqual("API店2", result["rows"][0]["shop_name"])
        self.assertEqual("https://api.test/goods-2", result["rows"][0]["product_url"])
        self.assertEqual(62, result["rows"][0]["price"])
        self.assertEqual(["容易卷边", "尺寸有误差吗"], result["rows"][0]["review_evidence"])
        self.assertNotIn("sku_count", result["rows"][0])
        self.assertNotIn("traffic_structure", result["rows"][0])
        self.assertEqual("competitor_join_by_goods_id", result["merge_strategy"])
        self.assertEqual(2, result["matched_products"])
        self.assertEqual(3, result["review_records_used"])

    def test_competitor_node_blocks_without_confirmed_top_products(self):
        self._write_local_api_doc_index()
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        config["nodes"].append(
            {
                "id": "analyze_competitors",
                "name": "竞品与竞店格局分析",
                "kind": "data",
                "source_type": "multi_source_analysis",
                "depends_on": ["collect_top_products", "collect_reviews_qa"],
                "data_requirements": ["competitor_landscape"],
                "outputs": ["competitor_landscape_table"],
                "output_field_requirements": [
                    {
                        "output_id": "competitor_landscape_table", "field_path": "items.properties.shop_name",
                        "field_name": "shop_name", "title": "shop_name", "description": "店铺名称",
                        "canonical_field_name": "shop_name", "type": "string", "required": True,
                    }
                ],
                "analysis_node_view": {
                    "node_kind": "data_analysis",
                    "purpose_model": {"purpose": "分析竞品格局"},
                    "input_model": {"data_sources": [{"description": "竞品格局"}]},
                    "execution_plan": {"steps": [{"instruction": "获取竞品数据"}]},
                    "data_output_model": {"fields": []},
                },
                "state_machine": [],
            }
        )
        self.config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

        status, data = self._direct("POST", "/api/nodes/analyze_competitors/run", {"known_params": {"category": "桌布"}})

        self.assertEqual(200, status)
        self.assertEqual("blocked", data["result"]["status"])
        self.assertIn("source_table_not_confirmed", data["result"]["blocked_reasons"])

    def test_competitor_node_merges_confirmed_products_api_and_reviews_by_goods_id(self):
        self._write_local_api_doc_index()
        self._append_competitor_analysis_to_local_index()
        self._write_gene_analysis_source_fixture(count=2, revision=3)
        self._write_confirmed_competitor_reviews()
        artifacts = self.app_root / "artifacts"
        (artifacts / "business_category_context.json").write_text(
            json.dumps(
                {
                    "schema_version": "business-category-context-v1",
                    "requested_name": "桌垫",
                    "canonical_name": "桌布",
                    "category_id": "121458013",
                    "aliases": ["桌垫", "桌布"],
                    "status": "resolved",
                    "source_node_id": "collect_top_products",
                    "source_revision": 3,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        fake_spec_pack = self._create_fake_spec_pack()

        status, data = self._direct(
            "POST",
            "/api/nodes/analyze_competitors/run",
            {"known_params": {"period": "2026-06-01"}, "execution_date": "2026-07-23", "top_n": 2},
            {"DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack), "DBA_LIVE_PROBE": "1"},
        )

        self.assertEqual(200, status)
        result = data["result"]
        self.assertNotEqual("mock_llm", result["status"])
        self.assertEqual("agent_enrichment_pending", result["status"])
        plan = next(item for item in result["api_execution_plan"] if item["execution_role"] == "competitor_landscape_primary")
        self.assertEqual("called", plan["status"])
        self.assertEqual("121458013", str(plan["params"]["cid"]))
        self.assertEqual("2026-06-01", plan["params"]["start_date"])
        self.assertEqual("2026-06-01", plan["params"]["end_date"])

        table = json.loads((self.app_root / result["data_table_ref"]).read_text(encoding="utf-8"))
        self.assertEqual("agent_enrichment_pending", table["status"])
        self.assertEqual(["gene-1", "gene-2"], [item["source_identity"] for item in table["row_meta"]])
        self.assertEqual("竞品店铺-gene-1", table["rows"][0]["shop_name"])
        self.assertEqual(["容易卷边", "尺寸有误差吗"], table["rows"][1]["review_evidence"])
        self.assertNotIn("sku_count", table["rows"][0])
        self.assertNotIn("traffic_structure", table["rows"][0])
        self.assertEqual("competitor_join_by_goods_id", table["merge_strategy"])
        self.assertEqual(2, table["competitor_enrichment"]["matched_products"])
        self.assertEqual(3, table["competitor_enrichment"]["review_records_used"])
        self.assertEqual(
            {"competitor_type", "visual_structure", "review_painpoints", "competitor_strength"},
            set(table["competitor_enrichment"]["fillable_fields"]),
        )
        status, workspace = self._direct("GET", "/api/nodes/analyze_competitors/data-table-workspace")
        self.assertEqual(200, status)
        self.assertEqual("competitor", workspace["agent_enrichment"]["subject_kind"])
        self.assertEqual(
            {"competitor_type", "visual_structure", "review_painpoints", "competitor_strength"},
            set(workspace["agent_enrichment"]["fillable_fields"]),
        )
        self.assertEqual(8, workspace["agent_enrichment"]["remaining_cells"])

        prompt_capture = self.app_root / "competitor_agent_batch_prompts.jsonl"
        fake_pi = self.app_root / "fake_pi_competitor_agent_batch"
        fake_pi.write_text(
            "#!/usr/bin/env node\n"
            "const fs = require('fs');\n"
            "let request = '';\n"
            "process.stdin.setEncoding('utf8');\n"
            "process.stdin.once('data', chunk => { request += chunk;\n"
            "  const payload = JSON.parse(request.trim());\n"
            f"  fs.appendFileSync({json.dumps(str(prompt_capture))}, JSON.stringify(payload) + '\\n');\n"
            "  const rowId = (payload.message.match(/\\\"row_id\\\": \\\"([^\\\"]+)/) || [])[1] || '';\n"
            "  const competitorType = rowId.endsWith('gene-2') ? '未知竞品' : '直接竞品';\n"
            "  const proposal = {schema_version:'pi-data-mapping-advice-v1',node_id:'analyze_competitors',summary:{status:'needs_review',text:'竞品建议'},field_advice:[],table_edit_proposal:{schema_version:'data-table-edit-proposal-v1',patches:[\n"
            "    {row_id:rowId,field_path:'competitor_type',old_value:'',new_value:competitorType,reason:'排名价格证据',confidence:0.9,evidence_refs:[]},\n"
            "    {row_id:rowId,field_path:'visual_structure',old_value:'',new_value:'透明主色、商品特写',reason:'主色与主图URL',confidence:0.7,evidence_refs:[]},\n"
            "    {row_id:rowId,field_path:'review_painpoints',old_value:'',new_value:'尺寸与卷边',reason:'评价与问大家',confidence:0.8,evidence_refs:[]},\n"
            "    {row_id:rowId,field_path:'competitor_strength',old_value:'',new_value:'销量领先',reason:'销量证据',confidence:0.8,evidence_refs:[]},\n"
            "    {row_id:rowId,field_path:'price',old_value:'',new_value:1,reason:'越界修改事实',confidence:1,evidence_refs:[]}\n"
            "  ]}};\n"
            "  process.stdout.write(JSON.stringify({type:'agent_start',model:'gpt-5.6-sol'}) + '\\n');\n"
            "  process.stdout.write(JSON.stringify({type:'message_update',assistantMessageEvent:{type:'text_delta',delta:JSON.stringify(proposal)}}) + '\\n');\n"
            "  process.stdout.write('{\"type\":\"agent_end\",\"messages\":[],\"willRetry\":false}\\n');\n"
            "});\n",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)
        status, started = self._direct(
            "POST",
            "/api/nodes/analyze_competitors/agent-thread/batches",
            {"base_revision": workspace["workspace"]["revision"], "page_number": 1, "page_size": 10},
            {
                "PI_BIN": str(fake_pi),
                "AICODEMIRROR_API_KEY": "sk-test",
                "PI_DEFAULT_MODEL": "aicodemirror/gpt-5.6-sol",
                "PI_RPC_TIMEOUT_MS": "3000",
            },
        )
        self.assertEqual(202, status)
        status, loaded = self._direct(
            "GET", f"/api/nodes/analyze_competitors/agent-thread/batches/{started['batch_id']}"
        )
        self.assertEqual(200, status)
        batch = loaded["batch"]
        self.assertEqual("competitor", batch["subject_kind"])
        self.assertEqual(8, batch["progress"]["target_cells"])
        self.assertEqual(7, batch["progress"]["proposed_cells"])
        self.assertFalse(any(item["field_path"] == "price" for item in batch["proposals"]))
        invalid_item = next(item for item in batch["items"] if item["row_id"] == "goods:gene-2")
        self.assertIn("invalid_competitor_type_rejected", invalid_item["proposal_risks"])
        prompts = [json.loads(line)["message"] for line in prompt_capture.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(2, len(prompts))
        gene_2_prompt = next(prompt for prompt in prompts if '"row_id": "goods:gene-2"' in prompt)
        self.assertIn("容易卷边", gene_2_prompt)
        self.assertIn("尺寸有误差吗", gene_2_prompt)
        self.assertNotIn('"row_id": "goods:gene-1"', gene_2_prompt)

        status, unchanged = self._direct("GET", "/api/nodes/analyze_competitors/data-table-workspace")
        self.assertEqual(200, status)
        self.assertTrue(all(not row.get("competitor_type") for row in unchanged["effective_rows"]))

    def test_competitor_api_empty_keeps_confirmed_product_facts(self):
        self._write_local_api_doc_index()
        self._append_competitor_analysis_to_local_index()
        self._write_gene_analysis_source_fixture(count=2, revision=3)
        fake_spec_pack = self._create_fake_spec_pack()

        status, data = self._direct(
            "POST",
            "/api/nodes/analyze_competitors/run",
            {
                "known_params": {"category": "桌布", "cid": "121458013", "period": "2026-06-01"},
                "execution_date": "2026-07-23",
                "top_n": 2,
            },
            {
                "DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack),
                "DBA_LIVE_PROBE": "1",
                "TEST_COMPETITOR_EMPTY": "1",
            },
        )

        self.assertEqual(200, status)
        result = data["result"]
        self.assertEqual("partial_data_table_ready", result["status"])
        self.assertIn("competitor_api_empty", result["risks"])
        table = json.loads((self.app_root / result["data_table_ref"]).read_text(encoding="utf-8"))
        self.assertEqual(2, len(table["rows"]))
        self.assertEqual("https://fixture.test/?id=gene-1", table["rows"][0]["product_url"])
        self.assertEqual("50", table["rows"][0]["price"])
        self.assertEqual("食品级无味，防油易清洁", table["rows"][0]["main_selling_point"])
        self.assertEqual(0, table["competitor_enrichment"]["matched_products"])

    def test_data_analysis_node_run_marks_missing_source_field_path(self):
        self._write_local_api_doc_index()
        field_coverage_plan = [
            {
                "field_name": "排名",
                "field_path": "items.properties.rank",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "top300_product_analysis",
                "source_field_path": "",
            }
        ]

        status, data = self._direct(
            "POST",
            "/api/nodes/collect_top_products/run",
            {
                "known_params": {"category": "入户地垫", "period": "近30天"},
                "field_coverage_plan": field_coverage_plan,
            },
        )

        self.assertEqual(status, 200)
        result = data["result"]
        self.assertEqual(result["status"], "blocked")
        self.assertIn("source_path_missing", result["blocked_reasons"])
        table = json.loads((self.app_root / result["data_table_ref"]).read_text(encoding="utf-8"))
        rank_source = next(item for item in table["field_sources"] if item["field_name"] == "排名")
        self.assertEqual(rank_source["value_status"], "source_path_missing")
        self.assertTrue(table["risks"])

    def test_data_analysis_node_run_does_not_block_api_when_one_field_lacks_source_path(self):
        self._write_local_api_doc_index()
        fake_spec_pack = self._create_fake_spec_pack()
        field_coverage_plan = [
            {
                "field_name": "排名",
                "field_path": "items.properties.rank",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "/api/category/top-products",
                "source_api_name": "类目商品排行",
                "source_field_path": "data.rows.rank",
            },
            {
                "field_name": "店铺名",
                "field_path": "items.properties.shop_name",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "/api/category/top-products",
                "source_api_name": "类目商品排行",
                "source_field_path": "",
            },
        ]

        status, data = self._direct(
            "POST",
            "/api/nodes/collect_top_products/run",
            {
                "known_params": {
                    "category": "沙发垫",
                    "start_date": "2026-06-01",
                    "end_date": "2026-06-30",
                },
                "field_coverage_plan": field_coverage_plan,
            },
            {"DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack), "DBA_LIVE_PROBE": "1"},
        )

        self.assertEqual(status, 200)
        result = data["result"]
        plan = next(item for item in result["api_execution_plan"] if item["api_id"] == "/api/category/top-products")
        self.assertEqual(plan["status"], "called")
        table = json.loads((self.app_root / result["data_table_ref"]).read_text(encoding="utf-8"))
        self.assertEqual(table["rows"][0]["排名"], 1)
        by_field = {item["field_name"]: item for item in table["field_sources"]}
        self.assertEqual(by_field["排名"]["value_status"], "present")
        self.assertEqual(by_field["店铺名"]["value_status"], "source_path_missing")

    def test_data_analysis_node_run_projects_live_probe_rows_to_business_fields(self):
        self._write_local_api_doc_index()
        fake_spec_pack = self._create_fake_spec_pack()
        field_coverage_plan = [
            {
                "field_name": "排名",
                "field_path": "items.properties.rank",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "/api/category/top-products",
                "source_api_name": "类目商品排行",
                "source_field_path": "data.rows.rank",
            },
            {
                "field_name": "客单价",
                "field_path": "items.properties.price",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "/api/category/top-products",
                "source_api_name": "类目商品排行",
                "source_field_path": "data.rows.price",
            },
        ]

        status, data = self._direct(
            "POST",
            "/api/nodes/collect_top_products/run",
            {
                "known_params": {
                    "category": "沙发垫",
                    "start_date": "2026-06-01",
                    "end_date": "2026-06-30",
                },
                "field_coverage_plan": field_coverage_plan,
            },
            {"DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack), "DBA_LIVE_PROBE": "1"},
        )

        self.assertEqual(status, 200)
        result = data["result"]
        self.assertEqual(result["status"], "partial_data_table_ready")
        self.assertEqual(result["api_execution_plan"][0]["status"], "called")
        self.assertEqual(result["api_execution_plan"][0]["params"]["start_date"], "2026-06-01")
        table = json.loads((self.app_root / result["data_table_ref"]).read_text(encoding="utf-8"))
        self.assertEqual(table["rows"][0]["排名"], 1)
        self.assertEqual(table["rows"][0]["客单价"], 99)
        rank_source = next(item for item in table["field_sources"] if item["field_name"] == "排名")
        self.assertEqual(rank_source["value_status"], "present")
        self.assertTrue((self.app_root / "artifacts" / "collect_top_products.db_agent.json").exists())

    def test_data_analysis_node_run_defers_derived_fields_to_interactive_agent(self):
        self._write_local_api_doc_index()
        fake_spec_pack = self._create_fake_spec_pack()
        fake_pi = self.app_root / "fake_pi_derived_rows"
        fake_pi.write_text(
            """#!/usr/bin/env node
process.stdin.once('data', () => {
  require('fs').writeFileSync(process.env.PI_CALLED, '1');
  const advice = {
    schema_version: 'pi-data-mapping-advice-v1',
    node_id: 'collect_top_products',
    summary: { status: 'needs_review', text: '派生字段草稿' },
    field_advice: [],
    derived_field_advice: [
      { field_name: '功能', status: 'draft', draft_value: '防滑', confidence: 0.7 }
    ],
    derived_field_rows: [
      { row_index: 0, fields: { 功能: { draft_value: '防滑', confidence: 0.7, evidence_fields: ['排名'] } } },
      { row_index: 1, fields: { 功能: { draft_value: '防水', confidence: 0.6, evidence_fields: ['排名'] } } }
    ],
    requires_human_confirmation: true
  };
  console.log(JSON.stringify({ type: 'message_delta', text: JSON.stringify(advice) }));
  console.log(JSON.stringify({ type: 'agent_end', messages: [], willRetry: false }));
});
""",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)
        field_coverage_plan = [
            {
                "field_name": "排名",
                "field_path": "items.properties.rank",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "/api/category/top-products",
                "source_api_name": "类目商品排行",
                "source_field_path": "data.rows.rank",
            },
            {
                "field_name": "功能",
                "field_path": "items.properties.function",
                "required": True,
                "mapping_status": "derived_or_manual_required",
                "source_kind": "pi_derived",
            },
        ]

        status, data = self._direct(
            "POST",
            "/api/nodes/collect_top_products/run",
            {
                "known_params": {
                    "category": "沙发垫",
                    "start_date": "2026-06-01",
                    "end_date": "2026-06-30",
                },
                "field_coverage_plan": field_coverage_plan,
            },
            {
                "DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack),
                "DBA_LIVE_PROBE": "1",
                "PI_BIN": str(fake_pi),
                "AICODEMIRROR_API_KEY": "sk-aicodemirror-secret",
                "PI_CALLED": str(self.app_root / "pi_called"),
                "PI_RPC_TIMEOUT_MS": "3000",
            },
        )

        self.assertEqual(status, 200)
        result = data["result"]
        table = json.loads((self.app_root / result["data_table_ref"]).read_text(encoding="utf-8"))
        self.assertNotIn("功能", table["rows"][0])
        self.assertNotIn("功能", table["rows"][1])
        function_source = next(item for item in table["field_sources"] if item["field_name"] == "功能")
        self.assertEqual(function_source["value_status"], "not_called")
        self.assertEqual(function_source["source_kind"], "pi_derived")
        self.assertTrue(table["derived_fields"])
        self.assertFalse((self.app_root / "pi_called").exists())
        trace = json.loads((self.app_root / result["execution_trace_ref"]).read_text(encoding="utf-8"))
        self.assertEqual(trace["pi_calls"], [])

    def test_data_analysis_node_run_preserves_api_values_without_automatic_pi(self):
        self._write_local_api_doc_index()
        fake_spec_pack = self._create_fake_spec_pack()
        fake_pi = self.app_root / "fake_pi_overwrite_attempt"
        fake_pi.write_text(
            """#!/usr/bin/env node
process.stdin.once('data', () => {
  const advice = {
    schema_version: 'pi-data-mapping-advice-v1',
    node_id: 'collect_top_products',
    summary: { status: 'needs_review', text: '包含越权字段的派生草稿' },
    field_advice: [],
    derived_field_advice: [{ field_name: '功能', status: 'draft', draft_value: '防滑', confidence: 0.7 }],
    derived_field_rows: [
      { row_index: 0, fields: {
        排名: { draft_value: 999, confidence: 0.99, evidence_fields: ['排名'] },
        功能: { draft_value: '防滑', confidence: 0.7, evidence_fields: ['排名'] }
      } }
    ],
    requires_human_confirmation: true
  };
  console.log(JSON.stringify({ type: 'message_delta', text: JSON.stringify(advice) }));
  console.log(JSON.stringify({ type: 'agent_end', messages: [], willRetry: false }));
});
""",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)
        field_coverage_plan = [
            {
                "field_name": "排名",
                "field_path": "items.properties.rank",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "/api/category/top-products",
                "source_api_name": "类目商品排行",
                "source_field_path": "data.rows.rank",
            },
            {
                "field_name": "功能",
                "field_path": "items.properties.function",
                "required": True,
                "mapping_status": "derived_or_manual_required",
                "source_kind": "pi_derived",
            },
        ]

        status, data = self._direct(
            "POST",
            "/api/nodes/collect_top_products/run",
            {
                "known_params": {"category": "沙发垫", "start_date": "2026-06-01", "end_date": "2026-06-30"},
                "field_coverage_plan": field_coverage_plan,
            },
            {
                "DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack),
                "DBA_LIVE_PROBE": "1",
                "PI_BIN": str(fake_pi),
                "AICODEMIRROR_API_KEY": "sk-aicodemirror-secret",
                "PI_RPC_TIMEOUT_MS": "3000",
            },
        )

        self.assertEqual(status, 200)
        result = data["result"]
        table = json.loads((self.app_root / result["data_table_ref"]).read_text(encoding="utf-8"))
        self.assertEqual(table["rows"][0]["排名"], 1)
        self.assertNotIn("功能", table["rows"][0])
        rank_source = next(item for item in table["field_sources"] if item["field_name"] == "排名")
        self.assertNotEqual(rank_source["source_kind"], "pi_derived")

    def test_data_analysis_node_resolves_category_name_to_cid_before_probe(self):
        self._write_local_api_doc_index()
        fake_spec_pack = self._create_fake_spec_pack()
        field_coverage_plan = [
            {
                "field_name": "商品链接",
                "field_path": "items.properties.product_url",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "data_ads_ind_sycm_speed_category_goods_m",
                "source_api_name": "月-热销商品-按交易增速排序",
                "source_field_path": "data.result[].goods_url",
            }
        ]

        status, data = self._direct(
            "POST",
            "/api/nodes/collect_top_products/run",
            {
                "known_params": {"category": "沙发垫", "period": "近30天"},
                "field_coverage_plan": field_coverage_plan,
            },
            {"DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack), "DBA_LIVE_PROBE": "1"},
        )

        self.assertEqual(status, 200)
        result = data["result"]
        plan = next(item for item in result["api_execution_plan"] if item["api_id"] == "data_ads_ind_sycm_speed_category_goods_m")
        self.assertEqual(plan["category_resolution"]["status"], "resolved")
        self.assertEqual(plan["category_resolution"]["direction"], "name_to_id")
        self.assertEqual(plan["category_resolution"]["resolver_provider"], "api_doc_matcher")
        self.assertEqual(plan["category_resolution"]["source_api_id"], "category_resolver_api")
        self.assertEqual(plan["category_resolution"]["category_id"], "50020776")
        self.assertEqual(plan["params"]["cid"], "50020776")
        self.assertNotIn("category_id_required", result["blocked_reasons"])
        resolver_calls = [item for item in json.loads((self.app_root / result["execution_trace_ref"]).read_text(encoding="utf-8"))["api_calls"] if item.get("purpose") == "category_resolution"]
        self.assertTrue(resolver_calls)
        self.assertEqual(resolver_calls[0]["resolver_provider"], "api_doc_matcher")
        self.assertIn("request_debug", resolver_calls[0])
        table = json.loads((self.app_root / result["data_table_ref"]).read_text(encoding="utf-8"))
        self.assertEqual(table["rows"][0]["商品链接"], "https://fixture.test/desk/1")
        self.assertNotIn("字段来源", table["rows"][0])
        self.assertTrue(table["field_sources"])
        self.assertTrue(any(src.get("field_name") == "商品链接" for src in table["field_sources"]))

    def test_data_analysis_node_uses_evidence_category_candidate_and_excludes_unscoped_rows(self):
        self._write_local_api_doc_index()
        fake_spec_pack = self._create_fake_spec_pack()
        field_coverage_plan = [
            {
                "field_name": "排名",
                "field_path": "items.properties.rank",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "data_ads_ind_trade_category_goods_m",
                "source_api_name": "月-热销商品-按交易总量排序",
                "source_field_path": "data.result[].rank",
            },
            {
                "field_name": "商品链接",
                "field_path": "items.properties.product_url",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "data_ads_ind_trade_category_goods_m",
                "source_api_name": "月-热销商品-按交易总量排序",
                "source_field_path": "data.result[].goods_url",
            },
            {
                "field_name": "是否高增速",
                "field_path": "items.properties.growth_flag",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "data_ads_ind_sycm_speed_category_goods_m",
                "source_api_name": "月-热销商品-按交易增速排序",
                "source_field_path": "data.result[].speed_type",
            },
        ]

        status, data = self._direct(
            "POST",
            "/api/nodes/collect_top_products/run",
            {
                "known_params": {"category": "桌垫", "period": "近30天"},
                "field_coverage_plan": field_coverage_plan,
                "execution_date": "2026-07-15",
            },
            {"DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack), "DBA_LIVE_PROBE": "1"},
        )

        self.assertEqual(200, status)
        result = data["result"]
        self.assertEqual("resolved", result["category_resolution"]["status"])
        self.assertEqual("桌垫", result["category_resolution"]["requested_name"])
        self.assertEqual("桌布", result["category_resolution"]["canonical_name"])
        self.assertEqual("121458013", result["category_resolution"]["category_id"])
        trade_plan = next(item for item in result["api_execution_plan"] if item["api_id"] == "data_ads_ind_trade_category_goods_m")
        self.assertEqual("121458013", trade_plan["params"]["cid"])
        self.assertEqual("2026-06-01", trade_plan["params"]["start_date"])
        self.assertEqual("2026-06-01", trade_plan["params"]["end_date"])
        self.assertEqual("matched", trade_plan["scope_validation_status"])
        speed_plan = next(item for item in result["api_execution_plan"] if item["api_id"] == "data_ads_ind_sycm_speed_category_goods_m")
        self.assertEqual("121458013", speed_plan["params"]["cid"])
        self.assertEqual(300, speed_plan["params"]["pageSize"])
        self.assertEqual(60, speed_plan["rows_returned"])
        self.assertEqual("matched", speed_plan["scope_validation_status"])
        self.assertNotIn("top300_product_analysis", {item["api_id"] for item in result["api_execution_plan"]})
        table = json.loads((self.app_root / result["data_table_ref"]).read_text(encoding="utf-8"))
        self.assertEqual("data_ads_ind_trade_category_goods_m", table["primary_api_id"])
        self.assertEqual("key_join", table["merge_strategy"])
        self.assertEqual(["data_ads_ind_sycm_speed_category_goods_m"], table["key_joined_api_ids"])
        self.assertEqual("https://fixture.test/desk/1", table["rows"][0]["商品链接"])
        self.assertEqual("高增", table["rows"][0]["是否高增速"])
        self.assertEqual([], table["join_blocked_api_ids"])

    def test_data_analysis_node_batch_enriches_product_details_by_goods_id(self):
        self._write_local_api_doc_index()
        self._append_product_detail_to_local_index()
        fake_spec_pack = self._create_fake_spec_pack()
        prompt_capture = self.app_root / "detail_pi_prompt.jsonl"
        fake_pi = self.app_root / "fake_pi_product_detail"
        fake_pi.write_text(
            """#!/usr/bin/env node
const fs = require('fs');
let body = '';
process.stdin.setEncoding('utf8');
process.stdin.once('data', chunk => {
  body += chunk;
  fs.writeFileSync(process.env.PI_PROMPT_CAPTURE, body);
  const advice = {
    schema_version: 'pi-data-mapping-advice-v1', node_id: 'collect_top_products',
    summary: { status: 'needs_review', text: '详情证据派生草稿' }, field_advice: [],
    derived_field_rows: [{ row_index: 0, fields: {
      功能: { draft_value: '防水防滑', confidence: 0.82, evidence_fields: ['selling_point_summary', 'core_material'] },
      风格: { draft_value: '简约实用', confidence: 0.68, evidence_fields: ['goods_name', 'usage_scene'] },
      主图元素: { draft_value: '商品主体、家居场景', confidence: 0.45, evidence_fields: ['goods_img'], risks: ['not_vision_verified'] }
    }}],
    requires_human_confirmation: true
  };
  console.log(JSON.stringify({ type: 'message_delta', text: JSON.stringify(advice) }));
  console.log(JSON.stringify({ type: 'agent_end', messages: [], willRetry: false }));
});
""",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)
        field_coverage_plan = [
            {
                "field_name": "排名",
                "field_path": "items.properties.rank",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "data_ads_ind_trade_category_goods_m",
                "source_api_name": "月-热销商品-按交易总量排序",
                "source_field_path": "data.result[].rank",
            },
            {
                "field_name": "材质",
                "field_path": "items.properties.material",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "data_goods_ads_ind_goods_detail_info_m",
                "source_api_name": "商品详情信息查询接口",
                "source_field_path": "data.result[].core_material",
            },
            {
                "field_name": "场景",
                "field_path": "items.properties.scene",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "data_goods_ads_ind_goods_detail_info_m",
                "source_api_name": "商品详情信息查询接口",
                "source_field_path": "data.result[].usage_scene",
            },
            {
                "field_name": "功能",
                "field_path": "items.properties.function",
                "required": True,
                "mapping_status": "derived_or_manual_required",
                "source_kind": "pi_derived",
                "evidence_field_paths": ["data.result[].selling_point_summary", "data.result[].core_material"],
            },
            {
                "field_name": "风格",
                "field_path": "items.properties.style",
                "required": True,
                "mapping_status": "derived_or_manual_required",
                "source_kind": "pi_derived",
                "evidence_field_paths": ["data.result[].goods_name", "data.result[].usage_scene"],
            },
            {
                "field_name": "主图元素",
                "field_path": "items.properties.main_image_elements",
                "required": True,
                "mapping_status": "derived_or_manual_required",
                "source_kind": "pi_derived",
                "evidence_field_paths": ["data.result[].goods_img", "data.result[].selling_point_summary"],
            },
        ]

        status, data = self._direct(
            "POST",
            "/api/nodes/collect_top_products/run",
            {
                "known_params": {"category": "桌垫", "cid": "121458013", "period": "近30天"},
                "field_coverage_plan": field_coverage_plan,
                "top_n": 3,
                "execution_date": "2026-07-15",
            },
            {
                "DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack),
                "DBA_LIVE_PROBE": "1",
                "TEST_DETAIL_PARTIAL": "1",
                "TEST_DETAIL_QBT_EMPTY": "1",
                "PI_BIN": str(fake_pi),
                "AICODEMIRROR_API_KEY": "sk-aicodemirror-secret",
                "PI_PROMPT_CAPTURE": str(prompt_capture),
                "PI_RPC_TIMEOUT_MS": "3000",
            },
        )

        self.assertEqual(200, status)
        result = data["result"]
        detail_plan = next(item for item in result["api_execution_plan"] if item["api_id"] == "data_goods_ads_ind_goods_detail_info_m")
        self.assertEqual("product_detail_enrichment", detail_plan["execution_role"])
        self.assertEqual("called", detail_plan["status"])
        self.assertEqual("sycm", detail_plan["selected_data_source"])
        self.assertEqual({"requested": 3, "success": 2, "empty": 1, "failed": 0, "identity_mismatch": 0}, detail_plan["batch_summary"])
        self.assertEqual("not_verifiable", detail_plan["temporal_alignment"]["status"])
        self.assertEqual("latest_available_snapshot", detail_plan["temporal_alignment"]["strategy"])
        table = json.loads((self.app_root / result["data_table_ref"]).read_text(encoding="utf-8"))
        self.assertEqual([1, 2, 3], [row["排名"] for row in table["rows"]])
        self.assertEqual("硅藻泥", table["rows"][0]["材质"])
        self.assertEqual("家用 玄关", table["rows"][0]["场景"])
        self.assertNotIn("材质", table["rows"][2])
        self.assertIn("data_goods_ads_ind_goods_detail_info_m", table["key_joined_api_ids"])
        self.assertEqual(detail_plan["batch_summary"], table["detail_enrichment"]["summary"])
        material_source = next(item for item in table["field_sources"] if item["field_name"] == "材质")
        self.assertEqual("partial", material_source["value_status"])
        self.assertEqual(2, material_source["rows_with_value"])
        self.assertNotIn("功能", table["rows"][0])
        self.assertNotIn("风格", table["rows"][0])
        self.assertNotIn("主图元素", table["rows"][0])
        function_source = next(item for item in table["field_sources"] if item["field_name"] == "功能")
        self.assertEqual("not_called", function_source["value_status"])
        self.assertFalse(prompt_capture.exists())
        evidence_row = table["derived_evidence_rows"][0]
        self.assertIn("selling_point_summary", evidence_row["fields"])
        self.assertEqual("防水防滑易清洁", evidence_row["fields"]["selling_point_summary"])
        self.assertEqual("https://fixture.test/desk/1.jpg", evidence_row["fields"]["goods_img"])
        self.assertIn("not_vision_verified", evidence_row["risks"])

    def test_data_analysis_node_product_detail_uses_most_recent_available_month(self):
        self._write_local_api_doc_index()
        self._append_product_detail_to_local_index()
        index_path = self.app_root / "data" / "api_doc_index.json"
        index_payload = json.loads(index_path.read_text(encoding="utf-8"))
        detail_entry = next(item for item in index_payload["apis"] if item["api_id"] == "data_goods_ads_ind_goods_detail_info_m")
        detail_entry["response_fields"].append(
            {"path": "data.result[].statist_date", "name": "statist_date", "type": "string", "description": "统计月份"}
        )
        index_path.write_text(json.dumps(index_payload, ensure_ascii=False), encoding="utf-8")
        fake_spec_pack = self._create_fake_spec_pack()
        field_coverage_plan = [
            {
                "field_name": "排名",
                "field_path": "items.properties.rank",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "data_ads_ind_trade_category_goods_m",
                "source_api_name": "月-热销商品-按交易总量排序",
                "source_field_path": "data.result[].rank",
            },
            {
                "field_name": "材质",
                "field_path": "items.properties.material",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "data_goods_ads_ind_goods_detail_info_m",
                "source_api_name": "商品详情信息查询接口",
                "source_field_path": "data.result[].core_material",
            },
        ]

        status, data = self._direct(
            "POST",
            "/api/nodes/collect_top_products/run",
            {
                "known_params": {"category": "桌垫", "cid": "121458013", "period": "近30天"},
                "field_coverage_plan": field_coverage_plan,
                "top_n": 1,
                "execution_date": "2026-07-15",
            },
            {
                "DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack),
                "DBA_LIVE_PROBE": "1",
                "TEST_DETAIL_DATED_ROWS": "1",
            },
        )

        self.assertEqual(200, status)
        result = data["result"]
        detail_plan = next(item for item in result["api_execution_plan"] if item["api_id"] == "data_goods_ads_ind_goods_detail_info_m")
        self.assertEqual("sycm", detail_plan["selected_data_source"])
        self.assertEqual("fallback_to_recent_available", detail_plan["temporal_alignment"]["status"])
        self.assertEqual("2026-05-01", detail_plan["temporal_alignment"]["selected_month"])
        table = json.loads((self.app_root / result["data_table_ref"]).read_text(encoding="utf-8"))
        self.assertEqual("PVC-May", table["rows"][0]["材质"])

    def test_data_analysis_node_product_detail_handles_top50_without_worker_buffer_failure(self):
        self._write_local_api_doc_index()
        self._append_product_detail_to_local_index()
        fake_spec_pack = self._create_fake_spec_pack()
        field_coverage_plan = [
            {
                "field_name": "排名",
                "field_path": "items.properties.rank",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "data_ads_ind_trade_category_goods_m",
                "source_api_name": "月-热销商品-按交易总量排序",
                "source_field_path": "data.result[].rank",
            },
            {
                "field_name": "材质",
                "field_path": "items.properties.material",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "data_goods_ads_ind_goods_detail_info_m",
                "source_api_name": "商品详情信息查询接口",
                "source_field_path": "data.result[].core_material",
            },
        ]

        status, data = self._direct(
            "POST",
            "/api/nodes/collect_top_products/run",
            {
                "known_params": {"category": "桌垫", "cid": "121458013", "period": "近30天"},
                "field_coverage_plan": field_coverage_plan,
                "top_n": 50,
                "execution_date": "2026-07-15",
            },
            {
                "DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack),
                "DBA_LIVE_PROBE": "1",
                "TEST_DETAIL_LARGE_PAYLOAD": "1",
            },
        )

        self.assertEqual(200, status)
        result = data["result"]
        detail_plan = next(item for item in result["api_execution_plan"] if item["api_id"] == "data_goods_ads_ind_goods_detail_info_m")
        self.assertEqual("called", detail_plan["status"])
        self.assertEqual(50, detail_plan["batch_summary"]["success"])
        self.assertEqual(1, detail_plan["request_debug"]["top_per_item"])
        material = next(item for item in result["field_sources"] if item["field_name"] == "材质")
        self.assertEqual("present", material["value_status"])
        self.assertEqual(50, material["rows_with_value"])

    def test_data_analysis_node_monthly_api_retries_previous_month_when_latest_is_empty(self):
        self._write_local_api_doc_index()
        fake_spec_pack = self._create_fake_spec_pack()
        field_coverage_plan = [
            {
                "field_name": "排名",
                "field_path": "items.properties.rank",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "data_ads_ind_trade_category_goods_m",
                "source_api_name": "月-热销商品-按交易总量排序",
                "source_field_path": "data.result[].rank",
            }
        ]

        status, data = self._direct(
            "POST",
            "/api/nodes/collect_top_products/run",
            {
                "known_params": {"category": "桌垫", "period": "近30天"},
                "field_coverage_plan": field_coverage_plan,
                "execution_date": "2026-07-15",
            },
            {
                "DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack),
                "DBA_LIVE_PROBE": "1",
                "TEST_MONTHLY_LATEST_EMPTY": "1",
            },
        )

        self.assertEqual(200, status)
        result = data["result"]
        plan = next(item for item in result["api_execution_plan"] if item["api_id"] == "data_ads_ind_trade_category_goods_m")
        self.assertEqual("2026-05-01", plan["selected_data_month"])
        self.assertEqual(2, len(plan["date_attempts"]))
        self.assertEqual(0, plan["date_attempts"][0]["rows_returned"])
        self.assertGreater(plan["date_attempts"][1]["rows_returned"], 0)
        self.assertEqual("2026-05-01", plan["params"]["start_date"])
        self.assertGreater(result["data_table_rows_count"], 0)
        context = json.loads((self.app_root / "artifacts" / "business_category_context.json").read_text(encoding="utf-8"))
        self.assertEqual("business-category-context-v1", context["schema_version"])
        self.assertEqual("桌垫", context["requested_name"])
        self.assertEqual("桌布", context["canonical_name"])
        self.assertEqual("121458013", context["category_id"])
        self.assertEqual("collect_top_products", context["source_node_id"])

    def test_data_analysis_node_blocks_when_discovered_category_resolver_cannot_match_name(self):
        self._write_local_api_doc_index()
        fake_spec_pack = self._create_fake_spec_pack()
        field_coverage_plan = [
            {
                "field_name": "商品链接",
                "field_path": "items.properties.product_url",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "data_ads_ind_sycm_speed_category_goods_m",
                "source_api_name": "月-热销商品-按交易增速排序",
                "source_field_path": "data.result[].goods_url",
            }
        ]

        status, data = self._direct(
            "POST",
            "/api/nodes/collect_top_products/run",
            {
                "known_params": {"category": "不存在类目", "period": "近30天"},
                "field_coverage_plan": field_coverage_plan,
            },
            {"DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack), "DBA_LIVE_PROBE": "1"},
        )

        self.assertEqual(status, 200)
        result = data["result"]
        plan = next(item for item in result["api_execution_plan"] if item["api_id"] == "data_ads_ind_sycm_speed_category_goods_m")
        self.assertEqual(plan["status"], "blocked")
        self.assertEqual(plan["category_resolution"]["status"], "blocked")
        self.assertEqual(plan["category_resolution"]["blocked_reason"], "category_not_found")
        self.assertNotEqual(plan["params"].get("cid"), "不存在类目")
        self.assertIn("category_not_found", result["blocked_reasons"])

    def test_category_resolver_ignores_rows_with_empty_category_names(self):
        self._write_local_api_doc_index()
        fake_spec_pack = self._create_fake_spec_pack()
        field_coverage_plan = [
            {
                "field_name": "商品链接",
                "field_path": "items.properties.product_url",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "data_ads_ind_sycm_speed_category_goods_m",
                "source_api_name": "月-热销商品-按交易增速排序",
                "source_field_path": "data.result[].goods_url",
            }
        ]

        status, data = self._direct(
            "POST",
            "/api/nodes/collect_top_products/run",
            {
                "known_params": {"category": "空名称边界类目扩展", "period": "近30天"},
                "field_coverage_plan": field_coverage_plan,
            },
            {
                "DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack),
                "DBA_LIVE_PROBE": "1",
                "TEST_RESOLVER_BLANK_NAME": "1",
            },
        )

        self.assertEqual(status, 200)
        plan = next(item for item in data["result"]["api_execution_plan"] if item["api_id"] == "data_ads_ind_sycm_speed_category_goods_m")
        self.assertEqual(plan["category_resolution"]["category_id"], "correct-category-id")
        self.assertEqual(plan["params"]["cid"], "correct-category-id")

    def test_category_resolver_probe_failure_is_traced_and_not_reported_as_category_not_found(self):
        self._write_local_api_doc_index()
        fake_spec_pack = self._create_fake_spec_pack()
        field_coverage_plan = [
            {
                "field_name": "商品链接",
                "field_path": "items.properties.product_url",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "data_ads_ind_sycm_speed_category_goods_m",
                "source_api_name": "月-热销商品-按交易增速排序",
                "source_field_path": "data.result[].goods_url",
            }
        ]

        status, data = self._direct(
            "POST",
            "/api/nodes/collect_top_products/run",
            {
                "known_params": {"category": "未索引桌垫", "period": "近30天"},
                "field_coverage_plan": field_coverage_plan,
            },
            {
                "DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack),
                "DBA_LIVE_PROBE": "1",
                "TEST_RESOLVER_FAIL": "1",
            },
        )

        self.assertEqual(status, 200)
        result = data["result"]
        plan = next(item for item in result["api_execution_plan"] if item["api_id"] == "data_ads_ind_sycm_speed_category_goods_m")
        self.assertEqual(plan["category_resolution"]["blocked_reason"], "resolver_probe_failed")
        self.assertIn("resolver_probe_failed", result["blocked_reasons"])
        trace = json.loads((self.app_root / result["execution_trace_ref"]).read_text(encoding="utf-8"))
        resolver_calls = [item for item in trace["api_calls"] if item.get("purpose") == "category_resolution"]
        self.assertTrue(resolver_calls)
        self.assertEqual(resolver_calls[0]["status"], "blocked")
        self.assertEqual(resolver_calls[0]["blocked_reason"], "resolver_probe_failed")

    def test_data_analysis_node_run_defaults_to_top_20_and_keeps_per_api_probe_evidence(self):
        fake_spec_pack = self._create_fake_spec_pack()
        field_coverage_plan = [
            {
                "field_name": "排名",
                "field_path": "items.properties.rank",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "/api/category/top-products",
                "source_api_name": "类目商品排行",
                "source_field_path": "data.rows.rank",
            },
            {
                "field_name": "客单价",
                "field_path": "items.properties.price",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "/api/category/top-products-secondary",
                "source_api_name": "类目商品价格",
                "source_field_path": "data.rows.price",
            },
        ]
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        node = next(item for item in config["nodes"] if item["id"] == "collect_top_products")
        node["output_field_requirements"] = field_coverage_plan
        self.config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

        status, data = self._direct(
            "POST",
            "/api/nodes/collect_top_products/run",
            {
                "known_params": {
                    "category": "沙发垫",
                    "start_date": "2026-06-01",
                    "end_date": "2026-06-30",
                },
                "field_coverage_plan": field_coverage_plan,
            },
            {"DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack), "DBA_LIVE_PROBE": "1"},
        )

        self.assertEqual(status, 200)
        result = data["result"]
        self.assertEqual(result["top_n"], 20)
        self.assertEqual(result["data_table_rows_count"], 20)
        self.assertEqual(result["data_table_preview"]["pagination"]["page_size"], 10)
        self.assertEqual(result["data_table_preview"]["pagination"]["total_rows"], 20)
        table = json.loads((self.app_root / result["data_table_ref"]).read_text(encoding="utf-8"))
        self.assertEqual(table["top_n"], 20)
        self.assertEqual(len(table["rows"]), 20)
        self.assertEqual(table["rows"][0]["排名"], 1)
        self.assertEqual(table["rows"][0]["客单价"], 99)
        self.assertEqual(table["rows"][19]["排名"], 20)
        self.assertEqual(table["rows"][19]["客单价"], 80)
        self.assertEqual(table["merge_strategy"], "key_join")
        self.assertEqual(result["status"], "data_table_ready")
        refs = [item["evidence_ref"] for item in result["api_execution_plan"]]
        self.assertEqual(len(set(refs)), 2)
        for ref in refs:
            evidence = json.loads((self.app_root / ref).read_text(encoding="utf-8"))
            self.assertEqual(evidence["response"]["payload"]["response"]["top"][0]["requested_top"], 20)
            self.assertIn("https://fixture.test", evidence["response"]["payload"]["request"]["url"])
        self.assertTrue(all(plan["request_debug"]["url"].startswith("https://fixture.test") for plan in result["api_execution_plan"]))

    def test_data_analysis_evidence_redacts_live_request_secrets(self):
        fake_spec_pack = self._create_fake_spec_pack()
        field_coverage_plan = [
            {
                "field_name": "排名",
                "field_path": "items.properties.rank",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "/api/category/top-products",
                "source_api_name": "类目商品排行",
                "source_field_path": "data.rows.rank",
            }
        ]

        status, data = self._direct(
            "POST",
            "/api/nodes/collect_top_products/run",
            {
                "known_params": {"category": "沙发垫", "start_date": "2026-06-01", "end_date": "2026-06-30"},
                "field_coverage_plan": field_coverage_plan,
            },
            {
                "DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack),
                "DBA_LIVE_PROBE": "1",
                "ZICHEN_APP_CODE_KEY": "live-app-code-secret",
            },
        )

        self.assertEqual(status, 200)
        evidence_ref = data["result"]["api_execution_plan"][0]["evidence_ref"]
        evidence_text = (self.app_root / evidence_ref).read_text(encoding="utf-8")
        self.assertNotIn("live-app-code-secret", evidence_text)
        self.assertIn("[REDACTED]", evidence_text)

    def test_required_empty_api_field_keeps_data_table_partial(self):
        fake_spec_pack = self._create_fake_spec_pack()
        field_coverage_plan = [
            {
                "field_name": "店铺名",
                "field_path": "items.properties.shop_name",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "/api/category/top-products",
                "source_api_name": "类目商品排行",
                "source_field_path": "data.rows.empty_required",
            }
        ]

        status, data = self._direct(
            "POST",
            "/api/nodes/collect_top_products/run",
            {
                "known_params": {"category": "沙发垫", "start_date": "2026-06-01", "end_date": "2026-06-30"},
                "field_coverage_plan": field_coverage_plan,
            },
            {"DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack), "DBA_LIVE_PROBE": "1"},
        )

        self.assertEqual(status, 200)
        result = data["result"]
        self.assertEqual(result["status"], "partial_data_table_ready")
        source = next(item for item in result["field_sources"] if item["field_name"] == "店铺名")
        self.assertEqual(source["value_status"], "empty")
        self.assertIn("店铺名:empty", result["risks"])

    def _keyword_field_coverage_plan(self):
        return [
            {
                "field_name": "keyword",
                "field_path": "items.properties.keyword",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "agent_xiaowan_keywords",
                "source_api_name": "直通车-小万关键词",
                "source_field_path": "data.result[].keyword",
            },
            {
                "field_name": "search_popularity",
                "field_path": "items.properties.search_popularity",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "agent_sycm_keyword",
                "source_api_name": "生意参谋关键词",
                "source_field_path": "data.result[].search_popularity",
            },
            {
                "field_name": "growth_rate",
                "field_path": "items.properties.growth_rate",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "agent_sycm_keyword",
                "source_api_name": "生意参谋关键词",
                "source_field_path": "data.result[].search_growth_rate",
            },
            {
                "field_name": "competition_index",
                "field_path": "items.properties.competition_index",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "agent_xiaowan_keywords",
                "source_api_name": "直通车-小万关键词",
                "source_field_path": "data.result[].competition_index",
            },
            {
                "field_name": "click_rate",
                "field_path": "items.properties.click_rate",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "agent_xiaowan_keywords",
                "source_api_name": "直通车-小万关键词",
                "source_field_path": "data.result[].click_rate",
            },
            {
                "field_name": "conversion_rate",
                "field_path": "items.properties.conversion_rate",
                "required": True,
                "mapping_status": "mapped",
                "source_api_id": "agent_sycm_keyword",
                "source_api_name": "生意参谋关键词",
                "source_field_path": "data.result[].pay_rate",
            },
            {
                "field_name": "root_terms",
                "field_path": "items.properties.root_terms",
                "required": True,
                "mapping_status": "derived_or_manual_required",
                "source_kind": "pi_derived",
                "source_api_id": "",
                "source_field_path": "",
                "evidence_field_paths": ["data.result[].keyword", "data.result[].keywords"],
            },
            {
                "field_name": "demand_type",
                "field_path": "items.properties.demand_type",
                "required": True,
                "mapping_status": "derived_or_manual_required",
                "source_kind": "pi_derived",
                "source_api_id": "",
                "source_field_path": "",
                "evidence_field_paths": ["items.properties.keyword", "items.properties.root_terms"],
            },
        ]

    def _write_resolved_category_context(self):
        artifacts = self.app_root / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / "business_category_context.json").write_text(
            json.dumps(
                {
                    "schema_version": "business-category-context-v1",
                    "requested_name": "桌垫",
                    "canonical_name": "桌布",
                    "category_id": "121458013",
                    "aliases": ["桌垫", "桌布"],
                    "status": "resolved",
                    "source_node_id": "collect_top_products",
                    "source_revision": 2,
                    "evidence_ref": "evidence/collect_top_products.category_resolution.json",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def test_keyword_analysis_uses_canonical_category_and_keyword_key_join(self):
        self._write_local_api_doc_index()
        self._append_keyword_apis_to_local_index()
        self._write_resolved_category_context()
        fake_spec_pack = self._create_fake_spec_pack()

        status, data = self._direct(
            "POST",
            "/api/nodes/collect_keywords/run",
            {
                "known_params": {"category": "桌垫"},
                "field_coverage_plan": self._keyword_field_coverage_plan(),
            },
            {"DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack), "DBA_LIVE_PROBE": "1"},
        )

        self.assertEqual(200, status)
        result = data["result"]
        self.assertEqual("agent_enrichment_pending", result["status"])
        self.assertEqual("桌布", result["selected_category_name"])
        self.assertEqual("桌布", result["category_context"]["canonical_name"])
        self.assertEqual("121458013", result["known_params"]["cid"])
        self.assertEqual("key_join", result["merge_strategy"])
        self.assertEqual(["keyword"], result["join_keys"])
        self.assertTrue(result["category_attempts"])
        self.assertTrue(all(item["category_name"] == "桌布" for item in result["category_attempts"]))
        table = json.loads((self.app_root / result["data_table_ref"]).read_text(encoding="utf-8"))
        self.assertEqual(1, len(table["rows"]))
        self.assertEqual("防水桌布", table["rows"][0]["keyword"].strip())
        self.assertEqual("1200", table["rows"][0]["search_popularity"])
        self.assertEqual("0.06", table["rows"][0]["conversion_rate"])
        by_field = {item["field_name"]: item for item in table["field_sources"]}
        self.assertEqual("pi_derived", by_field["root_terms"]["source_kind"])
        self.assertEqual("pi_derived", by_field["demand_type"]["source_kind"])
        self.assertEqual("", by_field["root_terms"]["source_field_path"])
        self.assertEqual("", by_field["demand_type"]["source_field_path"])
        root_artifact = json.loads((self.app_root / result["keyword_root_top20_ref"]).read_text(encoding="utf-8"))
        self.assertEqual("keyword-root-top20-v1", root_artifact["schema_version"])
        self.assertEqual("agent_enrichment_pending", root_artifact["status"])

    def test_keyword_analysis_resolves_category_when_shared_context_is_not_available(self):
        self._write_local_api_doc_index()
        self._append_keyword_apis_to_local_index()
        fake_spec_pack = self._create_fake_spec_pack()

        status, data = self._direct(
            "POST",
            "/api/nodes/collect_keywords/run",
            {
                "known_params": {"category": "桌垫"},
                "field_coverage_plan": self._keyword_field_coverage_plan(),
            },
            {"DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack), "DBA_LIVE_PROBE": "1"},
        )

        self.assertEqual(200, status)
        result = data["result"]
        self.assertEqual("agent_enrichment_pending", result["status"])
        self.assertEqual("桌布", result["selected_category_name"])
        self.assertEqual("桌布", result["category_context"]["canonical_name"])
        self.assertEqual("121458013", result["category_context"]["category_id"])
        self.assertEqual("collect_keywords", result["category_context"]["source_node_id"])

    def test_keyword_analysis_does_not_reuse_category_context_for_another_category(self):
        self._write_local_api_doc_index()
        self._append_keyword_apis_to_local_index()
        self._write_resolved_category_context()
        context_path = self.app_root / "artifacts" / "business_category_context.json"
        stale_context = json.loads(context_path.read_text(encoding="utf-8"))
        stale_context.update({
            "requested_name": "沙发垫",
            "canonical_name": "沙发垫",
            "category_id": "50020776",
            "aliases": ["沙发垫"],
        })
        context_path.write_text(json.dumps(stale_context, ensure_ascii=False), encoding="utf-8")
        fake_spec_pack = self._create_fake_spec_pack()

        status, data = self._direct(
            "POST",
            "/api/nodes/collect_keywords/run",
            {
                "known_params": {"category": "桌垫"},
                "field_coverage_plan": self._keyword_field_coverage_plan(),
            },
            {"DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack), "DBA_LIVE_PROBE": "1"},
        )

        self.assertEqual(200, status)
        result = data["result"]
        self.assertEqual("桌布", result["selected_category_name"])
        self.assertEqual("121458013", result["category_context"]["category_id"])

    def test_keyword_analysis_returns_empty_data_when_all_verified_candidates_are_empty(self):
        self._write_local_api_doc_index()
        self._append_keyword_apis_to_local_index()
        self._write_resolved_category_context()
        fake_spec_pack = self._create_fake_spec_pack()

        status, data = self._direct(
            "POST",
            "/api/nodes/collect_keywords/run",
            {
                "known_params": {"category": "桌垫"},
                "field_coverage_plan": self._keyword_field_coverage_plan(),
            },
            {
                "DB_ARCHAEOLOGIST_SPEC_PACK": str(fake_spec_pack),
                "DBA_LIVE_PROBE": "1",
                "TEST_KEYWORD_ALL_EMPTY": "1",
            },
        )

        self.assertEqual(200, status)
        result = data["result"]
        self.assertEqual("empty_data", result["status"])
        self.assertEqual([], result["blocked_reasons"])
        self.assertEqual("", result["selected_category_name"])
        attempted_names = {item["category_name"] for item in result["category_attempts"]}
        self.assertEqual({"桌垫", "桌布"}, attempted_names)
        self.assertTrue(all(item["status"] == "empty" for item in result["category_attempts"]))

    def test_pi_agent_status_degrades_when_runtime_is_missing(self):
        status, data = self._direct(
            "GET",
            "/api/pi-agent/status",
            env_extra={"PI_BIN": str(self.app_root / "missing-pi")},
        )

        self.assertEqual(status, 200)
        self.assertEqual(data["provider"], "pi_agent")
        self.assertEqual(data["status"], "not_configured")
        self.assertIn("data_mapping_advice", data["capabilities"])

    def test_pi_agent_status_degrades_when_model_key_is_missing(self):
        fake_pi = self.app_root / "fake_pi_without_key"
        fake_pi.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_pi.chmod(0o755)

        status, data = self._direct(
            "GET",
            "/api/pi-agent/status",
            env_extra={
                "PI_BIN": str(fake_pi),
                "AICODEMIRROR_API_KEY": "",
                "AICODEMIRROR_KEY": "",
                "DEEPSEEK_API_KEY": "",
                "PI_MODEL": "",
                "PI_DEFAULT_MODEL": "",
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "degraded")
        self.assertEqual(data["reason"], "model_key_not_configured")
        self.assertEqual(data["selected_model"], "aicodemirror/gpt-5.6-sol")
        self.assertFalse(data["model_key_configured"])

    def test_pi_agent_status_prefers_aicodemirror_then_deepseek(self):
        fake_pi = self.app_root / "fake_pi_status"
        fake_pi.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_pi.chmod(0o755)

        status, data = self._direct(
            "GET",
            "/api/pi-agent/status",
            env_extra={
                "PI_BIN": str(fake_pi),
                "AICODEMIRROR_API_KEY": "sk-aicodemirror-secret",
                "DEEPSEEK_API_KEY": "sk-deepseek-secret",
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["selected_model"], "aicodemirror/gpt-5.6-sol")
        self.assertEqual(data["model_provider"], "aicodemirror")
        self.assertTrue(data["model_key_configured"])
        self.assertEqual(data["model_options"][0]["model"], "aicodemirror/gpt-5.6-sol")
        self.assertTrue(data["model_options"][0]["configured"])
        self.assertEqual(data["model_options"][1]["model"], "deepseek/deepseek-v4-pro")
        self.assertTrue(data["model_options"][1]["configured"])
        self.assertNotIn("sk-aicodemirror-secret", json.dumps(data))

        status, data = self._direct(
            "GET",
            "/api/pi-agent/status",
            env_extra={
                "PI_BIN": str(fake_pi),
                "DEEPSEEK_API_KEY": "sk-deepseek-secret",
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(data["selected_model"], "deepseek/deepseek-v4-pro")
        self.assertEqual(data["model_provider"], "deepseek")
        self.assertTrue(data["model_key_configured"])

    def test_pi_agent_query_passes_selected_model_and_normalizes_aicodemirror_key(self):
        args_capture = self.app_root / "pi_args.txt"
        env_capture = self.app_root / "pi_env.txt"
        fake_pi = self.app_root / "fake_pi_model"
        fake_pi.write_text(
            f"""#!/bin/sh
printf '%s\n' "$@" > {args_capture}
printf '%s\n' "$AICODEMIRROR_API_KEY" > {env_capture}
IFS= read -r _request
printf '%s\n' '{{"type":"message_update","assistantMessageEvent":{{"type":"text_delta","delta":"{{\\"schema_version\\":\\"pi-data-mapping-advice-v1\\",\\"node_id\\":\\"collect_top_products\\",\\"summary\\":{{\\"status\\":\\"ok\\",\\"text\\":\\"model ok\\"}},\\"field_advice\\":[],\\"requires_human_confirmation\\":true}}"}}}}'
printf '%s\n' '{{"type":"agent_end","messages":[],"willRetry":false}}'
""",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)

        status, data = self._direct(
            "POST",
            "/api/pi-agent/query",
            {
                "node_id": "collect_top_products",
                "intent": "mapping_correction",
                "message": "用 DeepSeek 检查这个字段",
                "model": "deepseek/deepseek-v4-pro",
                "field_coverage_plan": [],
            },
            env_extra={
                "PI_BIN": str(fake_pi),
                "AICODEMIRROR_KEY": "sk-legacy-aicodemirror",
                "DEEPSEEK_API_KEY": "sk-deepseek-secret",
                "PI_RPC_TIMEOUT_MS": "3000",
            },
        )

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        args = args_capture.read_text(encoding="utf-8")
        self.assertIn("--model", args)
        self.assertIn("deepseek/deepseek-v4-pro", args)
        self.assertIn("--no-tools", args)
        self.assertIn("--no-context-files", args)
        self.assertEqual(env_capture.read_text(encoding="utf-8").strip(), "sk-legacy-aicodemirror")

    def test_pi_agent_query_keeps_rpc_stdin_open_until_agent_end(self):
        fake_pi = self.app_root / "fake_pi_requires_open_stdin"
        advice = {
            "schema_version": "pi-data-mapping-advice-v1",
            "node_id": "collect_top_products",
            "summary": {"status": "ok", "text": "stream completed"},
            "field_advice": [],
            "requires_human_confirmation": True,
        }
        event = {
            "type": "message_update",
            "assistantMessageEvent": {"type": "text_delta", "delta": json.dumps(advice, ensure_ascii=False)},
        }
        fake_pi.write_text(
            "#!/usr/bin/env node\n"
            "let stdinEnded = false;\n"
            "process.stdin.on('end', () => { stdinEnded = true; });\n"
            "process.stdin.once('data', () => {\n"
            "  setTimeout(() => {\n"
            "    if (stdinEnded) process.exit(0);\n"
            f"    console.log({json.dumps(json.dumps(event, ensure_ascii=False))});\n"
            "    console.log(JSON.stringify({ type: 'agent_end', messages: [], willRetry: false }));\n"
            "  }, 75);\n"
            "});\n",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)

        status, data = self._direct(
            "POST",
            "/api/pi-agent/query",
            {
                "node_id": "collect_top_products",
                "intent": "free_chat",
                "message": "保持流直到回答完成",
            },
            env_extra={"PI_BIN": str(fake_pi), "AICODEMIRROR_API_KEY": "sk-test", "PI_RPC_TIMEOUT_MS": "3000"},
        )

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["reason"], "ready")
        self.assertEqual(data["advice"]["summary"]["text"], "stream completed")

    def test_pi_agent_query_marks_empty_successful_exit_as_degraded(self):
        fake_pi = self.app_root / "fake_pi_empty_response"
        fake_pi.write_text(
            "#!/usr/bin/env node\n"
            "process.stdin.once('data', () => {\n"
            "  console.log(JSON.stringify({ type: 'response', command: 'prompt', success: true, id: 'empty' }));\n"
            "  process.exit(0);\n"
            "});\n",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)

        status, data = self._direct(
            "POST",
            "/api/pi-agent/query",
            {
                "node_id": "collect_top_products",
                "intent": "free_chat",
                "message": "不要把空响应标成成功",
            },
            env_extra={"PI_BIN": str(fake_pi), "AICODEMIRROR_API_KEY": "sk-test", "PI_RPC_TIMEOUT_MS": "3000"},
        )

        self.assertEqual(status, 200)
        self.assertFalse(data["ok"])
        self.assertEqual(data["status"], "degraded")
        self.assertEqual(data["reason"], "pi_empty_response")

    def test_pi_agent_prompt_includes_analysis_node_view_context(self):
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        node = next(item for item in config["nodes"] if item["id"] == "collect_top_products")
        node["analysis_node_view"] = {
            "schema_version": "analysis-node-view-v1",
            "node_id": "collect_top_products",
            "node_kind": "data_analysis",
            "purpose_model": {"title": "行业大盘与热销商品分析", "purpose": "判断热销商品机会"},
            "input_model": {"data_sources": [{"name": "生意参谋商品排行"}], "data_requirement_ids": ["category_top_products_300"]},
            "execution_plan": {"steps": [{"title": "匹配字段", "instruction": "匹配 API 字段"}]},
            "data_output_model": {"fields": []},
            "insight_output_model": {"requirements": [{"question": "哪些商品具备爆款机会？"}]},
            "verification_model": {"checks": []},
            "source_trace": {"business_doc_refs": ["source_doc#流程2"]},
        }
        self.config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

        prompt_capture = self.app_root / "pi_prompt.txt"
        fake_pi = self.app_root / "fake_pi_prompt"
        fake_pi.write_text(
            f"""#!/bin/sh
IFS= read -r _request
printf '%s\n' "$_request" > {prompt_capture}
printf '%s\n' '{{"type":"message_update","assistantMessageEvent":{{"type":"text_delta","delta":"{{\\"schema_version\\":\\"pi-data-mapping-advice-v1\\",\\"node_id\\":\\"collect_top_products\\",\\"summary\\":{{\\"status\\":\\"needs_review\\",\\"text\\":\\"context ok\\"}},\\"field_advice\\":[],\\"requires_human_confirmation\\":true}}"}}}}'
printf '%s\n' '{{"type":"agent_end","messages":[],"willRetry":false}}'
""",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)

        status, data = self._direct(
            "POST",
            "/api/pi-agent/query",
            {
                "node_id": "collect_top_products",
                "intent": "mapping_correction",
                "message": "检查字段",
                "field_coverage_plan": [],
            },
            env_extra={
                "PI_BIN": str(fake_pi),
                "AICODEMIRROR_API_KEY": "sk-aicodemirror-secret",
                "PI_RPC_TIMEOUT_MS": "3000",
            },
        )

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        prompt = prompt_capture.read_text(encoding="utf-8")
        self.assertIn("## 数据分析节点语义视图 analysis_node_view", prompt)
        self.assertIn("判断热销商品机会", prompt)
        self.assertIn("哪些商品具备爆款机会", prompt)

    def test_pi_agent_prompt_includes_table_selection_and_insight_evidence_context(self):
        prompt_capture = self.app_root / "pi_collaboration_prompt.txt"
        fake_pi = self.app_root / "fake_pi_collaboration_prompt"
        fake_pi.write_text(
            f"""#!/bin/sh
IFS= read -r _request
printf '%s\n' "$_request" > {prompt_capture}
printf '%s\n' '{{"type":"message_update","assistantMessageEvent":{{"type":"text_delta","delta":"{{\\"schema_version\\":\\"pi-data-mapping-advice-v1\\",\\"node_id\\":\\"collect_top_products\\",\\"summary\\":{{\\"status\\":\\"needs_review\\",\\"text\\":\\"ok\\"}},\\"field_advice\\":[]}}"}}}}'
printf '%s\n' '{{"type":"agent_end","messages":[],"willRetry":false}}'
""",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)
        status, data = self._direct(
            "POST",
            "/api/pi-agent/query",
            {
                "node_id": "collect_top_products",
                "intent": "insight_collaboration",
                "message": "分析产品类型占比",
                "table_workspace": {"revision": 2, "fields": [{"field_path": "产品类型"}], "row_meta": [{"row_id": "goods:desk-1"}]},
                "table_selection": {"scope_mode": "cells", "cells": [{"row_id": "goods:desk-1", "field_path": "产品类型", "effective_value": "桌垫"}]},
                "selected_requirement": {"requirement_id": "insight_1", "question": "当前行业热卖产品分为哪几类？"},
                "evidence_summary": {"insight_1": [{"field_path": "产品类型", "rows_with_value": 50}]},
            },
            env_extra={"PI_BIN": str(fake_pi), "AICODEMIRROR_API_KEY": "sk-test", "PI_RPC_TIMEOUT_MS": "3000"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        prompt = prompt_capture.read_text(encoding="utf-8")
        for expected in ["当前表格协作工作区", "当前表格选区", "当前分析结论要求", "确定性证据摘要", "insight_collaboration_proposal", "data-table-edit-proposal-v1"]:
            self.assertIn(expected, prompt)

    def test_insight_agent_proposal_application_keeps_proposed_evidence(self):
        self._write_collaboration_fixture()
        _, initial = self._direct("GET", "/api/nodes/collect_top_products/insight-workspace")
        requirement_id = initial["workspace"]["blocks"][0]["requirement_id"]
        status, proposed = self._direct(
            "POST",
            "/api/nodes/collect_top_products/insight-workspace/patch",
            {
                "base_revision": initial["workspace"]["revision"],
                "requirement_id": requirement_id,
                "agent_proposal": {
                    "schema_version": "insight-edit-proposal-v1",
                    "proposal_id": "proposal-1",
                    "requirement_id": requirement_id,
                    "proposed_text": "桌垫为主要产品类型。",
                    "evidence_bindings": [{"kind": "field", "field_path": "产品类型"}],
                },
            },
        )
        self.assertEqual(status, 200)
        status, applied = self._direct(
            "POST",
            "/api/nodes/collect_top_products/insight-workspace/patch",
            {
                "base_revision": proposed["workspace"]["revision"],
                "requirement_id": requirement_id,
                "proposal_id": "proposal-1",
                "proposal_action": "apply",
            },
        )
        self.assertEqual(status, 200)
        block = applied["workspace"]["blocks"][0]
        self.assertEqual(block["draft_text"], "桌垫为主要产品类型。")
        self.assertEqual(block["evidence_bindings"], [{"kind": "field", "field_path": "产品类型"}])

    def test_pi_agent_query_without_runtime_returns_structured_fallback_advice(self):
        status, data = self._direct(
            "POST",
            "/api/pi-agent/query",
            {
                "node_id": "collect_top_products",
                "message": "帮我检查字段映射",
                "selected_api_asset_cards": [],
                "field_coverage_plan": [],
                "join_plan": {},
            },
            env_extra={"PI_BIN": str(self.app_root / "missing-pi")},
        )

        self.assertEqual(status, 200)
        self.assertFalse(data["ok"])
        self.assertEqual(data["provider"], "pi_agent")
        self.assertEqual(data["advice"]["schema_version"], "pi-data-mapping-advice-v1")
        self.assertEqual(data["advice"]["summary"]["status"], "unavailable")
        self.assertTrue(data["advice"]["requires_human_confirmation"])
        self.assertIn("pi_mapping_advice.json", data["evidence_ref"])
        self.assertTrue((self.app_root / data["evidence_ref"]).exists())

    def test_pi_agent_derived_field_analysis_returns_structured_fallback(self):
        self._write_local_api_doc_index()

        status, data = self._direct(
            "POST",
            "/api/pi-agent/query",
            {
                "node_id": "collect_top_products",
                "intent": "derived_field_analysis",
                "message": "分析派生字段如何填充",
                "field_coverage_plan": [
                    {
                        "field_path": "items.properties.style",
                        "field_name": "风格",
                        "mapping_status": "derived_or_manual_required",
                        "source_kind": "pi_derived",
                    }
                ],
                "selected_api_asset_cards": [],
                "join_plan": {},
            },
            env_extra={"PI_BIN": str(self.app_root / "missing-pi")},
        )

        self.assertEqual(status, 200)
        self.assertFalse(data["ok"])
        self.assertEqual(data["advice"]["schema_version"], "pi-data-mapping-advice-v1")
        self.assertIn("derived_field_advice", data["advice"])
        self.assertEqual(data["advice"]["derived_field_advice"][0]["field_name"], "风格")
        self.assertTrue(data["advice"]["requires_human_confirmation"])

    def test_pi_agent_derived_field_fill_and_insight_draft_intents_return_structured_fallbacks(self):
        self._write_local_api_doc_index()

        status, derived = self._direct(
            "POST",
            "/api/pi-agent/query",
            {
                "node_id": "collect_top_products",
                "intent": "derived_field_fill",
                "message": "填充派生字段草稿",
                "field_coverage_plan": [
                    {
                        "field_path": "items.properties.hot_sale_reason",
                        "field_name": "爆款原因",
                        "mapping_status": "derived_or_manual_required",
                        "source_kind": "pi_derived",
                    }
                ],
                "data_table_draft": {"rows": [{"排名": 1, "主卖点": "防滑"}]},
            },
            env_extra={"PI_BIN": str(self.app_root / "missing-pi")},
        )

        self.assertEqual(status, 200)
        self.assertFalse(derived["ok"])
        self.assertEqual(derived["advice"]["schema_version"], "pi-data-mapping-advice-v1")
        self.assertEqual(derived["advice"]["derived_field_advice"][0]["field_name"], "爆款原因")
        self.assertIn("draft_value", derived["advice"]["derived_field_advice"][0])

        status, insight = self._direct(
            "POST",
            "/api/pi-agent/query",
            {
                "node_id": "collect_top_products",
                "intent": "insight_draft",
                "message": "生成分析结论草稿",
                "analysis_node_view": {
                    "insight_output_model": {
                        "requirements": [
                            {"question": "哪些商品具备爆款机会？", "required_evidence_fields": ["排名", "客单价"]}
                        ]
                    }
                },
                "data_table_draft": {"rows": [{"排名": 1, "客单价": 99}]},
            },
            env_extra={"PI_BIN": str(self.app_root / "missing-pi")},
        )

        self.assertEqual(status, 200)
        self.assertFalse(insight["ok"])
        self.assertEqual(insight["advice"]["schema_version"], "pi-data-mapping-advice-v1")
        self.assertIn("insight_draft_advice", insight["advice"])
        self.assertEqual(insight["advice"]["insight_draft_advice"]["status"], "needs_runtime_or_human_review")
        self.assertTrue(insight["advice"]["requires_human_confirmation"])

    def test_pi_agent_query_uses_runtime_for_mapping_advice(self):
        fake_pi = self.app_root / "fake_pi"
        fake_pi.write_text(
            """#!/bin/sh
IFS= read -r _request
printf '%s\n' '{"type":"response","command":"prompt","success":true,"id":"pi-test"}'
printf '%s\n' '{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"建议选择商品排行 API，并把 rank 映射到 data.rows.rank。"}}'
printf '%s\n' '{"type":"agent_end","messages":[],"willRetry":false}'
""",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)

        status, data = self._direct(
            "POST",
            "/api/pi-agent/query",
            {
                "node_id": "collect_top_products",
                "message": "帮我检查字段映射",
                "data_mapping_contract": {
                    "candidate_apis": [{"api_id": "/api/category/top-products"}],
                    "response_field_mapping": [],
                },
            },
            env_extra={"PI_BIN": str(fake_pi), "AICODEMIRROR_API_KEY": "sk-aicodemirror-secret", "PI_RPC_TIMEOUT_MS": "3000"},
        )

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["provider"], "pi_agent")
        self.assertIn("rank", data["response_text"])
        self.assertTrue(data["advice"]["requires_human_confirmation"])

    def test_pi_agent_mapping_correction_prompt_includes_target_field_and_history(self):
        prompt_capture = self.app_root / "pi_prompt.jsonl"
        fake_pi = self.app_root / "fake_pi_correction"
        fake_pi.write_text(
            f"""#!/bin/sh
IFS= read -r _request
printf '%s\n' "$_request" > {prompt_capture}
printf '%s\n' '{{"type":"message_update","assistantMessageEvent":{{"type":"text_delta","delta":"{{\\"schema_version\\":\\"pi-data-mapping-advice-v1\\",\\"node_id\\":\\"collect_top_products\\",\\"summary\\":{{\\"status\\":\\"needs_review\\",\\"text\\":\\"建议改用图片字段\\"}},\\"field_advice\\":[{{\\"field_path\\":\\"items.properties.product_image\\",\\"field_name\\":\\"商品主图\\",\\"judgement\\":\\"better_alternative\\",\\"confidence\\":0.86,\\"suggested_action\\":\\"change_source\\",\\"reason\\":\\"用户指出原映射不对\\",\\"suggested_source_api_id\\":\\"api_goods_rank\\",\\"suggested_source_field_path\\":\\"data.result[].pictures_linking\\"}}],\\"requires_human_confirmation\\":true}}"}}}}'
printf '%s\n' '{{"type":"agent_end","messages":[],"willRetry":false}}'
""",
            encoding="utf-8",
        )
        fake_pi.chmod(0o755)

        status, data = self._direct(
            "POST",
            "/api/pi-agent/query",
            {
                "node_id": "collect_top_products",
                "intent": "mapping_correction",
                "message": "这个字段匹配错了，应该是主图链接",
                "target_field": {
                    "field_path": "items.properties.product_image",
                    "field_name": "商品主图",
                    "source_field_path": "data.result[].commodity",
                },
                "conversation_history": [
                    {"role": "user", "content": "上一轮建议不对"},
                    {"role": "assistant", "content": "请指出目标字段"},
                ],
                "api_response_field_catalog": [
                    {
                        "source_api_id": "api_goods_rank",
                        "source_api_name": "商品排行",
                        "source_field_path": "data.result[].pictures_linking",
                        "api_field_name": "pictures_linking",
                        "api_field_type": "string",
                        "description": "商品图片链接",
                    }
                ],
            },
            env_extra={"PI_BIN": str(fake_pi), "AICODEMIRROR_API_KEY": "sk-aicodemirror-secret", "PI_RPC_TIMEOUT_MS": "3000"},
        )

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["advice"]["field_advice"][0]["judgement"], "better_alternative")
        captured = prompt_capture.read_text(encoding="utf-8")
        self.assertIn("mapping_correction", captured)
        self.assertIn("商品主图", captured)
        self.assertIn("这个字段匹配错了", captured)
        self.assertIn("上一轮建议不对", captured)
        self.assertIn("data.result[].pictures_linking", captured)


if __name__ == "__main__":
    unittest.main()
