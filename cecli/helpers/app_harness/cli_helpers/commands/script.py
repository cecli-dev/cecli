"""``script`` command parameters."""

from __future__ import annotations

import argparse

NAME = "script"
HELP = "Run a Python script against one bridge connection (default: stdin)."


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("file", nargs="?", default="-", help="Script file, or '-' to read stdin.")
