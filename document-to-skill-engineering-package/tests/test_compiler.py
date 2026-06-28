from pathlib import Path
from doc_to_skill.parser import DocumentParser
from doc_to_skill.compiler import SkillCompiler


def test_compile_skill_package(tmp_path):
    path = Path("examples/source_docs/20260519市场分析洞察元策略.md")
    ir = DocumentParser().parse(path)
    out = SkillCompiler().compile(ir, tmp_path / "skill")
    assert (out / "SKILL.md").exists()
    assert (out / "skill.yaml").exists()
    assert (out / "workflow.dag.yaml").exists()
    assert (out / "data_requirements.yaml").exists()
    assert (out / "tool_bindings.yaml").exists()
    assert (out / "eval_rules.yaml").exists()
    assert (out / "evidence_schema.yaml").exists()
