# AI Coding Quality Review Examples

## Mobile Collector Safety Boundary

- Risk Code: `MOB-SAFETY-BOUNDARY`
- Severity: `P0`
- Symptom: A collector helper retries through a login or captcha page instead of stopping.
- Root Cause: Risk markers are checked only on the initial page, not after fallback actions.
- Consequence: The automation may appear to bypass platform safety boundaries.
- Fix: Add risk marker checks before every fallback click and stop the current item with a risk event.
- Evidence: `third_party/taobao_collector/...` changed fallback flow without a matching negative test.
- Recommendation: `block`

## Mobilerun Runtime Budget

- Risk Code: `MOB-NONDET-BUDGET`
- Severity: `P1`
- Symptom: Mobilerun target recognition is called inside a loop without per-item or per-stage limits.
- Root Cause: The runtime treats nondeterministic recognition as a normal retry mechanism.
- Consequence: Cost and latency can spike, and repeated uncertain clicks become hard to audit.
- Fix: Add per-item budget, confidence threshold, structured trace, and budget-exhausted event.
- Evidence: Eval command emits recognition events but no `budget_remaining` field.
- Recommendation: `revise`

## Asset Center PG/OSS Integrity

- Risk Code: `ASSET-DATA-INTEGRITY`
- Severity: `P1`
- Symptom: Ingest writes PostgreSQL rows before object upload success is confirmed.
- Root Cause: Metadata and binary storage are not treated as a single recoverable operation.
- Consequence: Frontend lists assets whose preview/download object is missing.
- Fix: Upload object first or mark asset unavailable until both metadata and object write succeed; add repair or retry event.
- Evidence: `assets` row exists while OSS object is absent in ingest test fixture.
- Recommendation: `revise`

## Deployment Secret Boundary

- Risk Code: `DEPLOY-SECRET-BOUNDARY`
- Severity: `P0`
- Symptom: Mac mini deployment config reads PG/OSS credentials from the cloud asset center env file.
- Root Cause: Local workbench deployment and cloud service runtime configuration share one env boundary.
- Consequence: Server secrets can be copied to local machines or exposed in task logs.
- Fix: Keep `.env.asset.cloud` server-only; use a separate `.env.remote` for SSH deployment and redact all task logs.
- Evidence: Deployment script references `ASSET_CENTER_DB_DSN` while building remote Mac commands.
- Recommendation: `block`
