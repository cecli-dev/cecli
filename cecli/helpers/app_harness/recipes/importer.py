"""Load user and project app recipes from well-known directories.

External recipes are declarative (YAML or JSON). Python recipe modules are
not imported from user or project directories, so cloning a repository cannot
execute arbitrary code through its recipe files.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .schema import AppRecipe, recipe_from_mapping

LOGGER = logging.getLogger(__name__)

RECIPE_SUFFIXES = (".json", ".yaml", ".yml")
DEFAULT_RECIPE_DIRS = (
    Path.home() / ".cecli" / "app-recipes",
    Path.home() / ".agents" / "app-recipes",
)
PROJECT_RECIPE_DIRS = (
    Path("cecli") / "app-recipes",
    Path(".cecli") / "app-recipes",
    Path(".agents") / "app-recipes",
)


def recipe_dirs() -> list[Path]:
    """Return the directories searched for external recipes.

    ``CECLI_APP_RECIPES_DIRS`` overrides the search path; it is an
    ``os.pathsep``-separated list, and an empty value disables external
    recipes entirely.
    """

    override = os.environ.get("CECLI_APP_RECIPES_DIRS")

    if override is not None:
        return [Path(part).expanduser() for part in override.split(os.pathsep) if part.strip()]

    local = [Path.cwd() / part for part in PROJECT_RECIPE_DIRS]

    return [*DEFAULT_RECIPE_DIRS, *local]


def iter_recipe_files() -> Iterable[Path]:
    """Yield recipe files in search order."""

    for directory in recipe_dirs():
        if not directory.is_dir():
            continue

        for path in sorted(directory.iterdir()):
            if path.is_file() and path.suffix.casefold() in RECIPE_SUFFIXES:
                yield path


def load_external_recipes() -> dict[str, AppRecipe]:
    """Load every external recipe, skipping files that fail validation."""

    recipes: dict[str, AppRecipe] = {}

    for path in iter_recipe_files():
        try:
            for recipe in load_recipe_file(path):
                recipes[recipe.key] = recipe
        except Exception as exc:
            LOGGER.warning("Skipping app recipe %s: %s", path, exc)

    return recipes


def load_recipe_file(path: Path) -> list[AppRecipe]:
    """Return the recipes defined by one YAML or JSON file."""

    suffix = path.suffix.casefold()

    if suffix in (".yaml", ".yml"):
        payload = _load_yaml(path)
    elif suffix == ".json":
        payload = _load_json(path)
    else:
        raise ValueError(f"unsupported recipe suffix {path.suffix!r}")

    return _to_recipes(payload, path)


def _load_yaml(path: Path) -> Any:
    """Decode one or more YAML documents."""

    documents = [
        document for document in yaml.safe_load_all(path.read_text(encoding="utf-8")) if document
    ]

    if not documents:
        raise ValueError("empty recipe file")

    return documents[0] if len(documents) == 1 else documents


def _load_json(path: Path) -> Any:
    """Decode a JSON recipe file."""

    return json.loads(path.read_text(encoding="utf-8"))


def _to_recipes(payload: Any, path: Path) -> list[AppRecipe]:
    """Coerce a decoded payload into validated recipes."""

    recipes: list[AppRecipe] = []

    for entry in _entries(payload):
        if isinstance(entry, AppRecipe):
            recipes.append(entry)
            continue

        if not isinstance(entry, Mapping):
            raise ValueError("a recipe entry must be a mapping")

        recipes.append(recipe_from_mapping(entry, source=str(path), default_key=path.stem))

    if not recipes:
        raise ValueError("file contains no recipes")

    return recipes


def _entries(payload: Any) -> list[Any]:
    """Return the individual recipe entries in a decoded payload."""

    if isinstance(payload, Mapping) and isinstance(payload.get("recipes"), list):
        return list(payload["recipes"])

    if isinstance(payload, (list, tuple)):
        return list(payload)

    return [payload]
