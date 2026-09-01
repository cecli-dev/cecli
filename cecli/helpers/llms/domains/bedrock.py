"""AWS Bedrock Converse API adapter (non-streaming).

Converse is Bedrock's provider-neutral chat wire: OpenAI-style messages are
transformed to the Converse ``messages``/``system``/``inferenceConfig``/
``toolConfig`` shape, and the request is authenticated with AWS Signature V4
(see :mod:`cecli.helpers.llms.aws_sigv4`). The response is normalized back to
:class:`~cecli.helpers.llms.types.CompletionResponse`.

Streaming (``/model/{id}/converse-stream``) uses AWS's binary event-stream
encoding, which is not implemented yet; the provider entry sets
``supports_stream: false`` and :func:`bedrock_stream` raises a clear error.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional

from ..aws_sigv4 import AWSCredentials, resolve_aws_region, sign_request
from ..runtime import VERIFY_SSL, make_client
from ..types import (
    Choice,
    CompletionChunk,
    CompletionResponse,
    PartsMessage,
    TextPart,
    ToolCallPart,
    Usage,
    parts_message_to_message,
)

DEFAULT_TIMEOUT = 120.0

#: Converse ``stopReason`` -> OpenAI finish_reason mapping.
_STOP_REASON_MAP = {
    "end_turn": "stop",
    "tool_use": "tool_calls",
    "max_tokens": "length",
    "guardrail_intervened": "content_filter",
}


def bedrock_payload(
    resolved: Dict[str, Any],
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    kwargs: Dict[str, Any],
) -> Dict[str, Any]:
    """Transform OpenAI-style messages into a Bedrock Converse request body."""
    payload: Dict[str, Any] = {}

    system_blocks: List[Dict[str, Any]] = []
    converse_messages: List[Dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role")

        if role == "system":
            text = msg.get("content")
            if text:
                system_blocks.append({"text": text})
            continue

        if role == "tool":
            converse_messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "toolResult": {
                                "toolUseId": msg.get("tool_call_id", ""),
                                "content": [{"text": msg.get("content") or ""}],
                                "status": "success",
                            }
                        }
                    ],
                }
            )
            continue

        if role == "assistant":
            blocks: List[Dict[str, Any]] = []
            content = msg.get("content") or ""
            if content:
                blocks.append({"text": content})

            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") or {}
                args_raw = fn.get("arguments") or "{}"

                try:
                    args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                except json.JSONDecodeError:
                    args = {}

                blocks.append(
                    {
                        "toolUse": {
                            "toolUseId": tc.get("id", ""),
                            "name": fn.get("name", ""),
                            "input": args,
                        }
                    }
                )

            converse_messages.append({"role": "assistant", "content": blocks})
            continue

        # user
        blocks = _user_content_blocks(msg)
        converse_messages.append({"role": "user", "content": blocks})

    if system_blocks:
        payload["system"] = system_blocks

    payload["messages"] = converse_messages

    inference: Dict[str, Any] = {}

    max_tokens = kwargs.get("max_tokens")
    if max_tokens:
        inference["maxTokens"] = max_tokens

    temperature = kwargs.get("temperature")
    if temperature is not None:
        inference["temperature"] = temperature

    top_p = kwargs.get("top_p")
    if top_p is not None:
        inference["topP"] = top_p

    stop = kwargs.get("stop") or kwargs.get("stop_sequences")
    if stop:
        inference["stopSequences"] = stop if isinstance(stop, list) else [stop]

    if inference:
        payload["inferenceConfig"] = inference

    if tools:
        specs = []
        for tool in tools:
            fn = tool.get("function") or {}
            spec: Dict[str, Any] = {"name": fn.get("name", "")}
            if fn.get("description"):
                spec["description"] = fn["description"]
            if fn.get("parameters"):
                spec["inputSchema"] = fn["parameters"]
            specs.append({"toolSpec": spec})

        tool_config: Dict[str, Any] = {"tools": specs}

        tool_choice = kwargs.get("tool_choice")
        if tool_choice in ("none", "auto", "any"):
            tool_config["toolChoice"] = {"type": tool_choice}

        payload["toolConfig"] = tool_config

    extra_body = dict(resolved.get("extra_body") or {})
    extra_body.update(kwargs.get("extra_body") or {})
    payload.update(extra_body)
    return payload


def _user_content_blocks(msg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert a user message's content (str or OpenAI part list) to Converse text blocks."""
    content = msg.get("content")
    blocks: List[Dict[str, Any]] = []

    if isinstance(content, str):
        if content:
            blocks.append({"text": content})

    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                blocks.append({"text": block["text"]})

    return blocks


def bedrock_region(resolved: Dict[str, Any]) -> Optional[str]:
    """Resolve the AWS region for the request (explicit override, then env)."""
    return resolved.get("aws_region") or resolve_aws_region()


def bedrock_endpoint(resolved: Dict[str, Any]) -> str:
    """Return the Converse endpoint URL for the resolved model."""
    region = bedrock_region(resolved)

    if not region:
        raise ValueError(
            "Bedrock requires an AWS region: set AWS_REGION_NAME or AWS_REGION "
            "(or pass aws_region in the provider config)."
        )

    route = resolved["route"]
    return f"https://bedrock-runtime.{region}.amazonaws.com/model/{route}/converse"


def _signed_headers(
    resolved: Dict[str, Any], url: str, body: bytes, headers: Dict[str, str]
) -> Dict[str, str]:
    """Sign the Converse request with AWS SigV4."""
    creds = AWSCredentials.from_env()

    if creds is None:
        raise ValueError(
            "Bedrock requires AWS credentials: set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY "
            "(AWS_SESSION_TOKEN when using temporary credentials)."
        )

    region = bedrock_region(resolved)
    hdrs = {"Content-Type": "application/json", **headers}
    return sign_request("POST", url, body, creds, region, "bedrock", headers=hdrs)


async def bedrock_complete(
    resolved: Dict[str, Any],
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    key: Optional[str],
    headers: Dict[str, str],
    kwargs: Dict[str, Any],
) -> CompletionResponse:
    """Send a non-streaming Bedrock Converse completion."""
    url = bedrock_endpoint(resolved)
    payload = bedrock_payload(resolved, messages, tools, kwargs)
    body = json.dumps(payload)

    hdrs = _signed_headers(resolved, url, body.encode("utf-8"), headers)

    async with make_client(timeout=DEFAULT_TIMEOUT, verify=VERIFY_SSL) as client:
        resp = await client.post(url, content=body.encode("utf-8"), headers=hdrs)
        resp.raise_for_status()
        data = resp.json()

    return normalize_bedrock_response(data, resolved["model"])


async def bedrock_stream(
    resolved: Dict[str, Any],
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    key: Optional[str],
    headers: Dict[str, str],
    kwargs: Dict[str, Any],
) -> AsyncIterator[CompletionChunk]:
    """Streaming is not implemented for Bedrock Converse yet."""
    raise NotImplementedError(
        "Bedrock Converse streaming requires AWS event-stream decoding and is not supported yet. "
        "Use a non-streaming request (the bedrock provider sets supports_stream: false)."
    )


def normalize_bedrock_response(data: Dict[str, Any], model: str) -> CompletionResponse:
    """Normalize a Converse response body to a CompletionResponse."""
    output = data.get("output") or {}
    message = output.get("message") or {}
    content = message.get("content") or []

    parts = []

    for block in content:
        if block.get("text"):
            parts.append(TextPart(text=block["text"]))
        elif block.get("toolUse"):
            tool_use = block["toolUse"]
            parts.append(
                ToolCallPart(
                    name=tool_use.get("name", ""),
                    arguments=tool_use.get("input") or {},
                    tool_call_id=tool_use.get("toolUseId"),
                )
            )

    stop_reason = data.get("stopReason")
    finish_reason = _STOP_REASON_MAP.get(stop_reason)

    usage_raw = data.get("usage") or {}
    usage = Usage(
        prompt_tokens=usage_raw.get("inputTokens"),
        completion_tokens=usage_raw.get("outputTokens"),
        total_tokens=usage_raw.get("totalTokens"),
    )

    pm = PartsMessage(role="assistant", parts=parts)
    choices = [Choice(index=0, message=parts_message_to_message(pm), finish_reason=finish_reason)]

    provider_fields: Dict[str, Any] = {}
    if stop_reason:
        provider_fields["stop_reason"] = stop_reason

    return CompletionResponse(
        id=None,
        model=model,
        choices=choices,
        usage=usage or None,
        provider_specific_fields=provider_fields,
    )


__all__ = [
    "bedrock_complete",
    "bedrock_payload",
    "bedrock_stream",
    "normalize_bedrock_response",
]
