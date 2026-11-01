"""SchedulerDB tests (tests.md cases 30-39).

Every test points the DB at ``tmp_path`` so the global ``~/.cecli`` store is
never touched.  Expired leases are produced with a *negative* lease timeout
(``EXPIRED``) rather than by sleeping, which keeps the suite fast and
deterministic.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pytest

from cecli.helpers.scheduler.db import SchedulerDB, get_db_path
from cecli.helpers.scheduler.lock import JobLease
from cecli.helpers.workflows.models import TaskConfig, WorkflowConfig

# A slot string is just an opaque (name, slot) key; ISO-UTC keeps it comparable.
SLOT = "2026-01-01T00:00:00.000Z"
SLOT2 = "2026-01-01T00:30:00.000Z"
FUTURE = "2999-01-01T00:00:00.000Z"

# Acquiring with a negative lease timeout yields a row whose lease_expires_at is
# already in the past -- i.e. a crashed owner, without waiting for a real timeout.
EXPIRED = -0.05


def db_path_for(tmp_path):
    return tmp_path / "scheduler.v1" / "scheduler.db"


def make_wf(name="job", schedule="*/30 * * * *", **kwargs) -> WorkflowConfig:
    kwargs.setdefault("tasks", [TaskConfig(prompt="do the thing")])
    return WorkflowConfig(name=name, schedule=schedule, **kwargs)


async def make_db(tmp_path, **fields) -> SchedulerDB:
    """An initialized SchedulerDB with one job row seeded from *fields*."""

    db = SchedulerDB(db_path_for(tmp_path))
    await db.initialize()

    if fields:
        await db.upsert_definition(fields.pop("name", "job"), definition_hash="h1", **fields)

    return db


def rows(db: SchedulerDB, name: str | None = None) -> list[dict]:
    return db._recent_runs(name)


async def run_row(db: SchedulerDB, run_id: int) -> dict:
    return next(r for r in await db.recent_runs() if r["run_id"] == run_id)


class TestInitialize:
    """Case 30."""

    async def test_creates_schema_and_is_idempotent(self, tmp_path):
        db = await make_db(tmp_path)
        conn = sqlite3.connect(str(db_path_for(tmp_path)))

        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"jobs", "runs", "task_log"} <= tables
        assert db.db_path == db_path_for(tmp_path)
        assert get_db_path().name == "scheduler.db"

        await db.upsert_definition(
            "job", definition_hash="h1", schedule="*/30 * * * *", next_run_value=SLOT
        )
        await db.initialize()  # second call is a no-op
        assert (await db.get_job("job"))["definition_hash"] == "h1"

    async def test_wal_and_busy_timeout_pragmas(self, tmp_path):
        db = await make_db(tmp_path)
        conn = db._get_connection()

        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 10000

    async def test_crash_recovery_aborts_expired_running_rows(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)
        stale = await db.try_acquire("job", "host:1:dead", EXPIRED, SLOT)

        await db.initialize()

        recovered = await run_row(db, stale.run_id)
        assert recovered["status"] == "aborted"
        assert recovered["finished_at"] is not None
        assert "lease expired" in recovered["summary"]

    async def test_crash_recovery_leaves_live_rows_alone(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)
        held = await db.try_acquire("job", "host:1:live", 30, SLOT)

        await db.initialize()

        assert (await run_row(db, held.run_id))["status"] == "running"


class TestAcquire:
    """Cases 31, 33, 34."""

    async def test_free_slot_returns_lease(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)

        lease = await db.try_acquire("job", "host:1:aaaa", 30, SLOT)

        assert isinstance(lease, JobLease)
        assert (lease.name, lease.slot, lease.instance_id) == ("job", SLOT, "host:1:aaaa")
        assert lease.run_id > 0 and lease.lease_expires_at > db._now_iso()
        stored = await run_row(db, lease.run_id)
        assert stored["status"] == "running" and stored["attempts"] == 1
        assert stored["source"] == "scheduler"

    async def test_manual_source_is_recorded(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)

        lease = await db.try_acquire("job", "host:1:m", 30, SLOT, source="manual")

        assert (await run_row(db, lease.run_id))["source"] == "manual"

    async def test_second_acquire_of_live_slot_loses(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)
        winner = await db.try_acquire("job", "A", 30, SLOT)

        assert await db.try_acquire("job", "B", 30, SLOT) is None
        assert len(rows(db, "job")) == 1  # loser leaves no claim row behind
        assert (await run_row(db, winner.run_id))["instance_id"] == "A"

    async def test_steal_expired_lease_bumps_attempts(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)
        stale = await db.try_acquire("job", "A", EXPIRED, SLOT)

        stolen = await db.try_acquire("job", "B", 30, SLOT)

        assert stolen is not None and stolen.run_id != stale.run_id
        assert stolen.instance_id == "B"
        new_row = await run_row(db, stolen.run_id)
        assert (new_row["attempts"], new_row["status"]) == (2, "running")
        assert new_row["lease_expires_at"] > db._now_iso()
        assert (await run_row(db, stale.run_id))["attempts"] == 1  # history retained

    async def test_steal_after_release_or_abort_succeeds(self, tmp_path):
        """Crash recovery / reload leaves 'aborted' rows: the slot must not stall."""

        db = await make_db(tmp_path, next_run_value=SLOT)
        held = await db.try_acquire("job", "A", 30, SLOT)

        assert await db.release(held) == 1
        assert (await run_row(db, held.run_id))["status"] == "aborted"

        stolen = await db.try_acquire("job", "B", 30, SLOT)

        assert stolen is not None
        assert (await run_row(db, stolen.run_id))["attempts"] == 2

    async def test_third_attempt_after_two_steals(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)
        first = await db.try_acquire("job", "A", EXPIRED, SLOT)
        second = await db.try_acquire("job", "B", EXPIRED, SLOT)

        third = await db.try_acquire("job", "C", 30, SLOT)

        assert (await run_row(db, first.run_id))["attempts"] == 1
        assert (await run_row(db, second.run_id))["attempts"] == 2
        assert (await run_row(db, third.run_id))["attempts"] == 3
        assert len(rows(db, "job")) == 3

    async def test_acquire_requires_a_job_row(self, tmp_path):
        """runs.name is an FK: a claim for an unsynced job must fail loudly."""

        db = await make_db(tmp_path)

        with pytest.raises(sqlite3.IntegrityError):
            await db.try_acquire("orphan", "A", 30, SLOT)


class TestThreadRace:
    """Case 32."""

    async def test_twelve_threads_one_winner(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)
        barrier = threading.Barrier(12)
        won: list[int] = []
        lost = 0
        errors: list[BaseException] = []
        lock = threading.Lock()

        def claim(idx: int) -> None:
            nonlocal lost

            try:
                barrier.wait(timeout=10)
                lease = db._try_acquire("job", f"host:race:{idx}", 30, SLOT)

                with lock:
                    if lease is not None:
                        won.append(lease.run_id)
                    else:
                        lost += 1
            except BaseException as exc:  # 'database is locked' must not leak
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=claim, args=(i,)) for i in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert not errors
        assert len(won) == 1, f"expected exactly one winner, got {won}"
        assert lost == 11
        assert len(rows(db, "job")) == 1
        assert rows(db, "job")[0]["attempts"] == 1


class TestRenew:
    """Case 35."""

    async def test_owner_renew_extends_lease(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)
        lease = await db.try_acquire("job", "A", 30, SLOT)
        before = (await run_row(db, lease.run_id))["lease_expires_at"]

        assert await db.renew(lease.run_id, "A", 60) == 1

        after = (await run_row(db, lease.run_id))["lease_expires_at"]
        assert after > before
        assert after > db._iso(datetime.now(timezone.utc) + timedelta(minutes=59))

    async def test_renew_after_steal(self, tmp_path):
        """A steal inserts a new attempt row; the abandoned row is only pruned later.

        ``lock.start_lease_renewal`` treats ``renew() == 0`` as "lease lost", so the
        loser learns it only once ``advance``/``initialize`` flips its stale row to
        ``aborted`` -- assert that boundary explicitly.
        """

        db = await make_db(tmp_path, next_run_value=SLOT)
        stale = await db.try_acquire("job", "A", EXPIRED, SLOT)
        stolen = await db.try_acquire("job", "B", 30, SLOT)

        assert (await run_row(db, stale.run_id))["status"] == "running"

        await db.advance("job", FUTURE)  # prunes the expired attempt

        assert (await run_row(db, stale.run_id))["status"] == "aborted"
        assert await db.renew(stale.run_id, "A", 30) == 0
        assert await db.renew(stolen.run_id, "B", 30) == 1

    async def test_renew_wrong_instance_returns_zero(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)
        lease = await db.try_acquire("job", "A", 30, SLOT)

        assert await db.renew(lease.run_id, "B", 30) == 0
        assert (await run_row(db, lease.run_id))["instance_id"] == "A"

    async def test_renew_finished_run_returns_zero(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)
        lease = await db.try_acquire("job", "A", 30, SLOT)
        await db.finish(lease, None)

        assert await db.renew(lease.run_id, "A", 30) == 0


class TestFinishReleaseAdvance:
    """Case 36 + lease bookkeeping."""

    async def test_finish_writes_run_and_job_columns(self, tmp_path):
        from cecli.helpers.workflows.models import RunResult

        db = await make_db(tmp_path, next_run_value=SLOT)
        lease = await db.try_acquire("job", "A", 30, SLOT)

        await db.finish(lease, RunResult(name="job", status="ok", summary="all done"))

        run = await run_row(db, lease.run_id)
        job = await db.get_job("job")
        assert run["status"] == "ok" and run["summary"] == "all done"
        assert run["finished_at"] is not None and run["lease_expires_at"] == run["finished_at"]
        assert job["last_status"] == "ok" and job["last_run"] == run["finished_at"]

    async def test_finish_error_result_keeps_message(self, tmp_path):
        from cecli.helpers.workflows.models import RunResult

        db = await make_db(tmp_path, next_run_value=SLOT)
        lease = await db.try_acquire("job", "A", 30, SLOT)

        await db.finish(lease, RunResult.error(RuntimeError("kaboom"), name="job"))

        run = await run_row(db, lease.run_id)
        assert run["status"] == "error" and "kaboom" in run["summary"]
        assert (await db.get_job("job"))["last_status"] == "error"

    async def test_finish_accepts_bare_run_id(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)
        lease = await db.try_acquire("job", "A", 30, SLOT)

        await db.finish(lease.run_id, None, status="aborted", summary="cancelled")

        run = await run_row(db, lease.run_id)
        assert (run["status"], run["summary"]) == ("aborted", "cancelled")
        assert (await db.get_job("job"))["last_status"] == "aborted"

    async def test_finish_ok_with_error_message_flips_to_error(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)
        lease = await db.try_acquire("job", "A", 30, SLOT)

        await db.finish(lease, None, status="ok", error_message="hook aborted")

        assert (await run_row(db, lease.run_id))["status"] == "error"

    async def test_finish_truncates_long_summary(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)
        lease = await db.try_acquire("job", "A", 30, SLOT)

        await db.finish(lease, None, summary="x" * 9_000)

        assert len((await run_row(db, lease.run_id))["summary"]) == 4000

    async def test_release_aborts_and_frees_the_slot(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)
        lease = await db.try_acquire("job", "A", 30, SLOT)

        assert await db.release(lease) == 1
        assert (await run_row(db, lease.run_id))["status"] == "aborted"
        assert await db.release(lease) == 0  # already released
        assert await db.try_acquire("job", "B", 30, SLOT) is not None

    async def test_release_ignores_foreign_lease(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)
        lease = await db.try_acquire("job", "A", 30, SLOT)

        assert await db.release(lease, "B") == 0
        assert (await run_row(db, lease.run_id))["status"] == "running"

    async def test_advance_accepts_datetime_iso_none(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)
        when = datetime(2026, 5, 1, 12, 30, tzinfo=timezone.utc)

        await db.advance("job", when)
        assert (await db.get_job("job"))["next_run"] == "2026-05-01T12:30:00.000Z"

        await db.advance("job", "2026-05-01T13:00:00.000Z")
        assert (await db.get_job("job"))["next_run"] == "2026-05-01T13:00:00.000Z"

        await db.advance("job", None)
        assert (await db.get_job("job"))["next_run"] is None

    async def test_advance_prunes_expired_running_rows(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)
        stale = await db.try_acquire("job", "A", EXPIRED, SLOT)

        await db.advance("job", FUTURE)

        assert (await run_row(db, stale.run_id))["status"] == "aborted"
        assert (await db.get_job("job"))["next_run"] == FUTURE

    async def test_advance_keeps_live_running_row(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)
        lease = await db.try_acquire("job", "A", 30, SLOT)

        await db.advance("job", FUTURE)

        assert (await run_row(db, lease.run_id))["status"] == "running"


class TestDueDefinitions:
    """Case 37."""

    async def test_only_enabled_past_slots_are_due(self, tmp_path):
        db = await make_db(tmp_path)
        await db.upsert_definition("past", definition_hash="h", next_run_value=SLOT)
        await db.upsert_definition("future", definition_hash="h", next_run_value=FUTURE)
        await db.upsert_definition("manual", definition_hash="h", next_run_value=None)
        await db.upsert_definition("off", definition_hash="h", next_run_value=SLOT, enabled=False)

        due = await db.due_definitions(datetime(2026, 6, 1, tzinfo=timezone.utc))

        assert [job["name"] for job in due] == ["past"]
        assert due[0]["next_run"] == SLOT

    async def test_exactly_now_is_due(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)

        assert await db.due_definitions(datetime(2026, 1, 1, tzinfo=timezone.utc))

    async def test_owned_slot_is_not_due(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)
        await db.try_acquire("job", "A", 30, SLOT)

        assert await db.due_definitions() == []

    async def test_slot_of_a_different_name_is_not_blocked(self, tmp_path):
        db = await make_db(tmp_path)
        await db.upsert_definition("job", definition_hash="h", next_run_value=SLOT)
        await db.upsert_definition("other", definition_hash="h", next_run_value=SLOT)
        await db.try_acquire("other", "A", 30, SLOT)

        assert [j["name"] for j in await db.due_definitions()] == ["job"]

    async def test_expired_lease_makes_the_slot_due_again(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)
        await db.try_acquire("job", "A", EXPIRED, SLOT)

        assert [j["name"] for j in await db.due_definitions()] == ["job"]

    async def test_due_ordering_is_by_next_run(self, tmp_path):
        db = await make_db(tmp_path)

        await db.upsert_definition("later", definition_hash="h", next_run_value=SLOT2)
        await db.upsert_definition("sooner", definition_hash="h", next_run_value=SLOT)

        assert [j["name"] for j in await db.due_definitions()] == ["sooner", "later"]


class TestSyncDefinitions:
    """Case 38."""

    async def test_upserts_new_definitions_with_seeded_next_run(self, tmp_path):
        db = await make_db(tmp_path)
        now = datetime(2026, 1, 1, 0, 7, tzinfo=timezone.utc)

        await db.sync_definitions({"job": make_wf()}, now=now)

        job = await db.get_job("job")
        assert job["engine"] == "cron" and job["schedule"] == "*/30 * * * *"
        assert job["next_run"] == "2026-01-01T00:30:00.000Z"
        assert job["enabled"] == 1 and job["lease_timeout"] == 30.0
        assert len(job["definition_hash"]) == 64

    async def test_manual_definition_has_no_next_run(self, tmp_path):
        db = await make_db(tmp_path)

        await db.sync_definitions({"quiet": make_wf(schedule=None)}, now=datetime.now(timezone.utc))

        job = await db.get_job("quiet")
        assert job["engine"] == "manual" and job["next_run"] is None
        assert await db.due_definitions() == []

    async def test_disabled_definition_is_not_due(self, tmp_path):
        db = await make_db(tmp_path)

        await db.sync_definitions({"job": make_wf(enabled=False)})

        assert (await db.get_job("job"))["enabled"] == 0
        assert await db.due_definitions() == []

    async def test_changed_hash_recomputes_next_run(self, tmp_path):
        db = await make_db(tmp_path)
        old = make_wf()
        await db.sync_definitions({"job": old}, now=datetime(2026, 1, 1, 0, 7, tzinfo=timezone.utc))
        await db.advance("job", SLOT)

        await db.sync_definitions(
            {"job": make_wf(schedule="0 * * * *")},
            now=datetime(2026, 1, 1, 0, 7, tzinfo=timezone.utc),
        )

        job = await db.get_job("job")
        assert job["definition_hash"] != old.definition_hash()
        assert job["next_run"] == "2026-01-01T01:00:00.000Z"

    async def test_unchanged_hash_keeps_next_run_and_history(self, tmp_path):
        db = await make_db(tmp_path)
        wf = make_wf()
        await db.sync_definitions({"job": wf}, now=datetime(2026, 1, 1, 0, 7, tzinfo=timezone.utc))
        # advance is monotonic, so set the marker to a successor-like value
        # (later than the seeded 00:30) exactly as the scheduler would.
        await db.advance("job", "2026-01-01T04:00:00.000Z")

        await db.sync_definitions({"job": wf}, now=datetime(2026, 6, 1, tzinfo=timezone.utc))

        assert (await db.get_job("job"))["next_run"] == "2026-01-01T04:00:00.000Z"

    async def test_vanished_definition_disabled_not_deleted(self, tmp_path):
        db = await make_db(tmp_path)
        await db.sync_definitions({"gone": make_wf(name="gone")})
        held = await db.try_acquire("gone", "A", 30, SLOT)
        await db.finish(held, None)

        await db.sync_definitions({})

        job = await db.get_job("gone")
        assert (job["enabled"], job["next_run"]) == (0, None)
        assert job["last_status"] == "ok"  # history kept

    async def test_enable_rearms_next_run_after_disable(self, tmp_path):
        """A disable/enable round-trip must re-seed next_run from cron(now).

        Without this the job stays permanently dead: disable NULLs next_run,
        sync keeps a stored next_run whenever the hash is unchanged (it is),
        and only a definition edit would ever re-arm it.
        """
        db = await make_db(tmp_path)
        await db.sync_definitions({"job": make_wf()})

        await db.disable("job", "test")
        job = await db.get_job("job")
        assert (job["enabled"], job["next_run"]) == (0, None)

        assert await db.enable("job") == 1
        job = await db.get_job("job")
        assert job["enabled"] == 1
        assert job["next_run"] is not None
        seeded = datetime.fromisoformat(job["next_run"].replace("Z", "+00:00"))
        assert seeded > datetime.now(timezone.utc)

    async def test_enable_manual_job_and_unknown_name(self, tmp_path):
        db = await make_db(tmp_path)
        await db.sync_definitions({"job": make_wf(schedule=None)})

        await db.disable("job")
        assert await db.enable("job") == 1
        assert (await db.get_job("job"))["next_run"] is None

        assert await db.enable("nope") == 0

    async def test_bad_schedule_falls_back_to_manual(self, tmp_path):
        db = await make_db(tmp_path)

        await db.sync_definitions({"job": make_wf(schedule="not a cron")})

        job = await db.get_job("job")
        assert job["engine"] == "manual" and job["next_run"] is None


class TestViewsAndClose:
    """get_job / list_jobs / recent_runs / log_task / close."""

    async def test_get_job_missing_is_none(self, tmp_path):
        db = await make_db(tmp_path)

        assert await db.get_job("nope") is None

    async def test_list_jobs_orders_and_filters(self, tmp_path):
        db = await make_db(tmp_path)
        await db.upsert_definition("b", definition_hash="h")
        await db.upsert_definition("a", definition_hash="h")
        await db.upsert_definition("c", definition_hash="h", enabled=False)

        assert [j["name"] for j in await db.list_jobs()] == ["a", "b", "c"]
        assert [j["name"] for j in await db.list_jobs(enabled_only=True)] == ["a", "b"]

    async def test_recent_runs_limits_and_filters(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)
        await db.upsert_definition("other", definition_hash="h", next_run_value=SLOT)
        for idx in range(3):
            await db.try_acquire("job", f"i{idx}", EXPIRED, SLOT)
        await db.try_acquire("other", "x", EXPIRED, SLOT)

        mine = await db.recent_runs("job")
        assert [r["attempts"] for r in mine] == [3, 2, 1]
        assert len(await db.recent_runs("job", limit=2)) == 2
        assert {r["name"] for r in await db.recent_runs()} == {"job", "other"}

    async def test_log_task_records_and_upserts(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)
        lease = await db.try_acquire("job", "A", 30, SLOT)

        await db.log_task(lease.run_id, 0, "attach-gitlab", "ok", "done")
        await db.log_task(lease.run_id, 1, "summarize", "error", "boom")
        await db.log_task(lease.run_id, 0, "attach-gitlab", "skipped", "retry")

        conn = sqlite3.connect(str(db_path_for(tmp_path)))
        got = conn.execute(
            "SELECT idx, label, status, message FROM task_log ORDER BY idx"
        ).fetchall()
        assert got == [(0, "attach-gitlab", "skipped", "retry"), (1, "summarize", "error", "boom")]
        conn.close()

    async def test_close_then_reopen_keeps_state(self, tmp_path):
        db = await make_db(tmp_path, next_run_value=SLOT)
        await db.close()

        again = await make_db(tmp_path)

        assert (await again.get_job("job"))["definition_hash"] == "h1"
        await again.close()


class TestMultiConnection:
    """Case 39: two real connections against one WAL file."""

    async def test_two_connections_one_winner(self, tmp_path):
        path = db_path_for(tmp_path)
        first = SchedulerDB(path)
        await first.initialize()
        await first.upsert_definition("job", definition_hash="h1", next_run_value=SLOT)
        second = SchedulerDB(path)
        await second.initialize()

        assert await first.try_acquire("job", "A", 30, SLOT) is not None
        assert await second.try_acquire("job", "B", 30, SLOT) is None
        assert second._recent_runs("job") == first._recent_runs("job")

        await first.close()
        await second.close()

    async def test_cross_connection_steal_of_expired_lease(self, tmp_path):
        path = db_path_for(tmp_path)
        first = SchedulerDB(path)
        await first.initialize()
        await first.upsert_definition("job", definition_hash="h1", next_run_value=SLOT)
        second = SchedulerDB(path)
        await second.initialize()

        stale = await first.try_acquire("job", "A", EXPIRED, SLOT)
        stolen = await second.try_acquire("job", "B", 30, SLOT)

        assert stolen is not None and stolen.run_id != stale.run_id
        assert [
            (r["run_id"], r["attempts"], r["instance_id"]) for r in second._recent_runs("job")
        ] == [
            (stolen.run_id, 2, "B"),
            (stale.run_id, 1, "A"),
        ]
        assert await second.renew(stolen.run_id, "B", 30) == 1
        assert await first.try_acquire("job", "C", 30, SLOT) is None  # B owns it now

        await first.close()
        await second.close()

    async def test_parallel_connections_stay_serialized(self, tmp_path):
        """Concurrent writers on separate connections must not deadlock or error."""

        path = db_path_for(tmp_path)
        seed = SchedulerDB(path)
        await seed.initialize()
        await seed.upsert_definition("job", definition_hash="h1", next_run_value=SLOT)
        await seed.close()

        results: list[object] = []
        errors: list[BaseException] = []
        barrier = threading.Barrier(4)
        guard = threading.Lock()

        def claim(idx: int) -> None:
            db = SchedulerDB(path)

            try:
                db._initialize()
                barrier.wait(timeout=10)
                lease = db._try_acquire("job", f"proc:{idx}", 30, SLOT)

                with guard:
                    results.append(lease)
            except BaseException as exc:
                with guard:
                    errors.append(exc)
            finally:
                db._close_thread_conn()

        threads = [threading.Thread(target=claim, args=(i,)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert not errors
        assert sum(1 for lease in results if lease is not None) == 1

        check = SchedulerDB(path)
        assert len(check._recent_runs("job")) == 1
        await check.close()
