from __future__ import annotations

import csv
import html
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote


@dataclass(frozen=True)
class ExportOutputs:
    html_path: Path
    csv_path: Path
    zip_path: Path


def write_result_exports(run_dir: Path) -> ExportOutputs:
    run_dir = run_dir.resolve()
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = _result_rows(run_dir, manifest)
    html_path = run_dir / "results.html"
    csv_path = run_dir / "results.csv"
    zip_path = run_dir / "results_images.zip"
    _write_html(html_path, rows, manifest)
    _write_csv(csv_path, rows)
    _write_zip(zip_path, run_dir, rows)
    return ExportOutputs(html_path=html_path, csv_path=csv_path, zip_path=zip_path)


def _result_rows(run_dir: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in manifest.get("results", []):
        item_id = str(result.get("item_id") or "")
        original = _find_reference_image(run_dir, item_id)
        images = [
            {
                "path": _relative_path(run_dir, str(image.get("local_path") or "")),
                "stage": image.get("stage") or "image_search",
                "query": image.get("query") or "",
                "rank": image.get("rank"),
                "keyword_index": image.get("keyword_index"),
            }
            for image in result.get("images", [])
        ]
        rows.append(
            {
                "item_id": item_id,
                "keyword": result.get("keyword") or "",
                "status": result.get("status") or "",
                "original_image": original,
                "collected_images": images,
            }
        )
    return rows


def _write_html(path: Path, rows: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    body_rows = "\n".join(_html_row(row) for row in rows)
    path.write_text(
        f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>移动端图片采集结果</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #1f2933; background: #f6f7f9; }}
    h1 {{ font-size: 22px; margin: 0 0 8px; }}
    .meta {{ color: #5f6c7b; margin-bottom: 18px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d8dee8; }}
    th, td {{ padding: 12px; border-bottom: 1px solid #e6eaf0; vertical-align: top; text-align: left; }}
    th {{ background: #eef2f6; font-size: 13px; color: #425466; }}
    img {{ max-width: 140px; max-height: 140px; object-fit: cover; border: 1px solid #d8dee8; border-radius: 6px; }}
    .gallery {{ display: flex; flex-wrap: wrap; gap: 10px; }}
    .shot {{ width: 150px; }}
    .shot small {{ display: block; color: #5f6c7b; line-height: 1.4; }}
    .image-cell {{ display: inline-grid; gap: 8px; }}
    .preview-trigger {{ display: inline-flex; padding: 0; border: 0; background: transparent; cursor: zoom-in; }}
    .download-link {{ display: inline-flex; align-items: center; justify-content: center; min-height: 30px; padding: 0 10px; border-radius: 6px; background: #eef2f6; color: #243b53; text-decoration: none; font-size: 13px; }}
    .modal {{ position: fixed; inset: 0; display: none; place-items: center; padding: 24px; background: rgba(15, 23, 42, 0.78); z-index: 20; }}
    .modal.open {{ display: grid; }}
    .modal-panel {{ max-width: min(92vw, 980px); max-height: 92vh; display: grid; gap: 10px; }}
    .modal-header {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; color: #fff; }}
    .modal-title {{ font-weight: 600; }}
    .modal-close {{ min-width: 36px; height: 36px; border: 0; border-radius: 999px; background: #fff; color: #1f2933; font-size: 22px; line-height: 1; }}
    .modal img {{ max-width: 100%; max-height: 78vh; object-fit: contain; background: #fff; }}
    .empty {{ color: #8a96a3; }}
  </style>
</head>
<body>
  <h1>移动端图片采集结果</h1>
  <div class="meta">Run: {html.escape(str(manifest.get("run_id", "")))} · Status: {html.escape(str(manifest.get("status", "")))}</div>
  <table>
    <thead><tr><th>原始图片</th><th>采集图片列表</th></tr></thead>
    <tbody>{body_rows}</tbody>
  </table>
  <div id="image-preview-modal" class="modal" aria-hidden="true">
    <div class="modal-panel" role="dialog" aria-modal="true" aria-label="图片预览">
      <div class="modal-header">
        <div id="image-preview-title" class="modal-title"></div>
        <button id="image-preview-close" class="modal-close" type="button" aria-label="关闭">×</button>
      </div>
      <img id="image-preview-img" src="" alt="放大预览">
    </div>
  </div>
  <script>
    const modal = document.getElementById('image-preview-modal');
    const modalImage = document.getElementById('image-preview-img');
    const modalTitle = document.getElementById('image-preview-title');
    const closeButton = document.getElementById('image-preview-close');
    function closePreview() {{
      modal.classList.remove('open');
      modal.setAttribute('aria-hidden', 'true');
      modalImage.src = '';
    }}
    document.querySelectorAll('.preview-trigger').forEach((button) => {{
      button.addEventListener('click', () => {{
        modalImage.src = button.dataset.previewSrc;
        modalTitle.textContent = button.dataset.previewTitle || '图片预览';
        modal.classList.add('open');
        modal.setAttribute('aria-hidden', 'false');
      }});
    }});
    closeButton.addEventListener('click', closePreview);
    modal.addEventListener('click', (event) => {{
      if (event.target === modal) closePreview();
    }});
    document.addEventListener('keydown', (event) => {{
      if (event.key === 'Escape') closePreview();
    }});
  </script>
</body>
</html>
""",
        encoding="utf-8",
    )


def _html_row(row: dict[str, Any]) -> str:
    original = _asset_src(row["original_image"])
    original_html = (
        _image_action_html(
            src=original,
            alt="原始图片",
            title=f"原始图片 · {row['item_id']}",
            relative_path=row["original_image"],
        )
        + f"<div>{html.escape(row['item_id'])}</div>"
        if original
        else '<span class="empty">未找到原图</span>'
    )
    if row["collected_images"]:
        images_html = '<div class="gallery">' + "".join(
            _collected_image_html(image) for image in row["collected_images"]
        ) + "</div>"
    else:
        images_html = '<span class="empty">暂无采集图片</span>'
    return f"<tr><td>{original_html}</td><td>{images_html}</td></tr>"


def _collected_image_html(image: dict[str, Any]) -> str:
    path = _asset_src(image["path"])
    label = "图搜结果"
    if image["stage"] == "keyword_search":
        label = f"关键词 {image.get('keyword_index') or ''}: {image.get('query') or ''}"
    title = f"{label} · Rank {image.get('rank') or ''}"
    return (
        f'<div class="shot">'
        + _image_action_html(
            src=path,
            alt="采集图片",
            title=title,
            relative_path=image["path"],
        )
        + f"<small>{html.escape(label)} · Rank {html.escape(str(image.get('rank') or ''))}</small></div>"
    )


def _image_action_html(
    *, src: str, alt: str, title: str, relative_path: str
) -> str:
    escaped_title = html.escape(title, quote=True)
    escaped_alt = html.escape(alt, quote=True)
    download_name = _download_name(relative_path)
    return (
        '<div class="image-cell">'
        f'<button class="preview-trigger" type="button" data-preview-src="{src}" '
        f'data-preview-title="{escaped_title}">'
        f'<img src="{src}" alt="{escaped_alt}">'
        "</button>"
        f'<a class="download-link" href="{src}" download="{download_name}">下载</a>'
        "</div>"
    )


def _asset_src(relative_path: str) -> str:
    if not relative_path:
        return ""
    return html.escape("assets/" + quote(relative_path, safe="/"), quote=True)


def _download_name(relative_path: str) -> str:
    return html.escape(Path(relative_path).name, quote=True)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["original_image", "collected_images"])
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "original_image": row["original_image"],
                    "collected_images": ";".join(
                        image["path"] for image in row["collected_images"]
                    ),
                }
            )


def _write_zip(path: Path, run_dir: Path, rows: list[dict[str, Any]]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for row in rows:
            if row["original_image"]:
                _zip_relative(archive, run_dir, row["original_image"])
            for image in row["collected_images"]:
                _zip_relative(archive, run_dir, image["path"])


def _zip_relative(archive: zipfile.ZipFile, run_dir: Path, relative_path: str) -> None:
    path = run_dir / relative_path
    if path.exists() and path.is_file():
        archive.write(path, relative_path)


def _find_reference_image(run_dir: Path, item_id: str) -> str:
    input_dir = run_dir / "inputs" / item_id
    for path in sorted(input_dir.glob("reference.*")):
        return _relative_path(run_dir, str(path))
    return ""


def _relative_path(run_dir: Path, value: str) -> str:
    if not value:
        return ""
    path = Path(value)
    if not path.is_absolute():
        return path.as_posix()
    path = path.resolve()
    try:
        return path.relative_to(run_dir).as_posix()
    except ValueError:
        return path.as_posix()
