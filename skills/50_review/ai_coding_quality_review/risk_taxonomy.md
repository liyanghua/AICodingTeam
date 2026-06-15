# AI Coding Quality Risk Taxonomy

## General AI-Coding Risks

| Risk Code | Severity Bias | Meaning | Typical Evidence |
| --- | --- | --- | --- |
| `AIQ-ARCH-DRIFT` | P2 | Architecture or ownership boundaries drift from the project model. | Domain logic inside shared runtime, shared helpers with channel-specific assumptions, new dependencies crossing layers. |
| `AIQ-SCOPE-CREEP` | P2 | Unrelated edits are mixed with the requested change. | Formatting churn, broad refactors, unrelated files staged, behavior changes outside acceptance criteria. |
| `AIQ-CONTRACT-DRIFT` | P1 | Public contracts change without compatibility, migration, or tests. | CLI args, manifest fields, API response shape, schema, env vars, or run artifacts change silently. |
| `AIQ-DUP-KNOWLEDGE` | P2 | Rules or business knowledge are duplicated instead of centralized. | Repeated risk markers, prompt rules, UI markers, env parsing, or schema constants. |
| `AIQ-TEST-ILLUSION` | P1 | Tests appear green but do not prove the risky behavior. | Mock-only tests, happy-path snapshots, no negative cases, tests asserting implementation details. |
| `AIQ-OBSERVABILITY-GAP` | P2 | Failures cannot be diagnosed from emitted artifacts. | Missing step events, no debug screenshots/XML, no trace, missing summary, swallowed exceptions. |

## Project and Domain Risks

| Risk Code | Severity Bias | Meaning | Typical Evidence |
| --- | --- | --- | --- |
| `MOB-SAFETY-BOUNDARY` | P0 | Mobile automation touches forbidden platform boundaries. | Login automation, captcha handling, payment, cart/order flow, fingerprinting, proxying, anti-bot bypass. |
| `MOB-NONDET-BUDGET` | P1 | Mobilerun, VLM, or LLM fallback lacks bounded use. | No call budget, no confidence threshold, no trace, fallback clicks without deterministic gate. |
| `MOB-CHANNEL-COUPLING` | P2 | Channel-specific logic leaks between Taobao, XHS, and shared runtime. | Shared mutable state, Taobao markers inside XHS flow, generic helper assuming one app package. |
| `ASSET-DATA-INTEGRITY` | P1 | Asset metadata and binary objects can diverge. | PG row without OSS object, object without asset row, wrong hash, cross-category dedupe bug, stale scene tags. |
| `DEPLOY-SECRET-BOUNDARY` | P0 | Secrets or deployment configuration boundaries are confused. | Real `.env` committed, SSH password in cloud env, local deploy key exposed, server PG/OSS secrets copied to Mac workbench. |

## Severity Override Rules

- Upgrade to `P0` when a finding can expose secrets, bypass safety boundaries, destroy data, or make production unusable.
- Upgrade to `P1` when the issue affects a core collection, sync, ingest, or deployment workflow.
- Keep as `P2` when the issue is mainly maintainability but likely to compound.
- Use `P3` only for small cleanup that does not affect behavior, safety, or future diagnosis.
