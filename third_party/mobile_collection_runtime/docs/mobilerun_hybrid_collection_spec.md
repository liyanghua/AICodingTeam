# Mobilerun Hybrid Collection Spec

## Summary

Mobilerun is used as a target-recognition and diagnosis layer, not as the owner
of collection success. Deterministic collectors keep responsibility for safety
gates, media pulling, artifact writing, deduplication, and cloud sync.

The strategy is:

- Adapted channels: deterministic first, Mobilerun fallback only when target
  detection or page recovery fails.
- New-channel validation: Mobilerun first, record traces, then gradually extract
  stable deterministic markers and helpers.
- High-frequency batch collection: deterministic only; failed samples are
  diagnosed later with Mobilerun.

## Safety Boundary

- Manual login only.
- Do not automate credential entry, captcha solving, anti-risk bypass, private
  APIs, add-to-cart, order, or payment actions.
- Risk markers override confidence. If Mobilerun reports login, captcha,
  security verification, cart, order, or payment context, the runtime must stop.
- Mobilerun may propose candidate targets. The runtime decides whether an action
  is allowed.

## Runtime Responsibilities

- Enforce confidence thresholds and call budgets.
- Execute taps/swipes only after gates pass.
- Write `step_events.jsonl`, `risk_events.jsonl`, `trace.jsonl`, `debug/`, and
  `summary.json`.
- Preserve existing collector output contracts when a runtime is later attached
  to a production path.
- Keep Mobilerun traces separate from existing deterministic collector runs until
  a path is explicitly promoted.

## Execution Profiles

### Adapted Channel

Use deterministic state machines as the main path. Mobilerun is allowed only for:

- locating a missing target such as image-search entry, search box, save menu, or
  non-video hero image;
- diagnosing a page-state mismatch;
- recovering a single rank/item after a deterministic target detector fails.

Default budget: 5 calls per item, 2 calls per stage, 1 recovery per rank.

### New Channel

Use Mobilerun for low-frequency validation. Every action must produce a trace
entry with prompt, structured response, confidence, evidence, and final runtime
decision. Successful traces should be reviewed and converted into stable
markers, target detectors, or deterministic helpers.

### High-Frequency Batch

No Mobilerun calls in the hot path. Failed samples are queued for offline
diagnosis with screenshots, UI hierarchy, and prior step events.

## Events

Minimum Mobilerun target-recognition events:

```text
mobilerun_target_recognition_requested
mobilerun_target_recognition_succeeded
mobilerun_target_recognition_low_confidence
mobilerun_structured_output_invalid
mobilerun_risk_marker_detected
mobilerun_budget_exhausted
```

Evaluation tasks may add channel-specific events such as:

```text
taobao_image_search_button_tapped
taobao_album_page_reached
taobao_image_search_results_reached
```

## Promotion Rule

A Mobilerun-assisted path can be promoted to deterministic only after it has:

- at least one successful trace with screenshots/UI hierarchy;
- stable page-state markers;
- clear risk markers;
- replayable tests using fake adapter outputs;
- an explicit event contract.
