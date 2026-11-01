"""Per-run JSON-lines audit logs for workflow executions.

Every run appends to ``~/.cecli/workflows/runs/<YYYY-MM-DD>/<name>.<id>.jsonl``
with a ``start`` line (including the definition hash for drift detection),
one ``task`` line per workflow task and a final ``finish`` line. All
operations are best-effort: logging must never fail a workflow run.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass
class LogHandle:
    """Identifies the append-only log file of one workflow run."""

    path: str
    name: str
    source: str


def start_log(wf, source: str, run_id: Optional[int] = None) -> Optional[LogHandle]:
    """Create the run's log file and write the ``start`` line. Returns None on failure."""
    try:
        ident = str(run_id) if run_id is not None else uuid4().hex[:8]
        path = _runs_root() / datetime.now().strftime("%Y-%m-%d") / f"{wf.name}.{ident}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = LogHandle(path=str(path), name=wf.name, source=source)

        _append(
            handle,
            {
                "event": "start",
                "ts": _now_iso(),
                "workflow": wf.name,
                "source": source,
                "run_id": run_id,
                "definition_hash": wf.definition_hash(),
            },
        )
        return handle
    except Exception:
        logger.warning(
            "Failed to start run log for workflow %s", getattr(wf, "name", "?"), exc_info=True
        )
        return None


def log_task(handle: Optional[LogHandle], idx: int, result) -> None:
    """Append one ``task`` line for a :class:`TaskResult` (best-effort)."""
    if handle is None:
        return

    try:
        data = {"event": "task", "idx": idx, "ts": _now_iso()}
        data.update(result.to_dict() if hasattr(result, "to_dict") else {"message": str(result)})
        _append(handle, data)
    except Exception:
        logger.warning("Failed to append task log line for %s", handle.name, exc_info=True)


def finish_log(handle: Optional[LogHandle], result) -> None:
    """Append the ``finish`` line summarizing the run (best-effort)."""
    if handle is None:
        return

    try:
        _append(
            handle,
            {
                "event": "finish",
                "ts": _now_iso(),
                "workflow": getattr(result, "name", handle.name),
                "source": getattr(result, "source", handle.source),
                "status": getattr(result, "status", "?"),
                "summary": getattr(result, "summary", ""),
                "error_message": getattr(result, "error_message", ""),
                "run_id": getattr(result, "run_id", None),
            },
        )
    except Exception:
        logger.warning("Failed to finish run log for %s", handle.name, exc_info=True)


def latest_log_path(name: str) -> Optional[str]:
    """Return the newest run-log file for workflow *name*, or None."""
    try:
        root = _runs_root()
        if not root.is_dir():
            return None
        candidates = sorted(root.glob(f"*/{name}.*.jsonl"), key=lambda p: (p.parent.name, p.name))
        return str(candidates[-1]) if candidates else None
    except Exception:
        logger.warning("Failed to locate run logs for %s", name, exc_info=True)
        return None


def read_log_lines(path: str, limit: int = 50) -> list:
    """Read up to *limit* trailing JSON lines from a run log (best-effort)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        return [json.loads(line) for line in lines[-limit:] if line.strip()]
    except (OSError, ValueError):
        logger.warning("Failed to read run log %s", path, exc_info=True)
        return []


def _runs_root() -> Path:
    """Directory holding the per-day run-log folders."""
    return Path(os.path.expanduser("~/.cecli/workflows/runs"))


def _append(handle: LogHandle, data: Dict[str, Any]) -> None:
    with open(handle.path, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, default=str) + "\n")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
