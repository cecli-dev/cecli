"""WebSocket server with ACP v2 JSON-RPC framing.

Subscribes to blinker signals defined in ``signals.py`` and broadcasts
ACP v2 ``session/update`` notifications to all connected WebSocket clients.
Also receives ACP JSON-RPC messages from WebSocket clients (falling back
to legacy ``{"type": "user_input"}`` format for backward compatibility)
and routes them to the appropriate per-coder input queue.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import websockets
from websockets.asyncio.server import ServerConnection, serve

from cecli.helpers import queues
from cecli.helpers.server import signals as server_signals

logger = logging.getLogger(__name__)


class WebSocketSignalBridge:
    """Bridge between blinker signals and WebSocket clients via ACP v2.

    Subscribes to all relevant signals and broadcasts ACP v2 JSON-RPC
    ``session/update`` notifications to every connected WebSocket peer.
    Inbound ACP JSON-RPC messages (``initialize``, ``session/new``,
    ``session/prompt``, etc.) are dispatched through the ACP protocol handler.
    Legacy ``{"type": "user_input"}`` messages also work for backward compatibility.
    """

    def __init__(self, port: int = 0, host: str = "127.0.0.1") -> None:
        self.port = port
        self.host = host
        self._connections: set[ServerConnection] = set()
        self._server: Any = None
        self._subscribers: list[Any] = []
        self._loop = None
        self._acp_bridge: Any = None

    # ── Lifecycle ──────────────────────────────────────────────

    async def start(self) -> None:
        """Start the WebSocket server and subscribe to signals."""
        self._server = await serve(
            self._handle_connection,
            self.host,
            self.port,
            subprotocols=["acp.v1", "acp.v2"],
            # Don't reject clients that don't specify a subprotocol
            select_subprotocol=lambda _protocol, offered: offered[0] if offered else None,
        )
        # Re-read the actual port if 0 was passed (OS-assigned)
        self.port = self._server.sockets[0].getsockname()[1] if self._server.sockets else self.port
        logger.info("WebSocket server listening on ws://%s:%d", self.host, self.port)
        self._loop = asyncio.get_running_loop()

        from cecli.helpers.server.acp.bridge import AcpSignalBridge

        self._acp_bridge = AcpSignalBridge(
            broadcast_coro=self._broadcast_acp,
            primary_coder_id=queues.get_primary_coder_id(),
        )
        self._acp_bridge.subscribe(loop=self._loop)
        logger.info("ACP bridge initialized (sessionId=%s)", self._acp_bridge.session_id)

        self._subscribe_signals()

    async def stop(self) -> None:
        """Stop the WebSocket server and unsubscribe from signals."""
        self._unsubscribe_signals()

        if self._acp_bridge is not None:
            self._acp_bridge.unsubscribe()
            self._acp_bridge = None

        # Close all connections
        for ws in set(self._connections):
            await ws.close(1012, "Server shutting down")
        self._connections.clear()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    # ── Connection handling ────────────────────────────────────

    async def _handle_connection(self, ws: ServerConnection) -> None:
        """Handle a new WebSocket connection."""
        self._connections.add(ws)
        logger.info("WebSocket client connected (%d total)", len(self._connections))
        try:
            async for message in ws:
                await self._handle_message(ws, message)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._connections.discard(ws)
            logger.info("WebSocket client disconnected (%d remaining)", len(self._connections))

    async def _broadcast(self, event_type: str, **data: Any) -> None:
        """Broadcast a JSON event to all connected clients."""
        payload = json.dumps({"event": event_type, "data": data})
        dead: list[ServerConnection] = []
        for ws in self._connections:
            try:
                await ws.send(payload)
            except websockets.exceptions.ConnectionClosed:
                dead.append(ws)
        for ws in dead:
            self._connections.discard(ws)

    async def _broadcast_acp(self, event_type: str, **data: Any) -> None:
        """Broadcast an ACP JSON-RPC payload to all connected clients.

        Unlike ``_broadcast`` which wraps data in an event envelope,
        this sends the raw ACP JSON-RPC dict (already structured as a
        ``session/update`` notification).
        """
        payload = data.get("payload")
        if payload is None:
            return
        raw = json.dumps(payload)
        dead: list[ServerConnection] = []
        for ws in self._connections:
            try:
                await ws.send(raw)
            except websockets.exceptions.ConnectionClosed:
                dead.append(ws)
        for ws in dead:
            self._connections.discard(ws)

    # ── Signal subscriptions ───────────────────────────────────

    def _subscribe_signals(self) -> None:
        """Subscribe to signals not already handled by the ACP bridge.

        The ``AcpSignalBridge`` handles: tool_call, tool_result, stream_chunk,
        start_response, end_response, cost_update, error.
        These legacy handlers cover the remaining signals.
        """
        signals_and_receivers = [
            (server_signals.tool_output, self._on_tool_output),
            (server_signals.spinner, self._on_spinner),
            (server_signals.start_task, self._on_start_task),
            (server_signals.ready_for_input, self._on_ready_for_input),
            (server_signals.confirmation, self._on_confirmation),
        ]
        self._subscribers = []
        for sig, receiver in signals_and_receivers:
            sig.connect(receiver)
            self._subscribers.append((sig, receiver))

    def _unsubscribe_signals(self) -> None:
        """Unsubscribe from all blinker signals."""
        for sig, receiver in self._subscribers:
            sig.disconnect(receiver)
        self._subscribers.clear()

    # ── Signal handlers ────────────────────────────────────────

    def _on_tool_output(self, sender, **kw):
        asyncio.run_coroutine_threadsafe(
            self._broadcast("tool_output", text=kw.get("text"), coder_uuid=kw.get("coder_uuid")),
            self._loop,
        )

    def _on_tool_call(self, sender, **kw):
        asyncio.run_coroutine_threadsafe(
            self._broadcast("tool_call", lines=kw.get("lines"), coder_uuid=kw.get("coder_uuid")),
            self._loop,
        )

    def _on_tool_result(self, sender, **kw):
        asyncio.run_coroutine_threadsafe(
            self._broadcast("tool_result", text=kw.get("text"), coder_uuid=kw.get("coder_uuid")),
            self._loop,
        )

    def _on_stream_chunk(self, sender, **kw):
        asyncio.run_coroutine_threadsafe(
            self._broadcast("stream_chunk", text=kw.get("text"), coder_uuid=kw.get("coder_uuid")),
            self._loop,
        )

    def _on_start_response(self, sender, **kw):
        asyncio.run_coroutine_threadsafe(
            self._broadcast("start_response", coder_uuid=kw.get("coder_uuid")), self._loop
        )

    def _on_end_response(self, sender, **kw):
        asyncio.run_coroutine_threadsafe(
            self._broadcast("end_response", coder_uuid=kw.get("coder_uuid")), self._loop
        )

    def _on_spinner(self, sender, **kw):
        # asyncio.run_coroutine_threadsafe(
        #     self._broadcast(
        #     "spinner",
        #     action=kw.get("action"),
        #     text=kw.get("text"),
        #     coder_uuid=kw.get("coder_uuid"),
        # ),
        #     self._loop
        # )
        return

    def _on_start_task(self, sender, **kw):
        asyncio.run_coroutine_threadsafe(
            self._broadcast(
                "start_task",
                task_id=kw.get("task_id"),
                title=kw.get("title"),
                task_type=kw.get("task_type"),
                coder_uuid=kw.get("coder_uuid"),
            ),
            self._loop,
        )

    def _on_cost_update(self, sender, **kw):
        asyncio.run_coroutine_threadsafe(
            self._broadcast("cost_update", cost=kw.get("cost"), coder_uuid=kw.get("coder_uuid")),
            self._loop,
        )

    def _on_error(self, sender, **kw):
        asyncio.run_coroutine_threadsafe(
            self._broadcast("error", message=kw.get("message"), coder_uuid=kw.get("coder_uuid")),
            self._loop,
        )

    def _on_ready_for_input(self, sender, **kw):
        asyncio.run_coroutine_threadsafe(
            self._broadcast(
                "ready_for_input",
                files=kw.get("files"),
                commands=kw.get("commands"),
                chat_files=kw.get("chat_files"),
                coder_uuid=kw.get("coder_uuid"),
            ),
            self._loop,
        )

    def _on_confirmation(self, sender, **kw):
        asyncio.run_coroutine_threadsafe(
            self._broadcast(
                "confirmation",
                question=kw.get("question"),
                subject=kw.get("subject"),
                options=kw.get("options"),
                coder_uuid=kw.get("coder_uuid"),
            ),
            self._loop,
        )

    # ── Inbound message handling ───────────────────────────────

    async def _handle_message(self, ws: ServerConnection, raw: str) -> None:
        """Handle an incoming message from a WebSocket client.

        Detects JSON-RPC 2.0 messages (has ``"jsonrpc"`` key) and routes them
        through the ACP dispatcher. Falls back to legacy flat-format messages
        (``{"type": "user_input"}``, ``{"type": "confirmation"}``) for
        backward compatibility.
        """
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Invalid JSON from WebSocket client: %s", raw[:100])
            return

        # Detect ACP JSON-RPC messages (have "jsonrpc" key)
        if "jsonrpc" in msg and isinstance(msg.get("jsonrpc"), str):
            await self._handle_acp_message(ws, raw)
            return

        msg_type = msg.get("type")
        coder_uuid = msg.get("coder_uuid")

        if msg_type == "user_input":
            text = msg.get("text", "")
            target_uuid = coder_uuid or queues.get_primary_coder_id()
            if target_uuid:
                queues.push_coder_input(target_uuid, {"text": text, "coder_uuid": target_uuid})
            else:
                # No coder_uuid and no primary — broadcast via signal
                server_signals.send_user_input(self, text=text, coder_uuid=None)

        elif msg_type == "confirmation":
            confirmed = msg.get("confirmed")
            target_uuid = coder_uuid or queues.get_primary_coder_id()
            if target_uuid:
                queues.push_coder_input(
                    target_uuid,
                    {"confirmed": confirmed, "coder_uuid": target_uuid},
                )
            else:
                server_signals.send_confirmation(
                    self, question="", response=confirmed, coder_uuid=None
                )

        else:
            logger.warning("Unknown message type from WebSocket: %s", msg_type)

    async def _handle_acp_message(self, ws: ServerConnection, raw: str) -> None:
        """Route an ACP JSON-RPC message through the ACP dispatcher.

        Parses the message, dispatches to the appropriate handler, and
        sends responses back to the WebSocket client.
        """
        from cecli.helpers.server.acp.protocol import dispatch_inbound

        session_id = self._acp_bridge.session_id if self._acp_bridge else ""
        primary_id = queues.get_primary_coder_id() or ""

        responses = await dispatch_inbound(
            raw,
            session_id=session_id,
            primary_coder_id=primary_id,
        )

        for resp in responses:
            try:
                await ws.send(json.dumps(resp))
            except websockets.exceptions.ConnectionClosed:
                logger.warning("Connection closed while sending ACP response")
                break


# ── Convenience runner ─────────────────────────────────────────


async def run_ws_server(port: int, host: str = "127.0.0.1") -> WebSocketSignalBridge:
    """Create and start a WebSocketSignalBridge on the given port.

    This is called from ``main_async`` when ``--ws-port`` is set > 0.
    The caller should ``await bridge.stop()`` during shutdown.
    """
    bridge = WebSocketSignalBridge(port=port, host=host)
    await bridge.start()
    return bridge
