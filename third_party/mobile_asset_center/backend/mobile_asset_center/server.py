from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .agent import answer_asset_query
from .ingest import ingest_bundle
from .repository import PostgresAssetCenterRepository, SqliteAssetCenterRepository
from .storage import AliyunOssStorage, FilesystemCloudStorage


class AssetCenterRequestHandler(BaseHTTPRequestHandler):
    repository: SqliteAssetCenterRepository
    storage: FilesystemCloudStorage
    static_root: Path
    sync_token: str = ""

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/health":
                self._send_json({"status": "ok"})
                return
            if parsed.path == "/api/categories":
                self._send_json({"categories": self.repository.categories()})
                return
            if parsed.path == "/api/scenes":
                params = parse_qs(parsed.query)
                self._send_json(
                    {
                        "scenes": self.repository.scenes(
                            category=(params.get("category") or [""])[0]
                        )
                    }
                )
                return
            if parsed.path == "/api/assets":
                params = parse_qs(parsed.query)
                self._send_json(
                    self.repository.search_assets(
                        category=(params.get("category") or [""])[0],
                        scene=(params.get("scene") or [""])[0],
                        q=(params.get("q") or params.get("query") or [""])[0],
                        asset_type=(params.get("assetType") or [""])[0],
                        cursor=(params.get("cursor") or [""])[0],
                        limit=int((params.get("limit") or ["40"])[0]),
                    )
                )
                return
            if parsed.path.startswith("/api/assets/"):
                parts = [unquote(part) for part in parsed.path.strip("/").split("/")]
                if len(parts) == 4 and parts[3] in {"image", "download"}:
                    key = self.repository.object_key_for_asset(parts[2])
                    self.send_response(HTTPStatus.FOUND)
                    self.send_header("Location", self.storage.presign_get_url(key))
                    self.end_headers()
                    return
            if parsed.path.startswith("/api/objects/"):
                parts = [unquote(part) for part in parsed.path.strip("/").split("/")]
                if len(parts) >= 4:
                    key = "/".join(parts[3:])
                    self._send_bytes(self.storage.read_bytes(key), "image/jpeg")
                    return
            self._serve_static(parsed.path)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/ingest/bundles":
                self._require_sync_token()
                self._send_json(
                    ingest_bundle(
                        self._read_json(),
                        repository=self.repository,
                        storage=self.storage,
                    ),
                    HTTPStatus.CREATED,
                )
                return
            if parsed.path == "/api/agent/query":
                payload = self._read_json()
                self._send_json(
                    answer_asset_query(
                        str(payload.get("query") or ""),
                        categories=[
                            item["category"] for item in self.repository.categories()
                        ],
                        scenes=[item["scene"] for item in self.repository.scenes()],
                    )
                )
                return
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _require_sync_token(self) -> None:
        if not self.sync_token:
            return
        expected = f"Bearer {self.sync_token}"
        if self.headers.get("Authorization") != expected:
            raise PermissionError("invalid sync token")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

    def _serve_static(self, path: str) -> None:
        target = self.static_root / ("index.html" if path in {"", "/"} else path.lstrip("/"))
        if not target.exists():
            target = self.static_root / "index.html"
        self._send_bytes(target.read_bytes(), _content_type(target))

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_bytes(self, payload: bytes, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def serve(
    *,
    host: str,
    port: int,
    data_root: Path,
    static_root: Path,
    sync_token: str = "",
) -> ThreadingHTTPServer:
    repository = _build_repository(data_root)
    storage = _build_storage(data_root)
    handler = type(
        "ConfiguredAssetCenterRequestHandler",
        (AssetCenterRequestHandler,),
        {
            "repository": repository,
            "storage": storage,
            "static_root": static_root,
            "sync_token": sync_token,
        },
    )
    return ThreadingHTTPServer((host, port), handler)


def _build_repository(data_root: Path):
    dsn = os.environ.get("ASSET_CENTER_DB_DSN", "").strip()
    if dsn:
        return PostgresAssetCenterRepository(dsn)
    return SqliteAssetCenterRepository(data_root / "asset_center.sqlite3")


def _build_storage(data_root: Path):
    provider = os.environ.get("ASSET_CENTER_STORAGE_PROVIDER", "filesystem").strip()
    if provider == "aliyun_oss":
        return AliyunOssStorage(
            bucket=os.environ["ALIYUN_OSS_BUCKET"],
            endpoint=os.environ["ALIYUN_OSS_ENDPOINT"],
            access_key_id=os.environ["ALIYUN_OSS_ACCESS_KEY_ID"],
            access_key_secret=os.environ["ALIYUN_OSS_ACCESS_KEY_SECRET"],
            url_expires_seconds=int(os.environ.get("ASSET_CENTER_URL_EXPIRES_SECONDS", "3600")),
        )
    return FilesystemCloudStorage(data_root / "objects", bucket="cloud-assets")


def _content_type(path: Path) -> str:
    if path.suffix == ".css":
        return "text/css; charset=utf-8"
    if path.suffix == ".js":
        return "application/javascript; charset=utf-8"
    return "text/html; charset=utf-8"
