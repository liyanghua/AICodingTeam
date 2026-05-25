---
name: debugging_and_error_recovery
description: Use when tests fail, review fails, provider calls fail, runtime errors appear, or a run needs a focused recovery plan.
---

# Skill: debugging_and_error_recovery

## Purpose
Stop the line, classify the failure, and produce a minimal verified recovery plan.

## When To Use
- Tests, review, CI, provider, CLI, or runtime failed.
- A run is stuck or marked failed.
- A previous fix attempt did not address root cause.

## Inputs
- Failing command and output.
- Relevant logs and run record.
- Current diff.
- Optional: `failure_taxonomy.md`, `fix_plan_template.md`.

## Outputs
- Failure category.
- `fix_plan.md`.
- Regression test proposal.

## Steps
1. Reproduce or bound the failure.
2. Classify the failure with the taxonomy.
3. Minimize the suspected cause.
4. Propose the smallest fix and regression guard.
5. Verify the fix with the original failing command.

## Quality Gate
- Failure category is explicit.
- Fix is tied to evidence.
- Regression coverage is added or justified.
- New risk events are not hidden.

## Context Hygiene
- Load failing logs first, not every artifact.
- Do not retry blindly without a hypothesis.
- Do not mix unrelated failures into one fix plan.
