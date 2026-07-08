from __future__ import annotations

from .matcher import match_api_requirement, match_business_fields
from .models import ApiDocEntry, ApiMatch, SectionContext, SectionMatchResult, StrategyResult


def _entry_by_id(entries: list[ApiDocEntry]) -> dict[str, ApiDocEntry]:
    return {entry.api_id: entry for entry in entries}


def _coverage_for_api_ids(
    entries: list[ApiDocEntry],
    section: SectionContext,
    api_ids: list[str],
    source_strategy: str,
) -> float:
    return match_business_fields(
        entries,
        section.output_fields,
        api_ids=api_ids,
        source_strategy=source_strategy,
    ).business_field_coverage_score


def _verified_status_score(status: str) -> float:
    if status == "success":
        return 1.0
    if status == "empty":
        return 0.6
    if status == "unverified":
        return 0.4
    return 0.1


def _param_readiness_score(match: ApiMatch) -> float:
    if not match.missing_params:
        return 1.0
    return max(0.0, 1.0 - min(len(match.missing_params), 8) / 8)


def _union_matches(*groups: list[ApiMatch]) -> list[ApiMatch]:
    seen: dict[str, ApiMatch] = {}
    for group in groups:
        for match in group:
            if match.api_id not in seen or match.score > seen[match.api_id].score:
                seen[match.api_id] = match
    return list(seen.values())


def _rerank_candidates(
    entries: list[ApiDocEntry],
    section: SectionContext,
    candidates: list[ApiMatch],
    top_k: int,
) -> list[ApiMatch]:
    reranked: list[ApiMatch] = []
    for match in candidates:
        coverage = _coverage_for_api_ids(entries, section, [match.api_id], "field_coverage_rerank")
        verified = _verified_status_score(match.verified_status)
        param = _param_readiness_score(match)
        final_score = 0.45 * match.score + 0.35 * coverage + 0.10 * verified + 0.10 * param
        reranked.append(
            ApiMatch(
                api_id=match.api_id,
                name=match.name,
                method=match.method,
                path=match.path,
                score=round(final_score, 4),
                verified_status=match.verified_status,
                reasons=[
                    *match.reasons,
                    f"field_coverage={coverage:.4f}",
                    f"verified_score={verified:.2f}",
                    f"param_readiness={param:.2f}",
                ],
                missing_params=match.missing_params,
                risks=match.risks,
            )
        )
    reranked.sort(key=lambda item: (-item.score, item.api_id))
    return reranked[:top_k]


def _greedy_select_apis(entries: list[ApiDocEntry], section: SectionContext, candidates: list[ApiMatch]) -> list[str]:
    selected: list[str] = []
    best_score = 0.0
    for candidate in candidates:
        if len(selected) >= 5:
            break
        trial = [*selected, candidate.api_id]
        trial_score = _coverage_for_api_ids(entries, section, trial, "field_coverage_rerank")
        if not selected or trial_score > best_score:
            selected.append(candidate.api_id)
            best_score = trial_score
    return selected


def match_section(entries: list[ApiDocEntry], section: SectionContext, top_k: int = 8) -> SectionMatchResult:
    title_matches = match_api_requirement(entries, section.title, top_k=top_k)
    enriched_matches = match_api_requirement(entries, section.enriched_query(), top_k=top_k)
    candidates = _union_matches(title_matches, enriched_matches)
    reranked_matches = _rerank_candidates(entries, section, candidates, top_k=top_k)
    selected_api_ids = _greedy_select_apis(entries, section, reranked_matches)

    title_selected = [match.api_id for match in title_matches[: min(5, len(title_matches))]]
    enriched_selected = [match.api_id for match in enriched_matches[: min(5, len(enriched_matches))]]
    field_mapping = match_business_fields(
        entries,
        section.output_fields,
        api_ids=selected_api_ids,
        source_strategy="field_coverage_rerank",
    )
    strategy_field_mappings = {
        "title_only": match_business_fields(
            entries,
            section.output_fields,
            api_ids=title_selected,
            source_strategy="title_only",
        ),
        "enriched_context": match_business_fields(
            entries,
            section.output_fields,
            api_ids=enriched_selected,
            source_strategy="enriched_context",
        ),
        "field_coverage_rerank": field_mapping,
    }
    strategy_results = {
        "title_only": StrategyResult(
            strategy="title_only",
            api_candidates=title_matches,
            selected_api_ids=title_selected,
            business_field_coverage_score=strategy_field_mappings["title_only"].business_field_coverage_score,
        ),
        "enriched_context": StrategyResult(
            strategy="enriched_context",
            api_candidates=enriched_matches,
            selected_api_ids=enriched_selected,
            business_field_coverage_score=strategy_field_mappings["enriched_context"].business_field_coverage_score,
        ),
        "field_coverage_rerank": StrategyResult(
            strategy="field_coverage_rerank",
            api_candidates=reranked_matches,
            selected_api_ids=selected_api_ids,
            business_field_coverage_score=field_mapping.business_field_coverage_score,
        ),
    }
    missing_or_derived = [
        {
            "field": match.business_field,
            "status": match.status,
            "reason": match.missing_reason,
        }
        for match in field_mapping.matches
        if match.status in {"missing", "derived_or_manual_required"}
    ]
    return SectionMatchResult(
        section_context=section,
        strategy_results=strategy_results,
        field_mapping=field_mapping,
        business_field_coverage_score=field_mapping.business_field_coverage_score,
        missing_or_derived_fields=missing_or_derived,
        strategy_field_mappings=strategy_field_mappings,
    )
