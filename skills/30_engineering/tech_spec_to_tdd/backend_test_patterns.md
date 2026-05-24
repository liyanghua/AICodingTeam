# Backend Test Patterns

Use backend tests to prove public behavior and artifact contracts.

## Runtime / CLI

- Invoke CLI entrypoints when behavior is user-facing.
- Assert exit status, user-visible output, and generated artifact paths.
- Use deterministic fixtures; do not depend on network, real login, or real provider calls.

## Domain Pack

- Load `domains/<domain_id>/domain.yaml`.
- Validate required output fields and evaluation rules.
- Confirm backward compatibility for existing fields.

## Gates And Records

- Verify gate pass/fail decisions through run records.
- Assert failure categories and risk events are explicit.
- Confirm secrets are not serialized into artifacts.

## Test Shape

- One behavior per test.
- Prefer `unittest` and standard library helpers already used in this repo.
- Name tests as observable outcomes, not implementation internals.
