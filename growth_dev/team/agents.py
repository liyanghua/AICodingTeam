from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..utils import ensure_dir, now_iso, write_json
from .models import AgentRun, AgentSpec, DomainSpec, TeamRunRecord, TeamSpec


@dataclass(slots=True)
class AgentContext:
    run_id: str
    run_dir: Path
    brief: str
    team: TeamSpec
    domain: DomainSpec
    inputs: dict[str, Any]
    record: TeamRunRecord

    def artifact_path(self, name: str) -> Path:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Unsafe artifact path: {name}")
        return self.run_dir / path

    def write_text(self, name: str, content: str) -> str:
        path = self.artifact_path(name)
        ensure_dir(path.parent)
        path.write_text(content, encoding="utf-8")
        return name

    def write_json(self, name: str, payload: Any) -> str:
        path = self.artifact_path(name)
        write_json(path, payload)
        return name

    def read_text(self, name: str) -> str:
        return self.artifact_path(name).read_text(encoding="utf-8")


@dataclass(slots=True)
class AgentOutput:
    output_paths: list[str] = field(default_factory=list)
    risk_events: list[str] = field(default_factory=list)
    status: str = "completed"
    message: str = ""


AgentHandler = Callable[[AgentSpec, AgentContext], AgentOutput]


def run_deterministic_agent(agent: AgentSpec, context: AgentContext) -> AgentRun:
    started_at = now_iso()
    handler = AGENT_HANDLERS.get(agent.id, _generic_agent)
    try:
        output = handler(agent, context)
    except Exception as exc:  # noqa: BLE001 - persisted into a run record for offline inspection.
        return AgentRun(
            agent_id=agent.id,
            status="failed",
            started_at=started_at,
            finished_at=now_iso(),
            risk_events=[f"agent_exception:{type(exc).__name__}:{exc}"],
            output_paths=[],
            message=str(exc),
        )

    return AgentRun(
        agent_id=agent.id,
        status=output.status,
        started_at=started_at,
        finished_at=now_iso(),
        risk_events=output.risk_events,
        output_paths=output.output_paths,
        message=output.message,
    )


def _merged_inputs(context: AgentContext) -> dict[str, Any]:
    payload = dict(context.domain.defaults)
    payload.update(context.inputs)
    return payload


def _lines(*items: str) -> str:
    return "\n".join(items).rstrip() + "\n"


def _bullet(values: list[str]) -> list[str]:
    return [f"- {value}" for value in values]


def _generic_agent(agent: AgentSpec, context: AgentContext) -> AgentOutput:
    outputs: list[str] = []
    for output_name in agent.outputs:
        if output_name.endswith(".json"):
            outputs.append(context.write_json(output_name, {"agent": agent.id, "status": "planned"}))
        else:
            outputs.append(
                context.write_text(
                    output_name,
                    _lines(
                        f"# {agent.id.title()} Artifact",
                        "",
                        f"Domain: {context.domain.domain_id}",
                        f"Brief: {context.brief}",
                        "",
                        "This deterministic v1 agent produced a placeholder artifact.",
                    ),
                )
            )
    return AgentOutput(output_paths=outputs, message="generic deterministic artifact")


def _orchestrator(agent: AgentSpec, context: AgentContext) -> AgentOutput:
    inputs = _merged_inputs(context)
    task_payload = {
        "run_id": context.run_id,
        "domain_id": context.domain.domain_id,
        "brief": context.brief,
        "inputs": inputs,
        "task_tree": [
            {"id": "define", "owner": "product", "outputs": ["prd.md"]},
            {"id": "design", "owner": "architect", "outputs": ["tech_spec.md"]},
            {"id": "evaluate", "owner": "qa", "outputs": ["eval.md"]},
            {"id": "implement", "owner": "coder", "outputs": ["coding_prompt.md", "code_run_record.json"]},
            {"id": "verify", "owner": "verifier", "outputs": ["test_report.md"]},
            {"id": "publish", "owner": "publisher", "outputs": ["final_report.md"]},
        ],
        "agents": [item.id for item in context.team.agents],
        "gates": [gate.to_dict() for gate in context.team.gates],
    }
    outputs = [context.write_json("task.yaml", task_payload)]

    context_text = _lines(
        "# Context",
        "",
        f"Run: {context.run_id}",
        f"Domain: {context.domain.domain_id}",
        f"Brief: {context.brief}",
        "",
        "## Domain Summary",
        context.domain.summary or "No domain summary provided.",
        "",
        "## Inputs",
        "```json",
        json.dumps(inputs, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Risk Rules",
        *_bullet(context.domain.risk_rules),
        "",
        "## Team Pipeline",
        *_bullet([f"{item.id}: {', '.join(item.outputs)}" for item in context.team.agents]),
    )
    outputs.append(context.write_text("context.md", context_text))
    return AgentOutput(output_paths=outputs, message="task and context created")


def _product(agent: AgentSpec, context: AgentContext) -> AgentOutput:
    inputs = _merged_inputs(context)
    text = _lines(
        "# PRD",
        "",
        "## Background",
        context.domain.summary or "The runtime turns a one-shot brief into a gated artifact pipeline.",
        "",
        "## Goal",
        f"Deliver a reproducible result for: {context.brief}",
        "",
        "## Users",
        "- Operator who submits a business brief once",
        "- Agent team that consumes fixed artifacts instead of free-form chat",
        "- Reviewer who checks gates, risk events, and final report quality",
        "",
        "## Scope",
        *_domain_scope(context.domain.domain_id),
        "",
        "## Inputs",
        *_bullet([f"{key}: {value}" for key, value in inputs.items()]),
        "",
        "## Acceptance Criteria",
        "- Required artifacts exist in the run directory",
        "- Gates fail when required upstream artifacts are missing",
        "- Risk boundaries are written explicitly in review outputs",
        "- The final report links the stage artifacts and verification result",
    )
    return AgentOutput(output_paths=[context.write_text("prd.md", text)], message="prd created")


def _architect(agent: AgentSpec, context: AgentContext) -> AgentOutput:
    text = _lines(
        "# Technical Spec",
        "",
        "## Runtime Architecture",
        "- Local stdlib-only state machine",
        "- File-driven agents with explicit input and output artifacts",
        "- Domain packs supply schemas, defaults, evaluation rules, and risk rules",
        "- Run records are serialized as JSON for replay and status inspection",
        "",
        "## Data Contract",
        "```json",
        json.dumps(
            {
                "input_schema": context.domain.input_schema,
                "output_schema": context.domain.output_schema,
                "defaults": context.domain.defaults,
            },
            ensure_ascii=False,
            indent=2,
        ),
        "```",
        "",
        "## Gates",
        *_bullet([f"{gate.id} before {gate.before_agent}: {', '.join(gate.required_artifacts)}" for gate in context.team.gates]),
        "",
        "## Domain Integration",
        *_domain_architecture_notes(context.domain),
    )
    return AgentOutput(output_paths=[context.write_text("tech_spec.md", text)], message="technical spec created")


def _ux(agent: AgentSpec, context: AgentContext) -> AgentOutput:
    text = _lines(
        "# UI Spec",
        "",
        "## Primary Experience",
        *_domain_ux_notes(context.domain.domain_id),
        "",
        "## States",
        "- Ready state shows the configured input and next action",
        "- Running state exposes current agent and gate progress",
        "- Empty state names the missing upstream artifact",
        "- Error state writes the failure into the run record",
        "- Report state links final artifacts without requiring another prompt",
    )
    return AgentOutput(output_paths=[context.write_text("ui_spec.md", text)], message="ui spec created")


def _qa(agent: AgentSpec, context: AgentContext) -> AgentOutput:
    text = _lines(
        "# Eval",
        "",
        "## Unit Gates",
        "- Parse team.yaml into TeamSpec",
        "- Parse domain.yaml into DomainSpec",
        "- Fail gate checks when required artifacts are absent",
        "- Pass gate checks when required artifacts exist",
        "- Serialize and deserialize TeamRunRecord",
        "",
        "## Integration Gates",
        "- Run every deterministic agent in order",
        "- Verify declared outputs are present after each stage",
        "- Confirm before_coding runs before coder",
        "- Confirm before_publish runs before publisher",
        "",
        "## Domain Evaluation Rules",
        *_bullet(context.domain.evaluation_rules),
        "",
        "## Review Gate",
        "- Reports must include failures and caveats, not only success samples",
        "- Risk events must be explicit and carried into the final run record",
    )
    return AgentOutput(output_paths=[context.write_text("eval.md", text)], message="eval created")


def _coder(agent: AgentSpec, context: AgentContext) -> AgentOutput:
    text = _lines(
        "# Coding Prompt",
        "",
        f"Implement the requested domain task for run `{context.run_id}`.",
        "",
        "## Required Inputs",
        "- AGENTS.md",
        "- task.yaml",
        "- context.md",
        "- prd.md",
        "- tech_spec.md",
        "- ui_spec.md",
        "- eval.md",
        "",
        "## Constraints",
        "- Keep v1 deterministic and stdlib-only unless the domain pack explicitly permits a dependency",
        "- Preserve existing harness behavior and shared schemas",
        "- Write results into the run directory",
        "- Stop and record a risk event instead of bypassing platform challenges",
        "",
        "## Domain Notes",
        *_domain_coding_notes(context.domain),
    )
    record = {
        "agent": "coder",
        "status": "planned",
        "run_id": context.run_id,
        "domain_id": context.domain.domain_id,
        "used_existing_harness": context.domain.domain_id == "xhs_browser_benchmark",
        "outputs": ["coding_prompt.md"],
        "next_stage": "reviewer",
    }
    return AgentOutput(
        output_paths=[
            context.write_text("coding_prompt.md", text),
            context.write_json("code_run_record.json", record),
        ],
        message="coding prompt created",
    )


def _reviewer(agent: AgentSpec, context: AgentContext) -> AgentOutput:
    missing_live = _missing_live_frameworks(context.domain)
    lines = [
        "# Review Report",
        "",
        "## Safety Boundary",
        *_bullet(context.domain.risk_rules),
        "",
        "## Schema Review",
        "- Domain inputs and outputs are declared in domain.yaml",
        "- Agent outputs are declared in team.yaml and validated by the runtime",
        "- Run records include agent status, gate status, artifacts, and risk events",
    ]
    if missing_live:
        lines.extend(
            [
                "",
                "## Missing Live Framework Packages",
                *_bullet(missing_live),
                "",
                "The deterministic v1 runtime keeps these as unavailable until explicit package installation and manual-login runner wiring are completed.",
            ]
        )
    lines.extend(
        [
            "",
            "## Decision",
            "Pass for local deterministic runtime. Live external automation remains gated by manual login and package availability.",
        ]
    )
    return AgentOutput(output_paths=[context.write_text("review_report.md", _lines(*lines))], message="review created")


def _verifier(agent: AgentSpec, context: AgentContext) -> AgentOutput:
    risk_events: list[str] = []
    sections = [
        "# Test Report",
        "",
        "## Runtime Checks",
        "- Deterministic agents executed through the file pipeline",
        "- Gates are enforced before coding and before publishing",
        "- Declared artifacts are checked after each stage",
    ]

    if context.domain.domain_id == "xhs_browser_benchmark":
        try:
            from ..benchmark import benchmark
            from ..tasks import default_task_spec

            task = default_task_spec()
            inputs = _merged_inputs(context)
            if "keyword" in inputs:
                task.keyword = str(inputs["keyword"])
            if "top_n" in inputs:
                task.top_n = min(int(inputs["top_n"] or 3), 3)
            task.candidate_pool = max(task.top_n, min(int(inputs.get("candidate_pool", 20) or 20), 20))
            outcome = benchmark(task, frameworks=["mock"], runs_dir=context.run_dir / "verifier_runs", suite="team-mock")
            report_path = Path(outcome.artifacts["report_md"])
            sections.extend(
                [
                    "",
                    "## XHS Mock Benchmark",
                    "- Status: passed",
                    f"- Run id: {outcome.run_record.run_id}",
                    f"- Report: {report_path}",
                ]
            )
        except Exception as exc:  # noqa: BLE001 - verifier must preserve failure detail.
            risk_events.append(f"xhs_mock_verifier_failed:{type(exc).__name__}:{exc}")
            sections.extend(
                [
                    "",
                    "## XHS Mock Benchmark",
                    "- Status: failed",
                    f"- Error: {type(exc).__name__}: {exc}",
                ]
            )
    else:
        sections.extend(
            [
                "",
                "## Domain Verification",
                "- Status: planned",
                "- This domain pack uses artifact verification only in v1",
            ]
        )

    status = "completed" if not risk_events else "failed"
    return AgentOutput(
        output_paths=[context.write_text("test_report.md", _lines(*sections))],
        risk_events=risk_events,
        status=status,
        message="verification finished",
    )


def _publisher(agent: AgentSpec, context: AgentContext) -> AgentOutput:
    agent_lines = [
        f"- {run.agent_id}: {run.status} ({', '.join(run.output_paths) or 'no outputs'})"
        for run in context.record.agent_runs
    ]
    gate_lines = [
        f"- {gate.gate_id}: {gate.status} before {gate.before_agent}"
        for gate in context.record.gate_results
    ]
    text = _lines(
        "# Final Report",
        "",
        f"Run: {context.run_id}",
        f"Domain: {context.domain.domain_id}",
        f"Brief: {context.brief}",
        "",
        "## Agent Results",
        *(agent_lines or ["- No agent runs recorded"]),
        "",
        "## Gate Results",
        *(gate_lines or ["- No gates recorded"]),
        "",
        "## Artifacts",
        *_bullet(sorted(context.record.artifacts.values())),
        "",
        "## Recommendation",
        *_domain_recommendation(context.domain.domain_id),
    )
    return AgentOutput(output_paths=[context.write_text("final_report.md", text)], message="final report created")


def _domain_scope(domain_id: str) -> list[str]:
    if domain_id == "xhs_browser_benchmark":
        return [
            "- Compare Playwright MCP, Stagehand, Skyvern, HyperAgent, and browser-use against one collection task",
            "- Use a mock benchmark first and keep real-site runs manual-login, low-frequency, and challenge-stop",
            "- Produce stability, completeness, risk, cost, and maintainability evidence",
        ]
    if domain_id == "web_monitoring":
        return [
            "- Monitor a target web page for content changes",
            "- Store summary, diff metadata, and screenshot evidence",
            "- Reuse the same team runtime without changing orchestration code",
        ]
    return ["- Execute the domain pack using the shared agent runtime"]


def _domain_architecture_notes(domain: DomainSpec) -> list[str]:
    if domain.domain_id == "xhs_browser_benchmark":
        return [
            "- Existing benchmark harness remains the verifier tool for mock-mode confidence",
            "- Framework adapters stay isolated and report unavailable states clearly",
            "- No live runner is required for deterministic team runtime success",
        ]
    if domain.domain_id == "web_monitoring":
        return [
            "- Domain-specific monitor implementation can be added behind the coder stage",
            "- Output remains a structured report plus optional screenshot evidence",
            "- Runtime code does not need to change for new monitor targets",
        ]
    return ["- Domain-specific behavior is supplied by the domain pack"]


def _domain_ux_notes(domain_id: str) -> list[str]:
    if domain_id == "xhs_browser_benchmark":
        return [
            "- Mock page includes search, candidate cards, detail pages, media, comments, replies, load-more, empty, and risk states",
            "- Real-site flow must expose manual login and pause-on-challenge state",
            "- Report view prioritizes missing fields, risk events, and failed framework samples",
        ]
    if domain_id == "web_monitoring":
        return [
            "- Operator enters a target URL and monitoring objective",
            "- Result view shows previous summary, current summary, diff status, and screenshot evidence",
            "- Error states distinguish navigation failure, empty content, and changed layout",
        ]
    return ["- Present current stage, next gate, artifacts, and final report"]


def _domain_coding_notes(domain: DomainSpec) -> list[str]:
    if domain.domain_id == "xhs_browser_benchmark":
        return [
            "- Start from mock benchmark verification before any real-site pilot",
            "- Keep non-mock frameworks optional and mark missing packages as unavailable",
            "- Do not implement captcha solving, stealth, proxies, or private API reverse engineering",
        ]
    if domain.domain_id == "web_monitoring":
        return [
            "- Keep fetch or browser tooling behind a domain adapter",
            "- Persist page summary and diff evidence in the run directory",
            "- Treat authentication and paywalls as manual or out of scope unless authorized",
        ]
    return ["- Follow the domain pack schemas and risk rules"]


def _domain_recommendation(domain_id: str) -> list[str]:
    if domain_id == "xhs_browser_benchmark":
        return [
            "- Use Playwright MCP or mock mode as the deterministic baseline",
            "- Promote Stagehand or other live frameworks only after package installation and manual-login pilot gates pass",
            "- Keep production data access on authorized interfaces or written permission",
        ]
    if domain_id == "web_monitoring":
        return [
            "- Add a domain adapter for navigation and screenshot capture",
            "- Keep runtime unchanged while evolving monitoring-specific evaluation rules",
        ]
    return ["- Add a richer domain adapter after the deterministic pipeline is stable"]


def _missing_live_frameworks(domain: DomainSpec) -> list[str]:
    if domain.domain_id != "xhs_browser_benchmark":
        return []
    frameworks = domain.frameworks or ["playwright-mcp", "stagehand", "skyvern", "hyperagent", "browser-use"]
    return [
        f"{framework}: live package or bridge not installed in deterministic v1"
        for framework in frameworks
        if framework != "mock"
    ]


AGENT_HANDLERS: dict[str, AgentHandler] = {
    "orchestrator": _orchestrator,
    "product": _product,
    "architect": _architect,
    "ux": _ux,
    "qa": _qa,
    "coder": _coder,
    "reviewer": _reviewer,
    "verifier": _verifier,
    "publisher": _publisher,
}
