"""``/workflows list`` — show every loaded workflow."""

from cecli.commands.workflow_helpers.common import job_rows, workflows


async def cmd_list(io, coder) -> None:
    """Print each loaded workflow with its schedule and (if known) last run."""
    loaded = workflows(coder)
    if not loaded:
        io.tool_output("No workflows are loaded.")
        io.tool_output(
            "Add YAML files to ~/.cecli/workflows/ or a 'workflows:' config"
            " section, then run /workflows reload."
        )
        return

    jobs = await job_rows(coder)

    io.print("Workflows:")
    for wf in sorted(loaded, key=lambda w: w.name):
        job = jobs.get(wf.name) or {}
        state = "enabled" if wf.enabled else "disabled"
        line = f"  - {wf.name} [{state}] schedule: {wf.schedule or 'manual'}"
        if job:
            line += f" | last: {job.get('last_run') or '-'}" f" ({job.get('last_status') or '-'})"
        io.print(line)
        if wf.description:
            io.print(f"    {wf.description.strip()}")
