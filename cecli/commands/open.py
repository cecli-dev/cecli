"""Open command - register and open a workspace sub-agent rooted at a path."""

from pathlib import Path

from cecli.helpers.agents.service import AgentService
from cecli.helpers.workspaces.subagents import register_workspace_subagents

from .utils.base_command import BaseCommand


class OpenCommand(BaseCommand):
    NORM_NAME = "open"
    DESCRIPTION = "Open a workspace sub-agent rooted at a given path"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Open a workspace sub-agent rooted at the given path.

        Syntax:
            /open <name> <path>  — register and open a ``ws:{name}`` sub-agent rooted at ``<path>``
        """
        parts = args.strip().split(maxsplit=1)
        if len(parts) < 2:
            io.tool_error("Usage: /open <name> <path>")
            return

        name = parts[0]
        path_arg = parts[1].strip()

        project_name = name[3:] if name.startswith("ws:") else name
        agent_name = f"ws:{project_name}"
        path = Path(path_arg).expanduser()

        config = {
            "name": project_name,
            "projects": [{"name": project_name, "path": str(path)}],
        }
        registered = register_workspace_subagents(config)
        if agent_name not in registered:
            io.tool_error(f"Error: '{path}' is not a valid git repository or does not exist.")
            return

        root = AgentService.get_registry()[agent_name].metadata.get("root")

        try:
            agent_service = AgentService.get_instance(coder)
            new_coder, info = await agent_service.spawn(
                agent_name, prompt=None, parent=coder, auto_reap=False, independent=True
            )

            agent_service.foreground_uuid = info.coder.uuid

            if coder.tui and coder.tui():
                tui = coder.tui()
                switch_key = tui.get_keys_for("next_agent")
                io.tool_output(
                    f"Opened workspace sub-agent '{agent_name}' rooted at {root}. Switch with {switch_key}"
                )

                try:
                    tui.call_from_thread(tui._switch_to_container, info.coder.uuid)
                except Exception:
                    pass
            else:
                io.tool_output(f"Opened workspace sub-agent '{agent_name}' rooted at {root}.")
        except Exception as e:
            io.tool_error(f"Error opening workspace sub-agent '{agent_name}': {e}")

    @classmethod
    def get_help(cls) -> str:
        return "Open a workspace sub-agent rooted at a path (/open <name> <path>)"

    @classmethod
    def get_completions(cls, io, coder, args) -> list[str]:
        """Return registered workspace sub-agent names for tab-completion."""
        return [name for name in AgentService.get_registry().keys() if name.startswith("ws:")]
