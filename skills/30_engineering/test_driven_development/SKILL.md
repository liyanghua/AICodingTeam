---
name: test_driven_development
description: Use when new behavior, bug fixes, or acceptance criteria need executable tests before or alongside implementation.
---

# Skill: test_driven_development

## Purpose
Convert acceptance criteria into behavior-focused tests and keep implementation honest with red-green-refactor discipline.

## When To Use
- New behavior needs implementation.
- A bug fix needs regression coverage.
- UI, API, or CLI states need executable verification.

## Inputs
- Acceptance criteria.
- Tech or UI spec.
- Existing nearby tests.
- Optional: `tdd_cases_template.md`, `eval_template.md`, `pm_test_scenarios_template.md`.

## Outputs
- `tasks/current/tdd_cases.md`.
- `tasks/current/eval.md`.
- Verification commands.

## Steps
1. Identify public behavior to test.
2. Write the smallest failing test or test case.
3. Verify the failure mode is meaningful.
4. Implement the minimal change.
5. Run the test and relevant regression suite.
6. For product-shaped requirements, map acceptance criteria to happy path, edge case, error state, regression, and manual validation scenarios.

## Quality Gate
- Tests assert behavior, not private implementation.
- Red failure is observed or explicitly simulated in planning artifacts.
- UI states cover loading, empty, error, and success when applicable.
- Verification command is reproducible.
- Each PM test scenario maps to at least one acceptance criterion.
- New behavior has at least one red-first scenario before implementation.

## Context Hygiene
- Read nearby test patterns before inventing new ones.
- Do not load every test file in the repo.
- Keep test cases tied to acceptance criteria.
