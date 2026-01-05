from typing import Any, Dict, List, Union


def arg_resolver(obj: Union[List[Any], Dict[str, Any], Any], key: str, default: Any = None) -> Any:
    """
    Resolves a single key or index from an object with dash/underscore flexibility.
    """
    # 1. Handle List/Sequence access
    if isinstance(obj, (list, tuple)):
        if str(key).isdigit():
            idx = int(key)
            return obj[idx] if idx < len(obj) else default
        return default

    # 2. Handle Dict access
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        # Test underscore and hyphen versions directly
        key_str = str(key)
        # Check underscore version
        if "-" in key_str:
            underscore_key = key_str.replace("-", "_")
            if underscore_key in obj:
                return obj[underscore_key]
        # Check hyphen version
        if "_" in key_str:
            hyphen_key = key_str.replace("_", "-")
            if hyphen_key in obj:
                return obj[hyphen_key]
        return default

    # 3. Handle Object attribute access
    if hasattr(obj, "__dict__") or hasattr(obj, "__slots__"):
        if hasattr(obj, str(key)):
            return getattr(obj, key)
        # Test underscore and hyphen versions directly
        key_str = str(key)
        # Check underscore version
        if "-" in key_str:
            underscore_key = key_str.replace("-", "_")
            if hasattr(obj, underscore_key):
                return getattr(obj, underscore_key)
        # Check hyphen version
        if "_" in key_str:
            hyphen_key = key_str.replace("_", "-")
            if hasattr(obj, hyphen_key):
                return getattr(obj, hyphen_key)
        return default

    return default


def getter(
    data: Union[List[Any], Dict[str, Any], Any], path: Union[str, List[str]], default: Any = None
) -> Any:
    """Safely access nested dicts and lists using normalized dot-notation."""

    if data is None:
        return default

    # Handle single path string
    if isinstance(path, str):
        paths = [path]
    else:
        paths = path

    # Try each path, return first valid result
    for path_str in paths:
        current = data
        parts = path_str.split(".")
        found = True

        for part in parts:
            current = arg_resolver(current, part, default=default)
            if current is default:
                found = False
                break

        if found:
            return current

    return default
