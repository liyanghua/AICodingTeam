# Project Skills

This directory holds the active project-level engineering skills for the Agent Team Runtime.

## Call order

using_agent_skills -> spec_driven_development -> context_engineering -> planning_and_task_breakdown -> incremental_implementation -> test_driven_development -> debugging_and_error_recovery -> code_review_and_quality

## Boundary

- 当前阶段是文档/注册表接入；runtime 暂不自动执行这些 skills。
- This phase is documentation and registry only.
- Skills are long-lived method notes for the project.
- `tasks/current/` still holds per-run artifacts.
- `runs/<run_id>/` still holds runtime evidence.
- The runtime does not auto-execute skills yet.

## Context policy

Skills 不是越多越好。Too many active skills create trigger noise, context tax, rule conflicts, and maintenance debt.

- The active registry keeps only 8 P0 skills.
- P1/P2 skills stay in roadmap notes until there is repeated evidence they are needed.
- Default to one primary skill per phase.
- Use 最多 1 个 companion skill when the next gate requires it.
- Keep `SKILL.md` concise; load templates only for the artifact being written.
- Add a new skill only when it has a repeated failure mode, a clear output, a testable gate, and no overlap with an existing skill.

## Relationship to runtime

- `AGENTS.md` points agents at this registry.
- `README.md` summarizes the same order for humans.
- `skills/registry.yaml` is the machine-readable index for future runtime wiring.
- `run_retrospective` and `historical_task_recall` are listed separately under `memory_skills`; they are not active coding skills.
- Retrospective output may recommend active skills for the next run, but it should not be loaded into coding context unless explicitly selected and cited.
- Historical recall may cite similar run summaries and recommend active skills, but it must stay report-only unless a future audited runtime step explicitly injects it.
