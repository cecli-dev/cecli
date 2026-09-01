"""JSON-RPC 2.0 message builders and inbound ACP method dispatch.

Provides factory functions for constructing JSON-RPC 2.0 envelopes and
a dispatcher that maps inbound ACP method calls to internal operations.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from cecli import __version__ as cecli_version

logger = logging.getLogger(__name__)

# ── JSON-RPC Envelope Builders ─────────────────────────────────


def build_request(method: str, params: dict | None = None, msg_id: int = 1) -> dict:
    """Build a JSON-RPC 2.0 request dict."""
    return {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}}


def build_notification(method: str, params: dict | None = None) -> dict:
    """Build a JSON-RPC 2.0 notification dict (no id field)."""
    return {"jsonrpc": "2.0", "method": method, "params": params or {}}


def build_response(request_id: int | str | None, result: Any = None) -> dict:
    """Build a JSON-RPC 2.0 success response dict."""
    return {"jsonrpc": "2.0", "id": request_id, "result": result or {}}


def build_error_response(
    request_id: int | str | None,
    code: int,
    message: str,
    data: Any = None,
) -> dict:
    """Build a JSON-RPC 2.0 error response dict."""
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def parse_message(raw: str) -> dict:
    """Parse and validate an incoming JSON-RPC message.

    Returns the parsed message dict. Raises ``json.JSONDecodeError`` for
    invalid JSON, or ``ValueError`` for non-JSON-RPC structures.
    """
    msg = json.loads(raw)
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        raise ValueError("Not a JSON-RPC 2.0 message")
    return msg


# ── ACP-Specific Builders ──────────────────────────────────────


def make_initialize_result() -> dict:
    """Build the ACP initialize result."""
    return {
        "protocolVersion": 2,
        "capabilities": {
            "session": {},
        },
        "info": {
            "name": "cecli",
            "title": "CECLI Coding Agent",
            "version": cecli_version if isinstance(cecli_version, str) else "2.0.0",
        },
        "authMethods": [],
    }


def make_session_new_result(session_id: str) -> dict:
    """Build session/new result wrapping a coder UUID."""
    return {"sessionId": session_id}


def make_session_list_result(sessions: list[dict]) -> dict:
    """Build session/list result with _meta field."""
    return {"sessions": sessions, "_meta": {}}


def make_session_prompt_response() -> dict:
    """Build session/prompt response (always empty)."""
    return {}


def make_session_update_notification(session_id: str, update: dict) -> dict:
    """Build a session/update JSON-RPC notification."""
    return build_notification(
        "session/update",
        {"sessionId": session_id, "update": update},
    )


def make_state_update(
    state: str,
    stop_reason: str | None = None,
) -> dict:
    """Build a state_update payload."""
    result: dict[str, Any] = {"sessionUpdate": "state_update", "state": state}
    if stop_reason is not None:
        result["stopReason"] = stop_reason
    return result


def make_user_message(message_id: str, content: list[dict]) -> dict:
    """Build a user_message payload."""
    return {
        "sessionUpdate": "user_message",
        "messageId": message_id,
        "content": content,
    }


def make_agent_message_chunk(message_id: str, text: str) -> dict:
    """Build an agent_message_chunk payload."""
    return {
        "sessionUpdate": "agent_message_chunk",
        "messageId": message_id,
        "content": {"type": "text", "text": text},
    }


def make_agent_thought_chunk(message_id: str, text: str) -> dict:
    """Build an agent_thought_chunk payload."""
    return {
        "sessionUpdate": "agent_thought_chunk",
        "messageId": message_id,
        "content": {"type": "text", "text": text},
    }


def make_tool_call_update(
    tool_call_id: str,
    status: str,
    title: str | None = None,
    kind: str | None = None,
) -> dict:
    """Build a tool_call_update payload."""
    result: dict[str, Any] = {
        "sessionUpdate": "tool_call_update",
        "toolCallId": tool_call_id,
        "status": status,
    }
    if title is not None:
        result["title"] = title
    if kind is not None:
        result["kind"] = kind
    return result


def make_tool_call_content_chunk(tool_call_id: str, text: str) -> dict:
    """Build a tool_call_content_chunk payload."""
    return {
        "sessionUpdate": "tool_call_content_chunk",
        "toolCallId": tool_call_id,
        "content": {"type": "text", "text": text},
    }


def make_usage_update(used: int, size: int, cost: dict | None = None) -> dict:
    """Build a usage_update payload."""
    result: dict[str, Any] = {
        "sessionUpdate": "usage_update",
        "used": used,
        "size": size,
    }
    if cost is not None:
        result["cost"] = cost
    return result


# ── Inbound Dispatch ───────────────────────────────────────────


async def dispatch_inbound(
    raw: str,
    session_id: str | None = None,
    primary_coder_id: str | None = None,
) -> list[dict]:
    """Parse an inbound JSON-RPC message and dispatch to the appropriate handler.

    Args:
        raw: The raw JSON string from the WebSocket client.
        session_id: The session ID from the current connection context.
        primary_coder_id: The primary coder UUID for session/new fallback.

    Returns:
        A list of outbound JSON dicts (responses and/or notifications).
        An empty list means no response is needed (e.g., notification was handled).
    """
    try:
        msg = parse_message(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        error_resp = build_error_response(
            None,
            -32700,
            "Parse error",
            str(exc),
        )
        return [error_resp]

    method = msg.get("method", "")
    params = msg.get("params", {}) or {}
    msg_id = msg.get("id")

    if not method:
        error_resp = build_error_response(
            msg_id,
            -32600,
            "Invalid Request: missing method",
        )
        return [error_resp]

    logger.debug("ACP dispatch: method=%s id=%s params=%s", method, msg_id, params)

    if method == "initialize":
        return [build_response(msg_id, make_initialize_result())]

    elif method == "session/new":
        sid = primary_coder_id or params.get("sessionId", "")
        return [build_response(msg_id, make_session_new_result(sid))]

    elif method == "session/list":
        return _handle_session_list(msg_id)

    elif method == "session/prompt":
        return await _handle_session_prompt(msg_id, params, session_id, primary_coder_id)

    elif method == "session/cancel":
        return _handle_session_cancel(msg_id, params)

    elif method == "session/close":
        return _handle_session_close(msg_id, params)

    elif method == "session/resume":
        return _handle_session_resume(msg_id, params)

    else:
        error_resp = build_error_response(
            msg_id,
            -32601,
            f"Method not found: {method}",
        )
        return [error_resp]


async def _handle_session_prompt(
    msg_id: int | str | None,
    params: dict,
    session_id: str | None,
    primary_coder_id: str | None,
) -> list[dict]:
    """Handle session/prompt — accept text and route to coder queue."""
    from cecli.helpers import queues

    sid = params.get("sessionId", "") or session_id or primary_coder_id or ""
    prompt_blocks = params.get("prompt", [])

    # Extract text from content blocks
    text_parts: list[str] = []
    for block in prompt_blocks:
        if isinstance(block, dict):
            block_type = block.get("type", "")
            if block_type == "text" and block.get("text"):
                text_parts.append(block["text"])
            elif block_type == "resource":
                resource = block.get("resource", {})
                if resource.get("text"):
                    text_parts.append(resource["text"])

    full_text = "\n".join(text_parts)
    outbound: list[dict] = []

    # 1. Respond immediately with empty result
    outbound.append(build_response(msg_id, make_session_prompt_response()))

    # 2. Send user_message notification
    from cecli.helpers.server.acp.bridge import make_message_id

    user_msg_id = make_message_id("user", sid, str(hash(full_text)))
    outbound.append(
        make_session_update_notification(
            sid,
            make_user_message(user_msg_id, [{"type": "text", "text": full_text}]),
        )
    )

    # 3. Route text to coder queue (mimics user_input handling)
    if sid:
        queues.push_coder_input(sid, {"text": full_text, "coder_uuid": sid})
    else:
        logger.warning("session/prompt: no sessionId available to route input")

    return outbound


def _handle_session_cancel(msg_id: int | str | None, params: dict) -> list[dict]:
    """Handle session/cancel — stub that logs and returns cancelled state."""
    sid = params.get("sessionId", "")
    logger.info("ACP session/cancel requested for sessionId=%s (stub)", sid)
    return [
        make_session_update_notification(
            sid,
            make_state_update("idle", stop_reason="cancelled"),
        ),
    ]


def _handle_session_close(msg_id: int | str | None, params: dict) -> list[dict]:
    """Handle session/close — stub that logs and returns empty response."""
    sid = params.get("sessionId", "")
    logger.info("ACP session/close requested for sessionId=%s (stub)", sid)
    return [build_response(msg_id, {})]


def _handle_session_resume(msg_id: int | str | None, params: dict) -> list[dict]:
    """Handle session/resume — stub that returns empty response."""
    sid = params.get("sessionId", "")
    logger.info("ACP session/resume requested for sessionId=%s (stub)", sid)
    return [build_response(msg_id, {})]


def _handle_session_list(msg_id: int | str | None) -> list[dict]:
    """Handle session/list — return active coders as session info."""
    from cecli.helpers.agents.service import AgentService

    agents = AgentService.get_all_agents()
    sessions = []
    for coder in agents:
        sid = str(getattr(coder, "uuid", ""))
        cwd = getattr(coder, "cwd", None)
        sessions.append({"sessionId": sid, "cwd": cwd, "status": "active", "_meta": {}})

    return [build_response(msg_id, make_session_list_result(sessions))]
