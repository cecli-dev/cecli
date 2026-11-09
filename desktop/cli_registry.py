"""Background mirror and CLI registry for the desktop bridge.

The ACP child owns background commands and emits ``cecli/background/event``
notifications. This module keeps a synchronous, cache-only mirror of those
events plus the raw output ring used by the SSE replay contract, and exposes a
small registry that the HTTP layer can query without awaiting ACP requests.
"""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Any

MIRROR_RING_BYTES = 1024 * 1024
MIRROR_QUEUE_SIZE = 512


class BackgroundMirror:
    """Cache one bridge's background command state and raw output rings."""

    def __init__(self, bridge_id: str) -> None:
        self.bridge_id = bridge_id
        self.entries: dict[str, dict[str, Any]] = {}
        self._rings: dict[str, dict[str, Any]] = {}
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def seed(self, commands: list[dict[str, Any]]) -> None:
        """Replace cached entries from an ACP ``list`` result."""
        entries = {}
        for entry in commands:
            if not isinstance(entry, dict):
                continue
            key = entry.get("key")
            if isinstance(key, str) and key:
                entries[key] = dict(entry)
        self.entries = entries

    def apply_event(self, params: dict[str, Any]) -> None:
        """Fold one notification into the cache; never awaits or does I/O."""
        event = params.get("event")
        key = params.get("key")
        if not isinstance(key, str) or not key:
            return

        if event == "output":
            data = params.get("data")
            if isinstance(data, str):
                try:
                    raw = base64.b64decode(data, validate=True)
                except Exception:
                    return
                self._append_output(key, int(params.get("seq") or 0), raw)
            self._fanout(params)
            return

        if event == "closed":
            self.entries.pop(key, None)
            self._rings.pop(key, None)
            self._fanout(params)
            return

        entry = params.get("command")
        if isinstance(entry, dict):
            merged = dict(self.entries.get(key) or {})
            merged.update(entry)
            merged.setdefault("key", key)
            self.entries[key] = merged

        if event == "exited":
            merged = self.entries.setdefault(key, {"key": key})
            merged["state"] = params.get("state") or "exited"
            merged["running"] = False
            merged["exitCode"] = params.get("code")
            merged["endedAt"] = params.get("endedAt")
        elif event == "needs_input":
            merged = self.entries.setdefault(key, {"key": key})
            merged["needsInput"] = True
            merged["lastPrompt"] = params.get("prompt")
        elif event in ("started", "state"):
            merged = self.entries.setdefault(key, {"key": key})
            merged.setdefault("state", "running")

        self._fanout(params)

    def snapshot(self, key: str, since: int | None = None) -> dict[str, Any]:
        """Return replay bytes using FIX A offsets (seq is the END offset)."""
        ring = self._rings.get(key)
        entry = self.entries.get(key) or {}
        if ring is None:
            return {
                "seq": 0,
                "startSeq": 0,
                "data": b"",
                "reset": since is not None and since > 0,
                "state": entry.get("state", "exited"),
            }

        end = ring["seq"]
        start = ring.get("start", end - len(ring["data"]))
        if since is None or since < start or since > end:
            data = bytes(ring["data"])
            reset = since is not None and (since < start or since > end)
        else:
            offset = max(0, int(since) - start)
            data = bytes(ring["data"][offset:])
            reset = False

        return {
            "seq": end,
            "startSeq": start,
            "data": data,
            "reset": reset,
            "state": entry.get("state", "running"),
        }

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=MIRROR_QUEUE_SIZE)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def discard(self, key: str) -> None:
        """Drop one command's cached entry and ring (idempotent close)."""
        self.entries.pop(key, None)
        self._rings.pop(key, None)

    def _append_output(self, key: str, seq: int, data: bytes) -> None:
        ring = self._rings.get(key)
        if ring is None:
            ring = {"data": bytearray(), "seq": 0, "start": 0}
            self._rings[key] = ring

        if seq <= ring["seq"]:
            return

        if ring["seq"] and seq != ring["seq"] + len(data):
            self._signal_lag()

        ring["data"].extend(data)
        ring["seq"] = seq
        excess = len(ring["data"]) - MIRROR_RING_BYTES
        if excess > 0:
            del ring["data"][:excess]
        ring["start"] = ring["seq"] - len(ring["data"])

    def _fanout(self, params: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait({"type": "event", "params": params})
            except asyncio.QueueFull:
                self._lag_reset(queue)

    def _signal_lag(self) -> None:
        for queue in list(self._subscribers):
            self._lag_reset(queue)

    def _lag_reset(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        try:
            queue.put_nowait({"type": "reset", "reason": "lag"})
        except asyncio.QueueFull:
            pass


class CliRegistry:
    """Bridge-scoped mirrors plus semantic error mapping for ``/api/cli/*``."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._mirrors: dict[str, BackgroundMirror] = {}

    def mirror(self, bridge_id: str) -> BackgroundMirror:
        mirror = self._mirrors.get(bridge_id)
        if mirror is None:
            mirror = BackgroundMirror(bridge_id)
            self._mirrors[bridge_id] = mirror
        return mirror

    def apply_event(self, bridge_id: str, params: dict[str, Any]) -> None:
        self.mirror(bridge_id).apply_event(params)

    def subscribe(self, bridge_id: str) -> asyncio.Queue[dict[str, Any]]:
        return self.mirror(bridge_id).subscribe()

    def unsubscribe(self, bridge_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.mirror(bridge_id).unsubscribe(queue)

    def state_payload(self, bridge_id: str) -> dict[str, Any]:
        mirror = self.mirror(bridge_id)
        owner = None
        for entry in mirror.entries.values():
            if entry.get("inputOwner"):
                owner = entry["inputOwner"]
                break
        return {
            "enabled": bool(self.enabled),
            "background": bool(self.enabled),
            "rawBackground": True,
            "inputLease": True,
            "inputOwner": owner,
        }

    async def ensure_state(self, bridge) -> None:
        """Seed the mirror from ACP when it is cold; bounded and best-effort."""
        mirror = self.mirror(bridge.bridge_id)
        if mirror.entries:
            return
        try:
            result = await asyncio.wait_for(
                bridge.call_extension("cecli/background", {"action": "list"}), timeout=1.0
            )
        except Exception:
            return
        commands = result.get("commands") if isinstance(result, dict) else None
        if isinstance(commands, list):
            mirror.seed(commands)

    async def call(self, bridge, action: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = {"action": action, **params}
        result = await bridge.call_extension("cecli/background", payload)
        mirror = self.mirror(bridge.bridge_id)
        if action == "list" and isinstance(result.get("commands"), list):
            mirror.seed(result["commands"])
        elif action == "close" and isinstance(params.get("key"), str):
            if result.get("ok") is not False or str(result.get("error")) == "not_found":
                mirror.discard(params["key"])
        elif action == "state" and isinstance(result.get("command"), dict):
            entry = dict(result["command"])
            key = entry.get("key")
            if isinstance(key, str) and key:
                mirror.entries[key] = entry
        return result


def map_semantic_error(error: Any) -> int:
    """Map a ``{ok:false,error}`` result to the HTTP status the UI expects."""
    return {
        "not_found": 404,
        "not_running": 409,
        "input_locked": 423,
        "queue_full": 429,
        "too_large": 413,
    }.get(str(error), 400)


def error_code(result: dict[str, Any]) -> int | None:
    """Extract and map a semantic error from an ACP action result."""
    if not isinstance(result, dict) or result.get("ok") is not False:
        return None
    return map_semantic_error(result.get("error"))


def entry_state(entry: dict[str, Any]) -> str:
    """Best-effort running state for the CLI pane."""
    if entry.get("state"):
        return str(entry["state"])
    return "running" if entry.get("running") else "exited"


def now() -> float:
    return time.time()
