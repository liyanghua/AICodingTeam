# Taobao Keyword Search Collection Spec

This spec is the operating contract for Taobao keyword-search mobile collection.
It is meant to become a reusable skill later. Keep it strict: every click must
be followed by a page-state gate, and every failure must leave enough evidence
to explain what happened.

## Safety Boundary

- Use public Taobao mobile UI only.
- Manual login only.
- Do not collect credentials, bypass captcha, bypass risk controls, use private
  APIs, add to cart, place orders, or touch payment flows.
- Stop immediately on login, captcha, security verification, cart, order, or
  payment pages.
- "Human-compatible" interaction means conservative public-UI gestures, readiness
  checks, and low retry counts. It must not mean stealth, fingerprint spoofing,
  captcha handling, or any attempt to avoid platform risk controls.

## Required Flow

1. Ensure Taobao is foreground.
   - If current package is not `com.taobao.taobao`, start Taobao.
   - Wait for a strict home state, not just the word `搜索`.
   - If already inside Taobao but not home, press back once, then restart app if
     home still is not detected.
   - Record `taobao_home_ready` only after the hierarchy matches a valid home
     state.
   - Valid home signals include `search_bar_container`, `content-desc="搜索栏"`,
     or bottom tab `content-desc="首页"` with `selected="true"`.

2. Open the keyword search page.
   - Prefer clicking the visible home search bar through accessibility selector
     `content-desc="搜索栏"` when available.
   - If selector click does not reach the input page, retry the center of the
     detected `content-desc="搜索栏"` bounds and record
     `point_source=detected_home_search_bar`.
   - If the detected point still does not reach the input page, retry calibrated
     `home_search_box`, then ADB tap fallbacks when supported.
   - After every attempt, gate on keyword-input-page state. If the page is still
     home, record `taobao_home_search_box_click_not_on_input_page` and try the
     next candidate.
   - Gate on keyword-input-page state before input. The generic word `搜索` is
     not sufficient because Taobao home also contains it.
   - Do not use the orange home `搜索` button as a fallback because it may submit
     a stale query already shown on the home search bar.
   - Do not type if the search page was not reached.
   - Failure event: `taobao_search_page_not_reached`.

3. Enter keyword with robust input.
   - Try uiautomator2 `send_keys(text, clear=True)`.
   - If it fails with `ADB_KEYBOARD_CLEAR_TEXT`, `clearText`, `ExtractedText`, or
     a null-object keyboard error, fall back to ADBKeyboard broadcast input.
   - Fallback sequence should clear current text first, then:
     - for Chinese/non-ASCII keywords, use `ADB_INPUT_B64`;
     - for ASCII keywords, use escaped `adb shell input text`.
   - Do not use raw `adb shell input text '红白格桌垫'`; Android input text is not
     reliable for Chinese keywords.
   - Failure event: `taobao_keyword_text_input_failed`.

4. Submit keyword.
   - Prefer explicit search/submit UI target when available.
   - Fallback to enter key only after text input has succeeded.
   - Record `taobao_submit_keyword_search`.

5. Verify result page.
   - Do not rely on one generic word such as `商品` or `搜索`.
   - Treat Taobao result page as a combined-marker state.
   - Strong markers include: `综合`, `销量`, `店铺`, `宝贝`.
   - Real-list fallback markers include combinations of: `全部`, `品牌`,
     `官方自营`, `已售`, `人加购`, `¥`, `国补专区`, `旗舰店`, `店`.
   - If result page is not recognized, classify the current hierarchy as:
     `home_like`, `recommendation_like`, `result_like_unrecognized`, or
     `unknown`.
   - Failure event: `taobao_keyword_search_results_not_reached`.

6. Collect result and detail screenshots.
   - Capture the result-list screenshot before tapping a card.
   - Tap `result_card_<rank>` or fallback `result_card`.
   - Gate on detail markers before capturing detail.
   - Detail page markers may include `宝贝详情`, `评价`, `店铺`, `加入购物车`,
     `立即购买`; these are allowed as detail markers, but payment/order/cart
     pages are still risk states.
   - Before saving the detail main image, inspect the current hero media, not
     arbitrary text elsewhere on the page.
   - Prefer structured UI hierarchy signals:
     - `图集` / `图片` tab with `selected="true"` means the current hero media is
       an image, even if an unselected `视频` tab is still visible.
     - `视频` tab with `selected="true"` or visible hero-player controls means
       the current hero media is video.
     - `content-desc="商品图片"` or hero image node
       `com.taobao.taobao:id/iv_image_content` means image.
   - Only use broad text markers such as `视频`, `播放`, `暂停`, `00:xx`, or player
     controls as fallback when structured hero-media signals are unavailable.
   - If the current hero media is video, record
     `taobao_detail_media_video_detected`, swipe the hero carousel to the next
     media, and retry.
   - Scan at most 5 hero media entries. If none is a non-video image, record
     `taobao_detail_non_video_image_not_found`, keep the result-card image, and
     do not save the video frame as a detail asset.
   - After a non-video image is selected, use the Detail Image Save Interaction
     Contract below. In short: wait for the hero image to be stable, tap the
     visible hero image once to activate the image/gallery area, then long press
     the same visible image. Do not immediately long-press after page transition.
   - Use media-store diff to pull the newly saved image from the phone into
     `images/`; the final detail asset must be this pulled image, not a
     screenshot.
   - Press detail back and gate on result page before the next rank.

## Detail Image Save Interaction Contract

This contract exists because a human can manually tap/long-press the first
non-video image and save it, while a too-fast or poorly targeted automation
gesture may trigger login or another risk page. The goal is to make the program
act like a careful public-UI user, not to bypass login or risk controls.

1. Stable hero-image gate.
   - After `taobao_detail_non_video_image_selected`, wait until the detail page
     hierarchy is stable before touching the image.
   - Stability means the current hierarchy still classifies as `detail`, has no
     risk markers, and the hero media still classifies as non-video image after
     a short re-check.
   - Record `taobao_detail_image_stable_before_save`.

2. Target the visible hero image, not a blind coordinate.
   - Prefer the UI hierarchy bounds of `content-desc="商品图片"` or
     `com.taobao.taobao:id/iv_image_content`.
   - If hierarchy bounds are unavailable, fall back to calibrated
     `detail_main_image`.
   - The tap/long-press point must be inside the hero image area and outside
     bottom action regions such as `加入购物车` / `立即购买`.

3. Activation tap.
   - Tap the selected non-video hero image once.
   - Record `taobao_tap_detail_main_image` with `point_source`.
   - Wait for the page to settle after the tap.
   - If the tap opens a full-screen image/gallery preview, continue there only
     after preview/image markers are visible and no risk markers appear.
   - If login/captcha/security appears after the tap, stop the current rank with
     `taobao_detail_save_login_triggered`; do not retry or attempt to close it.

4. Long press after activation.
   - Long press the same hero image or preview image point after the activation
     wait.
   - Record `taobao_long_press_detail_main_image`.
   - Wait for a save menu marker. Valid markers are `保存图片` or `保存到相册`.
   - If login/captcha/security appears after long press, stop the current rank
     with `taobao_detail_save_login_triggered`; do not retry.

5. Save menu click.
   - Prefer detected save-menu bounds from UI hierarchy.
   - Fall back to calibrated `save_image_button` only if the save menu is visible
     but no clickable bounds can be parsed.
   - Record `taobao_tap_save_image_button`.

6. Retry limit.
   - At most one save retry is allowed, and only when no login/risk marker is
     present and no new media appears after a visible save-menu click.
   - The retry must repeat the same stable gate -> activation tap -> long press
     sequence.
   - Never spam long-press gestures.

7. Manual handoff.
   - If a logged-in human can save but automation triggers login, keep the
     result-card asset, write debug screenshot/XML, mark the detail asset as
     failed for this rank, and surface a manual handoff reason.
   - The collector must not try to log in, dismiss login, solve verification, or
     continue touching the save flow after a login/risk marker appears.

## Page-State Gates

Every gate must record the markers it expected and the markers it observed when
it fails. This avoids vague failures such as "cannot find search button" when
the actual failure is text input or result-page recognition.

Recommended page classifiers:

- `home`: Taobao home/search entry is visible; home must not be inferred from a
  single `搜索` string.
- `keyword_input`: keyword input page is visible. It must include stronger input
  signals such as `取消 + 输入商品`, a focused editable input, or equivalent
  search-entry markers.
- `recommendation`: suggestion/history page after search box click.
- `result_list`: keyword result list with product cards.
- `detail`: product detail page.
- `risk`: login/captcha/security/payment/order/cart state.
- `unknown`: none of the above.

## Event Contract

Minimum successful keyword event sequence:

```text
taobao_start_app                      optional
taobao_home_ready
taobao_tap_home_search_box
taobao_search_page_reached
taobao_set_keyword_search_text
taobao_submit_keyword_search
taobao_keyword_search_results_reached
taobao_tap_result_card
taobao_detail_non_video_image_selected
taobao_detail_image_stable_before_save
taobao_tap_detail_main_image
taobao_long_press_detail_main_image
taobao_tap_save_image_button
taobao_pull_saved_detail_image
```

Failure events:

```text
taobao_home_not_ready
taobao_search_page_not_reached
taobao_keyword_text_input_failed
taobao_keyword_search_stuck_on_recommendations
taobao_keyword_search_results_not_reached
taobao_result_list_not_ready
taobao_detail_page_not_reached
taobao_detail_non_video_image_not_found
taobao_detail_save_login_triggered
taobao_detail_save_menu_not_found
taobao_detail_save_no_new_media
taobao_risk_prompt_detected
```

Each failure must write:

- `risk_events.jsonl`
- `step_events.jsonl`
- `debug/<event>.png`
- `debug/<event>.xml`

## Output Contract

Each run writes:

```text
manifest.json
step_events.jsonl
risk_events.jsonl
results.csv
results.html
images/
debug/
```

`manifest.json` and `results.csv` assets must include:

- `channel=taobao`
- `mode=keyword_search`
- `query`
- `stage=keyword_search|detail`
- `rank`
- `source_item_id`
- `content_sha256`
- `local_path`

## Regression Cases

Tests must cover:

- A real Taobao result-list XML with `全部/品牌/官方自营/已售/旗舰店`
  is recognized as a result page.
- Taobao home/recommendation pages are not misclassified as result pages.
- Taobao home XML with `content-desc="搜索栏"` is not classified as keyword input.
- Keyword search uses detected home search-bar bounds before the calibrated
  fallback coordinate.
- If tapping the home search bar does not open a keyword input page, the flow
  fails before text input.
- uiautomator2 `ADB_KEYBOARD_CLEAR_TEXT` failure falls back to `ADB_INPUT_B64`
  for Chinese keywords.
- Fallback input failure writes `taobao_keyword_text_input_failed`.
- Search submit reaching recommendation/history page does not continue to card
  collection.
- Result-page recognition failure stores XML/screenshot and observed markers.
- Detail page first hero media is a video: flow swipes to the next hero media
  before long-pressing.
- Detail page non-video image save first waits for a stable hero image, taps the
  visible hero image once, then long-presses the same image point.
- If activation tap or long press triggers login/security verification, the flow
  records `taobao_detail_save_login_triggered`, keeps existing result-card
  output, and stops the detail-save attempt without retrying.
- Detail page all scanned hero media entries are videos: flow does not save a
  detail asset and records `taobao_detail_non_video_image_not_found`.
- Save menu is missing: flow records `taobao_detail_save_menu_not_found`.
- Save produces no new media after one retry: flow records
  `taobao_detail_save_no_new_media`.
- Successful keyword run writes `keyword_search` and `detail` assets.

## Manual Acceptance

Run:

```bash
cd third_party/taobao_collector
../xhs_collector/.venv/bin/python -m taobao_collector run \
  --mode keyword_search \
  --keyword "红白格桌垫" \
  --top-n 1
```

Accept when:

- CLI returns `status=completed`.
- CLI returns `asset_count=2`.
- CLI returns `risk_event_count=0`.
- `results.html` shows one result-list image and one detail image.
- `step_events.jsonl` contains the minimum successful event sequence.

If it fails, inspect in order:

```bash
cat <output_dir>/risk_events.jsonl
cat <output_dir>/step_events.jsonl
sed -n '1,240p' <output_dir>/debug/<event>.xml
```

Do not change coordinates until events prove the click target failed. If
`taobao_tap_home_search_box` has `point_source=detected_home_search_bar`, the
flow used the hierarchy-detected search bar center instead of the profile
coordinate. If `taobao_search_page_not_reached` appears, inspect the debug XML
and screenshot before recalibrating.
