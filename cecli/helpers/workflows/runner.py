"""The single dispatch path for workflow runs (manual or scheduled).

A run composes two existing mechanisms verbatim: the ``wf:`` sub-agent
registration (see :mod:`cecli.helpers.workflows.subagents`) and the CLI-33
per-coder prompt queue. The worker is spawned *without* a prompt so the whole
task list can be enqueued first; ``run_one`` then drains the queue as nested
recursion, executing each prompt exactly as if it had been typed.

Handled failures never raise into the caller — they return a ``RunResult``
with ``status`` set (``ok`` | ``error`` | ``aborted``).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, List, Optional

from cecli.helpers.workflows.models import RunResult, TaskResult, WorkflowConfig

logger = logging.getLogger(__name__)


async def execute_workflow(
    coder: Any,
    wf: WorkflowConfig,
    *,
    source: str = "manual",
    run_id: Optional[int] = None,
) -> RunResult:
    """Execute *wf* on its ``wf:{name}`` worker and report a :class:`RunResult`.

    Args:
        coder: The primary coder that owns the run (becomes the worker's parent).
        wf: The workflow definition to execute.
        source: ``manual`` | ``scheduler`` | ``scheduler_daemon`` — recorded on
            the result and in the run log.
        run_id: Optional scheduler ``runs`` row id, used for the log file name
            and placeholder expansion.
    """
    from cecli.helpers import command_queue
    from cecli.helpers.workflows import logs
    from cecli.helpers.workflows.subagents import register_workflow_subagents

    result = RunResult(
        name=wf.name,
        source=source,
        run_id=run_id,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    handle = logs.start_log(wf, source, run_id=run_id)
    result.log_path = handle.path if handle else None

    worker = None
    service = None
    try:
        from cecli.helpers.agents.service import AgentService

        register_workflow_subagents([wf])
        service = AgentService.get_instance(coder)

        if not wf.tasks:
            result.status = "error"
            result.error_message = "workflow has no tasks"
            return result

        texts = [_expand(task.prompt, wf=wf, run_id=run_id) for task in wf.tasks]

        # Persistent workflows reuse their previous worker (clearing its
        # conversation and queue) so they stay visible in the TUI; everything
        # else spawns WITHOUT a prompt so the whole task list can be staged
        # first. The daemon variant runs on its own tree branch, everything
        # else shares the owning session.
        worker, info = await _obtain_worker(service, coder, wf, source)

        for text in texts[1:]:
            command_queue.enqueue_prompt(worker, text)

        # The first task is started directly, so make sure a command task also
        # drains the staged queue instead of stopping after the command.
        worker._drain_queue_after_command = True
        service.start_generate_task(info, texts[0])

        outcome, detail = await _await_run(info)

        pending = command_queue.list_queue(worker)
        executed_tail = len(wf.tasks) - 1 - len(pending)
        failing = wf.tasks[_failing_index(executed_tail, len(wf.tasks))]

        if outcome != "ok" and _should_stop(wf, failing):
            command_queue.clear_queue(worker)

        result.status = outcome
        if outcome != "ok":
            result.error_message = detail if outcome == "error" else ""

        # Keep the abort reason (e.g. cancelled) as the summary unless
        # the worker actually produced one before dying.
        if outcome != "aborted" or info.summary:
            result.summary = info.summary or ""
        result.tasks = _task_results(wf, outcome, detail, executed_tail)

        if outcome != "aborted":
            _save_outputs(wf, result)

        for idx, task_result in enumerate(result.tasks):
            logs.log_task(handle, idx, task_result)
    except Exception as exc:
        logger.exception("workflow '%s' run failed unexpectedly", wf.name)
        result.status = "error"
        result.error_message = str(exc) or exc.__class__.__name__
    finally:
        if worker is not None:
            _save_session(worker, coder, wf, result)
            if not wf.persist:
                _reap_worker(service, worker)
        result.finished_at = datetime.now(timezone.utc).isoformat()
        logs.finish_log(handle, result)

    return result


# --------------------------------------------------------------------------- #
# Private helpers
# --------------------------------------------------------------------------- #


async def _obtain_worker(service: Any, coder: Any, wf: WorkflowConfig, source: str) -> Any:
    """Reuse a persistent ``wf:`` worker when possible, else spawn a new one."""

    if wf.persist:
        info = _find_reusable_worker(service, coder, wf)
        if info is not None:
            await _prepare_reused_worker(info, wf)
            return info.coder, info

    return await service.spawn(
        wf.agent_name,
        None,
        parent=coder,
        auto_reap=False,
        independent=(source == "scheduler_daemon"),
    )


async def _await_run(info: Any) -> Any:
    """Await the worker's generate task; returns ``(status, detail)``.

    There is deliberately no wall-clock cap: task success matters more than
    run duration, so a run is only ``aborted`` when the generate task is
    cancelled from outside (e.g. by ``SchedulerService.stop``). An external
    cancellation is reported rather than propagated, per the never-raise
    contract.
    """
    import asyncio

    from cecli.helpers.agents.service import SubAgentStatus

    try:
        await info.generate_task
    except asyncio.CancelledError:
        return "aborted", "run cancelled"
    except Exception as exc:
        return "error", str(exc) or exc.__class__.__name__

    if info.status == SubAgentStatus.ERROR:
        return "error", str(info.error or "")

    return "ok", ""


def _find_reusable_worker(service: Any, coder: Any, wf: WorkflowConfig) -> Any:
    """Return the run's persistent worker for *wf*, if one exists."""

    get_children = getattr(service, "get_children", None)
    if get_children is None:
        return None

    for info in reversed(get_children(coder)):
        if getattr(info, "name", None) != wf.agent_name:
            continue

        return info

    return None


async def _prepare_reused_worker(info: Any, wf: WorkflowConfig) -> None:
    """Wait for an in-flight run, then reset *info*'s conversation and queue."""
    import asyncio

    from cecli.helpers import command_queue
    from cecli.helpers.conversation.service import ConversationService

    task = getattr(info, "generate_task", None)
    if task is not None and not task.done():
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            # The reused worker is reset below regardless of how the prior run
            # ended; its outcome was already recorded by that run.
            pass

    worker = info.coder

    command_queue.clear_queue(worker)
    worker._queue_counter = 0
    worker._processing_queue = False
    worker._active_queue_prompt = None
    worker._drain_queue_after_command = False

    # File context belongs to the run that added it; start the next one with
    # the same empty file lists a freshly spawned worker would have.
    worker.abs_fnames = set()
    worker.abs_read_only_fnames = set()
    worker.abs_read_only_stubs_fnames = set()

    info.summary = None
    info.error = None
    info.cancel_requested = False
    info.auto_reap = False

    chunks = ConversationService.get_chunks(worker)
    chunks.flush_removals()
    ConversationService.get_manager(worker).reset()
    ConversationService.get_files(worker).reset()
    ConversationService.get_manager(worker).initialize(reformat=True)
    chunks.reset_clear_count()
    chunks.reset_message_tracker()
    chunks.add_system_message(_worker_prompt(wf))


def _worker_prompt(wf: WorkflowConfig) -> str:
    """System prompt of the registered ``wf:`` agent that runs *wf*."""
    from cecli.helpers.agents.service import AgentService

    config = AgentService.get_registry().get(wf.agent_name)
    return getattr(config, "prompt", "") or ""


def _task_results(wf, outcome, detail, executed_tail) -> List[TaskResult]:
    """Derive per-task outcomes from the overall run result and queue position."""
    results: List[TaskResult] = []
    failing_idx = _failing_index(executed_tail, len(wf.tasks))

    for idx, task in enumerate(wf.tasks):
        label = task.name or f"task-{idx + 1}"
        if outcome == "ok":
            results.append(TaskResult(index=idx, label=label, status="ok"))
        elif idx < failing_idx:
            results.append(TaskResult(index=idx, label=label, status="ok"))
        elif idx == failing_idx:
            results.append(TaskResult(index=idx, label=label, status=outcome, message=detail))
        else:
            results.append(TaskResult(index=idx, label=label, status="skipped"))

    return results


def _save_outputs(wf, result) -> None:
    """Persist the run summary to ``save_to`` output files (best-effort, never fatal)."""

    if not result.summary:
        return

    from cecli.helpers.workflows import outputs

    for idx, task in enumerate(wf.tasks):
        if not task.save_to:
            continue
        if idx >= len(result.tasks) or result.tasks[idx].status != "ok":
            continue

        try:
            path = outputs.save_output(
                wf.name,
                task.save_to,
                result.summary,
                run_id=result.run_id,
                started_at=result.started_at,
            )
            result.tasks[idx].message = f"saved to {path}"
        except Exception:
            logger.warning(
                "Failed to save save_to output for workflow '%s'", wf.name, exc_info=True
            )


def _reap_worker(service, worker) -> None:
    """Reap the run's worker coder (mirrors the /reap-agent teardown)."""
    from cecli.hooks.service import HookService

    try:
        HookService.destroy_instances(worker.uuid)
    except Exception:
        logger.warning("Failed to destroy workflow worker hooks", exc_info=True)

    try:
        if service is not None:
            service._cleanup_sub_agent(str(worker.uuid))
    except Exception:
        logger.warning("Failed to clean up workflow worker", exc_info=True)


_PLACEHOLDER_RE = re.compile(r"\{(date|workflow|run_id)\}")


def _expand(text: str, wf: WorkflowConfig, run_id: Optional[int] = None) -> str:
    """Expand ``{date}``, ``{workflow}`` and ``{run_id}`` placeholders.

    Environment variables are already interpolated at config-load time; this
    covers run-time placeholders only. Unknown braces are left verbatim.
    """
    values = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "workflow": wf.name,
        "run_id": "" if run_id is None else str(run_id),
    }

    return _PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1), m.group(0)), text)


def _failing_index(executed_tail: int, task_count: int) -> int:
    """Index of the task that ended the run, given how many tail tasks drained.

    The queue drains FIFO, so ``executed_tail`` tail prompts were dequeued and
    the deepest one still on the ``run_one`` stack when the failure surfaced is
    task ``executed_tail`` (0 — the first prompt — when nothing drained yet).
    """
    return max(0, min(executed_tail, task_count - 1))


def _should_stop(wf, failing_task) -> bool:
    """Whether remaining queued prompts should be dropped after a failure."""
    if failing_task is not None and failing_task.continue_on_error is not None:
        return not failing_task.continue_on_error

    return wf.on_failure == "stop"


def _save_session(worker, coder, wf, result) -> None:
    """Archive the worker's session payload into the run's outputs dir.

    Reuses the standard session machinery (payload format, encryption,
    directory creation), so a detached run is fully reviewable on disk
    without anything entering the parent's context.
    """

    try:
        from cecli.helpers.sessions.payload import build_payload
        from cecli.helpers.sessions.storage import write_payload
        from cecli.helpers.workflows import outputs

        path = outputs.run_output_dir(wf.name, result.run_id, result.started_at) / "session.json"
        payload = build_payload(worker, coder.io, f"workflow:{wf.name}", agent_name=wf.agent_name)
        write_payload(worker, coder.io, path, payload)
    except Exception:
        logger.warning("Failed to archive workflow session for '%s'", wf.name, exc_info=True)
