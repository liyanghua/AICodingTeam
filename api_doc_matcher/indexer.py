from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import ApiDocEntry, BuildIndexResult, DetailApiEntry, ValidationEntry
from .parse_detail_doc import parse_detail_doc
from .parse_validation_doc import parse_validation_doc


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _make_entry(validation: ValidationEntry | None, detail: DetailApiEntry | None) -> ApiDocEntry:
    api_id = validation.api_id if validation else detail.api_id if detail else ""
    return ApiDocEntry(
        api_id=api_id,
        source_seq=validation.source_seq if validation else None,
        name=validation.name if validation else api_id,
        module=validation.module if validation else "",
        business_module=validation.business_module if validation else "",
        analysis_domain=validation.analysis_domain if validation else "",
        method=validation.method if validation else detail.method if detail else "",
        path=validation.path if validation else detail.path if detail else "",
        verified_status=validation.verified_status if validation else "unverified",
        request_params=detail.request_params if detail else [],
        request_headers=detail.request_headers if detail else [],
        response_fields=detail.response_fields if detail else [],
        source_refs={
            "validation_doc": {
                "path": validation.source_path,
                "line": validation.source_line_no,
            }
            if validation
            else None,
            "detail_doc": {"path": detail.source_path, "line": detail.source_line_no} if detail else None,
        },
        parse_warnings=detail.parse_warnings if detail else ["missing_detail_doc_entry"],
    )


def build_index(
    *,
    detail_markdown: str,
    validation_markdown: str,
    out_dir: Path,
    detail_source_path: str = "",
    validation_source_path: str = "",
) -> BuildIndexResult:
    detail_result = parse_detail_doc(detail_markdown, source_path=detail_source_path)
    validation_result = parse_validation_doc(validation_markdown, source_path=validation_source_path)
    detail_by_id: dict[str, DetailApiEntry] = {entry.api_id: entry for entry in detail_result.entries}
    validation_by_id: dict[str, ValidationEntry] = {entry.api_id: entry for entry in validation_result.entries}

    entries: list[ApiDocEntry] = []
    join_hit = 0
    join_miss = 0
    for validation in validation_result.entries:
        detail = detail_by_id.get(validation.api_id)
        if detail:
            join_hit += 1
        else:
            join_miss += 1
        entries.append(_make_entry(validation, detail))

    orphan_details = [detail for api_id, detail in detail_by_id.items() if api_id not in validation_by_id]
    for detail in orphan_details:
        entries.append(_make_entry(None, detail))

    field_entries: list[dict[str, Any]] = []
    for entry in entries:
        for field_item in entry.response_fields:
            field_entries.append(
                {
                    "api_id": entry.api_id,
                    "api_name": entry.name,
                    "field_path": field_item.path,
                    "field_name": field_item.name,
                    "field_type": field_item.type,
                    "description": field_item.description,
                    "verified_status": entry.verified_status,
                    "business_module": entry.business_module,
                    "analysis_domain": entry.analysis_domain,
                }
            )

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        out_dir / "api_doc_index.json",
        {
            "schema_version": "api-doc-index-v1",
            "api_count": len(entries),
            "apis": [entry.to_dict() for entry in entries],
        },
    )
    _write_json(
        out_dir / "api_field_index.json",
        {
            "schema_version": "api-field-index-v1",
            "field_count": len(field_entries),
            "fields": field_entries,
        },
    )
    with (out_dir / "api_doc_chunks.jsonl").open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(
                json.dumps(
                    {
                        "api_id": entry.api_id,
                        "text": " ".join(
                            [
                                entry.name,
                                entry.business_module,
                                entry.analysis_domain,
                                entry.path,
                                " ".join(f"{f.path} {f.description}" for f in entry.response_fields),
                            ]
                        ).strip(),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    report = [
        "# API Doc Index Report",
        "",
        f"- API entries: {len(entries)}",
        f"- Field entries: {len(field_entries)}",
        f"- Validation parse failures: {len(validation_result.failures)}",
        f"- Detail parse failures: {len(detail_result.failures)}",
        f"- Join hit: {join_hit}",
        f"- Join miss: {join_miss}",
        f"- Orphan detail: {len(orphan_details)}",
        "",
        "## Safety",
        "",
        "- Header secret values are not stored; only header names are retained.",
    ]
    (out_dir / "api_doc_index_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    return BuildIndexResult(
        api_entries=entries,
        field_entries=field_entries,
        join_hit_count=join_hit,
        join_miss_count=join_miss,
        orphan_detail_count=len(orphan_details),
        output_dir=str(out_dir),
    )


def build_index_from_files(detail_doc: Path, validation_doc: Path, out_dir: Path) -> BuildIndexResult:
    return build_index(
        detail_markdown=detail_doc.read_text(encoding="utf-8"),
        validation_markdown=validation_doc.read_text(encoding="utf-8"),
        out_dir=out_dir,
        detail_source_path=str(detail_doc),
        validation_source_path=str(validation_doc),
    )
