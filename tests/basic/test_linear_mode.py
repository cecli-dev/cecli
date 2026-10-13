import asyncio
import hashlib
import inspect
import re
from types import SimpleNamespace

import pytest

from cecli.coders import Coder
from cecli.helpers import command_queue, coroutines
from cecli.io import InputOutput
from cecli.llm import litellm

LINEAR_OUTPUT_VIOLATION = re.compile(
    r"\r(?!\n)|\x08|\x1b(?:M|[78])|(?:\x1b\[|\x9b)"
    r"(?!(?:[0-?]*[ -/]*m|\?25[hl]))[0-?]*[ -/]*[@-~]"
)


def assert_linear_transcript(transcript):
    assert not LINEAR_OUTPUT_VIOLATION.search(transcript)


def captured_terminal(capsys):
    captured = capsys.readouterr()
    return captured.out + captured.err


def tool_call_response(name, arguments, call_id):
    return litellm.ModelResponse(
        model="fake",
        choices=[
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": arguments},
                        }
                    ],
                },
            }
        ],
    )


class FakeLLM:
    def __init__(self, replies):
        self.replies = iter(replies)

    async def send_completion(self, *args, **kwargs):
        reply = next(self.replies)
        if callable(reply):
            reply = reply()
        if inspect.isawaitable(reply):
            reply = await reply
        if isinstance(reply, BaseException):
            raise reply
        if isinstance(reply, litellm.ModelResponse):
            response = reply
        else:
            response = litellm.ModelResponse(
                model="fake",
                choices=[{"index": 0, "message": {"role": "assistant", "content": reply}}],
            )
        return hashlib.sha1(repr(reply).encode()), response


async def make_linear_coder(tmp_path, model, replies, monkeypatch, edit_format="diff"):
    monkeypatch.setattr("cecli.coders.base_coder.trim_memory", lambda: None)
    monkeypatch.setattr(coroutines, "fire_and_forget", lambda coro: coro.close())
    loop = asyncio.get_running_loop()

    def run_inline(_executor, func, *args):
        future = loop.create_future()
        try:
            future.set_result(func(*args))
        except BaseException as error:
            future.set_exception(error)
        return future

    monkeypatch.setattr(loop, "run_in_executor", run_inline)
    transcript_path = tmp_path / "transcript.md"
    io = InputOutput(chat_history_file=transcript_path, pretty=False, yes=True, show_spinner=False)
    args = SimpleNamespace(tui=False, fancy_input=True, debug=False)
    coder = await Coder.create(
        model,
        edit_format,
        io=io,
        args=args,
        use_git=False,
        stream=False,
        linear_output=True,
        auto_commits=False,
        auto_lint=False,
        detect_urls=False,
        root=tmp_path,
    )
    coder.main_model.send_completion = FakeLLM(replies).send_completion
    coder.interrupt_event = asyncio.Event()

    async def interruptible(awaitable, _event):
        return await awaitable, False

    coder.coroutines = SimpleNamespace(interruptible=interruptible)

    return coder, transcript_path


async def test_queued_input_is_serialized_after_current_turn(
    tmp_path, gpt35_model, monkeypatch, capsys
):
    started = asyncio.Event()
    release = asyncio.Event()

    async def first_reply():
        started.set()
        await release.wait()
        return "first reply"

    coder, transcript_path = await make_linear_coder(
        tmp_path, gpt35_model, [first_reply, "queued reply"], monkeypatch
    )
    run_task = asyncio.create_task(coder._run_linear("first prompt"))
    await asyncio.wait_for(started.wait(), timeout=5)
    command_queue.enqueue_prompt(coder, "second request sentinel")
    release.set()
    await asyncio.wait_for(run_task, timeout=5)

    transcript = transcript_path.read_text(encoding="utf-8")
    assert_linear_transcript(captured_terminal(capsys))
    assert transcript.index("first prompt") < transcript.index("first reply")
    assert transcript.index("first reply") < transcript.index("second request sentinel")
    assert transcript.index("second request sentinel") < transcript.index("queued reply")


async def test_interrupt_returns_to_usable_linear_prompt(
    tmp_path, gpt35_model, monkeypatch, capsys
):
    coder, transcript_path = await make_linear_coder(
        tmp_path,
        gpt35_model,
        [asyncio.CancelledError(), "recovered reply"],
        monkeypatch,
    )

    await asyncio.wait_for(coder._run_linear("interrupted request"), timeout=5)
    await asyncio.wait_for(coder._run_linear("request after interrupt"), timeout=5)

    transcript = transcript_path.read_text(encoding="utf-8")
    assert_linear_transcript(captured_terminal(capsys))
    assert "^C KeyboardInterrupt" in transcript
    assert transcript.index("request after interrupt") < transcript.index("recovered reply")


async def test_local_tool_round_trip_is_serialized(tmp_path, gpt35_model, monkeypatch, capsys):
    (tmp_path / "visible.txt").write_text("visible")
    tool_call = tool_call_response("local--ls", '{"path":"."}', "call_ls")
    done = tool_call_response(
        "local--Yield", '{"summary":"tool round trip complete"}', "call_yield"
    )
    coder, transcript_path = await make_linear_coder(
        tmp_path,
        gpt35_model,
        [tool_call, done],
        monkeypatch,
        edit_format="agent",
    )

    await asyncio.wait_for(coder._run_linear("list the directory"), timeout=5)

    transcript = transcript_path.read_text(encoding="utf-8")
    assert_linear_transcript(captured_terminal(capsys))
    assert "Tool Call: local • ls" in transcript
    assert "path: ." in transcript
    assert "Listed" in transcript
    assert "tool round trip complete" in transcript


@pytest.mark.parametrize(
    "transcript",
    [
        "progress\rrewrite",
        "\x1b[1A",
        "\x1b[1B",
        "\x1b[1C",
        "\x1b[1D",
        "\x1b[1G",
        "\x1b[2;3H",
        "\x1b[4f",
        "\x1b[2K",
        "\x1b[J",
        "\x1b[?2J",
        "\x1b[?2K",
        "\x1bM",
        "\x08",
        "\x1b7",
        "\x1b8",
        "\x1b[s",
        "\x1b[u",
        "\x9b2J",
        "\x1b[?1049h",
        "\x1b[?1049l",
        "\x1b[?25;1049h",
        "\x1b[P",
        "\x1b[X",
        "\x1b[L",
        "\x1b[M",
        "\x1b[@",
        "\x1b[I",
        "\x1b[Z",
        "\x1b[`",
        "\x1b[a",
        "\x1b[d",
        "\x1b[e",
    ],
)
def test_linear_transcript_rejects_rewrites(transcript):
    with pytest.raises(AssertionError):
        assert_linear_transcript(transcript)


def test_linear_transcript_allows_sgr_and_crlf():
    assert_linear_transcript("\x1b[?25l\x1b[31mred\x1b[0m\x1b[?25h\r\n")


@pytest.mark.parametrize("prompt_session", [object(), None], ids=["toolbar", "fallback"])
def test_linear_output_suppresses_dynamic_spinners(prompt_session):
    io = InputOutput(pretty=False)
    io.linear = True
    io.prompt_session = prompt_session
    try:
        io.start_spinner("Processing...")
        assert io.spinner_running is False
        assert io.fallback_spinner is None
        assert io.get_bottom_toolbar() is None
    finally:
        io.stop_spinner()
