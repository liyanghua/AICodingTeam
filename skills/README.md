# Project Skills

This directory holds the project-level engineering skills that guide the Agent Team Runtime.

## Call order

requirement_grilling -> requirement_to_prd -> repo_context_compiler -> prd_to_task_slices -> tech_spec_to_tdd -> diagnose_failure

## Boundary

- 当前阶段是文档/注册表接入；runtime 暂不自动执行这些 skills。
- This phase is documentation and registry only.
- Skills are long-lived method notes for the project.
- `tasks/current/` still holds per-run artifacts.
- `runs/<run_id>/` still holds runtime evidence.
- The runtime does not auto-execute skills yet.

## Relationship to runtime

- `AGENTS.md` points agents at this registry.
- `README.md` summarizes the same order for humans.
- `skills/registry.yaml` is the machine-readable index for future runtime wiring.
