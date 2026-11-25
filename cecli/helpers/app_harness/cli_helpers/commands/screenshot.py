"""``screenshot`` command parameters."""

from __future__ import annotations

import argparse
from pathlib import Path

from ...client import AppHarnessError
from .. import runtime

NAME = "screenshot"
HELP = "Capture a window to a PNG file."


def run(args: argparse.Namespace) -> int:
    window = runtime.require_window(args)

    if window is None:
        return runtime.refuse(args, "missing --window")

    client = runtime.make_client(args)
    data = client.screenshot(window)

    if not data:
        return runtime.fail(
            args, AppHarnessError("backend_error", "the bridge returned an empty image"), 1
        )

    out_path = Path(args.out).expanduser()
    out_path.write_bytes(data)
    payload = {"path": str(out_path), "bytes": len(data)}
    return runtime.emit(args, payload, lambda: print(out_path))


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out", default="screenshot.png", help="Output PNG path.")
