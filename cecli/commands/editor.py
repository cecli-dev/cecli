from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result
from cecli.editor import pipe_editor


class EditorCommand(BaseCommand):
    NORM_NAME = "editor"
    DESCRIPTION = "Open an editor to write a prompt"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the editor command with given parameters."""
        # Get editor from kwargs or coder
        editor = kwargs.get("editor") or getattr(coder, "editor", None)

        user_input = pipe_editor(args, suffix="md", editor=editor)
        if user_input.strip():
            io.set_placeholder(user_input.rstrip())
            return format_command_result(io, "editor", "Opened editor and set placeholder")
        else:
            return format_command_result(io, "editor", "Opened editor (no input provided)")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for editor command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the editor command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /editor              # Open editor with empty content\n"
        help_text += "  /editor <content>    # Open editor with initial content\n"
        help_text += "  /edit                # Alias for /editor\n"
        help_text += (
            "\nThis command opens your system's default text editor (or the editor specified\n"
        )
        help_text += (
            "by the EDITOR environment variable) to write a prompt. When you save and exit\n"
        )
        help_text += "the editor, the content will be placed in the input prompt for editing.\n"
        return help_text


class EditCommand(BaseCommand):
    NORM_NAME = "edit"
    DESCRIPTION = "Alias for /editor: Open an editor to write a prompt"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the edit command with given parameters."""
        # Just call the EditorCommand's execute method
        return await EditorCommand.execute(io, coder, args, **kwargs)

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for edit command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the edit command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /edit                # Open editor with empty content\n"
        help_text += "  /edit <content>      # Open editor with initial content\n"
        help_text += "  /editor              # Alias for /edit\n"
        help_text += (
            "\nThis command opens your system's default text editor (or the editor specified\n"
        )
        help_text += (
            "by the EDITOR environment variable) to write a prompt. When you save and exit\n"
        )
        help_text += "the editor, the content will be placed in the input prompt for editing.\n"
        return help_text
