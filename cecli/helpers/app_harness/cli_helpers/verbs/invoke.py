"""``invoke`` verb parameters."""

from __future__ import annotations

import argparse
from typing import Any

from ...client import AppClient, _target_for
from ...models import ActionResult
from .. import runtime
from ..common import add_pointer_options, add_selector_option, add_target_options

NAME = "invoke"
HELP = "Invoke the default action of an element."


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
    if target is not None and getattr(args, "at", None) == "center":
        point = point or runtime.center_for_target(client, window, target)

    return client.invoke(window, target, point=point, delivery_mode=delivery_mode)


def execute_locator(
    locator, args: argparse.Namespace, client: AppClient, window: str
) -> ActionResult:
    element = locator.wait()
    point = None

    if getattr(args, "at", None) == "center" and element.center is not None:
        point = element.center.to_dict()

    return client.invoke(
        window,
        _target_for(element),
        point=point,
        delivery_mode=getattr(args, "delivery_mode", None),
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    add_target_options(parser)
    add_selector_option(parser)
    add_pointer_options(parser)
