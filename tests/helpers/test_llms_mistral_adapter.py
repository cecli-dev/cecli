"""Mistral adapter tests: strict message-body sanitization.

``mistral-flows.har`` shows cecli's replay of an assistant tool-call turn gets
422'd by Mistral, which rejects ``reasoning_content`` / ``provider_specific_fields``
on assistant messages and ``provider_specific_fields`` plus a null ``index`` on
tool calls. These tests lock in that :class:`MistralProvider.transform_messages`
strips those fields before dispatch.
"""

import asyncio

import cecli.helpers.llms.pipeline as pipeline
from cecli.helpers.llms.providers import ProviderAdapter, get_provider_adapter
from cecli.helpers.llms.providers.mistral import MistralProvider
from cecli.helpers.llms.types import Choice, CompletionResponse, Message


def _assistant_tool_turn() -> list:
    """A replayed assistant tool-call turn shaped like the failing HAR entries."""
    return [
        {"role": "system", "content": "## directives"},
        {"role": "user", "content": "do work"},
        {
            "role": "assistant",
            "content": "calling tool",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "index": None,
                    "function": {"name": "local--UpdateTodoList", "arguments": "{}"},
                    "provider_specific_fields": {},
                }
            ],
            "reasoning_content": "internal thought",
            "provider_specific_fields": {},
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
    ]


def test_mistral_provider_is_registered():
    adapter = get_provider_adapter("mistral")

    assert isinstance(adapter, MistralProvider)
    assert adapter.provider == "mistral"


def test_strips_unsupported_assistant_fields():
    adapter = MistralProvider()

    cleaned = adapter.transform_messages(_assistant_tool_turn())

    for msg in cleaned:
        assert "reasoning_content" not in msg
        assert "provider_specific_fields" not in msg

    for tc in cleaned[2]["tool_calls"]:
        assert "index" not in tc
        assert "provider_specific_fields" not in tc


def test_preserves_valid_tool_call_shape():
    adapter = MistralProvider()

    cleaned = adapter.transform_messages(_assistant_tool_turn())

    tool_call = cleaned[2]["tool_calls"][0]
    assert tool_call == {
        "id": "call_1",
        "type": "function",
        "function": {"name": "local--UpdateTodoList", "arguments": "{}"},
    }


def test_clean_messages_are_untouched():
    adapter = MistralProvider()
    messages = [
        {"role": "system", "content": "be helpful"},
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "hi",
            "tool_calls": [
                {"id": "t", "type": "function", "function": {"name": "x", "arguments": "{}"}}
            ],
        },
    ]

    assert adapter.transform_messages(messages) is messages


def test_does_not_mutate_input():
    adapter = MistralProvider()
    messages = _assistant_tool_turn()

    adapter.transform_messages(messages)

    assert messages[2]["tool_calls"][0]["index"] is None
    assert "reasoning_content" in messages[2]
    assert "provider_specific_fields" in messages[2]


def test_base_adapter_is_noop_by_default():
    messages = [
        {
            "role": "assistant",
            "content": "hi",
            "reasoning_content": "x",
            "provider_specific_fields": {},
        }
    ]

    assert ProviderAdapter().transform_messages(messages) is messages


def _fake_response(model):
    return CompletionResponse(
        id="x",
        model=model,
        choices=[Choice(index=0, message=Message(role="assistant", content="ok"))],
    )


def test_pipeline_sanitizes_messages_for_mistral(monkeypatch):
    """acompletion applies the mistral adapter's sanitization end-to-end."""
    captured = {}

    async def fake_chat_complete(resolved, messages, tools, key, headers, kwargs):
        captured["messages"] = messages
        return _fake_response(resolved["model"])

    monkeypatch.setattr(pipeline, "chat_complete", fake_chat_complete)

    asyncio.run(
        pipeline.acompletion(
            model="mistral/ministral-8b-2410",
            messages=_assistant_tool_turn(),
        )
    )

    for msg in captured["messages"]:
        assert "reasoning_content" not in msg
        assert "provider_specific_fields" not in msg

    for tc in captured["messages"][2]["tool_calls"]:
        assert "index" not in tc
        assert "provider_specific_fields" not in tc
