from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from ..utils import ensure_dir, now_iso, read_json, write_json
from .retrospective import ensure_run_retrospective


ACTIVE_SKILL_IDS = {
    "using_agent_skills",
    "spec_driven_development",
    "context_engineering",
    "planning_and_task_breakdown",
    "incremental_implementation",
    "test_driven_development",
    "debugging_and_error_recovery",
    "code_review_and_quality",
}

SECRET_REPLACEMENTS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{6,}"), "<redacted-secret>"),
    (re.compile(r"(?i)(AICODEMIRROR_KEY\s*[:=]\s*)[^\s,;'\"\n]+"), r"\1<redacted>"),
    (re.compile(r"(?i)((api[_-]?key|secret|token|password)\s*[:=]\s*)[^\s,;'\"\n]+"), r"\1<redacted>"),
    (re.compile(r"\.env(?:/[A-Za-z0-9_\-]+)?"), "<env-file>"),
]


def search_memory(
    query: str,
    *,
    runs_dir: Path = Path("runs"),
    domain_id: str = "",
    task_type: str = "",
    limit: int = 5,
    refresh_missing: bool = False,
    exclude_run_id: str = "",
) -> dict[str, Any]:
    runs_path = Path(runs_dir)
    summaries = _load_summaries(runs_path, refresh_missing=refresh_missing, exclude_run_id=exclude_run_id)
    query_tokens = _tokens(" ".join([query, domain_id, task_type]))
    scored: list[dict[str, Any]] = []
    for summary in summaries:
        match = _score_summary(summary, query_tokens, domain_id=domain_id, task_type=task_type)
        if match["score"] <= 0:
            continue
        scored.append(match)
    scored.sort(key=lambda item: (item["score"], item["run_id"]), reverse=True)
    matches = scored[: max(limit, 0)]
    result = {
        "schema_version": 1,
        "query": _redact_text(query),
        "run_id": "",
        "domain_id": _redact_text(domain_id),
        "generated_at": now_iso(),
        "matches": matches,
        "recommended_skills": _aggregate_skills(matches),
        "context_strategy": _context_strategy(matches),
    }
    return _redact_payload(result)


def generate_memory_recall(
    query: str,
    *,
    run_id: str,
    runs_dir: Path = Path("runs"),
    domain_id: str = "",
    task_type: str = "",
    limit: int = 5,
    refresh_missing: bool = False,
) -> dict[str, Any]:
    run_dir = _safe_run_dir(Path(runs_dir), run_id)
    ensure_dir(run_dir)
    result = search_memory(
        query,
        runs_dir=runs_dir,
        domain_id=domain_id,
        task_type=task_type,
        limit=limit,
        refresh_missing=refresh_missing,
        exclude_run_id=run_id,
    )
    result["run_id"] = run_id
    result["domain_id"] = domain_id or result.get("domain_id", "")
    write_json(run_dir / "memory_recall.json", result)
    (run_dir / "memory_recall.md").write_text(memory_recall_markdown(result), encoding="utf-8")
    return {
        "run_id": run_id,
        "artifacts": {
            "memory_recall": "memory_recall.md",
            "memory_recall_json": "memory_recall.json",
        },
        "memory_recall": result,
    }


def memory_recall_markdown(result: dict[str, Any]) -> str:
    matches = result.get("matches") if isinstance(result.get("matches"), list) else []
    skills = result.get("recommended_skills") if isinstance(result.get("recommended_skills"), list) else []
    strategy = result.get("context_strategy") if isinstance(result.get("context_strategy"), dict) else {}
    lines = [
        f"# Historical Task Recall: {result.get('run_id') or result.get('query', '')}",
        "",
        "## 查询",
        "",
        f"- Query: {_inline_code(result.get('query', ''))}",
        f"- Domain: {_inline_code(result.get('domain_id', ''))}",
        "",
        "## 相似历史任务",
        "",
    ]
    if not matches:
        lines.append("- 暂无相似历史任务。")
    else:
        for match in matches:
            reasons = ", ".join(str(item) for item in match.get("reasons", [])) or "matched"
            lines.append(
                f"- {_inline_code(match.get('run_id', ''))} "
                f"score={match.get('score', 0):.2f} "
                f"domain={_inline_code(match.get('domain_id', ''))} "
                f"task={_inline_code(match.get('task_type', ''))} "
                f"reasons={_inline_code(reasons)}"
            )
    lines.extend(["", "## 推荐 Project Skills", ""])
    if not skills:
        lines.append("- 暂无推荐 skill。")
    else:
        for skill in skills:
            lines.append(
                f"- {_inline_code(skill.get('id', ''))} "
                f"confidence={skill.get('confidence', 0):.2f} "
                f"source={', '.join(skill.get('source_run_ids', []))}：{skill.get('why', '')}"
            )
    lines.extend(["", "## 下次上下文策略", ""])
    lines.extend(_strategy_lines("可复用上下文", strategy.get("reuse", [])))
    lines.extend(_strategy_lines("避免注入", strategy.get("avoid", [])))
    lines.extend(_strategy_lines("下次检查", strategy.get("checklist", [])))
    return "\n".join(lines).rstrip() + "\n"


def format_memory_search_result(result: dict[str, Any]) -> str:
    lines = [
        f"历史任务召回: {result.get('query', '')}",
        "",
        "相似历史任务:",
    ]
    matches = result.get("matches") if isinstance(result.get("matches"), list) else []
    if not matches:
        lines.append("- 暂无匹配结果。")
    else:
        for match in matches:
            lines.append(
                f"- {match.get('run_id', '')} score={match.get('score', 0):.2f} "
                f"domain={match.get('domain_id', '')} task={match.get('task_type', '')}"
            )
    lines.extend(["", "推荐 Project Skills:"])
    skills = result.get("recommended_skills") if isinstance(result.get("recommended_skills"), list) else []
    if not skills:
        lines.append("- 暂无推荐 skill。")
    else:
        for skill in skills:
            lines.append(f"- {skill.get('id', '')} confidence={skill.get('confidence', 0):.2f} {skill.get('why', '')}")
    strategy = result.get("context_strategy") if isinstance(result.get("context_strategy"), dict) else {}
    lines.extend(["", "上下文策略:"])
    lines.extend(_plain_list("复用", strategy.get("reuse", [])))
    lines.extend(_plain_list("避免", strategy.get("avoid", [])))
    lines.extend(_plain_list("检查", strategy.get("checklist", [])))
    return "\n".join(lines).rstrip() + "\n"


def _load_summaries(runs_dir: Path, *, refresh_missing: bool, exclude_run_id: str) -> list[dict[str, Any]]:
    if not runs_dir.exists():
        return []
    summaries: list[dict[str, Any]] = []
    for run_dir in sorted((item for item in runs_dir.iterdir() if item.is_dir()), key=lambda item: item.stat().st_mtime_ns, reverse=True):
        if run_dir.name == exclude_run_id:
            continue
        summary_path = run_dir / "learning_summary.json"
        if not summary_path.exists() and refresh_missing and (run_dir / "team_run_record.json").exists():
            try:
                ensure_run_retrospective(run_dir.name, runs_dir=runs_dir)
            except Exception:
                pass
        if not summary_path.exists():
            continue
        payload = _safe_json(summary_path)
        if isinstance(payload, dict):
            summaries.append(payload)
    return summaries


def _score_summary(summary: dict[str, Any], query_tokens: set[str], *, domain_id: str, task_type: str) -> dict[str, Any]:
    corpus = _summary_corpus(summary)
    corpus_tokens = _tokens(corpus)
    overlap = sorted(query_tokens & corpus_tokens)
    score = 0.0
    reasons: list[str] = []
    if domain_id and str(summary.get("domain_id", "")) == domain_id:
        score += 0.35
        reasons.append("same_domain")
    if task_type and str(summary.get("task_type", "")) == task_type:
        score += 0.25
        reasons.append("same_task_type")
    if overlap:
        score += min(0.45, len(overlap) * 0.08)
        reasons.append("matched_query_terms")
    if any(token in _tokens(" ".join(_list(summary.get("reusable_context")))) for token in query_tokens):
        score += 0.12
        reasons.append("matched_reusable_context")
    if any(token in _tokens(" ".join(_list(_nested(summary, "implementation_findings", "changed_files")))) for token in query_tokens):
        score += 0.12
        reasons.append("matched_changed_files")
    if str(summary.get("outcome", "")) == "accepted_and_verified":
        score += 0.06
        reasons.append("accepted_history")
    return {
        "run_id": str(summary.get("run_id", "")),
        "domain_id": str(summary.get("domain_id", "")),
        "task_type": str(summary.get("task_type", "")),
        "status": str(summary.get("status", "")),
        "outcome": str(summary.get("outcome", "")),
        "score": round(min(score, 1.0), 3),
        "reasons": _dedupe(reasons),
        "recommended_skills": [skill for skill in _list(summary.get("recommended_skills")) if skill in ACTIVE_SKILL_IDS],
        "reusable_context": _safe_context_list(summary.get("reusable_context")),
        "avoid_context": _safe_context_list(summary.get("avoid_context")),
        "failure_modes": _safe_context_list(summary.get("failure_modes")),
        "source_artifacts": _safe_context_list(summary.get("source_artifacts")),
    }


def _aggregate_skills(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    scores: dict[str, float] = {}
    sources: dict[str, list[str]] = {}
    for match in matches:
        for skill in match.get("recommended_skills", []):
            if skill not in ACTIVE_SKILL_IDS:
                continue
            counts[skill] += 1
            scores[skill] = scores.get(skill, 0.0) + float(match.get("score", 0) or 0)
            sources.setdefault(skill, []).append(str(match.get("run_id", "")))
    result: list[dict[str, Any]] = []
    for skill, count in counts.most_common():
        confidence = min(1.0, scores.get(skill, 0.0) / max(1, len(matches)))
        result.append(
            {
                "id": skill,
                "confidence": round(confidence, 3),
                "source_run_ids": _dedupe([item for item in sources.get(skill, []) if item]),
                "why": _skill_reason(skill, count),
            }
        )
    return result


def _context_strategy(matches: list[dict[str, Any]]) -> dict[str, list[str]]:
    reuse: list[str] = []
    avoid: list[str] = []
    checklist: list[str] = []
    for match in matches:
        reuse.extend(_list(match.get("reusable_context")))
        avoid.extend(_list(match.get("avoid_context")))
        if match.get("failure_modes"):
            checklist.append("先检查历史失败模式是否会在本次任务复现。")
        if match.get("run_id"):
            checklist.append(f"参考 `{match.get('run_id')}` 的验收证据和上下文边界。")
    return {
        "reuse": _dedupe(_safe_context_list(reuse))[:10],
        "avoid": _dedupe(_safe_context_list(avoid))[:10],
        "checklist": _dedupe(_safe_context_list(checklist))[:10],
    }


def _summary_corpus(summary: dict[str, Any]) -> str:
    fields: list[str] = [
        str(summary.get("run_id", "")),
        str(summary.get("domain_id", "")),
        str(summary.get("task_type", "")),
        str(summary.get("outcome", "")),
    ]
    fields.extend(_list(summary.get("failure_modes")))
    fields.extend(_list(summary.get("recommended_skills")))
    fields.extend(_list(summary.get("reusable_context")))
    fields.extend(_list(summary.get("avoid_context")))
    fields.extend(_list(summary.get("next_time_checklist")))
    for section in ("quality_findings", "implementation_findings", "review_test_findings"):
        value = summary.get(section)
        if isinstance(value, dict):
            fields.append(json.dumps(value, ensure_ascii=False))
    return " ".join(fields)


def _tokens(text: str) -> set[str]:
    lowered = str(text).lower()
    ascii_tokens = re.findall(r"[a-z0-9_]{2,}", lowered)
    cjk_tokens = re.findall(r"[\u4e00-\u9fff]{2,}", lowered)
    cjk_bigrams: list[str] = []
    for token in cjk_tokens:
        cjk_bigrams.extend(token[index : index + 2] for index in range(max(0, len(token) - 1)))
    return set(ascii_tokens + cjk_tokens + cjk_bigrams)


def _nested(payload: dict[str, Any], key: str, nested_key: str) -> Any:
    value = payload.get(key)
    if not isinstance(value, dict):
        return []
    return value.get(nested_key, [])


def _safe_context_list(value: Any) -> list[str]:
    return [_redact_text(item) for item in _list(value) if _is_safe_summary_value(item)]


def _is_safe_summary_value(value: str) -> bool:
    text = str(value).lower()
    if "raw diff line" in text or "raw-log" in text:
        return False
    return True


def _list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _safe_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}


def _safe_run_dir(runs_dir: Path, run_id: str) -> Path:
    base = Path(runs_dir).resolve()
    target = (base / run_id).resolve()
    if base != target and base not in target.parents:
        raise ValueError("Run id escapes runs directory.")
    return target


def _strategy_lines(title: str, values: Any) -> list[str]:
    lines = [f"### {title}"]
    items = _list(values)
    if not items:
        lines.append("- 暂无。")
    else:
        lines.extend(f"- {_inline_code(item)}" for item in items[:10])
    return lines + [""]


def _plain_list(title: str, values: Any) -> list[str]:
    items = _list(values)
    if not items:
        return [f"- {title}: 暂无"]
    return [f"- {title}: {', '.join(items[:6])}"]


def _skill_reason(skill: str, count: int) -> str:
    reasons = {
        "context_engineering": "历史相似任务提示需要先收窄上下文。",
        "code_review_and_quality": "历史相似任务需要保留独立 Review 和质量证据。",
        "test_driven_development": "历史相似任务依赖测试验收来确认结果。",
        "debugging_and_error_recovery": "历史相似任务出现失败模式，需要先分类再修复。",
        "incremental_implementation": "历史相似任务适合小步实现和可回滚变更。",
        "planning_and_task_breakdown": "历史相似任务需要先拆成可验收任务。",
        "spec_driven_development": "历史相似任务需要先明确规格和边界。",
        "using_agent_skills": "历史相似任务需要先进行 skill 路由。",
    }
    suffix = f"（来自 {count} 个相似 run）"
    return reasons.get(skill, "历史相似任务推荐使用该 skill。") + suffix


def _inline_code(value: Any) -> str:
    return f"`{_redact_text(str(value))}`"


def _redact_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {str(key): _redact_payload(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_redact_payload(item) for item in payload]
    if isinstance(payload, str):
        return _redact_text(payload)
    return payload


def _redact_text(value: str) -> str:
    redacted = str(value)
    for pattern, replacement in SECRET_REPLACEMENTS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
