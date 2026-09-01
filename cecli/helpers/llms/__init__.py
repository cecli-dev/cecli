"""LiteLLM-free LLM communication stack for cecli.

The ``cecli.helpers.llms`` package replaces the litellm-backed call path with a
small, lazy-loading dispatcher that mirrors the structure of
``cecli/helpers/model_config/``:

- :mod:`cecli.helpers.llms.config` - provider defaults + model config resolution
- :mod:`cecli.helpers.llms.domains` - one module per API family (chat,
  responses, messages, gemini)
- :mod:`cecli.helpers.llms.providers` - per-provider custom logic (auth,
  headers, response repair) with an extensible :class:`ProviderAdapter` base
- :mod:`cecli.helpers.llms.formatters` - sectional per-domain formatters
  (reasoning, thinking)
- :mod:`cecli.helpers.llms.pipeline` - the ``acompletion()`` dispatcher

Public API: :func:`acompletion`, :func:`resolve_model_config`,
:func:`get_api_key`.
"""

from __future__ import annotations

from .config import get_api_key, resolve_model_config
from .pipeline import acompletion
from .runtime import set_verify_ssl
from .types import CompletionChunk, CompletionResponse, ToolCall

__all__ = [
    "acompletion",
    "resolve_model_config",
    "get_api_key",
    "CompletionResponse",
    "CompletionChunk",
    "ToolCall",
    "set_verify_ssl",
]
