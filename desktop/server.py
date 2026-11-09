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

try:
    from .browser_bridge import BrowserBridge, BrowserError
    from .cli_registry import CliRegistry, error_code
    from .conf_store import ConfStore
    from .onboarding_api import OnboardingError, OnboardingService
    from .parent_death import arm_parent_death, child_parent_death_hook
    from .terminal import TerminalError, TerminalManager, replay_offsets
except ImportError:  # pragma: no cover - the server also runs as a script
    from browser_bridge import BrowserBridge, BrowserError
    from cli_registry import CliRegistry, error_code
    from conf_store import ConfStore
    from onboarding_api import OnboardingError, OnboardingService
    from parent_death import arm_parent_death, child_parent_death_hook
    from terminal import TerminalError, TerminalManager, replay_offsets

MAX_BODY = 1024 * 1024
DIRECTORY_LIMIT = 50
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
            "hooks": [],
            "mcpServers": [],
            "workflows": [],
            "contextFiles": [],
            "usage": {},
            "cwd": "",
            "gitBranch": "",
        }
        self.extra_sinks: list[Any] = []
        self.details_supported: bool | None = None
        self._details_task: asyncio.Task[Any] | None = None
        self._poll_task: asyncio.Task[Any] | None = None
        self.available_commands: list[dict[str, Any]] = []
        self.shared_browser: dict[str, Any] | None = None
        self.background_event_sink = None
        self._browser_announced = False

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
            "cwd": self.details.get("cwd", ""),
            "gitBranch": self.details.get("gitBranch", ""),
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
            "hooks": self.details.get("hooks", []),
            "workflows": self.details.get("workflows", []),
            "contextFiles": self.details.get("contextFiles", []),
            "usage": self.details.get("usage", {}),
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

    async def announce_browser(self, endpoint: dict[str, Any]) -> None:
        """Tell the child which live browser browser-harness should use."""
        identity = (endpoint.get("cdpUrl"), endpoint.get("port"))
        if self._browser_announced and self.shared_browser is not None:
            current = (self.shared_browser.get("cdpUrl"), self.shared_browser.get("port"))
            if current == identity:
                self.shared_browser = dict(endpoint)
                return

        self._browser_announced = False
        self.shared_browser = dict(endpoint)
        if self.status != "ready" or self.session_id is None:
            return

        payload = {"sessionId": self.session_id, **endpoint}
        try:
            await self._request("cecli/browser", payload, timeout=10.0)
            self._browser_announced = True
        except (AcpError, asyncio.TimeoutError):
            return

    async def set_skill(self, action: str, name: str) -> dict[str, Any]:
        """Load, remove, include or exclude one skill."""
        return await self.call_extension("cecli/skill", {"action": action, "name": name})

    async def set_mcp(self, action: str, name: str) -> dict[str, Any]:
        """Connect or disconnect one MCP server."""
        return await self.call_extension("cecli/mcp", {"action": action, "name": name})

    async def set_hook(self, action: str, name: str) -> dict[str, Any]:
        """Enable (``load``) or disable (``remove``) one configured hook."""
        return await self.call_extension("cecli/hook", {"action": action, "name": name})

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
        diffs = result.get("diffs")
        messages = result.get("messages")
        subagents = result.get("subagents")
        return {
            "messages": messages if isinstance(messages, list) else [],
            "subagents": subagents if isinstance(subagents, list) else [],
            "diffs": diffs if isinstance(diffs, list) else [],
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

        parent_death_hook = child_parent_death_hook()
        if parent_death_hook is not None:
            spawn_kwargs["preexec_fn"] = parent_death_hook

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
            if self.shared_browser is not None:
                asyncio.create_task(self.announce_browser(self.shared_browser))
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
        method = message.get("method")
        if method == "cecli/background/event":
            sink = self.background_event_sink
            if sink is not None:
                try:
                    sink(message.get("params") or {})
                except Exception:
                    pass
            return

        if method != "session/update":
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
        for key in ("skills", "mcpServers", "hooks", "workflows", "contextFiles"):
            value = result.get(key)
            if isinstance(value, list):
                self.details[key] = value
        if isinstance(result.get("usage"), dict):
            self.details["usage"] = result["usage"]
        if isinstance(result.get("cwd"), str):
            self.details["cwd"] = result["cwd"]
        if isinstance(result.get("gitBranch"), str):
            self.details["gitBranch"] = result["gitBranch"]
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
        self.browser_endpoint: dict[str, Any] | None = None
        self._counter = 0
        self.background_event_sink = None

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
        bridge.shared_browser = self.browser_endpoint
        if self.background_event_sink is not None:
            bridge.background_event_sink = lambda params, bid=bridge_id: self.background_event_sink(
                bid, params
            )
        bridge.extra_sinks.append(self.publish)
        self.sessions[bridge_id] = bridge
        self.order.append(bridge_id)
        if self.active_id is None:
            self.active_id = bridge_id
        asyncio.create_task(bridge.start())
        self.publish_sessions()
        return bridge

    async def announce_browser(self, endpoint: dict[str, Any]) -> None:
        """Share one browser endpoint with every current and future session."""
        self.browser_endpoint = dict(endpoint)
        bridges = list(self.sessions.values())
        await asyncio.gather(
            *(bridge.announce_browser(endpoint) for bridge in bridges),
            return_exceptions=True,
        )

    def allow_root(self, path: str) -> None:
        """Let an explicitly configured workspace spawn its session."""
        real = os.path.realpath(os.path.abspath(os.path.expanduser(str(path))))
        if real not in self.allowed_roots:
            self.allowed_roots.append(real)

    def find_by_workspace(self, path: str) -> AcpBridge | None:
        """The live session whose workspace is exactly ``path``, if any."""
        real = os.path.realpath(os.path.abspath(os.path.expanduser(str(path))))
        for bridge in self.sessions.values():
            if os.path.realpath(bridge.workspace) == real:
                return bridge
        return None

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
        browser: BrowserBridge | None = None,
        conf: ConfStore | None = None,
        onboarding: OnboardingService | None = None,
        terminal: TerminalManager | None = None,
        cli_enabled: bool = True,
    ) -> None:
        self.sessions = sessions
        self.token = token
        self.root = root
        self.host = host
        self.browser = browser
        self.conf = conf
        self.onboarding = onboarding
        self.terminal = terminal or TerminalManager()
        self.cli_enabled = bool(cli_enabled) and is_loopback_host(host)
        self.cli = CliRegistry(enabled=self.cli_enabled)
        if self.sessions is not None:
            self.sessions.background_event_sink = self._on_background_event
        self._browser_sync_task: asyncio.Task[Any] | None = None

    @property
    def bridge(self) -> AcpBridge:
        """The default parent session, kept for single-session callers."""
        return self.sessions.get_default()

    def _on_background_event(self, bridge_id: str, params: dict[str, Any]) -> None:
        """Fold one child background notification into the CLI mirror (sync)."""
        if not self.cli_enabled:
            return
        self.cli.apply_event(bridge_id, params)

        event = params.get("event")
        if not event or event == "output" or self.sessions is None:
            return

        publish = getattr(self.sessions, "publish", None)
        if publish is None:
            return

        key = params.get("key")
        publish(
            {
                "type": "cli",
                "bridgeId": bridge_id,
                "event": event,
                "cliId": key,
                "key": key,
                "state": params.get("state"),
                "lastPrompt": params.get("prompt"),
                "exitCode": params.get("code"),
                "endedAt": params.get("endedAt"),
                "signal": params.get("signal"),
                "entry": params.get("command"),
            }
        )

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

                if method == "GET" and path == "/api/browser/stream":
                    await self._serve_browser_stream(reader, writer)
                    return
                if method == "GET" and path == "/api/events":
                    await self._serve_events(reader, writer)
                    return
                if method == "GET" and path == "/api/terminal/ws":
                    await self._serve_terminal_websocket(reader, writer, headers, query)
                    return
                if method == "GET" and path == "/api/terminal/stream":
                    await self._serve_terminal_stream(reader, writer, query)
                    return
                if method == "GET" and path == "/api/cli/stream":
                    await self._serve_cli_stream(reader, writer, query, headers)
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
            bridge = next(iter(self.sessions.sessions.values()), None)
            return self._json(
                200,
                {
                    "ok": True,
                    "status": bridge.status if bridge is not None else "idle",
                    "sessions": len(self.sessions.sessions),
                },
            )

        if method == "GET" and path == "/api/browser/state":
            try:
                state = self._browser_bridge().snapshot()
            except BrowserError as err:
                return self._json(err.status, {"ok": False, "error": str(err)})
            return self._json(200, {"ok": True, **state})

        if method == "GET" and path == "/api/state":
            bridge = self.sessions.get(self._query_bridge(query))
            snapshot = self.sessions.snapshot(bridge.bridge_id)
            snapshot["terminal"] = self.terminal.state(bridge.bridge_id)
            if self.cli_enabled:
                await self.cli.ensure_state(bridge)
            snapshot["cliPane"] = self.cli.state_payload(bridge.bridge_id)
            return self._json(200, snapshot)

        if method == "GET" and path == "/api/terminal/state":
            try:
                bridge = self.sessions.get((query.get("bridgeId") or [None])[0])
            except BridgeError as err:
                return self._json(err.status, {"ok": False, "error": str(err)})
            return self._json(200, {"ok": True, "terminal": self.terminal.state(bridge.bridge_id)})

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

        if method == "GET" and path == "/api/workspaces":
            return self._list_workspaces()

        if method == "GET" and path == "/api/fs/dirs":
            return self._list_directories((query.get("path") or [""])[0])

        if method == "GET" and path == "/api/onboarding/status":
            return self._onboarding_call(lambda: self.onboarding.status())

        if method == "GET" and path == "/api/onboarding/providers":
            slug = (query.get("slug") or [None])[0]
            return self._onboarding_call(lambda: self.onboarding.providers(slug))

        if method == "GET" and path == "/api/onboarding/copilot":
            return self._onboarding_call(self.onboarding.copilot)

        if method == "DELETE" and path == "/api/workspaces":
            return await self._remove_workspace(body)

        if method == "GET" and path == "/api/cli/state":
            if not self.cli_enabled:
                return self._json(403, {"ok": False, "error": "cli pane disabled"})
            try:
                bridge = self.sessions.get(self._query_bridge(query))
            except BridgeError as err:
                return self._json(err.status, {"ok": False, "error": str(err)})
            await self.cli.ensure_state(bridge)
            mirror = self.cli.mirror(bridge.bridge_id)
            background = [
                {**entry, "cliId": entry.get("cliId") or entry.get("key")}
                for entry in mirror.entries.values()
            ]
            return self._json(
                200,
                {
                    "ok": True,
                    "bridgeId": bridge.bridge_id,
                    "workspace": bridge.workspace,
                    "terminals": self.terminal.terminals(bridge.bridge_id),
                    "background": background,
                    "cliPane": self.cli.state_payload(bridge.bridge_id),
                },
            )

        if method != "POST":
            return self._json(404, {"ok": False, "error": "not found"})

        if path.startswith("/api/browser/"):
            suffix = path[len("/api/browser/") :]
            if suffix == "start":
                return await self._browser_start(body)
            if suffix == "open":
                return await self._browser_open(body)
            if suffix == "action":
                return await self._browser_action(body)
            if suffix == "viewport":
                return await self._browser_viewport(body)
            if suffix == "input":
                return await self._browser_input(body)
            if suffix == "tab/close":
                return await self._browser_close_tab(body)
            if suffix == "tab/new":
                return await self._browser_new_tab(body)
            if suffix == "tab":
                return await self._browser_tab(body)
        if path == "/api/background":
            return await self._background(body)
        if path.startswith("/api/cli/"):
            return await self._cli_route(path[len("/api/cli/") :], body)
        if path.startswith("/api/terminal/"):
            return await self._terminal_route(path[len("/api/terminal/") :], body)

        if path == "/api/workspaces":
            return await self._add_workspace(body)
        if path == "/api/workspaces/update":
            return await self._update_workspace(body)
        if path == "/api/onboarding/config":
            return await self._onboarding_config(body)
        if path == "/api/onboarding/copilot/login":
            return await self._onboarding_copilot_login()
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
        if path in ("/api/skills", "/api/mcp", "/api/hooks", "/api/workflows", "/api/context"):
            return await self._registry_action(path.rsplit("/", 1)[-1], body)

        return self._json(404, {"ok": False, "error": "not found"})

    def _list_workspaces(self) -> tuple[int, bytes, str]:
        """Configured folders with validity and their live session ids."""
        if self.conf is None:
            return self._json(503, {"ok": False, "error": "workspace config is unavailable"})
        workspaces = []
        for entry in self.conf.workspace_states():
            bridge = self.sessions.find_by_workspace(entry["path"]) if self.sessions else None
            entry = {**entry, "bridgeId": bridge.bridge_id if bridge else None}
            workspaces.append(entry)
        return self._json(
            200,
            {
                "ok": True,
                "workspaces": workspaces,
                "configPath": str(self.conf.desktop_path),
                "desktopConfigPath": str(self.conf.desktop_path),
                "globalConfigPath": str(self.conf.global_path),
                "projectConfigPath": str(self.conf.project_path),
            },
        )

    def _list_directories(self, raw_path: str) -> tuple[int, bytes, str]:
        """Return matching child directories for the workspace path autocomplete."""
        expanded = os.path.expandvars(os.path.expanduser(raw_path or ""))
        if not expanded:
            expanded = os.path.expanduser("~")
        elif not os.path.isabs(expanded):
            base = getattr(self.sessions, "default_workspace", os.getcwd())
            expanded = os.path.join(base, expanded)

        trailing = expanded.endswith((os.sep, os.altsep) if os.altsep else (os.sep,))
        parent = expanded if trailing else os.path.dirname(expanded)
        prefix = "" if trailing else os.path.basename(expanded)
        if not parent:
            parent = os.sep

        try:
            with os.scandir(parent) as iterator:
                candidates = []
                for entry in iterator:
                    try:
                        if not entry.is_dir():
                            continue
                    except OSError:
                        continue
                    if entry.name.startswith(".") and not prefix.startswith("."):
                        continue
                    candidates.append(entry)
        except OSError:
            return self._json(
                200,
                {
                    "ok": True,
                    "parent": parent,
                    "prefix": prefix,
                    "separator": os.sep,
                    "entries": [],
                    "truncated": False,
                },
            )

        candidates.sort(key=lambda entry: entry.name.lower())
        needle = prefix.lower()
        entries = []
        truncated = False
        for entry in candidates:
            if needle and not entry.name.lower().startswith(needle):
                continue
            if len(entries) >= DIRECTORY_LIMIT:
                truncated = True
                break
            entries.append({"name": entry.name, "path": os.path.join(parent, entry.name)})

        return self._json(
            200,
            {
                "ok": True,
                "parent": parent,
                "prefix": prefix,
                "separator": os.sep,
                "entries": entries,
                "truncated": truncated,
            },
        )

    async def _add_workspace(self, body: bytes) -> tuple[int, bytes, str]:
        """Validate and persist a folder, then start its session."""
        data = self._decode_json(body)
        if data is None:
            return self._json(400, {"ok": False, "error": "invalid JSON"})
        if self.conf is None:
            return self._json(503, {"ok": False, "error": "workspace config is unavailable"})
        path = data.get("path")
        name = data.get("name")
        enable = data.get("enable_on_startup")
        if not isinstance(path, str) or not path.strip():
            return self._json(400, {"ok": False, "error": "path is required"})
        if name is not None and not isinstance(name, str):
            return self._json(400, {"ok": False, "error": "name must be a string"})
        if enable is not None and not isinstance(enable, bool):
            return self._json(400, {"ok": False, "error": "enable_on_startup must be a boolean"})

        try:
            entry = self.conf.add_workspace(path, name, enable_on_startup=enable)
        except ValueError as err:
            return self._json(400, {"ok": False, "error": str(err)})
        except OSError as err:
            return self._json(500, {"ok": False, "error": f"Failed to save workspace: {err}"})

        bridge = self.sessions.find_by_workspace(entry["path"])
        if bridge is None:
            self.sessions.allow_root(entry["path"])
            try:
                bridge = self.sessions.create(entry["path"], entry["name"])
            except BridgeError as err:
                self.conf.remove_workspace(entry["path"])
                return self._json(err.status, {"ok": False, "error": str(err)})

        return self._json(
            201,
            {
                "ok": True,
                "workspace": entry,
                "bridgeId": bridge.bridge_id,
                "sessions": self.sessions.list_sessions(),
            },
        )

    async def _update_workspace(self, body: bytes) -> tuple[int, bytes, str]:
        """Rename a folder or change whether it starts with the app."""
        data = self._decode_json(body)
        if data is None:
            return self._json(400, {"ok": False, "error": "invalid JSON"})
        if self.conf is None:
            return self._json(503, {"ok": False, "error": "workspace config is unavailable"})
        path = data.get("path")
        name = data.get("name")
        enable = data.get("enable_on_startup")
        if not isinstance(path, str) or not path.strip():
            return self._json(400, {"ok": False, "error": "path is required"})
        if name is not None and not isinstance(name, str):
            return self._json(400, {"ok": False, "error": "name must be a string"})
        if enable is not None and not isinstance(enable, bool):
            return self._json(400, {"ok": False, "error": "enable_on_startup must be a boolean"})

        try:
            entry = self.conf.update_workspace(path, name, enable)
        except ValueError as err:
            status = 404 if "Unknown workspace" in str(err) else 400
            return self._json(status, {"ok": False, "error": str(err)})
        except OSError as err:
            return self._json(500, {"ok": False, "error": f"Failed to save workspace: {err}"})

        bridge = self.sessions.find_by_workspace(entry["path"])
        if bridge is not None:
            bridge.title = entry["name"]
            self.sessions.publish_sessions()
        return self._json(
            200,
            {
                "ok": True,
                "workspace": entry,
                "bridgeId": bridge.bridge_id if bridge else None,
                "sessions": self.sessions.list_sessions(),
            },
        )

    async def _remove_workspace(self, body: bytes) -> tuple[int, bytes, str]:
        """Persist removal and stop the folder's live session, if any."""
        data = self._decode_json(body)
        if data is None:
            return self._json(400, {"ok": False, "error": "invalid JSON"})
        if self.conf is None:
            return self._json(503, {"ok": False, "error": "workspace config is unavailable"})
        path = data.get("path")
        if not isinstance(path, str) or not path.strip():
            return self._json(400, {"ok": False, "error": "path is required"})

        bridge = self.sessions.find_by_workspace(path)
        if bridge is not None and bridge.busy:
            return self._json(409, {"ok": False, "error": "Finish or stop the current turn first"})

        if not self.conf.remove_workspace(path):
            return self._json(404, {"ok": False, "error": "Unknown workspace"})

        closed = False
        if bridge is not None:
            if bridge.primary:
                others = [item for item in self.sessions.sessions.values() if item is not bridge]
                if others:
                    others[0].primary = True
                    bridge.primary = False
                else:
                    await bridge.shutdown()
                    self.sessions.sessions.pop(bridge.bridge_id, None)
                    if bridge.bridge_id in self.sessions.order:
                        self.sessions.order.remove(bridge.bridge_id)
                    if self.sessions.active_id == bridge.bridge_id:
                        self.sessions.active_id = None
                    self.sessions.publish_sessions()
                    closed = True
            if not closed:
                await self.sessions.close(bridge.bridge_id)
                closed = True
                await self.terminal.close(bridge.bridge_id)
        return self._json(
            200,
            {
                "ok": True,
                "closed": closed,
                "sessions": self.sessions.list_sessions(),
            },
        )

    def _onboarding_call(self, callback: Any) -> tuple[int, bytes, str]:
        """Run one synchronous onboarding query, mapping failures to statuses."""
        if self.onboarding is None:
            return self._json(503, {"ok": False, "error": "onboarding is unavailable"})
        try:
            return self._json(200, callback())
        except OnboardingError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})

    async def _onboarding_config(self, body: bytes) -> tuple[int, bytes, str]:
        """Persist provider keys and the default model from the GUI wizard."""
        data = self._decode_json(body)
        if data is None:
            return self._json(400, {"ok": False, "error": "invalid JSON"})
        if self.onboarding is None:
            return self._json(503, {"ok": False, "error": "onboarding is unavailable"})
        try:
            return self._json(200, await self.onboarding.configure(data))
        except OnboardingError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})

    async def _onboarding_copilot_login(self) -> tuple[int, bytes, str]:
        """Start or report the GitHub Copilot device flow."""
        if self.onboarding is None:
            return self._json(503, {"ok": False, "error": "onboarding is unavailable"})
        try:
            return self._json(200, await self.onboarding.copilot_login())
        except OnboardingError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})

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
        bridge = self.sessions.get(data.get("bridgeId"))
        try:
            await self.sessions.close(data.get("bridgeId"))
            await self.terminal.close(bridge.bridge_id)
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
            elif kind == "hooks":
                if action in (None, "list"):
                    await bridge.refresh_details()
                    return self._json(200, {"ok": True, "hooks": bridge.details["hooks"]})
                if action not in ("load", "remove", "enable", "disable") or not isinstance(
                    name, str
                ):
                    return self._json(400, {"ok": False, "error": "action and name are required"})
                await bridge.set_hook(action, name)
                return self._json(200, {"ok": True, "hooks": bridge.details["hooks"]})
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

    def _browser_bridge(self) -> BrowserBridge:
        """The configured browser mirror, or an API-level failure."""
        if self.browser is None:
            raise BrowserError("the browser bridge is not configured")
        return self.browser

    def _announce_browser(self, state: dict[str, Any]) -> None:
        """Tell every session which live browser browser-harness should use."""
        announce = getattr(self.sessions, "announce_browser", None)
        if announce is None or not state.get("running") or not state.get("cdpUrl"):
            return

        self._browser_sync_task = asyncio.create_task(
            announce(
                {
                    "cdpUrl": state["cdpUrl"],
                    "port": state.get("port"),
                    "url": state.get("url", ""),
                }
            )
        )

    async def _browser_start(self, body: bytes) -> tuple[int, bytes, str]:
        data = self._decode_json(body)
        if data is None:
            return self._json(400, {"ok": False, "error": "invalid JSON"})
        try:
            state = await self._browser_bridge().start()
        except BrowserError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})

        self._announce_browser(state)
        return self._json(202, {"ok": True, **state})

    async def _browser_open(self, body: bytes) -> tuple[int, bytes, str]:
        data = self._decode_json(body)
        if data is None:
            return self._json(400, {"ok": False, "error": "invalid JSON"})
        url = data.get("url")
        if not isinstance(url, str) or not url.strip():
            return self._json(400, {"ok": False, "error": "url is required"})
        try:
            state = await self._browser_bridge().open(url)
        except BrowserError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})
        self._announce_browser(state)
        return self._json(200, {"ok": True, **state})

    async def _browser_action(self, body: bytes) -> tuple[int, bytes, str]:
        data = self._decode_json(body)
        if data is None:
            return self._json(400, {"ok": False, "error": "invalid JSON"})
        action = data.get("action")
        if not isinstance(action, str) or not action.strip():
            return self._json(400, {"ok": False, "error": "action is required"})
        try:
            await self._browser_bridge().action(action)
        except BrowserError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})
        return self._json(202, {"ok": True})

    async def _browser_viewport(self, body: bytes) -> tuple[int, bytes, str]:
        data = self._decode_json(body)
        if data is None:
            return self._json(400, {"ok": False, "error": "invalid JSON"})
        width = data.get("width")
        height = data.get("height")
        if width is None or height is None:
            return self._json(400, {"ok": False, "error": "width and height are required"})
        try:
            await self._browser_bridge().set_viewport(width, height, data.get("dpr", 1.0))
        except BrowserError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})
        return self._json(202, {"ok": True})

    async def _browser_input(self, body: bytes) -> tuple[int, bytes, str]:
        data = self._decode_json(body)
        if data is None:
            return self._json(400, {"ok": False, "error": "invalid JSON"})
        event = data.get("event")
        if not isinstance(event, dict):
            return self._json(400, {"ok": False, "error": "event is required"})
        try:
            await self._browser_bridge().send_input(event)
        except BrowserError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})
        return self._json(202, {"ok": True})

    async def _browser_close_tab(self, body: bytes) -> tuple[int, bytes, str]:
        data = self._decode_json(body)
        if data is None:
            return self._json(400, {"ok": False, "error": "invalid JSON"})
        tab_id = data.get("tabId") or data.get("id")
        if not isinstance(tab_id, str) or not tab_id.strip():
            return self._json(400, {"ok": False, "error": "tabId is required"})
        try:
            state = await self._browser_bridge().close_tab(tab_id)
        except BrowserError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})
        self._announce_browser(state)
        return self._json(202, {"ok": True, **state})

    async def _browser_new_tab(self, body: bytes) -> tuple[int, bytes, str]:
        data = self._decode_json(body) if body else {}
        if data is None:
            return self._json(400, {"ok": False, "error": "invalid JSON"})
        url = data.get("url")
        if url is not None and not isinstance(url, str):
            return self._json(400, {"ok": False, "error": "url must be a string"})
        try:
            state = await self._browser_bridge().new_tab(url or None)
        except BrowserError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})
        self._announce_browser(state)
        return self._json(202, {"ok": True, **state})

    async def _browser_tab(self, body: bytes) -> tuple[int, bytes, str]:
        data = self._decode_json(body)
        if data is None:
            return self._json(400, {"ok": False, "error": "invalid JSON"})
        tab_id = data.get("tabId") or data.get("id")
        if not isinstance(tab_id, str) or not tab_id.strip():
            return self._json(400, {"ok": False, "error": "tabId is required"})
        try:
            state = await self._browser_bridge().select_tab(tab_id)
        except BrowserError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})
        self._announce_browser(state)
        return self._json(202, {"ok": True, **state})

    async def _cli_route(self, suffix: str, body: bytes) -> tuple[int, bytes, str]:
        """Dispatch one POST /api/cli/* control call."""
        if not self.cli_enabled:
            return self._json(403, {"ok": False, "error": "cli pane disabled"})

        actions = {"state", "input", "resize", "stop", "close", "stop_all"}
        if suffix not in actions:
            return self._json(404, {"ok": False, "error": "not found"})

        data = self._body_json(body)
        if data is None:
            return self._json(400, {"ok": False, "error": "invalid JSON"})

        bridge_id = data.get("bridgeId")
        if not isinstance(bridge_id, str) or not bridge_id:
            return self._json(400, {"ok": False, "error": "bridgeId is required"})

        try:
            bridge = self.sessions.get(bridge_id)
        except BridgeError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})

        params = {key: value for key, value in data.items() if key != "bridgeId"}
        if "cliId" in params and "key" not in params:
            params["key"] = params.pop("cliId")
        if isinstance(params.get("key"), str):
            params["key"] = _normalize_cli_key(bridge.bridge_id, params["key"])
        terminal_id = params.get("key")
        if isinstance(terminal_id, str) and terminal_id.startswith("term:"):
            return await self._cli_terminal(suffix, bridge.bridge_id, terminal_id, params)
        try:
            result = await self.cli.call(bridge, suffix, params)
        except BridgeError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})

        code = error_code(result)
        if code is not None:
            return self._json(code, {"ok": False, **result})
        if "ok" in result:
            return self._json(200, result)
        return self._json(200, {"ok": True, **result})

    async def _serve_cli_stream(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        query: dict[str, list[str]],
        headers: dict[str, str] | None = None,
    ) -> None:
        """SSE replay + live background output using FIX A offsets.

        Lifecycle events are emitted as first-class ``state`` frames; unknown
        event names fall back to ``type: "event"`` for client compatibility.
        """
        if not self.cli_enabled:
            await self._write_json(writer, 403, {"ok": False, "error": "cli pane disabled"})
            return

        bridge_id = _optional_str((query.get("bridgeId") or [None])[0])
        if not bridge_id:
            await self._write_json(writer, 400, {"ok": False, "error": "bridgeId is required"})
            return
        try:
            bridge = self.sessions.get(bridge_id)
        except BridgeError as err:
            await self._write_json(writer, err.status, {"ok": False, "error": str(err)})
            return
        key = _normalize_cli_key(
            bridge_id,
            _optional_str((query.get("cliId") or [None])[0])
            or _optional_str((query.get("key") or [None])[0]),
        )
        since = _optional_int(_optional_str((query.get("since") or [None])[0]))
        if since is None and headers:
            since = _optional_int(headers.get("last-event-id"))
        mirror = self.cli.mirror(bridge.bridge_id)
        await self.cli.ensure_state(bridge)

        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/event-stream\r\n"
            b"Cache-Control: no-cache\r\n"
            b"Connection: keep-alive\r\n"
            b"X-Accel-Buffering: no\r\n\r\n"
            b"retry: 2000\n\n"
        )

        queue = mirror.subscribe()
        last_seq = 0
        try:
            if key:
                snap = mirror.snapshot(key, since)
                last_seq = snap["seq"]
                if snap["reset"]:
                    writer.write(
                        _sse_payload(
                            {
                                "type": "reset",
                                "cliId": key,
                                "seq": snap["startSeq"],
                                "startSeq": snap["startSeq"],
                            }
                        )
                    )
                first = snap["startSeq"]
                if not snap["reset"] and since is not None:
                    first = max(since, snap["startSeq"])
                ready = {
                    "type": "ready",
                    "cliId": key,
                    "kind": "background",
                    "state": snap["state"],
                    "seq": first,
                    "startSeq": snap["startSeq"],
                }
                writer.write(_sse_payload(ready))
                if snap["data"]:
                    output = {
                        "type": "output",
                        "cliId": key,
                        "seq": snap["seq"],
                        "data": base64.b64encode(snap["data"]).decode("ascii"),
                    }
                    writer.write(_sse_payload(output, snap["seq"]))
            else:
                writer.write(_sse_payload({"type": "ready", "seq": 0, "startSeq": 0}))
            await writer.drain()

            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    writer.write(b": ping\n\n")
                    await writer.drain()
                    continue

                if item.get("type") == "reset":
                    if key:
                        snap = mirror.snapshot(key, None)
                        last_seq = snap["seq"]
                        reset = {
                            "type": "reset",
                            "cliId": key,
                            "seq": snap["startSeq"],
                            "startSeq": snap["startSeq"],
                        }
                        writer.write(_sse_payload(reset))
                        if snap["data"]:
                            output = {
                                "type": "output",
                                "cliId": key,
                                "seq": snap["seq"],
                                "data": base64.b64encode(snap["data"]).decode("ascii"),
                            }
                            writer.write(_sse_payload(output, snap["seq"]))
                    await writer.drain()
                    continue

                params = item.get("params") or {}
                event = params.get("event")
                event_key = params.get("key")
                if key and event_key != key:
                    continue
                event_id = None
                if event == "output":
                    frame = {
                        "type": "output",
                        "cliId": event_key,
                        "seq": params.get("seq"),
                        "data": params.get("data"),
                    }
                    event_id = _optional_int(params.get("seq"))
                    if event_id is not None:
                        last_seq = event_id
                elif event in ("exited", "closed"):
                    frame = {
                        "type": "exit",
                        "cliId": event_key,
                        "closed": event == "closed",
                        "code": params.get("code"),
                        "state": params.get("state"),
                        "endedAt": params.get("endedAt"),
                    }
                    event_id = last_seq
                    if event == "closed":
                        writer.write(_sse_payload(frame, event_id))
                        await writer.drain()
                        return
                elif event == "needs_input":
                    frame = {
                        "type": "state",
                        "cliId": event_key,
                        "key": event_key,
                        "state": "needs_input",
                        "needsInput": True,
                        "lastPrompt": params.get("prompt"),
                        "entry": params.get("command"),
                    }
                elif event in ("started", "state"):
                    command = params.get("command")
                    state = params.get("state")
                    if not state and isinstance(command, dict):
                        state = command.get("state")
                    frame = {
                        "type": "state",
                        "cliId": event_key,
                        "key": event_key,
                        "state": state,
                        "entry": command,
                    }
                else:
                    frame = {
                        "type": "event",
                        "cliId": event_key,
                        "key": event_key,
                        "event": event,
                        "state": params.get("state"),
                        "entry": params.get("command"),
                    }
                writer.write(_sse_payload(frame, event_id))
                await writer.drain()
        except (ConnectionError, BrokenPipeError, RuntimeError):
            return
        finally:
            mirror.unsubscribe(queue)
            await self._close_writer(writer)

    async def _background(self, body: bytes) -> tuple[int, bytes, str]:
        data = self._decode_json(body)
        if data is None:
            return self._json(400, {"ok": False, "error": "invalid JSON"})
        action = data.get("action")
        if action not in ("list", "output"):
            return self._json(400, {"ok": False, "error": "action must be list or output"})
        key = data.get("key")
        if action == "output" and not isinstance(key, str):
            return self._json(400, {"ok": False, "error": "key is required"})
        params: dict[str, Any] = {"action": action}
        if isinstance(key, str):
            params["key"] = key
        try:
            bridge = self.sessions.get(data.get("bridgeId"))
            result = await bridge.call_extension("cecli/background", params)
        except BridgeError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})
        if action == "list":
            commands = result.get("commands")
            return self._json(
                200,
                {"ok": True, "commands": commands if isinstance(commands, list) else []},
            )
        output = result.get("output")
        command = result.get("command")
        return self._json(
            200,
            {
                "ok": True,
                "output": output if isinstance(output, str) else "",
                "command": command if isinstance(command, dict) else {},
            },
        )

    async def _serve_browser_stream(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            browser = self._browser_bridge()
        except BrowserError as err:
            await self._write_json(writer, err.status, {"ok": False, "error": str(err)})
            return

        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/event-stream\r\n"
            b"Cache-Control: no-cache\r\n"
            b"Connection: keep-alive\r\n"
            b"X-Accel-Buffering: no\r\n\r\n"
            b"retry: 2000\n\n"
        )
        queue = browser.subscribe()
        try:
            await writer.drain()
        except (ConnectionError, RuntimeError):
            browser.unsubscribe(queue)
            return
        except asyncio.CancelledError:
            browser.unsubscribe(queue)
            raise

        writer_task = asyncio.create_task(self._browser_stream_writer(browser, queue, writer))
        read_task = asyncio.create_task(self._wait_for_disconnect(reader))
        try:
            done, pending = await asyncio.wait(
                {writer_task, read_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        finally:
            browser.unsubscribe(queue)
            await self._close_writer(writer)

    async def _browser_stream_writer(
        self,
        browser: BrowserBridge,
        queue: asyncio.Queue[dict[str, Any]],
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            state = {"type": "state", "state": browser.snapshot()}
            writer.write(f"data: {json.dumps(state, separators=(',', ':'))}\n\n".encode("utf-8"))
            await writer.drain()
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    writer.write(b": ping\n\n")
                    await writer.drain()
                    continue
                payload = (
                    f"data: {json.dumps(event, separators=(',', ':'), ensure_ascii=False)}\n\n"
                )
                writer.write(payload.encode("utf-8"))
                await writer.drain()
        except (ConnectionError, BrokenPipeError, RuntimeError):
            return

    async def _terminal_route(self, suffix: str, body: bytes) -> tuple[int, bytes, str]:
        """Dispatch one POST /api/terminal/* control call."""
        if suffix == "start":
            return await self._terminal_start(body)
        if suffix == "stop":
            return await self._terminal_stop(body)
        if suffix == "input":
            return await self._terminal_input(body)
        if suffix == "resize":
            return await self._terminal_resize(body)
        return self._json(404, {"ok": False, "error": "not found"})

    async def _terminal_start(self, body: bytes) -> tuple[int, bytes, str]:
        """Lazily spawn the workspace shell and return its state."""
        try:
            data = self._body_json(body)
            bridge = self.sessions.get(data.get("bridgeId"))
            session = self.terminal.get_or_create(bridge.bridge_id, bridge.workspace)
            await session.start()
        except BridgeError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})
        except TerminalError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})
        return self._json(200, {"ok": True, "terminal": session.state()})

    async def _cli_terminal(
        self, action: str, bridge_id: str, terminal_id: str, params: dict[str, Any]
    ) -> tuple[int, bytes, str]:
        """Dispatch a ``term:`` cliId to the terminal manager instead of ACP."""
        if not terminal_id.startswith(f"term:{bridge_id}:"):
            return self._json(404, {"ok": False, "error": "not_found"})
        session = self.terminal.get_by_id(terminal_id)
        if session is None:
            return self._json(404, {"ok": False, "error": "not_found"})

        try:
            if action == "input":
                payload = params.get("data")
                if isinstance(payload, str):
                    raw = payload.encode("utf-8")
                elif isinstance(params.get("base64"), str):
                    raw = base64.b64decode(params["base64"], validate=True)
                else:
                    raise TerminalError(400, "data is required")
                await session.write_async(raw)
            elif action == "resize":
                session.resize(params.get("cols"), params.get("rows"))
            elif action == "stop":
                await self.terminal.stop_by_id(terminal_id)
            elif action == "close":
                await self.terminal.close_by_id(terminal_id)
            elif action != "state":
                return self._json(404, {"ok": False, "error": "not found"})
        except TerminalError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})
        except ValueError as err:
            return self._json(400, {"ok": False, "error": str(err)})

        return self._json(200, {"ok": True, "cliId": terminal_id, "terminal": session.state()})

    async def _terminal_stop(self, body: bytes) -> tuple[int, bytes, str]:
        """Terminate the shell while retaining its ring and exit metadata."""
        try:
            data = self._body_json(body)
            bridge = self.sessions.get(data.get("bridgeId"))
            await self.terminal.stop(bridge.bridge_id)
        except BridgeError as err:
            return self._json(err.status, {"ok": False, "error": str(err)})
        return self._json(200, {"ok": True, "terminal": self.terminal.state(bridge.bridge_id)})

    async def _terminal_input(self, body: bytes) -> tuple[int, bytes, str]:
        """Write bytes to the PTY without ever logging them."""
        try:
            data = self._body_json(body)
            bridge = self.sessions.get(data.get("bridgeId"))
            session = self.terminal.get(bridge.bridge_id)
            if session is None or not session.running:
                raise TerminalError(409, "terminal is not running")
            payload = data.get("data")
            if isinstance(payload, str):
                raw = payload.encode("utf-8")
            elif isinstance(data.get("base64"), str):
                raw = base64.b64decode(data["base64"], validate=True)
            else:
                raise TerminalError(400, "data is required")
            await session.write_async(raw)
        except (BridgeError, TerminalError, ValueError) as err:
            status = getattr(err, "status", 400)
            return self._json(status, {"ok": False, "error": str(err)})
        return self._json(200, {"ok": True})

    async def _terminal_resize(self, body: bytes) -> tuple[int, bytes, str]:
        """Resize the PTY window."""
        try:
            data = self._body_json(body)
            bridge = self.sessions.get(data.get("bridgeId"))
            session = self.terminal.get(bridge.bridge_id)
            if session is None or not session.running:
                raise TerminalError(409, "terminal is not running")
            session.resize(data.get("cols"), data.get("rows"))
        except (BridgeError, TerminalError) as err:
            status = getattr(err, "status", 400)
            return self._json(status, {"ok": False, "error": str(err)})
        return self._json(200, {"ok": True, "cols": session.cols, "rows": session.rows})

    async def _serve_terminal_websocket(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        headers: dict[str, str],
        query: dict[str, list[str]],
    ) -> None:
        """Stream raw PTY bytes and accept input over one WebSocket."""
        key = (headers.get("sec-websocket-key") or "").strip()
        version = (headers.get("sec-websocket-version") or "").strip()
        protocols = [
            item.strip()
            for item in (headers.get("sec-websocket-protocol") or "").split(",")
            if item.strip()
        ]
        if not key or version != "13":
            await self._write_json(writer, 400, {"ok": False, "error": "bad handshake"})
            return
        if self.token and f"token.{self.token}" not in protocols:
            await self._write_json(writer, 403, {"ok": False, "error": "bad token"})
            return
        if not self.terminal.enabled:
            await self._write_json(writer, 403, {"ok": False, "error": "terminal disabled"})
            return

        try:
            data = self._body_json(query_body(query))
            bridge = self.sessions.get(data.get("bridgeId"))
        except BridgeError as err:
            await self._write_json(writer, err.status, {"ok": False, "error": str(err)})
            return
        session = self.terminal.get(bridge.bridge_id)
        if session is None:
            await self._write_json(writer, 409, {"ok": False, "error": "terminal is not running"})
            return

        since = _optional_int(query_body(query).get("since"))
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode("ascii")).digest()).decode(
            "ascii"
        )
        selected = next(
            (item for item in protocols if item == WS_SUBPROTOCOL or item.startswith("cecli.")),
            WS_SUBPROTOCOL,
        )
        writer.write(
            (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n"
                f"Sec-WebSocket-Protocol: {selected}\r\n\r\n"
            ).encode("latin-1")
        )
        await writer.drain()

        queue = session.subscribe()
        writer_task: asyncio.Task[Any] | None = None
        try:
            seq, output, reset = session.buffer.snapshot(since)
            start = seq - len(output)
            first = start if reset or since is None else max(int(since), start)
            if reset:
                await self._ws_write(
                    writer, 0x1, json.dumps({"type": "reset", "seq": start}).encode("utf-8")
                )
            await self._ws_write(
                writer,
                0x1,
                json.dumps(
                    {
                        "type": "ready",
                        "seq": first,
                        "cols": session.cols,
                        "rows": session.rows,
                        "pid": session.pid,
                    },
                    separators=(",", ":"),
                ).encode("utf-8"),
            )
            if output:
                await self._ws_write(writer, 0x2, struct.pack("!Q", seq) + output)
            if not session.running:
                exit_event = {"type": "exit", "code": getattr(session, "exit_code", None)}
                await self._ws_write(
                    writer,
                    0x1,
                    json.dumps(exit_event, separators=(",", ":")).encode("utf-8"),
                )
                return
            writer_task = asyncio.create_task(self._terminal_ws_writer(writer, queue))
            await self._terminal_ws_reader(reader, session)
        except (ConnectionError, RuntimeError):
            return
        finally:
            session.unsubscribe(queue)
            if writer_task is not None:
                writer_task.cancel()
                await asyncio.gather(writer_task, return_exceptions=True)
            await self._close_writer(writer)

    async def _terminal_ws_writer(
        self, writer: asyncio.StreamWriter, queue: asyncio.Queue[tuple[str, Any]]
    ) -> None:
        """Forward PTY output and exit notifications to one peer."""
        try:
            while True:
                kind, payload = await queue.get()
                if kind == "data":
                    seq, data = payload
                    await self._ws_write(writer, 0x2, struct.pack("!Q", seq) + data)
                elif kind == "exit":
                    await self._ws_write(
                        writer,
                        0x1,
                        json.dumps({"type": "exit", "code": payload}).encode("utf-8"),
                    )
                    return
        except (ConnectionError, BrokenPipeError, RuntimeError, asyncio.CancelledError):
            return

    async def _terminal_ws_reader(self, reader: asyncio.StreamReader, session: Any) -> None:
        """Accept JSON control frames and raw binary input frames."""
        while True:
            try:
                frame = await self._ws_read_frame(reader)
            except (ConnectionError, asyncio.IncompleteReadError):
                return
            if frame is None:
                return
            _fin, opcode, payload = frame
            if opcode == 0x8:
                return
            if opcode == 0x9:
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x2:
                try:
                    await session.write_async(payload)
                except TerminalError:
                    return
                continue
            if opcode != 0x1:
                continue
            try:
                message = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(message, dict):
                continue
            kind = message.get("type")
            if kind == "input":
                text = message.get("data")
                if isinstance(text, str):
                    try:
                        await session.write_async(text.encode("utf-8"))
                    except TerminalError:
                        return
            elif kind == "resize":
                session.resize(message.get("cols"), message.get("rows"))

    async def _serve_terminal_stream(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        query: dict[str, list[str]],
    ) -> None:
        """Read-only SSE fallback for terminal replay and live output."""
        if not self.terminal.enabled:
            await self._write_json(writer, 403, {"ok": False, "error": "terminal disabled"})
            return
        try:
            bridge = self.sessions.get(_optional_str(query.get("bridgeId")))
        except BridgeError as err:
            await self._write_json(writer, err.status, {"ok": False, "error": str(err)})
            return
        session = self.terminal.get(bridge.bridge_id)
        if session is None:
            await self._write_json(writer, 404, {"ok": False, "error": "terminal is not running"})
            return

        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/event-stream\r\n"
            b"Cache-Control: no-cache\r\n"
            b"Connection: keep-alive\r\n"
            b"X-Accel-Buffering: no\r\n\r\n"
            b"retry: 2000\n\n"
        )
        since = _optional_int(_optional_str((query.get("since") or [None])[0]))
        seq, output, reset = session.buffer.snapshot(since)
        replay_start, first = replay_offsets(seq, len(output), since, reset)
        if reset:
            writer.write(f"data: {json.dumps({'type': 'reset', 'seq': replay_start})}\n\n".encode())
        writer.write(f"data: {json.dumps({'type': 'ready', 'seq': first})}\n\n".encode())
        if output:
            event = {
                "type": "output",
                "seq": seq,
                "data": base64.b64encode(output).decode("ascii"),
            }
            writer.write(f"data: {json.dumps(event)}\n\n".encode())
        await writer.drain()

        if not session.running:
            writer.write(
                f"data: {json.dumps({'type': 'exit', 'code': session.exit_code})}\n\n".encode()
            )
            await writer.drain()
            await self._close_writer(writer)
            return

        queue = session.subscribe()
        try:
            while True:
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    writer.write(b": ping\n\n")
                    await writer.drain()
                    continue
                if kind == "data":
                    seq, data = payload
                    event = {
                        "type": "output",
                        "seq": seq,
                        "data": base64.b64encode(data).decode("ascii"),
                    }
                    writer.write(f"data: {json.dumps(event)}\n\n".encode())
                elif kind == "exit":
                    writer.write(
                        f"data: {json.dumps({'type': 'exit', 'code': payload})}\n\n".encode()
                    )
                    await writer.drain()
                    return
                await writer.drain()
        except (ConnectionError, BrokenPipeError, RuntimeError):
            return
        finally:
            session.unsubscribe(queue)
            await self._close_writer(writer)

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

        if command in ("background.list", "background.output"):
            background = self.sessions.get(bridge_id)
            action = command.split(".", 1)[1]
            payload: dict[str, Any] = {"action": action}
            key = params.get("key")
            if action == "output":
                if not isinstance(key, str):
                    raise BridgeError(400, "key is required")
                payload["key"] = key
            result = await background.call_extension("cecli/background", payload)
            if action == "list":
                commands = result.get("commands")
                return {"commands": commands if isinstance(commands, list) else []}
            output = result.get("output")
            entry = result.get("command")
            return {
                "output": output if isinstance(output, str) else "",
                "command": entry if isinstance(entry, dict) else {},
            }

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
        if command == "hooks.list":
            await bridge.refresh_details()
            return bridge.details["hooks"]
        if command in ("hooks.load", "hooks.remove", "hooks.enable", "hooks.disable"):
            return await bridge.set_hook(command.split(".", 1)[1], str(params.get("name")))
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

    def _body_json(self, body: bytes | dict[str, Any]) -> dict[str, Any]:
        """Decode a JSON request body or raise a 400 for malformed input."""

        if isinstance(body, dict):
            return body
        data = self._decode_json(body)
        if data is None:
            raise BridgeError(400, "invalid JSON body")
        return data

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
            503: "Service Unavailable",
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
        terminal_enabled: bool = False,
        terminal_shell: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.workspace = workspace
        self.cecli = cecli
        self.extra_args = extra_args
        self.open_browser = open_browser
        self.token = token
        self.max_sessions = max_sessions
        self.terminal_enabled = terminal_enabled
        self.terminal_shell = terminal_shell


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
        "--no-terminal",
        action="store_true",
        help="disable the interactive terminal panel",
    )
    parser.add_argument(
        "--terminal-shell",
        default=os.environ.get("CECLI_DESKTOP_TERMINAL_SHELL") or None,
        help="shell used for the interactive terminal",
    )
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
    terminal_disabled = os.environ.get("CECLI_DESKTOP_TERMINAL", "").lower() in (
        "0",
        "false",
        "no",
        "off",
    )
    terminal_enabled = not (args.no_terminal or terminal_disabled)

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
        terminal_enabled,
        args.terminal_shell,
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
    conf = ConfStore(config.workspace)
    onboarding = OnboardingService(manager, conf)
    browser = BrowserBridge()
    terminal = TerminalManager(
        enabled=config.terminal_enabled and is_loopback_host(config.host),
        shell=config.terminal_shell,
    )
    app = DesktopServer(
        manager,
        root,
        config.host,
        token=config.token,
        browser=browser,
        conf=conf,
        onboarding=onboarding,
        terminal=terminal,
        cli_enabled=os.environ.get("CECLI_DESKTOP_CLI_PANE", "").lower()
        not in ("0", "false", "no", "off"),
    )
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
    for sig in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGHUP", None)):
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass

    for entry in conf.workspace_states():
        if not entry["valid"]:
            print(
                f"warning: skipping workspace {entry['path']}: {entry.get('error', 'invalid')}",
                file=sys.stderr,
                flush=True,
            )
            continue
        manager.allow_root(entry["path"])
        if not entry.get("enable_on_startup", True):
            continue
        try:
            manager.create(entry["path"], entry["name"])
        except BridgeError as err:
            print(
                f"warning: could not start workspace {entry['path']}: {err}",
                file=sys.stderr,
                flush=True,
            )
    initial_browser = browser.snapshot()
    if initial_browser.get("running") and initial_browser.get("cdpUrl"):
        asyncio.create_task(
            manager.announce_browser(
                {
                    "cdpUrl": initial_browser["cdpUrl"],
                    "port": initial_browser.get("port"),
                    "url": initial_browser.get("url", ""),
                }
            )
        )
    if config.open_browser:
        asyncio.create_task(_open_browser(url))
    terminal_reaper = asyncio.create_task(_terminal_reaper_loop(terminal))

    try:
        await stop.wait()
    finally:
        server.close()
        try:
            await asyncio.wait_for(server.wait_closed(), 2.0)
        except asyncio.TimeoutError:
            pass
        try:
            await manager.shutdown()
        finally:
            try:
                await terminal.shutdown()
            finally:
                terminal_reaper.cancel()
                await asyncio.gather(terminal_reaper, return_exceptions=True)
                await browser.shutdown()


async def _terminal_reaper_loop(terminal: TerminalManager) -> None:
    """Drop exited terminal generations after their retention TTL."""
    while True:
        await asyncio.sleep(60)
        try:
            await terminal.reap()
        except Exception:
            pass


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


def _sse_payload(payload: dict[str, Any], event_id: int | None = None) -> bytes:
    """Encode one SSE frame, optionally carrying a resume cursor."""
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    body = json.dumps(payload, separators=(",", ":"))
    return f"{prefix}data: {body}\n\n".encode()


def query_body(query: dict[str, list[str]]) -> dict[str, str]:
    """Flatten a parsed query string to its first value per key."""

    return {key: values[0] for key, values in query.items() if values}


def _normalize_cli_key(bridge_id: str, value: Any) -> Any:
    """Accept UI tab ids of the form ``bg:<bridge>:<command key>``."""
    if not isinstance(value, str):
        return value

    prefix = f"bg:{bridge_id}:"
    return value[len(prefix) :] if value.startswith(prefix) else value


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
    arm_parent_death()
    config = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        asyncio.run(run_server(config))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
