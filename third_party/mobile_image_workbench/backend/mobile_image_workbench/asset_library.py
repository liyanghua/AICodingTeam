from __future__ import annotations

import datetime as dt
import base64
import hashlib
import json
import mimetypes
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .storage import FilesystemObjectStorageClient


ASSET_NAMESPACE = uuid.UUID("39541d8a-c0f8-4d27-95c2-b28f5f4d4f63")


@dataclass(frozen=True)
class AssetBlob:
    payload: bytes
    content_type: str
    filename: str


class AssetLibrary:
    def __init__(
        self,
        database_path: Path,
        storage: FilesystemObjectStorageClient,
    ) -> None:
        self.database_path = database_path
        self.storage = storage
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def ingest_run(
        self,
        run_dir: Path,
        *,
        job_id: str = "",
        category: str = "",
        scene: str = "",
        input_mode: str = "",
        uploaded_by: str = "",
    ) -> dict[str, int]:
        run_dir = run_dir.resolve()
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"manifest not found: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        run_id = str(manifest.get("run_id") or run_dir.name)
        default_category = (
            category
            or str(((manifest.get("config") or {}).get("target_category") or "")).strip()
        )
        counts = {"source_images": 0, "assets": 0, "duplicates": 0}
        with self._connect() as conn:
            for result in manifest.get("results", []):
                item_id = str(result.get("item_id") or "").strip()
                if not item_id:
                    continue
                keyword = str(result.get("keyword") or "")
                source_scene = scene or keyword
                source_id = _stable_id("source", run_id, item_id)
                original_path = _find_reference_image(run_dir, item_id)
                original_key = ""
                if original_path:
                    original_key = _object_key(
                        "original",
                        source_id,
                        original_path.suffix or ".jpg",
                    )
                    self.storage.put_object(
                        original_key,
                        original_path,
                        content_type=_guess_content_type(original_path.name),
                    )
                if self._insert_source_image(
                    conn,
                    source_id=source_id,
                    job_id=job_id,
                    run_id=run_id,
                    item_id=item_id,
                    original_object_key=original_key,
                    category=default_category,
                    scene=source_scene,
                    input_mode=input_mode,
                    keyword=keyword,
                    uploaded_by=uploaded_by,
                ):
                    counts["source_images"] += 1
                for image in result.get("images", []):
                    local_path = _local_image_path(run_dir, str(image.get("local_path") or ""))
                    if local_path is None or not local_path.exists() or not local_path.is_file():
                        continue
                    content_sha256 = _sha256_file(local_path)
                    duplicate_of = self._find_available_asset_by_hash(
                        conn, content_sha256, category=default_category
                    )
                    status = "duplicate" if duplicate_of else "available"
                    asset_id = _stable_id(
                        "asset",
                        run_id,
                        item_id,
                        str(image.get("stage") or "image_search"),
                        str(image.get("rank") or ""),
                        str(image.get("keyword_index") or ""),
                        str(image.get("query") or ""),
                        local_path.name,
                    )
                    object_key = _object_key(
                        "collected",
                        asset_id,
                        local_path.suffix or ".jpg",
                    )
                    metadata = self.storage.put_object(
                        object_key,
                        local_path,
                        content_type=_guess_content_type(local_path.name),
                    )
                    if self._insert_asset(
                        conn,
                        asset_id=asset_id,
                        source_image_id=source_id,
                        object_key=object_key,
                        category=default_category,
                        scene=source_scene,
                        query=str(image.get("query") or ""),
                        keyword_index=_optional_int(image.get("keyword_index")),
                        stage=str(image.get("stage") or "image_search"),
                        rank=_optional_int(image.get("rank")),
                        content_sha256=content_sha256,
                        phash=content_sha256[:16],
                        width=None,
                        height=None,
                        mime_type=metadata.content_type,
                        size_bytes=metadata.size_bytes,
                        status=status,
                        duplicate_of_asset_id=duplicate_of,
                        filename=local_path.name,
                    ):
                        counts["assets"] += 1
                        if duplicate_of:
                            counts["duplicates"] += 1
                        self._insert_tags(
                            conn,
                            asset_id,
                            _asset_tags(default_category, source_scene, image),
                        )
            conn.commit()
        return counts

    def search_assets(
        self,
        *,
        category: str = "",
        scene: str = "",
        query: str = "",
        stage: str = "",
        status: str = "available",
        source_image_id: str = "",
        limit: int = 80,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if category:
            clauses.append("a.category LIKE ?")
            params.append(f"%{category}%")
        if scene:
            clauses.append("a.scene LIKE ?")
            params.append(f"%{scene}%")
        if query:
            clauses.append("a.search_text LIKE ?")
            params.append(f"%{query}%")
        if stage:
            clauses.append("a.stage = ?")
            params.append(stage)
        if status:
            clauses.append("a.status = ?")
            params.append(status)
        if source_image_id:
            clauses.append("a.source_image_id = ?")
            params.append(source_image_id)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                  a.*, s.item_id, s.original_object_key, s.keyword AS source_keyword
                FROM assets a
                JOIN source_images s ON s.id = a.source_image_id
                {where}
                ORDER BY a.created_at DESC, a.rank ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._asset_payload(row) for row in rows]

    def scene_tag_candidates(
        self,
        *,
        category: str = "",
        run_id: str = "",
        job_id: str = "",
        limit: int = 100,
        retry_failed: bool = False,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        clauses = ["1 = 1"] if force else ["a.scene_tag_status != 'tagged'"]
        params: list[Any] = []
        if not retry_failed:
            clauses.append("a.scene_tag_status != 'failed'")
        if category:
            clauses.append("a.category LIKE ?")
            params.append(f"%{category}%")
        if run_id:
            clauses.append("s.run_id = ?")
            params.append(run_id)
        if job_id:
            clauses.append("s.job_id = ?")
            params.append(job_id)
        params.append(max(1, min(int(limit), 1000)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                  a.id, a.object_key, a.category, a.scene, a.query, a.stage,
                  a.rank, a.content_sha256, a.mime_type, a.filename,
                  a.scene_tag_status, s.keyword AS source_keyword, s.run_id,
                  s.job_id
                FROM assets a
                JOIN source_images s ON s.id = a.source_image_id
                WHERE {" AND ".join(clauses)}
                ORDER BY a.created_at ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            {
                "assetId": str(row["id"]),
                "objectKey": str(row["object_key"]),
                "category": str(row["category"] or ""),
                "scene": str(row["scene"] or ""),
                "query": str(row["query"] or ""),
                "stage": str(row["stage"] or ""),
                "rank": row["rank"],
                "contentSha256": str(row["content_sha256"] or ""),
                "mimeType": str(row["mime_type"] or "application/octet-stream"),
                "filename": str(row["filename"] or ""),
                "sceneTagStatus": str(row["scene_tag_status"] or "missing"),
                "sourceKeyword": str(row["source_keyword"] or ""),
                "runId": str(row["run_id"] or ""),
                "jobId": str(row["job_id"] or ""),
            }
            for row in rows
        ]

    def apply_scene_tags(
        self,
        asset_id: str,
        scene_tags: list[str],
        *,
        model: str,
        prompt_version: str,
        raw_response: dict[str, Any] | None = None,
        status: str = "tagged",
    ) -> None:
        tags = _normalize_scene_tags(scene_tags)
        primary_scene = tags[0] if tags else "未识别场景"
        status_value = status if status in {"missing", "pending", "tagged", "failed"} else "tagged"
        with self._connect() as conn:
            row = conn.execute(
                "SELECT category, query, stage, filename, content_sha256 FROM assets WHERE id = ?",
                (asset_id,),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(f"asset not found: {asset_id}")
            conn.execute(
                "DELETE FROM asset_tags WHERE asset_id = ? AND tag_type = 'scene'",
                (asset_id,),
            )
            self._insert_tags(conn, asset_id, [(tag, "scene") for tag in tags])
            search_text = _join_search_text(
                row["category"],
                primary_scene,
                row["query"],
                row["stage"],
                row["filename"],
                row["content_sha256"],
                *tags,
            )
            conn.execute(
                """
                UPDATE assets
                SET scene = ?, scene_tag_status = ?, scene_tag_model = ?,
                    scene_tag_prompt_version = ?, scene_tagged_at = ?,
                    search_text = ?
                WHERE id = ?
                """,
                (
                    primary_scene,
                    status_value,
                    model,
                    prompt_version,
                    _now(),
                    search_text,
                    asset_id,
                ),
            )
            self._save_scene_annotation(
                conn,
                content_sha256=str(row["content_sha256"] or ""),
                model=model,
                prompt_version=prompt_version,
                scene_tags=tags,
                raw_response=raw_response or {"scene_tags": tags},
            )
            conn.commit()

    def mark_scene_tag_failed(
        self,
        asset_id: str,
        *,
        model: str,
        prompt_version: str,
        reason: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE assets
                SET scene_tag_status = 'failed', scene_tag_model = ?,
                    scene_tag_prompt_version = ?, scene_tagged_at = ?
                WHERE id = ?
                """,
                (model, prompt_version, _now(), asset_id),
            )
            conn.commit()

    def cached_scene_tags(
        self, content_sha256: str, *, model: str, prompt_version: str
    ) -> list[str] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT scene_tags FROM asset_vision_annotations
                WHERE content_sha256 = ? AND model = ? AND prompt_version = ?
                """,
                (content_sha256, model, prompt_version),
            ).fetchone()
        if row is None:
            return None
        try:
            tags = json.loads(str(row["scene_tags"] or "[]"))
        except json.JSONDecodeError:
            return None
        return _normalize_scene_tags(tags)

    def asset_image_bytes(self, asset_id: str) -> bytes:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT object_key FROM assets WHERE id = ?",
                (asset_id,),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(f"asset not found: {asset_id}")
        return self.storage.read_object(str(row["object_key"]))

    def asset_local_path(self, asset_id: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT object_key FROM assets WHERE id = ?",
                (asset_id,),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(f"asset not found: {asset_id}")
        local_path_for_key = getattr(self.storage, "local_path_for_key", None)
        if not callable(local_path_for_key):
            return ""
        return str(local_path_for_key(str(row["object_key"])))

    def export_cloud_bundle(
        self,
        *,
        collector_id: str,
        category: str = "",
        limit: int = 100,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            clauses = ["a.status IN ('available', 'duplicate')"]
            params: list[Any] = []
            if category:
                clauses.append("a.category LIKE ?")
                params.append(f"%{category}%")
            params.append(max(1, min(int(limit), 1000)))
            rows = conn.execute(
                f"""
                SELECT
                  a.*, s.id AS source_id, s.item_id, s.original_object_key,
                  s.category AS source_category, s.scene AS source_scene,
                  s.input_mode, s.keyword AS source_keyword
                FROM assets a
                JOIN source_images s ON s.id = a.source_image_id
                WHERE {" AND ".join(clauses)}
                ORDER BY a.created_at ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
            source_ids = sorted({str(row["source_id"]) for row in rows})
            sources = [
                conn.execute(
                    "SELECT * FROM source_images WHERE id = ?",
                    (source_id,),
                ).fetchone()
                for source_id in source_ids
            ]
        objects: list[dict[str, Any]] = []
        seen_object_keys: set[str] = set()

        def add_object(key: str, content_type: str) -> None:
            if not key or key in seen_object_keys:
                return
            seen_object_keys.add(key)
            objects.append(
                {
                    "objectKey": key,
                    "contentType": content_type,
                    "contentBase64": base64.b64encode(self.storage.read_object(key)).decode("ascii"),
                }
            )

        source_payloads: list[dict[str, Any]] = []
        first_asset_scene_by_source = {
            str(row["source_id"]): str(row["scene"] or "")
            for row in rows
            if str(row["scene"] or "")
        }
        for source in sources:
            if source is None:
                continue
            original_key = str(source["original_object_key"] or "")
            source_scene = str(source["scene"] or "") or first_asset_scene_by_source.get(
                str(source["id"]), ""
            )
            if original_key:
                add_object(original_key, self.storage.head_object(original_key).content_type)
            source_payloads.append(
                {
                    "id": str(source["id"]),
                    "itemId": str(source["item_id"] or ""),
                    "objectKey": original_key,
                    "category": str(source["category"] or ""),
                    "scene": source_scene,
                    "inputMode": str(source["input_mode"] or ""),
                    "keyword": str(source["keyword"] or ""),
                }
            )

        asset_payloads: list[dict[str, Any]] = []
        for row in rows:
            object_key = str(row["object_key"] or "")
            add_object(object_key, str(row["mime_type"] or _guess_content_type(object_key)))
            scene_tags = self._scene_tags_for_asset(str(row["id"]))
            asset_payloads.append(
                {
                    "assetId": str(row["id"]),
                    "sourceImageId": str(row["source_image_id"]),
                    "assetType": "collected",
                    "objectKey": object_key,
                    "category": str(row["category"] or ""),
                    "scene": str(row["scene"] or ""),
                    "sceneTags": scene_tags,
                    "query": str(row["query"] or ""),
                    "keywordIndex": row["keyword_index"],
                    "stage": str(row["stage"] or ""),
                    "rank": row["rank"],
                    "contentSha256": str(row["content_sha256"] or ""),
                    "phash": str(row["phash"] or ""),
                    "mimeType": str(row["mime_type"] or _guess_content_type(object_key)),
                    "sizeBytes": int(row["size_bytes"] or 0),
                    "status": str(row["status"] or "available"),
                    "sceneTagStatus": str(row["scene_tag_status"] or "missing"),
                    "sceneTagModel": str(row["scene_tag_model"] or ""),
                    "sceneTagPromptVersion": str(row["scene_tag_prompt_version"] or ""),
                    "filename": str(row["filename"] or Path(object_key).name),
                }
            )

        return {
            "bundleId": f"{collector_id}-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%S%fZ')}",
            "collectorId": collector_id,
            "sourceImages": source_payloads,
            "assets": asset_payloads,
            "objects": objects,
        }

    def search_payload(self, filters: dict[str, Any]) -> dict[str, Any]:
        assets = self.search_assets(
            category=str(filters.get("category") or ""),
            scene=str(filters.get("scene") or ""),
            query=str(filters.get("query") or ""),
            stage=str(filters.get("stage") or ""),
            status=str(filters.get("status") or "available"),
            source_image_id=str(filters.get("sourceImageId") or filters.get("source_image_id") or ""),
            limit=int(filters.get("limit") or 80),
        )
        return {"total": len(assets), "assets": assets}

    def read_asset_blob(self, asset_id: str) -> AssetBlob:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT object_key, mime_type, filename FROM assets WHERE id = ?",
                (asset_id,),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(f"asset not found: {asset_id}")
        return AssetBlob(
            payload=self.storage.read_object(str(row["object_key"])),
            content_type=str(row["mime_type"] or "application/octet-stream"),
            filename=str(row["filename"] or Path(str(row["object_key"])).name),
        )

    def read_object_blob(self, bucket: str, key: str) -> AssetBlob:
        if bucket != self.storage.bucket:
            raise FileNotFoundError(f"bucket not found: {bucket}")
        metadata = self.storage.head_object(key)
        if not metadata.exists:
            raise FileNotFoundError(f"object not found: {key}")
        return AssetBlob(
            payload=self.storage.read_object(key),
            content_type=metadata.content_type,
            filename=Path(key).name,
        )

    def _asset_payload(self, row: sqlite3.Row) -> dict[str, Any]:
        asset_id = str(row["id"])
        return {
            "assetId": asset_id,
            "sourceImageId": row["source_image_id"],
            "objectKey": row["object_key"],
            "thumbObjectKey": row["thumb_object_key"],
            "category": row["category"],
            "scene": row["scene"],
            "sceneTags": self._scene_tags_for_asset(asset_id),
            "query": row["query"],
            "keywordIndex": row["keyword_index"],
            "stage": row["stage"],
            "rank": row["rank"],
            "contentSha256": row["content_sha256"],
            "phash": row["phash"],
            "width": row["width"],
            "height": row["height"],
            "mimeType": row["mime_type"],
            "sizeBytes": row["size_bytes"],
            "status": row["status"],
            "assetType": "collected",
            "sceneTagStatus": row["scene_tag_status"],
            "sceneTagModel": row["scene_tag_model"],
            "sceneTagPromptVersion": row["scene_tag_prompt_version"],
            "sceneTaggedAt": row["scene_tagged_at"],
            "duplicateOfAssetId": row["duplicate_of_asset_id"],
            "imageUrl": f"/api/library/assets/{asset_id}/image",
            "downloadUrl": f"/api/library/assets/{asset_id}/download",
            "sourceImage": {
                "itemId": row["item_id"],
                "originalObjectKey": row["original_object_key"],
                "keyword": row["source_keyword"],
            },
        }

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS source_images (
                  id TEXT PRIMARY KEY,
                  job_id TEXT NOT NULL DEFAULT '',
                  run_id TEXT NOT NULL DEFAULT '',
                  item_id TEXT NOT NULL DEFAULT '',
                  original_object_key TEXT NOT NULL DEFAULT '',
                  category TEXT NOT NULL DEFAULT '',
                  scene TEXT NOT NULL DEFAULT '',
                  input_mode TEXT NOT NULL DEFAULT '',
                  keyword TEXT NOT NULL DEFAULT '',
                  uploaded_by TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL,
                  search_text TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS assets (
                  id TEXT PRIMARY KEY,
                  source_image_id TEXT NOT NULL,
                  object_key TEXT NOT NULL,
                  thumb_object_key TEXT NOT NULL DEFAULT '',
                  category TEXT NOT NULL DEFAULT '',
                  scene TEXT NOT NULL DEFAULT '',
                  query TEXT NOT NULL DEFAULT '',
                  keyword_index INTEGER,
                  stage TEXT NOT NULL DEFAULT '',
                  rank INTEGER,
                  content_sha256 TEXT NOT NULL DEFAULT '',
                  phash TEXT NOT NULL DEFAULT '',
                  width INTEGER,
                  height INTEGER,
                  mime_type TEXT NOT NULL DEFAULT '',
                  size_bytes INTEGER NOT NULL DEFAULT 0,
                  status TEXT NOT NULL DEFAULT 'available',
                  duplicate_of_asset_id TEXT,
                  filename TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL,
                  scene_tag_status TEXT NOT NULL DEFAULT 'missing',
                  scene_tag_model TEXT NOT NULL DEFAULT '',
                  scene_tag_prompt_version TEXT NOT NULL DEFAULT '',
                  scene_tagged_at TEXT NOT NULL DEFAULT '',
                  search_text TEXT NOT NULL DEFAULT '',
                  FOREIGN KEY(source_image_id) REFERENCES source_images(id)
                );

                CREATE INDEX IF NOT EXISTS idx_assets_filters
                  ON assets(category, scene, stage, status);
                CREATE INDEX IF NOT EXISTS idx_assets_sha
                  ON assets(content_sha256, status);
                CREATE INDEX IF NOT EXISTS idx_assets_search_text
                  ON assets(search_text);

                CREATE TABLE IF NOT EXISTS asset_tags (
                  asset_id TEXT NOT NULL,
                  tag TEXT NOT NULL,
                  tag_type TEXT NOT NULL DEFAULT 'keyword',
                  PRIMARY KEY(asset_id, tag, tag_type)
                );

                CREATE TABLE IF NOT EXISTS asset_vision_annotations (
                  content_sha256 TEXT NOT NULL,
                  model TEXT NOT NULL,
                  prompt_version TEXT NOT NULL,
                  raw_response TEXT NOT NULL DEFAULT '{}',
                  scene_tags TEXT NOT NULL DEFAULT '[]',
                  created_at TEXT NOT NULL,
                  PRIMARY KEY(content_sha256, model, prompt_version)
                );
                """
            )
            _ensure_sqlite_columns(
                conn,
                "assets",
                {
                    "scene_tag_status": "TEXT NOT NULL DEFAULT 'missing'",
                    "scene_tag_model": "TEXT NOT NULL DEFAULT ''",
                    "scene_tag_prompt_version": "TEXT NOT NULL DEFAULT ''",
                    "scene_tagged_at": "TEXT NOT NULL DEFAULT ''",
                },
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _insert_source_image(self, conn: sqlite3.Connection, **values: Any) -> bool:
        now = _now()
        search_text = _join_search_text(
            values["item_id"],
            values["category"],
            values["scene"],
            values["keyword"],
            values["run_id"],
        )
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO source_images (
              id, job_id, run_id, item_id, original_object_key, category, scene,
              input_mode, keyword, uploaded_by, created_at, search_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values["source_id"],
                values["job_id"],
                values["run_id"],
                values["item_id"],
                values["original_object_key"],
                values["category"],
                values["scene"],
                values["input_mode"],
                values["keyword"],
                values["uploaded_by"],
                now,
                search_text,
            ),
        )
        return cursor.rowcount > 0

    def _insert_asset(self, conn: sqlite3.Connection, **values: Any) -> bool:
        search_text = _join_search_text(
            values["category"],
            values["scene"],
            values["query"],
            values["stage"],
            values["filename"],
            values["content_sha256"],
        )
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO assets (
              id, source_image_id, object_key, thumb_object_key, category, scene,
              query, keyword_index, stage, rank, content_sha256, phash, width,
              height, mime_type, size_bytes, status, duplicate_of_asset_id,
              filename, created_at, scene_tag_status, scene_tag_model,
              scene_tag_prompt_version, scene_tagged_at, search_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values["asset_id"],
                values["source_image_id"],
                values["object_key"],
                "",
                values["category"],
                values["scene"],
                values["query"],
                values["keyword_index"],
                values["stage"],
                values["rank"],
                values["content_sha256"],
                values["phash"],
                values["width"],
                values["height"],
                values["mime_type"],
                values["size_bytes"],
                values["status"],
                values["duplicate_of_asset_id"],
                values["filename"],
                _now(),
                "missing",
                "",
                "",
                "",
                search_text,
            ),
        )
        return cursor.rowcount > 0

    @staticmethod
    def _insert_tags(
        conn: sqlite3.Connection, asset_id: str, tags: list[tuple[str, str]]
    ) -> None:
        conn.executemany(
            "INSERT OR IGNORE INTO asset_tags (asset_id, tag, tag_type) VALUES (?, ?, ?)",
            [(asset_id, tag, tag_type) for tag, tag_type in tags if tag],
        )

    @staticmethod
    def _find_available_asset_by_hash(
        conn: sqlite3.Connection, content_sha256: str, *, category: str
    ) -> str | None:
        row = conn.execute(
            """
            SELECT id FROM assets
            WHERE content_sha256 = ? AND category = ? AND status = 'available'
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (content_sha256, category),
        ).fetchone()
        return str(row["id"]) if row else None

    def _scene_tags_for_asset(self, asset_id: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT tag FROM asset_tags
                WHERE asset_id = ? AND tag_type = 'scene'
                ORDER BY rowid ASC
                """,
                (asset_id,),
            ).fetchall()
        return [str(row["tag"]) for row in rows]

    @staticmethod
    def _save_scene_annotation(
        conn: sqlite3.Connection,
        *,
        content_sha256: str,
        model: str,
        prompt_version: str,
        scene_tags: list[str],
        raw_response: dict[str, Any],
    ) -> None:
        if not content_sha256:
            return
        conn.execute(
            """
            INSERT OR REPLACE INTO asset_vision_annotations (
              content_sha256, model, prompt_version, raw_response, scene_tags, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                content_sha256,
                model,
                prompt_version,
                json.dumps(raw_response, ensure_ascii=False),
                json.dumps(scene_tags, ensure_ascii=False),
                _now(),
            ),
        )


def _stable_id(*parts: str) -> str:
    return uuid.uuid5(ASSET_NAMESPACE, "|".join(parts)).hex


def _object_key(prefix: str, object_id: str, suffix: str) -> str:
    now = dt.datetime.now(dt.UTC)
    safe_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    return f"{prefix}/{now:%Y}/{now:%m}/{object_id}{safe_suffix.lower()}"


def _find_reference_image(run_dir: Path, item_id: str) -> Path | None:
    input_dir = run_dir / "inputs" / item_id
    for path in sorted(input_dir.glob("reference.*")):
        if path.is_file():
            return path
    return None


def _local_image_path(run_dir: Path, value: str) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else run_dir / path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _guess_content_type(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def _optional_int(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(value)


def _asset_tags(category: str, scene: str, image: dict[str, Any]) -> list[tuple[str, str]]:
    tags = [(category, "category"), (scene, "scene")]
    query = str(image.get("query") or "").strip()
    if query:
        tags.append((query, "query"))
    stage = str(image.get("stage") or "").strip()
    if stage:
        tags.append((stage, "stage"))
    return tags


def _normalize_scene_tags(tags: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in tags or []:
        tag = " ".join(str(value).strip().split())
        if not tag or tag in seen:
            continue
        seen.add(tag)
        result.append(tag)
        if len(result) >= 7:
            break
    return result or ["未识别场景"]


def _ensure_sqlite_columns(
    conn: sqlite3.Connection, table: str, columns: dict[str, str]
) -> None:
    existing = {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _join_search_text(*parts: Any) -> str:
    return " ".join(str(part).strip() for part in parts if str(part).strip())


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()
