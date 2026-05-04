from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class ListSkillsCommand(BaseCommand):
    NORM_NAME = "list-skills"
    DESCRIPTION = "List all available skills with their states and file paths"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the list-skills command with given parameters."""
        # Check if skills_manager is available
        if not hasattr(coder, "skills_manager") or coder.skills_manager is None:
            io.tool_output("Skills manager is not initialized. Skills may not be configured.")
            if hasattr(coder, "skills_directory_paths") and not coder.skills_directory_paths:
                io.tool_output(
                    "No skills directories configured. Use --skills-paths to configure skill"
                    " directories."
                )
            return format_command_result(io, "list-skills", "Skills manager is not initialized")

        try:
            formatted = coder.skills_manager.get_skills_list_formatted()
            return format_command_result(io, "list-skills", formatted)
        except Exception as e:
            error_msg = f"Error listing skills: {e}"
            return format_command_result(io, "list-skills", error_msg)

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for list-skills command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the list-skills command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /list-skills  # List all available skills with their states and paths\n"
        help_text += "\nExamples:\n"
        help_text += (
            "  /list-skills  # Shows a table of all skills, their include/exclude/visible status,\n"
        )
        help_text += "                # whether they are loaded, and their directory paths\n"
        help_text += "\n"
        help_text += "This command lists all skills found in the configured skill directories,\n"
        help_text += "displaying their current status (included/excluded/visible),\n"
        help_text += "whether they are loaded into context, and their file system paths.\n"
        return help_text
