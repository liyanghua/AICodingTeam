# AGENTS.md

## Product Goal

This repository is an AI-native Agent Team Runtime with an XHS-style browser automation benchmark as its first domain pack.
It turns a single business brief into gated engineering artifacts, then compares browser frameworks against the same task, same schema, and same safety gates.

## Architecture Principles

- Manual login only. Do not automate credential collection, captcha bypass, fingerprint spoofing, proxy rotation, or anti-bot evasion.
- Keep all outputs structured and reproducible.
- Preserve backward-compatible APIs and task schemas.
- Store run artifacts in `runs/` and task specs in `tasks/current/`.
- Keep the team runtime domain-agnostic. New tasks should add `domains/<domain_id>/` packs instead of rewriting orchestration code.
- Treat agents as fixed input/output workers, not free-form chat participants.
- Keep adapters isolated. Each framework gets its own runner and does not share mutable browser state.

## File Ownership

- Task package: `tasks/current/`
- Domain packs: `domains/`
- Team runtime: `growth_dev/team/`
- Core harness: `growth_dev/`
- Mock site: `growth_dev/mock_site.py`
- Scoring and reporting: `growth_dev/scoring.py`, `growth_dev/reporting.py`
- Framework adapters: `growth_dev/adapters/`

## Coding Rules

- Prefer the standard library unless a dependency is already present.
- Keep modules focused and small.
- Use deterministic fixture generation for tests.
- Keep v1 team agents deterministic and file-driven.
- Do not add unrelated refactors.

## Testing Rules

- Unit tests must cover count parsing, fixture generation, schema validation, and scoring.
- Integration tests must cover the mock site and report generation.
- Team runtime tests must cover team/domain parsing, gates, run record serialization, CLI entrypoints, and domain reuse.
- If a real framework package is missing, the adapter must fail clearly and mark itself unavailable.

## Review Rules

- Check that safety boundaries remain intact.
- Check that run outputs preserve the shared schema.
- Check that risk events are explicit and never hidden.

## Deployment Rules

- Do not attempt real-world scraping beyond the approved low-frequency, manual-login benchmark flow.
- Do not add production automation until the benchmark harness is proven locally.

## Do Not

- Do not bypass platform security.
- Do not hardcode private API usage.
- Do not create hidden background scrapers.
- Do not mutate unrelated files.
