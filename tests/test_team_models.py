from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any


TEAM_YAML = """\
team_id: ai_native_engineering_team
agents:
  - id: orchestrator
    outputs: [task.yaml, context.md]
  - id: product
    outputs: [prd.md]
  - id: architect
    outputs: [tech_spec.md]
  - id: ux
    outputs: [ui_spec.md]
  - id: qa
    outputs: [eval.md]
  - id: coder
    outputs: [coding_prompt.md, code_run_record.json]
  - id: reviewer
    outputs: [review_report.md]
  - id: verifier
    outputs: [test_report.md]
  - id: publisher
    outputs: [final_report.md]
gates:
  before_coding: [prd.md, tech_spec.md, ui_spec.md, eval.md]
  before_publish: [review_report.md, test_report.md]
"""


DOMAIN_YAML = """\
domain_id: xhs_browser_benchmark
input_schema:
  keyword: string
  top_n: integer
  frameworks: list
output_schema: XhsNote
risk_rules:
  - no_captcha_bypass
  - no_fingerprint_spoofing
  - no_proxy_rotation
  - manual_login_only
"""


INVALID_TEAM_YAML = """\
team_id: broken_team
agents:
  - id: orchestrator
    outputs: [task.yaml]
  - id: product
gates:
  before_coding: [prd.md]
"""


def _load_with_model(model: type[Any], path: Path) -> Any:
    for method_name in ("from_yaml", "from_file", "from_path", "load"):
        method = getattr(model, method_name, None)
        if method is not None:
            return method(path)
    raise AssertionError(f"{model.__name__} needs a YAML/file loader")


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value[name]
    return getattr(value, name)


class TeamModelTests(unittest.TestCase):
    def test_team_yaml_parses_agents_and_gates(self) -> None:
        from growth_dev.team.models import TeamSpec

        with tempfile.TemporaryDirectory() as temp_dir:
            team_path = Path(temp_dir) / "team.yaml"
            team_path.write_text(TEAM_YAML, encoding="utf-8")

            spec = _load_with_model(TeamSpec, team_path)

        self.assertEqual(_field(spec, "team_id"), "ai_native_engineering_team")
        agents = _field(spec, "agents")
        agent_ids = [_field(agent, "id") for agent in agents]
        self.assertEqual(
            agent_ids,
            [
                "orchestrator",
                "product",
                "architect",
                "ux",
                "qa",
                "coder",
                "reviewer",
                "verifier",
                "publisher",
            ],
        )
        coder = agents[5]
        self.assertEqual(_field(coder, "outputs"), ["coding_prompt.md", "code_run_record.json"])

        gates = _field(spec, "gates")
        gate_map = {(_field(gate, "id") if hasattr(gate, "id") or isinstance(gate, dict) and "id" in gate else _field(gate, "name")): gate for gate in gates} if isinstance(gates, list) else gates
        before_coding = gate_map["before_coding"]
        required = _field(before_coding, "required") if not isinstance(before_coding, list) else before_coding
        self.assertEqual(required, ["prd.md", "tech_spec.md", "ui_spec.md", "eval.md"])

    def test_domain_yaml_parses_schema_and_risk_rules(self) -> None:
        from growth_dev.team.models import DomainSpec

        with tempfile.TemporaryDirectory() as temp_dir:
            domain_path = Path(temp_dir) / "domain.yaml"
            domain_path.write_text(DOMAIN_YAML, encoding="utf-8")

            spec = _load_with_model(DomainSpec, domain_path)

        self.assertEqual(_field(spec, "domain_id"), "xhs_browser_benchmark")
        self.assertEqual(_field(spec, "input_schema")["top_n"], "integer")
        self.assertIn("manual_login_only", _field(spec, "risk_rules"))
        self.assertIn("no_captcha_bypass", _field(spec, "risk_rules"))

    def test_team_yaml_rejects_agent_without_outputs(self) -> None:
        from growth_dev.team.models import TeamSpec

        with tempfile.TemporaryDirectory() as temp_dir:
            team_path = Path(temp_dir) / "team.yaml"
            team_path.write_text(INVALID_TEAM_YAML, encoding="utf-8")

            with self.assertRaises(ValueError) as raised:
                _load_with_model(TeamSpec, team_path)

        self.assertIn("outputs", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
