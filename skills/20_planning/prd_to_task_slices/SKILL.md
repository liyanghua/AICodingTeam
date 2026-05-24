---
name: prd_to_task_slices
description: Split a PRD into vertical slices that can be implemented and verified independently.
---

# PRD to Task Slices

## Purpose
Turn PRD, tech spec, and UI spec into thin vertical slices that can each be implemented, reviewed, tested, and demoed independently.

## When To Use
- A PRD is ready.
- The next step is implementation planning.
- The work is large enough to need independent slices.
- A Codex prompt would otherwise ask for too much in one run.

## Inputs
- `tasks/current/prd.md`
- `tasks/current/tech_spec.md`
- `tasks/current/ui_spec.md`
- `tasks/current/context.md`
- `tasks/current/eval.md`, if already drafted.

## Outputs
- `tasks/current/slices/*.yaml`
- `tasks/current/slices/*.md`

## Steps
1. Identify user-visible increments and acceptance criteria.
2. Prefer vertical slices that cross data, service, UI, tests, and report/artifact evidence.
3. Avoid horizontal tasks like "backend only" or "CSS only" unless they unblock a vertical slice.
4. Mark dependencies, allowed paths, verification commands, and expected artifacts.
5. Keep each slice small enough for one Codex run and one human review.
6. Use `task_slice_template.yaml` and `issue_body_template.md`.

## Quality Gate
- Each slice is independently meaningful.
- Each slice can be tested.
- Slice boundaries are explicit.
- A failed slice can be diagnosed without rerunning the whole project.
