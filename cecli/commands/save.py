from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result
from cecli.commands.utils.save_load_manager import SaveLoadManager


class SaveCommand(BaseCommand):
    NORM_NAME = "save"
    DESCRIPTION = "Save commands to a file that can reconstruct the current chat session's files"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the save command with given parameters."""
        if not args.strip():
            return format_command_result(
                io, "save", "", "No filename provided to save the commands to"
            )

        manager = SaveLoadManager(coder, io)

        try:
            filepath = manager.save_commands(args.strip())
            return format_command_result(io, "save", f"Saved commands to {filepath}")
        except Exception as e:
            return format_command_result(io, "save", f"Error saving commands to file: {e}", e)

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for save command."""
        # For save command, we could return file paths for completion
        # For now, return empty list
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the save command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /save <filename>  # Save commands to reconstruct current chat session\n"
        help_text += "\nExamples:\n"
        help_text += "  /save session      # Save to .cecli/saves/session.txt\n"
        help_text += "  /save session.txt  # Save to .cecli/saves/session.txt\n"
        help_text += "  /save ./session.txt  # Save to ./session.txt (explicit path)\n"
        help_text += "  /save /tmp/session.txt  # Save to /tmp/session.txt (absolute path)\n"
        help_text += "\nThe saved file contains commands that can be used with /load to restore\n"
        help_text += "the current chat session, including all editable and read-only files.\n"
        help_text += "The file starts with /drop to clear existing files, then adds all files.\n"
        return help_text
