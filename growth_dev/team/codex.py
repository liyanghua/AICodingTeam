from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import threading
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

from ..utils import ensure_dir, now_iso, read_json, write_json


REQUIRED_CODEX_RESPONSE_FIELDS = ["summary", "files_changed", "tests_run", "risk_events", "blockers", "next_action"]

CODEX_RESPONSE_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "additionalProperties": False,
    "required": REQUIRED_CODEX_RESPONSE_FIELDS,
    "properties": {
        "summary": {"type": "string"},
        "files_changed": {"type": "array", "items": {"type": "string"}},
        "tests_run": {"type": "array", "items": {"type": "string"}},
        "risk_events": {"type": "array", "items": {"type": "string"}},
        "blockers": {"type": "array", "items": {"type": "string"}},
        "next_action": {"type": "string"},
    },
}

DEFAULT_ALLOWED_PATHS = ["growth_dev/", "dashboard/", "tests/", "domains/", "tasks/", "README.md", "AGENTS.md", "DESIGN.md"]
DEFAULT_VERIFICATION_COMMANDS = ["python3 -m unittest discover -s tests -v"]
UPSTREAM_CONTEXT_ARTIFACTS = ["task.yaml", "context.md", "prd.md", "tech_spec.md", "ui_spec.md", "eval.md", "AGENTS.md", "DESIGN.md"]

IMPLEMENTATION_TRACE_PATH = "codex/implementation_trace.json"
IMPLEMENTATION_TRACE_STEPS = [
    ("prepare_context", "准备上下文"),
    ("check_executor", "检查执行器"),
    ("prepare_worktree", "准备隔离工作区"),
    ("codex_running", "启动 AI coding"),
    ("parse_response", "解析 AI 输出"),
    ("collect_changes", "收集代码变化"),
    ("finalize_result", "生成实现结果"),
]
IMPLEMENTATION_TRACE_INPUT_TITLES = {
    "task.yaml": "任务包",
    "context.md": "上下文说明",
    "prd.md": "PRD",
    "tech_spec.md": "技术方案",
    "ui_spec.md": "UI 规范",
    "eval.md": "验收标准",
    "AGENTS.md": "Agent 规则",
    "DESIGN.md": "设计规范",
}

IMPLEMENTATION_RISK_PATTERNS = [
    "2captcha",
    "anti-captcha",
    "anticaptcha",
    "captcha_solver",
    "solve_captcha",
    "puppeteer-extra-plugin-stealth",
    "undetected_chromedriver",
    "undetected-chromedriver",
    "fingerprint spoof",
    "fingerprint_spoof",
    "proxy rotation",
    "proxy_pool",
    "anti-detect",
    "antidetect",
    "x-sign",
    "private api reverse",
]

NON_BLOCKING_CODEX_RISK_NOTE_MARKERS = [
    ("outside the high-level allowed list", "nearby supporting location"),
    ("outside the high-level allowed list", "required to implement"),
    ("nearby_supporting", "required"),
    ("nearby supporting", "required"),
]


@dataclass(slots=True)
class CodexProviderConfig:
    name: str
    base_url: str
    env_key: str
    secret_value: str = ""
    wire_api: str = "responses"
    requires_openai_auth: bool = False

    def command_overrides(self) -> list[str]:
        return [
            f'model_provider="{self.name}"',
            f'model_providers.{self.name}.name="{self.name}"',
            f'model_providers.{self.name}.base_url="{self.base_url}"',
            f'model_providers.{self.name}.env_key="{self.env_key}"',
            f'model_providers.{self.name}.wire_api="{self.wire_api}"',
            f"model_providers.{self.name}.requires_openai_auth={str(self.requires_openai_auth).lower()}",
        ]

    def redacted_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "base_url": self.base_url,
            "env_key": self.env_key,
            "wire_api": self.wire_api,
            "requires_openai_auth": self.requires_openai_auth,
            "secret_configured": bool(self.secret_value),
        }


@dataclass(slots=True)
class CodexExecutorConfig:
    binary: str = "codex"
    model: str = "gpt-5.3-codex"
    reasoning_effort: str = "medium"
    sandbox: str = "workspace-write"
    approval_policy: str = "never"
    timeout_seconds: int = 7200
    extra_add_dirs: list[str] = field(default_factory=list)
    provider: CodexProviderConfig | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.provider:
            payload["provider"] = self.provider.redacted_dict()
        return payload


@dataclass(slots=True)
class CodexPromptBundle:
    stage: str
    prompt_path: Path
    state_summary_path: Path
    output_schema_path: Path
    output_last_message_path: Path
    stdout_path: Path
    stderr_path: Path
    command_path: Path
    prompt_hash: str
    state_hash: str
    allowed_paths: list[str] = field(default_factory=list)
    verification_commands: list[str] = field(default_factory=list)

    def relative_paths(self, run_dir: Path) -> list[str]:
        return [
            _relative_to(self.prompt_path, run_dir),
            _relative_to(self.state_summary_path, run_dir),
            _relative_to(self.output_schema_path, run_dir),
            _relative_to(self.output_last_message_path, run_dir),
            _relative_to(self.stdout_path, run_dir),
            _relative_to(self.stderr_path, run_dir),
            _relative_to(self.command_path, run_dir),
        ]


@dataclass(slots=True)
class CodexStageResult:
    status: str
    output_paths: list[str]
    risk_events: list[str] = field(default_factory=list)
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def build_codex_exec_command(
    config: CodexExecutorConfig,
    *,
    worktree_dir: Path,
    run_dir: Path,
    output_schema_path: Path,
    output_last_message_path: Path,
) -> list[str]:
    command = _codex_base_command(config, worktree_dir=worktree_dir, run_dir=run_dir)
    command.extend(
        [
            "exec",
            "--json",
            "--output-last-message",
            str(output_last_message_path.resolve()),
            "--output-schema",
            str(output_schema_path.resolve()),
            "-",
        ]
    )
    return command


def build_codex_review_command(
    config: CodexExecutorConfig,
    *,
    worktree_dir: Path,
    run_dir: Path,
    title: str,
) -> list[str]:
    command = _codex_base_command(config, worktree_dir=worktree_dir, run_dir=run_dir)
    command.extend(["review", "--uncommitted", "--title", title])
    return command


def load_aicodemirror_provider_from_env(env_path: Path) -> CodexProviderConfig:
    values = _read_env_file(env_path)
    base_url = values.get("aicodemirror_base_url") or values.get("AICODEMIRROR_BASE_URL")
    secret = values.get("aicodemirror_key") or values.get("AICODEMIRROR_KEY")
    missing = []
    if not base_url:
        missing.append("aicodemirror_base_url")
    if not secret:
        missing.append("aicodemirror_key")
    if missing:
        raise ValueError(f"Missing aicodemirror provider setting(s) in {env_path}: {', '.join(missing)}")
    return CodexProviderConfig(
        name="aicodemirror",
        base_url=base_url,
        env_key="AICODEMIRROR_KEY",
        secret_value=secret,
        wire_api="responses",
        requires_openai_auth=False,
    )


class CodexExecutor:
    def __init__(
        self,
        config: CodexExecutorConfig | None = None,
        *,
        repo_root: Path,
        run_dir: Path,
    ) -> None:
        self.config = config or CodexExecutorConfig()
        self.repo_root = Path(repo_root).resolve()
        self.run_dir = Path(run_dir).resolve()
        self.codex_dir = ensure_dir(self.run_dir / "codex")
        self.worktree_dir = self.run_dir / "worktree"

    def write_prompt_bundle(self, stage: str, context: Any) -> CodexPromptBundle:
        ensure_dir(self.codex_dir)
        allowed_paths = _allowed_paths(context)
        verification_commands = _verification_commands(context)
        state_text = _build_state_summary(stage, context, allowed_paths, verification_commands, self.worktree_dir)
        prompt_text = _build_prompt(stage, context, state_text, allowed_paths, verification_commands)

        prefix = "codex" if stage == "coder" else f"codex_{stage}"
        prompt_path = self.codex_dir / f"{prefix}_prompt.md"
        state_summary_path = self.codex_dir / ("state_summary.md" if stage == "coder" else f"{stage}_state_summary.md")
        output_schema_path = self.codex_dir / "codex_response_schema.json"
        output_last_message_path = self.codex_dir / ("last_message.json" if stage == "coder" else f"{stage}_last_message.json")
        stdout_path = self.codex_dir / ("stdout.jsonl" if stage == "coder" else f"{stage}_stdout.log")
        stderr_path = self.codex_dir / ("stderr.log" if stage == "coder" else f"{stage}_stderr.log")
        command_path = self.codex_dir / ("command.json" if stage == "coder" else f"{stage}_command.json")

        prompt_path.write_text(prompt_text, encoding="utf-8")
        state_summary_path.write_text(state_text, encoding="utf-8")
        write_json(output_schema_path, CODEX_RESPONSE_SCHEMA)
        output_last_message_path.write_text("", encoding="utf-8")
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")

        bundle = CodexPromptBundle(
            stage=stage,
            prompt_path=prompt_path,
            state_summary_path=state_summary_path,
            output_schema_path=output_schema_path,
            output_last_message_path=output_last_message_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command_path=command_path,
            prompt_hash=_sha256_text(prompt_text),
            state_hash=_sha256_text(state_text),
            allowed_paths=allowed_paths,
            verification_commands=verification_commands,
        )
        prompt_bundle_path = self.codex_dir / ("prompt_bundle.json" if stage == "coder" else f"{stage}_prompt_bundle.json")
        write_json(
            prompt_bundle_path,
            {
                "stage": stage,
                "prompt_path": _relative_to(prompt_path, self.run_dir),
                "state_summary_path": _relative_to(state_summary_path, self.run_dir),
                "output_schema_path": _relative_to(output_schema_path, self.run_dir),
                "prompt_hash": bundle.prompt_hash,
                "state_hash": bundle.state_hash,
                "allowed_paths": allowed_paths,
                "verification_commands": verification_commands,
                "created_at": now_iso(),
            },
        )
        return bundle

    def run_coder(self, context: Any) -> CodexStageResult:
        bundle = self.write_prompt_bundle("coder", context)
        trace_path = self.codex_dir / "implementation_trace.json"
        trace = _new_implementation_trace(context, bundle)
        _trace_step(trace, "prepare_context", "running", "正在生成 AI coding 所需的上下文和提示包。")
        _write_implementation_trace(trace_path, trace)
        human_prompt = _human_coding_prompt(context, bundle, self.worktree_dir)
        output_paths = [context.write_text("coding_prompt.md", human_prompt)]
        output_paths.extend(bundle.relative_paths(self.run_dir))
        output_paths.append(IMPLEMENTATION_TRACE_PATH)
        _trace_step(
            trace,
            "prepare_context",
            "completed",
            "已生成 prompt bundle、状态摘要和 AI coding 任务书。",
            artifacts=[_relative_to(bundle.prompt_path, self.run_dir), _relative_to(bundle.state_summary_path, self.run_dir), "coding_prompt.md"],
        )
        _write_implementation_trace(trace_path, trace)

        _trace_step(trace, "check_executor", "running", "正在检查本地 Codex 执行器是否可用。")
        _write_implementation_trace(trace_path, trace)
        if not self._binary_available():
            record = self._failure_record("coder", bundle, "codex_binary_missing", extra={"binary": self.config.binary})
            record["artifacts"]["implementation_trace"] = IMPLEMENTATION_TRACE_PATH
            _trace_fail(trace, "check_executor", "Codex 执行器不可用。", record["risk_events"], record["blockers"], "fix_executor")
            _write_implementation_trace(trace_path, trace)
            output_paths.append(context.write_json("code_run_record.json", record))
            return CodexStageResult("failed", output_paths, record["risk_events"], record["summary"], record)
        _trace_step(trace, "check_executor", "completed", "本地 Codex 执行器可用。")
        _write_implementation_trace(trace_path, trace)

        try:
            _trace_step(trace, "prepare_worktree", "running", "正在准备隔离 git worktree 和必要的 git metadata 读取权限。")
            _write_implementation_trace(trace_path, trace)
            worktree_dir = self.prepare_worktree()
        except Exception as exc:  # noqa: BLE001 - persisted in run artifacts for offline inspection.
            record = self._failure_record("coder", bundle, f"worktree_prepare_failed:{type(exc).__name__}:{exc}")
            record["artifacts"]["implementation_trace"] = IMPLEMENTATION_TRACE_PATH
            _trace_fail(trace, "prepare_worktree", "隔离工作区准备失败。", record["risk_events"], record["blockers"], "fix_worktree")
            _write_implementation_trace(trace_path, trace)
            output_paths.append(context.write_json("code_run_record.json", record))
            return CodexStageResult("failed", output_paths, record["risk_events"], record["summary"], record)
        _trace_step(trace, "prepare_worktree", "completed", "隔离 worktree 已准备好。")
        _write_implementation_trace(trace_path, trace)

        _trace_step(trace, "codex_running", "running", "AI coding 正在根据任务书实现代码变更。")
        _write_implementation_trace(trace_path, trace)
        command = build_codex_exec_command(
            self.config,
            worktree_dir=worktree_dir,
            run_dir=self.run_dir,
            output_schema_path=bundle.output_schema_path,
            output_last_message_path=bundle.output_last_message_path,
        )
        write_json(bundle.command_path, {"command": command, "cwd": str(worktree_dir), "created_at": now_iso()})
        completed = self._run_process(command, bundle.prompt_path.read_text(encoding="utf-8"), worktree_dir, bundle.stdout_path, bundle.stderr_path)
        codex_run_status = "completed" if completed.returncode == 0 else "failed"
        _trace_step(trace, "codex_running", codex_run_status, f"AI coding 进程已结束，退出码 {completed.returncode}。")
        trace["evidence"]["exit_code"] = completed.returncode
        _write_implementation_trace(trace_path, trace)

        _trace_step(trace, "parse_response", "running", "正在解析 AI coding 返回的结构化结果。")
        _write_implementation_trace(trace_path, trace)
        response, validation_events = _read_codex_response(bundle.output_last_message_path)
        _trace_step(
            trace,
            "parse_response",
            "completed" if not validation_events else "failed",
            "已解析结构化结果。" if not validation_events else "结构化结果缺失或格式异常。",
        )
        _write_implementation_trace(trace_path, trace)
        _trace_step(trace, "collect_changes", "running", "正在收集 changed files、diff 和风险信号。")
        _write_implementation_trace(trace_path, trace)
        changed_files = _changed_files(worktree_dir)
        diff_path, status_path = _write_diff_artifacts(worktree_dir, self.codex_dir)
        response_risk_events = _string_list(response.get("risk_events", []))
        response_blocking_risk_events, non_blocking_risk_events = classify_codex_risk_events(response_risk_events)
        risk_events = list(response_blocking_risk_events)
        risk_events.extend(validation_events)
        risk_events.extend(_scan_implementation_risks(diff_path.read_text(encoding="utf-8") if diff_path.exists() else ""))
        risk_events = _dedupe(risk_events)
        non_blocking_risk_events = _dedupe(non_blocking_risk_events)
        blockers = _string_list(response.get("blockers", []))
        if completed.returncode != 0:
            risk_events.append(f"codex_exit_code:{completed.returncode}")
            blockers.append(f"codex exited with {completed.returncode}")
        failure_category = classify_codex_failure(completed.stderr, completed.returncode, "coder")
        if not changed_files:
            blockers.append("no_changed_files")

        status = "completed" if not risk_events and not blockers else "failed"
        files_changed = sorted(set(changed_files + _string_list(response.get("files_changed", []))))
        tests_run = _string_list(response.get("tests_run", []))
        trace["evidence"].update(
            {
                "changed_files": files_changed,
                "tests_run": tests_run,
                "verification_commands": bundle.verification_commands,
                "diff_path": _relative_to(diff_path, self.run_dir),
                "exit_code": completed.returncode,
            }
        )
        _trace_step(
            trace,
            "collect_changes",
            "completed" if changed_files else "failed",
            "已收集代码变化和 diff 证据。" if changed_files else "未检测到代码变化。",
            artifacts=[_relative_to(diff_path, self.run_dir), _relative_to(status_path, self.run_dir)],
        )
        _write_implementation_trace(trace_path, trace)
        _trace_step(trace, "finalize_result", "running", "正在整理 AI 实现结果、风险和下一步动作。")
        _write_implementation_trace(trace_path, trace)
        record = {
            "agent": "coder",
            "executor": "codex",
            "status": status,
            "run_id": context.run_id,
            "domain_id": context.domain.domain_id,
            "model": self.config.model,
            "reasoning_effort": self.config.reasoning_effort,
            "provider": self.config.provider.redacted_dict() if self.config.provider else {"name": "default"},
            "worktree_path": str(worktree_dir),
            "summary": str(response.get("summary", "")) or "Codex coding run finished without a structured summary.",
            "files_changed": files_changed,
            "tests_run": tests_run,
            "verification_commands": bundle.verification_commands,
            "risk_events": risk_events,
            "blocking_risk_events": risk_events,
            "non_blocking_risk_events": non_blocking_risk_events,
            "blockers": blockers,
            "next_action": str(response.get("next_action", "")),
            "prompt_hash": bundle.prompt_hash,
            "state_hash": bundle.state_hash,
            "exit_code": completed.returncode,
            "failure_category": failure_category,
            "artifacts": {
                "prompt": _relative_to(bundle.prompt_path, self.run_dir),
                "state_summary": _relative_to(bundle.state_summary_path, self.run_dir),
                "last_message": _relative_to(bundle.output_last_message_path, self.run_dir),
                "stdout": _relative_to(bundle.stdout_path, self.run_dir),
                "stderr": _relative_to(bundle.stderr_path, self.run_dir),
                "diff": _relative_to(diff_path, self.run_dir),
                "status": _relative_to(status_path, self.run_dir),
                "command": _relative_to(bundle.command_path, self.run_dir),
                "implementation_trace": IMPLEMENTATION_TRACE_PATH,
            },
        }
        trace["status"] = status
        trace["current_step"] = "finalize_result"
        trace["risk_events"] = risk_events
        trace["blocking_risk_events"] = risk_events
        trace["non_blocking_risk_events"] = non_blocking_risk_events
        trace["blockers"] = blockers
        trace["next_action"] = str(response.get("next_action", ""))
        _trace_step(
            trace,
            "finalize_result",
            status,
            "AI 实现结果已整理完成。" if status == "completed" else "AI 实现结果需要处理阻塞或风险。",
            artifacts=["code_run_record.json"],
        )
        trace["status"] = status
        _write_implementation_trace(trace_path, trace)
        output_paths.extend([_relative_to(diff_path, self.run_dir), _relative_to(status_path, self.run_dir)])
        output_paths.append(context.write_json("code_run_record.json", record))
        return CodexStageResult(status, _dedupe(output_paths), risk_events, record["summary"], record)

    def run_reviewer(self, context: Any) -> CodexStageResult:
        bundle = self.write_prompt_bundle("reviewer", context)
        output_paths = bundle.relative_paths(self.run_dir)
        worktree_dir = self.worktree_dir
        risk_events: list[str] = []
        if not _is_git_worktree(worktree_dir):
            risk_events.append("codex_worktree_missing")
            report = _review_report_text(context, "", [], risk_events, "Codex worktree is missing; no diff was reviewed.", diff_path="", code_record=None)
            output_paths.append(context.write_text("review_report.md", report))
            return CodexStageResult("failed", _dedupe(output_paths), risk_events, "Codex worktree is missing", {"risk_events": risk_events})
        if not self._binary_available():
            risk_events.append("codex_binary_missing")
            report = _review_report_text(
                context,
                "",
                _changed_files(worktree_dir),
                risk_events,
                f"Codex binary not found: {self.config.binary}",
                diff_path="",
                code_record=_previous_code_record(context),
            )
            output_paths.append(context.write_text("review_report.md", report))
            return CodexStageResult("failed", _dedupe(output_paths), risk_events, "Codex binary missing", {"risk_events": risk_events})

        changed_files = _changed_files(worktree_dir)
        if not changed_files:
            risk_events.append("codex_review_no_diff")
        diff_path, status_path = _write_diff_artifacts(worktree_dir, self.codex_dir)
        risk_events.extend(_scan_implementation_risks(diff_path.read_text(encoding="utf-8") if diff_path.exists() else ""))

        command = build_codex_review_command(
            self.config,
            worktree_dir=worktree_dir,
            run_dir=self.run_dir,
            title=f"{context.run_id} code review",
        )
        write_json(bundle.command_path, {"command": command, "cwd": str(worktree_dir), "created_at": now_iso()})
        completed = self._run_process(command, bundle.prompt_path.read_text(encoding="utf-8"), worktree_dir, bundle.stdout_path, bundle.stderr_path)
        review_text = bundle.stdout_path.read_text(encoding="utf-8")
        if completed.returncode != 0:
            risk_events.append(f"codex_review_exit_code:{completed.returncode}")
        failure_category = classify_codex_failure(completed.stderr + "\n" + completed.stdout, completed.returncode, "reviewer")

        report = _review_report_text(
            context,
            review_text,
            changed_files,
            risk_events,
            "",
            diff_path=_relative_to(diff_path, self.run_dir),
            code_record=_previous_code_record(context),
            test_report_text=_read_optional_run_text(context, "test_report.md"),
        )
        output_paths.extend([_relative_to(diff_path, self.run_dir), _relative_to(status_path, self.run_dir)])
        output_paths.append(context.write_text("review_report.md", report))
        metadata = {
            "executor": "codex",
            "status": "completed" if not risk_events else "failed",
            "changed_files": changed_files,
            "risk_events": risk_events,
            "exit_code": completed.returncode,
            "failure_category": failure_category,
            "provider": self.config.provider.redacted_dict() if self.config.provider else {"name": "default"},
            "artifacts": {
                "review_stdout": _relative_to(bundle.stdout_path, self.run_dir),
                "review_stderr": _relative_to(bundle.stderr_path, self.run_dir),
                "command": _relative_to(bundle.command_path, self.run_dir),
                "diff": _relative_to(diff_path, self.run_dir),
            },
        }
        return CodexStageResult(metadata["status"], _dedupe(output_paths), risk_events, "codex review finished", metadata)

    def run_verifier(self, context: Any) -> CodexStageResult:
        worktree_dir = self.worktree_dir
        commands = _verification_commands(context)
        risk_events: list[str] = []
        output_paths: list[str] = []
        if not _is_git_worktree(worktree_dir):
            risk_events.append("codex_worktree_missing")
            report = "# Test Report\n\n- Status: failed\n- Error: Codex worktree is missing.\n"
            output_paths.append(context.write_text("test_report.md", report))
            return CodexStageResult("failed", output_paths, risk_events, "Codex worktree is missing", {"risk_events": risk_events})

        results: list[dict[str, Any]] = []
        for index, command in enumerate(commands, start=1):
            stdout_path = self.codex_dir / f"verify_{index}_stdout.log"
            stderr_path = self.codex_dir / f"verify_{index}_stderr.log"
            started_at = now_iso()
            try:
                completed = subprocess.run(
                    shlex.split(command),
                    cwd=worktree_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=self.config.timeout_seconds,
                    check=False,
                    env=self._process_env(),
                )
                stdout_path.write_text(completed.stdout, encoding="utf-8")
                stderr_path.write_text(completed.stderr, encoding="utf-8")
                exit_code = completed.returncode
            except Exception as exc:  # noqa: BLE001 - persisted into verification artifacts.
                stdout_path.write_text("", encoding="utf-8")
                stderr_path.write_text(f"{type(exc).__name__}: {exc}", encoding="utf-8")
                exit_code = 1

            if exit_code != 0:
                risk_events.append(f"verification_failed:{command}:{exit_code}")
            failure_category = classify_codex_failure(
                stderr_path.read_text(encoding="utf-8", errors="replace")
                + "\n"
                + stdout_path.read_text(encoding="utf-8", errors="replace"),
                exit_code,
                "verifier",
            )
            output_paths.extend([_relative_to(stdout_path, self.run_dir), _relative_to(stderr_path, self.run_dir)])
            results.append(
                {
                    "command": command,
                    "exit_code": exit_code,
                    "failure_category": failure_category,
                    "started_at": started_at,
                    "finished_at": now_iso(),
                    "stdout_path": _relative_to(stdout_path, self.run_dir),
                    "stderr_path": _relative_to(stderr_path, self.run_dir),
                }
            )

        verification_record = {
            "executor": "codex",
            "status": "completed" if not risk_events else "failed",
            "worktree_path": str(worktree_dir),
            "commands": results,
            "risk_events": risk_events,
            "failure_category": next((item["failure_category"] for item in results if item.get("failure_category")), ""),
        }
        verification_record_path = self.codex_dir / "verification_record.json"
        write_json(verification_record_path, verification_record)
        output_paths.append(_relative_to(verification_record_path, self.run_dir))

        report = _verification_report_text(
            context,
            verification_record=verification_record,
            code_record=_previous_code_record(context),
            implementation_trace=_previous_implementation_trace(context),
        )
        output_paths.append(context.write_text("test_report.md", report))
        return CodexStageResult(verification_record["status"], _dedupe(output_paths), risk_events, "verification finished", verification_record)

    def prepare_worktree(self) -> Path:
        if _is_git_worktree(self.worktree_dir):
            self._add_worktree_git_metadata_dirs(self.worktree_dir)
            return self.worktree_dir
        ensure_dir(self.worktree_dir.parent)
        if self.worktree_dir.exists() and any(self.worktree_dir.iterdir()):
            raise RuntimeError(f"Worktree path exists but is not a git worktree: {self.worktree_dir}")
        _run_checked(["git", "rev-parse", "--show-toplevel"], cwd=self.repo_root)
        _run_checked(["git", "worktree", "add", "--detach", str(self.worktree_dir), "HEAD"], cwd=self.repo_root)
        self._add_worktree_git_metadata_dirs(self.worktree_dir)
        return self.worktree_dir

    def _add_worktree_git_metadata_dirs(self, worktree_dir: Path) -> None:
        for command in (
            ["git", "rev-parse", "--path-format=absolute", "--git-dir"],
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        ):
            completed = subprocess.run(command, cwd=worktree_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            if completed.returncode != 0:
                continue
            path_text = completed.stdout.strip()
            if not path_text:
                continue
            metadata_dir = str(Path(path_text).resolve())
            if metadata_dir != str(self.repo_root) and metadata_dir not in self.config.extra_add_dirs:
                self.config.extra_add_dirs.append(metadata_dir)

    def _binary_available(self) -> bool:
        return Path(self.config.binary).exists() or shutil.which(self.config.binary) is not None

    def _run_process(self, command: list[str], prompt_text: str, cwd: Path, stdout_path: Path, stderr_path: Path) -> subprocess.CompletedProcess[str]:
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=self._process_env(),
            )
        except Exception as exc:  # noqa: BLE001 - subprocess failures are persisted as artifacts.
            completed = subprocess.CompletedProcess(command, 1, "", f"{type(exc).__name__}: {exc}")
            stderr_path.write_text(completed.stderr, encoding="utf-8")
            return completed

        def stream_output(stream, path: Path, chunks: list[str]) -> None:
            if stream is None:
                return
            with path.open("a", encoding="utf-8") as handle:
                with stream:
                    while True:
                        chunk = stream.readline()
                        if chunk == "":
                            break
                        chunks.append(chunk)
                        handle.write(chunk)
                        handle.flush()

        stdout_thread = threading.Thread(target=stream_output, args=(process.stdout, stdout_path, stdout_chunks), daemon=True)
        stderr_thread = threading.Thread(target=stream_output, args=(process.stderr, stderr_path, stderr_chunks), daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        try:
            if process.stdin:
                with process.stdin:
                    process.stdin.write(prompt_text)
            return_code = process.wait(timeout=self.config.timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
            return_code = 1
            message = f"TimeoutExpired: command exceeded {self.config.timeout_seconds} seconds\n"
            stderr_chunks.append(message)
            with stderr_path.open("a", encoding="utf-8") as handle:
                handle.write(message)
        except Exception as exc:  # noqa: BLE001 - subprocess failures are persisted as artifacts.
            process.kill()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
            return_code = 1
            message = f"{type(exc).__name__}: {exc}\n"
            stderr_chunks.append(message)
            with stderr_path.open("a", encoding="utf-8") as handle:
                handle.write(message)

        stdout_thread.join(timeout=1.0)
        stderr_thread.join(timeout=1.0)
        return subprocess.CompletedProcess(command, return_code, "".join(stdout_chunks), "".join(stderr_chunks))

    def _process_env(self) -> dict[str, str] | None:
        if not self.config.provider:
            return None
        env = dict(os.environ)
        if self.config.provider.secret_value:
            env[self.config.provider.env_key] = self.config.provider.secret_value
        return env

    def _failure_record(self, stage: str, bundle: CodexPromptBundle, reason: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "agent": stage,
            "executor": "codex",
            "status": "failed",
            "summary": reason,
            "files_changed": [],
            "tests_run": [],
            "verification_commands": bundle.verification_commands,
            "risk_events": [reason],
            "blockers": [reason],
            "next_action": "fix_executor",
            "prompt_hash": bundle.prompt_hash,
            "state_hash": bundle.state_hash,
            "model": self.config.model,
            "reasoning_effort": self.config.reasoning_effort,
            "failure_category": classify_codex_failure(reason, 1, stage),
            "provider": self.config.provider.redacted_dict() if self.config.provider else {"name": "default"},
            "artifacts": {
                "prompt": _relative_to(bundle.prompt_path, self.run_dir),
                "state_summary": _relative_to(bundle.state_summary_path, self.run_dir),
                "stderr": _relative_to(bundle.stderr_path, self.run_dir),
            },
            **(extra or {}),
        }


def _codex_base_command(config: CodexExecutorConfig, *, worktree_dir: Path, run_dir: Path) -> list[str]:
    command = [config.binary, "--cd", str(worktree_dir.resolve()), "--add-dir", str(run_dir.resolve())]
    for extra_dir in config.extra_add_dirs:
        command.extend(["--add-dir", str(Path(extra_dir).resolve())])
    if config.sandbox:
        command.extend(["--sandbox", config.sandbox])
    if config.approval_policy:
        command.extend(["--ask-for-approval", config.approval_policy])
    if config.model:
        command.extend(["-m", config.model])
    if config.reasoning_effort:
        command.extend(["-c", f'reasoning_effort="{config.reasoning_effort}"'])
    if config.provider:
        for override in config.provider.command_overrides():
            command.extend(["-c", override])
    return command


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        raise FileNotFoundError(f"Env file not found: {path}")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _allowed_paths(context: Any) -> list[str]:
    inputs = getattr(context, "inputs", {}) or {}
    domain = getattr(context, "domain", None)
    metadata = getattr(domain, "metadata", {}) or {}
    return _string_list(inputs.get("allowed_paths") or inputs.get("allowed_files") or metadata.get("allowed_paths") or metadata.get("allowed_files") or DEFAULT_ALLOWED_PATHS)


def _verification_commands(context: Any) -> list[str]:
    inputs = getattr(context, "inputs", {}) or {}
    domain = getattr(context, "domain", None)
    metadata = getattr(domain, "metadata", {}) or {}
    return _string_list(inputs.get("verification_commands") or metadata.get("verification_commands") or DEFAULT_VERIFICATION_COMMANDS)


def _build_state_summary(stage: str, context: Any, allowed_paths: list[str], verification_commands: list[str], worktree_dir: Path) -> str:
    previous_record = _previous_code_record(context)
    domain = getattr(context, "domain", None)
    risk_rules = getattr(domain, "risk_rules", []) or []
    evaluation_rules = getattr(domain, "evaluation_rules", []) or []
    inputs = getattr(context, "inputs", {}) or {}
    lines = [
        "# State Summary",
        "",
        f"- Stage: `{stage}`",
        f"- Run: `{context.run_id}`",
        f"- Domain: `{domain.domain_id if domain else ''}`",
        f"- Brief: {context.brief}",
        f"- Worktree: `{worktree_dir}`",
        "",
        "## Inputs",
        "```json",
        json.dumps(inputs, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Upstream Artifacts",
        *_artifact_excerpt_lines(context),
        "",
        "## Allowed Files",
        *[f"- {path}" for path in allowed_paths],
        "",
        "## Verification Commands",
        *[f"- `{command}`" for command in verification_commands],
        "",
        "## Risk Rules",
        *[f"- {rule}" for rule in risk_rules],
        "",
        "## Evaluation Rules",
        *[f"- {rule}" for rule in evaluation_rules],
    ]
    if previous_record:
        lines.extend(
            [
                "",
                "## Previous Attempt",
                f"- Status: {previous_record.get('status', '')}",
                f"- Summary: {previous_record.get('summary', '')}",
                f"- Files changed: {', '.join(_string_list(previous_record.get('files_changed', []))) or 'none'}",
                f"- Blockers: {', '.join(_string_list(previous_record.get('blockers', []))) or 'none'}",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _artifact_excerpt_lines(context: Any, max_chars: int = 1800) -> list[str]:
    run_dir = Path(getattr(context, "run_dir", "."))
    repo_root = Path(getattr(context, "repo_root", "."))
    lines: list[str] = []
    for name in UPSTREAM_CONTEXT_ARTIFACTS:
        path = repo_root / name if name in {"AGENTS.md", "DESIGN.md"} else run_dir / name
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "\n...[truncated]"
        lines.extend([f"### {name}", "```text", text.rstrip(), "```", ""])
    return lines or ["- No upstream artifacts found yet"]


def _build_prompt(stage: str, context: Any, state_summary: str, allowed_paths: list[str], verification_commands: list[str]) -> str:
    role = "coding agent" if stage == "coder" else "code reviewer"
    action = "Implement the requested vertical slice in the isolated worktree." if stage == "coder" else "Review the uncommitted diff in the isolated worktree."
    return "\n".join(
        [
            f"# Codex {stage.title()} Prompt",
            "",
            f"You are the `{role}` for this Agent Team Runtime stage.",
            action,
            "",
            "## Non-Negotiable Rules",
            "- Use only the local repository and provided run artifacts as context.",
            "- Do not rely on prior chat history.",
            "- Keep the change scoped to the allowed files unless the task cannot be completed without a nearby supporting file.",
            "- Do not implement captcha solving, fingerprint spoofing, proxy rotation, anti-detect behavior, private API reverse engineering, or platform security bypasses.",
            "- Stop and report a blocker if the task would require a prohibited behavior.",
            "",
            "## Required Final Response",
            "Return JSON that matches `codex/codex_response_schema.json` exactly.",
            "",
            "## State Summary",
            state_summary.rstrip(),
            "",
            "## Acceptance Criteria",
            "- The requested change is represented by a git diff in the worktree.",
            "- The final response names changed files and verification commands actually run.",
            "- Risk events and blockers are explicit and not hidden in prose.",
            "",
            "## Allowed Files",
            *[f"- {path}" for path in allowed_paths],
            "",
            "## Verification Commands",
            *[f"- `{command}`" for command in verification_commands],
        ]
    ).rstrip() + "\n"


def _human_coding_prompt(context: Any, bundle: CodexPromptBundle, worktree_dir: Path) -> str:
    return "\n".join(
        [
            "# Coding Prompt",
            "",
            f"Executor: `codex`",
            f"Run: `{context.run_id}`",
            f"Domain: `{context.domain.domain_id}`",
            f"Worktree: `{worktree_dir}`",
            "",
            "The machine prompt bundle is stored separately so the coding context is replayable and compact.",
            "",
            "## Prompt Bundle",
            f"- Prompt: `{_relative_to(bundle.prompt_path, context.run_dir)}`",
            f"- State summary: `{_relative_to(bundle.state_summary_path, context.run_dir)}`",
            f"- Output schema: `{_relative_to(bundle.output_schema_path, context.run_dir)}`",
            f"- Prompt hash: `{bundle.prompt_hash}`",
            "",
            "## Safety",
            "Manual login only when browser automation is involved. Stop on verification challenges and never bypass platform security.",
        ]
    ).rstrip() + "\n"


def _review_report_text(
    context: Any,
    review_text: str,
    changed_files: list[str],
    risk_events: list[str],
    fallback: str,
    *,
    diff_path: str,
    code_record: dict[str, Any] | None,
    test_report_text: str = "",
) -> str:
    code_changed_files = _string_list((code_record or {}).get("files_changed", []))
    all_changed_files = _dedupe(changed_files + code_changed_files)
    coder_tests = _string_list((code_record or {}).get("tests_run", []))
    blocking_risks = _dedupe(
        _string_list((code_record or {}).get("blocking_risk_events", []))
        + _string_list((code_record or {}).get("risk_events", []))
        + risk_events
    )
    non_blocking_risks = _string_list((code_record or {}).get("non_blocking_risk_events", []))
    blockers = _string_list((code_record or {}).get("blockers", []))
    status_label = "通过" if not blocking_risks and not blockers else "需要处理"
    recommendation = "可以进入测试验收 / 交付验收。" if status_label == "通过" else "先处理阻塞问题，再进入测试验收。"
    tests_passed = _review_tests_passed(coder_tests, test_report_text)
    raw_review = review_text.rstrip() or fallback or "No review output was produced."

    lines = [
        "# Review Report",
        "",
        "## 结论",
        f"- 状态：{status_label}",
        f"- 建议：{recommendation}",
        f"- 阻塞问题：{', '.join(blockers) if blockers else '无'}",
        "",
        "## 本次评审范围",
        f"- 需求：{getattr(context, 'brief', '')}",
        "- Executor：`codex review --uncommitted`",
        "- 改动文件：",
        *([f"  - `{path}`" for path in all_changed_files] if all_changed_files else ["  - 未检测到改动文件"]),
        "",
        "## 评审维度",
        f"- 功能正确性：{'通过' if not blocking_risks else '需要处理'}",
        f"- 测试覆盖：{'通过' if tests_passed else '需要补充'}",
        f"- 变更范围：{'通过' if all_changed_files else '需要处理'}",
        f"- 安全边界：{'通过' if not blocking_risks else '需要处理'}",
        "- 可维护性：通过",
        "",
        "## Findings",
        f"- Critical：{'无' if not blocking_risks else ', '.join(blocking_risks)}",
        "- Major：无",
        "- Minor：无",
        "",
        "## 测试证据",
        *([f"- {test}" for test in coder_tests] if coder_tests else ["- 未记录 AI coding 阶段测试。"]),
    ]
    if test_report_text:
        lines.extend(["- Test Report：已生成 `test_report.md`，可查看完整 verifier 复核。"])
    lines.extend(
        [
            "",
            "## Diff 证据",
            f"- Diff：{diff_path or str(((code_record or {}).get('artifacts') or {}).get('diff', '未记录'))}",
            "",
            "## Codex Review 原文",
            raw_review,
            "",
            "## 风险与阻塞",
            f"- Blocking risk：{', '.join(blocking_risks) if blocking_risks else '无'}",
            f"- Non-blocking warning：{', '.join(non_blocking_risks) if non_blocking_risks else '无'}",
            f"- Blockers：{', '.join(blockers) if blockers else '无'}",
            "",
            "## Safety Boundary",
            *[f"- {rule}" for rule in getattr(context.domain, "risk_rules", [])],
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _review_tests_passed(coder_tests: list[str], test_report_text: str) -> bool:
    evidence = "\n".join(coder_tests + [test_report_text]).lower()
    return bool(coder_tests) or "passed" in evidence or "exit `0`" in evidence or "exit 0" in evidence


def _verification_report_text(
    context: Any,
    *,
    verification_record: dict[str, Any],
    code_record: dict[str, Any] | None,
    implementation_trace: dict[str, Any] | None,
) -> str:
    status = str(verification_record.get("status", "unknown"))
    commands = [item for item in verification_record.get("commands", []) if isinstance(item, dict)]
    trace_evidence = implementation_trace.get("evidence", {}) if isinstance(implementation_trace, dict) else {}
    changed_files = _dedupe(
        _string_list((code_record or {}).get("files_changed", []))
        + _string_list(trace_evidence.get("changed_files", []))
    )
    coder_tests = _dedupe(
        _string_list((code_record or {}).get("tests_run", []))
        + _string_list(trace_evidence.get("tests_run", []))
    )
    verification_commands = _dedupe(
        _string_list((code_record or {}).get("verification_commands", []))
        + _string_list(trace_evidence.get("verification_commands", []))
        + [str(item.get("command", "")) for item in commands if item.get("command")]
    )
    blocking_risks = _dedupe(
        _string_list((code_record or {}).get("blocking_risk_events", []))
        + _string_list((code_record or {}).get("risk_events", []))
        + _string_list(verification_record.get("risk_events", []))
        + _string_list((implementation_trace or {}).get("blocking_risk_events", []))
        + _string_list((implementation_trace or {}).get("risk_events", []))
    )
    non_blocking_risks = _dedupe(
        _string_list((code_record or {}).get("non_blocking_risk_events", []))
        + _string_list((implementation_trace or {}).get("non_blocking_risk_events", []))
    )
    blockers = _dedupe(
        _string_list((code_record or {}).get("blockers", []))
        + _string_list((implementation_trace or {}).get("blockers", []))
    )
    diff_path = str(trace_evidence.get("diff_path", "")) or str(((code_record or {}).get("artifacts") or {}).get("diff", ""))
    status_label = "通过" if status == "completed" and not blocking_risks and not blockers else "需要处理"
    recommendation = "可以进入 Review / 交付验收。" if status_label == "通过" else "先处理阻塞或失败测试，再进入交付验收。"

    lines = [
        "# Test Report",
        "",
        "## 结论",
        f"- 状态：{status_label}",
        f"- 建议：{recommendation}",
        f"- 阻塞：{', '.join(blockers) if blockers else '无'}",
        "",
        "## 本次验证目标",
        f"- 需求：{getattr(context, 'brief', '')}",
        f"- 运行：{getattr(context, 'run_id', '')}",
        f"- Domain：{getattr(getattr(context, 'domain', None), 'domain_id', '')}",
        "",
        "## 代码变化证据",
        *([f"- `{path}`" for path in changed_files] if changed_files else ["- 未记录 changed files。"]),
        "",
        "## AI 自测证据",
        *([f"- {test}" for test in coder_tests] if coder_tests else ["- 未记录 AI coding 阶段自测。"]),
        "",
        "## Verifier 复核命令",
    ]
    for result in commands:
        lines.append(f"- `{result['command']}` -> exit `{result['exit_code']}`")
    if not commands:
        lines.append("- 未记录 verifier 复核命令。")
    lines.extend(
        [
            "",
            "## 执行流程证据",
            f"- Trace 状态：{str((implementation_trace or {}).get('status', 'missing'))}",
            f"- Diff：{diff_path or '未记录'}",
            f"- Worktree：{verification_record.get('worktree_path', '')}",
            f"- Exit Code：{trace_evidence.get('exit_code', '未记录')}",
            "",
            "## Verification Commands",
            *([f"- `{command}`" for command in verification_commands] if verification_commands else ["- 未记录 verification command。"]),
            "",
            "## 风险与阻塞",
            f"- Blocking risk：{', '.join(blocking_risks) if blocking_risks else '无'}",
            f"- Non-blocking warning：{', '.join(non_blocking_risks) if non_blocking_risks else '无'}",
            f"- Blockers：{', '.join(blockers) if blockers else '无'}",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _new_implementation_trace(context: Any, bundle: CodexPromptBundle) -> dict[str, Any]:
    now = now_iso()
    return {
        "schema_version": 1,
        "run_id": context.run_id,
        "stage": "coder",
        "status": "running",
        "current_step": "",
        "updated_at": now,
        "inputs": _implementation_trace_inputs(context),
        "steps": [
            {
                "id": step_id,
                "title": title,
                "status": "pending",
                "started_at": "",
                "finished_at": "",
                "summary": "",
                "artifacts": [],
            }
            for step_id, title in IMPLEMENTATION_TRACE_STEPS
        ],
        "evidence": {
            "changed_files": [],
            "tests_run": [],
            "verification_commands": bundle.verification_commands,
            "diff_path": "",
            "exit_code": None,
        },
        "risk_events": [],
        "blockers": [],
        "next_action": "",
    }


def _implementation_trace_inputs(context: Any) -> list[dict[str, Any]]:
    run_dir = Path(getattr(context, "run_dir", "."))
    repo_root = Path(getattr(context, "repo_root", "."))
    inputs: list[dict[str, Any]] = []
    for path in UPSTREAM_CONTEXT_ARTIFACTS:
        scope = "repo" if path in {"AGENTS.md", "DESIGN.md"} else "run"
        target = repo_root / path if scope == "repo" else run_dir / path
        inputs.append(
            {
                "title": IMPLEMENTATION_TRACE_INPUT_TITLES.get(path, path),
                "path": path,
                "scope": scope,
                "exists": target.exists(),
            }
        )
    return inputs


def _trace_step(trace: dict[str, Any], step_id: str, status: str, summary: str, artifacts: list[str] | None = None) -> None:
    now = now_iso()
    trace["current_step"] = step_id
    trace["updated_at"] = now
    if status == "failed":
        trace["status"] = "failed"
    elif trace.get("status") != "failed":
        trace["status"] = "running"
    for step in trace.get("steps", []):
        if step.get("id") != step_id:
            continue
        if not step.get("started_at"):
            step["started_at"] = now
        if status in {"completed", "failed"}:
            step["finished_at"] = now
        step["status"] = status
        step["summary"] = summary
        if artifacts is not None:
            step["artifacts"] = artifacts
        break


def _trace_fail(trace: dict[str, Any], step_id: str, summary: str, risk_events: list[str], blockers: list[str], next_action: str) -> None:
    _trace_step(trace, step_id, "failed", summary)
    trace["status"] = "failed"
    trace["risk_events"] = risk_events
    trace["blockers"] = blockers
    trace["next_action"] = next_action


def _write_implementation_trace(path: Path, trace: dict[str, Any]) -> None:
    trace["updated_at"] = now_iso()
    write_json(path, trace)


def _read_codex_response(path: Path) -> tuple[dict[str, Any], list[str]]:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}, ["codex_missing_last_message"]
    try:
        payload = read_json(path)
    except Exception as exc:  # noqa: BLE001 - turns schema failure into an explicit risk event.
        return {}, [f"codex_response_parse_failed:{type(exc).__name__}"]
    events: list[str] = []
    for field_name in REQUIRED_CODEX_RESPONSE_FIELDS:
        if field_name not in payload:
            events.append(f"codex_response_missing_field:{field_name}")
    return payload if isinstance(payload, dict) else {}, events


def _changed_files(worktree_dir: Path) -> list[str]:
    if not _is_git_worktree(worktree_dir):
        return []
    files: set[str] = set()
    for command in (
        ["git", "diff", "--name-only"],
        ["git", "diff", "--cached", "--name-only"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ):
        completed = subprocess.run(command, cwd=worktree_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        if completed.returncode == 0:
            files.update(line.strip() for line in completed.stdout.splitlines() if line.strip())
    return sorted(files)


def _write_diff_artifacts(worktree_dir: Path, codex_dir: Path) -> tuple[Path, Path]:
    diff_path = codex_dir / "diff.patch"
    status_path = codex_dir / "git_status.txt"
    if not _is_git_worktree(worktree_dir):
        diff_path.write_text("", encoding="utf-8")
        status_path.write_text("worktree missing\n", encoding="utf-8")
        return diff_path, status_path

    diff = _git_text(["git", "diff", "--patch", "--binary"], cwd=worktree_dir)
    cached = _git_text(["git", "diff", "--cached", "--patch", "--binary"], cwd=worktree_dir)
    untracked_patches = []
    for file_name in _git_lines(["git", "ls-files", "--others", "--exclude-standard"], cwd=worktree_dir):
        file_path = worktree_dir / file_name
        if file_path.is_file() and file_path.stat().st_size <= 200_000:
            untracked_patches.append(_git_text_allow_diff(["git", "diff", "--no-index", "--", "/dev/null", file_name], cwd=worktree_dir))
    status = _git_text(["git", "status", "--short"], cwd=worktree_dir)
    diff_path.write_text("\n".join(item for item in [diff, cached, *untracked_patches] if item).strip() + "\n", encoding="utf-8")
    status_path.write_text(status, encoding="utf-8")
    return diff_path, status_path


def _scan_implementation_risks(text: str) -> list[str]:
    lowered = text.lower()
    return [f"prohibited_implementation_pattern:{pattern}" for pattern in IMPLEMENTATION_RISK_PATTERNS if pattern in lowered]


def classify_codex_risk_events(events: list[str]) -> tuple[list[str], list[str]]:
    blocking: list[str] = []
    non_blocking: list[str] = []
    for event in events:
        if _is_non_blocking_codex_risk_note(event):
            non_blocking.append(event)
        else:
            blocking.append(event)
    return _dedupe(blocking), _dedupe(non_blocking)


def _is_non_blocking_codex_risk_note(event: str) -> bool:
    lowered = event.lower()
    if lowered.startswith("note:") or lowered.startswith("non_blocking:") or lowered.startswith("non-blocking:"):
        return True
    if lowered.startswith("no ") and all(marker in lowered for marker in ("scraping", "captcha", "proxy")):
        return True
    return any(all(marker in lowered for marker in marker_set) for marker_set in NON_BLOCKING_CODEX_RISK_NOTE_MARKERS)


def classify_codex_failure(text: str, exit_code: int, stage: str) -> str:
    if exit_code == 0:
        return ""
    lowered = text.lower()
    provider_markers = [
        "401",
        "403",
        "unauthorized",
        "forbidden",
        "api key",
        "invalid key",
        "provider",
        "rate limit",
        "quota",
        "base_url",
        "connection",
        "tls",
        "timeout",
    ]
    cli_arg_markers = [
        "unrecognized option",
        "unexpected argument",
        "invalid value",
        "no such file or directory",
        "os error 2",
        "usage:",
    ]
    test_markers = [
        "failed",
        "failure",
        "error:",
        "traceback",
        "assertionerror",
        "pytest",
        "unittest",
    ]
    if any(marker in lowered for marker in provider_markers):
        return "provider_error"
    if any(marker in lowered for marker in cli_arg_markers) or exit_code == 2:
        return "codex_cli_args"
    if stage == "reviewer":
        return "review_failed"
    if stage == "verifier" or any(marker in lowered for marker in test_markers):
        return "test_failed"
    return "codex_runtime_error"


def _previous_code_record(context: Any) -> dict[str, Any] | None:
    path = Path(context.run_dir) / "code_run_record.json"
    if not path.exists():
        return None
    try:
        payload = read_json(path)
    except Exception:  # noqa: BLE001 - previous state is optional context.
        return None
    return payload if isinstance(payload, dict) else None


def _previous_implementation_trace(context: Any) -> dict[str, Any] | None:
    path = Path(context.run_dir) / IMPLEMENTATION_TRACE_PATH
    if not path.exists():
        return None
    try:
        payload = read_json(path)
    except Exception:  # noqa: BLE001 - trace is optional verification context.
        return None
    return payload if isinstance(payload, dict) else None


def _read_optional_run_text(context: Any, path: str) -> str:
    target = Path(context.run_dir) / path
    if not target.exists() or not target.is_file():
        return ""
    return target.read_text(encoding="utf-8", errors="replace")


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return [str(value)]


def _sha256_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _relative_to(path: Path, run_dir: Path) -> str:
    try:
        return path.resolve().relative_to(run_dir.resolve()).as_posix()
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _is_git_worktree(path: Path) -> bool:
    return path.exists() and ((path / ".git").exists() or (path / ".git").is_file())


def _run_checked(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)


def _git_text(command: list[str], cwd: Path) -> str:
    completed = subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    return completed.stdout if completed.returncode == 0 else completed.stderr


def _git_text_allow_diff(command: list[str], cwd: Path) -> str:
    completed = subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    return completed.stdout or completed.stderr


def _git_lines(command: list[str], cwd: Path) -> list[str]:
    completed = subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]
