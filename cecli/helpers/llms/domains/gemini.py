"""Gemini generateContent / streamGenerateContent adapter.

Reasoning effort maps to ``generationConfig.thinkingConfig`` via
:func:`gemini_thinking_config` (mirrors litellm Vertex
``_map_reasoning_effort_to_thinking_level``): Gemini 3+ models use
``thinkingLevel`` + ``includeThoughts``; older models use ``thinkingBudget``.
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
from ..utils import split_data_url, sse_json_lines, system_prompt

DEFAULT_TIMEOUT = 120.0

#: Per-stream tool-call index map (``call_id -> index``), reset by

#: Per-stream tool-call index map (``call_id -> index``), reset by
#: :func:`gemini_stream`.  Gemini streams each parallel functionCall part as a
#: separate SSE chunk; assigning a distinct monotonic index per call_id keeps
#: them from collapsing onto index 0 in the litellm shim's accumulation.
_stream_state: Dict[str, Dict[str, int]] = {"tool_indices": {}}


def gemini_payload(
    resolved: Dict[str, Any],
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    kwargs: Dict[str, Any],
) -> Dict[str, Any]:
    system = system_prompt(messages)
    # Map assistant tool-call ids to function metadata (name + native id /
    # signature) so tool results can be encoded as ``functionResponse`` parts.
    # Gemini requires a function response for each pending functionCall; a bare
    # text part makes the model re-invoke the tool instead of consuming the
    # result.
    call_meta = _build_call_meta(messages)
    # Gemini 3.x requires a native ``thoughtSignature`` on every replayed
    # ``functionCall`` part; messages from other providers cannot provide one,
    # so their calls are dropped to text (see :func:`_requires_thought_signatures`).
    require_signatures = _requires_thought_signatures(resolved)

    payload: Dict[str, Any] = {
        "contents": _encode_contents(messages, call_meta, require_signatures),
    }

    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}

    if tools:
        payload["tools"] = [{"functionDeclarations": [gemini_tool(t) for t in tools]}]

    api_block = resolved.get("api_block") or {}
    gen_config = payload.setdefault("generationConfig", {})

    # Caller/system overrides ride in ``kwargs["extra_body"]`` (models.py's
    # ``set_reasoning_effort`` / ``set_thinking_tokens``). Map them onto
    # ``generationConfig.thinkingConfig`` and keep the generic keys out of the
    # top level (Gemini rejects unknown fields).
    override_body = kwargs.get("extra_body") or {}
    override_effort = override_body.get("reasoning_effort")
    override_thinking = override_body.get("thinking")

    # The explicit ``set_thinking_tokens`` budget wins over the config-default
    # ``reasoning_effort`` that rides in the same channel: gemini configs default
    # to ``reasoning_effort`` (never ``thinking``), so an override ``thinking``
    # only appears when the user explicitly requested a thinking budget.
    if isinstance(override_thinking, dict) and override_thinking.get("budget_tokens"):
        gen_config["thinkingConfig"] = {"thinkingBudget": override_thinking["budget_tokens"]}
    elif override_effort:
        gen_config["thinkingConfig"] = gemini_thinking_config(resolved, override_effort)
    elif api_block.get("reasoning_effort"):
        gen_config["thinkingConfig"] = gemini_thinking_config(
            resolved, api_block["reasoning_effort"]
        )
    elif api_block.get("thinking"):
        gen_config["thinkingConfig"] = {
            "thinkingBudget": api_block["thinking"].get("budget_tokens", 8192)
        }

    max_tokens = kwargs.get("max_tokens")
    if max_tokens:
        payload.setdefault("generationConfig", {})["maxOutputTokens"] = max_tokens

    temperature = kwargs.get("temperature")
    if temperature is not None:
        payload.setdefault("generationConfig", {})["temperature"] = temperature

    # Apply extra_body passthrough without leaking the generic reasoning keys
    # (they are consumed above into thinkingConfig).
    extra_body = dict(resolved.get("extra_body") or {})
    extra_body.update(kwargs.get("extra_body") or {})
    extra_body.pop("reasoning_effort", None)
    extra_body.pop("thinking", None)
    payload.update(extra_body)
    return payload


def gemini_thinking_config(resolved: Dict[str, Any], effort: str) -> Dict[str, Any]:
    """Map reasoning_effort to Gemini thinkingConfig.

    Mirrors litellm ``VertexGeminiConfig._map_reasoning_effort_to_thinking_level``:
    Gemini 3+ models use ``thinkingLevel`` + ``includeThoughts`` instead of the
    older ``thinkingBudget``. gemini-3-flash supports the "minimal" level.
    """
    route = (resolved.get("route") or "").lower()
    is_gemini3flash = "gemini-3" in route and "flash" in route
    include = effort != "disable" and effort != "none"

    level_map = {
        "minimal": "minimal" if is_gemini3flash else "low",
        "low": "low",
        "medium": "medium" if is_gemini3flash else "high",
        "high": "high",
        "disable": "minimal" if is_gemini3flash else "low",
        "none": "minimal" if is_gemini3flash else "low",
    }
    level = level_map.get(effort, "high")
    return {"thinkingLevel": level, "includeThoughts": include}


def gemini_content(
    msg: Dict[str, Any],
    name_by_call_id: Optional[Dict[str, Any]] = None,
    require_signatures: bool = False,
) -> Dict[str, Any]:
    """Encode one chat message as a Gemini ``Content`` dict.

    ``name_by_call_id`` maps a tool-call id to either a plain function name or
    a ``{"name": ..., "signature": ...}`` dict (see :func:`gemini_payload`);
    tool results become ``functionResponse`` parts that echo the original call
    id/signature when available. Assistant turns replay prior thought parts
    (with their ``thoughtSignature``) for multi-turn reasoning.
    ``require_signatures`` is set for Gemini 3.x targets, which reject
    ``functionCall`` parts without a native signature (see
    :func:`_requires_thought_signatures`).
    """
    if msg.get("role") == "tool":
        return _tool_content(msg, name_by_call_id, require_signatures)

    if msg.get("role") == "assistant":
        return _model_content(msg, require_signatures)

    # user (and any non-assistant role, e.g. system, which folds into user).
    content = msg.get("content")

    if isinstance(content, str):
        return {"role": "user", "parts": [{"text": content}]}

    if isinstance(content, list):
        return {"role": "user", "parts": _gemini_user_parts(content)}

    parts: List[Dict[str, Any]] = []

    if content:
        parts.append({"text": json.dumps(content)})

    return {"role": "user", "parts": parts}


def gemini_tool(tool: Dict[str, Any]) -> Dict[str, Any]:
    fn = tool.get("function") or {}
    return {
        "name": fn.get("name", ""),
        "description": fn.get("description", ""),
        "parameters": _gemini_schema(fn.get("parameters", {"type": "object", "properties": {}})),
    }


async def gemini_complete(
    resolved: Dict[str, Any],
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    key: Optional[str],
    headers: Dict[str, str],
    kwargs: Dict[str, Any],
) -> CompletionResponse:
    url = f"{resolved['api_base']}/v1beta/models/{resolved['route']}:generateContent"
    payload = gemini_payload(resolved, messages, tools, kwargs)
    hdrs = {"Content-Type": "application/json", **headers}
    params: Dict[str, str] = {}

    async with make_client(timeout=DEFAULT_TIMEOUT, verify=VERIFY_SSL) as client:
        resp = await client.post(url, json=payload, headers=hdrs, params=params)
        resp.raise_for_status()
        data = resp.json()

    return normalize_gemini_response(data, resolved["model"])


async def gemini_stream(
    resolved: Dict[str, Any],
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    key: Optional[str],
    headers: Dict[str, str],
    kwargs: Dict[str, Any],
) -> AsyncIterator[CompletionChunk]:
    url = f"{resolved['api_base']}/v1beta/models/{resolved['route']}:streamGenerateContent"
    payload = gemini_payload(resolved, messages, tools, kwargs)
    hdrs = {"Content-Type": "application/json", **headers}
    params = {"alt": "sse"}
    has_seen_tool_calls = False
    _stream_state["tool_indices"] = {}

    async with make_client(timeout=DEFAULT_TIMEOUT, verify=VERIFY_SSL) as client:
        async with client.stream("POST", url, json=payload, headers=hdrs, params=params) as resp:
            resp.raise_for_status()
            async for json_obj in sse_json_lines(resp):
                chunk = parse_gemini_chunk(json_obj)

                if chunk:
                    if chunk.tool_calls:
                        has_seen_tool_calls = True

                    # Once a functionCall has streamed, the turn's finish must
                    # read "tool_calls" even if a later chunk reports STOP.
                    if has_seen_tool_calls and chunk.finish_reason is not None:
                        chunk.finish_reason = "tool_calls"

                    yield chunk


def normalize_gemini_response(data: Dict[str, Any], model: str) -> CompletionResponse:
    parts: List[Part] = []
    provider_fields: Dict[str, Any] = {}
    finish = None
    saw_function_call = False
    thought_signature = None

    for candidate in data.get("candidates") or []:
        content = candidate.get("content") or {}

        for part in content.get("parts") or []:
            if "text" in part:
                if part.get("thought"):
                    text = part.get("text") or ""
                    parts.append(ReasoningPart(text=text, redacted=not text))
                else:
                    parts.append(TextPart(text=part.get("text") or ""))

            if "functionCall" in part:
                fc = part["functionCall"]
                saw_function_call = True
                call_part = ToolCallPart(
                    name=fc.get("name", ""),
                    arguments=fc.get("args") or {},
                    tool_call_id=fc.get("id"),
                )

                # Gemini attaches thoughtSignature as a SIBLING of the
                # functionCall part, not as a field inside it.
                sig = part.get("thoughtSignature") or fc.get("signature")
                if sig:
                    call_part.provider_metadata["signature"] = sig

                parts.append(call_part)

        if candidate.get("thoughtSignature"):
            thought_signature = candidate["thoughtSignature"]

        finish = _map_finish_reason(candidate.get("finishReason"))

    if saw_function_call:
        finish = "tool_calls"

    if thought_signature:
        # Echo the thoughtSignature back on the next request (the encoder
        # replays prior thought parts with it). Keep the raw camelCase field
        # plus the snake_case alias the cecli request pipeline reads.
        provider_fields["thoughtSignature"] = thought_signature
        provider_fields["thought_signature"] = thought_signature

    # Preserve raw thought parts for verbatim replay, and per-call functionCall
    # signatures so tool results echo the original id/signature.
    thought_parts = []
    for p in parts:
        if isinstance(p, ReasoningPart):
            thought_entry = {"text": p.text, "thought": True}

            if p.provider_metadata.get("signature"):
                thought_entry["signature"] = p.provider_metadata["signature"]

            thought_parts.append(thought_entry)

    if thought_parts:
        provider_fields["thought_parts"] = thought_parts

    call_signatures = {
        p.tool_call_id: p.provider_metadata["signature"]
        for p in parts
        if isinstance(p, ToolCallPart) and p.tool_call_id and p.provider_metadata.get("signature")
    }

    if call_signatures:
        provider_fields["function_call_signatures"] = call_signatures

    pm = PartsMessage(role="assistant", parts=parts, provider_metadata=provider_fields)
    message = parts_message_to_message(pm)
    usage = _gemini_usage(data.get("usageMetadata") or {})
    return CompletionResponse(
        id=data.get("responseId"),
        model=model,
        choices=[Choice(index=0, message=message, finish_reason=finish)],
        usage=usage,
        provider_specific_fields=provider_fields,
    )


def parse_gemini_chunk(data: Dict[str, Any]) -> Optional[CompletionChunk]:
    chunk = CompletionChunk()
    parts: List[str] = []
    reasoning: List[str] = []
    tool_calls: List[ToolCall] = []
    saw_function_call = False

    for candidate in data.get("candidates") or []:
        content = candidate.get("content") or {}

        for part in content.get("parts") or []:
            if "text" in part:
                if part.get("thought"):
                    reasoning.append(part["text"])
                else:
                    parts.append(part["text"])

            if "functionCall" in part:
                fc = part["functionCall"]
                saw_function_call = True
                call_id = fc.get("id") or f"call_{len(tool_calls)}"

                # Assign a stable per-stream index keyed by call id so parallel
                # functionCall parts streamed in separate chunks do not collapse
                # onto index 0 in the litellm shim.
                indices = _stream_state["tool_indices"]

                if call_id not in indices:
                    indices[call_id] = len(indices)

                tool_calls.append(
                    ToolCall(
                        id=call_id,
                        name=fc.get("name", ""),
                        arguments=fc.get("args") or {},
                        index=indices[call_id],
                    )
                )

                # Capture the native thoughtSignature (a sibling of functionCall)
                # so streamed tool calls can echo it back on the next turn.
                sig = part.get("thoughtSignature")

                if sig:
                    chunk.provider_specific_fields.setdefault("function_call_signatures", {})[
                        call_id
                    ] = sig

        if candidate.get("finishReason"):
            chunk.finish_reason = _map_finish_reason(candidate.get("finishReason"))

    if saw_function_call:
        chunk.finish_reason = "tool_calls"

    chunk.text = "".join(parts)
    chunk.reasoning = "".join(reasoning)
    chunk.tool_calls = tool_calls
    chunk.usage = _gemini_usage(data.get("usageMetadata") or {})

    if (
        not chunk.text
        and not chunk.reasoning
        and not chunk.tool_calls
        and not chunk.finish_reason
        and not chunk.usage
    ):
        return None

    return chunk


# ---------------------------------------------------------------------------
# Private helpers (kept at the bottom so the core logic reads first)
# ---------------------------------------------------------------------------


_FINISH_MAP = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "RECITATION": "content_filter",
    "LANGUAGE": "content_filter",
    "BLOCKLIST": "content_filter",
    "PROHIBITED_CONTENT": "content_filter",
    "SPII": "content_filter",
    "IMAGE_SAFETY": "content_filter",
    "MALFORMED_FUNCTION_CALL": "tool_calls",
}


def _map_finish_reason(raw: Optional[str]) -> Optional[str]:
    """Map a Gemini ``finishReason`` to the normalized finish_reason."""
    if raw is None:
        return None

    return _FINISH_MAP.get(raw, raw)


def _gemini_usage(usage_raw: Dict[str, Any]) -> Optional[Usage]:
    """Map Gemini ``usageMetadata`` onto :class:`Usage`.

    ``thoughtsTokenCount`` is added to the output tokens when
    ``is_candidate_token_count_inclusive`` is False, and is surfaced on
    ``completion_tokens_details["reasoning_tokens"]``;
    ``cachedContentTokenCount`` maps to ``prompt_cache_hit_tokens``.
    """
    if not usage_raw:
        return None

    candidates = usage_raw.get("candidatesTokenCount")
    thoughts = usage_raw.get("thoughtsTokenCount")
    completion = candidates

    if thoughts and usage_raw.get("is_candidate_token_count_inclusive") is False:
        completion = (candidates or 0) + thoughts

    details = {"reasoning_tokens": thoughts} if thoughts is not None else None

    return Usage(
        prompt_tokens=usage_raw.get("promptTokenCount"),
        completion_tokens=completion,
        total_tokens=usage_raw.get("totalTokenCount"),
        prompt_cache_hit_tokens=usage_raw.get("cachedContentTokenCount"),
        completion_tokens_details=details,
    )


def _requires_thought_signatures(resolved: Dict[str, Any]) -> bool:
    """Whether the target model requires a signature on replayed functionCall parts.

    Gemini 3.x demands the native ``thoughtSignature`` (an opaque encrypted
    blob) on every ``functionCall`` part replayed in history; without it the
    API rejects the request with a 400. Older models (e.g. gemini-2.5-pro)
    accept signature-less replays. Messages from other providers never carry a
    Gemini signature, so for 3.x targets the encoder drops those calls to text.
    """
    return "gemini-3" in (resolved.get("route") or "").lower()


def _build_call_meta(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Map assistant tool-call ids to ``{"name", "signature"}`` metadata.

    Signatures come from ``provider_specific_fields["function_call_signatures"]``
    (captured by :func:`normalize_gemini_response` from native ``functionCall``
    parts) so ``functionResponse`` parts echo the original id/signature.
    """
    meta: Dict[str, Any] = {}

    for m in messages:
        if m.get("role") != "assistant":
            continue

        psf = m.get("provider_specific_fields") or {}
        signatures = psf.get("function_call_signatures") or {}

        for tc in m.get("tool_calls") or []:
            call_id = tc.get("id")

            if not call_id:
                continue

            fn = tc.get("function") or {}
            meta[call_id] = {
                "name": fn.get("name", ""),
                "signature": signatures.get(call_id),
            }

    return meta


def _call_meta(name_by_call_id: Optional[Dict[str, Any]], call_id: Optional[str]) -> Dict[str, Any]:
    """Resolve a tool-call id to metadata (tolerates legacy ``{id: name}`` maps)."""
    if not name_by_call_id or not call_id:
        return {}

    entry = name_by_call_id.get(call_id)

    if isinstance(entry, dict):
        return entry

    return {"name": entry or ""}


def _tool_content(
    msg: Dict[str, Any],
    name_by_call_id: Optional[Dict[str, Any]],
    require_signatures: bool = False,
) -> Dict[str, Any]:
    """Encode a tool-result message as a ``functionResponse`` user Content.

    On Gemini 3.x targets the matching ``functionCall`` was dropped to text
    when no signature was available, so the result is downgraded to a plain
    text part too (a ``functionResponse`` without its ``functionCall`` would
    be rejected or ignored).
    """
    meta = _call_meta(name_by_call_id, msg.get("tool_call_id"))
    name = meta.get("name") or ""

    if name and (meta.get("signature") or not require_signatures):
        fr: Dict[str, Any] = {
            "name": name,
            "response": {"output": msg.get("content") or ""},
        }
        call_id = msg.get("tool_call_id")

        if call_id:
            fr["id"] = call_id

        part_dict: Dict[str, Any] = {"functionResponse": fr}

        if require_signatures and meta.get("signature"):
            part_dict["thoughtSignature"] = meta["signature"]

        return {"role": "user", "parts": [part_dict]}

    # No matching functionCall recorded (or it was dropped for a
    # signature-requiring model) -- fall back to plain text.
    return {"role": "user", "parts": [{"text": msg.get("content") or ""}]}


def _model_content(msg: Dict[str, Any], require_signatures: bool = False) -> Dict[str, Any]:
    """Encode an assistant message, replaying prior thought parts.

    Gemini requires the full thinking turn (thought parts + ``thoughtSignature``)
    echoed back in the history for multi-turn reasoning, even when thoughts are
    hidden. The parts/signature captured by :func:`normalize_gemini_response`
    live on ``provider_specific_fields``; when an upstream consumer dropped
    them, fall back to reconstructing a single thought part from
    ``reasoning_content``.

    Gemini 3.x also requires a native ``thoughtSignature`` on every replayed
    ``functionCall`` part. Foreign messages never carry one, so on those models
    the call is dropped and surfaced as a text part instead of failing with a
    400 (see :func:`_requires_thought_signatures`).
    """
    psf = msg.get("provider_specific_fields") or {}
    thought_parts = psf.get("thought_parts") or []
    parts: List[Dict[str, Any]] = []

    for tp in thought_parts:
        tp_out: Dict[str, Any] = {"text": tp.get("text", ""), "thought": True}

        # The normalizer may stash the thought-part signature under either key
        # ("thoughtSignature" preferred, "signature" tolerated).
        tp_sig = tp.get("thoughtSignature") or tp.get("signature")

        if tp_sig:
            tp_out["thoughtSignature"] = tp_sig

        parts.append(tp_out)

    # Fallback: reconstruct a single thought part from reasoning_content when
    # the richer provider metadata was dropped by an upstream consumer. Thought
    # parts must precede any visible text/functionCall parts in the Content.
    if not thought_parts:
        reasoning = msg.get("reasoning_content")

        if isinstance(reasoning, str) and reasoning.strip():
            parts.append({"text": reasoning, "thought": True})

    content = msg.get("content")

    if isinstance(content, str):
        if content or not parts:
            parts.append({"text": content})
    elif content:
        parts.append({"text": json.dumps(content)})

    call_signatures = psf.get("function_call_signatures") or {}

    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        args_raw = fn.get("arguments") or "{}"

        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
        except json.JSONDecodeError:
            args = {}

        sig = call_signatures.get(tc["id"]) if tc.get("id") else None

        # A signature-requiring model cannot replay a call without its native
        # signature (foreign messages never have one). Drop the functionCall
        # and surface the call as text so the turn stays coherent; the
        # matching tool result is downgraded to text by _tool_content too.
        if require_signatures and not sig:
            parts.append({"text": f"[tool call: {fn.get('name', '')}({json.dumps(args)})]"})
            continue

        fc: Dict[str, Any] = {"name": fn.get("name", ""), "args": args}

        if tc.get("id"):
            fc["id"] = tc["id"]

        part_dict: Dict[str, Any] = {"functionCall": fc}

        if require_signatures and sig:
            part_dict["thoughtSignature"] = sig

        parts.append(part_dict)

    content_dict: Dict[str, Any] = {"role": "model", "parts": parts}
    signature = psf.get("thoughtSignature") or psf.get("thought_signature")

    if signature and signature != "skip_thought_signature_validator":
        content_dict["thoughtSignature"] = signature

    return content_dict


def _encode_contents(
    messages: List[Dict[str, Any]],
    name_by_call_id: Optional[Dict[str, Any]],
    require_signatures: bool = False,
) -> List[Dict[str, Any]]:
    """Encode the message list, merging consecutive same-role Contents.

    Gemini rejects histories with repeated ``user`` or ``model`` roles. System
    messages are hoisted to ``systemInstruction`` by the caller, so any
    remaining ``system`` role folds into ``user`` (``gemini_content`` maps it),
    and tool results are already ``user``-role ``functionResponse`` parts.
    Merging keeps e.g. multiple tool results (plus a following user text turn)
    in ONE Content right after the assistant tool-call turn.
    """
    encoded = [
        gemini_content(m, name_by_call_id, require_signatures)
        for m in messages
        if m.get("role") != "system"
    ]
    merged: List[Dict[str, Any]] = []

    for content in encoded:
        if merged and merged[-1].get("role") == content.get("role"):
            merged[-1]["parts"].extend(content.get("parts") or [])
        else:
            merged.append(content)

    return merged


#: JSON-Schema keywords Gemini's ``FunctionDeclaration.parameters`` rejects
#: (OpenAPI 3.0 strict subset). ``additionalProperties`` is emitted by
#: OpenAI-style strict tool schemas and caused a 400 for AgentCoder tools.
_GEMINI_UNSUPPORTED_SCHEMA_KEYS = frozenset({"additionalProperties", "$schema", "$defs"})


def _gemini_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively strip JSON-Schema keywords Gemini function declarations reject.

    Gemini validates ``FunctionDeclaration.parameters`` against a strict
    subset of OpenAPI 3.0 and returns 400 for unknown keys (observed:
    ``Unknown name "additionalProperties"`` on AgentCoder tool schemas).
    Everything else -- including ``default``, which Gemini does support -- is
    preserved verbatim.
    """
    if not isinstance(schema, dict):
        return schema

    cleaned: Dict[str, Any] = {}

    for key, value in schema.items():
        if key in _GEMINI_UNSUPPORTED_SCHEMA_KEYS:
            continue

        if isinstance(value, dict):
            cleaned[key] = _gemini_schema(value)
        elif isinstance(value, list):
            cleaned[key] = [
                _gemini_schema(item) if isinstance(item, dict) else item for item in value
            ]
        else:
            cleaned[key] = value

    return cleaned


def _gemini_user_parts(content: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Translate OpenAI-style user content parts into Gemini ``parts``.

    - ``text`` parts become ``{"text": ...}``
    - ``image_url`` data URLs become ``{"inlineData": {"mimeType", "data"}}``
    - ``image_url`` http(s) URLs become ``{"fileData": {"fileUri"}}``
    - anything else is JSON-serialized into a text part (never dropped)
    """
    parts: List[Dict[str, Any]] = []

    for part in content:
        if not isinstance(part, dict):
            parts.append({"text": json.dumps(part)})

            continue

        if part.get("type") == "text" and isinstance(part.get("text"), str):
            parts.append({"text": part["text"]})

            continue

        if part.get("type") == "image_url":
            image_url = part.get("image_url")
            url = image_url.get("url") if isinstance(image_url, dict) else None
            parsed = split_data_url(url)

            if parsed:
                mime, data = parsed
                parts.append({"inlineData": {"mimeType": mime, "data": data}})

                continue

            if isinstance(url, str) and url.startswith(("http://", "https://")):
                parts.append({"fileData": {"fileUri": url}})

                continue

        parts.append({"text": json.dumps(part)})

    return parts


__all__ = [
    "gemini_payload",
    "gemini_thinking_config",
    "gemini_content",
    "gemini_tool",
    "gemini_complete",
    "gemini_stream",
    "normalize_gemini_response",
    "parse_gemini_chunk",
]
