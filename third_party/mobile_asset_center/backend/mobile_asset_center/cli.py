from __future__ import annotations

import argparse
import os
from pathlib import Path

from .server import serve


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FRONTEND = PACKAGE_ROOT / "frontend"
DEFAULT_DATA_ROOT = PACKAGE_ROOT / "data"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mobile_asset_center")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8876)
    serve_parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    serve_parser.add_argument("--static-root", type=Path, default=DEFAULT_FRONTEND)
    serve_parser.add_argument("--sync-token", default=os.environ.get("ASSET_CENTER_SYNC_TOKEN", ""))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        server = serve(
            host=args.host,
            port=args.port,
            data_root=args.data_root,
            static_root=args.static_root,
            sync_token=args.sync_token,
        )
        print(f"mobile asset center: http://{args.host}:{args.port}", flush=True)
        server.serve_forever()
    return 0
