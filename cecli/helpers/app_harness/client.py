"""Discovery and HTTP client for the app-harness bridge.

The bridge is a mode of the ``ce-underscore`` binary. It writes ``bridge.json``
with its loopback port and a per-user token. This module finds that file,
validates versions, and sends requests with the token attached.
"""

from __future__ import annotations

import ipaddress
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from . import clipboard
from .constants import DEFAULT_LOCATOR_LIMIT
from .locator import CompoundSelector, Locator, MatchPlan, compile_match, parse, select
from .models import (
    ActionResult,
    DoctorReport,
    Element,
    Point,
    Snapshot,
    StateInfo,
    Window,
    error_details,
)

EXPECTED_BRIDGE_VERSION = "0.1.0"
CONNECT_TIMEOUT_SECONDS = 2.0
DEFAULT_READ_TIMEOUT_MS = 30_000
_ROUTE_FALLBACK_KINDS = ("unsupported", "not_found", "unknown_route", "route_not_found")
_TEXT_FALLBACK_KINDS = (
    "unsupported",
    "not_supported",
    "input_blocked",
    "invalid_request",
    "not_found",
    "target_not_found",
    "stale_target",
)
_DIALOG_ACCEPT_BUTTONS = ("OK", "Yes", "Continue", "Save")
_DIALOG_CANCEL_BUTTONS = ("Cancel", "No", "Close")
_DIALOG_BUTTON_MISSES = ("not_found", "timeout", "stale_target", "invalid_request")
_DIALOG_BUTTON_TIMEOUT_MS = 750
_DIALOG_DISMISS_LIMIT = 10
_DIALOG_CLASS_NAMES = ("#32770", "NUIDialog", "MsoDlg")


class AppHarnessError(Exception):
    """An error reported by the bridge or the local client."""

    def __init__(self, kind: str, message: str, details: dict[str, Any] | None = None) -> None:
        """Record the kind and message; ``details`` holds bridge recovery hints."""

        super().__init__(message)
        self.kind = kind
        self.message = message
        parsed = error_details(details) or {}

        for key, value in (details or {}).items():
            parsed.setdefault(key, value)

        self.details = parsed or None

    def __str__(self) -> str:
        return self.message


class BridgeUnavailable(AppHarnessError):
    """The bridge is missing, stale, or refusing connections."""

    def __init__(self, message: str) -> None:
        super().__init__("bridge_unavailable", message)


class VersionMismatch(AppHarnessError):
    """``bridge.json`` was written by an incompatible bridge."""

    def __init__(self, found: str, expected: str = EXPECTED_BRIDGE_VERSION) -> None:
        super().__init__(
            "version_mismatch",
            f"bridge version {found or '<missing>'} does not match client version {expected}",
        )
        self.found = found
        self.expected = expected


@dataclass
class BridgeFile:
    """Contents of ``bridge.json``."""

    version: str = ""
    platform: str = ""
    host: str = "127.0.0.1"
    port: int = 0
    token: str = ""
    pid: int = 0
    mode: str = ""
    started_at: str = ""
    path: Path | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: Path | None = None) -> BridgeFile:
        """Build a bridge description from decoded JSON."""

        return cls(
            version=_as_str(data.get("version")),
            platform=_as_str(data.get("platform")),
            host=_as_str(data.get("host"), default="127.0.0.1"),
            port=_as_int(data.get("port")),
            token=_as_str(data.get("token")),
            pid=_as_int(data.get("pid")),
            mode=_as_str(data.get("mode")),
            started_at=_as_str(data.get("started_at")),
            path=path,
        )

    @property
    def base_url(self) -> str:
        """Loopback base URL for requests."""

        return f"http://{self.host}:{self.port}"


def discover_bridge_file() -> Path | None:
    """Return the ``bridge.json`` path for this user, or ``None`` when absent."""

    override = os.environ.get("CECLI_BRIDGE_FILE")

    if override:
        return Path(override).expanduser()

    for candidate in _bridge_file_candidates():
        if candidate.exists():
            return candidate

    return None


def load_bridge_file(path: Path | None = None) -> BridgeFile:
    """Load and validate ``bridge.json``.

    Raises :class:`BridgeUnavailable` when the file is missing or unreadable and
    :class:`VersionMismatch` when the bridge version differs from the client.
    Set ``CECLI_BRIDGE_VERSION_SKIP=1`` to bypass the version check in tests.
    """

    bridge_path = Path(path).expanduser() if path is not None else discover_bridge_file()

    if bridge_path is None:
        raise BridgeUnavailable(
            "bridge.json was not found; install and run ce-underscore or pass --ensure-bridge"
        )

    try:
        data = json.loads(bridge_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BridgeUnavailable(f"bridge.json was not found at {bridge_path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise BridgeUnavailable(f"bridge.json at {bridge_path} is unreadable: {exc}") from exc

    if not isinstance(data, dict):
        raise BridgeUnavailable(f"bridge.json at {bridge_path} is not a JSON object")

    bridge = BridgeFile.from_dict(data, path=bridge_path)

    if bridge.port <= 0 or not bridge.token:
        raise BridgeUnavailable(
            f"bridge.json at {bridge_path} is incomplete; restart ce-underscore"
        )

    if not _is_loopback_host(bridge.host):
        raise BridgeUnavailable(
            f"bridge.json at {bridge_path} names a non-loopback host; refusing to send the token"
        )

    if os.environ.get("CECLI_BRIDGE_VERSION_SKIP") != "1":
        if bridge.version != EXPECTED_BRIDGE_VERSION:
            raise VersionMismatch(bridge.version, EXPECTED_BRIDGE_VERSION)

    return bridge


class AppClient:
    """One connection-scoped client for the app-harness bridge."""

    def __init__(
        self,
        bridge: BridgeFile | None = None,
        *,
        ensure_bridge: bool = False,
        timeout_ms: int | None = None,
    ) -> None:
        """Resolve the bridge, optionally starting it first."""

        self.timeout_ms = _resolve_timeout_ms(timeout_ms)
        self.last_notes: list[str] = []
        self._snapshot_cache: dict[tuple[Any, ...], Snapshot] | None = None
        bridge = bridge or self._resolve_bridge(ensure_bridge)
        self.bridge = bridge

    def state(self) -> StateInfo:
        """Return bridge identity and capabilities."""

        return StateInfo.from_dict(self._request("GET", "/api/app/state"))

    def help(self) -> dict[str, Any]:
        """Return the bridge capability document."""

        data = self._request("GET", "/api/app/help")

        return data if isinstance(data, dict) else {}

    def windows(self) -> list[Window]:
        """Return visible top-level windows."""

        data = self._request("GET", "/api/app/windows")

        if isinstance(data, dict):
            data = data.get("windows") or []

        if not isinstance(data, list):
            return []

        return [Window.from_dict(item) for item in data if isinstance(item, dict)]

    def snapshot(
        self,
        window: str,
        max_depth: int | None = None,
        max_elements: int | None = None,
        exclude_roles: Sequence[str] | None = None,
        actionable: bool = False,
    ) -> Snapshot:
        """Return the accessibility tree for ``window``.

        ``actionable`` asks the bridge to prune anonymous containers and reparent
        their kept children, which shrinks the tree at the cost of new ids.
        """

        key = _snapshot_key(window, max_depth, max_elements, exclude_roles, actionable)

        if self._snapshot_cache is not None and key in self._snapshot_cache:
            return self._snapshot_cache[key]

        payload = {
            "window": window,
            "max_depth": max_depth,
            "max_elements": max_elements,
        }
        if exclude_roles:
            payload["exclude_roles"] = list(exclude_roles)

        if actionable:
            payload["actionable"] = True

        snapshot = Snapshot.from_dict(
            self._request("POST", "/api/app/snapshot", payload),
            client=self,
            window=window,
        )
        snapshot.notes = list(self.last_notes)

        if self._snapshot_cache is not None:
            self._snapshot_cache[key] = snapshot

        return snapshot

    def enable_snapshot_cache(self) -> None:
        """Reuse snapshots within this client.

        Script mode enables this so a sequence of ``find`` calls does not
        re-walk the tree. Every action clears the cache, and :meth:`refresh`
        drops it explicitly when the app changed outside the bridge.
        """

        self._snapshot_cache = {}

    def refresh(self) -> int:
        """Drop cached snapshots and return how many keys were cleared."""

        if self._snapshot_cache is None:
            return 0

        cleared = len(self._snapshot_cache)
        self._snapshot_cache.clear()

        return cleared

    def find(
        self,
        window: str,
        selector: str,
        limit: int = DEFAULT_LOCATOR_LIMIT,
        max_depth: int | None = None,
        max_elements: int | None = None,
        exclude_roles: Sequence[str] | None = None,
    ) -> tuple[list[Element], int]:
        """Return elements matching ``selector`` and the full match count.

        ``limit`` only caps the returned list; the count always reflects every
        match in the snapshot. A negative ``limit`` disables the cap.
        """

        compounds = _parse_selector(selector)
        snapshot = self.snapshot(window, max_depth, max_elements, exclude_roles)
        matches = [element.bind(self, window) for element in select(snapshot.elements, compounds)]

        if limit is not None and limit >= 0:
            return matches[:limit], len(matches)

        return matches, len(matches)

    def find_server(
        self,
        window: str,
        *,
        roles: Sequence[str] = (),
        name: dict[str, Any] | str | None = None,
        value: dict[str, Any] | str | None = None,
        enabled: bool | None = None,
        sensitive: bool | None = None,
        limit: int | None = DEFAULT_LOCATOR_LIMIT,
        max_depth: int | None = None,
        max_elements: int | None = None,
        exclude_roles: Sequence[str] | None = None,
    ) -> tuple[list[Element], int, bool]:
        """Filter the accessibility tree on the bridge and return the matches.

        Returns ``(matches, match_count, truncated)``. ``match_count`` is the
        number of elements that matched before ``limit`` was applied. ``name``
        and ``value`` accept either a plain string (exact match) or a
        ``{op, value}`` mapping with ``op`` one of ``eq``, ``contains``,
        ``prefix`` or ``suffix``.

        Raises :class:`AppHarnessError` with an ``unsupported`` or ``not_found``
        kind when the bridge does not implement ``/api/app/find``; callers fall
        back to :meth:`find` in that case.
        """

        match: dict[str, Any] = {}

        if roles:
            match["roles"] = list(roles)

        for key, operand in (("name", name), ("value", value)):
            compiled = _match_operand(operand)

            if compiled is not None:
                match[key] = compiled

        if enabled is not None:
            match["enabled"] = bool(enabled)

        if sensitive is not None:
            match["sensitive"] = bool(sensitive)

        payload: dict[str, Any] = {"window": window, "match": match}

        if limit is not None and limit >= 0:
            payload["limit"] = limit

        if max_depth is not None:
            payload["max_depth"] = max_depth

        if max_elements is not None:
            payload["max_elements"] = max_elements

        if exclude_roles:
            payload["exclude_roles"] = list(exclude_roles)

        data = self._request("POST", "/api/app/find", payload)

        if not isinstance(data, dict):
            raise AppHarnessError("backend_error", "the bridge returned a non-object find result")

        raw_matches = data.get("matches")
        matches = (
            [
                Element.from_dict(item).bind(self, window)
                for item in raw_matches
                if isinstance(item, dict)
            ]
            if isinstance(raw_matches, list)
            else []
        )
        count = _as_int(data.get("match_count"), default=len(matches))

        return matches, count, bool(data.get("truncated"))

    def find_elements(
        self,
        window: str,
        selector: str,
        limit: int = DEFAULT_LOCATOR_LIMIT,
        max_depth: int | None = None,
        max_elements: int | None = None,
        exclude_roles: Sequence[str] | None = None,
    ) -> tuple[list[Element], int, bool]:
        """Return selector matches, preferring the server-side find route.

        Falls back to :meth:`find` (snapshot then filter) when the bridge has no
        ``/api/app/find`` route or the selector cannot be compiled to a match
        spec. Chained selectors re-evaluate their ancestors client-side over the
        returned elements' ``parent`` links, so the last compound is what the
        server filters on.
        """

        plan = compile_match(_parse_selector(selector))

        if plan is not None:
            try:
                matches, count, truncated = self._find_plan(
                    window, plan, limit, max_depth, max_elements, exclude_roles
                )
            except AppHarnessError as exc:

                if exc.kind not in _ROUTE_FALLBACK_KINDS:
                    raise
            else:

                if plan.simple:
                    return _cap_matches(matches, limit), count, truncated

                if not truncated:
                    selected = [
                        element.bind(self, window) for element in select(matches, plan.compounds)
                    ]
                    return _cap_matches(selected, limit), len(selected), False

        matches, count = self.find(window, selector, limit, max_depth, max_elements, exclude_roles)

        return matches, count, len(matches) < count

    def _find_plan(
        self,
        window: str,
        plan: MatchPlan,
        limit: int,
        max_depth: int | None,
        max_elements: int | None,
        exclude_roles: Sequence[str] | None,
    ) -> tuple[list[Element], int, bool]:
        spec = plan.spec
        server_limit = limit if plan.simple else _widen_limit(limit)
        attributes = plan.simple

        return self.find_server(
            window,
            roles=spec.get("roles") or (),
            name=spec.get("name") if attributes else None,
            value=spec.get("value") if attributes else None,
            enabled=spec.get("enabled") if attributes else None,
            sensitive=spec.get("sensitive") if attributes else None,
            limit=server_limit,
            max_depth=max_depth,
            max_elements=max_elements,
            exclude_roles=exclude_roles,
        )

    def locator(
        self,
        window: str,
        selector: str,
        *,
        timeout_ms: int | None = None,
        limit: int = DEFAULT_LOCATOR_LIMIT,
        max_depth: int | None = None,
        max_elements: int | None = None,
        exclude_roles: Sequence[str] | None = None,
    ) -> Locator:
        """Bind ``selector`` to ``window`` for re-resolved actions."""

        return Locator(
            self,
            window,
            selector,
            timeout_ms=timeout_ms,
            limit=limit,
            max_depth=max_depth,
            max_elements=max_elements,
            exclude_roles=exclude_roles,
        )

    def action(
        self,
        window: str,
        action: str,
        target: dict[str, Any] | None = None,
        value: str | None = None,
        keys: str | None = None,
        point: dict[str, int] | None = None,
        direction: str | None = None,
        amount: int | None = None,
        row: int | None = None,
        column: int | None = None,
        button: str | None = None,
        count: int | None = None,
        text: str | None = None,
        to_point: dict[str, int] | None = None,
        duration_ms: int | None = None,
        horizontal_percent: float | None = None,
        vertical_percent: float | None = None,
        delivery_mode: str | None = None,
    ) -> ActionResult:
        """Send one action request and parse its result.

        ``delivery_mode`` is ``"background"`` (default, restore the previous
        foreground window) or ``"foreground"`` (leave the target in front).
        """

        args: dict[str, Any] = {
            "value": value,
            "keys": keys,
            "point": point,
            "direction": direction,
            "amount": amount,
            "extra": {},
        }

        for key, extra in (
            ("row", row),
            ("column", column),
            ("button", button),
            ("count", count),
            ("text", text),
            ("to_point", to_point),
            ("duration_ms", duration_ms),
            ("horizontal_percent", horizontal_percent),
            ("vertical_percent", vertical_percent),
        ):
            if extra is not None:
                args[key] = extra

        if delivery_mode is not None:
            args["delivery_mode"] = delivery_mode
        payload = {
            "window": window,
            "action": action,
            "target": target,
            "args": args,
        }

        try:
            result = ActionResult.from_dict(self._request("POST", "/api/app/action", payload))
        except AppHarnessError as exc:
            if exc.kind == "input_blocked":
                raise self._enrich_blocked(exc) from exc

            raise

        if self._snapshot_cache is not None:
            self._snapshot_cache.clear()

        return result

    def batch(self, operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Run several operations in order over one request.

        Each result is the envelope that the dedicated endpoint would return, so
        callers inspect ``ok`` per operation. A failed operation does not stop
        the ones after it.
        """

        data = self._request("POST", "/api/app/batch", {"operations": operations})
        results = data.get("results") if isinstance(data, dict) else None

        if self._snapshot_cache is not None:
            self._snapshot_cache.clear()

        return results if isinstance(results, list) else []

    def invoke(
        self,
        window: str,
        target: dict[str, Any] | None = None,
        point: dict[str, int] | None = None,
        delivery_mode: str | None = None,
    ) -> ActionResult:
        """Invoke the default action of a control.

        ``point`` is only used as a pointer fallback when the element exposes no
        invoke pattern.
        """

        return self.action(
            window,
            "invoke",
            target=target,
            point=point,
            delivery_mode=delivery_mode,
        )

    def set_value(
        self,
        window: str,
        value: str,
        target: dict[str, Any] | None = None,
        delivery_mode: str | None = None,
    ) -> ActionResult:
        """Write ``value`` to a control and read it back."""

        return self.action(
            window, "set_value", target=target, value=value, delivery_mode=delivery_mode
        )

    def cell_at(
        self,
        window: str,
        row: int,
        column: int,
        grid: dict[str, Any] | None = None,
        delivery_mode: str | None = None,
    ) -> ActionResult:
        """Resolve a spreadsheet cell by its one-based row and column.

        ``grid`` optionally names the grid element (a selector dict from
        :meth:`locator`) so a window with several sheets addresses the intended
        one. Without it the backend picks its first grid.
        """

        return self.action(
            window,
            "cell_at",
            target=grid,
            row=row,
            column=column,
            delivery_mode=delivery_mode,
        )

    def get_value(
        self,
        window: str,
        target: dict[str, Any] | None = None,
        delivery_mode: str | None = None,
    ) -> ActionResult:
        """Read a control value, raising when the bridge refuses."""

        return self.action(window, "get_value", target=target, delivery_mode=delivery_mode)

    def click(
        self,
        window: str,
        target: dict[str, Any] | None = None,
        point: dict[str, int] | None = None,
        button: str = "left",
        count: int = 1,
        delivery_mode: str | None = None,
    ) -> ActionResult:
        """Click a target element or an explicit screen point."""

        extra: dict[str, Any] = {}

        if button != "left":
            extra["button"] = button

        if count != 1:
            extra["count"] = count

        return self.action(
            window,
            "click",
            target=target,
            point=point,
            delivery_mode=delivery_mode,
            **extra,
        )

    def keys(
        self,
        window: str,
        keys: str,
        target: dict[str, Any] | None = None,
        delivery_mode: str | None = None,
    ) -> ActionResult:
        """Send a keystroke specification to the window or target."""

        return self.action(window, "keys", target=target, keys=keys, delivery_mode=delivery_mode)

    def click_point(
        self,
        window: str,
        point: Any,
        button: str = "left",
        count: int = 1,
        delivery_mode: str | None = None,
    ) -> ActionResult:
        """Click an explicit screen point."""

        return self.action(
            window,
            "click",
            point=_point_value(point),
            button=button,
            count=count,
            delivery_mode=delivery_mode,
        )

    def double_click(
        self,
        window: str,
        target: dict[str, Any] | None = None,
        point: Any = None,
        delivery_mode: str | None = None,
    ) -> ActionResult:
        """Double-click a target or an explicit screen point."""

        return self.action(
            window,
            "double_click",
            target=target,
            point=self._resolve_point(window, target, point),
            delivery_mode=delivery_mode,
        )

    def right_click(
        self,
        window: str,
        target: dict[str, Any] | None = None,
        point: Any = None,
        delivery_mode: str | None = None,
    ) -> ActionResult:
        """Right-click a target or an explicit screen point."""

        return self.action(
            window,
            "right_click",
            target=target,
            point=self._resolve_point(window, target, point),
            delivery_mode=delivery_mode,
        )

    def hover(
        self,
        window: str,
        target: dict[str, Any] | None = None,
        point: Any = None,
        delivery_mode: str | None = None,
    ) -> ActionResult:
        """Move the pointer over a target or an explicit screen point."""

        return self.action(
            window,
            "hover",
            target=target,
            point=self._resolve_point(window, target, point),
            delivery_mode=delivery_mode,
        )

    def drag(
        self,
        window: str,
        start: Any,
        end: Any,
        duration_ms: int | None = None,
        delivery_mode: str | None = None,
    ) -> ActionResult:
        """Drag from ``start`` to ``end``."""

        return self.action(
            window,
            "drag",
            point=_point_value(start),
            to_point=_point_value(end),
            duration_ms=duration_ms,
            delivery_mode=delivery_mode,
        )

    def select(
        self,
        window: str,
        target: dict[str, Any] | None = None,
        delivery_mode: str | None = None,
    ) -> ActionResult:
        """Select a control."""

        return self.action(window, "select", target=target, delivery_mode=delivery_mode)

    def scroll_into_view(
        self,
        window: str,
        target: dict[str, Any] | None = None,
        delivery_mode: str | None = None,
    ) -> ActionResult:
        """Scroll a control into view."""

        return self.action(window, "scroll_into_view", target=target, delivery_mode=delivery_mode)

    def type_text(
        self,
        window: str,
        text: str,
        target: dict[str, Any] | None = None,
        replace: bool = True,
        commit: bool = False,
    ) -> ActionResult:
        """Type literal ``text`` into ``target`` or the focused window.

        A direct value write is preferred, then keyboard entry with literal keys,
        and finally a clipboard paste when the text cannot be encoded safely.
        """

        resolved = _target_dict(target)

        if resolved is not None:
            result = self._set_text(window, resolved, text)

            if result is not None:
                return result

        encoded = encode_literal_keys(text)

        if encoded is None:
            return self._paste_text(window, text, resolved, replace=replace, commit=commit)

        try:
            result = self._type_with_keys(window, resolved, encoded, replace=replace, commit=commit)
        except AppHarnessError as exc:
            if exc.kind not in _TEXT_FALLBACK_KINDS:
                raise

            return self._paste_text(window, text, resolved, replace=replace, commit=commit)

        return self._verify_text(
            window,
            resolved,
            text,
            result,
            retry_with_paste=True,
            replace=replace,
            commit=commit,
        )

    def edit_text(
        self, window: str, text: str, target: dict[str, Any] | None = None
    ) -> ActionResult:
        """Replace the text of ``target`` with ``text``."""

        return self.type_text(window, text, target=target, replace=True, commit=False)

    def dialogs(self) -> list[Window]:
        """Return blocking dialog windows.

        The dedicated endpoint is preferred; older bridges fall back to filtering
        the window list for dialog flags and dialog-like class names.
        """

        try:
            data = self._request("GET", "/api/app/dialogs")
        except AppHarnessError as exc:
            if exc.kind not in _ROUTE_FALLBACK_KINDS:
                raise

            return self._fallback_dialogs()

        raw = data.get("dialogs") if isinstance(data, dict) else None

        if not isinstance(raw, list):
            return self._fallback_dialogs()

        return [Window.from_dict(item) for item in raw if isinstance(item, dict)]

    def accept_dialog(self, selector: str | None = None, button: str | None = None) -> ActionResult:
        """Click the accept button of a blocking dialog."""

        dialog = self._pick_dialog(selector)
        names = (button,) if button else _DIALOG_ACCEPT_BUTTONS

        return self._press_dialog_button(dialog, names)

    def cancel_dialog(self, selector: str | None = None) -> ActionResult:
        """Click the cancel button of a blocking dialog."""

        dialog = self._pick_dialog(selector)

        return self._press_dialog_button(dialog, _DIALOG_CANCEL_BUTTONS)

    def dismiss_dialogs(self) -> list[ActionResult]:
        """Cancel every blocking dialog, newest windows first."""

        results: list[ActionResult] = []
        seen: set[str] = set()

        for _ in range(_DIALOG_DISMISS_LIMIT):
            pending = [dialog for dialog in self.dialogs() if _dialog_key(dialog) not in seen]

            if not pending:
                break

            for dialog in pending:
                seen.add(_dialog_key(dialog))
                results.append(self._press_dialog_button(dialog, _DIALOG_CANCEL_BUTTONS))

        return results

    def activate(self, window: str) -> ActionResult:
        """Raise and focus ``window`` so later input reaches it."""

        return self.action(window, "activate")

    def focus(
        self,
        window: str,
        target: dict[str, Any] | None = None,
        delivery_mode: str | None = None,
    ) -> ActionResult:
        """Move focus to a control."""

        return self.action(window, "focus", target=target, delivery_mode=delivery_mode)

    def scroll(
        self,
        window: str,
        direction: str = "down",
        amount: int | None = None,
        target: dict[str, Any] | None = None,
        point: dict[str, int] | None = None,
        delivery_mode: str | None = None,
    ) -> ActionResult:
        """Scroll a target, an explicit point, or the window in ``direction``."""

        return self.action(
            window,
            "scroll",
            target=target,
            point=point,
            direction=direction,
            amount=amount,
            delivery_mode=delivery_mode,
        )

    def scroll_to(
        self,
        window: str,
        horizontal_percent: float | None = None,
        vertical_percent: float | None = None,
        target: dict[str, Any] | None = None,
        delivery_mode: str | None = None,
        point: dict[str, int] | None = None,
    ) -> ActionResult:
        """Scroll a target to an absolute percentage along either axis."""

        return self.action(
            window,
            "scroll_to",
            target=target,
            horizontal_percent=horizontal_percent,
            vertical_percent=vertical_percent,
            delivery_mode=delivery_mode,
            point=point,
        )

    def screenshot(self, window: str) -> bytes:
        """Return raw PNG bytes for ``window``."""

        data = self._request_raw("POST", "/api/app/screenshot", {"window": window})

        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return data

        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AppHarnessError(
                "backend_error", "the bridge returned neither a PNG nor a JSON envelope"
            ) from exc

        if isinstance(payload, dict):
            _unwrap_envelope(payload)
            raise AppHarnessError("backend_error", "the bridge returned JSON instead of a PNG")

        raise AppHarnessError("backend_error", "the bridge returned an unexpected body")

    def doctor(self) -> DoctorReport:
        """Return permission and backend diagnostics."""

        return DoctorReport.from_dict(self._request("GET", "/api/app/doctor"))

    def shutdown(self) -> dict[str, Any]:
        """Ask the bridge to stop."""

        data = self._request("POST", "/api/app/shutdown", {})
        return data if isinstance(data, dict) else {"ok": True}

    def _resolve_bridge(self, ensure_bridge: bool) -> BridgeFile:
        try:
            bridge = load_bridge_file()
        except BridgeUnavailable as exc:
            if not ensure_bridge:
                raise

            self._start_bridge(exc)
            return self._wait_for_bridge()

        if not ensure_bridge:
            return bridge

        self.bridge = bridge

        try:
            self.state()
        except BridgeUnavailable as exc:
            self._start_bridge(exc)
            return self._wait_for_bridge()

        return bridge

    def _start_bridge(self, original: Exception) -> None:
        binary = _find_binary()

        if binary is None:
            raise BridgeUnavailable(
                f"{original}; ce-underscore was not found, install it or set CECLI_CE_UNDERSCORE"
            ) from original

        try:
            subprocess.run(
                [str(binary), "--ensure-bridge"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=max(10.0, self.timeout_ms / 1000.0),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise BridgeUnavailable(f"failed to start ce-underscore at {binary}: {exc}") from exc

    def _wait_for_bridge(self) -> BridgeFile:
        deadline = time.monotonic() + max(10.0, self.timeout_ms / 1000.0)
        last_error: Exception | None = None

        while time.monotonic() < deadline:
            try:
                bridge = load_bridge_file()
                self.bridge = bridge
                self.state()
                return bridge
            except (BridgeUnavailable, AppHarnessError) as exc:
                last_error = exc
                time.sleep(0.1)

        raise BridgeUnavailable(f"ce-underscore did not become ready: {last_error}")

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = self._request_bytes(method, path, payload)

        if not body:
            return {}

        try:
            envelope = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AppHarnessError("backend_error", f"invalid JSON from bridge: {exc}") from exc

        self.last_notes = _envelope_notes(envelope)

        return _unwrap_envelope(envelope)

    def _request_raw(self, method: str, path: str, payload: dict[str, Any] | None = None) -> bytes:
        return self._request_bytes(method, path, payload)

    def _request_bytes(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> bytes:
        _check_connection(self.bridge.host, self.bridge.port)

        data = None

        if payload is not None:
            data = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(
            f"{self.bridge.base_url}{path}",
            data=data,
            method=method,
            headers={
                "X-Cecli-Token": self.bridge.token,
                "Content-Type": "application/json",
                "Accept": "application/json, image/png",
            },
        )

        try:
            with _url_opener().open(request, timeout=self.timeout_ms / 1000.0) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise _http_error(exc) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise AppHarnessError("uncertain", "the bridge did not answer in time") from exc

            raise BridgeUnavailable(f"cannot reach the bridge: {exc.reason}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise AppHarnessError("uncertain", "the bridge did not answer in time") from exc
        except OSError as exc:
            raise BridgeUnavailable(f"cannot reach the bridge: {exc}") from exc

    def _resolve_point(
        self, window: str, target: dict[str, Any] | None, point: Any
    ) -> dict[str, int]:
        """Return the screen point for a pointer action."""

        if point is not None:
            return _point_value(point)

        if target is None:
            raise AppHarnessError("invalid_request", "a pointer action needs a point or a target")

        element = self._element_for_target(window, target)
        center = element.center

        if center is None:
            raise AppHarnessError(
                "invalid_request",
                f"element {element.id} has no bounds for a pointer action",
            )

        return center.to_dict()

    def _element_for_target(self, window: str, target: dict[str, Any]) -> Element:
        """Return the snapshot element that matches ``target``."""

        snapshot = self.snapshot(window)

        for element in snapshot.elements:
            if _target_matches(element, target):
                return element

        raise AppHarnessError(
            "not_found", f"no element matches target {target!r} in window {window!r}"
        )

    def _set_text(self, window: str, target: dict[str, Any], text: str) -> ActionResult | None:
        """Try a direct value write and return ``None`` when unsupported."""

        try:
            result = self.set_value(window, text, target)
        except AppHarnessError as exc:
            if exc.kind in _TEXT_FALLBACK_KINDS:
                return None

            raise

        if not result.delivered:
            return None

        return self._verify_text(window, target, text, result)

    def _type_with_keys(
        self,
        window: str,
        target: dict[str, Any] | None,
        keys: str,
        *,
        replace: bool,
        commit: bool,
    ) -> ActionResult:
        """Focus the target and send literal ``keys`` plus the replace chord."""

        if target is not None:
            self.focus(window, target)
        else:
            self.activate(window)

        if replace:
            self.keys(window, "^a", target)

        result = self.keys(window, keys, target)

        if commit:
            result = self.keys(window, "{ENTER}", target)

        return result

    def _paste_text(
        self,
        window: str,
        text: str,
        target: dict[str, Any] | None,
        *,
        replace: bool,
        commit: bool,
    ) -> ActionResult:
        """Paste ``text`` from the clipboard into the target."""

        try:
            clipboard.set_text(text)
        except clipboard.ClipboardError as exc:
            raise AppHarnessError("clipboard_unavailable", str(exc)) from exc

        result = self._type_with_keys(
            window, target, _paste_chord(), replace=replace, commit=commit
        )

        return self._verify_text(window, target, text, result)

    def _verify_text(
        self,
        window: str,
        target: dict[str, Any] | None,
        text: str,
        result: ActionResult,
        *,
        retry_with_paste: bool = False,
        replace: bool = True,
        commit: bool = False,
    ) -> ActionResult:
        """Compare the control value with ``text`` when the bridge exposes it.

        With ``retry_with_paste`` a confirmed mismatch is re-sent through the
        clipboard: some toolkits (WinUI/XAML) drop a fast burst of synthetic
        keystrokes while still accepting a single paste.
        """

        if target is None or not result.delivered:
            return result

        try:
            observed = self.get_value(window, target)
        except AppHarnessError as exc:
            if exc.kind in _TEXT_FALLBACK_KINDS:
                return result

            raise

        if observed.value is not None:
            result.value = observed.value
            result.verified = observed.value == text

        if not result.verified and retry_with_paste:
            try:
                return self._paste_text(window, text, target, replace=replace, commit=commit)
            except AppHarnessError as exc:
                if exc.kind == "clipboard_unavailable":
                    return result

                raise

        return result

    def _fallback_dialogs(self) -> list[Window]:
        """Filter the window list for dialog windows."""

        return [window for window in self.windows() if _is_dialog_window(window)]

    def _pick_dialog(self, selector: str | None) -> Window:
        """Return the dialog named by ``selector`` or the foreground one."""

        dialogs = self.dialogs()

        if selector is not None:
            for dialog in dialogs:
                if _dialog_matches(dialog, selector):
                    return dialog

            raise AppHarnessError("not_found", f"no dialog matches {selector!r}")

        if not dialogs:
            raise AppHarnessError("not_found", "no blocking dialog is open")

        for dialog in dialogs:
            if dialog.foreground:
                return dialog

        return dialogs[0]

    def _press_dialog_button(self, dialog: Window, names: Sequence[str]) -> ActionResult:
        """Click the first matching button, or send Escape."""

        window = _dialog_key(dialog)

        for name in names:
            if not name:
                continue

            selector = f'Button[name="{_quote_selector(name)}"]'

            try:
                return self.locator(window, selector, timeout_ms=_DIALOG_BUTTON_TIMEOUT_MS).click()
            except AppHarnessError as exc:
                if exc.kind not in _DIALOG_BUTTON_MISSES:
                    raise

        return self.keys(window, "{ESC}")

    def _enrich_blocked(self, error: AppHarnessError) -> AppHarnessError:
        """Mention the dialogs that may be blocking input."""

        try:
            titles = [dialog.title for dialog in self.dialogs() if dialog.title]
        except AppHarnessError:
            return error

        if not titles:
            return error

        details = dict(error.details or {})
        details["dialogs"] = titles

        return AppHarnessError(
            error.kind,
            f"{error.message} (blocking dialog: {', '.join(titles)})",
            details,
        )


def _bridge_file_candidates() -> list[Path]:
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        return [Path(local_app_data) / "cecli" / "bridge.json"] if local_app_data else []

    if sys.platform == "darwin":
        return [Path.home() / "Library" / "Application Support" / "cecli" / "bridge.json"]

    candidates: list[Path] = []
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")

    if runtime_dir:
        candidates.append(Path(runtime_dir) / "cecli" / "bridge.json")

    candidates.append(Path.home() / ".cache" / "cecli" / "bridge.json")
    return candidates


def _resolve_timeout_ms(timeout_ms: int | None) -> int:
    if timeout_ms is not None:
        return max(1, timeout_ms)

    override = os.environ.get("CECLI_APP_TIMEOUT_MS")

    if override:
        try:
            return max(1, int(override))
        except ValueError:
            pass

    return DEFAULT_READ_TIMEOUT_MS


def _find_binary() -> Path | None:
    override = os.environ.get("CECLI_CE_UNDERSCORE")

    if override:
        return Path(override).expanduser()

    candidates: list[Path] = []

    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")

        if local_app_data:
            base = Path(local_app_data)
            # Tauri's currentUser installer puts the app in
            # ``%LOCALAPPDATA%\<productName>``; older per-user layouts used
            # ``Programs\<productName>``.  The bundle's product name is not
            # guaranteed to match the binary, which is ``mainBinaryName``.
            for folder in ("cecli", "ce-underscore"):
                candidates.append(base / folder / "ce-underscore.exe")
                candidates.append(base / "Programs" / folder / "ce-underscore.exe")

        candidates.append(Path("C:/Program Files/cecli/ce-underscore.exe"))
        candidates.append(Path("C:/Program Files/ce-underscore/ce-underscore.exe"))
    elif sys.platform == "darwin":
        for app in ("cecli", "ce-underscore"):
            candidates.append(Path(f"/Applications/{app}.app/Contents/MacOS/ce-underscore"))

    for candidate in candidates:
        if candidate.exists():
            return candidate

    found = shutil.which("ce-underscore")
    return Path(found) if found else None


def _check_connection(host: str, port: int) -> None:
    try:
        with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT_SECONDS):
            pass
    except OSError as exc:
        raise BridgeUnavailable(
            f"cannot connect to the bridge at {host}:{port}: {exc}; restart ce-underscore"
        ) from exc


def _unwrap_envelope(envelope: Any) -> Any:
    if not isinstance(envelope, dict):
        raise AppHarnessError("backend_error", "bridge returned a non-object response")

    if envelope.get("ok"):
        return envelope.get("data") or {}

    error = envelope.get("error") or {}

    if not isinstance(error, dict):
        raise AppHarnessError("backend_error", str(error))

    kind = _as_str(error.get("type"), default="backend_error")
    message = _as_str(error.get("message"), default="the bridge rejected the request")
    raise AppHarnessError(kind, message, details=error.get("details"))


def _envelope_notes(envelope: Any) -> list[str]:
    """Return the non-fatal notes a successful envelope carries."""

    if not isinstance(envelope, dict):
        return []

    notes = envelope.get("notes")

    if not isinstance(notes, list):
        return []

    return [str(note) for note in notes if str(note).strip()]


def _http_error(exc: urllib.error.HTTPError) -> AppHarnessError:
    if exc.code in (401, 403):
        return AppHarnessError("unauthorized", "the bridge rejected the token")

    body = b""

    try:
        body = exc.read()
    except OSError:
        pass

    try:
        envelope = json.loads(body.decode("utf-8")) if body else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        envelope = None

    if isinstance(envelope, dict) and envelope.get("error"):
        try:
            _unwrap_envelope(envelope)
        except AppHarnessError as error:
            return error

    return AppHarnessError("backend_error", f"bridge HTTP error {exc.code}: {exc.reason}")


def _as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default

    return str(value)


def _as_int(value: Any, default: int = 0) -> int:
    if value is None or isinstance(value, bool):
        return default

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _match_operand(operand: dict[str, Any] | str | None) -> dict[str, Any] | None:
    if operand is None:
        return None

    if isinstance(operand, str):
        return {"op": "eq", "value": operand}

    if "value" not in operand:
        raise AppHarnessError("invalid_request", "a match operand needs a value")

    return {"op": str(operand.get("op") or "eq"), "value": str(operand["value"])}


def _cap_matches(matches: list[Element], limit: int | None) -> list[Element]:
    if limit is None or limit < 0:
        return matches

    return matches[:limit]


def _widen_limit(limit: int | None) -> int | None:
    if limit is None or limit < 0:
        return limit

    return max(limit * 4, 200)


def _parse_selector(selector: str) -> list[CompoundSelector]:
    try:
        return parse(selector)
    except ValueError as exc:
        raise AppHarnessError("invalid_request", str(exc)) from exc


def _snapshot_key(
    window: str,
    max_depth: int | None,
    max_elements: int | None,
    exclude_roles: Sequence[str] | None,
    actionable: bool,
) -> tuple[Any, ...]:
    return (window, max_depth, max_elements, tuple(exclude_roles or ()), bool(actionable))


def _target_for(element: Element) -> dict[str, Any]:
    target: dict[str, Any] = {"id": element.id}

    if element.runtime_id:
        target["runtime_id"] = element.runtime_id

    if element.path:
        target["path"] = element.path

    return target


def _describe(element: Element) -> str:
    label = element.control_type or "?"

    if element.name:
        label = f"{label} {element.name!r}"

    return f"{label} (id={element.id})"


def encode_literal_keys(text: str) -> str | None:
    """Encode literal text for the bridge's SendKeys-style key syntax.

    Characters that SendKeys treats as modifiers are wrapped in braces, and
    newlines become ``{ENTER}``. ``None`` means the text contains a control
    character that cannot be typed safely, so callers should paste it instead.
    """

    parts: list[str] = []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    for char in normalized:
        if char == "\n":
            parts.append("{ENTER}")
        elif char == "\t":
            parts.append("{TAB}")
        elif char in "^!+~%{}()[]":
            parts.append("{" + char + "}")
        elif ord(char) < 32 or ord(char) == 127:
            return None
        else:
            parts.append(char)

    return "".join(parts)


def _point_value(point: Any) -> dict[str, int]:
    """Normalize a point-like value into a bridge point mapping."""

    if isinstance(point, Point):
        return point.to_dict()

    if isinstance(point, dict) and "x" in point and "y" in point:
        return {"x": int(point["x"]), "y": int(point["y"])}

    if isinstance(point, (tuple, list)) and len(point) == 2:
        return {"x": int(point[0]), "y": int(point[1])}

    raise AppHarnessError(
        "invalid_request", f"unsupported point {point!r}; use Point, (x, y) or {{x, y}}"
    )


def _target_dict(target: Any) -> dict[str, Any] | None:
    """Normalize an element or target mapping into a bridge target."""

    if target is None:
        return None

    if isinstance(target, Element):
        return target.target()

    if isinstance(target, dict):
        return target

    raise AppHarnessError("invalid_request", f"unsupported target {target!r}")


def _target_matches(element: Element, target: dict[str, Any]) -> bool:
    """Return whether ``element`` satisfies every key in ``target``."""

    for key, value in target.items():
        if value is None:
            continue

        if key == "id":
            matches = element.id == int(value)
        elif key == "runtime_id":
            matches = element.runtime_id == str(value)
        elif key == "automation_id":
            matches = element.automation_id == str(value)
        elif key == "path":
            matches = element.path == str(value)
        elif key == "name":
            matches = element.name == str(value)
        elif key in ("role", "control_type"):
            matches = element.control_type.casefold() == str(value).casefold()
        else:
            matches = False

        if not matches:
            return False

    return bool(target)


def _is_dialog_window(window: Window) -> bool:
    """Return whether ``window`` looks like a modal dialog."""

    if window.dialog:
        return True

    class_name = (window.class_name or "").strip()

    if any(class_name.casefold() == name.casefold() for name in _DIALOG_CLASS_NAMES):
        return True

    return "dialog" in class_name.casefold()


def _dialog_key(window: Window) -> str:
    """Return the window key used to drive a dialog."""

    key = window.handle or window.title

    if not key:
        raise AppHarnessError("invalid_request", "the dialog has neither a handle nor a title")

    return key


def _dialog_matches(window: Window, selector: str) -> bool:
    """Return whether ``selector`` names ``window`` by any visible field."""

    needle = selector.casefold()
    fields = (window.handle, window.title, window.process_name, window.class_name)

    return any(needle in str(field).casefold() for field in fields if field)


def _quote_selector(value: str) -> str:
    """Escape a quoted selector attribute value."""

    return value.replace("\\", "\\\\").replace('"', '\\"')


def _paste_chord() -> str:
    """Return the keystroke chord that pastes the clipboard."""

    return "^v"


def _is_loopback_host(host: str | None) -> bool:
    """Return whether ``host`` names this machine's loopback interface."""

    text = (host or "").strip().lower()

    if text == "localhost":
        return True

    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so the bridge token cannot be forwarded elsewhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _url_opener() -> urllib.request.OpenerDirector:
    """Build an opener that ignores proxies and refuses redirects."""

    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
