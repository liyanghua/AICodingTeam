# Slice Loop Template

## Required Prompt Context

- overall goal:
- current slice:
- completed slices:
- pending slices:
- current diff:
- blockers:
- allowed paths:
- verification commands:

## Loop

1. Select exactly one slice.
2. Confirm allowed paths and stop conditions.
3. Confirm the slice acceptance criteria ids.
4. Add or update tests when the slice changes behavior.
5. Implement the smallest meaningful change.
6. Run verification commands.
7. Update `codex/slices/<slice_id>/slice_trace.json`.
8. Stop on blocker, unrelated scope, failed verification, or completed slice.
9. Continue only after the current slice has a completed or failed trace.
