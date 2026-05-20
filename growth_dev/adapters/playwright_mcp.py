from __future__ import annotations

from pathlib import Path

from .base import CommandRunnerAdapter


def create_playwright_mcp_adapter() -> CommandRunnerAdapter:
    root = Path(__file__).resolve().parents[2]
    return CommandRunnerAdapter(
        framework="playwright-mcp",
        command=["python3", str(root / "runners" / "playwright_mcp_runner.py")],
        runner_kind="python",
        notes="Playwright MCP needs a dedicated MCP client bridge.",
        timeout_seconds=3600,
    )

