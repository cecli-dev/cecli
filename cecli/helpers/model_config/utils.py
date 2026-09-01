"""Shared helpers for the model config system.

These string-scanning helpers mirror ``cecli/models.py``'s approach of working
with raw JSON text so model metadata is never materialized into a full dict.
"""

from __future__ import annotations


def get_entry_from_raw(raw, key):
    """Parse a single ``key`` entry from a raw JSON string (never the whole dict).

    Mirrors ``ModelInfoManager._get_entry_from_raw`` in ``cecli/models.py``,
    with a tighter lookbehind so ``provider/...``-prefixed keys never shadow a
    bare route lookup (e.g. ``github_copilot/gpt-5`` vs ``gpt-5``).
    """
    import json
    import re

    if not raw:
        return None

    escaped_key = re.escape(key)
    match = re.search(rf'(?<![\w/.-])"{escaped_key}"\s*:', raw)

    if not match:
        return None

    start = match.end()

    while start < len(raw) and raw[start] in " \t\n\r":
        start += 1

    if start >= len(raw) or raw[start] != "{":
        return None

    depth = 1
    pos = start + 1
    in_string = False
    escape = False

    while pos < len(raw) and depth > 0:
        ch = raw[pos]

        if escape:
            escape = False

        elif ch == "\\":
            escape = True

        elif ch == '"':
            in_string = not in_string

        elif not in_string:
            if ch == "{":
                depth += 1

            elif ch == "}":
                depth -= 1

        pos += 1

    if depth != 0:
        return None

    try:
        return json.loads(raw[start:pos])

    except json.JSONDecodeError:
        return None


def top_level_keys(raw):
    """Yield the top-level keys of a raw JSON object without parsing values."""
    keys = []
    depth = 0
    in_string = False
    escape = False
    i = 0
    n = len(raw)

    while i < n:
        ch = raw[i]

        if escape:
            escape = False
            i += 1
            continue

        if ch == "\\":
            escape = True
            i += 1
            continue

        if ch == '"':
            if depth == 1 and not in_string:
                key, after = _peek_key(raw, i)

                if after is not None:
                    keys.append(key)
                    i = after
                    continue

            in_string = not in_string
            i += 1
            continue

        if not in_string:
            if ch == "{":
                depth += 1

            elif ch == "}":
                depth -= 1

        i += 1

    return keys


def supports_reasoning(record):
    """Whether a model supports reasoning.

    Unknown models (``record`` is ``None``) are assumed to support reasoning;
    known records are only considered reasoning models when the metadata
    explicitly sets ``supports_reasoning`` to true.
    """
    if record is None:
        return True

    return bool(record.get("supports_reasoning"))


def _peek_key(raw, i):
    """If ``raw[i]`` starts a top-level ``"key":``, return (key, index after colon)."""
    start = i + 1
    j = start
    n = len(raw)

    while j < n:
        c = raw[j]

        if c == "\\":
            j += 2
            continue

        if c == '"':
            break

        j += 1

    if j >= n:
        return None, None

    key = raw[start:j]
    k = j + 1

    while k < n and raw[k] in " \t\n\r":
        k += 1

    if k < n and raw[k] == ":":
        return key, k

    return None, None
