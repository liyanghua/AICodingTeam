from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from .models import RunRecord
from .scoring import FrameworkScore, summary_table
from .utils import clamp, ensure_dir, write_json


def _point(cx: float, cy: float, radius: float, angle: float) -> tuple[float, float]:
    return cx + math.cos(angle) * radius, cy + math.sin(angle) * radius


def radar_svg(scores: dict[str, float], size: int = 420) -> str:
    labels = list(scores.keys())
    values = [clamp(scores[label]) for label in labels]
    cx = cy = size / 2
    radius = size * 0.32
    steps = 5
    angle_offset = -math.pi / 2
    points = []
    for index, value in enumerate(values):
        angle = angle_offset + (2 * math.pi * index / len(values))
        points.append(_point(cx, cy, radius * value, angle))

    grid_polygons = []
    for step in range(1, steps + 1):
        r = radius * step / steps
        pts = []
        for index in range(len(values)):
            angle = angle_offset + (2 * math.pi * index / len(values))
            x, y = _point(cx, cy, r, angle)
            pts.append(f"{x:.2f},{y:.2f}")
        grid_polygons.append(f'<polygon points="{" ".join(pts)}" fill="none" stroke="rgba(120,120,120,0.25)" stroke-width="1" />')

    axis_lines = []
    label_nodes = []
    for index, label in enumerate(labels):
        angle = angle_offset + (2 * math.pi * index / len(values))
        x, y = _point(cx, cy, radius, angle)
        axis_lines.append(f'<line x1="{cx:.2f}" y1="{cy:.2f}" x2="{x:.2f}" y2="{y:.2f}" stroke="rgba(120,120,120,0.35)" stroke-width="1" />')
        lx, ly = _point(cx, cy, radius + 28, angle)
        label_nodes.append(
            f'<text x="{lx:.2f}" y="{ly:.2f}" text-anchor="middle" dominant-baseline="middle" font-size="13" fill="#1f2937">{label}</text>'
        )

    area_points = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    point_nodes = "".join(
        f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4.5" fill="#2563eb" />' for x, y in points
    )

    return f"""
<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">
  <rect width="100%" height="100%" fill="white" />
  {''.join(grid_polygons)}
  {''.join(axis_lines)}
  <polygon points="{area_points}" fill="rgba(37,99,235,0.18)" stroke="#2563eb" stroke-width="2" />
  {point_nodes}
  {''.join(label_nodes)}
</svg>
""".strip()


def render_markdown_report(run_record: RunRecord, framework_scores: list[FrameworkScore]) -> str:
    rows = summary_table(framework_scores)
    lines = [
        f"# XHS Browser Framework Benchmark Report",
        "",
        f"- Run ID: `{run_record.run_id}`",
        f"- Keyword: `{run_record.task.keyword}`",
        f"- Top N: `{run_record.task.top_n}`",
        f"- Candidate Pool: `{run_record.task.candidate_pool}`",
        "",
        "## Summary",
        "",
        "| framework | status | total_score | completeness | risk_friendliness | stability | maintainability | elapsed_ms | token_cost |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['framework']} | {row['status']} | {row['total_score']:.4f} | {row['completeness']:.4f} | {row['risk_friendliness']:.4f} | {row['stability']:.4f} | {row['maintainability']:.4f} | {row['elapsed_ms']} | {row['token_cost']:.2f} |"
        )

    successful_rows = [row for row in rows if row["status"] == "success"]
    if successful_rows:
        best = max(successful_rows, key=lambda item: item["total_score"])
        lines += [
            "",
            "## Recommendation",
            "",
            f"Best current framework: `{best['framework']}` with score `{best['total_score']:.4f}`.",
            "",
        ]
    elif rows:
        lines += [
            "",
            "## Recommendation",
            "",
            "No framework completed a successful run yet. Fix runner availability before drawing framework conclusions.",
            "",
        ]

    lines += [
        "## Risk Events",
        "",
        "Risk events are recorded in the run artifacts for each adapter. Manual intervention, verification prompts, and blocking login states must be surfaced explicitly.",
        "",
        "## Notes",
        "",
        "- Real framework runs are only accepted when the framework package and runner are available locally.",
        "- The mock baseline should pass before any real browser integration is considered stable.",
    ]
    return "\n".join(lines)


def write_report(run_record: RunRecord, framework_scores: list[FrameworkScore], run_dir: Path) -> dict[str, Path]:
    ensure_dir(run_dir)
    markdown = render_markdown_report(run_record, framework_scores)
    report_md = run_dir / "report.md"
    report_json = run_dir / "report.json"
    report_svg = run_dir / "report.svg"
    report_md.write_text(markdown, encoding="utf-8")
    write_json(
        report_json,
        {
            "run_record": run_record.to_dict(),
            "framework_scores": [asdict(score) for score in framework_scores],
            "summary": summary_table(framework_scores),
        },
    )

    if framework_scores:
        radar = {
            "stability": sum(score.stability for score in framework_scores) / len(framework_scores),
            "completeness": sum(score.completeness for score in framework_scores) / len(framework_scores),
            "risk": sum(score.risk_friendliness for score in framework_scores) / len(framework_scores),
            "maintainability": sum(score.maintainability for score in framework_scores) / len(framework_scores),
            "score": sum(score.total_score for score in framework_scores) / len(framework_scores),
        }
        report_svg.write_text(
            radar_svg({
                "stability": radar["stability"],
                "completeness": radar["completeness"],
                "risk": radar["risk"],
                "maintainability": radar["maintainability"],
                "score": radar["score"],
            }),
            encoding="utf-8",
        )
    return {"report_md": report_md, "report_json": report_json, "report_svg": report_svg}
