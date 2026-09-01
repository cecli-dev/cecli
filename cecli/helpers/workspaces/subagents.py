"""Implicit ``ws:{name}`` workspace sub-agents.

When a workspace is active, each project becomes a sub-agent named
``ws:{project}``. The agent mirrors the ``worker`` default sub-agent but has
its ``root`` overridden to the project's git root and ``allow_nested_delegation``
enabled so it can itself serve as a base for further delegations.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import workspace_layout
from .paths import project_path

logger = logging.getLogger(__name__)


def register_workspace_subagents(
    workspace_config: Dict[str, Any] | None,
    workspace_root: Optional[Path | str] = None,
) -> List[str]:
    """Create and register a ``ws:{name}`` sub-agent for each workspace project.

    Each project may define a ``metadata`` block that supplies its sub-agent
    setup the same way a sub-agent .md file does: ``model`` / ``hooks`` /
    ``auto_reap`` become the config fields, and any other keys (e.g.
    ``agent-config``) are merged into the sub-agent metadata.

    ``root``, ``name`` and ``description`` are always derived from the
    workspace/project definition and cannot be overridden by the metadata block.

    Returns the list of registered agent names.
    """
    from cecli.helpers.agents.config import SubAgentConfig
    from cecli.helpers.agents.service import AgentService

    config = workspace_config or {}
    projects = config.get("projects") or []

    # Make sure the built-in defaults (including ``worker``) are loaded so the
    # workspace agents can mirror them, regardless of call ordering.
    if "worker" not in AgentService.get_registry():
        AgentService.build_registry([])

    worker = AgentService.get_registry().get("worker")

    layout = workspace_layout(config)
    if workspace_root is not None:
        root_base = Path(workspace_root).resolve()
    elif layout == "clone":
        root_base = Path(os.path.expanduser(f"~/.cecli/workspaces/{config.get('name')}"))
    else:
        root_base = Path(".")

    registered: List[str] = []
    for proj in projects:
        name = proj.get("name")
        if not name:
            continue
        root = project_path(root_base, proj, layout=layout)
        if not root:
            continue

        # A project may supply its own sub-agent setup under ``metadata``,
        # matching how .md sub-agent definitions do: ``model`` / ``hooks`` /
        # ``auto_reap`` map to the config fields; everything else is merged
        # into the sub-agent metadata.
        project_meta = dict(proj.get("metadata") or {})

        # ``root``, ``name`` and ``description`` are always derived from the
        # workspace/project definition and cannot be overridden by the metadata block.
        project_meta.pop("root", None)
        project_meta.pop("name", None)
        project_meta.pop("description", None)
        config_keys = {"model", "hooks", "auto_reap"}

        model = project_meta.get("model", worker.model if worker else None)
        hooks = (
            dict(project_meta["hooks"])
            if "hooks" in project_meta
            else (dict(worker.hooks) if worker else {})
        )
        auto_reap = (
            project_meta["auto_reap"]
            if "auto_reap" in project_meta
            else (worker.auto_reap if worker else None)
        )

        agent_name = f"ws:{name}"
        metadata = dict(worker.metadata) if worker else {}
        for key, value in project_meta.items():
            if key in config_keys:
                continue
            metadata[key] = value
        metadata["root"] = str(root)
        metadata["layout"] = layout

        agent_config = dict(metadata.get("agent-config") or {})
        agent_config["allow_nested_delegation"] = True
        metadata["agent-config"] = agent_config

        metadata["description"] = f"Workspace sub-agent for project '{name}' at path {root}"

        agent = SubAgentConfig(
            name=agent_name,
            prompt=(worker.prompt if worker else ""),
            model=model,
            hooks=hooks,
            auto_reap=auto_reap,
            metadata=metadata,
        )

        AgentService.register_subagent(agent_name, agent)
        registered.append(agent_name)
        logger.info("Registered workspace sub-agent '%s' -> %s", agent_name, root)

    return registered
