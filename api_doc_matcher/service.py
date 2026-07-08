"""stdin/stdout JSON 传输层：让 node 侧生成 app 以子进程"服务形式"复用 matcher.py。

协议与 shells/report_generator/engine/rule_engine.py 保持一致：
读 stdin 一个 JSON 请求，写 stdout 一个 JSON 响应，非法请求写 stderr 并非零退出。
本模块只做请求解码 + 结果编码，匹配逻辑全部委托 matcher.py / section_matcher.py，
不复制任何评分/别名规则，保证 matcher.py 是唯一事实源。

请求形状::

    {"op": "match_fields", "index_path": "...",
     "fields": [{"name": "主卖点", "description": "..."}, "排名"],
     "api_ids": ["api_012"], "source_strategy": "field_coverage_rerank"}

    {"op": "match_api", "index_path": "...", "query": "...", "top_k": 5}

    {"op": "match_section", "index_path": "...", "top_k": 8,
     "section": {"title": "...", "purpose": "...", "data_sources": [...],
                 "actions": [...], "output_fields": [{"name": "...", "description": "..."}]}}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .agent_adapter import load_api_entries
from .matcher import match_api_requirement, match_business_fields
from .models import ApiDocEntry, BusinessField, FieldMatchResult, SectionContext
from .section_matcher import match_section


def _business_fields(raw: object) -> list[BusinessField]:
    items = raw if isinstance(raw, list) else []
    return [BusinessField.from_any(item) for item in items]


def _section_context(raw: object) -> SectionContext:
    data = raw if isinstance(raw, dict) else {}
    return SectionContext(
        title=str(data.get("title", "")),
        purpose=str(data.get("purpose", "")),
        data_sources=[str(item) for item in data.get("data_sources", []) if str(item)],
        actions=[str(item) for item in data.get("actions", []) if str(item)],
        output_fields=_business_fields(data.get("output_fields")),
        source_path=str(data.get("source_path", "")),
    )


def _output_field_items(raw: object) -> list[dict]:
    items = raw if isinstance(raw, list) else []
    output_fields: list[dict] = []
    for index, item in enumerate(items):
        data = item if isinstance(item, dict) else {"field_name": str(item)}
        field_name = str(data.get("field_name") or data.get("title") or data.get("name") or "")
        if not field_name:
            continue
        output_fields.append(
            {
                "output_id": str(data.get("output_id", "")),
                "field_path": str(data.get("field_path") or data.get("path") or f"fields.{index}"),
                "field_name": field_name,
                "title": str(data.get("title") or field_name),
                "description": str(data.get("description") or data.get("field_description") or ""),
                "type": str(data.get("type") or "unknown"),
                "required": bool(data.get("required", True)),
                "source_schema_ref": str(data.get("source_schema_ref", "")),
                "canonical_field_name": str(data.get("canonical_field_name", "")),
                "source": str(data.get("source", "")),
                "source_trace": data.get("source_trace") if isinstance(data.get("source_trace"), dict) else {},
            }
        )
    return output_fields


def _section_from_business_context(raw_context: object, output_fields: list[dict]) -> tuple[str, SectionContext]:
    data = raw_context if isinstance(raw_context, dict) else {}
    node_id = str(data.get("node_id", ""))
    fields = [
        BusinessField(
            name=str(item["field_name"]),
            description=str(item.get("description", "")),
            required=bool(item.get("required", True)),
        )
        for item in output_fields
    ]
    return node_id, SectionContext(
        title=str(data.get("title", "")),
        purpose=str(data.get("purpose") or data.get("goal") or data.get("description") or ""),
        data_sources=[str(item) for item in data.get("data_sources", []) if str(item)],
        actions=[str(item) for item in data.get("actions", []) if str(item)],
        output_fields=fields,
        source_path=str(data.get("source_path", "")),
    )


def _api_asset(entry: ApiDocEntry) -> dict:
    response_fields = [
        {
            "path": field.path,
            "name": field.name,
            "type": field.type or "unknown",
            "desc": field.description,
            "description": field.description,
            "source": field.source,
        }
        for field in entry.response_fields
    ]
    request_params = [
        {
            "name": param.name,
            "type": param.type or "unknown",
            "required": param.required,
            "desc": param.description,
            "description": param.description,
            "position": param.position,
        }
        for param in entry.request_params
    ]
    return {
        "api_id": entry.api_id,
        "name": entry.name or entry.api_id,
        "method": entry.method,
        "path": entry.path,
        "domain": entry.analysis_domain,
        "capability": entry.business_module or entry.module,
        "module": entry.module,
        "business_module": entry.business_module,
        "analysis_domain": entry.analysis_domain,
        "verified_status": entry.verified_status,
        "quality_score": 1.0 if entry.verified_status == "success" else 0.6,
        "request_params": [param.to_dict() for param in entry.request_params],
        "response_fields": [field.to_dict() for field in entry.response_fields],
        "request_schema": {"query": request_params},
        "response_schema": {"root": "response", "fields": response_fields},
        "source_refs": entry.source_refs,
        "parse_warnings": entry.parse_warnings,
    }


def _field_status(raw_status: str) -> str:
    if raw_status == "matched":
        return "mapped"
    if raw_status == "suggested_needs_review":
        return "suggested"
    if raw_status == "derived_or_manual_required":
        return "derived_or_manual_required"
    return "missing"


def _is_covered(status: str) -> bool:
    return status in {"mapped", "suggested", "confirmed", "manual_fill", "derived", "derived_or_manual_required"}


def _field_coverage_plan(field_mapping: FieldMatchResult, output_fields: list[dict]) -> list[dict]:
    matches_by_name = {match.business_field: match for match in field_mapping.matches}
    plan: list[dict] = []
    for output_field in output_fields:
        field_name = str(output_field.get("field_name", ""))
        match = matches_by_name.get(field_name)
        status = _field_status(match.status) if match else "missing"
        mapped = status in {"mapped", "suggested"}
        derived = status == "derived_or_manual_required"
        plan.append(
            {
                **output_field,
                "field_description": output_field.get("description", ""),
                "source_api_id": str(match.api_id if mapped and match else ""),
                "source_api_name": str(match.api_name if mapped and match else ""),
                "source_field_path": str(match.api_field_path if mapped and match else ""),
                "api_field_path": str(match.api_field_path if mapped and match else ""),
                "api_field_name": str(match.api_field_name if mapped and match else ""),
                "api_field_type": str(match.api_field_type if mapped and match else ""),
                "source_role": "api_field" if mapped else "derived" if derived else "",
                "source_kind": "api_doc_index" if mapped else "pi_derived" if derived else "",
                "mapping_status": status,
                "status": status,
                "confidence": float(match.confidence if match else 0.0),
                "human_confirmed": False,
                "confirmed": False,
                "human_note": "",
                "match_basis": str(match.match_basis if match else "no_reliable_api_field"),
                "missing_reason": str(match.missing_reason if match else "候选 API 返回字段中没有找到可靠映射。"),
                "source_strategy": str(match.source_strategy if match else ""),
                "candidate_api_ids": list(match.candidate_api_ids if match else []),
                "candidate_field_options": [],
            }
        )
    return plan


def _coverage_summary(plan: list[dict]) -> dict:
    total = len(plan)
    mapped = sum(1 for item in plan if _is_covered(str(item.get("mapping_status", ""))))
    confirmed = sum(1 for item in plan if item.get("human_confirmed") or item.get("mapping_status") == "confirmed")
    missing_required = sum(
        1
        for item in plan
        if item.get("required", True) is not False and not _is_covered(str(item.get("mapping_status", "")))
    )
    derived = sum(1 for item in plan if item.get("mapping_status") == "derived_or_manual_required")
    return {
        "total": total,
        "mapped": mapped,
        "confirmed": confirmed,
        "missing_required": missing_required,
        "needs_human_confirmation": mapped - confirmed,
        "derived_or_manual_required": derived,
    }


def _derived_field_plan(plan: list[dict]) -> list[dict]:
    return [
        {
            "field_path": str(item.get("field_path", "")),
            "field_name": str(item.get("field_name", "")),
            "title": str(item.get("title") or item.get("field_name") or ""),
            "description": str(item.get("description", "")),
            "status": "needs_agent_or_manual_analysis",
            "source_kind": "pi_derived",
            "required_inputs": ["confirmed_api_field_mapping", "upstream_artifacts_or_sample_rows"],
            "available_evidence_fields": [],
            "suggested_analysis": "基于已确认 API 字段、商品图片/卖点/标题等证据，由 Agent 进行即席分析并生成草稿，人工确认后才进入产物。",
            "risks": ["不能由单个数仓 API 原生字段稳定提供，不得自动当作事实。"],
        }
        for item in plan
        if item.get("mapping_status") == "derived_or_manual_required"
    ]


def _op_match_fields(request: dict) -> dict:
    entries = load_api_entries(request["index_path"])
    result = match_business_fields(
        entries,
        _business_fields(request.get("fields")),
        api_ids=[str(item) for item in request.get("api_ids", []) if str(item)] or None,
        source_strategy=str(request.get("source_strategy", "")),
    )
    return {"schema_version": "business-field-match-v1", **result.to_dict()}


def _op_match_api(request: dict) -> dict:
    entries = load_api_entries(request["index_path"])
    matches = match_api_requirement(entries, str(request.get("query", "")), top_k=int(request.get("top_k", 5)))
    return {
        "schema_version": "business-api-match-v1",
        "query": str(request.get("query", "")),
        "matches": [match.to_dict() for match in matches],
    }


def _op_match_section(request: dict) -> dict:
    entries = load_api_entries(request["index_path"])
    result = match_section(entries, _section_context(request.get("section")), top_k=int(request.get("top_k", 8)))
    return result.to_dict()


def _op_match_business_context(request: dict) -> dict:
    entries = load_api_entries(request["index_path"])
    entries_by_id = {entry.api_id: entry for entry in entries}
    output_fields = _output_field_items(request.get("output_fields"))
    node_id, section = _section_from_business_context(request.get("business_context"), output_fields)
    result = match_section(entries, section, top_k=int(request.get("top_k", 8)))
    result_dict = result.to_dict()
    strategy = str(request.get("strategy") or "field_coverage_rerank")
    strategy_result = result_dict["strategy_results"].get(strategy) or result_dict["strategy_results"]["field_coverage_rerank"]
    selected_api_ids = [str(item) for item in strategy_result.get("selected_api_ids", []) if str(item)]
    selected_api_assets = [_api_asset(entries_by_id[api_id]) for api_id in selected_api_ids if api_id in entries_by_id]
    field_coverage_plan = _field_coverage_plan(result.field_mapping, output_fields)
    summary = _coverage_summary(field_coverage_plan)
    missing_or_derived = [
        {
            "field_name": str(item.get("field_name", "")),
            "field_path": str(item.get("field_path", "")),
            "status": str(item.get("mapping_status", "")),
            "reason": str(item.get("missing_reason", "")),
        }
        for item in field_coverage_plan
        if item.get("mapping_status") in {"missing", "derived_or_manual_required"}
    ]
    return {
        "schema_version": "business-context-field-mapping-v1",
        "provider": "api_doc_matcher",
        "node_id": node_id,
        "strategy": strategy,
        "business_context": {
            **(request.get("business_context") if isinstance(request.get("business_context"), dict) else {}),
            "output_fields": [field.to_dict() for field in section.output_fields],
        },
        "known_params": request.get("known_params") if isinstance(request.get("known_params"), dict) else {},
        "strategy_results": result_dict["strategy_results"],
        "strategy_field_mappings": result_dict["strategy_field_mappings"],
        "selected_api_ids": selected_api_ids,
        "candidate_apis": strategy_result.get("api_candidates", []),
        "selected_api_assets": selected_api_assets,
        "field_mapping": result.field_mapping.to_dict(),
        "field_coverage_plan": field_coverage_plan,
        "coverage_summary": summary,
        "business_field_coverage_metrics": {
            "business_field_coverage_score": result.field_mapping.business_field_coverage_score,
            "required_total": result.field_mapping.required_total,
            "covered_required": result.field_mapping.covered_required,
            "high_confidence": result.field_mapping.high_confidence,
            "confirmed_or_reviewable": result.field_mapping.confirmed_or_reviewable,
            "missing_required_fields": result.field_mapping.missing_required_fields,
        },
        "business_field_coverage_score": result.business_field_coverage_score,
        "derived_field_plan": _derived_field_plan(field_coverage_plan),
        "missing_or_derived_fields": missing_or_derived,
    }


_OPS = {
    "match_fields": _op_match_fields,
    "match_api": _op_match_api,
    "match_section": _op_match_section,
    "match_business_context": _op_match_business_context,
}


def handle(request: dict) -> dict:
    op = str(request.get("op", ""))
    handler = _OPS.get(op)
    if handler is None:
        raise ValueError(f"unknown op: {op!r}")
    if not request.get("index_path"):
        raise ValueError("index_path is required")
    if not Path(str(request["index_path"])).exists():
        raise ValueError(f"index not found: {request['index_path']}")
    return handler(request)


def main(argv: list[str] | None = None) -> int:
    raw = sys.stdin.read()
    try:
        request = json.loads(raw) if raw.strip() else {}
        response = handle(request)
    except Exception as error:  # noqa: BLE001 - 传输层统一把失败交给 node 兜底
        sys.stderr.write(f"{type(error).__name__}: {error}\n")
        return 1
    sys.stdout.write(json.dumps(response, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
