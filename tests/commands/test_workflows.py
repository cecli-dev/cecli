"""Tests for the /workflows command (tests.md cases 25-29)."""

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cecli.commands import CommandRegistry, Commands
from cecli.commands.workflows import WorkflowCommand
from cecli.helpers.workflows.models import TaskConfig, WorkflowConfig


@pytest.fixture
def mock_coder():
    coder = MagicMock()
    coder.uuid = "primary-uuid"
    coder.tui = None
    coder.scheduler = None
    return coder


@pytest.fixture
def mock_io():
    return MagicMock()


def _wf(name="demo", enabled=True, schedule=None, **kwargs):
    kwargs.setdefault("tasks", [TaskConfig(prompt="do it")])
    return WorkflowConfig(name=name, enabled=enabled, schedule=schedule, **kwargs)


def _coder_with(*wfs, scheduler=None):
    coder = MagicMock()
    coder.uuid = "primary-uuid"
    coder.tui = None
    coder.workflows = list(wfs)
    coder.scheduler = scheduler
    return coder


# ---------------------------------------------------------------- case 25 --


@pytest.mark.asyncio
async def test_list_shows_enabled_and_disabled_with_schedules(mock_io):
    coder = _coder_with(
        _wf("nightly", schedule="0 3 * * *", description="Nightly sweep"),
        _wf("old", enabled=False),
    )

    await WorkflowCommand.execute(mock_io, coder, "list")

    out = "\n".join(call.args[0] for call in coder_output_calls(mock_io))
    assert "nightly [enabled]" in out
    assert "schedule: 0 3 * * *" in out
    assert "old [disabled]" in out
    assert "schedule: manual" in out
    assert "Nightly sweep" in out


def coder_output_calls(mock_io):
    return list(mock_io.print.call_args_list) + list(mock_io.tool_output.call_args_list)


@pytest.mark.asyncio
async def test_list_without_workflows(mock_coder, mock_io):
    mock_coder.workflows = []
    with patch("cecli.helpers.workflows.subagents.get_workflow_configs", return_value=[]):
        await WorkflowCommand.execute(mock_io, mock_coder, "list")
    assert any("No workflows" in str(c) for c in coder_output_calls(mock_io))


# ---------------------------------------------------------------- case 26 --


@pytest.mark.asyncio
async def test_run_starts_background_task(mock_io):
    coder = _coder_with(_wf("demo"))
    with (
        patch("cecli.commands.workflow_helpers.run.asyncio.create_task") as mock_create,
        patch("cecli.helpers.workflows.runner.execute_workflow") as mock_exec,
    ):
        # the create_task stub closes the (already-recorded) coroutine so the
        # AsyncMock's never-awaited warning doesn't fire
        mock_create.side_effect = lambda coro: (coro.close(), MagicMock())[1]
        await WorkflowCommand.execute(mock_io, coder, "run demo")
    with (
        patch("cecli.commands.workflow_helpers.run.asyncio.create_task") as mock_create,
        patch("cecli.helpers.workflows.runner.execute_workflow", new=MagicMock()) as mock_exec,
    ):
        await WorkflowCommand.execute(mock_io, coder, "run demo")

    mock_create.assert_called_once()
    mock_exec.assert_called_once_with(coder, coder.workflows[0], source="manual")
    assert "started" in mock_io.tool_output.call_args.args[0]


@pytest.mark.asyncio
async def test_run_reports_completion_and_releases_task_ref(mock_io):
    """Reviewer MUST-FIX 2: the background run must survive (strong ref) and
    announce its summary in the conversation when done."""
    from cecli.commands.workflow_helpers import run as run_module
    from cecli.helpers.workflows.models import RunResult

    run_module._bg_runs.clear()
    coder = _coder_with(_wf("demo"))
    finished = RunResult(name="demo", status="ok", summary="all good")

    async def fake_exec(coder_, wf_, *, source="manual", run_id=None):
        return finished

    with patch("cecli.helpers.workflows.runner.execute_workflow", new=fake_exec):
        await WorkflowCommand.execute(mock_io, coder, "run demo")

        for _ in range(10):  # let the task and its done-callback run
            await asyncio.sleep(0)

    out = "\n".join(str(c.args[0]) for c in mock_io.tool_output.call_args_list)
    assert "started in the background" in out
    assert "finished: ok" in out
    assert "all good" in out
    assert not run_module._bg_runs  # reference released by the done-callback


@pytest.mark.asyncio
async def test_run_reports_error_status_via_tool_error(mock_io):
    from cecli.commands.workflow_helpers import run as run_module
    from cecli.helpers.workflows.models import RunResult

    run_module._bg_runs.clear()
    coder = _coder_with(_wf("demo"))
    bad = RunResult(name="demo", status="error", error_message="boom", summary="boom")

    async def fake_exec(coder_, wf_, *, source="manual", run_id=None):
        return bad

    with patch("cecli.helpers.workflows.runner.execute_workflow", new=fake_exec):
        await WorkflowCommand.execute(mock_io, coder, "run demo")
        for _ in range(10):
            await asyncio.sleep(0)

    err = "\n".join(str(c.args[0]) for c in mock_io.tool_error.call_args_list)
    assert "finished: error" in err
    assert not run_module._bg_runs


@pytest.mark.asyncio
async def test_run_unknown_name_errors_with_valid_names(mock_io):
    coder = _coder_with(_wf("demo"), _wf("other"))

    await WorkflowCommand.execute(mock_io, coder, "run nope")

    mock_io.tool_error.assert_called_once()
    message = mock_io.tool_error.call_args.args[0]
    assert "nope" in message
    assert "demo" in message and "other" in message


# ---------------------------------------------------------------- case 27 --


@pytest.mark.asyncio
async def test_show_dumps_yaml(mock_io):
    import yaml

    wf = _wf("demo", skills=["a"], tasks=[TaskConfig(prompt="p1"), TaskConfig(prompt="p2")])
    coder = _coder_with(wf)

    await WorkflowCommand.execute(mock_io, coder, "show demo")

    dumped = yaml.safe_load(mock_io.tool_output.call_args.args[0])
    assert dumped == wf.to_dict()


@pytest.mark.asyncio
async def test_status_uses_scheduler_db_when_present(mock_io):
    row = {
        "name": "demo",
        "enabled": 1,
        "engine": "cron",
        "next_run": "2026-10-11T03:00:00.000Z",
        "last_run": "2026-10-10T03:00:00.000Z",
        "last_status": "ok",
    }
    db = MagicMock()
    db.list_jobs = AsyncMock(return_value=[row])
    scheduler = MagicMock()
    scheduler.db = db
    coder = _coder_with(_wf("demo", schedule="0 3 * * *"), scheduler=scheduler)

    await WorkflowCommand.execute(mock_io, coder, "status")

    out = "\n".join(call.args[0] for call in coder_output_calls(mock_io))
    assert "Scheduler jobs:" in out
    assert "next_run=2026-10-11T03:00:00.000Z" in out
    assert "last_run=2026-10-10T03:00:00.000Z" in out


@pytest.mark.asyncio
async def test_status_without_scheduler_degrades_to_config(mock_io):
    coder = _coder_with(_wf("demo", schedule="0 3 * * *"))

    await WorkflowCommand.execute(mock_io, coder, "status")

    out = "\n".join(call.args[0] for call in coder_output_calls(mock_io))
    assert "demo [enabled]" in out
    assert "scheduler not running" in out


@pytest.mark.asyncio
async def test_last_reads_scheduler_row_then_log(mock_io):
    db = MagicMock()
    db.recent_runs = AsyncMock(
        return_value=[
            {
                "name": "demo",
                "status": "ok",
                "source": "scheduler",
                "summary": "no errors",
                "finished_at": "2026-10-10T03:01:00.000Z",
            }
        ]
    )
    scheduler = MagicMock()
    scheduler.db = db
    coder = _coder_with(_wf("demo"), scheduler=scheduler)

    await WorkflowCommand.execute(mock_io, coder, "last demo")
    out = "\n".join(call.args[0] for call in coder_output_calls(mock_io))
    assert "Status:  ok" in out
    assert "no errors" in out

    # no scheduler -> falls back to the newest run log
    coder2 = _coder_with(_wf("demo"))
    lines = [
        {"event": "start", "definition_hash": "abc"},
        {"event": "task", "idx": 0, "label": "task-1", "status": "error"},
        {"event": "finish", "status": "error", "source": "manual", "summary": ""},
    ]
    with (
        patch("cecli.helpers.workflows.logs.latest_log_path", return_value="/tmp/x.jsonl"),
        patch("cecli.helpers.workflows.logs.read_log_lines", return_value=lines),
    ):
        await WorkflowCommand.execute(mock_io, coder2, "last demo")
    out = "\n".join(call.args[0] for call in coder_output_calls(mock_io))
    assert "Status:  error" in out
    assert "task[0] task-1: error" in out


@pytest.mark.asyncio
async def test_last_unknown_is_reported(mock_io):
    coder = _coder_with(_wf("demo"))
    with patch("cecli.helpers.workflows.logs.latest_log_path", return_value=None):
        await WorkflowCommand.execute(mock_io, coder, "last ghost")
    assert any("No recorded runs" in str(c) for c in coder_output_calls(mock_io))


@pytest.mark.asyncio
async def test_enable_disable_flip_and_sync(mock_io):
    from cecli.helpers.workflows import subagents as wf_subagents

    wf = _wf("demo")
    coder = _coder_with(wf)

    with (
        patch.object(
            wf_subagents, "unregister_workflow_subagents", return_value=["wf:demo"]
        ) as unreg,
        patch.object(wf_subagents, "register_workflow_subagents", return_value=["wf:demo"]) as reg,
    ):
        await WorkflowCommand.execute(mock_io, coder, "disable demo")
        assert wf.enabled is False
        unreg.assert_called_once_with([wf])

        await WorkflowCommand.execute(mock_io, coder, "enable demo")
        assert wf.enabled is True
        reg.assert_called_once_with([wf])

    assert "disabled" in mock_io.tool_output.call_args_list[0].args[0]
    assert "enabled" in mock_io.tool_output.call_args_list[1].args[0]


@pytest.mark.asyncio
async def test_reload_reregisters_and_keeps_cached_names(mock_io):
    import cecli.helpers.workflows.config as wf_config

    from_file = _wf("from-file")
    cached = _wf("inline-only")
    coder = _coder_with(cached)

    real_config = wf_config
    stub = types.ModuleType("cecli.helpers.workflows.config")
    stub.load_workflows = MagicMock(return_value=[from_file])
    sys.modules["cecli.helpers.workflows.config"] = stub
    try:
        with (
            patch("cecli.helpers.workflows.subagents.get_workflow_configs", return_value=[cached]),
            patch(
                "cecli.helpers.workflows.subagents.unregister_workflow_subagents",
                return_value=["wf:inline-only"],
            ),
            patch(
                "cecli.helpers.workflows.subagents.register_workflow_subagents",
                return_value=["wf:from-file"],
            ) as reg,
        ):
            await WorkflowCommand.execute(mock_io, coder, "reload")
    finally:
        if real_config is not None:
            sys.modules["cecli.helpers.workflows.config"] = real_config

    registered = reg.call_args.args[0]
    assert {w.name for w in registered} == {"from-file", "inline-only"}
    assert "Reloaded 2 workflow(s)" in mock_io.tool_output.call_args.args[0]


@pytest.mark.asyncio
async def test_reload_error_path(mock_io, mock_coder):
    stub = types.ModuleType("cecli.helpers.workflows.config")

    def boom(**kwargs):
        raise RuntimeError("bad yaml")

    stub.load_workflows = boom
    real_config = sys.modules.get("cecli.helpers.workflows.config")
    sys.modules["cecli.helpers.workflows.config"] = stub
    try:
        await WorkflowCommand.execute(mock_io, mock_coder, "reload")
    finally:
        if real_config is not None:
            sys.modules["cecli.helpers.workflows.config"] = real_config

    assert "bad yaml" in mock_io.tool_error.call_args.args[0]


@pytest.mark.asyncio
async def test_unknown_subcommand(mock_coder, mock_io):
    await WorkflowCommand.execute(mock_io, mock_coder, "frobnicate")
    msg = mock_io.tool_error.call_args.args[0]
    assert "Unknown subcommand" in msg and "reload" in msg


# ---------------------------------------------------------------- case 28 --


def test_completions(mock_coder):
    mock_coder.workflows = [_wf("demo"), _wf("dep-check")]

    subs = WorkflowCommand.get_completions(None, mock_coder, "")
    assert "list" in subs and "run" in subs and "reload" in subs

    assert WorkflowCommand.get_completions(None, mock_coder, "ru") == ["run"]

    for sub in ("run", "show", "status"):
        names = WorkflowCommand.get_completions(None, mock_coder, f"{sub} de")
        assert names == ["demo", "dep-check"]

    # A trailing space means the subcommand is settled with no name prefix
    # yet, so all workflow names are offered immediately.
    for sub in ("run", "show", "status"):
        assert WorkflowCommand.get_completions(None, mock_coder, f"{sub} ") == [
            "demo",
            "dep-check",
        ]
        assert WorkflowCommand.get_completions(None, mock_coder, f"{sub} d") == [
            "demo",
            "dep-check",
        ]

    assert WorkflowCommand.get_completions(None, mock_coder, "list ") == []

    # Subcommand commands need the full argument text so the name is not
    # mistaken for a subcommand prefix by the completer.
    assert "/workflows" in Commands.FULL_ARGS_COMPLETION_COMMANDS

    assert WorkflowCommand.get_completions(None, mock_coder, "list something") == []


# ---------------------------------------------------------------- case 29 --


def test_registered_in_command_registry():
    assert CommandRegistry.get_command("workflows") is WorkflowCommand
    assert CommandRegistry.get_command("wf") is None
