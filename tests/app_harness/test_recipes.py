"""Tests for the Excel and LibreOffice recipe registry."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cecli.helpers.app_harness import recipes  # noqa: E402
from cecli.helpers.app_harness.models import Window  # noqa: E402


def test_list_apps_in_registration_order():
    assert recipes.list_apps() == ["excel", "libreoffice"]


def test_detect_app_from_process_names():
    assert recipes.detect_app("excel.exe") == "excel"
    assert recipes.detect_app("EXCEL.EXE") == "excel"
    assert recipes.detect_app("soffice.bin") == "libreoffice"
    assert recipes.detect_app("scalc.bin") == "libreoffice"


def test_detect_app_from_paths_and_titles():
    path = r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE"

    assert recipes.detect_app(path) == "excel"
    assert recipes.detect_app("Book1 - Excel") == "excel"
    assert recipes.detect_app("Untitled 1 - LibreOffice Calc") == "libreoffice"


def test_detect_app_from_window_objects():
    excel = Window(handle="0x1", process_name="excel.exe", title="Budget - Excel")
    calc = Window(handle="0x2", process_name="soffice.bin", title="Sheet - LibreOffice Calc")

    assert recipes.detect_app(excel) == "excel"
    assert recipes.detect_app(calc) == "libreoffice"
    assert recipes.detect_app(Window(title="Book1 - Excel")) == "excel"


def test_detect_app_from_mapping():
    assert recipes.detect_app({"process_name": "excel.exe"}) == "excel"
    assert recipes.detect_app({"title": "LibreOffice Calc"}) == "libreoffice"


def test_detect_app_unknown_or_empty():
    assert recipes.detect_app("notepad.exe") is None
    assert recipes.detect_app({"process_name": "notepad.exe"}) is None
    assert recipes.detect_app(None) is None
    assert recipes.detect_app("") is None


def test_get_recipe_aliases():
    assert recipes.get_recipe("excel").key == "excel"
    assert recipes.get_recipe("MS-Excel").key == "excel"
    assert recipes.get_recipe("Calc").key == "libreoffice"
    assert recipes.get_recipe("libreoffice calc").key == "libreoffice"


def test_get_recipe_unknown_raises():
    with pytest.raises(recipes.UnknownAppError):
        recipes.get_recipe("gnumeric")

    with pytest.raises(recipes.UnknownAppError):
        recipes.get_recipe("")


def test_recipes_cover_the_required_surface():
    selector_names = ("name_box", "sheet_tabs", "editing_probe", "dialog_ok")
    key_names = ("edit_cell", "cancel_edit", "commit", "paste")
    section_names = (
        "Cell read/write",
        "Name box and goto",
        "Range selection",
        "TSV paste",
        "Sheet tabs",
        "Dialogs",
        "Text entry",
    )

    for app in recipes.list_apps():
        recipe = recipes.get_recipe(app)

        for name in selector_names:
            assert recipe.selector(name), f"{app} lacks selector {name}"

        for name in key_names:
            assert recipe.chord(name), f"{app} lacks key {name}"

        for name in section_names:
            assert recipe.sections.get(name), f"{app} lacks section {name}"

        assert recipe.gotchas


def test_help_text_overview_lists_apps():
    text = recipes.help_text()

    assert "# Spreadsheet recipes" in text
    assert "excel" in text
    assert "libreoffice" in text
    assert "help_text(app)" in text


def test_help_text_excel_includes_shortcuts_and_gotchas():
    text = recipes.help_text("excel")

    assert "Microsoft Excel" in text
    assert "Name Box" in text
    assert "^v" in text
    assert "A1:C3" in text
    assert "Paste Options" in text
    assert "Gotchas" in text


def test_help_text_libreoffice_mentions_text_import():
    text = recipes.help_text("calc")

    assert "LibreOffice Calc" in text
    assert "Text Import" in text
    assert "page_tab" in text


def test_help_text_unknown_app_raises():
    with pytest.raises(recipes.UnknownAppError):
        recipes.help_text("gnumeric")
