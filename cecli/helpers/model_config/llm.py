"""Derive the ``llm`` override block for a model.

The llm block holds model metadata overrides. :mod:`cecli.models` merges these
into ``model.info`` the same way the ``llm`` section of a ``model-overrides``
entry is applied.
"""

from __future__ import annotations

from typing import Dict, Optional

from .identifiers import gpt_version, is_anthropic, is_github_copilot, is_meta
from .utils import supports_reasoning

RESPONSES_ENDPOINT = "/v1/responses"
CHAT_ENDPOINT = "/v1/chat/completions"
MESSAGES_ENDPOINT = "/v1/messages"


def derive_llm_config(provider: Optional[str], route: str, record: Optional[Dict]) -> Dict:
    """Return the ``llm`` config block for a model.

    Args:
        provider: Provider portion of the model name (may be ``None``).
        route: Model route (name after the provider prefix).
        record: The matched model metadata record, or ``None`` for unknown models.

    Returns:
        A dict of model-info overrides (provider, limits, mode, capabilities).
    """
    reasoning = supports_reasoning(record)
    record = record or {}
    endpoints = record.get("supported_endpoints") or []
    mode = _endpoint_mode(endpoints, provider, route, record)
    llm: Dict = {
        "litellm_provider": record.get("litellm_provider") or provider,
        # Token limits are taken verbatim from the metadata record; no guessing
        # or cross-key fallbacks between max_tokens/max_input_tokens/
        # max_output_tokens.
        "max_input_tokens": record.get("max_input_tokens"),
        "max_output_tokens": record.get("max_output_tokens"),
        "max_tokens": record.get("max_tokens"),
        "mode": mode,
        # All models are assumed to support tool calling.
        "supports_function_calling": True,
        # Streaming is assumed to be supported unless the metadata says otherwise.
        "supports_stream": bool(record.get("supports_stream", True)),
        "supports_parallel_function_calling": bool(
            record.get("supports_parallel_function_calling", True)
        ),
        "supports_response_schema": bool(record.get("supports_response_schema", True)),
        "supports_reasoning": reasoning,
        "supports_tool_choice": bool(record.get("supports_tool_choice", True)),
        "supports_vision": bool(record.get("supports_vision", False)),
    }
    endpoint = _endpoint_for_mode(mode, endpoints, provider, route, record)

    if endpoint:
        llm["supported_endpoints"] = [endpoint]

    return {k: v for k, v in llm.items() if v is not None}


def _endpoint_mode(endpoints, provider, route, record):
    """Pick responses vs chat mode based on the supported endpoints.

    Two rules force responses mode regardless of the record's endpoint list:
      1. GitHub Copilot gpt models newer than 5 (excluding ``mini`` variants).
      2. Meta-provider models.
    """
    if RESPONSES_ENDPOINT in (endpoints or []):
        return "responses"

    if _should_use_responses(provider, route, record):
        return "responses"

    return "chat"


def _endpoint_for_mode(mode, endpoints, provider, route, record):
    """Return the single endpoint that matches the derived endpoint type."""
    if mode == "responses":
        return RESPONSES_ENDPOINT

    if MESSAGES_ENDPOINT in (endpoints or []) and is_anthropic(provider, route, record):
        return MESSAGES_ENDPOINT

    if CHAT_ENDPOINT in (endpoints or []):
        return CHAT_ENDPOINT

    return None


def _should_use_responses(provider, route, record):
    """True when the model should use the responses API.

    Two rules force responses mode regardless of the record's endpoint list:
      1. GitHub Copilot gpt models newer than 5 (excluding ``mini`` variants).
      2. Meta-provider models.
    """
    if is_github_copilot(provider, route, record):
        if "mini" not in (route or "").lower() and gpt_version(route) >= 5:
            return True

    if is_meta(provider, route, record):
        return True

    return False
