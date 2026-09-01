from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.signals import ReloadProgramSignal


class HotReloadCommand(BaseCommand):
    NORM_NAME = "hot-reload"
    DESCRIPTION = "Hot-reload all configuration and restart the program"
    show_completion_notification = False

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Raise ReloadProgramSignal to trigger a full program hot-reload.

        Passes the current coder as from_coder so the new coder
        preserves its UUID, edit_format, and other state across
        the reload cycle.
        """
        io.tool_output("Hot-reloading program configuration...")
        raise ReloadProgramSignal(
            "User requested configuration reload",
            from_coder=coder,
        )

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for hot-reload command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the hot-reload command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /hot-reload  # Hot-reload all configuration files and restart\n"
        help_text += "\nThis will re-read config files, reinitialize the connection,"
        help_text += " and restart the chat session with the updated configuration."
        return help_text
