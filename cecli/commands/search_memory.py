"""Search-memory command - search the Memorizer fact database.

Runs the same full-text search the memorizer sub-agent uses (FTS5
prefix match over fact text via ``search_facts``) and prints the id,
category (tags) and text of every matching fact.
"""

from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class SearchMemoryCommand(BaseCommand):
    NORM_NAME = "search-memory"
    DESCRIPTION = "Search the memory fact database (same search the memorizer uses)"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Search the memory fact database.

        Syntax:
            /search-memory <word> [<word> ...]

        Each word is matched as a prefix against the fact text, exactly
        like the memorizer's SearchFacts tool.  Matching facts are shown
        with their id, category (tags) and text.
        """
        from cecli.helpers.memory.utils import search_facts

        words = args.strip().split()

        if not words:
            io.tool_error("Usage: /search-memory <word> [<word> ...]")

            return format_command_result(io, cls.NORM_NAME, "No search terms provided")

        try:
            results = search_facts(coder, words=words)
        except Exception as exc:
            return format_command_result(io, cls.NORM_NAME, "Search failed", str(exc))

        if not results:
            io.tool_output(f"No facts found matching: {' '.join(words)}")

            return format_command_result(io, cls.NORM_NAME, "No matching facts")

        io.tool_output(f"Found {len(results)} fact(s) matching: {' '.join(words)}")

        for r in results:
            category = ", ".join(r["tags"]) if r["tags"] else "(uncategorized)"
            io.tool_output(f"[{r['id_fact']}] ({category})\n{r['fact']}\n")

        return format_command_result(io, cls.NORM_NAME, f"Found {len(results)} matching fact(s)")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Return completion options for search-memory."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the search-memory command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /search-memory <word> [<word> ...]  # Search the fact database\n"
        help_text += "\nExamples:\n"
        help_text += "  /search-memory preferences\n"
        help_text += "  /search-memory memory db schema\n"
        help_text += "\nRuns the same FTS5 prefix search the memorizer sub-agent uses and\n"
        help_text += "prints each match with its id, category (tags) and text.\n"

        return help_text
