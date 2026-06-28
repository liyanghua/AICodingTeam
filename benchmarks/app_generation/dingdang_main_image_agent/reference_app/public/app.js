import {
  applyLayerIteration,
  buildImagePrompt,
  buildPlanningCards,
  buildVisualBaseline,
  diagnoseInput,
  generateCreativeSchemes,
} from "/src/shared/dingdang-core.js";

const stages = [
  ["1", "需求诊断", "任务类型 / 平台策略"],
  ["2", "创意方案", "三套方案单选"],
  ["3", "策略落地", "视觉基准 / 规划卡"],
  ["4", "Prompt 出图", "三层 Prompt / 图片生成"],
];

const state = {
  activeStage: 1,
  input: null,
  diagnosis: null,
  schemes: [],
  selectedSchemeId: "A",
  baseline: null,
  planningCards: [],
  prompts: [],
  images: [],
  statuses: [],
  productImageDataUrl: "",
  referenceImageDataUrl: "",
  provider: "openai",
};

const els = {
  form: document.querySelector("#intakeForm"),
  stageRail: document.querySelector("#stageRail"),
  apiStatus: document.querySelector("#apiStatus"),
  diagnosisPanel: document.querySelector("#diagnosisPanel"),
  schemesPanel: document.querySelector("#schemesPanel"),
  baselinePanel: document.querySelector("#baselinePanel"),
  consistencyPanel: document.querySelector("#consistencyPanel"),
  promptGrid: document.querySelector("#promptGrid"),
  eventLog: document.querySelector("#eventLog"),
  queueState: document.querySelector("#queueState"),
  runAllButton: document.querySelector("#runAllButton"),
  resetButton: document.querySelector("#resetButton"),
  buildPromptsButton: document.querySelector("#buildPromptsButton"),
  clearLogsButton: document.querySelector("#clearLogsButton"),
  modelInput: document.querySelector("#modelInput"),
  sizeInput: document.querySelector("#sizeInput"),
  qualityInput: document.querySelector("#qualityInput"),
  formatInput: document.querySelector("#formatInput"),
  iterationImage: document.querySelector("#iterationImage"),
  iterationLayer: document.querySelector("#iterationLayer"),
  iterationText: document.querySelector("#iterationText"),
  applyIterationButton: document.querySelector("#applyIterationButton"),
};

renderStageRail();
loadHealth();
bindEvents();
hydrateDefaults();

function bindEvents() {
  els.form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await runDiagnosis();
  });

  els.buildPromptsButton.addEventListener("click", () => {
    if (!state.baseline) runStrategy();
    buildPrompts();
  });

  els.runAllButton.addEventListener("click", async () => {
    if (!state.prompts.length) buildPrompts();
    await generateAllImages();
  });

  els.resetButton.addEventListener("click", () => {
    localStorage.removeItem("dingdang-draft");
    window.location.reload();
  });

  els.clearLogsButton.addEventListener("click", () => {
    els.eventLog.innerHTML = "";
  });

  els.applyIterationButton.addEventListener("click", () => {
    const index = Number(els.iterationImage.value || 1);
    if (!state.prompts[index - 1]) return log(`第 ${index} 张还没有 Prompt`);
    state.prompts[index - 1] = applyLayerIteration(state.prompts[index - 1], {
      imageIndex: index,
      layer: els.iterationLayer.value,
      instruction: els.iterationText.value,
    });
    renderPromptGrid();
    log(`第 ${index} 张已应用局部迭代`);
  });

  els.promptGrid.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const index = Number(button.dataset.index);
    const action = button.dataset.action;
    if (action === "generate") await generateOneImage(index);
    if (action === "copy") await copyPrompt(index);
    if (action === "download-prompt") downloadPrompt(index);
    if (action === "download-image") downloadImage(index);
  });

  els.promptGrid.addEventListener("input", (event) => {
    const textarea = event.target.closest("textarea[data-index]");
    if (!textarea) return;
    state.prompts[Number(textarea.dataset.index) - 1] = textarea.value;
  });
}

async function hydrateDefaults() {
  const saved = localStorage.getItem("dingdang-draft");
  if (saved) {
    try {
      const values = JSON.parse(saved);
      for (const [key, value] of Object.entries(values)) {
        const field = els.form.elements[key];
        if (field && field.type !== "file") field.value = value;
      }
    } catch {
      localStorage.removeItem("dingdang-draft");
    }
  }
  await runDiagnosis();
}

async function loadHealth() {
  try {
    const response = await fetch("/api/health");
    const health = await response.json();
    state.provider = health.provider || "openai";
    els.apiStatus.textContent = health.hasApiKey
      ? `${providerLabel(health.provider)} 已配置 · ${health.imageModel}`
      : `未检测到 ${health.provider === "openrouter" ? "OPENROUTER_API_KEY" : "OPENAI_API_KEY"}`;
    els.apiStatus.className = `api-status ${health.hasApiKey ? "ready" : "warn"}`;
    els.modelInput.value = health.imageModel || "gpt-image-2";
    els.sizeInput.value = health.imageSize || "1024x1024";
    els.qualityInput.value = health.imageQuality || "medium";
    if (health.imageOutputFormat) els.formatInput.value = health.imageOutputFormat;
  } catch {
    els.apiStatus.textContent = "本地服务未连接";
    els.apiStatus.className = "api-status warn";
  }
}

function providerLabel(provider) {
  return provider === "openrouter" ? "OpenRouter" : "OpenAI";
}

async function runDiagnosis() {
  state.input = readForm();
  state.productImageDataUrl = await readFile(els.form.elements.productImage.files[0]);
  state.referenceImageDataUrl = await readFile(els.form.elements.referenceImage.files[0]);
  state.diagnosis = diagnoseInput(state.input);
  state.schemes = generateCreativeSchemes(state.input, state.diagnosis);
  state.selectedSchemeId = state.schemes[0].id;
  state.activeStage = 2;
  saveDraft();
  renderDiagnosis();
  renderSchemes();
  runStrategy();
  log("Stage 1 诊断完成，已生成三套创意方案");
}

function runStrategy() {
  const scheme = selectedScheme();
  if (!scheme || !state.diagnosis) return;
  state.baseline = buildVisualBaseline(state.input, state.diagnosis, scheme);
  state.planningCards = buildPlanningCards(state.input, state.diagnosis, scheme, state.baseline);
  state.activeStage = 3;
  renderBaseline();
  renderConsistency();
  renderStageRail();
}

function buildPrompts() {
  const scheme = selectedScheme();
  if (!scheme || !state.baseline || !state.planningCards.length) return;
  state.prompts = state.planningCards.map((card, index) =>
    buildImagePrompt(state.input, state.diagnosis, scheme, state.baseline, card, index + 1),
  );
  state.images = Array.from({ length: state.prompts.length }, () => "");
  state.statuses = Array.from({ length: state.prompts.length }, () => "ready");
  state.activeStage = 4;
  renderPromptGrid();
  renderIterationSelect();
  renderStageRail();
  log("Stage 4 Prompt 已生成");
}

async function generateAllImages() {
  if (!state.prompts.length) return;
  for (let index = 1; index <= state.prompts.length; index += 1) {
    await generateOneImage(index);
  }
}

async function generateOneImage(index) {
  if (!state.productImageDataUrl) {
    setStatus(index, "error");
    log("请先上传产品图，再调用真实图片生成 API");
    return;
  }

  const prompt = state.prompts[index - 1];
  if (!prompt) return;
  setStatus(index, "running");
  els.queueState.textContent = `生成第 ${index} 张`;
  log(`节点开始: 第 ${index} 张图片生成`);

  try {
    const response = await fetch("/api/images/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        productImageDataUrl: state.productImageDataUrl,
        referenceImageDataUrl: state.referenceImageDataUrl,
        prompt,
        options: currentImageOptions(),
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "图片生成失败");
    state.images[index - 1] = payload.imageDataUrl;
    setStatus(index, "done");
    log(`节点结束: 第 ${index} 张图片生成完成`);
  } catch (error) {
    setStatus(index, "error");
    log(`节点失败: 第 ${index} 张 · ${error.message}`);
  } finally {
    els.queueState.textContent = "空闲";
  }
}

function renderStageRail() {
  els.stageRail.innerHTML = stages
    .map(
      ([number, title, desc]) => `
      <li class="stage-item ${Number(number) <= state.activeStage ? "active" : ""}">
        <span class="stage-number">${number}</span>
        <div><strong>${title}</strong><span>${desc}</span></div>
      </li>
    `,
    )
    .join("");
}

function renderDiagnosis() {
  const item = state.diagnosis;
  els.diagnosisPanel.className = "diagnosis-panel";
  els.diagnosisPanel.innerHTML = `
    <div class="diagnosis-grid">
      <div class="metric"><span>参考图判断</span><strong>${esc(item.referenceType)}</strong></div>
      <div class="metric"><span>任务类型</span><strong>${esc(item.taskType)}</strong></div>
      <div class="metric"><span>平台策略</span><strong>${esc(item.platformStrategy.firstImageStyle)}</strong></div>
      <div class="metric"><span>设计禁忌</span><strong>${esc(item.platformStrategy.forbidden)}</strong></div>
      <div class="metric"><span>阻断点</span><strong>${esc(item.blockers.join(" / "))}</strong></div>
      <div class="metric"><span>负面词基线</span><strong>${esc(item.platformStrategy.negativeWords.join("、"))}</strong></div>
    </div>
  `;
}

function renderSchemes() {
  els.schemesPanel.className = "schemes-panel";
  els.schemesPanel.innerHTML = state.schemes.map(renderScheme).join("");
  els.schemesPanel.querySelectorAll(".scheme-card").forEach((card) => {
    card.addEventListener("click", () => {
      state.selectedSchemeId = card.dataset.id;
      state.prompts = [];
      state.images = [];
      renderSchemes();
      runStrategy();
      log(`已锁定方案 ${state.selectedSchemeId}，不混搭其他方案`);
    });
  });
}

function renderScheme(scheme) {
  return `
    <article class="scheme-card ${scheme.id === state.selectedSchemeId ? "selected" : ""}" data-id="${scheme.id}">
      <h3><span><span class="badge">${scheme.id}</span> ${esc(scheme.name)}</span></h3>
      <p>${esc(scheme.coreHypothesis)}</p>
      <p><strong>钩子:</strong> ${esc(scheme.hookStrategy)} · <strong>变量:</strong> ${esc(scheme.variableDescription)}</p>
      <table>
        <thead><tr><th>#</th><th>钩子</th><th>主文案</th><th>变量</th></tr></thead>
        <tbody>
          ${scheme.rows
            .map(
              (row) => `
                <tr>
                  <td>${row.index}</td>
                  <td>${esc(row.hookType)}</td>
                  <td>${esc(row.mainCopy)}</td>
                  <td>${esc(row.testVariable)}</td>
                </tr>
              `,
            )
            .join("")}
        </tbody>
      </table>
    </article>
  `;
}

function renderBaseline() {
  const base = state.baseline;
  els.baselinePanel.className = "baseline-panel";
  els.baselinePanel.innerHTML = `
    <div class="baseline-grid">
      <div class="baseline-block"><span>色彩</span><strong>${esc(base.colorSystem.main)} / ${esc(base.colorSystem.secondary)} / ${esc(base.colorSystem.accent)}</strong></div>
      <div class="baseline-block"><span>光影</span><strong>${esc(base.lightSystem.direction)} · ${esc(base.lightSystem.temperature)}</strong></div>
      <div class="baseline-block"><span>字体</span><strong>${esc(base.fontSystem.title)} / ${esc(base.fontSystem.body)}</strong></div>
      <div class="baseline-block"><span>构图</span><strong>${esc(base.compositionSystem.productRatio)} · ${esc(base.compositionSystem.angle)}</strong></div>
      <div class="baseline-block"><span>禁用色</span><strong>${esc(base.colorSystem.forbidden)}</strong></div>
      <div class="baseline-block"><span>负面词</span><strong>${esc(base.negativeWords.join("、"))}</strong></div>
    </div>
  `;
}

function renderConsistency() {
  els.consistencyPanel.className = "consistency-panel";
  els.consistencyPanel.innerHTML = `
    <table class="consistency-table">
      <thead><tr><th>图</th><th>层类型</th><th>色温</th><th>主色调</th><th>产品角度</th></tr></thead>
      <tbody>
        ${state.planningCards
          .map(
            (card) => `
              <tr>
                <td>${card.index}</td>
                <td>${esc(card.layerType)}</td>
                <td>${esc(card.consistency.light)}</td>
                <td>${esc(card.consistency.palette)}</td>
                <td>${esc(card.consistency.angle)}</td>
              </tr>
            `,
          )
          .join("")}
      </tbody>
    </table>
  `;
}

function renderPromptGrid() {
  els.promptGrid.className = "prompt-grid";
  els.promptGrid.innerHTML = state.prompts
    .map((prompt, index) => {
      const number = index + 1;
      const status = state.statuses[index] || "ready";
      const image = state.images[index];
      return `
        <article class="prompt-card">
          <div class="prompt-card-header">
            <h3>第 ${number} 张 · ${esc(state.planningCards[index]?.name || "主图")}</h3>
            <span class="status-pill ${statusClass(status)}">${statusText(status)}</span>
          </div>
          <textarea data-index="${number}">${esc(prompt)}</textarea>
          <div class="image-preview">${image ? `<img src="${image}" alt="第 ${number} 张生成图" />` : "等待生成"}</div>
          <div class="button-row">
            <button class="primary-button" type="button" data-action="generate" data-index="${number}">生成</button>
            <button class="ghost-button" type="button" data-action="copy" data-index="${number}">复制 Prompt</button>
            <button class="ghost-button" type="button" data-action="download-prompt" data-index="${number}">下载 Prompt</button>
            ${
              image
                ? `<button class="ghost-button" type="button" data-action="download-image" data-index="${number}">下载图片</button>`
                : ""
            }
          </div>
        </article>
      `;
    })
    .join("");
}

function renderIterationSelect() {
  els.iterationImage.innerHTML = state.prompts
    .map((_, index) => `<option value="${index + 1}">第 ${index + 1} 张</option>`)
    .join("");
}

function setStatus(index, status) {
  state.statuses[index - 1] = status;
  renderPromptGrid();
}

function selectedScheme() {
  return state.schemes.find((scheme) => scheme.id === state.selectedSchemeId);
}

function readForm() {
  const data = new FormData(els.form);
  return {
    productName: data.get("productName")?.trim(),
    productDescription: data.get("productDescription")?.trim(),
    platform: data.get("platform"),
    category: data.get("category")?.trim(),
    priceBand: data.get("priceBand")?.trim(),
    targetMode: data.get("targetMode"),
    referenceKind: data.get("referenceKind"),
    sellingPoints: data.get("sellingPoints")?.trim(),
    audience: data.get("audience")?.trim(),
  };
}

function saveDraft() {
  localStorage.setItem("dingdang-draft", JSON.stringify(state.input));
}

function readFile(file) {
  return new Promise((resolve) => {
    if (!file) return resolve("");
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => resolve("");
    reader.readAsDataURL(file);
  });
}

function currentImageOptions() {
  return {
    model: els.modelInput.value.trim() || "gpt-image-2",
    size: els.sizeInput.value,
    quality: els.qualityInput.value,
    outputFormat: els.formatInput.value,
  };
}

async function copyPrompt(index) {
  const prompt = state.prompts[index - 1];
  await navigator.clipboard.writeText(prompt);
  log(`第 ${index} 张 Prompt 已复制`);
}

function downloadPrompt(index) {
  downloadDataUrl(
    `data:text/plain;charset=utf-8,${encodeURIComponent(state.prompts[index - 1])}`,
    `dingdang-prompt-${index}.txt`,
  );
}

function downloadImage(index) {
  downloadDataUrl(state.images[index - 1], `dingdang-image-${index}.${els.formatInput.value}`);
}

function downloadDataUrl(dataUrl, fileName) {
  const link = document.createElement("a");
  link.href = dataUrl;
  link.download = fileName;
  document.body.append(link);
  link.click();
  link.remove();
}

function statusText(status) {
  return {
    ready: "待生成",
    running: "生成中",
    done: "已完成",
    error: "失败",
  }[status];
}

function statusClass(status) {
  return status === "running" || status === "done" || status === "error" ? status : "";
}

function log(message) {
  const row = document.createElement("div");
  row.className = "log-row";
  const now = new Date();
  row.innerHTML = `<time>${now.toLocaleTimeString("zh-CN", { hour12: false })}</time><span>${esc(message)}</span>`;
  els.eventLog.prepend(row);
}

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
