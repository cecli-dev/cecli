"""How AcpAgent exchanges JSON-RPC messages with the client.

The agent only needs the small ``Transport`` interface below. ``StdioTransport``
implements it for clients that launch cecli as a subprocess (``cecli --acp``);
another transport, such as a WebSocket connection, can drive the same agent.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from typing import Any, Protocol

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# Returned by ``Transport.receive`` once the client has gone away
EOF = object()


def log(message: str) -> None:
    """Diagnostics go to stderr; stdout belongs to the protocol."""
    print(f"[cecli acp] {message}", file=sys.stderr, flush=True)


def result_message(request_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_message(request_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


class Transport(Protocol):
    """A connection to one ACP client, carrying JSON-RPC messages as dicts."""

    def open(self) -> None:
        """Start receiving messages from the client."""

    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        """Deliver incoming messages to ``loop`` (called from that loop)."""

    def detach(self) -> None:
        """Stop delivering to the current loop, keeping unread messages for the next."""

    async def receive(self) -> Any:
        """The next message from the client, or ``EOF`` once it has gone away."""

    def send(self, msg: dict) -> None:
        """Send a message to the client (safe to call from any thread)."""


class StdioTransport:
    """Newline-delimited JSON-RPC on the process's original stdin/stdout.

    ``open()`` moves the protocol onto private duplicates of fds 0 and 1,
    then points fd 0 at /dev/null and fd 1 at stderr, so stray prints, Rich
    consoles and child processes can neither corrupt nor consume the stream.

    A reader thread hands messages to whichever event loop is attached;
    messages that arrive while no loop is attached wait in a backlog.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._out = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._inbox: asyncio.Queue | None = None
        self._backlog: list[Any] = []

    def open(self) -> None:
        sys.stdout.flush()
        in_fd = os.dup(0)
        out_fd = os.dup(1)
        devnull = os.open(os.devnull, os.O_RDONLY)
        os.dup2(devnull, 0)
        os.close(devnull)
        os.dup2(2, 1)
        self.start(os.fdopen(in_fd, "rb"), os.fdopen(out_fd, "wb"))

    def start(self, reader, writer) -> None:
        self._out = writer
        thread = threading.Thread(
            target=self._read_loop, args=(reader,), name="cecli-acp-stdin", daemon=True
        )
        thread.start()

    def _read_loop(self, reader) -> None:
        for raw in reader:
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError as err:
                self.send(error_message(None, PARSE_ERROR, f"Parse error: {err}"))
                continue
            if not isinstance(msg, dict):
                self.send(error_message(None, INVALID_REQUEST, "Invalid Request"))
                continue
            self._deliver(msg)
        self._deliver(EOF)

    def _deliver(self, msg: Any) -> None:
        with self._lock:
            loop = self._loop
            if loop is not None:
                try:
                    loop.call_soon_threadsafe(self._enqueue, msg)
                    return
                except RuntimeError:  # loop closed under us
                    self._loop = None
                    self._inbox = None
            self._backlog.append(msg)

    def _enqueue(self, msg: Any) -> None:
        with self._lock:
            if self._inbox is not None:
                self._inbox.put_nowait(msg)
            else:
                self._backlog.append(msg)

    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            self._loop = loop
            self._inbox = asyncio.Queue()
            for msg in self._backlog:
                self._inbox.put_nowait(msg)
            self._backlog.clear()

    def detach(self) -> None:
        with self._lock:
            if self._inbox is not None:
                while not self._inbox.empty():
                    self._backlog.append(self._inbox.get_nowait())
            self._loop = None
            self._inbox = None

    async def receive(self) -> Any:
        return await self._inbox.get()

    def send(self, msg: dict) -> None:
        data = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        with self._write_lock:
            if self._out is None:
                return
            try:
                self._out.write(data + b"\n")
                self._out.flush()
            except (OSError, ValueError) as err:
                log(f"failed to write to client: {err}")
