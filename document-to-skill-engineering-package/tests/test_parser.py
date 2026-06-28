from pathlib import Path
from doc_to_skill.parser import DocumentParser


def test_parse_market_insight_doc():
    path = Path("examples/source_docs/20260519市场分析洞察元策略.md")
    ir = DocumentParser().parse(path)
    assert ir.strategy_id == "market_insight"
    assert len(ir.workflow_steps) >= 8
    assert len(ir.outputs) >= 8
    assert len(ir.data_requirements) >= 5
    assert any(q.id == "what_sells_well" for q in ir.business_questions)
