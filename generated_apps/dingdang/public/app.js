const STATE_KEY = 'dingdang-state';

// Load state from localStorage
let state = [];
try {
  const stored = localStorage.getItem(STATE_KEY);
  if (stored) {
    state = JSON.parse(stored);
  }
} catch (e) {
  console.error('Failed to load state:', e);
}

// Save state to localStorage
function saveState() {
  try {
    localStorage.setItem(STATE_KEY, JSON.stringify(state));
  } catch (e) {
    console.error('Failed to save state:', e);
  }
}

// Render functions
function renderEmpty() {
  return `
    <div class="empty-state">
      <h2>空状态</h2>
      <p>暂无数据</p>
    </div>
  `;
}

function renderLoading() {
  return `
    <div class="loading">
      <p>加载中...</p>
    </div>
  `;
}

function renderError(message) {
  return `
    <div class="error">
      <strong>错误：</strong> ${message}
    </div>
  `;
}

function renderSuccess(data) {
  return `
    <div class="container">
      <h1>叮当主图生成 Agent</h1>
      <div class="card">
        <p>应用已加载</p>
        <p>数据项数：${Array.isArray(data) ? data.length : 0}</p>
      </div>
    </div>
  `;
}

// Main render
function render() {
  const app = document.getElementById('app');
  if (!app) return;
  
  if (Array.isArray(state) && state.length === 0) {
    app.innerHTML = renderEmpty();
  } else {
    app.innerHTML = renderSuccess(state);
  }
}

// Expose for debugging
window.app = {
  state,
  render,
  saveState,
};

// Initial render
render();
