"""Scheduler SQLite database: schema, slot leases and crash recovery.

Global by design (cross-process arbiter) at
``~/.cecli/scheduler/scheduler.v1/scheduler.db``. WAL journal, thread-local
connections, and ``BEGIN IMMEDIATE`` for every write — the same recipe as
:mod:`cecli.helpers.memory.db`. The ``UNIQUE(name, slot, attempts)``
constraint on ``runs`` *is* the lock: whichever instance inserts the claim
row first owns the slot; others may only steal it after the lease expires.

All timestamps are UTC ISO-8601 with a trailing ``Z`` and millisecond
precision so they compare correctly as plain strings.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Union

from cecli.helpers.scheduler.cron import next_run as cron_next_run
from cecli.helpers.scheduler.lock import JobLease

logger = logging.getLogger(__name__)

# Increment when the schema changes in an incompatible way
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    name            TEXT PRIMARY KEY,
    definition_hash TEXT NOT NULL,
    schedule        TEXT,
    engine          TEXT,
    enabled         INTEGER NOT NULL DEFAULT 1,
    lease_timeout   REAL    NOT NULL DEFAULT 30,
    next_run        TEXT,
    last_run        TEXT,
    last_status     TEXT,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL REFERENCES jobs(name) ON DELETE CASCADE,
    slot            TEXT NOT NULL,
    instance_id     TEXT NOT NULL,
    source          TEXT NOT NULL,
    status          TEXT NOT NULL,
    acquired_at     TEXT NOT NULL,
    lease_expires_at TEXT NOT NULL,
    renewed_at      TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT,
    attempts        INTEGER NOT NULL DEFAULT 1,
    summary         TEXT,
    UNIQUE(name, slot, attempts)
);
CREATE INDEX IF NOT EXISTS ix_runs_name_status ON runs(name, status);

CREATE TABLE IF NOT EXISTS task_log (
    run_id   INTEGER NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    idx      INTEGER NOT NULL,
    label    TEXT,
    status   TEXT NOT NULL,
    message  TEXT,
    ts       TEXT NOT NULL,
    PRIMARY KEY (run_id, idx)
);
"""


def get_db_path() -> Path:
    """Return the global scheduler DB path (versioned directory)."""

    return Path.home() / ".cecli" / "scheduler" / f"scheduler.v{SCHEMA_VERSION}" / "scheduler.db"


class SchedulerDB:
    """Multi-process-safe store of job definitions' run state and leases.

    Public methods are coroutines (sync work runs via ``asyncio.to_thread``);
    the ``_``-prefixed sync versions are used directly by tests racing threads.
    """

    def __init__(self, db_path: Optional[Union[Path, str]] = None):
        self.db_path = Path(db_path) if db_path is not None else get_db_path()
        self._local = threading.local()
        # Registry of every connection ever handed out (asyncio.to_thread
        # workers get their own); close() drains it so reload cycles in one
        # process do not accumulate open handles on the WAL file.
        self._all_conns: list = []
        self._conns_lock = threading.Lock()
        self._initialized = False

    # ── async API ────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize)

    async def upsert_definition(self, name: str, **fields: Any) -> None:
        await asyncio.to_thread(self._upsert_definition, name, **fields)

    async def sync_definitions(
        self, workflows: Dict[str, Any], now: Optional[datetime] = None
    ) -> None:
        await asyncio.to_thread(self._sync_definitions, workflows, now)

    async def due_definitions(self, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._due_definitions, now)

    async def try_acquire(
        self,
        name: str,
        instance_id: str,
        lease_timeout_min: float,
        slot: str,
        source: str = "scheduler",
        attempts: int = 1,
    ) -> Optional[JobLease]:
        return await asyncio.to_thread(
            self._try_acquire, name, instance_id, lease_timeout_min, slot, source, attempts
        )

    async def renew(self, run_id: int, instance_id: str, lease_timeout_min: float) -> int:
        return await asyncio.to_thread(self._renew, run_id, instance_id, lease_timeout_min)

    async def finish(self, lease_or_run_id: Any, result: Any = None, **fields: Any) -> None:
        await asyncio.to_thread(self._finish, lease_or_run_id, result, **fields)

    async def release(self, lease_or_run_id: Any, instance_id: Optional[str] = None) -> int:
        return await asyncio.to_thread(self._release, lease_or_run_id, instance_id)

    async def advance(self, name: str, next_run_value: Any = None) -> None:
        await asyncio.to_thread(self._advance, name, next_run_value)

    async def disable(self, name: str, reason: str = "") -> None:
        await asyncio.to_thread(self._disable, name, reason)

    async def enable(self, name: str) -> int:
        return await asyncio.to_thread(self._enable, name)

    async def active_leases(self, name: Optional[str] = None) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._active_leases, name)

    async def get_job(self, name: str) -> Optional[Dict[str, Any]]:
        return await asyncio.to_thread(self._get_job, name)

    async def list_jobs(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._list_jobs, enabled_only)

    async def recent_runs(
        self, name: Optional[str] = None, limit: int = 20
    ) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._recent_runs, name, limit)

    async def log_task(
        self, run_id: int, idx: int, label: str, status: str, message: str = ""
    ) -> None:
        await asyncio.to_thread(self._log_task, run_id, idx, label, status, message)

    async def close(self) -> None:
        self._close_thread_conn()

    # ── sync implementations ─────────────────────────────────────────────

    def _initialize(self) -> None:
        conn = self._get_connection()
        conn.executescript(_SCHEMA)
        self._initialized = True

        now = self._now_iso()
        with self._write_txn(conn):
            cur = conn.execute(
                "UPDATE runs SET status='aborted', finished_at=?, lease_expires_at=?,"
                " summary=COALESCE(summary, 'aborted: lease expired before shutdown')"
                " WHERE status='running' AND lease_expires_at < ?",
                (now, now, now),
            )

        if cur.rowcount:
            logger.info("scheduler db crash recovery: aborted %d stale run(s)", cur.rowcount)

    def _upsert_definition(
        self,
        name: str,
        *,
        definition_hash: str,
        schedule: Optional[str] = None,
        engine: Optional[str] = None,
        enabled: bool = True,
        lease_timeout: float = 30.0,
        next_run_value: Any = None,
    ) -> None:
        conn = self._get_connection()
        now = self._now_iso()

        with self._write_txn(conn):
            conn.execute(
                """
                INSERT INTO jobs(name, definition_hash, schedule, engine, enabled,
                                 lease_timeout, next_run, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    definition_hash = excluded.definition_hash,
                    schedule        = excluded.schedule,
                    engine          = excluded.engine,
                    enabled         = excluded.enabled,
                    lease_timeout   = excluded.lease_timeout,
                    next_run        = excluded.next_run,
                    updated_at      = excluded.updated_at
                """,
                (
                    name,
                    definition_hash,
                    schedule,
                    engine,
                    1 if enabled else 0,
                    float(lease_timeout),
                    self._to_iso(next_run_value),
                    now,
                ),
            )

    def _sync_definitions(self, workflows: Dict[str, Any], now: Optional[datetime] = None) -> None:
        from cecli.helpers.scheduler.cron import parse_schedule

        conn = self._get_connection()
        now = now or datetime.now(timezone.utc)

        for name, wf in (workflows or {}).items():
            schedule = getattr(wf, "schedule", None)
            try:
                engine, _ = parse_schedule(schedule)
            except ValueError:
                logger.warning(
                    "workflow %r has a malformed schedule %r; registering manual", name, schedule
                )
                engine = "manual"
                schedule = None

            def_hash = self._definition_hash(wf)
            row = conn.execute(
                "SELECT definition_hash, next_run FROM jobs WHERE name = ?", (name,)
            ).fetchone()

            if row is None or row["definition_hash"] != def_hash:
                nxt = cron_next_run(schedule, now, timezone=getattr(wf, "timezone", None))
            else:
                nxt = row["next_run"]

            self._upsert_definition(
                name,
                definition_hash=def_hash,
                schedule=schedule,
                engine=engine,
                enabled=bool(getattr(wf, "enabled", True)),
                lease_timeout=float(getattr(wf, "lease_timeout", 30.0)),
                next_run_value=nxt,
            )

        if workflows is not None:
            # An *empty* mapping still means "disable everything else" (the
            # service passes its enabled-only dict), but `NOT IN ()` is a
            # syntax error on older SQLite, so branch instead of formatting.
            with self._write_txn(conn):
                if workflows:
                    marks = ",".join("?" for _ in workflows)
                    conn.execute(
                        f"UPDATE jobs SET enabled = 0, next_run = NULL, updated_at = ?"
                        f" WHERE enabled = 1 AND name NOT IN ({marks})",
                        (self._now_iso(), *workflows),
                    )
                else:
                    conn.execute(
                        "UPDATE jobs SET enabled = 0, next_run = NULL, updated_at = ?"
                        " WHERE enabled = 1",
                        (self._now_iso(),),
                    )

    def _active_leases(self, name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Running rows whose lease has not expired yet (optionally per job)."""
        conn = self._get_connection()
        sql = (
            "SELECT run_id, name, slot, instance_id, source, acquired_at,"
            " lease_expires_at, renewed_at FROM runs"
            " WHERE status = 'running' AND lease_expires_at > ?"
        )

        params: list = [self._now_iso()]

        if name is not None:
            sql += " AND name = ?"
            params.append(name)

        return [dict(r) for r in conn.execute(sql + " ORDER BY name, slot", params)]

    def _due_definitions(self, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        now_iso = self._to_iso(now) or self._now_iso()

        rows = conn.execute(
            "SELECT * FROM jobs"
            " WHERE enabled = 1 AND next_run IS NOT NULL AND next_run <= ?"
            "   AND NOT EXISTS ("
            "       SELECT 1 FROM runs WHERE runs.name = jobs.name"
            "         AND runs.slot = jobs.next_run"
            "         AND runs.status = 'running' AND runs.lease_expires_at > ?"
            "   )"
            " ORDER BY next_run",
            (now_iso, now_iso),
        ).fetchall()

        return [dict(row) for row in rows]

    def _try_acquire(
        self,
        name: str,
        instance_id: str,
        lease_timeout_min: float,
        slot: str,
        source: str = "scheduler",
        attempts: int = 1,
    ) -> Optional[JobLease]:
        conn = self._get_connection()
        now_dt = datetime.now(timezone.utc)
        now = self._iso(now_dt)
        expires = self._iso(now_dt + timedelta(minutes=float(lease_timeout_min)))

        with self._write_txn(conn):
            try:
                cur = conn.execute(
                    "INSERT INTO runs(name, slot, instance_id, source, status,"
                    " acquired_at, lease_expires_at, renewed_at, started_at, attempts)"
                    " VALUES(?, ?, ?, ?, 'running', ?, ?, ?, ?, ?)",
                    (name, slot, instance_id, source, now, expires, now, now, int(attempts)),
                )
                run_id = cur.lastrowid
            except sqlite3.IntegrityError as exc:
                if "UNIQUE" not in str(exc):
                    raise

                # Claim lost: a row already exists for this (name, slot, 1).
                # Steal only when the owner's lease is dead (expired-running,
                # or aborted by crash recovery / release) by inserting the next
                # attempt row: MAX(attempts)+1, computed under the same
                # BEGIN IMMEDIATE write lock, so the UNIQUE constraint can
                # never collide here and every attempt stays on record.
                live = conn.execute(
                    "SELECT 1 FROM runs WHERE name = ? AND slot = ?"
                    " AND status = 'running' AND lease_expires_at > ?",
                    (name, slot, now),
                ).fetchone()

                if live:
                    return None

                # A *completed* terminal row means the slot already ran (a peer
                # won, ran and advanced between our due-read and this acquire):
                # never re-run it. Only crash-aborted rows are retry-eligible.
                terminal = conn.execute(
                    "SELECT status FROM runs WHERE name = ? AND slot = ?"
                    " ORDER BY attempts DESC LIMIT 1",
                    (name, slot),
                ).fetchone()

                if terminal is not None and terminal["status"] in ("ok", "error", "skipped"):
                    return None

                nxt_attempts = conn.execute(
                    "SELECT COALESCE(MAX(attempts), 0) + 1 FROM runs"
                    " WHERE name = ? AND slot = ?",
                    (name, slot),
                ).fetchone()[0]
                cur = conn.execute(
                    "INSERT INTO runs(name, slot, instance_id, source, status,"
                    " acquired_at, lease_expires_at, renewed_at, started_at, attempts)"
                    " VALUES(?, ?, ?, ?, 'running', ?, ?, ?, ?, ?)",
                    (name, slot, instance_id, source, now, expires, now, now, int(nxt_attempts)),
                )
                run_id = cur.lastrowid

        return JobLease(
            run_id=int(run_id),
            name=name,
            slot=slot,
            instance_id=instance_id,
            lease_expires_at=expires,
        )

    def _renew(self, run_id: int, instance_id: str, lease_timeout_min: float) -> int:
        conn = self._get_connection()
        now_dt = datetime.now(timezone.utc)
        expires = self._iso(now_dt + timedelta(minutes=float(lease_timeout_min)))

        with self._write_txn(conn):
            cur = conn.execute(
                "UPDATE runs SET renewed_at = ?, lease_expires_at = ?"
                " WHERE run_id = ? AND instance_id = ? AND status = 'running'"
                "   AND NOT EXISTS ("
                "       SELECT 1 FROM runs r2"
                "       WHERE r2.name = runs.name AND r2.slot = runs.slot"
                "         AND r2.attempts > runs.attempts"
                "   )",
                (self._iso(now_dt), expires, int(run_id), instance_id),
            )

        return cur.rowcount

    def _finish(self, lease_or_run_id: Any, result: Any = None, **fields: Any) -> None:
        conn = self._get_connection()
        run_id = _run_id_of(lease_or_run_id)
        name = getattr(lease_or_run_id, "name", None) or fields.get("name")

        status = fields.get("status") or getattr(result, "status", None) or "ok"
        summary = fields.get("summary")
        if summary is None:
            summary = getattr(result, "summary", None) or getattr(result, "error_message", None)
        error_message = fields.get("error_message") or getattr(result, "error_message", None)

        if status == "ok" and error_message:
            status = "error"

        if summary is None:
            summary = ""
        summary = str(summary)[:4000]

        now = self._now_iso()

        with self._write_txn(conn):
            row = None
            if name is None:
                row = conn.execute("SELECT name FROM runs WHERE run_id = ?", (run_id,)).fetchone()
                name = row["name"] if row else None

            conn.execute(
                "UPDATE runs SET status = ?, summary = ?, finished_at = ?, lease_expires_at = ?"
                " WHERE run_id = ?",
                (status, summary, now, now, run_id),
            )

            if name is not None:
                conn.execute(
                    "UPDATE jobs SET last_run = ?, last_status = ?, updated_at = ? WHERE name = ?",
                    (now, status, now, name),
                )

    def _release(self, lease_or_run_id: Any, instance_id: Optional[str] = None) -> int:
        conn = self._get_connection()
        run_id = _run_id_of(lease_or_run_id)
        if instance_id is None:
            instance_id = getattr(lease_or_run_id, "instance_id", None)
        name = getattr(lease_or_run_id, "name", None)

        now = self._now_iso()

        with self._write_txn(conn):
            cur = conn.execute(
                "UPDATE runs SET status = 'aborted', finished_at = ?, lease_expires_at = ?,"
                " summary = 'released'"
                " WHERE run_id = ? AND status = 'running'"
                + (" AND instance_id = ?" if instance_id is not None else ""),
                (now, now, run_id) + ((instance_id,) if instance_id is not None else ()),
            )

            if cur.rowcount and name is None:
                row = conn.execute("SELECT name FROM runs WHERE run_id = ?", (run_id,)).fetchone()
                name = row["name"] if row else None

            if cur.rowcount and name is not None:
                conn.execute(
                    "UPDATE jobs SET last_status = 'aborted', updated_at = ? WHERE name = ?",
                    (now, name),
                )

        return cur.rowcount

    def _advance(self, name: str, next_run_value: Any = None) -> None:
        conn = self._get_connection()
        next_iso = self._to_iso(next_run_value)
        now = self._now_iso()

        with self._write_txn(conn):
            # Monotonic for concrete times: a stale writer finishing a late
            # slot must never drag next_run backwards (that would re-arm
            # already-run slots). None is an explicit clear (manual-only chain),
            # written unconditionally.
            conn.execute(
                "UPDATE jobs SET next_run = CASE"
                "   WHEN ? IS NULL THEN NULL"
                "   WHEN next_run IS NULL OR next_run < ? THEN ?"
                "   ELSE next_run END,"
                "   updated_at = ? WHERE name = ?",
                (next_iso, next_iso, next_iso, now, name),
            )
            conn.execute(
                "UPDATE runs SET status = 'aborted', finished_at = ?,"
                " summary = COALESCE(summary, 'aborted: lease expired')"
                " WHERE name = ? AND status = 'running' AND lease_expires_at < ?",
                (now, name, now),
            )

    def _disable(self, name: str, reason: str = "") -> None:
        conn = self._get_connection()

        with self._write_txn(conn):
            conn.execute(
                "UPDATE jobs SET enabled = 0, next_run = NULL, updated_at = ? WHERE name = ?",
                (self._now_iso(), name),
            )

        if reason:
            logger.info("scheduler job %r disabled: %s", name, reason)

    def _enable(self, name: str) -> int:
        """Re-arm a disabled job: enabled=1 and next_run from cron(now).

        ``disable`` NULLs ``next_run`` and a disabled definition's hash does not
        change, so without re-seeding an ``/workflows enable`` round-trip would
        leave the job permanently dead until its definition was edited.
        """
        conn = self._get_connection()
        now_dt = datetime.now(timezone.utc)
        now = self._iso(now_dt)

        with self._write_txn(conn):
            row = conn.execute(
                "SELECT schedule, engine FROM jobs WHERE name = ?", (name,)
            ).fetchone()

            if row is None:
                return 0

            nxt = None

            if row["schedule"] and row["engine"] != "manual":
                try:
                    nxt = self._iso(cron_next_run(row["schedule"], now_dt))
                except ValueError:
                    logger.warning(
                        "job %r has a malformed schedule %r; enabled without next_run",
                        name,
                        row["schedule"],
                    )

            conn.execute(
                "UPDATE jobs SET enabled = 1, next_run = ?, updated_at = ? WHERE name = ?",
                (nxt, now, name),
            )

        return 1

    def _get_job(self, name: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        row = conn.execute("SELECT * FROM jobs WHERE name = ?", (name,)).fetchone()

        return dict(row) if row else None

    def _list_jobs(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        sql = "SELECT * FROM jobs"

        if enabled_only:
            sql += " WHERE enabled = 1"

        return [dict(row) for row in conn.execute(sql + " ORDER BY name")]

    def _recent_runs(self, name: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        sql = "SELECT * FROM runs"
        params: tuple = ()

        if name is not None:
            sql += " WHERE name = ?"
            params = (name,)

        sql += " ORDER BY run_id DESC LIMIT ?"

        return [dict(r) for r in conn.execute(sql, params + (int(limit),))]

    def _log_task(self, run_id: int, idx: int, label: str, status: str, message: str = "") -> None:
        conn = self._get_connection()

        with self._write_txn(conn):
            conn.execute(
                "INSERT INTO task_log(run_id, idx, label, status, message, ts)"
                " VALUES(?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(run_id, idx) DO UPDATE SET"
                "   label = excluded.label, status = excluded.status,"
                "   message = excluded.message, ts = excluded.ts",
                (int(run_id), int(idx), label, status, message, self._now_iso()),
            )

    def _close_thread_conn(self) -> None:
        with self._conns_lock:
            conns, self._all_conns = self._all_conns, []

        for conn in conns:
            try:
                conn.close()
            except sqlite3.Error:
                pass

        self._local.conn = None

    # ── plumbing ─────────────────────────────────────────────────────────

    def _get_connection(self) -> sqlite3.Connection:
        """Return this thread's connection, applying the memory/db.py pragmas."""
        conn = getattr(self._local, "conn", None)

        if conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.db_path), timeout=10.0, isolation_level=None)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute("PRAGMA busy_timeout=10000;")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn

            with self._conns_lock:
                self._all_conns.append(conn)

        return conn

    @contextmanager
    def _write_txn(self, conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
        """One BEGIN IMMEDIATE transaction (cross-process write lock)."""
        conn.execute("BEGIN IMMEDIATE")

        try:
            yield conn
        except Exception:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")

    def _now_iso(self) -> str:
        return self._iso(datetime.now(timezone.utc))

    def _to_iso(self, value: Any) -> Optional[str]:
        if value is None:
            return None

        if isinstance(value, str):
            return value

        if isinstance(value, datetime):
            return self._iso(value)

        raise TypeError(f"cannot interpret as a time: {value!r}")

    @staticmethod
    def _iso(dt: datetime) -> str:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return (
            dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.")
            + f"{dt.microsecond // 1000:03d}Z"
        )

    @staticmethod
    def _definition_hash(wf: Any) -> str:
        hash_fn = getattr(wf, "definition_hash", None)

        if callable(hash_fn):
            return str(hash_fn())

        return str(hash_fn or "")


def _run_id_of(lease_or_run_id: Any) -> int:
    """Accept a JobLease (or anything with .run_id) or a bare int run_id."""
    run_id = getattr(lease_or_run_id, "run_id", lease_or_run_id)

    return int(run_id)
