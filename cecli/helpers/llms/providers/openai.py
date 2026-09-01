"""OpenAI provider adapter for the llms package.

OpenAI-compatible endpoints (/v1/chat/completions, /v1/responses) use the base
adapter's defaults: ``Authorization: Bearer`` + JSON content-type. This module
exists to document the drop-in extension point and to register the ``openai``
slug in the provider registry.
"""

from __future__ import annotations

from .base import ProviderAdapter


class OpenAIProvider(ProviderAdapter):
    """OpenAI: default Bearer auth; no overrides needed."""

    provider: str = "openai"


__all__ = ["OpenAIProvider"]
