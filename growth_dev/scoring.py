from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import AdapterResult, XhsNote
from .utils import clamp, parse_count


@dataclass(slots=True)
class FieldCoverage:
    title: float = 0.0
    body: float = 0.0
    author: float = 0.0
    counts: float = 0.0
    media: float = 0.0
    comments: float = 0.0
    replies: float = 0.0

    def average(self) -> float:
        values = [self.title, self.body, self.author, self.counts, self.media, self.comments, self.replies]
        return sum(values) / len(values)


@dataclass(slots=True)
class NoteScore:
    note_id: str
    coverage: FieldCoverage
    missing_fields: list[str] = field(default_factory=list)
    completeness: float = 0.0


@dataclass(slots=True)
class FrameworkScore:
    framework: str
    status: str
    run_success: float
    completeness: float
    risk_friendliness: float
    stability: float
    maintainability: float
    total_score: float
    metrics: dict[str, Any] = field(default_factory=dict)


def validate_note_payload(payload: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    required_top_level = ["note_id", "url", "title", "body", "author", "counts", "media", "comments", "extraction_meta"]
    for key in required_top_level:
        if key not in payload:
            problems.append(f"missing:{key}")

    author = payload.get("author", {})
    if not isinstance(author, dict) or not author.get("display_name") or not author.get("profile_url"):
        problems.append("author")

    counts = payload.get("counts", {})
    if not isinstance(counts, dict):
        problems.append("counts")
    else:
        for key in ("likes", "collects", "comments", "shares"):
            if key not in counts:
                problems.append(f"counts.{key}")

    media = payload.get("media", [])
    if not isinstance(media, list):
        problems.append("media")

    comments = payload.get("comments", [])
    if not isinstance(comments, list):
        problems.append("comments")

    return problems


def coverage_for_notes(expected: XhsNote, actual: XhsNote) -> FieldCoverage:
    coverage = FieldCoverage(
        title=1.0 if actual.title.strip() else 0.0,
        body=1.0 if actual.body.strip() else 0.0,
        author=1.0 if actual.author.display_name.strip() and actual.author.profile_url.strip() else 0.0,
        counts=1.0 if all(
            getattr(actual.counts, field) >= 0 for field in ("likes", "collects", "comments", "shares")
        ) else 0.0,
        media=clamp(len(actual.media) / max(1, len(expected.media))),
        comments=clamp(len(actual.comments) / max(1, len(expected.comments))),
        replies=clamp(actual.total_reply_count / max(1, expected.total_reply_count)),
    )
    return coverage


def note_score(expected: XhsNote, actual: XhsNote) -> NoteScore:
    coverage = coverage_for_notes(expected, actual)
    missing = []
    if coverage.title < 1.0:
        missing.append("title")
    if coverage.body < 1.0:
        missing.append("body")
    if coverage.author < 1.0:
        missing.append("author")
    if coverage.media < 1.0:
        missing.append("media")
    if coverage.comments < 1.0:
        missing.append("comments")
    if coverage.replies < 1.0 and expected.total_reply_count > 0:
        missing.append("replies")
    return NoteScore(note_id=expected.note_id, coverage=coverage, missing_fields=missing, completeness=coverage.average())


def framework_score(result: AdapterResult, expected_notes: list[XhsNote]) -> FrameworkScore:
    expected_by_id = {note.note_id: note for note in expected_notes}
    scored_notes: list[NoteScore] = []
    for note in result.notes:
        expected = expected_by_id.get(note.note_id)
        if expected is None:
            continue
        scored_notes.append(note_score(expected, note))

    completeness = sum(item.completeness for item in scored_notes) / max(1, len(scored_notes))
    run_success = 1.0 if result.status == "success" else 0.0
    risk_friendliness = clamp(1.0 - min(1.0, len(result.risk_events) / 3.0))
    stability = clamp(1.0 - min(1.0, result.metrics.crash_count / 3.0))
    maintainability = clamp(1.0 - min(1.0, result.metrics.token_cost / 10000.0))
    total_score = round(
        (run_success * 0.25)
        + (completeness * 0.35)
        + (risk_friendliness * 0.2)
        + (stability * 0.1)
        + (maintainability * 0.1),
        4,
    )
    return FrameworkScore(
        framework=result.framework,
        status=result.status,
        run_success=run_success,
        completeness=completeness,
        risk_friendliness=risk_friendliness,
        stability=stability,
        maintainability=maintainability,
        total_score=total_score,
        metrics={
            "elapsed_ms": result.metrics.elapsed_ms,
            "retry_count": result.metrics.retry_count,
            "crash_count": result.metrics.crash_count,
            "manual_interventions": result.metrics.manual_interventions,
            "token_cost": result.metrics.token_cost,
        },
    )


def summary_table(rows: list[FrameworkScore]) -> list[dict[str, Any]]:
    table: list[dict[str, Any]] = []
    for row in rows:
        table.append(
            {
                "framework": row.framework,
                "status": row.status,
                "total_score": row.total_score,
                "completeness": round(row.completeness, 4),
                "risk_friendliness": round(row.risk_friendliness, 4),
                "stability": round(row.stability, 4),
                "maintainability": round(row.maintainability, 4),
                "elapsed_ms": row.metrics.get("elapsed_ms", 0),
                "token_cost": row.metrics.get("token_cost", 0.0),
            }
        )
    return table


def expected_note_ids(keyword: str, top_n: int, candidate_pool: int) -> list[str]:
    cards = sort_cards_by_comments(build_candidate_cards(keyword, candidate_pool=candidate_pool))
    return [card.note.note_id for card in cards[:top_n]]

