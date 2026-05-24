const state = {
  selectedRunId: "",
  timer: null,
  i18n: null,
  currentRun: null,
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
  await refreshRun();
}

async function refreshRun() {
  if (!state.selectedRunId) return;
  const run = await fetchJson(`/api/runs/${encodeURIComponent(state.selectedRunId)}`);
  state.currentRun = run;
  renderBusinessRun(view.toBusinessViewModel(run, state.i18n));
}

function renderBusinessRun(vm) {
  $("current-task").textContent = vm.brief || t("app.emptySelection");
  $("brief-label").textContent = vm.runId ? `${t("app.currentTask")} ${vm.runId}` : "";
  $("task-headline").textContent = vm.headline || "";

  const pill = $("status-pill");
  pill.className = `status-pill ${statusClass(view.lookup(state.i18n, `status.${vm.status}.tone`, "muted"))}`;
  pill.textContent = vm.statusLabel;

  renderStages(vm.stages || []);
  renderGates(vm.qualityGates || []);
  renderDeliverables(vm.deliverables || []);
  renderArtifactActions(vm.deliverables || []);
  renderNextActions(vm.nextActions || []);
  renderEngineering(vm);
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
  if (action === "viewArtifacts") {
    const first = (stage.artifacts || []).find((artifact) => artifact.exists);
    if (first) loadArtifact(first);
    return;
  }
  if (action === "viewRisks") {
    $("artifact-preview").textContent = view.toBusinessViewModel(state.currentRun || {}, state.i18n).risks.join("\n");
    return;
  }
  document.querySelector(".engineering-panel").open = true;
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

function renderDeliverables(deliverables) {
  const container = $("deliverables");
  container.textContent = "";
  const visible = deliverables.filter((artifact) => artifact.exists).slice(0, 5);
  if (!visible.length) {
    const empty = document.createElement("p");
    empty.className = "meta";
    empty.textContent = t("actions.noArtifacts");
    container.appendChild(empty);
    return;
  }
  for (const artifact of visible) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "deliverable-card";
    item.addEventListener("click", () => loadArtifact(artifact));
    const title = document.createElement("strong");
    title.textContent = artifact.title;
    const desc = document.createElement("span");
    desc.textContent = artifact.description;
    item.append(title, desc);
    container.appendChild(item);
  }
}

function renderArtifactActions(deliverables) {
  const container = $("artifact-actions");
  container.textContent = "";
  for (const artifact of deliverables) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "artifact-button";
    button.disabled = !artifact.exists;
    button.textContent = artifact.exists ? artifact.title : `${artifact.title} (${t("actions.artifactPending")})`;
    button.addEventListener("click", () => loadArtifact(artifact));
    container.appendChild(button);
  }
}

async function loadArtifact(artifact) {
  if (!state.selectedRunId) return;
  const params = new URLSearchParams({ path: artifact.path, scope: artifact.scope || "run" });
  const data = await fetchJson(`/api/runs/${encodeURIComponent(state.selectedRunId)}/artifact?${params.toString()}`);
  $("artifact-preview").textContent = data.content || "";
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
  $("engineering-logs").textContent = (vm.engineering.logs || []).join("\n");
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
