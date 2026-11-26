"""Groq provider adapter for the llms package.

Groq speaks OpenAI-compatible /v1/chat/completions with Bearer auth, but its
endpoint validates the request body strictly and rejects unknown properties.
Groq has no prompt-cache key parameter, so this adapter strips the
``prompt_cache_key`` the shared chat payload builder would otherwise forward.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import ProviderAdapter


class GroqProvider(ProviderAdapter):
    """Groq: Bearer auth + strict chat body without ``prompt_cache_key``."""

    provider: str = "groq"

    def chat_payload(
        self,
        resolved: Dict[str, Any],
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        stream: bool,
        kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build the chat body without the unsupported ``prompt_cache_key``."""
        payload = super().chat_payload(resolved, messages, tools, stream, kwargs)

        payload.pop("prompt_cache_key", None)

        return payload


__all__ = ["GroqProvider"]
