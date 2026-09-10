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
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import ProviderAdapter


class MistralProvider(ProviderAdapter):
    """Mistral: Bearer auth (default) + strict message-body sanitization."""

    provider: str = "mistral"

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


__all__ = ["MistralProvider"]
