from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    matched: bool
    output_label: str
    severity: str = "info"
    score: float | int | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


def eval_rule(rule_id: str, inputs: dict[str, Any]) -> RuleHit:
    payload = dict(inputs or {})
    if rule_id == "strong_hot_gene":
        signals = {
            "top50_ratio": _number(payload.get("top50_ratio")) >= 0.30,
            "top100_ratio": _number(payload.get("top100_ratio")) >= 0.20,
            "buyer_ratio": _number(payload.get("buyer_ratio")) >= 0.30,
            "gmv_ratio": _number(payload.get("gmv_ratio")) >= 0.30,
        }
        return _signal_rule(rule_id, "强爆款基因", signals)
    if rule_id == "trend_hot_gene":
        signals = {
            "high_growth_product_ratio": _number(payload.get("high_growth_product_ratio")) >= 0.30,
            "keyword_growth": _number(payload.get("keyword_growth")) >= 0.20,
            "buyer_growth_30d": _number(payload.get("buyer_growth_30d")) >= 0.50,
            "cross_platform_hot": bool(payload.get("cross_platform_hot")),
        }
        return _signal_rule(rule_id, "趋势爆款基因", signals)
    if rule_id == "differentiated_opportunity_gene":
        signals = {
            "review_painpoint_ratio": _number(payload.get("review_painpoint_ratio")) >= 0.10,
            "qa_concern_ratio": _number(payload.get("qa_concern_ratio")) >= 0.10,
            "top50_supply_count": _number(payload.get("top50_supply_count")) < 5,
            "price_band_supply_gap": _number(payload.get("price_band_supply_ratio")) < 0.15
            and _number(payload.get("buyer_ratio")) >= 0.25,
        }
        return _signal_rule(rule_id, "差异机会基因", signals)
    if rule_id == "opportunity_score":
        return _opportunity_score(payload)
    raise ValueError(f"Unknown rule_id: {rule_id}")


def _signal_rule(rule_id: str, label: str, signals: dict[str, bool]) -> RuleHit:
    matched_count = sum(1 for value in signals.values() if value)
    return RuleHit(
        rule_id=rule_id,
        matched=matched_count >= 2,
        output_label=label,
        evidence={"signals": signals, "matched_count": matched_count, "required_count": 2},
    )


def _opportunity_score(inputs: dict[str, Any]) -> RuleHit:
    components = {
        "demand_clarity": _clamp(_number(inputs.get("demand_clarity")), 0, 20),
        "growth_trend": _clamp(_number(inputs.get("growth_trend")), 0, 20),
        "competition_strength": _clamp(_number(inputs.get("competition_strength")), 0, 15),
        "profit_space": _clamp(_number(inputs.get("profit_space")), 0, 15),
        "supply_chain_feasibility": _clamp(_number(inputs.get("supply_chain_feasibility")), 0, 15),
        "differentiation_strength": _clamp(_number(inputs.get("differentiation_strength")), 0, 15),
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


def _number(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
