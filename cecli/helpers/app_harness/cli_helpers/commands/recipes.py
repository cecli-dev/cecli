"""``recipes`` command parameters."""

from __future__ import annotations

import argparse

from .. import runtime

NAME = "recipes"
HELP = "Show spreadsheet app recipes for Excel and LibreOffice."


def run(args: argparse.Namespace) -> int:
    return runtime.run_help(args)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--app", default=None, help="Show the recipe for one app.")
    parser.add_argument(
        "--list-apps",
        dest="list_apps",
        action="store_true",
        help="List the apps that have recipes.",
    )
