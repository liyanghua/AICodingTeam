# growth-dev

AI-native Agent Team Runtime for turning business context into gated engineering artifacts, controlled Code Agent runs, review evidence, verification records, and human-confirmed delivery.

The current primary domain is `app_generation`: PRD / business-spec-to-local-app generation for producing runnable, reviewable, and iterated business applications. XHS/browser automation remains a reusable domain pack and historical benchmark, not the whole-project identity.

For the full project map, read [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md).

## Current status

Implemented foundations include the deterministic Agent Team Runtime, domain packs, Codex executor integration, Project Skills method layer, app-generation domain, observable Dashboard/workbench, preview and repair infrastructure, benchmark harness, scoring, report generation, and task package scaffolding.

The intended business compiler chain is:

```text
Business strategy documents
-> document-to-skill compiler
-> Strategy IR / Skill Spec / Workflow DAG / Data Requirement / Tool Binding / Evidence / Eval
-> app_generation Business PRD++ / AppSpec / DataSpec / KnowledgeSpec / ToolSpec / EvalSpec
-> controlled Code Agent generation
-> local app preview / review / verification / repair
```

## Quick start

### Business document to Skill

```bash
cd document-to-skill-engineering-package
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
python -m doc_to_skill.cli compile \
  --input examples/source_docs/20260519市场分析洞察元策略.md \
  --output build/market_insight_skill
pytest -q
```

### PRD / business spec to local app

```bash
python -m growth_dev app generate \
  --foreground \
  --executor codex \
  --prd-text "Todo App：用户可以新增、完成、筛选待办，状态保存在浏览器本地。" \
  --app-slug todo-prototype
```

### Agent Team Runtime

```bash
python -m growth_dev team init --domain xhs_browser_benchmark
python -m growth_dev team run --brief "对比 5 个浏览器自动化框架完成小红书采集任务"
python -m growth_dev team run \
  --executor codex \
  --model gpt-5.3-codex \
  --reasoning-effort medium \
  --brief "实现一个新的 domain pack"
python -m growth_dev team status --run-id <run-id>
python -m growth_dev team report --run-id <run-id>

python -m growth_dev code \
  --domain web_monitoring \
  --executor codex \
  --codex-provider aicodemirror \
  --env-file .env \
  --codex-binary /opt/homebrew/bin/codex \
  --model gpt-5.5 \
  --brief "给 web_monitoring domain 增加截图证据字段，并补充对应测试"
python -m growth_dev team status --run-id <run-id> --summary
python -m growth_dev team watch --run-id <run-id>
python -m growth_dev team diff --run-id <run-id>
python -m growth_dev team retrospective generate --run-id <run-id>
python -m growth_dev team memory export --run-id <run-id> --vault-dir /path/to/ObsidianVault
python -m growth_dev review --run-id <run-id>
python -m growth_dev test --run-id <run-id>
python -m growth_dev report --run-id <run-id>
```

### XHS / browser benchmark

```bash
python -m growth_dev xhs init
python -m growth_dev xhs serve-mock --port 8787
python -m growth_dev xhs benchmark --suite mock
python -m growth_dev xhs report --run-id <run-id>
```

## Agent Team Runtime

The `team` command turns a single brief into a gated artifact pipeline:

- `orchestrator`: `task.yaml`, `context.md`
- `product`: `prd.md`
- `architect`: `tech_spec.md`
- `ux`: `ui_spec.md`
- `qa`: `eval.md`
- `coder`: `coding_prompt.md`, `code_run_record.json`
- `reviewer`: `review_report.md`
- `verifier`: `test_report.md`
- `publisher`: `final_report.md`

Runs are written to `runs/<run_id>/`. Domain packs live under `domains/`; `xhs_browser_benchmark` is the historical first domain and `web_monitoring` proves the runtime can be reused without changing orchestration code.

`app_generation` is the current P0 domain for product work. The XHS browser benchmark remains a reusable domain pack and benchmark proving the runtime's domain-agnostic shape.

## Document-to-Skill compiler

The `document-to-skill-engineering-package/` package compiles business strategy documents into Agent Runtime assets:

- `Strategy IR`
- `Skill Spec`
- `Workflow DAG`
- `Data Requirement`
- `Tool Binding`
- `Evidence Pack`
- `Eval`

These assets are upstream context for richer `app_generation` flows. They can map into Business PRD++ / AppSpec / DataSpec / KnowledgeSpec / ToolSpec / EvalSpec, but this repository does not currently move the package into `domains/`.

## Project Skills

The first project-level production skills live under `skills/` and are indexed by `skills/registry.yaml`. They are the shared method layer for turning a brief into an AI-coding-ready task package, while `tasks/current/` and `runs/<run_id>/` remain the source of truth for each concrete run.

Current call order:

```text
using_agent_skills -> spec_driven_development -> context_engineering -> planning_and_task_breakdown -> incremental_implementation -> test_driven_development -> debugging_and_error_recovery -> code_review_and_quality
```

Skills are not better because there are more of them: the active registry keeps 8 P0 skills plus one P1 review companion, defaults to one primary skill per phase, and allows at most one companion skill when a gate needs it.

For AI-coding quality trend review, `ai_coding_quality_review` is registered as a P1 companion after `code_review_and_quality`. It produces a report-only health score and fixed-risk-model findings for architecture drift, contract drift, safety boundaries, asset data integrity, and deployment-secret boundaries.

For product-shaped requirements, the define and TDD skills now include PM Skills-inspired templates for PM-style PRD drafts, user stories, PRD red-team checks, and test scenarios. These templates only feed candidate understanding for strong LLM planning; official artifacts still require deterministic gates and are sourced from `runs/<run_id>/`.

The requirements-model integration contract is documented in `docs/requirements_model_candidate_understanding_spec.md`: the model may propose candidate understanding, but deterministic gates decide what becomes official.
Use `--requirements-model <model>` with `--planning-mode llm_assisted|auto` to enable candidate understanding. Provider settings may come from `--requirements-env-file`, or from `--env-file` when omitted; v1 accepts `REQUIREMENTS_MODEL_BASE_URL` / `REQUIREMENTS_MODEL_API_KEY` and can also reuse `AICODEMIRROR_BASE_URL` / `AICODEMIRROR_KEY`. The recorded request/response artifacts are sanitized summaries, not raw prompts or secrets.

For complex tasks, the runtime now writes a deterministic requirement and planning layer before coding, using coverage-driven slice planning as the Project Skills method. `--planning-mode auto` keeps simple briefs on the deterministic path and prepares a draft-only strong-LLM channel for complex briefs; `--planning-mode llm_assisted` always prepares that draft channel. Official artifacts are promoted only after deterministic gates pass. The intended验收 path is:

```text
brief analysis -> PM-style draft understanding -> official acceptance criteria -> coverage matrix -> slices -> per-slice trace -> implementation completion gate
```

The source of truth remains `runs/<run_id>/`: `requirements/brief_analysis.json`, `acceptance_criteria.md`, `context_pack.md`, `planning/acceptance_coverage_matrix.*`, `slices/*.yaml`, `codex/slices/*/slice_trace.json`, and `implementation_completion_gate.*`. Codex continuity must come from those run artifacts, current diff, blockers, and verification evidence rather than chat history.

### PRD-to-local-app generation

The `app_generation` domain turns a PRD into a lightweight local prototype app for product validation. v1 generates a native SPA plus a Node stdlib local server, with no database and browser `localStorage` as the only persistence layer. Generated code remains in an isolated Codex worktree until the existing review, verification, and human-confirmed apply gates pass.

Foreground example:

```bash
python -m growth_dev app generate \
  --foreground \
  --executor codex \
  --prd-text "Todo App：用户可以新增、完成、筛选待办，状态保存在浏览器本地。" \
  --app-slug todo-prototype
```

The Dashboard also includes a “PRD 生成本地应用” request mode that submits `domain=app_generation` with `prd_text` and `app_slug`.

Design and implementation docs:

- `docs/app_generation_prd_to_local_app_spec.md`
- `docs/app_generation_architecture.md`
- `docs/app_generation_acceptance_and_testing.md`
- `docs/app_generation_implementation_task_plan.md`

## Codex executor

`team run` defaults to the deterministic file-based agents. Add `--executor codex` to let the `coder` stage run `codex exec`, the `reviewer` stage run `codex review --uncommitted`, and the `verifier` stage run deterministic verification commands in the isolated worktree.

The Codex executor writes replayable context into `runs/<run_id>/codex/`:

- `codex_prompt.md`: compact machine prompt for `codex exec`
- `state_summary.md`: run state, allowed paths, verification commands, risk rules, and previous attempt summary
- `codex_response_schema.json`: required final JSON schema
- `last_message.json`: schema-constrained Codex final response
- `diff.patch` and `git_status.txt`: implementation evidence from the worktree
- `reviewer_stdout.log` and `verification_record.json`: review and verification evidence

Use `--inputs-json` to narrow scope and verification:

```bash
python -m growth_dev team run \
  --executor codex \
  --brief "给 web_monitoring 增加截图证据" \
  --inputs-json '{"allowed_paths":["growth_dev/","tests/"],"verification_commands":["python3 -m unittest discover -s tests -v"]}'
```

### Week 2 coding loop

The Week 2 loop is intentionally observable before it is automatically merged:

- `growth-dev code` is a Codex-first alias for `team run --executor codex`.
- `growth-dev code` starts in the background by default and immediately prints the run id, pid, watch command, and artifacts directory. Add `--foreground` when you want the old synchronous behavior.
- `growth-dev team watch` follows the run record, events, gates, recent logs, diff summary, and next actions.
- `growth-dev team status --summary` shows the current/last agent, recent Codex stdout/stderr lines, risk events, and diff size.
- `growth-dev team diff` prints the isolated worktree diff.
- `growth-dev review`, `growth-dev test`, and `growth-dev report` print the stage artifacts without needing to inspect files manually.
- `growth-dev team apply` only applies the worktree diff when the run is `completed`, no risk events are present, and the verifier stage completed.

Project-level third-party provider config is read from `.env` only for the child Codex process. The key is injected as `AICODEMIRROR_KEY` and is not written to run artifacts.

Every team run also writes `events.jsonl` as a stage timeline and `process.json` for background process metadata.

### Run retrospective

Terminal team runs now write deterministic learning artifacts after completion or failure:

- `retrospective.md`: business-friendly run review and next-time guidance.
- `learning_summary.json`: structured outcome, failure modes, recommended Project Skills, reusable context, and context to avoid.

You can regenerate them for historical runs:

```bash
python -m growth_dev.cli team retrospective generate --run-id <run-id>
python -m growth_dev.cli team retrospective generate --all --limit 50
```

Retrospectives are observability and memory artifacts only. They do not change gate results or inject memory into future Codex prompts.

### Historical task recall

The lightweight recall layer searches local `runs/*/learning_summary.json` files and recommends similar historical runs, reusable context, context to avoid, and active Project Skills. It is deterministic and report-only: results are written to `memory_recall.md` / `memory_recall.json` for new runs and are not injected into Codex prompts.

```bash
python -m growth_dev.cli team memory search \
  --query "Dashboard 交付验收状态" \
  --limit 5

python -m growth_dev.cli team memory search \
  --query "Dashboard 交付验收状态" \
  --domain-id web_monitoring \
  --json
```

Use `--refresh-missing` only when you explicitly want to generate missing retrospective summaries for historical runs. Recall output excludes raw logs, full diffs, raw prompts, `.env`, and provider secrets.

### Release readiness and PR draft

After a run has been accepted and full local tests pass, generate a local release readiness report:

```bash
python -m growth_dev.cli team release readiness --run-id <run-id>
python -m growth_dev.cli team release readiness --run-id <run-id> --json
```

This writes `release_readiness.json`, `release_readiness.md`, and `pr_draft.md` under `runs/<run_id>/`. The decision is one of `ready_for_pr_ci`, `ready_with_warnings`, or `blocked`, based on acceptance status, Review/Test reports, risk/blocker state, changed-file evidence, and current git status.

When readiness is not blocked, you can explicitly push the current branch, create a GitHub Draft PR, and refresh CI check status:

```bash
python -m growth_dev.cli team pr draft --run-id <run-id> --base main --push
python -m growth_dev.cli team pr status --run-id <run-id>
python -m growth_dev.cli team pr status --run-id <run-id> --json
```

This writes `github_pr.json`, `github_pr.md`, `ci_status.json`, and `ci_status.md`. It uses the GitHub CLI (`gh`) and never merges, deploys, or auto-fixes CI. If `gh` is missing, not authenticated, or the repo/branch is not ready, the failure is recorded as a run artifact.

The repository includes a minimal GitHub Actions workflow at `.github/workflows/ci.yml`. It runs the full local unittest command on PRs and pushes to `main`, so Dashboard PR/CI checks come from the same verification path used by local acceptance.

After PR/CI status is available, generate the local staging readiness judgment:

```bash
python -m growth_dev.cli team release staging-readiness --run-id <run-id>
python -m growth_dev.cli team release staging-readiness --run-id <run-id> --json
```

This writes `staging_readiness.json` and `staging_readiness.md`. The decision is one of `ready_for_staging`, `waiting_for_ci`, or `blocked`. Staging readiness requires accepted local changes, non-blocked release readiness, a created Draft PR, passed CI checks, and no uncleared risks. This layer only creates an auditable judgment; it does not deploy, merge, or auto-fix CI.

When staging readiness is `ready_for_staging`, run the local staging rehearsal before any real deploy decision:

```bash
python -m growth_dev.cli team release staging-rehearsal --run-id <run-id>
python -m growth_dev.cli team release staging-rehearsal --run-id <run-id> --json
```

This writes `staging_rehearsal.json`, `staging_rehearsal.md`, and test logs under `runs/<run_id>/staging_rehearsal/`. It rechecks staging readiness, records git status, reruns `python3 -m unittest discover -s tests -v`, and summarizes blockers, warnings, and next actions. It still does not merge, deploy, push, or mutate any remote environment.

### Obsidian project memory

The first memory layer is a manual Markdown export for Obsidian. It reads existing `runs/<run_id>/` artifacts and writes business-friendly project evolution notes into the selected vault without changing runtime behavior or injecting memory into future Codex prompts.

```bash
python -m growth_dev.cli team memory export \
  --run-id <run-id> \
  --vault-dir /path/to/ObsidianVault

python -m growth_dev.cli team memory export \
  --all \
  --limit 50 \
  --vault-dir /path/to/ObsidianVault
```

Exported notes live under `AI Coding Memory/` with `Index.md`, monthly timeline notes, domain notes, and one run note per exported run. Notes include summaries, historical recall, release readiness, GitHub PR / CI status, retrospectives, recommended skills, gates, changed files, risks, and local artifact links; raw logs, full diffs, `.env`, and provider secrets are not copied into the vault.

### Local dashboard

The browser UI lives in the top-level `dashboard/` directory, separate from the Python runtime. The backend only serves static assets and the local run API.

```bash
python -m growth_dev.cli team serve-dashboard \
  --host 127.0.0.1 \
  --port 8790 \
  --codex-provider aicodemirror \
  --env-file .env \
  --codex-binary /opt/homebrew/bin/codex \
  --model gpt-5.5 \
  --open-browser
```

Open `http://127.0.0.1:8790`, enter a brief, and the page will show the Agent stages, artifacts, gates, logs, diff summary, and next actions. When a completed run passes the apply gate, the dashboard can trigger a human-confirmed acceptance flow: it applies the run with `python3 -m growth_dev.cli team apply --run-id <run-id>` and then runs `python3 -m unittest discover -s tests -v`, with progress and log tails written under `runs/<run_id>/acceptance/`. After acceptance passes, the dashboard can generate the local release readiness report and PR draft, then explicitly trigger “推送当前分支并创建 Draft PR” and refresh PR/CI status. The CLI `growth-dev team apply` path remains available for manual operation.

## Safety

Manual login only. No captcha bypass, fingerprint spoofing, proxy rotation, or anti-bot evasion.
