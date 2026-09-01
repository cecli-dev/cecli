"""Workspaces: local multi-project workspaces with implicit ``ws:{name}`` sub-agents.

Replaces the former ``cecli.helpers.monorepo`` module. Workspaces are driven
entirely by a local ``.cecli.workspaces.yml`` configuration file that lists
existing git roots via ``path:`` entries. Each project automatically gets an
implicit ``ws:{project}`` sub-agent (mirroring the ``worker`` default) whose
``root`` points at that project, so workspaces can be spun up as agents.
"""

from .subagents import register_workspace_subagents
from .workspace import WorkspaceManager

__all__ = ["register_workspace_subagents", "WorkspaceManager"]
