from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class CommandPrefixCommand(BaseCommand):
    NORM_NAME = "command-prefix"
    DESCRIPTION = "Change Command Prefix For All Running Commands"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the command-prefix command with given parameters."""
        if not args.strip():
            setattr(coder.args, "command_prefix", "")
            io.tool_output("Command prefix cleared.")
            return format_command_result(io, "command-prefix", "Command prefix cleared")

        setattr(coder.args, "command_prefix", args.strip())
        io.tool_output(f"Command prefix set to: {args.strip()}")
        return format_command_result(io, "command-prefix", f"Command prefix set to: {args.strip()}")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for command-prefix command."""
        # No specific completions for this command
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the command-prefix command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /command-prefix <prefix>  # Set command prefix\n"
        help_text += "  /command-prefix           # Clear command prefix\n"
        help_text += "\nExamples:\n"
        help_text += "  /command-prefix !  # Use ! as command prefix\n"
        help_text += "  /command-prefix $  # Use $ as command prefix\n"
        help_text += "  /command-prefix    # Clear command prefix (use default /)\n"
        help_text += "\nThis command changes the prefix used for all commands.\n"
        help_text += (
            "The default prefix is '/'. After changing, use the new prefix for all commands.\n"
        )
        return help_text
