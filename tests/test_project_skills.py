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
        "templates": [
            "spec_template.md",
            "acceptance_criteria_template.md",
            "pm_prd_template.md",
            "user_story_template.md",
            "prd_red_team_template.md",
        ],
    },
    "context_engineering": {
        "dir": "skills/10_define/context_engineering",
        "templates": ["context_pack_template.md", "context_selection_matrix.md"],
    },
    "planning_and_task_breakdown": {
        "dir": "skills/20_plan/planning_and_task_breakdown",
        "templates": [
            "task_slice_template.yaml",
            "plan_template.md",
            "acceptance_coverage_matrix_template.md",
            "acceptance_coverage_matrix_template.json",
        ],
    },
    "incremental_implementation": {
        "dir": "skills/40_execution/incremental_implementation",
        "templates": [
            "slice_loop_template.md",
            "implementation_record_template.md",
            "slice_loop_trace_template.json",
            "implementation_completion_gate_template.md",
        ],
    },
    "test_driven_development": {
        "dir": "skills/30_engineering/test_driven_development",
        "templates": ["tdd_cases_template.md", "eval_template.md", "pm_test_scenarios_template.md"],
    },
    "debugging_and_error_recovery": {
        "dir": "skills/40_execution/debugging_and_error_recovery",
        "templates": ["failure_taxonomy.md", "fix_plan_template.md"],
    },
    "code_review_and_quality": {
        "dir": "skills/50_review/code_review_and_quality",
        "templates": ["review_checklist.md", "review_report_template.md"],
    },
    "ai_coding_quality_review": {
        "dir": "skills/50_review/ai_coding_quality_review",
        "templates": ["risk_taxonomy.md", "quality_report_template.md", "review_examples.md"],
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

EXPECTED_REVIEW_COMPANION_ORDER = "code_review_and_quality -> ai_coding_quality_review"

MEMORY_SKILLS = {
    "run_retrospective": {
        "dir": "skills/90_memory/run_retrospective",
        "templates": ["retrospective_template.md", "learning_summary_schema.md"],
    },
    "historical_task_recall": {
        "dir": "skills/90_memory/historical_task_recall",
        "templates": ["memory_recall_template.md", "recall_result_schema.md"],
    }
}


def _registry_ids(registry_text: str) -> list[str]:
    active_text = registry_text.split("\nmemory_skills:", 1)[0]
    return re.findall(r"^\s+- id: ([a-z0-9_]+)$", active_text, flags=re.MULTILINE)


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
            expected_priority = "priority: P1" if skill_id == "ai_coding_quality_review" else "priority: P0"
            self.assertIn(expected_priority, block)
            for template in spec["templates"]:
                self.assertIn(template, block)

        for old_skill_id in OLD_ACTIVE_SKILLS:
            self.assertNotIn(old_skill_id, _registry_ids(registry_text))

    def test_registry_declares_run_retrospective_as_non_active_memory_skill(self) -> None:
        root = Path(__file__).resolve().parents[1]
        registry_text = (root / "skills" / "registry.yaml").read_text(encoding="utf-8")

        self.assertEqual(_registry_ids(registry_text), list(EXPECTED_SKILLS.keys()))
        self.assertIn("memory_skills:", registry_text)
        self.assertIn("- id: run_retrospective", registry_text)
        self.assertIn("path: skills/90_memory/run_retrospective", registry_text)
        self.assertIn("- id: historical_task_recall", registry_text)
        self.assertIn("path: skills/90_memory/historical_task_recall", registry_text)
        self.assertIn("active: false", registry_text)

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

        for skill_id, spec in MEMORY_SKILLS.items():
            skill_dir = root / spec["dir"]
            skill_md = skill_dir / "SKILL.md"
            text = skill_md.read_text(encoding="utf-8")
            self.assertIn(f"name: {skill_id}", text)
            self.assertIn("## Purpose", text)
            self.assertIn("## Context Hygiene", text)
            for template in spec["templates"]:
                self.assertTrue((skill_dir / template).exists(), f"{skill_id} missing {template}")

    def test_skill_docs_explain_stage_order_runtime_boundary_and_context_policy(self) -> None:
        root = Path(__file__).resolve().parents[1]
        readme_text = (root / "skills" / "README.md").read_text(encoding="utf-8")

        self.assertIn(EXPECTED_ORDER, readme_text)
        self.assertIn(EXPECTED_REVIEW_COMPANION_ORDER, readme_text)
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
            self.assertIn("ai_coding_quality_review", text)
            self.assertIn("coverage-driven slice planning", text)

        self.assertIn("implementation completion gate", readme_text)
        self.assertIn("per-slice trace", readme_text)

    def test_old_first_batch_skills_are_not_active_directories(self) -> None:
        root = Path(__file__).resolve().parents[1]

        for skill_dir in OLD_ACTIVE_SKILLS.values():
            self.assertFalse((root / skill_dir / "SKILL.md").exists(), f"{skill_dir} should be replaced by production skills")

    def test_skill_ids_use_snake_case_for_registry_and_folder_names(self) -> None:
        for skill_id, spec in EXPECTED_SKILLS.items():
            self.assertRegex(skill_id, r"^[a-z0-9]+(_[a-z0-9]+)*$")
            self.assertEqual(Path(spec["dir"]).name, skill_id)

    def test_ai_coding_quality_gate_documents_risk_model_and_report_policy(self) -> None:
        root = Path(__file__).resolve().parents[1]
        gate_text = (root / "docs" / "ai_coding_quality_gate.md").read_text(encoding="utf-8")
        skill_dir = root / EXPECTED_SKILLS["ai_coding_quality_review"]["dir"]
        skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        taxonomy = (skill_dir / "risk_taxonomy.md").read_text(encoding="utf-8")
        template = (skill_dir / "quality_report_template.md").read_text(encoding="utf-8")

        for phrase in (
            "AIQ-ARCH-DRIFT",
            "MOB-SAFETY-BOUNDARY",
            "MOB-NONDET-BUDGET",
            "ASSET-DATA-INTEGRITY",
            "DEPLOY-SECRET-BOUNDARY",
            "health score",
            "block / revise / ready_with_risk / ready",
        ):
            self.assertIn(phrase, gate_text)

        self.assertIn("Do not use chat history as evidence", skill_text)
        self.assertIn("companion", skill_text)
        self.assertIn("MOB-CHANNEL-COUPLING", taxonomy)
        for field in ("Risk Code", "Severity", "Symptom", "Root Cause", "Consequence", "Fix", "Evidence", "Recommendation"):
            self.assertIn(field, template)

    def test_slice_planning_skill_requires_acceptance_coverage(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / EXPECTED_SKILLS["planning_and_task_breakdown"]["dir"]
        skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        slice_template = (skill_dir / "task_slice_template.yaml").read_text(encoding="utf-8")
        matrix_md = (skill_dir / "acceptance_coverage_matrix_template.md").read_text(encoding="utf-8")
        matrix_json = (skill_dir / "acceptance_coverage_matrix_template.json").read_text(encoding="utf-8")

        for phrase in (
            "acceptance criteria coverage",
            "orphan slice",
            "orphan acceptance criterion",
        ):
            self.assertIn(phrase, skill_text)

        for field in (
            "acceptance_criteria_ids:",
            "verification_commands:",
            "expected_artifacts:",
            "stop_conditions:",
            "depends_on:",
        ):
            self.assertIn(field, slice_template)

        self.assertIn("Acceptance Coverage Matrix", matrix_md)
        self.assertIn("all_acceptance_criteria_have_slices", matrix_json)

    def test_incremental_implementation_skill_defines_slice_loop_observability(self) -> None:
        root = Path(__file__).resolve().parents[1]
        skill_dir = root / EXPECTED_SKILLS["incremental_implementation"]["dir"]
        skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        loop_template = (skill_dir / "slice_loop_template.md").read_text(encoding="utf-8")
        trace_template = (skill_dir / "slice_loop_trace_template.json").read_text(encoding="utf-8")
        gate_template = (skill_dir / "implementation_completion_gate_template.md").read_text(encoding="utf-8")

        for phrase in (
            "slice-loop",
            "one slice at a time",
            "codex/slices/<slice_id>/slice_trace.json",
        ):
            self.assertIn(phrase, skill_text)

        for phrase in (
            "overall goal",
            "completed slices",
            "pending slices",
            "current diff",
            "allowed paths",
            "verification commands",
        ):
            self.assertIn(phrase, loop_template)

        self.assertIn('"schema_version": 1', trace_template)
        self.assertIn('"acceptance_coverage"', trace_template)
        for gate in (
            "all_slices_completed",
            "all_acceptance_criteria_covered",
            "required_tests_passed",
            "no_open_blockers",
            "no_unrelated_changes",
            "final_report_mentions_coverage",
        ):
            self.assertIn(gate, gate_template)

    def test_pm_skills_methods_are_absorbed_as_templates_not_active_skills(self) -> None:
        root = Path(__file__).resolve().parents[1]
        registry_text = (root / "skills" / "registry.yaml").read_text(encoding="utf-8")
        spec_dir = root / EXPECTED_SKILLS["spec_driven_development"]["dir"]
        tdd_dir = root / EXPECTED_SKILLS["test_driven_development"]["dir"]
        spec_text = (spec_dir / "SKILL.md").read_text(encoding="utf-8")
        tdd_text = (tdd_dir / "SKILL.md").read_text(encoding="utf-8")
        readme_text = (root / "skills" / "README.md").read_text(encoding="utf-8")

        for skill_id in ("create-prd", "user-stories", "test-scenarios", "strategy-red-team"):
            self.assertNotIn(f"- id: {skill_id}", registry_text)

        for template in ("pm_prd_template.md", "user_story_template.md", "prd_red_team_template.md"):
            self.assertTrue((spec_dir / template).exists())
            self.assertIn(template, registry_text)

        self.assertTrue((tdd_dir / "pm_test_scenarios_template.md").exists())
        self.assertIn("pm_test_scenarios_template.md", registry_text)

        for phrase in (
            "PM Skills",
            "candidate understanding",
            "deterministic gate",
            "run artifacts",
        ):
            self.assertIn(phrase, readme_text)

        self.assertIn("PM-style product clarification", spec_text)
        self.assertIn("3 C", spec_text)
        self.assertIn("INVEST", spec_text)
        self.assertIn("happy path", tdd_text)
        self.assertIn("edge case", tdd_text)
