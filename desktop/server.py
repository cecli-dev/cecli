"""Localhost HTTP/SSE bridge between the desktop UI and ``cecli --acp``.

Only the Python standard library is used. The module serves the static UI,
exposes a small JSON API, and supervises one ACP child process over
newline-delimited JSON-RPC on its stdin/stdout. Child stderr is republished to
the browser as log events and echoed to the server's stderr.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import shutil
import signal
import socket
import sys
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any, AsyncIterator

MAX_BODY = 1024 * 1024
SSE_QUEUE_SIZE = 512
MAX_LINE_BYTES = 32 * 1024 * 1024
STREAM_LIMIT = 10 * 1024 * 1024
HEARTBEAT_SECONDS = 15.0
INITIALIZE_TIMEOUT = 20.0
SESSION_TIMEOUT = 300.0
SHUTDOWN_TIMEOUT = 5.0

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
}


class BridgeError(Exception):
    """An API-level failure carrying the HTTP status it should become."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class AcpError(RuntimeError):
    """A JSON-RPC or child-process failure."""


class SseClient:
    """One connected event-stream client and its outbound queue."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=SSE_QUEUE_SIZE)

    def enqueue(self, event: dict[str, Any]) -> None:
        payload = json.dumps(event, separators=(",", ":"), ensure_ascii=False)
        while True:
            try:
                self.queue.put_nowait(payload)
                return
            except asyncio.QueueFull:
                # Drop the oldest update for a slow client instead of buffering forever
                try:
                    self.queue.get_nowait()
                except asyncio.QueueEmpty:
                    return


class AcpBridge:
    """Supervise one ACP child and translate between it, HTTP callers and SSE."""

    def __init__(self, cecli: str, extra_args: list[str], workspace: str) -> None:
        self.cecli = cecli
        self.extra_args = extra_args
        self.workspace = workspace
        self.process: asyncio.subprocess.Process | None = None
        self.status = "starting"
        self.status_detail: str | None = None
        self.busy = False
        self.session_id: str | None = None
        self.config_options: list[dict[str, Any]] = []
        self.modes: dict[str, Any] = {}
        self.agent: dict[str, Any] = {}
        self.clients: set[SseClient] = set()
        self._pending: dict[Any, asyncio.Future[Any]] = {}
        self._pending_permissions: dict[Any, dict[str, Any]] = {}
        self._next_id = 1
        self._write_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._generation = 0
        self._exit_reported_for = -1
        self._reader_tasks: list[asyncio.Task[Any]] = []
        self._lifecycle_task: asyncio.Task[Any] | None = None
        self._prompt_task: asyncio.Task[Any] | None = None
        self._config_tasks: set[asyncio.Task[Any]] = set()
        self._session_pending = False
        self._stopping = False

    async def start(self) -> None:
        """Launch the child and perform the ACP handshake in the background."""
        self._lifecycle_task = asyncio.create_task(self._boot())

    async def shutdown(self) -> None:
        """Terminate the child and wake anything waiting on it."""
        self._stopping = True
        self._cancel_task(self._lifecycle_task)
        self._cancel_task(self._prompt_task)
        for task in list(self._config_tasks):
            self._cancel_task(task)
        await self._stop_child()

    def snapshot(self) -> dict[str, Any]:
        """The state object returned by ``GET /api/state``."""
        return {
            "status": self.status,
            "busy": self.busy,
            "workspace": self.workspace,
            "sessionId": self.session_id,
            "configOptions": self.config_options,
            "modes": self.modes,
            "agent": self.agent,
            "permissions": [
                {"requestId": request_id, **permission}
                for request_id, permission in self._pending_permissions.items()
            ],
            "clients": len(self.clients),
        }

    async def prompt(self, text: str) -> None:
        """Start a turn, or raise ``BridgeError`` when the bridge is unavailable."""
        if self.status != "ready" or self.session_id is None:
            raise BridgeError(409, "The agent is not ready")
        if self.busy or self._session_pending:
            raise BridgeError(409, "The agent is busy")
        self.busy = True
        self._prompt_task = asyncio.create_task(self._run_prompt(text))

    async def cancel(self) -> None:
        """Send the cancellation notification for the current turn."""
        if self.process is None or not self.process.stdin or self.session_id is None:
            return
        try:
            await self._notify("session/cancel", {"sessionId": self.session_id})
        except (AcpError, ConnectionError, BrokenPipeError):
            pass

    async def new_session(self, cwd: str) -> None:
        """Request a fresh ACP session in the background."""
        if self.status != "ready" or self._session_pending:
            raise BridgeError(409, "The agent is not ready")
        if self.busy:
            raise BridgeError(409, "The agent is busy")
        self._session_pending = True
        self.session_id = None
        self.config_options = []
        self.modes = {}
        self.status = "starting"
        self.status_detail = None
        await self._broadcast(self._status_event())
        asyncio.create_task(self._new_session_worker(cwd))

    async def set_config(self, config_id: str, value: str) -> None:
        """Change a session config option in the background."""
        if self.status != "ready" or self.session_id is None:
            raise BridgeError(409, "The agent is not ready")
        task = asyncio.create_task(self._set_config_worker(config_id, value))
        self._config_tasks.add(task)
        task.add_done_callback(self._config_tasks.discard)

    async def resolve_permission(self, request_id: Any, option_id: str | None) -> None:
        """Answer a pending permission request; raise ``KeyError`` if unknown."""
        key = self._permission_key(request_id)
        self._pending_permissions.pop(key)
        if option_id is None:
            outcome: dict[str, Any] = {"outcome": {"outcome": "cancelled"}}
        else:
            outcome = {"outcome": {"outcome": "selected", "optionId": option_id}}
        await self._send_response(key, outcome)
        await self._broadcast(
            {"type": "permission_resolved", "requestId": key, "optionId": option_id}
        )

    async def restart(self) -> None:
        """Kill and respawn the child without waiting for the handshake."""
        self._lifecycle_task = asyncio.create_task(self._restart_worker())

    async def _boot(self) -> None:
        async with self._lifecycle_lock:
            await self._spawn_child()

    async def _restart_worker(self) -> None:
        async with self._lifecycle_lock:
            await self._stop_child()
            if not self._stopping:
                await self._spawn_child()

    async def _spawn_child(self) -> None:
        self._generation += 1
        generation = self._generation
        self.status = "starting"
        self.status_detail = None
        self.busy = False
        self.session_id = None
        self.config_options = []
        self.modes = {}
        await self._broadcast(self._status_event())

        command = [self.cecli, "--acp"] + self.extra_args

        try:
            self.process = await asyncio.create_subprocess_exec(
                *command,
                cwd=self.workspace,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=STREAM_LIMIT,
            )
        except OSError as err:
            self.process = None
            self.status = "exited"
            self.status_detail = f"could not start {self.cecli}: {err}"
            await self._broadcast({"type": "error", "message": self.status_detail})
            await self._broadcast(self._status_event())
            return

        process = self.process
        self._reader_tasks = [
            asyncio.create_task(self._read_stdout(generation, process)),
            asyncio.create_task(self._read_stderr(generation, process)),
            asyncio.create_task(self._wait_process(generation, process)),
        ]

        try:
            initialized = await self._request(
                "initialize",
                {"protocolVersion": 1, "clientCapabilities": {}},
                timeout=INITIALIZE_TIMEOUT,
            )
            info = (initialized or {}).get("agentInfo") or {}
            self.agent = {
                "name": info.get("name", "cecli"),
                "version": info.get("version", ""),
            }
            session = await self._request(
                "session/new",
                {"cwd": self.workspace, "mcpServers": []},
                timeout=SESSION_TIMEOUT,
            )
            self._apply_session(session or {})
            await self._broadcast(self._status_event())
            await self._broadcast(self._session_event())
        except asyncio.CancelledError:
            raise
        except Exception as err:
            if generation == self._generation and not self._stopping:
                process = self.process
                if process is not None and process.returncode is None:
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass
                    try:
                        await asyncio.wait_for(process.wait(), SHUTDOWN_TIMEOUT)
                    except asyncio.TimeoutError:
                        process.kill()
                self.status = "exited"
                self.status_detail = str(err)
                await self._broadcast({"type": "error", "message": str(err)})
                await self._broadcast(self._status_event())

    async def _stop_child(self) -> None:
        self._generation += 1
        process = self.process
        self.process = None
        self.busy = False
        self.session_id = None
        self._session_pending = False
        self._fail_pending("The agent stopped")
        await self._cancel_permissions()

        for task in self._reader_tasks:
            self._cancel_task(task)
        self._reader_tasks = []

        if process is not None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), SHUTDOWN_TIMEOUT)
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()

    async def _read_stdout(self, generation: int, process: asyncio.subprocess.Process) -> None:
        assert process.stdout is not None

        async for raw in self._lines(process.stdout):
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            try:
                message = json.loads(line)
            except json.JSONDecodeError as err:
                await self._broadcast(
                    {
                        "type": "log",
                        "level": "warning",
                        "message": f"ignored non-JSON stdout line: {err}",
                    }
                )
                continue

            if isinstance(message, dict):
                await self._dispatch(generation, message)

        code = await process.wait()
        await self._on_child_exit(generation, code)

    async def _read_stderr(self, generation: int, process: asyncio.subprocess.Process) -> None:
        assert process.stderr is not None

        async for raw in self._lines(process.stderr):
            message = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if not message:
                continue

            await asyncio.to_thread(print, message, file=sys.stderr, flush=True)
            if generation == self._generation:
                await self._broadcast({"type": "log", "level": "stderr", "message": message})

    async def _lines(self, stream: asyncio.StreamReader) -> AsyncIterator[bytes]:
        """Yield newline-delimited chunks without the reader's line-length limit.

        ``StreamReader.readline`` raises ``ValueError`` once a single line exceeds
        the stream limit, and a tool can legitimately print more than that at once.
        Splitting fixed-size reads keeps the reader alive and resynchronises after
        a line that is too large to keep.
        """
        buffer = b""
        dropping = False

        while True:
            chunk = await stream.read(65536)
            if not chunk:
                if buffer and not dropping:
                    yield buffer
                return

            buffer += chunk

            while True:
                newline = buffer.find(b"\n")
                if newline < 0:
                    break

                line = buffer[:newline]
                buffer = buffer[newline + 1 :]

                if dropping:
                    dropping = False
                    continue

                yield line

            if len(buffer) > MAX_LINE_BYTES:
                buffer = b""
                dropping = True

    async def _wait_process(self, generation: int, process: asyncio.subprocess.Process) -> None:
        code = await process.wait()
        await self._on_child_exit(generation, code)

    async def _on_child_exit(self, generation: int, code: int | None) -> None:
        if generation != self._generation or generation == self._exit_reported_for:
            return
        self._exit_reported_for = generation
        self.process = None
        self.status = "exited"
        self.status_detail = f"agent exited with code {code}"
        self.busy = False
        self.session_id = None
        self.config_options = []
        self.modes = {}
        self._session_pending = False
        self._fail_pending(self.status_detail)
        await self._cancel_permissions()
        await self._broadcast(self._status_event())

    async def _dispatch(self, generation: int, message: dict[str, Any]) -> None:
        if generation != self._generation:
            return
        method = message.get("method")
        if method is not None:
            if "id" in message:
                await self._handle_child_request(message)
            else:
                await self._handle_notification(message)
            return
        if "id" in message:
            self._resolve_response(message)
            return
        await self._broadcast(
            {"type": "log", "level": "warning", "message": "ignored malformed child message"}
        )

    async def _handle_notification(self, message: dict[str, Any]) -> None:
        if message.get("method") != "session/update":
            return

        params = message.get("params") or {}
        update = params.get("update") or {}
        if not isinstance(update, dict):
            return

        if update.get("sessionUpdate") == "config_option_update":
            if isinstance(update.get("configOptions"), list):
                self.config_options = update["configOptions"]
                self._sync_modes(self.config_options)
        elif update.get("sessionUpdate") == "current_mode_update":
            mode = update.get("currentModeId")
            if mode is not None:
                self.modes = {**self.modes, "currentModeId": mode}

        await self._broadcast(
            {
                "type": "update",
                "sessionId": params.get("sessionId") or self.session_id,
                "update": update,
            }
        )

    async def _handle_child_request(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        if message.get("method") == "session/request_permission":
            params = message.get("params") or {}
            permission = {
                "sessionId": params.get("sessionId") or self.session_id,
                "toolCall": params.get("toolCall") or {},
                "options": params.get("options") or [],
            }
            self._pending_permissions[request_id] = permission
            await self._broadcast({"type": "permission", "requestId": request_id, **permission})
            return

        await self._send_response(
            request_id,
            None,
            error={"code": -32601, "message": f"Method not found: {message.get('method')}"},
        )

    def _resolve_response(self, message: dict[str, Any]) -> None:
        future = self._pending.pop(message.get("id"), None)
        if future is None or future.done():
            return
        error = message.get("error")
        if error is not None:
            message_text = error.get("message") if isinstance(error, dict) else str(error)
            future.set_exception(AcpError(message_text))
        else:
            future.set_result(message.get("result"))

    async def _run_prompt(self, text: str) -> None:
        stop_reason = "error"
        cancelled = False
        try:
            result = await self._request(
                "session/prompt",
                {
                    "sessionId": self.session_id,
                    "prompt": [{"type": "text", "text": text}],
                },
            )
            stop_reason = (result or {}).get("stopReason") or "end_turn"
        except asyncio.CancelledError:
            cancelled = True
            raise
        except Exception as err:
            await self._broadcast({"type": "error", "message": str(err)})
        finally:
            if self._prompt_task is asyncio.current_task():
                self._prompt_task = None
                self.busy = False
                await self._cancel_permissions()
                if not cancelled:
                    await self._broadcast({"type": "prompt_done", "stopReason": stop_reason})

    async def _new_session_worker(self, cwd: str) -> None:
        try:
            session = await self._request(
                "session/new",
                {"cwd": cwd, "mcpServers": []},
                timeout=SESSION_TIMEOUT,
            )
            self._apply_session(session or {})
            await self._broadcast(self._status_event())
            await self._broadcast(self._session_event())
        except asyncio.CancelledError:
            raise
        except Exception as err:
            self.status = "ready" if self.process is not None and self.session_id else "exited"
            await self._broadcast({"type": "error", "message": str(err)})
            await self._broadcast(self._status_event())
        finally:
            self._session_pending = False

    async def _set_config_worker(self, config_id: str, value: str) -> None:
        try:
            result = await self._request(
                "session/set_config_option",
                {"sessionId": self.session_id, "configId": config_id, "value": value},
            )
            options = (result or {}).get("configOptions")
            if isinstance(options, list):
                self.config_options = options
                self._sync_modes(options)
                await self._broadcast(
                    {
                        "type": "update",
                        "sessionId": self.session_id,
                        "update": {
                            "sessionUpdate": "config_option_update",
                            "configOptions": options,
                        },
                    }
                )
        except asyncio.CancelledError:
            raise
        except Exception as err:
            await self._broadcast({"type": "error", "message": str(err)})

    async def _request(
        self, method: str, params: dict[str, Any], timeout: float | None = None
    ) -> Any:
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future

        try:
            await self._send_json(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            )
        except Exception as err:
            pending = self._pending.pop(request_id, None)
            if pending is not None and not pending.done():
                pending.cancel()
            raise AcpError(f"could not send {method}: {err}") from err

        try:
            if timeout is None:
                return await future
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError as err:
            raise AcpError(f"timed out waiting for {method}") from err
        except asyncio.CancelledError:
            future.cancel()
            raise
        finally:
            self._pending.pop(request_id, None)

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        await self._send_json({"jsonrpc": "2.0", "method": method, "params": params})

    async def _send_response(
        self, request_id: Any, result: Any, error: dict[str, Any] | None = None
    ) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        if error is None:
            message["result"] = result
        else:
            message["error"] = error
        try:
            await self._send_json(message)
        except AcpError:
            pass

    async def _send_json(self, message: dict[str, Any]) -> None:
        process = self.process
        if process is None or process.stdin is None:
            raise AcpError("The agent is not running")
        payload = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            async with self._write_lock:
                process.stdin.write(payload)
                await process.stdin.drain()
        except (ConnectionError, BrokenPipeError, RuntimeError) as err:
            raise AcpError(f"The agent is not accepting input: {err}") from err

    def _apply_session(self, session: dict[str, Any]) -> None:
        self.session_id = session.get("sessionId")
        options = session.get("configOptions")
        self.config_options = options if isinstance(options, list) else []
        modes = session.get("modes")
        self.modes = modes if isinstance(modes, dict) else {}
        if not self.modes and self.config_options:
            self._sync_modes(self.config_options)
        self.status = "ready"
        self.status_detail = None

    def _fail_pending(self, reason: str) -> None:
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(AcpError(reason))
        self._pending.clear()

    async def _cancel_permissions(self) -> None:
        for request_id in list(self._pending_permissions):
            self._pending_permissions.pop(request_id, None)
            await self._send_response(request_id, {"outcome": {"outcome": "cancelled"}})
            await self._broadcast(
                {"type": "permission_resolved", "requestId": request_id, "optionId": None}
            )

    def _sync_modes(self, options: list[dict[str, Any]]) -> None:
        mode = next((option for option in options if option.get("id") == "mode"), None)
        if mode is None:
            return
        self.modes = {
            **self.modes,
            "currentModeId": mode.get("currentValue"),
            "availableModes": [
                {"id": item.get("value"), "name": item.get("name")}
                for item in mode.get("options", [])
                if isinstance(item, dict) and "value" in item
            ],
        }

    def _permission_key(self, request_id: Any) -> Any:
        if request_id in self._pending_permissions:
            return request_id
        for key in self._pending_permissions:
            if str(key) == str(request_id):
                return key
        raise KeyError(request_id)

    def _status_event(self) -> dict[str, Any]:
        event: dict[str, Any] = {"type": "status", "status": self.status}
        if self.status_detail:
            event["detail"] = self.status_detail
        if self.agent:
            event["agent"] = self.agent
        return event

    def _session_event(self) -> dict[str, Any]:
        return {
            "type": "session",
            "sessionId": self.session_id,
            "configOptions": self.config_options,
            "modes": self.modes,
        }

    def _queue_event(self, event: dict[str, Any]) -> None:
        for client in list(self.clients):
            client.enqueue(event)

    async def _broadcast(self, event: dict[str, Any]) -> None:
        self._queue_event(event)

    def _cancel_task(self, task: asyncio.Task[Any] | None) -> None:
        if task is not None and not task.done():
            task.cancel()


class DesktopServer:
    """Minimal asyncio HTTP server for the API, SSE stream and static files."""

    def __init__(self, bridge: AcpBridge, root: Path, host: str = "127.0.0.1") -> None:
        self.bridge = bridge
        self.root = root
        self.host = host

    async def handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Serve keep-alive requests until the peer disconnects."""
        try:
            while True:
                request_line = await reader.readline()
                if not request_line:
                    return
                try:
                    method, target, version = request_line.decode("latin-1").split()
                except ValueError:
                    await self._write_json(writer, 400, {"ok": False, "error": "bad request"})
                    return

                headers = await self._read_headers(reader)
                if headers is None:
                    return

                if headers.get("transfer-encoding"):
                    await self._write_json(
                        writer, 400, {"ok": False, "error": "chunked bodies are not supported"}
                    )
                    return

                if not self._host_allowed(headers.get("host")):
                    await self._write_json(writer, 403, {"ok": False, "error": "host not allowed"})
                    return

                path = urllib.parse.unquote(urllib.parse.urlsplit(target).path)
                method = method.upper()
                if not self._origin_allowed(headers.get("origin"), headers.get("host")):
                    await self._write_json(
                        writer, 403, {"ok": False, "error": "origin not allowed"}
                    )
                    return

                if method == "POST" and path.startswith("/api/"):
                    media_type = headers.get("content-type", "").split(";")[0].strip().lower()
                    if media_type != "application/json":
                        await self._write_json(
                            writer, 415, {"ok": False, "error": "application/json is required"}
                        )
                        return

                try:
                    length = int(headers.get("content-length", "0"))
                except ValueError:
                    await self._write_json(
                        writer, 400, {"ok": False, "error": "bad content-length"}
                    )
                    return
                if length < 0:
                    await self._write_json(
                        writer, 400, {"ok": False, "error": "bad content-length"}
                    )
                    return
                if length > MAX_BODY:
                    await self._write_json(
                        writer,
                        413,
                        {"ok": False, "error": "request body too large"},
                        close=True,
                    )
                    return

                try:
                    body = await reader.readexactly(length) if length else b""
                except asyncio.IncompleteReadError:
                    return

                if method == "GET" and path == "/api/events":
                    await self._serve_events(reader, writer)
                    return

                status, payload, content_type = await self._route(method, path, body)
                keep_alive = (
                    version == "HTTP/1.1" and headers.get("connection", "").lower() != "close"
                )
                await self._write_response(
                    writer,
                    status,
                    payload,
                    content_type,
                    close=not keep_alive,
                )
                if not keep_alive:
                    return
        except (ConnectionError, asyncio.IncompleteReadError):
            return
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except (ConnectionError, RuntimeError):
                pass

    async def _route(self, method: str, path: str, body: bytes) -> tuple[int, bytes, str]:
        if method == "GET" and path == "/":
            return self._serve_file(self.root / "static" / "index.html")

        if method == "GET" and path.startswith("/static/"):
            return self._serve_static(path[len("/static/") :])

        if method == "GET" and path == "/api/health":
            return self._json(200, {"ok": True, "status": self.bridge.status})

        if method == "GET" and path == "/api/state":
            return self._json(200, self.bridge.snapshot())

        if method != "POST":
            return self._json(404, {"ok": False, "error": "not found"})

        if path == "/api/prompt":
            return await self._prompt(body)
        if path == "/api/cancel":
            await self.bridge.cancel()
            return self._json(202, {"ok": True})
        if path == "/api/new_session":
            return await self._new_session(body)
        if path == "/api/permission":
            return await self._permission(body)
        if path == "/api/config":
            return await self._config(body)
        if path == "/api/restart":
            await self.bridge.restart()
            return self._json(202, {"ok": True})

        return self._json(404, {"ok": False, "error": "not found"})

    async def _prompt(self, body: bytes) -> tuple[int, bytes, str]:
        data = self._decode_json(body)
        if data is None:
            return self._json(400, {"ok": False, "error": "invalid JSON"})
        text = data.get("text")
        if not isinstance(text, str) or not text.strip():
            return self._json(400, {"ok": False, "error": "text is required"})
        try:
            await self.bridge.prompt(text)
        except BridgeError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})
        return self._json(202, {"ok": True})

    async def _new_session(self, body: bytes) -> tuple[int, bytes, str]:
        data = self._decode_json(body) if body else {}
        if data is None:
            return self._json(400, {"ok": False, "error": "invalid JSON"})
        cwd = data.get("cwd") or self.bridge.workspace
        if not isinstance(cwd, str):
            return self._json(400, {"ok": False, "error": "cwd must be a string"})
        cwd = os.path.abspath(os.path.expanduser(cwd))
        try:
            await self.bridge.new_session(cwd)
        except BridgeError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})
        return self._json(202, {"ok": True})

    async def _permission(self, body: bytes) -> tuple[int, bytes, str]:
        data = self._decode_json(body)
        if data is None or "requestId" not in data or "optionId" not in data:
            return self._json(400, {"ok": False, "error": "requestId and optionId are required"})
        option_id = data.get("optionId")
        if option_id is not None and not isinstance(option_id, str):
            return self._json(400, {"ok": False, "error": "optionId must be a string or null"})
        try:
            await self.bridge.resolve_permission(data["requestId"], option_id)
        except KeyError:
            return self._json(404, {"ok": False, "error": "unknown permission request"})
        return self._json(200, {"ok": True})

    async def _config(self, body: bytes) -> tuple[int, bytes, str]:
        data = self._decode_json(body)
        if data is None:
            return self._json(400, {"ok": False, "error": "invalid JSON"})
        config_id = data.get("configId")
        value = data.get("value")
        if not isinstance(config_id, str) or not isinstance(value, str):
            return self._json(400, {"ok": False, "error": "configId and value are required"})
        try:
            await self.bridge.set_config(config_id, value)
        except BridgeError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})
        return self._json(202, {"ok": True})

    def _serve_static(self, relative: str) -> tuple[int, bytes, str]:
        try:
            static_root = (self.root / "static").resolve()
            parts = Path(relative).parts
            if not relative or any(
                part in ("..", ".", "/", "\\") or part.startswith(".") for part in parts
            ):
                return self._json(404, {"ok": False, "error": "not found"})
            if Path(relative).is_absolute():
                return self._json(404, {"ok": False, "error": "not found"})
            candidate = (static_root / relative).resolve()
            if candidate != static_root and static_root not in candidate.parents:
                return self._json(404, {"ok": False, "error": "not found"})
        except (OSError, ValueError):
            return self._json(404, {"ok": False, "error": "not found"})
        return self._serve_file(candidate)

    def _serve_file(self, path: Path) -> tuple[int, bytes, str]:
        if not path.is_file():
            return self._json(404, {"ok": False, "error": "not found"})
        content_type = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
        try:
            return 200, path.read_bytes(), content_type
        except OSError:
            return self._json(404, {"ok": False, "error": "not found"})

    async def _serve_events(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/event-stream\r\n"
            b"Cache-Control: no-cache\r\n"
            b"Connection: keep-alive\r\n"
            b"X-Accel-Buffering: no\r\n\r\n"
            b"retry: 2000\n\n"
        )
        client = SseClient()
        client.enqueue(self.bridge._status_event())
        if self.bridge.session_id is not None:
            client.enqueue(self.bridge._session_event())
        for request_id, permission in self.bridge._pending_permissions.items():
            client.enqueue({"type": "permission", "requestId": request_id, **permission})
        self.bridge.clients.add(client)
        try:
            await writer.drain()
        except ConnectionError:
            self.bridge.clients.discard(client)
            return

        writer_task = asyncio.create_task(self._sse_writer(client, writer))
        read_task = asyncio.create_task(self._wait_for_disconnect(reader))
        try:
            done, pending = await asyncio.wait(
                {writer_task, read_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        finally:
            self.bridge.clients.discard(client)
            await self._close_writer(writer)

    async def _sse_writer(self, client: SseClient, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                try:
                    data = await asyncio.wait_for(client.queue.get(), HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    writer.write(b": ping\n\n")
                    await writer.drain()
                    continue
                writer.write(f"data: {data}\n\n".encode("utf-8"))
                await writer.drain()
        except (ConnectionError, BrokenPipeError, RuntimeError):
            return

    async def _wait_for_disconnect(self, reader: asyncio.StreamReader) -> None:
        try:
            while await reader.read(1024):
                pass
        except (ConnectionError, RuntimeError):
            return

    async def _read_headers(self, reader: asyncio.StreamReader) -> dict[str, str] | None:
        headers: dict[str, str] = {}
        total = 0
        while True:
            line = await reader.readline()
            if not line:
                return None
            total += len(line)
            if total > 64 * 1024:
                return None
            if line in (b"\r\n", b"\n"):
                return headers
            try:
                name, value = line.decode("latin-1").split(":", 1)
            except ValueError:
                return None
            headers[name.strip().lower()] = value.strip()

    def _host_allowed(self, host_header: str | None) -> bool:
        """Reject requests whose Host would enable DNS-rebinding reads."""
        if not host_header:
            return True
        return _authority_host(host_header) in self._allowed_hosts()

    def _origin_allowed(self, origin: str | None, host_header: str | None) -> bool:
        """Allow same-origin and localhost-origin requests only."""
        if not origin:
            return True
        parsed = urllib.parse.urlsplit(origin)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        if parsed.hostname not in self._allowed_hosts():
            return False
        return (
            host_header is None or _authority_host(host_header) == (parsed.hostname or "").lower()
        )

    def _allowed_hosts(self) -> set[str]:
        names = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "::"}
        names.add(self.host.strip("[]"))
        return names

    def _decode_json(self, body: bytes) -> dict[str, Any] | None:
        if not body:
            return {}
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _json(self, status: int, value: dict[str, Any]) -> tuple[int, bytes, str]:
        return status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json"

    async def _write_json(
        self,
        writer: asyncio.StreamWriter,
        status: int,
        value: dict[str, Any],
        close: bool = True,
    ) -> None:
        _, payload, content_type = self._json(status, value)
        await self._write_response(writer, status, payload, content_type, close=close)

    async def _write_response(
        self,
        writer: asyncio.StreamWriter,
        status: int,
        payload: bytes,
        content_type: str,
        close: bool,
    ) -> None:
        try:
            writer.write(
                (
                    f"HTTP/1.1 {status} {self._reason(status)}\r\n"
                    f"Content-Type: {content_type}\r\n"
                    f"Cache-Control: {_cache_control(content_type)}\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    f"Connection: {'close' if close else 'keep-alive'}\r\n\r\n"
                ).encode("latin-1")
                + payload
            )
            await writer.drain()
        except (ConnectionError, BrokenPipeError):
            return

    async def _close_writer(self, writer: asyncio.StreamWriter) -> None:
        try:
            writer.close()
            await writer.wait_closed()
        except (ConnectionError, RuntimeError):
            pass

    def _reason(self, status: int) -> str:
        return {
            200: "OK",
            202: "Accepted",
            400: "Bad Request",
            404: "Not Found",
            405: "Method Not Allowed",
            409: "Conflict",
            413: "Payload Too Large",
            415: "Unsupported Media Type",
            500: "Internal Server Error",
        }.get(status, "Error")


class ServerConfig:
    """Command-line configuration for the bridge server."""

    def __init__(
        self,
        host: str,
        port: int,
        workspace: str,
        cecli: str,
        extra_args: list[str],
        open_browser: bool,
    ) -> None:
        self.host = host
        self.port = port
        self.workspace = workspace
        self.cecli = cecli
        self.extra_args = extra_args
        self.open_browser = open_browser


def parse_args(argv: list[str]) -> ServerConfig:
    """Parse server flags, splitting cecli passthrough arguments after ``--``."""
    if "--" in argv:
        split = argv.index("--")
        argv, extra_args = argv[:split], argv[split + 1 :]
    else:
        extra_args = []

    parser = argparse.ArgumentParser(description="Serve the cecli desktop bridge")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (loopback by default)")
    parser.add_argument("--port", type=int, default=8765, help="bind port")
    parser.add_argument("--workspace", default=os.getcwd(), help="workspace directory")
    parser.add_argument("--cecli", default=None, help="cecli executable")
    parser.add_argument("--open", action="store_true", help="open the UI in a browser")
    args = parser.parse_args(argv)

    cecli = args.cecli or os.environ.get("CECLI_BIN") or shutil.which("cecli") or "cecli"
    workspace = os.path.abspath(os.path.expanduser(args.workspace))
    return ServerConfig(args.host, args.port, workspace, cecli, extra_args, args.open)


async def run_server(config: ServerConfig) -> None:
    """Bind the HTTP server, start the child and serve until a signal arrives."""
    root = Path(__file__).resolve().parent
    bridge = AcpBridge(config.cecli, config.extra_args, config.workspace)
    app = DesktopServer(bridge, root, config.host)
    server = await asyncio.start_server(app.handle_connection, config.host, config.port)
    port = server.sockets[0].getsockname()[1] if server.sockets else config.port
    display_host = config.host
    if ":" in display_host and not display_host.startswith("["):
        display_host = f"[{display_host}]"
    url = f"http://{display_host}:{port}/"
    print(f"cecli desktop bridge listening on {url}", flush=True)

    if not is_loopback_host(config.host):
        print(
            f"warning: {config.host} is not a loopback address; the bridge has no authentication",
            file=sys.stderr,
            flush=True,
        )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass

    await bridge.start()
    if config.open_browser:
        asyncio.create_task(_open_browser(url))

    try:
        await stop.wait()
    finally:
        server.close()
        try:
            await asyncio.wait_for(server.wait_closed(), 2.0)
        except asyncio.TimeoutError:
            pass
        await bridge.shutdown()


async def _open_browser(url: str) -> None:
    await asyncio.sleep(0.2)
    try:
        await asyncio.get_running_loop().run_in_executor(None, webbrowser.open, url)
    except Exception:
        pass


def is_loopback_host(host: str) -> bool:
    """Whether a bind host is loopback, resolving names when needed."""
    if host in ("localhost", "::1"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    try:
        return ipaddress.ip_address(socket.gethostbyname(host)).is_loopback
    except (OSError, ValueError):
        return False


def _cache_control(content_type: str) -> str:
    """Immutable caching for content-hashed assets, revalidation for documents."""
    if content_type.startswith(("text/css", "text/javascript", "font/", "image/")):
        return "public, max-age=31536000, immutable"
    return "no-cache"


def _authority_host(authority: str) -> str:
    """Hostname from a Host/authority header, without port or brackets."""
    try:
        parsed = urllib.parse.urlsplit("//" + authority)
    except ValueError:
        return ""
    return (parsed.hostname or "").strip("[]").lower()


def main(argv: list[str] | None = None) -> int:
    """Entry point used by ``python3 desktop/server.py``."""
    config = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        asyncio.run(run_server(config))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
