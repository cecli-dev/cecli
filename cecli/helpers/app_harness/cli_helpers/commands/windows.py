"""``windows`` command parameters."""

from __future__ import annotations

import argparse

from .. import runtime

NAME = "windows"
HELP = "List visible top-level windows."


def run(args: argparse.Namespace) -> int:
    client = runtime.make_client(args)
    windows = client.windows()
    return runtime.emit(
        args,
        [window.to_dict() for window in windows],
        lambda: runtime.print_windows(windows),
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    del parser
