from __future__ import annotations

import sys
from pathlib import Path

from .models import CollectorConfig


def ensure_mobilerun_import_path() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    mobilerun_root = repo_root / "third_party" / "mobilerun-main"
    if str(mobilerun_root) not in sys.path:
        sys.path.insert(0, str(mobilerun_root))


class AndroidCollectorDevice:
    def __init__(self, config: CollectorConfig) -> None:
        ensure_mobilerun_import_path()
        from mobilerun.tools import AndroidDriver

        self.config = config
        self.driver = AndroidDriver(serial=config.device_serial)

    async def connect(self) -> None:
        await self.driver.connect()

    async def start_xhs(self) -> str:
        return await self.driver.start_app(self.config.xhs_package)

    async def push_reference_image(self, local_path: Path, item_id: str) -> str:
        await self.driver.ensure_connected()
        remote_path = (
            f"{self.config.remote_image_dir}/{item_id}{local_path.suffix or '.jpg'}"
        )
        await self.driver.device.shell(f"mkdir -p {self.config.remote_image_dir}")
        await self.driver.device.push(str(local_path), remote_path)
        await self.driver.device.shell(
            "am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE "
            f"-d file://{remote_path}"
        )
        return remote_path

    async def list_packages(self) -> list[str]:
        return await self.driver.list_packages(include_system=False)

    @property
    def adb_device(self):
        return self.driver.device


async def run_doctor(config: CollectorConfig) -> dict[str, object]:
    device = AndroidCollectorDevice(config)
    await device.connect()
    packages = await device.list_packages()
    has_xhs = config.xhs_package in packages
    return {
        "device_connected": True,
        "xhs_package": config.xhs_package,
        "xhs_installed": has_xhs,
        "manual_login_required": True,
        "safety": "manual login only; no captcha bypass; no anti-bot evasion",
    }
