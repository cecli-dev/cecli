"""/open — open a floating TUI panel.

Subcommands: commands (live background shell task manager),
plans (todo lists for the primary and every sub-agent), asides (raw /btw answers).
"""

from typing import List

from cecli.commands.utils.base_command import BaseCommand


class OpenCommand(BaseCommand):
    NORM_NAME = "open"
    DESCRIPTION = "Open a floating panel"

    SUBCOMMANDS = ("commands", "plans", "asides")
    SUBCOMMAND_USAGE = {
        "commands": "/open commands",
        "plans": "/open plans",
        "asides": "/open asides",
    }

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        parts = (args or "").strip().split(maxsplit=1)
        sub = parts[0].lower() if parts else "commands"

        if sub not in cls.SUBCOMMANDS:
            io.tool_error(f"Unknown panel: {sub}")
            return

        tui = coder.tui() if coder and coder.tui else None

        if tui is None:
            io.tool_output(f"/open {sub} is only available in the TUI.")
            return

        tui.call_from_thread(tui.open_panel, sub)

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Complete panel names."""
        prefix = (args or "").strip()
        return [sub for sub in cls.SUBCOMMANDS if sub.startswith(prefix)]
