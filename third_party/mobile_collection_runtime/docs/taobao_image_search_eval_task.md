# Taobao Image Search Mobilerun Evaluation Task

## Goal

Evaluate whether Mobilerun can help identify Taobao image-search targets without
changing the existing `taobao_collector run` deterministic path.

This task validates target recognition and page gates only. It does not require
batch asset download.

## Command Shape

Future real-device command:

```bash
python -m mobile_collection_runtime eval-taobao-image-search \
  --reference-image path/to/ref.jpg \
  --output-root eval_runs \
  --device-serial <optional>
```

Current fake-adapter verification is covered by unit tests.

## Expected Flow

1. Phone is manually logged into Taobao.
2. Runtime asks Mobilerun to identify `image_search_button`.
3. Runtime applies confidence and risk gates.
4. Runtime taps the approved target and verifies album page markers.
5. Runtime asks Mobilerun to identify `album_entry`.
6. Runtime asks Mobilerun to identify `first_album_image`.
7. Runtime taps the image and verifies image-search result markers.
8. Runtime writes trace and summary artifacts.

## Artifacts

Each eval run writes:

```text
summary.json
step_events.jsonl
risk_events.jsonl
trace.jsonl
debug/
```

## Success Events

```text
mobilerun_target_recognition_requested
mobilerun_target_recognition_succeeded
taobao_image_search_button_tapped
taobao_album_page_reached
taobao_image_search_results_reached
```

## Failure Events

```text
mobilerun_target_recognition_low_confidence
mobilerun_structured_output_invalid
mobilerun_risk_marker_detected
mobilerun_budget_exhausted
taobao_album_gate_failed
taobao_image_search_results_not_reached
```

## Acceptance

- If image-search entry cannot be identified with confidence `>= 0.85`, the task
  must not tap.
- If risk markers appear, the task must stop and write `risk_events.jsonl`.
- A successful fake eval writes `summary.json`, `trace.jsonl`, and success
  events.
- No existing XHS or Taobao deterministic collector entrypoint changes.
