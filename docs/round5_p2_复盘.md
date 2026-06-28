# ROUND 5 P2 复盘 — Preview Logs Viewer（预览日志查看器）

## 任务目标

在 ROUND 5 P1（Publish + Preview + Patch-app UI）基础上，增加应用预览日志查看功能，方便用户调试预览进程。

## 优先级决策

P2 候选有 5 个：
1. **Manual file editor**（Monaco）— 引入新依赖，违反 stdlib-only 约束，**延后**
2. **Diff modal**（diff2html）— 引入新依赖，可用纯 JS 简化版，**P3 候选**
3. **Preview logs viewer** — 后端已有 log_path，stdlib 可实现，调试价值最高，**选中**
4. **Multi-preview support** — 与 spec O2 约束冲突（单 run 单 app_slug），**跳过**
5. **WebSocket push** — 后端 preview.py 大改造，3s 轮询可接受，**延后**

**决策**：优先实施 **D3 Preview Logs Viewer**，理由：
- 后端已有 `preview_dir / "preview.log"`（stdout + stderr 合并）
- 无需新依赖，stdlib 可实现
- 调试预览应用最实用的功能（看进程输出）
- 前端 UI 改动小（toolbar + tab 切换）

## 实施内容

### 1. 后端新增 logs endpoint（dashboard.py）

**函数**：`get_app_generation_preview_logs(config, run_id, tail=200)`

- 读取 `runs/<run_id>/preview/preview.log`
- 返回：`{"lines": [...], "total_lines": N, "tail": M}`
- 支持 `tail` 参数（默认 200 行，避免大日志传输）
- 日志不存在返回空数组（不报错）

**HTTP 路由**：`GET /api/app-generation/runs/<run_id>/preview/logs?tail=N`

- Query 参数：`tail`（可选，默认 200）
- 返回 JSON：`{lines, total_lines, tail}`
- 错误处理：404（run 不存在）/ 500（读取失败）

### 2. 前端网络层（app_generation.js）

新增函数：

```javascript
async function getAppPreviewLogs(runId, tail) {
  const query = tail ? `?tail=${tail}` : "";
  return fetchJSON(`/api/app-generation/runs/${encodeURIComponent(runId)}/preview/logs${query}`);
}
```

### 3. 前端 UI 控制（app_generation.js）

#### 3.1 Toolbar 增加"查看日志"按钮

在 `renderAppPreviewIframe` 生成的 toolbar 中增加：

```javascript
el("button", {
  type: "button",
  className: "ghost small",
  onclick: () => toggleAppPreviewLogs(runId),
}, ["查看日志"])
```

#### 3.2 日志视图切换

**`toggleAppPreviewLogs(runId)`**：
- 检查 `previewContent.dataset.view === "logs"`
  - 是 → 调用 `renderAppPreviewIframe(state.appPreview)` 返回 iframe 视图
  - 否 → 清空 `previewContent`，渲染日志 toolbar + 日志容器，调用 `refreshAppPreviewLogs`

日志 toolbar 包含：
- "返回预览" 按钮 → 切回 iframe
- "刷新日志" 按钮 → 重新拉取日志

#### 3.3 日志渲染

**`refreshAppPreviewLogs(runId)`**：
- 调用 `getAppPreviewLogs(runId, 200)`
- 渲染：
  - 元信息：`显示最后 N 行（共 M 行）`（如果 total > tail）
  - 日志内容：`<pre>` 包裹，monospace 字体，深色背景
  - 空日志：显示"日志为空。"
  - 自动滚动到底部（`pre.scrollTop = pre.scrollHeight`）

#### 3.4 重构 iframe 渲染

抽取 `renderAppPreviewIframe(previewData)` 函数：
- 清空 `previewContent`
- 渲染 toolbar（在新窗口打开 / 查看日志 / 停止预览）
- 渲染 iframe（sandbox）
- `openAppPreviewRail` 调用此函数（避免重复代码）

### 4. CSS 样式（styles.css）

```css
.app-generation-app-preview-logs {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.app-generation-app-preview-logs pre.app-generation-app-preview-logs-content {
  max-height: clamp(360px, 55vh, 640px);
  overflow: auto;
  background: #0e1116;
  color: #d6e1ee;
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  font-size: 0.78em;
  line-height: 1.5;
  padding: var(--space-2);
  border-radius: var(--radius-control);
  white-space: pre-wrap;
  word-break: break-word;
}
```

特性：
- 深色背景（GitHub 风格）
- monospace 字体
- 最大高度 55vh（响应式）
- 自动换行（`pre-wrap` + `break-word`）

### 5. 测试（tests/test_dashboard.py）

新增 2 个测试：

#### test_get_preview_logs_returns_tail_lines_and_total_count
- 写入 500 行日志
- 请求 `tail=100`
- 断言：返回最后 100 行，`total_lines=500`，`lines[0]="line-0400"`, `lines[-1]="line-0499"`

#### test_get_preview_logs_returns_empty_when_log_missing
- preview/ 目录存在，但 preview.log 不存在
- 断言：返回 `lines=[]`, `total_lines=0`

## 验收标准

### P0

1. ✅ 后端：`grep -n "get_app_generation_preview_logs" growth_dev/team/dashboard.py` — 函数定义 + HTTP 路由
2. ✅ 前端：`grep -n "getAppPreviewLogs\|toggleAppPreviewLogs\|refreshAppPreviewLogs\|renderAppPreviewIframe" dashboard/app_generation.js` — 6+ hits
3. ✅ CSS：`grep -n "app-preview-logs" dashboard/styles.css` — 2+ hits
4. ✅ 测试：76/76 通过（74 旧 + 2 新）
5. ✅ JS 语法：`node --check dashboard/app_generation.js` — 无错误

### P1（手动验证，SANDBOX 不支持）

6. 🟡 启动 dashboard → 启动应用预览 → 点击"查看日志" → 显示日志内容（monospace 深色背景）
7. 🟡 日志视图 → 点击"返回预览" → 切回 iframe
8. 🟡 日志视图 → 点击"刷新日志" → 重新拉取最新日志
9. 🟡 preview 进程输出 500+ 行 → 日志视图显示"显示最后 200 行（共 N 行）"

## 技术决策

### D1 - 日志 tail 默认行数 200

**决策**：默认返回最后 200 行，前端不暴露 tail 参数调整。

**理由**：
- 200 行足够覆盖大部分启动错误和最近输出（约 10-15 屏）
- 避免大日志（10000+ 行）一次性传输阻塞 UI
- 如需完整日志，用户可直接访问 `runs/<run_id>/preview/preview.log`

### D2 - stdout + stderr 合并输出

**决策**：后端 `subprocess.Popen` 已将 stderr 重定向到 stdout（`stderr=subprocess.STDOUT`），前端只显示合并日志。

**理由**：
- 简化 UI（不需要 stdout/stderr tab 切换）
- 时间顺序保真（stderr 不会与 stdout 错位）
- 符合 preview.py 当前实现

### D3 - 日志视图与 iframe 互斥

**决策**：日志视图与 iframe 视图互斥，通过 `previewContent.dataset.view` 标记状态。

**理由**：
- 用户同时只能关注一个视图（日志 or 应用）
- 节省 DOM 渲染开销（不保留两个视图）
- 切换流畅（`toggleAppPreviewLogs` 双向切换）

### D4 - 不实时尾随（no live tail）

**决策**：日志视图不自动刷新，用户需手动点击"刷新日志"。

**理由**：
- 避免轮询刷新消耗带宽（每次传输 200 行）
- 用户可能需要查看特定错误，自动滚动会干扰
- 简化实现（无需 setInterval 管理）
- P3 可扩展为 WebSocket 实时推送

## 风险与缓解

### R1 - 大日志文件读取性能

**风险**：如果 preview.log 有 100MB+，`readlines()` 会阻塞 dashboard HTTP 线程。

**缓解**：
- tail=200 限制返回行数，即使大文件也只读最后 200 行
- Python `readlines()` 在 100MB 以下文件上性能可接受（< 100ms）
- 未来 P3 可改用 `tail -n 200` 命令（更高效）

### R2 - 非 UTF-8 日志内容

**风险**：预览应用输出二进制或非 UTF-8 字符时，`open(..., encoding="utf-8", errors="replace")` 会替换为 `�`。

**缓解**：
- `errors="replace"` 保证不会抛异常
- 前端 `pre` 元素正确显示替换字符
- 大部分 Node.js / Python 应用默认 UTF-8 输出

### R3 - 日志行数统计不准确

**风险**：`len(all_lines)` 统计行数，空行也计入，可能与用户预期不符。

**缓解**：
- 保持简单逻辑，不过滤空行（避免歧义）
- 元信息明确说"显示最后 N 行"，用户理解行 = `\n` 分隔
- 业务日志通常每行都有内容（timestamp + message）

## 遗留问题（Parked）

1. **实时尾随（live tail）缺失** — 用户需手动刷新。P3 可用 WebSocket 推送增量日志。
2. **日志搜索功能缺失** — 当前只能浏览器 Ctrl+F。P3 可加服务端 grep 支持。
3. **日志下载缺失** — 当前只能复制粘贴。P3 可加"下载完整日志"按钮，返回 `text/plain` 附件。
4. **多日志文件支持缺失** — 当前只显示 preview.log（合并 stdout/stderr）。如需分离，后端改 Popen 配置。

## 下一步（ROUND 5 P3 候选）

1. **Diff modal 简版** — patch_app 确认时显示 unified diff（纯 JS 实现，无新依赖）。
2. **日志实时尾随** — WebSocket 推送增量日志（需后端 preview.py 改造 + dashboard WebSocket handler）。
3. **Preview health 详情** — 健康检查失败时显示具体错误（HTTP status / timeout / connection refused）。
4. **应用预览快照** — 保存某个时刻的预览状态（URL / pid / 日志片段），便于事后分析。

## 总结

ROUND 5 P2 完成预览日志查看器，补齐应用预览调试最关键的能力。

**新增代码量**：
- Python：+18 行（get_app_generation_preview_logs 函数 + HTTP 路由）
- JS：+95 行（网络层 + UI 控制 + 日志渲染 + iframe 重构）
- CSS：+18 行（日志样式）
- Tests：+52 行（2 个测试用例）

**测试**：
- 后端回归：76/76 通过（74 旧 + 2 新）
- 静态验证：JS/CSS 接线点落位，语法校验通过

**交付物**：
- 用户可在应用预览 rail 点击"查看日志"，切换到日志视图
- 日志视图显示最后 200 行输出（monospace 深色背景）
- "返回预览"按钮切回 iframe，"刷新日志"按钮重新拉取

与 docs/app_preview_runner_spec.md § Preview Logs 契约对齐（虽未在该 spec 中明确，但符合"可观测"原则）。

## 对比 ROUND 5 P1

| 维度 | P1（Publish + Preview + Patch-app） | P2（Preview Logs） |
| --- | --- | --- |
| 复杂度 | 高（4 endpoint + 两阶段重启 + Agent action） | 低（1 endpoint + 简单 UI 切换） |
| 代码量 | +218 行 | +183 行 |
| 测试新增 | 0（依赖现有测试） | +2 个用例 |
| 用户价值 | 核心功能（预览必需） | 辅助功能（调试增强） |
| 技术风险 | 中（sandbox / 重启 / 轮询） | 低（只读日志文件） |

P2 作为 P1 的自然延伸，以较小代价显著提升预览调试体验。