"""/queue — queue prompts and manage the processing queue.

Subcommands: add, insert, list, remove, run. Bare text after ``/queue`` is
treated as ``add`` for backwards compatibility.
"""

from typing import List

from cecli.commands.utils.base_command import BaseCommand


class QueueCommand(BaseCommand):
    NORM_NAME = "queue"
    DESCRIPTION = "Queue a prompt or manage the processing queue"

    SUBCOMMANDS = ("add", "insert", "list", "remove", "run")
    NAME_SUBCOMMANDS = ()
    HELPER_MODULES = {
        "add": "cecli.commands.queue_helpers.add",
        "insert": "cecli.commands.queue_helpers.insert",
        "list": "cecli.commands.queue_helpers.list",
        "remove": "cecli.commands.queue_helpers.remove",
        "run": "cecli.commands.queue_helpers.run",
    }

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Dispatch a queue subcommand.

        Syntax:
            /queue add <prompt>             — Queue a prompt
            /queue <prompt>                 — Legacy shorthand for add
            /queue insert <index> <prompt>  — Insert at a 1-based position
            /queue list                     — Show queued prompts
            /queue remove <index>|*         — Remove one prompt or clear the queue
            /queue run                      — Process queued prompts now
        """
        raw = (args or "").strip()
        parts = raw.split(maxsplit=1)
        sub = parts[0].lower() if parts else ""
        rest = parts[1].strip() if len(parts) > 1 else ""

        if sub == "add":
            return cls.loader("add").cmd_add(io, coder, rest)

        if sub == "insert":
            return cls.loader("insert").cmd_insert(io, coder, rest)

        if sub == "list":
            return cls.loader("list").cmd_list(io, coder, rest)

        if sub == "remove":
            return cls.loader("remove").cmd_remove(io, coder, rest)

        if sub == "run":
            return await cls.loader("run").cmd_run(io, coder, rest)

        return cls.loader("add").cmd_add(io, coder, raw)

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Complete the subcommand, then the current argument token.

        ``add`` and the prompt portion of ``insert`` delegate to nested slash
        command completion so ``/queue add /ad<tab>`` behaves like ``/ad<tab>``.
        """
        from cecli.helpers import command_queue

        head = (args or "").lstrip()

        if not head:
            return list(cls.SUBCOMMANDS)

        if head.startswith("/"):
            return command_queue.nested_command_completions(coder, head)

        if " " not in head:
            return [s for s in cls.SUBCOMMANDS if s.startswith(head.lower())] or list(
                cls.SUBCOMMANDS
            )

        sub, _, rest = head.partition(" ")
        sub = sub.lower()
        if sub not in cls.SUBCOMMANDS:
            # Legacy shorthand: the whole argument string is an add prompt.
            return command_queue.nested_command_completions(coder, head)

        if sub == "add":
            return command_queue.nested_command_completions(coder, rest)

        if sub == "insert":
            first_space = rest.find(" ")
            if first_space == -1:
                return cls._index_completions(coder)

            return command_queue.nested_command_completions(coder, rest[first_space + 1 :])

        if sub == "remove":
            return cls._remove_completions(coder)

        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the queue command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /queue <prompt text>              # Queue a prompt for later processing\n"
        help_text += "  /queue add <prompt text>          # Same as above, explicit form\n"
        help_text += "  /queue insert <index> <prompt>    # Insert at a 1-based position\n"
        help_text += "  /queue list                       # Display all queued prompts\n"
        help_text += "  /queue remove <index>             # Remove the prompt at an index\n"
        help_text += "  /queue remove *                   # Clear the entire queue\n"
        help_text += "  /queue run                        # Process all queued prompts now\n"
        help_text += "\nDescription:\n"
        help_text += "  Queued prompts are processed sequentially after the current command\n"
        help_text += "  completes. The queue is in-memory only (lost on session restart).\n"
        help_text += "\nExamples:\n"
        help_text += "  /queue Review the changes in src/main.py\n"
        help_text += "  /queue insert 1 Write tests for the new feature\n"
        help_text += "  /queue remove 2\n"
        return help_text

    @classmethod
    def _index_completions(cls, coder) -> List[str]:
        """Suggest valid 1-based insertion positions."""
        from cecli.helpers import command_queue

        if not coder.commands:
            return []

        return [str(i) for i in range(1, command_queue.get_queue_length(coder) + 2)]

    @classmethod
    def _remove_completions(cls, coder) -> List[str]:
        """Suggest queue indices plus the clear-all wildcard."""
        from cecli.helpers import command_queue

        if not coder.commands:
            return []

        completions = [str(i) for i in range(1, command_queue.get_queue_length(coder) + 1)]
        completions.append("*")
        return completions
