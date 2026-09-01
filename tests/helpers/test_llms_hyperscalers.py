"""Offline tests for the Azure / Bedrock / Bedrock Mantle providers.

No live cloud credentials: request construction (URL, headers, query params,
SigV4-signed payloads) is asserted against fixtures, and the response
normalization is checked against representative provider payloads.
"""

from __future__ import annotations

import asyncio

import cecli.helpers.llms.domains.chat as chat_domain
from cecli.helpers.llms.config import resolve_model_config
from cecli.helpers.llms.domains.bedrock import (
    bedrock_endpoint,
    bedrock_payload,
    normalize_bedrock_response,
)
from cecli.helpers.llms.providers import get_provider_adapter
from cecli.helpers.llms.providers.azure import AzureProvider
from cecli.helpers.llms.providers.bedrock import BedrockProvider
from cecli.helpers.llms.providers.bedrock_mantle import BedrockMantleProvider

# ---------------------------------------------------------------------------
# Adapter registration + auth helpers
# ---------------------------------------------------------------------------


def test_adapters_auto_registered():
    assert get_provider_adapter("azure").provider == "azure"
    assert get_provider_adapter("bedrock").provider == "bedrock"
    assert get_provider_adapter("bedrock_mantle").provider == "bedrock_mantle"


def test_azure_build_headers_uses_api_key_header():
    adapter = AzureProvider()
    headers = adapter.build_headers({}, "sk-azure", "chat", {})
    assert headers["api-key"] == "sk-azure"
    assert "Authorization" not in headers


def test_azure_resolve_api_key_env(monkeypatch):
    monkeypatch.setenv("AZURE_API_KEY", "key1")
    assert AzureProvider().resolve_api_key({}, None) == "key1"

    monkeypatch.delenv("AZURE_API_KEY")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "key2")
    assert AzureProvider().resolve_api_key({}, None) == "key2"


def test_bedrock_provider_region_substitution(monkeypatch):
    monkeypatch.setenv("AWS_REGION_NAME", "eu-west-1")
    resolved = {"api_base": "https://bedrock-runtime.{region}.amazonaws.com"}
    base = BedrockProvider().resolve_api_base(resolved)
    assert base == "https://bedrock-runtime.eu-west-1.amazonaws.com"
    assert resolved["aws_region"] == "eu-west-1"


def test_bedrock_mantle_region_substitution():
    resolved = {"api_base": "https://bedrock-mantle.{region}.api.aws/v1"}
    base = BedrockMantleProvider().resolve_api_base(resolved)
    assert base == "https://bedrock-mantle.us-east-1.api.aws/v1"
    assert resolved["aws_region"] == "us-east-1"


# ---------------------------------------------------------------------------
# Bedrock Converse wire
# ---------------------------------------------------------------------------


def test_bedrock_payload_messages_and_tools():
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "What is 2+2?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "function": {"name": "add", "arguments": '{"a": 2, "b": 2}'}}
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "4"},
        {"role": "user", "content": "Thanks!"},
    ]
    tools = [
        {
            "function": {
                "name": "add",
                "description": "Add two numbers",
                "parameters": {"type": "object"},
            }
        }
    ]
    payload = bedrock_payload(
        {"extra_body": {}}, messages, tools, {"max_tokens": 64, "temperature": 0.5}
    )

    assert payload["system"] == [{"text": "You are helpful."}]
    assert payload["messages"][0] == {"role": "user", "content": [{"text": "What is 2+2?"}]}
    assert payload["messages"][1]["content"][0]["toolUse"]["toolUseId"] == "call_1"
    assert payload["messages"][1]["content"][0]["toolUse"]["input"] == {"a": 2, "b": 2}
    assert payload["messages"][2]["content"][0]["toolResult"]["toolUseId"] == "call_1"
    assert payload["messages"][2]["content"][0]["toolResult"]["content"] == [{"text": "4"}]
    assert payload["inferenceConfig"] == {"maxTokens": 64, "temperature": 0.5}
    assert payload["toolConfig"]["tools"][0]["toolSpec"]["name"] == "add"


def test_bedrock_payload_user_content_list_blocks():
    messages = [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]
    payload = bedrock_payload({"extra_body": {}}, messages, None, {})
    assert payload["messages"] == [{"role": "user", "content": [{"text": "hello"}]}]


def test_normalize_bedrock_response_text_and_tool_use():
    data = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {"text": "Let me compute."},
                    {"toolUse": {"toolUseId": "call_1", "name": "add", "input": {"a": 2, "b": 2}}},
                ],
            }
        },
        "stopReason": "tool_use",
        "usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15},
    }
    resp = normalize_bedrock_response(data, "bedrock/m")
    assert resp.choices[0].finish_reason == "tool_calls"
    assert resp.choices[0].message.content == "Let me compute."
    assert len(resp.choices[0].message.tool_calls) == 1
    assert resp.choices[0].message.tool_calls[0].name == "add"
    assert resp.choices[0].message.tool_calls[0].arguments == {"a": 2, "b": 2}
    assert resp.usage.prompt_tokens == 10
    assert resp.usage.completion_tokens == 5


def test_normalize_bedrock_response_stop_reason_mapping():
    resp = normalize_bedrock_response(
        {"output": {"message": {"content": [{"text": "done"}]}}, "stopReason": "end_turn"},
        "bedrock/m",
    )
    assert resp.choices[0].finish_reason == "stop"
    assert resp.choices[0].message.content == "done"


def test_bedrock_endpoint_requires_region():
    try:
        bedrock_endpoint({"route": "m"})
    except ValueError as exc:
        assert "region" in str(exc)
    else:
        raise AssertionError("expected ValueError without a region")


# ---------------------------------------------------------------------------
# Chat-family wiring: signer hook + extra_query
# ---------------------------------------------------------------------------


class _FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {
            "id": "x",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "hi"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
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

    def stream(self, *args, **kwargs):
        raise NotImplementedError


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_chat_domain_passes_extra_query_params(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(chat_domain, "make_client", lambda *a, **k: client)
    resolved = {
        "api_base": "https://res.openai.azure.com/openai/deployments/gpt-4o",
        "model": "azure/m",
        "route": "m",
        "extra_query": {"api-version": "2024-10-21"},
    }
    _run(
        chat_domain.chat_complete(
            resolved, [{"role": "user", "content": "hi"}], None, "key", {}, {}
        )
    )
    call = client.calls[0]
    assert call["url"] == "https://res.openai.azure.com/openai/deployments/gpt-4o/chat/completions"
    assert call["params"] == {"api-version": "2024-10-21"}


def test_chat_domain_invokes_signer(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(chat_domain, "make_client", lambda *a, **k: client)

    def signer(url, payload, headers, key):
        return url, {"Authorization": "AWS4-HMAC-SHA256 ..."}, b"{}"

    resolved = {
        "api_base": "https://bedrock-mantle.us-east-1.api.aws/v1",
        "model": "bedrock_mantle/m",
        "route": "m",
        "_signer": signer,
    }
    _run(
        chat_domain.chat_complete(resolved, [{"role": "user", "content": "hi"}], None, None, {}, {})
    )
    call = client.calls[0]
    assert call["content"] == b"{}"
    assert call["headers"]["Authorization"].startswith("AWS4-HMAC-SHA256")


def test_pipeline_azure_wires_api_key_and_version(monkeypatch):
    import cecli.helpers.llms.pipeline as pipeline

    client = _FakeClient()
    monkeypatch.setattr(chat_domain, "make_client", lambda *a, **k: client)
    monkeypatch.setenv("AZURE_API_KEY", "sk-azure")

    _run(
        pipeline.acompletion(
            "azure/deployment-model",
            [{"role": "user", "content": "hi"}],
            api_base="https://myres.openai.azure.com/openai/deployments/gpt-4o",
        )
    )
    call = client.calls[0]
    assert (
        call["url"] == "https://myres.openai.azure.com/openai/deployments/gpt-4o/chat/completions"
    )
    assert call["headers"]["api-key"] == "sk-azure"
    assert "Authorization" not in call["headers"]
    assert call["params"] == {"api-version": "2024-10-21"}


def test_pipeline_bedrock_mantle_sigv4(monkeypatch):
    import cecli.helpers.llms.pipeline as pipeline

    client = _FakeClient()
    monkeypatch.setattr(chat_domain, "make_client", lambda *a, **k: client)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKID")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "SECRET")

    _run(
        pipeline.acompletion(
            "bedrock_mantle/claude-sonnet-4",
            [{"role": "user", "content": "hi"}],
            api_base="https://bedrock-mantle.us-east-1.api.aws/v1",
        )
    )
    call = client.calls[0]
    assert call["url"] == "https://bedrock-mantle.us-east-1.api.aws/v1/chat/completions"
    assert call["headers"]["Authorization"].startswith("AWS4-HMAC-SHA256")
    assert call["content"] is not None  # signed body bytes
    assert call["headers"]["host"] == "bedrock-mantle.us-east-1.api.aws"


def test_pipeline_bedrock_mantle_bearer_when_token_set(monkeypatch):
    import cecli.helpers.llms.pipeline as pipeline

    client = _FakeClient()
    monkeypatch.setattr(chat_domain, "make_client", lambda *a, **k: client)
    monkeypatch.setenv("BEDROCK_MANTLE_API_KEY", "bearer-token")

    _run(
        pipeline.acompletion(
            "bedrock_mantle/claude-sonnet-4",
            [{"role": "user", "content": "hi"}],
            api_base="https://bedrock-mantle.us-east-1.api.aws/v1",
        )
    )
    call = client.calls[0]
    assert call["headers"]["Authorization"] == "Bearer bearer-token"


def test_resolve_model_config_surfaces_extra_query():
    resolved = resolve_model_config("azure/sample-model")
    assert resolved["extra_query"] == {"api-version": "2024-10-21"}


def test_resolve_model_config_bedrock_claude_maps_to_bedrock():
    """Hyphenated/newer claude names under ``bedrock/`` must route through the
    bedrock provider (SigV4 Converse wire) instead of falling back to the bare
    anthropic record (e.g. ``bedrock/claude-sonnet-5``)."""
    resolved = resolve_model_config("bedrock/claude-sonnet-5")

    assert resolved["provider"] == "bedrock"
    assert resolved["family"] == "bedrock"
    assert resolved["api_key_env"] == "AWS_ACCESS_KEY_ID"


def test_resolve_model_config_bedrock_mantle_claude_maps_to_bedrock_mantle():
    """Newer claude names under ``bedrock_mantle/`` route through the mantle
    provider (OpenAI-compatible chat wire with SigV4/Bearer) instead of the
    bare anthropic record."""
    resolved = resolve_model_config("bedrock_mantle/claude-sonnet-5")

    assert resolved["provider"] == "bedrock_mantle"
    assert resolved["family"] == "chat"
    assert resolved["api_key_env"] == "BEDROCK_MANTLE_API_KEY"


def test_resolve_model_config_openrouter_claude_maps_to_openrouter():
    """Anthropic models hosted on a third-party backend authenticate against
    THAT provider and speak its chat completions wire, not the anthropic
    messages API (e.g. ``openrouter/claude-sonnet-5``)."""
    resolved = resolve_model_config("openrouter/claude-sonnet-5")

    assert resolved["provider"] == "openrouter"
    assert resolved["family"] == "chat"
    assert resolved["api_key_env"] == "OPENROUTER_API_KEY"


def test_resolve_model_config_deepseek_claude_maps_to_deepseek():
    """Same provider-sensitive claude rule for deepseek."""
    resolved = resolve_model_config("deepseek/claude-sonnet-5")

    assert resolved["provider"] == "deepseek"
    assert resolved["family"] == "chat"
    assert resolved["api_key_env"] == "DEEPSEEK_API_KEY"


def test_resolve_model_config_anthropic_claude_stays_anthropic_messages():
    """Native anthropic claude models keep the anthropic provider and the
    /v1/messages wire (the override applies only to non-anthropic prefixes)."""
    resolved = resolve_model_config("anthropic/claude-sonnet-5")

    assert resolved["provider"] == "anthropic"
    assert resolved["family"] == "messages"
    assert resolved["api_key_env"] == "ANTHROPIC_API_KEY"
