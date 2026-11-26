"""``scroll-to`` verb parameters."""

from __future__ import annotations

import argparse
from typing import Any

from ...client import AppClient
from ...models import ActionResult
from .. import runtime
from ..common import add_selector_option, add_target_options

NAME = "scroll-to"
HELP = "Scroll a window or element to a percentage."


def run(args: argparse.Namespace) -> int:
    return runtime.run_verb(execute, args, execute_locator)


def execute(
    args: argparse.Namespace,
    client: AppClient,
    window: str,
    target: dict[str, Any] | None,
    point: dict[str, int] | None,
    delivery_mode: str | None,
) -> ActionResult:
    return client.scroll_to(
        window,
        args.horizontal_percent,
        args.vertical_percent,
        target,
        delivery_mode=delivery_mode,
    )


def execute_locator(
    locator, args: argparse.Namespace, client: AppClient, window: str
) -> ActionResult:
    return locator.scroll_to(args.horizontal_percent, args.vertical_percent)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    add_target_options(parser)
    add_selector_option(parser)
    parser.add_argument("--horizontal-percent", type=float, default=None)
    parser.add_argument("--vertical-percent", type=float, default=None)
