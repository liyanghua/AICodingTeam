from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .adapters.base import AdapterContext, AdapterFactory, AdapterResult
from .adapters.mock import MockAdapter
from .fixtures import build_candidate_cards, sort_cards_by_comments
from .models import RunRecord, TaskSpec, XhsNote
from .reporting import write_report
from .scoring import framework_score
from .tasks import default_task_spec
from .utils import ensure_dir, now_iso, read_json, timestamp_slug, write_json


DEFAULT_FRAMEWORKS = ["playwright-mcp", "stagehand", "skyvern", "hyperagent", "browser-use"]


@dataclass(slots=True)
class BenchmarkOutcome:
    run_record: RunRecord
    framework_scores: list
    artifacts: dict[str, Path]


def expected_notes(task: TaskSpec) -> list[XhsNote]:
    cards = sort_cards_by_comments(build_candidate_cards(task.keyword, candidate_pool=task.candidate_pool, base_url=task.base_url))
    return [card.note for card in cards[: task.top_n]]


def load_task(task_path: Path | None = None) -> TaskSpec:
    if task_path is None:
        return default_task_spec()
    payload = read_json(task_path)
    return TaskSpec.from_dict(payload)


def _adapter_factories() -> dict[str, AdapterFactory]:
    from .adapters.browser_use import create_browser_use_adapter
    from .adapters.hyperagent import create_hyperagent_adapter
    from .adapters.playwright_mcp import create_playwright_mcp_adapter
    from .adapters.skyvern import create_skyvern_adapter
    from .adapters.stagehand import create_stagehand_adapter

    return {
        "playwright-mcp": create_playwright_mcp_adapter,
        "stagehand": create_stagehand_adapter,
        "skyvern": create_skyvern_adapter,
        "hyperagent": create_hyperagent_adapter,
        "browser-use": create_browser_use_adapter,
    }


def run_framework(task: TaskSpec, framework: str, base_dir: Path, base_url: str | None = None) -> AdapterResult:
    factories = _adapter_factories()
    if framework not in factories:
        raise ValueError(f"Unknown framework: {framework}")
    context = AdapterContext(
        task=task,
        base_url=base_url or task.base_url,
        profile_dir=task.profile_dir,
        run_dir=base_dir,
        framework=framework,
    )
    adapter = factories[framework]()
    return adapter.run(context)


def run_mock(task: TaskSpec, base_dir: Path) -> AdapterResult:
    adapter = MockAdapter()
    context = AdapterContext(
        task=task,
        base_url=task.base_url,
        profile_dir=task.profile_dir,
        run_dir=base_dir,
        framework="mock",
    )
    return adapter.run(context)


def benchmark(task: TaskSpec, frameworks: Iterable[str], runs_dir: Path, suite: str = "pilot") -> BenchmarkOutcome:
    run_id = f"{task.task_id}-{suite}-{timestamp_slug()}"
    run_dir = ensure_dir(runs_dir / run_id)
    record = RunRecord(run_id=run_id, task=task, started_at=now_iso(), base_dir=runs_dir)
    expected = expected_notes(task)
    results: list[AdapterResult] = []

    for framework in frameworks:
        framework_dir = ensure_dir(run_dir / framework)
        if framework == "mock":
            result = run_mock(task, framework_dir)
        else:
            result = run_framework(task, framework, framework_dir, base_url=task.base_url)
        results.append(result)
        write_json(framework_dir / "result.json", result.to_dict())

    record.adapter_results = results
    record.finished_at = now_iso()

    scores = [framework_score(result, expected) for result in results]
    artifacts = write_report(record, scores, run_dir)
    write_json(run_dir / "run_record.json", record.to_dict())
    return BenchmarkOutcome(run_record=record, framework_scores=scores, artifacts=artifacts)
