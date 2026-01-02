from typing import List

import cecli.models as models
from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class ModelsCommand(BaseCommand):
    NORM_NAME = "models"
    DESCRIPTION = "Search the list of available models"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the models command with given parameters."""
        args = args.strip()

        if args:
            models.print_matching_models(io, args)
        else:
            io.tool_output("Please provide a partial model name to search for.")

        return format_command_result(io, "models", "Displayed model search results")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for models command."""
        return models.get_chat_model_names()

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the models command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /models <partial-name>  # Search for models matching the partial name\n"
        help_text += "\nExamples:\n"
        help_text += "  /models gpt-4          # Search for GPT-4 models\n"
        help_text += "  /models claude         # Search for Claude models\n"
        help_text += "  /models o1             # Search for o1 models\n"
        help_text += "\nThis command searches through the available LLM models and displays\n"
        help_text += "matching models with their details including cost and capabilities.\n"
        return help_text
