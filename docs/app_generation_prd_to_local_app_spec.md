# PRD 生成轻量本地应用规范

## 状态

本规范描述已实现的 v1 `PRD -> 本地原型应用` 能力。当前仓库已包含 `domains/app_generation/`、`python -m growth_dev app generate` CLI、Dashboard 的 PRD 生成模式、Codex 隔离 worktree 生成链路、评审、验证和端到端 fake Codex 测试。

v1 仍只面向 PRD 原型验证，不是生产级应用交付。生成结果默认停留在隔离 worktree，必须经过人工确认 apply gate 才能进入主工作区。

## 产品目标

让用户输入一份 PRD 后，系统生成一个可在本地运行和审查的轻量原型应用，用于快速验证产品流程、页面状态、交互和验收标准。生成过程必须复用现有 Agent Team Runtime、结构化 run artifacts、Codex 隔离 worktree、评审、验证和人工确认 apply gate。

v1 面向 PRD 原型验证，不面向生产部署。默认生成原生 SPA + Node 本地服务，无数据库，状态保存在浏览器 `localStorage`。

v1 同时区分两种质量模式：

- `prototype`：普通 PRD 默认模式。外部系统可用本地 mock、assumption 或 blocker 表示。
- `benchmark_parity`：当输入 PRD 来自 `benchmarks/app_generation/<benchmark_id>/input_prd.md`，生成结果必须覆盖 benchmark `expected_capabilities.json` 中的必需能力，并以 `reference_app/` 的核心用户路径作为能力基线。实现可以不同，但不得用 mock-only 替代必需用户路径。

## 目标用户

- 产品或业务负责人：提交 PRD，快速看到可交互原型。
- AI-Team 操作者：启动生成 run，查看阶段产物、diff、测试和风险事件。
- 工程评审者：审查生成代码是否符合 PRD、路径边界、安全边界和验收标准。
- 后续维护者：基于本文档继续扩展模板、验证规则和应用生成质量。

## 核心流程

1. 用户提交 PRD 文本或 PRD 文件，并指定 `app_slug`。
2. 系统把原始 PRD 固化为 run artifact：`input_prd.md`。
3. 需求阶段生成标准化 PRD：`requirements/normalized_prd.md`。
4. 规划阶段生成官方验收标准、上下文包、覆盖矩阵、TDD 计划和 slices。
5. Codex 在隔离 worktree 中生成本地应用代码，默认写入 `runs/<run_id>/worktree/generated_apps/<app_slug>/`。worktree 是 Codex 的工作源，不被预览系统直接消费。
6. Reviewer 和 verifier 产出评审与验证报告。
7. Dashboard 或 CLI 展示 preview 说明、diff、测试结果、风险事件和下一步动作。
8. 用户在右侧工作台显式点击「发布到预览」后，dashboard 把 worktree 内的 `generated_apps/<app_slug>/` 拷贝快照到 `runs/<run_id>/generated_apps/<app_slug>/`，记录 `source_commit` 和 `published_at`。预览运行时只看这个发布快照，不直接读 worktree。
9. 只有在人类确认后，才允许通过现有 apply gate 把 worktree 变更应用到主工作区。apply gate 与「发布到预览」是两条独立通路：apply gate 影响主工作区源码，发布只影响预览快照。

### 应用发布与预览语义

v1 区分三个目录角色，禁止混用：

| 目录 | 角色 | 谁可以写 |
| --- | --- | --- |
| `runs/<run_id>/worktree/generated_apps/<slug>/` | Codex 工作源 | 仅 `implementation` 节点重跑；Agent 不得直接修改 |
| `runs/<run_id>/generated_apps/<slug>/` | 已发布预览快照 | 用户显式「发布到预览」时由 dashboard 从 worktree 拷贝；Agent 的 `patch_app` 在此目录原地改并落 `app_patches/` 证据 |
| `runs/<run_id>/codex/` | Codex 原始追踪 | 任何人都不得修改 |

发布契约见 [`docs/app_preview_runner_spec.md`](docs/app_preview_runner_spec.md) § 应用发布契约；Agent 的 `patch_artifact` / `patch_app` 契约见 [`docs/app_generation_agent_bridge_spec.md`](docs/app_generation_agent_bridge_spec.md)。`implementation` 节点重跑会回滚到「未发布」状态，旧 `app_patches/` 标记 `invalidated_by_rerun=true`。

## v1 应用形态

- 前端：原生 SPA，包含 `index.html`、`styles.css`、`app.js`。
- 服务端：Node stdlib HTTP server，负责本地静态文件服务和可选 mock fixture endpoint。
- 持久化：浏览器 `localStorage`。
- 数据库：不使用。
- 鉴权：不实现真实登录、凭证采集或 token 管理。
- 外部服务：普通 `prototype` 模式默认不调用；当 PRD 命中本文档「图片生成类 PRD 要求」节定义的触发条件（明确要求图片生成、主图生成、参考图出图、生图、模型选择或 OpenAI/OpenRouter 图片能力）时，prototype 模式仍必须按该节生成显式图片生成能力，不视作违反默认形态。`benchmark_parity` 模式可生成显式外部 provider，例如图片生成 provider，但必须通过 Node 服务端读取本地 `.env` 或进程环境，不得暴露或持久化 secret。
- React：仅作为未来模板选项。v1 默认不引入 React、Vite、bundler 或 npm package。

## 范围内

- 接收 PRD 文本或 PRD 文件作为输入。
- 生成原始 PRD artifact、标准化 PRD artifact 和应用契约 artifact。
- 从 PRD 派生验收标准、coverage matrix、TDD plan 和 slices。
- 生成一个可本地预览的 SPA 原型。
- 记录 preview 命令、生成文件清单、测试命令、风险事件和 blocker。
- 保持生成代码位于受控路径下。

## 范围外

- 不自动部署到线上环境。
- 不创建数据库、迁移或后台任务系统。
- 不采集、生成或保存用户凭证、API key、token、cookie、password。
- 不绕过现有 review、verification、apply gate。
- 不把 PRD 中的含糊假设直接当作事实实现。
- 不为了生成应用而修改无关 domain pack、第三方采集器、运行时安全边界或历史 run artifacts。

## 安全边界

- `manual_human_apply_only`：生成代码默认停留在隔离 worktree，主工作区变更需要人工确认。「发布到预览」与「apply 到主工作区」是两条独立通路：前者从 worktree 拷贝快照到 `runs/<run_id>/generated_apps/<slug>/` 供预览消费，后者把 worktree 变更合并到仓库主工作区。两者都不绕过人工确认。
- `no_database`：v1 不创建数据库，不生成数据库连接字符串，不写入迁移。
- `local_storage_only`：持久化只允许浏览器 `localStorage`。
- `no_secret_persistence`：不得把 secret 写入源码、run artifacts、localStorage 或 preview 配置。
- `no_hidden_network_calls`：默认不生成隐藏网络请求。外部集成必须以 mock 或 blocker 表示。
- `no_external_deploy`：不得自动部署、推送远端、创建云资源或发布公开链接。

## 成功标准

- 原始 PRD 被保存为 `input_prd.md`。
- 标准化 PRD 明确目标用户、主流程、范围边界、页面状态和数据对象。
- 官方验收标准可观察、可测试，并映射到 coverage matrix。
- 生成应用符合默认技术形态：原生 SPA + Node stdlib server + `localStorage` + 无数据库。
- 生成文件只位于允许路径内：worktree 内 `generated_apps/<app_slug>/`；发布后快照位于 `runs/<run_id>/generated_apps/<app_slug>/`。
- `preview_instructions.md` 说明本地运行方式和预览地址。
- review 和 verification artifact 明确记录测试结果、风险事件和 blocker。
- README 只声明已实现的 v1 本地原型能力，不承诺生产部署、数据库、自动发布或公开托管。
- 预览启动前必须先完成发布，未发布时返回 412 + `app_not_published` 错误。

## Benchmark Parity 模式

当 PRD 命中 benchmark 时，runtime 必须生成 `benchmark_context.json` 和 `benchmark_context.md`，并把 benchmark 的必需能力、hard gates、参考应用角色和验收摘要注入 Codex prompt。

Dingdang benchmark 下，生成应用必须至少支持：

- 产品图上传。
- 参考图上传。
- 显式图片 provider 代理，例如 OpenAI 或 OpenRouter。
- 单张和批量出图。
- Prompt 下载和图片下载。
- Provider 未配置、超时或模型不支持时的清晰错误提示。

这些能力仍必须遵守无数据库、无隐藏网络调用、无 secret persistence 和人工 apply gate。

## 图片生成类 PRD 要求

当 PRD 明确要求图片生成、主图生成、参考图出图、生图、模型选择、OpenAI/OpenRouter 图片能力或类似用户路径时，即使处于普通 `prototype` 模式，生成应用也必须把图片生成能力作为显式产品能力处理。不得只生成静态 Prompt 或 mock-only 占位来替代用户核心路径。

图片生成类 PRD 的 `app_contract.json` 应声明：

```json
{
  "required_capabilities": {
    "image_generation": true
  },
  "provider_config": "server_env_only"
}
```

生成应用至少应包含：

- 前端生图入口：单张生图按钮；若 PRD 要求批量图，则包含批量生图按钮。
- 模型选择或模型显示：用户能看到当前图片模型；可切换时必须通过服务端白名单或显式参数传给服务端。
- Provider 配置状态：页面展示已配置、未配置、模型缺失、请求超时或 provider 错误。
- `GET /api/health`：返回 provider、配置状态、当前模型和错误摘要。
- `POST /api/images/generate`：由 Node 服务端读取 `.env` 或进程环境后调用外部图片 provider。
- `.env.example`：只包含占位 key 和默认模型，不包含真实 secret。
- 失败路径：provider 未配置、模型不支持参考图、请求超时、网络错误时，UI 显示清晰错误，不静默卡住。

### 服务端 `.env` 配置

API key 的唯一配置来源是服务端 `.env` 或进程环境。前端不得要求用户输入 API key，也不得把 API key 写入 localStorage、URL、run artifact、日志、SSE 或 Agent prompt。

推荐 `.env.example`：

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

如果生成应用同时支持 OpenAI，可增加：

```dotenv
OPENAI_API_KEY=sk-your-key-here
OPENAI_IMAGE_MODEL=gpt-image-2
OPENAI_IMAGE_SIZE=1024x1024
OPENAI_IMAGE_QUALITY=high
OPENAI_IMAGE_OUTPUT_FORMAT=png
```

### OpenRouter 图片协议

OpenRouter 图片生成必须使用：

- Endpoint：`https://openrouter.ai/api/v1/images`
- 参考图字段：`input_references`
- 默认模型：`OPENROUTER_IMAGE_MODEL || "openai/gpt-5.4-image-2"`

禁止把 `chat/completions + modalities` 当作图片生成主路径。若 provider 文档或模型能力变化导致协议不可用，生成应用必须显示 provider setup error 或 blocker，而不是伪造成功。

生成应用不得只在前端写死 `gpt-image-1`。模型下拉或模型显示必须优先展示服务端 `.env` / 进程环境中的 `OPENROUTER_IMAGE_MODEL`，例如 `openai/gpt-5.4-image-2`。如应用提供模型下拉，选项来源应来自服务端白名单或健康检查返回值；前端不得要求用户输入 API key，也不得把 API key 放入 localStorage。

### 图片类应用的预览约束

一键预览启动前必须先完成「发布到预览」操作。预览成功只代表已发布快照 (`runs/<run_id>/generated_apps/<slug>/`) 的本地应用启动和 UI 可交互；真实生图依赖用户本机 `.env`、provider 余额、模型可用性和网络状态，需通过页面操作或手动验收确认。

preview 和 Agent 都不得展示 `.env` 内容。右侧 Agent 只能看到 provider 配置摘要，例如“未检测到 OPENROUTER_API_KEY”或“OpenRouter 已配置，模型 openai/gpt-5.4-image-2”。

如果预览运行时报 `gpt-image-1 · not configured`，但仓库根 `.env` 已配置 `IMAGE_PROVIDER=openrouter` 与 `OPENROUTER_IMAGE_MODEL=openai/gpt-5.4-image-2`，该问题应按通用 provider/model 配置错误处理：右侧 Agent 在 `app_preview` focus 下生成 `patch_app` PatchSet，修复已发布应用读取服务端模型配置、默认模型或健康检查显示的逻辑。该场景不得写成 Dingdang 专用判断，也不得要求用户手动编辑生成文件。

### 增量优化约束

如果预览发现图片生成能力缺失，例如没有生图按钮、没有模型选择、没有 `/api/images/generate` 或没有 provider 状态，右侧 Agent 应在 `app_preview` focus 下返回 `patch_app` action，直接修改已发布快照 `runs/<run_id>/generated_apps/<slug>/`，并在 `runs/<run_id>/app_patches/` 落证据（详见 [`docs/app_generation_agent_bridge_spec.md`](docs/app_generation_agent_bridge_spec.md) § patch_app 契约）。如果缺口需要回到节点产物层修复（例如 `app_contract.json` 漏声明能力），返回 `patch_artifact` 并修改 `runs/<run_id>/artifacts/<node>/<file>`，证据落在 `runs/<run_id>/artifact_patches/`。

`patch_app` 与 `patch_artifact` 必须保留已通过能力，例如已有四阶段工作流、产品图上传、方案单选、Prompt 生成、下载能力和 localStorage 状态。除非 PRD 本身缺少图片生成需求事实，否则不得回到 `prd_input` 或要求重写完整 PRD，也不得让 Agent 触发整个 `implementation` 节点重跑。

`implementation` 节点重跑会使已发布快照失效：UI 退回「未发布」状态，旧 `app_patches/` 记录标记 `invalidated_by_rerun=true` 但保留为审计证据。

## 已实现入口

- Domain pack：`domains/app_generation/domain.yaml`
- CLI：`python -m growth_dev app generate`
- Dashboard：请求表单中的“PRD 生成本地应用”模式
- Runtime artifacts：`input_prd.md`、`requirements/normalized_prd.md`、`app_contract.json`、`preview_instructions.md`
- E2E 测试：`tests/test_app_generation_e2e.py`

## 后续扩展方向

- 增加更多本地模板，例如 React 作为显式模板选项。
- 增强 PRD 中外部依赖、数据库诉求和 secret 风险的分类报告。
- 增加更细的生成应用 smoke test，但仍保持 v1 无数据库、无自动部署。
