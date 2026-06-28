"""Static structural index of a benchmark `reference_app/`.

Exposes file tree, server routes, key exports, and capability->file mapping.
Never embeds source snippets, function bodies, or comments. Used to seed coder
context for `benchmark_parity` mode without leaking implementation details.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

INDEX_JSON_NAME = "reference_app_index.json"
INDEX_MD_NAME = "reference_app_index.md"

SCAN_ROOTS = ("src", "public", "tests")
SCAN_DEPTH_LIMIT = 3
SCAN_FILE_LIMIT = 200
ROOT_FILE_ALLOW = (
    ".json",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".md",
    ".html",
    ".css",
    ".yaml",
    ".yml",
)
SOURCE_SUFFIXES = (".js", ".mjs", ".cjs", ".ts")

EXPRESS_ROUTE = re.compile(
    r"\b(app|router)\.(get|post|put|delete|patch|options|head|all)\s*\(\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
URL_EQ_ROUTE = re.compile(
    r"(?:req\.url|url\.pathname|request\.url|pathname)\s*===\s*['\"]([^'\"]+)['\"]",
)
URL_STARTSWITH_ROUTE = re.compile(
    r"(?:req\.url|url\.pathname|request\.url|pathname)\.startsWith\s*\(\s*['\"]([^'\"]+)['\"]",
)
EXPORT_FUNCTION = re.compile(
    r"^\s*export\s+(?:async\s+)?(?:function|class|const|let|var)\s+([A-Za-z_$][\w$]*)",
)
EXPORTS_ASSIGN = re.compile(r"^\s*(?:module\.)?exports\.([A-Za-z_$][\w$]*)\s*=")
MODULE_EXPORTS_BLOCK = re.compile(r"module\.exports\s*=\s*\{([^}]+)\}", re.DOTALL)
MODULE_EXPORTS_KEY = re.compile(r"^\s*([A-Za-z_$][\w$]*)\s*(?::|,|$)", re.MULTILINE)

KEY_EXPORTS_PER_FILE_LIMIT = 12
MD_BUDGET_CHARS = 1200


def build_reference_app_index(
    reference_dir: Path,
    capabilities: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Build the structured index payload (json-ready dict)."""
    reference_dir = Path(reference_dir)
    file_tree = _scan_file_tree(reference_dir)
    server_routes = _scan_server_routes(reference_dir, file_tree)
    key_exports = _scan_key_exports(reference_dir, file_tree)
    capability_to_files = _scan_capability_to_files(
        reference_dir, list(capabilities), file_tree
    )
    return {
        "schema_version": 1,
        "reference_dir": str(reference_dir),
        "file_tree": file_tree,
        "server_routes": server_routes,
        "key_exports": key_exports,
        "capability_to_files": capability_to_files,
    }


def render_reference_app_index_markdown(payload: dict[str, Any]) -> str:
    """Render the human-readable index under MD_BUDGET_CHARS chars when possible."""
    file_tree = payload.get("file_tree") or []
    server_routes = payload.get("server_routes") or []
    capability_to_files = payload.get("capability_to_files") or []
    key_exports = payload.get("key_exports") or []
    sections = [
        _md_file_tree_section(file_tree),
        _md_routes_section(server_routes),
        _md_capability_section(capability_to_files),
        _md_exports_section(key_exports),
    ]
    rendered = _join_sections(sections, MD_BUDGET_CHARS)
    return rendered.rstrip() + "\n"


def write_reference_app_index_artifacts(
    out_dir: Path,
    payload: dict[str, Any],
) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / INDEX_JSON_NAME
    md_path = out_dir / INDEX_MD_NAME
    import json

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_reference_app_index_markdown(payload), encoding="utf-8")
    return json_path, md_path


def _scan_file_tree(reference_dir: Path) -> list[str]:
    if not reference_dir.exists():
        return []
    files: list[str] = []
    for child in sorted(reference_dir.iterdir()):
        if not child.is_file():
            continue
        if child.suffix.lower() not in ROOT_FILE_ALLOW:
            continue
        files.append(child.name)
    for root_name in SCAN_ROOTS:
        root = reference_dir / root_name
        if not root.exists() or not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(reference_dir)
            if len(rel.parts) > SCAN_DEPTH_LIMIT:
                continue
            if "node_modules" in rel.parts:
                continue
            files.append(rel.as_posix())
            if len(files) >= SCAN_FILE_LIMIT:
                return files
    return files


def _scan_server_routes(reference_dir: Path, file_tree: list[str]) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for rel in file_tree:
        if not rel.lower().endswith(SOURCE_SUFFIXES):
            continue
        path = reference_dir / rel
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            for match in EXPRESS_ROUTE.finditer(line):
                method = match.group(2).upper()
                route_path = match.group(3)
                key = (method, route_path, rel)
                if key in seen:
                    continue
                seen.add(key)
                routes.append({"method": method, "path": route_path, "file": rel, "line": line_no})
            for match in URL_EQ_ROUTE.finditer(line):
                route_path = match.group(1)
                key = ("ANY", route_path, rel)
                if key in seen:
                    continue
                seen.add(key)
                routes.append({"method": "ANY", "path": route_path, "file": rel, "line": line_no})
            for match in URL_STARTSWITH_ROUTE.finditer(line):
                route_path = match.group(1)
                key = ("PREFIX", route_path, rel)
                if key in seen:
                    continue
                seen.add(key)
                routes.append({"method": "PREFIX", "path": route_path, "file": rel, "line": line_no})
    return routes


def _scan_key_exports(reference_dir: Path, file_tree: list[str]) -> list[dict[str, Any]]:
    exports: list[dict[str, Any]] = []
    for rel in file_tree:
        if not rel.lower().endswith(SOURCE_SUFFIXES):
            continue
        path = reference_dir / rel
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        symbols: list[str] = []
        for line in text.splitlines():
            m = EXPORT_FUNCTION.match(line)
            if m and m.group(1) not in symbols:
                symbols.append(m.group(1))
                continue
            m = EXPORTS_ASSIGN.match(line)
            if m and m.group(1) not in symbols:
                symbols.append(m.group(1))
        block = MODULE_EXPORTS_BLOCK.search(text)
        if block:
            for m in MODULE_EXPORTS_KEY.finditer(block.group(1)):
                name = m.group(1)
                if name and name not in symbols:
                    symbols.append(name)
        if symbols:
            truncated = symbols[:KEY_EXPORTS_PER_FILE_LIMIT]
            entry: dict[str, Any] = {"file": rel, "symbols": truncated}
            if len(symbols) > KEY_EXPORTS_PER_FILE_LIMIT:
                entry["omitted"] = len(symbols) - KEY_EXPORTS_PER_FILE_LIMIT
            exports.append(entry)
    return exports


def _scan_capability_to_files(
    reference_dir: Path,
    capabilities: list[dict[str, Any]],
    file_tree: list[str],
) -> list[dict[str, Any]]:
    if not capabilities:
        return []
    file_texts: dict[str, str] = {}
    for rel in file_tree:
        path = reference_dir / rel
        try:
            file_texts[rel] = path.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
    result: list[dict[str, Any]] = []
    for item in capabilities:
        if not isinstance(item, dict):
            continue
        capability_id = str(item.get("id", "")).strip()
        if not capability_id:
            continue
        tokens = _capability_tokens(item)
        if not tokens:
            result.append({"capability_id": capability_id, "files": []})
            continue
        hits: list[str] = []
        for rel, text in file_texts.items():
            if any(token and token in text for token in tokens):
                hits.append(rel)
        result.append({"capability_id": capability_id, "files": hits})
    return result


def _capability_tokens(capability: dict[str, Any]) -> list[str]:
    detection = capability.get("detection") if isinstance(capability.get("detection"), dict) else {}
    tokens: list[str] = []
    for source in (
        detection.get("match_any"),
        capability.get("evidence"),
    ):
        if isinstance(source, list):
            tokens.extend(str(value).strip().lower() for value in source if str(value).strip())
    capability_id = str(capability.get("id", "")).strip().lower()
    if capability_id and capability_id not in tokens:
        tokens.append(capability_id)
    label = str(capability.get("label", "")).strip().lower()
    if label and label not in tokens:
        tokens.append(label)
    return [token for token in tokens if token]


def _md_file_tree_section(file_tree: list[str]) -> tuple[str, list[str]]:
    if not file_tree:
        return ("## File Tree", ["- (empty reference_app)"])
    lines = [f"- `{rel}`" for rel in file_tree]
    return ("## File Tree", lines)


def _md_routes_section(routes: list[dict[str, Any]]) -> tuple[str, list[str]]:
    if not routes:
        return ("## Server Routes", ["- (no routes detected)"])
    lines = []
    for route in routes:
        method = str(route.get("method", "")).upper() or "ANY"
        path = route.get("path", "")
        file = route.get("file", "")
        line = route.get("line", "")
        lines.append(f"- `{method} {path}` in `{file}` (line {line})")
    return ("## Server Routes", lines)


def _md_capability_section(capability_to_files: list[dict[str, Any]]) -> tuple[str, list[str]]:
    if not capability_to_files:
        return ("## Capability To Files", ["- (no capability mapping)"])
    lines = []
    for item in capability_to_files:
        cid = item.get("capability_id", "")
        files = item.get("files", []) or []
        joined = ", ".join(f"`{f}`" for f in files) if files else "(no match)"
        lines.append(f"- `{cid}`: {joined}")
    return ("## Capability To Files", lines)


def _md_exports_section(key_exports: list[dict[str, Any]]) -> tuple[str, list[str]]:
    if not key_exports:
        return ("## Key Exports", ["- (no exports detected)"])
    lines = []
    for entry in key_exports:
        file = entry.get("file", "")
        symbols = entry.get("symbols", []) or []
        omitted = entry.get("omitted")
        joined = ", ".join(symbols)
        suffix = f" (+{omitted} more)" if omitted else ""
        lines.append(f"- `{file}`: {joined}{suffix}")
    return ("## Key Exports", lines)


def _join_sections(sections: list[tuple[str, list[str]]], budget: int) -> str:
    header = "# Reference App Index\n\n"
    body_parts: list[str] = []
    total = len(header)
    for title, lines in sections:
        section_text = title + "\n\n" + "\n".join(lines) + "\n\n"
        if total + len(section_text) > budget and body_parts:
            body_parts.append(f"{title}\n\n- (omitted to fit context budget)\n\n")
            break
        body_parts.append(section_text)
        total += len(section_text)
    return header + "".join(body_parts)