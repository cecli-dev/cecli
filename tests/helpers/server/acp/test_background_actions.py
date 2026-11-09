"""Tests for cecli/background ACP actions."""

import base64
import platform
import sys
import time
import types

import pytest

from cecli.helpers.background_commands import HAS_PTY, BackgroundCommandManager
from cecli.helpers.server.acp.agent.agent import INVALID_PARAMS, AcpAgent, AcpError


# PTY-backed commands are only created on non-Windows platforms with termios support.
PTY_RESIZE_SUPPORTED = HAS_PTY and platform.system() != "Windows"


def make_agent():
    transport = types.SimpleNamespace(send=lambda msg: None)
    return AcpAgent(transport)


def call(agent, **params):
    return agent._on_cecli_background(params, None)


@pytest.fixture
def sleeper():
    key = BackgroundCommandManager.start_background_command(
        f'{sys.executable} -c "import time; time.sleep(30)"', use_pty=True
    )
    yield key
    BackgroundCommandManager.close_background_command(key)
    BackgroundCommandManager.signal_stop_all_background_commands()


def test_unknown_action_raises_invalid_params():
    with pytest.raises(AcpError) as err:
        call(make_agent(), action="nope")
    assert err.value.code == INVALID_PARAMS


@pytest.mark.parametrize("action", ["state", "snapshot", "input", "resize", "stop", "close"])
def test_missing_key_is_result_not_exception(action):
    params = {"action": action, "key": "missing"}
    if action == "input":
        params["base64"] = base64.b64encode(b"x").decode("ascii")

    result = call(make_agent(), **params)
    assert result == {"ok": False, "error": "not_found"}


def test_list_and_state_include_camel_case_fields(sleeper):
    agent = make_agent()
    listing = call(agent, action="list")
    keys = [entry["key"] for entry in listing["commands"]]
    assert sleeper in keys

    entry = call(agent, action="state", key=sleeper)["command"]
    for field in (
        "state",
        "exitCode",
        "endedAt",
        "signal",
        "needsInput",
        "lastPrompt",
        "cols",
        "rows",
        "pty",
        "inputOwner",
        "seq",
        "startSeq",
        "consumedAt",
    ):
        assert field in entry


def test_snapshot_returns_base64_ring(sleeper):
    result = call(make_agent(), action="snapshot", key=sleeper, since=0)
    assert result["seq"] >= result["startSeq"]
    assert isinstance(base64.b64decode(result["data"]), bytes)
    assert result["state"] in ("running", "needs_input")


def test_input_lease_conflict_and_release(sleeper):
    agent = make_agent()
    first = call(
        agent,
        action="input",
        key=sleeper,
        base64=base64.b64encode(b"u\n").decode("ascii"),
        owner="ui",
    )
    assert first["ok"] is True
    assert first["inputOwner"] == "ui"

    conflict = call(
        agent,
        action="input",
        key=sleeper,
        base64=base64.b64encode(b"a\n").decode("ascii"),
        owner="agent",
    )
    assert conflict == {"ok": False, "error": "input_locked"}

    released = call(agent, action="input", key=sleeper, base64="", owner=None, release=True)
    assert released["ok"] is True

    after = call(
        agent,
        action="input",
        key=sleeper,
        base64=base64.b64encode(b"a\n").decode("ascii"),
        owner="agent",
    )
    assert after["ok"] is True


def test_resize_reports_result(sleeper):
    result = call(make_agent(), action="resize", key=sleeper, cols=120, rows=40)
    assert result["cols"] == 120
    assert result["rows"] == 40
    assert result["resized"] is PTY_RESIZE_SUPPORTED
    result = call(make_agent(), action="input", key=sleeper, data="hello\n", owner="ui")
    assert result["ok"] is True
    assert result["accepted"] == len("hello\n")
    assert result["inputOwner"] == "ui"


def test_pipe_resize_reports_not_resized():
    key = BackgroundCommandManager.start_background_command(
        f'{sys.executable} -c "import time; time.sleep(5)"', use_pty=False
    )
    try:
        result = call(make_agent(), action="resize", key=key, cols=120, rows=40)
        assert result["resized"] is False
    finally:
        BackgroundCommandManager.close_background_command(key)
        BackgroundCommandManager.signal_stop_all_background_commands()


def test_release_accepts_missing_payload(sleeper):
    agent = make_agent()
    first = call(
        agent,
        action="input",
        key=sleeper,
        base64=base64.b64encode(b"u\n").decode("ascii"),
        owner="ui",
    )
    assert first["ok"] is True

    released = call(agent, action="input", key=sleeper, owner="ui", release=True)
    assert released["ok"] is True
    assert released["inputOwner"] is None


def test_stop_is_non_blocking_and_returns_stopping(sleeper):
    agent = make_agent()
    started = time.monotonic()
    result = call(agent, action="stop", key=sleeper, timeoutMs=5000)
    elapsed = time.monotonic() - started

    assert result["ok"] is True
    assert result["state"] == "stopping"
    assert elapsed < 0.2


def test_close_running_reports_closing(sleeper):
    result = call(make_agent(), action="close", key=sleeper)
    assert result == {"ok": True, "state": "closing"}


def test_stop_all_signals_without_waiting(sleeper):
    started = time.monotonic()
    result = call(make_agent(), action="stop_all")
    elapsed = time.monotonic() - started

    assert result["ok"] is True
    assert result["state"] == "stopping"
    assert elapsed < 0.2


def test_emitter_lifecycle_sets_and_clears_sink():
    agent = make_agent()
    agent._start_background_emitter()
    assert BackgroundCommandManager.event_sink is agent._background_emitter

    agent.shutdown()
    assert BackgroundCommandManager.event_sink is None
    assert agent._background_emitter is None


def test_background_emitter_sends_single_wrapped_notification():
    sent = []
    transport = types.SimpleNamespace(send=sent.append)
    agent = AcpAgent(transport)
    agent._start_background_emitter()

    key = BackgroundCommandManager.start_background_command("echo wired", use_pty=True)
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not sent:
            time.sleep(0.02)
    finally:
        agent._background_emitter.close()
        BackgroundCommandManager.close_background_command(key)
        BackgroundCommandManager.set_event_sink(None)

    messages = [m for m in sent if m.get("method") == "cecli/background/event"]
    assert messages
    params = messages[0]["params"]
    assert params.get("event")
    assert params.get("key") == key
    assert "method" not in params
