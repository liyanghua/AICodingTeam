from __future__ import annotations

from .schemas import StrategyIR


class CompileEvaluator:
    def evaluate(self, ir: StrategyIR) -> dict:
        workflow_coverage = min(len(ir.workflow_steps) / 10, 1.0)
        output_coverage = min(len(ir.outputs) / 10, 1.0)
        data_requirement_coverage = 0.0
        if ir.workflow_steps:
            steps_with_data = sum(1 for s in ir.workflow_steps if s.data_requirement_ids or s.step_type in {"form_collect", "scoring", "business_plan_generation"})
            data_requirement_coverage = steps_with_data / len(ir.workflow_steps)
        rule_coverage = min(len(ir.rules) / 4, 1.0)
        return {
            "workflow_coverage": workflow_coverage,
            "output_coverage": output_coverage,
            "data_requirement_coverage": data_requirement_coverage,
            "rule_coverage": rule_coverage,
            "pass": workflow_coverage >= 0.8 and output_coverage >= 0.8 and data_requirement_coverage >= 0.8,
        }
