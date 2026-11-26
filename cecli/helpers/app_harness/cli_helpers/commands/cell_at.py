"""``cell-at`` command parameters."""

from __future__ import annotations

import argparse

from .. import runtime

NAME = "cell-at"
HELP = "Resolve a spreadsheet cell by row and column."


def run(args: argparse.Namespace) -> int:
    window = runtime.require_window(args)

    if window is None:
        return runtime.refuse(args, "missing --window")

    client = runtime.make_client(args)
    grid = runtime.grid_target(client, window, args.grid)
    result = client.cell_at(window, args.row, args.column, grid)
    cell = result.element or {}
    payload = {
        "window": window,
        "row": args.row,
        "column": args.column,
        "id": cell.get("id"),
        "name": cell.get("name"),
        "value": cell.get("value") if cell.get("value") is not None else result.value,
        "path": cell.get("path"),
        "result": result.to_dict(),
    }
    return runtime.emit(
        args,
        payload,
        lambda: runtime.print_cell_at(payload),
        code=runtime.action_exit(result),
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--row", type=int, required=True, help="One-based row.")
    parser.add_argument("--column", type=int, required=True, help="One-based column.")
    parser.add_argument(
        "--grid",
        default=None,
        help="Selector for the grid or sheet; omit for the window's first grid.",
    )
