"""Canonical GUI event payloads, shared by every ACP front end.

All structured events travel as ``session/update`` payloads. The ACP agent
(``agent/updates.py``) and the legacy WebSocket signal bridge (``bridge.py``)
build the same shapes here so a client sees one event vocabulary regardless of
transport. New event kinds belong here, not in either transport adapter.

A ``state_update`` carries the session's current ``state`` (an activity) and,
optionally, the ``scope`` that changed. Clients apply the scope they already
track, or re-fetch the session snapshot when convenient; the snapshot remains
the authoritative source for reconnects.
"""

from __future__ import annotations

from typing import Any

# Session activity states
STATE_RUNNING = "running"
STATE_IDLE = "idle"
STATE_REQUIRES_ACTION = "requires_action"

# State scopes a client can refresh without polling
SCOPE_CONFIG = "config"
SCOPE_SKILLS = "skills"
SCOPE_HOOKS = "hooks"
SCOPE_MCP = "mcp"
SCOPE_WORKFLOWS = "workflows"
SCOPE_CONTEXT = "context"

# Scopes served by the session snapshot rather than the config options
DETAIL_SCOPES = frozenset(
    {
        SCOPE_SKILLS,
        SCOPE_HOOKS,
        SCOPE_MCP,
        SCOPE_WORKFLOWS,
        SCOPE_CONTEXT,
    }
)


def session_update(kind: str, **fields: Any) -> dict[str, Any]:
    """Build a ``session/update`` payload with ``kind`` as the discriminator."""
    return {"sessionUpdate": kind, **fields}


def state_update(
    state: str,
    stop_reason: str | None = None,
    scope: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build a ``state_update`` payload.

    ``state`` is the session activity (``running``, ``idle`` or
    ``requires_action``). ``scope`` names one cached detail that changed, so a
    client can re-fetch it instead of polling. ``stopReason`` only accompanies
    the transition to ``idle``.
    """
    payload = session_update("state_update", state=state)
    if stop_reason is not None:
        payload["stopReason"] = stop_reason
    if scope is not None:
        payload["scope"] = scope
    payload.update(extra)
    return payload
