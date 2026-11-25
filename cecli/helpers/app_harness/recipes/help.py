"""Render LLM-readable help text for one recipe or the whole registry."""

from __future__ import annotations

from .registry import get_recipe, list_apps, registry


def help_text(app: str | None = None) -> str:
    """Render an LLM-readable recipe for ``app`` or an overview of all apps."""

    if app is None:
        return _overview_text()

    recipe = get_recipe(app)
    lines = [f"# {recipe.display_name} ({recipe.key})", ""]

    if recipe.description:
        lines.extend([recipe.description, ""])

    lines.append(
        "Detect: process_name in "
        + ", ".join(recipe.process_names)
        + "; title contains "
        + ", ".join(recipe.title_markers)
    )

    if recipe.source:
        lines.append(f"Source: {recipe.source}")

    lines.append("")
    lines.append("Selectors:")

    for name, selector in recipe.selectors.items():
        lines.append(f"- {name}: {selector}")

    lines.append("")
    lines.append("Keys (SendKeys syntax):")

    for name, keys in recipe.keys.items():
        lines.append(f"- {name}: {keys}")

    for title, notes in recipe.sections.items():
        lines.append("")
        lines.append(f"{title}:")
        lines.extend(f"- {note}" for note in notes)

    if recipe.gotchas:
        lines.append("")
        lines.append("Gotchas:")
        lines.extend(f"- {note}" for note in recipe.gotchas)

    return "\n".join(lines)


def _overview_text() -> str:
    """Render the list-of-apps help text."""

    lines = [
        "# Spreadsheet recipes",
        "",
        "Pass an app key, alias, or process name to help_text(app).",
        "",
    ]

    recipes = registry()

    for key in list_apps():
        recipe = recipes[key]
        lines.append(
            f"- {key}: {recipe.display_name} "
            f"(aliases: {', '.join(recipe.aliases) or 'none'}; "
            f"processes: {', '.join(recipe.process_names)})"
        )

    lines.extend(
        [
            "",
            "Common surface: cell read via cell_at, cell write via edit_text or",
            "type_text, goto via the Name Box, range selection by typing A1:C3 into",
            "the Name Box, and bulk writes by pasting tab-separated values with",
            "Ctrl+V. See help_text(app) for selectors and gotchas.",
        ]
    )

    return "\n".join(lines)
