const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');
const { spawn, spawnSync } = require('child_process');
const { CollaborationError, compareAgentModels, createCollaborationStore } = require('./collaboration_store');
const { GeneAnalysisError, createHotProductGeneAnalysisStore } = require('./gene_analysis_store');

const HOST = '127.0.0.1';
const PORT = parseInt(process.env.PREVIEW_PORT || process.env.PORT || '8788', 10);

// Resolve paths for two layouts:
// - dev layout: server.js in shells/report_generator/server/, web/ + version.txt in shells/report_generator/
// - generated layout: server.js in generated_apps/<slug>/, public/ + shell_version.txt alongside
const SHELL_ROOT = path.resolve(__dirname, '..');
const APP_ROOT = process.env.APP_ROOT || process.cwd();
const CONFIG_PATH = process.argv[2] || path.join(APP_ROOT, 'app.config.json');

function firstExisting(candidates, fallback) {
  for (const candidate of candidates) {
    if (candidate && fs.existsSync(candidate)) return candidate;
  }
  return fallback;
}

const PUBLIC_DIR = firstExisting(
  [path.join(__dirname, 'public'), path.join(SHELL_ROOT, 'web')],
  path.join(SHELL_ROOT, 'web'),
);
const VERSION_PATH = firstExisting(
  [path.join(__dirname, 'shell_version.txt'), path.join(SHELL_ROOT, 'version.txt')],
  path.join(SHELL_ROOT, 'version.txt'),
);
const UPLOADS_DIR = path.join(APP_ROOT, 'uploads');
const EVIDENCE_DIR = path.join(APP_ROOT, 'evidence');
const ARTIFACTS_DIR = path.join(APP_ROOT, 'artifacts');
const collaborationStore = createCollaborationStore({
  appRoot: APP_ROOT,
  artifactsDir: ARTIFACTS_DIR,
  evidenceDir: EVIDENCE_DIR,
  defaultAgentModel: String(process.env.PI_MODEL || process.env.PI_DEFAULT_MODEL || 'aicodemirror/gpt-5.6-sol'),
  onAgentCallEvent: (eventType, data) => broadcastEvent(eventType || AGENT_CALL_EVENT, data),
  onDataTableConfirmed: persistConfirmedDataTableDerivatives,
});
const geneAnalysisStore = createHotProductGeneAnalysisStore({
  appRoot: APP_ROOT,
  artifactsDir: ARTIFACTS_DIR,
  evidenceDir: EVIDENCE_DIR,
  defaultAgentModel: String(process.env.PI_MODEL || process.env.PI_DEFAULT_MODEL || 'aicodemirror/gpt-5.6-sol'),
  evaluateRule: (ruleId, inputs) => evalRule(ruleId, inputs),
  onEvent: event => broadcastEvent('gene_analysis_update', event),
});
const API_NODE_RUN_PREFIX = '/api/nodes/';
const SSE_NODE_PREFIX = '/sse/nodes/';
const SSE_AGENT_PREFIX = '/sse/agent/';
const AGENT_CALL_EVENT = 'agent_call_update';
const DB_AGENT_WORKER = firstExisting(
  [path.join(__dirname, 'server', 'db_archaeologist_worker.mjs'), path.join(__dirname, 'db_archaeologist_worker.mjs'), path.join(SHELL_ROOT, 'server', 'db_archaeologist_worker.mjs')],
  path.join(SHELL_ROOT, 'server', 'db_archaeologist_worker.mjs'),
);
const API_DOC_INDEX_PATH = firstExisting(
  [path.join(APP_ROOT, 'data', 'api_doc_index.json'), path.join(APP_ROOT, 'data_capability', 'api_doc_index.json')],
  path.join(APP_ROOT, 'data', 'api_doc_index.json'),
);
const DB_AGENT_ALLOWED_ACTIONS = new Set(['understand_input', 'catalog', 'tool_plan', 'domain_apis', 'asset_card', 'field_map', 'suggest_multi_api_mapping', 'probe_sample', 'save_field_mapping', 'confirm_mapping']);
const DB_AGENT_MATCHER_ACTIONS = new Set(['understand_input', 'catalog', 'tool_plan', 'domain_apis', 'field_map', 'suggest_multi_api_mapping']);
const DEFAULT_DATA_ANALYSIS_TOP_N = 20;
const DATA_TABLE_PAGE_SIZE = 10;

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8',
};

let cachedConfig = null;
let cachedVersionError = null;

// SSE client management
const sseClients = new Set();

function broadcastEvent(eventType, data) {
  const message = `event: ${eventType}\ndata: ${JSON.stringify(data)}\n\n`;
  for (const client of sseClients) {
    if (client.filter && client.filter.node_id && client.filter.node_id !== data.node_id) continue;
    if (client.filter && client.filter.call_id && client.filter.call_id !== data.call?.call_id) continue;
    if (client.filter && client.filter.batch_id && client.filter.batch_id !== data.batch?.batch_id) continue;
    if (client.filter && client.filter.execution_id && client.filter.execution_id !== data.execution_id) continue;
    try {
      client.res.write(message);
    } catch (error) {
      sseClients.delete(client);
    }
  }
}

function readConfig() {
  if (cachedConfig) return cachedConfig;
  if (!fs.existsSync(CONFIG_PATH)) {
    throw new Error(`app.config.json not found at ${CONFIG_PATH}`);
  }
  const raw = fs.readFileSync(CONFIG_PATH, 'utf8');
  cachedConfig = JSON.parse(raw);
  
  // Validate schema version
  if (cachedConfig.schema_version !== 'app-config-v1') {
    throw new Error(`Unsupported schema_version: ${cachedConfig.schema_version}`);
  }
  
  // Validate shell compatibility
  const expected = fs.existsSync(VERSION_PATH) ? fs.readFileSync(VERSION_PATH, 'utf8').trim() : '';
  const actual = String(cachedConfig.shell_version || expected || '').trim();
  if (expected && actual && expected !== actual) {
    cachedVersionError = { error: 'shell_version_mismatch', expected, actual };
  }
  
  // Ensure required directories
  ensureDir(UPLOADS_DIR);
  ensureDir(EVIDENCE_DIR);
  ensureDir(ARTIFACTS_DIR);
  
  return cachedConfig;
}

function sendJson(res, status, payload) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.end(JSON.stringify(payload));
}

function sendText(res, status, text, contentType = 'text/plain; charset=utf-8') {
  res.statusCode = status;
  res.setHeader('Content-Type', contentType);
  res.setHeader('Cache-Control', 'no-store, max-age=0');
  res.end(text);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', chunk => {
      body += chunk.toString();
      if (body.length > 10 * 1024 * 1024) reject(new Error('request_body_too_large'));
    });
    req.on('end', () => resolve(body));
    req.on('error', reject);
  });
}

function parseJsonBody(req) {
  return readBody(req).then(body => {
    if (!body) return {};
    return JSON.parse(body);
  });
}

function dbAgentSpecPackRoot() {
  return String(process.env.DB_ARCHAEOLOGIST_SPEC_PACK || '').trim();
}

function hasLocalApiDocIndex() {
  return fs.existsSync(API_DOC_INDEX_PATH);
}

function loadLocalApiDocIndex() {
  if (!hasLocalApiDocIndex()) return { apis: [] };
  try {
    const payload = JSON.parse(fs.readFileSync(API_DOC_INDEX_PATH, 'utf8'));
    return payload && typeof payload === 'object' ? payload : { apis: [] };
  } catch (error) {
    return { apis: [], error: error.message };
  }
}

function localApiEntries() {
  const payload = loadLocalApiDocIndex();
  return Array.isArray(payload.apis) ? payload.apis.filter(item => item && typeof item === 'object') : [];
}

function localApiEntryForId(apiId) {
  return localApiEntries().find(item => String(item.api_id || '') === String(apiId || '')) || null;
}

function localApiIndexStats() {
  const entries = localApiEntries();
  const fieldCount = entries.reduce((total, entry) => total + (Array.isArray(entry.response_fields) ? entry.response_fields.length : 0), 0);
  return { api_count: entries.length, field_count: fieldCount };
}

// matcher 服务桥：把 API 召回和字段匹配委托给仓库内的 api_doc_matcher（唯一事实源）。
// node 侧只做传输与形状适配；调用失败时返回 degraded，不再用 JS 评分兜底。
function matcherRepoRoot() {
  const override = String(process.env.API_DOC_MATCHER_ROOT || '').trim();
  if (override && fs.existsSync(path.join(override, 'api_doc_matcher', '__init__.py'))) return override;
  const cwd = process.cwd();
  if (fs.existsSync(path.join(cwd, 'api_doc_matcher', '__init__.py'))) return cwd;
  let dir = APP_ROOT;
  for (let depth = 0; depth < 8; depth += 1) {
    if (fs.existsSync(path.join(dir, 'api_doc_matcher', '__init__.py'))) return dir;
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return '';
}

function matcherService(request) {
  const root = matcherRepoRoot();
  if (!root) return { degraded: true, reason: 'matcher_root_not_found' };
  const result = spawnSync('python3', ['-m', 'api_doc_matcher.service'], {
    input: JSON.stringify(request),
    cwd: root,
    encoding: 'utf-8',
    timeout: Number(process.env.MATCHER_TIMEOUT_MS || 20000),
    env: { ...process.env, PYTHONPATH: root },
  });
  if (result.error) return { degraded: true, reason: 'spawn_failed', error: result.error.message };
  if (result.status !== 0) return { degraded: true, reason: 'matcher_failed', stderr: result.stderr || '' };
  try {
    return JSON.parse(result.stdout);
  } catch (error) {
    return { degraded: true, reason: 'bad_matcher_json', error: error.message };
  }
}

function listFromMaybe(value) {
  if (Array.isArray(value)) return value.map(item => String(item || '').trim()).filter(Boolean);
  const text = String(value || '').trim();
  return text ? [text] : [];
}

function matcherBusinessContextForNode(node) {
  const view = node && node.node_execution_view ? node.node_execution_view : {};
  const context = node && node.data_mapping_context ? node.data_mapping_context : {};
  const businessContext = node && node.business_context ? node.business_context : {};
  const requiredData = Array.isArray(node && node.input_model && node.input_model.required_data)
    ? node.input_model.required_data
    : [];
  const dataSources = [
    ...listFromMaybe(context.data_sources),
    ...listFromMaybe(businessContext.data_sources),
    ...requiredData.map(item => String(item && (item.description || item.title || item.id) || '')).filter(Boolean),
  ];
  const actions = [
    ...listFromMaybe(context.actions),
    ...listFromMaybe(view.action && (view.action.markdown || view.action.summary)),
    ...listFromMaybe(view.artifact && (view.artifact.markdown || view.artifact.title)),
    ...listFromMaybe(context.business_query),
    ...listFromMaybe(businessContext.query),
  ];
  return {
    node_id: String(node && node.id || ''),
    title: String(context.section_title || context.title || node && (node.name || node.id) || ''),
    purpose: String(
      context.purpose
      || businessContext.purpose
      || view.goal && (view.goal.markdown || view.goal.summary)
      || businessRequirementForNode(node).description
      || ''
    ),
    data_sources: [...new Set(dataSources)],
    actions: [...new Set(actions)],
    source_path: String(context.source_path || businessContext.source_path || ''),
  };
}

function callBusinessContextMatcher(node, knownParams, payload = {}) {
  if (!hasLocalApiDocIndex()) {
    return { degraded: true, reason: 'api_doc_index_not_configured' };
  }
  const request = {
    op: 'match_business_context',
    index_path: API_DOC_INDEX_PATH,
    business_context: matcherBusinessContextForNode(node),
    output_fields: nodeOutputFieldRequirements(node),
    known_params: knownParams || {},
    strategy: String(payload.strategy || node && node.data_mapping_context && node.data_mapping_context.default_strategy || 'field_coverage_rerank'),
    top_k: Number(payload.top_k || 8) || 8,
  };
  const response = matcherService(request);
  if (!response || response.degraded || response.schema_version !== 'business-context-field-mapping-v1') {
    return {
      degraded: true,
      reason: 'matcher_service_unavailable',
      matcher_reason: response && response.reason || 'invalid_matcher_response',
      matcher_error: response && (response.error || response.stderr) || '',
    };
  }
  return response;
}

function todayInTimezone(timezone = 'Asia/Shanghai') {
  try {
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: timezone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).formatToParts(new Date());
    const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
    if (values.year && values.month && values.day) return `${values.year}-${values.month}-${values.day}`;
  } catch (error) {
    // Fall through to UTC ISO date when the requested timezone is not available.
  }
  return new Date().toISOString().slice(0, 10);
}

function callRequestParamBinder(apiId, knownParams, payload = {}) {
  if (!hasLocalApiDocIndex()) {
    return { degraded: true, reason: 'api_doc_index_not_configured' };
  }
  if (!localApiEntryForId(apiId)) {
    return { degraded: true, reason: 'api_id_not_in_api_doc_index' };
  }
  const timezone = String(payload.timezone || payload.execution_timezone || 'Asia/Shanghai');
  const request = {
    op: 'bind_request_params',
    index_path: API_DOC_INDEX_PATH,
    api_id: String(apiId || ''),
    known_params: knownParams || {},
    execution_date: String(payload.execution_date || payload.run_date || todayInTimezone(timezone)),
    timezone,
  };
  const response = matcherService(request);
  if (!response || response.degraded || response.schema_version !== 'request-param-binding-v1') {
    return {
      degraded: true,
      reason: 'matcher_service_unavailable',
      matcher_reason: response && response.reason || 'invalid_param_binding_response',
      matcher_error: response && (response.error || response.stderr) || '',
    };
  }
  return response;
}

function callCategoryResolverDiscovery(knownParams, payload = {}) {
  if (!hasLocalApiDocIndex()) {
    return { degraded: true, reason: 'api_doc_index_not_configured' };
  }
  const timezone = String(payload.timezone || payload.execution_timezone || 'Asia/Shanghai');
  const request = {
    op: 'discover_category_resolver',
    index_path: API_DOC_INDEX_PATH,
    known_params: knownParams || {},
    category_name: String(payload.category_name || knownParams && (knownParams.category || knownParams.category_name || knownParams['分析类目']) || ''),
    category_id: String(payload.category_id || knownParams && (knownParams.cid || knownParams.category_id || knownParams.cate_id || knownParams.cat_id) || ''),
    direction: String(payload.direction || 'name_to_id'),
    execution_date: String(payload.execution_date || payload.run_date || todayInTimezone(timezone)),
    timezone,
    top_k: Number(payload.top_k || 8) || 8,
  };
  const response = matcherService(request);
  if (!response || response.degraded || response.schema_version !== 'category-resolver-discovery-v1') {
    return {
      degraded: true,
      reason: 'matcher_service_unavailable',
      matcher_reason: response && response.reason || 'invalid_category_resolver_response',
      matcher_error: response && (response.error || response.stderr) || '',
      candidates: [],
    };
  }
  return response;
}

function callCategoryCandidateResolver(knownParams, payload = {}) {
  if (!hasLocalApiDocIndex()) {
    return { degraded: true, reason: 'api_doc_index_not_configured' };
  }
  const request = {
    op: 'resolve_category_candidates',
    index_path: API_DOC_INDEX_PATH,
    known_params: knownParams || {},
    category_name: String(payload.category_name || knownParams && (knownParams.category || knownParams.category_name || knownParams['分析类目']) || ''),
    category_id: String(payload.category_id || knownParams && (knownParams.cid || knownParams.category_id || knownParams.cate_id || knownParams.cat_id) || ''),
  };
  const response = matcherService(request);
  if (!response || response.degraded || response.schema_version !== 'business-category-resolution-v2') {
    return {
      degraded: true,
      reason: 'matcher_service_unavailable',
      matcher_reason: response && response.reason || 'invalid_category_resolution_response',
      matcher_error: response && (response.error || response.stderr) || '',
    };
  }
  return response;
}

function dbAgentStatus() {
  const specPackRoot = dbAgentSpecPackRoot();
  const liveEnabled = process.env.DBA_LIVE_PROBE === '1';
  const status = {
    status: 'degraded',
    reason: '',
    provider: '',
    spec_pack_configured: Boolean(specPackRoot),
    spec_pack_root: specPackRoot,
    api_doc_index_configured: hasLocalApiDocIndex(),
    api_doc_index_path: API_DOC_INDEX_PATH,
    api_doc_index_stats: hasLocalApiDocIndex() ? localApiIndexStats() : {},
    worker_path: DB_AGENT_WORKER,
    worker_available: fs.existsSync(DB_AGENT_WORKER),
    loader_available: false,
    live_probe_enabled: liveEnabled,
    allowed_tools: ['ask_api_catalog', 'select_tools_for_task', 'list_domain_apis', 'get_api_asset_card', 'probe_api_sample', 'probe_api_batch'],
  };
  if (!specPackRoot) {
    if (hasLocalApiDocIndex()) {
      status.status = 'ok';
      status.reason = 'api_doc_index_ready';
      status.provider = 'api_doc_index';
      return status;
    }
    status.reason = 'spec_pack_not_configured';
    return status;
  }
  if (!fs.existsSync(specPackRoot)) {
    status.reason = 'spec_pack_not_found';
    return status;
  }
  const loaderPath = path.join(specPackRoot, 'scripts', 'ts_loader.mjs');
  status.loader_available = fs.existsSync(loaderPath);
  if (!status.worker_available) {
    status.reason = 'worker_not_found';
    return status;
  }
  if (!status.loader_available) {
    status.reason = 'ts_loader_not_found';
    return status;
  }
  status.status = 'ok';
  status.reason = 'ready';
  status.provider = 'db_agent_worker';
  return status;
}

function piAgentBin() {
  return String(process.env.PI_BIN || 'pi').trim() || 'pi';
}

const PI_MODEL_OPTIONS = [
  {
    provider: 'aicodemirror',
    label: 'AICodeMirror GPT-5.6 Sol',
    model: 'aicodemirror/gpt-5.6-sol',
    env_keys: ['AICODEMIRROR_API_KEY', 'AICODEMIRROR_KEY'],
    primary_env_key: 'AICODEMIRROR_API_KEY',
  },
  {
    provider: 'deepseek',
    label: 'DeepSeek V4 Pro',
    model: 'deepseek/deepseek-v4-pro',
    env_keys: ['DEEPSEEK_API_KEY'],
    primary_env_key: 'DEEPSEEK_API_KEY',
  },
];

function envFirst(env, keys) {
  for (const key of keys) {
    const value = String(env[key] || '').trim();
    if (value) return value;
  }
  return '';
}

function piProcessEnv() {
  const env = { ...process.env };
  if (!String(env.AICODEMIRROR_API_KEY || '').trim() && String(env.AICODEMIRROR_KEY || '').trim()) {
    env.AICODEMIRROR_API_KEY = String(env.AICODEMIRROR_KEY).trim();
  }
  return env;
}

function piModelOptions(env = process.env) {
  return PI_MODEL_OPTIONS.map(option => ({
    provider: option.provider,
    label: option.label,
    model: option.model,
    configured: Boolean(envFirst(env, option.env_keys)),
    env_key: option.primary_env_key,
  }));
}

function resolvePiModel(payload = {}, env = process.env) {
  const requested = String(
    payload.model
    || payload.pi_model
    || env.PI_MODEL
    || env.PI_DEFAULT_MODEL
    || ''
  ).trim();
  const options = piModelOptions(env);
  const knownRequested = requested ? options.find(option => option.model === requested) : null;
  const selected = knownRequested
    || options.find(option => option.configured)
    || options[0];
  const provider = selected.provider || String((requested || selected.model).split('/')[0] || 'unknown');
  return {
    model: requested && !knownRequested ? requested : selected.model,
    provider,
    label: selected.label || requested,
    key_configured: knownRequested ? knownRequested.configured : Boolean(selected.configured),
    source: requested ? 'requested_or_env' : selected.configured ? 'first_configured' : 'default',
    options,
  };
}

function piAgentStatus() {
  const bin = piAgentBin();
  const env = piProcessEnv();
  const model = resolvePiModel({}, env);
  const probe = spawnSync(bin, ['--help'], {
    encoding: 'utf-8',
    timeout: 3000,
    env,
  });
  const available = !probe.error || probe.error.code !== 'ENOENT';
  const runtimeStatus = !available
    ? 'not_configured'
    : model.key_configured
      ? 'ready'
      : 'degraded';
  const reason = !available
    ? 'pi_binary_not_found'
    : model.key_configured
      ? 'ready'
      : 'model_key_not_configured';
  return {
    provider: 'pi_agent',
    status: runtimeStatus,
    reason,
    pi_bin: bin,
    selected_model: model.model,
    model_provider: model.provider,
    model_label: model.label,
    model_key_configured: model.key_configured,
    model_selection_source: model.source,
    model_options: model.options,
    capabilities: ['chat', 'stream', 'data_mapping_advice'],
    scope: 'right_agent_only',
    writes_node_facts: false,
  };
}

// Few-shot 锚点：约束 PI 输出为 pi-data-mapping-advice-v1 结构，避免只回“请确认”这类空文本。
const PI_MAPPING_ADVICE_EXAMPLE = {
  schema_version: 'pi-data-mapping-advice-v1',
  node_id: 'collect_top_products',
  summary: {
    status: 'needs_review',
    text: '字段覆盖基本可用，但商品唯一键和时间窗口需要确认。',
  },
  api_review: [
    {
      api_id: '/api/category/top-products',
      api_name: '类目商品排行',
      judgement: 'useful',
      reason: '覆盖排名、商品基础信息、价格、交易指数等核心字段。',
    },
  ],
  field_advice: [
    {
      field_path: 'items.properties.rank',
      field_name: 'rank',
      current_source_api_id: '/api/category/top-products',
      current_source_field_path: 'data.rows.rank',
      judgement: 'ok',
      confidence: 0.95,
      suggested_action: 'keep',
      reason: '字段语义和粒度一致。',
      suggested_source_api_id: '/api/category/top-products',
      suggested_source_field_path: 'data.rows.rank',
    },
    {
      field_path: 'items.properties.product_id',
      field_name: 'product_id',
      current_source_api_id: '',
      current_source_field_path: '',
      judgement: 'missing',
      confidence: 0,
      suggested_action: 'ask_user',
      reason: '候选 API 未提供确定的商品唯一键，需人工确认。',
      suggested_source_api_id: '',
      suggested_source_field_path: '',
    },
  ],
  join_advice: {
    judgement: 'needs_input',
    recommended_primary_api_id: '/api/category/top-products',
    recommended_join_keys: ['product_id'],
    grain: 'product',
    time_window: '近30天',
    risks: ['多 API 行级合并前必须确认 product_id 口径一致。'],
  },
  questions_for_user: ['商品唯一键使用 product_id 还是 item_id？'],
  requires_human_confirmation: true,
};

// 将 asset card 压缩为 PI 可读的完整 request/response schema，这是 PI 做语义匹配而非空猜的前提。
function assetCardSchemaForPrompt(card) {
  const item = card && typeof card === 'object' ? card : {};
  return {
    api_id: String(item.api_id || item.id || ''),
    name: String(item.name || item.title || item.api_id || ''),
    method: String(item.method || ''),
    path: String(item.path || item.api_id || ''),
    capability: String(item.capability || ''),
    request_params: requestParamsFromAssetCard(item),
    response_fields: apiFieldsFromAssetCard(item),
  };
}

function selectedApiCardsFromPayload(payload) {
  if (Array.isArray(payload && payload.selected_api_asset_cards)) return payload.selected_api_asset_cards;
  if (payload && payload.selected_api_asset_card) return [payload.selected_api_asset_card];
  return [];
}

function apiResponseFieldCatalogFromPayload(payload) {
  const direct = Array.isArray(payload && payload.api_response_field_catalog) ? payload.api_response_field_catalog : [];
  if (direct.length > 0) return direct;
  const contract = payload && payload.data_mapping_contract && typeof payload.data_mapping_contract === 'object'
    ? payload.data_mapping_contract
    : {};
  return Array.isArray(contract.api_response_field_catalog) ? contract.api_response_field_catalog : [];
}

function targetFieldFromPayload(payload) {
  const target = payload && payload.target_field && typeof payload.target_field === 'object' ? payload.target_field : {};
  return {
    field_path: String(target.field_path || ''),
    field_name: String(target.field_name || target.title || ''),
    title: String(target.title || target.field_name || ''),
    description: String(target.description || ''),
    current_source_api_id: String(target.source_api_id || target.current_source_api_id || ''),
    current_source_field_path: String(target.source_field_path || target.api_field_path || target.current_source_field_path || ''),
    current_status: String(target.mapping_status || target.status || ''),
    human_note: String(target.human_note || ''),
  };
}

function conversationHistoryFromPayload(payload) {
  const history = Array.isArray(payload && payload.conversation_history) ? payload.conversation_history : [];
  return history
    .filter(item => item && typeof item === 'object')
    .slice(-12)
    .map(item => ({
      role: String(item.role || 'user'),
      content: String(item.content || item.message || ''),
      created_at: String(item.created_at || ''),
    }))
    .filter(item => item.content);
}

function piPromptForDataMapping(node, payload) {
  const contract = payload.data_mapping_contract && typeof payload.data_mapping_contract === 'object'
    ? payload.data_mapping_contract
    : {};
  const cards = selectedApiCardsFromPayload(payload).map(assetCardSchemaForPrompt);
  const fieldCatalog = apiResponseFieldCatalogFromPayload(payload);
  const targetField = targetFieldFromPayload(payload);
  const conversationHistory = conversationHistoryFromPayload(payload);
  const baseline = Array.isArray(payload.field_coverage_plan) ? payload.field_coverage_plan : [];
  const analysisNodeView = payload.analysis_node_view && typeof payload.analysis_node_view === 'object'
    ? payload.analysis_node_view
    : node && node.analysis_node_view && typeof node.analysis_node_view === 'object'
      ? node.analysis_node_view
      : {};
  const joinPlan = payload.join_plan && typeof payload.join_plan === 'object' ? payload.join_plan : {};
  const upstream = Array.isArray(payload.upstream_artifacts)
    ? extractKnownParamsFromArtifacts(payload.upstream_artifacts)
    : {};
  const intent = String(payload.intent || 'data_mapping_advice');
  const collaborationIntent = ['table_edit_advice', 'insight_collaboration', 'free_chat'].includes(intent);
  const keywordTableAdvice = intent === 'table_edit_advice' && (
    String(node && node.id || '') === 'collect_keywords'
    || String(payload.batch_item_context && payload.batch_item_context.subject_kind || '') === 'keyword'
  );
  if (payload.batch_item_context && typeof payload.batch_item_context === 'object') {
    const keywordBatch = String(payload.batch_item_context.subject_kind || '') === 'keyword';
    return [
      keywordBatch
        ? '你是关键词语义补齐 Agent。当前请求只处理一个关键词的 root_terms 和 demand_type。'
        : '你是商品数据补齐 Agent。当前请求只处理一个商品和它的空缺派生字段。',
      `节点：${node && (node.name || node.id) || 'unknown'} (${node && node.id || ''})`,
      `意图：${intent}`,
      keywordBatch ? '## 当前关键词证据' : '## 当前商品证据',
      JSON.stringify(payload.batch_item_context, null, 2),
      ...(keywordBatch ? [
        '## 八类需求标准',
        '品类需求、人群需求、属性需求、功能需求、场景需求、品牌需求、风格需求、定制需求',
      ] : []),
      '## 输出要求',
      '必须返回 JSON，schema_version 固定为 "pi-data-mapping-advice-v1"，node_id 等于当前节点。',
      '必须返回 table_edit_proposal，schema_version 固定为 "data-table-edit-proposal-v1"。',
      keywordBatch
        ? 'patches 只能包含当前 row_id 的 root_terms 和 demand_type；root_terms 必须为去重字符串数组，demand_type 必须是八类需求标准中的一个主类型。每个字段必须单独返回一个 patch，格式示例：{"row_id":"keyword:书桌垫","field_path":"root_terms","old_value":[],"new_value":["书桌","桌垫"],"reason":"关键词拆解","confidence":0.9,"evidence_refs":[]}。'
        : 'patches 只能包含当前 row_id 的 target_fields，old_value 必须为空，new_value 只能是有证据支持的简洁描述。',
      `证据不足的字段不要编造，保持为空；不得修改 API 事实字段、其它${keywordBatch ? '关键词' : '商品'}或输出隐藏思维过程。`,
    ].join('\n');
  }
  return [
    collaborationIntent ? '你是生成应用右侧 Agent 的数据分析协作层。' : '你是生成应用右侧 Agent 的数据映射协作层。',
    collaborationIntent
      ? '目标：围绕当前可编辑数据表、业务分析要求和证据摘要回答问题或提出可审计建议；只建议，不自动写入或确认事实。'
      : '目标：围绕当前节点的输出字段要求、候选 API 的完整 schema 和确定性匹配 baseline，逐字段给出可审计建议；只建议，不写入事实源。',
    `意图：${intent}`,
    `节点：${node && (node.name || node.id) || 'unknown'} (${node && node.id || ''})`,
    `用户问题：${String(payload.message || '请给出字段映射建议。')}`,
    '## 数据分析节点语义视图 analysis_node_view',
    JSON.stringify(analysisNodeView, null, 2),
    '## 输出字段要求',
    JSON.stringify(nodeOutputFieldRequirements(node), null, 2),
    '## 候选 API 完整 schema（request/response 字段名、路径、类型、描述）',
    JSON.stringify(cards, null, 2),
    '## 可人工筛选的 API 返回字段目录（用于纠错或未匹配字段人工选择）',
    JSON.stringify(fieldCatalog, null, 2),
    '## 当前纠错目标字段（intent=mapping_correction 时必须优先处理）',
    JSON.stringify(targetField, null, 2),
    '## 多轮对话历史（最近 12 条）',
    JSON.stringify(conversationHistory, null, 2),
    '## 确定性规则匹配 baseline（field_coverage_plan：请在此基础上纠错和增强，而不是从零开始）',
    JSON.stringify(baseline, null, 2),
    '## 派生字段逐商品证据（仅用于生成未确认草稿）',
    JSON.stringify(Array.isArray(payload.derived_evidence_rows) ? payload.derived_evidence_rows : [], null, 2),
    '## Join plan baseline',
    JSON.stringify(joinPlan, null, 2),
    '## 上游业务参数（用于补齐类目、周期、产品线等口径）',
    JSON.stringify(upstream, null, 2),
    '## 当前数据映射合同',
    JSON.stringify(contract, null, 2),
    '## 当前数据表协作工作区（当前表格协作工作区，只允许引用其中存在的字段和 row_id）',
    JSON.stringify(payload.table_workspace && typeof payload.table_workspace === 'object' ? payload.table_workspace : {}, null, 2),
    '## 当前数据表有效数据（最多 100 行，row_id 与字段值可用于单元格建议和证据引用）',
    JSON.stringify(payload.data_table_draft && typeof payload.data_table_draft === 'object' ? payload.data_table_draft : {}, null, 2),
    '## 当前表格选区（intent=table_edit_advice 时不得越界修改）',
    JSON.stringify(payload.table_selection && typeof payload.table_selection === 'object' ? payload.table_selection : {}, null, 2),
    '## 当前分析结论要求（intent=insight_collaboration 时只处理这一条）',
    JSON.stringify(payload.selected_requirement && typeof payload.selected_requirement === 'object' ? payload.selected_requirement : {}, null, 2),
    '## 确定性证据摘要（字段缺失率、频次和数值统计）',
    JSON.stringify(payload.evidence_summary && typeof payload.evidence_summary === 'object' ? payload.evidence_summary : {}, null, 2),
    '## 输出要求',
    '1. 必须返回 JSON，schema_version 固定为 "pi-data-mapping-advice-v1"，node_id 等于当前节点。',
    '2. 对每个输出字段给出 field_advice：judgement(ok/needs_review/missing/better_alternative)、confidence(0-1)、reason。',
    '3. 有更优字段时给出 suggested_source_api_id / suggested_source_field_path，且必须来自上面列出的真实 API 字段。',
    '4. 如果 intent=derived_field_analysis 或 derived_field_fill，必须额外输出 derived_field_advice[]，说明派生字段的分析逻辑、所需证据、草稿值条件、置信度和风险；如果已有样例行证据，可输出 derived_field_rows[]，格式为 {row_index, fields:{字段名:{draft_value, confidence, evidence_fields}}}；无证据时 draft_value 留空。',
    '5. 如果 intent=mapping_correction，必须围绕“当前纠错目标字段”给出 field_advice；可以建议 change_source/manual_fill/ask_user，但不能自动确认。',
    '6. 如果 intent=insight_draft，必须额外输出 insight_draft_advice，包含草稿文本、证据字段、风险和待确认问题；不能把草稿写成 confirmed 事实。',
    keywordTableAdvice
      ? '7. 如果 intent=table_edit_advice，必须输出 table_edit_proposal，schema_version="data-table-edit-proposal-v1"；关键词字段必须逐字段输出标准 patch，例如 {"row_id":"keyword:书桌垫","field_path":"root_terms","old_value":[],"new_value":["书桌","桌垫"],"reason":"关键词拆解","confidence":0.9,"evidence_refs":[]}。只允许当前选区中的 root_terms 和 demand_type。'
      : '7. 如果 intent=table_edit_advice，必须输出 table_edit_proposal，schema_version="data-table-edit-proposal-v1"，patches 只包含当前选区中的 row_id/field_path，并带 old_value/new_value/reason/confidence/evidence_refs。',
    '8. 如果 intent=insight_collaboration，必须输出 insight_collaboration_proposal，包含 requirement_id、proposed_text、evidence_bindings、risks、questions_for_user；证据只能引用当前表格工作区中的字段和 row_id。',
    '9. 如果 intent=free_chat，基于当前数据表和多轮历史直接回答；没有足够证据时明确说明缺口，不生成表格 patch 或已确认结论。',
    '10. 无法完整判断时，用 questions_for_user 列出待用户澄清的问题。',
    '## 禁止',
    '- 禁止只输出“请确认”“建议人工核对”之类无信息量文本。',
    '- 禁止编造不存在的 API 字段；禁止直接确认合同；禁止调用 live probe；禁止输出 secret/凭据/环境变量。',
    '## Few-shot 示例（只用于锚定结构，不要照抄内容）',
    JSON.stringify(PI_MAPPING_ADVICE_EXAMPLE, null, 2),
  ].join('\n');
}

function parsePiRpcText(stdout) {
  const parts = [];
  for (const line of String(stdout || '').split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let event = null;
    try {
      event = JSON.parse(trimmed);
    } catch {
      parts.push(trimmed);
      continue;
    }
    if (event.type === 'message_update') {
      const inner = event.assistantMessageEvent || {};
      if (inner.type === 'text_delta') parts.push(String(inner.delta || ''));
      if (inner.type === 'text_end' && parts.length === 0) parts.push(String(inner.content || ''));
    } else if (event.type === 'message_delta') {
      parts.push(String(event.text || event.delta || ''));
    }
  }
  return parts.join('').trim();
}

function actualModelFromPiEvent(event) {
  if (!event || typeof event !== 'object') return '';
  const direct = event.actual_model || event.model_id || event.model;
  if (typeof direct === 'string' && direct.trim()) return direct.trim();
  const nested = [event.agent, event.message, event.metadata, event.response]
    .find(item => item && typeof item === 'object' && !Array.isArray(item));
  if (!nested) return '';
  const model = nested.actual_model || nested.model_id || nested.model;
  if (typeof model === 'string' && model.trim()) return model.trim();
  if (model && typeof model === 'object') {
    const provider = String(model.provider || '').trim();
    const id = String(model.id || model.model || '').trim();
    if (provider && id) return `${provider}/${id}`;
    if (id) return id;
  }
  return '';
}

function publicPiStage(event, state) {
  const type = String(event && event.type || '');
  const innerType = String(event && event.assistantMessageEvent && event.assistantMessageEvent.type || '');
  if (type === 'agent_start') return 'agent_started';
  if (type === 'thinking_start' || type === 'thinking_delta' || type === 'thinking_end') return state.sawAnalyzing ? '' : 'analyzing';
  if (type === 'turn_start' || innerType === 'text_start') return state.sawGenerating ? '' : 'generating';
  if ((type === 'message_update' && innerType === 'text_delta') || type === 'message_delta') return state.sawFirstText ? '' : 'first_text';
  return '';
}

const activePiCalls = new Map();

function runPiRpcOnce(bin, args, options) {
  return new Promise(resolve => {
    const timeoutMs = Number(options.timeout_ms || 60000);
    const requestId = String(options.request_id || `pi-${Date.now()}`);
    let child;
    try {
      child = spawn(bin, args, {
        cwd: options.cwd,
        env: options.env,
        stdio: ['pipe', 'pipe', 'pipe'],
      });
    } catch (error) {
      resolve({ error, status: null, stdout: '', stderr: '', saw_agent_end: false });
      return;
    }

    let stdout = '';
    let stderr = '';
    let stdoutBuffer = '';
    let settled = false;
    let sawAgentEnd = false;
    let rpcRejected = false;
    let rpcError = '';
    let actualModel = '';
    let eventCount = 0;
    const startedAt = Date.now();
    const publicState = { sawAnalyzing: false, sawGenerating: false, sawFirstText: false };

    const emitPublicEvent = event => {
      if (typeof options.on_event !== 'function') return;
      try {
        options.on_event({ ...event, at: event.at || new Date().toISOString() });
      } catch {
        // UI observability must not interrupt the PI process.
      }
    };

    activePiCalls.set(String(options.call_id || requestId), { child, cancelled: false });
    emitPublicEvent({ stage: 'process_started' });

    const finish = result => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      resolve({
        status: result.status,
        signal: result.signal || null,
        error: result.error || null,
        timed_out: Boolean(result.timed_out),
        stdout,
        stderr,
        saw_agent_end: sawAgentEnd,
        rpc_rejected: rpcRejected,
        rpc_error: rpcError,
        actual_model: actualModel,
        event_count: eventCount,
        duration_ms: Math.max(0, Date.now() - startedAt),
        cancelled: Boolean(result.cancelled),
      });
      activePiCalls.delete(String(options.call_id || requestId));
    };

    const stopChild = () => {
      if (child.stdin && !child.stdin.destroyed) child.stdin.end();
      const killTimer = setTimeout(() => {
        if (!child.killed) child.kill('SIGTERM');
      }, 250);
      if (typeof killTimer.unref === 'function') killTimer.unref();
    };

    const handleLine = line => {
      let event;
      try {
        event = JSON.parse(line);
      } catch {
        return;
      }
      eventCount += 1;
      const reportedModel = actualModelFromPiEvent(event);
      if (reportedModel) actualModel = reportedModel;
      const stage = publicPiStage(event, publicState);
      if (stage) {
        if (stage === 'analyzing') publicState.sawAnalyzing = true;
        if (stage === 'generating') publicState.sawGenerating = true;
        if (stage === 'first_text') publicState.sawFirstText = true;
        emitPublicEvent({ stage, ...(actualModel ? { actual_model: actualModel } : {}) });
      } else if (reportedModel && event.type === 'agent_start') {
        emitPublicEvent({ stage: 'agent_started', actual_model: actualModel });
      }
      if (event && event.type === 'response' && event.id === requestId && event.success === false) {
        rpcRejected = true;
        rpcError = String(event.error || 'pi_rpc_rejected');
        stopChild();
        finish({ status: 1 });
        return;
      }
      if (event && event.type === 'agent_end' && event.willRetry !== true) {
        sawAgentEnd = true;
        stopChild();
        finish({ status: 0 });
      }
    };

    const timeout = setTimeout(() => {
      if (!child.killed) child.kill('SIGTERM');
      finish({ status: null, timed_out: true });
    }, Math.max(timeoutMs, 1));
    if (typeof timeout.unref === 'function') timeout.unref();

    child.stdout.setEncoding('utf8');
    child.stdout.on('data', chunk => {
      stdout += chunk;
      stdoutBuffer += chunk;
      let newline;
      while ((newline = stdoutBuffer.indexOf('\n')) >= 0) {
        const line = stdoutBuffer.slice(0, newline).trim();
        stdoutBuffer = stdoutBuffer.slice(newline + 1);
        if (line) handleLine(line);
      }
    });
    child.stderr.setEncoding('utf8');
    child.stderr.on('data', chunk => {
      stderr = `${stderr}${chunk}`.slice(-8192);
    });
    child.on('error', error => finish({ status: null, error }));
    child.on('exit', (status, signal) => {
      const trailing = stdoutBuffer.trim();
      if (trailing) handleLine(trailing);
      const active = activePiCalls.get(String(options.call_id || requestId));
      finish({ status, signal, cancelled: Boolean(active && active.cancelled) });
    });

    const command = JSON.stringify({ type: 'prompt', id: requestId, message: options.prompt }) + '\n';
    child.stdin.on('error', error => finish({ status: null, error }));
    child.stdin.write(command, error => {
      if (error) finish({ status: null, error });
    });
  });
}

function cancelPiCall(callId) {
  const active = activePiCalls.get(String(callId || ''));
  if (!active || !active.child) return false;
  active.cancelled = true;
  if (!active.child.killed) active.child.kill('SIGTERM');
  return true;
}

function coerceConfidence(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return 0;
  if (num < 0) return 0;
  if (num > 1) return 1;
  return num;
}

// 请求上下文摘要，用于 advice.input_refs 和 evidence.request_summary。
function piAdviceContext(node, payload) {
  const cards = selectedApiCardsFromPayload(payload);
  const baseline = Array.isArray(payload.field_coverage_plan) ? payload.field_coverage_plan : [];
  const analysisNodeView = payload.analysis_node_view && typeof payload.analysis_node_view === 'object'
    ? payload.analysis_node_view
    : node && node.analysis_node_view && typeof node.analysis_node_view === 'object'
      ? node.analysis_node_view
      : {};
  const confirmed = baseline.filter(item => item && (item.human_confirmed || String(item.mapping_status || '') === 'confirmed')).length;
  return {
    node_id: node && node.id ? String(node.id) : '',
    intent: String(payload.intent || 'data_mapping_advice'),
    selected_api_count: cards.length,
    field_coverage_plan: baseline,
    field_coverage_count: baseline.length,
    confirmed_field_count: confirmed,
    target_field: targetFieldFromPayload(payload),
    conversation_history: conversationHistoryFromPayload(payload),
    api_response_field_catalog_count: apiResponseFieldCatalogFromPayload(payload).length,
    join_plan: payload.join_plan && typeof payload.join_plan === 'object' ? payload.join_plan : {},
    output_field_requirements: nodeOutputFieldRequirements(node),
    analysis_node_view: analysisNodeView,
    insight_requirements: Array.isArray(analysisNodeView.insight_output_model && analysisNodeView.insight_output_model.requirements)
      ? analysisNodeView.insight_output_model.requirements
      : [],
    data_table_rows_count: Array.isArray(payload.data_table_draft && payload.data_table_draft.rows) ? payload.data_table_draft.rows.length : 0,
    table_workspace: payload.table_workspace && typeof payload.table_workspace === 'object' ? payload.table_workspace : {},
    table_selection: payload.table_selection && typeof payload.table_selection === 'object' ? payload.table_selection : {},
    selected_requirement: payload.selected_requirement && typeof payload.selected_requirement === 'object' ? payload.selected_requirement : {},
    evidence_summary: payload.evidence_summary && typeof payload.evidence_summary === 'object' ? payload.evidence_summary : {},
    batch_item_context: payload.batch_item_context && typeof payload.batch_item_context === 'object' ? payload.batch_item_context : {},
  };
}

const FIELD_JUDGEMENTS = new Set(['ok', 'needs_review', 'missing', 'better_alternative']);
const FIELD_ACTIONS = new Set(['keep', 'change_source', 'manual_fill', 'ask_user', 'ignore']);
const API_JUDGEMENTS = new Set(['useful', 'partial', 'risky', 'not_recommended']);
const JOIN_JUDGEMENTS = new Set(['ok', 'needs_input', 'risky', 'not_needed']);
const SUMMARY_STATUS = new Set(['ok', 'needs_review', 'needs_input', 'blocked', 'unavailable']);

function normalizeFieldAdviceEntry(entry) {
  const item = entry && typeof entry === 'object' ? entry : {};
  const judgement = FIELD_JUDGEMENTS.has(item.judgement) ? item.judgement : 'needs_review';
  const suggestedAction = FIELD_ACTIONS.has(item.suggested_action) ? item.suggested_action : 'ask_user';
  return {
    field_path: String(item.field_path || ''),
    field_name: String(item.field_name || ''),
    current_source_api_id: String(item.current_source_api_id || ''),
    current_source_field_path: String(item.current_source_field_path || ''),
    judgement,
    confidence: coerceConfidence(item.confidence),
    suggested_action: suggestedAction,
    reason: String(item.reason || ''),
    suggested_source_api_id: String(item.suggested_source_api_id || ''),
    suggested_source_field_path: String(item.suggested_source_field_path || ''),
  };
}

// applicable_actions 由 field_advice 派生，只描述对 draft overlay 的 patch，不涉及合同确认。
function applicableActionsFromFieldAdvice(fieldAdvice) {
  return fieldAdvice
    .filter(item => ['ok', 'better_alternative'].includes(item.judgement) && (item.suggested_source_field_path || item.judgement === 'ok'))
    .map(item => ({
      action_id: `apply-${item.field_name || item.field_path}`,
      type: 'update_field_mapping',
      field_path: item.field_path,
      patch: {
        source_api_id: item.suggested_source_api_id,
        source_field_path: item.suggested_source_field_path,
        mapping_status: 'suggested',
        confidence: item.confidence,
        human_note: `PI 建议（置信度 ${item.confidence}）`,
      },
    }));
}

function normalizePiMappingAdvice(raw, context) {
  let parsed = null;
  if (raw && typeof raw === 'object') {
    parsed = raw;
  } else if (typeof raw === 'string' && raw.trim()) {
    const match = raw.match(/\{[\s\S]*\}/);
    if (match) {
      try {
        parsed = JSON.parse(match[0]);
      } catch {
        parsed = null;
      }
    }
  }
  if (!parsed || typeof parsed !== 'object') {
    return buildFallbackAdvice(context, {
      status: 'needs_review',
      text: typeof raw === 'string' && raw.trim() ? raw.trim() : 'PI 未返回结构化建议，已用确定性规则生成待确认草稿。',
      degraded: true,
    });
  }
  const summaryStatus = parsed.summary && SUMMARY_STATUS.has(parsed.summary.status) ? parsed.summary.status : 'needs_review';
  const fieldAdvice = (Array.isArray(parsed.field_advice) ? parsed.field_advice : []).map(normalizeFieldAdviceEntry);
  const apiReview = (Array.isArray(parsed.api_review) ? parsed.api_review : []).map(entry => {
    const item = entry && typeof entry === 'object' ? entry : {};
    return {
      api_id: String(item.api_id || ''),
      api_name: String(item.api_name || ''),
      judgement: API_JUDGEMENTS.has(item.judgement) ? item.judgement : 'partial',
      reason: String(item.reason || ''),
    };
  });
  const rawJoin = parsed.join_advice && typeof parsed.join_advice === 'object' ? parsed.join_advice : {};
  const joinAdvice = {
    judgement: JOIN_JUDGEMENTS.has(rawJoin.judgement) ? rawJoin.judgement : 'needs_input',
    recommended_primary_api_id: String(rawJoin.recommended_primary_api_id || ''),
    recommended_join_keys: Array.isArray(rawJoin.recommended_join_keys) ? rawJoin.recommended_join_keys.map(String) : [],
    grain: String(rawJoin.grain || 'unknown'),
    time_window: String(rawJoin.time_window || ''),
    risks: Array.isArray(rawJoin.risks) ? rawJoin.risks.map(String) : [],
  };
  return {
    schema_version: 'pi-data-mapping-advice-v1',
    node_id: context.node_id,
    advice_id: String(parsed.advice_id || `pi-advice-${Date.now()}`),
    created_at: String(parsed.created_at || new Date().toISOString()),
    input_refs: {
      data_mapping_contract_status: String((parsed.input_refs && parsed.input_refs.data_mapping_contract_status) || 'suggested'),
      selected_api_count: context.selected_api_count,
      field_coverage_count: context.field_coverage_count,
      confirmed_field_count: context.confirmed_field_count,
    },
    summary: {
      status: summaryStatus,
      text: String((parsed.summary && parsed.summary.text) || ''),
    },
    api_review: apiReview,
    field_advice: fieldAdvice,
    join_advice: joinAdvice,
    derived_field_advice: normalizeDerivedFieldAdvice(parsed.derived_field_advice, context),
    derived_field_rows: normalizeDerivedFieldRows(parsed.derived_field_rows || parsed.rows || (parsed.derived_field_fill && parsed.derived_field_fill.rows)),
    insight_draft_advice: normalizeInsightDraftAdvice(parsed.insight_draft_advice, context),
    table_edit_proposal: normalizeTableEditProposal(parsed.table_edit_proposal, context),
    insight_collaboration_proposal: normalizeInsightCollaborationProposal(parsed.insight_collaboration_proposal, context),
    questions_for_user: Array.isArray(parsed.questions_for_user) ? parsed.questions_for_user.map(String) : [],
    applicable_actions: applicableActionsFromFieldAdvice(fieldAdvice),
    requires_human_confirmation: true,
    source: { provider: 'pi_agent', degraded: false },
  };
}

function tableWorkspaceCatalog(context) {
  const workspace = context.table_workspace && typeof context.table_workspace === 'object' ? context.table_workspace : {};
  const aliases = new Map();
  const fields = new Set();
  const workspaceFields = (Array.isArray(workspace.fields) ? workspace.fields : [])
    .concat(Array.isArray(workspace.extension_fields) ? workspace.extension_fields : []);
  for (const item of workspaceFields) {
    const canonical = String(item && (item.field_name || item.title || item.field_path) || '');
    if (!canonical) continue;
    fields.add(canonical);
    for (const alias of [item && item.field_path, item && item.field_name, item && item.title, item && item.canonical_field_name]) {
      const key = String(alias || '');
      if (key) aliases.set(key, canonical);
    }
  }
  const rows = new Set();
  const rowAliases = new Map();
  const ambiguousRowAliases = new Set();
  const addRowAlias = (alias, canonical) => {
    const key = String(alias || '').trim();
    if (!key || ambiguousRowAliases.has(key)) return;
    const existing = rowAliases.get(key);
    if (existing && existing !== canonical) {
      rowAliases.delete(key);
      ambiguousRowAliases.add(key);
      return;
    }
    rowAliases.set(key, canonical);
  };
  for (const item of Array.isArray(workspace.row_meta) ? workspace.row_meta : []) {
    const canonical = String(item && item.row_id || '').trim();
    if (!canonical) continue;
    const sourceIdentity = String(item && item.source_identity || '').trim();
    rows.add(canonical);
    addRowAlias(canonical, canonical);
    addRowAlias(sourceIdentity, canonical);
    if (canonical.startsWith('goods:')) addRowAlias(canonical.slice('goods:'.length), canonical);
    if (sourceIdentity) addRowAlias(`goods:${sourceIdentity}`, canonical);
  }
  return { aliases, fields, rows, rowAliases };
}

function canonicalWorkspaceField(catalog, fieldPath) {
  const value = String(fieldPath || '');
  return catalog.aliases.get(value) || value;
}

function canonicalWorkspaceRowId(catalog, rowId) {
  const value = String(rowId || '').trim();
  if (catalog.rows.has(value)) return value;
  return catalog.rowAliases.get(value) || value;
}

function normalizeProposalEvidenceRefs(rawRefs) {
  const refs = [];
  for (const raw of Array.isArray(rawRefs) ? rawRefs : []) {
    if (typeof raw === 'string' || typeof raw === 'number') {
      const value = String(raw).trim();
      if (value) refs.push(value);
      continue;
    }
    if (!raw || typeof raw !== 'object') continue;
    const direct = String(raw.evidence_ref || raw.ref || raw.path || '').trim();
    if (direct) {
      refs.push(direct);
      continue;
    }
    const rowId = String(raw.row_id || '').trim();
    const fieldPath = String(raw.field_path || raw.field_name || '').trim();
    if (rowId && fieldPath) refs.push(`${rowId} · ${fieldPath}`);
    else if (fieldPath) refs.push(fieldPath);
  }
  return Array.from(new Set(refs));
}

function tableSelectionAllows(selection, rowId, fieldPath, catalog) {
  const scopeMode = String(selection && selection.scope_mode || 'cells');
  const canonicalRowId = canonicalWorkspaceRowId(catalog, rowId);
  const canonicalField = canonicalWorkspaceField(catalog, fieldPath);
  if (!catalog.rows.has(canonicalRowId) || !catalog.fields.has(canonicalField)) return false;
  if (scopeMode === 'whole_table') return true;
  if (scopeMode === 'column') {
    const fieldPaths = Array.isArray(selection.field_paths)
      ? selection.field_paths.map(item => canonicalWorkspaceField(catalog, item))
      : [];
    return fieldPaths.includes(canonicalField);
  }
  if (scopeMode === 'row') {
    const rowIds = Array.isArray(selection.row_ids)
      ? selection.row_ids.map(item => canonicalWorkspaceRowId(catalog, item))
      : [];
    return rowIds.includes(canonicalRowId);
  }
  const cells = Array.isArray(selection && selection.cells) ? selection.cells : [];
  return cells.some(cell => canonicalWorkspaceRowId(catalog, cell && cell.row_id) === canonicalRowId
    && canonicalWorkspaceField(catalog, cell && cell.field_path) === canonicalField);
}

const KEYWORD_DEMAND_TYPES = new Set([
  '品类需求', '人群需求', '属性需求', '功能需求',
  '场景需求', '品牌需求', '风格需求', '定制需求',
]);

const KEYWORD_DEMAND_TYPE_ALIASES = new Map(Array.from(KEYWORD_DEMAND_TYPES).flatMap(value => [
  [value, value],
  [value.slice(0, -2), value],
]));

function normalizeKeywordRootTerms(value) {
  const terms = Array.isArray(value)
    ? value
    : typeof value === 'string'
      ? value.split(/[，,、;；|\n]+/)
      : [];
  return Array.from(new Set(terms
    .filter(item => typeof item === 'string')
    .map(item => item.trim())
    .filter(Boolean)));
}

function normalizeKeywordDemandType(value) {
  const normalized = String(value || '').trim();
  return KEYWORD_DEMAND_TYPE_ALIASES.get(normalized) || '';
}

function keywordPatchCandidates(rawPatch) {
  const patch = rawPatch && typeof rawPatch === 'object' && !Array.isArray(rawPatch) ? rawPatch : {};
  const keys = Object.keys(patch).map(String).sort();
  const explicitField = patch.field_path || patch.field_name || patch.field;
  if (explicitField) {
    const hasNewValue = Object.prototype.hasOwnProperty.call(patch, 'new_value');
    const hasValue = Object.prototype.hasOwnProperty.call(patch, 'value');
    return [{
      patch: {
        ...patch,
        field_path: explicitField,
        new_value: hasNewValue ? patch.new_value : hasValue ? patch.value : undefined,
      },
      diagnostic: {
        patch_format: hasNewValue ? 'standard_field_patch' : hasValue ? 'field_value_patch' : 'field_patch_missing_value',
        original_patch_keys: keys,
        normalized_field: String(explicitField || ''),
        value_type: hasNewValue ? valueTypeName(patch.new_value) : hasValue ? valueTypeName(patch.value) : 'undefined',
      },
    }];
  }
  const flatFields = ['root_terms', 'demand_type'].filter(field => Object.prototype.hasOwnProperty.call(patch, field));
  if (flatFields.length > 0) {
    return flatFields.map(field => ({
      patch: {
        row_id: patch.row_id,
        field_path: field,
        old_value: patch.old_value,
        new_value: patch[field],
        reason: patch.reason,
        confidence: patch.confidence,
        evidence_refs: patch.evidence_refs,
      },
      diagnostic: {
        patch_format: 'flat_keyword_patch',
        original_patch_keys: keys,
        normalized_field: field,
        value_type: valueTypeName(patch[field]),
      },
    }));
  }
  return [{
    patch,
    diagnostic: {
      patch_format: 'unsupported_patch_shape',
      original_patch_keys: keys,
      normalized_field: '',
      value_type: 'undefined',
    },
    unsupported: true,
  }];
}

function valueTypeName(value) {
  if (Array.isArray(value)) return 'array';
  if (value === null) return 'null';
  return typeof value;
}

function normalizeTableEditProposal(raw, context) {
  if (String(context.intent || '') !== 'table_edit_advice' && (!raw || typeof raw !== 'object')) return null;
  const item = raw && typeof raw === 'object' ? raw : {};
  const catalog = tableWorkspaceCatalog(context);
  const selection = context.table_selection || {};
  const selectedCells = new Map((Array.isArray(selection.cells) ? selection.cells : []).map(cell => [
    `${canonicalWorkspaceRowId(catalog, cell && cell.row_id)}\u0000${canonicalWorkspaceField(catalog, cell && cell.field_path)}`,
    cell,
  ]));
  const risks = Array.isArray(item.risks) ? item.risks.map(String) : [];
  const rawPatches = Array.isArray(item.patches) ? item.patches : [];
  const keywordBatch = String(context.batch_item_context && context.batch_item_context.subject_kind || '') === 'keyword'
    || (catalog.fields.has('keyword') && catalog.fields.has('root_terms') && catalog.fields.has('demand_type'));
  let rejected = 0;
  let outsideSelectionRejected = 0;
  const rejectedPatchRefs = [];
  const patchDiagnostics = [];
  const patches = [];
  const candidates = rawPatches.flatMap(rawPatch => keywordBatch
    ? keywordPatchCandidates(rawPatch)
    : [{
        patch: rawPatch && typeof rawPatch === 'object' ? rawPatch : {},
        diagnostic: {
          patch_format: 'standard_field_patch',
          original_patch_keys: Object.keys(rawPatch && typeof rawPatch === 'object' ? rawPatch : {}).map(String).sort(),
          normalized_field: String(rawPatch && (rawPatch.field_path || rawPatch.field_name || rawPatch.field) || ''),
          value_type: valueTypeName(rawPatch && rawPatch.new_value),
        },
      }]);
  for (const candidate of candidates) {
    const patch = candidate.patch;
    const diagnostic = candidate.diagnostic;
    if (candidate.unsupported) {
      rejected += 1;
      risks.push('unsupported_patch_shape_rejected');
      rejectedPatchRefs.push({
        row_id: String(patch.row_id || ''),
        field_path: '',
        reason: 'unsupported_patch_shape',
        patch_keys: diagnostic.original_patch_keys,
      });
      patchDiagnostics.push({ status: 'rejected', reason: 'unsupported_patch_shape', ...diagnostic });
      continue;
    }
    const rowId = canonicalWorkspaceRowId(catalog, patch.row_id);
    const rawFieldPath = patch.field_path || patch.field_name || patch.field;
    const fieldPath = canonicalWorkspaceField(catalog, rawFieldPath);
    if (!tableSelectionAllows(selection, rowId, fieldPath, catalog)) {
      rejected += 1;
      outsideSelectionRejected += 1;
      rejectedPatchRefs.push({
        row_id: String(patch.row_id || ''),
        field_path: String(rawFieldPath || ''),
        reason: 'outside_selection',
        patch_keys: diagnostic.original_patch_keys,
      });
      patchDiagnostics.push({ status: 'rejected', reason: 'outside_selection', ...diagnostic });
      continue;
    }
    const selected = selectedCells.get(`${rowId}\u0000${fieldPath}`) || {};
    const oldValue = Object.prototype.hasOwnProperty.call(selected, 'effective_value') ? selected.effective_value : patch.old_value;
    const sourceKind = String(selected.source_kind || '');
    let newValue = patch.new_value;
    if (keywordBatch && fieldPath === 'root_terms') {
      newValue = normalizeKeywordRootTerms(newValue);
      if (newValue.length === 0) {
        rejected += 1;
        risks.push('invalid_root_terms_rejected');
        rejectedPatchRefs.push({
          row_id: rowId,
          field_path: fieldPath,
          reason: 'invalid_root_terms',
          patch_keys: diagnostic.original_patch_keys,
        });
        patchDiagnostics.push({ status: 'rejected', reason: 'invalid_root_terms', ...diagnostic });
        continue;
      }
    }
    if (keywordBatch && fieldPath === 'demand_type') {
      newValue = normalizeKeywordDemandType(newValue);
      if (!newValue) {
        rejected += 1;
        risks.push('invalid_demand_type_rejected');
        rejectedPatchRefs.push({
          row_id: rowId,
          field_path: fieldPath,
          reason: 'invalid_demand_type',
          patch_keys: diagnostic.original_patch_keys,
        });
        patchDiagnostics.push({ status: 'rejected', reason: 'invalid_demand_type', ...diagnostic });
        continue;
      }
    }
    patches.push({
      operation: newValue === '' ? 'clear_cell' : 'set_cell',
      row_id: rowId,
      field_path: fieldPath,
      old_value: oldValue,
      new_value: newValue,
      reason: String(patch.reason || ''),
      confidence: coerceConfidence(patch.confidence),
      evidence_refs: normalizeProposalEvidenceRefs(patch.evidence_refs),
      source_kind: 'pi_derived',
      overrides_api_value: sourceKind === 'api' && oldValue !== undefined && oldValue !== null && String(oldValue).trim() !== '' && newValue !== oldValue,
    });
    patchDiagnostics.push({ status: 'accepted', reason: '', ...diagnostic, normalized_field: fieldPath });
  }
  if (outsideSelectionRejected > 0) risks.push('patch_outside_selection_rejected');
  return {
    schema_version: 'data-table-edit-proposal-v1',
    proposal_id: String(item.proposal_id || `table-proposal-${Date.now()}`),
    workspace_revision: Number(context.table_workspace && context.table_workspace.revision || 0),
    scope: context.table_selection || {},
    patches,
    summary: String(item.summary || ''),
    risks: Array.from(new Set(risks)),
    input_patch_count: rawPatches.length,
    raw_patch_count: candidates.length,
    accepted_patch_count: patches.length,
    rejected_patch_count: rejected,
    rejected_patch_refs: rejectedPatchRefs,
    patch_diagnostics: patchDiagnostics,
    status: patches.length > 0 ? 'pending' : 'no_applicable_patch',
    requires_human_application: true,
  };
}

function normalizeInsightCollaborationProposal(raw, context) {
  if (String(context.intent || '') !== 'insight_collaboration' && (!raw || typeof raw !== 'object')) return null;
  const item = raw && typeof raw === 'object' ? raw : {};
  const catalog = tableWorkspaceCatalog(context);
  const requestedId = String(context.selected_requirement && context.selected_requirement.requirement_id || '');
  const proposalId = String(item.requirement_id || requestedId);
  const rawBindings = Array.isArray(item.evidence_bindings) ? item.evidence_bindings : [];
  const invalid = proposalId !== requestedId || rawBindings.some(binding => {
    const fieldPath = String(binding && binding.field_path || '');
    const rowId = String(binding && binding.row_id || '');
    return (fieldPath && !catalog.fields.has(fieldPath)) || (rowId && !catalog.rows.has(rowId));
  });
  const risks = Array.isArray(item.risks) ? item.risks.map(String) : [];
  if (invalid) risks.push('unknown_evidence_reference_rejected');
  return {
    schema_version: 'insight-edit-proposal-v1',
    proposal_id: String(item.proposal_id || `insight-proposal-${Date.now()}`),
    requirement_id: requestedId,
    proposed_text: String(item.proposed_text || item.draft_text || ''),
    evidence_bindings: invalid ? [] : rawBindings.map(binding => ({
      kind: String(binding.kind || (binding.row_id ? 'row' : 'field')),
      row_id: String(binding.row_id || ''),
      field_path: String(binding.field_path || ''),
    })),
    risks: Array.from(new Set(risks)),
    questions_for_user: Array.isArray(item.questions_for_user) ? item.questions_for_user.map(String) : [],
    status: invalid ? 'invalid_evidence' : (String(item.proposed_text || item.draft_text || '').trim() ? 'pending' : 'needs_evidence'),
    requires_human_application: true,
  };
}

function attachCollaborationProposals(advice, context) {
  return {
    ...advice,
    table_edit_proposal: advice.table_edit_proposal || normalizeTableEditProposal(null, context),
    insight_collaboration_proposal: advice.insight_collaboration_proposal || normalizeInsightCollaborationProposal(null, context),
  };
}

function normalizeInsightDraftAdvice(raw, context) {
  const item = raw && typeof raw === 'object' ? raw : {};
  const fallback = insightDraftAdviceFromContext(context);
  return {
    status: String(item.status || fallback.status),
    text: String(item.text || item.draft_text || fallback.text),
    requirements: Array.isArray(item.requirements) ? item.requirements : fallback.requirements,
    evidence_fields: Array.isArray(item.evidence_fields) ? item.evidence_fields.map(String) : fallback.evidence_fields,
    evidence_refs: Array.isArray(item.evidence_refs) ? item.evidence_refs.map(String) : fallback.evidence_refs,
    risks: Array.isArray(item.risks) ? item.risks.map(String) : fallback.risks,
    questions_for_user: Array.isArray(item.questions_for_user) ? item.questions_for_user.map(String) : fallback.questions_for_user,
    human_confirmation: { status: 'unconfirmed' },
  };
}

function normalizeDerivedFieldAdvice(rawList, context) {
  if (Array.isArray(rawList) && rawList.length > 0) {
    return rawList.map(item => {
      const entry = item && typeof item === 'object' ? item : {};
      return {
        field_path: String(entry.field_path || ''),
        field_name: String(entry.field_name || ''),
        status: String(entry.status || 'needs_review'),
        suggested_analysis: String(entry.suggested_analysis || entry.analysis || ''),
        required_inputs: Array.isArray(entry.required_inputs) ? entry.required_inputs.map(String) : [],
        available_evidence_fields: Array.isArray(entry.available_evidence_fields) ? entry.available_evidence_fields.map(String) : [],
        draft_value: String(entry.draft_value || ''),
        confidence: coerceConfidence(entry.confidence),
        risks: Array.isArray(entry.risks) ? entry.risks.map(String) : [],
      };
    });
  }
  return derivedFieldAdviceFromContext(context);
}

function normalizeDerivedFieldRows(rawList) {
  const rows = Array.isArray(rawList) ? rawList : [];
  return rows
    .map(item => {
      const row = item && typeof item === 'object' ? item : {};
      const rowIndex = Number(row.row_index);
      const rawFields = row.fields && typeof row.fields === 'object' ? row.fields : {};
      const fields = {};
      for (const [fieldName, value] of Object.entries(rawFields)) {
        const cell = value && typeof value === 'object' ? value : { draft_value: value };
        fields[String(fieldName)] = {
          draft_value: String(cell.draft_value ?? cell.value ?? ''),
          confidence: coerceConfidence(cell.confidence),
          evidence_fields: Array.isArray(cell.evidence_fields) ? cell.evidence_fields.map(String) : [],
          risks: Array.isArray(cell.risks) ? cell.risks.map(String) : [],
        };
      }
      return {
        row_index: Number.isFinite(rowIndex) ? rowIndex : -1,
        fields,
      };
    })
    .filter(item => item.row_index >= 0 && Object.keys(item.fields).length > 0);
}

function derivedFieldAdviceFromContext(context) {
  const baseline = Array.isArray(context.field_coverage_plan) ? context.field_coverage_plan : [];
  const requirements = Array.isArray(context.output_field_requirements) ? context.output_field_requirements : [];
  const byPath = new Map(baseline.map(item => [String(item.field_path || item.field_name || ''), item]));
  const candidates = [];
  for (const item of baseline) {
    const fieldName = String(item.field_name || item.title || '');
    if (String(item.mapping_status || item.status || '') === 'derived_or_manual_required' || item.source_kind === 'pi_derived' || DERIVED_FIELD_NAMES.has(fieldName)) {
      candidates.push(item);
    }
  }
  for (const item of requirements) {
    const fieldName = String(item.field_name || item.title || '');
    const key = String(item.field_path || item.field_name || '');
    if (!DERIVED_FIELD_NAMES.has(fieldName) && !DERIVED_FIELD_NAMES.has(normalizeFieldText(fieldName))) continue;
    if (!candidates.some(existing => String(existing.field_path || existing.field_name || '') === key)) {
      candidates.push(byPath.get(key) || item);
    }
  }
  return candidates.map(item => ({
    field_path: String(item.field_path || ''),
    field_name: String(item.field_name || item.title || ''),
    status: 'needs_evidence',
    suggested_analysis: '基于已确认 API 字段、上游中间产物、样例行、商品标题/图片/卖点等证据进行即席分析；无证据时只生成填充方案，不生成事实值。',
    required_inputs: ['confirmed_field_mapping', 'upstream_artifacts_or_sample_rows'],
    available_evidence_fields: [],
    draft_value: '',
    confidence: 0,
    risks: ['派生字段不是 API 原生字段，必须人工确认后才能进入节点产物。'],
  }));
}

function insightDraftAdviceFromContext(context) {
  const requirements = Array.isArray(context.insight_requirements) ? context.insight_requirements : [];
  const hasRows = Number(context.data_table_rows_count || 0) > 0;
  return {
    status: hasRows ? 'needs_runtime_or_human_review' : 'needs_evidence_or_runtime',
    text: '',
    requirements,
    evidence_fields: [],
    evidence_refs: [],
    risks: hasRows
      ? ['当前为分析结论草稿建议，必须经过人工确认后才能成为节点事实。']
      : ['缺少可引用的数据表样例行，不能生成事实性分析结论。'],
    questions_for_user: requirements.length > 0
      ? requirements.map(item => `请确认结论问题「${String(item.question || item.title || '分析结论')}」需要引用哪些字段或样例行。`)
      : ['请先确认分析结论要求和证据字段。'],
    human_confirmation: { status: 'unconfirmed' },
  };
}

// 确定性 fallback：基于 baseline field_coverage_plan 生成逐字段 advice，供 PI 未配置/纯文本/失败时兜底。
function buildFallbackAdvice(context, options = {}) {
  const status = options.status || 'needs_review';
  const baseline = Array.isArray(context.field_coverage_plan) ? context.field_coverage_plan : [];
  const requirements = Array.isArray(context.output_field_requirements) ? context.output_field_requirements : [];
  const byPath = new Map(baseline.map(item => [String(item.field_path || item.field_name || ''), item]));
  const source = requirements.length > 0 ? requirements : baseline;
  const fieldAdvice = source.map(field => {
    const key = String(field.field_path || field.field_name || '');
    const mapped = byPath.get(key) || (baseline.length === 0 ? field : {});
    const apiFieldPath = String(mapped.source_field_path || mapped.api_field_path || '');
    const hasSource = Boolean(apiFieldPath);
    return normalizeFieldAdviceEntry({
      field_path: key,
      field_name: String(field.field_name || mapped.field_name || ''),
      current_source_api_id: String(mapped.source_api_id || ''),
      current_source_field_path: apiFieldPath,
      judgement: hasSource ? 'needs_review' : 'missing',
      confidence: hasSource ? coerceConfidence(mapped.confidence) : 0,
      suggested_action: hasSource ? 'keep' : 'ask_user',
      reason: hasSource ? '确定性规则匹配，待人工确认口径。' : '未覆盖必填字段，需选择 API 或人工补充。',
      suggested_source_api_id: String(mapped.source_api_id || ''),
      suggested_source_field_path: apiFieldPath,
    });
  });
  const joinPlan = context.join_plan || {};
  const needsJoin = context.selected_api_count > 1 && !(Array.isArray(joinPlan.join_keys) && joinPlan.join_keys.length > 0);
  let summaryStatus = status;
  let summaryText = options.text || '';
  if (context.selected_api_count === 0) {
    summaryStatus = 'needs_input';
    summaryText = summaryText || '请先在中间工作区一键生成字段覆盖方案，再对错配、低置信或派生字段发起纠错。';
  }
  return attachCollaborationProposals({
    schema_version: 'pi-data-mapping-advice-v1',
    node_id: context.node_id,
    advice_id: `pi-advice-fallback-${Date.now()}`,
    created_at: new Date().toISOString(),
    input_refs: {
      data_mapping_contract_status: 'suggested',
      selected_api_count: context.selected_api_count,
      field_coverage_count: context.field_coverage_count,
      confirmed_field_count: context.confirmed_field_count,
    },
    summary: { status: summaryStatus, text: summaryText },
    api_review: [],
    field_advice: fieldAdvice,
    join_advice: {
      judgement: needsJoin ? 'needs_input' : 'not_needed',
      recommended_primary_api_id: String(joinPlan.primary_api_id || ''),
      recommended_join_keys: Array.isArray(joinPlan.join_keys) ? joinPlan.join_keys.map(String) : [],
      grain: String(joinPlan.grain || 'unknown'),
      time_window: String(joinPlan.time_window || ''),
      risks: Array.isArray(joinPlan.risks) ? joinPlan.risks.map(String) : [],
    },
    derived_field_advice: derivedFieldAdviceFromContext(context),
    derived_field_rows: [],
    insight_draft_advice: insightDraftAdviceFromContext(context),
    questions_for_user: context.selected_api_count === 0 ? ['请先在中间工作区生成字段覆盖方案'] : [],
    applicable_actions: applicableActionsFromFieldAdvice(fieldAdvice),
    requires_human_confirmation: true,
    source: { provider: 'deterministic_fallback', degraded: Boolean(options.degraded) },
  }, context);
}

function buildUnavailableAdvice(context, reason) {
  return attachCollaborationProposals({
    schema_version: 'pi-data-mapping-advice-v1',
    node_id: context.node_id,
    advice_id: `pi-advice-unavailable-${Date.now()}`,
    created_at: new Date().toISOString(),
    input_refs: {
      data_mapping_contract_status: 'suggested',
      selected_api_count: context.selected_api_count,
      field_coverage_count: context.field_coverage_count,
      confirmed_field_count: context.confirmed_field_count,
    },
    summary: {
      status: 'unavailable',
      text: 'PI Agent 未就绪，仍可在中间工作台手动确认字段映射。',
    },
    api_review: [],
    field_advice: buildFallbackAdvice(context, { status: 'needs_review' }).field_advice,
    join_advice: { judgement: 'needs_input', recommended_primary_api_id: '', recommended_join_keys: [], grain: 'unknown', time_window: '', risks: [] },
    derived_field_advice: derivedFieldAdviceFromContext(context),
    derived_field_rows: [],
    insight_draft_advice: insightDraftAdviceFromContext(context),
    questions_for_user: [],
    applicable_actions: [],
    requires_human_confirmation: true,
    source: { provider: 'pi_agent', degraded: true, reason: String(reason || 'not_ready') },
  }, context);
}

// PI 建议 evidence，剥离敏感字段，仅保留请求摘要 + 归一 advice。
function persistPiMappingAdvice(nodeId, advice, context) {
  ensureDir(EVIDENCE_DIR);
  const evidencePath = path.join(EVIDENCE_DIR, `${nodeId}.pi_mapping_advice.json`);
  fs.writeFileSync(evidencePath, JSON.stringify({
    node_id: nodeId,
    created_at: new Date().toISOString(),
    request_summary: {
      selected_api_count: context.selected_api_count,
      field_coverage_count: context.field_coverage_count,
      confirmed_field_count: context.confirmed_field_count,
    },
    advice,
    source: advice.source || { provider: 'pi_agent', degraded: false },
  }, null, 2));
  return `evidence/${nodeId}.pi_mapping_advice.json`;
}

function persistPiMappingThread(nodeId, payload, context, result) {
  const history = conversationHistoryFromPayload(payload);
  if (String(payload && payload.intent || '') !== 'mapping_correction' && history.length === 0) return '';
  ensureDir(EVIDENCE_DIR);
  const threadPath = path.join(EVIDENCE_DIR, `${nodeId}.pi_mapping_thread.jsonl`);
  const record = {
    node_id: nodeId,
    created_at: new Date().toISOString(),
    intent: String(payload.intent || 'data_mapping_advice'),
    target_field: context.target_field || {},
    user_message: String(payload.message || ''),
    conversation_history: history,
    advice_id: result && result.advice && result.advice.advice_id || '',
    status: result && result.status || '',
    provider: result && result.provider || 'pi_agent',
  };
  fs.appendFileSync(threadPath, `${JSON.stringify(record)}\n`);
  return `evidence/${nodeId}.pi_mapping_thread.jsonl`;
}

function isCollaborationIntent(payload) {
  return ['table_edit_advice', 'insight_collaboration', 'free_chat'].includes(String(payload && payload.intent || ''));
}

function collaborationTimeoutMs(payload) {
  const configured = Number(process.env.PI_RPC_TIMEOUT_MS || 0);
  if (Number.isFinite(configured) && configured > 0) return configured;
  return String(payload && payload.intent || '') === 'insight_collaboration' ? 180000 : 120000;
}

function structuredPiAdvice(raw) {
  if (raw && typeof raw === 'object' && !Array.isArray(raw)) return raw;
  if (typeof raw !== 'string' || !raw.trim()) return null;
  const match = raw.match(/\{[\s\S]*\}/);
  if (!match) return null;
  try {
    const parsed = JSON.parse(match[0]);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function collaborationAdviceValid(parsed, payload) {
  if (!parsed || typeof parsed !== 'object') return false;
  const intent = String(payload && payload.intent || '');
  if (intent === 'table_edit_advice') {
    return Boolean(parsed.table_edit_proposal && typeof parsed.table_edit_proposal === 'object');
  }
  if (intent === 'insight_collaboration') {
    return Boolean(parsed.insight_collaboration_proposal && typeof parsed.insight_collaboration_proposal === 'object');
  }
  return intent === 'free_chat' ? Boolean(parsed.summary || parsed.response_text || parsed.answer) : true;
}

async function callPiAgent(node, payload, runtime = {}) {
  const context = piAdviceContext(node, payload);
  const status = runtime.skip_status_probe === true
    ? { status: 'ready', reason: 'batch_call_spawn_is_authoritative' }
    : piAgentStatus();
  const collaborationIntent = isCollaborationIntent(payload);
  const strictCollaboration = collaborationIntent && payload.legacy_compat !== true;
  const env = piProcessEnv();
  const piModel = resolvePiModel(payload, env);
  if (status.status !== 'ready') {
    const advice = strictCollaboration ? null : buildUnavailableAdvice(context, status.reason);
    const result = {
      ok: false,
      status: status.status,
      reason: status.reason,
      provider: 'pi_agent',
      advice,
      requested_model: piModel.model,
      actual_model: '',
      model_resolution_status: 'unknown',
      model_comparison_reason: 'unknown',
    };
    if (advice) result.evidence_ref = persistPiMappingAdvice(context.node_id, advice, context);
    const threadRef = persistPiMappingThread(context.node_id, payload, context, result);
    if (threadRef) result.thread_ref = threadRef;
    return result;
  }
  const prompt = piPromptForDataMapping(node, payload);
  const requestId = `pi-${Date.now()}`;
  // pi rpc 协议的命令判别字段是 type，不是 command；用错字段会被拒为 "Unknown command: undefined"。
  // --no-session：单次数据映射建议无需持久化会话，避免 session 目录不可写时整体调用失败。
  const piArgs = [
    '--mode', 'rpc',
    '--no-session',
    '--no-tools',
    '--no-skills',
    '--no-context-files',
    '--no-prompt-templates',
    '--no-extensions',
  ];
  if (piModel.model) piArgs.push('--model', piModel.model);
  const result = await runPiRpcOnce(piAgentBin(), piArgs, {
    request_id: requestId,
    prompt,
    timeout_ms: collaborationIntent ? collaborationTimeoutMs(payload) : Number(process.env.PI_RPC_TIMEOUT_MS || 60000),
    cwd: APP_ROOT,
    env,
    call_id: runtime.call_id,
    on_event: runtime.on_event,
  });
  if (result.error) {
    const advice = strictCollaboration ? null : buildFallbackAdvice(context, {
      status: 'needs_review',
      text: 'PI 调用失败，已用确定性规则生成待确认草稿。',
      degraded: true,
    });
    const response = {
      ok: false,
      status: 'error',
      reason: 'pi_spawn_failed',
      provider: 'pi_agent',
      error: result.error.message,
      advice,
      requested_model: piModel.model,
      actual_model: '',
      model_resolution_status: 'unknown',
      model_comparison_reason: 'unknown',
      duration_ms: Number(result.duration_ms || 0),
    };
    if (advice) response.evidence_ref = persistPiMappingAdvice(context.node_id, advice, context);
    const threadRef = persistPiMappingThread(context.node_id, payload, context, response);
    if (threadRef) response.thread_ref = threadRef;
    return response;
  }
  const responseText = parsePiRpcText(result.stdout);
  const parsedAdvice = structuredPiAdvice(responseText);
  const structurallyValid = !strictCollaboration || collaborationAdviceValid(parsedAdvice, payload);
  const succeeded = result.status === 0 && result.saw_agent_end && Boolean(responseText) && structurallyValid && !result.cancelled;
  const advice = succeeded
    ? normalizePiMappingAdvice(parsedAdvice || responseText, context)
    : strictCollaboration
      ? null
      : buildFallbackAdvice(context, { status: 'needs_review', text: 'PI 未返回有效内容，已用确定性规则兜底。', degraded: true });
  const failureReason = result.cancelled
    ? 'pi_cancelled'
    : result.timed_out
    ? 'pi_rpc_timeout'
    : result.rpc_rejected
      ? 'pi_rpc_rejected'
      : result.status !== 0 && result.status !== null
        ? 'pi_rpc_failed'
        : !responseText
          ? 'pi_empty_response'
          : !result.saw_agent_end
            ? 'pi_incomplete_response'
            : !structurallyValid
              ? 'pi_invalid_response'
            : 'pi_rpc_failed';
  const actualModel = String(result.actual_model || '');
  const modelComparison = compareAgentModels(piModel.model, actualModel);
  const response = {
    ok: succeeded,
    status: succeeded ? 'ok' : ['pi_empty_response', 'pi_incomplete_response', 'pi_rpc_timeout'].includes(failureReason) ? 'degraded' : 'error',
    reason: succeeded ? 'ready' : failureReason,
    provider: 'pi_agent',
    model: piModel.model,
    model_provider: piModel.provider,
    requested_model: piModel.model,
    actual_model: actualModel,
    model_resolution_status: modelComparison.status,
    model_comparison_reason: modelComparison.reason,
    duration_ms: Number(result.duration_ms || 0),
    event_count: Number(result.event_count || 0),
    response_text: responseText,
    advice,
  };
  if (advice) response.evidence_ref = persistPiMappingAdvice(context.node_id, advice, context);
  const threadRef = persistPiMappingThread(context.node_id, payload, context, response);
  if (threadRef) response.thread_ref = threadRef;
  return response;
}

async function callPiGeneProfile(node, payload, runtime = {}) {
  const env = piProcessEnv();
  const status = piAgentStatus();
  const model = resolvePiModel(payload, env);
  if (status.status !== 'ready') {
    return {
      ok: false,
      status: status.status,
      reason: status.reason,
      requested_model: model.model,
      actual_model: '',
      model_resolution_status: 'unknown',
      model_comparison_reason: 'unknown',
    };
  }
  const context = payload && payload.gene_product_context && typeof payload.gene_product_context === 'object'
    ? payload.gene_product_context : {};
  const prompt = [
    '你正在执行流程3的单商品爆款基因提炼。',
    '只处理当前商品，不得引用或输出其它商品。',
    '上游产品类型、材质、功能、风格、场景、价格和数值指标都是事实，不得覆盖。',
    '仅规范化九维标签，并在文本证据明确时生成“人群”和“流量入口”未确认草稿；证据不足必须留空。',
    '视觉表达只能依据“主图元素”等文本证据；单独图片 URL 不是已完成视觉识别的证据。',
    '返回 JSON：schema_version=hot-product-gene-product-proposal-v1，row_id 必须与输入一致，包含 normalized_dimensions 和 derived_fields。',
    'derived_fields 每项必须包含 value、confidence、evidence_fields；evidence_fields 只能引用当前 source_row 中有值的字段。',
    JSON.stringify(context, null, 2),
  ].join('\n');
  const requestId = `gene-pi-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const args = [
    '--mode', 'rpc', '--no-session', '--no-tools', '--no-skills', '--no-context-files',
    '--no-prompt-templates', '--no-extensions',
  ];
  if (model.model) args.push('--model', model.model);
  const result = await runPiRpcOnce(piAgentBin(), args, {
    request_id: requestId,
    prompt,
    timeout_ms: Number(process.env.PI_RPC_TIMEOUT_MS || 120000),
    cwd: APP_ROOT,
    env,
    call_id: `${runtime.execution_id || requestId}:${runtime.row_id || ''}`,
    on_event: runtime.on_event,
  });
  const responseText = parsePiRpcText(result.stdout);
  const parsed = structuredPiAdvice(responseText);
  const rowMatches = parsed && String(parsed.row_id || '') === String(context.row_id || '');
  const valid = result.status === 0 && result.saw_agent_end && rowMatches && !result.cancelled;
  const reason = valid ? 'ready'
    : result.cancelled ? 'pi_cancelled'
      : result.timed_out ? 'pi_rpc_timeout'
        : result.error ? 'pi_spawn_failed'
          : !responseText ? 'pi_empty_response'
            : !result.saw_agent_end ? 'pi_incomplete_response'
              : !rowMatches ? 'invalid_proposal'
                : 'pi_rpc_failed';
  const actualModel = String(result.actual_model || '');
  const modelComparison = compareAgentModels(model.model, actualModel);
  return {
    ok: valid,
    status: valid ? 'ok' : 'error',
    reason,
    requested_model: model.model,
    actual_model: actualModel,
    model_resolution_status: modelComparison.status,
    model_comparison_reason: modelComparison.reason,
    duration_ms: Number(result.duration_ms || 0),
    response_text: responseText,
  };
}

function extractKnownParamsFromArtifacts(upstreamArtifacts) {
  const known = {};
  const labelMap = {
    '分析类目': 'category',
    '类目': 'category',
    '分析周期': 'period',
    '周期': 'period',
    '分析产品线': 'product_line',
    '产品线': 'product_line',
    '目标价格带': 'price_band',
    '价格带': 'price_band',
    '当前目标': 'goal',
  };
  const artifacts = Array.isArray(upstreamArtifacts) ? upstreamArtifacts : [];
  for (const item of artifacts) {
    const artifact = item && item.artifact && typeof item.artifact === 'object' ? item.artifact : item;
    const rows = Array.isArray(artifact && artifact.rows) ? artifact.rows : [];
    for (const row of rows) {
      const label = String(row.label || row.field_id || '').trim();
      const value = String(row.value || '').trim();
      if (!label || !value) continue;
      const key = labelMap[label] || labelMap[label.replace(/[：:]/g, '')];
      if (key && !known[key]) known[key] = value;
    }
    const fields = artifact && artifact.fields && typeof artifact.fields === 'object' ? artifact.fields : {};
    for (const [key, value] of Object.entries(fields)) {
      const normalized = labelMap[key] || key;
      if (normalized && value !== undefined && value !== null && String(value).trim() && !known[normalized]) {
        known[normalized] = String(value).trim();
      }
    }
  }
  return known;
}

function nodeById(config, nodeId) {
  const nodes = Array.isArray(config.nodes) ? config.nodes : [];
  return nodes.find(node => node && node.id === nodeId) || null;
}

function dbAgentTaskForNode(node, action) {
  const nodeName = String(node && (node.name || node.id) || '当前节点');
  const outputs = Array.isArray(node && node.output_model && node.output_model.outputs)
    ? node.output_model.outputs.map(output => output.title || output.id).filter(Boolean).join('、')
    : '';
  const requirements = Array.isArray(node && node.data_requirements) ? node.data_requirements.join('、') : '';
  if (requirements || outputs) {
    return `围绕节点「${nodeName}」的数据需求映射可用数仓 API、请求参数和响应字段；数据需求：${requirements || '未声明'}；产物：${outputs || '未声明'}`;
  }
  if (action === 'catalog') return `查询 ${nodeName} 需要的业务数据接口和取数方式`;
  return `为 ${nodeName} 选择可用数仓工具链、参数缺口和调用顺序`;
}

function nodeRequiredFields(node) {
  const outputFields = nodeOutputFieldRequirements(node);
  if (outputFields.length > 0) {
    return outputFields.map(item => String(item.field_name || item.title || '')).filter(Boolean);
  }
  const requiredData = Array.isArray(node && node.input_model && node.input_model.required_data)
    ? node.input_model.required_data
    : [];
  const fields = [];
  for (const item of requiredData) {
    const requiredFields = Array.isArray(item && item.required_fields) ? item.required_fields : [];
    for (const field of requiredFields) {
      const value = String(field || '').trim();
      if (value && !fields.includes(value)) fields.push(value);
    }
  }
  return fields;
}

function nodeOutputFieldRequirements(node) {
  const declared = Array.isArray(node && node.output_field_requirements) ? node.output_field_requirements : [];
  if (declared.length > 0) {
    return declared
      .filter(item => item && typeof item === 'object')
      .map(item => ({
        output_id: String(item.output_id || ''),
        field_path: String(item.field_path || item.field_name || ''),
        field_name: String(item.field_name || item.title || ''),
        title: String(item.title || item.field_name || ''),
        description: String(item.description || ''),
        type: String(item.type || 'unknown'),
        required: item.required !== false,
        source_schema_ref: String(item.source_schema_ref || ''),
        canonical_field_name: String(item.canonical_field_name || ''),
        source: String(item.source || 'output_field_requirements'),
        source_trace: item.source_trace && typeof item.source_trace === 'object' ? item.source_trace : {},
      }))
      .filter(item => item.field_name);
  }
  const outputs = Array.isArray(node && node.output_model && node.output_model.outputs) ? node.output_model.outputs : [];
  const requirements = [];
  for (const output of outputs) {
    if (!output || typeof output !== 'object') continue;
    const outputId = String(output.id || '');
    const schema = output.schema && typeof output.schema === 'object' ? output.schema : {};
    const appendProperties = (properties, required, prefix) => {
      for (const [name, propertySchema] of Object.entries(properties || {})) {
        const child = propertySchema && typeof propertySchema === 'object' ? propertySchema : {};
        requirements.push({
          output_id: outputId,
          field_path: `${prefix}.${name}`,
          field_name: String(name),
          title: String(child.title || name),
          description: String(child.description || child.desc || ''),
          type: String(child.type || 'unknown'),
          required: required.includes(String(name)),
          source_schema_ref: outputId ? `skill_snapshot/output_schemas/${outputId}.json` : 'app.config.json:output_model',
          source: 'derived_from_output_schema',
        });
      }
    };
    if (String(schema.type || '') === 'array') {
      const itemSchema = schema.items && typeof schema.items === 'object' ? schema.items : {};
      const properties = itemSchema.properties && typeof itemSchema.properties === 'object' ? itemSchema.properties : {};
      const required = Array.isArray(itemSchema.required) ? itemSchema.required.map(String) : [];
      appendProperties(properties, required, 'items.properties');
      continue;
    }
    const properties = schema.properties && typeof schema.properties === 'object' ? schema.properties : {};
    const required = Array.isArray(schema.required) ? schema.required.map(String) : [];
    appendProperties(properties, required, 'properties');
  }
  const granular = requirements.filter(item => !['rows', 'conclusions', 'evidence_ids'].includes(item.field_name));
  if (granular.length > 0) return requirements;
  const fields = [];
  const requiredData = Array.isArray(node && node.input_model && node.input_model.required_data) ? node.input_model.required_data : [];
  const fallbackOutputId = outputs[0] && outputs[0].id ? String(outputs[0].id) : 'node_output';
  for (const item of requiredData) {
    const requiredFields = Array.isArray(item && item.required_fields) ? item.required_fields : [];
    for (const field of requiredFields) {
      const fieldName = String(field || '').trim();
      if (!fieldName || fields.some(existing => existing.field_name === fieldName)) continue;
      fields.push({
        output_id: fallbackOutputId,
        field_path: `items.properties.${fieldName}`,
        field_name: fieldName,
        title: fieldName,
        description: String(item.description || ''),
        type: 'unknown',
        required: true,
        source_schema_ref: `app.config.json:nodes.${node.id}.input_model.required_data.${item.id || ''}.required_fields`,
        source: 'data_requirement_fallback',
      });
    }
  }
  return fields;
}

function dbAgentRequestForAction(action, node, payload, knownParams) {
  const task = String(payload.task || dbAgentTaskForNode(node, action));
  if (action === 'understand_input') {
    return {
      tool: 'select_tools_for_task',
      args: {
        task,
        known_params: knownParams,
      },
    };
  }
  if (action === 'catalog') {
    return {
      tool: 'ask_api_catalog',
      args: {
        question: String(payload.question || task),
        domain: payload.domain ? String(payload.domain) : undefined,
        limit: Number.isFinite(Number(payload.limit)) ? Number(payload.limit) : 8,
      },
    };
  }
  if (action === 'domain_apis') {
    return {
      tool: 'list_domain_apis',
      args: {
        domain: String(payload.domain || '商品域'),
        status: payload.status ? String(payload.status) : undefined,
        limit: Number.isFinite(Number(payload.limit)) ? Number(payload.limit) : 20,
      },
    };
  }
  if (action === 'asset_card') {
    return {
      tool: 'get_api_asset_card',
      args: { api_id: String(payload.api_id || '') },
    };
  }
  if (action === 'probe_sample') {
    return {
      tool: 'probe_api_sample',
      args: {
        api_id: String(payload.api_id || ''),
        params: payload.params && typeof payload.params === 'object' ? payload.params : knownParams,
        top: Number.isFinite(Number(payload.top)) ? Number(payload.top) : 2,
      },
    };
  }
  return {
    tool: 'select_tools_for_task',
    args: {
      task,
      known_params: knownParams,
    },
  };
}

function firstSourceApiFromToolPlan(toolPlan) {
  const tools = toolPlan && toolPlan.payload && Array.isArray(toolPlan.payload.recommended_tools)
    ? toolPlan.payload.recommended_tools
    : [];
  for (const tool of tools) {
    const sourceApis = Array.isArray(tool && tool.source_apis) ? tool.source_apis : [];
    const sourceApi = sourceApis.find(value => String(value || '').trim());
    if (sourceApi) return String(sourceApi).trim();
  }
  return '';
}

function outputTitlesForNode(node) {
  const outputs = Array.isArray(node && node.output_model && node.output_model.outputs)
    ? node.output_model.outputs
    : [];
  const titles = outputs.map(output => output && (output.title || output.id)).filter(Boolean);
  const legacy = Array.isArray(node && node.outputs) ? node.outputs : [];
  return [...new Set([...titles, ...legacy].map(value => String(value || '').trim()).filter(Boolean))];
}

function sourceContextRefsForNode(node) {
  const refs = [];
  if (node && node.node_execution_view) {
    refs.push({
      kind: 'node_execution_view',
      ref: `app.config.json:nodes.${node.id}.node_execution_view`,
      summary: String(node.node_execution_view.goal && node.node_execution_view.goal.markdown || node.node_execution_view.action && node.node_execution_view.action.markdown || '节点执行视图'),
    });
  }
  if (node && node.business_context) {
    refs.push({
      kind: 'business_context',
      ref: `app.config.json:nodes.${node.id}.business_context`,
      summary: String(node.business_context.query || node.business_context.status || '业务上下文'),
    });
  }
  const dataRefs = Array.isArray(node && node.input_model && node.input_model.required_data)
    ? node.input_model.required_data
    : [];
  for (const item of dataRefs) {
    refs.push({
      kind: 'data_requirement',
      ref: item && item.id ? `app.config.json:nodes.${node.id}.input_model.required_data.${item.id}` : `app.config.json:nodes.${node.id}.input_model.required_data`,
      summary: String(item && (item.description || item.title || item.id) || '数据需求'),
    });
  }
  if (refs.length === 0 && node) {
    refs.push({
      kind: 'workflow_node',
      ref: `app.config.json:nodes.${node.id}`,
      summary: String(node.name || node.id || '当前节点'),
    });
  }
  return refs;
}

function businessRequirementForNode(node) {
  const view = node && node.node_execution_view ? node.node_execution_view : {};
  const goalText = String(view.goal && (view.goal.markdown || view.goal.summary) || '');
  const actionText = String(view.action && (view.action.markdown || view.action.summary) || '');
  const contextResults = Array.isArray(node && node.business_context && node.business_context.results)
    ? node.business_context.results
    : [];
  const sourceText = contextResults.map(item => item && (item.text || item.content || item.snippet)).filter(Boolean).join('\n\n');
  return {
    title: String(node && (node.name || node.id) || '当前节点'),
    description: actionText || goalText || dbAgentTaskForNode(node, 'tool_plan'),
    required_outputs: outputTitlesForNode(node),
    required_fields: nodeRequiredFields(node),
    source_text: sourceText,
  };
}

function candidateApisFromToolPlan(toolPlan) {
  const payload = toolPlan && toolPlan.payload ? toolPlan.payload : toolPlan;
  const tools = Array.isArray(payload && payload.recommended_tools) ? payload.recommended_tools : [];
  const apis = [];
  for (const tool of tools) {
    const sourceApis = Array.isArray(tool && tool.source_apis) ? tool.source_apis : [];
    for (const apiId of sourceApis) {
      const value = String(apiId || '').trim();
      if (!value || apis.some(item => item.api_id === value)) continue;
      apis.push({
        api_id: value,
        name: String(tool.tool_id || value),
        domain: '',
        capability: '',
        quality_score: tool.quality_score,
        missing_params: Array.isArray(tool.missing_params) ? tool.missing_params : [],
        risks: Array.isArray(tool.risks) ? tool.risks : [],
      });
    }
  }
  return apis;
}

function requestParamMappingFromPayload(payload) {
  const params = Array.isArray(payload && payload.request_params) ? payload.request_params : [];
  return params.map(param => ({
    business_param: String(param.desc || param.name || ''),
    api_param: String(param.name || ''),
    value: String(param.known_value || ''),
    source: param.known_value ? 'upstream_artifact_or_known_params' : '',
    status: String(param.status || (param.required ? 'missing' : 'optional_or_unknown')),
  }));
}

function responseFieldMappingFromPayload(payload) {
  const matches = Array.isArray(payload && payload.field_matches) ? payload.field_matches : [];
  const selectedApi = selectedApiFromPayload(payload);
  return matches.map(item => ({
    business_field: String(item.required_field || ''),
    api_field_path: item.api_field ? String(item.api_field.path || '') : '',
    api_field_name: item.api_field ? String(item.api_field.name || '') : '',
    api_field_type: item.api_field ? String(item.api_field.type || '') : '',
    source_api_id: String(item.source_api_id || selectedApi.api_id || ''),
    source_api_name: String(item.source_api_name || selectedApi.name || ''),
    source_field_path: item.api_field ? String(item.api_field.path || '') : '',
    source_role: String(item.source_role || (selectedApi.api_id ? 'api_field' : '')),
    confidence: Number.isFinite(Number(item.score)) ? Number(item.score) : 0,
    status: String(item.status || 'unmatched'),
    match_basis: String(item.match_basis || ''),
  }));
}

function responseFieldMappingFromManual(mapping) {
  const items = Array.isArray(mapping) ? mapping : [];
  return items
    .filter(item => item && typeof item === 'object')
    .map(item => ({
      output_id: String(item.output_id || ''),
      field_path: String(item.field_path || ''),
      business_field: String(item.business_field || item.field_name || item.title || ''),
      api_field_path: String(item.api_field_path || ''),
      api_field_name: String(item.api_field_name || ''),
      api_field_type: String(item.api_field_type || item.type || ''),
      source_api_id: String(item.source_api_id || item.api_id || ''),
      source_api_name: String(item.source_api_name || item.api_name || ''),
      source_field_path: String(item.source_field_path || item.api_field_path || ''),
      source_role: String(item.source_role || (item.api_field_path ? 'api_field' : '')),
      confidence: Number.isFinite(Number(item.confidence)) ? Number(item.confidence) : 1,
      status: String(item.status || (item.api_field_path ? 'mapped' : 'unmapped')),
      match_basis: String(item.match_basis || 'human_selected'),
      human_note: String(item.human_note || item.note || ''),
    }))
    .filter(item => item.business_field);
}

function outputFieldMappingOverlay(node, manualMapping) {
  const manual = responseFieldMappingFromManual(manualMapping);
  const manualByField = new Map(manual.map(item => [item.field_path || item.business_field, item]));
  return nodeOutputFieldRequirements(node).map(field => {
    const mapped = manualByField.get(field.field_path) || manualByField.get(field.field_name) || null;
    return {
      ...field,
      mapping_status: mapped && mapped.api_field_path ? String(mapped.status || 'mapped') : 'unmapped',
      api_field_path: mapped ? mapped.api_field_path : '',
      api_field_name: mapped ? mapped.api_field_name : '',
      api_field_type: mapped ? mapped.api_field_type : '',
      source_api_id: mapped ? mapped.source_api_id : '',
      source_api_name: mapped ? mapped.source_api_name : '',
      source_field_path: mapped ? mapped.source_field_path || mapped.api_field_path : '',
      source_role: mapped ? mapped.source_role || (mapped.api_field_path ? 'api_field' : '') : '',
      confidence: mapped ? mapped.confidence : 0,
      human_note: mapped ? mapped.human_note : '',
      human_confirmed: Boolean(mapped && (mapped.human_confirmed || mapped.status === 'confirmed')),
      confirmed: Boolean(mapped && (mapped.human_confirmed || mapped.status === 'confirmed')),
    };
  });
}

function apiFieldsFromAssetCard(card) {
  const responseFields = card && card.response_schema && Array.isArray(card.response_schema.fields)
    ? card.response_schema.fields
    : [];
  return responseFields.map(field => ({
    path: String(field.path || field.name || ''),
    name: String(field.name || ''),
    type: String(field.type || 'unknown'),
    desc: String(field.desc || field.description || ''),
  }));
}

function requestParamsFromAssetCard(card) {
  const query = card && card.request_schema && Array.isArray(card.request_schema.query)
    ? card.request_schema.query
    : [];
  return query.map(param => ({
    name: String(param.name || ''),
    type: String(param.type || 'unknown'),
    required: Boolean(param.required),
    desc: String(param.desc || param.description || ''),
  }));
}

function buildAssetCardPayload(node, assetCardResponse) {
  const card = assetCardResponse && assetCardResponse.payload && assetCardResponse.payload.card
    ? assetCardResponse.payload.card
    : assetCardResponse && assetCardResponse.card;
  const selectedApi = card ? {
    api_id: String(card.api_id || ''),
    name: String(card.name || ''),
    method: String(card.method || ''),
    path: String(card.path || ''),
    domain: String(card.domain || ''),
    capability: String(card.capability || ''),
    quality_score: card.quality_score,
  } : {};
  return {
    selected_api: selectedApi,
    api_request_params: requestParamsFromAssetCard(card),
    api_response_fields: apiFieldsFromAssetCard(card),
    output_field_requirements: nodeOutputFieldRequirements(node),
    selected_api_asset_card: card || {},
    lineage_text: assetCardResponse && assetCardResponse.payload ? assetCardResponse.payload.lineage_text : assetCardResponse && assetCardResponse.lineage_text || '',
  };
}

function selectedApiFromPayload(payload) {
  const selected = payload && payload.selected_api && typeof payload.selected_api === 'object' ? payload.selected_api : {};
  return {
    api_id: String(selected.api_id || ''),
    name: String(selected.name || ''),
    method: String(selected.method || ''),
    path: String(selected.path || ''),
    domain: String(selected.domain || ''),
    capability: String(selected.capability || ''),
    quality_score: selected.quality_score,
  };
}

function normalizeApiSummary(api) {
  const item = api && typeof api === 'object' ? api : { api_id: api };
  return {
    api_id: String(item.api_id || item.id || ''),
    name: String(item.name || item.title || item.tool_id || item.api_id || ''),
    method: String(item.method || ''),
    path: String(item.path || item.api_id || ''),
    domain: String(item.domain || ''),
    capability: String(item.capability || ''),
    quality_score: item.quality_score,
  };
}

function selectedApisForContract(payload, selectedApi, options = {}) {
  const seen = new Set();
  const apis = [];
  const append = api => {
    const normalized = normalizeApiSummary(api);
    if (!normalized.api_id || seen.has(normalized.api_id)) return;
    seen.add(normalized.api_id);
    apis.push(normalized);
  };
  if (Array.isArray(options.selectedApis)) options.selectedApis.forEach(append);
  if (Array.isArray(payload && payload.selected_apis)) payload.selected_apis.forEach(append);
  if (selectedApi && selectedApi.api_id) append(selectedApi);
  if (Array.isArray(payload && payload.candidate_apis)) payload.candidate_apis.forEach(append);
  return apis;
}

function coveragePlanFromMappings(node, mappings, options = {}) {
  const fields = nodeOutputFieldRequirements(node);
  const byPath = new Map();
  const byName = new Map();
  for (const mapping of Array.isArray(mappings) ? mappings : []) {
    if (!mapping || typeof mapping !== 'object') continue;
    const pathKey = String(mapping.field_path || '').trim();
    const nameKey = String(mapping.business_field || mapping.field_name || mapping.title || '').trim();
    if (pathKey) byPath.set(pathKey, mapping);
    if (nameKey) byName.set(nameKey, mapping);
  }
  return fields.map(field => {
    const mapped = byPath.get(field.field_path) || byName.get(field.field_name) || byName.get(field.title) || null;
    const protectedSemanticField = PROTECTED_SEMANTIC_FIELD_NAMES.has(String(field.field_name || field.title || ''));
    const apiFieldPath = protectedSemanticField ? '' : String(mapped && (mapped.api_field_path || mapped.source_field_path) || '');
    const status = protectedSemanticField
      ? 'derived_or_manual_required'
      : String(mapped && (mapped.mapping_status || mapped.status) || (apiFieldPath ? 'mapped' : 'missing'));
    const mappedBusinessFieldName = String(mapped && (mapped.business_field || mapped.field_name || mapped.title) || '').trim();
    return {
      output_id: field.output_id,
      field_path: field.field_path,
      field_name: mappedBusinessFieldName || field.field_name,
      title: mappedBusinessFieldName || field.title,
      description: field.description,
      type: field.type,
      required: field.required !== false,
      source_schema_ref: field.source_schema_ref,
      canonical_field_name: field.canonical_field_name || '',
      source: field.source || '',
      source_trace: field.source_trace || {},
      source_api_id: protectedSemanticField ? '' : String(mapped && (mapped.source_api_id || mapped.api_id) || ''),
      source_api_name: protectedSemanticField ? '' : String(mapped && (mapped.source_api_name || mapped.api_name) || ''),
      source_field_path: apiFieldPath,
      api_field_path: apiFieldPath,
      api_field_name: String(mapped && mapped.api_field_name || ''),
      api_field_type: String(mapped && mapped.api_field_type || ''),
      source_role: protectedSemanticField ? 'derived' : String(mapped && mapped.source_role || (apiFieldPath ? 'api_field' : '')),
      source_kind: protectedSemanticField ? 'pi_derived' : String(mapped && mapped.source_kind || (apiFieldPath ? 'api_doc_index' : '')),
      mapping_status: status,
      confidence: mapped && Number.isFinite(Number(mapped.confidence)) ? Number(mapped.confidence) : (apiFieldPath ? 1 : 0),
      human_confirmed: Boolean(mapped && (mapped.human_confirmed || mapped.confirmed || status === 'confirmed')),
      human_note: String(mapped && (mapped.human_note || mapped.note) || ''),
      match_basis: String(mapped && mapped.match_basis || ''),
      missing_reason: String(mapped && mapped.missing_reason || ''),
      candidate_field_options: protectedSemanticField ? [] : Array.isArray(mapped && mapped.candidate_field_options) ? mapped.candidate_field_options : Array.isArray(mapped && mapped.candidates) ? mapped.candidates : [],
      evidence_field_paths: Array.isArray(mapped && mapped.evidence_field_paths) ? mapped.evidence_field_paths.map(String) : [],
    };
  });
}

function coverageSummary(fieldCoveragePlan) {
  const fields = Array.isArray(fieldCoveragePlan) ? fieldCoveragePlan : [];
  const isMapped = item => ['matched', 'mapped', 'suggested', 'confirmed', 'manual_fill', 'derived', 'derived_or_manual_required'].includes(String(item.mapping_status || item.status || ''));
  return {
    total: fields.length,
    mapped: fields.filter(isMapped).length,
    confirmed: fields.filter(item => item.human_confirmed || String(item.mapping_status || item.status || '') === 'confirmed').length,
    missing_required: fields.filter(item => item.required !== false && !isMapped(item)).length,
    needs_human_confirmation: fields.filter(item => isMapped(item) && !(item.human_confirmed || String(item.mapping_status || item.status || '') === 'confirmed')).length,
    derived_or_manual_required: fields.filter(item => String(item.mapping_status || item.status || '') === 'derived_or_manual_required').length,
  };
}

function defaultJoinPlan(selectedApis, payload, options = {}) {
  const provided = options.joinPlan || payload && payload.join_plan;
  if (provided && typeof provided === 'object') {
    return {
      primary_api_id: String(provided.primary_api_id || ''),
      join_keys: Array.isArray(provided.join_keys) ? provided.join_keys : [],
      grain: String(provided.grain || 'unknown'),
      time_window: String(provided.time_window || ''),
      risks: Array.isArray(provided.risks) ? provided.risks.map(String) : [],
    };
  }
  const primaryApi = selectedApis.find(api => api.api_id) || {};
  const risks = selectedApis.length > 1
    ? ['多个 API 共同覆盖字段，可在高级口径区补充合并键、数据粒度和时间口径。']
    : ['单 API 覆盖时仍需人工确认字段口径。'];
  return {
    primary_api_id: String(primaryApi.api_id || ''),
    join_keys: [],
    grain: 'unknown',
    time_window: '',
    risks,
  };
}

function buildDataMappingContract(node, knownParams, options = {}) {
  const payload = options.payload && typeof options.payload === 'object' ? options.payload : {};
  const toolPlan = options.toolPlan || payload.tool_plan || null;
  const evidenceRefs = Array.isArray(options.evidenceRefs) ? options.evidenceRefs.filter(Boolean) : [];
  const status = options.status || 'draft';
  const selectedApi = options.selectedApi || selectedApiFromPayload(payload);
  const candidateApis = Array.isArray(options.candidateApis)
    ? options.candidateApis
    : candidateApisFromToolPlan(toolPlan);
  const manualMappings = responseFieldMappingFromManual(options.manualResponseFieldMapping || payload.manual_response_field_mapping);
  const responseMappings = manualMappings.length > 0 ? manualMappings : responseFieldMappingFromPayload(payload);
  const selectedApis = selectedApisForContract(payload, selectedApi, options);
  const fieldCoveragePlan = Array.isArray(options.fieldCoveragePlan)
    ? coveragePlanFromMappings(node, options.fieldCoveragePlan, options)
    : Array.isArray(payload.field_coverage_plan)
      ? coveragePlanFromMappings(node, payload.field_coverage_plan, options)
      : coveragePlanFromMappings(node, responseMappings, options);
  const summary = coverageSummary(fieldCoveragePlan);
  const apiMatchingStrategyResults = options.apiMatchingStrategyResults || payload.strategy_results || payload.api_matching_strategy_results || {};
  const businessFieldCoverageMetrics = options.businessFieldCoverageMetrics
    || payload.business_field_coverage_metrics
    || (payload.field_mapping && typeof payload.field_mapping === 'object' ? {
      business_field_coverage_score: payload.field_mapping.business_field_coverage_score,
      required_total: payload.field_mapping.required_total,
      covered_required: payload.field_mapping.covered_required,
      high_confidence: payload.field_mapping.high_confidence,
      confirmed_or_reviewable: payload.field_mapping.confirmed_or_reviewable,
      missing_required_fields: payload.field_mapping.missing_required_fields,
    } : {});
  const derivedFieldPlan = Array.isArray(options.derivedFieldPlan)
    ? options.derivedFieldPlan
    : Array.isArray(payload.derived_field_plan)
      ? payload.derived_field_plan
      : derivedFieldPlanFromCoverage(fieldCoveragePlan);
  const unmatched = Array.isArray(options.unmatchedFields)
    ? options.unmatchedFields
    : Array.isArray(payload.unmatched_required_fields)
      ? payload.unmatched_required_fields
      : fieldCoveragePlan
        .filter(item => item.required !== false && !['matched', 'mapped', 'suggested', 'confirmed', 'manual_fill', 'derived', 'derived_or_manual_required'].includes(item.mapping_status))
        .map(item => item.field_name);
  return {
    schema_version: 'data-mapping-contract-v2',
    node_id: String(node && node.id || ''),
    business_requirement: businessRequirementForNode(node),
    source_context_refs: sourceContextRefsForNode(node),
    known_params: knownParams || {},
    candidate_apis: candidateApis,
    api_matching_strategy_results: apiMatchingStrategyResults,
    business_field_coverage_metrics: businessFieldCoverageMetrics,
    selected_api: selectedApi,
    selected_apis: selectedApis,
    selected_api_asset_card: options.selectedApiAssetCard || payload.selected_api_asset_card || {},
    selected_api_asset_cards: Array.isArray(options.selectedApiAssetCards)
      ? options.selectedApiAssetCards
      : Array.isArray(payload.selected_api_asset_cards)
        ? payload.selected_api_asset_cards
        : [],
    api_response_field_catalog: Array.isArray(options.apiResponseFieldCatalog)
      ? options.apiResponseFieldCatalog
      : Array.isArray(payload.api_response_field_catalog)
        ? payload.api_response_field_catalog
        : [],
    output_field_requirements: nodeOutputFieldRequirements(node),
    output_field_mapping_overlay: fieldCoveragePlan,
    field_coverage_plan: fieldCoveragePlan,
    derived_field_plan: derivedFieldPlan,
    join_plan: defaultJoinPlan(selectedApis, payload, options),
    coverage_summary: summary,
    request_param_mapping: requestParamMappingFromPayload(payload),
    response_field_mapping: responseMappings,
    manual_response_field_mapping: manualMappings,
    unmatched_fields: unmatched,
    human_decisions: Array.isArray(options.humanDecisions) ? options.humanDecisions : [],
    evidence_refs: evidenceRefs,
    status,
  };
}

function normalizeFieldText(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/[_\-./]+/g, ' ')
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

const PROTECTED_SEMANTIC_FIELD_NAMES = new Set(['root_terms', 'demand_type', '词根', '需求类型']);
const DERIVED_FIELD_NAMES = new Set([
  '功能', 'function', '风格', 'style', '主图元素', 'main_image_elements', '爆款原因', 'hot_sale_reason',
  ...PROTECTED_SEMANTIC_FIELD_NAMES,
]);

function localApiEntryToCard(entry) {
  const requestParams = Array.isArray(entry.request_params) ? entry.request_params : [];
  const responseFields = Array.isArray(entry.response_fields) ? entry.response_fields : [];
  return {
    api_id: String(entry.api_id || ''),
    name: String(entry.name || entry.api_id || ''),
    method: String(entry.method || ''),
    path: String(entry.path || ''),
    domain: String(entry.analysis_domain || ''),
    capability: String(entry.business_module || entry.module || ''),
    quality_score: entry.verified_status === 'success' ? 1 : 0.6,
    request_schema: {
      query: requestParams.map(param => ({
        name: String(param.name || ''),
        type: String(param.type || 'unknown'),
        required: Boolean(param.required),
        desc: String(param.description || ''),
      })),
    },
    response_schema: {
      root: 'response',
      fields: responseFields.map(field => ({
        path: String(field.path || field.name || ''),
        name: String(field.name || ''),
        type: String(field.type || 'unknown'),
        desc: String(field.description || ''),
      })),
    },
    source_refs: entry.source_refs || {},
  };
}

function localAssetCardPayload(node, apiId) {
  const entry = localApiEntryForId(apiId);
  const card = entry ? localApiEntryToCard(entry) : null;
  return {
    selected_api: card ? normalizeApiSummary(card) : { api_id: String(apiId || ''), found: false },
    api_request_params: requestParamsFromAssetCard(card),
    api_response_fields: apiFieldsFromAssetCard(card),
    output_field_requirements: nodeOutputFieldRequirements(node),
    selected_api_asset_card: card || {},
    lineage_text: card ? `api_doc_index:${card.api_id}` : '',
  };
}

function matcherPayloadForNode(node, knownParams, payload = {}) {
  const service = callBusinessContextMatcher(node, knownParams, payload);
  if (service.degraded) return service;
  const assets = Array.isArray(service.selected_api_assets) ? service.selected_api_assets : [];
  const selectedApis = assets.map(normalizeApiSummary).filter(api => api.api_id);
  const missingRequired = (Array.isArray(service.field_coverage_plan) ? service.field_coverage_plan : [])
    .filter(item => item && item.required !== false && String(item.mapping_status || '') === 'missing')
    .map(item => String(item.field_name || item.title || ''))
    .filter(Boolean);
  const recommendedTools = selectedApis.map((api, index) => {
    const asset = assets[index] || {};
    const requiredParams = Array.isArray(asset.request_schema && asset.request_schema.query)
      ? asset.request_schema.query.filter(param => param && param.required).map(param => String(param.name || '')).filter(Boolean)
      : [];
    return {
      tool_id: `api_doc_index.${api.api_id}`,
      call_order: index + 1,
      reason: 'api_doc_matcher business-context field coverage match',
      required_params: requiredParams,
      missing_params: requiredParams,
      source_apis: [api.api_id],
      quality_score: api.quality_score,
      risks: Array.isArray(asset.parse_warnings) ? asset.parse_warnings.map(String) : [],
    };
  });
  return {
    provider: 'api_doc_index',
    task: String(payload.task || dbAgentTaskForNode(node, 'tool_plan')),
    business_input: knownParams,
    business_context: service.business_context || matcherBusinessContextForNode(node),
    strategy_results: service.strategy_results || {},
    strategy_field_mappings: service.strategy_field_mappings || {},
    field_mapping: service.field_mapping || {},
    api_matching_strategy_results: service.strategy_results || {},
    business_field_coverage_metrics: service.business_field_coverage_metrics || {},
    recommended_tools: recommendedTools,
    candidate_apis: Array.isArray(service.candidate_apis) ? service.candidate_apis : [],
    selected_api_ids: Array.isArray(service.selected_api_ids) ? service.selected_api_ids : selectedApis.map(api => api.api_id),
    selected_api: selectedApis[0] || {},
    selected_apis: selectedApis,
    selected_api_asset_cards: assets,
    selected_api_assets: assets,
    api_response_field_catalog: Array.isArray(service.api_response_field_catalog) ? service.api_response_field_catalog : [],
    output_field_requirements: nodeOutputFieldRequirements(node),
    field_coverage_plan: Array.isArray(service.field_coverage_plan) ? service.field_coverage_plan : [],
    derived_field_plan: Array.isArray(service.derived_field_plan) ? service.derived_field_plan : [],
    missing_or_derived_fields: Array.isArray(service.missing_or_derived_fields) ? service.missing_or_derived_fields : [],
    unmatched_required_fields: missingRequired,
    coverage_summary: service.coverage_summary || {},
    business_field_coverage_score: service.business_field_coverage_score || 0,
    next_question: missingRequired.length > 0
      ? '仍有必填字段未覆盖；请交由右侧 Agent 分析缺口或补充 API 文档索引。'
      : '请在中间工作区审核字段来源，并确认映射合同。',
  };
}

function matcherUnavailableResponse(node, nodeId, action, knownParams, status, matcherResult) {
  return {
    ok: false,
    status: 'degraded',
    reason: 'matcher_service_unavailable',
    matcher_reason: matcherResult && matcherResult.matcher_reason || matcherResult && matcherResult.reason || '',
    matcher_error: matcherResult && matcherResult.matcher_error || '',
    provider: 'api_doc_index',
    node_id: nodeId,
    action,
    known_params: knownParams,
    next_step: '请先修复 api_doc_matcher.service 或 API 文档索引；系统不会用前端/JS fallback 生成空覆盖方案。',
    data_mapping_contract: buildDataMappingContract(node, knownParams, { status: 'degraded' }),
    db_agent_status: status,
  };
}

function derivedFieldPlanFromCoverage(fieldCoveragePlan) {
  const fields = Array.isArray(fieldCoveragePlan) ? fieldCoveragePlan : [];
  return fields
    .filter(item => String(item.mapping_status || item.status || '') === 'derived_or_manual_required' || DERIVED_FIELD_NAMES.has(String(item.field_name || '')))
    .map(item => ({
      field_path: String(item.field_path || ''),
      field_name: String(item.field_name || ''),
      title: String(item.title || item.field_name || ''),
      description: String(item.description || ''),
      status: 'needs_agent_or_manual_analysis',
      source_kind: 'pi_derived',
      required_inputs: ['confirmed_api_field_mapping', 'upstream_artifacts_or_sample_rows'],
      available_evidence_fields: Array.isArray(item.evidence_field_paths) ? item.evidence_field_paths.map(String) : [],
      evidence_field_paths: Array.isArray(item.evidence_field_paths) ? item.evidence_field_paths.map(String) : [],
      suggested_analysis: '基于已确认 API 字段、商品图片/卖点/标题等证据，由 Agent 进行即席分析并生成草稿，人工确认后才进入产物。',
      risks: ['不能由单个数仓 API 原生字段稳定提供，不得自动当作事实。'],
    }));
}

function callDbAgentWorker(request) {
  const specPackRoot = dbAgentSpecPackRoot();
  const loaderPath = path.join(specPackRoot, 'scripts', 'ts_loader.mjs');
  const result = spawnSync(process.execPath, ['--import', loaderPath, DB_AGENT_WORKER], {
    cwd: specPackRoot || APP_ROOT,
    input: JSON.stringify({ ...request, spec_pack_root: specPackRoot }),
    encoding: 'utf-8',
    timeout: request && request.tool === 'probe_api_batch' ? 120000 : 15000,
    maxBuffer: request && request.tool === 'probe_api_batch' ? 16 * 1024 * 1024 : 4 * 1024 * 1024,
    env: {
      ...process.env,
      DB_ARCHAEOLOGIST_SPEC_PACK: specPackRoot,
      LIVE_PROBE: process.env.DBA_LIVE_PROBE === '1' ? 'true' : process.env.LIVE_PROBE,
      REGISTRY_ROOT: specPackRoot,
      SPEC_PACK_ROOT: specPackRoot,
    },
  });
  if (result.error) {
    return { ok: false, status: 'error', reason: 'spawn_failed', error: result.error.message };
  }
  const stdout = String(result.stdout || '').trim();
  let parsed = null;
  try {
    parsed = stdout ? JSON.parse(stdout.split(/\r?\n/).filter(Boolean).pop()) : null;
  } catch (error) {
    return { ok: false, status: 'error', reason: 'bad_worker_json', error: error.message, stdout, stderr: result.stderr || '' };
  }
  if (result.status !== 0 && parsed && parsed.ok !== false) {
    return { ok: false, status: 'error', reason: 'worker_failed', exit_code: result.status, payload: parsed, stderr: result.stderr || '' };
  }
  return parsed || { ok: false, status: 'error', reason: 'empty_worker_output', stderr: result.stderr || '' };
}

function rowsFromProbePayload(payload) {
  if (!payload || typeof payload !== 'object') return [];
  const candidates = [
    payload.response && typeof payload.response === 'object' ? payload.response : null,
    payload.response && payload.response.response && typeof payload.response.response === 'object' ? payload.response.response : null,
    payload,
  ].filter(Boolean);
  for (const candidate of candidates) {
    if (candidate.data && Array.isArray(candidate.data.result)) return candidate.data.result;
    if (candidate.data && Array.isArray(candidate.data.rows)) return candidate.data.rows;
    if (candidate.data && Array.isArray(candidate.data.items)) return candidate.data.items;
    if (candidate.data && Array.isArray(candidate.data.list)) return candidate.data.list;
    if (Array.isArray(candidate.result)) return candidate.result;
    if (Array.isArray(candidate.rows)) return candidate.rows;
    if (Array.isArray(candidate.items)) return candidate.items;
    if (Array.isArray(candidate.top)) {
      if (candidate.top.length === 1 && candidate.top[0] && typeof candidate.top[0] === 'object' && Array.isArray(candidate.top[0].result)) {
        return candidate.top[0].result;
      }
      return candidate.top;
    }
  }
  return [];
}

function safeEvidenceToken(value) {
  const token = String(value || '')
    .replace(/^https?:\/\//, '')
    .replace(/[^A-Za-z0-9_-]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 80);
  return token || 'unknown';
}

function redactedUrlForDisplay(rawUrl) {
  const input = String(rawUrl || '');
  if (!input) return '';
  try {
    const parsed = new URL(input);
    const sensitiveKeys = new Set([
      'userid',
      'user_id',
      'tenantid',
      'tenant_id',
      'appcode',
      'app_code',
      'appcodekey',
      'app_code_key',
      'appkey',
      'app_key',
      'token',
      'access_token',
      'authorization',
      'x-ca-key',
      'x-ca-signature',
    ]);
    for (const key of Array.from(parsed.searchParams.keys())) {
      if (sensitiveKeys.has(key.toLowerCase())) parsed.searchParams.set(key, '[REDACTED]');
    }
    return parsed.toString();
  } catch {
    return input.replace(/(userId|tenantId|appCode(?:Key)?|app_code_key|appKey|app_key|token|access_token)=([^&]+)/gi, '$1=[REDACTED]');
  }
}

function redactedObjectForDisplay(value) {
  if (!value || typeof value !== 'object') return value === undefined ? null : value;
  const sensitive = /token|secret|password|authorization|app[_-]?code(?:[_-]?key)?|appcodekey|app[_-]?key|x-ca|user[_-]?id|tenant[_-]?id/i;
  if (Array.isArray(value)) return value.map(item => redactedObjectForDisplay(item));
  const declaredKey = String(value.name || value.key || value.param || value.parameter || '');
  const redactDeclaredValue = sensitive.test(declaredKey);
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [
    key,
    sensitive.test(key) || (redactDeclaredValue && ['value', 'default', 'resolved_value'].includes(key.toLowerCase()))
      ? '[REDACTED]'
      : redactedObjectForDisplay(item),
  ]));
}

function requestDebugFromProbePayload(payload) {
  const request = payload && typeof payload === 'object' && payload.request && typeof payload.request === 'object'
    ? payload.request
    : {};
  return {
    url: redactedUrlForDisplay(request.url || ''),
    query: redactedObjectForDisplay(request.query || {}),
    body: redactedObjectForDisplay(request.body || null),
    headers_keys: Array.isArray(request.headers_keys) ? request.headers_keys : [],
    auth_inject: redactedObjectForDisplay(request.auth_inject || {}),
  };
}

function dbAgentWorkerResponseForEvidence(workerResponse) {
  const sanitized = redactedObjectForDisplay(workerResponse && typeof workerResponse === 'object' ? workerResponse : {});
  const originalPayload = workerResponse && workerResponse.payload && typeof workerResponse.payload === 'object'
    ? workerResponse.payload
    : null;
  if (sanitized && sanitized.payload && originalPayload && originalPayload.request) {
    sanitized.payload.request = requestDebugFromProbePayload(originalPayload);
  }
  return sanitized;
}

function fieldPathLooksLikeCategoryName(field) {
  const text = `${field && (field.path || field.name || '') || ''} ${field && (field.description || field.desc || '') || ''}`.toLowerCase();
  return /category_name|cate_name|类目名称|品类名称/.test(text);
}

function fieldPathLooksLikeCategoryId(field) {
  const text = `${field && (field.path || field.name || '') || ''} ${field && (field.description || field.desc || '') || ''}`.toLowerCase();
  return /(^|[.\s_])cid($|[.\s_])|category_id|cate_id|cat_id|类目\s*id/i.test(text);
}

function apiEntryNeedsCategoryId(entry) {
  return (Array.isArray(entry && entry.request_params) ? entry.request_params : []).some(param => categoryParamRole(param.name, param.description) === 'category_id' && param.required);
}

function categoryResolverCandidates() {
  return localApiEntries().map(entry => {
    const fields = Array.isArray(entry.response_fields) ? entry.response_fields : [];
    const nameField = fields.find(fieldPathLooksLikeCategoryName);
    const idField = fields.find(fieldPathLooksLikeCategoryId);
    if (!nameField || !idField) return null;
    if (apiEntryNeedsCategoryId(entry)) return null;
    return {
      api_id: String(entry.api_id || ''),
      api_name: String(entry.name || entry.api_id || ''),
      name_field_path: String(nameField.path || nameField.name || ''),
      id_field_path: String(idField.path || idField.name || ''),
    };
  }).filter(Boolean);
}

function normalizeCategoryText(value) {
  return String(value || '').toLowerCase().replace(/\s+/g, '').trim();
}

function resolveCategoryIdForPlan(node, plan, knownParams, topN, dbStatus) {
  const resolution = plan.category_resolution && typeof plan.category_resolution === 'object' ? { ...plan.category_resolution } : {};
  resolution.schema_version = 'category-resolution-v1';
  resolution.direction = resolution.direction || 'name_to_id';
  if (resolution.category_id || !resolution.category_name) {
    return {
      resolved: Boolean(resolution.category_id),
      resolution: {
        ...resolution,
        status: resolution.category_id ? 'resolved' : resolution.status || 'needs_input',
        direction: resolution.category_id ? 'direct' : resolution.direction,
      },
      api_call: null,
    };
  }
  if (process.env.DBA_LIVE_PROBE !== '1' || dbStatus.status !== 'ok' || dbStatus.provider === 'api_doc_index') {
    resolution.status = 'needs_input';
    resolution.blocked_reason = 'category_id_required';
    resolution.resolver_provider = hasLocalApiDocIndex() ? 'api_doc_matcher' : '';
    return { resolved: false, resolution, api_call: null };
  }
  const discovery = callCategoryResolverDiscovery(knownParams, {
    category_name: resolution.category_name,
    direction: 'name_to_id',
    top: topN,
  });
  const candidates = !discovery.degraded && Array.isArray(discovery.candidates) && discovery.candidates.length > 0
    ? discovery.candidates.map(candidate => ({
      api_id: String(candidate.api_id || ''),
      api_name: String(candidate.api_name || candidate.api_id || ''),
      name_field_path: String(candidate.name_field_path || ''),
      id_field_path: String(candidate.id_field_path || ''),
      resolver_provider: discovery.provider || 'api_doc_matcher',
      discovery_score: candidate.score,
      request_binding: candidate.request_binding || {},
    }))
    : categoryResolverCandidates().map(candidate => ({ ...candidate, resolver_provider: 'server_fallback' }));
  if (candidates.length === 0) {
    resolution.status = 'blocked';
    resolution.blocked_reason = discovery.degraded ? 'resolver_discovery_failed' : 'resolver_not_found';
    resolution.resolver_provider = discovery.provider || 'api_doc_matcher';
    resolution.discovery_error = discovery.matcher_error || discovery.matcher_reason || discovery.reason || '';
    return { resolved: false, resolution, api_call: null };
  }
  let attemptedResolver = false;
  let successfulResolverProbe = false;
  let failedResolverProbe = false;
  const resolverCalls = [];
  for (const candidate of candidates) {
    const binding = callRequestParamBinder(candidate.api_id, knownParams, { top: topN });
    if (binding.degraded || (Array.isArray(binding.missing_required_params) && binding.missing_required_params.length > 0)) continue;
    attemptedResolver = true;
    const request = dbAgentRequestForAction('probe_sample', node, { api_id: candidate.api_id, params: binding.params || {}, top: Math.min(300, Math.max(50, topN)) }, knownParams);
    const workerResponse = callDbAgentWorker(request);
    const evidenceRef = persistDbAgentEvidence(node.id, 'category_resolution', workerResponse, knownParams, { apiId: candidate.api_id });
    const rows = rowsFromProbePayload(workerResponse && workerResponse.payload);
    const target = normalizeCategoryText(resolution.category_name);
    const namedRows = rows
      .map(row => ({ row, category_name: normalizeCategoryText(valueAtSourcePath(row, candidate.name_field_path)) }))
      .filter(item => item.category_name);
    const matchedItem = namedRows.find(item => item.category_name === target)
      || namedRows.find(item => item.category_name.includes(target) || target.includes(item.category_name));
    const categoryId = matchedItem ? valueAtSourcePath(matchedItem.row, candidate.id_field_path) : '';
    const workerOk = Boolean(workerResponse && workerResponse.ok);
    const probeFailureReason = workerOk ? '' : String(workerResponse && (workerResponse.reason || workerResponse.status) || 'resolver_probe_failed');
    const apiCall = {
      api_id: candidate.api_id,
      status: workerOk ? 'called' : 'blocked',
      blocked_reason: workerOk ? '' : 'resolver_probe_failed',
      worker_reason: probeFailureReason,
      evidence_ref: evidenceRef,
      artifact_ref: '',
      rows_returned: rows.length,
      request_debug: requestDebugFromProbePayload(workerResponse && workerResponse.payload),
      purpose: 'category_resolution',
      resolver_provider: candidate.resolver_provider || 'api_doc_matcher',
      source_field_paths: { name: candidate.name_field_path, id: candidate.id_field_path },
    };
    resolverCalls.push(apiCall);
    if (!workerOk) {
      failedResolverProbe = true;
      continue;
    }
    successfulResolverProbe = true;
    if (categoryId) {
      return {
        resolved: true,
        api_call: apiCall,
        api_calls: resolverCalls,
        resolution: {
          ...resolution,
          status: 'resolved',
          direction: 'name_to_id',
          category_id: String(categoryId),
          source_api_id: candidate.api_id,
          source_field_paths: { name: candidate.name_field_path, id: candidate.id_field_path },
          resolver_provider: candidate.resolver_provider || 'api_doc_matcher',
          request_debug: apiCall.request_debug,
          confidence: 0.92,
          evidence_ref: evidenceRef,
          blocked_reason: '',
        },
      };
    }
  }
  resolution.status = 'blocked';
  resolution.blocked_reason = successfulResolverProbe
    ? 'category_not_found'
    : failedResolverProbe
      ? 'resolver_probe_failed'
      : attemptedResolver
        ? 'resolver_probe_failed'
        : 'resolver_request_params_missing';
  resolution.resolver_provider = candidates[0] && candidates[0].resolver_provider || 'api_doc_matcher';
  return { resolved: false, resolution, api_call: null, api_calls: resolverCalls };
}

function persistDbAgentEvidence(nodeId, action, workerResponse, knownParams, options = {}) {
  ensureDir(EVIDENCE_DIR);
  const suffix = options.apiId ? `.${safeEvidenceToken(options.apiId)}` : '';
  const evidencePath = path.join(EVIDENCE_DIR, `${nodeId}.db_agent.${action}${suffix}.json`);
  fs.writeFileSync(evidencePath, JSON.stringify({
    node_id: nodeId,
    action,
    api_id: options.apiId || '',
    known_params: redactedObjectForDisplay(knownParams),
    response: dbAgentWorkerResponseForEvidence(workerResponse),
    created_at: new Date().toISOString(),
  }, null, 2));
  return `evidence/${nodeId}.db_agent.${action}${suffix}.json`;
}

function persistDataMappingContract(nodeId, contract, { draft = false } = {}) {
  ensureDir(EVIDENCE_DIR);
  const fileName = draft ? `${nodeId}.data_mapping_contract.draft.json` : `${nodeId}.data_mapping_contract.json`;
  const evidencePath = path.join(EVIDENCE_DIR, fileName);
  fs.writeFileSync(evidencePath, JSON.stringify({
    ...contract,
    persisted_at: new Date().toISOString(),
  }, null, 2));
  return `evidence/${fileName}`;
}

function persistDbAgentArtifact(node, workerResponse, evidenceRef) {
  const rows = rowsFromProbePayload(workerResponse && workerResponse.payload);
  if (rows.length === 0) return null;
  ensureDir(ARTIFACTS_DIR);
  const output = Array.isArray(node.output_model && node.output_model.outputs) ? node.output_model.outputs[0] : null;
  const artifact = {
    title: output && output.title ? output.title : '行业前300商品分析表',
    node_id: node.id,
    node_name: node.name || node.id,
    status: 'ready',
    rows,
    conclusions: [],
    evidence_ids: [evidenceRef],
    generated_at: new Date().toISOString(),
    source: 'db_archaeologist.probe_api_sample',
  };
  const artifactPath = path.join(ARTIFACTS_DIR, `${node.id}.db_agent.json`);
  fs.writeFileSync(artifactPath, JSON.stringify(artifact, null, 2));
  return { ...artifact, artifact_path: `artifacts/${node.id}.db_agent.json` };
}

function isDataAnalysisNode(node) {
  if (!node || typeof node !== 'object') return false;
  const view = node.analysis_node_view && typeof node.analysis_node_view === 'object' ? node.analysis_node_view : {};
  if (view.node_kind === 'data_analysis') return true;
  const fields = nodeOutputFieldRequirements(node);
  const requirementIds = Array.isArray(node.data_requirements) ? node.data_requirements : [];
  const requiredData = Array.isArray(node.input_model && node.input_model.required_data) ? node.input_model.required_data : [];
  return node.kind === 'data' && fields.length > 0 && (requirementIds.length > 0 || requiredData.length > 0);
}

function runKnownParams(payload, upstreamArtifacts) {
  return {
    ...extractKnownParamsFromArtifacts(upstreamArtifacts),
    ...(payload.known_params && typeof payload.known_params === 'object' ? payload.known_params : {}),
  };
}

function paramTokens(value) {
  const raw = String(value || '');
  const camelSplit = raw.replace(/([a-z0-9])([A-Z])/g, '$1 $2');
  const lower = camelSplit.toLowerCase();
  const compact = lower.replace(/[^a-z0-9\u4e00-\u9fff]+/g, '');
  const tokens = lower.split(/[^a-z0-9\u4e00-\u9fff]+/).map(item => item.trim()).filter(Boolean);
  if (compact) tokens.push(compact);
  return new Set(tokens);
}

function hasToken(tokens, values) {
  return values.some(value => tokens.has(value));
}

function categoryParamRole(paramName, desc) {
  const tokens = paramTokens(paramName);
  const compact = String(paramName || '').toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]+/g, '');
  const descText = String(desc || '');
  const descLower = descText.toLowerCase();
  const idNames = new Set(['cid', 'cateid', 'categoryid', 'catid']);
  const nameNames = new Set(['catename', 'categoryname', 'tertiarycategory']);
  const descSaysId = /类目\s*id/i.test(descText) || /category\s*id|cate\s*id/i.test(descLower);
  const descSaysName = /类目名称|品类名称|三级类目|叶子类目/.test(descText);
  if (idNames.has(compact) || hasToken(tokens, ['cid', 'cateid', 'cate_id', 'categoryid', 'category_id', 'catid', 'cat_id']) || descSaysId) return 'category_id';
  if (nameNames.has(compact) || hasToken(tokens, ['catename', 'cate_name', 'categoryname', 'category_name', 'tertiarycategory', 'tertiary_category']) || descSaysName) return 'category_name';
  if (/类目|品类|category|cate/.test(descLower) || hasToken(tokens, ['category', 'cate', 'cat'])) return 'category_name';
  return '';
}

function businessParamForApiParam(paramName, desc) {
  const nameTokens = paramTokens(paramName);
  const descText = String(desc || '').toLowerCase();
  const nameText = String(paramName || '').toLowerCase();
  const descSaysDate = /日期|时间|周期|date|time|period/.test(descText);
  const descSaysAuditTime = /更新|修改|创建|同步|入库|最后|最近|update|updated|modified|created|sync/.test(descText);
  const descSaysProduct = /商品|产品|关键词|product|goods|item|keyword/.test(descText);
  const descSaysPageSize = /页|分页|条数|数量|limit|page/.test(descText);
  const nameSaysAuditTime = hasToken(nameTokens, [
    'update',
    'updated',
    'updatetime',
    'updateat',
    'updatedat',
    'modify',
    'modified',
    'createtime',
    'createdat',
    'sync',
    'synctime',
    'timestamp',
  ]) || /(^|[_-])(update|updated|modify|modified|create|created|sync|timestamp)([_-]|$)/i.test(nameText);

  if (categoryParamRole(paramName, desc)) return 'category';
  if (
    !nameSaysAuditTime
    && !descSaysAuditTime
    && (
      hasToken(nameTokens, ['period', 'daterange', 'date_range', 'startdate', 'enddate', 'dealdate', 'bizdate'])
      || nameTokens.has('date')
      || (nameTokens.has('dt') && (descSaysDate || nameText === 'dt'))
      || descSaysDate
    )
  ) return 'period';
  if (
    hasToken(nameTokens, ['productline', 'product_line'])
    || descSaysProduct
    || ((nameTokens.has('product') || nameTokens.has('goods') || nameTokens.has('item') || nameTokens.has('keyword')) && descSaysProduct)
  ) return 'product_line';
  if (hasToken(nameTokens, ['priceband', 'price_band']) || /价格带|price\s*band/.test(descText)) return 'price_band';
  if (hasToken(nameTokens, ['pagesize', 'page_size', 'limit', 'top']) || (nameTokens.has('size') && descSaysPageSize) || /每页|条数|page\s*size/.test(descText)) return 'page_size';
  if (hasToken(nameTokens, ['page', 'pagenum', 'pageindex', 'pageno', 'page_no']) || /页码|page\s*(num|no|index)/.test(descText)) return 'page';
  return '';
}

function bindApiRequestParams(apiRequestParams, knownParams) {
  const mappings = [];
  const params = {};
  const missingRequiredParams = [];
  const droppedOptionalParams = [];
  const requiredParams = Array.isArray(apiRequestParams) ? apiRequestParams : [];
  const categoryResolution = {
    schema_version: 'category-resolution-v1',
    status: knownParams && (knownParams.cid || knownParams.category_id || knownParams.cate_id || knownParams.cat_id) ? 'resolved' : knownParams && (knownParams.category || knownParams['分析类目'] || knownParams['类目']) ? 'needs_input' : 'blocked',
    category_name: String(knownParams && (knownParams.category || knownParams['分析类目'] || knownParams['类目'] || knownParams.category_name || knownParams.cate_name || knownParams.tertiary_category) || ''),
    category_id: String(knownParams && (knownParams.cid || knownParams.category_id || knownParams.cate_id || knownParams.cat_id || knownParams['类目ID'] || knownParams['类目id']) || ''),
    source_param: '',
    source_api_id: '',
    source_field_paths: {},
    confidence: knownParams && (knownParams.cid || knownParams.category_id || knownParams.cate_id || knownParams.cat_id) ? 1 : 0,
    alternatives: [],
    evidence_ref: '',
    blocked_reason: '',
  };
  if (!categoryResolution.category_id) categoryResolution.blocked_reason = 'category_id_required';
  for (const param of requiredParams) {
    const apiParam = String(param && param.name || '').trim();
    if (!apiParam) continue;
    const desc = String(param && (param.desc || param.description) || '');
    const required = Boolean(param && param.required);
    let businessParam = businessParamForApiParam(apiParam, desc);
    const categoryRole = categoryParamRole(apiParam, desc);
    let value = Object.prototype.hasOwnProperty.call(knownParams || {}, apiParam) ? knownParams[apiParam] : undefined;
    let status = value !== undefined && value !== null && String(value).trim() ? 'bound' : '';
    let source = status === 'bound' ? 'known_params_api_param' : '';
    let bindingMethod = status === 'bound' ? 'direct_api_param' : '';
    let confidence = status === 'bound' ? 1 : 0;
    let missingReason = '';

    if (status !== 'bound' && categoryRole === 'category_id') {
      value = categoryResolution.category_id;
      status = value ? 'bound' : (required ? 'missing' : 'optional');
      source = value ? 'known_params_category_id' : '';
      bindingMethod = value ? 'category_id_direct' : '';
      confidence = value ? 1 : 0;
      missingReason = value ? '' : '缺少类目ID，不能把中文类目名绑定到 cid/category_id/cate_id';
      businessParam = 'category';
    } else if (status !== 'bound' && categoryRole === 'category_name') {
      value = categoryResolution.category_name;
      status = value ? 'bound' : (required ? 'missing' : 'optional');
      source = value ? 'upstream_artifact_or_known_params' : '';
      bindingMethod = value ? 'category_name_direct' : '';
      confidence = value ? 0.95 : 0;
      businessParam = 'category';
    } else if (status !== 'bound') {
      value = businessParam ? knownParams[businessParam] : undefined;
      status = value !== undefined && value !== null && String(value).trim() ? 'bound' : (required ? 'missing' : 'optional');
      source = status === 'bound' ? 'upstream_artifact_or_known_params' : '';
      bindingMethod = businessParam ? 'deterministic_alias' : '';
      confidence = status === 'bound' ? 0.9 : 0;
    } else if (!businessParam) {
      businessParam = apiParam;
    }

    if ((businessParam === 'page' || businessParam === 'page_size') && status !== 'bound') {
      value = businessParam === 'page' ? 1 : 300;
      status = 'bound';
      source = 'default';
      bindingMethod = 'deterministic_default';
      confidence = 0.8;
    } else if (businessParam === 'period' && status === 'bound' && bindingMethod !== 'direct_api_param' && /^(start|end|deal|biz|dt|date)/i.test(apiParam) && !/range/i.test(apiParam)) {
      // Relative business periods often need date normalization. Keep them visible for human review.
      status = 'manual_required';
      missingReason = '业务周期需要转换为 API 日期格式';
      confidence = 0.65;
    }

    if (status === 'bound') {
      params[apiParam] = value;
    } else if (required) {
      missingRequiredParams.push(apiParam);
    } else if (status === 'manual_required') {
      droppedOptionalParams.push(apiParam);
    }

    mappings.push({
      api_param: apiParam,
      api_param_path: `query.${apiParam}`,
      api_param_type: String(param && param.type || 'unknown'),
      business_param: businessParam,
      business_param_label: businessParam === 'category' ? '分析类目'
        : businessParam === 'period' ? '分析周期'
          : businessParam === 'product_line' ? '分析产品线'
            : businessParam === 'price_band' ? '价格带'
              : businessParam === 'page' ? '页码'
                : businessParam === 'page_size' ? '条数'
                  : '',
      source,
      source_ref: '',
      value: value === undefined || value === null ? '' : value,
      required,
      status,
      binding_method: bindingMethod,
      confidence,
      missing_reason: missingReason || (required && status === 'missing' ? '缺少可绑定业务参数' : ''),
      human_confirmed: false,
      category_param_role: categoryRole,
    });
  }
  return { request_param_mapping: mappings, params, missing_required_params: missingRequiredParams, dropped_optional_params: droppedOptionalParams, category_resolution: categoryResolution };
}

function assetCardForApi(node, apiId, selectedAssetCards) {
  const cards = Array.isArray(selectedAssetCards) ? selectedAssetCards : [];
  const existing = cards.find(card => String(card && card.api_id || '') === String(apiId || ''));
  if (existing) return existing;
  if (hasLocalApiDocIndex()) {
    const local = localAssetCardPayload(node, apiId);
    if (local.selected_api_asset_card && local.selected_api_asset_card.api_id) return local.selected_api_asset_card;
  }
  if (dbAgentStatus().status === 'ok') {
    const workerResponse = callDbAgentWorker({ tool: 'get_api_asset_card', args: { api_id: String(apiId || '') } });
    const payload = buildAssetCardPayload(node, workerResponse);
    if (payload.selected_api_asset_card && payload.selected_api_asset_card.api_id) return payload.selected_api_asset_card;
  }
  return null;
}

function dataAnalysisCoverageForRun(node, knownParams, payload) {
  const payloadCoveragePlan = Array.isArray(payload.field_coverage_plan) ? payload.field_coverage_plan : [];
  const hasExecutablePayloadCoverage = payloadCoveragePlan.some(item => {
    if (!item || typeof item !== 'object') return false;
    const apiId = String(item.source_api_id || item.api_id || '').trim();
    const sourcePath = String(item.source_field_path || item.api_field_path || '').trim();
    const status = String(item.mapping_status || item.status || '').trim();
    return apiId || sourcePath || status === 'derived_or_manual_required' || status === 'manual_fill';
  });
  if (hasExecutablePayloadCoverage) {
    return {
      ok: true,
      provider: 'payload',
      field_coverage_plan: coveragePlanFromMappings(node, payloadCoveragePlan),
      selected_api_asset_cards: Array.isArray(payload.selected_api_asset_cards) ? payload.selected_api_asset_cards : [],
      coverage_summary: coverageSummary(payloadCoveragePlan),
    };
  }
  if (payload.data_mapping_contract && Array.isArray(payload.data_mapping_contract.field_coverage_plan)) {
    return {
      ok: true,
      provider: 'data_mapping_contract',
      field_coverage_plan: coveragePlanFromMappings(node, payload.data_mapping_contract.field_coverage_plan),
      selected_api_asset_cards: Array.isArray(payload.data_mapping_contract.selected_api_asset_cards) ? payload.data_mapping_contract.selected_api_asset_cards : [],
      coverage_summary: coverageSummary(payload.data_mapping_contract.field_coverage_plan),
    };
  }
  const mapped = matcherPayloadForNode(node, knownParams, { ...payload, action: 'suggest_multi_api_mapping' });
  if (mapped.degraded) return { ok: false, degraded: true, ...mapped };
  return {
    ok: true,
    provider: mapped.provider || 'api_doc_index',
    field_coverage_plan: Array.isArray(mapped.field_coverage_plan) ? mapped.field_coverage_plan : [],
    selected_api_asset_cards: Array.isArray(mapped.selected_api_asset_cards) ? mapped.selected_api_asset_cards : [],
    coverage_summary: mapped.coverage_summary || {},
    mapping_payload: mapped,
  };
}

function groupedApiPlansForCoverage(node, knownParams, coverage, selectedAssetCards, payload = {}) {
  const byApi = new Map();
  for (const field of Array.isArray(coverage) ? coverage : []) {
    const apiId = String(field.source_api_id || '').trim();
    if (!apiId) continue;
    if (!byApi.has(apiId)) byApi.set(apiId, []);
    byApi.get(apiId).push(field);
  }
  return Array.from(byApi.entries()).map(([apiId, fields], index) => {
    const card = assetCardForApi(node, apiId, selectedAssetCards);
    const apiRequestParams = requestParamsFromAssetCard(card);
    const matcherBinding = localApiEntryForId(apiId) ? callRequestParamBinder(apiId, knownParams, payload) : null;
    const binding = matcherBinding && !matcherBinding.degraded
      ? matcherBinding
      : bindApiRequestParams(apiRequestParams, knownParams);
    const sourcePathMissing = fields
      .filter(field => !String(field.source_field_path || field.api_field_path || '').trim())
      .map(field => String(field.field_name || field.title || ''))
      .filter(Boolean);
    const hasExecutableFields = fields.some(field => String(field.source_field_path || field.api_field_path || '').trim());
    const missingRequiredParams = [...binding.missing_required_params];
    const categoryBlocked = Array.isArray(binding.request_param_mapping)
      && binding.request_param_mapping.some(item => item && item.category_param_role === 'category_id' && item.status === 'missing');
    const bindingUnavailable = Boolean(matcherBinding && matcherBinding.degraded && matcherBinding.reason !== 'api_id_not_in_api_doc_index');
    const status = missingRequiredParams.length > 0 || !hasExecutableFields || bindingUnavailable ? 'blocked' : 'planned';
    const executionRole = String(
      card && card.execution_applicability && card.execution_applicability.execution_role
      || dataApiExecutionRole(apiId, card && card.name || fields[0] && fields[0].source_api_name || '', card)
    );
    const categoryRoles = new Set((Array.isArray(binding.request_param_mapping) ? binding.request_param_mapping : [])
      .map(item => String(item && item.category_param_role || ''))
      .filter(Boolean));
    const categoryScope = executionRole === 'product_detail_enrichment'
      ? 'inherited_from_primary'
      : categoryRoles.has('category_id')
      ? 'category_id_required'
      : categoryRoles.has('category_name')
        ? 'category_name_supported'
        : 'unscoped';
    return {
      api_id: apiId,
      api_name: String(card && card.name || fields[0] && fields[0].source_api_name || ''),
      execution_role: executionRole,
      depends_on_role: executionRole === 'product_detail_enrichment' ? 'topn_trade_total_primary' : '',
      input_binding: executionRole === 'product_detail_enrichment' ? { goods_id: 'primary_rows[].goods_id' } : {},
      call_order: index + 1,
      source_fields: fields.map(field => String(field.field_name || field.title || '')).filter(Boolean),
      request_param_mapping: binding.request_param_mapping,
      params: binding.params,
      missing_required_params: missingRequiredParams,
      dropped_optional_params: binding.dropped_optional_params,
      category_resolution: binding.category_resolution || {},
      request_param_binding_provider: matcherBinding && !matcherBinding.degraded ? 'api_doc_matcher' : 'server_fallback',
      request_param_binding_reason: categoryBlocked ? 'category_id_required' : matcherBinding && matcherBinding.degraded ? matcherBinding.reason : '',
      execution_date: binding.execution_date || '',
      timezone: binding.timezone || '',
      normalized_period: binding.normalized_period || {},
      category_scope: categoryScope,
      scope_validation_status: categoryScope === 'unscoped' ? 'unverified' : 'pending',
      scope_validation: {},
      source_path_missing_fields: sourcePathMissing,
      status,
      evidence_ref: '',
      artifact_ref: '',
      rows_returned: 0,
    };
  });
}

function categoryValueFromRow(row, keys) {
  if (!row || typeof row !== 'object' || Array.isArray(row)) return '';
  for (const key of keys) {
    const value = row[key];
    if (value !== undefined && value !== null && String(value).trim()) return String(value).trim();
  }
  return '';
}

function validateRowsForCategoryScope(plan, rows, categoryResolution) {
  const categoryScope = String(plan && plan.category_scope || 'unscoped');
  const sourceRows = Array.isArray(rows) ? rows : [];
  if (categoryScope === 'unscoped') {
    return {
      status: 'unverified',
      accepted_rows: sourceRows,
      matched_rows: 0,
      rejected_rows: 0,
      reason: 'api_does_not_accept_category_filter',
    };
  }
  if (sourceRows.length === 0) {
    return { status: 'empty', accepted_rows: [], matched_rows: 0, rejected_rows: 0, reason: 'api_returned_no_rows' };
  }
  const expectedId = String(categoryResolution && categoryResolution.category_id || '');
  const expectedNames = new Set([
    normalizeCategoryText(categoryResolution && categoryResolution.requested_name),
    normalizeCategoryText(categoryResolution && categoryResolution.category_name),
    normalizeCategoryText(categoryResolution && categoryResolution.canonical_name),
  ].filter(Boolean));
  let inspectableRows = 0;
  const acceptedRows = [];
  for (const row of sourceRows) {
    const rowId = categoryValueFromRow(row, ['cid', 'category_id', 'cate_id', 'cat_id']);
    const rowName = normalizeCategoryText(categoryValueFromRow(row, ['category_name', 'cate_name', 'category', 'tertiary_category']));
    if (rowId || rowName) inspectableRows += 1;
    const idMatches = Boolean(expectedId && rowId && expectedId === rowId);
    const nameMatches = Boolean(rowName && expectedNames.has(rowName));
    if (idMatches || nameMatches) acceptedRows.push(row);
  }
  if (acceptedRows.length > 0) {
    return {
      status: 'matched',
      accepted_rows: acceptedRows,
      matched_rows: acceptedRows.length,
      rejected_rows: sourceRows.length - acceptedRows.length,
      reason: 'response_category_matches_resolution',
    };
  }
  if (inspectableRows > 0) {
    return {
      status: 'mismatch',
      accepted_rows: [],
      matched_rows: 0,
      rejected_rows: sourceRows.length,
      reason: 'response_category_mismatch',
    };
  }
  return {
    status: 'request_bound',
    accepted_rows: sourceRows,
    matched_rows: 0,
    rejected_rows: 0,
    reason: 'response_has_no_category_identity',
  };
}

function dataAnalysisTopN(payload = {}) {
  const raw = payload.top_n ?? payload.topN ?? payload.limit ?? payload.page_size;
  const numeric = Number(raw);
  if (!Number.isFinite(numeric)) return DEFAULT_DATA_ANALYSIS_TOP_N;
  return Math.max(1, Math.min(300, Math.floor(numeric)));
}

function applyTopNToPlanParams(plan, topN) {
  if (!plan || typeof plan !== 'object') return plan;
  const fetchLimit = String(plan.execution_role || '') === 'growth_enrichment'
    ? Math.max(Number(topN) || DEFAULT_DATA_ANALYSIS_TOP_N, 300)
    : Number(topN) || DEFAULT_DATA_ANALYSIS_TOP_N;
  const params = plan.params && typeof plan.params === 'object' ? { ...plan.params } : {};
  const mappings = Array.isArray(plan.request_param_mapping) ? plan.request_param_mapping.map(item => ({ ...item })) : [];
  for (const mapping of mappings) {
    const apiParam = String(mapping.api_param || '');
    const businessParam = String(mapping.business_param || '');
    if (!apiParam) continue;
    if (businessParam === 'page_size' || /^(pageSize|page_size|limit|top)$/i.test(apiParam)) {
      params[apiParam] = fetchLimit;
      mapping.value = fetchLimit;
      if (!mapping.binding_method || mapping.binding_method === 'deterministic_default') {
        mapping.binding_method = 'top_n_default';
      }
    }
  }
  plan.params = params;
  plan.fetch_limit = fetchLimit;
  plan.request_param_mapping = mappings;
  return plan;
}

function dataApiExecutionRole(apiId, apiName = '', card = null) {
  const text = `${apiId || ''} ${apiName || ''} ${card && card.path || ''}`.toLowerCase();
  const compactName = value => String(value || '').toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]+/g, '');
  const requestFields = requestParamsFromAssetCard(card).map(item => compactName(item.name));
  const responseFields = apiFieldsFromAssetCard(card).map(item => compactName(item.name || item.path));
  const hasProductInput = requestFields.some(name => ['goodsid', 'itemid', 'productid', 'commodityid'].includes(name));
  const hasProductOutput = responseFields.some(name => ['goodsid', 'itemid', 'productid', 'commodityid'].includes(name));
  const detailSignals = responseFields.filter(name => ['corematerial', 'usagescene', 'sellingpointsummary', 'goodsspecparams'].includes(name));
  if ((hasProductInput && hasProductOutput && detailSignals.length >= 2) || text.includes('goods_detail_info')) {
    return 'product_detail_enrichment';
  }
  if ((text.includes('热销商品') || text.includes('goods')) && (text.includes('交易总量') || text.includes('trade_category_goods'))) {
    return 'topn_trade_total_primary';
  }
  if ((text.includes('热销商品') || text.includes('goods')) && (text.includes('交易增速') || text.includes('speed_category_goods'))) {
    return 'growth_enrichment';
  }
  return 'general';
}

function normalizeDetailText(value) {
  if (value === undefined || value === null) return value;
  return String(value).replace(/\s+/g, ' ').trim();
}

function normalizedDetailRow(row) {
  if (!row || typeof row !== 'object' || Array.isArray(row)) return row;
  const normalized = { ...row };
  if (Object.prototype.hasOwnProperty.call(normalized, 'usage_scene')) {
    normalized.usage_scene = normalizeDetailText(normalized.usage_scene);
  }
  return normalized;
}

const DETAIL_DATE_FIELDS = ['statist_date', 'statistics_date', 'business_date', 'biz_date', 'data_month', 'statist_month', 'month'];

function normalizedDetailMonth(value) {
  const text = String(value || '').trim().replace(/^['"]+|['"]+$/g, '');
  const match = text.match(/^(\d{4})[-/]?(\d{2})(?:[-/]?(\d{2}))?/);
  if (!match) return '';
  return `${match[1]}-${match[2]}-${match[3] || '01'}`;
}

function detailMonthForRow(row) {
  if (!row || typeof row !== 'object' || Array.isArray(row)) return '';
  for (const field of DETAIL_DATE_FIELDS) {
    const normalized = normalizedDetailMonth(row[field]);
    if (normalized) return normalized;
  }
  return '';
}

function selectMostRecentDetailRow(rows, targetMonth = '') {
  const sourceRows = Array.isArray(rows) ? rows : [];
  if (sourceRows.length === 0) return { row: null, selected_month: '', temporal_status: 'not_available' };
  const datedRows = sourceRows
    .map(row => ({ row, month: detailMonthForRow(row) }))
    .filter(item => item.month)
    .sort((left, right) => right.month.localeCompare(left.month));
  if (datedRows.length === 0) {
    return { row: sourceRows[0], selected_month: '', temporal_status: 'not_verifiable' };
  }
  const normalizedTarget = normalizedDetailMonth(targetMonth);
  const selected = normalizedTarget
    ? datedRows.find(item => item.month <= normalizedTarget)
    : datedRows[0];
  if (!selected) return { row: null, selected_month: '', temporal_status: 'future_only' };
  return {
    row: selected.row,
    selected_month: selected.month,
    temporal_status: normalizedTarget && selected.month < normalizedTarget ? 'fallback_to_recent_available' : 'aligned',
  };
}

function detailTemporalAlignment(itemStatuses, targetMonth = '') {
  const successful = (Array.isArray(itemStatuses) ? itemStatuses : []).filter(item => item.status === 'success');
  const dated = successful.map(item => String(item.selected_data_month || '')).filter(Boolean).sort().reverse();
  if (successful.length === 0) {
    return {
      strategy: 'latest_available_snapshot',
      status: 'not_available',
      target_month: normalizedDetailMonth(targetMonth),
      selected_month: '',
      response_date_field: null,
    };
  }
  if (dated.length !== successful.length) {
    return {
      strategy: 'latest_available_snapshot',
      status: 'not_verifiable',
      target_month: normalizedDetailMonth(targetMonth),
      selected_month: dated[0] || '',
      response_date_field: null,
      reason: 'detail_response_date_field_missing',
    };
  }
  const selectedMonth = dated[0];
  const normalizedTarget = normalizedDetailMonth(targetMonth);
  return {
    strategy: 'latest_available_snapshot',
    status: normalizedTarget && selectedMonth < normalizedTarget ? 'fallback_to_recent_available' : 'aligned',
    target_month: normalizedTarget,
    selected_month: selectedMonth,
    response_date_field: DETAIL_DATE_FIELDS.find(field => successful.some(item => item.response_date_field === field)) || null,
  };
}

function detailDataSourceCandidates(plan) {
  const mappings = Array.isArray(plan && plan.request_param_mapping) ? plan.request_param_mapping : [];
  const mapping = mappings.find(item => String(item && item.api_param || '').toLowerCase() === 'data_source') || {};
  const candidates = [];
  const add = value => {
    const text = String(value || '').trim();
    if (text && !candidates.includes(text)) candidates.push(text);
  };
  if (mapping.binding_method !== 'documented_default') add(plan && plan.params && plan.params.data_source);
  for (const value of Array.isArray(mapping.candidate_values) ? mapping.candidate_values : []) add(value);
  add('sycm');
  add(plan && plan.params && plan.params.data_source);
  add('qbt');
  return candidates;
}

function detailResponseDateField(plan) {
  const entry = localApiEntryForId(plan && plan.api_id);
  const fields = Array.isArray(entry && entry.response_fields) ? entry.response_fields : [];
  for (const field of fields) {
    const name = String(field && (field.name || field.path) || '').split('.').pop().replace(/\[\]$/g, '');
    if (DETAIL_DATE_FIELDS.includes(name)) return name;
  }
  return '';
}

function detailBatchRows(workerResponse, options = {}) {
  const payload = workerResponse && workerResponse.payload && typeof workerResponse.payload === 'object'
    ? workerResponse.payload
    : {};
  const items = Array.isArray(payload.items) ? payload.items : [];
  const targetMonth = String(options.target_month || '');
  const dataSource = String(options.data_source || '');
  const rows = [];
  const itemStatuses = [];
  const summary = { requested: items.length, success: 0, empty: 0, failed: 0, identity_mismatch: 0 };
  for (const item of items) {
    const correlationId = String(item && item.correlation_id || '');
    const itemRows = Array.isArray(item && item.rows) ? item.rows : [];
    let status = String(item && item.status || 'failed');
    const accepted = [];
    for (const rawRow of itemRows) {
      const row = normalizedDetailRow(rawRow);
      const rowIdentity = productIdentityForRow(row);
      if (!correlationId || !rowIdentity || correlationId !== rowIdentity) {
        status = 'identity_mismatch';
        continue;
      }
      accepted.push(row);
    }
    if (status === 'success' && accepted.length === 0) status = itemRows.length > 0 ? 'identity_mismatch' : 'empty';
    const selection = status === 'success'
      ? selectMostRecentDetailRow(accepted, targetMonth)
      : { row: null, selected_month: '', temporal_status: status };
    if (status === 'success' && !selection.row) status = 'empty';
    if (status === 'success') summary.success += 1;
    else if (status === 'empty') summary.empty += 1;
    else if (status === 'identity_mismatch') summary.identity_mismatch += 1;
    else summary.failed += 1;
    if (status === 'success' && selection.row) rows.push(selection.row);
    const responseDateField = selection.row
      ? DETAIL_DATE_FIELDS.find(field => normalizedDetailMonth(selection.row[field])) || ''
      : '';
    itemStatuses.push({
      correlation_id: correlationId,
      status,
      attempts: Number(item && item.attempts || 0),
      rows_returned: status === 'success' ? 1 : 0,
      available_rows: accepted.length,
      data_source: dataSource,
      selected_data_month: selection.selected_month,
      temporal_status: selection.temporal_status,
      response_date_field: responseDateField,
      request_debug: redactedObjectForDisplay(item && item.response && item.response.request || {}),
      error: String(item && item.error || ''),
    });
  }
  return { rows, summary, item_statuses: itemStatuses };
}

function firstDetailValue(row, names) {
  for (const name of names) {
    const value = row && typeof row === 'object' ? row[name] : undefined;
    if (hasNonEmptyValue(value)) return value;
  }
  return '';
}

function usableProductImageUrl(value) {
  const text = String(value || '').trim();
  if (!/^https?:\/\//i.test(text)) return '';
  if (/item\.taobao\.com\/item\.htm/i.test(text)) return '';
  return text;
}

function derivedEvidenceRowsForProducts(rowsByApi, apiExecutionPlan, projection) {
  const primaryApiId = String(projection && projection.primary_api_id || '');
  const primaryRows = rowsByApi instanceof Map ? rowsByApi.get(primaryApiId) || [] : [];
  const detailPlan = (Array.isArray(apiExecutionPlan) ? apiExecutionPlan : [])
    .find(item => item.execution_role === 'product_detail_enrichment');
  const detailRows = detailPlan && rowsByApi instanceof Map ? rowsByApi.get(detailPlan.api_id) || [] : [];
  const detailById = rowsByProductIdentity(detailRows);
  return primaryRows.map((primaryRow, rowIndex) => {
    const goodsId = productIdentityForRow(primaryRow);
    const detailRow = goodsId ? detailById.get(goodsId) || {} : {};
    const imageUrl = usableProductImageUrl(firstDetailValue(primaryRow, ['goods_img', 'product_image', 'pictures_linking', 'image_url']));
    return {
      row_index: rowIndex,
      goods_id: goodsId,
      fields: {
        goods_name: firstDetailValue(detailRow, ['goods_name']) || firstDetailValue(primaryRow, ['goods_name', 'commodity', 'title']),
        core_material: firstDetailValue(detailRow, ['core_material']),
        usage_scene: firstDetailValue(detailRow, ['usage_scene']),
        selling_point_summary: firstDetailValue(detailRow, ['selling_point_summary']) || firstDetailValue(primaryRow, ['selling_point']),
        goods_spec_params: firstDetailValue(detailRow, ['goods_spec_params']),
        goods_img: imageUrl,
      },
      evidence_refs: [
        primaryApiId && (apiExecutionPlan.find(item => item.api_id === primaryApiId) || {}).evidence_ref,
        detailPlan && detailPlan.evidence_ref,
      ].filter(Boolean),
      image_evidence_status: imageUrl ? 'image_url_available_not_vision_verified' : 'not_vision_verified',
      risks: ['not_vision_verified'],
    };
  });
}

function previousMonthStart(value, monthsBack = 1) {
  const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return '';
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, 1));
  date.setUTCMonth(date.getUTCMonth() - Math.max(0, Number(monthsBack) || 0));
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}-01`;
}

function monthlyAttemptParams(plan, attemptIndex = 0, alignedMonth = '') {
  const params = plan && plan.params && typeof plan.params === 'object' ? { ...plan.params } : {};
  const baseDate = String(alignedMonth || params.start_date || params.end_date || '');
  if (!baseDate) return params;
  const targetDate = alignedMonth || previousMonthStart(baseDate, attemptIndex);
  if (!targetDate) return params;
  if (Object.prototype.hasOwnProperty.call(params, 'start_date')) params.start_date = targetDate;
  if (Object.prototype.hasOwnProperty.call(params, 'end_date')) params.end_date = targetDate;
  return params;
}

function monthlyFallbackLimit(plan, alignedMonth = '') {
  if (String(plan && plan.normalized_period && plan.normalized_period.grain || '') !== 'month') return 0;
  if (alignedMonth && String(plan && plan.execution_role || '') === 'growth_enrichment') return 0;
  return Math.max(0, Math.min(12, Number(plan.normalized_period.max_fallback_months ?? 6) || 0));
}

function dataTablePreview(dataTable, pageSize = DATA_TABLE_PAGE_SIZE) {
  const rows = Array.isArray(dataTable && dataTable.rows) ? dataTable.rows : [];
  const fields = Array.isArray(dataTable && dataTable.fields) ? [...dataTable.fields] : [];
  const safePageSize = Math.max(1, Math.min(50, Number(pageSize) || DATA_TABLE_PAGE_SIZE));
  return {
    fields,
    rows,
    top_n: Number(dataTable && dataTable.top_n || rows.length || 0),
    merge_strategy: String(dataTable && dataTable.merge_strategy || ''),
    primary_api_id: String(dataTable && dataTable.primary_api_id || ''),
    row_index_merged_api_ids: Array.isArray(dataTable && dataTable.row_index_merged_api_ids) ? dataTable.row_index_merged_api_ids : [],
    pagination: {
      current_page: 1,
      page_size: safePageSize,
      total_rows: rows.length,
      total_pages: Math.max(1, Math.ceil(rows.length / safePageSize)),
    },
  };
}

function pathSegmentsForProjection(sourcePath) {
  return String(sourcePath || '')
    .replace(/\[\]/g, '')
    .split('.')
    .map(part => part.trim())
    .filter(Boolean)
    .filter(part => !['data', 'result', 'results', 'rows', 'row', 'items', 'item', 'response', 'top'].includes(part));
}

function valueAtSourcePath(row, sourcePath) {
  if (!row || typeof row !== 'object') return undefined;
  const segments = pathSegmentsForProjection(sourcePath);
  let current = row;
  for (const segment of segments) {
    if (current && typeof current === 'object' && Object.prototype.hasOwnProperty.call(current, segment)) {
      current = current[segment];
    } else {
      current = undefined;
      break;
    }
  }
  if (current !== undefined) return current;
  const last = segments[segments.length - 1];
  return last && Object.prototype.hasOwnProperty.call(row, last) ? row[last] : undefined;
}

function hasNonEmptyValue(value) {
  return value !== undefined && value !== null && String(value).trim() !== '';
}

function rowsHaveValueForPath(rows, sourcePath) {
  return Array.isArray(rows) && rows.some(row => hasNonEmptyValue(valueAtSourcePath(row, sourcePath)));
}

function fieldNameAliases(fieldName) {
  const name = String(fieldName || '');
  const aliases = {
    '排名': ['rank', 'current_rank'],
    '商品链接': ['goods_url', 'product_url', 'item_url'],
    '客单价': ['unit_price', 'price', 'avg_price'],
    '价格带': ['price_band', 'unit_price', 'price'],
    '材质': ['material', 'material_real'],
    '场景': ['scene'],
    '主卖点': ['selling_point', 'sell_point'],
  };
  return aliases[name] || [];
}

function candidateFieldOptionsForRuntime(field) {
  const options = Array.isArray(field && field.candidate_field_options) ? field.candidate_field_options : [];
  const seen = new Set();
  const result = [];
  const add = (apiId, apiName, sourcePath, sourceKind = 'api_doc_index', confidence = 0.8) => {
    const key = `${apiId}::${sourcePath}`;
    if (!apiId || !sourcePath || seen.has(key)) return;
    seen.add(key);
    result.push({ source_api_id: apiId, source_api_name: apiName || '', source_field_path: sourcePath, source_kind: sourceKind, confidence });
  };
  for (const option of options) {
    add(String(option.source_api_id || ''), String(option.source_api_name || ''), String(option.source_field_path || ''), 'api_doc_index', Number(option.confidence || 0.8));
  }
  const apiId = String(field && field.source_api_id || '');
  const apiName = String(field && field.source_api_name || '');
  for (const alias of fieldNameAliases(field && (field.field_name || field.title))) {
    add(apiId, apiName, `data.result[].${alias}`, 'runtime_alias', 0.72);
    add(apiId, apiName, `data.rows.${alias}`, 'runtime_alias', 0.72);
  }
  return result;
}

function repairFieldCoverageWithRuntimeRows(fieldCoveragePlan, rowsByApi) {
  const repaired = [];
  for (const field of Array.isArray(fieldCoveragePlan) ? fieldCoveragePlan : []) {
    const item = { ...field };
    const mappingStatus = String(item.mapping_status || item.status || '');
    if (mappingStatus === 'derived_or_manual_required' || String(item.source_kind || '') === 'pi_derived') {
      repaired.push(item);
      continue;
    }
    const apiId = String(item.source_api_id || '');
    const sourcePath = String(item.source_field_path || item.api_field_path || '');
    const currentRows = rowsByApi instanceof Map ? rowsByApi.get(apiId) || [] : [];
    if (sourcePath && rowsHaveValueForPath(currentRows, sourcePath)) {
      repaired.push(item);
      continue;
    }
    let replacement = null;
    for (const option of candidateFieldOptionsForRuntime(item)) {
      const rows = rowsByApi instanceof Map ? rowsByApi.get(option.source_api_id) || [] : [];
      if (rowsHaveValueForPath(rows, option.source_field_path)) {
        replacement = option;
        break;
      }
    }
    if (replacement) {
      item.source_api_id = replacement.source_api_id;
      item.source_api_name = replacement.source_api_name || item.source_api_name || '';
      item.source_field_path = replacement.source_field_path;
      item.api_field_path = replacement.source_field_path;
      item.source_kind = replacement.source_kind;
      item.mapping_status = String(item.mapping_status || item.status || 'mapped') === 'missing' ? 'suggested' : String(item.mapping_status || item.status || 'mapped');
      item.status = item.mapping_status;
      item.confidence = Math.max(Number(item.confidence || 0), Number(replacement.confidence || 0));
      item.runtime_repair = {
        reason: 'source_field_had_no_live_values',
        previous_source_api_id: apiId,
        previous_source_field_path: sourcePath,
      };
    }
    repaired.push(item);
  }
  return repaired;
}

function derivedProductUrlFromRow(row) {
  const id = ['commodity_id', 'goods_id', 'item_id', 'product_id']
    .map(key => row && typeof row === 'object' ? row[key] : '')
    .find(value => hasNonEmptyValue(value));
  return id ? `https://item.taobao.com/item.htm?id=${encodeURIComponent(String(id))}` : undefined;
}

function shouldDeriveOutputField(fieldName, fields, rowsByApi) {
  const matching = (Array.isArray(fields) ? fields : []).filter(field => String(field.field_name || field.title || '') === fieldName);
  if (matching.length === 0) return false;
  return matching.every(field => {
    const apiId = String(field.source_api_id || '');
    const sourcePath = String(field.source_field_path || field.api_field_path || '');
    const rows = rowsByApi instanceof Map ? rowsByApi.get(apiId) || [] : [];
    return !sourcePath || !rowsHaveValueForPath(rows, sourcePath);
  });
}

const SPEED_TYPE_LABELS = {
  '1': '暴涨',
  '2': '高增',
  '3': '潜力',
  '4': '微涨',
  '5': '持平',
  '6': '下降',
};

function speedTypeDisplayValue(value) {
  const text = String(value ?? '').trim();
  if (!text) return text;
  if (Object.prototype.hasOwnProperty.call(SPEED_TYPE_LABELS, text)) return SPEED_TYPE_LABELS[text];
  const codeMatch = text.match(/^([1-6])(?:\D|$)/);
  if (codeMatch) return SPEED_TYPE_LABELS[codeMatch[1]];
  if (Object.values(SPEED_TYPE_LABELS).includes(text)) return text;
  return value;
}

function speedTypeValueSemantics() {
  return {
    kind: 'speed_type_enum',
    display_mode: 'enum_label',
    labels: { ...SPEED_TYPE_LABELS },
    high_growth_values: ['1', '2', '3'],
    non_high_growth_values: ['4', '5', '6'],
  };
}

function businessValueForProjection(fieldName, field, value) {
  const sourcePath = String(field && (field.source_field_path || field.api_field_path) || '');
  if (fieldName === '是否高增速' && sourcePath.endsWith('.speed_type')) {
    return speedTypeDisplayValue(value);
  }
  return value;
}

function projectRowsForFields(rows, fieldCoveragePlan) {
  const apiFields = (Array.isArray(fieldCoveragePlan) ? fieldCoveragePlan : [])
    .filter(field => String(field.source_field_path || field.api_field_path || '').trim());
  return (Array.isArray(rows) ? rows : []).map(row => {
    const out = {};
    for (const field of apiFields) {
      const fieldName = String(field.field_name || field.title || field.field_path || '');
      const value = valueAtSourcePath(row, field.source_field_path || field.api_field_path);
      if (value !== undefined) out[fieldName] = businessValueForProjection(fieldName, field, value);
    }
    return out;
  });
}

function primaryApiIdForProjection(apiExecutionPlan, rowsByApi) {
  const plans = Array.isArray(apiExecutionPlan) ? apiExecutionPlan : [];
  let best = { api_id: '', score: -1 };
  for (const plan of plans) {
    const apiId = String(plan && plan.api_id || '');
    const rows = rowsByApi instanceof Map ? rowsByApi.get(apiId) : null;
    if (plan && plan.status === 'called' && Array.isArray(rows) && rows.length > 0) {
      const sourceFieldCount = Array.isArray(plan.source_fields) ? plan.source_fields.length : 0;
      const scopeStatus = String(plan.scope_validation_status || '');
      const categoryScope = String(plan.category_scope || '');
      const scopeScore = scopeStatus === 'matched' || scopeStatus === 'verified'
        ? 3
        : categoryScope && categoryScope !== 'unscoped'
          ? 2
          : categoryScope === 'unscoped'
            ? 0
            : 1;
      const executionRole = String(plan.execution_role || '');
      const roleScore = executionRole === 'topn_trade_total_primary' ? 3 : executionRole === 'growth_enrichment' ? 1 : 2;
      const score = roleScore * 1000000000000 + scopeScore * 1000000000 + sourceFieldCount * 100000 + rows.length;
      if (score > best.score) best = { api_id: apiId, score };
    }
  }
  if (best.api_id) return best.api_id;
  for (const [apiId, rows] of rowsByApi instanceof Map ? rowsByApi.entries() : []) {
    if (Array.isArray(rows) && rows.length > 0) return apiId;
  }
  return '';
}

const PRODUCT_ID_KEYS = ['goods_id', 'commodity_id', 'item_id', 'product_id'];
const KEYWORD_ID_KEYS = ['keyword', 'keywords', 'kw_name', 'search_word'];

function productIdentityForRow(row) {
  if (!row || typeof row !== 'object' || Array.isArray(row)) return '';
  for (const key of PRODUCT_ID_KEYS) {
    const value = row[key];
    if (value !== undefined && value !== null && String(value).trim()) return String(value).trim();
  }
  const urlValue = row.goods_url || row.product_url || row.item_url || row.commodity_url || '';
  if (String(urlValue).trim()) {
    const match = String(urlValue).match(/[?&]id=([^&#]+)/i);
    return match ? decodeURIComponent(match[1]) : String(urlValue).trim();
  }
  return '';
}

function rowsByProductIdentity(rows) {
  const index = new Map();
  for (const row of Array.isArray(rows) ? rows : []) {
    const identity = productIdentityForRow(row);
    if (identity && !index.has(identity)) index.set(identity, row);
  }
  return index;
}

function keywordIdentityForRow(row) {
  if (!row || typeof row !== 'object' || Array.isArray(row)) return '';
  for (const key of KEYWORD_ID_KEYS) {
    const value = row[key];
    if (value !== undefined && value !== null && String(value).trim()) {
      return String(value).toLowerCase().replace(/\s+/g, '').trim();
    }
  }
  return '';
}

function analysisIdentityForRow(row) {
  return productIdentityForRow(row) || keywordIdentityForRow(row);
}

function rowsByAnalysisIdentity(rows) {
  const index = new Map();
  for (const row of Array.isArray(rows) ? rows : []) {
    const identity = analysisIdentityForRow(row);
    if (identity && !index.has(identity)) index.set(identity, row);
  }
  return index;
}

function sourceApiIdsWithRows(fieldCoveragePlan, rowsByApi) {
  const ids = [];
  const fields = Array.isArray(fieldCoveragePlan) ? fieldCoveragePlan : [];
  for (const field of fields) {
    const apiId = String(field && field.source_api_id || '').trim();
    if (!apiId || ids.includes(apiId)) continue;
    const rows = rowsByApi instanceof Map ? rowsByApi.get(apiId) : null;
    if (Array.isArray(rows) && rows.length > 0) ids.push(apiId);
  }
  return ids;
}

function projectRowsForApiFieldCoverage(rowsByApi, fieldCoveragePlan, apiExecutionPlan) {
  const primaryApiId = primaryApiIdForProjection(apiExecutionPlan, rowsByApi);
  const apiIdsWithRows = sourceApiIdsWithRows(fieldCoveragePlan, rowsByApi);
  const primaryRows = primaryApiId && rowsByApi instanceof Map ? rowsByApi.get(primaryApiId) || [] : [];
  const primaryIdentityIndex = rowsByAnalysisIdentity(primaryRows);
  const primaryIdentityKind = primaryRows.some(row => productIdentityForRow(row)) ? 'product_id' : primaryRows.some(row => keywordIdentityForRow(row)) ? 'keyword' : '';
  const keyJoinRowsByApi = new Map();
  const keyJoinedApiIds = [];
  const joinBlockedApiIds = [];
  for (const apiId of apiIdsWithRows) {
    if (apiId === primaryApiId) continue;
    const sourceRows = rowsByApi instanceof Map ? rowsByApi.get(apiId) || [] : [];
    const sourceIndex = rowsByAnalysisIdentity(sourceRows);
    const overlap = Array.from(sourceIndex.keys()).filter(key => primaryIdentityIndex.has(key));
    if (primaryIdentityIndex.size > 0 && overlap.length > 0) {
      keyJoinRowsByApi.set(apiId, sourceIndex);
      keyJoinedApiIds.push(apiId);
    } else {
      joinBlockedApiIds.push(apiId);
    }
  }
  const fields = Array.isArray(fieldCoveragePlan) ? fieldCoveragePlan : [];
  const deriveRank = shouldDeriveOutputField('排名', fields, rowsByApi);
  const deriveProductUrl = shouldDeriveOutputField('商品链接', fields, rowsByApi);
  const projectedRows = primaryRows.map((primaryRow, index) => {
    const out = {};
    for (const field of fields) {
      const apiId = String(field.source_api_id || '');
      const sourcePath = String(field.source_field_path || field.api_field_path || '');
      if (!apiId || !sourcePath) continue;
      const primaryIdentity = analysisIdentityForRow(primaryRow);
      const row = apiId === primaryApiId
        ? primaryRow
        : primaryIdentity && keyJoinRowsByApi.has(apiId)
          ? keyJoinRowsByApi.get(apiId).get(primaryIdentity)
          : null;
      const value = valueAtSourcePath(row, sourcePath);
      if (value !== undefined) {
        const fieldName = String(field.field_name || field.title || field.field_path || '');
        out[fieldName] = businessValueForProjection(fieldName, field, value);
      }
    }
    const fieldNames = new Set(fields.map(field => String(field.field_name || field.title || '')));
    if (deriveRank && fieldNames.has('排名') && !hasNonEmptyValue(out['排名'])) out['排名'] = index + 1;
    if (deriveProductUrl && fieldNames.has('商品链接') && !hasNonEmptyValue(out['商品链接'])) {
      const url = derivedProductUrlFromRow(primaryRow);
      if (url) out['商品链接'] = url;
    }
    return out;
  });
  return {
    rows: projectedRows,
    row_identities: primaryRows.map(analysisIdentityForRow),
    identity_kind: primaryIdentityKind,
    primary_api_id: primaryApiId,
    join_blocked_api_ids: joinBlockedApiIds,
    key_joined_api_ids: keyJoinedApiIds,
    join_keys: keyJoinedApiIds.length > 0 && primaryIdentityKind ? [primaryIdentityKind] : [],
    row_index_merged_api_ids: [],
    merge_strategy: keyJoinedApiIds.length > 0 ? 'key_join' : (primaryApiId ? 'single_api' : 'none'),
  };
}

function valuesForFieldFromRows(rows, field) {
  const sourcePath = String(field && (field.source_field_path || field.api_field_path) || '');
  const fieldName = String(field && (field.field_name || field.title || '') || '');
  if (!Array.isArray(rows)) return [];
  return rows.map(row => {
    const fromSourcePath = sourcePath ? valueAtSourcePath(row, sourcePath) : undefined;
    if (fromSourcePath !== undefined) return fromSourcePath;
    return row && typeof row === 'object' && Object.prototype.hasOwnProperty.call(row, fieldName) ? row[fieldName] : undefined;
  });
}

function buildFieldSources(fieldCoveragePlan, apiExecutionPlan, projectedRows, options = {}) {
  const planByApi = new Map(apiExecutionPlan.map(plan => [plan.api_id, plan]));
  const rowsByApi = options.rowsByApi instanceof Map ? options.rowsByApi : null;
  const joinBlockedApiIds = new Set(Array.isArray(options.joinBlockedApiIds) ? options.joinBlockedApiIds : []);
  const primaryApiId = String(options.primaryApiId || '');
  const deriveRank = shouldDeriveOutputField('排名', fieldCoveragePlan, rowsByApi);
  const deriveProductUrl = shouldDeriveOutputField('商品链接', fieldCoveragePlan, rowsByApi);
  return (Array.isArray(fieldCoveragePlan) ? fieldCoveragePlan : []).map(field => {
    const apiId = String(field.source_api_id || '');
    const sourcePath = String(field.source_field_path || field.api_field_path || '');
    const mappingStatus = String(field.mapping_status || field.status || (sourcePath ? 'mapped' : 'missing'));
    const plan = planByApi.get(apiId) || null;
    const fieldName = String(field.field_name || field.title || '');
    let valueStatus = 'not_called';
    let rowsChecked = 0;
    let rowsWithValue = 0;
    const projectedValues = valuesForFieldFromRows(projectedRows, { ...field, source_field_path: '', field_name: fieldName });
    const projectedRowsWithValue = projectedValues.filter(hasNonEmptyValue).length;
    const deterministicDerived = (fieldName === '排名' && deriveRank) || (fieldName === '商品链接' && deriveProductUrl);
    if (deterministicDerived && projectedRowsWithValue > 0) {
      rowsChecked = projectedValues.length;
      rowsWithValue = projectedRowsWithValue;
      valueStatus = 'present';
    } else if (!sourcePath && ['mapped', 'suggested', 'confirmed'].includes(mappingStatus)) valueStatus = 'source_path_missing';
    else if (!apiId && mappingStatus === 'derived_or_manual_required') valueStatus = 'not_called';
    else if (plan && plan.status === 'called') {
      const sourceRows = rowsByApi && rowsByApi.has(apiId) ? rowsByApi.get(apiId) : projectedRows;
      const sourceValues = valuesForFieldFromRows(sourceRows, field);
      const sourceRowsWithValue = sourceValues.filter(hasNonEmptyValue).length;
      rowsChecked = projectedValues.length || sourceValues.length;
      rowsWithValue = projectedRowsWithValue;
      if (joinBlockedApiIds.has(apiId) && sourceRowsWithValue > 0) valueStatus = 'join_blocked';
      else if (rowsWithValue > 0 && rowsWithValue < rowsChecked) valueStatus = 'partial';
      else if (rowsWithValue > 0) valueStatus = 'present';
      else if (apiId !== primaryApiId && sourceRowsWithValue > 0) valueStatus = 'missing';
      else if (sourceValues.some(value => value !== undefined)) valueStatus = 'empty';
      else valueStatus = sourceValues.length > 0 ? 'missing' : 'empty';
    } else if (plan && (plan.source_path_missing_fields || []).includes(String(field.field_name || field.title || ''))) {
      valueStatus = 'source_path_missing';
    }
    return {
      field_path: String(field.field_path || ''),
      field_name: fieldName,
      required: field.required !== false,
      mapping_status: mappingStatus,
      source_kind: deterministicDerived && projectedRowsWithValue > 0 ? 'deterministic_derived' : String(field.source_kind || ''),
      source_api_id: apiId,
      source_api_name: String(field.source_api_name || ''),
      source_field_path: sourcePath,
      confidence: Number.isFinite(Number(field.confidence)) ? Number(field.confidence) : 0,
      evidence_ref: plan ? plan.evidence_ref : '',
      api_call_status: plan ? plan.status : 'not_called',
      value_status: valueStatus,
      rows_with_value: rowsWithValue,
      rows_missing_value: Math.max(rowsChecked - rowsWithValue, 0),
      derivation_method: fieldName === '排名' && deterministicDerived && projectedRowsWithValue > 0 ? 'row_index_rank' : fieldName === '商品链接' && deterministicDerived && projectedRowsWithValue > 0 ? 'commodity_id_url' : '',
      value_semantics: fieldName === '是否高增速' && sourcePath.endsWith('.speed_type') ? speedTypeValueSemantics() : null,
      runtime_repair: field.runtime_repair || null,
    };
  });
}

function dataTableRiskSet(blockedReasons, fieldSources, projection) {
  const risks = new Set((Array.isArray(blockedReasons) ? blockedReasons : []).filter(Boolean));
  if (Array.isArray(projection && projection.join_blocked_api_ids) && projection.join_blocked_api_ids.length > 0) {
    risks.add('join_blocked');
  }
  if (Array.isArray(projection && projection.row_index_merged_api_ids) && projection.row_index_merged_api_ids.length > 0) {
    risks.add('row_index_merge_requires_review');
  }
  const incompleteStatuses = new Set(['empty', 'missing', 'partial', 'source_path_missing', 'not_called', 'join_blocked']);
  for (const source of Array.isArray(fieldSources) ? fieldSources : []) {
    if (source.required && incompleteStatuses.has(String(source.value_status || ''))) {
      risks.add(`${source.field_name}:${source.value_status}`);
    }
    if (source.required && source.source_kind === 'pi_derived' && ['present', 'pi_derived_unconfirmed'].includes(source.value_status)) {
      risks.add(`${source.field_name}:pi_derived_unconfirmed`);
    }
  }
  return risks;
}

function persistJsonArtifact(relativePath, payload) {
  const absolutePath = path.join(APP_ROOT, relativePath);
  ensureDir(path.dirname(absolutePath));
  fs.writeFileSync(absolutePath, JSON.stringify(payload, null, 2));
  return relativePath;
}

const BUSINESS_CATEGORY_CONTEXT_REF = 'artifacts/business_category_context.json';

function isKeywordAnalysisNode(node) {
  if (!node || typeof node !== 'object') return false;
  if (String(node.id || '') === 'collect_keywords') return true;
  const requirements = Array.isArray(node.data_requirements) ? node.data_requirements.map(String) : [];
  return requirements.includes('category_keywords_top300');
}

function loadBusinessCategoryContext() {
  const contextPath = path.join(APP_ROOT, BUSINESS_CATEGORY_CONTEXT_REF);
  if (!fs.existsSync(contextPath)) return null;
  try {
    const context = JSON.parse(fs.readFileSync(contextPath, 'utf-8'));
    if (context && context.schema_version === 'business-category-context-v1' && context.status === 'resolved') return context;
  } catch (_error) {
    return null;
  }
  return null;
}

function categoryContextMatchesRequest(context, requestedName) {
  const requested = normalizeCategoryText(requestedName);
  if (!context || !requested) return Boolean(context);
  const accepted = categoryAliases(context.requested_name, context.canonical_name, context.aliases)
    .map(normalizeCategoryText)
    .filter(Boolean);
  return accepted.includes(requested);
}

function categoryAliases(...values) {
  const aliases = [];
  for (const value of values.flat()) {
    const text = String(value || '').trim();
    if (text && !aliases.includes(text)) aliases.push(text);
  }
  return aliases;
}

function persistBusinessCategoryContext(node, resolution, existingContext = null) {
  if (!resolution || resolution.status !== 'resolved') return existingContext;
  const requestedName = String(resolution.requested_name || existingContext && existingContext.requested_name || '').trim();
  const canonicalName = String(
    resolution.canonical_name
    || resolution.category_name
    || existingContext && existingContext.canonical_name
    || requestedName
  ).trim();
  const categoryId = String(resolution.category_id || existingContext && existingContext.category_id || '').trim();
  if (!canonicalName && !categoryId) return existingContext;
  let sourceRevision = Number(existingContext && existingContext.source_revision || 0);
  if (String(node && node.id || '') === 'collect_top_products') {
    const confirmedPath = path.join(ARTIFACTS_DIR, 'collect_top_products.confirmed_data_table.json');
    if (fs.existsSync(confirmedPath)) {
      try {
        const confirmed = JSON.parse(fs.readFileSync(confirmedPath, 'utf-8'));
        sourceRevision = Number(confirmed.workspace_revision || sourceRevision || 0);
      } catch (_error) {
        sourceRevision = Number(sourceRevision || 0);
      }
    }
  }
  const context = {
    schema_version: 'business-category-context-v1',
    requested_name: requestedName,
    canonical_name: canonicalName,
    category_id: categoryId,
    aliases: categoryAliases(
      canonicalName,
      requestedName,
      existingContext && existingContext.aliases,
      resolution.aliases,
      (Array.isArray(resolution.alternatives) ? resolution.alternatives : []).map(item => item && (item.canonical_name || item.category_name || item.name))
    ),
    status: 'resolved',
    source_node_id: String(existingContext && existingContext.source_node_id || node && node.id || ''),
    source_revision: sourceRevision,
    evidence_ref: String(resolution.evidence_ref || existingContext && existingContext.evidence_ref || ''),
    updated_at: new Date().toISOString(),
  };
  persistJsonArtifact(BUSINESS_CATEGORY_CONTEXT_REF, context);
  return context;
}

function keywordCategoryCandidates(categoryContext, categoryResolution, requestedCategory) {
  return categoryAliases(
    categoryContext && categoryContext.canonical_name,
    categoryResolution && categoryResolution.canonical_name,
    categoryResolution && categoryResolution.category_name,
    requestedCategory,
    categoryContext && categoryContext.requested_name,
    categoryContext && categoryContext.aliases
  );
}

function keywordRootTerms(value) {
  const source = Array.isArray(value) ? value : String(value || '').split(/[、,，;；/|\s]+/);
  return categoryAliases(source.map(item => String(item || '').trim()).filter(Boolean));
}

function keywordMetricNumber(value) {
  const normalized = String(value ?? '').replace(/,/g, '').replace(/%$/, '').trim();
  const number = Number(normalized);
  if (!Number.isFinite(number)) return null;
  return String(value ?? '').trim().endsWith('%') ? number / 100 : number;
}

function keywordRootTop20Artifact(node, dataTable, createdAt) {
  if (!isKeywordAnalysisNode(node)) return null;
  const groups = new Map();
  for (const row of Array.isArray(dataTable && dataTable.rows) ? dataTable.rows : []) {
    const terms = keywordRootTerms(row.root_terms ?? row['词根']);
    for (const term of terms) {
      if (!groups.has(term)) {
        groups.set(term, {
          root_term: term,
          keyword_count: 0,
          search_popularity_total: 0,
          search_popularity_samples: 0,
          growth_rate_total: 0,
          growth_rate_samples: 0,
          demand_types: {},
          keywords: [],
        });
      }
      const group = groups.get(term);
      group.keyword_count += 1;
      const keyword = String(row.keyword ?? row.keywords ?? '').trim();
      if (keyword && !group.keywords.includes(keyword)) group.keywords.push(keyword);
      const popularity = keywordMetricNumber(row.search_popularity);
      if (popularity !== null) {
        group.search_popularity_total += popularity;
        group.search_popularity_samples += 1;
      }
      const growth = keywordMetricNumber(row.growth_rate);
      if (growth !== null) {
        group.growth_rate_total += growth;
        group.growth_rate_samples += 1;
      }
      const demandType = String(row.demand_type ?? row['需求类型'] ?? '').trim();
      if (demandType) group.demand_types[demandType] = Number(group.demand_types[demandType] || 0) + 1;
    }
  }
  const rows = Array.from(groups.values())
    .map(group => ({
      root_term: group.root_term,
      keyword_count: group.keyword_count,
      search_popularity_total: group.search_popularity_samples > 0 ? group.search_popularity_total : null,
      growth_rate_average: group.growth_rate_samples > 0 ? group.growth_rate_total / group.growth_rate_samples : null,
      demand_type_distribution: group.demand_types,
      sample_keywords: group.keywords.slice(0, 10),
    }))
    .sort((left, right) => (
      Number(right.search_popularity_total || 0) - Number(left.search_popularity_total || 0)
      || right.keyword_count - left.keyword_count
      || left.root_term.localeCompare(right.root_term, 'zh-CN')
    ))
    .slice(0, 20);
  return {
    schema_version: 'keyword-root-top20-v1',
    node_id: node.id,
    source_table_ref: `artifacts/${node.id}.data_table.json`,
    source_execution_id: String(dataTable && dataTable.execution_id || ''),
    status: rows.length > 0 ? 'draft_ready' : 'agent_enrichment_pending',
    rows,
    human_confirmation: { status: 'unconfirmed' },
    created_at: createdAt,
  };
}

function persistConfirmedDataTableDerivatives({ node_id: nodeId, workspace_revision: workspaceRevision, artifact, confirmation }) {
  const config = readConfig();
  const node = (Array.isArray(config.nodes) ? config.nodes : []).find(item => String(item && item.id || '') === String(nodeId || ''));
  if (!node || !isKeywordAnalysisNode(node)) return {};
  const createdAt = String(confirmation && confirmation.confirmed_at || new Date().toISOString());
  const rootArtifact = keywordRootTop20Artifact(node, {
    ...artifact,
    execution_id: String(artifact && artifact.base_execution_id || artifact && artifact.confirmed_at || createdAt),
  }, createdAt);
  if (!rootArtifact) return {};
  rootArtifact.source_table_ref = String(confirmation && confirmation.artifact_ref || `artifacts/${nodeId}.confirmed_data_table.json`);
  rootArtifact.source_revision = Number(workspaceRevision || 0);
  rootArtifact.status = rootArtifact.rows.length > 0 ? 'draft_ready' : 'agent_enrichment_pending';
  const ref = persistJsonArtifact(`artifacts/${nodeId}.keyword_root_top20.json`, rootArtifact);
  return { keyword_root_top20: rootArtifact, keyword_root_top20_ref: ref };
}

async function runDataAnalysisNode(node, payload, upstreamArtifacts) {
  let knownParams = { ...runKnownParams(payload, upstreamArtifacts) };
  const requestedCategoryInput = String(knownParams.category || knownParams.category_name || knownParams['分析类目'] || '');
  let categoryContext = loadBusinessCategoryContext();
  if (categoryContext && !categoryContextMatchesRequest(categoryContext, requestedCategoryInput)) categoryContext = null;
  if (isKeywordAnalysisNode(node) && !categoryContext && requestedCategoryInput) {
    const candidate = callCategoryCandidateResolver(knownParams, { category_name: requestedCategoryInput });
    if (!candidate.degraded && candidate.status === 'resolved' && (candidate.canonical_name || candidate.category_id)) {
      categoryContext = persistBusinessCategoryContext(node, {
        ...candidate,
        requested_name: requestedCategoryInput,
        category_name: String(candidate.canonical_name || requestedCategoryInput),
        status: 'resolved',
        evidence_ref: String(candidate.evidence_ref || ''),
      });
    }
  }
  if (isKeywordAnalysisNode(node) && categoryContext) {
    knownParams = {
      ...knownParams,
      requested_category: requestedCategoryInput || String(categoryContext.requested_name || ''),
      category: String(categoryContext.canonical_name || requestedCategoryInput),
      category_name: String(categoryContext.canonical_name || requestedCategoryInput),
      canonical_category: String(categoryContext.canonical_name || requestedCategoryInput),
      cid: String(categoryContext.category_id || knownParams.cid || ''),
      category_id: String(categoryContext.category_id || knownParams.category_id || ''),
    };
  }
  const topN = dataAnalysisTopN(payload);
  const coverageResult = dataAnalysisCoverageForRun(node, knownParams, payload);
  const createdAt = new Date().toISOString();
  if (!coverageResult.ok) {
    const result = {
      schema_version: 'data-analysis-execution-v1',
      node_id: node.id,
      status: 'degraded',
      known_params: knownParams,
      top_n: topN,
      execution_steps: [],
      api_execution_plan: [],
      data_table_ref: '',
      insight_draft_ref: '',
      execution_trace_ref: '',
      blocked_reasons: ['matcher_service_unavailable'],
      next_step: coverageResult.next_step || '请先修复 api_doc_matcher.service 或 API 文档索引。',
    };
    const traceRef = persistJsonArtifact(`evidence/${node.id}.execution_trace.json`, {
      schema_version: 'data-analysis-execution-trace-v1',
      node_id: node.id,
      created_at: createdAt,
      known_params: knownParams,
      field_coverage_ref: '',
      api_calls: [],
      pi_calls: [],
      blocked_reasons: result.blocked_reasons,
      artifact_refs: [],
      matcher_error: coverageResult.matcher_error || coverageResult.matcher_reason || '',
    });
    result.execution_trace_ref = traceRef;
    return result;
  }
  const fieldCoveragePlan = coveragePlanFromMappings(node, coverageResult.field_coverage_plan);
  let apiExecutionPlan = groupedApiPlansForCoverage(node, knownParams, fieldCoveragePlan, coverageResult.selected_api_asset_cards, payload)
    .map(plan => applyTopNToPlanParams(plan, topN))
    .sort((left, right) => {
      const priority = { topn_trade_total_primary: 0, growth_enrichment: 1, product_detail_enrichment: 2, general: 3 };
      return (priority[left.execution_role] ?? 9) - (priority[right.execution_role] ?? 9);
    });
  const dbStatus = dbAgentStatus();
  const liveEnabled = process.env.DBA_LIVE_PROBE === '1';
  const rowsByApi = new Map();
  const apiCalls = [];
  const piCalls = [];
  const blockedReasons = [];
  const categoryAttempts = [];
  let selectedCategoryName = '';
  let detailEnrichment = null;

  const requestedCategory = String(knownParams.requested_category || requestedCategoryInput || knownParams.category || knownParams.category_name || knownParams['分析类目'] || '');
  if (requestedCategory && apiExecutionPlan.some(plan => plan.category_scope !== 'unscoped')) {
    apiExecutionPlan = apiExecutionPlan.filter(plan => plan.category_scope !== 'unscoped');
  }
  if (apiExecutionPlan.length === 0) blockedReasons.push('no_source_api');
  const knownCategoryId = String(knownParams.cid || knownParams.category_id || knownParams.cate_id || knownParams.cat_id || '');
  let categoryResolution = categoryContext ? {
    schema_version: 'business-category-resolution-v2',
    provider: 'shared_business_category_context',
    requested_name: String(categoryContext.requested_name || requestedCategory),
    canonical_name: String(categoryContext.canonical_name || requestedCategory),
    category_name: String(categoryContext.canonical_name || requestedCategory),
    category_id: String(categoryContext.category_id || knownCategoryId),
    status: 'resolved',
    match_kind: 'upstream_verified_context',
    confidence: 1,
    evidence_sources: categoryContext.evidence_ref ? [{ evidence_ref: categoryContext.evidence_ref }] : [],
    alternatives: [],
    blocked_reason: '',
  } : {
    schema_version: 'business-category-resolution-v2',
    provider: 'api_doc_matcher',
    requested_name: requestedCategory,
    canonical_name: requestedCategory,
    category_name: requestedCategory,
    category_id: knownCategoryId,
    status: knownCategoryId ? 'resolved' : 'not_required',
    match_kind: knownCategoryId ? 'direct_id' : '',
    confidence: knownCategoryId ? 1 : 0,
    evidence_sources: [],
    alternatives: [],
    blocked_reason: '',
  };
  const categoryRequiredPlan = apiExecutionPlan.find(plan => plan.category_scope === 'category_id_required' && plan.request_param_binding_reason === 'category_id_required');
  if (categoryRequiredPlan) {
    const candidate = callCategoryCandidateResolver(knownParams, { category_name: requestedCategory });
    if (!candidate.degraded && candidate.status === 'resolved' && candidate.category_id) {
      categoryResolution = {
        ...candidate,
        category_name: candidate.canonical_name || requestedCategory,
        direction: 'name_to_id',
        status: liveEnabled ? 'pending_validation' : 'needs_validation',
        resolver_provider: 'api_doc_matcher',
        source_api_id: candidate.evidence_sources && candidate.evidence_sources[0] && candidate.evidence_sources[0].api_id || '',
      };
    } else if (liveEnabled && dbStatus.status === 'ok' && dbStatus.provider !== 'api_doc_index') {
      const resolved = resolveCategoryIdForPlan(node, categoryRequiredPlan, knownParams, topN, dbStatus);
      const resolverApiCalls = Array.isArray(resolved.api_calls)
        ? resolved.api_calls
        : resolved.api_call
          ? [resolved.api_call]
          : [];
      apiCalls.push(...resolverApiCalls);
      categoryResolution = {
        schema_version: 'business-category-resolution-v2',
        provider: 'api_doc_matcher',
        requested_name: requestedCategory,
        canonical_name: String(resolved.resolution.category_name || requestedCategory),
        category_name: String(resolved.resolution.category_name || requestedCategory),
        category_id: String(resolved.resolution.category_id || ''),
        status: resolved.resolved ? 'resolved' : 'blocked',
        match_kind: resolved.resolved ? 'resolver_api' : '',
        confidence: Number(resolved.resolution.confidence || 0),
        evidence_sources: [],
        alternatives: [],
        blocked_reason: resolved.resolution.blocked_reason || (resolved.resolved ? '' : 'category_resolution_required'),
        ...resolved.resolution,
      };
    } else {
      categoryResolution = {
        ...categoryResolution,
        status: 'blocked',
        blocked_reason: !liveEnabled ? 'live_probe_disabled' : candidate.reason || candidate.blocked_reason || 'category_resolution_required',
      };
    }

    if (categoryResolution.category_id) {
      knownParams = {
        ...knownParams,
        cid: String(categoryResolution.category_id),
        category_id: String(categoryResolution.category_id),
        canonical_category: String(categoryResolution.canonical_name || requestedCategory),
      };
      apiExecutionPlan = groupedApiPlansForCoverage(node, knownParams, fieldCoveragePlan, coverageResult.selected_api_asset_cards, payload)
        .map(plan => applyTopNToPlanParams(plan, topN))
        .sort((left, right) => {
          const priority = { topn_trade_total_primary: 0, growth_enrichment: 1, product_detail_enrichment: 2, general: 3 };
          return (priority[left.execution_role] ?? 9) - (priority[right.execution_role] ?? 9);
        });
      if (requestedCategory && apiExecutionPlan.some(plan => plan.category_scope !== 'unscoped')) {
        apiExecutionPlan = apiExecutionPlan.filter(plan => plan.category_scope !== 'unscoped');
      }
    }
  }
  for (const plan of apiExecutionPlan) {
    if (plan.category_scope === 'category_id_required') {
      plan.category_resolution = { ...categoryResolution };
      if (categoryResolution.status === 'blocked') {
        plan.blocked_reason = categoryResolution.blocked_reason || 'category_resolution_required';
        plan.request_param_binding_reason = plan.blocked_reason;
      }
    }
  }
  if (categoryResolution.status === 'blocked' && categoryResolution.blocked_reason) {
    blockedReasons.push(categoryResolution.blocked_reason);
  }

  const hasTradeTotalPrimaryPlan = apiExecutionPlan.some(plan => plan.execution_role === 'topn_trade_total_primary');
  let selectedPrimaryMonth = '';
  for (const plan of apiExecutionPlan) {
    if (plan.source_path_missing_fields.length > 0) blockedReasons.push('source_path_missing');
    if (!liveEnabled) {
      if (plan.missing_required_params.length > 0) blockedReasons.push('missing_required_params');
      if (plan.request_param_binding_reason) blockedReasons.push(plan.request_param_binding_reason);
      plan.status = 'blocked';
      plan.blocked_reason = 'live_probe_disabled';
      blockedReasons.push('live_probe_disabled');
      continue;
    }
    if (dbStatus.status !== 'ok' || dbStatus.provider === 'api_doc_index') {
      if (plan.missing_required_params.length > 0) blockedReasons.push('missing_required_params');
      if (plan.request_param_binding_reason) blockedReasons.push(plan.request_param_binding_reason);
      plan.status = 'blocked';
      plan.blocked_reason = dbStatus.provider === 'api_doc_index' ? 'live_probe_requires_db_agent_worker' : dbStatus.reason;
      blockedReasons.push(plan.blocked_reason);
      continue;
    }
    if (plan.missing_required_params.length > 0) blockedReasons.push('missing_required_params');
    if (plan.request_param_binding_reason) blockedReasons.push(plan.request_param_binding_reason);
    if (plan.status === 'blocked') {
      if (!plan.blocked_reason && plan.request_param_binding_reason) plan.blocked_reason = plan.request_param_binding_reason;
      if (plan.blocked_reason) blockedReasons.push(plan.blocked_reason);
      continue;
    }
    if (plan.execution_role === 'growth_enrichment' && hasTradeTotalPrimaryPlan && !selectedPrimaryMonth) {
      plan.status = 'blocked';
      plan.blocked_reason = 'primary_trade_total_no_data';
      blockedReasons.push(plan.blocked_reason);
      rowsByApi.set(plan.api_id, []);
      continue;
    }
    if (plan.execution_role === 'product_detail_enrichment') {
      const primaryPlan = apiExecutionPlan.find(item => item.execution_role === 'topn_trade_total_primary');
      const primaryRows = primaryPlan ? rowsByApi.get(primaryPlan.api_id) || [] : [];
      const identities = [];
      for (const row of primaryRows) {
        const identity = productIdentityForRow(row);
        if (identity && !identities.includes(identity)) identities.push(identity);
        if (identities.length >= Math.min(topN, 50)) break;
      }
      if (identities.length === 0) {
        plan.status = 'blocked';
        plan.blocked_reason = 'primary_product_ids_missing';
        blockedReasons.push(plan.blocked_reason);
        rowsByApi.set(plan.api_id, []);
        continue;
      }
      const targetMonth = selectedPrimaryMonth || '';
      const dataSourceCandidates = detailDataSourceCandidates(plan);
      const responseDateField = detailResponseDateField(plan);
      const topPerItem = responseDateField ? 20 : 1;
      const finalRowsById = new Map();
      const finalStatusesById = new Map();
      const attemptedSourcesById = new Map(identities.map(identity => [identity, []]));
      const sourceAttempts = [];
      let pendingIdentities = [...identities];
      for (let sourceIndex = 0; sourceIndex < dataSourceCandidates.length && pendingIdentities.length > 0; sourceIndex += 1) {
        const dataSource = dataSourceCandidates[sourceIndex];
        const request = {
          tool: 'probe_api_batch',
          args: {
            api_id: plan.api_id,
            items: pendingIdentities.map(identity => ({
              correlation_id: identity,
              params: { ...(plan.params || {}), goods_id: identity, data_source: dataSource },
            })),
            concurrency: 5,
            retry: 1,
            timeout_ms: 8000,
            top_per_item: topPerItem,
          },
        };
        const workerResponse = callDbAgentWorker(request);
        const batch = detailBatchRows(workerResponse, { target_month: targetMonth, data_source: dataSource });
        const rowById = rowsByProductIdentity(batch.rows);
        const statusById = new Map(batch.item_statuses.map(item => [String(item.correlation_id || ''), item]));
        const nextPending = [];
        for (const identity of pendingIdentities) {
          const attempted = attemptedSourcesById.get(identity) || [];
          attempted.push(dataSource);
          attemptedSourcesById.set(identity, attempted);
          const itemStatus = statusById.get(identity) || {
            correlation_id: identity,
            status: workerResponse && workerResponse.ok ? 'empty' : 'failed',
            attempts: 0,
            rows_returned: 0,
            available_rows: 0,
            data_source: dataSource,
            selected_data_month: '',
            temporal_status: 'not_available',
            response_date_field: '',
            request_debug: {},
            error: String(workerResponse && (workerResponse.reason || workerResponse.status) || 'detail_batch_failed'),
          };
          const canFallback = itemStatus.status === 'empty' && sourceIndex < dataSourceCandidates.length - 1;
          if (canFallback) {
            nextPending.push(identity);
            continue;
          }
          const row = rowById.get(identity);
          if (itemStatus.status === 'success' && row) finalRowsById.set(identity, row);
          finalStatusesById.set(identity, {
            ...itemStatus,
            attempted_data_sources: [...attempted],
            fallback_from: attempted.length > 1 ? attempted[0] : '',
          });
        }
        sourceAttempts.push({
          data_source: dataSource,
          requested: pendingIdentities.length,
          summary: batch.summary,
          worker_ok: Boolean(workerResponse && workerResponse.ok),
          worker_status: String(workerResponse && workerResponse.status || ''),
          worker_error: String(workerResponse && (workerResponse.error || workerResponse.reason) || ''),
        });
        pendingIdentities = nextPending;
      }
      for (const identity of identities) {
        if (finalStatusesById.has(identity)) continue;
        finalStatusesById.set(identity, {
          correlation_id: identity,
          status: 'empty',
          attempts: 0,
          rows_returned: 0,
          available_rows: 0,
          data_source: dataSourceCandidates[dataSourceCandidates.length - 1] || '',
          selected_data_month: '',
          temporal_status: 'not_available',
          response_date_field: '',
          request_debug: {},
          error: '',
          attempted_data_sources: attemptedSourcesById.get(identity) || [],
          fallback_from: '',
        });
      }
      const finalItemStatuses = identities.map(identity => finalStatusesById.get(identity));
      const finalRows = identities.map(identity => finalRowsById.get(identity)).filter(Boolean);
      const summary = { requested: identities.length, success: 0, empty: 0, failed: 0, identity_mismatch: 0 };
      for (const item of finalItemStatuses) {
        if (item.status === 'success') summary.success += 1;
        else if (item.status === 'empty') summary.empty += 1;
        else if (item.status === 'identity_mismatch') summary.identity_mismatch += 1;
        else summary.failed += 1;
      }
      const successfulSources = Array.from(new Set(finalItemStatuses
        .filter(item => item.status === 'success')
        .map(item => String(item.data_source || ''))
        .filter(Boolean)));
      const selectedDataSource = successfulSources.length === 1
        ? successfulSources[0]
        : successfulSources.length > 1
          ? 'mixed'
          : dataSourceCandidates[0] || '';
      const temporalAlignment = detailTemporalAlignment(finalItemStatuses, targetMonth);
      const combinedWorkerResponse = {
        ok: sourceAttempts.some(item => item.worker_ok),
        status: 'ok',
        payload: {
          kind: 'api_probe_batch_result',
          api_id: plan.api_id,
          summary,
          items: finalItemStatuses,
          selected_rows: finalRows,
          source_attempts: sourceAttempts,
        },
      };
      const evidenceRef = persistDbAgentEvidence(node.id, 'probe_api_batch', combinedWorkerResponse, knownParams, { apiId: plan.api_id });
      const called = combinedWorkerResponse.ok;
      plan.status = called ? 'called' : 'blocked';
      plan.blocked_reason = called ? '' : 'detail_batch_failed';
      plan.evidence_ref = evidenceRef;
      plan.rows_requested = identities.length;
      plan.rows_returned = finalRows.length;
      plan.rows_accepted = finalRows.length;
      plan.batch_summary = summary;
      plan.batch_item_statuses = finalItemStatuses;
      plan.selected_data_source = selectedDataSource;
      plan.data_sources_used = successfulSources;
      plan.data_source_attempts = sourceAttempts;
      plan.temporal_alignment = temporalAlignment;
      plan.params = { ...(plan.params || {}), data_source: selectedDataSource === 'mixed' ? dataSourceCandidates[0] : selectedDataSource };
      plan.request_param_mapping = (Array.isArray(plan.request_param_mapping) ? plan.request_param_mapping : []).map(item => {
        if (String(item && item.api_param || '').toLowerCase() !== 'data_source') return item;
        return { ...item, value: selectedDataSource, resolved_value: selectedDataSource, status: 'runtime_resolved', binding_method: 'detail_source_calibration' };
      });
      plan.scope_validation_status = 'inherited_from_primary';
      plan.scope_validation = { status: 'inherited_from_primary', reason: 'goods_id_join_to_category_verified_primary' };
      plan.request_debug = {
        tool: 'probe_api_batch',
        api_id: plan.api_id,
        requested_count: identities.length,
        concurrency: 5,
        retry: 1,
        top_per_item: topPerItem,
        selected_data_source: selectedDataSource,
        data_source_attempts: sourceAttempts,
        sample_requests: finalItemStatuses.slice(0, 5).map(item => item.request_debug),
      };
      if (!called) blockedReasons.push(plan.blocked_reason);
      rowsByApi.set(plan.api_id, finalRows);
      detailEnrichment = {
        api_id: plan.api_id,
        status: plan.status,
        summary,
        evidence_ref: evidenceRef,
        item_statuses: finalItemStatuses,
        selected_data_source: selectedDataSource,
        data_sources_used: successfulSources,
        data_source_attempts: sourceAttempts,
        temporal_alignment: temporalAlignment,
      };
      apiCalls.push({
        api_id: plan.api_id,
        execution_role: plan.execution_role,
        status: plan.status,
        evidence_ref: evidenceRef,
        rows_requested: identities.length,
        rows_returned: finalRows.length,
        batch_summary: summary,
        selected_data_source: selectedDataSource,
        temporal_alignment: temporalAlignment,
        request_debug: plan.request_debug,
      });
      continue;
    }
    const isMonthly = String(plan.normalized_period && plan.normalized_period.grain || '') === 'month';
    const alignedMonth = plan.execution_role === 'growth_enrichment' ? selectedPrimaryMonth : '';
    const fallbackLimit = monthlyFallbackLimit(plan, alignedMonth);
    const dateAttempts = [];
    let request = null;
    let workerResponse = null;
    let rows = [];
    let requestDebug = {};
    const supportsKeywordCategoryName = isKeywordAnalysisNode(node)
      && (Array.isArray(plan.request_param_mapping) ? plan.request_param_mapping : [])
        .some(item => String(item && item.api_param || '') === 'tertiary_category');
    if (supportsKeywordCategoryName && !isMonthly) {
      const candidates = keywordCategoryCandidates(categoryContext, categoryResolution, requestedCategory);
      const planAttempts = [];
      for (const candidateName of candidates) {
        const attemptParams = { ...(plan.params || {}), tertiary_category: candidateName };
        request = dbAgentRequestForAction('probe_sample', node, { api_id: plan.api_id, params: attemptParams, top: plan.fetch_limit || topN }, knownParams);
        workerResponse = callDbAgentWorker(request);
        rows = rowsFromProbePayload(workerResponse && workerResponse.payload);
        requestDebug = requestDebugFromProbePayload(workerResponse && workerResponse.payload);
        const attempt = {
          attempt: planAttempts.length + 1,
          api_id: plan.api_id,
          category_name: candidateName,
          status: workerResponse && workerResponse.ok ? (rows.length > 0 ? 'success' : 'empty') : 'blocked',
          rows_returned: rows.length,
          reason: workerResponse && workerResponse.ok ? (rows.length > 0 ? 'rows_returned' : 'api_returned_no_rows') : String(workerResponse && (workerResponse.reason || workerResponse.status) || 'probe_failed'),
          request_debug: requestDebug,
        };
        planAttempts.push(attempt);
        categoryAttempts.push(attempt);
        plan.params = attemptParams;
        if (!workerResponse || workerResponse.ok === false) break;
        if (rows.length > 0) {
          if (!selectedCategoryName) selectedCategoryName = candidateName;
          break;
        }
      }
      plan.category_attempts = planAttempts;
      plan.selected_category_name = rows.length > 0 ? String(plan.params.tertiary_category || '') : '';
    } else {
      for (let attemptIndex = 0; attemptIndex <= fallbackLimit; attemptIndex += 1) {
        const attemptParams = isMonthly
          ? monthlyAttemptParams(plan, attemptIndex, alignedMonth)
          : { ...(plan.params || {}) };
        request = dbAgentRequestForAction('probe_sample', node, { api_id: plan.api_id, params: attemptParams, top: plan.fetch_limit || topN }, knownParams);
        workerResponse = callDbAgentWorker(request);
        rows = rowsFromProbePayload(workerResponse && workerResponse.payload);
        requestDebug = requestDebugFromProbePayload(workerResponse && workerResponse.payload);
        plan.params = attemptParams;
        if (isMonthly) {
          dateAttempts.push({
            attempt: attemptIndex + 1,
            start_date: String(attemptParams.start_date || ''),
            end_date: String(attemptParams.end_date || ''),
            rows_returned: rows.length,
            status: workerResponse && workerResponse.ok ? 'ok' : 'blocked',
            reason: workerResponse && (workerResponse.reason || workerResponse.status) || '',
            request_debug: requestDebug,
          });
        }
        if (!workerResponse || workerResponse.ok === false || rows.length > 0 || attemptIndex >= fallbackLimit) break;
      }
    }
    if (isMonthly) {
      plan.date_attempts = dateAttempts;
      plan.request_param_mapping = (Array.isArray(plan.request_param_mapping) ? plan.request_param_mapping : []).map(item => (
        Object.prototype.hasOwnProperty.call(plan.params, item.api_param)
          ? { ...item, value: plan.params[item.api_param] }
          : item
      ));
    }
    const evidenceRef = persistDbAgentEvidence(node.id, 'probe_sample', workerResponse, knownParams, { apiId: plan.api_id });
    const scopeValidation = validateRowsForCategoryScope(plan, rows, categoryResolution);
    const acceptedRows = scopeValidation.accepted_rows;
    if (isMonthly && acceptedRows.length > 0) {
      plan.selected_data_month = String(plan.params.start_date || plan.params.end_date || '');
      if (plan.execution_role === 'topn_trade_total_primary') selectedPrimaryMonth = plan.selected_data_month;
    }
    plan.scope_validation_status = scopeValidation.status;
    plan.scope_validation = {
      status: scopeValidation.status,
      reason: scopeValidation.reason,
      matched_rows: scopeValidation.matched_rows,
      rejected_rows: scopeValidation.rejected_rows,
    };
    if (scopeValidation.status === 'matched' && categoryResolution.status === 'pending_validation') {
      categoryResolution = {
        ...categoryResolution,
        status: 'resolved',
        verification_api_id: plan.api_id,
        verification_evidence_ref: evidenceRef,
        verification: plan.scope_validation,
      };
      plan.category_resolution = { ...categoryResolution };
    }
    const canPersistRows = scopeValidation.status === 'matched'
      || scopeValidation.status === 'request_bound'
      || (!requestedCategory && scopeValidation.status === 'unverified');
    const artifact = workerResponse && workerResponse.ok && canPersistRows ? persistDbAgentArtifact(node, {
      ...workerResponse,
      payload: {
        ...(workerResponse.payload || {}),
        response: { top: acceptedRows },
      },
    }, evidenceRef) : null;
    plan.evidence_ref = evidenceRef;
    plan.artifact_ref = artifact && artifact.artifact_path || '';
    plan.rows_returned = rows.length;
    plan.rows_accepted = acceptedRows.length;
    plan.request_debug = requestDebug;
    plan.status = workerResponse && workerResponse.ok ? 'called' : 'blocked';
    if (!workerResponse || workerResponse.ok === false) {
      plan.blocked_reason = workerResponse && (workerResponse.reason || workerResponse.status) || 'probe_failed';
      blockedReasons.push(plan.blocked_reason);
    }
    if (scopeValidation.status === 'mismatch') {
      plan.status = 'blocked';
      plan.blocked_reason = 'category_scope_mismatch';
      blockedReasons.push('category_scope_mismatch');
    }
    rowsByApi.set(plan.api_id, acceptedRows);
    apiCalls.push({
      api_id: plan.api_id,
      status: plan.status,
      evidence_ref: evidenceRef,
      artifact_ref: plan.artifact_ref,
      rows_returned: rows.length,
      rows_accepted: acceptedRows.length,
      category_scope: plan.category_scope,
      scope_validation_status: plan.scope_validation_status,
      execution_role: plan.execution_role,
      selected_data_month: plan.selected_data_month || '',
      date_attempts: Array.isArray(plan.date_attempts) ? plan.date_attempts : [],
      category_attempts: Array.isArray(plan.category_attempts) ? plan.category_attempts : [],
      selected_category_name: plan.selected_category_name || '',
      request_debug: requestDebug,
    });
  }

  if (categoryResolution.status === 'pending_validation') {
    categoryResolution = {
      ...categoryResolution,
      status: 'needs_confirmation',
      blocked_reason: 'category_verification_failed',
    };
    blockedReasons.push('category_verification_failed');
  }
  const categoryResolutionRef = persistJsonArtifact(`evidence/${node.id}.category_resolution.json`, {
    ...categoryResolution,
    node_id: node.id,
    created_at: createdAt,
  });
  categoryResolution.evidence_ref = categoryResolutionRef;
  categoryContext = persistBusinessCategoryContext(node, categoryResolution, categoryContext);
  for (const plan of apiExecutionPlan) {
    if (plan.category_scope === 'category_id_required') plan.category_resolution = { ...categoryResolution };
  }

  const repairedFieldCoveragePlan = repairFieldCoverageWithRuntimeRows(fieldCoveragePlan, rowsByApi);
  const projection = projectRowsForApiFieldCoverage(rowsByApi, repairedFieldCoveragePlan, apiExecutionPlan);
  const projectedRows = projection.rows.slice(0, topN);
  if (projection.join_blocked_api_ids.length > 0) blockedReasons.push('join_blocked');
  if (projection.row_index_merged_api_ids.length > 0) blockedReasons.push('row_index_merge_requires_review');
  const fieldSources = buildFieldSources(repairedFieldCoveragePlan, apiExecutionPlan, projectedRows, {
    rowsByApi,
    primaryApiId: projection.primary_api_id,
    joinBlockedApiIds: projection.join_blocked_api_ids,
  });
  let riskSet = dataTableRiskSet(blockedReasons, fieldSources, projection);
  const derivedFields = derivedFieldPlanFromCoverage(repairedFieldCoveragePlan);
  const derivedEvidenceRows = derivedEvidenceRowsForProducts(rowsByApi, apiExecutionPlan, projection);
  const dataTable = {
    schema_version: 'data-table-draft-v1',
    node_id: node.id,
    execution_id: `exec-${Date.now()}`,
    title: outputTitlesForNode(node)[0] || node.name || node.id,
    status: 'draft',
    top_n: topN,
    pagination: {
      page_size: DATA_TABLE_PAGE_SIZE,
      total_rows: projectedRows.length,
      total_pages: Math.max(1, Math.ceil(projectedRows.length / DATA_TABLE_PAGE_SIZE)),
    },
    fields: nodeOutputFieldRequirements(node),
    rows: projectedRows,
    row_meta: projectedRows.map((row, index) => {
      const identity = String(projection.row_identities[index] || '');
      const identityPrefix = projection.identity_kind === 'keyword' ? 'keyword' : 'goods';
      return {
        row_id: identity ? `${identityPrefix}:${identity}` : `row:${createdAt}:${index + 1}`,
        source_identity: identity,
        source_index: index,
      };
    }),
    field_sources: fieldSources,
    derived_fields: derivedFields,
    category_resolution: categoryResolution,
    category_context: categoryContext || null,
    category_attempts: categoryAttempts,
    selected_category_name: selectedCategoryName,
    primary_api_id: projection.primary_api_id,
    join_blocked_api_ids: projection.join_blocked_api_ids,
    key_joined_api_ids: projection.key_joined_api_ids,
    join_keys: projection.join_keys,
    row_index_merged_api_ids: projection.row_index_merged_api_ids,
    merge_strategy: projection.merge_strategy,
    detail_enrichment: detailEnrichment,
    derived_evidence_rows: derivedEvidenceRows,
    risks: Array.from(riskSet),
    created_at: createdAt,
  };
  riskSet = dataTableRiskSet(blockedReasons, fieldSources, projection);
  dataTable.risks = Array.from(riskSet);
  const hasSuccessfulApiCall = apiCalls.some(item => item && item.status === 'called');
  const keywordEnrichmentPending = isKeywordAnalysisNode(node) && projectedRows.length > 0 && fieldSources.some(item => (
    PROTECTED_SEMANTIC_FIELD_NAMES.has(String(item.field_name || ''))
    && item.value_status !== 'present'
  ));
  const tableStatus = projectedRows.length > 0
    ? keywordEnrichmentPending
      ? 'agent_enrichment_pending'
      : (riskSet.size > 0 ? 'partial_data_table_ready' : 'data_table_ready')
    : hasSuccessfulApiCall && blockedReasons.length === 0
      ? 'empty_data'
      : 'blocked';
  const keywordRootArtifact = keywordRootTop20Artifact(node, dataTable, createdAt);
  const keywordRootTop20Ref = keywordRootArtifact
    ? persistJsonArtifact(`artifacts/${node.id}.keyword_root_top20.json`, keywordRootArtifact)
    : '';
  if (keywordRootTop20Ref) dataTable.keyword_root_top20_ref = keywordRootTop20Ref;
  const dataTableRef = persistJsonArtifact(`artifacts/${node.id}.data_table.json`, dataTable);
  const insightRequirements = node.analysis_node_view && node.analysis_node_view.insight_output_model
    ? node.analysis_node_view.insight_output_model.requirements || []
    : [];
  const insightAdvice = null;
  const insightDraft = {
    schema_version: 'insight-draft-v1',
    node_id: node.id,
    status: 'draft',
    requirements: insightRequirements,
    text: insightAdvice ? String(insightAdvice.text || '') : '',
    evidence_refs: insightAdvice && Array.isArray(insightAdvice.evidence_refs) ? insightAdvice.evidence_refs : [],
    evidence_fields: insightAdvice && Array.isArray(insightAdvice.evidence_fields) ? insightAdvice.evidence_fields : [],
    risks: Array.from(new Set([...Array.from(riskSet), ...((insightAdvice && Array.isArray(insightAdvice.risks)) ? insightAdvice.risks : [])])),
    questions_for_user: insightAdvice && Array.isArray(insightAdvice.questions_for_user) ? insightAdvice.questions_for_user : [],
    human_confirmation: { status: 'unconfirmed' },
    created_at: createdAt,
  };
  const insightRef = persistJsonArtifact(`artifacts/${node.id}.insight_draft.json`, insightDraft);
  const finalStatus = tableStatus;
  const traceRef = persistJsonArtifact(`evidence/${node.id}.execution_trace.json`, {
    schema_version: 'data-analysis-execution-trace-v1',
    node_id: node.id,
    created_at: createdAt,
    known_params: knownParams,
    category_resolution: categoryResolution,
    category_context: categoryContext || null,
    category_attempts: categoryAttempts,
    selected_category_name: selectedCategoryName,
    field_coverage_ref: coverageResult.provider,
    api_calls: apiCalls,
    pi_calls: piCalls,
    blocked_reasons: Array.from(new Set(blockedReasons.filter(Boolean))),
    artifact_refs: [dataTableRef, insightRef, keywordRootTop20Ref].filter(Boolean),
  });
  return {
    schema_version: 'data-analysis-execution-v1',
    node_id: node.id,
    status: finalStatus,
    known_params: knownParams,
    upstream_artifacts: upstreamArtifacts,
    top_n: topN,
    execution_steps: [],
    api_execution_plan: apiExecutionPlan,
    category_resolution: categoryResolution,
    category_context: categoryContext || null,
    category_attempts: categoryAttempts,
    selected_category_name: selectedCategoryName,
    data_table_ref: dataTableRef,
    insight_draft_ref: insightRef,
    keyword_root_top20_ref: keywordRootTop20Ref,
    execution_trace_ref: traceRef,
    coverage_summary: coverageSummary(fieldCoveragePlan),
    field_sources: fieldSources,
    data_table_status: dataTable.status,
    data_table_rows_count: projectedRows.length,
    data_table_preview: dataTablePreview(dataTable, DATA_TABLE_PAGE_SIZE),
    primary_api_id: projection.primary_api_id,
    join_blocked_api_ids: projection.join_blocked_api_ids,
    key_joined_api_ids: projection.key_joined_api_ids,
    join_keys: projection.join_keys,
    row_index_merged_api_ids: projection.row_index_merged_api_ids,
    merge_strategy: projection.merge_strategy,
    detail_enrichment: detailEnrichment,
    risks: Array.from(riskSet),
    blocked_reasons: Array.from(new Set(blockedReasons.filter(Boolean))),
  };
}

function safeId(value) {
  const id = String(value || '');
  if (!/^[a-zA-Z0-9_.-]+$/.test(id)) return '';
  return id;
}

function collaborationNodeFromPath(config, pathname) {
  const nodeId = safeId(String(pathname || '').split('/')[3] || '');
  if (!nodeId) throw new CollaborationError(400, 'invalid_node_id');
  const node = nodeById(config, nodeId);
  if (!node) throw new CollaborationError(404, 'node_not_found', { node_id: nodeId });
  if (!isDataAnalysisNode(node)) throw new CollaborationError(400, 'data_analysis_node_required', { node_id: nodeId });
  return { nodeId, node };
}

function geneAnalysisNodeFromPath(config, pathname) {
  const nodeId = safeId(String(pathname || '').split('/')[3] || '');
  if (nodeId !== 'analyze_hot_product_genes') throw new GeneAnalysisError(400, 'gene_analysis_node_required');
  const node = nodeById(config, nodeId);
  if (!node) throw new GeneAnalysisError(404, 'node_not_found', { node_id: nodeId });
  return { nodeId, node };
}

function startGeneAnalysis(node) {
  geneAnalysisStore.sourceTable();
  const executionId = `gene-exec-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const task = geneAnalysisStore.run(node, callPiGeneProfile, { execution_id: executionId });
  task.then(result => {
    broadcastEvent('node_done', { node_id: node.id, result, timestamp: new Date().toISOString() });
  }).catch(error => {
    broadcastEvent('node_error', { node_id: node.id, error: String(error.code || error.message || error), timestamp: new Date().toISOString() });
  });
  return {
    response: {
      schema_version: 'hot-product-gene-analysis-start-v1',
      status: 'running',
      node_id: node.id,
      execution_id: executionId,
    },
    task,
  };
}

async function handleGeneAnalysisApi(req, res, pathname, config) {
  try {
    const { nodeId, node } = geneAnalysisNodeFromPath(config, pathname);
    if (req.method === 'POST' && /\/run$/.test(pathname)) {
      const started = startGeneAnalysis(node);
      started.task.catch(error => console.error(`Gene analysis ${started.response.execution_id} failed:`, error.message || error));
      sendJson(res, 202, started.response);
      return;
    }
    if (req.method === 'GET' && /\/gene-analysis$/.test(pathname)) {
      sendJson(res, 200, geneAnalysisStore.analysisResponse(nodeId));
      return;
    }
    if (req.method === 'POST' && /\/gene-analysis\/[^/]+\/confirm$/.test(pathname)) {
      sendJson(res, 200, geneAnalysisStore.confirm(nodeId, await parseJsonBody(req)));
      return;
    }
    if (req.method === 'POST' && /\/gene-analysis\/[^/]+\/cancel$/.test(pathname)) {
      const executionId = safeId(pathname.split('/')[5] || '');
      const snapshot = geneAnalysisStore.analysisResponse(nodeId).analysis;
      for (const profile of snapshot && snapshot.product_profiles || []) {
        if (profile.agent_status === 'running') cancelPiCall(`${executionId}:${profile.row_id}`);
      }
      sendJson(res, 200, geneAnalysisStore.cancel(nodeId, executionId));
      return;
    }
    if (req.method === 'POST' && /\/gene-analysis\/[^/]+\/retry$/.test(pathname)) {
      const executionId = safeId(pathname.split('/')[5] || '');
      const task = geneAnalysisStore.retry(node, executionId, callPiGeneProfile);
      task.then(result => broadcastEvent('node_done', { node_id: nodeId, result, timestamp: new Date().toISOString() }))
        .catch(error => broadcastEvent('node_error', { node_id: nodeId, error: String(error.code || error.message || error), timestamp: new Date().toISOString() }));
      sendJson(res, 202, { status: 'running', node_id: nodeId, parent_execution_id: executionId });
      return;
    }
    sendJson(res, 404, { error: 'not_found' });
  } catch (error) {
    if (error instanceof GeneAnalysisError) {
      sendJson(res, error.statusCode, { error: error.code, ...error.details });
      return;
    }
    throw error;
  }
}

async function handleCollaborationApi(req, res, pathname, config) {
  try {
    const { nodeId, node } = collaborationNodeFromPath(config, pathname);
    let response;
    let responseStatus = 200;
    if (req.method === 'GET' && /\/data-table-workspace$/.test(pathname)) {
      response = collaborationStore.workspaceResponse(nodeId);
    } else if (req.method === 'POST' && /\/data-table-workspace\/confirm$/.test(pathname)) {
      response = collaborationStore.confirmDataTable(nodeId, await parseJsonBody(req));
      if (nodeId === 'collect_top_products' && response && response.confirmation) {
        const context = loadBusinessCategoryContext();
        if (context) {
          persistJsonArtifact(BUSINESS_CATEGORY_CONTEXT_REF, {
            ...context,
            source_revision: Number(response.confirmation.workspace_revision || context.source_revision || 0),
            updated_at: new Date().toISOString(),
          });
        }
      }
    } else if (req.method === 'POST' && /\/data-table-workspace\/patch$/.test(pathname)) {
      response = collaborationStore.applyPatch(nodeId, await parseJsonBody(req));
    } else if (req.method === 'POST' && /\/data-table-workspace\/proposal$/.test(pathname)) {
      response = collaborationStore.storeProposal(nodeId, await parseJsonBody(req));
    } else if (req.method === 'POST' && /\/data-table-workspace\/undo$/.test(pathname)) {
      response = collaborationStore.undo(nodeId, await parseJsonBody(req));
    } else if (req.method === 'GET' && /\/insight-workspace$/.test(pathname)) {
      response = collaborationStore.insightResponse(nodeId, node);
    } else if (req.method === 'POST' && /\/insight-workspace\/patch$/.test(pathname)) {
      response = collaborationStore.patchInsight(nodeId, node, await parseJsonBody(req));
    } else if (req.method === 'POST' && /\/insight-workspace\/confirm$/.test(pathname)) {
      response = collaborationStore.confirmInsight(nodeId, node, await parseJsonBody(req));
    } else if (req.method === 'GET' && /\/agent-thread$/.test(pathname)) {
      response = collaborationStore.threadResponse(nodeId);
    } else if (req.method === 'POST' && /\/agent-thread\/batches$/.test(pathname)) {
      const payload = await parseJsonBody(req);
      const batchCallAgent = (targetNode, targetPayload, runtime) => callPiAgent(targetNode, targetPayload, { ...runtime, skip_status_probe: true });
      const started = collaborationStore.startAgentBatch(nodeId, node, payload, batchCallAgent);
      response = started.response;
      responseStatus = 202;
      started.task.catch(error => console.error(`Agent batch ${response.batch_id} failed:`, error.message || error));
    } else if (req.method === 'GET' && /\/agent-thread\/batches\/[^/]+$/.test(pathname)) {
      response = collaborationStore.agentBatchResponse(nodeId, safeId(pathname.split('/')[6] || ''));
    } else if (req.method === 'POST' && /\/agent-thread\/batches\/[^/]+\/apply$/.test(pathname)) {
      response = collaborationStore.applyAgentBatch(nodeId, safeId(pathname.split('/')[6] || ''), await parseJsonBody(req));
    } else if (req.method === 'POST' && /\/agent-thread\/batches\/[^/]+\/cancel$/.test(pathname)) {
      const batchId = safeId(pathname.split('/')[6] || '');
      response = collaborationStore.cancelAgentBatch(nodeId, batchId);
      for (const callId of response.call_ids || []) cancelPiCall(callId);
    } else if (req.method === 'POST' && /\/agent-thread\/batches\/[^/]+\/retry$/.test(pathname)) {
      const batchId = safeId(pathname.split('/')[6] || '');
      const batchCallAgent = (targetNode, targetPayload, runtime) => callPiAgent(targetNode, targetPayload, { ...runtime, skip_status_probe: true });
      const retried = collaborationStore.retryAgentBatch(nodeId, node, batchId, batchCallAgent);
      response = retried.response;
      responseStatus = 202;
      retried.task.catch(error => console.error(`Agent batch retry ${batchId} failed:`, error.message || error));
    } else if (req.method === 'POST' && /\/agent-thread\/context$/.test(pathname)) {
      response = collaborationStore.attachThreadContext(nodeId, await parseJsonBody(req));
    } else if (req.method === 'POST' && /\/agent-thread\/model$/.test(pathname)) {
      const payload = await parseJsonBody(req);
      const allowedModels = new Set(piModelOptions(piProcessEnv()).map(item => item.model));
      if (!allowedModels.has(String(payload.preferred_model || ''))) throw new CollaborationError(400, 'preferred_model_unsupported');
      response = collaborationStore.setThreadModel(nodeId, payload);
    } else if (req.method === 'POST' && /\/agent-thread\/query$/.test(pathname)) {
      const payload = await parseJsonBody(req);
      if (payload.async === true) {
        const started = collaborationStore.startThreadQuery(nodeId, node, payload, callPiAgent);
        response = started.response;
        responseStatus = 202;
        started.task.catch(error => console.error(`Agent call ${response.call_id} failed:`, error.message || error));
      } else {
        response = await collaborationStore.queryThread(nodeId, node, payload, callPiAgent);
      }
    } else if (req.method === 'GET' && /\/agent-thread\/calls\/[^/]+$/.test(pathname)) {
      response = collaborationStore.agentCallResponse(nodeId, safeId(pathname.split('/')[6] || ''));
    } else if (req.method === 'POST' && /\/agent-thread\/calls\/[^/]+\/cancel$/.test(pathname)) {
      const callId = safeId(pathname.split('/')[6] || '');
      const cancelled = cancelPiCall(callId);
      response = { ok: cancelled, call_id: callId, status: cancelled ? 'cancelling' : 'not_running' };
    } else if (req.method === 'POST' && /\/agent-thread\/action$/.test(pathname)) {
      response = collaborationStore.actOnThread(nodeId, node, await parseJsonBody(req));
    } else {
      sendJson(res, 404, { error: 'not_found' });
      return;
    }
    sendJson(res, responseStatus, response);
  } catch (error) {
    if (error instanceof CollaborationError) {
      sendJson(res, error.statusCode, { error: error.code, ...error.details });
      return;
    }
    throw error;
  }
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function enginePath() {
  return firstExisting(
    [path.join(__dirname, 'engine', 'rule_engine.py'), path.join(SHELL_ROOT, 'engine', 'rule_engine.py')],
    path.join(SHELL_ROOT, 'engine', 'rule_engine.py'),
  );
}

function evalRule(ruleId, inputs) {
  // Call Python rule engine via subprocess
  const { spawnSync } = require('child_process');
  const ENGINE_PATH = enginePath();

  const request = JSON.stringify({ rule_id: ruleId, inputs: inputs || {} });

  const result = spawnSync('python3', [ENGINE_PATH], {
    input: request,
    encoding: 'utf-8',
    timeout: 5000,
  });

  if (result.error) {
    return {
      rule_id: ruleId,
      matched: false,
      output_label: '规则引擎调用失败',
      evidence: { error: 'spawn_failed', message: result.error.message },
    };
  }

  if (result.status !== 0) {
    return {
      rule_id: ruleId,
      matched: false,
      output_label: '规则引擎执行失败',
      evidence: { error: 'engine_failed', stderr: result.stderr, exit_code: result.status },
    };
  }

  try {
    return JSON.parse(result.stdout);
  } catch (parseError) {
    return {
      rule_id: ruleId,
      matched: false,
      output_label: '规则引擎返回格式错误',
      evidence: { error: 'parse_failed', stdout: result.stdout, message: parseError.message },
    };
  }
}

function renderAggregate(config, payload) {
  // Numbers gatekeeper: scan narrative for forbidden patterns
  const narrative = payload.narrative || '';
  const forbiddenPatterns = [
    /\d+\s*%/,                    // percentages: 30%
    /\d+\.\d+/,                   // decimals: 3.14
    /[¥$￥]\s*\d+/,               // currency: $100, ¥50
    /\d+\s*(元|美元|块|万|亿)/,    // Chinese currency units
    /\d{1,3}(,\d{3})+/,           // thousands separator: 1,000
    /GMV|销量|增速|增长率/,       // business metrics keywords
  ];
  
  for (const pattern of forbiddenPatterns) {
    if (pattern.test(String(narrative))) {
      return { 
        error: 'llm_safety_violation', 
        message: 'Narrative contains forbidden numbers or metrics',
        violated_pattern: pattern.source,
      };
    }
  }
  
  const aggregate = config.aggregate || {};
  const title = aggregate.title || aggregate.node_id || 'Final Report';
  const outputs = Array.isArray(payload.rule_outputs) ? payload.rule_outputs : [];
  
  // Build markdown report
  const lines = [
    `# ${title}`,
    '',
    '## 执行摘要',
    '',
    narrative || '暂无执行摘要。',
    '',
    '## 规则评估结果',
    '',
  ];
  
  // Add rule outputs table
  if (outputs.length > 0) {
    lines.push('| 规则 | 结论 | 分数 | 匹配 |');
    lines.push('| --- | --- | --- | --- |');
    
    for (const item of outputs) {
      const ruleId = item.rule_id || '';
      const label = item.output_label || '';
      const score = item.score !== null && item.score !== undefined ? item.score : '-';
      const matched = item.matched ? '✓' : '✗';
      lines.push(`| ${ruleId} | ${label} | ${score} | ${matched} |`);
    }
  } else {
    lines.push('暂无规则评估结果。');
  }
  
  lines.push('');
  lines.push('---');
  lines.push('');
  lines.push(`*报告生成时间：${new Date().toISOString()}*`);
  
  return { report_markdown: lines.join('\n') };
}

function validateActionRequest(action) {
  const type = String(action.type || '');
  if (type === 'rerun_node') {
    const nodeId = safeId(action.node_id || '');
    if (!nodeId) return { ok: false, reason: 'invalid_node_id' };
    return { ok: true, route: 'rerun_node', node_id: nodeId };
  }
  if (type === 'patch_app') {
    return validatePatchTargets(action, targetPath => {
      const parts = String(targetPath || '').split('/');
      if (parts.length < 3 || parts[0] !== 'generated_apps') return false;
      if (parts.some(part => part === '' || part === '.' || part === '..')) return false;
      return parts[2] === 'app.config.json' || (parts.length >= 4 && parts[2] === 'custom');
    });
  }
  if (type === 'patch_artifact') {
    return validatePatchTargets(action, targetPath => {
      const parts = String(targetPath || '').split('/');
      return parts.length >= 3 && parts[0] === 'artifacts' && !parts.some(part => part === '' || part === '.' || part === '..');
    });
  }
  return { ok: false, reason: 'unsupported_action_type' };
}

function validatePatchTargets(action, predicate) {
  const patches = Array.isArray(action.patches) ? action.patches : [];
  if (patches.length === 0) return { ok: false, reason: 'missing_patches' };
  for (const patch of patches) {
    if (!predicate(patch.target_path)) return { ok: false, reason: 'patch_out_of_scope' };
  }
  return { ok: true, route: action.type };
}

async function handleApi(req, res, pathname) {
  try {
    const config = readConfig();
    if (cachedVersionError) {
      sendJson(res, 412, cachedVersionError);
      return;
    }
    
    // Health check
    if (req.method === 'GET' && pathname === '/api/health') {
      // Check Python engine availability
      const { spawnSync } = require('child_process');
      const ENGINE_PATH = enginePath();
      let engineStatus = 'unknown';
      let engineError = null;
      
      try {
        const testResult = spawnSync('python3', [ENGINE_PATH], {
          input: JSON.stringify({ rule_id: 'strong_hot_gene', inputs: { topic_hot: 65, market_hot: 55 } }),
          encoding: 'utf-8',
          timeout: 3000,
        });
        
        if (testResult.error) {
          engineStatus = 'unavailable';
          engineError = testResult.error.message;
        } else if (testResult.status !== 0) {
          engineStatus = 'error';
          engineError = testResult.stderr || 'non_zero_exit';
        } else {
          try {
            JSON.parse(testResult.stdout);
            engineStatus = 'ok';
          } catch {
            engineStatus = 'invalid_output';
            engineError = 'json_parse_failed';
          }
        }
      } catch (error) {
        engineStatus = 'check_failed';
        engineError = error.message;
      }
      
      const health = {
        status: engineStatus === 'ok' ? 'ok' : 'degraded',
        shell_kind: config.shell_kind,
        shell_version: config.shell_version,
        app_slug: config.app_slug,
        config_loaded: true,
        nodes_count: Array.isArray(config.nodes) ? config.nodes.length : 0,
        python_engine: {
          status: engineStatus,
          error: engineError,
        },
        timestamp: new Date().toISOString(),
      };
      sendJson(res, 200, health);
      return;
    }
    
    // Get app config
    if (req.method === 'GET' && pathname === '/api/config') {
      sendJson(res, 200, config);
      return;
    }

    if (req.method === 'GET' && pathname === '/api/db-agent/status') {
      sendJson(res, 200, dbAgentStatus());
      return;
    }

    if (req.method === 'GET' && pathname === '/api/pi-agent/status') {
      sendJson(res, 200, piAgentStatus());
      return;
    }

    if (/^\/api\/nodes\/analyze_hot_product_genes\/(run|gene-analysis(?:\/[^/]+\/(?:retry|cancel|confirm))?)$/.test(pathname)) {
      await handleGeneAnalysisApi(req, res, pathname, config);
      return;
    }

    if (/^\/api\/nodes\/[^/]+\/(data-table-workspace|insight-workspace|agent-thread)(?:\/(patch|proposal|undo|confirm|context|query|action|model)|\/calls\/[^/]+(?:\/cancel)?|\/batches(?:\/[^/]+(?:\/(apply|cancel|retry))?)?)?$/.test(pathname)) {
      await handleCollaborationApi(req, res, pathname, config);
      return;
    }

    if (req.method === 'POST' && pathname === '/api/pi-agent/query') {
      const payload = await parseJsonBody(req);
      payload.legacy_compat = true;
      const nodeId = safeId(payload.node_id || '');
      if (!nodeId) {
        sendJson(res, 400, { ok: false, status: 'error', reason: 'invalid_node_id' });
        return;
      }
      const node = nodeById(config, nodeId);
      if (!node) {
        sendJson(res, 404, { ok: false, status: 'error', reason: 'node_not_found', node_id: nodeId });
        return;
      }
      const piResponse = await callPiAgent(node, payload);
      sendJson(res, 200, {
        ...piResponse,
        node_id: nodeId,
        action: 'data_mapping_advice',
      });
      return;
    }

    if (req.method === 'POST' && pathname === '/api/db-agent/query') {
      const status = dbAgentStatus();
      const payload = await parseJsonBody(req);
      const nodeId = safeId(payload.node_id || '');
      const action = String(payload.action || 'tool_plan');
      if (!nodeId) {
        sendJson(res, 400, { ok: false, status: 'error', reason: 'invalid_node_id' });
        return;
      }
      if (!DB_AGENT_ALLOWED_ACTIONS.has(action)) {
        sendJson(res, 400, { ok: false, status: 'blocked', reason: 'action_not_allowed', action });
        return;
      }
      const node = nodeById(config, nodeId);
      if (!node) {
        sendJson(res, 404, { ok: false, status: 'error', reason: 'node_not_found', node_id: nodeId });
        return;
      }
      const upstreamArtifacts = Array.isArray(payload.upstream_artifacts) ? payload.upstream_artifacts : [];
      const knownParams = {
        ...extractKnownParamsFromArtifacts(upstreamArtifacts),
        ...(payload.known_params && typeof payload.known_params === 'object' ? payload.known_params : {}),
      };
      if (action === 'save_field_mapping' || action === 'confirm_mapping') {
        const manualMapping = Array.isArray(payload.manual_response_field_mapping) ? payload.manual_response_field_mapping : [];
        const selectedApis = Array.isArray(payload.selected_apis) ? payload.selected_apis : [];
        const fieldCoveragePlan = Array.isArray(payload.field_coverage_plan) ? payload.field_coverage_plan : manualMapping;
        const evidenceRef = action === 'confirm_mapping'
          ? `evidence/${nodeId}.data_mapping_contract.json`
          : `evidence/${nodeId}.data_mapping_contract.draft.json`;
        const selectedApi = {
          api_id: String(payload.api_id || payload.selected_api && payload.selected_api.api_id || selectedApis[0] && selectedApis[0].api_id || ''),
          name: String(payload.selected_api && payload.selected_api.name || ''),
          method: String(payload.selected_api && payload.selected_api.method || ''),
          path: String(payload.selected_api && payload.selected_api.path || payload.api_id || ''),
          domain: String(payload.selected_api && payload.selected_api.domain || ''),
          capability: String(payload.selected_api && payload.selected_api.capability || ''),
        };
        const contract = buildDataMappingContract(node, knownParams, {
          status: action === 'confirm_mapping' ? 'confirmed' : 'suggested',
          selectedApi,
          selectedApis,
          fieldCoveragePlan,
          joinPlan: payload.join_plan && typeof payload.join_plan === 'object' ? payload.join_plan : undefined,
          manualResponseFieldMapping: manualMapping,
          humanDecisions: Array.isArray(payload.human_decisions) ? payload.human_decisions : [],
          evidenceRefs: [evidenceRef],
        });
        persistDataMappingContract(nodeId, contract, { draft: action !== 'confirm_mapping' });
        sendJson(res, 200, {
          ok: true,
          status: contract.status,
          node_id: nodeId,
          action,
          known_params: knownParams,
          evidence_ref: evidenceRef,
          payload: {
            selected_api: contract.selected_api,
            selected_apis: contract.selected_apis,
            output_field_requirements: contract.output_field_requirements,
            output_field_mapping_overlay: contract.output_field_mapping_overlay,
            field_coverage_plan: contract.field_coverage_plan,
            join_plan: contract.join_plan,
            coverage_summary: contract.coverage_summary,
            manual_response_field_mapping: contract.manual_response_field_mapping,
          },
          data_mapping_contract: contract,
        });
        return;
      }
      if (status.status !== 'ok') {
        sendJson(res, 200, {
          ok: false,
          status: 'degraded',
          reason: status.reason,
          node_id: nodeId,
          action,
          known_params: knownParams,
          data_mapping_contract: buildDataMappingContract(node, knownParams, { status: 'degraded' }),
          db_agent_status: status,
          });
          return;
      }
      if (status.provider === 'api_doc_index' || (hasLocalApiDocIndex() && DB_AGENT_MATCHER_ACTIONS.has(action))) {
        if (action === 'probe_sample') {
          sendJson(res, 200, {
            ok: false,
            status: 'blocked',
            reason: 'live_probe_requires_db_agent_worker',
            next_step: '本地 API 文档索引只支持 API/字段映射；样例取数需要配置 DB_ARCHAEOLOGIST_SPEC_PACK 并开启 DBA_LIVE_PROBE=1。',
            node_id: nodeId,
            action,
            known_params: knownParams,
            data_mapping_contract: buildDataMappingContract(node, knownParams, { status: 'blocked' }),
            db_agent_status: status,
          });
          return;
        }
        if (['understand_input', 'catalog', 'domain_apis', 'tool_plan'].includes(action)) {
          const responsePayload = matcherPayloadForNode(node, knownParams, payload);
          if (responsePayload.degraded) {
            sendJson(res, 200, matcherUnavailableResponse(node, nodeId, action, knownParams, status, responsePayload));
            return;
          }
          const response = {
            ok: responsePayload.selected_api_ids.length > 0,
            status: responsePayload.selected_api_ids.length > 0 ? 'suggested' : 'needs_input',
            provider: 'api_doc_index',
            node_id: nodeId,
            action,
            known_params: knownParams,
            payload: responsePayload,
            db_agent_status: status,
          };
          response.evidence_ref = persistDbAgentEvidence(nodeId, action, response, knownParams);
          response.data_mapping_contract = buildDataMappingContract(node, knownParams, {
            status: response.status,
            payload: responsePayload,
            toolPlan: { ok: response.ok, payload: responsePayload },
            apiMatchingStrategyResults: responsePayload.strategy_results,
            businessFieldCoverageMetrics: responsePayload.business_field_coverage_metrics,
            selectedApi: responsePayload.selected_api,
            selectedApis: responsePayload.selected_apis,
            selectedApiAssetCards: responsePayload.selected_api_asset_cards,
            apiResponseFieldCatalog: responsePayload.api_response_field_catalog,
            fieldCoveragePlan: responsePayload.field_coverage_plan,
            derivedFieldPlan: responsePayload.derived_field_plan,
            evidenceRefs: [response.evidence_ref],
          });
          sendJson(res, 200, response);
          return;
        }
        if (action === 'asset_card') {
          const apiId = String(payload.api_id || '').trim();
          if (!apiId) {
            sendJson(res, 200, {
              ok: false,
              status: 'needs_input',
              reason: 'api_id_required',
              next_step: '请先从候选 API 中选择一个，再查看返回字段。',
              node_id: nodeId,
              action,
              known_params: knownParams,
              data_mapping_contract: buildDataMappingContract(node, knownParams, { status: 'needs_input' }),
              db_agent_status: status,
            });
            return;
          }
          const payloadForContract = localAssetCardPayload(node, apiId);
          const found = Boolean(payloadForContract.selected_api_asset_card && payloadForContract.selected_api_asset_card.api_id);
          const response = {
            ok: found,
            status: found ? 'ok' : 'needs_input',
            provider: 'api_doc_index',
            node_id: nodeId,
            action,
            known_params: knownParams,
            payload: payloadForContract,
            db_agent_status: status,
          };
          response.evidence_ref = persistDbAgentEvidence(nodeId, action, response, knownParams);
          response.data_mapping_contract = buildDataMappingContract(node, knownParams, {
            status: found ? 'suggested' : 'needs_input',
            payload: payloadForContract,
            selectedApi: payloadForContract.selected_api,
            selectedApiAssetCard: payloadForContract.selected_api_asset_card,
            evidenceRefs: [response.evidence_ref],
          });
          sendJson(res, 200, response);
          return;
        }
        if (action === 'field_map') {
          const fieldMapPayload = matcherPayloadForNode(node, knownParams, payload);
          if (fieldMapPayload.degraded) {
            sendJson(res, 200, matcherUnavailableResponse(node, nodeId, action, knownParams, status, fieldMapPayload));
            return;
          }
          const response = {
            ok: true,
            status: fieldMapPayload.unmatched_required_fields.length > 0 ? 'needs_input' : 'ok',
            provider: 'api_doc_index',
            node_id: nodeId,
            action,
            known_params: knownParams,
            payload: fieldMapPayload,
            db_agent_status: status,
          };
          response.evidence_ref = persistDbAgentEvidence(nodeId, action, response, knownParams);
          response.data_mapping_contract = buildDataMappingContract(node, knownParams, {
            status: response.status,
            payload: fieldMapPayload,
            toolPlan: { ok: true, payload: fieldMapPayload },
            selectedApi: fieldMapPayload.selected_api,
            selectedApis: fieldMapPayload.selected_apis,
            selectedApiAssetCards: fieldMapPayload.selected_api_asset_cards,
            apiResponseFieldCatalog: fieldMapPayload.api_response_field_catalog,
            fieldCoveragePlan: fieldMapPayload.field_coverage_plan,
            derivedFieldPlan: fieldMapPayload.derived_field_plan,
            evidenceRefs: [response.evidence_ref],
          });
          sendJson(res, 200, response);
          return;
        }
        if (action === 'suggest_multi_api_mapping') {
          const responsePayload = matcherPayloadForNode(node, knownParams, payload);
          if (responsePayload.degraded) {
            sendJson(res, 200, matcherUnavailableResponse(node, nodeId, action, knownParams, status, responsePayload));
            return;
          }
          const response = {
            ok: true,
            status: responsePayload.unmatched_required_fields.length > 0 ? 'needs_input' : 'suggested',
            provider: 'api_doc_index',
            node_id: nodeId,
            action,
            known_params: knownParams,
            payload: responsePayload,
            db_agent_status: status,
          };
          response.evidence_ref = persistDbAgentEvidence(nodeId, action, response, knownParams);
          response.data_mapping_contract = buildDataMappingContract(node, knownParams, {
            status: response.status,
            payload: responsePayload,
            selectedApi: responsePayload.selected_api,
            selectedApis: responsePayload.selected_apis,
            selectedApiAssetCards: responsePayload.selected_api_asset_cards,
            apiResponseFieldCatalog: responsePayload.api_response_field_catalog,
            fieldCoveragePlan: responsePayload.field_coverage_plan,
            derivedFieldPlan: responsePayload.derived_field_plan,
            apiMatchingStrategyResults: responsePayload.strategy_results,
            businessFieldCoverageMetrics: responsePayload.business_field_coverage_metrics,
            evidenceRefs: [response.evidence_ref],
          });
          sendJson(res, 200, response);
          return;
        }
      }
      if (action === 'asset_card') {
        const apiId = String(payload.api_id || '').trim();
        if (!apiId) {
          sendJson(res, 200, {
            ok: false,
            status: 'needs_input',
            reason: 'api_id_required',
            next_step: '请先从候选 API 中选择一个，再查看返回字段。',
            node_id: nodeId,
            action,
            known_params: knownParams,
            data_mapping_contract: buildDataMappingContract(node, knownParams, { status: 'needs_input' }),
            db_agent_status: status,
          });
          return;
        }
        const workerResponse = callDbAgentWorker({
          tool: 'get_api_asset_card',
          args: { api_id: apiId },
        });
        const payloadForContract = buildAssetCardPayload(node, workerResponse);
        const response = {
          ok: workerResponse.ok !== false,
          status: workerResponse.ok === false ? 'blocked' : 'ok',
          node_id: nodeId,
          action,
          known_params: knownParams,
          payload: payloadForContract,
          db_agent_status: status,
        };
        response.evidence_ref = persistDbAgentEvidence(nodeId, action, response, knownParams);
        response.data_mapping_contract = buildDataMappingContract(node, knownParams, {
          status: response.ok ? 'suggested' : 'blocked',
          payload: payloadForContract,
          selectedApi: payloadForContract.selected_api,
          selectedApiAssetCard: payloadForContract.selected_api_asset_card,
          evidenceRefs: [response.evidence_ref],
        });
        sendJson(res, 200, response);
        return;
      }
      if (action === 'suggest_multi_api_mapping') {
        sendJson(res, 200, matcherUnavailableResponse(
          node,
          nodeId,
          action,
          knownParams,
          status,
          { reason: 'api_doc_index_not_configured' },
        ));
        return;
      }
      if (action === 'field_map') {
        sendJson(res, 200, matcherUnavailableResponse(
          node,
          nodeId,
          action,
          knownParams,
          status,
          { reason: 'api_doc_index_not_configured' },
        ));
        return;
      }
      const request = dbAgentRequestForAction(action, node, payload, knownParams);
      if (action === 'probe_sample' && !request.args.api_id) {
        const toolPlanRequest = dbAgentRequestForAction('tool_plan', node, payload, knownParams);
        const toolPlan = callDbAgentWorker(toolPlanRequest);
        request.args.api_id = firstSourceApiFromToolPlan(toolPlan);
      }
      if ((action === 'asset_card' || action === 'probe_sample') && !request.args.api_id) {
        sendJson(res, 200, {
          ok: false,
          status: 'needs_input',
          reason: 'api_id_required',
          next_step: '先执行映射数仓 API，或从候选 API 中选择一个。',
          node_id: nodeId,
          action,
          known_params: knownParams,
          data_mapping_contract: buildDataMappingContract(node, knownParams, { status: 'needs_input' }),
          db_agent_status: status,
        });
        return;
      }
      const workerResponse = callDbAgentWorker(request);
      const evidenceRef = persistDbAgentEvidence(nodeId, action, workerResponse, knownParams);
      const artifact = action === 'probe_sample' && workerResponse.ok ? persistDbAgentArtifact(node, workerResponse, evidenceRef) : null;
      const responsePayload = workerResponse && workerResponse.payload && typeof workerResponse.payload === 'object'
        ? workerResponse.payload
        : {};
      const selectedApi = request.args && request.args.api_id ? { api_id: String(request.args.api_id) } : {};
      const responseStatus = action === 'probe_sample' && workerResponse.reason === 'live_probe_disabled'
        ? 'blocked'
        : action === 'probe_sample' && workerResponse.ok && artifact
          ? 'sample_ready'
          : action === 'tool_plan' && workerResponse.ok
            ? 'suggested'
            : action === 'understand_input' && workerResponse.ok
              ? 'draft'
              : workerResponse.ok ? 'suggested' : 'blocked';
      sendJson(res, 200, {
        ...workerResponse,
        status: workerResponse.reason === 'live_probe_disabled' ? 'blocked' : workerResponse.status,
        node_id: nodeId,
        action,
        known_params: knownParams,
        evidence_ref: evidenceRef,
        artifact,
        next_step: workerResponse.reason === 'live_probe_disabled' ? '设置 DBA_LIVE_PROBE=1 并重启应用后再尝试样例取数。' : workerResponse.next_step,
        data_mapping_contract: buildDataMappingContract(node, knownParams, {
          status: responseStatus,
          payload: responsePayload,
          toolPlan: action === 'tool_plan' || action === 'understand_input' ? workerResponse : null,
          selectedApi,
          evidenceRefs: [evidenceRef],
        }),
        db_agent_status: status,
      });
      return;
    }
    
    // Get nodes list
    if (req.method === 'GET' && pathname === '/api/nodes') {
      const nodes = Array.isArray(config.nodes) ? config.nodes : [];
      sendJson(res, 200, { nodes });
      return;
    }
    
    // Get single node detail
    if (req.method === 'GET' && /^\/api\/nodes\/[^/]+$/.test(pathname)) {
      const nodeId = safeId(pathname.split('/')[3]);
      if (!nodeId) {
        sendJson(res, 400, { error: 'invalid_node_id' });
        return;
      }
      const nodes = Array.isArray(config.nodes) ? config.nodes : [];
      const node = nodes.find(n => n.id === nodeId);
      if (!node) {
        sendJson(res, 404, { error: 'node_not_found', node_id: nodeId });
        return;
      }
      sendJson(res, 200, node);
      return;
    }
  if (req.method === 'POST' && pathname.startsWith('/api/upload/')) {
    const dataRequirementId = safeId(pathname.split('/').pop());
    if (!dataRequirementId) {
      sendJson(res, 400, { error: 'invalid_data_requirement_id' });
      return;
    }
    ensureDir(UPLOADS_DIR);
    const body = await readBody(req);
    const target = path.join(UPLOADS_DIR, `${dataRequirementId}.upload`);
    fs.writeFileSync(target, body);
    sendJson(res, 200, { status: 'uploaded', data_requirement_id: dataRequirementId, path: `uploads/${dataRequirementId}.upload` });
    return;
  }
  // Node execution
  if (req.method === 'POST' && /^\/api\/nodes\/[^/]+\/run$/.test(pathname)) {
    const nodeId = safeId(pathname.split('/')[3]);
    if (!nodeId) {
      sendJson(res, 400, { error: 'invalid_node_id' });
      return;
    }
    
    const nodes = Array.isArray(config.nodes) ? config.nodes : [];
    const node = nodes.find(n => n.id === nodeId);
    if (!node) {
      sendJson(res, 404, { error: 'node_not_found', node_id: nodeId });
      return;
    }
    
    // Broadcast node_start
    broadcastEvent('node_start', { node_id: nodeId, name: node.name, kind: node.kind, timestamp: new Date().toISOString() });
    
    const payload = await parseJsonBody(req);
    const inputs = payload.inputs || payload;
    const submittedArtifact = payload.artifact && typeof payload.artifact === 'object' ? payload.artifact : null;
    const upstreamArtifacts = Array.isArray(payload.upstream_artifacts) ? payload.upstream_artifacts : [];
    let result;
    
    try {
      // Dispatch by node kind
      if (node.kind === 'form') {
        // Form nodes just validate and persist input
        const artifactPath = path.join(ARTIFACTS_DIR, `${nodeId}.json`);
        const artifactPayload = submittedArtifact
          ? {
              ...submittedArtifact,
              fields: inputs,
              persisted_at: new Date().toISOString(),
              artifact_path: `artifacts/${nodeId}.json`,
            }
          : inputs;
        fs.writeFileSync(artifactPath, JSON.stringify(artifactPayload, null, 2));
        result = submittedArtifact
          ? {
              status: 'collected',
              artifact_title: submittedArtifact.title || node.name || nodeId,
              artifact_path: `artifacts/${nodeId}.json`,
              rows: Array.isArray(submittedArtifact.rows) ? submittedArtifact.rows : [],
              missing_required: Array.isArray(submittedArtifact.missing_required) ? submittedArtifact.missing_required : [],
              fields: inputs,
            }
          : { status: 'collected', fields: inputs };
      } else if (node.kind === 'data') {
        if (isDataAnalysisNode(node)) {
          result = await runDataAnalysisNode(node, payload, upstreamArtifacts);
        } else {
          // Data nodes without analysis semantics still expect manual upload.
          result = {
            status: 'waiting_upload',
            message: 'Please upload data via /api/upload/:data_requirement_id',
            upstream_artifacts: upstreamArtifacts,
          };
        }
      } else if (node.kind === 'llm') {
        // LLM nodes: mock for now, should call Python engine
        broadcastEvent('node_progress', { node_id: nodeId, message: 'Calling LLM...', timestamp: new Date().toISOString() });
        result = { status: 'mock_llm', output: 'LLM processing not yet implemented', upstream_artifacts: upstreamArtifacts };
      } else if (node.kind === 'compute' || node.kind === 'aggregate') {
        // Compute/aggregate: call rule engine
        broadcastEvent('node_progress', { node_id: nodeId, message: 'Computing...', timestamp: new Date().toISOString() });
        result = evalRule(nodeId, inputs);
        if (upstreamArtifacts.length > 0 && result && typeof result === 'object') {
          result.upstream_artifacts = upstreamArtifacts;
        }
      } else {
        result = { status: 'unknown_kind', kind: node.kind, upstream_artifacts: upstreamArtifacts };
      }
      
      // Persist evidence
      ensureDir(EVIDENCE_DIR);
      const evidencePath = path.join(EVIDENCE_DIR, `${nodeId}.json`);
      fs.writeFileSync(evidencePath, JSON.stringify({ 
        node_id: nodeId, 
        kind: node.kind,
        inputs, 
        upstream_artifacts: upstreamArtifacts,
        result, 
        created_at: new Date().toISOString() 
      }, null, 2));
      
      // Broadcast node_done
      broadcastEvent('node_done', { node_id: nodeId, result, timestamp: new Date().toISOString() });
      
      sendJson(res, 200, { status: 'done', node_id: nodeId, kind: node.kind, result, evidence_ref: `evidence/${nodeId}.json` });
    } catch (error) {
      // Broadcast node_error
      const errorMessage = error.message || String(error);
      broadcastEvent('node_error', { node_id: nodeId, error: errorMessage, timestamp: new Date().toISOString() });
      sendJson(res, 500, { status: 'error', node_id: nodeId, error: errorMessage });
    }
    return;
  }
  // Export final report
  if (req.method === 'POST' && pathname === '/api/export/final_report') {
    const payload = await parseJsonBody(req);
    const rendered = renderAggregate(config, payload);
    if (rendered.error) {
      sendJson(res, 422, rendered);
      return;
    }
    const reportPath = path.join(APP_ROOT, 'final_report.md');
    fs.writeFileSync(reportPath, rendered.report_markdown);
    sendJson(res, 200, { ...rendered, report_path: 'final_report.md' });
    return;
  }
  if (req.method === 'POST' && pathname === '/api/agent/action_request') {
    const payload = await parseJsonBody(req);
    const validation = validateActionRequest(payload);
    if (!validation.ok) {
      sendJson(res, validation.reason === 'patch_out_of_scope' ? 412 : 400, { error: validation.reason });
      return;
    }
    if (validation.route === 'rerun_node') {
      const result = evalRule(validation.node_id, payload.inputs || {});
      sendJson(res, 200, { status: 'accepted', action: 'rerun_node', node_id: validation.node_id, result });
      return;
    }
    sendJson(res, 200, { status: 'accepted', action: validation.route, requires_confirmation: true });
    return;
  }
  sendJson(res, 404, { error: 'not_found', path: pathname });
  } catch (error) {
    console.error('API error:', error.message);
    sendJson(res, 500, { error: 'internal_error', message: error.message });
  }
}

function handleSse(req, res, pathname) {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-cache',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no',
  });
  
  // Register client
  const client = { res, filter: null };
  sseClients.add(client);
  
  // Send initial connection event
  const eventType = pathname.startsWith(SSE_AGENT_PREFIX) ? 'agent_connected' : 'stream_connected';
  res.write(`event: ${eventType}\n`);
  res.write(`data: ${JSON.stringify({ status: 'connected', path: pathname, timestamp: new Date().toISOString() })}\n\n`);
  
  // Send heartbeat every 30s
  const heartbeat = setInterval(() => {
    try {
      res.write(`: heartbeat\n\n`);
    } catch (error) {
      clearInterval(heartbeat);
      sseClients.delete(client);
    }
  }, 30000);
  
  // Clean up on close
  req.on('close', () => {
    clearInterval(heartbeat);
    sseClients.delete(client);
  });
}

function handleAgentCallSse(req, res, pathname) {
  const parts = String(pathname || '').split('/');
  const nodeId = safeId(parts[3] || '');
  const callId = safeId(parts[6] || '');
  if (!nodeId || !callId) {
    sendJson(res, 400, { error: 'invalid_agent_call_path' });
    return;
  }
  let snapshot;
  try {
    snapshot = collaborationStore.agentCallResponse(nodeId, callId);
  } catch (error) {
    if (error instanceof CollaborationError) {
      sendJson(res, error.statusCode, { error: error.code, ...error.details });
      return;
    }
    throw error;
  }
  res.writeHead(200, {
    'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-cache',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no',
  });
  const client = { res, filter: { node_id: nodeId, call_id: callId } };
  sseClients.add(client);
  res.write(`event: call_snapshot\ndata: ${JSON.stringify({ node_id: nodeId, call: snapshot.call })}\n\n`);
  const heartbeat = setInterval(() => {
    try {
      res.write(': heartbeat\n\n');
    } catch {
      clearInterval(heartbeat);
      sseClients.delete(client);
    }
  }, 15000);
  req.on('close', () => {
    clearInterval(heartbeat);
    sseClients.delete(client);
  });
}

function handleAgentBatchSse(req, res, pathname) {
  const parts = String(pathname || '').split('/');
  const nodeId = safeId(parts[3] || '');
  const batchId = safeId(parts[6] || '');
  if (!nodeId || !batchId) {
    sendJson(res, 400, { error: 'invalid_agent_batch_path' });
    return;
  }
  let snapshot;
  try {
    snapshot = collaborationStore.agentBatchResponse(nodeId, batchId);
  } catch (error) {
    if (error instanceof CollaborationError) {
      sendJson(res, error.statusCode, { error: error.code, ...error.details });
      return;
    }
    throw error;
  }
  res.writeHead(200, {
    'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-cache',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no',
  });
  const client = { res, filter: { node_id: nodeId, batch_id: batchId } };
  sseClients.add(client);
  res.write(`event: batch_snapshot\ndata: ${JSON.stringify({ node_id: nodeId, batch: snapshot.batch })}\n\n`);
  const heartbeat = setInterval(() => {
    try {
      res.write(': heartbeat\n\n');
    } catch {
      clearInterval(heartbeat);
      sseClients.delete(client);
    }
  }, 15000);
  req.on('close', () => {
    clearInterval(heartbeat);
    sseClients.delete(client);
  });
}

function handleGeneAnalysisSse(req, res, pathname) {
  const parts = String(pathname || '').split('/');
  const nodeId = safeId(parts[3] || '');
  const executionId = safeId(parts[5] || '');
  if (nodeId !== 'analyze_hot_product_genes' || !executionId) {
    sendJson(res, 400, { error: 'invalid_gene_analysis_path' });
    return;
  }
  const snapshot = geneAnalysisStore.analysisResponse(nodeId).analysis;
  if (!snapshot || snapshot.execution_id !== executionId) {
    sendJson(res, 404, { error: 'gene_analysis_not_found' });
    return;
  }
  res.writeHead(200, {
    'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-cache',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no',
  });
  const client = { res, filter: { node_id: nodeId, execution_id: executionId } };
  sseClients.add(client);
  res.write(`event: gene_analysis_snapshot\ndata: ${JSON.stringify({ node_id: nodeId, execution_id: executionId, analysis: snapshot })}\n\n`);
  const heartbeat = setInterval(() => {
    try {
      res.write(': heartbeat\n\n');
    } catch {
      clearInterval(heartbeat);
      sseClients.delete(client);
    }
  }, 15000);
  req.on('close', () => {
    clearInterval(heartbeat);
    sseClients.delete(client);
  });
}

function serveStatic(req, res, pathname) {
  let relative = pathname === '/' ? '/index.html' : pathname;
  relative = decodeURIComponent(relative);
  const fullPath = path.normalize(path.join(PUBLIC_DIR, relative));
  if (!fullPath.startsWith(PUBLIC_DIR)) {
    sendText(res, 403, 'Forbidden');
    return;
  }
  fs.readFile(fullPath, (err, data) => {
    if (err) {
      sendText(res, 404, '404 Not Found');
      return;
    }
    const ext = path.extname(fullPath);
    sendText(res, 200, data, MIME_TYPES[ext] || 'application/octet-stream');
  });
}

const server = http.createServer((req, res) => {
  const parsed = url.parse(req.url || '/');
  const pathname = parsed.pathname || '/';
  Promise.resolve()
    .then(() => {
      if (req.method === 'GET' && /^\/api\/nodes\/[^/]+\/agent-thread\/calls\/[^/]+\/events$/.test(pathname)) {
        return handleAgentCallSse(req, res, pathname);
      }
      if (req.method === 'GET' && /^\/api\/nodes\/[^/]+\/agent-thread\/batches\/[^/]+\/events$/.test(pathname)) {
        return handleAgentBatchSse(req, res, pathname);
      }
      if (req.method === 'GET' && /^\/api\/nodes\/analyze_hot_product_genes\/gene-analysis\/[^/]+\/events$/.test(pathname)) {
        return handleGeneAnalysisSse(req, res, pathname);
      }
      if (pathname.startsWith('/api/')) return handleApi(req, res, pathname);
      if (pathname.startsWith('/sse/')) return handleSse(req, res, pathname);
      return serveStatic(req, res, pathname);
    })
    .catch(err => {
      console.error('Request error:', err);
      sendJson(res, 500, { error: 'server_error', message: String(err.message || err) });
    });
});

function startupValidate() {
  const config = readConfig();
  console.log(`[report_generator] Loaded app.config.json`);
  console.log(`  app_slug: ${config.app_slug}`);
  console.log(`  shell_kind: ${config.shell_kind}`);
  console.log(`  shell_version: ${config.shell_version}`);
  console.log(`  nodes: ${Array.isArray(config.nodes) ? config.nodes.length : 0}`);
  console.log(`  config_path: ${CONFIG_PATH}`);
  console.log(`  public_dir: ${PUBLIC_DIR}`);
}

function startServer() {
  try {
    startupValidate();
  } catch (error) {
    console.error(`[report_generator] FATAL: Failed to load config: ${error.message}`);
    console.error(`  config_path: ${CONFIG_PATH}`);
    process.exit(1);
  }
  server.listen(PORT, HOST, () => {
    console.log(`[report_generator] Shell server running at http://${HOST}:${PORT}/`);
    console.log(`[report_generator] Ready to serve ${cachedConfig.nodes.length} nodes`);
  });
  return server;
}

if (require.main === module) {
  startServer();
}

module.exports = {
  handleApi,
  readConfig,
  renderAggregate,
  server,
  startServer,
  __test: {
    bindApiRequestParams,
    callCategoryResolverDiscovery,
    callRequestParamBinder,
    buildFieldSources,
    businessParamForApiParam,
    groupedApiPlansForCoverage,
    projectRowsForApiFieldCoverage,
    projectRowsForFields,
    repairFieldCoverageWithRuntimeRows,
    requestDebugFromProbePayload,
    rowsFromProbePayload,
    valueAtSourcePath,
  },
};
