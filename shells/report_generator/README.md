# Report Generator Shell

固定 Shell 模板，用于实例化市场分析洞察报告类应用。

## 概述

本 Shell 提供三栏交互式 SPA + Node.js 后端 + Python 规则引擎，专门用于消费 `app.config.json` 并渲染报告生成工作流。

## 目录结构

```
shells/report_generator/
├── server/           # Node.js 后端服务
│   └── server.js     # HTTP + SSE broker
├── web/              # 前端 SPA
│   ├── index.html
│   ├── app.js        # 主应用逻辑
│   └── styles.css
├── engine/           # Python 规则引擎（待实现）
├── contract.schema.json  # app.config.json JSON Schema
├── version.txt       # Shell 版本号（semver）
└── README.md         # 本文档
```

## 设计原则

1. **Shell 不可被 GenAgent 改写**：所有业务定制只能通过 `app.config.json` + `custom/` 目录，Shell 源码只能升级，不能按业务定制。

2. **零依赖 stdlib 实现**：
   - Node.js 端使用 `http` stdlib
   - Python 端使用 stdlib
   - 前端零 npm 依赖

3. **Schema 驱动**：启动时校验 `app.config.json` 符合 `contract.schema.json`。

4. **版本绑定**：`app.config.json.shell_version` 必须与 `version.txt` 一致。

## 核心功能

### 1. 三栏布局

- **左栏**：节点列表，显示执行流程和状态
- **中栏**：节点详情和产物展示
- **右栏**：Agent 交互区（占位）

### 2. 节点类型

- `form`: 表单输入收集
- `data`: 数据上传（CSV/JSON）
- `llm`: LLM 处理节点
- `compute`: 规则计算节点
- `aggregate`: 最终报告汇总

### 3. SSE 实时推送

- `node_start`: 节点开始执行
- `node_progress`: 执行进度更新
- `node_done`: 执行完成
- `node_error`: 执行失败

### 4. 产物可视化

- JSON 结构化展示
- Markdown 渲染
- 规则评估结果（badge + 分数 + 证据）

## API 端点

### 配置和节点

- `GET /api/health` - 健康检查
- `GET /api/config` - 返回 app.config.json
- `GET /api/nodes` - 节点列表
- `GET /api/nodes/:id` - 单节点详情

### 节点执行

- `POST /api/nodes/:id/run` - 执行节点
- `POST /api/upload/:data_requirement_id` - 上传数据

### 右侧 Agent 数据映射

- `GET /api/db-agent/status` - 检测外部数仓助手 bridge 状态
- `POST /api/db-agent/query` - 执行 `understand_input`、`tool_plan`、`field_map`、`probe_sample`

`/api/db-agent/query` 会在兼容旧 `payload` 的同时返回 `data_mapping_contract`。该合同用于记录业务文档描述、候选 API、请求参数映射、响应字段映射、未匹配字段、人工确认和 evidence 引用。未开启 `DBA_LIVE_PROBE=1` 时，`probe_sample` 返回 `blocked/live_probe_disabled`，不会调用真实取数。

### 报告导出

- `POST /api/export/final_report` - 生成最终报告

### SSE 推送

- `GET /sse/nodes/stream` - 节点状态流
- `GET /sse/agent/:conv_id` - Agent 交互流（占位）

## 启动方式

从 `generated_apps/<app_slug>/` 目录启动：

```bash
cd generated_apps/my-report-app
node ../../shells/report_generator/server/server.js
```

服务器自动读取当前目录的 `app.config.json`。

## 安全约束

1. **数字守门**：aggregate 节点的 narrative 段禁止包含数字、百分比、货币符号
2. **手动上传优先**：所有数据源默认降级为 `manual_upload_only`
3. **Evidence 追溯**：每个节点执行结果都落盘 evidence 记录
4. **数据映射确认**：右侧 Agent 结果先沉淀为 `data_mapping_contract`，未确认前不作为真实节点数据完成
5. **Live probe 显式开启**：真实样例取数必须设置 `DBA_LIVE_PROBE=1`，默认不读取或暴露 `.env` secrets

## 版本升级

Shell 版本遵循 semver：

- **MAJOR**: 破坏性变更（需要重新生成 app.config.json）
- **MINOR**: 向后兼容的功能增加
- **PATCH**: Bug 修复

## 不在范围

- 多 Shell 切换（当前仅 `report_generator`）
- 真实 API/浏览器自动化（严格 manual_login_only）
- 动态 DAG 修改（节点流程由 app.config.json 固定）
