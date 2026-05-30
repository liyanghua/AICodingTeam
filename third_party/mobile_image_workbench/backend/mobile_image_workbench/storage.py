from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


@dataclass(frozen=True)
class ObjectMetadata:
    key: str
    size_bytes: int
    content_type: str
    etag: str
    exists: bool = True


class FilesystemObjectStorageClient:
    """Local private object storage used by dev/test and MinIO-like deployments."""

    def __init__(self, root_dir: Path, *, bucket: str) -> None:
        self.root_dir = root_dir
        self.bucket = bucket
        self.bucket_dir.mkdir(parents=True, exist_ok=True)

    @property
    def bucket_dir(self) -> Path:
        return self.root_dir / self.bucket

    def put_object(
        self, key: str, source_path: Path, *, content_type: str | None = None
    ) -> ObjectMetadata:
        target = self._target_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target)
        metadata = self._metadata_for_path(
            key, target, content_type=content_type or _guess_content_type(source_path.name)
        )
        self._metadata_path(target).write_text(
            json.dumps(
                {
                    "key": metadata.key,
                    "size_bytes": metadata.size_bytes,
                    "content_type": metadata.content_type,
                    "etag": metadata.etag,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return metadata

    def head_object(self, key: str) -> ObjectMetadata:
        target = self._target_path(key)
        if not target.exists() or not target.is_file():
            return ObjectMetadata(
                key=key,
                size_bytes=0,
                content_type="application/octet-stream",
                etag="",
                exists=False,
            )
        metadata_path = self._metadata_path(target)
        if metadata_path.exists():
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            return ObjectMetadata(
                key=str(payload["key"]),
                size_bytes=int(payload["size_bytes"]),
                content_type=str(payload["content_type"]),
                etag=str(payload["etag"]),
                exists=True,
            )
        return self._metadata_for_path(key, target, content_type=_guess_content_type(key))

    def copy_object(self, source_key: str, target_key: str) -> ObjectMetadata:
        source = self._target_path(source_key)
        if not source.exists() or not source.is_file():
            return ObjectMetadata(
                key=target_key,
                size_bytes=0,
                content_type="application/octet-stream",
                etag="",
                exists=False,
            )
        return self.put_object(
            target_key,
            source,
            content_type=self.head_object(source_key).content_type,
        )

    def read_object(self, key: str) -> bytes:
        target = self._target_path(key)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"object not found: {key}")
        return target.read_bytes()

    def local_path_for_key(self, key: str) -> Path:
        return self._target_path(key)

    def presign_get_url(self, key: str) -> str:
        return f"/api/library/objects/{quote(self.bucket, safe='')}/{quote(key, safe='/')}"

    def _target_path(self, key: str) -> Path:
        path = Path(key)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError(f"invalid object key: {key}")
        target = (self.bucket_dir / path).resolve()
        bucket_root = self.bucket_dir.resolve()
        if bucket_root not in target.parents and target != bucket_root:
            raise ValueError(f"invalid object key: {key}")
        return target

    @staticmethod
    def _metadata_path(path: Path) -> Path:
        return path.with_name(path.name + ".metadata.json")

    @staticmethod
    def _metadata_for_path(
        key: str, path: Path, *, content_type: str
    ) -> ObjectMetadata:
        payload = path.read_bytes()
        return ObjectMetadata(
            key=key,
            size_bytes=len(payload),
            content_type=content_type,
            etag=hashlib.sha256(payload).hexdigest(),
            exists=True,
        )


def _guess_content_type(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"
