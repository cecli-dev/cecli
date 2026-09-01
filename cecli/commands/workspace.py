from cecli.commands.utils.base_command import BaseCommand


class WorkspaceCommand(BaseCommand):
    NORM_NAME = "workspace"
    DESCRIPTION = "Print information about the active workspace sub-agents"
    show_completion_notification = True

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Show the registered ws:{name} workspace sub-agents and their roots."""
        from cecli.helpers.agents.service import AgentService

        registry = AgentService.get_registry()
        ws_agents = sorted((name, cfg) for name, cfg in registry.items() if name.startswith("ws:"))

        if not ws_agents:
            io.tool_output("No workspace sub-agents are active.")
            return

        io.print("Workspace Sub-Agents:")
        for name, cfg in ws_agents:
            metadata = getattr(cfg, "metadata", {}) or {}
            io.print(f"  - {name}")
            io.print(f"    Root:   {metadata.get('root')}")
            io.print(f"    Layout: {metadata.get('layout')}")
            io.print("")

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the workspace command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /workspace  # List active workspace sub-agents\n"
        return help_text
