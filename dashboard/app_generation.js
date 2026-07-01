// PRD生成应用 · 可观测工作台
// 三栏布局：左侧任务/对比组、中间节点流与详情、右侧 Agent 协作。
// 后端契约：/api/app-generation/runs、/api/app-generation/runs/<id>、
// /api/app-generation/runs/<id>/context?node_id=&selected_variant=、
// /api/app-generation/agent/message、/api/app-generation/agent/stream、/api/app-generation/rerun。

const STATE_KEY = "app_generation_workbench_state_v1";

// TODO(model-list): 当前为前端硬编码常用模型清单；待后端 /api/app-generation/models 上线后切到动态拉取。
const COMMON_CODEX_MODELS = [
  "gpt-5.5",
  "gpt-5.3-codex",
  "gpt-5.1-codex",
  "gpt-4.1-mini",
  "claude-sonnet-4-5-20250929",
  "claude-opus-4-5-20251101",
];

const BUSINESS_NODE_TITLES = {
  skill_routing: "Skill 路由",
  prd_input: "PRD 输入",
  prd_normalization: "PRD 标准化",
  context_contract: "应用契约",
  planning_tdd: "规划与验收",
  implementation: "应用实现",
  review_quality: "质量评审",
  verification: "验证结果",
  preview_delivery: "预览交付",
};

const DETAIL_CARD_TITLES = [
  "Skill 路由",
  "变体与对比",
  "Project Skills",
  "输入",
  "输出",
  "Tool calls · Usage · Scores · 风险",
];

const STATUS_LABELS = {
  completed: "已完成",
  ready: "可执行",
  running: "执行中",
  warning: "需关注",
  blocked: "已阻塞",
  failed: "失败",
  missing: "未生成",
  not_started: "未开始",
  not_configured: "未配置",
  not_published: "未发布",
  published: "已发布",
  unknown: "未记录",
  success: "已就绪",
  error: "失败",
  pending: "未开始",
  drafted: "已形成草案",
  planned: "已纳入规划",
  generating: "正在生成",
  generated: "已生成",
  verifying: "正在验证",
  verified: "已验证",
  needs_attention: "需关注",
  patched: "已修复",
  delivered: "已交付",
  context: "上下文",
};

const VALIDATION_ICONS = {
  success: "✓",
  warning: "⚠",
  error: "✗",
  pending: "○",
};

const USAGE_LABELS = {
  prompt_tokens: "输入 Token",
  completion_tokens: "输出 Token",
  total_tokens: "总 Token",
  estimated_cost: "预估成本",
  usage_source: "来源",
};

const SCORE_LABELS = {
  product_effect: "产品效果",
  engineering_readiness: "工程可执行",
  acceptance_coverage: "验收覆盖",
  risk_score: "风险评分",
  ui_fit: "UI 贴合度",
};

const VARIANT_LABELS = {
  rule: "规则基线",
  codex: "Codex 生成",
  llm: "LLM 生成",
  pi_agent: "PI-Agent",
};

const state = {
  runs: [],
  isNewTask: false,
  selectedRun: null,
  selectedRunId: "",
  nodes: [],
  selectedNodeId: "",
  selectedVariant: "codex",
  nodeContext: null,
  providerStatuses: [],
  provider: "codex",
  uploadProvider: "default",
  uploadModel: COMMON_CODEX_MODELS[0],
  uploadFilename: "",
  agentMode: "explain",
  agentLog: [],
  preview: null,
  previewRequestSeq: 0,
  appPreview: null,
  appPreviewPollInterval: null,
  delegateRepairPollInterval: null,
  canvas: {
    projection: null,
    selectedBusinessNodeId: "",
    selectedObjectId: "",
    selectedObjectDetail: null,
    filters: {
      objectType: "all",
      status: "all",
    },
    coderLive: null,
    loading: false,
    error: "",
  },
  interactionContext: {
    focus: {
      card: "node_summary",
      artifact_ref: "",
      artifact_title: "",
      selected_text: "",
      view_mode: "node_detail",
    },
    allowed_operations: [
      "explain",
      "compare",
      "suggest_input_patch",
      "suggest_artifact_patch",
      "read_artifact",
      "suggest_artifact_regeneration",
      "explain_object",
      "repair_generated_app",
      "verify_capability",
      "patch_app",
      "delegate_code_repair",
      "diagnose_app_bug",
      "rerun_from_node",
      "select_variant",
      "ask_clarification",
    ],
  },
};

function loadPersistedState() {
  try {
    const raw = localStorage.getItem(STATE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object") {
      state.selectedRunId = parsed.selectedRunId || "";
      state.selectedNodeId = parsed.selectedNodeId || "";
      state.selectedVariant = parsed.selectedVariant || "codex";
      state.provider = parsed.provider || "codex";
      state.uploadProvider = parsed.uploadProvider || "default";
      state.uploadModel = parsed.uploadModel || COMMON_CODEX_MODELS[0];
      state.agentMode = parsed.agentMode || "explain";
      if (parsed.canvas && typeof parsed.canvas === "object") {
        state.canvas.selectedBusinessNodeId = parsed.canvas.selectedBusinessNodeId || "";
        state.canvas.selectedObjectId = parsed.canvas.selectedObjectId || "";
        if (parsed.canvas.filters && typeof parsed.canvas.filters === "object") {
          state.canvas.filters = {
            objectType: parsed.canvas.filters.objectType || "all",
            status: parsed.canvas.filters.status || "all",
          };
        }
      }
    }
  } catch (err) {
    // localStorage 可能不可用或包含损坏的 JSON，静默回退到默认状态。
  }
}

function persistState() {
  try {
    localStorage.setItem(
      STATE_KEY,
      JSON.stringify({
        selectedRunId: state.selectedRunId,
        selectedNodeId: state.selectedNodeId,
        selectedVariant: state.selectedVariant,
        provider: state.provider,
        uploadProvider: state.uploadProvider,
        uploadModel: state.uploadModel,
        agentMode: state.agentMode,
        canvas: {
          selectedBusinessNodeId: state.canvas.selectedBusinessNodeId || "",
          selectedObjectId: state.canvas.selectedObjectId || "",
          filters: state.canvas.filters || { objectType: "all", status: "all" },
        },
      })
    );
  } catch (err) {
    // 写失败不影响主流程。
  }
}

async function fetchJSON(url, options) {
  const response = await fetch(url, options);
  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch (err) {
    throw new Error(`Invalid JSON from ${url}`);
  }
  if (!response.ok) {
    const message = (payload && payload.error) || `HTTP ${response.status}`;
    throw new Error(message);
  }
  return payload;
}

function el(tag, attrs, children) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "className") node.className = value;
      else if (key === "dataset") {
        for (const [dk, dv] of Object.entries(value || {})) node.dataset[dk] = dv;
      } else if (key === "onclick") node.addEventListener("click", value);
      else if (key === "text") node.textContent = value;
      else node.setAttribute(key, String(value));
    }
  }
  if (Array.isArray(children)) {
    for (const child of children) {
      if (child === null || child === undefined) continue;
      if (typeof child === "string") node.appendChild(document.createTextNode(child));
      else node.appendChild(child);
    }
  }
  return node;
}

function clear(node) {
  if (!node) return;
  while (node.firstChild) node.removeChild(node.firstChild);
}

function statusBadge(status) {
  const map = {
    completed: "status-completed",
    ready: "status-completed",
    running: "status-processing",
    warning: "status-attention",
    blocked: "status-attention",
    failed: "status-attention",
    not_started: "status-muted",
    not_configured: "status-attention",
    not_published: "status-muted",
    published: "status-completed",
    unknown: "status-muted",
    success: "status-completed",
    error: "status-attention",
    pending: "status-muted",
    drafted: "status-processing",
    planned: "status-processing",
    generating: "status-processing",
    generated: "status-completed",
    verifying: "status-processing",
    verified: "status-completed",
    needs_attention: "status-attention",
    patched: "status-completed",
    delivered: "status-completed",
    context: "status-muted",
  };
  return map[status] || "status-muted";
}

function validationIcon(status) {
  return VALIDATION_ICONS[status] || VALIDATION_ICONS.pending;
}

function summarizeOutputs(summary) {
  if (!summary || typeof summary !== "object") return "";
  const total = Number(summary.total || 0);
  if (!total) return "";
  const ready = Number(summary.ready || 0);
  const parts = [`产物 ${ready}/${total} 就绪`];
  const warn = Number(summary.warning || 0);
  const err = Number(summary.error || 0);
  if (err) parts.push(`${err} 失败`);
  if (warn) parts.push(`${warn} 关注`);
  return parts.join("，");
}

function statusLabel(status) {
  return STATUS_LABELS[status] || status || "未记录";
}

function nodeTitle(node) {
  const id = typeof node === "string" ? node : node && node.id;
  return BUSINESS_NODE_TITLES[id] || (node && node.title) || id || "节点";
}

function variantLabel(variantId) {
  return VARIANT_LABELS[variantId] || variantId || "未记录";
}

function usageLabel(key) {
  return USAGE_LABELS[key] || key;
}

function scoreLabel(key) {
  return SCORE_LABELS[key] || key;
}

function safeText(value, fallback) {
  if (value === null || value === undefined || value === "") return fallback || "未记录";
  return String(value);
}

function setAgentFocus(card, extra) {
  const current = state.interactionContext && state.interactionContext.focus ? state.interactionContext.focus : {};
  const nextCard = card || (extra && extra.card) || current.card || "node_summary";
  state.interactionContext = {
    ...(state.interactionContext || {}),
    focus: {
      card: nextCard,
      artifact_ref: nextCard === "artifact_preview" ? current.artifact_ref || "" : "",
      artifact_title: nextCard === "artifact_preview" ? current.artifact_title || "" : "",
      selected_text: getSelectedText() || current.selected_text || "",
      view_mode: nextCard === "artifact_preview" ? "artifact_preview" : "node_detail",
      ...(extra || {}),
      card: nextCard,
    },
  };
  renderAgentContextRefs();
}

function getSelectedText() {
  const selected = window.getSelection ? String(window.getSelection() || "").trim() : "";
  return selected.length > 1000 ? selected.slice(0, 1000) : selected;
}

function buildAgentInteractionContext() {
  const focus = (state.interactionContext && state.interactionContext.focus) || {};
  const canvasSelection = focus.card === "canvas_object" || focus.card === "flow_step" ? buildCanvasSelectionContext() : null;
  return {
    schema_version: 1,
    run_id: state.selectedRunId,
    node_id: state.selectedNodeId,
    selected_variant: state.selectedVariant,
    context_revision: state.nodeContext ? state.nodeContext.context_revision : "",
    focus: {
      card: focus.card || "node_summary",
      artifact_ref: focus.artifact_ref || "",
      artifact_title: focus.artifact_title || "",
      selected_text: getSelectedText() || focus.selected_text || "",
      view_mode: focus.view_mode || "node_detail",
    },
    canvas_selection: canvasSelection,
    allowed_operations: (state.interactionContext && state.interactionContext.allowed_operations) || [],
  };
}

function buildCanvasSelectionContext() {
  const projection = state.canvas && state.canvas.projection;
  const focus = (state.interactionContext && state.interactionContext.focus) || {};
  if (projection && focus.card === "flow_step") {
    const step = currentCanvasBusinessNode();
    if (!step) return null;
    return {
      schema_version: 1,
      run_id: state.selectedRunId,
      selection_type: "flow_step",
      step_id: step.id,
      step_type: step.step_type || "business",
      title: step.title || step.id,
      status: step.status || "unknown",
      runtime_nodes: Array.isArray(step.runtime_nodes) ? step.runtime_nodes : [],
      input_summary: Array.isArray(step.input_summary) ? step.input_summary : [],
      process_summary: Array.isArray(step.process_summary) ? step.process_summary : [],
      output_summary: Array.isArray(step.output_summary) ? step.output_summary : [],
      evidence_refs: Array.isArray(step.evidence_refs) ? step.evidence_refs : [],
      allowed_actions: Array.isArray(step.available_actions) ? step.available_actions : [],
    };
  }
  const objectId = state.canvas && state.canvas.selectedObjectId;
  if (!projection || !objectId) return null;
  const objects = allCanvasObjects(projection);
  const object = objects.find((item) => item.object_id === objectId);
  if (!object) return null;
  const related = (projection.edges || [])
    .filter((edge) => edge && (edge.from === objectId || edge.to === objectId))
    .map((edge) => (edge.from === objectId ? edge.to : edge.from))
    .filter(Boolean)
    .slice(0, 12);
  return {
    schema_version: 1,
    run_id: state.selectedRunId,
    selection_type: "canvas_object",
    selection_id: object.object_id,
    object_type: object.object_type,
    title: object.title || object.object_id,
    status: object.status || "unknown",
    business_node: object.owner_node || object.owner_node_id || "",
    business_node_id: object.owner_node_id || "",
    focus_surface: "canvas_object_detail",
    visible_related_objects: related,
    allowed_actions: object.actions || [],
  };
}

function canvasFlowSteps(projection) {
  const proj = projection || (state.canvas && state.canvas.projection);
  if (!proj) return [];
  if (Array.isArray(proj.flow_steps) && proj.flow_steps.length) return proj.flow_steps;
  return Array.isArray(proj.business_nodes) ? proj.business_nodes : [];
}

function initialCanvasProjection() {
  const stepDefs = [
    ["prd_entry", "PRD 输入", "ui", "ready", ["粘贴 PRD 文本或选择 PRD 文件"], ["选择生成配置并点击启动生成"], ["新的应用生成任务"]],
    ["business_goal_understanding", "理解业务目标", "business", "not_started", ["PRD 输入"], ["等待生成任务启动"], ["业务目标摘要"]],
    ["business_spec_compilation", "编译业务规格", "business", "not_started", ["业务目标"], ["等待上一步完成"], ["标准化 PRD 与应用契约"]],
    ["app_structure_planning", "规划应用结构", "business", "not_started", ["应用契约"], ["等待规格编译完成"], ["TDD 计划与验收覆盖"]],
    ["prototype_generation", "生成应用原型", "business", "not_started", ["应用结构规划"], ["等待 Code Agent 执行"], ["本地应用原型"]],
    ["capability_verification", "验证业务能力", "business", "not_started", ["生成应用"], ["等待应用生成完成"], ["验证记录与能力缺口"]],
    ["delivery_version", "输出可交付版本", "business", "not_started", ["验证结果"], ["等待验证完成"], ["交付报告"]],
    ["app_preview", "可预览应用", "ui", "not_started", ["可交付版本"], ["等待应用生成并发布快照"], ["本地预览 URL"]],
  ];
  const flowSteps = stepDefs.map(([id, title, stepType, status, inputSummary, processSummary, outputSummary], index) => ({
    id,
    title,
    step_type: stepType,
    status,
    summary: id === "prd_entry" ? "上传 PRD 后开始生成应用。" : "等待 PRD 输入并启动生成。",
    input_summary: inputSummary,
    process_summary: processSummary,
    output_summary: outputSummary,
    available_actions: id === "prd_entry" ? ["start_generation"] : [],
    runtime_nodes: [],
    evidence_refs: [],
    artifact_refs: [],
    object_count: 0,
    object_counts: {},
    progress: { ready_artifacts: id === "prd_entry" ? 0 : 0, required_artifacts: 1, ratio: 0 },
    coder_progress: {},
    latest_event: id === "prd_entry" ? "请上传或粘贴 PRD。" : "",
    stage_index: index + 1,
    stage_total: stepDefs.length,
    is_entry: index === 0,
    is_terminal: index === stepDefs.length - 1,
  }));
  return {
    schema_version: 1,
    run: {
      run_id: "",
      domain_id: "app_generation",
      app_slug: "新应用",
      brief: "上传 PRD 后开始生成应用。",
      status: "draft",
      quality_mode: "prototype",
    },
    flow_steps: flowSteps,
    business_nodes: flowSteps.filter((step) => step.step_type === "business"),
    objects: [],
    edges: [],
    versions: [],
    context_objects: [],
    warnings: [],
    updated_at: "",
  };
}

function findArtifactByPath(path) {
  if (!path) return null;
  const pools = [];
  if (state.nodeContext) {
    pools.push(state.nodeContext.inputs || [], state.nodeContext.outputs || []);
  }
  for (const node of state.nodes || []) {
    pools.push(node.inputs || [], node.outputs || []);
  }
  for (const pool of pools) {
    const found = (pool || []).find((item) => item && item.path === path);
    if (found) return found;
  }
  return { path, title: path, status: "ready" };
}

function agentActionTitle(action) {
  const labels = {
    explain_node: "解释当前节点",
    explain_inputs: "解释输入",
    explain_outputs: "解释输出",
    compare_variants: "对比变体",
    read_artifact: "预览产物",
    suggest_input_patch: "调整输入",
    suggest_artifact_patch: "调整产物建议",
    suggest_artifact_regeneration: "重跑当前产物",
    explain_step: "解释业务步骤",
    explain_step_io: "说明步骤输入输出",
    inspect_evidence: "查看步骤证据",
    rerun_step: "重新执行步骤",
    explain_object: "解释业务对象",
    verify_capability: "验证业务能力",
    repair_generated_app: "修复当前应用",
    diagnose_app_bug: "诊断应用问题",
    patch_artifact: "修改产物",
    patch_app: "修改已发布应用",
    delegate_code_repair: "委托 Code Agent 修复",
    rerun_from_node: "从节点重跑",
    select_variant: "切换变体",
    ask_clarification: "澄清问题",
  };
  return labels[action.type] || action.type || "Agent 动作";
}

function agentActionSummary(action) {
  return (
    action.summary ||
    action.patch_summary ||
    (action.repair_request && action.repair_request.problem) ||
    action.reason ||
    action.question ||
    action.target_artifact ||
    action.override_instructions ||
    ""
  );
}

function agentActionSourceLine(action) {
  if (!action) return "";
  if (action.source_step_id) {
    const parts = [];
    if (action.source_step_title) parts.push(`业务步骤：${action.source_step_title}`);
    if (Array.isArray(action.source_runtime_nodes) && action.source_runtime_nodes.length) {
      parts.push(`工程证据：${action.source_runtime_nodes.join("，")}`);
    }
    return parts.join(" · ");
  }
  if (!action.source_object_id) return "";
  const parts = [];
  if (action.source_object_title) parts.push(`对象：${action.source_object_title}`);
  if (action.source_business_node) parts.push(`节点：${action.source_business_node}`);
  if (action.source_object_type) parts.push(`类型：${objectTypeLabel(action.source_object_type)}`);
  return parts.join(" · ");
}

function currentPublishStatus() {
  const selected =
    state.selectedRun ||
    (state.runs || []).find((run) => run && run.run_id === state.selectedRunId) ||
    null;
  return selected && selected.publish_status && typeof selected.publish_status === "object"
    ? selected.publish_status
    : { status: "not_published", message: "尚未发布应用快照。" };
}

function renderPreviewControls() {
  const publishBtn = document.getElementById("app-generation-publish-btn");
  const previewBtn = document.getElementById("app-generation-preview-btn");
  const status = document.getElementById("app-generation-app-preview-status");
  const runStatus = state.selectedRun ? String(state.selectedRun.status || "") : "";
  const publishStatus = currentPublishStatus();
  const isTerminal = ["completed", "failed", "blocked"].includes(runStatus);
  const isPublished = publishStatus.status === "published";

  if (publishBtn) {
    publishBtn.disabled = !state.selectedRunId || !isTerminal;
    publishBtn.title = state.isNewTask ? "请先上传 PRD 并启动生成。" : (publishBtn.disabled ? "任务完成后才能发布应用快照。" : "把生成应用发布为可预览快照。");
  }
  if (previewBtn) {
    previewBtn.disabled = !state.selectedRunId || !isPublished;
    previewBtn.title = state.isNewTask ? "生成完成并发布后才能启动预览。" : (isPublished ? "启动已发布快照的本地预览。" : "请先发布应用快照。");
  }
  if (status && !state.appPreview) {
    if (state.isNewTask) status.textContent = "上传 PRD 并生成完成后，可以发布快照并启动本地预览。";
    else if (!state.selectedRunId) status.textContent = "请选择一个任务。";
    else if (isPublished) status.textContent = publishStatus.published_at ? `已发布：${publishStatus.app_slug || "-"} · ${publishStatus.published_at}` : "已发布，可以启动预览。";
    else status.textContent = publishStatus.message || "未发布，请先点击「发布应用快照」。";
  }
}

function enterNewTaskMode() {
  state.isNewTask = true;
  state.selectedRun = null;
  state.selectedRunId = "";
  state.nodes = [];
  state.selectedNodeId = "";
  state.nodeContext = null;
  state.preview = null;
  state.appPreview = null;
  state.canvas.projection = initialCanvasProjection();
  state.canvas.selectedBusinessNodeId = "prd_entry";
  state.canvas.selectedObjectId = "";
  state.canvas.selectedObjectDetail = null;
  state.canvas.error = "";
  setAgentFocus("flow_step", { view_mode: "business_step_detail", selected_text: "" });
  persistState();
  renderRuns();
  renderProviders();
  renderPreviewControls();
  renderNodes();
  renderCanvasPanel();
  renderAgentContextRefs();
}

async function loadRuns() {
  try {
    const data = await fetchJSON("/api/app-generation/runs");
    state.runs = (data && data.runs) || [];
    renderRuns();
    if (!state.runs.length) {
      enterNewTaskMode();
    } else if (state.isNewTask) {
      renderRuns();
      renderCanvasPanel();
    } else if (!state.selectedRunId && state.runs.length) {
      await selectRun(state.runs[0].run_id);
    } else if (state.selectedRunId) {
      await selectRun(state.selectedRunId);
    }
  } catch (err) {
    state.runs = [];
    renderRuns();
    setRunsMessage(`加载任务失败：${err.message}`);
  }
}

function setRunsMessage(text) {
  const container = document.getElementById("app-generation-runs");
  if (!container) return;
  clear(container);
  container.appendChild(el("p", { className: "meta" }, [text]));
}

function renderRuns() {
  const container = document.getElementById("app-generation-runs");
  if (!container) return;
  clear(container);
  if (!state.runs.length) {
    container.appendChild(el("p", { className: "meta" }, ["暂无历史任务。请在右侧 PRD 输入步骤上传 PRD 并启动生成。"]));
    return;
  }
  // 按 comparison_group_id 分组展示，便于对比。
  const groups = new Map();
  for (const run of state.runs) {
    const key = run.comparison_group_id || run.run_id;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(run);
  }
  for (const [groupId, runs] of groups.entries()) {
    const groupNode = el("section", { className: "app-generation-group" }, [
      el("p", { className: "eyebrow" }, [`对比组 · ${groupId}`]),
    ]);
    for (const run of runs) {
      const isSelected = run.run_id === state.selectedRunId;
      const card = el(
        "button",
        {
          type: "button",
          className: "app-generation-run-card" + (isSelected ? " selected" : ""),
          onclick: () => selectRun(run.run_id),
        },
        [
          el("div", { className: "app-generation-run-card-head" }, [
            el("span", { className: "app-generation-run-slug" }, [run.app_slug || run.run_id]),
            el("span", { className: `mini-status ${statusBadge(run.status)}` }, [run.status || "unknown"]),
          ]),
          el("p", { className: "meta" }, [run.brief || run.run_id]),
          el("p", { className: "meta" }, [
            `executor: ${run.executor || "-"} · variant: ${run.selected_variant || "codex"}` +
              (run.is_rerun ? ` · rerun-from: ${run.rerun_from_node || "-"}` : ""),
          ]),
        ]
      );
      groupNode.appendChild(card);
    }
    container.appendChild(groupNode);
  }
}

async function selectRun(runId) {
  if (!runId) return;
  state.isNewTask = false;
  state.selectedRunId = runId;
  persistState();
  renderRuns();
  try {
    const data = await fetchJSON(`/api/app-generation/runs/${encodeURIComponent(runId)}`);
    state.selectedRun = (data && data.run) || null;
    state.nodes = (data && data.nodes) || [];
    state.providerStatuses = (data && data.provider_statuses) || [];
    await refreshCanvasProjection(runId);
    const meta = document.getElementById("app-generation-pipeline-meta");
    if (meta) {
      const run = (data && data.run) || {};
      meta.textContent = `${run.app_slug || runId} · ${run.executor || "-"} · ${run.status || "unknown"}` +
        (run.source_run_id ? ` · 源 ${run.source_run_id}` : "");
    }
    renderProviders();
    renderPreviewControls();
    renderNodes();
    renderCanvasPanel();
    if (!state.selectedNodeId || !state.nodes.find((n) => n.id === state.selectedNodeId)) {
      state.selectedNodeId = state.nodes[0] ? state.nodes[0].id : "";
    }
    if (state.selectedNodeId) {
      await selectNode(state.selectedNodeId);
      setAgentFocus("flow_step", { view_mode: "business_step_detail", selected_text: "" });
      renderAgentContextRefs();
    }
    const runStatus = (data && data.run && data.run.status) || "";
    if (runStatus && !["completed", "failed", "blocked"].includes(runStatus)) {
      subscribeRunEvents(runId);
    }
  } catch (err) {
    state.selectedRun = null;
    state.nodes = [];
    state.canvas.projection = null;
    state.canvas.selectedObjectDetail = null;
    state.canvas.error = err.message;
    renderPreviewControls();
    renderNodes();
    renderCanvasPanel();
    appendAgentLog("system", `加载节点失败：${err.message}`);
  }
}

async function refreshCanvasProjection(runId) {
  state.canvas.error = "";
  state.canvas.loading = true;
  state.canvas.selectedObjectDetail = null;
  try {
    const projection = await fetchJSON(`/api/app-generation/runs/${encodeURIComponent(runId)}/canvas`);
    state.canvas.projection = projection;
    const steps = canvasFlowSteps(projection);
    if (!steps.find((item) => item.id === state.canvas.selectedBusinessNodeId)) {
      state.canvas.selectedBusinessNodeId = steps[0] ? steps[0].id : "";
    }
    const objects = allCanvasObjects(projection);
    const visibleObjects = filteredCanvasObjects(objects);
    if (!visibleObjects.find((item) => item.object_id === state.canvas.selectedObjectId)) {
      state.canvas.selectedObjectId = visibleObjects[0] ? visibleObjects[0].object_id : "";
    }
    if (state.canvas.selectedObjectId) {
      await refreshCanvasObjectDetail(state.canvas.selectedObjectId);
    }
  } catch (err) {
    state.canvas.projection = null;
    state.canvas.selectedObjectId = "";
    state.canvas.selectedObjectDetail = null;
    state.canvas.error = err.message;
  } finally {
    state.canvas.loading = false;
  }
}

async function refreshCanvasObjectDetail(objectId) {
  if (!state.selectedRunId || !objectId) return;
  const detail = await fetchJSON(
    `/api/app-generation/runs/${encodeURIComponent(state.selectedRunId)}/canvas/objects/${encodeURIComponent(objectId)}`
  );
  state.canvas.selectedObjectDetail = detail;
}

function renderNodes() {
  const container = document.getElementById("app-generation-node-list");
  if (!container) return;
  clear(container);
  const visibleNodes = visibleEngineeringNodes();
  if (!visibleNodes.length) {
    container.appendChild(el("p", { className: "meta" }, ["所选任务暂无节点数据。"]));
    return;
  }
  for (const node of visibleNodes) {
    const summaryLine = summarizeOutputs(node.output_summary) || `产物 ${(node.outputs || []).length} · 风险 ${(node.risks || []).length}`;
    const card = el(
      "button",
      {
        type: "button",
        role: "listitem",
        className: "app-generation-node-card" + (node.id === state.selectedNodeId ? " selected" : ""),
        onclick: () => selectNode(node.id),
      },
      [
        el("div", { className: "app-generation-node-card-head" }, [
          el("span", { className: "app-generation-node-business-title" }, [nodeTitle(node)]),
          el("span", { className: `mini-status ${statusBadge(node.status)}` }, [statusLabel(node.status)]),
        ]),
        el("p", { className: "app-generation-node-title-text" }, [safeText(node.summary, "未记录")]),
        el("p", { className: "meta" }, [`${summaryLine} · 风险 ${(node.risks || []).length}`]),
      ]
    );
    container.appendChild(card);
  }
}

function visibleEngineeringNodes() {
  const showAll = Boolean(document.getElementById("app-generation-show-all-engineering-nodes")?.checked);
  if (showAll) return state.nodes || [];
  const step = currentCanvasBusinessNode();
  const mappedNodes = stepRuntimeEvidenceNodes(step);
  const runtimeNodes = new Set(mappedNodes);
  if (!runtimeNodes.size) return [];
  return (state.nodes || []).filter((node) => runtimeNodes.has(node.id));
}

function stepRuntimeEvidenceNodes(step) {
  if (!step) return [];
  if (Array.isArray(step.runtime_nodes) && step.runtime_nodes.length) return step.runtime_nodes;
  if (step.id === "prd_entry") return ["skill_routing", "prd_input"];
  if (step.id === "app_preview") return ["preview_delivery"];
  return [];
}

async function selectNode(nodeId) {
  if (!nodeId) return;
  state.selectedNodeId = nodeId;
  const node = state.nodes.find((n) => n.id === nodeId);
  if (node && node.selected_variant) {
    state.selectedVariant = node.selected_variant;
  }
  closeArtifactPreview();
  setAgentFocus("node_summary", { view_mode: "node_detail", selected_text: "" });
  persistState();
  renderNodes();
  await refreshNodeContext();
}

async function refreshNodeContext() {
  if (!state.selectedRunId || !state.selectedNodeId) return;
  try {
    const url = `/api/app-generation/runs/${encodeURIComponent(state.selectedRunId)}/context?node_id=${encodeURIComponent(state.selectedNodeId)}&selected_variant=${encodeURIComponent(state.selectedVariant)}`;
    const ctx = await fetchJSON(url);
    state.nodeContext = ctx;
    renderNodeDetail();
    renderAgentContextRefs();
  } catch (err) {
    appendAgentLog("system", `刷新 NodeContext 失败：${err.message}`);
  }
}

function renderNodeDetail() {
  const node = state.nodes.find((n) => n.id === state.selectedNodeId);
  const ctx = state.nodeContext;
  const titleEl = document.getElementById("app-generation-node-title");
  const summaryEl = document.getElementById("app-generation-node-summary");
  const kickerEl = document.getElementById("app-generation-node-kicker");
  const statusEl = document.getElementById("app-generation-node-status");
  const variantMeta = document.getElementById("app-generation-node-variant-meta");
  const comparisonEl = document.getElementById("app-generation-comparison");
  const skillRouting = document.getElementById("app-generation-skill-routing");
  if (!node) {
    if (titleEl) titleEl.textContent = "节点详情";
    if (summaryEl) summaryEl.textContent = "";
    if (skillRouting) skillRouting.textContent = "";
    return;
  }
  if (titleEl) titleEl.textContent = nodeTitle(node);
  if (summaryEl) summaryEl.textContent = safeText(node.summary, "未记录");
  if (kickerEl) {
    const summaryLine = summarizeOutputs(node.output_summary);
    kickerEl.textContent = summaryLine
      ? `${state.selectedRunId} · ${nodeTitle(node)} · ${summaryLine}`
      : `${state.selectedRunId} · ${nodeTitle(node)}`;
  }
  if (statusEl) {
    statusEl.textContent = statusLabel(node.status);
    statusEl.className = `mini-status ${statusBadge(node.status)}`;
  }
  if (variantMeta) variantMeta.textContent = `当前变体：${variantLabel(state.selectedVariant)}`;
  if (comparisonEl && node.comparison) {
    comparisonEl.textContent = `对比建议：${safeText(node.comparison.summary, "-")}`;
  }
  if (skillRouting) {
    const routingLines = (node.skills || [])
      .map((skill) => `${skill.id || "skill"} · ${skill.role || "角色未记录"} · ${skill.status || "recommended"}`)
      .join("；");
    skillRouting.textContent = routingLines || "未记录";
  }
  renderVariants(node);
  renderSkills(node);
  renderTimeline(node.phases || []);
  renderArtifacts("app-generation-inputs", node.inputs || [], "inputs");
  renderArtifacts("app-generation-outputs", node.outputs || [], "outputs");
  renderToolCalls(node.tool_calls || []);
  renderUsage(ctx ? ctx.usage : node.usage);
  renderScores(node.scores || {});
  renderRisks(node.risks || []);
  renderCanvasPanel();
}

function renderCanvasPanel() {
  const meta = document.getElementById("app-generation-canvas-meta");
  const track = document.getElementById("app-generation-business-node-track");
  const objectsEl = document.getElementById("app-generation-canvas-objects");
  const detailEl = document.getElementById("app-generation-canvas-object-detail");
  if (!track || !objectsEl || !detailEl) return;
  clear(track);
  clear(objectsEl);
  clear(detailEl);
  const projection = state.canvas && state.canvas.projection;
  if (!projection) {
    if (state.canvas.loading) {
      if (meta) meta.textContent = "正在加载生成画布…";
      track.appendChild(renderCanvasSkeleton(4));
      objectsEl.appendChild(renderCanvasSkeleton(3));
      detailEl.appendChild(el("p", { className: "meta" }, ["加载中…"]));
      return;
    }
    if (state.canvas.error) {
      if (meta) meta.textContent = `生成画布暂不可用：${state.canvas.error}`;
      track.appendChild(el("p", { className: "meta app-generation-state-error" }, [`加载失败：${state.canvas.error}`]));
      objectsEl.appendChild(el("p", { className: "meta" }, ["暂无业务对象。"]));
      detailEl.appendChild(el("p", { className: "meta" }, ["请选择一个业务对象。"]));
      return;
    }
    if (meta) meta.textContent = "选择任务后查看业务节点和对象。";
    track.appendChild(el("p", { className: "meta" }, ["选择任务后查看业务节点。"]));
    objectsEl.appendChild(el("p", { className: "meta" }, ["暂无业务对象。"]));
    detailEl.appendChild(el("p", { className: "meta" }, ["请选择一个业务对象。"]));
    return;
  }
  const nodes = canvasFlowSteps(projection);
  const objects = allCanvasObjects(projection);
  const visibleObjects = filteredCanvasObjects(objects);
  const selectedBusinessNode = currentCanvasBusinessNode();
  if (meta) {
    const filterText = visibleObjects.length === objects.length ? "" : ` · 当前显示 ${visibleObjects.length} 个`;
    const selectedText = selectedBusinessNode ? ` · 当前步骤：${selectedBusinessNode.title}` : "";
    meta.textContent = `${safeText(projection.run && projection.run.app_slug, state.selectedRunId)} · ${nodes.length} 个业务步骤 · ${objects.length} 个对象${selectedText}${filterText}`;
  }
  const objectsTitle = document.getElementById("app-generation-canvas-objects-title");
  if (objectsTitle) objectsTitle.textContent = selectedBusinessNode ? `${selectedBusinessNode.title} · 对象` : "当前步骤对象";
  syncCanvasFilterControls(objects);
  renderPipelineOverview(nodes);
  renderBusinessNodeTrack(track, nodes);
  renderStepDetail(selectedBusinessNode);
  renderCanvasObjects(objectsEl, visibleObjects);
  renderCanvasObjectDetail(detailEl, state.canvas.selectedObjectDetail || objects.find((item) => item.object_id === state.canvas.selectedObjectId));
}

function filteredCanvasObjects(objects) {
  const filters = (state.canvas && state.canvas.filters) || { objectType: "all", status: "all" };
  const selectedId = state.canvas.selectedBusinessNodeId;
  return (objects || []).filter((object) => {
    let nodeOk = !selectedId || object.owner_node_id === selectedId;
    if (selectedId === "prd_entry") {
      nodeOk = object.owner_node_id === "business_goal_understanding" && object.object_type === "business_goal";
    } else if (selectedId === "app_preview") {
      nodeOk =
        object.owner_node_id === "delivery_version" ||
        ["preview_session", "repair_candidate", "delivery_version"].includes(object.object_type);
    }
    const typeOk = !filters.objectType || filters.objectType === "all" || object.object_type === filters.objectType;
    const statusOk = !filters.status || filters.status === "all" || object.status === filters.status;
    return nodeOk && typeOk && statusOk;
  });
}

function currentCanvasBusinessNode() {
  const projection = state.canvas && state.canvas.projection;
  const nodes = canvasFlowSteps(projection);
  return nodes.find((node) => node.id === state.canvas.selectedBusinessNodeId) || null;
}

function syncCanvasFilterControls(objects) {
  const typeSelect = document.getElementById("app-generation-canvas-type-filter");
  const statusSelect = document.getElementById("app-generation-canvas-status-filter");
  if (!typeSelect || !statusSelect) return;
  syncCanvasFilterSelect(
    typeSelect,
    "objectType",
    [...new Set((objects || []).map((object) => object.object_type).filter(Boolean))].sort(),
    objectTypeLabel
  );
  syncCanvasFilterSelect(
    statusSelect,
    "status",
    [...new Set((objects || []).map((object) => object.status).filter(Boolean))].sort(),
    statusLabel
  );
}

function syncCanvasFilterSelect(select, key, values, labeler) {
  const current = (state.canvas.filters && state.canvas.filters[key]) || "all";
  const options = new Map([["all", "全部"]]);
  for (const value of values) options.set(value, labeler(value));
  clear(select);
  for (const [value, label] of options.entries()) {
    select.appendChild(el("option", { value, text: label }));
  }
  select.value = options.has(current) ? current : "all";
  if (select.value !== current) {
    state.canvas.filters[key] = "all";
  }
}

function allCanvasObjects(projection) {
  const proj = projection || (state.canvas && state.canvas.projection);
  if (!proj) return [];
  const base = Array.isArray(proj.objects) ? proj.objects : [];
  const ctx = Array.isArray(proj.context_objects) ? proj.context_objects : [];
  return [...base, ...ctx];
}

const PIPELINE_DONE_STATUSES = new Set([
  "drafted",
  "planned",
  "generated",
  "verified",
  "delivered",
  "completed",
]);

function coderLiveText() {
  const live = state.canvas && state.canvas.coderLive;
  if (!live || live.run_id !== state.selectedRunId) return "";
  const now = Date.now();
  const beatAge = live.heartbeat_ts ? now - live.heartbeat_ts : null;
  const progressAge = live.ts ? now - live.ts : null;
  if (beatAge !== null && beatAge > 8000) return "心跳中断";
  if (progressAge !== null && progressAge <= 6000) return "执行中 · 持续产出";
  if (live.alive) return "执行中 · 在算（暂无新动作）";
  return "";
}

function renderCoderLiveBadge() {
  const badge = document.getElementById("app-generation-coder-heartbeat");
  if (!badge) return;
  const text = coderLiveText();
  badge.textContent = text;
  badge.className =
    "app-generation-coder-heartbeat" +
    (text ? " active" : "") +
    (text === "心跳中断" ? " stalled" : "");
}

function renderCanvasSkeleton(count) {
  const wrap = el("div", { className: "app-generation-skeleton-group" }, []);
  for (let i = 0; i < (count || 3); i += 1) {
    wrap.appendChild(el("div", { className: "app-generation-skeleton-line" }, []));
  }
  return wrap;
}

function classificationBannerView(summary) {
  const decision = String((summary && summary.decision) || "");
  const warnings = Number((summary && summary.warnings_count) || 0);
  const preview = String((summary && summary.blocker_preview) || "");
  if (decision === "failed") {
    return {
      tone: "error",
      label: "生成失败",
      text: preview || String((summary && summary.primary_reason) || "存在阻塞性失败"),
      openable: true,
    };
  }
  if (decision === "passed_with_warnings" || decision === "completed_with_warnings") {
    return {
      tone: "warning",
      label: "通过 · 有告警",
      text: warnings ? `${warnings} 条无关告警` + (preview ? ` · ${preview}` : "") : (preview || "存在无关告警"),
      openable: true,
    };
  }
  if (decision === "passed" || decision === "completed") {
    return { tone: "success", label: "已完成", text: "生成通过，无阻塞失败", openable: false };
  }
  return null;
}

function renderClassificationBanner(container) {
  const projection = state.canvas && state.canvas.projection;
  const summary = projection && projection.run && projection.run.classification_summary;
  const view = classificationBannerView(summary);
  if (!view) return;
  const artifactPath = String((summary && summary.artifact_path) || "codex/failure_classification.md");
  const children = [
    el("span", { className: "app-generation-classification-banner-label" }, [view.label]),
    el("span", { className: "app-generation-classification-banner-text", title: view.text }, [view.text]),
  ];
  if (view.openable) {
    children.push(
      el(
        "button",
        {
          type: "button",
          className: "app-generation-classification-banner-action",
          onclick: () => openClassificationArtifact(artifactPath),
        },
        ["查看诊断"]
      )
    );
  }
  container.appendChild(
    el("div", { className: `app-generation-classification-banner ${view.tone}` }, children)
  );
}

function openClassificationArtifact(artifactPath) {
  const runId = state.selectedRunId;
  if (!runId) return;
  const path = artifactPath || "codex/failure_classification.md";
  openArtifactPreview(
    {
      path,
      title: "失败诊断",
      read_url: `/api/app-generation/runs/${encodeURIComponent(runId)}/artifacts/preview?path=${encodeURIComponent(path)}`,
    },
    "classification_banner"
  );
}

function renderPipelineOverview(nodes) {
  const container = document.getElementById("app-generation-pipeline-overview");
  if (!container) return;
  clear(container);
  if (!nodes.length) return;
  const projection = state.canvas && state.canvas.projection;
  renderClassificationBanner(container);
  const currentId = (projection && projection.current_business_node_id) || "";
  const doneCount = nodes.filter((node) => PIPELINE_DONE_STATUSES.has(node.status)).length;
  const runningNode = currentId ? nodes.find((node) => node.id === currentId) : null;
  const current = runningNode || nodes.find((node) => node.id === state.canvas.selectedBusinessNodeId) || nodes[0];
  const ratio = nodes.length ? Math.round((doneCount / nodes.length) * 100) : 0;
  const titleText = runningNode
    ? `正在执行：第 ${runningNode.stage_index || "-"}/${nodes.length} 步 · ${safeText(runningNode.title, "")}`
    : `第 ${current ? current.stage_index || "-" : "-"}/${nodes.length} 步 · ${current ? safeText(current.title, "") : ""}`;
  container.appendChild(
    el("div", { className: "app-generation-pipeline-overview-head" }, [
      el("span", { className: "app-generation-pipeline-overview-title" + (runningNode ? " running" : "") }, [
        titleText,
      ]),
      el("span", { className: "app-generation-coder-heartbeat", id: "app-generation-coder-heartbeat" }, [
        coderLiveText(),
      ]),
      el("span", { className: "meta" }, [`整体完成度 ${ratio}% · ${doneCount}/${nodes.length} 步就绪`]),
    ])
  );
  const fill = el("div", { className: "app-generation-pipeline-bar-fill" }, []);
  fill.style.width = `${ratio}%`;
  container.appendChild(el("div", { className: "app-generation-pipeline-bar" + (runningNode ? " running" : "") }, [fill]));
}

function pipelineArrow() {
  return el("span", { className: "app-generation-pipeline-arrow", "aria-hidden": "true" }, ["↓"]);
}

function renderBusinessNodeTrack(container, nodes) {
  if (!nodes.length) {
    container.appendChild(el("p", { className: "meta" }, ["暂无业务节点。"]));
    return;
  }
  const projection = state.canvas && state.canvas.projection;
  const currentId = (projection && projection.current_business_node_id) || "";
  const live = state.canvas && state.canvas.coderLive;
  nodes.forEach((node, index) => {
    if (index > 0) container.appendChild(pipelineArrow());
    const selected = node.id === state.canvas.selectedBusinessNodeId;
    const isRunning = node.status === "running" || node.is_current === true || node.id === currentId;
    const progress = node.progress || {};
    const ready = Number(progress.ready_artifacts || 0);
    const required = Number(progress.required_artifacts || 0);
    const oneLiner = Array.isArray(node.process_summary) && node.process_summary.length
      ? node.process_summary[0]
      : "";
    let metaText = required
      ? `产物 ${ready}/${required} · ${node.object_count || 0} 对象`
      : `${node.object_count || 0} 对象`;
    if (isRunning && node.id === "prototype_generation" && live && live.run_id === state.selectedRunId) {
      metaText = `已改 ${live.files_changed || 0} 文件 · 工具 ${live.tool_calls || 0} 次 · 第 ${live.event_seq || 0} 事件`;
    }
    const card = el(
      "button",
      {
        type: "button",
        className:
          "app-generation-business-node-card" +
          (selected ? " selected" : "") +
          (isRunning ? " running" : "") +
          (node.id === currentId ? " current" : "") +
          (node.step_type === "ui" ? " ui-step" : "") +
          (node.is_entry ? " entry" : "") +
          (node.is_terminal ? " terminal" : ""),
        onclick: () => selectCanvasBusinessNode(node.id),
      },
      [
        el("span", { className: "app-generation-business-node-index" }, [String(node.stage_index || "")]),
        el("span", { className: "app-generation-business-node-name" }, [safeText(node.title, "业务节点")]),
        oneLiner ? el("span", { className: "app-generation-business-node-oneliner" }, [oneLiner]) : null,
        el("span", { className: `mini-status ${statusBadge(node.status)}` }, [statusLabel(node.status)]),
        el("span", { className: "meta" }, [metaText]),
      ].filter(Boolean)
    );
    container.appendChild(card);
  });
}

function renderStepDetail(step) {
  const titleEl = document.getElementById("app-generation-step-title");
  const summaryEl = document.getElementById("app-generation-step-summary");
  const statusEl = document.getElementById("app-generation-step-status");
  const cardsEl = document.getElementById("app-generation-step-summary-cards");
  const prdDetail = document.getElementById("app-generation-prd-entry-detail");
  const previewDetail = document.getElementById("app-generation-app-preview-detail");
  if (!step) return;
  if (titleEl) titleEl.textContent = safeText(step.title, "BusinessStep");
  if (summaryEl) summaryEl.textContent = safeText(step.summary || step.latest_event, "选择流程节点查看输入、执行过程、输出和证据。");
  if (statusEl) {
    statusEl.textContent = statusLabel(step.status);
    statusEl.className = `mini-status ${statusBadge(step.status)}`;
  }
  if (prdDetail) prdDetail.hidden = step.id !== "prd_entry";
  if (previewDetail) previewDetail.hidden = step.id !== "app_preview";
  if (!cardsEl) return;
  clear(cardsEl);
  cardsEl.appendChild(renderStepSummaryCard("输入", step.input_summary || []));
  cardsEl.appendChild(renderStepSummaryCard("执行过程", step.process_summary || []));
  cardsEl.appendChild(renderStepSummaryCard("输出", step.output_summary || []));
  cardsEl.appendChild(renderStepActionsCard(step));
  cardsEl.appendChild(renderStepSummaryCard("工程证据", step.evidence_refs || []));
}

function renderStepSummaryCard(title, items) {
  const list = Array.isArray(items) ? items : [];
  return el("section", { className: "app-generation-step-card" }, [
    el("h5", null, [title]),
    list.length
      ? el("ul", null, list.map((item) => el("li", null, [safeText(item, "未记录")])))
      : el("p", { className: "meta" }, ["未记录"]),
  ]);
}

function renderStepActionsCard(step) {
  const actions = Array.isArray(step.available_actions) ? step.available_actions : [];
  const isBusinessStep = (step.step_type || "business") === "business" && Array.isArray(step.runtime_nodes) && step.runtime_nodes.length > 0;
  const children = [el("h5", null, ["你可以让 Agent 做什么"])];
  if (isBusinessStep) {
    children.push(
      el("div", { className: "app-generation-step-action-row triple" }, [
        el("button", { type: "button", className: "ghost small", onclick: () => triggerStepAction(step, "rerun_step") }, ["重跑这一步"]),
        el("button", { type: "button", className: "ghost small", onclick: () => openStepArtifact(step) }, ["看中间产物"]),
        el("button", { type: "button", className: "ghost small", onclick: () => requestStepRevision(step) }, ["让 Agent 改"]),
      ])
    );
  }
  const extraActions = actions.filter((action) => action !== "rerun_step");
  if (extraActions.length) {
    children.push(
      el("div", { className: "app-generation-step-action-row" }, extraActions.map((action) =>
        el("button", { type: "button", className: "ghost small", onclick: () => triggerStepAction(step, action) }, [stepActionLabel(action)])
      ))
    );
  } else if (!isBusinessStep) {
    children.push(el("p", { className: "meta" }, ["未记录"]));
  }
  return el("section", { className: "app-generation-step-card" }, children);
}

function openStepArtifact(step) {
  if (!step) return;
  const nodeId = firstRuntimeNodeForStep(step);
  const node = (state.nodes || []).find((n) => n.id === nodeId);
  const outputs = node && Array.isArray(node.outputs) ? node.outputs : [];
  const item = outputs.find((o) => (o.preview && o.preview.read_url) || o.read_url) || outputs[0];
  if (item) {
    openArtifactPreview(item, "business_step_artifact");
  } else {
    appendAgentLog("system", `「${safeText(step.title, step.id)}」暂无可预览的中间产物。`);
  }
}

function requestStepRevision(step) {
  if (!step) return;
  setAgentFocus("flow_step", { view_mode: "business_step_detail", selected_text: "" });
  const input = document.getElementById("app-generation-agent-input");
  if (input) {
    input.value = `请基于业务步骤「${safeText(step.title, step.id)}」对生成结果做修改，复杂代码改动请委托 Code Agent。`;
    input.focus();
  }
  state.agentMode = "auto";
  const modeSelect = document.getElementById("app-generation-agent-mode");
  if (modeSelect) modeSelect.value = "auto";
}

function stepActionLabel(action) {
  const labels = {
    start_generation: "启动生成",
    explain_prd_requirements: "检查 PRD",
    suggest_input_patch: "补充生成约束",
    explain_step: "解释这一步",
    explain_step_io: "说明输入输出",
    inspect_evidence: "查看证据",
    rerun_step: "重新执行这一步",
    verify_capability: "验证能力",
    publish_app: "发布应用",
    start_preview: "启动预览",
    stop_preview: "停止预览",
    delegate_code_repair: "修复预览问题",
  };
  return labels[action] || action || "Agent 动作";
}

async function triggerStepAction(step, action) {
  if (!step || !action) return;
  setAgentFocus("flow_step", { view_mode: "business_step_detail", selected_text: "" });
  persistState();
  if (action === "start_generation") {
    const input = document.getElementById("app-generation-upload-prd");
    if (input) input.focus();
    appendAgentLog("system", "请在 PRD 输入节点补充 PRD，然后点击「启动生成」。");
    return;
  }
  if (action === "publish_app") {
    if (state.selectedRunId) await publishAppFromUI(state.selectedRunId);
    return;
  }
  if (action === "start_preview") {
    if (state.selectedRunId) await startAppPreviewFromUI(state.selectedRunId);
    return;
  }
  if (action === "stop_preview") {
    if (state.selectedRunId) await stopAppPreviewFromUI(state.selectedRunId);
    return;
  }
  if (action === "inspect_evidence") {
    const evidence = document.getElementById("app-generation-engineering-evidence");
    if (evidence) evidence.open = true;
    appendAgentLog("system", `已展开「${safeText(step.title, "当前步骤")}」的工程证据层。`);
    return;
  }
  if (action === "rerun_step") {
    const nodeId = firstRuntimeNodeForStep(step);
    await triggerRerun(`从业务步骤「${safeText(step.title, step.id)}」重新执行。`, nodeId || state.selectedNodeId);
    return;
  }
  const input = document.getElementById("app-generation-agent-input");
  if (input) {
    input.value = stepActionPrompt(step, action);
    input.focus();
  }
  state.agentMode = "auto";
  const modeSelect = document.getElementById("app-generation-agent-mode");
  if (modeSelect) modeSelect.value = "auto";
  await sendAgentMessage(new Event("submit"));
}

function firstRuntimeNodeForStep(step) {
  const runtimeNodes = Array.isArray(step.runtime_nodes) ? step.runtime_nodes : [];
  const known = new Set((state.nodes || []).map((node) => node.id));
  return runtimeNodes.find((nodeId) => known.has(nodeId)) || "";
}

function stepActionPrompt(step, action) {
  const title = safeText(step.title, step.id || "当前步骤");
  const prompts = {
    explain_prd_requirements: `请检查「${title}」里的 PRD 是否足够生成应用，并指出缺少的业务约束。`,
    suggest_input_patch: `请基于「${title}」补充生成约束，说明会影响后续哪些步骤。`,
    explain_step: `请解释「${title}」这一步在 PRD 生成应用流程中做什么。`,
    explain_step_io: `请说明「${title}」这一步的输入、执行过程和输出。`,
    delegate_code_repair: `请基于「${title}」修复当前预览应用的问题，复杂代码修改请委托 Code Agent。`,
    verify_capability: `请验证「${title}」相关业务能力是否已经在生成应用中实现。`,
  };
  return prompts[action] || `请处理业务步骤「${title}」：${stepActionLabel(action)}。`;
}

function renderCanvasObjects(container, objects) {
  if (!objects.length) {
    container.appendChild(el("p", { className: "meta" }, ["暂无业务对象。"]));
    return;
  }
  for (const object of objects) {
    const selected = object.object_id === state.canvas.selectedObjectId;
    const card = el(
      "button",
      {
        type: "button",
        className: "app-generation-canvas-object" + (selected ? " selected" : ""),
        onclick: () => selectCanvasObject(object.object_id),
      },
      [
        el("div", { className: "app-generation-canvas-object-head" }, [
          el("span", { className: "app-generation-canvas-object-title" }, [safeText(object.title, object.object_id)]),
          el("span", { className: `mini-status ${statusBadge(object.status)}` }, [statusLabel(object.status)]),
        ]),
        el("p", { className: "meta" }, [objectTypeLabel(object.object_type) + " · " + safeText(object.owner_node, "未绑定节点")]),
        el("p", { className: "summary-text" }, [safeText(object.summary, "未记录")]),
      ]
    );
    container.appendChild(card);
  }
}

const OBJECT_ACTION_LABELS = {
  explain_object: "解释对象",
  suggest_object_patch: "建议修改",
  rerun_business_node: "重跑该步骤",
  verify_capability: "验证能力",
  repair_generated_app: "修复应用",
};

const OBJECT_ACTION_MODE = {
  explain_object: "explain",
  suggest_object_patch: "edit",
  rerun_business_node: "rerun",
  verify_capability: "auto",
  repair_generated_app: "explain",
};

const OBJECT_ACTION_PROMPT = {
  explain_object: (o) => `请解释业务对象「${o.title || o.object_id}」的作用、来源，以及它对最终可预览应用的影响。`,
  suggest_object_patch: (o) => `请针对业务对象「${o.title || o.object_id}」给出可执行的修改建议，并说明改动会回流到哪个步骤。`,
  rerun_business_node: (o) => `请准备重跑「${o.owner_node || "该步骤"}」，说明改动点与预期影响。`,
  verify_capability: (o) => `请验证业务能力「${o.title || o.object_id}」是否在生成应用中被正确实现。`,
  repair_generated_app: (o) => `请基于业务对象「${o.title || o.object_id}」诊断并修复生成应用中的问题。`,
};

const EDGE_RELATION_LABELS = {
  requires: "需要",
  produces: "产出",
  evidenced_by: "佐证",
};

function businessActionLabel(action) {
  const key = typeof action === "string" ? action : action && action.type;
  return OBJECT_ACTION_LABELS[key] || key || "Agent 动作";
}

function renderCanvasObjectDetail(container, object) {
  if (!object) {
    container.appendChild(el("p", { className: "meta" }, ["请选择一个业务对象。"]));
    return;
  }
  const sourceRefs = Array.isArray(object.source_refs) ? object.source_refs : [];
  const artifactRefs = Array.isArray(object.artifact_refs) ? object.artifact_refs : [];
  const evidenceRefs = Array.isArray(object.evidence_refs) ? object.evidence_refs : [];
  const actions = Array.isArray(object.actions) ? object.actions : [];
  const upstream = Array.isArray(object.upstream_objects) ? object.upstream_objects : [];
  const downstream = Array.isArray(object.downstream_objects) ? object.downstream_objects : [];
  container.appendChild(
    el("div", { className: "app-generation-canvas-detail-card" }, [
      el("div", { className: "app-generation-canvas-object-head" }, [
        el("strong", null, [safeText(object.title, object.object_id)]),
        el("span", { className: `mini-status ${statusBadge(object.status)}` }, [statusLabel(object.status)]),
      ]),
      el("p", { className: "summary-text" }, [safeText(object.summary, "未记录")]),
      el("dl", { className: "app-generation-dl" }, [
        el("dt", null, ["类型"]),
        el("dd", null, [objectTypeLabel(object.object_type)]),
        el("dt", null, ["所属节点"]),
        el("dd", null, [safeText(object.owner_node, "-")]),
      ]),
      renderObjectRelations("上游对象", upstream),
      renderObjectRelations("下游对象", downstream),
      renderObjectActions(object, actions),
      renderRefGroup("来源", sourceRefs),
      renderRefGroup("产物", artifactRefs),
      renderRefGroup("证据", evidenceRefs),
    ])
  );
}

function renderObjectRelations(title, relations) {
  if (!relations.length) return el("p", { className: "meta" }, [`${title} 未记录`]);
  const chips = relations.map((rel) =>
    el(
      "button",
      {
        type: "button",
        className: "app-generation-relation-chip",
        onclick: () => selectCanvasObject(rel.object_id),
      },
      [
        el("span", { className: "app-generation-relation-name" }, [safeText(rel.title, rel.object_id)]),
        el("span", { className: "meta" }, [
          `${objectTypeLabel(rel.object_type)}${rel.relation ? " · " + (EDGE_RELATION_LABELS[rel.relation] || rel.relation) : ""}`,
        ]),
      ]
    )
  );
  return el("div", { className: "app-generation-relation-group" }, [
    el("span", { className: "app-generation-relation-title" }, [title]),
    el("div", { className: "app-generation-relation-chips" }, chips),
  ]);
}

function renderObjectActions(object, actions) {
  const list = actions.length ? actions : ["explain_object"];
  const buttons = list.map((action) => {
    const key = typeof action === "string" ? action : action && action.type;
    return el(
      "button",
      {
        type: "button",
        className: "app-generation-object-action",
        onclick: () => triggerObjectAction(object, key),
      },
      [businessActionLabel(action)]
    );
  });
  return el("div", { className: "app-generation-object-actions" }, [
    el("span", { className: "app-generation-relation-title" }, ["用 Agent 处理"]),
    el("div", { className: "app-generation-object-action-row" }, buttons),
  ]);
}

function resolveEngineeringNodeIdForStep(step) {
  const runtimeNodes = step && Array.isArray(step.runtime_nodes) ? step.runtime_nodes : [];
  const known = new Set((state.nodes || []).map((node) => node.id));
  for (const nodeId of runtimeNodes) {
    if (known.has(nodeId)) return nodeId;
  }
  return "";
}

function resolveEngineeringNodeId(object) {
  const projection = state.canvas && state.canvas.projection;
  const businessNodes = projection && Array.isArray(projection.business_nodes) ? projection.business_nodes : [];
  const businessNode = businessNodes.find((node) => node.id === (object && object.owner_node_id));
  const resolved = resolveEngineeringNodeIdForStep(businessNode);
  return resolved || state.selectedNodeId || (state.nodes[0] && state.nodes[0].id) || "";
}

async function triggerObjectAction(object, action) {
  if (!object || !action) return;
  const mode = OBJECT_ACTION_MODE[action] || "auto";
  state.agentMode = mode;
  const modeSelect = document.getElementById("app-generation-agent-mode");
  if (modeSelect) modeSelect.value = mode;
  const nodeId = resolveEngineeringNodeId(object);
  if (nodeId && (nodeId !== state.selectedNodeId || !state.nodeContext)) {
    state.selectedNodeId = nodeId;
    const node = (state.nodes || []).find((item) => item.id === nodeId);
    if (node && node.selected_variant) state.selectedVariant = node.selected_variant;
    renderNodes();
    await refreshNodeContext();
  }
  const input = document.getElementById("app-generation-agent-input");
  const promptBuilder = OBJECT_ACTION_PROMPT[action];
  if (input && promptBuilder) input.value = promptBuilder(object);
  setAgentFocus("canvas_object", { view_mode: "canvas_object_detail", selected_text: "" });
  persistState();
  await sendAgentMessage(new Event("submit"));
}

function renderRefGroup(title, refs) {
  if (!refs.length) return el("p", { className: "meta" }, [`${title}：未记录`]);
  return el("p", { className: "meta" }, [`${title}：${refs.slice(0, 5).join("，")}${refs.length > 5 ? "…" : ""}`]);
}

async function selectCanvasBusinessNode(nodeId) {
  if (!nodeId) return;
  state.canvas.selectedBusinessNodeId = nodeId;
  const projection = state.canvas && state.canvas.projection;
  const businessNodes = projection && Array.isArray(projection.business_nodes) ? projection.business_nodes : [];
  const step = businessNodes.find((node) => node.id === nodeId);
  
  // Sync engineering node when business node changes
  if (step) {
    const engineeringNodeId = resolveEngineeringNodeIdForStep(step);
    if (engineeringNodeId && engineeringNodeId !== state.selectedNodeId) {
      state.selectedNodeId = engineeringNodeId;
      const node = (state.nodes || []).find((item) => item.id === engineeringNodeId);
      if (node && node.selected_variant) state.selectedVariant = node.selected_variant;
      renderNodes();
      await refreshNodeContext();
    }
  }
  
  const objects = allCanvasObjects(projection);
  const visibleObjects = filteredCanvasObjects(objects);
  state.canvas.selectedObjectId = visibleObjects[0] ? visibleObjects[0].object_id : "";
  if (state.canvas.selectedObjectId) {
    try {
      await refreshCanvasObjectDetail(state.canvas.selectedObjectId);
    } catch (err) {
      state.canvas.selectedObjectDetail = null;
      appendAgentLog("system", `加载业务对象失败：${err.message}`);
    }
  } else {
    state.canvas.selectedObjectDetail = null;
  }
  setAgentFocus("flow_step", { view_mode: "business_step_detail", selected_text: "" });
  persistState();
  renderCanvasPanel();
  renderNodes();
  renderAgentContextRefs();
}

async function selectCanvasObject(objectId) {
  if (!objectId) return;
  state.canvas.selectedObjectId = objectId;
  const projection = state.canvas && state.canvas.projection;
  const objects = allCanvasObjects(projection);
  const object = objects.find((item) => item.object_id === objectId);
  if (object && object.owner_node_id) {
    state.canvas.selectedBusinessNodeId = object.owner_node_id;
    const engineeringNodeId = resolveEngineeringNodeId(object);
    if (engineeringNodeId && engineeringNodeId !== state.selectedNodeId) {
      state.selectedNodeId = engineeringNodeId;
      const node = (state.nodes || []).find((item) => item.id === engineeringNodeId);
      if (node && node.selected_variant) state.selectedVariant = node.selected_variant;
      renderNodes();
      await refreshNodeContext();
    }
  }
  try {
    await refreshCanvasObjectDetail(objectId);
  } catch (err) {
    state.canvas.selectedObjectDetail = null;
    appendAgentLog("system", `加载业务对象失败：${err.message}`);
  }
  setAgentFocus("canvas_object", { view_mode: "canvas_object_detail", selected_text: "" });
  persistState();
  renderCanvasPanel();
  renderAgentContextRefs();
}

async function applyCanvasFilters() {
  const projection = state.canvas && state.canvas.projection;
  const objects = allCanvasObjects(projection);
  const visibleObjects = filteredCanvasObjects(objects);
  if (!visibleObjects.find((object) => object.object_id === state.canvas.selectedObjectId)) {
    state.canvas.selectedObjectId = visibleObjects[0] ? visibleObjects[0].object_id : "";
    if (state.canvas.selectedObjectId) {
      try {
        await refreshCanvasObjectDetail(state.canvas.selectedObjectId);
      } catch (err) {
        state.canvas.selectedObjectDetail = null;
        appendAgentLog("system", `加载业务对象失败：${err.message}`);
      }
    } else {
      state.canvas.selectedObjectDetail = null;
      setAgentFocus("node_summary", { view_mode: "node_detail", selected_text: "" });
    }
  }
  persistState();
  renderCanvasPanel();
  renderAgentContextRefs();
}

function objectTypeLabel(type) {
  const labels = {
    business_goal: "业务目标",
    user_persona: "用户角色",
    scenario: "业务场景",
    capability: "应用能力",
    page_flow: "页面流程",
    data_object: "数据对象",
    provider_config: "服务配置",
    knowledge_source: "依赖知识",
    tool_call: "工具调用",
    artifact: "中间产物",
    preview_session: "应用预览",
    capability_gap: "能力缺口",
    repair_candidate: "修复候选",
    delivery_version: "可交付版本",
  };
  return labels[type] || type || "业务对象";
}

function renderVariants(node) {
  const container = document.getElementById("app-generation-variants");
  if (!container) return;
  clear(container);
  for (const variant of node.variants || []) {
    const isSelected = variant.variant_id === state.selectedVariant;
    const card = el(
      "button",
      {
        type: "button",
        className: "app-generation-variant" + (isSelected ? " selected" : ""),
        onclick: () => {
          state.selectedVariant = variant.variant_id;
          persistState();
          refreshNodeContext();
        },
      },
      [
        el("div", { className: "app-generation-variant-head" }, [
          el("span", { className: "app-generation-variant-id" }, [variantLabel(variant.variant_id)]),
          el("span", { className: `mini-status ${statusBadge(variant.status)}` }, [statusLabel(variant.status)]),
        ]),
        el("p", { className: "meta" }, [
          `usage：${formatUsage(variant.usage)} · 风险 ${(variant.risks || []).length}`,
        ]),
      ]
    );
    container.appendChild(card);
  }
}

function formatUsage(usage) {
  if (!usage || typeof usage !== "object") return "unknown";
  return `输入 ${usage.prompt_tokens ?? "unknown"} / 输出 ${usage.completion_tokens ?? "unknown"} / 总 ${usage.total_tokens ?? "unknown"}`;
}

function renderSkills(node) {
  const ul = document.getElementById("app-generation-skills");
  if (!ul) return;
  clear(ul);
  for (const skill of node.skills || []) {
    ul.appendChild(
      el("li", { className: "app-generation-skill" }, [
        el("span", { className: "app-generation-skill-id" }, [skill.id]),
        el("span", { className: "meta" }, [
          `${skill.role || "角色未记录"} · ${skill.stage || "阶段未记录"} · ${statusLabel(skill.status)}`,
        ]),
        el("p", { className: "summary-text" }, [safeText(skill.why, "未记录")]),
      ])
    );
  }
}

function renderTimeline(phases) {
  const ol = document.getElementById("app-generation-timeline");
  const metaEl = document.getElementById("app-generation-timeline-meta");
  if (!ol) return;
  clear(ol);
  if (!phases || !phases.length) {
    ol.appendChild(el("li", { className: "app-generation-timeline-empty meta" }, ["暂无 phase 数据"]));
    if (metaEl) metaEl.textContent = "";
    return;
  }
  let done = 0;
  let running = 0;
  for (const phase of phases) {
    const status = String(phase.status || "pending");
    if (status === "completed") done += 1;
    if (status === "running") running += 1;
    const timeLine = [phase.started_at, phase.finished_at].filter(Boolean).join(" → ");
    const artifacts = Array.isArray(phase.artifacts) ? phase.artifacts : [];
    ol.appendChild(
      el("li", { className: `app-generation-timeline-item phase-${status}` }, [
        el("div", { className: "app-generation-timeline-marker" }, [phaseIcon(status)]),
        el("div", { className: "app-generation-timeline-body" }, [
          el("div", { className: "app-generation-timeline-head" }, [
            el("span", { className: "app-generation-timeline-label" }, [safeText(phase.label || phase.id, "未命名 phase")]),
            el("span", { className: `mini-status ${statusBadge(status)}` }, [statusLabel(status)]),
          ]),
          phase.summary ? el("p", { className: "meta" }, [safeText(phase.summary, "")]) : null,
          timeLine ? el("p", { className: "meta" }, [timeLine]) : null,
          artifacts.length ? el("p", { className: "meta" }, [`产物：${artifacts.join("，")}`]) : null,
        ]),
      ])
    );
  }
  if (metaEl) {
    metaEl.textContent = `已完成 ${done}/${phases.length}` + (running ? ` · ${running} 进行中` : "");
  }
}

function phaseIcon(status) {
  if (status === "completed") return "✓";
  if (status === "failed") return "✗";
  if (status === "running") return "●";
  return "○";
}

function renderArtifacts(elementId, items, sourceCard) {
  const ul = document.getElementById(elementId);
  if (!ul) return;
  clear(ul);
  for (const item of items) {
    const link = el("button", {
      type: "button",
      className: "app-generation-artifact-title",
      onclick: (event) => {
        event.stopPropagation();
        openArtifactPreview(item, sourceCard);
      },
    }, [item.title || item.path]);
    const validation = String(item.validation_status || (item.exists ? "success" : "pending"));
    const icon = el("span", {
      className: `app-generation-validation-icon validation-${validation}`,
      title: statusLabel(validation),
    }, [validationIcon(validation)]);
    ul.appendChild(
      el("li", { className: "app-generation-artifact" }, [
        el("div", { className: "app-generation-artifact-head" }, [
          icon,
          link,
          el("span", { className: `mini-status ${statusBadge(item.status)}` }, [statusLabel(item.status)]),
        ]),
        el("p", { className: "meta" }, [safeText(item.summary, "未记录")]),
        el("p", { className: "meta" }, [item.content_hash ? item.content_hash.slice(0, 22) + "…" : "no hash"]),
      ])
    );
  }
}

function renderToolCalls(calls) {
  const ul = document.getElementById("app-generation-tool-calls");
  if (!ul) return;
  clear(ul);
  if (!calls.length) {
    ul.appendChild(el("li", { className: "meta" }, ["未记录"]));
    return;
  }
  for (const call of calls) {
    ul.appendChild(
      el("li", { className: "app-generation-tool-call" }, [
        el("div", null, [
          el("span", { className: "app-generation-tool-name" }, [safeText(call.tool_name, "未记录")]),
          el("span", { className: `mini-status ${statusBadge(call.status)}` }, [statusLabel(call.status)]),
        ]),
        el("p", { className: "meta" }, [safeText(call.input_summary, "未记录")]),
        el("p", { className: "meta" }, [safeText(call.output_summary, "未记录")]),
      ])
    );
  }
}

function renderUsage(usage) {
  const dl = document.getElementById("app-generation-usage");
  if (!dl) return;
  clear(dl);
  const safe = usage && typeof usage === "object" ? usage : {};
  for (const key of ["prompt_tokens", "completion_tokens", "total_tokens", "estimated_cost", "usage_source"]) {
    dl.appendChild(el("dt", null, [usageLabel(key)]));
    dl.appendChild(el("dd", null, [String(safe[key] ?? "unknown")]));
  }
}

function renderScores(scores) {
  const dl = document.getElementById("app-generation-scores");
  if (!dl) return;
  clear(dl);
  for (const key of Object.keys(scores)) {
    dl.appendChild(el("dt", null, [scoreLabel(key)]));
    dl.appendChild(el("dd", null, [String(scores[key])]));
  }
}

function renderRisks(risks) {
  const ul = document.getElementById("app-generation-risks");
  if (!ul) return;
  clear(ul);
  if (!risks.length) {
    ul.appendChild(el("li", { className: "meta" }, ["无风险记录"]));
    return;
  }
  for (const risk of risks) {
    ul.appendChild(
      el("li", { className: "app-generation-risk" }, [
        el("span", { className: `mini-status ${statusBadge(risk.severity)}` }, [statusLabel(risk.severity)]),
        el("p", null, [safeText(risk.summary || risk.id, "未记录")]),
      ])
    );
  }
}

function renderProviders() {
  const select = document.getElementById("app-generation-provider");
  const message = document.getElementById("app-generation-provider-message");
  if (!select) return;
  clear(select);
  for (const provider of state.providerStatuses) {
    const opt = el(
      "option",
      { value: provider.provider },
      [`${provider.provider} · ${provider.status}`]
    );
    select.appendChild(opt);
  }
  if (state.providerStatuses.find((p) => p.provider === state.provider)) {
    select.value = state.provider;
  } else if (state.providerStatuses.length) {
    state.provider = state.providerStatuses[0].provider;
    select.value = state.provider;
    persistState();
  }
  const current = state.providerStatuses.find((p) => p.provider === state.provider);
  if (message) {
    message.textContent = current ? `${current.message} · capabilities: ${(current.capabilities || []).join(", ") || "-"}` : "";
  }
}

function renderAgentContextRefs() {
  const nodeEl = document.getElementById("app-generation-agent-node");
  const variantEl = document.getElementById("app-generation-agent-variant");
  const revisionEl = document.getElementById("app-generation-agent-revision");
  const statusEl = document.getElementById("app-generation-agent-status");
  const node = state.nodes.find((item) => item.id === state.selectedNodeId);
  const focus = (state.interactionContext && state.interactionContext.focus) || {};
  const canvasSelection = buildCanvasSelectionContext();
  if (nodeEl) {
    if (focus.card === "flow_step" && canvasSelection && canvasSelection.title) {
      const engineeringTitle = nodeTitle(node);
      nodeEl.textContent = engineeringTitle
        ? `${canvasSelection.title} · ${engineeringTitle}`
        : canvasSelection.title;
    } else {
      nodeEl.textContent = nodeTitle(node) || "-";
    }
  }
  if (variantEl) variantEl.textContent = variantLabel(state.selectedVariant) || "-";
  const ctx = state.nodeContext;
  if (revisionEl) {
    const rev = ctx ? ctx.context_revision : "";
    revisionEl.textContent = rev ? rev.slice(0, 24) + "…" : "-";
  }
  const focusEl = document.getElementById("app-generation-agent-focus");
  if (focusEl) {
    const card = focus.card || "node_summary";
    if (canvasSelection && card === "canvas_object") {
      focusEl.textContent = `${card} · ${canvasSelection.title}`;
    } else if (canvasSelection && card === "flow_step") {
      focusEl.textContent = `${card} · ${canvasSelection.title}`;
    } else {
      focusEl.textContent = focus.artifact_ref ? `${card} · ${focus.artifact_ref}` : card;
    }
  }
  if (statusEl) {
    if (state.isNewTask) {
      statusEl.textContent = "等待 PRD";
      statusEl.className = "mini-status status-muted";
    } else if (ctx) {
      statusEl.textContent = "已绑定节点";
      statusEl.className = "mini-status status-completed";
    } else {
      statusEl.textContent = "未绑定节点";
      statusEl.className = "mini-status status-muted";
    }
  }
}

async function openArtifactPreview(item, sourceCard) {
  const rail = document.getElementById("app-generation-preview-rail");
  if (!item || !rail) return;
  setAgentFocus("artifact_preview", {
    artifact_ref: item.path || "",
    artifact_title: item.title || item.path || "",
    source_card: sourceCard || "artifact",
    selected_text: getSelectedText(),
    view_mode: "artifact_preview",
  });
  const previewMeta = document.getElementById("app-generation-preview-meta");
  const previewTitle = document.getElementById("app-generation-preview-title");
  const previewContent = document.getElementById("app-generation-preview-content");
  const requestId = ++state.previewRequestSeq;
  state.preview = { item, preview: null, requestId };
  rail.hidden = false;
  const shell = document.querySelector(".app-generation-shell");
  if (shell) shell.classList.add("preview-open");
  if (previewTitle) previewTitle.textContent = item.title || item.path || "文件预览";
  if (previewMeta) {
    clear(previewMeta);
    previewMeta.appendChild(el("dt", null, ["来源"]));
    previewMeta.appendChild(el("dd", null, [item.path || "未记录"]));
    previewMeta.appendChild(el("dt", null, [statusLabel(item.status)]));
    previewMeta.appendChild(el("dd", null, [item.content_hash ? item.content_hash.slice(0, 24) + "…" : "未记录"]));
  }
  if (previewContent) {
    clear(previewContent);
    previewContent.appendChild(el("p", { className: "meta" }, ["加载中…"]));
  }
  const previewUrl = (item.preview && item.preview.read_url) || item.read_url;
  if (!previewUrl) {
    renderPreviewPayload({ kind: "binary", message: "此文件暂无可用预览。", content_hash: item.content_hash, size_bytes: item.size_bytes, path: item.path }, requestId);
    return;
  }
  try {
    const payload = await fetchJSON(previewUrl);
    if (!state.preview || state.preview.requestId !== requestId) return;
    state.preview = { item, preview: payload, requestId };
    renderPreviewPayload(payload, requestId);
  } catch (err) {
    if (!state.preview || state.preview.requestId !== requestId) return;
    renderPreviewPayload({ kind: "binary", message: `预览失败：${err.message}`, path: item.path, content_hash: item.content_hash, size_bytes: item.size_bytes }, requestId);
  }
}

function renderPreviewPayload(payload, requestId) {
  const rail = document.getElementById("app-generation-preview-rail");
  const previewMeta = document.getElementById("app-generation-preview-meta");
  const previewTitle = document.getElementById("app-generation-preview-title");
  const previewContent = document.getElementById("app-generation-preview-content");
  if (!rail || !previewMeta || !previewTitle || !previewContent) return;
  if (requestId && state.preview && state.preview.requestId !== requestId) return;
  rail.hidden = false;
  const shell = document.querySelector(".app-generation-shell");
  if (shell) shell.classList.add("preview-open");
  clear(previewContent);
  clear(previewMeta);
  previewMeta.appendChild(el("dt", null, ["类型"]));
  previewMeta.appendChild(el("dd", null, [safeText(payload.kind, "未记录")]));
  previewMeta.appendChild(el("dt", null, ["MIME"]));
  previewMeta.appendChild(el("dd", null, [safeText(payload.mime_type, "未记录")]));
  previewMeta.appendChild(el("dt", null, ["大小"]));
  previewMeta.appendChild(el("dd", null, [String(payload.size_bytes ?? "unknown")]));
  previewMeta.appendChild(el("dt", null, ["哈希"]));
  previewMeta.appendChild(el("dd", null, [safeText(payload.content_hash ? payload.content_hash.slice(0, 24) + "…" : "", "未记录")]));
  previewTitle.textContent = payload.title || payload.path || "文件预览";
  if (payload.kind === "image" && payload.data_url) {
    previewContent.appendChild(el("img", { src: payload.data_url, alt: payload.path || "preview" }));
    return;
  }
  if (payload.kind === "pdf" && payload.data_url) {
    previewContent.appendChild(el("iframe", { src: payload.data_url, title: payload.path || "preview" }));
    return;
  }
  if (payload.kind === "binary" || payload.kind === "too_large") {
    previewContent.appendChild(el("p", { className: "meta" }, [safeText(payload.message, "此文件暂不支持预览。")]));
    return;
  }
  const text = payload.content || payload.message || "";
  if (payload.mime_type === "application/json" && text) {
    try {
      previewContent.appendChild(el("pre", null, [JSON.stringify(JSON.parse(text), null, 2)]));
      return;
    } catch (err) {
      // fall through to raw text
    }
  }
  previewContent.appendChild(el("pre", null, [text || "未记录"]));
}

function closeArtifactPreview() {
  const rail = document.getElementById("app-generation-preview-rail");
  const shell = document.querySelector(".app-generation-shell");
  if (state.appPreview) {
    return;
  }
  if (rail) rail.hidden = true;
  if (shell) shell.classList.remove("preview-open");
  state.preview = null;
  state.previewRequestSeq += 1;
  setAgentFocus("node_summary", { view_mode: "node_detail", selected_text: "" });
}

async function publishApp(runId, appSlug) {
  const body = appSlug ? { app_slug: appSlug } : {};
  return fetchJSON(`/api/app-generation/runs/${encodeURIComponent(runId)}/publish-app`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function startAppPreview(runId, appSlug) {
  const body = appSlug ? { app_slug: appSlug } : {};
  return fetchJSON(`/api/app-generation/runs/${encodeURIComponent(runId)}/preview/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function stopAppPreview(runId) {
  return fetchJSON(`/api/app-generation/runs/${encodeURIComponent(runId)}/preview/stop`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
}

async function getAppPreviewStatus(runId) {
  return fetchJSON(`/api/app-generation/runs/${encodeURIComponent(runId)}/preview/status`);
}

async function getAppPreviewLogs(runId, tail) {
  const query = tail ? `?tail=${tail}` : "";
  return fetchJSON(`/api/app-generation/runs/${encodeURIComponent(runId)}/preview/logs${query}`);
}

async function patchAppFile(runId, payload) {
  return fetchJSON(`/api/app-generation/runs/${encodeURIComponent(runId)}/patch-app`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

async function startDelegateCodeRepair(runId, payload) {
  return fetchJSON(`/api/app-generation/runs/${encodeURIComponent(runId)}/delegate-code-repair`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

async function applyDelegateCodeRepair(runId, payload) {
  return fetchJSON(`/api/app-generation/runs/${encodeURIComponent(runId)}/delegate-code-repair/apply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

async function getDelegateCodeRepairStatus(runId, repairId) {
  return fetchJSON(`/api/app-generation/runs/${encodeURIComponent(runId)}/delegate-code-repair/status?repair_id=${encodeURIComponent(repairId)}&tail=5`);
}

function createRepairId() {
  return `repair-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

function startDelegateRepairProgressPolling(runId, repairId) {
  stopDelegateRepairProgressPolling();
  appendAgentLog("system", `Code Agent 修复进度：已接收修复请求（${repairId}）。`);
  let lastEventId = "";
  state.delegateRepairPollInterval = window.setInterval(async () => {
    try {
      const status = await getDelegateCodeRepairStatus(runId, repairId);
      const events = Array.isArray(status.latest_events) ? status.latest_events : [];
      const latest = events[events.length - 1];
      if (latest && latest.event_id && latest.event_id !== lastEventId) {
        lastEventId = latest.event_id;
        appendAgentLog("system", `Code Agent 修复进度：${latest.title || status.status || "执行中"}${latest.summary ? ` · ${latest.summary}` : ""}`);
      } else if (status.progress_status && status.progress_status.current_title && status.progress_status.latest_event_id !== lastEventId) {
        lastEventId = status.progress_status.latest_event_id || lastEventId;
        appendAgentLog("system", `Code Agent 修复进度：${status.progress_status.current_title}${status.progress_status.current_summary ? ` · ${status.progress_status.current_summary}` : ""}`);
      }
      if (status.result_ready || ["prepared", "failed", "applied"].includes(status.status)) {
        stopDelegateRepairProgressPolling();
      }
    } catch (_err) {
      // prepare 可能尚未创建 progress 文件，下一轮继续。
    }
  }, 2000);
}

function stopDelegateRepairProgressPolling() {
  if (state.delegateRepairPollInterval) {
    window.clearInterval(state.delegateRepairPollInterval);
    state.delegateRepairPollInterval = null;
  }
}

function renderDiffLines(diffText) {
  const container = el("pre", { className: "app-generation-diff-body" });
  if (!diffText) {
    container.appendChild(el("div", { className: "app-generation-diff-line context" }, ["(空 diff)"]));
    return container;
  }
  const lines = diffText.split("\n");
  for (const raw of lines) {
    let cls = "context";
    if (raw.startsWith("+++") || raw.startsWith("---")) cls = "filehdr";
    else if (raw.startsWith("@@")) cls = "hunk";
    else if (raw.startsWith("+")) cls = "add";
    else if (raw.startsWith("-")) cls = "del";
    container.appendChild(el("div", { className: `app-generation-diff-line ${cls}` }, [raw || " "]));
  }
  return container;
}

function showDiffModal({ targetPath, editKind, summary, diff }) {
  return new Promise((resolve) => {
    const overlay = el("div", { className: "app-generation-diff-overlay" });
    const card = el("div", { className: "app-generation-diff-card" });
    const header = el("header", { className: "app-generation-diff-header" }, [
      el("h3", null, ["确认 patch_app 改动"]),
      el("p", { className: "eyebrow" }, [`文件：${targetPath} · 方式：${editKind}`]),
      summary ? el("p", { className: "app-generation-diff-summary" }, [`说明：${summary}`]) : null,
      el("p", { className: "app-generation-diff-hint" }, ["确认后将写入已发布快照并触发两阶段重启。"]),
    ].filter(Boolean));
    const body = renderDiffLines(diff);
    const footer = el("footer", { className: "app-generation-diff-footer" });
    const cancelBtn = el("button", { className: "btn-secondary", type: "button" }, ["取消"]);
    const okBtn = el("button", { className: "btn-primary", type: "button" }, ["应用"]);
    cancelBtn.addEventListener("click", () => { cleanup(); resolve(false); });
    okBtn.addEventListener("click", () => { cleanup(); resolve(true); });
    overlay.addEventListener("click", (ev) => { if (ev.target === overlay) { cleanup(); resolve(false); } });
    function cleanup() { overlay.remove(); document.removeEventListener("keydown", onKey); }
    function onKey(ev) {
      if (ev.key === "Escape") { cleanup(); resolve(false); }
      else if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) { cleanup(); resolve(true); }
    }
    document.addEventListener("keydown", onKey);
    footer.appendChild(cancelBtn);
    footer.appendChild(okBtn);
    card.appendChild(header);
    card.appendChild(body);
    card.appendChild(footer);
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    okBtn.focus();
  });
}

function openAppPreviewRail(previewData) {
  const rail = document.getElementById("app-generation-preview-rail");
  const shell = document.querySelector(".app-generation-shell");
  const previewMeta = document.getElementById("app-generation-preview-meta");
  const previewTitle = document.getElementById("app-generation-preview-title");
  const previewContent = document.getElementById("app-generation-preview-content");
  if (!rail || !previewMeta || !previewTitle || !previewContent) return;

  state.appPreview = previewData;
  state.preview = null;
  state.previewRequestSeq += 1;

  rail.hidden = false;
  rail.dataset.mode = "app_preview";
  if (shell) shell.classList.add("preview-open");

  previewTitle.textContent = `应用预览 · ${previewData.app_slug || ""}`;

  clear(previewMeta);
  previewMeta.appendChild(el("dt", null, ["URL"]));
  previewMeta.appendChild(el("dd", null, [previewData.url || "-"]));
  previewMeta.appendChild(el("dt", null, ["端口"]));
  previewMeta.appendChild(el("dd", null, [String(previewData.port ?? "-")]));
  previewMeta.appendChild(el("dt", null, ["进程"]));
  previewMeta.appendChild(el("dd", null, [String(previewData.pid ?? "-")]));
  previewMeta.appendChild(el("dt", null, ["健康"]));
  previewMeta.appendChild(el("dd", null, [String(previewData.health_status || previewData.status || "-")]));

  renderAppPreviewIframe(previewData);

  setAgentFocus("app_preview", { view_mode: "app_preview", selected_text: "" });
  startAppPreviewPolling(previewData.run_id || state.selectedRunId);
}

function closeAppPreviewRail() {
  const rail = document.getElementById("app-generation-preview-rail");
  const shell = document.querySelector(".app-generation-shell");
  state.appPreview = null;
  stopAppPreviewPolling();
  if (rail) {
    rail.hidden = true;
    delete rail.dataset.mode;
  }
  if (shell) shell.classList.remove("preview-open");
  setAgentFocus("node_summary", { view_mode: "node_detail", selected_text: "" });
}

function startAppPreviewPolling(runId) {
  stopAppPreviewPolling();
  if (!runId) return;
  state.appPreviewPollInterval = window.setInterval(async () => {
    if (!state.appPreview || state.appPreview.run_id !== runId) {
      stopAppPreviewPolling();
      return;
    }
    try {
      const status = await getAppPreviewStatus(runId);
      const previewMeta = document.getElementById("app-generation-preview-meta");
      if (!previewMeta) return;
      const dds = previewMeta.querySelectorAll("dd");
      if (dds.length >= 4) dds[3].textContent = String(status.health_status || status.status || "-");
      if (status.status === "stale" || status.status === "stopped" || status.status === "not_running") {
        appendAgentLog("system", `预览进程已停止（${status.status}）。`);
        closeAppPreviewRail();
      }
    } catch (_err) {
      // ignore transient
    }
  }, 3000);
}

function stopAppPreviewPolling() {
  if (state.appPreviewPollInterval) {
    window.clearInterval(state.appPreviewPollInterval);
    state.appPreviewPollInterval = null;
  }
}

async function publishAppFromUI(runId) {
  const status = document.getElementById("app-generation-app-preview-status");
  if (status) status.textContent = "正在发布应用快照…";
  try {
    const result = await publishApp(runId);
    state.selectedRun = {
      ...(state.selectedRun || {}),
      run_id: runId,
      publish_status: {
        status: "published",
        app_slug: result.app_slug || "",
        published_at: result.published_at || "",
        source_commit: result.source_commit || "unknown",
        message: "应用快照已发布，可以启动预览。",
      },
    };
    state.runs = (state.runs || []).map((run) => {
      if (!run || run.run_id !== runId) return run;
      return { ...run, publish_status: state.selectedRun.publish_status };
    });
    if (status) status.textContent = `已发布：${result.app_slug} · ${result.files_count} 文件`;
    renderPreviewControls();
    appendAgentLog("system", `已发布 ${result.app_slug}（${result.files_count} 个文件）。`);
    return result;
  } catch (err) {
    if (status) status.textContent = `发布失败：${err.message}`;
    appendAgentLog("system", `发布失败：${err.message}`);
    throw err;
  }
}

async function startAppPreviewFromUI(runId) {
  const status = document.getElementById("app-generation-app-preview-status");
  const publishStatus = currentPublishStatus();
  if (publishStatus.status !== "published") {
    if (status) status.textContent = "未发布，请先点击「发布应用快照」。";
    appendAgentLog("system", "启动预览前需要先发布应用快照。");
    renderPreviewControls();
    return null;
  }
  if (status) status.textContent = "正在启动应用预览…";
  try {
    const result = await startAppPreview(runId);
    if (status) status.textContent = `预览已启动：${result.url}`;
    openAppPreviewRail({ ...result, run_id: runId });
    return result;
  } catch (err) {
    const msg = String(err.message || "");
    if (msg.includes("app_not_published")) {
      if (status) status.textContent = "未发布，请先点击「发布应用快照」。";
      appendAgentLog("system", "启动预览前需要先发布应用快照。");
      return null;
    }
    if (status) status.textContent = `启动预览失败：${err.message}`;
    appendAgentLog("system", `启动预览失败：${err.message}`);
    throw err;
  }
}

async function stopAppPreviewFromUI(runId) {
  const status = document.getElementById("app-generation-app-preview-status");
  if (status) status.textContent = "正在停止应用预览…";
  try {
    await stopAppPreview(runId);
    if (status) status.textContent = "已停止应用预览。";
  } catch (err) {
    if (status) status.textContent = `停止失败：${err.message}`;
    appendAgentLog("system", `停止预览失败：${err.message}`);
  } finally {
    closeAppPreviewRail();
  }
}

async function toggleAppPreviewLogs(runId) {
  const previewContent = document.getElementById("app-generation-preview-content");
  if (!previewContent || !state.appPreview) return;
  
  const isLogsView = previewContent.dataset.view === "logs";
  if (isLogsView) {
    renderAppPreviewIframe(state.appPreview);
    return;
  }
  
  clear(previewContent);
  previewContent.dataset.view = "logs";
  
  const toolbar = el("div", { className: "app-generation-app-preview-toolbar" }, [
    el("button", {
      type: "button",
      className: "ghost small",
      onclick: () => toggleAppPreviewLogs(runId),
    }, ["返回预览"]),
    el("button", {
      type: "button",
      className: "ghost small",
      onclick: () => refreshAppPreviewLogs(runId),
    }, ["刷新日志"]),
  ]);
  previewContent.appendChild(toolbar);
  
  const logContainer = el("div", { className: "app-generation-app-preview-logs", id: "app-generation-app-preview-logs-content" }, [
    el("p", { className: "meta" }, ["加载中…"]),
  ]);
  previewContent.appendChild(logContainer);
  
  await refreshAppPreviewLogs(runId);
}

async function refreshAppPreviewLogs(runId) {
  const logContainer = document.getElementById("app-generation-app-preview-logs-content");
  if (!logContainer) return;
  
  try {
    const result = await getAppPreviewLogs(runId, 200);
    clear(logContainer);
    
    if (result.error) {
      logContainer.appendChild(el("p", { className: "meta" }, [`错误：${result.error}`]));
      return;
    }
    
    const lines = result.lines || [];
    const total = result.total_lines || 0;
    const tail = result.tail || 200;
    
    if (!lines.length) {
      logContainer.appendChild(el("p", { className: "meta" }, ["日志为空。"]));
      return;
    }
    
    const metaLine = total > tail
      ? `显示最后 ${lines.length} 行（共 ${total} 行）`
      : `共 ${lines.length} 行`;
    logContainer.appendChild(el("p", { className: "meta" }, [metaLine]));
    
    const pre = el("pre", { className: "app-generation-app-preview-logs-content" });
    for (const line of lines) {
      pre.appendChild(document.createTextNode(line + "\n"));
    }
    logContainer.appendChild(pre);
    pre.scrollTop = pre.scrollHeight;
  } catch (err) {
    clear(logContainer);
    logContainer.appendChild(el("p", { className: "meta" }, [`加载失败：${err.message}`]));
  }
}

function renderAppPreviewIframe(previewData) {
  const previewContent = document.getElementById("app-generation-preview-content");
  if (!previewContent) return;
  
  delete previewContent.dataset.view;
  clear(previewContent);
  
  const toolbar = el("div", { className: "app-generation-app-preview-toolbar" }, [
    el("button", {
      type: "button",
      className: "ghost small",
      onclick: () => {
        if (previewData.url) window.open(previewData.url, "_blank", "noopener");
      },
    }, ["在新窗口打开"]),
    el("button", {
      type: "button",
      className: "ghost small",
      onclick: () => toggleAppPreviewLogs(previewData.run_id || state.selectedRunId),
    }, ["查看日志"]),
    el("button", {
      type: "button",
      className: "ghost small",
      onclick: () => stopAppPreviewFromUI(previewData.run_id || state.selectedRunId),
    }, ["停止预览"]),
  ]);
  previewContent.appendChild(toolbar);

  if (previewData.url) {
    const iframe = el("iframe", {
      src: previewData.url,
      title: `app-preview-${previewData.app_slug || ""}`,
      sandbox: "allow-scripts allow-forms allow-same-origin",
      className: "app-generation-app-preview-iframe",
    });
    previewContent.appendChild(iframe);
  } else {
    previewContent.appendChild(el("p", { className: "meta" }, ["预览未返回 URL。"]));
  }
}

function renderAgentActions(actions) {
  const list = el("ul", { className: "app-generation-agent-actions" });
  for (const action of actions || []) {
    const sourceLine = agentActionSourceLine(action);
    const button = el(
      "button",
      {
        type: "button",
        className: "ghost small",
        onclick: () => handleAgentAction(action),
      },
      [action.requires_confirmation ? "确认" : "执行"]
    );
    const li = el("li", null, [
      el("div", { className: "app-generation-agent-action-row" }, [
        el("span", { className: "app-generation-agent-action-title" }, [agentActionTitle(action)]),
        button,
      ]),
      sourceLine ? el("p", { className: "app-generation-agent-action-source" }, [sourceLine]) : null,
      el("p", { className: "meta" }, [agentActionSummary(action)]),
    ].filter(Boolean));
    list.appendChild(li);
  }
  return list;
}

async function handleAgentAction(action) {
  if (!action || !action.type) return;
  if (action.requires_confirmation) {
    const ok = window.confirm ? window.confirm(`确认执行：${agentActionTitle(action)}？`) : true;
    if (!ok) return;
  }
  if (action.type === "read_artifact") {
    const artifact = findArtifactByPath(action.target_artifact);
    if (artifact) await openArtifactPreview(artifact, "agent_action");
    return;
  }
  if (action.type === "suggest_input_patch" || action.type === "suggest_artifact_patch") {
    const input = document.getElementById("app-generation-agent-input");
    if (input) {
      input.value = action.override_instructions || action.patch_summary || action.summary || "";
      input.focus();
    }
    appendAgentLog("system", "已把调整说明放入输入框，确认后可发送或从节点重跑。");
    return;
  }
  if (action.type === "patch_app") {
    await handlePatchAppAction(action);
    return;
  }
  if (action.type === "delegate_code_repair") {
    await handleDelegateCodeRepairAction(action);
    return;
  }
  if (action.type === "repair_generated_app") {
    if (action.repair_request) {
      await handleDelegateCodeRepairAction({ ...action, type: "delegate_code_repair" });
    } else {
      appendAgentLog("system", "这个对象需要修复，但当前动作缺少 repair_request。请让 Agent 生成“委托 Code Agent 修复”的结构化请求。");
    }
    return;
  }
  if (action.type === "verify_capability") {
    await handleVerifyCapabilityAction(action);
    return;
  }
  if (action.type === "explain_step" || action.type === "explain_step_io") {
    appendAgentLog("system", `${agentActionSourceLine(action) || "当前业务步骤"}：${agentActionSummary(action) || "已聚焦到该业务步骤。"}`);
    return;
  }
  if (action.type === "inspect_evidence") {
    const evidence = document.getElementById("app-generation-engineering-evidence");
    if (evidence) evidence.open = true;
    renderNodes();
    appendAgentLog("system", `${agentActionSourceLine(action) || "当前业务步骤"}：已展开对应工程证据。`);
    return;
  }
  if (action.type === "rerun_step") {
    await triggerRerun(
      action.override_instructions || action.patch_summary || action.summary || "",
      action.rerun_from_node || action.target_node_id || state.selectedNodeId
    );
    return;
  }
  if (action.type === "explain_object") {
    appendAgentLog("system", `${agentActionSourceLine(action) || "当前对象"}：${agentActionSummary(action) || "已聚焦到该业务对象。"}`);
    return;
  }
  if (action.type === "patch_artifact") {
    appendAgentLog("system", `patch_artifact 暂未在 UI 接线（target_node=${action.target_node || "-"}，target_path=${action.target_path || "-"}）。`);
    return;
  }
  if (action.type === "suggest_artifact_regeneration" || action.type === "rerun_from_node") {
    await triggerRerun(
      action.override_instructions || action.patch_summary || action.summary || "",
      action.target_node_id || action.rerun_from_node || state.selectedNodeId
    );
    return;
  }
  if (action.type === "select_variant" && action.selected_variant) {
    state.selectedVariant = action.selected_variant;
    persistState();
    await refreshNodeContext();
    appendAgentLog("system", `已切换到 ${variantLabel(state.selectedVariant)}。`);
    return;
  }
  appendAgentLog("system", `${agentActionTitle(action)} 已记录，暂无自动执行步骤。`);
}

async function handleVerifyCapabilityAction(action) {
  if (!state.selectedRunId) {
    appendAgentLog("system", "验证业务能力需要先选择 run。");
    return;
  }
  appendAgentLog("system", `正在刷新能力证据：${action.source_object_title || action.summary || "当前业务对象"}…`);
  const evidence = [];
  try {
    const status = await getAppPreviewStatus(state.selectedRunId);
    evidence.push(`预览状态 ${status.status || "unknown"}${status.health_status ? ` · 健康 ${status.health_status}` : ""}`);
  } catch (err) {
    evidence.push(`预览状态暂不可用：${err.message}`);
  }
  try {
    await refreshCanvasProjection(state.selectedRunId);
    renderCanvasPanel();
    evidence.push("生成画布已刷新");
  } catch (err) {
    evidence.push(`生成画布刷新失败：${err.message}`);
  }
  appendAgentLog("system", `验证动作完成：${evidence.join("；")}。`);
}

async function handleDelegateCodeRepairAction(action) {
  if (!state.selectedRunId) {
    appendAgentLog("system", "delegate_code_repair 需要先选择 run。");
    return;
  }
  const repairRequest = action.repair_request || {};
  if (!repairRequest || typeof repairRequest !== "object") {
    appendAgentLog("system", "delegate_code_repair 缺少 repair_request。");
    return;
  }
  const repairId = action.repair_id || createRepairId();
  appendAgentLog("system", "正在委托 Code Agent 准备候选修复 diff…");
  startDelegateRepairProgressPolling(state.selectedRunId, repairId);
  let prepared;
  try {
    prepared = await startDelegateCodeRepair(state.selectedRunId, {
      repair_id: repairId,
      repair_request: repairRequest,
      action_id: action.action_id || "",
      agent_provider: action.source || action.provider || "",
    });
  } catch (err) {
    stopDelegateRepairProgressPolling();
    appendAgentLog("system", `delegate_code_repair prepare 失败：${err.message}`);
    return;
  }
  stopDelegateRepairProgressPolling();
  const risks = Array.isArray(prepared.risk_events) ? prepared.risk_events : [];
  const blockers = Array.isArray(prepared.blockers) ? prepared.blockers : [];
  appendAgentLog(
    "system",
    `Code Agent 候选修复状态：${prepared.status || "unknown"} · 改动 ${(prepared.changed_files || []).length} 个文件` +
      (risks.length || blockers.length ? ` · 风险/阻塞 ${risks.length + blockers.length}` : "")
  );
  if (prepared.status !== "prepared") {
    appendAgentLog("system", "候选修复未通过 prepare，旧应用未修改。", prepared);
    return;
  }
  const userConfirmed = await showDiffModal({
    targetPath: (prepared.changed_files || []).join("，") || prepared.app_slug || "published app",
    editKind: "delegate_code_repair",
    summary: action.summary || repairRequest.problem || "Code Agent 候选修复",
    diff: prepared.diff || "",
  });
  if (!userConfirmed) {
    appendAgentLog("system", "用户取消了 delegate_code_repair apply，旧应用未修改。");
    return;
  }
  appendAgentLog("system", "正在应用 Code Agent 候选修复并重启预览…");
  try {
    const applied = await applyDelegateCodeRepair(state.selectedRunId, {
      repair_id: prepared.repair_id,
      action_id: action.action_id || "",
      summary: action.summary || repairRequest.problem || "",
      agent_provider: action.source || action.provider || "",
    });
    const restart = applied.restart || {};
    const restartLine = restart.status
      ? `重启：${restart.status}${restart.new_pid ? ` · 新 pid=${restart.new_pid}` : ""}${restart.url ? ` · ${restart.url}` : ""}`
      : "未触发重启（预览未启动）";
    appendAgentLog("system", `delegate_code_repair 已应用。${restartLine}`);
    if (restart.url && state.appPreview) {
      const iframe = document.querySelector(".app-generation-app-preview-iframe");
      if (iframe) iframe.src = restart.url + "?t=" + Date.now();
      state.appPreview = { ...state.appPreview, url: restart.url, port: restart.new_port, pid: restart.new_pid };
    }
    await refreshNodeContext();
  } catch (err) {
    appendAgentLog("system", `delegate_code_repair apply 失败：${err.message}`);
  }
}

async function handlePatchAppAction(action) {
  if (!state.selectedRunId) {
    appendAgentLog("system", "patch_app 需要先选择 run。");
    return;
  }
  const patches = Array.isArray(action.patches) ? action.patches : [];
  const targetPath = action.target_path || patches[0]?.target_path || "";
  const editKind = action.edit_kind || patches[0]?.edit_kind || "";
  const summary = action.summary || action.patch_summary || "";
  const patchPayload = {
    summary,
    action_id: action.action_id || "",
    patch_set_id: action.patch_set_id || "",
    problem_source: action.problem_source || "",
    preserve_capabilities: Array.isArray(action.preserve_capabilities) ? action.preserve_capabilities : [],
    verification: Array.isArray(action.verification) ? action.verification : [],
  };
  if (patches.length) {
    patchPayload.patches = patches.map((patch) => ({
      target_path: patch.target_path || "",
      edit_kind: patch.edit_kind || "",
      new_content: patch.new_content || "",
      old_content: patch.old_content || "",
      anchor: patch.anchor || "",
      summary: patch.summary || summary,
    }));
  } else {
    patchPayload.target_path = targetPath;
    patchPayload.edit_kind = editKind;
    patchPayload.new_content = action.new_content || "";
    patchPayload.old_content = action.old_content || "";
    patchPayload.anchor = action.anchor || "";
  }

  const invalidPatch = patches.length
    ? patchPayload.patches.find((patch) => !patch.target_path || !patch.edit_kind)
    : (!targetPath || !editKind);
  if (invalidPatch) {
    appendAgentLog("system", `patch_app 缺少 target_path 或 edit_kind（target_path=${targetPath || "-"}，edit_kind=${editKind || "-"}）。`);
    return;
  }

  const targetLabel = patches.length > 1 ? `${patches.length} 个文件` : targetPath;
  const editLabel = patches.length > 1 ? "PatchSet" : editKind;
  appendAgentLog("system", `正在预览 patch_app 改动（${targetLabel} · ${editLabel}）…`);
  let dryRunResult;
  try {
    dryRunResult = await patchAppFile(state.selectedRunId, { ...patchPayload, dry_run: true });
  } catch (err) {
    appendAgentLog("system", `patch_app dry_run 失败：${err.message}`);
    return;
  }

  const userConfirmed = await showDiffModal({
    targetPath: patches.length > 1 ? (dryRunResult.patches || []).map((patch) => patch.target_path).join("，") : targetPath,
    editKind: editLabel,
    summary,
    diff: dryRunResult.diff || "",
  });

  if (!userConfirmed) {
    appendAgentLog("system", "用户取消了 patch_app。");
    return;
  }

  appendAgentLog("system", `正在应用 patch_app（${targetLabel} · ${editLabel}）…`);
  try {
    const result = await patchAppFile(state.selectedRunId, patchPayload);
    const restart = result.restart || {};
    const restartLine = restart.status
      ? `重启：${restart.status}${restart.new_pid ? ` · 新 pid=${restart.new_pid}` : ""}${restart.url ? ` · ${restart.url}` : ""}`
      : "未触发重启（预览未启动）";
    appendAgentLog("system", `patch_app 成功。${restartLine}`);
    if (restart.url && state.appPreview) {
      const iframe = document.querySelector(".app-generation-app-preview-iframe");
      if (iframe) iframe.src = restart.url + "?t=" + Date.now();
      state.appPreview = { ...state.appPreview, url: restart.url, port: restart.new_port, pid: restart.new_pid };
    }
  } catch (err) {
    appendAgentLog("system", `patch_app 失败：${err.message}`);
  }
}

function appendAgentLog(role, text, payload) {
  state.agentLog.push({ role, text, payload, at: new Date().toISOString() });
  const container = document.getElementById("app-generation-agent-log");
  if (!container) return null;
  const entry = el("article", { className: `app-generation-agent-entry role-${role}` }, [
    el("p", { className: "eyebrow" }, [`${role} · ${new Date().toLocaleTimeString()}`]),
    el("p", null, [text]),
  ]);
  if (payload && payload.actions && payload.actions.length) {
    entry.appendChild(renderAgentActions(payload.actions));
  }
  container.appendChild(entry);
  container.scrollTop = container.scrollHeight;
  return entry;
}

function agentLogNearBottom(container) {
  if (!container) return true;
  return container.scrollHeight - container.scrollTop - container.clientHeight < 80;
}

function maybeScrollAgentLog(container, wasNearBottom) {
  if (container && wasNearBottom) container.scrollTop = container.scrollHeight;
}

function renderInlineMarkdown(text) {
  const nodes = [];
  const src = String(text || "");
  const pattern = /(\*\*([^*]+)\*\*)|(`([^`]+)`)|(\[([^\]]+)\]\((https?:\/\/[^\s)]+)\))/g;
  let lastIndex = 0;
  let match;
  while ((match = pattern.exec(src)) !== null) {
    if (match.index > lastIndex) nodes.push(document.createTextNode(src.slice(lastIndex, match.index)));
    if (match[1]) nodes.push(el("strong", null, [match[2]]));
    else if (match[3]) nodes.push(el("code", { className: "app-generation-md-code-inline" }, [match[4]]));
    else if (match[5]) nodes.push(el("a", { href: match[7], target: "_blank", rel: "noopener noreferrer" }, [match[6]]));
    lastIndex = pattern.lastIndex;
  }
  if (lastIndex < src.length) nodes.push(document.createTextNode(src.slice(lastIndex)));
  return nodes;
}

function renderMarkdownInto(container, text) {
  if (!container) return;
  clear(container);
  const lines = String(text || "").split("\n");
  let i = 0;
  let listNode = null;
  let listType = "";
  const flushList = () => {
    if (listNode) container.appendChild(listNode);
    listNode = null;
    listType = "";
  };
  while (i < lines.length) {
    const line = lines[i];
    const fence = line.match(/^```(.*)$/);
    if (fence) {
      flushList();
      const codeLines = [];
      i += 1;
      while (i < lines.length && !/^```/.test(lines[i])) {
        codeLines.push(lines[i]);
        i += 1;
      }
      i += 1;
      const pre = el("pre", { className: "app-generation-md-code-block" }, [
        el("code", null, [codeLines.join("\n")]),
      ]);
      container.appendChild(pre);
      continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.*)$/);
    if (heading) {
      flushList();
      const level = heading[1].length;
      const tag = level === 1 ? "h4" : level === 2 ? "h5" : "h6";
      container.appendChild(el(tag, { className: "app-generation-md-heading" }, renderInlineMarkdown(heading[2])));
      i += 1;
      continue;
    }
    const ordered = line.match(/^\s*\d+\.\s+(.*)$/);
    const unordered = line.match(/^\s*[-*]\s+(.*)$/);
    if (ordered || unordered) {
      const wantType = ordered ? "ol" : "ul";
      if (listType !== wantType) {
        flushList();
        listNode = el(wantType, { className: "app-generation-md-list" }, []);
        listType = wantType;
      }
      listNode.appendChild(el("li", null, renderInlineMarkdown((ordered || unordered)[1])));
      i += 1;
      continue;
    }
    if (!line.trim()) {
      flushList();
      i += 1;
      continue;
    }
    flushList();
    container.appendChild(el("p", { className: "app-generation-md-paragraph" }, renderInlineMarkdown(line)));
    i += 1;
  }
  flushList();
}

const AGENT_PHASE_LABELS = {
  preparing_context: "正在准备上下文…",
  connecting_model: "正在连接模型…",
  thinking: "思考中…",
};

function startStreamingAgentBubble(providerLabel, options) {
  const container = document.getElementById("app-generation-agent-log");
  if (!container) return null;
  const onStop = options && typeof options.onStop === "function" ? options.onStop : null;
  const eyebrow = el("p", { className: "eyebrow" }, [`助手 · ${providerLabel} · ${new Date().toLocaleTimeString()}`]);
  const statusLine = el("p", { className: "app-generation-agent-thinking" }, [
    el("span", { className: "app-generation-agent-thinking-dots" }, [el("span"), el("span"), el("span")]),
    el("span", { className: "app-generation-agent-thinking-text" }, [AGENT_PHASE_LABELS.thinking]),
  ]);
  const body = el("div", { className: "app-generation-agent-stream-body app-generation-md" }, []);
  body.hidden = true;
  const tools = el("ul", { className: "app-generation-agent-tools" });
  const head = el("div", { className: "app-generation-agent-entry-head" }, [eyebrow]);
  if (onStop) {
    const stopBtn = el("button", { type: "button", className: "ghost small app-generation-agent-stop", onclick: () => onStop() }, ["停止"]);
    head.appendChild(stopBtn);
  }
  const entry = el("article", { className: "app-generation-agent-entry role-agent streaming" }, [head, statusLine, body, tools]);
  container.appendChild(entry);
  container.scrollTop = container.scrollHeight;
  const toolNodes = new Map();
  let textBuffer = "";
  const removeStop = () => {
    const btn = head.querySelector(".app-generation-agent-stop");
    if (btn) btn.remove();
  };
  const showBody = () => {
    if (body.hidden) {
      body.hidden = false;
      statusLine.hidden = true;
    }
  };
  return {
    setStatus(phase) {
      const textEl = statusLine.querySelector(".app-generation-agent-thinking-text");
      if (textEl) textEl.textContent = AGENT_PHASE_LABELS[phase] || AGENT_PHASE_LABELS.thinking;
    },
    appendText(text) {
      const near = agentLogNearBottom(container);
      textBuffer += text || "";
      showBody();
      renderMarkdownInto(body, textBuffer);
      maybeScrollAgentLog(container, near);
    },
    addToolCall(toolCallId, name, input) {
      const near = agentLogNearBottom(container);
      const summary = el("summary", { className: "app-generation-agent-tool-summary" }, [
        el("span", { className: "app-generation-agent-tool-spinner" }, []),
        el("span", null, [name || "tool"]),
      ]);
      const inputPre = el("pre", { className: "app-generation-agent-tool-input" }, [
        typeof input === "string" ? input : JSON.stringify(input || {}, null, 2),
      ]);
      const resultPre = el("pre", { className: "app-generation-agent-tool-result pending" }, ["运行中…"]);
      const details = el("details", { className: "app-generation-agent-tool-details" }, [summary, inputPre, resultPre]);
      const li = el("li", { className: "app-generation-agent-tool" }, [details]);
      tools.appendChild(li);
      toolNodes.set(toolCallId, { resultPre, summary });
      maybeScrollAgentLog(container, near);
    },
    updateToolResult(toolCallId, output, isError) {
      const node = toolNodes.get(toolCallId);
      if (!node) return;
      const near = agentLogNearBottom(container);
      node.resultPre.classList.remove("pending");
      node.resultPre.classList.add(isError ? "error" : "success");
      const spinner = node.summary.querySelector(".app-generation-agent-tool-spinner");
      if (spinner) spinner.classList.add(isError ? "failed" : "done");
      node.resultPre.textContent = typeof output === "string" ? output : JSON.stringify(output, null, 2);
      maybeScrollAgentLog(container, near);
    },
    finalize(payload) {
      const near = agentLogNearBottom(container);
      entry.classList.remove("streaming");
      removeStop();
      statusLine.hidden = true;
      if (payload && typeof payload.cleaned_message === "string" && payload.cleaned_message.length) {
        textBuffer = payload.cleaned_message;
      }
      if (!textBuffer && payload && payload.message) {
        textBuffer = payload.message;
      }
      showBody();
      renderMarkdownInto(body, textBuffer || "(无消息)");
      if (payload && payload.actions && payload.actions.length) {
        entry.appendChild(renderAgentActions(payload.actions));
      }
      if (payload && payload.usage) {
        entry.appendChild(
          el("p", { className: "app-generation-agent-usage" }, [
            `usage · prompt=${payload.usage.prompt_tokens ?? "?"} · completion=${payload.usage.completion_tokens ?? "?"} · total=${payload.usage.total_tokens ?? "?"}`,
          ])
        );
      }
      state.agentLog.push({
        role: `助手 · ${providerLabel}`,
        text: textBuffer || (payload && payload.message) || "(无消息)",
        payload,
        at: new Date().toISOString(),
      });
      maybeScrollAgentLog(container, near);
    },
    fail(reason) {
      const near = agentLogNearBottom(container);
      entry.classList.remove("streaming");
      entry.classList.add("error");
      removeStop();
      statusLine.hidden = true;
      showBody();
      entry.appendChild(el("p", { className: "app-generation-agent-error" }, [reason]));
      maybeScrollAgentLog(container, near);
    },
  };
}

async function streamAgentMessage(body, bubble, signal) {
  const response = await fetch("/api/app-generation/agent/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok || !response.body) {
    const text = await response.text().catch(() => "");
    throw new Error(`HTTP ${response.status} ${text || ""}`.trim());
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const dataLines = frame
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart());
      if (!dataLines.length) continue;
      let event;
      try {
        event = JSON.parse(dataLines.join("\n"));
      } catch (_err) {
        continue;
      }
      dispatchStreamEvent(event, bubble);
    }
  }
}

function dispatchStreamEvent(event, bubble) {
  if (!event || !bubble) return;
  const type = event.type;
  const payload = event.payload || {};
  if (type === "agent_status") {
    if (bubble.setStatus) bubble.setStatus(payload.phase);
  } else if (type === "message_delta") {
    bubble.appendText(payload.text || "");
  } else if (type === "tool_call") {
    bubble.addToolCall(payload.tool_call_id || payload.id || cryptoRandomId(), payload.name, payload.input);
  } else if (type === "tool_result") {
    bubble.updateToolResult(payload.tool_call_id || payload.id, payload.output, !!payload.is_error);
  } else if (type === "agent_end") {
    bubble.finalize(payload);
  } else if (type === "upstream_error") {
    bubble.fail(`${payload.phase || "error"} · ${payload.errorMessage || ""}`);
  }
}

function cryptoRandomId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return `id-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function sendAgentMessage(event) {
  event.preventDefault();
  const input = document.getElementById("app-generation-agent-input");
  if (state.isNewTask) {
    appendAgentLog("system", "请先在「PRD 输入」上传 PRD 并点击「启动生成」，生成任务创建后 Agent 会绑定到对应步骤。");
    if (input) input.focus();
    return;
  }
  if (!input || !state.nodeContext) {
    appendAgentLog("system", "请先选择左侧任务并点击节点。");
    return;
  }
  const message = input.value.trim();
  appendAgentLog("user", message || `[${state.agentMode}]`);
  input.value = "";
  const controller = new AbortController();
  state.agentStreamController = controller;
  const bubble = startStreamingAgentBubble(state.provider, { onStop: () => controller.abort() });
  const body = {
    provider: state.provider,
    mode: state.agentMode,
    intent: state.agentMode === "explain" ? "auto" : state.agentMode,
    message,
    node_context: state.nodeContext,
    interaction_context: buildAgentInteractionContext(),
  };
  try {
    await streamAgentMessage(body, bubble, controller.signal);
  } catch (err) {
    if (err && err.name === "AbortError") {
      if (bubble) bubble.fail("已停止本次 Agent 回复。");
    } else if (bubble) {
      bubble.fail(`Agent 调用失败：${err.message}`);
    } else {
      appendAgentLog("system", `Agent 调用失败：${err.message}`);
    }
  } finally {
    if (state.agentStreamController === controller) state.agentStreamController = null;
  }
}

async function triggerRerun(overrideInstructions, nodeId) {
  if (!state.nodeContext) {
    appendAgentLog("system", "请先选择左侧任务并点击节点。");
    return;
  }
  const status = document.getElementById("app-generation-rerun-status");
  if (status) status.textContent = "正在创建新 run …";
  try {
    const message = (document.getElementById("app-generation-agent-input") || {}).value || "";
    const rerunNodeId = nodeId || state.selectedNodeId;
    const override = overrideInstructions || message || `从 ${rerunNodeId} 重跑（无额外说明）`;
    const response = await fetchJSON("/api/app-generation/rerun", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_run_id: state.selectedRunId,
        rerun_from_node: rerunNodeId,
        selected_variant: state.selectedVariant,
        context_revision: state.nodeContext.context_revision,
        override_instructions: override,
      }),
    });
    if (status) {
      status.textContent = `新 run 已创建：${response.run_id}（源 ${response.source_run_id || "-"}）`;
    }
    appendAgentLog("system", `已从节点 ${rerunNodeId} 创建新 run：${response.run_id}`);
    await loadRuns();
  } catch (err) {
    if (status) status.textContent = `重跑失败：${err.message}`;
    appendAgentLog("system", `重跑失败：${err.message}`);
  }
}

async function uploadPrd(event) {
  event.preventDefault();
  const textarea = document.getElementById("app-generation-upload-prd");
  const executorSelect = document.getElementById("app-generation-upload-executor");
  const providerSelect = document.getElementById("app-generation-upload-provider");
  const modelSelect = document.getElementById("app-generation-upload-model");
  const status = document.getElementById("app-generation-upload-status");
  const prdText = (textarea && textarea.value) || "";
  if (!prdText.trim()) {
    if (status) status.textContent = "请粘贴 PRD 内容或选择 .md 文件后再启动。";
    return;
  }
  const executor = (executorSelect && executorSelect.value) || "codex";
  const codexProvider = (providerSelect && providerSelect.value) || state.uploadProvider || "default";
  const model = (modelSelect && modelSelect.value) || state.uploadModel || COMMON_CODEX_MODELS[0];
  state.uploadProvider = codexProvider;
  state.uploadModel = model;
  persistState();
  if (status) status.textContent = "正在创建 run …";
  try {
    const response = await fetchJSON("/api/app-generation/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prd_text: prdText,
        prd_filename: state.uploadFilename || "",
        executor,
        codex_provider: codexProvider,
        model,
      }),
    });
    if (status) {
      status.textContent = `已创建 run：${response.run_id}（${response.executor || executor} · ${codexProvider} · ${model}）`;
    }
    if (textarea) textarea.value = "";
    state.uploadFilename = "";
    const fileInput = document.getElementById("app-generation-upload-file");
    if (fileInput) fileInput.value = "";
    const fileLabel = document.querySelector('label[for="app-generation-upload-file"]');
    if (fileLabel) fileLabel.textContent = "或选择 PRD 文件 (.md)";
    await loadRuns();
    if (response.run_id) {
      await selectRun(response.run_id);
      subscribeRunEvents(response.run_id);
    }
  } catch (err) {
    if (status) status.textContent = `创建失败：${err.message}`;
  }
}

let _runEventSource = null;

function subscribeRunEvents(runId) {
  if (_runEventSource) {
    try {
      _runEventSource.close();
    } catch (_err) {}
    _runEventSource = null;
  }
  if (!runId || typeof EventSource === "undefined") return;
  const url = `/api/app-generation/runs/${encodeURIComponent(runId)}/events/stream`;
  const source = new EventSource(url);
  _runEventSource = source;
  source.onmessage = (msg) => {
    let event;
    try {
      event = JSON.parse(msg.data);
    } catch (_err) {
      return;
    }
    handleRunStreamEvent(runId, event);
  };
  source.onerror = () => {
    try {
      source.close();
    } catch (_err) {}
    if (_runEventSource === source) _runEventSource = null;
  };
}

function handleRunStreamEvent(runId, event) {
  if (!event || state.selectedRunId !== runId) return;
  const type = event.type;
  const payload = event.payload || {};
  if (type === "snapshot") {
    if (Array.isArray(payload.nodes)) {
      state.nodes = payload.nodes;
      renderNodes();
    }
    const meta = document.getElementById("app-generation-pipeline-meta");
    if (meta && payload.run) {
      meta.textContent = `${payload.run.app_slug || runId} · ${payload.run.executor || "-"} · ${payload.run.status || "unknown"}`;
    }
  } else if (type === "node_state") {
    const target = state.nodes.find((n) => n.id === payload.node_id);
    if (target) {
      target.status = payload.status;
      if (payload.outputs) target.outputs = payload.outputs;
      if (payload.output_summary) target.output_summary = payload.output_summary;
      if (payload.risks) target.risks = payload.risks;
      if (payload.phases) target.phases = payload.phases;
      renderNodes();
      if (target.id === state.selectedNodeId) renderNodeDetail();
    }
    refreshCanvasProjection(runId).then(() => renderCanvasPanel());
  } else if (type === "node_progress") {
    const ev = payload.event || {};
    const live = state.canvas.coderLive && state.canvas.coderLive.run_id === runId
      ? state.canvas.coderLive
      : { run_id: runId, files_changed: 0, tool_calls: 0, event_seq: 0, last_event_id: "" };
    const evId = String(ev.event_id || "");
    if (evId && evId !== live.last_event_id) {
      live.last_event_id = evId;
      live.event_seq += 1;
      const evType = String(ev.event_type || "");
      if (evType === "tool_call") live.tool_calls += 1;
      if (evType === "file_change" || evType === "patch") live.files_changed += 1;
    }
    live.title = ev.title || live.title || "";
    live.summary = ev.summary || live.summary || "";
    live.business_status = ev.business_status || live.business_status || "";
    live.alive = true;
    live.ts = Date.now();
    state.canvas.coderLive = live;
    renderCanvasPanel();
  } else if (type === "heartbeat") {
    const live = state.canvas.coderLive && state.canvas.coderLive.run_id === runId
      ? state.canvas.coderLive
      : { run_id: runId, files_changed: 0, tool_calls: 0, event_seq: 0, last_event_id: "" };
    live.running_node = payload.running_node || "";
    live.heartbeat_ts = Date.now();
    live.alive = true;
    state.canvas.coderLive = live;
    renderCoderLiveBadge();
  } else if (type === "run_finished") {
    const meta = document.getElementById("app-generation-pipeline-meta");
    if (meta) {
      const baseText = meta.textContent || "";
      meta.textContent = baseText.includes(payload.status)
        ? baseText
        : `${baseText} · ${payload.status}`;
    }
    if (_runEventSource) {
      try {
        _runEventSource.close();
      } catch (_err) {}
      _runEventSource = null;
    }
    state.canvas.coderLive = null;
    refreshCanvasProjection(runId).then(() => renderCanvasPanel());
    loadRuns();
  }
}

function populateUploadControls() {
  const providerSelect = document.getElementById("app-generation-upload-provider");
  if (providerSelect) {
    providerSelect.value = state.uploadProvider || "default";
    providerSelect.addEventListener("change", () => {
      state.uploadProvider = providerSelect.value;
      persistState();
    });
  }
  const modelSelect = document.getElementById("app-generation-upload-model");
  if (modelSelect) {
    clear(modelSelect);
    for (const name of COMMON_CODEX_MODELS) {
      const opt = el("option", { value: name }, [name]);
      modelSelect.appendChild(opt);
    }
    const initial = state.uploadModel || COMMON_CODEX_MODELS[0];
    if (!COMMON_CODEX_MODELS.includes(initial)) {
      modelSelect.appendChild(el("option", { value: initial }, [initial]));
    }
    modelSelect.value = initial;
    modelSelect.addEventListener("change", () => {
      state.uploadModel = modelSelect.value;
      persistState();
    });
  }
  const fileInput = document.getElementById("app-generation-upload-file");
  const textarea = document.getElementById("app-generation-upload-prd");
  const status = document.getElementById("app-generation-upload-status");
  const fileLabel = document.querySelector('label[for="app-generation-upload-file"]');
  const defaultFileLabel = fileLabel ? fileLabel.textContent : "";
  if (fileInput && textarea) {
    fileInput.addEventListener("change", () => {
      const file = fileInput.files && fileInput.files[0];
      if (!file) {
        state.uploadFilename = "";
        if (fileLabel) fileLabel.textContent = defaultFileLabel;
        return;
      }
      const sizeLimit = 1024 * 1024;
      if (file.size > sizeLimit) {
        if (status) status.textContent = `文件过大（${(file.size / 1024).toFixed(1)} KB），上限 1 MB。`;
        fileInput.value = "";
        return;
      }
      const reader = new FileReader();
      reader.onload = () => {
        const text = typeof reader.result === "string" ? reader.result : "";
        textarea.value = text;
        state.uploadFilename = file.name || "";
        if (fileLabel) fileLabel.textContent = `已载入：${file.name}`;
        if (status) status.textContent = `已载入 ${file.name}（${(file.size / 1024).toFixed(1)} KB），点击启动生成即可创建 run。`;
      };
      reader.onerror = () => {
        if (status) status.textContent = `读取文件失败：${(reader.error && reader.error.message) || "未知错误"}`;
      };
      reader.readAsText(file, "utf-8");
    });
  }
}

function bindUI() {
  const newTaskBtn = document.getElementById("app-generation-new-task");
  if (newTaskBtn) newTaskBtn.addEventListener("click", enterNewTaskMode);
  const refreshBtn = document.getElementById("app-generation-refresh");
  if (refreshBtn) refreshBtn.addEventListener("click", loadRuns);
  const uploadForm = document.getElementById("app-generation-upload-form");
  if (uploadForm) uploadForm.addEventListener("submit", uploadPrd);
  populateUploadControls();
  const providerSelect = document.getElementById("app-generation-provider");
  if (providerSelect) {
    providerSelect.addEventListener("change", () => {
      state.provider = providerSelect.value;
      persistState();
      renderProviders();
    });
  }
  const modeSelect = document.getElementById("app-generation-agent-mode");
  if (modeSelect) {
    modeSelect.value = state.agentMode;
    modeSelect.addEventListener("change", () => {
      state.agentMode = modeSelect.value;
      persistState();
    });
  }
  const form = document.getElementById("app-generation-agent-form");
  if (form) form.addEventListener("submit", sendAgentMessage);
  const showAllEngineering = document.getElementById("app-generation-show-all-engineering-nodes");
  if (showAllEngineering) showAllEngineering.addEventListener("change", renderNodes);
  const canvasTypeFilter = document.getElementById("app-generation-canvas-type-filter");
  if (canvasTypeFilter) {
    canvasTypeFilter.addEventListener("change", async () => {
      state.canvas.filters.objectType = canvasTypeFilter.value || "all";
      await applyCanvasFilters();
    });
  }
  const canvasStatusFilter = document.getElementById("app-generation-canvas-status-filter");
  if (canvasStatusFilter) {
    canvasStatusFilter.addEventListener("change", async () => {
      state.canvas.filters.status = canvasStatusFilter.value || "all";
      await applyCanvasFilters();
    });
  }
  const detail = document.getElementById("app-generation-node-detail");
  if (detail) {
    detail.addEventListener("click", (event) => {
      const card = event.target && event.target.closest ? event.target.closest("[data-focus-card]") : null;
      if (card && card.dataset && card.dataset.focusCard) {
        setAgentFocus(card.dataset.focusCard, {
          selected_text: getSelectedText(),
          view_mode: "node_detail",
        });
      }
    });
  }
  const rerunBtn = document.getElementById("app-generation-rerun");
  if (rerunBtn) rerunBtn.addEventListener("click", triggerRerun);
  const previewClose = document.getElementById("app-generation-preview-close");
  if (previewClose) {
    previewClose.addEventListener("click", () => {
      if (state.appPreview) {
        closeAppPreviewRail();
      } else {
        closeArtifactPreview();
      }
    });
  }
  const publishBtn = document.getElementById("app-generation-publish-btn");
  if (publishBtn) {
    publishBtn.addEventListener("click", () => {
      if (state.selectedRunId) publishAppFromUI(state.selectedRunId);
    });
  }
  const previewBtn = document.getElementById("app-generation-preview-btn");
  if (previewBtn) {
    previewBtn.addEventListener("click", () => {
      if (state.selectedRunId) startAppPreviewFromUI(state.selectedRunId);
    });
  }
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (state.appPreview) {
        closeAppPreviewRail();
      } else {
        closeArtifactPreview();
      }
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  loadPersistedState();
  bindUI();
  renderPreviewControls();
  loadRuns();
});
