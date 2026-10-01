"""Ollama provider adapter for the llms package.

Ollama's OpenAI-compatible ``/v1/chat/completions`` endpoint ignores runner
options such as ``num_ctx``; Ollama's own docs direct users to a Modelfile or the
native wire to change the context window. This adapter keeps the shared ``chat``
family but overrides its chat hooks (endpoint, payload, stream parsing) to speak
Ollama's native ``/api/chat`` wire, where api-block parameters such as ``num_ctx``
and ``keep_alive`` live under ``options``.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional

from ..constants import CONTROL_KWARGS
from ..types import (
    Choice,
    CompletionChunk,
    CompletionResponse,
    Part,
    PartsMessage,
    ReasoningPart,
    TextPart,
    ToolCall,
    ToolCallPart,
    Usage,
    parts_message_to_message,
)
from ..utils import extract_reasoning, split_data_url
from .base import ProviderAdapter

#: Native-body keys the payload builder consumes itself, so they must not also
#: be forwarded as runner options (on top of the shared shim/pipeline kwargs).
_NATIVE_CONTROL_KEYS = frozenset(
    {
        "stream_options",
        "prompt_cache_key",
        "tool_choice",
        "extra_body",
        "reasoning_effort",
        "thinking",
        "parallel_tool_calls",
    }
)

#: Request keys that must never be forwarded as runner options.
_CONTROL_KEYS = CONTROL_KWARGS | _NATIVE_CONTROL_KEYS


#: Native request-body keys forwarded at the top level (not under ``options``).
_TOP_LEVEL_KEYS = frozenset({"keep_alive", "format", "think"})

#: api-block parameter names mapped onto their native ``options`` equivalent.
_OPTION_ALIASES = {"max_tokens": "num_predict", "max_completion_tokens": "num_predict"}

#: Reasoning hints that explicitly turn thinking off.
_THINK_DISABLED = frozenset({"none", "disabled", "off", "false"})

#: cecli effort levels mapped onto Ollama's native ``think`` levels.
_THINK_LEVELS = {"low": "low", "medium": "medium", "high": "high", "max": "high"}

#: Ollama's default native origin when no base URL resolves.
_DEFAULT_BASE = "http://localhost:11434"


class _OllamaWire:
    """Shared native ``/api/chat`` chat hooks for the Ollama provider slugs."""

    #: num_ctx and friends only work on the native wire; never let
    #: OPENAI_API_BASE hijack an Ollama request.
    honors_openai_env_override: bool = False

    def __init__(self) -> None:
        self._tool_call_offset = 0

    def chat_url(self, resolved: Dict[str, Any], base: str) -> str:
        return f"{ollama_native_base(base)}/api/chat"

    def chat_payload(
        self,
        resolved: Dict[str, Any],
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        stream: bool,
        kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        return ollama_payload(resolved, messages, tools, stream, kwargs)

    def chat_stream_json(self, resp: Any) -> Any:
        self._tool_call_offset = 0

        return _ndjson_lines(resp)

    def parse_chat_response(self, data: Dict[str, Any], resolved: Dict[str, Any]) -> Any:
        return normalize_ollama_response(data, resolved["model"])

    def parse_chat_chunk(self, data: Dict[str, Any]) -> Any:
        """Normalize one chunk, numbering tool calls across the whole stream.

        Ollama streams each tool call whole (no id) with a per-chunk index that
        restarts at 0, so a running stream offset is applied to keep parallel
        calls distinct in the aggregators (which key by id, else index).
        """
        chunk = parse_ollama_chunk(data, self._tool_call_offset)

        if chunk and chunk.tool_calls:
            self._tool_call_offset += len(chunk.tool_calls)

        return chunk


class OllamaProvider(_OllamaWire, ProviderAdapter):
    """Ollama ``ollama/`` slug: native /api/chat wire."""

    provider: str = "ollama"


class OllamaChatProvider(_OllamaWire, ProviderAdapter):
    """Ollama ``ollama_chat/`` slug: native /api/chat wire."""

    provider: str = "ollama_chat"


def ollama_native_base(api_base: Optional[str]) -> str:
    """Strip an OpenAI-compat ``/v1`` (or ``/api``) suffix to reach Ollama."""
    base = (api_base or _DEFAULT_BASE).rstrip("/")

    for suffix in ("/v1", "/api"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]

    return base or _DEFAULT_BASE


def ollama_payload(
    resolved: Dict[str, Any],
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    stream: bool,
    kwargs: Dict[str, Any],
) -> Dict[str, Any]:
    """Build the native ``/api/chat`` payload from api-block/extra params."""
    body = _extra_body(resolved, kwargs)
    payload: Dict[str, Any] = {
        "model": resolved["route"],
        "messages": _native_messages(messages),
        "stream": stream,
    }

    if tools:
        payload["tools"] = tools

    options = _options(kwargs, body)

    if options:
        payload["options"] = options

    keep_alive = kwargs.get("keep_alive")

    if keep_alive is None:
        keep_alive = body.get("keep_alive")

    if keep_alive is not None:
        payload["keep_alive"] = keep_alive

    think = _think_value(kwargs, body)

    if think is not None:
        payload["think"] = think

    format_value = kwargs.get("format")

    if format_value is None:
        format_value = body.get("format")

    if format_value is not None:
        payload["format"] = format_value

    return payload


def normalize_ollama_response(data: Dict[str, Any], model: str) -> CompletionResponse:
    """Convert a native ``/api/chat`` response into a normalized response."""
    message = data.get("message") or {}
    parts: List[Part] = []
    content = message.get("content")

    if isinstance(content, str) and content:
        parts.append(TextPart(text=content))

    reasoning = message.get("thinking") or extract_reasoning(message)

    if reasoning:
        parts.append(ReasoningPart(text=reasoning))

    for tc in message.get("tool_calls") or []:
        function = tc.get("function") or {}
        parts.append(
            ToolCallPart(
                name=function.get("name", ""),
                arguments=_parse_arguments(function.get("arguments")),
                tool_call_id=tc.get("id"),
            )
        )

    pm = PartsMessage(role=message.get("role", "assistant"), parts=parts)
    finish_reason = _map_finish_reason(data.get("done_reason") or "stop")

    if any(isinstance(part, ToolCallPart) for part in parts):
        finish_reason = "tool_calls"

    return CompletionResponse(
        id=data.get("id"),
        model=model,
        choices=[
            Choice(
                index=0,
                message=parts_message_to_message(pm),
                finish_reason=finish_reason,
            )
        ],
        usage=_usage_from_native(data),
    )


def parse_ollama_chunk(data: Dict[str, Any], start_index: int = 0) -> Optional[CompletionChunk]:
    """Convert one native NDJSON chunk into a normalized stream chunk.

    ``start_index`` offsets the tool-call index/id so a caller consuming a whole
    stream keeps parallel calls distinct: Ollama streams each call whole with a
    per-chunk index that restarts at 0, so the streaming hook passes a running
    offset (see :meth:`_OllamaWire.parse_chat_chunk`).
    """
    message = data.get("message") or {}
    text = message.get("content") or ""
    reasoning = message.get("thinking") or ""
    tool_calls: List[ToolCall] = []

    for offset, tc in enumerate(message.get("tool_calls") or []):
        index = start_index + offset
        function = tc.get("function") or {}
        tool_calls.append(
            ToolCall(
                id=tc.get("id") or f"call_{index}",
                name=function.get("name", ""),
                arguments=_parse_arguments(function.get("arguments")),
                index=index,
            )
        )

    done = bool(data.get("done"))
    finish_reason = None
    usage = None

    if done:
        finish_reason = (
            "tool_calls" if tool_calls else _map_finish_reason(data.get("done_reason") or "stop")
        )
        usage = _usage_from_native(data)

    if not text and not reasoning and not tool_calls and not done:
        return None

    return CompletionChunk(
        text=text,
        reasoning=reasoning,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        usage=usage,
    )


def _extra_body(resolved: Dict[str, Any], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    body = dict(resolved.get("extra_body") or {})
    body.update(kwargs.get("extra_body") or {})
    return body


def _options(kwargs: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    options: Dict[str, Any] = {}

    for source in (kwargs, body):
        for key, value in source.items():
            if value is None or key in _CONTROL_KEYS or key in _TOP_LEVEL_KEYS:
                continue

            options[_OPTION_ALIASES.get(key, key)] = value

    return options


def _think_value(kwargs: Dict[str, Any], body: Dict[str, Any]) -> Optional[Any]:
    for source in (kwargs, body):
        thinking = source.get("thinking")

        if thinking is not None:
            return _normalize_think(thinking)

    for source in (kwargs, body):
        effort = source.get("reasoning_effort")

        if effort:
            return _normalize_think(effort)

    return None


def _normalize_think(value: Any) -> Optional[Any]:
    """Map a generic thinking/effort hint onto Ollama's ``think`` field.

    Ollama accepts a boolean or a ``low``/``medium``/``high`` level: explicit
    disables become ``False``, recognized levels are forwarded (``max`` ->
    ``high``), and an unrecognized value returns ``None`` so the field is omitted
    and Ollama's default applies rather than the level silently disabling
    thinking.
    """
    if isinstance(value, bool):
        return value

    if isinstance(value, dict):
        return value.get("type") != "disabled"

    if not isinstance(value, str):
        return None

    level = value.strip().lower()

    if level in _THINK_DISABLED:
        return False

    return _THINK_LEVELS.get(level)


def _native_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role")
        content, images = _native_content(msg.get("content"))
        native: Dict[str, Any] = {"role": role}

        if content is not None:
            native["content"] = content

        if images:
            native["images"] = images

        reasoning = msg.get("reasoning_content") or extract_reasoning(msg)

        if role == "assistant" and reasoning:
            native["thinking"] = reasoning

        tool_calls = msg.get("tool_calls")

        if tool_calls:
            native["tool_calls"] = [_native_tool_call(tc) for tc in tool_calls]

        tool_call_id = msg.get("tool_call_id")

        if tool_call_id is not None:
            native["tool_call_id"] = tool_call_id

        out.append(native)

    return out


def _native_content(content: Any) -> Any:
    if isinstance(content, str):
        return content, []

    if not isinstance(content, list):
        return (None if content is None else str(content)), []

    texts: List[str] = []
    images: List[str] = []

    for part in content:
        if not isinstance(part, dict):
            continue

        part_type = part.get("type")

        if part_type == "text" and isinstance(part.get("text"), str):
            texts.append(part["text"])
        elif part_type == "image_url":
            url = part.get("image_url")

            if isinstance(url, dict):
                url = url.get("url")

            split = split_data_url(url)

            if split:
                images.append(split[1])

    text = "\n".join(item for item in texts if item)
    return (text or None), images


def _native_tool_call(tc: Dict[str, Any]) -> Dict[str, Any]:
    function = tc.get("function") or {}
    return {
        "function": {
            "name": function.get("name", ""),
            "arguments": _parse_arguments(function.get("arguments")),
        }
    }


def _parse_arguments(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw

    if not isinstance(raw, str) or not raw.strip():
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}

    return parsed if isinstance(parsed, dict) else {"_value": parsed}


def _usage_from_native(data: Dict[str, Any]) -> Optional[Usage]:
    prompt_tokens = data.get("prompt_eval_count")
    completion_tokens = data.get("eval_count")

    if prompt_tokens is None and completion_tokens is None:
        return None

    return Usage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=(prompt_tokens or 0) + (completion_tokens or 0),
    )


def _map_finish_reason(reason: str) -> str:
    reason = (reason or "").lower()

    if reason in ("stop", "length", "tool_calls"):
        return reason

    return "stop"


async def _ndjson_lines(resp: Any) -> AsyncIterator[Dict[str, Any]]:
    """Yield parsed JSON objects from Ollama's newline-delimited stream."""
    async for raw in resp.aiter_lines():
        line = raw.strip()

        if not line:
            continue

        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


__all__ = [
    "OllamaProvider",
    "OllamaChatProvider",
    "ollama_payload",
    "ollama_native_base",
    "normalize_ollama_response",
    "parse_ollama_chunk",
]
