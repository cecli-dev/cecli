"""Sectional reasoning formatters for the llms package.

Mirrors ``cecli/helpers/model_config/formatters/reasoning.py``: a
:func:`format_reasoning` dispatcher selects the per-provider reasoning
extractor for a model. The extractors post-process a normalized message /
response dict to pull reasoning out of the provider-specific shapes.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from ..identifiers import is_anthropic, is_gemini, is_meta, is_openrouter
from ..utils import extract_reasoning


def format_reasoning(provider: Optional[str], route: str, record: Optional[Dict]) -> Callable:
    """Return the reasoning extractor for a model (default: generic)."""
    if is_gemini(provider, route, record):
        return gemini_reasoning

    if is_anthropic(provider, route, record):
        return anthropic_reasoning

    if is_meta(provider, route, record):
        return meta_reasoning

    if is_openrouter(provider, route, record):
        return openrouter_reasoning

    return generic_reasoning


def generic_reasoning(msg: Dict[str, Any]) -> str:
    """Generic extraction: reasoning_content / reasoning / reasoning_details."""
    return extract_reasoning(msg)


def openrouter_reasoning(msg: Dict[str, Any]) -> str:
    """OpenRouter puts reasoning in ``reasoning`` + ``reasoning_details``.

    The generic extractor already handles those shapes; kept as a named
    provider hook so future OpenRouter-specific shapes can be added here.
    """
    return extract_reasoning(msg)


def anthropic_reasoning(block: Dict[str, Any]) -> str:
    """Anthropic thinking blocks: text, or a signature-bearing encrypted block."""
    if block.get("type") != "thinking":
        return ""

    thinking_text = block.get("thinking") or ""

    if thinking_text.strip():
        return thinking_text

    if block.get("signature"):
        return "[encrypted thinking block present]"

    return ""


def gemini_reasoning(part: Dict[str, Any]) -> str:
    """Gemini ``thought`` parts carry the reasoning text."""
    if part.get("thought") and "text" in part:
        return part["text"]

    return ""


def meta_reasoning(item: Dict[str, Any]) -> str:
    """Meta responses-mode reasoning: encrypted_content is opaque.

    Returns the placeholder marker when only an encrypted blob is present so
    callers can tell reasoning happened (usage shows reasoning_tokens).
    """
    if item.get("encrypted_content"):
        return "[encrypted reasoning present]"

    return ""


__all__ = [
    "format_reasoning",
    "generic_reasoning",
    "openrouter_reasoning",
    "anthropic_reasoning",
    "gemini_reasoning",
    "meta_reasoning",
]
