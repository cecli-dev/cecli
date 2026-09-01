"""Thinking formatters for the model config pipeline.

These helpers rewrite the generic thinking shape onto the params litellm
understands for a provider.  ``extra_params`` are the kwargs passed to
``litellm.acompletion``, so a formatter exposes thinking as a top-level litellm
param and lets litellm map it onto the provider's own field.  For example:

- Gemini uses ``thinkingConfig`` under the hood: litellm maps a top-level
  anthropic-style ``thinking`` param to ``thinkingBudget`` (Gemini 2.5) or
  ``thinkingLevel`` (Gemini 3) and sets ``includeThoughts``.
- Anthropic consumes the top-level ``thinking`` kwarg directly; riding inside
  ``extra_body`` makes the API reject it as extra inputs.

``set_thinking_tokens`` in :mod:`cecli.models` invokes the formatter chosen by
the pipeline (``helpers.format_thinking``) after it has applied the generic
shape.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from ..identifiers import is_anthropic, is_claude_5_plus, is_gemini


def format_thinking(provider: Optional[str], route: str, record: Optional[Dict]) -> Callable:
    """Return the thinking formatter for a model.

    Args:
        provider: Provider portion of the model name (may be ``None``).
        route: Model route (name after the provider prefix).
        record: The matched model metadata record, or ``None`` for unknown models.

    Returns:
        A callable that mutates ``extra_params`` in place.  Unknown models get
        a noop so ``set_thinking_tokens`` keeps its default behavior.
    """
    if is_gemini(provider, route, record):
        return gemini_thinking

    if is_anthropic(provider, route, record):
        if is_claude_5_plus(provider, route, record):
            # Claude 5+ cannot use thinking.type.enabled; remove it entirely.
            return anthropic_5_thinking

        return anthropic_thinking

    return noop


def noop(extra_params: Dict) -> Dict:
    """Default formatter: leave ``extra_params`` untouched."""
    return extra_params


def gemini_thinking(extra_params: Dict) -> Dict:
    """Gemini models configure thinking via litellm's ``thinking`` kwarg.

    litellm maps the top-level anthropic-style ``thinking`` param onto
    Gemini's ``thinkingConfig`` (``thinkingBudget`` for Gemini 2.5,
    ``thinkingLevel`` for Gemini 3) and sets ``includeThoughts``, so the
    generic shape is lifted out of ``extra_body``.
    """
    return _lift_thinking(extra_params)


def anthropic_thinking(extra_params: Dict) -> Dict:
    """Anthropic (pre-5) models consume the top-level ``thinking`` kwarg.

    litellm maps the top-level anthropic-style ``thinking`` param into the
    request body, so it must not ride inside ``extra_body`` (which the
    Anthropic API rejects as extra inputs).
    """
    params = _lift_thinking(extra_params)
    params.pop("extra_body", None)
    return params


def anthropic_5_thinking(extra_params: Dict) -> Dict:
    """Claude 5+ models cannot use ``thinking.type.enabled``.

    Thinking is instead controlled via ``reasoning_effort`` (which litellm maps
    to ``thinking.type.adaptive`` + ``output_config.effort``), so any thinking
    block is removed entirely and ``extra_body`` is dropped.
    """
    extra_params.pop("thinking", None)
    extra_body = extra_params.get("extra_body")

    if isinstance(extra_body, dict):
        extra_body.pop("thinking", None)

    extra_params.pop("extra_body", None)
    return extra_params


def _lift_thinking(extra_params: Dict) -> Dict:
    """Move the generic ``thinking`` shape out of ``extra_body`` to top level."""
    extra_body = extra_params.get("extra_body")

    if not isinstance(extra_body, dict):
        return extra_params

    thinking = extra_body.pop("thinking", None)

    if thinking is not None:
        extra_params["thinking"] = thinking

    return extra_params
