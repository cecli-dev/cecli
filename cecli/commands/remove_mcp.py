from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class RemoveMcpCommand(BaseCommand):
    NORM_NAME = "remove-mcp"
    DESCRIPTION = "Remove a MCP server by name"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the remove-mcp command with given parameters."""
        if not args.strip():
            return format_command_result(io, cls.NORM_NAME, "Usage: /remove-mcp <mcp-name>")

        if not coder.mcp_manager or not coder.mcp_manager.servers:
            return format_command_result(
                io, cls.NORM_NAME, "No MCP servers connected, nothing to remove."
            )

        server_names = args.strip().split()
        results = []
        for server_name in server_names:
            was_disconnected = await coder.mcp_manager.disconnect_server(server_name)
            if was_disconnected:
                results.append(f"Removed server: {server_name}")
            else:
                results.append(f"Unable to remove server: {server_name}")

        try:
            return format_command_result(io, cls.NORM_NAME, "\n".join(results))
        finally:
            from . import SwitchCoderSignal

            raise SwitchCoderSignal(
                edit_format=coder.edit_format,
                summarize_from_coder=False,
                from_coder=coder,
                show_announcements=True,
                mcp_manager=coder.mcp_manager,
            )

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for remove-mcp command."""
        if not coder.mcp_manager or not coder.mcp_manager.servers:
            return []

        try:
            server_names = [server.name for server in coder.mcp_manager if server.is_connected]
            return server_names
        except Exception:
            return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the remove-mcp command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /remove-mcp <mcp-name>...  # Remove one or more mcps by name\n"
        help_text += "\nExamples:\n"
        help_text += "  /remove-mcp context7  # Remove the context7 mcp\n"
        help_text += "  /remove-mcp github context7  # Remove both github and context7 mcps\n"
        help_text += "\nThis command removes one or more MCP servers by name.\n"
