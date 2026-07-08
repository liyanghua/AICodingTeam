#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DETAIL_DOC="${DETAIL_DOC:-/Users/yichen/Desktop/OntologyBrain/PI_AGENT/db-archaeologist-pi-spec-pack/docs/data_api/智能体数仓完整接口文档_修复后逐接口完整格式版.md}"
VALIDATION_DOC="${VALIDATION_DOC:-/Users/yichen/Desktop/OntologyBrain/PI_AGENT/db-archaeologist-pi-spec-pack/docs/data_api/智能体数仓完整接口文档_全量验证版.md}"
OUT_DIR="${OUT_DIR:-api_doc_matcher/build}"
SOURCE_DOC="${SOURCE_DOC:-document-to-skill-engineering-package/examples/source_docs/20260519市场分析洞察元策略.md}"
SECTION_TITLE="${SECTION_TITLE:-流程2：行业大盘与热销商品分析}"
QUERY="${QUERY:-行业大盘与热销商品分析，需要类目排行和商品排行}"
FIELDS="${FIELDS:-排名,商品名,店铺名,价格,支付买家数,交易指数}"

echo "== API Doc Matcher CLI Acceptance =="
echo "repo: $ROOT_DIR"
echo "detail_doc: $DETAIL_DOC"
echo "validation_doc: $VALIDATION_DOC"
echo "source_doc: $SOURCE_DOC"
echo "section_title: $SECTION_TITLE"
echo "out_dir: $OUT_DIR"
echo "query: $QUERY"
echo "fields: $FIELDS"
echo

if [[ ! -f "$DETAIL_DOC" ]]; then
  echo "Detail doc not found: $DETAIL_DOC" >&2
  exit 1
fi

if [[ ! -f "$VALIDATION_DOC" ]]; then
  echo "Validation doc not found: $VALIDATION_DOC" >&2
  exit 1
fi

if [[ ! -f "$SOURCE_DOC" ]]; then
  echo "Source doc not found: $SOURCE_DOC" >&2
  exit 1
fi

echo "==> Static checks"
python3 -m py_compile api_doc_matcher/*.py

echo "==> Unit tests"
python3 -m unittest tests.test_api_doc_matcher -v

echo "==> Build index"
python3 -m api_doc_matcher.cli build-index \
  --detail-doc "$DETAIL_DOC" \
  --validation-doc "$VALIDATION_DOC" \
  --out "$OUT_DIR"

echo "==> Match API"
python3 -m api_doc_matcher.cli match-api \
  --index "$OUT_DIR/api_doc_index.json" \
  --query "$QUERY" \
  --top-k 5 > "$OUT_DIR/match_api_smoke.json"

echo "==> Match fields"
API_IDS="$(python3 - "$OUT_DIR/match_api_smoke.json" <<'PY'
import json
import sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
print(",".join(item["api_id"] for item in data.get("matches", [])[:5]))
PY
)"

python3 -m api_doc_matcher.cli match-fields \
  --index "$OUT_DIR/api_doc_index.json" \
  --fields "$FIELDS" \
  --api-ids "$API_IDS" > "$OUT_DIR/match_fields_smoke.json"

echo "==> Match business section"
python3 -m api_doc_matcher.cli match-section \
  --index "$OUT_DIR/api_doc_index.json" \
  --source-doc "$SOURCE_DOC" \
  --section-title "$SECTION_TITLE" \
  --strategy compare \
  --top-k 8 > "$OUT_DIR/match_section_smoke.json"

echo "==> Coverage score"
python3 - "$OUT_DIR/match_fields_smoke.json" <<'PY'
import json
import sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
score = data["business_field_coverage_score"]
print(json.dumps({
  "business_field_coverage_score": score,
  "required_total": data["required_total"],
  "covered_required": data["covered_required"],
  "high_confidence": data["high_confidence"],
  "missing_required_fields": data["missing_required_fields"],
}, ensure_ascii=False, indent=2))
if score < 0.60:
    raise SystemExit(f"business_field_coverage_score below P0 smoke threshold: {score} < 0.60")
PY

echo "==> Section coverage score"
python3 - "$OUT_DIR/match_section_smoke.json" <<'PY'
import json
import sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
fields = data["section_context"]["output_fields"]
score = data["business_field_coverage_score"]
summary = {
  "section_title": data["section_context"]["title"],
  "output_field_count": len(fields),
  "business_field_coverage_score": score,
  "selected_api_ids": data["strategy_results"]["field_coverage_rerank"]["selected_api_ids"],
  "missing_or_derived_fields": data["missing_or_derived_fields"],
}
print(json.dumps(summary, ensure_ascii=False, indent=2))
if len(fields) != 17:
    raise SystemExit(f"expected 17 output fields for flow2, got {len(fields)}")
if score < 0.75:
    raise SystemExit(f"section business_field_coverage_score below target: {score} < 0.75")
PY

echo "==> Secret leak check"
if command -v rg >/dev/null 2>&1; then
  if rg "tLeb3AGe|658d65aee9e9131342e3031af2f02650de7a71ad|secret-key|secret-code" "$OUT_DIR" >/dev/null; then
    echo "Secret-like value leaked into $OUT_DIR" >&2
    exit 1
  fi
else
  echo "rg not found; skipped secret leak check"
fi

echo
echo "Acceptance passed."
echo "Index: $OUT_DIR/api_doc_index.json"
echo "API smoke: $OUT_DIR/match_api_smoke.json"
echo "Field smoke: $OUT_DIR/match_fields_smoke.json"
echo "Section smoke: $OUT_DIR/match_section_smoke.json"
