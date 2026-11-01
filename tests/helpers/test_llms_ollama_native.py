"""Ollama native /api/chat wire tests.

Ollama's OpenAI-compatible ``/v1/chat/completions`` endpoint ignores runner
options such as ``num_ctx`` (and ``keep_alive``), so Ollama is implemented as a
provider adapter that keeps the shared ``chat`` family but overrides its chat
hooks to speak the native ``/api/chat`` wire (options under ``options``). These
tests lock in:

- ``ollama`` / ``ollama_chat`` resolve to the ``chat`` family but their own
  provider adapter
- the native base/URL and payload mapping (api-block params -> ``options``)
- native responses/chunks normalize into the shared cecli types
- the litellm shim forwards extra params instead of dropping them

No network: the payload builders, normalizers and URL/body construction are
exercised offline.
"""

import asyncio
from unittest.mock import patch

import cecli.helpers.llms as llms_pkg
from cecli.helpers.llms.config import resolve_model_config
from cecli.helpers.llms.domains.chat import chat_complete
from cecli.helpers.llms.litellm_compat import litellm
from cecli.helpers.llms.providers import get_provider_adapter
from cecli.helpers.llms.providers.ollama import (
    OllamaChatProvider,
    OllamaProvider,
    normalize_ollama_response,
    ollama_native_base,
    ollama_payload,
    parse_ollama_chunk,
)
from cecli.helpers.llms.types import CompletionResponse

MSGS = [{"role": "user", "content": "hi"}]


def test_ollama_providers_use_chat_family_with_dedicated_adapters():
    for slug, adapter_type in (("ollama", OllamaProvider), ("ollama_chat", OllamaChatProvider)):
        resolved = resolve_model_config(f"{slug}/llama3")

        assert resolved["family"] == "chat"
        assert resolved["provider"] == slug
        assert isinstance(get_provider_adapter(slug), adapter_type)


def test_native_base_strips_openai_compat_suffix():
    assert ollama_native_base("http://localhost:11434/v1") == "http://localhost:11434"
    assert ollama_native_base("http://host:1234/") == "http://host:1234"
    assert ollama_native_base(None) == "http://localhost:11434"


def test_payload_maps_api_params_to_native_fields():
    resolved = resolve_model_config("ollama_chat/llama3")
    payload = ollama_payload(
        resolved,
        MSGS,
        None,
        False,
        {"num_ctx": 57000, "keep_alive": -1, "temperature": 0, "max_tokens": 4096},
    )
    assert payload["model"] == "llama3"
    assert payload["options"] == {"temperature": 0, "num_ctx": 57000, "num_predict": 4096}
    assert payload["keep_alive"] == -1
    assert "max_tokens" not in payload
    assert "stream" not in payload["options"]


def test_payload_drops_control_kwargs():
    resolved = resolve_model_config("ollama_chat/llama3")
    payload = ollama_payload(
        resolved,
        MSGS,
        None,
        False,
        {
            "custom_llm_provider": "ollama_chat",
            "base_url": "http://ignored/v1",
            "drop_params": True,
            "allowed_openai_params": ["tools"],
            "parallel_tool_calls": True,
            "num_ctx": 123,
        },
    )
    assert payload["options"] == {"num_ctx": 123}


def test_payload_maps_reasoning_effort_to_think():
    resolved = resolve_model_config("ollama_chat/llama3")

    def think(effort=None, thinking=None):
        kwargs = {}

        if effort is not None:
            kwargs["reasoning_effort"] = effort

        if thinking is not None:
            kwargs["thinking"] = thinking

        return ollama_payload(resolved, MSGS, None, False, kwargs).get("think")

    assert think(effort="low") == "low"
    assert think(effort="medium") == "medium"
    assert think(effort="high") == "high"
    assert think(effort="max") == "high"
    assert think(effort="none") is False
    assert think(effort="minimal") is None
    assert think(thinking={"type": "enabled", "budget_tokens": 1024}) is True
    assert think(thinking={"type": "disabled"}) is False
    assert think(thinking=False) is False
    assert think(thinking="high") == "high"


def test_native_messages_carry_reasoning_and_tool_calls():
    resolved = resolve_model_config("ollama_chat/llama3")
    messages = [
        {
            "role": "assistant",
            "content": "ok",
            "reasoning_content": "why",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "f", "arguments": '{"a": 1}'},
                }
            ],
        },
        {"role": "tool", "content": "1", "tool_call_id": "call_1"},
    ]
    payload = ollama_payload(resolved, messages, None, False, {})
    assistant = payload["messages"][0]
    assert assistant["thinking"] == "why"
    assert assistant["tool_calls"] == [{"function": {"name": "f", "arguments": {"a": 1}}}]
    assert payload["messages"][1]["tool_call_id"] == "call_1"


def test_normalize_response_and_chunk_usage():
    data = {
        "message": {"role": "assistant", "content": "hi", "thinking": "t"},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 3,
        "eval_count": 1,
    }
    response = normalize_ollama_response(data, "ollama_chat/llama3")
    assert response.text == "hi"
    assert response.reasoning == "t"
    assert response.usage.total_tokens == 4

    chunk = parse_ollama_chunk({"message": {"role": "assistant", "content": "x"}, "done": False})
    assert chunk.text == "x"
    assert chunk.finish_reason is None

    final = parse_ollama_chunk(
        {
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 2,
            "eval_count": 0,
        }
    )
    assert final.finish_reason == "stop"
    assert final.usage.prompt_tokens == 2


def test_streamed_parallel_tool_calls_keep_distinct_indices():
    adapter = get_provider_adapter("ollama_chat")
    first = adapter.parse_chat_chunk(
        {"message": {"content": "", "tool_calls": [{"function": {"name": "a", "arguments": {}}}]}}
    )
    second = adapter.parse_chat_chunk(
        {
            "message": {
                "content": "",
                "tool_calls": [{"function": {"name": "b", "arguments": {}}}],
            },
            "done": True,
        }
    )

    assert [tc.id for tc in first.tool_calls] == ["call_0"]
    assert [tc.id for tc in second.tool_calls] == ["call_1"]
    assert [tc.index for tc in second.tool_calls] == [1]


def test_parallel_tool_calls_in_one_chunk_get_distinct_indices():
    adapter = get_provider_adapter("ollama_chat")
    chunk = adapter.parse_chat_chunk(
        {
            "message": {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "a", "arguments": {}}},
                    {"function": {"name": "b", "arguments": {}}},
                ],
            }
        }
    )

    assert [tc.index for tc in chunk.tool_calls] == [0, 1]
    assert [tc.id for tc in chunk.tool_calls] == ["call_0", "call_1"]


def test_chat_domain_posts_to_native_endpoint_via_provider():
    resolved = resolve_model_config("ollama_chat/llama3")
    resolved["_provider"] = get_provider_adapter("ollama_chat")
    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"role": "assistant", "content": "hi"}, "done": True}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, params=None, json=None):
            captured["url"] = url
            captured["json"] = json
            return _Resp()

    with patch("cecli.helpers.llms.domains.chat.make_client", return_value=_Client()):
        response = asyncio.run(chat_complete(resolved, MSGS, None, None, {}, {"num_ctx": 57000}))

    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["json"]["options"] == {"num_ctx": 57000}
    assert response.text == "hi"


def test_shim_forwards_extra_params(monkeypatch):
    captured = {}

    async def fake_dispatch(**kwargs):
        captured.update(kwargs)
        return CompletionResponse(model=kwargs.get("model"))

    monkeypatch.setattr(llms_pkg, "acompletion", fake_dispatch)

    asyncio.run(
        litellm.acompletion(
            model="ollama_chat/llama3",
            messages=MSGS,
            stream=False,
            num_ctx=57000,
            keep_alive=-1,
            top_p=0.9,
            drop_params=True,
            base_url="http://ignored/v1",
        )
    )
    assert captured["num_ctx"] == 57000
    assert captured["keep_alive"] == -1
    assert captured["top_p"] == 0.9
    assert "drop_params" not in captured
    assert "base_url" not in captured


def test_shim_keeps_narrow_passthrough_for_non_ollama(monkeypatch):
    captured = {}

    async def fake_dispatch(**kwargs):
        captured.update(kwargs)
        return CompletionResponse(model=kwargs.get("model"))

    monkeypatch.setattr(llms_pkg, "acompletion", fake_dispatch)

    asyncio.run(
        litellm.acompletion(
            model="openai/gpt-4o",
            messages=MSGS,
            stream=False,
            temperature=0.5,
            top_p=0.9,
            num_ctx=57000,
            keep_alive=-1,
            drop_params=True,
            base_url="http://ignored/v1",
        )
    )
    assert captured["temperature"] == 0.5
    assert "top_p" not in captured
    assert "num_ctx" not in captured
    assert "keep_alive" not in captured
    assert "drop_params" not in captured
    assert "base_url" not in captured
