"""Per-provider custom logic for the llms package.

Each provider module subclasses :class:`ProviderAdapter` and is registered in
the ``PROVIDER_REGISTRY`` so the pipeline can dispatch per-provider hooks
(auth, headers, response repair) while the domain adapters stay generic.
"""

from __future__ import annotations

from typing import Dict, Type

from .base import ProviderAdapter

#: Provider slug -> adapter class. Imported lazily to keep startup light
#: (mirrors the LazyLiteLLM deferral in cecli/llm.py).
_PROVIDER_CLASSES: Dict[str, Type[ProviderAdapter]] = {}


def _load_registry() -> Dict[str, Type[ProviderAdapter]]:
    """Populate and return the provider registry (lazy imports)."""
    if _PROVIDER_CLASSES:
        return _PROVIDER_CLASSES

    import importlib
    import pkgutil

    # Auto-discover every provider module (drop a file, it is registered);
    # ``base`` is the abstract base class, not a concrete provider.
    for module_info in pkgutil.iter_modules(__path__):
        if module_info.name == "base":
            continue

        importlib.import_module(f"{__name__}.{module_info.name}")

    for cls in ProviderAdapter.__subclasses__():
        _PROVIDER_CLASSES[cls.provider] = cls

    return _PROVIDER_CLASSES


def get_provider_adapter(provider: str) -> ProviderAdapter:
    """Return the adapter for ``provider`` (base adapter when unregistered)."""
    registry = _load_registry()

    return registry.get(provider, ProviderAdapter)()


__all__ = ["ProviderAdapter", "get_provider_adapter"]
