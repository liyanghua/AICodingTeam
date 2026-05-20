from __future__ import annotations

import json
import shutil
from pathlib import Path

from .models import TaskSpec
from .utils import ensure_dir


DEFAULT_TEAM_YAML = """\
team_id: ai_native_engineering_team
agents:
  - id: orchestrator
    outputs: [task.yaml, context.md]
  - id: product
    outputs: [prd.md]
  - id: architect
    outputs: [tech_spec.md]
  - id: ux
    outputs: [ui_spec.md]
  - id: qa
    outputs: [eval.md]
  - id: coder
    outputs: [coding_prompt.md, code_run_record.json]
  - id: reviewer
    outputs: [review_report.md]
  - id: verifier
    outputs: [test_report.md]
  - id: publisher
    outputs: [final_report.md]
gates:
  before_coding: [prd.md, tech_spec.md, ui_spec.md, eval.md]
  before_publish: [review_report.md, test_report.md]
"""


DEFAULT_XHS_DOMAIN_YAML = """\
domain_id: xhs_browser_benchmark
input_schema:
  keyword: string
  top_n: integer
  frameworks: list
risk_rules:
  - no_captcha_bypass
  - no_fingerprint_spoofing
  - no_proxy_rotation
  - manual_login_only
"""


def default_task_spec() -> TaskSpec:
    return TaskSpec(
        task_id="xhs-framework-benchmark",
        title="XHS browser framework benchmark harness",
        keyword="露营",
        top_n=20,
        candidate_pool=100,
        max_comments_per_note=500,
        mode="headed_low_frequency",
        profile_dir=Path(".local/browser-profiles/xhs"),
        frameworks=["playwright-mcp", "stagehand", "skyvern", "hyperagent", "browser-use"],
        base_url="http://127.0.0.1:8787",
        suite="pilot",
    )


def write_task_package(
    base_dir: Path,
    domain_id: str = "xhs_browser_benchmark",
    domains_dir: Path = Path("domains"),
) -> dict[str, Path]:
    ensure_dir(base_dir)
    task = default_task_spec()
    files: dict[str, Path] = {}

    task_yaml = base_dir / "task.yaml"
    context_md = base_dir / "context.md"
    prd_md = base_dir / "prd.md"
    tech_spec_md = base_dir / "tech_spec.md"
    ui_spec_md = base_dir / "ui_spec.md"
    eval_md = base_dir / "eval.md"
    tdd_md = base_dir / "tdd_cases.md"
    review_md = base_dir / "review_checklist.md"
    prompt_md = base_dir / "coding_prompt.md"
    team_yaml = base_dir / "team.yaml"
    domain_yaml = base_dir / "domain.yaml"

    task_yaml.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    context_md.write_text(
        "\n".join(
            [
                "# Context",
                "",
                "This task package drives an AI-native benchmark for XHS-style browser automation.",
                "",
                "Safety boundary: manual login only, no captcha bypass, no private API reverse engineering, no proxy rotation, no anti-bot evasion.",
                "",
                f"Frameworks: {', '.join(task.frameworks)}",
            ]
        ),
        encoding="utf-8",
    )
    prd_md.write_text(
        "\n".join(
            [
                "# PRD",
                "",
                "Build a benchmark harness that runs the same XHS采集 task across five browser frameworks and compares stability, completeness, risk friendliness, and maintainability.",
                "",
                "Acceptance: the mock site, schema validation, report generation, and framework runner slots must all exist.",
            ]
        ),
        encoding="utf-8",
    )
    tech_spec_md.write_text(
        "\n".join(
            [
                "# Technical Spec",
                "",
                "- Python stdlib harness",
                "- Local mock site with deterministic fixtures",
                "- Shared `XhsNote` schema",
                "- Per-framework runner scripts with JSON stdin/stdout contract",
                "- Markdown and SVG reporting",
            ]
        ),
        encoding="utf-8",
    )
    ui_spec_md.write_text(
        "\n".join(
            [
                "# UI Spec",
                "",
                "The mock site must expose search, search results, note detail, image/video media, comments, replies, and load-more states.",
            ]
        ),
        encoding="utf-8",
    )
    eval_md.write_text(
        "\n".join(
            [
                "# Eval",
                "",
                "## Schema",
                "",
                "- Validate every `XhsNote` payload against the shared schema.",
                "- Keep adapter results JSON-serializable and reproducible.",
                "",
                "## Tests",
                "",
                "- parse `1.2万`, `999+`, `3k`",
                "- generate deterministic fixtures",
                "- validate missing schema fields",
                "- compute completeness and summary tables",
                "- render markdown and SVG report artifacts",
                "",
                "## Risk Review",
                "",
                "- Manual login only.",
                "- No captcha bypass, fingerprint spoofing, proxy rotation, private API reverse engineering, or anti-bot evasion.",
                "- Risk events must be explicit in adapter and team reports.",
            ]
        ),
        encoding="utf-8",
    )
    tdd_md.write_text(
        "\n".join(
            [
                "# TDD Cases",
                "",
                "- parse `1.2万`, `999+`, `3k`",
                "- generate deterministic fixtures",
                "- validate missing schema fields",
                "- compute completeness and summary tables",
                "- render markdown and SVG report artifacts",
            ]
        ),
        encoding="utf-8",
    )
    review_md.write_text(
        "\n".join(
            [
                "# Review Checklist",
                "",
                "- Safety boundary intact",
                "- Shared schema preserved",
                "- Mock baseline passes",
                "- Risk events are explicit",
                "- Report generated with traceable artifacts",
            ]
        ),
        encoding="utf-8",
    )
    prompt_md.write_text(
        "\n".join(
            [
                "# Coding Prompt",
                "",
                "Implement the framework runner using the JSON protocol in this repository.",
                "Do not bypass login, do not disguise automation, and stop on any verification challenge.",
            ]
        ),
        encoding="utf-8",
    )
    _write_team_yaml(team_yaml, domains_dir / domain_id / "team.yaml")
    _write_domain_yaml(domain_yaml, domains_dir / domain_id / "domain.yaml")

    files["task.yaml"] = task_yaml
    files["context.md"] = context_md
    files["prd.md"] = prd_md
    files["tech_spec.md"] = tech_spec_md
    files["ui_spec.md"] = ui_spec_md
    files["eval.md"] = eval_md
    files["tdd_cases.md"] = tdd_md
    files["review_checklist.md"] = review_md
    files["coding_prompt.md"] = prompt_md
    files["team.yaml"] = team_yaml
    files["domain.yaml"] = domain_yaml
    return files


def _write_team_yaml(output_path: Path, source_path: Path) -> None:
    if source_path.exists():
        shutil.copyfile(source_path, output_path)
        return
    output_path.write_text(DEFAULT_TEAM_YAML, encoding="utf-8")


def _write_domain_yaml(output_path: Path, source_path: Path) -> None:
    if source_path.exists():
        shutil.copyfile(source_path, output_path)
        return
    output_path.write_text(DEFAULT_XHS_DOMAIN_YAML, encoding="utf-8")
