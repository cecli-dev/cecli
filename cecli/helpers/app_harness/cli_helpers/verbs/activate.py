"""``activate`` verb parameters."""

from __future__ import annotations

import argparse
from typing import Any

from ...client import AppClient
from ...models import ActionResult
from .. import runtime

NAME = "activate"
HELP = "Raise and focus a window."


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
    return client.activate(window)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    del parser
