const state = {
  config: null,
  selectedNodeId: '',
  nodeStatus: {},
  latestResult: {},
  nodeDrafts: {},
  draftArtifacts: {},
  nodeArtifacts: {},
  saveStatus: {},
  flowNotice: {},
  dbAgentStatus: null,
  dbAgentResults: {},
  dbAgentBusy: {},
  fieldMappingDrafts: {},
  piAgentStatus: null,
  piAgentResults: {},
  piAgentBusy: {},
  piAgentThreads: {},
  piCorrectionTargets: {},
  apiFieldBrowserFilters: {},
  piSelectedModel: '',
  dataAnalysisTopN: {},
  dataTablePages: {},
  dataTableWorkspaces: {},
  insightWorkspaces: {},
  collaborationBusy: {},
  collaborationNotices: {},
  tableSelections: {},
  tableEditing: {},
  agentThreads: {},
  agentCallSources: {},
  agentCallTimers: {},
  agentBatches: {},
  agentBatchSources: {},
  agentBatchTimers: {},
  agentBatchReview: {},
  agentScrollState: {},
  geneAnalyses: {},
  geneAnalysisSources: {},
  geneAnalysisTimers: {},
  layoutWidths: { left: 260, right: 360 },
  pendingAutoAdvanceNodeId: '',
  eventSource: null,
};

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

async function fetchConfig() {
  const response = await fetch('/api/config');
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `config failed: ${response.status}`);
  }
  return response.json();
}

function connectEventStream() {
  if (state.eventSource) {
    state.eventSource.close();
  }
  
  state.eventSource = new EventSource('/sse/nodes/stream');
  
  state.eventSource.addEventListener('stream_connected', (event) => {
    console.log('SSE connected:', JSON.parse(event.data));
  });
  
  state.eventSource.addEventListener('node_start', (event) => {
    const data = JSON.parse(event.data);
    state.nodeStatus[data.node_id] = 'running';
    render();
  });
  
  state.eventSource.addEventListener('node_progress', (event) => {
    const data = JSON.parse(event.data);
    console.log('Node progress:', data);
  });
  
  state.eventSource.addEventListener('node_done', (event) => {
    const data = JSON.parse(event.data);
    if (data.node_id === 'analyze_hot_product_genes') {
      state.geneAnalyses[data.node_id] = { analysis: data.result, confirmed_artifact: null };
      state.nodeStatus[data.node_id] = 'waiting';
      render();
      return;
    }
    const shouldAdvance = state.pendingAutoAdvanceNodeId === data.node_id;
    completeNodeRun(data.node_id, data.result, { autoAdvance: shouldAdvance });
    if (shouldAdvance) state.pendingAutoAdvanceNodeId = '';
  });

  state.eventSource.addEventListener('gene_analysis_update', (event) => {
    const data = JSON.parse(event.data);
    if (!data.node_id || !data.analysis) return;
    state.geneAnalyses[data.node_id] = {
      ...(state.geneAnalyses[data.node_id] || {}),
      analysis: data.analysis,
    };
    patchHotProductGeneMonitor(data.node_id);
    if (!['running', 'preparing'].includes(String(data.analysis.status || ''))) render();
  });
  
  state.eventSource.addEventListener('node_error', (event) => {
    const data = JSON.parse(event.data);
    state.nodeStatus[data.node_id] = 'failed';
    state.latestResult[data.node_id] = { error: data.error };
    render();
  });
  
  state.eventSource.onerror = (error) => {
    console.error('SSE error:', error);
    state.eventSource.close();
    // Reconnect after 5 seconds
    setTimeout(connectEventStream, 5000);
  };
}

function currentNode() {
  const nodes = state.config?.nodes || [];
  return nodes.find(node => node.id === state.selectedNodeId) || nodes[0] || null;
}

function nodeById(nodeId) {
  const nodes = state.config?.nodes || [];
  return nodes.find(node => node.id === nodeId) || null;
}

function isHotProductGeneNode(node) {
  return Boolean(node && node.id === 'analyze_hot_product_genes');
}

function statusFor(nodeId) {
  return state.nodeStatus[nodeId] || 'idle';
}

function draftStorageKey() {
  const slug = state.config?.app_slug || 'report-generator';
  return `${slug}-node-drafts`;
}

function artifactStorageKey() {
  const slug = state.config?.app_slug || 'report-generator';
  return `${slug}-node-artifacts`;
}

function loadNodeDrafts() {
  try {
    state.nodeDrafts = JSON.parse(localStorage.getItem(draftStorageKey()) || '{}') || {};
  } catch {
    state.nodeDrafts = {};
  }
}

function saveNodeDrafts() {
  localStorage.setItem(draftStorageKey(), JSON.stringify(state.nodeDrafts || {}));
}

function loadNodeArtifacts() {
  try {
    state.nodeArtifacts = JSON.parse(localStorage.getItem(artifactStorageKey()) || '{}') || {};
    state.draftArtifacts = { ...state.draftArtifacts, ...state.nodeArtifacts };
  } catch {
    state.nodeArtifacts = {};
  }
}

function saveNodeArtifacts() {
  localStorage.setItem(artifactStorageKey(), JSON.stringify(state.nodeArtifacts || {}));
}

function dbAgentStorageKey() {
  const slug = state.config?.app_slug || 'report-generator';
  return `${slug}-db-agent-results`;
}

function loadDbAgentResults() {
  try {
    state.dbAgentResults = JSON.parse(localStorage.getItem(dbAgentStorageKey()) || '{}') || {};
  } catch {
    state.dbAgentResults = {};
  }
}

function saveDbAgentResults() {
  localStorage.setItem(dbAgentStorageKey(), JSON.stringify(state.dbAgentResults || {}));
}

function workbenchStorageKey() {
  const slug = state.config?.app_slug || 'report-generator';
  const taskId = state.config?.task_ref?.task_id || state.config?.task_ref?.run_id || 'local';
  return `${taskId}:${slug}:field-mapping-workbench`;
}

function loadWorkbenchState() {
  try {
    const saved = JSON.parse(localStorage.getItem(workbenchStorageKey()) || '{}') || {};
    state.fieldMappingDrafts = saved.fieldMappingDrafts && typeof saved.fieldMappingDrafts === 'object' ? saved.fieldMappingDrafts : {};
    state.piAgentResults = saved.piAgentResults && typeof saved.piAgentResults === 'object' ? saved.piAgentResults : {};
    state.piAgentThreads = saved.piAgentThreads && typeof saved.piAgentThreads === 'object' ? saved.piAgentThreads : {};
    state.piCorrectionTargets = saved.piCorrectionTargets && typeof saved.piCorrectionTargets === 'object' ? saved.piCorrectionTargets : {};
    state.apiFieldBrowserFilters = saved.apiFieldBrowserFilters && typeof saved.apiFieldBrowserFilters === 'object' ? saved.apiFieldBrowserFilters : {};
    state.piSelectedModel = typeof saved.piSelectedModel === 'string' ? saved.piSelectedModel : '';
    state.dataAnalysisTopN = saved.dataAnalysisTopN && typeof saved.dataAnalysisTopN === 'object' ? saved.dataAnalysisTopN : {};
  } catch {
    state.fieldMappingDrafts = {};
    state.piAgentResults = {};
    state.piAgentThreads = {};
    state.piCorrectionTargets = {};
    state.apiFieldBrowserFilters = {};
    state.piSelectedModel = '';
    state.dataAnalysisTopN = {};
  }
}

function saveWorkbenchState() {
  localStorage.setItem(workbenchStorageKey(), JSON.stringify({
    fieldMappingDrafts: state.fieldMappingDrafts || {},
    piAgentResults: state.piAgentResults || {},
    piAgentThreads: state.piAgentThreads || {},
    piCorrectionTargets: state.piCorrectionTargets || {},
    apiFieldBrowserFilters: state.apiFieldBrowserFilters || {},
    piSelectedModel: state.piSelectedModel || '',
    dataAnalysisTopN: state.dataAnalysisTopN || {},
  }));
}

function layoutStorageKey() {
  const slug = state.config?.app_slug || 'report-generator';
  return `${slug}-layout-widths`;
}

function loadLayoutState() {
  try {
    const saved = JSON.parse(localStorage.getItem(layoutStorageKey()) || '{}') || {};
    state.layoutWidths = {
      left: clampPanelWidth(Number(saved.left) || 260, 200, 520),
      right: clampPanelWidth(Number(saved.right) || 360, 280, 620),
    };
  } catch {
    state.layoutWidths = { left: 260, right: 360 };
  }
}

function saveLayoutState() {
  localStorage.setItem(layoutStorageKey(), JSON.stringify(state.layoutWidths || {}));
}

function clampPanelWidth(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function layoutStyle() {
  const widths = state.layoutWidths || { left: 260, right: 360 };
  return `--left-panel-width:${clampPanelWidth(Number(widths.left) || 260, 200, 520)}px; --right-panel-width:${clampPanelWidth(Number(widths.right) || 360, 280, 620)}px;`;
}

const MARKET_SCOPE_FIELD_FALLBACKS = {
  category: { label: '分析类目', description: '精确到三级类目或最小叶子类目' },
  product_line: { label: '分析产品线', description: '例如沙发垫、桌垫、防晒衣、假发、地垫' },
  shop_stage: { label: '店铺阶段', description: '新店 / 成长期店铺 / 爆款店铺 / 多链接店铺' },
  goal: { label: '当前目标', description: '新品开发 / 爆款挖掘 / 产品升级 / 竞品突破' },
  advantages: { label: '当前资源', description: '供应链、价格、视觉、投放、品牌、客服等优势' },
  target_price_band: { label: '目标价格带', description: '低价 / 中价 / 高价 / 生意参谋6个价格带' },
  target_audience: { label: '目标人群', description: '已知人群 / 待分析人群' },
  period: { label: '分析周期', description: '近7天 / 近30天 / 月维度 / 季节维度' },
};

function artifactTitleFor(node) {
  const outputIds = Array.isArray(node.outputs) ? node.outputs : [];
  const title = node.node_execution_view?.artifact?.title
    || (outputIds.includes('market_insight_project_definition') ? '《市场洞察项目定义表》' : '')
    || node.output_model?.outputs?.[0]?.title
    || '节点中间产物';
  return String(title).trim() || '节点中间产物';
}

function fieldId(field) {
  return field.id || field.label || field.name || '';
}

function fieldLabel(field) {
  return field.label || field.name || field.id || '';
}

function normalizeScopeFormField(field) {
  const fallback = MARKET_SCOPE_FIELD_FALLBACKS[field.id] || {};
  return {
    id: field.id || fallback.label || '',
    label: field.label || fallback.label || field.name || field.id || '',
    description: field.description || fallback.description || field.type || '',
    required: field.required !== false,
    source: 'app_config.scope_form.fields',
  };
}

function nodeActionFields(node) {
  const executionFields = Array.isArray(node.node_execution_view?.action?.fields) ? node.node_execution_view.action.fields : [];
  if (executionFields.length > 0) return executionFields;
  const scopeFields = Array.isArray(state.config?.scope_form?.fields) ? state.config.scope_form.fields : [];
  if (node.kind === 'form' && scopeFields.length > 0) {
    return scopeFields.map(normalizeScopeFormField);
  }
  return [];
}

function buildNodeDraftArtifact(node, draft) {
  const fields = nodeActionFields(node);
  const rows = fields.map(field => {
    const id = fieldId(field);
    const value = String(draft?.[id] || '').trim();
    return {
      field_id: id,
      label: fieldLabel(field),
      requirement: field.description || '',
      value,
      required: Boolean(field.required),
      status: value ? 'filled' : field.required ? 'missing' : 'empty',
      source: field.source || 'node_execution_view.action.fields',
    };
  });
  return {
    title: artifactTitleFor(node),
    node_id: node.id,
    node_name: node.name || node.id,
    status: rows.some(row => row.status === 'missing') ? 'missing_required_fields' : 'ready',
    rows,
    missing_required: rows.filter(row => row.status === 'missing').map(row => row.label || row.field_id),
    generated_at: new Date().toISOString(),
    source: 'browser_manual_form_save',
  };
}

function rememberNodeArtifact(nodeId, artifact) {
  if (!nodeId || !artifact) return;
  state.draftArtifacts[nodeId] = artifact;
  state.nodeArtifacts[nodeId] = artifact;
  saveNodeArtifacts();
}

function artifactFromRunResult(nodeId, result) {
  const node = nodeById(nodeId) || { id: nodeId };
  const existing = state.draftArtifacts[nodeId] || state.nodeArtifacts[nodeId];
  if (existing) {
    return {
      ...existing,
      artifact_path: result?.artifact_path || existing.artifact_path,
      server_status: result?.status || existing.server_status,
    };
  }
  if (result && Array.isArray(result.rows)) {
    return {
      title: result.artifact_title || artifactTitleFor(node),
      node_id: nodeId,
      node_name: node.name || nodeId,
      status: Array.isArray(result.missing_required) && result.missing_required.length > 0 ? 'missing_required_fields' : 'ready',
      rows: result.rows,
      fields: result.fields || {},
      missing_required: result.missing_required || [],
      artifact_path: result.artifact_path || '',
      source: 'server_node_result',
    };
  }
  if (result && result.fields && nodeActionFields(node).length > 0) {
    return buildNodeDraftArtifact(node, result.fields);
  }
  return null;
}

function currentDraftArtifact(node) {
  const saved = state.nodeArtifacts[node.id] || state.draftArtifacts[node.id];
  if (saved) return saved;
  const draft = state.nodeDrafts[node.id] || {};
  if (Object.values(draft).some(value => String(value || '').trim())) {
    return buildNodeDraftArtifact(node, draft);
  }
  return null;
}

function upstreamArtifactsFor(node) {
  const dependencies = Array.isArray(node.depends_on) ? node.depends_on : [];
  return dependencies
    .map(nodeId => {
      const artifact = state.nodeArtifacts[nodeId] || state.draftArtifacts[nodeId];
      if (!artifact) return null;
      const sourceNode = nodeById(nodeId);
      return {
        source_node_id: nodeId,
        source_node_name: sourceNode?.name || nodeId,
        artifact,
      };
    })
    .filter(Boolean);
}

function listText(items, emptyText = '无') {
  if (!Array.isArray(items) || items.length === 0) return escapeHtml(emptyText);
  return escapeHtml(items.join(', '));
}

function renderKeyValueList(items) {
  const entries = Array.isArray(items) ? items : [];
  if (entries.length === 0) return '<p class="muted">无</p>';
  return `
    <ul class="meta-list">
      ${entries.map(item => `<li>${escapeHtml(item)}</li>`).join('')}
    </ul>
  `;
}

function renderInputModel(node) {
  const input = node.input_model || {};
  const fields = Array.isArray(input.fields) ? input.fields : [];
  const upstream = upstreamArtifactsFor(node);
  return `
    <p class="muted">mode：${escapeHtml(input.mode || 'derived')}</p>
    ${fields.length > 0 ? `
      <ul class="meta-list">
        ${fields.map(field => `<li>${escapeHtml(field.id || field.name || '')} · ${escapeHtml(field.type || 'field')}</li>`).join('')}
      </ul>
    ` : '<p class="muted">暂无表单字段。</p>'}
    ${renderUpstreamInputs(node, upstream)}
  `;
}

function renderUpstreamInputs(node, upstream) {
  const dependencies = Array.isArray(node.depends_on) ? node.depends_on : [];
  if (upstream.length === 0) {
    if (dependencies.length === 0) return '<p class="muted">无上游节点输入。</p>';
    return `<p class="muted">等待上游节点产物：${listText(dependencies, '无')}</p>`;
  }
  return `
    <div class="upstream-inputs">
      <h4>上游中间产物</h4>
      ${upstream.map(item => `
        <article class="model-card upstream-artifact">
          <h4>来自：${escapeHtml(item.source_node_name)}</h4>
          <p class="muted">node：${escapeHtml(item.source_node_id)} · artifact：${escapeHtml(item.artifact.title || '节点产物')}</p>
          ${renderArtifactRowsTable(item.artifact)}
        </article>
      `).join('')}
    </div>
  `;
}

function renderRequiredData(node) {
  const requiredData = node.input_model?.required_data || [];
  if (!Array.isArray(requiredData) || requiredData.length === 0) {
    return '<p class="muted">当前节点不需要人工上传数据。</p>';
  }
  return requiredData.map(item => `
    <article class="model-card">
      <h4>${escapeHtml(item.id || 'data_requirement')}</h4>
      <p>${escapeHtml(item.description || '暂无描述。')}</p>
      <p class="muted">freshness：${escapeHtml(item.freshness || '未声明')} · mode：${escapeHtml(item.effective_mode || 'manual_upload_only')} · status：${escapeHtml(item.status || 'available')}</p>
      <details>
        <summary>字段要求</summary>
        ${renderKeyValueList(item.required_fields || [])}
      </details>
      <details>
        <summary>证据要求</summary>
        ${renderKeyValueList(item.evidence_required || [])}
      </details>
      <details>
        <summary>来源</summary>
        <p class="muted">preferred：${listText(item.preferred_sources || [], '无')}</p>
        <p class="muted">fallback：${listText(item.fallback_sources || [], '无')}</p>
      </details>
    </article>
  `).join('');
}

function renderOutputModel(node) {
  const outputs = node.output_model?.outputs || [];
  if (!Array.isArray(outputs) || outputs.length === 0) {
    return '<p class="muted">暂无声明产物。</p>';
  }
  return outputs.map(output => {
    const summary = output.summary || {};
    const properties = summary.properties || Object.keys(output.schema?.properties || {});
    const required = summary.required || output.schema?.required || [];
    return `
      <article class="model-card">
        <h4>${escapeHtml(output.title || output.id)}</h4>
        <p>${escapeHtml(output.description || '暂无描述。')}</p>
        <p class="muted">id：${escapeHtml(output.id)} · source：${escapeHtml(output.source || 'unknown')} · status：${escapeHtml(output.status || 'unknown')}</p>
        <details>
          <summary>Schema</summary>
          <p class="muted">properties：${listText(properties, '无')}</p>
          <p class="muted">required：${listText(required, '无')}</p>
          <pre class="json-output">${escapeHtml(JSON.stringify(output.schema || {}, null, 2))}</pre>
        </details>
      </article>
    `;
  }).join('');
}

function outputFieldRequirementsForNode(node) {
  const declared = Array.isArray(node?.output_field_requirements) ? node.output_field_requirements : [];
  if (declared.length > 0) return declared.filter(item => item && item.field_name);
  const contextFields = Array.isArray(node?.data_mapping_context?.output_field_requirements)
    ? node.data_mapping_context.output_field_requirements
    : [];
  if (contextFields.length > 0) return contextFields.filter(item => item && item.field_name);
  const fields = [];
  const outputs = Array.isArray(node?.output_model?.outputs) ? node.output_model.outputs : [];
  outputs.forEach(output => {
    const outputId = output.id || '';
    const schema = output.schema || {};
    const appendProperties = (properties, required, prefix) => {
      Object.entries(properties || {}).forEach(([name, childSchema]) => {
        const child = childSchema && typeof childSchema === 'object' ? childSchema : {};
        fields.push({
          output_id: outputId,
          field_path: `${prefix}.${name}`,
          field_name: name,
      title: child.title || name,
      description: child.description || child.desc || '',
      type: child.type || 'unknown',
      required: required.includes(name),
      source_schema_ref: outputId ? `skill_snapshot/output_schemas/${outputId}.json` : 'app.config.json:output_model',
      canonical_field_name: child.canonical_field_name || '',
    });
      });
    };
    if (schema.type === 'array') {
      const itemSchema = schema.items || {};
      appendProperties(itemSchema.properties || {}, itemSchema.required || [], 'items.properties');
      return;
    }
    appendProperties(schema.properties || {}, schema.required || [], 'properties');
  });
  return fields;
}

function isDataMappingNode(node) {
  if (!node) return false;
  const fields = outputFieldRequirementsForNode(node);
  const requiredData = Array.isArray(node.input_model?.required_data) ? node.input_model.required_data : [];
  const requirementIds = Array.isArray(node.data_requirements) ? node.data_requirements : [];
  return fields.length > 0 && (requiredData.length > 0 || requirementIds.length > 0);
}

function currentFieldMappingOverlay(node) {
  if (!node) return [];
  const draft = Array.isArray(state.fieldMappingDrafts[node.id]) ? state.fieldMappingDrafts[node.id] : [];
  const draftByPath = new Map(draft.map(item => [item.field_path || item.business_field || item.field_name, item]));
  const contract = contractFromDbAgentResult(dbAgentResultFor(node));
  const contractOverlay = Array.isArray(contract?.field_coverage_plan)
    ? contract.field_coverage_plan
    : Array.isArray(contract?.output_field_mapping_overlay) ? contract.output_field_mapping_overlay : [];
  const contractByPath = new Map(contractOverlay.map(item => [item.field_path || item.field_name, item]));
  return outputFieldRequirementsForNode(node).map(field => {
    const mapped = draftByPath.get(field.field_path) || draftByPath.get(field.field_name) || contractByPath.get(field.field_path) || contractByPath.get(field.field_name) || {};
    return {
      ...field,
      mapping_status: mapped.mapping_status || mapped.status || (mapped.source_field_path || mapped.api_field_path ? 'mapped' : 'unmapped'),
      api_field_path: mapped.api_field_path || mapped.source_field_path || '',
      api_field_name: mapped.api_field_name || '',
      api_field_type: mapped.api_field_type || '',
      source_api_id: mapped.source_api_id || mapped.api_id || '',
      source_api_name: mapped.source_api_name || mapped.api_name || '',
      source_field_path: mapped.source_field_path || mapped.api_field_path || '',
      source_role: mapped.source_role || (mapped.api_field_path || mapped.source_field_path ? 'api_field' : ''),
      source_kind: mapped.source_kind || (mapped.api_field_path || mapped.source_field_path ? 'api_doc_index' : ''),
      evidence_field_paths: Array.isArray(mapped.evidence_field_paths) ? mapped.evidence_field_paths.map(String) : [],
      available_evidence_fields: Array.isArray(mapped.available_evidence_fields) ? mapped.available_evidence_fields.map(String) : [],
      confidence: mapped.confidence ?? '',
      human_note: mapped.human_note || '',
      canonical_field_name: field.canonical_field_name || mapped.canonical_field_name || '',
      candidate_field_options: Array.isArray(mapped.candidate_field_options) ? mapped.candidate_field_options : Array.isArray(mapped.candidates) ? mapped.candidates : [],
      confirmed: Boolean(mapped.confirmed || mapped.human_confirmed || mapped.status === 'confirmed' || mapped.mapping_status === 'confirmed'),
      human_confirmed: Boolean(mapped.confirmed || mapped.human_confirmed || mapped.status === 'confirmed' || mapped.mapping_status === 'confirmed'),
    };
  });
}

function coverageSummaryForFields(fields) {
  const isCovered = field => ['mapped', 'suggested', 'confirmed', 'manual_fill', 'derived', 'derived_or_manual_required'].includes(String(field.mapping_status || field.status || ''));
  return {
    total: fields.length,
    mapped: fields.filter(isCovered).length,
    confirmed: fields.filter(field => field.confirmed || field.human_confirmed || String(field.mapping_status || '') === 'confirmed').length,
    missingRequired: fields.filter(field => field.required && !isCovered(field)).length,
    derived: fields.filter(field => String(field.mapping_status || '') === 'derived_or_manual_required' || field.source_kind === 'pi_derived').length,
  };
}

const PI_HIGH_CONFIDENCE = 0.9;
const PI_MID_CONFIDENCE = 0.7;
const PI_MAPPING_ADVICE_SCHEMA_VERSION = 'pi-data-mapping-advice-v1';

// 从 PI advice 建立 field_path/field_name 双键索引，供工作台逐行内联建议。
function fieldAdviceIndexForNode(node) {
  const advice = state.piAgentResults[node.id]?.advice;
  const list = Array.isArray(advice?.field_advice) ? advice.field_advice : [];
  const index = new Map();
  for (const item of list) {
    if (item.field_path) index.set(item.field_path, item);
    if (item.field_name) index.set(item.field_name, item);
  }
  return index;
}

function adviceBadge(advice) {
  if (!advice) return '';
  const map = {
    ok: { cls: 'done', text: 'PI ✓ 一致' },
    needs_review: { cls: 'waiting', text: 'PI ⚠ 待审' },
    missing: { cls: 'failed', text: 'PI ✗ 缺失' },
    better_alternative: { cls: 'waiting', text: 'PI ↺ 更优' },
  };
  const meta = map[advice.judgement] || { cls: 'waiting', text: `PI ${advice.judgement}` };
  const conf = Number.isFinite(Number(advice.confidence)) ? ` ${(Number(advice.confidence) * 100).toFixed(0)}%` : '';
  return `<span class="badge ${meta.cls}" title="${escapeHtml(advice.reason || '')}">${meta.text}${conf}</span>`;
}

// 快捷操作：高置信 ok 可直接应用；缺失/更优可标记人工；均只写 draft overlay。
function adviceQuickActions(field, advice) {
  if (!advice) return '';
  const key = escapeHtml(field.field_path || field.field_name || '');
  const canApply = ['ok', 'better_alternative'].includes(advice.judgement) && advice.suggested_source_field_path;
  const buttons = [];
  if (canApply) buttons.push(`<button class="link-button" data-advice-action="apply" data-advice-field="${key}">应用</button>`);
  buttons.push(`<button class="link-button" data-advice-action="manual" data-advice-field="${key}">人工</button>`);
  buttons.push(`<button class="link-button" data-advice-action="ignore" data-advice-field="${key}">忽略</button>`);
  return buttons.join(' ');
}

function renderPiAdviceSummary(node) {
  const result = state.piAgentResults[node.id];
  const busy = Boolean(state.piAgentBusy[node.id]);
  if (busy) return '<p class="save-status saving">PI 正在生成逐字段建议...</p>';
  const advice = result?.advice;
  if (!advice) return `${renderPiAgentStatus()}<p class="muted">尚未生成 PI 建议。字段覆盖由一键方案完成；右侧 Agent 只针对错配、低置信和派生字段给出逐字段建议。</p>`;
  const statusText = {
    ok: '整体可用', needs_review: '需人工审核', needs_input: '需补充输入', blocked: '受阻', unavailable: 'PI 未就绪（确定性兜底）',
  }[advice.summary?.status] || advice.summary?.status || '';
  const degraded = advice.source?.provider !== 'pi_agent' || advice.source?.degraded;
  const questions = Array.isArray(advice.questions_for_user) && advice.questions_for_user.length
    ? `<ul class="muted">${advice.questions_for_user.map(q => `<li>${escapeHtml(q)}</li>`).join('')}</ul>`
    : '';
  return `
    <div class="pi-advice-summary">
      <p class="save-status ${degraded ? 'waiting' : 'done'}">PI 判断：${escapeHtml(statusText)}${degraded ? '（降级/兜底）' : ''}</p>
      ${advice.summary?.text ? `<p class="muted">${escapeHtml(advice.summary.text)}</p>` : ''}
      ${questions}
    </div>
  `;
}

function renderFieldCandidateOptions(field) {
  const candidates = Array.isArray(field.candidate_field_options) ? field.candidate_field_options : [];
  if (candidates.length === 0) return '<span class="muted">暂无候选字段</span>';
  return `
    <details>
      <summary>候选字段 ${candidates.length}</summary>
      <div class="candidate-field-list">
        ${candidates.map(candidate => `
          <button class="link-button candidate-field-option"
            data-candidate-action="apply"
            data-candidate-field="${escapeHtml(field.field_path || field.field_name || '')}"
            data-candidate-api-id="${escapeHtml(candidate.source_api_id || '')}"
            data-candidate-api-name="${escapeHtml(candidate.source_api_name || '')}"
            data-candidate-path="${escapeHtml(candidate.source_field_path || '')}"
            data-candidate-name="${escapeHtml(candidate.api_field_name || '')}"
            data-candidate-type="${escapeHtml(candidate.api_field_type || '')}"
            data-candidate-confidence="${escapeHtml(candidate.confidence ?? '')}">
            ${escapeHtml(candidate.source_api_name || candidate.source_api_id || 'API')} · ${escapeHtml(candidate.source_field_path || candidate.api_field_name || '')} · ${escapeHtml(candidate.confidence ?? '')}
          </button>
        `).join('')}
      </div>
    </details>
  `;
}

function apiResponseFieldCatalogForNode(node) {
  const result = dbAgentResultFor(node);
  const contract = contractFromDbAgentResult(result) || {};
  const fromPayload = Array.isArray(result?.payload?.api_response_field_catalog) ? result.payload.api_response_field_catalog : [];
  if (fromPayload.length > 0) return fromPayload;
  const fromContract = Array.isArray(contract.api_response_field_catalog) ? contract.api_response_field_catalog : [];
  if (fromContract.length > 0) return fromContract;
  const cards = Array.isArray(result?.payload?.selected_api_asset_cards)
    ? result.payload.selected_api_asset_cards
    : Array.isArray(contract.selected_api_asset_cards) ? contract.selected_api_asset_cards : [];
  const catalog = [];
  cards.forEach(card => {
    const fields = Array.isArray(card?.response_schema?.fields) ? card.response_schema.fields : [];
    fields.forEach(field => {
      catalog.push({
        source_api_id: card.api_id || '',
        source_api_name: card.name || card.api_id || '',
        source_field_path: field.path || field.name || '',
        api_field_name: field.name || '',
        api_field_type: field.type || 'unknown',
        description: field.desc || field.description || '',
      });
    });
  });
  return catalog;
}

function renderApiFieldBrowser(node, field) {
  const catalog = apiResponseFieldCatalogForNode(node);
  const fieldKey = field.field_path || field.field_name || '';
  if (catalog.length === 0) {
    return '<p class="muted">先点击「一键生成字段覆盖方案」获取 API 返回字段目录。</p>';
  }
  const filterKey = `${node.id}:${fieldKey}`;
  const options = catalog.map((item, index) => ({ item, index })).slice(0, 120);
  return `
    <details class="api-field-browser">
      <summary>浏览返回字段</summary>
      <label class="field-row compact">
        <span>筛选 API 返回字段</span>
        <input data-api-field-filter="${escapeHtml(fieldKey)}" value="${escapeHtml(state.apiFieldBrowserFilters[filterKey] || '')}" placeholder="输入字段名、API 或描述" />
      </label>
      <select data-api-field-select="${escapeHtml(fieldKey)}">
        ${options.map(({ item, index }) => `
          <option value="${index}" data-api-field-search="${escapeHtml([item.source_api_name, item.source_api_id, item.source_field_path, item.api_field_name, item.description].join(' ').toLowerCase())}">
            ${escapeHtml(item.source_api_name || item.source_api_id || 'API')} · ${escapeHtml(item.source_field_path || item.api_field_name || '')} · ${escapeHtml(item.description || item.api_field_type || '')}
          </option>
        `).join('')}
      </select>
      <button class="link-button" data-api-field-browser-action="apply" data-api-field-browser-field="${escapeHtml(fieldKey)}" ${options.length ? '' : 'disabled'}>应用选中字段</button>
    </details>
  `;
}

function renderOutputFieldMappingWorkbench(node) {
  if (!isDataMappingNode(node)) return '';
  const fields = currentFieldMappingOverlay(node);
  if (fields.length === 0) return '';
  const saveStatus = state.saveStatus[node.id];
  const summary = coverageSummaryForFields(fields);
  const adviceIndex = fieldAdviceIndexForNode(node);
  const busy = Boolean(state.piAgentBusy[node.id] || state.dbAgentBusy[node.id]);
  return `
    <div class="detail-section field-mapping-workbench">
      <h3>字段覆盖工作台</h3>
      <p class="muted">这里展示生成过程从产物 Schema / 数据需求转译出的字段要求；点击一键生成后，系统会直接自动选择 API 并填充字段，最终由用户审核确认。</p>
      ${saveStatus ? `<p class="save-status ${escapeHtml(saveStatus.status || '')}">${escapeHtml(saveStatus.message || '')}</p>` : ''}
      <div class="coverage-summary">
        <span class="badge">字段 ${summary.total}</span>
        <span class="badge done">已覆盖 ${summary.mapped}</span>
        <span class="badge done">已确认 ${summary.confirmed}</span>
        <span class="badge waiting">派生/人工 ${summary.derived}</span>
        <span class="badge ${summary.missingRequired ? 'failed' : 'done'}">必填未覆盖 ${summary.missingRequired}</span>
      </div>
      <div class="workbench-actions">
        <button class="secondary" data-workbench-action="suggest" ${busy ? 'disabled' : ''}>一键生成字段覆盖方案</button>
      </div>
      ${renderPiAdviceSummary(node)}
      <div class="artifact-table-wrap">
        <table class="artifact-table">
          <thead>
            <tr>
              <th>字段</th>
              <th>覆盖状态</th>
              <th>来源 API</th>
              <th>API 字段</th>
              <th>候选字段</th>
              <th>置信度</th>
              <th>PI 建议</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            ${fields.map(field => {
              const advice = adviceIndex.get(field.field_path) || adviceIndex.get(field.field_name) || null;
              const rowCls = advice?.judgement === 'missing' || ['unmapped', 'missing'].includes(field.mapping_status) ? 'missing' : '';
              return `
              <tr class="${rowCls}">
                <td>${escapeHtml(field.title || field.field_name)} ${adviceBadge(advice)}<br><span class="muted">${escapeHtml(field.field_path || '')}${field.required ? ' · 必填' : ''}</span></td>
                <td>${escapeHtml(field.confirmed ? 'confirmed' : field.mapping_status || 'unmapped')}</td>
                <td>${escapeHtml(field.source_api_name || field.source_api_id || field.source_kind || '待选择')}</td>
                <td>${escapeHtml(field.source_field_path || field.api_field_path || '待选择')}</td>
                <td>${renderFieldCandidateOptions(field)}${renderApiFieldBrowser(node, field)}</td>
                <td>${escapeHtml(field.confidence === '' ? '-' : field.confidence)}</td>
                <td>${advice ? `<details><summary>${escapeHtml(advice.reason || advice.judgement)}</summary><p class="muted">建议来源：${escapeHtml(advice.suggested_source_api_id || '-')} · ${escapeHtml(advice.suggested_source_field_path || '-')}</p></details>` : '<span class="muted">-</span>'}</td>
                <td><button class="link-button" data-correction-target="${escapeHtml(field.field_path || field.field_name || '')}">纠错</button> ${adviceQuickActions(field, advice)}</td>
              </tr>
            `;
            }).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function renderEvidenceModel(node) {
  const evidence = node.evidence_model || {};
  return `
    <p class="muted">required：${listText(evidence.required || [], '无')}</p>
    <details>
      <summary>Evidence contract</summary>
      <pre class="json-output">${escapeHtml(JSON.stringify(evidence.contract || {}, null, 2))}</pre>
    </details>
  `;
}

function renderToolModel(node) {
  const tool = node.tool_model || {};
  const bindings = Array.isArray(tool.bindings) ? tool.bindings : [];
  if (bindings.length === 0) {
    return `<p class="muted">effective_mode：${escapeHtml(tool.effective_mode || 'manual_upload_only')} · 无绑定工具。</p>`;
  }
  return `
    <p class="muted">effective_mode：${escapeHtml(tool.effective_mode || 'manual_upload_only')}</p>
    ${bindings.map(binding => `
      <article class="model-card">
        <h4>${escapeHtml(binding.data_requirement_id || 'tool_binding')}</h4>
        <p class="muted">primary：${escapeHtml(binding.declared_primary_tool || '未声明')} · status：${escapeHtml(binding.status || 'available')}</p>
        <p class="muted">fallback：${listText(binding.declared_fallback_tools || [], '无')}</p>
      </article>
    `).join('')}
  `;
}

function renderExecutionMarkdown(markdown, emptyText = '暂无') {
  const text = String(markdown || '').trim();
  if (!text) return `<p class="muted">${escapeHtml(emptyText)}</p>`;
  return `<div class="markdown-output compact">${renderMarkdown(text)}</div>`;
}

function renderExecutionForm(node) {
  const view = node.node_execution_view || {};
  const fields = nodeActionFields(node);
  if (fields.length === 0) {
    return '<p class="muted">当前节点没有可填写字段。</p>';
  }
  const draft = state.nodeDrafts[node.id] || {};
  const saveStatus = state.saveStatus[node.id];
  return `
    <div class="execution-form" data-node-form="${escapeHtml(node.id)}">
      ${fields.map(field => {
        const id = field.id || field.label || '';
        const value = draft[id] || '';
        return `
          <label class="field-row">
            <span>${escapeHtml(field.label || id)}</span>
            <input data-node-field="${escapeHtml(id)}" value="${escapeHtml(value)}" placeholder="${escapeHtml(field.description || '')}" />
            ${field.description ? `<small>${escapeHtml(field.description)}</small>` : ''}
          </label>
        `;
      }).join('')}
      <button class="secondary" id="save-node-draft">保存并生成产物</button>
      ${saveStatus ? `<p class="save-status ${escapeHtml(saveStatus.status || '')}">${escapeHtml(saveStatus.message || '')}</p>` : ''}
    </div>
  `;
}

function renderArtifactRowsTable(artifact) {
  const rows = Array.isArray(artifact.rows) ? artifact.rows : [];
  if (rows.length === 0) return '<p class="muted">暂无表格行。</p>';
  if (artifact.schema_version === 'data-table-confirmed-v1') {
    const fields = Array.isArray(artifact.fields) ? artifact.fields : [];
    return `
      <div class="artifact-table-wrap">
        <table class="artifact-table product-table">
          <thead><tr><th>#</th>${fields.map(field => `<th>${escapeHtml(field.title || field.field_name || field.field_path || '')}</th>`).join('')}</tr></thead>
          <tbody>${rows.map((row, index) => `<tr><td>${index + 1}</td>${fields.map(field => `<td>${renderPreviewCell(row, { label: field.title || field.field_name || field.field_path, candidates: [collaborationFieldPath(field)] })}</td>`).join('')}</tr>`).join('')}</tbody>
        </table>
      </div>
      <p class="muted">确认 revision ${escapeHtml(artifact.workspace_revision ?? '')} · ${escapeHtml(artifact.row_count || rows.length)} 行 · 空值 ${escapeHtml(artifact.missing_cell_count || 0)}</p>
    `;
  }
  return `
    <div class="artifact-table-wrap">
      <table class="artifact-table">
        <thead>
          <tr>
            <th>字段</th>
            <th>填写内容</th>
            <th>填写要求</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map(row => `
            <tr class="${row.status === 'missing' ? 'missing' : ''}">
              <td>${escapeHtml(row.label || row.field_id)}</td>
              <td>${escapeHtml(row.value || '未填写')}</td>
              <td>${escapeHtml(row.requirement || '未声明')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
}

function renderDraftArtifactTable(artifact) {
  const rows = Array.isArray(artifact.rows) ? artifact.rows : [];
  if (rows.length === 0) return '<p class="muted">暂无可生成字段。</p>';
  return `
    <article class="model-card generated-artifact">
      <h4>${escapeHtml(artifact.title || '节点中间产物')}</h4>
      <p class="muted">status：${escapeHtml(artifact.status || 'ready')} · source：${escapeHtml(artifact.source || 'browser_manual_form_save')}</p>
      ${artifact.missing_required?.length ? `<p class="error-text">待补充：${listText(artifact.missing_required, '无')}</p>` : '<p class="muted">已生成，可继续运行或导出。</p>'}
      ${renderArtifactRowsTable(artifact)}
    </article>
  `;
}

function renderExecutionView(node) {
  const view = node.node_execution_view || {};
  const action = view.action || {};
  const verification = view.verification || {};
  const artifact = view.artifact || {};
  const generatedArtifact = currentDraftArtifact(node);
  const checks = Array.isArray(verification.checks) ? verification.checks : [];
  return `
    <div class="detail-section execution-view">
      <h3>分析目标</h3>
      ${renderExecutionMarkdown(view.goal?.markdown, '暂无分析目标。')}
    </div>
    <div class="detail-section execution-view">
      <h3>执行动作</h3>
      ${renderExecutionMarkdown(action.markdown, '暂无执行动作。')}
    </div>
    <div class="detail-section execution-view">
      <h3>用户填写区</h3>
      ${renderExecutionForm(node)}
    </div>
    <div class="detail-section execution-view">
      <h3>验证标准</h3>
      ${checks.length > 0 ? `
        <ul class="meta-list">
          ${checks.map(check => `<li><strong>${escapeHtml(check.id || '判断项')}</strong>：${escapeHtml(check.standard || '')}</li>`).join('')}
        </ul>
      ` : renderExecutionMarkdown(verification.markdown, '暂无验证标准。')}
    </div>
    <div class="detail-section execution-view">
      <h3>中间产物</h3>
      <p>${escapeHtml(artifact.title || '节点中间产物')}</p>
      ${renderExecutionMarkdown(artifact.markdown, '暂无产物说明。')}
      ${generatedArtifact ? renderDraftArtifactTable(generatedArtifact) : '<p class="muted">保存填写内容后会在这里生成结构化产物表。</p>'}
    </div>
  `;
}

function isDataAnalysisNode(node) {
  if (!node) return false;
  if (node.analysis_node_view?.node_kind === 'data_analysis') return true;
  return isDataMappingNode(node);
}

function analysisNodeViewFor(node) {
  if (node?.analysis_node_view && typeof node.analysis_node_view === 'object') return node.analysis_node_view;
  const fields = outputFieldRequirementsForNode(node);
  const execution = node?.node_execution_view || {};
  return {
    schema_version: 'analysis-node-view-v1',
    node_id: node?.id || '',
    node_kind: isDataMappingNode(node) ? 'data_analysis' : 'standard',
    purpose_model: {
      title: execution.workflow_title || node?.name || node?.id || '',
      purpose: execution.goal?.markdown || '',
      business_questions: [],
      success_criteria: [],
    },
    input_model: {
      data_sources: Array.isArray(node?.input_model?.required_data) ? node.input_model.required_data.map(item => ({
        name: item.id || 'data_requirement',
        description: item.description || item.id || '',
      })) : [],
      upstream_artifacts: Array.isArray(node?.depends_on) ? node.depends_on.map(id => ({ node_id: id, artifact_title: '', required_fields: [] })) : [],
      data_requirement_ids: Array.isArray(node?.data_requirements) ? node.data_requirements : [],
      api_matching: { provider: 'api_doc_matcher', strategy: 'field_coverage_rerank', status: 'not_started' },
    },
    execution_plan: {
      steps: Array.isArray(execution.action?.steps)
        ? execution.action.steps.map((step, index) => ({ step_id: `step_${index + 1}`, title: `步骤${index + 1}`, instruction: step, requires: [], produces: [], human_review_required: true }))
        : [],
    },
    data_output_model: {
      output_id: node?.outputs?.[0] || 'node_output',
      title: node?.output_model?.outputs?.[0]?.title || '数据表产物',
      fields,
      coverage_summary: coverageSummaryForFields(currentFieldMappingOverlay(node)),
      contract_ref: '',
    },
    insight_output_model: {
      title: `${node?.name || node?.id || '节点'}分析结论`,
      requirements: [],
      draft: { status: 'not_started', text: '', evidence_refs: [], risks: [] },
      human_confirmation: { status: 'unconfirmed' },
    },
    verification_model: { checks: [] },
    source_trace: node?.source_trace || {},
  };
}

function renderAnalysisPurpose(view) {
  const purpose = view.purpose_model || {};
  const questions = Array.isArray(purpose.business_questions) ? purpose.business_questions : [];
  const success = Array.isArray(purpose.success_criteria) ? purpose.success_criteria : [];
  return `
    <div class="analysis-section">
      <h3>节点目标</h3>
      <h4>${escapeHtml(purpose.title || '数据分析节点')}</h4>
      <p>${escapeHtml(purpose.purpose || '暂无目的说明。')}</p>
      ${questions.length ? `<p class="muted">业务问题：${listText(questions, '无')}</p>` : ''}
      ${success.length ? `<p class="muted">成功标准：${listText(success, '无')}</p>` : ''}
    </div>
  `;
}

function renderAnalysisInputReadiness(view) {
  const input = view.input_model || {};
  const dataSources = Array.isArray(input.data_sources) ? input.data_sources : [];
  const upstream = Array.isArray(input.upstream_artifacts) ? input.upstream_artifacts : [];
  const requirementIds = Array.isArray(input.data_requirement_ids) ? input.data_requirement_ids : [];
  const missing = Array.isArray(input.missing_params) ? input.missing_params : [];
  const api = input.api_matching || {};
  return `
    <div class="analysis-section">
      <h3>输入准备</h3>
      <div class="analysis-grid">
        <article>
          <h4>数据来源</h4>
          ${dataSources.length ? `<ul class="meta-list">${dataSources.map(item => `<li><strong>${escapeHtml(item.name || '数据来源')}</strong>：${escapeHtml(item.description || '')}</li>`).join('')}</ul>` : '<p class="muted">暂无数据来源声明。</p>'}
        </article>
        <article>
          <h4>上游产物</h4>
          ${upstream.length ? `<ul class="meta-list">${upstream.map(item => `<li>${escapeHtml(item.node_id || '')}${item.artifact_title ? ` · ${escapeHtml(item.artifact_title)}` : ''}${Array.isArray(item.required_fields) && item.required_fields.length ? ` · ${listText(item.required_fields, '无')}` : ''}</li>`).join('')}</ul>` : '<p class="muted">无上游产物依赖。</p>'}
        </article>
      </div>
      <p class="muted">数据需求：${listText(requirementIds, '无')} · matcher：${escapeHtml(api.provider || 'api_doc_matcher')} / ${escapeHtml(api.strategy || 'field_coverage_rerank')}</p>
      ${missing.length ? `<p class="error-text">缺失参数：${listText(missing, '无')}</p>` : '<p class="muted">缺失参数会在字段覆盖或右侧 Agent 中提示。</p>'}
    </div>
  `;
}

function renderAnalysisFieldCoverage(node, view) {
  return `
    <div class="analysis-section">
      <h3>字段覆盖</h3>
      ${renderOutputFieldMappingWorkbench(node)}
    </div>
  `;
}

function renderAnalysisExecutionPlan(view) {
  const steps = Array.isArray(view.execution_plan?.steps) ? view.execution_plan.steps : [];
  return `
    <div class="analysis-section">
      <h3>执行动作</h3>
      ${steps.length ? `
        <ol class="analysis-steps">
          ${steps.map(step => `
            <li>
              <strong>${escapeHtml(step.title || step.step_id || '步骤')}</strong>
              <p>${escapeHtml(step.instruction || '')}</p>
              <p class="muted">依赖：${listText(step.requires || [], '无')} · 产物：${listText(step.produces || [], '无')} · 人审：${step.human_review_required ? '是' : '否'}</p>
            </li>
          `).join('')}
        </ol>
      ` : '<p class="muted">暂无执行动作。</p>'}
    </div>
  `;
}

function renderCategoryResolutionSummary(result) {
  const resolution = result?.category_resolution || {};
  if (!resolution.requested_name && !resolution.category_id) return '';
  const statusClass = resolution.status === 'resolved'
    ? 'done'
    : ['blocked', 'needs_confirmation'].includes(resolution.status)
      ? 'failed'
      : 'waiting';
  return `
    <div class="category-resolution-summary">
      <h5>类目解析</h5>
      <p>
        <span class="badge ${statusClass}">${escapeHtml(resolution.status || '')}</span>
        <strong>${escapeHtml(resolution.requested_name || resolution.category_name || '-')}</strong>
        <span class="muted">→ 标准类目 ${escapeHtml(resolution.canonical_name || resolution.category_name || '-')} → cid=${escapeHtml(resolution.category_id || '待确认')}</span>
      </p>
      <p class="muted">类目证据：${escapeHtml(resolution.source_api_id || resolution.provider || '-')} · 匹配方式：${escapeHtml(resolution.match_kind || '-')} · 置信度：${escapeHtml(resolution.confidence ?? '-')}</p>
      <p class="muted">live 校验：${escapeHtml(resolution.verification_api_id || '未执行')} · evidence：${escapeHtml(resolution.verification_evidence_ref || resolution.evidence_ref || '-')}</p>
      ${resolution.blocked_reason ? `<p class="error-text">${escapeHtml(resolution.blocked_reason)}</p>` : ''}
    </div>
  `;
}

function renderKeywordCategoryAttempts(result) {
  const attempts = Array.isArray(result?.category_attempts) ? result.category_attempts : [];
  const context = result?.category_context || {};
  if (attempts.length === 0 && !context.canonical_name) return '';
  return `
    <div class="category-resolution-summary keyword-category-attempts">
      <h5>关键词类目取数</h5>
      <p>
        <strong>${escapeHtml(context.requested_name || '-')}</strong>
        <span class="muted">→ ${escapeHtml(context.canonical_name || '-')} · cid=${escapeHtml(context.category_id || '-')} · 来源 ${escapeHtml(context.source_node_id || '-')} revision ${escapeHtml(context.source_revision ?? '-')}</span>
      </p>
      <p class="muted">最终使用：${escapeHtml(result?.selected_category_name || '无非空结果')} · 尝试 ${attempts.length} 次</p>
      ${attempts.length ? `
        <div class="artifact-table-wrap">
          <table class="artifact-table">
            <thead><tr><th>API</th><th>类目参数</th><th>结果</th><th>返回行</th><th>请求</th></tr></thead>
            <tbody>
              ${attempts.map(item => `
                <tr>
                  <td>${escapeHtml(item.api_id || '-')}</td>
                  <td>${escapeHtml(item.category_name || '-')}</td>
                  <td><span class="badge ${item.status === 'success' ? 'done' : item.status === 'blocked' ? 'failed' : 'waiting'}">${escapeHtml(item.status || '-')}</span><br><span class="muted">${escapeHtml(item.reason || '')}</span></td>
                  <td>${escapeHtml(item.rows_returned ?? 0)}</td>
                  <td><span class="muted">${escapeHtml(item.request_debug?.url || '-')}</span></td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      ` : ''}
    </div>
  `;
}

function renderProductDetailEnrichmentSummary(result) {
  const detail = result?.detail_enrichment;
  if (!detail || typeof detail !== 'object') return '';
  const summary = detail.summary || {};
  const sources = Array.isArray(result?.field_sources) ? result.field_sources : [];
  const fieldCoverage = fieldName => {
    const source = sources.find(item => String(item.field_name || '') === fieldName) || {};
    return `${Number(source.rows_with_value || 0)}/${Number(source.rows_with_value || 0) + Number(source.rows_missing_value || 0)}`;
  };
  const itemStatuses = Array.isArray(detail.item_statuses) ? detail.item_statuses : [];
  const exceptions = itemStatuses.filter(item => item.status !== 'success');
  const temporal = detail.temporal_alignment || {};
  const temporalText = temporal.status === 'fallback_to_recent_available'
    ? `最近可用快照：${temporal.selected_month || '-'}（目标 ${temporal.target_month || '-'}）`
    : temporal.status === 'aligned'
      ? `月份对齐：${temporal.selected_month || temporal.target_month || '-'}`
      : temporal.status === 'not_verifiable'
        ? '最近可用快照 · 月份不可验证'
        : `最近可用快照：${temporal.status || '未取到'}`;
  return `
    <div class="detail-enrichment-summary">
      <h5>商品详情补全</h5>
      <div class="coverage-summary">
        <span class="badge">计划 ${escapeHtml(summary.requested ?? 0)}</span>
        <span class="badge done">成功 ${escapeHtml(summary.success ?? 0)}</span>
        <span class="badge waiting">空结果 ${escapeHtml(summary.empty ?? 0)}</span>
        <span class="badge ${Number(summary.failed || 0) > 0 ? 'failed' : ''}">失败 ${escapeHtml(summary.failed ?? 0)}</span>
        ${Number(summary.identity_mismatch || 0) > 0 ? `<span class="badge failed">ID 不一致 ${escapeHtml(summary.identity_mismatch)}</span>` : ''}
        <span class="badge">材质覆盖 ${escapeHtml(fieldCoverage('材质'))}</span>
        <span class="badge">场景覆盖 ${escapeHtml(fieldCoverage('场景'))}</span>
      </div>
      <p class="muted">API：${escapeHtml(detail.api_id || '-')} · 数据源：${escapeHtml(detail.selected_data_source || '-')} · ${escapeHtml(temporalText)}</p>
      <p class="muted">evidence：${escapeHtml(detail.evidence_ref || '-')}</p>
      ${exceptions.length ? `
        <details>
          <summary>未补全商品 ${exceptions.length}</summary>
          <ul class="meta-list">
            ${exceptions.slice(0, 20).map(item => `<li>${escapeHtml(item.correlation_id || '-')} · ${escapeHtml(item.status || '')}${item.error ? ` · ${escapeHtml(item.error)}` : ''}</li>`).join('')}
          </ul>
        </details>
      ` : ''}
    </div>
  `;
}

function requestParamBusinessLabel(item) {
  const status = String(item?.status || '');
  if (item?.business_param_label || item?.business_param) return item.business_param_label || item.business_param;
  if (status === 'runtime_injected') return '运行时身份注入';
  if (status === 'deferred') return '主榜单逐行绑定';
  if (status === 'runtime_resolved') return '运行时数据源校准';
  return '未匹配业务参数';
}

function requestParamDisplayValue(item) {
  const status = String(item?.status || '');
  if (status === 'runtime_injected') return '已注入（脱敏）';
  if (status === 'deferred') return item?.value || '由主榜单商品 ID 注入';
  if (status === 'runtime_resolved') return item?.resolved_value || item?.value || listText(item?.candidate_values || [], '待运行时选择');
  return item?.value || '';
}

function renderApiExecutionPlan(result) {
  const plans = Array.isArray(result?.api_execution_plan) ? result.api_execution_plan : [];
  if (plans.length === 0) return '<p class="muted">暂无 API 调用计划。</p>';
  return `
    <div class="artifact-table-wrap">
      <table class="artifact-table">
        <thead>
          <tr>
            <th>API</th>
            <th>状态</th>
            <th>请求参数绑定</th>
            <th>缺失 required</th>
            <th>字段</th>
            <th>请求信息</th>
          </tr>
        </thead>
        <tbody>
          ${plans.map(plan => `
            <tr>
              <td>${escapeHtml(plan.api_name || plan.api_id || '')}<br><span class="muted">${escapeHtml(plan.api_id || '')}</span></td>
              <td>
                ${escapeHtml(plan.status || '')}${plan.blocked_reason ? `<br><span class="muted">${escapeHtml(plan.blocked_reason)}</span>` : ''}
                <br><span class="muted">原始行：${escapeHtml(plan.rows_returned ?? 0)} · 有效行：${escapeHtml(plan.rows_accepted ?? plan.rows_returned ?? 0)}</span>
                <br><span class="muted">范围：${escapeHtml(plan.category_scope || '-')} · 范围校验：${escapeHtml(plan.scope_validation_status || '-')}</span>
                <br><span class="muted">执行角色：${escapeHtml(plan.execution_role || 'general')} · 数据月份：${escapeHtml(plan.selected_data_month || '-')}</span>
                ${plan.batch_summary ? `<br><span class="muted">详情批量：计划 ${escapeHtml(plan.batch_summary.requested ?? 0)} · 成功 ${escapeHtml(plan.batch_summary.success ?? 0)} · 空结果 ${escapeHtml(plan.batch_summary.empty ?? 0)} · 失败 ${escapeHtml(plan.batch_summary.failed ?? 0)}</span>` : ''}
              </td>
              <td>
                ${Array.isArray(plan.request_param_mapping) && plan.request_param_mapping.length ? `
                  <details open>
                    <summary>请求参数绑定 ${plan.request_param_mapping.length}</summary>
                    ${plan.category_resolution ? `
                      <p class="muted">类目解析：${escapeHtml(plan.category_resolution.status || '')} · ${escapeHtml(plan.category_resolution.direction || '')} · name=${escapeHtml(plan.category_resolution.category_name || '')} · id=${escapeHtml(plan.category_resolution.category_id || '')} ${plan.category_resolution.blocked_reason ? `· ${escapeHtml(plan.category_resolution.blocked_reason)}` : ''}</p>
                      <p class="muted">解析 API：${escapeHtml(plan.category_resolution.source_api_id || '-')} · ${escapeHtml(plan.category_resolution.resolver_provider || '')}</p>
                      <p class="muted">字段路径：name=${escapeHtml(plan.category_resolution.source_field_paths?.name || '-')} · id=${escapeHtml(plan.category_resolution.source_field_paths?.id || '-')}</p>
                      ${plan.category_resolution.request_debug ? `<details><summary>类目解析请求</summary><p class="muted">${escapeHtml(plan.category_resolution.request_debug.url || '')}</p><pre class="json-output compact-json">${escapeHtml(JSON.stringify(plan.category_resolution.request_debug.query || {}, null, 2))}</pre></details>` : ''}
                    ` : ''}
                    <ul class="meta-list">
                      ${plan.request_param_mapping.map(item => `
                        <li>
                          <strong>${escapeHtml(item.api_param || '')}</strong>
                          <span class="badge ${item.status === 'bound' ? 'done' : item.status === 'missing' ? 'failed' : 'waiting'}">${escapeHtml(item.status || '')}</span>
                          <br><span class="muted">${escapeHtml(requestParamBusinessLabel(item))} · ${escapeHtml(requestParamDisplayValue(item))} · ${escapeHtml(item.missing_reason || item.binding_method || '')}</span>
                        </li>
                      `).join('')}
                    </ul>
                  </details>
                ` : '<span class="muted">无参数声明</span>'}
              </td>
              <td>${listText(plan.missing_required_params || [], '无')}</td>
              <td>${listText(plan.source_fields || [], '无')}</td>
              <td>
                <details>
                  <summary>请求 URL</summary>
                  <p class="muted">${escapeHtml(plan.request_debug?.url || '未调用或 worker 未返回 request debug')}</p>
                  <p class="muted">请求 query</p>
                  <pre class="json-output compact-json">${escapeHtml(JSON.stringify(plan.request_debug?.query || plan.params || {}, null, 2))}</pre>
                </details>
                ${Array.isArray(plan.date_attempts) && plan.date_attempts.length ? `
                  <details>
                    <summary>月份探测 ${plan.date_attempts.length} 次</summary>
                    <ul class="meta-list">
                      ${plan.date_attempts.map(item => `<li>${escapeHtml(item.start_date || '-')} · ${escapeHtml(item.rows_returned ?? 0)} 行 · ${escapeHtml(item.status || '')}</li>`).join('')}
                    </ul>
                  </details>
                ` : ''}
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
}

function previewCellValue(row, field) {
  for (const key of field.candidates || []) {
    if (row && typeof row === 'object' && Object.prototype.hasOwnProperty.call(row, key)) return row[key];
  }
  return undefined;
}

function isImagePreviewField(field, value) {
  const text = [
    field?.label,
    ...(Array.isArray(field?.candidates) ? field.candidates : []),
  ].filter(Boolean).join(' ').toLowerCase();
  const raw = String(value || '').trim();
  if (!raw || !/^https?:\/\//i.test(raw)) return false;
  const fieldLooksLikeImage = /商品主图|主图|image|img|pic|picture|pictures_linking|goods_img|product_image/.test(text);
  const urlLooksLikeImage = /\.(jpg|jpeg|png|webp|gif)(\?|#|$)/i.test(raw) || /alicdn|img\.|image|pic|picture/i.test(raw);
  return fieldLooksLikeImage || urlLooksLikeImage;
}

function renderPreviewCell(row, field) {
  const value = previewCellValue(row, field);
  const empty = value === undefined || value === null || String(value).trim() === '';
  if (empty) return '<span class="muted">待补齐</span>';
  const text = String(value);
  if (isImagePreviewField(field, text)) {
    return `<a class="product-thumb-link" href="${escapeHtml(text)}" target="_blank" rel="noreferrer"><img class="product-thumb" src="${escapeHtml(text)}" alt="${escapeHtml(field.label || '商品图片')}" loading="lazy"></a>`;
  }
  if (/^https?:\/\//i.test(text)) {
    return `<a href="${escapeHtml(text)}" target="_blank" rel="noreferrer">${escapeHtml(text)}</a>`;
  }
  return escapeHtml(text);
}

function collaborationFieldPath(field) {
  return String(field?.field_name || field?.title || field?.field_path || '');
}

function tableCellKey(rowId, fieldPath) {
  return `${rowId}\u0000${fieldPath}`;
}

function dataTableSelectionFor(nodeId) {
  return state.tableSelections[nodeId] || { scope_mode: 'cells', cells: [] };
}

function isTableCellSelected(nodeId, rowId, fieldPath) {
  const selection = dataTableSelectionFor(nodeId);
  if (selection.scope_mode === 'whole_table') return true;
  if (selection.scope_mode === 'column') return (selection.field_paths || []).includes(fieldPath);
  if (selection.scope_mode === 'row') return (selection.row_ids || []).includes(rowId);
  return (selection.cells || []).some(item => item.row_id === rowId && item.field_path === fieldPath);
}

function cellOverrideFor(workspace, rowId, fieldPath) {
  return workspace?.cell_overrides?.[rowId]?.[fieldPath] || null;
}

function renderEditableCellValue(value, field, editing) {
  if (editing) {
    const type = String(field?.type || 'string');
    if (type === 'single_select') {
      const options = Array.isArray(field.options) ? field.options : [];
      return `<select class="table-cell-editor" data-table-cell-editor><option value=""></option>${options.map(option => `<option value="${escapeHtml(option)}" ${String(value ?? '') === String(option) ? 'selected' : ''}>${escapeHtml(option)}</option>`).join('')}</select>`;
    }
    const inputType = type === 'number' ? 'number' : type === 'url' || type === 'image' ? 'url' : 'text';
    return `<input class="table-cell-editor" data-table-cell-editor type="${inputType}" value="${escapeHtml(value ?? '')}">`;
  }
  return renderPreviewCell({ value }, { label: field.title || field.field_name || field.field_path, candidates: ['value'] });
}

function renderSelectedCellActionBar(nodeId, payload) {
  const selection = dataTableSelectionFor(nodeId);
  const cells = Array.isArray(selection.cells) ? selection.cells : [];
  if (selection.scope_mode !== 'cells' || cells.length !== 1) {
    return '<div class="cell-action-bar empty"><span class="muted">选择一个单元格后，可直接填写或加入 Agent 对话。</span></div>';
  }
  const cell = tableCellDescriptor(nodeId, cells[0].row_id, cells[0].field_path);
  const workspace = payload.workspace || {};
  const override = cellOverrideFor(workspace, cell.row_id, cell.field_path);
  const product = cell.product_name || cell.product_id || cell.row_id;
  const sourceLabel = override?.source_kind || cell.source_kind || 'missing';
  return `
    <div class="cell-action-bar" data-cell-action-bar>
      <div class="cell-action-context">
        <strong>${escapeHtml(product)}</strong>
        <span>${escapeHtml(cell.field_path)}</span>
        <span class="badge ${sourceLabel === 'missing' ? 'waiting' : 'done'}">${sourceLabel === 'missing' ? '待补充' : escapeHtml(sourceLabel)}</span>
        <span class="muted">当前值：${escapeHtml(cell.effective_value || '空')}</span>
      </div>
      <div class="cell-action-controls">
        <input data-cell-action-input value="${escapeHtml(cell.effective_value ?? '')}" aria-label="单元格填写内容" placeholder="输入该单元格的值">
        <button data-cell-action-save>保存</button>
        <button class="secondary" data-cell-add-to-chat>加入 Agent 对话</button>
        <button class="secondary" data-cell-action-restore ${override ? '' : 'disabled'}>恢复 API 原值</button>
      </div>
    </div>
  `;
}

function renderEditableDataTableWorkspace(nodeId, payload) {
  const workspace = payload.workspace || {};
  const rows = Array.isArray(payload.effective_rows) ? payload.effective_rows : [];
  const fields = Array.isArray(payload.effective_fields) ? payload.effective_fields : [];
  const pageSize = 10;
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  const currentPage = Math.min(Math.max(1, Number(state.dataTablePages[nodeId] || 1)), totalPages);
  const start = (currentPage - 1) * pageSize;
  const visibleRows = rows.slice(start, start + pageSize);
  const visibleMeta = (workspace.row_meta || []).slice(start, start + pageSize);
  const editingKey = state.tableEditing[nodeId] || '';
  const notice = state.collaborationNotices[nodeId];
  const enrichment = payload.agent_enrichment || {};
  const agentFillable = new Set(Array.isArray(enrichment.fillable_fields)
    ? enrichment.fillable_fields.map(String)
    : ['功能', '风格', '主图元素', '爆款原因', '产品类型']);
  const subjectLabel = enrichment.subject_kind === 'keyword' ? '关键词' : '商品';
  const targetCells = visibleRows.reduce((count, row) => count + fields.filter(field => {
    const fieldPath = collaborationFieldPath(field);
    return agentFillable.has(fieldPath) && !String(row[fieldPath] ?? '').trim();
  }).length, 0);
  const eligibleProducts = visibleRows.filter(row => fields.some(field => {
    const fieldPath = collaborationFieldPath(field);
    return agentFillable.has(fieldPath) && !String(row[fieldPath] ?? '').trim();
  })).length;
  const activeBatch = latestAgentBatch(nodeId);
  const batchRunning = agentBatchIsRunning(activeBatch);
  const confirmation = payload.confirmation;
  return `
    <div class="data-table-preview editable-data-table">
      <div class="coverage-summary table-workspace-toolbar">
        <span class="badge done">可编辑数据表</span>
        <span class="badge">${escapeHtml(rows.length)} 行</span>
        <span class="badge waiting">revision ${escapeHtml(workspace.revision ?? 0)}</span>
        <button class="secondary" data-table-undo ${Number(workspace.revision || 0) === 0 ? 'disabled' : ''}>撤销</button>
        <button class="secondary" data-table-add-field>添加扩展字段</button>
        <button class="secondary" data-select-whole-table>选择全表</button>
        ${enrichment.status ? `<span class="badge ${enrichment.status === 'agent_enrichment_complete' ? 'done' : enrichment.status === 'agent_enrichment_running' ? 'waiting' : ''}">${escapeHtml(enrichment.status)}</span>` : ''}
        <span class="batch-page-summary">当前页 ${visibleRows.length} 个${subjectLabel} · ${eligibleProducts} 个需要补齐 · ${targetCells} 个目标单元格</span>
        <button data-agent-batch-start data-page-number="${currentPage}" ${!targetCells || batchRunning ? 'disabled' : ''}>当前页一键填充</button>
        <button data-table-confirm-advance ${batchRunning || rows.length === 0 ? 'disabled' : ''}>确认当前表格并进入下一步</button>
      </div>
      ${confirmation?.status === 'confirmed' ? `<p class="save-status done">当前表格已确认 · ${escapeHtml(confirmation.row_count || 0)} 行 · revision ${escapeHtml(confirmation.workspace_revision ?? '')}</p>` : confirmation?.status === 'stale' ? '<p class="save-status waiting">表格确认已过期，请重新确认后进入下一步。</p>' : ''}
      ${notice ? `<p class="save-status ${escapeHtml(notice.status || 'waiting')}">${escapeHtml(notice.message || '')}</p>` : ''}
      <div class="artifact-table-wrap product-table-wrap" data-editable-table tabindex="0">
        <table class="artifact-table product-table">
          <thead><tr><th>#</th>${fields.map(field => {
            const fieldPath = collaborationFieldPath(field);
            const selected = dataTableSelectionFor(nodeId).scope_mode === 'column' && (dataTableSelectionFor(nodeId).field_paths || []).includes(fieldPath);
            return `<th class="${selected ? 'table-cell-selected' : ''}" data-select-table-column="${escapeHtml(fieldPath)}">${escapeHtml(field.title || field.field_name || fieldPath)}${field.source === 'user_extension' ? `<br><span class="muted">扩展字段</span><span class="extension-field-actions"><button class="link-button" data-extension-field-edit="${escapeHtml(fieldPath)}">编辑</button><button class="link-button" data-extension-field-delete="${escapeHtml(fieldPath)}">删除</button></span>` : ''}</th>`;
          }).join('')}</tr></thead>
          <tbody>
            ${visibleRows.map((row, rowOffset) => {
              const meta = visibleMeta[rowOffset] || {};
              const rowId = String(meta.row_id || `row:${start + rowOffset + 1}`);
              return `<tr><td data-select-table-row="${escapeHtml(rowId)}">${start + rowOffset + 1}</td>${fields.map(field => {
                const fieldPath = collaborationFieldPath(field);
                const key = tableCellKey(rowId, fieldPath);
                const value = row[fieldPath] ?? '';
                const override = cellOverrideFor(workspace, rowId, fieldPath);
                const sourceClass = override ? `cell-source-${escapeHtml(override.source_kind || 'manual')}` : (String(value).trim() ? 'cell-source-api' : 'cell-source-missing');
                return `<td tabindex="0" class="editable-table-cell ${sourceClass} ${isTableCellSelected(nodeId, rowId, fieldPath) ? 'table-cell-selected' : ''}" data-table-cell data-row-id="${escapeHtml(rowId)}" data-field-path="${escapeHtml(fieldPath)}" data-current-value="${escapeHtml(value)}" title="${override ? `${override.source_kind} · ${override.reason || '已覆盖 API 原值'}` : (String(value).trim() ? 'API 原值' : '缺失')}">${renderEditableCellValue(value, field, editingKey === key)}${override && editingKey !== key ? `<span class="cell-source-mark">${override.source_kind === 'pi_derived' ? 'AI' : '人工'}</span><button class="cell-restore-source" data-restore-table-cell title="恢复 API 原值" aria-label="恢复 API 原值">&#8634;</button>` : ''}</td>`;
              }).join('')}</tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>
      <div class="table-pagination"><button class="secondary" data-table-workspace-page="prev" ${currentPage <= 1 ? 'disabled' : ''}>上一页</button><span class="muted">${start + 1}-${Math.min(rows.length, start + visibleRows.length)} / ${rows.length}</span><button class="secondary" data-table-workspace-page="next" ${currentPage >= totalPages ? 'disabled' : ''}>下一页</button></div>
      ${renderSelectedCellActionBar(nodeId, payload)}
    </div>
  `;
}

function renderValueStatusTable(result) {
  const sources = Array.isArray(result?.field_sources) ? result.field_sources : [];
  if (sources.length === 0) return '<p class="muted">暂无逐字段取值状态。运行当前节点后会展示字段是否真实取到值。</p>';
  const valueStatusClass = (item) => {
    if (item.value_status === 'present') return 'done';
    if (['empty', 'not_called', 'pi_derived_unconfirmed'].includes(item.value_status) || item.source_kind === 'pi_derived') return 'waiting';
    return 'failed';
  };
  return `
    <div class="artifact-table-wrap">
      <table class="artifact-table">
        <thead>
          <tr>
            <th>字段</th>
            <th>映射状态</th>
            <th>来源字段</th>
            <th>取值状态</th>
            <th>证据</th>
          </tr>
        </thead>
        <tbody>
          ${sources.map(item => `
            <tr class="${['missing', 'partial', 'source_path_missing', 'not_called', 'join_blocked'].includes(item.value_status) && item.required ? 'missing' : ''}">
              <td>${escapeHtml(item.field_name || item.field_path || '')}${item.required ? '<br><span class="muted">必填</span>' : ''}</td>
              <td>${escapeHtml(item.mapping_status || '')}<br><span class="muted">${escapeHtml(item.source_kind || '')}${item.derivation_method ? ` · ${escapeHtml(item.derivation_method)}` : ''}</span></td>
              <td>${escapeHtml(item.source_api_name || item.source_api_id || '')}<br><span class="muted">${escapeHtml(item.source_field_path || '无 source_field_path')}</span>${item.runtime_repair ? '<br><span class="muted">已运行时改用有值字段</span>' : ''}</td>
              <td><span class="badge ${valueStatusClass(item)}">${escapeHtml(item.value_status || '')}</span><br><span class="muted">有值 ${escapeHtml(item.rows_with_value ?? 0)} · 缺值 ${escapeHtml(item.rows_missing_value ?? 0)}</span></td>
              <td>${escapeHtml(item.evidence_ref || '-')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
}

function dataAnalysisStatusBadgeClass(status) {
  if (status === 'data_table_ready') return 'done';
  if (status === 'partial_data_table_ready' || status === 'agent_enrichment_pending') return 'running';
  if (status === 'empty_data') return 'waiting';
  if (status === 'blocked' || status === 'degraded') return 'failed';
  return 'waiting';
}

function renderMergeEvidence(result) {
  const strategy = String(result?.merge_strategy || '');
  if (!strategy) return '';
  const primary = String(result.primary_api_id || '');
  const joined = Array.isArray(result.key_joined_api_ids) ? result.key_joined_api_ids : [];
  const blocked = Array.isArray(result.join_blocked_api_ids) ? result.join_blocked_api_ids : [];
  const joinKeys = Array.isArray(result.join_keys) ? result.join_keys : [];
  const joinLabel = joinKeys.includes('keyword') ? '规范化关键词' : '商品 ID';
  const description = strategy === 'key_join'
    ? `以 ${primary || '主 API'} 为主表，按${joinLabel}合并 ${joined.join('、') || '补充 API'}`
    : strategy === 'single_api'
      ? `仅 ${primary || '一个经范围校验的 API'} 贡献商品行${blocked.length ? `；${blocked.join('、')} 未通过商品 ID 合并` : ''}`
      : strategy === 'blocked'
        ? '缺少可验证的共同商品 ID，合并已阻断'
        : `当前策略：${strategy}`;
  return `<p><strong>${escapeHtml(joinLabel)}合并</strong> · <span class="badge waiting">${escapeHtml(strategy)}</span> <span class="muted">${escapeHtml(description)}</span></p>`;
}

function renderDataAnalysisExecutionResult(result) {
  if (!result || result.schema_version !== 'data-analysis-execution-v1') return '';
  const risks = Array.isArray(result.risks) ? result.risks : [];
  return `
    <div class="analysis-run-evidence">
      <p>
        <span class="badge ${dataAnalysisStatusBadgeClass(result.status)}">${escapeHtml(result.status || '')}</span>
        <span class="muted">data：${escapeHtml(result.data_table_ref || '未生成')} · insight：${escapeHtml(result.insight_draft_ref || '未生成')} · trace：${escapeHtml(result.execution_trace_ref || '未生成')}</span>
      </p>
      ${renderCategoryResolutionSummary(result)}
      ${renderKeywordCategoryAttempts(result)}
      ${renderProductDetailEnrichmentSummary(result)}
      ${renderMergeEvidence(result)}
      <h4>API 调用计划</h4>
      ${renderApiExecutionPlan(result)}
      <h4>字段取值状态</h4>
      ${renderValueStatusTable(result)}
      ${risks.length ? `<p class="error-text">风险：${listText(risks, '无')}</p>` : '<p class="muted">暂无取值风险。</p>'}
    </div>
  `;
}

function renderDataAnalysisTableSection(node) {
  const fields = currentFieldMappingOverlay(node);
  const summary = coverageSummaryForFields(fields);
  const runResult = state.latestResult[node.id];
  const workspacePayload = state.dataTableWorkspaces[node.id];
  const rows = workspacePayload?.effective_rows || [];
  const selectedTopN = selectedDataAnalysisTopN(node.id);
  return `
    <div class="analysis-section analysis-data-table-section">
      <div class="analysis-table-heading">
        <div>
          <h3>TOP N 可编辑数据表</h3>
          <p class="muted">字段 ${summary.total} · 已覆盖 ${summary.mapped} · 必填未覆盖 ${summary.missingRequired}</p>
        </div>
        <div class="analysis-run-toolbar">
          <span class="badge ${dataAnalysisStatusBadgeClass(runResult?.status)}">${escapeHtml(runResult?.status || statusFor(node.id))}</span>
          <span class="badge">${escapeHtml(rows.length)} 行</span>
          <label class="top-n-control">TOP N
            <select data-analysis-top-n>
              <option value="10" ${selectedTopN === 10 ? 'selected' : ''}>10</option>
              <option value="20" ${selectedTopN === 20 ? 'selected' : ''}>20</option>
              <option value="30" ${selectedTopN === 30 ? 'selected' : ''}>30</option>
              <option value="50" ${selectedTopN === 50 ? 'selected' : ''}>50</option>
            </select>
          </label>
          <button id="run-node">运行当前节点</button>
        </div>
      </div>
      ${workspacePayload?.workspace
        ? renderEditableDataTableWorkspace(node.id, workspacePayload)
        : '<p class="muted">运行当前节点取得真实数据后，将在这里建立唯一的可编辑数据表。</p>'}
    </div>
  `;
}

function renderDataAnalysisNodeWorkspace(node) {
  const view = analysisNodeViewFor(node);
  return `
    <div class="analysis-workspace">
      ${renderAnalysisPurpose(view)}
      ${renderAnalysisInputReadiness(view)}
      ${renderAnalysisFieldCoverage(node, view)}
      ${renderAnalysisExecutionPlan(view)}
      ${renderDataAnalysisTableSection(node)}
    </div>
  `;
}

const HOT_PRODUCT_GENE_DIMENSIONS = ['产品类型', '材质', '功能', '风格', '人群', '场景', '价格带', '视觉表达', '流量入口'];
const GENE_SIGNAL_STATUSES = ['matched', 'not_matched', 'unavailable', 'insufficient_sample'];

function geneAnalysisFor(nodeId) {
  return state.geneAnalyses[nodeId] || { analysis: null, confirmed_artifact: null };
}

function geneStatusText(status) {
  return {
    running: '执行中', preparing: '准备中', draft_ready: '待人工确认', confirmed: '已确认',
    stale: '上游数据已变化', cancelled: '已取消', insufficient_sample: '样本不足',
    matched: '已命中', not_matched: '未命中', unavailable: '证据不可用',
  }[String(status || '')] || String(status || '未开始');
}

function geneElapsedSeconds(analysis) {
  if (!analysis?.created_at) return 0;
  const end = analysis.finished_at ? new Date(analysis.finished_at).getTime() : Date.now();
  return Math.max(0, Math.round((end - new Date(analysis.created_at).getTime()) / 1000));
}

function renderGeneExecutionMonitor(analysis) {
  const progress = analysis?.progress || {};
  return `
    <section class="gene-monitor" data-gene-monitor>
      <div class="gene-monitor-heading">
        <div>
          <h3>爆款基因执行监视器</h3>
          <p class="muted">模型：${escapeHtml(analysis?.requested_model || 'aicodemirror/gpt-5.6-sol')}</p>
        </div>
        <span class="badge ${escapeHtml(analysis?.status || 'idle')}" data-gene-monitor-status>${escapeHtml(geneStatusText(analysis?.status))}</span>
      </div>
      <div class="gene-monitor-grid">
        <span>商品 <strong data-gene-total>${escapeHtml(progress.total_products || analysis?.sample_size || 0)}</strong></span>
        <span>完成 <strong data-gene-completed>${escapeHtml(progress.completed_products || 0)}</strong></span>
        <span>运行 <strong data-gene-running>${escapeHtml(progress.running_products || 0)}</strong></span>
        <span>失败 <strong data-gene-failed>${escapeHtml(progress.failed_products || 0)}</strong></span>
        <span>耗时 <strong data-gene-elapsed>${escapeHtml(geneElapsedSeconds(analysis))}s</strong></span>
      </div>
      ${analysis?.classification_status === 'insufficient_sample'
        ? '<p class="gene-warning">当前 N 小于50：九维画像和候选组合可用，强度分级保持 insufficient_sample，不生成强结论。</p>' : ''}
    </section>
  `;
}

function renderGeneDimensionCell(dimension) {
  const item = dimension || {};
  const value = (item.normalized_tags || []).join('、') || item.raw_value || '';
  return `
    <div class="gene-dimension-value">
      <span>${escapeHtml(value || '待补充')}</span>
      <small class="gene-source-status ${escapeHtml(item.source_status || 'missing')}">${escapeHtml(item.source_status || 'missing')}</small>
    </div>
  `;
}

function renderProductGeneProfiles(nodeId, analysis) {
  const profiles = Array.isArray(analysis?.product_profiles) ? analysis.product_profiles : [];
  if (profiles.length === 0) return '<p class="muted">运行后显示逐商品九维画像。</p>';
  const pageSize = 10;
  const pageCount = Math.max(1, Math.ceil(profiles.length / pageSize));
  const page = Math.min(pageCount, Math.max(1, Number(state.dataTablePages[nodeId] || 1)));
  const rows = profiles.slice((page - 1) * pageSize, page * pageSize);
  const groups = new Map((analysis.gene_groups || []).map(group => [group.group_id, group]));
  return `
    <div class="gene-profile-table-wrap">
      <table class="data-table gene-profile-table">
        <thead><tr><th>商品</th>${HOT_PRODUCT_GENE_DIMENSIONS.map(name => `<th>${escapeHtml(name)}</th>`).join('')}<th>组合分级</th></tr></thead>
        <tbody>${rows.map(profile => {
          const labels = (profile.gene_group_ids || []).flatMap(id => (groups.get(id)?.classifications || []))
            .filter(item => item.matched).map(item => item.label);
          return `<tr>
            <td><strong>${escapeHtml(profile.product_name || profile.goods_id || profile.row_id)}</strong><small>排名 ${escapeHtml(profile.rank || '')}</small></td>
            ${HOT_PRODUCT_GENE_DIMENSIONS.map(name => `<td>${renderGeneDimensionCell(profile.dimensions?.[name])}</td>`).join('')}
            <td>${labels.length ? labels.map(label => `<span class="badge completed">${escapeHtml(label)}</span>`).join('') : `<span class="badge waiting">${escapeHtml(analysis.classification_status === 'insufficient_sample' ? '样本不足' : '未命中')}</span>`}</td>
          </tr>`;
        }).join('')}</tbody>
      </table>
    </div>
    <div class="table-pagination">
      <button data-gene-page="prev" ${page <= 1 ? 'disabled' : ''}>上一页</button>
      <span>第 ${page}/${pageCount} 页 · ${profiles.length} 个商品</span>
      <button data-gene-page="next" ${page >= pageCount ? 'disabled' : ''}>下一页</button>
    </div>
  `;
}

function renderGeneDimensionFindings(analysis) {
  const findings = Array.isArray(analysis?.dimension_findings) ? analysis.dimension_findings : [];
  if (findings.length === 0) return '';
  return `
    <section class="analysis-section">
      <h3>九维频次与覆盖率</h3>
      <div class="gene-finding-grid">${findings.map(item => `
        <div class="gene-finding-row">
          <strong>${escapeHtml(item.dimension)}</strong>
          <span>${escapeHtml(item.covered_products)}/${escapeHtml(item.total_products)}</span>
          <span>${escapeHtml((item.top_tags || []).slice(0, 5).map(tag => `${tag.tag} ${Math.round(tag.ratio * 100)}%`).join(' · ') || '无有效标签')}</span>
        </div>
      `).join('')}</div>
    </section>
  `;
}

function renderGeneSignal(signalName, signal) {
  const item = signal || { status: 'unavailable' };
  const value = item.value === null || item.value === undefined ? '-' : typeof item.value === 'number' ? `${Math.round(item.value * 1000) / 10}%` : item.value;
  return `<li><span>${escapeHtml(signalName)}</span><span>${escapeHtml(value)}</span><span class="gene-signal ${escapeHtml(item.status || 'unavailable')}">${escapeHtml(geneStatusText(item.status || 'unavailable'))}</span></li>`;
}

function renderGeneGroups(analysis) {
  const groups = Array.isArray(analysis?.gene_groups) ? analysis.gene_groups : [];
  if (groups.length === 0) return '<p class="muted">当前没有满足产品锚点、需求锚点和三维组合要求的候选。</p>';
  return `
    <div class="gene-group-list">${groups.map(group => `
      <article class="gene-group-row">
        <div class="gene-group-summary">
          <strong>${escapeHtml(group.gene_formula || group.normalized_gene_key)}</strong>
          <span>${escapeHtml(group.product_count)} 个商品 · 样本占比 ${escapeHtml(Math.round(Number(group.metrics?.sample_ratio || 0) * 1000) / 10)}% · ${escapeHtml(group.maturity)}</span>
        </div>
        <div class="gene-labels">${(group.classifications || []).map(item => `
          <span class="badge ${escapeHtml(item.status)}">${escapeHtml(item.label)} · ${escapeHtml(item.matched_count || 0)}/2 · ${escapeHtml(geneStatusText(item.status))}</span>
        `).join('')}</div>
        <details><summary>判断证据</summary>
          ${(group.classifications || []).map(item => `<div class="gene-rule-detail"><strong>${escapeHtml(item.label)}</strong><ul>${Object.entries(item.signals || {}).map(([name, signal]) => renderGeneSignal(name, signal)).join('')}</ul></div>`).join('')}
        </details>
      </article>
    `).join('')}</div>
  `;
}

function geneRunErrorMessage(error) {
  const code = String(error || '').trim();
  const messages = {
    source_table_not_confirmed: '请先在流程2确认 TOP N 商品表，再运行爆款基因提炼。',
    source_table_empty: '流程2已确认的数据表没有商品行，请重新取数并确认后再运行。',
    gene_analysis_source_revision_conflict: '流程2数据已变化，请重新运行爆款基因提炼。',
  };
  return messages[code] || code;
}

function renderHotProductGeneWorkspace(node) {
  const payload = geneAnalysisFor(node.id);
  const analysis = payload.analysis;
  const confirmed = payload.confirmed_artifact;
  const runError = state.latestResult[node.id]?.error;
  const running = ['running', 'preparing'].includes(String(analysis?.status || ''));
  const canConfirm = analysis?.status === 'draft_ready' && !confirmed;
  return `
    <div class="analysis-workspace hot-product-gene-workspace" data-dimension-status-field="source_status" data-classification-count-field="matched_count">
      <section class="analysis-section">
        <div class="analysis-table-heading">
          <div><h3>${escapeHtml(node.name || '爆款基因提炼')}</h3><p class="muted">数据源：流程2人工确认后的 TOP N 商品表 · 九维画像 → 组合聚合 → 证据分级</p></div>
          <div class="analysis-run-toolbar">
            <button id="run-node" ${running ? 'disabled' : ''}>${analysis ? '重新运行' : '运行当前节点'}</button>
            ${running ? `<button data-gene-cancel="${escapeHtml(analysis.execution_id)}">停止</button>` : ''}
            ${analysis?.progress?.failed_products ? `<button data-gene-retry="${escapeHtml(analysis.execution_id)}">重试失败商品</button>` : ''}
            ${canConfirm ? `<button class="primary" data-gene-confirm="${escapeHtml(analysis.execution_id)}">确认爆款基因并进入下一步</button>` : ''}
          </div>
        </div>
        ${confirmed ? `<p class="save-status ${confirmed.status === 'stale' ? 'failed' : 'done'}">${escapeHtml(confirmed.status === 'stale' ? '已确认结果因流程2变化而过期，请重新运行。' : '爆款基因已人工确认。')}</p>` : ''}
        ${runError ? `<p class="save-status failed">${escapeHtml(geneRunErrorMessage(runError))}<br><span class="muted">${escapeHtml(runError)}</span></p>` : ''}
      </section>
      ${renderGeneExecutionMonitor(analysis)}
      <section class="analysis-section"><h3>逐商品九维画像</h3>${renderProductGeneProfiles(node.id, analysis)}</section>
      ${renderGeneDimensionFindings(analysis)}
      <section class="analysis-section"><h3>聚合爆款基因组合</h3>${renderGeneGroups(analysis)}</section>
      ${analysis?.risks?.length ? `<details class="analysis-section"><summary>风险与不可用证据</summary><ul>${analysis.risks.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul></details>` : ''}
      <p class="sr-only">状态枚举：${GENE_SIGNAL_STATUSES.join(' ')}</p>
    </div>
  `;
}

function patchHotProductGeneMonitor(nodeId) {
  if (state.selectedNodeId !== nodeId) return;
  const analysis = geneAnalysisFor(nodeId).analysis;
  const monitor = document.querySelector('[data-gene-monitor]');
  if (!analysis || !monitor) return;
  const values = {
    '[data-gene-total]': analysis.progress?.total_products || analysis.sample_size || 0,
    '[data-gene-completed]': analysis.progress?.completed_products || 0,
    '[data-gene-running]': analysis.progress?.running_products || 0,
    '[data-gene-failed]': analysis.progress?.failed_products || 0,
    '[data-gene-elapsed]': `${geneElapsedSeconds(analysis)}s`,
    '[data-gene-monitor-status]': geneStatusText(analysis.status),
  };
  Object.entries(values).forEach(([selector, value]) => {
    const target = monitor.querySelector(selector);
    if (target) target.textContent = String(value);
  });
}

function renderBusinessContext(node) {
  const context = node.business_context || {};
  const results = Array.isArray(context.results) ? context.results : [];
  const warnings = Array.isArray(context.warnings) ? context.warnings : [];
  const status = context.status || 'missing';
  const header = `
    <p class="muted">status：${escapeHtml(status)} · mode：${escapeHtml(context.mode || 'local-skills.strategy_kb_search')}</p>
    <p class="muted">query：${escapeHtml(context.query || '未声明')}</p>
    <p class="muted">kb：${escapeHtml(context.kb_manifest || '未配置')}</p>
    ${context.error ? `<p class="error-text">${escapeHtml(context.error)}</p>` : ''}
    ${warnings.length > 0 ? `<p class="muted">warnings：${listText(warnings, '无')}</p>` : ''}
  `;
  if (results.length === 0) {
    return `${header}<p class="muted">未命中业务上下文。</p>`;
  }
  return `
    ${header}
    ${results.map(result => `
      <article class="model-card">
        <h4>${escapeHtml(result.doc_title || result.doc_id || 'Strategy KB passage')}</h4>
        <p class="muted">rank：${escapeHtml(result.rank || '')} · score：${escapeHtml(result.score || '')} · citation：${escapeHtml(result.citation_id || '无')}</p>
        <p class="muted">section：${escapeHtml(result.section || '未声明')}</p>
        <p>${escapeHtml(result.passage || '暂无片段。')}</p>
        <details>
          <summary>来源</summary>
          <p class="muted">doc_id：${escapeHtml(result.doc_id || '')}</p>
          <p class="muted">page：${escapeHtml(result.kb_page_id || '')}</p>
          <p class="muted">path：${escapeHtml(result.source_path || '')}</p>
          <p class="muted">matched：${listText(result.matched_terms || [], '无')}</p>
        </details>
      </article>
    `).join('')}
  `;
}

function renderSourceTrace(node) {
  const trace = node.source_trace || {};
  return `
    <p class="muted">workflow：${escapeHtml(trace.workflow_ref || '未声明')}</p>
    <p class="muted">data requirements：${listText(trace.data_requirement_refs || [], '无')}</p>
    <p class="muted">output schemas：${listText(trace.output_schema_refs || [], '无')}</p>
    <p class="muted">tool bindings：${listText(trace.tool_binding_refs || [], '无')}</p>
    <p class="muted">evidence：${escapeHtml(trace.evidence_ref || '未声明')}</p>
    <p class="muted">strategy kb：${escapeHtml(trace.strategy_kb_ref || '未配置')}</p>
    <p class="muted">strategy query：${escapeHtml(trace.strategy_kb_query || '无')}</p>
    <p class="muted">strategy citations：${listText(trace.strategy_kb_citation_refs || [], '无')}</p>
  `;
}

function renderNodeList() {
  const nodes = state.config?.nodes || [];
  return `
    <div class="node-list">
      ${nodes.map((node, index) => `
        <button class="node-item ${node.id === state.selectedNodeId ? 'active' : ''}" data-node-id="${escapeHtml(node.id)}">
          <span class="node-index">${String(index + 1).padStart(2, '0')}</span>
          <span class="node-info">
            <span class="node-name">${escapeHtml(node.name || node.id)}</span>
            <span class="node-kind">${escapeHtml(node.kind || 'node')}</span>
          </span>
          <span class="badge ${escapeHtml(statusFor(node.id))}">${escapeHtml(statusFor(node.id))}</span>
        </button>
      `).join('')}
    </div>
  `;
}

function renderNodeDetail() {
  const node = currentNode();
  if (!node) {
    return '<p class="muted">暂无节点。</p>';
  }
  const result = state.latestResult[node.id];
  const outputDisplay = result ? formatOutput(result) : '<p class="muted">节点运行后会在这里显示结构化结果。</p>';
  const flowNotice = state.flowNotice[node.id];
  if (isHotProductGeneNode(node)) {
    return `
      ${flowNotice ? `<p class="save-status ${escapeHtml(flowNotice.status || 'done')}">${escapeHtml(flowNotice.message || '')}</p>` : ''}
      ${renderHotProductGeneWorkspace(node)}
      <details class="detail-section engineering-details">
        <summary>工程证据与来源追踪</summary>
        ${renderEvidenceModel(node)}
        ${renderBusinessContext(node)}
        ${renderSourceTrace(node)}
      </details>
    `;
  }
  if (isDataAnalysisNode(node)) {
    return `
      <div class="detail-section">
        <h3>${escapeHtml(node.name || node.id)}</h3>
        <p class="muted">类型：<span class="kind-badge ${escapeHtml(node.kind)}">${escapeHtml(node.kind || 'node')}</span> · 依赖：${escapeHtml((node.depends_on || []).join(', ') || '无')}</p>
        ${flowNotice ? `<p class="save-status ${escapeHtml(flowNotice.status || 'done')}">${escapeHtml(flowNotice.message || '')}</p>` : ''}
      </div>
      ${renderDataAnalysisNodeWorkspace(node)}
      <details class="detail-section engineering-details">
        <summary>工程证据与来源追踪</summary>
        ${renderDataAnalysisExecutionResult(result)}
        ${renderEvidenceModel(node)}
        ${renderToolModel(node)}
        ${renderBusinessContext(node)}
        ${renderSourceTrace(node)}
        <p class="muted">${escapeHtml(result?.evidence_ref || '暂无 evidence。')}</p>
      </details>
    `;
  }

  return `
    <div class="detail-section">
      <h3>${escapeHtml(node.name || node.id)}</h3>
      <p class="muted">类型：<span class="kind-badge ${escapeHtml(node.kind)}">${escapeHtml(node.kind || 'node')}</span> · 依赖：${escapeHtml((node.depends_on || []).join(', ') || '无')}</p>
      ${flowNotice ? `<p class="save-status ${escapeHtml(flowNotice.status || 'done')}">${escapeHtml(flowNotice.message || '')}</p>` : ''}
    </div>
    ${renderExecutionView(node)}
    <div class="detail-section">
      <h3>输入</h3>
      ${renderInputModel(node)}
    </div>
    <div class="detail-section">
      <h3>依赖数据</h3>
      ${renderRequiredData(node)}
    </div>
    <div class="detail-section">
      <h3>产物</h3>
      ${renderOutputModel(node)}
    </div>
    ${renderOutputFieldMappingWorkbench(node)}
    <div class="detail-section">
      <h3>Evidence</h3>
      ${renderEvidenceModel(node)}
    </div>
    <div class="detail-section">
      <h3>Tool</h3>
      ${renderToolModel(node)}
    </div>
    <div class="detail-section">
      <h3>业务上下文</h3>
      ${renderBusinessContext(node)}
    </div>
    <div class="detail-section">
      <h3>Source Trace</h3>
      ${renderSourceTrace(node)}
    </div>
    <div class="detail-section">
      <h3>执行</h3>
      <button id="run-node">运行当前节点</button>
      <span class="badge ${escapeHtml(statusFor(node.id))}">${escapeHtml(statusFor(node.id))}</span>
    </div>
    <div class="detail-section">
      <h3>输出</h3>
      <div class="output">${outputDisplay}</div>
    </div>
    <div class="detail-section">
      <h3>工程证据</h3>
      <p class="muted">${escapeHtml(result?.evidence_ref || '暂无 evidence。')}</p>
    </div>
  `;
}

function formatOutput(result) {
  if (!result) return '<p class="muted">无输出</p>';

  // If result has error, show error message
  if (result.error) {
    return `<pre class="error-output">${escapeHtml(result.error)}</pre>`;
  }

  // Check if result contains markdown (report_markdown field)
  if (result.report_markdown || (result.result && result.result.report_markdown)) {
    const markdown = result.report_markdown || result.result.report_markdown;
    return `<div class="markdown-output">${renderMarkdown(markdown)}</div>`;
  }

  // Check if result.result is a string that looks like markdown
  if (result.result && typeof result.result === 'string' && isMarkdownLike(result.result)) {
    return `<div class="markdown-output">${renderMarkdown(result.result)}</div>`;
  }

  // If result has specific display field, use it
  if (result.result && typeof result.result === 'object') {
    return formatStructuredOutput(result.result);
  }

  // Default: show entire result as JSON
  return `<pre class="json-output">${escapeHtml(JSON.stringify(result, null, 2))}</pre>`;
}

function isMarkdownLike(text) {
  const str = String(text);
  // Check for common markdown patterns
  return /^#{1,6}\s/.test(str) || /\n#{1,6}\s/.test(str) || /\|\s*---\s*\|/.test(str);
}

function renderInlineMarkdown(text) {
  let html = escapeHtml(text);
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
  return html;
}

function parseMarkdownTableRow(line) {
  const trimmed = String(line || '').trim();
  if (!trimmed.startsWith('|') || !trimmed.endsWith('|')) return null;
  return trimmed.slice(1, -1).split('|').map(cell => cell.trim());
}

function isMarkdownTableDivider(line) {
  const cells = parseMarkdownTableRow(line);
  return Array.isArray(cells) && cells.length > 0 && cells.every(cell => /^:?-{3,}:?$/.test(cell));
}

function renderMarkdownTable(headers, rows) {
  return `
    <table>
      <thead>
        <tr>${headers.map(cell => `<th>${renderInlineMarkdown(cell)}</th>`).join('')}</tr>
      </thead>
      <tbody>
        ${rows.map(row => `<tr>${row.map(cell => `<td>${renderInlineMarkdown(cell)}</td>`).join('')}</tr>`).join('')}
      </tbody>
    </table>
  `;
}

function renderMarkdown(markdown) {
  const lines = String(markdown || '').replace(/\r\n/g, '\n').split('\n');
  const blocks = [];
  let paragraph = [];
  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    blocks.push(`<p>${paragraph.map(renderInlineMarkdown).join('<br>')}</p>`);
    paragraph = [];
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const trimmed = line.trim();
    if (!trimmed) {
      flushParagraph();
      continue;
    }

    const heading = /^(#{1,3})\s+(.+)$/.exec(trimmed);
    if (heading) {
      flushParagraph();
      const level = heading[1].length;
      blocks.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }

    const tableHeader = parseMarkdownTableRow(trimmed);
    if (tableHeader && isMarkdownTableDivider(lines[index + 1])) {
      flushParagraph();
      index += 2;
      const rows = [];
      while (index < lines.length) {
        const row = parseMarkdownTableRow(lines[index]);
        if (!row) break;
        rows.push(row);
        index += 1;
      }
      index -= 1;
      blocks.push(renderMarkdownTable(tableHeader, rows));
      continue;
    }

    paragraph.push(trimmed);
  }

  flushParagraph();
  return blocks.join('');
}

function formatStructuredOutput(data) {
  if (data.schema_version === 'data-analysis-execution-v1') {
    return renderDataAnalysisExecutionResult(data);
  }
  // Check if it's a rule evaluation result
  if (data.rule_id && data.output_label !== undefined) {
    return `
      <div class="rule-result">
        <div class="result-header">
          <span class="badge ${data.matched ? 'done' : 'idle'}">${data.matched ? '匹配' : '不匹配'}</span>
          <span class="result-label">${escapeHtml(data.output_label || '')}</span>
        </div>
        ${data.score !== undefined ? `<p><strong>分数：</strong>${escapeHtml(data.score)}</p>` : ''}
        ${data.evidence ? `<details><summary>证据</summary><pre class="json-output">${escapeHtml(JSON.stringify(data.evidence, null, 2))}</pre></details>` : ''}
      </div>
    `;
  }

  // Default: JSON output
  return `<pre class="json-output">${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
}

function dbAgentResultFor(node) {
  return node ? state.dbAgentResults[node.id] : null;
}

function renderDbAgentStatus() {
  const status = state.dbAgentStatus;
  if (!status) return '<p class="muted">状态待检测。</p>';
  const badge = status.status === 'ok' ? 'done' : 'waiting';
  return `
    <p class="muted">连接：<span class="badge ${badge}">${escapeHtml(status.status || 'unknown')}</span> · live：${status.live_probe_enabled ? 'on' : 'off'}</p>
    ${status.reason && status.reason !== 'ready' ? `<p class="muted">原因：${escapeHtml(status.reason)}</p>` : ''}
  `;
}

function selectedPiModel() {
  const node = currentNode();
  return agentThreadFor(node?.id).preferred_model
    || state.piSelectedModel
    || state.piAgentStatus?.selected_model
    || 'aicodemirror/gpt-5.6-sol';
}

function renderPiAgentStatus() {
  const status = state.piAgentStatus;
  if (!status) return '<p class="muted">PI runtime 状态待检测。</p>';
  const badge = status.status === 'ready' ? 'done' : 'waiting';
  const selectedModel = selectedPiModel();
  const options = Array.isArray(status.model_options) && status.model_options.length > 0
    ? status.model_options
    : [
      { provider: 'aicodemirror', label: 'AICodeMirror GPT-5.6 Sol', model: 'aicodemirror/gpt-5.6-sol', configured: false },
      { provider: 'deepseek', label: 'DeepSeek V4 Pro', model: 'deepseek/deepseek-v4-pro', configured: false },
    ];
  const optionTags = options.map(option => {
    const model = String(option.model || '');
    const label = String(option.label || model || 'model');
    const configured = option.configured ? '已配置' : '未配置';
    return `<option value="${escapeHtml(model)}" ${model === selectedModel ? 'selected' : ''}>${escapeHtml(label)} · ${escapeHtml(model)} · ${configured}</option>`;
  }).join('');
  const current = options.find(option => option.model === selectedModel) || {};
  const modelBadge = current.configured ? 'done' : 'waiting';
  const node = currentNode();
  const calls = agentThreadFor(node?.id).agent_calls || [];
  const latestCall = calls[calls.length - 1] || {};
  const actualModel = latestCall.actual_model || '未知';
  const resolutionBadge = latestCall.model_resolution_status === 'substituted' ? 'failed' : latestCall.model_resolution_status === 'matched' ? 'done' : 'waiting';
  return `
    <p class="muted">PI runtime：<span class="badge ${badge}">${escapeHtml(status.status || 'unknown')}</span> · scope：right_agent_only</p>
    <label class="field-label" for="pi-model-select">首选模型</label>
    <select id="pi-model-select" data-pi-model-select>
      ${optionTags}
    </select>
    <div class="agent-model-audit">
      <span>首选模型：<strong class="badge ${modelBadge}">${escapeHtml(selectedModel)}</strong></span>
      <span>请求模型：<strong>${escapeHtml(latestCall.requested_model || '尚未调用')}</strong></span>
      <span>实际模型：<strong class="badge ${resolutionBadge}">${escapeHtml(actualModel)}</strong></span>
      ${latestCall.model_comparison_reason ? `<span>比较：<strong>${escapeHtml(latestCall.model_comparison_reason)}</strong></span>` : ''}
    </div>
    ${latestCall.model_resolution_status === 'substituted' ? `<p class="call-warning">模型发生替换：请求 ${escapeHtml(latestCall.requested_model || '')}，实际 ${escapeHtml(actualModel)}。</p>` : ''}
    ${status.reason && status.reason !== 'ready' ? `<p class="muted">原因：${escapeHtml(status.reason)}</p>` : ''}
  `;
}

function renderDbAgentTools(payload) {
  const tools = Array.isArray(payload?.recommended_tools) ? payload.recommended_tools : [];
  if (tools.length === 0) return '<p class="muted">暂无推荐工具。</p>';
  return tools.map(tool => `
    <article class="model-card db-agent-tool">
      <h4>${escapeHtml(tool.tool_id || 'tool')}</h4>
      <p class="muted">order：${escapeHtml(tool.call_order || '')} · quality：${escapeHtml(tool.quality_score ?? '')}</p>
      <p>${escapeHtml(tool.reason || '')}</p>
      <p class="muted">source APIs：${listText(tool.source_apis || [], '无')}</p>
      <p class="muted">missing params：${listText(tool.missing_params || [], '无')}</p>
      <p class="muted">risk：${listText(tool.risks || [], '无')}</p>
    </article>
  `).join('');
}

function contractFromDbAgentResult(result) {
  if (!result || typeof result !== 'object') return null;
  if (result.data_mapping_contract && typeof result.data_mapping_contract === 'object') {
    return result.data_mapping_contract;
  }
  return null;
}

function firstSourceApiFromDbAgentResult(result) {
  const contractApi = String(result?.data_mapping_contract?.selected_api?.api_id || '').trim();
  if (contractApi) return contractApi;
  const selectedApi = String(result?.payload?.selected_api?.api_id || '').trim();
  if (selectedApi) return selectedApi;
  const contractCandidates = Array.isArray(result?.data_mapping_contract?.candidate_apis) ? result.data_mapping_contract.candidate_apis : [];
  for (const api of contractCandidates) {
    const apiId = String(api?.api_id || '').trim();
    if (apiId) return apiId;
  }
  const tools = Array.isArray(result?.payload?.recommended_tools) ? result.payload.recommended_tools : [];
  for (const tool of tools) {
    const sourceApis = Array.isArray(tool?.source_apis) ? tool.source_apis : [];
    const sourceApi = sourceApis.find(value => String(value || '').trim());
    if (sourceApi) return String(sourceApi).trim();
  }
  return '';
}

function agentThreadFor(nodeId) {
  return state.agentThreads[nodeId]?.thread || { schema_version: 'analysis-collaboration-thread-v1', messages: [] };
}

function renderAgentContextRefs(refs) {
  const items = Array.isArray(refs) ? refs : [];
  if (!items.length) return '';
  return items.map(ref => `
    <div class="agent-context-card">
      <strong>${escapeHtml(ref.product_name || ref.product_id || ref.row_id || '当前商品')}</strong>
      <span>${escapeHtml(ref.field_path || '')}</span>
      <span class="muted">当前值：${escapeHtml(ref.effective_value || '空')} · 来源：${escapeHtml(ref.source_kind || 'unknown')}</span>
      ${Object.keys(ref.evidence_values || {}).length ? `<dl class="agent-context-evidence">${Object.entries(ref.evidence_values || {}).map(([key, value]) => `<div><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd></div>`).join('')}</dl>` : ''}
    </div>
  `).join('');
}

function renderAgentContextSnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== 'object') return '<p class="muted">本次没有附加单元格上下文。</p>';
  const evidence = Object.entries(snapshot.evidence_values || {});
  return `
    <dl class="agent-call-context-grid">
      ${snapshot.product_name || snapshot.product_id ? `<div><dt>商品</dt><dd>${escapeHtml(snapshot.product_name || snapshot.product_id)}</dd></div>` : ''}
      ${snapshot.product_id ? `<div><dt>商品 ID</dt><dd>${escapeHtml(snapshot.product_id)}</dd></div>` : ''}
      ${snapshot.target_field ? `<div><dt>目标字段</dt><dd>${escapeHtml(snapshot.target_field)}</dd></div>` : ''}
      <div><dt>当前值</dt><dd>${escapeHtml(snapshot.current_value || '空')}</dd></div>
      <div><dt>API 原值</dt><dd>${escapeHtml(snapshot.api_original_value || '空')}</dd></div>
      ${evidence.map(([key, value]) => `<div><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd></div>`).join('')}
      <div><dt>表格 revision</dt><dd>${escapeHtml(snapshot.table_revision ?? '')}</dd></div>
      <div><dt>请求模型</dt><dd>${escapeHtml(snapshot.requested_model || '')}</dd></div>
    </dl>
  `;
}

function latestAgentCall(nodeId) {
  const calls = agentThreadFor(nodeId).agent_calls || [];
  return calls[calls.length - 1] || null;
}

function latestAgentBatch(nodeId) {
  const summaries = agentThreadFor(nodeId).agent_batches || [];
  const current = state.agentBatches[nodeId]?.batch;
  return current || summaries[summaries.length - 1] || null;
}

function agentBatchIsRunning(batch) {
  return Boolean(batch && ['preparing', 'running'].includes(String(batch.status || '')));
}

function updateAgentBatchInState(nodeId, batch) {
  if (!batch) return;
  state.agentBatches[nodeId] = { ok: true, batch };
  const payload = state.agentThreads[nodeId] || { ok: true, thread: agentThreadFor(nodeId) };
  const thread = payload.thread || {};
  const summaries = Array.isArray(thread.agent_batches) ? [...thread.agent_batches] : [];
  const index = summaries.findIndex(item => item.batch_id === batch.batch_id);
  const summary = {
    batch_id: batch.batch_id,
    schema_version: batch.schema_version,
    status: batch.status,
    subject_kind: batch.subject_kind || 'product',
    requested_model: batch.requested_model,
    base_revision: batch.base_revision,
    page: batch.page,
    progress: batch.progress,
    started_at: batch.started_at,
    finished_at: batch.finished_at || '',
    updated_at: batch.updated_at,
  };
  if (index >= 0) summaries[index] = summary;
  else summaries.push(summary);
  state.agentThreads[nodeId] = { ...payload, thread: { ...thread, agent_batches: summaries.slice(-20) } };
}

function renderAgentExecutionMonitor(nodeId) {
  const batch = latestAgentBatch(nodeId);
  if (!batch) {
    const call = latestAgentCall(nodeId);
    return `<section class="agent-execution-monitor ${agentCallIsRunning(call) ? 'is-running' : ''}" data-agent-execution-monitor>${call ? renderAgentCallStatus(nodeId) : '<p class="muted">Agent 执行监视器待启动。</p>'}</section>`;
  }
  const progress = batch.progress || {};
  const running = agentBatchIsRunning(batch);
  const elapsedMs = running
    ? Math.max(0, Date.now() - Date.parse(batch.started_at || new Date().toISOString()))
    : Math.max(0, Date.parse(batch.finished_at || batch.updated_at || new Date().toISOString()) - Date.parse(batch.started_at || new Date().toISOString()));
  const proposals = (batch.proposals || []).filter(item => item.status === 'pending');
  const subjectLabel = batch.subject_kind === 'keyword' ? '关键词' : '商品';
  return `
    <section class="agent-execution-monitor ${running ? 'is-running' : ''}" data-agent-execution-monitor data-schema-version="analysis-agent-batch-v1">
      <div class="agent-monitor-heading"><strong>当前页批量填充</strong><span class="badge ${batch.status === 'review_ready' ? 'done' : running ? 'waiting' : batch.status === 'completed' ? 'done' : 'failed'}">${escapeHtml(batch.status || 'unknown')}</span><span class="muted" data-agent-batch-elapsed>已运行 ${(elapsedMs / 1000).toFixed(0)} 秒</span></div>
      <div class="agent-monitor-stats"><span>对象：${subjectLabel}</span><span>模型：${escapeHtml(batch.requested_model || '未知')}</span><span>已完成 ${progress.completed_products || 0}/${progress.eligible_products || 0}</span><span>运行中 ${progress.running_products || 0}</span><span>缺少证据 ${progress.no_evidence_products || 0}</span><span>失败 ${progress.failed_products || 0}</span><span>已生成建议 ${progress.proposed_cells || 0}/${progress.target_cells || 0}</span>${progress.rejected_cells ? `<span class="call-warning">规则拒绝 ${progress.rejected_cells}</span>` : ''}</div>
      <p class="muted" data-agent-batch-stage>${escapeHtml(batch.public_stage || (running ? `正在处理${subjectLabel}` : '等待用户复核'))}</p>
      ${batch.status === 'review_ready' ? `<button data-agent-batch-review="${escapeHtml(batch.batch_id)}" ${proposals.length ? '' : 'disabled'}>进入一键复核（${proposals.length}）</button>${proposals.length ? '' : '<span class="muted">本批次暂无可应用建议，请展开明细查看原因。</span>'}` : ''}
      ${running ? `<button class="secondary" data-agent-batch-cancel="${escapeHtml(batch.batch_id)}">停止批次</button>` : ''}
      ${batch.items?.length ? `<details><summary>${subjectLabel}明细</summary><div class="agent-batch-items">${batch.items.map(item => `<div class="agent-batch-item"><strong>${escapeHtml(item.keyword || item.product?.product_name || item.product?.product_id || item.row_id)}</strong><span>${escapeHtml(item.proposal_status || item.status || '')}</span><span>${escapeHtml((item.target_fields || []).join('、'))}</span><span>${escapeHtml(item.actual_model || item.requested_model || '模型未知')} · ${escapeHtml(item.model_comparison_reason || 'unknown')}</span><span>返回 ${Number(item.raw_patch_count || 0)} · 接受 ${Number(item.accepted_patch_count || 0)}</span>${Object.keys(item.evidence_values || {}).length ? `<span>提交证据：${escapeHtml(Object.entries(item.evidence_values).map(([key, value]) => `${key}=${Array.isArray(value) ? value.join('、') : value}`).join('；'))}</span>` : ''}${item.patch_diagnostics?.length ? `<span>Patch 解析：${escapeHtml(item.patch_diagnostics.map(diagnostic => `${diagnostic.patch_format || 'unknown'} -> ${diagnostic.normalized_field || '-'} (${diagnostic.status || 'unknown'}${diagnostic.reason ? `:${diagnostic.reason}` : ''})`).join('；'))}</span>` : ''}${item.proposal_risks?.length ? `<span class="call-warning">${escapeHtml(item.proposal_risks.join('、'))}</span>` : ''}${item.failure_reason ? `<span class="call-warning">${escapeHtml(item.failure_reason)}</span>` : ''}</div>`).join('')}</div></details>` : ''}
    </section>
  `;
}

function renderAgentBatchReview(nodeId) {
  const batch = state.agentBatches[nodeId]?.batch;
  if (!batch || !['review_ready', 'completed'].includes(batch.status)) return '';
  const proposals = (batch.proposals || []).filter(item => item.status === 'pending');
  if (!proposals.length) return '';
  const selected = new Set(state.agentBatchReview[nodeId]?.proposalIds || []);
  const subjectLabel = batch.subject_kind === 'keyword' ? '关键词' : '商品';
  return `<section class="agent-batch-review" data-agent-batch-review-panel="${escapeHtml(batch.batch_id)}"><div class="agent-batch-review-heading"><strong>批量建议复核</strong><button class="link-button" data-agent-batch-select-all="${escapeHtml(batch.batch_id)}">选择当前全部可应用建议</button></div><div class="artifact-table-wrap"><table class="artifact-table"><thead><tr><th>${subjectLabel}</th><th>字段</th><th>当前值</th><th>建议值</th><th>理由</th><th>置信度</th><th>证据</th><th>选择</th></tr></thead><tbody>${proposals.map(proposal => `<tr><td>${escapeHtml(proposal.keyword || proposal.product_name || proposal.product_id || proposal.row_id)}</td><td>${escapeHtml(proposal.field_path)}</td><td>${escapeHtml(proposal.old_value || '空')}</td><td>${escapeHtml(Array.isArray(proposal.new_value) ? proposal.new_value.join('、') : proposal.new_value || '')}</td><td>${escapeHtml(proposal.reason || '')}</td><td>${escapeHtml(proposal.confidence ?? '')}</td><td>${escapeHtml((proposal.evidence_refs || []).join('、') || Object.keys(proposal.evidence_values || {}).join('、'))}</td><td><input type="checkbox" data-agent-batch-proposal="${escapeHtml(proposal.proposal_id)}" ${selected.has(proposal.proposal_id) ? 'checked' : ''}></td></tr>`).join('')}</tbody></table></div><div class="agent-actions"><button data-agent-batch-apply="${escapeHtml(batch.batch_id)}">应用所选建议</button><button class="secondary" data-agent-batch-review-close>关闭复核</button></div></section>`;
}

function renderAgentBatchMonitorArea(nodeId) {
  return `${renderAgentExecutionMonitor(nodeId)}${renderAgentBatchReview(nodeId)}`;
}

function patchAgentExecutionMonitor(nodeId, options = { elapsedOnly: true }) {
  const monitor = document.querySelector('[data-agent-execution-monitor]');
  if (!monitor || state.selectedNodeId !== nodeId) return;
  if (options.elapsedOnly) {
    const batch = latestAgentBatch(nodeId);
    const batchElapsed = monitor.querySelector('[data-agent-batch-elapsed]');
    if (batch && batchElapsed) batchElapsed.textContent = `已运行 ${Math.max(0, (Date.now() - Date.parse(batch.started_at || new Date().toISOString())) / 1000).toFixed(0)} 秒`;
    const call = latestAgentCall(nodeId);
    const callElapsed = monitor.querySelector('[data-agent-call-elapsed]');
    if (!batch && agentCallIsRunning(call) && callElapsed) callElapsed.textContent = `已等待 ${Math.max(0, (Date.now() - Date.parse(call.started_at || new Date().toISOString())) / 1000).toFixed(0)} 秒`;
    return;
  }
  const rendered = renderAgentExecutionMonitor(nodeId);
  const wrapper = document.createElement('div');
  wrapper.innerHTML = rendered;
  const next = wrapper.firstElementChild;
  if (next) monitor.replaceWith(next);
}

function agentThreadNearBottom(element) {
  return Boolean(element && element.scrollHeight - element.scrollTop - element.clientHeight < 32);
}

function captureAgentInteractionState(nodeId) {
  const thread = document.querySelector('[data-agent-thread]');
  const input = document.querySelector('[data-agent-thread-input]');
  if (!thread) return state.agentScrollState[nodeId] || {};
  const previous = state.agentScrollState[nodeId] || {};
  const active = document.activeElement;
  state.agentScrollState[nodeId] = {
    scrollTop: thread.scrollTop,
    nearBottom: agentThreadNearBottom(thread),
    inputValue: input?.value ?? '',
    inputFocused: active === input,
    forceBottom: Boolean(previous.forceBottom),
  };
  return state.agentScrollState[nodeId];
}

function restoreAgentInteractionState(nodeId, options = {}) {
  const thread = document.querySelector('[data-agent-thread]');
  const input = document.querySelector('[data-agent-thread-input]');
  const saved = state.agentScrollState[nodeId] || {};
  if (input && saved.inputValue !== undefined && document.activeElement !== input) input.value = saved.inputValue;
  if (thread) {
    if (options.forceBottom || saved.forceBottom || saved.nearBottom) thread.scrollTop = thread.scrollHeight;
    else if (saved.scrollTop !== undefined) thread.scrollTop = saved.scrollTop;
  }
  if (input && saved.inputFocused) input.focus();
  if (saved.forceBottom) state.agentScrollState[nodeId] = { ...saved, forceBottom: false };
  const newResults = document.querySelector('[data-agent-new-results]');
  if (newResults && (!saved.nearBottom && !options.forceBottom)) newResults.hidden = false;
}

function agentCallIsRunning(call) {
  return Boolean(call && ['preparing', 'running'].includes(call.status));
}

function renderAgentCallStatus(nodeId) {
  const call = latestAgentCall(nodeId);
  if (!call) return '';
  const failed = ['failed', 'timed_out', 'cancelled'].includes(call.status);
  const badge = call.status === 'completed' ? 'done' : failed ? 'failed' : 'waiting';
  const durationMs = agentCallIsRunning(call)
    ? Math.max(0, Date.now() - Date.parse(call.started_at || new Date().toISOString()))
    : Number(call.duration_ms || 0);
  const duration = agentCallIsRunning(call) ? `已等待 ${(durationMs / 1000).toFixed(0)} 秒` : `${(durationMs / 1000).toFixed(1)} 秒`;
  return `
    <section class="agent-call-status" data-agent-call-id="${escapeHtml(call.call_id || '')}">
      <div class="agent-call-heading">
        <strong>本次 Agent 调用</strong>
        <span class="badge ${badge}">${escapeHtml(call.status || 'unknown')}</span>
        <span class="muted" data-agent-call-elapsed>${escapeHtml(duration)}</span>
      </div>
      <details open>
        <summary>本次提交内容</summary>
        ${renderAgentContextSnapshot(call.context_snapshot)}
      </details>
      <details open>
        <summary>执行阶段</summary>
        <ol class="agent-call-timeline">
          ${(call.timeline || []).map(item => `<li><span>${escapeHtml(item.label || item.stage || '')}</span><time>${escapeHtml(item.at || '')}</time></li>`).join('') || '<li>等待开始</li>'}
        </ol>
      </details>
      <div class="agent-call-models">
        <span>请求模型：${escapeHtml(call.requested_model || '未知')}</span>
        <span>实际模型：${escapeHtml(call.actual_model || '未知')}</span>
      </div>
      ${call.model_resolution_status === 'substituted' ? '<p class="call-warning">实际模型与请求模型不一致，本次结果需额外复核。</p>' : ''}
      ${failed ? `
        <div class="agent-call-failure">
          <strong>本次 Agent 调用未完成</strong>
          <p>原因：${escapeHtml(call.failure_reason || call.status || 'unknown')}</p>
          ${call.partial_output ? `<details><summary>未完成内容</summary><pre>${escapeHtml(call.partial_output)}</pre></details>` : ''}
          <div class="agent-actions">
            <button data-agent-call-retry="${escapeHtml(call.call_id || '')}">重试当前模型</button>
            <button class="secondary" data-agent-call-switch-retry="${escapeHtml(call.call_id || '')}">切换模型后重试</button>
            <button class="secondary" data-agent-continue-manual>继续人工填写</button>
          </div>
        </div>
      ` : agentCallIsRunning(call) ? `<button class="secondary" data-agent-call-stop="${escapeHtml(call.call_id || '')}">停止</button>` : ''}
    </section>
  `;
}

function renderCellProposal(message) {
  const proposal = message.proposal;
  if (!proposal || proposal.schema_version !== 'data-table-edit-proposal-v1') return '';
  return `
    <div class="agent-proposal-card">
      ${(proposal.patches || []).map((patch, index) => {
        const applied = (message.applied_patch_indices || []).includes(index);
        return `
        <div class="agent-proposal-patch">
          <strong>${escapeHtml(patch.field_path || '')}</strong>
          <span class="proposal-diff">${escapeHtml(patch.old_value ?? '')} -> ${escapeHtml(patch.new_value ?? '')}</span>
          <span class="muted">${escapeHtml(patch.reason || '未提供理由')} · 置信度 ${escapeHtml(patch.confidence ?? 0)}</span>
          <span class="muted">证据：${listText(patch.evidence_refs || [], '无')}</span>
          ${applied ? '<span class="badge done">已回填</span>' : ['pending', 'partially_applied'].includes(message.proposal_status) ? `<div class="agent-actions"><button data-agent-proposal-apply="${escapeHtml(message.message_id)}" data-proposal-patch-index="${index}">回填此单元格</button><button class="secondary" data-agent-proposal-ignore="${escapeHtml(message.message_id)}">忽略</button></div>` : `<span class="badge done">${escapeHtml(message.proposal_status || '已处理')}</span>`}
        </div>
      `;}).join('') || '<p class="muted">本次没有可回填的单元格建议。</p>'}
    </div>
  `;
}

function renderInsightProposal(message, insightPayload) {
  const proposal = message.proposal;
  if (!proposal || proposal.schema_version !== 'insight-edit-proposal-v1') return '';
  const block = insightPayload?.workspace?.blocks?.find(item => item.requirement_id === message.requirement_id);
  const draftText = message.proposal_status === 'saved_as_draft' ? block?.draft_text || proposal.proposed_text : proposal.proposed_text;
  const bindings = Array.isArray(block?.evidence_bindings) && block.evidence_bindings.length
    ? block.evidence_bindings
    : proposal.evidence_bindings || [];
  return `
    <div class="agent-proposal-card insight-chat-proposal">
      <label>结论草稿<textarea data-agent-insight-draft="${escapeHtml(message.message_id)}">${escapeHtml(draftText || '')}</textarea></label>
      <div class="insight-evidence-picker">
        ${(block?.required_evidence_fields || []).map(fieldPath => `<label><input type="checkbox" data-agent-insight-evidence="${escapeHtml(message.message_id)}" value="${escapeHtml(fieldPath)}" ${bindings.some(item => item.field_path === fieldPath) ? 'checked' : ''}>${escapeHtml(fieldPath)}</label>`).join('') || '<span class="muted">当前要求没有预设证据字段。</span>'}
      </div>
      <p class="muted">风险：${listText(proposal.risks || [], '无')} · 状态：${escapeHtml(block?.status || message.proposal_status || 'pending')}</p>
      <div class="agent-actions">
        <button data-agent-insight-save="${escapeHtml(message.message_id)}" data-requirement-id="${escapeHtml(message.requirement_id || '')}">保存为结论草稿</button>
        <button class="secondary" data-agent-insight-confirm="${escapeHtml(message.message_id)}" data-requirement-id="${escapeHtml(message.requirement_id || '')}" ${!String(block?.draft_text || '').trim() || !(block?.evidence_bindings || []).length || block?.status === 'stale' ? 'disabled' : ''}>确认此结论</button>
      </div>
    </div>
  `;
}

function renderUnifiedAgentThread(nodeId, insightPayload) {
  const messages = agentThreadFor(nodeId).messages || [];
  return `
    <div class="agent-thread unified-agent-thread" data-agent-thread>
      ${messages.length ? messages.map(message => `
        <article class="agent-message role-${escapeHtml(message.role || 'user')}">
          <div class="agent-message-heading"><strong>${message.role === 'assistant' ? 'Agent' : message.role === 'context' ? '已加入上下文' : '你'}</strong>${message.requirement_id ? `<span class="badge">${escapeHtml(message.requirement_id)}</span>` : ''}</div>
          ${renderAgentContextRefs(message.context_refs)}
          <p>${escapeHtml(message.text || '')}</p>
          ${message.failure_reason ? `<p class="call-warning">失败原因：${escapeHtml(message.failure_reason)} · 请求模型：${escapeHtml(message.requested_model || '未知')} · 实际模型：${escapeHtml(message.actual_model || '未知')}</p>` : ''}
          ${renderCellProposal(message)}
          ${renderInsightProposal(message, insightPayload)}
        </article>
      `).join('') : '<p class="muted">选择单元格加入对话，或点击一个业务分析问题开始。</p>'}
    </div>
  `;
}

function renderAnalysisCollaborationAgent(node) {
  if (!node || !isDataAnalysisNode(node)) return '';
  const tablePayload = state.dataTableWorkspaces[node.id];
  const insightPayload = state.insightWorkspaces[node.id];
  const busy = Boolean(state.piAgentBusy[node.id]);
  const thread = agentThreadFor(node.id);
  const activeContext = (thread.messages || []).find(item => item.message_id === thread.active_context_message_id);
  return `
    <div class="db-agent-panel analysis-collaboration-agent">
      <h3>分析协作 Agent</h3>
      ${renderPiAgentStatus()}
      ${renderAgentBatchMonitorArea(node.id)}
      <section class="agent-insight-questions">
        <h4>业务分析问题</h4>
        ${(insightPayload?.workspace?.blocks || []).map(block => `<button class="agent-insight-link" data-agent-insight-question="${escapeHtml(block.requirement_id)}" ${busy || !tablePayload?.workspace ? 'disabled' : ''}>${escapeHtml(block.question || block.requirement_id)}</button>`).join('') || '<p class="muted">运行节点后会显示业务文档中的分析问题。</p>'}
      </section>
      ${renderUnifiedAgentThread(node.id, insightPayload)}
      <button class="link-button agent-new-results" data-agent-new-results hidden>有新结果</button>
      <section class="agent-composer">
        <div class="agent-active-context" data-agent-active-context>${activeContext ? `<details open><summary>本次提交内容</summary>${renderAgentContextRefs(activeContext.context_refs)}</details>` : ''}</div>
        <textarea class="agent-input" data-agent-thread-input placeholder="补充问题，或直接提出新的数据分析问题"></textarea>
        <button data-agent-thread-send ${busy || !tablePayload?.workspace ? 'disabled' : ''}>发送</button>
        <p class="muted">Agent 只生成建议；表格回填、结论保存和确认都需要你显式操作。</p>
      </section>
    </div>
  `;
}

function renderAgentPanel() {
  const node = currentNode();
  const view = node?.node_execution_view || {};
  const fields = node ? nodeActionFields(node) : [];
  return `
    <p class="muted">当前焦点：${escapeHtml(node?.name || '未选择节点')}</p>
    <p>${escapeHtml(view.goal?.markdown || '当前节点暂无结构化目标。')}</p>
    ${fields.length > 0 ? `<p class="muted">可协助填写：${listText(fields.map(field => field.label || field.id), '无')}</p>` : ''}
    ${renderAnalysisCollaborationAgent(node)}
  `;
}

function render() {
  if (state.selectedNodeId && document.querySelector('[data-agent-thread]')) captureAgentInteractionState(state.selectedNodeId);
  if (!state.config) {
    document.getElementById('app').innerHTML = '<div class="loading">正在加载应用配置...</div>';
    return;
  }
  document.title = state.config.task_ref?.title || state.config.app_slug || 'Report Generator';
  document.getElementById('app').innerHTML = `
    <main class="shell">
      <header class="topbar">
        <div>
          <h1>${escapeHtml(state.config.task_ref?.title || state.config.app_slug)}</h1>
          <p>${escapeHtml(state.config.shell_kind)} · ${escapeHtml(state.config.shell_version || 'dev')}</p>
        </div>
        <button id="export-report" class="secondary">导出报告</button>
      </header>
      <section class="layout" data-layout style="${escapeHtml(layoutStyle())}">
        <aside class="panel flow-panel">
          <h2>运行流程</h2>
          ${renderNodeList()}
        </aside>
        <div class="panel-resizer" data-layout-resizer="left" role="separator" aria-label="调整运行流程和节点详情宽度" tabindex="0"></div>
        <section class="panel main-panel">
          <h2>节点详情</h2>
          ${renderNodeDetail()}
        </section>
        <div class="panel-resizer" data-layout-resizer="right" role="separator" aria-label="调整节点详情和右侧 Agent 宽度" tabindex="0"></div>
        <aside class="panel agent-panel">
          <h2>右侧 Agent</h2>
          ${renderAgentPanel()}
        </aside>
      </section>
    </main>
  `;
  bindEvents();
}

function bindEvents() {
  document.querySelectorAll('[data-node-id]').forEach(button => {
    button.addEventListener('click', async () => {
      state.selectedNodeId = button.getAttribute('data-node-id') || '';
      await refreshConfirmedUpstreamArtifacts(currentNode());
      await refreshCollaborationWorkspaces(state.selectedNodeId, { render: false });
      await refreshGeneAnalysis(state.selectedNodeId, { render: false });
      render();
    });
  });
  const runButton = document.getElementById('run-node');
  if (runButton) {
    runButton.addEventListener('click', runCurrentNode);
  }
  document.querySelectorAll('[data-gene-page]').forEach(button => button.addEventListener('click', () => {
    const node = currentNode();
    if (!node) return;
    const delta = button.getAttribute('data-gene-page') === 'next' ? 1 : -1;
    state.dataTablePages[node.id] = Math.max(1, Number(state.dataTablePages[node.id] || 1) + delta);
    render();
  }));
  const geneConfirm = document.querySelector('[data-gene-confirm]');
  if (geneConfirm) geneConfirm.addEventListener('click', () => confirmHotProductGeneAnalysis(geneConfirm.getAttribute('data-gene-confirm') || ''));
  const geneCancel = document.querySelector('[data-gene-cancel]');
  if (geneCancel) geneCancel.addEventListener('click', () => cancelHotProductGeneAnalysis(geneCancel.getAttribute('data-gene-cancel') || ''));
  const geneRetry = document.querySelector('[data-gene-retry]');
  if (geneRetry) geneRetry.addEventListener('click', () => retryHotProductGeneAnalysis(geneRetry.getAttribute('data-gene-retry') || ''));
  const topNSelect = document.querySelector('[data-analysis-top-n]');
  if (topNSelect) {
    topNSelect.addEventListener('change', () => {
      const node = currentNode();
      if (!node) return;
      state.dataAnalysisTopN[node.id] = Number(topNSelect.value || 20);
      saveWorkbenchState();
      render();
    });
  }
  const saveDraftButton = document.getElementById('save-node-draft');
  if (saveDraftButton) {
    saveDraftButton.addEventListener('click', handleSaveNodeDraft);
  }
  const exportButton = document.getElementById('export-report');
  if (exportButton) {
    exportButton.addEventListener('click', exportReport);
  }
  document.querySelectorAll('[data-workbench-action]').forEach(button => {
    button.addEventListener('click', () => {
      const action = button.getAttribute('data-workbench-action') || '';
      if (action === 'suggest') suggestFieldMappingWithPi();
    });
  });
  document.querySelectorAll('[data-candidate-action]').forEach(button => {
    button.addEventListener('click', () => {
      applyCandidateFieldOption(button);
    });
  });
  document.querySelectorAll('[data-api-field-filter]').forEach(input => {
    input.addEventListener('input', () => {
      updateApiFieldBrowserFilter(input);
    });
  });
  document.querySelectorAll('[data-api-field-browser-action]').forEach(button => {
    button.addEventListener('click', () => {
      applyApiFieldBrowserSelection(button);
    });
  });
  document.querySelectorAll('[data-advice-action]').forEach(button => {
    button.addEventListener('click', () => {
      applyAdviceAction(button.getAttribute('data-advice-action') || '', button.getAttribute('data-advice-field') || '');
    });
  });
  const piModelSelect = document.querySelector('[data-pi-model-select]');
  if (piModelSelect) {
    piModelSelect.addEventListener('change', () => updateThreadPreferredModel(piModelSelect.value || ''));
  }
  document.querySelectorAll('[data-table-cell]').forEach(cell => {
    cell.addEventListener('click', event => {
      if (!event.target.matches('[data-table-cell-editor]')) selectTableCell(cell, event);
    });
    cell.addEventListener('dblclick', () => beginTableCellEdit(cell));
    cell.addEventListener('keydown', event => {
      if ((event.key === 'Enter' || event.key === 'F2') && !cell.querySelector('[data-table-cell-editor]')) {
        event.preventDefault();
        beginTableCellEdit(cell);
      }
    });
  });
  document.querySelectorAll('[data-restore-table-cell]').forEach(button => button.addEventListener('click', event => {
    event.preventDefault();
    event.stopPropagation();
    restoreTableCellSource(button);
  }));
  document.querySelectorAll('[data-table-cell-editor]').forEach(editor => {
    let committed = false;
    const cell = editor.closest('[data-table-cell]');
    editor.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        event.preventDefault();
        const node = currentNode();
        if (node) delete state.tableEditing[node.id];
        committed = true;
        render();
      } else if (event.key === 'Enter' || event.key === 'Tab') {
        event.preventDefault();
        committed = true;
        commitTableCellEditor(cell);
      }
    });
    editor.addEventListener('blur', () => {
      if (!committed) commitTableCellEditor(cell);
    });
  });
  document.querySelectorAll('[data-select-table-column]').forEach(header => header.addEventListener('click', () => selectTableColumn(header.getAttribute('data-select-table-column') || '')));
  document.querySelectorAll('[data-select-table-row]').forEach(cell => cell.addEventListener('click', () => selectTableRow(cell.getAttribute('data-select-table-row') || '')));
  const selectWholeTableButton = document.querySelector('[data-select-whole-table]');
  if (selectWholeTableButton) selectWholeTableButton.addEventListener('click', selectWholeTable);
  document.querySelectorAll('[data-extension-field-edit]').forEach(button => button.addEventListener('click', event => {
    event.preventDefault();
    event.stopPropagation();
    editExtensionField(button.getAttribute('data-extension-field-edit') || '');
  }));
  document.querySelectorAll('[data-extension-field-delete]').forEach(button => button.addEventListener('click', event => {
    event.preventDefault();
    event.stopPropagation();
    deleteExtensionField(button.getAttribute('data-extension-field-delete') || '');
  }));
  document.querySelectorAll('[data-editable-table]').forEach(table => table.addEventListener('paste', event => pasteTableRegion(event, table)));
  document.querySelectorAll('[data-table-workspace-page]').forEach(button => button.addEventListener('click', () => {
    const node = currentNode();
    if (!node) return;
    const direction = button.getAttribute('data-table-workspace-page') === 'next' ? 1 : -1;
    state.dataTablePages[node.id] = Math.max(1, Number(state.dataTablePages[node.id] || 1) + direction);
    render();
  }));
  document.querySelectorAll('[data-agent-batch-start]').forEach(button => button.addEventListener('click', () => startAgentBatch(Number(button.getAttribute('data-page-number') || 1))));
  const confirmTableButton = document.querySelector('[data-table-confirm-advance]');
  if (confirmTableButton) confirmTableButton.addEventListener('click', confirmDataTableAndAdvance);
  document.querySelectorAll('[data-agent-batch-proposal]').forEach(input => input.addEventListener('change', () => {
    const nodeId = currentNode()?.id || '';
    const selected = new Set(state.agentBatchReview[nodeId]?.proposalIds || []);
    if (input.checked) selected.add(input.getAttribute('data-agent-batch-proposal') || '');
    else selected.delete(input.getAttribute('data-agent-batch-proposal') || '');
    state.agentBatchReview[nodeId] = { proposalIds: Array.from(selected) };
  }));
  const agentPanel = document.querySelector('.analysis-collaboration-agent');
  if (agentPanel) agentPanel.addEventListener('click', event => {
    const target = event.target.closest('[data-agent-batch-start], [data-agent-batch-review], [data-agent-batch-review-close], [data-agent-batch-select-all], [data-agent-batch-apply], [data-agent-batch-cancel], [data-agent-call-retry], [data-agent-call-switch-retry], [data-agent-call-stop], [data-agent-continue-manual]');
    if (!target) return;
    if (target.matches('[data-agent-batch-start]')) startAgentBatch(Number(target.getAttribute('data-page-number') || 1));
    else if (target.matches('[data-agent-batch-review]')) {
      state.agentBatchReview[currentNode()?.id || ''] = { proposalIds: [] };
      render();
    } else if (target.matches('[data-agent-batch-review-close]')) {
      delete state.agentBatchReview[currentNode()?.id || ''];
      render();
    } else if (target.matches('[data-agent-batch-select-all]')) {
      const nodeId = currentNode()?.id || '';
      const batch = state.agentBatches[nodeId]?.batch;
      state.agentBatchReview[nodeId] = { proposalIds: (batch?.proposals || []).filter(item => item.status === 'pending').map(item => item.proposal_id) };
      render();
    } else if (target.matches('[data-agent-batch-apply]')) applyAgentBatchProposals(target.getAttribute('data-agent-batch-apply') || '');
    else if (target.matches('[data-agent-batch-cancel]')) cancelAgentBatch(target.getAttribute('data-agent-batch-cancel') || '');
    else if (target.matches('[data-agent-call-retry]')) retryAgentCall(target.getAttribute('data-agent-call-retry') || '');
    else if (target.matches('[data-agent-call-switch-retry]')) retryAgentCall(target.getAttribute('data-agent-call-switch-retry') || '', { switchModel: true });
    else if (target.matches('[data-agent-call-stop]')) stopAgentCall(target.getAttribute('data-agent-call-stop') || '');
    else if (target.matches('[data-agent-continue-manual]')) document.querySelector('[data-cell-action-input]')?.focus();
  });
  const undoButton = document.querySelector('[data-table-undo]');
  if (undoButton) undoButton.addEventListener('click', undoDataTableWorkspace);
  const addFieldButton = document.querySelector('[data-table-add-field]');
  if (addFieldButton) addFieldButton.addEventListener('click', addExtensionField);
  const cellActionSave = document.querySelector('[data-cell-action-save]');
  if (cellActionSave) cellActionSave.addEventListener('click', async () => {
    const node = currentNode();
    if (!node) return;
    const selection = dataTableSelectionFor(node.id);
    const cell = selection.scope_mode === 'cells' && selection.cells?.length === 1 ? selection.cells[0] : null;
    const input = document.querySelector('[data-cell-action-input]');
    if (!cell || !input) return;
    const current = tableCellDescriptor(node.id, cell.row_id, cell.field_path).effective_value;
    const next = input.value || '';
    if (String(current) === String(next)) return;
    await patchDataTableWorkspace([{ operation: next === '' ? 'clear_cell' : 'set_cell', row_id: cell.row_id, field_path: cell.field_path, expected_value: current, new_value: next, source_kind: 'manual', reason: '用户通过单元格操作条填写' }]);
  });
  const cellAddToChat = document.querySelector('[data-cell-add-to-chat]');
  if (cellAddToChat) cellAddToChat.addEventListener('click', addSelectedCellToAgent);
  const cellActionRestore = document.querySelector('[data-cell-action-restore]');
  if (cellActionRestore) cellActionRestore.addEventListener('click', async () => {
    const node = currentNode();
    const selection = node && dataTableSelectionFor(node.id);
    const cell = selection?.scope_mode === 'cells' && selection.cells?.length === 1 ? selection.cells[0] : null;
    if (!node || !cell) return;
    const current = tableCellDescriptor(node.id, cell.row_id, cell.field_path).effective_value;
    await patchDataTableWorkspace([{ operation: 'restore_source', row_id: cell.row_id, field_path: cell.field_path, expected_value: current }], { message: '已恢复 API 原值。' });
  });
  document.querySelectorAll('[data-agent-insight-question]').forEach(button => button.addEventListener('click', () => {
    const node = currentNode();
    const requirementId = button.getAttribute('data-agent-insight-question') || '';
    const block = state.insightWorkspaces[node?.id]?.workspace?.blocks?.find(item => item.requirement_id === requirementId);
    if (block) sendUnifiedAgentMessage({ requirementId, message: block.question });
  }));
  const agentSend = document.querySelector('[data-agent-thread-send]');
  if (agentSend) agentSend.addEventListener('click', () => sendUnifiedAgentMessage());
  const agentInput = document.querySelector('[data-agent-thread-input]');
  if (agentInput) agentInput.addEventListener('keydown', event => {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      sendUnifiedAgentMessage();
    }
  });
  document.querySelectorAll('[data-agent-proposal-apply]').forEach(button => button.addEventListener('click', () => actOnAgentThread('apply_cell_proposal', button.getAttribute('data-agent-proposal-apply') || '', { patchIndices: [Number(button.getAttribute('data-proposal-patch-index'))] })));
  document.querySelectorAll('[data-agent-proposal-ignore]').forEach(button => button.addEventListener('click', () => actOnAgentThread('ignore_proposal', button.getAttribute('data-agent-proposal-ignore') || '')));
  document.querySelectorAll('[data-agent-insight-save]').forEach(button => button.addEventListener('click', () => {
    const messageId = button.getAttribute('data-agent-insight-save') || '';
    const requirementId = button.getAttribute('data-requirement-id') || '';
    const editor = document.querySelector(`[data-agent-insight-draft="${CSS.escape(messageId)}"]`);
    actOnAgentThread('save_insight_draft', messageId, { requirementId, draftText: editor?.value || '', evidenceBindings: evidenceBindingsFromAgentMessage(messageId) });
  }));
  document.querySelectorAll('[data-agent-insight-confirm]').forEach(button => button.addEventListener('click', () => actOnAgentThread('confirm_insight', button.getAttribute('data-agent-insight-confirm') || '', { requirementId: button.getAttribute('data-requirement-id') || '' })));
  const chatThread = document.querySelector('[data-agent-thread]');
  const newResults = document.querySelector('[data-agent-new-results]');
  if (newResults) newResults.addEventListener('click', () => {
    if (chatThread) chatThread.scrollTop = chatThread.scrollHeight;
    newResults.hidden = true;
    captureAgentInteractionState(currentNode()?.id || '');
  });
  restoreAgentInteractionState(currentNode()?.id || '');
  bindLayoutResizers();
}

async function fetchDbAgentStatus() {
  try {
    const response = await fetch('/api/db-agent/status');
    state.dbAgentStatus = await response.json();
  } catch (error) {
    state.dbAgentStatus = { status: 'degraded', reason: error.message || String(error), live_probe_enabled: false };
  }
}

async function fetchPiAgentStatus() {
  try {
    const response = await fetch('/api/pi-agent/status');
    state.piAgentStatus = await response.json();
  } catch (error) {
    state.piAgentStatus = { provider: 'pi_agent', status: 'not_configured', reason: error.message || String(error), capabilities: ['data_mapping_advice'] };
  }
}

async function queryDbAgent(action, options = {}) {
  const node = currentNode();
  if (!node || !isDataMappingNode(node)) return;
  const previousResult = state.dbAgentResults[node.id];
  state.dbAgentBusy[node.id] = true;
  state.dbAgentResults[node.id] = { status: 'running', message: '数仓助手正在查询...' };
  saveDbAgentResults();
  render();
  try {
    const body = {
      node_id: node.id,
      action,
      upstream_artifacts: upstreamArtifactsFor(node),
    };
    if (options.api_id) {
      body.api_id = options.api_id;
    }
    if (action === 'domain_apis') {
      body.domain = '商品域';
      body.limit = 20;
    }
    if (action === 'probe_sample') {
      body.api_id = options.api_id || firstSourceApiFromDbAgentResult(previousResult);
    }
    if (action === 'suggest_multi_api_mapping') {
      body.auto_select_apis = true;
      delete state.fieldMappingDrafts[node.id];
    }
    const response = await fetch('/api/db-agent/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.reason || payload.error || `db agent failed: ${response.status}`);
    }
    if (action === 'suggest_multi_api_mapping' && payload.payload?.field_coverage_plan) {
      state.fieldMappingDrafts[node.id] = payload.payload.field_coverage_plan;
      delete state.piAgentResults[node.id];
    } else if (payload.data_mapping_contract?.field_coverage_plan) {
      state.fieldMappingDrafts[node.id] = payload.data_mapping_contract.field_coverage_plan;
    } else if (payload.payload?.field_coverage_plan) {
      state.fieldMappingDrafts[node.id] = payload.payload.field_coverage_plan;
    } else if (payload.data_mapping_contract?.output_field_mapping_overlay) {
      state.fieldMappingDrafts[node.id] = payload.data_mapping_contract.output_field_mapping_overlay;
    }
    if (action === 'suggest_multi_api_mapping') {
      const summary = payload.payload?.coverage_summary || payload.data_mapping_contract?.coverage_summary || coverageSummaryForFields(state.fieldMappingDrafts[node.id] || []);
      const total = Number(summary.total || 0);
      const mapped = Number(summary.mapped || 0);
      const derived = Number(summary.derived_or_manual_required || summary.derived || 0);
      const missing = Number(summary.missing_required || summary.missingRequired || 0);
      state.saveStatus[node.id] = {
        status: mapped > 0 && missing === 0 ? 'done' : 'waiting',
        message: `已生成字段覆盖方案：${mapped}/${total} 已覆盖，${derived} 个派生/人工字段，${missing} 个必填未覆盖。可运行节点取数，或继续人工修正字段。`,
      };
    }
    state.dbAgentResults[node.id] = payload;
    if (payload.artifact) {
      rememberNodeArtifact(node.id, payload.artifact);
      state.latestResult[node.id] = {
        status: 'collected',
        artifact_title: payload.artifact.title,
        artifact_path: payload.artifact.artifact_path || '',
        rows: payload.artifact.rows || [],
        evidence_ref: payload.evidence_ref,
        source: 'db_agent',
      };
      state.nodeStatus[node.id] = 'done';
    }
  } catch (error) {
    state.dbAgentResults[node.id] = { ok: false, status: 'error', reason: error.message || String(error) };
  } finally {
    state.dbAgentBusy[node.id] = false;
    saveDbAgentResults();
    saveWorkbenchState();
    render();
  }
}

function manualMappingForNode(node) {
  const draft = Array.isArray(state.fieldMappingDrafts[node.id]) ? state.fieldMappingDrafts[node.id] : [];
  if (draft.length > 0) return draft;
  const contract = contractFromDbAgentResult(dbAgentResultFor(node));
  const responseMappings = Array.isArray(contract?.response_field_mapping) ? contract.response_field_mapping : [];
  const outputFields = outputFieldRequirementsForNode(node);
  return responseMappings
    .filter(item => item.api_field_path)
    .map(item => {
      const outputField = outputFields.find(field => field.field_name === item.business_field || field.title === item.business_field) || {};
      return {
        output_id: outputField.output_id || item.output_id || '',
        field_path: outputField.field_path || item.field_path || item.business_field || '',
        field_name: outputField.field_name || item.business_field || '',
        title: outputField.title || item.business_field || '',
        api_field_path: item.api_field_path || '',
        api_field_name: item.api_field_name || '',
        api_field_type: item.api_field_type || '',
        source_api_id: item.source_api_id || '',
        source_api_name: item.source_api_name || '',
        source_field_path: item.source_field_path || item.api_field_path || '',
        source_role: item.source_role || (item.api_field_path ? 'api_field' : ''),
        confidence: item.confidence ?? 1,
        human_confirmed: Boolean(item.human_confirmed || item.confirmed),
        status: item.status === 'matched' ? 'mapped' : item.status || 'mapped',
        mapping_status: item.mapping_status || item.status || 'mapped',
        match_basis: item.match_basis || 'agent_suggested',
        human_note: item.human_note || '',
      };
    });
}

function setMappingCorrectionTarget(fieldPath) {
  const node = currentNode();
  if (!node || !fieldPath) return;
  state.piCorrectionTargets[node.id] = fieldPath;
  saveWorkbenchState();
  render();
}

function currentCorrectionTargetField(node) {
  const targetPath = state.piCorrectionTargets[node.id] || '';
  const fields = currentFieldMappingOverlay(node);
  return fields.find(field => field.field_path === targetPath || field.field_name === targetPath)
    || fields.find(field => !field.source_field_path || ['unmapped', 'missing', 'derived_or_manual_required', 'manual_fill'].includes(String(field.mapping_status || field.status || '')))
    || fields[0]
    || null;
}

async function sendMappingCorrectionMessage() {
  const node = currentNode();
  if (!node || !isDataMappingNode(node)) return;
  const input = document.getElementById('mapping-correction-input');
  const message = String(input?.value || '').trim();
  const targetField = currentCorrectionTargetField(node);
  if (!message || !targetField) return;
  const thread = Array.isArray(state.piAgentThreads[node.id]) ? state.piAgentThreads[node.id] : [];
  const nextThread = [...thread, { role: 'user', content: message, created_at: new Date().toISOString() }];
  state.piAgentThreads[node.id] = nextThread;
  state.piAgentBusy[node.id] = true;
  saveWorkbenchState();
  render();
  try {
    const response = await fetch('/api/pi-agent/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        node_id: node.id,
        intent: 'mapping_correction',
        message,
        model: selectedPiModel(),
        target_field: targetField,
        conversation_history: nextThread,
        analysis_node_view: analysisNodeViewFor(node),
        data_mapping_contract: contractFromDbAgentResult(dbAgentResultFor(node)) || {},
        field_coverage_plan: currentFieldMappingOverlay(node),
        api_response_field_catalog: apiResponseFieldCatalogForNode(node),
        upstream_artifacts: upstreamArtifactsFor(node),
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.reason || payload.error || `pi agent failed: ${response.status}`);
    }
    state.piAgentResults[node.id] = payload;
    const summary = payload.advice?.summary?.text || payload.response_text || '已返回字段纠错建议，请在中间工作区应用或人工确认。';
    state.piAgentThreads[node.id] = [...nextThread, { role: 'assistant', content: summary, created_at: new Date().toISOString() }];
  } catch (error) {
    state.piAgentThreads[node.id] = [...nextThread, { role: 'assistant', content: `纠错失败：${error.message || error}`, created_at: new Date().toISOString() }];
    state.piAgentResults[node.id] = { ok: false, status: 'error', reason: error.message || String(error), advice: { requires_human_confirmation: true } };
  } finally {
    state.piAgentBusy[node.id] = false;
    saveWorkbenchState();
    render();
  }
}

async function queryPiAgent(intent = 'data_mapping_advice') {
  const node = currentNode();
  if (!node || !isDataMappingNode(node)) return;
  state.piAgentBusy[node.id] = true;
  render();
  try {
    const response = await fetch('/api/pi-agent/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        node_id: node.id,
        intent,
        model: selectedPiModel(),
        message: '请基于当前输出字段要求、候选 API 完整 schema 和确定性 baseline，逐字段给出判断、置信度、理由，并指出缺口和下一步问题。',
        analysis_node_view: analysisNodeViewFor(node),
        data_mapping_contract: contractFromDbAgentResult(dbAgentResultFor(node)) || {},
        field_coverage_plan: currentFieldMappingOverlay(node),
        api_response_field_catalog: apiResponseFieldCatalogForNode(node),
        upstream_artifacts: upstreamArtifactsFor(node),
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.reason || payload.error || `pi agent failed: ${response.status}`);
    }
    state.piAgentResults[node.id] = payload;
  } catch (error) {
    state.piAgentResults[node.id] = { ok: false, status: 'error', reason: error.message || String(error), advice: { requires_human_confirmation: true } };
  } finally {
    state.piAgentBusy[node.id] = false;
    saveWorkbenchState();
    render();
  }
}

// 一键生成字段覆盖方案只跑确定性 API 文档匹配；派生字段由单独的 PI 分析按钮处理。
async function suggestFieldMappingWithPi() {
  const node = currentNode();
  if (!node || !isDataMappingNode(node)) return;
  await queryDbAgent('suggest_multi_api_mapping');
}

// 写入或更新单个字段草稿；只落 draft overlay，不置 human_confirmed。
function upsertFieldDraft(node, fieldPath, patch) {
  const overlay = currentFieldMappingOverlay(node);
  const next = overlay.map(field => {
    if (field.field_path !== fieldPath && field.field_name !== fieldPath) return field;
    return { ...field, ...patch };
  });
  state.fieldMappingDrafts[node.id] = next;
}

function applyCandidateFieldOption(button) {
  const node = currentNode();
  if (!node) return;
  const fieldPath = button.getAttribute('data-candidate-field') || '';
  if (!fieldPath) return;
  upsertFieldDraft(node, fieldPath, {
    source_api_id: button.getAttribute('data-candidate-api-id') || '',
    source_api_name: button.getAttribute('data-candidate-api-name') || '',
    source_field_path: button.getAttribute('data-candidate-path') || '',
    api_field_path: button.getAttribute('data-candidate-path') || '',
    api_field_name: button.getAttribute('data-candidate-name') || '',
    api_field_type: button.getAttribute('data-candidate-type') || '',
    source_role: 'api_field',
    source_kind: 'api_doc_index',
    mapping_status: 'mapped',
    confidence: button.getAttribute('data-candidate-confidence') || 1,
    human_confirmed: false,
    human_note: '人工从候选字段中选择',
  });
  saveWorkbenchState();
  render();
}

function updateApiFieldBrowserFilter(input) {
  const node = currentNode();
  if (!node) return;
  const fieldPath = input.getAttribute('data-api-field-filter') || '';
  if (!fieldPath) return;
  const filter = String(input.value || '').trim().toLowerCase();
  state.apiFieldBrowserFilters[`${node.id}:${fieldPath}`] = input.value || '';
  const select = Array.from(document.querySelectorAll('[data-api-field-select]'))
    .find(item => item.getAttribute('data-api-field-select') === fieldPath);
  if (select) {
    let firstVisible = null;
    Array.from(select.options).forEach(option => {
      const matched = !filter || String(option.getAttribute('data-api-field-search') || '').includes(filter);
      option.hidden = !matched;
      if (matched && !firstVisible) firstVisible = option;
    });
    if (firstVisible) select.value = firstVisible.value;
  }
  saveWorkbenchState();
}

function applyApiFieldBrowserSelection(button) {
  const node = currentNode();
  if (!node) return;
  const fieldPath = button.getAttribute('data-api-field-browser-field') || '';
  const select = Array.from(document.querySelectorAll('[data-api-field-select]'))
    .find(item => item.getAttribute('data-api-field-select') === fieldPath);
  if (!fieldPath || !select) return;
  const catalog = apiResponseFieldCatalogForNode(node);
  const selected = catalog[Number(select.value)];
  if (!selected) return;
  upsertFieldDraft(node, fieldPath, {
    source_api_id: selected.source_api_id || '',
    source_api_name: selected.source_api_name || '',
    source_field_path: selected.source_field_path || '',
    api_field_path: selected.source_field_path || '',
    api_field_name: selected.api_field_name || '',
    api_field_type: selected.api_field_type || '',
    source_role: 'api_field',
    source_kind: 'api_doc_index',
    mapping_status: 'mapped',
    confidence: 1,
    human_confirmed: false,
    human_note: '人工筛选 API 返回字段',
  });
  state.saveStatus[node.id] = { status: 'done', message: '已将人工筛选字段回填到当前字段覆盖草稿。' };
  saveWorkbenchState();
  render();
}

async function collaborationRequest(url, options = {}) {
  const response = await fetch(url, {
    method: options.method || 'GET',
    headers: options.body ? { 'Content-Type': 'application/json' } : undefined,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const payload = await response.json();
  if (!response.ok) {
    const error = new Error(payload.error || `request failed: ${response.status}`);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

async function refreshGeneAnalysis(nodeId, options = {}) {
  const node = nodeById(nodeId);
  if (!isHotProductGeneNode(node)) return;
  try {
    const payload = await collaborationRequest(`/api/nodes/${encodeURIComponent(nodeId)}/gene-analysis`);
    state.geneAnalyses[nodeId] = payload;
    const analysis = payload.analysis;
    if (analysis?.status === 'running') observeGeneAnalysis(nodeId, analysis.execution_id);
    if (payload.confirmed_artifact?.status === 'confirmed') {
      rememberNodeArtifact(nodeId, payload.confirmed_artifact);
      state.nodeStatus[nodeId] = 'done';
    } else if (analysis?.status === 'draft_ready') {
      state.nodeStatus[nodeId] = 'waiting';
    }
    if (options.render !== false) render();
  } catch (error) {
    state.geneAnalyses[nodeId] = { analysis: null, confirmed_artifact: null, error: error.message };
    if (options.render !== false) render();
  }
}

function observeGeneAnalysis(nodeId, executionId) {
  const current = state.geneAnalysisSources[nodeId];
  if (current?.executionId === executionId) return;
  if (current?.source) current.source.close();
  if (state.geneAnalysisTimers[nodeId]) clearInterval(state.geneAnalysisTimers[nodeId]);
  const source = new EventSource(`/api/nodes/${encodeURIComponent(nodeId)}/gene-analysis/${encodeURIComponent(executionId)}/events`);
  state.geneAnalysisSources[nodeId] = { executionId, source };
  state.geneAnalysisTimers[nodeId] = setInterval(() => patchHotProductGeneMonitor(nodeId), 1000);
  const update = event => {
    const data = JSON.parse(event.data || '{}');
    if (!data.analysis || data.analysis.execution_id !== executionId) return;
    state.geneAnalyses[nodeId] = { ...(state.geneAnalyses[nodeId] || {}), analysis: data.analysis };
    patchHotProductGeneMonitor(nodeId);
    if (!['running', 'preparing'].includes(String(data.analysis.status || ''))) {
      source.close();
      clearInterval(state.geneAnalysisTimers[nodeId]);
      delete state.geneAnalysisSources[nodeId];
      delete state.geneAnalysisTimers[nodeId];
      state.nodeStatus[nodeId] = 'waiting';
      render();
    }
  };
  source.addEventListener('gene_analysis_snapshot', update);
  source.addEventListener('gene_analysis_update', update);
  source.onerror = () => {
    source.close();
    clearInterval(state.geneAnalysisTimers[nodeId]);
    delete state.geneAnalysisSources[nodeId];
    delete state.geneAnalysisTimers[nodeId];
    setTimeout(() => refreshGeneAnalysis(nodeId, { render: false }), 800);
  };
}

async function confirmHotProductGeneAnalysis(executionId) {
  const node = currentNode();
  const analysis = geneAnalysisFor(node?.id || '').analysis;
  if (!isHotProductGeneNode(node) || !analysis) return;
  try {
    const response = await collaborationRequest(`/api/nodes/${encodeURIComponent(node.id)}/gene-analysis/${encodeURIComponent(executionId)}/confirm`, {
      method: 'POST',
      body: { execution_id: executionId, source_revision: analysis.source_revision, confirmed_by: 'local_user' },
    });
    if (response.artifact?.schema_version !== 'hot-product-gene-analysis-confirmed-v1') {
      throw new Error('gene_analysis_confirmation_invalid');
    }
    state.geneAnalyses[node.id] = { analysis: response.analysis, confirmed_artifact: response.artifact };
    rememberNodeArtifact(node.id, response.artifact);
    state.nodeStatus[node.id] = 'done';
    state.flowNotice[node.id] = { status: 'done', message: '爆款基因已确认，可供后续机会分析使用。' };
    advanceToNextNode(node.id);
  } catch (error) {
    state.flowNotice[node.id] = { status: 'failed', message: `确认失败：${error.message}` };
  }
  render();
}

async function cancelHotProductGeneAnalysis(executionId) {
  const node = currentNode();
  if (!isHotProductGeneNode(node)) return;
  try {
    await collaborationRequest(`/api/nodes/${encodeURIComponent(node.id)}/gene-analysis/${encodeURIComponent(executionId)}/cancel`, { method: 'POST', body: {} });
    state.flowNotice[node.id] = { status: 'waiting', message: '正在停止爆款基因提炼。' };
  } catch (error) {
    state.flowNotice[node.id] = { status: 'failed', message: `停止失败：${error.message}` };
  }
  render();
}

async function retryHotProductGeneAnalysis(executionId) {
  const node = currentNode();
  if (!isHotProductGeneNode(node)) return;
  try {
    await collaborationRequest(`/api/nodes/${encodeURIComponent(node.id)}/gene-analysis/${encodeURIComponent(executionId)}/retry`, { method: 'POST', body: {} });
    state.nodeStatus[node.id] = 'running';
    state.flowNotice[node.id] = { status: 'waiting', message: '正在重试失败商品。' };
    setTimeout(() => refreshGeneAnalysis(node.id), 300);
  } catch (error) {
    state.flowNotice[node.id] = { status: 'failed', message: `重试失败：${error.message}` };
    render();
  }
}

async function refreshCollaborationWorkspaces(nodeId, options = {}) {
  const node = nodeById(nodeId);
  if (!node || !isDataAnalysisNode(node)) return;
  try {
    const [table, insight, thread] = await Promise.all([
      collaborationRequest(`/api/nodes/${encodeURIComponent(nodeId)}/data-table-workspace`),
      collaborationRequest(`/api/nodes/${encodeURIComponent(nodeId)}/insight-workspace`),
      collaborationRequest(`/api/nodes/${encodeURIComponent(nodeId)}/agent-thread`),
    ]);
    state.dataTableWorkspaces[nodeId] = table;
    state.insightWorkspaces[nodeId] = insight;
    state.agentThreads[nodeId] = thread;
    const latestBatch = (thread.thread?.agent_batches || thread.agent_batches || []).slice(-1)[0];
    if (latestBatch?.batch_id) {
      try {
        state.agentBatches[nodeId] = await collaborationRequest(`/api/nodes/${encodeURIComponent(nodeId)}/agent-thread/batches/${encodeURIComponent(latestBatch.batch_id)}`);
      } catch (error) {
        if (error.status !== 404) state.collaborationNotices[nodeId] = { status: 'failed', message: `批次状态加载失败：${error.message}` };
      }
    }
    const latestCall = latestAgentCall(nodeId);
    if (agentCallIsRunning(latestCall) && !state.agentCallSources[nodeId]) {
      state.piAgentBusy[nodeId] = true;
      observeAgentCall(nodeId, latestCall.call_id);
    }
    if (options.render !== false) render();
  } catch (error) {
    if (error.status !== 404) {
      state.collaborationNotices[nodeId] = { status: 'failed', message: `协作工作区加载失败：${error.message}` };
      if (options.render !== false) render();
    }
  }
}

async function refreshConfirmedUpstreamArtifacts(node) {
  const dependencies = Array.isArray(node?.depends_on) ? node.depends_on : [];
  await Promise.all(dependencies.map(async nodeId => {
    const sourceNode = nodeById(nodeId);
    if (!sourceNode || !isDataAnalysisNode(sourceNode)) return;
    try {
      const table = state.dataTableWorkspaces[nodeId]
        || await collaborationRequest(`/api/nodes/${encodeURIComponent(nodeId)}/data-table-workspace`);
      state.dataTableWorkspaces[nodeId] = table;
      if (table.confirmed_artifact) {
        rememberNodeArtifact(nodeId, table.confirmed_artifact);
        state.nodeStatus[nodeId] = 'done';
      }
    } catch (error) {
      if (error.status !== 404) state.collaborationNotices[nodeId] = { status: 'failed', message: `上游确认产物加载失败：${error.message}` };
    }
  }));
}

async function confirmDataTableAndAdvance() {
  const node = currentNode();
  const table = state.dataTableWorkspaces[node?.id || ''];
  if (!node || !table?.workspace) return;
  state.collaborationBusy[node.id] = true;
  state.collaborationNotices[node.id] = { status: 'saving', message: '正在固化当前表格并准备下一步...' };
  render();
  try {
    const response = await collaborationRequest(`/api/nodes/${encodeURIComponent(node.id)}/data-table-workspace/confirm`, {
      method: 'POST',
      body: { base_revision: table.workspace.revision, confirmed_by: 'local_user' },
    });
    state.dataTableWorkspaces[node.id] = response.table_workspace;
    rememberNodeArtifact(node.id, response.artifact);
    state.latestResult[node.id] = {
      schema_version: 'data-table-confirmation-v1',
      status: 'data_table_confirmed',
      data_table_ref: response.confirmation.artifact_ref,
      row_count: response.confirmation.row_count,
      workspace_revision: response.confirmation.workspace_revision,
    };
    state.nodeStatus[node.id] = 'done';
    state.collaborationNotices[node.id] = {
      status: 'done',
      message: response.confirmation.ignored_pending_proposals
        ? `已确认当前表格，并忽略 ${response.confirmation.ignored_pending_proposals} 条未采纳建议。`
        : '已确认当前表格。',
    };
    advanceToNextNode(node.id);
  } catch (error) {
    if (error.status === 409) await refreshCollaborationWorkspaces(node.id, { render: false });
    const messages = {
      agent_batch_running: '当前仍有批量填充任务运行，请等待结束或停止后再确认。',
      revision_conflict: '表格已变化，请检查最新内容后重新确认。',
      data_table_empty: '当前表格没有商品数据，不能进入下一步。',
    };
    state.collaborationNotices[node.id] = {
      status: 'failed',
      message: messages[error.message] || `确认表格失败：${error.message}`,
    };
  } finally {
    state.collaborationBusy[node.id] = false;
  }
  render();
}

async function startAgentBatch(pageNumber) {
  const node = currentNode();
  const table = state.dataTableWorkspaces[node?.id];
  if (!node || !table?.workspace) return;
  const nodeId = node.id;
  state.piAgentBusy[nodeId] = true;
  captureAgentInteractionState(nodeId);
  render();
  try {
    const response = await collaborationRequest(`/api/nodes/${encodeURIComponent(nodeId)}/agent-thread/batches`, {
      method: 'POST',
      body: { base_revision: table.workspace.revision, page_number: pageNumber, page_size: 10 },
    });
    state.agentBatches[nodeId] = response;
    updateAgentBatchInState(nodeId, response.batch);
    observeAgentBatch(nodeId, response.batch_id);
    state.collaborationNotices[nodeId] = { status: 'waiting', message: '已启动当前页批量填充，建议生成后进入复核。' };
  } catch (error) {
    state.piAgentBusy[nodeId] = false;
    state.collaborationNotices[nodeId] = { status: 'failed', message: `批次启动失败：${error.message}` };
  }
  render();
}

async function refreshAgentBatch(nodeId, batchId, options = {}) {
  try {
    const response = await collaborationRequest(`/api/nodes/${encodeURIComponent(nodeId)}/agent-thread/batches/${encodeURIComponent(batchId)}`);
    state.agentBatches[nodeId] = response;
    updateAgentBatchInState(nodeId, response.batch);
    if (!agentBatchIsRunning(response.batch)) state.piAgentBusy[nodeId] = false;
    if (options.render !== false) render();
    return response.batch;
  } catch (error) {
    state.collaborationNotices[nodeId] = { status: 'failed', message: `批次状态刷新失败：${error.message}` };
    if (options.render !== false) render();
    return null;
  }
}

function observeAgentBatch(nodeId, batchId) {
  if (state.agentBatchSources[nodeId]) state.agentBatchSources[nodeId].close();
  if (state.agentBatchTimers[nodeId]) clearInterval(state.agentBatchTimers[nodeId]);
  const source = new EventSource(`/api/nodes/${encodeURIComponent(nodeId)}/agent-thread/batches/${encodeURIComponent(batchId)}/events`);
  state.agentBatchSources[nodeId] = source;
  state.agentBatchTimers[nodeId] = setInterval(() => {
    const batch = state.agentBatches[nodeId]?.batch;
    if (state.selectedNodeId === nodeId && agentBatchIsRunning(batch)) patchAgentExecutionMonitor(nodeId);
  }, 1000);
  const handleUpdate = async event => {
    const data = JSON.parse(event.data || '{}');
    if (!data.batch || data.batch.batch_id !== batchId) return;
    updateAgentBatchInState(nodeId, data.batch);
    patchAgentExecutionMonitor(nodeId, { elapsedOnly: false });
    if (!agentBatchIsRunning(data.batch)) {
      source.close();
      delete state.agentBatchSources[nodeId];
      clearInterval(state.agentBatchTimers[nodeId]);
      delete state.agentBatchTimers[nodeId];
      state.piAgentBusy[nodeId] = false;
      await refreshCollaborationWorkspaces(nodeId, { render: false });
      const saved = captureAgentInteractionState(nodeId);
      if (saved.nearBottom) render();
      else {
        render();
        const button = document.querySelector('[data-agent-new-results]');
        if (button) button.hidden = false;
      }
    }
  };
  source.addEventListener('batch_snapshot', handleUpdate);
  source.addEventListener('agent_batch_update', handleUpdate);
  source.onerror = () => {
    source.close();
    delete state.agentBatchSources[nodeId];
    clearInterval(state.agentBatchTimers[nodeId]);
    delete state.agentBatchTimers[nodeId];
    setTimeout(async () => {
      const batch = await refreshAgentBatch(nodeId, batchId, { render: false });
      if (agentBatchIsRunning(batch)) observeAgentBatch(nodeId, batchId);
    }, 800);
  };
}

async function cancelAgentBatch(batchId) {
  const node = currentNode();
  if (!node) return;
  try {
    await collaborationRequest(`/api/nodes/${encodeURIComponent(node.id)}/agent-thread/batches/${encodeURIComponent(batchId)}/cancel`, { method: 'POST', body: {} });
    await refreshAgentBatch(node.id, batchId, { render: false });
    state.collaborationNotices[node.id] = { status: 'waiting', message: '批次已停止。' };
  } catch (error) {
    state.collaborationNotices[node.id] = { status: 'failed', message: `停止批次失败：${error.message}` };
  }
  render();
}

async function applyAgentBatchProposals(batchId) {
  const node = currentNode();
  const review = state.agentBatchReview[node?.id || ''] || {};
  const table = state.dataTableWorkspaces[node?.id || ''];
  if (!node || !table?.workspace || !(review.proposalIds || []).length) return;
  try {
    const response = await collaborationRequest(`/api/nodes/${encodeURIComponent(node.id)}/agent-thread/batches/${encodeURIComponent(batchId)}/apply`, {
      method: 'POST',
      body: { base_revision: table.workspace.revision, proposal_ids: review.proposalIds },
    });
    state.dataTableWorkspaces[node.id] = response.table_workspace;
    state.agentBatches[node.id] = response;
    delete state.agentBatchReview[node.id];
    state.collaborationNotices[node.id] = { status: 'done', message: '已应用所选批量建议。' };
    await refreshCollaborationWorkspaces(node.id, { render: false });
  } catch (error) {
    if (error.status === 409) await refreshCollaborationWorkspaces(node.id, { render: false });
    state.collaborationNotices[node.id] = { status: 'failed', message: error.status === 409 ? '数据已变化，批量建议已过期，请重新运行。' : `批量建议应用失败：${error.message}` };
  }
  render();
}

function tableCellDescriptor(nodeId, rowId, fieldPath) {
  const payload = state.dataTableWorkspaces[nodeId] || {};
  const workspace = payload.workspace || {};
  const index = (workspace.row_meta || []).findIndex(item => item.row_id === rowId);
  const value = index >= 0 ? payload.effective_rows?.[index]?.[fieldPath] ?? '' : '';
  const row = index >= 0 ? payload.effective_rows?.[index] || {} : {};
  const rowMeta = index >= 0 ? workspace.row_meta?.[index] || {} : {};
  const override = cellOverrideFor(workspace, rowId, fieldPath);
  const productName = ['商品名', '商品名称', 'goods_name', 'product_name', 'item_name'].map(key => row[key]).find(item => String(item ?? '').trim()) || '';
  const productId = ['goods_id', 'commodity_id', 'item_id', 'product_id'].map(key => row[key]).find(item => String(item ?? '').trim()) || rowMeta.source_identity || '';
  return {
    row_id: rowId,
    field_path: fieldPath,
    effective_value: value,
    source_kind: override?.source_kind || (String(value).trim() ? 'api' : 'missing'),
    original_value: override?.original_value ?? value,
    evidence_refs: override?.evidence_refs || [],
    product_name: String(productName || ''),
    product_id: String(productId || ''),
  };
}

function selectTableCell(cell, event = {}) {
  const node = currentNode();
  if (!node) return;
  const rowId = cell.getAttribute('data-row-id') || '';
  const fieldPath = cell.getAttribute('data-field-path') || '';
  const descriptor = tableCellDescriptor(node.id, rowId, fieldPath);
  let cells = [];
  if (event.shiftKey && state.tableSelections[node.id]?.anchor) {
    const anchor = state.tableSelections[node.id].anchor;
    const allCells = Array.from(document.querySelectorAll('[data-table-cell]'));
    const rowIds = Array.from(new Set(allCells.map(item => item.getAttribute('data-row-id') || '')));
    const fieldPaths = Array.from(new Set(allCells.map(item => item.getAttribute('data-field-path') || '')));
    const rowStart = rowIds.indexOf(anchor.row_id);
    const rowEnd = rowIds.indexOf(rowId);
    const fieldStart = fieldPaths.indexOf(anchor.field_path);
    const fieldEnd = fieldPaths.indexOf(fieldPath);
    const selectedRows = rowIds.slice(Math.min(rowStart, rowEnd), Math.max(rowStart, rowEnd) + 1);
    const selectedFields = fieldPaths.slice(Math.min(fieldStart, fieldEnd), Math.max(fieldStart, fieldEnd) + 1);
    cells = selectedRows.flatMap(selectedRow => selectedFields.map(selectedField => tableCellDescriptor(node.id, selectedRow, selectedField)));
  } else if (event.metaKey || event.ctrlKey) {
    const existing = state.tableSelections[node.id]?.cells || [];
    const key = tableCellKey(rowId, fieldPath);
    cells = existing.some(item => tableCellKey(item.row_id, item.field_path) === key)
      ? existing.filter(item => tableCellKey(item.row_id, item.field_path) !== key)
      : [...existing, descriptor];
  } else {
    cells = [descriptor];
  }
  state.tableSelections[node.id] = { scope_mode: 'cells', cells, anchor: { row_id: rowId, field_path: fieldPath } };
  render();
}

function selectTableColumn(fieldPath) {
  const node = currentNode();
  const payload = node && state.dataTableWorkspaces[node.id];
  if (!node || !payload) return;
  state.tableSelections[node.id] = {
    scope_mode: 'column',
    field_paths: [fieldPath],
    cells: (payload.workspace?.row_meta || []).slice(0, 100).map(meta => tableCellDescriptor(node.id, meta.row_id, fieldPath)),
  };
  render();
}

function selectTableRow(rowId) {
  const node = currentNode();
  const payload = node && state.dataTableWorkspaces[node.id];
  if (!node || !payload) return;
  const fields = (payload.effective_fields || []).map(collaborationFieldPath);
  state.tableSelections[node.id] = {
    scope_mode: 'row',
    row_ids: [rowId],
    cells: fields.map(fieldPath => tableCellDescriptor(node.id, rowId, fieldPath)),
  };
  render();
}

function selectWholeTable() {
  const node = currentNode();
  const payload = node && state.dataTableWorkspaces[node.id];
  if (!node || !payload) return;
  const rowIds = (payload.workspace?.row_meta || []).map(item => item.row_id);
  const fieldPaths = (payload.effective_fields || []).map(collaborationFieldPath);
  state.tableSelections[node.id] = {
    scope_mode: 'whole_table',
    row_ids: rowIds,
    field_paths: fieldPaths,
    cells: rowIds.slice(0, 100).flatMap(rowId => fieldPaths.map(fieldPath => tableCellDescriptor(node.id, rowId, fieldPath))),
    truncated: rowIds.length * fieldPaths.length > 100,
  };
  render();
}

function beginTableCellEdit(cell) {
  const node = currentNode();
  if (!node) return;
  state.tableEditing[node.id] = tableCellKey(cell.getAttribute('data-row-id') || '', cell.getAttribute('data-field-path') || '');
  render();
  requestAnimationFrame(() => {
    const editor = document.querySelector('[data-table-cell-editor]');
    if (editor) {
      editor.focus();
      if (editor.select) editor.select();
    }
  });
}

async function patchDataTableWorkspace(operations, options = {}) {
  const node = currentNode();
  const payload = node && state.dataTableWorkspaces[node.id];
  if (!node || !payload?.workspace || !operations.length) return;
  state.collaborationBusy[node.id] = true;
  try {
    const updated = await collaborationRequest(`/api/nodes/${encodeURIComponent(node.id)}/data-table-workspace/patch`, {
      method: 'POST',
      body: {
        schema_version: 'data-table-edit-patch-v1',
        base_revision: payload.workspace.revision,
        operations,
        proposal_id: options.proposalId || '',
        proposal_patch_indices: options.proposalPatchIndices || [],
      },
    });
    state.dataTableWorkspaces[node.id] = updated;
    state.collaborationNotices[node.id] = { status: 'done', message: options.message || '表格草稿已保存。' };
    await refreshCollaborationWorkspaces(node.id, { render: false });
  } catch (error) {
    if (error.status === 409) await refreshCollaborationWorkspaces(node.id, { render: false });
    state.collaborationNotices[node.id] = { status: 'failed', message: error.status === 409 ? '数据已变化，已刷新到最新版本，请重新操作。' : `保存失败：${error.message}` };
  } finally {
    state.collaborationBusy[node.id] = false;
    render();
  }
}

async function commitTableCellEditor(cell) {
  const node = currentNode();
  if (!node || !cell) return;
  const editor = cell.querySelector('[data-table-cell-editor]');
  const rowId = cell.getAttribute('data-row-id') || '';
  const fieldPath = cell.getAttribute('data-field-path') || '';
  const current = tableCellDescriptor(node.id, rowId, fieldPath).effective_value;
  const next = editor?.value ?? current;
  delete state.tableEditing[node.id];
  if (String(next) === String(current)) {
    render();
    return;
  }
  await patchDataTableWorkspace([{ operation: next === '' ? 'clear_cell' : 'set_cell', row_id: rowId, field_path: fieldPath, expected_value: current, new_value: next, source_kind: 'manual', reason: '用户在中间表格编辑' }]);
}

async function restoreTableCellSource(button) {
  const cell = button.closest('[data-table-cell]');
  const node = currentNode();
  if (!cell || !node) return;
  const rowId = cell.getAttribute('data-row-id') || '';
  const fieldPath = cell.getAttribute('data-field-path') || '';
  const current = tableCellDescriptor(node.id, rowId, fieldPath).effective_value;
  await patchDataTableWorkspace([{ operation: 'restore_source', row_id: rowId, field_path: fieldPath, expected_value: current }], { message: '已恢复 API 原值。' });
}

async function pasteTableRegion(event, container) {
  const node = currentNode();
  const payload = node && state.dataTableWorkspaces[node.id];
  const selection = node && dataTableSelectionFor(node.id);
  const anchor = selection?.anchor || selection?.cells?.[0];
  if (!node || !payload || !anchor) return;
  const text = event.clipboardData?.getData('text/plain') || '';
  if (!text.includes('\t') && !text.includes('\n')) return;
  event.preventDefault();
  const grid = text.replace(/\r/g, '').split('\n').filter((line, index, list) => line || index < list.length - 1).map(line => line.split('\t'));
  const rowIds = (payload.workspace?.row_meta || []).map(item => item.row_id);
  const fieldPaths = (payload.effective_fields || []).map(collaborationFieldPath);
  const rowStart = rowIds.indexOf(anchor.row_id);
  const fieldStart = fieldPaths.indexOf(anchor.field_path);
  const operations = [];
  grid.forEach((values, rowOffset) => values.forEach((value, fieldOffset) => {
    const rowId = rowIds[rowStart + rowOffset];
    const fieldPath = fieldPaths[fieldStart + fieldOffset];
    if (!rowId || !fieldPath) return;
    const current = tableCellDescriptor(node.id, rowId, fieldPath).effective_value;
    operations.push({ operation: value === '' ? 'clear_cell' : 'set_cell', row_id: rowId, field_path: fieldPath, expected_value: current, new_value: value, source_kind: 'manual', reason: '用户批量粘贴' });
  }));
  await patchDataTableWorkspace(operations, { message: `已批量更新 ${operations.length} 个单元格。` });
}

async function undoDataTableWorkspace() {
  const node = currentNode();
  const payload = node && state.dataTableWorkspaces[node.id];
  if (!node || !payload?.workspace) return;
  try {
    state.dataTableWorkspaces[node.id] = await collaborationRequest(`/api/nodes/${encodeURIComponent(node.id)}/data-table-workspace/undo`, { method: 'POST', body: { base_revision: payload.workspace.revision } });
    await refreshCollaborationWorkspaces(node.id, { render: false });
    state.collaborationNotices[node.id] = { status: 'done', message: '已撤销最近一次表格修改。' };
  } catch (error) {
    state.collaborationNotices[node.id] = { status: 'failed', message: `撤销失败：${error.message}` };
  }
  render();
}

async function addExtensionField() {
  const title = window.prompt('扩展字段名称');
  if (!String(title || '').trim()) return;
  const type = window.prompt('字段类型：string / number / url / image / single_select', 'string') || 'string';
  await patchDataTableWorkspace([{ operation: 'add_extension_field', field_path: String(title).trim(), title: String(title).trim(), field_type: String(type).trim(), options: [] }], { message: `已添加扩展字段「${String(title).trim()}」。` });
}

async function editExtensionField(fieldPath) {
  const node = currentNode();
  const payload = node && state.dataTableWorkspaces[node.id];
  const field = payload?.workspace?.extension_fields?.find(item => collaborationFieldPath(item) === fieldPath);
  if (!field) return;
  const title = window.prompt('扩展字段显示名称', field.title || fieldPath);
  if (!String(title || '').trim()) return;
  const type = window.prompt('字段类型：string / number / url / image / single_select', field.type || 'string') || field.type || 'string';
  await patchDataTableWorkspace([{ operation: 'update_extension_field', field_path: fieldPath, title: String(title).trim(), field_type: String(type).trim(), options: field.options || [] }], { message: `已更新扩展字段「${fieldPath}」。` });
}

async function deleteExtensionField(fieldPath) {
  if (!window.confirm(`删除扩展字段「${fieldPath}」及其全部草稿值？`)) return;
  await patchDataTableWorkspace([{ operation: 'delete_extension_field', field_path: fieldPath }], { message: `已删除扩展字段「${fieldPath}」。` });
}

async function updateThreadPreferredModel(model) {
  const node = currentNode();
  if (!node || !model) return false;
  try {
    const response = await collaborationRequest(`/api/nodes/${encodeURIComponent(node.id)}/agent-thread/model`, {
      method: 'POST',
      body: { preferred_model: model, updated_by: 'user' },
    });
    state.agentThreads[node.id] = response;
    state.piSelectedModel = '';
    state.collaborationNotices[node.id] = { status: 'done', message: `首选模型已更新为 ${model}。` };
    render();
    return true;
  } catch (error) {
    state.collaborationNotices[node.id] = { status: 'failed', message: `模型更新失败：${error.message}` };
    render();
    return false;
  }
}

function updateAgentCallInState(nodeId, call) {
  if (!call) return;
  const payload = state.agentThreads[nodeId] || { ok: true, thread: agentThreadFor(nodeId) };
  const thread = payload.thread || { schema_version: 'analysis-collaboration-thread-v1', messages: [], agent_calls: [] };
  const calls = Array.isArray(thread.agent_calls) ? [...thread.agent_calls] : [];
  const index = calls.findIndex(item => item.call_id === call.call_id);
  if (index >= 0) calls[index] = call;
  else calls.push(call);
  state.agentThreads[nodeId] = { ...payload, thread: { ...thread, agent_calls: calls } };
}

async function refreshAgentCall(nodeId, callId) {
  try {
    const response = await collaborationRequest(`/api/nodes/${encodeURIComponent(nodeId)}/agent-thread/calls/${encodeURIComponent(callId)}`);
    updateAgentCallInState(nodeId, response.call);
    if (!agentCallIsRunning(response.call)) {
      state.piAgentBusy[nodeId] = false;
      await refreshCollaborationWorkspaces(nodeId, { render: false });
    }
    render();
    return response.call;
  } catch (error) {
    state.collaborationNotices[nodeId] = { status: 'failed', message: `调用状态刷新失败：${error.message}` };
    state.piAgentBusy[nodeId] = false;
    render();
    return null;
  }
}

function observeAgentCall(nodeId, callId) {
  if (state.agentCallSources[nodeId]) state.agentCallSources[nodeId].close();
  if (state.agentCallTimers[nodeId]) clearInterval(state.agentCallTimers[nodeId]);
  const source = new EventSource(`/api/nodes/${encodeURIComponent(nodeId)}/agent-thread/calls/${encodeURIComponent(callId)}/events`);
  state.agentCallSources[nodeId] = source;
  state.agentCallTimers[nodeId] = setInterval(() => {
    if (state.selectedNodeId === nodeId && state.piAgentBusy[nodeId]) patchAgentExecutionMonitor(nodeId);
  }, 1000);
  const handleUpdate = async event => {
    const data = JSON.parse(event.data || '{}');
    if (!data.call || data.call.call_id !== callId) return;
    updateAgentCallInState(nodeId, data.call);
    const terminal = !agentCallIsRunning(data.call);
    if (terminal) {
      source.close();
      delete state.agentCallSources[nodeId];
      clearInterval(state.agentCallTimers[nodeId]);
      delete state.agentCallTimers[nodeId];
      state.piAgentBusy[nodeId] = false;
      await refreshCollaborationWorkspaces(nodeId, { render: false });
    }
    patchAgentExecutionMonitor(nodeId, { elapsedOnly: false });
    const saved = captureAgentInteractionState(nodeId);
    if (terminal) {
      render();
      if (!saved.nearBottom) {
        const button = document.querySelector('[data-agent-new-results]');
        if (button) button.hidden = false;
      }
    }
  };
  source.addEventListener('call_snapshot', handleUpdate);
  source.addEventListener('agent_call_update', handleUpdate);
  source.onerror = () => {
    source.close();
    delete state.agentCallSources[nodeId];
    clearInterval(state.agentCallTimers[nodeId]);
    delete state.agentCallTimers[nodeId];
    setTimeout(async () => {
      const call = await refreshAgentCall(nodeId, callId);
      if (agentCallIsRunning(call)) observeAgentCall(nodeId, callId);
    }, 800);
  };
}

async function retryAgentCall(callId, options = {}) {
  const node = currentNode();
  const call = (agentThreadFor(node?.id).agent_calls || []).find(item => item.call_id === callId);
  if (!node || !call) return;
  if (options.switchModel) {
    const available = (state.piAgentStatus?.model_options || [])
      .filter(item => item.model && item.model !== selectedPiModel());
    const alternative = available.find(item => item.configured) || available[0];
    if (!alternative) {
      state.collaborationNotices[node.id] = { status: 'failed', message: '没有可切换的其它模型。' };
      render();
      return;
    }
    if (!await updateThreadPreferredModel(alternative.model)) return;
  }
  const snapshot = call.context_snapshot || {};
  if (snapshot.row_id && snapshot.target_field) {
    state.agentThreads[node.id] = await collaborationRequest(`/api/nodes/${encodeURIComponent(node.id)}/agent-thread/context`, {
      method: 'POST',
      body: { context_type: 'cell_context', row_id: snapshot.row_id, field_path: snapshot.target_field },
    });
  }
  await sendUnifiedAgentMessage({
    message: snapshot.user_message || '请重新处理上一次请求。',
    requirementId: snapshot.requirement_id || '',
    parentCallId: callId,
  });
}

async function stopAgentCall(callId) {
  const node = currentNode();
  if (!node || !callId) return;
  try {
    await collaborationRequest(`/api/nodes/${encodeURIComponent(node.id)}/agent-thread/calls/${encodeURIComponent(callId)}/cancel`, { method: 'POST', body: {} });
    state.collaborationNotices[node.id] = { status: 'waiting', message: '正在停止本次 Agent 调用。' };
  } catch (error) {
    state.collaborationNotices[node.id] = { status: 'failed', message: `停止失败：${error.message}` };
  }
  render();
}

async function addSelectedCellToAgent() {
  const node = currentNode();
  const selection = dataTableSelectionFor(node.id);
  const cell = selection.scope_mode === 'cells' && selection.cells?.length === 1 ? selection.cells[0] : null;
  if (!node || !cell) return;
  try {
    state.agentThreads[node.id] = await collaborationRequest(`/api/nodes/${encodeURIComponent(node.id)}/agent-thread/context`, {
      method: 'POST',
      body: {
        context_type: 'cell_context',
        row_id: cell.row_id,
        field_path: cell.field_path,
      },
    });
    state.collaborationNotices[node.id] = { status: 'done', message: '已加入 Agent 对话，可在右侧补充问题后发送。' };
    render();
    requestAnimationFrame(() => document.querySelector('[data-agent-thread-input]')?.focus());
  } catch (error) {
    state.collaborationNotices[node.id] = { status: 'failed', message: `加入对话失败：${error.message}` };
    render();
  }
}

async function sendUnifiedAgentMessage(options = {}) {
  const node = currentNode();
  const input = document.querySelector('[data-agent-thread-input]');
  const message = String(options.message ?? input?.value ?? '').trim();
  if (!node || !message) return;
  captureAgentInteractionState(node.id);
  state.agentScrollState[node.id] = { ...(state.agentScrollState[node.id] || {}), nearBottom: true, forceBottom: true };
  state.piAgentBusy[node.id] = true;
  render();
  try {
    state.agentThreads[node.id] = await collaborationRequest(`/api/nodes/${encodeURIComponent(node.id)}/agent-thread/query`, {
      method: 'POST',
      body: {
        async: true,
        message,
        requirement_id: String(options.requirementId || ''),
        parent_call_id: String(options.parentCallId || ''),
        upstream_artifacts: upstreamArtifactsFor(node),
      },
    });
    if (input) input.value = '';
    state.agentScrollState[node.id] = { ...(state.agentScrollState[node.id] || {}), inputValue: '', inputFocused: false, nearBottom: true };
    const callId = state.agentThreads[node.id].call_id;
    if (callId) observeAgentCall(node.id, callId);
    render();
  } catch (error) {
    state.collaborationNotices[node.id] = { status: 'failed', message: `Agent 请求失败：${error.message}` };
    state.piAgentBusy[node.id] = false;
    render();
  }
}

async function actOnAgentThread(action, messageId, options = {}) {
  const node = currentNode();
  if (!node) return;
  try {
    const response = await collaborationRequest(`/api/nodes/${encodeURIComponent(node.id)}/agent-thread/action`, {
      method: 'POST',
      body: {
        action,
        message_id: messageId,
        patch_indices: options.patchIndices || [],
        requirement_id: options.requirementId || '',
        draft_text: options.draftText,
        evidence_bindings: options.evidenceBindings,
      },
    });
    state.agentThreads[node.id] = { ok: true, thread: response.thread };
    if (response.table_workspace) state.dataTableWorkspaces[node.id] = response.table_workspace;
    if (response.insight_workspace) state.insightWorkspaces[node.id] = response.insight_workspace;
    state.collaborationNotices[node.id] = { status: 'done', message: action === 'apply_cell_proposal' ? 'Agent 建议已回填到表格草稿。' : action === 'save_insight_draft' ? '分析结论草稿已保存。' : action === 'confirm_insight' ? '分析结论已确认。' : '建议已处理。' };
  } catch (error) {
    if (error.status === 409) await refreshCollaborationWorkspaces(node.id, { render: false });
    state.collaborationNotices[node.id] = { status: 'failed', message: error.status === 409 ? '数据已变化，旧建议不能直接应用，请重新分析。' : `操作失败：${error.message}` };
  }
  render();
}

function evidenceBindingsFromAgentMessage(messageId) {
  return Array.from(document.querySelectorAll(`[data-agent-insight-evidence="${CSS.escape(messageId)}"]:checked`))
    .map(input => ({ kind: 'field', field_path: input.value }));
}

function applyLayoutStyle(layout) {
  if (!layout) return;
  const widths = state.layoutWidths || { left: 260, right: 360 };
  layout.style.setProperty('--left-panel-width', `${clampPanelWidth(Number(widths.left) || 260, 200, 520)}px`);
  layout.style.setProperty('--right-panel-width', `${clampPanelWidth(Number(widths.right) || 360, 280, 620)}px`);
}

function resizeLayoutPanel(side, deltaX, startWidths, layoutWidth) {
  const minCenter = 420;
  const leftMin = 200;
  const rightMin = 280;
  const chromeWidth = 64;
  const maxLeft = Math.max(leftMin, layoutWidth - startWidths.right - minCenter - chromeWidth);
  const maxRight = Math.max(rightMin, layoutWidth - startWidths.left - minCenter - chromeWidth);
  if (side === 'left') {
    state.layoutWidths.left = clampPanelWidth(startWidths.left + deltaX, leftMin, Math.min(520, maxLeft));
    return;
  }
  state.layoutWidths.right = clampPanelWidth(startWidths.right - deltaX, rightMin, Math.min(620, maxRight));
}

function bindLayoutResizers() {
  const layout = document.querySelector('[data-layout]');
  if (!layout) return;
  applyLayoutStyle(layout);
  document.querySelectorAll('[data-layout-resizer]').forEach(resizer => {
    resizer.addEventListener('pointerdown', event => {
      event.preventDefault();
      const side = resizer.getAttribute('data-layout-resizer') || 'left';
      const startX = event.clientX;
      const startWidths = { ...(state.layoutWidths || { left: 260, right: 360 }) };
      const layoutWidth = layout.getBoundingClientRect().width;
      resizer.classList.add('active');
      const onMove = moveEvent => {
        resizeLayoutPanel(side, moveEvent.clientX - startX, startWidths, layoutWidth);
        applyLayoutStyle(layout);
      };
      const onUp = () => {
        resizer.classList.remove('active');
        saveLayoutState();
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('pointerup', onUp);
      };
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', onUp, { once: true });
    });
    resizer.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault();
      const side = resizer.getAttribute('data-layout-resizer') || 'left';
      const direction = event.key === 'ArrowRight' ? 1 : -1;
      const startWidths = { ...(state.layoutWidths || { left: 260, right: 360 }) };
      const delta = side === 'right' ? -direction * 24 : direction * 24;
      resizeLayoutPanel(side, delta, startWidths, layout.getBoundingClientRect().width);
      applyLayoutStyle(layout);
      saveLayoutState();
    });
  });
}

// 单字段快捷操作：apply=采纳 PI 建议来源；manual=标记人工补充；ignore=清空 PI 建议来源。
function applyAdviceAction(action, fieldPath) {
  const node = currentNode();
  if (!node || !fieldPath) return;
  const adviceIndex = fieldAdviceIndexForNode(node);
  const advice = adviceIndex.get(fieldPath);
  if (action === 'apply' && advice) {
    upsertFieldDraft(node, fieldPath, {
      source_api_id: advice.suggested_source_api_id,
      source_field_path: advice.suggested_source_field_path,
      api_field_path: advice.suggested_source_field_path,
      source_role: 'api_field',
      source_kind: 'api_doc_index',
      mapping_status: 'suggested',
      confidence: advice.confidence,
      human_confirmed: false,
      human_note: `PI 建议（${advice.confidence}）`,
    });
  } else if (action === 'manual') {
    upsertFieldDraft(node, fieldPath, { mapping_status: 'manual_fill', source_kind: 'manual', human_note: '人工补充', human_confirmed: false });
  } else if (action === 'ignore') {
    upsertFieldDraft(node, fieldPath, { mapping_status: 'unmapped', source_api_id: '', source_field_path: '', api_field_path: '', source_role: '', source_kind: '', confidence: '', human_note: '' });
  }
  saveWorkbenchState();
  render();
}

async function handleSaveNodeDraft() {
  const node = currentNode();
  if (!node) return;
  const draft = collectCurrentDraft();
  const artifact = buildNodeDraftArtifact(node, draft);
  rememberNodeArtifact(node.id, artifact);
  state.saveStatus[node.id] = { status: 'saving', message: `正在生成${artifact.title}...` };
  saveNodeDrafts();
  render();

  try {
    const response = await fetch(`/api/nodes/${encodeURIComponent(node.id)}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ inputs: draft, artifact }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || payload.message || `save failed: ${response.status}`);
    }
    const result = payload.result || payload;
    state.nodeStatus[node.id] = 'done';
    state.latestResult[node.id] = result;
    const savedArtifact = artifactFromRunResult(node.id, result) || artifact;
    rememberNodeArtifact(node.id, savedArtifact);
    const persistedPath = result.artifact_path || payload.artifact_path || '';
    state.saveStatus[node.id] = {
      status: 'done',
      message: persistedPath
        ? `已生成${artifact.title}，并写入 ${persistedPath}。`
        : `已生成${artifact.title}；当前服务端已保存字段，重启 preview 后会写入结构化产物表。`,
    };
  } catch (error) {
    state.saveStatus[node.id] = {
      status: 'failed',
      message: `已在页面生成${artifact.title}；服务端写入失败：${error.message || error}`,
    };
  }
  render();
}

function collectCurrentDraft() {
  const node = currentNode();
  if (!node) return {};
  const values = { ...(state.nodeDrafts[node.id] || {}) };
  document.querySelectorAll('[data-node-field]').forEach(input => {
    const key = input.getAttribute('data-node-field') || '';
    if (key) values[key] = input.value || '';
  });
  state.nodeDrafts[node.id] = values;
  return values;
}

function buildNodeRunPayload(node, draft) {
  const payload = { inputs: draft };
  if (isDataAnalysisNode(node)) payload.top_n = selectedDataAnalysisTopN(node.id);
  const fields = nodeActionFields(node);
  if (fields.length > 0) {
    const artifact = buildNodeDraftArtifact(node, draft);
    payload.artifact = artifact;
    rememberNodeArtifact(node.id, artifact);
  }
  const upstream = upstreamArtifactsFor(node).map(item => ({
    source_node_id: item.source_node_id,
    source_node_name: item.source_node_name,
    ...item.artifact,
  }));
  if (upstream.length > 0) {
    payload.upstream_artifacts = upstream;
  }
  if (isDataMappingNode(node)) {
    payload.field_coverage_plan = currentFieldMappingOverlay(node);
    const contract = contractFromDbAgentResult(dbAgentResultFor(node));
    if (contract) payload.data_mapping_contract = contract;
  }
  return payload;
}

function selectedDataAnalysisTopN(nodeId) {
  const value = Number(state.dataAnalysisTopN[nodeId]);
  return [10, 20, 30, 50].includes(value) ? value : 20;
}

function isCompletedResult(result) {
  const status = String(result?.status || '');
  if (['waiting_upload', 'missing_required_fields', 'partial_data_table_ready', 'agent_enrichment_pending', 'empty_data', 'failed', 'error', 'blocked', 'degraded'].includes(status)) return false;
  if (Array.isArray(result?.missing_required) && result.missing_required.length > 0) return false;
  return true;
}

function completeNodeRun(nodeId, result, options = {}) {
  state.latestResult[nodeId] = result;
  const artifact = artifactFromRunResult(nodeId, result);
  if (artifact) rememberNodeArtifact(nodeId, artifact);
  state.nodeStatus[nodeId] = isCompletedResult(result) ? 'done' : 'waiting';
  if (result?.data_table_ref) refreshCollaborationWorkspaces(nodeId);
  if (options.autoAdvance && isCompletedResult(result)) {
    advanceToNextNode(nodeId);
  }
  render();
}

function advanceToNextNode(nodeId) {
  const nodes = state.config?.nodes || [];
  const index = nodes.findIndex(node => node.id === nodeId);
  const next = index >= 0 ? nodes[index + 1] : null;
  if (!next) return;
  const upstream = upstreamArtifactsFor(next);
  state.selectedNodeId = next.id;
  if (upstream.length > 0) {
    state.flowNotice[next.id] = {
      status: 'done',
      message: `已进入下一步，并接收上游输入：${upstream.map(item => item.artifact.title || item.source_node_name).join('、')}。`,
    };
  } else {
    state.flowNotice[next.id] = {
      status: 'done',
      message: '已进入下一步；等待上游产物或补充输入。',
    };
  }
}

async function runCurrentNode() {
  const node = currentNode();
  if (!node) return;
  const draft = collectCurrentDraft();
  const payload = buildNodeRunPayload(node, draft);
  saveNodeDrafts();
  
  // SSE will update status automatically, but we can set initial state
  state.pendingAutoAdvanceNodeId = isHotProductGeneNode(node) ? '' : node.id;
  state.nodeStatus[node.id] = 'running';
  render();
  
  try {
    const response = await fetch(`/api/nodes/${encodeURIComponent(node.id)}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const responsePayload = await response.json();
    if (!response.ok) {
      throw new Error(responsePayload.error || responsePayload.message || `run failed: ${response.status}`);
    }
    if (isHotProductGeneNode(node) && responsePayload.status === 'running') {
      state.latestResult[node.id] = responsePayload;
      state.geneAnalyses[node.id] = {
        analysis: {
          schema_version: 'hot-product-gene-analysis-v1',
          execution_id: responsePayload.execution_id,
          status: 'running',
          requested_model: 'aicodemirror/gpt-5.6-sol',
          progress: { total_products: 0, completed_products: 0, running_products: 0, failed_products: 0 },
          product_profiles: [], dimension_findings: [], gene_groups: [], risks: [],
          created_at: new Date().toISOString(),
        },
        confirmed_artifact: null,
      };
      observeGeneAnalysis(node.id, responsePayload.execution_id);
      render();
      return;
    }
    if (state.nodeStatus[node.id] === 'running' || !state.latestResult[node.id]) {
      completeNodeRun(node.id, responsePayload.result || responsePayload, { autoAdvance: state.pendingAutoAdvanceNodeId === node.id });
    }
    if (state.pendingAutoAdvanceNodeId === node.id) state.pendingAutoAdvanceNodeId = '';
  } catch (error) {
    state.pendingAutoAdvanceNodeId = '';
    state.nodeStatus[node.id] = 'failed';
    state.latestResult[node.id] = { error: String(error.message || error) };
    render();
  }
}

async function exportReport() {
  const response = await fetch('/api/export/final_report', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ narrative: '人工判断：当前报告已完成结构化汇总。', rule_outputs: Object.values(state.latestResult).map(item => item.result).filter(Boolean) }),
  });
  const payload = await response.json();
  alert(response.ok ? '报告已导出。' : `导出失败：${payload.error || response.status}`);
}

async function init() {
  try {
    state.config = await fetchConfig();
    state.selectedNodeId = state.config.nodes?.[0]?.id || '';
    loadNodeDrafts();
    loadNodeArtifacts();
    loadDbAgentResults();
    loadWorkbenchState();
    loadLayoutState();
    await fetchDbAgentStatus();
    await fetchPiAgentStatus();
    await refreshCollaborationWorkspaces(state.selectedNodeId, { render: false });
    await refreshGeneAnalysis(state.selectedNodeId, { render: false });
    connectEventStream();
    render();
  } catch (error) {
    document.getElementById('app').innerHTML = `<div class="error">加载失败：${escapeHtml(error.message || error)}</div>`;
  }
}

window.reportGeneratorApp = {
  state,
  renderNodeList,
  renderNodeDetail,
  renderMarkdown,
  buildNodeDraftArtifact,
  renderDraftArtifactTable,
  buildNodeRunPayload,
  completeNodeRun,
  upstreamArtifactsFor,
};
init();
