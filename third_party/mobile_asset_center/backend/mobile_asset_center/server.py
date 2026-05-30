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
                            category=_query_param(params, "category")
                        )
                    }
                )
                return
            if parsed.path == "/api/assets":
                params = parse_qs(parsed.query)
                self._send_json(
                    self.repository.search_assets(
                        category=_query_param(params, "category"),
                        scene=_query_param(params, "scene"),
                        q=_query_param(params, "q", "query"),
                        asset_type=_query_param(params, "assetType"),
                        cursor=_query_param(params, "cursor"),
                        limit=int(_query_param(params, "limit", default="40")),
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


def asset_center_runtime_config(
    data_root: Path, *, env: dict[str, str] | None = None
) -> dict[str, str]:
    values = os.environ if env is None else env
    profile = values.get("ASSET_CENTER_PROFILE", "local").strip() or "local"
    if profile not in {"local", "cloud"}:
        raise ValueError("ASSET_CENTER_PROFILE must be local or cloud")
    if profile == "local":
        return {
            "profile": "local",
            "repository": "sqlite",
            "storage": "filesystem",
            "database_path": str(data_root / "asset_center.sqlite3"),
            "objects_root": str(data_root / "objects"),
        }
    _require_env(
        values,
        [
            "ASSET_CENTER_DB_DSN",
            "ALIYUN_OSS_BUCKET",
            "ALIYUN_OSS_ENDPOINT",
            "ALIYUN_OSS_ACCESS_KEY_ID",
            "ALIYUN_OSS_ACCESS_KEY_SECRET",
        ],
    )
    storage_provider = values.get("ASSET_CENTER_STORAGE_PROVIDER", "aliyun_oss").strip()
    if storage_provider != "aliyun_oss":
        raise ValueError("cloud profile requires ASSET_CENTER_STORAGE_PROVIDER=aliyun_oss")
    return {
        "profile": "cloud",
        "repository": "postgres",
        "storage": "aliyun_oss",
        "dsn": values["ASSET_CENTER_DB_DSN"],
        "bucket": values["ALIYUN_OSS_BUCKET"],
        "endpoint": values["ALIYUN_OSS_ENDPOINT"],
    }


def _build_repository(data_root: Path):
    config = asset_center_runtime_config(data_root)
    if config["repository"] == "postgres":
        return PostgresAssetCenterRepository(config["dsn"])
    return SqliteAssetCenterRepository(data_root / "asset_center.sqlite3")


def _build_storage(data_root: Path):
    config = asset_center_runtime_config(data_root)
    if config["storage"] == "aliyun_oss":
        return AliyunOssStorage(
            bucket=os.environ["ALIYUN_OSS_BUCKET"],
            endpoint=os.environ["ALIYUN_OSS_ENDPOINT"],
            access_key_id=os.environ["ALIYUN_OSS_ACCESS_KEY_ID"],
            access_key_secret=os.environ["ALIYUN_OSS_ACCESS_KEY_SECRET"],
            url_expires_seconds=int(os.environ.get("ASSET_CENTER_URL_EXPIRES_SECONDS", "3600")),
        )
    return FilesystemCloudStorage(data_root / "objects", bucket="cloud-assets")


def _require_env(values: dict[str, str] | os._Environ[str], names: list[str]) -> None:
    missing = [name for name in names if not values.get(name, "").strip()]
    if missing:
        raise ValueError(f"missing required cloud config: {', '.join(missing)}")


def _query_param(params: dict[str, list[str]], *names: str, default: str = "") -> str:
    for name in names:
        values = params.get(name)
        if values:
            return _decode_query_value(values[0])
    return default


def _decode_query_value(value: str) -> str:
    if not value:
        return ""
    try:
        return value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def _content_type(path: Path) -> str:
    if path.suffix == ".css":
        return "text/css; charset=utf-8"
    if path.suffix == ".js":
        return "application/javascript; charset=utf-8"
    return "text/html; charset=utf-8"
