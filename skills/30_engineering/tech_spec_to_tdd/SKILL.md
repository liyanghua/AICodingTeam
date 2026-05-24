---
name: tech_spec_to_tdd
description: Convert a technical spec into behavior tests, integration coverage, and UI-state checks.
---

# Tech Spec to TDD

## Purpose
Turn the technical design into behavior-first tests, integration checks, and UI state review criteria before code is written.

## When To Use
- A tech spec exists.
- The implementation will change behavior.
- Tests must lead the implementation.
- A slice is about to enter AI coding and needs explicit verification commands.

## Inputs
- `tasks/current/tech_spec.md`
- `tasks/current/ui_spec.md`
- `tasks/current/prd.md`
- Data model, schema, or domain contract.
- `DESIGN.md`, for UI-facing work.

## Outputs
- `tasks/current/eval.md`
- `tasks/current/tdd_cases.md`
- `tasks/current/review_checklist.md`

## Steps
1. Convert acceptance criteria into observable behavior tests.
2. Define the first red test for each vertical slice before implementation.
3. Cover success, empty, error, loading, permission, and regression states where relevant.
4. Separate unit, integration, dashboard/API, and artifact contract checks.
5. Prefer public interfaces and stable artifacts over implementation internals.
6. Write verification commands that can be run by the verifier stage.

## Quality Gate
- Tests describe behavior, not internals.
- UI state coverage is present.
- Regression coverage is explicit.
- Every high-risk acceptance criterion has a concrete test or review checklist item.
