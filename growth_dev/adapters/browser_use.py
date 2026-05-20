from __future__ import annotations

from pathlib import Path

from .base import CommandRunnerAdapter


def create_browser_use_adapter() -> CommandRunnerAdapter:
    root = Path(__file__).resolve().parents[2]
    return CommandRunnerAdapter(
        framework="browser-use",
        command=["python3", str(root / "runners" / "browser_use_runner.py")],
        runner_kind="python",
        notes="browser-use runner uses the browser-use package when installed.",
        timeout_seconds=3600,
    )

