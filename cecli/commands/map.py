from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class MapCommand(BaseCommand):
    NORM_NAME = "map"
    DESCRIPTION = "Print out the current repository map"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the map command with given parameters."""
        repo_map = coder.get_repo_map()
        if repo_map:
            io.tool_output(repo_map)
        else:
            io.tool_output("No repository map available.")

        return format_command_result(io, "map", "Displayed repository map")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for map command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the map command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /map  # Print the current repository map\n"
        help_text += (
            "\nThe repository map provides a high-level overview of the codebase structure,\n"
        )
        help_text += "including key files, directories, and their relationships.\n"
        return help_text
