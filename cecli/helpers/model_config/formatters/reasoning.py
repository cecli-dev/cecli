"""Reasoning formatters for the model config pipeline.

These helpers rewrite the generic reasoning effort shape onto the params
litellm understands for a provider.  ``extra_params`` are the kwargs passed to
``litellm.acompletion``, so a formatter exposes the effort as a top-level
litellm param and lets litellm map it onto the provider's own field.  For
example, Gemini uses ``thinkingConfig`` under the hood: litellm maps a
top-level ``reasoning_effort`` to ``thinkingLevel`` (Gemini 3) or
``thinkingBudget`` (Gemini 2.5).  ``set_reasoning_effort`` in
:mod:`cecli.models` invokes the formatter chosen by the pipeline
(``helpers.format_reasoning``) after it has applied the generic shape.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from ..identifiers import is_claude_5_plus, is_gemini


def format_reasoning(provider: Optional[str], route: str, record: Optional[Dict]) -> Callable:
    """Return the reasoning formatter for a model.

    Args:
        provider: Provider portion of the model name (may be ``None``).
        route: Model route (name after the provider prefix).
        record: The matched model metadata record, or ``None`` for unknown models.

    Returns:
        A callable that mutates ``extra_params`` in place.  Unknown models get
        a noop so ``set_reasoning_effort`` keeps its default behavior.
    """
    if is_gemini(provider, route, record):
        return gemini_reasoning

    if is_claude_5_plus(provider, route, record):
        return anthropic_reasoning

    return noop


def noop(extra_params: Dict) -> Dict:
    """Default formatter: leave ``extra_params`` untouched."""
    return extra_params


def gemini_reasoning(extra_params: Dict) -> Dict:
    """Gemini models configure thinking via litellm's ``reasoning_effort``.

    litellm maps the top-level ``reasoning_effort`` kwarg onto Gemini's
    ``thinkingConfig`` (``thinkingLevel`` for Gemini 3, ``thinkingBudget`` for
    Gemini 2.5) and sets ``includeThoughts``, so the generic effort is lifted
    out of ``extra_body``.
    """
    return _lift_reasoning_effort(extra_params)


def anthropic_reasoning(extra_params: Dict) -> Dict:
    """Claude 5+ models configure thinking via litellm's ``reasoning_effort``.

    litellm maps the top-level ``reasoning_effort`` kwarg onto
    ``thinking.type.adaptive`` + ``output_config.effort``, so the generic
    effort is lifted out of ``extra_body`` and ``extra_body`` is dropped
    (Anthropic does not accept extra inputs).
    """
    params = _lift_reasoning_effort(extra_params)
    params.pop("extra_body", None)
    return params


def _lift_reasoning_effort(extra_params: Dict) -> Dict:
    """Move the generic ``reasoning_effort`` out of ``extra_body`` to top level."""
    extra_body = extra_params.get("extra_body")

    if not isinstance(extra_body, dict):
        return extra_params

    effort = extra_body.pop("reasoning_effort", None)

    if effort is not None:
        extra_params["reasoning_effort"] = effort

    return extra_params
