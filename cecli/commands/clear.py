from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class ClearCommand(BaseCommand):
    NORM_NAME = "clear"
    DESCRIPTION = "Clear the chat history"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        # Clear chat history
        coder.done_messages = []
        coder.cur_messages = []

        # Clear TUI output if available
        if coder.tui and coder.tui():
            coder.tui().action_clear_output()

        io.tool_output("All chat history cleared.")
        return format_command_result(io, "clear", "Cleared chat history")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for clear command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the clear command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /clear  # Clear all chat history\n"
        help_text += "\nNote: This only clears the chat history, not the files in the chat.\n"
        help_text += "Use /drop to remove files from the chat.\n"
        return help_text
