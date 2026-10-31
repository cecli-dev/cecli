"""Helpers for managing a coder's in-memory prompt queue (CLI-33).

The prompt queue lives on the coder instance (``Coder.prompt_queue``) so that
primary agents and sub-agents each have their own independent FIFO queue. The
functions in this module take the coder they operate on as their first argument
so callers (slash commands, the TUI, the generation loop) can target any agent.
"""

import threading
import time

MAX_QUEUE_SIZE = 100
MAX_PROMPT_LENGTH = 10000


def get_active_coder(coder):
    """Resolve the coder that queue commands should operate on.

    Uses ``AgentService`` so queue commands are sub-agent aware: when a
    sub-agent is in the foreground its queue is targeted, otherwise the
    primary coder's queue is used.
    """
    from cecli.helpers.agents.service import AgentService

    try:
        service = AgentService.get_instance(coder)
        return service.foreground_coder or coder
    except Exception:
        return coder


def enqueue_prompt(coder, text: str) -> dict:
    """Add a prompt to the given coder's queue and return the queued item.

    Args:
        coder: The coder whose queue should be modified.
        text: The prompt text to enqueue.

    Returns:
        dict with keys: id (str), text (str), timestamp (float).

    Raises:
        ValueError: If text is empty, None, or exceeds 10000 characters.
        RuntimeError: If the queue is at max capacity (100 items).
    """
    if not text or not text.strip():
        raise ValueError("Cannot enqueue empty prompt")
    if len(text) > MAX_PROMPT_LENGTH:
        raise ValueError("Prompt exceeds maximum length of 10000 characters")
    if get_queue_length(coder) >= MAX_QUEUE_SIZE:
        raise RuntimeError("Queue is full (max 100 items)")

    with _get_lock(coder):
        coder._queue_counter += 1
        item = {
            "id": str(coder._queue_counter),
            "text": text,
            "timestamp": time.time(),
        }
        coder.prompt_queue.append(item)
    return item


def insert_prompt(coder, text: str, index: int) -> dict:
    """Insert a prompt at the given 0-based index and return the queued item.

    Args:
        coder: The coder whose queue should be modified.
        text: The prompt text to insert.
        index: 0-based position to insert at. Clamped to [0, len(queue)].

    Returns:
        dict with keys: id (str), text (str), timestamp (float).

    Raises:
        ValueError: If text is empty, None, or exceeds 10000 characters.
        RuntimeError: If the queue is at max capacity (100 items).
    """
    if not text or not text.strip():
        raise ValueError("Cannot enqueue empty prompt")
    if len(text) > MAX_PROMPT_LENGTH:
        raise ValueError("Prompt exceeds maximum length of 10000 characters")
    if get_queue_length(coder) >= MAX_QUEUE_SIZE:
        raise RuntimeError("Queue is full (max 100 items)")

    index = max(0, min(index, get_queue_length(coder)))
    with _get_lock(coder):
        coder._queue_counter += 1
        item = {
            "id": str(coder._queue_counter),
            "text": text,
            "timestamp": time.time(),
        }
        coder.prompt_queue.insert(index, item)
    return item


def dequeue_prompt(coder) -> dict | None:
    """Remove and return the first item from the coder's queue (FIFO).

    Args:
        coder: The coder whose queue should be modified.

    Returns:
        The dequeued item dict, or None if the queue is empty.
    """
    with _get_lock(coder):
        if not coder.prompt_queue:
            return None
        return coder.prompt_queue.pop(0)


def dequeue_for_processing(coder) -> dict | None:
    """Remove and activate the next queued prompt for processing.

    Clearing ``_processing_queue`` while holding the queue lock avoids the
    race where a prompt is enqueued just after the drain sees an empty queue
    but before it releases the processing flag.
    """
    with _get_lock(coder):
        if not coder.prompt_queue:
            coder._active_queue_prompt = None
            coder._processing_queue = False
            return None
        item = coder.prompt_queue.pop(0)
        coder._active_queue_prompt = item
        return item


def get_active_prompt(coder) -> dict | None:
    """Return the prompt currently being processed, if any."""
    with _get_lock(coder):
        return getattr(coder, "_active_queue_prompt", None)


def clear_active_prompt(coder) -> dict | None:
    """Clear and return the prompt currently being processed, if any."""
    with _get_lock(coder):
        item = getattr(coder, "_active_queue_prompt", None)
        coder._active_queue_prompt = None
        return item


def requeue_active_prompt(coder) -> dict | None:
    """Return the in-flight prompt to the front of the queue.

    The original item is restored unchanged so its id and timestamp match the
    prompt the user originally queued.
    """
    with _get_lock(coder):
        item = getattr(coder, "_active_queue_prompt", None)
        if item is None:
            return None
        coder.prompt_queue.insert(0, item)
        coder._active_queue_prompt = None
        return item


def finish_processing(coder) -> None:
    """Mark the queue drain as finished."""
    with _get_lock(coder):
        coder._processing_queue = False


def get_queue_length(coder) -> int:
    """Return the current number of items in the coder's queue."""
    return len(coder.prompt_queue)


def list_queue(coder) -> list:
    """Return a snapshot of the coder's queued items."""
    return list(coder.prompt_queue)


def remove_from_queue(coder, index: int) -> dict | None:
    """Remove and return the item at the given 0-based index.

    Args:
        coder: The coder whose queue should be modified.
        index: 0-based index of the item to remove.

    Returns:
        The removed item dict, or None if the index is out of bounds.
    """
    with _get_lock(coder):
        if index < 0 or index >= len(coder.prompt_queue):
            return None
        return coder.prompt_queue.pop(index)


def clear_queue(coder) -> list:
    """Remove all items from the coder's queue and return them.

    Args:
        coder: The coder whose queue should be modified.

    Returns:
        List of all items that were in the queue.
    """
    with _get_lock(coder):
        items = list(coder.prompt_queue)
        coder.prompt_queue.clear()
    return items


def nested_command_completions(coder, text: str) -> list:
    """Completions for a nested slash-command inside queued prompt text (CLI-33).

    While the inner command is still being typed (no space yet), suggest
    matching command names from the registry (e.g. "/sess" -> "/sessions").
    Once the inner command is complete, delegate to the original command's
    ``get_completions`` so ``/queue /add <tab>`` behaves exactly like ``/add <tab>``.
    """
    if not text or not text.startswith("/"):
        return []

    from cecli.commands.utils.registry import CommandRegistry

    first_space = text.find(" ")
    if first_space == -1:
        prefix = text[1:].lower()
        return sorted(
            f"/{cmd}" for cmd in CommandRegistry.list_commands() if cmd.startswith(prefix)
        )

    inner_cmd = text[:first_space]
    inner_args = text[first_space + 1 :]
    try:
        return list(coder.commands.get_completions(inner_cmd, inner_args, coder=coder))
    except Exception:
        return []


def _get_lock(coder) -> threading.Lock:
    """Return the coder's queue lock, creating one if missing."""
    lock = getattr(coder, "_queue_lock", None)
    if lock is None:
        lock = threading.Lock()
        coder._queue_lock = lock
    return lock
