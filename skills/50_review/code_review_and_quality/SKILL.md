---
name: code_review_and_quality
description: Use when a diff, run output, or proposed change needs independent quality review before apply, publish, merge, or release.
---

# Skill: code_review_and_quality

## Purpose
Review a change for bugs, regressions, safety boundary violations, missing tests, and unrelated scope.

## When To Use
- A worktree diff is ready.
- The reviewer stage is running.
- The user asks for a review.
- A before-publish or apply gate is near.

## Inputs
- Diff or changed files.
- Acceptance criteria.
- Tests run.
- Risk events and run record.
- Optional: `review_checklist.md`, `review_report_template.md`.

## Outputs
- `review_report.md`.
- Severity-ranked findings.
- Recommendation: block, revise, or ready.

## Steps
1. Read acceptance criteria and scope.
2. Inspect diff before broad source context.
3. Check behavior, tests, safety, and maintainability.
4. Lead with actionable findings by severity.
5. State residual risk and missing verification.

## Quality Gate
- Findings are grounded in file paths or artifacts.
- Bugs and regressions come before style comments.
- Missing tests are called out.
- Unrelated refactors are rejected.

## Context Hygiene
- Do not review chat history as source of truth.
- Do not load unrelated modules unless the diff crosses their boundary.
- Keep summaries shorter than findings.
