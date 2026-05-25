---
name: planning_and_task_breakdown
description: Use when a spec must be broken into small, dependency-aware implementation tasks or vertical slices before coding begins.
---

# Skill: planning_and_task_breakdown

## Purpose
Break a spec into small vertical slices that can be implemented, tested, reviewed, and rolled back independently.

## When To Use
- The feature spans multiple modules or files.
- A single Codex run would be too large or vague.
- The user asks for an implementation plan.

## Inputs
- `prd.md`, `tech_spec.md`, `ui_spec.md`, `eval.md`.
- Existing `context_pack.md`.
- Optional: `task_slice_template.yaml`, `plan_template.md`.

## Outputs
- `tasks/current/slices/*.yaml`.
- `tasks/current/plan.md`.
- Slice-level verification commands.

## Steps
1. Identify end-to-end user-visible outcomes.
2. Split work by vertical slice, not by frontend/backend/database layers.
3. Mark dependencies and stop conditions.
4. Attach acceptance criteria and verification commands to each slice.
5. Keep each slice reviewable.

## Quality Gate
- Each slice can be demoed or verified alone.
- No slice requires broad unrelated cleanup.
- Dependencies are explicit.
- Tests and gates are attached before coding.

## Context Hygiene
- Do not load implementation files unless needed to size a slice.
- Do not split by organization chart or technology layer.
- Do not create more slices than the risk justifies.
