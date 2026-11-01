"""Shared lookups used by the ``/workflows`` subcommand modules."""

import logging

logger = logging.getLogger(__name__)


def workflows(coder) -> list:
    """The loaded WorkflowConfigs: coder-provided first, else the register cache."""
    loaded = getattr(coder, "workflows", None)
    if isinstance(loaded, (list, tuple)):
        return list(loaded)

    from cecli.helpers.workflows.subagents import get_workflow_configs

    return get_workflow_configs()


def find(coder, name):
    """Look up a workflow by name, ignoring a leading ``wf:`` prefix."""
    if not name:
        return None

    bare = name[3:] if name.startswith("wf:") else name
    for wf in workflows(coder):
        if wf.name == bare:
            return wf

    return None


def require(io, coder, name, sub):
    """Resolve a required workflow-name argument or emit the error."""
    if not name:
        io.tool_error(f"Usage: /workflows {sub} <name>")
        return None

    wf = find(coder, name)
    if wf is None:
        io.tool_error(unknown_message(coder, name))

    return wf


def unknown_message(coder, name):
    known = ", ".join(sorted(wf.name for wf in workflows(coder))) or "none loaded"
    return f"Error: unknown workflow '{name}'. Available: {known}"


def scheduler_db(coder):
    scheduler = getattr(coder, "scheduler", None)
    return getattr(scheduler, "db", None)


async def job_rows(coder, name=None):
    """jobs-table rows keyed by name (empty dict when no scheduler DB)."""
    db = scheduler_db(coder)
    if db is None:
        return {}

    list_jobs = getattr(db, "list_jobs", None)
    if list_jobs is None:
        return {}

    try:
        rows = await list_jobs()
    except Exception:
        logger.warning("scheduler list_jobs failed", exc_info=True)
        return {}

    jobs = {}
    for row in rows or []:
        row = dict(row)
        key = row.get("name")
        if key and (name is None or key == name):
            jobs[key] = row

    return jobs


async def active_leases(coder, name=None):
    """Currently-held leases, if the scheduler DB exposes them."""
    db = scheduler_db(coder)
    method = getattr(db, "active_leases", None) if db is not None else None
    if method is None:
        return []

    try:
        rows = await (method(name) if name else method())
    except TypeError:
        try:
            rows = await method()
        except Exception:
            logger.warning("scheduler active_leases failed", exc_info=True)
            return []
    except Exception:
        logger.warning("scheduler active_leases failed", exc_info=True)
        return []

    rows = [dict(r) for r in rows or []]
    return [r for r in rows if name is None or r.get("name") == name]


async def recent_run(coder, name):
    """The newest runs-table row for *name*, if a scheduler DB is present."""
    db = scheduler_db(coder)
    recent_runs = getattr(db, "recent_runs", None) if db is not None else None
    if recent_runs is None:
        return None

    try:
        rows = await recent_runs(name, limit=1)
    except TypeError:
        try:
            rows = await recent_runs(name)
        except Exception:
            logger.warning("scheduler recent_runs failed", exc_info=True)
            return None
    except Exception:
        logger.warning("scheduler recent_runs failed", exc_info=True)
        return None

    return dict(rows[0]) if rows else None
