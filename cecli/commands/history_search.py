import os
from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result
from cecli.decoding import safe_open
from cecli.utils import run_fzf


class HistorySearchCommand(BaseCommand):
    NORM_NAME = "history-search"
    DESCRIPTION = "Fuzzy search in history and paste it in the prompt"
    show_completion_notification = True

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the history-search command with given parameters."""
        # Get history lines based on whether we're in TUI mode or not
        if coder.tui and coder.tui():
            # In TUI mode, parse the history file directly using our custom parser
            history_lines = cls.parse_input_history_file(io.input_history_file)
        else:
            # In non-TUI mode, use the io.get_input_history() method
            history_lines = io.get_input_history()

        selected_lines = run_fzf(history_lines, coder=coder)
        if selected_lines:
            io.set_placeholder("".join(selected_lines))

            if coder.tui and coder.tui():
                coder.tui().set_input_value("".join(selected_lines))
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

    @classmethod
    def parse_input_history_file(cls, file_path: str) -> List[str]:
        """Parse the input history file format.

        The file format consists of blocks separated by timestamp lines starting with '#'.
        Each block has lines starting with '+' for the actual input.

        Args:
            file_path: Path to the history file

        Returns:
            List of history entries (strings)
        """
        if not file_path or not os.path.exists(file_path):
            return []

        try:
            with safe_open(file_path, "r") as f:
                content = f.read()
        except (OSError, IOError):
            return []

        # Parse the file format: blocks separated by timestamp lines starting with '#'
        # Each block has lines starting with '+' for the actual input
        history = []
        current_block = []
        in_block = False

        for line in content.splitlines():
            line = line.rstrip("\n")

            if line.startswith("#"):
                # This is a timestamp line - start a new block
                if current_block:
                    # Join the current block lines and add to history
                    block_text = "\n".join(current_block)
                    history.append(block_text)
                    current_block = []
                in_block = True
                # Reset in_block if we encounter another timestamp without any + lines
                # This handles consecutive timestamp lines
            elif line.startswith("+") and in_block:
                # This is an input line in the current block
                # Remove the leading '+' and add to current block
                # Use [1:] to remove the first character (the '+')
                # This preserves any leading spaces that might be part of the input
                current_block.append(line[1:])
            elif line.strip() == "":
                # Empty line - ignore
                continue
            else:
                # Unexpected line format - skip it
                continue

        # Don't forget the last block
        if current_block:
            block_text = "\n".join(current_block)
            history.append(block_text)

        return history
