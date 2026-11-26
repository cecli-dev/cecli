"""TOON (token-oriented object notation) encoding for bridge payloads.

TOON is a lossless, indentation-based encoding of the JSON data model aimed at
LLM input: uniform object arrays become one header plus CSV-like rows, nested
objects become indented keys, and quoting is kept to the minimum the format
requires.

The win depends on the payload shape. A flat array of uniform objects (the lean
snapshot record) is its best case; a record carrying an array-valued field such
as ``patterns`` disqualifies tabular form and TOON degrades to roughly JSON size.
That is why snapshots are rendered from the lean record by default and the full
record lives behind ``--verbose``.

This module implements the encoder only: the bridge and its clients always speak
JSON on the wire, and TOON is a rendering for humans and models.

Reference: https://github.com/toon-format/toon (spec v4.4).
"""

from __future__ import annotations

import re
from typing import Any

DELIMITER = ","
INDENT = "  "

_NUMERIC = re.compile(r"^[+-]?[0-9]+(?:\.[0-9]+)?(?:e[+-]?[0-9]+)?$", re.IGNORECASE)
_SAFE_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def encode(value: Any) -> str:
    """Encode a JSON-compatible value as TOON text."""

    if isinstance(value, dict):
        return "\n".join(_object_lines(value, 0))

    if isinstance(value, list):
        return "\n".join(_root_array_lines(value))

    return _primitive(value)


def _object_lines(obj: dict[str, Any], depth: int) -> list[str]:
    pad = INDENT * depth
    lines: list[str] = []

    for key, value in obj.items():
        name = _key(key)

        if isinstance(value, dict):
            lines.append(f"{pad}{name}:")

            if value:
                lines.extend(_object_lines(value, depth + 1))

            continue

        if isinstance(value, list):
            lines.extend(_array_lines(name, value, depth))

            continue

        lines.append(f"{pad}{name}: {_primitive(value)}")

    return lines


def _root_array_lines(items: list[Any]) -> list[str]:
    if not items:
        return ["[]"]

    if all(_is_primitive(item) for item in items):
        cells = DELIMITER.join(_primitive(item) for item in items)

        return [f"[{len(items)}]: {cells}"]

    fields = _tabular_fields(items)

    if fields is not None:
        header = f"[{len(items)}]{{{DELIMITER.join(_field_spec(*field) for field in fields)}}}:"

        return [header, *[_tabular_row(item, fields, 1) for item in items]]

    lines = [f"[{len(items)}]:"]

    for item in items:
        lines.extend(_list_item_lines(item, 1))

    return lines


def _array_lines(name: str, items: list[Any], depth: int) -> list[str]:
    pad = INDENT * depth

    if not items:
        return [f"{pad}{name}: []"]

    if all(_is_primitive(item) for item in items):
        cells = DELIMITER.join(_primitive(item) for item in items)

        return [f"{pad}{name}[{len(items)}]: {cells}"]

    fields = _tabular_fields(items)

    if fields is not None:
        spec = DELIMITER.join(_field_spec(*field) for field in fields)
        header = f"{pad}{name}[{len(items)}]{{{spec}}}:"

        return [header, *[_tabular_row(item, fields, depth + 1) for item in items]]

    lines = [f"{pad}{name}[{len(items)}]:"]

    for item in items:
        lines.extend(_list_item_lines(item, depth + 1))

    return lines


def _list_item_lines(item: Any, depth: int) -> list[str]:
    pad = INDENT * depth

    if _is_primitive(item):
        return [f"{pad}- {_primitive(item)}"]

    if isinstance(item, list):
        if not item:
            return [f"{pad}- [0]:"]

        if all(_is_primitive(entry) for entry in item):
            cells = DELIMITER.join(_primitive(entry) for entry in item)

            return [f"{pad}- [{len(item)}]: {cells}"]

        lines = [f"{pad}- [{len(item)}]:"]

        for entry in item:
            lines.extend(_list_item_lines(entry, depth + 1))

        return lines

    if not item:
        return [f"{pad}-"]

    pairs = list(item.items())
    first_key, first_value = pairs[0]
    name = _key(first_key)
    lines: list[str]

    if isinstance(first_value, dict):
        lines = [f"{pad}- {name}:"]

        if first_value:
            lines.extend(_object_lines(first_value, depth + 1))
    elif isinstance(first_value, list):
        nested = _array_lines(name, first_value, depth)
        lines = [nested[0].replace(f"{pad}{name}", f"{pad}- {name}", 1), *nested[1:]]
    else:
        lines = [f"{pad}- {name}: {_primitive(first_value)}"]

    for key, value in pairs[1:]:
        child_pad = pad + INDENT

        if isinstance(value, dict):
            lines.append(f"{child_pad}{_key(key)}:")

            if value:
                lines.extend(_object_lines(value, depth + 2))
        elif isinstance(value, list):
            lines.extend(_array_lines(_key(key), value, depth + 1))
        else:
            lines.append(f"{child_pad}{_key(key)}: {_primitive(value)}")

    return lines


def _tabular_fields(items: list[Any]) -> list[tuple[str, Any]] | None:
    """Return the field spec when ``items`` can use tabular form, else ``None``."""

    if not items or not all(isinstance(item, dict) and item for item in items):
        return None

    keys = list(items[0].keys())

    if any(set(item.keys()) != set(keys) for item in items):
        return None

    fields: list[tuple[str, Any]] = []

    for key in keys:
        column = [item[key] for item in items]

        if all(_is_primitive(value) for value in column):
            fields.append((key, None))

            continue

        nested = _tabular_fields(column)

        if nested is None:
            return None

        fields.append((key, nested))

    return fields


def _field_spec(name: str, nested: list[tuple[str, Any]] | None) -> str:
    """Render one header field, expanding a nested field group."""

    key = _key(name)

    if nested is None:
        return key

    group = DELIMITER.join(_field_spec(child, grandchild) for child, grandchild in nested)

    return f"{key}{{{group}}}"


def _tabular_row(item: dict[str, Any], fields: list[tuple[str, Any]], depth: int) -> str:
    pad = INDENT * depth
    cells: list[str] = []

    for key, nested in fields:
        if nested is None:
            cells.append(_primitive(item[key]))
        else:
            cells.extend(_flatten(item[key], nested))

    return pad + DELIMITER.join(cells)


def _flatten(obj: dict[str, Any], fields: list[tuple[str, Any]]) -> list[str]:
    cells: list[str] = []

    for key, nested in fields:
        if nested is None:
            cells.append(_primitive(obj[key]))
        else:
            cells.extend(_flatten(obj[key], nested))

    return cells


def _is_primitive(value: Any) -> bool:
    return not isinstance(value, (dict, list))


def _primitive(value: Any) -> str:
    if value is None:
        return "null"

    if value is True:
        return "true"

    if value is False:
        return "false"

    if isinstance(value, str):
        return _string(value)

    return str(value)


def _string(value: str) -> str:
    if not _needs_quotes(value):
        return value

    return _quoted(value)


def _quoted(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )

    return f'"{escaped}"'


def _needs_quotes(value: str) -> bool:
    if value == "":
        return True

    if value != value.strip(" \t"):
        return True

    if value in ("true", "false", "null"):
        return True

    if _NUMERIC.match(value):
        return True

    specials = (":", '"', "\\", "[", "]", "{", "}", DELIMITER)

    if any(character in value for character in specials):
        return True

    if any(ord(character) < 0x20 for character in value):
        return True

    return value.startswith(("-", "#"))


def _key(name: str) -> str:
    if _SAFE_KEY.match(name):
        return name

    return _quoted(name)
