---
name: using_agent_skills
description: Use when an agent must choose which project skill applies to a task phase, especially when several skills appear relevant or context pollution is likely.
---

# Skill: using_agent_skills

## Purpose
Choose the smallest useful set of project skills for the current phase.

## When To Use
- A run is moving between define, plan, execution, engineering, review, or ship phases.
- Multiple skills look relevant.
- The next agent needs a clear method without loading every skill.

## Inputs
- User brief or run brief.
- Current artifact state in `tasks/current/` or `runs/<run_id>/`.
- `skills/registry.yaml`.
- Optional: `routing_matrix.md`, `context_budget.md`.

## Outputs
- One primary skill.
- At most one companion skill.
- A short note naming skills intentionally not loaded.

## Steps
1. Identify the current phase and missing artifact.
2. Read only the registry entries that match the phase.
3. Select one primary skill based on trigger and output.
4. Add one companion only when a concrete gate needs it.
5. Record the selection in the task package or run note.

## Quality Gate
- Exactly one primary skill is selected.
- Companion skill count is zero or one.
- Selection is tied to an artifact or gate, not a vague similarity.
- Non-selected obvious skills are explicitly deferred.

## Context Hygiene
- Do not load all `SKILL.md` files.
- Do not use this skill as a wrapper around every action.
- Prefer artifact state over chat history when routing.
