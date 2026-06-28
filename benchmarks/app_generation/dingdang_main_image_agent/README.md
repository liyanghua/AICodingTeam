# Dingdang Main Image Agent Benchmark

## 状态

这是 `PRD -> 本地应用生成` 的第一个 benchmark fixture，用于评估生成系统对复杂产品 PRD 的理解、规划、实现和验证质量。本目录不是功能实现代码入口，也不要求本阶段新增 runner、API 或前端。

## 内容

- `input_prd.md`：用户提供的 Dingdang PRD 原文。
- `acceptance_criteria.md`：从 PRD 抽取的业务验收标准。
- `expected_capabilities.json`：机器可读能力清单。
- `scoring_rubric.json`：AGQS 评分维度与 hard gates。
- `benchmark.yaml`：benchmark manifest。
- `reference_app/`：用户提供的参考应用，用于对照审查，不是唯一标准答案。

## 审核重点

- 是否覆盖四阶段流程、两个阻断点、方案不可混搭、8 张图规划、平台策略、Prompt 分层和局部迭代。
- 是否把参考应用和 v1 默认生成形态区分清楚。
- 是否明确 `.env`、真实 secret、`node_modules/` 不进入 benchmark。
- 是否能支撑后续 AGQS scorer、hard gate checker 和 auto-research 实验 runner。

## 安全说明

`reference_app/.env.example` 和测试文件中的 key 字符串都是占位或测试值。真实 `.env` 已排除，不应把任何真实凭证提交到 benchmark。
