# AI Coding Quality Gate

## Purpose

The AI Coding Quality Gate is a report-only review layer for agent-authored or AI-assisted changes. It complements ordinary bug and regression review by checking recurring AI-coding risks: architecture drift, scope creep, contract drift, weak tests, missing observability, and project-specific safety boundaries.

This first version does not block CI, merge, publish, or deployment. It creates a structured report that can later become a before-publish gate after the team has enough calibration data.

## When To Use

Use this gate after `code_review_and_quality` when a change is large, AI-generated, touches multiple ownership boundaries, or affects one of these areas:

- Mobile collection flows for XHS, Taobao, or future channels.
- Asset center sync, PostgreSQL, OSS, SQLite, or object metadata.
- Mobilerun or LLM fallback runtime behavior.
- Deployment scripts, SSH configuration, cloud credentials, or environment profiles.
- Release preparation where architecture and quality trend risk matters more than line-level bugs alone.

## Evidence Policy

Review evidence must come from the current diff, changed files, tests, run artifacts, logs, schemas, manifests, and explicit risk events. Do not treat chat history or remembered intent as source of truth. If a claim cannot be tied to an artifact, mark it as an assumption or omit it.

## Risk Model

General AI-coding risks:

- `AIQ-ARCH-DRIFT`: Architecture boundaries drift, ownership becomes unclear, or domain-specific logic leaks into shared runtime.
- `AIQ-SCOPE-CREEP`: Unrelated edits, refactors, formatting churn, or behavior changes are bundled with the requested change.
- `AIQ-CONTRACT-DRIFT`: Schema, API, manifest, CLI, or artifact compatibility changes without migration or tests.
- `AIQ-DUP-KNOWLEDGE`: Rules, markers, prompts, risk terms, or configuration logic are duplicated across files.
- `AIQ-TEST-ILLUSION`: Tests only prove mocks, happy paths, snapshots, or implementation details while core behavior remains untested.
- `AIQ-OBSERVABILITY-GAP`: Missing logs, events, trace artifacts, debug files, or failure summaries make field failures hard to diagnose.

Project and domain risks:

- `MOB-SAFETY-BOUNDARY`: The change touches login, captcha, payment, cart, order, fingerprinting, proxying, or anti-bot evasion boundaries.
- `MOB-NONDET-BUDGET`: Mobilerun, VLM, or LLM fallback lacks budget limits, confidence gates, trace output, or deterministic fallback behavior.
- `MOB-CHANNEL-COUPLING`: Taobao, XHS, or generic mobile runtime logic becomes coupled through shared mutable state or channel-specific assumptions.
- `ASSET-DATA-INTEGRITY`: PostgreSQL, OSS, local SQLite, object files, metadata, hashes, or category-scoped dedupe can diverge.
- `DEPLOY-SECRET-BOUNDARY`: Secrets, SSH credentials, cloud environment files, and local deployment settings are mixed or exposed.

## Severity

- `P0`: Safety boundary violation, data destruction, secret exposure, or production-unusable regression.
- `P1`: Core behavior regression, unstable main workflow, missing tests for high-risk behavior, or broken compatibility.
- `P2`: Architecture drift, duplication, missing observability, or maintainability risk likely to compound.
- `P3`: Naming, documentation, small cleanup, or low-risk consistency issue.

## Report Format

Every finding uses this structure:

- Risk Code
- Severity
- Symptom
- Root Cause
- Consequence
- Fix
- Evidence
- Recommendation

Reports must include no more than 10 high-signal findings, sorted by severity and impact.

## Health Score

The report must include an overall health score from `0-100`.

Suggested scoring:

- Start at `100`.
- Subtract `35` for each P0 finding.
- Subtract `20` for each P1 finding.
- Subtract `10` for each P2 finding.
- Subtract `3` for each P3 finding.
- Subtract up to `10` for missing or unreliable verification evidence.
- Clamp the final score to `0-100`.

The health score is a review aid, not an automatic merge decision in v1.

## Recommendation Policy

Use exactly one conclusion: `block / revise / ready_with_risk / ready`.

- `block`: Any P0, likely data loss, secret exposure, safety boundary violation, or unusable core workflow.
- `revise`: Any unresolved P1 or multiple compounding P2 risks.
- `ready_with_risk`: No P0/P1, but meaningful P2 risks or incomplete verification remain.
- `ready`: No material findings and verification evidence is adequate for the requested scope.

## Operating Rules

- Run ordinary `code_review_and_quality` first when line-level bug and regression review is needed.
- Use this gate as the companion architecture and quality trend review.
- Prefer artifacts over intent.
- Call out missing evidence rather than filling gaps with assumptions.
- Do not request broad context unless the diff crosses an ownership boundary.
- Keep the report actionable: every finding needs a fix path or an explicit acceptance recommendation.
