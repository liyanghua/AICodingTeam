# 受控递归改进白皮书

**主题：AI-coding team 与经营增长 OS 如何借鉴 RSI 思想，构建工程自改进与策略自改进双循环**  
**版本：v1.0**  
**日期：2026-06-07**

---

## 0. 执行摘要

Anthropic 在《When AI builds itself》中讨论的 RSI（Recursive Self-Improvement）核心不是一个玄学概念，而是一个非常工程化的正反馈结构：AI 系统开始参与 AI 系统自身的研发，先加速代码、实验、测试、优化、评估等可执行环节，再逐步逼近研究判断和方向选择。Anthropic 明确指出，full recursive self-improvement 尚未到来，也并非必然，但 AI 已经显著加速 AI 开发流程。[^anthropic-rsi]

对你的系统而言，最值得借鉴的不是“AI 完全自治”，而是把 RSI 改造成一个**受控递归改进系统**：

> 目标定义 → Agent 执行 → 结果评估 → 错误归因 → 策略/Skill/流程改写 → 验证集通过 → 小流量发布 → 回写 Registry/Wiki → 下一轮执行。

这套思想可以抽象出两类系统：

1. **工程自改进系统**：让 AI-coding team 越交付越强。
2. **策略自改进系统**：让经营增长 OS 的策略、Skill、行业 know-how、企业 know-how 越执行越强。

二者共享同一套底层能力：GoalSpec、Context Compiler、Agent Runtime、Evidence Pack、Eval Platform、Auto-Research、SkillOpt、Registry/Wiki、Replay/Gate。

其中，Auto-Research 负责**参数寻优**，SkillOpt 负责**Skill / SOP / 策略文本寻优**。Microsoft Research 的 SkillOpt 将自然语言 Skill 文档视为 frozen agent 的可训练外部状态，通过 rollout、reflection、bounded edit、held-out validation gate 来稳定优化 Skill，并且部署时不增加额外推理调用。[^skillopt-ms][^skillopt-site]

---

## 1. 统一公式：Controlled Recursive Improvement Loop

### 1.1 RSI 的业务化改写

原始 RSI：

```text
AI improves AI development
→ stronger AI
→ stronger AI improves AI development faster
```

你的业务化版本：

```text
AI improves engineering production
→ stronger AI-coding team
→ stronger AI-coding team improves software delivery faster

AI improves business strategy execution
→ stronger Growth OS
→ stronger Growth OS improves strategy, skill, and know-how faster
```

更准确的命名应该是：

> **Controlled Recursive Improvement System**  
> 受控递归改进系统。

它不是让 AI 直接改生产系统，而是让 AI 在受限空间内提出改进，再通过数据、评测、回放、灰度和人工 Gate 决定是否发布。

### 1.2 统一公式

```text
Self-Improvement Loop =
GoalSpec
→ Context Compilation
→ Strategy / Skill Selection
→ Agent Runtime Execution
→ Evidence Pack Recording
→ Outcome Evaluation
→ Failure Attribution
→ Optimizer Proposal
→ Validation Gate
→ Registry / Wiki Update
→ Next Run
```

### 1.3 七个基本原则

| 原则 | 含义 | 为什么重要 |
|---|---|---|
| 可观测 | 每次 Agent 执行都留下输入、输出、工具调用、日志、证据 | 没有过程数据，就无法归因 |
| 可评估 | 每次结果都能被业务指标、工程指标或 Judge 打分 | 没有分数，就无法优化 |
| 可回放 | 历史任务可以用新旧策略重复执行 | 避免凭感觉升级 |
| 可审核 | 关键策略变更进入人工 Review | 控制业务风险和工程风险 |
| 可灰度 | 新 Skill / 新策略先小范围上线 | 防止全量事故 |
| 可回滚 | 新版本失败时回退旧版本 | 保障生产稳定性 |
| 可沉淀 | 成功/失败都进入 Registry/Wiki | 形成长期复利资产 |

### 1.4 不优化模型权重，优先优化外部可控资产

在当前阶段，不建议把“自改进”理解为训练大模型权重。你真正应该优化的是外部可控资产：

```text
Prompt
Skill.md
Agents.md
PRD Template
Tech Spec Template
Review Checklist
Strategy Bundle
Opportunity Scoring Formula
Strategy Arbiter Rule
Knowledge Wiki
Failure Pattern Library
```

这与 SkillOpt 的思想一致：把自然语言 Skill 当作可训练的外部状态，而不是直接修改模型本体。[^skillopt-ms]

---

## 2. 两类系统之一：工程自改进系统

### 2.1 定义

**工程自改进系统**是让 AI-coding team 通过每一次真实软件交付，持续优化它的需求理解、架构设计、代码生成、测试、Review、发布和回滚能力。

普通 AI-coding team：

```text
需求 → 产品 Agent → 架构 Agent → Coding Agent → Test Agent → Review Agent → Deploy Agent → 代码交付
```

自改进版 AI-coding team：

```text
需求 → Agent Team 交付代码
→ 记录全过程 Evidence
→ 工程 Eval 打分
→ 失败归因
→ 优化 Agents.md / PRD 模板 / Tech Spec / Coding Skill / Review Skill / Test Skill
→ 验证通过
→ 进入 Skill Registry
→ 下一轮交付更好
```

### 2.2 可优化对象

| 层级 | 可优化对象 | 示例 |
|---|---|---|
| 需求层 | PRD 模板 | 用户故事、边界条件、异常状态、验收标准 |
| 架构层 | Tech Spec 模板 | 模块边界、接口契约、数据模型、状态机 |
| 编码层 | Coding Skill | 文件修改规范、错误处理、分层约束 |
| 测试层 | TDD Skill | 单测、集成测试、Mock、回归用例 |
| Review 层 | Review Checklist | 安全、性能、可维护性、数据一致性 |
| 发布层 | Release Playbook | 灰度、迁移脚本、监控、回滚 |
| 编排层 | Agents.md | Agent 分工、交接规则、升级条件 |

### 2.3 工程自改进架构

```text
Engineering Improvement System

1. Task Intake
   - Feature / Bug / Refactor / Infra / UI

2. Code Context Compiler
   - Repo structure
   - Relevant files
   - Architecture constraints
   - Historical PR / bug / review comments

3. AI-Coding Agent Runtime
   - Product Agent / Architect Agent / Coding Agent
   - Test Agent / Review Agent / Release Agent

4. Engineering Evidence Pack
   - Prompt / context / plan
   - Code diff / test result / build logs
   - Review comments / runtime errors

5. Engineering Eval
   - PRD adherence / architecture compliance
   - Test adequacy / maintainability / production risk

6. Skill / Spec Optimizer
   - Agents.md optimization
   - Coding Skill / Review Skill / Test Skill optimization

7. Registry
   - Skill Registry / Spec Template Registry
   - Failure Pattern Library / Architecture Decision Record
```

### 2.4 工程数据采集

最低需要采集四类数据：

| 数据类型 | 字段示例 | 用途 |
|---|---|---|
| Task Data | task_id、任务类型、复杂度、模块、需求来源 | 任务归类和样本分桶 |
| Context Data | PRD、Tech Spec、相关代码、历史 Bug、架构约束 | 复现 Agent 的输入条件 |
| Execution Data | Agent 输出、工具调用、代码 diff、测试日志、review comment | 定位失败原因 |
| Outcome Data | 测试通过率、review 次数、bug 回流、上线异常、回滚 | 判断真实工程质量 |

### 2.5 工程 Eval Gate

Hard Gate：

```text
- 测试必须通过
- 类型检查必须通过
- lint 必须通过
- 不允许绕过安全约束
- 不允许修改未授权文件
- 不允许删除关键测试
- 不允许引入不可回滚迁移
```

Soft Score：

```text
EngineeringScore =
0.25 * RequirementCoverage
+ 0.20 * ArchitectureCompliance
+ 0.20 * TestAdequacy
+ 0.15 * Maintainability
+ 0.10 * ProductionSafety
+ 0.10 * DeliveryEfficiency
```

### 2.6 工程自改进的最小闭环

```text
历史 20 个开发任务
→ 用当前 Agents.md / Coding Skill 跑一次
→ 得到 baseline
→ Optimizer 生成候选 Skill Patch
→ 在相同任务集 + held-out 任务集回放
→ 只有当 EngineeringScore 提升且 Hard Gate 通过，才接受
→ 发布到 Skill Registry
```

---

## 3. 两类系统之二：策略自改进系统

### 3.1 定义

**策略自改进系统**是让经营增长 OS 在商机洞察、商品诊断、内容策划、素材生成、投放优化、指标回采等场景中，持续优化策略参数、业务 Skill、行业 know-how 和企业 know-how。

普通经营 Agent：

```text
业务问题 → 检索知识库 → 生成建议 → 执行 → 输出报告
```

自改进版经营增长 OS：

```text
业务目标 → 编译企业上下文 + 行业上下文
→ 生成 Strategy Bundle
→ Agent Runtime 执行
→ Evidence Pack 记录
→ 回采业务结果
→ Eval / 归因
→ Auto-Research 优化参数
→ SkillOpt 优化 Skill / SOP
→ Strategy Wiki / Skill Registry 回写
→ 下一轮策略更强
```

### 3.2 可优化对象

| 类型 | 可优化对象 | 示例 |
|---|---|---|
| 策略参数 | Auto-Research 参数 | 关键词扩展数量、采样深度、聚类阈值、机会评分权重 |
| 策略文档 | Strategy Skill / SOP | 商机洞察 SOP、内容策划 SOP、投流诊断 SOP |
| 执行 Skill | Agent Skill | 小红书采集、淘宝竞品分析、素材诊断、指标回采 |
| 决策规则 | Strategy Arbiter | 企业策略与行业策略的优先级、冲突处理规则 |
| 知识库 | Know-how Wiki | 行业打法、企业打法、失败模式、最佳实践 |

### 3.3 Auto-Research 与 SkillOpt 的分工

| 模块 | 优化对象 | 输入 | 输出 |
|---|---|---|---|
| Auto-Research | 参数、权重、阈值、策略组合 | 冻结数据、历史案例、Eval 分数 | 最优参数组合、评分权重、采样策略 |
| SkillOpt | Skill.md、SOP、Prompt、Checklist | scored rollouts、失败样本、成功样本 | bounded skill edit、候选 Skill 版本 |
| Eval Gate | 是否接受变更 | held-out 案例、业务指标、风险规则 | accept / reject / needs_review |
| Strategy Wiki | 解释和沉淀 | 参数变化、Skill 变化、业务结果 | 策略知识、失败模式、适用条件 |

关键关系：

```text
Auto-Research 发现参数规律
→ SkillOpt 将规律固化为可执行方法论
→ Eval Gate 验证是否真的提升
→ Strategy Wiki 记录为什么提升
→ Runtime 使用新版本执行
```

### 3.4 策略自改进架构

```text
Growth OS Strategy Improvement System

1. Business GoalSpec
   - GMV / ROI / CTR / CVR / Opportunity Quality

2. Business Context Compiler
   - 企业数据：商品 / 订单 / 流量 / 客服 / 素材 / 供应链
   - 行业数据：趋势 / 竞品 / 平台榜单 / 内容平台
   - 企业 know-how：品牌定位 / 历史打法 / 供应链约束
   - 行业 know-how：通用 SOP / 行业策略 / 案例库

3. Strategy Compiler
   - 行业策略召回 / 企业策略召回
   - 冲突检测 / 策略仲裁 / Strategy Bundle 生成

4. Agent Runtime / OpenClaw / AgentBox
   - 数据采集 / 商机洞察 / 内容策划
   - 素材生成 / 投放执行 / 指标回采

5. Business Evidence Pack
   - 输入证据 / 内容证据 / 竞品证据
   - 执行证据 / 结果证据

6. Business Eval / Judge
   - 机会卡质量 / 策略命中率 / ROI uplift
   - CTR-CVR uplift / 归因可信度 / 执行可落地性

7. Optimizer Layer
   - Auto-Research：参数寻优
   - SkillOpt：Skill / SOP 寻优

8. Validation Gate
   - 历史案例回放 / A-B 测试 / 小流量灰度
   - 人工审核 / 风险门槛

9. Registry / Wiki
   - Strategy Registry / Skill Registry
   - Industry Know-how Wiki / Enterprise Know-how Wiki
   - Failure Pattern Library
```

### 3.5 策略评分体系

```text
Business Improvement Score =
0.20 * EvidenceScore
+ 0.20 * StrategyFitScore
+ 0.20 * ExecutionFeasibilityScore
+ 0.20 * OutcomeLiftScore
+ 0.20 * ReusabilityScore
```

解释：

| 指标 | 含义 |
|---|---|
| EvidenceScore | 是否有足够搜索、评论、竞品、内容、转化证据 |
| StrategyFitScore | 是否符合企业定位、供应链能力、价格带、渠道特征 |
| ExecutionFeasibilityScore | 是否能被 Agent / 人实际执行 |
| OutcomeLiftScore | 是否带来 CTR、CVR、ROI、GMV 等结果提升 |
| ReusabilityScore | 是否可沉淀为行业/企业复用策略 |

---

## 4. 两类系统的统一架构

### 4.1 统一底座

工程自改进和策略自改进本质上共享同一套架构，只是目标、上下文、评估指标和优化对象不同。

```text
Unified Recursive Improvement Infrastructure

GoalSpec
→ Context Compiler
→ Strategy / Skill Compiler
→ Agent Runtime
→ Evidence Pack
→ Eval Platform
→ Optimizer Layer
→ Validation / Release Gate
→ Registry / Wiki

Shared capabilities:
- GoalSpec: engineering goals + business goals
- Context Compiler: code + business + data + know-how context
- Agent Runtime: Coding / Review / Data / Insight / Execution Agents
- Evidence Pack: diff / tests / logs / data evidence / outcome evidence
- Eval Platform: engineering eval + business eval + risk eval
- Optimizer Layer: Auto-Research + SkillOpt + template optimizer
- Release Gate: replay + held-out validation + A-B + human review + rollback
- Registry/Wiki: Skill / Strategy / Template / Failure Pattern / Decision Records
```

### 4.2 统一对象模型

```text
GoalSpec {
  goal_id
  domain: engineering | business
  target_metrics
  constraints
  risk_level
  validation_method
}

ContextPack {
  context_id
  goal_id
  data_refs
  code_refs
  knowledge_refs
  historical_cases
  constraints
}

Skill {
  skill_id
  domain
  version
  instruction
  input_schema
  output_schema
  allowed_tools
  risk_rules
  eval_cases
  status: draft | candidate | validated | production | deprecated
}

AgentRun {
  run_id
  goal_spec_id
  context_pack_id
  skill_version
  strategy_bundle_id
  tool_calls
  output_artifacts
  evidence_pack_id
  outcome_metrics
  failure_events
}

EvidencePack {
  evidence_id
  run_id
  input_evidence
  process_evidence
  output_evidence
  outcome_evidence
  screenshots
  logs
  citations
}

EvalResult {
  eval_id
  run_id
  metric_scores
  hard_gate_passed
  failure_reasons
  judge_notes
  recommendation
}

OptimizerProposal {
  proposal_id
  target_type: skill | strategy | parameter | template
  current_version
  proposed_patch
  reason
  expected_gain
  validation_result
  status: accepted | rejected | needs_review
}
```

### 4.3 统一流程

```text
1. 用户或系统提出 GoalSpec
2. Context Compiler 编译代码/业务/数据/know-how 上下文
3. Strategy / Skill Compiler 选择策略和 Skill 版本
4. Agent Runtime 执行任务
5. Evidence Recorder 生成 Evidence Pack
6. Eval Platform 打分并归因失败
7. Auto-Research 优化参数，SkillOpt 优化 Skill 文档
8. Validation Gate 进行回放、验证、灰度和人工审核
9. 通过后写入 Registry / Wiki
10. 下一轮执行自动使用更优版本
```

---

## 5. 基础设施、数据、Runtime、Know-how 的融入方式

### 5.1 基础设施层

| 模块 | 作用 |
|---|---|
| Evidence Lake | 存储所有 Agent 执行证据、日志、截图、输出、结果 |
| Eval Platform | 对工程结果和业务结果统一评分 |
| Replay Engine | 用历史任务回放新旧 Skill / 策略 |
| Skill Registry | 管理 Skill 版本、状态、适用条件、风险规则 |
| Strategy Registry | 管理行业策略、企业策略、冲突规则、适用边界 |
| Experiment Registry | 管理参数实验、A/B 实验、灰度结果 |
| Failure Pattern Library | 沉淀失败模式、错误归因和规避规则 |

### 5.2 数据层

| 数据类型 | 内容 | 用途 |
|---|---|---|
| Grounding Data | 商品、订单、流量、投放、客服、素材、竞品、评论、搜索趋势 | 生成判断 |
| Execution Data | Agent 输入输出、工具调用、Skill 版本、执行日志、截图 | 复盘过程 |
| Outcome Data | ROI、GMV、CTR、CVR、加购、收藏、询单、退款、复购 | 评估结果 |
| Learning Data | 成功案例、失败案例、A/B 结果、人工审核意见、策略冲突记录 | 优化策略和 Skill |

完整链路：

```text
Grounding Data → 生成策略
Execution Data → 记录执行
Outcome Data → 判断效果
Learning Data → 优化策略和 Skill
```

### 5.3 Agent Runtime 层

Runtime 不能只是执行器，它要成为：

```text
任务执行器 + 证据记录器 + 结果回采器 + 优化触发器
```

OpenClaw / AgentBox 可以这样定位：

| 组件 | 职责 |
|---|---|
| OpenClaw | 本地电脑、浏览器、平台操作 Runtime |
| AgentBox | 企业侧边缘执行节点 |
| Skill Engine | 执行版本化 Skill |
| Evidence Recorder | 记录截图、DOM、API response、日志、输出物 |
| Replay Engine | 用历史任务复跑新旧版本 |
| Eval Hook | 每次执行后触发评分 |
| Risk Guard | 权限、敏感动作、人工确认、回滚 |

### 5.4 行业 + 企业 Know-how 层

行业 know-how 解决：

```text
这个行业通常怎么做？
有哪些通用打法？
哪些策略跨企业有效？
哪些机会判断维度最重要？
哪些失败模式高频出现？
```

企业 know-how 解决：

```text
这家公司具体适合怎么做？
它的供应链能做什么？
品牌调性是什么？
历史上什么打法有效？
哪些价格带不能碰？
哪些素材风格转化好？
哪些平台账号权重高？
```

最佳融合方式：

```text
企业策略优先
行业策略显性补充
策略仲裁器统一裁决
Eval / 实验结果持续校正
```

策略仲裁器示例：

```text
StrategyArbiterScore =
0.30 * EnterpriseEvidenceStrength
+ 0.20 * IndustryGeneralizationScore
+ 0.20 * HistoricalOutcomeScore
+ 0.15 * ExecutionFeasibilityScore
+ 0.10 * RiskScore
+ 0.05 * FreshnessScore
```

输出结构：

```text
Strategy Bundle {
  selected_strategy
  enterprise_rules_used
  industry_rules_used
  conflict_resolved
  confidence
  required_evidence
  execution_constraints
  validation_plan
}
```

---

## 6. 落地建议和节奏

### Phase 0：定义对象和边界，1 周

目标：把“自改进”从概念变成对象模型。

交付物：

```text
GoalSpec Schema
ContextPack Schema
Skill Schema
StrategyBundle Schema
EvidencePack Schema
EvalResult Schema
OptimizerProposal Schema
Registry 状态机
```

验收标准：

```text
- 每次 AgentRun 都能关联 GoalSpec、SkillVersion、EvidencePack、EvalResult
- 每个 Skill 都有版本、状态、输入输出、工具权限、风险规则
- 每个策略变更都能追踪 proposal、验证结果和发布状态
```

### Phase 1：先做可观测，2-3 周

目标：所有 Agent 执行都能留下完整证据。

工程侧先接：

```text
- PRD 生成任务
- Tech Spec 生成任务
- 小型代码修改任务
- Review / Test 任务
```

业务侧先接：

```text
- 商机洞察
- 商品诊断
- 竞品分析
- 内容策划
```

交付物：

```text
AgentRun Logger
EvidencePack Builder
Run Dashboard
Skill Version Tracker
Outcome Metric Collector
```

### Phase 2：做离线 Eval 和 Replay，2-4 周

目标：可以用历史任务复跑新旧版本，建立 baseline。

工程侧：

```text
历史 20 个开发任务
→ 评估当前 Agents.md / Coding Skill / Review Skill
→ 输出 EngineeringScore baseline
```

业务侧：

```text
历史 30 个机会洞察/商品诊断案例
→ 评估当前策略参数和 Skill
→ 输出 BusinessScore baseline
```

交付物：

```text
Replay Engine
Eval Dataset
Engineering Eval Rubric
Business Eval Rubric
Baseline Report
```

### Phase 3：引入 Auto-Research，3-5 周

目标：先优化参数，不直接改 Skill。

业务侧优先参数：

```text
关键词扩展数量
平台采样深度
聚类阈值
评论痛点权重
搜索热度权重
竞品同质化权重
机会卡评分公式
```

工程侧可选参数：

```text
上下文召回 top_k
测试生成数量
相关文件选择阈值
Review checklist 权重
```

交付物：

```text
Parameter Search Runner
Experiment Registry
Parameter Leaderboard
BestConfig Exporter
```

### Phase 4：引入 SkillOpt，3-6 周

目标：优化 Skill.md / SOP / Checklist，但必须 bounded edit + validation gate。

候选 Skill：

```text
商机洞察 Skill
竞品分析 Skill
内容策划 Skill
商品诊断 Skill
Coding Skill
Review Skill
TDD Skill
PRD 生成 Skill
```

更新规则：

```text
- 每次只允许 add / delete / replace 小范围修改
- 必须说明修改原因
- 必须在训练样本和 held-out 样本上验证
- 只接受严格提升且不触发 Hard Gate 的版本
- rejected edits 进入 rejected buffer
```

交付物：

```text
SkillOpt Runner
Skill Patch Format
Held-out Validation Set
Skill Version Diff Viewer
Skill Promotion Workflow
```

### Phase 5：上线灰度自改进，持续迭代

目标：新策略和新 Skill 小范围自动推荐，人工审核后进入生产。

流程：

```text
Optimizer 生成 Candidate Skill / Strategy
→ 离线 Eval 通过
→ 小流量灰度
→ 人工审核
→ 生产发布
→ 监控回滚
```

交付物：

```text
Canary Release
Rollback Policy
Risk Dashboard
Strategy Decision Record
Skill Production Registry
```

---

## 7. 最小可行产品 MVP 建议

### 7.1 MVP 选择

建议 MVP 不要同时铺开所有场景，先选两个：

```text
工程侧：PRD → Tech Spec → 代码修改 → Test → Review 的小型 AI-coding 闭环
业务侧：商机洞察 → 机会卡 → 评估 → 参数寻优 → Skill 改写闭环
```

### 7.2 MVP 架构

```text
MVP Flow

GoalSpec
→ Context Compiler
→ Agent Runtime
→ Evidence Pack
→ Eval / Replay
→ Auto-Research + SkillOpt
→ Registry / Wiki
```

### 7.3 MVP 成功指标

工程侧：

```text
- 20 个历史开发任务可回放
- EngineeringScore baseline 建立
- 新 Coding Skill 至少提升 10%
- Review 修改次数下降
- 测试通过率不下降
```

业务侧：

```text
- 30 个历史商机洞察案例可回放
- 机会卡质量 baseline 建立
- Auto-Research 找到更优参数组合
- 新 Skill 在 held-out 案例上严格提升
- 输出可解释 Strategy Decision Record
```

---

## 8. 关键风险与治理

| 风险 | 表现 | 治理方式 |
|---|---|---|
| 自嗨优化 | Judge 分数提升，但业务结果不提升 | 引入 Outcome Data 和 A/B 测试 |
| 策略漂移 | Skill 越改越偏离企业定位 | 企业约束 Hard Gate |
| 过拟合历史案例 | 历史集提升，新案例下降 | held-out validation + 新鲜样本 |
| 证据污染 | Agent 引用错误或低质量证据 | Evidence Quality Gate |
| 运行时风险 | 自动执行平台动作导致损失 | Risk Guard + HITL + 回滚 |
| Skill 技术债 | Skill 越来越多、冲突越来越多 | Skill Registry + 依赖图 + 废弃机制 |
| 组织不可控 | 无人知道为什么策略升级 | Strategy Decision Record |

---

## 9. 结论

你应该把 RSI 思想转化为一个更适合商业落地的系统：

> **Business & Engineering Recursive Improvement Layer**

它不是让 AI 自己失控地修改系统，而是用工程化方式让 AI 持续改进两个生产函数：

```text
Engineering Production Function：
让 AI-coding team 越交付越强。

Business Strategy Production Function：
让经营增长 OS 的策略、Skill、know-how 越执行越强。
```

最终系统的关键不是“大模型更聪明”，而是：

```text
数据可采集
过程可记录
结果可评估
错误可归因
Skill 可优化
策略可验证
知识可沉淀
发布可治理
```

这套系统一旦跑通，会形成你的长期壁垒：

1. **工程壁垒**：AI-coding team 的交付能力不断复利。
2. **策略壁垒**：行业与企业 know-how 不断复利。
3. **数据壁垒**：每次执行都产生可学习样本。
4. **组织壁垒**：最佳实践不再只存在于专家脑子里，而是进入 Skill Registry 和 Strategy Wiki。

---

## 附录 A：建议文件结构

```text
recursive-improvement-os/
├── README.md
├── docs/
│   ├── 00_whitepaper.md
│   ├── 01_architecture.md
│   ├── 02_engineering_improvement.md
│   ├── 03_strategy_improvement.md
│   ├── 04_eval_system.md
│   ├── 05_skill_registry.md
│   └── 06_rollout_plan.md
├── schemas/
│   ├── goal_spec.schema.json
│   ├── context_pack.schema.json
│   ├── skill.schema.json
│   ├── strategy_bundle.schema.json
│   ├── evidence_pack.schema.json
│   ├── eval_result.schema.json
│   └── optimizer_proposal.schema.json
├── skills/
│   ├── engineering/
│   │   ├── coding.skill.md
│   │   ├── review.skill.md
│   │   └── tdd.skill.md
│   └── business/
│       ├── opportunity_insight.skill.md
│       ├── competitor_analysis.skill.md
│       └── content_planning.skill.md
├── evals/
│   ├── engineering_cases/
│   ├── business_cases/
│   ├── rubrics/
│   └── reports/
├── experiments/
│   ├── auto_research/
│   └── skillopt/
└── registry/
    ├── skill_registry.json
    ├── strategy_registry.json
    ├── experiment_registry.json
    └── failure_patterns.md
```

## 附录 B：参考资料

[^anthropic-rsi]: Anthropic Institute, *When AI builds itself: Our progress toward recursive self-improvement, and its implications*, https://www.anthropic.com/institute/recursive-self-improvement

[^skillopt-ms]: Microsoft Research, *SkillOpt: Executive Strategy for Self-Evolving Agent Skills*, https://www.microsoft.com/en-us/research/publication/skillopt-executive-strategy-for-self-evolving-agent-skills/

[^skillopt-site]: Microsoft SkillOpt project page, https://microsoft.github.io/SkillOpt/
