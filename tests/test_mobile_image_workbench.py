from __future__ import annotations

import base64
import csv
import json
import os
import re
import tempfile
import unittest
import zipfile
from pathlib import Path
from urllib.parse import unquote


class MobileImageWorkbenchTests(unittest.TestCase):
    def test_job_settings_defaults_match_input_modes(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.settings import (
            JobSettings,
        )

        single = JobSettings.for_mode("single_image")
        batch = JobSettings.for_mode("batch_images")
        config = JobSettings.for_mode("config_file")

        self.assertEqual(single.image_top_n, 10)
        self.assertEqual(single.keyword_top_n, 0)
        self.assertEqual(single.keyword_result_top_n, 0)
        self.assertEqual(batch.image_top_n, 10)
        self.assertEqual(batch.keyword_top_n, 0)
        self.assertEqual(batch.keyword_result_top_n, 0)
        self.assertEqual(config.image_top_n, 10)
        self.assertEqual(config.keyword_top_n, 4)
        self.assertEqual(config.keyword_result_top_n, 5)
        self.assertEqual(single.target_category, "桌垫")
        self.assertFalse(single.category_filter_enabled)
        self.assertFalse(batch.category_filter_enabled)
        self.assertFalse(config.category_filter_enabled)
        self.assertEqual(single.subject_recognition_wait_seconds, 5.0)
        self.assertEqual(config.subject_recognition_wait_seconds, 5.0)
        self.assertIn("桌垫", single.target_category_keywords)
        self.assertIn("餐桌垫", single.target_category_keywords)
        self.assertIn("餐垫", single.target_category_keywords)
        self.assertIn("桌垫桌布", single.target_category_keywords)

    def test_job_settings_accepts_target_category_overrides(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.settings import (
            JobSettings,
        )

        settings = JobSettings.from_payload(
            {
                "settings": {
                    "mode": "single_image",
                    "categoryFilterEnabled": True,
                    "targetCategory": "地毯",
                    "targetCategoryKeywords": "地毯, 客厅地毯\n绒面地垫",
                }
            }
        )

        self.assertTrue(settings.category_filter_enabled)
        self.assertEqual(settings.target_category, "地毯")
        self.assertEqual(settings.target_category_keywords, ["地毯", "客厅地毯", "绒面地垫"])

    def test_uploaded_images_become_direct_input_items(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.inputs import (
            UploadedImage,
            create_items_from_uploaded_images,
        )

        payload = base64.b64encode(b"fake-png").decode("ascii")
        with tempfile.TemporaryDirectory() as temp_dir:
            items = create_items_from_uploaded_images(
                [
                    UploadedImage(
                        filename="桌垫.png",
                        content_base64=payload,
                        keyword_candidates=["买家秀 实拍"],
                    )
                ],
                Path(temp_dir) / "job",
                image_top_n=10,
            )

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].item_id, "桌垫")
            self.assertEqual(items[0].top_n, 10)
            self.assertEqual(items[0].keyword_candidates, ["买家秀 实拍"])
            self.assertTrue(items[0].reference_image.exists())
            self.assertEqual(items[0].reference_image.read_bytes(), b"fake-png")

    def test_config_file_payload_writes_sidecar_images_next_to_workbook(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.inputs import (
            write_config_file_from_payload,
        )

        workbook_payload = base64.b64encode(b"xlsx").decode("ascii")
        image_payload = base64.b64encode(b"image").decode("ascii")
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook = write_config_file_from_payload(
                {
                    "configFile": {
                        "filename": "items.xlsx",
                        "contentBase64": workbook_payload,
                    },
                    "configImages": [
                        {
                            "filename": "ref.png",
                            "contentBase64": image_payload,
                        }
                    ],
                },
                Path(temp_dir) / "job",
            )

            self.assertEqual(workbook.name, "items.xlsx")
            self.assertEqual((workbook.parent / "ref.png").read_bytes(), b"image")

    def test_project_folder_payload_auto_detects_workbook_and_sidecar_images(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.inputs import (
            write_config_file_from_payload,
        )

        workbook_payload = base64.b64encode(b"xlsx").decode("ascii")
        image_payload = base64.b64encode(b"image").decode("ascii")
        temp_workbook_payload = base64.b64encode(b"temp").decode("ascii")
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook = write_config_file_from_payload(
                {
                    "projectFiles": [
                        {
                            "filename": ".~桌垫买家秀_TOP10关键词组合.xlsx",
                            "relativePath": "买家秀场景图/.~桌垫买家秀_TOP10关键词组合.xlsx",
                            "contentBase64": temp_workbook_payload,
                        },
                        {
                            "filename": "桌垫买家秀_TOP10关键词组合.xlsx",
                            "relativePath": "买家秀场景图/桌垫买家秀_TOP10关键词组合.xlsx",
                            "contentBase64": workbook_payload,
                        },
                        {
                            "filename": "1d3c.png",
                            "relativePath": "买家秀场景图/1d3c.png",
                            "contentBase64": image_payload,
                        },
                    ]
                },
                Path(temp_dir) / "job",
            )

            self.assertEqual(workbook.name, "桌垫买家秀_TOP10关键词组合.xlsx")
            self.assertEqual(workbook.parent.name, "买家秀场景图")
            self.assertEqual((workbook.parent / "1d3c.png").read_bytes(), b"image")
            self.assertFalse((workbook.parent / ".~桌垫买家秀_TOP10关键词组合.xlsx").exists())

    def test_config_file_payload_uses_stage_specific_defaults(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.collector_bridge import (
            build_collector_config_payload,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.settings import (
            JobSettings,
        )

        payload = build_collector_config_payload(
            JobSettings.for_mode("config_file"),
            output_root=Path("/tmp/workbench-runs"),
        )

        self.assertEqual(payload["mode"], "deterministic")
        self.assertEqual(payload["top_n"], 10)
        self.assertEqual(payload["image_top_n"], 10)
        self.assertEqual(payload["keyword_top_n"], 4)
        self.assertEqual(payload["keyword_result_top_n"], 5)
        self.assertEqual(payload["target_category"], "桌垫")
        self.assertEqual(payload["target_category_keywords"], [])
        self.assertEqual(payload["output_root"], "/tmp/workbench-runs")
        self.assertEqual(
            payload["deterministic"]["subject_recognition_wait_seconds"], 5.0
        )

    def test_subject_recognition_wait_setting_is_validated_and_forwarded(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.collector_bridge import (
            build_collector_config_payload,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.settings import (
            JobSettings,
        )

        settings = JobSettings.from_payload(
            {
                "settings": {
                    "mode": "single_image",
                    "subjectRecognitionWaitSeconds": 7.5,
                }
            }
        )
        payload = build_collector_config_payload(
            settings, output_root=Path("/tmp/workbench-runs")
        )

        self.assertEqual(settings.subject_recognition_wait_seconds, 7.5)
        self.assertEqual(
            payload["deterministic"]["subject_recognition_wait_seconds"], 7.5
        )
        with self.assertRaisesRegex(
            ValueError, "subject_recognition_wait_seconds must be >= 0"
        ):
            JobSettings.from_payload(
                {
                    "settings": {
                        "mode": "single_image",
                        "subjectRecognitionWaitSeconds": -0.1,
                    }
                }
            )

    def test_category_filter_toggle_controls_collector_keywords(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.collector_bridge import (
            build_collector_config_payload,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.settings import (
            JobSettings,
        )

        enabled = JobSettings.from_payload(
            {
                "settings": {
                    "mode": "single_image",
                    "categoryFilterEnabled": True,
                    "targetCategoryKeywords": "桌垫, 餐桌垫",
                }
            }
        )
        disabled = JobSettings.from_payload(
            {
                "settings": {
                    "mode": "single_image",
                    "categoryFilterEnabled": False,
                    "targetCategoryKeywords": "桌垫, 餐桌垫",
                }
            }
        )

        enabled_payload = build_collector_config_payload(
            enabled, output_root=Path("/tmp/workbench-runs")
        )
        disabled_payload = build_collector_config_payload(
            disabled, output_root=Path("/tmp/workbench-runs")
        )

        self.assertEqual(enabled_payload["target_category_keywords"], ["桌垫", "餐桌垫"])
        self.assertEqual(disabled_payload["target_category_keywords"], [])

    def test_workbench_default_config_resolves_xhs_collector_paths(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.collector_bridge import (
            write_collector_config,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.settings import (
            JobSettings,
        )

        base_config = Path("third_party/mobile_image_workbench/config/defaults.json")
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = write_collector_config(
                JobSettings.for_mode("single_image"),
                output_root=Path(temp_dir) / "runs",
                target_path=Path(temp_dir) / "collector_config.json",
                base_config_path=base_config,
            )

            payload = json.loads(config_path.read_text(encoding="utf-8"))
            deterministic = payload["deterministic"]
            self.assertTrue(Path(deterministic["coordinate_profile"]).exists())
            self.assertTrue(Path(deterministic["template_dir"]).exists())

    def test_event_translation_uses_business_friendly_language(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.events import (
            translate_event,
        )

        self.assertEqual(
            translate_event({"name": "push_reference"})["message"],
            "正在把参考图发送到手机相册",
        )
        self.assertEqual(
            translate_event(
                {
                    "name": "download_keyword_search_rank_3",
                    "query": "白底红格桌垫",
                    "rank": 3,
                }
            )["message"],
            "已保存关键词「白底红格桌垫」结果第 3 张",
        )
        risk = translate_event({"event": "captcha_required"})
        self.assertEqual(risk["level"], "needs_attention")
        self.assertIn("验证码", risk["message"])
        album = translate_event({"name": "album_thumbnail_not_found"})
        self.assertEqual(album["level"], "warning")
        self.assertIn("缩略图", album["message"])
        self.assertIn(
            "图搜笔记列表",
            translate_event({"name": "wait_image_search_result_list_stable"})[
                "message"
            ],
        )
        self.assertEqual(
            translate_event({"name": "open_image_search_result_card_rank_1"})[
                "message"
            ],
            "正在打开图搜结果第 1 条笔记",
        )
        self.assertEqual(
            translate_event({"name": "long_press_note_main_image"})["message"],
            "正在长按笔记图片准备保存",
        )
        self.assertEqual(
            translate_event({"name": "tap_save_image_menu_item"})["message"],
            "正在点击保存到相册",
        )
        self.assertEqual(
            translate_event({"name": "pull_saved_image_rank_1"})["message"],
            "正在把手机保存的第 1 张图片同步到本地",
        )
        subject = translate_event(
            {
                "source": "collector",
                "name": "wait_subject_recognition",
                "step": 9,
                "item_id": "sku",
            }
        )
        self.assertEqual(subject["message"], "等待小红书完成主体识别")
        self.assertEqual(subject["source"], "collector")
        self.assertIn("collector|wait_subject_recognition|9|sku", subject["eventKey"])
        unknown = translate_event({"name": "raw_engineering_step_name"})
        self.assertNotEqual(unknown["message"], "raw_engineering_step_name")
        self.assertNotIn("_", unknown["message"])

    def test_workbench_timeline_smart_auto_follows_latest_events(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_vue = (
            root / "third_party/mobile_image_workbench/frontend/src/App.vue"
        ).read_text(encoding="utf-8")
        styles = (
            root / "third_party/mobile_image_workbench/frontend/src/styles.css"
        ).read_text(encoding="utf-8")

        self.assertIn("nextTick", app_vue)
        self.assertIn('ref="timelineRef"', app_vue)
        self.assertIn('@scroll="handleTimelineScroll"', app_vue)
        self.assertIn("autoFollowTimeline", app_vue)
        self.assertIn("hasUnreadTimelineEvents", app_vue)
        self.assertIn("scrollTimelineToLatestIfNeeded", app_vue)
        self.assertIn("scrollTimelineToLatest", app_vue)
        self.assertIn("有新进展，查看最新", app_vue)
        self.assertIn(".timeline-jump-button", styles)

    def test_frontend_exposes_category_filter_toggle_default_off(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_vue = (
            root / "third_party/mobile_image_workbench/frontend/src/App.vue"
        ).read_text(encoding="utf-8")

        self.assertIn("categoryFilterEnabled: false", app_vue)
        self.assertIn("启用品类过滤", app_vue)
        self.assertIn("categoryFilterEnabled: settings.categoryFilterEnabled", app_vue)

    def test_frontend_exposes_subject_recognition_wait_setting(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_vue = (
            root / "third_party/mobile_image_workbench/frontend/src/App.vue"
        ).read_text(encoding="utf-8")

        self.assertIn("subjectRecognitionWaitSeconds: 5", app_vue)
        self.assertIn("主体识别等待秒数", app_vue)
        self.assertIn(
            "subjectRecognitionWaitSeconds: settings.subjectRecognitionWaitSeconds",
            app_vue,
        )

    def test_translated_events_order_prepare_collector_then_finish(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.jobs import (
            JobManager,
        )

        image_payload = base64.b64encode(b"image").decode("ascii")
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = JobManager(Path(temp_dir))
            record = manager.create_job(
                {
                    "mode": "single_image",
                    "settings": {"mode": "single_image"},
                    "images": [
                        {
                            "filename": "ref.png",
                            "contentBase64": image_payload,
                        }
                    ],
                },
                start=False,
            )
            (record.job_dir / "job_events.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"name": "job_started"}),
                        json.dumps({"name": "collector_completed"}),
                        json.dumps({"name": "result_exports_ready"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            collector_run = record.job_dir / "collector_runs" / "run-1"
            collector_run.mkdir(parents=True)
            (collector_run / "step_events.jsonl").write_text(
                json.dumps(
                    {"name": "tap_search_box", "step": 1, "item_id": "sku"}
                )
                + "\n",
                encoding="utf-8",
            )

            events = manager.translated_events(record.job_id)

            self.assertEqual(
                [event["name"] for event in events],
                [
                    "job_started",
                    "tap_search_box",
                    "collector_completed",
                    "result_exports_ready",
                ],
            )
            self.assertEqual([event["source"] for event in events], ["job", "collector", "job", "job"])

    def test_sse_stream_uses_stable_event_keys_instead_of_list_indexes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        server_py = (
            root / "third_party/mobile_image_workbench/backend/mobile_image_workbench/server.py"
        ).read_text(encoding="utf-8")

        self.assertIn("sent_event_keys", server_py)
        self.assertNotIn("events[sent:]", server_py)

    def test_running_job_streams_events_from_active_collector_run(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.jobs import (
            JobManager,
        )

        image_payload = base64.b64encode(b"image").decode("ascii")
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = JobManager(Path(temp_dir))
            record = manager.create_job(
                {
                    "mode": "single_image",
                    "settings": {"mode": "single_image"},
                    "images": [
                        {
                            "filename": "ref.png",
                            "contentBase64": image_payload,
                        }
                    ],
                },
                start=False,
            )
            job_payload = json.loads(
                (record.job_dir / "job.json").read_text(encoding="utf-8")
            )
            job_payload["status"] = "running"
            (record.job_dir / "job.json").write_text(
                json.dumps(job_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            collector_run = record.job_dir / "collector_runs" / "run-1"
            collector_run.mkdir(parents=True)
            (collector_run / "step_events.jsonl").write_text(
                json.dumps({"name": "tap_search_box", "item_id": "sku"})
                + "\n",
                encoding="utf-8",
            )

            events = manager.translated_events(record.job_id)

            self.assertEqual(events[0]["name"], "tap_search_box")
            self.assertEqual(events[0]["message"], "正在进入搜索")

    def test_dry_run_job_exposes_progress_events_without_step_log(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.jobs import (
            JobManager,
        )

        image_payload = base64.b64encode(b"image").decode("ascii")
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = JobManager(Path(temp_dir))
            record = manager.create_job(
                {
                    "mode": "single_image",
                    "settings": {
                        "mode": "single_image",
                        "dryRun": True,
                        "imageTopN": 1,
                        "keywordTopN": 0,
                        "keywordResultTopN": 0,
                    },
                    "images": [
                        {
                            "filename": "ref.png",
                            "contentBase64": image_payload,
                        }
                    ],
                },
                start=False,
            )

            manager.run_job(record.job_id)
            events = manager.translated_events(record.job_id)
            messages = [event["message"] for event in events]

            self.assertIn("采集任务已启动，正在准备输入文件", messages)
            self.assertIn("正在启动手机采集引擎", messages)
            self.assertIn("采集已完成，正在生成下载结果", messages)

    def test_collector_events_jsonl_is_translated_for_workbench_timeline(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.events import (
            read_translated_events,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "events.jsonl").write_text(
                json.dumps(
                    {
                        "event": "item.started",
                        "item_id": "sku",
                        "keyword": "桌垫",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            events = read_translated_events(run_dir)

            self.assertEqual(events[0]["name"], "item.started")
            self.assertEqual(events[0]["message"], "开始处理原图：桌垫")

    def test_frontend_polls_event_snapshot_when_sse_is_unavailable(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_vue = (
            root / "third_party/mobile_image_workbench/frontend/src/App.vue"
        ).read_text(encoding="utf-8")

        self.assertIn("seenEventKeys", app_vue)
        self.assertIn("appendBusinessEvent", app_vue)
        self.assertIn("refreshEvents", app_vue)
        self.assertIn("/events.json", app_vue)
        self.assertIn("await refreshEvents(id)", app_vue)

    def test_result_exports_include_original_and_collected_images(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.exports import (
            write_result_exports,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run"
            item_id = "桌垫 sku"
            input_dir = run_dir / "inputs" / item_id
            item_dir = run_dir / "items" / item_id
            input_dir.mkdir(parents=True)
            item_dir.mkdir(parents=True)
            (input_dir / "reference.jpg").write_bytes(b"ref")
            (item_dir / "rank_001 桌垫.jpg").write_bytes(b"rank")
            (item_dir / "keyword_001_rank_001.jpg").write_bytes(b"keyword")
            (run_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "run",
                        "status": "partial",
                        "results": [
                            {
                                "item_id": item_id,
                                "keyword": "桌垫",
                                "status": "partial",
                                "images": [
                                    {
                                        "rank": 1,
                                        "local_path": str(item_dir / "rank_001 桌垫.jpg"),
                                        "stage": "image_search",
                                        "query": "",
                                    },
                                    {
                                        "rank": 1,
                                        "local_path": str(
                                            item_dir / "keyword_001_rank_001.jpg"
                                        ),
                                        "stage": "keyword_search",
                                        "query": "白底红格桌垫",
                                        "keyword_index": 1,
                                    },
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            outputs = write_result_exports(run_dir)

            html = outputs.html_path.read_text(encoding="utf-8")
            self.assertIn("原始图片", html)
            self.assertIn("采集图片列表", html)
            self.assertIn("keyword_001_rank_001.jpg", html)
            self.assertIn(
                'src="assets/inputs/%E6%A1%8C%E5%9E%AB%20sku/reference.jpg"',
                html,
            )
            self.assertIn(
                'src="assets/items/%E6%A1%8C%E5%9E%AB%20sku/rank_001%20%E6%A1%8C%E5%9E%AB.jpg"',
                html,
            )
            self.assertIn('class="preview-trigger"', html)
            self.assertIn('data-preview-src="assets/inputs/%E6%A1%8C%E5%9E%AB%20sku/reference.jpg"', html)
            self.assertIn('data-preview-title="原始图片 · 桌垫 sku"', html)
            self.assertIn('data-preview-src="assets/items/%E6%A1%8C%E5%9E%AB%20sku/rank_001%20%E6%A1%8C%E5%9E%AB.jpg"', html)
            self.assertIn('download="reference.jpg"', html)
            self.assertIn('download="rank_001 桌垫.jpg"', html)
            self.assertIn('download="keyword_001_rank_001.jpg"', html)
            self.assertIn('id="image-preview-modal"', html)
            self.assertIn("addEventListener('keydown'", html)
            self.assertIn("event.key === 'Escape'", html)
            self.assertNotIn('src="inputs/', html)
            self.assertNotIn('src="items/', html)

            with outputs.csv_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["original_image"], f"inputs/{item_id}/reference.jpg")
            self.assertIn(
                f"items/{item_id}/rank_001 桌垫.jpg",
                rows[0]["collected_images"],
            )
            with zipfile.ZipFile(outputs.zip_path) as archive:
                names = set(archive.namelist())
            self.assertIn(f"inputs/{item_id}/reference.jpg", names)
            self.assertIn(f"items/{item_id}/rank_001 桌垫.jpg", names)

    def test_result_html_asset_urls_match_job_assets_route(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.exports import (
            write_result_exports,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.server import (
            WorkbenchRequestHandler,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "collector_runs" / "run-1"
            input_dir = run_dir / "inputs" / "sku"
            item_dir = run_dir / "items" / "sku"
            input_dir.mkdir(parents=True)
            item_dir.mkdir(parents=True)
            (input_dir / "reference.jpg").write_bytes(b"ref")
            (item_dir / "rank_001.jpg").write_bytes(b"rank")
            (run_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-1",
                        "status": "completed",
                        "results": [
                            {
                                "item_id": "sku",
                                "keyword": "桌垫",
                                "status": "completed",
                                "images": [
                                    {
                                        "rank": 1,
                                        "local_path": str(item_dir / "rank_001.jpg"),
                                        "stage": "image_search",
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            write_result_exports(run_dir)
            html_payload = (run_dir / "results.html").read_text(encoding="utf-8")
            match = re.search(r'src="assets/(items/[^"]+)"', html_payload)
            self.assertIsNotNone(match)
            asset_path = Path(unquote(match.group(1)))
            sent_files: list[tuple[Path, str]] = []
            json_errors: list[dict] = []
            handler = WorkbenchRequestHandler.__new__(WorkbenchRequestHandler)
            handler._send_file = lambda path, content_type: sent_files.append(
                (path, content_type)
            )
            handler._send_json = lambda payload, status=None: json_errors.append(payload)

            handler._send_asset(run_dir, asset_path)
            handler._send_asset(run_dir, Path("..") / "outside.jpg")

            self.assertEqual(sent_files[0][0], (item_dir / "rank_001.jpg").resolve())
            self.assertEqual(sent_files[0][1], "image/jpeg")
            self.assertEqual(json_errors[0]["error"], "invalid asset path")

    def test_result_export_with_relative_run_dir_keeps_asset_paths_relative(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.exports import (
            write_result_exports,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "runs" / "run-1"
            input_dir = run_dir / "inputs" / "sku"
            item_dir = run_dir / "items" / "sku"
            input_dir.mkdir(parents=True)
            item_dir.mkdir(parents=True)
            (input_dir / "reference.jpg").write_bytes(b"ref")
            (item_dir / "rank_001.jpg").write_bytes(b"rank")
            (run_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-1",
                        "status": "completed",
                        "results": [
                            {
                                "item_id": "sku",
                                "keyword": "桌垫",
                                "status": "completed",
                                "images": [
                                    {
                                        "rank": 1,
                                        "local_path": str(item_dir),
                                        "stage": "image_search",
                                    }
                                ],
                            }
                        ],
                    }
                ).replace(str(item_dir), str(item_dir / "rank_001.jpg")),
                encoding="utf-8",
            )
            old_cwd = Path.cwd()
            try:
                os.chdir(root)
                outputs = write_result_exports(Path("runs") / "run-1")
            finally:
                os.chdir(old_cwd)

            html_payload = (root / outputs.html_path).read_text(encoding="utf-8")
            self.assertIn('src="assets/inputs/sku/reference.jpg"', html_payload)
            self.assertIn('src="assets/items/sku/rank_001.jpg"', html_payload)
            self.assertNotIn("assets//", html_payload)
            self.assertNotIn(str(root), html_payload)


if __name__ == "__main__":
    unittest.main()
