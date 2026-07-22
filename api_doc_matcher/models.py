from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ApiParam:
    name: str
    type: str = ""
    required: bool = False
    description: str = ""
    position: str = "body"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApiParam":
        return cls(
            name=str(data.get("name", "")),
            type=str(data.get("type", "")),
            required=bool(data.get("required", False)),
            description=str(data.get("description", "")),
            position=str(data.get("position", "body")),
        )


@dataclass(slots=True)
class ApiField:
    path: str
    name: str
    type: str = ""
    description: str = ""
    source: str = "detail_doc"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApiField":
        return cls(
            path=str(data.get("path", "")),
            name=str(data.get("name", "")),
            type=str(data.get("type", "")),
            description=str(data.get("description", "")),
            source=str(data.get("source", "detail_doc")),
        )


@dataclass(slots=True)
class BusinessField:
    name: str
    description: str = ""
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_any(cls, value: Any) -> "BusinessField":
        if isinstance(value, BusinessField):
            return value
        if isinstance(value, dict):
            return cls(
                name=str(value.get("name", "")),
                description=str(value.get("description", "")),
                required=bool(value.get("required", True)),
            )
        return cls(name=str(value))


@dataclass(slots=True)
class SectionContext:
    title: str
    purpose: str = ""
    data_sources: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    output_fields: list[BusinessField] = field(default_factory=list)
    source_path: str = ""

    def enriched_query(self) -> str:
        return " ".join(
            [
                self.title,
                self.purpose,
                " ".join(self.data_sources),
                " ".join(self.actions),
            ]
        ).strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "purpose": self.purpose,
            "data_sources": self.data_sources,
            "actions": self.actions,
            "output_fields": [field_item.to_dict() for field_item in self.output_fields],
            "source_path": self.source_path,
        }


@dataclass(slots=True)
class DetailApiEntry:
    api_id: str
    method: str
    path: str
    api_name: str = ""
    verified_status: str = "unverified"
    verified_url_path: str = ""
    response_root: str = "data.result[]"
    default_params: dict[str, Any] = field(default_factory=dict)
    source_path: str = ""
    source_line_no: int = 0
    request_params: list[ApiParam] = field(default_factory=list)
    request_headers: list[str] = field(default_factory=list)
    response_fields: list[ApiField] = field(default_factory=list)
    response_examples: list[dict[str, Any]] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["request_params"] = [p.to_dict() for p in self.request_params]
        out["response_fields"] = [f.to_dict() for f in self.response_fields]
        return out


@dataclass(slots=True)
class ValidationEntry:
    api_id: str
    source_seq: int
    module: str
    business_module: str
    analysis_domain: str
    name: str
    method: str
    path: str
    verified_status: str
    verified_url_path: str
    body_template: dict[str, Any]
    verified_msg: str = ""
    source_path: str = ""
    source_line_no: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ApiDocEntry:
    api_id: str
    source_seq: int | None
    name: str
    module: str
    business_module: str
    analysis_domain: str
    method: str
    path: str
    verified_status: str
    verified_url_path: str = ""
    response_root: str = "data.result[]"
    default_params: dict[str, Any] = field(default_factory=dict)
    request_params: list[ApiParam] = field(default_factory=list)
    request_headers: list[str] = field(default_factory=list)
    response_fields: list[ApiField] = field(default_factory=list)
    source_refs: dict[str, Any] = field(default_factory=dict)
    parse_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["request_params"] = [p.to_dict() for p in self.request_params]
        out["response_fields"] = [f.to_dict() for f in self.response_fields]
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApiDocEntry":
        return cls(
            api_id=str(data.get("api_id", "")),
            source_seq=data.get("source_seq"),
            name=str(data.get("name", "")),
            module=str(data.get("module", "")),
            business_module=str(data.get("business_module", "")),
            analysis_domain=str(data.get("analysis_domain", "")),
            method=str(data.get("method", "")),
            path=str(data.get("path", "")),
            verified_status=str(data.get("verified_status", "")),
            verified_url_path=str(data.get("verified_url_path", "")),
            response_root=str(data.get("response_root", "data.result[]")),
            default_params=dict(data.get("default_params", {})) if isinstance(data.get("default_params"), dict) else {},
            request_params=[ApiParam.from_dict(p) for p in data.get("request_params", [])],
            request_headers=[str(h) for h in data.get("request_headers", [])],
            response_fields=[ApiField.from_dict(f) for f in data.get("response_fields", [])],
            source_refs=dict(data.get("source_refs", {})),
            parse_warnings=[str(w) for w in data.get("parse_warnings", [])],
        )


@dataclass(slots=True)
class ApiMatch:
    api_id: str
    name: str
    method: str
    path: str
    score: float
    verified_status: str
    reasons: list[str] = field(default_factory=list)
    missing_params: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FieldMatch:
    business_field: str
    status: str
    confidence: float
    field_description: str = ""
    api_id: str = ""
    api_name: str = ""
    api_field_path: str = ""
    api_field_name: str = ""
    api_field_type: str = ""
    match_basis: str = ""
    source_strategy: str = ""
    candidate_api_ids: list[str] = field(default_factory=list)
    missing_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FieldMatchResult:
    matches: list[FieldMatch]
    business_field_coverage_score: float
    required_total: int
    covered_required: int
    high_confidence: int
    confirmed_or_reviewable: int
    missing_required_fields: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "matches": [m.to_dict() for m in self.matches],
            "business_field_coverage_score": self.business_field_coverage_score,
            "required_total": self.required_total,
            "covered_required": self.covered_required,
            "high_confidence": self.high_confidence,
            "confirmed_or_reviewable": self.confirmed_or_reviewable,
            "missing_required_fields": self.missing_required_fields,
        }


@dataclass(slots=True)
class StrategyResult:
    strategy: str
    api_candidates: list[ApiMatch]
    selected_api_ids: list[str] = field(default_factory=list)
    business_field_coverage_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "api_candidates": [match.to_dict() for match in self.api_candidates],
            "selected_api_ids": self.selected_api_ids,
            "business_field_coverage_score": self.business_field_coverage_score,
        }


@dataclass(slots=True)
class SectionMatchResult:
    section_context: SectionContext
    strategy_results: dict[str, StrategyResult]
    field_mapping: FieldMatchResult
    business_field_coverage_score: float
    missing_or_derived_fields: list[dict[str, Any]]
    strategy_field_mappings: dict[str, FieldMatchResult] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "section-api-field-match-v1",
            "section_context": self.section_context.to_dict(),
            "strategy_results": {key: value.to_dict() for key, value in self.strategy_results.items()},
            "field_mapping": self.field_mapping.to_dict(),
            "strategy_field_mappings": {
                key: value.to_dict()
                for key, value in self.strategy_field_mappings.items()
            },
            "business_field_coverage_score": self.business_field_coverage_score,
            "missing_or_derived_fields": self.missing_or_derived_fields,
        }


@dataclass(slots=True)
class ParseResult:
    entries: list[Any]
    failures: list[dict[str, Any]] = field(default_factory=list)
    source_path: str = ""


@dataclass(slots=True)
class BuildIndexResult:
    api_entries: list[ApiDocEntry]
    field_entries: list[dict[str, Any]]
    join_hit_count: int
    join_miss_count: int
    orphan_detail_count: int
    output_dir: str

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "api_count": len(self.api_entries),
            "field_count": len(self.field_entries),
            "join_hit_count": self.join_hit_count,
            "join_miss_count": self.join_miss_count,
            "orphan_detail_count": self.orphan_detail_count,
            "output_dir": self.output_dir,
        }
