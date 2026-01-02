from typing import List

from cecli.commands.utils.base_command import BaseCommand


class AgentCommand(BaseCommand):
    NORM_NAME = "agent"
    DESCRIPTION = (
        "Enter agent mode to autonomously discover and manage relevant files. If no prompt"
        " provided, switches to agent mode."
    )

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the agent command with given parameters."""
        # Enable context management when entering agent mode
        if hasattr(coder, "context_management_enabled"):
            coder.context_management_enabled = True
            io.tool_output("Context management enabled for large files")

        return await cls._generic_chat_command(
            io, coder, args, "agent", placeholder=args.strip() or None
        )

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for agent command."""
        # The original completions_agent raises CommandCompletionException
        # This is handled by the completion system
        from cecli.io import CommandCompletionException

        raise CommandCompletionException()

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the agent command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /agent <prompt>  # Enter agent mode\n"
        help_text += "\nExamples:\n"
        help_text += "  /agent Fix this bug  # Use agent mode to autonomously fix a bug\n"
        help_text += "  /agent Add a new feature  # Use agent mode to implement a feature\n"
        help_text += (
            "\nThis command switches to agent mode temporarily to autonomously discover and manage"
            " files,\n"
        )
        help_text += (
            "then returns to your original mode. Agent mode enables context management for large"
            " files.\n"
        )
        return help_text
