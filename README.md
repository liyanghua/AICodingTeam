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
python -m growth_dev team diff --run-id <run-id>
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
- `growth-dev team status --summary` shows the current/last agent, recent Codex stdout/stderr lines, risk events, and diff size.
- `growth-dev team diff` prints the isolated worktree diff.
- `growth-dev review`, `growth-dev test`, and `growth-dev report` print the stage artifacts without needing to inspect files manually.
- `growth-dev team apply` only applies the worktree diff when the run is `completed`, no risk events are present, and the verifier stage completed.

Project-level third-party provider config is read from `.env` only for the child Codex process. The key is injected as `AICODEMIRROR_KEY` and is not written to run artifacts.

## Safety

Manual login only. No captcha bypass, fingerprint spoofing, proxy rotation, or anti-bot evasion.
