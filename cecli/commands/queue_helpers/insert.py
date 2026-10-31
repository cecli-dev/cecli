"""Subcommand helper for ``/queue insert``."""

from cecli.commands.utils.helpers import format_command_result
from cecli.helpers import command_queue


def cmd_insert(io, coder, args):
    """Insert a prompt into the queue at a specific position.

    Args:
        io: InputOutput instance
        coder: Coder instance (may be None for some commands)
        args: ``"<index> <prompt text>"``

    Returns:
        Formatted result string
    """
    if not coder.commands:
        return format_command_result(
            io,
            "insert-queue",
            "",
            error="Command system not available. Cannot insert into queue.",
        )

    parts = (args or "").strip().split(maxsplit=1)
    if len(parts) != 2:
        return format_command_result(
            io, "insert-queue", "", error="Usage: /queue insert <index> <prompt text>"
        )

    try:
        index = int(parts[0])
    except ValueError:
        return format_command_result(
            io,
            "insert-queue",
            "",
            error=f"Invalid index: '{parts[0]}'. Please provide a number.",
        )

    prompt_text = parts[1].strip()

    try:
        item = command_queue.insert_prompt(coder, prompt_text, index)
        io.tool_output(f"Prompt inserted at position {index + 1} (id: {item['id']})")

        return "Successfully executed insert-queue."
    except ValueError as e:
        return format_command_result(io, "insert-queue", "", error=str(e))
    except RuntimeError as e:
        return format_command_result(io, "insert-queue", "", error=str(e))
