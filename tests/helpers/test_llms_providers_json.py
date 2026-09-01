"""providers.json coverage: every OpenAI-compatible provider resolves.

``cecli/resources/providers.json`` lists the OpenAI-compatible providers cecli
ships with (base URL + API-key env var). This locks in that each one:

- is loaded by ``ModelProviderManager`` (supports_provider == True)
- resolves through ``resolve_model_config`` to the expected API family (``chat``
  for the OpenAI /chat/completions wire; ``responses`` for chatgpt; ``bedrock``
  for AWS Bedrock Converse)
- keeps its configured base URL and key env var
- routes through the base OpenAI-style provider adapter (Bearer auth) unless it
  registers a dedicated adapter (azure, bedrock, bedrock_mantle)

No network: resolution and adapter dispatch are offline.
"""

import importlib.resources as importlib_resources
import json

from cecli.helpers.llms.config import resolve_model_config
from cecli.helpers.llms.providers import ProviderAdapter, get_provider_adapter
from cecli.helpers.model_providers import ModelProviderManager

RESOURCE_FILE = "providers.json"

#: Providers whose model-settings default resolves to a non-``chat`` family.
EXPECTED_FAMILIES = {
    "chatgpt": "responses",  # ChatGPT subscription routes via /v1/responses
    "bedrock": "bedrock",  # AWS Bedrock Converse wire
}


def _providers_json() -> dict:
    resource = importlib_resources.files("cecli.resources").joinpath(RESOURCE_FILE)
    return json.loads(resource.read_text())


def test_every_providers_json_entry_is_supported():
    providers = _providers_json()
    assert providers, "providers.json should not be empty"
    mpm = ModelProviderManager()

    for name, cfg in providers.items():
        assert mpm.supports_provider(name), f"{name} should be supported"
        pcfg = mpm.get_provider_config(name) or {}
        assert pcfg.get("api_base") == cfg["api_base"]
        assert pcfg.get("api_key_env") == cfg["api_key_env"]


def test_every_provider_resolves_to_expected_family_with_base_and_key():
    providers = _providers_json()

    for name, cfg in providers.items():
        resolved = resolve_model_config(f"{name}/sample-model")
        expected_family = EXPECTED_FAMILIES.get(name, "chat")
        assert resolved["family"] == expected_family, f"{name} should use {expected_family}"
        assert resolved["provider"] == name
        assert resolved["api_base"] == cfg["api_base"].rstrip("/")
        assert resolved["api_key_env"] in cfg["api_key_env"]


def test_providers_use_registered_or_openai_style_base_adapter():
    """Every entry routes through its registered adapter, or the base adapter."""
    registry_names = set(_providers_json())

    for name in registry_names:
        adapter = get_provider_adapter(name)
        assert isinstance(adapter, ProviderAdapter)
        # Registered adapters advertise their own slug; the base adapter is
        # shared by all unregistered OpenAI-compatible providers.
        assert adapter.provider in ("openai", name), f"{name} adapter mismatch"
