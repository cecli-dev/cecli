import asyncio
import os
import sys
from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class ExitCommand(BaseCommand):
    NORM_NAME = "exit"
    DESCRIPTION = "Exit the application"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the exit command with given parameters."""
        # Check if running in TUI mode - use graceful exit to restore terminal
        if hasattr(io, "request_exit"):
            io.request_exit()
            # Give TUI time to process the exit message
            await asyncio.sleep(0.5)
            return format_command_result(io, "exit", "Exiting application")

        try:
            if coder.args.linear_output:
                os._exit(0)
            else:
                sys.exit()
        except Exception:
            sys.exit()

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for exit command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the exit command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /exit  # Exit the cecli application\n"
        help_text += "  /quit  # Alias for /exit\n"
        help_text += "\nThis command gracefully exits the cecli application.\n"
        help_text += "If running in TUI mode, it will restore the terminal properly.\n"
        help_text += "Otherwise, it will exit the Python process.\n"
        return help_text
