"""Session checkpoints for resuming interrupted workflow runs.

A checkpoint is written before each step starts, so the recorded step is the
one that was actually executing when the process died. The post_run hook then
chooses the next step dynamically; recording it before it starts keeps jumps,
loops and stops from being guessed or replayed incorrectly.
"""

from __future__ import annotations

import logging
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from cecli.helpers.workflows.models import WorkflowConfig

logger = logging.getLogger(__name__)


@dataclass
class ResumePoint:
    """A running workflow session found on disk, ready to be resumed."""

    key: str
    path: Any
    payload: dict
    step: str
    prompt: Any
    statuses: dict


def find_resume_session(coder, wf: WorkflowConfig, steps: dict) -> Optional[ResumePoint]:
    """Return the newest unfinished session for *wf*, if one is resumable."""
    from cecli.helpers.sessions.storage import read_payload
    from cecli.helpers.workflows import outputs

    root = outputs.workflow_output_dir(wf.name)

    if not root.is_dir():
        return None

    best = None

    for path in root.glob("*/session.json"):
        payload = read_payload(coder, coder.io, path, quiet=True)

        if not isinstance(payload, dict):
            continue

        state = payload.get("workflow")

        if not _is_resumable(state, wf, steps):
            continue

        key = str(state.get("updated_at") or "")

        if best is None or key > best.key:
            best = ResumePoint(
                key=key,
                path=path,
                payload=payload,
                step=state["step"],
                prompt=state.get("prompt") if isinstance(state.get("prompt"), str) else None,
                statuses=_statuses_from_state(state.get("statuses")),
            )

    return best


async def restore_session(
    worker, coder, wf: WorkflowConfig, resume: ResumePoint, system_prompt: str
) -> bool:
    """Load a saved session into *worker*; the caller resets it on failure."""
    from cecli.helpers import command_queue
    from cecli.helpers.conversation.service import ConversationService
    from cecli.helpers.sessions.payload import apply_payload

    try:
        applied, _edit_format = await apply_payload(
            worker, coder.io, resume.payload, resume.path, sub_agent=True
        )
    except Exception:
        logger.warning("Failed to restore workflow session for '%s'", wf.name, exc_info=True)
        applied = False

    if not applied:
        return False

    command_queue.clear_queue(worker)
    worker._queue_counter = 0
    ConversationService.get_chunks(worker).add_system_message(system_prompt)

    return True


def write_session_progress(
    worker,
    io,
    wf: WorkflowConfig,
    *,
    run_id: Any,
    started_at: Any,
    step: Any,
    prompt: Any,
    status: str = "running",
    statuses: Any = None,
) -> bool:
    """Write the worker's session with the step that is about to run."""
    from cecli.helpers.sessions.payload import build_payload
    from cecli.helpers.sessions.storage import write_payload
    from cecli.helpers.workflows import outputs

    try:
        path = outputs.run_output_dir(wf.name, run_id, started_at) / "session.json"
        payload = build_payload(
            worker,
            io,
            f"workflow:{wf.name}",
            agent_name=wf.agent_name,
            workflow=_session_metadata(wf, run_id, started_at, step, prompt, status, statuses),
        )

        return write_payload(worker, io, path, payload)
    except Exception:
        logger.warning("Failed to persist workflow session for '%s'", wf.name, exc_info=True)
        return False


def mark_resume_consumed(coder, resume: ResumePoint) -> None:
    """Mark the old session as resumed so it is never picked up twice."""
    from cecli.helpers.sessions.storage import write_payload

    state = dict(resume.payload.get("workflow") or {})
    state["status"] = "resumed"
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload = dict(resume.payload)
    payload["workflow"] = state

    try:
        write_payload(coder, coder.io, resume.path, payload)
    except Exception:
        logger.warning("Failed to mark workflow session %s as resumed", resume.path, exc_info=True)


def _is_resumable(state: Any, wf: WorkflowConfig, steps: dict) -> bool:
    """Whether a session payload points at an interrupted run of *wf*."""
    if not isinstance(state, dict):
        return False

    if state.get("name") != wf.name or state.get("status") != "running":
        return False

    if state.get("definition_hash") != wf.definition_hash():
        return False

    step = state.get("step")

    if not isinstance(step, str) or step not in steps:
        return False

    return not _process_is_live(state.get("pid"), state.get("host"))


def _process_is_live(pid: Any, host: Any) -> bool:
    """Whether *pid* is still running on this host."""
    if not pid or host != socket.gethostname():
        return False

    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (TypeError, ValueError, OSError):
        return False

    return True


def _statuses_from_state(value: Any) -> dict:
    """Convert persisted task statuses back into ``{name: (status, message)}``."""
    statuses = {}

    if not isinstance(value, dict):
        return statuses

    for name, pair in value.items():
        if isinstance(pair, (list, tuple)) and pair:
            statuses[str(name)] = (
                str(pair[0]),
                str(pair[1]) if len(pair) > 1 else "",
            )

    return statuses


def _session_metadata(
    wf: WorkflowConfig,
    run_id: Any,
    started_at: Any,
    step: Any,
    prompt: Any,
    status: str,
    statuses: Any,
) -> dict:
    """Build the ``workflow`` block stored inside a workflow session payload."""
    return {
        "name": wf.name,
        "run_id": run_id,
        "started_at": started_at,
        "step": step or "",
        "prompt": prompt,
        "status": status,
        "statuses": {
            name: list(value[:2])
            for name, value in (statuses or {}).items()
            if isinstance(value, (list, tuple)) and value
        },
        "definition_hash": wf.definition_hash(),
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
