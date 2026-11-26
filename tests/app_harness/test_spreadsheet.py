"""Tests for A1 parsing and the spreadsheet helpers against a fake client."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cecli.helpers.app_harness import clipboard, spreadsheet  # noqa: E402
from cecli.helpers.app_harness.client import AppHarnessError  # noqa: E402
from cecli.helpers.app_harness.models import ActionResult, Element, Window  # noqa: E402
from cecli.helpers.app_harness.spreadsheet import (  # noqa: E402
    Spreadsheet,
    format_cell,
    format_range,
    parse_cell,
    parse_range,
)


class FakeLocator:
    """Resolve selectors through :class:`FakeClient` immediately."""

    def __init__(self, owner, selector):
        self.owner = owner
        self.selector = selector

    def wait(self):
        self.owner.locator_calls.append(self.selector)

        return self.owner.element_for(self.selector)


class FakeClient:
    """Minimal app-harness client that records calls and serves canned cells."""

    def __init__(self, windows=None, tab_names=(), cells=None, editing=False):
        self.window_list = (
            list(windows)
            if windows is not None
            else [
                Window(
                    handle="0x10",
                    process_name="excel.exe",
                    title="Book1 - Excel",
                    class_name="XLMAIN",
                )
            ]
        )
        self.tab_names = list(tab_names)
        self.cells = dict(cells or {})
        self.editing = editing
        self.cell_calls = []
        self.key_calls = []
        self.set_value_calls = []
        self.locator_calls = []
        self.select_calls = []
        self.click_calls = []

    def windows(self):
        return self.window_list

    def cell_at(self, window, row, column, grid=None):
        self.cell_calls.append((window, row, column, grid))
        value = self.cells.get((row, column), format_cell(row, column))

        return ActionResult(
            action="cell_at",
            delivered=True,
            verified=True,
            value=value,
            element={
                "id": row * 100 + column,
                "value": value,
                "path": f"grid/{row}/{column}",
            },
        )

    def keys(self, window, keys, target=None):
        self.key_calls.append((window, keys, target))

        return ActionResult(action="keys", delivered=True, verified=True)

    def set_value(self, window, value, target=None):
        self.set_value_calls.append((window, value, target))

        return ActionResult(action="set_value", delivered=True, verified=True, value=value)

    def locator(self, window, selector, **kwargs):
        return FakeLocator(self, selector)

    def find_elements(self, window, selector, limit=50, **kwargs):
        if "page_tab" in selector or "tab_item" in selector:
            elements = [
                Element(
                    id=100 + index,
                    control_type="PageTab",
                    name=name,
                    path=f"tabs/{name}",
                )
                for index, name in enumerate(self.tab_names)
            ]
            elements = self._filter_named(selector, elements)

            return elements, len(elements), False

        if "Name Box" in selector:
            elements = [
                Element(id=6, control_type="ComboBox", name="Name Box", path="win/namebox"),
                Element(
                    id=7,
                    control_type="Edit",
                    name="Name Box",
                    runtime_id="42.7",
                    path="win/namebox/edit",
                ),
            ]

            return elements, len(elements), False

        if any(token in selector for token in ("Cancel", "Apply", "Enter")):
            elements = (
                [Element(id=200, control_type="Button", name="Cancel")] if self.editing else []
            )

            return elements, len(elements), False

        return [], 0, False

    def element_for(self, selector):
        if "Name Box" in selector:
            return Element(
                id=7,
                control_type="Edit",
                name="Name Box",
                runtime_id="42.7",
                path="win/namebox",
            )

        if selector == "table":
            return Element(id=11, control_type="Table", name="Grid", path="win/grid")

        if "page_tab" in selector or "tab_item" in selector:
            elements = [
                Element(
                    id=100 + index,
                    control_type="PageTab",
                    name=name,
                    path=f"tabs/{name}",
                )
                for index, name in enumerate(self.tab_names)
            ]
            matched = self._filter_named(selector, elements)

            if matched:
                return matched[0]

            raise AppHarnessError("not_found", f"no element matches {selector!r}")

        raise AppHarnessError("not_found", f"no element matches {selector!r}")

    def select(self, window, target):
        self.select_calls.append((window, target))

        return ActionResult(action="select", delivered=True, verified=True)

    def click(self, window, target=None):
        self.click_calls.append((window, target))

        return ActionResult(action="click", delivered=True, verified=True)

    def _filter_named(self, selector, elements):
        if 'name="' not in selector:
            return elements

        wanted = selector.split('name="', 1)[1].rsplit('"', 1)[0]

        return [element for element in elements if element.name == wanted]


class _RibbonTabClient(FakeClient):
    """Fake client whose workbook and ribbon tabs are both ``TabItem`` nodes."""

    def find_elements(self, window, selector, limit=50, **kwargs):
        if "tab_item" not in selector:
            return super().find_elements(window, selector, limit=limit, **kwargs)

        elements = [
            Element(
                id=1,
                control_type="TabItem",
                name="Home",
                automation_id="TabHome",
                path="win/Tab[Ribbon Tabs]/TabItem[Home]",
            ),
            Element(
                id=2,
                control_type="TabItem",
                name="Sheet1",
                automation_id="SheetTab",
                path="win/Tab[Workbook]/TabItem[Sheet1]",
            ),
        ]

        return elements, len(elements), False


def _sheet(client=None, **kwargs):
    return Spreadsheet(client or FakeClient(), "Book1 - Excel", **kwargs)


# A1 parsing


def test_parse_cell_accepts_plain_and_absolute_refs():
    assert parse_cell("A1") == (1, 1)
    assert parse_cell("$B$3") == (3, 2)
    assert parse_cell("aa10") == (10, 27)
    assert parse_cell("Sheet1!C4") == (4, 3)
    assert parse_cell("'My Sheet'!b2") == (2, 2)


def test_parse_cell_rejects_ranges_and_bad_refs():
    for ref in ("A1:C3", "A0", "1A", "", "AAAA1"):
        with pytest.raises(ValueError):
            parse_cell(ref)


def test_parse_range_handles_cells_and_directions():
    assert parse_range("A1:C3") == ((1, 1), (3, 3))
    assert parse_range("B2") == ((2, 2), (2, 2))
    assert parse_range("$C$3:$A$1") == ((3, 3), (1, 1))
    assert parse_range(" A1 : C3 ") == ((1, 1), (3, 3))
    assert parse_range("Sheet1!A1:B2") == ((1, 1), (2, 2))


def test_parse_range_handles_open_columns_and_rows():
    assert parse_range("A:C") == ((None, 1), (None, 3))
    assert parse_range("2:4") == ((2, None), (4, None))


def test_parse_range_rejects_malformed_input():
    for ref in ("", "A1:B2:C3", "A1:", "A1:Q"):
        with pytest.raises(ValueError):
            parse_range(ref)


def test_format_cell_and_range_round_trip():
    assert format_cell(1, 1) == "A1"
    assert format_cell(10, 27) == "AA10"
    assert format_cell(1000, 703) == "AAA1000"
    assert format_range((1, 1), (3, 3)) == "A1:C3"
    assert format_range((2, 2), (2, 2)) == "B2"

    with pytest.raises(ValueError):
        format_cell(0, 1)


# Cell reads and writes


def test_cell_and_value_forward_row_column_and_grid():
    client = FakeClient()
    sheet = Spreadsheet(client, "Book1 - Excel", grid={"id": 5})

    result = sheet.cell(2, 3)

    assert result.value == "C2"
    assert client.cell_calls == [("Book1 - Excel", 2, 3, {"id": 5})]
    assert sheet.value(2, 3) == ""


def test_grid_selector_is_resolved_to_a_target():
    client = FakeClient()
    sheet = Spreadsheet(client, "Book1 - Excel", grid="table")

    sheet.cell(1, 1)

    assert client.locator_calls == ["table"]
    assert client.cell_calls[0][3] == {"id": 11, "path": "win/grid"}


def test_set_cell_selects_the_reference_and_pastes(monkeypatch):
    sent = []
    monkeypatch.setattr(spreadsheet.clipboard, "set_text", lambda text: sent.append(text))
    client = FakeClient()
    sheet = _sheet(client)

    result = sheet.set_cell(1, 2, "hi")

    assert result.action == "keys"
    assert sent == ["hi"]
    assert client.set_value_calls[0][1] == "B1"
    assert [keys for _, keys, _ in client.key_calls] == ["{ENTER}", "^v"]


def test_set_cell_clears_with_delete(monkeypatch):
    sent = []
    monkeypatch.setattr(spreadsheet.clipboard, "set_text", lambda text: sent.append(text))
    client = FakeClient()
    sheet = _sheet(client)

    result = sheet.set_cell(1, 1, None)

    assert result.action == "keys"
    assert sent == []
    assert [keys for _, keys, _ in client.key_calls] == ["{ENTER}", "{DELETE}"]


def test_set_cell_falls_back_to_name_box_and_clipboard(monkeypatch):
    sent = []
    monkeypatch.setattr(spreadsheet.clipboard, "set_text", lambda text: sent.append(text))
    client = FakeClient()
    sheet = _sheet(client)

    sheet.set_cell(1, 1, "fallback")

    assert sent == ["fallback"]
    assert client.set_value_calls == [
        (
            "Book1 - Excel",
            "A1",
            {"id": 7, "runtime_id": "42.7", "path": "win/namebox/edit"},
        )
    ]
    assert [keys for _, keys, _ in client.key_calls] == ["{ENTER}", "^v"]

    # Navigation
    client = FakeClient()
    sheet = _sheet(client)

    sheet.goto("B3")

    assert client.set_value_calls == [
        (
            "Book1 - Excel",
            "B3",
            {"id": 7, "runtime_id": "42.7", "path": "win/namebox/edit"},
        )
    ]
    assert client.key_calls == [("Book1 - Excel", "{ENTER}", None)]


def test_goto_preserves_sheet_prefix_and_canonicalizes_case():
    client = FakeClient()
    sheet = _sheet(client)

    sheet.goto("'My Sheet'!b3")

    assert client.set_value_calls[-1][1] == "'My Sheet'!B3"


def test_select_range_types_the_range_into_the_name_box():
    client = FakeClient()
    sheet = _sheet(client)

    sheet.select_range("a1:c3")

    assert client.set_value_calls[-1][1] == "A1:C3"
    assert client.key_calls[-1][1] == "{ENTER}"


def test_goto_rejects_invalid_reference():
    sheet = _sheet()

    with pytest.raises(AppHarnessError) as excinfo:
        sheet.goto("not-a-ref")

    assert excinfo.value.kind == "invalid_request"


def test_cell_rejects_non_positive_coordinates():
    sheet = _sheet()

    for row, column in ((0, 1), (1, 0), (True, 1)):
        with pytest.raises(AppHarnessError) as excinfo:
            sheet.cell(row, column)

        assert excinfo.value.kind == "invalid_request"


# Ranges


def test_read_range_normalizes_and_reads_row_major():
    client = FakeClient(cells={(1, 1): "a", (1, 2): "b", (2, 1): "c", (2, 2): "d"})
    sheet = _sheet(client)

    assert sheet.read_range("B2:A1") == [["a", "b"], ["c", "d"]]
    assert len(client.cell_calls) == 4


def test_read_range_rejects_open_ended_ranges():
    sheet = _sheet()

    with pytest.raises(AppHarnessError) as excinfo:
        sheet.read_range("A:C")

    assert excinfo.value.kind == "unsupported_range"


def test_write_range_pastes_tsv_at_the_anchor(monkeypatch):
    sent = []
    monkeypatch.setattr(spreadsheet.clipboard, "set_text", lambda text: sent.append(text))
    client = FakeClient()
    sheet = _sheet(client)

    sheet.write_range("B2", [[1, 2], [3, 4]])

    assert sent == ["1\t2\n3\t4"]
    assert client.set_value_calls[-1][1] == "B2"
    assert client.key_calls[-1][1] == "^v"


def test_paste_tsv_quotes_fields_that_break_the_grid(monkeypatch):
    sent = []
    monkeypatch.setattr(spreadsheet.clipboard, "set_text", lambda text: sent.append(text))
    sheet = _sheet()

    sheet.paste_tsv("A1", [["a\tb", 'q"x'], ["line\nbreak", None]])

    assert sent == ['"a\tb"\t"q""x"\n"line\nbreak"\t']


def test_paste_tsv_accepts_ready_made_text(monkeypatch):
    sent = []
    monkeypatch.setattr(spreadsheet.clipboard, "set_text", lambda text: sent.append(text))
    sheet = _sheet()

    sheet.paste_tsv("A1", "a\tb")

    assert sent == ["a\tb"]


def test_paste_tsv_rejects_empty_data():
    sheet = _sheet()

    with pytest.raises(AppHarnessError) as excinfo:
        sheet.paste_tsv("A1", [])

    assert excinfo.value.kind == "invalid_request"


def test_paste_tsv_wraps_clipboard_failure(monkeypatch):
    def fail(text):
        raise clipboard.ClipboardError("no clipboard")

    monkeypatch.setattr(spreadsheet.clipboard, "set_text", fail)
    sheet = _sheet()

    with pytest.raises(AppHarnessError) as excinfo:
        sheet.paste_tsv("A1", "x")

    assert excinfo.value.kind == "clipboard_unavailable"


# Sheets


def test_sheet_names_returns_tab_names_in_order():
    client = FakeClient(tab_names=["Sheet1", "Sheet2"])
    sheet = _sheet(client)

    assert sheet.sheet_names() == ["Sheet1", "Sheet2"]


def test_sheet_names_raises_when_no_tabs_match():
    sheet = _sheet()

    with pytest.raises(AppHarnessError) as excinfo:
        sheet.sheet_names()

    assert excinfo.value.kind == "sheet_not_found"


def test_activate_sheet_selects_the_named_tab():
    client = FakeClient(tab_names=["Sheet1", "Sheet2"])
    sheet = _sheet(client)

    result = sheet.activate_sheet("Sheet2")

    assert result.action == "select"
    assert client.select_calls == [("Book1 - Excel", {"id": 101, "path": "tabs/Sheet2"})]


def test_activate_sheet_reports_missing_names():
    client = FakeClient(tab_names=["Sheet1"])
    sheet = _sheet(client)

    with pytest.raises(AppHarnessError) as excinfo:
        sheet.activate_sheet("Missing")

    assert excinfo.value.kind == "sheet_not_found"


def test_sheet_names_ignores_ribbon_tabs():
    sheet = _sheet(_RibbonTabClient())

    assert sheet.sheet_names() == ["Sheet1"]

    with pytest.raises(AppHarnessError) as excinfo:
        sheet.activate_sheet("Home")

    assert excinfo.value.kind == "sheet_not_found"


def test_value_strips_a_clipboard_bom():
    client = FakeClient(cells={(1, 1): "\ufeffalpha"})
    sheet = _sheet(client)

    assert sheet.value(1, 1) == "alpha"


# Editing state


def test_is_editing_uses_recipe_probe():
    client = FakeClient(editing=True)
    sheet = _sheet(client)

    assert sheet.is_editing() is True

    client.editing = False

    assert sheet.is_editing() is False


def test_cancel_edit_sends_escape():
    client = FakeClient()
    sheet = _sheet(client)

    sheet.cancel_edit()

    assert client.key_calls == [("Book1 - Excel", "{ESC}", None)]


# App detection


def test_app_detects_libreoffice_from_window_list():
    window = Window(
        handle="0x20",
        process_name="soffice.bin",
        title="Untitled 1 - LibreOffice Calc",
    )
    client = FakeClient(windows=[window])
    sheet = Spreadsheet(client, "Untitled 1 - LibreOffice Calc")

    assert sheet.app == "libreoffice"
    assert sheet.recipe.key == "libreoffice"


def test_explicit_app_alias_wins_over_window_detection():
    sheet = Spreadsheet(FakeClient(), "Book1 - Excel", app="calc")

    assert sheet.app == "libreoffice"


def test_explicit_unknown_app_raises():
    with pytest.raises(AppHarnessError) as excinfo:
        Spreadsheet(FakeClient(), "Book1 - Excel", app="gnumeric")

    assert excinfo.value.kind == "invalid_request"


def test_unknown_app_blocks_app_specific_helpers():
    client = FakeClient(windows=[])
    sheet = Spreadsheet(client, "Mystery Window")

    assert sheet.app is None

    with pytest.raises(AppHarnessError) as excinfo:
        sheet.goto("A1")

    assert excinfo.value.kind == "unsupported_app"


def test_window_object_is_accepted():
    window = Window(handle="0x99", process_name="excel.exe", title="Budget - Excel")
    client = FakeClient(windows=[window])
    sheet = Spreadsheet(client, window)

    assert sheet.window == "Budget - Excel"

    sheet.cell(1, 1)

    assert client.cell_calls[0][0] == "Budget - Excel"
