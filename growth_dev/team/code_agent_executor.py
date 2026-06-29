from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .codex import CodexExecutor, CodexExecutorConfig


@dataclass(slots=True)
class RepairResult:
    status: str
    app_slug: str
    candidate_dir: str = ""
    diff_path: str = ""
    changed_files: list[str] = field(default_factory=list)
    verification_results: list[dict[str, Any]] = field(default_factory=list)
    risk_events: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    codex_artifacts: dict[str, str] = field(default_factory=dict)
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "app_slug": self.app_slug,
            "candidate_dir": self.candidate_dir,
            "diff_path": self.diff_path,
            "changed_files": self.changed_files,
            "verification_results": self.verification_results,
            "risk_events": self.risk_events,
            "blockers": self.blockers,
            "codex_artifacts": self.codex_artifacts,
            "message": self.message,
        }


class CodeAgentExecutor:
    provider_id = "base"

    def run_repair(
        self,
        repair_request: dict[str, Any],
        *,
        run_dir: Path,
        repo_root: Path,
        config: CodexExecutorConfig,
    ) -> RepairResult:
        raise NotImplementedError


class CodexCodeAgentProvider(CodeAgentExecutor):
    provider_id = "codex"

    def run_repair(
        self,
        repair_request: dict[str, Any],
        *,
        run_dir: Path,
        repo_root: Path,
        config: CodexExecutorConfig,
    ) -> RepairResult:
        app_slug = str(repair_request.get("app_slug") or "").strip()
        context = _repair_context(repair_request, run_dir=run_dir, repo_root=repo_root)
        executor = CodexExecutor(config, repo_root=repo_root, run_dir=run_dir)
        result = executor.run_app_repair(context)
        metadata = result.metadata if isinstance(result.metadata, dict) else {}
        return RepairResult(
            status=str(metadata.get("status") or result.status),
            app_slug=app_slug,
            candidate_dir=str(metadata.get("candidate_dir") or ""),
            diff_path=str(metadata.get("diff_path") or ""),
            changed_files=[str(item) for item in metadata.get("changed_files", []) if item],
            verification_results=list(metadata.get("verification_results", []))
            if isinstance(metadata.get("verification_results"), list)
            else [],
            risk_events=[str(item) for item in result.risk_events if item],
            blockers=[str(item) for item in metadata.get("blockers", []) if item],
            codex_artifacts=dict(metadata.get("codex_artifacts", {}))
            if isinstance(metadata.get("codex_artifacts"), dict)
            else {},
            message=result.message,
        )


def run_repair(
    repair_request: dict[str, Any],
    *,
    run_dir: Path,
    repo_root: Path,
    config: CodexExecutorConfig,
    provider: str = "codex",
) -> RepairResult:
    providers: dict[str, CodeAgentExecutor] = {"codex": CodexCodeAgentProvider()}
    executor = providers.get(provider)
    if executor is None:
        raise ValueError(f"Unsupported CodeAgentExecutor provider: {provider}")
    return executor.run_repair(repair_request, run_dir=run_dir, repo_root=repo_root, config=config)


def _repair_context(repair_request: dict[str, Any], *, run_dir: Path, repo_root: Path) -> Any:
    app_slug = str(repair_request.get("app_slug") or "").strip()
    problem = str(repair_request.get("problem") or "").strip()
    expected = repair_request.get("expected_behavior") if isinstance(repair_request.get("expected_behavior"), list) else []
    constraints = repair_request.get("constraints") if isinstance(repair_request.get("constraints"), list) else []
    verification = repair_request.get("verification") if isinstance(repair_request.get("verification"), list) else []
    brief = problem or f"Repair published generated app {app_slug}"
    return SimpleNamespace(
        run_id=run_dir.name,
        run_dir=run_dir,
        repo_root=repo_root,
        brief=brief,
        inputs={
            "app_slug": app_slug,
            "repair_id": str(repair_request.get("repair_id") or "").strip(),
            "repair_request": repair_request,
            "allowed_paths": [f"generated_apps/{app_slug}"] if app_slug else ["generated_apps/"],
            "verification_commands": [str(item) for item in verification if item],
            "constraints": [str(item) for item in constraints if item],
            "expected_behavior": [str(item) for item in expected if item],
        },
        domain=SimpleNamespace(
            domain_id="app_generation",
            metadata={},
            risk_rules=[],
            evaluation_rules=[],
        ),
        record=SimpleNamespace(brief=brief),
    )
