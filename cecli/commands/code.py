from typing import List

from cecli.commands.utils.base_command import BaseCommand


class CodeCommand(BaseCommand):
    NORM_NAME = "code"
    DESCRIPTION = "Ask for changes to your code. If no prompt provided, switches to code mode."

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the code command with given parameters."""
        # Get the edit format from the main model, or use a default
        if coder.main_model and hasattr(coder.main_model, "edit_format"):
            edit_format = coder.main_model.edit_format
        else:
            # Default to a reasonable edit format if main_model is not available
            edit_format = "wholefile"
        return await cls._generic_chat_command(io, coder, args, edit_format)

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for code command."""
        # The original completions_code raises CommandCompletionException
        # This is handled by the completion system
        from cecli.io import CommandCompletionException

        raise CommandCompletionException()

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the code command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /code <prompt>  # Ask for changes to your code\n"
        help_text += "\nExamples:\n"
        help_text += "  /code Add a new function to calculate factorial  # Request code changes\n"
        help_text += "  /code Fix the bug in the login function          # Request bug fixes\n"
        help_text += "  /code Refactor this module to use async/await    # Request refactoring\n"
        help_text += (
            "\nThis command switches to code mode temporarily to make changes to your code,\n"
        )
        help_text += (
            "then returns to your original mode. It uses the current model's default edit format.\n"
        )
        return help_text
