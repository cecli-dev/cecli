import asyncio

from cecli.helpers import coroutines


def test_cancel_and_abandon_skips_tasks_from_closed_loop():
    loop = asyncio.new_event_loop()

    async def sleeper():
        await asyncio.sleep(10)

    task = loop.create_task(sleeper())
    loop.run_until_complete(asyncio.sleep(0))
    loop.close()
    task._log_destroy_pending = False
    coroutines.background_tasks.add(task)

    asyncio.run(coroutines.cancel_and_abandon([task]))

    assert task not in coroutines.background_tasks
