"""Provider / API-family identifier helpers for the llms package.

These predicates classify a model by provider and route from its name and the
resolved config, mirroring ``cecli/helpers/model_config/identifiers.py``.
Centralizing them keeps the domain adapters and provider adapters free of
repeated provider matching.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional


def _haystack(provider: Optional[str], route: str, record: Optional[Dict[str, Any]]) -> str:
    """Lowercased, space-joined provider/route/record-provider for matching."""
    provider = (provider or "").lower()
    route = (route or "").lower()
    record_provider = ((record or {}).get("litellm_provider") or "").lower()
    return " ".join([provider, route, record_provider])


def is_anthropic(provider: Optional[str], route: str, record: Optional[Dict[str, Any]]) -> bool:
    """True when the model is an Anthropic-family model (Claude)."""
    haystack = _haystack(provider, route, record)
    return "anthropic" in haystack or "claude" in (route or "").lower()


def is_gemini(provider: Optional[str], route: str, record: Optional[Dict[str, Any]]) -> bool:
    """True when the model is a Gemini-series model."""
    return "gemini" in _haystack(provider, route, record)


def is_github_copilot(
    provider: Optional[str], route: str, record: Optional[Dict[str, Any]]
) -> bool:
    """True when the model is served through GitHub Copilot."""
    provider = (provider or "").lower()
    record_provider = ((record or {}).get("litellm_provider") or "").lower()
    return provider == "github_copilot" or record_provider == "github_copilot"


def is_meta(provider: Optional[str], route: str, record: Optional[Dict[str, Any]]) -> bool:
    """True when the model is a Meta-provider model."""
    provider = (provider or "").lower()
    record_provider = ((record or {}).get("litellm_provider") or "").lower()
    return provider == "meta" or record_provider == "meta"


def is_openrouter(provider: Optional[str], route: str, record: Optional[Dict[str, Any]]) -> bool:
    """True when the model is served through OpenRouter."""
    provider = (provider or "").lower()
    record_provider = ((record or {}).get("litellm_provider") or "").lower()
    return provider == "openrouter" or record_provider == "openrouter"


def is_claude_5_plus(provider: Optional[str], route: str, record: Optional[Dict[str, Any]]) -> bool:
    """True for Claude 5+ models, which use adaptive thinking + output_config.

    Claude 5+ does not accept ``thinking.type.enabled``; thinking is controlled
    via ``thinking.type.adaptive`` and ``output_config.effort``.
    """
    route = (route or "").lower()
    match = re.search(r"claude[^\d]*(\d+)", route)

    if not match:
        return False

    return int(match.group(1)) >= 5


def gpt_version(route: str) -> float:
    """Return the leading ``gpt-`` model version, or 0 when not a gpt model.

    e.g. ``gpt-5.6-luna`` -> 5.6, ``gpt-5`` -> 5, ``claude-3`` -> 0.
    """
    match = re.match(r"^gpt-(\d+(?:\.\d+)?)", (route or "").lower())

    if not match:
        return 0

    return float(match.group(1))


__all__ = [
    "is_anthropic",
    "is_gemini",
    "is_github_copilot",
    "is_meta",
    "is_openrouter",
    "is_claude_5_plus",
    "gpt_version",
]
