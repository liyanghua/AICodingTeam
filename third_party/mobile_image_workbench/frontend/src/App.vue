<template>
  <main class="shell" @paste="handlePaste">
    <header class="topbar">
      <div>
        <h1>移动端图片采集工作台</h1>
        <p>用已登录的小红书 App 做低频、可观察的买家秀图片采集。</p>
      </div>
      <button class="ghost-button" type="button" @click="checkDoctor">
        <Activity :size="18" />
        检查环境
      </button>
    </header>

    <section class="workspace">
      <div class="composer">
        <div class="segmented" role="tablist" aria-label="输入模式">
          <button
            v-for="option in modeOptions"
            :key="option.value"
            :class="{ active: mode === option.value }"
            type="button"
            @click="setMode(option.value)"
          >
            <component :is="option.icon" :size="17" />
            {{ option.label }}
          </button>
        </div>

        <div
          class="dropzone"
          :class="{ dragging: isDragging }"
          @dragover.prevent="isDragging = true"
          @dragleave="isDragging = false"
          @drop.prevent="handleDrop"
        >
          <UploadCloud :size="28" />
          <strong>{{ uploadTitle }}</strong>
          <span>{{ uploadHint }}</span>
          <input
            ref="fileInput"
            :accept="acceptedTypes"
            :multiple="mode !== 'single_image'"
            type="file"
            @change="handleFilePick"
          />
          <input
            v-if="mode === 'config_file'"
            ref="folderInput"
            type="file"
            webkitdirectory
            multiple
            @change="handleFolderPick"
          />
          <button class="secondary-button" type="button" @click="openPrimaryPicker">
            <Plus :size="17" />
            {{ primaryPickerLabel }}
          </button>
          <button
            v-if="mode === 'config_file'"
            class="text-button"
            type="button"
            @click="fileInput?.click()"
          >
            改用 Excel + 图片选择
          </button>
        </div>

        <div v-if="imageFiles.length" class="preview-strip">
          <div v-for="file in imageFiles" :key="file.id" class="preview-tile">
            <img :src="file.previewUrl" :alt="file.name" />
            <span>{{ file.name }}</span>
            <button type="button" title="移除" @click="removeImage(file.id)">
              <X :size="15" />
            </button>
          </div>
        </div>

        <div v-if="configFile" class="file-row">
          <FileSpreadsheet :size="18" />
          <span>{{ configFile.name }}</span>
          <button type="button" @click="clearConfigSelection">移除</button>
        </div>

        <div v-if="configFolderSummary" class="validation-panel">
          <div>
            <strong>{{ configFolderSummary.title }}</strong>
            <span>{{ configFolderSummary.detail }}</span>
          </div>
          <span :class="['validation-pill', configFolderSummary.level]">
            {{ configFolderSummary.label }}
          </span>
        </div>

        <div v-if="configSidecarFiles.length" class="preview-strip">
          <div v-for="file in configSidecarFiles" :key="file.id" class="preview-tile">
            <img :src="file.previewUrl" :alt="file.name" />
            <span>{{ file.name }}</span>
            <button type="button" title="移除" @click="removeConfigSidecar(file.id)">
              <X :size="15" />
            </button>
          </div>
        </div>

        <div class="summary-band">
          <Sparkles :size="19" />
          <div>
            <strong>{{ taskSummary }}</strong>
            <span>{{ defaultSummary }}</span>
          </div>
        </div>

        <details class="advanced">
          <summary>
            <Settings2 :size="18" />
            高级配置
          </summary>
          <div class="settings-grid">
            <label>
              图搜采集张数
              <input v-model.number="settings.imageTopN" min="1" type="number" />
            </label>
            <label>
              关键词数量
              <input v-model.number="settings.keywordTopN" min="0" type="number" />
            </label>
            <label>
              每关键词采集张数
              <input v-model.number="settings.keywordResultTopN" min="0" type="number" />
            </label>
            <label>
              翻页上限
              <input v-model.number="settings.maxResultScrolls" min="1" type="number" />
            </label>
            <label>
              操作间隔秒数
              <input v-model.number="settings.throttleSeconds" min="0" step="0.5" type="number" />
            </label>
            <label>
              主体识别等待秒数
              <input v-model.number="settings.subjectRecognitionWaitSeconds" min="0" step="0.5" type="number" />
            </label>
            <label>
              设备序列号
              <input v-model="settings.deviceSerial" placeholder="默认自动连接" type="text" />
            </label>
            <label class="checkbox-field">
              <span>品类过滤</span>
              <span class="inline-checkbox">
                <input v-model="settings.categoryFilterEnabled" type="checkbox" />
                启用品类过滤
              </span>
            </label>
            <label>
              目标品类
              <input
                v-model="settings.targetCategory"
                :disabled="!settings.categoryFilterEnabled"
                placeholder="例如：桌垫"
                type="text"
              />
            </label>
            <label class="wide-field">
              品类关键词
              <input
                v-model="settings.targetCategoryKeywords"
                :disabled="!settings.categoryFilterEnabled"
                placeholder="桌垫, 餐桌垫, 餐垫, 桌垫桌布"
                type="text"
              />
            </label>
          </div>
          <label class="checkbox-row">
            <input v-model="settings.dryRun" type="checkbox" />
            只做 dry-run 验证产物链路
          </label>
        </details>

        <div class="actions">
          <button class="primary-button" :disabled="!canStart || isSubmitting" type="button" @click="startJob">
            <Play :size="18" />
            {{ isSubmitting ? '正在创建任务' : '开始采集' }}
          </button>
          <span v-if="doctorMessage" class="inline-status">{{ doctorMessage }}</span>
        </div>
      </div>

      <aside class="observer">
        <div class="observer-header">
          <div>
            <span class="eyebrow">采集过程</span>
            <h2>{{ jobTitle }}</h2>
          </div>
          <span class="status-pill" :class="jobStatus">{{ statusLabel }}</span>
        </div>

        <ol ref="timelineRef" class="timeline" aria-live="polite" @scroll="handleTimelineScroll">
          <li v-for="event in events" :key="event.id" :class="event.level">
            <span class="dot"></span>
            <div>
              <strong>{{ event.message }}</strong>
              <small v-if="event.query">关键词：{{ event.query }}</small>
            </div>
          </li>
          <li v-if="!events.length" class="muted">
            <span class="dot"></span>
            <div>
              <strong>等待任务开始</strong>
              <small>创建任务后，这里会实时显示手机端操作进度。</small>
            </div>
          </li>
        </ol>
        <button
          v-if="hasUnreadTimelineEvents"
          class="timeline-jump-button"
          type="button"
          @click="scrollTimelineToLatest"
        >
          有新进展，查看最新
        </button>

        <div v-if="jobId" class="download-box">
          <Download :size="18" />
          <div>
            <strong>结果下载</strong>
            <span>任务完成或部分完成后可下载 HTML、CSV 和图片包。</span>
          </div>
          <div class="download-links">
            <a :href="`/api/jobs/${jobId}/results.html`" target="_blank">HTML</a>
            <a :href="`/api/jobs/${jobId}/results.csv`">CSV</a>
            <a :href="`/api/jobs/${jobId}/results_images.zip`">ZIP</a>
          </div>
        </div>
      </aside>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, nextTick, reactive, ref } from 'vue';
import {
  Activity,
  Download,
  FileImage,
  FileSpreadsheet,
  Images,
  Play,
  Plus,
  Settings2,
  Sparkles,
  UploadCloud,
  X,
} from 'lucide-vue-next';

type JobMode = 'single_image' | 'batch_images' | 'config_file';

type LocalFile = {
  id: string;
  name: string;
  file: File;
  previewUrl: string;
  relativePath?: string;
};

type BusinessEvent = {
  id: string;
  level: 'info' | 'warning' | 'needs_attention';
  message: string;
  query?: string;
};

type RemoteBusinessEvent = {
  eventKey?: string;
  source?: string;
  name?: string;
  level?: BusinessEvent['level'];
  message?: string;
  query?: string;
  itemId?: string;
  stage?: string;
  rank?: number;
  raw?: Record<string, unknown>;
};

const modeOptions = [
  { value: 'single_image' as const, label: '单图片', icon: FileImage },
  { value: 'batch_images' as const, label: '批量图片', icon: Images },
  { value: 'config_file' as const, label: '配置文件', icon: FileSpreadsheet },
];

const mode = ref<JobMode>('single_image');
const imageFiles = ref<LocalFile[]>([]);
const configFile = ref<File | null>(null);
const configSidecarFiles = ref<LocalFile[]>([]);
const configProjectFiles = ref<LocalFile[]>([]);
const fileInput = ref<HTMLInputElement | null>(null);
const folderInput = ref<HTMLInputElement | null>(null);
const isDragging = ref(false);
const isSubmitting = ref(false);
const doctorMessage = ref('');
const jobId = ref('');
const jobStatus = ref('idle');
const events = ref<BusinessEvent[]>([]);
const eventCounter = ref(0);
const seenEventKeys = ref<Set<string>>(new Set());
const timelineRef = ref<HTMLElement | null>(null);
const autoFollowTimeline = ref(true);
const hasUnreadTimelineEvents = ref(false);
const TIMELINE_BOTTOM_THRESHOLD = 32;

const settings = reactive({
  imageTopN: 10,
  keywordTopN: 0,
  keywordResultTopN: 0,
  maxResultScrolls: 10,
  throttleSeconds: 3,
  subjectRecognitionWaitSeconds: 5,
  deviceSerial: '',
  categoryFilterEnabled: false,
  targetCategory: '桌垫',
  targetCategoryKeywords: '桌垫, 餐桌垫, 餐垫, 桌垫桌布',
  dryRun: false,
});

const acceptedTypes = computed(() =>
  mode.value === 'config_file'
    ? '.xlsx,.xlsm,image/png,image/jpeg,image/webp'
    : 'image/png,image/jpeg,image/webp',
);

const uploadTitle = computed(() =>
  mode.value === 'config_file' ? '选择采集项目文件夹' : '上传或粘贴参考图片',
);

const uploadHint = computed(() =>
  mode.value === 'config_file'
    ? '选择包含 Excel 和同目录图片的文件夹；系统会自动匹配 image_path + keywords'
    : '支持 PNG、JPG、WebP；也可以直接复制图片后粘贴到页面',
);

const primaryPickerLabel = computed(() =>
  mode.value === 'config_file' ? '选择项目文件夹' : '选择文件',
);

const taskSummary = computed(() => {
  if (mode.value === 'config_file') {
    if (configFile.value && configSidecarFiles.value.length) {
      return `将使用 ${configFile.value.name} 和 ${configSidecarFiles.value.length} 张原图创建采集任务`;
    }
    return configFile.value ? `将使用 ${configFile.value.name} 创建采集任务` : '等待选择项目文件夹';
  }
  const count = imageFiles.value.length;
  return count ? `将采集 ${count} 张原图` : '等待上传参考图片';
});

const defaultSummary = computed(() => {
  if (mode.value === 'config_file') {
    return `默认图搜 ${settings.imageTopN} 张，取 TOP ${settings.keywordTopN} 关键词，每个关键词 ${settings.keywordResultTopN} 张。`;
  }
  return `默认每张原图采集 ${settings.imageTopN} 张图搜结果。`;
});

const canStart = computed(() =>
  mode.value === 'config_file' ? Boolean(configFile.value) : imageFiles.value.length > 0,
);

const jobTitle = computed(() => (jobId.value ? `任务 ${jobId.value}` : '暂无运行任务'));

const configFolderSummary = computed(() => {
  if (mode.value !== 'config_file') {
    return null;
  }
  if (!configFile.value && configProjectFiles.value.length) {
    const workbookCount = configProjectFiles.value.filter((entry) =>
      /\.(xlsx|xlsm)$/i.test(entry.name) && !isOfficeTempFile(entry.name),
    ).length;
    return {
      title: '项目文件夹需要 1 个配置文件',
      detail: workbookCount > 1 ? `当前发现 ${workbookCount} 个 Excel，请保留一个业务配置文件。` : '没有发现 .xlsx/.xlsm 配置文件。',
      label: '需调整',
      level: 'warning',
    };
  }
  if (!configFile.value) {
    return null;
  }
  const projectName = inferProjectName();
  const imageCount = configSidecarFiles.value.length;
  if (!imageCount) {
    return {
      title: projectName ? `已选择项目：${projectName}` : '已选择配置文件',
      detail: '暂未发现同目录图片；如果 Excel 第一列使用相对图片名，请补充选择图片。',
      label: '需补图片',
      level: 'warning',
    };
  }
  return {
    title: projectName ? `已选择项目：${projectName}` : '已选择配置文件和图片',
    detail: `发现 1 个配置文件，${imageCount} 张图片。启动后会按 Excel 第一列自动匹配同目录图片。`,
    label: '可开始',
    level: 'ok',
  };
});

const statusLabel = computed(() => {
  const labels: Record<string, string> = {
    idle: '未开始',
    queued: '排队中',
    running: '运行中',
    needs_attention: '需人工处理',
    partial: '部分完成',
    completed: '完成',
    failed: '失败',
  };
  return labels[jobStatus.value] || jobStatus.value;
});

function setMode(nextMode: JobMode) {
  mode.value = nextMode;
  imageFiles.value = [];
  configFile.value = null;
  configSidecarFiles.value = [];
  configProjectFiles.value = [];
  if (nextMode === 'config_file') {
    settings.imageTopN = 10;
    settings.keywordTopN = 4;
    settings.keywordResultTopN = 5;
  } else {
    settings.imageTopN = 10;
    settings.keywordTopN = 0;
    settings.keywordResultTopN = 0;
  }
}

function handleDrop(event: DragEvent) {
  isDragging.value = false;
  const files = Array.from(event.dataTransfer?.files || []);
  addFiles(files);
}

function handleFilePick(event: Event) {
  const input = event.target as HTMLInputElement;
  addFiles(Array.from(input.files || []));
  input.value = '';
}

function handleFolderPick(event: Event) {
  const input = event.target as HTMLInputElement;
  addProjectFolder(Array.from(input.files || []));
  input.value = '';
}

function handlePaste(event: ClipboardEvent) {
  const files = Array.from(event.clipboardData?.files || []);
  if (files.length) {
    addFiles(files);
  }
}

function addFiles(files: File[]) {
  if (mode.value === 'config_file') {
    configProjectFiles.value = [];
    const workbook = files.find((file) => /\.(xlsx|xlsm)$/i.test(file.name) && !isOfficeTempFile(file.name));
    if (workbook) {
      configFile.value = workbook;
    }
    const sidecars = files
      .filter((file) => file.type.startsWith('image/'))
      .map((file) => ({
        id: crypto.randomUUID(),
        name: file.name,
        file,
        previewUrl: URL.createObjectURL(file),
      }));
    configSidecarFiles.value = configSidecarFiles.value.concat(sidecars);
    return;
  }
  const images = files.filter((file) => file.type.startsWith('image/'));
  const next = images.map((file) => ({
    id: crypto.randomUUID(),
    name: file.name,
    file,
    previewUrl: URL.createObjectURL(file),
  }));
  imageFiles.value = mode.value === 'single_image' ? next.slice(0, 1) : imageFiles.value.concat(next);
}

function addProjectFolder(files: File[]) {
  const workbook = findProjectWorkbook(files);
  configFile.value = workbook || null;
  configProjectFiles.value = files.map((file) => ({
    id: crypto.randomUUID(),
    name: file.name,
    file,
    previewUrl: file.type.startsWith('image/') ? URL.createObjectURL(file) : '',
    relativePath: file.webkitRelativePath || file.name,
  }));
  configSidecarFiles.value = configProjectFiles.value.filter((entry) => entry.file.type.startsWith('image/'));
}

function findProjectWorkbook(files: File[]) {
  const candidates = files.filter((file) => /\.(xlsx|xlsm)$/i.test(file.name) && !isOfficeTempFile(file.name));
  return candidates.length === 1 ? candidates[0] : null;
}

function isOfficeTempFile(name: string) {
  return name.startsWith('.~') || name.startsWith('~$');
}

function openPrimaryPicker() {
  if (mode.value === 'config_file') {
    folderInput.value?.click();
    return;
  }
  fileInput.value?.click();
}

function removeImage(id: string) {
  imageFiles.value = imageFiles.value.filter((file) => file.id !== id);
}

function removeConfigSidecar(id: string) {
  configSidecarFiles.value = configSidecarFiles.value.filter((file) => file.id !== id);
  configProjectFiles.value = configProjectFiles.value.filter((file) => file.id !== id);
}

function clearConfigSelection() {
  configFile.value = null;
  configSidecarFiles.value = [];
  configProjectFiles.value = [];
}

function inferProjectName() {
  const projectEntry = configProjectFiles.value.find((entry) => entry.file === configFile.value);
  const relativePath = projectEntry?.relativePath || configFile.value?.webkitRelativePath || '';
  return relativePath.split('/').filter(Boolean).slice(0, -1).pop() || '';
}

async function checkDoctor() {
  const response = await fetch('/api/doctor');
  const payload = await response.json();
  doctorMessage.value = payload.message || payload.status;
}

async function startJob() {
  isSubmitting.value = true;
  events.value = [];
  eventCounter.value = 0;
  seenEventKeys.value = new Set();
  autoFollowTimeline.value = true;
  hasUnreadTimelineEvents.value = false;
  try {
    const payload = await buildPayload();
    const response = await fetch('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      throw new Error((await response.json()).error || '任务创建失败');
    }
    const job = await response.json();
    jobId.value = job.jobId;
    jobStatus.value = job.status;
    subscribeEvents(job.jobId);
    refreshEvents(job.jobId);
    pollJob(job.jobId);
  } catch (error) {
    events.value.push({
      id: `local-${Date.now()}`,
      level: 'warning',
      message: error instanceof Error ? error.message : '任务创建失败',
    });
    scrollTimelineToLatestIfNeeded();
  } finally {
    isSubmitting.value = false;
  }
}

async function buildPayload() {
  const base = {
    mode: mode.value,
    settings: {
      mode: mode.value,
      imageTopN: settings.imageTopN,
      keywordTopN: settings.keywordTopN,
      keywordResultTopN: settings.keywordResultTopN,
      maxResultScrolls: settings.maxResultScrolls,
      throttleSeconds: settings.throttleSeconds,
      subjectRecognitionWaitSeconds: settings.subjectRecognitionWaitSeconds,
      deviceSerial: settings.deviceSerial || undefined,
      categoryFilterEnabled: settings.categoryFilterEnabled,
      targetCategory: settings.targetCategory,
      targetCategoryKeywords: settings.targetCategoryKeywords,
      dryRun: settings.dryRun,
    },
  };
  if (mode.value === 'config_file') {
    const projectFiles = configProjectFiles.value.length
      ? configProjectFiles.value.map((entry) => filePayload(entry.file, entry.relativePath))
      : [];
    return {
      ...base,
      ...(projectFiles.length
        ? { projectFiles: await Promise.all(projectFiles) }
        : {
            configFile: await filePayload(configFile.value as File),
            configImages: await Promise.all(configSidecarFiles.value.map((entry) => filePayload(entry.file))),
          }),
    };
  }
  return {
    ...base,
    images: await Promise.all(imageFiles.value.map((entry) => filePayload(entry.file))),
  };
}

async function filePayload(file: File, relativePath?: string) {
  const content = await readFileAsDataUrl(file);
  return {
    filename: file.name,
    relativePath: relativePath || file.webkitRelativePath || file.name,
    contentBase64: content,
  };
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function subscribeEvents(id: string) {
  const stream = new EventSource(`/api/jobs/${id}/events`);
  stream.onmessage = (message) => {
    const event = JSON.parse(message.data);
    appendBusinessEvent(event);
  };
  stream.onerror = () => stream.close();
}

function appendBusinessEvent(event: RemoteBusinessEvent) {
  const key = remoteEventKey(event);
  if (seenEventKeys.value.has(key)) {
    return;
  }
  seenEventKeys.value.add(key);
  eventCounter.value += 1;
  events.value.push({
    id: `${eventCounter.value}`,
    level: normalizeEventLevel(event.level),
    message: event.message || '正在执行采集步骤',
    query: event.query,
  });
  if (event.level === 'needs_attention') {
    jobStatus.value = 'needs_attention';
  }
  scrollTimelineToLatestIfNeeded();
}

function remoteEventKey(event: RemoteBusinessEvent) {
  if (event.eventKey) {
    return event.eventKey;
  }
  const raw = event.raw || {};
  return [
    event.source || raw.source || 'collector',
    event.name || raw.name || raw.event || 'event',
    raw.step || '',
    event.itemId || raw.item_id || '',
    event.stage || raw.stage || '',
    event.rank || raw.rank || '',
    event.query || raw.query || '',
    event.message || raw.message || '',
  ].join('|');
}

function normalizeEventLevel(level?: string): BusinessEvent['level'] {
  if (level === 'warning' || level === 'needs_attention') {
    return level;
  }
  return 'info';
}

async function refreshEvents(id: string) {
  const response = await fetch(`/api/jobs/${id}/events.json`);
  if (!response.ok) {
    return;
  }
  const payload = await response.json();
  for (const event of payload.events || []) {
    appendBusinessEvent(event);
  }
}

function handleTimelineScroll() {
  const timeline = timelineRef.value;
  if (!timeline) {
    return;
  }
  const distanceFromBottom = timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight;
  const isAtBottom = distanceFromBottom <= TIMELINE_BOTTOM_THRESHOLD;
  autoFollowTimeline.value = isAtBottom;
  if (isAtBottom) {
    hasUnreadTimelineEvents.value = false;
  }
}

function scrollTimelineToLatestIfNeeded() {
  if (!autoFollowTimeline.value) {
    hasUnreadTimelineEvents.value = true;
    return;
  }
  scrollTimelineToLatest();
}

function scrollTimelineToLatest() {
  nextTick(() => {
    const timeline = timelineRef.value;
    if (!timeline) {
      return;
    }
    timeline.scrollTop = timeline.scrollHeight;
    autoFollowTimeline.value = true;
    hasUnreadTimelineEvents.value = false;
  });
}

async function pollJob(id: string) {
  while (true) {
    await refreshEvents(id);
    const response = await fetch(`/api/jobs/${id}`);
    const payload = await response.json();
    jobStatus.value = payload.status;
    if (!['queued', 'running'].includes(payload.status)) {
      await refreshEvents(id);
      break;
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
}
</script>
