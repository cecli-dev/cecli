"""``find`` command parameters."""

from __future__ import annotations

import argparse

from .. import runtime

NAME = "find"
HELP = "Find elements in a window with a selector."


def run(args: argparse.Namespace) -> int:
    window = runtime.require_window(args)

    if window is None:
        return runtime.refuse(args, "missing --window")

    client = runtime.make_client(args)
    matches, count, truncated = client.find_elements(window, args.selector, args.limit)
    payload = {
        "window": window,
        "selector": args.selector,
        "matches": count,
        "truncated": truncated,
        "elements": [runtime.find_row(element) for element in matches],
    }
    return runtime.emit(
        args,
        payload,
        lambda: runtime.print_find(payload),
        format="json" if args.json else "toon",
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("selector", help="Selector, e.g. \"Button[name='Save']\".")
    parser.add_argument("--limit", type=int, default=50, help="Maximum matches to print.")
