"""Model config resolution for the llms package.

Reuses cecli's ``model_config`` pipeline (``get_default_config``) and
``model_providers`` (``ModelProviderManager`` + ``PROVIDER_CONFIGS``) as the
source of truth for base URL / api-key env / extra headers, with hardcoded
fallbacks for the built-in providers.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from cecli.helpers.model_config.pipeline import get_default_config
from cecli.helpers.model_providers import ModelProviderManager

#: Built-in provider defaults (base URLs / key env). Custom providers (chutes,
#: ...) are resolved from cecli PROVIDER_CONFIGS.
PROVIDER_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "openai": {"api_base": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY"},
    "anthropic": {"api_base": "https://api.anthropic.com", "api_key_env": "ANTHROPIC_API_KEY"},
    "deepseek": {"api_base": "https://api.deepseek.com/v1", "api_key_env": "DEEPSEEK_API_KEY"},
    "openrouter": {"api_base": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY"},
    "gemini": {
        "api_base": "https://generativelanguage.googleapis.com",
        "api_key_env": "GEMINI_API_KEY",
    },
    "github_copilot": {"api_base": "https://api.githubcopilot.com", "api_key_env": None},
    "meta": {"api_base": "https://api.meta.ai/v1", "api_key_env": "META_API_KEY"},
    "chutes": {"api_base": "https://llm.chutes.ai/v1/", "api_key_env": "CHUTES_API_KEY"},
    "opencode-go": {
        "api_base": "https://opencode.ai/zen/go/v1",
        "api_key_env": "OPENCODE_GO_API_KEY",
    },
    "opencode-zen": {
        "api_base": "https://opencode.ai/zen/zen/v1",
        "api_key_env": "OPENCODE_ZEN_API_KEY",
    },
}


def resolve_model_config(model: str) -> Dict[str, Any]:
    """Resolve provider/api-base/api-key/API-family for a model.

    Priority for api_base: explicit env ``{PROVIDER}_API_BASE`` > cecli
    ``PROVIDER_CONFIGS[provider].api_base`` > built-in default.
    """
    cfg = get_default_config(model)
    llm_block = cfg.get("llm") or {}
    api_block = cfg.get("api") or {}
    agent_block = dict(cfg.get("agent") or {})
    prefix = model.split("/", 1)[0] if "/" in model else None
    provider = llm_block.get("litellm_provider") or prefix
    route = model.split("/", 1)[1] if "/" in model else model
    is_claude = "claude" in route.lower()

    mpm = ModelProviderManager()

    # Providers with dedicated routing semantics (authenticated session, AWS
    # SigV4 signing, dedicated endpoint templates) win over the metadata
    # record's ``litellm_provider`` for every model under their prefix, so a
    # ``github_copilot/`` / ``bedrock/`` / ``bedrock_mantle/`` model never
    # falls back to a bare (anthropic/openai) record (e.g.
    # ``github_copilot/claude-sonnet-4-5`` resolving to the bare
    # ``claude-sonnet-4-5`` anthropic entry).
    if prefix in ("github_copilot", "bedrock", "bedrock_mantle"):
        provider = prefix

    # Anthropic models hosted by a third-party provider (openrouter, deepseek,
    # ...) authenticate against THAT provider, not anthropic: ``{provider}/claude-*``
    # must route through the provider prefix even when the record lookup lands
    # on the bare anthropic entry (e.g. ``openrouter/claude-sonnet-5``).
    elif prefix and prefix != "anthropic" and is_claude:
        provider = prefix

    # A configured provider (built-in providers.json entry or a user-defined
    # ``model-providers`` entry such as ``bifrost``) wins over the metadata
    # record's ``litellm_provider`` for every model under its prefix, so
    # ``bifrost/gemini/gemini-2.5-pro`` routes through bifrost (its api_base)
    # rather than falling back to the bare ``gemini/gemini-2.5-pro`` record.
    elif prefix and provider != prefix and mpm.supports_provider(prefix):
        provider = prefix

    pcfg = mpm.get_provider_config(provider) or {}

    env_base = os.environ.get(f"{provider.upper()}_API_BASE") if provider else None
    api_base = (
        env_base
        or pcfg.get("api_base")
        or PROVIDER_DEFAULTS.get(provider or "", {}).get("api_base")
    )
    api_base = api_base.rstrip("/") if api_base else None

    # github_copilot resolves its endpoint from the authenticated session
    # (api-key.json endpoints.api), never from a caller-supplied base.
    if provider == "github_copilot":
        from .providers.github_copilot import copilot_api_base

        api_base = (env_base or copilot_api_base()).rstrip("/")

    key_envs = pcfg.get("api_key_env") or [
        PROVIDER_DEFAULTS.get(provider or "", {}).get("api_key_env")
    ]
    key_env = next((e for e in key_envs if e), None)

    mode = llm_block.get("mode") or "chat"
    endpoints = llm_block.get("supported_endpoints") or []

    # API family: responses > anthropic messages > gemini > chat completions
    if provider == "github_copilot":
        # Copilot supports all three; claude -> anthropic-native /v1/messages,
        # gpt-5-mini -> chat, everything else -> responses.
        if "claude" in route.lower():
            family = "messages"
        elif "gpt-5-mini" in route.lower():
            family = "chat"
        else:
            family = "responses"
    elif provider in ("bedrock", "bedrock_converse"):
        # AWS Bedrock Converse wire (SigV4-signed; see domains/bedrock.py).
        family = "bedrock"
    elif provider == "bedrock_mantle":
        # Mantle is an OpenAI-compatible chat wire (SigV4-signed via the chat
        # family's signer hook); see providers/bedrock_mantle.py.
        family = "chat"
    elif is_claude and provider != "anthropic":
        # A claude model on a non-anthropic provider uses that provider's
        # OpenAI-compatible chat completions wire (openrouter, deepseek,
        # azure_ai, ...); only native anthropic (or copilot's anthropic-native
        # /v1/messages proxy, handled above) speaks the messages API.
        family = "chat"
    elif mode == "responses" or "/v1/responses" in endpoints:
        family = "responses"
    elif provider == "anthropic":
        family = "messages"
    elif provider == "gemini":
        family = "gemini"
    else:
        family = "chat"

    extra_headers = dict(pcfg.get("default_headers") or {})
    extra_body = dict(api_block.get("extra_body") or {})

    # Effective cache flags for the domain adapters. Anthropic messages-API
    # models never cache "by default": prompt caching only happens when the
    # request asks for it, so the messages domain requests top-level automatic
    # caching (agent.cache_control True + caches_by_default False).
    if family == "messages":
        agent_block["cache_control"] = True
        agent_block["caches_by_default"] = False

    return {
        "model": model,
        "provider": provider,
        "route": route,
        "family": family,
        "api_base": api_base,
        "api_key_env": key_env,
        "extra_headers": extra_headers,
        "extra_body": extra_body,
        "extra_query": dict(pcfg.get("extra_query") or {}),
        "session_header": mpm.get_provider_session_header(provider),
        "api_block": api_block,
        "llm_block": llm_block,
        "agent_block": agent_block,
    }


def get_api_key(resolved: Dict[str, Any], api_key: Optional[str]) -> Optional[str]:
    """Return the API key: explicit arg, else env, else copilot auth, else None."""
    if api_key:
        return api_key

    if resolved.get("provider") == "github_copilot":
        from .providers.github_copilot import copilot_api_key

        return copilot_api_key()

    env_name = resolved.get("api_key_env")

    if env_name:
        return os.environ.get(env_name)

    return None


__all__ = ["PROVIDER_DEFAULTS", "resolve_model_config", "get_api_key"]
