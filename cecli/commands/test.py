from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class TestCommand(BaseCommand):
    NORM_NAME = "test"
    DESCRIPTION = "Run a shell command and add the output to the chat on non-zero exit code"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the test command with given parameters."""
        if not args and coder.test_cmd:
            args = coder.test_cmd

        if not args:
            return format_command_result(io, "test", "No test command provided")

        if not callable(args):
            if type(args) is not str:
                raise ValueError(repr(args))
            # Use the run command with add_on_nonzero_exit=True
            from cecli.commands import CommandRegistry

            return await CommandRegistry.execute("run", io, coder, args, add_on_nonzero_exit=True)

        errors = args()
        if not errors:
            return format_command_result(io, "test", "Test passed with no errors")

        io.tool_output(errors)
        return errors

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for test command."""
        # For test command, we could return common test commands
        # For now, return empty list
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the test command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /test <command>     # Run a test command\n"
        help_text += "  /test               # Run the default test command (if set)\n"
        help_text += (
            "\nThis command runs a shell command and automatically adds the output to the chat\n"
        )
        help_text += "if the command exits with a non-zero status (i.e., the test fails).\n"
        help_text += "If the test passes (exit code 0), the output is not added to the chat.\n"
        help_text += (
            "\nYou can set a default test command using the --test-cmd option when starting"
            " cecli.\n"
        )
        return help_text
