import asyncio

import pytest  # noqa: F401

from cecli.helpers.threading import ThreadSafeEvent
from cecli.run_cmd import run_cmd, run_cmd_async


def test_run_cmd_echo():
    command = "echo Hello"
    exit_code, output = run_cmd(command)

    assert exit_code == 0
    assert output.strip() == "Hello"


def test_run_cmd_async_leaves_no_event_waiters():
    event = ThreadSafeEvent()

    async def run():
        exit_code, output = await run_cmd_async("echo Hello", event)

        assert exit_code == 0
        assert output.strip() == "Hello"
        # A waiter parked on the event outlives the command and is later
        # reported as "Task was destroyed but it is pending".
        assert len(event._async_event._waiters) == 0

    asyncio.run(run())
