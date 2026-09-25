import asyncio
import hashlib
import inspect
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cecli.coders import Coder
from cecli.helpers import command_queue, coroutines
from cecli.io import InputOutput
from cecli.llm import litellm
from cecli.mcp import McpServer

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


async def test_mcp_tool_round_trip_returns_to_conversation(
    tmp_path, gpt35_model, monkeypatch, capsys
):
    tool_call = tool_call_response("test-mcp--echo", '{"message":"hello"}', "call_echo")
    done = tool_call_response("local--Yield", '{"summary":"mcp round trip complete"}', "call_yield")
    coder, transcript_path = await make_linear_coder(
        tmp_path, gpt35_model, [tool_call, done], monkeypatch, edit_format="agent"
    )
    session = SimpleNamespace(
        call_tool=AsyncMock(
            return_value=SimpleNamespace(content=[SimpleNamespace(text="MCP result sentinel")])
        )
    )
    server = McpServer({"name": "Test-MCP"})
    server.connect = AsyncMock(return_value=session)
    coder.mcp_manager._servers.append(server)
    coder.mcp_manager._connected_servers.add(server)
    coder.mcp_manager._server_tools[server.name] = [
        {
            "type": "function",
            "function": {
                "name": "echo",
                "description": "Echo a message",
                "parameters": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                },
            },
        }
    ]

    await asyncio.wait_for(coder._run_linear("call the MCP server"), timeout=5)

    transcript = transcript_path.read_text(encoding="utf-8")
    tool_results = [message for message in coder.cur_messages if message.get("tool_call_id")]
    assert_linear_transcript(captured_terminal(capsys))
    session.call_tool.assert_awaited_once_with(name="echo", arguments={"message": "hello"})
    assert [message["tool_call_id"] for message in tool_results] == ["call_echo", "call_yield"]
    assert "MCP result sentinel" in tool_results[0]["content"]
    assert 'Arguments: {"message":"hello"}' in transcript
    assert transcript.index("Tool Call: test-mcp • echo") < transcript.index(
        "mcp round trip complete"
    )


async def test_confirmation_rejection_returns_to_usable_prompt(
    tmp_path, gpt35_model, monkeypatch, capsys
):
    command_call = tool_call_response(
        "local--Command",
        '{"command":"printf confirmation-sentinel"}',
        "call_command",
    )

    coder, transcript_path = await make_linear_coder(
        tmp_path,
        gpt35_model,
        [
            command_call,
            tool_call_response(
                "local--Yield", '{"summary":"first turn complete"}', "call_first_yield"
            ),
            tool_call_response(
                "local--Yield", '{"summary":"second turn complete"}', "call_second_yield"
            ),
        ],
        monkeypatch,
        edit_format="agent",
    )
    prompts = []
    coder.io.prompt_session = None
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or "n")

    await asyncio.wait_for(coder._run_linear("request requiring confirmation"), timeout=5)
    await asyncio.wait_for(coder._run_linear("request after confirmation"), timeout=5)

    transcript = transcript_path.read_text(encoding="utf-8")
    command_result = next(
        message for message in coder.cur_messages if message.get("tool_call_id") == "call_command"
    )
    assert_linear_transcript(captured_terminal(capsys))
    assert coder.io.get_confirmation_acknowledgement() is False
    assert len(prompts) == 1
    assert prompts[0].startswith("Allow execution of this command?")
    assert "Command execution skipped by user." in command_result["content"]
    assert transcript.index("first turn complete") < transcript.index("request after confirmation")
    assert transcript.index("request after confirmation") < transcript.index("second turn complete")


async def test_delegate_activity_is_serialized_before_parent_continues(
    tmp_path, gpt35_model, monkeypatch, capsys
):
    coder, transcript_path = await make_linear_coder(
        tmp_path,
        gpt35_model,
        [
            tool_call_response(
                "local--Delegate",
                '{"delegations":[{"name":"worker","prompt":"child task sentinel",'
                '"async":false}]}',
                "call_delegate",
            ),
            tool_call_response(
                "local--Yield", '{"summary":"parent handled child summary"}', "call_yield"
            ),
            tool_call_response(
                "local--Yield", '{"summary":"parent prompt still works"}', "call_followup"
            ),
        ],
        monkeypatch,
        edit_format="agent",
    )

    child_started = asyncio.Event()
    release_child = asyncio.Event()

    async def invoke(name, prompt, **kwargs):
        child_started.set()
        await release_child.wait()
        coder.io.tool_output("child output sentinel")
        return "child summary sentinel"

    agent_service = SimpleNamespace(
        invoke=AsyncMock(side_effect=invoke),
        get_children=lambda _coder: [],
        get_parent=lambda _coder: None,
        reap_all_finished_agents=AsyncMock(),
    )
    monkeypatch.setattr(
        "cecli.helpers.agents.service.AgentService.get_instance",
        lambda _coder=None: agent_service,
    )

    delegate_task = asyncio.create_task(coder._run_linear("delegate request"))
    await asyncio.wait_for(child_started.wait(), timeout=5)
    assert not delegate_task.done()
    assert "parent handled child summary" not in transcript_path.read_text(encoding="utf-8")
    release_child.set()
    await asyncio.wait_for(delegate_task, timeout=5)
    await asyncio.wait_for(coder._run_linear("parent follow-up sentinel"), timeout=5)

    transcript = transcript_path.read_text(encoding="utf-8")
    delegate_result = next(
        message for message in coder.cur_messages if message.get("tool_call_id") == "call_delegate"
    )
    assert_linear_transcript(captured_terminal(capsys))
    assert "child summary sentinel" in delegate_result["content"]
    assert transcript.index("child task sentinel") < transcript.index("child output sentinel")
    assert transcript.index("child output sentinel") < transcript.index(
        "parent handled child summary"
    )
    assert transcript.index("parent handled child summary") < transcript.index(
        "parent follow-up sentinel"
    )
    assert transcript.index("parent follow-up sentinel") < transcript.index(
        "parent prompt still works"
    )


async def test_compaction_commands_and_cleanup_under_linear_mode(
    tmp_path, gpt35_model, monkeypatch, capsys
):
    from cecli.helpers.agents.service import AgentService
    from cecli.main import graceful_exit

    real_fire_and_forget = coroutines.fire_and_forget
    coder, transcript_path = await make_linear_coder(
        tmp_path,
        gpt35_model,
        [
            tool_call_response(
                "local--Yield", '{"summary":"context before compaction"}', "call_yield"
            )
        ],
        monkeypatch,
        edit_format="agent",
    )
    await asyncio.wait_for(coder._run_linear("seed compactable context"), timeout=5)
    monkeypatch.setattr(coroutines, "fire_and_forget", real_fire_and_forget)

    memorizer_started = asyncio.Event()
    memorizer_cancelled = asyncio.Event()

    async def blocked_memorizer(*args, **kwargs):
        memorizer_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            memorizer_cancelled.set()
            raise

    monkeypatch.setattr("cecli.helpers.memory.utils.invoke_memorizer", blocked_memorizer)

    coder.enable_context_compaction = True
    coder.context_compaction_max_tokens = 1
    coder.context_compaction_summary_tokens = 32
    coder.summarizer.count_tokens = lambda messages: 100 if messages else 0
    coder.summarizer.summarize_all_as_text = AsyncMock(return_value="compacted sentinel")

    await asyncio.wait_for(coder._run_linear("/compact retain the sentinel"), timeout=5)
    await asyncio.wait_for(coder._run_linear("/help"), timeout=5)
    await asyncio.wait_for(coder._run_linear("/tokens"), timeout=5)
    await asyncio.wait_for(memorizer_started.wait(), timeout=5)

    child_started = asyncio.Event()
    child_cancelled = asyncio.Event()
    child_finalizer_cancelled = asyncio.Event()

    async def child_finalizer():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            child_finalizer_cancelled.set()
            raise

    async def active_child():
        child_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            child_cancelled.set()
            raise
        finally:
            coroutines.fire_and_forget(child_finalizer())

    child_task = asyncio.create_task(active_child())
    await asyncio.wait_for(child_started.wait(), timeout=5)
    agent_service = AgentService.get_instance(coder)
    agent_service.sub_agents["exit-child"] = SimpleNamespace(
        coder=SimpleNamespace(uuid="exit-child"), generate_task=child_task
    )
    agent_service._sub_agent_order.append("exit-child")

    await graceful_exit(coder)
    await asyncio.sleep(0)

    transcript = transcript_path.read_text(encoding="utf-8")
    assert_linear_transcript(captured_terminal(capsys))
    assert "Forcing compaction of chat history" in transcript
    assert "Use `/help <question>`" in transcript
    assert "Token report generated" in transcript
    assert memorizer_cancelled.is_set()
    assert child_cancelled.is_set()
    assert child_finalizer_cancelled.is_set()
    assert not coroutines.background_tasks


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
