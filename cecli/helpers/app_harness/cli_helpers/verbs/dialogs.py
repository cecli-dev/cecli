"""``dialogs`` verb parameters."""

from __future__ import annotations

import argparse

from .. import runtime

NAME = "dialogs"
HELP = "List blocking dialog windows."


def run(args: argparse.Namespace) -> int:
    client = runtime.make_client(args)
    dialogs = client.dialogs()
    payload = {"dialogs": [dialog.to_dict() for dialog in dialogs]}
    return runtime.emit(
        args,
        payload,
        lambda: runtime.print_dialogs(dialogs),
        format="json" if args.json else "toon",
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    del parser
