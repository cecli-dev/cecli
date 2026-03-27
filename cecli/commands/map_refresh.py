from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result
from cecli.helpers.conversation import ConversationService, MessageTag


class MapRefreshCommand(BaseCommand):
    NORM_NAME = "map-refresh"
    DESCRIPTION = "Force a refresh of the repository map"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the map-refresh command with given parameters."""
        # Clear any existing REPO tagged messages before refreshing
        ConversationService.get_manager(coder).clear_tag(MessageTag.REPO)

        # Parse the argument
        arg_str = args.strip() if args else ""

        # Clear the repo_map instance if any argument is provided
        if arg_str:
            # Clear the combined_map_dict if it exists
            if (
                hasattr(coder, "repo_map")
                and coder.repo_map is not None
                and hasattr(coder.repo_map, "combined_map_dict")
            ):
                coder.repo_map.combined_map_dict = {}

            # Check if the argument is numeric
            try:
                map_tokens = int(arg_str)
                if map_tokens > 0:
                    # Reinitialize repo_map with new map_tokens value
                    if coder.repo and hasattr(coder, "repo_map") and coder.repo_map is not None:
                        # Get current RepoMap configuration
                        current_repo_map = coder.repo_map
                        current_repo_map.max_map_tokens = map_tokens

                        io.tool_output(f"RepoMap reinitialized with {map_tokens} max_tokens.")
                    else:
                        io.tool_output(
                            f"Numeric argument {map_tokens} ignored - no repo_map to reinitialize."
                        )
                else:
                    io.tool_output(
                        f"Argument cleared repo_map but {map_tokens} is not a positive integer."
                    )
            except ValueError:
                # Argument is not numeric, just clear the repo_map
                io.tool_output("Non-numeric argument provided - repo_map cleared.")
        else:
            # No argument provided, just clear combined_map_dict
            if (
                hasattr(coder, "repo_map")
                and coder.repo_map is not None
                and hasattr(coder.repo_map, "combined_map_dict")
            ):
                coder.repo_map.combined_map_dict = {}

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
        help_text += "  /map-refresh           # Force a refresh of the repository map\n"
        help_text += (
            "  /map-refresh <tokens>  # Reinitialize repo_map with specified max_tokens value\n"
        )
        help_text += "\nThis command forces a refresh of the repository map, which can be useful\n"
        help_text += "if files have been added, removed, or modified outside of cecli.\n"
        help_text += "\nIf a numeric argument is provided, the RepoMap will be reinitialized\n"
        help_text += "with that value as the max_tokens parameter. If any non-numeric argument\n"
        help_text += "is provided, the repo_map will be cleared but not reinitialized.\n"
        return help_text
