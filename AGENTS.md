# AGENTS.md

## Agent Entry Role

This file is the AI-coding entrypoint for the root repository. It defines execution rules, safety boundaries, file ownership, and project-level reading order. It is not the full product whitepaper.

For the project identity and document map, read `docs/PROJECT_OVERVIEW.md` first after this file.

## Product Goal

This repository is an AI-native Agent Team Runtime. It turns business briefs, domain specs, and run artifacts into gated engineering artifacts, controlled code-generation runs, review evidence, verification records, and human-confirmed delivery.

The current primary domain is `app_generation`: PRD / business-spec-to-local-app generation for producing runnable, reviewable, and iterated business applications.

`document-to-skill-engineering-package/` is an upstream strategy and Skill compilation capability. It compiles business strategy documents into Strategy IR, Skill Spec, Workflow DAG, Data Requirement, Tool Binding, Evidence Pack, and Eval artifacts that can feed richer business context for `app_generation`.

XHS/browser automation remains an important reusable domain pack and historical starting point, but it is not the whole-project identity.

## Main Product Chain

```text
Business strategy documents
-> document-to-skill compiler
-> Strategy IR / Skill Spec / Workflow DAG
-> Data Requirement / Tool Binding / Evidence Pack / Eval
-> app_generation Business PRD++ / AppSpec / DataSpec / KnowledgeSpec / ToolSpec / EvalSpec
-> controlled Code Agent generation
-> local app preview / review / verification / repair
-> run artifacts and improvement candidates
```

## Architecture Principles

- Manual login only. Do not automate credential collection, captcha bypass, fingerprint spoofing, proxy rotation, or anti-bot evasion.
- Do not turn business strategy documents directly into prompts. Compile them into Strategy IR, data requirements, tool bindings, evidence, and eval contracts first.
- Do not let LLM output become factual business conclusions without evidence.
- Keep all outputs structured and reproducible.
- Preserve backward-compatible APIs and task schemas.
- Store run artifacts in `runs/` and task specs in `tasks/current/`.
- Keep the team runtime domain-agnostic. New tasks should add `domains/<domain_id>/` packs instead of rewriting orchestration code.
- Treat agents as fixed input/output workers, not free-form chat participants.
- Keep adapters isolated. Each framework gets its own runner and does not share mutable browser state.
- When `--executor codex` is used, keep orchestration deterministic: Codex may implement and review code, but context must come from run artifacts rather than prior chat history.
- Codex coding runs must use an isolated git worktree and persist prompt, state summary, schema, stdout/stderr, diff, review, and verification records under `runs/<run_id>/codex/`.

## File Ownership

- Project overview: `docs/PROJECT_OVERVIEW.md`
- Task package: `tasks/current/`
- Domain packs: `domains/`
- Primary app generation domain docs: `docs/app_generation_*.md`
- Upstream document-to-skill compiler: `document-to-skill-engineering-package/`
- Team runtime: `growth_dev/team/`
- Core harness: `growth_dev/`
- Mock site: `growth_dev/mock_site.py`
- Scoring and reporting: `growth_dev/scoring.py`, `growth_dev/reporting.py`
- Framework adapters: `growth_dev/adapters/`

`tasks/current/` describes the active task package. It must not be used as the root project identity when it disagrees with `docs/PROJECT_OVERVIEW.md`.

## Project Skills

- Project-level skills live under `skills/` and are indexed by `skills/registry.yaml`.
- For skill routing, spec writing, context engineering, task breakdown, incremental implementation, TDD planning, failure recovery, or code review, read `skills/registry.yaml` first and then the corresponding `SKILL.md`.
- Skills define the project method layer; they do not replace per-run artifacts in `tasks/current/` or execution evidence in `runs/<run_id>/`.
- The first batch call order is `using_agent_skills -> spec_driven_development -> context_engineering -> planning_and_task_breakdown -> incremental_implementation -> test_driven_development -> debugging_and_error_recovery -> code_review_and_quality`.
- `ai_coding_quality_review` is a P1 companion after normal review for AI-coding architecture drift, contract drift, safety, data-integrity, and deployment-secret risk.
- Skills are not better because there are more of them. Default to one primary skill per phase and at most one companion skill to avoid context pollution.
- PM Skills-inspired PRD, user story, red-team, and test scenario templates are candidate understanding aids under existing P0 skills; they are not active skills and do not override deterministic gates or run artifacts.
- Complex tasks should use coverage-driven slice planning: acceptance criteria map to `slices/*.yaml`, Codex slice-loop traces, and an implementation completion gate.

## Coding Rules

- Prefer the standard library unless a dependency is already present.
- Keep modules focused and small.
- Use deterministic fixture generation for tests.
- Keep v1 team agents deterministic and file-driven.
- Keep Codex prompts narrow: include the goal, allowed paths, current state summary, failed tests, acceptance criteria, stop conditions, and verification commands.
- For Codex slice-loop work, continuity must come from run artifacts, slice yaml, acceptance coverage matrix, per-slice trace, current diff, and verification evidence, not chat history.
- Codex final responses must be structured JSON with `summary`, `files_changed`, `tests_run`, `risk_events`, `blockers`, and `next_action`.
- For Dashboard or UI changes, read root `DESIGN.md` first and keep styles aligned with its design tokens, component rules, and business-friendly language.
- Do not add unrelated refactors.

## Testing Rules

- Unit tests must cover count parsing, fixture generation, schema validation, and scoring.
- Integration tests must cover the mock site and report generation.
- Team runtime tests must cover team/domain parsing, gates, run record serialization, CLI entrypoints, and domain reuse.
- Codex executor tests must cover command construction, prompt bundle generation, missing binary failures, fake Codex execution, review output, and worktree verification.
- If a real framework package is missing, the adapter must fail clearly and mark itself unavailable.

## Review Rules

- Check that safety boundaries remain intact.
- Check that run outputs preserve the shared schema.
- Check that risk events are explicit and never hidden.

## Deployment Rules

- Do not attempt real-world scraping beyond the approved low-frequency, manual-login benchmark flow.
- Do not add production automation until the benchmark harness is proven locally.

## Do Not

- Do not bypass platform security.
- Do not hardcode private API usage.
- Do not create hidden background scrapers.
- Do not mutate unrelated files.
