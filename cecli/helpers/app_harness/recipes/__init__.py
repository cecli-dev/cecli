"""Application recipes for app-harness.

A recipe names the selectors, key chords, and caveats needed to drive one
application. Bundled recipes live in :mod:`defaults`; users and projects can
add their own YAML/JSON recipes in the directories searched by
:mod:`importer`.
"""

from .defaults import DEFAULT_RECIPES
from .help import help_text
from .importer import load_external_recipes, recipe_dirs
from .registry import detect_app, get_recipe, list_apps, registry, reload_recipes
from .schema import AppRecipe, UnknownAppError, recipe_from_mapping

__all__ = [
    "DEFAULT_RECIPES",
    "AppRecipe",
    "UnknownAppError",
    "detect_app",
    "get_recipe",
    "help_text",
    "list_apps",
    "load_external_recipes",
    "recipe_dirs",
    "recipe_from_mapping",
    "registry",
    "reload_recipes",
]
