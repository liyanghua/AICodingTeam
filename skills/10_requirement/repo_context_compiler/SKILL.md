---
name: repo_context_compiler
description: Summarize the current repository, impacted modules, and change boundaries for a task.
---

# Repo Context Compiler

## Purpose
Build a compact repository context pack so planning and coding agents know the relevant files, ownership boundaries, test surfaces, and safety constraints.

## When To Use
- A task needs code changes.
- Impacted modules are unclear.
- The agent should not rely on chat history alone.
- A Codex run will be started and must receive deterministic context from files.

## Inputs
- `AGENTS.md`
- `README.md`
- `DESIGN.md`, for Dashboard or UI work.
- Relevant files under `growth_dev/`, `domains/`, `dashboard/`, and `tests/`.
- Current `tasks/current/` artifacts, when present.

## Outputs
- Repo context section in `tasks/current/context.md`.
- Optional `tasks/current/impact_analysis.md`.

## Steps
1. Read only the files needed to understand the task path.
2. Identify modules, owners, public contracts, artifacts, and tests likely to change.
3. Map data flow from input brief to run artifacts, dashboard/API, or domain pack output.
4. Record compatibility, safety, and "do not touch" boundaries.
5. Summarize the smallest viable change area and likely verification commands.
6. Use `context_template.md` and `impact_analysis_template.md`.

## Quality Gate
- Impacted files are named.
- Boundaries are explicit.
- No hidden assumptions remain.
- The context is short enough for a code prompt but specific enough to stop unrelated refactors.
