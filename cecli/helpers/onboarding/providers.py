"""Provider and model discovery for the onboarding wizard."""

import importlib.resources as importlib_resources
import json
import os
from typing import Dict, List

# Providers that authenticate through mechanisms other than a simple _API_KEY
# (e.g. GitHub Copilot tokens or AWS credentials), so onboarding should never
# prompt for a key and instead jump straight to model selection.
NO_KEY_SLUGS = {"github_copilot", "bedrock", "bedrock_mantle"}

# Friendly display names for the default providers that are not covered by
# providers.json.
_PROVIDER_DISPLAY: Dict[str, str] = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "deepseek": "DeepSeek",
    "openrouter": "OpenRouter",
    "gemini": "Google Gemini",
    "github_copilot": "GitHub Copilot",
    "meta": "Meta",
}

# Builtin providers used as a fallback if the llms config is unavailable.
BUILTIN_PROVIDERS: List[Dict] = [
    {"slug": "openai", "display_name": "OpenAI", "api_key_env": ["OPENAI_API_KEY"]},
    {"slug": "anthropic", "display_name": "Anthropic", "api_key_env": ["ANTHROPIC_API_KEY"]},
    {
        "slug": "github_copilot",
        "display_name": "GitHub Copilot",
        "api_key_env": ["GITHUB_COPILOT_TOKEN"],
    },
]

# The bundled metadata resources used for model discovery. The ext file is a
# superset, so later entries win when both are merged.
_METADATA_RESOURCES = ("model-metadata.json", "model-metadata.ext.json")


def _provider_configs() -> Dict:
    from cecli.helpers.model_providers import PROVIDER_CONFIGS

    return PROVIDER_CONFIGS


def _load_metadata() -> Dict:
    """Merge the bundled model metadata resources into one ``{model: info}`` dict."""
    data = {}
    for name in _METADATA_RESOURCES:
        try:
            resource = importlib_resources.files("cecli.resources").joinpath(name)
        except (FileNotFoundError, ModuleNotFoundError):
            continue
        try:
            entries = json.loads(resource.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(entries, dict):
            data.update(entries)
    return data


def _models_from_metadata(data: Dict, slug: str) -> List[str]:
    """Return selectable model names for a provider from the metadata dict."""
    models = []
    for name, meta in data.items():
        if not isinstance(meta, dict):
            continue
        provider = meta.get("litellm_provider") or ""
        if provider == slug:
            models.append(name if name.startswith(slug + "/") else f"{slug}/{name}")
        elif name.startswith(slug + "/"):
            models.append(name)
    return models


def iter_providers() -> List[Dict]:
    """Return the list of providers selectable during onboarding."""
    providers: Dict[str, Dict] = {}

    # Default providers from the llms config (openai, anthropic, deepseek,
    # openrouter, gemini, github_copilot, meta, chutes, opencode-*).
    try:
        from cecli.helpers.llms.config import PROVIDER_DEFAULTS
    except ImportError:
        PROVIDER_DEFAULTS = None

    if PROVIDER_DEFAULTS:
        for slug, cfg in PROVIDER_DEFAULTS.items():
            key_env = cfg.get("api_key_env")
            key_env = [key_env] if isinstance(key_env, str) and key_env else []
            providers[slug] = {
                "slug": slug,
                "display_name": _PROVIDER_DISPLAY.get(slug) or slug,
                "api_key_env": key_env,
            }
    else:
        for entry in BUILTIN_PROVIDERS:
            providers[entry["slug"]] = dict(entry)

    # Custom providers from providers.json override the defaults where present.
    for slug, cfg in _provider_configs().items():
        providers[slug] = {
            "slug": slug,
            "display_name": cfg.get("display_name", slug),
            "api_key_env": list(cfg.get("api_key_env", []) or []),
        }

    return list(providers.values())


def provider_has_key(entry: Dict) -> bool:
    """Return True if the provider already has a key in the environment."""
    return any(os.environ.get(env_var) for env_var in entry.get("api_key_env") or [])


def provider_needs_key(entry: Dict) -> bool:
    """Return True if onboarding should prompt the user for an API key."""
    return entry["slug"] not in NO_KEY_SLUGS


def provider_display(entry: Dict) -> str:
    """Return the display label for a provider entry."""
    label = entry.get("display_name", entry["slug"])
    if provider_has_key(entry):
        return f"{label}  (key set)"
    return label


def get_models_for_provider(slug: str) -> List[str]:
    """Return the selectable model names for a provider."""
    models = _models_from_metadata(_load_metadata(), slug)
    if models:
        return sorted(set(models))

    # Fall back to a live fetch for providers absent from the bundled metadata.
    from cecli.models import model_info_manager

    manager = model_info_manager.provider_manager
    if manager.supports_provider(slug):
        try:
            manager.refresh_provider_cache(slug)
        except Exception:
            pass
        content = manager.get_provider_models(slug)
        if content:
            return sorted(f"{slug}/{model_id}" for model_id in content)
    return []
