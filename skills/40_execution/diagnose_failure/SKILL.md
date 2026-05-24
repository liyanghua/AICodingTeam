---
name: diagnose_failure
description: Reproduce, classify, and fix a failing run or test before retrying the coding agent.
---

# Diagnose Failure

## Purpose
Turn a failed test, review, provider call, runtime crash, or Codex run into a concrete fix plan and regression guard instead of retrying blindly.

## When To Use
- Tests fail.
- Review fails.
- A run record reports runtime failure.
- Dashboard/watch shows a run stuck, failed, or missing expected artifacts.
- Codex exits without a structured summary or provider/model errors appear.

## Inputs
- Failing command and output.
- `runs/<run_id>/team_run_record.json`
- `runs/<run_id>/events.jsonl`
- Relevant `codex/*.log`, `diff.patch`, and `git_status.txt`.
- Current code diff and nearby tests.

## Outputs
- `tasks/current/fix_plan.md` or run-local `fix_plan.md`.
- Failure category from `failure_taxonomy.md`.
- Regression test suggestions and retry criteria.

## Steps
1. Reproduce the failure with the smallest command or artifact read.
2. Classify the failure using `failure_taxonomy.md`.
3. Reduce the failure surface to the smallest affected contract.
4. Inspect only the code, artifact, or provider boundary needed for a hypothesis.
5. Propose the minimal fix and the regression test that would fail before the fix.
6. Write the retry command and stop conditions in `fix_plan_template.md`.

## Quality Gate
- Failure category is explicit.
- Root cause is narrow enough to act on.
- Regression coverage is proposed.
- The next coding run has a clear fix target and does not repeat the same blind attempt.
