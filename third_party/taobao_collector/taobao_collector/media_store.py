from __future__ import annotations

from pathlib import Path
from typing import Protocol


class SyncPullDevice(Protocol):
    def shell(self, command: str) -> str: ...

    def pull(self, remote: str, local: str) -> None: ...


def diff_new_media(before: list[str], after: list[str]) -> list[str]:
    previous = set(before)
    return sorted(path for path in after if path not in previous)


class SyncMediaStore:
    def __init__(self, adb_device: SyncPullDevice) -> None:
        self._device = adb_device

    def snapshot(self) -> list[str]:
        command = (
            "find /sdcard/DCIM /sdcard/Pictures -type f "
            "\\( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' \\) "
            "2>/dev/null"
        )
        output = self._device.shell(command)
        return sorted(line.strip() for line in output.splitlines() if line.strip())

    def pull(self, remote_path: str, target_path: Path) -> Path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        self._device.pull(remote_path, str(target_path))
        return target_path

    def refresh(self) -> None:
        self._device.shell("cmd media scan-volume external_primary >/dev/null 2>&1 || true")


def suffix_for_media(remote_path: str) -> str:
    suffix = Path(remote_path).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp"} else ".jpg"


class DryRunMediaStore:
    def __init__(self) -> None:
        self.paths: list[str] = []
        self.payloads: dict[str, bytes] = {}

    def snapshot(self) -> list[str]:
        return list(self.paths)

    def record_saved_image(self) -> str:
        remote_path = f"/sdcard/Pictures/taobao_collector/dry_saved_{len(self.paths) + 1}.jpg"
        self.paths.append(remote_path)
        self.payloads[remote_path] = f"dry-run-taobao-detail:{remote_path}".encode("utf-8")
        return remote_path

    def pull(self, remote_path: str, target_path: Path) -> Path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(self.payloads.get(remote_path, b"dry-run-taobao-detail"))
        return target_path

    def refresh(self) -> None:
        return
