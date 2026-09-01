"""OpenRouter provider adapter for the llms package.

OpenRouter speaks OpenAI-compatible /v1/chat/completions with Bearer auth, so
the base adapter's defaults apply. Reasoning arrives via ``message.reasoning``
/ ``message.reasoning_details`` (not ``reasoning_content``); the generic
:func:`cecli.helpers.llms.utils.extract_reasoning` already handles all three
shapes, so no normalize override is needed here.
"""

from __future__ import annotations

from .base import ProviderAdapter


class OpenRouterProvider(ProviderAdapter):
    """OpenRouter: Bearer auth + generic reasoning extraction."""

    provider: str = "openrouter"


__all__ = ["OpenRouterProvider"]
