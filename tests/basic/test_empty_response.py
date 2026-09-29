"""Tests for empty-response detection with non-meaningful reasoning content.

Regression coverage for the ``retry-on-empty`` fix: a completion with empty
``content``, no tool calls, and a ``reasoning_content`` made entirely of
non-alphanumeric characters (e.g. moonshotai/kimi-k3 returning ``"!!!!"``) must
be classified as an empty response so the existing retry loop engages.
"""

from types import SimpleNamespace

import pytest

from cecli.coders.base_coder import Coder, _is_meaningful_reasoning
from cecli.helpers.threading import ThreadSafeEvent
from cecli.llm import litellm


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class _AlwaysSetEvent:
    def is_set(self):
        return True


class _FakeIO:
    def __init__(self):
        self.confirmation_in_progress_event = _AlwaysSetEvent()
        self.assistant_outputs = []

    def tool_error(self, *a, **k):
        pass

    def tool_warning(self, *a, **k):
        pass

    def update_spinner_suffix(self, *a, **k):
        pass

    def reset_streaming_response(self):
        pass

    def stream_output(self, *a, **k):
        pass

    def ai_output(self, *a, **k):
        pass

    def tool_output(self, *a, **k):
        pass

    def assistant_output(self, *a, **k):
        self.assistant_outputs.append(a)


class _FakeTokenProfiler:
    def start(self):
        pass

    def on_token(self):
        pass

    def on_error(self):
        pass

    def add_to_usage_report(self, *a, **k):
        return a[0] if a else ""


def _make_coder(stream=False):
    coder = Coder.__new__(Coder)
    coder.stream = stream
    coder.verbose = False
    coder.args = SimpleNamespace(debug=False, show_thinking=False)
    coder.io = _FakeIO()
    coder.interrupt_event = ThreadSafeEvent()
    coder.pretty = False
    coder.reasoning_tag_name = "THINKING"
    coder.got_reasoning_content = False
    coder.ended_reasoning_content = False
    coder.empty_response = False
    coder.tool_reflection = False
    coder.partial_response_content = ""
    coder.partial_response_reasoning_content = ""
    coder.partial_response_chunks = []
    coder.partial_response_tool_calls = []
    coder.partial_response_function_call = dict()
    coder.partial_response_consolidated = None
    coder.multi_response_content = ""
    coder.chat_completion_response_hashes = []
    coder._streaming_buffer_length = 0
    coder.token_profiler = _FakeTokenProfiler()
    coder._output_loop_detected = False
    coder._output_loop_message = ""
    coder._has_empty_reflected = False
    coder.edit_format = "code"
    return coder


def _tc(index, call_id, name, arguments):
    return litellm.ChatCompletionMessageToolCall(
        id=call_id,
        function=litellm.Function(arguments=arguments or "", name=name),
        type="function",
        index=index,
    )


def _non_streaming_completion(content="", reasoning=None, tool_calls=None):
    message = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return litellm.ModelResponse(
        id="test-completion",
        created=0,
        model="gpt-test",
        object="chat.completion",
        choices=[{"finish_reason": "stop", "index": 0, "message": message}],
        usage={"completion_tokens": 1, "prompt_tokens": 1, "total_tokens": 2},
    )


def _reasoning_chunk(text):
    delta = litellm.Delta(role="assistant", content=None, reasoning_content=text)
    choice = litellm.StreamChoice(finish_reason=None, index=0, delta=delta)
    return litellm.StreamChunk(
        id="cmpl-test", created=1000, model="gpt-test", choices=[choice], usage=None
    )


async def _agen(chunks):
    for chunk in chunks:
        yield chunk


# --------------------------------------------------------------------------- #
# _is_meaningful_reasoning unit tests
# --------------------------------------------------------------------------- #
def test_is_meaningful_reasoning_empty_and_none():
    assert _is_meaningful_reasoning("") is False
    assert _is_meaningful_reasoning(None) is False


def test_is_meaningful_reasoning_punctuation_only():
    assert _is_meaningful_reasoning("!!!!") is False
    assert _is_meaningful_reasoning("...?!,;:") is False


def test_is_meaningful_reasoning_whitespace_only():
    assert _is_meaningful_reasoning("   \n\t  ") is False


def test_is_meaningful_reasoning_normal_text():
    assert _is_meaningful_reasoning("Let me think about this") is True


def test_is_meaningful_reasoning_mixed_punctuation_and_alnum():
    assert _is_meaningful_reasoning("42?") is True
    assert _is_meaningful_reasoning("!!!a!!!") is True


# --------------------------------------------------------------------------- #
# Non-streaming path (show_send_output)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_junk_reasoning_is_empty_non_streaming():
    coder = _make_coder(stream=False)
    await coder.show_send_output(_non_streaming_completion(content="", reasoning="!" * 40))
    assert coder.empty_response is True


@pytest.mark.asyncio
async def test_meaningful_reasoning_is_not_empty_non_streaming():
    coder = _make_coder(stream=False)
    await coder.show_send_output(
        _non_streaming_completion(content="", reasoning="Let me think about this")
    )
    assert coder.empty_response is False


@pytest.mark.asyncio
async def test_tool_calls_are_not_empty_non_streaming():
    coder = _make_coder(stream=False)
    await coder.show_send_output(
        _non_streaming_completion(
            content="",
            reasoning="",
            tool_calls=[_tc(0, "call_1", "Local--ls", "{}")],
        )
    )
    assert coder.empty_response is False


@pytest.mark.asyncio
async def test_mixed_reasoning_is_not_empty_non_streaming():
    coder = _make_coder(stream=False)
    await coder.show_send_output(_non_streaming_completion(content="", reasoning="42?"))
    assert coder.empty_response is False


# --------------------------------------------------------------------------- #
# Streaming path (show_send_output_stream)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_junk_reasoning_is_empty_streaming():
    coder = _make_coder(stream=True)
    coder.args.show_thinking = True
    async for _ in coder.show_send_output_stream(_agen([_reasoning_chunk("!" * 40)])):
        pass
    assert coder.empty_response is True


@pytest.mark.asyncio
async def test_meaningful_reasoning_is_not_empty_streaming():
    coder = _make_coder(stream=True)
    coder.args.show_thinking = True
    async for _ in coder.show_send_output_stream(
        _agen([_reasoning_chunk("Let me think about this")])
    ):
        pass
    assert coder.empty_response is False