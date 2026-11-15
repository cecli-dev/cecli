"""Tests for execute_workflow and per-step post_run routing. No real LLM calls."""

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cecli.helpers.agents.service import SubAgentInfo, SubAgentStatus
from cecli.helpers.workflows.models import TaskConfig, WorkflowConfig
from cecli.helpers.workflows.runner import execute_workflow
from cecli.signals import SwitchCoderSignal


def jump_to_end(coder, context):
    return context.jump("end")


def jump_to_middle(coder, context):
    return context.jump("middle", "OVERRIDE")


def stop_after_middle(coder, context):
    return False


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


def make_worker(raise_on=None, switch_on=None, summary="all done"):
    worker = MagicMock()
    worker.uuid = "worker-uuid"
    worker.prompt_queue = []
    worker._queue_counter = 0
    worker._queue_lock = threading.Lock()
    worker.worktree = None
    worker.received = []
    worker.partial_response_content = summary

    async def _generate(prompt, preproc=True):
        worker.received.append(prompt)
        if switch_on is not None and switch_on == prompt:
            raise SwitchCoderSignal(prompt=prompt)
        if raise_on == prompt:
            raise RuntimeError(f"boom: {prompt}")

    worker.generate = _generate
    return worker


class FakeService:
    """AgentService stand-in: spawn, children and cleanup only."""

    def __init__(self, worker):
        self.worker = worker
        self.calls = []
        self.info = SubAgentInfo(name="wf:demo", coder=worker, parent_uuid="primary-uuid")
        self.sub_agents = {}
        self.children = []
        self.reaped = []

    async def spawn(self, name, prompt=None, parent=None, auto_reap=None, independent=False):
        self.calls.append(("spawn", name, prompt, parent, auto_reap, independent))
        return self.worker, self.info

    def get_children(self, coder):
        return list(self.children)

    async def switch_sub_agent_coder(self, info, switch, preproc=True, drain=True):
        old = info.coder
        new = make_worker(summary=old.partial_response_content)
        new.uuid = f"worker-{len(self.sub_agents) + 2}"
        new.prompt_queue = list(old.prompt_queue)
        new._queue_counter = old._queue_counter
        old.prompt_queue.clear()
        info.coder = new
        self.sub_agents[new.uuid] = info
        self.worker = new
        self.new_worker = new
        self.switched = getattr(self, "switched", 0) + 1
        assert drain is False
        return new

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


@pytest.mark.asyncio
async def test_spawn_without_prompt_and_run_in_order(coder):
    worker = make_worker()
    service = FakeService(worker)
    wf = _wf(
        TaskConfig(prompt="first", name="first"),
        TaskConfig(prompt="second", name="second"),
        TaskConfig(prompt="third", name="third"),
    )

    result = await _execute(service, wf, coder)

    assert service.calls[0] == ("spawn", "wf:demo", None, coder, False, False)
    assert worker.received == ["first", "second", "third"]
    assert worker.prompt_queue == []
    assert result.status == "ok"
    assert [t.status for t in result.tasks] == ["ok", "ok", "ok"]


@pytest.mark.asyncio
async def test_command_task_does_not_stall_the_queue(coder):
    worker = make_worker()
    service = FakeService(worker)
    wf = _wf(
        TaskConfig(prompt="/mcp load github"),
        TaskConfig(prompt="triage issues"),
    )

    result = await _execute(service, wf, coder)

    assert worker.received == ["/mcp load github", "triage issues"]
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_summary_and_timestamps(coder):
    worker = make_worker()
    service = FakeService(worker)

    result = await _execute(service, _wf(TaskConfig(prompt="x")), coder)

    assert result.summary == "all done"
    assert result.finished_at and result.started_at
    assert service.reaped == ["worker-uuid"]


@pytest.mark.asyncio
async def test_error_with_on_failure_stop_skips_remaining(coder):
    worker = make_worker(raise_on="a")
    service = FakeService(worker)
    wf = _wf(TaskConfig(prompt="a"), TaskConfig(prompt="b"))  # on_failure defaults to stop

    result = await _execute(service, wf, coder)

    assert result.status == "error"
    assert "boom: a" in result.error_message
    assert worker.prompt_queue == []
    assert worker.received == ["a"]
    assert [t.status for t in result.tasks] == ["error", "skipped"]


@pytest.mark.asyncio
async def test_error_with_on_failure_continue_runs_remaining(coder):
    worker = make_worker(raise_on="a")
    service = FakeService(worker)
    wf = _wf(TaskConfig(prompt="a"), TaskConfig(prompt="b"), on_failure="continue")

    result = await _execute(service, wf, coder)

    assert result.status == "error"
    assert worker.received == ["a", "b"]
    assert [t.status for t in result.tasks] == ["error", "ok"]


@pytest.mark.asyncio
async def test_per_task_continue_on_error_overrides_stop(coder):
    worker = make_worker(raise_on="a")
    service = FakeService(worker)
    wf = _wf(
        TaskConfig(prompt="a", continue_on_error=True),
        TaskConfig(prompt="b"),
        on_failure="stop",
    )

    result = await _execute(service, wf, coder)

    assert result.status == "error"
    assert worker.received == ["a", "b"]


@pytest.mark.asyncio
async def test_post_run_can_jump_forward(coder):
    worker = make_worker()
    service = FakeService(worker)
    wf = _wf(
        TaskConfig(prompt="start", name="start", post_run="%s:jump_to_end" % __name__),
        TaskConfig(prompt="middle", name="middle"),
        TaskConfig(prompt="end", name="end"),
    )

    result = await _execute(service, wf, coder)

    assert worker.received == ["start", "end"]
    assert [t.status for t in result.tasks] == ["ok", "skipped", "ok"]
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_post_run_jump_can_replace_the_next_prompt(coder):
    worker = make_worker()
    service = FakeService(worker)
    wf = _wf(
        TaskConfig(prompt="start", name="start", post_run=jump_to_middle),
        TaskConfig(prompt="middle", name="middle"),
        TaskConfig(prompt="end", name="end"),
    )

    await _execute(service, wf, coder)

    assert worker.received == ["start", "OVERRIDE", "end"]


@pytest.mark.asyncio
async def test_post_run_can_loop_back(coder):
    looped = []

    def loop_start_once(coder, context):
        if not looped:
            looped.append(True)
            return context.jump("start", "again")

        return True

    worker = make_worker()
    service = FakeService(worker)
    wf = _wf(
        TaskConfig(prompt="start", name="start", post_run=loop_start_once),
        TaskConfig(prompt="middle", name="middle"),
        TaskConfig(prompt="end", name="end"),
    )

    await _execute(service, wf, coder)

    assert worker.received == ["start", "again", "middle", "end"]


@pytest.mark.asyncio
async def test_post_run_false_stops_processing(coder):
    worker = make_worker()
    service = FakeService(worker)
    wf = _wf(
        TaskConfig(prompt="start", name="start"),
        TaskConfig(prompt="middle", name="middle", post_run=stop_after_middle),
        TaskConfig(prompt="end", name="end"),
    )

    result = await _execute(service, wf, coder)

    assert worker.received == ["start", "middle"]
    assert worker.prompt_queue == []
    assert [t.status for t in result.tasks] == ["ok", "ok", "skipped"]
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_unknown_jump_target_continues_normally(coder):
    worker = make_worker()
    service = FakeService(worker)
    wf = _wf(
        TaskConfig(prompt="start", name="start", post_run=lambda c, ctx: ctx.jump("nope")),
        TaskConfig(prompt="end", name="end"),
    )

    await _execute(service, wf, coder)

    assert worker.received == ["start", "end"]


@pytest.mark.asyncio
async def test_save_to_writes_persistent_output_file(coder, isolate_home):
    worker = make_worker()
    service = FakeService(worker)
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
    service = FakeService(worker)
    wf = _wf(TaskConfig(prompt="keep", save_to="notes.md"))

    result = await _execute(service, wf, coder, run_id=7)

    from cecli.helpers.workflows.logs import read_log_lines

    task_lines = [e for e in read_log_lines(result.log_path) if e.get("event") == "task"]
    assert "saved to" in task_lines[0]["message"]
    assert "run-7" in task_lines[0]["message"]


@pytest.mark.asyncio
async def test_save_to_failure_is_not_fatal(coder):
    worker = make_worker()
    service = FakeService(worker)
    wf = _wf(TaskConfig(prompt="x", save_to="note"))

    with patch(
        "cecli.helpers.workflows.outputs.save_output", side_effect=RuntimeError("disk full")
    ):
        result = await _execute(service, wf, coder)

    assert result.status == "ok"


@pytest.mark.asyncio
async def test_placeholders_expanded_before_queuing(coder):
    from datetime import datetime

    worker = make_worker()
    service = FakeService(worker)
    wf = _wf(
        TaskConfig(prompt="report for {date} ({workflow})"),
        TaskConfig(prompt="run {run_id} of {workflow}"),
    )

    await _execute(service, wf, coder, run_id=42)

    today = datetime.now().strftime("%Y-%m-%d")
    first, second = worker.received
    assert today in first and "demo" in first and "{" not in first
    assert second == "run 42 of demo"


@pytest.mark.asyncio
async def test_source_recorded_and_logged(coder, isolate_home):
    worker = make_worker()
    service = FakeService(worker)

    result = await _execute(service, _wf(TaskConfig(prompt="tick")), coder, source="scheduler")

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
    service = FakeService(worker)

    with (
        patch("cecli.helpers.sessions.payload.build_payload", return_value={"ok": True}) as bp,
        patch("cecli.helpers.sessions.storage.write_payload", return_value=True) as wp,
    ):
        result = await _execute(service, _wf(TaskConfig(prompt="x")), coder, run_id=4)

    assert result.status == "ok"
    bp.assert_called_once()
    assert bp.call_args.kwargs.get("agent_name") == "wf:demo"
    path = wp.call_args.args[2]
    assert path.name == "session.json"
    assert path.parent.name == "run-4"


@pytest.mark.asyncio
async def test_session_archive_failure_is_not_fatal(coder):
    worker = make_worker()
    service = FakeService(worker)

    with patch(
        "cecli.helpers.sessions.payload.build_payload",
        side_effect=RuntimeError("no conversation"),
    ):
        result = await _execute(service, _wf(TaskConfig(prompt="x")), coder)

    assert result.status == "ok"


@pytest.mark.asyncio
async def test_persist_worker_is_not_reaped(coder):
    worker = make_worker()
    service = FakeService(worker)

    result = await _execute(service, _wf(TaskConfig(prompt="x"), persist=True), coder)

    assert result.status == "ok"
    assert service.reaped == []


@pytest.mark.asyncio
async def test_persist_reuses_existing_worker(coder):
    existing = make_worker()
    existing.prompt_queue = [{"id": "1", "text": "stale", "timestamp": 0}]
    info = SubAgentInfo(
        name="wf:demo",
        coder=existing,
        parent_uuid="primary-uuid",
        status=SubAgentStatus.FINISHED,
    )

    service = FakeService(make_worker())
    service.children = [info]
    wf = _wf(TaskConfig(prompt="fresh"), TaskConfig(prompt="tail"), persist=True)

    with (
        patch("cecli.helpers.conversation.service.ConversationService.get_chunks") as get_chunks,
        patch("cecli.helpers.conversation.service.ConversationService.get_manager") as get_manager,
        patch("cecli.helpers.conversation.service.ConversationService.get_files") as get_files,
    ):
        result = await _execute(service, wf, coder)

    assert result.status == "ok"
    assert not any(call[0] == "spawn" for call in service.calls)
    assert existing.received == ["fresh", "tail"]
    assert existing.prompt_queue == []
    get_manager.return_value.reset.assert_called_once()
    get_manager.return_value.initialize.assert_called_once()
    get_files.return_value.reset.assert_called_once()
    get_chunks.return_value.add_system_message.assert_called_once()
    assert service.reaped == []


@pytest.mark.asyncio
async def test_worktree_recorded_and_logged(coder):
    worker = make_worker()

    class Record:
        def to_dict(self):
            return {"branch": "cecli/wf-demo-1234", "path": "/tmp/wt"}

    worker.worktree = Record()
    service = FakeService(worker)

    result = await _execute(service, _wf(TaskConfig(prompt="x")), coder)

    assert result.worktree == {"branch": "cecli/wf-demo-1234", "path": "/tmp/wt"}

    from cecli.helpers.workflows.logs import read_log_lines

    finish = [e for e in read_log_lines(result.log_path) if e.get("event") == "finish"][-1]
    assert finish["worktree"] == result.worktree


@pytest.mark.asyncio
async def test_switch_coder_mid_run_preserves_remaining_queue(coder):
    worker = make_worker(switch_on="start")
    service = FakeService(worker)
    wf = _wf(
        TaskConfig(prompt="start", name="start"),
        TaskConfig(prompt="middle", name="middle"),
        TaskConfig(prompt="end", name="end"),
    )

    result = await _execute(service, wf, coder)

    assert result.status == "ok"
    assert service.switched == 1
    assert worker.received == ["start"]
    assert service.new_worker.received == ["middle", "end"]
    assert service.new_worker.prompt_queue == []
    assert [t.status for t in result.tasks] == ["ok", "ok", "ok"]
