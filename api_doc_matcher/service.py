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
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .agent_adapter import load_api_entries
from .matcher import _field_score, match_api_requirement, match_business_fields
from .models import ApiDocEntry, ApiParam, BusinessField, FieldMatchResult, SectionContext
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
        "verified_url_path": entry.verified_url_path,
        "default_params": entry.default_params,
        "quality_score": 1.0 if entry.verified_status == "success" else 0.6,
        "request_params": [param.to_dict() for param in entry.request_params],
        "response_fields": [field.to_dict() for field in entry.response_fields],
        "request_schema": {"query": request_params},
        "response_schema": {"root": entry.response_root or "data.result[]", "fields": response_fields},
        "source_refs": entry.source_refs,
        "parse_warnings": entry.parse_warnings,
    }


def _api_response_field_catalog(entries: list[ApiDocEntry]) -> list[dict]:
    catalog: list[dict] = []
    for entry in entries:
        for field in entry.response_fields:
            catalog.append(
                {
                    "source_api_id": entry.api_id,
                    "source_api_name": entry.name or entry.api_id,
                    "source_field_path": field.path,
                    "api_field_name": field.name,
                    "api_field_type": field.type or "unknown",
                    "description": field.description,
                    "field_source": field.source,
                }
            )
    return catalog


def _compact_token(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.lower())


def _param_tokens(value: str) -> set[str]:
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or ""))
    lower = camel_split.lower()
    tokens = {item.strip() for item in re.split(r"[^a-z0-9\u4e00-\u9fff]+", lower) if item.strip()}
    compact = _compact_token(lower)
    if compact:
        tokens.add(compact)
    return tokens


def _has_any(tokens: set[str], values: list[str]) -> bool:
    return any(value in tokens for value in values)


def _category_param_role(param: ApiParam) -> str:
    name = param.name.lower()
    compact = _compact_token(param.name)
    tokens = _param_tokens(param.name)
    desc = param.description.lower()
    id_names = {"cid", "cateid", "cate_id", "categoryid", "category_id", "catid", "cat_id"}
    name_names = {"catename", "cate_name", "categoryname", "category_name", "tertiarycategory", "tertiary_category"}
    desc_says_id = "类目id" in desc or "类目ID" in param.description or re.search(r"category\s*id|cate\s*id", desc)
    desc_says_name = "类目名称" in desc or "品类名称" in desc or "三级类目" in desc or "叶子类目" in desc
    if compact in id_names or _has_any(tokens, ["cid", "categoryid", "category_id", "cateid", "cate_id", "catid", "cat_id"]) or desc_says_id:
        return "category_id"
    if compact in name_names or _has_any(tokens, ["categoryname", "category_name", "catename", "cate_name", "tertiarycategory", "tertiary_category"]) or desc_says_name:
        return "category_name"
    if "类目" in desc or "品类" in desc or _has_any(tokens, ["category", "cate", "cat"]):
        return "category_name"
    return ""


def _field_path_looks_like_category_name(field) -> bool:
    text = f"{field.path} {field.name} {field.description}".lower()
    return bool(re.search(r"category[_\s-]*name|cate[_\s-]*name|cid[_\s-]*name|类目名称|品类名称|三级类目|叶子类目", text))


def _field_path_looks_like_category_id(field) -> bool:
    text = f"{field.path} {field.name} {field.description}".lower()
    return bool(re.search(r"(^|[.\s_\[\]-])cid($|[.\s_\[\]-])|category[_\s-]*id|cate[_\s-]*id|cat[_\s-]*id|类目\s*id", text))


def _entry_needs_unknown_category_id(entry: ApiDocEntry, known_params: dict) -> bool:
    _, known_id = _first_known(known_params, ["cid", "category_id", "cate_id", "cat_id", "类目ID", "类目id"])
    if known_id:
        return False
    return any(_category_param_role(param) == "category_id" and param.required for param in entry.request_params)


def _resolver_domain_score(entry: ApiDocEntry) -> float:
    text = f"{entry.name} {entry.module} {entry.business_module} {entry.analysis_domain}".lower()
    score = 0.0
    for token in ["类目", "品类", "category", "cate"]:
        if token in text:
            score += 0.18
    for token in ["商品", "行业", "goods", "product", "industry"]:
        if token in text:
            score += 0.06
    return min(score, 0.35)


def _resolver_semantic_mode(entry: ApiDocEntry) -> tuple[str, str]:
    text = f"{entry.name} {entry.module} {entry.business_module} {entry.analysis_domain} {entry.path}".lower()
    unrelated_tokens = [
        "数据来源",
        "指标关系",
        "页面模块",
        "数据治理",
        "社媒",
        "人群",
        "画像",
        "persona",
        "social_media",
    ]
    if any(token.lower() in text for token in unrelated_tokens):
        return "unsuitable", "unrelated_business_domain"
    category_name_params = [param for param in entry.request_params if _category_param_role(param) == "category_name"]
    if category_name_params:
        return "direct_name_lookup", "request_accepts_category_name"
    if "类目" in text and "解析" in text:
        return "unfiltered_category_dictionary", "category_resolver_semantics"
    dictionary_tokens = ["类目列表", "类目字典", "类目下拉", "类目结构", "类目解析", "category_list", "taxonomy", "商品列表", "商品维表"]
    if any(token.lower() in text for token in dictionary_tokens):
        return "unfiltered_category_dictionary", "category_dictionary_semantics"
    return "unsuitable", "schema_only_without_resolver_semantics"


def _load_category_entities(index_path: str) -> list[dict]:
    try:
        payload = json.loads(Path(index_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in payload.get("category_entities", []) if isinstance(item, dict)]


def _normalize_category_text(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def _category_candidate_score(requested_name: str, entity: dict) -> tuple[float, str]:
    target = _normalize_category_text(requested_name)
    canonical = _normalize_category_text(entity.get("canonical_name"))
    aliases = [_normalize_category_text(item) for item in entity.get("aliases", []) if str(item).strip()]
    evidence_texts = [_normalize_category_text(item) for item in entity.get("evidence_texts", []) if str(item).strip()]
    if target and canonical == target:
        return 1.0, "exact"
    if target and target in aliases:
        return 0.96, "alias"
    evidence_hits = sum(1 for text in evidence_texts if target and target in text)
    if evidence_hits >= 2:
        return 0.92, "product_title_evidence"
    if evidence_hits == 1:
        return 0.78, "product_title_evidence"
    if target and canonical and (target in canonical or canonical in target):
        return 0.82, "api_evidence"
    return 0.0, ""


def _resolve_category_candidates(index_path: str, requested_name: str, category_id: str = "") -> dict:
    requested_name = str(requested_name or "").strip()
    category_id = str(category_id or "").strip()
    if category_id:
        return {
            "schema_version": "business-category-resolution-v2",
            "provider": "api_doc_matcher",
            "requested_name": requested_name,
            "canonical_name": requested_name,
            "category_id": category_id,
            "status": "resolved",
            "match_kind": "direct_id",
            "confidence": 1.0,
            "evidence_sources": [],
            "alternatives": [],
            "blocked_reason": "",
        }
    ranked: list[dict] = []
    for entity in _load_category_entities(index_path):
        score, match_kind = _category_candidate_score(requested_name, entity)
        if score <= 0:
            continue
        ranked.append(
            {
                "canonical_name": str(entity.get("canonical_name", "")),
                "category_id": str(entity.get("category_id", "")),
                "confidence": round(score, 4),
                "match_kind": match_kind,
                "evidence_count": int(entity.get("evidence_count", 0) or 0),
                "evidence_sources": list(entity.get("evidence_sources", [])),
            }
        )
    ranked.sort(key=lambda item: (-item["confidence"], -item["evidence_count"], item["canonical_name"], item["category_id"]))
    if not ranked:
        return {
            "schema_version": "business-category-resolution-v2",
            "provider": "api_doc_matcher",
            "requested_name": requested_name,
            "canonical_name": "",
            "category_id": "",
            "status": "blocked",
            "match_kind": "",
            "confidence": 0.0,
            "evidence_sources": [],
            "alternatives": [],
            "blocked_reason": "category_not_found",
        }
    best = ranked[0]
    conflicting_top = any(
        item["category_id"] != best["category_id"] and abs(item["confidence"] - best["confidence"]) < 0.05
        for item in ranked[1:]
    )
    status = "resolved" if best["confidence"] >= 0.9 and not conflicting_top else "needs_confirmation"
    return {
        "schema_version": "business-category-resolution-v2",
        "provider": "api_doc_matcher",
        "requested_name": requested_name,
        "canonical_name": best["canonical_name"],
        "category_id": best["category_id"],
        "status": status,
        "match_kind": best["match_kind"],
        "confidence": best["confidence"],
        "evidence_sources": best["evidence_sources"],
        "alternatives": ranked[1:5],
        "blocked_reason": "" if status == "resolved" else "category_confirmation_required",
    }


def _resolver_request_binding_status(entry: ApiDocEntry, known_params: dict, execution_date: date, timezone: str) -> dict:
    binding = _bind_request_params_for_entry(entry, known_params, execution_date, timezone)
    missing_required = [str(item) for item in binding.get("missing_required_params", []) if str(item)]
    return {
        "status": "blocked" if missing_required else "ready",
        "params": binding.get("params", {}),
        "missing_required_params": missing_required,
        "request_param_mapping": binding.get("request_param_mapping", []),
    }


def _first_known(known_params: dict, keys: list[str]) -> tuple[str, str]:
    for key in keys:
        if key in known_params and known_params[key] is not None and str(known_params[key]).strip():
            return key, str(known_params[key]).strip()
    return "", ""


def _parse_execution_date(raw: object, timezone: str) -> date:
    text = str(raw or "").strip()
    if text:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                pass
    try:
        return datetime.now(ZoneInfo(timezone or "Asia/Shanghai")).date()
    except Exception:  # noqa: BLE001 - ZoneInfo may be unavailable for custom timezone ids
        return date.today()


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def _period_bounds(period: str, execution_date: date) -> dict:
    text = str(period or "").strip()
    normalized = {
        "raw": text,
        "start_date": execution_date.isoformat(),
        "end_date": execution_date.isoformat(),
        "month": execution_date.strftime("%Y-%m"),
        "source": "execution_date_default",
    }
    if not text:
        return normalized
    exact_day = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if exact_day:
        day = date(int(exact_day.group(1)), int(exact_day.group(2)), int(exact_day.group(3)))
        return {
            **normalized,
            "start_date": day.isoformat(),
            "end_date": day.isoformat(),
            "month": day.strftime("%Y-%m"),
            "source": "period_exact_date",
        }
    exact_month = re.search(r"(\d{4})[-/](\d{1,2})", text)
    if exact_month:
        year = int(exact_month.group(1))
        month = int(exact_month.group(2))
        start = date(year, month, 1)
        end = min(_month_end(year, month), execution_date)
        return {
            **normalized,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "month": f"{year:04d}-{month:02d}",
            "source": "period_exact_month",
        }
    relative_days = re.search(r"近\s*(\d+)\s*天", text)
    if relative_days:
        days = max(1, int(relative_days.group(1)))
        start = execution_date - timedelta(days=days - 1)
        return {
            **normalized,
            "start_date": start.isoformat(),
            "end_date": execution_date.isoformat(),
            "month": execution_date.strftime("%Y-%m"),
            "source": f"period_last_{days}_days",
        }
    if "昨天" in text:
        day = execution_date - timedelta(days=1)
        return {**normalized, "start_date": day.isoformat(), "end_date": day.isoformat(), "month": day.strftime("%Y-%m"), "source": "period_yesterday"}
    if "今天" in text or "今日" in text:
        return {**normalized, "source": "period_today"}
    if "月" in text:
        start = execution_date.replace(day=1)
        return {**normalized, "start_date": start.isoformat(), "source": "period_month_to_date"}
    if "季" in text:
        quarter_start_month = ((execution_date.month - 1) // 3) * 3 + 1
        start = date(execution_date.year, quarter_start_month, 1)
        return {**normalized, "start_date": start.isoformat(), "source": "period_quarter_to_date"}
    return {**normalized, "source": "period_unparsed_execution_date_default"}


def _date_role(param: ApiParam) -> str:
    name = param.name.lower()
    compact = _compact_token(name)
    tokens = _param_tokens(param.name)
    desc = param.description.lower()
    audit_hint = re.search(r"更新|修改|创建|同步|入库|最后|最近|update|updated|modified|created|sync", desc)
    audit_name = re.search(r"(^|[_-])(update|updated|modify|modified|create|created|sync|timestamp)([_-]|$)", name)
    if audit_hint or audit_name or compact in {"updatetime", "updatedat", "createtime", "createdat", "modifiedtime", "modifiedat"}:
        return ""
    if "月份" in desc or "统计月份" in desc or compact in {"statistdate", "statisticsdate", "statdate", "month", "bizmonth"} or _has_any(tokens, ["month"]):
        return "month"
    if compact in {"daterange", "dateinterval", "timerange", "period"} or "日期范围" in desc or "时间范围" in desc:
        return "date_range"
    if compact in {"startdate", "begindate", "fromdate"} or _has_any(tokens, ["start", "begin", "from"]) or "开始日期" in desc:
        return "start_date"
    if compact in {"enddate", "todate"} or _has_any(tokens, ["end", "to"]) or "结束日期" in desc:
        return "end_date"
    if compact in {"dealdate", "bizdate", "dt", "date", "day"} or "交易日期" in desc or "业务日期" in desc or "日期" in desc:
        return "single_date"
    return ""


def _business_param_for_api_param(param: ApiParam) -> str:
    tokens = _param_tokens(param.name)
    desc = param.description.lower()
    if _has_any(tokens, ["pagesize", "page_size", "limit", "top"]) or (tokens & {"size"} and re.search(r"页|分页|条数|数量|limit|page", desc)):
        return "page_size"
    if _has_any(tokens, ["page", "pagenum", "pageindex", "pageno", "page_no"]) or re.search(r"页码|page\s*(num|no|index)", desc):
        return "page"
    if _date_role(param):
        return "period"
    if _category_param_role(param):
        return "category"
    if _has_any(tokens, ["productline", "product_line"]) or "产品线" in desc:
        return "product_line"
    if _has_any(tokens, ["priceband", "price_band"]) or "价格带" in desc:
        return "price_band"
    return ""


def _business_label(name: str) -> str:
    return {
        "category": "分析类目",
        "period": "分析周期",
        "product_line": "分析产品线",
        "price_band": "价格带",
        "page": "页码",
        "page_size": "条数",
        "data_source": "详情数据源",
    }.get(name, "")


def _date_value_for_role(role: str, bounds: dict) -> str:
    if role == "start_date":
        return str(bounds["start_date"])
    if role == "end_date":
        return str(bounds["end_date"])
    if role == "month":
        return str(bounds["month"])
    if role == "date_range":
        return f"{bounds['start_date']},{bounds['end_date']}"
    return str(bounds["end_date"])


def _api_execution_role(entry: ApiDocEntry) -> str:
    text = f"{entry.name} {entry.module} {entry.business_module} {entry.analysis_domain} {entry.path}".lower()
    request_names = {_compact_token(param.name) for param in entry.request_params}
    response_names = {_compact_token(field.name) for field in entry.response_fields}
    has_product_id_input = bool(request_names & {
        "goodsid", "goodsidlist", "itemid", "itemidlist",
        "productid", "productidlist", "commodityid", "commodityidlist",
    })
    has_product_id_output = bool(response_names & {"goodsid", "itemid", "productid", "commodityid"})
    detail_fields = {"corematerial", "usagescene", "sellingpointsummary", "goodsspecparams"}
    feedback_fields = {"comment", "questioncontent", "answercount"}
    competitor_fields = {"shopname", "shop", "goodshref", "goodsurl", "price", "unitprice", "mainsellingpoint", "sellingpoint"}
    if has_product_id_input and has_product_id_output and len(response_names & detail_fields) >= 2:
        return "product_detail_enrichment"
    if has_product_id_input and has_product_id_output and response_names & feedback_fields:
        return "product_feedback_enrichment"
    if has_product_id_output and ("competition_pattern" in text or "竞争格局" in text) and len(response_names & competitor_fields) >= 3:
        return "competitor_landscape_primary"
    if ("热销商品" in text or "hot" in text) and ("交易总量" in text or "trade_category_goods" in text):
        return "topn_trade_total_primary"
    if ("热销商品" in text or "hot" in text) and ("交易增速" in text or "speed_category_goods" in text):
        return "growth_enrichment"
    return "general"


def _api_time_grain(entry: ApiDocEntry) -> str:
    text = f"{entry.name} {entry.path}".lower()
    has_range_params = {param.name for param in entry.request_params}.issuperset({"start_date", "end_date"})
    if has_range_params and (entry.name.strip().startswith("月-") or entry.path.rstrip("/").endswith("_m")):
        return "month"
    return "range"


def _previous_month_start(value: date) -> date:
    return (value.replace(day=1) - timedelta(days=1)).replace(day=1)


def _monthly_period_bounds(period: str, execution_date: date) -> dict:
    text = str(period or "").strip()
    exact_day = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    exact_month = re.search(r"(\d{4})[-/](\d{1,2})", text)
    if exact_day:
        month_start = date(int(exact_day.group(1)), int(exact_day.group(2)), 1)
        source = "explicit_month"
    elif exact_month:
        month_start = date(int(exact_month.group(1)), int(exact_month.group(2)), 1)
        source = "explicit_month"
    else:
        month_start = _previous_month_start(execution_date)
        source = "latest_complete_month"
    return {
        "raw": text,
        "start_date": month_start.isoformat(),
        "end_date": month_start.isoformat(),
        "month": month_start.strftime("%Y-%m"),
        "source": source,
        "grain": "month",
        "max_fallback_months": 6,
    }


def _category_resolution(known_params: dict) -> dict:
    category_key, category_name = _first_known(known_params, ["category", "分析类目", "类目", "category_name", "cate_name", "tertiary_category"])
    id_key, category_id = _first_known(known_params, ["cid", "category_id", "cate_id", "cat_id", "类目ID", "类目id"])
    status = "resolved" if category_id else "needs_input" if category_name else "blocked"
    return {
        "schema_version": "category-resolution-v1",
        "status": status,
        "category_name": category_name,
        "category_id": category_id,
        "source_param": id_key or category_key,
        "source_api_id": "",
        "source_field_paths": {},
        "confidence": 1.0 if category_id else 0.0,
        "alternatives": [],
        "evidence_ref": "",
        "blocked_reason": "" if category_id else "category_id_required",
    }


def _bind_request_params_for_entry(entry: ApiDocEntry, known_params: dict, execution_date: date, timezone: str) -> dict:
    params: dict[str, object] = {}
    mappings: list[dict] = []
    missing_required: list[str] = []
    dropped_optional: list[str] = []
    category_resolution = _category_resolution(known_params)
    _, period = _first_known(known_params, ["period", "分析周期", "周期", "analysis_period", "date_period"])
    time_grain = _api_time_grain(entry)
    bounds = _monthly_period_bounds(period, execution_date) if time_grain == "month" else _period_bounds(period, execution_date)
    execution_role = _api_execution_role(entry)
    if "grain" not in bounds:
        bounds["grain"] = time_grain

    for param in entry.request_params:
        api_param = param.name.strip()
        if not api_param:
            continue
        required = bool(param.required)
        business_param = _business_param_for_api_param(param)
        value: object = ""
        status = "optional"
        source = ""
        binding_method = ""
        confidence = 0.0
        missing_reason = ""
        candidate_values: list[str] = []
        date_role = _date_role(param)
        category_role = _category_param_role(param)
        compact_param = _compact_token(api_param)

        if execution_role in {"product_detail_enrichment", "product_feedback_enrichment"} and compact_param in {"tenantid", "userid"}:
            status = "runtime_injected"
            source = "worker_env"
            binding_method = "verified_call_identity_injection"
            confidence = 1.0
        elif execution_role in {"product_detail_enrichment", "product_feedback_enrichment"} and compact_param in {
            "goodsid", "goodsidlist", "itemid", "itemidlist", "productid", "productidlist", "commodityid", "commodityidlist"
        }:
            status = "deferred"
            source = "confirmed_rows" if execution_role == "product_feedback_enrichment" else "primary_rows"
            binding_method = "dependent_row_binding"
            confidence = 1.0
        elif api_param in known_params and known_params[api_param] is not None and str(known_params[api_param]).strip():
            value = str(known_params[api_param]).strip()
            status = "bound"
            source = "known_params_api_param"
            binding_method = "direct_api_param"
            confidence = 1.0
            if not business_param:
                business_param = api_param
        elif category_role == "category_id":
            _, known_id = _first_known(known_params, ["cid", "category_id", "cate_id", "cat_id", "类目ID", "类目id"])
            if known_id:
                value = known_id
                status = "bound"
                source = "known_params_category_id"
                binding_method = "category_id_direct"
                confidence = 1.0
            else:
                status = "missing" if required else "optional"
                business_param = "category"
                missing_reason = "缺少类目ID，不能把中文类目名绑定到 cid/category_id/cate_id"
        elif category_role == "category_name":
            _, known_name = _first_known(known_params, ["category", "分析类目", "类目", "category_name", "cate_name", "tertiary_category"])
            if known_name:
                value = known_name
                status = "bound"
                source = "upstream_artifact_or_known_params"
                binding_method = "category_name_direct"
                confidence = 0.95
                business_param = "category"
        elif date_role:
            value = _date_value_for_role(date_role, bounds)
            status = "bound"
            source = "derived"
            binding_method = "api_doc_matcher_date_normalization"
            confidence = 0.92
            business_param = "period"
        elif business_param == "page":
            value = 1
            status = "bound"
            source = "default"
            binding_method = "deterministic_default"
            confidence = 0.8
        elif business_param == "page_size":
            value = 300
            status = "bound"
            source = "default"
            binding_method = "deterministic_default"
            confidence = 0.8
        elif execution_role == "product_detail_enrichment" and compact_param == "datasource":
            business_param = "data_source"
            status = "runtime_resolved"
            source = "worker_runtime"
            binding_method = "detail_source_calibration"
            confidence = 1.0
            documented_default = str(entry.default_params.get(api_param) or "qbt").strip()
            candidate_values = ["sycm"]
            if documented_default and documented_default not in candidate_values:
                candidate_values.append(documented_default)
        else:
            known_key, known_value = _first_known(
                known_params,
                {
                    "category": ["category", "分析类目", "类目"],
                    "product_line": ["product_line", "分析产品线", "产品线"],
                    "price_band": ["price_band", "目标价格带", "价格带"],
                }.get(business_param, []),
            )
            if known_value:
                value = known_value
                status = "bound"
                source = "upstream_artifact_or_known_params"
                binding_method = "deterministic_alias"
                confidence = 0.9
                _ = known_key

        if status == "bound":
            params[api_param] = value
        elif required and status not in {"deferred", "runtime_injected", "runtime_resolved"}:
            status = status if status == "missing" else "missing"
            missing_required.append(api_param)
            missing_reason = missing_reason or "缺少可绑定业务参数"
        elif status == "optional":
            dropped_optional.append(api_param)

        mappings.append(
            {
                "api_param": api_param,
                "api_param_path": f"query.{api_param}",
                "api_param_type": param.type or "unknown",
                "business_param": business_param,
                "business_param_label": _business_label(business_param),
                "source": source,
                "source_ref": "",
                "value": value,
                "required": required,
                "status": status,
                "binding_method": binding_method,
                "confidence": confidence,
                "missing_reason": missing_reason,
                "candidate_values": candidate_values,
                "human_confirmed": False,
                "category_param_role": category_role,
                "date_conversion_rule": date_role if binding_method == "api_doc_matcher_date_normalization" else "",
                "execution_date": execution_date.isoformat() if binding_method == "api_doc_matcher_date_normalization" else "",
                "timezone": timezone if binding_method == "api_doc_matcher_date_normalization" else "",
                "normalized_period": bounds if binding_method == "api_doc_matcher_date_normalization" else {},
            }
        )

    return {
        "schema_version": "request-param-binding-v1",
        "provider": "api_doc_matcher",
        "api_id": entry.api_id,
        "api_name": entry.name or entry.api_id,
        "known_params": known_params,
        "execution_date": execution_date.isoformat(),
        "timezone": timezone,
        "normalized_period": bounds,
        "category_resolution": category_resolution,
        "params": params,
        "request_param_mapping": mappings,
        "missing_required_params": missing_required,
        "dropped_optional_params": dropped_optional,
        "execution_role": execution_role,
        "depends_on_role": (
            "topn_trade_total_primary" if execution_role == "product_detail_enrichment"
            else "confirmed_top_products" if execution_role == "product_feedback_enrichment"
            else ""
        ),
        "input_binding": (
            {"goods_id": "primary_rows[].goods_id"} if execution_role == "product_detail_enrichment"
            else {
                "goods_id": "confirmed_rows[].goods_id",
                "goods_id_list": "confirmed_rows[].goods_id",
            } if execution_role == "product_feedback_enrichment"
            else {}
        ),
    }


def _candidate_field_options(output_field: dict, entries: list[ApiDocEntry], *, limit: int = 8) -> list[dict]:
    business_field = BusinessField(
        name=str(output_field.get("field_name") or output_field.get("title") or ""),
        description=str(output_field.get("description") or output_field.get("field_description") or ""),
        required=bool(output_field.get("required", True)),
    )
    candidates: list[dict] = []
    for entry in entries:
        for field in entry.response_fields:
            score, basis = _field_score(business_field, field)
            if score <= 0:
                continue
            candidates.append(
                {
                    "source_api_id": entry.api_id,
                    "source_api_name": entry.name or entry.api_id,
                    "source_field_path": field.path,
                    "api_field_name": field.name,
                    "api_field_type": field.type or "unknown",
                    "description": field.description,
                    "confidence": round(score, 4),
                    "match_basis": basis,
                }
            )
    candidates.sort(key=lambda item: (-float(item["confidence"]), item["source_api_id"], item["source_field_path"]))
    return candidates[:limit]


def _field_status(raw_status: str) -> str:
    if raw_status == "matched":
        return "mapped"
    if raw_status == "suggested_needs_review":
        return "suggested"
    if raw_status == "derived_or_manual_required":
        return "derived_or_manual_required"
    return "missing"


EXECUTION_DERIVED_FIELDS = {
    "价格带",
    "产品类型",
    "材质",
    "场景",
    "功能",
    "风格",
    "主图元素",
    "爆款原因",
    "root_terms",
    "demand_type",
    "词根",
    "需求类型",
    "competitor_product_url",
    "sentiment",
    "painpoint_type",
    "competitor_type",
    "visual_structure",
    "review_painpoints",
    "competitor_strength",
}

EXECUTION_FIELD_PREFERENCES = {
    "排名": ("topn_trade_total_primary", "rank"),
    "店铺名": ("topn_trade_total_primary", "shop_name"),
    "商品链接": ("topn_trade_total_primary", "goods_url"),
    "商品主图": ("topn_trade_total_primary", "goods_img"),
    "销量/支付买家数": ("topn_trade_total_primary", "num_payers_interval"),
    "GMV/交易指数": ("topn_trade_total_primary", "sales_revenue"),
    "客单价": ("topn_trade_total_primary", "unit_price"),
    "主卖点": ("topn_trade_total_primary", "selling_point"),
    "是否高增速": ("growth_enrichment", "speed_type"),
    "材质": ("product_detail_enrichment", "core_material"),
    "场景": ("product_detail_enrichment", "usage_scene"),
    "review_text": ("product_feedback_enrichment", "comment"),
    "qa_question": ("product_feedback_enrichment", "question_content"),
    "shop_name": ("competitor_landscape_primary", "shop_name"),
    "product_url": ("competitor_landscape_primary", "goods_href"),
    "price": ("competitor_landscape_primary", "price"),
    "main_selling_point": ("competitor_landscape_primary", "main_selling_point"),
}

FEEDBACK_UNAVAILABLE_FIELDS = {"rating", "qa_answer", "sku_name", "created_at"}
COMPETITOR_UNAVAILABLE_FIELDS = {"sku_count", "traffic_structure"}

DERIVED_FIELD_EVIDENCE_NAMES = {
    "功能": {"goods_name", "selling_point_summary", "goods_spec_params", "core_material", "usage_scene"},
    "风格": {"goods_name", "selling_point_summary", "usage_scene", "core_material"},
    "主图元素": {"goods_img", "goods_name", "selling_point_summary"},
    "爆款原因": {"goods_name", "selling_point_summary", "core_material", "usage_scene"},
    "root_terms": {"keyword", "keywords"},
    "demand_type": {"keyword", "keywords", "wordpack", "category_requirements"},
    "词根": {"keyword", "keywords"},
    "需求类型": {"keyword", "keywords", "wordpack", "category_requirements"},
    "sentiment": {"comment"},
    "painpoint_type": {"comment", "question_content"},
    "competitor_type": {"shop_name", "goods_href", "price", "unit_price", "sales_total", "sales_ratio", "main_selling_point", "selling_point"},
    "visual_structure": {"main_image_url", "main_image", "main_color", "image_words"},
    "review_painpoints": {"comment", "question_content"},
    "competitor_strength": {"qbt_rank", "sycm_rank", "sales_total", "sales_ratio", "price", "unit_price"},
}


def _derived_evidence_field_paths(field_name: str, entries: list[ApiDocEntry]) -> list[str]:
    names = DERIVED_FIELD_EVIDENCE_NAMES.get(field_name, set())
    paths: list[str] = []
    for entry in entries:
        for field in entry.response_fields:
            if field.name in names and field.path not in paths:
                paths.append(field.path)
    return paths


def _preferred_execution_field(field_name: str, entries: list[ApiDocEntry]) -> dict | None:
    preference = EXECUTION_FIELD_PREFERENCES.get(field_name)
    if not preference:
        return None
    role, api_field_name = preference
    for entry in entries:
        if _api_execution_role(entry) != role:
            continue
        for field in entry.response_fields:
            if field.name == api_field_name:
                return {
                    "source_api_id": entry.api_id,
                    "source_api_name": entry.name or entry.api_id,
                    "source_field_path": field.path,
                    "api_field_name": field.name,
                    "api_field_type": field.type or "unknown",
                    "confidence": 0.99,
                    "match_basis": f"execution_role:{role}:{api_field_name}",
                }
    return None


def _is_covered(status: str) -> bool:
    return status in {"mapped", "suggested", "confirmed", "manual_fill", "derived", "derived_or_manual_required"}


def _field_coverage_plan(
    field_mapping: FieldMatchResult,
    output_fields: list[dict],
    selected_entries: list[ApiDocEntry],
    api_applicability: dict[str, dict] | None = None,
) -> list[dict]:
    matches_by_name = {match.business_field: match for match in field_mapping.matches}
    applicability = api_applicability or {}
    selected_api_ids = {entry.api_id for entry in selected_entries}
    feedback_analysis = any(_api_execution_role(entry) == "product_feedback_enrichment" for entry in selected_entries)
    competitor_analysis = any(_api_execution_role(entry) == "competitor_landscape_primary" for entry in selected_entries)
    plan: list[dict] = []
    for output_field in output_fields:
        field_name = str(output_field.get("field_name", ""))
        match = matches_by_name.get(field_name)
        status = _field_status(match.status) if match else "missing"
        mapped = status in {"mapped", "suggested"}
        derived = status == "derived_or_manual_required"
        candidates = _candidate_field_options(output_field, selected_entries)
        source_api_id = str(match.api_id if mapped and match else "")
        source_api_name = str(match.api_name if mapped and match else "")
        source_field_path = str(match.api_field_path if mapped and match else "")
        api_field_name = str(match.api_field_name if mapped and match else "")
        api_field_type = str(match.api_field_type if mapped and match else "")
        confidence = float(match.confidence if match else 0.0)
        match_basis = str(match.match_basis if match else "no_reliable_api_field")
        if mapped and source_api_id not in selected_api_ids:
            mapped = False
            status = "missing"
            source_api_id = ""
            source_api_name = ""
            source_field_path = ""
            api_field_name = ""
            api_field_type = ""
            confidence = 0.0
            match_basis = "source_api_not_selected_for_execution"
        preferred = _preferred_execution_field(field_name, selected_entries)
        if preferred:
            mapped = True
            derived = False
            status = "mapped"
            source_api_id = str(preferred["source_api_id"])
            source_api_name = str(preferred["source_api_name"])
            source_field_path = str(preferred["source_field_path"])
            api_field_name = str(preferred["api_field_name"])
            api_field_type = str(preferred["api_field_type"])
            confidence = float(preferred["confidence"])
            match_basis = str(preferred["match_basis"])
        elif field_name in EXECUTION_DERIVED_FIELDS:
            mapped = False
            derived = True
            status = "derived_or_manual_required"
            source_api_id = ""
            source_api_name = ""
            source_field_path = ""
            api_field_name = ""
            api_field_type = ""
            confidence = 0.0
            match_basis = "requires_derived_or_manual_enrichment"
        elif feedback_analysis and field_name in FEEDBACK_UNAVAILABLE_FIELDS:
            mapped = False
            derived = False
            status = "missing"
            source_api_id = ""
            source_api_name = ""
            source_field_path = ""
            api_field_name = ""
            api_field_type = ""
            confidence = 0.0
            match_basis = "feedback_api_field_unavailable"
        elif competitor_analysis and field_name in COMPETITOR_UNAVAILABLE_FIELDS:
            mapped = False
            derived = False
            status = "missing"
            source_api_id = ""
            source_api_name = ""
            source_field_path = ""
            api_field_name = ""
            api_field_type = ""
            confidence = 0.0
            match_basis = "competitor_api_field_unavailable"
        current_scope = str(applicability.get(source_api_id, {}).get("category_scope", ""))
        scoped_candidates = [
            item
            for item in candidates
            if applicability.get(str(item.get("source_api_id", "")), {}).get("category_scope")
            in {"category_name_supported", "category_id_required"}
            and applicability.get(str(item.get("source_api_id", "")), {}).get("category_resolution_ready")
        ]
        if mapped and current_scope == "category_unscoped" and scoped_candidates:
            replacement = scoped_candidates[0]
            replacement_confidence = float(replacement.get("confidence", 0.0) or 0.0)
            if replacement_confidence >= confidence - 0.1:
                source_api_id = str(replacement.get("source_api_id", ""))
                source_api_name = str(replacement.get("source_api_name", ""))
                source_field_path = str(replacement.get("source_field_path", ""))
                api_field_name = str(replacement.get("api_field_name", ""))
                api_field_type = str(replacement.get("api_field_type", ""))
                confidence = replacement_confidence
                match_basis = f"category_scope_preferred:{replacement.get('match_basis', '')}"
        plan.append(
            {
                **output_field,
                "field_description": output_field.get("description", ""),
                "source_api_id": source_api_id,
                "source_api_name": source_api_name,
                "source_field_path": source_field_path,
                "api_field_path": source_field_path,
                "api_field_name": api_field_name,
                "api_field_type": api_field_type,
                "source_role": "api_field" if mapped else "derived" if derived else "",
                "source_kind": "api_doc_index" if mapped else "pi_derived" if derived else "",
                "mapping_status": status,
                "status": status,
                "confidence": confidence,
                "human_confirmed": False,
                "confirmed": False,
                "human_note": "",
                "match_basis": match_basis,
                "missing_reason": str(match.missing_reason if match else "候选 API 返回字段中没有找到可靠映射。"),
                "source_strategy": str(match.source_strategy if match else ""),
                "candidate_api_ids": list(match.candidate_api_ids if match else []),
                "candidate_field_options": candidates,
                "evidence_field_paths": _derived_evidence_field_paths(field_name, selected_entries) if derived else [],
            }
        )
    return plan


def _api_category_scope(entry: ApiDocEntry) -> str:
    if _api_execution_role(entry) in {"product_detail_enrichment", "product_feedback_enrichment"}:
        return "inherited_from_primary"
    roles = {_category_param_role(param) for param in entry.request_params}
    if "category_name" in roles:
        return "category_name_supported"
    if "category_id" in roles:
        return "category_id_required"
    return "category_unscoped"


def _api_applicability(entry: ApiDocEntry, known_params: dict, category_resolution: dict) -> dict:
    scope = _api_category_scope(entry)
    category_name = str(
        known_params.get("category")
        or known_params.get("category_name")
        or known_params.get("分析类目")
        or ""
    ).strip()
    known_category_id = str(
        known_params.get("cid")
        or known_params.get("category_id")
        or known_params.get("cate_id")
        or known_params.get("cat_id")
        or ""
    ).strip()
    category_id = str(
        known_category_id
        or category_resolution.get("category_id")
        or ""
    ).strip()
    resolution_ready = scope == "category_name_supported" and bool(category_name)
    if scope == "category_id_required":
        resolution_ready = bool(
            known_category_id
            or category_id and category_resolution.get("status") in {"resolved", "needs_confirmation"}
        )
    execution_role = _api_execution_role(entry)
    return {
        "execution_role": execution_role,
        "depends_on_role": (
            "topn_trade_total_primary" if execution_role == "product_detail_enrichment"
            else "confirmed_top_products" if execution_role == "product_feedback_enrichment"
            else ""
        ),
        "input_binding": (
            {"goods_id": "primary_rows[].goods_id"} if execution_role == "product_detail_enrichment"
            else {
                "goods_id": "confirmed_rows[].goods_id",
                "goods_id_list": "confirmed_rows[].goods_id",
            } if execution_role == "product_feedback_enrichment"
            else {}
        ),
        "time_grain": _api_time_grain(entry),
        "category_scope": scope,
        "category_name_supported": scope == "category_name_supported",
        "category_id_required": scope == "category_id_required",
        "category_unscoped": scope == "category_unscoped",
        "category_resolution_ready": resolution_ready,
        "category_resolution_status": str(category_resolution.get("status", "")),
    }


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
            "available_evidence_fields": list(item.get("evidence_field_paths", [])),
            "evidence_field_paths": list(item.get("evidence_field_paths", [])),
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
    known_params = request.get("known_params") if isinstance(request.get("known_params"), dict) else {}
    requested_category = str(known_params.get("category") or known_params.get("category_name") or known_params.get("分析类目") or "")
    requested_category_id = str(
        known_params.get("cid")
        or known_params.get("category_id")
        or known_params.get("cate_id")
        or known_params.get("cat_id")
        or ""
    )
    category_resolution = _resolve_category_candidates(
        str(request["index_path"]), requested_category, requested_category_id
    ) if requested_category or requested_category_id else {
        "status": "not_required",
        "category_id": "",
    }
    api_applicability = {
        api_id: _api_applicability(entry, known_params, category_resolution)
        for api_id, entry in entries_by_id.items()
    }
    if requested_category:
        context_text = " ".join(
            [
                section.title,
                section.purpose,
                *section.data_sources,
                *section.actions,
                *[field.name for field in section.output_fields],
            ]
        )
        competitor_context = (
            str(node_id) == "analyze_competitors"
            or any(token in context_text for token in ["竞店", "竞争格局", "竞品类型", "竞争强度"])
        )
        hot_product_context = (
            not competitor_context
            and "商品" in context_text
            and any(token in context_text for token in ["热销", "排行", "排名", "销量"])
        )
        detail_enrichment_needed = any(
            field.name in {"材质", "场景", "功能", "风格", "主图元素", "爆款原因"}
            for field in section.output_fields
        )
        feedback_context = any(token in context_text for token in ["评价", "评论", "问大家", "痛点"])
        role_api_ids: list[str] = []
        if hot_product_context:
            roles = ["topn_trade_total_primary", "growth_enrichment"]
            if detail_enrichment_needed:
                roles.append("product_detail_enrichment")
            for role in roles:
                candidates = [
                    entry
                    for entry in entries
                    if _api_execution_role(entry) == role
                    and (
                        api_applicability[entry.api_id]["category_resolution_ready"]
                        or role == "product_detail_enrichment"
                    )
                ]
                candidates.sort(key=lambda entry: (0 if entry.verified_status == "success" else 1, entry.source_seq, entry.api_id))
                if candidates:
                    role_api_ids.append(candidates[0].api_id)
        if feedback_context and not competitor_context:
            feedback_candidates = [
                entry
                for entry in entries
                if _api_execution_role(entry) == "product_feedback_enrichment"
            ]
            feedback_candidates.sort(key=lambda entry: (0 if entry.verified_status == "success" else 1, entry.source_seq, entry.api_id))
            role_api_ids.extend(entry.api_id for entry in feedback_candidates)
        else:
            selected_api_ids = [
                api_id for api_id in selected_api_ids
                if api_applicability.get(api_id, {}).get("execution_role") != "product_feedback_enrichment"
            ]
        if competitor_context:
            competitor_priority = {
                "data_shop_competition_pattern_analysis_v3": 0,
                "data_competition_pattern_analysis_v3": 1,
                "data_competition_pattern_analysis": 2,
            }
            competitor_candidates = [
                entry
                for entry in entries
                if _api_execution_role(entry) == "competitor_landscape_primary"
                and api_applicability[entry.api_id]["category_resolution_ready"]
            ]
            competitor_candidates.sort(key=lambda entry: (
                competitor_priority.get(entry.api_id, 99),
                0 if entry.verified_status == "success" else 1,
                entry.source_seq,
                entry.api_id,
            ))
            if competitor_candidates:
                role_api_ids.append(competitor_candidates[0].api_id)
            selected_api_ids = [
                api_id for api_id in selected_api_ids
                if api_applicability.get(api_id, {}).get("execution_role") == "competitor_landscape_primary"
            ]
        else:
            selected_api_ids = [
                api_id for api_id in selected_api_ids
                if api_applicability.get(api_id, {}).get("execution_role") != "competitor_landscape_primary"
            ]
        scoped_candidates = [
            str(item.get("api_id", ""))
            for item in strategy_result.get("api_candidates", [])
            if str(item.get("api_id", "")) in entries_by_id
            and api_applicability[str(item.get("api_id", ""))]["category_scope"] != "category_unscoped"
            and api_applicability[str(item.get("api_id", ""))]["category_resolution_ready"]
        ]
        if scoped_candidates and scoped_candidates[0] not in selected_api_ids:
            selected_api_ids = [scoped_candidates[0], *selected_api_ids]
        selected_api_ids = [
            api_id
            for api_id in selected_api_ids
            if api_applicability.get(api_id, {}).get("category_scope") != "category_unscoped"
        ]
        selected_api_ids = [*role_api_ids, *selected_api_ids]
        if competitor_context:
            selected_api_ids = role_api_ids[:1]
        selected_api_ids = sorted(
            dict.fromkeys(selected_api_ids),
            key=lambda api_id: (
                0 if api_applicability.get(api_id, {}).get("execution_role") == "topn_trade_total_primary" else
                1 if api_applicability.get(api_id, {}).get("execution_role") == "growth_enrichment" else
                2 if api_applicability.get(api_id, {}).get("execution_role") == "product_detail_enrichment" else
                3 if api_applicability.get(api_id, {}).get("execution_role") == "product_feedback_enrichment" else
                4 if api_applicability.get(api_id, {}).get("execution_role") == "competitor_landscape_primary" else
                5 if api_applicability.get(api_id, {}).get("category_scope") == "category_name_supported" else
                6 if api_applicability.get(api_id, {}).get("category_scope") == "category_id_required" and api_applicability.get(api_id, {}).get("category_resolution_ready") else
                7 if api_applicability.get(api_id, {}).get("category_scope") == "category_id_required" else
                8,
                selected_api_ids.index(api_id) if api_id in selected_api_ids else 999,
            ),
        )[:5]
    strategy_result["selected_api_ids"] = list(selected_api_ids)
    selected_entries = [entries_by_id[api_id] for api_id in selected_api_ids if api_id in entries_by_id]
    selected_api_assets = [
        {**_api_asset(entry), "execution_applicability": api_applicability.get(entry.api_id, {})}
        for entry in selected_entries
    ]
    api_response_field_catalog = _api_response_field_catalog(selected_entries)
    field_coverage_plan = _field_coverage_plan(result.field_mapping, output_fields, selected_entries, api_applicability)
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
        "known_params": known_params,
        "category_resolution_candidate": category_resolution,
        "api_applicability": {api_id: api_applicability[api_id] for api_id in selected_api_ids if api_id in api_applicability},
        "strategy_results": result_dict["strategy_results"],
        "strategy_field_mappings": result_dict["strategy_field_mappings"],
        "selected_api_ids": selected_api_ids,
        "candidate_apis": [
            {**item, "execution_applicability": api_applicability.get(str(item.get("api_id", "")), {})}
            for item in strategy_result.get("api_candidates", [])
        ],
        "selected_api_assets": selected_api_assets,
        "api_response_field_catalog": api_response_field_catalog,
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


def _op_bind_request_params(request: dict) -> dict:
    entries = load_api_entries(request["index_path"])
    api_id = str(request.get("api_id", "")).strip()
    entry = next((item for item in entries if item.api_id == api_id), None)
    if entry is None:
        raise ValueError(f"api_id not found: {api_id}")
    known_params = request.get("known_params") if isinstance(request.get("known_params"), dict) else {}
    timezone = str(request.get("timezone") or "Asia/Shanghai")
    execution_date = _parse_execution_date(request.get("execution_date"), timezone)
    return _bind_request_params_for_entry(entry, known_params, execution_date, timezone)


def _op_discover_category_resolver(request: dict) -> dict:
    entries = load_api_entries(request["index_path"])
    known_params = request.get("known_params") if isinstance(request.get("known_params"), dict) else {}
    category_name = str(request.get("category_name") or known_params.get("category") or known_params.get("category_name") or known_params.get("分析类目") or "").strip()
    category_id = str(request.get("category_id") or known_params.get("cid") or known_params.get("category_id") or known_params.get("cate_id") or known_params.get("cat_id") or "").strip()
    direction = str(request.get("direction") or ("id_to_name" if category_id and not category_name else "name_to_id"))
    top_k = max(1, int(request.get("top_k", 8) or 8))
    timezone = str(request.get("timezone") or "Asia/Shanghai")
    execution_date = _parse_execution_date(request.get("execution_date"), timezone)
    candidates: list[dict] = []
    rejected_candidates: list[dict] = []
    for entry in entries:
        name_field = next((field for field in entry.response_fields if _field_path_looks_like_category_name(field)), None)
        id_field = next((field for field in entry.response_fields if _field_path_looks_like_category_id(field)), None)
        if not name_field or not id_field:
            continue
        if _entry_needs_unknown_category_id(entry, known_params):
            rejected_candidates.append({"api_id": entry.api_id, "resolver_mode": "requires_unknown_id", "reason": "resolver_requires_category_id"})
            continue
        resolver_mode, resolver_reason = _resolver_semantic_mode(entry)
        if resolver_mode == "unsuitable":
            rejected_candidates.append({"api_id": entry.api_id, "resolver_mode": resolver_mode, "reason": resolver_reason})
            continue
        binding_status = _resolver_request_binding_status(entry, known_params, execution_date, timezone)
        if binding_status["status"] != "ready":
            rejected_candidates.append({"api_id": entry.api_id, "resolver_mode": resolver_mode, "reason": "resolver_request_params_missing"})
            continue
        verified_score = 0.2 if entry.verified_status == "success" else 0.08 if entry.verified_status else 0.0
        readiness_score = 0.25 if binding_status["status"] == "ready" else 0.0
        score = round(0.4 + verified_score + readiness_score + _resolver_domain_score(entry), 4)
        candidates.append(
            {
                "api_id": entry.api_id,
                "api_name": entry.name or entry.api_id,
                "method": entry.method,
                "path": entry.path,
                "verified_status": entry.verified_status,
                "business_module": entry.business_module,
                "analysis_domain": entry.analysis_domain,
                "name_field_path": name_field.path,
                "name_field_name": name_field.name,
                "id_field_path": id_field.path,
                "id_field_name": id_field.name,
                "score": score,
                "resolver_mode": resolver_mode,
                "request_binding": binding_status,
                "reason": resolver_reason,
            }
        )
    candidates.sort(key=lambda item: (-float(item["score"]), item["api_id"]))
    return {
        "schema_version": "category-resolver-discovery-v1",
        "provider": "api_doc_matcher",
        "direction": direction,
        "category_name": category_name,
        "category_id": category_id,
        "execution_date": execution_date.isoformat(),
        "timezone": timezone,
        "candidates": candidates[:top_k],
        "rejected_candidates": rejected_candidates,
    }


def _op_resolve_category_candidates(request: dict) -> dict:
    known_params = request.get("known_params") if isinstance(request.get("known_params"), dict) else {}
    requested_name = str(
        request.get("category_name")
        or known_params.get("category")
        or known_params.get("category_name")
        or known_params.get("分析类目")
        or ""
    )
    category_id = str(
        request.get("category_id")
        or known_params.get("cid")
        or known_params.get("category_id")
        or known_params.get("cate_id")
        or known_params.get("cat_id")
        or ""
    )
    return _resolve_category_candidates(str(request["index_path"]), requested_name, category_id)


_OPS = {
    "match_fields": _op_match_fields,
    "match_api": _op_match_api,
    "match_section": _op_match_section,
    "match_business_context": _op_match_business_context,
    "bind_request_params": _op_bind_request_params,
    "discover_category_resolver": _op_discover_category_resolver,
    "resolve_category_candidates": _op_resolve_category_candidates,
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
