"""``/workflows reload`` — re-read workflow definitions."""


def cmd_reload(io, coder) -> None:
    """Re-read workflow definitions and refresh the wf: agent registrations."""
    try:
        from cecli.helpers.workflows import load_workflows

        workflows = load_workflows(
            config_arg=getattr(coder, "workflows_config_arg", None),
            merged_config=getattr(coder, "workflows_merged_config", None),
            git_root=getattr(coder, "root", None),
        )
    except Exception as exc:
        io.tool_error(f"Error reloading workflows: {exc}")
        return

    from cecli.helpers.workflows.subagents import (
        get_workflow_configs,
        register_workflow_subagents,
        unregister_workflow_subagents,
    )

    # Files re-read here may not cover sources the startup load had access
    # to (inline --workflows / merged config); keep those cached configs so
    # they don't silently vanish from the registry on reload.
    previous = get_workflow_configs()
    by_name = {wf.name: wf for wf in previous}
    by_name.update({wf.name: wf for wf in workflows})
    merged = sorted(by_name.values(), key=lambda w: w.name)

    unregister_workflow_subagents(previous)
    registered = register_workflow_subagents(merged)

    # A running scheduler must learn the new definitions too (hash change
    # reseeds next_run; vanished names get disabled) - fire-and-forget.
    scheduler = getattr(coder, "scheduler", None)
    if scheduler is not None and getattr(scheduler, "db", None) is not None:
        import asyncio

        try:
            asyncio.get_running_loop().create_task(
                scheduler.db.sync_definitions({wf.name: wf for wf in merged if wf.enabled})
            )
        except RuntimeError:
            pass

    try:
        coder.workflows = merged
    except Exception:
        pass

    io.tool_output(
        f"Reloaded {len(merged)} workflow(s);"
        f" {len(registered)} agent(s) registered: {', '.join(registered) or 'none'}"
    )
