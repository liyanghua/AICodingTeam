const fs = require('fs');
const path = require('path');

const EXTENSION_FIELD_TYPES = new Set(['string', 'number', 'url', 'image', 'single_select']);
const PATCH_OPERATIONS = new Set([
  'set_cell',
  'clear_cell',
  'restore_source',
  'add_extension_field',
  'update_extension_field',
  'delete_extension_field',
]);
const THREAD_MESSAGE_LIMIT = 200;
const THREAD_PI_HISTORY_LIMIT = 20;
const THREAD_AGENT_CALL_LIMIT = 50;
const THREAD_AGENT_BATCH_LIMIT = 20;
const DEFAULT_AGENT_MODEL = 'aicodemirror/gpt-5.6-sol';
const AGENT_BATCH_PAGE_SIZE = 10;
const AGENT_BATCH_CONCURRENCY = 2;
const AGENT_BATCH_TIMEOUT_MS = 10 * 60 * 1000;
const AGENT_FILLABLE_FIELDS = new Set(['功能', '风格', '主图元素', '爆款原因', '产品类型']);
const KEYWORD_FILLABLE_FIELDS = ['root_terms', 'demand_type'];
const KEYWORD_DEMAND_TYPES = new Set([
  '品类需求', '人群需求', '属性需求', '功能需求',
  '场景需求', '品牌需求', '风格需求', '定制需求',
]);
const API_FACT_FIELDS = new Set([
  '排名', '店铺名', '商品链接', '商品主图', '销量', '支付买家数', '销量/支付买家数',
  'GMV', '交易指数', 'GMV/交易指数', '客单价', '价格带', '是否高增速', 'speed_type',
]);

class CollaborationError extends Error {
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

function atomicWriteJson(filePath, payload) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const tempPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  fs.writeFileSync(tempPath, JSON.stringify(payload, null, 2));
  fs.renameSync(tempPath, filePath);
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function nonEmpty(value) {
  return value !== undefined && value !== null && String(value).trim() !== '';
}

function valuesEqual(left, right) {
  if (left === right) return true;
  if ((left && typeof left === 'object') || (right && typeof right === 'object')) {
    try {
      return JSON.stringify(left) === JSON.stringify(right);
    } catch {
      return false;
    }
  }
  return false;
}

function compareAgentModels(requestedModel, actualModel) {
  const requested = String(requestedModel || '').trim();
  const actual = String(actualModel || '').trim();
  if (!actual) return { status: 'unknown', reason: 'unknown' };
  if (requested === actual) return { status: 'matched', reason: 'exact' };
  const requestedQualified = requested.includes('/');
  const actualQualified = actual.includes('/');
  const requestedBase = requested.split('/').pop();
  const actualBase = actual.split('/').pop();
  if (requestedBase && requestedBase === actualBase && requestedQualified !== actualQualified) {
    return { status: 'matched', reason: 'provider_omitted' };
  }
  return { status: 'substituted', reason: 'different_model' };
}

function fieldPathOf(field) {
  return String(field && (field.field_name || field.title || field.field_path) || '').trim();
}

function rowIdentityFromUrl(value) {
  const text = String(value || '').trim();
  if (!text) return '';
  const match = text.match(/[?&]id=([^&#]+)/i);
  if (match) return decodeURIComponent(match[1]);
  return text.replace(/#.*$/, '').replace(/\/$/, '');
}

function rowIdentity(row) {
  if (!row || typeof row !== 'object' || Array.isArray(row)) return '';
  for (const key of ['goods_id', 'commodity_id', 'item_id', 'product_id']) {
    if (nonEmpty(row[key])) return String(row[key]).trim();
  }
  for (const key of ['商品链接', 'goods_url', 'product_url', 'item_url', 'commodity_url']) {
    const identity = rowIdentityFromUrl(row[key]);
    if (identity) return identity;
  }
  return '';
}

function safeRowId(identity, executionId, index) {
  if (identity) return `goods:${identity}`;
  return `row:${executionId || 'draft'}:${index + 1}`;
}

function normalizedRowMeta(table) {
  const rows = Array.isArray(table && table.rows) ? table.rows : [];
  const supplied = Array.isArray(table && table.row_meta) ? table.row_meta : [];
  const executionId = String(table && (table.execution_id || table.created_at) || 'draft');
  return rows.map((row, index) => {
    const existing = supplied[index] && typeof supplied[index] === 'object' ? supplied[index] : {};
    const identity = String(existing.source_identity || rowIdentity(row));
    return {
      row_id: String(existing.row_id || safeRowId(identity, executionId, index)),
      source_identity: identity,
      source_index: index,
    };
  });
}

function normalizedRequirements(node) {
  const insight = node && node.analysis_node_view && node.analysis_node_view.insight_output_model;
  const requirements = insight && Array.isArray(insight.requirements) ? insight.requirements : [];
  const source = requirements.length > 0
    ? requirements
    : [{ question: '基于当前数据表形成有证据引用的业务分析结论。', required_evidence_fields: [] }];
  return source.map((item, index) => ({
    requirement_id: String(item.requirement_id || `insight_${index + 1}`),
    question: String(item.question || item.title || `分析结论 ${index + 1}`),
    required_evidence_fields: Array.isArray(item.required_evidence_fields) ? item.required_evidence_fields.map(String) : [],
    source_ref: String(item.source_ref || 'app.config.json:analysis_node_view'),
  }));
}

function createCollaborationStore({
  appRoot,
  artifactsDir,
  evidenceDir,
  defaultAgentModel = DEFAULT_AGENT_MODEL,
  onAgentCallEvent = () => {},
  onDataTableConfirmed = () => ({}),
}) {
  const tablePath = nodeId => path.join(artifactsDir, `${nodeId}.data_table.json`);
  const workspacePath = nodeId => path.join(artifactsDir, `${nodeId}.data_table_workspace.json`);
  const confirmedTablePath = nodeId => path.join(artifactsDir, `${nodeId}.confirmed_data_table.json`);
  const confirmationPath = nodeId => path.join(evidenceDir, `${nodeId}.data_table_confirmation.json`);
  const historyPath = nodeId => path.join(evidenceDir, `${nodeId}.data_table_edit_history.json`);
  const insightPath = nodeId => path.join(artifactsDir, `${nodeId}.insight_workspace.json`);
  const threadPath = nodeId => path.join(artifactsDir, `${nodeId}.agent_thread.json`);
  const threadHistoryPath = nodeId => path.join(evidenceDir, `${nodeId}.agent_thread_history.json`);
  const batchPath = (nodeId, batchId) => path.join(artifactsDir, `${nodeId}.agent_batch.${batchId}.json`);
  const batchHistoryPath = nodeId => path.join(evidenceDir, `${nodeId}.agent_batch_history.json`);

  function baseTable(nodeId) {
    const table = readJson(tablePath(nodeId));
    if (!table || table.schema_version !== 'data-table-draft-v1') {
      throw new CollaborationError(404, 'data_table_not_found', { node_id: nodeId });
    }
    return table;
  }

  function createWorkspace(nodeId, table) {
    return {
      schema_version: 'data-table-workspace-v1',
      node_id: nodeId,
      base_data_table_ref: `artifacts/${nodeId}.data_table.json`,
      base_execution_id: String(table.execution_id || table.created_at || ''),
      revision: 0,
      fields: Array.isArray(table.fields) ? clone(table.fields) : [],
      row_meta: normalizedRowMeta(table),
      cell_overrides: {},
      extension_fields: [],
      pending_agent_proposals: [],
      orphaned_patches: [],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
  }

  function reconcileWorkspace(nodeId, workspace, table) {
    const executionId = String(table.execution_id || table.created_at || '');
    if (String(workspace.base_execution_id || '') === executionId) return workspace;
    const nextMeta = normalizedRowMeta(table);
    const validRows = new Set(nextMeta.map(item => item.row_id));
    const migrated = {};
    const orphaned = Array.isArray(workspace.orphaned_patches) ? clone(workspace.orphaned_patches) : [];
    for (const [rowId, fields] of Object.entries(workspace.cell_overrides || {})) {
      if (validRows.has(rowId)) migrated[rowId] = fields;
      else orphaned.push({ row_id: rowId, fields, reason: 'row_not_found_after_rerun', orphaned_at: new Date().toISOString() });
    }
    const next = {
      ...workspace,
      base_execution_id: executionId,
      base_data_table_ref: `artifacts/${nodeId}.data_table.json`,
      fields: Array.isArray(table.fields) ? clone(table.fields) : [],
      row_meta: nextMeta,
      cell_overrides: migrated,
      pending_agent_proposals: (workspace.pending_agent_proposals || []).map(item => ({ ...item, status: 'stale' })),
      orphaned_patches: orphaned,
      revision: Number(workspace.revision || 0) + 1,
      updated_at: new Date().toISOString(),
    };
    atomicWriteJson(workspacePath(nodeId), next);
    markDataTableConfirmationStale(nodeId, next.revision);
    markInsightBlocksStale(nodeId, next.revision, new Set(), true);
    return next;
  }

  function loadWorkspace(nodeId) {
    const table = baseTable(nodeId);
    let workspace = readJson(workspacePath(nodeId));
    if (!workspace || workspace.schema_version !== 'data-table-workspace-v1') {
      workspace = createWorkspace(nodeId, table);
      atomicWriteJson(workspacePath(nodeId), workspace);
    } else {
      workspace = reconcileWorkspace(nodeId, workspace, table);
    }
    return { workspace, table };
  }

  function effectiveFields(workspace) {
    return [...(workspace.fields || []), ...(workspace.extension_fields || [])];
  }

  function effectiveRows(workspace, table) {
    const extensions = Array.isArray(workspace.extension_fields) ? workspace.extension_fields : [];
    return (Array.isArray(table.rows) ? table.rows : []).map((sourceRow, index) => {
      const row = { ...sourceRow };
      for (const field of extensions) {
        const fieldPath = fieldPathOf(field);
        if (fieldPath && !Object.prototype.hasOwnProperty.call(row, fieldPath)) row[fieldPath] = '';
      }
      const rowId = workspace.row_meta[index] && workspace.row_meta[index].row_id;
      for (const [fieldPath, override] of Object.entries(workspace.cell_overrides[rowId] || {})) {
        row[fieldPath] = override.value;
      }
      return row;
    });
  }

  function agentEnrichmentSummary(nodeId, workspace, table, rows) {
    const fieldNames = effectiveFields(workspace).map(fieldPathOf).filter(Boolean);
    const keywordTable = fieldNames.includes('keyword')
      && KEYWORD_FILLABLE_FIELDS.some(field => fieldNames.includes(field));
    const definitions = derivedFieldCatalog(table);
    const fillableFields = keywordTable
      ? KEYWORD_FILLABLE_FIELDS.filter(field => fieldNames.includes(field))
      : fieldNames.filter(field => definitions.has(field) || AGENT_FILLABLE_FIELDS.has(field));
    const totalCells = rows.length * fillableFields.length;
    const remainingCells = rows.reduce((count, row) => (
      count + fillableFields.filter(field => !nonEmpty(row && row[field])).length
    ), 0);
    const filledCells = Math.max(0, totalCells - remainingCells);
    let latestBatch = null;
    const thread = readJson(threadPath(nodeId));
    const summaries = thread && Array.isArray(thread.agent_batches) ? thread.agent_batches : [];
    const latestSummary = summaries[summaries.length - 1];
    if (latestSummary && latestSummary.batch_id) {
      const storedBatch = readJson(batchPath(nodeId, String(latestSummary.batch_id || '')));
      if (storedBatch) latestBatch = decorateAgentBatchFreshness(nodeId, storedBatch, workspace);
    }
    let status = remainingCells === 0 && totalCells > 0
      ? 'agent_enrichment_complete'
      : filledCells > 0
        ? 'agent_enrichment_partial'
        : 'agent_enrichment_pending';
    if (remainingCells > 0 && latestBatch && ['preparing', 'running'].includes(String(latestBatch.status || ''))) {
      status = 'agent_enrichment_running';
    } else if (remainingCells > 0 && filledCells === 0 && latestBatch && String(latestBatch.status || '') === 'review_ready'
      && (latestBatch.proposals || []).some(proposal => proposal.status === 'pending')) {
      status = 'agent_review_ready';
    }
    return {
      subject_kind: keywordTable ? 'keyword' : 'product',
      fillable_fields: fillableFields,
      total_cells: totalCells,
      filled_cells: filledCells,
      remaining_cells: remainingCells,
      status,
      latest_batch_id: String(latestBatch && latestBatch.batch_id || ''),
    };
  }

  function workspaceResponse(nodeId) {
    const { workspace, table } = loadWorkspace(nodeId);
    const rows = effectiveRows(workspace, table);
    const confirmation = readJson(confirmationPath(nodeId));
    const confirmedArtifact = readJson(confirmedTablePath(nodeId));
    const confirmationCurrent = confirmation
      && confirmation.status === 'confirmed'
      && Number(confirmation.workspace_revision) === Number(workspace.revision || 0);
    return {
      ok: true,
      workspace,
      effective_fields: effectiveFields(workspace),
      effective_rows: rows,
      agent_enrichment: agentEnrichmentSummary(nodeId, workspace, table, rows),
      confirmation: confirmationCurrent ? confirmation : confirmation ? { ...confirmation, status: 'stale' } : null,
      confirmed_artifact: confirmationCurrent ? confirmedArtifact : null,
    };
  }

  function markDataTableConfirmationStale(nodeId, revision) {
    const confirmation = readJson(confirmationPath(nodeId));
    if (!confirmation || confirmation.status !== 'confirmed') return;
    confirmation.status = 'stale';
    confirmation.stale_at = new Date().toISOString();
    confirmation.stale_revision = Number(revision || 0);
    atomicWriteJson(confirmationPath(nodeId), confirmation);
  }

  function fieldIndex(workspace) {
    return new Map(effectiveFields(workspace).map(field => [fieldPathOf(field), field]));
  }

  function rowIndex(workspace) {
    return new Map((workspace.row_meta || []).map((item, index) => [String(item.row_id || ''), index]));
  }

  function currentValue(workspace, table, rowId, fieldPath) {
    const index = rowIndex(workspace).get(rowId);
    if (index === undefined) throw new CollaborationError(400, 'row_not_found', { row_id: rowId });
    const override = workspace.cell_overrides[rowId] && workspace.cell_overrides[rowId][fieldPath];
    if (override) return override.value;
    return table.rows[index] && Object.prototype.hasOwnProperty.call(table.rows[index], fieldPath)
      ? table.rows[index][fieldPath]
      : '';
  }

  function appendHistory(nodeId, record) {
    const existing = readJson(historyPath(nodeId), { schema_version: 'data-table-edit-history-v1', node_id: nodeId, records: [] });
    existing.records = [...(existing.records || []), record].slice(-100);
    existing.updated_at = new Date().toISOString();
    atomicWriteJson(historyPath(nodeId), existing);
  }

  function markInsightBlocksStale(nodeId, tableRevision, changedFields, all = false) {
    const filePath = insightPath(nodeId);
    const workspace = readJson(filePath);
    if (!workspace || workspace.schema_version !== 'insight-collaboration-v1') return;
    let changed = false;
    workspace.blocks = (workspace.blocks || []).map(block => {
      const used = new Set([
        ...(block.required_evidence_fields || []),
        ...(block.evidence_bindings || []).map(item => String(item.field_path || '')).filter(Boolean),
      ]);
      const affected = all || Array.from(changedFields).some(field => used.has(field));
      const hasContent = Boolean(String(block.draft_text || '').trim()) || String(block.status || '') === 'confirmed';
      if (!affected || !hasContent) return block;
      changed = true;
      return {
        ...block,
        status: 'stale',
        risks: Array.from(new Set([...(block.risks || []), 'data_table_changed_requires_review'])),
        human_confirmation: { ...(block.human_confirmation || {}), status: 'stale' },
      };
    });
    workspace.table_revision = tableRevision;
    if (changed) workspace.revision = Number(workspace.revision || 0) + 1;
    workspace.updated_at = new Date().toISOString();
    atomicWriteJson(filePath, workspace);
  }

  function validateRevision(workspace, baseRevision) {
    if (Number(baseRevision) !== Number(workspace.revision || 0)) {
      throw new CollaborationError(409, 'revision_conflict', { current_revision: Number(workspace.revision || 0) });
    }
  }

  function applyPatch(nodeId, payload, options = {}) {
    const { workspace: stored, table } = loadWorkspace(nodeId);
    if (String(payload && payload.schema_version || '') !== 'data-table-edit-patch-v1') {
      throw new CollaborationError(400, 'patch_schema_invalid');
    }
    validateRevision(stored, payload && payload.base_revision);
    const operations = Array.isArray(payload && payload.operations) ? payload.operations : [];
    if (operations.length === 0 || operations.length > 1000) {
      throw new CollaborationError(400, 'invalid_operations');
    }
    const before = clone(stored);
    const workspace = clone(stored);
    const changedFields = new Set();
    const conflicts = [];

    for (const operation of operations) {
      const kind = String(operation && operation.operation || '');
      if (!PATCH_OPERATIONS.has(kind)) throw new CollaborationError(400, 'operation_not_allowed', { operation: kind });
      const fieldPath = String(operation.field_path || operation.field_name || '').trim();
      if (kind === 'add_extension_field') {
        if (!fieldPath || fieldIndex(workspace).has(fieldPath)) throw new CollaborationError(400, 'field_already_exists', { field_path: fieldPath });
        const type = String(operation.field_type || operation.type || 'string');
        if (!EXTENSION_FIELD_TYPES.has(type)) throw new CollaborationError(400, 'extension_field_type_invalid', { field_type: type });
        workspace.extension_fields.push({
          field_path: fieldPath,
          field_name: fieldPath,
          title: String(operation.title || fieldPath),
          description: String(operation.description || ''),
          type,
          required: false,
          options: type === 'single_select' && Array.isArray(operation.options) ? operation.options.map(String) : [],
          source: 'user_extension',
        });
        changedFields.add(fieldPath);
        continue;
      }
      if (kind === 'update_extension_field') {
        const index = workspace.extension_fields.findIndex(item => fieldPathOf(item) === fieldPath);
        if (index < 0) throw new CollaborationError(400, 'extension_field_not_found', { field_path: fieldPath });
        const type = String(operation.field_type || operation.type || workspace.extension_fields[index].type || 'string');
        if (!EXTENSION_FIELD_TYPES.has(type)) throw new CollaborationError(400, 'extension_field_type_invalid', { field_type: type });
        workspace.extension_fields[index] = {
          ...workspace.extension_fields[index],
          title: String(operation.title || workspace.extension_fields[index].title || fieldPath),
          description: operation.description === undefined ? workspace.extension_fields[index].description : String(operation.description || ''),
          type,
          options: type === 'single_select' && Array.isArray(operation.options) ? operation.options.map(String) : [],
        };
        changedFields.add(fieldPath);
        continue;
      }
      if (kind === 'delete_extension_field') {
        const index = workspace.extension_fields.findIndex(item => fieldPathOf(item) === fieldPath);
        if (index < 0) throw new CollaborationError(400, 'protected_or_missing_field', { field_path: fieldPath });
        workspace.extension_fields.splice(index, 1);
        for (const rowFields of Object.values(workspace.cell_overrides || {})) delete rowFields[fieldPath];
        changedFields.add(fieldPath);
        continue;
      }

      const rowId = String(operation.row_id || '');
      if (!fieldIndex(workspace).has(fieldPath)) throw new CollaborationError(400, 'field_not_found', { field_path: fieldPath });
      const current = currentValue(workspace, table, rowId, fieldPath);
      if (Object.prototype.hasOwnProperty.call(operation, 'expected_value') && !valuesEqual(operation.expected_value, current)) {
        conflicts.push({ row_id: rowId, field_path: fieldPath, expected_value: operation.expected_value, current_value: current });
        continue;
      }
      if (!workspace.cell_overrides[rowId]) workspace.cell_overrides[rowId] = {};
      if (kind === 'restore_source') {
        delete workspace.cell_overrides[rowId][fieldPath];
        if (Object.keys(workspace.cell_overrides[rowId]).length === 0) delete workspace.cell_overrides[rowId];
      } else {
        const sourceKind = String(operation.source_kind || 'manual');
        if (!['manual', 'pi_derived'].includes(sourceKind)) throw new CollaborationError(400, 'source_kind_not_allowed');
        workspace.cell_overrides[rowId][fieldPath] = {
          value: kind === 'clear_cell' ? '' : operation.new_value,
          original_value: table.rows[rowIndex(workspace).get(rowId)] && table.rows[rowIndex(workspace).get(rowId)][fieldPath] !== undefined
            ? table.rows[rowIndex(workspace).get(rowId)][fieldPath]
            : '',
          source_kind: sourceKind,
          reason: String(operation.reason || ''),
          confidence: Number.isFinite(Number(operation.confidence)) ? Number(operation.confidence) : null,
          evidence_refs: Array.isArray(operation.evidence_refs) ? operation.evidence_refs.map(String) : [],
          proposal_id: String(operation.proposal_id || payload.proposal_id || ''),
          batch_id: String(operation.batch_id || payload.batch_id || ''),
          overrides_api_value: nonEmpty(current),
          updated_at: new Date().toISOString(),
        };
      }
      changedFields.add(fieldPath);
    }

    if (conflicts.length > 0) throw new CollaborationError(409, 'cell_value_conflict', { conflicts });
    workspace.revision = Number(stored.revision || 0) + 1;
    workspace.updated_at = new Date().toISOString();
    workspace.pending_agent_proposals = (workspace.pending_agent_proposals || []).map(item => {
      if (item.status !== 'pending') return item;
      if (item.proposal_id !== payload.proposal_id) return { ...item, status: 'stale' };
      const appliedIndices = new Set(Array.isArray(payload.proposal_patch_indices) ? payload.proposal_patch_indices.map(Number) : []);
      const patches = (item.patches || []).map((patch, index) => appliedIndices.has(index)
        ? { ...patch, status: 'applied', applied_at: new Date().toISOString() }
        : patch);
      const complete = patches.length > 0 && patches.every(patch => patch.status === 'applied');
      return {
        ...item,
        patches,
        status: complete ? 'applied' : 'pending',
        workspace_revision: workspace.revision,
        applied_at: complete ? new Date().toISOString() : '',
      };
    });
    atomicWriteJson(workspacePath(nodeId), workspace);
    markDataTableConfirmationStale(nodeId, workspace.revision);
    appendHistory(nodeId, {
      edit_id: `edit-${Date.now()}`,
      created_at: new Date().toISOString(),
      revision_before: stored.revision,
      revision_after: workspace.revision,
      source_kind: String(options.sourceKind || operations[0].source_kind || 'manual'),
      proposal_id: String(payload.proposal_id || ''),
      batch_id: String(payload.batch_id || ''),
      operations: clone(operations),
      before_workspace: before,
      status: 'applied',
    });
    markInsightBlocksStale(nodeId, workspace.revision, changedFields);
    return workspaceResponse(nodeId);
  }

  function undo(nodeId, payload) {
    const { workspace } = loadWorkspace(nodeId);
    validateRevision(workspace, payload && payload.base_revision);
    const history = readJson(historyPath(nodeId), { records: [] });
    const record = [...(history.records || [])].reverse().find(item => item.status === 'applied' && item.before_workspace);
    if (!record) throw new CollaborationError(409, 'nothing_to_undo');
    const restored = {
      ...clone(record.before_workspace),
      revision: Number(workspace.revision || 0) + 1,
      base_execution_id: workspace.base_execution_id,
      base_data_table_ref: workspace.base_data_table_ref,
      row_meta: workspace.row_meta,
      updated_at: new Date().toISOString(),
    };
    record.status = 'undone';
    record.undone_at = new Date().toISOString();
    history.updated_at = new Date().toISOString();
    atomicWriteJson(workspacePath(nodeId), restored);
    markDataTableConfirmationStale(nodeId, restored.revision);
    atomicWriteJson(historyPath(nodeId), history);
    markInsightBlocksStale(nodeId, restored.revision, new Set(), true);
    return workspaceResponse(nodeId);
  }

  function storeProposal(nodeId, payload) {
    const { workspace } = loadWorkspace(nodeId);
    validateRevision(workspace, payload && payload.base_revision);
    const proposalId = String(payload.proposal_id || (payload.proposal && payload.proposal.proposal_id) || '');
    if (payload.action === 'reject') {
      workspace.pending_agent_proposals = (workspace.pending_agent_proposals || []).map(item => item.proposal_id === proposalId
        ? { ...item, status: 'rejected', rejected_at: new Date().toISOString() }
        : item);
    } else {
      const proposal = clone(payload.proposal || payload);
      if (proposal.schema_version !== 'data-table-edit-proposal-v1') throw new CollaborationError(400, 'proposal_schema_invalid');
      proposal.proposal_id = String(proposal.proposal_id || `proposal-${Date.now()}`);
      proposal.workspace_revision = Number(workspace.revision || 0) + 1;
      proposal.status = 'pending';
      proposal.requires_human_application = true;
      proposal.patches = (Array.isArray(proposal.patches) ? proposal.patches : []).map(item => ({ ...item, status: 'pending' }));
      workspace.pending_agent_proposals = [...(workspace.pending_agent_proposals || []), proposal].slice(-20);
    }
    workspace.revision = Number(workspace.revision || 0) + 1;
    workspace.updated_at = new Date().toISOString();
    atomicWriteJson(workspacePath(nodeId), workspace);
    return workspaceResponse(nodeId);
  }

  function createInsightWorkspace(nodeId, node, tableRevision) {
    return {
      schema_version: 'insight-collaboration-v1',
      node_id: nodeId,
      table_revision: tableRevision,
      revision: 0,
      blocks: normalizedRequirements(node).map(requirement => ({
        ...requirement,
        draft_text: '',
        evidence_bindings: [],
        pending_agent_proposals: [],
        risks: [],
        questions_for_user: [],
        status: 'not_started',
        human_confirmation: { status: 'unconfirmed', confirmed_by: '', confirmed_at: '' },
      })),
      consolidated_narrative: { text: '', status: 'not_started', human_confirmation: { status: 'unconfirmed' } },
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
  }

  function loadInsightWorkspace(nodeId, node) {
    const table = workspaceResponse(nodeId);
    let workspace = readJson(insightPath(nodeId));
    if (!workspace || workspace.schema_version !== 'insight-collaboration-v1') {
      workspace = createInsightWorkspace(nodeId, node, table.workspace.revision);
      atomicWriteJson(insightPath(nodeId), workspace);
    }
    return { workspace, table };
  }

  function insightResponse(nodeId, node) {
    const { workspace, table } = loadInsightWorkspace(nodeId, node);
    return { ok: true, workspace, evidence_summary: evidenceSummary(workspace, table) };
  }

  function validateEvidenceBindings(bindings, table) {
    const fields = new Set((table.effective_fields || []).map(fieldPathOf));
    const rows = new Set((table.workspace.row_meta || []).map(item => String(item.row_id || '')));
    const invalid = [];
    for (const binding of bindings) {
      const fieldPath = String(binding && binding.field_path || '');
      const rowId = String(binding && binding.row_id || '');
      if (fieldPath && !fields.has(fieldPath)) invalid.push({ ...binding, reason: 'field_not_found' });
      if (rowId && !rows.has(rowId)) invalid.push({ ...binding, reason: 'row_not_found' });
    }
    if (invalid.length > 0) throw new CollaborationError(400, 'evidence_binding_invalid', { invalid_bindings: invalid });
  }

  function evidenceSummary(workspace, table) {
    const rows = table.effective_rows || [];
    const summaries = {};
    for (const block of workspace.blocks || []) {
      const fields = Array.from(new Set([...(block.required_evidence_fields || []), ...(block.evidence_bindings || []).map(item => item.field_path).filter(Boolean)]));
      summaries[block.requirement_id] = fields.map(fieldPath => {
        const values = rows.map(row => row[fieldPath]).filter(nonEmpty);
        const frequencies = new Map();
        for (const value of values) frequencies.set(String(value), (frequencies.get(String(value)) || 0) + 1);
        return {
          field_path: fieldPath,
          rows_with_value: values.length,
          rows_missing_value: Math.max(0, rows.length - values.length),
          top_values: Array.from(frequencies.entries()).sort((a, b) => b[1] - a[1]).slice(0, 10).map(([value, count]) => ({ value, count })),
        };
      });
    }
    return summaries;
  }

  function patchInsight(nodeId, node, payload) {
    const { workspace, table } = loadInsightWorkspace(nodeId, node);
    validateRevision(workspace, payload && payload.base_revision);
    const requirementId = String(payload.requirement_id || '');
    const block = (workspace.blocks || []).find(item => item.requirement_id === requirementId);
    if (!block) throw new CollaborationError(400, 'insight_requirement_not_found');
    let bindings = Array.isArray(payload.evidence_bindings) ? payload.evidence_bindings.map(item => ({ ...item })) : block.evidence_bindings || [];
    validateEvidenceBindings(bindings, table);
    if (payload.agent_proposal && typeof payload.agent_proposal === 'object') {
      block.pending_agent_proposals = [...(block.pending_agent_proposals || []), {
        ...clone(payload.agent_proposal),
        proposal_id: String(payload.agent_proposal.proposal_id || `insight-proposal-${Date.now()}`),
        status: 'pending',
        workspace_revision: workspace.revision,
        requires_human_application: true,
      }].slice(-20);
    }
    if (payload.proposal_id && payload.proposal_action) {
      const proposal = (block.pending_agent_proposals || []).find(item => item.proposal_id === payload.proposal_id && item.status === 'pending');
      if (!proposal) throw new CollaborationError(409, 'insight_proposal_not_pending');
      if (payload.proposal_action === 'apply') {
        validateEvidenceBindings(proposal.evidence_bindings || [], table);
        block.draft_text = String(proposal.proposed_text || '');
        bindings = clone(proposal.evidence_bindings || []);
        proposal.status = 'applied';
        proposal.applied_at = new Date().toISOString();
      } else if (payload.proposal_action === 'reject') {
        proposal.status = 'rejected';
        proposal.rejected_at = new Date().toISOString();
      } else {
        throw new CollaborationError(400, 'insight_proposal_action_invalid');
      }
    }
    if (payload.draft_text !== undefined) block.draft_text = String(payload.draft_text || '');
    block.evidence_bindings = bindings;
    if (Array.isArray(payload.risks)) block.risks = payload.risks.map(String);
    if (Array.isArray(payload.questions_for_user)) block.questions_for_user = payload.questions_for_user.map(String);
    block.status = String(block.draft_text || '').trim() ? 'draft_ready' : 'not_started';
    block.human_confirmation = { ...(block.human_confirmation || {}), status: 'unconfirmed', confirmed_by: '', confirmed_at: '' };
    workspace.table_revision = table.workspace.revision;
    workspace.revision = Number(workspace.revision || 0) + 1;
    workspace.updated_at = new Date().toISOString();
    atomicWriteJson(insightPath(nodeId), workspace);
    return insightResponse(nodeId, node);
  }

  function confirmInsight(nodeId, node, payload) {
    const { workspace, table } = loadInsightWorkspace(nodeId, node);
    validateRevision(workspace, payload && payload.base_revision);
    const block = (workspace.blocks || []).find(item => item.requirement_id === String(payload.requirement_id || ''));
    if (!block) throw new CollaborationError(400, 'insight_requirement_not_found');
    if (String(block.status || '') === 'stale' || String(block.human_confirmation && block.human_confirmation.status || '') === 'stale') {
      throw new CollaborationError(409, 'insight_stale');
    }
    validateEvidenceBindings(block.evidence_bindings || [], table);
    if (!Array.isArray(block.evidence_bindings) || block.evidence_bindings.length === 0) {
      throw new CollaborationError(409, 'evidence_required');
    }
    if (!String(block.draft_text || '').trim()) throw new CollaborationError(409, 'insight_draft_required');
    block.status = 'confirmed';
    block.human_confirmation = {
      status: 'confirmed',
      confirmed_by: String(payload.confirmed_by || 'local_user'),
      confirmed_at: new Date().toISOString(),
    };
    workspace.table_revision = table.workspace.revision;
    workspace.revision = Number(workspace.revision || 0) + 1;
    workspace.updated_at = new Date().toISOString();
    atomicWriteJson(insightPath(nodeId), workspace);
    return { ...insightResponse(nodeId, node), block };
  }

  function createThread(nodeId) {
    const now = new Date().toISOString();
    return {
      schema_version: 'analysis-collaboration-thread-v1',
      node_id: nodeId,
      revision: 0,
      messages: [],
      agent_calls: [],
      agent_batches: [],
      preferred_model: String(defaultAgentModel || DEFAULT_AGENT_MODEL),
      model_updated_at: now,
      model_updated_by: 'runtime_default',
      active_context_message_id: '',
      active_requirement_id: '',
      created_at: now,
      updated_at: now,
    };
  }

  function loadThread(nodeId) {
    let thread = readJson(threadPath(nodeId));
    if (!thread || thread.schema_version !== 'analysis-collaboration-thread-v1') {
      thread = createThread(nodeId);
      atomicWriteJson(threadPath(nodeId), thread);
      return thread;
    }
    const messages = Array.isArray(thread.messages) ? thread.messages.slice(-THREAD_MESSAGE_LIMIT) : [];
    const agentCalls = Array.isArray(thread.agent_calls) ? thread.agent_calls.slice(-THREAD_AGENT_CALL_LIMIT) : [];
    const agentBatches = Array.isArray(thread.agent_batches) ? thread.agent_batches.slice(-THREAD_AGENT_BATCH_LIMIT) : [];
    const preferredModel = String(thread.preferred_model || defaultAgentModel || DEFAULT_AGENT_MODEL);
    if (messages.length !== (thread.messages || []).length
      || agentCalls.length !== (thread.agent_calls || []).length
      || agentBatches.length !== (thread.agent_batches || []).length
      || preferredModel !== thread.preferred_model) {
      thread = {
        ...thread,
        messages,
        agent_calls: agentCalls,
        agent_batches: agentBatches,
        preferred_model: preferredModel,
        model_updated_at: thread.model_updated_at || new Date().toISOString(),
        model_updated_by: thread.model_updated_by || 'runtime_default',
        updated_at: new Date().toISOString(),
      };
      atomicWriteJson(threadPath(nodeId), thread);
    }
    return thread;
  }

  function appendThreadHistory(nodeId, record) {
    const filePath = threadHistoryPath(nodeId);
    const history = readJson(filePath, {
      schema_version: 'analysis-collaboration-thread-history-v1',
      node_id: nodeId,
      records: [],
    });
    history.records = [...(history.records || []), record].slice(-500);
    history.updated_at = new Date().toISOString();
    atomicWriteJson(filePath, history);
  }

  function writeThread(nodeId, thread, historyRecord) {
    const next = {
      ...thread,
      schema_version: 'analysis-collaboration-thread-v1',
      node_id: nodeId,
      revision: Number(thread.revision || 0) + 1,
      messages: (thread.messages || []).slice(-THREAD_MESSAGE_LIMIT),
      agent_calls: (thread.agent_calls || []).slice(-THREAD_AGENT_CALL_LIMIT),
      agent_batches: (thread.agent_batches || []).slice(-THREAD_AGENT_BATCH_LIMIT),
      updated_at: new Date().toISOString(),
    };
    if (!next.created_at) next.created_at = next.updated_at;
    atomicWriteJson(threadPath(nodeId), next);
    if (historyRecord) {
      appendThreadHistory(nodeId, {
        event_id: `thread-event-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        created_at: new Date().toISOString(),
        thread_revision: next.revision,
        ...clone(historyRecord),
      });
    }
    return next;
  }

  function threadResponse(nodeId) {
    return { ok: true, thread: loadThread(nodeId) };
  }

  function setThreadModel(nodeId, payload) {
    const preferredModel = String(payload && payload.preferred_model || '').trim();
    if (!preferredModel) throw new CollaborationError(400, 'preferred_model_required');
    const thread = loadThread(nodeId);
    thread.preferred_model = preferredModel;
    thread.model_updated_at = new Date().toISOString();
    thread.model_updated_by = String(payload && payload.updated_by || 'user');
    const next = writeThread(nodeId, thread, {
      action: 'set_preferred_model',
      preferred_model: preferredModel,
      updated_by: thread.model_updated_by,
    });
    return { ok: true, thread: next };
  }

  function safeProductContext(row, rowMeta) {
    const productNameKeys = ['商品名', '商品名称', 'goods_name', 'product_name', 'item_name'];
    const productIdKeys = ['goods_id', 'commodity_id', 'item_id', 'product_id'];
    const productName = productNameKeys.map(key => row && row[key]).find(nonEmpty);
    const productId = productIdKeys.map(key => row && row[key]).find(nonEmpty) || rowMeta && rowMeta.source_identity;
    return {
      product_name: nonEmpty(productName) ? String(productName) : '',
      product_id: nonEmpty(productId) ? String(productId) : '',
    };
  }

  function safeKeywordContext(row, rowMeta) {
    const keyword = String(row && (row.keyword ?? row.keywords) || '').trim();
    return { keyword };
  }

  function cellContextRef(nodeId, rowId, fieldPath) {
    const table = workspaceResponse(nodeId);
    const sourceTable = baseTable(nodeId);
    const fields = new Set((table.effective_fields || []).map(fieldPathOf));
    if (!fields.has(fieldPath)) throw new CollaborationError(400, 'field_not_found', { field_path: fieldPath });
    const rowIndex = (table.workspace.row_meta || []).findIndex(item => String(item.row_id || '') === rowId);
    if (rowIndex < 0) throw new CollaborationError(400, 'row_not_found', { row_id: rowId });
    const row = table.effective_rows[rowIndex] || {};
    const rowMeta = table.workspace.row_meta[rowIndex] || {};
    const override = table.workspace.cell_overrides && table.workspace.cell_overrides[rowId]
      ? table.workspace.cell_overrides[rowId][fieldPath]
      : null;
    const effectiveValue = Object.prototype.hasOwnProperty.call(row, fieldPath) ? row[fieldPath] : '';
    const product = safeProductContext(row, rowMeta);
    const keyword = safeKeywordContext(row, rowMeta);
    const fieldSource = (Array.isArray(sourceTable.field_sources) ? sourceTable.field_sources : []).find(item => {
      const candidate = String(item && (item.field_name || item.title || item.field_path) || '');
      return candidate === fieldPath || String(item && item.field_path || '') === fieldPath;
    }) || {};
    const derivedField = (Array.isArray(sourceTable.derived_fields) ? sourceTable.derived_fields : []).find(item => {
      const candidate = String(item && (item.field_name || item.title || item.field_path) || '');
      return candidate === fieldPath || String(item && item.field_path || '') === fieldPath;
    }) || {};
    const evidenceRefs = Array.from(new Set([
      ...(override && Array.isArray(override.evidence_refs) ? override.evidence_refs.map(String) : []),
      String(fieldSource.evidence_ref || ''),
      ...(Array.isArray(fieldSource.evidence_refs) ? fieldSource.evidence_refs.map(String) : []),
    ].filter(Boolean)));
    const relatedFieldNames = new Set([
      '商品名', '商品名称', 'goods_name', 'product_name',
      '材质', 'core_material',
      '场景', 'usage_scene',
      '主卖点', '卖点总结', 'selling_point_summary',
      '商品规格', '规格', 'goods_spec_params',
      '商品主图', 'goods_img',
      'keyword', 'keywords', 'search_popularity', 'growth_rate', 'competition_index',
      'click_rate', 'conversion_rate',
    ]);
    for (const evidencePath of [
      ...(Array.isArray(fieldSource.evidence_field_paths) ? fieldSource.evidence_field_paths : []),
      ...(Array.isArray(derivedField.evidence_field_paths) ? derivedField.evidence_field_paths : []),
      ...(Array.isArray(derivedField.available_evidence_fields) ? derivedField.available_evidence_fields : []),
    ]) {
      const leaf = String(evidencePath || '').replace(/\[\]/g, '').split('.').pop();
      if (leaf) relatedFieldNames.add(leaf);
    }
    const evidenceValues = {};
    for (const [key, value] of Object.entries(row || {})) {
      if (key === fieldPath || !relatedFieldNames.has(key) || !nonEmpty(value)) continue;
      evidenceValues[key] = value;
    }
    return {
      context_type: 'cell_context',
      row_id: rowId,
      field_path: fieldPath,
      effective_value: effectiveValue,
      original_value: override ? override.original_value : effectiveValue,
      source_kind: override && override.source_kind ? override.source_kind : (nonEmpty(effectiveValue) ? 'api' : 'missing'),
      source_api_id: String(fieldSource.source_api_id || ''),
      source_field_path: String(fieldSource.source_field_path || fieldSource.api_field_path || ''),
      value_status: String(fieldSource.value_status || ''),
      related_evidence_fields: Array.from(new Set([
        ...(Array.isArray(fieldSource.evidence_field_paths) ? fieldSource.evidence_field_paths.map(String) : []),
        ...(Array.isArray(derivedField.evidence_field_paths) ? derivedField.evidence_field_paths.map(String) : []),
        ...(Array.isArray(derivedField.available_evidence_fields) ? derivedField.available_evidence_fields.map(String) : []),
      ].filter(Boolean))),
      evidence_refs: evidenceRefs,
      evidence_values: evidenceValues,
      ...product,
      ...keyword,
    };
  }

  function attachThreadContext(nodeId, payload) {
    if (String(payload && payload.context_type || '') !== 'cell_context') {
      throw new CollaborationError(400, 'context_type_invalid');
    }
    const rowId = String(payload.row_id || '');
    const fieldPath = String(payload.field_path || '');
    const contextRef = cellContextRef(nodeId, rowId, fieldPath);
    const table = workspaceResponse(nodeId);
    const thread = loadThread(nodeId);
    const message = {
      message_id: `context-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      role: 'context',
      text: `已加入对话：${contextRef.product_name || contextRef.product_id || rowId} · ${fieldPath}`,
      intent: 'cell_context',
      context_refs: [contextRef],
      table_revision: Number(table.workspace.revision || 0),
      created_at: new Date().toISOString(),
    };
    thread.messages = [...(thread.messages || []), message];
    thread.active_context_message_id = message.message_id;
    thread.active_requirement_id = '';
    const next = writeThread(nodeId, thread, { action: 'attach_context', message });
    return { ok: true, thread: next, attached_context: contextRef };
  }

  function threadConversationHistory(thread) {
    return (thread.messages || [])
      .slice(-THREAD_PI_HISTORY_LIMIT)
      .map(message => ({
        role: message.role === 'assistant' ? 'assistant' : 'user',
        content: String(message.text || ''),
        created_at: String(message.created_at || ''),
      }))
      .filter(item => item.content);
  }

  function modelResolutionStatus(requestedModel, actualModel) {
    return compareAgentModels(requestedModel, actualModel).status;
  }

  function callTimelineItem(stage, details = {}) {
    const labels = {
      context_prepared: '正在整理单元格证据',
      process_started: '已启动 PI Agent',
      agent_started: '已提交至首选模型',
      analyzing: 'Agent 正在分析证据',
      generating: '正在生成建议',
      first_text: '已收到首段内容',
      completed: '已完成',
      failed: '调用失败',
      timed_out: '调用超时',
      cancelled: '已停止',
    };
    return {
      stage,
      label: labels[stage] || stage,
      at: String(details.at || new Date().toISOString()),
      ...(details.actual_model ? { actual_model: String(details.actual_model) } : {}),
    };
  }

  function contextSnapshotForCall(prepared, requestedModel) {
    const refs = Array.isArray(prepared.userMessage.context_refs) ? prepared.userMessage.context_refs : [];
    const cell = refs[0] || {};
    return {
      intent: prepared.bridgeIntent,
      user_message: prepared.userMessage.text,
      row_id: String(cell.row_id || ''),
      product_id: String(cell.product_id || ''),
      product_name: String(cell.product_name || ''),
      target_field: String(cell.field_path || ''),
      current_value: cell.effective_value ?? '',
      api_original_value: cell.original_value ?? '',
      source_kind: String(cell.source_kind || ''),
      source_api_id: String(cell.source_api_id || ''),
      source_field_path: String(cell.source_field_path || ''),
      evidence_values: clone(cell.evidence_values || {}),
      evidence_refs: clone(cell.evidence_refs || []),
      related_evidence_fields: clone(cell.related_evidence_fields || []),
      requirement_id: String(prepared.requirementId || ''),
      requirement: prepared.requirement ? String(prepared.requirement.question || '') : '',
      table_revision: Number(prepared.table.workspace.revision || 0),
      requested_model: requestedModel,
    };
  }

  function notifyAgentCall(nodeId, call) {
    try {
      onAgentCallEvent('agent_call_update', { node_id: nodeId, call: clone(call) });
    } catch {
      // Observability transport must not break persisted collaboration state.
    }
  }

  function updateAgentCall(nodeId, callId, updater) {
    const thread = loadThread(nodeId);
    const call = (thread.agent_calls || []).find(item => item.call_id === callId);
    if (!call) throw new CollaborationError(404, 'agent_call_not_found', { call_id: callId });
    updater(call);
    call.updated_at = new Date().toISOString();
    const next = writeThread(nodeId, thread);
    const saved = (next.agent_calls || []).find(item => item.call_id === callId) || call;
    notifyAgentCall(nodeId, saved);
    return saved;
  }

  function recordAgentCallEvent(nodeId, callId, event) {
    return updateAgentCall(nodeId, callId, call => {
      const stage = String(event && event.stage || '');
      if (!stage) return;
      const onceStages = new Set(['context_prepared', 'process_started', 'agent_started', 'analyzing', 'generating', 'first_text', 'completed', 'failed', 'timed_out', 'cancelled']);
      const alreadyRecorded = (call.timeline || []).some(item => item.stage === stage);
      if (!alreadyRecorded || !onceStages.has(stage)) call.timeline.push(callTimelineItem(stage, event));
      call.event_count = Number(call.event_count || 0) + 1;
      if (['process_started', 'agent_started', 'analyzing', 'generating', 'first_text'].includes(stage)) call.status = 'running';
      if (event.actual_model) {
        call.actual_model = String(event.actual_model);
        const comparison = compareAgentModels(call.requested_model, call.actual_model);
        call.model_resolution_status = comparison.status;
        call.model_comparison_reason = comparison.reason;
      }
      if (stage === 'process_started') call.process_started_at = String(event.at || new Date().toISOString());
      if (stage === 'agent_started') call.agent_started_at = String(event.at || new Date().toISOString());
      if (stage === 'first_text' && !call.first_token_at) call.first_token_at = String(event.at || new Date().toISOString());
    });
  }

  function prepareThreadQuery(nodeId, node, payload) {
    const text = String(payload && payload.message || '').trim();
    if (!text) throw new CollaborationError(400, 'message_required');
    let thread = loadThread(nodeId);
    const table = workspaceResponse(nodeId);
    const insight = insightResponse(nodeId, node);
    const requirementId = String(payload.requirement_id || thread.active_requirement_id || '');
    const requirement = requirementId
      ? (insight.workspace.blocks || []).find(item => item.requirement_id === requirementId)
      : null;
    if (requirementId && !requirement) throw new CollaborationError(400, 'insight_requirement_not_found');
    const activeContextId = String(thread.active_context_message_id || '');
    const contextMessage = requirement || !activeContextId ? null : threadMessage(thread, activeContextId);
    const intent = requirement ? 'insight_requirement' : contextMessage ? 'cell_context' : 'free_chat';
    const userMessage = {
      message_id: `user-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      role: 'user',
      text,
      intent,
      requirement_id: requirementId,
      context_refs: contextMessage ? clone(contextMessage.context_refs || []) : [],
      table_revision: Number(table.workspace.revision || 0),
      created_at: new Date().toISOString(),
    };

    let tableSelection = {};
    if (contextMessage) {
      const refs = (contextMessage.context_refs || []).map(item => cellContextRef(nodeId, String(item.row_id || ''), String(item.field_path || '')));
      userMessage.context_refs = refs;
      tableSelection = { scope_mode: 'cells', cells: refs };
    }
    const bridgeIntent = requirement ? 'insight_collaboration' : contextMessage ? 'table_edit_advice' : 'free_chat';
    const selectedRowIds = new Set(contextMessage
      ? userMessage.context_refs.map(item => String(item && item.row_id || '')).filter(Boolean)
      : []);
    const agentRows = (table.effective_rows || [])
      .map((row, index) => ({ row_id: String(table.workspace.row_meta?.[index]?.row_id || ''), ...row }))
      .filter(row => selectedRowIds.size === 0 || selectedRowIds.has(row.row_id))
      .slice(0, 100);
    const agentWorkspace = selectedRowIds.size === 0
      ? table.workspace
      : {
          ...table.workspace,
          row_meta: (table.workspace.row_meta || []).filter(item => selectedRowIds.has(String(item && item.row_id || ''))),
          cell_overrides: Object.fromEntries(Object.entries(table.workspace.cell_overrides || {})
            .filter(([rowId]) => selectedRowIds.has(String(rowId)))),
        };
    const requestedModel = String(thread.preferred_model || payload.model || defaultAgentModel || DEFAULT_AGENT_MODEL);
    const agentPayload = {
      ...payload,
      model: requestedModel,
      node_id: nodeId,
      intent: bridgeIntent,
      message: text,
      conversation_history: threadConversationHistory(thread),
      analysis_node_view: node.analysis_node_view || {},
      table_workspace: agentWorkspace,
      table_selection: tableSelection,
      selected_requirement: requirement || {},
      evidence_summary: requirement ? { [requirementId]: insight.evidence_summary[requirementId] || [] } : {},
      data_table_draft: { fields: table.effective_fields || [], rows: agentRows },
    };
    const prepared = { nodeId, node, payload, thread, table, insight, requirementId, requirement, contextMessage, intent, userMessage, bridgeIntent, agentPayload };
    const callId = `call-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const now = new Date().toISOString();
    const call = {
      call_id: callId,
      parent_call_id: String(payload.parent_call_id || ''),
      intent: bridgeIntent,
      status: 'preparing',
      requested_model: requestedModel,
      actual_model: '',
      model_resolution_status: 'unknown',
      model_comparison_reason: 'unknown',
      context_snapshot: contextSnapshotForCall(prepared, requestedModel),
      timeline: [callTimelineItem('context_prepared', { at: now })],
      started_at: now,
      process_started_at: '',
      agent_started_at: '',
      first_token_at: '',
      finished_at: '',
      duration_ms: 0,
      event_count: 1,
      failure_reason: '',
      partial_output: '',
      created_at: now,
      updated_at: now,
    };
    userMessage.call_id = callId;
    thread.messages = [...(thread.messages || []), userMessage];
    thread.agent_calls = [...(thread.agent_calls || []), call];
    thread = writeThread(nodeId, thread, { action: 'start_agent_call', message: userMessage, call });
    notifyAgentCall(nodeId, call);
    return { ...prepared, thread, callId };
  }

  async function executeThreadQuery(prepared, callAgent) {
    const { nodeId, node, callId, contextMessage, requirement, requirementId, intent, userMessage, table, agentPayload } = prepared;
    const agentResponse = await callAgent(node, agentPayload, {
      call_id: callId,
      on_event: event => recordAgentCallEvent(nodeId, callId, event),
    });
    const tableProposal = agentResponse && agentResponse.ok && agentResponse.advice && agentResponse.advice.table_edit_proposal;
    const insightProposal = agentResponse && agentResponse.ok && agentResponse.advice && agentResponse.advice.insight_collaboration_proposal;
    const proposal = requirement ? insightProposal : contextMessage ? tableProposal : null;
    const summary = proposal && (proposal.summary || proposal.proposed_text)
      || agentResponse && agentResponse.ok && agentResponse.advice && agentResponse.advice.summary && agentResponse.advice.summary.text
      || agentResponse && agentResponse.ok && agentResponse.response_text
      || `Agent 调用未完成：${agentResponse && agentResponse.reason || 'unknown'}`;
    const finishedAt = new Date().toISOString();
    const callStatus = agentResponse && agentResponse.ok
      ? 'completed'
      : agentResponse && agentResponse.reason === 'pi_rpc_timeout'
        ? 'timed_out'
        : agentResponse && agentResponse.reason === 'pi_cancelled'
          ? 'cancelled'
          : 'failed';
    const terminalStage = callStatus === 'completed' ? 'completed' : callStatus === 'timed_out' ? 'timed_out' : callStatus === 'cancelled' ? 'cancelled' : 'failed';
    const call = updateAgentCall(nodeId, callId, item => {
      if (!(item.timeline || []).some(entry => entry.stage === terminalStage)) item.timeline.push(callTimelineItem(terminalStage, { at: finishedAt }));
      item.status = callStatus;
      item.finished_at = finishedAt;
      item.duration_ms = Number(agentResponse && agentResponse.duration_ms || Math.max(0, Date.parse(finishedAt) - Date.parse(item.started_at)));
      item.failure_reason = agentResponse && agentResponse.ok ? '' : String(agentResponse && agentResponse.reason || 'pi_rpc_failed');
      item.partial_output = agentResponse && agentResponse.ok ? '' : String(agentResponse && agentResponse.response_text || '');
      item.actual_model = String(agentResponse && agentResponse.actual_model || item.actual_model || '');
      const comparison = compareAgentModels(item.requested_model, item.actual_model);
      item.model_resolution_status = comparison.status;
      item.model_comparison_reason = comparison.reason;
    });
    const assistantMessage = {
      message_id: `assistant-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      role: 'assistant',
      text: String(summary || ''),
      intent,
      requirement_id: requirementId,
      context_refs: contextMessage ? clone(userMessage.context_refs || []) : [],
      table_revision: Number(table.workspace.revision || 0),
      proposal: proposal ? clone(proposal) : null,
      proposal_status: proposal ? 'pending' : 'none',
      agent_status: String(agentResponse && agentResponse.status || ''),
      failure_reason: agentResponse && agentResponse.ok ? '' : String(agentResponse && agentResponse.reason || 'pi_rpc_failed'),
      call_id: callId,
      requested_model: call.requested_model,
      actual_model: call.actual_model,
      model_resolution_status: call.model_resolution_status,
      model_comparison_reason: call.model_comparison_reason,
      duration_ms: call.duration_ms,
      evidence_ref: String(agentResponse && agentResponse.evidence_ref || ''),
      created_at: new Date().toISOString(),
    };
    let thread = loadThread(nodeId);
    thread.messages = [...(thread.messages || []), assistantMessage];
    thread.active_context_message_id = '';
    thread.active_requirement_id = requirementId;
    thread = writeThread(nodeId, thread, { action: 'append_assistant_message', message: assistantMessage, call_id: callId });
    return { ok: true, thread, agent_response: agentResponse, call };
  }

  async function queryThread(nodeId, node, payload, callAgent) {
    return executeThreadQuery(prepareThreadQuery(nodeId, node, payload), callAgent);
  }

  function startThreadQuery(nodeId, node, payload, callAgent) {
    const prepared = prepareThreadQuery(nodeId, node, payload);
    const task = executeThreadQuery(prepared, callAgent);
    return {
      response: { ok: true, status: 'accepted', call_id: prepared.callId, thread: prepared.thread },
      task,
    };
  }

  function agentCallResponse(nodeId, callId) {
    const thread = loadThread(nodeId);
    const call = (thread.agent_calls || []).find(item => item.call_id === callId);
    if (!call) throw new CollaborationError(404, 'agent_call_not_found', { call_id: callId });
    return { ok: true, call: clone(call) };
  }

  function appendBatchHistory(nodeId, record) {
    const filePath = batchHistoryPath(nodeId);
    const history = readJson(filePath, {
      schema_version: 'analysis-agent-batch-history-v1',
      node_id: nodeId,
      records: [],
    });
    history.records = [...(history.records || []), {
      event_id: `batch-event-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      created_at: new Date().toISOString(),
      ...clone(record),
    }].slice(-500);
    history.updated_at = new Date().toISOString();
    atomicWriteJson(filePath, history);
  }

  function batchSummary(batch) {
    return {
      batch_id: batch.batch_id,
      schema_version: batch.schema_version,
      status: batch.status,
      subject_kind: String(batch.subject_kind || 'product'),
      requested_model: batch.requested_model,
      base_revision: batch.base_revision,
      base_execution_id: String(batch.base_execution_id || ''),
      freshness_status: String(batch.freshness_status || 'current'),
      stale_reason: String(batch.stale_reason || ''),
      page: clone(batch.page || {}),
      progress: clone(batch.progress || {}),
      started_at: batch.started_at,
      finished_at: batch.finished_at || '',
      updated_at: batch.updated_at,
    };
  }

  function persistAgentBatch(nodeId, batch, historyRecord = null) {
    batch.updated_at = new Date().toISOString();
    atomicWriteJson(batchPath(nodeId, batch.batch_id), batch);
    let thread = loadThread(nodeId);
    const summaries = Array.isArray(thread.agent_batches) ? [...thread.agent_batches] : [];
    const index = summaries.findIndex(item => item.batch_id === batch.batch_id);
    if (index >= 0) summaries[index] = batchSummary(batch);
    else summaries.push(batchSummary(batch));
    thread.agent_batches = summaries.slice(-THREAD_AGENT_BATCH_LIMIT);
    thread = writeThread(nodeId, thread);
    if (historyRecord) appendBatchHistory(nodeId, { batch_id: batch.batch_id, ...historyRecord });
    try {
      onAgentCallEvent('agent_batch_update', {
        node_id: nodeId,
        batch: decorateAgentBatchFreshness(nodeId, batch),
      });
    } catch {
      // Observability transport must not break persisted batch state.
    }
    return { batch, thread };
  }

  function storedAgentBatch(nodeId, batchId) {
    const batch = readJson(batchPath(nodeId, batchId));
    if (!batch || batch.schema_version !== 'analysis-agent-batch-v1') {
      throw new CollaborationError(404, 'agent_batch_not_found', { batch_id: batchId });
    }
    return batch;
  }

  function agentBatchFreshness(nodeId, batch, workspace = null) {
    const currentWorkspace = workspace || loadWorkspace(nodeId).workspace;
    const baseRevision = Number(batch.base_revision || 0);
    const currentRevision = Number(currentWorkspace.revision || 0);
    const baseExecutionId = String(batch.base_execution_id || '');
    const currentExecutionId = String(currentWorkspace.base_execution_id || '');
    let staleReason = '';
    if (baseExecutionId && baseExecutionId !== currentExecutionId) {
      staleReason = 'source_execution_changed';
    } else if (baseRevision !== currentRevision) {
      staleReason = 'workspace_revision_changed';
    }
    return {
      freshness_status: staleReason ? 'stale' : 'current',
      stale_reason: staleReason,
      base_revision: baseRevision,
      current_revision: currentRevision,
      base_execution_id: baseExecutionId,
      current_execution_id: currentExecutionId,
    };
  }

  function decorateAgentBatchFreshness(nodeId, batch, workspace = null) {
    const decorated = clone(batch);
    const freshness = agentBatchFreshness(nodeId, decorated, workspace);
    Object.assign(decorated, freshness);
    if (freshness.freshness_status !== 'stale') return decorated;
    decorated.previous_status = String(
      decorated.previous_status || (decorated.status === 'stale' ? '' : decorated.status) || 'unknown'
    );
    decorated.status = 'stale';
    decorated.public_stage = '批次数据已变化，仅保留审计记录';
    decorated.proposals = (decorated.proposals || []).map(proposal => (
      proposal.status === 'pending' ? { ...proposal, status: 'stale' } : proposal
    ));
    decorated.items = (decorated.items || []).map(item => (
      ['queued', 'running'].includes(String(item.status || ''))
        ? { ...item, status: 'failed', failure_reason: 'source_revision_changed' }
        : item
    ));
    return decorated;
  }

  function agentBatchResponse(nodeId, batchId) {
    return { ok: true, batch: decorateAgentBatchFreshness(nodeId, storedAgentBatch(nodeId, batchId)) };
  }

  function throwAgentBatchStale(batch) {
    throw new CollaborationError(409, 'agent_batch_stale', {
      stale_reason: String(batch.stale_reason || 'workspace_revision_changed'),
      base_revision: Number(batch.base_revision || 0),
      current_revision: Number(batch.current_revision || 0),
      base_execution_id: String(batch.base_execution_id || ''),
      current_execution_id: String(batch.current_execution_id || ''),
    });
  }

  function updateAgentBatch(nodeId, batchId, updater, historyRecord = null) {
    const batch = clone(storedAgentBatch(nodeId, batchId));
    updater(batch);
    persistAgentBatch(nodeId, batch, historyRecord);
    return batch;
  }

  function derivedFieldCatalog(table) {
    const fields = new Map();
    for (const item of Array.isArray(table.derived_fields) ? table.derived_fields : []) {
      const name = fieldPathOf(item);
      if (name) fields.set(name, item);
    }
    for (const item of Array.isArray(table.field_sources) ? table.field_sources : []) {
      const name = fieldPathOf(item);
      const agentFillable = String(item.source_kind || '') === 'pi_derived'
        || String(item.value_status || '') === 'pi_derived_unconfirmed'
        || String(item.mapping_status || '') === 'derived_or_manual_required';
      if (name && agentFillable && !fields.has(name)) fields.set(name, item);
    }
    return fields;
  }

  function evidenceNamesForField(fieldPath, definition) {
    const aliases = {
      core_material: ['core_material', '材质'],
      usage_scene: ['usage_scene', '场景'],
      selling_point_summary: ['selling_point_summary', '卖点总结', '主卖点'],
      goods_spec_params: ['goods_spec_params', '商品规格', '规格'],
      goods_name: ['goods_name', '商品名', '商品名称'],
      goods_img: ['goods_img', '商品主图'],
    };
    const names = new Set([
      '商品名', '商品名称', 'goods_name', '材质', 'core_material', '场景', 'usage_scene',
      '主卖点', '卖点总结', 'selling_point_summary', '商品规格', '规格', 'goods_spec_params',
      'speed_type', '趋势类型',
    ]);
    const paths = [
      ...(Array.isArray(definition && definition.evidence_field_paths) ? definition.evidence_field_paths : []),
      ...(Array.isArray(definition && definition.available_evidence_fields) ? definition.available_evidence_fields : []),
    ];
    for (const pathValue of paths) {
      const leaf = String(pathValue || '').replace(/\[\]/g, '').split('.').pop();
      if (!leaf) continue;
      names.add(leaf);
      for (const alias of aliases[leaf] || []) names.add(alias);
    }
    names.delete(fieldPath);
    return names;
  }

  function batchEvidenceValues(row, targetFields, definitions, subjectKind = 'product') {
    const explicitNames = new Set();
    for (const fieldPath of targetFields) {
      for (const name of evidenceNamesForField(fieldPath, definitions.get(fieldPath))) explicitNames.add(name);
    }
    if (subjectKind === 'keyword') {
      for (const name of [
        'keyword', 'keywords', 'search_popularity', 'growth_rate', 'competition_index',
        'click_rate', 'conversion_rate',
      ]) explicitNames.add(name);
    }
    const values = {};
    for (const [key, value] of Object.entries(row || {})) {
      if (targetFields.includes(key) || !nonEmpty(value) || !explicitNames.has(key)) continue;
      values[key] = value;
    }
    if (Object.keys(values).length === 0) {
      for (const [key, value] of Object.entries(row || {})) {
        if (targetFields.includes(key) || !nonEmpty(value) || API_FACT_FIELDS.has(key)) continue;
        values[key] = value;
        if (Object.keys(values).length >= 20) break;
      }
    }
    return values;
  }

  function prepareAgentBatch(nodeId, node, payload) {
    const tablePayload = workspaceResponse(nodeId);
    const workspace = tablePayload.workspace;
    validateRevision(workspace, payload && payload.base_revision);
    const pageSize = Number(payload && payload.page_size || AGENT_BATCH_PAGE_SIZE);
    if (pageSize !== AGENT_BATCH_PAGE_SIZE) throw new CollaborationError(400, 'agent_batch_page_size_invalid', { page_size: AGENT_BATCH_PAGE_SIZE });
    const pageNumber = Number(payload && payload.page_number || 1);
    if (!Number.isInteger(pageNumber) || pageNumber < 1) throw new CollaborationError(400, 'agent_batch_page_invalid');
    const start = (pageNumber - 1) * pageSize;
    const rows = (tablePayload.effective_rows || []).slice(start, start + pageSize);
    const rowMeta = (workspace.row_meta || []).slice(start, start + pageSize);
    if (rows.length === 0) throw new CollaborationError(400, 'agent_batch_page_empty');
    const sourceTable = baseTable(nodeId);
    const definitions = derivedFieldCatalog(sourceTable);
    const fieldNames = (tablePayload.effective_fields || []).map(fieldPathOf).filter(Boolean);
    const subjectKind = String(tablePayload.agent_enrichment && tablePayload.agent_enrichment.subject_kind || 'product');
    const fillable = new Set(tablePayload.agent_enrichment && Array.isArray(tablePayload.agent_enrichment.fillable_fields)
      ? tablePayload.agent_enrichment.fillable_fields.map(String)
      : [...definitions.keys(), ...fieldNames.filter(name => AGENT_FILLABLE_FIELDS.has(name))]);
    const thread = loadThread(nodeId);
    const running = (thread.agent_batches || []).find(item => {
      if (!['preparing', 'running'].includes(String(item.status || ''))) return false;
      try {
        return agentBatchResponse(nodeId, String(item.batch_id || '')).batch.freshness_status === 'current';
      } catch {
        return false;
      }
    });
    if (running) throw new CollaborationError(409, 'agent_batch_already_running', { batch_id: running.batch_id });
    const requestedModel = String(thread.preferred_model || defaultAgentModel || DEFAULT_AGENT_MODEL);
    const items = [];
    for (let index = 0; index < rows.length; index += 1) {
      const row = rows[index] || {};
      const meta = rowMeta[index] || {};
      const rowId = String(meta.row_id || '');
      const targetFields = fieldNames.filter(fieldPath => fillable.has(fieldPath)
        && !API_FACT_FIELDS.has(fieldPath)
        && !nonEmpty(row[fieldPath]));
      if (targetFields.length === 0) continue;
      const evidenceValues = batchEvidenceValues(row, targetFields, definitions, subjectKind);
      const evidenceRefs = Array.from(new Set(targetFields.flatMap(fieldPath => {
        const source = (sourceTable.field_sources || []).find(item => fieldPathOf(item) === fieldPath) || {};
        return [String(source.evidence_ref || ''), ...(Array.isArray(source.evidence_refs) ? source.evidence_refs.map(String) : [])];
      }).filter(Boolean)));
      items.push({
        item_id: `batch-item-${Date.now()}-${index}-${Math.random().toString(36).slice(2, 7)}`,
        row_id: rowId,
        row_index: start + index,
        product: safeProductContext(row, meta),
        keyword: safeKeywordContext(row, meta).keyword,
        subject_kind: subjectKind,
        status: Object.keys(evidenceValues).length > 0 ? 'queued' : 'no_evidence',
        target_fields: targetFields,
        evidence_values: evidenceValues,
        evidence_refs: evidenceRefs,
        call_id: '',
        requested_model: requestedModel,
        actual_model: '',
        model_resolution_status: 'unknown',
        model_comparison_reason: 'unknown',
        proposed_cells: 0,
        raw_patch_count: 0,
        accepted_patch_count: 0,
        rejected_patch_count: 0,
        proposal_status: '',
        proposal_risks: [],
        rejected_patch_refs: [],
        failure_reason: Object.keys(evidenceValues).length > 0 ? '' : 'no_evidence',
        started_at: '',
        finished_at: '',
        duration_ms: 0,
      });
    }
    const batchId = `batch-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const now = new Date().toISOString();
    const batch = {
      schema_version: 'analysis-agent-batch-v1',
      batch_id: batchId,
      node_id: nodeId,
      base_revision: Number(workspace.revision || 0),
      base_execution_id: String(workspace.base_execution_id || ''),
      freshness_status: 'current',
      stale_reason: '',
      current_revision: Number(workspace.revision || 0),
      current_execution_id: String(workspace.base_execution_id || ''),
      status: items.some(item => item.status === 'queued') ? 'preparing' : 'review_ready',
      subject_kind: subjectKind,
      requested_model: requestedModel,
      page: { number: pageNumber, size: pageSize, row_ids: rowMeta.map(item => String(item.row_id || '')).filter(Boolean) },
      progress: {},
      public_stage: '正在校验当前页',
      items,
      proposals: [],
      started_at: now,
      finished_at: items.some(item => item.status === 'queued') ? '' : now,
      updated_at: now,
    };
    recalculateBatchProgress(batch);
    persistAgentBatch(nodeId, batch, { action: 'batch_created', page: batch.page, progress: batch.progress });
    let nextThread = loadThread(nodeId);
    nextThread.messages = [...(nextThread.messages || []), {
      message_id: `batch-user-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      role: 'user',
      text: `发起当前页一键填充：第 ${pageNumber} 页，共 ${items.length} 个待补${subjectKind === 'keyword' ? '关键词' : '商品'}。`,
      intent: 'table_edit_batch',
      batch_id: batchId,
      table_revision: batch.base_revision,
      created_at: now,
    }];
    nextThread = writeThread(nodeId, nextThread, { action: 'start_agent_batch', batch_id: batchId });
    return { nodeId, node, batchId, thread: nextThread };
  }

  function recalculateBatchProgress(batch) {
    const items = Array.isArray(batch.items) ? batch.items : [];
    batch.progress = {
      eligible_products: items.length,
      completed_products: items.filter(item => item.status === 'completed').length,
      running_products: items.filter(item => item.status === 'running').length,
      failed_products: items.filter(item => item.status === 'failed').length,
      no_evidence_products: items.filter(item => item.status === 'no_evidence').length,
      cancelled_products: items.filter(item => item.status === 'cancelled').length,
      target_cells: items.reduce((sum, item) => sum + (item.target_fields || []).length, 0),
      proposed_cells: (batch.proposals || []).filter(item => item.status === 'pending').length,
      rejected_cells: items.reduce((sum, item) => sum + Number(item.rejected_patch_count || 0), 0),
    };
  }

  function agentPayloadForBatchItem(nodeId, node, batch, item) {
    const table = workspaceResponse(nodeId);
    const sourceTable = baseTable(nodeId);
    const row = table.effective_rows[item.row_index] || {};
    const meta = table.workspace.row_meta[item.row_index] || {};
    const cells = item.target_fields.map(fieldPath => ({
      context_type: 'cell_context',
      row_id: item.row_id,
      field_path: fieldPath,
      effective_value: row[fieldPath] ?? '',
      original_value: row[fieldPath] ?? '',
      source_kind: 'missing',
      evidence_values: clone(item.evidence_values || {}),
      evidence_refs: clone(item.evidence_refs || []),
      ...safeProductContext(row, meta),
      ...safeKeywordContext(row, meta),
    }));
    const scopedWorkspace = {
      ...table.workspace,
      row_meta: [clone(meta)],
      cell_overrides: table.workspace.cell_overrides[item.row_id]
        ? { [item.row_id]: clone(table.workspace.cell_overrides[item.row_id]) }
        : {},
    };
    const promptContext = {
      subject_kind: String(batch.subject_kind || item.subject_kind || 'product'),
      row_id: item.row_id,
      ...(String(batch.subject_kind || '') === 'keyword'
        ? {
            keyword: String(item.keyword || ''),
            category_context: clone(sourceTable.category_context || {}),
            demand_type_contract: Array.from(KEYWORD_DEMAND_TYPES),
          }
        : { product: item.product }),
      target_fields: item.target_fields,
      evidence_values: item.evidence_values,
      evidence_refs: item.evidence_refs,
      table_revision: batch.base_revision,
    };
    const keywordInstruction = String(batch.subject_kind || '') === 'keyword'
      ? '请基于当前关键词及其指标，同时生成 root_terms 和 demand_type。root_terms 必须是去重字符串数组；demand_type 必须是八类需求标准之一：品类需求、人群需求、属性需求、功能需求、场景需求、品牌需求、风格需求、定制需求。只允许修改当前行的 root_terms、demand_type。每个字段单独返回一个 patch，例如 {"row_id":"keyword:书桌垫","field_path":"root_terms","old_value":[],"new_value":["书桌","桌垫"],"reason":"关键词拆解","confidence":0.9,"evidence_refs":[]}。'
      : '请结合当前商品已有信息，补齐全部目标字段。';
    return {
      model: batch.requested_model,
      node_id: nodeId,
      intent: 'table_edit_advice',
      message: `${keywordInstruction}只返回有证据支持的简洁描述；证据不足则留空并说明原因。\n${JSON.stringify(promptContext, null, 2)}`,
      conversation_history: [],
      analysis_node_view: node.analysis_node_view || {},
      table_workspace: scopedWorkspace,
      table_selection: { scope_mode: 'cells', cells },
      selected_requirement: {},
      evidence_summary: {},
      batch_item_context: promptContext,
      data_table_draft: { fields: table.effective_fields || [], rows: [{ row_id: item.row_id, ...row }] },
    };
  }

  function normalizeKeywordRootTerms(value) {
    const values = Array.isArray(value)
      ? value
      : typeof value === 'string'
        ? value.split(/[，,、;；|\n]+/)
        : [];
    return Array.from(new Set(values
      .filter(item => typeof item === 'string')
      .map(item => item.trim())
      .filter(Boolean)));
  }

  async function executeAgentBatch(prepared, callAgent, itemIds = null) {
    const { nodeId, node, batchId } = prepared;
    let initial = agentBatchResponse(nodeId, batchId).batch;
    if (initial.freshness_status === 'stale') return { ok: true, batch: initial };
    const allowedIds = itemIds ? new Set(itemIds) : null;
    const queue = initial.items
      .filter(item => (!allowedIds || allowedIds.has(item.item_id)) && item.status === 'queued')
      .map(item => item.item_id);
    if (queue.length === 0) return agentBatchResponse(nodeId, batchId);
    updateAgentBatch(nodeId, batchId, batch => {
      batch.status = 'running';
      batch.public_stage = `正在构造${batch.subject_kind === 'keyword' ? '关键词' : '商品'}证据`;
      recalculateBatchProgress(batch);
    }, { action: 'batch_started' });
    const deadline = Date.now() + AGENT_BATCH_TIMEOUT_MS;
    let cursor = 0;
    const worker = async () => {
      while (cursor < queue.length) {
        if (agentBatchResponse(nodeId, batchId).batch.freshness_status === 'stale') return;
        const queueIndex = cursor;
        cursor += 1;
        const itemId = queue[queueIndex];
        if (Date.now() >= deadline) {
          updateAgentBatch(nodeId, batchId, batch => {
            const item = batch.items.find(candidate => candidate.item_id === itemId);
            if (item && item.status === 'queued') {
              item.status = 'failed';
              item.failure_reason = 'agent_batch_timeout';
              item.finished_at = new Date().toISOString();
            }
            recalculateBatchProgress(batch);
          });
          continue;
        }
        let itemSnapshot;
        const callId = `batch-call-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        updateAgentBatch(nodeId, batchId, batch => {
          const item = batch.items.find(candidate => candidate.item_id === itemId);
          if (!item || item.status !== 'queued') return;
          item.status = 'running';
          item.call_id = callId;
          item.started_at = new Date().toISOString();
          batch.public_stage = `正在处理${batch.subject_kind === 'keyword' ? '关键词' : '商品'} ${Math.min(queueIndex + 1, queue.length)}/${queue.length}`;
          recalculateBatchProgress(batch);
          itemSnapshot = clone(item);
        });
        if (!itemSnapshot) continue;
        const batchSnapshot = agentBatchResponse(nodeId, batchId).batch;
        if (batchSnapshot.freshness_status === 'stale') return;
        const response = await callAgent(node, agentPayloadForBatchItem(nodeId, node, batchSnapshot, itemSnapshot), { call_id: callId });
        if (agentBatchResponse(nodeId, batchId).batch.freshness_status === 'stale') return;
        updateAgentBatch(nodeId, batchId, batch => {
          const item = batch.items.find(candidate => candidate.item_id === itemId);
          if (!item || item.status === 'cancelled') return;
          const proposal = response && response.ok && response.advice && response.advice.table_edit_proposal;
          const patches = Array.isArray(proposal && proposal.patches) ? proposal.patches : [];
          const rawPatchCount = Number(proposal && proposal.raw_patch_count != null ? proposal.raw_patch_count : patches.length);
          const proposalRisks = Array.isArray(proposal && proposal.risks) ? proposal.risks.map(String) : [];
          const rejectedPatchRefs = Array.isArray(proposal && proposal.rejected_patch_refs)
            ? proposal.rejected_patch_refs.map(ref => ({
              row_id: String(ref && ref.row_id || ''),
              field_path: String(ref && ref.field_path || ''),
              reason: String(ref && ref.reason || 'rejected'),
              patch_keys: Array.isArray(ref && ref.patch_keys) ? ref.patch_keys.map(String) : [],
              patch_format: String(ref && ref.patch_format || ''),
              original_patch_keys: Array.isArray(ref && ref.original_patch_keys) ? ref.original_patch_keys.map(String) : [],
              normalized_field: String(ref && ref.normalized_field || ''),
              value_type: String(ref && ref.value_type || ''),
            }))
            : [];
          const patchDiagnostics = Array.isArray(proposal && proposal.patch_diagnostics)
            ? proposal.patch_diagnostics.map(diagnostic => ({
              status: String(diagnostic && diagnostic.status || ''),
              reason: String(diagnostic && diagnostic.reason || ''),
              patch_format: String(diagnostic && diagnostic.patch_format || ''),
              original_patch_keys: Array.isArray(diagnostic && diagnostic.original_patch_keys)
                ? diagnostic.original_patch_keys.map(String)
                : [],
              normalized_field: String(diagnostic && diagnostic.normalized_field || ''),
              value_type: String(diagnostic && diagnostic.value_type || ''),
            }))
            : [];
          const allowedFields = new Set(item.target_fields || []);
          const applicable = [];
          for (const patch of patches) {
            const fieldPath = String(patch.field_path || '');
            if (String(patch.row_id || '') !== item.row_id
              || !allowedFields.has(fieldPath)
              || nonEmpty(patch.old_value)
              || !nonEmpty(patch.new_value)) continue;
            if (batch.subject_kind === 'keyword' && fieldPath === 'root_terms') {
              const rootTerms = normalizeKeywordRootTerms(patch.new_value);
              if (rootTerms.length === 0) {
                proposalRisks.push('invalid_root_terms_rejected');
                continue;
              }
              applicable.push({ ...patch, new_value: rootTerms });
              continue;
            }
            if (batch.subject_kind === 'keyword' && fieldPath === 'demand_type'
              && !KEYWORD_DEMAND_TYPES.has(String(patch.new_value || '').trim())) {
              proposalRisks.push('invalid_demand_type_rejected');
              continue;
            }
            applicable.push(patch);
          }
          const proposalIds = [];
          for (const patch of applicable) {
            const proposalId = `batch-proposal-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
            proposalIds.push(proposalId);
            batch.proposals.push({
              proposal_id: proposalId,
              item_id: item.item_id,
              row_id: item.row_id,
              product_name: batch.subject_kind === 'keyword' ? item.keyword : item.product.product_name,
              product_id: batch.subject_kind === 'keyword' ? '' : item.product.product_id,
              keyword: batch.subject_kind === 'keyword' ? item.keyword : '',
              field_path: String(patch.field_path || ''),
              old_value: patch.old_value ?? '',
              new_value: patch.new_value,
              reason: String(patch.reason || ''),
              confidence: Number.isFinite(Number(patch.confidence)) ? Number(patch.confidence) : 0,
              evidence_refs: Array.isArray(patch.evidence_refs) ? patch.evidence_refs.map(String) : [],
              evidence_values: clone(item.evidence_values || {}),
              status: 'pending',
            });
          }
          item.status = response && response.ok ? 'completed' : 'failed';
          item.actual_model = String(response && response.actual_model || '');
          const comparison = compareAgentModels(item.requested_model, item.actual_model);
          item.model_resolution_status = String(response && response.model_resolution_status || comparison.status);
          item.model_comparison_reason = String(response && response.model_comparison_reason || comparison.reason);
          item.failure_reason = response && response.ok ? '' : String(response && response.reason || 'pi_rpc_failed');
          item.finished_at = new Date().toISOString();
          item.duration_ms = Number(response && response.duration_ms || Math.max(0, Date.parse(item.finished_at) - Date.parse(item.started_at)));
          item.proposed_cells = proposalIds.length;
          item.raw_patch_count = rawPatchCount;
          item.accepted_patch_count = proposalIds.length;
          item.rejected_patch_count = Math.max(0, rawPatchCount - proposalIds.length);
          item.proposal_status = response && response.ok
            ? (proposalIds.length > 0 ? 'completed_with_proposals' : 'completed_no_applicable_patch')
            : 'failed';
          item.proposal_risks = Array.from(new Set(proposalRisks));
          item.rejected_patch_refs = rejectedPatchRefs;
          item.patch_diagnostics = patchDiagnostics;
          item.proposal_ids = proposalIds;
          batch.public_stage = '正在聚合结构化建议';
          recalculateBatchProgress(batch);
        }, { action: 'batch_item_finished', item_id: itemId });
      }
    };
    await Promise.all(Array.from({ length: Math.min(AGENT_BATCH_CONCURRENCY, queue.length) }, () => worker()));
    const freshnessAfterWorkers = agentBatchResponse(nodeId, batchId).batch;
    if (freshnessAfterWorkers.freshness_status === 'stale') return { ok: true, batch: freshnessAfterWorkers };
    const finalBatch = updateAgentBatch(nodeId, batchId, batch => {
      if (batch.status !== 'cancelled') batch.status = 'review_ready';
      batch.public_stage = batch.status === 'cancelled' ? '已取消' : '等待用户复核';
      batch.finished_at = new Date().toISOString();
      recalculateBatchProgress(batch);
    }, { action: 'batch_finished' });
    let thread = loadThread(nodeId);
    const rejectedCount = Number(finalBatch.progress.rejected_cells || 0);
    const subjectLabel = finalBatch.subject_kind === 'keyword' ? '关键词' : '商品';
    const summaryText = finalBatch.progress.proposed_cells > 0
      ? `当前页批量填充完成：${finalBatch.progress.completed_products}/${finalBatch.progress.eligible_products} 个${subjectLabel}已处理，已生成建议 ${finalBatch.progress.proposed_cells}/${finalBatch.progress.target_cells}。`
      : rejectedCount > 0
        ? `当前页批量填充完成，但没有可复核建议：Agent 返回的 ${rejectedCount} 条建议未通过当前页、字段或空值校验，请展开${subjectLabel}明细查看风险。`
        : `当前页批量填充完成：${finalBatch.progress.completed_products}/${finalBatch.progress.eligible_products} 个${subjectLabel}已处理，Agent 未生成有证据支持的建议。`;
    thread.messages = [...(thread.messages || []), {
      message_id: `batch-assistant-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      role: 'assistant',
      text: summaryText,
      intent: 'table_edit_batch',
      batch_id: batchId,
      table_revision: finalBatch.base_revision,
      created_at: new Date().toISOString(),
    }];
    writeThread(nodeId, thread, { action: 'append_agent_batch_summary', batch_id: batchId });
    return { ok: true, batch: finalBatch };
  }

  function startAgentBatch(nodeId, node, payload, callAgent) {
    const prepared = prepareAgentBatch(nodeId, node, payload);
    const task = executeAgentBatch(prepared, callAgent);
    return {
      response: { ok: true, status: 'accepted', batch_id: prepared.batchId, batch: agentBatchResponse(nodeId, prepared.batchId).batch, thread: prepared.thread },
      task,
    };
  }

  function applyAgentBatch(nodeId, batchId, payload) {
    const batch = agentBatchResponse(nodeId, batchId).batch;
    if (batch.freshness_status === 'stale') throwAgentBatchStale(batch);
    const table = workspaceResponse(nodeId);
    validateRevision(table.workspace, payload && payload.base_revision);
    if (Number(batch.base_revision) !== Number(table.workspace.revision || 0)) {
      throwAgentBatchStale(decorateAgentBatchFreshness(nodeId, batch, table.workspace));
    }
    const selected = new Set(Array.isArray(payload && payload.proposal_ids) ? payload.proposal_ids.map(String) : []);
    if (selected.size === 0) throw new CollaborationError(400, 'agent_batch_proposals_required');
    const pageRows = new Set(batch.page && Array.isArray(batch.page.row_ids) ? batch.page.row_ids.map(String) : []);
    const proposals = (batch.proposals || []).filter(item => selected.has(String(item.proposal_id || '')));
    if (proposals.length !== selected.size) throw new CollaborationError(400, 'agent_batch_proposal_not_found');
    const operations = proposals.map(proposal => {
      if (proposal.status !== 'pending' || !pageRows.has(String(proposal.row_id || '')) || nonEmpty(proposal.old_value)) {
        throw new CollaborationError(409, 'agent_batch_proposal_not_applicable', { proposal_id: proposal.proposal_id });
      }
      const current = currentValue(table.workspace, baseTable(nodeId), proposal.row_id, proposal.field_path);
      if (nonEmpty(current) || !valuesEqual(current, proposal.old_value)) {
        throw new CollaborationError(409, 'revision_conflict', { current_revision: Number(table.workspace.revision || 0) });
      }
      return {
        operation: 'set_cell',
        row_id: proposal.row_id,
        field_path: proposal.field_path,
        expected_value: proposal.old_value,
        new_value: proposal.new_value,
        source_kind: 'pi_derived',
        reason: proposal.reason,
        confidence: proposal.confidence,
        evidence_refs: proposal.evidence_refs || [],
        proposal_id: proposal.proposal_id,
        batch_id: batchId,
      };
    });
    const tableWorkspace = applyPatch(nodeId, {
      schema_version: 'data-table-edit-patch-v1',
      base_revision: table.workspace.revision,
      batch_id: batchId,
      operations,
    }, { sourceKind: 'pi_derived' });
    const appliedAt = new Date().toISOString();
    updateAgentBatch(nodeId, batchId, item => {
      item.proposals = (item.proposals || []).map(proposal => selected.has(String(proposal.proposal_id || ''))
        ? { ...proposal, status: 'applied', applied_at: appliedAt }
        : proposal);
      item.status = (item.proposals || []).some(proposal => proposal.status === 'pending') ? 'review_ready' : 'completed';
      item.applied_at = appliedAt;
      item.applied_revision = tableWorkspace.workspace.revision;
      recalculateBatchProgress(item);
    }, { action: 'batch_proposals_applied', proposal_ids: Array.from(selected), revision: tableWorkspace.workspace.revision });
    return { ok: true, batch: agentBatchResponse(nodeId, batchId).batch, table_workspace: workspaceResponse(nodeId) };
  }

  function confirmDataTable(nodeId, payload = {}) {
    const tablePayload = workspaceResponse(nodeId);
    const { workspace, effective_fields: fields, effective_rows: rows } = tablePayload;
    validateRevision(workspace, payload.base_revision);
    if (rows.length === 0) throw new CollaborationError(409, 'data_table_empty');

    const thread = loadThread(nodeId);
    const batches = (thread.agent_batches || []).map(summary => {
      try {
        return agentBatchResponse(nodeId, String(summary.batch_id || '')).batch;
      } catch (error) {
        if (error instanceof CollaborationError && error.code === 'agent_batch_not_found') return null;
        throw error;
      }
    }).filter(Boolean);
    const running = batches.filter(batch => ['preparing', 'running'].includes(String(batch.status || '')));
    if (running.length > 0) {
      throw new CollaborationError(409, 'agent_batch_running', {
        batch_ids: running.map(batch => batch.batch_id),
      });
    }

    const confirmedAt = new Date().toISOString();
    let ignoredPendingProposals = 0;
    for (const batch of batches) {
      const pending = (batch.proposals || []).filter(proposal => proposal.status === 'pending');
      if (pending.length === 0) continue;
      ignoredPendingProposals += pending.length;
      updateAgentBatch(nodeId, batch.batch_id, item => {
        item.proposals = (item.proposals || []).map(proposal => proposal.status === 'pending'
          ? { ...proposal, status: 'ignored_on_finalize', ignored_at: confirmedAt }
          : proposal);
        item.status = 'completed';
        item.finished_at = item.finished_at || confirmedAt;
        item.public_stage = '已完成复核';
        recalculateBatchProgress(item);
      }, { action: 'pending_proposals_ignored_on_finalize', proposal_count: pending.length });
    }

    const fieldPaths = fields.map(fieldPathOf).filter(Boolean);
    const missingCells = rows.reduce((count, row) => count + fieldPaths.filter(field => !nonEmpty(row[field])).length, 0);
    const overrideCount = Object.values(workspace.cell_overrides || {})
      .reduce((count, values) => count + Object.keys(values || {}).length, 0);
    const artifactRef = `artifacts/${nodeId}.confirmed_data_table.json`;
    const artifact = {
      schema_version: 'data-table-confirmed-v1',
      node_id: nodeId,
      title: '已确认 TOP N 商品数据表',
      status: 'confirmed',
      source: 'data_table_workspace_confirmation',
      base_data_table_ref: workspace.base_data_table_ref,
      workspace_revision: Number(workspace.revision || 0),
      fields: clone(fields),
      rows: clone(rows),
      row_meta: clone(workspace.row_meta || []),
      cell_overrides: clone(workspace.cell_overrides || {}),
      row_count: rows.length,
      field_count: fields.length,
      missing_cell_count: missingCells,
      override_count: overrideCount,
      confirmed_by: String(payload.confirmed_by || 'local_user'),
      confirmed_at: confirmedAt,
      artifact_path: artifactRef,
    };
    const confirmation = {
      schema_version: 'data-table-confirmation-v1',
      node_id: nodeId,
      status: 'confirmed',
      workspace_revision: Number(workspace.revision || 0),
      row_count: rows.length,
      field_count: fields.length,
      missing_cell_count: missingCells,
      override_count: overrideCount,
      ignored_pending_proposals: ignoredPendingProposals,
      artifact_ref: artifactRef,
      confirmed_by: artifact.confirmed_by,
      confirmed_at: confirmedAt,
    };
    atomicWriteJson(confirmedTablePath(nodeId), artifact);
    atomicWriteJson(confirmationPath(nodeId), confirmation);
    const confirmedDerived = onDataTableConfirmed({
      node_id: nodeId,
      workspace_revision: Number(workspace.revision || 0),
      artifact: clone(artifact),
      confirmation: clone(confirmation),
    }) || {};
    appendHistory(nodeId, {
      edit_id: `confirmation-${Date.now()}`,
      created_at: confirmedAt,
      revision_before: workspace.revision,
      revision_after: workspace.revision,
      source_kind: 'human_confirmation',
      status: 'confirmed',
      artifact_ref: artifactRef,
      ignored_pending_proposals: ignoredPendingProposals,
    });
    return { ok: true, confirmation, artifact, ...confirmedDerived, table_workspace: workspaceResponse(nodeId) };
  }

  function cancelAgentBatch(nodeId, batchId) {
    const current = agentBatchResponse(nodeId, batchId).batch;
    if (current.freshness_status === 'stale') throwAgentBatchStale(current);
    const batch = updateAgentBatch(nodeId, batchId, item => {
      if (!['preparing', 'running'].includes(item.status)) throw new CollaborationError(409, 'agent_batch_not_running');
      item.status = 'cancelled';
      item.public_stage = '已取消';
      item.finished_at = new Date().toISOString();
      item.items = (item.items || []).map(child => ['queued', 'running'].includes(child.status)
        ? { ...child, status: 'cancelled', failure_reason: 'user_cancelled', finished_at: new Date().toISOString() }
        : child);
      recalculateBatchProgress(item);
    }, { action: 'batch_cancelled' });
    return { ok: true, batch, call_ids: batch.items.map(item => item.call_id).filter(Boolean) };
  }

  function retryAgentBatch(nodeId, node, batchId, callAgent) {
    const batch = agentBatchResponse(nodeId, batchId).batch;
    if (batch.freshness_status === 'stale') throwAgentBatchStale(batch);
    const table = workspaceResponse(nodeId);
    if (Number(batch.base_revision) !== Number(table.workspace.revision || 0)) {
      throwAgentBatchStale(decorateAgentBatchFreshness(nodeId, batch, table.workspace));
    }
    const retryIds = batch.items.filter(item => ['failed', 'no_evidence'].includes(item.status) && Object.keys(item.evidence_values || {}).length > 0).map(item => item.item_id);
    if (retryIds.length === 0) throw new CollaborationError(409, 'agent_batch_no_retryable_items');
    updateAgentBatch(nodeId, batchId, item => {
      item.status = 'preparing';
      item.finished_at = '';
      item.items = item.items.map(child => retryIds.includes(child.item_id)
        ? { ...child, status: 'queued', failure_reason: '', finished_at: '', duration_ms: 0 }
        : child);
      recalculateBatchProgress(item);
    }, { action: 'batch_retry_started', item_ids: retryIds });
    const prepared = { nodeId, node, batchId };
    return { response: { ok: true, status: 'accepted', batch_id: batchId, batch: agentBatchResponse(nodeId, batchId).batch }, task: executeAgentBatch(prepared, callAgent, retryIds) };
  }

  function threadMessage(thread, messageId) {
    const message = (thread.messages || []).find(item => String(item.message_id || '') === messageId);
    if (!message) throw new CollaborationError(404, 'thread_message_not_found', { message_id: messageId });
    return message;
  }

  function actOnThread(nodeId, node, payload) {
    const action = String(payload && payload.action || '');
    let thread = loadThread(nodeId);
    const messageId = String(payload.message_id || '');
    const message = messageId ? threadMessage(thread, messageId) : null;
    let tableWorkspace = null;
    let insightWorkspace = null;

    if (action === 'apply_cell_proposal') {
      if (!message || !message.proposal || !['pending', 'partially_applied'].includes(message.proposal_status)) {
        throw new CollaborationError(409, 'table_proposal_not_pending');
      }
      const current = workspaceResponse(nodeId);
      if (Number(message.table_revision) !== Number(current.workspace.revision || 0)
        || Number(message.proposal.workspace_revision) !== Number(current.workspace.revision || 0)) {
        throw new CollaborationError(409, 'revision_conflict', { current_revision: Number(current.workspace.revision || 0) });
      }
      const allPatches = Array.isArray(message.proposal.patches) ? message.proposal.patches : [];
      const requested = Array.isArray(payload.patch_indices) && payload.patch_indices.length
        ? payload.patch_indices.map(Number)
        : allPatches.map((_, index) => index);
      const alreadyApplied = new Set(Array.isArray(message.applied_patch_indices) ? message.applied_patch_indices.map(Number) : []);
      if (requested.some(index => alreadyApplied.has(index))) {
        throw new CollaborationError(409, 'proposal_patch_already_applied');
      }
      const operations = requested.map(index => {
        const patch = allPatches[index];
        if (!patch) throw new CollaborationError(400, 'proposal_patch_not_found', { patch_index: index });
        return {
          operation: patch.operation || (patch.new_value === '' ? 'clear_cell' : 'set_cell'),
          row_id: patch.row_id,
          field_path: patch.field_path,
          expected_value: patch.old_value,
          new_value: patch.new_value,
          source_kind: 'pi_derived',
          reason: patch.reason,
          confidence: patch.confidence,
          evidence_refs: patch.evidence_refs || [],
        };
      });
      tableWorkspace = applyPatch(nodeId, {
        schema_version: 'data-table-edit-patch-v1',
        base_revision: current.workspace.revision,
        proposal_id: message.proposal.proposal_id,
        proposal_patch_indices: requested,
        operations,
      }, { sourceKind: 'pi_derived' });
      const appliedIndices = Array.from(new Set([...alreadyApplied, ...requested])).sort((a, b) => a - b);
      message.proposal_status = appliedIndices.length === allPatches.length ? 'applied' : 'partially_applied';
      message.applied_patch_indices = appliedIndices;
      message.table_revision = Number(tableWorkspace.workspace.revision || 0);
      message.proposal.workspace_revision = Number(tableWorkspace.workspace.revision || 0);
      message.applied_at = new Date().toISOString();
    } else if (action === 'ignore_proposal') {
      if (!message || !['pending', 'partially_applied'].includes(message.proposal_status)) throw new CollaborationError(409, 'proposal_not_pending');
      message.proposal_status = message.proposal_status === 'partially_applied' ? 'partially_applied_ignored' : 'ignored';
      message.ignored_at = new Date().toISOString();
    } else if (action === 'save_insight_draft') {
      if (!message || !message.proposal || message.intent !== 'insight_requirement') {
        throw new CollaborationError(409, 'insight_proposal_not_pending');
      }
      const table = workspaceResponse(nodeId);
      if (Number(message.table_revision) !== Number(table.workspace.revision || 0)) {
        throw new CollaborationError(409, 'revision_conflict', { current_revision: Number(table.workspace.revision || 0) });
      }
      const current = insightResponse(nodeId, node);
      const proposal = message.proposal;
      insightWorkspace = patchInsight(nodeId, node, {
        base_revision: current.workspace.revision,
        requirement_id: String(payload.requirement_id || message.requirement_id || proposal.requirement_id || ''),
        draft_text: payload.draft_text === undefined ? proposal.proposed_text : payload.draft_text,
        evidence_bindings: Array.isArray(payload.evidence_bindings) ? payload.evidence_bindings : proposal.evidence_bindings || [],
        risks: proposal.risks || [],
        questions_for_user: proposal.questions_for_user || [],
      });
      message.proposal_status = 'saved_as_draft';
      message.saved_at = new Date().toISOString();
    } else if (action === 'confirm_insight') {
      const current = insightResponse(nodeId, node);
      insightWorkspace = confirmInsight(nodeId, node, {
        base_revision: current.workspace.revision,
        requirement_id: String(payload.requirement_id || message && message.requirement_id || ''),
        confirmed_by: String(payload.confirmed_by || 'local_user'),
      });
    } else {
      throw new CollaborationError(400, 'thread_action_invalid', { action });
    }

    thread = writeThread(nodeId, thread, {
      action,
      message_id: messageId,
      requirement_id: String(payload.requirement_id || message && message.requirement_id || ''),
    });
    return { ok: true, thread, table_workspace: tableWorkspace, insight_workspace: insightWorkspace };
  }

  return {
    actOnThread,
    agentCallResponse,
    agentBatchResponse,
    applyAgentBatch,
    applyPatch,
    attachThreadContext,
    confirmInsight,
    insightResponse,
    patchInsight,
    queryThread,
    setThreadModel,
    startAgentBatch,
    startThreadQuery,
    storeProposal,
    threadResponse,
    cancelAgentBatch,
    confirmDataTable,
    retryAgentBatch,
    undo,
    workspaceResponse,
  };
}

module.exports = {
  CollaborationError,
  atomicWriteJson,
  compareAgentModels,
  createCollaborationStore,
  normalizedRowMeta,
};
