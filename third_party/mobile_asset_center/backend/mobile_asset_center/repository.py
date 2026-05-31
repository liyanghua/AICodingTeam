from __future__ import annotations

import datetime as dt
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


class SqliteAssetCenterRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def upsert_collector(self, collector_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO collectors (id, created_at)
                VALUES (?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (collector_id, _now()),
            )
            conn.commit()

    def upsert_ingest_batch(self, bundle_id: str, collector_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ingest_batches (id, collector_id, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (bundle_id, collector_id, _now()),
            )
            conn.commit()

    def upsert_source_image(self, source: dict[str, Any]) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO source_images (
                  id, item_id, object_key, category, scene, input_mode,
                  keyword, created_at, search_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  object_key=excluded.object_key,
                  category=excluded.category,
                  scene=excluded.scene,
                  input_mode=excluded.input_mode,
                  keyword=excluded.keyword,
                  search_text=excluded.search_text
                """,
                (
                    source["id"],
                    source.get("itemId", ""),
                    source.get("objectKey", ""),
                    source.get("category", ""),
                    source.get("scene", ""),
                    source.get("inputMode", ""),
                    source.get("keyword", ""),
                    _now(),
                    _join_search_text(
                        source.get("itemId", ""),
                        source.get("category", ""),
                        source.get("scene", ""),
                        source.get("keyword", ""),
                    ),
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def upsert_asset(self, asset: dict[str, Any]) -> bool:
        scene_tags = _normalize_tags(asset.get("sceneTags") or [])
        asset = dict(asset)
        duplicate_of = self.find_available_asset_by_hash(
            str(asset.get("contentSha256") or ""),
            category=str(asset.get("category") or ""),
            exclude_asset_id=str(asset.get("assetId") or ""),
        )
        if duplicate_of:
            asset["status"] = "duplicate"
        search_text = _join_search_text(
            asset.get("category", ""),
            asset.get("scene", ""),
            asset.get("query", ""),
            asset.get("stage", ""),
            asset.get("filename", ""),
            *scene_tags,
        )
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO assets (
                  id, source_image_id, asset_type, object_key, category, scene,
                  query, keyword_index, stage, rank, content_sha256, phash,
                  mime_type, size_bytes, status, filename, scene_tag_status,
                  scene_tag_model, scene_tag_prompt_version, created_at, search_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  object_key=excluded.object_key,
                  category=excluded.category,
                  scene=excluded.scene,
                  query=excluded.query,
                  stage=excluded.stage,
                  rank=excluded.rank,
                  status=excluded.status,
                  scene_tag_status=excluded.scene_tag_status,
                  scene_tag_model=excluded.scene_tag_model,
                  scene_tag_prompt_version=excluded.scene_tag_prompt_version,
                  search_text=excluded.search_text
                """,
                (
                    asset["assetId"],
                    asset.get("sourceImageId", ""),
                    asset.get("assetType", "collected"),
                    asset.get("objectKey", ""),
                    asset.get("category", ""),
                    asset.get("scene", ""),
                    asset.get("query", ""),
                    _optional_int(asset.get("keywordIndex")),
                    asset.get("stage", ""),
                    _optional_int(asset.get("rank")),
                    asset.get("contentSha256", ""),
                    asset.get("phash", ""),
                    asset.get("mimeType", ""),
                    int(asset.get("sizeBytes") or 0),
                    asset.get("status", "available"),
                    asset.get("filename", ""),
                    asset.get("sceneTagStatus", "missing"),
                    asset.get("sceneTagModel", ""),
                    asset.get("sceneTagPromptVersion", ""),
                    _now(),
                    search_text,
                ),
            )
            conn.execute("DELETE FROM asset_tags WHERE asset_id = ?", (asset["assetId"],))
            for tag in scene_tags:
                conn.execute(
                    "INSERT OR IGNORE INTO asset_tags (asset_id, tag, tag_type) VALUES (?, ?, 'scene')",
                    (asset["assetId"], tag),
                )
            if asset.get("category"):
                conn.execute(
                    "INSERT OR IGNORE INTO asset_tags (asset_id, tag, tag_type) VALUES (?, ?, 'category')",
                    (asset["assetId"], asset["category"]),
                )
            conn.commit()
            return cursor.rowcount > 0

    def find_available_asset_by_hash(
        self, content_sha256: str, *, category: str, exclude_asset_id: str = ""
    ) -> str:
        if not content_sha256 or not category:
            return ""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM assets
                WHERE content_sha256 = ? AND category = ? AND status = 'available' AND id != ?
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """,
                (content_sha256, category, exclude_asset_id),
            ).fetchone()
        return str(row["id"]) if row else ""

    def categories(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT category, COUNT(*) AS count
                FROM assets
                WHERE category != '' AND status = 'available'
                GROUP BY category
                ORDER BY count DESC, category ASC
                """
            ).fetchall()
        return [{"category": row["category"], "count": row["count"]} for row in rows]

    def scenes(self, *, category: str = "") -> list[dict[str, Any]]:
        clauses = ["t.tag_type = 'scene'", "a.status = 'available'"]
        params: list[Any] = []
        if category:
            clauses.append("a.category = ?")
            params.append(category)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                  t.tag AS scene,
                  COUNT(*) AS count,
                  MIN(CASE WHEN t.tag = a.scene THEN 0 ELSE 1 END) AS kind_order
                FROM asset_tags t
                JOIN assets a ON a.id = t.asset_id
                WHERE {" AND ".join(clauses)}
                GROUP BY t.tag
                ORDER BY kind_order ASC, count DESC, t.tag ASC
                """,
                params,
            ).fetchall()
        return [
            {
                "scene": row["scene"],
                "count": row["count"],
                "kind": self._scene_kind(str(row["scene"]), category=category),
            }
            for row in rows
        ]

    def search_assets(
        self,
        *,
        category: str = "",
        scene: str = "",
        q: str = "",
        asset_type: str = "",
        cursor: str = "",
        limit: int = 40,
    ) -> dict[str, Any]:
        clauses = ["a.status = 'available'"]
        params: list[Any] = []
        if category:
            clauses.append("a.category = ?")
            params.append(category)
        if scene:
            clauses.append(
                "EXISTS (SELECT 1 FROM asset_tags t WHERE t.asset_id = a.id AND t.tag_type = 'scene' AND t.tag = ?)"
            )
            params.append(scene)
        if q:
            clauses.append("a.search_text LIKE ?")
            params.append(f"%{q}%")
        if asset_type:
            clauses.append("a.asset_type = ?")
            params.append(asset_type)
        if cursor:
            clauses.append("a.created_at < ?")
            params.append(cursor)
        limit_value = max(1, min(int(limit), 100))
        params.append(limit_value + 1)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT a.*
                FROM assets a
                WHERE {" AND ".join(clauses)}
                ORDER BY a.created_at DESC, a.id ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        has_more = len(rows) > limit_value
        rows = rows[:limit_value]
        return {
            "assets": [self._asset_payload(row) for row in rows],
            "nextCursor": rows[-1]["created_at"] if has_more and rows else "",
        }

    def object_key_for_asset(self, asset_id: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT object_key FROM assets WHERE id = ?",
                (asset_id,),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(f"asset not found: {asset_id}")
        return str(row["object_key"])

    def _asset_payload(self, row: sqlite3.Row) -> dict[str, Any]:
        asset_id = str(row["id"])
        scene_tags = self._scene_tags(asset_id)
        return {
            "assetId": asset_id,
            "sourceImageId": row["source_image_id"],
            "assetType": row["asset_type"],
            "objectKey": row["object_key"],
            "category": row["category"],
            "scene": row["scene"],
            "sceneTags": scene_tags,
            "query": row["query"],
            "stage": row["stage"],
            "rank": row["rank"],
            "status": row["status"],
            "mimeType": row["mime_type"],
            "sizeBytes": row["size_bytes"],
            "sceneTagStatus": row["scene_tag_status"],
            "imageUrl": f"/api/objects/cloud-assets/{row['object_key']}",
            "downloadUrl": f"/api/assets/{asset_id}/download",
        }

    def _scene_tags(self, asset_id: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT tag FROM asset_tags WHERE asset_id = ? AND tag_type = 'scene' ORDER BY rowid ASC",
                (asset_id,),
            ).fetchall()
        return [str(row["tag"]) for row in rows]

    def _scene_kind(self, scene: str, *, category: str = "") -> str:
        clauses = ["scene = ?", "status = 'available'"]
        params: list[Any] = [scene]
        if category:
            clauses.append("category = ?")
            params.append(category)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT 1 FROM assets WHERE {' AND '.join(clauses)} LIMIT 1",
                params,
            ).fetchone()
        return "primary" if row else "detail"

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS collectors (
                  id TEXT PRIMARY KEY,
                  created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ingest_batches (
                  id TEXT PRIMARY KEY,
                  collector_id TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS source_images (
                  id TEXT PRIMARY KEY,
                  item_id TEXT NOT NULL DEFAULT '',
                  object_key TEXT NOT NULL DEFAULT '',
                  category TEXT NOT NULL DEFAULT '',
                  scene TEXT NOT NULL DEFAULT '',
                  input_mode TEXT NOT NULL DEFAULT '',
                  keyword TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL,
                  search_text TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS assets (
                  id TEXT PRIMARY KEY,
                  source_image_id TEXT NOT NULL DEFAULT '',
                  asset_type TEXT NOT NULL DEFAULT 'collected',
                  object_key TEXT NOT NULL DEFAULT '',
                  category TEXT NOT NULL DEFAULT '',
                  scene TEXT NOT NULL DEFAULT '',
                  query TEXT NOT NULL DEFAULT '',
                  keyword_index INTEGER,
                  stage TEXT NOT NULL DEFAULT '',
                  rank INTEGER,
                  content_sha256 TEXT NOT NULL DEFAULT '',
                  phash TEXT NOT NULL DEFAULT '',
                  mime_type TEXT NOT NULL DEFAULT '',
                  size_bytes INTEGER NOT NULL DEFAULT 0,
                  status TEXT NOT NULL DEFAULT 'available',
                  filename TEXT NOT NULL DEFAULT '',
                  scene_tag_status TEXT NOT NULL DEFAULT 'missing',
                  scene_tag_model TEXT NOT NULL DEFAULT '',
                  scene_tag_prompt_version TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL,
                  search_text TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_cloud_assets_filters
                  ON assets(category, scene, asset_type, status);
                CREATE INDEX IF NOT EXISTS idx_cloud_assets_search
                  ON assets(search_text);
                CREATE TABLE IF NOT EXISTS asset_tags (
                  asset_id TEXT NOT NULL,
                  tag TEXT NOT NULL,
                  tag_type TEXT NOT NULL,
                  PRIMARY KEY(asset_id, tag, tag_type)
                );
                """
            )
            conn.commit()

    def _connect(self) -> closing[sqlite3.Connection]:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return closing(conn)


class PostgresAssetCenterRepository:
    def __init__(self, dsn: str) -> None:
        try:
            import psycopg  # type: ignore
            from psycopg.rows import dict_row  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on production env
            raise RuntimeError("install psycopg to use PostgreSQL repository") from exc
        self.psycopg = psycopg
        self.dict_row = dict_row
        self.dsn = dsn
        self._ensure_schema()

    def upsert_collector(self, collector_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO collectors (id, created_at)
                VALUES (%s, %s)
                ON CONFLICT(id) DO NOTHING
                """,
                (collector_id, _now()),
            )

    def upsert_ingest_batch(self, bundle_id: str, collector_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ingest_batches (id, collector_id, created_at)
                VALUES (%s, %s, %s)
                ON CONFLICT(id) DO NOTHING
                """,
                (bundle_id, collector_id, _now()),
            )

    def upsert_source_image(self, source: dict[str, Any]) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO source_images (
                  id, item_id, object_key, category, scene, input_mode,
                  keyword, created_at, search_text
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(id) DO UPDATE SET
                  object_key=excluded.object_key,
                  category=excluded.category,
                  scene=excluded.scene,
                  input_mode=excluded.input_mode,
                  keyword=excluded.keyword,
                  search_text=excluded.search_text
                """,
                (
                    source["id"],
                    source.get("itemId", ""),
                    source.get("objectKey", ""),
                    source.get("category", ""),
                    source.get("scene", ""),
                    source.get("inputMode", ""),
                    source.get("keyword", ""),
                    _now(),
                    _join_search_text(
                        source.get("itemId", ""),
                        source.get("category", ""),
                        source.get("scene", ""),
                        source.get("keyword", ""),
                    ),
                ),
            )
            return cursor.rowcount > 0

    def upsert_asset(self, asset: dict[str, Any]) -> bool:
        scene_tags = _normalize_tags(asset.get("sceneTags") or [])
        asset = dict(asset)
        duplicate_of = self.find_available_asset_by_hash(
            str(asset.get("contentSha256") or ""),
            category=str(asset.get("category") or ""),
            exclude_asset_id=str(asset.get("assetId") or ""),
        )
        if duplicate_of:
            asset["status"] = "duplicate"
        search_text = _join_search_text(
            asset.get("category", ""),
            asset.get("scene", ""),
            asset.get("query", ""),
            asset.get("stage", ""),
            asset.get("filename", ""),
            *scene_tags,
        )
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO assets (
                  id, source_image_id, asset_type, object_key, category, scene,
                  query, keyword_index, stage, rank, content_sha256, phash,
                  mime_type, size_bytes, status, filename, scene_tag_status,
                  scene_tag_model, scene_tag_prompt_version, created_at, search_text
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(id) DO UPDATE SET
                  object_key=excluded.object_key,
                  category=excluded.category,
                  scene=excluded.scene,
                  query=excluded.query,
                  stage=excluded.stage,
                  rank=excluded.rank,
                  status=excluded.status,
                  scene_tag_status=excluded.scene_tag_status,
                  scene_tag_model=excluded.scene_tag_model,
                  scene_tag_prompt_version=excluded.scene_tag_prompt_version,
                  search_text=excluded.search_text
                """,
                (
                    asset["assetId"],
                    asset.get("sourceImageId", ""),
                    asset.get("assetType", "collected"),
                    asset.get("objectKey", ""),
                    asset.get("category", ""),
                    asset.get("scene", ""),
                    asset.get("query", ""),
                    _optional_int(asset.get("keywordIndex")),
                    asset.get("stage", ""),
                    _optional_int(asset.get("rank")),
                    asset.get("contentSha256", ""),
                    asset.get("phash", ""),
                    asset.get("mimeType", ""),
                    int(asset.get("sizeBytes") or 0),
                    asset.get("status", "available"),
                    asset.get("filename", ""),
                    asset.get("sceneTagStatus", "missing"),
                    asset.get("sceneTagModel", ""),
                    asset.get("sceneTagPromptVersion", ""),
                    _now(),
                    search_text,
                ),
            )
            conn.execute("DELETE FROM asset_tags WHERE asset_id = %s", (asset["assetId"],))
            for tag in scene_tags:
                conn.execute(
                    "INSERT INTO asset_tags (asset_id, tag, tag_type) VALUES (%s, %s, 'scene') ON CONFLICT DO NOTHING",
                    (asset["assetId"], tag),
                )
            if asset.get("category"):
                conn.execute(
                    "INSERT INTO asset_tags (asset_id, tag, tag_type) VALUES (%s, %s, 'category') ON CONFLICT DO NOTHING",
                    (asset["assetId"], asset["category"]),
                )
            return cursor.rowcount > 0

    def find_available_asset_by_hash(
        self, content_sha256: str, *, category: str, exclude_asset_id: str = ""
    ) -> str:
        if not content_sha256 or not category:
            return ""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM assets
                WHERE content_sha256 = %s AND category = %s AND status = 'available' AND id != %s
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """,
                (content_sha256, category, exclude_asset_id),
            ).fetchone()
        return str(row["id"]) if row else ""

    def categories(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT category, COUNT(*) AS count
                FROM assets
                WHERE category != '' AND status = 'available'
                GROUP BY category
                ORDER BY count DESC, category ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def scenes(self, *, category: str = "") -> list[dict[str, Any]]:
        clauses = ["t.tag_type = 'scene'", "a.status = 'available'"]
        params: list[Any] = []
        if category:
            clauses.append("a.category = %s")
            params.append(category)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                  t.tag AS scene,
                  COUNT(*) AS count,
                  MIN(CASE WHEN t.tag = a.scene THEN 0 ELSE 1 END) AS kind_order
                FROM asset_tags t
                JOIN assets a ON a.id = t.asset_id
                WHERE {" AND ".join(clauses)}
                GROUP BY t.tag
                ORDER BY kind_order ASC, count DESC, t.tag ASC
                """,
                params,
            ).fetchall()
        return [
            {
                "scene": row["scene"],
                "count": row["count"],
                "kind": self._scene_kind(str(row["scene"]), category=category),
            }
            for row in rows
        ]

    def search_assets(
        self,
        *,
        category: str = "",
        scene: str = "",
        q: str = "",
        asset_type: str = "",
        cursor: str = "",
        limit: int = 40,
    ) -> dict[str, Any]:
        clauses = ["a.status = 'available'"]
        params: list[Any] = []
        if category:
            clauses.append("a.category = %s")
            params.append(category)
        if scene:
            clauses.append(
                "EXISTS (SELECT 1 FROM asset_tags t WHERE t.asset_id = a.id AND t.tag_type = 'scene' AND t.tag = %s)"
            )
            params.append(scene)
        if q:
            clauses.append("a.search_text ILIKE %s")
            params.append(f"%{q}%")
        if asset_type:
            clauses.append("a.asset_type = %s")
            params.append(asset_type)
        if cursor:
            clauses.append("a.created_at < %s")
            params.append(cursor)
        limit_value = max(1, min(int(limit), 100))
        params.append(limit_value + 1)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT a.*
                FROM assets a
                WHERE {" AND ".join(clauses)}
                ORDER BY a.created_at DESC, a.id ASC
                LIMIT %s
                """,
                params,
            ).fetchall()
        has_more = len(rows) > limit_value
        rows = rows[:limit_value]
        return {
            "assets": [self._asset_payload(row) for row in rows],
            "nextCursor": rows[-1]["created_at"] if has_more and rows else "",
        }

    def object_key_for_asset(self, asset_id: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT object_key FROM assets WHERE id = %s",
                (asset_id,),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(f"asset not found: {asset_id}")
        return str(row["object_key"])

    def _asset_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        asset_id = str(row["id"])
        return {
            "assetId": asset_id,
            "sourceImageId": row["source_image_id"],
            "assetType": row["asset_type"],
            "objectKey": row["object_key"],
            "category": row["category"],
            "scene": row["scene"],
            "sceneTags": self._scene_tags(asset_id),
            "query": row["query"],
            "stage": row["stage"],
            "rank": row["rank"],
            "status": row["status"],
            "mimeType": row["mime_type"],
            "sizeBytes": row["size_bytes"],
            "sceneTagStatus": row["scene_tag_status"],
            "imageUrl": f"/api/assets/{asset_id}/image",
            "downloadUrl": f"/api/assets/{asset_id}/download",
        }

    def _scene_tags(self, asset_id: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT tag FROM asset_tags WHERE asset_id = %s AND tag_type = 'scene' ORDER BY tag ASC",
                (asset_id,),
            ).fetchall()
        return [str(row["tag"]) for row in rows]

    def _scene_kind(self, scene: str, *, category: str = "") -> str:
        clauses = ["scene = %s", "status = 'available'"]
        params: list[Any] = [scene]
        if category:
            clauses.append("category = %s")
            params.append(category)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT 1 FROM assets WHERE {' AND '.join(clauses)} LIMIT 1",
                params,
            ).fetchone()
        return "primary" if row else "detail"

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS collectors (
                  id TEXT PRIMARY KEY,
                  created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingest_batches (
                  id TEXT PRIMARY KEY,
                  collector_id TEXT NOT NULL,
                  created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_images (
                  id TEXT PRIMARY KEY,
                  item_id TEXT NOT NULL DEFAULT '',
                  object_key TEXT NOT NULL DEFAULT '',
                  category TEXT NOT NULL DEFAULT '',
                  scene TEXT NOT NULL DEFAULT '',
                  input_mode TEXT NOT NULL DEFAULT '',
                  keyword TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL,
                  search_text TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS assets (
                  id TEXT PRIMARY KEY,
                  source_image_id TEXT NOT NULL DEFAULT '',
                  asset_type TEXT NOT NULL DEFAULT 'collected',
                  object_key TEXT NOT NULL DEFAULT '',
                  category TEXT NOT NULL DEFAULT '',
                  scene TEXT NOT NULL DEFAULT '',
                  query TEXT NOT NULL DEFAULT '',
                  keyword_index INTEGER,
                  stage TEXT NOT NULL DEFAULT '',
                  rank INTEGER,
                  content_sha256 TEXT NOT NULL DEFAULT '',
                  phash TEXT NOT NULL DEFAULT '',
                  mime_type TEXT NOT NULL DEFAULT '',
                  size_bytes INTEGER NOT NULL DEFAULT 0,
                  status TEXT NOT NULL DEFAULT 'available',
                  filename TEXT NOT NULL DEFAULT '',
                  scene_tag_status TEXT NOT NULL DEFAULT 'missing',
                  scene_tag_model TEXT NOT NULL DEFAULT '',
                  scene_tag_prompt_version TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL,
                  search_text TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS asset_tags (
                  asset_id TEXT NOT NULL,
                  tag TEXT NOT NULL,
                  tag_type TEXT NOT NULL,
                  PRIMARY KEY(asset_id, tag, tag_type)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pg_assets_filters ON assets(category, scene, asset_type, status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pg_assets_search ON assets(search_text)"
            )

    def _connect(self):
        return self.psycopg.connect(self.dsn, row_factory=self.dict_row)


def _optional_int(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(value)


def _join_search_text(*parts: Any) -> str:
    return " ".join(str(part).strip() for part in parts if str(part).strip())


def _normalize_tags(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        tag = " ".join(str(value).strip().split())
        if not tag or tag in seen:
            continue
        seen.add(tag)
        result.append(tag)
    return result


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()
