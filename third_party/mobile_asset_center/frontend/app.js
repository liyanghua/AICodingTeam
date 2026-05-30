const state = {
  category: '',
  scene: '',
  assetType: '',
  cursor: '',
  loading: false,
};

const categoryList = document.querySelector('#categoryList');
const primarySceneTabs = document.querySelector('#primarySceneTabs');
const detailSceneTabs = document.querySelector('#detailSceneTabs');
const assetFeed = document.querySelector('#assetFeed');
const loadMoreButton = document.querySelector('#loadMoreButton');
const resultSummary = document.querySelector('#resultSummary');
const activeCategoryLabel = document.querySelector('#activeCategoryLabel');
const activeFilterSummary = document.querySelector('#activeFilterSummary');

async function init() {
  bindEvents();
  await loadCategories();
  await loadScenes();
  await loadAssets({ reset: true });
}

function bindEvents() {
  loadMoreButton.addEventListener('click', () => loadAssets({ reset: false }));
  document.querySelectorAll('[data-asset-type]').forEach((button) => {
    button.addEventListener('click', () => {
      document.querySelectorAll('[data-asset-type]').forEach((item) => item.classList.remove('active'));
      button.classList.add('active');
      state.assetType = button.dataset.assetType || '';
      loadAssets({ reset: true });
    });
  });
}

async function loadCategories() {
  const payload = await fetchJson('/api/categories');
  const categories = payload.categories || [];
  categoryList.innerHTML = '';
  categoryList.appendChild(categoryButton({ category: '', count: 0 }, '全部品类'));
  categories.forEach((item) => categoryList.appendChild(categoryButton(item, item.category)));
}

function categoryButton(item, label) {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = item.count ? `${label} ${item.count}` : label;
  button.className = state.category === item.category ? 'active' : '';
  button.addEventListener('click', async () => {
    state.category = item.category || '';
    state.scene = '';
    activeCategoryLabel.textContent = state.category || '全部品类';
    await loadCategories();
    await loadScenes();
    await loadAssets({ reset: true });
  });
  return button;
}

async function loadScenes() {
  const params = new URLSearchParams();
  if (state.category) params.set('category', state.category);
  const payload = await fetchJson(`/api/scenes?${params.toString()}`);
  const scenes = payload.scenes || [];
  const primaryScenes = scenes.filter((item) => item.kind !== 'detail');
  const detailScenes = scenes.filter((item) => item.kind === 'detail');

  primarySceneTabs.innerHTML = '';
  detailSceneTabs.innerHTML = '';
  primarySceneTabs.appendChild(sceneButton({ scene: '', count: 0, kind: 'primary' }));
  appendSceneGroup(primarySceneTabs, primaryScenes, '暂无主标签');
  appendSceneGroup(detailSceneTabs, detailScenes, '暂无细分标签');
}

function appendSceneGroup(container, scenes, emptyLabel) {
  if (!scenes.length) {
    const empty = document.createElement('span');
    empty.className = 'scene-empty';
    empty.textContent = emptyLabel;
    container.appendChild(empty);
    return;
  }
  scenes.forEach((item) => container.appendChild(sceneButton(item)));
}

function sceneButton(item) {
  const scene = item.scene || '';
  const button = document.createElement('button');
  button.type = 'button';
  const kindClass = item.kind === 'detail' ? 'scene-kind-detail' : 'scene-kind-primary';
  const label = scene || '全部场景';
  button.className = [
    'scene-chip',
    kindClass,
    state.scene === scene ? 'active' : '',
  ].filter(Boolean).join(' ');
  button.innerHTML = `
    <span class="scene-name">${escapeHtml(label)}</span>
    <span class="scene-count">${Number(item.count || 0)}</span>
  `;
  button.addEventListener('click', () => {
    state.scene = scene;
    loadScenes();
    loadAssets({ reset: true });
  });
  return button;
}

async function loadAssets({ reset }) {
  if (state.loading) return;
  state.loading = true;
  try {
    if (reset) {
      state.cursor = '';
      assetFeed.innerHTML = '';
    }
    const params = new URLSearchParams();
    if (state.category) params.set('category', state.category);
    if (state.scene) params.set('scene', state.scene);
    if (state.assetType) params.set('assetType', state.assetType);
    if (state.cursor) params.set('cursor', state.cursor);
    const payload = await fetchJson(`/api/assets?${params.toString()}`);
    const assets = payload.assets || [];
    assets.forEach((asset) => assetFeed.appendChild(assetCard(asset)));
    state.cursor = payload.nextCursor || '';
    loadMoreButton.hidden = !state.cursor;
    resultSummary.textContent = assets.length
      ? `已加载 ${assetFeed.children.length} 张素材`
      : assetFeed.children.length
        ? `已加载 ${assetFeed.children.length} 张素材`
        : '暂无匹配素材';
    activeFilterSummary.textContent = filterSummary();
  } catch (error) {
    resultSummary.textContent = '素材加载失败，请稍后重试。';
  } finally {
    state.loading = false;
  }
}

function assetCard(asset) {
  const article = document.createElement('article');
  article.className = 'asset-card';
  const label = asset.assetType === 'original' ? '原始素材' : '抓取素材';
  const typeClass = asset.assetType === 'original' ? 'asset-type asset-type-original' : 'asset-type';
  article.innerHTML = `
    <a href="${asset.imageUrl}" target="_blank"><img src="${asset.imageUrl}" alt="${asset.query || asset.category || label}" loading="lazy" /></a>
    <div class="asset-body">
      <span class="${typeClass}">${label}</span>
      <strong>${asset.category || '未分类'} · ${asset.scene || '未标注场景'}</strong>
      <small>${asset.stage || '来源未知'} · Rank ${asset.rank || '-'}</small>
      <div class="tag-row">${(asset.sceneTags || []).map((tag) => `<span>${tag}</span>`).join('')}</div>
      <a href="${asset.downloadUrl}" download>下载</a>
    </div>
  `;
  return article;
}

function filterSummary() {
  const parts = [];
  parts.push(state.category || '全部品类');
  if (state.scene) parts.push(state.scene);
  if (state.assetType) parts.push(state.assetType === 'original' ? '原始素材' : '抓取素材');
  return `当前筛选：${parts.join(' / ')}`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[char]);
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(`请求失败：${response.status}`);
  }
  return response.json();
}

init();
