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

import asyncio
import logging
import re
from datetime import datetime, timezone
from types import MappingProxyType
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

        worker, info = await _obtain_worker(service, coder, wf, source)
        steps = _step_map(wf, texts)
        _stage_steps(worker, wf, steps)

        state = {"statuses": {}, "last_error": ""}
        info.generate_task = asyncio.create_task(
            _drive_steps(service, worker, info, wf, steps, state)
        )

        try:
            outcome, detail = await _await_run(info)
        finally:
            command_queue.clear_active_prompt(worker)

        if outcome == "ok" and state["last_error"]:
            outcome, detail = "error", state["last_error"]

        statuses = state["statuses"]
        failing = _failing_task(wf, statuses)

        if outcome != "ok" and _should_stop(wf, failing):
            command_queue.clear_queue(worker)

        result.status = outcome
        if outcome != "ok":
            result.error_message = detail if outcome == "error" else ""

        # Keep the abort reason (e.g. cancelled) as the summary unless
        # the worker actually produced one before dying.
        if outcome != "aborted" or info.summary:
            result.summary = info.summary or ""
        result.tasks = _task_results(wf, statuses, outcome, detail)

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
            worker = getattr(info, "coder", None) or worker
            record = getattr(worker, "worktree", None)
            if record is not None:
                to_dict = getattr(record, "to_dict", None)
                result.worktree = to_dict() if callable(to_dict) else record

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
    worker._active_queue_index = None
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


def _task_results(wf, statuses, outcome, detail) -> List[TaskResult]:
    """Build one result per declared task from the steps that actually ran."""
    results: List[TaskResult] = []

    for idx, task in enumerate(wf.tasks):
        label = task.name or f"task-{idx + 1}"
        status, message = statuses.get(label, ("skipped", ""))
        results.append(TaskResult(index=idx, label=label, status=status, message=message))

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


def _step_map(wf: WorkflowConfig, texts: List[str]) -> dict:
    """Return the ordered ``{step name: original prompt}`` map for a run."""
    steps = {}

    for index, (task, text) in enumerate(zip(wf.tasks, texts), start=1):
        name = task.name or f"task-{index}"
        if name in steps:
            logger.warning(
                "workflow '%s' has duplicate step name '%s'; the later definition wins",
                wf.name,
                name,
            )
        steps[name] = text

    return steps


def _stage_steps(worker, wf: WorkflowConfig, steps: dict) -> None:
    """Load every step into the worker's prompt queue in definition order."""
    from cecli.helpers import command_queue

    for name, prompt in steps.items():
        command_queue.enqueue_prompt(worker, prompt, metadata={"workflow": wf.name, "step": name})


async def _drive_steps(service, worker, info, wf: WorkflowConfig, steps: dict, state: dict) -> None:
    """Drain the step queue, running each step's ``post_run`` hook afterwards."""
    import asyncio

    from cecli.commands import SwitchCoderSignal
    from cecli.helpers import command_queue
    from cecli.helpers.agents.service import (
        DEFAULT_SUMMARY_INTERRUPTED,
        SubAgentStatus,
    )
    from cecli.helpers.workflows.hooks import WorkflowRunContext, run_task_hooks

    statuses = state["statuses"]
    info.status = SubAgentStatus.RUNNING
    info.cancel_requested = False
    # run_one() drains the queue itself at the end of every prompt. Keeping this
    # flag set lets the runner own the queue and run hooks between steps.
    worker._processing_queue = True

    try:
        while True:
            item = command_queue.dequeue_prompt(worker)
            if item is None:
                break

            metadata = item.get("metadata") or {}
            name = metadata.get("step") or ""
            task = _task_for_step(wf, name)
            prompt = item["text"]
            status, message = "ok", ""

            try:
                await worker.generate(prompt, preproc=True)
            except SwitchCoderSignal as switch:
                old_coder = worker
                worker = await service.switch_sub_agent_coder(
                    info, switch, preproc=True, drain=False
                )
                old_coder._processing_queue = False
                worker._processing_queue = True
            except asyncio.CancelledError:
                statuses[name] = ("aborted", "run cancelled")
                raise
            except Exception as exc:
                status, message = "error", str(exc) or exc.__class__.__name__
                state["last_error"] = message

            statuses[name] = (status, message)

            context = WorkflowRunContext(
                coder=worker,
                workflow=wf,
                task=task,
                steps=MappingProxyType(dict(steps)),
                step_name=name,
                prompt=prompt,
                status=status,
                error=message or None,
            )
            directive = await run_task_hooks(worker, context)

            if directive is False:
                command_queue.clear_queue(worker)
                break

            if isinstance(directive, tuple):
                _jump(worker, wf, steps, directive[0], directive[1])
                continue

            if status == "error" and _should_stop(wf, task):
                command_queue.clear_queue(worker)
                break

        if info.status == SubAgentStatus.RUNNING:
            info.status = SubAgentStatus.FINISHED
            info.summary = info.summary or _fallback_summary(worker)
    except asyncio.CancelledError:
        info.status = SubAgentStatus.FINISHED
        info.summary = info.summary or DEFAULT_SUMMARY_INTERRUPTED
        raise
    except Exception as exc:
        info.status = SubAgentStatus.ERROR
        info.error = str(exc) or exc.__class__.__name__
        raise
    finally:
        worker._processing_queue = False


def _jump(worker, wf: WorkflowConfig, steps: dict, target: str, prompt) -> None:
    """Replace the remaining queue with *target* and the steps after it."""
    from cecli.helpers import command_queue

    names = list(steps)
    if target not in steps:
        logger.warning(
            "workflow '%s' hook jumped to unknown step '%s'; continuing normally",
            wf.name,
            target,
        )
        return

    command_queue.clear_queue(worker)
    for name in names[names.index(target) :]:
        text = prompt if name == target and prompt is not None else steps[name]
        command_queue.enqueue_prompt(worker, text, metadata={"workflow": wf.name, "step": name})


def _task_for_step(wf: WorkflowConfig, name: str):
    """Return the declared task whose step name is *name*."""
    for index, task in enumerate(wf.tasks, start=1):
        if (task.name or f"task-{index}") == name:
            return task

    return None


def _failing_task(wf: WorkflowConfig, statuses: dict):
    """Return the last task that finished with an error or abort status."""
    for index in range(len(wf.tasks), 0, -1):
        task = wf.tasks[index - 1]
        name = task.name or f"task-{index}"
        if statuses.get(name, ("skipped", ""))[0] in ("error", "aborted"):
            return task

    return None


def _fallback_summary(worker) -> str:
    """Use the worker's last response as the summary when it yielded none."""
    content = getattr(worker, "partial_response_content", None)
    if isinstance(content, str) and content.strip():
        return content.strip()

    return "(completed without explicit summary)"


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
