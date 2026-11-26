"""``doctor`` command parameters."""

from __future__ import annotations

import argparse

from .. import runtime

NAME = "doctor"
HELP = "Show permission and backend diagnostics."


def run(args: argparse.Namespace) -> int:
    client = runtime.make_client(args)
    report = client.doctor()
    return runtime.emit(args, report.to_dict(), lambda: runtime.print_doctor(report))


def add_arguments(parser: argparse.ArgumentParser) -> None:
    del parser
