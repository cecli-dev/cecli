"""Meta (Muse Spark) provider adapter for the llms package.

Meta speaks the /v1/responses family with Bearer auth. Its reasoning output is
encrypted (``reasoning.encrypted_content`` with an empty ``summary``); the
responses domain normalizer already marks that as reasoning-present (mirroring
the Anthropic encrypted-thinking handling), so this adapter is registration-only
for now. A future override of :meth:`~ProviderAdapter.normalize` could post-process
the marker without touching the domain.
"""

from __future__ import annotations

from .base import ProviderAdapter


class MetaProvider(ProviderAdapter):
    """Meta: encrypted reasoning handled by the responses domain."""

    provider: str = "meta"


__all__ = ["MetaProvider"]
