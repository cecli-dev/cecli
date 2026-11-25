"""Recipe registry: bundled defaults plus external recipes, lookup, and detection."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .defaults import DEFAULT_RECIPES
from .importer import load_external_recipes
from .schema import AppRecipe, UnknownAppError

_REGISTRY: dict[str, AppRecipe] | None = None
_ALIASES: dict[str, str] | None = None


def reload_recipes() -> int:
    """Drop the cached registry so the next lookup re-reads external recipes."""

    global _REGISTRY, _ALIASES

    _REGISTRY = None
    _ALIASES = None

    return len(registry())


def registry() -> dict[str, AppRecipe]:
    """Return the merged recipe registry in registration order."""

    global _REGISTRY, _ALIASES

    if _REGISTRY is None:
        recipes = dict(DEFAULT_RECIPES)
        recipes.update(load_external_recipes())
        _REGISTRY = recipes
        _ALIASES = _build_aliases(recipes)

    return _REGISTRY


def list_apps() -> list[str]:
    """Return the recipe keys in registration order."""

    return list(registry())


def get_recipe(app: str) -> AppRecipe:
    """Return the recipe for ``app`` (key, alias, or display name)."""

    if not isinstance(app, str) or not app.strip():
        raise UnknownAppError(f"unknown app {app!r}; known apps: {', '.join(list_apps())}")

    key = _build_aliases(registry()).get(app.strip().casefold())

    if key is None:
        raise UnknownAppError(f"unknown app {app!r}; known apps: {', '.join(list_apps())}")

    return registry()[key]


def detect_app(window_or_process_name: Any) -> str | None:
    """Return the recipe key for a window, process name, or title.

    Accepts a :class:`~cecli.helpers.app_harness.models.Window`-like object, a
    mapping with ``process_name``/``title`` keys, or a plain string. ``None``
    means no recipe matched and the caller should ask for an explicit ``app=``.
    """

    values = _detection_values(window_or_process_name)

    for recipe in registry().values():
        if any(_matches(recipe, value) for value in values):
            return recipe.key

    return None


def _build_aliases(recipes: Mapping[str, AppRecipe]) -> dict[str, str]:
    """Build the case-insensitive alias map from the recipe definitions."""

    aliases: dict[str, str] = {}

    for key, recipe in recipes.items():
        for alias in (key, recipe.display_name, *recipe.aliases):
            aliases[alias.casefold()] = key

    return aliases


def _detection_values(value: Any) -> list[str]:
    """Collect string candidates from a window object, mapping or plain string."""

    if value is None:
        return []

    if isinstance(value, str):
        return [value]

    if isinstance(value, Mapping):
        keys = ("process_name", "process", "title", "name", "class_name")

        return [str(value[key]) for key in keys if value.get(key)]

    candidates: list[str] = []

    for attribute in ("process_name", "title", "name", "class_name"):
        item = getattr(value, attribute, None)

        if isinstance(item, str) and item:
            candidates.append(item)

    if not candidates:
        candidates.append(str(value))

    return candidates


def _matches(recipe: AppRecipe, value: str) -> bool:
    """Return whether ``value`` names or titles ``recipe``'s application."""

    text = value.strip().casefold()

    if not text:
        return False

    process = _normalize_process(text)

    for name in recipe.process_names:
        if process == _normalize_process(name) or text == name.casefold():
            return True

    return any(marker.casefold() in text for marker in recipe.title_markers)


def _normalize_process(value: str) -> str:
    """Lowercase a process name and drop its directory and executable suffix."""

    name = re.split(r"[\\/]", value.strip())[-1].casefold()

    for suffix in (".exe", ".bin"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]

    return name
