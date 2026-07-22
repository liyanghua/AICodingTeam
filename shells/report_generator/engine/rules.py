from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any, Callable


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    matched: bool
    output_label: str
    severity: str = "info"
    score: float | int | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def eval_rule(rule_id: str, inputs: dict[str, Any]) -> RuleHit:
    """Evaluate one independent gene rule using only canonical evidence fields."""
    payload = dict(inputs or {})
    if rule_id == "strong_hot_gene":
        signals = {
            "top50_ratio": _ratio_signal(
                payload,
                "top50_ratio",
                0.30,
                "top50 ratio >= 0.30",
                sample_size=payload.get("sample_size"),
                minimum_sample=50,
            ),
            "top100_ratio": _ratio_signal(payload, "top100_ratio", 0.20, "top100 ratio >= 0.20"),
            "buyer_ratio": _ratio_signal(payload, "buyer_ratio", 0.30, "buyer ratio >= 0.30"),
            "gmv_ratio": _ratio_signal(payload, "gmv_ratio", 0.30, "GMV ratio >= 0.30"),
        }
        return _signal_rule(rule_id, "强爆款基因", signals)
    if rule_id == "trend_hot_gene":
        signals = {
            "high_growth_product_ratio": _ratio_signal(
                payload, "high_growth_product_ratio", 0.30, "high-growth product ratio >= 0.30"
            ),
            "keyword_growth": _number_signal(payload, "keyword_growth", 0.20, "keyword growth >= 0.20"),
            "buyer_growth_30d": _number_signal(
                payload, "buyer_growth_30d", 0.50, "30-day buyer growth >= 0.50"
            ),
            "cross_platform_hot": _boolean_signal(
                payload, "cross_platform_hot", "cross-platform content is hot"
            ),
        }
        return _signal_rule(rule_id, "趋势爆款基因", signals)
    if rule_id == "differentiated_opportunity_gene":
        signals = {
            "review_painpoint_ratio": _ratio_signal(
                payload, "review_painpoint_ratio", 0.10, "review pain-point ratio >= 0.10"
            ),
            "qa_concern_ratio": _ratio_signal(
                payload, "qa_concern_ratio", 0.10, "Q&A concern ratio >= 0.10"
            ),
            "top50_supply_count": _number_signal(
                payload,
                "top50_supply_count",
                5,
                "TOP50 supply count < 5",
                comparator=lambda value, threshold: value < threshold,
                integer=True,
            ),
            "price_band_supply_gap": _compound_signal(
                payload,
                ["price_band_supply_ratio", "price_band_buyer_ratio"],
                "price-band supply ratio < 0.15 and buyer ratio >= 0.25",
                lambda supply, buyer: supply < 0.15 and buyer >= 0.25,
            ),
        }
        return _signal_rule(rule_id, "差异机会基因", signals)
    if rule_id == "opportunity_score":
        return _opportunity_score(payload)
    raise ValueError(f"Unknown rule_id: {rule_id}")


def _signal_rule(rule_id: str, label: str, signals: dict[str, dict[str, Any]]) -> RuleHit:
    available = [signal for signal in signals.values() if signal["available"]]
    matched_count = sum(1 for signal in available if signal["matched"])
    available_count = len(available)
    if matched_count >= 2:
        classification_status = "matched"
    elif available_count < 2:
        classification_status = "insufficient_evidence"
    else:
        classification_status = "not_matched"
    evidence_fields = sorted(
        {
            field
            for signal in signals.values()
            for field in signal["evidence_fields"]
        }
    )
    return RuleHit(
        rule_id=rule_id,
        matched=matched_count >= 2,
        output_label=label,
        evidence={
            "signals": signals,
            "available_count": available_count,
            "matched_count": matched_count,
            "required_count": 2,
            "classification_status": classification_status,
            "evidence_fields": evidence_fields,
        },
    )


def _ratio_signal(
    inputs: dict[str, Any],
    field: str,
    threshold: float,
    description: str,
    *,
    sample_size: Any = None,
    minimum_sample: int | None = None,
) -> dict[str, Any]:
    if minimum_sample is not None and _valid_integer(sample_size) and int(sample_size) < minimum_sample:
        return _unavailable_signal(
            field,
            "insufficient_sample",
            description,
            evidence_fields=[field, "sample_size"],
            value=inputs.get(field),
        )
    value = _strict_metric(inputs.get(field), ratio=True)
    if value is None:
        return _unavailable_signal(field, "unavailable", description)
    return _available_signal(
        field,
        value,
        value >= threshold,
        description,
        evidence_fields=[field] + (["sample_size"] if sample_size is not None else []),
    )


def _number_signal(
    inputs: dict[str, Any],
    field: str,
    threshold: float,
    description: str,
    *,
    comparator: Callable[[float, float], bool] | None = None,
    integer: bool = False,
) -> dict[str, Any]:
    value = _strict_metric(inputs.get(field), integer=integer)
    if value is None:
        return _unavailable_signal(field, "unavailable", description)
    compare = comparator or (lambda actual, expected: actual >= expected)
    return _available_signal(field, value, compare(value, threshold), description, evidence_fields=[field])


def _boolean_signal(inputs: dict[str, Any], field: str, description: str) -> dict[str, Any]:
    value = inputs.get(field)
    if type(value) is not bool:
        return _unavailable_signal(field, "unavailable", description)
    return _available_signal(field, value, value, description, evidence_fields=[field])


def _compound_signal(
    inputs: dict[str, Any], fields: list[str], description: str, predicate: Callable[..., bool]
) -> dict[str, Any]:
    values = [_strict_metric(inputs.get(field), ratio=True) for field in fields]
    if any(value is None for value in values):
        return _unavailable_signal("price_band_supply_gap", "unavailable", description)
    return _available_signal(
        "price_band_supply_gap",
        {field: value for field, value in zip(fields, values)},
        predicate(*values),
        description,
        evidence_fields=fields,
    )


def _available_signal(
    field: str,
    value: Any,
    matched: bool,
    description: str,
    *,
    evidence_fields: list[str],
) -> dict[str, Any]:
    return {
        "status": "matched" if matched else "not_matched",
        "source_status": "available",
        "available": True,
        "matched": bool(matched),
        "value": value,
        "threshold": description,
        "evidence_fields": evidence_fields,
    }


def _unavailable_signal(
    field: str,
    source_status: str,
    description: str,
    *,
    evidence_fields: list[str] | None = None,
    value: Any = None,
) -> dict[str, Any]:
    return {
        "status": source_status,
        "source_status": source_status,
        "available": False,
        "matched": None,
        "value": value if source_status == "insufficient_sample" else None,
        "threshold": description,
        "evidence_fields": evidence_fields or [],
    }


def _strict_metric(value: Any, *, ratio: bool = False, integer: bool = False) -> float | int | None:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        return None
    if integer and float(value).is_integer() is False:
        return None
    number = int(value) if integer else float(value)
    if number < 0 or (ratio and number > 1):
        return None
    return number


def _valid_integer(value: Any) -> bool:
    return _strict_metric(value, integer=True) is not None


def _opportunity_score(inputs: dict[str, Any]) -> RuleHit:
    aliases = {
        "demand_clarity": "market_size",
        "growth_trend": "growth_rate",
        "competition_strength": "competition_intensity",
        "profit_space": "brand_fit",
    }
    raw_components = {
        name: inputs.get(name, inputs.get(alias))
        for name, alias in aliases.items()
    }
    raw_components.update(
        {
            "supply_chain_feasibility": inputs.get("supply_chain_feasibility"),
            "differentiation_strength": inputs.get("differentiation_strength"),
        }
    )
    limits = {
        "demand_clarity": 20,
        "growth_trend": 20,
        "competition_strength": 15,
        "profit_space": 15,
        "supply_chain_feasibility": 15,
        "differentiation_strength": 15,
    }
    components = {
        name: _clamp(_number(value), 0, limits[name])
        for name, value in raw_components.items()
    }
    score = sum(components.values())
    if score >= 85:
        label = "优先立项开发"
    elif score >= 70:
        label = "小批量测试"
    elif score >= 60:
        label = "继续观察"
    else:
        label = "暂不开发"
    return RuleHit(
        rule_id="opportunity_score",
        matched=score >= 60,
        output_label=label,
        score=int(score) if float(score).is_integer() else score,
        evidence={"components": components, "formula": "20+20+15+15+15+15"},
    )


def eval_legacy_rule(rule_id: str, inputs: dict[str, Any]) -> RuleHit:
    """Compatibility rules for the old direct rule_engine API."""
    payload = dict(inputs or {})
    if rule_id == "strong_hot_gene":
        growth = _clamp(_number(payload.get("category_gmv_growth")), 0, 100)
        cr5 = _clamp(_number(payload.get("cr5")), 0, 100)
        matched = growth >= 30 and cr5 <= 40
        return RuleHit(
            rule_id,
            matched,
            "强热基因确认" if matched else "非强热基因",
            evidence={"category_gmv_growth": growth, "cr5": cr5, "threshold_growth": 30, "threshold_cr5": 40},
        )
    if rule_id == "trend_hot_gene":
        search_growth = _clamp(_number(payload.get("search_index_mom")), 0, 500)
        note_growth = _clamp(_number(payload.get("note_growth")), 0, 500)
        matched = search_growth >= 50 and note_growth >= 20
        return RuleHit(
            rule_id,
            matched,
            "趋势热基因确认" if matched else "非趋势热基因",
            evidence={"search_index_mom": search_growth, "note_growth": note_growth, "threshold_search": 50, "threshold_note": 20},
        )
    if rule_id == "differentiated_opportunity_gene":
        homogenization = _clamp(_number(payload.get("top20_homogenization")), 0, 100)
        longtail_gmv = _clamp(_number(payload.get("longtail_gmv_ratio")), 0, 100)
        matched = homogenization >= 60 and longtail_gmv >= 25
        return RuleHit(
            rule_id,
            matched,
            "差异化机会确认" if matched else "无差异化机会",
            evidence={"top20_homogenization": homogenization, "longtail_gmv_ratio": longtail_gmv},
        )
    return eval_rule(rule_id, payload)


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
