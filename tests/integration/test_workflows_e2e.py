"""End-to-end workflow + scheduler integration tests (tests.md cases 54-56).

Everything shipped is real here: YAML discovery (:func:`load_workflows` under a
fake ``Path.home``), the ``SchedulerService`` tick/dispatch contract, the SQLite
lease arbiter (:class:`SchedulerDB` under ``tmp_path``) and cron arithmetic
(:mod:`cecli.helpers.scheduler.cron`). Only the two collaborators that would
need a live session are replaced: ``register_workflow_subagents`` (the agent
registry) and ``execute_workflow`` (coder / sub-agent spawn), the latter with a
counting AsyncMock - which is exactly what makes duplicate dispatch observable.

Fake time is always derived from the DB's own seeded ``next_run`` (i.e. the next
minute boundary after the *real* now), so lease timestamps - which the DB
computes from the wall clock - stay comfortably live for the whole test.
"""

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cecli.helpers.scheduler.db import SchedulerDB
from cecli.helpers.scheduler.service import SchedulerService
from cecli.helpers.workflows import load_workflows
from cecli.helpers.workflows.models import (
    RunResult,
    TaskConfig,
    TaskResult,
    WorkflowConfig,
)

MINUTE = timedelta(minutes=1)

# Long enough that start()'s tick loop never gets a second pass in: the test
# owns every tick by calling _tick() with fake now values.
NO_LOOP = 10_000.0

DEMO_YML = """\
name: demo
description: >
  End-to-end demo workflow discovered from ~/.cecli/workflows/demo.yml.
schedule: "*/1 * * * *"
timezone: UTC
lease_timeout: 5
on_failure: continue
skills:
  - demo-skill
servers:
  - Demo-MCP
tasks:
  - name: attach-demo
    prompt: /mcp load demo
  - name: write-report
    prompt: summarize the demo run into .cecli/reports/demo.md
"""


@pytest.fixture
def stubs():
    """Count dispatches; keep the agent registry and lease renewal inert."""

    execute = AsyncMock(side_effect=_ok_dispatch)
    register = MagicMock(return_value=["wf:demo"])

    with (
        patch("cecli.helpers.workflows.runner.execute_workflow", execute),
        patch("cecli.helpers.workflows.subagents.register_workflow_subagents", register),
        patch("cecli.helpers.scheduler.lock.start_lease_renewal", _renewal_dummy),
    ):
        yield SimpleNamespace(execute=execute, register=register)


# ------------------------------------------------------------- case 54 --
async def test_yaml_config_drives_two_runs_through_real_db(tmp_path, monkeypatch, stubs):
    """demo.yml -> load_workflows -> SchedulerService -> SchedulerDB, twice."""

    home, repo = _isolate_fs(tmp_path, monkeypatch)
    (home / ".cecli" / "workflows" / "demo.yml").write_text(DEMO_YML)

    configs = load_workflows()
    wf = _only_demo(configs)
    assert [t.prompt for t in wf.tasks] == [
        "/mcp load demo",
        "summarize the demo run into .cecli/reports/demo.md",
    ], "task order must survive YAML loading"

    db = SchedulerDB(db_path=tmp_path / "scheduler.db")
    service = await _started(_service([wf], db=db))

    assert service.workflows == {"demo": wf}
    stubs.register.assert_called_once()
    assert [w.name for w in stubs.register.call_args[0][0]] == ["demo"]

    job = await db.get_job("demo")
    assert job["engine"] == "cron"
    assert job["enabled"] == 1
    assert job["definition_hash"] == wf.definition_hash()

    first = _aware(job["next_run"])
    assert (first.second, first.microsecond) == (0, 0), "cron seeds a whole-minute slot"
    assert first > datetime.now(timezone.utc) - MINUTE, "the slot is the next minute, not stale"

    await service._tick(now=first)
    await _drain(service)
    await service._tick(now=first + MINUTE)
    await _drain(service)

    assert stubs.execute.await_count == 2
    assert [call.args[1] for call in stubs.execute.call_args_list] == [wf, wf]
    assert [call.kwargs["source"] for call in stubs.execute.call_args_list] == [
        "scheduler",
        "scheduler",
    ]

    runs = sorted(await db.recent_runs("demo"), key=lambda r: r["run_id"])
    assert [r["status"] for r in runs] == ["ok", "ok"]
    assert [r["source"] for r in runs] == ["scheduler", "scheduler"]
    assert [r["attempts"] for r in runs] == [1, 1]
    assert [_aware(r["slot"]) for r in runs] == [first, first + MINUTE]
    assert len({(r["name"], r["slot"], r["attempts"]) for r in runs}) == 2
    assert _task_log(db) == [
        ("attach-demo", "ok"),
        ("write-report", "ok"),
        ("attach-demo", "ok"),
        ("write-report", "ok"),
    ], "the runner's per-task outcomes must reach task_log in order"

    job = await db.get_job("demo")
    assert _aware(job["next_run"]) == first + 2 * MINUTE, "next_run advanced once per slot"
    assert job["last_status"] == "ok"
    assert _aware(job["last_run"]) >= _now_floor()

    await service.stop()


# ------------------------------------------------------------- case 55 --
async def test_two_instances_one_db_claim_each_slot_exactly_once(tmp_path, stubs):
    """Concurrent instances sharing a DB file: one dispatch per slot, ever.

    Runs are slow on purpose: the loser instance then always reaches
    ``try_acquire`` while the winner still holds a *live* lease, so the claim
    race itself is arbitrated - not just a stale ``next_run`` read.
    """

    stubs.execute.side_effect = _slow_dispatch

    wf = WorkflowConfig(name="duo", tasks=[TaskConfig(prompt="go")], schedule="*/1 * * * *")
    db_path = tmp_path / "shared.db"
    services = [await _started(_service([wf], db=SchedulerDB(db_path=db_path))) for _ in range(2)]
    first_service, second_service = services

    assert first_service.instance_id != second_service.instance_id
    assert first_service.db is not second_service.db
    assert first_service.db.db_path == second_service.db.db_path

    slot = _aware((await first_service.db.get_job("duo"))["next_run"])

    for _ in range(3):
        await asyncio.gather(first_service._tick(now=slot), second_service._tick(now=slot))
        await _drain(first_service)
        await _drain(second_service)
        slot = slot + MINUTE

    assert stubs.execute.await_count == 3, "a shared DB must never double-dispatch"

    runs = sorted(await first_service.db.recent_runs("duo"), key=lambda r: r["run_id"])
    assert len(runs) == 3
    assert [r["attempts"] for r in runs] == [1, 1, 1], "one primary claim per slot"
    assert [r["status"] for r in runs] == ["ok", "ok", "ok"]
    assert len({r["slot"] for r in runs}) == 3
    assert len({(r["name"], r["slot"], r["attempts"]) for r in runs}) == 3
    assert {r["instance_id"] for r in runs} <= {
        first_service.instance_id,
        second_service.instance_id,
    }
    # Which instance wins a slot is a race; that each slot is won at most once
    # is the contract - so the two instances' slot sets must be disjoint.
    owned = [
        {r["slot"] for r in runs if r["instance_id"] == service.instance_id} for service in services
    ]

    assert owned[0].isdisjoint(owned[1])
    assert owned[0] | owned[1] == {r["slot"] for r in runs}

    for service in services:
        await service.stop()


# ------------------------------------------------------------- case 56 --
async def test_stop_releases_lease_so_a_fresh_instance_steals(tmp_path, stubs):
    """stop() cancels the hung run and frees the lease - no timeout wait."""

    wf = WorkflowConfig(
        name="steal",
        tasks=[TaskConfig(prompt="go")],
        schedule="*/1 * * * *",
        lease_timeout=120.0,
    )
    entered, hold = asyncio.Event(), asyncio.Event()

    async def hanging(coder, workflow, *, source="manual", run_id=None):
        entered.set()
        await hold.wait()

        return RunResult(name=workflow.name, status="ok", source=source)

    stubs.execute.side_effect = hanging

    db_path = tmp_path / "steal.db"
    owner = await _started(_service([wf], db=SchedulerDB(db_path=db_path)))
    slot = (await owner.db.get_job("steal"))["next_run"]

    await owner._tick(now=_aware(slot))
    await asyncio.wait_for(entered.wait(), timeout=5)

    heir = await _started(_service([wf], db=SchedulerDB(db_path=db_path)))
    assert heir.instance_id != owner.instance_id

    assert await heir.db.try_acquire("steal", heir.instance_id, wf.lease_timeout, slot) is None
    assert len(await heir.db.recent_runs("steal")) == 1, "a live lease is not stealable"

    await owner.stop()

    assert not owner.running
    assert owner._active == {}
    assert owner._held_leases == {}

    lease = await heir.db.try_acquire("steal", heir.instance_id, wf.lease_timeout, slot)
    assert lease is not None, "stop() must free the slot immediately"

    runs = sorted(await heir.db.recent_runs("steal"), key=lambda r: r["run_id"])
    assert [r["attempts"] for r in runs] == [1, 2]
    assert runs[0]["status"] == "aborted"
    assert runs[0]["slot"] == runs[1]["slot"] == slot
    assert runs[1]["instance_id"] == heir.instance_id
    assert runs[1]["status"] == "running"

    hold.set()
    await heir.stop()


# ------------------------------------------------------------- helpers --
def _service(workflows, *, db):
    coder = MagicMock()
    coder.uuid = "e2e-primary"

    return SchedulerService(coder, workflows, io=None, tick_seconds=NO_LOOP, db=db)


async def _started(service):
    """start() (DB init, registration, definition sync), then park the loop."""

    await service.start()
    service._task.cancel()
    await asyncio.gather(service._task, return_exceptions=True)

    return service


async def _drain(service):
    while service._active:
        await asyncio.gather(*list(service._active.values()), return_exceptions=True)

        for name in [n for n, t in service._active.items() if t.done()]:
            service._active.pop(name, None)


def _only_demo(configs):
    assert [wf.name for wf in configs] == ["demo"], "only demo.yml should be visible"
    wf = configs[0]
    assert isinstance(wf, WorkflowConfig)
    assert wf.schedule == "*/1 * * * *"
    assert wf.enabled and wf.lease_timeout == 5.0 and wf.on_failure == "continue"
    assert wf.servers == ["demo-mcp"], "servers normalize to lowercase"
    assert wf.agent_name == "wf:demo"

    return wf


def _isolate_fs(tmp_path, monkeypatch):
    """Fake HOME (for ~/.cecli/workflows) plus an empty cwd (no local file)."""

    home = tmp_path / "home"
    (home / ".cecli" / "workflows").mkdir(parents=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.chdir(repo)

    return home, repo


def _renewal_dummy(*args, **kwargs):
    return SimpleNamespace(cancel=lambda: None)


async def _ok_dispatch(coder, wf, *, source="manual", run_id=None):
    tasks = [
        TaskResult(index=index, label=task.name or f"task-{index}", status="ok")
        for index, task in enumerate(wf.tasks)
    ]

    return RunResult(name=wf.name, status="ok", source=source, tasks=tasks)


async def _slow_dispatch(coder, wf, *, source="manual", run_id=None):
    await asyncio.sleep(0.1)

    return await _ok_dispatch(coder, wf, source=source, run_id=run_id)


def _task_log(db):
    """(label, status) of every task_log row, oldest run first."""
    conn = sqlite3.connect(db.db_path)

    try:
        return conn.execute("SELECT label, status FROM task_log ORDER BY run_id, idx").fetchall()
    finally:
        conn.close()


def _aware(value):
    """DB ISO string / datetime -> aware UTC datetime."""

    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _now_floor():
    return datetime.now(timezone.utc) - MINUTE
