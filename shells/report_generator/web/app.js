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
    const shouldAdvance = state.pendingAutoAdvanceNodeId === data.node_id;
    completeNodeRun(data.node_id, data.result, { autoAdvance: shouldAdvance });
    if (shouldAdvance) state.pendingAutoAdvanceNodeId = '';
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
  } catch {
    state.fieldMappingDrafts = {};
    state.piAgentResults = {};
  }
}

function saveWorkbenchState() {
  localStorage.setItem(workbenchStorageKey(), JSON.stringify({
    fieldMappingDrafts: state.fieldMappingDrafts || {},
    piAgentResults: state.piAgentResults || {},
  }));
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
  return fields.length > 0 && (requiredData.length > 0 || requirementIds.length > 0 || node.kind === 'data');
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
  if (!advice) return `${renderPiAgentStatus()}<p class="muted">尚未生成 PI 建议。点击「智能匹配字段（PI 增强）」在下方表格内联查看逐字段判断。</p>`;
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

function renderOutputFieldMappingWorkbench(node) {
  if (!isDataMappingNode(node)) return '';
  const fields = currentFieldMappingOverlay(node);
  if (fields.length === 0) return '';
  const saveStatus = state.saveStatus[node.id];
  const summary = coverageSummaryForFields(fields);
  const adviceIndex = fieldAdviceIndexForNode(node);
  const hasAdvice = adviceIndex.size > 0;
  const highConfidenceCount = [...adviceIndex.values()].filter((item, i, arr) => arr.indexOf(item) === i && item.judgement === 'ok' && Number(item.confidence) >= PI_HIGH_CONFIDENCE).length;
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
        <button class="secondary" data-workbench-action="derived-analysis" ${busy ? 'disabled' : ''}>派生字段分析</button>
        <button class="secondary" data-workbench-action="apply-high-confidence" ${hasAdvice && highConfidenceCount > 0 ? '' : 'disabled'}>应用高置信建议 ≥0.9（${highConfidenceCount}）</button>
        <button class="secondary" data-workbench-action="confirm-high-confidence" ${fields.some(field => field.mapping_status === 'suggested' && Number(field.confidence) >= PI_HIGH_CONFIDENCE) ? '' : 'disabled'}>批量确认高置信字段</button>
        <button class="secondary" id="confirm-field-mapping-contract" ${busy ? 'disabled' : ''}>确认映射合同</button>
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
                <td>${renderFieldCandidateOptions(field)}</td>
                <td>${escapeHtml(field.confidence === '' ? '-' : field.confidence)}</td>
                <td>${advice ? `<details><summary>${escapeHtml(advice.reason || advice.judgement)}</summary><p class="muted">建议来源：${escapeHtml(advice.suggested_source_api_id || '-')} · ${escapeHtml(advice.suggested_source_field_path || '-')}</p></details>` : '<span class="muted">-</span>'}</td>
                <td>${adviceQuickActions(field, advice)}</td>
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

function renderPiAgentStatus() {
  const status = state.piAgentStatus;
  if (!status) return '<p class="muted">PI runtime 状态待检测。</p>';
  const badge = status.status === 'ready' ? 'done' : 'waiting';
  return `
    <p class="muted">PI runtime：<span class="badge ${badge}">${escapeHtml(status.status || 'unknown')}</span> · scope：right_agent_only</p>
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

function renderContractCandidateApis(contract) {
  const apis = Array.isArray(contract?.candidate_apis) ? contract.candidate_apis : [];
  if (apis.length === 0) return '<p class="muted">暂无候选 API；一键生成字段覆盖方案会自动选择 API。</p>';
  return apis.map(api => `
    <article class="model-card db-agent-tool">
      <h4>${escapeHtml(api.name || api.api_id || '候选 API')}</h4>
      <p class="muted">api：${escapeHtml(api.api_id || '')} · domain：${escapeHtml(api.domain || '未声明')} · capability：${escapeHtml(api.capability || '未声明')}</p>
      <p class="muted">quality：${escapeHtml(api.quality_score ?? '未记录')} · missing params：${listText(api.missing_params || [], '无')}</p>
      <p class="muted">risk：${listText(api.risks || [], '无')}</p>
    </article>
  `).join('');
}

function renderContractRequestParams(contract) {
  const params = Array.isArray(contract?.request_param_mapping) ? contract.request_param_mapping : [];
  if (params.length === 0) return '<p class="muted">暂无请求参数映射；完成字段匹配后会展示。</p>';
  return `
    <div class="artifact-table-wrap">
      <table class="artifact-table">
        <thead>
          <tr>
            <th>业务参数</th>
            <th>API 参数</th>
            <th>取值</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          ${params.map(item => `
            <tr class="${item.status === 'missing' ? 'missing' : ''}">
              <td>${escapeHtml(item.business_param || '')}</td>
              <td>${escapeHtml(item.api_param || '')}</td>
              <td>${escapeHtml(item.value || '待补充')}</td>
              <td>${escapeHtml(item.status || '')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
}

function renderContractResponseFields(contract) {
  const fields = Array.isArray(contract?.field_coverage_plan) && contract.field_coverage_plan.length
    ? contract.field_coverage_plan.map(item => ({
      business_field: item.field_name || item.title,
      api_field_path: item.source_field_path || item.api_field_path,
      api_field_name: item.api_field_name,
      source_api_id: item.source_api_id,
      source_api_name: item.source_api_name,
      status: item.mapping_status,
      confidence: item.confidence,
      match_basis: item.match_basis || '',
    }))
    : Array.isArray(contract?.response_field_mapping) ? contract.response_field_mapping : [];
  if (fields.length === 0) return '<p class="muted">暂无响应字段映射；完成字段匹配后会展示。</p>';
  return `
    <div class="artifact-table-wrap">
      <table class="artifact-table">
        <thead>
          <tr>
            <th>业务字段</th>
            <th>来源 API</th>
            <th>API 字段</th>
            <th>置信度</th>
            <th>依据</th>
          </tr>
        </thead>
        <tbody>
          ${fields.map(item => `
            <tr class="${item.status === 'matched' ? '' : 'missing'}">
              <td>${escapeHtml(item.business_field || '')}</td>
              <td>${escapeHtml(item.source_api_name || item.source_api_id || '')}</td>
              <td>${escapeHtml(item.api_field_path || item.api_field_name || '待人工选择')}</td>
              <td>${escapeHtml(item.status || '')} · ${escapeHtml(item.confidence ?? '')}</td>
              <td>${escapeHtml(item.match_basis || '')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
}

function renderDataMappingContract(result) {
  const contract = contractFromDbAgentResult(result);
  if (!contract) return '';
  const knownEntries = Object.entries(contract.known_params || {}).filter(([, value]) => String(value || '').trim());
  const selected = contract.selected_api || {};
  const selectedApis = Array.isArray(contract.selected_apis) ? contract.selected_apis : [];
  const coverage = contract.coverage_summary || {};
  const unmatched = Array.isArray(contract.unmatched_fields) ? contract.unmatched_fields : [];
  const statusClass = ['confirmed', 'sample_ready'].includes(contract.status) ? 'done' : ['blocked', 'degraded', 'rejected'].includes(contract.status) ? 'failed' : 'waiting';
  return `
    <section class="db-agent-contract">
      <h4>数据映射合同</h4>
      <p class="save-status ${statusClass}">合同状态：${escapeHtml(contract.status || 'draft')}</p>
      <article class="model-card db-agent-tool">
        <h4>${escapeHtml(contract.business_requirement?.title || '业务数据需求')}</h4>
        <p>${escapeHtml(contract.business_requirement?.description || '暂无业务需求描述。')}</p>
        <p class="muted">required outputs：${listText(contract.business_requirement?.required_outputs || [], '无')}</p>
        <p class="muted">required fields：${listText(contract.business_requirement?.required_fields || [], '无')}</p>
      </article>
      <p class="muted">覆盖摘要：total ${escapeHtml(coverage.total ?? 0)} · mapped ${escapeHtml(coverage.mapped ?? 0)} · confirmed ${escapeHtml(coverage.confirmed ?? 0)} · missing_required ${escapeHtml(coverage.missing_required ?? 0)}</p>
      <details open>
        <summary>业务输入理解</summary>
        ${knownEntries.length ? `
          <ul class="meta-list">
            ${knownEntries.map(([key, value]) => `<li>${escapeHtml(key)}：${escapeHtml(value)}</li>`).join('')}
          </ul>
        ` : '<p class="muted">暂无已识别业务输入。</p>'}
      </details>
      ${selectedApis.length ? `
        <details open>
          <summary>已选 API 集合</summary>
          ${selectedApis.map(api => `
            <article class="model-card db-agent-tool">
              <h4>${escapeHtml(api.name || api.api_id || 'API')}</h4>
              <p class="muted">api：${escapeHtml(api.api_id || '')} · path：${escapeHtml(api.path || '')}</p>
            </article>
          `).join('')}
        </details>
      ` : ''}
      <details open>
        <summary>候选 API</summary>
        ${renderContractCandidateApis(contract)}
      </details>
      ${selected.api_id ? `
        <article class="model-card db-agent-tool">
          <h4>已选 API：${escapeHtml(selected.name || selected.api_id)}</h4>
          <p class="muted">api：${escapeHtml(selected.api_id || '')} · path：${escapeHtml(selected.path || '')}</p>
          <p class="muted">domain：${escapeHtml(selected.domain || '')} · capability：${escapeHtml(selected.capability || '')}</p>
        </article>
      ` : ''}
      <details open>
        <summary>请求参数映射</summary>
        ${renderContractRequestParams(contract)}
      </details>
      <details open>
        <summary>响应字段映射</summary>
        ${renderContractResponseFields(contract)}
      </details>
      <details open>
        <summary>人工确认</summary>
        ${unmatched.length ? `<p class="error-text">待人工确认字段：${listText(unmatched, '无')}</p>` : '<p class="muted">暂无未匹配字段；仍需用户确认 API 和口径后再取数。</p>'}
        <p class="muted">evidence：${listText(contract.evidence_refs || [], '暂未写入')}</p>
      </details>
    </section>
  `;
}

function renderBusinessInputResult(payload) {
  const known = payload.business_input || payload.known_params || {};
  const entries = Object.entries(known).filter(([, value]) => String(value || '').trim());
  return `
    <p class="save-status done">已理解业务输入。</p>
    <p class="muted">人-Agent 协同确认：请确认类目、周期、产品线是否正确，再继续映射 API。</p>
    ${entries.length ? `
      <ul class="meta-list">
        ${entries.map(([key, value]) => `<li>${escapeHtml(key)}：${escapeHtml(value)}</li>`).join('')}
      </ul>
    ` : '<p class="muted">还没有从上游产物提取到业务输入。</p>'}
  `;
}

function renderFieldMapResult(payload) {
  const selected = payload.selected_api || {};
  const matches = Array.isArray(payload.field_matches) ? payload.field_matches : [];
  const unmatched = Array.isArray(payload.unmatched_required_fields) ? payload.unmatched_required_fields : [];
  return `
    <p class="save-status ${unmatched.length ? 'waiting' : 'done'}">已完成字段匹配${unmatched.length ? '，仍需人工确认缺口。' : '。'}</p>
    <article class="model-card db-agent-tool">
      <h4>${escapeHtml(selected.name || selected.api_id || '候选 API')}</h4>
      <p class="muted">api：${escapeHtml(selected.api_id || '')} · path：${escapeHtml(selected.path || '')}</p>
      <p class="muted">domain：${escapeHtml(selected.domain || '')} · capability：${escapeHtml(selected.capability || '')} · quality：${escapeHtml(selected.quality_score ?? '')}</p>
    </article>
    <div class="artifact-table-wrap">
      <table class="artifact-table">
        <thead>
          <tr>
            <th>业务字段</th>
            <th>匹配状态</th>
            <th>API 字段</th>
            <th>依据</th>
          </tr>
        </thead>
        <tbody>
          ${matches.map(item => `
            <tr class="${item.status === 'matched' ? '' : 'missing'}">
              <td>${escapeHtml(item.required_field || '')}</td>
              <td>${escapeHtml(item.status || '')} · ${escapeHtml(item.score ?? '')}</td>
              <td>${item.api_field ? `${escapeHtml(item.api_field.path || item.api_field.name || '')}<br><span class="muted">${escapeHtml(item.api_field.desc || '')}</span>` : '待人工选择'}</td>
              <td>${escapeHtml(item.match_basis || '')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
    ${unmatched.length ? `<p class="error-text">待人工确认字段：${listText(unmatched, '无')}</p>` : ''}
  `;
}

function renderDbAgentResult(result) {
  if (!result) return '<p class="muted">点击按钮后会在这里展示接口、工具链、参数缺口和取数证据。</p>';
  if (result.status === 'running') {
    return `<p class="save-status saving">${escapeHtml(result.message || '数仓助手正在查询...')}</p>`;
  }
  if (result.ok === false) {
    return `
      <p class="save-status failed">数仓助手未就绪：${escapeHtml(result.reason || result.error || 'unknown')}</p>
      ${result.next_step ? `<p class="muted">下一步：${escapeHtml(result.next_step)}</p>` : ''}
      ${renderDataMappingContract(result)}
      <details>
        <summary>调试信息</summary>
        <pre class="json-output">${escapeHtml(JSON.stringify(result, null, 2))}</pre>
      </details>
    `;
  }
  const payload = result.payload || {};
  const contractView = renderDataMappingContract(result);
  if (result.action === 'understand_input') {
    return renderBusinessInputResult({ ...payload, business_input: result.known_params || payload.business_input || {} }) + contractView;
  }
  if (result.action === 'tool_plan') {
    return `
      <p class="save-status done">已完成数仓 API 映射方案。</p>
      <p class="muted">next：${escapeHtml(payload.next_question || '无')}</p>
      ${renderDbAgentTools(payload)}
      ${contractView}
    `;
  }
  if (result.action === 'field_map') {
    return renderFieldMapResult(payload) + contractView;
  }
  if (result.action === 'asset_card') {
    return `
      <p class="save-status done">已读取 API 详情。</p>
      <article class="model-card db-agent-tool">
        <h4>${escapeHtml(payload.selected_api?.name || payload.selected_api?.api_id || '已选 API')}</h4>
        <p class="muted">api：${escapeHtml(payload.selected_api?.api_id || '')} · path：${escapeHtml(payload.selected_api?.path || '')}</p>
      </article>
      ${contractView}
    `;
  }
  if (result.action === 'suggest_multi_api_mapping') {
    return `
      <p class="save-status ${result.status === 'suggested' ? 'done' : 'waiting'}">已生成多 API 字段覆盖建议。</p>
      <p class="muted">next：${escapeHtml(payload.next_question || '请在中间工作区审核字段来源，并确认映射合同。')}</p>
      ${contractView}
    `;
  }
  if (result.action === 'catalog') {
    return `
      <p class="save-status done">已查询可用排行接口。</p>
      ${contractView}
      <pre class="json-output">${escapeHtml(JSON.stringify(payload, null, 2))}</pre>
    `;
  }
  if (result.action === 'domain_apis') {
    return `
      <p class="save-status done">已列出商品/类目域接口。</p>
      ${contractView}
      <pre class="json-output">${escapeHtml(JSON.stringify(payload, null, 2))}</pre>
    `;
  }
  if (result.action === 'probe_sample') {
    return `
      <p class="save-status ${result.artifact ? 'done' : 'waiting'}">${result.artifact ? '已生成排行样例产物。' : '样例探针未返回可沉淀行。'}</p>
      ${result.artifact ? renderDraftArtifactTable(result.artifact) : ''}
      ${contractView}
      <pre class="json-output">${escapeHtml(JSON.stringify(payload, null, 2))}</pre>
    `;
  }
  return `<pre class="json-output">${escapeHtml(JSON.stringify(result, null, 2))}</pre>`;
}

function renderGapAgentPanel(node) {
  if (!isDataMappingNode(node)) return '';
  const fields = currentFieldMappingOverlay(node);
  const adviceIndex = fieldAdviceIndexForNode(node);
  const pendingFields = fields.filter(field => {
    const advice = adviceIndex.get(field.field_path) || adviceIndex.get(field.field_name);
    const status = String(field.mapping_status || field.status || '');
    return !field.source_field_path
      || ['unmapped', 'missing', 'derived_or_manual_required', 'manual_fill'].includes(status)
      || ['missing', 'needs_review', 'better_alternative'].includes(String(advice?.judgement || ''));
  });
  const derivedAdvice = Array.isArray(state.piAgentResults[node.id]?.advice?.derived_field_advice)
    ? state.piAgentResults[node.id].advice.derived_field_advice
    : [];
  const derivedFields = pendingFields.filter(field => field.source_kind === 'pi_derived' || String(field.mapping_status || '') === 'derived_or_manual_required');
  const busy = Boolean(state.piAgentBusy[node.id]);
  return `
    <div class="db-agent-panel gap-agent-panel">
      <h3>缺口助手</h3>
      ${renderPiAgentStatus()}
      <p class="muted">右侧只处理未覆盖、低置信和派生字段；API 选择、字段映射、批量确认和合同确认都在中间「字段覆盖工作台」完成。</p>
      <div class="agent-actions">
        <button class="secondary" data-workbench-action="derived-analysis" ${busy ? 'disabled' : ''}>生成派生字段填充方案</button>
      </div>
      <details open>
        <summary>待处理字段</summary>
        ${pendingFields.length ? `
          <ul class="meta-list">
            ${pendingFields.map(field => `<li>${escapeHtml(field.title || field.field_name)} · ${escapeHtml(field.mapping_status || 'unmapped')} · ${escapeHtml(field.source_field_path || '待补充')}</li>`).join('')}
          </ul>
        ` : '<p class="muted">当前没有待处理字段。</p>'}
      </details>
      <details open>
        <summary>派生字段</summary>
        ${derivedFields.length ? `
          <ul class="meta-list">
            ${derivedFields.map(field => `<li>${escapeHtml(field.title || field.field_name)}：${escapeHtml(field.description || '需要 Agent/人工基于证据分析')}</li>`).join('')}
          </ul>
        ` : '<p class="muted">当前没有被标记为派生/人工的字段。</p>'}
        ${derivedAdvice.length ? `
          <div class="artifact-table-wrap">
            <table class="artifact-table">
              <thead>
                <tr>
                  <th>字段</th>
                  <th>派生建议</th>
                  <th>所需证据</th>
                  <th>风险</th>
                </tr>
              </thead>
              <tbody>
                ${derivedAdvice.map(item => `
                  <tr>
                    <td>${escapeHtml(item.field_name || item.field_path || '')}</td>
                    <td>${escapeHtml(item.suggested_analysis || '')}</td>
                    <td>${listText(item.required_inputs || [], '无')}</td>
                    <td>${listText(item.risks || [], '无')}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        ` : '<p class="muted">尚未生成派生字段方案。</p>'}
      </details>
    </div>
  `;
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

function renderAgentPanel() {
  const node = currentNode();
  const view = node?.node_execution_view || {};
  const fields = node ? nodeActionFields(node) : [];
  return `
    <p class="muted">当前焦点：${escapeHtml(node?.name || '未选择节点')}</p>
    <p>${escapeHtml(view.goal?.markdown || '当前节点暂无结构化目标。')}</p>
    ${fields.length > 0 ? `<p class="muted">可协助填写：${listText(fields.map(field => field.label || field.id), '无')}</p>` : ''}
    ${renderGapAgentPanel(node)}
    <textarea class="agent-input" placeholder="询问这一步、要求重跑，或提出小范围修改"></textarea>
    <p class="muted">RunAgent 通道已预留；结构化动作会走可确认协议。</p>
  `;
}

function render() {
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
      <section class="layout">
        <aside class="panel">
          <h2>运行流程</h2>
          ${renderNodeList()}
        </aside>
        <section class="panel">
          <h2>节点详情</h2>
          ${renderNodeDetail()}
        </section>
        <aside class="panel">
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
    button.addEventListener('click', () => {
      state.selectedNodeId = button.getAttribute('data-node-id') || '';
      render();
    });
  });
  const runButton = document.getElementById('run-node');
  if (runButton) {
    runButton.addEventListener('click', runCurrentNode);
  }
  const saveDraftButton = document.getElementById('save-node-draft');
  if (saveDraftButton) {
    saveDraftButton.addEventListener('click', handleSaveNodeDraft);
  }
  const exportButton = document.getElementById('export-report');
  if (exportButton) {
    exportButton.addEventListener('click', exportReport);
  }
  document.querySelectorAll('[data-db-agent-action]').forEach(button => {
    button.addEventListener('click', () => {
      queryDbAgent(button.getAttribute('data-db-agent-action') || 'tool_plan');
    });
  });
  document.querySelectorAll('[data-workbench-action]').forEach(button => {
    button.addEventListener('click', () => {
      const action = button.getAttribute('data-workbench-action') || '';
      if (action === 'suggest') suggestFieldMappingWithPi();
      else if (action === 'derived-analysis') queryPiAgent('derived_field_analysis');
      else if (action === 'tool-plan') queryDbAgent('tool_plan');
      else if (action === 'apply-high-confidence') applyHighConfidenceAdvice();
      else if (action === 'confirm-high-confidence') confirmHighConfidenceMappings();
    });
  });
  document.querySelectorAll('[data-candidate-action]').forEach(button => {
    button.addEventListener('click', () => {
      applyCandidateFieldOption(button);
    });
  });
  document.querySelectorAll('[data-advice-action]').forEach(button => {
    button.addEventListener('click', () => {
      applyAdviceAction(button.getAttribute('data-advice-action') || '', button.getAttribute('data-advice-field') || '');
    });
  });
  const confirmFieldMappingButton = document.getElementById('confirm-field-mapping-contract');
  if (confirmFieldMappingButton) {
    confirmFieldMappingButton.addEventListener('click', confirmFieldMappingContract);
  }
  const saveDbAgentButton = document.getElementById('save-db-agent-evidence');
  if (saveDbAgentButton) {
    saveDbAgentButton.addEventListener('click', rememberDbAgentEvidence);
  }
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
        message: `已生成字段覆盖方案：${mapped}/${total} 已覆盖，${derived} 个派生/人工字段，${missing} 个必填未覆盖。请在中间工作区审核后确认合同。`,
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

async function saveFieldMappingDraft() {
  await persistFieldMappingContract('save_field_mapping');
}

async function confirmFieldMappingContract() {
  await persistFieldMappingContract('confirm_mapping');
}

async function persistFieldMappingContract(action) {
  const node = currentNode();
  if (!node || !isDataMappingNode(node)) return;
  const manualMapping = manualMappingForNode(node);
  const contract = contractFromDbAgentResult(dbAgentResultFor(node)) || {};
  const selectedApis = Array.isArray(contract.selected_apis) ? contract.selected_apis : [];
  const fieldCoveragePlan = currentFieldMappingOverlay(node).map(field => {
    const mapped = manualMapping.find(item => item.field_path === field.field_path || item.field_name === field.field_name) || {};
    return {
      ...field,
      ...mapped,
      source_field_path: mapped.source_field_path || mapped.api_field_path || field.source_field_path || field.api_field_path || '',
      mapping_status: mapped.mapping_status || mapped.status || field.mapping_status || 'unmapped',
      human_confirmed: action === 'confirm_mapping' ? Boolean(mapped.api_field_path || field.api_field_path || mapped.source_field_path || field.source_field_path) : Boolean(field.human_confirmed),
    };
  });
  state.dbAgentBusy[node.id] = true;
  render();
  try {
    const response = await fetch('/api/db-agent/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        node_id: node.id,
        action,
        selected_apis: selectedApis,
        upstream_artifacts: upstreamArtifactsFor(node),
        manual_response_field_mapping: manualMapping,
        field_coverage_plan: fieldCoveragePlan,
        human_decisions: action === 'confirm_mapping'
          ? [{ decision: 'confirmed', target: 'data_mapping_contract', note: '用户确认 API 与字段映射。' }]
          : [],
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.reason || payload.error || `field mapping failed: ${response.status}`);
    }
    state.dbAgentResults[node.id] = payload;
    if (payload.data_mapping_contract?.field_coverage_plan) {
      state.fieldMappingDrafts[node.id] = payload.data_mapping_contract.field_coverage_plan;
    } else if (payload.data_mapping_contract?.output_field_mapping_overlay) {
      state.fieldMappingDrafts[node.id] = payload.data_mapping_contract.output_field_mapping_overlay;
    }
    saveWorkbenchState();
    state.saveStatus[node.id] = {
      status: payload.ok ? 'done' : 'failed',
      message: action === 'confirm_mapping' ? '已确认映射合同。' : '已保存字段覆盖草稿。',
    };
  } catch (error) {
    state.saveStatus[node.id] = { status: 'failed', message: error.message || String(error) };
  } finally {
    state.dbAgentBusy[node.id] = false;
    saveDbAgentResults();
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
        message: '请基于当前输出字段要求、候选 API 完整 schema 和确定性 baseline，逐字段给出判断、置信度、理由，并指出缺口和下一步问题。',
        data_mapping_contract: contractFromDbAgentResult(dbAgentResultFor(node)) || {},
        field_coverage_plan: currentFieldMappingOverlay(node),
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

// 批量应用：仅 judgement=ok 且 confidence>=0.9，跳过低置信项并提示。
function applyHighConfidenceAdvice() {
  const node = currentNode();
  if (!node) return;
  const adviceIndex = fieldAdviceIndexForNode(node);
  const overlay = currentFieldMappingOverlay(node);
  let applied = 0;
  let skipped = 0;
  const next = overlay.map(field => {
    const advice = adviceIndex.get(field.field_path) || adviceIndex.get(field.field_name);
    if (!advice) return field;
    if (advice.judgement === 'ok' && Number(advice.confidence) >= PI_HIGH_CONFIDENCE && advice.suggested_source_field_path) {
      applied += 1;
      return {
        ...field,
        source_api_id: advice.suggested_source_api_id || field.source_api_id,
        source_field_path: advice.suggested_source_field_path,
        api_field_path: advice.suggested_source_field_path,
        source_role: 'api_field',
        source_kind: 'api_doc_index',
        mapping_status: 'suggested',
        confidence: advice.confidence,
        human_confirmed: false,
        human_note: `PI 高置信建议（${advice.confidence}）`,
      };
    }
    if (['needs_review', 'missing', 'better_alternative'].includes(advice.judgement) || Number(advice.confidence) < PI_HIGH_CONFIDENCE) {
      skipped += 1;
    }
    return field;
  });
  state.fieldMappingDrafts[node.id] = next;
  state.saveStatus[node.id] = { status: applied ? 'done' : 'waiting', message: `已应用 ${applied} 个高置信字段，跳过 ${skipped} 个需人工确认的字段。` };
  saveWorkbenchState();
  render();
}

function confirmHighConfidenceMappings() {
  const node = currentNode();
  if (!node) return;
  const overlay = currentFieldMappingOverlay(node);
  let confirmed = 0;
  const next = overlay.map(field => {
    const confidence = Number(field.confidence);
    const hasSource = Boolean(field.source_field_path || field.api_field_path);
    if (hasSource && ['mapped', 'suggested'].includes(String(field.mapping_status || '')) && confidence >= PI_HIGH_CONFIDENCE) {
      confirmed += 1;
      return { ...field, mapping_status: 'confirmed', human_confirmed: true, confirmed: true };
    }
    return field;
  });
  state.fieldMappingDrafts[node.id] = next;
  state.saveStatus[node.id] = { status: confirmed ? 'done' : 'waiting', message: `已批量确认 ${confirmed} 个高置信字段。` };
  saveWorkbenchState();
  render();
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

function rememberDbAgentEvidence() {
  const node = currentNode();
  if (!node) return;
  const result = dbAgentResultFor(node);
  if (!result) return;
  const contract = contractFromDbAgentResult(result);
  if (result.artifact) {
    rememberNodeArtifact(node.id, result.artifact);
    state.nodeStatus[node.id] = 'done';
    state.saveStatus[node.id] = { status: 'done', message: `已将数仓助手结果保存为${result.artifact.title || '节点产物'}。` };
  } else if (contract) {
    const artifact = {
      title: '数据映射合同',
      node_id: node.id,
      node_name: node.name || node.id,
      status: contract.status,
      data_mapping_contract: contract,
      evidence_ids: contract.evidence_refs || [],
      generated_at: new Date().toISOString(),
      source: 'db_agent.data_mapping_contract',
    };
    rememberNodeArtifact(node.id, artifact);
    state.latestResult[node.id] = {
      status: ['confirmed', 'sample_ready'].includes(contract.status) ? 'db_agent_contract_confirmed' : 'db_agent_contract_draft',
      artifact_title: artifact.title,
      db_agent: result,
      data_mapping_contract: contract,
      evidence_ref: result.evidence_ref || '',
    };
    state.nodeStatus[node.id] = ['blocked', 'degraded', 'rejected'].includes(contract.status) ? 'waiting' : 'waiting';
    state.saveStatus[node.id] = {
      status: result.ok === false ? 'failed' : 'done',
      message: result.ok === false
        ? `已保留映射合同草稿；仍需处理：${result.next_step || result.reason || '请补充数据映射信息'}。`
        : '已将数据映射合同保存为本节点输入/证据。',
    };
  } else {
    state.latestResult[node.id] = {
      status: result.ok ? 'db_agent_context_ready' : 'db_agent_context_degraded',
      db_agent: result,
      evidence_ref: result.evidence_ref || '',
    };
    state.nodeStatus[node.id] = result.ok ? 'waiting' : 'failed';
    state.saveStatus[node.id] = { status: result.ok ? 'done' : 'failed', message: result.ok ? '已将数仓助手查询结果保存为本节点输入/证据。' : '数仓助手结果不可用，已保留错误信息。' };
  }
  saveNodeArtifacts();
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
  return payload;
}

function isCompletedResult(result) {
  const status = String(result?.status || '');
  if (['waiting_upload', 'missing_required_fields', 'failed', 'error'].includes(status)) return false;
  if (Array.isArray(result?.missing_required) && result.missing_required.length > 0) return false;
  return true;
}

function completeNodeRun(nodeId, result, options = {}) {
  state.latestResult[nodeId] = result;
  const artifact = artifactFromRunResult(nodeId, result);
  if (artifact) rememberNodeArtifact(nodeId, artifact);
  state.nodeStatus[nodeId] = isCompletedResult(result) ? 'done' : 'waiting';
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
  state.pendingAutoAdvanceNodeId = node.id;
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
    await fetchDbAgentStatus();
    await fetchPiAgentStatus();
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
