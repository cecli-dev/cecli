"""``scroll`` verb parameters."""

from __future__ import annotations

import argparse
from typing import Any

from ...client import AppClient
from ...models import ActionResult
from .. import runtime
from ..common import SCROLL_DIRECTIONS, add_pointer_options, add_target_options

NAME = "scroll"
HELP = "Scroll a window or element."


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
    if target is not None and getattr(args, "at", None) == "center":
        point = point or runtime.center_for_target(client, window, target)

    return client.scroll(
        window,
        args.direction,
        args.amount,
        target,
        point=point,
        delivery_mode=delivery_mode,
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    add_target_options(parser)
    add_pointer_options(parser)
    parser.add_argument("--direction", default="down", choices=SCROLL_DIRECTIONS)
    parser.add_argument("--amount", type=int, default=None, help="Scroll amount.")
