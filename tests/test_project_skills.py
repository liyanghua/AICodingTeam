from __future__ import annotations

import re
import unittest
from pathlib import Path


EXPECTED_SKILLS = {
    "using_agent_skills": {
        "dir": "skills/00_meta/using_agent_skills",
        "templates": ["routing_matrix.md", "context_budget.md"],
    },
    "spec_driven_development": {
        "dir": "skills/10_define/spec_driven_development",
        "templates": ["spec_template.md", "acceptance_criteria_template.md"],
    },
    "context_engineering": {
        "dir": "skills/10_define/context_engineering",
        "templates": ["context_pack_template.md", "context_selection_matrix.md"],
    },
    "planning_and_task_breakdown": {
        "dir": "skills/20_plan/planning_and_task_breakdown",
        "templates": ["task_slice_template.yaml", "plan_template.md"],
    },
    "incremental_implementation": {
        "dir": "skills/40_execution/incremental_implementation",
        "templates": ["slice_loop_template.md", "implementation_record_template.md"],
    },
    "test_driven_development": {
        "dir": "skills/30_engineering/test_driven_development",
        "templates": ["tdd_cases_template.md", "eval_template.md"],
    },
    "debugging_and_error_recovery": {
        "dir": "skills/40_execution/debugging_and_error_recovery",
        "templates": ["failure_taxonomy.md", "fix_plan_template.md"],
    },
    "code_review_and_quality": {
        "dir": "skills/50_review/code_review_and_quality",
        "templates": ["review_checklist.md", "review_report_template.md"],
    },
}

OLD_ACTIVE_SKILLS = {
    "requirement_grilling": "skills/10_requirement/requirement_grilling",
    "requirement_to_prd": "skills/10_requirement/requirement_to_prd",
    "repo_context_compiler": "skills/10_requirement/repo_context_compiler",
    "prd_to_task_slices": "skills/20_planning/prd_to_task_slices",
    "tech_spec_to_tdd": "skills/30_engineering/tech_spec_to_tdd",
    "diagnose_failure": "skills/40_execution/diagnose_failure",
}

EXPECTED_ORDER = (
    "using_agent_skills -> spec_driven_development -> context_engineering -> "
    "planning_and_task_breakdown -> incremental_implementation -> test_driven_development -> "
    "debugging_and_error_recovery -> code_review_and_quality"
)


def _registry_ids(registry_text: str) -> list[str]:
    return re.findall(r"^\s+- id: ([a-z0-9_]+)$", registry_text, flags=re.MULTILINE)


def _registry_block(registry_text: str, skill_id: str) -> str:
    match = re.search(rf"^\s+- id: {skill_id}\n(?:(?!^\s+- id: ).)*", registry_text, flags=re.MULTILINE | re.DOTALL)
    if not match:
        raise AssertionError(f"Missing registry block for {skill_id}")
    return match.group(0)


class ProjectSkillsTests(unittest.TestCase):
    def test_registry_declares_first_batch_production_skills(self) -> None:
        root = Path(__file__).resolve().parents[1]
        registry_path = root / "skills" / "registry.yaml"
        registry_text = registry_path.read_text(encoding="utf-8")

        self.assertEqual(_registry_ids(registry_text), list(EXPECTED_SKILLS.keys()))
        for skill_id, spec in EXPECTED_SKILLS.items():
            block = _registry_block(registry_text, skill_id)
            self.assertIn(f"path: {spec['dir']}", block)
            for field in (
                "stage:",
                "priority: P0",
                "source_inspiration:",
                "replaces:",
                "inputs:",
                "outputs:",
                "triggers:",
                "quality_gates:",
                "templates:",
                "context_budget:",
            ):
                self.assertIn(field, block, f"{skill_id} missing registry field {field}")
            for template in spec["templates"]:
                self.assertIn(template, block)

        for old_skill_id in OLD_ACTIVE_SKILLS:
            self.assertNotIn(old_skill_id, _registry_ids(registry_text))

    def test_each_project_skill_has_required_contract_sections_and_templates(self) -> None:
        root = Path(__file__).resolve().parents[1]
        required_sections = (
            "## Purpose",
            "## When To Use",
            "## Inputs",
            "## Outputs",
            "## Steps",
            "## Quality Gate",
            "## Context Hygiene",
        )

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

    def test_skill_docs_explain_stage_order_runtime_boundary_and_context_policy(self) -> None:
        root = Path(__file__).resolve().parents[1]
        readme_text = (root / "skills" / "README.md").read_text(encoding="utf-8")

        self.assertIn(EXPECTED_ORDER, readme_text)
        self.assertIn("文档/注册表接入", readme_text)
        self.assertIn("不自动执行", readme_text)
        self.assertIn("不是越多越好", readme_text)
        self.assertIn("最多 1 个 companion skill", readme_text)

    def test_agents_and_readme_reference_project_skills_registry(self) -> None:
        root = Path(__file__).resolve().parents[1]
        agents_text = (root / "AGENTS.md").read_text(encoding="utf-8")
        readme_text = (root / "README.md").read_text(encoding="utf-8")

        for text in (agents_text, readme_text):
            self.assertIn("skills/registry.yaml", text)
            self.assertIn("Project Skills", text)
            self.assertIn(EXPECTED_ORDER, text)

    def test_old_first_batch_skills_are_not_active_directories(self) -> None:
        root = Path(__file__).resolve().parents[1]

        for skill_dir in OLD_ACTIVE_SKILLS.values():
            self.assertFalse((root / skill_dir / "SKILL.md").exists(), f"{skill_dir} should be replaced by production skills")

    def test_skill_ids_use_snake_case_for_registry_and_folder_names(self) -> None:
        for skill_id, spec in EXPECTED_SKILLS.items():
            self.assertRegex(skill_id, r"^[a-z0-9]+(_[a-z0-9]+)*$")
            self.assertEqual(Path(spec["dir"]).name, skill_id)
