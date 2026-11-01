"""Job leases: the handle returned by a successful slot claim.

The lease itself is just data — the locking lives in SQLite
(:mod:`cecli.helpers.scheduler.db`, ``UNIQUE(name, slot, attempts)`` plus
``lease_expires_at``). This module provides the value object and the
background renewal helper a runner starts alongside a workflow run.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class JobLease:
    """Ownership of one (name, slot) claim in the scheduler DB."""

    run_id: int
    name: str
    slot: str
    instance_id: str
    lease_expires_at: str


async def start_lease_renewal(db: Any, lease: JobLease, lease_timeout_min: float) -> asyncio.Task:
    """Spawn a task renewing *lease* every ``max(5, lease_timeout/3)`` seconds.

    Renews until the caller cancels the task, or until ``db.renew`` reports the
    lease was lost (stolen) — then it logs a warning and exits quietly.
    """

    interval = max(5.0, (float(lease_timeout_min) * 60.0) / 3.0)

    async def _renew_loop() -> None:
        while True:
            await asyncio.sleep(interval)

            try:
                renewed = await db.renew(lease.run_id, lease.instance_id, lease_timeout_min)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("lease renewal failed for run %s (%s)", lease.run_id, lease.name)
                continue

            if not renewed:
                logger.warning(
                    "lease lost for run %s (%s slot %s); stopping renewal",
                    lease.run_id,
                    lease.name,
                    lease.slot,
                )

                return

    return asyncio.create_task(_renew_loop())
