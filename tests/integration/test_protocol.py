"""End-to-end protocol checks against an isolated fake bridge.

These tests exercise the real HTTP client and CLI code paths. They run against
whatever fake bridge the fixtures can start, so the same assertions cover the
compiled Rust server, ``ce-underscore --app-harness`` with the fake backend,
and the in-process Python fake.
"""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from .conftest import PNG_SIGNATURE, BridgeHandle, CliRunner

pytestmark = pytest.mark.integration


def test_state_reports_identity(cli: CliRunner, fake_bridge: BridgeHandle) -> None:
    """``state`` returns the bridge identity and capabilities."""

    result = cli.run("state", "--json")

    assert result.returncode == 0, result.stderr

    payload = result.json()

    assert isinstance(payload.get("platform"), str)
    assert isinstance(payload.get("version"), str)
    assert isinstance(payload.get("backend"), str)
    assert isinstance(payload.get("capabilities"), list)
    assert payload.get("health") in {"ready", "degraded", "unavailable"}


def test_windows_lists_top_level_windows(cli: CliRunner, fake_bridge: BridgeHandle) -> None:
    """``windows`` returns at least one visible window with a handle and title."""

    windows = list_windows(cli)

    assert windows, "fake backend reported no windows"

    for window in windows:
        assert isinstance(window.get("handle"), str)
        assert isinstance(window.get("title"), str)
        assert isinstance(window.get("pid"), int)


def test_snapshot_has_structurally_valid_elements(
    cli: CliRunner, fake_bridge: BridgeHandle
) -> None:
    """A snapshot carries a window, unique ids, roles, and budget metadata."""

    title = first_window_title(cli)
    result = cli.run("snapshot", "--window", title, "--json")

    assert result.returncode == 0, result.stderr

    snapshot = result.json()

    assert isinstance(snapshot.get("window"), dict)
    assert isinstance(snapshot.get("elements"), list) and snapshot["elements"]
    assert isinstance(snapshot.get("truncated"), bool)
    assert isinstance(snapshot.get("max_depth"), int)
    assert isinstance(snapshot.get("max_elements"), int)
    assert snapshot["total_elements"] >= len(snapshot["elements"])

    ids = [element["id"] for element in snapshot["elements"]]

    assert len(ids) == len(set(ids)), "element ids must be unique within a snapshot"

    for element in snapshot["elements"]:
        assert isinstance(element.get("control_type"), str) and element["control_type"]
        assert isinstance(element.get("depth"), int)
        assert isinstance(element.get("patterns"), list)
        assert isinstance(element.get("enabled"), bool)
        assert isinstance(element.get("sensitive"), bool)


def test_invoke_resolves_snapshot_id(cli: CliRunner, fake_bridge: BridgeHandle) -> None:
    """Snapshot an element, then invoke it in a separate invocation by id."""

    title = first_window_title(cli)
    snapshot = snapshot_window(cli, title)
    element = first_element(snapshot, pattern="Invoke")

    result = cli.run("invoke", "--window", title, "--id", str(element["id"]), "--json")

    assert result.returncode == 0, result.stderr

    payload = result.json()

    assert payload.get("delivered") is True
    assert payload.get("uncertain") is False


def test_set_value_resolves_snapshot_id_and_reads_back(
    cli: CliRunner, fake_bridge: BridgeHandle
) -> None:
    """Snapshot an editable control, write it by id, then read the value back."""

    title = first_window_title(cli)
    snapshot = snapshot_window(cli, title)
    element = first_element(snapshot, pattern="Value")
    value = f"integration-{fake_bridge.kind}"

    write = cli.run(
        "set-value",
        "--window",
        title,
        "--id",
        str(element["id"]),
        "--value",
        value,
        "--json",
    )

    assert write.returncode == 0, write.stderr
    assert write.json().get("delivered") is True
    assert write.json().get("verified") is True

    read = cli.run("get-value", "--window", title, "--id", str(element["id"]), "--json")

    assert read.returncode == 0, read.stderr
    assert read.json().get("value") is not None

    if fake_bridge.is_rust:
        assert read.json().get("value") == value


def test_token_rejection_returns_401(fake_bridge: BridgeHandle) -> None:
    """Requests with a wrong or missing token are rejected before dispatch."""

    with pytest.raises(urllib.error.HTTPError) as wrong:
        request_state(fake_bridge, token="0" * len(fake_bridge.token) or "wrong")

    assert wrong.value.code == 401

    with pytest.raises(urllib.error.HTTPError) as missing:
        request_state(fake_bridge, token=None)

    assert missing.value.code == 401

    status, payload = request_state(fake_bridge)

    assert status == 200
    assert payload.get("ok") is True


def test_bridge_file_override_is_honoured(
    cli: CliRunner, fake_bridge: BridgeHandle, tmp_path: Path
) -> None:
    """``CECLI_BRIDGE_FILE`` selects the discovery file, not a hardcoded path."""

    alternate = tmp_path / "alternate" / "bridge.json"
    alternate.parent.mkdir()
    alternate.write_text(fake_bridge.bridge_path.read_text(encoding="utf-8"), encoding="utf-8")

    found = cli.run("state", "--json", env={"CECLI_BRIDGE_FILE": str(alternate)})

    assert found.returncode == 0, found.stderr
    assert found.json().get("health") in {"ready", "degraded"}

    missing = tmp_path / "missing" / "bridge.json"
    absent = cli.run("state", "--json", env={"CECLI_BRIDGE_FILE": str(missing)})

    assert absent.returncode == 4
    assert "bridge" in (absent.stderr + absent.stdout).lower()


def test_version_mismatch_is_bridge_unavailable(cli: CliRunner, fake_bridge: BridgeHandle) -> None:
    """A bridge.json from another version exits 4 and names the mismatch."""

    fake_bridge.write_version("9.9.9")

    result = cli.run("state", "--json")

    assert result.returncode == 4

    payload = result.json()

    assert payload.get("ok") is False
    assert payload.get("error", {}).get("type") == "version_mismatch"


def test_truncation_flags_are_explicit(cli: CliRunner, fake_bridge: BridgeHandle) -> None:
    """Budget limits set ``truncated`` and never invent extra elements."""

    title = first_window_title(cli)
    result = cli.run(
        "snapshot",
        "--window",
        title,
        "--max-depth",
        "1",
        "--max-elements",
        "2",
        "--json",
    )

    assert result.returncode == 0, result.stderr

    snapshot = result.json()

    assert snapshot.get("truncated") is True
    assert snapshot.get("max_depth") == 1
    assert snapshot.get("max_elements") == 2
    assert snapshot["total_elements"] >= len(snapshot["elements"])

    if fake_bridge.is_rust:
        assert len(snapshot["elements"]) <= 2


def test_transport_timeout_maps_to_uncertain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bridge that answers too slowly raises ``uncertain`` and is not retried."""

    from cecli.helpers.app_harness.client import AppClient, AppHarnessError

    server = SlowBridge(tmp_path, delay=1.5)
    server.start()
    monkeypatch.setenv("CECLI_BRIDGE_FILE", str(server.bridge_path))
    monkeypatch.delenv("CECLI_BRIDGE_VERSION_SKIP", raising=False)
    monkeypatch.delenv("CECLI_APP_TIMEOUT_MS", raising=False)

    try:
        client = AppClient(timeout_ms=200)

        with pytest.raises(AppHarnessError) as caught:
            client.action("Slow Window", "invoke", target={"name": "Save"})

        assert caught.value.kind == "uncertain"
        assert server.request_count == 1, "timed-out actions must not be retried"
    finally:
        server.stop()


def test_screenshot_returns_png_bytes(
    cli: CliRunner, fake_bridge: BridgeHandle, tmp_path: Path
) -> None:
    """``screenshot`` writes a file that begins with the PNG signature."""

    title = first_window_title(cli)
    output = tmp_path / "shot.png"
    result = cli.run("screenshot", "--window", title, "--out", str(output), "--json")

    assert result.returncode == 0, result.stderr

    payload = result.json()
    data = output.read_bytes()

    assert data.startswith(PNG_SIGNATURE)
    assert len(data) > len(PNG_SIGNATURE)
    assert payload.get("bytes") == len(data)
    assert Path(payload.get("path", "")) == output


def list_windows(cli: CliRunner) -> list[dict[str, Any]]:
    """Return the parsed ``windows`` payload."""

    result = cli.run("windows", "--json")

    assert result.returncode == 0, result.stderr

    payload = result.json()

    assert isinstance(payload, list)
    return payload


def first_window_title(cli: CliRunner) -> str:
    """Return the title of the first window reported by the fake bridge."""

    windows = list_windows(cli)

    assert windows, "fake backend reported no windows"
    return str(windows[0]["title"])


def snapshot_window(cli: CliRunner, title: str) -> dict[str, Any]:
    """Snapshot a window and return the parsed payload."""

    result = cli.run("snapshot", "--window", title, "--json")

    assert result.returncode == 0, result.stderr
    return result.json()


def first_element(snapshot: dict[str, Any], pattern: str) -> dict[str, Any]:
    """Return the first enabled, non-sensitive element exposing ``pattern``."""

    for element in snapshot.get("elements", []):
        if pattern not in element.get("patterns", []):
            continue

        if element.get("sensitive") or not element.get("enabled", True):
            continue

        return element

    raise AssertionError(f"snapshot has no enabled element with pattern {pattern!r}")


def request_state(
    bridge: BridgeHandle, token: str | None = "__default__"
) -> tuple[int, dict[str, Any]]:
    """Call ``/api/app/state`` with an explicit or default token."""

    headers = {"Accept": "application/json"}

    if token == "__default__":
        headers["X-Cecli-Token"] = bridge.token
    elif token is not None:
        headers["X-Cecli-Token"] = token

    request = urllib.request.Request(
        f"http://127.0.0.1:{bridge.port}/api/app/state", headers=headers, method="GET"
    )

    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


class SlowBridge:
    """Minimal bridge that delays every response past a short client timeout."""

    def __init__(self, directory: Path, delay: float = 1.5) -> None:
        self.delay = delay
        self.request_count = 0
        self.token = "cd" * 32
        self.bridge_path = directory / "bridge.json"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowHandler)
        self.server.slow_bridge = self  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._write_bridge()

    @property
    def port(self) -> int:
        """Bound loopback port."""

        return int(self.server.server_address[1])

    def start(self) -> None:
        """Serve requests on a daemon thread."""

        self.thread.start()

    def stop(self) -> None:
        """Stop the server and join the serving thread."""

        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _write_bridge(self) -> None:
        payload = {
            "version": "0.1.0",
            "platform": "fake",
            "host": "127.0.0.1",
            "port": self.port,
            "token": self.token,
            "pid": 4242,
            "mode": "bridge",
            "started_at": "2026-11-19T12:00:00Z",
        }
        self.bridge_path.write_text(json.dumps(payload), encoding="utf-8")


class _SlowHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._handle()

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._handle()

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _handle(self) -> None:
        bridge: SlowBridge = self.server.slow_bridge  # type: ignore[attr-defined]
        bridge.request_count += 1
        length = int(self.headers.get("Content-Length") or 0)

        if length:
            self.rfile.read(length)

        threading.Event().wait(bridge.delay)

        body = json.dumps(
            {
                "ok": True,
                "action": "action",
                "data": {
                    "action": "invoke",
                    "delivered": True,
                    "verified": True,
                    "uncertain": False,
                },
                "error": None,
                "health": "ready",
            }
        ).encode("utf-8")

        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            pass
