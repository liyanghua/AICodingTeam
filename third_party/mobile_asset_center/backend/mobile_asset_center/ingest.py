from __future__ import annotations

import base64
from typing import Any


def ingest_bundle(bundle: dict[str, Any], *, repository: Any, storage: Any) -> dict[str, int]:
    collector_id = str(bundle.get("collectorId") or "")
    bundle_id = str(bundle.get("bundleId") or "")
    if not collector_id:
        raise ValueError("collectorId is required")
    if not bundle_id:
        raise ValueError("bundleId is required")
    repository.upsert_collector(collector_id)
    repository.upsert_ingest_batch(bundle_id, collector_id)

    object_content_types: dict[str, str] = {}
    for obj in bundle.get("objects", []):
        key = str(obj.get("objectKey") or "")
        payload = base64.b64decode(str(obj.get("contentBase64") or ""))
        content_type = str(obj.get("contentType") or "application/octet-stream")
        storage.put_bytes(key, payload, content_type=content_type)
        object_content_types[key] = content_type

    source_count = 0
    asset_count = 0
    duplicate_count = 0
    for source in bundle.get("sourceImages", []):
        if repository.upsert_source_image(source):
            source_count += 1
        original_key = str(source.get("objectKey") or "")
        if original_key:
            original_asset = {
                "assetId": f"original-{source['id']}",
                "sourceImageId": source["id"],
                "assetType": "original",
                "objectKey": original_key,
                "category": source.get("category", ""),
                "scene": source.get("scene", ""),
                "sceneTags": [source.get("scene", "")] if source.get("scene") else [],
                "query": source.get("keyword", ""),
                "stage": "original",
                "rank": None,
                "mimeType": object_content_types.get(original_key, "image/jpeg"),
                "status": "available",
                "sceneTagStatus": "tagged" if source.get("scene") else "missing",
            }
            if repository.upsert_asset(original_asset):
                asset_count += 1

    for asset in bundle.get("assets", []):
        normalized_asset = dict(asset)
        duplicate_of = _find_duplicate_asset_id(repository, normalized_asset)
        if duplicate_of:
            normalized_asset["status"] = "duplicate"
            duplicate_count += 1
        if repository.upsert_asset(normalized_asset):
            asset_count += 1

    return {
        "sourceImages": source_count,
        "assets": asset_count,
        "objects": len(bundle.get("objects", [])),
        "duplicates": duplicate_count,
    }


def _find_duplicate_asset_id(repository: Any, asset: dict[str, Any]) -> str:
    finder = getattr(repository, "find_available_asset_by_hash", None)
    if not callable(finder):
        return ""
    return str(
        finder(
            str(asset.get("contentSha256") or ""),
            category=str(asset.get("category") or ""),
            exclude_asset_id=str(asset.get("assetId") or ""),
        )
        or ""
    )
