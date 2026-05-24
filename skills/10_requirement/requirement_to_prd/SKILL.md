---
name: requirement_to_prd
description: Convert clarified context into a PRD that an engineering agent can execute without guessing.
---

# Requirement to PRD

## Purpose
Compile the clarified business context into a PRD that product, engineering, QA, and Codex can all use as the same source of product truth.

## When To Use
- Context has been clarified.
- A PRD is missing or stale.
- The next agent needs a stable product contract.
- A run needs business-readable artifacts before code generation.

## Inputs
- `tasks/current/context.md`
- Business brief
- Optional `DESIGN.md`
- Existing `tasks/current/prd.md`, when revising.

## Outputs
- `tasks/current/prd.md`
- `tasks/current/acceptance_criteria.md`

## Steps
1. State background and the concrete business goal in one paragraph.
2. Identify primary users, secondary users, and the jobs they are trying to complete.
3. Describe the core flow from user action to visible result.
4. Define functional scope, non-goals, data objects, and UI states.
5. Write acceptance criteria as observable behaviors, not implementation details.
6. Call out risks, dependencies, and questions that affect delivery.
7. Use `prd_template.md` and `acceptance_criteria_template.md`.

## Quality Gate
- Goal is explicit.
- User role and scenario are clear.
- Acceptance criteria are testable.
- Non-goals prevent the coding agent from expanding scope.
- The PRD can feed `prd_to_task_slices` without extra chat context.
