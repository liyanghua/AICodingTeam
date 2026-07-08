"""Tests for report_generator shell server API endpoints."""
import json
import os
import shutil
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
export async function probeApiSampleTool(args) {
  return {
    api_id: args.api_id,
    mode: 'fake_probe',
    response: {
      top: [
        { rank: 1, title: '沙发垫 A', price: 99 },
        { rank: 2, title: '沙发垫 B', price: 89 }
      ]
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

    def _write_local_api_doc_index(self) -> Path:
        data_dir = self.app_root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        index_path = data_dir / "api_doc_index.json"
        index_path.write_text(
            json.dumps(
                {
                    "schema_version": "api-doc-index-v1",
                    "summary": {"api_count": 2, "field_count": 17},
                    "apis": [
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
                            "api_id": "data_ads_ind_sycm_speed_category_goods_m",
                            "source_seq": 2,
                            "name": "月-热销商品-按交易增速排序",
                            "module": "fixture",
                            "business_module": "热销商品",
                            "analysis_domain": "商品域",
                            "method": "POST",
                            "path": "/data/ads_ind_sycm_speed_category_goods_m",
                            "verified_status": "success",
                            "request_params": [
                                {"name": "cid", "type": "string", "required": True, "description": "类目ID"},
                                {"name": "start_date", "type": "string", "required": True, "description": "开始日期"},
                            ],
                            "request_headers": [],
                            "response_fields": [
                                {"path": "data.result[].last_month_rank", "name": "last_month_rank", "type": "number", "description": "上月排名"},
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

        selected_api = tool_plan["payload"]["strategy_results"]["field_coverage_rerank"]["selected_api_ids"][0]
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
        self.assertIn("derived_field_plan", mapping_contract)
        derived_names = {item["field_name"] for item in mapping_contract["derived_field_plan"]}
        self.assertEqual(derived_names, {"功能", "风格", "主图元素", "爆款原因"})

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
        self.assertEqual(coverage_by_field["排名"]["source_api_id"], "top300_product_analysis")
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

    def test_pi_agent_query_uses_runtime_for_mapping_advice(self):
        fake_pi = self.app_root / "fake_pi"
        fake_pi.write_text(
            """#!/bin/sh
cat >/dev/null
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
            env_extra={"PI_BIN": str(fake_pi), "PI_RPC_TIMEOUT_MS": "3000"},
        )

        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["provider"], "pi_agent")
        self.assertIn("rank", data["response_text"])
        self.assertTrue(data["advice"]["requires_human_confirmation"])


if __name__ == "__main__":
    unittest.main()
