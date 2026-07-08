from __future__ import annotations

import re

from .models import BusinessField, SectionContext
from .text_utils import parse_markdown_table


FLOW_HEAD = re.compile(r"^##\s*(流程\d+[:：].+?)\s*$")
SUB_HEAD = re.compile(r"^###\s*([0-9]+(?:\.[0-9]+)?)[\s\u00a0]*(.+?)\s*$")


def _normalize_spaces(text: str) -> str:
    return text.replace("\u00a0", " ").strip()


def _extract_section(markdown: str, section_title: str) -> tuple[str, list[str]]:
    lines = markdown.splitlines()
    start = -1
    normalized_target = _normalize_spaces(section_title)
    title = normalized_target
    for idx, line in enumerate(lines):
        match = FLOW_HEAD.match(_normalize_spaces(line))
        if match and _normalize_spaces(match.group(1)) == normalized_target:
            start = idx
            title = _normalize_spaces(match.group(1))
            break
    if start < 0:
        raise ValueError(f"section not found: {section_title}")

    end = len(lines)
    for idx in range(start + 1, len(lines)):
        if FLOW_HEAD.match(_normalize_spaces(lines[idx])):
            end = idx
            break
    return title, lines[start:end]


def _subsections(lines: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    current_key = ""
    current_lines: list[str] = []
    for line in lines:
        match = SUB_HEAD.match(_normalize_spaces(line))
        if match:
            if current_key:
                out[current_key] = current_lines
            current_key = match.group(1)
            current_lines = []
            continue
        if current_key:
            current_lines.append(line)
    if current_key:
        out[current_key] = current_lines
    return out


def _plain_text(lines: list[str]) -> str:
    text_lines: list[str] = []
    for line in lines:
        stripped = _normalize_spaces(line)
        if not stripped or stripped.startswith("|") or stripped.startswith("---"):
            continue
        text_lines.append(stripped)
    return " ".join(text_lines).strip()


def _numbered_items(lines: list[str]) -> list[str]:
    items: list[str] = []
    for line in lines:
        stripped = _normalize_spaces(line)
        if not stripped:
            continue
        stripped = re.sub(r"^[0-9]+[.、]\s*", "", stripped)
        stripped = re.sub(r"^第[一二三四五六七八九十]+步[:：]\s*", "", stripped)
        if stripped and not stripped.startswith("|"):
            items.append(stripped)
    return items


def _output_fields(lines: list[str]) -> list[BusinessField]:
    fields: list[BusinessField] = []
    for row in parse_markdown_table(lines):
        name = (row.get("字段") or "").strip()
        if not name:
            continue
        fields.append(BusinessField(name=name, description=(row.get("说明") or "").strip()))
    return fields


def parse_business_section(markdown: str, section_title: str, source_path: str = "") -> SectionContext:
    title, lines = _extract_section(markdown, section_title)
    subs = _subsections(lines)
    purpose = _plain_text(subs.get("2.1", []))
    data_sources = _numbered_items(subs.get("2.2", []))
    actions = _numbered_items(subs.get("2.3", []))
    output_fields = _output_fields(subs.get("2.4", []))
    return SectionContext(
        title=title,
        purpose=purpose,
        data_sources=data_sources,
        actions=actions,
        output_fields=output_fields,
        source_path=source_path,
    )


def parse_business_section_from_file(path: str, section_title: str) -> SectionContext:
    from pathlib import Path

    doc_path = Path(path)
    return parse_business_section(
        doc_path.read_text(encoding="utf-8"),
        section_title,
        source_path=str(doc_path),
    )
