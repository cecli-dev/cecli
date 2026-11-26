"""``state`` command parameters."""

from __future__ import annotations

import argparse

from .. import runtime

NAME = "state"
HELP = "Show bridge identity and capabilities."


def run(args: argparse.Namespace) -> int:
    client = runtime.make_client(args)
    info = client.state()
    return runtime.emit(args, info.to_dict(), lambda: runtime.print_state(info))


def add_arguments(parser: argparse.ArgumentParser) -> None:
    del parser
