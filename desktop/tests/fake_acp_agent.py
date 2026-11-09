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
_announced_subagents: set[str] = set()
_hooks: list[dict[str, Any]] = [
    {
        "name": "guard",
        "type": "pre_tool",
        "enabled": True,
        "priority": 5,
        "description": "Blocks unsafe commands",
    },
    {
        "name": "notify",
        "type": "on_message",
        "enabled": False,
        "priority": 20,
        "description": None,
    },
]


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


def update(payload: dict[str, Any], session_id: str | None = None) -> None:
    send(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {"sessionId": session_id or SESSION_ID, "update": payload},
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
        {
            "id": "reasoning_effort",
            "name": "Reasoning effort",
            "category": "thought_level",
            "type": "select",
            "currentValue": "high",
            "options": [
                {"value": "low", "name": "Low"},
                {"value": "high", "name": "High"},
            ],
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

    if "spawn" in text:
        _announced_subagents.add("child-1")
        update(
            {
                "sessionUpdate": "subagent_update",
                "sessionId": "child-1",
                "title": "worker",
                "description": "Background worker",
                "capabilities": {},
                "state": {"state": "running"},
            }
        )
        update(
            {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "child output"},
            },
            "child-1",
        )
        update(
            {
                "sessionUpdate": "subagent_update",
                "sessionId": "child-1",
                "capabilities": {},
                "state": {"state": "idle", "stopReason": "end_turn"},
            }
        )
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


def handle_complete(request_id: Any, params: dict[str, Any]) -> None:
    """Return deterministic completion suggestions for bridge tests."""
    text = str(params.get("text") or "")

    if text.startswith("/"):
        suggestions = ["/help", "/status"]
        descriptions = {"/help": "Show help", "/status": "Show status"}
        start = 0
    elif text.startswith("@"):
        suggestions = ["README.md"]
        descriptions = {}
        start = 1
    else:
        suggestions = []
        descriptions = {}
        start = len(text)

    result(
        request_id,
        {"suggestions": suggestions, "descriptions": descriptions, "start": start},
    )


def state_details() -> dict[str, Any]:
    """Registry payload returned by ``cecli/state`` in tests."""
    return {
        "ready": True,
        "cwd": os.getcwd(),
        "gitBranch": "main",
        "skills": [{"name": "pdf", "loaded": True}],
        "mcpServers": [{"name": "github", "connected": False}],
        "workflows": [{"name": "demo"}],
        "contextFiles": [{"path": "README.md"}],
        "hooks": [
            dict(hook) for hook in sorted(_hooks, key=lambda item: (item["type"], item["priority"]))
        ],
        "subagents": [],
    }


def handle_hook(request_id: Any, params: dict[str, Any]) -> None:
    """Enable or disable one fake hook and return the refreshed list."""
    name = params.get("name")
    action = params.get("action")
    if action in ("load", "enable"):
        enabled = True
    elif action in ("remove", "disable"):
        enabled = False
    else:
        error(request_id, -32602, f"unknown hook action: {action}")
        return

    for hook in _hooks:
        if hook["name"] == name:
            hook["enabled"] = enabled
            hooks = [
                dict(item)
                for item in sorted(_hooks, key=lambda entry: (entry["type"], entry["priority"]))
            ]
            result(request_id, {"result": True, "hooks": hooks})
            return

    error(request_id, -32602, f"Hook '{name}' not found")


def handle_history(request_id: Any) -> None:
    """Return a deterministic conversation stream for transcript replay."""
    messages = [
        {
            "role": "user",
            "content": '<context name="user_input" from="agent">\nHello there\n</context>',
        },
        {"role": "assistant", "content": "Hi, I can help."},
        {
            "role": "assistant",
            "content": "",
            "toolCalls": [
                {
                    "id": "call-1",
                    "name": "ReadFile",
                    "arguments": '{"path": "CONTRACT.md"}',
                }
            ],
        },
        {"role": "tool", "toolCallId": "call-1", "content": "contract body"},
        {"role": "assistant", "content": "All done."},
    ]
    diffs = [
        {
            "file": "CONTRACT.md",
            "diff": "@@ -1 +1 @@\n-old line\n+new line",
        }
    ]
    subagents = [
        {
            "sessionId": session_id,
            "messages": [
                {"role": "user", "content": "work"},
                {"role": "assistant", "content": "child reply"},
            ],
            "diffs": [
                {
                    "file": f"{session_id}.md",
                    "diff": "@@ -2 +2 @@\n-child line\n+child line two",
                }
            ],
        }
        for session_id in sorted(_announced_subagents)
    ]
    result(request_id, {"messages": messages, "subagents": subagents, "diffs": diffs})


def handle_subagent_message(request_id: Any, params: dict[str, Any]) -> None:
    """Echo a user message into a child session, like the real agent does."""
    session_id = params.get("sessionId")
    text = str(params.get("text") or "")
    result(request_id, {"ok": True})

    if not session_id:
        return

    update(
        {
            "sessionUpdate": "session_message",
            "userMessage": True,
            "senderSessionId": SESSION_ID,
            "recipientSessionId": session_id,
            "content": [{"type": "text", "text": text}],
        }
    )
    update(
        {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": f"echo: {text}"},
        },
        session_id,
    )


BACKGROUND_COMMANDS: list[dict[str, Any]] = [
    {
        "key": "bg_1_0001",
        "command": "sleep 60",
        "running": True,
        "persist": False,
        "continuedInBackground": True,
        "bufferSize": 120,
        "pages": 1,
        "totalChars": 240,
        "startTime": 1000.0,
        "endTime": None,
        "duration": 12.5,
    },
    {
        "key": "bg_2_0002",
        "command": "printf 'done\\n'",
        "running": False,
        "persist": True,
        "continuedInBackground": False,
        "bufferSize": 5,
        "pages": 0,
        "totalChars": 5,
        "startTime": 900.0,
        "endTime": 901.5,
        "duration": 1.5,
    },
]

BACKGROUND_OUTPUT = {
    "bg_1_0001": "tick 1\ntick 2\ntick 3\n",
    "bg_2_0002": "done\n",
}


def handle_background(request_id: Any, params: dict[str, Any]) -> None:
    """Return deterministic background commands and output for bridge tests."""
    action = params.get("action", "list")

    if action == "list":
        result(request_id, {"commands": BACKGROUND_COMMANDS})
        return

    if action != "output":
        error(request_id, -32602, f"unknown background action: {action}")
        return

    key = params.get("key")
    if key not in BACKGROUND_OUTPUT:
        error(request_id, -32602, f"unknown background command: {key}")
        return

    command = next((item for item in BACKGROUND_COMMANDS if item["key"] == key), {})
    result(request_id, {"output": BACKGROUND_OUTPUT[key], "command": command})


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
    elif method == "cecli/complete":
        handle_complete(request_id, params)
    elif method == "cecli/state":
        result(request_id, state_details())
    elif method == "cecli/hook":
        handle_hook(request_id, params)
    elif method == "cecli/history":
        handle_history(request_id)
    elif method == "cecli/background":
        handle_background(request_id, params)
    elif method == "cecli/subagent/message":
        handle_subagent_message(request_id, params)
    elif method in ("cecli/skill", "cecli/mcp", "cecli/context"):
        result(request_id, {"ok": True})
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
