"""``drag`` verb parameters."""

from __future__ import annotations

import argparse
from typing import Any

from ...client import AppClient, AppHarnessError
from ...models import ActionResult
from .. import runtime
from ..common import add_selector_option, add_target_options

NAME = "drag"
HELP = "Drag from a point or element to a point or element."


def run(args: argparse.Namespace) -> int:
    return runtime.run_verb(execute, args)


def execute(
    args: argparse.Namespace,
    client: AppClient,
    window: str,
    target: dict[str, Any] | None,
    point: dict[str, int] | None,
    delivery_mode: str | None,
) -> ActionResult:
    start = point

    if start is None and target is not None:
        start = runtime.center_for_target(client, window, target)

    if start is None:
        raise AppHarnessError("invalid_request", "drag needs --x/--y or an element target")

    end = runtime.drag_destination(args)

    if end is None and args.to_name:
        end = runtime.center_for_target(client, window, {"name": args.to_name})

    if end is None:
        raise AppHarnessError("invalid_request", "drag needs --to-x/--to-y or --to-name")

    return client.drag(
        window, start, end, duration_ms=args.duration_ms, delivery_mode=delivery_mode
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    add_target_options(parser)
    add_selector_option(parser)
    parser.add_argument("--to-x", type=int, default=None, help="Destination screen x.")
    parser.add_argument("--to-y", type=int, default=None, help="Destination screen y.")
    parser.add_argument("--to-name", default=None, help="Destination element name.")
    parser.add_argument(
        "--duration-ms", type=int, default=None, help="Drag duration in milliseconds."
    )
