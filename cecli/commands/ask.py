from typing import List

from cecli.commands.utils.base_command import BaseCommand


class AskCommand(BaseCommand):
    NORM_NAME = "ask"
    DESCRIPTION = (
        "Ask questions about the code base without editing any files. If no prompt provided,"
        " switches to ask mode."
    )

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the ask command with given parameters."""
        return await cls._generic_chat_command(io, coder, args, "ask")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for ask command."""
        # The original completions_ask raises CommandCompletionException
        # This is handled by the completion system
        from cecli.io import CommandCompletionException

        raise CommandCompletionException()

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the ask command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /ask <question>  # Ask a question about the code base\n"
        help_text += "\nExamples:\n"
        help_text += "  /ask What does this function do?  # Ask about a function\n"
        help_text += "  /ask How does this module work?   # Ask about a module\n"
        help_text += (
            "\nThis command allows you to ask questions about the code base without editing"
            " files.\n"
        )
        help_text += (
            "It switches to ask mode temporarily to answer your question, then returns to your"
            " original mode.\n"
        )
        return help_text
