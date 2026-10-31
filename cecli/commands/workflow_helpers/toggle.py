"""``/workflows enable|disable`` — flip a workflow for this session."""

import logging

from cecli.commands.workflow_helpers.common import require, scheduler_db

logger = logging.getLogger(__name__)


async def cmd_toggle(io, coder, name, enable) -> None:
    """Flip wf.enabled for the session and (un)register the wf: agent."""
    from cecli.helpers.workflows.subagents import (
        register_workflow_subagents,
        unregister_workflow_subagents,
    )

    wf = require(io, coder, name, "enable" if enable else "disable")
    if wf is None:
        return

    wf.enabled = bool(enable)
    if enable:
        register_workflow_subagents([wf])
    else:
        unregister_workflow_subagents([wf])

    db = scheduler_db(coder)
    if db is not None:
        method = getattr(db, "enable" if enable else "disable", None)
        if method is not None:
            try:
                await (method(wf.name) if enable else method(wf.name, "disabled via /workflows"))
            except TypeError:
                try:
                    await method(wf.name)
                except Exception:
                    logger.warning("scheduler db sync failed", exc_info=True)
            except Exception:
                logger.warning("scheduler db sync failed", exc_info=True)

    state = "enabled" if enable else "disabled"
    io.tool_output(
        f"Workflow '{wf.name}' {state} for this session (files unchanged —"
        " /workflows reload re-reads them)."
    )
