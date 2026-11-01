"""OpenRouter provider adapter for the llms package.

OpenRouter speaks OpenAI-compatible /v1/chat/completions with Bearer auth, so
the base adapter's defaults apply. It additionally sends the app-attribution
headers OpenRouter uses to rank and list cecli (``HTTP-Referer`` /
``X-OpenRouter-Title`` / ``X-OpenRouter-Categories``). Reasoning arrives via
``message.reasoning`` /
``message.reasoning_details`` (not ``reasoning_content``); the generic
:func:`cecli.helpers.llms.utils.extract_reasoning` already handles all three
shapes, so no normalize override is needed here.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .base import ProviderAdapter

#: App-attribution metadata OpenRouter uses to create/rank the app page.
_APP_URL = "https://cecli.dev"
_APP_TITLE = "cecli"
_APP_CATEGORIES = "cli-agent"


class OpenRouterProvider(ProviderAdapter):
    """OpenRouter: Bearer auth + app attribution + generic reasoning extraction."""

    provider: str = "openrouter"

    def build_headers(
        self,
        resolved: Dict[str, Any],
        key: Optional[str],
        family: str,
        headers: Dict[str, str],
    ) -> Dict[str, str]:
        """Add OpenRouter's app-attribution headers (explicit ones win)."""
        merged = super().build_headers(resolved, key, family, headers)

        merged.setdefault("HTTP-Referer", _APP_URL)
        merged.setdefault("X-OpenRouter-Title", _APP_TITLE)
        merged.setdefault("X-OpenRouter-Categories", _APP_CATEGORIES)

        return merged


__all__ = ["OpenRouterProvider"]
