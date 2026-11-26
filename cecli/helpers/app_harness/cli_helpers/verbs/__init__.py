"""One module per one-shot action verb; registered in help order."""

from __future__ import annotations

from ..common import common_parser
from . import (
    activate,
    click,
    dialogs,
    double_click,
    drag,
    focus,
    get_value,
    hover,
    invoke,
    keys,
    right_click,
    scroll,
    scroll_to,
    select,
    set_value,
    type_text,
)

VERBS = (
    click,
    double_click,
    right_click,
    hover,
    select,
    invoke,
    get_value,
    focus,
    set_value,
    keys,
    activate,
    scroll,
    scroll_to,
    drag,
    type_text,
    dialogs,
)


def register(subparsers) -> None:
    """Attach every verb module to ``subparsers``."""

    for module in VERBS:
        parser = subparsers.add_parser(module.NAME, help=module.HELP, parents=[common_parser()])
        module.add_arguments(parser)

        handler = getattr(module, "run", None)

        if handler is not None:
            parser.set_defaults(handler=handler)
