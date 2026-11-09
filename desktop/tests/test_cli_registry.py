"""Tests for the desktop CLI registry and /api/cli routing."""

import asyncio
import base64
import inspect
import json
from pathlib import Path

from desktop.cli_registry import CliRegistry, error_code, map_semantic_error
from desktop.server import DesktopServer


def mirror_with_output():
    registry = CliRegistry(enabled=True)
    mirror = registry.mirror("s1")
    mirror.apply_event(
        {"event": "started", "key": "bg_1", "command": {"key": "bg_1", "state": "running"}}
    )
    mirror.apply_event(
        {
            "event": "output",
            "key": "bg_1",
            "seq": 3,
            "data": base64.b64encode(b"abc").decode(),
        }
    )
    return registry, mirror


def test_output_dedupes_replayed_seq():
    _, mirror = mirror_with_output()
    mirror.apply_event(
        {"event": "output", "key": "bg_1", "seq": 3, "data": base64.b64encode(b"abc").decode()}
    )
    snap = mirror.snapshot("bg_1")
    assert snap["data"] == b"abc"
    assert snap["seq"] == 3
    assert snap["startSeq"] == 0


def test_snapshot_fix_a_offsets():
    _, mirror = mirror_with_output()
    assert mirror.snapshot("bg_1", None)["seq"] == 3
    assert mirror.snapshot("bg_1", 1)["data"] == b"bc"
    assert mirror.snapshot("bg_1", 3)["data"] == b""
    reset = mirror.snapshot("bg_1", 0)
    assert reset["startSeq"] == 0
    assert reset["reset"] is False
    ahead = mirror.snapshot("bg_1", 10)
    assert ahead["reset"] is True
    assert ahead["data"] == b"abc"
    assert ahead["startSeq"] == 0


def test_lag_reset_preserves_subscriber_signal():
    _, mirror = mirror_with_output()
    queue = mirror.subscribe()
    while not queue.empty():
        queue.get_nowait()
    for queue_item in list(mirror._subscribers):
        while True:
            try:
                queue_item.get_nowait()
            except asyncio.QueueEmpty:
                break
    for index in range(1000):
        mirror.apply_event(
            {
                "event": "output",
                "key": "bg_1",
                "seq": 4 + index,
                "data": base64.b64encode(b"x").decode(),
            }
        )
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    assert any(item.get("type") == "reset" for item in items)


def test_cli_pane_gate_payload():
    assert CliRegistry(enabled=False).state_payload("s1")["enabled"] is False
    payload = CliRegistry(enabled=True).state_payload("s1")
    assert set(payload) == {"enabled", "background", "rawBackground", "inputLease", "inputOwner"}


def test_error_mapping():
    assert map_semantic_error("not_found") == 404
    assert map_semantic_error("not_running") == 409
    assert map_semantic_error("input_locked") == 423
    assert map_semantic_error("queue_full") == 429
    assert map_semantic_error("too_large") == 413
    assert error_code({"ok": True}) is None
    assert error_code({"ok": False, "error": "not_found"}) == 404


class FakeBridge:
    bridge_id = "s1"
    workspace = "/tmp/ws"

    def __init__(self, result):
        self.result = result
        self.calls = []

    async def call_extension(self, method, params):
        self.calls.append(params)
        return dict(self.result)


class FakeSessions:
    background_event_sink = None

    def __init__(self, bridge):
        self.bridge = bridge

    def get(self, bridge_id):
        return self.bridge

    def snapshot(self, bridge_id):
        return {"bridgeId": bridge_id}


def make_server(result, cli_enabled=True):
    bridge = FakeBridge(result)
    return DesktopServer(FakeSessions(bridge), Path("."), cli_enabled=cli_enabled), bridge


def test_post_cli_state_maps_not_found_to_404():
    server, _ = make_server({"ok": False, "error": "not_found"})
    status, payload, _ = asyncio.run(
        server._route("POST", "/api/cli/state", b'{"bridgeId": "s1", "key": "missing"}', {})
    )
    assert status == 404
    assert json.loads(payload)["ok"] is False


def test_post_cli_requires_bridge_id():
    server, _ = make_server({"ok": True})
    status, payload, _ = asyncio.run(server._route("POST", "/api/cli/state", b"{}", {}))
    assert status == 400
    assert b"bridgeId" in payload


def test_post_cli_gate_disabled():
    server, _ = make_server({"ok": True}, cli_enabled=False)
    status, _, _ = asyncio.run(server._route("POST", "/api/cli/state", b'{"bridgeId": "s1"}', {}))
    assert status == 403


def test_state_reports_cli_pane_enabled(DummySessions=None):
    bridge = FakeBridge({"commands": []})
    sessions = FakeSessions(bridge)
    sessions.snapshot = lambda bridge_id: {"bridgeId": bridge_id, "sessions": []}
    sessions.get = lambda bridge_id=None: bridge
    server = DesktopServer(sessions, Path("."), cli_enabled=True)
    status, payload, _ = asyncio.run(server._route("GET", "/api/state", b"", {}))
    assert status == 200
    assert json.loads(payload)["cliPane"]["enabled"] is True
    assert json.loads(payload)["cliPane"]["background"] is True


class FakeWriter:
    def __init__(self):
        self.text = ""

    def write(self, data):
        self.text += data.decode("utf-8")

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass


def registry_server():
    registry = CliRegistry(enabled=True)
    bridge = FakeBridge({"commands": []})
    server = DesktopServer(FakeSessions(bridge), Path("."), cli_enabled=True)
    server.cli = registry
    return server, registry, registry.mirror("s1")


def stream_frames(text):
    frames = []
    for line in text.splitlines():
        if line.startswith("data: "):
            frames.append(json.loads(line[len("data: ") :]))
    return frames


async def until(predicate, timeout=2.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("timed out waiting for stream output")
        await asyncio.sleep(0.001)


async def stop_stream(task):
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)


def test_get_cli_state_alias_exposes_raw_cli_id():
    server, _, mirror = registry_server()
    mirror.apply_event(
        {"event": "started", "key": "bg_9", "command": {"key": "bg_9", "state": "running"}}
    )
    status, payload, _ = asyncio.run(
        server._route("GET", "/api/cli/state", b"", {"bridgeId": ["s1"]})
    )
    data = json.loads(payload)
    assert status == 200
    assert data["ok"] is True
    assert data["bridgeId"] == "s1"
    assert data["workspace"] == "/tmp/ws"
    assert isinstance(data["terminals"], list)
    assert data["background"][0]["cliId"] == "bg_9"
    assert data["background"][0]["key"] == "bg_9"


def test_get_cli_state_alias_respects_gate():
    server, _, _ = registry_server()
    server.cli_enabled = False
    status, payload, _ = asyncio.run(
        server._route("GET", "/api/cli/state", b"", {"bridgeId": ["s1"]})
    )
    assert status == 403
    assert json.loads(payload)["ok"] is False


def test_post_cli_maps_cli_id_to_key():
    server, bridge = make_server({"ok": True})
    asyncio.run(
        server._route(
            "POST",
            "/api/cli/input",
            b'{"bridgeId": "s1", "cliId": "bg_1", "data": "hi"}',
            {},
        )
    )
    assert bridge.calls[-1]["key"] == "bg_1"
    assert "cliId" not in bridge.calls[-1]


def test_cli_stream_uses_cli_id_and_isolates_tabs():
    server, _, mirror = registry_server()
    for command_key, text in (("bg_1", b"one"), ("bg_2", b"two")):
        mirror.apply_event(
            {"event": "started", "key": command_key, "command": {"key": command_key}}
        )
        mirror.apply_event(
            {
                "event": "output",
                "key": command_key,
                "seq": len(text),
                "data": base64.b64encode(text).decode(),
            }
        )

    writer = FakeWriter()
    query = {"bridgeId": ["s1"], "cliId": ["bg_1"], "since": ["0"]}

    async def run():
        task = asyncio.ensure_future(server._serve_cli_stream(None, writer, query))
        await asyncio.sleep(0.05)
        mirror.apply_event(
            {
                "event": "output",
                "key": "bg_2",
                "seq": 6,
                "data": base64.b64encode(b"xxx").decode(),
            }
        )
        mirror.apply_event(
            {
                "event": "output",
                "key": "bg_1",
                "seq": 6,
                "data": base64.b64encode(b"yyy").decode(),
            }
        )
        await asyncio.sleep(0.05)
        await stop_stream(task)

    asyncio.run(run())
    frames = stream_frames(writer.text)
    ready = next(frame for frame in frames if frame.get("type") == "ready")
    assert ready["cliId"] == "bg_1"
    assert ready["seq"] == 0
    assert ready["startSeq"] == 0
    outputs = [frame for frame in frames if frame.get("type") == "output"]
    assert all(frame["cliId"] == "bg_1" for frame in outputs)
    assert base64.b64decode(outputs[0]["data"]) == b"one"
    assert b"yyy" in [base64.b64decode(frame["data"]) for frame in outputs]


def test_cli_stream_replays_from_since_offset():
    server, _, mirror = registry_server()
    mirror.apply_event({"event": "started", "key": "bg_1", "command": {"key": "bg_1"}})
    mirror.apply_event(
        {
            "event": "output",
            "key": "bg_1",
            "seq": 3,
            "data": base64.b64encode(b"abc").decode(),
        }
    )

    writer = FakeWriter()
    query = {"bridgeId": ["s1"], "cliId": ["bg_1"], "since": ["1"]}

    async def run():
        task = asyncio.ensure_future(server._serve_cli_stream(None, writer, query))
        await asyncio.sleep(0.05)
        await stop_stream(task)

    asyncio.run(run())
    frames = stream_frames(writer.text)
    ready = next(frame for frame in frames if frame.get("type") == "ready")
    assert ready["seq"] == 1
    outputs = [frame for frame in frames if frame.get("type") == "output"]
    assert base64.b64decode(outputs[0]["data"]) == b"bc"
    assert outputs[0]["seq"] == 3


def test_cli_stream_lag_resets_and_resnapshots():
    server, _, mirror = registry_server()
    mirror.apply_event({"event": "started", "key": "bg_1", "command": {"key": "bg_1"}})
    mirror.apply_event(
        {
            "event": "output",
            "key": "bg_1",
            "seq": 3,
            "data": base64.b64encode(b"abc").decode(),
        }
    )

    writer = FakeWriter()
    query = {"bridgeId": ["s1"], "cliId": ["bg_1"], "since": ["0"]}

    async def run():
        task = asyncio.ensure_future(server._serve_cli_stream(None, writer, query))
        await asyncio.sleep(0.05)
        mirror.apply_event(
            {
                "event": "output",
                "key": "bg_1",
                "seq": 9,
                "data": base64.b64encode(b"zzz").decode(),
            }
        )
        await asyncio.sleep(0.05)
        await stop_stream(task)

    asyncio.run(run())
    frames = stream_frames(writer.text)
    assert any(frame.get("type") == "reset" for frame in frames)
    data_frames = [base64.b64decode(frame["data"]) for frame in frames if "data" in frame]
    assert any(b"abc" in data for data in data_frames)
    assert any(b"zzz" in data for data in data_frames)


def test_get_cli_state_seeds_cold_mirror_from_acp():
    bridge = FakeBridge({"commands": [{"key": "bg_5", "state": "running"}]})
    server = DesktopServer(FakeSessions(bridge), Path("."), cli_enabled=True)
    status, payload, _ = asyncio.run(
        server._route("GET", "/api/cli/state", b"", {"bridgeId": ["s1"]})
    )
    data = json.loads(payload)
    assert status == 200
    assert bridge.calls[0]["action"] == "list"
    assert data["background"][0]["cliId"] == "bg_5"


def test_background_event_sink_is_synchronous():
    server, _, mirror = registry_server()
    assert not inspect.iscoroutinefunction(server._on_background_event)
    server._on_background_event("s1", {"event": "started", "key": "bg_3"})
    assert "bg_3" in mirror.entries


def test_cli_stream_since_end_appends_live_frame():
    server, _, mirror = registry_server()
    mirror.apply_event({"event": "started", "key": "bg_1", "command": {"key": "bg_1"}})
    mirror.apply_event(
        {
            "event": "output",
            "key": "bg_1",
            "seq": 3,
            "data": base64.b64encode(b"abc").decode(),
        }
    )

    writer = FakeWriter()
    query = {"bridgeId": ["s1"], "cliId": ["bg_1"], "since": ["3"]}

    async def run():
        task = asyncio.ensure_future(server._serve_cli_stream(None, writer, query))
        await until(lambda: "ready" in writer.text)
        mirror.apply_event(
            {
                "event": "output",
                "key": "bg_1",
                "seq": 6,
                "data": base64.b64encode(b"def").decode(),
            }
        )
        await until(lambda: b"def" in _stream_data(writer.text))
        await stop_stream(task)

    asyncio.run(run())
    frames = stream_frames(writer.text)
    ready = next(frame for frame in frames if frame.get("type") == "ready")
    assert ready["seq"] == 3
    assert not any(frame.get("type") == "reset" for frame in frames)
    outputs = [frame for frame in frames if frame.get("type") == "output"]
    assert base64.b64decode(outputs[-1]["data"]) == b"def"


def test_cli_stream_stale_cursor_resets_and_replays_ring():
    server, _, mirror = registry_server()
    mirror.apply_event({"event": "started", "key": "bg_1", "command": {"key": "bg_1"}})
    mirror.apply_event(
        {
            "event": "output",
            "key": "bg_1",
            "seq": 3,
            "data": base64.b64encode(b"abc").decode(),
        }
    )

    writer = FakeWriter()
    query = {"bridgeId": ["s1"], "cliId": ["bg_1"], "since": ["10"]}

    async def run():
        task = asyncio.ensure_future(server._serve_cli_stream(None, writer, query))
        await until(lambda: "ready" in writer.text)
        await stop_stream(task)

    asyncio.run(run())
    frames = stream_frames(writer.text)
    reset = next(frame for frame in frames if frame.get("type") == "reset")
    assert reset["seq"] == 0
    ready = next(frame for frame in frames if frame.get("type") == "ready")
    assert ready["seq"] == 0
    outputs = [frame for frame in frames if frame.get("type") == "output"]
    assert base64.b64decode(outputs[0]["data"]) == b"abc"


def test_cli_stream_uses_last_event_id_header():
    server, _, mirror = registry_server()
    mirror.apply_event({"event": "started", "key": "bg_1", "command": {"key": "bg_1"}})
    mirror.apply_event(
        {
            "event": "output",
            "key": "bg_1",
            "seq": 3,
            "data": base64.b64encode(b"abc").decode(),
        }
    )

    writer = FakeWriter()
    query = {"bridgeId": ["s1"], "cliId": ["bg_1"]}

    async def run():
        task = asyncio.ensure_future(
            server._serve_cli_stream(None, writer, query, {"last-event-id": "1"})
        )
        await until(lambda: "ready" in writer.text)
        await stop_stream(task)

    asyncio.run(run())
    frames = stream_frames(writer.text)
    ready = next(frame for frame in frames if frame.get("type") == "ready")
    assert ready["seq"] == 1
    outputs = [frame for frame in frames if frame.get("type") == "output"]
    assert base64.b64decode(outputs[0]["data"]) == b"bc"
    assert "id: 3\n" in writer.text


def test_cli_stream_emits_first_class_needs_input_frame():
    server, _, mirror = registry_server()
    mirror.apply_event({"event": "started", "key": "bg_1", "command": {"key": "bg_1"}})

    writer = FakeWriter()
    query = {"bridgeId": ["s1"], "cliId": ["bg_1"], "since": ["0"]}

    async def run():
        task = asyncio.ensure_future(server._serve_cli_stream(None, writer, query))
        await until(lambda: "ready" in writer.text)
        mirror.apply_event({"event": "needs_input", "key": "bg_1", "prompt": "Password:"})
        await until(lambda: '"needsInput":true' in writer.text)
        await stop_stream(task)

    asyncio.run(run())
    frames = stream_frames(writer.text)
    frame = next(frame for frame in frames if frame.get("type") == "state")
    assert frame["cliId"] == "bg_1"
    assert frame["key"] == "bg_1"
    assert frame["lastPrompt"] == "Password:"


def test_background_event_publishes_cli_event():
    published = []

    class PublishingSessions(FakeSessions):
        def publish(self, event):
            published.append(event)

    bridge = FakeBridge({"commands": []})
    server = DesktopServer(PublishingSessions(bridge), Path("."), cli_enabled=True)
    server._on_background_event(
        "s1", {"event": "needs_input", "key": "bg_1", "prompt": "Password:"}
    )
    server._on_background_event("s1", {"event": "output", "key": "bg_1", "seq": 3, "data": "YWJj"})

    assert len(published) == 1
    event = published[0]
    assert event["type"] == "cli"
    assert event["bridgeId"] == "s1"
    assert event["event"] == "needs_input"
    assert event["cliId"] == "bg_1"
    assert event["lastPrompt"] == "Password:"


def _stream_data(text):
    return [
        base64.b64decode(frame["data"])
        for frame in stream_frames(text)
        if frame.get("type") == "output" and frame.get("data")
    ]


def test_discard_drops_entry_and_ring():
    _, mirror = mirror_with_output()
    mirror.discard("bg_1")
    assert "bg_1" not in mirror.entries
    assert mirror.snapshot("bg_1")["data"] == b""


def test_close_call_discards_mirror_entry():
    registry, mirror = mirror_with_output()

    class FakeBridge:
        bridge_id = "s1"

        async def call_extension(self, method, payload):
            return {"ok": True, "state": "closed"}

    result = asyncio.run(registry.call(FakeBridge(), "close", {"key": "bg_1"}))
    assert result["ok"] is True
    assert "bg_1" not in mirror.entries


def test_normalize_cli_key_accepts_ui_tab_ids():
    from desktop.server import _normalize_cli_key

    assert _normalize_cli_key("s1", "bg:s1:bg_1") == "bg_1"
    assert _normalize_cli_key("s1", "bg_1") == "bg_1"
    assert _normalize_cli_key("s1", "bg:s2:bg_1") == "bg:s2:bg_1"
    assert _normalize_cli_key("s1", None) is None
