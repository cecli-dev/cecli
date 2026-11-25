"""``get-value`` verb parameters."""

from __future__ import annotations

import argparse
from typing import Any

from ...client import AppClient
from ...models import ActionResult
from .. import runtime
from ..common import add_pointer_options, add_selector_option, add_target_options

NAME = "get-value"
HELP = "Read an element value."


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
    return client.get_value(window, target, delivery_mode=delivery_mode)


def execute_locator(
    locator, args: argparse.Namespace, client: AppClient, window: str
) -> ActionResult:
    return locator.get_value()


def add_arguments(parser: argparse.ArgumentParser) -> None:
    add_target_options(parser)
    add_selector_option(parser)
    add_pointer_options(parser)
