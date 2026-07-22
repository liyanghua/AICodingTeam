from __future__ import annotations

from .models import ApiDocEntry, ApiField, ApiMatch, BusinessField, FieldMatch, FieldMatchResult
from .text_utils import normalize_text, query_terms


API_SYNONYMS: dict[str, list[str]] = {
    "类目": ["category", "cate", "cid", "类目"],
    "商品": ["goods", "item", "commodity", "product", "商品"],
    "排行": ["top", "rank", "top300", "排名", "排行"],
    "热销": ["top", "best", "sales", "热销", "商品"],
    "行业": ["industry", "ind", "类目", "行业"],
    "大盘": ["market", "行业", "类目"],
    "价格": ["price", "unit_price", "价格"],
}

FIELD_ALIASES: dict[str, list[str]] = {
    "排名": ["rank", "排名", "排行"],
    "商品名": ["commodity", "goods_name", "item_name", "product_name", "商品名称", "商品标题", "商品名"],
    "商品名称": ["commodity", "goods_name", "item_name", "product_name", "商品名称", "商品标题"],
    "商品链接": ["goods_url", "item_url", "product_url", "url", "商品链接", "链接"],
    "商品主图": ["pictures_linking", "pic", "image", "img", "main_image", "主图", "图片链接", "商品主图"],
    "店铺名": ["store_name", "shop_name", "店铺名称", "店铺名"],
    "店铺名称": ["store_name", "shop_name", "店铺名称"],
    "价格": ["unit_price", "price", "价格", "件单价"],
    "客单价": ["unit_price", "customer_unit_price", "price", "客单价", "previous_customer_unit_price"],
    "价格带": ["price_band", "avg_price", "price", "价格带", "价格"],
    "支付买家数": ["num_payers", "pay_buyer", "支付买家数", "买家数"],
    "销量/支付买家数": ["num_payers", "pay_buyer", "num_total", "sales_volume", "销量", "支付买家数", "销售能力"],
    "交易指数": ["trade_index", "transaction_index", "交易指数"],
    "GMV/交易指数": ["sales_revenue", "gmv", "trade_index", "transaction_index", "num_total", "交易指数", "判断体量"],
    "产品类型": ["product_type", "category_name", "top3_category_name", "store_type", "产品类型", "品类", "款式", "形态"],
    "材质": ["material", "material_real", "材质"],
    "场景": ["scene", "场景"],
    "主卖点": ["selling_point", "sell_point", "卖点", "主卖点"],
    "是否高增速": ["speed_type", "yoy", "growth", "rate", "高增速", "排名提升"],
    "keyword": ["keyword", "keywords", "关键词", "搜索词"],
    "search_popularity": ["search_popularity", "搜索人气"],
    "growth_rate": ["search_growth_rate", "growth_rate", "搜索增长率"],
    "competition_index": ["competition_index", "竞争指数"],
    "click_rate": ["click_rate", "点击率"],
    "conversion_rate": ["conversion_rate", "pay_rate", "支付转化率", "转化率"],
}

DERIVED_OR_MANUAL_FIELDS = {
    "功能",
    "风格",
    "主图元素",
    "爆款原因",
    "root_terms",
    "demand_type",
    "词根",
    "需求类型",
}


def _expanded_terms(query: str) -> list[str]:
    terms = set(query_terms(query))
    for key, values in API_SYNONYMS.items():
        if key in query:
            terms.add(key.lower())
            for value in values:
                terms.add(value.lower())
    return [term for term in terms if len(term) >= 2]


def _api_doc_text(entry: ApiDocEntry) -> str:
    return normalize_text(
        " ".join(
            [
                entry.api_id,
                entry.name,
                entry.module,
                entry.business_module,
                entry.analysis_domain,
                entry.path,
                " ".join(p.name + " " + p.description for p in entry.request_params),
                " ".join(f.path + " " + f.description for f in entry.response_fields),
            ]
        )
    )


def match_api_requirement(entries: list[ApiDocEntry], query: str, top_k: int = 5) -> list[ApiMatch]:
    terms = _expanded_terms(query)
    matches: list[ApiMatch] = []
    for entry in entries:
        haystack = _api_doc_text(entry)
        reasons: list[str] = []
        hit_count = 0
        for term in terms:
            if term and term in haystack:
                hit_count += 1
        if hit_count:
            reasons.append(f"term_hits={hit_count}")
        score = hit_count / max(1, len(terms))
        if "top300" in haystack and ("300" in query or "排行" in query or "热销" in query):
            score += 0.3
            reasons.append("top300_rank_hint")
        if "商品" in query and ("商品" in entry.name or "commodity" in haystack or "goods" in haystack):
            score += 0.2
            reasons.append("product_hint")
        if "类目" in query and ("类目" in entry.name or "category" in haystack or "cid" in haystack):
            score += 0.15
            reasons.append("category_hint")
        if entry.verified_status == "success":
            score += 0.08
            reasons.append("verified_success")
        elif entry.verified_status == "empty":
            score += 0.02
            reasons.append("verified_empty")
        if score <= 0:
            continue
        missing = [p.name for p in entry.request_params if p.required]
        risks = list(entry.parse_warnings)
        matches.append(
            ApiMatch(
                api_id=entry.api_id,
                name=entry.name,
                method=entry.method,
                path=entry.path,
                score=round(score, 4),
                verified_status=entry.verified_status,
                reasons=reasons,
                missing_params=missing,
                risks=risks,
            )
        )
    matches.sort(key=lambda item: (-item.score, item.api_id))
    return matches[:top_k]


def _field_score(business_field: BusinessField, api_field: ApiField) -> tuple[float, str]:
    field_norm = business_field.name.lower().strip()
    path = api_field.path.lower()
    name = api_field.name.lower()
    desc = api_field.description.lower()
    haystack = f"{path} {name} {desc}"
    aliases = FIELD_ALIASES.get(business_field.name, [business_field.name])
    description_terms = query_terms(business_field.description)
    if field_norm and (field_norm == name or business_field.name in api_field.description):
        return 0.95, "exact_or_description_match"
    for alias in aliases:
        alias_norm = alias.lower()
        if alias_norm and alias_norm in haystack:
            return 0.9, f"alias_match:{alias}"
    image_hints = {"主图", "图片", "视觉", "image", "pic", "img"}
    if business_field.name == "商品主图" and any(hint in haystack for hint in image_hints):
        return 0.85, "visual_image_hint"
    terms = [t for t in query_terms(f"{business_field.name} {business_field.description}") if len(t) >= 2]
    if terms:
        hits = sum(1 for term in terms if term in haystack)
        desc_hits = sum(1 for term in description_terms if len(term) >= 2 and term in haystack)
        if hits:
            return min(0.8, 0.45 + 0.15 * hits + 0.05 * desc_hits), f"partial_term_hits:{hits}"
    return 0.0, "no_match"


def _status_for_confidence(confidence: float) -> str:
    if confidence >= 0.85:
        return "matched"
    if confidence >= 0.60:
        return "suggested_needs_review"
    return "missing"


def match_business_fields(
    entries: list[ApiDocEntry],
    business_fields: list[str | BusinessField | dict],
    api_ids: list[str] | None = None,
    source_strategy: str = "",
) -> FieldMatchResult:
    normalized_fields = [BusinessField.from_any(field_item) for field_item in business_fields]
    api_filter = set(api_ids or [])
    candidate_entries = [entry for entry in entries if not api_filter or entry.api_id in api_filter]
    candidate_api_ids = [entry.api_id for entry in candidate_entries]
    matches: list[FieldMatch] = []
    for business_field in normalized_fields:
        if business_field.name in DERIVED_OR_MANUAL_FIELDS:
            matches.append(
                FieldMatch(
                    business_field=business_field.name,
                    status="derived_or_manual_required",
                    confidence=0.0,
                    field_description=business_field.description,
                    match_basis="requires_derived_or_manual_enrichment",
                    source_strategy=source_strategy,
                    candidate_api_ids=candidate_api_ids,
                    missing_reason="业务字段需要二次加工、视觉/内容分析或人工标注，不能由单个 API 原生字段稳定提供。",
                )
            )
            continue
        best_entry: ApiDocEntry | None = None
        best_field: ApiField | None = None
        best_score = 0.0
        best_basis = "no_match"
        for entry in candidate_entries:
            for api_field in entry.response_fields:
                score, basis = _field_score(business_field, api_field)
                if score > best_score:
                    best_entry = entry
                    best_field = api_field
                    best_score = score
                    best_basis = basis
        status = _status_for_confidence(best_score)
        if best_entry and best_field and status != "missing":
            matches.append(
                FieldMatch(
                    business_field=business_field.name,
                    status=status,
                    confidence=round(best_score, 4),
                    field_description=business_field.description,
                    api_id=best_entry.api_id,
                    api_name=best_entry.name,
                    api_field_path=best_field.path,
                    api_field_name=best_field.name,
                    api_field_type=best_field.type,
                    match_basis=best_basis,
                    source_strategy=source_strategy,
                    candidate_api_ids=candidate_api_ids,
                )
            )
        else:
            matches.append(
                FieldMatch(
                    business_field=business_field.name,
                    status="missing",
                    confidence=0.0,
                    field_description=business_field.description,
                    match_basis="no_reliable_api_field",
                    source_strategy=source_strategy,
                    candidate_api_ids=candidate_api_ids,
                    missing_reason="候选 API 返回字段中没有找到可靠映射。",
                )
            )

    required_total = len(normalized_fields)
    covered_required = sum(1 for match in matches if match.status != "missing")
    high_confidence = sum(1 for match in matches if match.confidence >= 0.85)
    confirmed_or_reviewable = sum(
        1
        for match in matches
        if match.status in {"matched", "suggested_needs_review", "derived_or_manual_required"}
    )
    missing_required_fields = [match.business_field for match in matches if match.status == "missing"]
    if required_total:
        score = (
            0.5 * (covered_required / required_total)
            + 0.3 * (high_confidence / required_total)
            + 0.2 * (confirmed_or_reviewable / required_total)
        )
    else:
        score = 0.0
    return FieldMatchResult(
        matches=matches,
        business_field_coverage_score=round(score, 4),
        required_total=required_total,
        covered_required=covered_required,
        high_confidence=high_confidence,
        confirmed_or_reviewable=confirmed_or_reviewable,
        missing_required_fields=missing_required_fields,
    )
