"""acompletion() dispatcher for the llms package.

Resolves a model's config (provider / API family / base / key), then routes to
the family adapter in :mod:`cecli.helpers.llms.domains`, applying per-provider
hooks (auth, headers, response repair) via :mod:`cecli.helpers.llms.providers`.
Returns a :class:`~cecli.helpers.llms.types.CompletionResponse` (non-stream) or
an async iterator of :class:`~cecli.helpers.llms.types.CompletionChunk`
(stream).
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional

from .config import resolve_model_config
from .domains import (
    anthropic_complete,
    anthropic_stream,
    bedrock_complete,
    bedrock_stream,
    chat_complete,
    chat_stream,
    gemini_complete,
    gemini_stream,
    responses_complete,
    responses_stream,
)
from .providers import get_provider_adapter
from .types import CompletionChunk, CompletionResponse


async def acompletion(
    model: str,
    messages: List[Dict[str, Any]],
    stream: bool = False,
    tools: Optional[List[Dict[str, Any]]] = None,
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
    extra_headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Any:
    """Send a chat-style completion through the llm-package-backed dispatcher."""
    resolved = resolve_model_config(model)

    if api_base:
        resolved["api_base"] = api_base.rstrip("/")

    provider = get_provider_adapter(resolved.get("provider") or "openai")
    resolved["api_base"] = provider.resolve_api_base(resolved)
    key = provider.resolve_api_key(resolved, api_key)

    family = resolved["family"]

    # Providers that need to sign the final request (URL + body) expose a
    # ``sign_request`` hook; the family adapter invokes it after building the
    # payload (e.g. Bedrock Mantle's SigV4 path).
    resolved["_signer"] = getattr(provider, "sign_request", None)

    headers = dict(resolved.get("extra_headers") or {})
    headers.update(extra_headers or {})
    headers = provider.build_headers(resolved, key, family, headers)

    if stream:
        gen = _stream_family(family, resolved, messages, tools, key, headers, kwargs)

        return _apply_normalize(gen, provider, family, resolved)

    resp = await _complete_family(family, resolved, messages, tools, key, headers, kwargs)

    return provider.normalize(family, resp, resolved)


async def _complete_family(
    family: str,
    resolved: Dict[str, Any],
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    key: Optional[str],
    headers: Dict[str, str],
    kwargs: Dict[str, Any],
) -> CompletionResponse:
    if family == "responses":
        return await responses_complete(resolved, messages, tools, key, headers, kwargs)

    if family == "messages":
        return await anthropic_complete(resolved, messages, tools, key, headers, kwargs)

    if family == "gemini":
        return await gemini_complete(resolved, messages, tools, key, headers, kwargs)

    if family == "bedrock":
        return await bedrock_complete(resolved, messages, tools, key, headers, kwargs)

    return await chat_complete(resolved, messages, tools, key, headers, kwargs)


async def _stream_family(
    family: str,
    resolved: Dict[str, Any],
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    key: Optional[str],
    headers: Dict[str, str],
    kwargs: Dict[str, Any],
) -> AsyncIterator[CompletionChunk]:
    if family == "responses":
        async for chunk in responses_stream(resolved, messages, tools, key, headers, kwargs):
            yield chunk

        return

    if family == "messages":
        async for chunk in anthropic_stream(resolved, messages, tools, key, headers, kwargs):
            yield chunk

        return

    if family == "gemini":
        async for chunk in gemini_stream(resolved, messages, tools, key, headers, kwargs):
            yield chunk

        return

    if family == "bedrock":
        async for chunk in bedrock_stream(resolved, messages, tools, key, headers, kwargs):
            yield chunk

        return

    async for chunk in chat_stream(resolved, messages, tools, key, headers, kwargs):
        yield chunk


async def _apply_normalize(
    gen: AsyncIterator[CompletionChunk],
    provider: Any,
    family: str,
    resolved: Dict[str, Any],
) -> AsyncIterator[CompletionChunk]:
    """Yield each stream chunk through the provider's ``normalize`` hook."""
    async for chunk in gen:
        yield provider.normalize(family, chunk, resolved)


__all__ = ["acompletion"]
