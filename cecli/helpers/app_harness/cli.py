"""Command-line interface for the app-harness bridge.

Script mode is the default surface: a bare script path, ``-``, or no subcommand
at all runs a Python program against one long-lived
:class:`~cecli.helpers.app_harness.client.AppClient` and exposes helpers in the program
namespace. One-shot subcommands remain for single calls.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Callable, Sequence

from . import clipboard, interop
from .cli_helpers import commands as command_registry
from .cli_helpers import runtime
from .cli_helpers import verbs as verb_registry
from .cli_helpers.common import EPILOG, add_global_options
from .client import (
    AppClient,
    AppHarnessError,
    BridgeUnavailable,
    Locator,
    VersionMismatch,
)
from .models import ActionResult, Element, Snapshot
from .spreadsheet import Spreadsheet

EXIT_OK = runtime.EXIT_OK
EXIT_INTERNAL = runtime.EXIT_INTERNAL
EXIT_REFUSED = runtime.EXIT_REFUSED
EXIT_UNVERIFIED = runtime.EXIT_UNVERIFIED
EXIT_UNAVAILABLE = runtime.EXIT_UNAVAILABLE


COMMANDS = (
    "script",
    "state",
    "windows",
    "doctor",
    "help",
    "recipes",
    "snapshot",
    "find",
    "cell-at",
    "screenshot",
    "click",
    "invoke",
    "get-value",
    "set-value",
    "keys",
    "focus",
    "scroll",
    "scroll-to",
    "activate",
)

VALUE_FLAGS = ("--window", "--timeout-ms", "--host")

HIDDEN_COMMANDS = (
    "click",
    "invoke",
    "get-value",
    "set-value",
    "keys",
    "focus",
    "scroll",
    "scroll-to",
    "activate",
    "double-click",
    "right-click",
    "hover",
    "drag",
    "select",
    "type-text",
    "dialogs",
)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the app-harness command and return a process exit code."""

    args: argparse.Namespace | None = None

    try:
        forwarded = interop.maybe_forward(argv)

        if forwarded is not None:
            return forwarded

        tokens = _implicit_script(argv)
        parser = _parser_for(tokens)
        args = parser.parse_args(tokens)

        if args.command in (None, "script"):
            return _run_script(args)

        return _run_command(args)
    except BridgeUnavailable as exc:
        return runtime.fail(args, exc, EXIT_UNAVAILABLE)
    except VersionMismatch as exc:
        return runtime.fail(args, runtime.version_hint(exc), EXIT_UNAVAILABLE)
    except AppHarnessError as exc:
        code = EXIT_INTERNAL if exc.kind == "expectation_failed" else EXIT_REFUSED
        return runtime.fail(args, exc, code)
    except KeyboardInterrupt:
        return runtime.fail(args, AppHarnessError("interrupted", "interrupted"), EXIT_INTERNAL)
    except Exception as exc:  # noqa: BLE001 - top-level guard for the CLI contract
        return runtime.fail(args, exc, EXIT_INTERNAL)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the ``app-harness`` command."""

    parser = argparse.ArgumentParser(
        prog="app-harness",
        description="Control native applications through the ce-underscore bridge.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG,
    )
    add_global_options(parser, defaults=True)

    subparsers = parser.add_subparsers(dest="command")
    command_registry.register(subparsers)

    return parser


def build_verb_parser() -> argparse.ArgumentParser:
    """Build the parser for the hidden one-shot verbs.

    These remain for single calls and for humans, but the default help advertises
    script mode only: a sequence of calls belongs in a script.
    """

    parser = argparse.ArgumentParser(
        prog="app-harness",
        description="One-shot action verbs (prefer script mode for sequences).",
    )
    add_global_options(parser, defaults=True)
    subparsers = parser.add_subparsers(dest="command")
    verb_registry.register(subparsers)

    return parser


def _run_command(args: argparse.Namespace) -> int:
    handler = getattr(args, "handler", None)

    if handler is None:
        return EXIT_REFUSED

    return handler(args)


def _run_script(args: argparse.Namespace) -> int:
    source = getattr(args, "file", "-")

    if source in (None, "-"):
        if sys.stdin.isatty():
            build_parser().print_help(sys.stderr)
            return EXIT_REFUSED

        program = sys.stdin.read()
    else:
        try:
            program = Path(source).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            return runtime.fail(
                args,
                AppHarnessError("invalid_request", f"cannot read {source}: {exc}"),
                EXIT_REFUSED,
            )

    if not program.strip():
        return EXIT_OK

    client = runtime.make_client(args)
    client.enable_snapshot_cache()
    results: list[ActionResult] = []
    emissions: list[Any] = []
    namespace = _script_namespace(client, args.window, results, emissions)

    try:
        exec(compile(program, "<app-harness>", "exec"), namespace)
    except SystemExit as exc:
        runtime.print_emissions(emissions)
        return int(exc.code) if isinstance(exc.code, int) else EXIT_INTERNAL
    except BaseException:
        runtime.print_emissions(emissions)
        raise

    runtime.print_emissions(emissions)

    worst = EXIT_OK

    for result in results:
        code = runtime.action_exit(result)

        if code == EXIT_REFUSED:
            return EXIT_REFUSED

        if code != EXIT_OK:
            worst = EXIT_UNVERIFIED

    return worst


def _script_namespace(
    client: AppClient,
    default_window: str | None,
    results: list[ActionResult],
    emissions: list[Any],
) -> dict[str, Any]:
    """Build the namespace exposed to a stdin script."""

    def window_for(window: str | None) -> str:
        resolved = window or default_window

        if not resolved:
            raise AppHarnessError("invalid_request", "missing window argument")

        return resolved

    def record(result: ActionResult) -> ActionResult:
        results.append(result)
        return result

    def state() -> Any:
        return client.state()

    def windows() -> Any:
        return client.windows()

    def snapshot(
        window: str | None = None,
        max_depth: int | None = None,
        max_elements: int | None = None,
        actionable: bool = False,
    ) -> Snapshot:
        return client.snapshot(window_for(window), max_depth, max_elements, actionable=actionable)

    def invoke(
        window: str | None = None,
        delivery_mode: str | None = None,
        **selectors: Any,
    ) -> ActionResult:
        return record(
            client.invoke(
                window_for(window),
                runtime.selector_from_kwargs(selectors),
                delivery_mode=delivery_mode,
            )
        )

    def set_value(
        value: str,
        window: str | None = None,
        delivery_mode: str | None = None,
        **selectors: Any,
    ) -> ActionResult:
        return record(
            client.set_value(
                window_for(window),
                value,
                runtime.selector_from_kwargs(selectors),
                delivery_mode=delivery_mode,
            )
        )

    def get_value(
        window: str | None = None,
        delivery_mode: str | None = None,
        **selectors: Any,
    ) -> ActionResult:
        return record(
            client.get_value(
                window_for(window),
                runtime.selector_from_kwargs(selectors),
                delivery_mode=delivery_mode,
            )
        )

    def click(
        window: str | None = None,
        x: int | None = None,
        y: int | None = None,
        delivery_mode: str | None = None,
        **selectors: Any,
    ) -> ActionResult:
        point = {"x": x, "y": y} if x is not None and y is not None else None
        return record(
            client.click(
                window_for(window),
                runtime.selector_from_kwargs(selectors),
                point,
                delivery_mode=delivery_mode,
            )
        )

    def keys(
        keys: str,
        window: str | None = None,
        delivery_mode: str | None = None,
        **selectors: Any,
    ) -> ActionResult:
        return record(
            client.keys(
                window_for(window),
                keys,
                runtime.selector_from_kwargs(selectors),
                delivery_mode=delivery_mode,
            )
        )

    def wait_for_value(
        value: str,
        timeout_ms: int | None = None,
        interval_ms: int = 100,
        window: str | None = None,
        **selectors: Any,
    ) -> ActionResult:
        """Poll ``get_value`` until it reports ``value`` or the timeout expires."""

        target = runtime.selector_from_kwargs(selectors)
        deadline = time.monotonic() + max(1, timeout_ms or client.timeout_ms) / 1000.0
        result = client.get_value(window_for(window), target)

        while result.value != value:
            if time.monotonic() >= deadline:
                raise AppHarnessError(
                    "timeout",
                    f"value did not become {value!r}; last read {result.value!r}",
                )

            time.sleep(interval_ms / 1000.0)
            result = client.get_value(window_for(window), target)

        return record(result)

    def activate(window: str | None = None) -> ActionResult:
        return record(client.activate(window_for(window)))

    def batch(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return client.batch(operations)

    def focus(
        window: str | None = None,
        delivery_mode: str | None = None,
        **selectors: Any,
    ) -> ActionResult:
        return record(
            client.focus(
                window_for(window),
                runtime.selector_from_kwargs(selectors),
                delivery_mode=delivery_mode,
            )
        )

    def scroll(
        window: str | None = None,
        direction: str = "down",
        amount: int | None = None,
        delivery_mode: str | None = None,
        **selectors: Any,
    ) -> ActionResult:
        return record(
            client.scroll(
                window_for(window),
                direction,
                amount,
                runtime.selector_from_kwargs(selectors),
                delivery_mode=delivery_mode,
            )
        )

    def scroll_to(
        horizontal_percent: float | None = None,
        vertical_percent: float | None = None,
        window: str | None = None,
        delivery_mode: str | None = None,
        **selectors: Any,
    ) -> ActionResult:
        return record(
            client.scroll_to(
                window_for(window),
                horizontal_percent,
                vertical_percent,
                runtime.selector_from_kwargs(selectors),
                delivery_mode=delivery_mode,
            )
        )

    def find(selector: str, limit: int = 50, window: str | None = None) -> list[Element]:
        target = window_for(window)
        matches, _, _ = client.find_elements(target, selector, limit)
        locator = client.locator(target, selector, limit=limit)
        return _FindResult(matches, locator, record)

    def cell_at(
        row: int,
        column: int,
        grid: str | None = None,
        window: str | None = None,
        delivery_mode: str | None = None,
    ) -> ActionResult:
        """Address a cell, optionally scoped to the grid matched by ``grid``."""

        return record(runtime.cell_at(client, window_for(window), row, column, grid, delivery_mode))

    def locator(selector: str, timeout_ms: int = 5000, window: str | None = None) -> Locator:
        """Bind ``selector`` to the window for re-resolved single-element actions."""

        return client.locator(window_for(window), selector, timeout_ms=timeout_ms)

    def wait_for(
        selector: str,
        timeout_ms: int = 5000,
        window: str | None = None,
        visible: bool | None = None,
        enabled: bool | None = None,
        value: str | None = None,
    ) -> Element:
        """Wait for the single match, optionally also for a state to hold."""

        locator = client.locator(window_for(window), selector, timeout_ms=timeout_ms)

        if visible is None and enabled is None and value is None:
            return locator.wait()

        return locator.wait_for(
            visible=visible, enabled=enabled, value=value, timeout_ms=timeout_ms
        )

    def double_click(
        window: str | None = None,
        x: int | None = None,
        y: int | None = None,
        delivery_mode: str | None = None,
        **selectors: Any,
    ) -> ActionResult:
        point = {"x": x, "y": y} if x is not None and y is not None else None
        return record(
            client.double_click(
                window_for(window),
                runtime.selector_from_kwargs(selectors),
                point,
                delivery_mode=delivery_mode,
            )
        )

    def right_click(
        window: str | None = None,
        x: int | None = None,
        y: int | None = None,
        delivery_mode: str | None = None,
        **selectors: Any,
    ) -> ActionResult:
        point = {"x": x, "y": y} if x is not None and y is not None else None
        return record(
            client.right_click(
                window_for(window),
                runtime.selector_from_kwargs(selectors),
                point,
                delivery_mode=delivery_mode,
            )
        )

    def hover(
        window: str | None = None,
        x: int | None = None,
        y: int | None = None,
        delivery_mode: str | None = None,
        **selectors: Any,
    ) -> ActionResult:
        point = {"x": x, "y": y} if x is not None and y is not None else None
        return record(
            client.hover(
                window_for(window),
                runtime.selector_from_kwargs(selectors),
                point,
                delivery_mode=delivery_mode,
            )
        )

    def drag(
        start: Any,
        end: Any,
        window: str | None = None,
        duration_ms: int | None = None,
        delivery_mode: str | None = None,
    ) -> ActionResult:
        return record(
            client.drag(
                window_for(window),
                start,
                end,
                duration_ms=duration_ms,
                delivery_mode=delivery_mode,
            )
        )

    def select(
        window: str | None = None,
        delivery_mode: str | None = None,
        **selectors: Any,
    ) -> ActionResult:
        return record(
            client.select(
                window_for(window),
                runtime.selector_from_kwargs(selectors),
                delivery_mode=delivery_mode,
            )
        )

    def scroll_into_view(
        window: str | None = None,
        delivery_mode: str | None = None,
        **selectors: Any,
    ) -> ActionResult:
        return record(
            client.scroll_into_view(
                window_for(window),
                runtime.selector_from_kwargs(selectors),
                delivery_mode=delivery_mode,
            )
        )

    def type_text(
        text: str,
        window: str | None = None,
        replace: bool = True,
        commit: bool = False,
        **selectors: Any,
    ) -> ActionResult:
        return record(
            client.type_text(
                window_for(window),
                text,
                runtime.selector_from_kwargs(selectors),
                replace=replace,
                commit=commit,
            )
        )

    def edit_text(text: str, window: str | None = None, **selectors: Any) -> ActionResult:
        return record(
            client.edit_text(window_for(window), text, runtime.selector_from_kwargs(selectors))
        )

    def dialogs() -> Any:
        return client.dialogs()

    def accept_dialog(selector: str | None = None, button: str | None = None) -> ActionResult:
        return record(client.accept_dialog(selector, button))

    def cancel_dialog(selector: str | None = None) -> ActionResult:
        return record(client.cancel_dialog(selector))

    def dismiss_dialogs() -> list[ActionResult]:
        return [record(result) for result in client.dismiss_dialogs()]

    def spreadsheet(
        window: str | None = None, grid: Any = None, app: str | None = None
    ) -> Spreadsheet:
        return Spreadsheet(client, window_for(window), grid=grid, app=app)

    def paste_tsv(
        anchor: str,
        rows_or_text: Any,
        window: str | None = None,
        grid: Any = None,
        app: str | None = None,
    ) -> ActionResult:
        sheet = spreadsheet(window=window, grid=grid, app=app)
        return record(sheet.paste_tsv(anchor, rows_or_text))

    def set_clipboard(text: str) -> None:
        clipboard.set_text(text)

    def get_clipboard() -> str:
        return clipboard.get_text()

    def screenshot(window: str | None = None) -> bytes:
        return client.screenshot(window_for(window))

    def emit(payload: Any) -> None:
        """Collect one structured result for the final JSON output."""

        emissions.append(payload)

    def expect(condition: Any, message: str = "expectation failed") -> None:
        """Stop the script when ``condition`` is falsy."""

        if not condition:
            raise AppHarnessError("expectation_failed", message)

    def refresh() -> int:
        """Drop cached snapshots so the next read hits the bridge."""

        return client.refresh()

    return {
        "state": state,
        "windows": windows,
        "snapshot": snapshot,
        "find": find,
        "locator": locator,
        "wait_for": wait_for,
        "cell_at": cell_at,
        "click": click,
        "double_click": double_click,
        "right_click": right_click,
        "hover": hover,
        "drag": drag,
        "select": select,
        "scroll_into_view": scroll_into_view,
        "type_text": type_text,
        "edit_text": edit_text,
        "dialogs": dialogs,
        "accept_dialog": accept_dialog,
        "cancel_dialog": cancel_dialog,
        "dismiss_dialogs": dismiss_dialogs,
        "spreadsheet": spreadsheet,
        "paste_tsv": paste_tsv,
        "set_clipboard": set_clipboard,
        "get_clipboard": get_clipboard,
        "invoke": invoke,
        "set_value": set_value,
        "get_value": get_value,
        "wait_for_value": wait_for_value,
        "keys": keys,
        "focus": focus,
        "activate": activate,
        "batch": batch,
        "scroll": scroll,
        "scroll_to": scroll_to,
        "screenshot": screenshot,
        "emit": emit,
        "expect": expect,
        "refresh": refresh,
    }


class _FindResult(list):
    """Matches that also drive the selector they came from.

    Script mode returns this instead of a bare list so
    ``find("Button[name='Save']").click()`` re-resolves the element immediately
    before acting, exactly like :meth:`AppClient.locator`.
    """

    def __init__(self, matches: list[Element], locator: Any, record: Callable) -> None:
        super().__init__(matches)
        self.locator = locator
        self._record = record

    def click(self) -> ActionResult:
        return self._record(self.locator.click())

    def invoke(self) -> ActionResult:
        return self._record(self.locator.invoke())

    def set_value(self, value: str) -> ActionResult:
        return self._record(self.locator.set_value(value))

    def get_value(self) -> ActionResult:
        return self._record(self.locator.get_value())

    def focus(self) -> ActionResult:
        return self._record(self.locator.focus())


def _implicit_script(argv: Sequence[str] | None) -> list[str]:
    """Insert ``script`` before a bare path so a script file is the default."""

    tokens = list(sys.argv[1:] if argv is None else argv)
    index = _first_positional(tokens)

    if index is None:
        return tokens

    token = tokens[index]

    if token in COMMANDS or not _looks_like_script(token):
        return tokens

    return [*tokens[:index], "script", *tokens[index:]]


def _parser_for(tokens: Sequence[str]) -> argparse.ArgumentParser:
    """Pick the parser that knows the command in ``tokens``."""

    index = _first_positional(list(tokens))

    if index is not None and tokens[index] in HIDDEN_COMMANDS:
        return build_verb_parser()

    return build_parser()


def _looks_like_script(token: str) -> bool:
    return token == "-" or token.endswith(".py") or "/" in token or "\\" in token


def _first_positional(tokens: list[str]) -> int | None:
    skip_value = False

    for index, token in enumerate(tokens):
        if skip_value:
            skip_value = False
            continue

        if token == "--":
            return index + 1 if index + 1 < len(tokens) else None

        if token == "-":
            return index

        if token.startswith("-"):
            if "=" not in token and token in VALUE_FLAGS:
                skip_value = True

            continue

        return index

    return None


if __name__ == "__main__":
    raise SystemExit(main())
