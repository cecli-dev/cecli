"""Extensible base shape for per-provider custom logic.

Each provider module in :mod:`cecli.helpers.llms.providers` subclasses
:class:`ProviderAdapter` and overrides only the hooks it needs (auth, header
injection, response repair, routing overrides). The default implementations
delegate to the generic family adapters in :mod:`cecli.helpers.llms.domains`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class ProviderAdapter:
    """Base shape for per-provider request/response customization.

    Concrete providers override the hooks they need:

    - :meth:`resolve_api_base` - endpoint selection (e.g. copilot reads the
      authenticated session's ``endpoints.api``).
    - :meth:`resolve_api_key` - key source (env, auth cache, oauth refresh).
    - :meth:`build_headers` - auth scheme + provider-specific headers.
    - :meth:`transform_messages` - transform the outgoing message body to
      normalize fields a stricter provider rejects (e.g. Mistral rejects
      ``reasoning_content`` / ``provider_specific_fields`` and a null tool-call
      ``index``).
    - :meth:`normalize` - post-process a family-normalized response
      (e.g. meta encrypted-reasoning marker).
    """

    #: Provider slug used by the registry (``openai``, ``github_copilot``, ...).
    provider: str = "openai"

    def resolve_api_base(self, resolved: Dict[str, Any]) -> str:
        """Return the api_base for a resolved config (default: as resolved)."""
        return resolved["api_base"]

    def resolve_api_key(self, resolved: Dict[str, Any], api_key: Optional[str]) -> Optional[str]:
        """Return the API key for a resolved config (default: env-based)."""
        from ..config import get_api_key

        return get_api_key(resolved, api_key)

    def build_headers(
        self,
        resolved: Dict[str, Any],
        key: Optional[str],
        family: str,
        headers: Dict[str, str],
    ) -> Dict[str, str]:
        """Return the merged request headers (default: Bearer + content-type)."""
        merged = dict(headers)

        if key:
            merged.setdefault("Authorization", f"Bearer {key}")

        merged.setdefault("Content-Type", "application/json")
        return merged

    def transform_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Transform the outgoing message body to normalize provider-specific fields.

        The default is a no-op. Providers with a stricter request schema override
        this to strip fields the generic OpenAI-compatible wire tolerates but the
        provider rejects (e.g. Mistral rejects ``reasoning_content`` and
        ``provider_specific_fields`` on assistant turns, and a null tool-call
        ``index``).
        """
        return messages

    def normalize(
        self,
        family: str,
        data: Any,
        resolved: Dict[str, Any],
    ) -> Any:
        """Post-process a normalized response (default: no-op)."""
        return data


__all__ = ["ProviderAdapter"]
