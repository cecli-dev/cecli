from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class ContextManagementCommand(BaseCommand):
    NORM_NAME = "context-management"
    DESCRIPTION = "Toggle context management for large files"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the context-management command with given parameters."""
        if not hasattr(coder, "context_management_enabled"):
            io.tool_error("Context management is only available in agent mode.")
            return format_command_result(
                io, "context-management", "Context management only available in agent mode"
            )

        # Toggle the setting
        coder.context_management_enabled = not coder.context_management_enabled

        # Report the new state
        if coder.context_management_enabled:
            io.tool_output("Context management is now ON - large files may be truncated.")
            return format_command_result(io, "context-management", "Context management is now ON")
        else:
            io.tool_output("Context management is now OFF - files will not be truncated.")
            return format_command_result(io, "context-management", "Context management is now OFF")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for context-management command."""
        # For context-management command, we could return toggle options
        # For now, return empty list
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the context-management command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /context-management  # Toggle context management for large files\n"
        help_text += (
            "\nThis command toggles context management, which controls whether large files\n"
        )
        help_text += "are automatically truncated to save tokens when using agent mode.\n"
        help_text += "When ON: Large files may be truncated to save context window space.\n"
        help_text += "When OFF: Files will not be truncated, using more tokens.\n"
        help_text += "\nNote: This command is only available in agent mode.\n"
        return help_text
