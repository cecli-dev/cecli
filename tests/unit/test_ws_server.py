"""Unit tests for cecli/helpers/server/ws_server.py — WebSocket signal bridge."""

from __future__ import annotations

import asyncio
import json
import queue

import pytest
import websockets

from cecli.helpers import queues
from cecli.helpers.server import signals
from cecli.helpers.server.ws_server import WebSocketSignalBridge, run_ws_server


@pytest.fixture(autouse=True)
def clear_queues():
    """Clear the global queue registry before each test."""
    queues._per_coder_queues.clear()
    queues._primary_coder_id = None
    yield
    queues._per_coder_queues.clear()


class TestWebSocketSignalBridgeStartStop:
    """Tests for WebSocketSignalBridge start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        """Starting the bridge creates a server that can be stopped cleanly."""
        bridge = WebSocketSignalBridge(port=0)  # OS-assigned port
        await bridge.start()
        assert bridge.port > 0
        assert bridge._server is not None
        await bridge.stop()
        assert bridge._server is None

    @pytest.mark.asyncio
    async def test_double_stop_is_safe(self):
        """Stopping an already-stopped bridge does not raise."""
        bridge = WebSocketSignalBridge(port=0)
        await bridge.start()
        await bridge.stop()
        # Second stop should be a no-op
        await bridge.stop()

    @pytest.mark.asyncio
    async def test_custom_host_and_port(self):
        """Bridge can be started on a specific host and port."""
        bridge = WebSocketSignalBridge(port=0, host="127.0.0.1")
        await bridge.start()
        assert bridge.host == "127.0.0.1"
        assert bridge.port > 0
        await bridge.stop()


class TestWebSocketSignalBridgeSubprotocolNegotiation:
    """Tests for WebSocket subprotocol negotiation."""

    @pytest.mark.asyncio
    async def test_connect_without_subprotocol(self):
        """Client connecting without a subprotocol is accepted."""
        bridge = WebSocketSignalBridge(port=0)
        await bridge.start()

        uri = f"ws://{bridge.host}:{bridge.port}"
        async with websockets.connect(uri) as ws:
            assert ws.subprotocol is None

        await bridge.stop()

    @pytest.mark.asyncio
    async def test_connect_with_acp_v1_subprotocol(self):
        """Client connecting with 'acp.v1' subprotocol is accepted."""
        bridge = WebSocketSignalBridge(port=0)
        await bridge.start()

        uri = f"ws://{bridge.host}:{bridge.port}"
        async with websockets.connect(uri, subprotocols=["acp.v1"]) as ws:
            assert ws.subprotocol == "acp.v1"

        await bridge.stop()

    @pytest.mark.asyncio
    async def test_connect_with_acp_v2_subprotocol(self):
        """Client connecting with 'acp.v2' subprotocol is accepted."""
        bridge = WebSocketSignalBridge(port=0)
        await bridge.start()

        uri = f"ws://{bridge.host}:{bridge.port}"
        async with websockets.connect(uri, subprotocols=["acp.v2"]) as ws:
            assert ws.subprotocol == "acp.v2"

        await bridge.stop()


class TestWebSocketSignalBridgeBroadcasting:
    """Tests for broadcasting signals via WebSocket."""

    @pytest.mark.asyncio
    async def test_tool_output_broadcast(self):
        """tool_output signal is broadcast to connected WebSocket clients."""
        bridge = WebSocketSignalBridge(port=0)
        await bridge.start()

        received = await connect_and_collect(
            bridge, bridge._broadcast("tool_output", text="hello", coder_uuid="coder-1")
        )

        await bridge.stop()
        assert received is not None
        assert received["event"] == "tool_output"
        assert received["data"]["text"] == "hello"

    @pytest.mark.asyncio
    async def test_stream_chunk_broadcast(self):
        """stream_chunk signal is broadcast to connected clients."""
        bridge = WebSocketSignalBridge(port=0)
        await bridge.start()

        received = await connect_and_collect(
            bridge, bridge._broadcast("stream_chunk", text="chunk", coder_uuid="coder-1")
        )

        await bridge.stop()
        assert received is not None
        assert received["event"] == "stream_chunk"

    @pytest.mark.asyncio
    async def test_spinner_broadcast(self):
        """spinner signal is broadcast."""
        bridge = WebSocketSignalBridge(port=0)
        await bridge.start()

        received = await connect_and_collect(
            bridge,
            bridge._broadcast("spinner", action="start", text="loading", coder_uuid="coder-1"),
        )

        await bridge.stop()
        assert received is not None
        assert received["event"] == "spinner"
        assert received["data"]["action"] == "start"

    @pytest.mark.asyncio
    async def test_start_task_broadcast(self):
        """start_task signal is broadcast."""
        bridge = WebSocketSignalBridge(port=0)
        await bridge.start()

        received = await connect_and_collect(
            bridge,
            bridge._broadcast(
                "start_task", task_id="t1", title="Task", task_type="general", coder_uuid="coder-1"
            ),
        )

        await bridge.stop()
        assert received is not None
        assert received["event"] == "start_task"
        assert received["data"]["task_id"] == "t1"

    @pytest.mark.asyncio
    async def test_multiple_clients_receive_broadcast(self):
        """Multiple connected clients all receive the broadcast."""
        bridge = WebSocketSignalBridge(port=0)
        await bridge.start()

        uri = f"ws://{bridge.host}:{bridge.port}"

        async def connect_and_get():
            # Use an explicit, generous open timeout: slow CI runners can
            # occasionally exceed websockets' 10s default handshake timeout.
            ws = await websockets.connect(uri, open_timeout=15.0)
            return ws

        ws1 = await connect_and_get()
        ws2 = await connect_and_get()
        # Wait until the server has registered both connections so the
        # broadcast below cannot race connection registration.
        await wait_for_registered_clients(bridge, count=2, timeout=5.0)

        await bridge._broadcast("tool_output", text="broadcast", coder_uuid="coder-1")

        # Bound the receives: a missed broadcast should fail fast with a
        # clear TimeoutError instead of hanging the whole CI job.
        msg1 = json.loads(await asyncio.wait_for(ws1.recv(), timeout=5.0))
        msg2 = json.loads(await asyncio.wait_for(ws2.recv(), timeout=5.0))

        await ws1.close()
        await ws2.close()
        await bridge.stop()

        assert msg1["data"]["text"] == "broadcast"
        assert msg2["data"]["text"] == "broadcast"


class TestWebSocketSignalBridgeInboundMessages:
    """Tests for handling inbound messages from WebSocket clients."""

    @pytest.mark.asyncio
    async def test_user_input_with_coder_uuid(self):
        """Inbound user_input with coder_uuid is pushed to the per-coder queue."""
        bridge = WebSocketSignalBridge(port=0)
        await bridge.start()

        # Register a coder queue
        q = queue.Queue()
        queues.register_coder_queue("coder-1", q)

        uri = f"ws://{bridge.host}:{bridge.port}"
        async with websockets.connect(uri) as ws:
            await asyncio.sleep(0.1)
            await ws.send(
                json.dumps(
                    {
                        "type": "user_input",
                        "text": "hello from ws",
                        "coder_uuid": "coder-1",
                    }
                )
            )
            await asyncio.sleep(0.1)

        result = q.get_nowait()
        assert result["text"] == "hello from ws"
        assert result["coder_uuid"] == "coder-1"

        await bridge.stop()

    @pytest.mark.asyncio
    async def test_user_input_without_coder_uuid(self):
        """Inbound user_input without coder_uuid fires the user_input signal."""
        bridge = WebSocketSignalBridge(port=0)
        await bridge.start()

        received = {}

        def handler(sender, **kw):
            received.update(kw)

        signals.user_input.connect(handler)

        uri = f"ws://{bridge.host}:{bridge.port}"
        async with websockets.connect(uri) as ws:
            await asyncio.sleep(0.1)
            await ws.send(
                json.dumps(
                    {
                        "type": "user_input",
                        "text": "hello without uuid",
                    }
                )
            )
            await asyncio.sleep(0.1)

        await ws.close()
        await bridge.stop()

        assert received.get("text") == "hello without uuid"

    @pytest.mark.asyncio
    async def test_confirmation_with_coder_uuid(self):
        """Inbound confirmation with coder_uuid is pushed to the per-coder queue."""
        bridge = WebSocketSignalBridge(port=0)
        await bridge.start()

        q = queue.Queue()
        queues.register_coder_queue("coder-1", q)

        uri = f"ws://{bridge.host}:{bridge.port}"
        async with websockets.connect(uri) as ws:
            await asyncio.sleep(0.1)
            await ws.send(
                json.dumps(
                    {
                        "type": "confirmation",
                        "confirmed": True,
                        "coder_uuid": "coder-1",
                    }
                )
            )
            await asyncio.sleep(0.1)

        result = q.get_nowait()
        assert result["confirmed"] is True

        await ws.close()
        await bridge.stop()

    @pytest.mark.asyncio
    async def test_confirmation_without_coder_uuid(self):
        """Inbound confirmation without coder_uuid fires the confirmation signal."""
        bridge = WebSocketSignalBridge(port=0)
        await bridge.start()

        received = {}

        def handler(sender, **kw):
            received.update(kw)

        signals.confirmation.connect(handler)

        uri = f"ws://{bridge.host}:{bridge.port}"
        async with websockets.connect(uri) as ws:
            await asyncio.sleep(0.1)
            await ws.send(
                json.dumps(
                    {
                        "type": "confirmation",
                        "confirmed": False,
                    }
                )
            )
            await asyncio.sleep(0.1)

        await ws.close()
        await bridge.stop()

        assert received.get("response") is False

    @pytest.mark.asyncio
    async def test_invalid_json(self):
        """Invalid JSON from a client is silently ignored."""
        bridge = WebSocketSignalBridge(port=0)
        await bridge.start()

        uri = f"ws://{bridge.host}:{bridge.port}"
        async with websockets.connect(uri) as ws:
            await asyncio.sleep(0.1)
            await ws.send("not valid json")
            await asyncio.sleep(0.1)
            # No exception means success

        await ws.close()
        await bridge.stop()

    @pytest.mark.asyncio
    async def test_unknown_message_type(self):
        """Unknown message types are silently ignored."""
        bridge = WebSocketSignalBridge(port=0)
        await bridge.start()

        uri = f"ws://{bridge.host}:{bridge.port}"
        async with websockets.connect(uri) as ws:
            await asyncio.sleep(0.1)
            await ws.send(json.dumps({"type": "unknown_type"}))
            await asyncio.sleep(0.1)
            # No exception means success

        await ws.close()
        await bridge.stop()


class TestRunWsServer:
    """Tests for the run_ws_server convenience function."""

    @pytest.mark.asyncio
    async def test_run_ws_server_creates_bridge(self):
        """run_ws_server creates and starts a WebSocketSignalBridge."""
        bridge = await run_ws_server(port=0, host="127.0.0.1")
        assert isinstance(bridge, WebSocketSignalBridge)
        assert bridge.port > 0
        assert bridge._server is not None
        await bridge.stop()


# ── Helpers ──────────────────────────────────────────────────


async def connect_and_collect(bridge, broadcast_coro):
    """Connect to the bridge, trigger a broadcast, and collect the message."""
    uri = f"ws://{bridge.host}:{bridge.port}"
    async with websockets.connect(uri) as ws:
        await asyncio.sleep(0.1)  # Let connection register
        await broadcast_coro
        await asyncio.sleep(0.1)
        msg = await ws.recv()
    return json.loads(msg)


async def wait_for_registered_clients(bridge, count: int, timeout: float) -> None:
    """Wait until the bridge has registered at least ``count`` connected clients."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while len(bridge._connections) < count:
        if loop.time() >= deadline:
            raise TimeoutError(
                f"bridge registered {len(bridge._connections)}/{count} clients within {timeout}s"
            )
        await asyncio.sleep(0.01)
