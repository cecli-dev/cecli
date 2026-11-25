"""``click`` verb parameters."""

from __future__ import annotations

import argparse
from typing import Any

from ...client import AppClient, AppHarnessError
from ...models import ActionResult
from .. import runtime
from ..common import add_pointer_options, add_selector_option, add_target_options

NAME = "click"
HELP = "Click an element or an explicit screen point."


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
    button = getattr(args, "button", "left")
    count = getattr(args, "count", 1)

    if getattr(args, "at", None) == "center" and target is not None:
        point = runtime.center_for_target(client, window, target)

    if point is not None and button == "left" and count == 1:
        return client.click(window, target, point, delivery_mode=delivery_mode)

    return client.action(
        window,
        "click",
        target=target,
        point=point,
        button=button,
        count=count,
        delivery_mode=delivery_mode,
    )


def execute_locator(
    locator, args: argparse.Namespace, client: AppClient, window: str
) -> ActionResult:
    button = getattr(args, "button", "left")
    count = getattr(args, "count", 1)

    if getattr(args, "at", None) == "center":
        element = locator.wait()
        center = element.center

        if center is None:
            raise AppHarnessError(
                "invalid_request", f"element {element.id} has no bounds for a pointer action"
            )

        return client.click_point(window, center, button=button, count=count)

    if button == "left" and count == 1:
        return locator.click()

    return locator.click(button=button, count=count)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    add_target_options(parser)
    add_selector_option(parser)
    add_pointer_options(parser, buttons=True, counts=True)
