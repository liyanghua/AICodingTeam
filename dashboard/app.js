const state = {
  selectedRunId: "",
  selectedArtifactPath: "",
  selectedDiffFilePath: "",
  selectedStageDetail: null,
  stageDetailScroll: { key: "", top: 0 },
  timer: null,
  i18n: null,
  currentRun: null,
  currentVm: null,
};

const $ = (id) => document.getElementById(id);
const view = window.BusinessView;
const ACCEPTANCE_ENDPOINT_SUFFIX = "/acceptance";

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
  state.selectedDiffFilePath = "";
  state.selectedStageDetail = null;
  state.stageDetailScroll = { key: "", top: 0 };
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
  renderAcceptance(vm);
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
    state.stageDetailScroll = { key: "", top: 0 };
  } else {
    state.selectedStageDetail = { stageId: stage.id, mode };
    state.stageDetailScroll = { key: stageDetailKey(state.selectedStageDetail), top: 0 };
  }
  renderStageDetail(state.currentVm || view.toBusinessViewModel(state.currentRun || {}, state.i18n));
}

function stageDetailKey(selection = state.selectedStageDetail) {
  if (!selection) return "";
  return `${state.selectedRunId || ""}:${selection.stageId || ""}:${selection.mode || ""}`;
}

function captureStageDetailScroll() {
  const body = document.querySelector("#stage-detail-panel .stage-detail-body");
  if (!body || !state.selectedStageDetail) return;
  state.stageDetailScroll = { key: stageDetailKey(), top: body.scrollTop || 0 };
}

function restoreStageDetailScroll(body) {
  if (!body || !state.selectedStageDetail) return;
  const currentKey = stageDetailKey();
  if (state.stageDetailScroll.key !== currentKey) return;
  const top = Math.min(state.stageDetailScroll.top || 0, Math.max(0, body.scrollHeight - body.clientHeight));
  body.scrollTop = top;
}

function renderStageDetail(vm) {
  const panel = $("stage-detail-panel");
  if (!panel) return;
  captureStageDetailScroll();
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
  body.className = `stage-detail-body ${selection.mode === "engineering" ? "engineering-mode" : "deliverables-mode"}`;
  if (selection.mode === "engineering") {
    renderStageEngineering(stage, vm, body);
  } else {
    renderStageDeliverables(stage, body);
  }

  body.addEventListener("scroll", () => {
    state.stageDetailScroll = { key: stageDetailKey(), top: body.scrollTop || 0 };
  });
  panel.append(header, body);
  restoreStageDetailScroll(body);
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
  if (stage.id === "implementation") {
    renderImplementationFlow(vm.implementationFlow || {}, container);
  }
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

  const inputs = stageDetailList(
    t("implementationFlow.inputs"),
    (flow.inputs || []).filter((item) => item.exists).map((item) => `${item.title || item.path}: ${item.path}`),
    t("implementationFlow.none"),
  );

  const timeline = document.createElement("div");
  timeline.className = "stage-detail-block";
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
  const changedFiles = stageDetailList(t("implementationFlow.changedFiles"), evidence.changed_files || [], t("implementationFlow.none"));
  const testEvidence = (evidence.tests_run || []).length ? evidence.tests_run : evidence.verification_commands || [];
  const testsRun = stageDetailList(t("implementationFlow.testsRun"), testEvidence, t("implementationFlow.none"));
  const blockers = stageDetailList(t("implementationFlow.blockers"), flow.blockers || [], t("implementationFlow.none"));
  const risks = stageDetailList(t("implementationFlow.risks"), flow.risk_events || [], t("implementationFlow.none"));
  const nextAction = stageDetailList(t("implementationFlow.nextAction"), flow.next_action ? [flow.next_action] : [], t("implementationFlow.none"));

  panel.append(current, inputs, timeline, changedFiles, testsRun, blockers, risks, nextAction);
  container.appendChild(panel);
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
  list.className = "stage-detail-list";
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
  if (artifact.path !== "codex/diff.patch") state.selectedDiffFilePath = "";
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
  const content = await loadArtifactContent(artifact);
  if (artifact.path === "codex/diff.patch") {
    renderDiffArtifact(content, artifact);
    return;
  }
  const preview = $("artifact-preview");
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
  const preview = $("artifact-preview");
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
