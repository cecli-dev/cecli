"""In-process fake bridge used by the app-harness tests.

The fake speaks the same envelope shape and paths as
``crates/ce-app-bridge/src/protocol.rs`` but serves canned data. Every request
is recorded so tests can assert headers, bodies, and ordering.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-png-payload"

FIND_MISS_CANDIDATES = ['Button "Save" (id2)', 'Button "Save As"']

WINDOW = {
    "handle": "0x1234",
    "pid": 4242,
    "process_name": "excel",
    "title": "Excel - Book1",
    "class_name": "XLMAIN",
    "bounds": {"left": 0, "top": 0, "width": 800, "height": 600},
    "foreground": True,
    "enabled": True,
}

ELEMENTS = [
    {
        "id": 0,
        "parent": None,
        "depth": 0,
        "runtime_id": "42.1",
        "control_type": "Window",
        "name": "Excel - Book1",
        "automation_id": None,
        "class_name": "XLMAIN",
        "value": None,
        "enabled": True,
        "offscreen": False,
        "bounds": {"left": 0, "top": 0, "width": 800, "height": 600},
        "patterns": ["Window"],
        "sensitive": False,
    },
    {
        "id": 1,
        "parent": 0,
        "depth": 1,
        "runtime_id": "42.2",
        "control_type": "Edit",
        "name": "Address",
        "automation_id": "A1",
        "class_name": "Edit",
        "value": "",
        "enabled": True,
        "offscreen": False,
        "bounds": {"left": 10, "top": 20, "width": 200, "height": 24},
        "patterns": ["Value"],
        "sensitive": False,
    },
    {
        "id": 2,
        "parent": 0,
        "depth": 1,
        "runtime_id": "42.3",
        "control_type": "Button",
        "name": "Save",
        "automation_id": "SaveButton",
        "class_name": "Button",
        "value": None,
        "enabled": True,
        "offscreen": False,
        "bounds": {"left": 300, "top": 20, "width": 80, "height": 24},
        "patterns": ["Invoke"],
        "sensitive": False,
    },
    {
        "id": 3,
        "parent": 1,
        "depth": 2,
        "runtime_id": "42.4",
        "control_type": "Edit",
        "name": "Password",
        "automation_id": "PasswordField",
        "class_name": "Edit",
        "value": None,
        "enabled": False,
        "offscreen": True,
        "bounds": None,
        "patterns": ["Value"],
        "sensitive": True,
    },
]

DIALOG_WINDOW = {
    "handle": "0x9001",
    "pid": 4242,
    "process_name": "excel",
    "title": "Microsoft Excel",
    "class_name": "#32770",
    "bounds": {"left": 200, "top": 150, "width": 400, "height": 200},
    "foreground": True,
    "dialog": True,
    "enabled": True,
}

STATE = {
    "platform": "linux",
    "version": "0.1.0",
    "backend": "fake",
    "capabilities": ["windows", "snapshot", "actions"],
    "health": "ready",
    "pid": 4242,
    "mode": "bridge",
    "protocol_version": "0.1.0",
}

DOCTOR = {
    "platform": "linux",
    "backend": "fake",
    "health": "degraded",
    "permissions": {"accessibility": "granted"},
    "checks": [
        {"name": "loopback", "ok": True, "detail": "bound to 127.0.0.1"},
        {"name": "token", "ok": True, "detail": "64 hex chars"},
        {"name": "screen_capture", "ok": False, "detail": "not requested"},
    ],
    "notes": ["fixture bridge"],
}


HELP = {
    "protocol_version": "0.1.0",
    "backend": "fake",
    "platform": "linux",
    "capabilities": ["windows", "snapshot", "actions"],
    "endpoints": {"snapshot": "POST {window, max_depth, max_elements, exclude_roles}"},
    "actions": {"invoke": "run an element's default action"},
    "selectors": {"name": "accessible name"},
    "capabilities_matrix": {
        "snapshot": {"actionable": True, "truncated_by": True},
        "find": {"server": True},
        "actions": {"cell_at": True},
    },
    "notes": ["actions resolve against the latest snapshot"],
}


def envelope(
    action: str,
    data: Any,
    *,
    ok: bool = True,
    error: dict[str, Any] | None = None,
    notes: list[str] | None = None,
):
    """Build a protocol envelope with a trailing-free JSON structure."""

    return {
        "ok": ok,
        "action": action,
        "data": data if ok else {},
        "error": error,
        "health": "ready" if ok else "degraded",
        **({"notes": list(notes)} if notes else {}),
    }


class FakeBridge:
    """Threaded HTTP bridge with canned responses and request recording."""

    def __init__(self, directory: Path, version: str = "0.1.0") -> None:
        self.directory = directory
        self.token = "ab" * 32
        self.action_mode = "ok"
        self.find_enabled = True
        self.find_miss_error = False
        self.snapshot_notes: list[str] = []
        self.action_outcome: str | None = None
        self.dialogs: list[dict[str, Any]] = []
        self.dialogs_route = True
        self.include_dialog_in_windows = False
        self.set_value_mode = "ok"
        self.last_set_value: str | None = None
        self.requests: list[dict[str, Any]] = []
        self.action_requests: list[dict[str, Any]] = []
        self.bridge_path = directory / "bridge.json"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.fake_bridge = self  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.write_bridge(version)

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def write_bridge(self, version: str = "0.1.0") -> Path:
        """Write ``bridge.json`` pointing at this server."""

        payload = {
            "version": version,
            "platform": "linux",
            "host": "127.0.0.1",
            "port": self.port,
            "token": self.token,
            "pid": 4242,
            "mode": "bridge",
            "started_at": "2026-11-19T12:00:00Z",
        }
        self.bridge_path.write_text(json.dumps(payload), encoding="utf-8")
        return self.bridge_path

    def start(self) -> None:
        """Start serving requests on the background thread."""

        self.thread.start()

    def stop(self) -> None:
        """Stop the server and join the thread."""

        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def paths(self) -> list[str]:
        """Return the request paths in order."""

        return [request["path"] for request in self.requests]


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._handle()

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._handle()

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _handle(self) -> None:
        fake: FakeBridge = self.server.fake_bridge  # type: ignore[attr-defined]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        body: dict[str, Any] = {}

        if raw:
            try:
                body = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                body = {}

        fake.requests.append(
            {
                "method": self.command,
                "path": self.path,
                "token": self.headers.get("X-Cecli-Token"),
                "body": body,
            }
        )

        if self.headers.get("X-Cecli-Token") != fake.token:
            self._send_json(
                401,
                envelope(
                    "error",
                    {},
                    ok=False,
                    error={"type": "unauthorized", "message": "bad token"},
                ),
            )
            return

        if self.path == "/api/app/state":
            self._send_json(200, envelope("state", STATE))
        elif self.path == "/api/app/windows":
            windows = [WINDOW]

            if fake.include_dialog_in_windows:
                windows = [WINDOW, *fake.dialogs]

            self._send_json(200, envelope("windows", windows))
        elif self.path == "/api/app/dialogs":
            if not fake.dialogs_route:
                self._send_json(
                    404,
                    envelope(
                        "error",
                        {},
                        ok=False,
                        error={"type": "not_found", "message": self.path},
                    ),
                )
                return

            self._send_json(200, envelope("dialogs", {"dialogs": list(fake.dialogs)}))
        elif self.path == "/api/app/doctor":
            self._send_json(200, envelope("doctor", DOCTOR))
        elif self.path == "/api/app/help":
            self._send_json(200, envelope("help", HELP))
        elif self.path == "/api/app/snapshot":
            snapshot = {
                "window": WINDOW,
                "elements": ELEMENTS,
                "truncated": True,
                "max_depth": body.get("max_depth") or 6,
                "max_elements": body.get("max_elements") or 50,
                "total_elements": 99,
                "actionable": bool(body.get("actionable")),
            }
            self._send_json(200, envelope("snapshot", snapshot, notes=fake.snapshot_notes))
        elif self.path == "/api/app/find" and fake.find_enabled:
            matches, count, truncated = _find_matches(body.get("match") or {}, body.get("limit"))

            if not matches and fake.find_miss_error:
                self._send_json(
                    200,
                    envelope(
                        "find",
                        {},
                        ok=False,
                        error={
                            "type": "target_not_found",
                            "message": "no element matches the requested selector",
                            "details": {
                                "candidates": list(FIND_MISS_CANDIDATES),
                                "scope": "window",
                            },
                        },
                    ),
                )

                return

            self._send_json(
                200,
                envelope(
                    "find",
                    {
                        "matches": matches,
                        "match_count": count,
                        "truncated": truncated,
                        "truncated_by": "limit" if truncated else None,
                    },
                ),
            )
        elif self.path == "/api/app/action":
            fake.action_requests.append(body)
            self._send_action(fake, body)
        elif self.path == "/api/app/screenshot":
            requested = str(body.get("window") or "")

            if requested and requested.casefold() not in WINDOW["title"].casefold():
                self._send_json(
                    200,
                    envelope(
                        "screenshot",
                        {},
                        ok=False,
                        error={
                            "type": "window_not_found",
                            "message": f"no window matching '{requested}'",
                        },
                    ),
                )

                return

            self._send_bytes(200, PNG_BYTES, "image/png")
        elif self.path == "/api/app/shutdown":
            self._send_json(200, envelope("shutdown", {"ok": True}))
        else:
            self._send_json(
                404,
                envelope("error", {}, ok=False, error={"type": "not_found", "message": self.path}),
            )

    def _send_action(self, fake: FakeBridge, body: dict[str, Any]) -> None:
        action = str(body.get("action") or "action")

        if fake.action_mode == "refuse":
            self._send_json(
                200,
                envelope(
                    action,
                    {},
                    ok=False,
                    error={"type": "input_blocked", "message": "control is disabled"},
                ),
            )
            return

        if fake.action_mode == "uncertain":
            result = {
                "action": action,
                "delivered": True,
                "verified": False,
                "uncertain": True,
                "message": "timed out waiting for confirmation",
            }
        elif fake.action_mode == "unverified":
            result = {
                "action": action,
                "delivered": True,
                "verified": False,
                "uncertain": False,
            }
        elif action == "cell_at":
            args = body.get("args") or {}
            row = int(args.get("row") or 0)
            column = int(args.get("column") or 0)
            name = _cell_name(row, column)
            result = {
                "action": action,
                "delivered": True,
                "verified": True,
                "uncertain": False,
                "value": name,
                "element": {
                    "id": 100 + row * 10 + column,
                    "control_type": "TableCell",
                    "name": name,
                    "value": name,
                    "path": f"Sheet1/Table/TableCell[{name}]",
                },
            }
        elif action == "set_value":
            args = body.get("args") or {}
            value = str(args.get("value") or "")

            if fake.set_value_mode == "unsupported":
                self._send_json(
                    200,
                    envelope(
                        action,
                        {},
                        ok=False,
                        error={
                            "type": "unsupported",
                            "message": "the control has no Value pattern",
                        },
                    ),
                )

                return

            verified = fake.set_value_mode != "unverified"

            if verified:
                fake.last_set_value = value

            result = {
                "action": action,
                "delivered": True,
                "verified": verified,
                "uncertain": False,
                "value": value,
            }
        elif action == "get_value":
            result = {
                "action": action,
                "delivered": True,
                "verified": True,
                "uncertain": False,
                "value": fake.last_set_value if fake.last_set_value is not None else "hello",
            }
        else:
            result = {
                "action": action,
                "delivered": True,
                "verified": True,
                "uncertain": False,
            }

        if fake.action_outcome:
            result["outcome"] = fake.action_outcome

        self._send_json(200, envelope(action, result))

    def _send_json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload).encode("utf-8")
        self._send_bytes(status, data, "application/json")

    def _send_bytes(self, status: int, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _cell_name(row: int, column: int) -> str:
    if 1 <= column <= 26:
        return f"{chr(64 + column)}{row}"

    return f"R{row}C{column}"


def _find_matches(match: dict[str, Any], limit: Any) -> tuple[list[dict[str, Any]], int, bool]:
    """Evaluate a simple role/name/value/state match spec against ELEMENTS."""

    roles = [str(role) for role in match.get("roles") or []]
    matches: list[dict[str, Any]] = []

    for element in ELEMENTS:

        if roles and not any(
            _normalize_role(role) == _normalize_role(element.get("control_type") or "")
            for role in roles
        ):
            continue

        if not _operand_matches(element.get("name"), match.get("name")):
            continue

        if not _operand_matches(element.get("value"), match.get("value")):
            continue

        if "enabled" in match and bool(element.get("enabled", True)) != bool(match["enabled"]):
            continue

        if "sensitive" in match and bool(element.get("sensitive")) != bool(match["sensitive"]):
            continue

        matches.append(element)

    count = len(matches)
    capped = limit is not None and int(limit) >= 0

    if not capped:
        return matches, count, False

    return matches[: int(limit)], count, count > int(limit)


def _operand_matches(actual: Any, spec: Any) -> bool:
    if not isinstance(spec, dict):
        return True

    expected = str(spec.get("value") or "").casefold()
    text = str(actual or "").casefold()
    op = spec.get("op") or "eq"

    if op == "contains":
        return expected in text

    if op == "prefix":
        return text.startswith(expected)

    if op == "suffix":
        return text.endswith(expected)

    return text == expected


def _normalize_role(role: str) -> str:
    return re.sub(r"[^a-z0-9]", "", role.casefold())


@pytest.fixture
def fake_bridge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeBridge:
    """Run a fake bridge and point discovery at its ``bridge.json``."""

    bridge = FakeBridge(tmp_path)
    bridge.start()
    monkeypatch.setenv("CECLI_BRIDGE_FILE", str(bridge.bridge_path))
    monkeypatch.delenv("CECLI_BRIDGE_VERSION_SKIP", raising=False)
    monkeypatch.delenv("CECLI_APP_TIMEOUT_MS", raising=False)
    monkeypatch.delenv("CECLI_CE_UNDERSCORE", raising=False)

    try:
        yield bridge
    finally:
        bridge.stop()
