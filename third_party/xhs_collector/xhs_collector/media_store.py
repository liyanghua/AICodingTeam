from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol


class PullDevice(Protocol):
    async def shell(self, command: str) -> str: ...

    async def pull(self, remote: str, local: str) -> None: ...


def diff_new_media(before: list[str], after: list[str]) -> list[str]:
    previous = set(before)
    return sorted(path for path in after if path not in previous)


class MediaStore:
    def __init__(self, adb_device: PullDevice) -> None:
        self._device = adb_device

    async def snapshot(self) -> list[str]:
        command = (
            "find /sdcard/DCIM /sdcard/Pictures -type f "
            "\\( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' \\) "
            "2>/dev/null"
        )
        output = await self._device.shell(command)
        return sorted(line.strip() for line in output.splitlines() if line.strip())

    async def pull(self, remote_path: str, target_path: Path) -> Path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        await self._device.pull(remote_path, str(target_path))
        return target_path

    async def refresh(self) -> None:
        await self._device.shell("cmd media scan-volume external_primary >/dev/null 2>&1 || true")


class SyncMediaStore:
    def __init__(self, adb_device: PullDevice) -> None:
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


class DryRunMediaStore:
    def create_ranked_image(self, target_path: Path, payload: bytes) -> Path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(payload)
        return target_path

    def copy_ranked_image(self, source_path: Path, target_path: Path) -> Path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target_path)
        return target_path
