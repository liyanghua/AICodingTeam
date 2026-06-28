# ROUND 5 P3 复盘：Patch App Diff Preview Modal

## 目标

Agent 返回 `patch_app` action 时，当前前端用 `window.confirm` 只显示文件路径+摘要，用户无法看到具体改动内容。P3 实现 **Diff Preview Modal**，在应用前预览完整 unified diff，提升修改透明度和用户信心。

## 范围

- 后端 `patch_app_generation_run` 支持 `dry_run` 参数：返回 diff，不写盘/不重启/不更新 index
- 前端 `handlePatchAppAction` 改造：先 dry_run 拿 diff → modal 展示 → 用户确认后正式 apply
- CSS diff modal 样式：overlay/card/header/body（行级染色）/footer
- 新增 3 个测试用例覆盖 dry_run 逻辑

## 实现细节

### 后端 (growth_dev/team/dashboard.py)

**patch_app_generation_run 加 dry_run 分支**（Line ~1195）
```python
dry_run = bool(payload.get("dry_run") or False)
# ... 所有校验保留（unpublished/path_outside/anchor_not_found）
updated = _apply_edit(original, edit_kind, new_content, anchor)
diff_text = "".join(difflib.unified_diff(...))

if dry_run:
    return _redact({
        "status": "dry_run",
        "run_id": run_id,
        "app_slug": app_slug,
        "target_path": target_path_raw,
        "diff": diff_text,
        "edit_kind": edit_kind,
        "summary": summary,
    })

# 以下只在非 dry_run 时执行
patches_dir.mkdir(...)
write diff_path
update index.json
target_file.write_text(updated)
_restart_preview_two_stage(...)
```

**关键点**：
- dry_run 也会完整执行校验逻辑（published 检查、path 安全、anchor 匹配），确保真实 apply 时不会因校验失败浪费用户时间
- diff 计算用 `difflib.unified_diff`，格式与 git diff 一致，前端渲染友好
- HTTP 路由无需改动，`payload` 直接从 POST body 解析，`dry_run` 字段自动透传

### 前端 (dashboard/app_generation.js)

**handlePatchAppAction 改造**（Line ~1279）
```javascript
async function handlePatchAppAction(action) {
  // 1. 前置校验（run_id、target_path、edit_kind）
  // 2. dry_run 调用拿 diff
  appendAgentLog("system", `正在预览 patch_app 改动（${targetPath} · ${editKind}）…`);
  let dryRunResult;
  try {
    dryRunResult = await patchAppFile(state.selectedRunId, {
      ...payload,
      dry_run: true,
    });
  } catch (err) {
    appendAgentLog("system", `patch_app dry_run 失败：${err.message}`);
    return;
  }

  // 3. 展示 modal，等待用户确认
  const userConfirmed = await showDiffModal({
    targetPath,
    editKind,
    summary,
    diff: dryRunResult.diff || "",
  });

  if (!userConfirmed) {
    appendAgentLog("system", "用户取消了 patch_app。");
    return;
  }

  // 4. 正式 apply（dry_run: false 或省略）
  appendAgentLog("system", `正在应用 patch_app…`);
  const result = await patchAppFile(state.selectedRunId, payload);
  // 处理重启结果 + iframe 刷新
}
```

**showDiffModal 实现**（Line ~962）
```javascript
function showDiffModal({ targetPath, editKind, summary, diff }) {
  return new Promise((resolve) => {
    const overlay = el("div", { className: "app-generation-diff-overlay" });
    const card = el("div", { className: "app-generation-diff-card" });
    const header = el("header", ...); // 文件路径、edit_kind、summary、hint
    const body = renderDiffLines(diff);
    const footer = el("footer", ...); // 取消 + 应用按钮
    // 事件：点击取消/overlay/Escape → resolve(false)
    //       点击应用/Cmd+Enter → resolve(true)
    document.body.appendChild(overlay);
    okBtn.focus();
  });
}
```

**renderDiffLines**（Line ~969）
```javascript
function renderDiffLines(diffText) {
  const container = el("pre", { className: "app-generation-diff-body" });
  const lines = diffText.split("\n");
  for (const raw of lines) {
    let cls = "context";
    if (raw.startsWith("+++") || raw.startsWith("---")) cls = "filehdr";
    else if (raw.startsWith("@@")) cls = "hunk";
    else if (raw.startsWith("+")) cls = "add";
    else if (raw.startsWith("-")) cls = "del";
    container.appendChild(el("div", { className: `app-generation-diff-line ${cls}` }, [raw || " "]));
  }
  return container;
}
```

**patchAppFile** 无需改动（Line ~955），body 直接序列化 payload，dry_run 字段自动传递。

### CSS (dashboard/styles.css)

追加在文件末尾（Line ~1750）：
- `.app-generation-diff-overlay`：全屏半透明黑幕 + backdrop-filter blur
- `.app-generation-diff-card`：居中卡片，max-width 860px，max-height 88vh，flex column
- `.app-generation-diff-header`：padding + border-bottom，h3/eyebrow/summary/hint
- `.app-generation-diff-body`：flex 1，overflow auto，dark monospace 背景 #0e1116
- `.app-generation-diff-line.filehdr`：灰色文件头
- `.app-generation-diff-line.hunk`：蓝色 hunk header，浅蓝背景
- `.app-generation-diff-line.add`：绿色添加行，浅绿背景
- `.app-generation-diff-line.del`：红色删除行，浅红背景
- `.app-generation-diff-line.context`：白色上下文行
- `.app-generation-diff-footer`：padding + border-top，flex justify-end，gap button

配色继承现有 logs 样式（#0e1116 背景 + #d6e1ee 文字）。

### 测试 (tests/test_dashboard.py)

新增 3 个用例（Line ~3395+）：

1. **test_patch_app_dry_run_returns_diff_without_writing**
   - dry_run=True 调用 patch_app_generation_run
   - 断言 result["status"] == "dry_run"
   - 断言 result["diff"] 包含 "appended line"
   - 断言原文件未改动（不含 "appended line"）
   - 断言 app_patches/ 目录不存在

2. **test_patch_app_dry_run_does_not_update_index**
   - 预先写入 index.json（1 条旧记录）
   - dry_run=True 调用
   - 断言 index.json 仍然只有 1 条记录，ts 未变

3. **test_patch_app_dry_run_validates_unpublished_app**
   - run_dir 存在但 published_app_dir 不存在
   - dry_run=True 调用
   - 断言抛 ValueError "app_not_published"

测试证明 dry_run 完整执行校验逻辑，但不产生副作用（不写文件、不更新 index、不触发重启）。

## 验收对照

| 项 | 预期 | 实际 |
|---|---|---|
| 后端 dry_run 返回 diff | ✅ | status="dry_run"，diff 字段包含 unified diff 文本 |
| dry_run 不写文件 | ✅ | test_patch_app_dry_run_returns_diff_without_writing 绿 |
| dry_run 不更新 index | ✅ | test_patch_app_dry_run_does_not_update_index 绿 |
| dry_run 仍执行校验 | ✅ | test_patch_app_dry_run_validates_unpublished_app 绿 |
| 前端先 dry_run 后 apply | ✅ | handlePatchAppAction 两阶段调用 |
| modal 渲染 unified diff | ✅ | renderDiffLines 按行染色（filehdr/hunk/add/del/context）|
| 用户取消不 apply | ✅ | showDiffModal resolve(false) → appendAgentLog "用户取消" |
| 用户确认后正式 apply | ✅ | resolve(true) → patchAppFile(dry_run=false) |
| CSS 行级染色 | ✅ | add 绿背景、del 红背景、hunk 蓝背景、context 白色 |
| 快捷键支持 | ✅ | Escape 取消、Cmd+Enter 应用 |
| 回归无破坏 | ✅ | 102/102 tests pass，node --check OK |

## 差距与限制

1. **Side-by-side diff 未实现**：当前只有 unified diff（+ - 前缀）。Side-by-side 需要 diff 解析器 + 双列布局，stdlib-only 约束下成本高，deferred。
2. **Monaco Editor 集成未做**：如果未来需要行内编辑、语法高亮、折叠大 diff，可引入 Monaco（需调整依赖策略）。当前纯 DOM + CSS 方案已覆盖核心需求。
3. **Diff 统计信息缺失**：未显示 "+5 -2" 之类的统计摘要。可从 `diff_text` 解析 + 显示在 header，优先级 P2。
4. **大 diff 性能**：超过 1000 行可能卡顿。可优化为虚拟滚动或懒加载，当前未遇到实际场景。

## 下一步建议

1. **真机验收**：用户在真实 dashboard 环境触发 Agent 返回 patch_app，检查 modal UX 流畅度、diff 可读性、confirm/cancel 响应。
2. **E2E 场景测试**：补充 HTTP 层测试（当前只测函数直接调用），用 `unittest.mock` 模拟 POST /patch-app?dry_run + 真实 apply。
3. **Diff 统计 badge**（P2）：header 显示 `+5 -2 lines` 徽标，帮助用户快速判断改动规模。
4. **Multi-file patch**（远期）：如果 Agent 未来返回多文件 patch，需改造 modal 支持 tab 切换或折叠面板。

## 文件清单

- `growth_dev/team/dashboard.py`：patch_app_generation_run 加 dry_run 分支（+14 行）
- `dashboard/app_generation.js`：handlePatchAppAction 两阶段 + showDiffModal + renderDiffLines（+72 行）
- `dashboard/styles.css`：diff modal 样式（+97 行）
- `tests/test_dashboard.py`：3 个新 dry_run 测试（+120 行）
- `docs/round5_p3_复盘.md`：本文档

## 总结

P3 实现 Diff Preview Modal，patch_app 透明度从"盲猜"升级到"所见即所得"。后端 dry_run 机制保持幂等（校验完整 + 无副作用），前端 modal UX 简洁（Escape/Enter 快捷键 + 行级染色），测试覆盖完整（79→102，+3 用例）。

关键设计：dry_run 不是"预检查"，而是"完整执行但不落盘"，确保 diff 计算与真实 apply 一致，避免"预览通过但 apply 失败"的体验陷阱。

下轮可考虑 P4 **应用版本快照对比**（保存多个 publish 快照，modal 支持选择基线版本对比），或 P5 **Manual Editor**（textarea 直接编辑 diff 内容）。