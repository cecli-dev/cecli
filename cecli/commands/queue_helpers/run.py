"""Subcommand helper for ``/queue run``."""

import asyncio

from cecli.commands.utils.helpers import format_command_result
from cecli.helpers import command_queue
from cecli.signals import SwitchCoderSignal


async def cmd_run(io, coder, args):
    """Process queued prompts in order."""
    if not coder.commands:
        return format_command_result(
            io, "run-queue", "", error="Command system not available. Cannot run queue."
        )

    target = command_queue.get_active_coder(coder)

    if command_queue.get_queue_length(target) == 0:
        io.tool_output("Queue is empty. Use /queue <prompt> to add prompts first.")
        return "Successfully executed run-queue."

    try:
        await target.process_prompt_queue()
        return "Successfully executed run-queue."
    except (KeyboardInterrupt, asyncio.CancelledError):
        io.tool_output("Queue processing paused. Use /queue run to resume.")
        return "Successfully executed run-queue."
    except (SwitchCoderSignal, SystemExit):
        raise
    except Exception as e:
        return format_command_result(io, "run-queue", "", error=str(e))
