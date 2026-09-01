"""Sectional thinking-config formatters for the llms package.

Mirrors ``cecli/helpers/model_config/formatters/thinking.py``: a
:func:`format_thinking` dispatcher selects the per-provider thinking
configuration builder, mapping the generic reasoning-effort/thinking shape
onto the provider's request field (Gemini thinkingConfig, Anthropic
output_config / thinking block, chat reasoning_effort).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from ..identifiers import is_anthropic, is_claude_5_plus, is_gemini


def format_thinking(provider: Optional[str], route: str, record: Optional[Dict]) -> Callable:
    """Return the thinking-config builder for a model (default: noop)."""
    if is_gemini(provider, route, record):
        return gemini_thinking

    if is_anthropic(provider, route, record) and is_claude_5_plus(provider, route, record):
        return anthropic_5_thinking

    if is_anthropic(provider, route, record):
        return anthropic_thinking

    return noop


def noop(payload: Dict[str, Any], api_block: Dict[str, Any]) -> Dict[str, Any]:
    """Default: leave the payload untouched."""
    return payload


def gemini_thinking(payload: Dict[str, Any], api_block: Dict[str, Any]) -> Dict[str, Any]:
    """Gemini: map reasoning_effort/thinking onto ``generationConfig.thinkingConfig``."""
    from ..domains.gemini import gemini_thinking_config

    gen_config = payload.setdefault("generationConfig", {})

    if api_block.get("reasoning_effort"):
        gen_config["thinkingConfig"] = gemini_thinking_config(
            {"route": payload.get("model", "")}, api_block["reasoning_effort"]
        )
    elif api_block.get("thinking"):
        gen_config["thinkingConfig"] = {
            "thinkingBudget": api_block["thinking"].get("budget_tokens", 8192)
        }

    return payload


def anthropic_5_thinking(payload: Dict[str, Any], api_block: Dict[str, Any]) -> Dict[str, Any]:
    """Claude 5+: adaptive thinking via ``output_config.effort``."""
    if api_block.get("reasoning_effort"):
        payload["output_config"] = {"effort": api_block["reasoning_effort"]}

    return payload


def anthropic_thinking(payload: Dict[str, Any], api_block: Dict[str, Any]) -> Dict[str, Any]:
    """Pre-Claude-5: the ``thinking`` block (type enabled + budget)."""
    if api_block.get("thinking"):
        payload["thinking"] = api_block["thinking"]

    return payload


__all__ = [
    "format_thinking",
    "noop",
    "gemini_thinking",
    "anthropic_5_thinking",
    "anthropic_thinking",
]
