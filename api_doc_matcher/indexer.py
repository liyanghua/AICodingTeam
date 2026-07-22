from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import ApiDocEntry, BuildIndexResult, DetailApiEntry, ValidationEntry
from .parse_detail_doc import parse_detail_doc
from .parse_validation_doc import parse_validation_doc


CATEGORY_NAME_KEYS = ("category_name", "cate_name", "category", "tertiary_category", "three_level")
CATEGORY_ID_KEYS = ("category_id", "cate_id", "cid", "c_id", "cat_id")
PRODUCT_TEXT_KEYS = ("goods_name", "commodity", "product_name", "title", "comp_goods_name")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _make_entry(validation: ValidationEntry | None, detail: DetailApiEntry | None) -> ApiDocEntry:
    api_id = validation.api_id if validation else detail.api_id if detail else ""
    return ApiDocEntry(
        api_id=api_id,
        source_seq=validation.source_seq if validation else None,
        name=validation.name if validation else detail.api_name if detail and detail.api_name else api_id,
        module=validation.module if validation else "",
        business_module=validation.business_module if validation else "",
        analysis_domain=validation.analysis_domain if validation else "",
        method=validation.method if validation else detail.method if detail else "",
        path=validation.path if validation else detail.path if detail else "",
        verified_status=validation.verified_status if validation else detail.verified_status if detail else "unverified",
        verified_url_path=validation.verified_url_path if validation else detail.verified_url_path if detail else "",
        response_root=detail.response_root if detail else "data.result[]",
        default_params=detail.default_params if detail else {},
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


def _walk_objects(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_objects(child)


def _first_text(row: dict[str, Any], keys: tuple[str, ...]) -> tuple[str, str]:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return key, str(value).strip()
    return "", ""


def _category_entities(detail_entries: list[DetailApiEntry]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in detail_entries:
        for example in entry.response_examples:
            for row in _walk_objects(example):
                name_key, category_name = _first_text(row, CATEGORY_NAME_KEYS)
                id_key, category_id = _first_text(row, CATEGORY_ID_KEYS)
                if not category_name or not category_id:
                    continue
                text_key, evidence_text = _first_text(row, PRODUCT_TEXT_KEYS)
                group_key = (category_name, category_id)
                entity = grouped.setdefault(
                    group_key,
                    {
                        "canonical_name": category_name,
                        "category_id": category_id,
                        "aliases": [],
                        "evidence_count": 0,
                        "evidence_texts": [],
                        "evidence_sources": [],
                    },
                )
                entity["evidence_count"] += 1
                if evidence_text and evidence_text not in entity["evidence_texts"] and len(entity["evidence_texts"]) < 8:
                    entity["evidence_texts"].append(evidence_text)
                source = {
                    "api_id": entry.api_id,
                    "source_ref": {
                        "path": entry.source_path,
                        "line": entry.source_line_no,
                    },
                    "name_field_path": name_key,
                    "id_field_path": id_key,
                    "evidence_text_field": text_key,
                    "evidence_kind": "api_response_example",
                }
                if source not in entity["evidence_sources"]:
                    entity["evidence_sources"].append(source)
    return sorted(grouped.values(), key=lambda item: (item["canonical_name"], item["category_id"]))


def merge_detail_documents_into_index_payload(
    index_payload: dict[str, Any],
    extra_detail_documents: list[tuple[str, str]],
) -> dict[str, Any]:
    payload = dict(index_payload)
    existing = [ApiDocEntry.from_dict(item) for item in payload.get("apis", []) if isinstance(item, dict)]
    order = [entry.api_id for entry in existing]
    by_id = {entry.api_id: entry for entry in existing}
    parsed_details: list[DetailApiEntry] = []
    for source_path, markdown in extra_detail_documents:
        parsed_details.extend(parse_detail_doc(markdown, source_path=source_path).entries)
    for detail in parsed_details:
        current = by_id.get(detail.api_id)
        if current:
            current.request_params = detail.request_params or current.request_params
            current.request_headers = detail.request_headers or current.request_headers
            current.response_fields = detail.response_fields or current.response_fields
            current.verified_url_path = detail.verified_url_path or current.verified_url_path
            current.response_root = detail.response_root or current.response_root
            current.default_params = detail.default_params or current.default_params
            current.source_refs["detail_doc"] = {"path": detail.source_path, "line": detail.source_line_no}
            current.parse_warnings = detail.parse_warnings
            if current.verified_status != "success":
                current.verified_status = detail.verified_status
            if not current.name or current.name == current.api_id:
                current.name = detail.api_name or current.name
        else:
            by_id[detail.api_id] = _make_entry(None, detail)
            order.append(detail.api_id)
    existing_entities = [item for item in payload.get("category_entities", []) if isinstance(item, dict)]
    entity_by_key = {
        (str(item.get("canonical_name", "")), str(item.get("category_id", ""))): item
        for item in existing_entities
    }
    for entity in _category_entities(parsed_details):
        entity_by_key[(str(entity.get("canonical_name", "")), str(entity.get("category_id", "")))] = entity
    entities = sorted(entity_by_key.values(), key=lambda item: (str(item.get("canonical_name", "")), str(item.get("category_id", ""))))
    payload.update({
        "schema_version": "api-doc-index-v2",
        "api_count": len(order),
        "category_entity_count": len(entities),
        "category_entities": entities,
        "apis": [by_id[api_id].to_dict() for api_id in order],
    })
    return payload


def build_index(
    *,
    detail_markdown: str,
    validation_markdown: str,
    out_dir: Path,
    detail_source_path: str = "",
    validation_source_path: str = "",
    extra_detail_documents: list[tuple[str, str]] | None = None,
) -> BuildIndexResult:
    detail_result = parse_detail_doc(detail_markdown, source_path=detail_source_path)
    validation_result = parse_validation_doc(validation_markdown, source_path=validation_source_path)
    extra_results = [
        parse_detail_doc(markdown, source_path=source_path)
        for source_path, markdown in (extra_detail_documents or [])
    ]
    all_detail_entries = list(detail_result.entries)
    for extra_result in extra_results:
        all_detail_entries.extend(extra_result.entries)
    detail_by_id: dict[str, DetailApiEntry] = {entry.api_id: entry for entry in all_detail_entries}
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

    category_entities = _category_entities(all_detail_entries)

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        out_dir / "api_doc_index.json",
        {
            "schema_version": "api-doc-index-v2",
            "api_count": len(entries),
            "category_entity_count": len(category_entities),
            "category_entities": category_entities,
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
        f"- Category entities: {len(category_entities)}",
        f"- Validation parse failures: {len(validation_result.failures)}",
        f"- Detail parse failures: {len(detail_result.failures) + sum(len(item.failures) for item in extra_results)}",
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


def build_index_from_files(
    detail_doc: Path,
    validation_doc: Path,
    out_dir: Path,
    extra_detail_docs: list[Path] | None = None,
) -> BuildIndexResult:
    return build_index(
        detail_markdown=detail_doc.read_text(encoding="utf-8"),
        validation_markdown=validation_doc.read_text(encoding="utf-8"),
        out_dir=out_dir,
        detail_source_path=str(detail_doc),
        validation_source_path=str(validation_doc),
        extra_detail_documents=[(str(path), path.read_text(encoding="utf-8")) for path in (extra_detail_docs or [])],
    )
