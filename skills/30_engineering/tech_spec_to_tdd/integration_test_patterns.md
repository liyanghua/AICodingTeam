# Integration Test Patterns

Use integration tests to prove the pipeline holds together across generated artifacts.

## Runtime Flow

- Start from a realistic brief or fixture run.
- Exercise orchestrator/product/architect/ux/qa/coder/reviewer/verifier/publisher where possible.
- Confirm `team_run_record.json`, `events.jsonl`, reports, and codex artifacts agree.

## Dashboard/API Flow

- Use fixture runs for completed, running, and failed states.
- Verify serializers do not leak `.env` values or provider keys.
- Verify business view state and engineering detail state are both available.

## Failure Flow

- Simulate failed provider, failed review, failed test, and permission errors.
- Assert `failure_category`, risk events, and next actions are visible.
