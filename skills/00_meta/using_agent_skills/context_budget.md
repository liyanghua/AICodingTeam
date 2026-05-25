# Context Budget

- Registry metadata is cheap; full `SKILL.md` files are not.
- Load the selected primary `SKILL.md`.
- Load a companion `SKILL.md` only when its output is required by the next gate.
- Load templates only when writing that exact artifact.
- Never load raw logs, full diffs, and historical memory notes together unless diagnosing a failure.
