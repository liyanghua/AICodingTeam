from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Self

from .yaml_io import load_yaml_subset


GATE_AGENT_TARGETS = {
    "before_coding": "coder",
    "before_publish": "publisher",
}


@dataclass(slots=True)
class AgentSpec:
    id: str
    role: str = ""
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            id=str(data.get("id", "")),
            role=str(data.get("role", "")),
            inputs=[str(item) for item in data.get("inputs", [])],
            outputs=[str(item) for item in data.get("outputs", [])],
            description=str(data.get("description", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class GateSpec:
    id: str
    required_artifacts: list[str] = field(default_factory=list)
    before_agent: str = ""
    description: str = ""

    @property
    def required(self) -> list[str]:
        return self.required_artifacts

    @classmethod
    def from_config(cls, gate_id: str, data: Any) -> Self:
        if isinstance(data, list):
            return cls(
                id=gate_id,
                required_artifacts=[str(item) for item in data],
                before_agent=GATE_AGENT_TARGETS.get(gate_id, ""),
            )
        if isinstance(data, dict):
            required = data.get("required_artifacts", data.get("required", data.get("artifacts", [])))
            return cls(
                id=str(data.get("id", gate_id)),
                required_artifacts=[str(item) for item in required],
                before_agent=str(data.get("before_agent", GATE_AGENT_TARGETS.get(gate_id, ""))),
                description=str(data.get("description", "")),
            )
        raise TypeError(f"Unsupported gate config for {gate_id}: {type(data).__name__}")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls.from_config(str(data.get("id", "")), data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TeamSpec:
    team_id: str
    agents: list[AgentSpec] = field(default_factory=list)
    gates: list[GateSpec] = field(default_factory=list)
    version: str = "1"
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        gates_data = data.get("gates", {})
        if isinstance(gates_data, dict):
            gates = [GateSpec.from_config(str(gate_id), config) for gate_id, config in gates_data.items()]
        elif isinstance(gates_data, list):
            gates = [GateSpec.from_dict(item) for item in gates_data if isinstance(item, dict)]
        else:
            gates = []

        spec = cls(
            team_id=str(data.get("team_id", "ai_native_engineering_team")),
            agents=[AgentSpec.from_dict(item) for item in data.get("agents", [])],
            gates=gates,
            version=str(data.get("version", "1")),
            description=str(data.get("description", "")),
        )
        spec.validate()
        return spec

    @classmethod
    def from_path(cls, path: Path | str) -> Self:
        return cls.from_dict(load_yaml_subset(Path(path)))

    from_file = from_path
    from_yaml = from_path
    load = from_path

    def to_dict(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "version": self.version,
            "description": self.description,
            "agents": [agent.to_dict() for agent in self.agents],
            "gates": [gate.to_dict() for gate in self.gates],
        }

    def gates_before(self, agent_id: str) -> list[GateSpec]:
        return [gate for gate in self.gates if gate.before_agent == agent_id]

    def gate_by_id(self, gate_id: str) -> GateSpec:
        for gate in self.gates:
            if gate.id == gate_id:
                return gate
        raise KeyError(f"Unknown gate: {gate_id}")

    def validate(self) -> None:
        if not self.agents:
            raise ValueError("team agents are required")
        for agent in self.agents:
            if not agent.id:
                raise ValueError("agent id is required")
            if not agent.outputs:
                raise ValueError(f"agent {agent.id} outputs are required")


@dataclass(slots=True)
class DomainSpec:
    domain_id: str
    title: str = ""
    summary: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: Any = field(default_factory=dict)
    defaults: dict[str, Any] = field(default_factory=dict)
    frameworks: list[str] = field(default_factory=list)
    risk_rules: list[str] = field(default_factory=list)
    evaluation_rules: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        known = {
            "domain_id",
            "title",
            "summary",
            "input_schema",
            "output_schema",
            "defaults",
            "frameworks",
            "risk_rules",
            "evaluation_rules",
        }
        metadata = {str(key): value for key, value in data.items() if key not in known}
        return cls(
            domain_id=str(data.get("domain_id", "")),
            title=str(data.get("title", "")),
            summary=str(data.get("summary", "")),
            input_schema=dict(data.get("input_schema", {})),
            output_schema=data.get("output_schema", {}),
            defaults=dict(data.get("defaults", {})),
            frameworks=[str(item) for item in data.get("frameworks", [])],
            risk_rules=[str(item) for item in data.get("risk_rules", [])],
            evaluation_rules=[str(item) for item in data.get("evaluation_rules", [])],
            metadata=metadata,
        )

    @classmethod
    def from_path(cls, path: Path | str) -> Self:
        return cls.from_dict(load_yaml_subset(Path(path)))

    from_file = from_path
    from_yaml = from_path
    load = from_path

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        metadata = payload.pop("metadata")
        payload.update(metadata)
        return payload


@dataclass(slots=True)
class GateResult:
    gate_id: str
    status: str
    required_artifacts: list[str] = field(default_factory=list)
    missing_artifacts: list[str] = field(default_factory=list)
    checked_at: str = ""
    before_agent: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            gate_id=str(data.get("gate_id", "")),
            status=str(data.get("status", "unknown")),
            required_artifacts=[str(item) for item in data.get("required_artifacts", [])],
            missing_artifacts=[str(item) for item in data.get("missing_artifacts", [])],
            checked_at=str(data.get("checked_at", "")),
            before_agent=str(data.get("before_agent", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AgentRun:
    agent_id: str
    status: str = "pending"
    started_at: str = ""
    finished_at: str = ""
    risk_events: list[str] = field(default_factory=list)
    output_paths: list[str] = field(default_factory=list)
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            agent_id=str(data.get("agent_id", "")),
            status=str(data.get("status", "pending")),
            started_at=str(data.get("started_at", "")),
            finished_at=str(data.get("finished_at", "")),
            risk_events=[str(item) for item in data.get("risk_events", [])],
            output_paths=[str(item) for item in data.get("output_paths", [])],
            message=str(data.get("message", "")),
            metadata=dict(data.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TeamRunRecord:
    run_id: str
    domain_id: str
    brief: str
    team_id: str = "ai_native_engineering_team"
    status: str = "pending"
    run_dir: Path = Path("runs")
    started_at: str = ""
    finished_at: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    agent_runs: list[AgentRun] = field(default_factory=list)
    gate_results: list[GateResult] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    output_paths: list[str] = field(default_factory=list)
    risk_events: list[str] = field(default_factory=list)
    executor: str = "deterministic"
    executor_config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            run_id=str(data.get("run_id", "")),
            domain_id=str(data.get("domain_id", "")),
            brief=str(data.get("brief", "")),
            team_id=str(data.get("team_id", "ai_native_engineering_team")),
            status=str(data.get("status", "pending")),
            run_dir=Path(data.get("run_dir", "runs")),
            started_at=str(data.get("started_at", "")),
            finished_at=str(data.get("finished_at", "")),
            inputs=dict(data.get("inputs", {})),
            agent_runs=[AgentRun.from_dict(item) for item in data.get("agent_runs", [])],
            gate_results=[GateResult.from_dict(item) for item in data.get("gate_results", [])],
            artifacts={str(key): str(value) for key, value in data.get("artifacts", {}).items()},
            output_paths=[str(item) for item in data.get("output_paths", [])],
            risk_events=[str(item) for item in data.get("risk_events", [])],
            executor=str(data.get("executor", "deterministic")),
            executor_config=dict(data.get("executor_config") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "team_id": self.team_id,
            "domain_id": self.domain_id,
            "brief": self.brief,
            "status": self.status,
            "run_dir": str(self.run_dir),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "inputs": self.inputs,
            "agent_runs": [agent_run.to_dict() for agent_run in self.agent_runs],
            "gate_results": [gate_result.to_dict() for gate_result in self.gate_results],
            "artifacts": self.artifacts,
            "output_paths": self.output_paths,
            "risk_events": self.risk_events,
            "executor": self.executor,
            "executor_config": self.executor_config,
        }

    def add_agent_run(self, agent_run: AgentRun) -> None:
        self.agent_runs.append(agent_run)
        for output_path in agent_run.output_paths:
            self.artifacts[Path(output_path).name] = output_path
            if output_path not in self.output_paths:
                self.output_paths.append(output_path)
        self.risk_events.extend(agent_run.risk_events)
