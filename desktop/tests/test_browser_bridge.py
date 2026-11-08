#!/usr/bin/env python3
"""Unit tests for the desktop browser bridge.

The real CDP path is covered by a small in-process WebSocket server, so these
tests exercise framing, command dispatch and event delivery without launching a
browser. Pure helpers and the JSON routes are checked directly.
"""

from __future__ import annotations

import asyncio
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import browser_bridge  # noqa: E402
import server  # noqa: E402
from browser_bridge import (  # noqa: E402
    BrowserBridge,
    BrowserError,
    _CdpSession,
    _key_params,
    _launch_args,
    _modifier_bits,
    _mouse_params,
    _resolve_window_mode,
    _wheel_params,
    _window_flags,
    find_browser,
    normalize_url,
)


class UrlTests(unittest.TestCase):
    def test_bare_domains_get_https(self) -> None:
        self.assertEqual(normalize_url("example.com"), "https://example.com")
        self.assertEqual(normalize_url("  example.com/a?b=1  "), "https://example.com/a?b=1")
        self.assertEqual(normalize_url("example.com:8080/x"), "https://example.com:8080/x")

    def test_preserved_schemes_and_localhost(self) -> None:
        self.assertEqual(normalize_url("http://example.com"), "http://example.com")
        self.assertEqual(normalize_url("https://example.com"), "https://example.com")
        self.assertEqual(normalize_url("about:blank"), "about:blank")
        self.assertEqual(normalize_url("localhost:3000/x"), "http://localhost:3000/x")
        self.assertEqual(normalize_url("127.0.0.1:9000"), "http://127.0.0.1:9000")

    def test_rejects_empty_and_unsupported(self) -> None:
        for value in ("", "   ", "javascript:alert(1)", "ftp://example.com", "not a url"):
            with self.assertRaises(BrowserError) as caught:
                normalize_url(value)
            self.assertEqual(caught.exception.status, 400)

    def test_rejects_non_strings(self) -> None:
        with self.assertRaises(BrowserError):
            normalize_url(42)  # type: ignore[arg-type]


class InputTests(unittest.TestCase):
    def test_key_codes_and_modifiers(self) -> None:
        event = _key_params({"type": "keyDown", "key": "Enter", "modifiers": ["ctrl", "shift"]})
        self.assertEqual(event["windowsVirtualKeyCode"], 13)
        self.assertEqual(event["modifiers"], 10)
        self.assertEqual(event["text"], "\r")

        arrow = _key_params({"type": "keyUp", "key": "ArrowLeft"})
        self.assertEqual(arrow["windowsVirtualKeyCode"], 37)

    def test_modifier_bits_accepts_names_and_numbers(self) -> None:
        self.assertEqual(_modifier_bits(["alt", "meta"]), 5)
        self.assertEqual(_modifier_bits("ctrl+shift"), 10)
        self.assertEqual(_modifier_bits(3), 3)
        self.assertEqual(_modifier_bits(None), 0)

    def test_mouse_and_wheel_defaults(self) -> None:
        mouse = _mouse_params({"type": "mouseReleased", "x": 1, "y": 2})
        self.assertEqual(mouse["buttons"], 0)
        self.assertEqual(mouse["clickCount"], 1)
        move = _mouse_params(
            {"type": "mouseMoved", "x": 1, "y": 2, "button": "none", "clickCount": 0}
        )
        self.assertEqual(move["clickCount"], 0)
        wheel = _wheel_params({"x": 1, "y": 2, "deltaY": -120})
        self.assertEqual(wheel["type"], "mouseWheel")
        self.assertEqual(wheel["deltaY"], -120.0)

    def test_unknown_mouse_type_is_rejected(self) -> None:
        with self.assertRaises(BrowserError):
            _mouse_params({"type": "mouseWarp", "x": 1, "y": 2})

    def test_pointer_move_defaults_to_hover(self) -> None:
        move = _mouse_params({"type": "mouseMoved", "x": 3, "y": 4})
        self.assertEqual(move["button"], "none")
        self.assertEqual(move["buttons"], 0)
        self.assertEqual(move["clickCount"], 0)

    def test_unknown_mouse_button_is_rejected(self) -> None:
        with self.assertRaises(BrowserError):
            _mouse_params({"type": "mousePressed", "x": 1, "y": 2, "button": "bogus"})

    def test_printable_key_gets_a_virtual_code_and_text(self) -> None:
        event = _key_params({"type": "keyDown", "key": "a"})
        self.assertEqual(event["windowsVirtualKeyCode"], 65)
        self.assertEqual(event["text"], "a")

        shortcut = _key_params({"type": "rawKeyDown", "key": "a", "modifiers": 2})
        self.assertEqual(shortcut["windowsVirtualKeyCode"], 65)
        self.assertNotIn("text", shortcut)

    def test_key_down_requires_a_key(self) -> None:
        with self.assertRaises(BrowserError):
            _key_params({"type": "keyDown"})


class DiscoveryTests(unittest.TestCase):
    def test_overrides_and_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "chrome"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
            with mock.patch.dict(os.environ, {"CECLI_BROWSER_BIN": str(executable)}):
                self.assertEqual(find_browser(), str(executable))
                bridge = BrowserBridge(profile=Path(temp_dir) / "profile", port=9999)
                state = bridge.snapshot()
                self.assertTrue(state["available"])
                self.assertEqual(state["executable"], str(executable))
                self.assertEqual(state["browser"], "Chrome")
                self.assertEqual(state["viewport"]["width"], 1280)

    def test_snapshot_never_raises_without_a_browser(self) -> None:
        with mock.patch.dict(os.environ, {"CECLI_BROWSER_BIN": ""}, clear=False):
            with mock.patch.object(browser_bridge, "find_browser", return_value=None):
                state = BrowserBridge().snapshot()
        self.assertFalse(state["available"])
        self.assertFalse(state["running"])
        self.assertIsNone(state["error"])

    def test_cast_size_is_bounded(self) -> None:
        bridge = BrowserBridge()
        bridge._viewport = {"width": 3000, "height": 2000, "dpr": 2.0}
        size = bridge._cast_size()
        self.assertEqual(size["maxWidth"], 2048)
        self.assertEqual(size["maxHeight"], 2048)


class WindowModeTests(unittest.TestCase):
    def test_flags_for_each_mode(self) -> None:
        headless = _window_flags("headless")
        self.assertIn("--headless=new", headless)
        self.assertNotIn("--start-minimized", headless)
        self.assertNotIn("--window-position", " ".join(headless))

        minimized = _window_flags("minimized")
        self.assertIn("--start-minimized", minimized)
        self.assertIn("--window-position=-32000,-32000", minimized)

        offscreen = _window_flags("offscreen")
        self.assertIn("--window-position=-32000,-32000", offscreen)
        self.assertNotIn("--headless=new", offscreen)

        self.assertEqual(_window_flags("visible"), [browser_bridge.WINDOW_SIZE_FLAG])

    def test_launch_args_include_selected_mode(self) -> None:
        args = _launch_args("/usr/bin/chrome", 9222, "/tmp/profile", "headless")
        self.assertEqual(args[0], "/usr/bin/chrome")
        self.assertIn("--remote-debugging-port=9222", args)
        self.assertIn("--user-data-dir=/tmp/profile", args)
        self.assertIn("--headless=new", args)
        self.assertEqual(args[-1], "about:blank")

        visible = _launch_args("/usr/bin/chrome", 9222, "/tmp/profile", "visible")
        self.assertNotIn("--window-position=-32000,-32000", visible)
        self.assertIn("--window-size=1280,900", visible)

    def test_environment_override_wins(self) -> None:
        with mock.patch.dict(os.environ, {"CECLI_BROWSER_WINDOW_MODE": "visible"}):
            self.assertEqual(_resolve_window_mode(), "visible")
        with mock.patch.dict(os.environ, {"CECLI_BROWSER_WINDOW_MODE": "minimized"}):
            self.assertEqual(_resolve_window_mode(), "minimized")

    def test_invalid_override_falls_back_to_auto(self) -> None:
        with mock.patch.dict(os.environ, {"CECLI_BROWSER_WINDOW_MODE": "banana"}):
            with mock.patch.object(browser_bridge, "_is_wsl", return_value=False):
                with mock.patch.object(browser_bridge.sys, "platform", "linux"):
                    self.assertEqual(_resolve_window_mode(), "minimized")

    def test_auto_wsl_uses_headless(self) -> None:
        with mock.patch.dict(os.environ, {"CECLI_BROWSER_WINDOW_MODE": ""}):
            with mock.patch.object(browser_bridge, "_is_wsl", return_value=True):
                self.assertEqual(_resolve_window_mode(), "headless")

    def test_auto_linux_uses_minimized(self) -> None:
        with mock.patch.dict(os.environ, {"CECLI_BROWSER_WINDOW_MODE": ""}):
            with mock.patch.object(browser_bridge, "_is_wsl", return_value=False):
                with mock.patch.object(browser_bridge.sys, "platform", "linux"):
                    self.assertEqual(_resolve_window_mode(), "minimized")

    def test_auto_macos_and_windows_keep_offscreen(self) -> None:
        for platform in ("darwin", "win32"):
            with mock.patch.dict(os.environ, {"CECLI_BROWSER_WINDOW_MODE": ""}):
                with mock.patch.object(browser_bridge.sys, "platform", platform):
                    self.assertEqual(_resolve_window_mode(), "offscreen")

    def test_custom_browser_stays_offscreen(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"CECLI_BROWSER_WINDOW_MODE": "", "CECLI_BROWSER_BIN": "/opt/custom/chrome"},
        ):
            with mock.patch.object(browser_bridge, "_is_wsl", return_value=True):
                self.assertEqual(_resolve_window_mode(), "offscreen")

    def test_wsl_detection_uses_environment(self) -> None:
        with mock.patch.dict(os.environ, {"WSL_DISTRO_NAME": "Ubuntu"}, clear=True):
            with mock.patch.object(browser_bridge.sys, "platform", "linux"):
                self.assertTrue(browser_bridge._is_wsl())
        with mock.patch.dict(os.environ, {"WSL_INTEROP": "/run/WSL/2_interop"}, clear=True):
            with mock.patch.object(browser_bridge.sys, "platform", "linux"):
                self.assertTrue(browser_bridge._is_wsl())
        with mock.patch.dict(os.environ, {"WSL_DISTRO_NAME": "Ubuntu"}, clear=True):
            with mock.patch.object(browser_bridge.sys, "platform", "darwin"):
                self.assertFalse(browser_bridge._is_wsl())

    def test_snapshot_reports_resolved_mode(self) -> None:
        with mock.patch.dict(os.environ, {"CECLI_BROWSER_WINDOW_MODE": "visible"}):
            bridge = BrowserBridge(window_mode="visible")
            self.assertEqual(bridge.snapshot()["windowMode"], "visible")

    def test_ensure_browser_launches_in_selected_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "chrome"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            bridge = BrowserBridge(
                executable=str(executable),
                profile=Path(temp_dir) / "profile",
                port=9999,
                window_mode="headless",
            )
            process = mock.Mock()
            process.poll.return_value = None
            popen_patch = mock.patch.object(
                browser_bridge.subprocess, "Popen", return_value=process
            )
            with popen_patch as popen:
                wait_for_debugger = mock.AsyncMock(return_value=True)
                bridge._wait_for_debugger = wait_for_debugger  # type: ignore[method-assign]
                bridge._write_saved_port = mock.Mock()  # type: ignore[method-assign]
                asyncio.run(bridge._ensure_browser())
            args = popen.call_args.args[0]
            self.assertIn("--headless=new", args)
            self.assertNotIn("--window-position=-32000,-32000", args)


def _server_frame(payload: bytes, opcode: int = 0x1) -> bytes:
    length = len(payload)
    header = bytearray([0x80 | opcode])
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", length))
    return bytes(header) + payload


async def _client_frame(reader: asyncio.StreamReader) -> tuple[int, bytes] | None:
    try:
        head = await reader.readexactly(2)
    except asyncio.IncompleteReadError:
        return None
    first, second = head
    opcode = first & 0x0F
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", await reader.readexactly(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", await reader.readexactly(8))[0]
    mask = await reader.readexactly(4) if second & 0x80 else b""
    payload = await reader.readexactly(length) if length else b""
    if mask:
        payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    return opcode, payload


class FakeCdpServer:
    """A tiny CDP endpoint good enough for one page session."""

    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []
        self.acks: list[dict[str, Any]] = []
        self.server: asyncio.AbstractServer | None = None
        self.writer: asyncio.StreamWriter | None = None

    async def start(self) -> str:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        return f"ws://127.0.0.1:{port}/devtools/page/fake"

    async def close(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\nConnection: Upgrade\r\n\r\n"
        )
        await writer.drain()
        self.writer = writer
        try:
            while True:
                frame = await _client_frame(reader)
                if frame is None:
                    return
                opcode, payload = frame
                if opcode == 0x8:
                    return
                if opcode != 0x1:
                    continue
                message = json.loads(payload.decode("utf-8"))
                self.frames.append(message)
                await self._reply(writer, message)
        finally:
            writer.close()

    async def _reply(self, writer: asyncio.StreamWriter, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        method = message.get("method")
        result: dict[str, Any] = {}
        if method == "Page.fail":
            writer.write(
                _server_frame(
                    json.dumps(
                        {"id": request_id, "error": {"code": -32000, "message": "nope"}}
                    ).encode()
                )
            )
            await writer.drain()
            return
        if method == "Runtime.evaluate":
            result = {"result": {"value": {"url": "about:blank", "title": "Fake"}}}
        elif method == "Page.getNavigationHistory":
            result = {"currentIndex": 1, "entries": [{"id": 1}, {"id": 2}]}
        elif method == "Page.screencastFrameAck":
            self.acks.append(message.get("params") or {})
        writer.write(_server_frame(json.dumps({"id": request_id, "result": result}).encode()))
        if method == "Page.startScreencast":
            event = {
                "method": "Page.screencastFrame",
                "params": {
                    "data": "ZmFrZQ==",
                    "metadata": {"deviceWidth": 100},
                    "sessionId": 1,
                },
            }
            writer.write(_server_frame(json.dumps(event).encode()))
        await writer.drain()


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_subscribe_does_not_start_the_cast_before_start(self) -> None:
        bridge = BrowserBridge()

        with mock.patch.object(bridge, "_schedule_cast_start") as schedule:
            bridge.subscribe()

        schedule.assert_not_called()

    async def test_wait_for_debugger_stops_when_the_process_exits(self) -> None:
        bridge = BrowserBridge()
        bridge._process = mock.Mock()
        bridge._process.poll.return_value = 1

        with mock.patch.object(bridge, "_debugger_up", new=mock.AsyncMock(return_value=False)):
            ready = await bridge._wait_for_debugger(5.0)

        self.assertFalse(ready)


class TabTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_tabs_caches_and_publishes(self) -> None:
        bridge = BrowserBridge()
        bridge._target_id = "b"
        queue = bridge.subscribe()
        pages = [
            {
                "id": "a",
                "type": "page",
                "title": "Alpha",
                "url": "https://a.example/",
                "webSocketDebuggerUrl": "ws://x/a",
            },
            {
                "id": "b",
                "type": "page",
                "title": "Beta",
                "url": "https://b.example/",
                "webSocketDebuggerUrl": "ws://x/b",
            },
        ]

        with mock.patch.object(bridge, "_list_pages", mock.AsyncMock(return_value=pages)):
            tabs = await bridge._refresh_tabs()

        self.assertEqual([tab["id"] for tab in tabs], ["a", "b"])
        self.assertFalse(tabs[0]["active"])
        self.assertTrue(tabs[1]["active"])

        event = queue.get_nowait()
        self.assertEqual(event["type"], "state")
        self.assertEqual(event["state"]["activeTabId"], "b")

    async def test_select_tab_rejects_unknown_ids(self) -> None:
        bridge = BrowserBridge()

        with mock.patch.object(bridge, "_list_pages", mock.AsyncMock(return_value=[])):
            with self.assertRaises(BrowserError) as caught:
                await bridge.select_tab("missing")

        self.assertEqual(caught.exception.status, 404)

    async def test_viewport_is_capped_at_1080p(self) -> None:
        bridge = BrowserBridge()
        session = mock.Mock()
        session.closed = False
        session.send = mock.AsyncMock(return_value={})
        bridge._session = session

        await bridge.set_viewport(3000, 2000, 1.0)

        self.assertEqual(bridge._viewport, {"width": 1920, "height": 1080, "dpr": 1.0})

    async def test_new_tab_opens_and_selects(self) -> None:
        bridge = BrowserBridge()
        bridge._http_json = mock.Mock(return_value={"id": "new-tab"})
        bridge.select_tab = mock.AsyncMock(return_value={"activeTabId": "new-tab"})

        state = await bridge.new_tab()

        self.assertEqual(state["activeTabId"], "new-tab")
        bridge.select_tab.assert_awaited_once_with("new-tab")
        bridge._http_json.assert_called_once_with("/json/new?about%3Ablank", "PUT")

    async def test_close_inactive_tab_keeps_current_session(self) -> None:
        bridge = BrowserBridge()
        bridge._target_id = "keep"
        bridge._list_pages = mock.AsyncMock(
            return_value=[
                {"id": "keep", "type": "page", "webSocketDebuggerUrl": "ws://keep"},
                {"id": "drop", "type": "page", "webSocketDebuggerUrl": "ws://drop"},
            ]
        )
        bridge._http_text = mock.Mock(return_value="Target is closing")
        bridge._refresh_tabs = mock.AsyncMock(return_value=[])

        await bridge.close_tab("drop")

        bridge._http_text.assert_called_once_with("/json/close/drop", "GET")
        self.assertEqual(bridge._target_id, "keep")

    async def test_refresh_scroll_publishes_boundaries(self) -> None:
        bridge = BrowserBridge()
        session = mock.Mock()
        session.closed = False
        session.send = mock.AsyncMock(
            return_value={"result": {"value": {"x": 4, "y": 120, "maxX": 40, "maxY": 300}}}
        )
        bridge._session = session
        queue = asyncio.Queue()
        bridge._subscribers.add(queue)

        await bridge._refresh_scroll()

        self.assertTrue(bridge._scroll_known)
        self.assertEqual(bridge._scroll, {"x": 4, "y": 120, "maxX": 40, "maxY": 300})
        event = queue.get_nowait()
        self.assertEqual(event["state"]["scroll"]["maxY"], 300)


class CdpSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.fake = FakeCdpServer()
        self.url = await self.fake.start()
        self.session = _CdpSession(self.url, "fake")
        await self.session.open()

    async def asyncTearDown(self) -> None:
        await self.session.close()
        await self.fake.close()

    async def test_commands_and_events(self) -> None:
        state = await self.session.send("Runtime.evaluate", {"expression": "1"})
        self.assertEqual(state["result"]["value"]["title"], "Fake")

        frame_event = asyncio.Event()
        received: list[dict[str, Any]] = []
        self.session.on(
            "Page.screencastFrame",
            lambda params: (received.append(params), frame_event.set()),
        )
        await self.session.send(
            "Page.startScreencast", {"format": "jpeg", "quality": 70, "everyNthFrame": 1}
        )
        await asyncio.wait_for(frame_event.wait(), 2.0)
        self.assertEqual(received[0]["data"], "ZmFrZQ==")

        history = await self.session.send("Page.getNavigationHistory")
        self.assertEqual(history["currentIndex"], 1)

    async def test_error_result_raises_browser_error(self) -> None:
        with self.assertRaises(BrowserError):
            await self.session.send("Page.fail")


class StubBrowser:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.frames: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.unsubscribed = False

    def snapshot(self) -> dict[str, Any]:
        return {
            "available": True,
            "running": True,
            "browser": "Chrome",
            "executable": "/usr/bin/google-chrome",
            "profile": "/tmp/profile",
            "port": 9334,
            "url": "about:blank",
            "title": "",
            "error": None,
            "viewport": {"width": 1280, "height": 900, "dpr": 1.0},
        }

    async def start(self) -> dict[str, Any]:
        self.calls.append(("start", None))
        return self.snapshot()

    async def open(self, url: str) -> dict[str, Any]:
        self.calls.append(("open", url))
        return self.snapshot()

    async def action(self, action: str) -> None:
        self.calls.append(("action", action))

    async def select_tab(self, tab_id: str) -> dict[str, Any]:
        self.calls.append(("tab", tab_id))
        return self.snapshot()

    async def new_tab(self, url: str | None = None) -> dict[str, Any]:
        self.calls.append(("tab/new", url))
        return self.snapshot()

    async def close_tab(self, tab_id: str) -> dict[str, Any]:
        self.calls.append(("tab/close", tab_id))
        return self.snapshot()

    async def set_viewport(self, width: int, height: int, dpr: float = 1.0) -> None:
        self.calls.append(("viewport", (width, height, dpr)))

    async def send_input(self, event: dict[str, Any]) -> None:
        self.calls.append(("input", event))

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        return self.frames

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.unsubscribed = True


class StubBridge:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []

    async def call_extension(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.requests.append((method, params))
        if params.get("action") == "list":
            return {"commands": [{"key": "abc", "command": "sleep 1"}]}
        return {"output": "done", "command": {"key": params.get("key")}}


class StubSessions:
    def __init__(self) -> None:
        self.bridge = StubBridge()

    def get(self, _bridge_id: str | None = None) -> StubBridge:
        return self.bridge


class RouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.browser = StubBrowser()
        self.sessions = StubSessions()
        self.app = server.DesktopServer(None, ROOT, browser=self.browser)
        self.app.sessions = self.sessions

    def route(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> tuple[int, dict[str, Any], str]:
        payload = b"" if body is None else json.dumps(body).encode("utf-8")
        status, raw, content_type = asyncio.run(self.app._route(method, path, payload, {}))
        return status, json.loads(raw.decode("utf-8")), content_type

    def test_state_and_start(self) -> None:
        status, body, _ = self.route("GET", "/api/browser/state")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertTrue(body["running"])

        status, body, _ = self.route("POST", "/api/browser/start", {})
        self.assertEqual(status, 202)
        self.assertEqual(self.browser.calls, [("start", None)])

    def test_open_validates_and_forwards(self) -> None:
        status, body, _ = self.route("POST", "/api/browser/open", {})
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])

        status, _, _ = self.route("POST", "/api/browser/open", {"url": "example.com"})
        self.assertEqual(status, 200)
        self.assertEqual(self.browser.calls[-1], ("open", "example.com"))

    def test_action_viewport_and_input(self) -> None:
        status, _, _ = self.route("POST", "/api/browser/action", {"action": "reload"})
        self.assertEqual(status, 202)
        status, _, _ = self.route(
            "POST", "/api/browser/viewport", {"width": 800, "height": 600, "dpr": 1.5}
        )
        self.assertEqual(status, 202)
        status, _, _ = self.route(
            "POST", "/api/browser/input", {"event": {"kind": "text", "text": "hi"}}
        )
        self.assertEqual(status, 202)
        self.assertEqual(self.browser.calls[-3][0], "action")
        self.assertEqual(self.browser.calls[-2][1], (800, 600, 1.5))
        self.assertEqual(self.browser.calls[-1][0], "input")

    def test_tab_switch_validates_and_forwards(self) -> None:
        status, body, _ = self.route("POST", "/api/browser/tab", {})
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])

        status, _, _ = self.route("POST", "/api/browser/tab", {"tabId": "abc"})
        self.assertEqual(status, 202)
        self.assertEqual(self.browser.calls[-1], ("tab", "abc"))

    def test_new_tab_forwards_optional_url(self) -> None:
        status, _, _ = self.route("POST", "/api/browser/tab/new", {})
        self.assertEqual(status, 202)
        self.assertEqual(self.browser.calls[-1], ("tab/new", None))

        status, _, _ = self.route("POST", "/api/browser/tab/new", {"url": "example.com"})
        self.assertEqual(status, 202)
        self.assertEqual(self.browser.calls[-1], ("tab/new", "example.com"))

    def test_close_tab_validates_and_forwards(self) -> None:
        status, body, _ = self.route("POST", "/api/browser/tab/close", {})
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])

        status, _, _ = self.route("POST", "/api/browser/tab/close", {"tabId": "abc"})
        self.assertEqual(status, 202)
        self.assertEqual(self.browser.calls[-1], ("tab/close", "abc"))

    def test_background_list_and_output(self) -> None:
        status, body, _ = self.route("POST", "/api/background", {"action": "list"})
        self.assertEqual(status, 200)
        self.assertEqual(body["commands"][0]["key"], "abc")

        status, body, _ = self.route("POST", "/api/background", {"action": "output", "key": "abc"})
        self.assertEqual(status, 200)
        self.assertEqual(body["output"], "done")
        self.assertEqual(body["command"]["key"], "abc")

        status, _, _ = self.route("POST", "/api/background", {"action": "output"})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
