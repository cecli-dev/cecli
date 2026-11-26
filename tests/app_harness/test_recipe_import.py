"""Tests for external app-recipe discovery and defaults."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cecli.helpers.app_harness import recipes  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_recipes(monkeypatch, tmp_path):
    monkeypatch.setenv("CECLI_APP_RECIPES_DIRS", str(tmp_path))
    recipes.reload_recipes()

    yield

    recipes.reload_recipes()


def test_bundled_recipes_are_importable_per_app():
    from cecli.helpers.app_harness.recipes.defaults import DEFAULT_RECIPES

    assert set(DEFAULT_RECIPES) == {"excel", "libreoffice"}
    assert DEFAULT_RECIPES["excel"].source.endswith("excel.yml")
    assert DEFAULT_RECIPES["excel"].selector("name_box")


def test_yaml_recipe_is_loaded(tmp_path):
    (tmp_path / "notepad.yaml").write_text(
        """\
key: notepad
display_name: Notepad
process_names: [notepad.exe, notepad]
title_markers: [notepad]
selectors:
  editor: "document[name='Text editor']"
keys:
  save: "^s"
sections:
  Text: ["Use set_value on the document."]
gotchas: ["Use wait_for_value after typing."]
""",
        encoding="utf-8",
    )

    recipes.reload_recipes()

    recipe = recipes.get_recipe("notepad")

    assert recipe.display_name == "Notepad"
    assert recipe.source.endswith("notepad.yaml")
    assert recipe.selector("editor") == "document[name='Text editor']"
    assert recipes.detect_app({"process_name": "notepad.exe"}) == "notepad"


def test_json_recipe_list_can_override_a_default(tmp_path):
    (tmp_path / "apps.json").write_text(
        json.dumps(
            [
                {
                    "key": "excel",
                    "display_name": "Custom Excel",
                    "process_names": ["excel.exe"],
                }
            ]
        ),
        encoding="utf-8",
    )

    recipes.reload_recipes()

    assert recipes.get_recipe("excel").display_name == "Custom Excel"
    assert recipes.get_recipe("excel").source.endswith("apps.json")


def test_invalid_recipes_are_skipped(tmp_path):
    (tmp_path / "broken.yaml").write_text("key: broken\n", encoding="utf-8")
    (tmp_path / "good.yaml").write_text("key: good\nprocess_names: [good.exe]\n", encoding="utf-8")

    recipes.reload_recipes()

    assert "broken" not in recipes.list_apps()
    assert "good" in recipes.list_apps()


def test_python_files_are_not_imported(tmp_path):
    (tmp_path / "evil.py").write_text("raise RuntimeError('should not run')\n", encoding="utf-8")

    recipes.reload_recipes()

    assert recipes.list_apps() == ["excel", "libreoffice"]


def test_environment_can_disable_external_recipes(monkeypatch):
    monkeypatch.setenv("CECLI_APP_RECIPES_DIRS", "")

    assert recipes.recipe_dirs() == []


def test_creator_helper_writes_a_yml_recipe(tmp_path):
    from cecli.helpers.creator import app_recipe_helpers

    fragment, notes = app_recipe_helpers.build_fragment(
        None,
        tmp_path,
        "notepad",
        None,
        "key: notepad\ndisplay_name: Notepad\nprocess_names: [notepad.exe]\n",
    )

    assert fragment == {}
    assert (tmp_path / "app-recipes" / "notepad.yml").exists()
    assert any("notepad.yml" in note for note in notes)
