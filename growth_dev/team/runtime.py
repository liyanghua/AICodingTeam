from __future__ import annotations

from pathlib import Path
from typing import Any

from ..utils import ensure_dir, now_iso, timestamp_slug, write_json
from .agents import AgentContext, run_deterministic_agent
from .codex import CodexExecutorConfig, load_aicodemirror_provider_from_env
from .domain import load_domain_spec, load_team_spec
from .models import AgentRun, AgentSpec, GateResult, GateSpec, TeamRunRecord, TeamSpec


class GateFailure(RuntimeError):
    def __init__(self, result: GateResult) -> None:
        self.result = result
        missing = ", ".join(result.missing_artifacts)
        super().__init__(f"Gate {result.gate_id} failed; missing artifacts: {missing}")


def default_team_spec() -> TeamSpec:
    return TeamSpec(
        team_id="ai_native_engineering_team",
        description="Deterministic local agent team for AI-native engineering runs.",
        agents=[
            AgentSpec(id="orchestrator", outputs=["task.yaml", "context.md"]),
            AgentSpec(id="product", outputs=["prd.md"]),
            AgentSpec(id="architect", outputs=["tech_spec.md"]),
            AgentSpec(id="ux", outputs=["ui_spec.md"]),
            AgentSpec(id="qa", outputs=["eval.md"]),
            AgentSpec(id="coder", outputs=["coding_prompt.md", "code_run_record.json"]),
            AgentSpec(id="reviewer", outputs=["review_report.md"]),
            AgentSpec(id="verifier", outputs=["test_report.md"]),
            AgentSpec(id="publisher", outputs=["final_report.md"]),
        ],
        gates=[
            GateSpec(
                id="before_coding",
                before_agent="coder",
                required_artifacts=["prd.md", "tech_spec.md", "ui_spec.md", "eval.md"],
            ),
            GateSpec(
                id="before_publish",
                before_agent="publisher",
                required_artifacts=["review_report.md", "test_report.md"],
            ),
        ],
    )


def check_gate(gate: GateSpec, run_dir: Path) -> GateResult:
    missing = [artifact for artifact in gate.required_artifacts if not _artifact_exists(run_dir, artifact)]
    return GateResult(
        gate_id=gate.id,
        status="failed" if missing else "passed",
        required_artifacts=list(gate.required_artifacts),
        missing_artifacts=missing,
        checked_at=now_iso(),
        before_agent=gate.before_agent,
    )


def enforce_gate(gate: GateSpec, run_dir: Path) -> GateResult:
    result = check_gate(gate, run_dir)
    if result.status != "passed":
        raise GateFailure(result)
    return result


class TeamRuntime:
    def __init__(
        self,
        team: TeamSpec | None = None,
        domain=None,
        runs_dir: Path = Path("runs"),
        *,
        team_spec: TeamSpec | None = None,
        domain_spec=None,
        repo_root: Path | None = None,
        executor: str = "deterministic",
        codex_binary: str = "codex",
        codex_model: str = "gpt-5.3-codex",
        codex_reasoning_effort: str = "medium",
        codex_provider: str = "default",
        codex_env_file: Path | None = None,
    ) -> None:
        self.team = team if team is not None else team_spec
        self.domain = domain if domain is not None else domain_spec
        if self.team is None:
            raise ValueError("team spec is required")
        if self.domain is None:
            raise ValueError("domain spec is required")
        if executor not in {"deterministic", "codex"}:
            raise ValueError(f"Unsupported executor: {executor}")
        self.runs_dir = runs_dir
        self.repo_root = Path(repo_root or Path.cwd())
        self.executor = executor
        provider_config = None
        if codex_provider == "aicodemirror":
            env_path = Path(codex_env_file or ".env")
            if not env_path.is_absolute():
                env_path = self.repo_root / env_path
            provider_config = load_aicodemirror_provider_from_env(env_path)
        elif codex_provider not in {"default", ""}:
            raise ValueError(f"Unsupported codex provider: {codex_provider}")
        self.codex_config = CodexExecutorConfig(
            binary=codex_binary,
            model=codex_model,
            reasoning_effort=codex_reasoning_effort,
            provider=provider_config,
        )

    @classmethod
    def from_files(
        cls,
        team_path: Path,
        domain_id: str,
        domains_dir: Path = Path("domains"),
        runs_dir: Path = Path("runs"),
        repo_root: Path | None = None,
        executor: str = "deterministic",
        codex_binary: str = "codex",
        codex_model: str = "gpt-5.3-codex",
        codex_reasoning_effort: str = "medium",
        codex_provider: str = "default",
        codex_env_file: Path | None = None,
    ) -> "TeamRuntime":
        return cls(
            team=load_team_spec(team_path),
            domain=load_domain_spec(domain_id, domains_dir=domains_dir),
            runs_dir=runs_dir,
            repo_root=repo_root,
            executor=executor,
            codex_binary=codex_binary,
            codex_model=codex_model,
            codex_reasoning_effort=codex_reasoning_effort,
            codex_provider=codex_provider,
            codex_env_file=codex_env_file,
        )

    @classmethod
    def from_domain(
        cls,
        domain_id: str,
        domains_dir: Path = Path("domains"),
        runs_dir: Path = Path("runs"),
        team: TeamSpec | None = None,
        repo_root: Path | None = None,
        executor: str = "deterministic",
        codex_binary: str = "codex",
        codex_model: str = "gpt-5.3-codex",
        codex_reasoning_effort: str = "medium",
        codex_provider: str = "default",
        codex_env_file: Path | None = None,
    ) -> "TeamRuntime":
        return cls(
            team=team or default_team_spec(),
            domain=load_domain_spec(domain_id, domains_dir=domains_dir),
            runs_dir=runs_dir,
            repo_root=repo_root,
            executor=executor,
            codex_binary=codex_binary,
            codex_model=codex_model,
            codex_reasoning_effort=codex_reasoning_effort,
            codex_provider=codex_provider,
            codex_env_file=codex_env_file,
        )

    def run(
        self,
        brief: str,
        inputs: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> TeamRunRecord:
        ensure_dir(self.runs_dir)
        actual_run_id = run_id or f"{self.domain.domain_id}-{timestamp_slug()}"
        run_dir = ensure_dir(self.runs_dir / actual_run_id)
        record = TeamRunRecord(
            run_id=actual_run_id,
            team_id=self.team.team_id,
            domain_id=self.domain.domain_id,
            brief=brief,
            status="running",
            run_dir=run_dir,
            started_at=now_iso(),
            inputs=dict(inputs or {}),
            executor=self.executor,
            executor_config=self.codex_config.to_dict() if self.executor == "codex" else {},
        )
        self._write_record(record)
        write_json(run_dir / "team_spec.json", self.team.to_dict())
        write_json(run_dir / "domain_spec.json", self.domain.to_dict())

        for agent in self.team.agents:
            gate_failed = self._run_gates_before(agent.id, record)
            if gate_failed:
                record.status = "failed"
                record.finished_at = now_iso()
                self._write_record(record)
                return record

            agent_context = AgentContext(
                run_id=actual_run_id,
                run_dir=run_dir,
                brief=brief,
                team=self.team,
                domain=self.domain,
                inputs=dict(inputs or {}),
                record=record,
                repo_root=self.repo_root,
                executor=self.executor,
                codex_config=self.codex_config,
            )
            running_run = AgentRun(
                agent_id=agent.id,
                status="running",
                started_at=now_iso(),
                finished_at="",
                risk_events=[],
                output_paths=[],
                message="agent started",
            )
            record.agent_runs.append(running_run)
            self._write_record(record)
            agent_run = run_deterministic_agent(agent, agent_context)
            missing_outputs = self._missing_declared_outputs(agent, run_dir)
            if missing_outputs and agent_run.status == "completed":
                agent_run.status = "failed"
                agent_run.risk_events.append(f"missing_declared_outputs:{','.join(missing_outputs)}")
                agent_run.message = f"Missing declared outputs: {', '.join(missing_outputs)}"
            record.agent_runs[-1] = agent_run
            record.add_agent_run_outputs(agent_run)
            self._write_record(record)

            if agent_run.status != "completed":
                record.status = "failed"
                record.finished_at = now_iso()
                self._write_record(record)
                return record

        record.status = "completed"
        record.finished_at = now_iso()
        self._write_record(record)
        return record

    def check_gate(self, run_dir: Path, gate_id: str) -> GateResult:
        return enforce_gate(self.team.gate_by_id(gate_id), run_dir)

    def enforce_gate(self, run_dir: Path, gate_id: str) -> GateResult:
        return self.check_gate(run_dir, gate_id)

    def run_gate(self, run_dir: Path, gate_id: str) -> GateResult:
        return self.check_gate(run_dir, gate_id)

    def _run_gates_before(self, agent_id: str, record: TeamRunRecord) -> bool:
        failed = False
        for gate in self.team.gates_before(agent_id):
            result = check_gate(gate, record.run_dir)
            record.gate_results.append(result)
            if result.status != "passed":
                failed = True
        return failed

    def _missing_declared_outputs(self, agent: AgentSpec, run_dir: Path) -> list[str]:
        return [output for output in agent.outputs if not _artifact_exists(run_dir, output)]

    def _write_record(self, record: TeamRunRecord) -> None:
        write_json(record.run_dir / "team_run_record.json", record.to_dict())

    @staticmethod
    def load_record(run_id: str, runs_dir: Path = Path("runs")) -> TeamRunRecord:
        import json

        path = runs_dir / run_id / "team_run_record.json"
        return TeamRunRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _artifact_exists(run_dir: Path, artifact: str) -> bool:
    path = Path(artifact)
    if path.is_absolute() or ".." in path.parts:
        return False
    return (run_dir / path).exists()
