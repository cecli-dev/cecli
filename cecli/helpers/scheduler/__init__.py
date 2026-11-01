"""Cross-instance scheduler for workflows.

An in-session async driver ticks, decides which workflows are due, and
dispatches them, coordinating multiple concurrently-running cecli instances
through a global SQLite DB (atomic slot claims + lease timeouts) so a
scheduled job never runs twice.

Exports are resolved lazily (PEP 562) to avoid importing asyncio/sqlite
services at package-import time.
"""

from typing import Any

_EXPORTS = {
    "SchedulerService": "cecli.helpers.scheduler.service",
    "SchedulerDB": "cecli.helpers.scheduler.db",
    "JobLease": "cecli.helpers.scheduler.lock",
    "parse_schedule": "cecli.helpers.scheduler.cron",
    "next_run": "cecli.helpers.scheduler.cron",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        import importlib

        return getattr(importlib.import_module(_EXPORTS[name]), name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
