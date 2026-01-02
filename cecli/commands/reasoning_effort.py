from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class ReasoningEffortCommand(BaseCommand):
    NORM_NAME = "reasoning-effort"
    DESCRIPTION = (
        "Set the reasoning effort level (values: number or low/medium/high depending on model)"
    )

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the reasoning-effort command with given parameters."""
        model = coder.main_model

        if not args.strip():
            # Display current value if no args are provided
            reasoning_value = model.get_reasoning_effort()
            if reasoning_value is None:
                io.tool_output("Reasoning effort is not currently set.")
                return format_command_result(
                    io, "reasoning-effort", "Displayed current reasoning effort status"
                )
            else:
                io.tool_output(f"Current reasoning effort: {reasoning_value}")
                return format_command_result(
                    io, "reasoning-effort", f"Displayed current reasoning effort: {reasoning_value}"
                )

        value = args.strip()
        model.set_reasoning_effort(value)
        reasoning_value = model.get_reasoning_effort()
        io.tool_output(f"Set reasoning effort to {reasoning_value}")
        io.tool_output()

        # Output announcements
        announcements = "\n".join(coder.get_announcements())
        io.tool_output(announcements)

        return format_command_result(
            io, "reasoning-effort", f"Set reasoning effort to {reasoning_value}"
        )

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for reasoning-effort command."""
        # Common reasoning effort values
        return ["low", "medium", "high"]

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the reasoning-effort command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /reasoning-effort              # Show current reasoning effort\n"
        help_text += "  /reasoning-effort <value>      # Set reasoning effort\n"
        help_text += "\nExamples:\n"
        help_text += "  /reasoning-effort low          # Set to low reasoning effort\n"
        help_text += "  /reasoning-effort medium       # Set to medium reasoning effort\n"
        help_text += "  /reasoning-effort high         # Set to high reasoning effort\n"
        help_text += "  /reasoning-effort 0.5          # Set to 0.5 (numeric value)\n"
        help_text += (
            "\nThis command sets the reasoning effort level for models that support reasoning.\n"
        )
        help_text += (
            "The available values depend on the model (e.g., low/medium/high or numeric values).\n"
        )
        return help_text
