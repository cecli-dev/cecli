"""Subcommand helper for ``/queue remove``."""

from cecli.commands.utils.helpers import format_command_result
from cecli.helpers import command_queue


def cmd_remove(io, coder, args):
    """Remove a prompt from the queue by index, or ``*`` to clear all."""
    if not coder.commands:
        return format_command_result(
            io,
            "remove-queue",
            "",
            error="Command system not available. Cannot remove from queue.",
        )

    if command_queue.get_queue_length(coder) == 0:
        return format_command_result(
            io, "remove-queue", "", error="Queue is empty. Nothing to remove."
        )

    if args and args.strip() == "*":
        items = command_queue.clear_queue(coder)
        count = len(items)
        io.tool_output(f"Removed all {count} queued prompt(s).")
        return "Successfully executed remove-queue."

    if args and args.strip():
        try:
            index = int(args.strip()) - 1
        except ValueError:
            return format_command_result(
                io,
                "remove-queue",
                "",
                error=f"Invalid index: '{args.strip()}'. Please provide a number or '*'.",
            )

        item = command_queue.remove_from_queue(coder, index)
        if item is None:
            queue_len = command_queue.get_queue_length(coder)
            return format_command_result(
                io,
                "remove-queue",
                "",
                error=f"Index {args.strip()} is out of range. Queue has {queue_len} item(s).",
            )

        io.tool_output(f"Removed: {item['text'][:80]}")
        return "Successfully executed remove-queue."

    queue = command_queue.list_queue(coder)
    io.tool_output("Queued prompts:")
    for i, item in enumerate(queue, 1):
        text = item["text"][:80]
        if len(item["text"]) > 80:
            text += "..."
        io.tool_output(f"  [{i}] {text}")

    io.tool_output("\nEnter index to remove, '*' to clear all, or press Enter to cancel:")
    return format_command_result(
        io, "remove-queue", "Usage: /queue remove <index> | /queue remove *"
    )
