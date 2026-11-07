#!/usr/bin/env python3
"""End-to-end tests for desktop/server.py against a scripted ACP agent.

Every test owns a server process and a fake ``cecli --acp`` child, so the
suite exercises the real subprocess, JSON-RPC, HTTP and SSE paths together.
Only the standard library is used and the tests skip when sockets are absent.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import queue
import re
import shlex
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server.py"
FAKE_AGENT = Path(__file__).resolve().parent / "fake_acp_agent.py"


class EventReader:
    """Background reader for one SSE connection over a raw socket."""

    def __init__(self, host: str, port: int) -> None:
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stop = threading.Event()
        self._sock = socket.create_connection((host, port), timeout=5.0)
        self._sock.sendall(
            f"GET /api/events HTTP/1.1\r\nHost: {host}:{port}\r\nAccept: text/event-stream\r\n\r\n".encode(
                "ascii"
            )
        )
        self._sock.settimeout(0.5)
        self._buffer = b""
        self._read_headers()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def _read_headers(self) -> None:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise AssertionError("SSE connection closed during headers")
            data += chunk
            if len(data) > 64 * 1024:
                raise AssertionError("SSE headers too large")
        head, self._buffer = data.split(b"\r\n\r\n", 1)
        status_line = head.split(b"\r\n", 1)[0].decode("latin-1")
        parts = status_line.split()
        if len(parts) < 2 or parts[1] != "200":
            raise AssertionError(f"SSE connect failed: {status_line}")

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            try:
                chunk = self._sock.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                return
            if not chunk:
                return
            self._buffer += chunk
            while b"\n" in self._buffer:
                line, self._buffer = self._buffer.split(b"\n", 1)
                text = line.decode("utf-8", errors="replace").strip()
                if not text.startswith("data: "):
                    continue
                try:
                    event = json.loads(text[len("data: ") :])
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    self.events.put(event)

    def collect_until(
        self, predicate: Callable[[dict[str, Any]], bool], timeout: float = 6.0
    ) -> list[dict[str, Any]]:
        """Consume events through the first match and return them in order."""
        found: list[dict[str, Any]] = []
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(f"timed out waiting for event; got {found[-5:]}")
            try:
                event = self.events.get(timeout=remaining)
            except queue.Empty:
                raise AssertionError(f"timed out waiting for event; got {found[-5:]}") from None
            found.append(event)
            if predicate(event):
                return found

    def drain(self, duration: float = 0.25) -> list[dict[str, Any]]:
        """Drop events that arrived before the interesting action."""
        dropped: list[dict[str, Any]] = []
        deadline = time.monotonic() + duration
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return dropped
            try:
                dropped.append(self.events.get(timeout=remaining))
            except queue.Empty:
                return dropped

    def close(self) -> None:
        self._stop.set()
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout=1.0)


class BridgeTest(unittest.TestCase):
    """Base fixture: one server process per test."""

    workspace: Path
    process: subprocess.Popen[bytes]
    events: list[EventReader]

    @classmethod
    def setUpClass(cls) -> None:
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.bind(("127.0.0.1", 0))
            probe.close()
        except OSError as err:
            raise unittest.SkipTest(f"sockets are unavailable: {err}") from err

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name) / "workspace"
        self.workspace.mkdir()
        self.host = "127.0.0.1"
        self.port = free_port()
        self.events = []

        wrapper = Path(self.temp_dir.name) / "fake-cecli"
        wrapper.write_text(
            f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(FAKE_AGENT))} "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)

        self.process = subprocess.Popen(
            [
                sys.executable,
                str(SERVER),
                "--host",
                self.host,
                "--port",
                str(self.port),
                "--workspace",
                str(self.workspace),
                "--cecli",
                str(wrapper),
            ],
            cwd=str(ROOT.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.wait_listening()

    def tearDown(self) -> None:
        for reader in self.events:
            reader.close()
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.communicate(timeout=5)
        self.temp_dir.cleanup()

    def open_events(self) -> EventReader:
        reader = EventReader(self.host, self.port)
        self.events.append(reader)
        return reader

    def wait_listening(self, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                stderr = self.process.stderr.read().decode("utf-8", errors="replace")
                raise AssertionError(f"server exited during startup:\n{stderr}")
            try:
                status, _ = self.request("GET", "/api/health", timeout=1.0)
            except OSError:
                time.sleep(0.05)
                continue
            if status == 200:
                return
            time.sleep(0.05)
        raise AssertionError("server did not start listening")

    def wait_ready(self, timeout: float = 10.0) -> dict[str, Any]:
        return self.wait_state(lambda state: state.get("status") == "ready", timeout)

    def wait_state(
        self, predicate: Callable[[dict[str, Any]], bool], timeout: float = 10.0
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            try:
                status, last = self.request("GET", "/api/state", timeout=2.0)
            except OSError:
                time.sleep(0.05)
                continue
            if status == 200 and predicate(last):
                return last
            time.sleep(0.05)
        raise AssertionError(f"state never matched; last state: {last}")

    def request(
        self, method: str, path: str, body: dict[str, Any] | None = None, timeout: float = 5.0
    ) -> tuple[int, dict[str, Any]]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"http://{self.host}:{self.port}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, decode_body(response.read())
        except urllib.error.HTTPError as err:
            try:
                return err.code, decode_body(err.read())
            finally:
                err.close()

    def test_health_and_state(self) -> None:
        status, health = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(health["ok"])
        self.assertIn(health["status"], ("starting", "ready"))

        state = self.wait_ready()
        self.assertFalse(state["busy"])
        self.assertEqual(state["workspace"], str(self.workspace))
        self.assertEqual(state["sessionId"], "fake-session")
        self.assertEqual(state["agent"]["name"], "fake-acp")
        self.assertTrue(state["configOptions"])
        self.assertIn("currentModeId", state["modes"])
        self.assertIsInstance(state["clients"], int)

    def test_completion_route(self) -> None:
        self.wait_ready()

        status, body = self.request("POST", "/api/complete", {"text": "/h"})

        self.assertEqual(status, 200)
        self.assertIn("/help", body["suggestions"])
        self.assertEqual(body["descriptions"]["/help"], "Show help")

    def test_history_replays_the_conversation_stream(self) -> None:
        self.wait_ready()

        status, body = self.request("GET", "/api/history")

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["messages"][0]["role"], "user")
        self.assertIn("Hello there", body["messages"][0]["content"])
        self.assertEqual(body["messages"][1]["content"], "Hi, I can help.")
        self.assertEqual(body["messages"][2]["toolCalls"][0]["name"], "ReadFile")
        self.assertEqual(body["subagents"], [])

    def test_workflow_runs_as_a_prompt(self) -> None:
        self.wait_ready()

        status, body = self.request("POST", "/api/workflows", {"action": "run", "name": "demo"})

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        state = self.wait_state(lambda value: value.get("busy") is True)
        self.assertTrue(state["busy"])

    def test_subagent_updates_reach_the_state_tree(self) -> None:
        self.wait_ready()

        status, _ = self.request("POST", "/api/prompt", {"text": "spawn worker"})

        self.assertEqual(status, 202)
        state = self.wait_state(
            lambda value: any(
                agent.get("sessionId") == "child-1" for agent in value.get("subagents") or []
            )
        )
        agent = next(item for item in state["subagents"] if item["sessionId"] == "child-1")
        self.assertEqual(agent["title"], "worker")

    def test_session_ready_via_events(self) -> None:
        reader = self.open_events()
        events = reader.collect_until(lambda event: event.get("type") == "session")
        self.assertTrue(any(event.get("type") == "status" for event in events), "no status event")
        session = events[-1]
        self.assertEqual(session["sessionId"], "fake-session")
        self.assertTrue(session["configOptions"])
        self.assertIsInstance(session["modes"], dict)

        state = self.wait_ready()
        self.assertEqual(state["sessionId"], session["sessionId"])

    def test_prompt_streams_events_then_permission(self) -> None:
        self.wait_ready()
        reader = self.open_events()
        reader.drain()

        status, body = self.request("POST", "/api/prompt", {"text": "hello"})
        self.assertEqual(status, 202)
        self.assertTrue(body["ok"])

        events = reader.collect_until(lambda event: event.get("type") == "permission")
        updates = [
            event["update"].get("sessionUpdate")
            for event in events
            if event.get("type") == "update"
        ]
        self.assertEqual(
            updates[:6],
            [
                "agent_thought_chunk",
                "agent_message_chunk",
                "tool_call",
                "tool_call_update",
                "plan",
                "usage_update",
            ],
        )

        permission = events[-1]
        self.assertEqual(
            set(permission),
            {"type", "requestId", "sessionId", "toolCall", "options", "bridgeId"},
        )
        self.assertEqual(permission["sessionId"], "fake-session")
        self.assertEqual([item["optionId"] for item in permission["options"]], ["y", "n"])

        state = self.wait_state(lambda snapshot: snapshot.get("busy") is True)
        self.assertTrue(state["busy"])
        self.assertEqual(
            set(state["permissions"][0]),
            {"requestId", "sessionId", "toolCall", "options", "bridgeId"},
        )

        status, body = self.request("POST", "/api/prompt", {"text": "again"})
        self.assertEqual(status, 409)
        self.assertFalse(body["ok"])

        status, body = self.request(
            "POST",
            "/api/permission",
            {"requestId": permission["requestId"], "optionId": "y"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

        finished = reader.collect_until(lambda event: event.get("type") == "prompt_done")
        resolved = [event for event in finished if event.get("type") == "permission_resolved"]
        self.assertTrue(resolved)
        self.assertEqual(resolved[0]["optionId"], "y")
        self.assertEqual(finished[-1]["stopReason"], "end_turn")

        state = self.wait_state(lambda snapshot: snapshot.get("busy") is False)
        self.assertFalse(state["busy"])
        self.assertEqual(state["permissions"], [])

    def test_prompt_while_busy_is_conflict(self) -> None:
        self.wait_ready()
        reader = self.open_events()
        reader.drain()

        status, _ = self.request("POST", "/api/prompt", {"text": "hold"})
        self.assertEqual(status, 202)
        permission_batch = reader.collect_until(lambda event: event.get("type") == "permission")
        self.assertTrue(permission_batch)

        status, body = self.request("POST", "/api/prompt", {"text": "second"})
        self.assertEqual(status, 409)
        self.assertFalse(body["ok"])

        self.request("POST", "/api/cancel")
        reader.collect_until(lambda event: event.get("type") == "prompt_done", timeout=6.0)

    def test_cancel_reports_cancelled(self) -> None:
        self.wait_ready()
        reader = self.open_events()
        reader.drain()

        status, _ = self.request("POST", "/api/prompt", {"text": "long task"})
        self.assertEqual(status, 202)
        reader.collect_until(lambda event: event.get("type") == "permission")

        status, body = self.request("POST", "/api/cancel")
        self.assertEqual(status, 202)
        self.assertTrue(body["ok"])

        finished = reader.collect_until(lambda event: event.get("type") == "prompt_done")
        self.assertEqual(finished[-1]["stopReason"], "cancelled")
        self.assertFalse(any(event.get("type") == "permission" for event in finished))
        state = self.wait_state(lambda snapshot: snapshot.get("busy") is False)
        self.assertFalse(state["busy"])
        self.assertEqual(state["permissions"], [])

    def test_cancelled_permission_reaches_the_agent(self) -> None:
        self.wait_ready()
        reader = self.open_events()
        reader.drain()

        status, _ = self.request("POST", "/api/prompt", {"text": "cancel permission"})
        self.assertEqual(status, 202)
        events = reader.collect_until(lambda event: event.get("type") == "permission")
        permission = events[-1]

        status, body = self.request(
            "POST",
            "/api/permission",
            {"requestId": permission["requestId"], "optionId": None},
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

        finished = reader.collect_until(
            lambda event: event.get("type") == "prompt_done", timeout=8.0
        )
        if not any(
            event.get("type") == "log"
            and "permission outcome=cancelled" in event.get("message", "")
            for event in finished
        ):
            finished += reader.collect_until(
                lambda event: event.get("type") == "log"
                and "permission outcome=cancelled" in event.get("message", ""),
                timeout=8.0,
            )

        self.assertTrue(
            any(
                event.get("type") == "log"
                and "permission outcome=cancelled" in event.get("message", "")
                for event in finished
            )
        )
        resolved = [event for event in finished if event.get("type") == "permission_resolved"]
        self.assertTrue(resolved)
        self.assertIsNone(resolved[0]["optionId"])
        done = next(event for event in finished if event.get("type") == "prompt_done")
        self.assertEqual(done["stopReason"], "end_turn")

    def test_sigterm_exits_with_an_open_event_stream(self) -> None:
        self.wait_ready()
        self.open_events()

        self.process.terminate()
        try:
            code = self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.fail("server did not exit after SIGTERM with an open SSE client")

        self.assertEqual(code, 0)

    def test_second_permission_survives_first_answer(self) -> None:
        self.wait_ready()
        reader = self.open_events()
        reader.drain()

        status, _ = self.request("POST", "/api/prompt", {"text": "two permissions"})
        self.assertEqual(status, 202)

        first_batch = reader.collect_until(lambda event: event.get("type") == "permission")
        second_batch = reader.collect_until(lambda event: event.get("type") == "permission")
        first_id = first_batch[-1]["requestId"]
        second_id = second_batch[-1]["requestId"]
        self.assertNotEqual(first_id, second_id)

        status, _ = self.request(
            "POST", "/api/permission", {"requestId": first_id, "optionId": "y"}
        )
        self.assertEqual(status, 200)

        state = self.wait_state(
            lambda snapshot: [item["requestId"] for item in snapshot.get("permissions") or []]
            == [second_id]
        )
        self.assertTrue(state["busy"])

        status, _ = self.request(
            "POST", "/api/permission", {"requestId": second_id, "optionId": "y"}
        )
        self.assertEqual(status, 200)

        finished = reader.collect_until(
            lambda event: event.get("type") == "prompt_done", timeout=8.0
        )
        resolved = [event for event in finished if event.get("type") == "permission_resolved"]
        self.assertEqual(resolved[-1]["requestId"], second_id)
        self.wait_state(lambda snapshot: snapshot.get("permissions") == [])

    def test_unknown_permission_is_not_found(self) -> None:
        self.wait_ready()
        status, body = self.request(
            "POST", "/api/permission", {"requestId": 987654, "optionId": "y"}
        )
        self.assertEqual(status, 404)
        self.assertFalse(body["ok"])

    def test_config_option_post(self) -> None:
        self.wait_ready()
        state = self.wait_state(lambda snapshot: option_value(snapshot, "mode") == "agent")
        self.assertEqual(state["status"], "ready")

        status, body = self.request("POST", "/api/config", {"configId": "mode", "value": "code"})
        self.assertEqual(status, 409)
        self.assertFalse(body["ok"])

        state = self.wait_state(lambda snapshot: option_value(snapshot, "mode") == "agent")
        self.assertEqual(state["modes"]["currentModeId"], "agent")

    def test_new_session_clears_the_previous_id(self) -> None:
        self.wait_ready()

        status, body = self.request("POST", "/api/new_session", {})
        self.assertEqual(status, 202)
        self.assertTrue(body["ok"])

        state = self.wait_state(lambda snapshot: snapshot.get("sessionId") is None)
        self.assertEqual(state["status"], "starting")
        self.assertEqual(state["configOptions"], [])
        self.assertEqual(state["modes"], {})

        state = self.wait_ready()
        self.assertEqual(state["sessionId"], "fake-session")

    def test_static_path_traversal_is_denied(self) -> None:
        for path in (
            "/static/../server.py",
            "/static/%2e%2e/server.py",
            "/static/..%2fserver.py",
        ):
            connection = http.client.HTTPConnection(self.host, self.port, timeout=3)
            try:
                connection.request("GET", path)
                response = connection.getresponse()
                response.read()
                self.assertIn(response.status, (403, 404), path)
            finally:
                connection.close()

    def test_restart_spawns_a_clean_child(self) -> None:
        self.wait_ready()
        reader = self.open_events()
        reader.drain()

        status, body = self.request("POST", "/api/restart")
        self.assertEqual(status, 202)
        self.assertTrue(body["ok"])

        reader.collect_until(
            lambda event: event.get("type") == "status" and event.get("status") == "starting",
            timeout=8.0,
        )
        events = reader.collect_until(lambda event: event.get("type") == "session", timeout=8.0)
        self.assertTrue(
            any(
                event.get("type") == "status" and event.get("status") == "ready" for event in events
            )
        )
        self.assertEqual(events[-1]["sessionId"], "fake-session")

        state = self.wait_ready()
        self.assertFalse(state["busy"])
        status, _ = self.request("POST", "/api/prompt", {"text": "after restart"})
        self.assertEqual(status, 202)
        reader.collect_until(lambda event: event.get("type") == "permission", timeout=8.0)

    def test_index_page_and_assets_are_served(self) -> None:
        with urllib.request.urlopen(f"http://{self.host}:{self.port}/", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("text/html", response.headers["Content-Type"])
            self.assertEqual(response.headers["Cache-Control"], "no-cache")
            page = response.read().decode("utf-8")

        self.assertRegex(page, r'/static/assets/[^"]+\.js')
        self.assertRegex(page, r'/static/assets/[^"]+\.css')
        self.assertNotIn("/static/app.js", page)
        self.assertNotIn("/static/styles.css", page)

        assets = re.findall(r'/static/(assets/[^"]+\.(?:js|css))', page)
        self.assertEqual(len(assets), 2, page)

        for asset in assets:
            with urllib.request.urlopen(
                f"http://{self.host}:{self.port}/static/{asset}", timeout=5
            ) as asset_response:
                self.assertEqual(asset_response.status, 200, asset)
                self.assertEqual(
                    asset_response.headers["Cache-Control"],
                    "public, max-age=31536000, immutable",
                )

    def test_prompt_rejects_wrong_media_type_and_empty_text(self) -> None:
        self.wait_ready()
        status, _ = self.raw_request(
            "POST",
            "/api/prompt",
            {"Content-Type": "text/plain"},
            b'{"text": "plain"}',
        )
        self.assertEqual(status, 415)

        status, _ = self.request("POST", "/api/prompt", {"text": "   "})
        self.assertEqual(status, 400)

        status, _ = self.request("POST", "/api/prompt", {})
        self.assertEqual(status, 400)

    def test_cross_origin_and_foreign_host_are_forbidden(self) -> None:
        self.wait_ready()
        status, _ = self.raw_request(
            "POST",
            "/api/cancel",
            {"Origin": "http://evil.example"},
            b"{}",
        )
        self.assertEqual(status, 403)

        status, _ = self.raw_request(
            "GET",
            "/api/state",
            {"Host": "evil.example"},
            None,
        )
        self.assertEqual(status, 403)

    def test_static_dotfile_is_not_found(self) -> None:
        status, _ = self.raw_request("GET", "/static/.build-hash", {}, None)
        self.assertEqual(status, 404)

    def test_static_null_byte_is_not_found(self) -> None:
        status, _ = self.raw_request("GET", "/static/%00", {}, None)
        self.assertEqual(status, 404)

    def test_oversized_body_is_rejected(self) -> None:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=3)
        try:
            connection.putrequest("POST", "/api/prompt")
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", str(2 * 1024 * 1024))
            connection.endheaders()
            response = connection.getresponse()
            response.read()
            self.assertEqual(response.status, 413)
        finally:
            connection.close()

    def raw_request(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        body: bytes | None,
    ) -> tuple[int, bytes]:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_ipv6_loopback_origin_is_allowed(self) -> None:
        port = self.port
        status, _ = self.raw_request(
            "GET",
            "/api/state",
            {"Host": f"[::1]:{port}", "Origin": f"http://[::1]:{port}"},
            None,
        )
        self.assertEqual(status, 200)

    def test_sessions_api_supports_multiple_parents(self) -> None:
        self.wait_ready()
        status, body = self.request("GET", "/api/sessions")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["sessions"]), 1)

        status, created = self.request("POST", "/api/sessions", {"title": "second"})
        self.assertEqual(status, 201)
        bridge_id = created["bridgeId"]

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            _, listing = self.request("GET", "/api/sessions")
            matching = [item for item in listing["sessions"] if item["bridgeId"] == bridge_id]
            if matching and matching[0]["status"] == "ready":
                break
            time.sleep(0.05)
        else:
            self.fail("second session never became ready")

        status, _ = self.request("POST", "/api/prompt", {"text": "hello"})
        self.assertEqual(status, 400)
        status, _ = self.request("POST", "/api/prompt", {"bridgeId": bridge_id, "text": "hello"})
        self.assertEqual(status, 202)

    def test_websocket_channel_returns_only_command_results(self) -> None:
        self.wait_ready()
        with urllib.request.urlopen(f"http://{self.host}:{self.port}/", timeout=5) as page:
            html = page.read().decode("utf-8")
        match = re.search(r'__CECLI_TOKEN__="([^"]+)"', html)
        self.assertIsNotNone(match)
        token = match.group(1)

        connection = socket.create_connection((self.host, self.port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        connection.sendall(
            (
                f"GET /ws HTTP/1.1\r\nHost: {self.host}:{self.port}\r\n"
                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                f"Sec-WebSocket-Protocol: cecli.desktop.v1, token.{token}\r\n\r\n"
            ).encode("ascii")
        )
        try:
            head = b""
            while b"\r\n\r\n" not in head:
                head += connection.recv(4096)
            self.assertIn(b"101 Switching Protocols", head)

            message = json.dumps({"id": "1", "command": "sessions.list", "params": {}}).encode(
                "utf-8"
            )
            mask = os.urandom(4)
            payload = bytes(value ^ mask[index % 4] for index, value in enumerate(message))
            connection.sendall(bytes([0x81, 0x80 | len(message)]) + mask + payload)

            header = connection.recv(2)
            length = header[1] & 0x7F
            if length == 126:
                length = struct.unpack("!H", connection.recv(2))[0]
            data = b""
            while len(data) < length:
                data += connection.recv(length - len(data))
            reply = json.loads(data.decode("utf-8"))
            self.assertTrue(reply.get("ok"))
            self.assertNotIn("event", reply)
            self.assertIn("sessions", reply.get("result", {}))
        finally:
            connection.close()


# Test method names are intentionally descriptive; keep helpers below the suites.
def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def decode_body(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def option_value(state: dict[str, Any], config_id: str) -> Any:
    for option in state.get("configOptions") or []:
        if option.get("id") == config_id:
            return option.get("currentValue")
    return None


if __name__ == "__main__":
    unittest.main()
