"""/mcp — manage MCP servers (list, load, remove).

Consolidates the former ``/list-mcp``, ``/load-mcp`` and ``/remove-mcp``
commands; the per-subcommand logic lives in ``cecli.commands.mcp_helpers``.
"""

from cecli.commands.utils.base_command import BaseCommand


class McpCommand(BaseCommand):
    NORM_NAME = "mcp"
    DESCRIPTION = "Manage MCP servers (list, load, remove)"

    SUBCOMMANDS = ("list", "load", "remove")
    NAME_SUBCOMMANDS = ("load", "remove")
    HELPER_MODULES = {
        "list": "cecli.commands.mcp_helpers.list",
        "load": "cecli.commands.mcp_helpers.load",
        "remove": "cecli.commands.mcp_helpers.remove",
    }

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Dispatch an mcp subcommand.

        Syntax:
            /mcp list                   — List MCP servers (default)
            /mcp load <mcp-name>...     — Load one or more mcps by name
            /mcp load *                 — Load all mcps enabled by default
            /mcp remove <mcp-name>...   — Remove one or more mcps by name
            /mcp remove *               — Remove all connected mcps
        """
        parts = (args or "").strip().split(maxsplit=1)
        sub = parts[0].lower() if parts else "list"
        rest = parts[1].strip() if len(parts) > 1 else ""

        if sub == "list":
            return await cls.loader("list").cmd_list(io, coder)

        if sub == "load":
            return await cls.loader("load").cmd_load(io, coder, rest)

        if sub == "remove":
            return await cls.loader("remove").cmd_remove(io, coder, rest)

        io.tool_error(f"Unknown subcommand '{sub}'. Try one of: {', '.join(cls.SUBCOMMANDS)}")

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the mcp command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += (
            "  /mcp list                    # Lists MCP servers with coder-sensitive"
            " active/inactive/configured status\n"
        )
        help_text += "  /mcp load <mcp-name>...      # Load one or more mcps by name\n"
        help_text += "  /mcp load *                  # Load all mcps enabled by default\n"
        help_text += "  /mcp remove <mcp-name>...    # Remove one or more mcps by name\n"
        help_text += "  /mcp remove *                # Remove all connected mcps\n"
        help_text += "\nExamples:\n"
        help_text += "  /mcp load context7           # Load the context7 mcp\n"
        help_text += "  /mcp load github context7    # Load both github and context7 mcps\n"
        help_text += "  /mcp remove context7         # Remove the context7 mcp\n"
        help_text += "  /mcp remove github context7  # Remove both github and context7 mcps\n"
        help_text += "  /mcp remove *                # Remove all connected mcps\n"
        return help_text

    @classmethod
    def get_completions(cls, io, coder, args) -> list:
        """Complete the subcommand, then each argument in turn.

        The whole argument string is used so a space moves completion on to
        the next argument (e.g. ``load context7 `` offers more servers).
        """
        raw = args or ""
        head = raw.lstrip()

        if not head:
            return list(cls.SUBCOMMANDS)

        if " " not in head:
            return [s for s in cls.SUBCOMMANDS if s.startswith(head.lower())] or list(
                cls.SUBCOMMANDS
            )

        sub, _, rest = head.partition(" ")
        sub = sub.lower()
        if sub not in cls.SUBCOMMANDS:
            return []

        if sub not in cls.NAME_SUBCOMMANDS:
            return []

        return cls._name_completions(io, coder, sub, rest)

    @classmethod
    def _name_completions(cls, io, coder, sub, rest):
        """Filter the subcommand's server names by the argument being typed."""
        current = "" if not rest or rest.endswith(" ") else rest.rsplit(" ", 1)[-1]
        names = cls.loader(sub).get_completions(io, coder)
        return [name for name in names if name.startswith(current)]
