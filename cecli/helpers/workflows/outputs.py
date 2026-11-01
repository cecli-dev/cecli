"""Persistent per-run output files for workflow ``save_to`` keys.

Runs store nothing in any database (the project-facts / memorizer DB is not
an output sink): each run gets its own directory under
``~/.cecli/workflows/outputs/{workflow}/``, named ``run-{id}`` for scheduler
runs or by the run's start timestamp for manual ones. A task with ``save_to``
writes the run's final summary into ``{key}`` inside that directory, and the
resulting path is recorded in the run log (and ``/workflows last``).
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def outputs_root() -> Path:
    """Directory holding the per-workflow output trees."""
    return Path(os.path.expanduser("~/.cecli/workflows/outputs"))


def save_output(
    wf_name: str,
    key: str,
    text: str,
    run_id: Optional[int] = None,
    started_at: Optional[str] = None,
) -> str:
    """Write *text* into the run's output directory; return the file path.

    Raises on I/O failure — the caller (the runner) treats saving as
    best-effort, so errors surface there as warnings rather than here.
    """
    directory = run_output_dir(wf_name, run_id, started_at)
    path = directory / _safe(key, fallback="output")
    path.write_text(text, encoding="utf-8")
    return str(path)


def run_output_dir(
    wf_name: str, run_id: Optional[int] = None, started_at: Optional[str] = None
) -> Path:
    """The persistent directory for one run's artifacts (created on demand)."""
    directory = outputs_root() / _safe(wf_name) / _run_key(run_id, started_at)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _safe(value: str, fallback: str = "workflow") -> str:
    """Flatten a workflow name / save_to key into one filesystem-safe name."""
    cleaned = _SAFE_RE.sub("_", str(value).strip()).strip(".")
    return cleaned or fallback


def _run_key(run_id: Optional[int], started_at: Optional[str]) -> str:
    """Directory name for a run: the scheduler id, else a sortable timestamp."""
    if run_id is not None:
        return f"run-{run_id}"

    stamp = started_at or datetime.now(timezone.utc).isoformat()
    return stamp[:19].replace("T", "-").replace(":", "")
