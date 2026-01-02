import subprocess
from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class GitCommand(BaseCommand):
    NORM_NAME = "git"
    DESCRIPTION = "Run a git command (output excluded from chat)"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        combined_output = None
        try:
            args = "git " + args
            env = dict(subprocess.os.environ)
            env["GIT_EDITOR"] = "true"
            result = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                shell=True,
                encoding=io.encoding,
                errors="replace",
            )
            combined_output = result.stdout
        except Exception as e:
            io.tool_error(f"Error running /git command: {e}")
            return format_command_result(io, "git", f"Error running git command: {e}", e)

        if combined_output is None:
            return format_command_result(io, "git", "No output from git command")

        io.tool_output(combined_output)
        return format_command_result(io, "git", "Git command executed successfully")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for git command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the git command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /git <git-command>  # Run any git command\n"
        help_text += "\nExamples:\n"
        help_text += "  /git status        # Show git status\n"
        help_text += "  /git diff          # Show git diff\n"
        help_text += "  /git log --oneline # Show git log\n"
        help_text += "  /git add .         # Stage all changes\n"
        help_text += "\nNote: The output of git commands is excluded from the chat history.\n"
        return help_text
