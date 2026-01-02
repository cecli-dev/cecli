from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class MapRefreshCommand(BaseCommand):
    NORM_NAME = "map-refresh"
    DESCRIPTION = "Force a refresh of the repository map"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the map-refresh command with given parameters."""
        repo_map = coder.get_repo_map(force_refresh=True)
        if repo_map:
            io.tool_output("The repo map has been refreshed, use /map to view it.")
        else:
            io.tool_output("No repository map available.")

        return format_command_result(io, "map-refresh", "Refreshed repository map")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for map-refresh command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the map-refresh command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /map-refresh  # Force a refresh of the repository map\n"
        help_text += "\nThis command forces a refresh of the repository map, which can be useful\n"
        help_text += "if files have been added, removed, or modified outside of cecli.\n"
        return help_text
