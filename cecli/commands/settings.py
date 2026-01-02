from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result
from cecli.format_settings import format_settings


class SettingsCommand(BaseCommand):
    NORM_NAME = "settings"
    DESCRIPTION = "Print out the current settings"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        # Get parser and args from kwargs or use defaults
        parser = kwargs.get("parser")
        cmd_args = kwargs.get("system_args")

        if not parser or not cmd_args:
            io.tool_error("Settings command requires parser and args context")
            return format_command_result(
                io, "settings", "Missing parser or args context", Exception("Missing context")
            )

        settings = format_settings(parser, cmd_args)
        announcements = "\n".join(coder.get_announcements())

        # Build metadata for the active models (main, editor, weak)
        model_sections = []
        active_models = [
            ("Main model", coder.main_model),
            ("Editor model", getattr(coder.main_model, "editor_model", None)),
            ("Weak model", getattr(coder.main_model, "weak_model", None)),
        ]
        for label, model in active_models:
            if not model:
                continue
            info = getattr(model, "info", {}) or {}
            if not info:
                continue
            model_sections.append(f"{label} ({model.name}):")
            for k, v in sorted(info.items()):
                model_sections.append(f"  {k}: {v}")
            model_sections.append("")  # blank line between models

        model_metadata = "\n".join(model_sections)

        output = f"{announcements}\n{settings}"
        if model_metadata:
            output += "\n" + model_metadata
        io.tool_output(output)

        return format_command_result(io, "settings", "Displayed current settings")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for settings command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the settings command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /settings  # Display current settings and model information\n"
        help_text += (
            "\nNote: This command shows the current configuration including model settings,\n"
        )
        help_text += "context window size, and other runtime parameters.\n"
        return help_text
