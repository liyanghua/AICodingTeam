from __future__ import annotations

import re
import unittest
from pathlib import Path


EXPECTED_SKILLS = {
    "requirement_grilling": {
        "dir": "skills/10_requirement/requirement_grilling",
        "templates": ["question_bank.md", "context_format.md", "adr_format.md"],
    },
    "requirement_to_prd": {
        "dir": "skills/10_requirement/requirement_to_prd",
        "templates": ["prd_template.md", "acceptance_criteria_template.md"],
    },
    "repo_context_compiler": {
        "dir": "skills/10_requirement/repo_context_compiler",
        "templates": ["context_template.md", "impact_analysis_template.md"],
    },
    "prd_to_task_slices": {
        "dir": "skills/20_planning/prd_to_task_slices",
        "templates": ["task_slice_template.yaml", "issue_body_template.md"],
    },
    "tech_spec_to_tdd": {
        "dir": "skills/30_engineering/tech_spec_to_tdd",
        "templates": ["backend_test_patterns.md", "frontend_test_patterns.md", "integration_test_patterns.md", "eval_template.md"],
    },
    "diagnose_failure": {
        "dir": "skills/40_execution/diagnose_failure",
        "templates": ["failure_taxonomy.md", "fix_plan_template.md"],
    },
}


class ProjectSkillsTests(unittest.TestCase):
    def test_registry_declares_first_batch_project_skills(self) -> None:
        root = Path(__file__).resolve().parents[1]
        registry_path = root / "skills" / "registry.yaml"
        registry_text = registry_path.read_text(encoding="utf-8")

        for skill_id, spec in EXPECTED_SKILLS.items():
            self.assertIn(f"id: {skill_id}", registry_text)
            self.assertIn(f"path: {spec['dir']}", registry_text)
            self.assertRegex(registry_text, rf"id: {skill_id}[\s\S]*?priority: P0")
            self.assertRegex(registry_text, rf"id: {skill_id}[\s\S]*?quality_gates:")
            for template in spec["templates"]:
                self.assertIn(template, registry_text)

    def test_each_project_skill_has_required_contract_sections_and_templates(self) -> None:
        root = Path(__file__).resolve().parents[1]
        required_sections = ("## Purpose", "## When To Use", "## Inputs", "## Outputs", "## Steps", "## Quality Gate")

        for skill_id, spec in EXPECTED_SKILLS.items():
            skill_dir = root / spec["dir"]
            skill_md = skill_dir / "SKILL.md"
            text = skill_md.read_text(encoding="utf-8")

            self.assertIn(f"name: {skill_id}", text)
            self.assertIn("description:", text)
            for section in required_sections:
                self.assertIn(section, text, f"{skill_id} missing {section}")
            for template in spec["templates"]:
                self.assertTrue((skill_dir / template).exists(), f"{skill_id} missing {template}")

    def test_skill_docs_explain_stage_order_and_runtime_boundary(self) -> None:
        root = Path(__file__).resolve().parents[1]
        readme_text = (root / "skills" / "README.md").read_text(encoding="utf-8")

        expected_order = (
            "requirement_grilling -> requirement_to_prd -> repo_context_compiler -> "
            "prd_to_task_slices -> tech_spec_to_tdd -> diagnose_failure"
        )
        self.assertIn(expected_order, readme_text)
        self.assertIn("文档/注册表接入", readme_text)
        self.assertIn("不自动执行", readme_text)

    def test_agents_and_readme_reference_project_skills_registry(self) -> None:
        root = Path(__file__).resolve().parents[1]
        agents_text = (root / "AGENTS.md").read_text(encoding="utf-8")
        readme_text = (root / "README.md").read_text(encoding="utf-8")

        for text in (agents_text, readme_text):
            self.assertIn("skills/registry.yaml", text)
            self.assertIn("Project Skills", text)

    def test_skill_ids_use_snake_case_for_registry_and_folder_names(self) -> None:
        for skill_id, spec in EXPECTED_SKILLS.items():
            self.assertRegex(skill_id, r"^[a-z0-9]+(_[a-z0-9]+)*$")
            self.assertEqual(Path(spec["dir"]).name, skill_id)
