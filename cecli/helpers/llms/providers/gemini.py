"""Gemini provider adapter for the llms package.

Gemini authenticates via the ``x-goog-api-key`` header, NOT via an
``Authorization: Bearer`` header. The base :class:`ProviderAdapter` adds a
Bearer header whenever a key is present, which Google rejects with 401 for API
keys, so this adapter overrides :meth:`build_headers` to set ``x-goog-api-key``
instead.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .base import ProviderAdapter


class GeminiProvider(ProviderAdapter):
    """Gemini: key via x-goog-api-key header; no Authorization header."""

    provider: str = "gemini"

    def build_headers(
        self,
        resolved: Dict[str, Any],
        key: Optional[str],
        family: str,
        headers: Dict[str, str],
    ) -> Dict[str, str]:
        """Return headers with x-goog-api-key set instead of Authorization."""
        merged = dict(headers)

        merged.setdefault("Content-Type", "application/json")
        if key:
            merged["x-goog-api-key"] = key
        return merged


__all__ = ["GeminiProvider"]
