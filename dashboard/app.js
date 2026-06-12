const state = {
  selectedRunId: "",
  selectedArtifactPath: "",
  selectedDiffFilePath: "",
  selectedFlowNodeId: "",
  flowDetailScroll: { key: "", top: 0 },
  timer: null,
  i18n: null,
  currentRun: null,
  currentVm: null,
};

const $ = (id) => document.getElementById(id);
const view = window.BusinessView;
const ACCEPTANCE_ENDPOINT_SUFFIX = "/acceptance";
const RELEASE_READINESS_ENDPOINT_SUFFIX = "/release/readiness";
const GITHUB_PR_DRAFT_ENDPOINT_SUFFIX = "/pr/draft";
const GITHUB_PR_STATUS_ENDPOINT_SUFFIX = "/pr/status";
const STAGING_READINESS_ENDPOINT_SUFFIX = "/staging-readiness";
const STAGING_REHEARSAL_ENDPOINT_SUFFIX = "/staging-rehearsal";
const PRODUCTION_READINESS_ENDPOINT_SUFFIX = "/production-readiness";

function t(path, fallback = "") {
  return view.lookup(state.i18n, path, fallback || view.lookup(state.i18n, "app.unknown", "未知项"));
}

function statusClass(tone) {
  return `status-${tone || "muted"}`;
}

function truncateTaskSummary(value, maxLength = 42) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength).trimEnd()}（...）`;
}

function taskRecordSummary(run) {
  return truncateTaskSummary(run.brief || run.domain_id || run.run_id || t("app.unknown"));
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Request failed: ${response.status}`);
  }
  return data;
}

async function loadI18n() {
  state.i18n = await fetchJson("/i18n/zh-CN.json");
  applyI18n(document);
}

function applyI18n(root) {
  root.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n, node.textContent);
  });
  root.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
    node.setAttribute("placeholder", t(node.dataset.i18nPlaceholder, ""));
  });
}

async function refreshRuns() {
  const data = await fetchJson("/api/runs");
  const runs = data.runs || [];
  renderRunList(runs);
  if (!state.selectedRunId && runs[0]) {
    await selectRun(runs[0].run_id);
  }
}

function renderRunList(runs) {
  const container = $("runs");
  container.textContent = "";
  if (!runs.length) {
    const empty = document.createElement("p");
    empty.className = "meta";
    empty.textContent = t("app.emptyRuns");
    container.appendChild(empty);
    return;
  }
  for (const run of runs) {
    const runStatus = view.toBusinessViewModel(run, state.i18n);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "task-card";
    button.addEventListener("click", () => selectRun(run.run_id));

    const title = document.createElement("strong");
    title.className = "task-card-title";
    title.textContent = taskRecordSummary(run);
    button.title = run.brief || run.run_id || "";
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = run.run_id;
    const status = document.createElement("span");
    status.className = `mini-status ${statusClass(view.lookup(state.i18n, `status.${runStatus.status}.tone`, "muted"))}`;
    status.textContent = runStatus.statusLabel;

    button.append(title, meta, status);
    container.appendChild(button);
  }
}

async function selectRun(runId) {
  state.selectedRunId = runId;
  state.selectedArtifactPath = "";
  state.selectedDiffFilePath = "";
  state.selectedFlowNodeId = "";
  state.flowDetailScroll = { key: "", top: 0 };
  await refreshRun();
}

async function refreshRun() {
  if (!state.selectedRunId) return;
  const run = await fetchJson(`/api/runs/${encodeURIComponent(state.selectedRunId)}`);
  state.currentRun = run;
  state.currentVm = view.toBusinessViewModel(run, state.i18n);
  renderBusinessRun(state.currentVm);
}

function renderBusinessRun(vm) {
  renderAcceptance(vm);
  renderReleaseReadiness(vm);
  renderGithubPrCi(vm);
  renderStagingReadiness(vm);
  renderStagingRehearsal(vm);
  renderProductionReadiness(vm);
  renderFlowTimeline(vm);
  ensureSelectedFlowNode(vm);
  renderSelectedFlowNode(vm);
}

function renderFlowTimeline(vm) {
  const container = $("flow-nodes");
  if (!container) return;
  container.textContent = "";
  for (const node of vm.flowNodes || []) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = node.id === state.selectedFlowNodeId ? "flow-node-button selected" : "flow-node-button";
    button.addEventListener("click", () => selectFlowNode(node.id));

    const dot = document.createElement("span");
    dot.className = `flow-node-dot ${statusClass(node.tone)}`;
    const body = document.createElement("span");
    body.className = "flow-node-body";
    const title = document.createElement("strong");
    title.textContent = node.title || node.id;
    const summary = document.createElement("span");
    summary.textContent = node.summary || "";
    const status = document.createElement("span");
    status.className = `mini-status ${statusClass(node.tone)}`;
    status.textContent = node.statusLabel || "";
    body.append(title, summary);
    button.append(dot, body, status);
    container.appendChild(button);
  }

  const all = document.createElement("button");
  all.type = "button";
  all.className = state.selectedFlowNodeId === "all_artifacts" ? "flow-node-button selected" : "flow-node-button";
  all.addEventListener("click", () => selectFlowNode("all_artifacts"));
  const dot = document.createElement("span");
  dot.className = "flow-node-dot status-muted";
  const body = document.createElement("span");
  body.className = "flow-node-body";
  const title = document.createElement("strong");
  title.textContent = t("flow.allArtifacts");
  const summary = document.createElement("span");
  summary.textContent = t("flow.allArtifactsHint");
  body.append(title, summary);
  all.append(dot, body);
  container.appendChild(all);
}

function ensureSelectedFlowNode(vm) {
  const nodes = vm.flowNodes || [];
  if (state.selectedFlowNodeId === "all_artifacts") return;
  if (nodes.some((node) => node.id === state.selectedFlowNodeId)) return;
  state.selectedFlowNodeId = vm.recommendedFlowNodeId || (nodes[0] || {}).id || "";
  state.flowDetailScroll = { key: "", top: 0 };
}

function selectFlowNode(nodeId) {
  captureFlowDetailScroll();
  state.selectedFlowNodeId = nodeId;
  state.selectedArtifactPath = "";
  state.selectedDiffFilePath = "";
  state.flowDetailScroll = { key: flowDetailKey(), top: 0 };
  renderFlowTimeline(state.currentVm || {});
  renderSelectedFlowNode(state.currentVm || {});
}

function flowDetailKey() {
  return `${state.selectedRunId || ""}:${state.selectedFlowNodeId || ""}`;
}

function captureFlowDetailScroll() {
  const detail = $("flow-node-detail");
  if (!detail || !state.selectedFlowNodeId) return;
  state.flowDetailScroll = { key: flowDetailKey(), top: detail.scrollTop || 0 };
}

function restoreFlowDetailScroll(detail) {
  if (!detail || state.flowDetailScroll.key !== flowDetailKey()) return;
  const top = Math.min(state.flowDetailScroll.top || 0, Math.max(0, detail.scrollHeight - detail.clientHeight));
  detail.scrollTop = top;
}

function renderSelectedFlowNode(vm) {
  const detail = $("flow-node-detail");
  if (!detail) return;
  captureFlowDetailScroll();
  const node = state.selectedFlowNodeId === "all_artifacts"
    ? renderAllArtifactsNode(vm)
    : (vm.flowNodes || []).find((item) => item.id === state.selectedFlowNodeId);
  if (!node) return;

  $("flow-node-kicker").textContent = t("flow.detailTitle");
  $("flow-node-title").textContent = node.title || "";
  $("flow-node-summary").textContent = node.summary || "";
  const status = $("flow-node-status");
  status.className = `mini-status ${statusClass(node.tone)}`;
  status.textContent = node.statusLabel || "";

  renderFlowRows($("flow-node-insights"), node.insights || [], t("flow.emptyInsights"));
  renderFlowGates($("flow-node-gates"), node.gates || []);
  renderFlowNodeActions(node);
  renderFlowNodeSpecifics(node, vm);
  renderFlowNodeArtifacts(node);
  renderFlowNodeEngineering(node);

  detail.addEventListener("scroll", () => {
    state.flowDetailScroll = { key: flowDetailKey(), top: detail.scrollTop || 0 };
  }, { once: true });
  restoreFlowDetailScroll(detail);
}

function renderAllArtifactsNode(vm) {
  return {
    id: "all_artifacts",
    title: t("flow.allArtifacts"),
    summary: t("flow.allArtifactsHint"),
    status: "completed",
    statusLabel: t("status.completed.label"),
    tone: "green",
    insights: vm.nextActions || [],
    gates: [],
    actions: [],
    artifacts: vm.deliverables || [],
    engineeringEvidence: (vm.flowNodes || []).find((node) => node.id === "implementation")?.engineeringEvidence || {},
  };
}

function renderFlowRows(container, rows, emptyText) {
  if (!container) return;
  container.textContent = "";
  const items = (rows || []).filter(Boolean).slice(0, 8);
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "quality-row";
    empty.textContent = emptyText;
    container.appendChild(empty);
    return;
  }
  for (const text of items) {
    const row = document.createElement("div");
    row.className = "quality-row";
    row.textContent = typeof text === "string" ? text : JSON.stringify(text);
    container.appendChild(row);
  }
}

function renderFlowGates(container, gates) {
  if (!container) return;
  container.textContent = "";
  if (!gates.length) {
    const empty = document.createElement("div");
    empty.className = "quality-row";
    empty.textContent = t("flow.emptyGates");
    container.appendChild(empty);
    return;
  }
  for (const gate of gates.slice(0, 8)) {
    const row = document.createElement("div");
    row.className = `quality-row release-gate-row release-gate-${gate.status || "unknown"}`;
    row.textContent = `${gate.title || gate.id || t("app.unknown")}: ${gate.statusLabel || gate.status || ""} · ${gate.detail || ""}`;
    container.appendChild(row);
  }
}

function renderFlowNodeActions(node) {
  const container = $("flow-node-actions");
  if (!container) return;
  container.textContent = "";
  const actionIds = (node.actions || []).map((action) => action.id);
  const renderers = {
    acceptance: () => container.appendChild(flowActionButton("acceptance-action", startAcceptance)),
    release_readiness: () => container.appendChild(flowActionButton("release-readiness-action", startReleaseReadiness)),
    github_pr: () => container.appendChild(flowActionButton("github-pr-action", startGithubDraftPr)),
    github_ci: () => container.appendChild(flowActionButton("github-ci-action", refreshGithubCi, "ghost")),
    staging_readiness: () => container.appendChild(flowActionButton("staging-readiness-action", startStagingReadiness)),
    staging_rehearsal: () => container.appendChild(flowActionButton("staging-rehearsal-action", startStagingRehearsal, "ghost")),
    production_readiness: () => container.appendChild(flowActionButton("production-readiness-action", startProductionReadiness)),
  };
  for (const id of actionIds) {
    if (renderers[id]) renderers[id]();
  }
  if (!container.children.length) {
    const empty = document.createElement("div");
    empty.className = "quality-row";
    empty.textContent = t("flow.emptyActions");
    container.appendChild(empty);
  }
}

function flowActionButton(sourceId, handler, extraClass = "") {
  const source = $(sourceId);
  const button = document.createElement("button");
  button.type = "button";
  button.className = extraClass;
  button.disabled = source ? source.disabled : false;
  button.textContent = source ? source.textContent : t("app.unknown");
  button.addEventListener("click", handler);
  return button;
}

function renderFlowNodeArtifacts(node) {
  const container = $("flow-artifact-actions");
  if (!container) return;
  container.textContent = "";
  const artifacts = node.artifacts || [];
  if (!artifacts.length) {
    const empty = document.createElement("div");
    empty.className = "quality-row";
    empty.textContent = t("flow.emptyArtifacts");
    container.appendChild(empty);
    renderSelectedArtifact(null);
    $("flow-artifact-preview").textContent = t("flow.emptyArtifacts");
    return;
  }
  for (const artifact of artifacts) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = artifact.path === state.selectedArtifactPath ? "artifact-button selected" : "artifact-button";
    button.dataset.path = artifact.path;
    button.disabled = !artifact.exists;
    button.textContent = artifact.exists ? artifact.title : `${artifact.title} (${t("actions.artifactPending")})`;
    button.addEventListener("click", () => selectArtifact(artifact));
    container.appendChild(button);
  }
  const selected = artifacts.find((artifact) => artifact.path === state.selectedArtifactPath && artifact.exists) || artifacts.find((artifact) => artifact.exists);
  if (selected) selectArtifact(selected);
}

function renderFlowNodeEngineering(node) {
  const container = $("flow-engineering-evidence");
  if (!container) return;
  container.textContent = "";
  const evidence = node.engineeringEvidence || {};
  const rows = [
    flowEvidenceList(t("flow.runIdentity"), [Object.values(evidence.run || {}).filter(Boolean).join(" / ")], t("flow.emptyEngineering")),
    flowEvidenceList(t("stageDetail.relatedAgents"), evidence.agentIds || [], t("flow.emptyEngineering")),
    flowEvidenceList(t("stageDetail.relatedEvents"), (evidence.events || []).map((item) => typeof item === "string" ? item : JSON.stringify(item)), t("flow.emptyEngineering")),
    flowEvidenceList(t("stageDetail.relatedLogs"), evidence.logs || [], t("stageDetail.globalEngineeringHint")),
  ];
  if (evidence.diffSummary && evidence.diffSummary.available) {
    rows.push(flowEvidenceList(t("app.engineeringDiff"), [renderDiffSummary(evidence.diffSummary)], t("diffView.empty")));
  }
  for (const row of rows) container.appendChild(row);
}

function flowEvidenceList(title, values, emptyText) {
  const block = document.createElement("div");
  block.className = "flow-evidence-card";
  const heading = document.createElement("strong");
  heading.textContent = title;
  block.appendChild(heading);
  const items = (values || []).filter(Boolean).slice(0, 4);
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "summary-text";
    empty.textContent = emptyText;
    block.appendChild(empty);
    return block;
  }
  const list = document.createElement("ul");
  list.className = "flow-evidence-list";
  for (const item of items) {
    const row = document.createElement("li");
    row.textContent = typeof item === "string" ? item : JSON.stringify(item);
    list.appendChild(row);
  }
  block.appendChild(list);
  return block;
}

function renderFlowNodeSpecifics(node, vm) {
  const container = $("flow-node-specifics");
  if (!container) return;
  container.textContent = "";
  if (node.id === "implementation") {
    renderImplementationFlow(vm.implementationFlow || {}, container);
    renderFlowNodeSpecificRows(container, t("complexTask.sliceLoopTitle"), [
      vm.sliceLoop.summary,
      vm.sliceLoop.currentSliceId ? `${t("complexTask.currentSlice")}: ${vm.sliceLoop.currentSliceId}` : "",
      ...(vm.sliceLoop.blockers || []).slice(0, 2).map((item) => `${t("complexTask.blocker")}: ${item}`),
      vm.sliceLoop.nextAction ? `${t("complexTask.nextAction")}: ${vm.sliceLoop.nextAction}` : "",
    ]);
    renderFlowNodeSpecificRows(container, t("complexTask.completionTitle"), [
      `${t("complexTask.statusLabel")}: ${vm.completionGate.statusLabel || t("app.unknown")}`,
      vm.completionGate.summary,
      ...(vm.completionGate.blockers || []).slice(0, 2).map((item) => `${t("complexTask.blocker")}: ${item}`),
      vm.completionGate.nextAction ? `${t("complexTask.nextAction")}: ${vm.completionGate.nextAction}` : "",
    ]);
    return;
  }
  if (node.id === "requirement") {
    renderFlowNodeSpecificRows(container, t("complexTask.requirementTitle"), [
      `${t("complexTask.statusLabel")}: ${vm.requirementUnderstanding.statusLabel || t("app.unknown")}`,
      vm.requirementUnderstanding.summary,
      vm.requirementUnderstanding.complexity ? `${t("complexTask.complexity")}: ${vm.requirementUnderstanding.complexity}` : "",
      vm.requirementUnderstanding.planningMode ? `${t("complexTask.planningMode")}: ${vm.requirementUnderstanding.planningMode}` : "",
      ...(vm.requirementUnderstanding.blockingQuestions || []).slice(0, 3).map((item) => `${t("complexTask.blockingQuestion")}: ${item}`),
    ]);
    renderFlowNodeSpecificRows(container, t("memoryRecall.title"), [
      vm.memoryRecall.summary,
      ...(vm.memoryRecall.recommendedSkills || []).slice(0, 3).map((item) => `${item.id || t("app.unknown")} · ${item.why || ""}`),
    ]);
    return;
  }
  if (node.id === "design") {
    renderFlowNodeSpecificRows(container, t("complexTask.coverageTitle"), [
      vm.acceptanceCoverage.summary,
      `${t("complexTask.ready")}: ${vm.acceptanceCoverage.ready ? t("githubPr.yes") : t("githubPr.no")}`,
      ...(vm.acceptanceCoverage.orphanCriteria || []).slice(0, 3).map((item) => `${t("complexTask.orphanCriteria")}: ${item.id || item.description || ""}`),
    ]);
    return;
  }
  if (node.id === "delivery") {
    renderFlowNodeSpecificRows(container, t("acceptance.title"), [
      (vm.acceptance || {}).conclusion || t("acceptance.notStarted"),
      (vm.acceptance || {}).next_action ? `${t("implementationFlow.nextAction")}: ${(vm.acceptance || {}).next_action}` : "",
    ]);
    return;
  }
  if (node.id === "release") {
    renderFlowNodeSpecificRows(container, t("releaseReadiness.title"), [
      `${t("releaseReadiness.decision")}: ${vm.releaseReadiness.decisionLabel || t("releaseReadiness.decisions.not_generated")}`,
      vm.releaseReadiness.summary,
      ...(vm.releaseReadiness.blockers || []).slice(0, 3).map((item) => `${t("githubPr.blocker")}: ${item}`),
      ...(vm.releaseReadiness.warnings || []).slice(0, 3).map((item) => `${t("githubPr.warning")}: ${item}`),
    ]);
    return;
  }
  if (node.id === "github_pr_ci") {
    renderFlowNodeSpecificRows(container, t("githubPr.title"), [
      `${t("githubPr.prInfo")}: ${vm.githubPr.statusLabel || ""}`,
      vm.githubPr.pr && vm.githubPr.pr.url ? `${t("githubPr.prUrl")}: ${vm.githubPr.pr.url}` : t("githubPr.noPr"),
      `${t("githubPr.ciInfo")}: ${vm.githubPr.ciStatusLabel || ""}`,
      ...(vm.githubPr.blockers || []).slice(0, 3).map((item) => `${t("githubPr.blocker")}: ${item}`),
      vm.githubPr.nextAction ? `${t("githubPr.nextAction")}: ${vm.githubPr.nextAction}` : "",
    ]);
    return;
  }
  if (node.id === "staging") {
    renderFlowNodeSpecificRows(container, t("stagingReadiness.title"), [
      `${t("stagingReadiness.decision")}: ${vm.stagingReadiness.decisionLabel || t("stagingReadiness.decisions.not_generated")}`,
      vm.stagingReadiness.summary,
      vm.stagingReadiness.evidence && vm.stagingReadiness.evidence.ci_summary ? `${t("stagingReadiness.ciSummary")}: ${vm.stagingReadiness.evidence.ci_summary}` : "",
      ...(vm.stagingReadiness.blockers || []).slice(0, 3).map((item) => `${t("stagingReadiness.blocker")}: ${item}`),
    ]);
    renderFlowNodeSpecificRows(container, t("stagingRehearsal.title"), [
      `${t("stagingRehearsal.status")}: ${vm.stagingRehearsal.statusLabel || t("stagingRehearsal.statuses.not_started")}`,
      vm.stagingRehearsal.summary,
      ...(vm.stagingRehearsal.steps || []).slice(0, 3).map((step) => `${step.id || t("app.unknown")}: ${step.status || ""}${step.exit_code == null ? "" : ` · ${t("acceptance.exitCode")}: ${step.exit_code}`}`),
      ...(vm.stagingRehearsal.blockers || []).slice(0, 3).map((item) => `${t("stagingRehearsal.blocker")}: ${item}`),
      ...(vm.stagingRehearsal.nextActions || []).slice(0, 2).map((item) => `${t("stagingRehearsal.nextActions")}: ${item}`),
    ]);
    return;
  }
  if (node.id === "production") {
    const evidence = vm.productionReadiness.evidence || {};
    const localValidation = evidence.local_validation || {};
    const macMiniValidation = evidence.mac_mini_validation || {};
    const macMini = evidence.mac_mini || {};
    const cloud = evidence.cloud_asset_center || {};
    const smoke = evidence.collector_smoke || {};
    const sync = evidence.cloud_sync || {};
    const localCloud = localValidation.cloud_asset_center || cloud;
    const macDoctor = macMiniValidation.doctor || macMini;
    const macSmoke = macMiniValidation.collector_smoke || smoke;
    const macSync = macMiniValidation.cloud_sync || sync;
    renderFlowNodeSpecificRows(container, t("productionReadiness.title"), [
      `${t("productionReadiness.decision")}: ${vm.productionReadiness.decisionLabel || t("productionReadiness.decisions.not_generated")}`,
      vm.productionReadiness.summary,
      ...(vm.productionReadiness.blockers || []).slice(0, 3).map((item) => `${t("productionReadiness.blocker")}: ${item}`),
      ...(vm.productionReadiness.warnings || []).slice(0, 3).map((item) => `${t("productionReadiness.warning")}: ${item}`),
    ]);
    renderFlowNodeSpecificRows(container, t("productionReadiness.localValidation"), [
      localValidation.profile ? `${t("productionReadiness.profile")}: ${localValidation.profile}` : "",
      localValidation.staging_rehearsal_status ? `${t("stagingRehearsal.status")}: ${localValidation.staging_rehearsal_status}` : "",
      localCloud.status ? `${t("productionReadiness.cloudAssetCenter")}: ${localCloud.status}` : "",
    ]);
    renderFlowNodeSpecificRows(container, t("productionReadiness.macMiniValidation"), [
      macMiniValidation.profile ? `${t("productionReadiness.profile")}: ${macMiniValidation.profile}` : "",
      macDoctor.status ? `${t("productionReadiness.macMini")}: ${macDoctor.status}` : "",
      macSmoke.status ? `${t("productionReadiness.collectorSmoke")}: ${macSmoke.status}${macSmoke.result_count == null ? "" : ` · ${t("productionReadiness.resultCount")}: ${macSmoke.result_count}`}` : "",
      macSync.status ? `${t("productionReadiness.cloudSync")}: ${macSync.status}${macSync.synced_assets == null ? "" : ` · ${t("productionReadiness.syncedAssets")}: ${macSync.synced_assets}`}` : "",
      ...(vm.productionReadiness.nextActions || []).slice(0, 3).map((item) => `${t("productionReadiness.nextActions")}: ${item}`),
    ]);
  }
}

function renderFlowNodeSpecificRows(container, title, values) {
  const rows = (values || []).filter(Boolean);
  if (!rows.length) return;
  const card = document.createElement("section");
  card.className = "flow-detail-card flow-specific-card";
  const heading = document.createElement("h3");
  heading.textContent = title;
  const list = document.createElement("div");
  list.className = "quality-list";
  card.append(heading, list);
  renderFlowRows(list, rows, "");
  container.appendChild(card);
}

function renderHealth(health) {
  if (!$("health-summary")) return;
  $("health-summary").textContent = health.summary || t("health.unknownSummary");
  const list = $("health-details");
  list.textContent = "";
  const rows = [];
  rows.push(`${t("health.statusLabel")}: ${health.label || t("app.unknown")}`);
  for (const group of (health.warningGroups || []).slice(0, 3)) rows.push(`${t("health.warningLabel")}: ${group.title || group.id} (${group.count || 0})`);
  for (const blocker of health.blockers || []) rows.push(`${t("health.blockerLabel")}: ${blocker}`);
  if (rows.length === 1) rows.push(t("health.noIssue"));
  for (const rowText of rows) {
    const row = document.createElement("div");
    row.className = "quality-row";
    row.textContent = rowText;
    list.appendChild(row);
  }
}

function renderArtifactQuality(quality) {
  if (!$("artifact-quality-summary")) return;
  const summary = $("artifact-quality-summary");
  const score = quality.score == null ? "" : ` ${Math.round(Number(quality.score) * 100)}%`;
  summary.textContent = `${quality.summary || t("quality.unknownSummary")}${score}`;
  const list = $("artifact-quality-checks");
  list.textContent = "";
  const checks = (quality.checks || []).slice(0, 6);
  if (!checks.length) {
    const empty = document.createElement("div");
    empty.className = "quality-row";
    empty.textContent = t("quality.noChecks");
    list.appendChild(empty);
    return;
  }
  for (const check of checks) {
    const row = document.createElement("div");
    row.className = `quality-row quality-${check.status || "unknown"}`;
    row.textContent = `${check.title || check.id}: ${check.detail || ""}`;
    list.appendChild(row);
  }
}

function renderMemoryRecall(memoryRecall) {
  const summary = $("memory-recall-summary");
  const skills = $("memory-recall-skills");
  const matches = $("memory-recall-matches");
  if (!summary || !skills || !matches) return;
  summary.textContent = memoryRecall.summary || t("memoryRecall.empty");
  skills.textContent = "";
  matches.textContent = "";

  const skillItems = (memoryRecall.recommendedSkills || []).slice(0, 4);
  if (!skillItems.length) {
    const empty = document.createElement("div");
    empty.className = "quality-row";
    empty.textContent = t("memoryRecall.noSkills");
    skills.appendChild(empty);
  } else {
    for (const skill of skillItems) {
      const row = document.createElement("div");
      row.className = "quality-row";
      row.textContent = `${skill.id || t("app.unknown")} · ${Math.round(Number(skill.confidence || 0) * 100)}% · ${skill.why || ""}`;
      skills.appendChild(row);
    }
  }

  const matchItems = (memoryRecall.matches || []).slice(0, 4);
  if (!matchItems.length) {
    const empty = document.createElement("div");
    empty.className = "quality-row";
    empty.textContent = t("memoryRecall.noMatches");
    matches.appendChild(empty);
  } else {
    for (const match of matchItems) {
      const row = document.createElement("div");
      row.className = "quality-row";
      row.textContent = `${match.run_id || t("app.unknown")} · ${Math.round(Number(match.score || 0) * 100)}% · ${match.task_type || ""}`;
      matches.appendChild(row);
    }
  }
}

function renderComplexTask(vm) {
  renderRequirementUnderstanding(vm.requirementUnderstanding || {});
  renderAcceptanceCoverage(vm.acceptanceCoverage || {});
  renderSliceLoop(vm.sliceLoop || {});
  renderCompletionGate(vm.completionGate || {});
}

function renderRequirementUnderstanding(requirement) {
  const summary = $("requirement-understanding-summary");
  const details = $("requirement-understanding-details");
  if (!summary || !details) return;
  summary.textContent = requirement.summary || t("complexTask.requirementEmpty");
  const rows = [
    `${t("complexTask.statusLabel")}: ${requirement.statusLabel || t("app.unknown")}`,
  ];
  if (requirement.complexity) rows.push(`${t("complexTask.complexity")}: ${requirement.complexity}`);
  if (requirement.planningMode) rows.push(`${t("complexTask.planningMode")}: ${requirement.planningMode}`);
  rows.push(`${t("complexTask.llmDraft")}: ${requirement.llmDraftRequested ? t("githubPr.yes") : t("githubPr.no")}`);
  for (const question of (requirement.blockingQuestions || []).slice(0, 2)) rows.push(`${t("complexTask.blockingQuestion")}: ${question}`);
  for (const blocker of (requirement.blockers || []).slice(0, 2)) rows.push(`${t("complexTask.blocker")}: ${blocker}`);
  for (const warning of (requirement.warnings || []).slice(0, 2)) rows.push(`${t("complexTask.warning")}: ${warning}`);
  if ((requirement.recommendedSkills || []).length) rows.push(`${t("complexTask.skills")}: ${requirement.recommendedSkills.slice(0, 3).join(", ")}`);
  renderCompactRows(details, rows, t("complexTask.requirementEmpty"));
}

function renderAcceptanceCoverage(coverage) {
  const summary = $("acceptance-coverage-summary");
  const details = $("acceptance-coverage-details");
  if (!summary || !details) return;
  summary.textContent = coverage.summary || t("complexTask.coverageEmpty");
  const rows = [];
  if (coverage.totalCriteria) rows.push(`${t("complexTask.acceptanceCriteria")}: ${coverage.coveredCount || 0}/${coverage.totalCriteria}`);
  if (coverage.sliceCount) rows.push(`${t("complexTask.slices")}: ${coverage.sliceCount}`);
  rows.push(`${t("complexTask.ready")}: ${coverage.ready ? t("githubPr.yes") : t("githubPr.no")}`);
  for (const item of (coverage.orphanCriteria || []).slice(0, 2)) rows.push(`${t("complexTask.orphanCriteria")}: ${item.id || item.description || ""}`);
  for (const item of (coverage.slices || []).slice(0, 3)) rows.push(`${item.id || t("app.unknown")}: ${(item.acceptance_criteria_ids || []).join(", ")}`);
  renderCompactRows(details, rows, t("complexTask.coverageEmpty"));
}

function renderSliceLoop(sliceLoop) {
  const summary = $("slice-loop-summary");
  const details = $("slice-loop-details");
  if (!summary || !details) return;
  summary.textContent = sliceLoop.summary || t("complexTask.sliceLoopEmpty");
  const rows = [
    `${t("complexTask.statusLabel")}: ${sliceLoop.statusLabel || t("app.unknown")}`,
  ];
  if (sliceLoop.executionStrategy) rows.push(`${t("complexTask.executionStrategy")}: ${sliceLoop.executionStrategy}`);
  if (sliceLoop.currentSliceId) rows.push(`${t("complexTask.currentSlice")}: ${sliceLoop.currentSliceId}`);
  if ((sliceLoop.completedSliceIds || []).length) rows.push(`${t("complexTask.completedSlices")}: ${sliceLoop.completedSliceIds.join(", ")}`);
  if ((sliceLoop.pendingSliceIds || []).length) rows.push(`${t("complexTask.pendingSlices")}: ${sliceLoop.pendingSliceIds.join(", ")}`);
  for (const blocker of (sliceLoop.blockers || []).slice(0, 2)) rows.push(`${t("complexTask.blocker")}: ${blocker}`);
  if (sliceLoop.nextAction) rows.push(`${t("complexTask.nextAction")}: ${sliceLoop.nextAction}`);
  renderCompactRows(details, rows, t("complexTask.sliceLoopEmpty"));
}

function renderCompletionGate(completionGate) {
  const summary = $("completion-gate-summary");
  const details = $("completion-gate-details");
  if (!summary || !details) return;
  summary.textContent = completionGate.summary || t("complexTask.completionEmpty");
  const rows = [
    `${t("complexTask.statusLabel")}: ${completionGate.statusLabel || t("app.unknown")}`,
  ];
  for (const check of (completionGate.checks || []).slice(0, 4)) rows.push(`${check.id || t("app.unknown")}: ${check.status || ""}`);
  for (const blocker of (completionGate.blockers || []).slice(0, 2)) rows.push(`${t("complexTask.blocker")}: ${blocker}`);
  if (completionGate.nextAction) rows.push(`${t("complexTask.nextAction")}: ${completionGate.nextAction}`);
  renderCompactRows(details, rows, t("complexTask.completionEmpty"));
}

function renderCompactRows(container, rows, emptyText) {
  container.textContent = "";
  const items = rows.filter(Boolean).slice(0, 8);
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "quality-row";
    empty.textContent = emptyText;
    container.appendChild(empty);
    return;
  }
  for (const rowText of items) {
    const row = document.createElement("div");
    row.className = "quality-row";
    row.textContent = rowText;
    container.appendChild(row);
  }
}

function renderImplementationFlow(flow, container) {
  const panel = document.createElement("div");
  panel.className = "implementation-flow";
  if (!flow || !Object.keys(flow).length) {
    const empty = document.createElement("p");
    empty.className = "summary-text";
    empty.textContent = t("implementationFlow.empty");
    panel.appendChild(empty);
    container.appendChild(panel);
    return;
  }

  const current = document.createElement("div");
  current.className = "implementation-current";
  const currentTitle = document.createElement("strong");
  currentTitle.textContent = t("implementationFlow.currentStep");
  const currentText = document.createElement("span");
  const step = (flow.steps || []).find((item) => item.id === flow.current_step) || {};
  currentText.textContent = step.title || flow.current_step || t("implementationFlow.none");
  current.append(currentTitle, currentText);

  const inputs = implementationFlowList(
    t("implementationFlow.inputs"),
    (flow.inputs || []).filter((item) => item.exists).map((item) => `${item.title || item.path}: ${item.path}`),
    t("implementationFlow.none"),
  );

  const timeline = document.createElement("div");
  timeline.className = "flow-specific-block";
  const timelineTitle = document.createElement("strong");
  timelineTitle.textContent = t("implementationFlow.timeline");
  const timelineList = document.createElement("ol");
  timelineList.className = "implementation-timeline";
  for (const item of flow.steps || []) {
    const row = document.createElement("li");
    row.className = `implementation-step implementation-${item.status || "pending"}`;
    const rowTitle = document.createElement("span");
    rowTitle.textContent = item.title || item.id;
    const rowStatus = document.createElement("em");
    rowStatus.textContent = t(`implementationFlow.${item.status || "pending"}`);
    const rowSummary = document.createElement("p");
    rowSummary.textContent = item.summary || "";
    row.append(rowTitle, rowStatus, rowSummary);
    timelineList.appendChild(row);
  }
  timeline.append(timelineTitle, timelineList);

  const evidence = flow.evidence || {};
  const changedFiles = implementationFlowList(t("implementationFlow.changedFiles"), evidence.changed_files || [], t("implementationFlow.none"));
  const testEvidence = (evidence.tests_run || []).length ? evidence.tests_run : evidence.verification_commands || [];
  const testsRun = implementationFlowList(t("implementationFlow.testsRun"), testEvidence, t("implementationFlow.none"));
  const blockers = implementationFlowList(t("implementationFlow.blockers"), flow.blockers || [], t("implementationFlow.none"));
  const risks = implementationFlowList(t("implementationFlow.risks"), flow.risk_events || [], t("implementationFlow.none"));
  const nextAction = implementationFlowList(t("implementationFlow.nextAction"), flow.next_action ? [flow.next_action] : [], t("implementationFlow.none"));

  panel.append(current, inputs, timeline, changedFiles, testsRun, blockers, risks, nextAction);
  container.appendChild(panel);
}

function implementationFlowList(title, values, emptyText) {
  const block = document.createElement("div");
  block.className = "flow-specific-block";
  const heading = document.createElement("strong");
  heading.textContent = title;
  block.appendChild(heading);
  const items = (values || []).filter(Boolean).slice(0, 4);
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "summary-text";
    empty.textContent = emptyText;
    block.appendChild(empty);
    return block;
  }
  const list = document.createElement("ul");
  list.className = "flow-specific-list";
  for (const item of items) {
    const row = document.createElement("li");
    row.textContent = typeof item === "string" ? item : JSON.stringify(item);
    list.appendChild(row);
  }
  block.appendChild(list);
  return block;
}

function renderGates(gates) {
  const container = $("quality-gates");
  if (!container) return;
  container.textContent = "";
  for (const gate of gates) {
    const card = document.createElement("article");
    card.className = "gate-card";
    const status = document.createElement("span");
    status.className = `mini-status ${statusClass(gate.tone)}`;
    status.textContent = gate.statusLabel;
    const title = document.createElement("h3");
    title.textContent = gate.title;
    const detail = document.createElement("p");
    detail.className = "meta";
    detail.textContent = gate.detail;
    card.append(status, title, detail);
    container.appendChild(card);
  }
}

function renderAcceptance(vm) {
  const acceptance = vm.acceptance || {};
  const applyGate = vm.applyGate || {};
  const action = $("acceptance-action");
  const summary = $("acceptance-summary");
  const nextAction = $("acceptance-next-action");
  const steps = $("acceptance-steps");
  const status = acceptance.status || "not_started";
  const canStart = applyGate.status === "passed" && status === "not_started";
  const isRunning = status === "queued" || status === "running";

  action.disabled = !canStart || isRunning;
  action.textContent = isRunning ? t("acceptance.running") : t("acceptance.confirmButton");
  action.onclick = startAcceptance;

  if (status === "completed") {
    summary.textContent = acceptance.conclusion || t("acceptance.completed");
  } else if (status === "failed") {
    summary.textContent = acceptance.conclusion || t("acceptance.failed");
  } else if (isRunning) {
    summary.textContent = acceptance.summary || t("acceptance.running");
  } else if (applyGate.status !== "passed") {
    summary.textContent = applyGate.reason || t("acceptance.blocked");
  } else {
    summary.textContent = t("acceptance.notStarted");
  }

  steps.textContent = "";
  const rows = (acceptance.steps || []).length ? acceptance.steps : defaultAcceptanceSteps();
  for (const step of rows) {
    const row = document.createElement("article");
    row.className = `acceptance-step acceptance-${step.status || "pending"}`;

    const title = document.createElement("strong");
    title.textContent = step.title || step.id || t("app.unknown");
    const badge = document.createElement("span");
    badge.className = `mini-status ${statusClass(acceptanceTone(step.status))}`;
    badge.textContent = t(`acceptance.${step.status || "pending"}`, step.status || "");
    const command = document.createElement("code");
    command.textContent = step.command || "";
    const exit = document.createElement("p");
    exit.className = "meta";
    exit.textContent = step.exit_code == null ? t("acceptance.waitingExit") : `${t("acceptance.exitCode")}: ${step.exit_code}`;
    const logs = document.createElement("pre");
    logs.className = "acceptance-log";
    logs.textContent = [...(step.stdout_tail || []), ...(step.stderr_tail || [])].slice(-8).join("\n");
    row.append(title, badge, command, exit);
    if (logs.textContent) row.appendChild(logs);
    steps.appendChild(row);
  }

  nextAction.textContent = acceptance.next_action || t("acceptance.defaultNextAction");
}

function defaultAcceptanceSteps() {
  return [
    { id: "apply", title: t("acceptance.applyStep"), status: "pending", command: "" },
    { id: "tests", title: t("acceptance.testsStep"), status: "pending", command: "python3 -m unittest discover -s tests -v" },
  ];
}

function acceptanceTone(status) {
  if (status === "completed") return "green";
  if (status === "failed") return "red";
  if (status === "running") return "blue";
  return "muted";
}

async function startAcceptance() {
  if (!state.selectedRunId) return;
  const action = $("acceptance-action");
  action.disabled = true;
  action.textContent = t("acceptance.running");
  await fetchJson(`/api/runs/${encodeURIComponent(state.selectedRunId)}${ACCEPTANCE_ENDPOINT_SUFFIX}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  await refreshRun();
}

function renderReleaseReadiness(vm) {
  const readiness = vm.releaseReadiness || {};
  const acceptance = vm.acceptance || {};
  const action = $("release-readiness-action");
  const summary = $("release-readiness-summary");
  const gates = $("release-readiness-gates");
  const pr = $("release-readiness-pr");
  if (!action || !summary || !gates || !pr) return;

  const canGenerate = (vm.status === "completed" || acceptance.status === "completed") && acceptance.status === "completed";
  action.disabled = !canGenerate;
  action.textContent = t("releaseReadiness.generateButton");
  action.onclick = startReleaseReadiness;
  summary.textContent = readiness.summary || (canGenerate ? t("releaseReadiness.readyToGenerate") : t("releaseReadiness.empty"));

  gates.textContent = "";
  const gateItems = (readiness.gates || []).slice(0, 6);
  if (!gateItems.length) {
    const empty = document.createElement("div");
    empty.className = "quality-row";
    empty.textContent = t("releaseReadiness.noGates");
    gates.appendChild(empty);
  } else {
    for (const gate of gateItems) {
      const row = document.createElement("div");
      row.className = `quality-row release-gate-row release-gate-${gate.status || "unknown"}`;
      row.textContent = `${gate.id || t("app.unknown")}: ${gate.status || ""} · ${gate.reason || ""}`;
      gates.appendChild(row);
    }
  }

  pr.textContent = "";
  const decision = document.createElement("div");
  decision.className = "quality-row";
  decision.textContent = `${t("releaseReadiness.decision")}: ${readiness.decisionLabel || t("releaseReadiness.decisions.not_generated")}`;
  pr.appendChild(decision);
  if (readiness.prDraft && readiness.prDraft.title) {
    const title = document.createElement("div");
    title.className = "quality-row";
    title.textContent = `${t("releaseReadiness.prTitle")}: ${readiness.prDraft.title}`;
    pr.appendChild(title);
  }
  const nextActions = (readiness.nextActions || []).slice(0, 3);
  if (nextActions.length) {
    for (const item of nextActions) {
      const row = document.createElement("div");
      row.className = "quality-row";
      row.textContent = `${t("releaseReadiness.nextActions")}: ${item}`;
      pr.appendChild(row);
    }
  }
}

async function startReleaseReadiness() {
  if (!state.selectedRunId) return;
  const action = $("release-readiness-action");
  action.disabled = true;
  action.textContent = t("releaseReadiness.generating");
  await fetchJson(`/api/runs/${encodeURIComponent(state.selectedRunId)}${RELEASE_READINESS_ENDPOINT_SUFFIX}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  await refreshRun();
}

function renderGithubPrCi(vm) {
  const githubPr = vm.githubPr || {};
  const readiness = vm.releaseReadiness || {};
  const prAction = $("github-pr-action");
  const ciAction = $("github-ci-action");
  const summary = $("github-pr-summary");
  const prInfo = $("github-pr-info");
  const ciInfo = $("github-ci-info");
  if (!prAction || !ciAction || !summary || !prInfo || !ciInfo) return;

  const decision = readiness.decision || "not_generated";
  const canCreate = decision === "ready_for_pr_ci" || decision === "ready_with_warnings";
  const hasPr = githubPr.status === "created" && githubPr.pr && githubPr.pr.url;
  prAction.disabled = !canCreate || hasPr;
  ciAction.disabled = !hasPr;
  prAction.textContent = t("githubPr.createDraftButton");
  ciAction.textContent = t("githubPr.refreshCiButton");
  prAction.onclick = startGithubDraftPr;
  ciAction.onclick = refreshGithubCi;

  if (!canCreate) {
    summary.textContent = readiness.decision === "blocked" ? t("githubPr.blockedByReadiness") : t("githubPr.notReady");
  } else if (hasPr) {
    summary.textContent = `${githubPr.statusLabel || t("githubPr.status.created")} · ${githubPr.ciStatusLabel || ""} · ${githubPr.summary || ""}`;
  } else {
    summary.textContent = t("githubPr.readyToCreate");
  }

  prInfo.textContent = "";
  const prRows = [];
  const pr = githubPr.pr || {};
  if (hasPr) {
    prRows.push(`${t("githubPr.prUrl")}: ${pr.url}`);
    prRows.push(`${t("githubPr.baseHead")}: ${pr.base || ""} <- ${pr.head || ""}`);
    prRows.push(`${t("githubPr.draft")}: ${pr.is_draft === false ? t("githubPr.no") : t("githubPr.yes")}`);
  } else {
    prRows.push(t("githubPr.noPr"));
  }
  for (const blocker of githubPr.blockers || []) prRows.push(`${t("githubPr.blocker")}: ${blocker}`);
  for (const warning of githubPr.warnings || []) prRows.push(`${t("githubPr.warning")}: ${warning}`);
  for (const rowText of prRows.slice(0, 8)) {
    const row = document.createElement("div");
    row.className = "quality-row";
    row.textContent = rowText;
    prInfo.appendChild(row);
  }

  ciInfo.textContent = "";
  const checks = githubPr.checks || [];
  if (!checks.length) {
    const empty = document.createElement("div");
    empty.className = "quality-row";
    empty.textContent = hasPr ? t("githubPr.noChecks") : t("githubPr.noPr");
    ciInfo.appendChild(empty);
  } else {
    for (const check of checks.slice(0, 8)) {
      const row = document.createElement("div");
      row.className = `quality-row github-check github-check-${String(check.conclusion || check.status || "unknown").toLowerCase()}`;
      row.textContent = `${check.name || t("app.unknown")}: ${check.status || ""} / ${check.conclusion || ""}`;
      ciInfo.appendChild(row);
    }
  }
  if (githubPr.nextAction) {
    const next = document.createElement("div");
    next.className = "quality-row";
    next.textContent = `${t("githubPr.nextAction")}: ${githubPr.nextAction}`;
    ciInfo.appendChild(next);
  }
}

async function startGithubDraftPr() {
  if (!state.selectedRunId) return;
  const action = $("github-pr-action");
  action.disabled = true;
  action.textContent = t("githubPr.creating");
  await fetchJson(`/api/runs/${encodeURIComponent(state.selectedRunId)}${GITHUB_PR_DRAFT_ENDPOINT_SUFFIX}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  await refreshRun();
}

async function refreshGithubCi() {
  if (!state.selectedRunId) return;
  const action = $("github-ci-action");
  action.disabled = true;
  action.textContent = t("githubPr.refreshing");
  await fetchJson(`/api/runs/${encodeURIComponent(state.selectedRunId)}${GITHUB_PR_STATUS_ENDPOINT_SUFFIX}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  await refreshRun();
}

function renderStagingReadiness(vm) {
  const staging = vm.stagingReadiness || {};
  const githubPr = vm.githubPr || {};
  const action = $("staging-readiness-action");
  const summary = $("staging-readiness-summary");
  const gates = $("staging-readiness-gates");
  const evidence = $("staging-readiness-evidence");
  if (!action || !summary || !gates || !evidence) return;

  const hasPr = githubPr.status === "created" && githubPr.pr && githubPr.pr.url;
  const canGenerate = hasPr || (githubPr.ciStatus && githubPr.ciStatus !== "not_started");
  action.disabled = !canGenerate;
  action.textContent = t("stagingReadiness.generateButton");
  action.onclick = startStagingReadiness;
  summary.textContent = staging.summary || (canGenerate ? t("stagingReadiness.readyToGenerate") : t("stagingReadiness.empty"));

  gates.textContent = "";
  const gateItems = (staging.gates || []).slice(0, 6);
  if (!gateItems.length) {
    const empty = document.createElement("div");
    empty.className = "quality-row";
    empty.textContent = t("stagingReadiness.noGates");
    gates.appendChild(empty);
  } else {
    for (const gate of gateItems) {
      const row = document.createElement("div");
      row.className = `quality-row release-gate-row release-gate-${gate.status || "unknown"}`;
      row.textContent = `${gate.id || t("app.unknown")}: ${gate.status || ""} · ${gate.reason || ""}`;
      gates.appendChild(row);
    }
  }

  evidence.textContent = "";
  const rows = [];
  rows.push(`${t("stagingReadiness.decision")}: ${staging.decisionLabel || t("stagingReadiness.decisions.not_generated")}`);
  if (staging.evidence) {
    if (staging.evidence.pr_url) rows.push(`${t("stagingReadiness.prUrl")}: ${staging.evidence.pr_url}`);
    if (staging.evidence.ci_status) rows.push(`${t("stagingReadiness.ciStatus")}: ${staging.evidence.ci_status}`);
    if (staging.evidence.ci_summary) rows.push(`${t("stagingReadiness.ciSummary")}: ${staging.evidence.ci_summary}`);
  }
  for (const blocker of staging.blockers || []) rows.push(`${t("stagingReadiness.blocker")}: ${blocker}`);
  for (const warning of staging.warnings || []) rows.push(`${t("stagingReadiness.warning")}: ${warning}`);
  for (const item of (staging.nextActions || []).slice(0, 3)) rows.push(`${t("stagingReadiness.nextActions")}: ${item}`);
  for (const rowText of rows.slice(0, 10)) {
    const row = document.createElement("div");
    row.className = "quality-row";
    row.textContent = rowText;
    evidence.appendChild(row);
  }
}

async function startStagingReadiness() {
  if (!state.selectedRunId) return;
  const action = $("staging-readiness-action");
  action.disabled = true;
  action.textContent = t("stagingReadiness.generating");
  await fetchJson(`/api/runs/${encodeURIComponent(state.selectedRunId)}${STAGING_READINESS_ENDPOINT_SUFFIX}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  await refreshRun();
}

function renderStagingRehearsal(vm) {
  const rehearsal = vm.stagingRehearsal || {};
  const staging = vm.stagingReadiness || {};
  const action = $("staging-rehearsal-action");
  const summary = $("staging-rehearsal-summary");
  const details = $("staging-rehearsal-details");
  if (!action || !summary || !details) return;

  const canRun = staging.decision === "ready_for_staging" && rehearsal.status !== "running";
  action.disabled = !canRun;
  action.textContent = rehearsal.status === "running" ? t("stagingRehearsal.running") : t("stagingRehearsal.runButton");
  action.onclick = startStagingRehearsal;
  summary.textContent = rehearsal.summary || (canRun ? t("stagingRehearsal.readyToRun") : t("stagingRehearsal.empty"));

  details.textContent = "";
  const rows = [];
  rows.push(`${t("stagingRehearsal.status")}: ${rehearsal.statusLabel || t("stagingRehearsal.statuses.not_started")}`);
  if (rehearsal.stagingReadinessDecision) rows.push(`${t("stagingReadiness.decision")}: ${rehearsal.stagingReadinessDecision}`);
  for (const step of rehearsal.steps || []) {
    rows.push(`${step.id || t("app.unknown")}: ${step.status || ""}${step.command ? ` · ${step.command}` : ""}${step.exit_code == null ? "" : ` · ${t("acceptance.exitCode")}: ${step.exit_code}`}`);
    for (const line of [...(step.stdout_tail || []), ...(step.stderr_tail || [])].slice(-4)) rows.push(`${t("stagingRehearsal.logs")}: ${line}`);
  }
  for (const blocker of rehearsal.blockers || []) rows.push(`${t("stagingRehearsal.blocker")}: ${blocker}`);
  for (const warning of rehearsal.warnings || []) rows.push(`${t("stagingRehearsal.warning")}: ${warning}`);
  for (const item of (rehearsal.nextActions || []).slice(0, 3)) rows.push(`${t("stagingRehearsal.nextActions")}: ${item}`);
  renderCompactRows(details, rows, t("stagingRehearsal.empty"));
}

async function startStagingRehearsal() {
  if (!state.selectedRunId) return;
  const action = $("staging-rehearsal-action");
  action.disabled = true;
  action.textContent = t("stagingRehearsal.running");
  await fetchJson(`/api/runs/${encodeURIComponent(state.selectedRunId)}${STAGING_REHEARSAL_ENDPOINT_SUFFIX}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  await refreshRun();
}

function renderProductionReadiness(vm) {
  const production = vm.productionReadiness || {};
  const rehearsal = vm.stagingRehearsal || {};
  const staging = vm.stagingReadiness || {};
  const action = $("production-readiness-action");
  const summary = $("production-readiness-summary");
  const gates = $("production-readiness-gates");
  const evidence = $("production-readiness-evidence");
  if (!action || !summary || !gates || !evidence) return;

  const canGenerate = rehearsal.status === "completed" || staging.decision === "ready_for_staging";
  action.disabled = !canGenerate;
  action.textContent = t("productionReadiness.generateButton");
  action.onclick = startProductionReadiness;
  summary.textContent = production.summary || (canGenerate ? t("productionReadiness.readyToGenerate") : t("productionReadiness.empty"));

  gates.textContent = "";
  const gateItems = (production.gates || []).slice(0, 8);
  if (!gateItems.length) {
    const empty = document.createElement("div");
    empty.className = "quality-row";
    empty.textContent = t("productionReadiness.noGates");
    gates.appendChild(empty);
  } else {
    for (const gate of gateItems) {
      const row = document.createElement("div");
      row.className = `quality-row release-gate-row release-gate-${gate.status || "unknown"}`;
      row.textContent = `${gate.id || t("app.unknown")}: ${gate.status || ""} · ${gate.reason || ""}`;
      gates.appendChild(row);
    }
  }

  evidence.textContent = "";
  const ev = production.evidence || {};
  const localValidation = ev.local_validation || {};
  const macMiniValidation = ev.mac_mini_validation || {};
  const macMini = ev.mac_mini || {};
  const cloud = ev.cloud_asset_center || {};
  const smoke = ev.collector_smoke || {};
  const sync = ev.cloud_sync || {};
  const localCloud = localValidation.cloud_asset_center || cloud;
  const macDoctor = macMiniValidation.doctor || macMini;
  const macSmoke = macMiniValidation.collector_smoke || smoke;
  const macSync = macMiniValidation.cloud_sync || sync;
  const rows = [];
  rows.push(`${t("productionReadiness.decision")}: ${production.decisionLabel || t("productionReadiness.decisions.not_generated")}`);
  if (ev.staging_decision) rows.push(`${t("stagingReadiness.decision")}: ${ev.staging_decision}`);
  if (ev.staging_rehearsal_status) rows.push(`${t("stagingRehearsal.status")}: ${ev.staging_rehearsal_status}`);
  if (localValidation.profile) rows.push(`${t("productionReadiness.localValidation")}: ${localValidation.profile}`);
  if (localCloud.status) rows.push(`${t("productionReadiness.cloudAssetCenter")}: ${localCloud.status}`);
  if (macMiniValidation.profile) rows.push(`${t("productionReadiness.macMiniValidation")}: ${macMiniValidation.profile}`);
  if (macDoctor.status) rows.push(`${t("productionReadiness.macMini")}: ${macDoctor.status}`);
  if (macSmoke.status) rows.push(`${t("productionReadiness.collectorSmoke")}: ${macSmoke.status}${macSmoke.result_count == null ? "" : ` · ${t("productionReadiness.resultCount")}: ${macSmoke.result_count}`}`);
  if (macSync.status) rows.push(`${t("productionReadiness.cloudSync")}: ${macSync.status}${macSync.synced_assets == null ? "" : ` · ${t("productionReadiness.syncedAssets")}: ${macSync.synced_assets}`}`);
  for (const blocker of production.blockers || []) rows.push(`${t("productionReadiness.blocker")}: ${blocker}`);
  for (const warning of production.warnings || []) rows.push(`${t("productionReadiness.warning")}: ${warning}`);
  for (const item of (production.nextActions || []).slice(0, 3)) rows.push(`${t("productionReadiness.nextActions")}: ${item}`);
  renderCompactRows(evidence, rows, t("productionReadiness.empty"));
}

async function startProductionReadiness() {
  if (!state.selectedRunId) return;
  const action = $("production-readiness-action");
  action.disabled = true;
  action.textContent = t("productionReadiness.generating");
  await fetchJson(`/api/runs/${encodeURIComponent(state.selectedRunId)}${PRODUCTION_READINESS_ENDPOINT_SUFFIX}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  await refreshRun();
}

function renderArtifactActions(deliverables) {
  const container = $("artifact-actions");
  if (!container) return;
  container.textContent = "";
  for (const artifact of deliverables) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = artifact.path === state.selectedArtifactPath ? "artifact-button selected" : "artifact-button";
    button.disabled = !artifact.exists;
    button.textContent = artifact.exists ? artifact.title : `${artifact.title} (${t("actions.artifactPending")})`;
    button.addEventListener("click", () => selectArtifact(artifact));
    container.appendChild(button);
  }
}

function ensureSelectedArtifact(vm) {
  const deliverables = vm.deliverables || [];
  const selected = deliverables.find((artifact) => artifact.path === state.selectedArtifactPath && artifact.exists);
  if (selected) {
    renderSelectedArtifact(selected);
    return;
  }
  if (vm.recommendedArtifact) {
    selectArtifact(vm.recommendedArtifact);
    return;
  }
  renderSelectedArtifact(null);
}

function selectArtifact(artifact) {
  if (!artifact || !artifact.exists) return;
  state.selectedArtifactPath = artifact.path;
  if (artifact.path !== "codex/diff.patch") state.selectedDiffFilePath = "";
  updateFlowArtifactButtons();
  renderSelectedArtifact(artifact);
  loadArtifact(artifact);
}

function updateFlowArtifactButtons() {
  const container = $("flow-artifact-actions");
  if (!container) return;
  for (const button of container.querySelectorAll(".artifact-button")) {
    button.classList.toggle("selected", button.dataset.path === state.selectedArtifactPath);
  }
}

function renderSelectedArtifact(artifact) {
  $("selected-artifact-title").textContent = artifact ? artifact.title : t("actions.noDeliverables");
  $("selected-artifact-description").textContent = artifact ? artifact.description : "";
  $("selected-artifact-status").textContent = artifact ? t("actions.artifactReady") : t("actions.artifactPending");
}

async function loadArtifact(artifact) {
  if (!state.selectedRunId) return;
  const content = await loadArtifactContent(artifact);
  if (artifact.path === "codex/diff.patch") {
    renderDiffArtifact(content, artifact);
    return;
  }
  const preview = $("flow-artifact-preview");
  preview.className = "artifact-preview";
  preview.textContent = content;
}

async function loadArtifactContent(artifact) {
  const params = new URLSearchParams({ path: artifact.path, scope: artifact.scope || "run" });
  const data = await fetchJson(`/api/runs/${encodeURIComponent(state.selectedRunId)}/artifact?${params.toString()}`);
  return data.content || "";
}

function renderNextActions(actions) {
  const container = $("next-actions");
  container.textContent = "";
  if (!actions.length) {
    const row = document.createElement("div");
    row.className = "action-row meta";
    row.textContent = t("actions.noNextAction");
    container.appendChild(row);
    return;
  }
  for (const action of actions) {
    const row = document.createElement("div");
    row.className = "action-row meta";
    row.textContent = action;
    container.appendChild(row);
  }
}

function renderEngineering(vm) {
  if (!$("engineering-run")) return;
  $("engineering-run").textContent = [vm.engineering.runId, vm.engineering.status, vm.engineering.executor].filter(Boolean).join("\n");
  $("engineering-events").textContent = JSON.stringify(vm.engineering.events || [], null, 2);
  const rawWarnings = (vm.engineering.healthSummary || {}).raw_warnings || [];
  const warningSection = rawWarnings.length ? ["", t("health.rawWarningsLabel"), ...rawWarnings] : [];
  $("engineering-logs").textContent = [...(vm.engineering.logs || []), ...warningSection].join("\n");
  $("engineering-diff").textContent = renderDiffSummary(vm.engineering.diffSummary || {});
}

function renderDiffSummary(diffSummary) {
  if (!diffSummary || !diffSummary.available) return t("diffView.empty");
  const files = diffSummary.files || [];
  const rows = [
    `${diffSummary.files_changed || files.length || 0} ${t("diffView.changedFiles")}，+${diffSummary.additions || 0} / -${diffSummary.deletions || 0}`,
  ];
  for (const file of files.slice(0, 8)) {
    rows.push(`${file.path || t("app.unknown")}  ${statusText(file.status)}  +${file.additions || 0} / -${file.deletions || 0}`);
  }
  if (files.length > 8) rows.push(`... ${files.length - 8}`);
  return rows.join("\n");
}

function renderDiffArtifact(rawPatch, artifact) {
  const preview = $("flow-artifact-preview");
  preview.className = "artifact-preview diff-artifact-preview";
  preview.textContent = "";

  const parsed = parseUnifiedDiff(rawPatch);
  const wrapper = document.createElement("div");
  wrapper.className = "diff-view";
  wrapper.setAttribute("role", "region");
  wrapper.setAttribute("aria-label", artifact.title || t("artifacts.codex/diff.patch.title"));

  if (!parsed.files.length) {
    const empty = document.createElement("p");
    empty.className = "summary-text";
    empty.textContent = rawPatch && rawPatch.trim() ? t("diffView.binaryOrNoText") : t("diffView.empty");
    wrapper.appendChild(empty);
    preview.appendChild(wrapper);
    return;
  }

  if (!state.selectedDiffFilePath || !parsed.files.some((file) => file.path === state.selectedDiffFilePath)) {
    state.selectedDiffFilePath = parsed.files[0].path;
  }
  const selectedFile = parsed.files.find((file) => file.path === state.selectedDiffFilePath) || parsed.files[0];

  const summary = document.createElement("div");
  summary.className = "diff-summary";
  summary.textContent = `${parsed.files.length} ${t("diffView.changedFiles")}，+${parsed.additions} / -${parsed.deletions}`;

  const body = document.createElement("div");
  body.className = "diff-body";

  const fileList = document.createElement("div");
  fileList.className = "diff-file-list";
  for (const file of parsed.files) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = file.path === selectedFile.path ? "diff-file-button selected" : "diff-file-button";
    button.addEventListener("click", () => {
      state.selectedDiffFilePath = file.path;
      renderDiffArtifact(rawPatch, artifact);
    });

    const name = document.createElement("span");
    name.className = "diff-file-name";
    name.textContent = file.path;
    const meta = document.createElement("span");
    meta.className = "diff-file-meta";
    meta.textContent = `${statusText(file.status)}  +${file.additions} / -${file.deletions}`;
    button.append(name, meta);
    fileList.appendChild(button);
  }

  const diffPreview = document.createElement("div");
  diffPreview.className = "diff-preview";
  if (!selectedFile.lines.length) {
    const empty = document.createElement("p");
    empty.className = "summary-text";
    empty.textContent = t("diffView.binaryOrNoText");
    diffPreview.appendChild(empty);
  } else {
    for (const line of selectedFile.lines) {
      const row = document.createElement("div");
      row.className = `diff-line ${diffLineClass(line)}`;
      row.textContent = line || " ";
      diffPreview.appendChild(row);
    }
  }

  body.append(fileList, diffPreview);
  wrapper.append(summary, body);
  preview.appendChild(wrapper);
}

function parseUnifiedDiff(rawPatch) {
  const files = [];
  let current = null;
  let inHunk = false;

  function finishCurrent() {
    if (!current) return;
    files.push({
      path: current.path || current.newPath || current.oldPath || t("app.unknown"),
      status: current.status || "modified",
      additions: current.additions || 0,
      deletions: current.deletions || 0,
      lines: current.lines || [],
    });
    current = null;
  }

  for (const line of String(rawPatch || "").split(/\r?\n/)) {
    if (line.startsWith("diff --git ")) {
      finishCurrent();
      const paths = parseDiffGitPaths(line);
      current = {
        path: paths.newPath || paths.oldPath,
        oldPath: paths.oldPath,
        newPath: paths.newPath,
        status: "modified",
        additions: 0,
        deletions: 0,
        lines: [line],
      };
      inHunk = false;
      continue;
    }
    if (!current) continue;
    current.lines.push(line);
    if (line.startsWith("new file mode")) current.status = "added";
    if (line.startsWith("deleted file mode")) current.status = "deleted";
    if (line.startsWith("rename from ")) {
      current.status = "renamed";
      current.oldPath = normalizeDiffPath(line.replace("rename from ", ""));
    }
    if (line.startsWith("rename to ")) {
      current.status = "renamed";
      current.newPath = normalizeDiffPath(line.replace("rename to ", ""));
      current.path = current.newPath;
    }
    if (line.startsWith("--- ")) {
      const oldPath = normalizeDiffPath(line.replace("--- ", ""));
      if (oldPath === "/dev/null") current.status = "added";
      else current.oldPath = oldPath;
    } else if (line.startsWith("+++ ")) {
      const newPath = normalizeDiffPath(line.replace("+++ ", ""));
      if (newPath === "/dev/null") {
        current.status = "deleted";
        current.path = current.oldPath || current.path;
      } else {
        current.newPath = newPath;
        current.path = newPath;
      }
    } else if (line.startsWith("@@")) {
      inHunk = true;
    } else if (inHunk && line.startsWith("+") && !line.startsWith("+++")) {
      current.additions += 1;
    } else if (inHunk && line.startsWith("-") && !line.startsWith("---")) {
      current.deletions += 1;
    }
  }
  finishCurrent();
  return {
    files,
    additions: files.reduce((total, file) => total + file.additions, 0),
    deletions: files.reduce((total, file) => total + file.deletions, 0),
  };
}

function parseDiffGitPaths(line) {
  const match = line.match(/^diff --git a\/(.*?) b\/(.*)$/);
  if (!match) return { oldPath: "", newPath: "" };
  return { oldPath: normalizeDiffPath(match[1]), newPath: normalizeDiffPath(match[2]) };
}

function normalizeDiffPath(path) {
  const value = String(path || "").trim().replace(/^"|"$/g, "");
  if (value === "/dev/null" || value === "dev/null") return "/dev/null";
  if (value.startsWith("a/") || value.startsWith("b/")) return value.slice(2);
  return value;
}

function diffLineClass(line) {
  if (line.startsWith("+") && !line.startsWith("+++")) return "diff-line-add";
  if (line.startsWith("-") && !line.startsWith("---")) return "diff-line-remove";
  if (line.startsWith("diff --git") || line.startsWith("@@") || line.startsWith("index ") || line.startsWith("---") || line.startsWith("+++") || line.startsWith("new file mode") || line.startsWith("deleted file mode") || line.startsWith("rename ")) {
    return "diff-line-meta";
  }
  return "diff-line-context";
}

function statusText(status) {
  return t(`diffView.${status || "modified"}`, status || "");
}

async function startRun(event) {
  event.preventDefault();
  const brief = $("brief").value.trim();
  if (!brief) {
    $("brief").focus();
    return;
  }
  const payload = {
    brief,
    domain: $("domain").value.trim() || "web_monitoring",
    executor: $("executor").value,
    provider: $("provider").value,
    model: $("model").value.trim(),
  };
  const data = await fetchJson("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  await refreshRuns();
  await selectRun(data.run_id);
}

function startPolling() {
  if (state.timer) clearInterval(state.timer);
  state.timer = setInterval(async () => {
    try {
      await refreshRuns();
      await refreshRun();
    } catch (error) {
      $("flow-artifact-preview").textContent = String(error.message || error);
    }
  }, 2000);
}

async function boot() {
  await loadI18n();
  $("run-form").addEventListener("submit", startRun);
  $("refresh-runs").addEventListener("click", refreshRuns);
  await refreshRuns();
  startPolling();
}

boot().catch((error) => {
  const target = $("flow-artifact-preview");
  if (target) target.textContent = String(error.message || error);
});
