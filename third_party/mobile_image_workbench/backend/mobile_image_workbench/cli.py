from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path

from .env import load_env_file, load_package_env
from .scene_tagger import default_vlm_model


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNS_ROOT = PACKAGE_ROOT / "runs"
DEFAULT_STATIC_ROOT = PACKAGE_ROOT / "frontend" / "dist"
DEFAULT_CONFIG = PACKAGE_ROOT / "config" / "defaults.json"


class _WorkbenchArgumentParser(argparse.ArgumentParser):
    def parse_args(self, args=None, namespace=None):
        parsed = super().parse_args(args, namespace)
        _load_cli_env(parsed.env_file)
        if getattr(parsed, "command", "") == "tag-scenes" and parsed.model is None:
            parsed.model = default_vlm_model()
        return parsed


def build_parser(argv: list[str] | None = None) -> argparse.ArgumentParser:
    env_file = _env_file_from_argv(argv)
    _load_cli_env(env_file)
    parser = _WorkbenchArgumentParser(prog="mobile_image_workbench")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=env_file,
        help="Load a workbench dotenv file before command defaults are evaluated.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="Start the local workbench")
    _add_env_file_arg(serve_parser)
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    serve_parser.add_argument("--static-root", type=Path, default=DEFAULT_STATIC_ROOT)
    serve_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)

    run_parser = subparsers.add_parser("run", help="Create and run one job")
    _add_env_file_arg(run_parser)
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
    _add_env_file_arg(export_parser)
    export_parser.add_argument("--run-dir", type=Path, required=True)

    sync_parser = subparsers.add_parser("sync", help="Ingest a collector run into the asset center")
    _add_env_file_arg(sync_parser)
    sync_parser.add_argument("--run-dir", type=Path, required=True)
    sync_parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    sync_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sync_parser.add_argument("--job-id", default="")
    sync_parser.add_argument("--category", default="")
    sync_parser.add_argument("--scene", default="")
    sync_parser.add_argument("--input-mode", default="")
    sync_parser.add_argument("--uploaded-by", default="")

    tag_parser = subparsers.add_parser("tag-scenes", help="Generate local VLM scene tags for ingested assets")
    _add_env_file_arg(tag_parser)
    tag_parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    tag_parser.add_argument("--category", default="")
    tag_parser.add_argument("--run-id", default="")
    tag_parser.add_argument("--job-id", default="")
    tag_parser.add_argument("--limit", type=int, default=100)
    tag_parser.add_argument("--provider", choices=["rule", "openai_compatible"], default="openai_compatible")
    tag_parser.add_argument("--model", default=None)
    tag_parser.add_argument("--retry-failed", action="store_true")
    tag_parser.add_argument("--force", action="store_true")
    tag_parser.add_argument("--debug-request", action="store_true")
    tag_parser.add_argument("--dry-run", action="store_true")

    cloud_parser = subparsers.add_parser("sync-cloud", help="Sync local asset center records to a cloud asset center")
    _add_env_file_arg(cloud_parser)
    cloud_parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    cloud_parser.add_argument("--server-url", required=True)
    cloud_parser.add_argument("--token", required=True)
    cloud_parser.add_argument("--collector-id", required=True)
    cloud_parser.add_argument("--category", default="")
    cloud_parser.add_argument("--job-id", default="")
    cloud_parser.add_argument("--batch-size", type=int, default=100)

    deploy_parser = subparsers.add_parser(
        "deploy-mac-mini",
        help="Rsync the current repo to the configured Mac mini and restart the workbench.",
    )
    _add_env_file_arg(deploy_parser)
    deploy_parser.add_argument("--repo-root", type=Path, default=None)
    deploy_parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(argv)
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            from .server import serve

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
            from .jobs import JobManager

            manager = JobManager(args.runs_root, base_collector_config=args.config)
            payload = _payload_from_run_args(args)
            record = manager.create_job(payload, start=False)
            result = manager.run_job(record.job_id)
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
            return 0 if result.status in {"completed", "partial"} else 1
        if args.command == "export":
            from .exports import write_result_exports

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
        if args.command == "sync":
            from .jobs import JobManager

            manager = JobManager(args.runs_root, base_collector_config=args.config)
            summary = manager.ingest_assets(
                args.run_dir,
                job_id=args.job_id,
                category=args.category,
                scene=args.scene,
                input_mode=args.input_mode,
                uploaded_by=args.uploaded_by,
            )
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0
        if args.command == "tag-scenes":
            from .cloud_sync import build_local_asset_library
            from .scene_tagger import build_scene_tagger, tag_missing_scene_assets

            library = build_local_asset_library(args.runs_root)
            summary = tag_missing_scene_assets(
                library,
                build_scene_tagger(args.provider, model=args.model),
                category=args.category,
                run_id=args.run_id,
                job_id=args.job_id,
                limit=args.limit,
                dry_run=args.dry_run,
                retry_failed=args.retry_failed,
                force=args.force,
                debug_request=args.debug_request,
            )
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0 if summary.get("failed", 0) == 0 else 1
        if args.command == "sync-cloud":
            from .cloud_sync import sync_cloud_bundle

            summary = sync_cloud_bundle(
                runs_root=args.runs_root,
                server_url=args.server_url,
                token=args.token,
                collector_id=args.collector_id,
                category=args.category,
                job_id=args.job_id,
                batch_size=args.batch_size,
            )
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0
        if args.command == "deploy-mac-mini":
            from .admin import AdminTaskManager, default_repo_root

            repo_root = (args.repo_root or default_repo_root()).resolve()
            admin = AdminTaskManager(repo_root, run_async=False)
            task = admin.start_mac_mini_remote_deploy()
            if args.json:
                print(json.dumps(task, ensure_ascii=False, indent=2))
            else:
                print(_format_admin_task(task), end="")
            return 0 if task.get("status") == "completed" else 1
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"error: {exc}", flush=True)
        return 1
    parser.error(f"unknown command: {args.command}")
    return 2


def _env_file_from_argv(argv: list[str] | None) -> Path | None:
    if argv is None:
        return None
    for index, value in enumerate(argv):
        if value == "--env-file" and index + 1 < len(argv):
            return Path(argv[index + 1])
        if value.startswith("--env-file="):
            return Path(value.split("=", 1)[1])
    return None


def _load_cli_env(env_file: Path | None) -> dict[str, str]:
    original_env = dict(os.environ)
    loaded = load_package_env(PACKAGE_ROOT)
    if env_file is not None:
        explicit = load_env_file(env_file, override=True)
        for name, value in original_env.items():
            if name in explicit:
                os.environ[name] = value
                explicit.pop(name, None)
        loaded.update(explicit)
    return loaded


def _add_env_file_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--env-file",
        type=Path,
        default=argparse.SUPPRESS,
        help="Load a workbench dotenv file for this command.",
    )


def _format_admin_task(task: dict) -> str:
    lines = [
        f"Task: {task.get('taskId', '')}",
        f"Kind: {task.get('kind', '')}",
        f"Status: {task.get('status', '')}",
    ]
    message = str(task.get("message", ""))
    if message:
        lines.append(f"Message: {message}")
    summary = task.get("summary")
    if isinstance(summary, dict) and summary:
        lines.append("Summary:")
        for key, value in summary.items():
            lines.append(f"- {key}: {value}")
    exit_code = task.get("exitCode")
    if exit_code is not None:
        lines.append(f"Exit code: {exit_code}")
    logs = task.get("logs")
    if isinstance(logs, list) and logs:
        lines.append("")
        lines.append("Logs:")
        for item in logs[-20:]:
            lines.append(str(item))
    return "\n".join(lines).rstrip() + "\n"


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
