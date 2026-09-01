"""Derive the ``api`` override block for a model.

The api block holds request-level parameters. :mod:`cecli.models` merges each
of these keys into ``extra_params`` the same way the ``api`` section of a
``model-overrides`` entry is applied.
"""

from __future__ import annotations

from typing import Dict, Optional

from .identifiers import is_anthropic, is_claude_5_plus, is_gemini_2_5
from .utils import supports_reasoning

_THINKING_BUDGET_TOKENS = 2048
#: Default thinking budget for Gemini 2.5 models (Gemini 2.5 Pro's default).
_GEMINI_THINKING_BUDGET_TOKENS = 8192


def derive_api_config(provider: Optional[str], route: str, record: Optional[Dict]) -> Dict:
    """Return the ``api`` config block for a model.

    Args:
        provider: Provider portion of the model name (may be ``None``).
        route: Model route (name after the provider prefix).
        record: The matched model metadata record, or ``None`` for unknown models.

    Returns:
        A dict of request-level params (reasoning format, thinking, tool calls).
    """
    reasoning = supports_reasoning(record)
    record = record or {}
    gemini_2_5 = is_gemini_2_5(provider, route, record)
    api: Dict = {}

    if reasoning and not gemini_2_5:
        effort = _default_reasoning_effort(record)

        if effort:
            api["reasoning_effort"] = effort

    if is_anthropic(provider, route, record) and not is_claude_5_plus(provider, route, record):
        # Claude 5+ uses adaptive thinking via ``reasoning_effort`` instead of
        # the ``thinking.type.enabled`` budget block.
        api["thinking"] = {"type": "enabled", "budget_tokens": _THINKING_BUDGET_TOKENS}
    elif gemini_2_5:
        # Gemini 2.5 configures thinking via a token budget; litellm maps the
        # generic ``thinking`` param onto ``thinkingBudget`` + ``includeThoughts``.
        api["thinking"] = {"type": "enabled", "budget_tokens": _GEMINI_THINKING_BUDGET_TOKENS}

    if record.get("supports_parallel_function_calling", True):
        api["parallel_tool_calls"] = True

    return api


def _default_reasoning_effort(record):
    """Default reasoning effort for a reasoning-capable model.

    Always ``medium``; the metadata effort flags are intentionally not used.
    """
    return "medium"
