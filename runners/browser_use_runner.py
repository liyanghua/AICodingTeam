from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


def load_input(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_output(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def package_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    data = load_input(Path(args.input))
    reason = "missing-package:browser_use" if not package_available("browser_use") else "runner-skeleton-only"
    payload = {
        "framework": "browser-use",
        "status": "unavailable",
        "notes": [],
        "risk_events": [reason],
        "metrics": {
            "elapsed_ms": 0,
            "retry_count": 0,
            "crash_count": 0,
            "manual_interventions": 0,
            "token_cost": 0.0,
        },
        "runner": "runners/browser_use_runner.py",
        "input_keyword": data.get("task", {}).get("keyword", ""),
    }
    write_output(Path(args.output), payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
