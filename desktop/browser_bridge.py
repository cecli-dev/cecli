"""Drive an installed Chromium browser over CDP and mirror it as JPEG frames.

Most sites refuse to be framed or drop their cookies inside a cross-site
iframe, so the desktop UI cannot embed them directly. This module launches (or
attaches to) a real Chrome, Edge, Chromium or Brave with a dedicated profile,
speaks the DevTools Protocol over a standard-library asyncio WebSocket, and
fans one shared screencast out to any number of SSE subscribers. Pointer, wheel,
text and key events from the UI are forwarded as CDP input commands.

Only the Python standard library is used, and all diagnostic HTTP/WebSocket
traffic stays on loopback (or the Windows host loopback under WSL).
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

DEFAULT_PORT = 9222
PORT_CANDIDATES = (9222, 9223, 9224, 9225, 9334)
PORT_FILE = ".cecli-browser-port"
FRAME_INTERVAL = 0.04
FRAME_QUALITY = 70
MAX_DPR = 1.5
MAX_CAST_WIDTH = 2048
MAX_CAST_HEIGHT = 2048
MAX_FRAME_QUEUE = 4
TAB_POLL_SECONDS = 1.5
SCROLL_POLL_SECONDS = 0.4
HEALTH_TIMEOUT = 1.5
LAUNCH_TIMEOUT = 30.0
CDP_TIMEOUT = 30.0
DEFAULT_VIEWPORT = {"width": 1280, "height": 900, "dpr": 1.0}

ALLOWED_SCHEMES = ("http", "https", "about", "file", "chrome", "data")
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")

MOUSE_BUTTONS = ("none", "left", "middle", "right", "back", "forward")

MODIFIER_BITS = {
    "alt": 1,
    "ctrl": 2,
    "control": 2,
    "meta": 4,
    "cmd": 4,
    "command": 4,
    "win": 4,
    "shift": 8,
}

KEY_CODES = {
    "enter": (13, "Enter"),
    "return": (13, "Enter"),
    "backspace": (8, "Backspace"),
    "delete": (46, "Delete"),
    "tab": (9, "Tab"),
    "escape": (27, "Escape"),
    "esc": (27, "Escape"),
    "arrowup": (38, "ArrowUp"),
    "up": (38, "ArrowUp"),
    "arrowdown": (40, "ArrowDown"),
    "down": (40, "ArrowDown"),
    "arrowleft": (37, "ArrowLeft"),
    "left": (37, "ArrowLeft"),
    "arrowright": (39, "ArrowRight"),
    "right": (39, "ArrowRight"),
    "home": (36, "Home"),
    "end": (35, "End"),
    "pageup": (33, "PageUp"),
    "pagedown": (34, "PageDown"),
    "space": (32, "Space"),
    " ": (32, "Space"),
}

BROWSER_COMMANDS = (
    "google-chrome",
    "google-chrome-stable",
    "chrome",
    "microsoft-edge",
    "microsoft-edge-stable",
    "msedge",
    "chromium",
    "chromium-browser",
    "brave-browser",
    "brave",
)

WINDOW_MODE_ENV = "CECLI_BROWSER_WINDOW_MODE"
WINDOW_MODES = ("auto", "offscreen", "minimized", "headless", "visible")
WINDOW_SIZE_FLAG = "--window-size=1280,900"
OFFSCREEN_POSITION_FLAG = "--window-position=-32000,-32000"

LAUNCH_FLAGS = (
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-background-timer-throttling",
    "--disable-features=CalculateNativeWinOcclusion,Translate",
)


class BrowserError(Exception):
    """A browser API failure, carrying the HTTP status it should become."""

    def __init__(self, message: str, status: int = 503) -> None:
        super().__init__(message)
        self.status = status


class _CdpSocket:
    """One RFC6455 client connection to a single CDP target."""

    def __init__(self, url: str) -> None:
        parsed = urllib.parse.urlsplit(url)
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 80
        self.path = parsed.path or "/"
        if parsed.query:
            self.path = f"{self.path}?{parsed.query}"
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.closed = False
        self._write_lock: asyncio.Lock | None = None

    async def connect(self) -> None:
        """Perform the WebSocket handshake against the CDP endpoint."""

        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), 10.0
            )
        except (OSError, asyncio.TimeoutError) as err:
            raise BrowserError(f"could not connect to the browser debugger: {err}") from err

        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.writer.write(request.encode("latin-1"))
        await self.writer.drain()
        try:
            head = await asyncio.wait_for(self.reader.readuntil(b"\r\n\r\n"), 10.0)
        except (
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
            asyncio.TimeoutError,
        ) as err:
            raise BrowserError(f"browser handshake failed: {err}") from err

        status_line = head.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
        if " 101 " not in status_line:
            raise BrowserError(f"browser rejected the WebSocket handshake: {status_line}")

    def _lock(self) -> asyncio.Lock:
        if self._write_lock is None:
            self._write_lock = asyncio.Lock()
        return self._write_lock

    async def send_text(self, text: str) -> None:
        """Send one masked text frame."""

        await self._write_frame(0x1, text.encode("utf-8"))

    async def send_pong(self, payload: bytes) -> None:
        await self._write_frame(0xA, payload)

    async def _write_frame(self, opcode: int, payload: bytes) -> None:
        if self.closed or self.writer is None:
            raise BrowserError("the browser debugger connection is closed")
        mask = os.urandom(4)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        length = len(payload)
        header = bytearray([0x80 | opcode])
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(length.to_bytes(2, "big"))
        else:
            header.append(0x80 | 127)
            header.extend(length.to_bytes(8, "big"))
        async with self._lock():
            try:
                self.writer.write(bytes(header) + mask + masked)
                await self.writer.drain()
            except (ConnectionError, OSError) as err:
                self.closed = True
                raise BrowserError("the browser debugger connection was lost") from err

    async def read_message(self) -> dict[str, Any] | None:
        """Read one complete JSON message, handling control and continuation frames."""

        fragments: list[bytes] = []
        fragmented = False
        while True:
            frame = await self._read_frame()
            if frame is None:
                return None
            fin, opcode, payload = frame
            if opcode == 0x8:
                await self._reply_close(payload)
                return None
            if opcode == 0x9:
                await self.send_pong(payload)
                continue
            if opcode == 0xA:
                continue
            if opcode in (0x1, 0x2):
                if fin:
                    return _decode_json(payload)
                fragments = [payload]
                fragmented = True
                continue
            if opcode == 0x0 and fragmented:
                fragments.append(payload)
                if fin:
                    fragmented = False
                    message = b"".join(fragments)
                    fragments = []
                    return _decode_json(message)
        return None

    async def _reply_close(self, payload: bytes) -> None:
        if self.writer is None:
            return
        try:
            await self._write_frame(0x8, payload[:125])
        except BrowserError:
            pass
        self.closed = True

    async def _read_frame(self) -> tuple[bool, int, bytes] | None:
        if self.closed or self.reader is None:
            return None
        try:
            head = await self.reader.readexactly(2)
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            return None
        first, second = head
        fin = bool(first & 0x80)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        try:
            if length == 126:
                length = int.from_bytes(await self.reader.readexactly(2), "big")
            elif length == 127:
                length = int.from_bytes(await self.reader.readexactly(8), "big")
            if length > 64 * 1024 * 1024:
                return None
            mask = await self.reader.readexactly(4) if masked else b""
            payload = await self.reader.readexactly(length) if length else b""
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            return None
        if masked:
            payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        return fin, opcode, payload

    async def close(self) -> None:
        """Close the TCP connection without waiting for a peer handshake."""

        if self.closed:
            return
        self.closed = True
        writer = self.writer
        if writer is None:
            return
        try:
            writer.close()
            await writer.wait_closed()
        except (ConnectionError, OSError, RuntimeError):
            pass


class _CdpSession:
    """One live CDP session against one page target."""

    def __init__(self, url: str, target_id: str) -> None:
        self.socket = _CdpSocket(url)
        self.target_id = target_id
        self.closed = False
        self._next_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._listeners: dict[str, set[Callable[[dict[str, Any]], None]]] = defaultdict(set)
        self._close_callbacks: set[Callable[[], None]] = set()
        self._reader_task: asyncio.Task[Any] | None = None

    async def open(self) -> None:
        await self.socket.connect()
        self._reader_task = asyncio.create_task(self._reader())
        await self.send("Page.enable")
        await self.send("Runtime.enable")

    def on(self, method: str, callback: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        """Subscribe to one CDP event; returns an unsubscribe function."""

        self._listeners[method].add(callback)

        def unsubscribe() -> None:
            self._listeners[method].discard(callback)

        return unsubscribe

    def on_close(self, callback: Callable[[], None]) -> Callable[[], None]:
        self._close_callbacks.add(callback)
        return lambda: self._close_callbacks.discard(callback)

    async def send(
        self, method: str, params: dict[str, Any] | None = None, timeout: float = CDP_TIMEOUT
    ) -> dict[str, Any]:
        """Send one CDP command and return its result object."""

        if self.closed:
            raise BrowserError("the browser debugger connection is closed")

        self._next_id += 1
        request_id = self._next_id
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self.socket.send_text(
                json.dumps({"id": request_id, "method": method, "params": params or {}})
            )
            message = await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError as err:
            raise BrowserError(f"CDP command timed out: {method}") from err
        finally:
            self._pending.pop(request_id, None)

        if "error" in message:
            error = message.get("error") or {}
            text = error.get("message") if isinstance(error, dict) else str(error)
            raise BrowserError(str(text or f"{method} failed"))
        result = message.get("result")
        return result if isinstance(result, dict) else {}

    async def _reader(self) -> None:
        try:
            while True:
                message = await self.socket.read_message()
                if message is None:
                    break
                request_id = message.get("id")
                if isinstance(request_id, int) and request_id in self._pending:
                    future = self._pending[request_id]
                    if not future.done():
                        future.set_result(message)
                    continue
                method = message.get("method")
                if isinstance(method, str):
                    self._dispatch(method, message.get("params") or {})
        except (BrowserError, ConnectionError, OSError):
            pass
        finally:
            self._mark_closed()

    def _dispatch(self, method: str, params: Any) -> None:
        if not isinstance(params, dict):
            return
        for callback in list(self._listeners.get(method, ())):
            try:
                callback(params)
            except Exception:
                continue

    def _mark_closed(self) -> None:
        if self.closed:
            return
        self.closed = True
        for future in self._pending.values():
            if not future.done():
                future.set_exception(BrowserError("the browser debugger connection was lost"))
        for callback in list(self._close_callbacks):
            try:
                callback()
            except Exception:
                continue

    async def close(self) -> None:
        if self.closed:
            await self.socket.close()
            return
        self.closed = True
        task = self._reader_task
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        await self.socket.close()


class BrowserBridge:
    """Supervise one attached real browser and its shared screencast."""

    def __init__(
        self,
        executable: str | None = None,
        profile: str | os.PathLike[str] | None = None,
        port: int | None = None,
        window_mode: str | None = None,
    ) -> None:
        self._executable = os.path.expanduser(executable) if executable else None
        self._requested_window_mode = window_mode
        profile_value = (
            profile
            or os.environ.get("CECLI_BROWSER_PROFILE")
            or os.path.join("~", ".cecli", "desktop", "browser-profile")
        )
        self._profile = Path(os.path.expanduser(str(profile_value)))
        env_port = os.environ.get("CECLI_BROWSER_CDP_PORT")
        self._port_explicit = port is not None or bool(env_port)
        try:
            self._preferred_port = int(port if port is not None else env_port or DEFAULT_PORT)
        except (TypeError, ValueError):
            self._preferred_port = DEFAULT_PORT
        self._port = self._read_saved_port() or self._preferred_port

        self._host = "127.0.0.1"
        self._process: subprocess.Popen[Any] | None = None
        self._window_mode: str | None = None
        self._session: _CdpSession | None = None
        self._target_id: str | None = None
        self._session_unsubs: list[Callable[[], None]] = []
        self._url = "about:blank"
        self._title = ""
        self._error: str | None = None
        self._viewport = dict(DEFAULT_VIEWPORT)
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._last_frame: dict[str, Any] | None = None
        self._frame_count = 0
        self._tabs: list[dict[str, Any]] = []
        self._tabs_signature: tuple[Any, ...] | None = None
        self._tab_task: asyncio.Task[Any] | None = None
        self._scroll: dict[str, int] = {"x": 0, "y": 0, "maxX": 0, "maxY": 0}
        self._scroll_known = False
        self._scroll_signature: tuple[int, ...] | None = None
        self._scroll_task: asyncio.Task[Any] | None = None
        self._cast_running = False
        self._cast_session: _CdpSession | None = None
        self._cast_unsubs: list[Callable[[], None]] = []
        self._next_ack_at = 0.0
        self._ack_tasks: set[asyncio.Task[Any]] = set()
        self._session_lock: asyncio.Lock | None = None
        self._cast_lock: asyncio.Lock | None = None
        self._tab_lock: asyncio.Lock | None = None

    def snapshot(self) -> dict[str, Any]:
        """Cheap, never-raising state for the UI."""

        try:
            executable = self._executable or find_browser()
            running = bool(
                (self._session is not None and not self._session.closed)
                or (self._process is not None and self._process.poll() is None)
            )
            return {
                "available": bool(executable),
                "running": running,
                "browser": browser_name(executable) if executable else None,
                "executable": executable,
                "windowMode": (
                    self._window_mode
                    or _resolve_window_mode(executable, self._requested_window_mode)
                ),
                "profile": str(self._profile),
                "port": self._port,
                "cdpUrl": f"http://{self._host}:{self._port}",
                "url": self._url,
                "title": self._title,
                "error": self._error,
                "viewport": {
                    "width": self._viewport["width"],
                    "height": self._viewport["height"],
                    "dpr": self._viewport["dpr"],
                },
                "frames": self._frame_count,
                "subscribers": len(self._subscribers),
                "tabs": [dict(item) for item in self._tabs],
                "activeTabId": self._target_id,
                "scroll": dict(self._scroll) if self._scroll_known else None,
            }
        except Exception as err:
            return {
                "available": False,
                "running": False,
                "browser": None,
                "executable": None,
                "windowMode": self._window_mode,
                "profile": str(self._profile),
                "port": self._port,
                "cdpUrl": f"http://{self._host}:{self._port}",
                "url": self._url,
                "title": self._title,
                "error": str(err),
                "viewport": dict(self._viewport),
                "frames": self._frame_count,
                "subscribers": len(self._subscribers),
                "tabs": [dict(item) for item in self._tabs],
                "activeTabId": self._target_id,
                "scroll": dict(self._scroll) if self._scroll_known else None,
            }

    async def start(self) -> dict[str, Any]:
        """Launch or attach to the browser and open the cached page target."""

        self._error = None
        try:
            await self._ensure_session()
            await self._refresh_tabs()
            if self._subscribers:
                await self._ensure_screencast()
        except BrowserError as err:
            self._error = str(err)
            raise
        return self.snapshot()

    async def open(self, url: str) -> dict[str, Any]:
        """Navigate the shared target, normalising bare domains to https."""

        target = normalize_url(url)
        try:
            session = await self._ensure_session()
            await session.send("Page.navigate", {"url": target})
            self._url = target
            await asyncio.sleep(0.35)
            if self._subscribers:
                await self._ensure_screencast()
            await self._refresh_meta()
            await self._refresh_tabs()
        except BrowserError as err:
            self._error = str(err)
            raise
        self._error = None
        return self.snapshot()

    async def select_tab(self, tab_id: str) -> dict[str, Any]:
        """Attach the shared screencast to another open browser tab."""
        value = str(tab_id or "").strip()
        if not value:
            raise BrowserError("tab id is required", 400)

        async with self._lock(self._tab_lock, "tab"):
            pages = await self._list_pages()
            page = next(
                (item for item in pages if item.get("id") == value and item.get("type") == "page"),
                None,
            )
            if page is None:
                raise BrowserError("unknown browser tab", 404)
            if value == self._target_id and self._session is not None and not self._session.closed:
                return self.snapshot()

            await self._stop_screencast(force=True)
            previous = self._session
            self._session = None
            self._target_id = value
            if previous is not None:
                await previous.close()
            await self._ensure_session()
            if self._subscribers:
                await self._ensure_screencast()
            await self._refresh_meta()
            self._tabs_signature = None
            await self._refresh_tabs()

        self._error = None
        return self.snapshot()

    async def close_tab(self, tab_id: str) -> dict[str, Any]:
        """Close one browser tab, keeping a live target selected."""
        value = str(tab_id or "").strip()
        if not value:
            raise BrowserError("tab id is required", 400)

        pages = await self._list_pages()
        target = next(
            (item for item in pages if item.get("id") == value and item.get("type") == "page"),
            None,
        )
        if target is None:
            raise BrowserError("unknown browser tab", 404)

        if value == self._target_id:
            fallback = next(
                (
                    item
                    for item in pages
                    if item.get("id") != value
                    and item.get("type") == "page"
                    and item.get("webSocketDebuggerUrl")
                ),
                None,
            )
            if fallback is not None:
                await self.select_tab(str(fallback["id"]))
            else:
                await self.new_tab()

        try:
            await asyncio.to_thread(
                self._http_text,
                "/json/close/" + urllib.parse.quote(value, safe=""),
                "GET",
            )
        except (OSError, ValueError) as err:
            raise BrowserError(f"could not close the browser tab: {err}") from err

        self._tabs_signature = None
        await self._refresh_tabs()
        self._error = None
        return self.snapshot()

    async def new_tab(self, url: str | None = None) -> dict[str, Any]:
        """Open and select a fresh browser tab."""
        target = normalize_url(url) if url else "about:blank"
        try:
            page = await asyncio.to_thread(
                self._http_json,
                "/json/new?" + urllib.parse.quote(target, safe=""),
                "PUT",
            )
        except (OSError, ValueError, json.JSONDecodeError) as err:
            raise BrowserError(f"could not open a browser tab: {err}") from err

        tab_id = page.get("id") if isinstance(page, dict) else None
        if not isinstance(tab_id, str):
            raise BrowserError("the browser did not return a new tab")
        return await self.select_tab(tab_id)

    async def _refresh_tabs(self) -> list[dict[str, Any]]:
        """Refresh the open-tab list and publish it when it changes."""
        try:
            pages = await self._list_pages()
        except BrowserError:
            return self._tabs

        tabs = []
        for item in pages:
            tab_id = item.get("id")
            if item.get("type") != "page" or not isinstance(tab_id, str):
                continue
            if not item.get("webSocketDebuggerUrl"):
                continue
            tabs.append(
                {
                    "id": tab_id,
                    "title": str(item.get("title") or ""),
                    "url": str(item.get("url") or ""),
                    "active": tab_id == self._target_id,
                }
            )

        signature = tuple((item["id"], item["title"], item["url"]) for item in tabs)
        if tabs != self._tabs or signature != self._tabs_signature:
            self._tabs = tabs
            self._tabs_signature = signature
            self._publish_state()
        return tabs

    async def action(self, name: str) -> None:
        """Run one navigation action: back, forward, reload or stop."""

        action = str(name or "").strip().lower()
        if action not in ("back", "forward", "reload", "stop"):
            raise BrowserError(f"unsupported browser action: {name}", 400)
        session = await self._ensure_session()
        if action in ("back", "forward"):
            history = await session.send("Page.getNavigationHistory")
            current = history.get("currentIndex")
            entries = history.get("entries") or []
            if isinstance(current, int):
                target = current - 1 if action == "back" else current + 1
                if 0 <= target < len(entries):
                    entry = entries[target] if isinstance(entries[target], dict) else {}
                    entry_id = entry.get("id")
                    if entry_id is not None:
                        await session.send("Page.navigateToHistoryEntry", {"entryId": entry_id})
        elif action == "reload":
            await session.send("Page.reload", {"ignoreCache": False})
        else:
            await session.send("Page.stopLoading")
        await asyncio.sleep(0.2)
        await self._refresh_meta()

    async def set_viewport(self, width: int, height: int, dpr: float = 1.0) -> None:
        """Resize the emulated page and restart a running screencast."""

        try:
            width_value = int(float(width))
            height_value = int(float(height))
            dpr_value = float(dpr)
        except (TypeError, ValueError) as err:
            raise BrowserError("viewport width, height and dpr must be numbers", 400) from err
        if not 0.1 <= dpr_value <= 4.0:
            raise BrowserError("dpr must be between 0.1 and 4", 400)

        self._viewport = {
            "width": max(320, min(width_value, 1920)),
            "height": max(240, min(height_value, 1080)),
            "dpr": max(0.5, min(dpr_value, 2.0)),
        }
        session = await self._ensure_session()
        await session.send(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": self._viewport["width"],
                "height": self._viewport["height"],
                "deviceScaleFactor": self._viewport["dpr"],
                "mobile": False,
            },
        )
        if self._cast_running:
            await self._stop_screencast(force=True)
            await self._ensure_screencast()

    async def send_input(self, event: dict[str, Any]) -> None:
        """Forward one pointer, wheel, text or key event to the page."""

        if not isinstance(event, dict):
            raise BrowserError("event must be an object", 400)
        kind = str(event.get("kind") or "").strip().lower()
        params: dict[str, Any] | None = None
        if kind == "mouse":
            params = _mouse_params(event)
            method = "Input.dispatchMouseEvent"
        elif kind == "wheel":
            params = _wheel_params(event)
            method = "Input.dispatchMouseEvent"
        elif kind == "text":
            text = event.get("text")
            if not isinstance(text, str):
                raise BrowserError("text input requires a text string", 400)
            params = {"text": text}
            method = "Input.insertText"
        elif kind == "key":
            params = _key_params(event)
            method = "Input.dispatchKeyEvent"
        else:
            raise BrowserError(f"unsupported input kind: {kind}", 400)

        if kind == "text" and not params["text"]:
            return
        session = await self._ensure_session()
        await session.send(method, params, timeout=10.0)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Attach one frame queue; a running browser then streams frames."""

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=MAX_FRAME_QUEUE)
        if self._last_frame is not None:
            queue.put_nowait(self._last_frame)
        self._subscribers.add(queue)
        if self._browser_running() and not self._cast_running:
            self._schedule_cast_start()
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Detach a queue; the last one to leave stops the screencast."""

        self._subscribers.discard(queue)
        if not self._subscribers and self._cast_running:
            self._task(self._stop_screencast())

    async def shutdown(self) -> None:
        """Stop the screencast, detach CDP and close a browser we launched."""

        await self._stop_screencast(force=True)
        self._stop_tab_poll()
        self._stop_scroll_poll()
        for queue in list(self._subscribers):
            self._subscribers.discard(queue)
        session = self._session
        self._session = None
        self._target_id = None
        if session is not None:
            await session.close()
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
            try:
                await asyncio.to_thread(process.wait, 3.0)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except OSError:
                    pass
                await asyncio.to_thread(process.wait, 2.0)
            except OSError:
                pass

    async def _ensure_session(self) -> _CdpSession:
        if self._session is not None and not self._session.closed:
            return self._session

        async with self._lock(self._session_lock, "session"):
            if self._session is not None and not self._session.closed:
                return self._session
            await self._ensure_browser()
            pages = await self._list_pages()
            page = next(
                (item for item in pages if self._target_id and item.get("id") == self._target_id),
                None,
            )
            if page is None:
                page = next(
                    (
                        item
                        for item in pages
                        if item.get("type") == "page"
                        and item.get("webSocketDebuggerUrl")
                        and not _is_blank(item.get("url"))
                    ),
                    None,
                )
            if page is None:
                page = next(
                    (
                        item
                        for item in pages
                        if item.get("type") == "page" and item.get("webSocketDebuggerUrl")
                    ),
                    None,
                )
            if page is None:
                try:
                    page = await asyncio.to_thread(self._http_json, "/json/new?about:blank", "PUT")
                except (OSError, ValueError, json.JSONDecodeError) as err:
                    raise BrowserError(f"could not open a browser page: {err}") from err

            target_id = page.get("id")
            ws_url = page.get("webSocketDebuggerUrl")
            if not isinstance(target_id, str) or not isinstance(ws_url, str):
                raise BrowserError("the browser exposed no debuggable page")

            session = _CdpSession(_rewrite_ws_url(ws_url, self._host), target_id)
            try:
                await session.open()
            except BrowserError:
                await session.close()
                raise
            self._session = session
            try:
                await session.send("Page.bringToFront", timeout=5.0)
                await session.send(
                    "Emulation.setDeviceMetricsOverride",
                    {
                        "width": self._viewport["width"],
                        "height": self._viewport["height"],
                        "deviceScaleFactor": self._viewport["dpr"],
                        "mobile": False,
                    },
                    timeout=5.0,
                )
                await session.send(
                    "Emulation.setFocusEmulationEnabled", {"enabled": True}, timeout=5.0
                )
            except BrowserError:
                pass
            self._target_id = target_id
            self._session_unsubs = [
                session.on("Page.frameNavigated", self._on_frame_navigated),
                session.on("Page.loadEventFired", self._on_load_event),
                session.on("Page.navigatedWithinDocument", self._on_navigated_within_document),
            ]
            session.on_close(lambda: self._on_session_closed(session))
            await self._refresh_meta()
            self._start_tab_poll()
            self._start_scroll_poll()
            return session

    async def _ensure_browser(self) -> None:
        executable = self._executable or find_browser()
        if executable:
            self._executable = executable

        if self._process is not None and self._process.poll() is None:
            if await self._wait_for_debugger():
                return
            raise BrowserError("the browser is running but not answering on its debugging port")

        if self._profile_active() and await self._debugger_up():
            return

        if not executable:
            raise BrowserError(
                "no Chrome, Edge, Chromium or Brave browser was found; set CECLI_BROWSER_BIN"
            )
        if not os.path.isfile(executable):
            raise BrowserError(f"browser executable not found: {executable}")

        try:
            self._profile.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            raise BrowserError(f"could not create the browser profile: {err}") from err

        if not self._port_explicit:
            self._port = self._choose_port()

        profile = _browser_profile_arg(self._profile, executable)
        self._window_mode = _resolve_window_mode(executable, self._requested_window_mode)
        args = _launch_args(executable, self._port, profile, self._window_mode)
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
        else:
            kwargs["start_new_session"] = True

        try:
            self._process = subprocess.Popen(args, **kwargs)
        except OSError as err:
            raise BrowserError(f"could not launch {browser_name(executable)}: {err}") from err

        if not await self._wait_for_debugger():
            process = self._process
            self._process = None
            if process is not None and process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    pass
            raise BrowserError(
                f"{browser_name(executable)} did not expose its debugging port on {self._port}"
            )

        if self._window_mode == "minimized":
            await _minimize_window(self._process)

        self._write_saved_port()

    async def _wait_for_debugger(self, timeout: float = LAUNCH_TIMEOUT) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if self._process is not None and self._process.poll() is not None:
                return False
            if await self._debugger_up():
                return True
            await asyncio.sleep(0.25)
        return False

    def _read_saved_port(self) -> int | None:
        """Read the debugger port saved by the previous desktop run."""
        try:
            value = int((self._profile / PORT_FILE).read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None
        return value if value > 0 else None

    def _write_saved_port(self) -> None:
        """Remember the chosen debugger port for a later desktop run."""
        try:
            (self._profile / PORT_FILE).write_text(str(self._port), encoding="utf-8")
        except OSError:
            return

    def _choose_port(self) -> int:
        """Pick the first standard loopback CDP port that is still free."""
        candidates = [self._port, self._preferred_port, *PORT_CANDIDATES]
        for port in dict.fromkeys(candidates):
            if port > 0 and self._port_free(port):
                return port
        return self._preferred_port

    @staticmethod
    def _port_free(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.1)
            return sock.connect_ex(("127.0.0.1", port)) != 0

    def _browser_running(self) -> bool:
        """Whether a CDP session or launched browser process is still alive."""
        return bool(
            (self._session is not None and not self._session.closed)
            or (self._process is not None and self._process.poll() is None)
        )

    def _profile_active(self) -> bool:
        """Whether our dedicated profile is locked by a live browser instance."""
        lock = self._profile / "SingletonLock"
        try:
            return lock.is_symlink() or lock.exists()
        except OSError:
            return False

    async def _debugger_up(self) -> bool:
        for host in self._debug_host_candidates():
            try:
                info = await asyncio.to_thread(
                    self._http_json_on, host, "/json/version", "GET", HEALTH_TIMEOUT
                )
            except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(info, dict):
                self._host = host
                return True
        return False

    def _debug_host_candidates(self) -> list[str]:
        executable = self._executable or ""
        if os.name != "nt" and executable.lower().endswith(".exe") and _is_wsl():
            hosts = ["127.0.0.1", "host.docker.internal"]
            nameserver = _wsl_nameserver()
            if nameserver:
                hosts.append(nameserver)
            return hosts
        return ["127.0.0.1"]

    def _http_json(self, path: str, method: str = "GET", timeout: float = HEALTH_TIMEOUT) -> Any:
        return self._http_json_on(self._host, path, method, timeout)

    def _http_json_on(self, host: str, path: str, method: str, timeout: float) -> Any:
        url = f"http://{host}:{self._port}{path}"
        request = urllib.request.Request(
            url, method=method, headers={"Host": f"{host}:{self._port}"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
        return json.loads(payload.decode("utf-8"))

    def _http_text(self, path: str, method: str = "GET", timeout: float = HEALTH_TIMEOUT) -> str:
        url = f"http://{self._host}:{self._port}{path}"
        request = urllib.request.Request(
            url, method=method, headers={"Host": f"{self._host}:{self._port}"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")

    async def _list_pages(self) -> list[dict[str, Any]]:
        try:
            result = await asyncio.to_thread(self._http_json, "/json/list")
        except (OSError, ValueError, json.JSONDecodeError) as err:
            raise BrowserError(f"could not list browser pages: {err}") from err
        if isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
        if isinstance(result, dict) and isinstance(result.get("targets"), list):
            return [item for item in result["targets"] if isinstance(item, dict)]
        return []

    async def _refresh_meta(self) -> None:
        session = self._session
        if session is None or session.closed:
            return
        try:
            result = await session.send(
                "Runtime.evaluate",
                {
                    "expression": "({url: location.href, title: document.title})",
                    "returnByValue": True,
                },
                timeout=5.0,
            )
        except BrowserError:
            return
        value = (result.get("result") or {}).get("value")
        if not isinstance(value, dict):
            return
        url = value.get("url")
        title = value.get("title")
        changed = False
        if isinstance(url, str) and url and url != self._url:
            self._url = url
            changed = True
        if isinstance(title, str) and title != self._title:
            self._title = title
            changed = True
        if changed:
            self._publish_state()

    def _on_frame_navigated(self, params: dict[str, Any]) -> None:
        frame = params.get("frame")
        if not isinstance(frame, dict) or frame.get("parentId"):
            return
        url = frame.get("url")
        if isinstance(url, str) and url and url != self._url:
            self._url = url
            self._publish_state()

    def _on_navigated_within_document(self, params: dict[str, Any]) -> None:
        url = params.get("url")
        if isinstance(url, str) and url and url != self._url:
            self._url = url
            self._publish_state()

    def _on_load_event(self, _params: dict[str, Any]) -> None:
        self._task(self._refresh_meta())

    def _on_session_closed(self, session: _CdpSession) -> None:
        if session is not self._session:
            return
        self._session = None
        self._target_id = None
        self._cast_running = False
        self._cast_session = None
        self._publish_event({"type": "error", "message": "the browser connection closed"})
        if self._subscribers:
            self._task(self._restart_screencast_later())

    async def _ensure_screencast(self) -> None:
        if not self._subscribers:
            return
        if self._session is None and self._process is None:
            return

        async with self._lock(self._cast_lock, "cast"):
            if self._cast_running and self._cast_session and not self._cast_session.closed:
                return
            session = await self._ensure_session()
            self._cast_session = session
            self._cast_running = True
            self._cast_unsubs = [
                session.on("Page.screencastFrame", self._on_screencast_frame),
            ]
            try:
                await session.send(
                    "Page.startScreencast",
                    {
                        "format": "jpeg",
                        "quality": FRAME_QUALITY,
                        **self._cast_size(),
                        "everyNthFrame": 1,
                    },
                )
            except BrowserError as err:
                self._cast_running = False
                self._cast_session = None
                self._drop_cast_listeners()
                self._error = str(err)
                raise

            if not self._subscribers:
                await self._stop_screencast(force=True)

    async def _stop_screencast(self, force: bool = False) -> None:
        if not force and self._subscribers:
            return
        self._cast_running = False
        session = self._cast_session
        self._cast_session = None
        self._drop_cast_listeners()
        if session is not None and not session.closed:
            try:
                await session.send("Page.stopScreencast", timeout=2.0)
            except BrowserError:
                pass

    def _drop_cast_listeners(self) -> None:
        for unsubscribe in self._cast_unsubs:
            try:
                unsubscribe()
            except Exception:
                continue
        self._cast_unsubs = []

    def _schedule_cast_start(self) -> None:
        self._task(self._start_screencast_safely())

    async def _restart_screencast_later(self) -> None:
        await asyncio.sleep(1.0)
        if self._subscribers and not self._cast_running:
            await self._start_screencast_safely()

    async def _start_screencast_safely(self) -> None:
        try:
            await self._ensure_screencast()
        except BrowserError as err:
            self._error = str(err)
            self._publish_event({"type": "error", "message": str(err)})

    def _on_screencast_frame(self, params: dict[str, Any]) -> None:
        data = params.get("data")
        if not isinstance(data, str) or not data:
            return
        self._frame_count += 1
        meta = params.get("metadata") if isinstance(params.get("metadata"), dict) else {}
        frame = {"type": "frame", "data": data, "meta": meta}
        self._last_frame = frame
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(frame)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(frame)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    continue
        self._schedule_ack(params.get("sessionId"))

    def _schedule_ack(self, session_id: Any) -> None:
        if session_id is None:
            return
        session = self._cast_session
        if session is None or session.closed:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        now = loop.time()
        slot = max(now, self._next_ack_at + FRAME_INTERVAL)
        self._next_ack_at = slot
        task = loop.create_task(self._ack_later(session, session_id, max(0.0, slot - now)))
        self._ack_tasks.add(task)
        task.add_done_callback(self._ack_tasks.discard)

    async def _ack_later(self, session: _CdpSession, session_id: Any, delay: float) -> None:
        if delay:
            await asyncio.sleep(delay)
        try:
            await session.send("Page.screencastFrameAck", {"sessionId": session_id}, timeout=5.0)
        except BrowserError:
            return

    def _cast_size(self) -> dict[str, int]:
        scale = min(self._viewport["dpr"], MAX_DPR)
        return {
            "maxWidth": min(int(round(self._viewport["width"] * scale)), MAX_CAST_WIDTH),
            "maxHeight": min(int(round(self._viewport["height"] * scale)), MAX_CAST_HEIGHT),
        }

    def _start_tab_poll(self) -> None:
        """Poll the debugger for tabs opened by browser-harness or the user."""
        if self._tab_task is not None and not self._tab_task.done():
            return
        try:
            self._tab_task = asyncio.get_running_loop().create_task(self._poll_tabs())
        except RuntimeError:
            return

    async def _poll_tabs(self) -> None:
        try:
            while self._browser_running():
                await asyncio.sleep(TAB_POLL_SECONDS)
                if not self._browser_running():
                    return
                await self._refresh_tabs()
        except asyncio.CancelledError:
            raise
        finally:
            if self._tab_task is asyncio.current_task():
                self._tab_task = None

    def _stop_tab_poll(self) -> None:
        task = self._tab_task
        self._tab_task = None
        if task is not None and not task.done():
            task.cancel()

    def _start_scroll_poll(self) -> None:
        """Track the page scroll position so the UI can chain wheel scrolling."""
        if self._scroll_task is not None and not self._scroll_task.done():
            return
        try:
            self._scroll_task = asyncio.get_running_loop().create_task(self._poll_scroll())
        except RuntimeError:
            return

    async def _poll_scroll(self) -> None:
        try:
            while self._browser_running():
                await asyncio.sleep(SCROLL_POLL_SECONDS)
                if not self._browser_running():
                    return
                if not self._subscribers:
                    continue
                await self._refresh_scroll()
        except asyncio.CancelledError:
            raise
        finally:
            if self._scroll_task is asyncio.current_task():
                self._scroll_task = None

    async def _refresh_scroll(self) -> None:
        session = self._session
        if session is None or session.closed:
            return

        expression = (
            "(() => { "
            "const d = document.scrollingElement || document.documentElement || {}; "
            "const vw = window.innerWidth || 0; "
            "const vh = window.innerHeight || 0; "
            "return { "
            "x: window.scrollX || window.pageXOffset || 0, "
            "y: window.scrollY || window.pageYOffset || 0, "
            "maxX: Math.max(0, (d.scrollWidth || 0) - vw), "
            "maxY: Math.max(0, (d.scrollHeight || 0) - vh) "
            "}; })()"
        )
        try:
            result = await session.send(
                "Runtime.evaluate",
                {"expression": expression, "returnByValue": True},
                timeout=2.0,
            )
        except BrowserError:
            return

        value = (result.get("result") or {}).get("value")
        if not isinstance(value, dict):
            return

        scroll = {}
        for key in ("x", "y", "maxX", "maxY"):
            try:
                scroll[key] = max(0, int(float(value.get(key) or 0)))
            except (TypeError, ValueError):
                scroll[key] = 0

        signature = tuple(scroll[key] for key in ("x", "y", "maxX", "maxY"))
        if signature == self._scroll_signature:
            return

        self._scroll = scroll
        self._scroll_signature = signature
        self._scroll_known = True
        self._publish_state()

    def _stop_scroll_poll(self) -> None:
        task = self._scroll_task
        self._scroll_task = None
        if task is not None and not task.done():
            task.cancel()

    def _publish_state(self) -> None:
        """Push a fresh metadata snapshot to connected panes."""
        if self._subscribers:
            self._publish_event({"type": "state", "state": self.snapshot()})

    def _publish_event(self, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                continue

    def _task(self, coroutine: Any) -> None:
        try:
            asyncio.get_running_loop().create_task(coroutine)
        except RuntimeError:
            return

    def _lock(self, holder: asyncio.Lock | None, name: str) -> asyncio.Lock:
        if holder is not None:
            return holder
        lock = asyncio.Lock()
        if name == "session":
            self._session_lock = lock
        elif name == "tab":
            self._tab_lock = lock
        else:
            self._cast_lock = lock
        return lock


def normalize_url(raw: Any) -> str:
    """Validate and normalise one user-supplied address."""

    if not isinstance(raw, str):
        raise BrowserError("url must be a string", 400)
    value = raw.strip()
    if not value:
        raise BrowserError("url is required", 400)
    if any(ord(character) < 32 for character in value):
        raise BrowserError("url contains control characters", 400)
    lowered = value.lower()
    if lowered == "localhost" or (
        lowered.startswith("localhost") and len(lowered) > 9 and lowered[9] in ":/"
    ):
        candidate = f"http://{value}"
    elif lowered == "::1":
        return "http://[::1]"
    elif lowered.startswith(("127.", "[::1]")):
        candidate = f"http://{value}"
    else:
        scheme = _SCHEME_RE.match(value)
        if scheme:
            name = scheme.group(0)[:-1].lower()
            if name not in ALLOWED_SCHEMES:
                if "." in name:
                    scheme = None
                else:
                    raise BrowserError(f"unsupported URL scheme: {name}", 400)
            elif name not in ("http", "https"):
                return value
        if scheme is None and any(character.isspace() for character in value):
            raise BrowserError("url contains whitespace", 400)
        candidate = value if scheme else f"https://{value}"

    try:
        parsed = urllib.parse.urlsplit(candidate)
        host = parsed.hostname
    except ValueError as err:
        raise BrowserError("url requires a valid host", 400) from err
    if not host or any(character.isspace() for character in parsed.netloc):
        raise BrowserError("url requires a valid host", 400)
    return candidate


def browser_name(executable: str | None) -> str | None:
    """Human-readable browser family for one executable path."""

    if not executable:
        return None
    stem = Path(executable).name.lower()
    if "msedge" in stem or "edge" in stem:
        return "Edge"
    if "brave" in stem:
        return "Brave"
    if "chromium" in stem:
        return "Chromium"
    if "chrome" in stem:
        return "Chrome"
    return Path(executable).stem or "Chromium"


def find_browser() -> str | None:
    """Resolve an installed Chromium browser, preferring Chrome."""

    override = os.environ.get("CECLI_BROWSER_BIN", "").strip()
    if override:
        expanded = os.path.expanduser(override)
        if os.path.isfile(expanded):
            return expanded
        found = shutil.which(override)
        if found:
            return found
        return None

    for command in BROWSER_COMMANDS:
        found = shutil.which(command)
        if found:
            return found

    for candidate in _standard_paths():
        if os.path.isfile(candidate):
            return candidate
    return None


def _standard_paths() -> list[str]:
    paths: list[str] = []
    program_roots = [
        os.environ.get("PROGRAMFILES"),
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("LOCALAPPDATA"),
    ]
    relative = (
        ("Google", "Chrome", "Application", "chrome.exe"),
        ("Microsoft", "Edge", "Application", "msedge.exe"),
        ("Chromium", "Application", "chrome.exe"),
        ("BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
    )
    for root in program_roots:
        if not root:
            continue
        for parts in relative:
            paths.append(os.path.join(os.path.expanduser(root), *parts))

    for prefix in (
        "/mnt/c/Program Files",
        "/mnt/c/Program Files (x86)",
        "/mnt/d/Program Files",
        "/mnt/d/Program Files (x86)",
    ):
        paths.extend(
            [
                f"{prefix}/Google/Chrome/Application/chrome.exe",
                f"{prefix}/Microsoft/Edge/Application/msedge.exe",
                f"{prefix}/Chromium/Application/chrome.exe",
                f"{prefix}/BraveSoftware/Brave-Browser/Application/brave.exe",
            ]
        )

    paths.extend(
        [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/microsoft-edge",
            "/usr/bin/microsoft-edge-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
            "/usr/bin/brave-browser",
            "/opt/google/chrome/chrome",
        ]
    )
    return paths


def _resolve_window_mode(executable: str | None = None, requested: str | None = None) -> str:
    """Resolve the requested window mode to one concrete launch mode.

    ``auto`` uses headless Chromium on WSL because WSLg ignores window
    positioning, minimizes on other Linux desktops, and keeps the historical
    off-screen placement on macOS and Windows. A user-supplied
    ``CECLI_BROWSER_BIN`` keeps the off-screen default so wrapper scripts that
    need a display are not forced into headless mode.
    """

    value = (requested or os.environ.get(WINDOW_MODE_ENV, "")).strip().lower()
    if value not in WINDOW_MODES:
        value = "auto"
    if value != "auto":
        return value
    if os.environ.get("CECLI_BROWSER_BIN", "").strip():
        return "offscreen"
    if _is_wsl():
        return "headless"
    if sys.platform.startswith("linux"):
        return "minimized"
    return "offscreen"


def _window_flags(mode: str) -> list[str]:
    """Chromium flags for one concrete window mode."""

    if mode == "headless":
        return ["--headless=new", WINDOW_SIZE_FLAG]
    if mode == "visible":
        return [WINDOW_SIZE_FLAG]
    if mode == "minimized":
        return [WINDOW_SIZE_FLAG, OFFSCREEN_POSITION_FLAG, "--start-minimized"]
    return [WINDOW_SIZE_FLAG, OFFSCREEN_POSITION_FLAG]


def _launch_args(executable: str, port: int, profile: str, mode: str) -> list[str]:
    """Full Chromium command line for one launch."""

    return [
        executable,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        *LAUNCH_FLAGS,
        *_window_flags(mode),
        "about:blank",
    ]


def _is_wsl() -> bool:
    if sys.platform != "linux":
        return False
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False


async def _minimize_window(process: subprocess.Popen[Any] | None) -> None:
    """Best-effort iconify when a compositor ignores ``--start-minimized``."""

    if process is None or sys.platform != "linux" or process.poll() is not None:
        return
    executable = shutil.which("xdotool")
    if not executable:
        return
    try:
        await asyncio.to_thread(
            subprocess.run,
            [executable, "search", "--onlyvisible", "--pid", str(process.pid), "windowminimize"],
            capture_output=True,
            timeout=2.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return


def _wsl_nameserver() -> str | None:
    try:
        for line in Path("/etc/resolv.conf").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("nameserver"):
                parts = line.split()
                if len(parts) > 1:
                    return parts[1]
    except OSError:
        return None
    return None


def _browser_profile_arg(profile: Path, executable: str) -> str:
    if os.name != "nt" and executable.lower().endswith(".exe") and _is_wsl():
        try:
            result = subprocess.run(
                ["wslpath", "-w", str(profile)],
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )
            native = result.stdout.strip()
            if result.returncode == 0 and native:
                return native
        except (OSError, subprocess.SubprocessError):
            pass
    return str(profile)


def _rewrite_ws_url(url: str, host: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    port = parsed.port or 80
    netloc = f"[{host}]:{port}" if ":" in host and not host.startswith("[") else f"{host}:{port}"
    return urllib.parse.urlunsplit((parsed.scheme or "ws", netloc, parsed.path, parsed.query, ""))


def _is_blank(url: Any) -> bool:
    return not url or str(url).startswith("about:blank")


def _decode_json(payload: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _number(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as err:
        raise BrowserError(f"{name} must be a number", 400) from err


def _mouse_params(event: dict[str, Any]) -> dict[str, Any]:
    event_type = str(event.get("type") or "mouseMoved")
    if event_type not in ("mousePressed", "mouseReleased", "mouseMoved"):
        raise BrowserError(f"unsupported mouse event type: {event_type}", 400)

    moving = event_type == "mouseMoved"
    default_button = "none" if moving else "left"
    button = str(event.get("button") or default_button)
    if button not in MOUSE_BUTTONS:
        raise BrowserError(f"unsupported mouse button: {button}", 400)

    click_count = event.get("clickCount")
    try:
        click_count_value = max(0, int(click_count))
    except (TypeError, ValueError):
        click_count_value = 0 if moving else 1

    buttons = event.get("buttons")
    try:
        buttons_value = int(buttons)
    except (TypeError, ValueError):
        buttons_value = 0 if moving or event_type == "mouseReleased" else 1

    return {
        "type": event_type,
        "x": _number(event.get("x", 0), "x"),
        "y": _number(event.get("y", 0), "y"),
        "button": button,
        "buttons": buttons_value,
        "clickCount": click_count_value,
    }


def _wheel_params(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "mouseWheel",
        "x": _number(event.get("x", 0), "x"),
        "y": _number(event.get("y", 0), "y"),
        "deltaX": _number(event.get("deltaX", 0), "deltaX"),
        "deltaY": _number(event.get("deltaY", 0), "deltaY"),
        "button": "none",
        "buttons": 0,
    }


def _key_params(event: dict[str, Any]) -> dict[str, Any]:
    event_type = str(event.get("type") or "keyDown")
    if event_type not in ("keyDown", "keyUp", "rawKeyDown", "char"):
        raise BrowserError(f"unsupported key event type: {event_type}", 400)
    key = str(event.get("key") or "")
    if not key and event_type in ("keyDown", "rawKeyDown", "char"):
        raise BrowserError("key is required for key events", 400)

    code = str(event.get("code") or "")
    virtual = KEY_CODES.get(key.lower())
    if virtual is None:
        provided = event.get("windowsVirtualKeyCode")
        if isinstance(provided, int) and provided > 0:
            virtual = (provided, code)
    if virtual is None and len(key) == 1:
        virtual = (ord(key.upper()), code)

    modifiers = _modifier_bits(event.get("modifiers"))
    params: dict[str, Any] = {"type": event_type}
    if key:
        params["key"] = key
    if code:
        params["code"] = code
    if virtual:
        params["windowsVirtualKeyCode"] = virtual[0]
        params["nativeVirtualKeyCode"] = virtual[0]
        if virtual[1]:
            params.setdefault("code", virtual[1])
    if modifiers:
        params["modifiers"] = modifiers
    if event_type in ("keyDown", "char"):
        text = event.get("text")
        if isinstance(text, str) and text:
            params["text"] = text
        elif key == "Enter":
            params["text"] = "\r"
        elif len(key) == 1 and not modifiers:
            params["text"] = key
    return params


def _modifier_bits(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value & 15
    if isinstance(value, str):
        names = re.split(r"[+,]", value)
    elif isinstance(value, (list, tuple, set)):
        names = [str(item) for item in value]
    else:
        return 0
    bits = 0
    for name in names:
        bits |= MODIFIER_BITS.get(str(name).strip().lower(), 0)
    return bits
