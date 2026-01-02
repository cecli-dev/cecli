from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result
from cecli.repo import ANY_GIT_ERROR


class CommitCommand(BaseCommand):
    NORM_NAME = "commit"
    DESCRIPTION = "Commit edits to the repo made outside the chat (commit message optional)"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the commit command with given parameters."""
        try:
            return await cls._raw_cmd_commit(io, coder, args)
        except ANY_GIT_ERROR as err:
            io.tool_error(f"Unable to complete commit: {err}")
            return format_command_result(io, "commit", f"Unable to complete commit: {err}", err)

    @classmethod
    async def _raw_cmd_commit(cls, io, coder, args):
        """Raw commit implementation without error handling."""
        if not coder.repo:
            io.tool_error("No git repository found.")
            return format_command_result(io, "commit", "No git repository found")

        if not coder.repo.is_dirty():
            io.tool_warning("No more changes to commit.")
            return format_command_result(io, "commit", "No more changes to commit")

        commit_message = args.strip() if args else None
        await coder.repo.commit(message=commit_message, coder=coder)
        return format_command_result(io, "commit", "Changes committed successfully")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for commit command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the commit command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /commit              # Commit changes with auto-generated message\n"
        help_text += "  /commit <message>    # Commit changes with specific message\n"
        help_text += "\nThis command commits all uncommitted changes in the repository.\n"
        help_text += "If no commit message is provided, an auto-generated message will be used.\n"
        help_text += "\nNote: This only commits changes made outside the chat session.\n"
        help_text += "Changes made by cecli during the chat are automatically committed.\n"
        return help_text
