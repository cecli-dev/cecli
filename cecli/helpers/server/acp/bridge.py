"""Signal → ACP notification adapter.

Maps the existing blinker signals (from ``cecli.helpers.server.signals``) to ACP
``session/update`` notifications. This is the core of the integration — it
subscribes to signals and broadcasts the equivalent ACP JSON-RPC messages
over the WebSocket.
"""

from __future__ import annotations

import logging
from typing import Any

import xxhash

from cecli.helpers.server import signals as server_signals
from cecli.helpers.server.acp import protocol as acp_protocol
from cecli.reasoning_tags import REASONING_END, REASONING_START

logger = logging.getLogger(__name__)

# ── Per-coder-uuid state ───────────────────────────────────────

_reasoning_state: dict[str, bool] = {}
_message_id_counters: dict[str, dict[str, int]] = {}


# ── Message ID Generation ─────────────────────────────────────


def make_message_id(prefix: str, coder_uuid: str, seed: str = "") -> str:
    """Generate a deterministic message ID using xxhash."""
    raw = f"{prefix}:{coder_uuid}:{seed}"
    return xxhash.xxh64(raw.encode()).hexdigest()


def make_tool_call_id(coder_uuid: str, call_text: str) -> str:
    """Generate a deterministic tool call ID using xxhash."""
    raw = f"tool:{coder_uuid}:{call_text}"
    return xxhash.xxh64(raw.encode()).hexdigest()


def _next_counter(coder_uuid: str, key: str) -> int:
    """Get and increment a per-coder counter for message ID generation."""
    if coder_uuid not in _message_id_counters:
        _message_id_counters[coder_uuid] = {}
    counters = _message_id_counters[coder_uuid]
    counters[key] = counters.get(key, 0) + 1
    return counters[key]


# ── Reasoning Tracker ──────────────────────────────────────────


class ReasoningTracker:
    """Per-coder-uuid tracker for reasoning start/end state."""

    @classmethod
    def is_inside_reasoning(cls, coder_uuid: str) -> bool:
        """Check if we are currently inside a reasoning block."""
        return _reasoning_state.get(coder_uuid, False)

    @classmethod
    def set_inside(cls, coder_uuid: str, value: bool) -> None:
        """Set the reasoning state for a coder."""
        _reasoning_state[coder_uuid] = value

    @classmethod
    def classify_stream_chunk(
        cls,
        coder_uuid: str,
        text: str,
    ) -> str:
        """Classify a stream_chunk as "thought", "message", or "mixed".

        Checks for REASONING_START and REASONING_END markers in the chunk
        text and updates the per-coder state accordingly.

        REASONING_START (14 dashes) contains REASONING_END (10 dashes) as a
        substring, so we must mask the START marker before checking for END
        to avoid false detection within the longer dash sequence.
        """
        in_reasoning = cls.is_inside_reasoning(coder_uuid)

        start_marker = REASONING_START.rstrip("\n")
        end_marker = REASONING_END.rstrip("\n")

        has_start = start_marker in text

        # Avoid false END detection within START marker
        # REASONING_START (14 dashes) contains REASONING_END (10 dashes)
        if has_start:
            text_for_end = text.replace(start_marker, " ", 1)
        else:
            text_for_end = text
        has_end = end_marker in text_for_end

        if has_start:
            cls.set_inside(coder_uuid, True)
        if has_end:
            cls.set_inside(coder_uuid, False)

        if has_start and has_end:
            return "mixed"
        if in_reasoning or has_start:
            return "thought"
        if has_end:
            return "mixed"
        return "message"


# ── ACP Signal Bridge ──────────────────────────────────────────


class AcpSignalBridge:
    """Subscribes to blinker signals and broadcasts ACP session/update notifications.

    Mirrors the structure of ``WebSocketSignalBridge`` but produces ACP-formatted
    JSON instead of flat events. Intended for use when ``WebSocketSignalBridge``
    has ``acp_mode=True``.
    """

    def __init__(
        self,
        broadcast_coro: Any = None,
        primary_coder_id: str | None = None,
    ) -> None:
        """Initialize the ACP bridge.

        Args:
            broadcast_coro: An async callable ``(event_type, **data)`` that sends
                            JSON to the connected WebSocket clients.
            primary_coder_id: The primary coder UUID used as sessionId.
        """
        self._broadcast_coro = broadcast_coro
        self._primary_coder_id = primary_coder_id or ""
        self._subscribers: list[Any] = []
        self._loop = None

    @property
    def session_id(self) -> str:
        """Return the session ID (primary coder UUID)."""
        return self._primary_coder_id

    def set_broadcast(self, broadcast_coro: Any) -> None:
        """Set or update the broadcast coroutine."""
        self._broadcast_coro = broadcast_coro

    def subscribe(self, loop: Any = None) -> None:
        """Subscribe to all signals with ACP translators."""
        self._loop = loop
        signals_and_receivers = [
            (server_signals.tool_call, self._on_tool_call),
            (server_signals.tool_result, self._on_tool_result),
            (server_signals.stream_chunk, self._on_stream_chunk),
            (server_signals.start_response, self._on_start_response),
            (server_signals.end_response, self._on_end_response),
            (server_signals.cost_update, self._on_cost_update),
            (server_signals.error, self._on_error),
        ]
        self._subscribers = []
        for sig, receiver in signals_and_receivers:
            sig.connect(receiver)
            self._subscribers.append((sig, receiver))

        logger.info(
            "ACP bridge subscribed to %d signals (sessionId=%s)",
            len(signals_and_receivers),
            self.session_id,
        )

    def unsubscribe(self) -> None:
        """Unsubscribe from all signals."""
        for sig, receiver in self._subscribers:
            sig.disconnect(receiver)
        self._subscribers.clear()

    # ── Outbound helpers ────────────────────────────────────────

    def _send_update(self, update: dict) -> None:
        """Send a session/update notification via the broadcast coroutine."""
        if self._broadcast_coro is None:
            return
        notification = acp_protocol.make_session_update_notification(
            self.session_id,
            update,
        )
        payload = notification  # Already a dict — broadcast will json.dumps it
        if self._loop:
            import asyncio

            asyncio.run_coroutine_threadsafe(
                self._broadcast_coro("acp", payload=payload),
                self._loop,
            )

    # ── Signal handlers (ACP translators) ───────────────────────

    def _on_start_response(self, sender: Any, **kw: Any) -> None:
        """start_response → state_update(state="running")."""
        update = acp_protocol.make_state_update("running")
        self._send_update(update)

    def _on_stream_chunk(self, sender: Any, **kw: Any) -> None:
        """stream_chunk → agent_message_chunk or agent_thought_chunk."""
        text = kw.get("text", "")
        # Use session_id consistently for reasoning tracking across all chunks
        # (stream_chunk may arrive with different coder_uuids from sub-agents)
        sid = self.session_id

        classification = ReasoningTracker.classify_stream_chunk(sid, text)

        if classification == "mixed":
            # Split at REASONING_END boundary
            end_marker = REASONING_END.rstrip("\n")
            parts = text.split(end_marker, 1)
            thought_text = parts[0] + end_marker if len(parts) > 1 else parts[0]
            message_text = parts[1] if len(parts) > 1 else ""

            # Emit thought chunk for reasoning portion
            if thought_text.strip():
                thought_id = make_message_id(
                    "thought",
                    sid,
                    str(_next_counter(sid, "thought")),
                )
                update = acp_protocol.make_agent_thought_chunk(thought_id, thought_text)
                self._send_update(update)

            # Emit message chunk for post-reasoning portion
            if message_text.strip():
                msg_id = make_message_id(
                    "msg",
                    sid,
                    str(_next_counter(sid, "msg")),
                )
                update = acp_protocol.make_agent_message_chunk(msg_id, message_text)
                self._send_update(update)

        elif classification == "thought":
            thought_id = make_message_id(
                "thought",
                sid,
                str(_next_counter(sid, "thought")),
            )
            update = acp_protocol.make_agent_thought_chunk(thought_id, text)
            self._send_update(update)

        else:
            # Normal message chunk
            msg_id = make_message_id(
                "msg",
                sid,
                str(_next_counter(sid, "msg")),
            )
            update = acp_protocol.make_agent_message_chunk(msg_id, text)
            self._send_update(update)

    def _on_tool_call(self, sender: Any, **kw: Any) -> None:
        """tool_call → tool_call_update(status="in_progress")."""
        lines = kw.get("lines", [])
        coder_uuid = kw.get("coder_uuid", self.session_id) or self.session_id

        # Generate tool call ID from first line text
        call_text = lines[0] if lines else ""
        tool_call_id = make_tool_call_id(coder_uuid, call_text)

        # Extract title from first line (strip Rich markup)
        title = call_text
        if title:
            # Basic cleanup of Rich markup
            import re

            title = re.sub(r"\[.*?\]", "", title).strip()

        # Infer kind from tool name
        kind = _infer_tool_kind(call_text)

        update = acp_protocol.make_tool_call_update(
            tool_call_id,
            status="in_progress",
            title=title,
            kind=kind,
        )
        self._send_update(update)

    def _on_tool_result(self, sender: Any, **kw: Any) -> None:
        """tool_result → tool_call_content_chunk + tool_call_update completed."""
        text = kw.get("text", "")
        coder_uuid = kw.get("coder_uuid", self.session_id) or self.session_id

        # We need to know which tool call this result belongs to.
        # In practice, the last tool_call_id is used.
        # Generate a consistent ID from the result text
        tool_call_id = make_tool_call_id(coder_uuid, text[:100])

        # 1. Send content chunk
        content_update = acp_protocol.make_tool_call_content_chunk(tool_call_id, text)
        self._send_update(content_update)

        # 2. Send completed status — commented out to avoid premature completion
        # between multiple tool result chunks
        # completed_update = acp_protocol.make_tool_call_update(
        #     tool_call_id, status="completed",
        # )
        # self._send_update(completed_update)

    def _on_end_response(self, sender: Any, **kw: Any) -> None:
        """end_response — commented out (premature during tool calls)."""
        pass

    def _on_cost_update(self, sender: Any, **kw: Any) -> None:
        """cost_update → usage_update."""
        cost = kw.get("cost", 0.0)
        # Estimate token counts from cost (rough heuristic)
        used = int(cost * 100000) if cost > 0 else 0
        update = acp_protocol.make_usage_update(
            used=used,
            size=0,
            cost={"amount": cost, "currency": "USD"},
        )
        self._send_update(update)

    def _on_error(self, sender: Any, **kw: Any) -> None:
        """error → state_update(state="idle", stopReason="refusal")."""
        update = acp_protocol.make_state_update(
            "idle",
            stop_reason="refusal",
        )
        self._send_update(update)


# ── Helpers ────────────────────────────────────────────────────


def _infer_tool_kind(call_text: str) -> str:
    """Infer the tool kind from the first line of a tool call."""
    call_lower = call_text.lower()
    if any(word in call_lower for word in ("read", "view", "list", "grep", "search")):
        return "read"
    elif any(word in call_lower for word in ("write", "edit", "create", "replace", "delete")):
        return "write"
    elif any(word in call_lower for word in ("bash", "run", "execute", "command")):
        return "command"
    return "other"
