---
name: ai_coding_quality_review
description: Use when AI-generated or agent-authored changes need quality-risk review for architecture drift, contract drift, safety boundaries, test illusion, or maintainability before commit, publish, or release.
---

# Skill: ai_coding_quality_review

## Purpose
Review AI-coding changes for fixed risk patterns that ordinary diff review can miss: architecture drift, scope creep, contract drift, test illusion, observability gaps, and project-specific safety or data-integrity risks.

This skill is a companion to `code_review_and_quality`. Use the ordinary review skill first for bugs and regressions, then use this skill when the change needs architecture, quality trend, or AI-coding risk diagnosis.

## When To Use
- Large AI-generated or agent-authored diffs.
- User asks for AI-coding quality review, health score, or brooks-lint-style review.
- Mobile collector, Taobao, XHS, Mobilerun runtime, asset center, sync, OSS, PostgreSQL, or deployment script changes.
- Before commit, publish, release, or handoff when maintainability and safety boundaries matter.
- After repeated failures that suggest test illusion, missing observability, or architecture drift.

## Inputs
- Current diff and changed files.
- Existing `code_review_and_quality` report if available.
- Acceptance criteria, task slice, or user plan.
- Tests run and verification output.
- Risk events, logs, manifests, schemas, step events, and run artifacts.
- Reference files: `risk_taxonomy.md`, `quality_report_template.md`, and `review_examples.md` when needed.

## Outputs
- Structured quality report using `quality_report_template.md`.
- Overall health score from `0-100`.
- Conclusion: `block`, `revise`, `ready_with_risk`, or `ready`.
- Up to 10 severity-ranked findings with risk code, evidence, and fix recommendation.

## Steps
1. Read the scope, acceptance criteria, and current diff before broad source context.
2. Read the ordinary review report if it exists; do not repeat low-level findings unless they affect the quality risk conclusion.
3. Load `risk_taxonomy.md` and map findings to the fixed risk codes.
4. Check changed files against ownership boundaries: collector channel, runtime, asset center, deployment, tests, and docs.
5. Verify evidence from files, tests, logs, schemas, or run artifacts. Do not use chat history as evidence.
6. Score health using the project gate policy and choose one conclusion.
7. Write the report with at most 10 high-signal findings, sorted by severity.

## Quality Gate
- Every finding has a risk code, severity, symptom, root cause, consequence, fix, evidence, and recommendation.
- P0/P1 findings must block or require revision unless explicitly accepted by the user.
- Safety boundary, secret boundary, data integrity, and contract drift findings outrank style or naming issues.
- Missing verification is itself a finding when the change touches a core workflow.
- The report must state residual risk even when the recommendation is `ready`.

## Context Hygiene
- Do not use chat history as evidence.
- Prefer current diff, changed files, tests, logs, run artifacts, manifests, and schemas.
- Do not load unrelated modules unless the diff crosses their boundary.
- Keep this skill as a companion, not a replacement, for `code_review_and_quality`.
- Avoid broad codebase tours; inspect only files needed to validate a risk claim.
