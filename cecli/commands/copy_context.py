from typing import List

import pyperclip

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class CopyContextCommand(BaseCommand):
    NORM_NAME = "copy-context"
    DESCRIPTION = "Copy the current chat context as markdown, suitable to paste into a web UI"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the copy-context command with given parameters."""
        chunks = coder.format_chat_chunks()

        markdown = ""

        # Only include specified chunks in order
        for messages in [chunks.repo, chunks.readonly_files, chunks.chat_files]:
            for msg in messages:
                # Only include user messages
                if msg["role"] != "user":
                    continue

                content = msg["content"]

                # Handle image/multipart content
                if isinstance(content, list):
                    for part in content:
                        if part.get("type") == "text":
                            markdown += part["text"] + "\n\n"
                else:
                    markdown += content + "\n\n"

        args = args or ""
        markdown += f"""
Just tell me how to edit the files to make the changes.
Don't give me back entire files.
Just show me the edits I need to make.

{args}
"""

        try:
            pyperclip.copy(markdown)
            io.tool_output("Copied code context to clipboard.")
            return format_command_result(io, "copy-context", "Copied code context to clipboard")
        except pyperclip.PyperclipException as e:
            io.tool_error(f"Failed to copy to clipboard: {str(e)}")
            io.tool_output("You may need to install xclip or xsel on Linux, or pbcopy on macOS.")
            return format_command_result(
                io, "copy-context", f"Failed to copy to clipboard: {str(e)}"
            )
        except Exception as e:
            io.tool_error(f"An unexpected error occurred while copying to clipboard: {str(e)}")
            return format_command_result(io, "copy-context", f"Unexpected error: {str(e)}")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for copy-context command."""
        # No specific completions for this command
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the copy-context command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /copy-context [additional instructions]  # Copy chat context to clipboard\n"
        help_text += "\nExamples:\n"
        help_text += "  /copy-context  # Copy current chat context\n"
        help_text += (
            "  /copy-context Please fix this bug  # Copy context with additional instructions\n"
        )
        help_text += (
            "\nThis command copies the current chat context as markdown to your clipboard,\n"
        )
        help_text += "making it easy to paste into web UIs or other applications.\n"
        return help_text
