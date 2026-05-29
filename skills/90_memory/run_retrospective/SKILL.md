---
name: run_retrospective
description: Use when a run has reached a terminal state and project memory needs a concise, auditable learning summary.
---

# Skill: run_retrospective

## Purpose
Turn a finished or failed run into reusable project learning without polluting future coding context.

## When To Use
- A run is completed, failed, or manually exported to memory.
- Obsidian notes need project evolution context.
- A future task needs cited prior learning.

## Inputs
- `team_run_record.json`.
- `events.jsonl`.
- `review_report.md`, `test_report.md`, `final_report.md`.
- `codex/implementation_trace.json` when present.
- `acceptance/status.json` when present.

## Outputs
- `retrospective.md`.
- `learning_summary.json`.
- Recommended active Project Skills.

## Steps
1. Classify the task type and outcome.
2. Summarize quality, implementation, review, test, and acceptance evidence.
3. Name failure modes and reusable context.
4. Name context to avoid next time.
5. Recommend only active registry skill ids.

## Quality Gate
- No raw logs, full diff, raw prompt, `.env`, or provider secrets are copied.
- Recommendations cite current active skills.
- Running runs are marked as incomplete observations.
- The summary is short enough for Obsidian review.

## Context Hygiene
- Prefer artifact paths and concise summaries over copied content.
- Do not inject this memory into Codex prompts automatically.
- Treat current repo truth as newer than historical notes.
