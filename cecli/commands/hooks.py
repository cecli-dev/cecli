"""/hooks — list, enable and disable hooks.

Subcommands: list, load, remove. The ``list`` flags (``--type``,
``--enabled-only``, ``--disabled-only``) may also be passed directly to
``/hooks`` for backwards compatibility.
"""

from typing import List

from cecli.commands.utils.base_command import BaseCommand


class HooksCommand(BaseCommand):
    NORM_NAME = "hooks"
    DESCRIPTION = "List, enable and disable hooks"

    SUBCOMMANDS = ("list", "load", "remove")
    NAME_SUBCOMMANDS = ("load", "remove")
    HELPER_MODULES = {
        "list": "cecli.commands.hooks_helpers.list",
        "load": "cecli.commands.hooks_helpers.load",
        "remove": "cecli.commands.hooks_helpers.remove",
    }
    ALIASES = {
        "list-hooks": "list",
        "load-hook": "load",
        "remove-hook": "remove",
    }
    SUBCOMMAND_USAGE = {
        "list": "/hooks list [--type T] [--enabled-only|--disabled-only]",
        "load": "/hooks load <hook-name> ...",
        "remove": "/hooks remove <hook-name> ...",
    }

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Dispatch a hooks subcommand.

        Syntax:
            /hooks list [--type T] [--enabled-only|--disabled-only]
                                        — List registered hooks (default)
            /hooks load <name>...       — Enable one or more hooks
            /hooks remove <name>...     — Disable one or more hooks
        """
        raw = (args or "").strip()
        parts = raw.split(maxsplit=1)
        sub = parts[0].lower() if parts else "list"
        rest = parts[1].strip() if len(parts) > 1 else ""

        if sub.startswith("-"):
            return cls.loader("list").cmd_list(io, coder, raw)

        if sub == "list":
            return cls.loader("list").cmd_list(io, coder, rest)

        if sub == "load":
            return cls.loader("load").cmd_load(io, coder, rest)

        if sub == "remove":
            return cls.loader("remove").cmd_remove(io, coder, rest)

        io.tool_error(f"Unknown subcommand '{sub}'. Try one of: {', '.join(cls.SUBCOMMANDS)}")

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the hooks command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /hooks list                         # List all hooks\n"
        help_text += "  /hooks list --type pre_tool         # List only pre_tool hooks\n"
        help_text += "  /hooks list --enabled-only          # List only enabled hooks\n"
        help_text += "  /hooks list --disabled-only         # List only disabled hooks\n"
        help_text += "  /hooks load <hook-name>...          # Enable one or more hooks\n"
        help_text += "  /hooks remove <hook-name>...        # Disable one or more hooks\n"
        help_text += "\nExamples:\n"
        help_text += "  /hooks\n"
        help_text += "  /hooks --type start                 # Legacy flag form\n"
        help_text += "  /hooks load my_start_hook\n"
        help_text += "  /hooks remove check_commands\n"
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

        from cecli.commands.hooks_helpers.common import hook_names

        current = "" if not rest or rest.endswith(" ") else rest.rsplit(" ", 1)[-1]
        return [name for name in hook_names(coder) if name.startswith(current)]
