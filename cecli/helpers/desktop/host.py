"""Host the desktop HTTP bridge inside the cecli ACP process."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from typing import Any

from cecli.helpers.server.acp.agent.transport import EOF, InProcessTransport

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_MAX_SESSIONS = 8

_VALUE_FLAGS = {
    "--desktop-bridge-host": "host",
    "--desktop-bridge-port": "port",
    "--desktop-bridge-workspace": "workspace",
    "--desktop-bridge-static-root": "static_root",
    "--desktop-bridge-install-root": "install_root",
    "--desktop-bridge-cecli": "cecli",
    "--desktop-bridge-token": "token",
    "--desktop-bridge-max-sessions": "max_sessions",
    "--desktop-bridge-terminal-shell": "terminal_shell",
}
_BOOL_FLAGS = {
    "--desktop-bridge-open": "open_browser",
    "--desktop-bridge-no-terminal": "no_terminal",
}


class DesktopAgentLink:
    """The bridge side of an in-process ACP transport.

    The agent may run on another thread and event loop.  ``send`` hands client
    messages to the agent through the transport, and ``receive`` yields the
    agent's messages after hopping back onto the bridge loop.
    """

    def __init__(self) -> None:
        self.transport = InProcessTransport(self._deliver)
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._incoming: asyncio.Queue | None = None
        self._backlog: list[Any] = []

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            self._loop = loop
            self._incoming = asyncio.Queue()
            for message in self._backlog:
                self._incoming.put_nowait(message)
            self._backlog.clear()

    async def send(self, message: dict[str, Any]) -> None:
        self.transport.deliver(message)

    async def receive(self) -> Any:
        assert self._incoming is not None
        return await self._incoming.get()

    async def close(self) -> None:
        self.transport.deliver(EOF)

    def _deliver(self, message: Any) -> None:
        with self._lock:
            loop = self._loop
            incoming = self._incoming
            if loop is None or incoming is None:
                self._backlog.append(message)
                return

        try:
            loop.call_soon_threadsafe(incoming.put_nowait, message)
        except RuntimeError:
            with self._lock:
                self._backlog.append(message)


def parse_desktop_args(argv: list[str]) -> tuple[dict[str, Any] | None, list[str]]:
    """Read ``--desktop-bridge`` flags and return the remaining CLI arguments."""
    options: dict[str, Any] = {}
    rest: list[str] = []
    index = 0
    enabled = False
    while index < len(argv):
        arg = argv[index]
        if arg == "--desktop-bridge":
            enabled = True
        elif arg in _VALUE_FLAGS:
            index += 1
            if index >= len(argv):
                raise SystemExit(f"{arg} requires a value")
            options[_VALUE_FLAGS[arg]] = argv[index]
        elif arg in _BOOL_FLAGS:
            options[_BOOL_FLAGS[arg]] = True
        else:
            rest.append(arg)
            index += 1
            continue
        index += 1

    if not enabled:
        return None, argv

    parsed = {
        "host": options.get("host", DEFAULT_HOST),
        "port": int(options.get("port", DEFAULT_PORT)),
        "workspace": os.path.abspath(os.path.expanduser(options.get("workspace") or os.getcwd())),
        "static_root": options.get("static_root"),
        "install_root": options.get("install_root"),
        "cecli": options.get("cecli"),
        "token": options.get("token") or os.environ.get("CECLI_DESKTOP_TOKEN") or "",
        "max_sessions": max(1, int(options.get("max_sessions", DEFAULT_MAX_SESSIONS))),
        "open_browser": bool(options.get("open_browser")),
        "terminal_enabled": not options.get("no_terminal", False),
        "terminal_shell": (
            options.get("terminal_shell") or os.environ.get("CECLI_DESKTOP_TERMINAL_SHELL")
        ),
    }
    return parsed, rest


def start_desktop_bridge(
    link: DesktopAgentLink,
    options: dict[str, Any],
    stop_event: threading.Event | None = None,
) -> threading.Thread:
    """Run the HTTP bridge on a daemon thread until the process exits."""
    from cecli.helpers.desktop.bridge import ServerConfig, run_server

    config = ServerConfig(
        options["host"],
        options["port"],
        options["workspace"],
        options.get("cecli") or _cecli_executable(),
        [],
        options["open_browser"],
        options["token"],
        options["max_sessions"],
        options["terminal_enabled"],
        options["terminal_shell"],
        options["static_root"],
        options["install_root"],
    )

    def serve() -> None:
        try:
            _run_bridge_loop(
                run_server(
                    config,
                    connection_factory=lambda: link,
                    stop_event=stop_event,
                    handle_signals=False,
                )
            )
        except Exception as error:
            print(f"desktop bridge stopped: {error}", file=sys.stderr, flush=True)

    thread = threading.Thread(target=serve, name="cecli-desktop-bridge", daemon=True)
    thread.start()
    return thread


def _run_bridge_loop(coroutine: Any) -> None:
    """Run the bridge on a loop that is allowed to spawn ACP subprocesses.

    ``cecli.main`` installs ``WindowsSelectorEventLoopPolicy`` for the ACP stdio
    loop, and selector loops on Windows cannot start subprocesses.  Every
    workspace session beyond the embedded one would then fail to spawn and sit
    in ``starting`` forever, so the bridge thread gets its own Proactor loop.
    """
    loop_type = getattr(asyncio, "ProactorEventLoop", None) if os.name == "nt" else None

    if loop_type is None:
        asyncio.run(coroutine)
        return

    loop = loop_type()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(coroutine)
    finally:
        try:
            loop.close()
        finally:
            asyncio.set_event_loop(None)


def _cecli_executable() -> str:
    argv0 = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if _is_executable_file(argv0):
        return argv0

    from cecli.helpers.desktop.bridge import default_cecli

    suffix = ".exe" if os.name == "nt" else ""
    return default_cecli(suffix) or "cecli"


def _is_executable_file(path: str) -> bool:
    """Return True when *path* can be spawned directly as a program.

    ``sys.argv[0]`` is a ``.py`` script when the bridge is hosted inside
    ``desktop/server.py``; ``os.access(..., os.X_OK)`` still reports that as
    executable on Windows, but spawning it raises ``WinError 193`` ("%1 is not
    a valid Win32 application"), which silently killed every extra session.
    """
    if not path or not os.path.isfile(path):
        return False
    extension = os.path.splitext(path)[1].lower()
    if os.name == "nt":
        return extension in {".exe", ".cmd", ".bat", ".com"}
    return os.access(path, os.X_OK) and extension not in {".py", ".pyw"}
