from __future__ import annotations

import base64
import contextlib
import csv
import io
from http import HTTPStatus
import json
import os
import re
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock
from urllib.parse import unquote


def _restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


class MobileImageWorkbenchTests(unittest.TestCase):
    def test_filesystem_object_storage_round_trips_private_assets(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.storage import (
            FilesystemObjectStorageClient,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            storage = FilesystemObjectStorageClient(Path(temp_dir) / "objects", bucket="dev-assets")
            source = Path(temp_dir) / "source.jpg"
            source.write_bytes(b"image-bytes")

            storage.put_object("collected/2026/05/a.jpg", source, content_type="image/jpeg")
            meta = storage.head_object("collected/2026/05/a.jpg")
            copied = storage.copy_object("collected/2026/05/a.jpg", "thumb/2026/05/a_512.webp")

            self.assertEqual(meta.key, "collected/2026/05/a.jpg")
            self.assertEqual(meta.size_bytes, len(b"image-bytes"))
            self.assertEqual(meta.content_type, "image/jpeg")
            self.assertTrue(copied.exists)
            self.assertEqual(
                storage.read_object("thumb/2026/05/a_512.webp"),
                b"image-bytes",
            )
            self.assertEqual(
                storage.presign_get_url("collected/2026/05/a.jpg"),
                "/api/library/objects/dev-assets/collected/2026/05/a.jpg",
            )

    def test_asset_library_ingests_run_and_searches_business_metadata(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.asset_library import (
            AssetLibrary,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.storage import (
            FilesystemObjectStorageClient,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "run"
            input_dir = run_dir / "inputs" / "sku-1"
            item_dir = run_dir / "items" / "sku-1"
            input_dir.mkdir(parents=True)
            item_dir.mkdir(parents=True)
            (input_dir / "reference.jpg").write_bytes(b"reference")
            (item_dir / "rank_001.jpg").write_bytes(b"first-collected")
            (item_dir / "keyword_001_rank_001.jpg").write_bytes(b"keyword-collected")
            (run_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-1",
                        "status": "completed",
                        "config": {"target_category": "桌垫"},
                        "results": [
                            {
                                "item_id": "sku-1",
                                "keyword": "餐桌买家秀",
                                "status": "completed",
                                "images": [
                                    {
                                        "rank": 1,
                                        "local_path": str(item_dir / "rank_001.jpg"),
                                        "stage": "image_search",
                                        "query": "",
                                    },
                                    {
                                        "rank": 1,
                                        "local_path": str(item_dir / "keyword_001_rank_001.jpg"),
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
            storage = FilesystemObjectStorageClient(root / "objects", bucket="dev-assets")
            library = AssetLibrary(root / "asset_center.sqlite3", storage)

            summary = library.ingest_run(
                run_dir,
                job_id="job-1",
                category="桌垫",
                scene="餐桌布置",
            )
            matches = library.search_assets(
                category="桌垫",
                scene="餐桌布置",
                query="红格",
                stage="keyword_search",
            )

            self.assertEqual(summary["source_images"], 1)
            self.assertEqual(summary["assets"], 2)
            self.assertEqual(summary["duplicates"], 0)
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["query"], "白底红格桌垫")
            self.assertEqual(matches[0]["category"], "桌垫")
            self.assertEqual(matches[0]["scene"], "餐桌布置")
            self.assertEqual(matches[0]["status"], "available")
            self.assertIn("/api/library/assets/", matches[0]["imageUrl"])
            self.assertIn("/download", matches[0]["downloadUrl"])
            self.assertTrue((root / "objects" / "dev-assets" / matches[0]["objectKey"]).exists())

    def test_asset_library_marks_duplicate_media_without_consuming_search_results(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.asset_library import (
            AssetLibrary,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.storage import (
            FilesystemObjectStorageClient,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = FilesystemObjectStorageClient(root / "objects", bucket="dev-assets")
            library = AssetLibrary(root / "asset_center.sqlite3", storage)

            def make_run(run_name: str) -> Path:
                run_dir = root / run_name
                input_dir = run_dir / "inputs" / "sku"
                item_dir = run_dir / "items" / "sku"
                input_dir.mkdir(parents=True)
                item_dir.mkdir(parents=True)
                (input_dir / "reference.jpg").write_bytes(f"ref-{run_name}".encode())
                (item_dir / "rank_001.jpg").write_bytes(b"same-collected-image")
                (run_dir / "manifest.json").write_text(
                    json.dumps(
                        {
                            "run_id": run_name,
                            "status": "completed",
                            "results": [
                                {
                                    "item_id": "sku",
                                    "keyword": "",
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
                return run_dir

            library.ingest_run(make_run("run-a"), job_id="job-a", category="桌垫", scene="餐桌")
            summary = library.ingest_run(make_run("run-b"), job_id="job-b", category="桌垫", scene="餐桌")

            available = library.search_assets(status="available")
            duplicates = library.search_assets(status="duplicate")

            self.assertEqual(summary["duplicates"], 1)
            self.assertEqual(len(available), 1)
            self.assertEqual(len(duplicates), 1)
            self.assertEqual(duplicates[0]["status"], "duplicate")
            self.assertEqual(duplicates[0]["duplicateOfAssetId"], available[0]["assetId"])

    def test_asset_library_allows_same_hash_across_different_categories(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.asset_library import (
            AssetLibrary,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.storage import (
            FilesystemObjectStorageClient,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = FilesystemObjectStorageClient(root / "objects", bucket="dev-assets")
            library = AssetLibrary(root / "asset_center.sqlite3", storage)

            def make_run(run_name: str) -> Path:
                run_dir = root / run_name
                input_dir = run_dir / "inputs" / "sku"
                item_dir = run_dir / "items" / "sku"
                input_dir.mkdir(parents=True)
                item_dir.mkdir(parents=True)
                (input_dir / "reference.jpg").write_bytes(f"ref-{run_name}".encode())
                (item_dir / "rank_001.jpg").write_bytes(b"same-image-for-two-categories")
                (run_dir / "manifest.json").write_text(
                    json.dumps(
                        {
                            "run_id": run_name,
                            "status": "completed",
                            "results": [
                                {
                                    "item_id": "sku",
                                    "keyword": "",
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
                return run_dir

            library.ingest_run(make_run("run-a"), job_id="job-a", category="桌垫", scene="餐桌")
            summary = library.ingest_run(make_run("run-b"), job_id="job-b", category="餐垫", scene="餐桌")

            available = library.search_assets(status="available")
            duplicates = library.search_assets(status="duplicate")

            self.assertEqual(summary["duplicates"], 0)
            self.assertEqual(len(available), 2)
            self.assertEqual(len(duplicates), 0)

    def test_job_manager_exposes_asset_center_search_after_ingest(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.jobs import (
            JobManager,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manager = JobManager(root)
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
                                "keyword": "餐桌",
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

            summary = manager.ingest_assets(run_dir, job_id="job-1", category="桌垫", scene="餐桌")
            results = manager.search_assets({"category": "桌垫", "scene": "餐桌"})

            self.assertEqual(summary["assets"], 1)
            self.assertEqual(results["total"], 1)
            self.assertEqual(results["assets"][0]["sourceImage"]["itemId"], "sku")

    def test_cli_registers_asset_sync_command_for_historical_runs(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.cli import (
            build_parser,
        )

        parser = build_parser()
        args = parser.parse_args(
            [
                "sync",
                "--run-dir",
                "/tmp/run-1",
                "--category",
                "桌垫",
                "--scene",
                "餐桌",
            ]
        )

        self.assertEqual(args.command, "sync")
        self.assertEqual(str(args.run_dir), "/tmp/run-1")
        self.assertEqual(args.category, "桌垫")
        self.assertEqual(args.scene, "餐桌")

    def test_cli_registers_scene_tagging_and_cloud_sync_commands(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.cli import (
            build_parser,
        )

        parser = build_parser()
        tag_args = parser.parse_args(
            [
                "--env-file",
                "/tmp/workbench.local.env",
                "tag-scenes",
                "--runs-root",
                "/tmp/workbench-runs",
                "--category",
                "桌垫",
                "--limit",
                "200",
                "--provider",
                "rule",
                "--model",
                "test-model",
                "--force",
                "--debug-request",
                "--dry-run",
            ]
        )
        sync_args = parser.parse_args(
            [
                "sync-cloud",
                "--runs-root",
                "/tmp/workbench-runs",
                "--server-url",
                "https://asset.example.com",
                "--token",
                "secret",
                "--collector-id",
                "mac-01",
                "--job-id",
                "job-1",
                "--batch-size",
                "100",
            ]
        )

        self.assertEqual(tag_args.command, "tag-scenes")
        self.assertEqual(str(tag_args.env_file), "/tmp/workbench.local.env")
        self.assertEqual(tag_args.provider, "rule")
        self.assertTrue(tag_args.force)
        self.assertTrue(tag_args.debug_request)
        self.assertTrue(tag_args.dry_run)
        self.assertEqual(sync_args.command, "sync-cloud")
        self.assertEqual(sync_args.collector_id, "mac-01")
        self.assertEqual(sync_args.job_id, "job-1")
        self.assertEqual(sync_args.batch_size, 100)

    def test_cli_deploy_mac_mini_runs_remote_deploy_once(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.cli import (
            main,
        )

        calls: list[tuple[Path, bool]] = []

        class FakeAdmin:
            def __init__(self, repo_root, *, run_async=True):
                calls.append((Path(repo_root), run_async))

            def start_mac_mini_remote_deploy(self):
                return {
                    "taskId": "admin-1",
                    "kind": "deploy_mac_mini_remote",
                    "status": "completed",
                    "message": "执行完成",
                    "exitCode": 0,
                    "summary": {"target": "zw@192.168.77.35"},
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with mock.patch(
                "third_party.mobile_image_workbench.backend.mobile_image_workbench.admin.AdminTaskManager",
                FakeAdmin,
            ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "deploy-mac-mini",
                        "--repo-root",
                        str(repo_root),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(calls, [(repo_root.resolve(), False)])
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["summary"]["target"], "zw@192.168.77.35")

    def test_cli_env_file_loads_before_scene_tagger_default_model(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.cli import (
            build_parser,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env.local"
            env_path.write_text(
                "DASHSCOPE_VLM_MODEL=qwen-vl-plus-from-env-file\n"
                "DASHSCOPE_API_KEY=file-key\n",
                encoding="utf-8",
            )
            old_model = os.environ.get("DASHSCOPE_VLM_MODEL")
            old_key = os.environ.get("DASHSCOPE_API_KEY")
            try:
                os.environ.pop("DASHSCOPE_VLM_MODEL", None)
                os.environ["DASHSCOPE_API_KEY"] = "existing-key"
                parser = build_parser(["--env-file", str(env_path)])
                args = parser.parse_args(["--env-file", str(env_path), "tag-scenes"])
                args_after_command = parser.parse_args(["tag-scenes", "--env-file", str(env_path)])

                self.assertEqual(args.model, "qwen-vl-plus-from-env-file")
                self.assertEqual(args_after_command.model, "qwen-vl-plus-from-env-file")
                self.assertEqual(os.environ["DASHSCOPE_API_KEY"], "existing-key")
            finally:
                _restore_env("DASHSCOPE_VLM_MODEL", old_model)
                _restore_env("DASHSCOPE_API_KEY", old_key)

    def test_scene_tagger_defaults_to_qwen_vl_max_and_dashscope_env(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.cli import (
            build_parser,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.scene_tagger import (
            OpenAICompatibleSceneTagger,
        )

        parser = build_parser()
        args = parser.parse_args(["tag-scenes", "--runs-root", "/tmp/workbench-runs"])
        old_key = os.environ.get("DASHSCOPE_API_KEY")
        try:
            os.environ["DASHSCOPE_API_KEY"] = "dashscope-key"
            tagger = OpenAICompatibleSceneTagger(model=args.model)
        finally:
            if old_key is None:
                os.environ.pop("DASHSCOPE_API_KEY", None)
            else:
                os.environ["DASHSCOPE_API_KEY"] = old_key

        self.assertEqual(args.model, "qwen-vl-max")
        self.assertEqual(tagger.model, "qwen-vl-max")
        self.assertEqual(tagger.api_key, "dashscope-key")
        self.assertEqual(
            tagger.base_url,
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

    def test_workbench_env_loader_reads_vlm_config_without_overriding_existing_values(
        self,
    ) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.env import (
            load_env_file,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.scene_tagger import (
            default_vlm_model,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "DASHSCOPE_API_KEY=dashscope-from-file",
                        "DASHSCOPE_VLM_MODEL=qwen-vl-max-latest",
                        "DASHSCOPE_BASE_URL=\"https://dashscope.aliyuncs.com/compatible-mode/v1\"",
                        "not a valid line",
                        "bad-key=ignored",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            old_key = os.environ.get("DASHSCOPE_API_KEY")
            old_model = os.environ.get("DASHSCOPE_VLM_MODEL")
            old_base = os.environ.get("DASHSCOPE_BASE_URL")
            try:
                os.environ["DASHSCOPE_API_KEY"] = "already-set"
                os.environ.pop("DASHSCOPE_VLM_MODEL", None)
                os.environ.pop("DASHSCOPE_BASE_URL", None)
                loaded = load_env_file(env_path)

                self.assertEqual(os.environ["DASHSCOPE_API_KEY"], "already-set")
                self.assertEqual(os.environ["DASHSCOPE_VLM_MODEL"], "qwen-vl-max-latest")
                self.assertEqual(
                    os.environ["DASHSCOPE_BASE_URL"],
                    "https://dashscope.aliyuncs.com/compatible-mode/v1",
                )
                self.assertEqual(default_vlm_model(), "qwen-vl-max-latest")
                self.assertIn("DASHSCOPE_VLM_MODEL", loaded)
                self.assertNotIn("bad-key", loaded)
            finally:
                _restore_env("DASHSCOPE_API_KEY", old_key)
                _restore_env("DASHSCOPE_VLM_MODEL", old_model)
                _restore_env("DASHSCOPE_BASE_URL", old_base)

    def test_scene_tagger_debug_request_exposes_image_identity_without_base64(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.scene_tagger import (
            OpenAICompatibleSceneTagger,
            PROMPT_VERSION,
            SceneTagInput,
        )

        tagger = OpenAICompatibleSceneTagger(
            model="qwen-vl-max",
            api_key="not-logged",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        debug = tagger.debug_request(
            SceneTagInput(
                asset_id="asset-1",
                object_key="collected/2026/05/asset-1.jpg",
                category="桌垫",
                query="红格桌垫",
                source_keyword="买家秀",
                filename="rank_001.jpg",
                mime_type="image/jpeg",
                image_bytes=b"exact-image-payload",
            ),
            local_image_path="/tmp/objects/asset-1.jpg",
        )

        self.assertEqual(debug["model"], "qwen-vl-max")
        self.assertEqual(PROMPT_VERSION, "v2")
        self.assertEqual(
            debug["endpoint"],
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        )
        self.assertEqual(debug["objectKey"], "collected/2026/05/asset-1.jpg")
        self.assertEqual(debug["localImagePath"], "/tmp/objects/asset-1.jpg")
        self.assertEqual(debug["imageBytes"]["length"], len(b"exact-image-payload"))
        self.assertRegex(debug["imageBytes"]["sha256"], r"^[a-f0-9]{64}$")
        self.assertEqual(debug["imageUrl"]["prefix"], "data:image/jpeg;base64,")
        self.assertIn("<redacted", debug["imageUrl"]["preview"])
        self.assertNotIn(base64.b64encode(b"exact-image-payload").decode("ascii"), json.dumps(debug))
        self.assertIn("固定品类：桌垫", debug["prompt"]["userText"])
        self.assertIn("primary_scene", debug["prompt"]["userText"])
        self.assertIn("scene_tags", debug["prompt"]["userText"])
        self.assertIn("4-6 个", debug["prompt"]["userText"])
        self.assertIn("不要输出品类词本身", debug["prompt"]["userText"])
        self.assertIn("颜色图案", debug["prompt"]["userText"])

    def test_asset_library_scene_tags_missing_assets_and_reuses_hash_cache(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.asset_library import (
            AssetLibrary,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.scene_tagger import (
            SceneTagResult,
            StaticSceneTagger,
            tag_missing_scene_assets,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.storage import (
            FilesystemObjectStorageClient,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "run"
            input_dir = run_dir / "inputs" / "sku"
            item_dir = run_dir / "items" / "sku"
            input_dir.mkdir(parents=True)
            item_dir.mkdir(parents=True)
            (input_dir / "reference.jpg").write_bytes(b"ref")
            (item_dir / "rank_001.jpg").write_bytes(b"first")
            (item_dir / "rank_002.jpg").write_bytes(b"first")
            (run_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-1",
                        "status": "completed",
                        "results": [
                            {
                                "item_id": "sku",
                                "keyword": "红格桌垫买家秀",
                                "images": [
                                    {
                                        "rank": 1,
                                        "local_path": str(item_dir / "rank_001.jpg"),
                                        "stage": "image_search",
                                        "query": "",
                                    },
                                    {
                                        "rank": 2,
                                        "local_path": str(item_dir / "rank_002.jpg"),
                                        "stage": "image_search",
                                        "query": "",
                                    },
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            library = AssetLibrary(
                root / "asset_center.sqlite3",
                FilesystemObjectStorageClient(root / "objects", bucket="dev-assets"),
            )
            library.ingest_run(run_dir, job_id="job-1", category="桌垫", scene="")

            dry = tag_missing_scene_assets(
                library,
                StaticSceneTagger(SceneTagResult(["餐桌布置", "买家秀", "红白格"], "high")),
                category="桌垫",
                limit=10,
                dry_run=True,
            )
            written = tag_missing_scene_assets(
                library,
                StaticSceneTagger(SceneTagResult(["餐桌布置", "买家秀", "红白格"], "high")),
                category="桌垫",
                limit=10,
                dry_run=False,
            )
            overwritten = tag_missing_scene_assets(
                library,
                StaticSceneTagger(
                    SceneTagResult(
                        ["红白格", "买家秀实拍", "桌面俯拍", "棉麻质感"],
                        "high",
                        primary_scene="白底展示",
                    )
                ),
                category="桌垫",
                limit=10,
                dry_run=False,
                force=True,
                debug_request=True,
            )
            class ExplodingTagger:
                model = "qwen-vl-max"
                prompt_version = "v1"
                calls = 0

                def debug_request(self, payload, *, local_image_path: str = ""):
                    return {
                        "assetId": payload.asset_id,
                        "imageBytes": {"length": len(payload.image_bytes)},
                        "localImagePath": local_image_path,
                    }

                def tag(self, payload):
                    self.calls += 1
                    raise AssertionError("debug dry-run must not call the VLM")

            exploding_tagger = ExplodingTagger()
            debug_only = tag_missing_scene_assets(
                library,
                exploding_tagger,
                category="桌垫",
                limit=1,
                dry_run=True,
                force=True,
                debug_request=True,
            )
            matches = library.search_assets(scene="餐桌布置")
            overwritten_matches = library.search_assets(scene="白底展示")

            self.assertEqual(dry["dry_run"], True)
            self.assertEqual(dry["tagged"], 0)
            self.assertEqual(written["tagged"], 2)
            self.assertEqual(written["vlm_calls"], 1)
            self.assertEqual(overwritten["tagged"], 2)
            self.assertEqual(len(overwritten["debug_requests"]), 2)
            self.assertIn("imageBytes", overwritten["debug_requests"][0])
            self.assertEqual(debug_only["vlm_calls"], 0)
            self.assertEqual(debug_only["failed"], 0)
            self.assertEqual(debug_only["assets"][0]["status"], "debugged")
            self.assertEqual(exploding_tagger.calls, 0)
            self.assertEqual(len(matches), 0)
            self.assertEqual(len(overwritten_matches), 1)
            self.assertEqual(overwritten_matches[0]["scene"], "白底展示")
            self.assertEqual(
                overwritten_matches[0]["sceneTags"],
                ["白底展示", "红白格", "买家秀实拍", "桌面俯拍", "棉麻质感"],
            )
            self.assertEqual(overwritten_matches[0]["sceneTagStatus"], "tagged")

    def test_asset_library_exports_cloud_sync_bundle_with_scene_tags(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.asset_library import (
            AssetLibrary,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.storage import (
            FilesystemObjectStorageClient,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "run"
            input_dir = run_dir / "inputs" / "sku"
            item_dir = run_dir / "items" / "sku"
            input_dir.mkdir(parents=True)
            item_dir.mkdir(parents=True)
            (input_dir / "reference.jpg").write_bytes(b"reference")
            (item_dir / "rank_001.jpg").write_bytes(b"rank")
            (run_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-1",
                        "status": "completed",
                        "results": [
                            {
                                "item_id": "sku",
                                "keyword": "红格桌垫",
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
            library = AssetLibrary(
                root / "asset_center.sqlite3",
                FilesystemObjectStorageClient(root / "objects", bucket="dev-assets"),
            )
            library.ingest_run(run_dir, job_id="job-1", category="桌垫", scene="")
            other_run_dir = root / "other-run"
            other_input_dir = other_run_dir / "inputs" / "sku2"
            other_item_dir = other_run_dir / "items" / "sku2"
            other_input_dir.mkdir(parents=True)
            other_item_dir.mkdir(parents=True)
            (other_input_dir / "reference.jpg").write_bytes(b"reference-2")
            (other_item_dir / "rank_001.jpg").write_bytes(b"rank-2")
            (other_run_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-2",
                        "status": "completed",
                        "results": [
                            {
                                "item_id": "sku2",
                                "keyword": "蓝格桌垫",
                                "images": [
                                    {
                                        "rank": 1,
                                        "local_path": str(other_item_dir / "rank_001.jpg"),
                                        "stage": "image_search",
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            library.ingest_run(other_run_dir, job_id="job-2", category="桌垫", scene="")
            job_assets = library.export_cloud_bundle(
                collector_id="mac-01",
                category="桌垫",
                job_id="job-1",
                limit=10,
            )["assets"]
            asset_id = job_assets[0]["assetId"]
            library.apply_scene_tags(
                asset_id,
                ["餐桌布置", "买家秀"],
                model="test-model",
                prompt_version="v1",
                raw_response={"scene_tags": ["餐桌布置", "买家秀"]},
            )

            bundle = library.export_cloud_bundle(
                collector_id="mac-01",
                category="桌垫",
                job_id="job-1",
                limit=10,
            )

            self.assertEqual(bundle["collectorId"], "mac-01")
            self.assertEqual(len(bundle["sourceImages"]), 1)
            self.assertEqual(len(bundle["assets"]), 1)
            self.assertEqual(bundle["sourceImages"][0]["itemId"], "sku")
            self.assertEqual(bundle["assets"][0]["scene"], "餐桌布置")
            self.assertEqual(bundle["assets"][0]["sceneTags"], ["餐桌布置", "买家秀"])
            self.assertEqual(bundle["assets"][0]["sceneTagStatus"], "tagged")
            self.assertTrue(bundle["objects"][0]["contentBase64"])
            self.assertIn("sourceImages", bundle)

    def test_job_manager_syncs_completed_job_to_cloud_after_scene_tagging(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.asset_library import (
            AssetLibrary,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.jobs import (
            JobManager,
            JobRecord,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.scene_tagger import (
            SceneTagResult,
            StaticSceneTagger,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.settings import (
            JobSettings,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.storage import (
            FilesystemObjectStorageClient,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_root = root / "runs"
            run_dir = root / "collector-run"
            input_dir = run_dir / "inputs" / "sku"
            item_dir = run_dir / "items" / "sku"
            input_dir.mkdir(parents=True)
            item_dir.mkdir(parents=True)
            (input_dir / "reference.jpg").write_bytes(b"reference")
            (item_dir / "rank_001.jpg").write_bytes(b"rank")
            (run_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-1",
                        "status": "completed",
                        "results": [
                            {
                                "item_id": "sku",
                                "keyword": "红格桌垫",
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
            manager = JobManager(
                runs_root,
                asset_library=AssetLibrary(
                    runs_root / "asset_center.sqlite3",
                    FilesystemObjectStorageClient(runs_root / "objects", bucket="dev-assets"),
                ),
            )
            job_dir = runs_root / "job-1"
            record = JobRecord(
                job_id="job-1",
                status="completed",
                job_dir=job_dir,
                settings=JobSettings.for_mode("single_image"),
                collector_run_dir=run_dir,
            )
            manager._write_record(record)
            sync_calls = []

            def fake_cloud_sync(**kwargs):
                sync_calls.append(kwargs)
                return {"sourceImages": 1, "assets": 1, "duplicates": 0}

            with mock.patch.dict(
                os.environ,
                {
                    "MWB_CLOUD_SERVER_URL": "https://asset.example.com",
                    "MWB_CLOUD_SYNC_TOKEN": "token",
                    "MWB_COLLECTOR_ID": "mac-01",
                },
                clear=False,
            ):
                summary = manager.sync_job_to_cloud(
                    "job-1",
                    scene_tagger=StaticSceneTagger(
                        SceneTagResult(["餐桌布置", "红白格"], "high", {}, "餐桌布置")
                    ),
                    cloud_sync=fake_cloud_sync,
                )

            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["tagScenes"]["tagged"], 1)
            self.assertEqual(summary["cloudSync"]["assets"], 1)
            self.assertEqual(sync_calls[0]["job_id"], "job-1")
            self.assertEqual(sync_calls[0]["server_url"], "https://asset.example.com")
            self.assertEqual(sync_calls[0]["token"], "token")

    def test_job_manager_rejects_cloud_sync_before_collection_finishes(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.jobs import (
            JobManager,
            JobRecord,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.settings import (
            JobSettings,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            runs_root = Path(temp_dir) / "runs"
            manager = JobManager(runs_root)
            record = JobRecord(
                job_id="job-queued",
                status="queued",
                job_dir=runs_root / "job-queued",
                settings=JobSettings.for_mode("single_image"),
            )
            manager._write_record(record)

            with self.assertRaisesRegex(ValueError, "completed or partial"):
                manager.sync_job_to_cloud("job-queued")

    def test_job_manager_lists_persisted_jobs_newest_first_for_history(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.jobs import (
            JobManager,
            JobRecord,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.settings import (
            JobSettings,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manager = JobManager(root / "runs")
            old_job = JobRecord(
                job_id="20260524T000000000000Z",
                status="failed",
                job_dir=root / "runs" / "20260524T000000000000Z",
                settings=JobSettings.for_mode("single_image"),
                message="device not ready",
            )
            newer_job = JobRecord(
                job_id="20260525T000000000000Z",
                status="completed",
                job_dir=root / "runs" / "20260525T000000000000Z",
                settings=JobSettings.for_mode("batch_images"),
                collector_run_dir=root / "collector-run",
                message="采集完成",
            )
            manager._write_record(old_job)
            manager._write_record(newer_job)
            (root / "runs" / "bad-job").mkdir()
            (root / "runs" / "bad-job" / "job.json").write_text(
                "{not valid json",
                encoding="utf-8",
            )

            jobs = manager.list_jobs(limit=10)

            self.assertEqual([job.job_id for job in jobs], [newer_job.job_id, old_job.job_id])
            self.assertEqual(jobs[0].status, "completed")
            self.assertEqual(jobs[0].settings.mode, "batch_images")
            self.assertEqual(jobs[0].message, "采集完成")

    def test_jobs_get_route_returns_history_list(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.server import (
            WorkbenchRequestHandler,
        )

        class FakeManager:
            def list_jobs(self, limit=50):
                self.limit = limit
                return [
                    mock.Mock(
                        to_dict=lambda: {
                            "jobId": "20260525T000000000000Z",
                            "status": "completed",
                            "settings": {"mode": "batch_images"},
                            "message": "采集完成",
                        }
                    )
                ]

        handler = WorkbenchRequestHandler.__new__(WorkbenchRequestHandler)
        handler.path = "/api/jobs?limit=5"
        handler.manager = FakeManager()
        payloads: list[tuple[dict, HTTPStatus]] = []
        handler._send_json = lambda payload, status=HTTPStatus.OK: payloads.append(
            (payload, status)
        )

        handler.do_GET()

        self.assertEqual(handler.manager.limit, 5)
        self.assertEqual(payloads[0][0]["jobs"][0]["jobId"], "20260525T000000000000Z")
        self.assertEqual(payloads[0][0]["jobs"][0]["status"], "completed")

    def test_job_manager_stop_running_job_marks_stopping_and_writes_cancel_marker(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.jobs import (
            JobManager,
            JobRecord,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.settings import (
            JobSettings,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manager = JobManager(root / "runs")
            record = JobRecord(
                job_id="job-running",
                status="running",
                job_dir=root / "runs" / "job-running",
                settings=JobSettings.for_mode("single_image"),
                message="采集任务运行中",
            )
            manager._write_record(record)

            stopped = manager.stop_job("job-running")

            self.assertEqual(stopped.status, "stopping")
            self.assertTrue((record.job_dir / "cancel_requested.json").exists())
            events = (record.job_dir / "job_events.jsonl").read_text(encoding="utf-8")
            self.assertIn("stop_requested", events)

    def test_job_manager_stop_queued_job_finishes_as_canceled(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.jobs import (
            JobManager,
            JobRecord,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.settings import (
            JobSettings,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manager = JobManager(root / "runs")
            record = JobRecord(
                job_id="job-queued",
                status="queued",
                job_dir=root / "runs" / "job-queued",
                settings=JobSettings.for_mode("single_image"),
            )
            manager._write_record(record)

            stopped = manager.stop_job("job-queued")

            self.assertEqual(stopped.status, "canceled")
            self.assertTrue((record.job_dir / "cancel_requested.json").exists())
            events = (record.job_dir / "job_events.jsonl").read_text(encoding="utf-8")
            self.assertIn("stop_requested", events)
            self.assertIn("job_canceled", events)

    def test_job_manager_rejects_stop_after_job_is_terminal(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.jobs import (
            JobManager,
            JobRecord,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.settings import (
            JobSettings,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manager = JobManager(root / "runs")
            record = JobRecord(
                job_id="job-done",
                status="completed",
                job_dir=root / "runs" / "job-done",
                settings=JobSettings.for_mode("single_image"),
            )
            manager._write_record(record)

            with self.assertRaisesRegex(ValueError, "cannot stop"):
                manager.stop_job("job-done")

    def test_job_stop_post_route_calls_manager(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.server import (
            WorkbenchRequestHandler,
        )

        calls: list[str] = []

        class FakeManager:
            def stop_job(self, job_id: str):
                calls.append(job_id)
                return mock.Mock(
                    to_dict=lambda: {"jobId": job_id, "status": "stopping"}
                )

        handler = WorkbenchRequestHandler.__new__(WorkbenchRequestHandler)
        handler.path = "/api/jobs/job-1/stop"
        handler.manager = FakeManager()
        payloads: list[tuple[dict, HTTPStatus]] = []
        handler._send_json = lambda payload, status=HTTPStatus.OK: payloads.append(
            (payload, status)
        )

        handler.do_POST()

        self.assertEqual(calls, ["job-1"])
        self.assertEqual(payloads[0][0]["status"], "stopping")

    def test_job_manager_passes_cancel_token_to_collector_and_finishes_canceled(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.jobs import (
            JobManager,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manager = JobManager(root / "runs")
            image_path = root / "ref.jpg"
            image_path.write_bytes(b"fake image")
            payload = {
                "mode": "single_image",
                "images": [
                    {
                        "filename": "ref.jpg",
                        "contentBase64": base64.b64encode(b"fake image").decode("ascii"),
                    }
                ],
                "settings": {
                    "mode": "single_image",
                    "dryRun": False,
                    "deterministicMode": True,
                    "imageTopN": 1,
                    "keywordTopN": 0,
                },
            }
            record = manager.create_job(payload, start=False)

            class FakeManifest:
                status = "canceled"
                output_dir = record.job_dir / "collector_runs" / "fake-run"

            captured = {}

            def fake_collect(*args, **kwargs):
                captured["cancel_token"] = kwargs["cancel_token"]
                self.assertFalse(captured["cancel_token"].is_cancel_requested())
                (FakeManifest.output_dir / "items").mkdir(parents=True)
                (FakeManifest.output_dir / "manifest.json").write_text(
                    json.dumps(
                        {
                            "run_id": "fake-run",
                            "status": "canceled",
                            "output_dir": str(FakeManifest.output_dir),
                            "input_path": str(record.job_dir / "generated_inputs.json"),
                            "mode": "deterministic",
                            "results": [],
                        }
                    ),
                    encoding="utf-8",
                )
                return FakeManifest()

            with mock.patch(
                "third_party.mobile_image_workbench.backend.mobile_image_workbench.jobs.run_direct_items_collect",
                side_effect=fake_collect,
            ), mock.patch(
                "third_party.mobile_image_workbench.backend.mobile_image_workbench.jobs.write_result_exports"
            ):
                updated = manager.run_job(record.job_id)

            self.assertEqual(updated.status, "canceled")
            self.assertIsNotNone(captured["cancel_token"])
            events = (record.job_dir / "job_events.jsonl").read_text(encoding="utf-8")
            self.assertIn("job_canceled", events)

    def test_admin_status_reports_config_and_latest_syncable_job(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.admin import (
            AdminTaskManager,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.jobs import (
            JobManager,
            JobRecord,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.settings import (
            JobSettings,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manager = JobManager(root / "runs")
            manager._write_record(
                JobRecord(
                    job_id="20260524T000000000000Z",
                    status="completed",
                    job_dir=root / "runs" / "20260524T000000000000Z",
                    settings=JobSettings.for_mode("single_image"),
                    collector_run_dir=root / "collector-a",
                )
            )
            manager._write_record(
                JobRecord(
                    job_id="20260525T000000000000Z",
                    status="partial",
                    job_dir=root / "runs" / "20260525T000000000000Z",
                    settings=JobSettings.for_mode("batch_images"),
                    collector_run_dir=root / "collector-b",
                )
            )
            admin = AdminTaskManager(root)

            with mock.patch.dict(
                os.environ,
                {
                    "MWB_ADMIN_TOKEN": "secret",
                    "MWB_CLOUD_SERVER_URL": "https://asset.example.com",
                    "MWB_CLOUD_SYNC_TOKEN": "sync-token",
                    "MWB_COLLECTOR_ID": "mac-01",
                    "DASHSCOPE_API_KEY": "dashscope",
                    "MWB_DEPLOY_SSH_HOST": "asset.internal",
                    "MWB_DEPLOY_SSH_USER": "deploy",
                    "MWB_DEPLOY_SSH_KEY_PATH": "/Users/yichen/.ssh/deploy",
                },
                clear=False,
            ):
                status = admin.status(manager)

            self.assertTrue(status["adminTokenConfigured"])
            self.assertTrue(status["cloudSync"]["configured"])
            self.assertTrue(status["vlm"]["configured"])
            self.assertTrue(status["deploy"]["cloud"]["configured"])
            self.assertIn("macMiniRemote", status["deploy"])
            self.assertIn("install_workbench_launchd.sh", status["deploy"]["mac"]["script"])
            self.assertEqual(status["latestSyncableJob"]["jobId"], "20260525T000000000000Z")

    def test_admin_rejects_missing_or_invalid_token_for_mutating_actions(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.admin import (
            require_admin_token,
        )

        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(PermissionError, "MWB_ADMIN_TOKEN"):
                require_admin_token("")
        with mock.patch.dict(os.environ, {"MWB_ADMIN_TOKEN": "secret"}, clear=True):
            with self.assertRaisesRegex(PermissionError, "invalid admin token"):
                require_admin_token("Bearer wrong")
            self.assertIsNone(require_admin_token("Bearer secret"))

    def test_admin_sync_latest_selects_latest_completed_job_and_records_task(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.admin import (
            AdminTaskManager,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.jobs import (
            JobManager,
            JobRecord,
        )
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.settings import (
            JobSettings,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manager = JobManager(root / "runs")
            sync_calls: list[str] = []
            manager.sync_job_to_cloud = lambda job_id: sync_calls.append(job_id) or {
                "status": "completed",
                "cloudSync": {"assets": 3},
            }
            manager._write_record(
                JobRecord(
                    job_id="20260524T000000000000Z",
                    status="completed",
                    job_dir=root / "runs" / "20260524T000000000000Z",
                    settings=JobSettings.for_mode("single_image"),
                )
            )
            manager._write_record(
                JobRecord(
                    job_id="20260525T000000000000Z",
                    status="partial",
                    job_dir=root / "runs" / "20260525T000000000000Z",
                    settings=JobSettings.for_mode("batch_images"),
                )
            )
            admin = AdminTaskManager(root, run_async=False)

            task = admin.start_sync_latest(manager)

            self.assertEqual(sync_calls, ["20260525T000000000000Z"])
            self.assertEqual(task["status"], "completed")
            self.assertEqual(task["summary"]["cloudSync"]["assets"], 3)
            self.assertIn("最新任务 20260525T000000000000Z", "\n".join(task["logs"]))

    def test_admin_deploy_commands_are_whitelisted_and_recorded(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.admin import (
            AdminTaskManager,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mac_script = root / "third_party/mobile_deploy/mac-mini/install_workbench_launchd.sh"
            cloud_script = root / "third_party/mobile_deploy/server/install_asset_center_systemd.sh"
            mac_script.parent.mkdir(parents=True)
            cloud_script.parent.mkdir(parents=True)
            mac_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            cloud_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            popen_calls = []
            run_calls = []

            class FakePopen:
                def __init__(self, command, **kwargs):
                    popen_calls.append((command, kwargs))

            class FakeCompleted:
                returncode = 0
                stdout = "ok"
                stderr = ""

            def fake_run(command, **kwargs):
                run_calls.append((command, kwargs))
                return FakeCompleted()

            admin = AdminTaskManager(
                root,
                run_async=False,
                popen_runner=FakePopen,
                command_runner=fake_run,
            )
            with mock.patch.dict(
                os.environ,
                {
                    "MWB_DEPLOY_SSH_HOST": "asset.internal",
                    "MWB_DEPLOY_SSH_USER": "deploy",
                    "MWB_DEPLOY_SSH_KEY_PATH": "/Users/yichen/.ssh/deploy",
                    "MWB_DEPLOY_SSH_PORT": "2222",
                    "MWB_DEPLOY_REMOTE_ROOT": "/tmp/mobile-deploy-workspace",
                    "MWB_DEPLOY_REMOTE_INSTALL_DIR": "/opt/mobile_asset_center",
                    "MWB_DEPLOY_HOST_NAME": "asset.internal",
                },
                clear=False,
            ):
                mac_task = admin.start_mac_deploy()
                cloud_task = admin.start_cloud_deploy()

            self.assertEqual(mac_task["status"], "completed")
            self.assertEqual(popen_calls[0][0], ["bash", str(mac_script.resolve())])
            self.assertEqual(cloud_task["status"], "completed")
            self.assertEqual(run_calls[0][0][0], "rsync")
            self.assertEqual(run_calls[1][0][0], "ssh")
            self.assertIn("install_asset_center_systemd.sh", run_calls[1][0][-1])
            self.assertNotIn(";", run_calls[0][0])

    def test_admin_mac_mini_remote_config_loads_from_dedicated_env_file(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.admin import (
            AdminTaskManager,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            remote_env = root / "third_party/mobile_deploy/mac-mini/.env.remote"
            remote_env.parent.mkdir(parents=True)
            remote_env.write_text(
                "\n".join(
                    [
                        "MWB_MAC_MINI_SSH_TARGET=deployer@192.168.77.85",
                        "MWB_MAC_MINI_REMOTE_ROOT=/Users/deployer/mobile-runtime",
                        "MWB_MAC_MINI_SSH_KEY_PATH=/Users/yichen/.ssh/mac-mini",
                        "MWB_MAC_MINI_SSH_PORT=2222",
                        "MWB_MAC_MINI_WORKBENCH_ENV_FILE=/Users/deployer/mobile-runtime/third_party/mobile_image_workbench/.env.mac-mini",
                        "MWB_MAC_MINI_SSH_PASS=secret-should-not-leak",
                    ]
                ),
                encoding="utf-8",
            )
            admin = AdminTaskManager(root)

            with mock.patch.dict(os.environ, {}, clear=True):
                status = admin.status(mock.Mock(root_dir=root / "runs"))

            remote = status["deploy"]["macMiniRemote"]
            self.assertTrue(remote["configured"])
            self.assertEqual(remote["auth"], "key")
            self.assertEqual(remote["target"], "deployer@192.168.77.85")
            self.assertEqual(remote["remoteRoot"], "/Users/deployer/mobile-runtime")
            self.assertEqual(remote["port"], "2222")
            self.assertEqual(
                remote["workbenchEnvFile"],
                "/Users/deployer/mobile-runtime/third_party/mobile_image_workbench/.env.mac-mini",
            )
            self.assertNotIn("secret-should-not-leak", json.dumps(remote, ensure_ascii=False))

    def test_admin_mac_mini_remote_config_uses_new_env_before_legacy_names(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.admin import (
            AdminTaskManager,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            admin = AdminTaskManager(root)
            with mock.patch.dict(
                os.environ,
                {
                    "MAC_MINI_USER": "legacy@host",
                    "MAC_NINI_PASS": "legacy-pass",
                    "RES_DIR": "/legacy/root",
                    "MWB_MAC_MINI_SSH_TARGET": "new@host",
                    "MWB_MAC_MINI_REMOTE_ROOT": "/new/root",
                    "MWB_MAC_MINI_SSH_PASS": "new-pass",
                },
                clear=True,
            ):
                status = admin.status(mock.Mock(root_dir=root / "runs"))

            remote = status["deploy"]["macMiniRemote"]
            self.assertTrue(remote["configured"])
            self.assertEqual(remote["target"], "new@host")
            self.assertEqual(remote["remoteRoot"], "/new/root")
            self.assertEqual(remote["auth"], "password")

    def test_admin_mac_mini_remote_deploy_uses_key_auth_whitelisted_commands(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.admin import (
            AdminTaskManager,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mac_script = root / "third_party/mobile_deploy/mac-mini/install_workbench_launchd.sh"
            key_path = root / "keys/mac-mini"
            mac_script.parent.mkdir(parents=True)
            key_path.parent.mkdir(parents=True)
            mac_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            key_path.write_text("fake-key", encoding="utf-8")
            run_calls = []

            class FakeCompleted:
                returncode = 0
                stdout = "ok"
                stderr = ""

            def fake_run(command, **kwargs):
                run_calls.append((command, kwargs))
                return FakeCompleted()

            admin = AdminTaskManager(root, run_async=False, command_runner=fake_run)
            with mock.patch.dict(
                os.environ,
                {
                    "MWB_MAC_MINI_SSH_TARGET": "deployer@192.168.77.85",
                    "MWB_MAC_MINI_REMOTE_ROOT": "/Users/deployer/mobile-runtime",
                    "MWB_MAC_MINI_SSH_KEY_PATH": str(key_path),
                    "MWB_MAC_MINI_SSH_PORT": "2222",
                },
                clear=True,
            ):
                task = admin.start_mac_mini_remote_deploy()

            self.assertEqual(task["status"], "completed")
            self.assertEqual([call[0][0] for call in run_calls], ["rsync", "ssh"])
            self.assertIn("deployer@192.168.77.85:/Users/deployer/mobile-runtime/", run_calls[0][0])
            self.assertIn("install_workbench_launchd.sh", run_calls[1][0][-1])
            self.assertIn("MWB_ENV_FILE=", run_calls[1][0][-1])
            self.assertIn(f"-i {key_path}", " ".join(run_calls[0][0]))
            self.assertIn("IdentitiesOnly=yes", " ".join(run_calls[0][0]))
            self.assertNotIn("secret", "\n".join(" ".join(call[0]) for call in run_calls))
            self.assertNotIn(";", run_calls[0][0])

    def test_admin_mac_mini_remote_deploy_rejects_missing_key_file_before_rsync(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.admin import (
            AdminTaskManager,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mac_script = root / "third_party/mobile_deploy/mac-mini/install_workbench_launchd.sh"
            mac_script.parent.mkdir(parents=True)
            mac_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            run_calls = []

            def fake_run(command, **kwargs):
                run_calls.append((command, kwargs))
                return mock.Mock(returncode=0, stdout="", stderr="")

            admin = AdminTaskManager(root, run_async=False, command_runner=fake_run)
            with mock.patch.dict(
                os.environ,
                {
                    "MWB_MAC_MINI_SSH_TARGET": "deployer@192.168.77.85",
                    "MWB_MAC_MINI_REMOTE_ROOT": "/Users/deployer/mobile-runtime",
                    "MWB_MAC_MINI_SSH_KEY_PATH": "/Users/you/.ssh/mac-mini-deploy",
                },
                clear=True,
            ):
                task = admin.start_mac_mini_remote_deploy()

            self.assertEqual(task["status"], "failed")
            self.assertIn("SSH key file not found", task["message"])
            self.assertEqual(run_calls, [])

    def test_admin_mac_mini_remote_deploy_requires_sshpass_for_password_auth(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.admin import (
            AdminTaskManager,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mac_script = root / "third_party/mobile_deploy/mac-mini/install_workbench_launchd.sh"
            mac_script.parent.mkdir(parents=True)
            mac_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            admin = AdminTaskManager(root, run_async=False, command_runner=lambda *args, **kwargs: None)

            with mock.patch.dict(
                os.environ,
                {
                    "MWB_MAC_MINI_SSH_TARGET": "deployer@192.168.77.85",
                    "MWB_MAC_MINI_REMOTE_ROOT": "/Users/deployer/mobile-runtime",
                    "MAC_NINI_PASS": "legacy-pass",
                },
                clear=True,
            ), mock.patch(
                "third_party.mobile_image_workbench.backend.mobile_image_workbench.admin.shutil.which",
                return_value=None,
            ):
                task = admin.start_mac_mini_remote_deploy()

            self.assertEqual(task["status"], "failed")
            self.assertIn("sshpass", task["message"])

    def test_admin_post_route_starts_mac_mini_remote_deploy_with_token(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.server import (
            WorkbenchRequestHandler,
        )

        calls: list[str] = []

        class FakeHeaders:
            def get(self, name, default=None):
                return "Bearer secret" if name == "Authorization" else default

        class FakeAdmin:
            def start_mac_mini_remote_deploy(self):
                calls.append("mac-mini")
                return {"taskId": "admin-1", "status": "queued"}

        handler = WorkbenchRequestHandler.__new__(WorkbenchRequestHandler)
        handler.path = "/api/admin/deploy/mac-mini"
        handler.headers = FakeHeaders()
        handler.admin_manager = FakeAdmin()
        payloads: list[tuple[dict, HTTPStatus]] = []
        handler._send_json = lambda payload, status=HTTPStatus.OK: payloads.append(
            (payload, status)
        )

        with mock.patch.dict(os.environ, {"MWB_ADMIN_TOKEN": "secret"}, clear=True):
            handler.do_POST()

        self.assertEqual(calls, ["mac-mini"])
        self.assertEqual(payloads[0][0]["taskId"], "admin-1")

    def test_frontend_exposes_asset_center_filters_and_results_grid(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_vue = (
            root / "third_party/mobile_image_workbench/frontend/src/App.vue"
        ).read_text(encoding="utf-8")

        self.assertIn("素材中心", app_vue)
        self.assertIn("/api/library/assets", app_vue)
        self.assertIn("assetFilters", app_vue)
        self.assertIn("category", app_vue)
        self.assertIn("scene", app_vue)
        self.assertIn("downloadUrl", app_vue)

    def test_frontend_exposes_cloud_sync_action_after_collection(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_vue = (
            root / "third_party/mobile_image_workbench/frontend/src/App.vue"
        ).read_text(encoding="utf-8")
        css = (
            root / "third_party/mobile_image_workbench/frontend/src/styles.css"
        ).read_text(encoding="utf-8")

        self.assertIn("打标签并同步云端", app_vue)
        self.assertIn("/sync-cloud", app_vue)
        self.assertIn("canSyncToCloud", app_vue)
        self.assertIn("cloud-sync-actions", css)

    def test_frontend_exposes_admin_view_for_sync_and_deploy(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_vue = (
            root / "third_party/mobile_image_workbench/frontend/src/App.vue"
        ).read_text(encoding="utf-8")
        css = (
            root / "third_party/mobile_image_workbench/frontend/src/styles.css"
        ).read_text(encoding="utf-8")

        self.assertIn("后台管理", app_vue)
        self.assertIn("MWB_ADMIN_TOKEN", app_vue)
        self.assertIn("sessionStorage", app_vue)
        self.assertIn("/api/admin/status", app_vue)
        self.assertIn("/api/admin/sync/latest", app_vue)
        self.assertIn("/api/admin/deploy/mac", app_vue)
        self.assertIn("/api/admin/deploy/mac-mini", app_vue)
        self.assertIn("/api/admin/deploy/cloud", app_vue)
        self.assertIn("Authorization: `Bearer ${adminToken.value}`", app_vue)
        self.assertIn("一键同步最新任务", app_vue)
        self.assertIn("部署 Mac 工作台", app_vue)
        self.assertIn("远程部署 Mac mini", app_vue)
        self.assertIn("部署云端素材中心", app_vue)
        self.assertIn("admin-page", css)
        self.assertIn("admin-log", css)

    def test_frontend_exposes_stop_current_collection_action(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_vue = (
            root / "third_party/mobile_image_workbench/frontend/src/App.vue"
        ).read_text(encoding="utf-8")
        css = (
            root / "third_party/mobile_image_workbench/frontend/src/styles.css"
        ).read_text(encoding="utf-8")

        self.assertIn("停止采集", app_vue)
        self.assertIn("stopCurrentJob", app_vue)
        self.assertIn("/stop", app_vue)
        self.assertIn("isStoppingJob", app_vue)
        self.assertIn("canStopJob", app_vue)
        self.assertIn("stopping", app_vue)
        self.assertIn("canceled", app_vue)
        self.assertIn("stop-button", css)

    def test_mobile_deploy_scripts_cover_mac_mini_and_cloud_server(self) -> None:
        root = Path(__file__).resolve().parents[1]
        mac_script = (
            root / "third_party/mobile_deploy/mac-mini/install_workbench_launchd.sh"
        ).read_text(encoding="utf-8")
        server_script = (
            root / "third_party/mobile_deploy/server/install_asset_center_systemd.sh"
        ).read_text(encoding="utf-8")
        readme = (root / "third_party/mobile_deploy/README.md").read_text(
            encoding="utf-8"
        )
        mac_env = (
            root / "third_party/mobile_deploy/mac-mini/workbench.env.example"
        ).read_text(encoding="utf-8")
        local_env = (
            root / "third_party/mobile_deploy/mac-mini/workbench.local.env.example"
        ).read_text(encoding="utf-8")
        mac_mini_env = (
            root / "third_party/mobile_deploy/mac-mini/workbench.mac-mini.env.example"
        ).read_text(encoding="utf-8")
        remote_env = (
            root / "third_party/mobile_deploy/mac-mini/remote.env.example"
        ).read_text(encoding="utf-8")
        server_env = (
            root / "third_party/mobile_deploy/server/asset-center.env.example"
        ).read_text(encoding="utf-8")

        self.assertIn("LaunchAgents", mac_script)
        self.assertIn("mobile_image_workbench", mac_script)
        self.assertIn("<string>serve</string>", mac_script)
        self.assertIn("MWB_PYTHON_BIN", mac_script)
        self.assertIn("python3.12", mac_script)
        self.assertIn("python3.11", mac_script)
        self.assertIn("Removing incompatible venv", mac_script)
        self.assertIn("Install Certificates.command", mac_script)
        self.assertIn("/Applications/Python 3.12/Install Certificates.command", mac_script)
        self.assertIn("python_certificates_ready", mac_script)
        self.assertIn(
            "Python SSL certificates already available; skipping certificate installer.",
            mac_script,
        )
        self.assertIn("No Python certificate installer found", mac_script)
        self.assertIn("MWB_PIP_TRUSTED_HOST", mac_script)
        self.assertIn("PIP_TRUSTED_HOST", mac_script)
        self.assertIn("MWB_PIP_INDEX_URL", mac_script)
        self.assertIn("MWB_ENV_FILE", mac_script)
        self.assertIn("load_dotenv", mac_script)
        self.assertIn("pip_tooling_ready", mac_script)
        self.assertIn("pip tooling already available; skipping upgrade.", mac_script)
        self.assertIn("--no-build-isolation", mac_script)
        self.assertIn("pip install --no-build-isolation -e", mac_script)
        self.assertNotIn("source \"${ENV_FILE}\"", mac_script)
        self.assertIn("<string>--env-file</string>", mac_script)
        self.assertIn("npm not found; using existing frontend/dist", mac_script)
        self.assertIn("frontend/dist/index.html", mac_script)
        self.assertIn("ANDROID_HOME_DIR", mac_script)
        self.assertIn("platform-tools", mac_script)
        self.assertIn("<key>ANDROID_HOME</key>", mac_script)
        self.assertIn("MWB_CLOUD_SERVER_URL", mac_env)
        self.assertIn("DASHSCOPE_API_KEY", mac_env)
        self.assertIn("MWB_ADMIN_TOKEN", mac_env)
        self.assertIn("MWB_DEPLOY_SSH_HOST", mac_env)
        self.assertIn("MWB_COLLECTOR_ID=local-validation", local_env)
        self.assertIn("MWB_CLOUD_SERVER_URL=http://127.0.0.1:8876", local_env)
        self.assertIn("MWB_COLLECTOR_ID=mac-mini-01", mac_mini_env)
        self.assertIn("MWB_PYTHON_BIN", mac_mini_env)
        self.assertIn("ANDROID_HOME", mac_mini_env)
        self.assertIn("workbench.local.env.example", readme)
        self.assertIn("workbench.mac-mini.env.example", readme)
        self.assertIn("MWB_MAC_MINI_SSH_TARGET", remote_env)
        self.assertIn("MWB_MAC_MINI_REMOTE_ROOT", remote_env)
        self.assertIn("MWB_MAC_MINI_WORKBENCH_ENV_FILE", remote_env)
        self.assertIn("MWB_MAC_MINI_SSH_PASS", remote_env)
        self.assertIn("systemctl", server_script)
        self.assertIn("mobile_asset_center", server_script)
        self.assertIn("serve --env-file", server_script)
        self.assertIn("nginx", server_script)
        self.assertIn("ASSET_CENTER_PROFILE=cloud", server_env)
        self.assertIn("ALIYUN_OSS_BUCKET", server_env)
        self.assertIn("Mac mini", readme)
        self.assertIn(".env.remote", readme)
        self.assertIn(".env.asset.cloud", readme)
        self.assertIn("deploy-mac-mini --json", readme)
        self.assertIn("云服务器", readme)

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

    def test_direct_image_modes_ignore_keyword_counts_without_explicit_keywords(
        self,
    ) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.settings import (
            JobSettings,
        )

        batch = JobSettings.from_payload(
            {
                "mode": "batch_images",
                "settings": {
                    "mode": "batch_images",
                    "keywordTopN": 3,
                    "keywordResultTopN": 5,
                },
                "images": [
                    {"filename": "a.png", "contentBase64": "x"},
                    {"filename": "b.png", "contentBase64": "x"},
                ],
            }
        )
        single = JobSettings.from_payload(
            {
                "mode": "single_image",
                "settings": {
                    "mode": "single_image",
                    "keywordTopN": 2,
                    "keywordResultTopN": 5,
                },
                "image": {"filename": "a.png", "contentBase64": "x"},
            }
        )

        self.assertEqual(batch.keyword_top_n, 0)
        self.assertEqual(batch.keyword_result_top_n, 0)
        self.assertEqual(single.keyword_top_n, 0)
        self.assertEqual(single.keyword_result_top_n, 0)

    def test_direct_image_modes_allow_explicit_keyword_counts_with_image_keywords(
        self,
    ) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.settings import (
            JobSettings,
        )

        settings = JobSettings.from_payload(
            {
                "mode": "batch_images",
                "settings": {
                    "mode": "batch_images",
                    "keywordTopN": 2,
                    "keywordResultTopN": 5,
                },
                "images": [
                    {
                        "filename": "a.png",
                        "contentBase64": "x",
                        "keywordCandidates": ["桌垫 买家秀"],
                    }
                ],
            }
        )

        self.assertEqual(settings.keyword_top_n, 2)
        self.assertEqual(settings.keyword_result_top_n, 5)

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

    def test_event_translation_marks_input_injection_permission_as_attention(self) -> None:
        from third_party.mobile_image_workbench.backend.mobile_image_workbench.events import (
            translate_event,
        )

        current = translate_event(
            {
                "event": "device_input_permission_required",
                "reason": "java.lang.SecurityException: Injecting input events requires INJECT_EVENTS permission",
            }
        )
        legacy = translate_event(
            {
                "event": "deterministic_failed",
                "reason": "java.lang.SecurityException: Injecting input events requires the caller to have the INJECT_EVENTS permission",
            }
        )

        self.assertEqual(current["level"], "needs_attention")
        self.assertIn("新手机", current["message"])
        self.assertIn("自动点击", current["message"])
        self.assertEqual(legacy["level"], "needs_attention")
        self.assertIn("USB 调试", legacy["message"])

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

    def test_frontend_paste_reads_clipboard_items_and_shows_feedback(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_vue = (
            root / "third_party/mobile_image_workbench/frontend/src/App.vue"
        ).read_text(encoding="utf-8")

        self.assertIn("clipboardData?.items", app_vue)
        self.assertIn("getAsFile()", app_vue)
        self.assertIn("dedupeFiles", app_vue)
        self.assertIn("pasteMessage", app_vue)
        self.assertIn("已粘贴", app_vue)
        self.assertIn("没有识别到图片", app_vue)
        self.assertIn("event.preventDefault()", app_vue)

    def test_frontend_upload_ids_do_not_require_secure_context_random_uuid(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_vue = (
            root / "third_party/mobile_image_workbench/frontend/src/App.vue"
        ).read_text(encoding="utf-8")

        self.assertIn("function makeLocalId", app_vue)
        self.assertIn("globalThis.crypto?.randomUUID", app_vue)
        self.assertNotIn("id: crypto.randomUUID()", app_vue)

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

    def test_frontend_loads_job_history_after_refresh(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_vue = (
            root / "third_party/mobile_image_workbench/frontend/src/App.vue"
        ).read_text(encoding="utf-8")
        css = (
            root / "third_party/mobile_image_workbench/frontend/src/styles.css"
        ).read_text(encoding="utf-8")

        self.assertIn("历史任务", app_vue)
        self.assertIn("jobHistory", app_vue)
        self.assertIn("loadJobHistory", app_vue)
        self.assertIn("/api/jobs?limit=20", app_vue)
        self.assertIn("selectJobHistoryItem", app_vue)
        self.assertIn("closeEventStream", app_vue)
        self.assertIn(".history-panel", css)

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
