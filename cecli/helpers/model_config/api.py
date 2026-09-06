"""Derive the ``api`` override block for a model.

The api block holds request-level parameters. :mod:`cecli.models` merges each
of these keys into ``extra_params`` the same way the ``api`` section of a
``model-overrides`` entry is applied.

The default reasoning effort and thinking budget are read from the config
registry (per model) so they can be set explicitly or by the pipeline; a
missing registry value falls back to the built-in defaults.
"""

from __future__ import annotations

from typing import Dict, Optional

from .identifiers import is_anthropic, is_claude_5_plus, is_gemini_2_5, is_glm, is_kimi
from .registry import get_default
from .utils import supports_reasoning

_THINKING_BUDGET_TOKENS = 2048
#: Default thinking budget for Gemini 2.5 models (Gemini 2.5 Pro's default).
_GEMINI_THINKING_BUDGET_TOKENS = 8192
#: Default reasoning effort for reasoning-capable models.
_DEFAULT_REASONING_EFFORT = "medium"
#: Default reasoning effort for some newer models, which use ``low``/``high``/
#: ``max`` levels instead of the ``low``/``medium``/``high`` ladder.
_DEFAULT_HIGH_REASONING_EFFORT = "high"


def derive_api_config(
    provider: Optional[str], route: str, record: Optional[Dict], model_name: Optional[str] = None
) -> Dict:
    """Return the ``api`` config block for a model.

    Args:
        provider: Provider portion of the model name (may be ``None``).
        route: Model route (name after the provider prefix).
        record: The matched model metadata record, or ``None`` for unknown models.
        model_name: Fully qualified model name used to look up the config
            registry; when ``None`` the built-in defaults are used.

    Returns:
        A dict of request-level params (reasoning format, thinking, tool calls).
    """
    reasoning = supports_reasoning(record)
    record = record or {}
    gemini_2_5 = is_gemini_2_5(provider, route, record)
    api: Dict = {}
    defaults = get_default(model_name) if model_name else {}

    if reasoning and not gemini_2_5:
        default_effort = _DEFAULT_REASONING_EFFORT

        if is_glm(provider, route, record) or is_kimi(provider, route, record):
            default_effort = _DEFAULT_HIGH_REASONING_EFFORT

        effort = _resolve_reasoning_effort(defaults.get("reasoning"), default_effort)

        if effort:
            api["reasoning_effort"] = effort

    if is_anthropic(provider, route, record) and not is_claude_5_plus(provider, route, record):
        # Claude 5+ uses adaptive thinking via ``reasoning_effort`` instead of
        # the ``thinking.type.enabled`` budget block.
        budget = _resolve_thinking_budget(defaults.get("thinking"), _THINKING_BUDGET_TOKENS)

        if budget:
            api["thinking"] = {"type": "enabled", "budget_tokens": budget}
    elif gemini_2_5:
        # Gemini 2.5 configures thinking via a token budget; litellm maps the
        # generic ``thinking`` param onto ``thinkingBudget`` + ``includeThoughts``.
        budget = _resolve_thinking_budget(defaults.get("thinking"), _GEMINI_THINKING_BUDGET_TOKENS)

        if budget:
            api["thinking"] = {"type": "enabled", "budget_tokens": budget}

    if record.get("supports_parallel_function_calling", True):
        api["parallel_tool_calls"] = True

    return api


def _resolve_reasoning_effort(registered, default=_DEFAULT_REASONING_EFFORT):
    """Return the default reasoning effort for a model.

    ``"none"`` opts out (no default), a missing/empty registered value keeps
    ``default``, and any other value is used verbatim.
    """
    if registered is None or registered == "":
        return default

    if registered == "none":
        return None

    return registered


def _resolve_thinking_budget(registered, default):
    """Return the default thinking budget for a model.

    ``0`` opts out of a thinking level, a missing/empty registered value keeps
    ``default``, and any other value is used verbatim.
    """
    if registered is None or registered == "":
        return default

    if registered == 0 or registered == "0":
        return None

    return registered
