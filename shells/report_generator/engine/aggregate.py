from __future__ import annotations

import re
from typing import Any


class NarrativeSafetyError(ValueError):
    """Raised when an LLM-editable narrative section contains forbidden facts."""


FORBIDDEN_NUMBER_RE = re.compile(r"(\d+\s*%|\d+\.\d+|[¥$￥]\s*\d+|\d+\s*(元|美元|块))")


def render_aggregate_report(
    aggregate: dict[str, Any],
    *,
    rule_outputs: list[dict[str, Any]],
    narrative: dict[str, str] | None = None,
) -> str:
    """Render the final report while keeping numbers sourced from rule outputs."""
    narrative = narrative or {}
    for section, text in narrative.items():
        if FORBIDDEN_NUMBER_RE.search(str(text)):
            raise NarrativeSafetyError(f"llm_safety_violation: narrative section {section!r} contains forbidden numbers")

    title = str(aggregate.get("title") or aggregate.get("node_id") or "final_report")
    lines = [f"# {title}", ""]
    if narrative:
        lines.extend(["## 人工叙述", ""])
        for section, text in narrative.items():
            lines.extend([f"### {section}", str(text), ""])
    lines.extend(["## 规则输出", "", "| rule_id | label | score |", "| --- | --- | --- |"])
    for item in rule_outputs:
        lines.append(
            f"| {item.get('rule_id', '')} | {item.get('output_label', '')} | {item.get('score', '')} |"
        )
    lines.extend(["", "## Evidence", "", "- 规则结论来自结构化 rule_outputs，叙述段禁止自行编造数字。"])
    return "\n".join(lines)
