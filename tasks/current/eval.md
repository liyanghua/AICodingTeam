# Eval

## Schema

- Validate every `XhsNote` payload against the shared schema.
- Keep adapter results JSON-serializable and reproducible.

## Tests

- parse `1.2万`, `999+`, `3k`
- generate deterministic fixtures
- validate missing schema fields
- compute completeness and summary tables
- render markdown and SVG report artifacts

## Risk Review

- Manual login only.
- No captcha bypass, fingerprint spoofing, proxy rotation, private API reverse engineering, or anti-bot evasion.
- Risk events must be explicit in adapter and team reports.