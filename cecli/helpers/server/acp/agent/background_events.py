"""Ordered, coalesced background event emitter for the ACP bridge."""

from __future__ import annotations

import base64
import threading
import time
from collections import deque
from typing import Any, Callable

BG_OUTPUT_COALESCE_SECONDS = 0.05
BG_OUTPUT_COALESCE_BYTES = 16 * 1024
BG_EVENT_QUEUE_MAX = 4096


class BackgroundEventEmitter:
    """Enqueue background events and send them from one ordered thread.

    ``publish``/``publish_output`` never block and never touch the transport,
    so they are safe to call while the background manager holds its state
    locks. Output is coalesced per key to at most one frame per 50 ms or
    16 KiB, and events never overtake earlier output for the same key.
    """

    def __init__(self, send: Callable[[dict], None], max_queue: int = BG_EVENT_QUEUE_MAX):
        self._send = send
        self._max_queue = max_queue
        self._cv = threading.Condition()
        self._pending: dict[str, bytearray] = {}
        self._pending_seq: dict[str, int] = {}
        self._pending_since: dict[str, float] = {}
        self._order: deque[tuple[str, str]] = deque()
        self._queued_keys: set[str] = set()
        self._events: dict[int, dict] = {}
        self._next_event_id = 0
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="background-events", daemon=True)
        self._thread.start()

    def publish(self, params: dict) -> None:
        """Enqueue a non-output event; never blocks."""
        with self._cv:
            if self._closed:
                return
            self._append_event_locked(params)
            self._cv.notify()

    def publish_output(self, key: str, seq: int, data: bytes) -> None:
        """Enqueue raw output bytes for ``key``; never blocks."""
        if not key or not data:
            return

        with self._cv:
            if self._closed:
                return

            buffer = self._pending.get(key)
            if buffer is None:
                buffer = bytearray()
                self._pending[key] = buffer
                self._pending_since[key] = time.monotonic()

            buffer.extend(data)
            self._pending_seq[key] = int(seq)

            if key not in self._queued_keys:
                self._order.append(("out", key))
                self._queued_keys.add(key)

            self._cv.notify()

    def close(self, timeout: float = 2.0) -> None:
        """Flush pending output and stop the emitter thread."""
        with self._cv:
            self._closed = True
            self._cv.notify_all()

        self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while True:
            with self._cv:
                if self._closed and not self._order:
                    return

                batch = self._collect_locked()
                if not batch:
                    self._cv.wait(timeout=BG_OUTPUT_COALESCE_SECONDS / 2)

            for params in batch:
                try:
                    self._send(background_notification(params))
                except Exception:
                    pass

    def _append_event_locked(self, params: dict) -> None:
        if len(self._order) >= self._max_queue:
            kind, value = self._order.popleft()
            if kind == "out":
                self._pending.pop(value, None)
                self._pending_seq.pop(value, None)
                self._pending_since.pop(value, None)
                self._queued_keys.discard(value)
            else:
                self._events.pop(int(value), None)

        event_id = self._next_event_id
        self._next_event_id += 1
        self._events[event_id] = params
        self._order.append(("event", str(event_id)))

    def _collect_locked(self) -> list[dict]:
        now = time.monotonic()
        sends: list[dict] = []
        order: deque[tuple[str, str]] = deque()
        blocked = False

        for kind, value in self._order:
            if blocked:
                order.append((kind, value))
                continue

            if kind == "out":
                data = self._pending.get(value)
                if not data:
                    self._pending_seq.pop(value, None)
                    self._pending_since.pop(value, None)
                    self._queued_keys.discard(value)
                    continue

                age = now - self._pending_since.get(value, now)
                if (
                    not self._closed
                    and len(data) < BG_OUTPUT_COALESCE_BYTES
                    and age < BG_OUTPUT_COALESCE_SECONDS
                ):
                    blocked = True
                    order.append((kind, value))
                    continue

                sends.append(
                    {
                        "schemaVersion": 1,
                        "event": "output",
                        "key": value,
                        "seq": self._pending_seq.get(value, 0),
                        "data": base64.b64encode(bytes(data)).decode("ascii"),
                    }
                )
                self._pending.pop(value, None)
                self._pending_seq.pop(value, None)
                self._pending_since.pop(value, None)
                self._queued_keys.discard(value)
                continue

            params = self._events.pop(int(value), None)
            if params is not None:
                sends.append(params)

        self._order = order
        return sends


def background_notification(params: dict) -> dict[str, Any]:
    """Wrap background event params in a JSON-RPC notification."""
    return {"jsonrpc": "2.0", "method": "cecli/background/event", "params": params}
