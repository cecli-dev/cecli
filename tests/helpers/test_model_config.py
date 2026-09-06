"""Tests for the metadata-driven model config pipeline."""

import json

from cecli.helpers.model_config import ModelConfigPipeline, get_default_config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record(**overrides):
    """Build a litellm-style metadata record with sane defaults."""
    record = {
        "litellm_provider": "openai",
        "max_input_tokens": 272000,
        "max_output_tokens": 128000,
        "max_tokens": 128000,
        "mode": "chat",
        "supported_endpoints": ["/v1/chat/completions", "/v1/responses"],
        "supports_function_calling": True,
        "supports_parallel_function_calling": True,
        "supports_prompt_caching": True,
        "supports_reasoning": True,
        "supports_response_schema": True,
        "supports_tool_choice": True,
        "supports_vision": False,
        "cache_read_input_token_cost": 1.25e-7,
    }
    record.update(overrides)
    return record


# ---------------------------------------------------------------------------
# Lookup behavior
# ---------------------------------------------------------------------------


def test_exact_model_match():
    metadata = {"gpt-5": _record()}
    config = get_default_config("gpt-5", [metadata])

    assert config["llm"]["litellm_provider"] == "openai"
    assert config["llm"]["max_input_tokens"] == 272000
    assert config["llm"]["mode"] == "responses"
    assert config["llm"]["supported_endpoints"] == ["/v1/responses"]


def test_provider_prefixed_lookup():
    metadata = {
        "deepseek/deepseek-v4-flash": _record(
            litellm_provider="deepseek", supported_endpoints=["/v1/chat/completions"]
        )
    }
    config = get_default_config("deepseek/deepseek-v4-flash", [metadata])

    assert config["llm"]["litellm_provider"] == "deepseek"
    assert config["llm"]["mode"] == "chat"
    assert config["llm"]["supported_endpoints"] == ["/v1/chat/completions"]
    assert config["api"]["reasoning_effort"] == "medium"


def test_route_match_without_provider_prefix():
    metadata = {"gpt-5": _record()}
    config = get_default_config("openai/gpt-5", [metadata])

    assert config["llm"]["litellm_provider"] == "openai"


def test_family_fallback_to_newer_family():
    metadata = {"gpt-5": _record()}
    config = get_default_config("openai/gpt-5.6-luna", [metadata])

    assert config["llm"]["litellm_provider"] == "openai"
    assert config["llm"]["max_input_tokens"] == 272000


def test_closest_provider_match():
    metadata = {
        "vendor/gpt-5-x": _record(litellm_provider="vendor", max_input_tokens=272000),
        "vendor/other": _record(litellm_provider="vendor", max_input_tokens=999),
    }
    config = get_default_config("vendor/gpt-5-y", [metadata])

    assert config["llm"]["litellm_provider"] == "vendor"
    assert config["llm"]["max_input_tokens"] == 272000


def test_no_match_returns_defaults():
    config = get_default_config("unknown/model", [])

    assert config["api"] == {"reasoning_effort": "medium", "parallel_tool_calls": True}
    assert config["llm"] == {
        "litellm_provider": "unknown",
        "mode": "chat",
        "supports_function_calling": True,
        "supports_stream": True,
        "supports_parallel_function_calling": True,
        "supports_response_schema": True,
        "supports_reasoning": True,
        "supports_tool_choice": True,
        "supports_vision": False,
    }
    assert config["agent"] == {
        "cache_control": False,
        "caches_by_default": True,
        "use_temperature": False,
        "uses_messages_api": False,
    }
    # Unknown models get a noop reasoning formatter (the default behavior in
    # set_reasoning_effort is used unchanged).
    assert callable(config["helpers"]["format_reasoning"])


# ---------------------------------------------------------------------------
# Metadata sources
# ---------------------------------------------------------------------------


def test_metadata_files_merge_later_wins():
    first = {"model": _record(litellm_provider="openai")}
    second = {"model": _record(litellm_provider="other")}
    config = get_default_config("model", [first, second])

    assert config["llm"]["litellm_provider"] == "other"


def test_json_file_and_string_sources(tmp_path):
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps({"model": _record(litellm_provider="file")}))
    config = get_default_config("model", [str(path)])

    assert config["llm"]["litellm_provider"] == "file"

    raw = json.dumps({"model": _record(litellm_provider="raw")})
    config = get_default_config("model", [raw])

    assert config["llm"]["litellm_provider"] == "raw"


def test_overlong_raw_json_string_source():
    """Raw JSON strings longer than the OS path limit are scanned as JSON.

    Regression for CI failures on Python <= 3.12 where ``Path.exists()``
    raised OSError [Errno 36] ENAMETOOLONG when probing an over-long string
    instead of returning False, crashing ``Model(...)`` setup.
    """
    raw = json.dumps({"model": _record(litellm_provider="overlong"), "padding": "x" * 5000})

    assert len(raw) > 4096

    config = get_default_config("model", [raw])

    assert config["llm"]["litellm_provider"] == "overlong"


def test_model_init_with_overlong_raw_metadata(monkeypatch):
    """Model init tolerates an over-long raw metadata string from get_metadata_sources."""
    from cecli.models import Model, model_info_manager

    big = json.dumps({"model": _record(litellm_provider="overlong"), "padding": "x" * 5000})
    monkeypatch.setattr(model_info_manager, "get_metadata_sources", lambda: [big])
    monkeypatch.setattr(model_info_manager, "get_model_info", lambda model: {})

    model = Model("model")

    assert model.info["litellm_provider"] == "overlong"


def test_single_dict_source():
    config = get_default_config("model", {"model": _record(litellm_provider="openai")})

    assert config["llm"]["litellm_provider"] == "openai"


def test_pipeline_class_default_sources():
    pipeline = ModelConfigPipeline(metadata_files=[{"model": _record()}])
    config = pipeline.get_default_config("model")

    assert config["llm"]["litellm_provider"] == "openai"


# ---------------------------------------------------------------------------
# Derived config blocks
# ---------------------------------------------------------------------------


def test_tool_calling_always_true():
    metadata = {"model": _record(supports_function_calling=False)}
    config = get_default_config("model", [metadata])

    assert config["llm"]["supports_function_calling"] is True


def test_responses_vs_chat_mode():
    chat = _record(supported_endpoints=["/v1/chat/completions"])
    responses = _record(supported_endpoints=["/v1/chat/completions", "/v1/batch", "/v1/responses"])

    chat_config = get_default_config("chat-model", [{"chat-model": chat}])
    resp_config = get_default_config("resp-model", [{"resp-model": responses}])

    assert chat_config["llm"]["mode"] == "chat"
    assert chat_config["llm"]["supported_endpoints"] == ["/v1/chat/completions"]
    assert resp_config["llm"]["mode"] == "responses"
    assert resp_config["llm"]["supported_endpoints"] == ["/v1/responses"]


def test_token_limits_not_guessed():
    only_max = _record()
    only_max.pop("max_input_tokens")
    only_max.pop("max_output_tokens")
    config = get_default_config("only-max", [{"only-max": only_max}])

    assert config["llm"]["max_tokens"] == 128000
    assert "max_input_tokens" not in config["llm"]
    assert "max_output_tokens" not in config["llm"]

    only_input = _record()
    only_input.pop("max_output_tokens")
    only_input.pop("max_tokens")
    config = get_default_config("only-input", [{"only-input": only_input}])

    assert config["llm"]["max_input_tokens"] == 272000
    assert "max_tokens" not in config["llm"]


def test_anthropic_chat_uses_messages_endpoint():
    metadata = {
        "anthropic/claude-sonnet-5": _record(
            litellm_provider="anthropic", supported_endpoints=["/v1/messages"]
        )
    }
    config = get_default_config("anthropic/claude-sonnet-5", [metadata])

    assert config["llm"]["mode"] == "chat"
    assert config["llm"]["supported_endpoints"] == ["/v1/messages"]


def test_reasoning_effort_defaults_to_medium():
    high = _record(supports_high_reasoning_effort=True)
    generic = _record(supports_reasoning=True)

    # The default reasoning effort is always medium, regardless of the
    # metadata effort flags.
    assert get_default_config("high", [{"high": high}])["api"]["reasoning_effort"] == "medium"
    assert (
        get_default_config("generic", [{"generic": generic}])["api"]["reasoning_effort"] == "medium"
    )


def test_glm_and_kimi_default_to_high_reasoning_effort():
    """GLM/Kimi models default to ``high`` effort, not ``medium``."""
    glm = _record(litellm_provider="zai")
    kimi = _record(litellm_provider="moonshot")

    assert get_default_config("glm-4.6", [{"glm-4.6": glm}])["api"]["reasoning_effort"] == "high"
    assert get_default_config("kimi-k2", [{"kimi-k2": kimi}])["api"]["reasoning_effort"] == "high"


def test_vision_flag():
    vision = _record(supports_vision=True)
    no_vision = _record(supports_vision=False)

    assert get_default_config("v", [{"v": vision}])["llm"]["supports_vision"] is True
    assert get_default_config("nv", [{"nv": no_vision}])["llm"]["supports_vision"] is False


def test_anthropic_thinking_and_cache_control():
    config = get_default_config("anthropic/claude-opus-4-7", [])

    assert config["agent"]["cache_control"] is True
    assert config["agent"]["use_temperature"] is False
    assert config["api"]["thinking"]["type"] == "enabled"
    assert config["api"]["thinking"]["budget_tokens"] == 2048


def test_claude_route_detects_anthropic():
    metadata = {
        "github_copilot/claude-sonnet-5": _record(
            litellm_provider="github_copilot", supported_endpoints=["/v1/messages"]
        )
    }
    config = get_default_config("github_copilot/claude-sonnet-5", [metadata])

    assert config["agent"]["cache_control"] is True
    # Claude 5+ uses reasoning_effort (adaptive thinking) instead of a thinking
    # budget block.
    assert "thinking" not in config["api"]
    assert config["api"]["reasoning_effort"] == "medium"
    assert config["llm"]["supported_endpoints"] == ["/v1/messages"]


# ---------------------------------------------------------------------------
# Caching support
# ---------------------------------------------------------------------------


def test_cache_read_input_token_cost_drives_caching():
    cached = _record(cache_read_input_token_cost=2.8e-9)
    no_cache = _record(cache_read_input_token_cost=0)

    assert get_default_config("cached", [{"cached": cached}])["agent"]["caches_by_default"] is True
    assert (
        get_default_config("no-cache", [{"no-cache": no_cache}])["agent"]["caches_by_default"]
        is False
    )


def test_missing_cost_key_disables_caching():
    record = _record()
    record.pop("cache_read_input_token_cost")
    metadata = {"model": record}

    assert get_default_config("model", [metadata])["agent"]["caches_by_default"] is False


def test_raw_scan_prefers_bare_key_over_prefixed():
    raw = json.dumps(
        {
            "github_copilot/gpt-5": _record(litellm_provider="github_copilot"),
            "gpt-5": _record(litellm_provider="openai"),
        }
    )
    config = get_default_config("gpt-5", [raw])

    assert config["llm"]["litellm_provider"] == "openai"

    config = get_default_config("github_copilot/gpt-5", [raw])

    assert config["llm"]["litellm_provider"] == "github_copilot"


def test_bundled_metadata_default():
    config = get_default_config("gpt-5")

    assert config["llm"]["litellm_provider"] == "openai"
    assert config["llm"]["mode"] == "responses"


def test_supports_stream_default_true():
    generic = _record()
    no_stream = _record(supports_stream=False)

    assert get_default_config("generic", [{"generic": generic}])["llm"]["supports_stream"] is True
    assert (
        get_default_config("no-stream", [{"no-stream": no_stream}])["llm"]["supports_stream"]
        is False
    )


def test_model_init_uses_pipeline_defaults(tmp_path, monkeypatch):
    """Model.__init__ derives info and settings from the model config pipeline."""
    from cecli.models import Model, model_info_manager

    metadata_file = tmp_path / "custom-metadata.json"
    metadata_file.write_text(
        json.dumps(
            {
                "custom/alpha": {
                    "litellm_provider": "custom",
                    "max_input_tokens": 123456,
                    "max_output_tokens": 65432,
                    "max_tokens": 65432,
                    "supported_endpoints": ["/v1/chat/completions"],
                    "supports_function_calling": True,
                    "supports_reasoning": True,
                    "cache_read_input_token_cost": 2e-9,
                }
            }
        )
    )
    monkeypatch.setattr(model_info_manager, "get_metadata_sources", lambda: [str(metadata_file)])
    monkeypatch.setattr(model_info_manager, "get_model_info", lambda model: {})

    model = Model("custom/alpha")

    assert model.info["max_input_tokens"] == 123456
    assert model.info["mode"] == "chat"
    assert model.info["supports_function_calling"] is True
    assert model.caches_by_default is True
    assert model.use_temperature is False
    assert model.extra_params.get("parallel_tool_calls") is True


def test_custom_metadata_file_preferred_over_bundled(tmp_path):
    import importlib.resources

    custom = tmp_path / "custom-metadata.json"
    custom.write_text(json.dumps({"deepseek/deepseek-chat": {"max_input_tokens": 1234}}))
    bundled = str(importlib.resources.files("cecli.resources").joinpath("model-metadata.json"))

    config = get_default_config("deepseek/deepseek-chat", [bundled, str(custom)])

    assert config["llm"]["max_input_tokens"] == 1234


def test_bundled_fallback_when_custom_lacks_model(tmp_path):
    import importlib.resources

    custom = tmp_path / "custom-metadata.json"
    custom.write_text(json.dumps({"other/model": {"max_input_tokens": 1}}))
    bundled = str(importlib.resources.files("cecli.resources").joinpath("model-metadata.json"))

    config = get_default_config("gpt-5", [bundled, str(custom)])

    assert config["llm"]["litellm_provider"] == "openai"
    assert config["llm"]["max_input_tokens"] == 272000


def test_model_init_applies_reasoning_effort_chat(tmp_path, monkeypatch):
    from cecli.models import Model, model_info_manager

    metadata_file = tmp_path / "custom-metadata.json"
    metadata_file.write_text(
        json.dumps(
            {
                "chat/alpha": {
                    "litellm_provider": "chat",
                    "supported_endpoints": ["/v1/chat/completions"],
                    "supports_reasoning": True,
                }
            }
        )
    )
    monkeypatch.setattr(model_info_manager, "get_metadata_sources", lambda: [str(metadata_file)])
    monkeypatch.setattr(model_info_manager, "get_model_info", lambda model: {})

    model = Model("chat/alpha")

    assert model.extra_params["extra_body"]["reasoning_effort"] == "medium"
    assert "reasoning_effort" not in model.extra_params  # routed via extra_body
    assert "store" not in model.extra_params["extra_body"]
    assert "include" not in model.extra_params["extra_body"]
    assert model.get_reasoning_effort() == "medium"


def test_model_init_applies_reasoning_effort_responses(tmp_path, monkeypatch):
    from cecli.models import Model, model_info_manager

    metadata_file = tmp_path / "custom-metadata.json"
    metadata_file.write_text(
        json.dumps(
            {
                "resp/beta": {
                    "litellm_provider": "openai",
                    "supported_endpoints": ["/v1/responses"],
                    "supports_reasoning": True,
                }
            }
        )
    )
    monkeypatch.setattr(model_info_manager, "get_metadata_sources", lambda: [str(metadata_file)])
    monkeypatch.setattr(model_info_manager, "get_model_info", lambda model: {})

    model = Model("resp/beta")

    assert model.extra_params["extra_body"]["reasoning"] == {"effort": "medium"}
    assert model.extra_params["extra_body"]["store"] is False
    assert model.extra_params["extra_body"]["include"] == ["reasoning.encrypted_content"]
    assert model.get_reasoning_effort() == "medium"


def test_model_init_applies_thinking_for_anthropic(tmp_path, monkeypatch):
    from cecli.models import Model, model_info_manager

    metadata_file = tmp_path / "custom-metadata.json"
    metadata_file.write_text(
        json.dumps(
            {
                "anthropic/claude-x": {
                    "litellm_provider": "anthropic",
                    "supports_reasoning": True,
                }
            }
        )
    )
    monkeypatch.setattr(model_info_manager, "get_metadata_sources", lambda: [str(metadata_file)])
    monkeypatch.setattr(model_info_manager, "get_model_info", lambda model: {})

    model = Model("anthropic/claude-x")

    # Anthropic consumes the top-level ``thinking`` kwarg; it must not ride in
    # extra_body (which the API rejects as extra inputs).
    assert model.extra_params["thinking"] == {"type": "enabled", "budget_tokens": 2048}
    assert "thinking" not in model.extra_params.get("extra_body", {})
    assert model.get_thinking_tokens() == "2k"
    assert model.use_temperature is False


def test_model_init_no_reasoning_defaults(tmp_path, monkeypatch):
    from cecli.models import Model, model_info_manager

    metadata_file = tmp_path / "custom-metadata.json"
    metadata_file.write_text(json.dumps({"plain/gamma": {"litellm_provider": "custom"}}))
    monkeypatch.setattr(model_info_manager, "get_metadata_sources", lambda: [str(metadata_file)])
    monkeypatch.setattr(model_info_manager, "get_model_info", lambda model: {})

    model = Model("plain/gamma")

    assert "thinking" not in model.extra_params
    assert "extra_body" not in model.extra_params
    assert model.get_reasoning_effort() is None


def test_set_reasoning_effort_unsets():
    from cecli.models import Model

    model = Model("gpt-4")

    model.extra_params = {"extra_body": {"reasoning_effort": "high", "other": 1}}
    model.set_reasoning_effort("none")
    assert model.extra_params["extra_body"] == {"other": 1}

    model.extra_params = {"extra_body": {"reasoning": {"effort": "high"}, "other": 1}}
    model.set_reasoning_effort(None)
    assert model.extra_params["extra_body"] == {"other": 1}

    # The thinking form (max_tokens) is left intact.
    model.extra_params = {"extra_body": {"reasoning": {"max_tokens": 2048}}}
    model.set_reasoning_effort(None)
    assert model.extra_params["extra_body"] == {"reasoning": {"max_tokens": 2048}}


def test_model_init_override_reasoning_effort_wins(tmp_path, monkeypatch):
    from cecli.models import Model, model_info_manager

    metadata_file = tmp_path / "custom-metadata.json"
    metadata_file.write_text(
        json.dumps(
            {
                "chat/delta": {
                    "litellm_provider": "chat",
                    "supported_endpoints": ["/v1/chat/completions"],
                    "supports_reasoning": True,
                }
            }
        )
    )
    monkeypatch.setattr(model_info_manager, "get_metadata_sources", lambda: [str(metadata_file)])
    monkeypatch.setattr(model_info_manager, "get_model_info", lambda model: {})

    model = Model(
        "chat/delta",
        override_kwargs={"api": {"reasoning_effort": "high"}},
    )

    assert model.extra_params["extra_body"]["reasoning_effort"] == "high"


# ---------------------------------------------------------------------------
# Responses-mode rules (github_copilot gpt>5, meta provider)
# ---------------------------------------------------------------------------


def test_github_copilot_gpt_gt5_uses_responses():
    metadata = {
        "github_copilot/gpt-5.6-luna": _record(
            litellm_provider="github_copilot",
            supported_endpoints=["/v1/chat/completions"],
        )
    }
    config = get_default_config("github_copilot/gpt-5.6-luna", [metadata])

    assert config["llm"]["mode"] == "responses"
    assert config["llm"]["supported_endpoints"] == ["/v1/responses"]


def test_github_copilot_gpt_gt5_no_endpoints_still_responses():
    metadata = {
        "github_copilot/gpt-5.6-luna": _record(
            litellm_provider="github_copilot", supported_endpoints=None
        )
    }
    config = get_default_config("github_copilot/gpt-5.6-luna", [metadata])

    assert config["llm"]["mode"] == "responses"
    assert config["llm"]["supported_endpoints"] == ["/v1/responses"]


def test_github_copilot_gpt_mini_stays_chat():
    metadata = {
        "github_copilot/gpt-5.4-mini": _record(
            litellm_provider="github_copilot",
            supported_endpoints=["/v1/chat/completions"],
        )
    }
    config = get_default_config("github_copilot/gpt-5.4-mini", [metadata])

    assert config["llm"]["mode"] == "chat"
    assert config["llm"]["supported_endpoints"] == ["/v1/chat/completions"]


def test_github_copilot_gpt_below5_stays_chat():
    metadata = {
        "github_copilot/gpt-4.1": _record(
            litellm_provider="github_copilot",
            supported_endpoints=["/v1/chat/completions"],
        )
    }
    config = get_default_config("github_copilot/gpt-4.1", [metadata])

    assert config["llm"]["mode"] == "chat"
    assert config["llm"]["supported_endpoints"] == ["/v1/chat/completions"]


def test_meta_provider_uses_responses():
    metadata = {
        "meta/llama-4-maverick": _record(
            litellm_provider="meta", supported_endpoints=["/v1/chat/completions"]
        )
    }
    config = get_default_config("meta/llama-4-maverick", [metadata])

    assert config["llm"]["mode"] == "responses"
    assert config["llm"]["supported_endpoints"] == ["/v1/responses"]


def test_non_gpt_github_copilot_stays_chat():
    metadata = {
        "github_copilot/claude-sonnet-5": _record(
            litellm_provider="github_copilot",
            supported_endpoints=["/v1/chat/completions"],
        )
    }
    config = get_default_config("github_copilot/claude-sonnet-5", [metadata])

    assert config["llm"]["mode"] == "chat"


def test_adaptive_thinking_sets_use_temperature_false():
    record = _record(supports_reasoning=False, supports_adaptive_thinking=True)
    config = get_default_config("adaptive", [{"adaptive": record}])

    assert config["agent"]["use_temperature"] is False


def test_no_adaptive_thinking_keeps_temperature():
    record = _record(supports_reasoning=False, supported_endpoints=["/v1/chat/completions"])
    config = get_default_config("plain", [{"plain": record}])

    assert "use_temperature" not in config["agent"]


def test_provider_prefix_keeps_provider_on_family_fallback():
    """A provider-prefixed model must not fall through to a bare different-provider record."""
    metadata = {
        "github_copilot/gpt-5": _record(litellm_provider="github_copilot"),
        "gpt-5.6-luna": _record(litellm_provider="openai"),
    }
    config = get_default_config("github_copilot/gpt-5.6-luna", [metadata])

    assert config["llm"]["litellm_provider"] == "github_copilot"


def test_responses_mode_sets_temperature_and_store():
    responses = _record(
        supports_reasoning=False,
        supported_endpoints=["/v1/chat/completions", "/v1/responses"],
    )
    chat = _record(
        supports_reasoning=False,
        supported_endpoints=["/v1/chat/completions"],
    )

    resp_config = get_default_config("resp-model", [{"resp-model": responses}])
    chat_config = get_default_config("chat-model", [{"chat-model": chat}])

    assert resp_config["agent"]["use_temperature"] is False
    assert resp_config["api"]["extra_body"] == {
        "store": False,
        "include": ["reasoning.encrypted_content"],
    }

    assert "use_temperature" not in chat_config["agent"]
    assert "extra_body" not in chat_config["api"]


# ---------------------------------------------------------------------------
# Reasoning formatter helpers (format_reasoning)
# ---------------------------------------------------------------------------


def test_gemini_reasoning_formatter_lifts_to_top_level():
    config = get_default_config("gemini/gemini-3-pro-preview", [])

    formatter = config["helpers"]["format_reasoning"]
    extra_params = {"extra_body": {"reasoning_effort": "medium", "other": 1}}

    formatter(extra_params)

    assert extra_params["reasoning_effort"] == "medium"
    assert extra_params["extra_body"] == {"other": 1}


def test_unknown_reasoning_formatter_is_noop():
    config = get_default_config("unknown/model", [])

    formatter = config["helpers"]["format_reasoning"]
    extra_params = {"extra_body": {"reasoning_effort": "medium", "other": 1}}

    formatter(extra_params)

    assert extra_params["extra_body"] == {"reasoning_effort": "medium", "other": 1}
    assert "reasoning_effort" not in extra_params


def test_model_init_gemini_2_5_uses_thinking_budget(tmp_path, monkeypatch):
    from cecli.models import Model, model_info_manager

    metadata_file = tmp_path / "custom-metadata.json"
    metadata_file.write_text(
        json.dumps(
            {
                "gemini/gemini-2.5-flash": {
                    "litellm_provider": "gemini",
                    "supported_endpoints": ["/v1/chat/completions"],
                    "supports_reasoning": True,
                }
            }
        )
    )
    monkeypatch.setattr(model_info_manager, "get_metadata_sources", lambda: [str(metadata_file)])
    monkeypatch.setattr(model_info_manager, "get_model_info", lambda model: {})

    model = Model("gemini/gemini-2.5-flash")

    # Gemini 2.5 configures thinking via a token budget, exposed as litellm's
    # top-level ``thinking`` param (mapped to thinkingBudget + includeThoughts).
    assert model.extra_params["thinking"] == {
        "type": "enabled",
        "budget_tokens": 8192,
    }
    assert "thinking" not in model.extra_params.get("extra_body", {})
    assert "reasoning_effort" not in model.extra_params
    assert model.get_raw_thinking_tokens() == 8192


def test_model_init_gemini_3_uses_reasoning_effort(tmp_path, monkeypatch):
    from cecli.models import Model, model_info_manager

    metadata_file = tmp_path / "custom-metadata.json"
    metadata_file.write_text(
        json.dumps(
            {
                "gemini/gemini-3-pro-preview": {
                    "litellm_provider": "gemini",
                    "supported_endpoints": ["/v1/chat/completions"],
                    "supports_reasoning": True,
                }
            }
        )
    )
    monkeypatch.setattr(model_info_manager, "get_metadata_sources", lambda: [str(metadata_file)])
    monkeypatch.setattr(model_info_manager, "get_model_info", lambda model: {})

    model = Model("gemini/gemini-3-pro-preview")

    # Gemini 3 uses thinking_level; litellm maps the top-level reasoning_effort
    # kwarg onto thinkingConfig.thinkingLevel.
    assert model.extra_params["reasoning_effort"] == "medium"
    assert "reasoning_effort" not in model.extra_params.get("extra_body", {})
    assert model.get_reasoning_effort() == "medium"


def test_gemini_thinking_formatter_lifts_to_top_level():
    config = get_default_config("gemini/gemini-2.5-flash", [])

    formatter = config["helpers"]["format_thinking"]
    extra_params = {
        "extra_body": {
            "thinking": {"type": "enabled", "budget_tokens": 8192},
            "other": 1,
        }
    }

    formatter(extra_params)

    assert extra_params["thinking"] == {"type": "enabled", "budget_tokens": 8192}
    assert extra_params["extra_body"] == {"other": 1}


def test_unknown_thinking_formatter_is_noop():
    config = get_default_config("unknown/model", [])

    formatter = config["helpers"]["format_thinking"]
    extra_params = {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": 2048}}}

    formatter(extra_params)

    assert extra_params["extra_body"]["thinking"] == {
        "type": "enabled",
        "budget_tokens": 2048,
    }
    assert "thinking" not in extra_params


def test_anthropic_thinking_formatter_lifts_to_top_level():
    config = get_default_config("anthropic/claude-opus-4-7", [])

    formatter = config["helpers"]["format_thinking"]
    extra_params = {
        "extra_body": {
            "thinking": {"type": "enabled", "budget_tokens": 2048},
            "other": 1,
        }
    }

    formatter(extra_params)

    assert extra_params["thinking"] == {"type": "enabled", "budget_tokens": 2048}
    # Anthropic does not accept extra_body at all, so it is dropped entirely.
    assert "extra_body" not in extra_params


def test_bare_claude_thinking_formatter_lifts_to_top_level():
    config = get_default_config("claude-opus-4-7", [])

    formatter = config["helpers"]["format_thinking"]
    extra_params = {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": 2048}}}

    formatter(extra_params)

    assert extra_params["thinking"] == {"type": "enabled", "budget_tokens": 2048}
    assert "extra_body" not in extra_params


# ---------------------------------------------------------------------------
# Claude 5+ adaptive thinking (reasoning_effort instead of thinking budget)
# ---------------------------------------------------------------------------


def test_claude_5_uses_reasoning_effort_not_thinking():
    metadata = {
        "anthropic/claude-opus-5": _record(
            litellm_provider="anthropic", supported_endpoints=["/v1/messages"]
        )
    }
    config = get_default_config("anthropic/claude-opus-5", [metadata])

    assert "thinking" not in config["api"]
    assert config["api"]["reasoning_effort"] == "medium"


def test_anthropic_reasoning_formatter_lifts_to_top_level():
    config = get_default_config("anthropic/claude-opus-5", [])

    formatter = config["helpers"]["format_reasoning"]
    extra_params = {"extra_body": {"reasoning_effort": "medium", "other": 1}}

    formatter(extra_params)

    assert extra_params["reasoning_effort"] == "medium"
    assert "extra_body" not in extra_params


def test_claude_5_thinking_formatter_removes_thinking():
    config = get_default_config("anthropic/claude-opus-5", [])

    formatter = config["helpers"]["format_thinking"]
    extra_params = {
        "thinking": {"type": "enabled", "budget_tokens": 2048},
        "extra_body": {"thinking": {"type": "enabled", "budget_tokens": 2048}},
    }

    formatter(extra_params)

    assert "thinking" not in extra_params
    assert "extra_body" not in extra_params


def test_model_init_claude_5_uses_reasoning_effort(tmp_path, monkeypatch):
    from cecli.models import Model, model_info_manager

    metadata_file = tmp_path / "custom-metadata.json"
    metadata_file.write_text(
        json.dumps(
            {
                "anthropic/claude-opus-5": {
                    "litellm_provider": "anthropic",
                    "supported_endpoints": ["/v1/messages"],
                    "supports_reasoning": True,
                }
            }
        )
    )
    monkeypatch.setattr(model_info_manager, "get_metadata_sources", lambda: [str(metadata_file)])
    monkeypatch.setattr(model_info_manager, "get_model_info", lambda model: {})

    model = Model("anthropic/claude-opus-5")

    # Claude 5+ uses adaptive thinking via reasoning_effort: litellm maps the
    # top-level param to thinking.type.adaptive + output_config.effort.
    assert model.extra_params["reasoning_effort"] == "medium"
    assert "thinking" not in model.extra_params
    assert "extra_body" not in model.extra_params
    assert model.get_reasoning_effort() == "medium"
