"""AcpAgent: the agent side of the Agent Client Protocol (ACP) v1.

One process serves one project. ``bootstrap()`` runs before ``main_async`` so
the first ``session/new`` can pick the working directory the coder is built in;
its response is deferred until the coder first asks for input. From then on the
coder's normal linear run loop drives each turn: a turn starts when
``next_input`` hands the loop a prompt and ends when the loop asks again.
"""

from __future__ import annotations

import asyncio
import base64
import math
import os
import sys
import time
import uuid
import weakref
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from cecli import __version__
from cecli.helpers.server.acp.agent.config import SessionConfig, current_value
from cecli.helpers.server.acp.agent.mcp import ClientMcpServers
from cecli.helpers.server.acp.agent.transport import (
    EOF,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    Transport,
    error_message,
    log,
    result_message,
)
from cecli.helpers.server.acp.agent.updates import CONSOLE_FENCE, UpdateEmitter
from cecli.helpers.server.acp.events import (
    SCOPE_CONTEXT,
    SCOPE_HOOKS,
    SCOPE_MCP,
    SCOPE_SKILLS,
    SCOPE_WORKFLOWS,
    STATE_IDLE,
    STATE_REQUIRES_ACTION,
    STATE_RUNNING,
    state_update,
)

PROTOCOL_VERSION = 1

# Commands that make no sense when an editor owns the UI
HIDDEN_COMMANDS = {
    "edit",
    "editor",
    "exit",
    "hot-reload",
    "multiline-mode",
    "quit",
    "terminal-setup",
    "voice",
}

# Commands safe to run without waiting for the current turn to finish.
# Steering them would hand the text to the model instead of executing it.
MID_TURN_COMMANDS = {"reap-agent"}

_DEFERRED = object()


class AcpError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ── Prompt conversion ──────────────────────────────────────────


def _file_path(uri: str | None) -> str | None:
    if not uri or not uri.startswith("file://"):
        return None
    path = unquote(urlparse(uri).path)
    if os.name == "nt" and len(path) > 2 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return path


def _display_path(path: str, root: str) -> str:
    try:
        rel = os.path.relpath(path, root)
    except ValueError:  # different drive
        return path
    return path if rel.startswith("..") else rel


def prompt_to_text(blocks: list, root: str) -> tuple[str, list[str]]:
    """Flatten ACP content blocks into cecli input text plus mentioned file paths."""
    parts: list[str] = []
    paths: list[str] = []
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            parts.append(block.get("text") or "")
        elif kind == "resource_link":
            path = _file_path(block.get("uri"))
            if path:
                paths.append(path)
                parts.append(_display_path(path, root))
            else:
                parts.append(block.get("uri") or block.get("name") or "")
        elif kind == "resource":
            resource = block.get("resource") or {}
            uri = resource.get("uri") or ""
            path = _file_path(uri)
            if path:
                paths.append(path)
            label = _display_path(path, root) if path else uri
            text = resource.get("text")
            if text is not None and (not path or "#" in uri):
                # A selection or non-file context: the text itself is the point
                parts.append(f"\n{label}:\n```\n{text}\n```\n")
            else:
                parts.append(label)
    return " ".join(p for p in parts if p).strip(), paths


# ── Agent ──────────────────────────────────────────────────────


@dataclass
class _Turn:
    text: str
    on_finish: Callable[[str], None]
    request_id: Any = None  # None for internal commands, whose output is not shown
    paths: list[str] = field(default_factory=list)
    cancelled: bool = False


@dataclass
class _Subagent:
    """A cecli sub-agent, shown to the client as a child session."""

    agent_uuid: str
    session_id: str
    parent_session_id: str
    emitter: UpdateEmitter
    running: bool = False
    cancelled: bool = False
    removed: bool = False


class AcpAgent:
    def __init__(self, transport: Transport):
        self.transport = transport
        self.emitter = UpdateEmitter(self._send_turn_update)
        self.config = SessionConfig()
        self.mcp = ClientMcpServers(log)
        self.session_id: str | None = None
        self.cwd: str | None = None
        self.turn: _Turn | None = None
        self._deferred_new: list[Any] = []
        self._ready = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._inputs: asyncio.Queue | None = None
        self._dispatcher: asyncio.Task | None = None
        self._coder_ref = None
        self._next_request_id = 0
        # request id -> (future, the session that asked)
        self._pending: dict[Any, tuple[asyncio.Future, str | None]] = {}
        self._sent_options: list[dict] | None = None
        # Sub-agents as child sessions, keyed by coder uuid; only for clients
        # that advertise the (unstable) subagents capability
        self.subagents_supported = False
        self.subagents: dict[str, _Subagent] = {}
        self._message_count = 0
        self._shutdown_started = False
        self._termination_requested = False
        self._background_emitter = None

    # ── Lifecycle ───────────────────────────────────────────────

    def bootstrap(self) -> str | None:
        """Open the transport, answer ``initialize`` and wait for the first ``session/new``.

        Returns that session's cwd, or None if the client hung up first.
        """
        self.transport.open()
        # Commands run in a pseudo-terminal, where git log and friends start a
        # pager that waits for a keypress nobody can send
        os.environ["PAGER"] = "cat"
        os.environ["GIT_PAGER"] = "cat"
        return asyncio.run(self._await_first_session())

    async def _await_first_session(self) -> str | None:
        self.transport.attach(asyncio.get_running_loop())
        try:
            while True:
                msg = await self.transport.receive()
                if msg is EOF:
                    return None
                if msg.get("method") == "session/new" and "id" in msg:
                    try:
                        cwd = _require_cwd(msg.get("params") or {})
                    except AcpError as err:
                        self.transport.send(error_message(msg["id"], err.code, err.message))
                        continue
                    self.cwd = cwd
                    self.session_id = _new_session_id()
                    self.mcp.want((msg.get("params") or {}).get("mcpServers"))
                    self._deferred_new.append(msg["id"])
                    return cwd
                self._handle(msg)
        finally:
            self.transport.detach()

    @property
    def launched(self) -> bool:
        """True once ``bootstrap`` has a session to serve."""
        return self.session_id is not None

    def start(self) -> None:
        """Serve the protocol on the running loop (``main_async``'s)."""
        if not self.launched:
            raise RuntimeError("--acp must be launched through the cecli command line")
        loop = asyncio.get_running_loop()
        if self._loop is loop:
            return
        if self.turn is not None:
            # A program reload dropped the loop mid-turn
            self._finish_turn()
        self._loop = loop
        self._inputs = asyncio.Queue()
        self.transport.attach(loop)
        self._start_background_emitter()
        self._dispatcher = loop.create_task(self._dispatch())

    def shutdown(self) -> None:
        """Answer whatever is still waiting before the process exits."""
        if self._shutdown_started:
            return
        self._shutdown_started = True
        for request_id in self._deferred_new:
            self.transport.send(
                error_message(
                    request_id,
                    INTERNAL_ERROR,
                    "cecli exited before the session was ready; see its stderr for details",
                )
            )
        self._deferred_new.clear()
        self._finish_turn()
        try:
            from cecli.helpers.background_commands import BackgroundCommandManager

            BackgroundCommandManager.stop_all_background_commands(timeout=2.0)
        except Exception:
            pass

        emitter = getattr(self, "_background_emitter", None)
        if emitter is not None:
            from cecli.helpers.background_commands import BackgroundCommandManager

            BackgroundCommandManager.set_event_sink(None)
            emitter.close()
            self._background_emitter = None

    def _start_background_emitter(self) -> None:
        """Install the ordered background event sink for this bridge."""
        from cecli.helpers.background_commands import BackgroundCommandManager
        from cecli.helpers.server.acp.agent.background_events import (
            BackgroundEventEmitter,
        )

        if self._background_emitter is not None:
            self._background_emitter.close()

        self._background_emitter = BackgroundEventEmitter(
            lambda notification: self.transport.send(notification)
        )
        BackgroundCommandManager.set_event_sink(self._background_emitter)

    def request_termination(self) -> None:
        """Signal-safe: flag termination without acquiring locks or waiting."""
        self._termination_requested = True
        if self.turn is not None:
            self.turn.cancelled = True

    async def _dispatch(self) -> None:
        while True:
            msg = await self.transport.receive()
            if msg is EOF:
                self._on_eof()
                return
            if "method" in msg:
                self._handle(msg)
            else:
                self._on_response(msg)

    def _on_eof(self) -> None:
        self._cancel_pending_requests()
        if self.turn is not None:
            self.turn.cancelled = True
            self._interrupt_coder()
        self._inputs.put_nowait(EOF)
        try:
            from cecli.helpers.background_commands import BackgroundCommandManager

            BackgroundCommandManager.stop_all_background_commands(timeout=2.0)
        except Exception:
            pass

    # ── Inbound ─────────────────────────────────────────────────
    def _handle(self, msg: dict) -> None:
        method = msg.get("method")
        params = msg.get("params") or {}
        is_request = "id" in msg
        request_id = msg.get("id")
        handlers = {
            "initialize": self._on_initialize,
            "authenticate": lambda params, request_id: {},
            "session/new": self._on_session_new,
            "session/prompt": self._on_session_prompt,
            "session/cancel": self._on_session_cancel,
            "session/set_config_option": self._on_set_config_option,
            "session/set_mode": self._on_set_mode,
            "cecli/state": self._on_cecli_state,
            "cecli/history": self._on_cecli_history,
            "cecli/skill": self._on_cecli_skill,
            "cecli/hook": self._on_cecli_hook,
            "cecli/mcp": self._on_cecli_mcp,
            "cecli/workflow": self._on_cecli_workflow,
            "cecli/context": self._on_cecli_context,
            "cecli/steer": self._on_cecli_steer,
            "cecli/complete": self._on_cecli_complete,
            "cecli/background": self._on_cecli_background,
            "cecli/browser": self._on_cecli_browser,
            "cecli/subagent/message": self._on_cecli_subagent_message,
        }
        handler = handlers.get(method)
        if handler is None:
            if is_request:
                self.transport.send(
                    error_message(request_id, METHOD_NOT_FOUND, f"Method not found: {method}")
                )
            return

        try:
            result = handler(params, request_id)
        except AcpError as err:
            if is_request:
                self.transport.send(error_message(request_id, err.code, err.message))
            return
        except Exception as err:  # never let one bad message kill the dispatcher
            log(f"error handling {method}: {err!r}")
            if is_request:
                self.transport.send(error_message(request_id, INTERNAL_ERROR, str(err)))
            return

        if is_request and result is not _DEFERRED:
            self.transport.send(result_message(request_id, result))

    def _on_initialize(self, params: dict, request_id: Any) -> dict:
        capabilities = params.get("clientCapabilities") or {}
        self.subagents_supported = isinstance(capabilities.get("subagents"), dict)
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "agentCapabilities": {
                "loadSession": False,
                "promptCapabilities": {"image": False, "audio": False, "embeddedContext": True},
                "mcpCapabilities": {"http": True, "sse": True},
            },
            "authMethods": [],
            "agentInfo": {"name": "cecli", "title": "cecli", "version": __version__},
        }

    def _on_session_new(self, params: dict, request_id: Any) -> Any:
        cwd = _require_cwd(params)
        if self.cwd is None:
            raise AcpError(INTERNAL_ERROR, "cecli is not running in ACP mode")
        if os.path.realpath(cwd) != os.path.realpath(self.cwd):
            raise AcpError(
                INVALID_PARAMS,
                f"This cecli process serves {self.cwd}; start another agent for {cwd}",
            )
        self.mcp.want(params.get("mcpServers"))
        if not self._ready:
            self._deferred_new.append(request_id)
            return _DEFERRED

        # A new thread on the same project: clear the chat, then hand out a new id
        session_id = _new_session_id()

        def finish(_stop_reason: str) -> None:
            self.session_id = session_id
            self.transport.send(result_message(request_id, self._session_state()))
            self._announce_commands()

        self._inputs.put_nowait(_Turn("/clear", on_finish=finish))
        return _DEFERRED

    def _on_session_prompt(self, params: dict, request_id: Any) -> Any:
        self._require_session(params.get("sessionId"))
        text, paths = prompt_to_text(params.get("prompt"), self.cwd or os.getcwd())
        if not text and not paths:
            return {"stopReason": "end_turn"}

        def finish(stop_reason: str) -> None:
            self.transport.send(result_message(request_id, {"stopReason": stop_reason}))

        self._inputs.put_nowait(_Turn(text, on_finish=finish, request_id=request_id, paths=paths))
        return _DEFERRED

    def _run_mid_turn_command(
        self, coder: Any, text: str, target_agent_uuid: str | None = None
    ) -> bool:
        """Run a command now instead of queueing it into the running turn."""
        if self._loop is None or not text.startswith("/"):
            return False

        commands = getattr(coder, "commands", None)
        if commands is None:
            return False

        from cecli.commands.utils.registry import CommandRegistry

        name = text.strip().split()[0][1:]
        alias = CommandRegistry.resolve_alias(name)
        if (alias[0] if alias else name) not in MID_TURN_COMMANDS:
            return False

        self._loop.create_task(self._run_command(coder, text, target_agent_uuid))
        return True

    async def _run_command(
        self, coder: Any, text: str, target_agent_uuid: str | None = None
    ) -> None:
        """Run a command outside the turn loop, logging any failure."""
        try:
            await coder.commands.run(text, coder=coder, target_agent_uuid=target_agent_uuid)
        except Exception as err:
            log(f"could not run command {text.split()[0]}: {err!r}")

    def _on_cecli_steer(self, params: dict, request_id: Any) -> dict:
        """Inject a prompt into the running turn instead of queueing a new one."""
        from cecli.helpers.conversation.service import ConversationService
        from cecli.helpers.conversation.tags import MessageTag

        self._require_session(params.get("sessionId"))
        text, paths = prompt_to_text(params.get("prompt"), self.cwd or os.getcwd())
        if not text:
            raise AcpError(INVALID_PARAMS, "text is required")

        if not self.in_prompt():
            return {"ok": True, "steered": False}

        coder = self._require_coder()
        is_command = self._run_mid_turn_command(coder, text)

        if not is_command:
            _log_user_input(coder, text)

            if paths:
                _add_mentions(coder, paths)

            ConversationService.get_manager(coder).queue_message(
                message_dict={"role": "user", "content": coder.wrap_user_input(text)},
                tag=MessageTag.CUR,
                hash_key=("steer", str(coder.uuid), str(time.monotonic_ns())),
            )

        self._message_count += 1
        self.send_update(
            {
                "sessionUpdate": "session_message",
                "userMessage": True,
                "messageId": f"cecli-message-{self._message_count}",
                "senderSessionId": self.session_id,
                "recipientSessionId": self.session_id,
                "content": [{"type": "text", "text": text}],
            }
        )
        return {"ok": True, "steered": True}

    def _on_session_cancel(self, params: dict, request_id: Any) -> None:
        if params.get("sessionId") != self.session_id:
            self._cancel_subagent(params.get("sessionId"))
            return None

        # Prompts queued behind the running one are dropped
        kept = []
        while not self._inputs.empty():
            queued = self._inputs.get_nowait()
            if isinstance(queued, _Turn) and queued.request_id is not None:
                queued.on_finish("cancelled")
            else:
                kept.append(queued)
        for queued in kept:
            self._inputs.put_nowait(queued)

        if self.turn is not None and self.turn.request_id is not None:
            self.turn.cancelled = True
            # Sub-agents the turn waits for are cancelled with it and report that
            # themselves; ones working in the background keep going
            self._cancel_pending_requests(self.session_id)
            self._interrupt_coder()
        return None

    def _on_set_config_option(self, params: dict, request_id: Any) -> Any:
        self._require_session(params.get("sessionId"))
        command = self._config_command(params.get("configId"), params.get("value"))
        if command is None:
            return {"configOptions": self._current_options()}

        def finish(_stop_reason: str) -> None:
            self.transport.send(
                result_message(request_id, {"configOptions": self._current_options()})
            )

        self._inputs.put_nowait(_Turn(command, on_finish=finish))
        return _DEFERRED

    def _on_set_mode(self, params: dict, request_id: Any) -> Any:
        # Legacy modes, for clients without config options
        self._require_session(params.get("sessionId"))
        command = self._config_command("mode", params.get("modeId"))
        if command is None:
            return {}

        def finish(_stop_reason: str) -> None:
            self._sync_config()
            self.transport.send(result_message(request_id, {}))

        self._inputs.put_nowait(_Turn(command, on_finish=finish))
        return _DEFERRED

    def _config_command(self, config_id: Any, value: Any) -> str | None:
        try:
            return self.config.command(self._coder(), config_id, value)
        except ValueError as err:
            raise AcpError(INVALID_PARAMS, str(err))

    # ── Desktop state and controls ───────────────────────────────────────

    def _on_cecli_state(self, params: dict, request_id: Any) -> dict:
        """Return the TUI-level state the desktop sidebar renders."""
        coder = self._coder()
        if coder is None:
            return self._empty_state()
        return self._state_snapshot(coder)

    def _on_cecli_history(self, params: dict, request_id: Any) -> dict:
        """Return each coder's visible conversation stream for transcript replay."""
        coder = self._coder()
        if coder is None:
            return {"messages": [], "subagents": [], "diffs": []}

        from cecli.helpers.agents.service import AgentService

        service = AgentService.get_instance(coder)
        infos = {str(info.coder.uuid): info for info in service.sub_agents.values()}
        subagents: list[dict[str, Any]] = []

        for subagent in self.subagents.values():
            info = infos.get(str(subagent.agent_uuid))
            if info is None or subagent.removed:
                continue
            subagents.append(
                {
                    "sessionId": subagent.session_id,
                    "uuid": subagent.agent_uuid,
                    "messages": _conversation_history(info.coder),
                    "diffs": _conversation_diffs(info.coder),
                }
            )

        return {
            "messages": _conversation_history(coder),
            "subagents": subagents,
            "diffs": _conversation_diffs(coder),
        }

    def _on_cecli_skill(self, params: dict, request_id: Any) -> dict:
        """Load, remove, include or exclude a skill on the serialised coder."""
        coder = self._require_coder()
        manager = getattr(coder, "skills_manager", None)
        if manager is None:
            raise AcpError(INVALID_PARAMS, "skills are not available")

        action = params.get("action")
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise AcpError(INVALID_PARAMS, "name is required")

        actions = {
            "load": manager.load_skill,
            "remove": manager.remove_skill,
            "include": manager.include_skill,
            "exclude": manager.exclude_skill,
        }
        handler = actions.get(action)
        if handler is None:
            raise AcpError(INVALID_PARAMS, f"unknown skill action: {action}")

        try:
            result = handler(name)
        except Exception as err:
            raise AcpError(INTERNAL_ERROR, str(err)) from err

        self._emit_state(scope=SCOPE_SKILLS)
        return {"result": result, "skills": self._skills_state(coder)}

    def _on_cecli_hook(self, params: dict, request_id: Any) -> dict:
        """Enable or disable a configured hook on the serialised coder.

        ``load``/``enable`` turn a hook on and ``remove``/``disable`` turn it off.
        The change only lives in the running session; nothing is written back to
        the YAML or Python hook sources.
        """
        from cecli.hooks.service import HookService

        coder = self._require_coder()
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise AcpError(INVALID_PARAMS, "name is required")

        actions = {
            "load": "enable_hook",
            "enable": "enable_hook",
            "remove": "disable_hook",
            "disable": "disable_hook",
        }
        method = actions.get(params.get("action"))
        if method is None:
            raise AcpError(INVALID_PARAMS, f"unknown hook action: {params.get('action')}")

        try:
            manager = HookService.get_manager(coder)
            if not manager.hook_exists(name):
                raise AcpError(INVALID_PARAMS, f"Hook '{name}' not found")
            changed = getattr(manager, method)(name)
        except AcpError:
            raise
        except Exception as err:
            raise AcpError(INTERNAL_ERROR, str(err)) from err

        self._emit_state(scope=SCOPE_HOOKS)
        return {"result": bool(changed), "hooks": self._hooks_state(coder)}

    def _on_cecli_mcp(self, params: dict, request_id: Any) -> Any:
        """Connect or disconnect an MCP server without blocking the dispatcher."""
        coder = self._require_coder()
        manager = getattr(coder, "mcp_manager", None)
        if manager is None:
            raise AcpError(INVALID_PARAMS, "MCP is not available")

        action = params.get("action")
        name = params.get("name")
        if action not in ("connect", "disconnect") or not isinstance(name, str) or not name:
            raise AcpError(INVALID_PARAMS, "action and name are required")

        async def run() -> None:
            error = None
            try:
                if action == "connect":
                    await manager.connect_server(name)
                else:
                    await manager.disconnect_server(name)
            except Exception as err:
                error = str(err)

            payload: dict[str, Any] = {"mcpServers": self._mcp_state(coder)}
            if error:
                payload["error"] = error
            self._emit_state(scope=SCOPE_MCP)
            self.transport.send(result_message(request_id, payload))

        asyncio.run_coroutine_threadsafe(run(), self._loop)
        return _DEFERRED

    def _on_cecli_workflow(self, params: dict, request_id: Any) -> Any:
        """List workflows, or start a manual run in the background."""
        coder = self._require_coder()
        action = params.get("action", "list")

        if action == "list":
            return {"workflows": self._workflow_state(coder)}
        if action != "run":
            raise AcpError(INVALID_PARAMS, f"unknown workflow action: {action}")

        from cecli.commands.workflow_helpers.common import find

        wf = find(coder, params.get("name"))
        if wf is None:
            raise AcpError(INVALID_PARAMS, f"unknown workflow: {params.get('name')}")

        async def run() -> None:
            from cecli.helpers.workflows.runner import execute_workflow

            try:
                result = await execute_workflow(coder, wf, source="manual")
                payload = {
                    "status": result.status,
                    "summary": result.summary,
                    "workflows": self._workflow_state(coder),
                }
            except Exception as err:
                payload = {"error": str(err), "workflows": self._workflow_state(coder)}
            self._emit_state(scope=SCOPE_WORKFLOWS)
            self.transport.send(result_message(request_id, payload))

        asyncio.run_coroutine_threadsafe(run(), self._loop)
        return _DEFERRED

    def _on_cecli_context(self, params: dict, request_id: Any) -> dict:
        """Add or remove a file from the coder's editable or read-only context."""
        coder = self._require_coder()
        action = params.get("action")
        path = params.get("path")
        if action not in ("add", "remove") or not isinstance(path, str) or not path:
            raise AcpError(INVALID_PARAMS, "action and path are required")

        root = self.cwd or os.getcwd()
        absolute = path if os.path.isabs(path) else os.path.abspath(os.path.join(root, path))
        read_only = bool(params.get("readOnly"))

        if action == "add":
            target = coder.abs_read_only_fnames if read_only else coder.abs_fnames
            target.add(absolute)
        else:
            coder.abs_fnames.discard(absolute)
            coder.abs_read_only_fnames.discard(absolute)

        self._emit_state(scope=SCOPE_CONTEXT)
        return {"contextFiles": self._context_state(coder)}

    def _on_cecli_complete(self, params: dict, request_id: Any) -> dict:
        """Return shell-style completion candidates for the desktop composer."""
        coder = self._require_coder()
        text = params.get("text")
        if not isinstance(text, str):
            raise AcpError(INVALID_PARAMS, "text is required")
        return _complete(coder, text)

    def _on_cecli_browser(self, params: dict, request_id: Any) -> dict:
        """Point browser-harness at the desktop's shared browser."""
        from cecli.helpers import browser

        action = params.get("action", "set")
        if action == "clear":
            browser.clear_active_cdp_url()
            return {"ok": True}

        cdp_url = params.get("cdpUrl") or params.get("cdp_url")
        if not isinstance(cdp_url, str) or not cdp_url.strip():
            raise AcpError(INVALID_PARAMS, "cdpUrl is required")

        parsed = urlparse(cdp_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise AcpError(INVALID_PARAMS, "cdpUrl must be an http(s) URL")

        port = params.get("port") or parsed.port
        value = browser.set_active_cdp_url(cdp_url, port)
        return {"ok": True, "cdpUrl": value, "port": port}

    def _on_cecli_background(self, params: dict, request_id: Any) -> dict:
        """Handle background command introspection and control actions."""
        from cecli.helpers.background_commands import BackgroundCommandManager

        action = params.get("action", "list")
        commands = BackgroundCommandManager.list_background_commands()

        if action == "list":
            return {
                "commands": [
                    self._background_entry(command_key, info)
                    for command_key, info in commands.items()
                ]
            }

        if action == "stop_all":
            stopped = BackgroundCommandManager.signal_stop_all_background_commands()
            return {"ok": True, "stopped": stopped, "state": "stopping"}

        command_key = params.get("key")
        if not isinstance(command_key, str) or not command_key:
            raise AcpError(INVALID_PARAMS, "key is required")

        info = commands.get(command_key)

        if action == "output":
            if info is None:
                raise AcpError(INVALID_PARAMS, f"unknown background command: {command_key}")
            return {
                "output": BackgroundCommandManager.get_command_output(command_key),
                "command": self._background_entry(command_key, info),
            }

        if action == "state":
            if info is None:
                return {"ok": False, "error": "not_found"}
            return {"command": self._background_entry(command_key, info)}

        if action == "snapshot":
            snapshot = BackgroundCommandManager.snapshot_background_command(
                command_key, params.get("since")
            )
            if snapshot is None:
                return {"ok": False, "error": "not_found"}
            return {
                "seq": snapshot["seq"],
                "startSeq": snapshot["startSeq"],
                "data": base64.b64encode(snapshot["data"]).decode("ascii"),
                "reset": snapshot["reset"],
                "state": snapshot["state"],
            }

        if action == "input":
            release = bool(params.get("release", False))
            encoded = params.get("base64")
            raw = params.get("data")

            if isinstance(encoded, str):
                try:
                    data = base64.b64decode(encoded.encode("ascii"), validate=True)
                except Exception:
                    raise AcpError(INVALID_PARAMS, "base64 is invalid")
            elif isinstance(raw, str):
                data = raw.encode("utf-8")
            elif release:
                data = b""
            else:
                raise AcpError(INVALID_PARAMS, "base64 or data is required")

            accepted, status = BackgroundCommandManager.send_input_bytes(
                command_key,
                data,
                owner=params.get("owner"),
                release=release,
            )
            if status in ("accepted", "released"):
                updated = BackgroundCommandManager.list_background_commands().get(command_key, {})
                return {
                    "ok": True,
                    "accepted": accepted,
                    "inputSeq": params.get("inputSeq"),
                    "inputOwner": updated.get("input_owner", updated.get("inputOwner")),
                }
            return {"ok": False, "error": status}

        if action == "resize":
            info_r = BackgroundCommandManager.resize_background_command(
                command_key, params.get("cols"), params.get("rows")
            )
            if info_r is None:
                return {"ok": False, "error": "not_found"}
            return {
                "cols": info_r["cols"],
                "rows": info_r["rows"],
                "resized": info_r["resized"],
            }

        if action == "stop":
            if info is None:
                return {"ok": False, "error": "not_found"}
            timeout = max(0.1, float(params.get("timeoutMs", 5000)) / 1000.0)
            signalled = BackgroundCommandManager.signal_stop_background_command(
                command_key, timeout=timeout
            )
            return {
                "ok": True,
                "exitCode": info.get("exit_code", info.get("exitCode")),
                "signal": info.get("signal"),
                "endedAt": info.get("ended_at", info.get("endedAt")),
                "state": "stopping" if signalled else info.get("state"),
            }
            return {
                "ok": True,
                "exitCode": info.get("exit_code", info.get("exitCode")),
                "signal": info.get("signal"),
                "endedAt": info.get("ended_at", info.get("endedAt")),
                "state": "stopping" if signalled else info.get("state"),
            }

        if action == "close":
            ok, status = BackgroundCommandManager.close_background_command(command_key)
            if not ok:
                return {"ok": False, "error": status}
            return {"ok": True, "state": status}

        raise AcpError(INVALID_PARAMS, f"unknown background action: {action}")

    def _on_cecli_subagent_message(self, params: dict, request_id: Any) -> dict:
        """Send a message to an active sub-agent, starting one when it is idle."""
        from cecli.helpers.agents.service import AgentService

        coder = self._require_coder()
        session_id = params.get("sessionId")
        text = params.get("text")
        if not isinstance(text, str) or not text.strip():
            raise AcpError(INVALID_PARAMS, "text is required")

        subagent = next(
            (
                item
                for item in self.subagents.values()
                if item.session_id == session_id and not item.removed
            ),
            None,
        )
        if subagent is None:
            raise AcpError(INVALID_PARAMS, "unknown sub-agent session")

        service = AgentService.get_instance(coder)
        info = service.sub_agents.get(subagent.agent_uuid)
        if info is None:
            raise AcpError(INVALID_PARAMS, "the sub-agent is no longer tracked")

        if not self._run_mid_turn_command(info.coder, text, target_agent_uuid=subagent.agent_uuid):
            if subagent.running:
                from cecli.helpers.conversation.service import ConversationService
                from cecli.helpers.conversation.tags import MessageTag

                with service._get_lock(service._conversation_locks, info.coder.uuid):
                    ConversationService.get_manager(info.coder).add_message(
                        message_dict={"role": "user", "content": text},
                        tag=MessageTag.CUR,
                        hash_key=(
                            "desktop_message",
                            "user",
                            info.coder.uuid,
                            str(time.monotonic_ns()),
                        ),
                        force=True,
                    )
            else:
                service.start_generate_task(info, text)

        self._message_count += 1
        self.send_update(
            {
                "sessionUpdate": "session_message",
                "userMessage": True,
                "messageId": f"cecli-message-{self._message_count}",
                "senderSessionId": self.session_id,
                "recipientSessionId": subagent.session_id,
                "content": [{"type": "text", "text": text}],
            },
            subagent.parent_session_id,
        )
        return {"ok": True, "running": subagent.running}

    def _on_response(self, msg: dict) -> None:
        future, _session_id = self._pending.get(msg.get("id"), (None, None))
        if future is None or future.done():
            return
        if "error" in msg:
            log(f"client error: {msg['error']}")
            future.set_result(None)
        else:
            future.set_result(msg.get("result"))

    def _require_session(self, session_id: Any) -> None:
        if not self._ready or session_id != self.session_id:
            raise AcpError(INVALID_PARAMS, f"Unknown session: {session_id}")

    # ── Turns (called from the coder loop via AcpInputOutput) ───

    async def next_input(self, coder: Any = None) -> str:
        """End the current turn, then wait for the next prompt."""
        # A mode or model switch replaces the coder, so track it before the
        # finished turn reports the new configuration
        if coder is not None:
            self._coder_ref = weakref.ref(coder)
            if self.mcp.pending:
                # Before session/new is answered, so the first prompt has the tools
                await self._sync_mcp(coder)
        self._finish_turn()

        if not self._ready:
            self._ready = True
            for request_id in self._deferred_new:
                self.transport.send(result_message(request_id, self._session_state()))
            self._deferred_new.clear()
            self._announce_commands()

        turn = await self._inputs.get()
        if turn is EOF:
            self._inputs.put_nowait(EOF)
            raise EOFError
        self.turn = turn
        if turn.paths and coder is not None:
            _add_mentions(coder, turn.paths)
        if turn.request_id is not None:
            self._emit_state(state=STATE_RUNNING)
        return turn.text

    async def _sync_mcp(self, coder: Any) -> None:
        try:
            await self.mcp.sync(
                getattr(coder, "mcp_manager", None), coder.io, getattr(coder, "verbose", False)
            )
        except Exception as err:  # a broken MCP server must not break the session
            log(f"could not connect the client's MCP servers: {err!r}")

    def in_prompt(self) -> bool:
        """True while a client prompt (not an internal command) is running."""
        return self.turn is not None and self.turn.request_id is not None

    def _finish_turn(self) -> None:
        turn = self.turn
        if turn is not None and turn.request_id is not None:
            self.emitter.finish_turn(cancelled=turn.cancelled)
            stop_reason = "cancelled" if turn.cancelled else "end_turn"
            self._emit_state(state=STATE_IDLE, stop_reason=stop_reason)
            self._sync_config()
        else:
            self.emitter.reset()
        self.turn = None
        if turn is not None:
            turn.on_finish("cancelled" if turn.cancelled else "end_turn")

    def _coder(self) -> Any:
        return self._coder_ref() if self._coder_ref is not None else None

    def _interrupt_coder(self) -> None:
        coder = self._coder()
        if coder is None:
            return
        task = getattr(coder.io, "output_task", None)
        if task is not None and not task.done():
            task.cancel()
        event = getattr(coder, "interrupt_event", None)
        if event is not None:
            event.set()

    # ── Outbound ────────────────────────────────────────────────

    def _send_turn_update(self, update: dict) -> None:
        kind = update.get("sessionUpdate")
        if self.in_prompt() or kind == "state_update":
            self.send_update(update)
        elif kind == "agent_message_chunk":
            # Output outside a prompt (startup, internal commands) is only logged,
            # so startup failures still explain themselves in the client's logs
            text = update["content"]["text"].replace(CONSOLE_FENCE + "\n", "")
            sys.stderr.write(text)
            sys.stderr.flush()

    def send_update(self, update: dict, session_id: str | None = None) -> None:
        self.transport.send(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {"sessionId": session_id or self.session_id, "update": update},
            }
        )

    def _emit_state(
        self,
        state: str | None = None,
        scope: str | None = None,
        stop_reason: str | None = None,
    ) -> None:
        """Push the session activity, plus the changed detail scope when there is one."""
        if state is None:
            state = STATE_RUNNING if self.in_prompt() else STATE_IDLE
        self.emitter.emit(state_update(state, stop_reason=stop_reason, scope=scope))

    def _current_options(self) -> list[dict]:
        """The config options as they now stand, remembered as what the client has."""
        try:
            options = self.config.options(self._coder())
        except Exception as err:  # never let a model quirk break the session
            log(f"could not build config options: {err!r}")
            options = []
        self._sent_options = options
        return options

    def _session_state(self) -> dict:
        state: dict[str, Any] = {"sessionId": self.session_id}
        options = self._current_options()
        if options:
            state["configOptions"] = options
            state["modes"] = self.config.modes(options)
        state["usage"] = self._usage_state()
        return state

    def _usage_state(self) -> dict[str, Any]:
        """Token, cost and context metrics for the desktop metrics menu.

        ``cache_hit_ratio`` is cached prompt tokens over sent prompt tokens
        (0..1), matching the rate the TUI reports; cached tokens are a subset of
        sent tokens.  Each field is read independently so one missing attribute
        cannot blank the whole payload.
        """
        usage: dict[str, Any] = {
            "cost": None,
            "tokens_sent": 0,
            "tokens_received": 0,
            "tokens_cached": 0,
            "cache_hit_ratio": None,
            "context_used": 0,
            "context_size": 0,
            "model": None,
            "stats": None,
        }
        coder = self._coder()
        if coder is None:
            return usage

        model = _active_model(coder)
        name = getattr(model, "name", None)
        usage["model"] = name
        usage["tokens_sent"] = _usage_int(coder, "total_tokens_sent")
        usage["tokens_received"] = _usage_int(coder, "total_tokens_received")
        usage["tokens_cached"] = _usage_int(coder, "total_cached_tokens")
        usage["cache_hit_ratio"] = _cache_hit_ratio(usage["tokens_cached"], usage["tokens_sent"])

        info = getattr(model, "info", None)
        info = info if isinstance(info, dict) else {}
        context_size = _usage_int(info, "max_input_tokens")
        if context_size <= 0:
            context_size = _usage_int(model, "max_chat_history_tokens")
        usage["context_size"] = context_size

        # Cost is only meaningful when the model carries pricing metadata; an
        # unpriced model reports null rather than a fabricated zero.
        total_cost = _usage_number(coder, "total_cost")
        priced = bool(info.get("input_cost_per_token") or info.get("output_cost_per_token"))
        if total_cost is not None and (total_cost > 0 or priced):
            usage["cost"] = total_cost

        if name:
            try:
                tokens, peak, per_minute = type(coder)._get_token_usage_stats(name)
                usage["stats"] = {
                    "tokens_last_minute": tokens,
                    "max_single_request": peak,
                    "requests_per_minute": per_minute,
                }
            except Exception as err:
                log(f"could not read token usage stats: {err!r}")

        messages = self._context_messages(coder)
        if messages and model is not None:
            try:
                usage["context_used"] = int(model.token_count(messages) or 0)
            except Exception as err:
                log(f"could not count context tokens: {err!r}")

        return usage

    def _context_messages(self, coder: Any) -> list[dict[str, Any]]:
        """The current conversation messages used to estimate context usage."""
        try:
            from cecli.helpers.conversation import ConversationService

            messages = ConversationService.get_manager(coder).get_messages_dict()
            if messages:
                return messages
        except Exception:
            pass
        try:
            return list(coder.done_messages) + list(coder.cur_messages)
        except Exception:
            return []

    def _sync_config(self) -> None:
        """Tell the client when a typed command (/model, /ask, ...) changed the options."""
        previous = self._sent_options
        options = self._current_options()
        if not options or options == previous:
            return
        self.send_update({"sessionUpdate": "config_option_update", "configOptions": options})
        mode = current_value(options, "mode")
        if mode is not None and mode != current_value(previous or [], "mode"):
            self.send_update({"sessionUpdate": "current_mode_update", "currentModeId": mode})

    def _announce_commands(self) -> None:
        from cecli.commands.utils.registry import CommandRegistry

        commands = []
        for name in sorted(CommandRegistry.list_commands()):
            if name in HIDDEN_COMMANDS:
                continue
            command = CommandRegistry.get_command(name)
            description = getattr(command, "DESCRIPTION", "") or name
            commands.append({"name": name, "description": description})
        self.send_update(
            {"sessionUpdate": "available_commands_update", "availableCommands": commands}
        )

    async def request(self, method: str, params: dict) -> Any:
        """Send a request to the client and wait for its result (None on error)."""
        self._next_request_id += 1
        request_id = self._next_request_id
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = (future, params.get("sessionId"))
        self.transport.send(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        try:
            return await future
        finally:
            self._pending.pop(request_id, None)

    def _cancel_pending_requests(self, session_id: str | None = None) -> None:
        """Answer outstanding requests as cancelled: all of them, or one session's."""
        for future, owner in self._pending.values():
            if not future.done() and session_id in (None, owner):
                future.set_result({"outcome": {"outcome": "cancelled"}})

    async def ask_permission(
        self, question: str, subject: str | None, options: list[dict], agent_uuid: str | None = None
    ) -> str | None:
        """Ask the client to approve something; returns the chosen optionId or None."""
        subagent = self.subagents.get(agent_uuid) if agent_uuid else None
        if subagent is not None:
            # A sub-agent may ask while the parent's turn is over
            if not subagent.running or subagent.cancelled:
                return None
            emitter, session_id = subagent.emitter, subagent.session_id
            self._send_subagent_state(subagent, {"state": "requires_action"})
        elif not self.in_prompt() or self.turn.cancelled:
            return None
        else:
            emitter, session_id = self.emitter, self.session_id
            self._emit_state(state=STATE_REQUIRES_ACTION)

        tool_call_id, synthetic = emitter.permission_target(question, subject)
        result = await self.request(
            "session/request_permission",
            {
                "sessionId": session_id,
                "toolCall": emitter.permission_prompt(tool_call_id, question),
                "options": options,
            },
        )
        if subagent is not None and subagent.running and not subagent.cancelled:
            self._send_subagent_state(subagent, {"state": "running"})
        elif subagent is None and self.in_prompt() and not self.turn.cancelled:
            self._emit_state(state=STATE_RUNNING)
        outcome = (result or {}).get("outcome") or {}
        choice = outcome.get("optionId") if outcome.get("outcome") == "selected" else None

        allowed = any(o["optionId"] == choice and o["kind"].startswith("allow") for o in options)
        emitter.permission_resolved(tool_call_id, synthetic, allowed)
        return choice

    # ── Sub-agents (the unstable ACP subagents RFD) ─────────────

    def emitter_for(self, agent_uuid: str | None) -> UpdateEmitter:
        """The emitter for output from the coder with this uuid."""
        subagent = self.subagents.get(agent_uuid) if agent_uuid else None
        return subagent.emitter if subagent is not None else self.emitter

    def subagent_event(self, agent_uuid: str, event: str, **details: Any) -> None:
        """Show a cecli sub-agent to the client as a child session.

        Clients that don't advertise the subagents capability see sub-agent
        output in the parent session instead, as before.
        """
        if not self.subagents_supported or self.session_id is None:
            return
        if event == "created":
            self._announce_subagent(agent_uuid, **details)
            return
        if event == "message":
            self._report_message(details.get("sender_uuid"), agent_uuid, details.get("text"))
            return

        subagent = self.subagents.get(agent_uuid)
        if subagent is None:
            return
        if event == "running":
            subagent.running, subagent.cancelled = True, False
            self._send_subagent_state(subagent, {"state": "running"})
        elif event == "idle":
            stop_reason = details.get("stop_reason") or "end_turn"
            subagent.emitter.finish_turn(cancelled=stop_reason == "cancelled")
            subagent.running = False
            self._cancel_pending_requests(subagent.session_id)
            state = {"state": "idle", "stopReason": stop_reason}
            if stop_reason == "error":
                state["error"] = {
                    "code": INTERNAL_ERROR,
                    "message": details.get("error") or "The sub-agent failed",
                }
            self._send_subagent_state(subagent, state)
        elif event == "removed":
            # Reaped: nothing left to cancel. The child's history stays with the client
            subagent.removed = True
            self.send_update(
                {
                    "sessionUpdate": "subagent_update",
                    "sessionId": subagent.session_id,
                    "capabilities": None,
                },
                subagent.parent_session_id,
            )

    def _announce_subagent(
        self,
        agent_uuid: str,
        parent_uuid: str | None = None,
        name: str | None = None,
        description: str | None = None,
        root: str | None = None,
        **_details: Any,
    ) -> None:
        if agent_uuid in self.subagents:
            return
        session_id = _new_session_id()
        parent_session_id = self._session_of(parent_uuid)
        emitter = UpdateEmitter(lambda update: self.send_update(update, session_id))
        if root:
            emitter.root = root

        update: dict[str, Any] = {
            "sessionUpdate": "subagent_update",
            "sessionId": session_id,
            "capabilities": {"cancel": {}},
        }
        if name:
            update["title"] = name
        if description:
            update["description"] = str(description)
        # The announcement goes out before anything that names the child
        self.send_update(update, parent_session_id)
        self.subagents[agent_uuid] = _Subagent(agent_uuid, session_id, parent_session_id, emitter)

    def _session_of(self, agent_uuid: str | None) -> str:
        """The session showing this coder: its own if it's a sub-agent, else the parent's."""
        subagent = self.subagents.get(agent_uuid) if agent_uuid else None
        return subagent.session_id if subagent is not None else self.session_id

    def _report_message(self, sender_uuid: str | None, recipient_uuid: str, text: Any) -> None:
        """A message between agents, as the sender sent it and as the recipient got it."""
        if not text:
            return
        sender, recipient = self._session_of(sender_uuid), self._session_of(recipient_uuid)
        if sender == recipient:
            return
        content = [{"type": "text", "text": str(text)}]
        for session_id in (sender, recipient):
            self._message_count += 1
            self.send_update(
                {
                    "sessionUpdate": "session_message",
                    "messageId": f"cecli-message-{self._message_count}",
                    "senderSessionId": sender,
                    "recipientSessionId": recipient,
                    "content": content,
                },
                session_id,
            )

    def _send_subagent_state(self, subagent: _Subagent, state: dict) -> None:
        self.send_update(
            {"sessionUpdate": "subagent_update", "sessionId": subagent.session_id, "state": state},
            subagent.parent_session_id,
        )

    def _cancel_subagent(self, session_id: Any) -> None:
        """``session/cancel`` on a child: stop that sub-agent's current work only."""
        subagent = next((s for s in self.subagents.values() if s.session_id == session_id), None)
        if subagent is None or subagent.removed or not subagent.running:
            return
        subagent.cancelled = True
        self._cancel_pending_requests(subagent.session_id)
        coder = self._coder()
        if coder is None:
            return
        from cecli.helpers.agents.service import AgentService

        # It reports the cancelled idle state itself once it has stopped
        AgentService.get_instance(coder).cancel_sub_agent(subagent.agent_uuid)

    # ── State helpers ─────────────────────────────────────────────────────

    def _require_coder(self) -> Any:
        coder = self._coder()
        if coder is None:
            raise AcpError(INTERNAL_ERROR, "cecli is not ready")
        return coder

    def _empty_state(self) -> dict[str, Any]:
        return {
            "activity": "idle",
            "subagents": [],
            "contextFiles": [],
            "skills": [],
            "mcpServers": [],
            "hooks": [],
            "workflows": [],
        }

    def _state_snapshot(self, coder: Any) -> dict[str, Any]:
        if self.in_prompt():
            activity = "running"
        elif self._pending:
            activity = "requires_action"
        else:
            activity = "idle"

        return {
            "activity": activity,
            "cwd": str(self.cwd or ""),
            "gitBranch": _git_branch_for(self.cwd),
            "subagents": self._subagent_state(coder),
            "contextFiles": self._context_state(coder),
            "skills": self._skills_state(coder),
            "mcpServers": self._mcp_state(coder),
            "hooks": self._hooks_state(coder),
            "workflows": self._workflow_state(coder),
            "usage": self._usage_state(),
        }

    def _subagent_state(self, coder: Any) -> list[dict[str, Any]]:
        from cecli.helpers.agents.service import AgentService

        service = AgentService.get_instance(coder)
        infos = {str(info.coder.uuid): info for info in service.sub_agents.values()}
        result: list[dict[str, Any]] = []

        for agent_uuid, subagent in self.subagents.items():
            info = infos.get(str(agent_uuid))
            info_coder = getattr(info, "coder", None) if info else None
            root = str(
                getattr(info_coder, "root", None) or getattr(subagent.emitter, "root", None) or ""
            )
            branch = _git_branch_for(root)
            result.append(
                {
                    "sessionId": subagent.session_id,
                    "parentSessionId": subagent.parent_session_id,
                    "cwd": root,
                    "gitBranch": branch,
                    "uuid": subagent.agent_uuid,
                    "parentUuid": getattr(info, "parent_uuid", None),
                    "name": getattr(info, "name", None) or subagent.agent_uuid,
                    "status": getattr(getattr(info, "status", None), "value", "running"),
                    "running": subagent.running,
                    "removed": subagent.removed,
                    "summary": getattr(info, "summary", None),
                    "contextFiles": self._context_state(info.coder) if info else [],
                }
            )

        announced = set(self.subagents)
        for agent_uuid, info in infos.items():
            if agent_uuid in announced:
                continue

            root = str(getattr(info.coder, "root", None) or "")
            branch = _git_branch_for(root)
            result.append(
                {
                    "sessionId": None,
                    "parentSessionId": None,
                    "cwd": root,
                    "gitBranch": branch,
                    "uuid": agent_uuid,
                    "parentUuid": info.parent_uuid,
                    "name": info.name,
                    "status": info.status.value,
                    "running": info.status.value == "running",
                    "removed": False,
                    "summary": info.summary,
                    "contextFiles": self._context_state(info.coder),
                }
            )

        return result

    def _context_state(self, coder: Any) -> list[dict[str, Any]]:
        root = self.cwd or os.getcwd()
        result: list[dict[str, Any]] = []
        groups = (
            (getattr(coder, "abs_fnames", set()), False),
            (getattr(coder, "abs_read_only_fnames", set()), True),
            (getattr(coder, "abs_read_only_stubs_fnames", set()), True),
        )

        for paths, read_only in groups:
            for path in sorted(paths):
                try:
                    relative = os.path.relpath(path, root)
                except ValueError:
                    relative = path
                result.append({"path": relative, "absolutePath": path, "readOnly": read_only})

        return result

    def _skills_state(self, coder: Any) -> list[dict[str, Any]]:
        manager = getattr(coder, "skills_manager", None)
        if manager is None:
            return []
        try:
            return manager.get_all_skills_info()
        except Exception:
            return []

    def _hooks_state(self, coder: Any) -> list[dict[str, Any]]:
        """Configured hooks as one flat list ordered by type then priority.

        Types follow ``HookType`` declaration order with unknown types last.
        """
        from cecli.hooks.service import HookService
        from cecli.hooks.types import HookType

        try:
            manager = HookService.get_manager(coder)
            all_hooks = manager.get_all_hooks()
        except Exception:
            return []

        result: list[dict[str, Any]] = []
        for hook_type, hooks in all_hooks.items():
            for hook in hooks:
                result.append(
                    {
                        "name": hook.name,
                        "type": getattr(hook.type, "value", hook_type),
                        "enabled": bool(hook.enabled),
                        "priority": hook.priority,
                        "description": getattr(hook, "description", None),
                    }
                )

        type_order = {hook_type.value: index for index, hook_type in enumerate(HookType)}
        unknown = len(type_order)
        result.sort(
            key=lambda item: (
                type_order.get(item["type"], unknown),
                item["priority"],
                str(item["name"]),
            )
        )
        return result

    def _mcp_state(self, coder: Any) -> list[dict[str, Any]]:
        manager = getattr(coder, "mcp_manager", None)
        if manager is None:
            return []

        result = []
        for server in getattr(manager, "servers", []):
            config = getattr(server, "config", {}) or {}
            result.append(
                {
                    "name": server.name,
                    "connected": bool(
                        server in getattr(manager, "connected_servers", set())
                        or getattr(server, "is_connected", False)
                    ),
                    "enabled": bool(config.get("enabled", True)),
                    "type": config.get("type") or ("stdio" if config.get("command") else "remote"),
                }
            )
        return sorted(result, key=lambda item: item["name"])

    def _workflow_state(self, coder: Any) -> list[dict[str, Any]]:
        from cecli.commands.workflow_helpers.common import workflows

        try:
            items = workflows(coder)
        except Exception:
            items = []

        return [
            {
                "name": wf.name,
                "description": wf.description,
                "schedule": wf.schedule,
                "enabled": wf.enabled,
                "tasks": len(wf.tasks),
                "sourcePath": wf.source_path,
            }
            for wf in items
        ]

    @staticmethod
    def _background_entry(command_key: str, info: dict[str, Any]) -> dict[str, Any]:
        """Convert a manager entry to the camelCase shape the desktop expects."""
        return {
            "key": command_key,
            "command": info.get("command") or "",
            "state": info.get("state") or ("running" if info.get("running") else "exited"),
            "running": bool(info.get("running")),
            "persist": bool(info.get("persist")),
            "continuedInBackground": bool(info.get("continued_in_background")),
            "pid": info.get("pid"),
            "cols": info.get("cols", 100),
            "rows": info.get("rows", 30),
            "pty": bool(info.get("pty")),
            "seq": info.get("seq", 0),
            "startSeq": info.get("start_seq", info.get("startSeq", 0)),
            "exitCode": info.get("exit_code", info.get("exitCode")),
            "signal": info.get("signal"),
            "endedAt": info.get("ended_at", info.get("endedAt")),
            "needsInput": bool(info.get("needs_input", info.get("needsInput"))),
            "lastPrompt": info.get("last_prompt", info.get("lastPrompt")),
            "inputOwner": info.get("input_owner", info.get("inputOwner")),
            "consumedAt": info.get("consumed_at", info.get("consumedAt")),
            "bufferSize": info.get("buffer_size") or 0,
            "pages": info.get("pages") or 0,
            "totalChars": info.get("total_chars") or 0,
            "startTime": info.get("start_time", info.get("startedAt")),
            "endTime": info.get("end_time", info.get("endedAt")),
            "duration": info.get("duration"),
        }


PATH_COMPLETION_COMMANDS = {"/add", "/read-only", "/read-only-stub", "/rules", "/load", "/save"}
MAX_COMPLETIONS = 50


def _conversation_history(coder: Any, limit: int = 400) -> list[dict[str, Any]]:
    """Normalise a coder's CUR/DONE messages into a transcript-replay payload."""
    from cecli.helpers.conversation.service import ConversationService
    from cecli.helpers.conversation.tags import MessageTag

    try:
        manager = ConversationService.get_manager(coder)
        messages = manager.get_messages()
    except Exception:
        return []

    tags = (MessageTag.CUR.value, MessageTag.DONE.value)
    history: list[dict[str, Any]] = []

    for message in messages:
        if message.tag not in tags:
            continue

        data = message.to_dict()
        role = data.get("role")
        if role not in ("user", "assistant", "tool"):
            continue

        content = data.get("content")
        content = content if isinstance(content, str) else ("" if content is None else str(content))
        tool_calls = data.get("tool_calls") or []
        if not content and not tool_calls:
            continue

        entry: dict[str, Any] = {"role": role, "content": content}
        reasoning = data.get("reasoning_content") or data.get("reasoning")
        if reasoning:
            entry["reasoning"] = str(reasoning)
        if tool_calls:
            entry["toolCalls"] = [
                _history_tool_call(tool_call) for tool_call in tool_calls if tool_call
            ]
        if data.get("tool_call_id"):
            entry["toolCallId"] = data["tool_call_id"]

        history.append(entry)

    return history[-limit:]


MAX_DIFF_CHARS = 40_000


def _conversation_diffs(coder: Any) -> list[dict[str, Any]]:
    """Extract file-edit diffs from a coder's DIFFS messages for replay.

    Each entry is ``{"file": relative path, "diff": raw unified diff}``.  The
    diffs also travel live as ``sessionUpdate: diff`` updates; replay dedupes
    identical payloads so a reconnect cannot double-render them.
    """
    from cecli.helpers.conversation.service import ConversationService
    from cecli.helpers.conversation.tags import MessageTag

    try:
        manager = ConversationService.get_manager(coder)
        messages = manager.get_messages()
    except Exception:
        return []

    diffs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for message in messages:
        if message.tag != MessageTag.DIFFS.value:
            continue

        data = message.to_dict()
        content = data.get("content")
        parsed = _parse_diff_message(content if isinstance(content, str) else str(content))
        if parsed is None:
            continue

        file_name, diff = parsed
        if (file_name, diff) in seen:
            continue

        seen.add((file_name, diff))
        if len(diff) > MAX_DIFF_CHARS:
            diff = diff[:MAX_DIFF_CHARS].rstrip() + "\n...(truncated)"
        diffs.append({"file": file_name, "diff": diff})

    return diffs


def _parse_diff_message(content: str) -> tuple[str, str] | None:
    """Split a DIFFS message into ``(relative path, raw diff)``."""
    import json

    if not content:
        return None

    header, separator, body = content.partition("\n\n")
    if not separator:
        return None

    file_name = header.split(" has been updated.", 1)[0].strip()
    body = body.strip("\n")

    if body.lstrip().startswith("{"):
        try:
            payload = json.loads(body)
        except ValueError:
            payload = None

        if isinstance(payload, dict):
            file_name = str(payload.get("file_name") or file_name).strip()
            body = str(payload.get("prefixed_diff") or "")

    if not file_name or not body:
        return None

    return file_name, body


def _history_tool_call(tool_call: Any) -> dict[str, Any]:
    """Reduce one provider tool call to the id/name/arguments the UI needs."""
    if isinstance(tool_call, dict):
        function = tool_call.get("function") or {}
        return {
            "id": tool_call.get("id"),
            "name": function.get("name") or tool_call.get("name") or "",
            "arguments": function.get("arguments") or tool_call.get("arguments") or "",
        }

    function = getattr(tool_call, "function", None)
    return {
        "id": getattr(tool_call, "id", None),
        "name": getattr(function, "name", "") or "",
        "arguments": getattr(function, "arguments", "") or "",
    }


def _complete(coder: Any, text: str) -> dict[str, Any]:
    """Return completion candidates for the desktop composer.

    Mirrors the TUI's slash-command, argument, `@` mention and path
    completion behavior closely enough that the desktop and terminal share
    the same command surface.
    """
    commands = getattr(coder, "commands", None)
    suggestions: list[str] = []
    descriptions: dict[str, str] = {}
    start = 0

    if "@" in text:
        at_index = text.rfind("@")
        prefix = text[at_index + 1 :]
        start = at_index + 1
        suggestions = _mention_completions(coder, prefix)
    elif text.startswith("/"):
        parts = text.split(maxsplit=1)
        cmd_part = parts[0]

        if len(parts) == 1 and not text.endswith(" "):
            suggestions, descriptions = _command_completions(commands, cmd_part)
        else:
            arg_prefix = "" if text.endswith(" ") else text.rsplit(maxsplit=1)[-1]
            start = len(text) - len(arg_prefix)
            if cmd_part in PATH_COMPLETION_COMMANDS:
                suggestions = _path_completions(coder, arg_prefix)
            else:
                suggestions = _argument_completions(commands, coder, text, cmd_part, arg_prefix)
    else:
        words = text.rsplit(maxsplit=1)
        last = words[-1] if words else ""
        if "/" in last:
            start = len(text) - len(last)
            suggestions = _path_completions(coder, last)

    unique = []
    seen = set()
    for item in suggestions:
        value = str(item)
        if value and value not in seen:
            seen.add(value)
            unique.append(value)

    return {
        "suggestions": unique[:MAX_COMPLETIONS],
        "descriptions": {
            key: value for key, value in descriptions.items() if key in unique[:MAX_COMPLETIONS]
        },
        "start": start,
    }


def _command_completions(commands: Any, cmd_part: str) -> tuple[list[str], dict[str, str]]:
    if commands is None:
        return [], {}

    from cecli.commands.utils.registry import CommandRegistry

    all_commands = commands.get_commands()
    if cmd_part == "/":
        matches = all_commands
    else:
        starts_with = [item for item in all_commands if item.startswith(cmd_part)]
        contains = [
            item for item in all_commands if cmd_part[1:] in item and not item.startswith(cmd_part)
        ]
        matches = starts_with + contains

    descriptions = {}
    for item in matches:
        name = item[1:]
        if name in HIDDEN_COMMANDS:
            continue
        description = CommandRegistry.get_command_description(name)
        if description:
            descriptions[item] = description

    return [item for item in matches if item[1:] not in HIDDEN_COMMANDS], descriptions


def _argument_completions(
    commands: Any, coder: Any, text: str, cmd_name: str, arg_prefix: str
) -> list[str]:
    if commands is None:
        return []

    try:
        if commands.uses_full_args_completion(cmd_name):
            nested_text = text[len(cmd_name) :].lstrip()
            values = commands.get_completions(cmd_name, args=nested_text, coder=coder)
        else:
            values = commands.get_completions(cmd_name, args=arg_prefix, coder=coder)
    except Exception:
        return []

    if not values:
        return []

    exempt = {"/model", "/models", "/agent-model", "/editor-model", "/weak-model"}
    lowered = arg_prefix.lower()
    if arg_prefix and cmd_name not in exempt:
        return [str(item) for item in values if lowered in str(item).lower()]
    return [str(item) for item in values]


def _mention_completions(coder: Any, prefix: str) -> list[str]:
    values = _path_completions(coder, prefix)
    try:
        values.extend(coder.get_inchat_relative_files())
    except Exception:
        pass
    return values


def _path_completions(coder: Any, prefix: str) -> list[str]:
    """Prefix then fuzzy file lookup under the coder's root."""
    from cecli.helpers.file_system import FileSystemService

    root = getattr(coder, "root", None) or os.getcwd()
    try:
        fs = getattr(coder, "fs", None) or FileSystemService.for_root(
            str(root), repo=getattr(coder, "repo", None)
        )
        if prefix:
            matches = fs.list_prefix(prefix) if fs.trie else []
            if not matches:
                matches = fs.search(prefix, threshold=0.1)
            if matches:
                return matches
    except Exception:
        pass

    return _filesystem_completions(str(root), prefix)


def _filesystem_completions(root: str, prefix: str) -> list[str]:
    if "/" in prefix:
        dir_part, file_part = prefix.rsplit("/", 1)
        search_dir = os.path.join(root, dir_part)
        path_prefix = dir_part + "/"
    else:
        search_dir = root
        file_part = prefix
        path_prefix = ""

    completions = []
    try:
        for entry in os.scandir(search_dir):
            if file_part.lower() not in entry.name.lower():
                continue
            suffix = "/" if entry.is_dir() else ""
            completions.append(path_prefix + entry.name + suffix)
    except OSError:
        pass

    return sorted(completions)


def _require_cwd(params: dict) -> str:
    cwd = params.get("cwd")
    if not isinstance(cwd, str) or not os.path.isabs(cwd):
        raise AcpError(INVALID_PARAMS, "session/new requires an absolute cwd")
    if not os.path.isdir(cwd):
        raise AcpError(INVALID_PARAMS, f"Not a directory: {cwd}")
    return cwd


def _new_session_id() -> str:
    return uuid.uuid4().hex


def _log_user_input(coder: Any, text: str) -> None:
    """Record a client prompt in the same chat history the TUI writes."""
    io = getattr(coder, "io", None)
    log = getattr(io, "log_user_input", None)

    if callable(log):
        log(text)
        return

    user_input = getattr(io, "user_input", None)

    if callable(user_input):
        user_input(text)


def _add_mentions(coder: Any, paths: list[str]) -> None:
    """Put @-mentioned files in the chat, as cecli would for /add."""
    root = os.path.realpath(coder.root)
    for path in paths:
        if not os.path.isfile(path):
            continue
        real = os.path.realpath(path)
        if real in coder.abs_fnames or real in coder.abs_read_only_fnames:
            continue
        try:
            inside = os.path.commonpath([root, real]) == root
        except ValueError:  # different drives
            inside = False
        if inside:
            rel = coder.get_rel_fname(real)
            coder.add_rel_fname(rel)
            coder.io.tool_output(f"Added {rel} to the chat")
        else:
            coder.abs_read_only_fnames.add(real)
            coder.io.tool_output(f"Added {real} to the chat (read-only)")


def _active_model(coder: Any) -> Any:
    """The model currently answering for ``coder``, if one can be resolved."""
    get_active_model = getattr(coder, "get_active_model", None)
    if callable(get_active_model):
        try:
            model = get_active_model()
        except Exception as err:
            log(f"could not resolve the active model: {err!r}")
        else:
            if model is not None:
                return model

    return getattr(coder, "main_model", None)


def _cache_hit_ratio(cached: int, sent: int) -> float | None:
    """Cached prompt tokens over sent prompt tokens, clamped to 0..1."""
    if sent <= 0:
        return None

    return min(max(cached / sent, 0.0), 1.0)


def _usage_int(source: Any, name: str) -> int:
    """Read an attribute or mapping key as a non-negative int, defaulting to 0."""
    value = _usage_value(source, name)
    if isinstance(value, bool) or value is None:
        return 0

    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0

    return int(number) if math.isfinite(number) and number > 0 else 0


def _usage_number(source: Any, name: str) -> float | None:
    """Read an attribute or mapping key as a finite float, or None."""
    value = _usage_value(source, name)
    if isinstance(value, bool) or value is None:
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    return number if math.isfinite(number) else None


def _usage_value(source: Any, name: str) -> Any:
    """Read ``name`` from a mapping or an object without leaking exceptions."""
    if isinstance(source, dict):
        return source.get(name)

    try:
        return getattr(source, name, None)
    except Exception:
        return None


def _git_branch_for(cwd: Any) -> str:
    """Return the checked-out branch under ``cwd`` without shelling out.

    Reads ``.git/HEAD`` directly, walking up parent directories. Worktree ``.git``
    files (``gitdir: ...``) are followed, and a detached HEAD yields its short sha.
    Returns an empty string when no readable repository is found.
    """
    try:
        if not cwd:
            return ""

        git_dir = _git_dir_for(os.path.abspath(str(cwd)))
        if not git_dir:
            return ""

        with open(os.path.join(git_dir, "HEAD"), "r", encoding="utf-8", errors="replace") as handle:
            head = handle.read().strip()
    except (OSError, TypeError, ValueError):
        return ""

    if not head:
        return ""

    if head.startswith("ref:"):
        ref = head[4:].strip()
        prefix = "refs/heads/"
        return ref[len(prefix) :] if ref.startswith(prefix) else ref.rpartition("/")[2]

    return head[:7]


def _git_dir_for(start: str) -> str:
    """Find the ``.git`` directory for ``start``, following parent dirs and worktrees."""
    current = start

    while current:
        candidate = os.path.join(current, ".git")

        if os.path.isdir(candidate):
            return candidate

        if os.path.isfile(candidate):
            try:
                with open(candidate, "r", encoding="utf-8", errors="replace") as handle:
                    first = handle.readline().strip()
            except OSError:
                return ""

            if first.startswith("gitdir:"):
                git_dir = first[len("gitdir:") :].strip()
                if not os.path.isabs(git_dir):
                    git_dir = os.path.normpath(os.path.join(current, git_dir))
                return git_dir

        parent = os.path.dirname(current)
        if parent == current:
            break

        current = parent

    return ""
