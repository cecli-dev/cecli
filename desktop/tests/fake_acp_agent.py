#!/usr/bin/env python3
"""A tiny scripted ACP agent used by the desktop bridge tests.

It never calls a model. It answers the handshake, streams one of each update
kind, asks for permission and completes prompts. Run it only through the
bridge (or by hand with newline-delimited JSON-RPC on stdin/stdout).
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Any

SESSION_ID = "fake-session"
PERMISSION_BASE = 900

_stdout_lock = threading.Lock()
_config_options: list[dict[str, Any]] = []
_pending_prompt: dict[str, Any] | None = None
_permission_seq = 0


def send(message: dict[str, Any]) -> None:
    """Write one JSON-RPC message to stdout without interleaving threads."""
    line = json.dumps(message, separators=(",", ":")) + "\n"
    with _stdout_lock:
        sys.stdout.write(line)
        sys.stdout.flush()


def result(request_id: Any, value: Any) -> None:
    send({"jsonrpc": "2.0", "id": request_id, "result": value})


def error(request_id: Any, code: int, message: str) -> None:
    send({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


def update(payload: dict[str, Any]) -> None:
    send(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {"sessionId": SESSION_ID, "update": payload},
        }
    )


def default_config_options() -> list[dict[str, Any]]:
    return [
        {
            "id": "mode",
            "name": "Mode",
            "category": "mode",
            "type": "select",
            "currentValue": "ask",
            "options": [
                {"value": "ask", "name": "Ask", "description": "Ask before editing"},
                {"value": "code", "name": "Code", "description": "Edit freely"},
            ],
        },
        {
            "id": "model",
            "name": "Model",
            "category": "model",
            "type": "select",
            "currentValue": "fake-1",
            "options": [{"value": "fake-1", "name": "Fake One", "description": "Small"}],
        },
    ]


def session_state() -> dict[str, Any]:
    mode = next((option for option in _config_options if option.get("id") == "mode"), None)
    modes = {}
    if mode is not None:
        modes = {
            "currentModeId": mode["currentValue"],
            "availableModes": [
                {"id": item["value"], "name": item["name"]}
                for item in mode.get("options", [])
                if "value" in item
            ],
        }
    return {"sessionId": SESSION_ID, "configOptions": _config_options, "modes": modes}


def handle_initialize(request_id: Any) -> None:
    result(
        request_id,
        {
            "protocolVersion": 1,
            "agentCapabilities": {"loadSession": False},
            "authMethods": [],
            "agentInfo": {"name": "fake-acp", "title": "Fake ACP", "version": "0.0.1"},
        },
    )


def handle_session_new(request_id: Any) -> None:
    threading.Thread(target=_finish_session_new, args=(request_id,), daemon=True).start()


def _finish_session_new(request_id: Any) -> None:
    time.sleep(0.35)
    result(request_id, session_state())


def handle_prompt(request_id: Any, params: dict[str, Any]) -> None:
    global _pending_prompt

    text = _prompt_text(params)
    if text.strip() == "/crash":
        os._exit(3)

    if _pending_prompt is not None:
        error(request_id, -32000, "already prompting")
        return

    _pending_prompt = {"id": request_id, "permission_ids": []}

    update(
        {
            "sessionUpdate": "agent_thought_chunk",
            "content": {"type": "text", "text": "Thinking about the request.\n"},
        }
    )
    update(
        {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "Working on it. "},
        }
    )
    update(
        {
            "sessionUpdate": "tool_call",
            "toolCallId": "call-1",
            "title": "ReadFile CONTRACT.md",
            "kind": "read",
            "status": "in_progress",
            "rawInput": {"file_path": "CONTRACT.md"},
        }
    )
    update(
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": "call-1",
            "status": "completed",
            "content": [
                {
                    "type": "content",
                    "content": {"type": "text", "text": "```\ncontract body\n```"},
                }
            ],
        }
    )
    update(
        {
            "sessionUpdate": "plan",
            "entries": [
                {"content": "Inspect the workspace", "priority": "high", "status": "completed"},
                {"content": "Write the answer", "priority": "medium", "status": "in_progress"},
            ],
        }
    )
    update(
        {
            "sessionUpdate": "usage_update",
            "used": 1234,
            "size": 200000,
            "cost": {"amount": 0.001, "currency": "USD"},
        }
    )
    _ask_permission()
    if "two permissions" in text:
        _ask_permission()


def _ask_permission() -> None:
    global _permission_seq

    assert _pending_prompt is not None
    _permission_seq += 1
    request_id = PERMISSION_BASE + _permission_seq
    _pending_prompt["permission_ids"].append(request_id)
    send(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "session/request_permission",
            "params": {
                "sessionId": SESSION_ID,
                "toolCall": {
                    "toolCallId": "call-1",
                    "title": "Run the fake tool?",
                    "content": [
                        {
                            "type": "content",
                            "content": {"type": "text", "text": "fake tool input"},
                        }
                    ],
                },
                "options": [
                    {"optionId": "y", "name": "Allow", "kind": "allow_once"},
                    {"optionId": "n", "name": "Deny", "kind": "reject_once"},
                ],
            },
        }
    )


def handle_permission_response(message: dict[str, Any]) -> bool:
    """Finish the turn when the client answers our permission request."""
    global _pending_prompt

    pending = _pending_prompt
    if pending is None or message.get("id") not in pending["permission_ids"]:
        return False

    pending["permission_ids"].remove(message["id"])

    result_body = message.get("result")
    outcome = result_body.get("outcome") if isinstance(result_body, dict) else None
    outcome = outcome if isinstance(outcome, dict) else {}
    effect = outcome.get("outcome") or "unknown"
    selected = outcome.get("optionId") if effect == "selected" else None
    print(
        f"fake agent: permission outcome={effect} option={selected}",
        file=sys.stderr,
        flush=True,
    )

    if pending["permission_ids"]:
        return True

    update(
        {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "Done.\n"},
        }
    )
    result(pending["id"], {"stopReason": "end_turn"})
    _pending_prompt = None
    return True


def handle_cancel(_params: dict[str, Any]) -> None:
    global _pending_prompt

    pending = _pending_prompt
    if pending is None:
        return

    result(pending["id"], {"stopReason": "cancelled"})
    update({"sessionUpdate": "state_update", "state": "idle", "stopReason": "cancelled"})
    _pending_prompt = None


def handle_config(request_id: Any, params: dict[str, Any]) -> None:

    config_id = params.get("configId")
    value = params.get("value")
    for option in _config_options:
        if option.get("id") == config_id:
            option["currentValue"] = value
            break
    result(request_id, {"configOptions": _config_options})
    update({"sessionUpdate": "config_option_update", "configOptions": _config_options})


def _prompt_text(params: dict[str, Any]) -> str:
    parts = params.get("prompt") or []
    return "".join(
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and part.get("type") == "text"
    )


def dispatch(message: dict[str, Any]) -> None:
    """Handle one JSON-RPC request, notification or response."""
    method = message.get("method")
    if method is None:
        if not handle_permission_response(message):
            pass
        return

    request_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        handle_initialize(request_id)
    elif method == "session/new":
        handle_session_new(request_id)
    elif method == "session/prompt":
        handle_prompt(request_id, params)
    elif method == "session/set_config_option":
        handle_config(request_id, params)
    elif method == "session/cancel":
        handle_cancel(params)
    elif request_id is not None:
        error(request_id, -32601, f"Method not found: {method}")


def main() -> int:
    """Read newline-delimited JSON-RPC until stdin closes."""
    global _config_options

    _config_options = default_config_options()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as err:
            print(f"fake agent: bad JSON: {err}", file=sys.stderr, flush=True)
            continue
        if isinstance(message, dict):
            dispatch(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
