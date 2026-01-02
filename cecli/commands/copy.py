from typing import List

import pyperclip

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class CopyCommand(BaseCommand):
    NORM_NAME = "copy"
    DESCRIPTION = "Copy the last assistant message to the clipboard"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        all_messages = coder.done_messages + coder.cur_messages
        assistant_messages = [msg for msg in reversed(all_messages) if msg["role"] == "assistant"]

        if not assistant_messages:
            io.tool_error("No assistant messages found to copy.")
            return format_command_result(
                io, "copy", "No assistant messages found", Exception("No assistant messages")
            )

        last_assistant_message = assistant_messages[0]["content"]

        try:
            pyperclip.copy(last_assistant_message)
            preview = (
                last_assistant_message[:50] + "..."
                if len(last_assistant_message) > 50
                else last_assistant_message
            )
            io.tool_output(f"Copied last assistant message to clipboard. Preview: {preview}")
            return format_command_result(io, "copy", "Copied last assistant message to clipboard")
        except pyperclip.PyperclipException as e:
            io.tool_error(f"Failed to copy to clipboard: {str(e)}")
            io.tool_output("You may need to install xclip or xsel on Linux, or pbcopy on macOS.")
            return format_command_result(io, "copy", f"Failed to copy: {str(e)}", e)
        except Exception as e:
            io.tool_error(f"An unexpected error occurred while copying to clipboard: {str(e)}")
            return format_command_result(io, "copy", f"Unexpected error: {str(e)}", e)

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for copy command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the copy command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /copy  # Copy the last assistant message to clipboard\n"
        help_text += (
            "\nNote: This command copies the most recent message from the assistant to your system"
            " clipboard.\n"
        )
        help_text += (
            "If clipboard access fails, you may need to install xclip/xsel (Linux) or pbcopy"
            " (macOS).\n"
        )
        return help_text
