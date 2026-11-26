"""One module per app-harness command; registered in help order."""

from __future__ import annotations

from ..common import common_parser
from . import cell_at, doctor, find
from . import help as help_command
from . import recipes, screenshot, script, snapshot, state, windows

COMMANDS = (
    script,
    state,
    windows,
    doctor,
    help_command,
    recipes,
    snapshot,
    find,
    cell_at,
    screenshot,
)


def register(subparsers) -> None:
    """Attach every command module to ``subparsers``."""

    for module in COMMANDS:
        parser = subparsers.add_parser(module.NAME, help=module.HELP, parents=[common_parser()])
        module.add_arguments(parser)

        handler = getattr(module, "run", None)

        if handler is not None:
            parser.set_defaults(handler=handler)
