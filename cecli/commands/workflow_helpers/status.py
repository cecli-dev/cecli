"""``/workflows status`` — scheduler job state, or the config view."""

from cecli.commands.workflow_helpers.common import (
    active_leases,
    find,
    job_rows,
    unknown_message,
)
from cecli.commands.workflow_helpers.list import cmd_list
from cecli.commands.workflow_helpers.show import cmd_show


async def cmd_status(io, coder, name) -> None:
    """Show scheduler job rows and active leases, or fall back to the list view."""
    if name and not find(coder, name):
        io.tool_error(unknown_message(coder, name))
        return

    jobs = await job_rows(coder, name=name or None)
    leases = await active_leases(coder, name=name or None)

    if not jobs and not leases:
        # No scheduler DB state visible — degrade to the config view.
        if name:
            cmd_show(io, coder, name)
        else:
            await cmd_list(io, coder)
            io.tool_output("(scheduler not running — showing config view)")
        return

    if jobs:
        io.print("Scheduler jobs:")
        for job_name, row in sorted(jobs.items()):
            io.print(
                f"  - {job_name}: enabled={row.get('enabled')}"
                f" engine={row.get('engine') or '-'}"
                f" next_run={row.get('next_run') or '-'}"
                f" last_run={row.get('last_run') or '-'}"
                f" ({row.get('last_status') or '-'})"
            )

    if leases:
        io.print("Active leases:")
        for lease in leases:
            io.print(
                f"  - {lease.get('name')}: slot={lease.get('slot')}"
                f" instance={lease.get('instance_id')}"
                f" expires={lease.get('lease_expires_at')}"
            )
