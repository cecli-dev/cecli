from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class ThinkTokensCommand(BaseCommand):
    NORM_NAME = "think-tokens"
    DESCRIPTION = "Set the thinking token budget, eg: 8096, 8k, 10.5k, 0.5M, or 0 to disable"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the think-tokens command with given parameters."""
        model = coder.main_model

        if not args.strip():
            # Display current value if no args are provided
            formatted_budget = model.get_thinking_tokens()
            if formatted_budget is None:
                io.tool_output("Thinking tokens are not currently set.")
                return format_command_result(
                    io, "think-tokens", "Displayed current thinking token status"
                )
            else:
                budget = model.get_raw_thinking_tokens()
                io.tool_output(
                    f"Current thinking token budget: {budget:,} tokens ({formatted_budget})."
                )
                return format_command_result(
                    io,
                    "think-tokens",
                    f"Displayed current thinking token budget: {budget:,} tokens",
                )

        value = args.strip()
        model.set_thinking_tokens(value)

        # Handle the special case of 0 to disable thinking tokens
        if value == "0":
            io.tool_output("Thinking tokens disabled.")
            return format_command_result(io, "think-tokens", "Thinking tokens disabled")
        else:
            formatted_budget = model.get_thinking_tokens()
            budget = model.get_raw_thinking_tokens()
            io.tool_output(f"Set thinking token budget to {budget:,} tokens ({formatted_budget}).")
            return format_command_result(
                io, "think-tokens", f"Set thinking token budget to {budget:,} tokens"
            )

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for think-tokens command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the think-tokens command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /think-tokens              # Show current thinking token budget\n"
        help_text += "  /think-tokens <budget>     # Set thinking token budget\n"
        help_text += "\nExamples:\n"
        help_text += "  /think-tokens 8096         # Set to 8096 tokens\n"
        help_text += "  /think-tokens 8k           # Set to 8,000 tokens\n"
        help_text += "  /think-tokens 10.5k        # Set to 10,500 tokens\n"
        help_text += "  /think-tokens 0.5M         # Set to 500,000 tokens\n"
        help_text += "  /think-tokens 0            # Disable thinking tokens\n"
        help_text += (
            "\nThis command sets the thinking token budget for models that support reasoning.\n"
        )
        help_text += (
            "Thinking tokens are used for internal reasoning before generating a response.\n"
        )
        return help_text
