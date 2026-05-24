---
name: requirement_grilling
description: Clarify an incoming business brief into a precise context pack before PRD generation.
---

# Requirement Grilling

## Purpose
Turn a fuzzy business brief into a shared context pack before the runtime generates PRD, tech spec, UI spec, or code prompts. This skill prevents AI coding from guessing business intent.

## When To Use
- A new business brief arrives.
- Terms or scope are ambiguous.
- PRD generation would otherwise guess.
- The dashboard or CLI has a brief, but `tasks/current/context.md` is missing or stale.

## Inputs
- Raw business brief from the user.
- Existing `tasks/current/context.md`, if present.
- `AGENTS.md` for project constraints.
- `DESIGN.md`, when the request touches Dashboard or UI behavior.
- Domain pack notes from `domains/<domain_id>/`, when relevant.

## Outputs
- `tasks/current/context.md`
- Optional ADR draft when a decision changes architecture or product policy.
- A short list of open questions that must be answered before implementation, or explicitly parked.

## Steps
1. Extract the user outcome, target user, workflow boundary, data objects, UI states, and acceptance signal.
2. Ask only questions that change implementation, testing, or scope.
3. Normalize project terms so later agents use one vocabulary.
4. Separate in-scope, out-of-scope, assumptions, risks, and open decisions.
5. Write or update `tasks/current/context.md` using `context_format.md`.
6. If the answer creates a durable product or architecture decision, draft an ADR using `adr_format.md`.

## Quality Gate
- Key terms have one agreed meaning.
- Scope and out-of-scope are explicit.
- Open questions are either answered or parked.
- The next skill can generate PRD without inventing goals, users, or acceptance criteria.
