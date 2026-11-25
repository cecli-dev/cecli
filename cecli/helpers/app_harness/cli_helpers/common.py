"""Shared argparse options for the app-harness CLI parsers."""

from __future__ import annotations

import argparse

SCROLL_DIRECTIONS = ("up", "down", "left", "right")

EPILOG = (
    "Script mode is the control surface: pass a script path, '-' or\n"
    "nothing at all to run Python against one bridge connection.\n"
    "Helpers: state, windows, snapshot, find, locator, wait_for, cell_at,\n"
    "click, double_click, right_click, hover, drag, select,\n"
    "scroll_into_view, type_text, edit_text, dialogs, accept_dialog,\n"
    "cancel_dialog, dismiss_dialogs, spreadsheet, paste_tsv,\n"
    "set_clipboard, get_clipboard, keys, focus, scroll, scroll_to, activate,\n"
    "screenshot, wait_for_value, emit, expect, refresh.\n"
    "emit(payload) prints one JSON result; expect(cond, msg) stops the\n"
    "script when an assertion fails; snapshots are cached until an\n"
    "action clears the cache.\n\n"
    "One-shot verbs (click, double-click, right-click, hover, drag,\n"
    "select, type-text, dialogs, invoke, set-value, get-value, focus,\n"
    "keys, scroll, scroll-to, activate) remain as hidden aliases for single calls;\n"
    "run 'app-harness <verb> --help' for their flags.\n\n"
    "Help recipes: 'app-harness help --list-apps' and\n"
    "'app-harness help --app excel' work without a bridge.\n\n"
    "Example:\n"
    "  app-harness --window \"Untitled - Notepad\" - <<'PY'\n"
    "  cell = locator(\"text_field[name='Text Editor']\").wait()\n"
    "  cell.set_value('hello')\n"
    "  expect(cell.get_value().value == 'hello', 'write did not stick')\n"
    "  emit({'value': cell.get_value().value})\n"
    "  PY"
)


def add_global_options(parser: argparse.ArgumentParser, *, defaults: bool) -> None:
    """Add the options accepted before or after a subcommand."""

    default = None if defaults else argparse.SUPPRESS

    parser.add_argument(
        "--json",
        action="store_true",
        default=False if defaults else argparse.SUPPRESS,
        help="Print machine-readable JSON output.",
    )
    parser.add_argument(
        "--ensure-bridge",
        action="store_true",
        default=False if defaults else argparse.SUPPRESS,
        help="Start ce-underscore if no bridge is running.",
    )
    parser.add_argument(
        "--window", default=default, help="Target window title, process, or handle."
    )
    parser.add_argument(
        "--timeout-ms", type=int, default=default, help="Read timeout in milliseconds."
    )
    parser.add_argument(
        "--host",
        choices=("local", "windows"),
        default="local" if defaults else argparse.SUPPRESS,
        help="Run against the local bridge or forward to Windows from WSL.",
    )
    parser.add_argument(
        "--interop",
        action="store_true",
        default=False if defaults else argparse.SUPPRESS,
        help="Forward this invocation to a Windows Python when running in WSL.",
    )


def common_parser() -> argparse.ArgumentParser:
    """Return the parent parser every subcommand inherits."""

    parser = argparse.ArgumentParser(add_help=False)
    add_global_options(parser, defaults=False)

    return parser


def add_target_options(parser: argparse.ArgumentParser) -> None:
    """Add element-target and delivery options."""

    parser.add_argument("--name", default=None, help="Target element name.")
    parser.add_argument("--role", default=None, help="Target element role.")
    parser.add_argument("--runtime-id", dest="runtime_id", default=None, help="Runtime id.")
    parser.add_argument("--id", dest="id", type=int, default=None, help="Element id.")
    parser.add_argument(
        "--automation-id", dest="automation_id", default=None, help="Automation id."
    )
    parser.add_argument(
        "--path",
        default=None,
        help="Stable role/name path from snapshot output, e.g. Frame[Title]/Panel/Button[Save].",
    )
    parser.add_argument("--x", type=int, default=None, help="Screen x for click.")
    parser.add_argument("--y", type=int, default=None, help="Screen y for click.")
    parser.add_argument(
        "--delivery-mode",
        choices=("background", "foreground"),
        default=None,
        help=(
            "Restore the previous foreground window (background, default) or leave"
            " the target in front (foreground)."
        ),
    )


def add_selector_option(parser: argparse.ArgumentParser) -> None:
    """Add the ``--selector`` option."""

    parser.add_argument(
        "--selector",
        default=None,
        help="Playwright-style selector, e.g. \"Button[name='Save']\".",
    )


def add_pointer_options(
    parser: argparse.ArgumentParser, *, buttons: bool = False, counts: bool = False
) -> None:
    """Add element-centre and mouse-button options shared by pointer verbs."""

    parser.add_argument(
        "--at",
        choices=("center",),
        default=None,
        help="Use the element centre for a pointer action.",
    )

    if buttons:
        parser.add_argument(
            "--button",
            choices=("left", "right", "middle"),
            default="left",
            help="Mouse button.",
        )

    if counts:
        parser.add_argument("--count", type=int, default=1, help="Click count.")
