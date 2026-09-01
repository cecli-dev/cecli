"""Model identifier helpers for the model config pipeline.

These predicates classify a model by family/provider from its name prefix,
route, and metadata record.  Centralizing them keeps the config modules
(api.py, llm.py, agent.py) and formatters free of repeated provider matching.
"""

from __future__ import annotations

import re


def _haystack(provider, route, record):
    """Lowercased, space-joined provider/route/record-provider for matching."""
    provider = (provider or "").lower()
    route = (route or "").lower()
    record_provider = ((record or {}).get("litellm_provider") or "").lower()
    return " ".join([provider, route, record_provider])


def is_anthropic(provider, route, record):
    """True when the model is an Anthropic-family model (Claude)."""
    haystack = _haystack(provider, route, record)
    return "anthropic" in haystack or "claude" in (route or "").lower()


def is_gemini(provider, route, record):
    """True when the model is a Gemini-series model."""
    return "gemini" in _haystack(provider, route, record)


def is_gemini_2_5(provider, route, record):
    """True when the model is a Gemini 2.5-series model."""
    return "gemini-2.5" in (route or "").lower()


def is_claude_5_plus(provider, route, record):
    """True for Claude 5+ models, which use adaptive thinking + output_config.

    Claude 5+ does not accept ``thinking.type.enabled``; thinking is controlled
    via ``thinking.type.adaptive`` and ``output_config.effort`` (which litellm
    derives from a top-level ``reasoning_effort`` param).
    """
    route = (route or "").lower()
    match = re.search(r"claude[^\d]*(\d+)", route)

    if not match:
        return False

    return int(match.group(1)) >= 5


def is_github_copilot(provider, route, record):
    """True when the model is served through GitHub Copilot."""
    provider = (provider or "").lower()
    record_provider = ((record or {}).get("litellm_provider") or "").lower()
    return provider == "github_copilot" or record_provider == "github_copilot"


def is_meta(provider, route, record):
    """True when the model is a Meta-provider model."""
    provider = (provider or "").lower()
    record_provider = ((record or {}).get("litellm_provider") or "").lower()
    return provider == "meta" or record_provider == "meta"


def gpt_version(route):
    """Return the leading ``gpt-`` model version, or 0 when not a gpt model.

    e.g. ``gpt-5.6-luna`` -> 5.6, ``gpt-5`` -> 5, ``claude-3`` -> 0.
    """
    match = re.match(r"^gpt-(\d+(?:\.\d+)?)", (route or "").lower())

    if not match:
        return 0

    return float(match.group(1))
