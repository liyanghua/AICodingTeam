from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from ..fixtures import build_candidate_cards, sort_cards_by_comments
from ..models import AdapterResult, RunMetrics, TaskSpec, XhsNote
from ..utils import ensure_dir, now_millis, read_json, write_json


@dataclass(slots=True)
class AdapterContext:
    task: TaskSpec
    base_url: str
    profile_dir: Path
    run_dir: Path
    framework: str
    dry_run: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class BrowserAdapter(Protocol):
    framework: str

    def run(self, context: AdapterContext) -> AdapterResult: ...


AdapterFactory = Callable[[], BrowserAdapter]


@dataclass(slots=True)
class CommandRunnerAdapter:
    framework: str
    command: list[str]
    runner_kind: str = "python"
    notes: str = ""
    timeout_seconds: int = 3600

    def run(self, context: AdapterContext) -> AdapterResult:
        ensure_dir(context.run_dir)
        input_path = context.run_dir / "input.json"
        output_path = context.run_dir / "output.json"
        stdout_path = context.run_dir / "stdout.log"
        stderr_path = context.run_dir / "stderr.log"

        payload = {
            "framework": self.framework,
            "task": context.task.to_dict(),
            "runtime": {
                "base_url": context.base_url,
                "profile_dir": str(context.profile_dir),
                "run_dir": str(context.run_dir),
                "dry_run": context.dry_run,
                "extra": context.extra,
            },
        }
        write_json(input_path, payload)

        if context.dry_run or not self.command:
            return self._unavailable_result(
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                output_path=output_path,
                reason="adapter is in dry-run mode or no command is configured",
            )

        executable = self.command[0]
        if shutil.which(executable) is None and not Path(executable).exists():
            return self._unavailable_result(
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                output_path=output_path,
                reason=f"command not found: {executable}",
            )

        cmd = [*self.command, "--input", str(input_path), "--output", str(output_path)]
        with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open("w", encoding="utf-8") as stderr_file:
            try:
                completed = subprocess.run(
                    cmd,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except Exception as exc:  # pragma: no cover - subprocess error path
                return AdapterResult(
                    framework=self.framework,
                    status="failed",
                    notes=[],
                    risk_events=[f"runner-error:{type(exc).__name__}"],
                    metrics=RunMetrics(elapsed_ms=0, crash_count=1),
                    stdout_path=str(stdout_path),
                    stderr_path=str(stderr_path),
                    exit_code=1,
                    runner=" ".join(self.command),
                )

        if output_path.exists():
            try:
                payload = read_json(output_path)
                result = AdapterResult.from_dict(payload)
                result.framework = self.framework
                result.stdout_path = str(stdout_path)
                result.stderr_path = str(stderr_path)
                result.exit_code = completed.returncode
                result.runner = " ".join(self.command)
                return result
            except Exception as exc:  # pragma: no cover - malformed output path
                return AdapterResult(
                    framework=self.framework,
                    status="failed",
                    notes=[],
                    risk_events=[f"output-parse-error:{type(exc).__name__}"],
                    metrics=RunMetrics(elapsed_ms=0, crash_count=1),
                    stdout_path=str(stdout_path),
                    stderr_path=str(stderr_path),
                    exit_code=completed.returncode,
                    runner=" ".join(self.command),
                )

        return AdapterResult(
            framework=self.framework,
            status="unavailable",
            notes=[],
            risk_events=[f"runner-returned-no-output:{completed.returncode}"],
            metrics=RunMetrics(elapsed_ms=0, crash_count=1 if completed.returncode else 0),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            exit_code=completed.returncode,
            runner=" ".join(self.command),
        )

    def _unavailable_result(
        self,
        stdout_path: Path,
        stderr_path: Path,
        output_path: Path,
        reason: str,
    ) -> AdapterResult:
        write_json(output_path, {"framework": self.framework, "status": "unavailable", "risk_events": [reason], "notes": []})
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text(reason, encoding="utf-8")
        return AdapterResult(
            framework=self.framework,
            status="unavailable",
            notes=[],
            risk_events=[reason],
            metrics=RunMetrics(elapsed_ms=0, crash_count=0),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            exit_code=127,
            runner=" ".join(self.command),
        )


@dataclass(slots=True)
class MockAdapter:
    framework: str = "mock"

    def run(self, context: AdapterContext) -> AdapterResult:
        cards = sort_cards_by_comments(build_candidate_cards(context.task.keyword, candidate_pool=context.task.candidate_pool, base_url=context.base_url))
        expected = [card.note for card in cards[: context.task.top_n]]
        notes: list[XhsNote] = []
        for note in expected:
            payload = note.to_dict()
            payload.setdefault("extraction_meta", {})
            payload["extraction_meta"].update(
                {
                    "framework": self.framework,
                    "complete": True,
                    "risk_events": [],
                    "source": "mock-site",
                }
            )
            notes.append(XhsNote.from_dict(payload))
        elapsed_ms = 25 + len(notes) * 8
        return AdapterResult(
            framework=self.framework,
            status="success",
            notes=notes,
            risk_events=[],
            metrics=RunMetrics(elapsed_ms=elapsed_ms, retry_count=0, crash_count=0, manual_interventions=0, token_cost=0.0),
            exit_code=0,
            runner="builtin:mock",
        )

