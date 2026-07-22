const fs = require('fs');
const path = require('path');

const DIMENSIONS = ['产品类型', '材质', '功能', '风格', '人群', '场景', '价格带', '视觉表达', '流量入口'];
const FACT_DIMENSIONS = new Set(['产品类型', '材质', '功能', '风格', '场景']);
const DERIVED_DIMENSIONS = new Set(['人群', '流量入口']);
const HIGH_GROWTH_LABELS = new Set(['暴涨', '高增', '潜力']);
const CONCURRENCY = 2;

class GeneAnalysisError extends Error {
  constructor(statusCode, code, details = {}) {
    super(code);
    this.statusCode = statusCode;
    this.code = code;
    this.details = details;
  }
}

function readJson(filePath, fallback = null) {
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch (error) {
    if (error && error.code === 'ENOENT') return fallback;
    throw error;
  }
}

function atomicWriteJson(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const temporary = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  fs.writeFileSync(temporary, JSON.stringify(value, null, 2));
  fs.renameSync(temporary, filePath);
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function nonEmpty(value) {
  return value !== undefined && value !== null && String(value).trim() !== '';
}

function strictExactNumber(value) {
  if (typeof value === 'number') return Number.isFinite(value) && value >= 0 ? value : null;
  const text = String(value ?? '').trim();
  if (!/^\d+(?:\.\d+)?$/.test(text)) return null;
  const number = Number(text);
  return Number.isFinite(number) ? number : null;
}

function normalizedTags(value) {
  if (Array.isArray(value)) return Array.from(new Set(value.flatMap(normalizedTags))).sort();
  return Array.from(new Set(String(value || '')
    .split(/[、,，;；|/+\n]+/)
    .map(item => item.trim().replace(/\s+/g, ' '))
    .filter(Boolean))).sort();
}

function parsePiPayload(response) {
  if (!response || response.ok !== true) return null;
  if (response.proposal && typeof response.proposal === 'object') return response.proposal;
  const raw = response.response_text;
  if (raw && typeof raw === 'object') return raw;
  if (typeof raw !== 'string' || !raw.trim()) return null;
  const match = raw.match(/\{[\s\S]*\}/);
  if (!match) return null;
  try {
    const parsed = JSON.parse(match[0]);
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch {
    return null;
  }
}

function relativePriceBands(rows) {
  const prices = rows.map(row => Number(row['客单价'])).filter(Number.isFinite).sort((a, b) => a - b);
  if (prices.length < 3) return { lower: null, upper: null };
  return {
    lower: prices[Math.floor((prices.length - 1) / 3)],
    upper: prices[Math.floor(((prices.length - 1) * 2) / 3)],
  };
}

function relativePriceBand(row, bands) {
  if (nonEmpty(row['价格带'])) return { value: String(row['价格带']).trim(), status: 'api_fact' };
  const price = Number(row['客单价']);
  if (!Number.isFinite(price) || bands.lower === null || bands.upper === null) return { value: '', status: 'missing' };
  if (price <= bands.lower) return { value: `样本低价格带（≤${bands.lower}）`, status: 'deterministic_relative_band' };
  if (price <= bands.upper) return { value: `样本中价格带（${bands.lower}-${bands.upper}）`, status: 'deterministic_relative_band' };
  return { value: `样本高价格带（>${bands.upper}）`, status: 'deterministic_relative_band' };
}

function baseDimensions(row, bands) {
  const price = relativePriceBand(row, bands);
  const raw = {
    '产品类型': row['产品类型'],
    '材质': row['材质'],
    '功能': row['功能'],
    '风格': row['风格'],
    '人群': row['人群'],
    '场景': row['场景'],
    '价格带': price.value,
    '视觉表达': row['主图元素'] || row['视觉表达'],
    '流量入口': row['流量入口'],
  };
  const output = {};
  for (const name of DIMENSIONS) {
    const value = nonEmpty(raw[name]) ? String(raw[name]).trim() : '';
    let sourceStatus = value ? 'api_fact' : 'missing';
    if (name === '价格带') sourceStatus = price.status;
    if (name === '视觉表达' && value) sourceStatus = row['主图元素'] ? 'pi_derived_unconfirmed' : 'api_fact';
    output[name] = {
      raw_value: value,
      normalized_tags: normalizedTags(value),
      source_status: sourceStatus,
      confidence: value ? (sourceStatus === 'api_fact' ? 1 : 0.7) : 0,
      evidence_fields: value ? [name === '视觉表达' && row['主图元素'] ? '主图元素' : name] : [],
    };
  }
  return output;
}

function applyPiProposal(profile, proposal) {
  if (!proposal || String(proposal.row_id || '') !== profile.row_id) return profile;
  const normalized = proposal.normalized_dimensions && typeof proposal.normalized_dimensions === 'object'
    ? proposal.normalized_dimensions : {};
  const derived = proposal.derived_fields && typeof proposal.derived_fields === 'object'
    ? proposal.derived_fields : {};
  for (const name of DIMENSIONS) {
    const dimension = profile.dimensions[name];
    if (!dimension) continue;
    if (FACT_DIMENSIONS.has(name) || dimension.source_status === 'api_fact') {
      // Agent may normalize spelling, but must not replace the upstream fact with unrelated content.
      const candidate = normalizedTags(normalized[name]);
      const rawTokens = normalizedTags(dimension.raw_value).map(item => item.toLowerCase());
      const supported = candidate.filter(item => rawTokens.some(raw => raw.includes(item.toLowerCase()) || item.toLowerCase().includes(raw)));
      if (supported.length > 0) dimension.normalized_tags = supported;
      continue;
    }
    if (DERIVED_DIMENSIONS.has(name)) {
      const item = derived[name] && typeof derived[name] === 'object' ? derived[name] : {};
      const value = nonEmpty(item.value) ? String(item.value).trim() : '';
      const evidence = Array.isArray(item.evidence_fields) ? item.evidence_fields.map(String).filter(field => nonEmpty(profile.source_row[field])) : [];
      if (!value || evidence.length === 0) continue;
      dimension.raw_value = value;
      dimension.normalized_tags = normalizedTags(normalized[name]).length > 0 ? normalizedTags(normalized[name]) : normalizedTags(value);
      dimension.source_status = 'pi_derived_unconfirmed';
      dimension.confidence = Math.max(0, Math.min(1, Number(item.confidence || 0.5)));
      dimension.evidence_fields = evidence;
      continue;
    }
    if (dimension.source_status !== 'missing' && normalizedTags(normalized[name]).length > 0) {
      dimension.normalized_tags = normalizedTags(normalized[name]);
    }
  }
  return profile;
}

function profileFormula(dimensions) {
  const first = name => (dimensions[name] && dimensions[name].normalized_tags || [])[0] || '';
  return [first('产品类型') || first('材质'), first('场景'), first('功能'), first('价格带'), first('视觉表达')]
    .filter(Boolean).join(' + ');
}

function groupKey(profile) {
  const dimensions = profile.dimensions;
  const selected = ['产品类型', '材质', '功能', '人群', '场景']
    .map(name => [name, (dimensions[name].normalized_tags || [])[0] || ''])
    .filter(([, value]) => value);
  const hasProductAnchor = selected.some(([name]) => ['产品类型', '材质'].includes(name));
  const hasDemandAnchor = selected.some(([name]) => ['功能', '人群', '场景'].includes(name));
  if (selected.length < 3 || !hasProductAnchor || !hasDemandAnchor) return '';
  return selected.map(([name, value]) => `${name}:${value}`).join('|');
}

function unavailableSignal(value, threshold, comparator = 'gte') {
  if (value === null || value === undefined) return { status: 'unavailable', value: null, threshold, comparator };
  const matched = comparator === 'lt' ? value < threshold : value >= threshold;
  return { status: matched ? 'matched' : 'not_matched', value, threshold, comparator };
}

function localClassification(ruleId, label, sampleSize, signals) {
  if (sampleSize < 50) {
    const gatedSignals = Object.fromEntries(Object.entries(signals).map(([name, signal]) => {
      if (!name.startsWith('top50')) return [name, signal];
      return [name, { ...signal, status: 'insufficient_sample', value: signal.value }];
    }));
    return { rule_id: ruleId, label, status: 'insufficient_sample', matched: false, matched_count: 0, required_count: 2, signals: gatedSignals };
  }
  const matchedCount = Object.values(signals).filter(item => item.status === 'matched').length;
  return { rule_id: ruleId, label, status: matchedCount >= 2 ? 'matched' : 'not_matched', matched: matchedCount >= 2, matched_count: matchedCount, required_count: 2, signals };
}

function classifyGroup(group, sampleSize, evaluateRule) {
  const definitions = [
    ['strong_hot_gene', '强爆款基因', {
      top50_ratio: unavailableSignal(group.metrics.sample_ratio, 0.30),
      top100_ratio: unavailableSignal(null, 0.20),
      buyer_ratio: unavailableSignal(group.metrics.buyer_ratio, 0.30),
      gmv_ratio: unavailableSignal(group.metrics.gmv_ratio, 0.30),
    }],
    ['trend_hot_gene', '趋势爆款基因', {
      high_growth_product_ratio: unavailableSignal(group.metrics.high_growth_ratio, 0.30),
      keyword_growth: unavailableSignal(null, 0.20),
      buyer_growth_30d: unavailableSignal(null, 0.50),
      cross_platform_hot: unavailableSignal(null, true),
    }],
    ['differentiated_opportunity_gene', '差异机会基因', {
      review_painpoint_ratio: unavailableSignal(null, 0.10),
      qa_concern_ratio: unavailableSignal(null, 0.10),
      top50_supply_count: unavailableSignal(group.product_count, 5, 'lt'),
      price_band_supply_gap: unavailableSignal(null, true),
    }],
  ];
  return definitions.map(([ruleId, label, signals]) => {
    if (sampleSize < 50 || typeof evaluateRule !== 'function') return localClassification(ruleId, label, sampleSize, signals);
    const values = { sample_size: sampleSize };
    for (const [key, signal] of Object.entries(signals)) if (signal.status !== 'unavailable') values[key] = signal.value;
    const evaluated = evaluateRule(ruleId, values) || {};
    const evidenceSignals = evaluated.evidence && evaluated.evidence.signals;
    const normalizedSignals = {};
    for (const [key, fallback] of Object.entries(signals)) {
      const candidate = evidenceSignals && evidenceSignals[key];
      normalizedSignals[key] = candidate && typeof candidate === 'object' ? candidate : fallback;
    }
    return {
      rule_id: ruleId,
      label: String(evaluated.output_label || label),
      status: String(evaluated.evidence && evaluated.evidence.classification_status || (evaluated.matched ? 'matched' : 'not_matched')),
      matched: Boolean(evaluated.matched),
      matched_count: Number(evaluated.evidence && evaluated.evidence.matched_count || 0),
      required_count: 2,
      signals: normalizedSignals,
    };
  });
}

function createHotProductGeneAnalysisStore({ appRoot, artifactsDir, evidenceDir, defaultAgentModel, evaluateRule = null, onEvent = () => {} }) {
  const nodeId = 'analyze_hot_product_genes';
  const sourcePath = path.join(artifactsDir, 'collect_top_products.confirmed_data_table.json');
  const sourceConfirmationPath = path.join(evidenceDir, 'collect_top_products.data_table_confirmation.json');
  const analysisPath = path.join(artifactsDir, `${nodeId}.gene_analysis.json`);
  const confirmedPath = path.join(artifactsDir, `${nodeId}.confirmed_gene_analysis.json`);
  const evidencePath = path.join(evidenceDir, `${nodeId}.gene_analysis.json`);
  const controls = new Map();

  function sourceTable() {
    const table = readJson(sourcePath);
    const confirmation = readJson(sourceConfirmationPath);
    const valid = table && table.schema_version === 'data-table-confirmed-v1' && table.status === 'confirmed'
      && confirmation && confirmation.status === 'confirmed'
      && Number(confirmation.workspace_revision) === Number(table.workspace_revision);
    if (!valid) throw new GeneAnalysisError(409, 'source_table_not_confirmed');
    return table;
  }

  function persist(analysis) {
    analysis.updated_at = new Date().toISOString();
    atomicWriteJson(analysisPath, analysis);
    atomicWriteJson(evidencePath, {
      schema_version: 'hot-product-gene-analysis-evidence-v1',
      node_id: nodeId,
      execution_id: analysis.execution_id,
      source_table_ref: analysis.source_table_ref,
      source_revision: analysis.source_revision,
      progress: analysis.progress,
      risks: analysis.risks,
      updated_at: analysis.updated_at,
    });
    onEvent({ node_id: nodeId, execution_id: analysis.execution_id, analysis: clone(analysis) });
  }

  function buildGroups(profiles, sampleSize) {
    const totalBuyer = profiles.every(item => strictExactNumber(item.source_row['支付买家数']) !== null)
      ? profiles.reduce((sum, item) => sum + strictExactNumber(item.source_row['支付买家数']), 0) : null;
    const totalGmv = profiles.every(item => strictExactNumber(item.source_row.GMV) !== null)
      ? profiles.reduce((sum, item) => sum + strictExactNumber(item.source_row.GMV), 0) : null;
    const grouped = new Map();
    for (const profile of profiles) {
      const key = groupKey(profile);
      if (!key) continue;
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key).push(profile);
    }
    return Array.from(grouped.entries()).map(([key, members], index) => {
      const highGrowth = members.filter(item => HIGH_GROWTH_LABELS.has(String(item.source_row['是否高增速'] || ''))).length;
      const memberBuyer = totalBuyer === null ? null : members.reduce((sum, item) => sum + strictExactNumber(item.source_row['支付买家数']), 0);
      const memberGmv = totalGmv === null ? null : members.reduce((sum, item) => sum + strictExactNumber(item.source_row.GMV), 0);
      const group = {
        group_id: `gene-group-${index + 1}`,
        normalized_gene_key: key,
        member_row_ids: members.map(item => item.row_id),
        product_count: members.length,
        maturity: members.length >= 5 ? 'formal' : 'observation_candidate',
        gene_formula: members[0] ? members[0].gene_formula : '',
        metrics: {
          sample_ratio: sampleSize ? members.length / sampleSize : null,
          buyer_ratio: totalBuyer > 0 ? memberBuyer / totalBuyer : null,
          gmv_ratio: totalGmv > 0 ? memberGmv / totalGmv : null,
          high_growth_ratio: members.length ? highGrowth / members.length : null,
        },
      };
      group.classifications = classifyGroup(group, sampleSize, evaluateRule);
      group.business_actions = group.classifications.filter(item => item.matched).map(item => ({
        strong_hot_gene: '主推款、新品开发、爆款复制',
        trend_hot_gene: '快速测款、小批量上新',
        differentiated_opportunity_gene: '产品升级、视觉差异化、价格带错位',
      }[item.rule_id]));
      return group;
    }).sort((a, b) => b.product_count - a.product_count || a.normalized_gene_key.localeCompare(b.normalized_gene_key));
  }

  function findings(profiles) {
    return DIMENSIONS.map(name => {
      const counts = new Map();
      let covered = 0;
      for (const profile of profiles) {
        const tags = profile.dimensions[name].normalized_tags || [];
        if (tags.length > 0) covered += 1;
        for (const tag of tags) counts.set(tag, (counts.get(tag) || 0) + 1);
      }
      return {
        dimension: name,
        covered_products: covered,
        total_products: profiles.length,
        coverage_ratio: profiles.length ? covered / profiles.length : 0,
        top_tags: Array.from(counts.entries()).map(([tag, count]) => ({ tag, count, ratio: profiles.length ? count / profiles.length : 0 }))
          .sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag)).slice(0, 20),
      };
    });
  }

  async function mapLimit(items, limit, worker) {
    let cursor = 0;
    const runners = Array.from({ length: Math.min(limit, items.length) }, async () => {
      while (cursor < items.length) {
        const index = cursor;
        cursor += 1;
        await worker(items[index], index);
      }
    });
    await Promise.all(runners);
  }

  async function run(node, callAgent, options = {}) {
    const table = sourceTable();
    const rows = Array.isArray(table.rows) ? table.rows : [];
    const meta = Array.isArray(table.row_meta) ? table.row_meta : [];
    if (rows.length === 0) throw new GeneAnalysisError(409, 'source_table_empty');
    const executionId = String(options.execution_id || `gene-exec-${Date.now()}`);
    const control = { cancelled: false };
    controls.set(executionId, control);
    const bands = relativePriceBands(rows);
    const previousProfiles = new Map((Array.isArray(options.previous_profiles) ? options.previous_profiles : [])
      .map(profile => [String(profile.row_id || ''), clone(profile)]));
    const retryFailedOnly = options.retry_failed_only === true;
    const profiles = rows.map((row, index) => {
      const rowId = String(meta[index] && meta[index].row_id || `row:${index + 1}`);
      const previous = previousProfiles.get(rowId);
      if (retryFailedOnly && previous && previous.agent_status !== 'failed') return previous;
      return {
        row_id: rowId,
        goods_id: String(meta[index] && meta[index].source_identity || ''),
        rank: row['排名'] || index + 1,
        product_name: row['商品名'] || row['商品名称'] || '',
        product_url: row['商品链接'] || '',
        dimensions: baseDimensions(row, bands),
        gene_formula: '',
        gene_group_ids: [],
        agent_status: 'queued',
        requested_model: defaultAgentModel,
        actual_model: '',
        failure_reason: '',
        source_row: clone(row),
      };
    });
    const analysis = {
      schema_version: 'hot-product-gene-analysis-v1',
      node_id: nodeId,
      execution_id: executionId,
      source_table_ref: 'artifacts/collect_top_products.confirmed_data_table.json',
      source_revision: Number(table.workspace_revision || 0),
      source_trace: clone(
        node && node.analysis_node_view && node.analysis_node_view.source_trace
        || node && node.source_trace
        || {}
      ),
      sample_size: profiles.length,
      status: 'running',
      classification_status: profiles.length < 50 ? 'insufficient_sample' : 'evaluated',
      requested_model: defaultAgentModel,
      actual_models: [],
      product_profiles: profiles,
      dimension_findings: [],
      gene_groups: [],
      coverage: {},
      progress: {
        total_products: profiles.length,
        completed_products: profiles.filter(item => item.agent_status === 'completed').length,
        running_products: 0,
        failed_products: 0,
      },
      risks: profiles.length < 50 ? ['insufficient_sample_for_top50_classification'] : [],
      human_confirmation: { status: 'unconfirmed' },
      created_at: new Date().toISOString(),
    };
    persist(analysis);
    const pendingProfiles = retryFailedOnly ? profiles.filter(profile => profile.agent_status === 'queued') : profiles;
    await mapLimit(pendingProfiles, CONCURRENCY, async profile => {
      if (control.cancelled) {
        profile.agent_status = 'cancelled';
        return;
      }
      profile.agent_status = 'running';
      analysis.progress.running_products += 1;
      persist(analysis);
      const request = {
        intent: 'hot_product_gene_profile',
        model: defaultAgentModel,
        node_id: nodeId,
        gene_product_context: {
          row_id: profile.row_id,
          goods_id: profile.goods_id,
          target_dimensions: DIMENSIONS,
          source_row: clone(profile.source_row),
          source_revision: analysis.source_revision,
        },
        message: '仅规范化当前商品九维标签，并在证据充分时给出人群和建议流量入口草稿。不得修改上游事实，证据不足必须留空。',
      };
      try {
        const response = await callAgent(node, request, { execution_id: executionId, row_id: profile.row_id });
        const proposal = parsePiPayload(response);
        if (proposal) {
          applyPiProposal(profile, proposal);
          profile.agent_status = 'completed';
          profile.actual_model = String(response.actual_model || '');
        } else {
          profile.agent_status = 'failed';
          profile.failure_reason = String(response && response.reason || 'pi_invalid_response');
        }
      } catch (error) {
        profile.agent_status = 'failed';
        profile.failure_reason = String(error.message || error);
      }
      profile.gene_formula = profileFormula(profile.dimensions);
      analysis.progress.running_products -= 1;
      if (profile.agent_status === 'completed') analysis.progress.completed_products += 1;
      else analysis.progress.failed_products += 1;
      persist(analysis);
    });
    analysis.gene_groups = buildGroups(profiles, profiles.length);
    const groupsByRow = new Map();
    for (const group of analysis.gene_groups) for (const rowId of group.member_row_ids) {
      if (!groupsByRow.has(rowId)) groupsByRow.set(rowId, []);
      groupsByRow.get(rowId).push(group.group_id);
    }
    for (const profile of profiles) profile.gene_group_ids = groupsByRow.get(profile.row_id) || [];
    analysis.dimension_findings = findings(profiles);
    analysis.coverage = Object.fromEntries(analysis.dimension_findings.map(item => [item.dimension, {
      covered_products: item.covered_products,
      total_products: item.total_products,
      ratio: item.coverage_ratio,
    }]));
    analysis.actual_models = Array.from(new Set(profiles.map(item => item.actual_model).filter(Boolean)));
    if (analysis.progress.failed_products > 0) analysis.risks.push('partial_pi_failure');
    analysis.status = control.cancelled ? 'cancelled' : 'draft_ready';
    analysis.finished_at = new Date().toISOString();
    persist(analysis);
    controls.delete(executionId);
    return clone(analysis);
  }

  function analysisResponse(requestedNodeId = nodeId) {
    if (requestedNodeId !== nodeId) throw new GeneAnalysisError(400, 'gene_analysis_node_required');
    const analysis = readJson(analysisPath);
    const confirmed = readJson(confirmedPath);
    if (!analysis) return { analysis: null, confirmed_artifact: null };
    const table = readJson(sourcePath);
    const confirmation = readJson(sourceConfirmationPath);
    const current = table && confirmation && table.status === 'confirmed' && confirmation.status === 'confirmed'
      && Number(table.workspace_revision) === Number(analysis.source_revision)
      && Number(confirmation.workspace_revision) === Number(analysis.source_revision);
    if (!current) {
      analysis.status = 'stale';
      analysis.risks = Array.from(new Set([...(analysis.risks || []), 'source_table_changed_requires_rerun']));
      if (confirmed) {
        confirmed.status = 'stale';
        confirmed.human_confirmation = { ...(confirmed.human_confirmation || {}), status: 'stale' };
      }
      atomicWriteJson(analysisPath, analysis);
      if (confirmed) atomicWriteJson(confirmedPath, confirmed);
    }
    return { analysis, confirmed_artifact: confirmed };
  }

  function confirm(requestedNodeId, payload = {}) {
    const response = analysisResponse(requestedNodeId);
    const analysis = response.analysis;
    if (!analysis || analysis.status !== 'draft_ready') throw new GeneAnalysisError(409, 'gene_analysis_not_ready');
    if (String(payload.execution_id || '') !== analysis.execution_id || Number(payload.source_revision) !== Number(analysis.source_revision)) {
      throw new GeneAnalysisError(409, 'gene_analysis_revision_conflict');
    }
    const confirmedAt = new Date().toISOString();
    const artifact = {
      ...clone(analysis),
      schema_version: 'hot-product-gene-analysis-confirmed-v1',
      status: 'confirmed',
      human_confirmation: { status: 'confirmed', confirmed_by: String(payload.confirmed_by || 'local_user'), confirmed_at: confirmedAt },
      artifact_path: `artifacts/${nodeId}.confirmed_gene_analysis.json`,
    };
    atomicWriteJson(confirmedPath, artifact);
    return { ok: true, artifact, analysis };
  }

  function cancel(requestedNodeId, executionId) {
    if (requestedNodeId !== nodeId) throw new GeneAnalysisError(400, 'gene_analysis_node_required');
    const control = controls.get(executionId);
    if (!control) return { ok: false, status: 'not_running', execution_id: executionId };
    control.cancelled = true;
    return { ok: true, status: 'cancelling', execution_id: executionId };
  }

  async function retry(node, executionId, callAgent) {
    const current = readJson(analysisPath);
    if (!current || current.execution_id !== executionId) throw new GeneAnalysisError(404, 'gene_analysis_not_found');
    const table = sourceTable();
    if (Number(table.workspace_revision) !== Number(current.source_revision)) {
      throw new GeneAnalysisError(409, 'gene_analysis_source_revision_conflict', {
        expected_revision: Number(current.source_revision),
        current_revision: Number(table.workspace_revision),
      });
    }
    return run(node, callAgent, {
      execution_id: `gene-exec-${Date.now()}`,
      retry_failed_only: true,
      previous_profiles: current.product_profiles || [],
    });
  }

  return { run, retry, cancel, confirm, analysisResponse, sourceTable };
}

module.exports = {
  DIMENSIONS,
  GeneAnalysisError,
  createHotProductGeneAnalysisStore,
  __test: { normalizedTags, relativePriceBands, relativePriceBand, applyPiProposal, groupKey },
};
