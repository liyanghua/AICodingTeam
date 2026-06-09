from __future__ import annotations

import base64
import io
import shlex
import subprocess
from pathlib import Path


class UiautomatorTaobaoDevice:
    def __init__(self, u2_device, serial: str | None = None) -> None:
        self._device = u2_device
        self._serial = serial
        self._adb: _Adb | None = None

    @classmethod
    def connect(cls, serial: str | None = None) -> "UiautomatorTaobaoDevice":
        try:
            import uiautomator2 as u2
        except ImportError as exc:
            raise RuntimeError(
                "uiautomator2 is required for Taobao mobile collection. "
                "Install it in the collector Python environment."
            ) from exc
        return cls(u2.connect(serial), serial=serial)

    @property
    def adb(self) -> "_Adb":
        if self._adb is not None:
            return self._adb
        serial = self._serial or getattr(self._device, "serial", None)
        return _Adb(serial)

    def current_package(self) -> str:
        current = self._device.app_current()
        if isinstance(current, dict):
            return str(current.get("package") or "")
        return str(current or "")

    def start_app(self, package: str) -> None:
        self._device.app_start(package)

    def dump_hierarchy(self) -> str:
        return self._device.dump_hierarchy()

    def tap_by_description(self, description: str) -> bool:
        target = self._device(description=description)
        click_exists = getattr(target, "click_exists", None)
        if click_exists is not None:
            try:
                return bool(click_exists(timeout=1.0))
            except TypeError:
                return bool(click_exists())
        exists = getattr(target, "exists", False)
        if callable(exists):
            exists = exists()
        if not exists:
            return False
        target.click()
        return True

    def tap_profile_point(self, _name: str, point: tuple[float, float]) -> None:
        x, y = self._to_screen_point(point)
        try:
            self._device.click(x, y)
        except Exception as exc:
            if not _is_input_injection_error(exc):
                raise
            self.adb.shell(f"input tap {x} {y}")

    def tap_profile_point_adb(self, _name: str, point: tuple[float, float]) -> None:
        x, y = self._to_screen_point(point)
        self.adb.shell(f"input tap {x} {y}")

    def long_press_profile_point(
        self, _name: str, point: tuple[float, float], duration: float = 1.0
    ) -> None:
        x, y = self._to_screen_point(point)
        try:
            self._device.long_click(x, y, duration)
        except Exception as exc:
            if not _is_input_injection_error(exc):
                raise
            self.adb.shell(f"input swipe {x} {y} {x} {y} {round(duration * 1000)}")

    def swipe_profile_points(
        self,
        _name: str,
        start: tuple[float, float],
        end: tuple[float, float],
        duration: float = 0.3,
    ) -> None:
        x1, y1 = self._to_screen_point(start)
        x2, y2 = self._to_screen_point(end)
        duration_ms = round(duration * 1000)
        try:
            self._device.swipe(x1, y1, x2, y2, duration)
        except Exception as exc:
            if not _is_input_injection_error(exc):
                raise
            self.adb.shell(f"input swipe {x1} {y1} {x2} {y2} {duration_ms}")

    def set_text(self, text: str) -> None:
        send_keys = getattr(self._device, "send_keys", None)
        if send_keys is not None:
            try:
                send_keys(text, clear=True)
                return
            except TypeError:
                send_keys(text)
                return
            except Exception as exc:
                if not _is_adb_keyboard_clear_error(exc):
                    raise
                self._adb_text_fallback(text)
                return
        self._adb_text_fallback(text)

    def _adb_text_fallback(self, text: str) -> None:
        self.adb.shell("input keyevent KEYCODE_CTRL_LEFT KEYCODE_A")
        self.adb.shell("input keyevent KEYCODE_DEL")
        if not text.isascii():
            encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
            self.adb.shell(f"am broadcast -a ADB_INPUT_B64 --es msg {shlex.quote(encoded)}")
            return
        escaped = shlex.quote(text.replace(" ", "%s"))
        self.adb.shell(f"input text {escaped}")

    def press_enter(self) -> None:
        press = getattr(self._device, "press", None)
        if press is not None:
            press("enter")
            return
        self.adb.shell("input keyevent ENTER")

    def press_back(self) -> None:
        press = getattr(self._device, "press", None)
        if press is not None:
            try:
                press("back")
                return
            except Exception as exc:
                if not _is_input_injection_error(exc):
                    raise
        self.adb.shell("input keyevent BACK")

    def save_screenshot(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        image = self._device.screenshot()
        if isinstance(image, bytes):
            path.write_bytes(image)
            return
        if isinstance(image, str):
            path.write_bytes(Path(image).read_bytes())
            return
        save = getattr(image, "save", None)
        if save is not None:
            image.save(path)
            return
        output = getattr(image, "tobytes", None)
        path.write_bytes(output() if output else bytes(image))

    def push_reference_image(self, local_path: Path, item_id: str, remote_dir: str) -> str:
        remote_path = f"{remote_dir}/{item_id}{local_path.suffix or '.jpg'}"
        self.adb.shell(f"mkdir -p {remote_dir}")
        self.adb.push(str(local_path), remote_path)
        self.adb.shell(
            "am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE "
            f"-d file://{remote_path}"
        )
        return remote_path

    def _to_screen_point(self, point: tuple[float, float]) -> tuple[int, int]:
        width, height = tuple(self._device.window_size())
        return round(width * point[0]), round(height * point[1])


class _Adb:
    def __init__(self, serial: str | None) -> None:
        self.serial = serial

    def shell(self, command: str) -> str:
        result = subprocess.run(
            self._args(["shell", command]),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return result.stdout

    def push(self, local: str, remote: str) -> None:
        subprocess.run(self._args(["push", local, remote]), check=True)

    def pull(self, remote: str, local: str) -> None:
        subprocess.run(self._args(["pull", remote, local]), check=True)

    def _args(self, args: list[str]) -> list[str]:
        base = ["adb"]
        if self.serial:
            base.extend(["-s", self.serial])
        return base + args


def _is_input_injection_error(exc: Exception) -> bool:
    text = str(exc)
    return "INJECT_EVENTS" in text or "Injecting input events" in text


def _is_adb_keyboard_clear_error(exc: Exception) -> bool:
    text = str(exc)
    return (
        "ADB_KEYBOARD_CLEAR_TEXT" in text
        or "clearText" in text
        or "ExtractedText" in text
        or "null object reference" in text
    )
