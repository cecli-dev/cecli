"""High-level utilities for the Memorizer sub-agent.

Public API
----------

- ``add_fact(fact=..., tags=[...])`` – insert a fact with optional tags
- ``remove_facts(id_facts=[...])`` – delete facts by id
- ``search_facts(words=[...], tags=[...])`` – full-text search the fact store
- ``recent_tags(coder, limit=100)`` – most recently used tags + total count
- ``invoke_memorizer(coder, additional_context=...)`` – fire the memorizer
  sub-agent with current context
"""

import logging
import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional

from cecli.helpers.memory.db import (
    _ensure_tags,
    _get_connection,
    _link_fact_tags,
    init_db,
)

logger = logging.getLogger(__name__)


def add_fact(coder, fact: str, tags: Optional[list[str]] = None) -> int:
    """Insert a fact with optional tags.  Returns the new fact id.

    Args:
        coder: The active Coder instance (used to locate the project root).
        fact: The textual fact to store.
        tags: Optional list of tag strings to associate with the fact.

    Returns:
        The ``id_fact`` primary key of the newly inserted row.
    """

    init_db(root=coder.root)

    conn = _get_connection(root=coder.root)
    tags = tags or []

    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")

        cursor.execute(
            "INSERT INTO Facts (date, fact) VALUES (?, ?)",
            (datetime.now(timezone.utc).isoformat(), fact),
        )
        id_fact = cursor.lastrowid

        if tags:
            tag_ids = _ensure_tags(cursor, tags)
            _link_fact_tags(cursor, id_fact, tags, tag_ids)

        conn.commit()

        logger.debug("Added fact #%d with %d tag(s)", id_fact, len(tags))

        return id_fact
    except sqlite3.OperationalError:
        conn.rollback()

        raise


def remove_facts(coder, id_facts: list[int]) -> int:
    """Delete facts by their primary keys.

    Also cleans up orphaned FactTags rows (the FK cascade handles Facts,
    but we explicitly prune FactTags as well for hygiene).

    Args:
        coder: The active Coder instance (used to locate the project root).
        id_facts: List of ``id_fact`` values to delete.

    Returns:
        Number of rows deleted from the Facts table.
    """

    if not id_facts:
        return 0

    init_db(root=coder.root)

    conn = _get_connection(root=coder.root)

    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")

        placeholders = ",".join("?" for _ in id_facts)

        # Remove FactTags rows first (FK cascade would handle this, but be explicit)
        cursor.execute(
            f"DELETE FROM FactTags WHERE id_fact IN ({placeholders})",
            id_facts,
        )

        # Remove Facts (FTS triggers will handle the FTS table)
        cursor.execute(
            f"DELETE FROM Facts WHERE id_fact IN ({placeholders})",
            id_facts,
        )

        deleted = cursor.rowcount
        conn.commit()

        logger.debug("Removed %d fact(s)", deleted)

        return deleted
    except sqlite3.OperationalError:
        conn.rollback()

        raise


def search_facts(
    coder,
    words: list[str],
    tags: Optional[list[str]] = None,
    limit: int = 20,
) -> list[dict]:
    """Full-text search across facts, optionally filtered by tags.

    Uses the FTS5 table with the porter/unicode61 tokenizer.  Results are
    ordered by FTS rank (relevance) first, then by recency.

    Args:
        coder: The active Coder instance (used to locate the project root).
        words: Search terms – joined into an FTS5 query string.
        tags: Optional tag filter.  If provided, only facts that have at
              least one of these tags are returned.
        limit: Maximum number of results (default 20).

    Returns:
        A list of dicts with keys ``id_fact``, ``fact``, ``date``, ``tags``.
    """

    init_db(root=coder.root)

    conn = _get_connection(root=coder.root)
    cursor = conn.cursor()

    # Build FTS query – each word becomes a prefix match term
    fts_query = " ".join(f'"{w}"*' for w in words) if words else "*"

    if tags:
        tag_placeholders = ",".join("?" for _ in tags)
        cursor.execute(
            f"""
            SELECT f.id_fact, f.fact, f.date,
                   GROUP_CONCAT(t.tag, ',') AS tags
            FROM facts_fts fts
            JOIN Facts f ON f.id_fact = fts.rowid
            JOIN FactTags ft ON ft.id_fact = f.id_fact
            JOIN Tags t ON t.id_tag = ft.id_tag
            WHERE facts_fts MATCH ?
              AND t.tag IN ({tag_placeholders})
            GROUP BY f.id_fact
            ORDER BY rank, f.date DESC
            LIMIT ?
            """,
            [fts_query] + list(tags) + [limit],
        )
    else:
        cursor.execute(
            """
            SELECT f.id_fact, f.fact, f.date,
                   GROUP_CONCAT(t.tag, ',') AS tags
            FROM facts_fts fts
            JOIN Facts f ON f.id_fact = fts.rowid
            LEFT JOIN FactTags ft ON ft.id_fact = f.id_fact
            LEFT JOIN Tags t ON t.id_tag = ft.id_tag
            WHERE facts_fts MATCH ?
            GROUP BY f.id_fact
            ORDER BY rank, f.date DESC
            LIMIT ?
            """,
            [fts_query, limit],
        )

    rows = cursor.fetchall()

    results = []

    for row in rows:
        tag_list = row["tags"].split(",") if row["tags"] else []

        results.append(
            {
                "id_fact": row["id_fact"],
                "fact": row["fact"],
                "date": row["date"],
                "tags": tag_list,
            }
        )

    return results


def recent_tags(coder, limit: int = 100) -> dict:
    """Return the most recently used tags plus the total tag count.

    Tags are deduplicated and ordered by the recency of the most recent
    fact they are attached to (facts sorted by ``id_fact`` descending),
    then truncated to *limit* entries.

    Args:
        coder: The active Coder instance (used to locate the project root).
        limit: Maximum number of recent tags to return (default 100).

    Returns:
        A dict with keys ``tags`` (list of tag strings, most recent first)
        and ``total`` (int count of all distinct tags in the store).
    """

    init_db(root=coder.root)

    conn = _get_connection(root=coder.root)
    cursor = conn.cursor()

    # Tags ordered by the recency of the most recent fact they tag:
    # sort facts by id descending and dedupe on the tag name.
    cursor.execute(
        """
        SELECT t.tag
        FROM Facts f
        JOIN FactTags ft ON ft.id_fact = f.id_fact
        JOIN Tags t ON t.id_tag = ft.id_tag
        GROUP BY t.tag
        ORDER BY MAX(f.id_fact) DESC
        LIMIT ?
        """,
        (limit,),
    )

    tags = [row["tag"] for row in cursor.fetchall()]

    cursor.execute("SELECT COUNT(*) AS total FROM Tags")

    total = cursor.fetchone()["total"]

    return {"tags": tags, "total": total}


async def invoke_memorizer(
    coder,
    additional_context: str = "",
) -> None:
    """Fire the memorizer sub-agent with the latest context.

    Gathers the most recent user message, any saved observations from
    ``ObservationService``, and the optional *additional_context* string,
    then spawns the memorizer as a fire-and-forget sub-agent.

    Args:
        coder: The active Coder instance.
        additional_context: Extra text (e.g. compaction / yield summary)
            to include for the memorizer to derive new facts from.
    """
    # Rate-limit: don't invoke the memorizer more than once every 2 minutes
    now = time.time()
    last_invoke = getattr(coder, "_last_memory_invoke_time", 0.0)
    elapsed = now - last_invoke

    if elapsed < 120.0:
        logger.debug(
            "Skipping memorizer invocation (%.1fs since last, need >= 120s)",
            elapsed,
        )

        return

    from cecli.helpers.agents.service import AgentService
    from cecli.helpers.observations.service import ObservationService

    agent_service = AgentService.get_instance(coder)

    if not agent_service:
        return

    # Gather context pieces
    parts: list[str] = []

    # Recent tags (deduplicated, most recently used first) plus the total
    # tag count — first context part so the memorizer sees active tags
    recent = recent_tags(coder)

    tag_list = ", ".join(recent["tags"]) if recent["tags"] else "(none)"

    parts.append(f"## Recent Tags\n\n{tag_list}\n\n## Total Tags in DB\n\n{recent['total']}")

    # Latest user message
    last_user = getattr(coder, "last_user_message", "")

    if last_user:
        parts.append(f"## Latest User Message\n\n{last_user}")

    # Observations
    obs_service = ObservationService.get_instance(coder)

    if obs_service and obs_service.observations:
        obs_text = "\n".join(f"- {o}" for o in obs_service.observations)

        parts.append(f"## Saved Observations\n\n{obs_text}")

    # Additional context (compaction / yield summary)
    if additional_context:
        parts.append(f"## Additional Context\n\n{additional_context}")

    if not parts:
        return

    prompt = "\n\n".join(parts)

    logger.debug("Invoking memorizer with %d context part(s)", len(parts))

    # Update timestamp before spawning so concurrent calls are also rate-limited
    coder._last_memory_invoke_time = time.time()

    # Fire-and-forget (don't block the primary agent)
    try:

        await agent_service.spawn(
            name="memorizer",
            prompt=prompt,
            independent=True,
        )
    except Exception:
        logger.debug("Failed to spawn memorizer sub-agent", exc_info=True)
