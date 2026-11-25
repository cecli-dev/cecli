"""``keys`` verb parameters."""

from __future__ import annotations

import argparse
from typing import Any

from ...client import AppClient, _target_for
from ...models import ActionResult
from .. import runtime
from ..common import add_selector_option, add_target_options

NAME = "keys"
HELP = "Send keystrokes to a window or element."


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
    return client.keys(window, args.keys, target, delivery_mode=delivery_mode)


def execute_locator(
    locator, args: argparse.Namespace, client: AppClient, window: str
) -> ActionResult:
    return client.keys(window, args.keys, _target_for(locator.wait()))


def add_arguments(parser: argparse.ArgumentParser) -> None:
    add_target_options(parser)
    add_selector_option(parser)
    parser.add_argument("--keys", required=True, help="Keystroke specification, e.g. ^s.")
