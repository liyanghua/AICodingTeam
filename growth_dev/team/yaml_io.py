from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class YamlSubsetError(ValueError):
    pass


def load_yaml_subset(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = parse_yaml_subset(text)
    if not isinstance(payload, dict):
        raise YamlSubsetError(f"Expected a mapping in {path}")
    return payload


def parse_yaml_subset(text: str) -> Any:
    lines = _tokenize(text)
    if not lines:
        return {}
    value, index = _parse_block(lines, 0, lines[0][0])
    if index != len(lines):
        indent, content = lines[index]
        raise YamlSubsetError(f"Unexpected line at indent {indent}: {content}")
    return value


def _tokenize(text: str) -> list[tuple[int, str]]:
    tokens: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if "\t" in raw_line[:indent]:
            raise YamlSubsetError("Tabs are not supported in YAML indentation")
        content = raw_line.strip()
        if tokens and indent > tokens[-1][0] and not content.startswith("- ") and ":" not in content:
            prev_indent, prev_content = tokens[-1]
            tokens[-1] = (prev_indent, prev_content + " " + content)
            continue
        tokens.append((indent, content))
    return tokens


def _parse_block(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    current_indent, content = lines[index]
    if current_indent != indent:
        raise YamlSubsetError(f"Expected indent {indent}, got {current_indent}: {content}")
    if content.startswith("- "):
        return _parse_list(lines, index, indent)
    return _parse_map(lines, index, indent)


def _parse_map(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[dict[str, Any], int]:
    payload: dict[str, Any] = {}
    while index < len(lines):
        current_indent, content = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise YamlSubsetError(f"Unexpected nested line: {content}")
        if content.startswith("- "):
            break

        key, value = _split_key_value(content)
        if value:
            payload[key] = _parse_scalar(value)
            index += 1
            continue

        index += 1
        if index < len(lines) and lines[index][0] > indent:
            payload[key], index = _parse_block(lines, index, lines[index][0])
        elif index < len(lines) and lines[index][0] == indent and lines[index][1].startswith("- "):
            payload[key], index = _parse_list(lines, index, indent)
        else:
            payload[key] = {}
    return payload, index


def _parse_list(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[list[Any], int]:
    values: list[Any] = []
    while index < len(lines):
        current_indent, content = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise YamlSubsetError(f"Unexpected nested list line: {content}")
        if not content.startswith("- "):
            break

        item = content[2:].strip()
        if not item:
            index += 1
            if index < len(lines) and lines[index][0] > indent:
                value, index = _parse_block(lines, index, lines[index][0])
            else:
                value = None
            values.append(value)
            continue

        if _looks_like_mapping(item):
            key, value = _split_key_value(item)
            mapping: dict[str, Any] = {key: _parse_scalar(value) if value else {}}
            index += 1
            if index < len(lines) and lines[index][0] > indent:
                child, index = _parse_block(lines, index, lines[index][0])
                if isinstance(child, dict):
                    mapping.update(child)
                else:
                    mapping[key] = child
            values.append(mapping)
            continue

        values.append(_parse_scalar(item))
        index += 1
    return values, index


def _looks_like_mapping(text: str) -> bool:
    if ":" not in text:
        return False
    key = text.split(":", 1)[0].strip()
    return bool(key) and " " not in key


def _split_key_value(text: str) -> tuple[str, str]:
    if ":" not in text:
        raise YamlSubsetError(f"Expected key/value line: {text}")
    key, value = text.split(":", 1)
    key = key.strip()
    if not key:
        raise YamlSubsetError(f"Empty key in line: {text}")
    return key, value.strip()


def _parse_scalar(text: str) -> Any:
    value = text.strip()
    if value == "[]":
        return []
    if value == "{}":
        return {}
    if value.startswith("[") and value.endswith("]"):
        body = value[1:-1].strip()
        if not body:
            return []
        return [_parse_scalar(part.strip()) for part in body.split(",")]
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]

    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none", "~"}:
        return None

    if _is_int(value):
        return int(value)
    if _is_float(value):
        return float(value)
    return value


def _is_int(value: str) -> bool:
    if value.startswith("-"):
        value = value[1:]
    return value.isdigit()


def _is_float(value: str) -> bool:
    if value.count(".") != 1:
        return False
    left, right = value.split(".", 1)
    if left.startswith("-"):
        left = left[1:]
    return bool(left) and left.isdigit() and right.isdigit()
