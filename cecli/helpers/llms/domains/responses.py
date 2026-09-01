"""OpenAI /v1/responses adapter.

Covers gpt-5.x and meta (muse-spark). Responses-mode models return reasoning as
``reasoning`` items with ``content``/``summary`` blocks, or as an opaque
``encrypted_content`` blob (meta muse-spark) which is stashed on
``provider_specific_fields["reasoning_items"]`` so ``to_responses_input`` can
replay it verbatim on the next turn (stateless round-trip); the assistant
message is marked ``reasoning_redacted`` instead of fabricating placeholder
text.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional

from ..runtime import VERIFY_SSL, make_client
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
from ..utils import sse_json_lines, system_prompt

DEFAULT_TIMEOUT = 120.0

#: Per-stream correlation state for the SSE loop. ``responses_stream`` resets
#: this before each request; ``parse_responses_chunk`` reads/updates it so
#: event-to-event correlation (function_call ``item_id`` -> call_id/name and
#: reasoning item capture) survives while keeping the public single-argument
#: signature of ``parse_responses_chunk`` stable.
_stream_state: Dict[str, Any] = {"tool_items": {}, "reasoning_items": {}}


def responses_payload(
    resolved: Dict[str, Any],
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    stream: bool,
    kwargs: Dict[str, Any],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": resolved["route"],
        "input": to_responses_input(messages, resolved.get("model")),
        "stream": stream,
        "store": False,
    }

    if tools:
        payload["tools"] = [responses_tool(t) for t in tools]

    api_block = resolved.get("api_block") or {}
    if api_block.get("reasoning_effort"):
        payload["reasoning"] = {"effort": api_block["reasoning_effort"], "summary": "auto"}
        # Encrypted reasoning blobs (meta muse-spark) are only returned when
        # explicitly requested; without them prior reasoning items cannot be
        # replayed on the next turn.
        payload["include"] = ["reasoning.encrypted_content"]

    if api_block.get("parallel_tool_calls") is not None:
        payload["parallel_tool_calls"] = api_block["parallel_tool_calls"]

    max_tokens = kwargs.get("max_tokens")
    if max_tokens:
        payload["max_output_tokens"] = max_tokens

    temperature = kwargs.get("temperature")
    if temperature is not None:
        payload["temperature"] = temperature

    extra_body = dict(kwargs.get("extra_body") or {})
    # The Responses API controls reasoning via the nested ``reasoning.effort``
    # field (already handled above); a generic top-level ``thinking`` budget
    # (or flat ``reasoning_effort``) has no wire equivalent and would be
    # rejected as an unknown field.
    extra_body.pop("reasoning_effort", None)
    extra_body.pop("thinking", None)
    payload.update(resolved.get("extra_body") or {})
    payload.update(extra_body)
    return payload


def to_responses_input(
    messages: List[Dict[str, Any]], current_model: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Convert OpenAI chat messages to responses-API input items.

    ``current_model`` gates the encrypted-reasoning replay: reasoning items are
    only replayed when the model that produced them (recorded at stash time in
    ``provider_specific_fields["reasoning_items_origin"]``) matches the current
    target. Foreign encrypted reasoning (ids + ciphertext are provider/model
    specific) is dropped instead of replayed, which would 400.
    """
    items: List[Dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        if role == "system":
            continue  # handled via instructions at call site

        if role == "assistant":
            # Replay stashed reasoning items BEFORE the assistant message item
            # so the provider can continue its OWN encrypted reasoning state
            # (stateless round-trip: the whole conversation is re-sent).
            for r_item in _stashed_reasoning_items(msg, current_model):
                items.append(_reasoning_input_item(r_item))

            # Assistant turns must use ``output_text`` content blocks; Copilot /
            # OpenAI reject ``input_text`` on assistant messages with HTTP 400
            # ("Supported values are: 'output_text' and 'refusal'").
            if content:
                text = content if isinstance(content, str) else json.dumps(content)
                items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": text}],
                    }
                )

            # Prior assistant tool calls are ``function_call`` input items
            # (``function_call_output`` is reserved for tool results below).
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") or {}
                items.append(
                    {
                        "type": "function_call",
                        "call_id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "arguments": fn.get("arguments", ""),
                    }
                )
            continue

        if role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": msg.get("tool_call_id", ""),
                    "output": content or "",
                }
            )
            continue

        if isinstance(content, list):
            items.append(
                {
                    "type": "message",
                    "role": role,
                    "content": _responses_user_content(content),
                }
            )

            continue

        text = content if isinstance(content, str) else json.dumps(content)
        items.append(
            {"type": "message", "role": role, "content": [{"type": "input_text", "text": text}]}
        )

    return items


def responses_tool(tool: Dict[str, Any]) -> Dict[str, Any]:
    fn = tool.get("function") or {}
    return {
        "type": "function",
        "name": fn.get("name", ""),
        "description": fn.get("description", ""),
        "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
        "strict": tool.get("strict", False),
    }


async def responses_complete(
    resolved: Dict[str, Any],
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    key: Optional[str],
    headers: Dict[str, str],
    kwargs: Dict[str, Any],
) -> CompletionResponse:
    url = f"{resolved['api_base']}/responses"
    payload = responses_payload(resolved, messages, tools, False, kwargs)
    system = system_prompt(messages)

    if system:
        payload["instructions"] = system

    hdrs = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", **headers}

    async with make_client(timeout=DEFAULT_TIMEOUT, verify=VERIFY_SSL) as client:
        resp = await client.post(url, json=payload, headers=hdrs)
        resp.raise_for_status()
        data = resp.json()

    return normalize_responses_response(data, resolved["model"])


async def responses_stream(
    resolved: Dict[str, Any],
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    key: Optional[str],
    headers: Dict[str, str],
    kwargs: Dict[str, Any],
) -> AsyncIterator[CompletionChunk]:
    url = f"{resolved['api_base']}/responses"
    payload = responses_payload(resolved, messages, tools, True, kwargs)
    system = system_prompt(messages)

    if system:
        payload["instructions"] = system

    hdrs = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", **headers}

    _reset_stream_state()
    # Tag reasoning items stashed during this stream with the producing model
    # so the request encoder replays them only to the same model (a switch to
    # another provider/model 400s on foreign reasoning ids/ciphertext).
    _stream_state["model"] = resolved["model"]

    async with make_client(timeout=DEFAULT_TIMEOUT, verify=VERIFY_SSL) as client:
        async with client.stream("POST", url, json=payload, headers=hdrs) as resp:
            resp.raise_for_status()
            async for json_obj in sse_json_lines(resp):
                chunk = parse_responses_chunk(json_obj)

                if chunk:
                    yield chunk


def normalize_responses_response(data: Dict[str, Any], model: str) -> CompletionResponse:
    parts: List[Part] = []
    provider_fields: Dict[str, Any] = {}

    for item in data.get("output") or []:
        item_type = item.get("type")

        if item_type == "reasoning":
            for block in item.get("content") or []:
                if block.get("type") == "reasoning_text" and block.get("text"):
                    parts.append(ReasoningPart(text=block["text"]))

            for block in item.get("summary") or []:
                if block.get("type") == "summary_text" and block.get("text"):
                    parts.append(ReasoningPart(text=block["text"]))

            # Encrypted reasoning (e.g. meta muse-spark): an opaque blob that
            # must be echoed back verbatim on the next turn. Stash the whole
            # item (id + summary + encrypted_content) under
            # provider_specific_fields["reasoning_items"] and mark the message
            # redacted instead of fabricating placeholder text.
            if item.get("encrypted_content"):
                provider_fields.setdefault("reasoning_items", []).append(item)
                # Record which model produced this encrypted reasoning so the
                # request encoder only replays it to the SAME model (ids and
                # ciphertext are model-specific; a switch 400s otherwise).
                provider_fields["reasoning_items_origin"] = model
                parts.append(ReasoningPart(redacted=True))

        elif item_type == "function_call":
            args_raw = item.get("arguments") or "{}"

            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except json.JSONDecodeError:
                args = {"_raw": args_raw}

            parts.append(
                ToolCallPart(
                    name=item.get("name", ""),
                    arguments=args,
                    tool_call_id=item.get("call_id") or item.get("id"),
                )
            )

        elif item_type == "message":
            for block in item.get("content") or []:
                if block.get("type") == "output_text" and block.get("text"):
                    parts.append(TextPart(text=block["text"]))

    message = parts_message_to_message(
        PartsMessage(role="assistant", parts=parts, provider_metadata=provider_fields)
    )
    finish = data.get("status")

    if finish == "completed":
        finish = "stop"

    usage = _build_usage(data.get("usage") or {})
    return CompletionResponse(
        id=data.get("id"),
        model=model,
        choices=[Choice(index=0, message=message, finish_reason=finish)],
        usage=usage,
        provider_specific_fields=provider_fields,
    )


def parse_responses_chunk(data: Dict[str, Any]) -> Optional[CompletionChunk]:
    """Parse one responses-API SSE event into a normalized chunk."""
    evt = data.get("type") or ""
    chunk = CompletionChunk()

    if evt == "response.output_text.delta":
        chunk.text = data.get("delta") or ""
        return chunk

    if evt == "response.reasoning_summary_text.delta":
        chunk.reasoning = data.get("delta") or ""
        return chunk

    if evt == "response.reasoning_text.delta":
        chunk.reasoning = data.get("delta") or ""
        return chunk

    if evt == "response.output_item.added":
        _on_output_item_added(data.get("item") or {}, data.get("output_index"))
        return None

    if evt == "response.output_item.done":
        _on_output_item_done(data.get("item") or {}, data.get("output_index"))
        return None

    if evt == "response.function_call_arguments.delta":
        # OpenAI correlates deltas via item_id (== the function_call item id).
        # Copilot sends a *rotating* opaque item_id on every delta event, so
        # fall back to output_index (stable per item in the output array).
        meta = _stream_state["tool_items"].get(data.get("item_id") or "") or {}

        if not meta:
            meta = _stream_state["tool_items"].get(data.get("output_index")) or {}

        chunk.tool_calls = [
            ToolCall(
                id=meta.get("call_id") or "",
                name=meta.get("name") or "",
                arguments={"_fragment": data.get("delta") or ""},
            )
        ]
        return chunk

    if evt == "response.completed":
        resp = data.get("response") or {}
        chunk.finish_reason = "stop" if resp.get("status") == "completed" else resp.get("status")

        _capture_final_reasoning(resp)

        # Reasoning metadata rides on the authoritative completed event; the
        # per-event ciphertext differs, so only the final items are emitted.
        if _stream_state["reasoning_items"]:
            chunk.provider_specific_fields = {
                "reasoning_items": list(_stream_state["reasoning_items"].values()),
                "reasoning_items_origin": _stream_state.get("model"),
            }

        chunk.usage = _build_usage(resp.get("usage") or {})
        return chunk

    return None


def _reset_stream_state() -> None:
    """Clear per-stream correlation state before a new SSE loop."""
    _stream_state["tool_items"] = {}
    _stream_state["reasoning_items"] = {}
    _stream_state["model"] = None


def _on_output_item_added(item: Dict[str, Any], output_index: Optional[int] = None) -> None:
    """Register function_call / reasoning items when they first appear.

    ``response.function_call_arguments.delta`` events carry the item_id on
    OpenAI but a rotating opaque item_id on Copilot, so the call_id + name are
    registered under BOTH the item id and its ``output_index`` to let the delta
    handler correlate either way.
    """
    item_type = item.get("type")

    if item_type == "function_call":
        meta = {
            "call_id": item.get("call_id") or item.get("id"),
            "name": item.get("name") or "",
        }

        if item.get("id"):
            _stream_state["tool_items"][item["id"]] = meta

        if output_index is not None:
            _stream_state["tool_items"][output_index] = meta

    elif item_type == "reasoning":
        _stream_state["reasoning_items"][item.get("id")] = item


def _on_output_item_done(item: Dict[str, Any], output_index: Optional[int] = None) -> None:
    """Refresh item metadata from the ``output_item.done`` event.

    The done event carries a fuller function_call (call_id) and reasoning item
    (encrypted_content may only be populated here) than the added event.
    """
    item_type = item.get("type")

    if item_type == "function_call":
        meta = {
            "call_id": item.get("call_id") or item.get("id"),
            "name": item.get("name") or "",
        }

        if item.get("id"):
            _stream_state["tool_items"][item["id"]] = meta

        if output_index is not None:
            _stream_state["tool_items"][output_index] = meta

    elif item_type == "reasoning":
        _stream_state["reasoning_items"][item.get("id")] = item


def _capture_final_reasoning(resp: Dict[str, Any]) -> None:
    """Overwrite per-event reasoning ciphertext with the authoritative items.

    The ``encrypted_content`` observed on ``output_item.added``/``done`` can
    differ from the final value; the ``output`` embedded in the
    ``response.completed`` event is authoritative.
    """
    items = [
        item
        for item in resp.get("output") or []
        if item.get("type") == "reasoning" and item.get("encrypted_content")
    ]
    _stream_state["reasoning_items"] = {item.get("id"): item for item in items}


def _stashed_reasoning_items(
    msg: Dict[str, Any], current_model: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Collect stashed reasoning items from a stored assistant message.

    The normalizer stores whole ``reasoning`` items under
    ``provider_specific_fields["reasoning_items"]``; ``helpers.requests`` may
    hoist them to the message top level (``msg["reasoning_items"]``) before
    this point, so both locations are honoured.

    Encrypted reasoning is model-specific: the ``id`` format and ciphertext are
    only valid for the model that produced them. When the current target model
    differs from the recorded origin (or the origin is unknown/absent -- a
    legacy or foreign stash), the items are dropped instead of being replayed
    verbatim; replaying foreign items 400s ("Invalid reasoning item id
    format").
    """
    raw = (msg.get("provider_specific_fields") or {}).get("reasoning_items")
    if raw is None:
        raw = msg.get("reasoning_items")

    if not raw:
        return []

    origin = (msg.get("provider_specific_fields") or {}).get("reasoning_items_origin")

    if not current_model or not origin or origin != current_model:
        return []

    if isinstance(raw, dict):
        return [raw]

    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]

    return []


def _reasoning_input_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Build the responses-API input item that replays a prior reasoning item."""
    return {
        "type": "reasoning",
        "id": item.get("id"),
        "encrypted_content": item.get("encrypted_content"),
        "summary": item.get("summary") or [],
    }


def _build_usage(usage_raw: Dict[str, Any]) -> Usage:
    """Map responses-API usage fields onto the normalized ``Usage`` shape.

    ``input_tokens_details``/``output_tokens_details`` are preserved wholesale
    so ``output_tokens_details.reasoning_tokens`` lands on
    ``completion_tokens_details`` for reasoning-token accounting.
    """
    input_details = usage_raw.get("input_tokens_details") or {}
    output_details = usage_raw.get("output_tokens_details") or {}
    return Usage(
        prompt_tokens=usage_raw.get("input_tokens"),
        completion_tokens=usage_raw.get("output_tokens"),
        total_tokens=usage_raw.get("total_tokens"),
        prompt_cache_hit_tokens=input_details.get("cached_tokens"),
        prompt_tokens_details=input_details,
        completion_tokens_details=output_details,
    )


def _responses_user_content(content: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Translate OpenAI-style user content parts into responses-API content parts.

    - ``text`` parts become ``{"type": "input_text", ...}``
    - ``image_url`` parts become ``{"type": "input_image", "image_url": <url>}``
    - anything else is JSON-serialized into an ``input_text`` part (never dropped)
    """
    out: List[Dict[str, Any]] = []

    for part in content:
        if not isinstance(part, dict):
            out.append({"type": "input_text", "text": json.dumps(part)})

            continue

        if part.get("type") == "text" and isinstance(part.get("text"), str):
            out.append({"type": "input_text", "text": part["text"]})

            continue

        if part.get("type") == "image_url":
            image_url = part.get("image_url")
            url = image_url.get("url") if isinstance(image_url, dict) else None

            if isinstance(url, str):
                out.append({"type": "input_image", "image_url": url})

                continue

        out.append({"type": "input_text", "text": json.dumps(part)})

    return out


__all__ = [
    "responses_payload",
    "to_responses_input",
    "responses_tool",
    "responses_complete",
    "responses_stream",
    "normalize_responses_response",
    "parse_responses_chunk",
]
