from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    from xhs_collector.models import InputItem
except ImportError:  # pragma: no cover - used from the monorepo without install
    from third_party.xhs_collector.xhs_collector.models import InputItem


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass(frozen=True)
class UploadedImage:
    filename: str
    content_base64: str
    keyword_candidates: list[str] = field(default_factory=list)
    description: str = ""
    item_id: str | None = None

    @classmethod
    def from_payload(cls, payload: dict) -> "UploadedImage":
        return cls(
            filename=str(payload.get("filename") or "image.png"),
            content_base64=str(
                payload.get("contentBase64")
                or payload.get("content_base64")
                or payload.get("data")
                or ""
            ),
            keyword_candidates=[
                str(value).strip()
                for value in (
                    payload.get("keywordCandidates")
                    or payload.get("keyword_candidates")
                    or []
                )
                if str(value).strip()
            ],
            description=str(payload.get("description") or ""),
            item_id=(
                str(payload.get("itemId") or payload.get("item_id")).strip()
                if payload.get("itemId") or payload.get("item_id")
                else None
            ),
        )


def create_items_from_uploaded_images(
    images: list[UploadedImage], job_dir: Path, image_top_n: int
) -> list[InputItem]:
    if not images:
        raise ValueError("at least one image is required")
    items: list[InputItem] = []
    for index, image in enumerate(images, start=1):
        payload = _decode_base64_payload(image.content_base64)
        suffix = _safe_suffix(Path(image.filename).suffix)
        item_id = _safe_item_id(image.item_id or Path(image.filename).stem or f"image-{index}")
        if any(existing.item_id == item_id for existing in items):
            item_id = f"{item_id}-{index}"
        item_dir = job_dir / "inputs" / item_id
        item_dir.mkdir(parents=True, exist_ok=True)
        reference_image = item_dir / f"reference{suffix}"
        reference_image.write_bytes(payload)
        keyword_candidates = image.keyword_candidates
        keyword = keyword_candidates[0] if keyword_candidates else ""
        items.append(
            InputItem(
                item_id=item_id,
                keyword=keyword,
                keyword_candidates=keyword_candidates,
                description=image.description,
                reference_image=reference_image,
                top_n=image_top_n,
                source_row=index,
            )
        )
    return items


def uploaded_images_from_payload(payload: dict) -> list[UploadedImage]:
    raw_images = payload.get("images")
    if raw_images is None and payload.get("image") is not None:
        raw_images = [payload["image"]]
    return [UploadedImage.from_payload(raw) for raw in (raw_images or [])]


def write_config_file_from_payload(payload: dict, job_dir: Path) -> Path:
    config_file = payload.get("configFile") or payload.get("config_file")
    project_files = payload.get("projectFiles") or payload.get("project_files") or []
    if not config_file and project_files:
        return _write_project_folder_files(project_files, job_dir)
    if not config_file:
        raise ValueError("configFile is required for config_file mode")
    filename = str(config_file.get("filename") or "input.xlsx")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".xlsx", ".xlsm"}:
        raise ValueError("configFile must be an .xlsx workbook")
    content = _decode_base64_payload(
        str(
            config_file.get("contentBase64")
            or config_file.get("content_base64")
            or config_file.get("data")
            or ""
        )
    )
    target_dir = job_dir / "uploads"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / _safe_filename(filename)
    target.write_bytes(content)
    for sidecar in payload.get("configImages") or payload.get("config_images") or []:
        sidecar_name = _safe_filename(str(sidecar.get("filename") or "image.png"))
        sidecar_content = _decode_base64_payload(
            str(
                sidecar.get("contentBase64")
                or sidecar.get("content_base64")
                or sidecar.get("data")
                or ""
            )
        )
        (target_dir / sidecar_name).write_bytes(sidecar_content)
    return target


def _write_project_folder_files(project_files: list[dict], job_dir: Path) -> Path:
    target_dir = job_dir / "uploads"
    target_dir.mkdir(parents=True, exist_ok=True)
    workbook_entries = [
        entry
        for entry in project_files
        if _is_workbook_name(_payload_filename(entry))
        and not _is_office_temp_name(_payload_filename(entry))
    ]
    if not workbook_entries:
        raise ValueError("project folder must contain one .xlsx or .xlsm workbook")
    if len(workbook_entries) > 1:
        names = ", ".join(_payload_filename(entry) for entry in workbook_entries)
        raise ValueError(f"project folder must contain exactly one workbook, found: {names}")

    workbook_path: Path | None = None
    for entry in project_files:
        filename = _payload_filename(entry)
        if not (
            _is_workbook_name(filename)
            or Path(filename).suffix.lower() in IMAGE_SUFFIXES
        ):
            continue
        if _is_office_temp_name(filename):
            continue
        relative_path = _safe_relative_path(entry)
        target = target_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        content = _decode_base64_payload(
            str(
                entry.get("contentBase64")
                or entry.get("content_base64")
                or entry.get("data")
                or ""
            )
        )
        target.write_bytes(content)
        if entry is workbook_entries[0]:
            workbook_path = target
    if workbook_path is None:
        raise ValueError("project folder workbook was not written")
    return workbook_path


def _payload_filename(payload: dict) -> str:
    return str(payload.get("filename") or Path(str(payload.get("relativePath") or "")).name)


def _is_workbook_name(filename: str) -> bool:
    return Path(filename).suffix.lower() in {".xlsx", ".xlsm"}


def _is_office_temp_name(filename: str) -> bool:
    name = Path(filename).name
    return name.startswith(".~") or name.startswith("~$")


def _safe_relative_path(payload: dict) -> Path:
    value = str(
        payload.get("relativePath")
        or payload.get("relative_path")
        or payload.get("filename")
        or "file"
    )
    path = Path(value)
    parts = [
        _safe_filename(part)
        for part in path.parts
        if part not in {"", ".", "..", path.anchor}
    ]
    if not parts:
        parts = [_safe_filename(_payload_filename(payload))]
    return Path(*parts)


def _decode_base64_payload(value: str) -> bytes:
    if not value:
        raise ValueError("image content is empty")
    _, _, maybe_payload = value.partition(",")
    encoded = maybe_payload if value.startswith("data:") else value
    return base64.b64decode(encoded, validate=True)


def _safe_suffix(value: str) -> str:
    suffix = value.lower()
    return suffix if suffix in IMAGE_SUFFIXES else ".png"


def _safe_item_id(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "-", value).strip("-._")
    return slug or "image"


def _safe_filename(value: str) -> str:
    name = Path(value).name
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._ -]+", "-", name).strip() or "input.xlsx"
