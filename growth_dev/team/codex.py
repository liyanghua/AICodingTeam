from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import difflib
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

from ..utils import ensure_dir, now_iso, read_json, write_json
from .yaml_io import load_yaml_subset


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
TASK_ALLOWED_PATH_MARKERS = ("allowed_paths", "allowed paths", "allowed_files", "allowed files", "允许路径")
TASK_ALLOWED_PATH_SAFE_ROOTS = ("third_party", "tests", "domains", "growth_dev", "dashboard", "skills", "docs", "tasks", "generated_apps", ".github")
TASK_ALLOWED_PATH_SAFE_ROOT_FILES = ("README.md", "AGENTS.md", "DESIGN.md", "pyproject.toml")
TASK_ALLOWED_PATH_FORBIDDEN_PREFIXES = (
    "runs/",
    "third_party/mobile_asset_center/data/",
    "third_party/mobile_image_workbench/runs/",
    "third_party/xhs_collector/runs/",
)
TASK_ALLOWED_PATH_FORBIDDEN_SUFFIXES = (".key", ".pem", ".p12", ".pfx")
TASK_ALLOWED_PATH_PATTERN = re.compile(
    r"(?<![\w./-])(?:(?:third_party|tests|domains|growth_dev|dashboard|skills|docs|tasks|generated_apps|\.github)(?:/[\w.-]+)+/?|(?:README|AGENTS|DESIGN)\.md|pyproject\.toml)(?![\w./-])"
)
UPSTREAM_CONTEXT_ARTIFACTS = [
    "task.yaml",
    "context.md",
    "input_prd.md",
    "requirements/normalized_prd.md",
    "app_contract.json",
    "benchmark_context.md",
    "benchmark_context.json",
    "reference_app_index.md",
    "preview_instructions.md",
    "requirements/capability_boundary.md",
    "planning/tdd_plan.md",
    "prd.md",
    "tech_spec.md",
    "ui_spec.md",
    "eval.md",
    "AGENTS.md",
    "DESIGN.md",
]

IMPLEMENTATION_TRACE_PATH = "codex/implementation_trace.json"
FAILURE_CLASSIFICATION_JSON_PATH = "codex/failure_classification.json"
FAILURE_CLASSIFICATION_MD_PATH = "codex/failure_classification.md"
SLICE_LOOP_STATE_PATH = "codex/slice_loop_state.json"
IMPLEMENTATION_COMPLETION_GATE_JSON_PATH = "implementation_completion_gate.json"
IMPLEMENTATION_COMPLETION_GATE_MD_PATH = "implementation_completion_gate.md"
APP_RUNTIME_VERIFICATION_PATH = "codex/app_runtime_verification.json"
SLICE_LOOP_EXECUTION_STRATEGY = "single_codex_pass_over_planned_slices_v1"
BENCHMARK_FIX_SLICE_DISABLE_ENV = "BENCHMARK_FIX_SLICE_DISABLE"
BENCHMARK_FIX_SLICE_MAX_ROUNDS = 1
BENCHMARK_FIX_SLICE_PROMPT_PATH = "codex/fix_slice_prompt.md"
BENCHMARK_FIX_SLICE_STDOUT_PATH = "codex/fix_stdout.jsonl"
BENCHMARK_FIX_SLICE_STDERR_PATH = "codex/fix_stderr.log"
BENCHMARK_FIX_SLICE_LAST_MESSAGE_PATH = "codex/last_message_fix.json"
BENCHMARK_FIX_SLICE_COMMAND_PATH = "codex/fix_command.json"
BENCHMARK_FIX_SLICE_STATE_PATH = "codex/fix_state_summary.md"
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
    "input_prd.md": "原始 PRD",
    "requirements/normalized_prd.md": "标准化 PRD",
    "app_contract.json": "应用生成契约",
    "benchmark_context.md": "Benchmark 能力契约",
    "reference_app_index.md": "参考应用结构索引",
    "preview_instructions.md": "本地预览说明",
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

SAFE_RISK_CONTEXT_MARKERS = [
    "prohibited",
    "forbidden",
    "unsupported",
    "do not",
    "must not",
    "no_",
    "not allowed",
    "禁止",
    "不支持",
    "不允许",
    "不得",
]

NON_BLOCKING_CODEX_RISK_NOTE_MARKERS = [
    ("outside the high-level allowed list", "nearby supporting location"),
    ("outside the high-level allowed list", "required to implement"),
    ("nearby_supporting", "required"),
    ("nearby supporting", "required"),
    ("modified tests/", "supporting test boundary", "no runs", "env-file", "remote key"),
    ("preview bind", "sandbox", "eperm"),
    ("provider is not configured", "setup error", "does not persist secrets"),
    ("external image provider", "explicit", "server-side", "no hidden network"),
    ("image provider capability", "explicit", "server-side", "no hidden network"),
    ("declared verification commands passed", "eperm"),
    ("captcha", "proxy", "fingerprint"),
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
        slice_loop = _new_slice_loop_state(context, bundle)
        slice_loop_output_paths = _write_initial_slice_loop_artifacts(self.run_dir, self.codex_dir, slice_loop)
        _trace_step(trace, "prepare_context", "running", "正在生成 AI coding 所需的上下文和提示包。")
        _write_implementation_trace(trace_path, trace)
        human_prompt = _human_coding_prompt(context, bundle, self.worktree_dir)
        output_paths = [context.write_text("coding_prompt.md", human_prompt)]
        output_paths.extend(bundle.relative_paths(self.run_dir))
        output_paths.append(IMPLEMENTATION_TRACE_PATH)
        output_paths.extend(slice_loop_output_paths)
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
            _attach_slice_loop_artifacts(record, slice_loop_output_paths)
            _finalize_slice_loop_failure(self.run_dir, self.codex_dir, slice_loop, "codex_binary_missing")
            _trace_fail(trace, "check_executor", "Codex 执行器不可用。", record["risk_events"], record["blockers"], "fix_executor")
            trace["failure_classification"] = record.get("failure_classification", {})
            _write_implementation_trace(trace_path, trace)
            output_paths.extend([FAILURE_CLASSIFICATION_JSON_PATH, FAILURE_CLASSIFICATION_MD_PATH])
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
            _attach_slice_loop_artifacts(record, slice_loop_output_paths)
            _finalize_slice_loop_failure(self.run_dir, self.codex_dir, slice_loop, record["risk_events"][0])
            _trace_fail(trace, "prepare_worktree", "隔离工作区准备失败。", record["risk_events"], record["blockers"], "fix_worktree")
            trace["failure_classification"] = record.get("failure_classification", {})
            _write_implementation_trace(trace_path, trace)
            output_paths.extend([FAILURE_CLASSIFICATION_JSON_PATH, FAILURE_CLASSIFICATION_MD_PATH])
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
        diff_policy_hits = _scan_implementation_risks(diff_path.read_text(encoding="utf-8") if diff_path.exists() else "")
        blockers = _string_list(response.get("blockers", []))
        response_blockers = list(blockers)
        failure_category = classify_codex_failure(completed.stderr, completed.returncode, "coder")
        files_changed = sorted(set(changed_files + _string_list(response.get("files_changed", []))))
        tests_run = _string_list(response.get("tests_run", []))
        boundary_violations = _unrelated_changed_files(changed_files, bundle.allowed_paths)
        benchmark_evaluation = _evaluate_benchmark_parity_if_needed(context, worktree_dir)
        app_runtime_verification = _run_app_runtime_verification_if_needed(
            context=context,
            commands=bundle.verification_commands,
            worktree_dir=worktree_dir,
            codex_dir=self.codex_dir,
            run_dir=self.run_dir,
            env=self._process_env(),
            timeout_seconds=min(self.config.timeout_seconds, 60),
        )
        app_runtime_events = _string_list(app_runtime_verification.get("blocking_events", []))
        if app_runtime_events and benchmark_evaluation.get("enabled"):
            benchmark_evaluation = {
                **benchmark_evaluation,
                "blocking_events": _dedupe(_string_list(benchmark_evaluation.get("blocking_events", [])) + app_runtime_events),
                "artifacts": _dedupe(_string_list(benchmark_evaluation.get("artifacts", [])) + [APP_RUNTIME_VERIFICATION_PATH]),
            }
        first_round_state = {
            "exit_code": completed.returncode,
            "summary": str(response.get("summary", "")),
            "files_changed": files_changed,
        }
        fix_slice_result = self._maybe_run_benchmark_fix_slice(
            context=context,
            bundle=bundle,
            worktree_dir=worktree_dir,
            previous_record=first_round_state,
            first_evaluation=benchmark_evaluation,
        )
        fix_slice_record: dict[str, Any] | None = None
        if fix_slice_result.get("attempted"):
            fix_slice_record = fix_slice_result.get("fix_record")
            new_evaluation = fix_slice_result.get("new_evaluation") or benchmark_evaluation
            benchmark_evaluation = new_evaluation
            fix_response = fix_slice_result.get("response") or {}
            response = {**response, **{k: v for k, v in fix_response.items() if v not in (None, "")}}
            response_risk_events = _string_list(response.get("risk_events", []))
            response_blocking_risk_events, non_blocking_risk_events = classify_codex_risk_events(response_risk_events)
            blockers = _string_list(response.get("blockers", []))
            response_blockers = list(blockers)
            changed_files = _changed_files(worktree_dir)
            diff_path, status_path = _write_diff_artifacts(worktree_dir, self.codex_dir)
            diff_policy_hits = _scan_implementation_risks(diff_path.read_text(encoding="utf-8") if diff_path.exists() else "")
            files_changed = sorted(set(changed_files + _string_list(response.get("files_changed", []))))
            tests_run = _string_list(response.get("tests_run", []))
            boundary_violations = _unrelated_changed_files(changed_files, bundle.allowed_paths)
            app_runtime_verification = _run_app_runtime_verification_if_needed(
                context=context,
                commands=bundle.verification_commands,
                worktree_dir=worktree_dir,
                codex_dir=self.codex_dir,
                run_dir=self.run_dir,
                env=self._process_env(),
                timeout_seconds=min(self.config.timeout_seconds, 60),
            )
            app_runtime_events = _string_list(app_runtime_verification.get("blocking_events", []))
            if app_runtime_events and benchmark_evaluation.get("enabled"):
                benchmark_evaluation = {
                    **benchmark_evaluation,
                    "blocking_events": _dedupe(_string_list(benchmark_evaluation.get("blocking_events", [])) + app_runtime_events),
                    "artifacts": _dedupe(_string_list(benchmark_evaluation.get("artifacts", [])) + [APP_RUNTIME_VERIFICATION_PATH]),
                }
            fix_exit_code = int(fix_slice_result.get("exit_code", 0))
            validation_events = list(fix_slice_result.get("validation_events") or validation_events)
            completed = subprocess.CompletedProcess(completed.args, fix_exit_code, completed.stdout, completed.stderr)
            failure_category = classify_codex_failure(completed.stderr, fix_exit_code, "coder")
            if fix_slice_result.get("status") == "failed":
                blockers.append(f"benchmark_fix_slice_failed:{fix_slice_result.get('reason', 'unknown')}")
                response_blocking_risk_events = _dedupe(
                    response_blocking_risk_events
                    + [f"benchmark_fix_slice_failed:{fix_slice_result.get('reason', 'unknown')}"]
                )
        classification = _build_failure_classification(
            run_id=context.run_id,
            exit_code=completed.returncode,
            validation_events=validation_events,
            changed_files=files_changed,
            tests_run=tests_run,
            codex_blockers=response_blockers,
            codex_risk_events=response_risk_events,
            codex_blocking_risk_events=response_blocking_risk_events
            + _string_list(benchmark_evaluation.get("blocking_events", []))
            + app_runtime_events,
            codex_non_blocking_risk_events=non_blocking_risk_events + _string_list(benchmark_evaluation.get("warnings", [])),
            diff_policy_hits=diff_policy_hits,
            allowed_paths=bundle.allowed_paths,
            boundary_violations=boundary_violations,
            no_changed_files=not changed_files,
        )
        classification_json_path = self.codex_dir / "failure_classification.json"
        classification_md_path = self.codex_dir / "failure_classification.md"
        write_json(classification_json_path, classification)
        classification_md_path.write_text(_failure_classification_markdown(classification), encoding="utf-8")
        risk_events = _string_list(classification.get("blocking_events", []))
        non_blocking_risk_events = _string_list(classification.get("warnings", []))
        blockers = list(response_blockers)
        if completed.returncode != 0:
            blockers.append(f"codex exited with {completed.returncode}")
        if not changed_files:
            blockers.append("no_changed_files")
        blockers = _dedupe(blockers)
        status = "failed" if classification.get("classification_decision") == "failed" else "completed"
        trace["evidence"].update(
            {
                "changed_files": files_changed,
                "tests_run": tests_run,
                "verification_commands": bundle.verification_commands,
                "diff_path": _relative_to(diff_path, self.run_dir),
                "exit_code": completed.returncode,
                "failure_classification": FAILURE_CLASSIFICATION_JSON_PATH,
                **({"app_runtime_verification": APP_RUNTIME_VERIFICATION_PATH} if app_runtime_verification else {}),
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
            "failure_classification": classification,
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
                "failure_classification": FAILURE_CLASSIFICATION_JSON_PATH,
                **({"app_runtime_verification": APP_RUNTIME_VERIFICATION_PATH} if app_runtime_verification else {}),
                **(
                    {
                        "benchmark_diff": "benchmark_diff.md",
                        "agqs_score": "agqs_score.json",
                    }
                    if benchmark_evaluation.get("enabled")
                    else {}
                ),
            },
        }
        completion_paths: list[str] = []
        completion_gate: dict[str, Any] = {}
        if slice_loop.get("enabled"):
            completion_gate = _write_completion_gate(
                self.run_dir,
                slice_loop,
                status=status,
                files_changed=files_changed,
                tests_run=tests_run,
                verification_commands=bundle.verification_commands,
                risk_events=risk_events,
                blockers=blockers,
                allowed_paths=bundle.allowed_paths,
            )
            completion_paths = [IMPLEMENTATION_COMPLETION_GATE_JSON_PATH, IMPLEMENTATION_COMPLETION_GATE_MD_PATH]
            output_paths.extend(completion_paths)
            _finalize_slice_loop_success(
                self.run_dir,
                self.codex_dir,
                slice_loop,
                status=status,
                files_changed=files_changed,
                tests_run=tests_run,
                verification_commands=bundle.verification_commands,
                risk_events=risk_events,
                blockers=blockers,
                diff_path=_relative_to(diff_path, self.run_dir),
                completion_gate=completion_gate,
            )
        _attach_slice_loop_artifacts(record, slice_loop_output_paths + completion_paths)
        if fix_slice_record is not None:
            record["benchmark_fix_slice"] = fix_slice_record
            output_paths.extend(_string_list(fix_slice_result.get("output_paths", [])))
            record["artifacts"]["benchmark_fix_slice_prompt"] = fix_slice_record["artifacts"]["prompt"]
            record["artifacts"]["benchmark_fix_slice_last_message"] = fix_slice_record["artifacts"]["last_message"]
        trace["status"] = status
        trace["current_step"] = "finalize_result"
        trace["risk_events"] = risk_events
        trace["blocking_risk_events"] = risk_events
        trace["non_blocking_risk_events"] = non_blocking_risk_events
        trace["blockers"] = blockers
        trace["failure_classification"] = classification
        trace["next_action"] = str(response.get("next_action", ""))
        _trace_step(
            trace,
            "finalize_result",
            status,
            "AI 实现结果已整理完成。" if status == "completed" else "AI 实现结果需要处理阻塞或风险。",
            artifacts=["code_run_record.json", FAILURE_CLASSIFICATION_JSON_PATH],
        )
        trace["status"] = status
        _write_implementation_trace(trace_path, trace)
        output_paths.extend(
            [
                _relative_to(diff_path, self.run_dir),
                _relative_to(status_path, self.run_dir),
                FAILURE_CLASSIFICATION_JSON_PATH,
                FAILURE_CLASSIFICATION_MD_PATH,
            ]
        )
        if app_runtime_verification:
            output_paths.append(APP_RUNTIME_VERIFICATION_PATH)
        output_paths.extend(_string_list(benchmark_evaluation.get("artifacts", [])))
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

    def run_app_repair(self, context: Any) -> CodexStageResult:
        """Prepare a candidate repair diff for the published generated app.

        This is intentionally separate from ``run_coder``: it seeds the current
        published snapshot into the isolated worktree, lets Codex repair only
        ``generated_apps/<slug>/``, and returns a candidate diff. It does not
        promote the result back into ``runs/<run_id>/generated_apps``.
        """
        bundle = self.write_prompt_bundle("app_repair", context)
        output_paths = bundle.relative_paths(self.run_dir)
        app_slug = str((getattr(context, "inputs", {}) or {}).get("app_slug") or "").strip()
        if not app_slug:
            record = self._failure_record("app_repair", bundle, "app_slug_missing")
            output_paths.append(context.write_json("codex/app_repair_result.json", record))
            return CodexStageResult("failed", output_paths, record["risk_events"], record["summary"], record)

        published_app_dir = self.run_dir / "generated_apps" / app_slug
        publish_record_path = published_app_dir / "app_publish.json"
        if not published_app_dir.exists() or not publish_record_path.exists():
            record = self._failure_record("app_repair", bundle, "app_not_published")
            output_paths.append(context.write_json("codex/app_repair_result.json", record))
            return CodexStageResult("failed", output_paths, record["risk_events"], record["summary"], record)

        if not self._binary_available():
            record = self._failure_record("app_repair", bundle, "codex_binary_missing", extra={"binary": self.config.binary})
            output_paths.append(context.write_json("codex/app_repair_result.json", record))
            return CodexStageResult("failed", output_paths, record["risk_events"], record["summary"], record)

        try:
            worktree_dir = self.prepare_worktree()
            candidate_dir, baseline_dir = _seed_app_repair_candidate(
                published_app_dir=published_app_dir,
                worktree_dir=worktree_dir,
                codex_dir=self.codex_dir,
                app_slug=app_slug,
            )
        except Exception as exc:  # noqa: BLE001 - persisted for UI inspection.
            record = self._failure_record("app_repair", bundle, f"app_repair_seed_failed:{type(exc).__name__}:{exc}")
            output_paths.append(context.write_json("codex/app_repair_result.json", record))
            return CodexStageResult("failed", output_paths, record["risk_events"], record["summary"], record)

        command = build_codex_exec_command(
            self.config,
            worktree_dir=worktree_dir,
            run_dir=self.run_dir,
            output_schema_path=bundle.output_schema_path,
            output_last_message_path=bundle.output_last_message_path,
        )
        write_json(bundle.command_path, {"command": command, "cwd": str(worktree_dir), "created_at": now_iso()})
        completed = self._run_process(command, bundle.prompt_path.read_text(encoding="utf-8"), worktree_dir, bundle.stdout_path, bundle.stderr_path)
        response, validation_events = _read_codex_response(bundle.output_last_message_path)

        diff_path = self.codex_dir / "app_repair_diff.patch"
        changed_files = _write_directory_diff(baseline_dir, candidate_dir, diff_path, app_slug=app_slug)
        verification_record = _run_app_repair_verification(
            commands=bundle.verification_commands,
            app_dir=candidate_dir,
            codex_dir=self.codex_dir,
            run_dir=self.run_dir,
            env=self._process_env(),
            timeout_seconds=min(self.config.timeout_seconds, 60),
        )
        verification_events = _string_list(verification_record.get("risk_events", []))
        blockers = _string_list(response.get("blockers", []))
        risk_events = _dedupe(validation_events + verification_events)
        if completed.returncode != 0:
            blockers.append(f"codex exited with {completed.returncode}")
            risk_events.append(f"codex_exit_code:{completed.returncode}")
        if not changed_files:
            blockers.append("no_changed_files")
            risk_events.append("no_changed_files")
        status = "prepared" if not risk_events and not blockers else "failed"
        record = {
            "agent": "app_repair",
            "executor": "codex",
            "status": status,
            "app_slug": app_slug,
            "candidate_dir": _relative_to(candidate_dir, self.run_dir),
            "baseline_dir": _relative_to(baseline_dir, self.run_dir),
            "diff_path": _relative_to(diff_path, self.run_dir),
            "changed_files": changed_files,
            "summary": str(response.get("summary") or "Code Agent repair candidate prepared."),
            "tests_run": _string_list(response.get("tests_run", [])),
            "verification_results": verification_record.get("commands", []),
            "risk_events": _dedupe(risk_events),
            "blockers": _dedupe(blockers),
            "exit_code": completed.returncode,
            "prompt_hash": bundle.prompt_hash,
            "state_hash": bundle.state_hash,
            "codex_artifacts": {
                "prompt": _relative_to(bundle.prompt_path, self.run_dir),
                "state_summary": _relative_to(bundle.state_summary_path, self.run_dir),
                "last_message": _relative_to(bundle.output_last_message_path, self.run_dir),
                "stdout": _relative_to(bundle.stdout_path, self.run_dir),
                "stderr": _relative_to(bundle.stderr_path, self.run_dir),
                "command": _relative_to(bundle.command_path, self.run_dir),
                "diff": _relative_to(diff_path, self.run_dir),
                "verification": "codex/app_repair_verification.json",
            },
        }
        result_path = self.codex_dir / "app_repair_result.json"
        write_json(result_path, record)
        output_paths.extend([
            _relative_to(diff_path, self.run_dir),
            _relative_to(result_path, self.run_dir),
            "codex/app_repair_verification.json",
        ])
        return CodexStageResult(status, _dedupe(output_paths), record["risk_events"], record["summary"], record)

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

    def _maybe_run_benchmark_fix_slice(
        self,
        *,
        context: Any,
        bundle: CodexPromptBundle,
        worktree_dir: Path,
        previous_record: dict[str, Any],
        first_evaluation: dict[str, Any],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"attempted": False, "reason": "", "output_paths": []}
        if not first_evaluation.get("enabled"):
            result["reason"] = "evaluation_not_enabled"
            return result
        if previous_record.get("exit_code") != 0:
            result["reason"] = "first_round_failed"
            return result
        blocking = _string_list(first_evaluation.get("blocking_events", []))
        missing = _missing_capability_ids(blocking)
        if not missing:
            result["reason"] = "no_missing"
            return result
        if not _benchmark_fix_slice_enabled():
            result["reason"] = "disabled_env"
            return result
        if not self._binary_available():
            result["reason"] = "codex_binary_missing"
            return result
        fix_targets = _fix_slice_capability_targets(self.run_dir, missing)
        prompt_path = self.codex_dir / "fix_slice_prompt.md"
        stdout_path = self.codex_dir / "fix_stdout.jsonl"
        stderr_path = self.codex_dir / "fix_stderr.log"
        last_message_path = self.codex_dir / "last_message_fix.json"
        command_path = self.codex_dir / "fix_command.json"
        prompt_text = _build_fix_slice_prompt(
            context=context,
            bundle=bundle,
            worktree_dir=worktree_dir,
            previous_record=previous_record,
            first_evaluation=first_evaluation,
            fix_targets=fix_targets,
        )
        prompt_path.write_text(prompt_text, encoding="utf-8")
        last_message_path.write_text("", encoding="utf-8")
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        command = build_codex_exec_command(
            self.config,
            worktree_dir=worktree_dir,
            run_dir=self.run_dir,
            output_schema_path=bundle.output_schema_path,
            output_last_message_path=last_message_path,
        )
        write_json(
            command_path,
            {"command": command, "cwd": str(worktree_dir), "created_at": now_iso(), "round": 2},
        )
        completed = self._run_process(command, prompt_text, worktree_dir, stdout_path, stderr_path)
        response, validation_events = _read_codex_response(last_message_path)
        new_evaluation = _evaluate_benchmark_parity_if_needed(context, worktree_dir)
        before = list(missing)
        after_missing = _missing_capability_ids(_string_list(new_evaluation.get("blocking_events", [])))
        succeeded = (
            completed.returncode == 0
            and bool(new_evaluation.get("enabled"))
            and not after_missing
            and not validation_events
        )
        status = "completed" if succeeded else "failed"
        remediated = [cid for cid in before if cid not in after_missing]
        output_paths = [
            _relative_to(prompt_path, self.run_dir),
            _relative_to(stdout_path, self.run_dir),
            _relative_to(stderr_path, self.run_dir),
            _relative_to(last_message_path, self.run_dir),
            _relative_to(command_path, self.run_dir),
        ]
        fix_record = {
            "attempted": True,
            "status": status,
            "round": 2,
            "max_rounds": BENCHMARK_FIX_SLICE_MAX_ROUNDS + 1,
            "before_missing": before,
            "after_missing": after_missing,
            "remediated_capabilities": remediated,
            "exit_code": completed.returncode,
            "validation_events": validation_events,
            "summary": str(response.get("summary", "")),
            "files_changed": _string_list(response.get("files_changed", [])),
            "tests_run": _string_list(response.get("tests_run", [])),
            "risk_events": _string_list(response.get("risk_events", [])),
            "blockers": _string_list(response.get("blockers", [])),
            "artifacts": {
                "prompt": _relative_to(prompt_path, self.run_dir),
                "stdout": _relative_to(stdout_path, self.run_dir),
                "stderr": _relative_to(stderr_path, self.run_dir),
                "last_message": _relative_to(last_message_path, self.run_dir),
                "command": _relative_to(command_path, self.run_dir),
            },
        }
        result.update(
            {
                "attempted": True,
                "status": status,
                "reason": "" if succeeded else _fix_slice_failure_reason(completed.returncode, validation_events, after_missing),
                "fix_record": fix_record,
                "output_paths": output_paths,
                "new_evaluation": new_evaluation,
                "before_missing": before,
                "after_missing": after_missing,
                "exit_code": completed.returncode,
                "response": response,
                "validation_events": validation_events,
            }
        )
        return result

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
        classification = _build_preflight_failure_classification(self.run_dir.name, reason)
        write_json(self.codex_dir / "failure_classification.json", classification)
        (self.codex_dir / "failure_classification.md").write_text(_failure_classification_markdown(classification), encoding="utf-8")
        return {
            "agent": stage,
            "executor": "codex",
            "status": "failed",
            "summary": reason,
            "files_changed": [],
            "tests_run": [],
            "verification_commands": bundle.verification_commands,
            "risk_events": [reason],
            "blocking_risk_events": [reason],
            "non_blocking_risk_events": [],
            "blockers": [reason],
            "failure_classification": classification,
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
                "failure_classification": FAILURE_CLASSIFICATION_JSON_PATH,
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
    base_paths = _string_list(inputs.get("allowed_paths") or inputs.get("allowed_files"))
    if not base_paths:
        base_paths = _string_list(metadata.get("allowed_paths") or metadata.get("allowed_files"))
    if not base_paths:
        base_paths = list(DEFAULT_ALLOWED_PATHS)
    return _dedupe(base_paths + _task_level_allowed_paths(context) + _slice_declared_allowed_paths(context))


def _task_level_allowed_paths(context: Any) -> list[str]:
    text = _task_level_allowed_path_text(context)
    lowered = text.lower()
    if not any(marker in lowered for marker in TASK_ALLOWED_PATH_MARKERS):
        return []
    return _dedupe([path for path in TASK_ALLOWED_PATH_PATTERN.findall(text) if _is_safe_task_allowed_path(path)])


def _task_level_allowed_path_text(context: Any) -> str:
    values = [str(getattr(context, "brief", "") or "")]
    record = getattr(context, "record", None)
    if record is not None:
        values.append(str(getattr(record, "brief", "") or ""))
    return "\n".join(value for value in values if value)


def _slice_declared_allowed_paths(context: Any) -> list[str]:
    run_dir = Path(getattr(context, "run_dir", "."))
    paths: list[str] = []
    for slice_item in _read_slice_definitions(run_dir):
        paths.extend(_string_list(slice_item.get("allowed_paths", [])))
    return _dedupe([path for path in paths if _is_safe_task_allowed_path(path)])


def _is_safe_task_allowed_path(path: str) -> bool:
    normalized = path.replace("\\", "/").strip().strip("`'\".,;:，。、")
    normalized = re.sub(r"/+", "/", normalized)
    if not normalized or normalized.startswith(("/", "~")) or "://" in normalized:
        return False
    parts = [part for part in normalized.split("/") if part]
    if not parts or any(part == ".." for part in parts):
        return False
    lowered = normalized.lower()
    lowered_parts = [part.lower() for part in parts]
    if any(lowered == prefix.rstrip("/") or lowered.startswith(prefix) for prefix in TASK_ALLOWED_PATH_FORBIDDEN_PREFIXES):
        return False
    if any(part == ".env" or part.startswith(".env.") or part.endswith(".env") for part in lowered_parts):
        return False
    if lowered.endswith(TASK_ALLOWED_PATH_FORBIDDEN_SUFFIXES):
        return False
    if parts[0] in TASK_ALLOWED_PATH_SAFE_ROOTS:
        return len(parts) > 1 or normalized.endswith("/")
    return normalized in TASK_ALLOWED_PATH_SAFE_ROOT_FILES


def _verification_commands(context: Any) -> list[str]:
    app_generation_commands = _app_generation_verification_commands(context)
    if app_generation_commands:
        return app_generation_commands
    inputs = getattr(context, "inputs", {}) or {}
    domain = getattr(context, "domain", None)
    metadata = getattr(domain, "metadata", {}) or {}
    commands = _string_list(inputs.get("verification_commands") or metadata.get("verification_commands") or DEFAULT_VERIFICATION_COMMANDS)
    return _format_app_generation_command_templates(commands, context)


def _app_generation_verification_commands(context: Any) -> list[str]:
    domain = getattr(context, "domain", None)
    if getattr(domain, "domain_id", "") != "app_generation":
        return []
    contract_path = Path(getattr(context, "run_dir", ".")) / "app_contract.json"
    if not contract_path.exists():
        return []
    try:
        contract = read_json(contract_path)
    except Exception:  # noqa: BLE001 - fall back to domain metadata.
        return []
    commands = _string_list(contract.get("verification_commands") if isinstance(contract, dict) else [])
    return _format_app_generation_command_templates(commands, context)


def _run_app_runtime_verification_if_needed(
    *,
    context: Any,
    commands: list[str],
    worktree_dir: Path,
    codex_dir: Path,
    run_dir: Path,
    env: dict[str, str],
    timeout_seconds: int,
) -> dict[str, Any]:
    domain = getattr(context, "domain", None)
    if getattr(domain, "domain_id", "") != "app_generation":
        return {}
    safe_commands = _app_runtime_safe_commands(commands)
    if not safe_commands:
        return {}
    results: list[dict[str, Any]] = []
    blocking_events: list[str] = []
    for index, command in enumerate(safe_commands, start=1):
        stdout_path = codex_dir / f"app_runtime_verify_{index}_stdout.log"
        stderr_path = codex_dir / f"app_runtime_verify_{index}_stderr.log"
        started_at = now_iso()
        try:
            completed = subprocess.run(
                shlex.split(command),
                cwd=worktree_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_seconds,
                check=False,
                env=env,
            )
            stdout = completed.stdout
            stderr = completed.stderr
            exit_code = completed.returncode
        except Exception as exc:  # noqa: BLE001 - persisted as verification evidence.
            stdout = ""
            stderr = f"{type(exc).__name__}: {exc}"
            exit_code = 1
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        if exit_code != 0:
            blocking_events.append(f"app_runtime_verification_failed:{command}:{exit_code}")
        results.append(
            {
                "command": command,
                "exit_code": exit_code,
                "started_at": started_at,
                "finished_at": now_iso(),
                "stdout_path": _relative_to(stdout_path, run_dir),
                "stderr_path": _relative_to(stderr_path, run_dir),
            }
        )
    record = {
        "schema_version": 1,
        "status": "passed" if not blocking_events else "failed",
        "commands": results,
        "blocking_events": blocking_events,
        "worktree_path": str(worktree_dir),
    }
    write_json(codex_dir / "app_runtime_verification.json", record)
    return record


def _app_runtime_safe_commands(commands: list[str]) -> list[str]:
    safe: list[str] = []
    for command in commands:
        try:
            parts = shlex.split(command)
        except ValueError:
            continue
        if len(parts) == 3 and parts[0] == "node" and parts[1] == "--check" and parts[2].startswith("generated_apps/"):
            safe.append(command)
            continue
        if len(parts) == 2 and parts[0] == "node" and parts[1].startswith("generated_apps/") and parts[1].endswith("/runtime_smoke.js"):
            safe.append(command)
    return _dedupe(safe)


def _evaluate_benchmark_parity_if_needed(context: Any, worktree_dir: Path) -> dict[str, Any]:
    domain = getattr(context, "domain", None)
    if getattr(domain, "domain_id", "") != "app_generation":
        return {"enabled": False, "blocking_events": [], "warnings": [], "artifacts": []}
    contract_path = Path(getattr(context, "run_dir", ".")) / "app_contract.json"
    if not contract_path.exists():
        return {"enabled": False, "blocking_events": [], "warnings": [], "artifacts": []}
    contract = read_json(contract_path)
    if contract.get("quality_mode") != "benchmark_parity":
        return {"enabled": False, "blocking_events": [], "warnings": [], "artifacts": []}
    from .app_generation import evaluate_benchmark_parity

    return evaluate_benchmark_parity(run_dir=Path(getattr(context, "run_dir", ".")), worktree_dir=worktree_dir, contract=contract)


def _format_app_generation_command_templates(commands: list[str], context: Any) -> list[str]:
    inputs = getattr(context, "inputs", {}) or {}
    app_slug = str(inputs.get("app_slug", "") or "").strip()
    if not app_slug:
        return commands
    return [command.replace("{app_slug}", app_slug) for command in commands]


def _benchmark_fix_slice_enabled() -> bool:
    return os.environ.get(BENCHMARK_FIX_SLICE_DISABLE_ENV, "").strip() not in {"1", "true", "True", "yes", "on"}


def _fix_slice_failure_reason(exit_code: int, validation_events: list[str], after_missing: list[str]) -> str:
    if exit_code != 0:
        return f"codex_exit:{exit_code}"
    if validation_events:
        return f"response_invalid:{validation_events[0]}"
    if after_missing:
        return f"still_missing:{','.join(after_missing)}"
    return "unknown"


def _missing_capability_ids(blocking_events: list[str]) -> list[str]:
    prefix = "benchmark_parity_missing:"
    missing: list[str] = []
    for event in blocking_events:
        if not isinstance(event, str):
            continue
        if event.startswith(prefix):
            cid = event[len(prefix):].strip()
            if cid and cid != "secret_leak" and cid != "generated_app_dir":
                missing.append(cid)
        if event.startswith("app_runtime_verification_failed:"):
            missing.append("runtime_startup_smoke")
    return _dedupe(missing)


def _fix_slice_capability_targets(
    run_dir: Path,
    missing_capability_ids: list[str],
) -> list[dict[str, Any]]:
    benchmark_path = run_dir / "benchmark_context.json"
    capabilities: list[dict[str, Any]] = []
    if benchmark_path.exists():
        try:
            payload = read_json(benchmark_path)
        except Exception:  # noqa: BLE001 - fallback to empty
            payload = {}
        if isinstance(payload, dict):
            capabilities = [item for item in payload.get("required_capabilities", []) if isinstance(item, dict)]
    capability_by_id = {str(item.get("id", "")): item for item in capabilities}
    index_path = run_dir / "reference_app_index.json"
    capability_files: dict[str, list[str]] = {}
    if index_path.exists():
        try:
            index_payload = read_json(index_path)
        except Exception:  # noqa: BLE001
            index_payload = {}
        if isinstance(index_payload, dict):
            for item in index_payload.get("capability_to_files", []) or []:
                if isinstance(item, dict):
                    cid = str(item.get("capability_id", ""))
                    files = [str(value) for value in (item.get("files") or []) if str(value).strip()]
                    capability_files[cid] = files
    targets: list[dict[str, Any]] = []
    for cid in missing_capability_ids:
        cap = capability_by_id.get(cid, {})
        if not cap:
            cap = _synthetic_fix_slice_capability(cid)
        targets.append(
            {
                "id": cid,
                "label": cap.get("label", cid),
                "expected_behavior": cap.get("expected_behavior", ""),
                "detection_hints": list(((cap.get("detection") or {}) if isinstance(cap.get("detection"), dict) else {}).get("match_any", []) or []),
                "evidence_files": list(((cap.get("detection") or {}) if isinstance(cap.get("detection"), dict) else {}).get("evidence_files", []) or []),
                "reference_files": capability_files.get(cid, []),
            }
        )
    return targets


def _synthetic_fix_slice_capability(capability_id: str) -> dict[str, Any]:
    if capability_id == "runtime_startup_smoke":
        return {
            "id": capability_id,
            "label": "Runtime startup smoke",
            "expected_behavior": "The generated app must include runtime_smoke.js and it must pass without throwing before DOM events are bound.",
            "detection": {"match_any": ["runtime_smoke.js", "runtime_init_ok", "DOMContentLoaded"]},
        }
    if capability_id == "openrouter_images_endpoint":
        return {
            "id": capability_id,
            "label": "OpenRouter images endpoint",
            "expected_behavior": "Use POST https://openrouter.ai/api/v1/images with input_references; do not use chat/completions plus modalities as the image path.",
            "detection": {"match_any": ["https://openrouter.ai/api/v1/images", "input_references", "openai/gpt-image-1"]},
        }
    return {"id": capability_id, "label": capability_id, "expected_behavior": "", "detection": {"match_any": []}}


def _build_fix_slice_prompt(
    *,
    context: Any,
    bundle: CodexPromptBundle,
    worktree_dir: Path,
    previous_record: dict[str, Any],
    first_evaluation: dict[str, Any],
    fix_targets: list[dict[str, Any]],
) -> str:
    allowed_paths = bundle.allowed_paths
    verification_commands = bundle.verification_commands
    target_lines: list[str] = []
    for target in fix_targets:
        target_lines.append(f"- `{target['id']}` - {target.get('label', '')}")
        if target.get("expected_behavior"):
            target_lines.append(f"  - expected_behavior: {target['expected_behavior']}")
        if target.get("detection_hints"):
            target_lines.append(f"  - detection_hints: {', '.join(target['detection_hints'])}")
        if target.get("evidence_files"):
            target_lines.append(f"  - evidence_files: {', '.join(target['evidence_files'])}")
        if target.get("reference_files"):
            target_lines.append(f"  - reference_files: {', '.join(target['reference_files'])}")
    artifact_lines = _artifact_excerpt_lines(context)
    runtime_lines = _runtime_verification_excerpt_lines(Path(getattr(context, "run_dir", ".")))
    return "\n".join(
        [
            "# Codex Benchmark Fix Slice Prompt",
            "",
            "You are the `coding agent` running a fix-slice pass over the same worktree.",
            "Your job is to remediate the missing benchmark capabilities listed below, without breaking what already passes.",
            "",
            "## Non-Negotiable Rules",
            "- Reuse the existing worktree; do not re-scaffold the app from scratch.",
            "- Only modify files that implement the listed missing capabilities or directly related glue.",
            "- Do not break or remove previously covered capabilities, files, or routes.",
            "- Do not introduce new dependencies; stay within Node stdlib and the v1 contract.",
            "- Do not commit secrets; placeholder env example files remain placeholder.",
            "- Stop and emit a blocker if a fix would require a prohibited behavior.",
            "",
            "## Benchmark Fix Slice",
            f"- Round: 2 of {BENCHMARK_FIX_SLICE_MAX_ROUNDS + 1} (single fix-slice retry).",
            f"- Missing capability count: {len(fix_targets)}.",
            "",
            "### Missing Capabilities",
            *target_lines,
            "",
            "## Previous Attempt",
            f"- Status: {previous_record.get('status', '')}",
            f"- Summary: {previous_record.get('summary', '')}",
            f"- Files changed: {', '.join(_string_list(previous_record.get('files_changed', []))) or 'none'}",
            f"- Blocking events: {', '.join(_string_list(first_evaluation.get('blocking_events', []))) or 'none'}",
            "",
            "## Required Final Response",
            "Return JSON that matches `codex/codex_response_schema.json` exactly.",
            "",
            "### `risk_events` Field Discipline",
            "- Use `risk_events` only for problems that should block review or release of this run.",
            "- Do NOT put capability-gap self-disclosure (e.g. `no external image model`, `placeholder previews only`, `no database; localStorage only`)",
            "  or sandbox/runtime environment limits (e.g. `listen EPERM`, `sandboxCwd must be an absolute file URI`, manual browser preview blocked by sandbox) into `risk_events`.",
            "  Describe them in `summary` or `next_action` instead.",
            "- Decision rule: if it would not prevent the next reviewer from approving the diff, keep it out of `risk_events`.",
            "",
            "## Upstream Artifacts",
            *artifact_lines,
            "",
            "## App Runtime Verification",
            *runtime_lines,
            "",
            "## Allowed Files",
            *[f"- {path}" for path in allowed_paths],
            "",
            "## Verification Commands",
            *[f"- `{command}`" for command in verification_commands],
            f"- Worktree: `{worktree_dir}`",
        ]
    ).rstrip() + "\n"


def _runtime_verification_excerpt_lines(run_dir: Path) -> list[str]:
    path = run_dir / APP_RUNTIME_VERIFICATION_PATH
    if not path.exists():
        return ["- No app runtime verification artifact recorded."]
    try:
        payload = read_json(path)
    except Exception as exc:  # noqa: BLE001 - keep prompt generation robust.
        return [f"- Could not read `{APP_RUNTIME_VERIFICATION_PATH}`: {type(exc).__name__}: {exc}"]
    lines = [f"- Status: `{payload.get('status', 'unknown')}`"]
    for item in payload.get("commands", []) or []:
        if not isinstance(item, dict):
            continue
        lines.append(f"- `{item.get('command', '')}` -> exit `{item.get('exit_code', '')}`")
        if item.get("stdout_path"):
            lines.append(f"  - stdout: `{item.get('stdout_path')}`")
            stdout_excerpt = _runtime_log_excerpt(run_dir, str(item.get("stdout_path", "")))
            if stdout_excerpt:
                lines.append(f"    - stdout_excerpt: {stdout_excerpt}")
        if item.get("stderr_path"):
            lines.append(f"  - stderr: `{item.get('stderr_path')}`")
            stderr_excerpt = _runtime_log_excerpt(run_dir, str(item.get("stderr_path", "")))
            if stderr_excerpt:
                lines.append(f"    - stderr_excerpt: {stderr_excerpt}")
    for event in _string_list(payload.get("blocking_events", [])):
        lines.append(f"- blocking: `{event}`")
    return lines or ["- No app runtime verification command results recorded."]


def _runtime_log_excerpt(run_dir: Path, relative_path: str, *, max_chars: int = 600) -> str:
    if not relative_path:
        return ""
    candidate = (run_dir / relative_path).resolve()
    try:
        candidate.relative_to(run_dir.resolve())
    except ValueError:
        return ""
    if not candidate.exists() or not candidate.is_file():
        return ""
    text = candidate.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return ""
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "..."
    return json.dumps(text, ensure_ascii=False)


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
    lines.extend(_slice_loop_context_lines(context))
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


def _app_repair_prompt_lines(context: Any) -> list[str]:
    inputs = getattr(context, "inputs", {}) or {}
    repair_request = inputs.get("repair_request") if isinstance(inputs.get("repair_request"), dict) else {}
    app_slug = str(inputs.get("app_slug") or repair_request.get("app_slug") or "")
    constraints = _string_list(repair_request.get("constraints") or inputs.get("constraints"))
    expected = _string_list(repair_request.get("expected_behavior") or inputs.get("expected_behavior"))
    problem = str(repair_request.get("problem") or getattr(context, "brief", "") or "")
    lines = [
        "",
        "## App Repair Contract",
        f"- Target published app slug: `{app_slug}`.",
        f"- Problem: {problem}",
        "- Repair only the current candidate copy under `generated_apps/<slug>/`.",
        "- Do not modify run artifacts, `codex/`, `.env`, `app_publish.json`, `node_modules`, or repository source files.",
        "- Preserve existing user workflow unless the repair request explicitly says otherwise.",
        "- API keys and secrets must remain server-side environment variables only.",
    ]
    if constraints:
        lines.extend(["", "### Constraints", *[f"- {item}" for item in constraints]])
    if expected:
        lines.extend(["", "### Expected Behavior", *[f"- {item}" for item in expected]])
    return lines


def _build_prompt(stage: str, context: Any, state_summary: str, allowed_paths: list[str], verification_commands: list[str]) -> str:
    if stage == "coder":
        role = "coding agent"
        action = "Implement the requested vertical slice in the isolated worktree."
    elif stage == "app_repair":
        role = "code repair agent"
        action = "Repair the current published generated app snapshot in the isolated worktree."
    else:
        role = "code reviewer"
        action = "Review the uncommitted diff in the isolated worktree."
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
            "### `risk_events` Field Discipline",
            "- Use `risk_events` only for problems that should block review or release of this run.",
            "  Examples: a failing test that was hidden by skipping, schema/contract mismatch, missing required artifact, a prohibited behavior was introduced.",
            "- Do NOT put the following into `risk_events`; describe them in `summary` or `next_action` instead:",
            "  - Capability-gap self-disclosure that the implementation already represents explicitly,",
            "    e.g. \"no external image model is called\", \"image generation is placeholder only\",",
            "    \"no database; localStorage only\", \"no proxy / captcha / fingerprint\".",
            "    These are implementation choices consistent with the PRD/contract, not blockers.",
            "  - Sandbox / runtime environment limits encountered during verification,",
            "    e.g. `listen EPERM`, `sandboxCwd must be an absolute file URI`,",
            "    \"manual browser preview not completed because sandbox forbids localhost binding\",",
            "    DNS/network not reachable, missing local binary.",
            "    These are environmental, not defects of the generated code.",
            "- Decision rule: if it would not prevent the next reviewer from approving the diff, keep it out of `risk_events`.",
            "",
            "## State Summary",
            state_summary.rstrip(),
            "",
            "## Acceptance Criteria",
            "- The requested change is represented by a git diff in the worktree.",
            "- The final response names changed files and verification commands actually run.",
            "- Risk events and blockers are explicit and not hidden in prose.",
            *(_app_repair_prompt_lines(context) if stage == "app_repair" else []),
            *_app_generation_prompt_lines(context),
            "",
            "## Codex Slice-Loop",
            *_slice_loop_prompt_lines(context),
            "",
            "## Codex / System Responsibility Boundary",
            "- AI-Team owns requirement clarification, capability boundary, TDD plan, gates, and final readiness decisions.",
            "- Codex CLI owns red-first tests, minimal implementation, verification evidence, and explicit blockers.",
            "- Do not promote LLM draft assumptions or change real-device/production gates from inside the coding pass.",
            "",
            "## Allowed Files",
            *[f"- {path}" for path in allowed_paths],
            "",
            "## Verification Commands",
            *[f"- `{command}`" for command in verification_commands],
        ]
    ).rstrip() + "\n"


def _seed_app_repair_candidate(
    *,
    published_app_dir: Path,
    worktree_dir: Path,
    codex_dir: Path,
    app_slug: str,
) -> tuple[Path, Path]:
    baseline_root = codex_dir / "app_repair_baseline"
    baseline_dir = baseline_root / app_slug
    candidate_dir = worktree_dir / "generated_apps" / app_slug
    for path in (baseline_dir, candidate_dir):
        if path.exists():
            shutil.rmtree(path)
    baseline_dir.parent.mkdir(parents=True, exist_ok=True)
    candidate_dir.parent.mkdir(parents=True, exist_ok=True)
    ignore = shutil.ignore_patterns("app_publish.json", "app_patches", "node_modules", ".env", ".env.*")
    shutil.copytree(published_app_dir, baseline_dir, ignore=ignore)
    shutil.copytree(baseline_dir, candidate_dir)
    return candidate_dir, baseline_dir


def _write_directory_diff(baseline_dir: Path, candidate_dir: Path, diff_path: Path, *, app_slug: str) -> list[str]:
    changed: list[str] = []
    diff_parts: list[str] = []
    rel_paths = sorted(
        {
            path.relative_to(root).as_posix()
            for root in (baseline_dir, candidate_dir)
            if root.exists()
            for path in root.rglob("*")
            if path.is_file()
        }
    )
    for rel_path in rel_paths:
        before_path = baseline_dir / rel_path
        after_path = candidate_dir / rel_path
        before = before_path.read_text(encoding="utf-8", errors="replace") if before_path.exists() else ""
        after = after_path.read_text(encoding="utf-8", errors="replace") if after_path.exists() else ""
        if before == after:
            continue
        run_rel = f"generated_apps/{app_slug}/{rel_path}"
        changed.append(run_rel)
        diff_parts.extend(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{run_rel}",
                tofile=f"b/{run_rel}",
            )
        )
        if diff_parts and not str(diff_parts[-1]).endswith("\n"):
            diff_parts.append("\n")
    diff_path.write_text("".join(diff_parts), encoding="utf-8")
    return changed


def _run_app_repair_verification(
    *,
    commands: list[str],
    app_dir: Path,
    codex_dir: Path,
    run_dir: Path,
    env: dict[str, str] | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    safe_commands = _app_repair_safe_commands(commands)
    if not safe_commands:
        safe_commands = ["node --check server.js"]
        if (app_dir / "public" / "app.js").exists():
            safe_commands.append("node --check public/app.js")
        if (app_dir / "runtime_smoke.js").exists():
            safe_commands.append("node runtime_smoke.js")
    results: list[dict[str, Any]] = []
    risk_events: list[str] = []
    for index, command in enumerate(safe_commands, start=1):
        stdout_path = codex_dir / f"app_repair_verify_{index}_stdout.log"
        stderr_path = codex_dir / f"app_repair_verify_{index}_stderr.log"
        started_at = now_iso()
        try:
            completed = subprocess.run(
                shlex.split(command),
                cwd=app_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_seconds,
                check=False,
                env=env,
            )
            stdout = completed.stdout
            stderr = completed.stderr
            exit_code = completed.returncode
        except Exception as exc:  # noqa: BLE001 - persisted as verification evidence.
            stdout = ""
            stderr = f"{type(exc).__name__}: {exc}"
            exit_code = 1
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        if exit_code != 0:
            risk_events.append(f"app_repair_verification_failed:{command}:{exit_code}")
        results.append(
            {
                "command": command,
                "exit_code": exit_code,
                "started_at": started_at,
                "finished_at": now_iso(),
                "stdout_path": _relative_to(stdout_path, run_dir),
                "stderr_path": _relative_to(stderr_path, run_dir),
            }
        )
    record = {
        "schema_version": 1,
        "status": "passed" if not risk_events else "failed",
        "commands": results,
        "risk_events": risk_events,
        "app_dir": _relative_to(app_dir, run_dir),
    }
    write_json(codex_dir / "app_repair_verification.json", record)
    return record


def _app_repair_safe_commands(commands: list[str]) -> list[str]:
    safe: list[str] = []
    for command in commands:
        command_text = str(command).strip()
        try:
            parts = shlex.split(command_text)
        except ValueError:
            continue
        if len(parts) == 3 and parts[0] == "node" and parts[1] == "--check" and parts[2] in {"server.js", "public/app.js", "runtime_smoke.js"}:
            safe.append(command_text)
            continue
        if len(parts) == 2 and parts[0] == "node" and parts[1] == "runtime_smoke.js":
            safe.append(command_text)
    return _dedupe(safe)


def _app_generation_prompt_lines(context: Any) -> list[str]:
    domain = getattr(context, "domain", None)
    if getattr(domain, "domain_id", "") != "app_generation":
        return []
    run_dir = Path(getattr(context, "run_dir", "."))
    lines = [
        "",
        "## App Generation Runtime Contract",
        "- Generate `runtime_smoke.js` in the app root.",
        "- `node --check` is not sufficient: `runtime_smoke.js` must prove the browser entry script initializes without throwing before DOM events are bound.",
        "- The generated SPA must render first-screen controls with options and bind primary button click handlers; silent no-op buttons are blockers.",
    ]
    benchmark_path = run_dir / "benchmark_context.json"
    if benchmark_path.exists():
        try:
            benchmark = read_json(benchmark_path)
        except Exception:  # noqa: BLE001 - prompt enhancement should not break non-benchmark runs.
            benchmark = {}
        instructions = _string_list(benchmark.get("instructions", []))
        if instructions:
            lines.extend(["", "## Benchmark-Specific Generation Requirements"])
            lines.extend(f"- {item}" for item in instructions)
    
    # 图片生成类应用结构契约（见 docs/app_generation_prd_to_local_app_spec.md § 图片生成类 PRD 要求）
    lines.extend([
        "",
        "## Image Generation App Structure Contract",
        "When PRD explicitly requires image generation, main image generation, reference image output, or OpenAI/OpenRouter image capability:",
        "- Frontend: model selector, provider config status badge (shows 'configured' / 'not configured', NOT the key itself), single/batch generate buttons, result area, error area.",
        "- Backend: `GET /api/health` returns `{provider, configured, model, message}`; `POST /api/images/generate` reads API key from `process.env` only.",
        "- Config: `.env.example` with placeholder keys and default model; `README.md` explains server-side `.env` setup.",
        "- Anchors: Preserve `// === AGENT_EDIT:<id> START ===` and `// === AGENT_EDIT:<id> END ===` comment blocks for future `patch_app` replace_block operations.",
        "- Forbidden: frontend API_KEY input field, `localStorage` key persistence, `config.json` key persistence.",
        "",
    ])
    
    return lines


def _slice_loop_context_lines(context: Any) -> list[str]:
    run_dir = Path(getattr(context, "run_dir", "."))
    slices = _read_slice_definitions(run_dir)
    if not slices:
        return []
    coverage = _read_acceptance_coverage_matrix(run_dir)
    first_slice = slices[0]
    lines = [
        "",
        "## Codex Slice-Loop",
        f"- Execution strategy: `{SLICE_LOOP_EXECUTION_STRATEGY}`",
        f"- Current slice: `{first_slice.get('id', '')}` {first_slice.get('title', '')}",
        f"- Completed slices: none",
        f"- Pending slices: {', '.join(str(item.get('id', '')) for item in slices)}",
        "- Continuity source: run artifacts, slice yaml, coverage matrix, traces, and current diff.",
        "",
        "### Current Slice",
        f"- Acceptance criteria ids: {', '.join(_string_list(first_slice.get('acceptance_criteria_ids', []))) or 'none'}",
        f"- Allowed paths: {', '.join(_string_list(first_slice.get('allowed_paths', []))) or 'none'}",
        f"- Verification commands: {'; '.join(_string_list(first_slice.get('verification_commands', []))) or 'none'}",
    ]
    if coverage:
        lines.extend(
            [
                "",
                "### Acceptance Coverage Matrix",
                f"- Acceptance criteria count: {len(coverage.get('acceptance_criteria', []))}",
                f"- Slice count: {len(coverage.get('slices', []))}",
                "- Coverage matrix artifact: `planning/acceptance_coverage_matrix.json`",
            ]
        )
    return lines


def _slice_loop_prompt_lines(context: Any) -> list[str]:
    run_dir = Path(getattr(context, "run_dir", "."))
    slices = _read_slice_definitions(run_dir)
    if not slices:
        return ["- No planned slices were found; use the single-prompt Codex flow."]
    first_slice = slices[0]
    return [
        "- Use coverage-driven slice-loop discipline even when v1 executes through one Codex process.",
        "- Treat `planning/acceptance_coverage_matrix.json` and `slices/*.yaml` as the continuity source.",
        f"- Current slice: `{first_slice.get('id', '')}`.",
        "- Keep the final JSON focused on changed files, tests, risk events, blockers, and next action.",
        "- Do not start unrelated refactors outside the declared allowed paths.",
    ]


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


def _new_slice_loop_state(context: Any, bundle: CodexPromptBundle) -> dict[str, Any]:
    now = now_iso()
    run_dir = Path(getattr(context, "run_dir", "."))
    slices = _read_slice_definitions(run_dir)
    coverage = _read_acceptance_coverage_matrix(run_dir)
    return {
        "schema_version": 1,
        "run_id": getattr(context, "run_id", ""),
        "stage": "coder",
        "enabled": bool(slices),
        "status": "not_started" if slices else "skipped",
        "execution_strategy": SLICE_LOOP_EXECUTION_STRATEGY if slices else "single_prompt_no_slices",
        "current_slice_id": str(slices[0].get("id", "")) if slices else "",
        "updated_at": now,
        "overall_goal": getattr(context, "brief", ""),
        "coverage_matrix_path": "planning/acceptance_coverage_matrix.json" if coverage else "",
        "slices": [
            {
                "id": str(item.get("id", "")),
                "title": str(item.get("title", "")),
                "status": "pending",
                "acceptance_criteria_ids": _string_list(item.get("acceptance_criteria_ids", [])),
                "depends_on": _string_list(item.get("depends_on", [])),
                "allowed_paths": _string_list(item.get("allowed_paths", [])),
                "verification_commands": _string_list(item.get("verification_commands", [])),
                "trace_path": f"codex/slices/{item.get('id', '')}/slice_trace.json",
            }
            for item in slices
        ],
        "completed_slice_ids": [],
        "pending_slice_ids": [str(item.get("id", "")) for item in slices],
        "blockers": [],
        "risk_events": [],
        "next_action": "",
    }


def _write_initial_slice_loop_artifacts(run_dir: Path, codex_dir: Path, slice_loop: dict[str, Any]) -> list[str]:
    if not slice_loop.get("enabled"):
        return []
    output_paths = [SLICE_LOOP_STATE_PATH]
    for item in slice_loop.get("slices", []):
        slice_id = str(item.get("id", "")).strip()
        if not slice_id:
            continue
        trace_path = codex_dir / "slices" / slice_id / "slice_trace.json"
        trace = _slice_trace_payload(
            run_id=str(slice_loop.get("run_id", "")),
            slice_item=item,
            status="pending",
            summary="Slice is planned and waiting for Codex execution.",
        )
        ensure_dir(trace_path.parent)
        write_json(trace_path, trace)
        output_paths.append(_relative_to(trace_path, run_dir))
    write_json(codex_dir / "slice_loop_state.json", slice_loop)
    return output_paths


def _finalize_slice_loop_failure(run_dir: Path, codex_dir: Path, slice_loop: dict[str, Any], reason: str) -> None:
    if not slice_loop.get("enabled"):
        return
    slice_loop["status"] = "failed"
    slice_loop["updated_at"] = now_iso()
    slice_loop["blockers"] = _dedupe(_string_list(slice_loop.get("blockers", [])) + [reason])
    slice_loop["risk_events"] = _dedupe(_string_list(slice_loop.get("risk_events", [])) + [reason])
    slice_loop["next_action"] = "Resolve the blocker, then rerun the current slice."
    for item in slice_loop.get("slices", []):
        if item.get("id") == slice_loop.get("current_slice_id"):
            item["status"] = "failed"
            trace_path = codex_dir / "slices" / str(item.get("id", "")) / "slice_trace.json"
            trace = _slice_trace_payload(
                run_id=str(slice_loop.get("run_id", "")),
                slice_item=item,
                status="failed",
                summary="Slice could not start because Codex setup failed.",
                blockers=[reason],
                risk_events=[reason],
            )
            write_json(trace_path, trace)
            break
    write_json(codex_dir / "slice_loop_state.json", slice_loop)
    _write_completion_gate(
        run_dir,
        slice_loop,
        status="failed",
        files_changed=[],
        tests_run=[],
        verification_commands=[],
        risk_events=[reason],
        blockers=[reason],
        allowed_paths=[],
    )


def _finalize_slice_loop_success(
    run_dir: Path,
    codex_dir: Path,
    slice_loop: dict[str, Any],
    *,
    status: str,
    files_changed: list[str],
    tests_run: list[str],
    verification_commands: list[str],
    risk_events: list[str],
    blockers: list[str],
    diff_path: str,
    completion_gate: dict[str, Any],
) -> None:
    if not slice_loop.get("enabled"):
        return
    completed_ids: list[str] = []
    for item in slice_loop.get("slices", []):
        slice_id = str(item.get("id", ""))
        item["status"] = "completed" if status == "completed" else "failed"
        if status == "completed":
            completed_ids.append(slice_id)
        trace_path = codex_dir / "slices" / slice_id / "slice_trace.json"
        trace = _slice_trace_payload(
            run_id=str(slice_loop.get("run_id", "")),
            slice_item=item,
            status=item["status"],
            summary="Slice evidence was collected from the Codex implementation pass.",
            changed_files=files_changed,
            tests_run=tests_run,
            verification_commands=verification_commands,
            risk_events=risk_events,
            blockers=blockers,
            diff_path=diff_path,
        )
        write_json(trace_path, trace)
    slice_loop["status"] = "completed" if status == "completed" and completion_gate.get("status") == "passed" else "failed"
    slice_loop["current_slice_id"] = ""
    slice_loop["completed_slice_ids"] = completed_ids
    slice_loop["pending_slice_ids"] = [] if status == "completed" else [str(item.get("id", "")) for item in slice_loop.get("slices", [])]
    slice_loop["risk_events"] = risk_events
    slice_loop["blockers"] = blockers
    slice_loop["next_action"] = "Ready for review." if slice_loop["status"] == "completed" else "Resolve slice-loop blockers before review."
    slice_loop["updated_at"] = now_iso()
    write_json(codex_dir / "slice_loop_state.json", slice_loop)


def _slice_trace_payload(
    *,
    run_id: str,
    slice_item: dict[str, Any],
    status: str,
    summary: str,
    changed_files: list[str] | None = None,
    tests_run: list[str] | None = None,
    verification_commands: list[str] | None = None,
    risk_events: list[str] | None = None,
    blockers: list[str] | None = None,
    diff_path: str = "",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "slice_id": str(slice_item.get("id", "")),
        "title": str(slice_item.get("title", "")),
        "status": status,
        "execution_strategy": SLICE_LOOP_EXECUTION_STRATEGY,
        "updated_at": now_iso(),
        "goal": str(slice_item.get("coverage_goal", slice_item.get("title", ""))),
        "acceptance_criteria_ids": _string_list(slice_item.get("acceptance_criteria_ids", [])),
        "depends_on": _string_list(slice_item.get("depends_on", [])),
        "allowed_paths": _string_list(slice_item.get("allowed_paths", [])),
        "expected_artifacts": _string_list(slice_item.get("expected_artifacts", [])),
        "stop_conditions": _string_list(slice_item.get("stop_conditions", [])),
        "summary": summary,
        "evidence": {
            "changed_files": changed_files or [],
            "tests_run": tests_run or [],
            "verification_commands": verification_commands or _string_list(slice_item.get("verification_commands", [])),
            "diff_path": diff_path,
        },
        "risk_events": risk_events or [],
        "blockers": blockers or [],
        "acceptance_criteria_satisfied": status == "completed" and not blockers and not risk_events,
    }


def _write_completion_gate(
    run_dir: Path,
    slice_loop: dict[str, Any],
    *,
    status: str,
    files_changed: list[str],
    tests_run: list[str],
    verification_commands: list[str],
    risk_events: list[str],
    blockers: list[str],
    allowed_paths: list[str],
) -> dict[str, Any]:
    slices = [item for item in slice_loop.get("slices", []) if isinstance(item, dict)]
    all_slice_ids = [str(item.get("id", "")) for item in slices]
    completed_slice_ids = all_slice_ids if status == "completed" and not blockers and not risk_events else _string_list(slice_loop.get("completed_slice_ids", []))
    covered_ac_ids = {ac_id for item in slices for ac_id in _string_list(item.get("acceptance_criteria_ids", []))}
    coverage = _read_acceptance_coverage_matrix(run_dir)
    required_ac_ids = {str(item.get("id", "")) for item in coverage.get("acceptance_criteria", []) if str(item.get("id", "")).strip()}
    if not required_ac_ids:
        required_ac_ids = set(covered_ac_ids)
    unrelated = _unrelated_changed_files(files_changed, allowed_paths)
    checks = [
        _completion_check("all_slices_completed", set(completed_slice_ids) == set(all_slice_ids), all_slice_ids),
        _completion_check("all_acceptance_criteria_covered", required_ac_ids.issubset(covered_ac_ids), sorted(required_ac_ids)),
        _completion_check("required_tests_passed", bool(tests_run) or bool(verification_commands), tests_run or verification_commands),
        _completion_check("no_open_blockers", not blockers and not risk_events, blockers + risk_events),
        _completion_check("no_unrelated_changes", not unrelated, unrelated),
        {
            "id": "final_report_mentions_coverage",
            "status": "warning",
            "reason": "Final report is generated after coding; publisher should mention acceptance coverage.",
            "evidence": ["final_report.md"],
        },
    ]
    hard_failed = any(item["status"] == "failed" for item in checks)
    gate = {
        "schema_version": 1,
        "run_id": str(slice_loop.get("run_id", "")),
        "generated_at": now_iso(),
        "status": "failed" if hard_failed else "passed",
        "summary": "Implementation is ready for review." if not hard_failed else "Implementation is not ready for review.",
        "checks": checks,
        "evidence": {
            "changed_files": files_changed,
            "tests_run": tests_run,
            "verification_commands": verification_commands,
            "completed_slice_ids": completed_slice_ids,
            "required_acceptance_criteria_ids": sorted(required_ac_ids),
            "covered_acceptance_criteria_ids": sorted(covered_ac_ids),
        },
        "blockers": blockers + risk_events + unrelated,
        "next_action": "Proceed to review and verifier." if not hard_failed else "Resolve blockers, rerun tests, and regenerate completion gate.",
    }
    write_json(run_dir / IMPLEMENTATION_COMPLETION_GATE_JSON_PATH, gate)
    (run_dir / IMPLEMENTATION_COMPLETION_GATE_MD_PATH).write_text(_completion_gate_markdown(gate), encoding="utf-8")
    return gate


def _completion_check(check_id: str, passed: bool, evidence: list[str]) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "passed" if passed else "failed",
        "reason": "Check passed." if passed else "Check failed.",
        "evidence": evidence,
    }


def _completion_gate_markdown(gate: dict[str, Any]) -> str:
    lines = [
        "# Implementation Completion Gate",
        "",
        f"- Status: `{gate.get('status', '')}`",
        f"- Summary: {gate.get('summary', '')}",
        "",
        "## Checks",
    ]
    for item in gate.get("checks", []):
        lines.append(f"- `{item.get('id', '')}`: {item.get('status', '')} - {item.get('reason', '')}")
    evidence = gate.get("evidence", {})
    lines.extend(
        [
            "",
            "## Evidence",
            f"- Completed slices: {', '.join(_string_list(evidence.get('completed_slice_ids', []))) or 'none'}",
            f"- Covered AC: {', '.join(_string_list(evidence.get('covered_acceptance_criteria_ids', []))) or 'none'}",
            f"- Changed files: {', '.join(_string_list(evidence.get('changed_files', []))) or 'none'}",
            f"- Tests: {', '.join(_string_list(evidence.get('tests_run', []))) or 'none'}",
            "",
            "## Next Action",
            str(gate.get("next_action", "")),
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _attach_slice_loop_artifacts(record: dict[str, Any], output_paths: list[str]) -> None:
    artifacts = record.setdefault("artifacts", {})
    if SLICE_LOOP_STATE_PATH in output_paths:
        artifacts["slice_loop_state"] = SLICE_LOOP_STATE_PATH
    if IMPLEMENTATION_COMPLETION_GATE_JSON_PATH in output_paths:
        artifacts["implementation_completion_gate"] = IMPLEMENTATION_COMPLETION_GATE_JSON_PATH
    slice_traces = [path for path in output_paths if path.startswith("codex/slices/") and path.endswith("/slice_trace.json")]
    if slice_traces:
        artifacts["slice_traces"] = slice_traces


def _read_slice_definitions(run_dir: Path) -> list[dict[str, Any]]:
    slices_dir = run_dir / "slices"
    if not slices_dir.exists():
        return []
    definitions: list[dict[str, Any]] = []
    for path in sorted(slices_dir.glob("*.yaml")):
        try:
            payload = load_yaml_subset(path)
        except Exception:  # noqa: BLE001 - bad slices are handled by planning quality artifacts.
            continue
        if not isinstance(payload, dict):
            continue
        slice_id = str(payload.get("slice_id") or payload.get("id") or path.stem)
        definitions.append(
            {
                "id": slice_id,
                "title": str(payload.get("title", slice_id)),
                "type": str(payload.get("type", "coding")),
                "depends_on": _string_list(payload.get("depends_on", [])),
                "acceptance_criteria_ids": _string_list(payload.get("acceptance_criteria_ids", [])),
                "coverage_goal": str(payload.get("coverage_goal", "")),
                "allowed_paths": _string_list(payload.get("allowed_paths", [])),
                "expected_artifacts": _string_list(payload.get("expected_artifacts", [])),
                "verification_commands": _string_list(payload.get("verification_commands", [])),
                "stop_conditions": _string_list(payload.get("stop_conditions", [])),
            }
        )
    return definitions


def _read_acceptance_coverage_matrix(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "planning" / "acceptance_coverage_matrix.json"
    if not path.exists():
        return {}
    try:
        payload = read_json(path)
    except Exception:  # noqa: BLE001 - optional observability artifact.
        return {}
    return payload if isinstance(payload, dict) else {}


def _unrelated_changed_files(files_changed: list[str], allowed_paths: list[str]) -> list[str]:
    if not allowed_paths:
        return []
    unrelated: list[str] = []
    for file_name in files_changed:
        normalized = file_name.strip()
        if not normalized:
            continue
        if not any(normalized == allowed.rstrip("/") or normalized.startswith(allowed.rstrip("/") + "/") for allowed in allowed_paths):
            unrelated.append(normalized)
    return unrelated


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
    matched: set[str] = set()
    for line in _added_diff_lines(text):
        lowered = line.lower()
        if _is_safe_risk_context(lowered):
            continue
        for pattern in IMPLEMENTATION_RISK_PATTERNS:
            if pattern in lowered:
                matched.add(pattern)
    return [
        f"prohibited_implementation_pattern:{pattern}"
        for pattern in IMPLEMENTATION_RISK_PATTERNS
        if pattern in matched
    ]


def _added_diff_lines(text: str) -> list[str]:
    lines: list[str] = []
    for line in text.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        lines.append(line[1:])
    return lines


def _is_safe_risk_context(lowered_line: str) -> bool:
    return any(marker in lowered_line for marker in SAFE_RISK_CONTEXT_MARKERS)


def _build_failure_classification(
    *,
    run_id: str,
    exit_code: int,
    validation_events: list[str],
    changed_files: list[str],
    tests_run: list[str],
    codex_blockers: list[str],
    codex_risk_events: list[str],
    codex_blocking_risk_events: list[str],
    codex_non_blocking_risk_events: list[str],
    diff_policy_hits: list[str],
    allowed_paths: list[str],
    boundary_violations: list[str],
    no_changed_files: bool,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for event in validation_events:
        events.append(_classification_event(event, "blocking", "schema", event, [event]))
    if exit_code != 0:
        event_id = f"codex_exit_code:{exit_code}"
        events.append(_classification_event(event_id, "blocking", "executor", f"Codex exited with {exit_code}.", [event_id]))
    for blocker in codex_blockers:
        events.append(_classification_event("codex_blocker_reported", "blocking", "codex_response", blocker, [blocker]))
    for event in codex_blocking_risk_events:
        events.append(_classification_event(event, "blocking", "codex_response", event, [event]))
    for event in diff_policy_hits:
        events.append(_classification_event(event, "blocking", "diff_scan", event, [event]))
    for file_name in boundary_violations:
        event_id = f"changed_file_outside_allowed_paths:{file_name}"
        events.append(_classification_event(event_id, "blocking", "file_boundary", f"Changed file is outside allowed paths: {file_name}", [file_name]))
    if no_changed_files:
        events.append(_classification_event("no_changed_files", "blocking", "file_boundary", "No code changes were detected.", []))
    for event in codex_non_blocking_risk_events:
        events.append(_classification_event(_non_blocking_risk_event_id(event), "warning", "codex_response", event, [event]))

    blocking_events = _dedupe(str(event["id"]) for event in events if event.get("severity") == "blocking")
    warnings = _dedupe(str(event["reason"]) for event in events if event.get("severity") == "warning")
    if blocking_events:
        decision = "failed"
        summary = f"AI implementation is blocked by {len(blocking_events)} deterministic event(s)."
        primary_reason = blocking_events[0]
    elif warnings:
        decision = "passed_with_warnings"
        summary = f"AI implementation completed with {len(warnings)} non-blocking warning(s)."
        primary_reason = warnings[0]
    else:
        decision = "passed"
        summary = "AI implementation completed without blocking failure evidence."
        primary_reason = "No blocking failure evidence."

    return {
        "schema_version": 1,
        "run_id": run_id,
        "stage": "coder",
        "generated_at": now_iso(),
        "classification_decision": decision,
        "summary": summary,
        "primary_reason": primary_reason,
        "events": events,
        "evidence": {
            "exit_code": exit_code,
            "schema_valid": not validation_events,
            "changed_files": changed_files,
            "tests_run": tests_run,
            "codex_blockers": codex_blockers,
            "codex_risk_events": codex_risk_events,
            "diff_policy_hits": diff_policy_hits,
            "working_tree": {
                "allowed_paths": allowed_paths,
                "boundary_violations": boundary_violations,
                "no_changed_files": no_changed_files,
            },
        },
        "blocking_events": blocking_events,
        "warnings": warnings,
        "next_actions": _failure_classification_next_actions(decision, blocking_events),
    }


def _build_preflight_failure_classification(run_id: str, reason: str) -> dict[str, Any]:
    event = _classification_event(reason, "blocking", "executor", reason, [reason])
    return {
        "schema_version": 1,
        "run_id": run_id,
        "stage": "coder",
        "generated_at": now_iso(),
        "classification_decision": "failed",
        "summary": "AI implementation could not start because a preflight check failed.",
        "primary_reason": reason,
        "events": [event],
        "evidence": {
            "exit_code": 1,
            "schema_valid": False,
            "changed_files": [],
            "tests_run": [],
            "codex_blockers": [reason],
            "codex_risk_events": [],
            "diff_policy_hits": [],
            "working_tree": {
                "allowed_paths": [],
                "boundary_violations": [],
                "no_changed_files": True,
            },
        },
        "blocking_events": [reason],
        "warnings": [],
        "next_actions": [f"Resolve blocking event `{reason}` before review/test."],
    }


def _classification_event(event_id: str, severity: str, source: str, reason: str, evidence: list[str]) -> dict[str, Any]:
    return {
        "id": event_id,
        "severity": severity,
        "source": source,
        "reason": reason,
        "evidence": _string_list(evidence),
    }


def _non_blocking_risk_event_id(event: str) -> str:
    lowered = event.lower()
    if "modified tests/" in lowered and "supporting test boundary" in lowered:
        return "supporting_test_boundary_note"
    if "nearby supporting" in lowered or "nearby_supporting" in lowered:
        return "supporting_location_note"
    if lowered.startswith("no ") and all(marker in lowered for marker in ("scraping", "captcha", "proxy")):
        return "safety_boundary_note"
    if lowered.startswith("note:"):
        return "codex_note"
    return "codex_non_blocking_risk_note"


def _failure_classification_next_actions(decision: str, blocking_events: list[str]) -> list[str]:
    if decision == "failed":
        return [f"Resolve blocking event `{event}` before review/test." for event in blocking_events]
    if decision == "passed_with_warnings":
        return ["Review non-blocking warnings, then proceed to review/test."]
    return ["Proceed to review/test."]


def _failure_classification_markdown(classification: dict[str, Any]) -> str:
    lines = [
        "# Failure Classification",
        "",
        f"- Run: `{classification.get('run_id', '')}`",
        f"- Stage: `{classification.get('stage', '')}`",
        f"- Decision: `{classification.get('classification_decision', '')}`",
        f"- Summary: {classification.get('summary', '')}",
        f"- Primary reason: {classification.get('primary_reason', '')}",
        "",
        "## Blocking Events",
    ]
    blocking = _string_list(classification.get("blocking_events", []))
    lines.extend([f"- `{event}`" for event in blocking] or ["- None"])
    warnings = _string_list(classification.get("warnings", []))
    lines.extend(["", "## Warnings"])
    lines.extend([f"- {warning}" for warning in warnings] or ["- None"])
    evidence = classification.get("evidence", {}) if isinstance(classification.get("evidence"), dict) else {}
    working_tree = evidence.get("working_tree", {}) if isinstance(evidence.get("working_tree"), dict) else {}
    lines.extend(
        [
            "",
            "## Evidence",
            f"- Exit code: `{evidence.get('exit_code', '')}`",
            f"- Schema valid: `{str(evidence.get('schema_valid', ''))}`",
            f"- Changed files: {', '.join(_string_list(evidence.get('changed_files', []))) or 'none'}",
            f"- Tests run: {', '.join(_string_list(evidence.get('tests_run', []))) or 'none'}",
            f"- Boundary violations: {', '.join(_string_list(working_tree.get('boundary_violations', []))) or 'none'}",
            "",
            "## Next Actions",
        ]
    )
    lines.extend([f"- {action}" for action in _string_list(classification.get("next_actions", []))] or ["- None"])
    return "\n".join(lines).rstrip() + "\n"


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
    if lowered.startswith(("no ", "no_", "no-")) and all(
        marker in lowered for marker in ("scraping", "captcha", "proxy")
    ):
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
