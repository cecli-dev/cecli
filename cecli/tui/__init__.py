"""Textual TUI interface for cecli.

This package provides an experimental TUI (Terminal User Interface) for cecli
using the Textual framework. Launch with: cecli --tui
"""

import queue
import weakref

from cecli.commands import ReloadProgramSignal

from .app import TUI
from .io import TextualInputOutput
from .worker import CoderWorker

__all__ = ["TUI", "TextualInputOutput", "CoderWorker", "create_tui_io", "launch_tui"]


def create_tui_io(args, editing_mode):
    """Create TUI IO instance and communication queues.

    Args:
        args: Parsed command line arguments
        editing_mode: EditingMode.VI or EditingMode.EMACS

    Returns:
        Tuple of (io, output_queue, input_queue)
    """
    output_queue = queue.Queue()
    input_queue = queue.Queue()

    io = TextualInputOutput(
        output_queue=output_queue,
        input_queue=input_queue,
        pretty=True,
        yes=args.yes_always,
        input_history_file=args.input_history_file,
        chat_history_file=args.chat_history_file,
        input=None,
        output=None,
        user_input_color=args.user_input_color,
        tool_output_color=args.tool_output_color,
        tool_warning_color=args.tool_warning_color,
        tool_error_color=args.tool_error_color,
        completion_menu_color=args.completion_menu_color,
        completion_menu_bg_color=args.completion_menu_bg_color,
        completion_menu_current_color=args.completion_menu_current_color,
        completion_menu_current_bg_color=args.completion_menu_current_bg_color,
        assistant_output_color=args.assistant_output_color,
        code_theme=args.code_theme,
        dry_run=args.dry_run,
        encoding=args.encoding,
        line_endings=args.line_endings,
        editingmode=editing_mode,
        fancy_input=False,
        multiline_mode=args.multiline,
        notifications=args.notifications,
        notifications_command=args.notifications_command,
        notification_bell=args.notification_bell,
        verbose=args.verbose,
    )

    return io, output_queue, input_queue


async def launch_tui(coder, output_queue, input_queue, args):
    """Launch the TUI application.

    Args:
        coder: Initialized Coder instance
        output_queue: Queue for output messages
        input_queue: Queue for input messages

    Returns:
        Exit code from TUI
    """
    # Pin tqdm's class lock before the TUI captures stdout/stderr (see _pin_tqdm_lock).
    _pin_tqdm_lock()

    worker = None
    return_code = 0
    try:
        worker = CoderWorker(coder, output_queue, input_queue)
        app = TUI(worker, output_queue, input_queue, args)

        # Set weak reference to TUI app on the coder instance
        coder.tui = weakref.ref(app)

        if args.headless:
            print("cecli started in --headless mode, use ^C to exit...", flush=True)

        return_code = await app.run_async(headless=bool(args.headless))
        return_code = return_code if return_code else 0
    finally:
        if worker:
            worker.stop()

    # After clean shutdown, check if a reload was signaled
    # by the worker thread (ReloadProgramSignal caught in _async_run)
    if worker and getattr(worker, "_reload_signal", False):
        raise ReloadProgramSignal(
            "Reloading program configuration after TUI exit", from_coder=worker.coder
        )

    return return_code


def _pin_tqdm_lock():
    """Pin tqdm's class lock to a plain threading.RLock before the TUI starts.

    The Textual TUI redirects stdout/stderr to capture streams whose fileno()
    returns -1. tqdm's first use builds a multiprocessing.RLock whose resource
    tracker subprocess then fails with "ValueError: bad value(s) in fds_to_keep".
    Scoped to the TUI launch path so non-TUI runs keep tqdm's default lock.
    This makes the /help command work as intended.
    """
    try:
        import threading

        import tqdm.std

        tqdm.std.tqdm.set_lock(threading.RLock())
    except Exception:
        pass
