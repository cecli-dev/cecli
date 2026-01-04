"""
Dynamic module loading utilities for cecli.

Provides functions for dynamically loading Python modules from files.
Based on the dynamic loading concepts from:
https://medium.com/@david.bonn.2010/dynamic-loading-of-python-code-2617c04e5f3f
"""

import importlib.util
import re
import secrets
import string
import sys
from pathlib import Path
from typing import Dict

# Cache for loaded modules: maps absolute file path -> module object
module_cache: Dict[str, object] = {}


def gensym(length=32, prefix="gensym_"):
    """
    generates a fairly unique symbol, used to make a module name,
    used as a helper function for load_module

    :return: generated symbol
    """
    alphabet = string.ascii_uppercase + string.ascii_lowercase + string.digits
    symbol = "".join([secrets.choice(alphabet) for i in range(length)])
    return prefix + symbol


def normalize_filename(filename: str) -> str:
    """
    Normalize a filename to be a valid Python module name.

    :param filename: Original filename
    :return: Normalized module name
    """
    # Remove extension
    name = Path(filename).stem

    # Replace non-alphanumeric characters with underscores
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)

    # Ensure it starts with a letter or underscore
    if not name or name[0].isdigit():
        name = "_" + name

    return name.lower()


def load_module(source, module_name=None, reload=False):
    """
    Read a file source and loads it as a module.

    :param source: file to load
    :param module_name: name of module to register in sys.modules
    :return: loaded module
    """
    # Convert to absolute path for cache key
    source_path = Path(source).resolve()

    # Check cache first
    if str(source_path) in module_cache and not reload:
        return module_cache[str(source_path)]

    if module_name is None:
        # Use normalized filename as base, then add unique suffix
        base_name = normalize_filename(source)
        module_name = f"{base_name}_{gensym(8, '')}"

    spec = importlib.util.spec_from_file_location(module_name, source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    # Cache the loaded module
    module_cache[str(source_path)] = module

    return module
