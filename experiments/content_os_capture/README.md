# Content OS Capture Prototype

Standalone Android prototype for the Content OS inspiration capture flow.

The prototype validates a narrow V1 loop:

1. Pick a client profile.
2. Start an inspiration capture session.
3. Capture a screenshot from Xiaohongshu through an overlay action.
4. Save the item into the inspiration inbox.
5. Show material completeness and confidence.
6. Generate a mock script package that respects the available material level.

This project is intentionally isolated from the existing mobile workbench,
asset center, collectors, VLM config, and cloud sync code.

## Material Levels

- `L1_SCREENSHOT`: screenshot-only inspiration. Generates a usable draft, but
  only claims visual hook, scene, category hints, and first-screen framing.
- `L2_LINK_TEXT`: screenshot plus link/title/body/tags/comment hints. Generates
  a stronger script package with content structure and selling point framing.
- `L3_RICH_MEDIA`: original image set, key frames, a short recording, or a
  user-provided video. Images can strengthen composition/material/detail
  analysis; videos can strengthen first-three-second, shot rhythm, subtitle, and
  voiceover structure analysis.
- `L4_FULL_REVIEW`: full video, comments, metrics, and account performance. Not
  implemented in V1.

## Build Notes

This directory is a self-contained Android Gradle project skeleton. Install
Android Studio or Gradle locally, then run:

```bash
cd experiments/content_os_capture
gradle test
gradle assembleDebug
```

No production backend or platform private API is used by this prototype.

If Gradle is not installed yet, run the static verification:

```bash
bash experiments/content_os_capture/verify_static.sh
```

## V1 Non-goals

- No Xiaohongshu private API.
- No original video downloading.
- User-provided video is allowed as rich material, but the prototype never
  fetches or downloads the original platform video automatically.
- No background continuous monitoring.
- No real OCR/VLM integration yet.
- No cloud sync or existing asset-center dependency.
