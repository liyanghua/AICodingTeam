# Project Skills

This directory holds the active project-level engineering skills for the Agent Team Runtime.

## Call order

using_agent_skills -> spec_driven_development -> context_engineering -> planning_and_task_breakdown -> incremental_implementation -> test_driven_development -> debugging_and_error_recovery -> code_review_and_quality

Review companion order:

code_review_and_quality -> ai_coding_quality_review

## Boundary

- 当前阶段是文档/注册表接入；runtime 暂不自动执行这些 skills。
- This phase is documentation and registry only.
- Skills are long-lived method notes for the project.
- `tasks/current/` still holds per-run artifacts.
- `runs/<run_id>/` still holds runtime evidence.
- The runtime does not auto-execute skills yet.

## Context policy

Skills 不是越多越好。Too many active skills create trigger noise, context tax, rule conflicts, and maintenance debt.

- The active registry keeps 8 P0 skills plus the P1 `ai_coding_quality_review` companion.
- Other P1/P2 skills stay in roadmap notes until there is repeated evidence they are needed.
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

## Complex task planning

复杂任务默认使用 coverage-driven slice planning：先建立 acceptance coverage matrix，再生成 `slices/*.yaml`。每个 slice 必须覆盖至少一个 acceptance criterion，每条 acceptance criterion 也必须被至少一个 slice 覆盖。

Codex slice-loop 默认一次只执行一个 slice。连续性来自 run artifacts、slice yaml、coverage matrix、per-slice trace、current diff 和 verification evidence，而不是聊天历史。

整体完成判断以 implementation completion gate 为准：所有 slice 完成、验收标准被覆盖、测试通过、无开放 blocker、无无关变更，并且最终报告说明覆盖关系。

## PM Skills-inspired templates

PM Skills 方法只作为 candidate understanding 素材挂在现有 P0 skills 下，不新增 active skill、不改变 call order。`spec_driven_development` 可使用 PM-style PRD、user stories 和 PRD red-team 模板生成 draft；`test_driven_development` 可使用 PM test scenarios 模板把 AC 映射为 happy path、edge case、error state、regression 和 manual validation。

这些 draft 只帮助强 LLM 理解需求。正式 PRD、AC、TDD plan 和 slices 仍必须通过 deterministic gate，并以 `runs/<run_id>/` run artifacts 作为事实来源。
