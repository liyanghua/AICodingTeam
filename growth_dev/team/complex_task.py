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
    if _should_generate_llm_draft(analysis, normalized):
        draft_paths = _write_llm_draft_placeholders(requirements_dir, analysis, normalized)

    acceptance = _acceptance_criteria(artifact_brief, domain, artifact_inputs, analysis)
    acceptance_md = _acceptance_criteria_markdown(acceptance)
    (run_dir / "acceptance_criteria.md").write_text(acceptance_md, encoding="utf-8")

    context_pack = _context_pack_markdown(artifact_brief, domain, artifact_inputs, analysis, normalized)
    (run_dir / "context_pack.md").write_text(context_pack, encoding="utf-8")

    slices = _task_slices(acceptance, artifact_inputs)
    for item in slices:
        (slices_dir / f"{item['id']}.yaml").write_text(_slice_yaml(item), encoding="utf-8")

    coverage = _coverage_matrix(run_id, acceptance, slices)
    write_json(planning_dir / "acceptance_coverage_matrix.json", coverage)
    (planning_dir / "acceptance_coverage_matrix.md").write_text(_coverage_matrix_markdown(coverage), encoding="utf-8")

    requirement_quality = _requirement_quality_report(analysis, acceptance, coverage)
    planning_quality = _planning_quality_report(coverage, slices)
    write_json(requirements_dir / "requirement_quality_report.json", requirement_quality)
    write_json(planning_dir / "planning_quality_report.json", planning_quality)

    output_paths = [
        "requirements/brief_analysis.json",
        *draft_paths,
        "acceptance_criteria.md",
        "context_pack.md",
        "planning/acceptance_coverage_matrix.json",
        "planning/acceptance_coverage_matrix.md",
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
    }
    paths: list[str] = []
    for name, lines in files.items():
        (requirements_dir / name).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        paths.append(f"requirements/{name}")
    return paths


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


def _task_slices(acceptance: list[dict[str, Any]], inputs: dict[str, Any]) -> list[dict[str, Any]]:
    allowed_paths = _string_list(inputs.get("allowed_paths")) or ["growth_dev/", "dashboard/", "tests/", "README.md", "AGENTS.md"]
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


def _requirement_quality_report(analysis: dict[str, Any], acceptance: list[dict[str, Any]], coverage: dict[str, Any]) -> dict[str, Any]:
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
    status = "passed" if not blockers else "failed"
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
        ],
    }


def _planning_quality_report(coverage: dict[str, Any], slices: list[dict[str, Any]]) -> dict[str, Any]:
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
