# Tech Spec: 市场分析洞察报告生成器

> 上游 PRD：[`prd.md`](prd.md)。技术决定按 PRD「标准段 / 定制段」二分。标准段由模板渲染器或现有 deterministic fallback 生成；定制段由 Code Agent 实现。

## 1. 运行形态

| 层 | 技术选择 | 说明 |
| --- | --- | --- |
| 静态前端 | 原生 SPA（`index.html / styles.css / app.js`） | 复用 `docs/app_generation_deterministic_fallback_spec.md` 的 SPA 模板 |
| HTTP 服务端 | Python FastAPI（uvicorn 启动） | 提供 `/api/...` 接口；同时静态托管 `public/` |
| 规则引擎 | Python 模块 `rules/` | 纯函数；输入 schema 校验通过的 dict，输出结论 list |
| DAG 执行 | 复用 [`document-to-skill-engineering-package/src/doc_to_skill/runtime.py`](../../document-to-skill-engineering-package/src/doc_to_skill/runtime.py) | 由 FastAPI 路由触发，按节点状态机驱动 |
| 持久化 | 浏览器 `localStorage` + 服务器 `runs/<run_id>/` 文件夹 | 不引入数据库 |
| 网络 | 不出网 | 不安装 `requests` 等远程客户端；禁止真实电商 API |

端口：`8789`（写入 `task.yaml.base_url`）。

## 2. 目录布局

```
generated_apps/market-insight-report-app/
  server.py              # FastAPI 入口
  rules/
    hot_gene.py          # strong_hot_gene / trend_hot_gene
    differentiated.py    # differentiated_opportunity_gene
    opportunity_score.py # opportunity_score
  csv_io/
    schemas.py           # 与 data_requirements.yaml 一一对应
    aliases.py           # csv_field_aliases 实现
    loader.py            # CSV → dict + 校验
  dag/
    runner.py            # 包装 runtime.py，注入节点回调
    nodes.py             # 每个节点输入 / 输出绑定
  evidence/
    pack.py              # Evidence Pack 落盘
  reports/
    final_report.py      # customizations.report_export_md
  public/
    index.html
    styles.css
    app.js
  runs/<run_id>/
    uploads/*.csv
    evidence/*.json
    outputs/<schema_id>.json
    final_report.md
  skill_ref/             # symlink 或拷贝 build/market_insight_skill 的快照
```

`skill_ref/` 是 build 产物的只读拷贝，确保运行版本可追溯；版本号取 `build/market_insight_skill/skill.yaml` 中的 `version`。

## 3. 数据流

```mermaid
graph LR
  F[表单 + CSV] --> V[csv_io/loader.py<br/>schema 校验]
  V --> E[evidence/pack.py<br/>Evidence Pack 落盘]
  E --> D[dag/runner.py<br/>按 DAG 拓扑]
  D --> R[rules/*.py<br/>规则计算]
  R --> O[outputs/<schema_id>.json]
  O --> A[/api/run/<run_id>/status<br/>前端轮询]
  A --> U[SPA 渲染卡片]
  O --> M[reports/final_report.py]
  M --> X[final_report.md]
```

LLM 在本应用中**只**承担两个职责：

1. 在 `analyze_hot_product_genes` 中把 TOP300 商品的「材质 / 功能 / 风格 / 场景 / 主要卖点」做归类（不发明数据）。
2. 在 `collect_reviews_qa` 中把评价文本做痛点分类（不发明数据）。

LLM 输出必须经过 schema 校验；任何字段越界或编造数字直接 fail。

## 4. 接口契约

### 4.1 表单提交

`POST /api/run` → 返回 `run_id`，落盘 `runs/<run_id>/scope.json`。

### 4.2 CSV 上传

`POST /api/run/<run_id>/upload/<data_requirements_id>` → multipart CSV。
服务端按 `csv_io/schemas.py` 校验；通过则落盘 + 生成 Evidence Pack；失败返回字段级错误。

### 4.3 节点驱动

`POST /api/run/<run_id>/advance` → DAG runner 计算下一个 ready 节点；返回节点状态机变更。
`GET /api/run/<run_id>/status` → 完整节点状态 + 各表 schema 输出路径。

### 4.4 报告导出

`POST /api/run/<run_id>/report` → 生成 `final_report.md`，返回下载链接。

## 5. 规则引擎实现约束

- 全部纯函数。输入：dict + run 上下文；输出：`{rule_id, label, supporting_metrics, evidence_ids}`。
- 阈值常量直接从 `skill_ref/eval_rules.yaml` 解析加载。代码中**不**硬编码阈值数值。
- 规则越线判定与档位判定属于纯计算，不允许调用 LLM。
- 缺数据维度需在 `supporting_metrics` 中标记 `null`，并触发上层 `degraded_dimensions`。

## 6. DAG runner 复用

复用 `src/doc_to_skill/runtime.py`，按节点 type 注入回调：

| node type | 回调实现 |
| --- | --- |
| `form_collect` | 读 `scope.json` |
| `data_collect` | 读 `uploads/<data_requirements_id>.csv` 并生成 Evidence Pack |
| `compute_and_llm_extract` | rules + 受限 LLM 归类（仅文本字段） |
| `compute` | rules only |
| `multi_source_analysis` | rules + 跨表 join |
| `external_research` | 仅 CSV（v1 关闭浏览器路径） |
| `scoring` | `rules/opportunity_score.py` |
| `business_plan_generation` | 模板填充 + 受限 LLM 文案 |

## 7. 与 app_generation 链路对齐

- `tasks/current/prd.md` 由 `growth_dev/team/app_generation.py` 消费派生 acceptance / coverage / TDD / slices。
- 标准段交付物（SPA shell + DAG runner 绑定）走 deterministic fallback 模板。
- 定制段交付物（`customizations[]` 8 项）走 codex executor，按 `docs/app_generation_agent_bridge_spec.md` 的 `patch_app` 契约打补丁。

## 8. 不引入的依赖

- 不引入数据库、缓存、消息队列。
- 不引入 React / Vue / Vite / 任何 bundler。
- 不引入 Selenium / Playwright / Puppeteer。
- 不引入电商平台 SDK。

## 9. 版本与可追溯

- `runs/<run_id>/meta.json` 记录 `skill_version / app_version / scope / created_at`。
- 任意结论可通过 `evidence_ids` 反向追到 `evidence/*.json`，再到具体上传 CSV 行。