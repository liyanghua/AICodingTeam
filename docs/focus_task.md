下面给你一版可以直接进入 AI-coding / 工程立项的方案。核心目标是把 **Playwright + Stagehand** 做成你经营增长 OS 的生产级“浏览器感知与执行底座”，沉淀为可复用、可评测、可审计、可回放的 **Browser Skill Runtime**。

---

# 0. 总体定位

你的浏览器自动化层不要定义成“爬虫”或“RPA”，而应该定义成：

> **经营增长 OS 的感知与执行层：通过受控浏览器节点，把平台页面、账号后台、内容发布、指标回采等非 API 能力，封装成可治理的 Browser Skills。**

它在系统中的位置：

```text
经营增长 OS
│
├─ Decision Brain / Ontology Brain
│   ├─ 决策：要采什么、执行什么、验证什么
│   └─ 输出 BrowserTaskSpec
│
├─ Browser Automation Gateway
│   ├─ Skill Registry
│   ├─ Policy Guard
│   ├─ Task Router
│   ├─ Playwright Runtime
│   ├─ Stagehand Runtime
│   ├─ Evidence Recorder
│   ├─ Eval / Replay Engine
│   └─ AgentBox Local Node
│
├─ Data Agent
│   ├─ 结构化指标入库
│   ├─ 报表解释
│   └─ 经营数据查询
│
└─ Growth Lab / 操盘工作台
    ├─ 机会卡
    ├─ 内容策划
    ├─ 商品诊断
    ├─ 发布测试
    └─ 效果复盘
```

Playwright 负责 **确定性、稳定性、测试、trace、video、截图、回放**。Playwright 官方 Trace Viewer 支持在执行后查看 trace，用于调试失败用例；Playwright Test 也支持按配置录制视频。([Playwright][1])

Stagehand 负责 **自然语言动作、页面理解、结构化抽取、弱选择器依赖、自愈式交互**。Stagehand 的核心能力是把代码控制和 AI 动作结合，提供 `act / extract / observe / agent` 等 primitives。([Stagehand][2])

---

# 1. 技术选型原则

## 1.1 Playwright 和 Stagehand 的职责边界

| 层级         | 首选技术                                  | 原因                               |
| ---------- | ------------------------------------- | -------------------------------- |
| 稳定页面操作     | Playwright                            | 确定性强，可测试，可回放                     |
| 账号态登录后操作   | Playwright                            | 可控、低风险、便于审计                      |
| 结构化指标回采    | Playwright + Stagehand extract        | Playwright 控制流程，Stagehand 辅助识别字段 |
| 页面元素变化较多   | Stagehand observe / act               | 降低选择器维护成本                        |
| 多步骤高风险执行   | Playwright 主导 + Stagehand 辅助          | 关键步骤必须可控                         |
| 未知页面探索     | Stagehand agent                       | 只用于探索和 POC，不直接作为生产主链路            |
| TDD / 回归测试 | Playwright Test                       | 稳定、成熟、CI 友好                      |
| 证据包        | Playwright trace / screenshot / video | 原生能力完整                           |

## 1.2 生产原则

你的核心原则应该是：

```text
高频任务代码化
变化任务 AI 化
关键动作审批化
所有执行证据化
失败原因结构化
成功经验 Skill 化
```

这意味着：
不要把 Stagehand 当成“万能 Agent”，而是把它当成 **Playwright 的 AI 增强层**。

---

# 2. 目标能力拆解

你要沉淀 6 类核心能力：

## 2.1 数据采集 Skill

用于从公开页面、搜索结果页、商品页、内容页、榜单页采集结构化信息。

典型场景：

```text
xhs.search_notes.collect
xhs.note.detail.collect
taobao.item.detail.collect
tmall.search_result.collect
douyin.video.detail.collect
competitor.product_page.collect
```

输出：

```json
{
  "skill_id": "xhs.search_notes.collect",
  "platform": "xhs",
  "keyword": "桌垫 防水 防油",
  "items": [
    {
      "title": "北欧风桌垫真实买家秀",
      "author": "xxx",
      "like_count": 1200,
      "comment_count": 88,
      "note_url": "...",
      "cover_image_url": "...",
      "rank_position": 1
    }
  ],
  "evidence_pack_id": "evp_20260526_001",
  "confidence": 0.91
}
```

## 2.2 指标回采 Skill

用于从账号后台回收内容、商品、活动、投放的数据。

典型场景：

```text
xhs.note.metrics.fetch
xhs.account.dashboard.fetch
tmall.item.metrics.fetch
tmall.business_advisor.download
douyin.video.metrics.fetch
```

输出：

```json
{
  "object_type": "note",
  "object_id": "xhs_note_123",
  "metric_date": "2026-05-26",
  "metrics": {
    "impression": 12345,
    "click": 456,
    "like": 300,
    "comment": 28,
    "favorite": 90
  },
  "source": {
    "platform": "xhs",
    "account_id": "acc_001",
    "evidence_pack_id": "evp_001"
  },
  "confidence": 0.95
}
```

## 2.3 平台执行 Skill

用于执行平台动作，但必须强治理。

典型场景：

```text
xhs.note.publish_draft
xhs.note.schedule_publish
tmall.product.image_upload
tmall.campaign.apply
douyin.video.upload_draft
```

注意：
发布、提交、报名、修改配置等动作，要区分：

```text
草稿动作：可自动执行
高风险动作：必须人工确认
不可逆动作：默认禁止自动执行
```

## 2.4 Evidence Pack

所有浏览器任务都要形成证据包。

包含：

```text
screenshots/
videos/
trace.zip
dom_snapshots/
network_summary.json
action_log.jsonl
risk_events.json
structured_result.json
failure_reason.json
```

Evidence Pack 的价值是：

1. 给人审；
2. 给复盘；
3. 给 Eval；
4. 给失败诊断；
5. 给策略回流；
6. 给客户交付证明。

## 2.5 TDD / Eval / Replay

这部分是生产级能力的关键。

你要把每个 Skill 变成可评测对象，而不是一次性脚本。

每个 Skill 至少有：

```text
unit test
mock page test
fixture data test
golden output test
real account smoke test
replay test
regression test
```

Playwright 官方有面向 coding agents 的 CLI，强调 token-efficient browser control、installable skills，适合和 AI-coding 工具协同。([Playwright][3])

## 2.6 AgentBox 本地执行节点

AgentBox 是运行在客户侧或本地机器上的浏览器执行节点，负责：

```text
账号态浏览器
本地 Cookie / Session
人工扫码登录
本地文件上传下载
浏览器截图/视频/trace
任务队列消费
结果回传
健康检查
```

这对你的 ToB 经营 OS 非常重要，因为很多平台后台无法只靠云端 API 解决。

---

# 3. 总体技术架构

## 3.1 分层架构

```text
L0：业务入口层
- Growth Lab
- 商品诊断
- 内容策划
- 操盘工作台
- Data Agent
- Decision Brain

L1：任务编译层
- BrowserTaskSpec Compiler
- Goal → Task
- OpportunityCard → CollectTask / PublishTask / FetchMetricTask
- ValidationPlan → MetricFetchTask

L2：浏览器自动化网关
- Browser Automation Gateway
- Skill Registry
- Policy Guard
- Task Router
- Credential Resolver
- Account Session Manager

L3：执行 Runtime
- Playwright Runtime
- Stagehand Runtime
- Hybrid Runtime
- Local AgentBox Runtime
- Optional Cloud Browser Runtime

L4：证据与观测层
- Evidence Recorder
- Trace Collector
- Screenshot Collector
- Video Collector
- Action Log
- Risk Event Log
- Failure Classifier

L5：评测与回放层
- TDD Harness
- Eval Harness
- Replay Engine
- Golden Dataset
- Skill Leaderboard
- Regression Gate

L6：数据与知识回流层
- Structured Result Store
- Data Lake / Warehouse
- Ontology Brain
- SOP / Skill Wiki
- Memory / Case Library
```

---

# 4. 核心模块设计

## 4.1 BrowserTaskSpec

这是经营 OS 和浏览器执行层之间的核心接口。

```yaml
task_id: task_20260526_001
task_type: data_collect
platform: xhs
account_id: acc_xhs_001
skill_id: xhs.search_notes.collect
priority: normal

input:
  keyword: "桌垫 防水 防油"
  max_items: 20
  sort: "综合"
  filters:
    content_type: "note"
    time_range: "30d"

execution:
  runtime: hybrid
  browser_mode: local_persistent
  headless: false
  timeout_seconds: 180
  max_retries: 2
  human_confirm_required: false

policy:
  allow_login: manual_only
  allow_publish: false
  allow_download: true
  allow_private_api_reverse_engineering: false
  allow_captcha_bypass: false
  rate_limit:
    max_tasks_per_hour: 10

evidence:
  screenshot: true
  trace: true
  video: retain_on_failure
  dom_snapshot: true
  action_log: true

output_schema: XhsSearchNotesResult
```

## 4.2 Skill Definition

每个 Skill 都应该是一个可版本化资产。

```yaml
skill_id: xhs.search_notes.collect
version: 0.1.0
name: 小红书搜索结果采集
category: data_collect
platform: xhs
owner: growth-lab

description: >
  输入关键词，在小红书搜索结果页采集笔记卡片信息，包括标题、作者、互动指标、封面图和链接。

input_schema:
  keyword:
    type: string
    required: true
  max_items:
    type: integer
    default: 20
  sort:
    type: string
    enum: ["综合", "最新", "最热"]

output_schema:
  type: object
  required:
    - items
    - evidence_pack_id
    - confidence

risk_level: medium

runtime:
  preferred: hybrid
  fallback:
    - playwright
    - stagehand

human_confirm_points: []

evidence_required:
  - screenshot
  - trace
  - action_log
  - structured_result

eval:
  golden_cases:
    - cases/xhs_search_notes/tablecloth_basic.yaml
  success_criteria:
    min_item_count: 10
    min_required_field_rate: 0.9
    min_confidence: 0.85
```

## 4.3 Runtime Router

路由规则：

```text
if skill.is_deterministic:
    use PlaywrightRuntime

if page_structure_unstable and task_is_low_risk:
    use StagehandRuntime

if task_has_fixed_flow_but_unstable_selectors:
    use HybridRuntime

if account_session_required:
    use AgentBoxLocalRuntime

if human_confirm_required:
    pause before critical action
```

## 4.4 Hybrid Runtime

Hybrid Runtime 是生产级核心。

推荐执行策略：

```text
1. Playwright 打开页面、管理上下文、控制账号态
2. Stagehand observe 识别页面候选元素
3. Playwright 执行确定性点击/输入
4. Stagehand extract 做结构化抽取
5. Playwright 保存截图、trace、video
6. Result Compiler 校验输出 schema
7. Evidence Recorder 归档证据包
```

Stagehand 的 `act()` 可以执行页面动作，`extract()` 可以进行结构化数据抽取，`observe()` 可以观察可执行动作，适合处理页面结构变化较多但任务目标明确的场景。([Stagehand][4])

---

# 5. 代码工程目录建议

建议 repo 结构如下：

```text
browser-automation-gateway/
│
├─ README.md
├─ AGENTS.md
├─ package.json
├─ pnpm-workspace.yaml
├─ tsconfig.json
├─ .env.example
│
├─ docs/
│  ├─ PRD.md
│  ├─ TECH_SPEC.md
│  ├─ ARCHITECTURE.md
│  ├─ SKILL_SPEC.md
│  ├─ EVAL_SPEC.md
│  ├─ SECURITY_POLICY.md
│  ├─ AGENTBOX_SPEC.md
│  └─ RUNBOOK.md
│
├─ apps/
│  ├─ gateway-api/
│  │  ├─ src/
│  │  │  ├─ routes/
│  │  │  ├─ services/
│  │  │  ├─ controllers/
│  │  │  └─ main.ts
│  │  └─ tests/
│  │
│  ├─ agentbox-node/
│  │  ├─ src/
│  │  │  ├─ worker.ts
│  │  │  ├─ session-manager.ts
│  │  │  ├─ health.ts
│  │  │  └─ uploader.ts
│  │  └─ tests/
│  │
│  └─ studio/
│     └─ src/
│
├─ packages/
│  ├─ core/
│  │  ├─ src/
│  │  │  ├─ task-spec.ts
│  │  │  ├─ skill-spec.ts
│  │  │  ├─ result.ts
│  │  │  ├─ policy.ts
│  │  │  └─ errors.ts
│  │
│  ├─ playwright-runtime/
│  │  ├─ src/
│  │  │  ├─ runtime.ts
│  │  │  ├─ browser-context.ts
│  │  │  ├─ trace.ts
│  │  │  ├─ screenshot.ts
│  │  │  └─ download.ts
│  │
│  ├─ stagehand-runtime/
│  │  ├─ src/
│  │  │  ├─ runtime.ts
│  │  │  ├─ act.ts
│  │  │  ├─ observe.ts
│  │  │  ├─ extract.ts
│  │  │  └─ schemas.ts
│  │
│  ├─ hybrid-runtime/
│  │  ├─ src/
│  │  │  ├─ runtime.ts
│  │  │  ├─ router.ts
│  │  │  └─ fallback.ts
│  │
│  ├─ evidence/
│  │  ├─ src/
│  │  │  ├─ recorder.ts
│  │  │  ├─ action-log.ts
│  │  │  ├─ evidence-pack.ts
│  │  │  └─ storage.ts
│  │
│  ├─ eval-harness/
│  │  ├─ src/
│  │  │  ├─ runner.ts
│  │  │  ├─ scoring.ts
│  │  │  ├─ golden.ts
│  │  │  └─ leaderboard.ts
│  │
│  └─ skill-registry/
│     ├─ src/
│     │  ├─ loader.ts
│     │  ├─ validator.ts
│     │  └─ registry.ts
│
├─ skills/
│  ├─ xhs/
│  │  ├─ search_notes_collect/
│  │  │  ├─ skill.yaml
│  │  │  ├─ handler.ts
│  │  │  ├─ schema.ts
│  │  │  ├─ eval_cases/
│  │  │  └─ README.md
│  │  │
│  │  ├─ note_metrics_fetch/
│  │  └─ note_publish_draft/
│  │
│  ├─ taobao/
│  ├─ tmall/
│  └─ douyin/
│
├─ fixtures/
│  ├─ mock_pages/
│  ├─ golden_outputs/
│  └─ sample_tasks/
│
├─ runs/
│  └─ .gitkeep
│
└─ scripts/
   ├─ run-task.ts
   ├─ run-eval.ts
   ├─ replay.ts
   └─ create-skill.ts
```

---

# 6. 核心数据模型

## 6.1 BrowserRun

```ts
export interface BrowserRun {
  runId: string;
  taskId: string;
  skillId: string;
  skillVersion: string;
  workspaceId: string;
  brandId?: string;
  accountId?: string;
  platform: string;

  status: "pending" | "running" | "success" | "failed" | "paused" | "cancelled";

  runtime: "playwright" | "stagehand" | "hybrid";
  startedAt: string;
  finishedAt?: string;

  input: Record<string, unknown>;
  output?: Record<string, unknown>;

  evidencePackId?: string;
  confidence?: number;

  failure?: {
    type: string;
    message: string;
    stepId?: string;
    recoverable: boolean;
  };

  metrics: {
    durationMs: number;
    retryCount: number;
    actionCount: number;
    screenshotCount: number;
    tokenUsage?: number;
  };
}
```

## 6.2 EvidencePack

```ts
export interface EvidencePack {
  evidencePackId: string;
  runId: string;
  taskId: string;
  skillId: string;

  artifacts: {
    screenshots: string[];
    videos: string[];
    traces: string[];
    domSnapshots: string[];
    downloads: string[];
    actionLog: string;
    networkSummary?: string;
    structuredResult?: string;
    failureReason?: string;
  };

  summary: {
    finalUrl: string;
    pageTitle?: string;
    riskEvents: RiskEvent[];
    confidence: number;
  };

  createdAt: string;
}
```

## 6.3 ActionLog

```json
{
  "timestamp": "2026-05-26T10:00:00+08:00",
  "step_id": "step_003",
  "action_type": "click",
  "engine": "playwright",
  "target": "搜索框",
  "selector": "input[type='search']",
  "instruction": "点击搜索框",
  "result": "success",
  "screenshot": "screenshots/step_003.png"
}
```

## 6.4 FailureReason

```json
{
  "failure_type": "selector_not_found",
  "recoverable": true,
  "step_id": "step_004",
  "message": "搜索结果卡片选择器未找到",
  "suggested_recovery": "fallback_to_stagehand_observe",
  "evidence": {
    "screenshot": "screenshots/failure.png",
    "trace": "trace.zip"
  }
}
```

---

# 7. Skill 类型设计

## 7.1 数据采集 Skill

```text
输入：关键词 / URL / 类目 / 条件
过程：打开页面 → 搜索/访问 → 滚动 → 抽取 → 去重 → 校验
输出：结构化列表 + 证据包
```

核心指标：

```text
字段完整率
去重准确率
采集数量达成率
页面异常识别率
失败可恢复率
```

## 7.2 指标回采 Skill

```text
输入：对象 ID / 日期范围 / 账号 ID
过程：登录态检查 → 进入后台 → 定位对象 → 获取指标 → 截图留证
输出：指标快照 + 证据包
```

核心指标：

```text
数值准确率
日期匹配准确率
对象匹配准确率
截图证据完整率
```

## 7.3 平台执行 Skill

```text
输入：素材 / 文案 / 商品 / 发布配置
过程：进入后台 → 上传素材 → 填写信息 → 预览 → 人工确认 → 提交或保存草稿
输出：执行状态 + 平台对象 ID + 证据包
```

核心指标：

```text
流程完成率
人工确认点命中率
错误提交率
草稿保存成功率
证据完整率
```

---

# 8. 三个首批 P0 Skill

建议第一阶段只做 3 个，不要铺太大。

## P0-1：小红书搜索结果采集

```yaml
skill_id: xhs.search_notes.collect
purpose: 从关键词采集小红书搜索结果，用于机会卡和内容策略输入
runtime: hybrid
risk_level: medium
```

输入：

```json
{
  "keyword": "桌垫 防水 防油",
  "max_notes": 20,
  "sort": "综合"
}
```

输出：

```json
{
  "notes": [
    {
      "title": "...",
      "author": "...",
      "like_count": 123,
      "comment_count": 12,
      "cover_image_url": "...",
      "note_url": "...",
      "rank_position": 1
    }
  ],
  "evidence_pack_id": "..."
}
```

## P0-2：小红书笔记指标回采

```yaml
skill_id: xhs.note.metrics.fetch
purpose: 回采已发布笔记的曝光、互动、收藏等指标
runtime: playwright_first
risk_level: medium
```

## P0-3：小红书笔记草稿发布

```yaml
skill_id: xhs.note.publish_draft
purpose: 把 Growth Lab 生成的标题、正文、图片发布为草稿
runtime: playwright_first
risk_level: high
human_confirm_required: true
```

这个 Skill 不建议一开始自动点击最终发布。先做“保存草稿 + 人工确认”。

---

# 9. Policy Guard 设计

这是生产级系统最重要的边界。

## 9.1 禁止行为

```yaml
forbidden:
  - captcha_bypass
  - fingerprint_spoofing
  - proxy_rotation_for_avoidance
  - private_api_reverse_engineering
  - unauthorized_account_access
  - destructive_action_without_confirmation
```

## 9.2 风险等级

```text
Low：公开页面采集、截图、结构化抽取
Medium：账号后台指标查看、报表下载
High：内容上传、草稿创建、配置修改
Critical：最终发布、广告投放、活动报名、价格修改
```

## 9.3 人工确认点

```yaml
human_confirm_points:
  - before_final_publish
  - before_price_change
  - before_campaign_submit
  - before_delete
  - before_bulk_operation
```

---

# 10. TDD / Eval / Replay 体系

## 10.1 Skill 测试分层

```text
L1 Unit Test
- schema 校验
- 输入输出转换
- URL 解析
- 数据清洗

L2 Mock Page Test
- 使用本地 HTML fixture
- 测试选择器和抽取逻辑

L3 Golden Case Test
- 固定页面快照
- 对比 golden output

L4 Real Smoke Test
- 使用测试账号
- 低频真实页面验证

L5 Regression Test
- 每次 skill 版本升级必须跑
- 不通过不能发布

L6 Replay Test
- 使用 trace / screenshot / action log 复盘失败
```

## 10.2 Eval 指标

| 指标                      | 含义            |    建议阈值 |
| ----------------------- | ------------- | ------: |
| task_success_rate       | 任务成功率         |   ≥ 90% |
| required_field_rate     | 必填字段完整率       |   ≥ 95% |
| output_schema_pass_rate | 输出 schema 通过率 |    100% |
| evidence_complete_rate  | 证据包完整率        |   ≥ 98% |
| replay_available_rate   | 可回放率          |   ≥ 95% |
| false_success_rate      | 误判成功率         |    ≤ 2% |
| human_intervention_rate | 人工介入率         | 按任务类型评估 |
| avg_task_cost           | 平均任务成本        |    持续下降 |
| avg_duration_ms         | 平均耗时          |    持续优化 |

## 10.3 Golden Case

```yaml
case_id: xhs_search_notes_001
skill_id: xhs.search_notes.collect
input:
  keyword: "桌垫 防水 防油"
  max_notes: 10

expected:
  min_items: 8
  required_fields:
    - title
    - author
    - note_url
    - cover_image_url
  field_rate_threshold: 0.9
  confidence_threshold: 0.85
```

---

# 11. Replay Engine 设计

Replay 的目标不是“重新执行”，而是让人能看懂为什么成功或失败。

Replay 页面至少展示：

```text
任务信息
Skill 版本
输入参数
执行时间线
每一步 action
对应 screenshot
trace 链接
video 链接
结构化输出
失败原因
风险事件
人工确认记录
```

Playwright trace 可以用于执行后调试，官方 Trace Viewer 支持查看执行过程中的页面状态、动作和上下文。([Playwright][1])

---

# 12. AgentBox 本地节点设计

## 12.1 AgentBox 的职责

```text
1. 管理本地浏览器环境
2. 保存账号 session
3. 执行 Gateway 下发的 BrowserTask
4. 上传 Evidence Pack
5. 支持人工接管
6. 上报健康状态
```

## 12.2 AgentBox 架构

```text
AgentBox Local Node
│
├─ Task Puller
│   └─ 从 Gateway 拉取任务
│
├─ Session Manager
│   ├─ 浏览器 profile
│   ├─ Cookie/session
│   └─ 登录状态检测
│
├─ Runtime Executor
│   ├─ Playwright Runtime
│   ├─ Stagehand Runtime
│   └─ Hybrid Runtime
│
├─ Evidence Recorder
│   ├─ screenshot
│   ├─ trace
│   ├─ video
│   └─ action log
│
├─ Human Control Panel
│   ├─ 暂停
│   ├─ 接管
│   ├─ 确认
│   └─ 终止
│
└─ Uploader
    ├─ 上传结果
    ├─ 上传证据包
    └─ 上报健康状态
```

## 12.3 AgentBox 心跳

```json
{
  "agentbox_id": "agentbox_001",
  "workspace_id": "ws_001",
  "status": "online",
  "browser_status": "ready",
  "active_sessions": 2,
  "running_tasks": 1,
  "queue_capacity": 5,
  "last_heartbeat_at": "2026-05-26T10:00:00+08:00"
}
```

---

# 13. 与经营增长 OS 的业务对象打通

## 13.1 机会卡 → 数据采集任务

```text
OpportunityCard
→ 需要验证某个趋势
→ 生成 xhs.search_notes.collect
→ 回收内容样本
→ Data Agent 分析
→ OpportunityCard 更新证据链
```

## 13.2 内容策划 → 平台执行任务

```text
NotePlan
→ 标题 / 正文 / 图片
→ xhs.note.publish_draft
→ 保存草稿
→ 人工确认
→ 发布
→ 回采 note_id
```

## 13.3 测试任务 → 指标回采任务

```text
TestTask
→ 发布后 T+1/T+3/T+7 回采
→ xhs.note.metrics.fetch
→ ResultSnapshot
→ AmplificationPlan
→ AssetPerformanceCard
```

## 13.4 商品诊断 → 后台数据回采

```text
DiagnosisGoal
→ 需要单品近 7/30 天数据
→ tmall.item.metrics.fetch
→ 指标入库
→ DiagnosisReport
→ ExecutablePlanPack
```

---

# 14. 分阶段落地规划

# Phase 0：技术底座 POC，1-2 周

## 目标

验证 Playwright + Stagehand 的组合能跑通：

```text
打开页面
执行搜索
抽取结构化数据
生成证据包
保存 trace / screenshot / action log
```

## 交付物

```text
1. browser-automation-gateway repo
2. BrowserTaskSpec v0.1
3. EvidencePack v0.1
4. PlaywrightRuntime v0.1
5. StagehandRuntime v0.1
6. HybridRuntime v0.1
7. xhs.search_notes.collect demo
```

## 验收标准

```text
- 能输入关键词采集 10 条搜索结果
- 输出 JSON schema 校验通过
- 每次 run 有截图和 action log
- 失败时能输出 failure_reason
- 本地可通过 npm/pnpm 一键运行
```

---

# Phase 1：P0 Skill 生产化，3-4 周

## 目标

把 3 个 P0 Skill 做成可复用能力。

```text
xhs.search_notes.collect
xhs.note.metrics.fetch
xhs.note.publish_draft
```

## 重点能力

```text
Skill Registry
Policy Guard
Evidence Recorder
Eval Harness
Replay Viewer 初版
AgentBox Local Node 初版
```

## 交付物

```text
1. skills/xhs/search_notes_collect
2. skills/xhs/note_metrics_fetch
3. skills/xhs/note_publish_draft
4. skill.yaml 标准
5. eval case 标准
6. evidence pack 标准
7. AgentBox 本地 worker
8. Replay HTML 报告
```

## 验收标准

```text
- 每个 Skill 至少 5 个 eval case
- 输出 schema pass rate = 100%
- evidence complete rate ≥ 95%
- search_notes_collect 成功率 ≥ 85%
- note_metrics_fetch 成功率 ≥ 80%
- publish_draft 支持人工确认
- 所有高风险动作默认暂停等待确认
```

---

# Phase 2：接入 Growth Lab / 操盘工作台，4-6 周

## 目标

让 Browser Skills 成为业务工作台可调用能力。

## 打通链路

```text
机会卡 → 采集任务
内容方案 → 草稿发布
测试任务 → 指标回采
结果快照 → 放大建议
```

## 新增对象

```text
BrowserTask
BrowserRun
EvidencePack
SkillRunReport
ResultSnapshot
PlatformObjectBinding
```

## 前端页面

```text
1. Browser Task Center
2. Skill Registry
3. Run Detail
4. Evidence Replay
5. AgentBox Status
6. Human Confirmation Queue
```

## 验收标准

```text
- 业务页面可发起浏览器任务
- 任务状态实时更新
- 结果自动绑定到机会卡 / 测试任务
- 失败任务可查看截图、trace、日志
- 人工确认任务可暂停、继续、终止
```

---

# Phase 3：多平台扩展，6-8 周

## 目标

从小红书扩展到淘宝 / 天猫 / 抖音等平台。

## 新增 Skill

```text
tmall.item.detail.collect
tmall.item.metrics.fetch
tmall.business_report.download
douyin.video.metrics.fetch
douyin.video.upload_draft
```

## 重点

```text
平台适配层
账号隔离
多租户 workspace
下载文件处理
对象绑定
指标口径标准化
```

## 验收标准

```text
- 至少支持 3 个平台
- 每个平台至少 2 个核心 Skill
- 指标统一进入 MetricSnapshot
- 支持 workspace / brand / account 隔离
- 支持多 AgentBox 节点注册
```

---

# Phase 4：Eval Leaderboard + Skill 自优化，持续建设

## 目标

把浏览器 Skill 从“能跑”升级到“能持续优化”。

## 能力

```text
Skill Leaderboard
失败聚类
选择器自愈建议
Stagehand fallback 策略优化
Prompt 版本对比
Skill 版本灰度
成本 / 成功率 / 耗时评估
```

## 指标

```text
- 每个 Skill 有 weekly success rate
- 每个 Skill 有 cost trend
- 每个 Skill 有 failure type distribution
- 每个 Skill 有 regression gate
- 新版本必须优于 baseline 才能发布
```

---

# 15. 关键工程难点与解决方案

## 15.1 页面变化导致脚本失效

解决：

```text
Playwright 固定主流程
Stagehand observe 辅助定位
失败后 fallback 到自然语言动作
把失败截图进入 regression case
```

## 15.2 数据抽取不稳定

解决：

```text
强 schema
字段级 confidence
多源校验
单位/日期/数字清洗
golden output 对比
```

## 15.3 账号登录与风控

解决：

```text
人工登录
本地持久化 profile
禁止验证码绕过
低频任务
账号健康检测
人工接管
```

## 15.4 高风险平台执行

解决：

```text
默认保存草稿
最终发布人工确认
关键动作截图
不可逆动作黑名单
审批队列
```

## 15.5 证据包成本过高

解决：

```text
成功任务只保留关键截图 + action log
失败任务保留 video + trace
高风险任务完整保留
设置生命周期归档策略
```

---

# 16. AI-coding 任务拆解

你可以让 AI-coding 按下面顺序实现。

## Sprint 1：基础工程

```text
1. 初始化 monorepo
2. 定义 BrowserTaskSpec / SkillSpec / BrowserRun / EvidencePack
3. 实现 PlaywrightRuntime
4. 实现 EvidenceRecorder
5. 实现 run-task CLI
6. 实现一个 mock skill
```

## Sprint 2：Stagehand 集成

```text
1. 接入 StagehandRuntime
2. 封装 act / observe / extract
3. 实现 HybridRuntime
4. 支持 fallback 策略
5. 支持结构化 extract schema 校验
```

## Sprint 3：第一个真实 Skill

```text
1. 实现 xhs.search_notes.collect
2. 加入 screenshots
3. 加入 action_log
4. 加入 trace
5. 加入 failure_reason
6. 写 5 个 eval case
```

## Sprint 4：AgentBox

```text
1. 实现本地 worker
2. 支持任务拉取
3. 支持浏览器 profile
4. 支持 session 检查
5. 支持结果上传
6. 支持健康心跳
```

## Sprint 5：业务接入

```text
1. 接入 Growth Lab OpportunityCard
2. 支持页面发起 collect task
3. 展示 run 状态
4. 展示 evidence pack
5. 回写采集结果
```

---

# 17. 最小可用版本定义

MVP 不要追求全平台。MVP 只需要证明：

```text
一个业务任务
一个浏览器 Skill
一次结构化结果
一份证据包
一次评测
一次回放
一次业务回流
```

建议 MVP 场景：

> **小红书关键词采集 → 生成内容机会证据 → 机会卡更新 → Evidence Pack 可回放。**

MVP 成功标准：

```text
- 输入关键词后自动采集 10-20 条内容
- 结果结构化进入机会卡证据区
- 每条任务有截图、日志、trace
- 失败可定位原因
- 可重复跑 eval case
```

---

# 18. 最终推荐技术栈

```text
Language:
- TypeScript

Browser:
- Playwright
- Stagehand

Backend:
- Fastify / NestJS 二选一
- PostgreSQL
- Redis / BullMQ
- MinIO / S3 compatible storage

AgentBox:
- Node.js worker
- Playwright persistent context
- Local profile storage
- WebSocket / polling task channel

Eval:
- Playwright Test
- Custom Eval Harness
- Golden JSON
- Replay Report HTML

Observability:
- OpenTelemetry
- structured logs
- run metrics
- evidence artifact storage

Security:
- workspace isolation
- account isolation
- encrypted credential reference
- policy guard
- human confirmation
```

---

# 19. 你现在最应该做的 5 件事

## 1. 先定义 BrowserTaskSpec

没有统一任务协议，后面 Skill 会散。

## 2. 先做 Evidence Pack

证据包是生产级和 demo 级的分水岭。

## 3. 先做一个 P0 Skill

建议从 `xhs.search_notes.collect` 开始。

## 4. 先做 Eval Harness

不要等 Skill 很多之后再补评测。

## 5. 先做 AgentBox 最小节点

本地账号态、人工登录、截图留证，是你后面 ToB 交付的关键能力。

---

# 20. 最终路线图压缩版

```text
第 1-2 周：
Browser Gateway + PlaywrightRuntime + EvidencePack + xhs.search_notes.collect POC

第 3-6 周：
StagehandRuntime + HybridRuntime + Skill Registry + Eval Harness + Replay Report

第 7-10 周：
AgentBox Local Node + xhs.note.metrics.fetch + xhs.note.publish_draft

第 11-16 周：
接入 Growth Lab / 操盘工作台，形成机会卡采集、草稿发布、指标回采闭环

第 17-24 周：
扩展淘宝/天猫/抖音，建设多租户、账号隔离、Skill Leaderboard、失败聚类和持续优化
```

---

# 21. 最核心的架构判断

这套能力真正的价值不是“自动打开网页”，而是：

> 把平台页面里的数据、动作、结果，全部变成经营 OS 可调用、可评测、可回放、可沉淀的 **Browser Skills**。

你的经营增长 OS 最终应该形成这样的闭环：

```text
策略判断
→ 生成浏览器任务
→ 自动采集 / 执行 / 回采
→ 形成证据包
→ 结构化入库
→ 进入机会卡 / 诊断 / 测试任务
→ 复盘效果
→ 优化 Skill 和策略
```

这就是 Playwright + Stagehand 在你系统里的最佳定位：
**不是 RPA 工具，而是经营增长 OS 的平台感知与执行基础设施。**

[1]: https://playwright.dev/docs/trace-viewer?utm_source=chatgpt.com "Trace viewer"
[2]: https://docs.stagehand.dev/v3/first-steps/introduction?utm_source=chatgpt.com "Stagehand Docs"
[3]: https://playwright.dev/agent-cli/introduction?utm_source=chatgpt.com "Playwright CLI"
[4]: https://docs.stagehand.dev/v3/basics/act?utm_source=chatgpt.com "Act - Stagehand Docs"
