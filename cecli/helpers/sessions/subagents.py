"""Detecting, saving, and resolving the sub-agents that belong to a session."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .layout import SUB_AGENT_PAYLOAD_NAME
from .payload import build_payload
from .storage import write_payload

logger = logging.getLogger(__name__)

# The memorizer is a transient helper that is re-spawned on demand; a saved
# session must never try to resurrect it.
MEMORIZER_AGENT_NAME = "memorizer"


def detect_agent_name(coder) -> Optional[str]:
    """Return a coder's sub-agent type, or ``None`` for the primary agent."""
    coder_uuid = getattr(coder, "uuid", None)
    parent_uuid = getattr(coder, "parent_uuid", None)
    if not isinstance(coder_uuid, str) or not coder_uuid:
        return None

    if not isinstance(parent_uuid, str) or not parent_uuid:
        return None

    try:
        from cecli.helpers.agents.service import AgentService

        return AgentService.get_instance(coder).get_agent_name(coder)

    except Exception:
        return None


def live_sub_agents(coder) -> List[Tuple[str, object]]:
    """Return ``(agent_name, sub_coder)`` for every live sub-agent of ``coder``.

    Descendants at any depth are included so a saved session captures the whole
    delegation tree, not just the direct children.
    """
    try:
        from cecli.helpers.agents.service import AgentService

        service = AgentService.get_instance(coder)

    except Exception:
        return []

    infos: Dict[str, object] = {}
    for info in list(service.sub_agents.values()):
        sub_coder = getattr(info, "coder", None)
        sub_uuid = getattr(sub_coder, "uuid", None) if sub_coder is not None else None
        if sub_coder is not None and sub_uuid is not None:
            infos[str(sub_uuid)] = info

    root_uuid = str(getattr(coder, "uuid", ""))

    agents = []
    for info in infos.values():
        agent_name = getattr(info, "name", None)
        if agent_name and _descends_from(info, root_uuid, infos):
            agents.append((agent_name, info.coder))

    return agents


def sub_agent_state(coder) -> Tuple[bool, Optional[str]]:
    """Return ``(independent, status)`` for a tracked sub-agent coder.

    Falls back to ``(False, None)`` when the coder is not (or no longer) tracked
    by the :class:`AgentService`, so payload building stays safe for callers with
    no live service.
    """
    from cecli.helpers.agents.service import AgentService

    coder_uuid = getattr(coder, "uuid", None)
    if not isinstance(coder_uuid, str) or not coder_uuid:
        return False, None

    try:
        service = AgentService.get_instance(coder)
    except Exception:
        return False, None

    info = service.sub_agents.get(coder_uuid)
    if info is None:
        return False, None

    status = getattr(getattr(info, "status", None), "value", None)

    return bool(getattr(info, "independent", False)), status


def save_sub_agents(coder, io, session_name: str, subs_dir: Path) -> int:
    """Write each descendant sub-agent payload into ``subs_dir/{child}/agent.json``.

    Returns the number of sub-agents saved.
    """
    subs_dir.mkdir(parents=True, exist_ok=True)

    used: Set[str] = set()
    written = 0
    for agent_name, sub_coder in live_sub_agents(coder):
        child_dir = subs_dir / _unique_child_name(agent_name, used)
        payload = build_payload(sub_coder, io, session_name, agent_name=agent_name)

        if write_payload(sub_coder, io, child_dir / SUB_AGENT_PAYLOAD_NAME, payload):
            written += 1

    return written


def should_restore_sub_agent(sub_data: Dict) -> bool:
    """Return whether a saved sub-agent payload should be rebuilt on load.

    Independent agents are always restored regardless of how they finished. A
    dependent agent is restored only while it is still unfinished and unerrored.
    The transient ``memorizer`` helper is never restored.
    """
    from cecli.helpers.agents.service import SubAgentStatus

    agent_name = sub_data.get("agent_name")
    if not agent_name or agent_name == MEMORIZER_AGENT_NAME:
        return False

    if sub_data.get("independent", True):
        return True

    status = sub_data.get("status")

    return status not in (SubAgentStatus.FINISHED.value, SubAgentStatus.ERROR.value)


def resolve_reload_agent_name(name: str, root: Optional[str]) -> Optional[str]:
    """Resolve a stored agent type to a registered name, falling back to ``worker``."""
    from cecli.helpers.agents.service import AgentService

    registry = AgentService.get_registry()

    if name not in registry and name.startswith("ws:") and root:
        ensure_ws_agent_registered(name, str(root))

        registry = AgentService.get_registry()

    if name in registry:
        return name

    if "worker" in registry:
        return "worker"

    return None


def ensure_ws_agent_registered(name: str, root: str) -> None:
    """Register a ``ws:`` sub-agent for a stored root when it is missing."""
    from cecli.helpers.workspaces.subagents import register_workspace_subagents

    project_name = name[3:]
    register_workspace_subagents(
        {
            "name": project_name,
            "projects": [{"name": project_name, "path": root}],
        }
    )


def _descends_from(info, root_uuid: str, infos: Dict[str, object]) -> bool:
    """Return True when ``info`` sits anywhere below ``root_uuid`` in the tree."""
    seen: Set[str] = set()

    current = info
    while current is not None:
        parent_uuid = getattr(current, "parent_uuid", None)
        if not parent_uuid:
            return False

        if parent_uuid == root_uuid:
            return True

        if parent_uuid in seen:
            return False

        seen.add(parent_uuid)
        current = infos.get(parent_uuid)

    return False


def _unique_child_name(agent_name: str, used: Set[str]) -> str:
    """Return a filesystem-safe, unique directory name for a sub-agent."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in agent_name) or "agent"
    candidate = safe
    suffix = 2
    while candidate in used:
        candidate = f"{safe}-{suffix}"
        suffix += 1

    used.add(candidate)

    return candidate
