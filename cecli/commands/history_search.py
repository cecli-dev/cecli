from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result
from cecli.utils import run_fzf


class HistorySearchCommand(BaseCommand):
    NORM_NAME = "history-search"
    DESCRIPTION = "Fuzzy search in history and paste it in the prompt"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the history-search command with given parameters."""
        history_lines = io.get_input_history()
        selected_lines = run_fzf(history_lines, coder=coder)
        if selected_lines:
            io.set_placeholder("".join(selected_lines))
            return format_command_result(
                io, "history-search", "Selected history lines and set placeholder"
            )
        else:
            return format_command_result(io, "history-search", "No history lines selected")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for history-search command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the history-search command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /history-search  # Fuzzy search through command history\n"
        help_text += (
            "\nThis command opens a fuzzy finder (FZF) to search through your command history.\n"
        )
        help_text += "Selected lines will be pasted into the input prompt for editing.\n"
        return help_text
