"""SchedulerService tick/dispatch tests (plan: tests.md cases 45-53).

Uses a stub DB and patched execute_workflow / lease helpers so no sqlite,
croniter or coder runs happen. The service contract exercised here matches
cecli/helpers/scheduler/service.py.
"""

import asyncio
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cecli.helpers.scheduler.service import SchedulerService
from cecli.helpers.workflows.models import RunResult, TaskConfig, WorkflowConfig

STEP = timedelta(minutes=15)
BASE = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def make_wf(name="job", schedule="*/15 * * * *", **kw):
    return WorkflowConfig(name=name, tasks=[TaskConfig(prompt="do it")], schedule=schedule, **kw)


def make_lease(name="job", slot=None):
    slot = slot or BASE

    return SimpleNamespace(
        run_id=1,
        name=name,
        slot=slot,
        instance_id="stub",
        lease_expires_at=slot + timedelta(minutes=30),
    )


class StubDB:
    """In-memory stand-in for SchedulerDB matching the service's call contract."""

    def __init__(self):
        self.calls = []
        self.due = []
        self.acquire_returns_lease = True

    async def initialize(self):
        self.calls.append(("initialize",))

    async def sync_definitions(self, workflows):
        self.calls.append(("sync", tuple(workflows)))

    async def due_definitions(self, now):
        return list(self.due)

    async def try_acquire(
        self, name, instance_id, lease_timeout, slot, source="scheduler", attempts=1
    ):
        self.calls.append(("acquire", name))

        if not self.acquire_returns_lease:
            return None

        return make_lease(name, slot)

    async def renew(self, run_id, instance_id, lease_timeout):
        self.calls.append(("renew", run_id))

        return 1

    async def finish(self, lease, result):
        run_id = getattr(lease, "run_id", lease)
        status = getattr(result, "status", result)
        self.calls.append(("finish", run_id, status))

    async def advance(self, name, nxt):
        self.calls.append(("advance", name, nxt))

    async def disable(self, name, reason):
        self.calls.append(("disable", name, reason))

    async def release(self, lease):
        self.calls.append(("release", getattr(lease, "run_id", lease)))

    async def close(self):
        self.calls.append(("close",))


class RecordingRenewal:
    """Stand-in for the renewal task: records start + cancel."""

    instances = []

    def __init__(self, *args, **kwargs):
        self.cancelled = False
        RecordingRenewal.instances.append(self)

    def cancel(self):
        self.cancelled = True


async def _drain(service):
    while service._active:
        await asyncio.gather(*list(service._active.values()), return_exceptions=True)

        for name in [n for n, t in service._active.items() if t.done()]:
            service._active.pop(name, None)


def _service(workflows, db=None, **kw):
    coder = MagicMock()
    coder.uuid = "primary-uuid"
    service = SchedulerService(coder, [], db=db or StubDB(), **kw)
    service.workflows = {wf.name: wf for wf in workflows}

    return service


@pytest.fixture(autouse=True)
def _fresh_renewal_log():
    RecordingRenewal.instances = []


@pytest.fixture
def patched_dispatch():
    """Patch the three lazily-imported collaborators of _dispatch."""

    def fake_next(expr, after, timezone=None):
        return after + STEP

    with (
        patch(
            "cecli.helpers.workflows.runner.execute_workflow",
            new=AsyncMock(
                return_value=RunResult(name="job", status="ok", source="scheduler", summary="done")
            ),
        ) as mock_exec,
        patch("cecli.helpers.scheduler.cron.next_run", new=fake_next),
        patch("cecli.helpers.scheduler.lock.start_lease_renewal", new=RecordingRenewal),
    ):
        yield mock_exec


class TestTick:
    @pytest.mark.asyncio
    async def test_due_unowned_job_dispatches_once(self, patched_dispatch):
        db = StubDB()
        db.due = [{"name": "job", "next_run": BASE}]
        service = _service([make_wf()], db=db)

        await service._tick(now=BASE)
        await _drain(service)

        assert ("acquire", "job") in db.calls
        assert patched_dispatch.await_count == 1
        assert ("finish", 1, "ok") in db.calls
        advances = [c for c in db.calls if c[0] == "advance"]
        assert advances and advances[0][2] > BASE

    @pytest.mark.asyncio
    async def test_job_owned_elsewhere_is_not_dispatched(self, patched_dispatch):
        db = StubDB()
        db.acquire_returns_lease = False
        db.due = [{"name": "job", "next_run": BASE}]
        service = _service([make_wf()], db=db)

        await service._tick(now=BASE)
        await _drain(service)

        assert patched_dispatch.await_count == 0
        assert not any(c[0] in ("finish", "advance") for c in db.calls)

    @pytest.mark.asyncio
    async def test_active_job_not_respawned_while_running(self, patched_dispatch):
        db = StubDB()
        db.due = [{"name": "job", "next_run": BASE}]
        service = _service([make_wf()], db=db)
        gate = asyncio.Event()
        patched_dispatch.side_effect = lambda *a, **k: gate.wait()
        service._active["job"] = asyncio.create_task(asyncio.sleep(30))

        await service._tick(now=BASE)
        assert ("acquire", "job") not in db.calls

        service._active["job"].cancel()
        await _drain(service)

    @pytest.mark.asyncio
    async def test_vanished_definition_is_disabled_not_dispatched(self, patched_dispatch):
        db = StubDB()
        db.due = [{"name": "ghost", "next_run": BASE}]
        service = _service([], db=db)

        await service._tick(now=BASE)
        await _drain(service)

        assert ("disable", "ghost", "definition removed") in db.calls
        assert patched_dispatch.await_count == 0

    @pytest.mark.asyncio
    async def test_dispatch_exception_finishes_error_and_advances(self, patched_dispatch):
        patched_dispatch.side_effect = RuntimeError("boom")
        db = StubDB()
        db.due = [{"name": "job", "next_run": BASE}]
        service = _service([make_wf()], db=db)

        await service._tick(now=BASE)
        await _drain(service)

        assert ("finish", 1, "error") in db.calls
        assert any(c[0] == "advance" for c in db.calls)

    @pytest.mark.asyncio
    async def test_renewal_task_started_and_cancelled(self, patched_dispatch):
        db = StubDB()
        db.due = [{"name": "job", "next_run": BASE}]
        service = _service([make_wf()], db=db)

        await service._tick(now=BASE)
        await _drain(service)

        assert len(RecordingRenewal.instances) == 1
        assert RecordingRenewal.instances[0].cancelled


class TestCatchUp:
    @pytest.mark.asyncio
    async def test_no_catchup_skips_to_latest(self, patched_dispatch):
        db = StubDB()
        late = BASE - 5 * STEP
        db.due = [{"name": "job", "next_run": late}]
        service = _service([make_wf()], db=db, catch_up=False)

        await service._tick(now=BASE)
        await _drain(service)

        nxt = [c for c in db.calls if c[0] == "advance"][0][2]
        assert nxt > BASE

    @pytest.mark.asyncio
    async def test_catchup_replays_one_slot(self, patched_dispatch):
        db = StubDB()
        late = BASE - 5 * STEP
        db.due = [{"name": "job", "next_run": late}]
        service = _service([make_wf()], db=db, catch_up=True, max_catchup=5)

        await service._tick(now=BASE)
        await _drain(service)

        nxt = [c for c in db.calls if c[0] == "advance"][0][2]
        assert nxt == late + STEP

    @pytest.mark.asyncio
    async def test_default_catches_up_without_any_flags(self, patched_dispatch):
        db = StubDB()
        late = BASE - 2 * STEP
        db.due = [{"name": "job", "next_run": late}]
        service = _service([make_wf()], db=db)

        await service._tick(now=BASE)
        await _drain(service)

        nxt = [c for c in db.calls if c[0] == "advance"][0][2]
        assert nxt == late + STEP

    @pytest.mark.asyncio
    async def test_workflow_catch_up_false_overrides_scheduler_default(self, patched_dispatch):
        db = StubDB()
        late = BASE - 5 * STEP
        db.due = [{"name": "job", "next_run": late}]
        service = _service([make_wf(catch_up=False)], db=db)

        await service._tick(now=BASE)
        await _drain(service)

        nxt = [c for c in db.calls if c[0] == "advance"][0][2]
        assert nxt > BASE

    @pytest.mark.asyncio
    async def test_catchup_backlog_beyond_cap_skips(self, patched_dispatch):
        db = StubDB()
        late = BASE - 10 * STEP
        db.due = [{"name": "job", "next_run": late}]
        service = _service([make_wf()], db=db, catch_up=True, max_catchup=3)

        await service._tick(now=BASE)
        await _drain(service)

        nxt = [c for c in db.calls if c[0] == "advance"][0][2]
        assert nxt > BASE


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_cancels_dispatch_and_releases_lease(self):
        db = StubDB()
        gate = asyncio.Event()
        service = _service([make_wf()], db=db)

        async def hang(*args, **kwargs):
            await gate.wait()
            return RunResult(name="job", status="ok")

        def fake_next(expr, after, timezone=None):
            return after + STEP

        with (
            patch("cecli.helpers.workflows.runner.execute_workflow", new=hang),
            patch("cecli.helpers.scheduler.cron.next_run", new=fake_next),
            patch("cecli.helpers.scheduler.lock.start_lease_renewal", new=RecordingRenewal),
        ):
            db.due = [{"name": "job", "next_run": BASE}]
            await service._tick(now=BASE)
            await asyncio.sleep(0)
            await service.stop()

        assert ("release", 1) in db.calls
        assert ("close",) in db.calls
        assert any(c[0] == "finish" and c[2] == "aborted" for c in db.calls)
        assert not service._active
        assert RecordingRenewal.instances[0].cancelled

    @pytest.mark.asyncio
    async def test_stop_before_dispatch_starts_releases_lease(self):
        """Regression: a tick claim whose task never got scheduled must not
        leak a live lease (would stall the job for the whole lease_timeout)."""

        db = StubDB()
        service = _service([make_wf()], db=db)

        async def hang(*args, **kwargs):
            await asyncio.Event().wait()
            return RunResult(name="job", status="ok")

        def fake_next(expr, after, timezone=None):
            return after + STEP

        with (
            patch("cecli.helpers.workflows.runner.execute_workflow", new=hang),
            patch("cecli.helpers.scheduler.cron.next_run", new=fake_next),
            patch("cecli.helpers.scheduler.lock.start_lease_renewal", new=RecordingRenewal),
        ):
            db.due = [{"name": "job", "next_run": BASE}]
            await service._tick(now=BASE)

            # No awaits in between: the dispatch task has not started yet.
            await service.stop()

        assert ("release", 1) in db.calls
        assert not any(c[0] == "advance" for c in db.calls)
        assert not service._active
        assert not service._held_leases

    @pytest.mark.asyncio
    async def test_stop_abandons_dispatch_that_ignores_cancellation(self):
        """Regression: stop() must not hang behind a task that swallows cancel
        (the pre-cancel_and_abandon gather awaited it unboundedly)."""
        import contextlib
        import functools

        import cecli.helpers.coroutines as coroutines

        db = StubDB()
        service = _service([make_wf()], db=db)

        async def stubborn():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await asyncio.sleep(30)

        task = asyncio.create_task(stubborn())
        service._held_leases["job"] = make_lease()
        service._active["job"] = task

        await asyncio.sleep(0)

        with patch(
            "cecli.helpers.coroutines.cancel_and_abandon",
            new=functools.partial(coroutines.cancel_and_abandon, grace=0.05),
        ):
            await asyncio.wait_for(service.stop(), timeout=2)

        assert ("release", 1) in db.calls

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


class TestCoderLoopBridge:
    """Scheduled runs must execute on the coder's own (worker) event loop."""

    def test_coder_loop_is_none_without_tui(self):
        """A coder with no resolvable worker loop (linear/test) bridges to the current loop."""
        service = _service([make_wf()])

        assert service._coder_loop() is None

    @pytest.mark.asyncio
    async def test_on_coder_loop_awaits_directly_without_tui(self):
        service = _service([make_wf()])
        seen = []

        async def make_coro():
            seen.append(asyncio.get_running_loop())
            return "ok"

        result = await asyncio.wait_for(service._on_coder_loop(make_coro), timeout=5)

        assert result == "ok"
        assert seen == [asyncio.get_running_loop()]

    @pytest.mark.asyncio
    async def test_on_coder_loop_bridges_to_worker_loop(self):
        """A scheduled dispatch must be awaited on the coder's worker-thread loop."""
        service = _service([make_wf()])
        foreign = asyncio.new_event_loop()
        started = threading.Event()

        def run_foreign():
            asyncio.set_event_loop(foreign)
            foreign.call_soon(started.set)
            foreign.run_forever()

        thread = threading.Thread(target=run_foreign, daemon=True)
        thread.start()

        try:
            assert started.wait(timeout=5)
            service.coder.tui = lambda: SimpleNamespace(worker=SimpleNamespace(loop=foreign))

            assert service._coder_loop() is foreign

            seen = []

            async def make_coro():
                seen.append(asyncio.get_running_loop())
                return "bridged"

            result = await asyncio.wait_for(service._on_coder_loop(make_coro), timeout=5)

            assert result == "bridged"
            assert seen == [foreign]
        finally:
            foreign.call_soon_threadsafe(foreign.stop)
            thread.join(timeout=5)
            foreign.close()
