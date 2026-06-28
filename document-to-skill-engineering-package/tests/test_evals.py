from pathlib import Path
from doc_to_skill.parser import DocumentParser
from doc_to_skill.evals import CompileEvaluator


def test_compile_eval_passes():
    ir = DocumentParser().parse(Path("examples/source_docs/20260519市场分析洞察元策略.md"))
    metrics = CompileEvaluator().evaluate(ir)
    assert metrics["pass"] is True
    assert metrics["workflow_coverage"] >= 0.8
