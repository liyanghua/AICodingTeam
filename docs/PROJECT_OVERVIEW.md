# Project Overview

## Project Identity

This repository is an **AI-native Agent Team Runtime**.

Its job is to turn business context into gated artifacts, controlled code-generation runs, review evidence, verification records, and human-confirmed delivery. It is not a single XHS automation project, not a free-form chat app, and not an ungoverned code-generation wrapper.

The current primary domain is `app_generation`: a PRD / business-spec-to-local-app generation domain for producing runnable, reviewable, and iterated business applications.

## End-to-End Business Compiler Chain

The intended product chain is:

```text
Business strategy documents
-> document-to-skill compiler
-> Strategy IR / Skill Spec / Workflow DAG
-> Data Requirement / Tool Binding / Evidence Pack / Eval
-> app_generation business compiler
-> Business PRD++ / AppSpec / DataSpec / KnowledgeSpec / ToolSpec / EvalSpec
-> controlled Code Agent generation
-> local app preview / review / verification / repair
-> reusable runtime artifacts and improvement candidates
```

This means `document-to-skill-engineering-package` is an upstream strategy and skill compilation capability. It is not promoted to `domains/` in the current architecture, but its outputs can feed the business context, knowledge, data, tool, evidence, and evaluation layers used by `app_generation`.

## Core Layers

### 1. Agent Team Runtime

The runtime lives under `growth_dev/team/` and turns a brief or domain request into structured run artifacts. It keeps orchestration deterministic, file-driven, and replayable.

Key artifacts live in:

- `tasks/current/` for the active task package.
- `runs/<run_id>/` for per-run evidence, logs, diffs, reviews, tests, and release records.
- `domains/` for reusable domain packs.

### 2. Project Skills Method Layer

Project skills live under `skills/` and are indexed by `skills/registry.yaml`. They define the method layer for spec writing, context selection, planning, TDD, implementation, debugging, and review.

Skills guide how artifacts are created. They do not replace `tasks/current/` or `runs/<run_id>/` as the source of truth.

### 3. Upstream Strategy Compilation

`document-to-skill-engineering-package/` compiles business strategy documents into executable strategy assets:

- `Strategy IR`
- `Skill Spec`
- `Workflow DAG`
- `Data Requirement`
- `Tool Binding`
- `Evidence Pack`
- `Eval`

Those assets are intended to become structured upstream inputs for richer business app generation. The package keeps its own local `README.md`, `AGENTS.md`, specs, examples, and tests because it has a focused compiler architecture.

### 4. Domain Packs And Current Primary Domain

`app_generation` is the current P0 domain. It turns PRD or business-spec inputs into local prototype applications through a governed pipeline:

```text
input PRD / business context
-> normalized requirements
-> app contract
-> acceptance criteria
-> planning and slices
-> Codex / CodeAgent execution in an isolated worktree
-> review and verification
-> preview and human-confirmed apply
```

XHS and browser automation domains remain important reusable domain packs and historical starting points. They are not the whole-project identity.

### 5. Workbench, Observability, And Repair

The Dashboard and workbench expose run state, node context, artifacts, preview controls, Codex progress, and right-side Agent collaboration.

The V2 canvas direction is documented as an experience layer over existing artifacts. It should make business goals, pages, capabilities, data, tools, validation, and repair into selectable and traceable objects without replacing the underlying runtime.

## Document Map

Start here:

- [`../AGENTS.md`](../AGENTS.md): AI coding entrypoint, boundaries, ownership, and execution rules.
- [`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md): project identity, product chain, and document map.
- [`../README.md`](../README.md): human quick start and CLI entrypoints.

For `app_generation`:

- [`app_generation_spec.md`](app_generation_spec.md): upgraded Business App Compiler product specification.
- [`app_generation_architecture.md`](app_generation_architecture.md): v1 architecture and artifact contracts.
- [`app_generation_prd_to_local_app_spec.md`](app_generation_prd_to_local_app_spec.md): PRD-to-local-app domain contract.
- [`app_generation_workbench_spec.md`](app_generation_workbench_spec.md): observable workbench specification.
- [`app_generation_canvas_experience_spec.md`](app_generation_canvas_experience_spec.md): V2 canvas experience direction.
- [`app_generation_runway_timeline_spec.md`](app_generation_runway_timeline_spec.md): Runway Timeline main workbench experience, aligning PRD input, business steps, app preview, Agent collaboration, and folded engineering evidence.
- [`app_generation_node_context_contract.md`](app_generation_node_context_contract.md): node and Agent interaction context contracts.
- [`app_generation_agent_bridge_spec.md`](app_generation_agent_bridge_spec.md): right-side Agent provider and action protocol.
- [`app_generation_codex_observability_spec.md`](app_generation_codex_observability_spec.md): Code Agent progress visibility.
- [`app_generation_acceptance_and_testing.md`](app_generation_acceptance_and_testing.md): app generation acceptance and testing strategy.

For capability-runtime architecture:

- [`skill-runtime-whitepaper.md`](skill-runtime-whitepaper.md): why App is a shell over a shared capability-runtime, the architecture evolution, the service / skill / runtime three-layer relation, the runtime kernel plus multi-scenario skills model, the MVP 1.0 colocated form, and the preconditions for Code Agent capability spillover.
- [`skill-runtime-architecture-v5.html`](skill-runtime-architecture-v5.html): full-chain minimal architecture diagram from business scenario to generated app to shared ecommerce scenario skills.
- [`skill-runtime-ecosystem-flywheel.html`](skill-runtime-ecosystem-flywheel.html): ecosystem flywheel diagram — four roles (trainer / TP operator / data provider+platform / merchant) × entry / contribution / revenue share, and how the six-step flywheel forms moats. End-state view only, not the MVP roadmap.
- [`business-plan-capability-runtime.html`](business-plan-capability-runtime.html): business plan that walks every internal role (CEO / BD / product / engineering / content partner / finance / marketing / HR) through the minimum two-sided loop (content partner + merchant), the four-stage path from MVP to ecosystem, the monetization and revenue-share mechanics, risks, and reference companies (Salesforce, Shopify, HubSpot, 有赞 / 微盟, 阿里生意参谋, Notion).

For upstream document-to-skill compilation:

- [`../document-to-skill-engineering-package/README.md`](../document-to-skill-engineering-package/README.md): package overview and quick start.
- [`../document-to-skill-engineering-package/AGENTS.md`](../document-to-skill-engineering-package/AGENTS.md): local AI-coding rules for the compiler package.
- [`../document-to-skill-engineering-package/specs/STRATEGY_IR_SPEC.md`](../document-to-skill-engineering-package/specs/STRATEGY_IR_SPEC.md): Strategy IR contract.
- [`../document-to-skill-engineering-package/specs/SKILL_SPEC.md`](../document-to-skill-engineering-package/specs/SKILL_SPEC.md): generated Skill package contract.
- [`../document-to-skill-engineering-package/specs/DATA_REQUIREMENT_DSL.md`](../document-to-skill-engineering-package/specs/DATA_REQUIREMENT_DSL.md): data requirement DSL.
- [`../document-to-skill-engineering-package/specs/TOOL_CONTRACT_SPEC.md`](../document-to-skill-engineering-package/specs/TOOL_CONTRACT_SPEC.md): tool contract rules.
- [`../document-to-skill-engineering-package/specs/EVIDENCE_PACK_SPEC.md`](../document-to-skill-engineering-package/specs/EVIDENCE_PACK_SPEC.md): evidence pack contract.
- [`../document-to-skill-engineering-package/specs/EVAL_SPEC.md`](../document-to-skill-engineering-package/specs/EVAL_SPEC.md): evaluation contract.

For XHS and browser automation domains:

- [`focus_task.md`](focus_task.md): browser-skill and AgentBox direction.
- [`../domains/xhs_browser_benchmark/domain.yaml`](../domains/xhs_browser_benchmark/domain.yaml): XHS browser benchmark domain pack.
- [`../domains/xhs_mobile_collection/domain.yaml`](../domains/xhs_mobile_collection/domain.yaml): XHS mobile collection domain pack.
- [`../domains/mobilerun_xhs_collector/domain.yaml`](../domains/mobilerun_xhs_collector/domain.yaml): MobileRun XHS collector domain pack.

## AI Agent Reading Order

When entering the repository, use this order:

1. Read [`../AGENTS.md`](../AGENTS.md) for execution rules and safety boundaries.
2. Read this overview to understand the project identity and current primary chain.
3. If the task touches app generation, read the relevant `docs/app_generation_*` spec before editing code.
4. If the task touches business document compilation, read `document-to-skill-engineering-package/AGENTS.md` and the relevant package specs.
5. If the task touches a domain pack, read that domain's `domain.yaml` and nearby tests.
6. Use `tasks/current/` and `runs/<run_id>/` only as task/run truth, not as the project identity.

## Non-Goals And Safety Boundaries

- Do not treat XHS automation as the only product goal.
- Do not turn strategy documents directly into long prompts.
- Do not let LLM output become factual business conclusions without evidence.
- Do not automate credential collection, captcha bypass, fingerprint spoofing, proxy rotation, or anti-bot evasion.
- Do not mutate generated apps or main workspace code without the established review, verification, and human-confirmed apply gates.
