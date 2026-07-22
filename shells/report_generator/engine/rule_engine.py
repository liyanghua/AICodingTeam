"""Report Generator Rule Engine compatibility façade and CLI."""

from __future__ import annotations

import json
import sys
from typing import Any

try:
    from . import rules
except ImportError:  # pragma: no cover - supports direct ``python rule_engine.py`` execution.
    import rules  # type: ignore[no-redef]


def clamp(value: Any, lo: float, hi: float) -> float:
    """Clamp numeric value between lo and hi for legacy callers."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, num))


def _as_dict(hit: rules.RuleHit) -> dict[str, Any]:
    return hit.to_dict()


def _uses_legacy_inputs(rule_id: str, inputs: dict[str, Any]) -> bool:
    legacy_fields = {
        "strong_hot_gene": {"category_gmv_growth", "cr5"},
        "trend_hot_gene": {"search_index_mom", "note_growth"},
        "differentiated_opportunity_gene": {"top20_homogenization", "longtail_gmv_ratio"},
    }
    return bool(legacy_fields.get(rule_id, set()) & set(inputs or {}))


def eval_rule(rule_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
    """Delegate rule evaluation to ``rules.py`` while retaining old inputs."""
    payload = dict(inputs or {})
    try:
        hit = (
            rules.eval_legacy_rule(rule_id, payload)
            if _uses_legacy_inputs(rule_id, payload)
            else rules.eval_rule(rule_id, payload)
        )
    except ValueError:
        return {
            "rule_id": rule_id,
            "matched": False,
            "output_label": "未配置规则",
            "score": None,
            "evidence": {"warning": "unknown_rule", "known_rules": list(RULE_REGISTRY.keys())},
        }
    return _as_dict(hit)


def evaluate_strong_hot_gene(inputs: dict[str, Any]) -> dict[str, Any]:
    return eval_rule("strong_hot_gene", inputs)


def evaluate_trend_hot_gene(inputs: dict[str, Any]) -> dict[str, Any]:
    return eval_rule("trend_hot_gene", inputs)


def evaluate_differentiated_opportunity_gene(inputs: dict[str, Any]) -> dict[str, Any]:
    return eval_rule("differentiated_opportunity_gene", inputs)


def evaluate_opportunity_score(inputs: dict[str, Any]) -> dict[str, Any]:
    return eval_rule("opportunity_score", inputs)


RULE_REGISTRY = {
    "strong_hot_gene": evaluate_strong_hot_gene,
    "trend_hot_gene": evaluate_trend_hot_gene,
    "differentiated_opportunity_gene": evaluate_differentiated_opportunity_gene,
    "opportunity_score": evaluate_opportunity_score,
}


def main() -> None:
    """Read ``rule_id`` and ``inputs`` JSON from stdin and write JSON to stdout."""
    try:
        request = json.loads(sys.stdin.read())
        result = eval_rule(request.get("rule_id", ""), request.get("inputs", {}))
        sys.stdout.write(json.dumps(result, ensure_ascii=False))
        sys.stdout.flush()
        sys.exit(0)
    except Exception as exc:
        error = {"error": "rule_engine_failed", "message": str(exc)}
        sys.stderr.write(json.dumps(error, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
