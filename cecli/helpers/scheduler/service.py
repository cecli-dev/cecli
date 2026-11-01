"""In-session scheduler driver.

One ``SchedulerService`` lives on the primary coder (like ``file_watcher``). It
ticks, asks the shared :class:`~cecli.helpers.scheduler.db.SchedulerDB` which
workflow slots are due, claims them with an atomic lease (the DB is the
cross-process arbiter, so any number of concurrent cecli instances produce
exactly one run per scheduled slot), and dispatches the workflow into the
owning coder's event loop via ``execute_workflow``.

The scheduler never stores definitions: YAML is the source of truth, the DB is
only arbitration state. A workflow deleted from YAML is disabled on the next
tick (its history is kept).
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class SchedulerService:
    """Async tick loop that dispatches due workflows under DB-backed leases."""

    def __init__(
        self,
        coder: Any,
        workflow_configs: Iterable[Any],
        io: Any = None,
        *,
        tick_seconds: float = 60.0,
        db: Any = None,
        catch_up: bool = True,
        max_catchup: int = 1,
    ) -> None:
        if db is None:
            from cecli.helpers.scheduler.db import SchedulerDB

            db = SchedulerDB()

        self.coder = coder
        self.io = io
        self.workflows: Dict[str, Any] = {
            wf.name: wf for wf in workflow_configs or [] if wf.enabled
        }
        self.db = db
        self.tick_seconds = tick_seconds
        self.catch_up = catch_up
        self.max_catchup = max_catchup
        self.instance_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
        self._task: Optional[asyncio.Task] = None
        self._active: Dict[str, asyncio.Task] = {}
        self._held_leases: Dict[str, Any] = {}
        self._stopping = False

    async def start(self) -> None:
        """Initialize the DB, register ``wf:`` agents and begin ticking."""

        from cecli.helpers.workflows import register_workflow_subagents

        await self.db.initialize()
        register_workflow_subagents(self.workflows.values())
        await self.db.sync_definitions(self.workflows)
        self._task = asyncio.create_task(self._loop())
        if self.io is not None and self.workflows:
            self.io.tool_output(
                f"Scheduler started ({len(self.workflows)} scheduled workflow(s), "
                f"tick {self.tick_seconds:g}s, instance {self.instance_id})."
            )

    async def stop(self, *, release_leases: bool = True) -> None:
        """Cancel the tick and in-flight dispatches, releasing held leases."""

        from cecli.helpers.coroutines import cancel_and_abandon

        self._stopping = True

        # Snapshot the claims before cancelling: a dispatch whose task never
        # got past its first step would otherwise leave its lease unreleased.
        held = dict(getattr(self, "_held_leases", {}))

        tasks = []
        if self._task is not None:
            tasks.append(self._task)
            self._task = None

        tasks.extend(self._active.values())

        # Bounded unwind: a worker that swallows cancellation is abandoned
        # after the grace period instead of hanging the exit/reload path.
        await cancel_and_abandon(tasks)

        if release_leases:
            for name, lease in held.items():
                self._held_leases.pop(name, None)

                try:
                    await self.db.release(lease)
                except Exception:
                    logger.exception("scheduler: failed to release lease %s", lease)

        try:
            await self.db.close()
        except Exception:
            logger.debug("scheduler: db close failed", exc_info=True)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("scheduler tick failed")

            await asyncio.sleep(self.tick_seconds)

    async def _tick(self, now: Optional[datetime] = None) -> None:
        """One scheduling pass: prune vanished defs, claim and dispatch due slots."""

        now = now or datetime.now(timezone.utc)
        due = await self.db.due_definitions(now)

        for job in due:
            name = job["name"]
            wf = self.workflows.get(name)

            if wf is None:
                await self.db.disable(name, "definition removed")
                continue

            if name in self._active:
                continue

            slot = job.get("next_run")
            lease = await self.db.try_acquire(name, self.instance_id, wf.lease_timeout, slot)

            if lease is None:
                continue

            # Record the claim BEFORE the task starts: stop() may run in the
            # window between create_task and first execution, and an unreleased
            # live lease would stall the job for the whole lease_timeout.
            self._held_leases[name] = lease
            task = asyncio.create_task(self._dispatch(wf, lease, slot, now))
            self._active[name] = task
            task.add_done_callback(lambda _t, n=name: self._active.pop(n, None))

    async def _dispatch(self, wf: Any, lease: Any, slot: Any, now: datetime) -> None:
        """Run one claimed slot, then finish the lease and advance ``next_run``."""

        from cecli.helpers.scheduler.cron import next_run
        from cecli.helpers.scheduler.lock import start_lease_renewal
        from cecli.helpers.workflows import RunResult, execute_workflow

        # _tick already recorded the claim (before this task was even started);
        # re-assert for dispatches entered directly.
        held = self._held_leases
        held[wf.name] = lease
        renewal = start_lease_renewal(self.db, lease, wf.lease_timeout)

        if asyncio.iscoroutine(renewal):
            renewal = asyncio.create_task(renewal)

        try:
            result = await self._on_coder_loop(
                lambda: execute_workflow(self.coder, wf, source="scheduler")
            )
            await self.db.finish(lease, result)
            await self._log_tasks(lease, result)
        except asyncio.CancelledError:
            await self.db.finish(
                lease,
                RunResult(name=wf.name, status="aborted", source="scheduler", summary="cancelled"),
            )
            raise
        except Exception as exc:
            logger.exception("scheduler: workflow %s dispatch failed", wf.name)
            await self.db.finish(lease, RunResult.error(exc, name=wf.name))
        finally:
            _cancel_renewal(renewal)
            held.pop(wf.name, None)
            nxt = self._successor(wf, slot, now, next_run)
            await self.db.advance(wf.name, nxt)

    def _coder_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """Best-effort discovery of the loop the interactive coder runs on.

        In TUI mode the coder lives on a worker-thread loop while the scheduler
        ticks on the main (Textual) loop, so the two differ. Returns ``None``
        when the coder's loop cannot be determined (linear/one-shot sessions,
        tests), in which case callers stay on the current loop.
        """

        tui_ref = getattr(self.coder, "tui", None)

        try:
            tui = tui_ref() if callable(tui_ref) else tui_ref
        except Exception:
            tui = None

        worker = getattr(tui, "worker", None)
        loop = getattr(worker, "loop", None)

        return loop if isinstance(loop, asyncio.AbstractEventLoop) else None

    async def _on_coder_loop(self, make_coro: Any) -> Any:
        """Await ``make_coro()`` on the coder's own event loop.

        A workflow run owns coder I/O (prompts, confirmations, tool output),
        which is bound to the loop the coder actually runs on.
        """

        target = self._coder_loop()
        running = asyncio.get_running_loop()

        if target is None or target is running or target.is_closed():
            return await make_coro()

        future = asyncio.run_coroutine_threadsafe(make_coro(), target)
        return await asyncio.wrap_future(future)

    async def _log_tasks(self, lease: Any, result: Any) -> None:
        """Mirror the runner's per-task outcomes into the DB ``task_log``."""

        log_task = getattr(self.db, "log_task", None)
        run_id = getattr(lease, "run_id", None)

        if log_task is None or run_id is None:
            return

        for task in getattr(result, "tasks", None) or []:
            try:
                await log_task(
                    run_id,
                    task.index,
                    task.label or "",
                    task.status,
                    task.message or "",
                )
            except Exception:
                logger.debug("scheduler: task_log write failed", exc_info=True)

    def _successor(self, wf: Any, slot: Any, now: datetime, next_run_fn: Any) -> Optional[datetime]:
        """Cron successor of the *slot* (replay order); skip to latest if no catch-up."""

        if not wf.schedule:
            return None
        nxt = next_run_fn(wf.schedule, _as_dt(slot), timezone=getattr(wf, "timezone", "local"))

        wf_flag = getattr(wf, "catch_up", None)
        catch_up = bool(self.catch_up if wf_flag is None else wf_flag)

        if not catch_up:
            # A sleeper that woke across several windows jumps straight to the
            # next future slot instead of replaying history (bounded anyway).
            latest = next_run_fn(wf.schedule, now, timezone=getattr(wf, "timezone", "local"))

            if latest is not None and (nxt is None or latest > nxt):
                nxt = latest

        elif nxt is not None:
            # Replay overdue slots one at a time (this call advances exactly one
            # cron step). But if the backlog behind `now` is deeper than
            # max_catchup, skip straight to the next future slot so a laptop
            # asleep for a weekend doesn't queue hundreds of stale runs.
            probe = nxt
            depth = 0

            while probe is not None and probe < now and depth < self.max_catchup + 1:
                probe = next_run_fn(wf.schedule, probe, timezone=getattr(wf, "timezone", "local"))
                depth += 1

            if probe is not None and probe < now:
                nxt = next_run_fn(wf.schedule, now, timezone=getattr(wf, "timezone", "local"))

        return nxt


def _cancel_renewal(renewal: Any) -> None:
    """Cancel the lease-renewal wrapper *and* the inner loop task it returned.

    ``start_lease_renewal`` may hand back a Task whose *result* is the actual
    renewal loop task (async-def style); cancelling only the wrapper after it
    completed would leak the inner loop.
    """

    if renewal is None:
        return

    renewal.cancel()

    if isinstance(renewal, asyncio.Future) and renewal.done() and not renewal.cancelled():
        inner = getattr(renewal, "result", lambda: None)()
        cancel = getattr(inner, "cancel", None)

        if callable(cancel):
            cancel()


def _as_dt(value: Any) -> datetime:
    """Coerce an ISO string / datetime to an aware UTC datetime."""

    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    return datetime.now(timezone.utc)
