---
name: incremental_implementation
description: Use when implementing a feature or fix in small reviewable slices, especially when changes span multiple files or need rollback-friendly progress.
---

# Skill: incremental_implementation

## Purpose
Implement one vertical slice at a time while preserving reviewability and rollback safety.

## When To Use
- A coding agent is working from `tasks/current/slices/*.yaml`.
- The diff touches multiple files.
- The work needs frequent verification.

## Inputs
- One selected slice.
- Context pack.
- Eval and verification commands.
- Allowed paths.

## Outputs
- Changed files for the slice.
- `implementation_record.md` or `code_run_record.json`.
- Test evidence.

## Steps
1. Read one slice and its acceptance criteria.
2. Confirm allowed paths and stop conditions.
3. Make the smallest meaningful change.
4. Run the slice verification command.
5. Record files changed, tests run, risks, blockers, and next action.

## Quality Gate
- Only one slice is in progress.
- Diff remains small enough to review.
- Verification is run before moving to the next slice.
- Unrelated refactors are deferred.

## Context Hygiene
- Do not preload future slices.
- Do not include unrelated source context for convenience.
- Summarize repeated evidence instead of pasting full logs.
