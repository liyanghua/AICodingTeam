# deterministic CLI 基线

## 目标

本基线用于验收 `app_generation` 的 deterministic CLI 链路：

```text
主业务文档
-> doc-to-skill 产物包
-> APP-generation
-> 本地 report_generator 应用
-> CLI 验证
```

本轮只输入主业务文档：

```text
document-to-skill-engineering-package/examples/source_docs/20260519市场分析洞察元策略.md
```

`collection.yaml` 原生集合输入、集合合并编译、真实 CSV 实算、Codex 增强生成都放到后续增强。

## 当前断点

上游 Skill 包已经能生成业务运行需要的结构化资产：

- `workflow.dag.yaml`：业务 DAG。
- `data_requirements.yaml`：人工上传数据需求。
- `output_schemas/*.json`：报告输出表结构。
- `eval_rules.yaml`：规则和 hard requirements。
- `evidence_schema.yaml`：Evidence Pack 结构。

P0/P1 修复前，生成应用接近空壳的原因不在 Skill 包缺信息，而在下游执行闭环不足：

- `app.config.json` 未完整暴露可执行输出 schema 摘要，部分节点输出只显示 missing schema。
- `report_generator` shell 仍偏节点展示壳：data 节点停在 `waiting_upload`，llm 节点返回 mock，compute/aggregate 节点没有按业务 DAG 聚合成完整报告。
- `appcheck acceptance` 会暴露 PRD/custom/rule/safety/node 派生验收与 markdown/contract 不一致。
- 部分 run 声明了 `runtime_smoke.js` 验证命令，但 deterministic 生成应用未必产出该文件。

P0/P1 基线实现后，deterministic 链路必须做到：

- 对缺失同名 `output_schemas/*.json` 的 workflow output 生成 deterministic fallback schema，并标记为可追溯的 `generated_fallback`，不再静默显示 missing。
- `app.config.json` 携带 output schema summary 和 evidence contract。
- 每个 workflow node 都升级为可执行节点视图模型，包含 `input_model`、`output_model`、`execution_model`、`evidence_model`、`tool_model` 和 `source_trace`。
- Strategy KB build 阶段必须把主业务文档中的 `## 流程N：...` 切成 `page_type=workflow_section` 的 KB page；查询 `流程N:节点标题的具体内容` 时直接返回完整流程章节和 `subsections`。
- 每个 workflow node 都包含 `business_context`，由 `hermes-agent/local-skills/business-strategy-workspace-adapter/scripts/query_strategy_kb.py` 在生成期按节点标题查询 Strategy KB 得到，展示 workflow section、citation、source path 和 query。
- 每个 workflow node 都包含 `node_execution_view`，从 workflow section 映射出分析目标、执行动作、验证标准、中间产物、Agent 辅助上下文和来源追踪。
- `report_generator` UI 必须从节点视图模型展示分析目标、执行动作、用户填写区、验证标准、中间产物、输入、依赖数据、产物 schema、Evidence、Tool 和 Source Trace，而不是只展示节点 ID。
- 四源派生验收以 `app_contract.json` 为准，`acceptance_criteria.md`、coverage matrix、requirement quality gate 保持一致。
- `report_generator` 生成应用产出 `artifacts/fixture_outputs.json`、`evidence/evidence_pack.json`、`final_report.md` 和 `runtime_smoke.js`。
- `runtime_smoke.js` 覆盖 `/api/health`、至少一个节点执行和 `/api/export/final_report`。
- `runtime_smoke.js` 断言 `/api/config` 和 `/api/nodes/:id` 都返回完整节点视图模型、`business_context` 和 `node_execution_view`，至少一个 data 节点带有展开后的 `required_data`，至少一个节点带有 `output_model.outputs[].schema`、`output_field_requirements` 和 `data_mapping_context`；form 节点运行后必须落盘节点 artifact。
- P0 字段映射基线已经进入生成过程：新生成的 `report_generator` 应用会在中栏展示输出字段要求，右侧 Agent 可选择候选 API、查看 API 返回字段、把字段映射回中栏，并确认 `data_mapping_contract`。

因此 deterministic 基线的第一目标是稳定暴露这些断点，而不是把断点静默吞掉。

## 一键验收脚本

脚本位置：

```bash
scripts/accept_app_generation_cli_baseline.sh
```

默认行为：

- 不修改 `tasks/current/*`。
- 不删除旧 run。
- 不自动创建 venv 或安装依赖。
- 若同名 run 已存在，直接失败并提示换 `RUN_ID`。
- preview 默认不启动；需要时设置 `START_PREVIEW=1`。

默认参数：

```bash
RUN_ID=app_generation-cli-baseline-001
APP_SLUG=market-insight-cli-baseline
PORT=8799
PRD_FILE=tasks/current/prd.md
SOURCE_DOC=document-to-skill-engineering-package/examples/source_docs/20260519市场分析洞察元策略.md
SKILL_OUT=document-to-skill-engineering-package/build/market_insight_skill_cli_acceptance
HERMES_AGENT_ROOT=/Users/yichen/Desktop/OntologyBrain/PersonAgent/hermes-agent
BUILD_STRATEGY_KB=1
STRATEGY_KB_OUTPUT=$HERMES_AGENT_ROOT/.strategy-kb/marketing-insight/kb-standalone-smoke
STRATEGY_KB=$STRATEGY_KB_OUTPUT/kb_manifest.json
STRATEGY_KB_BUILD_SCRIPT=$HERMES_AGENT_ROOT/local-skills/business-strategy-workspace-adapter/scripts/build_strategy_kb.py
STRATEGY_KB_QUERY_SCRIPT=$HERMES_AGENT_ROOT/local-skills/business-strategy-workspace-adapter/scripts/query_strategy_kb.py
STRATEGY_KB_PYTHON=$HERMES_AGENT_ROOT/.venv/bin/python
STRATEGY_KB_COLLECTION=$HERMES_AGENT_ROOT/docs/biz_spec/marketing_insight/collection.yaml
STRATEGY_KB_OPENKB_ROOT=$HERMES_AGENT_ROOT/third_party/OpenKB
STRATEGY_KB_TOP_K=3
```

运行：

```bash
bash scripts/accept_app_generation_cli_baseline.sh
```

覆盖参数示例：

```bash
RUN_ID=app_generation-cli-baseline-002 \
APP_SLUG=market-insight-cli-baseline-002 \
START_PREVIEW=1 \
bash scripts/accept_app_generation_cli_baseline.sh
```

如果 `doc_to_skill` 缺依赖，先安装上游包：

```bash
python3 -m venv document-to-skill-engineering-package/.venv
source document-to-skill-engineering-package/.venv/bin/activate
python -m pip install -e "document-to-skill-engineering-package[dev]"
```

也可以不激活 venv，但要保证当前 `python3` 能运行：

```bash
PYTHONPATH=document-to-skill-engineering-package/src python3 -m doc_to_skill.cli --help
```

## 验收步骤

脚本按顺序执行以下 CLI 验收：

1. 检查 `doc_to_skill` CLI 可用。
2. 用主业务文档编译 Skill 包。
3. 检查 Skill 包关键文件存在。
4. 运行 deterministic APP-generation：

```bash
python3 -m growth_dev.cli app generate \
  --prd-file "$PRD_FILE" \
  --app-slug "$APP_SLUG" \
  --run-id "$RUN_ID" \
  --executor deterministic \
  --skill-dir "$SKILL_OUT" \
  --task-yaml-path tasks/current/task.yaml \
  --domain-yaml-path tasks/current/domain.yaml \
  --strategy-kb "$STRATEGY_KB" \
  --strategy-kb-query-script "$STRATEGY_KB_QUERY_SCRIPT" \
  --strategy-kb-python "$STRATEGY_KB_PYTHON" \
  --strategy-kb-top-k "$STRATEGY_KB_TOP_K" \
  --shell-kind report_generator \
  --foreground
```

5. 读取 run 状态：

```bash
python3 -m growth_dev.cli team status --run-id "$RUN_ID" --summary
python3 -m growth_dev.cli team workspace show --run-id "$RUN_ID" --json
```

6. 验证 app config 与 acceptance：

```bash
python3 -m growth_dev.cli app appcheck config --run-id "$RUN_ID"
python3 -m growth_dev.cli app appcheck acceptance --run-id "$RUN_ID"
```

7. 检查生成应用 server 语法：

```bash
node --check "runs/$RUN_ID/generated_apps/$APP_SLUG/server.js"
```

8. 运行生成应用 runtime smoke：

```bash
node "runs/$RUN_ID/generated_apps/$APP_SLUG/runtime_smoke.js"
```

9. 断言可执行节点视图模型：

```bash
python3 -c "import json; from pathlib import Path; p=Path('runs/$RUN_ID/generated_apps/$APP_SLUG/app.config.json'); c=json.loads(p.read_text()); nodes=c['nodes']; assert all(isinstance(n.get('input_model'), dict) and isinstance(n.get('output_model'), dict) and isinstance(n.get('evidence_model'), dict) for n in nodes); assert any(n.get('kind')=='data' and n['input_model'].get('required_data') for n in nodes)"
```

10. 断言 Strategy KB 业务上下文和节点执行视图：

```bash
python3 -c "import json; from pathlib import Path; p=Path('runs/$RUN_ID/generated_apps/$APP_SLUG/app.config.json'); c=json.loads(p.read_text()); nodes=c['nodes']; assert all(n.get('business_context', {}).get('status') == 'available' and n['business_context'].get('results') for n in nodes)"
python3 -c "import json; from pathlib import Path; p=Path('runs/$RUN_ID/generated_apps/$APP_SLUG/app.config.json'); c=json.loads(p.read_text()); first=c['nodes'][0]['node_execution_view']; assert first['status']=='available'; assert '市场洞察项目定义表' in first['artifact']['title']; assert any(f['id']=='分析类目' for f in first['action']['fields'])"
```

11. 断言 canvas 第 5/6/7 步不是 `generating`：

```bash
python3 -c "from pathlib import Path; from growth_dev.team.app_generation_canvas import build_canvas_projection; p=build_canvas_projection('$RUN_ID', runs_dir=Path('runs'), repo_root=Path('.')); statuses={s['id']: s['status'] for s in p['flow_steps']}; print(statuses); assert statuses['prototype_generation']=='generated'; assert statuses['capability_verification']=='verified'; assert statuses['delivery_version']=='delivered'"
```

12. 可选 preview：

```bash
START_PREVIEW=1 bash scripts/accept_app_generation_cli_baseline.sh
```

preview 模式会执行：

```bash
python3 -m growth_dev.cli app preview start --run-id "$RUN_ID" --port "$PORT"
python3 -m growth_dev.cli app preview list
python3 -m growth_dev.cli app preview stop --run-id "$RUN_ID"
```

## 失败判读

脚本失败时会打印：

- 已通过步骤。
- 失败命令。
- run 目录。
- generated app 目录。
- 常见阻断说明。

常见阻断：

- `doc_to_skill` 不可用：当前 Python 环境缺 `typer/rich` 等上游依赖。
- `appcheck acceptance` 失败：`app.config.json` 派生验收、`app_contract.json`、`acceptance_criteria.md` 未完全对齐。
- `runtime_smoke.js` 失败：生成应用未通过 health、节点执行或报告导出。
- Strategy KB 业务上下文失败：`kb_manifest.json`、query script、Hermes `.venv` Python 路径不可用，或节点标题查询没有返回 passage。
- preview 失败：本地 socket 权限或端口占用，不应阻断非 preview 的基础 CLI 基线验收。

## 后续增强

deterministic P0/P1 基线通过后，再进入以下阶段：

1. 支持 `collection.yaml` 原生集合编译。
2. 将节点拓扑、数据需求和产物 schema 从旧 `document-to-skill-engineering-package` 全量迁移到 `local-skills` 的 playbook/schema bundle。
3. 将 deterministic fixture 升级为真实 CSV 实算、规则计算和业务 DAG 聚合。
4. 扩展 `runtime_smoke.js` 到多节点链路、上传样例数据和报告内容断言。
5. 在 deterministic 基线之上叠加 Codex 应用增强，而不是让 Codex 替代基线。
