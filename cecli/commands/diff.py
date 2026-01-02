from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.repo import ANY_GIT_ERROR
from cecli.run_cmd import run_cmd


class DiffCommand(BaseCommand):
    NORM_NAME = "diff"
    DESCRIPTION = "Display the diff of changes since the last message"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        try:
            await cls._raw_cmd_diff(io, coder, args)
        except ANY_GIT_ERROR as err:
            io.tool_error(f"Unable to complete diff: {err}")

    @classmethod
    async def _raw_cmd_diff(cls, io, coder, args=""):
        if not coder.repo:
            io.tool_error("No git repository found.")
            return

        current_head = coder.repo.get_head_commit_sha()
        if current_head is None:
            io.tool_error("Unable to get current commit. The repository might be empty.")
            return

        if len(coder.commit_before_message) < 2:
            commit_before_message = current_head + "^"
        else:
            commit_before_message = coder.commit_before_message[-2]

        if not commit_before_message or commit_before_message == current_head:
            io.tool_warning("No changes to display since the last message.")
            return

        io.tool_output(f"Diff since {commit_before_message[:7]}...")

        if coder.pretty:
            run_cmd(f"git diff {commit_before_message}")
            return

        diff = coder.repo.diff_commits(
            coder.pretty,
            commit_before_message,
            "HEAD",
        )

        io.print(diff)

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for diff command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the diff command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /diff  # Show changes since the last message\n"
        help_text += (
            "\nNote: This shows git diff between the current state and the state before the last"
            " message.\n"
        )
        return help_text
