"""Gemini Interactions API adapter (stateless mode).

The Interactions API represents a turn as an ordered ``steps`` array rather than
an assistant message with tool calls. In stateless mode (``store: false``) the
client resends the full history on every request, including previous ``thought``
steps and their encrypted ``signature`` values. This adapter therefore:

- encodes chat messages as Interactions steps (``user_input``, ``thought``,
  ``model_output``, ``function_call``, ``function_result``);
- preserves every model step returned by the API verbatim on
  ``provider_specific_fields["interactions_steps"]`` so the next request replays
  it unchanged, signatures included;
- maps streamed ``step.start`` / ``step.delta`` / ``step.stop`` events onto
  :class:`CompletionChunk`, accumulating tool arguments and signatures.

:func:`cecli.helpers.llms.config.resolve_model_config` selects this adapter for
``gemini/gemini-4-*`` routes; Gemini 3 and older models keep using the
generateContent adapter.
"""

from __future__ import annotations

import copy
import json
import re
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

#: Interactions API endpoint (v1beta).
INTERACTIONS_PATH = "/v1beta/interactions"

#: Revision that selects the ``steps`` schema (the default since June 2026).
API_REVISION = "2026-05-20"

#: Replayable model steps kept on assistant messages for stateless requests.
STEPS_KEY = "interactions_steps"


def interactions_payload(
    resolved: Dict[str, Any],
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    kwargs: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a stateless Interactions request body.

    The full conversation is encoded in ``input``; ``store`` is always false and
    no ``previous_interaction_id`` is ever sent.
    """
    payload: Dict[str, Any] = {
        "model": resolved.get("route") or resolved.get("model"),
        "input": interactions_input(messages),
        "store": False,
    }
    system = system_prompt(messages)

    if system:
        payload["system_instruction"] = system

    if tools:
        payload["tools"] = [interactions_tool(tool) for tool in tools]

    generation_config = _generation_config(resolved, kwargs)

    if generation_config:
        payload["generation_config"] = generation_config

    extra_body = dict(resolved.get("extra_body") or {})
    extra_body.update(kwargs.get("extra_body") or {})

    for key in ("reasoning_effort", "thinking", "thinking_level", "thinking_summaries"):
        extra_body.pop(key, None)

    payload.update(extra_body)
    return payload


def interactions_input(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Encode the whole chat history as an Interactions ``input`` step array."""
    call_names = _call_names(messages)
    steps: List[Dict[str, Any]] = []

    for message in messages:
        role = message.get("role")

        if role == "system":
            continue

        if role == "assistant":
            steps.extend(_assistant_steps(message))
        elif role == "tool":
            steps.append(_function_result_step(message, call_names))
        else:
            steps.append({"type": "user_input", "content": _user_content(message.get("content"))})

    return steps


def interactions_tool(tool: Dict[str, Any]) -> Dict[str, Any]:
    """Translate an OpenAI-style function tool into an Interactions Tool."""
    function = tool.get("function") or tool
    out: Dict[str, Any] = {
        "type": "function",
        "name": function.get("name") or tool.get("name") or "",
    }
    description = function.get("description") or tool.get("description")

    if description:
        out["description"] = description

    parameters = function.get("parameters") or tool.get("parameters")

    if parameters:
        out["parameters"] = parameters

    return out


def interactions_thinking_level(resolved: Dict[str, Any], effort: str) -> str:
    """Map ``reasoning_effort`` to an Interactions ``thinking_level``."""
    route = (resolved.get("route") or "").lower()
    major, minor = _gemini_version(route)

    if major >= 4:
        allow_xhigh = "hydrogen" in route or "neon" in route
        level_map = {
            "minimal": "low",
            "low": "low",
            "medium": "medium",
            "high": "high",
            "xhigh": "xhigh" if allow_xhigh else "high",
            "disable": "low",
            "none": "low",
        }
    else:
        is_gemini3_flash = major == 3 and "flash" in route
        supports_minimal = is_gemini3_flash and minor < 8
        level_map = {
            "minimal": "minimal" if supports_minimal else "low",
            "low": "low",
            "medium": "medium" if is_gemini3_flash else "high",
            "high": "high",
            "xhigh": "high",
            "disable": "low",
            "none": "low",
        }

    return level_map.get(effort, "high")


def normalize_interactions_response(
    data: Dict[str, Any], model: Optional[str]
) -> CompletionResponse:
    """Normalize an Interaction resource into a :class:`CompletionResponse`.

    Every returned step is copied verbatim into ``provider_specific_fields`` so
    a later stateless request can resend thought/function-call/built-in steps
    exactly as received, including their signatures.
    """
    raw_steps = data.get("steps") or []
    parts: List[Part] = []
    provider_fields: Dict[str, Any] = {}
    signatures: List[str] = []
    saw_function_call = False

    for step in raw_steps:
        step_type = step.get("type")

        if step_type == "thought":
            text = _thought_text(step)
            part = ReasoningPart(text=text, redacted=not text)
            signature = step.get("signature")

            if signature:
                part.provider_metadata["signature"] = signature
                signatures.append(signature)

            parts.append(part)
        elif step_type == "function_call":
            saw_function_call = True
            part = ToolCallPart(
                name=step.get("name") or "",
                arguments=step.get("arguments") or {},
                tool_call_id=step.get("id"),
            )
            signature = step.get("signature")

            if signature:
                part.provider_metadata["signature"] = signature

            part.provider_metadata["step"] = copy.deepcopy(step)
            parts.append(part)
        elif step_type == "model_output":
            for block in _content_blocks(step.get("content")):
                if block.get("type") == "text":
                    parts.append(TextPart(text=block.get("text") or ""))

    if raw_steps:
        provider_fields[STEPS_KEY] = copy.deepcopy(raw_steps)

    if data.get("id"):
        provider_fields["interactions_id"] = data["id"]

    if signatures:
        provider_fields["thought_signatures"] = signatures

    message = parts_message_to_message(
        PartsMessage(role="assistant", parts=parts, provider_metadata=provider_fields)
    )
    finish_reason = _map_status(data.get("status"), saw_function_call)

    return CompletionResponse(
        id=data.get("id"),
        model=data.get("model") or model,
        choices=[Choice(index=0, message=message, finish_reason=finish_reason)],
        usage=_interactions_usage(data.get("usage") or {}),
        provider_specific_fields=provider_fields,
    )


async def interactions_complete(
    resolved: Dict[str, Any],
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    key: Optional[str],
    headers: Dict[str, str],
    kwargs: Dict[str, Any],
) -> CompletionResponse:
    """Send a stateless, non-streaming Interactions request."""
    url = f"{resolved['api_base']}{INTERACTIONS_PATH}"
    payload = interactions_payload(resolved, messages, tools, kwargs)
    payload["stream"] = False
    request_headers = _request_headers(headers)

    async with make_client(timeout=DEFAULT_TIMEOUT, verify=VERIFY_SSL) as client:
        resp = await client.post(url, json=payload, headers=request_headers)
        resp.raise_for_status()
        data = resp.json()

    return normalize_interactions_response(data, resolved.get("model"))


async def interactions_stream(
    resolved: Dict[str, Any],
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    key: Optional[str],
    headers: Dict[str, str],
    kwargs: Dict[str, Any],
) -> AsyncIterator[CompletionChunk]:
    """Stream a stateless Interactions request as SSE step events."""
    url = f"{resolved['api_base']}{INTERACTIONS_PATH}"
    payload = interactions_payload(resolved, messages, tools, kwargs)
    payload["stream"] = True
    request_headers = _request_headers(headers)
    state: Dict[str, Any] = {"steps": {}, "order": [], "arguments": {}}

    async with make_client(timeout=DEFAULT_TIMEOUT, verify=VERIFY_SSL) as client:
        async with client.stream("POST", url, json=payload, headers=request_headers) as resp:
            resp.raise_for_status()

            async for event in sse_json_lines(resp):
                chunk = _consume_event(event, state)

                if chunk:
                    yield chunk


# ---------------------------------------------------------------------------
# Private helpers (kept at the bottom so the core logic reads first)
# ---------------------------------------------------------------------------


_FINISH_BY_STATUS = {
    "completed": "stop",
    "incomplete": "length",
    "requires_action": "tool_calls",
    "requires_continuation": "length",
    "cancelled": "error",
    "failed": "error",
}


def _request_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """Return request headers with the interactions JSON/revision headers set."""
    return {
        "Content-Type": "application/json",
        "Api-Revision": API_REVISION,
        **headers,
    }


def _generation_config(resolved: Dict[str, Any], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Build ``generation_config`` from generic request kwargs and model config."""
    config: Dict[str, Any] = {}
    max_tokens = kwargs.get("max_tokens") or kwargs.get("max_completion_tokens")

    if max_tokens:
        config["max_output_tokens"] = max_tokens

    temperature = kwargs.get("temperature")

    if temperature is not None:
        config["temperature"] = temperature

    for key in ("top_p", "top_k"):
        value = kwargs.get(key)

        if value is not None:
            config[key] = value

    override_body = kwargs.get("extra_body") or {}
    api_block = resolved.get("api_block") or {}
    effort = override_body.get("reasoning_effort")
    thinking = override_body.get("thinking")
    explicit_level = override_body.get("thinking_level")

    if explicit_level:
        config["thinking_level"] = explicit_level
    elif isinstance(thinking, dict) and thinking.get("budget_tokens") is not None:
        config["thinking_level"] = _level_from_budget(thinking["budget_tokens"])
    elif effort:
        config["thinking_level"] = interactions_thinking_level(resolved, effort)
    elif api_block.get("reasoning_effort"):
        config["thinking_level"] = interactions_thinking_level(
            resolved, api_block["reasoning_effort"]
        )
    elif api_block.get("thinking"):
        config["thinking_level"] = _level_from_budget(
            api_block["thinking"].get("budget_tokens", 8192)
        )

    summaries = override_body.get("thinking_summaries") or api_block.get("thinking_summaries")

    if summaries:
        config["thinking_summaries"] = summaries

    return config


def _assistant_steps(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Encode an assistant turn, preferring verbatim API steps when present."""
    psf = message.get("provider_specific_fields") or {}
    raw_steps = psf.get(STEPS_KEY)

    if raw_steps:
        return copy.deepcopy(raw_steps)

    steps: List[Dict[str, Any]] = []
    steps.extend(_thought_steps(psf))
    content = message.get("content")

    if isinstance(content, str) and content:
        steps.append({"type": "model_output", "content": [{"type": "text", "text": content}]})
    elif content and not isinstance(content, str):
        text = json.dumps(content)
        steps.append({"type": "model_output", "content": [{"type": "text", "text": text}]})

    for tool_call in message.get("tool_calls") or []:
        step = _function_call_step(tool_call)

        if step:
            steps.append(step)

    return steps


def _thought_steps(psf: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Rebuild thought steps for histories that lack the raw API steps."""
    entries = psf.get("thought_steps") or psf.get("interactions_thought_steps") or []
    steps: List[Dict[str, Any]] = []

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        if entry.get("type") == "thought":
            steps.append(copy.deepcopy(entry))
            continue

        text = entry.get("text") or ""
        step: Dict[str, Any] = {"type": "thought", "summary": []}
        signature = entry.get("signature") or entry.get("thoughtSignature")

        if text:
            step["summary"].append({"type": "text", "text": text})

        if signature:
            step["signature"] = signature

        steps.append(step)

    return steps


def _function_call_step(tool_call: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Translate an OpenAI-style tool call into a function_call step."""
    psf = tool_call.get("provider_specific_fields") or {}
    raw_step = psf.get("interactions_step")

    if isinstance(raw_step, dict):
        step = copy.deepcopy(raw_step)
        step.setdefault("type", "function_call")
        return step

    function = tool_call.get("function") or {}
    arguments = _parse_arguments(function.get("arguments"))
    step = {
        "type": "function_call",
        "name": function.get("name") or tool_call.get("name") or "",
        "arguments": arguments,
    }
    call_id = tool_call.get("id") or tool_call.get("tool_call_id")

    if call_id:
        step["id"] = call_id

    return step


def _function_result_step(message: Dict[str, Any], call_names: Dict[str, str]) -> Dict[str, Any]:
    """Translate a tool-result chat message into a function_result step."""
    call_id = message.get("tool_call_id") or ""
    name = message.get("name") or call_names.get(call_id, "")
    step: Dict[str, Any] = {
        "type": "function_result",
        "call_id": call_id,
        "name": name,
        "result": _result_content(message.get("content")),
    }

    if message.get("is_error"):
        step["is_error"] = True

    return step


def _user_content(content: Any) -> List[Dict[str, Any]]:
    """Translate OpenAI-style user content into Interactions Content blocks."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]

    if isinstance(content, list):
        blocks: List[Dict[str, Any]] = []

        for part in content:
            if not isinstance(part, dict):
                blocks.append({"type": "text", "text": json.dumps(part)})
                continue

            if part.get("type") == "text" and isinstance(part.get("text"), str):
                blocks.append({"type": "text", "text": part["text"]})
                continue

            if part.get("type") == "image_url":
                image_url = part.get("image_url")
                url = image_url.get("url") if isinstance(image_url, dict) else None
                parsed = split_data_url(url)

                if parsed:
                    mime, data = parsed
                    blocks.append({"type": "image", "mime_type": mime, "data": data})
                    continue

                if isinstance(url, str) and url.startswith(("http://", "https://")):
                    blocks.append({"type": "image", "uri": url})
                    continue

            blocks.append({"type": "text", "text": json.dumps(part)})

        return blocks or [{"type": "text", "text": ""}]

    if content is None:
        return [{"type": "text", "text": ""}]

    return [{"type": "text", "text": json.dumps(content)}]


def _result_content(content: Any) -> List[Dict[str, Any]]:
    """Normalize a tool result payload into Content blocks."""
    if isinstance(content, list):
        return content

    if isinstance(content, str):
        text = content
    elif content is None:
        text = ""
    else:
        text = json.dumps(content)

    return [{"type": "text", "text": text}]


def _call_names(messages: List[Dict[str, Any]]) -> Dict[str, str]:
    """Map assistant tool-call ids to function names for tool results."""
    names: Dict[str, str] = {}

    for message in messages:
        if message.get("role") != "assistant":
            continue

        for tool_call in message.get("tool_calls") or []:
            call_id = tool_call.get("id") or tool_call.get("tool_call_id")

            if not call_id:
                continue

            function = tool_call.get("function") or {}
            names[call_id] = function.get("name") or tool_call.get("name") or ""

    return names


def _thought_text(step: Dict[str, Any]) -> str:
    """Join the text blocks of a thought step's summary."""
    texts = [
        block.get("text") or ""
        for block in _content_blocks(step.get("summary"))
        if block.get("type") == "text" and block.get("text")
    ]
    return "\n".join(texts)


def _content_blocks(value: Any) -> List[Dict[str, Any]]:
    """Return a Content array, tolerating a single string or dict."""
    if isinstance(value, list):
        return [block for block in value if isinstance(block, dict)]

    if isinstance(value, dict):
        return [value]

    if isinstance(value, str):
        return [{"type": "text", "text": value}]

    return []


def _parse_arguments(value: Any) -> Dict[str, Any]:
    """Parse a tool-call argument payload (JSON string or dict)."""
    if isinstance(value, dict):
        return value

    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}

        return parsed if isinstance(parsed, dict) else {}

    return {}


def _map_status(status: Optional[str], saw_function_call: bool) -> Optional[str]:
    """Map an Interaction ``status`` to a normalized finish_reason."""
    if saw_function_call:
        return "tool_calls"

    if status is None:
        return None

    return _FINISH_BY_STATUS.get(status, status)


def _interactions_usage(usage_raw: Dict[str, Any]) -> Optional[Usage]:
    """Map Interactions usage fields onto :class:`Usage`.

    ``total_output_tokens`` excludes thinking tokens, so thought tokens are
    added to the completion total and surfaced as ``reasoning_tokens``.
    """
    if not usage_raw:
        return None

    output_tokens = usage_raw.get("total_output_tokens")
    thought_tokens = usage_raw.get("total_thought_tokens")
    completion_tokens = output_tokens

    if output_tokens is not None or thought_tokens is not None:
        completion_tokens = (output_tokens or 0) + (thought_tokens or 0)

    details: Dict[str, Any] = {}

    if thought_tokens is not None:
        details["reasoning_tokens"] = thought_tokens

    if usage_raw.get("total_tool_use_tokens") is not None:
        details["tool_use_tokens"] = usage_raw["total_tool_use_tokens"]

    return Usage(
        prompt_tokens=usage_raw.get("total_input_tokens"),
        completion_tokens=completion_tokens,
        total_tokens=usage_raw.get("total_tokens"),
        prompt_cache_hit_tokens=usage_raw.get("total_cached_tokens"),
        completion_tokens_details=details or None,
    )


def _gemini_version(route: str) -> tuple[int, int]:
    """Return the ``(major, minor)`` Gemini version encoded in a route."""
    match = re.search(r"gemini-(\d+)(?:\.(\d+))?", route or "")

    if not match:
        return 0, 0

    return int(match.group(1)), int(match.group(2) or 0)


def _level_from_budget(budget: Any) -> str:
    """Approximate a thinking budget as the nearest thinking_level."""
    if not isinstance(budget, (int, float)) or budget <= 0:
        return "low"

    if budget >= 32768:
        return "high"

    if budget >= 8192:
        return "medium"

    return "low"


def _consume_event(event: Dict[str, Any], state: Dict[str, Any]) -> Optional[CompletionChunk]:
    """Map one SSE event onto a chunk, updating accumulator state."""
    event_type = event.get("event_type") or event.get("type")

    if event_type == "step.start":
        return _start_step(event, state)

    if event_type == "step.delta":
        return _delta_step(event, state)

    if event_type == "step.stop":
        return _stop_step(event, state)

    if event_type == "interaction.completed":
        return _completed_event(event, state)

    if event_type == "error":
        error = event.get("error") or {}
        message = error.get("message") or "Interactions stream error"
        raise RuntimeError(message)

    return None


def _start_step(event: Dict[str, Any], state: Dict[str, Any]) -> Optional[CompletionChunk]:
    """Record a new step and emit any content present in ``step.start``."""
    index = event.get("index")
    step = copy.deepcopy(event.get("step") or {})
    index = index if isinstance(index, int) else len(state["order"])
    state["steps"][index] = step
    state["order"].append(index)
    initial = step.get("arguments")
    has_initial_arguments = isinstance(initial, dict) and bool(initial)
    state["arguments"][index] = json.dumps(initial) if has_initial_arguments else ""
    chunk = CompletionChunk()
    step_type = step.get("type")

    if step_type == "model_output":
        chunk.text = "".join(
            block.get("text") or ""
            for block in _content_blocks(step.get("content"))
            if block.get("type") == "text"
        )
    elif step_type == "thought":
        chunk.reasoning = _thought_text(step)
    elif step_type == "function_call":
        chunk.tool_calls = [_stream_call(step, index, "")]

    if not chunk.text and not chunk.reasoning and not chunk.tool_calls:
        return None

    return chunk


def _delta_step(event: Dict[str, Any], state: Dict[str, Any]) -> Optional[CompletionChunk]:
    """Accumulate one step delta and emit incremental text/reasoning/tool args."""
    index = event.get("index")
    index = index if isinstance(index, int) else 0
    delta = event.get("delta") or {}
    default_type = {
        "text": "model_output",
        "thought_summary": "thought",
        "thought_signature": "thought",
        "arguments_delta": "function_call",
    }.get(delta.get("type"), delta.get("type") or "unknown")
    step = state["steps"].setdefault(index, {"type": default_type})
    delta_type = delta.get("type")
    chunk = CompletionChunk()

    if delta_type == "text":
        text = delta.get("text") or ""
        _append_text_block(step, text)
        chunk.text = text
    elif delta_type == "thought_summary":
        content = delta.get("content") or {}
        step.setdefault("summary", []).extend(_content_blocks(content))
        chunk.reasoning = _thought_text({"summary": _content_blocks(content)})
    elif delta_type == "thought_signature":
        if delta.get("signature"):
            step["signature"] = delta["signature"]
    elif delta_type == "arguments_delta":
        fragment = delta.get("arguments") or ""
        state["arguments"][index] = state["arguments"].get(index, "") + fragment
        chunk.tool_calls = [_stream_call(step, index, fragment)]
    else:
        _merge_opaque_delta(step, delta)

    if delta.get("signature") and "signature" not in step:
        step["signature"] = delta["signature"]

    if (
        not chunk.text
        and not chunk.reasoning
        and not chunk.tool_calls
        and not chunk.provider_specific_fields
    ):
        return None

    return chunk


def _stop_step(event: Dict[str, Any], state: Dict[str, Any]) -> Optional[CompletionChunk]:
    """Finalize a step, emitting the verbatim replayable step for the next turn."""
    index = event.get("index")
    index = index if isinstance(index, int) else 0
    step = state["steps"].get(index) or {}

    if step.get("type") == "function_call":
        step["arguments"] = _parse_arguments(state["arguments"].get(index) or "{}")

    chunk = CompletionChunk(provider_specific_fields={STEPS_KEY: [copy.deepcopy(step)]})

    if step.get("type") == "function_call":
        chunk.finish_reason = "tool_calls"

    return chunk


def _completed_event(event: Dict[str, Any], state: Dict[str, Any]) -> Optional[CompletionChunk]:
    """Emit final usage and finish reason from ``interaction.completed``."""
    interaction = event.get("interaction") or {}
    saw_function_call = any(step.get("type") == "function_call" for step in state["steps"].values())
    chunk = CompletionChunk(
        usage=_interactions_usage(interaction.get("usage") or {}),
        finish_reason=_map_status(interaction.get("status"), saw_function_call),
    )

    if interaction.get("id"):
        chunk.provider_specific_fields["interactions_id"] = interaction["id"]

    if not chunk.usage and not chunk.finish_reason and not chunk.provider_specific_fields:
        return None

    return chunk


def _stream_call(step: Dict[str, Any], index: int, fragment: str) -> ToolCall:
    """Build a streaming tool-call fragment for the litellm shim accumulator."""
    return ToolCall(
        id=step.get("id") or "",
        name=step.get("name") or "",
        arguments={"_fragment": fragment, "_index": index},
        index=index,
    )


def _append_text_block(step: Dict[str, Any], text: str) -> None:
    """Append streamed text to a model_output step's content array."""
    blocks = step.setdefault("content", [])

    if blocks and blocks[-1].get("type") == "text":
        blocks[-1]["text"] = (blocks[-1].get("text") or "") + text
    else:
        blocks.append({"type": "text", "text": text})


def _merge_opaque_delta(step: Dict[str, Any], delta: Dict[str, Any]) -> None:
    """Preserve non-text deltas (built-in tools) on the replayable step."""
    for key, value in delta.items():
        if key == "type":
            continue

        if key == "arguments" and isinstance(value, str):
            current = step.get(key) or ""
            step[key] = f"{current}{value}"
        elif key in ("arguments", "result", "signature", "id", "call_id") or key not in step:
            step[key] = copy.deepcopy(value)


__all__ = [
    "interactions_payload",
    "interactions_input",
    "interactions_tool",
    "interactions_thinking_level",
    "interactions_complete",
    "interactions_stream",
    "normalize_interactions_response",
]
