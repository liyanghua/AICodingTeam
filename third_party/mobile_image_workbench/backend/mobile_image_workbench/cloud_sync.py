from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .asset_library import AssetLibrary
from .storage import FilesystemObjectStorageClient


def build_local_asset_library(runs_root: Path) -> AssetLibrary:
    return AssetLibrary(
        runs_root / "asset_center.sqlite3",
        FilesystemObjectStorageClient(
            runs_root / "object_storage",
            bucket="mobile-image-assets",
        ),
    )


def sync_cloud_bundle(
    *,
    runs_root: Path,
    server_url: str,
    token: str,
    collector_id: str,
    category: str = "",
    batch_size: int = 100,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    library = build_local_asset_library(runs_root)
    bundle = library.export_cloud_bundle(
        collector_id=collector_id,
        category=category,
        limit=batch_size,
    )
    endpoint = f"{server_url.rstrip('/')}/api/ingest/bundles"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(bundle, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"cloud sync failed: HTTP {exc.code} {message}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"cloud sync failed: {exc}") from exc
