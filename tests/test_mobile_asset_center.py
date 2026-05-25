from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path


class MobileAssetCenterTests(unittest.TestCase):
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

    def test_cloud_frontend_uses_category_sidebar_scene_tabs_feed_and_agent_panel(self) -> None:
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
        self.assertIn("主标签", html)
        self.assertIn("细分标签", html)
        self.assertIn("asset-feed", html)
        self.assertIn("agent-panel", html)
        self.assertIn("原始素材", html)
        self.assertIn("抓取素材", html)
        self.assertNotIn("keywordInput", html)
        self.assertNotIn("searchButton", html)
        self.assertIn("activeFilterSummary", html)
        self.assertIn("/api/categories", js)
        self.assertIn("/api/scenes", js)
        self.assertIn("/api/assets", js)
        self.assertIn("/api/agent/query", js)
        self.assertIn("primarySceneTabs", js)
        self.assertIn("detailSceneTabs", js)
        self.assertIn("appendSceneGroup", js)
        self.assertIn("scene-chip", js)
        self.assertIn("scene-count", js)
        self.assertIn("scene-kind-primary", js)
        self.assertIn("scene-kind-detail", js)
        self.assertIn("activeFilterSummary", js)
        self.assertIn("grid-template-columns", css)
        self.assertIn("--color-action: #1f5d8c", css)
        self.assertIn("scene-filter-panel", css)
        self.assertIn("scene-group-header", css)
        self.assertIn("flex-wrap: wrap", css)
        self.assertIn("overflow-x: visible", css)
        self.assertIn("scene-chip", css)
        self.assertIn("scene-count", css)
        self.assertIn("scene-kind-primary", css)
        self.assertIn("scene-kind-detail", css)

    def test_cloud_frontend_keeps_agent_query_failures_recoverable(self) -> None:
        root = Path(__file__).resolve().parents[1]
        js = (
            root / "third_party/mobile_asset_center/frontend/app.js"
        ).read_text(encoding="utf-8")

        self.assertIn("try {", js)
        self.assertIn("catch (error)", js)
        self.assertIn("finally {", js)
        self.assertIn("查询失败，请调整描述后重试。", js)
        self.assertIn("state.loading = false;", js)


if __name__ == "__main__":
    unittest.main()
