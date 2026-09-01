"""api_base / base_url override tests for the llms package.

Mirrors litellm's ``api_base`` override: a per-request ``api_base`` kwarg (via
the shim or directly on ``pipeline.acompletion``) overrides the provider's
default endpoint, ``{PROVIDER}_API_BASE`` env vars override globally at config
resolution, and each family adapter builds its request URL from the resolved
base. No network: the family adapter / package dispatch are monkeypatched.
"""

import asyncio
import json

import cecli.helpers.llms as llms_pkg
import cecli.helpers.llms.pipeline as pipeline
from cecli.helpers.llms.config import resolve_model_config
from cecli.helpers.llms.litellm_compat import litellm
from cecli.helpers.llms.types import Choice, CompletionResponse, Message

MSGS = [{"role": "user", "content": "hi"}]


def _fake_response(model):
    return CompletionResponse(
        id="x",
        model=model,
        choices=[Choice(index=0, message=Message(role="assistant", content="hi"))],
    )


# ---------------------------------------------------------------------------
# Config-level precedence
# ---------------------------------------------------------------------------


def test_default_api_base_from_provider_defaults():
    resolved = resolve_model_config("deepseek/deepseek-v4-flash")
    assert resolved["api_base"] == "https://api.deepseek.com/v1"


def test_env_api_base_overrides_default(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_BASE", "https://env.example.com/v1")
    resolved = resolve_model_config("deepseek/deepseek-v4-flash")
    assert resolved["api_base"] == "https://env.example.com/v1"


def test_env_api_base_trailing_slash_stripped(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_BASE", "https://env.example.com/v1/")
    resolved = resolve_model_config("deepseek/deepseek-v4-flash")
    assert resolved["api_base"] == "https://env.example.com/v1"


def test_configured_provider_prefix_wins_over_metadata_record():
    """A user-configured provider (model-providers) overrides a metadata record.

    ``bifrost/gemini/gemini-2.5-pro`` collides with the bundled
    ``gemini/gemini-2.5-pro`` record (``litellm_provider: gemini``); because
    ``bifrost`` is a configured provider, it must route through bifrost's
    api_base on the chat wire instead of the native gemini family.
    """
    from cecli.helpers.model_providers import PROVIDER_CONFIGS, ModelProviderManager

    # Without the provider configured, the colliding route stays native gemini.
    baseline = resolve_model_config("bifrost/gemini/gemini-2.5-pro")

    assert baseline["provider"] == "gemini"
    assert baseline["family"] == "gemini"

    original = dict(PROVIDER_CONFIGS)

    try:
        ModelProviderManager().merge_provider_configs(
            {
                "bifrost": {
                    "api_base": "http://localhost:8090/v1",
                    "requires_api_key": False,
                    "display_name": "bifrost",
                    "models_url": "http://localhost:8090/v1/models",
                }
            }
        )

        resolved = resolve_model_config("bifrost/gemini/gemini-2.5-pro")

        assert resolved["provider"] == "bifrost"
        assert resolved["family"] == "chat"
        assert resolved["api_base"] == "http://localhost:8090/v1"
        assert resolved["api_key_env"] is None
    finally:
        PROVIDER_CONFIGS.clear()
        PROVIDER_CONFIGS.update(original)


# ---------------------------------------------------------------------------
# Per-request override via the pipeline
# ---------------------------------------------------------------------------


def test_pipeline_api_base_override_reaches_adapter(monkeypatch):
    """pipeline.acompletion(api_base=...) overrides the resolved base (rstripped)."""
    captured = {}

    async def fake_chat_complete(resolved, messages, tools, key, headers, kwargs):
        captured["api_base"] = resolved["api_base"]
        captured["family"] = resolved["family"]
        return _fake_response(resolved["model"])

    monkeypatch.setattr(pipeline, "chat_complete", fake_chat_complete)

    asyncio.run(
        pipeline.acompletion(
            model="deepseek/deepseek-v4-flash",
            messages=MSGS,
            api_base="https://my-proxy.example.com/v1/",
        )
    )

    assert captured["api_base"] == "https://my-proxy.example.com/v1"
    assert captured["family"] == "chat"


def test_pipeline_without_api_base_uses_default(monkeypatch):
    captured = {}

    async def fake_chat_complete(resolved, messages, tools, key, headers, kwargs):
        captured["api_base"] = resolved["api_base"]
        return _fake_response(resolved["model"])

    monkeypatch.setattr(pipeline, "chat_complete", fake_chat_complete)

    asyncio.run(pipeline.acompletion(model="deepseek/deepseek-v4-flash", messages=MSGS))

    assert captured["api_base"] == "https://api.deepseek.com/v1"


# ---------------------------------------------------------------------------
# Shim forwarding
# ---------------------------------------------------------------------------


def test_shim_forwards_api_base_to_dispatch(monkeypatch):
    """litellm.acompletion(api_base=...) reaches the package dispatch."""
    captured = {}

    async def fake_dispatch(**kwargs):
        captured.update(kwargs)
        return _fake_response(kwargs.get("model"))

    monkeypatch.setattr(llms_pkg, "acompletion", fake_dispatch)

    asyncio.run(
        litellm.acompletion(
            model="deepseek/deepseek-v4-flash",
            messages=MSGS,
            stream=False,
            api_base="https://my-proxy.example.com/v1",
        )
    )

    assert captured.get("api_base") == "https://my-proxy.example.com/v1"


# ---------------------------------------------------------------------------
# Request-time OPENAI_API_BASE / OPENAI_API_KEY override
# (docs/llms/openai-compat.md)
# ---------------------------------------------------------------------------


class _FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "id": "x",
            "model": "m",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}}],
            "usage": {},
        }


class _FakeClient:
    def __init__(self):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return _FakeResponse()

    def stream(self, method, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self

    def raise_for_status(self):
        return None

    async def aiter_lines(self):
        yield "data: " + json.dumps(
            {
                "id": "x",
                "choices": [{"index": 0, "delta": {"content": "hi"}, "finish_reason": "stop"}],
            }
        )
        yield "data: [DONE]"


def test_chat_domain_openai_api_base_overrides_request_url(monkeypatch):
    import cecli.helpers.llms.domains.chat as chat_domain

    client = _FakeClient()
    monkeypatch.setattr(chat_domain, "make_client", lambda *a, **k: client)
    monkeypatch.setenv("OPENAI_API_BASE", "https://my-proxy.example.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key")

    resolved = resolve_model_config("deepseek/deepseek-v4-flash")

    asyncio.run(
        chat_domain.chat_complete(
            resolved,
            MSGS,
            None,
            "sk-deepseek",
            {"Authorization": "Bearer sk-deepseek"},
            {},
        )
    )

    call = client.calls[0]
    assert call["url"] == "https://my-proxy.example.com/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer sk-env-key"


def test_chat_domain_malformed_openai_api_base_ignored(monkeypatch):
    import cecli.helpers.llms.domains.chat as chat_domain

    client = _FakeClient()
    monkeypatch.setattr(chat_domain, "make_client", lambda *a, **k: client)
    monkeypatch.setenv("OPENAI_API_BASE", "localhost:8000")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key")

    resolved = resolve_model_config("deepseek/deepseek-v4-flash")

    asyncio.run(
        chat_domain.chat_complete(
            resolved,
            MSGS,
            None,
            "sk-deepseek",
            {"Authorization": "Bearer sk-deepseek"},
            {},
        )
    )

    call = client.calls[0]
    assert call["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer sk-deepseek"


def test_chat_domain_stream_uses_openai_api_base(monkeypatch):
    import cecli.helpers.llms.domains.chat as chat_domain

    client = _FakeClient()
    monkeypatch.setattr(chat_domain, "make_client", lambda *a, **k: client)
    monkeypatch.setenv("OPENAI_API_BASE", "https://my-proxy.example.com/v1/")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key")

    resolved = resolve_model_config("deepseek/deepseek-v4-flash")

    async def collect():
        out = []

        async for chunk in chat_domain.chat_stream(
            resolved,
            MSGS,
            None,
            "sk-deepseek",
            {"Authorization": "Bearer sk-deepseek"},
            {},
        ):
            out.append(chunk)

        return out

    asyncio.run(collect())

    call = client.calls[0]
    assert call["url"] == "https://my-proxy.example.com/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer sk-env-key"


def test_pipeline_openai_env_overrides_chat_request(monkeypatch):
    import cecli.helpers.llms.domains.chat as chat_domain

    client = _FakeClient()
    monkeypatch.setattr(chat_domain, "make_client", lambda *a, **k: client)
    monkeypatch.setenv("OPENAI_API_BASE", "https://my-proxy.example.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek")

    asyncio.run(pipeline.acompletion(model="deepseek/deepseek-v4-flash", messages=MSGS))

    call = client.calls[0]
    assert call["url"] == "https://my-proxy.example.com/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer sk-env-key"
