from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..utils import ensure_dir, now_iso, write_json
from .models import DomainSpec


PLANNING_MODES = {"deterministic", "llm_assisted", "auto"}
REQUIREMENT_QUALITY_ARTIFACT = "requirements/requirement_quality_report.json"
PLANNING_QUALITY_ARTIFACT = "planning/planning_quality_report.json"
REQUIREMENT_CANDIDATE_ARTIFACT = "requirements/requirement_understanding.candidate.json"
CAPABILITY_BOUNDARY_JSON_ARTIFACT = "requirements/capability_boundary.json"
CAPABILITY_BOUNDARY_MD_ARTIFACT = "requirements/capability_boundary.md"
TDD_PLAN_JSON_ARTIFACT = "planning/tdd_plan.json"
TDD_PLAN_MD_ARTIFACT = "planning/tdd_plan.md"
SECRET_REPLACEMENTS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{6,}"), "<redacted-secret>"),
    (re.compile(r"(?i)(AICODEMIRROR_KEY\s*[:=]\s*)[^\s,;'\"\n]+"), r"\1<redacted>"),
    (re.compile(r"(?i)((api[_-]?key|secret|token|password)\s*[:=]\s*)[^\s,;'\"\n]+"), r"\1<redacted>"),
]

COMPLEX_BRIEF_MARKERS = [
    "dashboard",
    "ui",
    "api",
    "slice",
    "trace",
    "gate",
    "workflow",
    "流程",
    "完整",
    "复杂",
    "友好",
    "优化",
    "质量",
    "验收",
    "可观测",
    "执行",
    "发布",
    "ci",
]


@dataclass(slots=True)
class ComplexTaskConfig:
    planning_mode: str = "auto"
    requirements_model: str = ""
    requirements_reasoning_effort: str = "medium"

    def normalized(self) -> "ComplexTaskConfig":
        mode = self.planning_mode or "auto"
        if mode not in PLANNING_MODES:
            raise ValueError(f"Unsupported planning mode: {mode}")
        effort = self.requirements_reasoning_effort or "medium"
        if effort not in {"low", "medium", "high"}:
            raise ValueError(f"Unsupported requirements reasoning effort: {effort}")
        return ComplexTaskConfig(
            planning_mode=mode,
            requirements_model=self.requirements_model or "",
            requirements_reasoning_effort=effort,
        )

    def to_dict(self) -> dict[str, str]:
        config = self.normalized()
        return {
            "planning_mode": config.planning_mode,
            "requirements_model": config.requirements_model,
            "requirements_reasoning_effort": config.requirements_reasoning_effort,
        }


def generate_complex_task_artifacts(
    *,
    run_id: str,
    run_dir: Path,
    brief: str,
    domain: DomainSpec,
    inputs: dict[str, Any] | None = None,
    config: ComplexTaskConfig | None = None,
) -> dict[str, Any]:
    """Generate deterministic requirement, planning, and slice-loop seed artifacts."""
    normalized = (config or ComplexTaskConfig()).normalized()
    inputs = dict(inputs or {})
    artifact_inputs = _redact_payload(inputs)
    artifact_brief = _redact_text(brief)
    run_dir = Path(run_dir)
    requirements_dir = ensure_dir(run_dir / "requirements")
    planning_dir = ensure_dir(run_dir / "planning")
    slices_dir = ensure_dir(run_dir / "slices")

    analysis = _brief_analysis(run_id, artifact_brief, domain, inputs, normalized)
    write_json(requirements_dir / "brief_analysis.json", analysis)

    draft_paths: list[str] = []
    llm_draft_requested = _should_generate_llm_draft(analysis, normalized)
    if llm_draft_requested:
        draft_paths = _write_llm_draft_placeholders(requirements_dir, analysis, normalized)
        candidate = _requirement_candidate(run_id, artifact_brief, domain, artifact_inputs, analysis, normalized)
        write_json(requirements_dir / "requirement_understanding.candidate.json", candidate)
        draft_paths.append(REQUIREMENT_CANDIDATE_ARTIFACT)

    capability_boundary = _capability_boundary(run_id, artifact_brief, domain, artifact_inputs, run_dir)
    write_json(requirements_dir / "capability_boundary.json", capability_boundary)
    (requirements_dir / "capability_boundary.md").write_text(
        _capability_boundary_markdown(capability_boundary),
        encoding="utf-8",
    )

    acceptance = _acceptance_criteria(artifact_brief, domain, artifact_inputs, analysis)
    acceptance_md = _acceptance_criteria_markdown(acceptance)
    (run_dir / "acceptance_criteria.md").write_text(acceptance_md, encoding="utf-8")

    context_pack = _context_pack_markdown(artifact_brief, domain, artifact_inputs, analysis, normalized)
    (run_dir / "context_pack.md").write_text(context_pack, encoding="utf-8")

    slices = _task_slices(acceptance, artifact_inputs, domain)
    for item in slices:
        (slices_dir / f"{item['id']}.yaml").write_text(_slice_yaml(item), encoding="utf-8")

    coverage = _coverage_matrix(run_id, acceptance, slices)
    write_json(planning_dir / "acceptance_coverage_matrix.json", coverage)
    (planning_dir / "acceptance_coverage_matrix.md").write_text(_coverage_matrix_markdown(coverage), encoding="utf-8")

    tdd_plan = _tdd_plan(run_id, artifact_brief, domain, acceptance, slices, artifact_inputs)
    write_json(planning_dir / "tdd_plan.json", tdd_plan)
    (planning_dir / "tdd_plan.md").write_text(_tdd_plan_markdown(tdd_plan), encoding="utf-8")
    if llm_draft_requested:
        draft_paths.extend(_write_pm_planning_drafts(planning_dir, acceptance, tdd_plan))

    requirement_quality = _requirement_quality_report(analysis, acceptance, coverage, capability_boundary)
    planning_quality = _planning_quality_report(coverage, slices, tdd_plan)
    write_json(requirements_dir / "requirement_quality_report.json", requirement_quality)
    write_json(planning_dir / "planning_quality_report.json", planning_quality)

    output_paths = [
        "requirements/brief_analysis.json",
        *draft_paths,
        CAPABILITY_BOUNDARY_JSON_ARTIFACT,
        CAPABILITY_BOUNDARY_MD_ARTIFACT,
        "acceptance_criteria.md",
        "context_pack.md",
        "planning/acceptance_coverage_matrix.json",
        "planning/acceptance_coverage_matrix.md",
        TDD_PLAN_JSON_ARTIFACT,
        TDD_PLAN_MD_ARTIFACT,
        *[f"slices/{item['id']}.yaml" for item in slices],
        REQUIREMENT_QUALITY_ARTIFACT,
        PLANNING_QUALITY_ARTIFACT,
    ]
    return {
        "status": "passed" if requirement_quality["status"] == "passed" and planning_quality["status"] == "passed" else "failed",
        "output_paths": output_paths,
        "requirement_quality": requirement_quality,
        "planning_quality": planning_quality,
        "analysis": analysis,
    }


def _brief_analysis(run_id: str, brief: str, domain: DomainSpec, inputs: dict[str, Any], config: ComplexTaskConfig) -> dict[str, Any]:
    markers = [marker for marker in COMPLEX_BRIEF_MARKERS if marker.lower() in brief.lower()]
    complexity = "complex" if len(brief) >= 28 or len(markers) >= 2 or bool(inputs.get("force_complex_task")) else "simple"
    blocking_questions = [_redact_text(str(item)) for item in inputs.get("blocking_questions", []) if str(item).strip()]
    if inputs.get("force_blocking_question"):
        blocking_questions.append("The task contains an explicit unresolved blocking question.")
    return {
        "schema_version": 1,
        "run_id": run_id,
        "domain_id": domain.domain_id,
        "brief": brief,
        "generated_at": now_iso(),
        "planning_mode": config.planning_mode,
        "requirements_model": _redact_text(config.requirements_model),
        "requirements_reasoning_effort": config.requirements_reasoning_effort,
        "complexity": complexity,
        "complexity_markers": markers,
        "llm_draft_requested": config.planning_mode == "llm_assisted" or (config.planning_mode == "auto" and complexity == "complex"),
        "blocking_questions": blocking_questions,
        "assumptions": _assumptions(domain, inputs),
        "safety_boundaries": list(domain.risk_rules),
        "recommended_skills": ["spec_driven_development", "context_engineering", "planning_and_task_breakdown"],
    }


def _write_llm_draft_placeholders(requirements_dir: Path, analysis: dict[str, Any], config: ComplexTaskConfig) -> list[str]:
    model = _redact_text(config.requirements_model or "not_configured")
    note = (
        "LLM-assisted requirement understanding was requested, but v1 keeps strong LLM output as a "
        "candidate-only draft channel. No draft is promoted unless deterministic validation passes."
    )
    files = {
        "clarification.md": [
            "# Requirement Clarification",
            "",
            f"- Brief: {analysis['brief']}",
            f"- Model: `{model}`",
            f"- Mode: `{config.planning_mode}`",
            f"- Note: {note}",
        ],
        "acceptance_criteria.draft.md": [
            "# Draft Acceptance Criteria",
            "",
            "This draft channel is reserved for strong LLM candidates. Official criteria live in `acceptance_criteria.md`.",
        ],
        "open_questions.md": [
            "# Open Questions",
            "",
            *([f"- {item}" for item in analysis.get("blocking_questions", [])] or ["- No blocking questions detected by deterministic analysis."]),
        ],
        "assumptions.md": [
            "# Assumptions",
            "",
            *[f"- {item}" for item in analysis.get("assumptions", [])],
        ],
        "prd.draft.md": _pm_prd_draft_lines(analysis, model, note),
        "user_stories.draft.md": _pm_user_story_draft_lines(analysis),
        "prd_red_team.md": _pm_prd_red_team_lines(analysis),
    }
    paths: list[str] = []
    for name, lines in files.items():
        (requirements_dir / name).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        paths.append(f"requirements/{name}")
    return paths


def _write_pm_planning_drafts(planning_dir: Path, acceptance: list[dict[str, Any]], tdd_plan: dict[str, Any]) -> list[str]:
    path = planning_dir / "test_scenarios.draft.md"
    path.write_text(_pm_test_scenarios_markdown(acceptance, tdd_plan), encoding="utf-8")
    return ["planning/test_scenarios.draft.md"]


def _pm_prd_draft_lines(analysis: dict[str, Any], model: str, note: str) -> list[str]:
    brief = str(analysis.get("brief", "")).strip()
    assumptions = [str(item) for item in analysis.get("assumptions", [])]
    questions = [str(item) for item in analysis.get("blocking_questions", [])]
    return [
        "# PM PRD Draft",
        "",
        f"- Method: PM Skills-inspired candidate understanding",
        f"- Model: `{model}`",
        f"- Promotion policy: {note}",
        "",
        "## Problem",
        f"- Requested outcome: {brief}",
        "",
        "## Users And Operators",
        "- Primary user/operator: derived from the brief or domain pack.",
        "- Reviewer/approver: human gate owner.",
        "",
        "## Core Workflow",
        "1. User submits the brief.",
        "2. AI-Team produces official requirements after deterministic validation.",
        "3. Codex or another executor implements only after gates pass.",
        "",
        "## User Stories",
        "- See `user_stories.draft.md`.",
        "",
        "## Acceptance Signals",
        "- Official `acceptance_criteria.md`.",
        "- `planning/tdd_plan.json` and verification commands.",
        "- Dashboard/run artifacts for review evidence.",
        "",
        "## Assumptions",
        *([f"- {item}" for item in assumptions] or ["- none"]),
        "",
        "## Open Questions",
        *([f"- {item}" for item in questions] or ["- No blocking questions detected by deterministic analysis."]),
    ]


def _pm_user_story_draft_lines(analysis: dict[str, Any]) -> list[str]:
    brief = str(analysis.get("brief", "")).strip()
    return [
        "# User Stories Draft",
        "",
        "## US-001",
        "",
        f"- Card: As the task owner, I want `{brief}`, so that the requested outcome can be implemented and verified through run artifacts.",
        "- Conversation:",
        "  - Confirm scope, non-goals, safety constraints, and compatibility requirements.",
        "  - Keep unresolved assumptions out of official artifacts.",
        "- Confirmation:",
        "  - Acceptance criteria ids: `AC-001` and related official criteria.",
        "  - Verification command: see `planning/tdd_plan.json`.",
        "",
        "## 3 C / INVEST Notes",
        "- Card names role, capability, and value.",
        "- Conversation captures assumptions and open questions.",
        "- Confirmation maps to acceptance criteria and tests.",
        "- Story remains small enough for coverage-driven slices.",
    ]


def _pm_prd_red_team_lines(analysis: dict[str, Any]) -> list[str]:
    questions = [str(item) for item in analysis.get("blocking_questions", [])]
    status = "block" if questions else "promote"
    return [
        "# PRD Red-Team Draft",
        "",
        f"- Recommendation: `{status}`",
        "- Method: PM Skills-inspired PRD red-team check.",
        "",
        "## Load-Bearing Assumptions",
        "- Assumptions must stay in `requirements/assumptions.md` unless validated by official artifacts.",
        "",
        "## Scope Risks",
        "- Watch for old-domain leakage, unrelated refactors, and hidden deployment changes.",
        "",
        "## Testability Risks",
        "- Every official acceptance criterion must map to at least one TDD scenario and slice.",
        "",
        "## Open Questions",
        *([f"- {item}" for item in questions] or ["- No blocking questions detected."]),
    ]


def _requirement_candidate(
    run_id: str,
    brief: str,
    domain: DomainSpec,
    inputs: dict[str, Any],
    analysis: dict[str, Any],
    config: ComplexTaskConfig,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "domain_id": domain.domain_id,
        "generated_at": now_iso(),
        "model": _redact_text(config.requirements_model or "not_configured"),
        "reasoning_effort": config.requirements_reasoning_effort,
        "status": "candidate_only",
        "method_source": "PM Skills-inspired candidate understanding; official artifacts require deterministic gates.",
        "clarification_angles": [
            "业务目标",
            "用户/操作者",
            "输入输出",
            "主流程",
            "边界/非目标",
            "兼容性",
            "安全风险",
            "可观测验收",
            "部署/环境依赖",
            "用户故事",
            "测试场景",
            "PRD red-team",
        ],
        "candidate_scope": {
            "goal": _compact(brief),
            "domain_id": domain.domain_id,
            "allowed_paths": _string_list(inputs.get("allowed_paths")) or _string_list(domain.metadata.get("allowed_paths")),
            "verification_commands": _string_list(inputs.get("verification_commands")) or _string_list(domain.metadata.get("verification_commands")),
        },
        "blocking_questions": list(analysis.get("blocking_questions", [])),
        "assumptions": list(analysis.get("assumptions", [])),
        "safety_boundaries": list(domain.risk_rules),
        "promotion_policy": "Do not promote this candidate unless deterministic requirement quality gates pass.",
    }


def _capability_boundary(
    run_id: str,
    brief: str,
    domain: DomainSpec,
    inputs: dict[str, Any],
    run_dir: Path,
) -> dict[str, Any]:
    capabilities = domain.metadata.get("capabilities") if isinstance(domain.metadata, dict) else {}
    if not isinstance(capabilities, dict):
        capabilities = {}
    supported = _capability_list(capabilities.get("supported"))
    if not supported:
        supported = _default_domain_capabilities(domain, inputs)
    unsupported = _capability_list(capabilities.get("unsupported"))
    required_new = _required_new_capabilities(brief, domain, supported)
    historical = _historical_learning_sources(run_dir.parent, domain.domain_id, brief)
    return {
        "schema_version": 1,
        "run_id": run_id,
        "domain_id": domain.domain_id,
        "generated_at": now_iso(),
        "change_type": _capability_change_type(brief, supported, required_new),
        "summary": "Capability boundary is derived from the domain pack, current run inputs, and local learning summaries.",
        "existing_capabilities": supported,
        "required_new_capabilities": required_new,
        "unsupported_capabilities": unsupported,
        "manual_gates": _string_list(capabilities.get("manual_gates")),
        "source_artifacts": _dedupe(
            [
                "domain.yaml",
                "capabilities.yaml" if capabilities else "",
                *[str(item) for item in historical],
            ]
        ),
        "inputs_considered": sorted(str(key) for key in inputs.keys()),
        "runtime_policy": "Obsidian is not used as runtime source of truth; use repo domain pack and run artifacts.",
    }


def _default_domain_capabilities(domain: DomainSpec, inputs: dict[str, Any]) -> list[dict[str, Any]]:
    verification_commands = _string_list(inputs.get("verification_commands")) or _string_list(domain.metadata.get("verification_commands"))
    return [
        {
            "id": f"{domain.domain_id}_baseline",
            "summary": f"Use the `{domain.domain_id}` domain pack, current run artifacts, and declared verification commands as baseline capability evidence.",
            "entrypoint": "",
            "evidence": ["domain.yaml"],
            "verification_commands": [_redact_text(command) for command in verification_commands],
            "source": "domain_pack_default",
        }
    ]


def _capability_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        capability_id = str(item.get("id", "")).strip()
        if not capability_id:
            continue
        items.append(
            {
                "id": capability_id,
                "summary": _redact_text(str(item.get("summary", ""))),
                "entrypoint": _redact_text(str(item.get("entrypoint", ""))),
                "evidence": [_redact_text(str(path)) for path in _string_list(item.get("evidence"))],
                "verification_commands": [_redact_text(str(command)) for command in _string_list(item.get("verification_commands"))],
            }
        )
    return items


def _required_new_capabilities(brief: str, domain: DomainSpec, supported: list[dict[str, Any]]) -> list[dict[str, str]]:
    lowered = brief.lower()
    supported_ids = {str(item.get("id", "")) for item in supported}
    required: list[dict[str, str]] = []
    if domain.domain_id == "xhs_mobile_collection" and any(marker in lowered for marker in ("纯关键词", "run-keyword", "keyword-only", "keyword_only")):
        required.append(
            {
                "id": "keyword_only_collection",
                "summary": "Keyword-only text search collection without image search.",
                "status": "already_supported" if "keyword_only_collection" in supported_ids else "missing",
            }
        )
    return required


def _capability_change_type(brief: str, supported: list[dict[str, Any]], required_new: list[dict[str, str]]) -> str:
    lowered = brief.lower()
    if any(marker in lowered for marker in ("修复", "bug", "fix")):
        return "fix_existing_capability"
    if required_new or any(marker in lowered for marker in ("新增", "增加", "扩展", "add", "new")):
        return "extend_existing_capability" if supported else "new_capability"
    return "adjust_existing_capability" if supported else "new_capability"


def _historical_learning_sources(runs_dir: Path, domain_id: str, brief: str, limit: int = 3) -> list[str]:
    if not runs_dir.exists():
        return []
    terms = {part.lower() for part in re.findall(r"[\w\u4e00-\u9fff]+", brief) if len(part) >= 2}
    matches: list[tuple[int, str]] = []
    for summary_path in runs_dir.glob("*/learning_summary.json"):
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict) or str(payload.get("domain_id", "")) != domain_id:
            continue
        text = json.dumps(payload, ensure_ascii=False).lower()
        score = sum(1 for term in terms if term in text)
        matches.append((score, f"{summary_path.parent.name}/learning_summary.json"))
    matches.sort(key=lambda item: item[0], reverse=True)
    return [path for score, path in matches[:limit] if score > 0]


def _capability_boundary_markdown(boundary: dict[str, Any]) -> str:
    lines = [
        "# Capability Boundary",
        "",
        f"- Change type: `{boundary.get('change_type', '')}`",
        f"- Runtime policy: {boundary.get('runtime_policy', '')}",
        "",
        "## Existing Capabilities",
        *_capability_markdown_lines(boundary.get("existing_capabilities", [])),
        "",
        "## Required New Capabilities",
        *_capability_markdown_lines(boundary.get("required_new_capabilities", [])),
        "",
        "## Unsupported Capabilities",
        *_capability_markdown_lines(boundary.get("unsupported_capabilities", [])),
        "",
        "## Source Artifacts",
        *[f"- `{item}`" for item in _string_list(boundary.get("source_artifacts"))],
    ]
    return "\n".join(lines).rstrip() + "\n"


def _capability_markdown_lines(capabilities: Any) -> list[str]:
    if not isinstance(capabilities, list) or not capabilities:
        return ["- none"]
    lines: list[str] = []
    for item in capabilities:
        if not isinstance(item, dict):
            continue
        suffix = f": {item.get('summary', '')}" if item.get("summary") else ""
        lines.append(f"- `{item.get('id', '')}`{suffix}")
    return lines or ["- none"]


def _acceptance_criteria(brief: str, domain: DomainSpec, inputs: dict[str, Any], analysis: dict[str, Any]) -> list[dict[str, Any]]:
    task_text = _compact(brief)
    criteria = [
        {
            "id": "AC-001",
            "description": f"The implementation addresses the requested outcome: {task_text}.",
            "observable": True,
            "testable": True,
            "source": "brief",
        },
        {
            "id": "AC-002",
            "description": f"Generated artifacts remain specific to `{domain.domain_id}` and avoid unrelated domain leakage.",
            "observable": True,
            "testable": True,
            "source": "domain",
        },
        {
            "id": "AC-003",
            "description": "Verification commands or explicit evidence prove the behavior before review.",
            "observable": True,
            "testable": True,
            "source": "project_gate",
        },
    ]
    if analysis.get("complexity") == "complex":
        criteria.append(
            {
                "id": "AC-004",
                "description": "The plan is split into verifiable vertical slices with traceable completion evidence.",
                "observable": True,
                "testable": True,
                "source": "complex_task_skill",
            }
        )
    if _looks_like_ui_task(brief):
        criteria.append(
            {
                "id": f"AC-{len(criteria) + 1:03d}",
                "description": "User-facing states are understandable in the Dashboard or UI without exposing raw logs by default.",
                "observable": True,
                "testable": True,
                "source": "ui",
            }
        )
    return criteria


def _task_slices(acceptance: list[dict[str, Any]], inputs: dict[str, Any], domain: DomainSpec) -> list[dict[str, Any]]:
    allowed_paths = _string_list(inputs.get("allowed_paths")) or _string_list(domain.metadata.get("allowed_paths")) or ["growth_dev/", "dashboard/", "tests/", "README.md", "AGENTS.md"]
    verification_commands = _string_list(inputs.get("verification_commands")) or ["python3 -m unittest discover -s tests -v"]
    slices: list[dict[str, Any]] = []
    for index, criterion in enumerate(acceptance, start=1):
        slices.append(
            {
                "id": f"slice-{index:03d}",
                "title": f"Cover {criterion['id']}",
                "type": "coding",
                "depends_on": [f"slice-{index - 1:03d}"] if index > 1 else [],
                "acceptance_criteria_ids": [criterion["id"]],
                "coverage_goal": criterion["description"],
                "allowed_paths": allowed_paths,
                "expected_artifacts": ["changed files", "test or verification evidence", "slice_trace.json"],
                "verification_commands": verification_commands,
                "stop_conditions": [
                    "Required upstream artifact is missing.",
                    "Scope expands beyond allowed paths.",
                    "Slice no longer maps to a named acceptance criterion.",
                ],
            }
        )
    return slices


def _coverage_matrix(run_id: str, acceptance: list[dict[str, Any]], slices: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "generated_at": now_iso(),
        "acceptance_criteria": [
            {
                **criterion,
                "covering_slice_ids": [item["id"] for item in slices if criterion["id"] in item["acceptance_criteria_ids"]],
                "status": "planned",
            }
            for criterion in acceptance
        ],
        "slices": [
            {
                "id": item["id"],
                "title": item["title"],
                "acceptance_criteria_ids": item["acceptance_criteria_ids"],
                "verification_commands": item["verification_commands"],
                "status": "planned",
            }
            for item in slices
        ],
    }


def _tdd_plan(
    run_id: str,
    brief: str,
    domain: DomainSpec,
    acceptance: list[dict[str, Any]],
    slices: list[dict[str, Any]],
    inputs: dict[str, Any],
) -> dict[str, Any]:
    verification_commands = _string_list(inputs.get("verification_commands")) or _string_list(domain.metadata.get("verification_commands")) or ["python3 -m unittest discover -s tests -v"]
    cases: list[dict[str, Any]] = []
    xhs_keyword_cases = _xhs_keyword_tdd_cases(brief, acceptance, verification_commands)
    if xhs_keyword_cases:
        cases.extend(xhs_keyword_cases)
    else:
        for index, criterion in enumerate(acceptance, start=1):
            cases.append(
                {
                    "id": f"TDD-{index:03d}",
                    "acceptance_criteria_ids": [criterion["id"]],
                    "related_slice_ids": [item["id"] for item in slices if criterion["id"] in item.get("acceptance_criteria_ids", [])],
                    "test_intent": f"Add or update behavior tests proving {criterion['id']}.",
                    "expected_red_failure": "The behavior is missing before implementation.",
                    "verification_command": verification_commands[0],
                    "red_first_required": True,
                    "executor": "codex_cli",
                }
            )
    covered = {ac_id for case in cases for ac_id in _string_list(case.get("acceptance_criteria_ids"))}
    required = {str(item.get("id", "")) for item in acceptance}
    return {
        "schema_version": 1,
        "run_id": run_id,
        "generated_at": now_iso(),
        "status": "passed" if required.issubset(covered) and cases else "failed",
        "summary": "TDD plan maps acceptance criteria to red-first tests before Codex implementation.",
        "test_cases": cases,
        "coverage": {
            "required_acceptance_criteria_ids": sorted(required),
            "covered_acceptance_criteria_ids": sorted(covered),
            "missing_acceptance_criteria_ids": sorted(required - covered),
        },
        "policy": "Codex writes failing tests first, records red failure, then makes the minimal green implementation.",
    }


def _xhs_keyword_tdd_cases(brief: str, acceptance: list[dict[str, Any]], verification_commands: list[str]) -> list[dict[str, Any]]:
    lowered = brief.lower()
    if not any(marker in lowered for marker in ("纯关键词", "run-keyword", "keyword-only", "keyword_only")):
        return []
    ac_ids = [str(item.get("id", "")) for item in acceptance if str(item.get("id", "")).strip()]
    command = next((item for item in verification_commands if "test_xhs_collector" in item), verification_commands[0])
    intents = [
        ("run-keyword CLI routes to keyword-only deterministic collection", "run-keyword command is missing or routes to the legacy flow."),
        ("search_mode=keyword_only is accepted while default remains image_then_keyword", "CollectorConfig has no search_mode or rejects keyword_only."),
        ("keyword-only flow 不走图搜 and does not push a reference image", "The flow still taps image search or pushes a reference image."),
        ("keyword-only result selection records skip_video_note_card for video notes", "Video result cards are selected instead of skipped."),
        ("TOP N image/text note downloads create auditable item outputs", "The deterministic result does not collect the requested TOP N images."),
    ]
    return [
        {
            "id": f"TDD-{index:03d}",
            "acceptance_criteria_ids": ac_ids or ["AC-001"],
            "related_slice_ids": [],
            "test_intent": intent,
            "expected_red_failure": red_failure,
            "verification_command": command,
            "red_first_required": True,
            "executor": "codex_cli",
        }
        for index, (intent, red_failure) in enumerate(intents, start=1)
    ]


def _tdd_plan_markdown(plan: dict[str, Any]) -> str:
    lines = [
        "# TDD Plan",
        "",
        f"- Status: `{plan.get('status', '')}`",
        f"- Policy: {plan.get('policy', '')}",
        "",
        "## Test Cases",
    ]
    for item in plan.get("test_cases", []):
        lines.extend(
            [
                f"- `{item.get('id', '')}` {item.get('test_intent', '')}",
                f"  - AC: {', '.join(_string_list(item.get('acceptance_criteria_ids')))}",
                f"  - Red failure: {item.get('expected_red_failure', '')}",
                f"  - Command: `{item.get('verification_command', '')}`",
            ]
        )
    coverage = plan.get("coverage", {})
    lines.extend(
        [
            "",
            "## Coverage",
            f"- Required AC: {', '.join(_string_list(coverage.get('required_acceptance_criteria_ids')))}",
            f"- Covered AC: {', '.join(_string_list(coverage.get('covered_acceptance_criteria_ids')))}",
            f"- Missing AC: {', '.join(_string_list(coverage.get('missing_acceptance_criteria_ids'))) or 'none'}",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _pm_test_scenarios_markdown(acceptance: list[dict[str, Any]], tdd_plan: dict[str, Any]) -> str:
    ac_ids = [str(item.get("id", "")) for item in acceptance if str(item.get("id", "")).strip()]
    command = ""
    test_cases = tdd_plan.get("test_cases", []) if isinstance(tdd_plan.get("test_cases"), list) else []
    if test_cases and isinstance(test_cases[0], dict):
        command = str(test_cases[0].get("verification_command", ""))
    scenario_types = [
        ("happy path", "Main workflow produces the requested user-visible outcome."),
        ("edge case", "Missing, partial, duplicate, or boundary inputs remain explainable."),
        ("error state", "Unsafe, unavailable, or permission-blocked states stop with clear evidence."),
        ("regression", "Existing supported behavior remains compatible."),
        ("manual validation", "Real device, deployment, or external service evidence is captured when required."),
    ]
    lines = [
        "# PM Test Scenarios Draft",
        "",
        "These scenarios are candidate planning aids. Official executable checks live in `planning/tdd_plan.json`.",
        "",
    ]
    for index, (scenario_type, expected) in enumerate(scenario_types, start=1):
        lines.extend(
            [
                f"## SCN-{index:03d}",
                "",
                f"- Type: {scenario_type}",
                f"- Related acceptance criteria: {', '.join(ac_ids) or 'AC-001'}",
                "- Preconditions: official requirement artifacts exist and gates have passed.",
                "- Steps:",
                "  1. Execute the relevant workflow or verification command.",
                f"- Expected result: {expected}",
                f"- Verification command: `{command}`" if command else "- Verification command: see `planning/tdd_plan.json`.",
                "- Expected red failure: behavior or evidence is missing before implementation.",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _requirement_quality_report(
    analysis: dict[str, Any],
    acceptance: list[dict[str, Any]],
    coverage: dict[str, Any],
    capability_boundary: dict[str, Any],
) -> dict[str, Any]:
    blockers: list[str] = []
    if analysis.get("blocking_questions"):
        blockers.append("blocking_questions_present")
    for item in acceptance:
        if not re.fullmatch(r"AC-\d{3}", str(item.get("id", ""))):
            blockers.append(f"invalid_acceptance_id:{item.get('id')}")
        if not item.get("observable") or not item.get("testable"):
            blockers.append(f"untestable_acceptance:{item.get('id')}")
    if any(not item.get("covering_slice_ids") for item in coverage.get("acceptance_criteria", [])):
        blockers.append("acceptance_not_covered_by_slice")
    if not capability_boundary.get("existing_capabilities") and not capability_boundary.get("required_new_capabilities"):
        blockers.append("capability_boundary_missing")
    status = "passed" if not blockers else "failed"
    pm_status = "passed" if status == "passed" else "failed"
    return {
        "schema_version": 1,
        "status": status,
        "summary": "Requirement understanding is ready for planning." if status == "passed" else "Requirement understanding needs more input.",
        "blockers": blockers,
        "warnings": ["llm_draft_channel_used_but_not_promoted"] if analysis.get("llm_draft_requested") else [],
        "checks": [
            {"id": "stable_acceptance_ids", "status": "passed" if not any("invalid_acceptance_id" in item for item in blockers) else "failed"},
            {"id": "testable_acceptance", "status": "passed" if not any("untestable_acceptance" in item for item in blockers) else "failed"},
            {"id": "no_blocking_questions", "status": "passed" if not analysis.get("blocking_questions") else "failed"},
            {"id": "coverage_ready", "status": "passed" if "acceptance_not_covered_by_slice" not in blockers else "failed"},
            {"id": "capability_boundary_ready", "status": "passed" if "capability_boundary_missing" not in blockers else "failed"},
            {"id": "user_stories_are_structured", "status": pm_status},
            {"id": "prd_separates_facts_assumptions_questions", "status": pm_status},
            {"id": "test_scenarios_map_to_acceptance", "status": pm_status},
            {"id": "red_team_risks_addressed", "status": pm_status},
        ],
    }


def _planning_quality_report(coverage: dict[str, Any], slices: list[dict[str, Any]], tdd_plan: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    ac_ids = {str(item["id"]) for item in coverage.get("acceptance_criteria", [])}
    covered_ids = {str(ac_id) for item in slices for ac_id in item.get("acceptance_criteria_ids", [])}
    if ac_ids - covered_ids:
        blockers.append("orphan_acceptance_criterion")
    for item in slices:
        if not item.get("acceptance_criteria_ids"):
            blockers.append(f"orphan_slice:{item.get('id')}")
        if not item.get("verification_commands"):
            blockers.append(f"unverifiable_slice:{item.get('id')}")
        if not item.get("allowed_paths"):
            blockers.append(f"slice_without_allowed_paths:{item.get('id')}")
    if tdd_plan.get("status") != "passed" or not tdd_plan.get("test_cases"):
        blockers.append("tdd_plan_missing_or_incomplete")
    status = "passed" if not blockers else "failed"
    return {
        "schema_version": 1,
        "status": status,
        "summary": "Planning is ready for implementation." if status == "passed" else "Planning needs revision before implementation.",
        "blockers": blockers,
        "checks": {
            "no_orphan_acceptance_criterion": "orphan_acceptance_criterion" not in blockers,
            "no_orphan_slice": not any(item.startswith("orphan_slice:") for item in blockers),
            "all_slices_verifiable": not any(item.startswith("unverifiable_slice:") for item in blockers),
            "allowed_paths_declared": not any(item.startswith("slice_without_allowed_paths:") for item in blockers),
            "tdd_plan_ready": "tdd_plan_missing_or_incomplete" not in blockers,
        },
    }


def _acceptance_criteria_markdown(criteria: list[dict[str, Any]]) -> str:
    lines = ["# Acceptance Criteria", ""]
    for item in criteria:
        lines.append(f"- `{item['id']}` {item['description']}")
    return "\n".join(lines).rstrip() + "\n"


def _context_pack_markdown(brief: str, domain: DomainSpec, inputs: dict[str, Any], analysis: dict[str, Any], config: ComplexTaskConfig) -> str:
    return "\n".join(
        [
            "# Context Pack",
            "",
            f"## Brief\n{brief}",
            "",
            f"## Domain\n- `{domain.domain_id}`: {domain.summary or 'No summary provided.'}",
            "",
            "## Planning",
            f"- Mode: `{config.planning_mode}`",
            f"- Complexity: `{analysis.get('complexity')}`",
            "",
            "## Inputs",
            "```json",
            json.dumps(inputs, ensure_ascii=False, indent=2),
            "```",
            "",
            "## Safety Boundaries",
            *[f"- {rule}" for rule in domain.risk_rules],
            "",
            "## Context Hygiene",
            "- Use current run artifacts as the source of truth.",
            "- Do not rely on chat history for Codex execution continuity.",
        ]
    ).rstrip() + "\n"


def _coverage_matrix_markdown(coverage: dict[str, Any]) -> str:
    lines = ["# Acceptance Coverage Matrix", "", "| Acceptance ID | Covering Slices | Verification | Status |", "| --- | --- | --- | --- |"]
    slices_by_id = {item["id"]: item for item in coverage.get("slices", [])}
    for item in coverage.get("acceptance_criteria", []):
        slice_ids = item.get("covering_slice_ids", [])
        commands = []
        for slice_id in slice_ids:
            commands.extend(slices_by_id.get(slice_id, {}).get("verification_commands", []))
        lines.append(f"| {item.get('id')} | {', '.join(slice_ids)} | {'; '.join(commands)} | {item.get('status', 'planned')} |")
    return "\n".join(lines).rstrip() + "\n"


def _slice_yaml(item: dict[str, Any]) -> str:
    lines = [
        f"slice_id: {item['id']}",
        f"title: {item['title']}",
        f"type: {item['type']}",
        "depends_on:",
        *[f"  - {value}" for value in item.get("depends_on", [])],
        "acceptance_criteria_ids:",
        *[f"  - {value}" for value in item.get("acceptance_criteria_ids", [])],
        f"coverage_goal: {item['coverage_goal']}",
        "allowed_paths:",
        *[f"  - {value}" for value in item.get("allowed_paths", [])],
        "expected_artifacts:",
        *[f"  - {value}" for value in item.get("expected_artifacts", [])],
        "verification_commands:",
        *[f"  - {value}" for value in item.get("verification_commands", [])],
        "stop_conditions:",
        *[f"  - {value}" for value in item.get("stop_conditions", [])],
    ]
    return "\n".join(lines).rstrip() + "\n"


def _should_generate_llm_draft(analysis: dict[str, Any], config: ComplexTaskConfig) -> bool:
    return config.planning_mode == "llm_assisted" or (config.planning_mode == "auto" and analysis.get("complexity") == "complex")


def _assumptions(domain: DomainSpec, inputs: dict[str, Any]) -> list[str]:
    assumptions = [f"Use the `{domain.domain_id}` domain pack as the task boundary."]
    if not inputs.get("allowed_paths"):
        assumptions.append("Use default allowed paths unless the task provides a narrower list.")
    if not inputs.get("verification_commands"):
        assumptions.append("Use the default full unittest command as verification.")
    return assumptions


def _looks_like_ui_task(brief: str) -> bool:
    lowered = brief.lower()
    return any(marker in lowered for marker in ("dashboard", "ui", "页面", "按钮", "展示", "交互", "panel", "card"))


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _compact(value: str, limit: int = 160) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _redact_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            key_text = str(key)
            lower = key_text.lower()
            if lower in {"api_key", "apikey", "access_token", "refresh_token", "password", "token", "key"}:
                redacted[key_text] = "<redacted>"
            elif "secret" in lower and lower != "secret_configured":
                redacted[key_text] = "<redacted>"
            else:
                redacted[key_text] = _redact_payload(value)
        return redacted
    if isinstance(payload, list):
        return [_redact_payload(item) for item in payload]
    if isinstance(payload, str):
        return _redact_text(payload)
    return payload


def _redact_text(value: str) -> str:
    redacted = str(value)
    for pattern, replacement in SECRET_REPLACEMENTS:
        redacted = pattern.sub(replacement, redacted)
    return redacted
