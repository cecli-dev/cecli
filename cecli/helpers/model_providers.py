"""Unified model provider metadata caching and lookup.

Historically cecli kept separate modules per provider (OpenRouter vs OpenAI-like).
Those grew unwieldy and duplicated caching, request, and normalization logic.
This helper centralizes that behavior so every OpenAI-compatible endpoint defines
a small config blob and inherits the same cache + routing plumbing.
Provider configs remain curated via ``scripts/generate_providers.py`` and the
static per-model fallback metadata is still cleaned up with ``clean_metadata.py``.
"""

from __future__ import annotations

import importlib.resources as importlib_resources
import json
import os
import re
import time
from copy import deepcopy
from pathlib import Path
from typing import Dict, Optional

import requests

from cecli.helpers.file_searcher import handle_core_files

RESOURCE_FILE = "providers.json"


def _first_env_value(names):
    """Return the first non-empty environment variable for the provided names."""
    if not names:
        return None
    if isinstance(names, str):
        names = [names]
    for env_name in names or []:
        if not env_name:
            continue
        val = os.environ.get(env_name)
        if val:
            return val
    return None


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """Recursively merge override dict into base without mutating inputs."""
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _load_provider_configs() -> Dict[str, Dict]:
    """Load provider configuration overrides from the packaged JSON file."""
    configs: Dict[str, Dict] = {}
    try:
        resource = importlib_resources.files("cecli.resources").joinpath(RESOURCE_FILE)
        data = json.loads(resource.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    for provider, override in data.items():
        base = configs.get(provider, {})
        configs[provider] = _deep_merge(base, override)
    return configs


PROVIDER_CONFIGS = _load_provider_configs()


class ModelProviderManager:
    CACHE_TTL = 60 * 60 * 24
    DEFAULT_TOKEN_PRICE_RATIO = 1000000

    def __init__(self, provider_configs: Optional[Dict[str, Dict]] = None) -> None:
        self.cache_dir = handle_core_files(Path.home() / ".cecli" / "caches")
        self.verify_ssl: bool = True
        self.provider_configs = provider_configs or deepcopy(PROVIDER_CONFIGS)
        self._provider_cache: Dict[str, Dict | None] = {}
        self._cache_loaded: Dict[str, bool] = {}
        for name in self.provider_configs:
            self._provider_cache[name] = None
            self._cache_loaded[name] = False

    def set_verify_ssl(self, verify_ssl: bool) -> None:
        self.verify_ssl = verify_ssl

    def merge_provider_configs(self, user_configs: Dict[str, Dict]) -> None:
        """Merge user-defined provider configs into the existing provider configs.

        Merges into both this instance and the module-level ``PROVIDER_CONFIGS``
        so freshly-constructed managers (e.g. the llms dispatcher's config
        resolver) see the same user providers without sharing instance state.
        """
        for slug, cfg in user_configs.items():
            if slug in self.provider_configs:
                self.provider_configs[slug] = _deep_merge(self.provider_configs[slug], cfg)
            else:
                self.provider_configs[slug] = deepcopy(cfg)
                self._provider_cache[slug] = None
                self._cache_loaded[slug] = False

            if slug in PROVIDER_CONFIGS:
                PROVIDER_CONFIGS[slug] = _deep_merge(PROVIDER_CONFIGS[slug], cfg)
            else:
                PROVIDER_CONFIGS[slug] = deepcopy(cfg)

    def supports_provider(self, provider: Optional[str]) -> bool:
        return bool(provider and provider in self.provider_configs)

    def get_provider_config(self, provider: Optional[str]) -> Optional[Dict]:
        if not provider:
            return None
        config = self.provider_configs.get(provider)
        if not config:
            return None
        config = dict(config)
        config.setdefault("litellm_provider", provider)
        return config

    def get_provider_base_url(self, provider: Optional[str]) -> Optional[str]:
        config = self.get_provider_config(provider)
        if not config:
            return None
        base_envs = config.get("base_url_env") or []
        for env_var in base_envs:
            val = os.environ.get(env_var)
            if val:
                return val.rstrip("/")
        return config.get("api_base")

    def get_required_api_keys(self, provider: Optional[str]) -> list[str]:
        config = self.get_provider_config(provider)
        if not config:
            return []
        return list(config.get("api_key_env", []))

    def get_provider_session_header(self, provider: Optional[str]) -> Optional[str]:
        """Return the configured session header name (if any) for a provider."""
        config = self.get_provider_config(provider)

        if not config:
            return None

        return config.get("session_header")

    def get_model_info(self, model: str) -> Dict:
        provider, route = self._split_model(model)
        if not provider or not self._ensure_provider_state(provider):
            return {}
        content = self._ensure_content(provider)
        record = self._find_record(content, route)
        if not record and self.refresh_provider_cache(provider):
            content = self._provider_cache.get(provider)
            record = self._find_record(content, route)
        if not record:
            return {}
        return self._record_to_info(record, provider)

    def get_models_for_listing(self) -> Dict[str, Dict]:
        listings: Dict[str, Dict] = {}
        for provider in list(self.provider_configs.keys()):
            content = self._ensure_content(provider)
            if not content or "data" not in content:
                continue
            for record in content["data"]:
                model_id = record.get("id")
                if not model_id:
                    continue
                info = self._record_to_info(record, provider)
                if info:
                    listings[model_id] = info
        return listings

    def refresh_provider_cache(self, provider: str) -> bool:
        if not self._ensure_provider_state(provider):
            return False
        config = self.provider_configs[provider]
        if not config.get("models_url") and not config.get("api_base"):
            return False
        self._provider_cache[provider] = None
        self._cache_loaded[provider] = True
        self._update_cache(provider)
        return bool(self._provider_cache.get(provider))

    def _ensure_provider_state(self, provider: str) -> bool:
        if provider not in self.provider_configs:
            return False
        self._provider_cache.setdefault(provider, None)
        self._cache_loaded.setdefault(provider, False)
        return True

    def _split_model(self, model: str) -> tuple[Optional[str], str]:
        if "/" not in model:
            return None, model
        provider, route = model.split("/", 1)
        return provider, route

    def _ensure_content(self, provider: str) -> Optional[Dict]:
        self._load_cache(provider)
        if not self._provider_cache.get(provider):
            self._update_cache(provider)
        return self._provider_cache.get(provider)

    def _find_record(self, content: Optional[Dict], route: str) -> Optional[Dict]:
        if not content or "data" not in content:
            return None
        candidates = {route}
        if ":" in route:
            candidates.add(route.split(":", 1)[0])
        return next((item for item in content["data"] if item.get("id") in candidates), None)

    def _record_to_info(self, record: Dict, provider: str) -> Dict:
        context_len = _first_value(
            record,
            "max_input_tokens",
            "max_tokens",
            "max_output_tokens",
            "context_length",
            "context_window",
            "top_provider_context_length",
            "top_provider",
        )
        if isinstance(context_len, dict):
            context_len = context_len.get("context_length") or context_len.get("max_tokens")
        pricing = record.get("pricing", {}) if isinstance(record.get("pricing"), dict) else {}
        input_cost = _cost_per_token(
            _first_value(pricing, "prompt", "input", "prompt_tokens")
            or _first_value(record, "input_cost_per_token", "prompt_cost_per_token")
        )
        output_cost = _cost_per_token(
            _first_value(pricing, "completion", "output", "completion_tokens")
            or _first_value(record, "output_cost_per_token", "completion_cost_per_token")
        )
        max_tokens = _first_value(
            record,
            "max_tokens",
            "max_input_tokens",
            "context_length",
            "context_window",
            "top_provider_context_length",
        )
        max_output_tokens = _first_value(
            record,
            "max_output_tokens",
            "max_tokens",
            "context_length",
            "context_window",
            "top_provider_context_length",
        )
        if max_tokens is None:
            max_tokens = context_len
        if max_output_tokens is None:
            max_output_tokens = context_len

        def _normalize_cost(cost: Optional[float]) -> float:
            if cost is None or cost == 0:
                return 0.0
            if cost >= 0.001:
                return cost / self.DEFAULT_TOKEN_PRICE_RATIO
            return cost

        info = {
            "max_input_tokens": context_len,
            "max_tokens": max_tokens,
            "max_output_tokens": max_output_tokens,
            "input_cost_per_token": _normalize_cost(input_cost),
            "output_cost_per_token": _normalize_cost(output_cost),
            "litellm_provider": provider,
            "mode": record.get("mode", "chat"),
        }
        return {k: v for k, v in info.items() if v is not None}

    def _get_cache_file(self, provider: str) -> Path:
        fname = f"{provider}_models.json"
        return self.cache_dir / fname

    def _normalize_models_payload(self, provider: str, payload: Dict) -> Dict:
        """Normalize provider payloads into an OpenAI-style `{data: [{id: ...}]}`."""
        if not isinstance(payload, dict):
            return {}
        if "data" in payload and isinstance(payload.get("data"), list):
            return payload
        # Fireworks returns `{models: [...], nextPageToken: ..., totalSize: ...}`
        models = payload.get("models")
        if isinstance(models, list):
            normalized = []
            for item in models:
                if not isinstance(item, dict):
                    continue
                model_id = item.get("name") or item.get("id")
                if not model_id:
                    continue
                record = {"id": model_id}
                for key in (
                    "max_input_tokens",
                    "max_output_tokens",
                    "max_tokens",
                    "context_length",
                    "context_window",
                    "mode",
                    "pricing",
                    "input_cost_per_token",
                    "output_cost_per_token",
                ):
                    if key in item and item[key] is not None:
                        record[key] = item[key]
                normalized.append(record)
            return {"data": normalized}
        return {}

    def _load_cache(self, provider: str) -> None:
        if self._cache_loaded.get(provider):
            return
        cache_file = self._get_cache_file(provider)
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            if cache_file.exists():
                cache_age = time.time() - cache_file.stat().st_mtime
                if cache_age < self.CACHE_TTL:
                    try:
                        self._provider_cache[provider] = json.loads(cache_file.read_text())
                    except json.JSONDecodeError:
                        self._provider_cache[provider] = None
        except OSError:
            pass
        self._cache_loaded[provider] = True

    def _update_cache(self, provider: str) -> None:
        payload = self._fetch_provider_models(provider)
        cache_file = self._get_cache_file(provider)
        if payload:
            normalized = self._normalize_models_payload(provider, payload)
            self._provider_cache[provider] = normalized
            try:
                cache_file.write_text(json.dumps(normalized, indent=2))
            except OSError:
                pass
            return
        static_models = self.provider_configs[provider].get("static_models")
        if static_models and not self._provider_cache.get(provider):
            self._provider_cache[provider] = {"data": static_models}

    def _fetch_provider_models(self, provider: str) -> Optional[Dict]:
        config = self.provider_configs[provider]
        models_url = config.get("models_url")
        if not models_url:
            api_base = config.get("api_base")
            if api_base:
                models_url = api_base.rstrip("/") + "/models"
        if not models_url:
            return None
        # Substitute {account_id} placeholder if present
        if "{account_id}" in models_url:
            account_id = self._get_account_id(provider)
            if not account_id:
                # Remove /accounts/{account_id} portion from URL if account_id is not set
                models_url = models_url.replace("/accounts/{account_id}", "")
            else:
                models_url = models_url.replace("{account_id}", account_id)
        headers = {}
        default_headers = config.get("default_headers") or {}
        headers.update(default_headers)
        api_key = self._get_api_key(provider)
        requires_api_key = config.get("requires_api_key", True)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        elif requires_api_key:
            return None
        try:
            response = requests.get(
                models_url,
                headers=headers or None,
                timeout=config.get("timeout", 10),
                verify=self.verify_ssl,
            )
            response.raise_for_status()
            return response.json()
        except Exception as ex:
            print(f"Failed to fetch {provider} model list: {ex}")
            return None

    def _get_api_key(self, provider: str) -> Optional[str]:
        config = self.provider_configs[provider]
        for env_var in config.get("api_key_env", []):
            value = os.environ.get(env_var)
            if value:
                return value
        return None

    def _get_account_id(self, provider: str) -> Optional[str]:
        config = self.provider_configs[provider]
        account_id_env = config.get("account_id_env")
        if account_id_env:
            return os.environ.get(account_id_env)
        return None


_NUMBER_RE = re.compile(r"-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


def _cost_per_token(val: Optional[str | float | int]) -> Optional[float]:
    """Parse token pricing strings into floats, tolerating currency prefixes."""
    if val in (None, "", "-", "N/A"):
        return None
    if val == "0":
        return 0.0
    if isinstance(val, str):
        cleaned = val.strip().replace(",", "")
        if cleaned.startswith("$"):
            cleaned = cleaned[1:]
        match = _NUMBER_RE.search(cleaned)
        if not match:
            return None
        val = match.group(0)
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _first_value(record: Dict, *keys: str):
    """Return the first non-empty value for the provided keys."""
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None
