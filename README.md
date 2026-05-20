# growth-dev

Agent Team Runtime plus a benchmark harness for comparing browser automation frameworks on the same XHS-style collection task.

## Current status

The deterministic Agent Team Runtime, domain packs, harness, mock site, scoring, report generator, and task package scaffolding are implemented.
The framework-specific runners are scaffolded as integration points and can be wired once the corresponding packages are installed.

## Quick start

```bash
python -m growth_dev team init --domain xhs_browser_benchmark
python -m growth_dev team run --brief "对比 5 个浏览器自动化框架完成小红书采集任务"
python -m growth_dev team status --run-id <run-id>
python -m growth_dev team report --run-id <run-id>

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

## Safety

Manual login only. No captcha bypass, fingerprint spoofing, proxy rotation, or anti-bot evasion.
