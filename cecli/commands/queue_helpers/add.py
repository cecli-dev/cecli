"""Subcommand helper for ``/queue add``."""

from cecli.commands.utils.helpers import format_command_result
from cecli.helpers import command_queue


def cmd_add(io, coder, args):
    """Add a prompt to the processing queue.

    Args:
        io: InputOutput instance
        coder: Coder instance (may be None for some commands)
        args: Prompt text to queue

    Returns:
        Formatted result string
    """
    if not coder.commands:
        return format_command_result(
            io, "queue", "", error="Command system not available. Cannot queue prompts."
        )

    if not args or not args.strip():
        return format_command_result(
            io,
            "queue",
            "",
            error=(
                "Usage: /queue <prompt text> - Add a prompt to the queue "
                "for processing after current tasks complete."
            ),
        )

    prompt_text = args.strip()

    if len(prompt_text) > 10000:
        return format_command_result(
            io,
            "queue",
            "",
            error=f"Prompt exceeds maximum length of 10000 characters "
            f"(got {len(prompt_text)}).",
        )

    try:
        item = command_queue.enqueue_prompt(coder, prompt_text)
        position = command_queue.get_queue_length(coder)
        io.tool_output(f"Prompt queued at position {position} (id: {item['id']})")

        return "Successfully executed queue."
    except ValueError as e:
        return format_command_result(io, "queue", "", error=str(e))
    except RuntimeError as e:
        return format_command_result(io, "queue", "", error=str(e))
