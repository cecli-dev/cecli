from typing import List

from cecli.commands.utils.base_command import BaseCommand


class ArchitectCommand(BaseCommand):
    NORM_NAME = "architect"
    DESCRIPTION = (
        "Enter architect/editor mode using 2 different models. If no prompt provided, switches to"
        " architect/editor mode."
    )

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the architect command with given parameters."""
        return await cls._generic_chat_command(io, coder, args, "architect")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for architect command."""
        # The original completions_architect raises CommandCompletionException
        # This is handled by the completion system
        from cecli.io import CommandCompletionException

        raise CommandCompletionException()

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the architect command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /architect <prompt>  # Enter architect/editor mode\n"
        help_text += "\nExamples:\n"
        help_text += "  /architect Design a new API endpoint  # Use architect mode for design\n"
        help_text += (
            "  /architect Plan the refactoring of this module  # Use architect mode for planning\n"
        )
        help_text += (
            "\nThis command switches to architect/editor mode temporarily to work on design and"
            " planning tasks,\n"
        )
        help_text += (
            "then returns to your original mode. Architect mode uses two different models for"
            " planning and editing.\n"
        )
        return help_text
