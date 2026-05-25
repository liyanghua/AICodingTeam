---
name: spec_driven_development
description: Use when a new feature, domain pack, or material behavior change needs a business-readable spec, scope boundary, or acceptance criteria before coding.
---

# Skill: spec_driven_development

## Purpose
Turn a business brief into an AI-coding-ready spec with explicit scope and testable acceptance criteria.

## When To Use
- A user asks for a new capability or significant change.
- PRD, scope, users, or acceptance criteria are missing.
- A coding agent would otherwise need to guess intent.

## Inputs
- Business brief.
- Existing `tasks/current/context.md` when present.
- `AGENTS.md`; `DESIGN.md` for UI work.
- Optional: `spec_template.md`, `acceptance_criteria_template.md`.

## Outputs
- `tasks/current/prd.md`.
- `tasks/current/acceptance_criteria.md`.
- Open questions and out-of-scope boundaries.

## Steps
1. Restate the business goal and intended users.
2. Define in-scope and out-of-scope behavior.
3. Describe the core workflow and expected states.
4. Name data objects, external dependencies, and safety constraints.
5. Write acceptance criteria that QA can turn into tests.

## Quality Gate
- The goal is measurable.
- User roles and core workflow are explicit.
- Scope boundaries prevent unrelated refactors.
- Acceptance criteria are observable from public behavior.

## Context Hygiene
- Do not inspect broad source files unless needed to define feasibility.
- Do not include implementation details that belong in tech spec.
- Capture open questions instead of filling gaps with assumptions.
