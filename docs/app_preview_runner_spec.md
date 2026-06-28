# App Preview Runner Spec

## 状态

本规范定义阶段 0b：preview runner，负责把生成的应用拉起为可访问的本地服务，是「PRD → 能跑的实例」闭环的最后一公里。

## 目标

在生成阶段（codex 或 deterministic）完成后，提供确定性、可测试、安全的进程拉起与回收能力，把 `generated_apps/{app_slug}/` 变成浏览器可访问的 URL。

本规范同时定义下一轮 Dashboard 一键预览契约：工作台可以从 `app_generation` run 直接启动、停止和查询生成应用预览，并把预览 URL 交给内嵌浏览器栏展示。该能力仍处于规范阶段；除非代码、测试和 API 明确实现，否则不得在 UI 文案中暗示已经可用。

## 设计原则

- **可测试**：所有路径必须在不依赖真实 node 二进制的情况下也能跑测试（通过抽象 spawn 接口）。
- **可回收**：每次启动都注册回收钩子，确保进程退出时端口释放。
- **确定性产物**：每次启动产生一个 `preview_run_record.json` 记录 pid、port、url、健康状态、启动时间。
- **安全边界**：只允许从 allowed paths 启动；不允许绑定到 0.0.0.0；只绑定 127.0.0.1。
- **零外部依赖**：用 Python stdlib 实现，靠 socket + http.client 做端口分配与健康检查。

## 输入

```python
@dataclass
class PreviewRunRequest:
    run_id: str
    app_slug: str
    generated_app_dir: Path     # 绝对路径，必须在 allowed paths 内
    preview_command: list[str]  # 例如 ["node", "server.js"]
    preferred_port: int = 8788
    health_path: str = "/"
    health_timeout_seconds: float = 5.0
    repo_root: Path = Path(".")
```

## 输出

```python
@dataclass
class PreviewRunResult:
    status: Literal["running", "failed", "timeout"]
    pid: int | None
    port: int | None
    url: str | None
    health_status: Literal["ok", "failed", "unknown"]
    started_at: str             # ISO timestamp
    log_path: Path              # stdout/stderr 合并日志
    record_path: Path           # preview_run_record.json 绝对路径
    risk_events: list[str]
    message: str
```

## 核心模块

新增 `growth_dev/team/preview.py`，导出：

```python
def start_preview(request: PreviewRunRequest, *, runs_dir: Path) -> PreviewRunResult:
    """拉起应用进程，做端口分配 + 健康检查 + 状态记录。"""

def stop_preview(record_path: Path) -> dict[str, Any]:
    """根据 preview_run_record.json 优雅停止进程。"""

def list_active_previews(runs_dir: Path) -> list[dict[str, Any]]:
    """列出当前可能仍在运行的 preview（基于 record 文件）。"""

def allocate_port(preferred: int) -> int:
    """从 preferred 开始向上找一个可用 TCP 端口，最多尝试 50 次。"""

def wait_for_health(url: str, *, timeout: float) -> tuple[bool, str]:
    """轮询 HTTP HEAD/GET 直到 200 或超时。返回 (ok, message)。"""
```

## 关键算法

### 端口分配

```
for offset in range(50):
    candidate = preferred + offset
    if can_bind('127.0.0.1', candidate):
        return candidate
raise RuntimeError("no available port near preferred")
```

通过 `socket.socket()` + `bind` + `close` 探测。

### 启动流程

1. 校验 `generated_app_dir` 位于 allowed paths (`generated_apps/`) 之下
2. 校验 `preview_command` 第一个元素为白名单可执行（`node`、`python3`）
3. 分配端口
4. 把端口同时作为环境变量 `PORT` 和 `PREVIEW_PORT` 传入 server 进程
5. `subprocess.Popen` 拉起，stdout/stderr 重定向到 `runs/{run_id}/preview/preview.log`
6. 健康检查：轮询 `http://127.0.0.1:{port}{health_path}`，间隔 100ms，最长 `health_timeout_seconds`
7. 写入 `preview_run_record.json`
8. 返回 `PreviewRunResult`

### 停止流程

1. 读取 record，拿 pid
2. 先 `SIGTERM`，等 3 秒
3. 仍存活则 `SIGKILL`
4. 更新 record 的 `stopped_at` 字段

### 自动重启流程（两阶段）

`patch_app` 落盘并覆写 `runs/<run_id>/generated_apps/<slug>/<file>` 后，若当前 preview 处于 `running` 状态，触发两阶段重启：

**阶段 1 — 启动新进程并健康检查（旧进程不动）**

1. 读取 `preview_run_record.json` 得到 `old_pid` 和 `old_port`
2. 分配新端口 `new_port`（`new_port != old_port`，规则同 `### 端口分配`）
3. 用 `new_port` 拉起新 `node server.js` 进程，stdout/stderr 重定向到 `runs/<run_id>/preview/preview.<ts>.log`
4. 轮询 `http://127.0.0.1:{new_port}{health_path}`，间隔 100ms，最长 `health_timeout_seconds`

**阶段 2 — 健康通过则切流量 + 优雅停旧**

5. 健康通过：
   - 一次性更新 `preview_run_record.json`：`pid=new_pid`、`port=new_port`、`url=http://127.0.0.1:{new_port}`、`previous_pid=old_pid`、`previous_port=old_port`、`switched_at=<now>`
   - SSE 推 `preview_url_changed` + `preview_restarted`，前端 iframe 按新 URL 刷新
   - 对 `old_pid` 执行优雅停止：`SIGTERM` 等 3 秒，仍存活则 `SIGKILL`
   - `preview_status.app_patches_count` 递增

6. 健康失败：
   - 立即对 `new_pid` 执行 `SIGTERM`（3 秒）→ `SIGKILL`
   - **旧进程保持原状不杀**；`preview_run_record.json` 不改 `pid`/`port`
   - 写 `preview_status.last_patch_restart_error = {"phase": "new_process_health_check", "error": "...", "ts": "..."}`
   - SSE 推 `preview_restart_failed`，前端 banner「补丁已落盘但新版本启动失败，当前预览仍为旧版本」

**不变量：**

- 旧进程在新进程健康通过前始终运行；用户在切流量前看到的预览始终是旧版本。
- 端口切换通过 `preview_run_record.json` 原子写入实现；前端 iframe URL 切换由 SSE `preview_url_changed` 驱动。
- patch_app 后无 active preview 时不触发重启，下次手动启动加载最新代码。

## 与现有 server.js 模板的契约

deterministic 模板生成的 `server.js` 必须：
- 从 `process.env.PORT` 或 `process.env.PREVIEW_PORT` 读端口，fallback 到 8788
- 绑定 `127.0.0.1`，不绑定 0.0.0.0

这样 preview runner 可以动态注入端口，避免端口冲突。

Codex 生成的 `server.js` 也必须遵守同一契约。若生成应用只支持 `PORT`，preview runner 仍必须可用；若只支持 `PREVIEW_PORT`，也必须可用。

## Dashboard 一键预览 API

Dashboard 为 `app_generation` 工作台提供以下 API：

```text
POST /api/app-generation/runs/{run_id}/preview/start
POST /api/app-generation/runs/{run_id}/preview/stop
GET  /api/app-generation/runs/{run_id}/preview/status
```

### start

输入：

```json
{
  "preferred_port": 8788,
  "inject_env": true
}
```

规则：

- `preferred_port` 可选，默认来自 `app_contract.preview.url`，解析失败时用 8788。
- `inject_env=true` 时，Dashboard 从仓库根 `.env` 读取图片 provider 白名单字段并注入 preview 子进程环境。不得把任意 secret 同步到生成应用目录文件。
- 为兼容旧客户端，`sync_env=true` 可作为 `inject_env=true` 的别名，但语义仍是子进程 env 注入，不是复制 `.env`。
- 同一个 run 若已有 active preview，必须先 stop 旧进程，再启动新进程。
- 启动失败必须返回业务可理解的错误，例如端口不可用、`EPERM`、健康检查超时、生成应用目录缺失或启动命令不允许。

输出：

```json
{
  "status": "running",
  "run_id": "app_generation-...",
  "app_slug": "input-prd",
  "url": "http://127.0.0.1:8799",
  "port": 8799,
  "health_status": "ok",
  "health_message": "GET / returned 200",
  "record_path": "preview/preview_run_record.json",
  "log_path": "preview/preview.log",
  "risk_events": []
}
```

### stop

规则：

- 根据 `preview/preview_run_record.json` 停止进程。
- 无 active preview 时返回 `status=stopped` 或 `status=not_running`，不得报 500。
- stop 只影响 preview 进程，不改变 run status、节点状态或 artifacts。

### status

规则：

- 读取 `preview/preview_run_record.json`。
- 若 record 存在但 pid 已不存在，返回 `status=stopped` 或 `status=stale`。
- 返回值不得包含 `.env` 内容、API key 或完整进程环境。

## 应用发布契约

**预览源是发布快照，不是 worktree。** Dashboard 必须提供显式「发布到预览」操作，把 worktree 当前状态出货为稳定快照：

### `POST /api/app_generation/runs/<run_id>/publish-app`

请求体：

```json
{
  "app_slug": "optional, 默认从 task.yaml 推导或扫描唯一目录"
}
```

行为：

1. **源目录**：`runs/<run_id>/worktree/generated_apps/<slug>/`
2. **目标目录**：`runs/<run_id>/generated_apps/<slug>/`
3. **覆盖式全量拷贝**：已存在直接覆盖（不做增量 diff，不保留旧版本子目录）
4. **写发布记录**：`runs/<run_id>/generated_apps/<slug>/app_publish.json`

```json
{
  "published_at": "2026-06-27T09:30:00Z",
  "source_commit": "abc123def",
  "app_slug": "image-generator-prototype",
  "files_count": 12,
  "app_patches_count_at_publish": 0
}
```

5. **旧 app_patches 处理**：
   - 若 `generated_apps/<slug>/` 已存在且 `app_patches/index.json` 含记录，直接覆盖快照，旧 `app_patches/` **保留但 base 已变**。
   - 前端 toast 提示「已发布，N 个历史补丁 base 已变」（若 N > 0）。
   - rerun `implementation` 节点本身**不写**已发布快照 `runs/<run_id>/generated_apps/<slug>/`，只更新 worktree；同时把 `app_patches/index.json` 所有条目追加 `invalidated_by_rerun=true` 标记，`preview_status` 退回「未发布」。前端预览面板显示「N 个历史补丁因重新生成已失效，请重新发布到预览」。新的 worktree 内容只有在用户再次点「发布到预览」后才会进入快照。

6. **返回**：200 + `{published_at, app_slug, files_count}`

安全校验：

- 源目录必须在 `runs/<run_id>/worktree/` 下。
- 目标目录必须在 `runs/<run_id>/generated_apps/` 下。
- 禁止 `..`、符号链接逃逸或跨 run 操作。

## 生成应用目录解析

Dashboard 一键预览**唯一来源**是 `runs/<run_id>/generated_apps/<slug>/`（发布快照），不再 fallback worktree。

前置校验：

1. 若 `generated_apps/<slug>/` 不存在 → 返回 412，响应体：

```json
{
  "error": "app_not_published",
  "hint": "请先点「发布到预览」按钮，将 worktree 应用发布为预览快照"
}
```

2. 若 `app_publish.json` 缺失 → 返回 412，响应体：

```json
{
  "error": "missing_publish_record",
  "hint": "发布快照存在但缺少发布记录，请重新发布"
}
```

3. v1 单 run 单 `app_slug`。若 `generated_apps/` 下存在多个子目录且请求未显式指定 `app_slug`，preview start 必须返回 422，响应体形如：

```json
{
  "error": "multiple_apps_found",
  "apps": ["slug1", "slug2"],
  "hint": "请在请求 body 中显式指定 app_slug"
}
```

安全校验（沿用）：

- 解析后路径必须位于当前 run 目录下。
- 路径必须包含 `generated_apps` 段。
- 不允许绝对路径输入覆盖 `generated_app_dir`。
- 不允许 `..`、符号链接逃逸或跨 run 读取。

## App Preview Rail 契约

Dashboard 不直接把 preview runner 当作最终交付，而是把它暴露为工作台中的应用预览模式：

- 文件预览和应用预览复用同一个预览竖栏。
- `file_preview` 与 `app_preview` 互斥；打开应用预览会替换当前文件预览内容。
- 应用预览使用 iframe 加载 `PreviewRunResult.url`。
- iframe 必须显式声明 `sandbox="allow-scripts allow-forms allow-same-origin"`，避免预览页面通过 `window.top` 操控 dashboard 主页面。
- 预览竖栏关闭只隐藏 iframe，不停止 preview 进程；停止必须通过 stop API。
- 右侧 Agent 面板不因应用预览打开而被压缩或覆盖。

## Preview Env 注入白名单

一键预览必须支持从仓库根 `.env` 读取图片 provider 配置，并把白名单字段注入 preview 子进程环境。默认行为是 **process env injection**，不是把真实 secret 复制进 run artifact、Agent prompt 或前端状态。

允许注入 preview 子进程的字段仅限：

- `IMAGE_PROVIDER`
- `OPENROUTER_API_KEY`
- `OPENROUTER_API_BASE_URL`
- `OPENROUTER_IMAGE_MODEL`
- `OPENROUTER_IMAGE_SIZE`
- `OPENROUTER_IMAGE_QUALITY`
- `OPENROUTER_IMAGE_OUTPUT_FORMAT`
- `IMAGE_REQUEST_TIMEOUT_MS`
- `OPENAI_API_KEY`
- `OPENAI_IMAGE_MODEL`
- `OPENAI_IMAGE_SIZE`
- `OPENAI_IMAGE_QUALITY`
- `OPENAI_IMAGE_OUTPUT_FORMAT`

注入规则：

- preview runner 先读取仓库根 `.env`，只提取上述白名单字段，合并到子进程 env。
- 命令行显式传入的 preview env 覆盖仓库根 `.env`；未显式传入时仓库根 `.env` 覆盖父进程同名变量，保证本地工作台配置稳定可复现。
- `PORT` 与 `PREVIEW_PORT` 由 preview runner 注入，应用可读取任一字段。
- 不得把真实 API key 写入 `runs/<run_id>/generated_apps/<slug>/.env`，除非后续实现提供显式“写入本地预览配置”动作并要求用户确认；即使写入，也必须限制在已发布快照目录内，且不得进入 artifact 摘要。
- `.env` 内容不进入 run artifact 摘要、SSE 事件、Agent prompt、preview record、logs API 或日志。
- `.env.example` 只能包含占位值，不得复制真实 key。

推荐图片 provider 本地配置：

```dotenv
IMAGE_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-v1-your-key-here
OPENROUTER_API_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_IMAGE_MODEL=openai/gpt-5.4-image-2
OPENROUTER_IMAGE_SIZE=1024x1024
OPENROUTER_IMAGE_QUALITY=high
OPENROUTER_IMAGE_OUTPUT_FORMAT=png
IMAGE_REQUEST_TIMEOUT_MS=1200000
```

secret redaction 要求：

- preview record、日志摘要、SSE、Agent context 和 Dashboard API response 不得回显 API key 原文。
- 可展示 provider/model 摘要，例如「OpenRouter 已配置，模型 openai/gpt-5.4-image-2」或「未检测到 OPENROUTER_API_KEY」。
- 如果页面报错 `gpt-image-1 · not configured`，且 `.env` 中已有 `OPENROUTER_IMAGE_MODEL=openai/gpt-5.4-image-2`，右侧 Agent 在 `app_preview` focus 下应生成 `patch_app` PatchSet，修正已发布应用读取模型配置或默认模型的逻辑，而不是要求用户手动改文件。

## v1 独立沙箱定义

v1 的“独立沙箱”指独立本地 preview 进程、受控 cwd、命令白名单、路径白名单和 preview record，不引入 Docker、VM 或容器运行时。

独立 preview 进程不得：

- 修改旧 run artifact。
- 写入主仓库源码。
- 绕过 review、verification 或 apply gate。
- 绑定 `0.0.0.0` 或公开网络地址。
- 读取非白名单 secret。

## CLI 集成

新增子命令 `python -m growth_dev app preview`：

```
app preview start --run-id <id> [--runs-dir runs] [--port 8788]
app preview stop  --run-id <id> [--runs-dir runs]
app preview list  [--runs-dir runs]
```

`start` 返回 stdout：
```
PID: 12345
URL: http://127.0.0.1:8788
Log: runs/{run_id}/preview/preview.log
Health: ok
```

## 测试策略

### 单元测试（不依赖真实进程）
- `allocate_port`：mock `socket.bind`，验证回退逻辑
- `wait_for_health`：mock `http.client`，验证超时与重试
- `start_preview` 路径校验：传入越界目录应 raise
- `start_preview` 命令白名单：传入 `rm` 应 raise
- `inject_preview_env`：仓库根 `.env` 中的 `OPENROUTER_IMAGE_MODEL=openai/gpt-5.4-image-2` 进入子进程 env
- `secret_redaction`：preview record、logs API、SSE 和 Agent context 中不出现 `OPENROUTER_API_KEY` 原文
- `legacy_sync_env_alias`：`sync_env=true` 等价于 `inject_env=true`，但不复制真实 `.env` 到生成应用目录

### 集成测试（需要真实 node）
- 用 deterministic 生成器产出 server.js
- `start_preview` 拉起，curl `/` 返回 200
- `stop_preview` 后端口释放
- 跨平台 `SIGTERM`/`SIGKILL` 处理
- 已发布应用通过 `/api/health` 读到注入的 provider/model 摘要，但 response 不包含 API key

集成测试用 `unittest.skipUnless(shutil.which("node"), "node not available")` 守门。

## 安全边界

- ✅ 只允许绑定 127.0.0.1
- ✅ 只允许 `node` / `python3` 作为启动命令
- ✅ 只允许 `generated_apps/` 下的目录作为 cwd
- ✅ 进程退出时保证端口释放
- ❌ 不允许 `0.0.0.0` 绑定
- ❌ 不允许 shell=True
- ❌ 不允许相对路径逃逸（`../`）
- ❌ 不允许预览长期未停止（默认 24h 后视为僵尸）

## 产物文件

`runs/{run_id}/preview/`:
- `preview_run_record.json`：状态记录
- `preview.log`：进程输出
- `health_check.json`：健康检查历史

## preview_run_record.json schema

```json
{
  "schema_version": 1,
  "run_id": "app-generation-xxx",
  "app_slug": "todo-prototype",
  "pid": 12345,
  "port": 8788,
  "url": "http://127.0.0.1:8788",
  "command": ["node", "server.js"],
  "cwd": "/abs/path/to/generated_apps/todo-prototype",
  "started_at": "2026-03-14T10:00:00Z",
  "stopped_at": null,
  "health_status": "ok",
  "health_message": "GET / returned 200",
  "log_path": "preview/preview.log",
  "risk_events": []
}
```
