"""cecli/helpers/queues.py — Global per-coder queue registry."""

from __future__ import annotations

import asyncio
import logging
import queue
from typing import Any

logger = logging.getLogger(__name__)

# Global registry: coder_uuid → queue.Queue for sending input to that coder
_per_coder_queues: dict[str, "queue.Queue"] = {}

# First-registered coder is tracked as the primary (used when no coder_uuid is given)
_primary_coder_id: str | None = None

# Event-loop state for waking input consumers. All per-coder input is consumed
# on the coder worker loop; producers (TUI, WebSocket, ACP) push to the
# thread-safe queues and wake waiters through _input_wake instead of forcing
# consumers to poll.
_input_loop: asyncio.AbstractEventLoop | None = None
_input_wake: asyncio.Event | None = None

# Dedicated wake events for consumers parked on a loop *other* than the primary
# input loop (for example a scheduler-dispatched workflow asking for input while
# the scheduler ticks on the main/Textual loop). They get their own slot so a
# foreign-loop consumer can never steal the primary binding and strand the
# primary coder's input pump.
_input_wakes: dict[asyncio.AbstractEventLoop, asyncio.Event] = {}


def register_coder_queue(coder_uuid: str, q: "queue.Queue") -> None:
    """Register a per-coder input queue.

    The first coder registered is automatically tracked as the primary
    coder, used as the default target when no coder_uuid is specified.
    """
    global _primary_coder_id
    if not _per_coder_queues:
        _primary_coder_id = coder_uuid
    _per_coder_queues[coder_uuid] = q


def unregister_coder_queue(coder_uuid: str) -> None:
    """Unregister a per-coder input queue.

    If the unregistered coder was the primary, the primary is cleared.
    """
    global _primary_coder_id
    _per_coder_queues.pop(coder_uuid, None)
    if _primary_coder_id == coder_uuid:
        _primary_coder_id = None


def get_coder_queue(coder_uuid: str) -> "queue.Queue | None":
    """Get the input queue for a given coder UUID."""
    return _per_coder_queues.get(coder_uuid)


def push_coder_input(coder_uuid: str, message: str | dict[str, Any]) -> bool:
    """Push a user input message directly to a coder's input queue.

    Accepts either a raw string (text input) or a dict (structured message
    like confirmation responses). Wakes any coroutine blocked in
    wait_for_input() so consumers react immediately instead of polling.

    Returns True if delivered, False if the coder is not registered.
    """
    q = _per_coder_queues.get(coder_uuid)
    if q is None:
        return False
    q.put(message)
    wake_input_waiters()
    return True


def get_primary_coder_id() -> str | None:
    """Get the primary coder UUID (the first one registered).

    Returns None if no coders have been registered.
    """
    return _primary_coder_id


def set_input_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Bind the input wake-up state to a specific event loop.

    Consumers awaiting wait_for_input() run on this loop (the coder worker
    loop). If this is never called, wait_for_input() binds to the running
    loop on first use.
    """
    global _input_loop, _input_wake
    _input_loop = loop
    _input_wake = asyncio.Event()
    # This loop now owns the primary slot, so drop any dedicated wake it may
    # have registered while it was still a foreign consumer.
    _input_wakes.pop(loop, None)


def wake_input_waiters() -> None:
    """Wake coroutines blocked in wait_for_input().

    Safe to call from any thread; the wake is marshaled onto the input loop
    via call_soon_threadsafe. No-op if no consumer has bound a loop yet.

    If the bound loop was closed (e.g. a hot reload tore down the previous
    coder worker loop), the stale binding is dropped so the next
    wait_for_input() rebinds to the current loop instead of raising
    "Event loop is closed".

    Every loop with a parked consumer is woken, not just the primary one:
    a consumer on a foreign loop has its own event (see ``_input_wakes``) so
    the primary binding is never stolen from it.
    """
    global _input_loop, _input_wake

    loop = _input_loop

    if loop is not None:
        if _input_wake is None:
            _input_loop = None
        elif loop.is_closed():
            _input_loop = None
            _input_wake = None
        else:
            loop.call_soon_threadsafe(_input_wake.set)

    for other, wake in list(_input_wakes.items()):
        if other.is_closed():
            _input_wakes.pop(other, None)
            continue

        try:
            other.call_soon_threadsafe(wake.set)
        except RuntimeError:
            # Loop stopped accepting callbacks between the check and the call.
            _input_wakes.pop(other, None)


async def wait_for_input() -> None:
    """Await the next input push without polling.

    Intended to be called from the input loop (the coder worker loop).
    Consumers sweep the payload queues first, then block here until
    wake_input_waiters() fires. Initializes the wake state from the running
    loop on first use and rebinds whenever the previous loop was closed (which
    happens across a hot reload).

    A caller on a *different*, still-live loop no longer rebinds the primary
    slot: it gets a dedicated wake event instead. Rebinding used to strand the
    primary coder's input pump on the orphaned event, which froze the TUI
    (prompts, slash commands and ``/exit`` all unresponsive; only Ctrl-Q
    worked) whenever a scheduler-dispatched workflow needed input or a
    confirmation and therefore ran on the main (Textual) loop.
    """
    loop = asyncio.get_running_loop()

    if _input_loop is None or _input_wake is None or _input_loop.is_closed():
        set_input_loop(loop)

    if _input_loop is loop:
        _input_wake.clear()
        await _input_wake.wait()
        return

    logger.warning(
        "wait_for_input() called from a non-input loop (%r); using a dedicated"
        " wake event instead of rebinding the primary input loop",
        loop,
    )

    wake = _input_wakes.get(loop)

    if wake is None:
        wake = asyncio.Event()
        _input_wakes[loop] = wake

    wake.clear()
    await wake.wait()
