from __future__ import annotations

from .models import ParseResult, ValidationEntry
from .text_utils import canonicalize_path, path_to_api_id, safe_json_loads, split_markdown_table_row, strip_ticks


HEADER_PREFIX = "| 序号 | 模块 | 业务模块 | 分析域 | 接口名称 | 方法 | 原URL/Path | 修复后状态 | 修复后可用URL | 修复后入参 | 说明/验证信息 |"


def _status_value(raw: str) -> str:
    if "成功但空" in raw:
        return "empty"
    if "成功" in raw:
        return "success"
    if "无权限" in raw:
        return "unauthorized"
    if "无法测试" in raw:
        return "untestable"
    if "失败" in raw:
        return "business_failed"
    return "unknown"


def parse_validation_doc(markdown: str, source_path: str = "") -> ParseResult:
    lines = markdown.splitlines()
    header_index = -1
    for idx, line in enumerate(lines):
        if line.strip() == HEADER_PREFIX:
            header_index = idx
            break
    if header_index < 0:
        return ParseResult(entries=[], failures=[{"failure_type": "header_not_found"}], source_path=source_path)

    header = split_markdown_table_row(lines[header_index])
    entries: list[ValidationEntry] = []
    failures: list[dict[str, object]] = []
    for idx in range(header_index + 2, len(lines)):
        line = lines[idx]
        stripped = line.strip()
        if stripped.startswith("## ") or stripped.startswith("# "):
            break
        if not stripped.startswith("|"):
            continue
        cells = split_markdown_table_row(stripped)
        if len(cells) != len(header):
            failures.append(
                {
                    "source_line_no": idx + 1,
                    "failure_type": "column_count_mismatch",
                    "message": f"expected {len(header)} columns, got {len(cells)}",
                }
            )
            continue
        row = {header[i]: cells[i] for i in range(len(header))}
        try:
            source_seq = int(row["序号"].strip())
        except ValueError:
            failures.append(
                {
                    "source_line_no": idx + 1,
                    "failure_type": "source_seq_unparseable",
                    "message": row.get("序号", ""),
                }
            )
            continue
        path = canonicalize_path(row["原URL/Path"])
        entries.append(
            ValidationEntry(
                api_id=path_to_api_id(path),
                source_seq=source_seq,
                module=row["模块"].strip(),
                business_module=row["业务模块"].strip(),
                analysis_domain=row["分析域"].strip(),
                name=row["接口名称"].strip(),
                method=row["方法"].strip().upper(),
                path=path,
                verified_status=_status_value(row["修复后状态"]),
                verified_url_path=canonicalize_path(row["修复后可用URL"]),
                body_template=safe_json_loads(row["修复后入参"]),
                verified_msg=strip_ticks(row["说明/验证信息"]).strip(),
                source_path=source_path,
                source_line_no=idx + 1,
            )
        )
    return ParseResult(entries=entries, failures=failures, source_path=source_path)
