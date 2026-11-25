"""Recipe schema, validation, and mapping coercion for app-harness recipes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


class UnknownAppError(ValueError):
    """Raised when an app name or alias is not in the recipe registry."""


@dataclass(frozen=True)
class AppRecipe:
    """Everything the spreadsheet helpers need to drive one application."""

    key: str
    display_name: str
    process_names: tuple[str, ...]
    title_markers: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    selectors: Mapping[str, str] = field(default_factory=dict)
    keys: Mapping[str, str] = field(default_factory=dict)
    sections: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    gotchas: tuple[str, ...] = ()
    description: str = ""
    source: str | None = None

    def selector(self, name: str) -> str | None:
        """Return one named selector, or ``None`` when the app lacks it."""

        return self.selectors.get(name)

    def chord(self, name: str, default: str = "") -> str:
        """Return one named key chord, or ``default`` when the app lacks it."""

        return self.keys.get(name, default)


def recipe_from_mapping(
    data: Any, *, source: str | None = None, default_key: str | None = None
) -> AppRecipe:
    """Build and validate an :class:`AppRecipe` from a decoded mapping."""

    if not isinstance(data, Mapping):
        raise ValueError("a recipe must be a mapping")

    key = _text(data.get("key") or default_key)

    if not key:
        raise ValueError("recipe is missing 'key'")

    process_names = _strings(data.get("process_names") or data.get("processes"))
    title_markers = _strings(data.get("title_markers") or data.get("titles"))

    if not process_names and not title_markers:
        raise ValueError(f"recipe {key!r} must define process_names or title_markers")

    return AppRecipe(
        key=key,
        display_name=_text(data.get("display_name") or data.get("name") or key),
        process_names=process_names,
        title_markers=title_markers,
        aliases=_strings(data.get("aliases")),
        selectors=_string_map(data.get("selectors")),
        keys=_string_map(data.get("keys")),
        sections=_sections(data.get("sections")),
        gotchas=_strings(data.get("gotchas")),
        description=_text(data.get("description")),
        source=source,
    )


def _text(value: Any) -> str:
    """Return a stripped string, or ``""`` for ``None``."""

    return str(value).strip() if value is not None else ""


def _strings(value: Any) -> tuple[str, ...]:
    """Coerce a string or sequence into a tuple of non-empty strings."""

    if value is None:
        return ()

    if isinstance(value, str):
        value = (value,)

    if not isinstance(value, (list, tuple, set)):
        value = (value,)

    return tuple(text for item in value if (text := _text(item)))


def _string_map(value: Any) -> dict[str, str]:
    """Coerce a mapping into a string-to-string mapping."""

    if not isinstance(value, Mapping):
        return {}

    return {str(key): str(item) for key, item in value.items() if item is not None}


def _sections(value: Any) -> dict[str, tuple[str, ...]]:
    """Coerce named help sections into tuples of strings."""

    if not isinstance(value, Mapping):
        return {}

    sections: dict[str, tuple[str, ...]] = {}

    for title, notes in value.items():
        items = _strings(notes)

        if items:
            sections[str(title)] = items

    return sections
