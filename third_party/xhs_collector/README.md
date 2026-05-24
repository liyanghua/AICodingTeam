# XHS Collector

Low-frequency, manual-login Xiaohongshu image collection prototype. It reads
an Excel task list, pushes reference images to an Android device, drives the
already logged-in XHS app through image search, and pulls saved images back
from the device gallery.

Two execution modes are available:

- `mobilerun`: LLM/vision agent mode for exploration and fallback.
- `deterministic`: uiautomator2 coordinate state machine. Current smoke mode
  stops after reaching the image-search results page.

Safety boundaries:

- Manual login only.
- No credential collection.
- No captcha bypass.
- No fingerprint, proxy, or anti-bot evasion.
- Stop and record a risk event when login, captcha, or platform risk controls
  require human confirmation.

## Commands

```bash
python3 -m xhs_collector doctor --config config/xhs_collector.json

python3 -m xhs_collector validate \
  --input "../../input_image/买家秀场景图/桌垫买家秀_TOP10关键词组合.xlsx" \
  --config config/xhs_collector.json

python3 -m xhs_collector run \
  --input "../../input_image/买家秀场景图/桌垫买家秀_TOP10关键词组合.xlsx" \
  --config config/xhs_collector.json \
  --dry-run
```

Run commands from `third_party/xhs_collector`, or set `PYTHONPATH` to include
that directory.

## Deterministic Mode

Install runtime dependencies in a Python 3.11-3.13 environment:

```bash
python3 -m pip install uiautomator2 opencv-python
python3 -m uiautomator2 init
```

Prepare the phone:

- Enable USB debugging.
- Install 小红书 and finish login manually.
- Clear login, captcha, risk-control, and photo permission prompts yourself.
- Confirm `adb devices` shows the target device.

Create the starter coordinate profile:

```bash
cd third_party/xhs_collector
python3 -m xhs_collector calibrate \
  --config config/xhs_collector.json \
  --output config/xhs_coordinates.json
```

Use the interactive wizard to calibrate all tap points in order:

```bash
python3 -m xhs_collector calibrate-flow \
  --config config/xhs_collector.json \
  --output-dir calibration/flow \
  --wait-seconds 3
```

For each point, the wizard screenshots the current page, writes a grid image,
suggests a candidate, and prompts:

- Press Enter to accept the recommended candidate.
- Type `x,y` to set the target from screenshot pixels.
- Type `q` to stop.

For `search_box`, `calibrate-flow` prefers a visual hint for the XHS home-page
search entry: the top-right magnifier. On a `1200 x 2670` screenshot this
appears as `1119,200`, which is stored as `[0.9325, 0.0749]`. If a secondary UI hierarchy candidate is available, the
prompt shows it for comparison. After clicking `search_box`, the wizard verifies
that the phone reached a search page by checking UI text and input markers such
as `取消`, `搜索历史`, `搜索小红书`, or `EditText`. If verification fails, it
tries a few nearby top-right fallback points before stopping with
`verification_failed` instead of continuing with wrong screenshots. The
post-click hierarchy is written to
`calibration/flow/search_box/search_box_after_click.xml` for diagnosis.

For `image_search_button`, the wizard prefers the camera icon inside the search
box. On a `1200 x 2670` screenshot this appears as `922,212`, stored as
`[0.7683, 0.0794]`. After clicking, it verifies that an album/image picker page
opened by checking text such as `相册`, `最近项目`, `照片`, or gallery-related UI
markers. Verification evidence is written to
`calibration/flow/image_search_button/image_search_button_after_click.xml`.

For `album_entry`, the current XHS image-search camera page uses a bottom
gallery strip. The wizard prefers the bottom-right `展开` button. On a
`1200 x 2670` screenshot this appears as `1110,2261`, stored as
`[0.925, 0.8468]`. It verifies that the expanded album/grid page is visible and
writes evidence to `calibration/flow/album_entry/album_entry_after_click.xml`.

For `first_album_image`, the wizard prefers the first tile in the expanded
album grid. On a `1200 x 2670` screenshot this is `150,520`, stored as
`[0.125, 0.1948]`. After clicking it, the wizard checks for selection/confirm
markers such as `完成`, `确定`, `下一步`, or `已选择`.

For `album_confirm`, the wizard prefers the bottom-right confirmation action.
On a `1200 x 2670` screenshot this is `1056,2577`, stored as `[0.88, 0.965]`.
After clicking it, the wizard checks for result-page markers such as `图搜`,
`结果`, `相关`, `相似`, or `笔记`.

After the image-search result page is reached, deterministic mode can save the
first results through the public app UI. It waits for recognition, swipes the
bottom result panel fullscreen, opens each result card, long-presses the note
image, taps the save-image menu item, then uses ADB media diff/pull to fetch the
newly saved image. The extra calibration points are:

- `results_panel_swipe_start`, `results_panel_swipe_end`
- `result_card_1`, `result_card_2`, `result_card_3`
- `note_main_image`, `save_image_menu_item`, `note_back_button`

To calibrate only the result/download points after the phone is already on the
image-search result page:

```bash
python3 -m xhs_collector calibrate-flow \
  --config config/xhs_collector.json \
  --output-dir calibration/download_flow \
  --points results_panel_swipe_start results_panel_swipe_end result_card_1 result_card_2 result_card_3 note_main_image save_image_menu_item note_back_button \
  --wait-seconds 3 \
  --no-start-app
```

For a first download smoke, keep the run small:

```bash
python3 -m xhs_collector run \
  --input "../../input_image/买家秀场景图/桌垫买家秀_TOP10关键词组合.xlsx" \
  --config config/xhs_collector.json \
  --mode deterministic \
  --top-n 1
```

Then check the latest run for `items/<item_id>/rank_001.*`. Once stable, rerun
with `--top-n 3` and expect `rank_001.*` through `rank_003.*`.
For productized flows that need different counts per stage, use staged
overrides:

```bash
python3 -m xhs_collector run \
  --input "../../input_image/买家秀场景图/桌垫买家秀_TOP10关键词组合.xlsx" \
  --config config/xhs_collector.json \
  --mode deterministic \
  --image-top-n 10 \
  --keyword-top-n 4 \
  --keyword-result-top-n 5
```

`--top-n` remains a compatibility shortcut when image-search and keyword-search
stages should use the same target count.

If the phone is already on the XHS camera/album page and you only want to
continue from there, skip launching XHS again:

```bash
python3 -m xhs_collector calibrate-flow \
  --config config/xhs_collector.json \
  --output-dir calibration/flow \
  --points album_entry first_album_image album_confirm \
  --wait-seconds 3 \
  --no-start-app
```

The wizard writes `config/xhs_coordinates.json` after each accepted point and
clicks the point to advance to the next page. It waits 2 seconds by default
after opening XHS and after each accepted click before taking the next
screenshot; use `--wait-seconds 3` or higher if the app is still on the splash
screen or page transition animation. If a popup or ad appears, close it on the
phone, then continue with the prompt.

Candidate detection is text-based over uiautomator2 XML hierarchy:

- `search_box`: `搜索` / `search`
- `image_search_button`: `相机` / `拍照` / `图片` / `图搜` / `扫一扫` / `camera` / `image`
- `album_entry`: `相册` / `选择图片` / `从相册` / `album` / `gallery`
- `album_confirm`: `完成` / `确定` / `确认` / `下一步` / `使用` / `done` / `ok` / `confirm` / `next`
- `first_album_image` and `results_anchor`: usually rely on visual hints or manual `x,y`

You can still calibrate a single point with `calibrate-point`. Values are stored
as `[x_ratio, y_ratio]` in the range `0..1`. Recalibrate after changing device,
resolution, or major app version.

For example, to calibrate only the image-search/camera button after the phone
is already on the search page:

```bash
python3 -m xhs_collector calibrate-point \
  --config config/xhs_collector.json \
  --point image_search_button \
  --output-dir calibration/image_search_button \
  --wait-seconds 3
```

If it returns `needs_manual_point`, open
`calibration/image_search_button/image_search_button_grid.png` and rerun with
the button center in pixels:

```bash
python3 -m xhs_collector calibrate-point \
  --config config/xhs_collector.json \
  --point image_search_button \
  --output-dir calibration/image_search_button \
  --x 1090 \
  --y 135
```

`calibrate-search-box` remains available as a compatibility alias for
`calibrate-point --point search_box --start-app`.

Run a one-image smoke test first:

```bash
python3 -m xhs_collector run \
  --input "../../input_image/买家秀场景图/桌垫买家秀_TOP10关键词组合.xlsx" \
  --config config/xhs_collector.json \
  --mode deterministic \
  --top-n 1
```

This smoke run now executes the deterministic image-search and public UI save
path when download coordinates are present. Outputs are written under
`runs/xhs_collector/<run_id>/`, including `manifest.json`, `step_events.jsonl`,
`risk_events.jsonl`, screenshots, and UI hierarchy dumps.

The coordinate profile contains:

- `search_box`
- `image_search_button`
- `album_entry`
- `first_album_image`
- `album_confirm`
- `results_anchor`

Template fallback is optional. Put small PNG templates such as
`image_search_button.png`, `album_entry.png`, or `results_anchor.png` in
`templates/xhs/`. They are only used when text/selectors/coordinates fail.
