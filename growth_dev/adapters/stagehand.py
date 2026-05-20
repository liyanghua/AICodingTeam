from __future__ import annotations

from pathlib import Path

from .base import CommandRunnerAdapter


def create_stagehand_adapter() -> CommandRunnerAdapter:
    root = Path(__file__).resolve().parents[2]
    return CommandRunnerAdapter(
        framework="stagehand",
        command=["node", str(root / "runners" / "stagehand_runner.mjs")],
        runner_kind="node",
        notes="Stagehand runner uses @browserbasehq/stagehand when installed.",
        timeout_seconds=3600,
    )

