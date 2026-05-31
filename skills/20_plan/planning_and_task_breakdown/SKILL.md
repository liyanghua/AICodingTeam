---
name: planning_and_task_breakdown
description: Use when a spec must be broken into small, dependency-aware implementation tasks or vertical slices before coding begins.
---

# Skill: planning_and_task_breakdown

## Purpose
Break a spec into acceptance criteria coverage-driven vertical slices that can be implemented, tested, reviewed, and rolled back independently.

## When To Use
- The feature spans multiple modules or files.
- A single Codex run would be too large or vague.
- The user asks for an implementation plan.
- Acceptance criteria need explicit implementation coverage before coding.

## Inputs
- `prd.md`, `tech_spec.md`, `ui_spec.md`, `eval.md`.
- Existing `context_pack.md`.
- Acceptance criteria with stable ids.
- Optional: `task_slice_template.yaml`, `plan_template.md`, `acceptance_coverage_matrix_template.md`.

## Outputs
- `tasks/current/slices/*.yaml`.
- `tasks/current/plan.md`.
- `tasks/current/acceptance_coverage_matrix.md` or `.json`.
- Slice-level verification commands.

## Steps
1. Assign stable ids to acceptance criteria.
2. Build an acceptance criteria coverage matrix before writing slices.
3. Split work by vertical outcome, not by frontend/backend/database layers.
4. Attach acceptance criteria ids, boundaries, allowed paths, expected artifacts, dependencies, stop conditions, and verification commands to each slice.
5. Keep each slice reviewable and independently verifiable.
6. Re-check the matrix for orphan slice and orphan acceptance criterion cases.

## Quality Gate
- Each slice can be demoed or verified alone.
- Each slice maps to at least one acceptance criterion; no orphan slice.
- Each acceptance criterion maps to at least one slice; no orphan acceptance criterion.
- No slice requires broad unrelated cleanup.
- Dependencies are explicit.
- Tests and gates are attached before coding.

## Context Hygiene
- Do not load implementation files unless needed to size a slice.
- Do not split by organization chart or technology layer.
- Do not create more slices than the risk justifies.
- Do not create slices that only rename, rearrange, or prepare code unless they directly unlock named acceptance criteria.
