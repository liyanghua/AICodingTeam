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
  unknown: "未记录",
  success: "已就绪",
  error: "失败",
  pending: "未开始",
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
    unknown: "status-muted",
    success: "status-completed",
    error: "status-attention",
    pending: "status-muted",
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
    allowed_operations: (state.interactionContext && state.interactionContext.allowed_operations) || [],
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
    patch_artifact: "修改产物",
    patch_app: "修改已发布应用",
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
    action.reason ||
    action.question ||
    action.target_artifact ||
    action.override_instructions ||
    ""
  );
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
    publishBtn.title = publishBtn.disabled ? "任务完成后才能发布应用快照。" : "把生成应用发布为可预览快照。";
  }
  if (previewBtn) {
    previewBtn.disabled = !state.selectedRunId || !isPublished;
    previewBtn.title = isPublished ? "启动已发布快照的本地预览。" : "请先发布应用快照。";
  }
  if (status && !state.appPreview) {
    if (!state.selectedRunId) status.textContent = "请选择一个任务。";
    else if (isPublished) status.textContent = publishStatus.published_at ? `已发布：${publishStatus.app_slug || "-"} · ${publishStatus.published_at}` : "已发布，可以启动预览。";
    else status.textContent = publishStatus.message || "未发布，请先点击「发布应用快照」。";
  }
}

async function loadRuns() {
  try {
    const data = await fetchJSON("/api/app-generation/runs");
    state.runs = (data && data.runs) || [];
    renderRuns();
    if (!state.selectedRunId && state.runs.length) {
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
    container.appendChild(el("p", { className: "meta" }, ["暂无 app_generation 任务。先在主工作台创建一个。"]));
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
  state.selectedRunId = runId;
  persistState();
  renderRuns();
  try {
    const data = await fetchJSON(`/api/app-generation/runs/${encodeURIComponent(runId)}`);
    state.selectedRun = (data && data.run) || null;
    state.nodes = (data && data.nodes) || [];
    state.providerStatuses = (data && data.provider_statuses) || [];
    const meta = document.getElementById("app-generation-pipeline-meta");
    if (meta) {
      const run = (data && data.run) || {};
      meta.textContent = `${run.app_slug || runId} · ${run.executor || "-"} · ${run.status || "unknown"}` +
        (run.source_run_id ? ` · 源 ${run.source_run_id}` : "");
    }
    renderProviders();
    renderPreviewControls();
    renderNodes();
    if (!state.selectedNodeId || !state.nodes.find((n) => n.id === state.selectedNodeId)) {
      state.selectedNodeId = state.nodes[0] ? state.nodes[0].id : "";
    }
    if (state.selectedNodeId) {
      await selectNode(state.selectedNodeId);
    }
    const runStatus = (data && data.run && data.run.status) || "";
    if (runStatus && !["completed", "failed", "blocked"].includes(runStatus)) {
      subscribeRunEvents(runId);
    }
  } catch (err) {
    state.selectedRun = null;
    state.nodes = [];
    renderPreviewControls();
    renderNodes();
    appendAgentLog("system", `加载节点失败：${err.message}`);
  }
}

function renderNodes() {
  const container = document.getElementById("app-generation-node-list");
  if (!container) return;
  clear(container);
  if (!state.nodes.length) {
    container.appendChild(el("p", { className: "meta" }, ["所选任务暂无节点数据。"]));
    return;
  }
  for (const node of state.nodes) {
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
  if (nodeEl) nodeEl.textContent = nodeTitle(node) || "-";
  if (variantEl) variantEl.textContent = variantLabel(state.selectedVariant) || "-";
  const ctx = state.nodeContext;
  if (revisionEl) {
    const rev = ctx ? ctx.context_revision : "";
    revisionEl.textContent = rev ? rev.slice(0, 24) + "…" : "-";
  }
  const focusEl = document.getElementById("app-generation-agent-focus");
  if (focusEl) {
    const focus = (state.interactionContext && state.interactionContext.focus) || {};
    const card = focus.card || "node_summary";
    focusEl.textContent = focus.artifact_ref ? `${card} · ${focus.artifact_ref}` : card;
  }
  if (statusEl) {
    if (ctx) {
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
      el("p", { className: "meta" }, [agentActionSummary(action)]),
    ]);
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

async function handlePatchAppAction(action) {
  if (!state.selectedRunId) {
    appendAgentLog("system", "patch_app 需要先选择 run。");
    return;
  }
  const targetPath = action.target_path || "";
  const editKind = action.edit_kind || "";
  const newContent = action.new_content || "";
  const summary = action.summary || action.patch_summary || "";
  if (!targetPath || !editKind) {
    appendAgentLog("system", `patch_app 缺少 target_path 或 edit_kind（target_path=${targetPath || "-"}，edit_kind=${editKind || "-"}）。`);
    return;
  }

  appendAgentLog("system", `正在预览 patch_app 改动（${targetPath} · ${editKind}）…`);
  let dryRunResult;
  try {
    dryRunResult = await patchAppFile(state.selectedRunId, {
      target_path: targetPath,
      edit_kind: editKind,
      new_content: newContent,
      summary,
      anchor: action.anchor || "",
      action_id: action.action_id || "",
      dry_run: true,
    });
  } catch (err) {
    appendAgentLog("system", `patch_app dry_run 失败：${err.message}`);
    return;
  }

  const userConfirmed = await showDiffModal({
    targetPath,
    editKind,
    summary,
    diff: dryRunResult.diff || "",
  });

  if (!userConfirmed) {
    appendAgentLog("system", "用户取消了 patch_app。");
    return;
  }

  appendAgentLog("system", `正在应用 patch_app（${targetPath} · ${editKind}）…`);
  try {
    const result = await patchAppFile(state.selectedRunId, {
      target_path: targetPath,
      edit_kind: editKind,
      new_content: newContent,
      summary,
      anchor: action.anchor || "",
      action_id: action.action_id || "",
    });
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

function startStreamingAgentBubble(providerLabel) {
  const container = document.getElementById("app-generation-agent-log");
  if (!container) return null;
  const eyebrow = el("p", { className: "eyebrow" }, [`agent · ${providerLabel} · ${new Date().toLocaleTimeString()}`]);
  const body = el("p", { className: "app-generation-agent-stream-body" }, [""]);
  const tools = el("ul", { className: "app-generation-agent-tools" });
  const entry = el("article", { className: "app-generation-agent-entry role-agent streaming" }, [eyebrow, body, tools]);
  container.appendChild(entry);
  container.scrollTop = container.scrollHeight;
  const toolNodes = new Map();
  let textBuffer = "";
  return {
    appendText(text) {
      textBuffer += text || "";
      body.textContent = textBuffer;
      container.scrollTop = container.scrollHeight;
    },
    addToolCall(toolCallId, name, input) {
      const summary = el(
        "summary",
        { className: "app-generation-agent-tool-summary" },
        [`🔧 ${name || "tool"}`],
      );
      const inputPre = el("pre", { className: "app-generation-agent-tool-input" }, [
        typeof input === "string" ? input : JSON.stringify(input || {}, null, 2),
      ]);
      const resultPre = el("pre", { className: "app-generation-agent-tool-result pending" }, ["运行中…"]);
      const details = el(
        "details",
        { className: "app-generation-agent-tool-details" },
        [summary, inputPre, resultPre],
      );
      const li = el("li", { className: "app-generation-agent-tool" }, [details]);
      tools.appendChild(li);
      toolNodes.set(toolCallId, { resultPre });
      container.scrollTop = container.scrollHeight;
    },
    updateToolResult(toolCallId, output, isError) {
      const node = toolNodes.get(toolCallId);
      if (!node) return;
      node.resultPre.classList.remove("pending");
      if (isError) node.resultPre.classList.add("error");
      node.resultPre.textContent = typeof output === "string" ? output : JSON.stringify(output, null, 2);
      container.scrollTop = container.scrollHeight;
    },
    finalize(payload) {
      entry.classList.remove("streaming");
      if (payload && payload.actions && payload.actions.length) {
        entry.appendChild(renderAgentActions(payload.actions));
      }
      if (payload && typeof payload.cleaned_message === "string" && payload.cleaned_message.length) {
        textBuffer = payload.cleaned_message;
        body.textContent = textBuffer;
      }
      if (payload && payload.usage) {
        const usage = el("p", { className: "app-generation-agent-usage" }, [
          `usage · prompt=${payload.usage.prompt_tokens ?? "?"} · completion=${payload.usage.completion_tokens ?? "?"} · total=${payload.usage.total_tokens ?? "?"}`,
        ]);
        entry.appendChild(usage);
      }
      if (!textBuffer && payload && payload.message) {
        body.textContent = payload.message;
      }
      state.agentLog.push({
        role: `agent · ${providerLabel}`,
        text: textBuffer || (payload && payload.message) || "(无消息)",
        payload,
        at: new Date().toISOString(),
      });
      container.scrollTop = container.scrollHeight;
    },
    fail(reason) {
      entry.classList.remove("streaming");
      entry.classList.add("error");
      const errLine = el("p", { className: "app-generation-agent-error" }, [reason]);
      entry.appendChild(errLine);
      container.scrollTop = container.scrollHeight;
    },
  };
}

async function streamAgentMessage(body, bubble) {
  const response = await fetch("/api/app-generation/agent/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
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
  if (type === "message_delta") {
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
  if (!input || !state.nodeContext) {
    appendAgentLog("system", "请先选择左侧任务并点击节点。");
    return;
  }
  const message = input.value.trim();
  appendAgentLog("user", message || `[${state.agentMode}]`);
  input.value = "";
  const bubble = startStreamingAgentBubble(state.provider);
  const body = {
    provider: state.provider,
    mode: state.agentMode,
    intent: state.agentMode === "explain" ? "auto" : state.agentMode,
    message,
    node_context: state.nodeContext,
    interaction_context: buildAgentInteractionContext(),
  };
  try {
    await streamAgentMessage(body, bubble);
  } catch (err) {
    if (bubble) bubble.fail(`Agent 调用失败：${err.message}`);
    else appendAgentLog("system", `Agent 调用失败：${err.message}`);
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
