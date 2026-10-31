"""``/workflows last`` — summarize the most recent run of a workflow."""

from cecli.commands.workflow_helpers.common import find, recent_run


async def cmd_last(io, coder, name) -> None:
    """Summarize the most recent run of a workflow (DB row, else run log)."""
    from cecli.helpers.workflows import logs

    if not name:
        io.tool_error("Usage: /workflows last <name>")
        return

    wf = find(coder, name)
    lookup = wf.name if wf else name.removeprefix("wf:")

    row = await recent_run(coder, lookup)
    if row is not None:
        io.print(f"Last run of '{lookup}' ({row.get('finished_at') or row.get('started_at')}):")
        io.print(f"  Status:  {row.get('status')}")
        io.print(f"  Source:  {row.get('source')}")
        if row.get("summary"):
            io.print(f"  Summary: {row.get('summary')}")
        return

    path = logs.latest_log_path(lookup)
    if path is None:
        io.tool_output(f"No recorded runs for '{lookup}'.")
        return

    lines = logs.read_log_lines(path)
    finish = next((ln for ln in reversed(lines) if ln.get("event") == "finish"), {})
    io.print(f"Last run of '{lookup}' (log: {path}):")
    io.print(f"  Status:  {finish.get('status', '?')}")
    io.print(f"  Source:  {finish.get('source', '?')}")
    if finish.get("summary"):
        io.print(f"  Summary: {finish.get('summary')}")
    for ln in lines:
        if ln.get("event") == "task":
            io.print(f"  task[{ln.get('idx')}] {ln.get('label')}: {ln.get('status')}")
