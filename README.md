# growth-dev

Agent Team Runtime plus a benchmark harness for comparing browser automation frameworks on the same XHS-style collection task.

## Current status

The deterministic Agent Team Runtime, domain packs, harness, mock site, scoring, report generator, and task package scaffolding are implemented.
The framework-specific runners are scaffolded as integration points and can be wired once the corresponding packages are installed.

## Quick start

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

Runs are written to `runs/<run_id>/`. Domain packs live under `domains/`; `xhs_browser_benchmark` is the first domain and `web_monitoring` proves the runtime can be reused without changing orchestration code.

## Project Skills

The first project-level production skills live under `skills/` and are indexed by `skills/registry.yaml`. They are the shared method layer for turning a brief into an AI-coding-ready task package, while `tasks/current/` and `runs/<run_id>/` remain the source of truth for each concrete run.

Current call order:

```text
using_agent_skills -> spec_driven_development -> context_engineering -> planning_and_task_breakdown -> incremental_implementation -> test_driven_development -> debugging_and_error_recovery -> code_review_and_quality
```

Skills are not better because there are more of them: the active registry keeps only 8 P0 skills, defaults to one primary skill per phase, and allows at most one companion skill when a gate needs it.

For complex tasks, the runtime now writes a deterministic requirement and planning layer before coding, using coverage-driven slice planning as the Project Skills method. `--planning-mode auto` keeps simple briefs on the deterministic path and prepares a draft-only strong-LLM channel for complex briefs; `--planning-mode llm_assisted` always prepares that draft channel. Official artifacts are promoted only after deterministic gates pass. The intended验收 path is:

```text
brief analysis -> official acceptance criteria -> coverage matrix -> slices -> per-slice trace -> implementation completion gate
```

The source of truth remains `runs/<run_id>/`: `requirements/brief_analysis.json`, `acceptance_criteria.md`, `context_pack.md`, `planning/acceptance_coverage_matrix.*`, `slices/*.yaml`, `codex/slices/*/slice_trace.json`, and `implementation_completion_gate.*`. Codex continuity must come from those run artifacts, current diff, blockers, and verification evidence rather than chat history.

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
