"""``snapshot`` command parameters."""

from __future__ import annotations

import argparse

from .. import runtime

NAME = "snapshot"
HELP = "Print the accessibility tree for a window."


def run(args: argparse.Namespace) -> int:
    window = runtime.require_window(args)

    if window is None:
        return runtime.refuse(args, "missing --window")

    client = runtime.make_client(args)
    snapshot = client.snapshot(
        window,
        args.max_depth,
        args.max_elements,
        args.exclude_role,
        actionable=args.actionable,
    )
    elements = runtime.filter_elements(snapshot.elements, args.name, args.role)
    fmt = "json" if args.json else args.format
    lean = not args.verbose and fmt != "json"
    payload = snapshot.to_dict(lean=lean)

    if args.name or args.role:
        payload["elements"] = [element.to_dict(lean=lean) for element in elements]

    if snapshot.notes:
        payload["notes"] = list(snapshot.notes)

    return runtime.emit(
        args,
        payload,
        lambda: runtime.print_snapshot(snapshot, elements),
        format=fmt,
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-depth", type=int, default=None, help="Maximum tree depth.")
    parser.add_argument("--max-elements", type=int, default=None, help="Maximum elements.")
    parser.add_argument("--name", default=None, help="Only show elements with this name.")
    parser.add_argument("--role", default=None, help="Only show elements with this role.")
    parser.add_argument(
        "--exclude-role",
        action="append",
        default=[],
        metavar="ROLE",
        help="Skip whole subtrees with this role (repeatable), e.g. --exclude-role Menu.",
    )
    parser.add_argument(
        "--actionable",
        action="store_true",
        help="Prune anonymous containers and reparent their children.",
    )
    parser.add_argument(
        "--format",
        choices=("toon", "json", "lines"),
        default="toon",
        help="Output format: TOON (default, compact tabular record), JSON, or a tree.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include geometry, runtime ids, pattern lists and paths.",
    )
