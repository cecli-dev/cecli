"""Anthropic provider adapter for the llms package.

The Anthropic /v1/messages family adapter (:mod:`...domains.messages`) already
sets ``x-api-key`` + ``anthropic-version`` internally, so this adapter needs no
header overrides for the standard Anthropic path. The github_copilot provider
(same family, Bearer auth + messages-proxy headers) has its own adapter.
"""

from __future__ import annotations

from .base import ProviderAdapter


class AnthropicProvider(ProviderAdapter):
    """Anthropic: auth handled by the messages domain; registration only."""

    provider: str = "anthropic"


__all__ = ["AnthropicProvider"]
