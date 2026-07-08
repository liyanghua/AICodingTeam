from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import unquote, urlparse


OPENAPI_PREFIX = re.compile(r"^/openApi/api/[^/]+/5(?=/)")
NON_ID = re.compile(r"[^a-zA-Z0-9]+")


def strip_ticks(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == "`" and text[-1] == "`":
        return text[1:-1].strip()
    return text


def canonicalize_path(value: str) -> str:
    text = strip_ticks(value).strip().strip('"')
    if not text:
        return ""
    parsed = urlparse(text)
    path = parsed.path if parsed.scheme and parsed.netloc else text.split("?", 1)[0]
    path = unquote(path)
    path = OPENAPI_PREFIX.sub("", path)
    if not path.startswith("/"):
        path = "/" + path
    return path.rstrip("/") or "/"


def path_to_api_id(path: str) -> str:
    normalized = canonicalize_path(path).strip("/")
    api_id = NON_ID.sub("_", normalized).strip("_").lower()
    return api_id or "root"


def split_markdown_table_row(line: str) -> list[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    cells: list[str] = []
    buf: list[str] = []
    in_ticks = False
    escape = False
    for ch in text:
        if escape:
            buf.append(ch)
            escape = False
            continue
        if ch == "\\":
            buf.append(ch)
            escape = True
            continue
        if ch == "`":
            in_ticks = not in_ticks
            buf.append(ch)
            continue
        if ch == "|" and not in_ticks:
            cells.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    cells.append("".join(buf).strip())
    return cells


def parse_markdown_table(lines: list[str]) -> list[dict[str, str]]:
    header: list[str] | None = None
    saw_divider = False
    rows: list[dict[str, str]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            if header and saw_divider:
                break
            continue
        cells = split_markdown_table_row(stripped)
        if not header:
            header = cells
            continue
        if not saw_divider and all(re.fullmatch(r":?-{2,}:?", c.strip()) for c in cells):
            saw_divider = True
            continue
        if not saw_divider:
            header = cells
            continue
        row = {header[i]: cells[i] if i < len(cells) else "" for i in range(len(header))}
        if any(v.strip() for v in row.values()):
            rows.append(row)
    return rows


def safe_json_loads(value: str) -> dict[str, Any]:
    text = strip_ticks(value).strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def last_field_name(path: str) -> str:
    tail = path.split(".")[-1]
    return tail.replace("[]", "").strip()


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def query_terms(value: str) -> list[str]:
    terms = {normalize_text(value)}
    for part in re.split(r"[\s,，。；;:：/|()（）\\[\\]{}<>《》]+", value):
        part = part.strip().lower()
        if len(part) >= 2:
            terms.add(part)
    compact = re.sub(r"\s+", "", value.lower())
    for i in range(max(0, len(compact) - 1)):
        gram = compact[i : i + 2]
        if re.search(r"[\u4e00-\u9fff]", gram):
            terms.add(gram)
    return [t for t in terms if t]
