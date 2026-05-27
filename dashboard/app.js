const state = {
  selectedRunId: "",
  selectedArtifactPath: "",
  selectedStageDetail: null,
  timer: null,
  i18n: null,
  currentRun: null,
  currentVm: null,
};

const $ = (id) => document.getElementById(id);
const view = window.BusinessView;

function t(path, fallback = "") {
  return view.lookup(state.i18n, path, fallback || view.lookup(state.i18n, "app.unknown", "未知项"));
}

function statusClass(tone) {
  return `status-${tone || "muted"}`;
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
    title.textContent = run.brief || run.domain_id || t("app.unknown");
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
  state.selectedStageDetail = null;
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
  $("current-task").textContent = vm.brief || t("app.emptySelection");
  $("brief-label").textContent = vm.runId ? `${t("app.currentTask")} ${vm.runId}` : "";
  $("task-headline").textContent = vm.headline || "";

  const pill = $("status-pill");
  pill.className = `status-pill ${statusClass(view.lookup(state.i18n, `status.${vm.status}.tone`, "muted"))}`;
  pill.textContent = vm.statusLabel;

  renderStages(vm.stages || []);
  renderStageDetail(vm);
  renderHealth(vm.health || {});
  renderArtifactQuality(vm.artifactQuality || {});
  renderGates(vm.qualityGates || []);
  renderArtifactActions(vm.deliverables || []);
  ensureSelectedArtifact(vm);
  renderNextActions(vm.nextActions || []);
  renderEngineering(vm);
}

function renderHealth(health) {
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

function renderStages(stages) {
  const container = $("business-stages");
  container.textContent = "";
  for (const stage of stages) {
    const card = document.createElement("article");
    card.className = "business-stage-card";

    const header = document.createElement("div");
    header.className = "card-title-row";
    const title = document.createElement("h3");
    title.textContent = stage.title;
    const status = document.createElement("span");
    status.className = `mini-status ${statusClass(stage.tone)}`;
    status.textContent = stage.statusLabel;
    header.append(title, status);

    const summary = document.createElement("p");
    summary.className = "stage-summary";
    summary.textContent = stage.summary;

    const rows = document.createElement("dl");
    rows.className = "stage-rows";
    for (const row of stage.rows || []) {
      const term = document.createElement("dt");
      term.textContent = row.label;
      const detail = document.createElement("dd");
      detail.textContent = row.text;
      rows.append(term, detail);
    }

    const actions = document.createElement("div");
    actions.className = "card-actions";
    for (const action of stage.actions || []) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ghost small";
      button.textContent = t(`actions.${action}`);
      button.addEventListener("click", () => handleStageAction(action, stage));
      actions.appendChild(button);
    }

    card.append(header, summary, rows, actions);
    container.appendChild(card);
  }
}

function handleStageAction(action, stage) {
  if (action === "viewDeliverables") {
    const first = (stage.artifacts || []).find((artifact) => artifact.exists);
    if (first) selectArtifact(first);
    toggleStageDetail(stage, "deliverables");
    return;
  }
  if (action === "viewRisks") {
    $("artifact-preview").textContent = view.toBusinessViewModel(state.currentRun || {}, state.i18n).risks.join("\n");
    focusSection("deliverables-panel");
    return;
  }
  toggleStageDetail(stage, "engineering");
}

function toggleStageDetail(stage, mode) {
  const current = state.selectedStageDetail || {};
  if (current.stageId === stage.id && current.mode === mode) {
    state.selectedStageDetail = null;
  } else {
    state.selectedStageDetail = { stageId: stage.id, mode };
  }
  renderStageDetail(state.currentVm || view.toBusinessViewModel(state.currentRun || {}, state.i18n));
}

function renderStageDetail(vm) {
  const panel = $("stage-detail-panel");
  if (!panel) return;
  panel.textContent = "";
  const selection = state.selectedStageDetail;
  if (!selection) {
    panel.hidden = true;
    return;
  }
  const stage = (vm.stages || []).find((item) => item.id === selection.stageId);
  if (!stage) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;

  const header = document.createElement("div");
  header.className = "stage-detail-header";
  const title = document.createElement("h3");
  title.textContent = `${stage.title} / ${selection.mode === "engineering" ? t("stageDetail.engineeringSuffix") : t("stageDetail.deliverablesSuffix")}`;
  const status = document.createElement("span");
  status.className = `mini-status ${statusClass(stage.tone)}`;
  status.textContent = stage.statusLabel;
  header.append(title, status);

  const body = document.createElement("div");
  body.className = "stage-detail-body";
  if (selection.mode === "engineering") {
    renderStageEngineering(stage, vm, body);
  } else {
    renderStageDeliverables(stage, body);
  }

  panel.append(header, body);
}

function renderStageDeliverables(stage, container) {
  const artifacts = (stage.artifacts || []).filter((artifact) => artifact.exists);
  if (!artifacts.length) {
    const empty = document.createElement("p");
    empty.className = "summary-text";
    empty.textContent = t("stageDetail.emptyDeliverables");
    container.appendChild(empty);
    return;
  }

  const list = document.createElement("div");
  list.className = "stage-artifact-list";
  for (const artifact of artifacts) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = artifact.path === state.selectedArtifactPath ? "artifact-button selected" : "artifact-button";
    button.textContent = artifact.title;
    button.addEventListener("click", () => {
      selectArtifact(artifact);
      renderStageDetail(state.currentVm || view.toBusinessViewModel(state.currentRun || {}, state.i18n));
    });
    list.appendChild(button);
  }

  const preview = document.createElement("div");
  preview.className = "stage-detail-preview";
  const selected = artifacts.find((artifact) => artifact.path === state.selectedArtifactPath) || artifacts[0];
  const heading = document.createElement("h4");
  heading.textContent = `${t("stageDetail.selectedArtifact")}: ${selected.title}`;
  const description = document.createElement("p");
  description.className = "summary-text";
  description.textContent = selected.description || t("stageDetail.globalArtifactsHint");
  const content = document.createElement("pre");
  content.className = "stage-artifact-preview";
  content.textContent = "";
  const hint = document.createElement("p");
  hint.className = "meta";
  hint.textContent = t("stageDetail.globalArtifactsHint");
  preview.append(heading, description, content, hint);
  loadArtifactContent(selected).then((value) => {
    content.textContent = value;
  }).catch((error) => {
    content.textContent = String(error.message || error);
  });

  const action = document.createElement("button");
  action.type = "button";
  action.className = "ghost small";
  action.textContent = t("stageDetail.openGlobalDeliverables");
  action.addEventListener("click", () => focusSection("deliverables-panel"));
  preview.appendChild(action);

  container.append(list, preview);
}

function renderStageEngineering(stage, vm, container) {
  const related = filterEngineeringForStage(stage, vm);
  const agents = document.createElement("div");
  agents.className = "stage-detail-block";
  const agentTitle = document.createElement("strong");
  agentTitle.textContent = t("stageDetail.relatedAgents");
  const agentText = document.createElement("p");
  agentText.className = "summary-text";
  agentText.textContent = (stage.agentIds || []).join(", ") || t("stageDetail.emptyEngineering");
  agents.append(agentTitle, agentText);

  const events = stageDetailList(t("stageDetail.relatedEvents"), related.events, t("stageDetail.emptyEngineering"));
  const logs = stageDetailList(t("stageDetail.relatedLogs"), related.logs, t("stageDetail.globalEngineeringHint"));
  const risks = stageDetailList(t("stageDetail.riskEvents"), related.risks, t("actions.noRisk"));

  const action = document.createElement("button");
  action.type = "button";
  action.className = "ghost small";
  action.textContent = t("stageDetail.openGlobalEngineering");
  action.addEventListener("click", () => focusSection("engineering-rail"));

  container.append(agents, events, logs, risks, action);
}

function stageDetailList(title, values, emptyText) {
  const block = document.createElement("div");
  block.className = "stage-detail-block";
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
  for (const item of items) {
    const row = document.createElement("li");
    row.textContent = typeof item === "string" ? item : JSON.stringify(item);
    list.appendChild(row);
  }
  block.appendChild(list);
  return block;
}

function filterEngineeringForStage(stage, vm) {
  const agentIds = stage.agentIds || [];
  const engineering = vm.engineering || {};
  const events = (engineering.events || []).filter((event) => {
    const text = JSON.stringify(event);
    return agentIds.some((agentId) => text.includes(agentId));
  });
  const logs = (engineering.logs || []).filter((line) => agentIds.some((agentId) => String(line).includes(agentId)));
  const fallbackLogs = logs.length ? logs : (engineering.logs || []).slice(0, 3);
  const risks = (vm.risks || []).filter((risk) => risk && risk !== t("actions.noRisk"));
  return { events, logs: fallbackLogs, risks };
}

function focusSection(id) {
  const target = $(id);
  if (!target) return;
  target.scrollIntoView({ behavior: "smooth", block: "start" });
  if (typeof target.focus === "function") target.focus({ preventScroll: true });
}

function renderGates(gates) {
  const container = $("quality-gates");
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

function renderArtifactActions(deliverables) {
  const container = $("artifact-actions");
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
  renderArtifactActions((view.toBusinessViewModel(state.currentRun || {}, state.i18n).deliverables || []));
  renderSelectedArtifact(artifact);
  loadArtifact(artifact);
}

function renderSelectedArtifact(artifact) {
  $("selected-artifact-title").textContent = artifact ? artifact.title : t("actions.noDeliverables");
  $("selected-artifact-description").textContent = artifact ? artifact.description : "";
  $("selected-artifact-status").textContent = artifact ? t("actions.artifactReady") : t("actions.artifactPending");
}

async function loadArtifact(artifact) {
  if (!state.selectedRunId) return;
  $("artifact-preview").textContent = await loadArtifactContent(artifact);
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
  $("engineering-run").textContent = [vm.engineering.runId, vm.engineering.status, vm.engineering.executor].filter(Boolean).join("\n");
  $("engineering-events").textContent = JSON.stringify(vm.engineering.events || [], null, 2);
  const rawWarnings = (vm.engineering.healthSummary || {}).raw_warnings || [];
  const warningSection = rawWarnings.length ? ["", t("health.rawWarningsLabel"), ...rawWarnings] : [];
  $("engineering-logs").textContent = [...(vm.engineering.logs || []), ...warningSection].join("\n");
  $("engineering-diff").textContent = JSON.stringify(vm.engineering.diffSummary || {}, null, 2);
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
      $("artifact-preview").textContent = String(error.message || error);
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
  const target = $("artifact-preview");
  if (target) target.textContent = String(error.message || error);
});
