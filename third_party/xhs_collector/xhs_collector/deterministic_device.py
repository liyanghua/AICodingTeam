from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REQUIRED_POINTS = {
    "search_box",
    "image_search_button",
    "album_entry",
    "first_album_image",
    "album_confirm",
}
DOWNLOAD_POINTS = {
    "results_panel_swipe_start",
    "results_panel_swipe_end",
    "result_card_1",
    "result_card_2",
    "result_card_3",
    "note_main_image",
    "save_image_menu_item",
    "note_back_button",
}
KEYWORD_SEARCH_POINTS = {
    "keyword_search_box",
    "keyword_search_submit",
}
SUPPORTED_POINTS = REQUIRED_POINTS | DOWNLOAD_POINTS | KEYWORD_SEARCH_POINTS | {
    "results_anchor",
}


@dataclass(frozen=True)
class CoordinateProfile:
    points: dict[str, tuple[float, float]]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CoordinateProfile":
        raw_points = data.get("points", {})
        points: dict[str, tuple[float, float]] = {}
        for name, raw_value in raw_points.items():
            if not isinstance(raw_value, (list, tuple)) or len(raw_value) != 2:
                raise ValueError(f"coordinate point {name} must be [x_ratio, y_ratio]")
            x_ratio = float(raw_value[0])
            y_ratio = float(raw_value[1])
            _validate_ratio(x_ratio)
            _validate_ratio(y_ratio)
            points[str(name)] = (x_ratio, y_ratio)
        missing = sorted(REQUIRED_POINTS - set(points))
        if missing:
            raise ValueError(f"missing coordinate point: {missing[0]}")
        return cls(points=points)

    @classmethod
    def load(cls, path: Path) -> "CoordinateProfile":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"points": {name: list(value) for name, value in self.points.items()}},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def point(self, name: str) -> tuple[float, float]:
        if name not in self.points:
            raise KeyError(f"coordinate point not found: {name}")
        return self.points[name]

    def require_points(self, names: set[str]) -> None:
        missing = sorted(names - set(self.points))
        if missing:
            raise ValueError(f"missing coordinate point: {missing[0]}")


def write_default_coordinate_profile(path: Path) -> CoordinateProfile:
    profile = CoordinateProfile.from_dict(
        {
            "points": {
                "search_box": [0.5, 0.08],
                "image_search_button": [0.9, 0.12],
                "album_entry": [0.925, 0.8468],
                "first_album_image": [0.125, 0.1948],
                "album_confirm": [0.88, 0.965],
                "results_anchor": [0.5, 0.24],
                "keyword_search_box": [0.12, 0.08],
                "keyword_search_submit": [0.88, 0.08],
                "results_panel_swipe_start": [0.5, 0.82],
                "results_panel_swipe_end": [0.5, 0.18],
                "result_card_1": [0.25, 0.3],
                "result_card_2": [0.75, 0.3],
                "result_card_3": [0.25, 0.58],
                "note_main_image": [0.5, 0.4],
                "save_image_menu_item": [0.5, 0.82],
                "note_back_button": [0.06, 0.07],
            }
        }
    )
    profile.write(path)
    return profile


class DeterministicDevice:
    def __init__(self, u2_device, serial: str | None = None) -> None:
        self._device = u2_device
        self._serial = serial

    @classmethod
    def connect(cls, serial: str | None = None) -> "DeterministicDevice":
        try:
            import uiautomator2 as u2
        except ImportError as exc:
            raise RuntimeError(
                "uiautomator2 is required for deterministic mode. "
                "Install it in a Python 3.11-3.13 environment."
            ) from exc
        return cls(u2.connect(serial), serial=serial)

    @property
    def adb_device(self) -> "DeterministicAdbDevice":
        serial = self._serial or getattr(self._device, "serial", None)
        return DeterministicAdbDevice(serial=serial)

    def start_app(self, package: str) -> None:
        self._device.app_start(package)

    def current_package(self) -> str:
        app_current = getattr(self._device, "app_current", None)
        if app_current is None:
            return ""
        current = app_current()
        if isinstance(current, dict):
            return str(current.get("package") or "")
        return str(current or "")

    def window_size(self) -> tuple[int, int]:
        return tuple(self._device.window_size())

    def click_ratio(self, x_ratio: float, y_ratio: float) -> None:
        x, y = self._to_screen_point(x_ratio, y_ratio)
        try:
            self._device.click(x, y)
        except Exception as exc:
            if not _is_input_injection_error(exc):
                raise
            self.adb_device.shell(f"input tap {x} {y}")

    def click_point(self, x: int, y: int) -> None:
        try:
            self._device.click(x, y)
        except Exception as exc:
            if not _is_input_injection_error(exc):
                raise
            self.adb_device.shell(f"input tap {x} {y}")

    def set_text(self, text: str) -> None:
        send_keys = getattr(self._device, "send_keys", None)
        if send_keys is not None:
            try:
                send_keys(text, clear=True)
                return
            except TypeError:
                send_keys(text)
                return
        escaped = shlex.quote(text.replace(" ", "%s"))
        self.adb_device.shell(f"input text {escaped}")

    def press_enter(self) -> None:
        press = getattr(self._device, "press", None)
        if press is not None:
            press("enter")
            return
        self.adb_device.shell("input keyevent ENTER")

    def press_back(self) -> None:
        press = getattr(self._device, "press", None)
        if press is not None:
            try:
                press("back")
                return
            except Exception as exc:
                if not _is_input_injection_error(exc):
                    raise
        self.adb_device.shell("input keyevent BACK")

    def long_press_ratio(
        self, x_ratio: float, y_ratio: float, duration: float = 1.0
    ) -> None:
        x, y = self._to_screen_point(x_ratio, y_ratio)
        try:
            self._device.long_click(x, y, duration)
        except Exception as exc:
            if not _is_input_injection_error(exc):
                raise
            self.adb_device.shell(f"input swipe {x} {y} {x} {y} {round(duration * 1000)}")

    def swipe_ratio(
        self,
        x1_ratio: float,
        y1_ratio: float,
        x2_ratio: float,
        y2_ratio: float,
        duration: float = 0.5,
    ) -> None:
        x1, y1 = self._to_screen_point(x1_ratio, y1_ratio)
        x2, y2 = self._to_screen_point(x2_ratio, y2_ratio)
        try:
            self._device.swipe(x1, y1, x2, y2, duration)
        except Exception as exc:
            if not _is_input_injection_error(exc):
                raise
            self.adb_device.shell(
                f"input swipe {x1} {y1} {x2} {y2} {round(duration * 1000)}"
            )

    def dump_hierarchy(self) -> str:
        return self._device.dump_hierarchy()

    def exists_text(self, text: str) -> bool:
        return text in self.dump_hierarchy()

    def screenshot(self) -> bytes:
        image = self._device.screenshot()
        if isinstance(image, bytes):
            return image
        if isinstance(image, str):
            return Path(image).read_bytes()
        save = getattr(image, "save", None)
        if save is not None:
            import io

            buffer = io.BytesIO()
            save(buffer, format="PNG")
            return buffer.getvalue()
        output = getattr(image, "tobytes", None)
        return output() if output else bytes(image)

    def push_reference_image(
        self, local_path: Path, item_id: str, remote_dir: str
    ) -> str:
        remote_path = f"{remote_dir}/{item_id}{local_path.suffix or '.jpg'}"
        self.adb_device.shell(f"mkdir -p {remote_dir}")
        self.adb_device.push(str(local_path), remote_path)
        self.adb_device.shell(
            "am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE "
            f"-d file://{remote_path}"
        )
        return remote_path

    def save_debug_artifacts(self, output_dir: Path, step_name: str) -> None:
        screenshot_dir = output_dir / "screenshots"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        (screenshot_dir / f"{step_name}.png").write_bytes(self.screenshot())
        (screenshot_dir / f"{step_name}.xml").write_text(
            self.dump_hierarchy(), encoding="utf-8"
        )

    def _to_screen_point(self, x_ratio: float, y_ratio: float) -> tuple[int, int]:
        _validate_ratio(x_ratio)
        _validate_ratio(y_ratio)
        width, height = self.window_size()
        return round(width * x_ratio), round(height * y_ratio)


class DeterministicAdbDevice:
    def __init__(self, serial: str | None = None) -> None:
        self.serial = serial

    def shell(self, command: str) -> str:
        args = self._adb_args(["shell", command])
        try:
            result = subprocess.run(
                args,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(_format_adb_error(args, exc)) from exc
        return result.stdout

    def push(self, local: str, remote: str) -> None:
        subprocess.run(self._adb_args(["push", local, remote]), check=True)

    def pull(self, remote: str, local: str) -> None:
        subprocess.run(self._adb_args(["pull", remote, local]), check=True)

    def _adb_args(self, args: list[str]) -> list[str]:
        base = ["adb"]
        if self.serial:
            base.extend(["-s", self.serial])
        return base + args


def _validate_ratio(value: float) -> None:
    if not 0 <= value <= 1:
        raise ValueError("ratio must be between 0 and 1")


def _is_input_injection_error(exc: Exception) -> bool:
    text = str(exc)
    return "INJECT_EVENTS" in text or "Injecting input events" in text


def _format_adb_error(args: list[str], exc: subprocess.CalledProcessError) -> str:
    details = str(exc)
    stderr = (exc.stderr or "").strip()
    stdout = (exc.stdout or "").strip()
    if stderr:
        details = f"{details}\nstderr: {stderr}"
    if stdout:
        details = f"{details}\nstdout: {stdout}"
    return f"adb command failed: {' '.join(shlex.quote(arg) for arg in args)}\n{details}"
