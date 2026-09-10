"""Mistral provider adapter for the llms package.

Mistral speaks OpenAI-compatible /v1/chat/completions with Bearer auth, but its
request body is validated by a strict Pydantic schema that rejects fields the
generic OpenAI-compatible wire tolerates. Assistant turns built by cecli carry
``reasoning_content`` and ``provider_specific_fields`` on the message, a null
``function_call`` left behind by the legacy wire, and ``provider_specific_fields``
plus a null ``index`` on tool calls (a streaming artifact); Mistral rejects
each of these with a 422 on the relevant ``messages[i]`` path.

This adapter iterates over the message body before dispatch and strips those
fields, leaving tool calls in the request wire shape (``id`` / ``type`` /
``function``).

On the response side Mistral streams ``content`` as a list of typed parts
(``thinking`` / ``text``); :meth:`normalize` flattens those into the generic
``text`` / ``reasoning`` fields so the shared chat parser stays provider-agnostic.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..types import CompletionChunk, CompletionResponse
from .base import ProviderAdapter


class MistralProvider(ProviderAdapter):
    """Mistral: Bearer auth (default) + strict message-body sanitization."""

    provider: str = "mistral"

    #: Mistral rejects ``reasoning_content`` on assistant turns (see
    #: :meth:`transform_messages`), so the chat payload must not inject it.
    echoes_reasoning_content: bool = False

    def transform_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Strip fields Mistral's strict chat-completions schema rejects."""
        changed = False
        out: List[Dict[str, Any]] = []

        for msg in messages:
            cleaned = self._clean_message(msg)

            if cleaned is not None:
                out.append(cleaned)
                changed = True
            else:
                out.append(msg)

        return out if changed else messages

    def normalize(self, family: str, data: Any, resolved: Dict[str, Any]) -> Any:
        """Flatten Mistral's typed content parts into the generic shape.

        Mistral streams ``content`` as a list of typed parts, carrying reasoning
        in ``{"type": "thinking", "thinking": [...]}`` blocks alongside
        ``{"type": "text", ...}`` ones. The generic OpenAI-compatible parser
        treats that list as opaque text, which then crashes consumers that
        concatenate it as a string. Move thinking parts onto ``reasoning``
        (stream) / ``reasoning_content`` and join text parts into plain text.
        """
        if family != "chat":
            return data

        if isinstance(data, CompletionChunk):
            return self._normalize_chunk(data)

        if isinstance(data, CompletionResponse):
            return self._normalize_response(data)

        return data

    def _clean_message(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return a sanitized copy of ``msg``, or ``None`` when unchanged."""
        tool_calls = msg.get("tool_calls")
        needs_tool_fix = any(
            isinstance(tc, dict) and ("index" in tc or "provider_specific_fields" in tc)
            for tc in tool_calls or []
        )

        if (
            "reasoning_content" not in msg
            and "provider_specific_fields" not in msg
            and "function_call" not in msg
            and not needs_tool_fix
        ):
            return None

        cleaned = dict(msg)
        cleaned.pop("reasoning_content", None)
        cleaned.pop("provider_specific_fields", None)
        cleaned.pop("function_call", None)

        if tool_calls:
            cleaned["tool_calls"] = [self._clean_tool_call(tc) for tc in tool_calls]

        return cleaned

    def _clean_tool_call(self, tc: Any) -> Any:
        """Drop streaming-only fields from a tool call."""
        if not isinstance(tc, dict):
            return tc

        cleaned = dict(tc)
        cleaned.pop("index", None)
        cleaned.pop("provider_specific_fields", None)
        return cleaned

    def _normalize_chunk(self, chunk: CompletionChunk) -> CompletionChunk:
        """Flatten a streamed chunk's typed ``content`` parts."""
        text, reasoning = self._split_content(chunk.text)
        chunk.text = text

        if reasoning:
            chunk.reasoning = (chunk.reasoning or "") + reasoning

        return chunk

    def _normalize_response(self, response: CompletionResponse) -> CompletionResponse:
        """Flatten typed ``content`` parts on each choice's message."""
        for choice in response.choices:
            message = choice.message
            content = message.content

            if isinstance(content, list):
                text, reasoning = self._split_content(content)
                message.content = text or None

                if reasoning:
                    message.reasoning_content = (message.reasoning_content or "") + reasoning

            if isinstance(message.reasoning_content, list):
                text, reasoning = self._split_content(message.reasoning_content)
                message.reasoning_content = text or reasoning

        return response

    def _split_content(self, content: Any) -> Tuple[str, str]:
        """Split a Mistral ``content`` value into ``(text, reasoning)``."""
        if isinstance(content, str):
            return content, ""

        if not isinstance(content, list):
            return "", ""

        texts: List[str] = []
        reasonings: List[str] = []

        for part in content:
            if not isinstance(part, dict):
                continue

            part_type = part.get("type")

            if part_type == "thinking":
                reasonings.append(self._flatten_thinking(part.get("thinking")))
            elif part_type == "text":
                text = part.get("text")

                if isinstance(text, str):
                    texts.append(text)

        return "".join(texts), "".join(reasonings)

    def _flatten_thinking(self, thinking: Any) -> str:
        """Join a thinking block (a string or a list of text parts)."""
        if isinstance(thinking, str):
            return thinking

        if not isinstance(thinking, list):
            return ""

        return "".join(item.get("text") or "" for item in thinking if isinstance(item, dict))


__all__ = ["MistralProvider"]
