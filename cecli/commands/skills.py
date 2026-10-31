"""/skills — manage skills (list, load, include, exclude, remove, import).

Subcommands are dispatched to helper functions in ``cecli.commands.skills_helpers``.
"""

from typing import List

from cecli.commands.utils.base_command import BaseCommand


class SkillsCommand(BaseCommand):
    NORM_NAME = "skills"
    DESCRIPTION = "Manage skills (list, load, include, exclude, remove, import)"

    SUBCOMMANDS = ("list", "load", "include", "exclude", "remove", "import")
    NAME_SUBCOMMANDS = ("load", "include", "exclude", "remove")
    HELPER_MODULES = {
        "list": "cecli.commands.skills_helpers.list",
        "load": "cecli.commands.skills_helpers.load",
        "include": "cecli.commands.skills_helpers.include",
        "exclude": "cecli.commands.skills_helpers.exclude",
        "remove": "cecli.commands.skills_helpers.remove",
        "import": "cecli.commands.skills_helpers.import_skill",
    }
    SUBCOMMAND_USAGE = {
        "list": "/skills list",
        "load": "/skills load <skill-name> ...",
        "include": "/skills include <skill-name> ...",
        "exclude": "/skills exclude <skill-name> ...",
        "remove": "/skills remove <skill-name> ...",
        "import": "/skills import [--global] <skill-name>",
    }

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Dispatch a skills subcommand.

        Syntax:
            /skills list             — Show all skills and their states
            /skills load <name>...   — Load one or more skills (agent mode)
            /skills include <name>...— Whitelist one or more skills (agent mode)
            /skills exclude <name>...— Blacklist one or more skills (agent mode)
            /skills remove <name>... — Remove one or more skills (agent mode)
            /skills import [--global] <name> — Import a skill from the registry
        """
        parts = (args or "").strip().split(maxsplit=1)
        sub = parts[0].lower() if parts else "list"
        rest = parts[1].strip() if len(parts) > 1 else ""

        if sub == "list":
            return await cls.loader("list").cmd_list(io, coder)
        elif sub == "load":
            return await cls.loader("load").cmd_load(io, coder, rest)
        elif sub == "include":
            return await cls.loader("include").cmd_include(io, coder, rest)
        elif sub == "exclude":
            return await cls.loader("exclude").cmd_exclude(io, coder, rest)
        elif sub == "remove":
            return await cls.loader("remove").cmd_remove(io, coder, rest)
        elif sub == "import":
            return await cls.loader("import").cmd_import(io, coder, rest)

        io.tool_error(f"Unknown subcommand '{sub}'. Try one of: {', '.join(cls.SUBCOMMANDS)}")

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the skills command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /skills list                       # List skills and their paths\n"
        help_text += "  /skills load <skill-name>...       # Load one or more skills\n"
        help_text += "  /skills include <skill-name>...    # Whitelist one or more skills\n"
        help_text += "  /skills exclude <skill-name>...    # Blacklist one or more skills\n"
        help_text += "  /skills remove <skill-name>...     # Remove one or more skills\n"
        help_text += "  /skills import [--global] <skill-name>  # Import a skill\n"
        help_text += "\nExamples:\n"
        help_text += (
            "  /skills list  # Shows a table of all skills, their include/exclude/visible status,\n"
        )
        help_text += "                # whether they are loaded, and their directory paths\n"
        help_text += "  /skills load pdf  # Load the PDF skill\n"
        help_text += "  /skills load web pdf  # Load both web and PDF skills\n"
        help_text += "  /skills include pdf  # Include (whitelist) the PDF skill\n"
        help_text += "  /skills include web pdf  # Include both web and PDF skills\n"
        help_text += "  /skills exclude pdf  # Exclude (blacklist) the PDF skill\n"
        help_text += "  /skills exclude web pdf  # Exclude both web and PDF skills\n"
        help_text += "  /skills remove pdf  # Remove the PDF skill\n"
        help_text += "  /skills remove web pdf  # Remove both web and PDF skills\n"
        help_text += (
            "  /skills import files/docx  # Import the docx skill from the community registry\n"
        )
        help_text += "  /skills import --global pdf  # Import the PDF skill globally\n"
        help_text += "\n"
        help_text += (
            "Skills are only available in agent mode. /skills list shows all skills found in the\n"
        )
        help_text += "configured skill directories, displaying their current status\n"
        help_text += (
            "(included/excluded/visible), whether they are loaded into context, and their\n"
        )
        help_text += "file system paths.\n"
        help_text += (
            "Loading pulls a skill and its tools into the agent's context, while including\n"
        )
        help_text += (
            "adds it to the whitelist: when a skill is included, only whitelisted skills will\n"
        )
        help_text += (
            "be discoverable. Excluded skills are hidden from discovery and unavailable for\n"
        )
        help_text += "loading.\n"
        help_text += "\n"
        help_text += (
            "Skills are looked up in the cecli community registry first, then on skills.sh.\n"
        )
        help_text += "The imported skill is added to the current session like /skills include.\n"
        return help_text

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Complete the subcommand, then each argument in turn.

        The whole argument string is used so a space moves completion on to
        the next argument (e.g. ``include pdf `` offers more skills).
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

        if sub == "import":
            return cls._import_completions(io, coder, rest)

        if sub not in cls.NAME_SUBCOMMANDS:
            return []

        return cls._name_completions(io, coder, sub, rest)

    @classmethod
    def _name_completions(cls, io, coder, sub, rest) -> List[str]:
        """Filter the subcommand's skill names by the argument being typed."""
        current = "" if not rest or rest.endswith(" ") else rest.rsplit(" ", 1)[-1]
        names = cls.loader(sub).get_completions(io, coder)
        return [name for name in names if name.startswith(current)]

    @classmethod
    def _import_completions(cls, io, coder, rest) -> List[str]:
        """Complete ``import`` flags first, then registry skill names."""
        if not rest or rest.endswith(" "):
            completed, current = rest.split(), ""
        else:
            head, _, current = rest.rpartition(" ")
            completed = head.split()

        candidates = cls.loader("import").get_completions(io, coder)
        if any(token in ("--global", "-g") for token in completed):
            candidates = [c for c in candidates if c not in ("--global", "-g")]

        return [c for c in candidates if c.startswith(current)]
