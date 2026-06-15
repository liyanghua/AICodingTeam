from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


REQUIRED_RESPONSE_FIELDS = {
    "target_type",
    "bounds",
    "confidence",
    "evidence",
    "page_state",
    "risk_markers",
    "recommended_action",
}


@dataclass(frozen=True)
class Budget:
    max_item_calls: int = 5
    max_stage_calls: int = 2
    max_rank_recoveries: int = 1


@dataclass(frozen=True)
class RuntimePolicy:
    allow_threshold: float = 0.85
    retry_threshold: float = 0.60
    budget: Budget = field(default_factory=Budget)


@dataclass(frozen=True)
class RecognitionRequest:
    item_id: str
    stage: str
    target_type: str
    prompt: str
    rank: int | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TargetRecognitionResponse:
    target_type: str
    bounds: list[float]
    confidence: float
    evidence: list[str]
    page_state: str
    risk_markers: list[str]
    recommended_action: str


@dataclass(frozen=True)
class RecognitionResult:
    allowed: bool
    event: str
    response: TargetRecognitionResponse | None = None
    reason: str = ""


class MobilerunAdapter(Protocol):
    def recognize_target(self, request: RecognitionRequest) -> dict[str, Any]: ...


class FakeMobilerunAdapter:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[RecognitionRequest] = []

    def recognize_target(self, request: RecognitionRequest) -> dict[str, Any]:
        self.calls.append(request)
        if not self.responses:
            raise RuntimeError("fake Mobilerun adapter has no responses left")
        return self.responses.pop(0)


class TargetRecognitionRuntime:
    def __init__(
        self,
        output_dir: Path,
        adapter: MobilerunAdapter,
        policy: RuntimePolicy | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.adapter = adapter
        self.policy = policy or RuntimePolicy()
        self._item_calls: dict[str, int] = {}
        self._stage_calls: dict[tuple[str, str], int] = {}
        self._prepare_output_dir()

    def recognize(self, request: RecognitionRequest) -> RecognitionResult:
        if self._budget_exhausted(request):
            event = {
                "event": "mobilerun_budget_exhausted",
                "item_id": request.item_id,
                "stage": request.stage,
                "target_type": request.target_type,
            }
            self._write_event(event)
            self._write_risk_event(event)
            return RecognitionResult(False, event["event"], reason="budget exhausted")

        self._consume_budget(request)
        self._write_event(
            {
                "event": "mobilerun_target_recognition_requested",
                "item_id": request.item_id,
                "stage": request.stage,
                "target_type": request.target_type,
                "prompt": request.prompt,
            }
        )
        raw_response = self.adapter.recognize_target(request)
        self._append_jsonl(self.output_dir / "trace.jsonl", {"request": request.__dict__, "response": raw_response})
        try:
            response = _parse_response(raw_response)
        except ValueError as exc:
            self._write_debug("mobilerun_structured_output_invalid", raw_response)
            event = {
                "event": "mobilerun_structured_output_invalid",
                "item_id": request.item_id,
                "stage": request.stage,
                "target_type": request.target_type,
                "reason": str(exc),
            }
            self._write_event(event)
            self._write_risk_event(event)
            return RecognitionResult(False, event["event"], reason=str(exc))

        if response.risk_markers:
            event = {
                "event": "mobilerun_risk_marker_detected",
                "item_id": request.item_id,
                "stage": request.stage,
                "target_type": request.target_type,
                "risk_markers": response.risk_markers,
                "page_state": response.page_state,
            }
            self._write_event(event)
            self._write_risk_event(event)
            return RecognitionResult(False, event["event"], response=response, reason="risk marker detected")

        if response.confidence < self.policy.allow_threshold:
            event = {
                "event": "mobilerun_target_recognition_low_confidence",
                "item_id": request.item_id,
                "stage": request.stage,
                "target_type": request.target_type,
                "confidence": response.confidence,
                "retry_allowed": response.confidence >= self.policy.retry_threshold,
            }
            self._write_event(event)
            return RecognitionResult(False, event["event"], response=response, reason="low confidence")

        event = {
            "event": "mobilerun_target_recognition_succeeded",
            "item_id": request.item_id,
            "stage": request.stage,
            "target_type": request.target_type,
            "confidence": response.confidence,
            "bounds": response.bounds,
            "page_state": response.page_state,
        }
        self._write_event(event)
        return RecognitionResult(True, event["event"], response=response)

    def _budget_exhausted(self, request: RecognitionRequest) -> bool:
        item_calls = self._item_calls.get(request.item_id, 0)
        stage_calls = self._stage_calls.get((request.item_id, request.stage), 0)
        return (
            item_calls >= self.policy.budget.max_item_calls
            or stage_calls >= self.policy.budget.max_stage_calls
        )

    def _consume_budget(self, request: RecognitionRequest) -> None:
        self._item_calls[request.item_id] = self._item_calls.get(request.item_id, 0) + 1
        key = (request.item_id, request.stage)
        self._stage_calls[key] = self._stage_calls.get(key, 0) + 1

    def _prepare_output_dir(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "debug").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "step_events.jsonl").touch()
        (self.output_dir / "risk_events.jsonl").touch()
        (self.output_dir / "trace.jsonl").touch()

    def _write_event(self, event: dict[str, Any]) -> None:
        self._append_jsonl(self.output_dir / "step_events.jsonl", event)

    def _write_risk_event(self, event: dict[str, Any]) -> None:
        self._append_jsonl(self.output_dir / "risk_events.jsonl", event)

    def _write_debug(self, name: str, payload: dict[str, Any]) -> None:
        (self.output_dir / "debug" / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _parse_response(payload: dict[str, Any]) -> TargetRecognitionResponse:
    missing = sorted(REQUIRED_RESPONSE_FIELDS - set(payload))
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")
    bounds = payload["bounds"]
    if not isinstance(bounds, list) or len(bounds) != 4:
        raise ValueError("bounds must be [x1, y1, x2, y2]")
    evidence = payload["evidence"]
    if not isinstance(evidence, list):
        raise ValueError("evidence must be a list")
    risk_markers = payload["risk_markers"]
    if not isinstance(risk_markers, list):
        raise ValueError("risk_markers must be a list")
    return TargetRecognitionResponse(
        target_type=str(payload["target_type"]),
        bounds=[float(value) for value in bounds],
        confidence=float(payload["confidence"]),
        evidence=[str(value) for value in evidence],
        page_state=str(payload["page_state"]),
        risk_markers=[str(value) for value in risk_markers],
        recommended_action=str(payload["recommended_action"]),
    )
