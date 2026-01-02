from typing import List

from cecli.commands.utils.base_command import BaseCommand


class ContextCommand(BaseCommand):
    NORM_NAME = "context"
    DESCRIPTION = (
        "Enter context mode to see surrounding code context. If no prompt provided, switches to"
        " context mode."
    )

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the context command with given parameters."""
        return await cls._generic_chat_command(
            io, coder, args, "context", placeholder=args.strip() or None
        )

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for context command."""
        # The original completions_context raises CommandCompletionException
        # This is handled by the completion system
        from cecli.io import CommandCompletionException

        raise CommandCompletionException()

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the context command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /context <prompt>  # Enter context mode to see surrounding code context\n"
        help_text += "\nExamples:\n"
        help_text += (
            "  /context What files are related to this function?  # Ask about code context\n"
        )
        help_text += (
            "  /context Show me the imports in this module        # Ask about module structure\n"
        )
        help_text += (
            "\nThis command switches to context mode temporarily to examine code context,\n"
        )
        help_text += "then returns to your original mode. Context mode is designed for exploring\n"
        help_text += "and understanding code without making changes.\n"
        return help_text
