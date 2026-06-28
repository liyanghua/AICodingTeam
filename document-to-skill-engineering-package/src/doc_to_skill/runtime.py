from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class NodeTrace:
    node_id: str
    status: str
    started_at: float
    ended_at: float
    output_ref: str | None = None
    error: str | None = None


@dataclass
class RuntimeResult:
    skill_run_id: str
    traces: list[NodeTrace] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)


class MockRuntimeExecutor:
    """A deterministic mock DAG executor.

    Replace this with LangGraph / OpenClaw / Temporal in production.
    """

    def execute(self, workflow: dict, inputs: dict[str, Any]) -> RuntimeResult:
        result = RuntimeResult(skill_run_id=f"run_{int(time.time())}")
        for node in workflow.get("nodes", []):
            start = time.time()
            node_id = node["id"]
            output_ref = f"mock://outputs/{node_id}.json"
            result.outputs[node_id] = {
                "node_id": node_id,
                "inputs": inputs,
                "mock": True,
                "message": f"Executed {node_id} with mock backend.",
            }
            end = time.time()
            result.traces.append(NodeTrace(node_id=node_id, status="success", started_at=start, ended_at=end, output_ref=output_ref))
        return result
