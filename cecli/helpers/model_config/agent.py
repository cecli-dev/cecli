"""Derive the ``agent`` override block for a model.

The agent block holds ModelSettings overrides. :mod:`cecli.models` applies each
of these directly (``setattr``) the same way the ``agent`` section of a
``model-overrides`` entry is applied.
"""

from __future__ import annotations

from typing import Dict, Optional

from .identifiers import is_anthropic
from .utils import supports_reasoning


def _uses_anthropic_messages_api(
    provider: Optional[str], route: str, record: Optional[Dict]
) -> bool:
    """True when the model speaks the Anthropic /v1/messages wire format.

    Only the native Anthropic provider (explicit prefix, or a bare claude
    name that resolves to the anthropic record) and GitHub Copilot's
    anthropic-native proxy (``github_copilot/claude-*``) route through the
    messages family. Other claude routes (openrouter, deepseek, bedrock,
    ...) use chat completions / converse and keep their own caching
    semantics.
    """
    if provider == "anthropic":
        return True

    if provider == "github_copilot":
        return "claude" in (route or "").lower()

    if provider is None:
        return (record or {}).get("litellm_provider") == "anthropic"

    return False


def derive_agent_config(provider: Optional[str], route: str, record: Optional[Dict]) -> Dict:
    """Return the ``agent`` config block for a model.

    Args:
        provider: Provider portion of the model name (may be ``None``).
        route: Model route (name after the provider prefix).
        record: The matched model metadata record, or ``None`` for unknown models.

    Returns:
        A dict of ModelSettings overrides (caching, temperature handling).
    """
    reasoning = supports_reasoning(record)
    uses_messages_api = _uses_anthropic_messages_api(provider, route, record)
    agent: Dict = {
        "cache_control": is_anthropic(provider, route, record),
        # ``cache_read_input_token_cost`` in the metadata is the determinant for
        # whether a model supports prompt caching. Unknown models default to
        # assuming caching support.
        #
        # Anthropic messages-API models never cache "by default": prompt
        # caching only happens when the request asks for it (the llms
        # messages domain requests top-level automatic caching), so keep
        # ``caches_by_default`` off for them.
        "caches_by_default": (
            not uses_messages_api
            and (bool(record.get("cache_read_input_token_cost")) if record else True)
        ),
        "uses_messages_api": uses_messages_api,
    }

    if reasoning or record.get("supports_adaptive_thinking"):
        agent["use_temperature"] = False

    return agent
