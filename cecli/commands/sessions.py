"""/sessions — list, load and save chat sessions.

Subcommands are dispatched to helper functions in
``cecli.commands.sessions_helpers``.
"""

from typing import List

from cecli.commands.utils.base_command import BaseCommand


class SessionsCommand(BaseCommand):
    NORM_NAME = "sessions"
    DESCRIPTION = "List, load and save chat sessions"

    SUBCOMMANDS = ("list", "load", "save")
    NAME_SUBCOMMANDS = ("load", "save")
    HELPER_MODULES = {
        "list": "cecli.commands.sessions_helpers.list",
        "load": "cecli.commands.sessions_helpers.load",
        "save": "cecli.commands.sessions_helpers.save",
    }
    SUBCOMMAND_USAGE = {
        "list": "/sessions list",
        "load": "/sessions load <session-name>",
        "save": "/sessions save <session-name>",
    }

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Dispatch a sessions subcommand.

        Syntax:
            /sessions list                  — List saved sessions (default)
            /sessions load <name-or-path>   — Load a saved session
            /sessions save <name>           — Save the current session
        """
        parts = (args or "").strip().split(maxsplit=1)
        sub = parts[0].lower() if parts else "list"
        rest = parts[1].strip() if len(parts) > 1 else ""

        if sub == "list":
            return cls.loader("list").cmd_list(io, coder, rest)

        if sub == "load":
            return await cls.loader("load").cmd_load(io, coder, rest)

        if sub == "save":
            return cls.loader("save").cmd_save(io, coder, rest)

        io.tool_error(f"Unknown subcommand '{sub}'. Try one of: {', '.join(cls.SUBCOMMANDS)}")

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the sessions command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /sessions list                     # List saved sessions\n"
        help_text += "  /sessions load <session-name>      # Load a saved session\n"
        help_text += "  /sessions save <session-name>      # Save the current session\n"
        help_text += "\nSessions are stored in the .cecli/sessions/ directory. Loading a session\n"
        help_text += "also restores any sub-agents saved with it.\n"
        help_text += "\nExamples:\n"
        help_text += "  /sessions list\n"
        help_text += "  /sessions load my-feature\n"
        help_text += "  /sessions save bug-fix\n"
        return help_text

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Complete the subcommand, then each argument in turn."""
        head = (args or "").lstrip()

        if not head:
            return list(cls.SUBCOMMANDS)

        if " " not in head:
            return [s for s in cls.SUBCOMMANDS if s.startswith(head.lower())] or list(
                cls.SUBCOMMANDS
            )

        sub, _, rest = head.partition(" ")
        sub = sub.lower()
        if sub not in cls.NAME_SUBCOMMANDS:
            return []

        from cecli.commands.sessions_helpers.common import session_names

        current = "" if not rest or rest.endswith(" ") else rest.rsplit(" ", 1)[-1]
        return [name for name in session_names(coder, io) if name.startswith(current)]
