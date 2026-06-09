from __future__ import annotations

import csv
import hashlib
import html
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .models import TaobaoAsset, TaobaoManifest


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(data), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def append_jsonl(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_jsonable(event), ensure_ascii=False) + "\n")


def write_manifest(manifest: TaobaoManifest) -> None:
    write_json(manifest.output_dir / "manifest.json", manifest)


def write_exports(manifest: TaobaoManifest) -> None:
    _write_csv(manifest.output_dir / "results.csv", manifest.assets)
    _write_html(manifest.output_dir / "results.html", manifest)


def write_captured_asset(
    *,
    manifest: TaobaoManifest,
    source_item_id: str,
    query: str,
    stage: str,
    rank: int,
    image_type: str,
    payload: bytes,
) -> TaobaoAsset:
    suffix = ".png"
    filename = f"{source_item_id}_{stage}_rank_{rank:03d}_{image_type}{suffix}"
    target = manifest.output_dir / "images" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    digest = sha256_bytes(payload)
    asset = TaobaoAsset(
        asset_id=f"{source_item_id}-{stage}-{rank:03d}-{image_type}",
        channel="taobao",
        mode=manifest.mode,
        source_item_id=source_item_id,
        query=query,
        stage=stage,
        rank=rank,
        local_path=target,
        content_sha256=digest,
        image_type=image_type,
    )
    manifest.assets.append(asset)
    return asset


def write_file_asset(
    *,
    manifest: TaobaoManifest,
    source_item_id: str,
    query: str,
    stage: str,
    rank: int,
    image_type: str,
    local_path: Path,
) -> TaobaoAsset:
    payload = local_path.read_bytes()
    asset = TaobaoAsset(
        asset_id=f"{source_item_id}-{stage}-{rank:03d}-{image_type}",
        channel="taobao",
        mode=manifest.mode,
        source_item_id=source_item_id,
        query=query,
        stage=stage,
        rank=rank,
        local_path=local_path,
        content_sha256=sha256_bytes(payload),
        image_type=image_type,
    )
    manifest.assets.append(asset)
    return asset


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_csv(path: Path, assets: list[TaobaoAsset]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "channel",
                "mode",
                "source_item_id",
                "query",
                "stage",
                "rank",
                "image_type",
                "local_path",
                "content_sha256",
                "status",
                "message",
            ],
        )
        writer.writeheader()
        for asset in assets:
            writer.writerow(
                {
                    "channel": asset.channel,
                    "mode": asset.mode,
                    "source_item_id": asset.source_item_id,
                    "query": asset.query,
                    "stage": asset.stage,
                    "rank": asset.rank,
                    "image_type": asset.image_type,
                    "local_path": str(asset.local_path),
                    "content_sha256": asset.content_sha256,
                    "status": asset.status,
                    "message": asset.message,
                }
            )


def _write_html(path: Path, manifest: TaobaoManifest) -> None:
    cards = "\n".join(_asset_card(manifest.output_dir, asset) for asset in manifest.assets)
    if not cards:
        cards = '<p class="empty">暂无采集图片。请查看 manifest.json 和 debug 目录中的失败原因。</p>'
    path.write_text(
        f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>淘宝采集结果</title>
  <style>
    body {{ margin: 24px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #1f2933; background: #f6f7f9; }}
    h1 {{ margin: 0 0 8px; font-size: 22px; }}
    .meta {{ margin-bottom: 18px; color: #5f6c7b; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; }}
    article {{ background: #fff; border: 1px solid #d8dee8; border-radius: 8px; overflow: hidden; }}
    img {{ width: 100%; aspect-ratio: 1 / 1; object-fit: cover; background: #eef2f6; }}
    .body {{ display: grid; gap: 4px; padding: 10px; font-size: 13px; }}
    .body strong {{ font-size: 14px; }}
    .body span {{ color: #5f6c7b; }}
    .empty {{ color: #8a96a3; }}
  </style>
</head>
<body>
  <h1>淘宝采集结果</h1>
  <div class="meta">Run: {html.escape(manifest.run_id)} · Status: {html.escape(manifest.status)} · Mode: {html.escape(manifest.mode)}</div>
  <section class="grid">{cards}</section>
</body>
</html>
""",
        encoding="utf-8",
    )


def _asset_card(run_dir: Path, asset: TaobaoAsset) -> str:
    src = _asset_url(run_dir, asset.local_path)
    return f"""<article>
  <a href="{src}" target="_blank"><img src="{src}" alt="{html.escape(asset.stage)}"></a>
  <div class="body">
    <strong>{html.escape(asset.stage)} · Rank {asset.rank}</strong>
    <span>{html.escape(asset.query or "no query")}</span>
    <span>{html.escape(asset.image_type)} · {html.escape(asset.content_sha256[:12])}</span>
  </div>
</article>"""


def _asset_url(run_dir: Path, path: Path) -> str:
    try:
        relative = path.resolve().relative_to(run_dir.resolve())
    except ValueError:
        relative = path
    return quote(str(relative).replace("\\", "/"))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return {key: _jsonable(val) for key, val in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value
