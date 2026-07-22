#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

RUN_ID="${RUN_ID:-app_generation-cli-baseline-001}"
APP_SLUG="${APP_SLUG:-market-insight-cli-baseline}"
PORT="${PORT:-8799}"
PRD_FILE="${PRD_FILE:-tasks/current/prd.md}"
SOURCE_DOC="${SOURCE_DOC:-document-to-skill-engineering-package/examples/source_docs/20260519市场分析洞察元策略.md}"
SKILL_OUT="${SKILL_OUT:-document-to-skill-engineering-package/build/market_insight_skill_cli_acceptance}"
TASK_YAML_PATH="${TASK_YAML_PATH:-tasks/current/task.yaml}"
DOMAIN_YAML_PATH="${DOMAIN_YAML_PATH:-tasks/current/domain.yaml}"
START_PREVIEW="${START_PREVIEW:-0}"
HERMES_AGENT_ROOT="${HERMES_AGENT_ROOT:-/Users/yichen/Desktop/OntologyBrain/PersonAgent/hermes-agent}"
BUILD_STRATEGY_KB="${BUILD_STRATEGY_KB:-1}"
STRATEGY_KB_OUTPUT="${STRATEGY_KB_OUTPUT:-$HERMES_AGENT_ROOT/.strategy-kb/marketing-insight/kb-standalone-smoke}"
STRATEGY_KB="${STRATEGY_KB:-$STRATEGY_KB_OUTPUT/kb_manifest.json}"
STRATEGY_KB_BUILD_SCRIPT="${STRATEGY_KB_BUILD_SCRIPT:-$HERMES_AGENT_ROOT/local-skills/business-strategy-workspace-adapter/scripts/build_strategy_kb.py}"
STRATEGY_KB_QUERY_SCRIPT="${STRATEGY_KB_QUERY_SCRIPT:-$HERMES_AGENT_ROOT/local-skills/business-strategy-workspace-adapter/scripts/query_strategy_kb.py}"
STRATEGY_KB_PYTHON="${STRATEGY_KB_PYTHON:-$HERMES_AGENT_ROOT/.venv/bin/python}"
STRATEGY_KB_COLLECTION="${STRATEGY_KB_COLLECTION:-$HERMES_AGENT_ROOT/docs/biz_spec/marketing_insight/collection.yaml}"
STRATEGY_KB_OPENKB_ROOT="${STRATEGY_KB_OPENKB_ROOT:-$HERMES_AGENT_ROOT/third_party/OpenKB}"
STRATEGY_KB_TOP_K="${STRATEGY_KB_TOP_K:-3}"
API_DOC_INDEX="${API_DOC_INDEX:-api_doc_matcher/build/api_doc_index.json}"
API_DETAIL_DOC="${API_DETAIL_DOC:-}"
API_VALIDATION_DOC="${API_VALIDATION_DOC:-}"

RUN_DIR="runs/$RUN_ID"
APP_DIR="$RUN_DIR/generated_apps/$APP_SLUG"
SERVER_JS="$APP_DIR/server.js"
RUNTIME_SMOKE_JS="$APP_DIR/runtime_smoke.js"
DOC_TO_SKILL_SRC="document-to-skill-engineering-package/src"
DOC_TO_SKILL_PYTHONPATH="$DOC_TO_SKILL_SRC"
if [[ -n "${PYTHONPATH:-}" ]]; then
  DOC_TO_SKILL_PYTHONPATH="$DOC_TO_SKILL_SRC:$PYTHONPATH"
fi
# Prefer the package-local venv interpreter (created by the manual install step) so
# doc_to_skill deps (typer/rich/pydantic/PyYAML) resolve without needing an activated
# shell. Fall back to bare python3, and allow an explicit override.
DOC_TO_SKILL_VENV_PYTHON="document-to-skill-engineering-package/.venv/bin/python"
if [[ -n "${DOC_TO_SKILL_PYTHON:-}" ]]; then
  DOC_TO_SKILL_PYTHON="$DOC_TO_SKILL_PYTHON"
elif [[ -x "$DOC_TO_SKILL_VENV_PYTHON" ]]; then
  DOC_TO_SKILL_PYTHON="$DOC_TO_SKILL_VENV_PYTHON"
else
  DOC_TO_SKILL_PYTHON="python3"
fi

PASSED_STEPS=()
CURRENT_STEP="initializing"
CURRENT_COMMAND=""
PREVIEW_STARTED=0

print_config() {
  printf '\n== deterministic CLI baseline ==\n'
  printf 'repo: %s\n' "$REPO_ROOT"
  printf 'run_id: %s\n' "$RUN_ID"
  printf 'app_slug: %s\n' "$APP_SLUG"
  printf 'source_doc: %s\n' "$SOURCE_DOC"
  printf 'doc_to_skill_python: %s\n' "$DOC_TO_SKILL_PYTHON"
  printf 'skill_out: %s\n' "$SKILL_OUT"
  printf 'prd_file: %s\n' "$PRD_FILE"
  printf 'task_yaml_path: %s\n' "$TASK_YAML_PATH"
  printf 'domain_yaml_path: %s\n' "$DOMAIN_YAML_PATH"
  printf 'strategy_kb: %s\n' "$STRATEGY_KB"
  printf 'build_strategy_kb: %s\n' "$BUILD_STRATEGY_KB"
  printf 'strategy_kb_output: %s\n' "$STRATEGY_KB_OUTPUT"
  printf 'strategy_kb_build_script: %s\n' "$STRATEGY_KB_BUILD_SCRIPT"
  printf 'strategy_kb_query_script: %s\n' "$STRATEGY_KB_QUERY_SCRIPT"
  printf 'strategy_kb_python: %s\n' "$STRATEGY_KB_PYTHON"
  printf 'strategy_kb_collection: %s\n' "$STRATEGY_KB_COLLECTION"
  printf 'strategy_kb_openkb_root: %s\n' "$STRATEGY_KB_OPENKB_ROOT"
  printf 'strategy_kb_top_k: %s\n' "$STRATEGY_KB_TOP_K"
  printf 'api_doc_index: %s\n' "$API_DOC_INDEX"
  printf 'api_detail_doc: %s\n' "${API_DETAIL_DOC:-}"
  printf 'api_validation_doc: %s\n' "${API_VALIDATION_DOC:-}"
  printf 'start_preview: %s\n' "$START_PREVIEW"
}

print_passed_steps() {
  printf '\nPassed steps:\n'
  if (( ${#PASSED_STEPS[@]} == 0 )); then
    printf '%s\n' '- none'
    return
  fi
  local step
  for step in "${PASSED_STEPS[@]}"; do
    printf '%s\n' "- $step"
  done
}

print_known_blockers() {
  printf '\nKnown blockers to inspect if this run fails:\n'
  printf '%s\n' '- doc_to_skill unavailable: current python3 may be missing typer/rich or package deps.'
  printf '%s\n' '- appcheck acceptance mismatch: app.config.json, app_contract.json, acceptance_criteria.md, and derived rules may not align.'
  printf '%s\n' '- runtime_smoke.js failure: generated report_generator app did not pass health, node execution, or report export.'
  printf '%s\n' '- local-skills Strategy KB unavailable: build script, kb_manifest, query script, python path is missing or query returns no passages.'
  printf '%s\n' '- api_doc_index unavailable: run api_doc_matcher/accept_cli.sh first, or pass API_DETAIL_DOC/API_VALIDATION_DOC.'
  printf '%s\n' '- report_generator shell gap: real CSV calculation remains a later enhancement; this baseline uses deterministic fixtures.'
  printf '%s\n' '- preview failure: local socket permission or port conflict should not block the non-preview baseline.'
}

print_paths() {
  printf '\nRun directory: %s\n' "$RUN_DIR"
  printf 'Generated app directory: %s\n' "$APP_DIR"
}

cleanup_preview() {
  if [[ "${PREVIEW_STARTED:-0}" == "1" ]]; then
    printf '\nStopping preview after script exit...\n'
    python3 -m growth_dev.cli app preview stop --run-id "$RUN_ID" >/dev/null 2>&1 || true
  fi
}

fail_step() {
  local exit_code="$1"
  printf '\nFAILED: %s\n' "$CURRENT_STEP" >&2
  if [[ -n "$CURRENT_COMMAND" ]]; then
    printf 'Failed command: %s\n' "$CURRENT_COMMAND" >&2
  fi
  printf 'Exit code: %s\n' "$exit_code" >&2
  print_passed_steps >&2
  print_paths >&2
  print_known_blockers >&2
  exit "$exit_code"
}

trap cleanup_preview EXIT

set_current_command() {
  CURRENT_COMMAND=""
  local part
  for part in "$@"; do
    CURRENT_COMMAND+=$(printf '%q ' "$part")
  done
  CURRENT_COMMAND="${CURRENT_COMMAND% }"
}

run_step() {
  CURRENT_STEP="$1"
  shift
  set_current_command "$@"
  printf '\n==> %s\n' "$CURRENT_STEP"
  printf '$ %s\n' "$CURRENT_COMMAND"
  if "$@"; then
    PASSED_STEPS+=("$CURRENT_STEP")
  else
    local exit_code=$?
    fail_step "$exit_code"
  fi
}

check_required_inputs() {
  local missing=0
  local file
  for file in "$SOURCE_DOC" "$PRD_FILE" "$TASK_YAML_PATH" "$DOMAIN_YAML_PATH" "$STRATEGY_KB_QUERY_SCRIPT"; do
    if [[ ! -f "$file" ]]; then
      printf 'Missing required file: %s\n' "$file" >&2
      missing=1
    fi
  done
  if [[ "$BUILD_STRATEGY_KB" == "1" ]]; then
    for file in "$STRATEGY_KB_BUILD_SCRIPT" "$STRATEGY_KB_COLLECTION"; do
      if [[ ! -f "$file" ]]; then
        printf 'Missing required Strategy KB build input: %s\n' "$file" >&2
        missing=1
      fi
    done
    if [[ ! -d "$STRATEGY_KB_OPENKB_ROOT" ]]; then
      printf 'Missing Strategy KB OpenKB root: %s\n' "$STRATEGY_KB_OPENKB_ROOT" >&2
      missing=1
    fi
  elif [[ ! -f "$STRATEGY_KB" ]]; then
    printf 'Missing required file: %s\n' "$STRATEGY_KB" >&2
    missing=1
  fi
  if [[ ! -x "$STRATEGY_KB_PYTHON" ]]; then
    printf 'Strategy KB python is not executable: %s\n' "$STRATEGY_KB_PYTHON" >&2
    missing=1
  fi
  if [[ -e "$RUN_DIR" ]]; then
    printf 'Run directory already exists: %s\n' "$RUN_DIR" >&2
    printf 'Use a new RUN_ID to avoid overwriting prior run artifacts.\n' >&2
    missing=1
  fi
  return "$missing"
}

check_local_commands() {
  local missing=0
  local command_name
  for command_name in python3 node; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
      printf 'Missing required command: %s\n' "$command_name" >&2
      missing=1
    fi
  done
  return "$missing"
}

check_api_doc_inputs() {
  if [[ -n "$API_DOC_INDEX" && -f "$API_DOC_INDEX" ]]; then
    return 0
  fi
  if [[ -n "$API_DETAIL_DOC" || -n "$API_VALIDATION_DOC" ]]; then
    local missing=0
    if [[ -z "$API_DETAIL_DOC" || ! -f "$API_DETAIL_DOC" ]]; then
      printf 'Missing API detail doc: %s\n' "${API_DETAIL_DOC:-<empty>}" >&2
      missing=1
    fi
    if [[ -z "$API_VALIDATION_DOC" || ! -f "$API_VALIDATION_DOC" ]]; then
      printf 'Missing API validation doc: %s\n' "${API_VALIDATION_DOC:-<empty>}" >&2
      missing=1
    fi
    return "$missing"
  fi
  printf 'API doc index is required for field mapping acceptance.\n' >&2
  printf 'Run api_doc_matcher/accept_cli.sh first, or pass API_DETAIL_DOC and API_VALIDATION_DOC.\n' >&2
  return 1
}

check_doc_to_skill_cli() {
  local output
  if ! output=$(env PYTHONPATH="$DOC_TO_SKILL_PYTHONPATH" "$DOC_TO_SKILL_PYTHON" -m doc_to_skill.cli --help 2>&1); then
    printf 'doc_to_skill CLI is not available in the current python3 environment.\n' >&2
    printf '\nOriginal output:\n%s\n' "$output" >&2
    printf '\nInstall dependencies manually, for example:\n' >&2
    printf 'python3 -m venv document-to-skill-engineering-package/.venv\n' >&2
    printf 'source document-to-skill-engineering-package/.venv/bin/activate\n' >&2
    printf 'python -m pip install -e "document-to-skill-engineering-package[dev]"\n' >&2
    return 1
  fi
}

check_skill_artifacts() {
  local missing=0
  local artifact
  for artifact in \
    "SKILL.md" \
    "skill.yaml" \
    "workflow.dag.yaml" \
    "data_requirements.yaml" \
    "tool_bindings.yaml" \
    "eval_rules.yaml" \
    "evidence_schema.yaml"; do
    if [[ ! -f "$SKILL_OUT/$artifact" ]]; then
      printf 'Missing compiled skill artifact: %s\n' "$SKILL_OUT/$artifact" >&2
      missing=1
    fi
  done
  return "$missing"
}

build_strategy_kb() {
  if [[ "$BUILD_STRATEGY_KB" != "1" ]]; then
    printf 'Strategy KB rebuild skipped. Using existing manifest: %s\n' "$STRATEGY_KB"
    return 0
  fi
  pushd "$HERMES_AGENT_ROOT" >/dev/null
  if "$STRATEGY_KB_PYTHON" "$STRATEGY_KB_BUILD_SCRIPT" \
    --collection "$STRATEGY_KB_COLLECTION" \
    --openkb-root "$STRATEGY_KB_OPENKB_ROOT" \
    --openkb-mode source-only \
    --output "$STRATEGY_KB_OUTPUT"; then
    popd >/dev/null
    return 0
  fi
  popd >/dev/null
  return 1
}

assert_strategy_kb_workflow_sections() {
  STRATEGY_KB="$STRATEGY_KB" python3 -c '
from pathlib import Path
import json
import os

manifest = json.loads(Path(os.environ["STRATEGY_KB"]).read_text(encoding="utf-8"))
pages = manifest.get("pages") if isinstance(manifest.get("pages"), list) else []
workflow_pages = [page for page in pages if isinstance(page, dict) and page.get("page_type") == "workflow_section"]
if len(workflow_pages) < 10:
    raise SystemExit(f"expected at least 10 workflow_section pages, got {len(workflow_pages)}")
first = next((page for page in workflow_pages if page.get("workflow_no") == 1), None)
if not first:
    raise SystemExit("missing workflow section page for flow 1")
text = str(first.get("full_text") or "")
for needle in ("### 1.1", "### 1.2", "### 1.3", "### 1.4", "《市场洞察项目定义表》"):
    if needle not in text:
        raise SystemExit(f"flow 1 workflow section missing {needle}")
if "流程2：行业大盘与热销商品分析" in text:
    raise SystemExit("flow 1 workflow section leaked flow 2")
print("strategy kb workflow sections ok:", len(workflow_pages))
'
}

assert_canvas_projection() {
  RUN_ID="$RUN_ID" python3 -c '
from pathlib import Path
import os

from growth_dev.team.app_generation_canvas import build_canvas_projection

run_id = os.environ["RUN_ID"]
projection = build_canvas_projection(run_id, runs_dir=Path("runs"), repo_root=Path("."))
statuses = {step["id"]: step["status"] for step in projection["flow_steps"]}
print("canvas statuses:", statuses)
expected = {
    "prototype_generation": "generated",
    "capability_verification": "verified",
    "delivery_version": "delivered",
}
errors = [
    f"{step_id}: expected {expected_status}, got {statuses.get(step_id)}"
    for step_id, expected_status in expected.items()
    if statuses.get(step_id) != expected_status
]
generating = [
    step_id
    for step_id in expected
    if statuses.get(step_id) == "generating"
]
if generating:
    errors.append("steps still generating: " + ", ".join(generating))
if errors:
    raise SystemExit("; ".join(errors))
'
}

assert_node_execution_view() {
  RUN_ID="$RUN_ID" APP_SLUG="$APP_SLUG" python3 -c '
from pathlib import Path
import json
import os

run_id = os.environ["RUN_ID"]
app_slug = os.environ["APP_SLUG"]
config_path = Path("runs") / run_id / "generated_apps" / app_slug / "app.config.json"
config = json.loads(config_path.read_text(encoding="utf-8"))
nodes = config.get("nodes") if isinstance(config.get("nodes"), list) else []
if not nodes:
    raise SystemExit("app.config.json has no nodes")
for node in nodes:
    view = node.get("node_execution_view")
    if not isinstance(view, dict):
        raise SystemExit(f"node {node.get('id')} missing node_execution_view")
first = nodes[0]["node_execution_view"]
if first.get("status") != "available":
    raise SystemExit(f"first node execution view not available: {first.get('status')}")
fields = [str(field.get("id") or field.get("label") or "") for field in first.get("action", {}).get("fields", []) if isinstance(field, dict)]
for field in ("分析类目", "分析产品线", "店铺阶段", "当前目标", "当前资源", "目标价格带", "目标人群", "分析周期"):
    if field not in fields:
        raise SystemExit(f"first node execution view missing field: {field}")
checks = [str(check.get("id") or "") for check in first.get("verification", {}).get("checks", []) if isinstance(check, dict)]
for check in ("类目是否清楚", "产品是否清楚", "分析周期是否清楚", "目标是否清楚"):
    if check not in checks:
        raise SystemExit(f"first node execution view missing check: {check}")
artifact = str(first.get("artifact", {}).get("title") or "")
if "市场洞察项目定义表" not in artifact:
    raise SystemExit(f"first node artifact title mismatch: {artifact}")
print("node execution view ok:", len(nodes), "nodes")
'
}

assert_node_view_model() {
  RUN_ID="$RUN_ID" APP_SLUG="$APP_SLUG" python3 -c '
from pathlib import Path
import json
import os

run_id = os.environ["RUN_ID"]
app_slug = os.environ["APP_SLUG"]
config_path = Path("runs") / run_id / "generated_apps" / app_slug / "app.config.json"
config = json.loads(config_path.read_text(encoding="utf-8"))
nodes = config.get("nodes") if isinstance(config.get("nodes"), list) else []
if not nodes:
    raise SystemExit("app.config.json has no nodes")

required_fields = [
    "input_model",
    "output_model",
    "execution_model",
    "evidence_model",
    "tool_model",
    "source_trace",
    "business_context",
    "node_execution_view",
]
for node in nodes:
    node_id = str(node.get("id") or "")
    for field in required_fields:
        if not isinstance(node.get(field), dict):
            raise SystemExit(f"node {node_id} missing {field}")
    outputs = node["output_model"].get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise SystemExit(f"node {node_id} missing output_model.outputs")
    if not any(isinstance(output, dict) and isinstance(output.get("schema"), dict) for output in outputs):
        raise SystemExit(f"node {node_id} missing output schema")
    if node.get("tool_model", {}).get("effective_mode") != "manual_upload_only":
        raise SystemExit(f"node {node_id} invalid tool mode")
    output_fields = node.get("output_field_requirements")
    if not isinstance(output_fields, list) or not output_fields:
        raise SystemExit(f"node {node_id} missing output_field_requirements")
    for item in output_fields:
        if not isinstance(item, dict):
            raise SystemExit(f"node {node_id} output_field_requirements must be objects")
        for field in ("output_id", "field_path", "field_name", "title", "description", "type", "required", "source_schema_ref"):
            if field not in item:
                raise SystemExit(f"node {node_id} output field missing {field}")
    mapping_context = node.get("data_mapping_context")
    if not isinstance(mapping_context, dict):
        raise SystemExit(f"node {node_id} missing data_mapping_context")
    if mapping_context.get("output_field_count") != len(output_fields):
        raise SystemExit(f"node {node_id} data_mapping_context output_field_count mismatch")
    analysis_view = node.get("analysis_node_view")
    if not isinstance(analysis_view, dict):
        raise SystemExit(f"node {node_id} missing analysis_node_view")
    if analysis_view.get("schema_version") != "analysis-node-view-v1":
        raise SystemExit(f"node {node_id} invalid analysis_node_view schema_version")
    if output_fields and node.get("data_requirements"):
        if analysis_view.get("node_kind") != "data_analysis":
            raise SystemExit(f"node {node_id} expected data_analysis analysis_node_view")
        data_output = analysis_view.get("data_output_model")
        if not isinstance(data_output, dict) or len(data_output.get("fields", [])) != len(output_fields):
            raise SystemExit(f"node {node_id} analysis data_output_model fields mismatch")
        for section in ("purpose_model", "input_model", "execution_plan", "insight_output_model", "verification_model", "source_trace"):
            if not isinstance(analysis_view.get(section), dict):
                raise SystemExit(f"node {node_id} analysis_node_view missing {section}")
    if node_id == "collect_top_products":
        names = [str(field.get("field_name") or "") for field in output_fields]
        expected = [
            "排名",
            "店铺名",
            "商品链接",
            "商品主图",
            "销量/支付买家数",
            "GMV/交易指数",
            "客单价",
            "价格带",
            "产品类型",
            "材质",
            "功能",
            "风格",
            "场景",
            "主卖点",
            "主图元素",
            "是否高增速",
            "爆款原因",
        ]
        missing = [name for name in expected if name not in names]
        if missing:
            raise SystemExit(f"collect_top_products missing business output fields: {missing}; got {names}")
        image_field = next((field for field in output_fields if str(field.get("field_name") or "") == "商品主图"), None)
        if not image_field or "视觉表达" not in str(image_field.get("description") or ""):
            raise SystemExit(f"collect_top_products 商品主图 lost business description: {image_field}")
        analysis_view = node.get("analysis_node_view", {})
        if "行业大盘" not in str(analysis_view.get("purpose_model", {}).get("title") or ""):
            raise SystemExit("collect_top_products analysis purpose title missing")
        if not analysis_view.get("input_model", {}).get("data_sources"):
            raise SystemExit("collect_top_products analysis input data_sources missing")
        if not analysis_view.get("execution_plan", {}).get("steps"):
            raise SystemExit("collect_top_products analysis execution steps missing")
        if not analysis_view.get("insight_output_model", {}).get("requirements"):
            raise SystemExit("collect_top_products analysis insight requirements missing")

data_nodes = [node for node in nodes if node.get("kind") == "data"]
if not any(
    isinstance(node.get("input_model", {}).get("required_data"), list)
    and node["input_model"]["required_data"]
    and isinstance(node["input_model"]["required_data"][0], dict)
    for node in data_nodes
):
    raise SystemExit("no data node exposes expanded required_data")
print("node view model ok:", len(nodes), "nodes with output field requirements")
'
}

assert_strategy_kb_business_context() {
  RUN_ID="$RUN_ID" APP_SLUG="$APP_SLUG" python3 -c '
from pathlib import Path
import json
import os

run_id = os.environ["RUN_ID"]
app_slug = os.environ["APP_SLUG"]
config_path = Path("runs") / run_id / "generated_apps" / app_slug / "app.config.json"
config = json.loads(config_path.read_text(encoding="utf-8"))
nodes = config.get("nodes") if isinstance(config.get("nodes"), list) else []
if not nodes:
    raise SystemExit("app.config.json has no nodes")

errors = []
for node in nodes:
    node_id = str(node.get("id") or "")
    context = node.get("business_context")
    if not isinstance(context, dict):
        errors.append(f"{node_id}: missing business_context")
        continue
    results = context.get("results")
    if context.get("status") != "available" or not isinstance(results, list) or not results:
        count = len(results) if isinstance(results, list) else "invalid"
        errors.append(f"{node_id}: status={context.get('status')} results={count}")
    if not context.get("query"):
        errors.append(f"{node_id}: missing query")
    trace = node.get("source_trace") if isinstance(node.get("source_trace"), dict) else {}
    if not trace.get("strategy_kb_query"):
        errors.append(f"{node_id}: missing source_trace strategy query")

first = nodes[0].get("business_context", {})
first_passages = "\n".join(str(item.get("passage") or "") for item in first.get("results", []) if isinstance(item, dict))
if "确定分析边界" not in first_passages:
    errors.append("first node passage does not mention 确定分析边界")

if errors:
    raise SystemExit("; ".join(errors))
print("strategy kb business context ok:", len(nodes), "nodes")
'
}

preview_start() {
  PREVIEW_STARTED=1
  python3 -m growth_dev.cli app preview start --run-id "$RUN_ID" --port "$PORT"
}

preview_stop() {
  python3 -m growth_dev.cli app preview stop --run-id "$RUN_ID"
  PREVIEW_STARTED=0
}

print_config

API_DOC_ARGS=()
if [[ -n "$API_DOC_INDEX" && -f "$API_DOC_INDEX" ]]; then
  API_DOC_ARGS=(--api-doc-index "$API_DOC_INDEX")
elif [[ -n "$API_DETAIL_DOC" || -n "$API_VALIDATION_DOC" ]]; then
  API_DOC_ARGS=(--api-detail-doc "$API_DETAIL_DOC" --api-validation-doc "$API_VALIDATION_DOC")
fi

run_step "Check required input files and run id" check_required_inputs
run_step "Check local CLI dependencies" check_local_commands
run_step "Check API doc matcher inputs" check_api_doc_inputs
run_step "Check doc_to_skill CLI" check_doc_to_skill_cli
run_step "Build Strategy KB workflow sections" build_strategy_kb
run_step "Assert Strategy KB workflow sections" assert_strategy_kb_workflow_sections
run_step \
  "Compile main business document into Skill package" \
  env PYTHONPATH="$DOC_TO_SKILL_PYTHONPATH" "$DOC_TO_SKILL_PYTHON" -m doc_to_skill.cli compile \
  --input "$SOURCE_DOC" \
  --output "$SKILL_OUT"
run_step "Check compiled Skill package artifacts" check_skill_artifacts
run_step \
  "Generate deterministic APP-generation run" \
  python3 -m growth_dev.cli app generate \
  --prd-file "$PRD_FILE" \
  --app-slug "$APP_SLUG" \
  --run-id "$RUN_ID" \
  --executor deterministic \
  --skill-dir "$SKILL_OUT" \
  --task-yaml-path "$TASK_YAML_PATH" \
  --domain-yaml-path "$DOMAIN_YAML_PATH" \
  --strategy-kb "$STRATEGY_KB" \
  --strategy-kb-query-script "$STRATEGY_KB_QUERY_SCRIPT" \
  --strategy-kb-python "$STRATEGY_KB_PYTHON" \
  --strategy-kb-top-k "$STRATEGY_KB_TOP_K" \
  "${API_DOC_ARGS[@]}" \
  --shell-kind report_generator \
  --foreground
run_step \
  "Show team status summary" \
  python3 -m growth_dev.cli team status --run-id "$RUN_ID" --summary
run_step \
  "Show workspace JSON" \
  python3 -m growth_dev.cli team workspace show --run-id "$RUN_ID" --json
run_step \
  "Validate app config" \
  python3 -m growth_dev.cli app appcheck config --run-id "$RUN_ID"
run_step \
  "Validate app acceptance" \
  python3 -m growth_dev.cli app appcheck acceptance --run-id "$RUN_ID"
run_step "Assert executable node view model" assert_node_view_model
run_step "Assert Strategy KB business context" assert_strategy_kb_business_context
run_step "Assert node execution view" assert_node_execution_view
run_step \
  "Check generated server syntax" \
  node --check "$SERVER_JS"
run_step \
  "Run generated runtime smoke" \
  node "$RUNTIME_SMOKE_JS"
run_step "Assert canvas projection step statuses" assert_canvas_projection

if [[ "$START_PREVIEW" == "1" ]]; then
  run_step "Start generated app preview" preview_start
  run_step "List active previews" python3 -m growth_dev.cli app preview list
  run_step "Stop generated app preview" preview_stop
else
  printf '\nPreview skipped. Set START_PREVIEW=1 to run preview start/list/stop.\n'
fi

printf '\nSUCCESS: deterministic CLI baseline completed.\n'
print_passed_steps
print_paths
print_known_blockers
