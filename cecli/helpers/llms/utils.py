"""Shared helpers for the llms package.

SSE parsing, system-prompt extraction, and reasoning-text extraction are used
by multiple domain adapters, so they live here rather than being duplicated.
"""

from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from cecli.http import httpx


async def sse_json_lines(resp: httpx.Response) -> AsyncIterator[Dict[str, Any]]:
    """Yield parsed JSON from ``data:`` lines of an SSE stream."""
    buffer = ""

    async for raw in resp.aiter_lines():
        line = raw.strip()

        if not line.startswith("data:"):
            continue

        payload = line[5:].strip()

        if payload == "[DONE]":
            continue

        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            buffer += payload

            try:
                yield json.loads(buffer)
            except json.JSONDecodeError:
                continue


def system_prompt(messages: List[Dict[str, Any]]) -> Optional[str]:
    """Join all system messages into a single prompt (or None)."""
    systems = [m["content"] for m in messages if m.get("role") == "system" and m.get("content")]
    return "\n\n".join(systems) if systems else None


def extract_reasoning(msg: Dict[str, Any]) -> str:
    """Extract reasoning text from a chat message or delta.

    Handles three shapes seen in the wild:
      - ``reasoning_content`` (str) - deepseek-style
      - ``reasoning`` (str) - openrouter
      - ``reasoning_details`` (list of {"type": "reasoning.text", "text": ...})

    OpenRouter (and minimax via OpenRouter) sends BOTH the flat ``reasoning``
    string AND a ``reasoning_details`` list holding the *same* incremental text
    on every delta; combining them doubled the reasoning. The structured list
    is authoritative when present; the flat string is only a fallback.
    """
    details = msg.get("reasoning_details") or msg.get("reasoning_content_details")

    if isinstance(details, list) and details:
        texts: List[str] = []

        for item in details:
            if isinstance(item, dict):
                text = item.get("text")

                if isinstance(text, str) and text.strip():
                    texts.append(text)

        if texts:
            return "\n".join(texts)

    parts: List[str] = []

    for key in ("reasoning_content", "reasoning"):
        val = msg.get(key)

        if isinstance(val, str) and val.strip():
            parts.append(val)

    return "\n".join(parts)


_DATA_URL_RE = re.compile(r"data:([^;,]+)(;base64)?,(.*)", re.DOTALL)


def split_data_url(url: Any) -> Optional[Tuple[str, str]]:
    """Parse a ``data:<mime>;base64,<payload>`` URL into ``(mime_type, data)``.

    Returns None for non-data URLs (https://..., gs://...) or non-base64
    payloads so callers can fall back to fileData / text placeholders.
    """
    if not isinstance(url, str):
        return None

    match = _DATA_URL_RE.match(url)

    if not match or not match.group(2):
        return None

    return (match.group(1) or "application/octet-stream", match.group(3))


__all__ = ["sse_json_lines", "system_prompt", "extract_reasoning", "split_data_url"]
