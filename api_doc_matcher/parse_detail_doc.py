from __future__ import annotations

import re

from .models import ApiField, ApiParam, DetailApiEntry, ParseResult
from .text_utils import canonicalize_path, last_field_name, parse_markdown_table, path_to_api_id


CURL_HEAD = re.compile(r'^curl\s+-X\s+([A-Z]+)\s+"([^"]+)"')
HEADER_RE = re.compile(r'-H\s+"([^":]+)\s*:')


def _find_curl_blocks(lines: list[str]) -> list[tuple[int, int, str, str]]:
    starts: list[tuple[int, str, str]] = []
    for idx, line in enumerate(lines):
        match = CURL_HEAD.search(line.strip())
        if match:
            starts.append((idx, match.group(1).upper(), match.group(2)))
    blocks: list[tuple[int, int, str, str]] = []
    for pos, (start, method, url) in enumerate(starts):
        end = starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)
        blocks.append((start, end, method, url))
    return blocks


def _subsection(lines: list[str], title: str) -> list[str]:
    start = -1
    for idx, line in enumerate(lines):
        if line.strip() == f"### {title}":
            start = idx + 1
            break
    if start < 0:
        return []
    end = len(lines)
    for idx in range(start, len(lines)):
        if lines[idx].startswith("### "):
            end = idx
            break
    return lines[start:end]


def _parse_params(lines: list[str]) -> list[ApiParam]:
    params: list[ApiParam] = []
    for row in parse_markdown_table(lines):
        name = row.get("参数字段") or row.get("名称") or row.get("参数") or ""
        if not name.strip():
            continue
        required_raw = row.get("是否必填") or row.get("必选") or row.get("必填") or ""
        params.append(
            ApiParam(
                name=name.strip(),
                type=(row.get("数据类型") or row.get("类型") or "").strip(),
                required=required_raw.strip() in {"是", "true", "True", "required"},
                description=(row.get("说明") or row.get("备注") or "").strip(),
                position=(row.get("位置") or "body").strip().lower() or "body",
            )
        )
    return params


def _parse_response_fields(lines: list[str]) -> list[ApiField]:
    fields: list[ApiField] = []
    for row in parse_markdown_table(lines):
        path = row.get("字段名称") or row.get("名称") or row.get("字段") or ""
        if not path.strip():
            continue
        clean_path = path.strip().lstrip("»").strip()
        fields.append(
            ApiField(
                path=clean_path,
                name=last_field_name(clean_path),
                type=(row.get("数据类型") or row.get("类型") or "").strip(),
                description=(row.get("说明") or row.get("中文名") or "").strip(),
            )
        )
    return fields


def _parse_headers(lines: list[str]) -> list[str]:
    headers: list[str] = []
    seen: set[str] = set()
    for line in lines:
        for match in HEADER_RE.finditer(line):
            header = match.group(1).strip()
            if header and header not in seen:
                headers.append(header)
                seen.add(header)
    return headers


def parse_detail_doc(markdown: str, source_path: str = "") -> ParseResult:
    lines = markdown.splitlines()
    entries: list[DetailApiEntry] = []
    failures: list[dict[str, object]] = []
    for start, end, method, url in _find_curl_blocks(lines):
        block = lines[start:end]
        path = canonicalize_path(url)
        api_id = path_to_api_id(path)
        params = _parse_params(_subsection(block, "参数字段说明"))
        response_fields = _parse_response_fields(_subsection(block, "返回字段说明"))
        warnings: list[str] = []
        if not params:
            warnings.append("missing_request_params")
        if not response_fields:
            warnings.append("missing_response_fields")
        entries.append(
            DetailApiEntry(
                api_id=api_id,
                method=method,
                path=path,
                source_path=source_path,
                source_line_no=start + 1,
                request_params=params,
                request_headers=_parse_headers(block),
                response_fields=response_fields,
                parse_warnings=warnings,
            )
        )
    if not entries:
        failures.append({"failure_type": "curl_block_not_found"})
    return ParseResult(entries=entries, failures=failures, source_path=source_path)
