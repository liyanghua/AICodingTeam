from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class ReferenceAppIndexTests(unittest.TestCase):
    def _make_reference_app(self, root: Path) -> Path:
        ref = root / "reference_app"
        (ref / "src" / "server").mkdir(parents=True)
        (ref / "public").mkdir(parents=True)
        (ref / "tests").mkdir(parents=True)

        (ref / "package.json").write_text("{\"name\": \"ref\"}\n", encoding="utf-8")
        (ref / "README.md").write_text("# Ref\n", encoding="utf-8")

        server_js = (
            "import { generateImageFromProvider } from './image-provider.js';\n"
            "export function createServer() {\n"
            "  return createHttpServer(async (request, response) => {\n"
            "    const url = new URL(request.url);\n"
            "    if (request.method === 'POST' && url.pathname === '/api/images/generate') {\n"
            "      // handle\n"
            "    }\n"
            "    if (request.url === '/api/health') {\n"
            "      // health\n"
            "    }\n"
            "  });\n"
            "}\n"
        )
        (ref / "src" / "server" / "server.js").write_text(server_js, encoding="utf-8")

        provider_js = (
            "export function resolveImageProviderConfig(env) { return { provider: 'openai' }; }\n"
            "export async function generateImageFromProvider(input) { return null; }\n"
        )
        (ref / "src" / "server" / "image-provider.js").write_text(provider_js, encoding="utf-8")

        legacy_js = (
            "function helperA() {}\n"
            "function helperB() {}\n"
            "module.exports = {\n"
            "  helperA,\n"
            "  helperB,\n"
            "  helperC: () => 1,\n"
            "};\n"
        )
        (ref / "src" / "server" / "legacy.js").write_text(legacy_js, encoding="utf-8")

        express_js = (
            "const app = express();\n"
            "app.get('/api/items', (req, res) => res.send([]));\n"
            "app.post('/api/items', (req, res) => res.send({}));\n"
            "router.delete('/api/items/:id', (req, res) => res.send({}));\n"
        )
        (ref / "src" / "server" / "express-style.js").write_text(express_js, encoding="utf-8")

        (ref / "public" / "index.html").write_text("<html>产品图 参考图</html>\n", encoding="utf-8")
        (ref / "public" / "app.js").write_text(
            "exports.downloadImage = function() {};\n", encoding="utf-8"
        )
        (ref / "tests" / "core.test.js").write_text(
            "test('ok', () => {});\n", encoding="utf-8"
        )
        return ref

    def test_build_reference_app_index_routes_exports_and_tree(self) -> None:
        from growth_dev.team.reference_index import build_reference_app_index

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ref = self._make_reference_app(root)
            capabilities = [
                {
                    "id": "image_provider_proxy",
                    "label": "image provider",
                    "evidence": ["/api/images/generate", "openai"],
                },
                {
                    "id": "image_download",
                    "label": "image download",
                    "detection": {"match_any": ["downloadImage"]},
                },
                {
                    "id": "product_image_upload",
                    "label": "产品图上传",
                    "evidence": ["产品图"],
                },
            ]
            payload = build_reference_app_index(ref, capabilities)

        self.assertEqual(payload["schema_version"], 1)
        self.assertIn("package.json", payload["file_tree"])
        self.assertIn("src/server/server.js", payload["file_tree"])
        self.assertIn("public/index.html", payload["file_tree"])
        for rel in payload["file_tree"]:
            self.assertLessEqual(len(Path(rel).parts), 3)

        route_paths = {(r["method"], r["path"]) for r in payload["server_routes"]}
        self.assertIn(("GET", "/api/items"), route_paths)
        self.assertIn(("POST", "/api/items"), route_paths)
        self.assertIn(("DELETE", "/api/items/:id"), route_paths)
        self.assertIn(("ANY", "/api/health"), route_paths)
        self.assertIn(("ANY", "/api/images/generate"), route_paths)

        exports_by_file = {entry["file"]: entry["symbols"] for entry in payload["key_exports"]}
        self.assertIn("createServer", exports_by_file.get("src/server/server.js", []))
        self.assertIn("resolveImageProviderConfig", exports_by_file.get("src/server/image-provider.js", []))
        self.assertIn("generateImageFromProvider", exports_by_file.get("src/server/image-provider.js", []))
        legacy_symbols = exports_by_file.get("src/server/legacy.js", [])
        self.assertIn("helperA", legacy_symbols)
        self.assertIn("helperC", legacy_symbols)
        self.assertIn("downloadImage", exports_by_file.get("public/app.js", []))

        capability_map = {item["capability_id"]: item["files"] for item in payload["capability_to_files"]}
        self.assertIn("src/server/server.js", capability_map["image_provider_proxy"])
        self.assertIn("public/app.js", capability_map["image_download"])
        self.assertIn("public/index.html", capability_map["product_image_upload"])

    def test_render_markdown_stays_under_budget(self) -> None:
        from growth_dev.team.reference_index import (
            MD_BUDGET_CHARS,
            build_reference_app_index,
            render_reference_app_index_markdown,
        )

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ref = self._make_reference_app(root)
            payload = build_reference_app_index(ref, [])
            text = render_reference_app_index_markdown(payload)

        self.assertTrue(text.startswith("# Reference App Index"))
        self.assertLessEqual(len(text), MD_BUDGET_CHARS + 200)
        self.assertNotIn("function createServer", text)
        self.assertNotIn("module.exports", text)

    def test_write_reference_app_index_artifacts_produces_both_files(self) -> None:
        from growth_dev.team.reference_index import (
            INDEX_JSON_NAME,
            INDEX_MD_NAME,
            build_reference_app_index,
            write_reference_app_index_artifacts,
        )

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ref = self._make_reference_app(root)
            out = root / "run"
            payload = build_reference_app_index(ref, [])
            json_path, md_path = write_reference_app_index_artifacts(out, payload)
            self.assertEqual(json_path.name, INDEX_JSON_NAME)
            self.assertEqual(md_path.name, INDEX_MD_NAME)
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["schema_version"], 1)
            self.assertIn("# Reference App Index", md_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()