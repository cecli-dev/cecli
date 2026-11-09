"""Phase 3 terminal retention, generations, limits, and cli dispatch."""

import asyncio
import json
from pathlib import Path

from desktop.server import DesktopServer
from desktop.terminal import (
    TERMINAL_MAX_PER_BRIDGE,
    ConPtyTerminalSession,
    PipeTerminalSession,
    TerminalBuffer,
    TerminalError,
    TerminalManager,
    replay_offsets,
)
from desktop.tests.test_cli_registry import FakeBridge, FakeSessions


def make_manager(**kwargs):
    kwargs.setdefault("enabled", True)
    kwargs.setdefault("shell", "/bin/sh")
    kwargs.setdefault("backend", "pty")
    return TerminalManager(**kwargs)


async def until(predicate, timeout=4.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("timed out waiting for terminal output")
        await asyncio.sleep(0.005)


def test_stop_retains_and_close_removes():
    async def run():
        manager = make_manager()
        session = manager.get_or_create("b1", "/tmp")
        await session.start()
        await session.write_async(b"echo phase3-retain\n")
        await until(lambda: b"phase3-retain" in session.buffer.snapshot(None)[1])

        await manager.stop("b1")
        retained = manager.get("b1")
        assert retained is not None
        assert retained.running is False
        assert retained.ended_at is not None
        assert retained.exit_code is not None
        assert retained.buffer.seq > 0

        await manager.close("b1")
        assert manager.get("b1") is None
        await manager.shutdown()

    asyncio.run(run())


def test_reaper_keeps_within_ttl_and_drops_after():
    async def run():
        manager = make_manager()
        session = manager.get_or_create("b1", "/tmp")
        await session.start()
        await manager.stop("b1")
        ended = manager.get("b1").ended_at

        await manager.reap(now=ended + 10)
        assert manager.get("b1") is not None
        await manager.reap(now=ended + 901)
        assert manager.get("b1") is None
        await manager.shutdown()

    asyncio.run(run())


def test_generations_mint_new_ids_on_restart():
    async def run():
        manager = make_manager()
        first = manager.get_or_create("b1", "/tmp")
        assert first.id == "term:b1:1"
        assert manager.get_or_create("b1", "/tmp") is first

        await first.start()
        await manager.stop("b1")
        second = manager.get_or_create("b1", "/tmp")
        assert second.id == "term:b1:2"
        assert second.id != first.id
        await manager.shutdown()

    asyncio.run(run())


def test_per_bridge_and_global_limits():
    async def run():
        manager = make_manager()
        created = 0
        for _ in range(6):
            try:
                session = manager.get_or_create("b1", "/tmp")
                await session.start()
                await manager.stop("b1")
                created += 1
            except TerminalError as err:
                assert err.status == 409
                break
        assert created == TERMINAL_MAX_PER_BRIDGE
        await manager.shutdown()

        global_manager = make_manager()
        for index in range(8):
            global_manager.get_or_create(f"multi{index}", "/tmp")
        try:
            global_manager.get_or_create("overflow", "/tmp")
        except TerminalError as err:
            assert err.status == 409
        else:
            raise AssertionError("global terminal cap was not enforced")
        await global_manager.shutdown()

    asyncio.run(run())


def test_terminals_and_state_payload():
    async def run():
        manager = make_manager()
        session = manager.get_or_create("b1", "/tmp")
        await session.start()
        payload = manager.terminals("b1")
        assert len(payload) == 1
        assert payload[0]["id"] == "term:b1:1"
        state = manager.state("b1")
        assert state["id"] == "term:b1:1"
        assert "endedAt" in state
        assert state["backend"] in ("pty", "pipe", "conpty")
        await manager.shutdown()

    asyncio.run(run())


def test_pipe_backend_runs_and_reports_non_null_exit():
    async def run():
        manager = make_manager(backend="pipe")
        session = manager.get_or_create("b1", "/tmp")
        assert isinstance(session, PipeTerminalSession)
        await session.start()
        await session.write_async(b"echo pipe-phase3\n")
        await until(lambda: b"pipe-phase3" in session.buffer.snapshot(None)[1])
        await manager.stop("b1")
        assert manager.get("b1").exit_code is not None
        await manager.shutdown()

    asyncio.run(run())


def test_backend_selection_and_conpty_class():
    assert ConPtyTerminalSession.backend == "conpty"
    assert make_manager(backend="conpty").backend == "conpty"
    try:
        TerminalManager(enabled=True, shell="/bin/sh", backend="bogus")
    except TerminalError as err:
        assert err.status == 400
    else:
        raise AssertionError("unknown backend was accepted")


def test_cli_dispatch_isolated_per_bridge():
    async def run():
        manager = make_manager()
        bridge = FakeBridge({"commands": []})
        server = DesktopServer(FakeSessions(bridge), Path("."), cli_enabled=True)
        server.terminal = manager

        status, payload, _ = await server._terminal_start(b'{"bridgeId": "s1"}')
        assert status == 200
        terminal_id = json.loads(payload)["terminal"]["id"]
        assert terminal_id == "term:s1:1"

        status, payload, _ = await server._route("GET", "/api/cli/state", b"", {"bridgeId": ["s1"]})
        state = json.loads(payload)
        assert [item["id"] for item in state["terminals"]] == [terminal_id]

        status, _, _ = await server._route(
            "POST",
            "/api/cli/resize",
            json.dumps({"bridgeId": "s1", "cliId": terminal_id, "cols": 120, "rows": 40}).encode(),
            {},
        )
        assert status == 200

        status, _, _ = await server._route(
            "POST",
            "/api/cli/stop",
            json.dumps({"bridgeId": "s1", "cliId": terminal_id}).encode(),
            {},
        )
        assert status == 200
        assert manager.get_by_id(terminal_id).running is False

        foreign = manager.get_or_create("s2", "/tmp")
        before = foreign.ended_at
        status, _, _ = await server._route(
            "POST",
            "/api/cli/stop",
            json.dumps({"bridgeId": "s1", "cliId": foreign.id}).encode(),
            {},
        )
        assert status == 404
        assert foreign.ended_at == before

        status, _, _ = await server._route(
            "POST",
            "/api/cli/close",
            json.dumps({"bridgeId": "s1", "cliId": terminal_id}).encode(),
            {},
        )
        assert status == 200
        assert manager.get("s1") is None
        await manager.shutdown()

    asyncio.run(run())


def test_stop_retains_close_removes():
    async def run():
        manager = make_manager()
        session = manager.get_or_create("b1", "/tmp")
        await session.start()
        await manager.stop("b1")
        assert manager.get("b1") is not None
        assert manager.get("b1").ended_at is not None
        await manager.close("b1")
        assert manager.get("b1") is None
        await manager.shutdown()

    asyncio.run(run())


def test_ttl_reaper_keeps_then_drops():
    async def run():
        manager = make_manager()
        session = manager.get_or_create("b1", "/tmp")
        await session.start()
        await manager.stop("b1")
        ended = session.ended_at
        await manager.reap(now=ended + 5)
        assert manager.get("b1") is not None
        await manager.reap(now=ended + 901)
        assert manager.get("b1") is None
        await manager.shutdown()

    asyncio.run(run())


def test_generation_ids_and_restart():
    async def run():
        manager = make_manager()
        first = manager.get_or_create("b1", "/tmp")
        assert first.id == "term:b1:1"
        await first.start()
        await manager.stop("b1")
        second = manager.get_or_create("b1", "/tmp")
        assert second.id == "term:b1:2"
        await manager.shutdown()

    asyncio.run(run())


def test_per_bridge_retention_limit():
    async def run():
        manager = make_manager()
        created = 0
        for _ in range(6):
            try:
                session = manager.get_or_create("b1", "/tmp")
                await session.start()
                await manager.stop("b1")
                created += 1
            except TerminalError as err:
                assert err.status == 409
                break
        assert created == TERMINAL_MAX_PER_BRIDGE
        await manager.shutdown()

    asyncio.run(run())


def test_global_limit_counts_live_sessions_only():
    async def run():
        manager = make_manager()
        for index in range(8):
            session = manager.get_or_create(f"multi{index}", "/tmp")
            await session.start()
            await manager.stop(f"multi{index}")
        session = manager.get_or_create("late", "/tmp")
        assert session.id == "term:late:1"
        await manager.shutdown()

    asyncio.run(run())


def test_state_and_terminals_payload():
    async def run():
        manager = make_manager()
        session = manager.get_or_create("b1", "/tmp")
        await session.start()
        payload = manager.terminals("b1")
        assert len(payload) == 1
        assert payload[0]["id"] == session.id
        state = manager.state("b1")
        assert state["id"] == session.id
        assert "endedAt" in state
        await manager.shutdown()

    asyncio.run(run())


def test_pipe_backend_falls_back_and_runs():
    async def run():
        manager = make_manager(backend="pipe")
        session = manager.get_or_create("b1", "/tmp")
        assert isinstance(session, PipeTerminalSession)
        await session.start()
        await session.write_async(b"echo pipe-fallback\n")
        await until(lambda: b"pipe-fallback" in session.buffer.snapshot(None)[1])
        await manager.stop("b1")
        assert manager.get("b1").ended_at is not None
        await manager.shutdown()

    asyncio.run(run())


def test_pipe_fallback_session_and_resize():
    async def run():
        manager = make_manager(backend="pipe")
        session = manager.get_or_create("b1", "/tmp")
        session.resize(90, 20)
        assert (session.cols, session.rows) == (90, 20)
        await session.start()
        await manager.stop("b1")
        assert manager.get("b1").exit_code is not None
        await manager.shutdown()

    asyncio.run(run())


def test_unknown_backend_rejected_and_conpty_kept():
    assert make_manager(backend="conpty").backend == "conpty"
    assert hasattr(ConPtyTerminalSession, "backend")
    try:
        TerminalManager(enabled=True, shell="/bin/sh", backend="nope")
    except TerminalError as err:
        assert err.status == 400
    else:
        raise AssertionError("unknown backend was accepted")


def test_cli_dispatch_keeps_terminal_ids_out_of_acp():
    async def run():
        manager = make_manager()
        bridge = FakeBridge({"commands": []})
        server = DesktopServer(FakeSessions(bridge), Path("."), cli_enabled=True)
        server.terminal = manager
        await server._terminal_start(b'{"bridgeId": "s1"}')
        status, _, _ = await server._route(
            "POST",
            "/api/cli/resize",
            b'{"bridgeId": "s1", "cliId": "term:s1:1", "cols": 120, "rows": 40}',
            {},
        )
        assert status == 200
        assert bridge.calls == []
        await manager.shutdown()

    asyncio.run(run())


def test_cli_input_dispatch_on_stopped_terminal_conflicts():
    async def run():
        manager = make_manager()
        bridge = FakeBridge({"commands": []})
        server = DesktopServer(FakeSessions(bridge), Path("."), cli_enabled=True)
        server.terminal = manager
        await server._terminal_start(b'{"bridgeId": "s1"}')
        await server._terminal_stop(b'{"bridgeId": "s1"}')
        status, _, _ = await server._route(
            "POST",
            "/api/cli/input",
            b'{"bridgeId": "s1", "cliId": "term:s1:1", "data": "x"}',
            {},
        )
        assert status == 409
        assert bridge.calls == []
        await manager.shutdown()

    asyncio.run(run())


def test_buffer_replay_offsets_match_fix_a_contract():
    buffer = TerminalBuffer()
    assert buffer.append(b"abc") == 3

    seq, data, reset = buffer.snapshot(1)
    assert (seq, data, reset) == (3, b"bc", False)
    assert seq - len(data) == 1

    seq, data, reset = buffer.snapshot(3)
    assert (seq, data, reset) == (3, b"", False)

    seq, data, reset = buffer.snapshot(0)
    assert (seq, data, reset) == (3, b"abc", False)
    assert seq - len(data) == 0


def test_buffer_stale_ahead_cursor_resets_to_full_ring():
    buffer = TerminalBuffer()
    buffer.append(b"abc")
    seq, data, reset = buffer.snapshot(10)
    assert reset is True
    assert (seq, data) == (3, b"abc")


def test_retained_session_replays_after_stop():
    async def run():
        manager = make_manager()
        session = manager.get_or_create("b1", "/tmp")
        await session.start()
        await session.write_async(b"echo replay-after-stop\n")
        await until(lambda: b"replay-after-stop" in session.buffer.snapshot(None)[1])
        await manager.stop("b1")

        retained = manager.get("b1")
        assert retained is not None and retained.running is False
        seq, data, reset = retained.buffer.snapshot(0)
        assert reset is False
        assert b"replay-after-stop" in data
        assert seq == retained.buffer.seq
        await manager.shutdown()

    asyncio.run(run())


def test_replay_offsets_fix_a_contract():
    assert replay_offsets(3, 3, None, False) == (0, 0)
    assert replay_offsets(3, 2, 1, False) == (1, 1)
    assert replay_offsets(3, 0, 3, False) == (3, 3)
    assert replay_offsets(3, 3, 10, True) == (0, 0)
