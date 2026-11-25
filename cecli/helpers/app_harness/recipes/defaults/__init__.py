"""Bundled app recipes shipped with app-harness.

Defaults are declarative ``.yml`` files in this package, loaded through the
same schema as user and project recipes. Add a new bundled app by dropping a
``<app>.yml`` file here; no Python registry edit is needed.
"""

from __future__ import annotations

from importlib.resources import files

import yaml

from ..schema import AppRecipe, recipe_from_mapping


def load_default_recipes() -> dict[str, AppRecipe]:
    """Load the bundled ``.yml`` recipes in filename order."""

    directory = files(__package__)
    recipes: dict[str, AppRecipe] = {}

    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        if not entry.name.endswith((".yml", ".yaml")):
            continue

        data = yaml.safe_load(entry.read_text(encoding="utf-8"))
        recipe = recipe_from_mapping(data, source=f"defaults/{entry.name}")
        recipes[recipe.key] = recipe

    return recipes


DEFAULT_RECIPES = load_default_recipes()

__all__ = ["DEFAULT_RECIPES", "load_default_recipes"]
