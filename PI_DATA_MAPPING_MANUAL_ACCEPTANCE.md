# PI 数据映射改进 - 人工验收指南

## 改进目标

将原本 7-9 次区域切换的交互流程简化为 0 次，PI 建议内联到中间工作台，支持批量应用高置信建议和单字段快捷操作。

## 验收环境

```bash
cd <app_workspace>  # 例如包含 app.config.json 的项目目录
node /path/to/shells/report_generator/server/server.js
```

浏览器访问 `http://localhost:8765`，选择一个 data mapping 节点（例如 `collect_top_products`）。

## 验收步骤

### 1. 基础流程：确定性 baseline（无 PI）

**操作：**
1. 右侧「数仓助手」→「1. 理解业务输入」→「2. 映射数仓 API」
2. 从候选 API 列表中选择 2 个 API（点击「选择」按钮）
3. 中间「字段覆盖工作台」→「智能匹配字段（PI 增强）」

**预期：**
- 工作台顶部显示「PI 判断：PI 未就绪（降级/兜底）」
- 表格每行字段显示确定性规则匹配的来源 API 和字段路径
- 未覆盖字段显示 `PI ✗ 缺失` 徽标
- 已匹配字段显示 `PI ⚠ 待审` 徽标
- 「应用高置信建议 ≥0.9（0）」按钮禁用（因为 PI 未配置，无高置信建议）

### 2. PI 增强流程（PI 配置且可用）

**前置条件：** PI_AGENT_BIN 环境变量指向有效 pi binary，且支持 RPC 模式。

**操作：**
1. 重复步骤 1.1-1.3
2. 观察 PI 判断摘要和工作台表格

**预期：**
- 顶部显示「PI 判断：需人工审核」或「整体可用」，附带 PI 摘要文本
- 表格每行显示 PI 徽标：
  - `PI ✓ 一致 95%`：字段映射正确，置信度 0.95
  - `PI ⚠ 待审 65%`：置信度低于 0.9，需人工确认
  - `PI ✗ 缺失 0%`：未覆盖必填字段
  - `PI ↺ 更优 88%`：有更好的字段选择
- 点击 `PI: ...` details 可展开查看理由和建议来源
- 「应用高置信建议 ≥0.9（N）」按钮启用，显示高置信字段数量

### 3. 批量应用高置信建议

**操作：**
1. 点击「应用高置信建议 ≥0.9」

**预期：**
- 只有 `judgement=ok` 且 `confidence>=0.9` 的字段被更新为 `suggested` 状态
- 低置信度字段（< 0.9）保持原样
- 顶部显示「已应用 N 个高置信字段，跳过 M 个需人工确认的字段」
- 表格中应用字段的「覆盖状态」变为 `suggested`，「置信度」更新为 PI 给出的值
- `human_confirmed` 仍为 `false`，需用户最终「确认映射合同」

### 4. 单字段快捷操作

**操作：**
1. 找一个显示 `PI ↺ 更优` 的字段行
2. 点击该行「操作」列的「应用」按钮

**预期：**
- 该字段的「来源 API」和「API 字段」立即更新为 PI 建议的来源
- 「覆盖状态」变为 `suggested`
- 「置信度」显示 PI 给出的值
- 其他字段不受影响

**操作：**
1. 找一个 `PI ✗ 缺失` 的字段行
2. 点击「人工」按钮

**预期：**
- 该字段「覆盖状态」变为 `manual_fill`
- 「口径备注」显示「人工补充」
- 可后续在表单或其他节点中手动填充

**操作：**
1. 找一个字段行
2. 点击「忽略」按钮

**预期：**
- 该字段来源清空，「覆盖状态」变为 `unmapped`

### 5. Join plan 确认

**操作：**
1. 在工作台底部「Join / 粒度确认」区域填写：
   - 主 API：`/api/category/top-products`
   - Join Key：`product_id`
   - 数据粒度：`product`
   - 时间口径：`近30天`
2. 点击「确认映射合同」

**预期：**
- 调用 `/api/db-agent/query` action=`confirm_mapping`
- 顶部显示「已确认映射合同」
- 所有已映射字段的 `human_confirmed` 置为 `true`
- 右侧数仓助手面板显示合同摘要（覆盖统计、join plan、evidence_ref）

### 6. 证据持久化

**操作：**
1. 右侧「保存映射合同/证据」

**预期：**
- 在 `evidence/` 目录生成：
  - `<node_id>.data_mapping_contract.json`（确认合同）
  - `<node_id>.pi_mapping_advice.json`（PI 建议历史）
  - `<node_id>.db_agent.suggest_multi_api_mapping.json`（确定性 baseline）

## 关键验证点

### ✅ 交互流程简化
- **旧**：右侧选 API → 中间查看 → 右侧获取 PI 建议 → 中间应用草稿 → 中间确认 → 合同确认（7-9 次切换）
- **新**：右侧选 API → 中间「智能匹配（PI 增强）」→ 批量应用/逐字段确认 → 合同确认（0 次切换）

### ✅ PI 建议内联
- 表格每行内嵌 PI 徽标、置信度、理由、快捷操作
- 无需在右侧独立面板查看，所有决策在中间工作台完成

### ✅ 置信度闸门
- 批量应用只作用于 `judgement=ok && confidence>=0.9`
- 低置信字段（< 0.7）或 `needs_review/missing` 强制人工确认
- 中等置信（0.7-0.9）不进入批量，只能单字段手动应用

### ✅ 降级友好
- PI 未配置时，返回结构化 `pi-data-mapping-advice-v1`，`summary.status=unavailable`
- PI 返回纯文本时，normalize 为结构化，`source.degraded=true`
- 确定性规则作为 baseline 兜底，不阻断基础流程

### ✅ 智能建议质量
- PI prompt 注入完整 API request/response schema、确定性 baseline、上游产物、few-shot 示例
- PI 输出包含逐字段 judgement、confidence、reason、suggested_source_field_path
- 禁止只输出"请确认"之类无信息量文本

## 验收通过标准

- [ ] 静态检查通过（`node --check`）
- [ ] PI 未配置时，工作台显示兜底建议，批量按钮禁用
- [ ] PI 配置时，工作台显示逐字段 PI 徽标、置信度、理由
- [ ] 批量应用只作用于高置信字段（≥0.9），跳过低置信字段并提示
- [ ] 单字段快捷操作（应用/人工/忽略）立即更新 draft overlay
- [ ] 确认合同后，evidence 目录生成 PI advice 和 contract JSON
- [ ] 右侧 PI 面板已删除，数仓助手按钮精简为 3 个（理解/映射/样例）

## 回归风险

- 旧的「让 PI 检查字段映射」按钮和「回填到中间表格」按钮已删除，确认无业务流程依赖
- `saveFieldMappingDraft` 函数保留但无按钮触发，仅被 `confirmFieldMappingContract` 内部调用
- `state.fieldMappingDrafts` 和 `state.piAgentResults` 状态管理未变，向下兼容

## 已知限制

- PI binary 必须支持 RPC 模式（`--mode rpc`）和 JSON stdin/stdout
- PI 超时默认 15s（可通过 `PI_RPC_TIMEOUT_MS` 环境变量调整）
- 批量应用不会自动触发合同确认，用户仍需点击「确认映射合同」
- 单字段快捷操作只更新 draft overlay，不直接修改 confirmed contract