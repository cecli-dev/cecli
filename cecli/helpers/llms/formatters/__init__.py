"""Sectional per-domain formatters for the llms package.

Mirrors ``cecli/helpers/model_config/formatters/``: each module is a
cross-cutting concern (reasoning, thinking) exporting provider-specific
functions plus a ``format_*`` dispatcher selected by provider/route/record.
"""

from __future__ import annotations

from .reasoning import (
    anthropic_reasoning,
    format_reasoning,
    gemini_reasoning,
    generic_reasoning,
    meta_reasoning,
    openrouter_reasoning,
)
from .thinking import (
    anthropic_5_thinking,
    anthropic_thinking,
    format_thinking,
    gemini_thinking,
    noop,
)

__all__ = [
    "format_reasoning",
    "generic_reasoning",
    "openrouter_reasoning",
    "anthropic_reasoning",
    "gemini_reasoning",
    "meta_reasoning",
    "format_thinking",
    "noop",
    "gemini_thinking",
    "anthropic_5_thinking",
    "anthropic_thinking",
]
