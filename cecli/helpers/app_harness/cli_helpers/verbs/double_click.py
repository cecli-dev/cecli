"""``double-click`` verb parameters."""

from __future__ import annotations

import argparse
from typing import Any

from ...client import AppClient
from ...models import ActionResult
from .. import runtime
from ..common import add_pointer_options, add_selector_option, add_target_options

NAME = "double-click"
HELP = "Double-click an element or point."


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
    if getattr(args, "at", None) == "center" and target is not None:
        point = runtime.center_for_target(client, window, target)

    return client.double_click(window, target, point, delivery_mode=delivery_mode)


def execute_locator(
    locator, args: argparse.Namespace, client: AppClient, window: str
) -> ActionResult:
    return locator.double_click()


def add_arguments(parser: argparse.ArgumentParser) -> None:
    add_target_options(parser)
    add_selector_option(parser)
    add_pointer_options(parser, buttons=True, counts=True)
