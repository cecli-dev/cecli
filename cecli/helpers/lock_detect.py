import asyncio
import logging
import os
import sys
import threading
import time
import traceback

from cecli.decoding import safe_open

# Set up logging to catch asyncio framework logs
logging.basicConfig(level=logging.INFO)
logging.getLogger("asyncio").setLevel(logging.DEBUG)


# Registered event loops whose asyncio tasks are included in each dump.
# Task state is only read from the owning loop (see _dump_async_state), since
# thread stacks alone cannot show coroutine/task state.
_async_loops: dict = {}
_async_state_providers: dict = {}


def dump_stacks_to_file(filename=".cecli/logs/threads.log", interval=5, max_prints=10):
    """Periodically writes stack traces to a file, resetting it after max_prints."""
    print_count = 0

    log_dir = os.path.dirname(filename)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    while True:
        time.sleep(interval)
        try:
            # Determine mode: "w" to overwrite/clear on the 11th print, "a" to append
            mode = "w" if print_count >= max_prints else "a"

            with safe_open(filename, mode) as f:
                if mode == "w":
                    f.write(f"--- Log reset automatically after {max_prints} prints ---\n")
                    print_count = 0  # Reset the counter

                timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                f.write(
                    f"\n=================== STACK TRACE DUMP ({timestamp}) ===================\n"
                )

                for thread_id, frame in sys._current_frames().items():
                    thread_obj = threading._active.get(thread_id)
                    thread_name = thread_obj.name if thread_obj else "Unknown Thread"

                    f.write(f"\nThread Name: {thread_name} (ID: {thread_id})\n")
                    f.write("-" * 40 + "\n")
                    traceback.print_stack(frame, file=f)

                f.write("=" * 70 + "\n")

            for name in list(_async_loops.keys()):
                _schedule_async_dump(name, filename)

            print_count += 1  # Increment after a successful write

        except Exception as e:
            print(f"Error writing stack dump to file: {e}", file=sys.stderr)


def register_async_loop(name, loop) -> None:
    """Register an event loop to include asyncio task dumps for."""
    _async_loops[name] = loop


def register_async_state_provider(name, provider) -> None:
    """Register a callable returning extra state text for a loop's dump."""
    _async_state_providers[name] = provider


def _format_async_tasks(loop, name) -> str:
    """Return a readable dump of every task on ``loop`` (loop thread only)."""
    lines = [f"\n------------------- ASYNCIO TASKS ({name}) -------------------\n"]

    try:
        tasks = asyncio.all_tasks(loop)
    except Exception as e:
        return f"<unable to read asyncio tasks: {e}>\n"

    for task in tasks:
        lines.append(f"\n[{task.get_name()}] done={task.done()} cancelled={task.cancelled()}\n")
        lines.append(f"  {task.get_coro()!r}\n")

        for frame in task.get_stack(limit=10):
            lines.append("".join(traceback.format_stack(frame, limit=1)))

    return "".join(lines)


def _dump_async_state(name, filename) -> None:
    """Append asyncio task/state info for one loop. Runs on the loop thread."""
    loop = _async_loops.get(name)
    if loop is None or loop.is_closed():
        return

    parts = []
    provider = _async_state_providers.get(name)

    if provider is not None:
        try:
            parts.append(provider())
        except Exception as e:
            parts.append(f"<state provider error: {e}>\n")

    parts.append(_format_async_tasks(loop, name))

    try:
        with safe_open(filename, "a") as f:
            f.write("".join(parts))
    except Exception:
        pass


def _schedule_async_dump(name, filename) -> None:
    """Schedule an async-state dump onto a registered loop, if it is running."""
    loop = _async_loops.get(name)
    if loop is None or loop.is_closed() or not loop.is_running():
        return

    try:
        loop.call_soon_threadsafe(_dump_async_state, name, filename)
    except RuntimeError:
        pass


# Start the monitor in a background daemon thread
monitor_thread = threading.Thread(
    target=dump_stacks_to_file,
    args=(".cecli/logs/threads.log", 5, 10),  # Clears every 10 prints
    daemon=True,
)
monitor_thread.start()
