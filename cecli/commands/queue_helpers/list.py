"""Subcommand helper for ``/queue list``."""

import datetime

from cecli.commands.utils.helpers import format_command_result
from cecli.helpers import command_queue


def cmd_list(io, coder, args):
    """Display all prompts currently in the queue."""
    if not coder.commands:
        return format_command_result(
            io,
            "list-queue",
            "",
            error="Command system not available. Cannot list queue.",
        )

    queue = command_queue.list_queue(coder)

    if not queue:
        io.tool_output("Queue is empty.")
        return "Successfully executed list-queue."

    lines = []
    for i, item in enumerate(queue, start=1):
        text = item["text"]
        display_text = text[:80] + "..." if len(text) > 80 else text
        ts = datetime.datetime.fromtimestamp(item["timestamp"]).strftime("%H:%M:%S")
        lines.append(f"[{i}] {display_text} ({ts})")

    io.tool_output("\n".join(lines))
    return "Successfully executed list-queue."
