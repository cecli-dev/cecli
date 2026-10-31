"""Tests for execute_workflow (tests.md cases 18-24). No real LLM calls."""

import asyncio
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cecli.helpers import command_queue
from cecli.helpers.agents.service import SubAgentInfo, SubAgentStatus
from cecli.helpers.workflows.models import TaskConfig, WorkflowConfig
from cecli.helpers.workflows.runner import execute_workflow


@pytest.fixture(autouse=True)
def isolate_home(tmp_path, monkeypatch):
    """Keep run logs out of the real ~/.cecli."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return tmp_path


@pytest.fixture
def coder():
    c = MagicMock()
    c.uuid = "primary-uuid"
    return c


def make_worker():
    worker = MagicMock()
    worker.uuid = "worker-uuid"
    worker.prompt_queue = []
    worker._queue_counter = 0
    worker._queue_lock = threading.Lock()
    return worker


class FakeService:
    """AgentService stand-in: spawn + a scriptable generate task."""

    def __init__(self, worker, gen):
        self.worker = worker
        self.gen = gen
        self.calls = []
        self.info = SubAgentInfo(name="wf:demo", coder=worker, parent_uuid="primary-uuid")
        self.reaped = []

    async def spawn(self, name, prompt=None, parent=None, auto_reap=None, independent=False):
        self.calls.append(("spawn", name, prompt, parent, auto_reap, independent))
        return self.worker, self.info

    def start_generate_task(self, info, user_message):
        # snapshot of the queue at start proves enqueue-before-start ordering
        self.calls.append(
            (
                "start",
                user_message,
                command_queue.list_queue(info.coder),
                info.coder._drain_queue_after_command,
            )
        )
        info.status = SubAgentStatus.RUNNING

        async def _run():
            try:
                await self.gen(info)
            except asyncio.CancelledError:
                info.status = SubAgentStatus.FINISHED
                info.summary = "(interrupted)"
                raise
            except Exception as exc:
                info.status = SubAgentStatus.ERROR
                info.error = str(exc)
                raise

        info.generate_task = asyncio.create_task(_run())

    def _cleanup_sub_agent(self, uuid):
        self.reaped.append(uuid)


async def _execute(service, wf, coder, source="manual", run_id=None):
    with (
        patch(
            "cecli.helpers.workflows.subagents.register_workflow_subagents",
            return_value=[wf.agent_name],
        ),
        patch("cecli.helpers.agents.service.AgentService.get_instance", return_value=service),
        patch("cecli.hooks.service.HookService") as mock_hooks,
    ):
        result = await execute_workflow(coder, wf, source=source, run_id=run_id)
    service.mock_hooks = mock_hooks
    return result


def _wf(*tasks, **kwargs):
    kwargs.setdefault("name", "demo")
    return WorkflowConfig(tasks=list(tasks), **kwargs)


async def _drain(info):
    worker = info.coder
    while True:
        item = command_queue.dequeue_prompt(worker)
        if item is None:
            break
        info.coder.received.append(item["text"])
    info.status = SubAgentStatus.FINISHED
    info.summary = "all done"


# ---------------------------------------------------------------- case 18 --


@pytest.mark.asyncio
async def test_spawn_without_prompt_then_enqueue_then_start(coder):
    worker = make_worker()
    worker.received = []
    service = FakeService(worker, _drain)
    wf = _wf(
        TaskConfig(prompt="first"),
        TaskConfig(prompt="second"),
        TaskConfig(prompt="third"),
    )

    result = await _execute(service, wf, coder)

    # spawned with NO prompt, under the workflow's agent name, non-reaping
    assert service.calls[0] == ("spawn", "wf:demo", None, coder, False, False)

    # tasks[1:] were enqueued (in order) BEFORE the first generate started
    _, first_text, queue_at_start, drain_after_command = service.calls[1]
    assert first_text == "first"
    assert [item["text"] for item in queue_at_start] == ["second", "third"]
    assert drain_after_command is True
    assert result.status == "ok"
    assert [t.status for t in result.tasks] == ["ok", "ok", "ok"]


@pytest.mark.asyncio
async def test_command_first_task_drains_staged_queue(coder):
    """A workflow whose first task is a slash command must drain the rest."""
    worker = make_worker()
    worker.received = []
    service = FakeService(worker, _drain)
    wf = _wf(
        TaskConfig(prompt="/mcp load github"),
        TaskConfig(prompt="triage issues"),
    )

    result = await _execute(service, wf, coder)

    _, first_text, queue_at_start, drain_after_command = service.calls[1]
    assert first_text == "/mcp load github"
    assert [item["text"] for item in queue_at_start] == ["triage issues"]
    assert drain_after_command is True
    assert result.status == "ok"


# ---------------------------------------------------------------- case 19 --


@pytest.mark.asyncio
async def test_sequential_drain_order(coder):
    worker = make_worker()
    worker.received = []
    service = FakeService(worker, _drain)
    wf = _wf(
        TaskConfig(prompt="one"),
        TaskConfig(prompt="two"),
        TaskConfig(prompt="three"),
    )

    result = await _execute(service, wf, coder)

    received = [service.calls[1][1]] + worker.received
    assert received == ["one", "two", "three"]
    assert result.summary == "all done"
    assert result.finished_at and result.started_at


# ---------------------------------------------------------------- case 20 --


@pytest.mark.asyncio
async def test_task_timeouts_do_not_cap_the_run(coder):
    """Task success beats duration: per-task timeouts never abort a run."""
    worker = make_worker()
    worker.received = []

    async def slow(info):
        await asyncio.sleep(0.05)
        await _drain(info)

    service = FakeService(worker, slow)
    wf = _wf(
        TaskConfig(prompt="start", timeout=0.001),
        TaskConfig(prompt="queued", timeout=0.001),
    )

    result = await _execute(service, wf, coder)

    assert result.status == "ok"
    assert service.reaped == ["worker-uuid"]


# ---------------------------------------------------------------- case 21 --


@pytest.mark.asyncio
async def test_error_with_on_failure_stop_clears_queue(coder):
    worker = make_worker()
    worker.received = []

    async def boom(info):
        raise RuntimeError("hook aborted the step")

    service = FakeService(worker, boom)
    wf = _wf(TaskConfig(prompt="a"), TaskConfig(prompt="b"))  # on_failure defaults to stop

    result = await _execute(service, wf, coder)

    assert result.status == "error"
    assert "hook aborted" in result.error_message
    assert worker.prompt_queue == []
    assert [t.status for t in result.tasks] == ["error", "skipped"]


@pytest.mark.asyncio
async def test_error_with_on_failure_continue_keeps_queue(coder):
    worker = make_worker()
    worker.received = []

    async def boom(info):
        raise RuntimeError("nope")

    service = FakeService(worker, boom)
    wf = _wf(
        TaskConfig(prompt="a"),
        TaskConfig(prompt="b"),
        on_failure="continue",
    )

    result = await _execute(service, wf, coder)

    assert result.status == "error"
    # the drain is *not* cancelled: remaining prompts stay queued
    assert [item["text"] for item in worker.prompt_queue] == ["b"]


@pytest.mark.asyncio
async def test_per_task_continue_on_error_overrides_stop(coder):
    worker = make_worker()
    worker.received = []

    async def boom(info):
        raise RuntimeError("nope")

    service = FakeService(worker, boom)
    wf = _wf(
        TaskConfig(prompt="a", continue_on_error=True),
        TaskConfig(prompt="b"),
        on_failure="stop",
    )

    result = await _execute(service, wf, coder)

    assert result.status == "error"
    assert len(worker.prompt_queue) == 1


# ---------------------------------------------------------------- case 22 --


@pytest.mark.asyncio
async def test_save_to_writes_persistent_output_file(coder, isolate_home):
    worker = make_worker()
    worker.received = []
    service = FakeService(worker, _drain)
    wf = _wf(TaskConfig(prompt="summarize", save_to="pipeline_summary"))

    result = await _execute(service, wf, coder)

    assert result.status == "ok"
    path = Path(result.tasks[0].message.split("saved to ", 1)[1])
    assert path.is_relative_to(isolate_home / ".cecli" / "workflows" / "outputs" / "demo")
    assert path.name == "pipeline_summary"
    assert path.read_text(encoding="utf-8") == "all done"


@pytest.mark.asyncio
async def test_save_to_path_is_logged(coder):
    worker = make_worker()
    worker.received = []
    service = FakeService(worker, _drain)
    wf = _wf(TaskConfig(prompt="keep", save_to="notes.md"))

    result = await _execute(service, wf, coder, run_id=7)

    from cecli.helpers.workflows.logs import read_log_lines

    task_lines = [e for e in read_log_lines(result.log_path) if e.get("event") == "task"]
    assert "saved to" in task_lines[0]["message"]
    assert "run-7" in task_lines[0]["message"]


@pytest.mark.asyncio
async def test_save_to_failure_is_not_fatal(coder):
    worker = make_worker()
    worker.received = []
    service = FakeService(worker, _drain)
    wf = _wf(TaskConfig(prompt="x", save_to="note"))

    with patch(
        "cecli.helpers.workflows.outputs.save_output", side_effect=RuntimeError("disk full")
    ):
        result = await _execute(service, wf, coder)

    assert result.status == "ok"


# ---------------------------------------------------------------- case 23 --


@pytest.mark.asyncio
async def test_placeholders_expanded_before_enqueue(coder):
    from datetime import datetime

    worker = make_worker()
    worker.received = []
    service = FakeService(worker, _drain)
    wf = _wf(
        TaskConfig(prompt="report for {date} ({workflow})"),
        TaskConfig(prompt="run {run_id} of {workflow}"),
    )

    await _execute(service, wf, coder, run_id=42)

    today = datetime.now().strftime("%Y-%m-%d")
    first = service.calls[1][1]
    assert today in first and "demo" in first and "{" not in first
    assert worker.received == ["run 42 of demo"]


# ---------------------------------------------------------------- case 24 --


@pytest.mark.asyncio
async def test_source_recorded_and_logged(coder, isolate_home):
    worker = make_worker()
    worker.received = []
    service = FakeService(worker, _drain)
    wf = _wf(TaskConfig(prompt="tick"))

    result = await _execute(service, wf, coder, source="scheduler")

    assert result.source == "scheduler"
    assert result.log_path

    from cecli.helpers.workflows.logs import read_log_lines

    lines = read_log_lines(result.log_path)
    events = [line["event"] for line in lines]
    assert events[0] == "start"
    assert "task" in events
    assert events[-1] == "finish"
    assert lines[-1]["status"] == "ok"
    assert "definition_hash" in lines[0]


@pytest.mark.asyncio
async def test_unexpected_failure_returns_error_result(coder):
    service = MagicMock()
    service.spawn = MagicMock(side_effect=ValueError("Unknown sub-agent"))

    with (
        patch("cecli.helpers.workflows.subagents.register_workflow_subagents"),
        patch("cecli.helpers.agents.service.AgentService.get_instance", return_value=service),
        patch("cecli.hooks.service.HookService"),
    ):
        result = await execute_workflow(coder, _wf(TaskConfig(prompt="x")))

    assert result.status == "error"
    assert "Unknown sub-agent" in result.error_message


@pytest.mark.asyncio
async def test_worker_session_archived_to_run_outputs(coder):
    worker = make_worker()
    worker.received = []

    service = FakeService(worker, _drain)
    wf = _wf(TaskConfig(prompt="x"))

    with (
        patch("cecli.helpers.sessions.payload.build_payload", return_value={"ok": True}) as bp,
        patch("cecli.helpers.sessions.storage.write_payload", return_value=True) as wp,
    ):
        result = await _execute(service, wf, coder, run_id=4)

    assert result.status == "ok"
    bp.assert_called_once()
    assert bp.call_args.kwargs.get("agent_name") == "wf:demo"
    path = wp.call_args.args[2]
    assert path.name == "session.json"
    assert path.parent.name == "run-4"


@pytest.mark.asyncio
async def test_session_archive_failure_is_not_fatal(coder):
    worker = make_worker()
    worker.received = []

    service = FakeService(worker, _drain)
    wf = _wf(TaskConfig(prompt="x"))

    with patch(
        "cecli.helpers.sessions.payload.build_payload",
        side_effect=RuntimeError("no conversation"),
    ):
        result = await _execute(service, wf, coder)

    assert result.status == "ok"
