"""Report Generator Rule Engine.

Pure Python stdlib rule evaluator for market insight scenarios.
Consumes app.config.json rule definitions and evaluates against inputs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def clamp(value: Any, lo: float, hi: float) -> float:
    """Clamp numeric value between lo and hi."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, num))


def evaluate_strong_hot_gene(inputs: dict) -> dict:
    """强热基因判定：品类 GMV 增速 >= 30% 且集中度 CR5 <= 40%."""
    growth = clamp(inputs.get("category_gmv_growth"), 0, 100)
    cr5 = clamp(inputs.get("cr5"), 0, 100)
    
    matched = growth >= 30 and cr5 <= 40
    label = "强热基因确认" if matched else "非强热基因"
    
    return {
        "rule_id": "strong_hot_gene",
        "matched": matched,
        "output_label": label,
        "score": None,
        "evidence": {
            "category_gmv_growth": growth,
            "cr5": cr5,
            "threshold_growth": 30,
            "threshold_cr5": 40,
        },
    }


def evaluate_trend_hot_gene(inputs: dict) -> dict:
    """趋势热基因判定：搜索指数环比 >= 50% 且笔记增速 >= 20%."""
    search_growth = clamp(inputs.get("search_index_mom"), 0, 500)
    note_growth = clamp(inputs.get("note_growth"), 0, 500)
    
    matched = search_growth >= 50 and note_growth >= 20
    label = "趋势热基因确认" if matched else "非趋势热基因"
    
    return {
        "rule_id": "trend_hot_gene",
        "matched": matched,
        "output_label": label,
        "score": None,
        "evidence": {
            "search_index_mom": search_growth,
            "note_growth": note_growth,
            "threshold_search": 50,
            "threshold_note": 20,
        },
    }


def evaluate_differentiated_opportunity_gene(inputs: dict) -> dict:
    """差异化机会基因：Top20 同质化率 >= 60% 且长尾 GMV 占比 >= 25%."""
    homogenization = clamp(inputs.get("top20_homogenization"), 0, 100)
    longtail_gmv = clamp(inputs.get("longtail_gmv_ratio"), 0, 100)
    
    matched = homogenization >= 60 and longtail_gmv >= 25
    label = "差异化机会确认" if matched else "无差异化机会"
    
    return {
        "rule_id": "differentiated_opportunity_gene",
        "matched": matched,
        "output_label": label,
        "score": None,
        "evidence": {
            "top20_homogenization": homogenization,
            "longtail_gmv_ratio": longtail_gmv,
            "threshold_homogenization": 60,
            "threshold_longtail": 25,
        },
    }


def evaluate_opportunity_score(inputs: dict) -> dict:
    """机会分数：6 维加权（20+20+15+15+15+15 = 100）.
    
    档位阈值：
    - >= 85: 优先立项开发
    - >= 70: 小批量测试
    - >= 60: 继续观察
    - <  60: 暂不开发
    """
    components = {
        "market_size": clamp(inputs.get("market_size"), 0, 20),
        "growth_rate": clamp(inputs.get("growth_rate"), 0, 20),
        "competition_intensity": clamp(inputs.get("competition_intensity"), 0, 15),
        "brand_fit": clamp(inputs.get("brand_fit"), 0, 15),
        "supply_chain_feasibility": clamp(inputs.get("supply_chain_feasibility"), 0, 15),
        "differentiation_strength": clamp(inputs.get("differentiation_strength"), 0, 15),
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
    
    matched = score >= 60
    
    return {
        "rule_id": "opportunity_score",
        "matched": matched,
        "output_label": label,
        "score": score,
        "evidence": {
            "components": components,
            "formula": "20+20+15+15+15+15",
            "thresholds": {"priority": 85, "test": 70, "observe": 60},
        },
    }


RULE_REGISTRY = {
    "strong_hot_gene": evaluate_strong_hot_gene,
    "trend_hot_gene": evaluate_trend_hot_gene,
    "differentiated_opportunity_gene": evaluate_differentiated_opportunity_gene,
    "opportunity_score": evaluate_opportunity_score,
}


def eval_rule(rule_id: str, inputs: dict) -> dict:
    """Evaluate a rule by ID with given inputs.
    
    Returns a RuleHit dict with:
    - rule_id: the rule identifier
    - matched: whether the rule matched
    - output_label: human-readable label
    - score: numeric score (if applicable)
    - evidence: input values and thresholds used
    """
    evaluator = RULE_REGISTRY.get(rule_id)
    if evaluator is None:
        return {
            "rule_id": rule_id,
            "matched": False,
            "output_label": "未配置规则",
            "score": None,
            "evidence": {"warning": "unknown_rule", "known_rules": list(RULE_REGISTRY.keys())},
        }
    return evaluator(inputs)


def main():
    """CLI entry: read rule_id and inputs from stdin, write result to stdout.
    
    Usage: echo '{"rule_id": "opportunity_score", "inputs": {...}}' | python rule_engine.py
    """
    try:
        request = json.loads(sys.stdin.read())
        rule_id = request.get("rule_id", "")
        inputs = request.get("inputs", {})
        result = eval_rule(rule_id, inputs)
        sys.stdout.write(json.dumps(result, ensure_ascii=False))
        sys.stdout.flush()
        sys.exit(0)
    except Exception as exc:
        error = {"error": "rule_engine_failed", "message": str(exc)}
        sys.stderr.write(json.dumps(error, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()