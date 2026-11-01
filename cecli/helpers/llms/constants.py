"""Shared constant values for the llms package.

Only values that more than one module needs live here; single-use constants stay
next to the code that reads them.
"""

from __future__ import annotations

from typing import FrozenSet

#: litellm/cecli runtime kwargs consumed by the shim or the pipeline (routing,
#: auth, timeouts, cache plumbing) that must never be sent as request params.
CONTROL_KWARGS: FrozenSet[str] = frozenset(
    {
        "model",
        "messages",
        "stream",
        "tools",
        "functions",
        "api_base",
        "base_url",
        "api_key",
        "extra_headers",
        "headers",
        "timeout",
        "drop_params",
        "allowed_openai_params",
        "custom_llm_provider",
        "cache_control_injection_points",
        "logger_fn",
    }
)

__all__ = ["CONTROL_KWARGS"]
