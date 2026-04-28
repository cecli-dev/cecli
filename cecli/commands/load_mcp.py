from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class LoadMcpCommand(BaseCommand):
    NORM_NAME = "load-mcp"
    DESCRIPTION = "Load MCP server(s) by name, or use '*' to load all enabled servers"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the load-mcp command with given parameters."""
        if not args.strip():
            return format_command_result(io, cls.NORM_NAME, "Usage: /load-mcp <mcp-name>")

        if not coder.mcp_manager or not coder.mcp_manager.servers:
            return format_command_result(
                io, cls.NORM_NAME, "No MCP servers found, nothing to load."
            )

        server_names = args.strip().split()
        results = []

        # Handle '*' wildcard to load all servers enabled by default
        if server_names == ["*"]:
            for server in coder.mcp_manager.servers:
                if server in coder.mcp_manager.connected_servers:
                    results.append(f"Server already loaded: {server.name}")
                    continue
                auto_connect = server.config.get("enabled", True)
                if not auto_connect:
                    results.append(f"Skipping server (not enabled by default): {server.name}")
                    continue
                did_connect = await coder.mcp_manager.connect_server(server.name)
                if did_connect:
                    results.append(f"Loaded server: {server.name}")
                else:
                    results.append(f"Unable to load server: {server.name}")
        else:
            for server_name in server_names:
                server = coder.mcp_manager.get_server(server_name)
                if server is None:
                    results.append(f"MCP server {server_name} does not exist.")
                    continue

                did_connect = await coder.mcp_manager.connect_server(server.name)
                if did_connect:
                    results.append(f"Loaded server: {server_name}")
                else:
                    results.append(f"Unable to load server: {server_name}")

        try:
            return format_command_result(io, cls.NORM_NAME, "\n".join(results))
        finally:
            from . import SwitchCoderSignal

            raise SwitchCoderSignal(
                edit_format=coder.edit_format,
                summarize_from_coder=False,
                from_coder=coder,
                show_announcements=True,
            )

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for load-mcp command."""
        if not coder.mcp_manager or not coder.mcp_manager.servers:
            return []

        try:
            server_names = [
                server.name
                for server in coder.mcp_manager
                if server not in coder.mcp_manager.connected_servers
            ]
            return server_names
        except Exception:
            return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the load-mcp command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /load-mcp <mcp-name>...  # Load one or more mcps by name\n"
        help_text += "  /load-mcp *              # Load all mcps enabled by default\n"
        help_text += "\nExamples:\n"
        help_text += "  /load-mcp context7  # Load the context7 mcp\n"
        help_text += "  /load-mcp github context7  # Load both github and context7 mcps\n"
        help_text += "  /load-mcp *          # Load all mcps enabled by default\n"
