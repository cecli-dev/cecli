"""Localhost HTTP/SSE bridge between the desktop UI and ``cecli --acp``.

Only the Python standard library is used. The module serves the static UI,
exposes a small JSON API, and supervises one ACP child process over
newline-delimited JSON-RPC on its stdin/stdout. Child stderr is republished to
the browser as log events and echoed to the server's stderr.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import ipaddress
import json
import os
import secrets
import shutil
import signal
import socket
import struct
import sys
import time
import urllib.parse
import uuid
import webbrowser
from pathlib import Path
from typing import Any, AsyncIterator

MAX_BODY = 1024 * 1024
SSE_QUEUE_SIZE = 512
MAX_LINE_BYTES = 32 * 1024 * 1024
STREAM_LIMIT = 10 * 1024 * 1024
HEARTBEAT_SECONDS = 15.0
WS_MAX_MESSAGE = 1024 * 1024
WS_HEARTBEAT_SECONDS = 15.0
WS_SUBPROTOCOL = "cecli.desktop.v1"
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
WS_PROTOCOL = WS_SUBPROTOCOL
MAX_SESSIONS = max(1, int(os.environ.get("CECLI_DESKTOP_MAX_SESSIONS", "8")))
INITIALIZE_TIMEOUT = 20.0
SESSION_TIMEOUT = 300.0
SHUTDOWN_TIMEOUT = 5.0
SYNC_SECONDS = 5.0

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

    def __init__(
        self,
        cecli: str,
        extra_args: list[str],
        workspace: str,
        bridge_id: str | None = None,
        title: str | None = None,
        primary: bool = False,
    ) -> None:
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
        self.bridge_id = bridge_id or "primary"
        self.title = title or os.path.basename(workspace.rstrip(os.sep)) or "cecli"
        self.primary = primary
        self.created_at = time.time()
        self.activity = "starting"
        self.activity_detail = ""
        self.last_activity = self.created_at
        self.subagents: dict[str, dict[str, Any]] = {}
        self.details: dict[str, Any] = {
            "skills": [],
            "mcpServers": [],
            "workflows": [],
            "contextFiles": [],
        }
        self.extra_sinks: list[Any] = []
        self.details_supported: bool | None = None
        self._details_task: asyncio.Task[Any] | None = None
        self._poll_task: asyncio.Task[Any] | None = None
        self.available_commands: list[dict[str, Any]] = []

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
            "bridgeId": self.bridge_id,
            "title": self.title,
            "primary": self.primary,
            "status": self.status,
            "busy": self.busy,
            "workspace": self.workspace,
            "sessionId": self.session_id,
            "configOptions": self.config_options,
            "modes": self.modes,
            "agent": self.agent,
            "activity": self.activity,
            "activityDetail": self.activity_detail,
            "createdAt": self.created_at,
            "lastActivity": self.last_activity,
            "subagents": [item for item in self.subagents.values() if not item.get("removed")],
            "detailsSupported": self.details_supported,
            "skills": self.details.get("skills", []),
            "mcpServers": self.details.get("mcpServers", []),
            "workflows": self.details.get("workflows", []),
            "contextFiles": self.details.get("contextFiles", []),
            "permissions": [
                {"requestId": request_id, "bridgeId": self.bridge_id, **permission}
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
        self.activity = "running"
        self.last_activity = time.time()
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
        if config_id == "mode":
            raise BridgeError(409, "Mode switching is disabled")
        if self.status != "ready" or self.session_id is None:
            raise BridgeError(409, "The agent is not ready")
        task = asyncio.create_task(self._set_config_worker(config_id, value))
        self._config_tasks.add(task)
        task.add_done_callback(self._config_tasks.discard)

    @property
    def permission_count(self) -> int:
        """Number of pending permission requests for the sidebar badge."""
        return len(self._pending_permissions)

    async def call_extension(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Call one ``cecli/*`` extension on the live child and cache details."""
        if self.status != "ready" or self.session_id is None:
            raise BridgeError(409, "The agent is not ready")

        payload = {"sessionId": self.session_id, **params}
        try:
            result = await self._request(method, payload, timeout=30.0)
        except (AcpError, asyncio.TimeoutError) as err:
            raise BridgeError(502, str(err) or f"{method} failed") from err

        if isinstance(result, dict):
            self._apply_details(result)
        return result if isinstance(result, dict) else {}

    async def set_skill(self, action: str, name: str) -> dict[str, Any]:
        """Load, remove, include or exclude one skill."""
        return await self.call_extension("cecli/skill", {"action": action, "name": name})

    async def set_mcp(self, action: str, name: str) -> dict[str, Any]:
        """Connect or disconnect one MCP server."""
        return await self.call_extension("cecli/mcp", {"action": action, "name": name})

    async def run_workflow(self, name: str) -> dict[str, Any]:
        """Run a workflow as a normal slash command in the primary session.

        The workflow then streams into the same transcript as any other turn
        instead of running invisibly beside it.
        """
        if self.busy or self._session_pending:
            raise BridgeError(409, "Finish or stop the current turn first")
        if not isinstance(name, str) or not name.strip():
            raise BridgeError(400, "name is required")
        await self.prompt(f"/workflows run {name.strip()}")
        return {"ok": True, "workflow": name.strip()}

    async def complete(self, text: str) -> dict[str, Any]:
        """Return composer completion candidates for the current coder."""
        if self.status != "ready" or self.session_id is None:
            raise BridgeError(409, "The agent is not ready")
        if not isinstance(text, str):
            raise BridgeError(400, "text is required")
        return await self.call_extension("cecli/complete", {"text": text})

    async def history(self) -> dict[str, Any]:
        """Return each coder's conversation stream for transcript replay."""
        if self.status != "ready" or self.session_id is None:
            raise BridgeError(409, "The agent is not ready")

        result = await self.call_extension("cecli/history", {})
        messages = result.get("messages")
        subagents = result.get("subagents")
        return {
            "messages": messages if isinstance(messages, list) else [],
            "subagents": subagents if isinstance(subagents, list) else [],
        }

    async def set_context(self, action: str, path: str, read_only: bool = False) -> dict[str, Any]:
        """Add or remove a context file on the child."""
        return await self.call_extension(
            "cecli/context", {"action": action, "path": path, "readOnly": read_only}
        )

    async def send_subagent_message(self, child_session_id: str, text: str) -> dict[str, Any]:
        """Deliver a message to one sub-agent session."""
        if self.status != "ready" or self.session_id is None:
            raise BridgeError(409, "The agent is not ready")
        try:
            result = await self._request(
                "cecli/subagent/message",
                {"sessionId": child_session_id, "text": text},
                timeout=30.0,
            )
        except (AcpError, asyncio.TimeoutError) as err:
            raise BridgeError(502, str(err)) from err
        return result if isinstance(result, dict) else {}

    async def cancel_subagent(self, child_session_id: str) -> None:
        """Cancel the current turn of one sub-agent session."""
        if self.session_id is None:
            return
        await self._notify("session/cancel", {"sessionId": child_session_id})

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
        self.activity = "starting"
        self.activity_detail = ""
        self.busy = False
        self.session_id = None
        self.config_options = []
        self.modes = {}
        await self._broadcast(self._status_event())

        command = [self.cecli, "--acp"] + self.extra_args
        spawn_kwargs: dict[str, Any] = {}
        if os.name == "posix":
            # Own process group so terminate()/kill() reach tool subprocesses too
            spawn_kwargs["start_new_session"] = True

        try:
            self.process = await asyncio.create_subprocess_exec(
                *command,
                cwd=self.workspace,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=STREAM_LIMIT,
                **spawn_kwargs,
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
                {"protocolVersion": 1, "clientCapabilities": {"subagents": {}}},
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
            await self._ensure_agent_mode()
            self._schedule_details_refresh()
            self._start_poll()
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
        self._cancel_task(self._poll_task)
        self._fail_pending("The agent stopped")
        await self._cancel_permissions()

        for task in self._reader_tasks:
            self._cancel_task(task)
        self._reader_tasks = []

        if process is not None:
            try:
                _signal_process(process)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), SHUTDOWN_TIMEOUT)
            except asyncio.TimeoutError:
                try:
                    _signal_process(process, hard=True)
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
        self.activity = "exited"
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

        kind = update.get("sessionUpdate")
        if kind == "config_option_update":
            if isinstance(update.get("configOptions"), list):
                self.config_options = update["configOptions"]
                self._sync_modes(self.config_options)
        elif kind == "current_mode_update":
            mode = update.get("currentModeId")
            if mode is not None:
                self.modes = {**self.modes, "currentModeId": mode}
        elif kind == "available_commands_update":
            commands = update.get("availableCommands")
            if isinstance(commands, list):
                self.available_commands = commands
        elif kind in ("tool_call", "tool_call_update"):
            if update.get("title"):
                self.activity_detail = str(update["title"])
            if update.get("status") == "completed":
                self.activity_detail = ""
        elif kind == "state_update":
            state = update.get("state")
            if state:
                self.activity = str(state)
                if state == "idle":
                    self.activity_detail = ""
        elif kind == "subagent_update":
            self._track_subagent(params.get("sessionId"), update)
            await self._broadcast(self._subagents_event())

        self.last_activity = time.time()

        await self._broadcast(
            {
                "type": "update",
                "sessionId": params.get("sessionId") or self.session_id,
                "update": update,
            }
        )

    def _track_subagent(self, parent_session_id: Any, update: dict[str, Any]) -> None:
        """Fold one ``subagent_update`` into the cached child-session tree."""
        child_id = update.get("sessionId")
        if not child_id:
            return

        entry = self.subagents.setdefault(
            str(child_id),
            {"sessionId": str(child_id), "parentSessionId": parent_session_id},
        )
        if parent_session_id:
            entry["parentSessionId"] = parent_session_id
        if update.get("title"):
            entry["title"] = str(update["title"])
        if update.get("description"):
            entry["description"] = str(update["description"])

        if "capabilities" in update and update["capabilities"] is None:
            entry["removed"] = True
            entry["running"] = False
        elif "capabilities" in update:
            entry["announced"] = True

        state = update.get("state")
        if isinstance(state, dict):
            entry["state"] = state.get("state", "idle")
            entry["running"] = state.get("state") == "running"
            if state.get("stopReason"):
                entry["stopReason"] = state["stopReason"]
            if state.get("error"):
                entry["error"] = state["error"]

    def _start_poll(self) -> None:
        """Keep the sidebar's agent tree and registries fresh in the background."""
        self._cancel_task(self._poll_task)
        self._poll_task = asyncio.create_task(self._poll_details())

    async def _poll_details(self) -> None:
        while not self._stopping:
            await asyncio.sleep(SYNC_SECONDS)
            if self.status != "ready" or self.session_id is None:
                continue
            try:
                await self.refresh_details()
            except asyncio.CancelledError:
                raise
            except Exception:
                continue

    def _schedule_details_refresh(self) -> None:
        """Refresh sidebar state without blocking the handshake path."""
        self._cancel_task(self._details_task)
        self._details_task = asyncio.create_task(self.refresh_details())

    async def refresh_details(self) -> dict[str, Any]:
        """Ask the child for skills, MCP servers, workflows and context files."""
        if self.status != "ready" or self.session_id is None:
            return self.details
        try:
            result = await self._request(
                "cecli/state", {"sessionId": self.session_id}, timeout=10.0
            )
        except (AcpError, asyncio.TimeoutError):
            return self.details

        if isinstance(result, dict):
            self._apply_details(result)
            await self._broadcast(
                {
                    "type": "details",
                    "details": self.details,
                    "subagents": [
                        item for item in self.subagents.values() if not item.get("removed")
                    ],
                }
            )
        return self.details

    def _apply_details(self, result: dict[str, Any]) -> None:
        if result.get("ready") is False:
            self.details_supported = (
                False if self.details_supported is None else self.details_supported
            )
            return

        self.details_supported = True
        for key in ("skills", "mcpServers", "workflows", "contextFiles"):
            value = result.get(key)
            if isinstance(value, list):
                self.details[key] = value
        if isinstance(result.get("subagents"), list):
            for item in result["subagents"]:
                child_id = item.get("sessionId")
                if not child_id:
                    continue
                key = str(child_id)
                entry = self.subagents.setdefault(key, {"sessionId": key})
                was_removed = entry.get("removed", False)
                entry.update(item)
                entry["sessionId"] = key
                if was_removed:
                    entry["removed"] = True
        if result.get("activity"):
            self.activity = str(result["activity"])

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
                self.activity = "idle"
                self.last_activity = time.time()
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
            await self._ensure_agent_mode()
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

    async def _ensure_agent_mode(self) -> None:
        """Keep the desktop session in agent mode without a mode picker."""
        if self.status != "ready" or self.session_id is None:
            return

        mode = next((option for option in self.config_options if option.get("id") == "mode"), None)
        if mode is None:
            return
        if mode.get("currentValue") in ("agent", "agent-yolo"):
            return

        try:
            result = await self._request(
                "session/set_config_option",
                {"sessionId": self.session_id, "configId": "mode", "value": "agent"},
                timeout=30.0,
            )
        except (AcpError, asyncio.TimeoutError):
            return

        options = (result or {}).get("configOptions")
        if isinstance(options, list):
            self.config_options = options
            self._sync_modes(options)

    def _apply_session(self, session: dict[str, Any]) -> None:
        self.session_id = session.get("sessionId")
        options = session.get("configOptions")
        self.config_options = options if isinstance(options, list) else []
        modes = session.get("modes")
        self.modes = modes if isinstance(modes, dict) else {}
        if not self.modes and self.config_options:
            self._sync_modes(self.config_options)
        self.status = "ready"
        self.activity = "idle"
        self.last_activity = time.time()
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
        event: dict[str, Any] = {
            "type": "status",
            "bridgeId": self.bridge_id,
            "status": self.status,
            "activity": self.activity,
        }
        if self.status_detail:
            event["detail"] = self.status_detail
        if self.agent:
            event["agent"] = self.agent
        return event

    def _subagents_event(self) -> dict[str, Any]:
        return {
            "type": "subagents",
            "bridgeId": self.bridge_id,
            "subagents": [item for item in self.subagents.values() if not item.get("removed")],
        }

    def _session_event(self) -> dict[str, Any]:
        return {
            "type": "session",
            "bridgeId": self.bridge_id,
            "sessionId": self.session_id,
            "configOptions": self.config_options,
            "modes": self.modes,
        }

    def _queue_event(self, event: dict[str, Any]) -> None:
        for client in list(self.clients):
            client.enqueue(event)

    async def _broadcast(self, event: dict[str, Any]) -> None:
        """Queue one event for SSE clients and manager-level sinks."""
        event.setdefault("bridgeId", self.bridge_id)
        if self.session_id and "sessionId" not in event:
            event["sessionId"] = self.session_id

        sinks = list(self.extra_sinks)
        if not sinks:
            self._queue_event(event)
            return
        for sink in sinks:
            try:
                sink(event)
            except Exception as err:
                print(f"cecli desktop event sink failed: {err}", file=sys.stderr, flush=True)

    def _cancel_task(self, task: asyncio.Task[Any] | None) -> None:
        if task is not None and not task.done():
            task.cancel()


class WsClient:
    """One WebSocket peer with a single outbound writer queue.

    The broadcaster and request handler only enqueue here; one writer task owns
    the StreamWriter so frames can never interleave.
    """

    def __init__(self) -> None:
        self.queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=SSE_QUEUE_SIZE)

    def enqueue(self, event: dict[str, Any]) -> None:
        """Queue a state/update event for the peer."""
        self._put(("event", event))

    def enqueue_response(self, payload: dict[str, Any]) -> None:
        """Queue a command response for the peer."""
        self._put(("response", payload))

    def enqueue_frame(self, opcode: int, payload: bytes = b"") -> None:
        """Queue a raw control/data frame (pong, close)."""
        self._put(("frame", (opcode, payload)))

    def _put(self, item: tuple[str, Any]) -> None:
        while True:
            try:
                self.queue.put_nowait(item)
                return
            except asyncio.QueueFull:
                try:
                    self.queue.get_nowait()
                except asyncio.QueueEmpty:
                    return


class SessionManager:
    """Own every parent cecli child; one child serves one ACP session."""

    def __init__(
        self,
        cecli: str,
        extra_args: list[str],
        default_workspace: str,
        max_sessions: int = MAX_SESSIONS,
        token: str = "",
    ) -> None:
        self.cecli = cecli
        self.extra_args = _sanitize_extra_args(extra_args)
        self.default_workspace = default_workspace
        self.max_sessions = max_sessions
        self.token = token
        roots = os.environ.get("CECLI_DESKTOP_ALLOWED_ROOTS", "")
        self.allowed_roots = [os.path.realpath(default_workspace)] + [
            os.path.realpath(item) for item in roots.split(os.pathsep) if item.strip()
        ]
        self.sessions: dict[str, AcpBridge] = {}
        self.order: list[str] = []
        self.active_id: str | None = None
        self.ws_clients: set[WsClient] = set()
        self.sse_clients: set[SseClient] = set()
        self._counter = 0

    def create(self, cwd: str | None = None, title: str | None = None) -> AcpBridge:
        """Add a parent session, spawning its ACP child in the background."""
        if len(self.sessions) >= self.max_sessions:
            raise BridgeError(409, f"At most {self.max_sessions} sessions are supported")

        self._counter += 1
        bridge_id = f"s{self._counter}-{uuid.uuid4().hex[:8]}"
        workspace = os.path.abspath(os.path.expanduser(cwd or self.default_workspace))
        real_workspace = os.path.realpath(workspace)
        if not os.path.isdir(real_workspace):
            raise BridgeError(400, f"Workspace does not exist: {workspace}")
        if not any(
            real_workspace == root or real_workspace.startswith(root + os.sep)
            for root in self.allowed_roots
        ):
            raise BridgeError(403, "Workspace is outside the allowed roots")
        bridge = AcpBridge(
            self.cecli,
            self.extra_args,
            workspace,
            bridge_id=bridge_id,
            primary=not self.sessions,
            title=title or os.path.basename(workspace.rstrip(os.sep)) or "cecli",
        )
        bridge.extra_sinks.append(self.publish)
        self.sessions[bridge_id] = bridge
        self.order.append(bridge_id)
        if self.active_id is None:
            self.active_id = bridge_id
        asyncio.create_task(bridge.start())
        self.publish_sessions()
        return bridge

    def get(self, bridge_id: str | None = None) -> AcpBridge:
        """Resolve an exact bridge id; never fall back to another session."""
        if not bridge_id:
            return self.get_default()
        bridge = self.sessions.get(str(bridge_id))
        if bridge is None:
            raise BridgeError(404, "Unknown session")
        return bridge

    def get_mutation(self, bridge_id: str | None = None) -> AcpBridge:
        """Resolve a mutating target; require an explicit id when ambiguous."""
        if bridge_id:
            return self.get(bridge_id)
        if len(self.sessions) > 1:
            raise BridgeError(400, "bridgeId is required when multiple sessions exist")
        return self.get_default()

    def get_default(self) -> AcpBridge:
        """The bootstrap/default session used by legacy single-session calls."""
        bridge = self.sessions.get(self.active_id or "") or next(iter(self.sessions.values()), None)
        if bridge is None:
            raise BridgeError(404, "No session is available")
        return bridge

    def list_sessions(self) -> list[dict[str, Any]]:
        """Cheap summaries for the sidebar tree."""
        summaries = []
        for bridge_id in self.order:
            bridge = self.sessions.get(bridge_id)
            if bridge is None:
                continue
            summaries.append(
                {
                    "bridgeId": bridge.bridge_id,
                    "primary": bridge.primary,
                    "title": bridge.title,
                    "workspace": bridge.workspace,
                    "status": bridge.status,
                    "activity": bridge.activity,
                    "activityDetail": bridge.activity_detail,
                    "busy": bridge.busy,
                    "sessionId": bridge.session_id,
                    "createdAt": bridge.created_at,
                    "lastActivity": bridge.last_activity,
                    "subagents": [
                        item for item in bridge.subagents.values() if not item.get("removed")
                    ],
                    "skills": bridge.details.get("skills", []),
                    "mcpServers": bridge.details.get("mcpServers", []),
                    "workflows": bridge.details.get("workflows", []),
                    "contextFiles": bridge.details.get("contextFiles", []),
                    "permissionCount": len(bridge._pending_permissions),
                }
            )
        return summaries

    def snapshot(self, bridge_id: str | None = None) -> dict[str, Any]:
        """State for one bridge plus the manager-wide session list."""
        bridge = self.get(bridge_id)
        snapshot = bridge.snapshot()
        snapshot["sessions"] = self.list_sessions()
        snapshot["activeBridgeId"] = self.active_id
        snapshot["maxSessions"] = self.max_sessions
        return snapshot

    async def close(self, bridge_id: str | None = None) -> None:
        """Stop one parent session and drop it from the tree."""
        if not bridge_id:
            bridge_id = self.active_id
        if not bridge_id or bridge_id not in self.sessions:
            return
        bridge = self.sessions[bridge_id]
        if bridge.primary:
            raise BridgeError(409, "The primary session cannot be closed")
        if bridge.busy:
            raise BridgeError(409, "Finish or stop the current turn first")
        bridge.activity = "closing"
        self.publish_sessions()
        try:
            await bridge.shutdown()
        finally:
            self.sessions.pop(bridge.bridge_id, None)
            if bridge.bridge_id in self.order:
                self.order.remove(bridge.bridge_id)
            if self.active_id == bridge.bridge_id:
                self.active_id = self.order[0] if self.order else None
            self.publish_sessions()

    async def shutdown(self) -> None:
        """Stop every child concurrently, bounded by the normal grace period."""
        bridges = list(self.sessions.values())
        self.sessions.clear()
        self.order.clear()
        self.active_id = None
        if not bridges:
            return
        await asyncio.gather(*(bridge.shutdown() for bridge in bridges), return_exceptions=True)

    def publish(self, event: dict[str, Any]) -> None:
        """Fan one event out to every SSE client."""
        seen: set[int] = set()
        for bridge in self.sessions.values():
            for client in list(bridge.clients):
                if id(client) in seen:
                    continue
                seen.add(id(client))
                client.enqueue(event)
        for client in list(self.sse_clients):
            client.enqueue(event)

    def publish_sessions(self) -> None:
        """Announce the current parent-session tree."""
        self.publish(
            {
                "type": "sessions",
                "sessions": self.list_sessions(),
                "activeBridgeId": self.active_id,
            }
        )


class DesktopServer:
    """Minimal asyncio HTTP server for the API, SSE stream and static files."""

    def __init__(
        self,
        sessions: SessionManager,
        root: Path,
        host: str = "127.0.0.1",
        token: str = "",
    ) -> None:
        self.sessions = sessions
        self.token = token
        self.root = root
        self.host = host

    @property
    def bridge(self) -> AcpBridge:
        """The default parent session, kept for single-session callers."""
        return self.sessions.get_default()

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

                parsed = urllib.parse.urlsplit(target)
                path = urllib.parse.unquote(parsed.path)
                query = urllib.parse.parse_qs(parsed.query)
                method = method.upper()
                if not self._origin_allowed(headers.get("origin"), headers.get("host")):
                    await self._write_json(
                        writer, 403, {"ok": False, "error": "origin not allowed"}
                    )
                    return

                if method == "GET" and path == "/ws":
                    await self._serve_websocket(reader, writer, headers)
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

                try:
                    status, payload, content_type = await self._route(method, path, body, query)
                except BridgeError as err:
                    await self._write_json(writer, err.status, {"ok": False, "error": str(err)})
                    return
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

    async def _route(
        self, method: str, path: str, body: bytes, query: dict[str, list[str]]
    ) -> tuple[int, bytes, str]:
        if method == "GET" and path == "/":
            return self._serve_index()

        if method == "GET" and path.startswith("/static/"):
            return self._serve_static(path[len("/static/") :])

        if method == "GET" and path == "/api/health":
            return self._json(
                200,
                {
                    "ok": True,
                    "status": self.sessions.get_default().status,
                    "sessions": len(self.sessions.sessions),
                },
            )

        if method == "GET" and path == "/api/state":
            return self._json(200, self.sessions.snapshot(self._query_bridge(query)))

        if method == "GET" and path == "/api/history":
            bridge = self.sessions.get(self._query_bridge(query))
            try:
                result = await bridge.history()
            except BridgeError as err:
                return self._json(err.status, {"ok": False, "error": str(err)})
            return self._json(200, {"ok": True, **result})

        if method == "GET" and path == "/api/sessions":
            return self._json(
                200,
                {
                    "sessions": self.sessions.list_sessions(),
                    "activeBridgeId": self.sessions.active_id,
                    "maxSessions": self.sessions.max_sessions,
                },
            )

        if method != "POST":
            return self._json(404, {"ok": False, "error": "not found"})

        if path == "/api/sessions":
            return await self._create_session(body)
        if path == "/api/sessions/close":
            return await self._close_session(body)
        if path == "/api/prompt":
            return await self._prompt(body)
        if path == "/api/cancel":
            bridge = self._bridge_from(body)
            await bridge.cancel()
            return self._json(202, {"ok": True})
        if path == "/api/new_session":
            return await self._new_session(body)
        if path == "/api/permission":
            return await self._permission(body)
        if path == "/api/config":
            return await self._config(body)
        if path == "/api/restart":
            await self._bridge_from(body).restart()
            return self._json(202, {"ok": True})
        if path == "/api/complete":
            return await self._complete(body)
        if path == "/api/details":
            return await self._details(body)
        if path == "/api/subagent/message":
            return await self._subagent_message(body)
        if path == "/api/subagent/cancel":
            return await self._subagent_cancel(body)
        if path in ("/api/skills", "/api/mcp", "/api/workflows", "/api/context"):
            return await self._registry_action(path.rsplit("/", 1)[-1], body)

        return self._json(404, {"ok": False, "error": "not found"})

    def _query_bridge(self, query: dict[str, list[str]]) -> str | None:
        values = query.get("bridgeId") or query.get("session") or []
        return values[0] if values else None

    def _bridge_from(self, body: bytes) -> AcpBridge:
        data = self._decode_json(body) if body else {}
        if data is None:
            raise BridgeError(400, "invalid JSON")
        return self.sessions.get_mutation(data.get("bridgeId"))

    async def _create_session(self, body: bytes) -> tuple[int, bytes, str]:
        data = self._decode_json(body) if body else {}
        if data is None:
            return self._json(400, {"ok": False, "error": "invalid JSON"})
        cwd = data.get("cwd") or self.sessions.default_workspace
        if not isinstance(cwd, str):
            return self._json(400, {"ok": False, "error": "cwd must be a string"})
        try:
            bridge = self.sessions.create(cwd, data.get("title"))
        except BridgeError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})
        return self._json(
            201,
            {
                "ok": True,
                "bridgeId": bridge.bridge_id,
                "state": self.sessions.snapshot(bridge.bridge_id),
            },
        )

    async def _close_session(self, body: bytes) -> tuple[int, bytes, str]:
        data = self._decode_json(body) if body else {}
        if data is None:
            return self._json(400, {"ok": False, "error": "invalid JSON"})
        try:
            await self.sessions.close(data.get("bridgeId"))
        except BridgeError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})
        return self._json(200, {"ok": True, "sessions": self.sessions.list_sessions()})

    async def _complete(self, body: bytes) -> tuple[int, bytes, str]:
        data = self._decode_json(body) or {}
        bridge = self.sessions.get_mutation(data.get("bridgeId"))
        text = data.get("text")
        if not isinstance(text, str):
            return self._json(400, {"ok": False, "error": "text is required"})
        try:
            result = await bridge.complete(text)
        except BridgeError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})
        return self._json(200, {"ok": True, **result})

    async def _details(self, body: bytes) -> tuple[int, bytes, str]:
        bridge = self._bridge_from(body)
        await bridge.refresh_details()
        return self._json(200, self.sessions.snapshot(bridge.bridge_id))

    async def _subagent_message(self, body: bytes) -> tuple[int, bytes, str]:
        data = self._decode_json(body) or {}
        bridge = self.sessions.get_mutation(data.get("bridgeId"))
        session_id = data.get("sessionId")
        text = data.get("text")
        if not isinstance(session_id, str) or not isinstance(text, str) or not text.strip():
            return self._json(400, {"ok": False, "error": "sessionId and text are required"})
        try:
            result = await bridge.send_subagent_message(session_id, text)
        except BridgeError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})
        return self._json(200, {"ok": True, "result": result})

    async def _subagent_cancel(self, body: bytes) -> tuple[int, bytes, str]:
        data = self._decode_json(body) or {}
        bridge = self.sessions.get_mutation(data.get("bridgeId"))
        session_id = data.get("sessionId")
        if not isinstance(session_id, str):
            return self._json(400, {"ok": False, "error": "sessionId is required"})
        await bridge.cancel_subagent(session_id)
        return self._json(202, {"ok": True})

    async def _registry_action(self, kind: str, body: bytes) -> tuple[int, bytes, str]:
        data = self._decode_json(body) or {}
        bridge = self.sessions.get_mutation(data.get("bridgeId"))
        action = data.get("action")
        name = data.get("name")

        try:
            if kind == "skills":
                if action == "list":
                    await bridge.refresh_details()
                    return self._json(200, {"ok": True, "skills": bridge.details["skills"]})
                if not isinstance(action, str) or not isinstance(name, str):
                    return self._json(400, {"ok": False, "error": "action and name are required"})
                result = await bridge.set_skill(action, name)
            elif kind == "mcp":
                if action == "list":
                    await bridge.refresh_details()
                    return self._json(200, {"ok": True, "mcpServers": bridge.details["mcpServers"]})
                if action not in ("connect", "disconnect") or not isinstance(name, str):
                    return self._json(400, {"ok": False, "error": "action and name are required"})
                result = await bridge.set_mcp(action, name)
            elif kind == "workflows":
                if action in (None, "list"):
                    await bridge.refresh_details()
                    return self._json(200, {"ok": True, "workflows": bridge.details["workflows"]})
                if action != "run" or not isinstance(name, str):
                    return self._json(400, {"ok": False, "error": "name is required"})
                result = await bridge.run_workflow(name)
            else:
                if action not in ("add", "remove") or not isinstance(name, str):
                    return self._json(400, {"ok": False, "error": "action and path are required"})
                result = await bridge.set_context(action, name, bool(data.get("readOnly")))
        except BridgeError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})

        error = result.get("error") if isinstance(result, dict) else None
        if error:
            return self._json(502, {"ok": False, "error": str(error)})
        return self._json(200, {"ok": True, "result": result})

    async def _prompt(self, body: bytes) -> tuple[int, bytes, str]:
        data = self._decode_json(body)
        if data is None:
            return self._json(400, {"ok": False, "error": "invalid JSON"})
        text = data.get("text")
        if not isinstance(text, str) or not text.strip():
            return self._json(400, {"ok": False, "error": "text is required"})
        try:
            await self.sessions.get_mutation(data.get("bridgeId")).prompt(text)
        except BridgeError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})
        return self._json(202, {"ok": True})

    async def _new_session(self, body: bytes) -> tuple[int, bytes, str]:
        data = self._decode_json(body) if body else {}
        if data is None:
            return self._json(400, {"ok": False, "error": "invalid JSON"})
        bridge = self.sessions.get_mutation(data.get("bridgeId"))
        cwd = data.get("cwd") or bridge.workspace
        if not isinstance(cwd, str):
            return self._json(400, {"ok": False, "error": "cwd must be a string"})
        try:
            await bridge.new_session(os.path.abspath(os.path.expanduser(cwd)))
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
            await self.sessions.get_mutation(data.get("bridgeId")).resolve_permission(
                data["requestId"], option_id
            )
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
            await self.sessions.get_mutation(data.get("bridgeId")).set_config(config_id, value)
        except BridgeError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})
        return self._json(202, {"ok": True})

    async def _serve_websocket(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        headers: dict[str, str],
    ) -> None:
        """Complete the RFC6455 handshake and serve one command channel."""
        key = (headers.get("sec-websocket-key") or "").strip()
        version = (headers.get("sec-websocket-version") or "").strip()
        protocols = [
            item.strip()
            for item in (headers.get("sec-websocket-protocol") or "").split(",")
            if item.strip()
        ]

        if not key:
            await self._write_json(
                writer, 400, {"ok": False, "error": "Sec-WebSocket-Key is required"}
            )
            return
        if version != "13":
            await self._write_json(
                writer, 426, {"ok": False, "error": "unsupported WebSocket version"}
            )
            return
        if self.token and f"token.{self.token}" not in protocols:
            await self._write_json(writer, 403, {"ok": False, "error": "bad token"})
            return

        selected = next(
            (item for item in protocols if item == WS_SUBPROTOCOL or item.startswith("cecli.")),
            WS_SUBPROTOCOL,
        )
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode("ascii")).digest()).decode(
            "ascii"
        )
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n"
            f"Sec-WebSocket-Protocol: {selected}\r\n\r\n"
        )
        writer.write(response.encode("latin-1"))
        await writer.drain()

        client = WsClient()
        self.sessions.ws_clients.add(client)

        writer_task = asyncio.create_task(self._ws_writer(client, writer))
        try:
            await self._ws_reader(client, reader)
        finally:
            self.sessions.ws_clients.discard(client)
            writer_task.cancel()
            await asyncio.gather(writer_task, return_exceptions=True)
            await self._close_writer(writer)

    async def _ws_writer(self, client: WsClient, writer: asyncio.StreamWriter) -> None:
        """The single writer task for one WebSocket peer."""
        try:
            while True:
                kind, payload = await client.queue.get()
                if kind == "event":
                    await self._ws_write(
                        writer,
                        0x1,
                        json.dumps(
                            {"type": "event", "event": payload}, separators=(",", ":")
                        ).encode("utf-8"),
                    )
                elif kind == "response":
                    await self._ws_write(
                        writer,
                        0x1,
                        json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                    )
                else:
                    opcode, data = payload
                    await self._ws_write(writer, opcode, data)
        except (ConnectionError, BrokenPipeError, RuntimeError, asyncio.CancelledError):
            return

    async def _ws_reader(self, client: WsClient, reader: asyncio.StreamReader) -> None:
        """Read frames, handle control frames, and dispatch text messages."""
        fragment_opcode: int | None = None
        fragments = bytearray()

        while True:
            try:
                frame = await self._ws_read_frame(reader)
            except (ConnectionError, asyncio.IncompleteReadError):
                return
            except ValueError:
                client.enqueue_frame(0x8, self._ws_close_payload(1002))
                return

            if frame is None:
                return
            fin, opcode, payload = frame

            if opcode == 0x8:
                client.enqueue_frame(0x8, payload[:125])
                return
            if opcode == 0x9:
                client.enqueue_frame(0xA, payload[:125])
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x0:
                if fragment_opcode is None:
                    client.enqueue_frame(0x8, self._ws_close_payload(1002))
                    return
                fragments.extend(payload)
                if len(fragments) > WS_MAX_MESSAGE:
                    client.enqueue_frame(0x8, self._ws_close_payload(1009))
                    return
                if not fin:
                    continue
                opcode, payload = fragment_opcode, bytes(fragments)
                fragment_opcode, fragments = None, bytearray()
            elif opcode in (0x1, 0x2):
                if not fin:
                    fragment_opcode = opcode
                    fragments = bytearray(payload)
                    continue
            else:
                client.enqueue_frame(0x8, self._ws_close_payload(1003))
                return

            if opcode != 0x1:
                continue
            try:
                message = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                client.enqueue_response({"id": None, "ok": False, "error": "invalid JSON message"})
                continue
            if isinstance(message, dict):
                await self._handle_ws_command(client, message)

    async def _ws_read_frame(self, reader: asyncio.StreamReader) -> tuple[bool, int, bytes] | None:
        """Parse one client frame; raise ValueError on a protocol violation."""
        head = await reader.readexactly(2)
        fin = bool(head[0] & 0x80)
        rsv = head[0] & 0x70
        opcode = head[0] & 0x0F
        masked = bool(head[1] & 0x80)
        length = head[1] & 0x7F

        if rsv or not masked:
            raise ValueError("unmasked frame or reserved bits")
        if length == 126:
            length = struct.unpack("!H", await reader.readexactly(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", await reader.readexactly(8))[0]
        if opcode >= 0x8 and (length > 125 or not fin):
            raise ValueError("bad control frame")
        if length > WS_MAX_MESSAGE:
            raise ValueError("frame too large")

        mask = await reader.readexactly(4)
        payload = bytearray(await reader.readexactly(length))
        for index in range(length):
            payload[index] ^= mask[index % 4]
        return fin, opcode, bytes(payload)

    async def _ws_write(self, writer: asyncio.StreamWriter, opcode: int, payload: bytes) -> None:
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(length)
        elif length < 65536:
            header.append(126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(127)
            header.extend(struct.pack("!Q", length))
        writer.write(bytes(header) + payload)
        await writer.drain()

    @staticmethod
    def _ws_close_payload(code: int) -> bytes:
        return struct.pack("!H", code)

    async def _handle_ws_command(self, client: WsClient, message: dict[str, Any]) -> None:
        """Dispatch one JSON command and queue its response."""
        request_id = message.get("id")
        command = message.get("command") or message.get("type")
        params = message.get("params")
        if not isinstance(params, dict):
            params = message

        try:
            result = await self._dispatch_ws(command, params)
        except BridgeError as err:
            client.enqueue_response(
                {"id": request_id, "ok": False, "error": str(err), "status": err.status}
            )
            return
        except Exception as err:
            client.enqueue_response({"id": request_id, "ok": False, "error": str(err)})
            return

        client.enqueue_response({"id": request_id, "ok": True, "result": result})

    async def _dispatch_ws(self, command: Any, params: dict[str, Any]) -> Any:
        """Map one WebSocket command onto the shared bridge API."""
        bridge_id = params.get("bridgeId")

        if command == "state.get":
            return self.sessions.snapshot(bridge_id)
        if command == "sessions.list":
            return {
                "sessions": self.sessions.list_sessions(),
                "activeBridgeId": self.sessions.active_id,
                "maxSessions": self.sessions.max_sessions,
            }
        if command == "sessions.create":
            bridge = self.sessions.create(params.get("cwd"), params.get("title"))
            return {"bridgeId": bridge.bridge_id}
        if command == "sessions.close":
            await self.sessions.close(bridge_id)
            return {"sessions": self.sessions.list_sessions()}

        bridge = self.sessions.get_mutation(bridge_id)

        if command == "session.prompt":
            await bridge.prompt(str(params.get("text") or ""))
            return {"ok": True}
        if command == "session.cancel":
            await bridge.cancel()
            return {"ok": True}
        if command == "session.new":
            await bridge.new_session(params.get("cwd") or bridge.workspace)
            return {"ok": True}
        if command == "session.config":
            await bridge.set_config(str(params.get("configId")), str(params.get("value")))
            return {"ok": True}
        if command == "session.permission":
            await bridge.resolve_permission(params.get("requestId"), params.get("optionId"))
            return {"ok": True}
        if command == "complete.get":
            return await bridge.complete(str(params.get("text") or ""))
        if command == "history.get":
            return await bridge.history()
        if command == "state.details":
            await bridge.refresh_details()
            return self.sessions.snapshot(bridge.bridge_id)

        if command == "subagents.list":
            await bridge.refresh_details()
            return bridge.snapshot()["subagents"]
        if command == "subagents.message":
            return await bridge.send_subagent_message(
                str(params.get("sessionId")), str(params.get("text") or "")
            )
        if command == "subagents.cancel":
            await bridge.cancel_subagent(str(params.get("sessionId")))
            return {"ok": True}

        if command == "skills.list":
            await bridge.refresh_details()
            return bridge.details["skills"]
        if command == "mcp.list":
            await bridge.refresh_details()
            return bridge.details["mcpServers"]
        if command == "workflows.list":
            await bridge.refresh_details()
            return bridge.details["workflows"]
        if command in ("skills.load", "skills.remove", "skills.include", "skills.exclude"):
            return await bridge.set_skill(command.split(".", 1)[1], str(params.get("name")))
        if command in ("mcp.connect", "mcp.disconnect"):
            return await bridge.set_mcp(command.split(".", 1)[1], str(params.get("name")))
        if command == "workflows.run":
            return await bridge.run_workflow(str(params.get("name")))
        if command in ("context.add", "context.remove"):
            return await bridge.set_context(
                command.split(".", 1)[1],
                str(params.get("path")),
                bool(params.get("readOnly")),
            )

        raise BridgeError(400, f"unknown command: {command}")

    def _serve_index(self) -> tuple[int, bytes, str]:
        """Serve the built index page with the per-run token injected."""
        path = self.root / "static" / "index.html"
        if not path.is_file():
            return self._json(404, {"ok": False, "error": "not found"})
        try:
            page = path.read_text(encoding="utf-8")
        except OSError:
            return self._json(404, {"ok": False, "error": "not found"})
        if self.token:
            snippet = (
                f'<meta name="cecli-token" content="{self.token}">'
                f'<script>window.__CECLI_TOKEN__="{self.token}";</script>'
            )
            page = page.replace("</head>", snippet + "</head>", 1)
        return 200, page.encode("utf-8"), "text/html; charset=utf-8"

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
        for bridge in self.sessions.sessions.values():
            client.enqueue(bridge._status_event())
            if bridge.session_id is not None:
                client.enqueue(bridge._session_event())
            for request_id, permission in bridge._pending_permissions.items():
                client.enqueue(
                    {
                        "type": "permission",
                        "requestId": request_id,
                        "bridgeId": bridge.bridge_id,
                        **permission,
                    }
                )
        client.enqueue(
            {
                "type": "sessions",
                "sessions": self.sessions.list_sessions(),
                "activeBridgeId": self.sessions.active_id,
            }
        )
        self.sessions.sse_clients.add(client)
        try:
            await writer.drain()
        except ConnectionError:
            self.sessions.sse_clients.discard(client)
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
            self.sessions.sse_clients.discard(client)
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

    def _reason(self, status: int) -> str:
        return {
            200: "OK",
            202: "Accepted",
            400: "Bad Request",
            403: "Forbidden",
            404: "Not Found",
            405: "Method Not Allowed",
            409: "Conflict",
            413: "Payload Too Large",
            415: "Unsupported Media Type",
            500: "Internal Server Error",
        }.get(status, "Error")

    async def _close_writer(self, writer: asyncio.StreamWriter) -> None:
        try:
            writer.close()
            await writer.wait_closed()
        except (ConnectionError, RuntimeError):
            pass


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
        token: str = "",
        max_sessions: int = MAX_SESSIONS,
    ) -> None:
        self.host = host
        self.port = port
        self.workspace = workspace
        self.cecli = cecli
        self.extra_args = extra_args
        self.open_browser = open_browser
        self.token = token
        self.max_sessions = max_sessions


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
    parser.add_argument(
        "--token",
        default=os.environ.get("CECLI_DESKTOP_TOKEN") or secrets.token_urlsafe(24),
        help="WebSocket bearer token (generated per run by default)",
    )
    parser.add_argument(
        "--max-sessions",
        type=int,
        default=MAX_SESSIONS,
        help="maximum number of concurrent parent sessions",
    )
    args = parser.parse_args(argv)

    suffix = ".exe" if os.name == "nt" else ""
    sibling = Path(sys.executable).with_name(f"cecli{suffix}")
    cecli = (
        args.cecli
        or os.environ.get("CECLI_BIN")
        or (str(sibling) if sibling.is_file() else None)
        or shutil.which("cecli")
        or "cecli"
    )
    workspace = os.path.abspath(os.path.expanduser(args.workspace))
    return ServerConfig(
        args.host,
        args.port,
        workspace,
        cecli,
        extra_args,
        args.open,
        args.token,
        max(1, args.max_sessions),
    )


async def run_server(config: ServerConfig) -> None:
    """Bind the HTTP server, spawn the default session and serve until signalled."""
    root = Path(__file__).resolve().parent
    manager = SessionManager(
        config.cecli,
        config.extra_args,
        config.workspace,
        max_sessions=config.max_sessions,
        token=config.token,
    )
    app = DesktopServer(manager, root, config.host, token=config.token)
    server = await asyncio.start_server(app.handle_connection, config.host, config.port)
    port = server.sockets[0].getsockname()[1] if server.sockets else config.port
    app.port = port
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

    manager.create(config.workspace, "primary")
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
        await manager.shutdown()


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


def _sanitize_extra_args(args: list[str]) -> list[str]:
    """Drop ``--server-config``: its fixed WS port breaks multi-child runs."""
    cleaned: list[str] = []
    skip_next = False

    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg == "--server-config":
            skip_next = True
            continue
        if arg.startswith("--server-config="):
            continue
        cleaned.append(arg)

    return cleaned


def _signal_process(process: asyncio.subprocess.Process, hard: bool = False) -> None:
    """Signal the child's process group on POSIX, or the child elsewhere."""
    if os.name == "posix":
        sig = signal.SIGKILL if hard else signal.SIGTERM
        try:
            os.killpg(process.pid, sig)
            return
        except ProcessLookupError:
            raise

    if hard:
        process.kill()
    else:
        process.terminate()


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
