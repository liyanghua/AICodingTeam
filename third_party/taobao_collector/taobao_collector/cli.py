from __future__ import annotations

import argparse
import json
from pathlib import Path

from .coordinates import write_default_coordinate_profile
from .fake_device import DryRunTaobaoDevice
from .models import TaobaoRequest
from .runner import run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="taobao_collector")
    subparsers = parser.add_subparsers(dest="command", required=True)

    calibrate = subparsers.add_parser(
        "calibrate", help="Write a starter Taobao coordinate profile"
    )
    calibrate.add_argument("--output", type=Path, required=True)

    run_parser = subparsers.add_parser("run", help="Run Taobao mobile collection")
    run_parser.add_argument(
        "--mode", choices=["image_search", "keyword_search", "both"], required=True
    )
    run_parser.add_argument("--config", type=Path, default=None)
    run_parser.add_argument("--input-image", type=Path, default=None)
    run_parser.add_argument("--keyword", default="")
    run_parser.add_argument("--keywords", type=Path, default=None)
    run_parser.add_argument("--top-n", type=int, default=None)
    run_parser.add_argument("--device-serial", default=None)
    run_parser.add_argument("--coordinate-profile", type=Path, default=None)
    run_parser.add_argument("--runs-root", type=Path, default=None)
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run with a simulated device and write local artifacts only",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "calibrate":
            output = write_default_coordinate_profile(args.output)
            print(
                json.dumps(
                    {"status": "ok", "coordinate_profile": str(args.output), "points": sorted(output.points)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "run":
            keywords = _read_keywords(args.keywords)
            request = TaobaoRequest(
                mode=args.mode,
                input_image=args.input_image,
                keyword=args.keyword,
                keywords=keywords,
                top_n=args.top_n or 0,
            )
            manifest = run(
                request,
                args.config,
                device=DryRunTaobaoDevice() if args.dry_run else None,
                mode=args.mode,
                top_n=args.top_n,
                output_root=args.runs_root,
                coordinate_profile=args.coordinate_profile,
                device_serial=args.device_serial,
            )
            print(
                json.dumps(
                    {
                        "status": manifest.status,
                        "run_id": manifest.run_id,
                        "output_dir": str(manifest.output_dir),
                        "asset_count": len(manifest.assets),
                        "risk_event_count": len(manifest.risk_events),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        parser.error("unknown command")
    except Exception as exc:
        print(f"error: {exc}")
        return 1
    return 1


def _read_keywords(path: Path | None) -> list[str]:
    if path is None:
        return []
    if not path.exists():
        raise FileNotFoundError(f"keywords file not found: {path}")
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
