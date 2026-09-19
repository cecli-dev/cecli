import asyncio
import logging

from cecli.helpers.threading import ThreadSafeEvent

logger = logging.getLogger(__name__)


# Strong reference pool to protect fire-and-forget tasks from garbage collection
background_tasks: set = set()

# Grace period granted to a cancelled task to unwind. Transports that defer or
# swallow cancellation (AnyIO cancel scopes, shielded streams) would otherwise
# block the interrupting coroutine forever.
INTERRUPT_UNWIND_GRACE_SECONDS = 5.0


def fire_and_forget(coro) -> asyncio.Task:
    """Safely schedule a background coroutine without awaiting it."""
    task = asyncio.create_task(coro)
    background_tasks.add(task)
    task.add_done_callback(_handle_result)
    return task


async def interruptible_async_generator(async_generator, interrupt_event):
    """
    Wraps an async generator to make it interruptible.
    """
    gen = async_generator.__aiter__()
    interrupt_task = asyncio.create_task(interrupt_event.wait())
    next_task = None

    try:
        while True:
            next_task = asyncio.create_task(gen.__anext__())
            done, pending = await asyncio.wait(
                {next_task, interrupt_task}, return_when=asyncio.FIRST_COMPLETED
            )

            if interrupt_task in done:
                await cancel_and_abandon([next_task])
                break

            if next_task in done:
                try:
                    yield next_task.result()
                except StopAsyncIteration:
                    break
    finally:
        # Cancel whichever task is still pending if the generator is closed early
        # (e.g. GeneratorExit at the wait or yield), not just the interrupt waiter.
        await cancel_and_abandon([task for task in (next_task, interrupt_task) if task is not None])


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

    A task that ignores cancellation is abandoned once the grace period
    elapses (see cancel_and_abandon) so a wedged transport cannot block the
    caller forever.
    """
    if interrupt_event is None:
        interrupt_event = ThreadSafeEvent()

    main_task = asyncio.create_task(coroutine)
    interrupt_task = asyncio.create_task(interrupt_event.wait())

    try:
        done, pending = await asyncio.wait(
            {main_task, interrupt_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        await cancel_and_abandon(pending)

        if interrupt_task in done:
            return None, True

        try:
            return main_task.result(), False
        except asyncio.CancelledError:
            return None, True
    finally:
        # When the caller is cancelled while waiting, neither branch above
        # runs, so cancel any remaining tasks here instead of orphaning the
        # inner coroutine (which would keep running detached).
        await cancel_and_abandon([main_task, interrupt_task])


def task_is_cancelling() -> bool:
    """Return True when the running asyncio task has a pending cancellation.

    Used to tell a genuine cancellation of the caller apart from cancellation
    errors that transports (e.g. MCP's anyio TaskGroups) surface for ordinary
    connection failures.

    Reliable on Python 3.11+ (``Task.cancelling()``). On 3.10 there is no public
    signal: ``_must_cancel`` is already cleared by the time the CancelledError is
    delivered, so this is best-effort and usually reports False. Callers must
    therefore treat False as "not known to be cancelling" rather than proof.
    """
    task = asyncio.current_task()
    if task is None:
        return False

    cancelling_fn = getattr(task, "cancelling", None)
    if cancelling_fn is not None:
        return cancelling_fn() > 0

    # Python 3.10 fallback: best-effort only (see docstring).
    return bool(getattr(task, "_must_cancel", False))


def drain_task_results(tasks):
    """Consume exceptions from finished tasks so they aren't reported as unretrieved."""
    for task in tasks:
        if task.cancelled():
            continue

        try:
            exc = task.exception()
        except (asyncio.CancelledError, asyncio.InvalidStateError):
            continue

        if exc is not None:
            logger.warning(f"Task raised while unwinding after interrupt: {exc}")


async def cancel_and_abandon(tasks, grace=INTERRUPT_UNWIND_GRACE_SECONDS):
    """Cancel tasks and wait up to ``grace`` seconds for them to unwind.

    Cancellation is cooperative, and some transports (AnyIO cancel scopes,
    shielded streams) defer or swallow it. Waiting on them unconditionally
    would block the caller forever, so anything still running after the grace
    period is abandoned: it keeps a strong reference so it can finish on its
    own without tripping the "Task was destroyed but it is pending" warning.
    """
    pending_tasks = [task for task in tasks if not task.done()]

    if not pending_tasks:
        return

    for task in pending_tasks:
        task.cancel()

    done, still_running = await asyncio.wait(set(pending_tasks), timeout=grace)
    drain_task_results(done)

    for task in still_running:
        logger.warning(
            f"Task ignored cancellation after {grace}s; abandoning it. It may still be"
            " running and could touch shared state later."
        )
        background_tasks.add(task)
        task.add_done_callback(_handle_result)


def _handle_result(task: asyncio.Task) -> None:
    """Callback to clean up references and capture exceptions safely."""
    background_tasks.discard(task)
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Background task failed: {e}", exc_info=True)
