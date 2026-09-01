"""Azure OpenAI provider adapter.

Azure OpenAI speaks the OpenAI-compatible wire but authenticates with an
``api-key`` header (not ``Authorization: Bearer``) and requires an
``api-version`` query param on every request. The api-version rides in the
provider config's ``extra_query`` (surfaced by ``resolve_model_config``) and is
appended by the chat domain; the api-key header is applied here.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from .base import ProviderAdapter


class AzureProvider(ProviderAdapter):
    """Azure OpenAI: api-key header + api-version query param."""

    provider: str = "azure"

    def resolve_api_key(self, resolved: Dict[str, Any], api_key: Optional[str]) -> Optional[str]:
        """Return the Azure API key (AZURE_API_KEY first, then AZURE_OPENAI_API_KEY)."""
        if api_key:
            return api_key

        return os.environ.get("AZURE_API_KEY") or os.environ.get("AZURE_OPENAI_API_KEY")

    def build_headers(
        self,
        resolved: Dict[str, Any],
        key: Optional[str],
        family: str,
        headers: Dict[str, str],
    ) -> Dict[str, str]:
        """Authenticate with the ``api-key`` header instead of Bearer."""
        merged = dict(headers)

        if key:
            merged["api-key"] = key

        merged.setdefault("Content-Type", "application/json")
        return merged


__all__ = ["AzureProvider"]
