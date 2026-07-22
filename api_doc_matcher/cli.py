from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent_adapter import load_api_entries
from .indexer import build_index_from_files
from .matcher import match_api_requirement, match_business_fields
from .section_matcher import match_section
from .section_parser import parse_business_section_from_file


def _print_json(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _cmd_build_index(args: argparse.Namespace) -> int:
    detail_doc = Path(args.detail_doc)
    validation_doc = Path(args.validation_doc)
    if not detail_doc.exists():
        raise SystemExit(f"detail doc not found: {detail_doc}")
    if not validation_doc.exists():
        raise SystemExit(f"validation doc not found: {validation_doc}")
    extra_detail_docs = [Path(item) for item in args.extra_detail_doc]
    missing_extra = next((path for path in extra_detail_docs if not path.exists()), None)
    if missing_extra:
        raise SystemExit(f"extra detail doc not found: {missing_extra}")
    result = build_index_from_files(detail_doc, validation_doc, Path(args.out), extra_detail_docs=extra_detail_docs)
    _print_json(result.to_summary_dict())
    return 0


def _cmd_match_api(args: argparse.Namespace) -> int:
    entries = load_api_entries(args.index)
    _print_json(
        {
            "schema_version": "business-api-match-v1",
            "query": args.query,
            "matches": [match.to_dict() for match in match_api_requirement(entries, args.query, top_k=args.top_k)],
        }
    )
    return 0


def _cmd_match_fields(args: argparse.Namespace) -> int:
    entries = load_api_entries(args.index)
    result = match_business_fields(entries, _split_csv(args.fields), api_ids=_split_csv(args.api_ids))
    _print_json({"schema_version": "business-field-match-v1", **result.to_dict()})
    return 0


def _cmd_smoke(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    result = build_index_from_files(Path(args.detail_doc), Path(args.validation_doc), out_dir)
    api_matches = match_api_requirement(
        result.api_entries,
        args.query,
        top_k=args.top_k,
    )
    field_result = match_business_fields(
        result.api_entries,
        _split_csv(args.fields),
        api_ids=[match.api_id for match in api_matches],
    )
    api_payload = {
        "schema_version": "business-api-match-v1",
        "query": args.query,
        "matches": [match.to_dict() for match in api_matches],
    }
    field_payload = {"schema_version": "business-field-match-v1", **field_result.to_dict()}
    (out_dir / "match_api_smoke.json").write_text(
        json.dumps(api_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_dir / "match_fields_smoke.json").write_text(
        json.dumps(field_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _print_json(
        {
            "index": result.to_summary_dict(),
            "top_api_ids": [match.api_id for match in api_matches],
            "business_field_coverage_score": field_result.business_field_coverage_score,
            "missing_required_fields": field_result.missing_required_fields,
            "output_dir": str(out_dir),
        }
    )
    return 0


def _cmd_match_section(args: argparse.Namespace) -> int:
    entries = load_api_entries(args.index)
    section = parse_business_section_from_file(args.source_doc, args.section_title)
    result = match_section(entries, section, top_k=args.top_k)
    payload = result.to_dict()
    if args.strategy != "compare":
        strategy = payload["strategy_results"].get(args.strategy)
        if strategy is None:
            raise SystemExit(f"unknown strategy: {args.strategy}")
        payload["strategy_results"] = {args.strategy: strategy}
    _print_json(payload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="api-doc-matcher")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build-index", help="Parse two API docs and build derived indexes")
    build.add_argument("--detail-doc", required=True)
    build.add_argument("--validation-doc", required=True)
    build.add_argument("--extra-detail-doc", action="append", default=[])
    build.add_argument("--out", default="api_doc_matcher/build")
    build.set_defaults(func=_cmd_build_index)

    match_api = subparsers.add_parser("match-api", help="Match business language to API candidates")
    match_api.add_argument("--index", required=True)
    match_api.add_argument("--query", required=True)
    match_api.add_argument("--top-k", type=int, default=5)
    match_api.set_defaults(func=_cmd_match_api)

    match_fields = subparsers.add_parser("match-fields", help="Match business fields to API response fields")
    match_fields.add_argument("--index", required=True)
    match_fields.add_argument("--fields", required=True)
    match_fields.add_argument("--api-ids", default="")
    match_fields.set_defaults(func=_cmd_match_fields)

    smoke = subparsers.add_parser("smoke", help="Run build + API match + field match")
    smoke.add_argument("--detail-doc", required=True)
    smoke.add_argument("--validation-doc", required=True)
    smoke.add_argument("--out", default="api_doc_matcher/build")
    smoke.add_argument("--query", default="行业大盘与热销商品分析，需要类目排行和商品排行")
    smoke.add_argument("--fields", default="排名,商品名,店铺名,价格,支付买家数,交易指数")
    smoke.add_argument("--top-k", type=int, default=5)
    smoke.set_defaults(func=_cmd_smoke)

    section = subparsers.add_parser("match-section", help="Match a business document workflow section to APIs and fields")
    section.add_argument("--index", required=True)
    section.add_argument("--source-doc", required=True)
    section.add_argument("--section-title", required=True)
    section.add_argument(
        "--strategy",
        choices=["compare", "title_only", "enriched_context", "field_coverage_rerank"],
        default="compare",
    )
    section.add_argument("--top-k", type=int, default=8)
    section.set_defaults(func=_cmd_match_section)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
