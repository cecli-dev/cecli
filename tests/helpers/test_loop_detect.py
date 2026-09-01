"""Tests for the streaming loop detector and its integration into the coder.

The ``LoopDetector`` watches a stream of text as it is generated and raises a
``LoopDetectedError`` when the model starts repeating itself (stuck on a single
character, a single word, or a whole sentence). These tests cover:

* what the detector can and cannot catch from LLM / small-language-model output,
* the bounded-LRU behaviour of the sentence cache,
* the ``show_send_output_stream`` integration that stops streaming early,
* the ``send``-level handling that marks the turn as ``[SYSTEM CANCEL: OUTPUT LOOP DETECTED]``
  and drops any pending tool calls so they are never executed.
"""

import hashlib
from types import SimpleNamespace

import pytest

from cecli.coders.base_coder import Coder
from cecli.helpers.loop_detect import LoopDetectedError, LoopDetector, is_sentence
from cecli.helpers.threading import ThreadSafeEvent
from cecli.llm import litellm


# --------------------------------------------------------------------------- #
# LoopDetector unit tests
# --------------------------------------------------------------------------- #
def test_detects_char_loop():
    detector = LoopDetector(char_limit=5)
    with pytest.raises(LoopDetectedError) as exc:
        detector.push("aaaaaa")

    assert "Char loop: 'a' repeated 5 times." == str(exc.value)


def test_char_loop_does_not_trigger_below_limit():
    detector = LoopDetector(char_limit=5)
    assert detector.push("aaaa") is None  # 4 < limit, no raise


def test_detects_word_loop():
    detector = LoopDetector(word_limit=3)
    with pytest.raises(LoopDetectedError) as exc:
        detector.push("foo foo foo foo")

    assert "Word loop: 'foo' repeated 3 times." == str(exc.value)


def test_word_loop_does_not_trigger_below_limit():
    detector = LoopDetector(word_limit=10)
    assert detector.push("the the the the") is None  # 4 < 10


def test_detects_sentence_loop():
    detector = LoopDetector(sentence_limit=3)
    sentence = "This is a repeated sentence. "
    with pytest.raises(LoopDetectedError) as exc:
        for _ in range(3):
            detector.push(sentence)

    assert "Sentence loop: 'this is a repeated sentence.'" in str(exc.value)


def test_sentence_loop_does_not_trigger_below_limit():
    detector = LoopDetector(sentence_limit=3)
    sentence = "This is a repeated sentence. "
    # Two occurrences are below the trigger of three.
    assert detector.push(sentence) is None
    assert detector.push(sentence) is None


def test_sentence_cache_is_bounded_lru():
    """Oldest sentences are evicted so a repeated-in-the-past sentence is fresh."""
    detector = LoopDetector(sentence_limit=2, max_sentences=2)

    detector.push("This is sentence number one.")
    detector.push("This is sentence number two.")
    detector.push("This is sentence number three.")  # evicts number one
    detector.push("This is sentence number one.")  # fresh again, count == 1

    assert detector.sentence_counts.get("this is sentence number one.") == 1


def test_normal_prose_is_not_flagged():
    detector = LoopDetector()
    text = (
        "The quick brown fox jumps over the lazy dog. It was a sunny "
        "afternoon and the meadow was full of wildflowers."
    )
    assert detector.push(text) is None


def test_small_model_repetitive_but_short_output_is_not_flagged():
    """Tiny models often echo a word or two; that must not be called a loop."""
    detector = LoopDetector()
    for _ in range(4):
        assert detector.push("ok") is None


def test_custom_limits_respected():
    detector = LoopDetector(char_limit=3, word_limit=2, sentence_limit=2)
    with pytest.raises(LoopDetectedError):
        detector.push("aaaa")
    assert detector.char_count == 3


def test_error_can_be_caught_as_exception():
    detector = LoopDetector(char_limit=2)
    try:
        detector.push("aaaa")
    except Exception as exc:  # noqa: BLE001 - deliberately broad
        assert isinstance(exc, LoopDetectedError)
        assert "Char loop" in str(exc)
    else:
        pytest.fail("expected LoopDetectedError")


def test_is_sentence_matches_latin_prose():
    assert is_sentence("The quick brown fox jumps over the lazy dog.") is True
    assert is_sentence("Hello world!") is True
    assert is_sentence("Are you sure?") is True


def test_is_sentence_rejects_fragments_and_code():
    assert is_sentence("Not a sentence") is False  # no terminator
    assert is_sentence("not a sentence.") is False  # lowercase start
    assert is_sentence("Uppercase.") is False  # single word (no space)
    assert is_sentence("") is False
    assert is_sentence("   ") is False
    assert is_sentence("def foo():") is False  # code, no terminator
    assert is_sentence("print('x')") is False  # code


def test_code_like_output_does_not_trigger_sentence_loop():
    """Lowercase code/prose fragments must not be counted as sentence loops."""
    detector = LoopDetector(sentence_limit=5)
    fragment = "some code like line that is long.\n"

    for _ in range(6):
        detector.push(fragment)

    assert detector.sentence_counts == {}


# --------------------------------------------------------------------------- #
# Integration helpers
# --------------------------------------------------------------------------- #
class _AlwaysSetEvent:
    def is_set(self):
        return True


class _FakeIO:
    def __init__(self):
        self.confirmation_in_progress_event = _AlwaysSetEvent()
        self.warnings = []

    def tool_error(self, *a, **k):
        pass

    def tool_warning(self, *a, **k):
        self.warnings.append(a)

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

    def rule(self, *a, **k):
        pass

    def update_spinner(self, *a, **k):
        pass

    def start_spinner(self, *a, **k):
        pass

    def stop_spinner(self, *a, **k):
        pass

    def assistant_output(self, *a, **k):
        pass

    def llm_started(self):
        pass

    def ring_bell(self):
        pass


class _FakeTokenProfiler:
    def start(self):
        pass

    def on_token(self):
        pass

    def on_error(self):
        pass

    def add_to_usage_report(self, *a, **k):
        return a[0] if a else ""


def _make_coder():
    coder = Coder.__new__(Coder)
    coder.stream = True
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
    coder._streaming_buffer_length = 0
    coder.token_profiler = _FakeTokenProfiler()
    coder._output_loop_detected = False
    coder._output_loop_message = ""
    coder._has_empty_reflected = False
    coder.edit_format = "code"
    coder.max_compaction_retries = 3
    coder.enable_context_compaction = False
    coder.model_kwargs = {}
    coder.chat_completion_call_hashes = []
    coder.last_user_message = ""
    coder.error_code = None
    return coder


def _content_chunk(text):
    delta = litellm.Delta(role="assistant", content=text)
    choice = litellm.StreamChoice(finish_reason=None, index=0, delta=delta)
    return litellm.StreamChunk(
        id="cmpl-test", created=1000, model="gpt-test", choices=[choice], usage=None
    )


def _tc(index, call_id, name, arguments):
    return litellm.ChatCompletionMessageToolCall(
        id=call_id,
        function=litellm.Function(arguments=arguments or "", name=name),
        type="function",
        index=index,
    )


def _tool_chunk(tool_calls):
    delta = litellm.Delta(role="assistant", content=None, tool_calls=tool_calls)
    choice = litellm.StreamChoice(finish_reason=None, index=0, delta=delta)
    return litellm.StreamChunk(
        id="cmpl-test", created=1000, model="gpt-test", choices=[choice], usage=None
    )


def _agen(chunks):
    async def gen():
        for chunk in chunks:
            yield chunk

    return gen()


class _FakeModel:
    def __init__(self, chunks):
        self.chunks = chunks

    async def send_completion(self, *args, **kwargs):
        return hashlib.sha1(b"test"), _agen(self.chunks)


# --------------------------------------------------------------------------- #
# show_send_output_stream integration
# --------------------------------------------------------------------------- #
async def test_show_stream_detects_content_loop_and_stops():
    coder = _make_coder()
    chunks = [_content_chunk("a" * 50), _content_chunk("a" * 51)]

    async for _ in coder.show_send_output_stream(_agen(chunks)):
        pass

    assert coder._output_loop_detected is True
    assert "Char loop" in coder._output_loop_message


async def test_show_stream_detects_tool_args_loop_and_stops():
    coder = _make_coder()
    # A single tool-call fragment that is itself a repeated-character loop.
    chunks = [_tool_chunk([_tc(0, "call_1", "Local--ls", "a" * 101)])]

    async for _ in coder.show_send_output_stream(_agen(chunks)):
        pass

    assert coder._output_loop_detected is True
    assert "Char loop" in coder._output_loop_message


async def test_show_stream_does_not_flag_normal_stream():
    coder = _make_coder()
    # Real consolidation is expensive here, so stub it; we only assert that a
    # healthy stream never trips the detector flag.
    coder.consolidate_chunks = lambda: (None, None, None)
    chunks = [
        _content_chunk("The quick brown fox jumps over the lazy dog."),
        _content_chunk(" It was a sunny afternoon."),
    ]

    async for _ in coder.show_send_output_stream(_agen(chunks)):
        pass

    assert coder._output_loop_detected is False


def test_consolidate_chunks_applies_marker_and_clears_tool_calls():
    coder = _make_coder()
    coder.partial_response_chunks = [_tool_chunk([_tc(0, "call_1", "Local--ls", "{}")])]
    coder._output_loop_detected = True

    response, func_err, content_err = coder.consolidate_chunks()

    assert func_err is None
    assert "[SYSTEM CANCEL: OUTPUT LOOP DETECTED]" in coder.partial_response_content
    assert coder.partial_response_tool_calls == []
    assert coder.partial_response_function_call == dict()

    # The marker must also be written into the response message so it actually
    # reaches the assistant message / conversation (which is built via model_dump).
    msg = response.choices[0].message
    assert "[SYSTEM CANCEL: OUTPUT LOOP DETECTED]" in (msg.content or "")
    assert msg.tool_calls == []

    dumped = response.model_dump()["choices"][0]["message"]
    assert "[SYSTEM CANCEL: OUTPUT LOOP DETECTED]" in (dumped.get("content") or "")


def test_consolidate_chunks_propagates_marker_onto_existing_content():
    """A content-only loop keeps prior text and appends the marker to message.content."""
    coder = _make_coder()
    coder.partial_response_chunks = [
        _content_chunk("The quick brown fox jumps over the lazy dog. ")
    ]
    coder._output_loop_detected = True

    response, func_err, content_err = coder.consolidate_chunks()

    assert func_err is None
    msg = response.choices[0].message
    assert "[SYSTEM CANCEL: OUTPUT LOOP DETECTED]" in msg.content
    assert "The quick brown fox jumps over the lazy dog." in msg.content


def test_consolidate_chunks_leaves_normal_stream_untouched():
    coder = _make_coder()
    coder.partial_response_chunks = [_content_chunk("The quick brown fox jumps over the lazy dog.")]

    response, func_err, content_err = coder.consolidate_chunks()

    assert func_err is None
    assert "[SYSTEM CANCEL: OUTPUT LOOP DETECTED]" not in coder.partial_response_content
    assert coder.partial_response_tool_calls == []


async def test_show_stream_closes_provider_on_loop():
    """Loop-detection must aclose() the provider async generator, not leak it."""
    coder = _make_coder()
    closed = {"closed": False}

    async def provider():
        try:
            yield _content_chunk("a" * 50)
            yield _content_chunk("a" * 51)
        finally:
            closed["closed"] = True

    stream = provider()

    async for _ in coder.show_send_output_stream(stream):
        pass

    assert coder._output_loop_detected is True
    assert closed["closed"] is True


# --------------------------------------------------------------------------- #
# send() integration
# --------------------------------------------------------------------------- #
async def test_send_appends_marker_and_clears_tool_calls_on_content_loop():
    coder = _make_coder()
    coder.calculate_and_show_tokens_and_cost = lambda *a, **k: None
    chunks = [_content_chunk("a" * 50), _content_chunk("a" * 51)]
    model = _FakeModel(chunks)

    async for _ in coder.send([], model=model):
        pass

    assert coder._output_loop_detected is True
    assert "[SYSTEM CANCEL: OUTPUT LOOP DETECTED]" in coder.partial_response_content
    assert coder.partial_response_tool_calls == []


async def test_send_appends_marker_and_clears_tool_calls_on_tool_loop():
    coder = _make_coder()
    coder.calculate_and_show_tokens_and_cost = lambda *a, **k: None
    chunks = [_tool_chunk([_tc(0, "call_1", "Local--ls", "a" * 101)])]
    model = _FakeModel(chunks)

    async for _ in coder.send([], model=model):
        pass

    assert coder._output_loop_detected is True
    assert "[SYSTEM CANCEL: OUTPUT LOOP DETECTED]" in coder.partial_response_content
    assert coder.partial_response_tool_calls == []
    assert coder.partial_response_function_call == dict()
