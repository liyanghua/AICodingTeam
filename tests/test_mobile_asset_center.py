from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock
from pathlib import Path


class MobileAssetCenterTests(unittest.TestCase):
    def test_asset_center_defaults_to_local_profile_without_cloud_env(self) -> None:
        from third_party.mobile_asset_center.backend.mobile_asset_center.server import (
            asset_center_runtime_config,
        )

        env = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            config = asset_center_runtime_config(Path(temp_dir), env=env)

        self.assertEqual(config["profile"], "local")
        self.assertEqual(config["repository"], "sqlite")
        self.assertEqual(config["storage"], "filesystem")

    def test_asset_center_cloud_profile_requires_pg_and_oss_variables(self) -> None:
        from third_party.mobile_asset_center.backend.mobile_asset_center.server import (
            asset_center_runtime_config,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "ASSET_CENTER_DB_DSN"):
                asset_center_runtime_config(
                    Path(temp_dir),
                    env={
                        "ASSET_CENTER_PROFILE": "cloud",
                        "ASSET_CENTER_STORAGE_PROVIDER": "aliyun_oss",
                    },
                )

    def test_asset_center_env_file_loads_without_overriding_existing_env(self) -> None:
        from third_party.mobile_asset_center.backend.mobile_asset_center.cli import (
            main,
        )
        from third_party.mobile_asset_center.backend.mobile_asset_center.server import (
            asset_center_runtime_config,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_file = root / ".env.asset.local"
            env_file.write_text(
                "ASSET_CENTER_PROFILE=local\n"
                "ASSET_CENTER_SYNC_TOKEN=file-token\n",
                encoding="utf-8",
            )

            class FakeServer:
                def serve_forever(self) -> None:
                    return None

            captured: dict = {}

            def fake_serve(**kwargs):
                captured.update(kwargs)
                return FakeServer()

            with mock.patch.dict(os.environ, {"ASSET_CENTER_SYNC_TOKEN": "real-env-token"}, clear=False):
                with mock.patch(
                    "third_party.mobile_asset_center.backend.mobile_asset_center.cli.serve",
                    fake_serve,
                ):
                    status = main(
                        [
                            "serve",
                            "--env-file",
                            str(env_file),
                            "--data-root",
                            str(root / "data"),
                            "--static-root",
                            str(root),
                        ]
                    )

            self.assertEqual(status, 0)
            self.assertEqual(captured["sync_token"], "real-env-token")
            self.assertEqual(
                asset_center_runtime_config(captured["data_root"])["profile"], "local"
            )

    def test_mobile_deploy_readme_documents_local_cloud_profile_env_file(self) -> None:
        root = Path(__file__).resolve().parents[1]
        readme = (root / "third_party/mobile_deploy/README.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("python3.12 -m venv .venv-asset-center", readme)
        self.assertIn("python -m pip install -e '.[cloud]'", readme)
        self.assertIn("--env-file .env.asset.local-cloud", readme)
        self.assertIn("workbench.local.env.example", readme)

    def test_asset_center_cloud_profile_uses_standard_env_for_pg_and_oss(self) -> None:
        from third_party.mobile_asset_center.backend.mobile_asset_center.server import (
            asset_center_runtime_config,
        )

        env = {
            "ASSET_CENTER_PROFILE": "cloud",
            "ASSET_CENTER_DB_DSN": "postgresql://asset_user:secret@example.com:5432/assets",
            "ASSET_CENTER_STORAGE_PROVIDER": "aliyun_oss",
            "ALIYUN_OSS_BUCKET": "asset-bucket",
            "ALIYUN_OSS_ENDPOINT": "oss-cn-hangzhou.aliyuncs.com",
            "ALIYUN_OSS_ACCESS_KEY_ID": "ak",
            "ALIYUN_OSS_ACCESS_KEY_SECRET": "sk",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            config = asset_center_runtime_config(Path(temp_dir), env=env)

        self.assertEqual(config["profile"], "cloud")
        self.assertEqual(config["repository"], "postgres")
        self.assertEqual(config["storage"], "aliyun_oss")

    def test_cloud_ingest_writes_objects_metadata_and_scene_indexes(self) -> None:
        from third_party.mobile_asset_center.backend.mobile_asset_center.ingest import (
            ingest_bundle,
        )
        from third_party.mobile_asset_center.backend.mobile_asset_center.repository import (
            SqliteAssetCenterRepository,
        )
        from third_party.mobile_asset_center.backend.mobile_asset_center.storage import (
            FilesystemCloudStorage,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = SqliteAssetCenterRepository(root / "asset_center.sqlite3")
            storage = FilesystemCloudStorage(root / "objects", bucket="cloud-assets")
            bundle = {
                "bundleId": "bundle-1",
                "collectorId": "mac-01",
                "sourceImages": [
                    {
                        "id": "source-1",
                        "itemId": "sku",
                        "objectKey": "original/2026/05/source-1.jpg",
                        "category": "桌垫",
                        "scene": "餐桌布置",
                        "inputMode": "config_file",
                        "keyword": "红格桌垫",
                    }
                ],
                "assets": [
                    {
                        "assetId": "asset-1",
                        "sourceImageId": "source-1",
                        "assetType": "collected",
                        "objectKey": "collected/2026/05/asset-1.jpg",
                        "category": "桌垫",
                        "scene": "餐桌布置",
                        "sceneTags": ["餐桌布置", "买家秀实拍", "红白格"],
                        "query": "红格桌垫",
                        "stage": "image_search",
                        "rank": 1,
                        "contentSha256": "sha",
                        "mimeType": "image/jpeg",
                        "sizeBytes": 5,
                        "status": "available",
                        "sceneTagStatus": "tagged",
                    }
                ],
                "objects": [
                    {
                        "objectKey": "original/2026/05/source-1.jpg",
                        "contentType": "image/jpeg",
                        "contentBase64": base64.b64encode(b"ref").decode("ascii"),
                    },
                    {
                        "objectKey": "collected/2026/05/asset-1.jpg",
                        "contentType": "image/jpeg",
                        "contentBase64": base64.b64encode(b"asset").decode("ascii"),
                    },
                ],
            }

            summary = ingest_bundle(bundle, repository=repository, storage=storage)
            categories = repository.categories()
            scenes = repository.scenes(category="桌垫")
            assets = repository.search_assets(category="桌垫", scene="餐桌布置")

            self.assertEqual(summary["assets"], 2)
            self.assertEqual(categories[0]["category"], "桌垫")
            self.assertEqual(scenes[0]["scene"], "餐桌布置")
            self.assertEqual(scenes[0]["kind"], "primary")
            detail_scene = next(item for item in scenes if item["scene"] == "红白格")
            self.assertEqual(detail_scene["kind"], "detail")
            self.assertEqual(len(assets["assets"]), 2)
            self.assertEqual(
                {asset["assetType"] for asset in assets["assets"]},
                {"original", "collected"},
            )
            self.assertIn("/api/objects/cloud-assets/collected/2026/05/asset-1.jpg", json.dumps(assets, ensure_ascii=False))
            detail_assets = repository.search_assets(category="桌垫", scene="红白格")
            self.assertEqual(len(detail_assets["assets"]), 1)

    def test_cloud_ingest_deduplicates_same_hash_only_within_same_category(self) -> None:
        from third_party.mobile_asset_center.backend.mobile_asset_center.ingest import (
            ingest_bundle,
        )
        from third_party.mobile_asset_center.backend.mobile_asset_center.repository import (
            SqliteAssetCenterRepository,
        )
        from third_party.mobile_asset_center.backend.mobile_asset_center.storage import (
            FilesystemCloudStorage,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repository = SqliteAssetCenterRepository(root / "asset_center.sqlite3")
            storage = FilesystemCloudStorage(root / "objects", bucket="cloud-assets")
            bundle = {
                "bundleId": "bundle-duplicate",
                "collectorId": "mac-01",
                "sourceImages": [],
                "assets": [
                    {
                        "assetId": "asset-desk-1",
                        "sourceImageId": "source-1",
                        "assetType": "collected",
                        "objectKey": "collected/2026/05/asset-desk-1.jpg",
                        "category": "桌垫",
                        "scene": "餐桌布置",
                        "sceneTags": ["餐桌布置"],
                        "contentSha256": "same-sha",
                        "mimeType": "image/jpeg",
                        "status": "available",
                    },
                    {
                        "assetId": "asset-desk-2",
                        "sourceImageId": "source-2",
                        "assetType": "collected",
                        "objectKey": "collected/2026/05/asset-desk-2.jpg",
                        "category": "桌垫",
                        "scene": "买家秀实拍",
                        "sceneTags": ["买家秀实拍"],
                        "contentSha256": "same-sha",
                        "mimeType": "image/jpeg",
                        "status": "available",
                    },
                    {
                        "assetId": "asset-placemat-1",
                        "sourceImageId": "source-3",
                        "assetType": "collected",
                        "objectKey": "collected/2026/05/asset-placemat-1.jpg",
                        "category": "餐垫",
                        "scene": "餐桌布置",
                        "sceneTags": ["餐桌布置"],
                        "contentSha256": "same-sha",
                        "mimeType": "image/jpeg",
                        "status": "available",
                    },
                ],
                "objects": [
                    {
                        "objectKey": "collected/2026/05/asset-desk-1.jpg",
                        "contentType": "image/jpeg",
                        "contentBase64": base64.b64encode(b"one").decode("ascii"),
                    },
                    {
                        "objectKey": "collected/2026/05/asset-desk-2.jpg",
                        "contentType": "image/jpeg",
                        "contentBase64": base64.b64encode(b"two").decode("ascii"),
                    },
                    {
                        "objectKey": "collected/2026/05/asset-placemat-1.jpg",
                        "contentType": "image/jpeg",
                        "contentBase64": base64.b64encode(b"three").decode("ascii"),
                    },
                ],
            }

            summary = ingest_bundle(bundle, repository=repository, storage=storage)
            desk_assets = repository.search_assets(category="桌垫")
            placemat_assets = repository.search_assets(category="餐垫")

            self.assertEqual(summary["assets"], 3)
            self.assertEqual(summary["duplicates"], 1)
            self.assertEqual(len(desk_assets["assets"]), 1)
            self.assertEqual(len(placemat_assets["assets"]), 1)

            categories = {item["category"]: item["count"] for item in repository.categories()}
            self.assertEqual(categories["桌垫"], 1)
            self.assertEqual(categories["餐垫"], 1)

            desk_scenes = {item["scene"]: item["count"] for item in repository.scenes(category="桌垫")}
            self.assertEqual(desk_scenes, {"餐桌布置": 1})

    def test_postgres_scene_query_is_group_by_safe(self) -> None:
        from third_party.mobile_asset_center.backend.mobile_asset_center.repository import (
            PostgresAssetCenterRepository,
        )

        case = self

        class FakeResult:
            def __init__(self, rows=None):
                self.rows = rows or []
                self.rowcount = 0

            def fetchall(self):
                return self.rows

            def fetchone(self):
                return self.rows[0] if self.rows else None

        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql, params=None):
                if "SELECT t.tag AS scene" in sql:
                    case.assertIn("MIN(CASE WHEN t.tag = a.scene THEN 0 ELSE 1 END)", sql)
                return FakeResult([])

        fake_psycopg = types.ModuleType("psycopg")
        fake_psycopg.connect = lambda *args, **kwargs: FakeConnection()
        fake_rows = types.ModuleType("psycopg.rows")
        fake_rows.dict_row = object()

        with mock.patch.dict(
            sys.modules,
            {"psycopg": fake_psycopg, "psycopg.rows": fake_rows},
        ):
            repository = PostgresAssetCenterRepository("postgresql://example")

        self.assertEqual(repository.scenes(category="桌垫"), [])

    def test_query_param_decodes_raw_utf8_chinese_values(self) -> None:
        from third_party.mobile_asset_center.backend.mobile_asset_center.server import (
            _query_param,
        )

        raw_utf8_value = "桌垫".encode("utf-8").decode("latin-1")

        self.assertEqual(_query_param({"category": ["桌垫"]}, "category"), "桌垫")
        self.assertEqual(_query_param({"category": [raw_utf8_value]}, "category"), "桌垫")

    def test_cloud_agent_query_turns_business_text_into_asset_filters(self) -> None:
        from third_party.mobile_asset_center.backend.mobile_asset_center.agent import (
            answer_asset_query,
        )

        response = answer_asset_query(
            "找餐桌布置红格桌垫",
            categories=["桌垫", "餐垫"],
            scenes=["餐桌布置", "买家秀"],
        )

        self.assertEqual(response["filters"]["category"], "桌垫")
        self.assertEqual(response["filters"]["scene"], "餐桌布置")
        self.assertIn("红格", response["filters"]["q"])
        self.assertIn("已按", response["message"])

    def test_cloud_agent_query_uses_detail_scene_without_leaving_command_words(self) -> None:
        from third_party.mobile_asset_center.backend.mobile_asset_center.agent import (
            answer_asset_query,
        )

        response = answer_asset_query(
            "找红白格桌垫",
            categories=["桌垫", "餐垫"],
            scenes=["餐桌布置", "买家秀", "红白格"],
        )

        self.assertEqual(response["filters"]["category"], "桌垫")
        self.assertEqual(response["filters"]["scene"], "红白格")
        self.assertEqual(response["filters"]["q"], "")
        self.assertIn("已按", response["message"])

    def test_cloud_frontend_uses_two_column_category_and_asset_layout_without_agent_panel(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (
            root / "third_party/mobile_asset_center/frontend/index.html"
        ).read_text(encoding="utf-8")
        css = (
            root / "third_party/mobile_asset_center/frontend/styles.css"
        ).read_text(encoding="utf-8")
        js = (
            root / "third_party/mobile_asset_center/frontend/app.js"
        ).read_text(encoding="utf-8")

        self.assertIn("category-sidebar", html)
        self.assertIn("scene-filter-panel", html)
        self.assertIn("primarySceneTabs", html)
        self.assertIn("detailSceneTabs", html)
        self.assertIn("<title>场景素材中心</title>", html)
        self.assertIn("<span>场景素材中心</span>", html)
        self.assertIn("<h1>场景素材中心</h1>", html)
        self.assertNotIn("素材检索工作台", html)
        self.assertIn("主标签", html)
        self.assertIn("细分标签", html)
        self.assertIn("asset-feed", html)
        self.assertIn("原始素材", html)
        self.assertIn("抓取素材", html)
        self.assertNotIn("agent-panel", html)
        self.assertNotIn("Agent", html)
        self.assertNotIn("问素材中心", html)
        self.assertNotIn("agentInput", html)
        self.assertNotIn("agentButton", html)
        self.assertNotIn("agentAnswer", html)
        self.assertNotIn("右侧", html)
        self.assertNotIn("keywordInput", html)
        self.assertNotIn("searchButton", html)
        self.assertIn("activeFilterSummary", html)
        self.assertIn("/api/categories", js)
        self.assertIn("/api/scenes", js)
        self.assertIn("/api/assets", js)
        self.assertNotIn("/api/agent/query", js)
        self.assertNotIn("askAgent", js)
        self.assertNotIn("agentInput", js)
        self.assertNotIn("agentButton", js)
        self.assertNotIn("agentAnswer", js)
        self.assertNotIn("state.q", js)
        self.assertIn("primarySceneTabs", js)
        self.assertIn("detailSceneTabs", js)
        self.assertIn("appendSceneGroup", js)
        self.assertIn("scene-chip", js)
        self.assertIn("scene-count", js)
        self.assertIn("scene-kind-primary", js)
        self.assertIn("scene-kind-detail", js)
        self.assertIn("activeFilterSummary", js)
        self.assertIn("grid-template-columns", css)
        self.assertIn("grid-template-columns: 236px minmax(0, 1fr)", css)
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr))", css)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", css)
        self.assertNotIn("320px", css)
        self.assertNotIn(".agent-panel", css)
        self.assertNotIn(".agent-answer", css)
        self.assertIn("--color-action: #1f5d8c", css)
        self.assertIn("scene-filter-panel", css)
        self.assertIn("scene-group-header", css)
        self.assertIn("flex-wrap: wrap", css)
        self.assertIn("overflow-x: visible", css)
        self.assertIn("scene-chip", css)
        self.assertIn("scene-count", css)
        self.assertIn("scene-kind-primary", css)
        self.assertIn("scene-kind-detail", css)

    def test_cloud_frontend_filter_summary_has_no_agent_keyword_state(self) -> None:
        root = Path(__file__).resolve().parents[1]
        js = (
            root / "third_party/mobile_asset_center/frontend/app.js"
        ).read_text(encoding="utf-8")

        self.assertIn("当前筛选：", js)
        self.assertIn("state.category", js)
        self.assertIn("state.scene", js)
        self.assertIn("state.assetType", js)
        self.assertNotIn("关键词：", js)
        self.assertNotIn("filters?.q", js)


if __name__ == "__main__":
    unittest.main()
