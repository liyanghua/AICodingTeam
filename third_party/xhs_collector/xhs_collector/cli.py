from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .calibration import (
    DEFAULT_FLOW_POINTS,
    calibrate_flow_on_device,
    calibrate_point_on_device,
    calibrate_search_box_on_device,
)
from .config import load_config
from .device import run_doctor
from .runner import (
    calibrate,
    run_collect,
    run_collect_keyword,
    run_dry_collect,
    validate_input,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xhs_collector")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Check device and XHS readiness")
    doctor.add_argument("--config", type=Path, default=None)

    calibrate_parser = subparsers.add_parser(
        "calibrate", help="Write a starter deterministic coordinate profile"
    )
    calibrate_parser.add_argument("--config", type=Path, default=None)
    calibrate_parser.add_argument("--output", type=Path, required=True)

    search_box_parser = subparsers.add_parser(
        "calibrate-search-box",
        help="Open XHS, screenshot the home page, update search_box, and click it",
    )
    search_box_parser.add_argument("--config", type=Path, default=None)
    search_box_parser.add_argument("--output-dir", type=Path, default=Path("calibration"))
    search_box_parser.add_argument("--x", type=int, default=None)
    search_box_parser.add_argument("--y", type=int, default=None)
    search_box_parser.add_argument("--no-click", action="store_true")
    search_box_parser.add_argument("--wait-seconds", type=float, default=2.0)

    point_parser = subparsers.add_parser(
        "calibrate-point",
        help="Screenshot the current page, update one deterministic coordinate point, and click it",
    )
    point_parser.add_argument("--config", type=Path, default=None)
    point_parser.add_argument("--point", required=True)
    point_parser.add_argument("--output-dir", type=Path, default=None)
    point_parser.add_argument("--x", type=int, default=None)
    point_parser.add_argument("--y", type=int, default=None)
    point_parser.add_argument("--no-click", action="store_true")
    point_parser.add_argument("--start-app", action="store_true")
    point_parser.add_argument("--wait-seconds", type=float, default=2.0)

    flow_parser = subparsers.add_parser(
        "calibrate-flow",
        help="Interactive wizard for calibrating deterministic coordinate points",
    )
    flow_parser.add_argument("--config", type=Path, default=None)
    flow_parser.add_argument("--output-dir", type=Path, default=Path("calibration/flow"))
    flow_parser.add_argument("--points", nargs="*", default=DEFAULT_FLOW_POINTS)
    flow_parser.add_argument("--wait-seconds", type=float, default=2.0)
    flow_parser.add_argument(
        "--no-start-app",
        action="store_true",
        help="Continue from the current phone screen instead of launching XHS first",
    )

    validate = subparsers.add_parser("validate", help="Validate Excel input")
    validate.add_argument("--input", type=Path, required=True)
    validate.add_argument("--config", type=Path, default=None)

    run = subparsers.add_parser("run", help="Run collection")
    run.add_argument("--input", type=Path, required=True)
    run.add_argument("--config", type=Path, default=None)
    run.add_argument("--top-n", type=int, default=None)
    run.add_argument("--image-top-n", type=int, default=None)
    run.add_argument("--keyword-top-n", type=int, default=None)
    run.add_argument("--keyword-result-top-n", type=int, default=None)
    run.add_argument("--mode", choices=["mobilerun", "deterministic"], default=None)
    run.add_argument("--dry-run", action="store_true")

    run_keyword = subparsers.add_parser(
        "run-keyword", help="Run keyword-only text search collection"
    )
    run_keyword.add_argument("--keyword", required=True)
    run_keyword.add_argument("--config", type=Path, default=None)
    run_keyword.add_argument("--top-n", type=int, default=None)
    run_keyword.add_argument(
        "--mode", choices=["deterministic"], default="deterministic"
    )
    return parser


def _format_cli_error(exc: Exception) -> str:
    message = str(exc)
    if "No package metadata was found for mobilerun" in message or "No module named 'mobilerun" in message:
        return json.dumps(
            {
                "status": "environment_blocker",
                "blocker": "mobilerun_missing",
                "message": "mobilerun is not installed or not importable from third_party/mobilerun-main.",
                "next_action": "Install or expose third_party/mobilerun-main before running doctor or real-device collection.",
            },
            ensure_ascii=False,
            indent=2,
        )
    return f"error: {message}"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            config = load_config(args.config)
            payload = asyncio.run(run_doctor(config))
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if args.command == "validate":
            config = load_config(args.config)
            items = validate_input(args.input, config)
            print(
                json.dumps(
                    {
                        "status": "ok",
                        "item_count": len(items),
                        "items": [
                            {
                                "item_id": item.item_id,
                                "keyword": item.keyword,
                                "top_n": item.top_n,
                                "reference_image": str(item.reference_image),
                            }
                            for item in items
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "calibrate":
            output = calibrate(args.output)
            print(
                json.dumps(
                    {"status": "ok", "coordinate_profile": str(output)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "calibrate-search-box":
            config = load_config(args.config)
            if (args.x is None) != (args.y is None):
                raise ValueError("--x and --y must be provided together")
            payload = calibrate_search_box_on_device(
                profile_path=config.deterministic.coordinate_profile,
                output_dir=args.output_dir,
                xhs_package=config.xhs_package,
                device_serial=config.device_serial,
                pixel_x=args.x,
                pixel_y=args.y,
                click=not args.no_click,
                wait_seconds=args.wait_seconds,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if args.command == "calibrate-point":
            config = load_config(args.config)
            if (args.x is None) != (args.y is None):
                raise ValueError("--x and --y must be provided together")
            output_dir = args.output_dir or Path("calibration") / args.point
            payload = calibrate_point_on_device(
                point_name=args.point,
                profile_path=config.deterministic.coordinate_profile,
                output_dir=output_dir,
                xhs_package=config.xhs_package,
                device_serial=config.device_serial,
                pixel_x=args.x,
                pixel_y=args.y,
                click=not args.no_click,
                start_app=args.start_app,
                wait_seconds=args.wait_seconds,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if args.command == "calibrate-flow":
            config = load_config(args.config)
            payload = calibrate_flow_on_device(
                profile_path=config.deterministic.coordinate_profile,
                output_dir=args.output_dir,
                xhs_package=config.xhs_package,
                device_serial=config.device_serial,
                points=args.points,
                wait_seconds=args.wait_seconds,
                start_app=not args.no_start_app,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if args.command == "run":
            manifest = (
                run_dry_collect(
                    args.input,
                    args.config,
                    args.top_n,
                    args.keyword_top_n,
                    image_top_n=args.image_top_n,
                    keyword_result_top_n=args.keyword_result_top_n,
                )
                if args.dry_run
                else run_collect(
                    args.input,
                    args.config,
                    args.top_n,
                    keyword_top_n=args.keyword_top_n,
                    image_top_n=args.image_top_n,
                    keyword_result_top_n=args.keyword_result_top_n,
                    mode=args.mode,
                )
            )
            print(
                json.dumps(
                    {
                        "status": manifest.status,
                        "run_id": manifest.run_id,
                        "output_dir": str(manifest.output_dir),
                        "result_count": len(manifest.results),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "run-keyword":
            manifest = run_collect_keyword(
                args.keyword,
                args.config,
                args.top_n,
                mode=args.mode,
            )
            print(
                json.dumps(
                    {
                        "status": manifest.status,
                        "run_id": manifest.run_id,
                        "output_dir": str(manifest.output_dir),
                        "result_count": len(manifest.results),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
    except Exception as exc:
        print(_format_cli_error(exc), flush=True)
        return 1
    parser.error(f"unknown command: {args.command}")
    return 2
