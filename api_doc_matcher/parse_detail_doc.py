from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlsplit

from .models import ApiField, ApiParam, DetailApiEntry, ParseResult
from .text_utils import canonicalize_path, last_field_name, parse_markdown_table, path_to_api_id


CURL_HEAD = re.compile(r'^curl\s+-X\s+([A-Z]+)\s+"([^"]+)"')
HEADER_RE = re.compile(r'-H\s+"([^":]+)\s*:')
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


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


def _subsection_by_alias(lines: list[str], aliases: tuple[str, ...]) -> tuple[str, list[str]]:
    for idx, line in enumerate(lines):
        match = HEADING_RE.match(line.strip())
        if not match:
            continue
        heading = match.group(2).strip()
        normalized = re.sub(r"[`*]", "", heading).lower()
        if not any(alias.lower() in normalized for alias in aliases):
            continue
        end = len(lines)
        for cursor in range(idx + 1, len(lines)):
            if HEADING_RE.match(lines[cursor].strip()):
                end = cursor
                break
        return heading, lines[idx + 1 : end]
    return "", []


def _parse_params(lines: list[str], *, position: str = "body") -> list[ApiParam]:
    params: list[ApiParam] = []
    for row in parse_markdown_table(lines):
        name = row.get("参数字段") or row.get("参数名") or row.get("名称") or row.get("参数") or ""
        if not name.strip():
            continue
        required_raw = row.get("是否必填") or row.get("必选") or row.get("必填") or ""
        params.append(
            ApiParam(
                name=name.strip().strip("`"),
                type=(row.get("数据类型") or row.get("类型") or "").strip(),
                required=required_raw.strip() in {"是", "true", "True", "required"},
                description=(row.get("说明") or row.get("备注") or "").strip(),
                position=(row.get("位置") or position).strip().lower() or position,
            )
        )
    return params


def _parse_response_fields(lines: list[str], *, response_root: str = "") -> list[ApiField]:
    fields: list[ApiField] = []
    for row in parse_markdown_table(lines):
        path = row.get("字段名称") or row.get("字段名") or row.get("名称") or row.get("字段") or ""
        if not path.strip():
            continue
        clean_path = path.strip().lstrip("»").strip().replace("`", "")
        if response_root and "." not in clean_path and not clean_path.startswith("["):
            clean_path = f"{response_root}.{clean_path}"
        fields.append(
            ApiField(
                path=clean_path,
                name=last_field_name(clean_path),
                type=(row.get("数据类型") or row.get("类型") or "").strip(),
                description=(row.get("说明") or row.get("中文名") or "").strip(),
            )
        )
    return fields


def _parse_response_examples(lines: list[str]) -> list[dict[str, object]]:
    examples: list[dict[str, object]] = []
    in_json = False
    buffer: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not in_json and stripped.lower() == "```json":
            in_json = True
            buffer = []
            continue
        if in_json and stripped == "```":
            raw = "\n".join(buffer).strip()
            in_json = False
            buffer = []
            if not raw:
                continue
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                examples.append(value)
            continue
        if in_json:
            buffer.append(line)
    return examples


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


def _document_api_name(lines: list[str]) -> str:
    for row in parse_markdown_table(lines):
        if (row.get("项目") or "").strip() == "接口名称" and (row.get("内容") or "").strip():
            return (row.get("内容") or "").strip()
    for line in lines:
        if line.startswith("# "):
            return re.sub(r"接口文档$", "接口", line[2:].strip())
    return ""


def _verified_status(block: list[str], examples: list[dict[str, object]]) -> str:
    text = "\n".join(block)
    if re.search(r"验证状态[^\n]*(成功|success)", text, re.IGNORECASE):
        return "success"
    for example in examples:
        if str(example.get("code", "")) == "200" and ("data" in example or str(example.get("msg", "")) == "成功"):
            return "success"
    return "unverified"


def _response_examples_from_block(block: list[str]) -> list[dict[str, object]]:
    examples = _parse_response_examples(block)
    response_examples: list[dict[str, object]] = []
    seen: set[str] = set()
    for example in examples:
        if "data" not in example and "code" not in example:
            continue
        key = json.dumps(example, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        response_examples.append(example)
    return response_examples


def _response_root_from_heading(heading: str) -> str:
    match = re.search(r"`?([a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*|\[\])+)`?", heading)
    return match.group(1) if match else "data.result[]"


def _default_params(url: str) -> dict[str, object]:
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    return {key: values[-1] for key, values in query.items() if key == "data_source" and values}


def parse_detail_doc(markdown: str, source_path: str = "") -> ParseResult:
    lines = markdown.splitlines()
    curl_blocks = _find_curl_blocks(lines)
    document_api_name = _document_api_name(lines)
    entries: list[DetailApiEntry] = []
    failures: list[dict[str, object]] = []
    for start, end, method, url in curl_blocks:
        block = lines[start:end]
        section_scope = lines if len(curl_blocks) == 1 and document_api_name else block
        path = canonicalize_path(url)
        api_id = path_to_api_id(path)
        params = _parse_params(_subsection(section_scope, "参数字段说明"))
        if not params:
            _, query_lines = _subsection_by_alias(section_scope, ("query 参数", "query参数"))
            params = _parse_params(query_lines, position="query")
        response_heading, response_lines = _subsection_by_alias(
            section_scope,
            ("返回字段说明", "data.result[] 字段说明", "响应字段说明"),
        )
        response_root = _response_root_from_heading(response_heading)
        response_fields = _parse_response_fields(response_lines, response_root=response_root)
        response_examples = _response_examples_from_block(block)
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
                api_name=document_api_name if len(curl_blocks) == 1 else "",
                verified_status=_verified_status(block, response_examples),
                verified_url_path=urlsplit(url).path,
                response_root=response_root,
                default_params=_default_params(url),
                source_path=source_path,
                source_line_no=start + 1,
                request_params=params,
                request_headers=_parse_headers(block),
                response_fields=response_fields,
                response_examples=response_examples,
                parse_warnings=warnings,
            )
        )
    if not entries:
        failures.append({"failure_type": "curl_block_not_found"})
    return ParseResult(entries=entries, failures=failures, source_path=source_path)
