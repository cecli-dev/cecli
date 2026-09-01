"""Remove-memory command - delete facts from the Memorizer fact database.

Parses a list of fact ids from the argument string — any separator is
accepted (spaces, commas, semicolons, etc.) — and forwards them to the
``remove_facts`` memory utility for deletion.
"""

import re
from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class RemoveMemoryCommand(BaseCommand):
    NORM_NAME = "remove-memory"
    DESCRIPTION = "Remove facts from the memory fact database by id"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Remove facts from the memory fact database by their ids.

        Syntax:
            /remove-memory <id> [<id> ...]

        Ids may be separated by any non-numeric character (spaces,
        commas, semicolons, etc.).  Each continuous run of digits is
        treated as a fact id and forwarded to ``remove_facts`` for
        deletion from the database.
        """
        from cecli.helpers.memory.utils import remove_facts

        id_facts = [int(m) for m in re.findall(r"\d+", args)]

        if not id_facts:
            io.tool_error("Usage: /remove-memory <id> [<id> ...]")

            return format_command_result(io, cls.NORM_NAME, "No fact ids provided")

        try:
            removed = remove_facts(coder, id_facts=id_facts)
        except Exception as exc:
            return format_command_result(io, cls.NORM_NAME, "Remove failed", str(exc))

        io.tool_output(f"Removed {removed} fact(s): {', '.join(str(i) for i in id_facts)}")

        return format_command_result(io, cls.NORM_NAME, f"Removed {removed} fact(s)")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Return completion options for remove-memory."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the remove-memory command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /remove-memory <id> [<id> ...]  # Delete facts from the fact database\n"
        help_text += "\nExamples:\n"
        help_text += "  /remove-memory 1\n"
        help_text += "  /remove-memory 1,2,3 7 10,30\n"
        help_text += "\nIds may be separated by any non-numeric character; each\n"
        help_text += "continuous run of digits is treated as a fact id.\n"

        return help_text
