"""Textual TUI interface for cecli.

This package provides an experimental TUI (Terminal User Interface) for cecli
using the Textual framework. Launch with: cecli --tui
"""

import queue
import weakref

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
    worker = CoderWorker(coder, output_queue, input_queue)
    app = TUI(worker, output_queue, input_queue, args)

    # Set weak reference to TUI app on the coder instance
    coder.tui = weakref.ref(app)

    return_code = await app.run_async()

    worker.stop()
    return return_code if return_code else 0
