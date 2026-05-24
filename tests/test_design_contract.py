from __future__ import annotations

import re
import unittest
from pathlib import Path


class DesignContractTests(unittest.TestCase):
    def test_root_design_md_uses_design_md_contract_shape(self) -> None:
        root = Path(__file__).resolve().parents[1]
        design_path = root / "DESIGN.md"

        text = design_path.read_text(encoding="utf-8")
        frontmatter = _frontmatter(text)

        self.assertIn("colors:", frontmatter)
        self.assertIn("typography:", frontmatter)
        self.assertIn("spacing:", frontmatter)
        self.assertIn("rounded:", frontmatter)
        self.assertIn("elevation:", frontmatter)
        self.assertIn("components:", frontmatter)
        for heading in (
            "## Overview",
            "## Colors",
            "## Typography",
            "## Layout",
            "## Elevation & Depth",
            "## Shapes",
            "## Components",
            "## Do's and Don'ts",
        ):
            self.assertIn(heading, text)
        self.assertIn("Agent Team Dashboard", text)
        self.assertIn("business and product users", text)

    def test_dashboard_css_tokens_are_declared_in_design_md(self) -> None:
        root = Path(__file__).resolve().parents[1]
        design_text = (root / "DESIGN.md").read_text(encoding="utf-8")
        css_text = (root / "dashboard" / "styles.css").read_text(encoding="utf-8")

        required_tokens = (
            "--color-background",
            "--color-surface",
            "--color-text",
            "--color-status-processing",
            "--color-status-completed",
            "--space-2",
            "--radius-card",
            "--elevation-panel",
            "--component-button-height",
            "--component-card-border",
        )
        for token in required_tokens:
            self.assertIn(token, css_text)
            self.assertIn(token.removeprefix("--"), design_text)
        self.assertNotIn("--primary:", css_text)
        self.assertNotIn("--surface-soft:", css_text)

    def test_agents_and_codex_reference_design_md_for_ui_work(self) -> None:
        root = Path(__file__).resolve().parents[1]
        agents_text = (root / "AGENTS.md").read_text(encoding="utf-8")

        from growth_dev.team.codex import DEFAULT_ALLOWED_PATHS, UPSTREAM_CONTEXT_ARTIFACTS

        self.assertIn("DESIGN.md", agents_text)
        self.assertIn("Dashboard", agents_text)
        self.assertIn("DESIGN.md", DEFAULT_ALLOWED_PATHS)
        self.assertIn("DESIGN.md", UPSTREAM_CONTEXT_ARTIFACTS)


def _frontmatter(text: str) -> str:
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise AssertionError("DESIGN.md must start with YAML frontmatter")
    return match.group(1)
