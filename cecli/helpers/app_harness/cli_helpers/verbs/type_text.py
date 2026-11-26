"""``type-text`` verb parameters."""

from __future__ import annotations

import argparse
from typing import Any

from ...client import AppClient
from ...models import ActionResult
from .. import runtime
from ..common import add_selector_option, add_target_options

NAME = "type-text"
HELP = "Type literal text into an element."


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
    return client.type_text(
        window,
        args.text,
        target,
        replace=args.replace,
        commit=args.commit,
    )


def execute_locator(
    locator, args: argparse.Namespace, client: AppClient, window: str
) -> ActionResult:
    return locator.type_text(args.text, replace=args.replace, commit=args.commit)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    add_target_options(parser)
    add_selector_option(parser)
    parser.add_argument("--text", required=True, help="Literal text to type.")
    parser.add_argument(
        "--replace", dest="replace", action="store_true", default=True, help="Select all first."
    )
    parser.add_argument(
        "--no-replace", dest="replace", action="store_false", help="Append instead of replacing."
    )
    parser.add_argument("--commit", action="store_true", help="Press Enter afterwards.")
