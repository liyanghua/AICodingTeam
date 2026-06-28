from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any


REQUIRED_POINTS = {
    "home_search_box",
    "image_search_button",
    "album_entry",
    "first_album_image",
    "album_confirm",
    "result_card",
    "detail_main_image",
    "save_image_button",
    "detail_back_button",
}
OPTIONAL_POINTS = {
    "result_card_1",
    "result_card_2",
    "result_card_3",
}
SUPPORTED_POINTS = REQUIRED_POINTS | OPTIONAL_POINTS


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
        if not path.exists():
            raise FileNotFoundError(f"coordinate profile not found: {path}")
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"points": {key: list(value) for key, value in self.points.items()}},
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

    def result_card_point(self, rank: int) -> tuple[float, float]:
        name = f"result_card_{rank}"
        if name in self.points:
            return self.points[name]
        return self.point("result_card")

    def result_card_slots(self) -> list[tuple[str, tuple[float, float]]]:
        slots: list[tuple[int, str, tuple[float, float]]] = []
        for name, point in self.points.items():
            match = re.fullmatch(r"result_card_(\d+)", name)
            if match is None:
                continue
            slots.append((int(match.group(1)), name, point))
        if not slots:
            return [("result_card", self.point("result_card"))]
        return [(name, point) for _, name, point in sorted(slots)]


def write_default_coordinate_profile(path: Path) -> CoordinateProfile:
    profile = CoordinateProfile.from_dict(
        {
            "points": {
                "home_search_box": [0.5, 0.08],
                "image_search_button": [0.9, 0.08],
                "album_entry": [0.5, 0.88],
                "first_album_image": [0.16, 0.22],
                "album_confirm": [0.88, 0.95],
                "result_card": [0.5, 0.34],
                "result_card_1": [0.25, 0.34],
                "result_card_2": [0.75, 0.34],
                "result_card_3": [0.25, 0.62],
                "detail_main_image": [0.5, 0.35],
                "save_image_button": [0.5, 0.82],
                "detail_back_button": [0.06, 0.07],
            }
        }
    )
    profile.write(path)
    return profile


def _validate_ratio(value: float) -> None:
    if not 0 <= value <= 1:
        raise ValueError("ratio must be between 0 and 1")
