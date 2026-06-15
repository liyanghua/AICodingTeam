from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class MobileCollectionRuntimeTests(unittest.TestCase):
    def test_high_confidence_target_is_allowed_and_events_are_written(self) -> None:
        from third_party.mobile_collection_runtime.mobile_collection_runtime.runtime import (
            Budget,
            FakeMobilerunAdapter,
            RecognitionRequest,
            RuntimePolicy,
            TargetRecognitionRuntime,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = TargetRecognitionRuntime(
                root,
                FakeMobilerunAdapter(
                    [
                        {
                            "target_type": "image_search_button",
                            "bounds": [0.84, 0.04, 0.96, 0.14],
                            "confidence": 0.92,
                            "evidence": ["camera icon in search bar"],
                            "page_state": "home",
                            "risk_markers": [],
                            "recommended_action": "tap",
                        }
                    ]
                ),
                RuntimePolicy(budget=Budget(max_item_calls=5, max_stage_calls=2)),
            )

            result = runtime.recognize(
                RecognitionRequest(
                    item_id="item-1",
                    stage="home",
                    target_type="image_search_button",
                    prompt="Find Taobao image search entry",
                )
            )

            self.assertTrue(result.allowed)
            self.assertEqual(result.event, "mobilerun_target_recognition_succeeded")
            self.assertEqual(result.response.bounds, [0.84, 0.04, 0.96, 0.14])
            events = _read_jsonl(root / "step_events.jsonl")
            self.assertEqual(
                [event["event"] for event in events],
                [
                    "mobilerun_target_recognition_requested",
                    "mobilerun_target_recognition_succeeded",
                ],
            )

    def test_low_confidence_target_is_not_allowed(self) -> None:
        from third_party.mobile_collection_runtime.mobile_collection_runtime.runtime import (
            FakeMobilerunAdapter,
            RecognitionRequest,
            TargetRecognitionRuntime,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = TargetRecognitionRuntime(
                root,
                FakeMobilerunAdapter(
                    [
                        {
                            "target_type": "image_search_button",
                            "bounds": [0.1, 0.1, 0.2, 0.2],
                            "confidence": 0.52,
                            "evidence": ["unclear icon"],
                            "page_state": "home",
                            "risk_markers": [],
                            "recommended_action": "tap",
                        }
                    ]
                ),
            )

            result = runtime.recognize(
                RecognitionRequest(
                    item_id="item-1",
                    stage="home",
                    target_type="image_search_button",
                    prompt="Find Taobao image search entry",
                )
            )

            self.assertFalse(result.allowed)
            self.assertEqual(result.event, "mobilerun_target_recognition_low_confidence")
            self.assertEqual(len(runtime.adapter.calls), 1)

    def test_risk_marker_blocks_even_high_confidence_target(self) -> None:
        from third_party.mobile_collection_runtime.mobile_collection_runtime.runtime import (
            FakeMobilerunAdapter,
            RecognitionRequest,
            TargetRecognitionRuntime,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = TargetRecognitionRuntime(
                root,
                FakeMobilerunAdapter(
                    [
                        {
                            "target_type": "image_search_button",
                            "bounds": [0.84, 0.04, 0.96, 0.14],
                            "confidence": 0.95,
                            "evidence": ["camera icon"],
                            "page_state": "login",
                            "risk_markers": ["请登录"],
                            "recommended_action": "tap",
                        }
                    ]
                ),
            )

            result = runtime.recognize(
                RecognitionRequest(
                    item_id="item-1",
                    stage="home",
                    target_type="image_search_button",
                    prompt="Find Taobao image search entry",
                )
            )

            self.assertFalse(result.allowed)
            self.assertEqual(result.event, "mobilerun_risk_marker_detected")
            risk_events = _read_jsonl(root / "risk_events.jsonl")
            self.assertEqual(risk_events[0]["risk_markers"], ["请登录"])

    def test_budget_exhaustion_stops_before_adapter_call(self) -> None:
        from third_party.mobile_collection_runtime.mobile_collection_runtime.runtime import (
            Budget,
            FakeMobilerunAdapter,
            RecognitionRequest,
            RuntimePolicy,
            TargetRecognitionRuntime,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            adapter = FakeMobilerunAdapter(
                [
                    {
                        "target_type": "image_search_button",
                        "bounds": [0.84, 0.04, 0.96, 0.14],
                        "confidence": 0.92,
                        "evidence": ["camera icon"],
                        "page_state": "home",
                        "risk_markers": [],
                        "recommended_action": "tap",
                    }
                ]
            )
            runtime = TargetRecognitionRuntime(
                root,
                adapter,
                RuntimePolicy(budget=Budget(max_item_calls=1, max_stage_calls=1)),
            )
            request = RecognitionRequest(
                item_id="item-1",
                stage="home",
                target_type="image_search_button",
                prompt="Find Taobao image search entry",
            )

            self.assertTrue(runtime.recognize(request).allowed)
            result = runtime.recognize(request)

            self.assertFalse(result.allowed)
            self.assertEqual(result.event, "mobilerun_budget_exhausted")
            self.assertEqual(len(adapter.calls), 1)

    def test_invalid_structured_output_writes_debug_and_fails(self) -> None:
        from third_party.mobile_collection_runtime.mobile_collection_runtime.runtime import (
            FakeMobilerunAdapter,
            RecognitionRequest,
            TargetRecognitionRuntime,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = TargetRecognitionRuntime(
                root,
                FakeMobilerunAdapter([{"target_type": "image_search_button"}]),
            )

            result = runtime.recognize(
                RecognitionRequest(
                    item_id="item-1",
                    stage="home",
                    target_type="image_search_button",
                    prompt="Find Taobao image search entry",
                )
            )

            self.assertFalse(result.allowed)
            self.assertEqual(result.event, "mobilerun_structured_output_invalid")
            self.assertTrue((root / "debug" / "mobilerun_structured_output_invalid.json").exists())

    def test_taobao_image_search_eval_writes_summary_and_trace(self) -> None:
        from third_party.mobile_collection_runtime.mobile_collection_runtime.taobao_eval import (
            FakeTaobaoImageSearchDevice,
            run_taobao_image_search_eval,
        )
        from third_party.mobile_collection_runtime.mobile_collection_runtime.runtime import (
            FakeMobilerunAdapter,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reference = root / "ref.jpg"
            reference.write_bytes(b"fake-image")
            output_root = root / "eval_runs"

            summary = run_taobao_image_search_eval(
                output_root=output_root,
                reference_image=reference,
                adapter=FakeMobilerunAdapter(
                    [
                        {
                            "target_type": "image_search_button",
                            "bounds": [0.84, 0.04, 0.96, 0.14],
                            "confidence": 0.93,
                            "evidence": ["camera icon in Taobao search bar"],
                            "page_state": "home",
                            "risk_markers": [],
                            "recommended_action": "tap",
                        },
                        {
                            "target_type": "album_entry",
                            "bounds": [0.2, 0.82, 0.8, 0.95],
                            "confidence": 0.91,
                            "evidence": ["album grid visible"],
                            "page_state": "album",
                            "risk_markers": [],
                            "recommended_action": "tap",
                        },
                        {
                            "target_type": "first_album_image",
                            "bounds": [0.04, 0.18, 0.32, 0.4],
                            "confidence": 0.9,
                            "evidence": ["first reference thumbnail"],
                            "page_state": "album",
                            "risk_markers": [],
                            "recommended_action": "tap",
                        },
                    ]
                ),
                device=FakeTaobaoImageSearchDevice(),
                run_id="eval-1",
            )

            run_dir = output_root / "eval-1"
            self.assertEqual(summary["status"], "completed")
            self.assertTrue((run_dir / "summary.json").exists())
            self.assertTrue((run_dir / "trace.jsonl").exists())
            event_names = [event["event"] for event in _read_jsonl(run_dir / "step_events.jsonl")]
            self.assertIn("taobao_image_search_button_tapped", event_names)
            self.assertIn("taobao_album_page_reached", event_names)
            self.assertIn("taobao_image_search_results_reached", event_names)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
