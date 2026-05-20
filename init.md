 **AI-native 工程生产线构建说明书**：

输入业务需求文档；系统自动拆解成 PRD、Tech Spec、架构图、AGENTS.md、UI 规范、任务包；再交给 AI-coding 工具实现；之后进入代码 Review、TDD、CI、部署、人审发布。
先做“单个统筹 Agent + 多个确定性关卡 + AI coding 执行器”的流水线。**

---

# 一、方案：Hermes 做“工程统筹 Agent”，AI coding 工具做“执行器”

Hermes Agent 的优势是长期记忆、Skill 沉淀、自我改进、跨 Session 记忆和任务经验积累；官方文档也强调它不是单纯 coding copilot，而是可长期运行、会从经验中创建和改进 skills 的 autonomous agent。([Hermes Agent][1])

所以它最适合做：

```text
需求统筹 / 任务拆解 / Skill 选择 / 任务状态管理 / 复盘沉淀
```

而真正改代码，可以交给：

```text
Codex CLI / Claude Code / Cursor / OpenCode / Aider / Goose
```

OpenAI Codex CLI 本身就是面向本地代码库的 coding agent，可以读代码、改代码、运行命令，并带有审批模式；OpenAI 最新 Codex 模型也明确面向 long-horizon agentic coding tasks。([OpenAI Help Center][2]) ([OpenAI 开发者][3])

Claude Code 也已经支持 subagents、slash commands、hooks、GitHub Actions 等能力，适合做 Review、测试、Issue-to-PR 等工程自动化。([Claude API Docs][4])

---

# 二、整体架构

```text
输入业务需求
   ↓
Hermes Orchestrator Agent
   ↓
需求理解 / 拆解 / 风险判断 / 输出任务计划
   ↓
产物生成层
   ├── Product Agent：PRD / 用户故事 / 验收标准
   ├── Architect Agent：技术架构 / 数据模型 / 接口设计
   ├── UX Agent：页面结构 / UI 交互规范 / 状态机
   ├── QA Agent：TDD / 测试用例 / 验收脚本
   ├── Coding Agent：代码实现
   ├── Review Agent：代码 Review / 安全 / 可维护性
   └── Deploy Agent：CI/CD / 部署 / 回滚检查
   ↓
工程仓库
   ├── docs/
   ├── AGENTS.md
   ├── tasks/
   ├── tests/
   ├── src/
   └── .github/workflows/
   ↓
PR / CI / Test / Review / Deploy
   ↓
结果复盘 → Hermes Memory / Skill Registry
```

核心不是“让 7 个 Agent 自由聊天”，而是：
**每个 Agent 只负责一个固定产物，每个产物都有 Schema，每个阶段都有 Gate。**

---

# 三、定义 6 个核心 Agent

## 1. Orchestrator Agent：统筹 Agent

这是 Hermes 的主角色。

职责：

```text
1. 接收用户的业务需求
2. 判断需求类型：新功能 / 改版 / Bug / 数据链路 / UI 页面 / Agent 能力
3. 生成任务分解树
4. 选择需要调用哪些 Agent
5. 检查每个 Agent 产物是否齐全
6. 决定是否进入 AI coding
7. 记录任务结果和经验
```

它不直接写大量代码，而是负责：

```text
需求 → 任务 → 文档 → 代码任务 → Review → 测试 → 部署 → 复盘
```

---

## 2. Product Agent：产品 Agent

输入：

```text
业务需求文档
已有产品背景
用户角色
业务目标
```

输出：

```text
docs/prd.md
docs/user_stories.md
docs/acceptance_criteria.md
```

核心产物结构：

```markdown
# PRD

## 1. 背景
## 2. 目标用户
## 3. 业务目标
## 4. 使用场景
## 5. 核心流程
## 6. 功能范围
## 7. 非功能范围
## 8. 验收标准
## 9. 风险与依赖
```

---

## 3. Architect Agent：架构 Agent

输入：

```text
PRD
现有代码结构
数据库结构
已有 API
技术约束
```

输出：

```text
docs/tech_spec.md
docs/architecture.md
docs/data_model.md
docs/api_contract.md
docs/architecture_diagram.md
```

重点是把“业务需求”转成 AI coding 能理解的工程边界：

```text
改哪些模块
新增哪些表
新增哪些 API
影响哪些页面
哪些代码不能动
哪些兼容性必须保持
```

---

## 4. UX Agent：用户体验 Agent

输入：

```text
PRD
目标用户
页面现状
业务流程
```

输出：

```text
docs/ui_spec.md
docs/interaction_spec.md
docs/page_state_machine.md
```

经营增长OS里面，现在很多产品都是“业务专家工作台 / 操盘手工作台 / 内容策划台”，所以 UX Agent 特别重要。

它要输出：

```text
页面结构
信息架构
组件说明
状态流转
空状态
加载态
错误态
审批态
编辑态
多人协作态
```

---

## 5. Coding Agent：实现 Agent

输入：

```text
AGENTS.md
task.yaml
prd.md
tech_spec.md
ui_spec.md
eval.md
```

输出：

```text
代码变更
单元测试
集成测试
迁移脚本
README 更新
```

这里可以用 Codex CLI、Claude Code、Cursor、OpenCode 等。Codex 官方用例里也强调它适合生产系统里的可控代码修改、PR Review、Web 开发和复杂知识工作流。([OpenAI 开发者][5])

---

## 6. Review + QA + Deploy Agent

可以先合并成一个 **Guardian Agent**，不要一开始拆太细。

职责：

```text
1. 跑测试
2. 检查是否满足 PRD
3. 检查是否违反架构约束
4. 检查是否有安全风险
5. 检查是否有破坏性改动
6. 生成 Review 报告
7. 判断是否允许部署
```

Claude Code 的 hooks 可以在工具调用前后、用户提交 prompt、Session 开始/结束、Subagent 结束等节点触发脚本，非常适合做工程关卡。([Claude API Docs][6])

---

# 四、工程仓库应该长这样

所有需求都落到一个标准目录：

```text
repo/
├── AGENTS.md
├── docs/
│   ├── product/
│   │   ├── prd.md
│   │   ├── user_stories.md
│   │   └── acceptance_criteria.md
│   ├── architecture/
│   │   ├── tech_spec.md
│   │   ├── architecture.md
│   │   ├── api_contract.md
│   │   └── data_model.md
│   ├── ux/
│   │   ├── ui_spec.md
│   │   ├── interaction_spec.md
│   │   └── page_state_machine.md
│   └── eval/
│       ├── test_plan.md
│       ├── tdd_cases.md
│       └── review_checklist.md
├── tasks/
│   ├── task.yaml
│   ├── context.md
│   ├── implementation_plan.md
│   └── review_report.md
├── src/
├── tests/
├── scripts/
│   ├── run_eval.sh
│   ├── run_review.sh
│   └── deploy.sh
└── .github/
    └── workflows/
        ├── ci.yml
        ├── ai_review.yml
        └── deploy.yml
```

---

# 五、AGENTS.md 怎么写

AGENTS.md 不要写成大而全的公司制度。2026 年一篇针对 AGENTS.md 的研究发现，过多或不必要的仓库级上下文可能降低任务成功率并增加推理成本；它更适合写最小必要约束，而不是把所有知识都塞进去。([arXiv][7])

AGENTS.md 应该只写 8 类内容：

```markdown
# AGENTS.md

## 1. Product Goal

本项目是经营增长 OS 的 AI-native 工程工作台，用于把业务需求自动转成 PRD、技术方案、UI 规范、TDD、代码实现和部署流程。

## 2. Architecture Principles

- 后端 API 必须保持向后兼容。
- 新增数据模型必须有 migration。
- 不允许绕过 repository/service 分层直接访问数据库。
- 所有 Agent 产物必须写入 docs/ 或 tasks/。
- 任何自动部署前必须通过测试和 Review Gate。

## 3. File Ownership

- PRD 写入 docs/product/
- 技术方案写入 docs/architecture/
- UI 规范写入 docs/ux/
- 测试方案写入 docs/eval/
- 任务上下文写入 tasks/

## 4. Coding Rules

- 小步提交。
- 每次只完成一个 task.yaml 中定义的任务。
- 不允许无关重构。
- 不允许删除已有测试。
- 修改 API 必须同步更新 api_contract.md。

## 5. Testing Rules

- 新功能必须先补测试。
- Bug 修复必须有回归测试。
- UI 状态必须覆盖 loading / empty / error / success。
- Agent 输出必须有结构化验收标准。

## 6. Review Rules

Review 必须检查：
- 是否满足 PRD
- 是否符合架构约束
- 是否有安全风险
- 是否破坏已有接口
- 是否有测试覆盖

## 7. Deployment Rules

- main 分支禁止直接提交。
- 所有变更通过 PR。
- 部署前必须通过 CI。
- 失败自动回滚或阻断发布。

## 8. Do Not

- 不要大范围重写。
- 不要引入未批准的新框架。
- 不要把业务规则硬编码到 UI。
- 不要在没有测试的情况下修改核心链路。
```

---

# 六、任务流转用 task.yaml 固化
每次只需要输入需求，Orchestrator Agent 自动生成：

```yaml
task_id: feature_content_strategy_workspace_v1
title: 内容策划工作台升级
type: feature
priority: P0

business_input:
  source_doc: docs/input/business_requirement.md
  owner: Clifford
  goal: "把业务需求转成可执行的内容策划工作台功能"

agents:
  product_agent:
    output:
      - docs/product/prd.md
      - docs/product/acceptance_criteria.md

  architect_agent:
    output:
      - docs/architecture/tech_spec.md
      - docs/architecture/api_contract.md
      - docs/architecture/data_model.md

  ux_agent:
    output:
      - docs/ux/ui_spec.md
      - docs/ux/page_state_machine.md

  qa_agent:
    output:
      - docs/eval/tdd_cases.md
      - docs/eval/review_checklist.md

  coding_agent:
    input:
      - AGENTS.md
      - docs/product/prd.md
      - docs/architecture/tech_spec.md
      - docs/ux/ui_spec.md
      - docs/eval/tdd_cases.md
    output:
      - code_changes
      - tests
      - migration

gates:
  before_coding:
    required:
      - prd_completed
      - tech_spec_completed
      - ui_spec_completed
      - acceptance_criteria_completed

  before_merge:
    required:
      - tests_passed
      - review_passed
      - no_architecture_violation

  before_deploy:
    required:
      - ci_passed
      - manual_approval
```

这个文件非常关键。
它是从“聊天式 AI coding”升级到“工程化 AI coding”的核心。

---

# 七、Hermes Skill 设计

Hermes 不要直接记一堆散乱经验，而是沉淀成 Skills。

第一批做 6 个 Skill：

```text
1. requirement_to_prd
2. prd_to_tech_spec
3. prd_to_ui_spec
4. tech_spec_to_tdd
5. task_to_code_prompt
6. review_and_deploy_gate
```

每个 Skill 都有固定输入、输出和验收标准。

例如：

```yaml
skill_id: requirement_to_engineering_pack
name: 业务需求转工程任务包
version: 0.1.0

input:
  - business_requirement.md
  - existing_repo_context
  - product_memory
  - architecture_memory

output:
  - task.yaml
  - prd.md
  - tech_spec.md
  - ui_spec.md
  - eval.md
  - coding_prompt.md

steps:
  - 识别业务目标
  - 识别用户角色
  - 识别功能边界
  - 拆解页面与流程
  - 生成技术影响分析
  - 生成测试与验收标准
  - 生成 AI coding prompt

eval:
  - 是否有明确业务目标
  - 是否有功能范围和非功能范围
  - 是否有架构约束
  - 是否有可执行任务拆解
  - 是否有测试标准
```

---

# 八、真正需要的不是 7 个 Agent，而是 5 个阶段

更简单、更稳的方案是这样：

## 阶段 1：需求编译

```text
输入：业务文档
输出：
- task.yaml
- context.md
- prd.md
```

## 阶段 2：工程设计

```text
输入：PRD + 代码库上下文
输出：
- tech_spec.md
- architecture.md
- api_contract.md
- data_model.md
```

## 阶段 3：交互设计

```text
输入：PRD + 技术约束
输出：
- ui_spec.md
- page_state_machine.md
- component_spec.md
```

## 阶段 4：AI coding

```text
输入：完整工程任务包
输出：
- feature branch
- code diff
- tests
```

## 阶段 5：Review / Test / Deploy

```text
输入：代码变更
输出：
- review_report.md
- test_report.md
- deploy_report.md
```

这样比“多个 Agent 自由协作”更可靠。

---

# 九、最小MVP

 Phase 1 就做一个 **CLI + 文件夹流水线**。

只需要一个命令：

```bash
growth-dev new "我要做一个内容策划工作台，支持上传业务文档后生成任务清单、PRD、UI规范，并交给 AI coding 实现"
```

然后自动生成：

```text
tasks/current/task.yaml
tasks/current/context.md
docs/product/prd.md
docs/architecture/tech_spec.md
docs/ux/ui_spec.md
docs/eval/tdd_cases.md
prompts/coding_prompt.md
```

再执行：

```bash
growth-dev code
growth-dev review
growth-dev test
growth-dev deploy
```

本质上你先做一个自己的 **AI Engineering Harness**。

---

# 十、Phase 1 技术选型

## 最简单组合

```text
Hermes Agent
+ Python CLI
+ Git
+ Codex CLI 或 Claude Code
+ GitHub Actions
+ Pytest / Playwright / Vitest
+ Markdown/YAML 文件系统
```

### 角色分工

| 模块                  | 负责什么             |
| ------------------- | ---------------- |
| Hermes              | 记忆、Skill、任务统筹、复盘 |
| Python CLI          | 流水线控制            |
| Codex / Claude Code | 代码实现             |
| GitHub Actions      | CI、Review、部署     |
| Markdown/YAML       | 任务上下文和工程产物       |
| Tests               | TDD 与回归验证        |

---

# 十一、推荐执行命令设计

```bash
# 1. 创建任务
growth-dev init --input ./docs/input/business.md

# 2. 生成产品文档
growth-dev product

# 3. 生成技术方案
growth-dev architect

# 4. 生成 UI 规范
growth-dev ux

# 5. 生成测试方案
growth-dev qa

# 6. 生成 coding prompt
growth-dev prompt

# 7. 调用 AI coding
growth-dev code --engine codex

# 8. Review
growth-dev review

# 9. 测试
growth-dev test

# 10. 部署
growth-dev deploy --env staging
```

未来可以把这些命令包装成 Web 工作台，但第一版建议 CLI 优先。

---

# 十二、自动部署要加人审 Gate

分两层：

```text
staging：可自动部署
production：必须人工确认
```

流程：

```text
AI coding 完成
  ↓
自动测试
  ↓
AI Review
  ↓
部署 staging
  ↓
生成验收报告
  ↓
点确认
  ↓
部署 production
```

不要一开始让 Agent 自动上生产。

---

# 十三、最终每天的工作方式

只做两件事的目标是成立的，但要拆成这样：

## 做的第 1 件事：输入需求

例如：

```text
我要做一个业务专家工作台里的语义单元聚合功能。
现在 section 和 raw_output 更像工程调试视图，不适合业务专家。
我希望用户看到的是可理解、可编辑、可确认的语义单元。
需要支持文档块聚合、人工修正、结构化入库、后续 Agent 调用。
```

## 做的第 2 件事：审批关键关卡

不是每天盯代码，而是审批：

```text
1. PRD 是否对
2. 技术边界是否对
3. UI 体验是否对
4. Review 是否通过
5. 是否发布
```

也就是从“写需求的人”变成：

> **AI-native 工程团队的 Owner / Approver / Strategy Controller**

---

# 十四、最终落地路径

## Week 1：先搭文件流水线

完成：

```text
task.yaml
context.md
prd.md
tech_spec.md
ui_spec.md
eval.md
coding_prompt.md
```

不接 Hermes，也不做复杂多 Agent。

---

## Week 2：接入 AI coding

完成：

```text
growth-dev code --engine codex
growth-dev review
growth-dev test
```

先让 Codex / Claude Code 能基于文档实现小功能。

---

## Week 3：接 Hermes Memory / Skill

完成：

```text
需求类型识别
历史任务召回
Skill 选择
任务复盘
失败案例沉淀
```

---

## Week 4：接 GitHub Actions + Staging Deploy

完成：

```text
PR 自动生成
CI 自动测试
AI Review
Staging 自动部署
Production 人工确认
```

---

# 十五、最重要的产品判断

不要把系统做成：

```text
多个 Agent 聊天协作
```

而应该做成：

```text
业务需求 → 工程任务包 → AI coding → 测试 → Review → 部署 → 复盘
```

所以最简单、最稳的版本是：

```text
一个 Hermes Orchestrator
+ 一套标准文档 Schema
+ 一个 coding 执行器
+ 一个 Review/Test Gate
+ 一个部署 Gate
```

最终架构可以概括为：

```text
Hermes = 工程项目经理 + 经验记忆
GPT = 需求理解与文档生成
Codex / Claude Code = AI 程序员
Review Agent = 架构师 + QA
GitHub Actions = 自动化流水线
AGENTS.md = 仓库级工程宪法
task.yaml = 每次需求的任务合同
```


[1]: https://hermes-agent.nousresearch.com/docs/?utm_source=chatgpt.com "Hermes Agent Documentation | Hermes Agent"
[2]: https://help.openai.com/en/articles/11096431-Openai-Codex-Letting-Tharted?utm_source=chatgpt.com "OpenAI Codex CLI – Getting Started | OpenAI Help Center"
[3]: https://developers.openai.com/api/docs/models/gpt-5.2-codex?utm_source=chatgpt.com "GPT-5.2-Codex Model | OpenAI API"
[4]: https://docs.anthropic.com/en/docs/claude-code/sub-agents?utm_source=chatgpt.com "Subagents - Anthropic"
[5]: https://developers.openai.com/codex/use-cases/?utm_source=chatgpt.com "Codex use cases"
[6]: https://docs.anthropic.com/en/docs/claude-code/hooks?utm_source=chatgpt.com "Hooks reference - Anthropic"
[7]: https://arxiv.org/abs/2602.11988?utm_source=chatgpt.com "Evaluating AGENTS.md: Are Repository-Level Context Files Helpful for Coding Agents?"
