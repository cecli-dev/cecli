"""Shared HTTP client module selection for cecli.

mcp SDK 2.x migrated from ``httpx`` to ``httpx2`` (a drop-in fork exposing the
same public API). To keep a single HTTP stack loaded and to keep cecli's
``except httpx.*`` handlers compatible with the exceptions raised by the
installed mcp SDK, :data:`httpx` here is the module the mcp SDK itself uses:

- mcp SDK >= 2 -> ``httpx2`` (imported and aliased as ``httpx``)
- mcp SDK < 2 -> ``httpx``

If the mcp version cannot be determined (or ``httpx2`` is not installed), plain
``httpx`` is used.
"""

from __future__ import annotations

import importlib.metadata


def _mcp_major_version() -> int:
    """Return the installed mcp SDK major version (1, 2, ...)."""

    try:
        return int(importlib.metadata.version("mcp").split(".")[0])

    except Exception:
        return 1


def _load_http_client():
    """Select the HTTP client module matching the installed mcp SDK."""

    if _mcp_major_version() >= 2:
        try:
            import httpx2

            return httpx2

        except ImportError:
            pass

    import httpx

    return httpx


#: The HTTP client module used by the installed mcp SDK (``httpx2`` on mcp SDK
#: 2.x, ``httpx`` otherwise). Import it as ``httpx`` so cecli code stays
#: provider-agnostic: ``from cecli.http import httpx``.
httpx = _load_http_client()

__all__ = ["httpx", "_mcp_major_version"]
