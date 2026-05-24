from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

from .exports import write_result_exports
from .jobs import JobManager
from .server import serve


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNS_ROOT = PACKAGE_ROOT / "runs"
DEFAULT_STATIC_ROOT = PACKAGE_ROOT / "frontend" / "dist"
DEFAULT_CONFIG = PACKAGE_ROOT / "config" / "defaults.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mobile_image_workbench")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="Start the local workbench")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    serve_parser.add_argument("--static-root", type=Path, default=DEFAULT_STATIC_ROOT)
    serve_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)

    run_parser = subparsers.add_parser("run", help="Create and run one job")
    run_parser.add_argument("--mode", choices=["single_image", "batch_images", "config_file"], required=True)
    run_parser.add_argument("--input", type=Path, nargs="+", required=True)
    run_parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    run_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    run_parser.add_argument("--image-top-n", type=int, default=None)
    run_parser.add_argument("--keyword-top-n", type=int, default=None)
    run_parser.add_argument("--keyword-result-top-n", type=int, default=None)
    run_parser.add_argument("--device-serial", default=None)
    run_parser.add_argument("--dry-run", action="store_true")

    export_parser = subparsers.add_parser("export", help="Regenerate result exports")
    export_parser.add_argument("--run-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            server = serve(
                host=args.host,
                port=args.port,
                runs_root=args.runs_root,
                static_root=args.static_root,
                base_collector_config=args.config,
            )
            print(f"mobile image workbench: http://{args.host}:{args.port}", flush=True)
            server.serve_forever()
            return 0
        if args.command == "run":
            manager = JobManager(args.runs_root, base_collector_config=args.config)
            payload = _payload_from_run_args(args)
            record = manager.create_job(payload, start=False)
            result = manager.run_job(record.job_id)
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
            return 0 if result.status in {"completed", "partial"} else 1
        if args.command == "export":
            outputs = write_result_exports(args.run_dir)
            print(
                json.dumps(
                    {
                        "html": str(outputs.html_path),
                        "csv": str(outputs.csv_path),
                        "zip": str(outputs.zip_path),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"error: {exc}", flush=True)
        return 1
    parser.error(f"unknown command: {args.command}")
    return 2


def _payload_from_run_args(args: argparse.Namespace) -> dict:
    settings = {
        "mode": args.mode,
        "dryRun": args.dry_run,
    }
    if args.image_top_n is not None:
        settings["imageTopN"] = args.image_top_n
    if args.keyword_top_n is not None:
        settings["keywordTopN"] = args.keyword_top_n
    if args.keyword_result_top_n is not None:
        settings["keywordResultTopN"] = args.keyword_result_top_n
    if args.device_serial:
        settings["deviceSerial"] = args.device_serial
    if args.mode == "config_file":
        if len(args.input) != 1:
            raise ValueError("config_file mode accepts exactly one input workbook")
        return {
            "mode": args.mode,
            "settings": settings,
            "configFile": _file_payload(args.input[0]),
        }
    images = [_file_payload(path) for path in args.input]
    if args.mode == "single_image":
        images = images[:1]
    return {"mode": args.mode, "settings": settings, "images": images}


def _file_payload(path: Path) -> dict:
    return {
        "filename": path.name,
        "contentBase64": base64.b64encode(path.read_bytes()).decode("ascii"),
    }
