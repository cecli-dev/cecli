"""DeepSeek provider adapter for the llms package.

DeepSeek speaks OpenAI-compatible /v1/chat/completions with Bearer auth and
returns reasoning via ``delta.reasoning_content`` (also ``reasoning_content`` on
non-streamed choices). The generic :func:`cecli.helpers.llms.utils.extract_reasoning`
already handles that shape, so no overrides are needed here.
"""

from __future__ import annotations

from .base import ProviderAdapter


class DeepSeekProvider(ProviderAdapter):
    """DeepSeek: Bearer auth + reasoning_content extraction."""

    provider: str = "deepseek"


__all__ = ["DeepSeekProvider"]
