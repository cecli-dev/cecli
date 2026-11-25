"""Spreadsheet helpers for Excel and LibreOffice Calc.

The bridge exposes a ``cell_at`` action that resolves one grid cell by row and
column; this module adds A1 parsing, Name Box navigation, range selection and
clipboard-based bulk writes on top. Application-specific selectors and key
chords live in :mod:`cecli.helpers.app_harness.recipes` so the two supported apps stay
in one place.

Rows and columns are one-based everywhere, matching both A1 notation and the
bridge protocol.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from . import clipboard, recipes
from .client import AppHarnessError
from .models import ActionResult, Element, Window

_CELL_PATTERN = re.compile(r"^\$?([A-Za-z]{1,3})\$?([1-9][0-9]*)$")
_COLUMN_PATTERN = re.compile(r"^\$?([A-Za-z]{1,3})$")
_ROW_PATTERN = re.compile(r"^\$?([1-9][0-9]*)$")

RangePoint = tuple[int | None, int | None]


def parse_cell(ref: str) -> tuple[int, int]:
    """Parse ``A1`` notation into a one-based ``(row, column)`` pair.

    A leading ``$`` and a sheet prefix (``Sheet1!`` or ``'My Sheet'!``) are
    accepted and ignored for the coordinate. Whole-column or whole-row
    references are rejected because they do not name a single cell.
    """

    _, body = _split_sheet(ref)
    match = _CELL_PATTERN.match(body)

    if not match:
        raise ValueError(f"invalid A1 cell reference: {ref!r}")

    return int(match.group(2)), _column_index(match.group(1))


def parse_range(ref: str) -> tuple[RangePoint, RangePoint]:
    """Parse a cell or range into start and end ``(row, column)`` points.

    A single cell returns the same point twice. Whole columns and rows are
    supported and represented with ``None`` on the unbounded axis, e.g.
    ``A:C`` becomes ``((None, 1), (None, 3))``. Coordinates are returned in
    the order written; callers that read a block should normalize them.
    """

    _, body = _split_sheet(ref)

    return _parse_range_body(body)


def format_cell(row: int, column: int) -> str:
    """Render a one-based row and column as an A1 reference."""

    if not isinstance(row, int) or row < 1:
        raise ValueError(f"row must be a positive integer, got {row!r}")

    if not isinstance(column, int) or column < 1:
        raise ValueError(f"column must be a positive integer, got {column!r}")

    return f"{_column_letters(column)}{row}"


def format_range(start: RangePoint, end: RangePoint) -> str:
    """Render two points as an A1 range, collapsing a single cell."""

    if start == end:
        return _format_point(start)

    return f"{_format_point(start)}:{_format_point(end)}"


class Spreadsheet:
    """Drive one spreadsheet window through the app-harness client.

    ``window`` is a window title, handle, or :class:`Window`. ``grid`` is an
    optional locator selector, target mapping, or bound element that scopes
    ``cell_at`` when a window contains more than one grid. ``app`` accepts an
    Excel or LibreOffice key or alias; when omitted the app is detected from
    the target window's process name and title on first use.
    """

    def __init__(
        self,
        client: Any,
        window: str | Window,
        grid: Any = None,
        app: str | None = None,
    ) -> None:
        """Record the client, target window, optional grid and explicit app."""

        self.client = client
        self._window_spec = window
        self.window = _window_key(window)
        self.grid = grid
        self._app = _explicit_app(app)
        self._grid_target: dict[str, Any] | None = None
        self._grid_resolved = False
        self._windows: list[Window] | None = None

    @property
    def app(self) -> str | None:
        """Return the explicit app key or the one detected from the window."""

        if self._app is None:
            self._app = self._detect_app()

        return self._app

    @property
    def recipe(self) -> recipes.AppRecipe:
        """Return the recipe for the resolved app, or raise a clear error."""

        app = self.app

        if app is None:
            raise AppHarnessError(
                "unsupported_app",
                "could not detect the spreadsheet app; pass app='excel' or "
                "app='libreoffice' explicitly",
            )

        return recipes.get_recipe(app)

    def cell(self, row: int, column: int) -> ActionResult:
        """Resolve one cell through the bridge and return its action result."""

        _check_position(row, column)

        return self.client.cell_at(self.window, row, column, self._grid())

    def value(self, row: int, column: int) -> str:
        """Return the displayed value of one cell.

        A bridge that reports the cell address for an empty cell is normalized
        to ``""``, so a cell holding exactly its own address reads as empty.
        """

        try:
            result = self.cell(row, column)
        except AppHarnessError as exc:
            if exc.kind in ("target_not_found", "not_found"):
                return ""

            raise

        text = _result_text(result)

        if text.strip().casefold() == format_cell(row, column).casefold():
            return ""

        return text

    def set_cell(self, row: int, column: int, value: Any) -> ActionResult:
        """Write one cell, preferring a direct value write over keystrokes.

        ``edit_text`` and ``type_text`` are used when the client provides them.
        Older clients fall back to selecting the cell through the Name Box and
        pasting the value from the clipboard.
        """

        _check_position(row, column)
        text = "" if value is None else str(value)

        return self._write_text(row, column, text)

    def goto(self, ref: str | tuple[int, int]) -> ActionResult:
        """Move the selection to a cell or range using the Name Box."""

        text = self._reference_or_error(ref)

        return self._select_reference(text)

    def select_range(self, ref: str) -> ActionResult:
        """Select an A1 range through the Name Box."""

        start, end = self._range_or_error(ref)

        if start == end:
            return self.goto(ref)

        return self._select_reference(self._reference_or_error(ref))

    def read_range(self, ref: str) -> list[list[str]]:
        """Read every cell in ``ref`` as a row-major matrix of strings."""

        start, end = self._range_or_error(ref)
        first_row, last_row, first_column, last_column = _concrete_bounds(start, end)
        rows: list[list[str]] = []

        for row in range(first_row, last_row + 1):
            rows.append(
                [self.value(row, column) for column in range(first_column, last_column + 1)]
            )

        return rows

    def write_range(self, ref: str, rows: Any) -> ActionResult:
        """Write a two-dimensional block starting at ``ref`` via one TSV paste."""

        anchor = self._anchor_or_error(ref)

        return self.paste_tsv(anchor, rows)

    def paste_tsv(self, anchor: str, rows_or_text: Any) -> ActionResult:
        """Paste tab-separated rows at ``anchor`` using the clipboard.

        ``rows_or_text`` is either ready-made TSV text or a row-major sequence
        of sequences. A flat sequence is treated as a single row.
        """

        text = _tsv_text(rows_or_text)

        if not text:
            raise AppHarnessError("invalid_request", "cannot paste empty TSV data")

        anchor_text = self._anchor_or_error(anchor)

        try:
            clipboard.set_text(text)
        except clipboard.ClipboardError as exc:
            raise AppHarnessError("clipboard_unavailable", str(exc)) from exc

        self.goto(anchor_text)

        return self.client.keys(self.window, self._chord("paste", "^v"))

    def sheet_names(self) -> list[str]:
        """Return sheet tab names in tab order."""

        selector = self.recipe.selector("sheet_tabs")

        if not selector:
            raise AppHarnessError(
                "unsupported_feature",
                f"the {self.recipe.key} recipe has no sheet-tab selector",
            )

        elements = [element for element in self._find_all(selector) if not _is_ribbon_tab(element)]
        names: list[str] = []

        for element in elements:
            name = (element.name or "").strip()

            if name and name not in names:
                names.append(name)

        if not names:
            raise AppHarnessError(
                "sheet_not_found",
                f"no sheet tabs matched {selector!r} in window {self.window!r}",
            )

        return names

    def activate_sheet(self, name: str) -> ActionResult:
        """Activate the sheet tab named ``name``."""

        selector = self.recipe.selector("sheet_tabs")

        if not selector:
            raise AppHarnessError(
                "unsupported_feature",
                f"the {self.recipe.key} recipe has no sheet-tab selector",
            )

        elements = [
            element
            for element in self._find_all(selector)
            if not _is_ribbon_tab(element)
            and (element.name or "").strip().casefold() == name.casefold()
        ]

        if not elements:
            raise AppHarnessError(
                "sheet_not_found",
                f"no sheet named {name!r} in window {self.window!r}",
            )

        target = _target_from_element(elements[0])
        select = getattr(self.client, "select", None)

        if callable(select):
            return select(self.window, target)

        return self.client.click(self.window, target)

    def is_editing(self) -> bool:
        """Return whether a cell editor appears to be open.

        This is a best-effort probe built on recipe-provided formula-bar
        indicators; see :mod:`cecli.helpers.app_harness.recipes` for the per-app
        selectors.
        """

        selector = self.recipe.selector("editing_probe")

        if not selector:
            return False

        try:
            elements = self._find_all(selector)
        except AppHarnessError:
            return False

        return any(element.enabled and not element.offscreen for element in elements)

    def cancel_edit(self) -> ActionResult:
        """Send Escape to leave in-cell editing without committing."""

        return self.client.keys(self.window, self._chord("cancel_edit", "{ESC}"))

    def _detect_app(self) -> str | None:
        """Detect the app from the target window, falling back to its label."""

        for window in self._known_windows():
            if _window_matches(window, self._window_spec):
                detected = recipes.detect_app(window)

                if detected:
                    return detected

        return recipes.detect_app(self._window_spec)

    def _known_windows(self) -> list[Window]:
        """Return windows from the client, caching the successful response."""

        if self._windows is None:
            try:
                self._windows = list(self.client.windows())
            except AppHarnessError:
                self._windows = []

        return self._windows

    def _grid(self) -> dict[str, Any] | None:
        """Resolve the optional grid argument into a bridge target."""

        if self._grid_resolved:
            return self._grid_target

        self._grid_resolved = True

        if self.grid is None:
            self._grid_target = None
        elif isinstance(self.grid, Mapping):
            self._grid_target = dict(self.grid)
        elif isinstance(self.grid, str):
            element = self.client.locator(self.window, self.grid).wait()
            self._grid_target = _target_from_element(element)
        elif hasattr(self.grid, "wait"):
            self._grid_target = _target_from_element(self.grid.wait())
        elif hasattr(self.grid, "id"):
            self._grid_target = _target_from_element(self.grid)
        else:
            raise AppHarnessError(
                "invalid_request",
                "grid must be a selector, target mapping, or element",
            )

        return self._grid_target

    def _cell_target(self, row: int, column: int) -> dict[str, Any] | None:
        """Return the cell target from ``cell_at``, tolerating older bridges."""

        try:
            result = self.cell(row, column)
        except AppHarnessError:
            return None

        return _target_from_result(result)

    def _write_text(
        self,
        row: int,
        column: int,
        text: str,
    ) -> ActionResult:
        """Write one cell through the Name Box and the clipboard.

        Keystrokes make Excel rewrite and challenge formulas, and a direct value
        write on a grid cell can leave the cell in edit mode, so the selection
        is set by reference and the text pasted. Empty text clears the cell.
        """

        self.goto(format_cell(row, column))

        if not text:
            return self.client.keys(self.window, self._chord("delete", "{DELETE}"))

        try:
            clipboard.set_text(text)
        except clipboard.ClipboardError as exc:
            raise AppHarnessError("clipboard_unavailable", str(exc)) from exc

        return self.client.keys(self.window, self._chord("paste", "^v"))

    def _select_reference(self, text: str) -> ActionResult:
        """Enter ``text`` in the Name Box and commit the selection."""

        selector = self.recipe.selector("name_box")

        if not selector:
            raise AppHarnessError(
                "unsupported_feature",
                f"the {self.recipe.key} recipe has no Name Box selector",
            )

        try:
            elements = self._find_all(selector)
        except AppHarnessError as exc:
            if exc.kind in ("not_found", "timeout"):
                raise AppHarnessError(
                    "not_found",
                    f"could not find the Name Box {selector!r} in window "
                    f"{self.window!r}; activate the spreadsheet first",
                ) from exc

            raise

        element = _pick_entry_element(elements)

        if element is None:
            raise AppHarnessError(
                "not_found",
                f"could not find the Name Box {selector!r} in window "
                f"{self.window!r}; activate the spreadsheet first",
            )

        self.client.set_value(self.window, text, _target_from_element(element))

        return self.client.keys(self.window, self._chord("commit", "{ENTER}"))

    def _find_all(self, selector: str) -> list[Element]:
        """Return every element matching ``selector`` without a result cap."""

        find_elements = getattr(self.client, "find_elements", None)

        if callable(find_elements):
            elements, _, _ = find_elements(self.window, selector, limit=-1)
            return list(elements)

        elements, _ = self.client.find(self.window, selector, limit=-1)

        return list(elements)

    def _chord(self, name: str, default: str) -> str:
        """Return a recipe key chord with a fallback."""

        return self.recipe.chord(name, default)

    def _reference_or_error(self, ref: str | tuple[int, int]) -> str:
        """Parse an A1 reference, converting failures to ``AppHarnessError``."""

        try:
            return _reference_text(ref)
        except ValueError as exc:
            raise AppHarnessError("invalid_request", str(exc)) from exc

    def _range_or_error(self, ref: str) -> tuple[RangePoint, RangePoint]:
        """Parse an A1 range, converting failures to ``AppHarnessError``."""

        try:
            return parse_range(ref)
        except ValueError as exc:
            raise AppHarnessError("invalid_request", str(exc)) from exc

    def _anchor_or_error(self, ref: str | tuple[int, int]) -> str:
        """Parse a block anchor, converting failures to ``AppHarnessError``."""

        try:
            return _anchor_text(ref)
        except ValueError as exc:
            raise AppHarnessError("invalid_request", str(exc)) from exc


def _explicit_app(app: str | None) -> str | None:
    """Normalize an explicitly supplied app key or alias."""

    if app is None:
        return None

    try:
        return recipes.get_recipe(app).key
    except recipes.UnknownAppError as exc:
        raise AppHarnessError("invalid_request", str(exc)) from exc


def _check_position(row: int, column: int) -> None:
    """Reject non-positive or non-integer cell coordinates."""

    if not isinstance(row, int) or isinstance(row, bool) or row < 1:
        raise AppHarnessError("invalid_request", f"row must be a positive integer, got {row!r}")

    if not isinstance(column, int) or isinstance(column, bool) or column < 1:
        raise AppHarnessError(
            "invalid_request", f"column must be a positive integer, got {column!r}"
        )


def _window_key(window: str | Window) -> str:
    """Return the bridge window key for a title, handle or Window object."""

    if isinstance(window, Window):
        key = window.title or window.handle
    else:
        key = str(window or "")

    key = key.strip()

    if not key:
        raise AppHarnessError("invalid_request", "window must not be empty")

    return key


def _window_matches(window: Window, spec: Any) -> bool:
    """Return whether ``window`` is the one named by ``spec``."""

    if isinstance(spec, Window):
        if spec.handle and window.handle == spec.handle:
            return True

        values = [spec.title]
    else:
        values = [str(spec)]

    for value in values:
        text = (value or "").strip().casefold()

        if not text:
            continue

        if window.handle and window.handle.casefold() == text:
            return True

        if window.process_name and window.process_name.casefold() == text:
            return True

        if window.title:
            title = window.title.casefold()

            if title == text or text in title or title in text:
                return True

    return False


def _reference_text(ref: str | tuple[int, int]) -> str:
    """Return a canonical A1 reference, preserving any sheet prefix."""

    if isinstance(ref, (tuple, list)):
        if len(ref) != 2:
            raise ValueError("an A1 reference tuple must hold (row, column)")

        return format_cell(int(ref[0]), int(ref[1]))

    if not isinstance(ref, str):
        raise ValueError("an A1 reference must be a string or (row, column) tuple")

    sheet, body = _split_sheet(ref)
    start, end = _parse_range_body(body)
    text = format_range(start, end)

    return f"{sheet}!{text}" if sheet else text


def _anchor_text(ref: str | tuple[int, int]) -> str:
    """Return the top-left cell of ``ref`` as an A1 reference."""

    if isinstance(ref, (tuple, list)):
        if len(ref) != 2:
            raise ValueError("an A1 reference tuple must hold (row, column)")

        return format_cell(int(ref[0]), int(ref[1]))

    sheet, body = _split_sheet(ref)
    start, _ = _parse_range_body(body)

    if start[0] is None or start[1] is None:
        raise ValueError(f"anchor must name a single cell: {ref!r}")

    text = format_cell(*start)

    return f"{sheet}!{text}" if sheet else text


def _split_sheet(ref: str) -> tuple[str, str]:
    """Split an optional sheet prefix from an A1 body."""

    if not isinstance(ref, str):
        raise ValueError("an A1 reference must be a string")

    text = ref.strip()

    if "!" not in text:
        return "", text

    sheet, body = text.rsplit("!", 1)

    return sheet.strip(), body.strip()


def _parse_range_body(text: str) -> tuple[RangePoint, RangePoint]:
    """Parse the body of an A1 reference (everything after the sheet)."""

    if not text:
        raise ValueError("A1 reference must not be empty")

    parts = text.split(":")

    if len(parts) == 1:
        point = _parse_point(parts[0])
        return point, point

    if len(parts) != 2:
        raise ValueError(f"invalid A1 range: {text!r}")

    start = _parse_point(parts[0])
    end = _parse_point(parts[1])

    if _point_kind(start) != _point_kind(end):
        raise ValueError(f"range endpoints must have the same shape: {text!r}")

    return start, end


def _parse_point(text: str) -> RangePoint:
    """Parse one cell, column-only, or row-only endpoint."""

    part = text.strip()
    cell = _CELL_PATTERN.match(part)

    if cell:
        return int(cell.group(2)), _column_index(cell.group(1))

    column = _COLUMN_PATTERN.match(part)

    if column:
        return None, _column_index(column.group(1))

    row = _ROW_PATTERN.match(part)

    if row:
        return int(row.group(1)), None

    raise ValueError(f"invalid A1 reference part: {part!r}")


def _point_kind(point: RangePoint) -> str:
    """Classify an endpoint as a cell, a whole column, or a whole row."""

    row, column = point

    if row is None:
        return "column"

    if column is None:
        return "row"

    return "cell"


def _format_point(point: RangePoint) -> str:
    """Render one endpoint, allowing an open row or column."""

    row, column = point

    if row is None and column is None:
        raise ValueError("an A1 reference part must name a row, column, or cell")

    if column is None:
        return str(row)

    if row is None:
        return _column_letters(column)

    return format_cell(row, column)


def _column_index(letters: str) -> int:
    """Convert bijective base-26 column letters to a one-based index."""

    index = 0

    for char in letters.upper():
        if not "A" <= char <= "Z":
            raise ValueError(f"invalid column letters: {letters!r}")

        index = index * 26 + (ord(char) - ord("A") + 1)

    return index


def _column_letters(column: int) -> str:
    """Convert a one-based column index to bijective base-26 letters."""

    if column < 1:
        raise ValueError(f"column must be positive, got {column!r}")

    letters = ""

    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(ord("A") + remainder) + letters

    return letters


def _concrete_bounds(start: RangePoint, end: RangePoint) -> tuple[int, int, int, int]:
    """Return normalized concrete bounds or raise for open-ended ranges."""

    if None in (start[0], start[1], end[0], end[1]):
        raise AppHarnessError(
            "unsupported_range",
            "reading a whole column or row is not supported; name both endpoints",
        )

    first_row = min(int(start[0]), int(end[0]))
    last_row = max(int(start[0]), int(end[0]))
    first_column = min(int(start[1]), int(end[1]))
    last_column = max(int(start[1]), int(end[1]))

    return first_row, last_row, first_column, last_column


def _target_from_result(result: ActionResult) -> dict[str, Any] | None:
    """Build a bridge target from the element attached to ``result``."""

    if not isinstance(result.element, Mapping):
        return None

    return _target_from_element(result.element)


def _target_from_element(value: Any) -> dict[str, Any]:
    """Build a bridge target from an Element or a raw element mapping."""

    if isinstance(value, Element):
        data: Mapping[str, Any] = {
            "id": value.id,
            "runtime_id": value.runtime_id,
            "path": value.path,
        }
    elif isinstance(value, Mapping):
        data = value
    else:
        return {}

    target: dict[str, Any] = {}

    if data.get("id") is not None:
        target["id"] = data["id"]

    for key in ("runtime_id", "path"):
        if data.get(key):
            target[key] = data[key]

    return target


def _result_text(result: ActionResult) -> str:
    """Return the value a cell action reported, falling back to its element."""

    if result.value is not None:
        return result.value.lstrip("\ufeff")

    if isinstance(result.element, Mapping):
        for key in ("value", "name"):
            item = result.element.get(key)

            if item is not None:
                return str(item)

    return ""


def _tsv_text(rows_or_text: Any) -> str:
    """Return TSV text from either a string or a row-major sequence."""

    if isinstance(rows_or_text, str):
        return rows_or_text

    if rows_or_text is None:
        raise AppHarnessError("invalid_request", "TSV rows must not be None")

    if not isinstance(rows_or_text, (list, tuple)):
        raise AppHarnessError("invalid_request", "TSV rows must be a sequence of rows or a string")

    values = list(rows_or_text)

    if values and not any(isinstance(row, (list, tuple)) for row in values):
        values = [values]

    lines: list[str] = []

    for row in values:
        cells = list(row) if isinstance(row, (list, tuple)) else [row]
        lines.append("\t".join(_tsv_field(cell) for cell in cells))

    return "\n".join(lines)


def _tsv_field(value: Any) -> str:
    """Render one field, quoting values that would break the tab structure."""

    text = "" if value is None else str(value)

    if any(char in text for char in '\t\n\r"'):
        return '"' + text.replace('"', '""') + '"'

    return text


def _quote_selector_value(value: str) -> str:
    """Quote a string for a locator ``[name="..."]`` attribute."""

    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')

    return f'"{escaped}"'


def _is_ribbon_tab(element: Any) -> bool:
    """Return whether a tab item belongs to the ribbon rather than the workbook.

    Excel exposes both ribbon tabs and sheet tabs as ``TabItem`` nodes; the
    ribbon ones live under a ``Tab[Ribbon Tabs]`` ancestor, which shows up in the
    element path.
    """

    if (getattr(element, "automation_id", None) or "").casefold() == "sheettab":
        return False

    path = getattr(element, "path", None) or ""

    return "[Ribbon Tabs]" in path


def _pick_entry_element(elements: Any) -> Element | None:
    """Return the most settable element from a locator match set.

    Excel exposes the Name Box as both a ``ComboBox`` and a nested ``Edit``, so
    an exact selector matches two nodes. The text-entry node wins.
    """

    items = [element for element in elements if getattr(element, "enabled", True)]

    for element in items:
        if (getattr(element, "control_type", "") or "").casefold() in (
            "edit",
            "text_field",
            "entry",
        ):
            return element

    if items:
        return items[0]

    return elements[0] if elements else None
