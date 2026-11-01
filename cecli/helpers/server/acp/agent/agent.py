"""AcpAgent: the agent side of the Agent Client Protocol (ACP) v1.

One process serves one project. ``bootstrap()`` runs before ``main_async`` so
the first ``session/new`` can pick the working directory the coder is built in;
its response is deferred until the coder first asks for input. From then on the
coder's normal linear run loop drives each turn: a turn starts when
``next_input`` hands the loop a prompt and ends when the loop asks again.
"""

from __future__ import annotations

import asyncio
import os
import sys
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
        self._dispatcher = loop.create_task(self._dispatch())

    def shutdown(self) -> None:
        """Answer whatever is still waiting before the process exits."""
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
            # Flush while the turn is still current so the updates go out
            self.emitter.finish_turn(cancelled=turn.cancelled)
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
        if self.in_prompt():
            self.send_update(update)
        elif update.get("sessionUpdate") == "agent_message_chunk":
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
        return state

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


def _require_cwd(params: dict) -> str:
    cwd = params.get("cwd")
    if not isinstance(cwd, str) or not os.path.isabs(cwd):
        raise AcpError(INVALID_PARAMS, "session/new requires an absolute cwd")
    if not os.path.isdir(cwd):
        raise AcpError(INVALID_PARAMS, f"Not a directory: {cwd}")
    return cwd


def _new_session_id() -> str:
    return uuid.uuid4().hex


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
