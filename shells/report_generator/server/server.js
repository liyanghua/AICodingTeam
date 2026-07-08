const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');
const { spawnSync } = require('child_process');

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
const API_NODE_RUN_PREFIX = '/api/nodes/';
const SSE_NODE_PREFIX = '/sse/nodes/';
const SSE_AGENT_PREFIX = '/sse/agent/';
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
    try {
      client.write(message);
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
    allowed_tools: ['ask_api_catalog', 'select_tools_for_task', 'list_domain_apis', 'get_api_asset_card', 'probe_api_sample'],
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

function piAgentStatus() {
  const bin = piAgentBin();
  const probe = spawnSync(bin, ['--help'], {
    encoding: 'utf-8',
    timeout: 3000,
    env: process.env,
  });
  const available = !probe.error || probe.error.code !== 'ENOENT';
  return {
    provider: 'pi_agent',
    status: available ? 'ready' : 'not_configured',
    reason: available ? 'ready' : 'pi_binary_not_found',
    pi_bin: bin,
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

function piPromptForDataMapping(node, payload) {
  const contract = payload.data_mapping_contract && typeof payload.data_mapping_contract === 'object'
    ? payload.data_mapping_contract
    : {};
  const cards = selectedApiCardsFromPayload(payload).map(assetCardSchemaForPrompt);
  const baseline = Array.isArray(payload.field_coverage_plan) ? payload.field_coverage_plan : [];
  const joinPlan = payload.join_plan && typeof payload.join_plan === 'object' ? payload.join_plan : {};
  const upstream = Array.isArray(payload.upstream_artifacts)
    ? extractKnownParamsFromArtifacts(payload.upstream_artifacts)
    : {};
  return [
    '你是生成应用右侧 Agent 的数据映射协作层。',
    '目标：围绕当前节点的输出字段要求、候选 API 的完整 schema 和确定性匹配 baseline，逐字段给出可审计建议；只建议，不写入事实源。',
    `意图：${String(payload.intent || 'data_mapping_advice')}`,
    `节点：${node && (node.name || node.id) || 'unknown'} (${node && node.id || ''})`,
    `用户问题：${String(payload.message || '请给出字段映射建议。')}`,
    '## 输出字段要求',
    JSON.stringify(nodeOutputFieldRequirements(node), null, 2),
    '## 候选 API 完整 schema（request/response 字段名、路径、类型、描述）',
    JSON.stringify(cards, null, 2),
    '## 确定性规则匹配 baseline（field_coverage_plan：请在此基础上纠错和增强，而不是从零开始）',
    JSON.stringify(baseline, null, 2),
    '## Join plan baseline',
    JSON.stringify(joinPlan, null, 2),
    '## 上游业务参数（用于补齐类目、周期、产品线等口径）',
    JSON.stringify(upstream, null, 2),
    '## 当前数据映射合同',
    JSON.stringify(contract, null, 2),
    '## 输出要求',
    '1. 必须返回 JSON，schema_version 固定为 "pi-data-mapping-advice-v1"，node_id 等于当前节点。',
    '2. 对每个输出字段给出 field_advice：judgement(ok/needs_review/missing/better_alternative)、confidence(0-1)、reason。',
    '3. 有更优字段时给出 suggested_source_api_id / suggested_source_field_path，且必须来自上面列出的真实 API 字段。',
    '4. 多个 API 且缺 join key 时，join_advice.judgement 输出 needs_input，并给出 recommended_join_keys。',
    '5. 如果 intent=derived_field_analysis，必须额外输出 derived_field_advice[]，说明派生字段的分析逻辑、所需证据、草稿值条件、置信度和风险；无证据时 draft_value 留空。',
    '6. 无法完整判断时，用 questions_for_user 列出待用户澄清的问题。',
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
  const confirmed = baseline.filter(item => item && (item.human_confirmed || String(item.mapping_status || '') === 'confirmed')).length;
  return {
    node_id: node && node.id ? String(node.id) : '',
    intent: String(payload.intent || 'data_mapping_advice'),
    selected_api_count: cards.length,
    field_coverage_plan: baseline,
    field_coverage_count: baseline.length,
    confirmed_field_count: confirmed,
    join_plan: payload.join_plan && typeof payload.join_plan === 'object' ? payload.join_plan : {},
    output_field_requirements: nodeOutputFieldRequirements(node),
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
    questions_for_user: Array.isArray(parsed.questions_for_user) ? parsed.questions_for_user.map(String) : [],
    applicable_actions: applicableActionsFromFieldAdvice(fieldAdvice),
    requires_human_confirmation: true,
    source: { provider: 'pi_agent', degraded: false },
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
    summaryText = summaryText || '请先选择候选 API，再生成字段映射建议。';
  }
  return {
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
    questions_for_user: context.selected_api_count === 0 ? ['请先选择候选 API'] : [],
    applicable_actions: applicableActionsFromFieldAdvice(fieldAdvice),
    requires_human_confirmation: true,
    source: { provider: 'deterministic_fallback', degraded: Boolean(options.degraded) },
  };
}

function buildUnavailableAdvice(context, reason) {
  return {
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
    questions_for_user: [],
    applicable_actions: [],
    requires_human_confirmation: true,
    source: { provider: 'pi_agent', degraded: true, reason: String(reason || 'not_ready') },
  };
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

function callPiAgent(node, payload) {
  const context = piAdviceContext(node, payload);
  const status = piAgentStatus();
  if (status.status !== 'ready') {
    const advice = buildUnavailableAdvice(context, status.reason);
    return {
      ok: false,
      status: status.status,
      reason: status.reason,
      provider: 'pi_agent',
      advice,
      evidence_ref: persistPiMappingAdvice(context.node_id, advice, context),
    };
  }
  const prompt = piPromptForDataMapping(node, payload);
  const requestId = `pi-${Date.now()}`;
  // pi rpc 协议的命令判别字段是 type，不是 command；用错字段会被拒为 "Unknown command: undefined"。
  const rpcCommand = JSON.stringify({ type: 'prompt', id: requestId, message: prompt }) + '\n';
  // --no-session：单次数据映射建议无需持久化会话，避免 session 目录不可写时整体调用失败。
  const piArgs = ['--mode', 'rpc', '--no-session'];
  // 允许经 PI_MODEL 指定 provider/model（默认 provider 缺 key 时可切到已配置的模型）。
  const piModel = String(process.env.PI_MODEL || '').trim();
  if (piModel) piArgs.push('--model', piModel);
  const result = spawnSync(piAgentBin(), piArgs, {
    input: rpcCommand,
    encoding: 'utf-8',
    timeout: Number(process.env.PI_RPC_TIMEOUT_MS || 60000),
    cwd: APP_ROOT,
    env: process.env,
  });
  if (result.error) {
    const advice = buildFallbackAdvice(context, {
      status: 'needs_review',
      text: 'PI 调用失败，已用确定性规则生成待确认草稿。',
      degraded: true,
    });
    return {
      ok: false,
      status: 'error',
      reason: 'pi_spawn_failed',
      provider: 'pi_agent',
      error: result.error.message,
      advice,
      evidence_ref: persistPiMappingAdvice(context.node_id, advice, context),
    };
  }
  const responseText = parsePiRpcText(result.stdout);
  const succeeded = result.status === 0 && Boolean(responseText);
  const advice = succeeded
    ? normalizePiMappingAdvice(responseText, context)
    : buildFallbackAdvice(context, { status: 'needs_review', text: 'PI 未返回有效内容，已用确定性规则兜底。', degraded: true });
  return {
    ok: succeeded,
    status: result.status === 0 ? 'ok' : 'error',
    reason: result.status === 0 ? 'ready' : 'pi_rpc_failed',
    provider: 'pi_agent',
    response_text: responseText,
    advice,
    evidence_ref: persistPiMappingAdvice(context.node_id, advice, context),
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
        top: Number.isFinite(Number(payload.top)) ? Number(payload.top) : 10,
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
    const apiFieldPath = String(mapped && (mapped.api_field_path || mapped.source_field_path) || '');
    const status = String(mapped && (mapped.mapping_status || mapped.status) || (apiFieldPath ? 'mapped' : 'missing'));
    return {
      output_id: field.output_id,
      field_path: field.field_path,
      field_name: field.field_name,
      title: field.title,
      description: field.description,
      type: field.type,
      required: field.required !== false,
      source_schema_ref: field.source_schema_ref,
      canonical_field_name: field.canonical_field_name || '',
      source: field.source || '',
      source_trace: field.source_trace || {},
      source_api_id: String(mapped && (mapped.source_api_id || mapped.api_id) || ''),
      source_api_name: String(mapped && (mapped.source_api_name || mapped.api_name) || ''),
      source_field_path: apiFieldPath,
      api_field_path: apiFieldPath,
      api_field_name: String(mapped && mapped.api_field_name || ''),
      api_field_type: String(mapped && mapped.api_field_type || ''),
      source_role: String(mapped && mapped.source_role || (apiFieldPath ? 'api_field' : '')),
      source_kind: String(mapped && mapped.source_kind || (apiFieldPath ? 'api_doc_index' : '')),
      mapping_status: status,
      confidence: mapped && Number.isFinite(Number(mapped.confidence)) ? Number(mapped.confidence) : (apiFieldPath ? 1 : 0),
      human_confirmed: Boolean(mapped && (mapped.human_confirmed || mapped.confirmed || status === 'confirmed')),
      human_note: String(mapped && (mapped.human_note || mapped.note) || ''),
      match_basis: String(mapped && mapped.match_basis || ''),
      missing_reason: String(mapped && mapped.missing_reason || ''),
      candidate_field_options: Array.isArray(mapped && mapped.candidate_field_options) ? mapped.candidate_field_options : Array.isArray(mapped && mapped.candidates) ? mapped.candidates : [],
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

const DERIVED_FIELD_NAMES = new Set(['功能', 'function', '风格', 'style', '主图元素', 'main_image_elements', '爆款原因', 'hot_sale_reason']);

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
  const entry = localApiEntries().find(item => String(item.api_id || '') === String(apiId || ''));
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
      available_evidence_fields: [],
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
    timeout: 15000,
    env: {
      ...process.env,
      DB_ARCHAEOLOGIST_SPEC_PACK: specPackRoot,
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
  const response = payload.response && typeof payload.response === 'object' ? payload.response : payload;
  if (Array.isArray(response.top)) return response.top;
  if (response.response && Array.isArray(response.response.top)) return response.response.top;
  if (Array.isArray(payload.top)) return payload.top;
  return [];
}

function persistDbAgentEvidence(nodeId, action, workerResponse, knownParams) {
  ensureDir(EVIDENCE_DIR);
  const evidencePath = path.join(EVIDENCE_DIR, `${nodeId}.db_agent.${action}.json`);
  fs.writeFileSync(evidencePath, JSON.stringify({
    node_id: nodeId,
    action,
    known_params: knownParams,
    response: workerResponse,
    created_at: new Date().toISOString(),
  }, null, 2));
  return `evidence/${nodeId}.db_agent.${action}.json`;
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

function safeId(value) {
  const id = String(value || '');
  if (!/^[a-zA-Z0-9_.-]+$/.test(id)) return '';
  return id;
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

    if (req.method === 'POST' && pathname === '/api/pi-agent/query') {
      const payload = await parseJsonBody(req);
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
      sendJson(res, 200, {
        ...callPiAgent(node, payload),
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
        // Data nodes expect manual upload
        result = {
          status: 'waiting_upload',
          message: 'Please upload data via /api/upload/:data_requirement_id',
          upstream_artifacts: upstreamArtifacts,
        };
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
  sseClients.add(res);
  
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
      sseClients.delete(res);
    }
  }, 30000);
  
  // Clean up on close
  req.on('close', () => {
    clearInterval(heartbeat);
    sseClients.delete(res);
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
};
