from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class MultilineModeCommand(BaseCommand):
    NORM_NAME = "multiline-mode"
    DESCRIPTION = "Toggle multiline mode (swaps behavior of Enter and Meta+Enter)"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the multiline-mode command with given parameters."""
        io.toggle_multiline_mode()
        return format_command_result(io, "multiline-mode", "Toggled multiline mode")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for multiline-mode command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the multiline-mode command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /multiline-mode  # Toggle multiline mode\n"
        help_text += (
            "\nThis command toggles multiline mode, which swaps the behavior of Enter and"
            " Meta+Enter.\n"
        )
        help_text += "When multiline mode is enabled:\n"
        help_text += "  - Enter: Creates a new line in the input\n"
        help_text += "  - Meta+Enter: Submits the input\n"
        help_text += "When multiline mode is disabled (default):\n"
        help_text += "  - Enter: Submits the input\n"
        help_text += "  - Meta+Enter: Creates a new line in the input\n"
        return help_text
