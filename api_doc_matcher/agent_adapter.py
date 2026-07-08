from __future__ import annotations

import json
from pathlib import Path

from .matcher import match_api_requirement, match_business_fields
from .models import ApiDocEntry
from .section_matcher import match_section
from .section_parser import parse_business_section_from_file


def load_api_entries(index_path: str | Path) -> list[ApiDocEntry]:
    data = json.loads(Path(index_path).read_text(encoding="utf-8"))
    return [ApiDocEntry.from_dict(item) for item in data.get("apis", [])]


def match_business_api_requirement(index_path: str | Path, query: str, top_k: int = 5) -> dict:
    entries = load_api_entries(index_path)
    return {
        "schema_version": "business-api-match-v1",
        "query": query,
        "matches": [match.to_dict() for match in match_api_requirement(entries, query, top_k=top_k)],
    }


def match_business_fields_to_api_fields(
    index_path: str | Path,
    fields: list[str],
    api_ids: list[str] | None = None,
) -> dict:
    entries = load_api_entries(index_path)
    return {
        "schema_version": "business-field-match-v1",
        **match_business_fields(entries, fields, api_ids=api_ids).to_dict(),
    }


def match_business_section_to_api_fields(
    index_path: str | Path,
    source_doc: str | Path,
    section_title: str,
    top_k: int = 8,
) -> dict:
    entries = load_api_entries(index_path)
    section = parse_business_section_from_file(str(source_doc), section_title)
    return match_section(entries, section, top_k=top_k).to_dict()
