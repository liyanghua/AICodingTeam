from __future__ import annotations

from pathlib import Path

from .base import CommandRunnerAdapter


def create_hyperagent_adapter() -> CommandRunnerAdapter:
    root = Path(__file__).resolve().parents[2]
    return CommandRunnerAdapter(
        framework="hyperagent",
        command=["node", str(root / "runners" / "hyperagent_runner.mjs")],
        runner_kind="node",
        notes="HyperAgent runner uses the official HyperAgent package when installed.",
        timeout_seconds=3600,
    )

