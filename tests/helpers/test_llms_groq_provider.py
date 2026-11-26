"""Tests for the Groq provider adapter.

Groq's chat-completions endpoint rejects unknown body properties, including the
``prompt_cache_key`` the shared OpenAI-compatible payload builder forwards. The
adapter must drop it for both streaming and non-streaming requests.
"""

from cecli.helpers.llms.providers import ProviderAdapter, get_provider_adapter
from cecli.helpers.llms.providers.groq import GroqProvider

MESSAGES = [{"role": "user", "content": "hi"}]
RESOLVED = {
    "route": "openai/gpt-oss-120b",
    "api_block": {},
    "_echo_reasoning_content": True,
}


def test_groq_is_registered():
    adapter = get_provider_adapter("groq")

    assert isinstance(adapter, GroqProvider)
    assert isinstance(adapter, ProviderAdapter)


def test_payload_omits_prompt_cache_key():
    payload = GroqProvider().chat_payload(
        RESOLVED,
        MESSAGES,
        None,
        False,
        {"prompt_cache_key": "session-1", "temperature": 0.2},
    )

    assert "prompt_cache_key" not in payload
    assert payload["temperature"] == 0.2
    assert payload["model"] == "openai/gpt-oss-120b"
    assert payload["messages"] == MESSAGES
    assert payload["stream"] is False


def test_stream_payload_omits_prompt_cache_key():
    payload = GroqProvider().chat_payload(
        RESOLVED,
        MESSAGES,
        None,
        True,
        {"prompt_cache_key": "session-1"},
    )

    assert "prompt_cache_key" not in payload
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}


def test_payload_omits_prompt_cache_key_from_extra_body():
    payload = GroqProvider().chat_payload(
        RESOLVED,
        MESSAGES,
        None,
        False,
        {"extra_body": {"prompt_cache_key": "session-1"}},
    )

    assert "prompt_cache_key" not in payload


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


def test_pipeline_groq_request_body_omits_prompt_cache_key(monkeypatch):
    import asyncio

    import cecli.helpers.llms.domains.chat as chat_domain
    from cecli.helpers.llms import pipeline

    client = _FakeClient()
    monkeypatch.setattr(chat_domain, "make_client", lambda *a, **k: client)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")

    asyncio.run(
        pipeline.acompletion(
            model="groq/openai/gpt-oss-120b",
            messages=MESSAGES,
            prompt_cache_key="session-1",
        )
    )

    body = client.calls[0]["json"]

    assert "prompt_cache_key" not in body
    assert body["model"] == "openai/gpt-oss-120b"
    assert client.calls[0]["url"] == "https://api.groq.com/openai/v1/chat/completions"
