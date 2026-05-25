from __future__ import annotations

import os
import re
from pathlib import Path


_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_env_file(path: Path, *, override: bool = False) -> dict[str, str]:
    if not path.exists() or not path.is_file():
        return {}
    loaded: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if not _ENV_NAME_RE.match(name):
            continue
        value = _strip_inline_comment(value.strip())
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]
        if override or name not in os.environ:
            os.environ[name] = value
            loaded[name] = value
    return loaded


def load_package_env(package_root: Path, *, override: bool = False) -> dict[str, str]:
    return load_env_file(package_root / ".env", override=override)


def _strip_inline_comment(value: str) -> str:
    quote: str | None = None
    for index, char in enumerate(value):
        if char in {"'", '"'}:
            quote = None if quote == char else char
        if char == "#" and quote is None:
            if index == 0 or value[index - 1].isspace():
                return value[:index].strip()
    return value
