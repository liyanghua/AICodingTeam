# Coding Prompt: 市场分析洞察报告生成器

> 本文件是 Code Agent（codex executor）执行 PRD 时的约束清单。所有约束等价于硬性 invariants：违反任一条视为生成失败，触发评审拒绝。

## 1. 数据来源约束

- 严禁连接真实电商 API（淘宝 / 天猫 / 拼多多 / 京东 / 抖音 / 小红书 / 任何官方或非官方接口）。
- 严禁安装 / 使用电商平台 SDK、模拟登录工具、指纹欺骗工具、浏览器自动化工具。
- 所有事实数字（GMV、销量、买家、增长率、评分、占比）必须来自上传 CSV 或本地规则引擎计算。
- v1 关闭浏览器抓取路径；`collect_cross_platform_trends` 仅消费 CSV。

## 2. LLM 使用约束

- LLM 仅承担两件事：① TOP300 商品的「材质 / 功能 / 风格 / 场景 / 主要卖点」分类标签化；② 评价/问大家文本的痛点分类。
- LLM 严禁输出数值字段。任一 LLM 输出经过 schema 校验，越界字段直接 fail。
- 规则越线判定与档位判定**不**调用 LLM，纯代码计算。

## 3. Skill 引用约束

- 严禁重新设计 schema。所有输出文件 schema 取自 `skill_ref/output_schemas/*.json`。
- 严禁重新设定阈值。阈值常量从 `skill_ref/eval_rules.yaml` 解析加载，不得在代码中硬编码数值。
- 严禁在代码中扩展 DAG 节点或修改依赖。DAG 拓扑取自 `skill_ref/workflow.dag.yaml`。
- 严禁绕过 Evidence Pack。每次 CSV 落地都必须生成 Evidence Pack；每条结论必须绑定 evidence_ids。

## 4. 定制段约束

- 仅实现 PRD 文末 `customizations[]` 中列出的 8 项。
- 新增任何定制项前，必须先更新 PRD 并通过评审；不允许在代码中直接增加 PRD 未声明的定制行为。
- 每条定制项必须能映射到「位置 / 行为 / 验收」三件套；验收能被 TDD 用例覆盖。

## 5. 文件与目录约束

- 应用代码生成在 `generated_apps/market-insight-report-app/`。
- `skill_ref/` 为只读 Skill 制品快照；代码不得修改 `skill_ref/` 内容。
- 上传 CSV 落盘 `runs/<run_id>/uploads/`；Evidence Pack 落盘 `runs/<run_id>/evidence/`；输出 schema JSON 落盘 `runs/<run_id>/outputs/`。
- 不引入数据库、消息队列、缓存层。

## 6. 安全约束

- 不读取用户 home 目录或 SSH 密钥等任何敏感路径。
- 不写入工作区以外的目录。
- 不发起出网请求；构建时不允许新增 `requests / httpx / aiohttp` 等出网客户端依赖（FastAPI/uvicorn 仅作 HTTP 服务，非客户端）。

## 7. 失败可见性

- 任一节点 `failed` 时必须在前端给出阻断对话框，列出缺失数据 / 字段。
- 任一节点 `degraded` 时必须在前端展示顶部横幅，说明缺失维度。
- `final_report.md` 的导出按钮在 `score_opportunities` 未 `ok` 时灰显。

## 8. 验收门禁

- PRD §8 全部条目通过。
- `eval.md` 全部用例通过。
- 4 项 `hard_requirements` 必须 100% 满足；任一不满足 → 整体 fail。

## 9. 与方法论的对齐

- 实现行为时必须按 [`docs/business_doc_to_prd_method.md`](../../docs/business_doc_to_prd_method.md) 的「标准段 / 定制段」分类清楚每段代码归属，方便后续模板化抽取。
- 标准段代码倾向于由模板生成；本次 Code Agent 优先完成定制段，并确保标准段在 deterministic fallback 模板下可重生。