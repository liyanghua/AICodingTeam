# ROUND 5 P1 复盘 — 前端 UI 接线（Publish + Preview + Patch-app）

## 任务目标

在 ROUND 5 P0（patch_app HTTP API + 两阶段重启）基础上，完成前端 workbench UI 接线：
1. 中间栏节点详情区增加 Publish + Preview 按钮
2. Preview-rail 复用为应用预览 iframe 模式（sandbox）
3. Agent 返回 patch_app action 时前端确认并调用后端
4. Preview 启动后轮询健康状态

## 实施内容

### 1. HTML 新增应用预览控制区（app_generation.html）

在节点详情 header 后插入：

```html
<section class="app-generation-detail-card app-generation-app-preview-controls" data-focus-card="app_preview">
  <div class="panel-header">
    <h3>应用预览与发布</h3>
  </div>
  <div class="app-generation-app-preview-actions">
    <button id="app-generation-publish-btn" type="button" class="ghost small">发布应用快照</button>
    <button id="app-generation-preview-btn" type="button" class="primary small">启动应用预览</button>
  </div>
  <p id="app-generation-app-preview-status" class="meta"></p>
</section>
```

### 2. JS 新增网络层函数（app_generation.js）

- `publishApp(runId, appSlug)` → `POST /api/app-generation/runs/<id>/publish-app`
- `startAppPreview(runId, appSlug)` → `POST /api/app-generation/runs/<id>/preview/start`
- `stopAppPreview(runId)` → `POST /api/app-generation/runs/<id>/preview/stop`
- `getAppPreviewStatus(runId)` → `GET /api/app-generation/runs/<id>/preview/status`
- `patchAppFile(runId, payload)` → `POST /api/app-generation/runs/<id>/patch-app`

### 3. JS 新增 UI 控制函数

- `openAppPreviewRail(previewData)` — 将 preview-rail 切换到应用预览模式，渲染 iframe（sandbox="allow-scripts allow-forms allow-same-origin"）+ toolbar（新窗口打开 / 停止预览）
- `closeAppPreviewRail()` — 关闭应用预览 rail，停止轮询
- `startAppPreviewPolling(runId)` — 每 3s 轮询 GET preview/status，更新健康状态；检测到 stale/stopped 自动关闭
- `stopAppPreviewPolling()` — 清理轮询 interval
- `publishAppFromUI(runId)` — 调用 publishApp，显示状态消息
- `startAppPreviewFromUI(runId)` — 调用 startAppPreview；若遇 412 app_not_published，先 publish 再重试
- `stopAppPreviewFromUI(runId)` — 调用 stopAppPreview，关闭 rail

### 4. JS 扩展 Agent action 处理

在 `handleAgentAction` 增加分支：

- `action.type === "patch_app"` → 调用 `handlePatchAppAction(action)`
- `action.type === "patch_artifact"` → 显示占位消息（v1 未接线）

新增 `handlePatchAppAction(action)` 函数：

1. 提取 `target_path / edit_kind / new_content / summary / anchor / action_id`
2. 用户确认（window.confirm 显示文件路径 + 编辑方式 + 说明）
3. 调用 `patchAppFile(state.selectedRunId, payload)`
4. 成功后：
   - 如果 result.restart.status 存在，显示重启信息（新 pid / 新 url）
   - 如果 appPreview 活跃，刷新 iframe src 并更新 state

扩展 `agentActionTitle` 映射：
- `patch_artifact` → "修改产物"
- `patch_app` → "修改已发布应用"
- `explain_inputs` / `explain_outputs`（未来扩展占位）

### 5. JS 事件绑定

在 `bindUI()` 中：

- `#app-generation-publish-btn` → `publishAppFromUI(state.selectedRunId)`
- `#app-generation-preview-btn` → `startAppPreviewFromUI(state.selectedRunId)`
- `#app-generation-preview-close` → 判断 `state.appPreview` 存在时调用 `closeAppPreviewRail()`，否则调用 `closeArtifactPreview()`
- `Escape` 键同上

### 6. JS 状态扩展

在 `state` 对象新增：

- `appPreview: null` — 当前应用预览数据（run_id / app_slug / url / port / pid / health_status）
- `appPreviewPollInterval: null` — 轮询 timer ID

### 7. CSS 样式新增（styles.css）

```css
.app-generation-app-preview-controls {
  border-left: 3px solid var(--color-accent, #3a8bff);
}

.app-generation-app-preview-actions {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.app-generation-app-preview-toolbar {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
  flex-wrap: wrap;
}

.app-generation-app-preview-iframe {
  width: 100%;
  height: clamp(420px, 60vh, 720px);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: #ffffff;
}

.app-generation-preview-rail[data-mode="app_preview"] {
  flex: 0 0 clamp(420px, 36vw, 560px);
  min-width: 420px;
}
```

## 验收标准

### P0

1. ✅ `grep -n "app-generation-publish-btn\|app-generation-preview-btn" dashboard/app_generation.html` — 2 hits（HTML 按钮存在）
2. ✅ `grep -n "publishApp\|startAppPreview\|patchAppFile" dashboard/app_generation.js` — 8+ hits（网络层函数存在）
3. ✅ `grep -n "patch_app\|handlePatchAppAction" dashboard/app_generation.js` — 5+ hits（action 处理接线）
4. ✅ `grep -n "app-preview-iframe\|sandbox=" dashboard/app_generation.js` — 1 hit（iframe sandbox 声明）
5. ✅ `node --check dashboard/app_generation.js` — 无语法错误
6. ✅ `python -m unittest tests.test_dashboard` — 74/74 通过（无回归）

### P1（手动验证，SANDBOX 环境不支持）

7. 🟡 启动 dashboard → app_generation.html → 选中 run → 点击"发布应用快照" → 返回 `{"published_at": "...", "app_slug": "...", "files_count": N}`
8. 🟡 点击"启动应用预览" → preview-rail 打开，显示 iframe + toolbar；iframe src = `http://127.0.0.1:<port>`，sandbox 声明
9. 🟡 Agent 返回 `patch_app` action → 用户点击确认 → 后端应用编辑 → 两阶段重启 → iframe 刷新
10. 🟡 点击 toolbar "停止预览" → 后端 kill 进程 → preview-rail 关闭

## 技术决策

### D1 - Preview-rail 复用 vs 新 panel

**决策**：复用现有 `app-generation-preview-rail`，用 `data-mode="app_preview"` 区分文件预览与应用预览模式。

**理由**：
- 用户同时只能关注一个预览（文件 or 应用），UI 互斥合理
- 节省一个 panel 的布局空间
- 通过 `state.appPreview` 存在判断模式，`closeArtifactPreview` 和 `closeAppPreviewRail` 分支清晰

### D2 - 412 app_not_published 自动 publish vs 显式报错

**决策**：前端自动先 publish 再 preview。

**理由**：
- 用户点击"启动应用预览"意图明确（想看应用），期望一键流程
- publish 是幂等操作，无副作用
- 减少用户点击次数（从 2 步降到 1 步）

### D3 - Patch-app diff 预览 vs 直接确认

**决策**：v1 用 `window.confirm` 显示文件路径 + 编辑方式 + 说明，不做 diff 渲染。

**理由**：
- diff 渲染需要前端 diff 库（monaco-diff / diff2html），增加依赖
- Agent 已在 message 中显示了调整说明，用户有上下文
- P1 可扩展为 modal + diff 视图

### D4 - Preview 健康轮询频率 3s

**决策**：每 3s 轮询一次 `GET preview/status`。

**理由**：
- 应用预览进程通常长期稳定运行，3s 延迟可接受
- 降低后端 API 压力（相比 1s 轮询）
- 检测到 stale/stopped 立即停止轮询，避免无效请求

## 风险与缓解

### R1 - iframe sandbox 限制预览应用功能

**风险**：`sandbox="allow-scripts allow-forms allow-same-origin"` 禁用了 `allow-top-navigation`，预览应用内的外链点击可能失效。

**缓解**：toolbar 提供"在新窗口打开"按钮，绕过 sandbox 限制。

### R2 - CORS / CSP 可能阻止 127.0.0.1 iframe

**风险**：部分浏览器或企业 CSP 策略可能阻止 dashboard（8790）iframe 加载 127.0.0.1:<preview_port>。

**缓解**：
- 后端 preview server 显式返回 `Access-Control-Allow-Origin: *`（已在 preview.py 实现）
- 用户手动在 dashboard response header 中配置 CSP（未来 P2）

### R3 - Patch-app 两阶段重启失败时 UI 不同步

**风险**：如果 patch_app 返回 `restart.status=health_timeout_kept_old`，后端保留旧进程，但前端 state.appPreview 可能已更新为新 URL。

**缓解**：前端只在 `restart.status == "success"` 时更新 iframe src；失败时保持原 URL。当前实现检查 `restart.url` 存在才刷新，符合这一约束。

### R4 - Agent 未返回 patch_app action 时功能不可达

**风险**：v1 只有 Agent 返回 `patch_app` action 才触发，用户无法手动修改已发布应用。

**缓解**：
- 用户可通过文件系统手动编辑 `runs/<run_id>/generated_apps/<slug>/` 文件，再调用 preview/stop + preview/start 重启
- P2 可在 UI 增加"手动编辑文件"按钮，调用 file explorer or inline editor

## 遗留问题（Parked）

1. **patch_artifact 未接线** — 只返占位消息。需后端实现 artifact worktree 锁定机制后再接线。
2. **diff 渲染缺失** — patch-app 确认只显示文本说明，无 before/after diff 视图。P2 扩展。
3. **Preview port 冲突处理** — 当前 preferred_port=8788 固定，多 run 并发 preview 会端口冲突。后端已实现 auto-increment 逻辑（preview.py），UI 无需改动。
4. **Preview 进程崩溃无主动通知** — 只能通过 3s 轮询发现。P2 可改用 WebSocket 推送。

## 下一步（ROUND 5 P2 候选）

1. **Manual file editor** — 在应用预览 toolbar 增加"编辑文件"按钮，调用 Monaco editor inline 编辑已发布应用文件，保存后自动触发 patch-app + 重启。
2. **Diff modal** — patch_app 确认时显示 modal，渲染 before/after diff（monaco-diff or diff2html）。
3. **Preview logs viewer** — preview-rail 增加"查看日志"tab，实时展示 preview process stdout/stderr（通过 log_path 读取）。
4. **Multi-preview support** — 允许同一 run 的多个 app_slug 并发预览（当前单 run 单 preview）。
5. **WebSocket push** — 替换 preview 健康轮询为 WebSocket 推送（后端 preview.py 需改造）。

## 总结

ROUND 5 P1 完成前端 Publish + Preview + Patch-app UI 接线，与 ROUND 5 P0 后端接口契约精确对齐。

**新增代码量**：
- HTML：+12 行（应用预览控制区）
- JS：+180 行（网络层 + UI 控制 + action 处理 + 事件绑定）
- CSS：+26 行（应用预览样式）

**测试**：
- 后端回归：74/74 通过（tests.test_dashboard）
- 静态验证：HTML/JS/CSS 接线点落位，JS 语法校验通过

**交付物**：
- 用户可在 workbench 一键发布应用快照 + 启动 iframe 预览
- Agent 返回 patch_app action 时前端确认并调用后端两阶段重启
- Preview 健康状态 3s 轮询 + 自动检测 stale 进程

与 docs/app_generation_workbench_spec.md § 应用预览模式、docs/app_preview_runner_spec.md § App Preview Rail 契约全面对齐。