"""Discover Python modules available to the creator agent's extensions."""

import sys
from importlib.metadata import distributions, packages_distributions


def installed_modules() -> list:
    """Return top-level importable module names from installed distributions."""
    modules = set()

    try:
        mapping = packages_distributions()
    except Exception:
        mapping = {}

    for module in mapping:
        if module and not module.startswith("_") and not module.endswith("__mypyc"):
            modules.add(module)

    if modules:
        return sorted(modules, key=str.lower)

    # Fallback for environments where top-level module metadata is missing.
    try:
        for distribution in distributions():
            name = distribution.metadata.get("Name")
            if name:
                modules.add(name.replace("-", "_"))
    except Exception:
        return []

    return sorted(modules, key=str.lower)


def packages_context() -> tuple:
    """Return ``(environment label, importable modules)`` or None."""
    modules = installed_modules()
    if not modules:
        return None

    version = sys.version.split()[0]

    return f"Python {version}", modules
