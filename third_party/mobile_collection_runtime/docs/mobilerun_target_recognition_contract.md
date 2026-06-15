# Mobilerun Target Recognition Contract

## Purpose

This contract defines the structured output expected from Mobilerun when it is
used to identify a UI target. The response is a candidate, not permission to
click.

## Request

The runtime sends:

```json
{
  "item_id": "item-1",
  "stage": "home",
  "target_type": "image_search_button",
  "prompt": "Find the Taobao image search camera entry.",
  "rank": null,
  "context": {}
}
```

## Required Response

```json
{
  "target_type": "image_search_button",
  "bounds": [0.84, 0.04, 0.96, 0.14],
  "confidence": 0.92,
  "evidence": ["camera icon inside search bar"],
  "page_state": "home",
  "risk_markers": [],
  "recommended_action": "tap"
}
```

Fields:

- `target_type`: requested target type.
- `bounds`: normalized `[x1, y1, x2, y2]` in screen coordinates.
- `confidence`: `0.0` to `1.0`.
- `evidence`: visible UI clues supporting the target.
- `page_state`: Mobilerun's page classification.
- `risk_markers`: login, captcha, security, cart, order, or payment markers.
- `recommended_action`: usually `tap`, `swipe`, `type`, or `stop`.

## Decision Policy

- `confidence >= 0.85`: action may execute if no risk markers exist.
- `0.60 <= confidence < 0.85`: do not click automatically; one retry or debug
  capture is allowed.
- `confidence < 0.60`: do not click.
- Any `risk_markers`: stop regardless of confidence.
- Missing required fields: write debug output and fail the recognition step.

## Budget

Defaults:

- max 5 target-recognition calls per item;
- max 2 calls per stage;
- max 1 abnormal recovery per rank.

When exhausted, write `mobilerun_budget_exhausted` and stop the current item or
evaluation task.

## Trace

Every call writes to `trace.jsonl` with:

- request;
- raw response;
- parsed result or validation error;
- runtime decision event.
