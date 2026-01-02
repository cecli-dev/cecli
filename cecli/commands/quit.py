from typing import List

from cecli.commands.exit import ExitCommand
from cecli.commands.utils.base_command import BaseCommand


class QuitCommand(BaseCommand):
    NORM_NAME = "quit"
    DESCRIPTION = "Exit the application (alias for /exit)"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the quit command with given parameters."""
        # Just call the ExitCommand's execute method
        return await ExitCommand.execute(io, coder, args, **kwargs)

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for quit command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the quit command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /quit  # Exit the cecli application\n"
        help_text += "  /exit  # Alias for /quit\n"
        help_text += "\nThis command gracefully exits the cecli application.\n"
        help_text += "If running in TUI mode, it will restore the terminal properly.\n"
        help_text += "Otherwise, it will exit the Python process.\n"
        return help_text
