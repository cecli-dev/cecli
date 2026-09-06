"""Process-wide registry of per-model reasoning/thinking defaults.

The model config pipeline writes a ``{reasoning, thinking}`` entry per model
name so :func:`derive_api_config` and :mod:`cecli.models` agree on the default
effort/budget, even after a user overrides it with ``set_reasoning_effort`` /
``set_thinking_tokens``.
"""

from __future__ import annotations

from typing import Any, Dict

#: Sentinel for "leave this key unchanged" so an explicit ``None`` can be stored.
_UNSET = object()

#: Singleton registry: ``{model_name: {"reasoning": ..., "thinking": ...}}``.
default_registry: Dict[str, Dict[str, Any]] = {}


def register_default(model_name: str, reasoning: Any = _UNSET, thinking: Any = _UNSET) -> None:
    """Record the default reasoning/thinking config for ``model_name``.

    Omitting ``reasoning`` or ``thinking`` leaves that key unchanged; passing an
    explicit ``None`` stores ``None`` so the api derivation falls back to its
    built-in default (``"medium"`` / the provider default budget).
    """
    entry = default_registry.setdefault(model_name, {})

    if reasoning is not _UNSET:
        entry["reasoning"] = reasoning

    if thinking is not _UNSET:
        entry["thinking"] = thinking


def get_default(model_name: str) -> Dict[str, Any]:
    """Return the registered ``{reasoning, thinking}`` defaults for ``model_name``."""
    return default_registry.get(model_name, {})


def clear_default_registry() -> None:
    """Reset the registry (mainly for tests)."""
    default_registry.clear()
