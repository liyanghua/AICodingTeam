---
name: historical_task_recall
description: Recall similar historical runs from learning_summary.json and recommend active Project Skills without injecting memory into coding prompts.
---

# Skill: historical_task_recall

## Purpose
基于本地 `runs/*/learning_summary.json` 召回相似历史任务，给出可审计的上下文复用建议和 Project Skills 推荐。

## When To Use
- 新 run 启动时需要生成 `memory_recall.md/json`。
- 用户询问“历史上有没有类似任务”。
- 用户想知道本次任务应优先使用哪些 active Project Skills。

## Inputs
- 当前 brief 或 search query。
- 可选 `domain_id` 和 `task_type`。
- `runs/*/learning_summary.json`。
- `skills/registry.yaml` 中 active skill id。

## Outputs
- `runs/<run_id>/memory_recall.md`。
- `runs/<run_id>/memory_recall.json`。
- 相似 run 列表、推荐 skills、可复用上下文、应避免上下文、下次 checklist。

## Steps
1. 只扫描 summary artifacts，不读取 raw logs、full diff、raw prompt 或 Obsidian vault。
2. 用 query/domain/task_type 与历史 summary 做确定性加权匹配。
3. 聚合历史 run 的 `recommended_skills`，并过滤到 active registry ids。
4. 输出每个推荐的来源 run id、原因和置信度。
5. 明确上下文策略：reuse、avoid、checklist。

## Quality Gate
- 每个匹配结果必须引用 `run_id` 和 summary artifact。
- 推荐 skill 必须存在于 active registry。
- 输出不得包含 secret、`.env` 内容、raw stdout/stderr、完整 diff 或 raw prompt。
- 召回结果只能作为建议，不改变 gate 或执行器行为。

## Context Hygiene
默认不把历史任务全文注入 coding prompt。只传递被引用的 run id、摘要、上下文路径和排除列表；如需人工查看，跳转到 `memory_recall.md` 或 Obsidian run note。
