from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..utils import ensure_dir, read_json
from .models import TeamRunRecord
from .retrospective import ensure_run_retrospective


MEMORY_ROOT_NAME = "AI Coding Memory"

BUSINESS_ARTIFACTS = [
    ("task.yaml", "任务包"),
    ("context.md", "上下文"),
    ("prd.md", "PRD"),
    ("tech_spec.md", "技术方案"),
    ("ui_spec.md", "UI 方案"),
    ("eval.md", "验收标准"),
    ("coding_prompt.md", "Coding Prompt"),
    ("review_report.md", "Review 报告"),
    ("test_report.md", "测试报告"),
    ("final_report.md", "最终报告"),
]

EVIDENCE_ARTIFACTS = [
    ("codex/diff.patch", "代码 diff"),
    ("codex/git_status.txt", "Git 状态"),
    ("codex/stdout.jsonl", "Codex stdout"),
    ("codex/stderr.log", "Codex stderr"),
    ("codex/reviewer_stdout.log", "Review stdout"),
    ("codex/reviewer_stderr.log", "Review stderr"),
    ("codex/verification_record.json", "验证记录"),
]

AGENT_LABELS = {
    "orchestrator": "需求理解",
    "product": "产品方案",
    "architect": "技术方案",
    "ux": "交互方案",
    "qa": "验收设计",
    "coder": "AI 实现",
    "reviewer": "代码 Review",
    "verifier": "测试验证",
    "publisher": "交付报告",
}

SECRET_REPLACEMENTS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{6,}"), lambda match: "<redacted-secret>"),
    (re.compile(r"(?i)(AICODEMIRROR_KEY\s*[:=]\s*)[^\s,;'\"]+"), lambda match: f"{match.group(1)}<redacted>"),
    (
        re.compile(r"(?i)((api[_-]?key|secret|token|password)\s*[:=]\s*)[^\s,;'\"]+"),
        lambda match: f"{match.group(1)}<redacted>",
    ),
]


def export_run_to_obsidian(run_id: str, *, runs_dir: Path = Path("runs"), vault_dir: Path) -> dict[str, Any]:
    runs_path = Path(runs_dir)
    record, run_dir = _load_record(run_id, runs_path)
    ensure_run_retrospective(record.run_id, runs_dir=runs_path)
    memory_root = _memory_root(vault_dir)
    written = [_write_run_note(record, run_dir, memory_root)]
    written.extend(_regenerate_indexes(memory_root))
    return _result([record.run_id], memory_root, written)


def export_recent_runs_to_obsidian(*, runs_dir: Path = Path("runs"), vault_dir: Path, limit: int = 50) -> dict[str, Any]:
    runs_path = Path(runs_dir)
    records = _discover_records(runs_path)
    selected = records[: max(limit, 0)]
    memory_root = _memory_root(vault_dir)
    written: list[Path] = []
    run_ids: list[str] = []
    for record, run_dir in selected:
        ensure_run_retrospective(record.run_id, runs_dir=runs_path)
        written.append(_write_run_note(record, run_dir, memory_root))
        run_ids.append(record.run_id)
    written.extend(_regenerate_indexes(memory_root))
    return _result(run_ids, memory_root, written)


def _load_record(run_id: str, runs_dir: Path) -> tuple[TeamRunRecord, Path]:
    run_dir = runs_dir / run_id
    record_path = run_dir / "team_run_record.json"
    if not record_path.exists():
        raise FileNotFoundError(f"team_run_record.json not found: {record_path}")
    record = TeamRunRecord.from_dict(read_json(record_path))
    return record, run_dir


def _discover_records(runs_dir: Path) -> list[tuple[TeamRunRecord, Path]]:
    if not runs_dir.exists():
        return []
    records: list[tuple[TeamRunRecord, Path]] = []
    for run_dir in runs_dir.iterdir():
        record_path = run_dir / "team_run_record.json"
        if not record_path.exists():
            continue
        record = TeamRunRecord.from_dict(read_json(record_path))
        records.append((record, run_dir))
    records.sort(key=lambda item: _recency_key(item[0], item[1]), reverse=True)
    return records


def _recency_key(record: TeamRunRecord, run_dir: Path) -> str:
    if record.started_at:
        return record.started_at
    if record.finished_at:
        return record.finished_at
    return str(run_dir.stat().st_mtime_ns)


def _memory_root(vault_dir: Path) -> Path:
    root = Path(vault_dir) / MEMORY_ROOT_NAME
    ensure_dir(root / "Runs")
    ensure_dir(root / "Timeline")
    ensure_dir(root / "Domains")
    return root


def _write_run_note(record: TeamRunRecord, run_dir: Path, memory_root: Path) -> Path:
    note_path = memory_root / "Runs" / f"{_safe_file_stem(record.run_id)}.md"
    note_path.write_text(_run_note(record, run_dir), encoding="utf-8")
    return note_path


def _run_note(record: TeamRunRecord, run_dir: Path) -> str:
    changed_files = [_redact(value) for value in _changed_files(record)]
    risk_events = [_redact(value) for value in _risk_events(record)]
    lines = [
        "---",
        f"run_id: {_yaml_scalar(record.run_id)}",
        f"domain_id: {_yaml_scalar(record.domain_id)}",
        f"status: {_yaml_scalar(record.status)}",
        f"started_at: {_yaml_scalar(record.started_at)}",
        f"finished_at: {_yaml_scalar(record.finished_at)}",
        f"executor: {_yaml_scalar(record.executor)}",
        f"brief: {_yaml_scalar(_redact(record.brief))}",
        *_yaml_list("changed_files", changed_files),
        *_yaml_list("risk_events", risk_events),
        "tags:",
        "  - ai-coding",
        "  - agent-team-runtime",
        "---",
        "",
        f"# {record.run_id}",
        "",
        f"- Domain: [[Domains/{_safe_file_stem(record.domain_id)}|{record.domain_id}]]",
        f"- Status: `{record.status}`",
        f"- Run directory: [{run_dir.resolve()}]({run_dir.resolve().as_uri()})",
        "",
        "## 本次需求",
        "",
        _redact(record.brief) or "未记录 brief。",
        "",
        "## 阶段时间线",
        "",
        *_agent_timeline(record),
        "",
        "## 产物摘要",
        "",
        *_artifact_summary_lines(run_dir),
        "",
        "## 代码变化摘要",
        "",
        *_changed_file_lines(changed_files, run_dir),
        "",
        "## 质量检查与关卡",
        "",
        *_quality_lines(record, run_dir),
        "",
        "## 风险与阻塞",
        "",
        *_risk_lines(risk_events),
        "",
        "## 可沉淀的经验",
        "",
        *_lesson_lines(record, changed_files, risk_events),
        "",
        "## 任务复盘",
        "",
        *_retrospective_lines(run_dir),
        "",
        "## 推荐 Project Skills",
        "",
        *_recommended_skill_lines(run_dir),
        "",
        "## 下次上下文策略",
        "",
        *_context_strategy_lines(run_dir),
        "",
        "## 本地产物链接",
        "",
        *_artifact_link_lines(run_dir),
        "",
        "## 工程详情",
        "",
        *_executor_lines(record),
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _changed_files(record: TeamRunRecord) -> list[str]:
    files: list[str] = []
    for agent_run in record.agent_runs:
        for key in ("files_changed", "changed_files"):
            value = agent_run.metadata.get(key)
            if isinstance(value, list):
                files.extend(str(item) for item in value)
    return _dedupe(files)


def _risk_events(record: TeamRunRecord) -> list[str]:
    events = list(record.risk_events)
    for agent_run in record.agent_runs:
        events.extend(agent_run.risk_events)
    return _dedupe(events)


def _agent_timeline(record: TeamRunRecord) -> list[str]:
    if not record.agent_runs:
        return ["暂无阶段记录。"]
    lines = ["| 阶段 | 状态 | 摘要 |", "| --- | --- | --- |"]
    for agent_run in record.agent_runs:
        label = AGENT_LABELS.get(agent_run.agent_id, agent_run.agent_id or "未知阶段")
        message = _redact(agent_run.message).replace("|", "\\|") or "-"
        lines.append(f"| {label} | `{agent_run.status}` | {message} |")
    return lines


def _artifact_summary_lines(run_dir: Path) -> list[str]:
    lines: list[str] = []
    for relative_path, label in BUSINESS_ARTIFACTS:
        path = run_dir / relative_path
        if path.exists():
            summary = _summarize_text(path)
            suffix = f"：{summary}" if summary else ""
            lines.append(f"- {label} 已生成{suffix}")
    return lines or ["暂无可展示产物。"]


def _changed_file_lines(changed_files: list[str], run_dir: Path) -> list[str]:
    if not changed_files:
        lines = ["暂无记录的代码变更文件。"]
    else:
        lines = [f"- `{path}`" for path in changed_files]
    diff_path = run_dir / "codex" / "diff.patch"
    if diff_path.exists():
        lines.append(f"- 完整 diff 仅保留为本地链接，不复制到笔记：[{diff_path.name}]({diff_path.resolve().as_uri()})")
    return lines


def _quality_lines(record: TeamRunRecord, run_dir: Path) -> list[str]:
    lines: list[str] = []
    if record.gate_results:
        lines.append("| 关卡 | 状态 | 说明 |")
        lines.append("| --- | --- | --- |")
        for gate in record.gate_results:
            reason = "通过" if gate.status == "passed" else f"缺失：{', '.join(gate.missing_artifacts)}"
            lines.append(f"| `{gate.gate_id}` | `{gate.status}` | {reason} |")
    review = _summarize_text(run_dir / "review_report.md")
    test = _summarize_text(run_dir / "test_report.md")
    if review:
        lines.append(f"- Review：{review}")
    if test:
        lines.append(f"- Test：{test}")
    return lines or ["暂无质量检查记录。"]


def _risk_lines(risk_events: list[str]) -> list[str]:
    if not risk_events:
        return ["暂无记录的风险或阻塞。"]
    return [f"- {_redact(event)}" for event in risk_events]


def _lesson_lines(record: TeamRunRecord, changed_files: list[str], risk_events: list[str]) -> list[str]:
    if record.status == "completed" and not risk_events:
        lines = ["- 本次 run 可作为同类需求从 brief 到交付报告的参考样例。"]
    elif risk_events:
        lines = ["- 后续相似任务应优先检查本次暴露的风险项。"]
    else:
        lines = ["- 本次 run 仍在进行或未完整收敛，适合复盘流程阻塞点。"]
    if changed_files:
        lines.append(f"- 主要影响面：{', '.join(f'`{path}`' for path in changed_files[:5])}")
    return lines


def _retrospective_lines(run_dir: Path) -> list[str]:
    learning = _learning_summary(run_dir)
    if learning:
        return [
            f"- Outcome: `{learning.get('outcome', 'unknown')}`",
            f"- Task type: `{learning.get('task_type', 'unknown')}`",
            f"- Source: [retrospective.md]({(run_dir / 'retrospective.md').resolve().as_uri()})",
        ]
    summary = _summarize_text(run_dir / "retrospective.md")
    return [summary] if summary else ["暂无复盘摘要。"]


def _recommended_skill_lines(run_dir: Path) -> list[str]:
    skills = _learning_summary(run_dir).get("recommended_skills", [])
    if not isinstance(skills, list) or not skills:
        return ["暂无推荐 skill。"]
    return [f"- `{_redact(str(skill))}`" for skill in skills]


def _context_strategy_lines(run_dir: Path) -> list[str]:
    learning = _learning_summary(run_dir)
    reusable = learning.get("reusable_context", [])
    avoid = learning.get("avoid_context", [])
    lines: list[str] = []
    if isinstance(reusable, list) and reusable:
        lines.append("### 可复用上下文")
        lines.extend(f"- `{_redact(str(item))}`" for item in reusable[:8])
    if isinstance(avoid, list) and avoid:
        lines.append("### 避免注入")
        lines.extend(f"- `{_redact(str(item))}`" for item in avoid[:8])
    return lines or ["暂无上下文策略。"]


def _learning_summary(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "learning_summary.json"
    if not path.exists():
        return {}
    payload = read_json(path)
    return payload if isinstance(payload, dict) else {}


def _artifact_link_lines(run_dir: Path) -> list[str]:
    lines = ["### 业务产物"]
    found_business = False
    for relative_path, label in BUSINESS_ARTIFACTS:
        path = run_dir / relative_path
        if path.exists():
            found_business = True
            lines.append(f"- [{label}]({path.resolve().as_uri()})")
    if not found_business:
        lines.append("- 暂无业务产物链接。")
    lines.append("")
    lines.append("### 工程证据（仅链接，不复制内容）")
    found_evidence = False
    for relative_path, label in EVIDENCE_ARTIFACTS:
        path = run_dir / relative_path
        if path.exists():
            found_evidence = True
            lines.append(f"- [{label}]({path.resolve().as_uri()})")
    if not found_evidence:
        lines.append("- 暂无工程证据链接。")
    return lines


def _executor_lines(record: TeamRunRecord) -> list[str]:
    lines = [f"- Executor: `{record.executor}`"]
    config = record.executor_config or {}
    model = config.get("model")
    if model:
        lines.append(f"- Model: `{_redact(str(model))}`")
    provider = config.get("provider")
    if isinstance(provider, dict):
        name = provider.get("name")
        env_key = provider.get("env_key")
        secret_configured = provider.get("secret_configured")
        if name:
            lines.append(f"- Provider: `{_redact(str(name))}`")
        if env_key:
            lines.append(f"- Provider env_key: `{_redact(str(env_key))}`")
        if secret_configured is not None:
            lines.append(f"- Provider secret configured: `{bool(secret_configured)}`")
    return lines


def _summarize_text(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        lines.append(_redact(line))
        if len(lines) >= 2:
            break
    summary = " ".join(lines)
    if len(summary) > 180:
        return summary[:177].rstrip() + "..."
    return summary


def _regenerate_indexes(memory_root: Path) -> list[Path]:
    notes = _read_run_note_index(memory_root)
    written = [
        _write_index(memory_root, notes),
        *_write_timeline_notes(memory_root, notes),
        *_write_domain_notes(memory_root, notes),
    ]
    return written


def _read_run_note_index(memory_root: Path) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    for path in sorted((memory_root / "Runs").glob("*.md")):
        frontmatter = _parse_frontmatter(path)
        if not frontmatter.get("run_id"):
            continue
        frontmatter["note_stem"] = path.stem
        notes.append(frontmatter)
    notes.sort(key=lambda item: str(item.get("started_at") or item.get("finished_at") or ""), reverse=True)
    return notes


def _write_index(memory_root: Path, notes: list[dict[str, Any]]) -> Path:
    path = memory_root / "Index.md"
    lines = [
        "# AI Coding Memory",
        "",
        "这个目录从本地 `runs/<run_id>/` 产物生成，用来复盘项目演进。默认只保存摘要和本地链接，不复制原始日志或完整 diff。",
        "",
        "## 最近运行",
        "",
    ]
    if not notes:
        lines.append("暂无导出的 run。")
    else:
        lines.extend(["| Run | 状态 | Domain | 时间 |", "| --- | --- | --- | --- |"])
        for note in notes:
            lines.append(
                f"| {_run_wikilink(note)} | `{note.get('status', '')}` | "
                f"[[Domains/{_safe_file_stem(str(note.get('domain_id', 'unknown')))}|{note.get('domain_id', '')}]] | "
                f"{note.get('started_at', '')} |"
            )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def _write_timeline_notes(memory_root: Path, notes: list[dict[str, Any]]) -> list[Path]:
    by_month: dict[str, list[dict[str, Any]]] = {}
    for note in notes:
        month = _month_key(str(note.get("started_at") or note.get("finished_at") or "unknown"))
        by_month.setdefault(month, []).append(note)
    written: list[Path] = []
    for month, month_notes in sorted(by_month.items(), reverse=True):
        path = memory_root / "Timeline" / f"{month}.md"
        lines = [
            f"# {month} 项目演进时间线",
            "",
            "| Run | 状态 | Domain | 摘要 |",
            "| --- | --- | --- | --- |",
        ]
        for note in month_notes:
            lines.append(
                f"| {_run_wikilink(note)} | `{note.get('status', '')}` | "
                f"`{note.get('domain_id', '')}` | {_redact(str(note.get('brief', '')))} |"
            )
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        written.append(path)
    return written


def _write_domain_notes(memory_root: Path, notes: list[dict[str, Any]]) -> list[Path]:
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for note in notes:
        domain_id = str(note.get("domain_id") or "unknown")
        by_domain.setdefault(domain_id, []).append(note)
    written: list[Path] = []
    for domain_id, domain_notes in sorted(by_domain.items()):
        path = memory_root / "Domains" / f"{_safe_file_stem(domain_id)}.md"
        lines = [
            f"# {domain_id}",
            "",
            "## 相关运行",
            "",
            "| Run | 状态 | 时间 |",
            "| --- | --- | --- |",
        ]
        for note in domain_notes:
            lines.append(f"| {_run_wikilink(note)} | `{note.get('status', '')}` | {note.get('started_at', '')} |")
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        written.append(path)
    return written


def _parse_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}
    data: dict[str, Any] = {}
    current_list: str | None = None
    for line in text[4:end].splitlines():
        if line.startswith("  - ") and current_list:
            data.setdefault(current_list, []).append(_unquote_yaml_scalar(line[4:]))
            continue
        if ":" not in line:
            current_list = None
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if value == "":
            data[key] = []
            current_list = key
        elif value == "[]":
            data[key] = []
            current_list = None
        else:
            data[key] = _unquote_yaml_scalar(value)
            current_list = None
    return data


def _run_wikilink(note: dict[str, Any]) -> str:
    run_id = str(note.get("run_id", "unknown"))
    stem = str(note.get("note_stem") or _safe_file_stem(run_id))
    return f"[[Runs/{stem}|{run_id}]]"


def _month_key(value: str) -> str:
    if re.match(r"^\d{4}-\d{2}", value):
        return value[:7]
    return "unknown"


def _yaml_scalar(value: Any) -> str:
    return json.dumps(str(value or ""), ensure_ascii=False)


def _yaml_list(key: str, values: list[str]) -> list[str]:
    if not values:
        return [f"{key}: []"]
    return [f"{key}:", *[f"  - {_yaml_scalar(value)}" for value in values]]


def _unquote_yaml_scalar(value: str) -> str:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return value
    return str(decoded)


def _safe_file_stem(value: str) -> str:
    safe = re.sub(r"[\\/:*?\"<>|\r\n]+", "-", value.strip()).strip(". ")
    return safe or "unknown"


def _redact(value: str) -> str:
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


def _result(run_ids: list[str], memory_root: Path, written: list[Path]) -> dict[str, Any]:
    unique_written = _dedupe([str(path) for path in written])
    return {
        "run_ids": run_ids,
        "memory_root": str(memory_root),
        "files_written": unique_written,
    }
