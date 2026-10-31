"""``/workflows run`` — start a manual run in the background."""

import asyncio

from cecli.commands.workflow_helpers.common import require

# Strong refs to in-flight background ``/workflows run`` tasks (the event loop
# only weakly references tasks, so an unreferenced one can be GC'd mid-run).
_bg_runs: set = set()


async def cmd_run(io, coder, name) -> None:
    """Start a background manual run of the named workflow."""
    from cecli.helpers.workflows.runner import execute_workflow

    wf = require(io, coder, name, "run")
    if wf is None:
        return

    task = asyncio.create_task(execute_workflow(coder, wf, source="manual"))

    # The loop keeps only weak references to tasks; hold one here so a
    # background run can never be garbage-collected mid-flight, and report
    # the summary into the conversation when it finishes.
    _bg_runs.add(task)
    task.add_done_callback(lambda t: report_run(io, t, wf.name))
    io.tool_output(f"workflow '{wf.name}' started in the background")


def report_run(io, task, name) -> None:
    """Done-callback for background manual runs: release ref + announce."""
    _bg_runs.discard(task)

    try:
        result = task.result()
    except asyncio.CancelledError:
        io.tool_warning(f"workflow '{name}' run was cancelled")
        return
    except Exception as exc:
        io.tool_error(f"workflow '{name}' run failed: {exc}")
        return

    line = f"workflow '{name}' finished: {result.status}"
    summary = (result.summary or "").strip().replace("\n", " ")

    if summary:
        line += f" \u2014 {summary[:240]}"

    if result.status == "ok":
        io.tool_output(line)
    else:
        io.tool_error(line)
