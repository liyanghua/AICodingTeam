from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


@dataclass(frozen=True)
class StoredObject:
    key: str
    size_bytes: int
    content_type: str
    etag: str


class FilesystemCloudStorage:
    def __init__(self, root_dir: Path, *, bucket: str) -> None:
        self.root_dir = root_dir
        self.bucket = bucket
        self.bucket_dir.mkdir(parents=True, exist_ok=True)

    @property
    def bucket_dir(self) -> Path:
        return self.root_dir / self.bucket

    def put_bytes(self, key: str, payload: bytes, *, content_type: str) -> StoredObject:
        target = self._target_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        return StoredObject(
            key=key,
            size_bytes=len(payload),
            content_type=content_type,
            etag=hashlib.sha256(payload).hexdigest(),
        )

    def read_bytes(self, key: str) -> bytes:
        return self._target_path(key).read_bytes()

    def presign_get_url(self, key: str) -> str:
        return f"/api/objects/{quote(self.bucket, safe='')}/{quote(key, safe='/')}"

    def copy_from_path(self, key: str, source: Path, *, content_type: str) -> StoredObject:
        target = self._target_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        payload = target.read_bytes()
        return StoredObject(
            key=key,
            size_bytes=len(payload),
            content_type=content_type,
            etag=hashlib.sha256(payload).hexdigest(),
        )

    def _target_path(self, key: str) -> Path:
        path = Path(key)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError(f"invalid object key: {key}")
        target = (self.bucket_dir / path).resolve()
        bucket_root = self.bucket_dir.resolve()
        if bucket_root not in target.parents and target != bucket_root:
            raise ValueError(f"invalid object key: {key}")
        return target


class AliyunOssStorage:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint: str,
        access_key_id: str,
        access_key_secret: str,
        url_expires_seconds: int = 3600,
    ) -> None:
        try:
            import oss2  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on production env
            raise RuntimeError("install oss2 to use Aliyun OSS storage") from exc
        self.bucket_name = bucket
        self.url_expires_seconds = url_expires_seconds
        auth = oss2.Auth(access_key_id, access_key_secret)
        self.bucket = oss2.Bucket(auth, endpoint, bucket)

    def put_bytes(self, key: str, payload: bytes, *, content_type: str) -> StoredObject:
        headers = {"Content-Type": content_type}
        result = self.bucket.put_object(key, payload, headers=headers)
        return StoredObject(
            key=key,
            size_bytes=len(payload),
            content_type=content_type,
            etag=str(result.etag or ""),
        )

    def read_bytes(self, key: str) -> bytes:
        return self.bucket.get_object(key).read()

    def presign_get_url(self, key: str) -> str:
        return self.bucket.sign_url("GET", key, self.url_expires_seconds)
