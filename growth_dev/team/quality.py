from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import TeamRunRecord


QUALITY_ARTIFACTS = ("prd.md", "tech_spec.md", "ui_spec.md", "eval.md", "final_report.md")
STALE_CONTEXT_MARKERS = (
    "xhs_browser_benchmark",
    "xhs benchmark",
    "xhs style",
    "小红书",
    "playwright mcp",
    "stagehand",
    "skyvern",
    "hyperagent",
    "browser-use",
)
UI_KEYWORDS = ("ui", "页面", "界面", "前端", "交互", "dashboard", "可视化", "按钮", "表单", "工作台")
NO_UI_MARKERS = ("无 ui 影响", "无ui影响", "no ui impact", "no user interface impact", "不涉及 ui", "不涉及页面")


@dataclass(slots=True)
class QualityCheck:
    id: str
    title: str
    status: str
    detail: str
    artifact: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ArtifactQualityReport:
    status: str
    score: float
    summary: str
    checks: list[QualityCheck] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "score": self.score,
            "summary": self.summary,
            "checks": [check.to_dict() for check in self.checks],
        }


@dataclass(slots=True)
class RunHealthSummary:
    status: str
    label: str
    summary: str
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warning_groups: list[dict[str, Any]] = field(default_factory=list)
    raw_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_run_quality(record: TeamRunRecord, run_dir: Path) -> ArtifactQualityReport:
    checks: list[QualityCheck] = []
    task_terms = _task_terms(record)
    requires_ui = _requires_ui(record)

    for artifact in QUALITY_ARTIFACTS:
        path = run_dir / artifact
        if not path.exists():
            checks.append(QualityCheck(f"{artifact}.exists", _artifact_title(artifact), "failed", "产物缺失。", artifact))
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        lower = text.lower()
        checks.append(QualityCheck(f"{artifact}.exists", _artifact_title(artifact), "passed", "产物已生成。", artifact))

        leakage = _context_leakage(record, lower)
        if leakage:
            checks.append(
                QualityCheck(
                    f"{artifact}.context_leakage",
                    "上下文污染检查",
                    "failed",
                    f"发现疑似旧领域上下文：{', '.join(leakage[:4])}。",
                    artifact,
                )
            )
        else:
            checks.append(QualityCheck(f"{artifact}.context_leakage", "上下文污染检查", "passed", "未发现明显旧领域上下文。", artifact))

        if artifact == "ui_spec.md" and not requires_ui:
            if any(marker in lower for marker in NO_UI_MARKERS):
                checks.append(QualityCheck(f"{artifact}.no_ui_impact", "UI 影响说明", "passed", "非 UI 任务已明确说明无 UI 影响。", artifact))
            else:
                checks.append(QualityCheck(f"{artifact}.no_ui_impact", "UI 影响说明", "failed", "非 UI 任务需要明确说明无 UI 影响。", artifact))

        if artifact in {"prd.md", "tech_spec.md", "eval.md", "final_report.md"}:
            matched_terms = [term for term in task_terms if term and term in lower]
            if matched_terms:
                checks.append(
                    QualityCheck(
                        f"{artifact}.specificity",
                        "需求贴题度",
                        "passed",
                        f"包含任务关键词：{', '.join(matched_terms[:4])}。",
                        artifact,
                    )
                )
            else:
                checks.append(QualityCheck(f"{artifact}.specificity", "需求贴题度", "failed", "内容没有明显围绕本次 brief/domain。", artifact))

        section_status, section_detail = _section_check(artifact, lower)
        checks.append(QualityCheck(f"{artifact}.structure", "结构完整性", section_status, section_detail, artifact))

    failed = [check for check in checks if check.status == "failed"]
    passed = [check for check in checks if check.status == "passed"]
    score = round(len(passed) / len(checks), 3) if checks else 0.0
    if failed:
        if any(check.id.endswith(".context_leakage") for check in failed):
            summary = "发现旧领域上下文污染或产物贴题度不足，需要人工复核。"
        else:
            summary = "文件产物存在缺失或表达不完整，需要补齐后再采纳。"
        status = "needs_attention"
    else:
        summary = "文件产物贴合需求，结构和验收信息基本齐备。"
        status = "passed"
    return ArtifactQualityReport(status=status, score=score, summary=summary, checks=checks)


def summarize_run_health(record: TeamRunRecord, run_dir: Path) -> RunHealthSummary:
    warnings, blockers = _log_warnings_and_blockers(run_dir)
    non_blocking_risk_notes = _non_blocking_risk_notes(record)
    warning_groups = _warning_groups(warnings + list(record.risk_events) + non_blocking_risk_notes)
    if record.status == "failed":
        blockers.extend(_record_blockers(record))
        return RunHealthSummary(
            status="failed_needs_attention",
            label="失败需处理",
            summary="任务失败，需要先处理阻塞原因。",
            warnings=_warning_group_summaries(warning_groups),
            blockers=_dedupe(blockers) or ["run_failed"],
            warning_groups=warning_groups,
            raw_warnings=_dedupe(warnings),
        )
    if record.status in {"running", "starting", "pending"}:
        return RunHealthSummary(
            status="running",
            label="运行中",
            summary="AI 团队正在处理任务，可继续观察阶段进度和最近日志。",
            warnings=_warning_group_summaries(warning_groups),
            blockers=_dedupe(blockers),
            warning_groups=warning_groups,
            raw_warnings=_dedupe(warnings),
        )
    if record.status == "completed" and (warnings or record.risk_events or non_blocking_risk_notes):
        group_count = len(warning_groups)
        summary = (
            f"存在 {group_count} 类非阻塞系统提示（非阻塞警告），未影响 Review/Test/Report。"
            if group_count
            else "任务已完成，关键流程未失败，但存在非阻塞警告或风险提示。"
        )
        return RunHealthSummary(
            status="completed_with_warnings",
            label="已完成但有警告",
            summary=summary,
            warnings=_warning_group_summaries(warning_groups),
            blockers=[],
            warning_groups=warning_groups,
            raw_warnings=_dedupe(warnings + non_blocking_risk_notes),
        )
    if record.status == "completed":
        return RunHealthSummary(
            status="completed_ready",
            label="已完成可采纳",
            summary="任务已完成，Review/Test 证据齐备，可查看 diff 和最终报告后决定是否采纳。",
            warnings=[],
            blockers=[],
            warning_groups=[],
            raw_warnings=[],
        )
    return RunHealthSummary(
        status="unknown",
        label="状态未知",
        summary="暂时无法判断任务健康状态，请查看工程详情。",
        warnings=_warning_group_summaries(warning_groups),
        blockers=_dedupe(blockers),
        warning_groups=warning_groups,
        raw_warnings=_dedupe(warnings),
    )


def summarize_run_logs(run_dir: Path, max_lines: int = 8) -> list[str]:
    lines: list[str] = []
    stdout_path = run_dir / "codex" / "stdout.jsonl"
    if stdout_path.exists():
        lines.extend(_summarize_stdout_jsonl(stdout_path))
    for path in (
        run_dir / "background_stdout.log",
        run_dir / "background_stderr.log",
        run_dir / "codex" / "stderr.log",
        run_dir / "codex" / "reviewer_stdout.log",
        run_dir / "codex" / "reviewer_stderr.log",
    ):
        if not path.exists():
            continue
        for line in _tail_lines(path, max_lines=2):
            lines.append(f"{path.name}: {_redact_text(line)}")
    return lines[-max_lines:]


def _summarize_stdout_jsonl(path: Path) -> list[str]:
    lines: list[str] = []
    for line in _tail_lines(path, max_lines=6):
        parsed = _json_object(line)
        if not parsed:
            lines.append(f"{path.name}: {_redact_text(line)}")
            continue
        item = parsed.get("item") if isinstance(parsed.get("item"), dict) else {}
        if item.get("type") == "agent_message":
            message = _json_object(str(item.get("text", "")))
            if message:
                summary = str(message.get("summary", "")).strip()
                files_changed = [str(item) for item in message.get("files_changed", [])]
                tests_run = [str(item) for item in message.get("tests_run", [])]
                risks = [str(item) for item in message.get("risk_events", [])]
                if summary:
                    lines.append(f"Codex summary: {_redact_text(summary)}")
                if files_changed:
                    lines.append(f"Changed files: {', '.join(files_changed[:6])}")
                if tests_run:
                    lines.append(f"Tests: {tests_run[-1]}")
                if risks:
                    lines.append(f"Risk events: {', '.join(risks[:4])}")
            continue
        if parsed.get("type") == "turn.completed":
            usage = parsed.get("usage") if isinstance(parsed.get("usage"), dict) else {}
            if usage:
                lines.append(
                    "Codex usage: "
                    + ", ".join(f"{key}={value}" for key, value in usage.items() if key in {"input_tokens", "output_tokens", "reasoning_output_tokens"})
                )
    return lines


def _log_warnings_and_blockers(run_dir: Path) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    blockers: list[str] = []
    for path in (run_dir / "background_stderr.log", run_dir / "codex" / "stderr.log", run_dir / "codex" / "reviewer_stderr.log"):
        if not path.exists():
            continue
        for line in _tail_lines(path, max_lines=20):
            lower = line.lower()
            if "permissionerror" in lower or "operation not permitted" in lower or "traceback" in lower:
                blockers.append(_redact_text(line))
            elif "warn" in lower or "error" in lower or "settlement_unknown_model" in lower or "failed to refresh available models" in lower:
                warnings.append(_redact_text(line))
    return warnings, blockers


def _warning_groups(warnings: list[str]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for warning in _dedupe(warnings):
        group_id, title = _warning_group_for(warning)
        if group_id not in grouped:
            grouped[group_id] = {"id": group_id, "title": title, "count": 0, "severity": "info", "sample": warning}
            order.append(group_id)
        grouped[group_id]["count"] += 1
    priority = {
        "plugin_sync": 0,
        "telemetry": 1,
        "network_retry": 2,
        "mcp_cleanup": 3,
        "model_provider": 4,
        "unknown": 9,
    }
    return [grouped[group_id] for group_id in sorted(order, key=lambda item: priority.get(item, 99))]


def _warning_group_for(warning: str) -> tuple[str, str]:
    lower = warning.lower()
    if "no scraping" in lower or "outside the high-level allowed list" in lower or "non_blocking" in lower or "non-blocking" in lower:
        return "execution_boundary_note", "执行边界说明"
    if "plugin" in lower and ("sync" in lower or "catalog" in lower):
        return "plugin_sync", "插件同步提示"
    if "telemetry" in lower or "codex_otel" in lower or "metrics counter" in lower:
        return "telemetry", "遥测提示"
    if "stream disconnected" in lower or "retrying sampling" in lower or "failed to send remote plugin sync request" in lower:
        return "network_retry", "临时网络重试"
    if "mcp" in lower or "process group" in lower or "no such process" in lower:
        return "mcp_cleanup", "MCP 清理提示"
    if "model" in lower or "provider" in lower or "settlement_unknown_model" in lower or "failed to refresh available models" in lower:
        return "model_provider", "模型服务提示"
    return "unknown", "其他系统提示"


def _warning_group_summaries(groups: list[dict[str, Any]], limit: int = 3) -> list[str]:
    return [f"{group['title']}：{group['count']} 条" for group in groups[:limit]]


def _record_blockers(record: TeamRunRecord) -> list[str]:
    blockers = list(record.risk_events)
    for agent_run in record.agent_runs:
        if agent_run.status == "failed":
            failure_category = (agent_run.metadata or {}).get("failure_category")
            blockers.append(str(failure_category or agent_run.message or f"agent_failed:{agent_run.agent_id}"))
    return blockers


def _non_blocking_risk_notes(record: TeamRunRecord) -> list[str]:
    notes: list[str] = []
    for agent_run in record.agent_runs:
        metadata = agent_run.metadata or {}
        raw_notes = metadata.get("non_blocking_risk_events", [])
        if isinstance(raw_notes, str):
            notes.append(raw_notes)
        elif isinstance(raw_notes, list):
            notes.extend(str(item) for item in raw_notes)
    return _dedupe(notes)


def _task_terms(record: TeamRunRecord) -> list[str]:
    seed = f"{record.domain_id} {record.brief}"
    terms = {record.domain_id.lower()}
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", seed):
        value = token.lower()
        if value not in {"domain", "增加", "补充", "对应", "测试", "字段"}:
            terms.add(value)
    if "截图" in seed and "证据" in seed:
        terms.add("screenshot_evidence")
    return sorted(terms, key=len, reverse=True)


def _context_leakage(record: TeamRunRecord, lower_text: str) -> list[str]:
    expected_domain = record.domain_id.lower()
    leakage: list[str] = []
    for marker in STALE_CONTEXT_MARKERS:
        marker_lower = marker.lower()
        if marker_lower == expected_domain:
            continue
        if marker_lower in lower_text:
            leakage.append(marker)
    return leakage


def _requires_ui(record: TeamRunRecord) -> bool:
    text = f"{record.domain_id} {record.brief}".lower()
    return any(keyword in text for keyword in UI_KEYWORDS)


def _section_check(artifact: str, lower_text: str) -> tuple[str, str]:
    expectations = {
        "prd.md": ("background", "goal", "scope", "acceptance", "背景", "目标", "范围", "验收"),
        "tech_spec.md": ("architecture", "contract", "data", "gate", "技术", "数据", "接口", "边界"),
        "ui_spec.md": ("ui", "impact", "state", "无 ui 影响", "界面", "交互", "状态", "无ui影响"),
        "eval.md": ("acceptance", "test", "review", "gate", "验收", "测试", "评审", "关卡"),
        "final_report.md": ("brief", "gate", "recommendation", "summary", "需求", "结果", "建议", "关卡"),
    }
    terms = expectations.get(artifact, ())
    hits = [term for term in terms if term in lower_text]
    if len(hits) >= 2:
        return "passed", f"包含关键结构信息：{', '.join(hits[:4])}。"
    return "failed", "缺少足够的结构化信息。"


def _artifact_title(artifact: str) -> str:
    return {
        "prd.md": "PRD",
        "tech_spec.md": "技术方案",
        "ui_spec.md": "UI 规范",
        "eval.md": "验收标准",
        "final_report.md": "最终报告",
    }.get(artifact, artifact)


def _tail_lines(path: Path, max_lines: int = 5) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()][-max_lines:]


def _json_object(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _redact_text(value: str) -> str:
    text = re.sub(r"sk-[A-Za-z0-9_\-]+", "<redacted>", value)
    text = text.replace(".env", "<env-file>")
    return text
