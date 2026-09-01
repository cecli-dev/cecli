"""SQLite database schema and helpers for the Memorizer fact store.

Schema
------

Facts (id_fact INTEGER PRIMARY KEY, date TIMESTAMP, fact TEXT)
Tags  (id_tag  INTEGER PRIMARY KEY, tag TEXT UNIQUE)
FactTags (id_tag INTEGER, id_fact INTEGER, PRIMARY KEY (id_tag, id_fact))

A virtual FTS5 table (facts_fts) is kept in sync with the Facts table
for full-text search.

Multi-process safety is achieved via WAL journal mode and BEGIN IMMEDIATE
transactions.
"""

import logging
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# Increment this when the schema changes in an incompatible way
SCHEMA_VERSION = 1

# Thread-local storage so each thread gets its own connection
_local = threading.local()

# Set to True after the first init_db() call in a session
_INIT_COMPLETED = False


def get_schema_version() -> int:
    """Return the current schema version."""

    return SCHEMA_VERSION


def get_db_path(root: Path | str | None = None) -> Path:
    """Return the filesystem path of the SQLite database.

    If *root* is provided (e.g. ``coder.root``), the database lives at
    ``{root}/.cecli/memory.{SCHEMA_VERSION}.db``.  Otherwise the current
    working directory is used.
    """
    base = Path(root) if root is not None else Path.cwd()
    return base / ".cecli" / f"memory.v{SCHEMA_VERSION}" / "cache.db"


def _get_connection(root: Path | None = None) -> sqlite3.Connection:
    """Return a thread-local, write-optimised SQLite connection."""
    conn = getattr(_local, "conn", None)

    if conn is None:
        db_path = get_db_path(root)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_path), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.row_factory = sqlite3.Row

        _local.conn = conn

    return conn


def init_db(root: Path | None = None) -> None:
    """Create the schema (tables, indexes, FTS) if it does not exist.

    Only runs once per session — subsequent calls are no-ops.
    """
    global _INIT_COMPLETED

    if _INIT_COMPLETED:
        return

    conn = _get_connection(root)

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS Facts (
            id_fact INTEGER PRIMARY KEY AUTOINCREMENT,
            date    TIMESTAMP NOT NULL DEFAULT (datetime('now')),
            fact    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS Tags (
            id_tag INTEGER PRIMARY KEY AUTOINCREMENT,
            tag    TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS FactTags (
            id_tag  INTEGER NOT NULL REFERENCES Tags(id_tag),
            id_fact INTEGER NOT NULL REFERENCES Facts(id_fact),
            PRIMARY KEY (id_tag, id_fact)
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
            fact,
            content='Facts',
            content_rowid='id_fact',
            tokenize='porter unicode61'
        );

        -- Triggers to keep FTS in sync
        CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON Facts BEGIN
            INSERT INTO facts_fts(rowid, fact) VALUES (new.id_fact, new.fact);
        END;

        CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON Facts BEGIN
            INSERT INTO facts_fts(facts_fts, rowid, fact) VALUES('delete', old.id_fact, old.fact);
        END;

        CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON Facts BEGIN
            INSERT INTO facts_fts(facts_fts, rowid, fact) VALUES('delete', old.id_fact, old.fact);
            INSERT INTO facts_fts(rowid, fact) VALUES (new.id_fact, new.fact);
        END;
        """)

    conn.commit()

    _INIT_COMPLETED = True

    logger.debug("Memory DB initialised at %s", get_db_path(root))


def _ensure_tags(cursor: sqlite3.Cursor, tags: list[str]) -> dict[str, int]:
    """Ensure every tag in *tags* exists in the Tags table.

    Returns a mapping ``{tag_name: id_tag}`` for all requested tags.
    """

    tag_ids: dict[str, int] = {}

    for t in tags:
        cursor.execute("INSERT OR IGNORE INTO Tags (tag) VALUES (?)", (t,))
        cursor.execute("SELECT id_tag FROM Tags WHERE tag = ?", (t,))
        row = cursor.fetchone()

        if row:
            tag_ids[t] = row["id_tag"]

    return tag_ids


def _link_fact_tags(
    cursor: sqlite3.Cursor, id_fact: int, tags: list[str], tag_ids: dict[str, int]
) -> None:
    """Link *id_fact* to each tag in *tags* via the FactTags table."""

    for t in tags:
        id_tag = tag_ids.get(t)

        if id_tag is not None:
            cursor.execute(
                "INSERT OR IGNORE INTO FactTags (id_tag, id_fact) VALUES (?, ?)",
                (id_tag, id_fact),
            )
