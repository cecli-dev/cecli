"""Tests for the ACP v1 agent (``cecli --acp``)."""

from __future__ import annotations

import asyncio
import os
import threading
from types import SimpleNamespace

import pytest

from cecli import models
from cecli.helpers.server.acp.agent import config as acp_config
from cecli.helpers.server.acp.agent.agent import AcpAgent, prompt_to_text
from cecli.helpers.server.acp.agent.config import SessionConfig, current_value
from cecli.helpers.server.acp.agent.io import AcpInputOutput
from cecli.helpers.server.acp.agent.mcp import ClientMcpServers, to_cecli_configs
from cecli.helpers.server.acp.agent.transport import (
    EOF,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
)
from cecli.helpers.server.acp.agent.updates import UpdateEmitter
from cecli.reasoning_tags import REASONING_END, REASONING_START


@pytest.fixture(autouse=True)
def configured_models(monkeypatch):
    """User aliases and model files as main() would register them, without reading ~."""
    monkeypatch.setitem(models.MODEL_ALIASES, "fast", "gpt-x")
    monkeypatch.setitem(models.MODEL_ALIASES, "smart", "big-model")
    monkeypatch.setattr(
        models.ModelOverrides, "_overrides", {"gpt-y": {"high": {"reasoning_effort": "high"}}}
    )
    monkeypatch.setattr(acp_config, "settings_file_models", lambda coder: ["local/qwen"])
    # No provider API keys, whatever the environment running the tests has
    monkeypatch.setattr(acp_config, "keyed_provider_models", lambda: [])


# ── UpdateEmitter ──────────────────────────────────────────────


def make_emitter():
    updates = []
    return UpdateEmitter(updates.append), updates


def texts(updates, kind):
    return "".join(u["content"]["text"] for u in updates if u["sessionUpdate"] == kind)


def test_reasoning_markers_split_across_chunks():
    emitter, updates = make_emitter()
    stream = f"\n{REASONING_START}pondering{REASONING_END}\nThe answer."
    for i in range(0, len(stream), 3):
        emitter.stream(stream[i : i + 3])
    emitter.stream("", final=True)

    assert texts(updates, "agent_thought_chunk").strip() == "pondering"
    assert texts(updates, "agent_message_chunk").strip() == "The answer."
    # The newline ahead of the marker must not become its own message
    assert updates[0]["sessionUpdate"] == "agent_thought_chunk"


def test_console_lines_share_one_fence_closed_by_model_text():
    emitter, updates = make_emitter()
    emitter.stream("Intro.")
    emitter.block("line one")
    emitter.block("line two")
    emitter.stream("More prose.")

    text = texts(updates, "agent_message_chunk")
    assert text == "Intro.\n\n````\nline one\nline two\n````\n\nMore prose."


def test_tool_lifecycle_and_output():
    emitter, updates = make_emitter()
    emitter.root = "/proj"
    emitter.tool_event("t1", "pending", name="Local--ReadFile", arguments='{"file_path": "a.py"}')
    emitter.tool_header("Tool Call: Local • ReadFile")
    emitter.block("Arguments: {...}")  # panel body is dropped
    emitter.tool_footer()
    emitter.tool_event("t1", "in_progress")
    emitter.block("Viewed a.py")
    emitter.tool_event("t1", "completed", result="contents")

    call = updates[0]
    assert call["sessionUpdate"] == "tool_call"
    assert call["title"] == "ReadFile: a.py"
    assert call["kind"] == "read"
    assert call["locations"] == [{"path": "/proj/a.py"}]
    assert call["rawInput"] == {"file_path": "a.py"}

    statuses = [u.get("status") for u in updates if u["sessionUpdate"] == "tool_call_update"]
    assert statuses == ["in_progress", None, "completed"]
    content = updates[2]["content"][0]["content"]["text"]
    assert "Viewed a.py" in content and "Arguments" not in content
    assert texts(updates, "agent_message_chunk") == ""


def test_result_shown_when_tool_printed_nothing():
    emitter, updates = make_emitter()
    emitter.tool_event("t1", "pending", name="Grep", arguments="{}")
    emitter.tool_event("t1", "in_progress")
    emitter.tool_event("t1", "completed", result="match.py:3")

    assert "match.py:3" in updates[-2]["content"][0]["content"]["text"]
    assert updates[-1]["status"] == "completed"


def test_model_text_settles_running_tools():
    emitter, updates = make_emitter()
    emitter.tool_event("t1", "pending", name="Command", arguments='{"command": "ls"}')
    emitter.tool_event("t1", "in_progress")
    emitter.stream("Done.")

    # Not "execute", which would hide Zed's progress spinner while it runs
    assert updates[0]["kind"] == "other"
    assert {
        "sessionUpdate": "tool_call_update",
        "toolCallId": "t1",
        "status": "completed",
    } in updates


def test_finish_turn_fails_open_tools_when_cancelled():
    emitter, updates = make_emitter()
    emitter.tool_event("t1", "pending", name="Command", arguments="{}")
    emitter.tool_event("t1", "in_progress")
    emitter.finish_turn(cancelled=True)

    assert updates[-1] == {
        "sessionUpdate": "tool_call_update",
        "toolCallId": "t1",
        "status": "failed",
    }


def test_finish_turn_fails_skipped_tools():
    emitter, updates = make_emitter()
    emitter.tool_event("t1", "pending", name="Command", arguments="{}")
    emitter.finish_turn()

    assert updates[-1] == {
        "sessionUpdate": "tool_call_update",
        "toolCallId": "t1",
        "status": "failed",
    }


def test_todo_list_becomes_plan_and_yield_summary_a_message():
    emitter, updates = make_emitter()
    tasks = [
        {"task": "Read", "done": True},
        {"task": "Write", "done": False, "current": True},
        {"task": "Test", "done": False},
    ]
    emitter.tool_event("t1", "pending", name="UpdateTodoList", arguments={"tasks": tasks})
    plan = next(u for u in updates if u["sessionUpdate"] == "plan")
    assert [e["status"] for e in plan["entries"]] == ["completed", "in_progress", "pending"]

    emitter.tool_event("t2", "pending", name="Yield", arguments={"summary": "All done."})
    emitter.tool_event("t2", "in_progress")
    emitter.tool_event("t2", "completed", result="Yielded.")
    assert texts(updates, "agent_message_chunk").strip() == "All done."


def test_permission_target_prefers_the_obvious_tool():
    emitter, updates = make_emitter()
    emitter.tool_event("t1", "pending", name="Command", arguments="{}")
    assert emitter.permission_target("Run tools?", None) == ("t1", False)

    emitter.tool_event("t2", "pending", name="Grep", arguments="{}")
    tool_id, synthetic = emitter.permission_target("Run tools?", None)
    assert synthetic and tool_id.startswith("cecli-confirm-")

    # Rejecting a group prompt fails every tool waiting behind it
    emitter.permission_resolved(tool_id, True, allowed=False)
    failed = {u["toolCallId"] for u in updates if u.get("status") == "failed"}
    assert failed == {tool_id, "t1", "t2"}


def test_permission_question_shows_until_answered():
    emitter, updates = make_emitter()
    emitter.tool_event("t1", "pending", name="Command", arguments='{"command": "ls"}')
    emitter.tool_event("t1", "in_progress")

    # A tool can be asked about twice; each request carries its own question
    for question in ("Allow execution of this command?", "Allow this command for the session?"):
        prompt = emitter.permission_prompt("t1", question)
        assert prompt["content"][0]["content"]["text"] == question
        emitter.permission_resolved("t1", False, allowed=True)
        assert updates[-1] == {
            "sessionUpdate": "tool_call_update",
            "toolCallId": "t1",
            "content": [],
        }

    # Output printed later replaces the content as usual
    emitter.block("a.py")
    assert "a.py" in updates[-1]["content"][0]["content"]["text"]
    assert emitter.permission_prompt("cecli-confirm-9", "Run?") == {"toolCallId": "cecli-confirm-9"}


# ── Prompt conversion ──────────────────────────────────────────


def test_prompt_to_text(tmp_path):
    root = str(tmp_path)
    blocks = [
        {"type": "text", "text": "Explain"},
        {"type": "resource_link", "name": "a.py", "uri": (tmp_path / "a.py").as_uri()},
        {
            "type": "resource",
            "resource": {"uri": (tmp_path / "b.py").as_uri() + "#L2:3", "text": "x = 1"},
        },
        {"type": "resource", "resource": {"uri": "zed:///rules", "text": "Be terse."}},
    ]
    text, paths = prompt_to_text(blocks, root)

    assert text.startswith("Explain a.py")
    assert "b.py:\n```\nx = 1\n```" in text
    assert "Be terse." in text
    assert [os.path.normpath(p) for p in paths] == [str(tmp_path / "a.py"), str(tmp_path / "b.py")]


# ── AcpAgent ───────────────────────────────────────────────────


class FakeTransport:
    def __init__(self):
        self.sent = []
        self._inbox = None

    def attach(self, loop):
        self._inbox = asyncio.Queue()

    def detach(self):
        pass

    async def receive(self):
        return await self._inbox.get()

    def feed(self, msg):
        self._inbox.put_nowait(msg)

    def send(self, msg):
        self.sent.append(msg)

    def results(self):
        return {m["id"]: m for m in self.sent if "method" not in m}

    def updates(self):
        return [m["params"]["update"] for m in self.sent if m.get("method") == "session/update"]


class StubModel:
    def __init__(self, name, accepts=("reasoning_effort",), effort=None, budget=None):
        self.name = name
        self.accepts_settings = list(accepts)
        self.effort = effort
        self.budget = budget

    def get_reasoning_effort(self):
        return self.effort

    def get_raw_thinking_tokens(self):
        return self.budget

    def get_thinking_tokens(self):
        return None if self.budget is None else f"{self.budget // 1024}k"


class StubCoder:
    def __init__(self, root, model=None, edit_format="diff"):
        self.root = str(root)
        self.abs_fnames = set()
        self.abs_read_only_fnames = set()
        self.io = SimpleNamespace(output_task=None, yes=None, tool_output=lambda *a, **k: None)
        self.interrupt_event = threading.Event()
        self.main_model = model or StubModel("gpt-x")
        self.agent_model = None
        self.edit_format = edit_format
        self.args = SimpleNamespace(model="fast", alias=["fast:gpt-x", "smart:big-model"])
        self.repo = None

    def get_active_model(self):
        if self.edit_format == "agent" and self.agent_model:
            return self.agent_model
        return self.main_model

    async def forever(self):
        await asyncio.sleep(3600)


def make_coder(root):
    return StubCoder(root)


async def ready_agent(tmp_path):
    """An agent past bootstrap, with session/new (id 2) deferred."""
    transport = FakeTransport()
    agent = AcpAgent(transport)
    agent.cwd = str(tmp_path)
    agent.session_id = "s1"
    agent._deferred_new.append(2)
    agent.start()
    return agent, transport


async def settle():
    for _ in range(5):
        await asyncio.sleep(0)


def prompt(request_id, text, session_id="s1"):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "session/prompt",
        "params": {"sessionId": session_id, "prompt": [{"type": "text", "text": text}]},
    }


async def test_initialize_and_unknown_method(tmp_path):
    agent, transport = await ready_agent(tmp_path)
    transport.feed({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    transport.feed({"jsonrpc": "2.0", "id": 9, "method": "session/load", "params": {}})
    await settle()

    result = transport.results()[1]["result"]
    assert result["protocolVersion"] == 1
    assert result["agentCapabilities"]["loadSession"] is False
    assert transport.results()[9]["error"]["code"] == METHOD_NOT_FOUND


async def test_turn_lifecycle(tmp_path):
    agent, transport = await ready_agent(tmp_path)
    coder = make_coder(tmp_path)

    # Prompts are rejected until the coder is ready (the client has no id yet)
    transport.feed(prompt(3, "too early"))
    await settle()
    assert "error" in transport.results()[3]

    waiting = asyncio.create_task(agent.next_input(coder))
    await settle()
    session = transport.results()[2]["result"]
    assert session["sessionId"] == "s1"
    assert [o["id"] for o in session["configOptions"]] == ["mode", "model", "reasoning_effort"]
    assert session["modes"]["currentModeId"] == "code"
    assert transport.updates()[0]["sessionUpdate"] == "available_commands_update"
    names = {c["name"] for c in transport.updates()[0]["availableCommands"]}
    assert "add" in names and "exit" not in names

    transport.feed(prompt(4, "hello"))
    assert await waiting == "hello"

    agent.emitter.stream("Hi there.", final=True)
    assert 4 not in transport.results()

    # The loop asking for input again ends the turn
    waiting = asyncio.create_task(agent.next_input(coder))
    await settle()
    assert transport.results()[4]["result"] == {"stopReason": "end_turn"}
    # The turn's updates all precede its response
    kinds = [m.get("method") or m.get("id") for m in transport.sent]
    assert kinds[-2:] == ["session/update", 4]
    assert transport.updates()[-1]["content"]["text"] == "Hi there."
    waiting.cancel()


async def test_cancel_interrupts_coder(tmp_path):
    agent, transport = await ready_agent(tmp_path)
    coder = make_coder(tmp_path)
    waiting = asyncio.create_task(agent.next_input(coder))
    await settle()
    transport.feed(prompt(4, "long job"))
    await waiting

    coder.io.output_task = asyncio.create_task(coder.forever())
    transport.feed({"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": "s1"}})
    await settle()
    assert coder.io.output_task.cancelled()
    assert coder.interrupt_event.is_set()

    waiting = asyncio.create_task(agent.next_input(coder))
    await settle()
    assert transport.results()[4]["result"] == {"stopReason": "cancelled"}
    waiting.cancel()


async def test_permission_roundtrip_through_confirm_ask(tmp_path):
    agent, transport = await ready_agent(tmp_path)
    io = AcpInputOutput(agent=agent)
    waiting = asyncio.create_task(agent.next_input(make_coder(tmp_path)))
    await settle()
    transport.feed(prompt(4, "do it"))
    await waiting

    asking = asyncio.create_task(io.confirm_ask("Run tools?", group_response="Run MCP Tools"))
    await settle()
    request = next(m for m in transport.sent if m.get("method") == "session/request_permission")
    assert {o["optionId"] for o in request["params"]["options"]} == {"y", "a", "s", "n"}

    transport.feed(
        {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {"outcome": {"outcome": "selected", "optionId": "a"}},
        }
    )
    assert await asking is True
    # "Yes to all" sticks, so the next group prompt is not sent to the client
    assert await io.confirm_ask("Run tools?", group_response="Run MCP Tools") is True
    assert sum(m.get("method") == "session/request_permission" for m in transport.sent) == 1


async def test_confirm_outside_a_prompt_declines(tmp_path):
    agent, transport = await ready_agent(tmp_path)
    io = AcpInputOutput(agent=agent)
    assert await io.confirm_ask("Add .cecli* to .gitignore?") is False
    assert not any(m.get("method") == "session/request_permission" for m in transport.sent)


async def test_usage_report_is_not_shown(tmp_path):
    agent, transport = await ready_agent(tmp_path)
    io = AcpInputOutput(agent=agent)
    waiting = asyncio.create_task(agent.next_input(make_coder(tmp_path)))
    await settle()
    transport.feed(prompt(4, "hi"))
    await waiting

    io.tool_output("18k ◇ 95.4% ↑ 139 ↓ $0.00015", type="usage-report")
    io.tool_output("Added a.py to the chat")
    agent.emitter.stream("Done.", final=True)
    shown = "".join(u["content"]["text"] for u in transport.updates() if "content" in u)
    assert "Added a.py" in shown
    assert "$0.00015" not in shown


async def test_eof_ends_the_input_loop(tmp_path):
    agent, transport = await ready_agent(tmp_path)
    waiting = asyncio.create_task(agent.next_input(make_coder(tmp_path)))
    await settle()
    transport.feed(EOF)
    with pytest.raises(EOFError):
        await waiting


async def test_second_session_clears_chat(tmp_path):
    agent, transport = await ready_agent(tmp_path)
    coder = make_coder(tmp_path)
    waiting = asyncio.create_task(agent.next_input(coder))
    await settle()

    other = tmp_path / "other"
    other.mkdir()
    transport.feed(
        {"jsonrpc": "2.0", "id": 5, "method": "session/new", "params": {"cwd": str(other)}}
    )
    transport.feed(
        {"jsonrpc": "2.0", "id": 6, "method": "session/new", "params": {"cwd": str(tmp_path)}}
    )
    await settle()
    assert transport.results()[5]["error"]["code"] == INVALID_PARAMS

    # The new session runs /clear as an internal turn before it is answered
    assert await waiting == "/clear"
    assert 6 not in transport.results()
    waiting = asyncio.create_task(agent.next_input(coder))
    await settle()
    new_id = transport.results()[6]["result"]["sessionId"]
    assert new_id != "s1" and agent.session_id == new_id

    transport.feed(prompt(7, "stale", session_id="s1"))
    await settle()
    assert "error" in transport.results()[7]
    waiting.cancel()


# ── Sub-agents ─────────────────────────────────────────────────


def notifications(transport):
    """``(sessionId, update)`` for each session/update sent."""
    return [
        (m["params"]["sessionId"], m["params"]["update"])
        for m in transport.sent
        if m.get("method") == "session/update"
    ]


def subagent_states(transport):
    return [
        (session_id, update["sessionId"], update["state"])
        for session_id, update in notifications(transport)
        if update["sessionUpdate"] == "subagent_update" and "state" in update
    ]


async def delegating_agent(tmp_path, subagents=True):
    """An agent in the middle of a prompt, for a client with or without subagent support."""
    agent, transport = await ready_agent(tmp_path)
    capabilities = {"subagents": {}} if subagents else {}
    transport.feed(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": 1, "clientCapabilities": capabilities},
        }
    )
    coder = make_coder(tmp_path)
    coder.uuid = "primary"
    waiting = asyncio.create_task(agent.next_input(coder))
    await settle()
    transport.feed(prompt(4, "delegate this"))
    await waiting
    transport.sent.clear()
    # The agent holds the coder weakly; the caller keeps it alive, as cecli's loop would
    return agent, transport, AcpInputOutput(agent=agent), coder


async def test_subagent_is_a_child_session(tmp_path):
    agent, transport, io, _coder = await delegating_agent(tmp_path)
    io.subagent_event(
        "w1", "created", parent_uuid="primary", name="worker", description="Does work", root="/w"
    )
    io.subagent_event("w1", "message", sender_uuid="primary", text="Fix the tests")
    io.subagent_event("w1", "running")
    io.stream_output("On it.", final=True, coder_uuid="w1")
    io.tool_call_event("t1", "pending", coder_uuid="w1", name="ReadFile", arguments='{"path": "a"}')
    io.stream_output("Meanwhile, the parent.", final=True, coder_uuid="primary")
    io.subagent_event("w1", "idle", stop_reason="end_turn", error=None)

    sent = notifications(transport)
    child = agent.subagents["w1"].session_id
    # Announced on the parent's session before anything names the child
    assert sent[0] == (
        "s1",
        {
            "sessionUpdate": "subagent_update",
            "sessionId": child,
            "capabilities": {"cancel": {}},
            "title": "worker",
            "description": "Does work",
        },
    )
    # The delegation as the parent sent it, then as the child got it
    (out_session, outgoing), (in_session, incoming) = sent[1], sent[2]
    assert (out_session, in_session) == ("s1", child)
    for message in (outgoing, incoming):
        assert message["sessionUpdate"] == "session_message"
        assert (message["senderSessionId"], message["recipientSessionId"]) == ("s1", child)
        assert message["content"] == [{"type": "text", "text": "Fix the tests"}]
    assert outgoing["messageId"] != incoming["messageId"]

    # Each agent's output lands in its own session
    child_updates = [update for session_id, update in sent if session_id == child]
    assert texts(child_updates, "agent_message_chunk") == "On it."
    call = next(u for u in child_updates if u["sessionUpdate"] == "tool_call")
    assert call["locations"] == [{"path": "/w/a"}]
    parent_updates = [update for session_id, update in sent if session_id == "s1"]
    assert texts(parent_updates, "agent_message_chunk") == "Meanwhile, the parent."

    # Going idle settles the child's tools; this one was announced but never ran
    assert child_updates[-1]["status"] == "failed"
    assert subagent_states(transport) == [
        ("s1", child, {"state": "running"}),
        ("s1", child, {"state": "idle", "stopReason": "end_turn"}),
    ]


async def test_subagents_stay_in_the_parent_session_without_client_support(tmp_path):
    agent, transport, io, _coder = await delegating_agent(tmp_path, subagents=False)
    io.subagent_event("w1", "created", parent_uuid="primary", name="worker")
    io.subagent_event("w1", "message", sender_uuid="primary", text="Fix the tests")
    io.subagent_event("w1", "running")
    io.stream_output("On it.", final=True, coder_uuid="w1")

    sent = notifications(transport)
    assert [(session_id, u["sessionUpdate"]) for session_id, u in sent] == [
        ("s1", "agent_message_chunk")
    ]


async def test_nested_subagent_reports_to_its_parent(tmp_path):
    agent, transport, io, _coder = await delegating_agent(tmp_path)
    io.subagent_event("w1", "created", parent_uuid="primary", name="worker")
    io.subagent_event("h1", "created", parent_uuid="w1", name="helper")
    io.subagent_event("h1", "running")
    io.subagent_event("h1", "idle", stop_reason="error", error="boom")
    io.subagent_event("w1", "message", sender_uuid="h1", text="The helper agent failed")
    io.subagent_event("h1", "removed")

    child, grandchild = agent.subagents["w1"].session_id, agent.subagents["h1"].session_id
    sent = notifications(transport)
    assert sent[1][0] == child and sent[1][1]["sessionId"] == grandchild
    assert subagent_states(transport) == [
        (child, grandchild, {"state": "running"}),
        (
            child,
            grandchild,
            {
                "state": "idle",
                "stopReason": "error",
                "error": {"code": INTERNAL_ERROR, "message": "boom"},
            },
        ),
    ]
    reply = [(s, u) for s, u in sent if u["sessionUpdate"] == "session_message"]
    assert [s for s, _ in reply] == [grandchild, child]
    assert all(u["senderSessionId"] == grandchild for _, u in reply)
    # Once reaped, it can no longer be cancelled
    assert sent[-1] == (
        child,
        {"sessionUpdate": "subagent_update", "sessionId": grandchild, "capabilities": None},
    )


def answer(transport, request, option_id):
    transport.feed(
        {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {"outcome": {"outcome": "selected", "optionId": option_id}},
        }
    )


async def test_subagent_asks_permission_in_its_own_session(tmp_path):
    agent, transport, io, _coder = await delegating_agent(tmp_path)
    io.subagent_event("w1", "created", parent_uuid="primary", name="worker")
    io.subagent_event("w1", "running")
    child = agent.subagents["w1"].session_id
    # The parent's turn is over, but the sub-agent works on in the background
    agent._finish_turn()

    asking = asyncio.create_task(io.confirm_ask("Run tools?", coder_uuid="w1"))
    await settle()
    request = next(m for m in transport.sent if m.get("method") == "session/request_permission")
    assert request["params"]["sessionId"] == child
    answer(transport, request, "y")
    assert await asking is True
    assert [state["state"] for _, _, state in subagent_states(transport)] == [
        "running",
        "requires_action",
        "running",
    ]


async def test_cancelling_a_subagent_leaves_the_rest_running(tmp_path, monkeypatch):
    from cecli.helpers.agents.service import AgentService

    cancelled = []
    service = SimpleNamespace(cancel_sub_agent=cancelled.append)
    monkeypatch.setattr(AgentService, "get_instance", staticmethod(lambda coder: service))

    agent, transport, io, _coder = await delegating_agent(tmp_path)
    io.subagent_event("w1", "created", parent_uuid="primary", name="worker")
    io.subagent_event("w1", "running")
    child = agent.subagents["w1"].session_id
    asking = asyncio.create_task(io.confirm_ask("Run tools?", coder_uuid="w1"))
    await settle()

    # Cancelling the parent's turn leaves a background sub-agent's question open
    transport.feed({"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": "s1"}})
    await settle()
    assert not asking.done() and cancelled == []

    transport.feed({"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": child}})
    await settle()
    assert cancelled == ["w1"]
    assert await asking is False


# ── Config options ─────────────────────────────────────────────


def model_groups(option):
    """``{group name: [values]}`` of the grouped model picker."""
    return {group["name"]: [v["value"] for v in group["options"]] for group in option["options"]}


def test_config_options_list_configured_models(tmp_path):
    options = SessionConfig().options(StubCoder(tmp_path))
    mode, model, effort = options

    assert mode["currentValue"] == "code"  # any edit format other than a chat mode
    assert [v["value"] for v in mode["options"]] == [
        "code",
        "ask",
        "architect",
        "context",
        "agent",
        "agent-yolo",
    ]

    # Startup model and its alias collapse into one entry; tag overrides stay distinct
    assert model_groups(model) == {"Configured": ["fast", "smart", "gpt-y:high", "local/qwen"]}
    assert model["currentValue"] == "fast"
    assert model["options"][0]["options"][1]["description"] == "big-model"

    assert effort["category"] == "thought_level"
    assert effort["currentValue"] == "default"
    assert [v["value"] for v in effort["options"]] == ["default", "low", "medium", "high"]


def test_config_options_follow_the_running_model(tmp_path):
    config = SessionConfig()
    coder = StubCoder(tmp_path, model=StubModel("other-model", accepts=(), effort="xhigh"))
    model = current_value(config.options(coder), "model")
    assert model == "other-model"  # switched with a typed /model: listed first

    options = config.options(coder)
    assert model_groups(options[1])["Configured"][0] == "other-model"
    # An effort set elsewhere is shown even though it is not a standard choice
    assert options[2]["currentValue"] == "xhigh"

    coder.main_model = StubModel("claude-x", accepts=("thinking_tokens",), budget=2048)
    effort = config.options(coder)[2]
    assert effort["id"] == "thinking_tokens"
    assert effort["currentValue"] == "2k"
    # A model's own default budget slots in by size
    assert [v["value"] for v in effort["options"]] == ["0", "2k", "4k", "8k", "16k", "32k"]

    coder.main_model = StubModel("plain", accepts=())
    assert [o["id"] for o in config.options(coder)] == ["mode", "model"]


def test_model_picker_lists_providers_with_a_key(tmp_path, monkeypatch):
    monkeypatch.setattr(
        acp_config,
        "keyed_provider_models",
        lambda: [
            ("openai", "OpenAI", ["openai/gpt-5", "openai/gpt-5-mini"]),
            ("anthropic", "Anthropic", ["anthropic/claude-sonnet-4-5", "big-model"]),
        ],
    )
    coder = StubCoder(tmp_path)
    config = SessionConfig()

    model = config.options(coder)[1]
    # "big-model" is already listed as the "smart" alias
    assert model_groups(model) == {
        "Configured": ["fast", "smart", "gpt-y:high", "local/qwen"],
        "OpenAI": ["openai/gpt-5", "openai/gpt-5-mini"],
        "Anthropic": ["anthropic/claude-sonnet-4-5"],
    }
    assert config.command(coder, "model", "openai/gpt-5-mini") == "/model openai/gpt-5-mini"

    # The filter narrows the provider lists; configured models always stay
    coder.args.acp_models = ["mini", "claude-*-4"]
    model = SessionConfig().options(coder)[1]
    assert model_groups(model) == {
        "Configured": ["fast", "smart", "gpt-y:high", "local/qwen"],
        "OpenAI": ["openai/gpt-5-mini"],
        "Anthropic": ["anthropic/claude-sonnet-4-5"],
    }


def test_model_filter_matches_like_models_command():
    assert acp_config.matches_filter("anthropic/claude-sonnet-4-5", ["SONNET"])
    assert acp_config.matches_filter("openrouter/anthropic/claude-opus-4", ["anthropic/*"])
    assert not acp_config.matches_filter("openai/gpt-5", ["claude", "gemini-*"])


def test_config_choices_map_to_commands(tmp_path):
    config = SessionConfig()
    coder = StubCoder(tmp_path, model=StubModel("gpt-x", effort="high"))

    assert config.command(coder, "mode", "ask") == "/ask"
    assert config.command(coder, "mode", "code") is None  # already current
    assert config.command(coder, "model", "smart") == "/model smart"
    assert config.model_choice == "smart"
    assert config.command(coder, "reasoning_effort", "default") == "/reasoning-effort none"
    assert config.command(coder, "reasoning_effort", "low") == "/reasoning-effort low"
    with pytest.raises(ValueError):
        config.command(coder, "model", "not-configured")
    with pytest.raises(ValueError):
        config.command(coder, "thinking_tokens", "8k")  # not offered for this model

    coder.main_model = StubModel("claude-x", accepts=("thinking_tokens",), budget=8192)
    assert config.command(coder, "thinking_tokens", "0") == "/think-tokens 0"


def test_agent_mode_picks_the_agent_model(tmp_path):
    config = SessionConfig()
    coder = StubCoder(tmp_path, edit_format="agent")
    coder.agent_model = StubModel("big-model", effort="low")

    options = config.options(coder)
    assert current_value(options, "model") == "smart"
    assert current_value(options, "reasoning_effort") == "low"
    assert config.command(coder, "model", "fast") == "/agent-model fast"


def config_request(request_id, config_id, value, session_id="s1"):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "session/set_config_option",
        "params": {"sessionId": session_id, "configId": config_id, "value": value},
    }


async def test_set_config_option_runs_the_cecli_command(tmp_path):
    agent, transport = await ready_agent(tmp_path)
    waiting = asyncio.create_task(agent.next_input(StubCoder(tmp_path)))
    await settle()

    # Unchanged values answer at once; unknown ones are rejected
    transport.feed(config_request(3, "mode", "code"))
    transport.feed(config_request(4, "mode", "yolo"))
    await settle()
    assert current_value(transport.results()[3]["result"]["configOptions"], "mode") == "code"
    assert transport.results()[4]["error"]["code"] == INVALID_PARAMS

    transport.feed(config_request(5, "mode", "ask"))
    assert await waiting == "/ask"
    assert 5 not in transport.results()

    # /ask replaces the coder; the answer reflects the new one
    waiting = asyncio.create_task(agent.next_input(StubCoder(tmp_path, edit_format="ask")))
    await settle()
    options = transport.results()[5]["result"]["configOptions"]
    assert current_value(options, "mode") == "ask"
    # The client already has these options from the answer
    assert not any(u["sessionUpdate"] == "config_option_update" for u in transport.updates())
    waiting.cancel()


async def test_typed_commands_update_the_pickers(tmp_path):
    agent, transport = await ready_agent(tmp_path)
    coder = StubCoder(tmp_path)
    waiting = asyncio.create_task(agent.next_input(coder))
    await settle()
    transport.feed(prompt(3, "/ask"))
    await waiting

    waiting = asyncio.create_task(agent.next_input(StubCoder(tmp_path, edit_format="ask")))
    await settle()
    kinds = [u["sessionUpdate"] for u in transport.updates()]
    assert kinds[-2:] == ["config_option_update", "current_mode_update"]
    assert transport.updates()[-1]["currentModeId"] == "ask"
    # The pickers change before the prompt's response arrives
    assert transport.sent[-1]["id"] == 3

    # Legacy session/set_mode takes the same path
    transport.feed(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "session/set_mode",
            "params": {"sessionId": "s1", "modeId": "agent"},
        }
    )
    assert await waiting == "/agent"
    waiting = asyncio.create_task(agent.next_input(StubCoder(tmp_path, edit_format="agent")))
    await settle()
    assert transport.results()[4]["result"] == {}
    assert transport.updates()[-1] == {
        "sessionUpdate": "current_mode_update",
        "currentModeId": "agent",
    }
    waiting.cancel()


def test_yolo_mode_toggles_what_yolo_sets(tmp_path):
    config = SessionConfig()
    coder = StubCoder(tmp_path, edit_format="agent")
    coder.io.yes = None

    # From Agent, YOLO is only a settings change: no coder switch needed
    assert config.command(coder, "mode", "agent-yolo") is None
    assert coder.io.yes is True and coder.args.yes_always_commands is True
    assert current_value(config.options(coder), "mode") == "agent-yolo"

    # Back to Agent restores the confirmations
    assert config.command(coder, "mode", "agent") is None
    assert coder.io.yes is None and coder.args.yes_always_commands is False

    # From another mode, YOLO switches to agent mode too; leaving it turns it off
    coder.edit_format = "ask"
    assert config.command(coder, "mode", "agent-yolo") == "/agent"
    coder.edit_format = "agent"
    assert config.command(coder, "mode", "code") == "/code"
    assert coder.io.yes is None and coder.args.yes_always_commands is False

    # Typing /ask while in YOLO ends it too, so the picker never hides it
    assert config.command(coder, "mode", "agent-yolo") is None
    coder.edit_format = "ask"
    assert current_value(config.options(coder), "mode") == "ask"
    assert coder.io.yes is None and coder.args.yes_always_commands is False
    coder.edit_format = "agent"

    # Launched with --yolo, agent mode already shows as YOLO
    coder.args.yes_always_commands, coder.io.yes = True, True
    assert current_value(config.options(coder), "mode") == "agent-yolo"
    assert config.command(coder, "mode", "agent") is None
    assert coder.io.yes is None and coder.args.yes_always_commands is False


# ── Client MCP servers ─────────────────────────────────────────

ZED_SERVERS = [
    {
        "name": "GitHub",
        "command": "/usr/local/bin/github-mcp",
        "args": ["stdio"],
        "env": [{"name": "TOKEN", "value": "t"}],
    },
    {"type": "http", "name": "docs", "url": "https://example.com/mcp", "headers": []},
    {"type": "sse", "name": "events", "url": "https://example.com/sse"},
    {"name": "broken"},  # no command: ignored
]


def test_client_mcp_servers_become_cecli_configs():
    configs = to_cecli_configs(ZED_SERVERS)
    assert set(configs) == {"github", "docs", "events"}
    assert configs["github"] == {
        "transport": "stdio",
        "command": "/usr/local/bin/github-mcp",
        "args": ["stdio"],
        "env": {"TOKEN": "t"},
        "name": "GitHub",
    }
    assert configs["docs"]["transport"] == "http"
    assert configs["events"] == {
        "transport": "sse",
        "url": "https://example.com/sse",
        "headers": {},
        "name": "events",
    }


class FakeMcpManager:
    def __init__(self, *names):
        self.servers = {n: SimpleNamespace(name=n) for n in names}
        self.connected = set(names)
        self.calls = []

    def get_server(self, name):
        return self.servers.get(name.lower())

    @property
    def connected_servers(self):
        return [self.servers[n] for n in self.connected]

    async def add_server(self, server, connect=False):
        self.servers[server.name] = server
        self.calls.append(("add", server.name, type(server).__name__))
        if connect:
            self.connected.add(server.name)
        return True

    async def connect_server(self, name):
        self.connected.add(name)
        self.calls.append(("connect", name))
        return True

    async def disconnect_server(self, name):
        self.connected.discard(name)
        self.calls.append(("disconnect", name))
        return True


async def test_client_mcp_servers_sync_with_the_manager():
    logged = []
    servers = ClientMcpServers(logged.append)
    manager = FakeMcpManager("docs")  # cecli's own config already has "docs"

    servers.want(ZED_SERVERS)
    await servers.sync(manager)
    assert manager.calls == [
        ("add", "github", "McpServer"),
        ("add", "events", "SseServer"),
    ]
    assert any("cecli has one by that name" in line for line in logged)

    # A later session drops one server and keeps the other
    manager.calls.clear()
    servers.want(ZED_SERVERS[:1])
    await servers.sync(manager)
    assert manager.calls == [("disconnect", "events")]

    # Nothing pending: nothing happens
    manager.calls.clear()
    await servers.sync(manager)
    assert manager.calls == []


async def test_session_new_connects_client_mcp_servers_first(tmp_path):
    agent, transport = await ready_agent(tmp_path)
    transport.feed({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    await settle()
    capabilities = transport.results()[1]["result"]["agentCapabilities"]
    assert capabilities["mcpCapabilities"] == {"http": True, "sse": True}

    agent.mcp.want(ZED_SERVERS[:1])  # as bootstrap() records the first session/new
    coder = StubCoder(tmp_path)
    coder.mcp_manager = FakeMcpManager()
    waiting = asyncio.create_task(agent.next_input(coder))
    await settle()
    assert coder.mcp_manager.calls == [("add", "github", "McpServer")]
    assert transport.results()[2]["result"]["sessionId"] == "s1"
    waiting.cancel()
