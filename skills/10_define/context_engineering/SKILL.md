---
name: context_engineering
description: Use when an agent needs bounded task context, repo impact analysis, memory excerpts, or artifact selection before planning, coding, review, or debugging.
---

# Skill: context_engineering

## Purpose
Build the smallest sufficient context pack for the next agent stage.

## When To Use
- The task touches unfamiliar code.
- Prior attempts failed because context was missing or noisy.
- Obsidian memory or run history might help but must be cited.

## Inputs
- PRD or brief.
- Repo structure and relevant files.
- Domain pack and run artifacts.
- Optional: `context_pack_template.md`, `context_selection_matrix.md`.

## Outputs
- `tasks/current/context.md` updates.
- `tasks/current/context_pack.md`.
- `tasks/current/impact_analysis.md`.

## Steps
1. Identify the next consumer: planner, coder, reviewer, or debugger.
2. Select only files and artifacts needed by that consumer.
3. Summarize constraints, interfaces, and nearby ownership boundaries.
4. Cite any run memory or historical notes by path.
5. Exclude irrelevant logs, diffs, and stale decisions.

## Quality Gate
- Relevant modules and allowed paths are named.
- Excluded context is explained when it was tempting to include.
- Historical context has a source path.
- The pack is small enough to read before work starts.

## Context Hygiene
- Do not paste whole files when a path and short summary are enough.
- Do not mix memory, raw logs, and full diffs unless debugging.
- Prefer current repo truth over historical notes when they disagree.
