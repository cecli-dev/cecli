"""Shared runtime used by the app-harness command and verb handlers."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

from .. import recipes, toon
from ..client import (
    AppClient,
    AppHarnessError,
    BridgeUnavailable,
    VersionMismatch,
    _target_for,
    _target_matches,
)
from ..models import ActionResult, Element, Snapshot

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_REFUSED = 2
EXIT_UNVERIFIED = 3
EXIT_UNAVAILABLE = 4

POINTER_COMMANDS = ("click", "double-click", "right-click", "hover")


def run_verb(execute: Callable, args: Any, locator_execute: Callable | None = None) -> int:
    """Resolve the target, run one verb, and emit its result."""

    window = require_window(args)

    if window is None:
        return refuse(args, "missing --window")

    command = args.command
    selector = getattr(args, "selector", None)
    delivery_mode = getattr(args, "delivery_mode", None)
    target: dict[str, Any] | None = None
    point: dict[str, int] | None = None

    if selector is not None:
        conflict = selector_conflict(args)

        if conflict is not None:
            return refuse(args, conflict)
    elif command not in ("keys", "activate"):
        if command in POINTER_COMMANDS and _point_from_args(args) is not None:
            point = _point_from_args(args)
        else:
            if (getattr(args, "x", None) is None) != (getattr(args, "y", None) is None):
                return refuse(args, "--x and --y must be supplied together")

            target = target_from_options(args)

            if not target and command not in ("scroll", "scroll-to", "drag"):
                return refuse(args, "missing element selector (--name, --role, --runtime-id, --id)")
    else:
        target = target_from_options(args)

    message = _validate_verb_args(args)

    if message is not None:
        return refuse(args, message)

    client = make_client(args)

    if selector is not None:
        if locator_execute is None:
            return refuse(args, f"--selector is not supported for {command}")

        locator = client.locator(window, selector, timeout_ms=args.timeout_ms)
        result = locator_execute(locator, args, client, window)
    else:
        result = execute(args, client, window, target, point, delivery_mode)

    code = action_exit(result)
    return emit(args, result.to_dict(), lambda: print_action(result), code=code)


def run_help(args: Any) -> int:
    """Run the help or recipes command, with or without a bridge."""

    if getattr(args, "list_apps", False):
        apps = recipes.list_apps()

        if getattr(args, "json", False):
            print(json.dumps(apps))
        else:
            print("\n".join(apps))

        return EXIT_OK

    app = getattr(args, "app", None)

    if app:
        try:
            text = recipes.help_text(app)
        except recipes.UnknownAppError as exc:
            print(f"error: {exc}", file=sys.stderr)
            print("\n".join(recipes.list_apps()))
            return EXIT_REFUSED

        try:
            doc = make_client(args).help()
        except (BridgeUnavailable, AppHarnessError):
            doc = None

        if getattr(args, "json", False):
            payload = {"app": app, "help": text}

            if doc:
                payload["bridge"] = doc

            print(json.dumps(payload, indent=2))
            return EXIT_OK

        print(text)

        if doc:
            print()
            print_help(doc)

        return EXIT_OK

    doc = make_client(args).help()
    return emit(
        args,
        doc,
        lambda: print_help(doc),
        format="json" if args.json else "toon",
    )


def make_client(args: Any) -> AppClient:
    return AppClient(ensure_bridge=args.ensure_bridge, timeout_ms=args.timeout_ms)


def require_window(args: Any) -> str | None:
    return args.window or None


def target_from_options(args: Any) -> dict[str, Any] | None:
    target: dict[str, Any] = {}

    for key in ("name", "role", "runtime_id", "id", "automation_id", "path"):
        value = getattr(args, key, None)

        if value is not None:
            target[key] = value

    return target or None


def selector_conflict(args: Any) -> str | None:
    """Return a message when ``--selector`` is mixed with a target flag."""

    flags = [
        "--" + name.replace("_", "-")
        for name in ("name", "role", "runtime_id", "id", "automation_id", "path", "x", "y")
        if getattr(args, name, None) is not None
    ]

    if not flags:
        return None

    return "--selector cannot be combined with " + ", ".join(flags)


def selector_from_kwargs(kwargs: dict[str, Any]) -> dict[str, Any] | None:
    selectors = {
        key: kwargs[key]
        for key in ("id", "runtime_id", "name", "role", "automation_id", "path")
        if kwargs.get(key) is not None
    }
    return selectors or None


def filter_elements(elements: list[Element], name: str | None, role: str | None) -> list[Element]:
    if name is None and role is None:
        return elements

    filtered = []

    for element in elements:
        if name is not None and (element.name or "").lower() != name.lower():
            continue

        if role is not None and element.control_type.lower() != role.lower():
            continue

        filtered.append(element)

    return filtered


def grid_target(client: AppClient, window: str, selector: str | None) -> dict[str, Any] | None:
    """Resolve a grid selector into a target reference for ``cell_at``."""

    if not selector:
        return None

    # The bridge resolves the target against its own latest snapshot, so make
    # sure it has one even when the script's first call was a server-side find.
    client.snapshot(window)

    return _target_for(client.locator(window, selector).wait())


def cell_at(
    client: AppClient,
    window: str,
    row: int,
    column: int,
    selector: str | None,
    delivery_mode: str | None = None,
) -> ActionResult:
    return client.cell_at(
        window,
        row,
        column,
        grid_target(client, window, selector),
        delivery_mode=delivery_mode,
    )


def center_for_target(client: AppClient, window: str, target: dict[str, Any]) -> dict[str, int]:
    """Resolve ``target`` in a fresh snapshot and return its centre."""

    snapshot = client.snapshot(window)

    for element in snapshot.elements:
        if _target_matches(element, target):
            center = element.center

            if center is None:
                raise AppHarnessError(
                    "invalid_request", f"element {element.id} has no bounds for a pointer action"
                )

            return center.to_dict()

    raise AppHarnessError("not_found", f"no element matches target {target!r} in window {window!r}")


def drag_destination(args: Any) -> dict[str, int] | None:
    """Return an explicit drag destination point when both axes were given."""

    if args.to_x is None or args.to_y is None:
        return None

    return {"x": args.to_x, "y": args.to_y}


def action_exit(result: ActionResult) -> int:
    if result.uncertain:
        return EXIT_UNVERIFIED

    if result.delivered and not result.verified:
        return EXIT_UNVERIFIED

    if not result.delivered:
        return EXIT_REFUSED

    return EXIT_OK


def emit(
    args: Any,
    payload: Any,
    printer: Callable[[], None],
    *,
    code: int = EXIT_OK,
    format: str | None = None,
) -> int:
    if format == "toon":
        print(toon.encode(payload))
    elif format == "json" or args.json:
        print(json.dumps(payload, indent=2, sort_keys=False))
    else:
        printer()

    return code


def print_emissions(emissions: list[Any]) -> None:
    """Print collected ``emit`` payloads as one JSON document."""

    if not emissions:
        return

    payload: Any = emissions[0] if len(emissions) == 1 else emissions
    print(json.dumps(payload, indent=2, sort_keys=False))


def refuse(args: Any, message: str) -> int:
    return fail(args, AppHarnessError("invalid_request", message), EXIT_REFUSED)


def fail(args: Any, error: Exception, code: int) -> int:
    message = str(error) or error.__class__.__name__

    if isinstance(error, BridgeUnavailable) and "ce-underscore" not in message:
        message = f"{message}; install and run ce-underscore to serve the bridge"

    if isinstance(error, BridgeUnavailable):
        message += wsl_hint()

    details = getattr(error, "details", None)
    message = f"{message}{details_hint(details)}"
    print(f"error: {message}", file=sys.stderr)

    if getattr(args, "json", False):
        error_payload: dict[str, Any] = {
            "type": getattr(error, "kind", "error"),
            "message": message,
        }

        if details:
            error_payload["details"] = details

        print(json.dumps({"ok": False, "error": error_payload}))

    return code


def details_hint(details: dict[str, Any] | None) -> str:
    """Render error details as a short suffix for the human message."""

    if not details:
        return ""

    candidates = details.get("candidates") or []

    if candidates:
        near = ", ".join(str(candidate) for candidate in candidates)
        return f" (near: {near})"

    last_observed = details.get("last_observed")

    if last_observed:
        return f" (last observed: {last_observed})"

    return ""


def version_hint(error: VersionMismatch) -> VersionMismatch:
    return VersionMismatch(
        f"{error.found}; update ce-underscore and cecli so versions match",
        error.expected,
    )


def print_state(info: Any) -> None:
    print(f"platform: {info.platform}")
    print(f"version: {info.version}")
    print(f"backend: {info.backend}")
    print(f"health: {info.health}")
    print(f"mode: {info.mode}")
    print(f"pid: {info.pid}")
    print(f"protocol_version: {info.protocol_version}")
    print(f"capabilities: {', '.join(info.capabilities) or '-'}")


def print_windows(windows: list[Any]) -> None:
    if not windows:
        print("(no windows)")
        return

    headers = ("HANDLE", "PID", "PROCESS", "TITLE")
    rows = [
        (
            window.handle or "-",
            str(window.pid),
            window.process_name or "-",
            window.title or "-",
        )
        for window in windows
    ]
    widths = [len(header) for header in headers]

    for row in rows:
        widths = [max(width, len(cell)) for width, cell in zip(widths, row)]

    print("  ".join(header.ljust(width) for header, width in zip(headers, widths)))

    for row in rows:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)))


def print_snapshot(snapshot: Snapshot, elements: list[Element]) -> None:
    window = snapshot.window

    if window is not None:
        print(f"window: {window.title or '<untitled>'} [{window.handle}] pid={window.pid}")
    else:
        print("window: <unknown>")

    for element in elements:
        indent = "  " * max(0, element.depth)
        print(f"{indent}{element}")

    if not elements:
        print("(no elements)")

    if snapshot.truncated:
        print(
            f"truncated: {len(snapshot.elements)}/{snapshot.total_elements} elements "
            f"(max_depth={snapshot.max_depth}, max_elements={snapshot.max_elements})"
        )

    for note in snapshot.notes:
        print(f"note: {note}")


def find_row(element: Element) -> dict[str, Any]:
    return {
        "id": element.id,
        "control_type": element.control_type,
        "name": element.name,
        "value": element.value,
        "path": element.path,
    }


def print_find(payload: dict[str, Any]) -> None:
    print(f"{payload.get('matches', 0)} match(es) for {payload.get('selector')!r}")

    for row in payload.get("elements") or []:
        print(f"[{row['id']}] {row['control_type']} {row.get('name') or ''}")

    if payload.get("truncated"):
        print("truncated: raise --limit to see every match")


def print_cell_at(payload: dict[str, Any]) -> None:
    print(f"cell: row={payload.get('row')} column={payload.get('column')}")
    print(f"id: {payload.get('id')}")
    print(f"name: {payload.get('name')}")
    print(f"value: {payload.get('value')}")
    print(f"path: {payload.get('path')}")


def print_action(result: ActionResult) -> None:
    if result.uncertain:
        status = "uncertain"
    elif not result.delivered:
        status = "not delivered"
    elif result.verified:
        status = "ok"
    else:
        status = "delivered but unverified"

    line = f"{result.action or 'action'}: {status}"

    if result.value is not None:
        line = f"{line} = {result.value}"

    if result.outcome:
        line = f"{line} [outcome: {result.outcome}]"

    if result.message:
        line = f"{line} ({result.message})"

    print(line)


def print_dialogs(dialogs: list[Any]) -> None:
    """Render the dialog list as one row per window."""

    if not dialogs:
        print("(no dialogs)")
        return

    for dialog in dialogs:
        print(f"{dialog.handle or '-'}  {dialog.title or '-'}  {dialog.process_name or '-'}")


def print_help(doc: dict[str, Any]) -> None:
    """Render the capability document as short sections."""

    print(f"backend: {doc.get('backend')} ({doc.get('platform')})")
    print(f"capabilities: {', '.join(doc.get('capabilities') or [])}")
    print(f"protocol: {doc.get('protocol_version')}")

    _print_capability_matrix(doc)

    for title, key in (
        ("Endpoints", "endpoints"),
        ("Actions", "actions"),
        ("Selectors", "selectors"),
    ):
        section = doc.get(key) or {}

        if not section:
            continue

        print(f"\n{title}:")

        for name, detail in section.items():
            print(f"  {name}: {detail}")

    notes = doc.get("notes") or []

    if notes:
        print("\nNotes:")

        for note in notes:
            print(f"  - {note}")


def print_doctor(report: Any) -> None:
    print(f"platform: {report.platform}")
    print(f"backend: {report.backend}")
    print(f"health: {report.health}")
    print("permissions:" if report.permissions else "permissions: -")

    for name, state in report.permissions.items():
        print(f"  {name}: {state}")

    print("checks:" if report.checks else "checks: -")

    for check in report.checks:
        print(f"  {'ok' if check.ok else 'FAIL'}  {check.name}: {check.detail}")

    for note in report.notes:
        print(f"note: {note}")


def wsl_hint(osrelease: str | None = None) -> str:
    """Return an extra hint when the CLI runs inside WSL."""

    text = osrelease if osrelease is not None else _read_osrelease()
    lowered = text.lower()

    if "microsoft" not in lowered and "wsl" not in lowered:
        return ""

    return (
        " (WSL detected: a bridge running on Windows is not reachable from WSL under"
        " NAT; run this command there through powershell.exe interop, or switch WSL to"
        " mirrored networking)"
    )


def _validate_verb_args(args: Any) -> str | None:
    """Return a refusal message when a verb flag is missing or invalid."""

    command = args.command

    if command == "set-value" and getattr(args, "value", None) is None:
        return "missing --value"

    if command == "keys" and not getattr(args, "keys", None):
        return "missing --keys"

    if command == "type-text" and not getattr(args, "text", None):
        return "missing --text"

    if command == "scroll-to":
        horizontal = getattr(args, "horizontal_percent", None)
        vertical = getattr(args, "vertical_percent", None)

        if horizontal is None and vertical is None:
            return "missing --horizontal-percent or --vertical-percent"

        for axis, value in (("horizontal", horizontal), ("vertical", vertical)):
            if value is not None and not 0 <= value <= 100:
                return f"--{axis}-percent must be between 0 and 100"

    return None


def _point_from_args(args: Any) -> dict[str, int] | None:
    """Return an explicit screen point when both axes were given."""

    x = getattr(args, "x", None)
    y = getattr(args, "y", None)

    if x is None or y is None:
        return None

    return {"x": x, "y": y}


def _print_capability_matrix(doc: dict[str, Any]) -> None:
    """Render the per-feature support matrix from the help document."""

    matrix = doc.get("capabilities_matrix") or {}

    if not isinstance(matrix, dict) or not matrix:
        return

    print("\nCapabilities:")

    for name, detail in matrix.items():
        if isinstance(detail, dict):
            summary = ", ".join(f"{key}={value}" for key, value in detail.items())
        else:
            summary = str(detail)

        print(f"  {name}: {summary}")


def _read_osrelease() -> str:
    try:
        return Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8")
    except OSError:
        return ""
