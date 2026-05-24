# Failure Taxonomy

- `schema_mismatch`: artifact, domain output, or API response shape does not match the declared contract.
- `api_contract_broken`: CLI/API behavior changed incompatibly or a command now rejects valid inputs.
- `test_missing`: implementation changed behavior without a regression or acceptance test.
- `ui_state_missing`: loading, empty, error, success, permission, or handoff state is absent or unclear.
- `runtime_error`: command, background process, Codex executor, provider, filesystem, or permission failure.
- `architecture_violation`: change crosses ownership boundaries, writes to disallowed paths, or hardcodes policy in the wrong layer.
- `unrelated_refactor`: diff includes behavior or structure outside the requested slice.
