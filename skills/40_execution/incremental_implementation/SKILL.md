---
name: incremental_implementation
description: Use when implementing a feature or fix in small reviewable slices, especially when changes span multiple files or need rollback-friendly progress.
---

# Skill: incremental_implementation

## Purpose
Implement one vertical slice at a time while preserving reviewability, rollback safety, and whole-task continuity through a Codex slice-loop.

## When To Use
- A coding agent is working from `tasks/current/slices/*.yaml`.
- The diff touches multiple files.
- The work needs frequent verification.
- The run needs observable per-slice progress and continuity across Codex turns.

## Inputs
- One selected slice.
- Context pack.
- Acceptance coverage matrix.
- Completed and pending slice summaries.
- Eval and verification commands.
- Allowed paths.

## Outputs
- Changed files for the slice.
- `codex/slices/<slice_id>/slice_trace.json`.
- `implementation_record.md` or `code_run_record.json`.
- `implementation_completion_gate.md` when all slices are done.
- Test evidence.

## Steps
1. Read the overall goal, acceptance coverage matrix, and exactly one selected slice.
2. Confirm allowed paths, stop conditions, completed slices, pending slices, current diff, blockers, and verification commands.
3. Run the Codex slice-loop one slice at a time; do not start a second slice until the current trace is completed or failed.
4. Make the smallest meaningful change that satisfies the current slice acceptance criteria.
5. Run the slice verification command.
6. Record files changed, tests run, risks, blockers, acceptance coverage, and next action in `codex/slices/<slice_id>/slice_trace.json`.
7. After the final slice, evaluate the implementation completion gate against the original acceptance criteria.

## Quality Gate
- Only one slice is in progress.
- `codex/slices/<slice_id>/slice_trace.json` exists for each attempted slice.
- Diff remains small enough to review.
- Verification is run before moving to the next slice.
- Acceptance coverage stays aligned with the completed slice set.
- Whole-task completion is based on the completion gate, not only on "all slices ran".
- Unrelated refactors are deferred.

## Context Hygiene
- Do not preload future slices.
- Do not include unrelated source context for convenience.
- Summarize repeated evidence instead of pasting full logs.
- Do not rely on chat history for continuity; use run artifacts, slice yaml, coverage matrix, trace, and current diff.
