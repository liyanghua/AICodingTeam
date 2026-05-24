from __future__ import annotations

import posixpath
import re
import shutil
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .models import InputItem

SHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
OD_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
XDR_NS = "{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}"
TRUTHY = {"1", "true", "yes", "y", "on", "是", "启用"}
FALSY = {"0", "false", "no", "n", "off", "否", "禁用", "skip"}
KEYWORD_COLUMNS = {"keyword", "keywords"}


def read_input_excel(
    excel_path: Path, output_input_dir: Path, default_top_n: int
) -> list[InputItem]:
    if not excel_path.exists():
        raise FileNotFoundError(f"input excel not found: {excel_path}")
    if excel_path.stat().st_size == 0:
        raise ValueError("invalid xlsx: file is empty")
    try:
        with zipfile.ZipFile(excel_path) as archive:
            sheet_path, rows = _read_first_sheet_rows(archive)
            embedded_images = _extract_embedded_images(archive, sheet_path)
    except zipfile.BadZipFile as exc:
        raise ValueError("invalid xlsx: not a zip workbook") from exc

    if not rows:
        return []
    header = [_normalize_header(value) for value in rows[0]]
    if not KEYWORD_COLUMNS.intersection(header):
        raise ValueError("missing required column: keyword or keywords")

    items: list[InputItem] = []
    for offset, raw_values in enumerate(rows[1:], start=2):
        row = _row_dict(header, raw_values)
        if not _row_enabled(row.get("enabled", "yes")):
            continue
        keyword_candidates = _parse_keyword_candidates(
            row.get("keywords", "") or row.get("keyword", "")
        )
        keyword = row.get("keyword", "").strip()
        if not keyword and keyword_candidates:
            keyword = keyword_candidates[0]
        if not keyword:
            continue
        item_id = row.get("item_id", "").strip() or f"row-{offset}"
        image_path_value = row.get("image_path", "").strip()
        if item_id.startswith("row-") and image_path_value:
            item_id = Path(image_path_value).stem
        item_id = _safe_item_id(item_id)
        top_n = int(row.get("top_n", "").strip() or default_top_n)
        if top_n < 1:
            raise ValueError(f"row {offset}: top_n must be >= 1")
        reference_image = _copy_reference_image(
            row=row,
            excel_path=excel_path,
            item_dir=output_input_dir / item_id,
            embedded_images=embedded_images,
            row_number=offset,
        )
        items.append(
            InputItem(
                item_id=item_id,
                keyword=keyword,
                keyword_candidates=keyword_candidates or [keyword],
                description=row.get("description", "").strip(),
                reference_image=reference_image,
                top_n=top_n,
                source_row=offset,
            )
        )
    return items


def _read_first_sheet_rows(archive: zipfile.ZipFile) -> tuple[str, list[list[str]]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_targets = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
    first_sheet = workbook.find(f"{SHEET_NS}sheets/{SHEET_NS}sheet")
    if first_sheet is None:
        return "", []
    rel_id = first_sheet.attrib[f"{OD_REL_NS}id"]
    target = rel_targets[rel_id]
    sheet_path = _resolve_xl_target(target)
    shared_strings = _read_shared_strings(archive)
    sheet = ET.fromstring(archive.read(sheet_path))
    parsed_rows: list[list[str]] = []
    for row in sheet.findall(f"{SHEET_NS}sheetData/{SHEET_NS}row"):
        values_by_index: dict[int, str] = {}
        for cell in row.findall(f"{SHEET_NS}c"):
            column_index = _cell_column_index(cell.attrib.get("r", "A1"))
            values_by_index[column_index] = _cell_value(cell, shared_strings)
        if values_by_index:
            max_index = max(values_by_index)
            parsed_rows.append(
                [values_by_index.get(index, "") for index in range(1, max_index + 1)]
            )
    return sheet_path, parsed_rows


def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    strings: list[str] = []
    for item in root.findall(f"{SHEET_NS}si"):
        strings.append("".join(text.text or "" for text in item.iter(f"{SHEET_NS}t")))
    return strings


def _extract_embedded_images(
    archive: zipfile.ZipFile, sheet_path: str
) -> dict[int, tuple[str, bytes]]:
    anchored = _extract_anchored_images(archive, sheet_path)
    if anchored:
        return anchored

    media_names = sorted(
        name
        for name in archive.namelist()
        if name.startswith("xl/media/") and not name.endswith("/")
    )
    return {
        index: (Path(name).suffix or ".bin", archive.read(name))
        for index, name in enumerate(media_names, start=2)
    }


def _extract_anchored_images(
    archive: zipfile.ZipFile, sheet_path: str
) -> dict[int, tuple[str, bytes]]:
    sheet_rels_path = _rels_path_for(sheet_path)
    try:
        sheet_rels = ET.fromstring(archive.read(sheet_rels_path))
        sheet = ET.fromstring(archive.read(sheet_path))
    except KeyError:
        return {}

    rel_targets = {rel.attrib["Id"]: rel.attrib["Target"] for rel in sheet_rels}
    drawing = sheet.find(f"{SHEET_NS}drawing")
    if drawing is None:
        return {}
    drawing_rel_id = drawing.attrib.get(f"{OD_REL_NS}id")
    if not drawing_rel_id or drawing_rel_id not in rel_targets:
        return {}
    drawing_path = _resolve_relative_part(sheet_path, rel_targets[drawing_rel_id])
    try:
        drawing_root = ET.fromstring(archive.read(drawing_path))
        drawing_rels = ET.fromstring(archive.read(_rels_path_for(drawing_path)))
    except KeyError:
        return {}
    image_targets = {rel.attrib["Id"]: rel.attrib["Target"] for rel in drawing_rels}

    images: dict[int, tuple[str, bytes]] = {}
    for anchor in drawing_root:
        from_node = anchor.find(f"{XDR_NS}from")
        if from_node is None:
            continue
        row_node = from_node.find(f"{XDR_NS}row")
        if row_node is None or row_node.text is None:
            continue
        row_number = int(row_node.text) + 1
        embed_id = None
        for element in anchor.iter():
            embed_id = element.attrib.get(f"{OD_REL_NS}embed")
            if embed_id:
                break
        if not embed_id or embed_id not in image_targets:
            continue
        image_path = _resolve_relative_part(drawing_path, image_targets[embed_id])
        images[row_number] = (
            Path(image_path).suffix or ".bin",
            archive.read(image_path),
        )
    return images


def _copy_reference_image(
    row: dict[str, str],
    excel_path: Path,
    item_dir: Path,
    embedded_images: dict[int, tuple[str, bytes]],
    row_number: int,
) -> Path:
    item_dir.mkdir(parents=True, exist_ok=True)
    image_path_value = row.get("image_path", "").strip()
    if image_path_value:
        source = Path(image_path_value)
        if not source.is_absolute():
            source = excel_path.parent / source
        if not source.exists():
            raise FileNotFoundError(f"row {row_number}: image_path not found: {source}")
        target = item_dir / f"reference{source.suffix or '.jpg'}"
        shutil.copyfile(source, target)
        return target

    embedded = embedded_images.get(row_number)
    if embedded:
        suffix, payload = embedded
        target = item_dir / f"reference{suffix}"
        target.write_bytes(payload)
        return target

    raise ValueError(f"row {row_number}: image_path or embedded image is required")


def _resolve_xl_target(target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    if target.startswith("xl/"):
        return target
    return posixpath.normpath(posixpath.join("xl", target))


def _resolve_relative_part(base_part: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(base_part), target))


def _rels_path_for(part_path: str) -> str:
    directory = posixpath.dirname(part_path)
    filename = posixpath.basename(part_path)
    return posixpath.join(directory, "_rels", f"{filename}.rels")


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    if cell.attrib.get("t") == "inlineStr":
        return "".join(text.text or "" for text in cell.iter(f"{SHEET_NS}t"))
    value = cell.find(f"{SHEET_NS}v")
    if value is None or value.text is None:
        return ""
    raw = value.text
    if cell.attrib.get("t") == "s":
        index = int(raw)
        return shared_strings[index] if index < len(shared_strings) else ""
    return raw


def _cell_column_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha()).upper()
    total = 0
    for ch in letters:
        total = total * 26 + (ord(ch) - 64)
    return total or 1


def _normalize_header(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def _row_dict(header: list[str], values: list[str]) -> dict[str, str]:
    return {
        name: values[index].strip() if index < len(values) else ""
        for index, name in enumerate(header)
    }


def _row_enabled(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in FALSY:
        return False
    if normalized in TRUTHY:
        return True
    return True


def _safe_item_id(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "-", value).strip("-._")
    return slug or "item"


def _parse_keyword_candidates(value: str) -> list[str]:
    candidates: list[str] = []
    for raw_line in str(value).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^\s*(?:TOP\s*)?\d+\s*[.．、:：)]\s*", "", line, flags=re.I)
        line = line.strip()
        if line:
            candidates.append(line)
    return candidates
