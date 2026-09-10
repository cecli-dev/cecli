"""Tests for the Mistral provider response normalization.

Mistral returns ``content`` as a list of typed parts (``thinking`` / ``text``)
rather than the plain string the OpenAI-compatible wire uses. The provider's
``normalize`` hook flattens those parts so the shared chat parser (and the
streaming consumers that concatenate ``delta.content``) stay provider-agnostic.
"""

from cecli.helpers.llms.domains.chat import chat_payload, parse_chat_chunk
from cecli.helpers.llms.providers.mistral import MistralProvider
from cecli.helpers.llms.types import (
    Choice,
    CompletionChunk,
    CompletionResponse,
    Message,
)


def _chunk(content):
    return parse_chat_chunk(
        {
            "id": "1",
            "model": "mistral-small-latest",
            "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}],
        }
    )


def test_stream_thinking_parts_become_reasoning():
    normalized = MistralProvider().normalize(
        "chat",
        _chunk([{"type": "thinking", "thinking": [{"type": "text", "text": "think "}]}]),
        {},
    )

    assert normalized.text == ""
    assert normalized.reasoning == "think "


def test_stream_text_parts_join_into_text():
    normalized = MistralProvider().normalize(
        "chat",
        _chunk([{"type": "text", "text": "Hello "}, {"type": "text", "text": "world"}]),
        {},
    )

    assert normalized.text == "Hello world"
    assert normalized.reasoning == ""


def test_string_content_is_left_untouched():
    normalized = MistralProvider().normalize(
        "chat", CompletionChunk(text="plain", reasoning="kept"), {}
    )

    assert normalized.text == "plain"
    assert normalized.reasoning == "kept"


def test_mixed_thinking_and_text_parts_split():
    normalized = MistralProvider().normalize(
        "chat",
        _chunk([{"type": "thinking", "thinking": "why"}, {"type": "text", "text": "answer"}]),
        {},
    )

    assert normalized.text == "answer"
    assert normalized.reasoning == "why"


def test_non_stream_response_content_list_is_flattened():
    response = CompletionResponse(
        choices=[
            Choice(
                index=0,
                message=Message(
                    role="assistant",
                    content=[{"type": "text", "text": "Hello"}, {"type": "text", "text": "!"}],
                ),
            )
        ]
    )

    normalized = MistralProvider().normalize("chat", response, {})

    assert normalized.choices[0].message.content == "Hello!"


def test_non_chat_family_is_untouched():
    chunk = CompletionChunk(text=["not", "a", "string"])

    assert MistralProvider().normalize("responses", chunk, {}) is chunk


def test_mistral_does_not_echo_reasoning_content():
    assert MistralProvider().echoes_reasoning_content is False


def test_payload_does_not_reinject_reasoning_content_for_mistral():
    """The chat coercer must not re-add the field Mistral rejects."""
    provider = MistralProvider()
    messages = provider.transform_messages(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello", "reasoning_content": ""},
        ]
    )
    resolved = {
        "route": "mistral-small-latest",
        "api_block": {"reasoning_effort": "high"},
        "_echo_reasoning_content": provider.echoes_reasoning_content,
    }

    payload = chat_payload(resolved, messages, None, True, {})

    assert "reasoning_content" not in payload["messages"][2]


def test_payload_coerces_reasoning_content_by_default():
    """Providers without an opt-out still get reasoning_content injected."""
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    resolved = {"route": "deepseek-chat", "api_block": {"reasoning_effort": "high"}}

    payload = chat_payload(resolved, messages, None, True, {})

    assert payload["messages"][2]["reasoning_content"] == ""
