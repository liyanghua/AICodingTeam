from __future__ import annotations

import json
from pathlib import Path

from .models import TaobaoConfig


def load_config(path: Path | None) -> TaobaoConfig:
    if path is None:
        return TaobaoConfig.from_dict({})
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config must be a JSON object")
    return TaobaoConfig.from_dict(data)
