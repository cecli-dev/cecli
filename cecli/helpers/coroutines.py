import asyncio


def is_active(task):
    if not task or task.done() or task.cancelled():
        return False

    return True


async def interruptible(coroutine, interrupt_event):
    """
    Runs a coroutine and allows it to be interrupted by an asyncio.Event.

    Args:
        coroutine: The coroutine to run.
        interrupt_event: The asyncio.Event that signals an interruption.

    Returns:
        A tuple of (result, interrupted).
        - If not interrupted: (coroutine_result, False)
        - If interrupted: (None, True)
    """
    main_task = asyncio.create_task(coroutine)
    interrupt_task = asyncio.create_task(interrupt_event.wait())

    done, pending = await asyncio.wait(
        {main_task, interrupt_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass  # Expected

    if interrupt_task in done:
        return None, True

    try:
        return main_task.result(), False
    except asyncio.CancelledError:
        return None, True
