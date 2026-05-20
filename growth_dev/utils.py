from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def now_millis() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def slugify(text: str) -> str:
    value = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", text.strip())
    value = re.sub(r"-+", "-", value).strip("-")
    return value.lower() or "item"


def stable_seed(*parts: str) -> int:
    payload = "||".join(parts).encode("utf-8")
    return int(sha256(payload).hexdigest()[:16], 16)


def json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def human_ms(value: int) -> str:
    if value < 1000:
        return f"{value}ms"
    seconds = value / 1000
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes, remainder = divmod(seconds, 60)
    return f"{int(minutes)}m{remainder:04.1f}s"


def parse_count(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)

    text = str(value).strip().lower().replace(",", "")
    if not text:
        return 0
    if text.endswith("+"):
        text = text[:-1]

    multipliers = {
        "亿": 100000000,
        "w": 10000,
        "万": 10000,
        "k": 1000,
    }
    for suffix, multiplier in multipliers.items():
        if text.endswith(suffix):
            number = text[: -len(suffix)]
            return int(float(number) * multiplier)

    return int(float(text))


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))
