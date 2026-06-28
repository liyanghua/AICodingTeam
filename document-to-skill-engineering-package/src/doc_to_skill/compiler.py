from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import yaml

from .schemas import StrategyIR


class SkillCompiler:
    """Compile StrategyIR into a runnable skill package."""

    def compile(self, ir: StrategyIR, output_dir: str | Path) -> Path:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "output_schemas").mkdir(exist_ok=True)

        self._write_yaml(output_dir / "strategy_ir.yaml", ir.model_dump(mode="json"))
        self._write_skill_md(ir, output_dir / "SKILL.md")
        self._write_skill_yaml(ir, output_dir / "skill.yaml")
        self._write_workflow(ir, output_dir / "workflow.dag.yaml")
        self._write_data_requirements(ir, output_dir / "data_requirements.yaml")
        self._write_tool_bindings(ir, output_dir / "tool_bindings.yaml")
        self._write_eval_rules(ir, output_dir / "eval_rules.yaml")
        self._write_evidence_schema(output_dir / "evidence_schema.yaml")
        self._write_output_schemas(ir, output_dir / "output_schemas")
        self._write_missing_tools_report(ir, output_dir / "missing_tools_report.md")
        return output_dir

    def _write_yaml(self, path: Path, data: Any) -> None:
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def _write_skill_md(self, ir: StrategyIR, path: Path) -> None:
        workflow = "\n".join([f"{i+1}. {s.title}" for i, s in enumerate(ir.workflow_steps)])
        outputs = "\n".join([f"- {o.name}: {o.description}" for o in ir.outputs])
        questions = "\n".join([f"- {q.question}" for q in ir.business_questions])
        path.write_text(f"""# {ir.name} Skill

## Purpose

将 `{ir.source_doc}` 中的业务策略编译为 Agent Runtime 可执行流程。

## Business Questions

{questions}

## Workflow

{workflow}

## Required Outputs

{outputs}

## Data Policy

- 优先使用内部数仓 API。
- 其次使用 BI API 或平台导出工具。
- 再其次使用浏览器自动化工具。
- 外部公开趋势可使用 Exa / Web Intelligence。
- 没有数据时不得编造经营结论。

## Evidence Policy

- 每个结论必须有 Evidence Pack。
- 每个分数必须有公式或规则。
- 每个推荐必须能追溯到数据、规则或人工复核。
""", encoding="utf-8")

    def _write_skill_yaml(self, ir: StrategyIR, path: Path) -> None:
        data = {
            "skill_id": ir.strategy_id,
            "name": ir.name,
            "version": ir.version,
            "source_doc": ir.source_doc,
            "input_schema": {
                "category": {"type": "string", "required": True},
                "product_line": {"type": "string", "required": True},
                "analysis_period": {"type": "string", "enum": ["7d", "30d", "monthly", "seasonal"], "default": "30d"},
                "business_goal": {"type": "string", "required": True},
            },
            "outputs": [o.id for o in ir.outputs],
            "workflow_file": "workflow.dag.yaml",
            "data_requirements_file": "data_requirements.yaml",
            "tool_bindings_file": "tool_bindings.yaml",
            "eval_rules_file": "eval_rules.yaml",
            "evidence_schema_file": "evidence_schema.yaml",
        }
        self._write_yaml(path, data)

    def _write_workflow(self, ir: StrategyIR, path: Path) -> None:
        nodes = []
        for s in ir.workflow_steps:
            nodes.append({
                "id": s.step_id,
                "name": s.title,
                "type": str(s.step_type),
                "depends_on": s.depends_on,
                "data_requirements": s.data_requirement_ids,
                "outputs": s.outputs,
                "rules": s.rules,
            })
        self._write_yaml(path, {"nodes": nodes})

    def _write_data_requirements(self, ir: StrategyIR, path: Path) -> None:
        self._write_yaml(path, {"data_requirements": [d.model_dump(mode="json") for d in ir.data_requirements]})

    def _write_tool_bindings(self, ir: StrategyIR, path: Path) -> None:
        bindings = {}
        for d in ir.data_requirements:
            primary = self._guess_primary_tool(d)
            bindings[d.id] = {
                "primary_tool": primary,
                "fallback_tools": [self._source_to_tool(x) for x in d.preferred_sources[1:]] + [self._source_to_tool(x) for x in d.fallback_sources],
            }
        self._write_yaml(path, {"tool_bindings": bindings})

    def _guess_primary_tool(self, req) -> str:
        if req.preferred_sources:
            return self._source_to_tool(req.preferred_sources[0])
        return "manual_upload.generic_file"

    def _source_to_tool(self, source: str) -> str:
        mapping = {
            "internal_dw.": "internal_api.",
            "bi_api.": "bi_api.",
            "browser.": "browser.",
            "external_web.": "external_web.",
            "compute.": "compute.",
            "manual_upload.": "manual_upload.",
        }
        for prefix, tool_prefix in mapping.items():
            if source.startswith(prefix):
                return source.replace(prefix, tool_prefix, 1)
        return source

    def _write_eval_rules(self, ir: StrategyIR, path: Path) -> None:
        data = {
            "hard_requirements": [
                "required_outputs_present",
                "evidence_required_for_each_conclusion",
                "score_formula_required",
                "no_data_no_strong_claim",
            ],
            "rules": [r.model_dump(mode="json") for r in ir.rules],
            "quality_metrics": {
                "workflow_node_success_rate": 0.95,
                "data_requirement_coverage": 0.90,
                "evidence_completeness": 0.95,
                "output_schema_validity": 1.0,
            },
        }
        self._write_yaml(path, data)

    def _write_evidence_schema(self, path: Path) -> None:
        schema = {
            "type": "object",
            "required": ["evidence_id", "skill_run_id", "step_id", "claim", "evidence_type", "source_data"],
            "properties": {
                "evidence_id": {"type": "string"},
                "skill_run_id": {"type": "string"},
                "step_id": {"type": "string"},
                "claim": {"type": "string"},
                "evidence_type": {"type": "string"},
                "source_data": {"type": "array"},
                "computation": {"type": "object"},
                "rule_hit": {"type": "object"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
        }
        self._write_yaml(path, schema)

    def _write_output_schemas(self, ir: StrategyIR, dir_: Path) -> None:
        for output in ir.outputs:
            schema = {
                "type": "object",
                "title": output.name,
                "description": output.description,
                "properties": {
                    "rows": {"type": "array", "items": {"type": "object"}},
                    "conclusions": {"type": "array", "items": {"type": "string"}},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                },
            }
            (dir_ / f"{output.id}.json").write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_missing_tools_report(self, ir: StrategyIR, path: Path) -> None:
        lines = ["# Missing Tools Report", "", "以下工具需要根据企业数据/API现状确认或实现：", ""]
        for req in ir.data_requirements:
            lines.append(f"## {req.id}")
            lines.append(req.description)
            lines.append("")
            lines.append("候选来源：")
            for s in req.preferred_sources + req.fallback_sources:
                lines.append(f"- {s}")
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
