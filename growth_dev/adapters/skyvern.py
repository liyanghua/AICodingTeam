from __future__ import annotations

from pathlib import Path

from .base import CommandRunnerAdapter


def create_skyvern_adapter() -> CommandRunnerAdapter:
    root = Path(__file__).resolve().parents[2]
    return CommandRunnerAdapter(
        framework="skyvern",
        command=["python3", str(root / "runners" / "skyvern_runner.py")],
        runner_kind="python",
        notes="Skyvern runner requires the skyvern package.",
        timeout_seconds=3600,
    )

