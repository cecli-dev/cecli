"""Creator helpers for app-harness app recipes."""

from pathlib import Path

import yaml

from cecli.helpers.app_harness.recipes.defaults import DEFAULT_RECIPES
from cecli.helpers.app_harness.recipes.schema import AppRecipe, recipe_from_mapping
from cecli.helpers.creator import config_helpers


def build_app_recipe_fragment(coder, scope_dir, name, config, content) -> tuple:
    """Write a validated YAML app recipe into the scope's app-recipes directory."""

    from cecli.tools.utils.helpers import ToolError

    try:
        file_path = default_file(scope_dir, name)
        payload = _payload(name, config, content)
        recipe = recipe_from_mapping(payload, source=str(file_path), default_key=name)
    except ValueError as exc:
        raise ToolError(f"Invalid app recipe: {exc}") from exc

    config_helpers.write_text(file_path, yaml.safe_dump(_as_mapping(recipe), sort_keys=False))

    notes = [f"App recipe '{recipe.key}' written to {file_path}"]

    if recipe.key in DEFAULT_RECIPES:
        notes.append(f"Overrides the bundled '{recipe.key}' recipe")

    if not recipe.selectors:
        notes.append("Warning: recipe has no selectors; helpers will rely on generic actions")

    if not recipe.sections:
        notes.append("Warning: recipe has no help sections")

    return {}, notes


def remove_entry(data, name) -> bool:
    """App recipes are file-backed, so creator.yml never records them."""

    return False


def default_file(scope_dir, name):
    """Return the YAML file backing an app recipe."""

    safe_name = str(name or "").strip()

    if not safe_name or Path(safe_name).name != safe_name:
        raise ValueError(f"invalid app recipe name {name!r}")

    return Path(scope_dir) / "app-recipes" / f"{safe_name}.yml"


def _payload(name, config, content) -> dict:
    """Return the recipe mapping from ``content`` or ``config``."""

    from cecli.tools.utils.helpers import ToolError

    if content is not None:
        parsed = config_helpers.parse_mapping(content)

        if not isinstance(parsed, dict):
            raise ToolError("app recipe content must be a YAML or JSON mapping")

        return parsed

    if isinstance(config, dict):
        return dict(config)

    raise ToolError("app_recipe requires content or a config mapping")


def _as_mapping(recipe: AppRecipe) -> dict:
    """Return a serializable recipe mapping suitable for YAML."""

    data = {
        "key": recipe.key,
        "display_name": recipe.display_name,
        "process_names": list(recipe.process_names),
        "title_markers": list(recipe.title_markers),
        "aliases": list(recipe.aliases),
        "selectors": dict(recipe.selectors),
        "keys": dict(recipe.keys),
        "sections": {title: list(notes) for title, notes in recipe.sections.items()},
        "gotchas": list(recipe.gotchas),
    }

    if recipe.description:
        data["description"] = recipe.description

    return data


build_fragment = build_app_recipe_fragment
