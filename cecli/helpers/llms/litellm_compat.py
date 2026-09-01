"""LiteLLM-shaped compat facade backed by the litellm-free ``cecli.helpers.llms`` dispatcher.

cecli historically routed every model request through ``litellm.acompletion`` and
consumed litellm's response objects (``ModelResponse``, streaming chunks,
``types.utils`` tool-call types, the ``litellm.*Error`` exception taxonomy,
``model_cost``, ``encode``/``token_counter``, ``validate_environment`` and
``transcription``).

This module replaces that dependency with a thin, lazily-loaded facade that
keeps the same public attribute surface while delegating the actual HTTP work
to :mod:`cecli.helpers.llms` (a ~35 MB import footprint vs litellm's ~205 MB).

The shims below are intentionally **mutable dataclasses**: cecli's callers
reassign fields in place (``response.usage = ...``, ``message.tool_calls = ...``,
``chunk._hidden_params["created_at"] = ...``).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import warnings
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from cecli.dump import dump  # noqa: F401
from cecli.http import httpx

warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

SITE_URL = "https://cecli.dev"
APP_NAME = "cecli"

os.environ["OR_SITE_URL"] = SITE_URL
os.environ["OR_APP_NAME"] = APP_NAME


# ---------------------------------------------------------------------------
# Litellm-shaped response shims (mutable dataclasses)
# ---------------------------------------------------------------------------


@dataclass
class Function:
    """Tool-call function payload (litellm ``types.utils.Function`` shape)."""

    name: Optional[str] = None
    arguments: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to the wire-format function dict."""
        return {"name": self.name, "arguments": self.arguments}


@dataclass
class ChatCompletionMessageToolCall:
    """A tool call attached to a message or a stream delta."""

    id: Optional[str] = None
    type: Optional[str] = "function"
    function: Optional[Function] = None
    index: Optional[int] = None
    provider_specific_fields: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        if isinstance(self.function, dict):
            self.function = _coerce_function(self.function)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to the wire-format tool-call dict (id/type/index/function)."""
        return _tool_call_to_dict(self)


@dataclass
class Message:
    role: str = "assistant"
    content: Optional[str] = None
    tool_calls: List[ChatCompletionMessageToolCall] = field(default_factory=list)
    function_call: Optional[Dict[str, Any]] = None
    reasoning_content: Optional[str] = None
    reasoning: Optional[str] = None
    reasoning_redacted: bool = False
    provider_specific_fields: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.tool_calls = [_coerce_tool_call(tc) for tc in self.tool_calls or []]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to the wire-format message dict."""
        return _message_to_dict(self)


@dataclass
class Choices:
    index: int = 0
    message: Optional[Message] = None
    finish_reason: Optional[str] = None

    def __post_init__(self) -> None:
        if isinstance(self.message, dict):
            self.message = _coerce_message(self.message)


@dataclass
class Usage:
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    # Provider cache/usage details preserved for token & cost logging.
    prompt_cache_hit_tokens: Optional[int] = None
    cache_read_input_tokens: Optional[int] = None
    cache_creation_input_tokens: Optional[int] = None
    prompt_tokens_details: Optional[Dict[str, Any]] = None
    completion_tokens_details: Optional[Dict[str, Any]] = None


@dataclass
class Delta:
    role: Optional[str] = None
    content: Optional[str] = None
    tool_calls: List[ChatCompletionMessageToolCall] = field(default_factory=list)
    function_call: Optional[Dict[str, Any]] = None
    reasoning_content: Optional[str] = None
    reasoning: Optional[str] = None
    provider_specific_fields: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamChoice:
    index: int = 0
    delta: Optional[Delta] = None
    finish_reason: Optional[str] = None


@dataclass
class StreamChunk:
    id: Optional[str] = None
    model: Optional[str] = None
    choices: List[StreamChoice] = field(default_factory=list)
    usage: Optional[Usage] = None
    created: Optional[int] = None
    _hidden_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelResponse:
    id: Optional[str] = None
    model: Optional[str] = None
    object: Optional[str] = None
    system_fingerprint: Optional[Any] = None
    choices: List[Choices] = field(default_factory=list)
    usage: Optional[Usage] = None
    created: Optional[int] = None
    _hidden_params: Dict[str, Any] = field(default_factory=dict)
    provider_specific_fields: Dict[str, Any] = field(default_factory=dict)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Dataclass init tolerant of unknown keys + raw dict coercion.

        litellm responses are pydantic models that accept a wide range of keys
        (``object``, ``system_fingerprint``, provider-specific extras). Tests
        and cecli callers construct ``ModelResponse(**raw_dict)``, so unknown
        keys are stashed in ``_extra`` instead of raising and nested raw dicts
        are converted into their shim classes.
        """
        field_names = [
            "id",
            "model",
            "object",
            "system_fingerprint",
            "choices",
            "usage",
            "created",
            "_hidden_params",
            "provider_specific_fields",
        ]
        for name, value in zip(field_names, args):
            kwargs.setdefault(name, value)

        self.id = kwargs.pop("id", None)
        self.model = kwargs.pop("model", None)
        self.object = kwargs.pop("object", None)
        self.system_fingerprint = kwargs.pop("system_fingerprint", None)
        self.choices = kwargs.pop("choices", [])
        self.usage = kwargs.pop("usage", None)
        self.created = kwargs.pop("created", None)
        self._hidden_params = kwargs.pop("_hidden_params", {})
        self.provider_specific_fields = kwargs.pop("provider_specific_fields", {})
        self._extra = kwargs

        self.choices = [_coerce_choice(c) for c in self.choices or []]
        if isinstance(self.usage, dict):
            self.usage = _coerce_usage(self.usage)

    def model_dump(self) -> Dict[str, Any]:
        """Pydantic-style dump consumed by ``base_coder`` consolidation."""
        return {
            "id": self.id,
            "model": self.model,
            "created": self.created,
            "choices": [_choice_to_dict(c) for c in self.choices],
            "usage": _usage_to_dict(self.usage),
        }


# ---------------------------------------------------------------------------
# Serialization helpers (model_dump shape)
# ---------------------------------------------------------------------------


def _choice_to_dict(choice: Choices) -> Dict[str, Any]:
    return {
        "index": choice.index,
        "finish_reason": choice.finish_reason,
        "message": _message_to_dict(choice.message) if choice.message else None,
    }


def _message_to_dict(message: Message) -> Dict[str, Any]:
    res = {
        "role": message.role,
        "content": message.content,
        "tool_calls": [_tool_call_to_dict(tc) for tc in message.tool_calls] or None,
        "function_call": _function_to_dict(message.function_call),
        "reasoning_content": message.reasoning_content,
        "provider_specific_fields": message.provider_specific_fields,
    }

    if getattr(message, "reasoning_redacted", None):
        res["reasoning_redacted"] = message.reasoning_redacted

    return res


def _tool_call_to_dict(tc: ChatCompletionMessageToolCall) -> Dict[str, Any]:
    function = tc.function
    return {
        "id": tc.id,
        "type": tc.type,
        "index": tc.index,
        "function": {
            "name": function.name if function else None,
            "arguments": function.arguments if function else "",
        },
        "provider_specific_fields": tc.provider_specific_fields,
    }


def _function_to_dict(fn: Optional[Function]) -> Optional[Dict[str, Any]]:
    """Serialize a Function shim to its wire-format dict."""
    if not fn:
        return None

    return {"name": fn.name, "arguments": fn.arguments}


def _usage_to_dict(usage: Optional[Usage]) -> Optional[Dict[str, Any]]:
    if not usage:
        return None
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
        "prompt_cache_hit_tokens": getattr(usage, "prompt_cache_hit_tokens", None),
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
        "prompt_tokens_details": getattr(usage, "prompt_tokens_details", None),
        "completion_tokens_details": getattr(usage, "completion_tokens_details", None),
    }


def _coerce_choice(value: Any) -> Any:
    """Convert a raw choice dict (or pass through a Choices object)."""
    if isinstance(value, Choices):
        return value
    if isinstance(value, dict):
        return Choices(
            index=value.get("index", 0),
            message=value.get("message"),
            finish_reason=value.get("finish_reason"),
        )
    return value


def _coerce_message(value: Any) -> Any:
    """Convert a raw message dict (or pass through a Message object)."""
    if isinstance(value, Message):
        return value
    if isinstance(value, dict):
        reasoning = value.get("reasoning_content") or value.get("reasoning")
        return Message(
            role=value.get("role", "assistant"),
            content=value.get("content"),
            tool_calls=value.get("tool_calls") or [],
            function_call=value.get("function_call"),
            reasoning_content=reasoning,
            reasoning=reasoning,
            reasoning_redacted=value.get("reasoning_redacted", False),
            provider_specific_fields=value.get("provider_specific_fields") or {},
        )
    return value


def _coerce_tool_call(value: Any) -> Any:
    """Convert a raw tool-call dict (or pass through a tool-call object)."""
    if isinstance(value, ChatCompletionMessageToolCall):
        return value
    if isinstance(value, dict):
        return ChatCompletionMessageToolCall(
            id=value.get("id"),
            type=value.get("type", "function"),
            function=value.get("function"),
            index=value.get("index"),
            provider_specific_fields=value.get("provider_specific_fields"),
        )
    return value


def _coerce_function(value: Any) -> Any:
    """Convert a raw function dict (or pass through a Function object)."""
    if isinstance(value, Function):
        return value
    if isinstance(value, dict):
        return Function(
            name=value.get("name"),
            arguments=value.get("arguments") or "",
        )
    return value


def _coerce_usage(value: Any) -> Optional[Usage]:
    """Convert a raw usage dict (or pass through a Usage object)."""
    if isinstance(value, Usage):
        return value
    if isinstance(value, dict):
        return Usage(
            prompt_tokens=value.get("prompt_tokens"),
            completion_tokens=value.get("completion_tokens"),
            total_tokens=value.get("total_tokens"),
            prompt_cache_hit_tokens=value.get("prompt_cache_hit_tokens"),
            cache_read_input_tokens=value.get("cache_read_input_tokens"),
            cache_creation_input_tokens=value.get("cache_creation_input_tokens"),
            prompt_tokens_details=value.get("prompt_tokens_details"),
            completion_tokens_details=value.get("completion_tokens_details"),
        )
    return value


# ---------------------------------------------------------------------------
# Litellm-shaped exceptions
# ---------------------------------------------------------------------------

#: Names exposed on the facade as ``litellm.<Name>``. Must match the EXCEPTIONS
#: list in ``cecli/exceptions.py`` exactly (the strict check iterates
#: ``dir(litellm)`` for every name ending in "Error").
_EXCEPTION_NAMES = [
    "APIConnectionError",
    "APIError",
    "APIResponseValidationError",
    "AuthenticationError",
    "AzureOpenAIError",
    "BadGatewayError",
    "BadRequestError",
    "BudgetExceededError",
    "ContentPolicyViolationError",
    "ContextWindowExceededError",
    "ErrorEventError",
    "ImageFetchError",
    "InternalServerError",
    "InvalidRequestError",
    "JSONSchemaValidationError",
    "NotFoundError",
    "OpenAIError",
    "PermissionDeniedError",
    "RateLimitError",
    "RouterRateLimitError",
    "ServiceUnavailableError",
    "UnprocessableEntityError",
    "UnsupportedParamsError",
    "Timeout",
]


class _FacadeException(Exception):
    """Base class for litellm-shaped exceptions raised by the facade."""

    def __init__(
        self,
        message: Optional[str] = None,
        status_code: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message or "")
        self.status_code = status_code
        for k, v in kwargs.items():
            setattr(self, k, v)


class APIConnectionError(_FacadeException):
    pass


class APIError(_FacadeException):
    pass


class APIResponseValidationError(_FacadeException):
    pass


class AuthenticationError(_FacadeException):
    pass


class AzureOpenAIError(_FacadeException):
    pass


class BadGatewayError(_FacadeException):
    pass


class BadRequestError(_FacadeException):
    pass


class BudgetExceededError(_FacadeException):
    pass


class ContentPolicyViolationError(_FacadeException):
    pass


class ContextWindowExceededError(_FacadeException):
    pass


class ErrorEventError(_FacadeException):
    pass


class ImageFetchError(_FacadeException):
    pass


class InternalServerError(_FacadeException):
    pass


class InvalidRequestError(_FacadeException):
    pass


class JSONSchemaValidationError(_FacadeException):
    pass


class NotFoundError(_FacadeException):
    pass


class OpenAIError(_FacadeException):
    pass


class PermissionDeniedError(_FacadeException):
    pass


class RateLimitError(_FacadeException):
    pass


class RouterRateLimitError(_FacadeException):
    pass


class ServiceUnavailableError(_FacadeException):
    pass


class UnprocessableEntityError(_FacadeException):
    pass


class UnsupportedParamsError(_FacadeException):
    pass


class Timeout(_FacadeException):
    pass


def _translate_http_error(err: httpx.HTTPStatusError) -> _FacadeException:
    """Map an httpx status error to a litellm-shaped facade exception."""
    status = err.response.status_code

    # Streaming responses are not consumed; .text raises ResponseNotRead.
    try:
        text = err.response.text or ""
    except Exception:
        text = ""
    body = text.lower()
    message = text or str(err)

    if status == 400 and any(
        token in body for token in ("context", "context_length", "maximum context")
    ):
        return ContextWindowExceededError(
            message=message, status_code=status, response=err.response
        )

    if status in (401, 403):
        return AuthenticationError(message=message, status_code=status, response=err.response)

    if status == 404:
        return NotFoundError(message=message, status_code=status, response=err.response)

    if status == 429:
        return RateLimitError(message=message, status_code=status, response=err.response)

    if status >= 500:
        return InternalServerError(message=message, status_code=status, response=err.response)

    return APIError(message=message, status_code=status, response=err.response)


# ---------------------------------------------------------------------------
# Package -> shim translation helpers
# ---------------------------------------------------------------------------


def _tool_call_from_pkg(index: int, tc: Any) -> ChatCompletionMessageToolCall:
    """Convert a ``cecli.helpers.llms.ToolCall`` into a litellm-shaped tool call.

    Streaming tool calls arrive with ``arguments`` set to a ``{"_fragment":
    <partial_json>}`` marker (see the domain stream parsers in ``domains/``).
    The fragment text must flow through ``Function.arguments`` raw so the
    downstream concatenation (``base_coder._build_tool_calls_from_chunks`` and
    the facade ``stream_chunk_builder``) can reassemble it into valid JSON.
    Empty fragments stay empty so the joiners skip them.

    When the domain also attaches ``arguments["_index"]`` (the provider's
    original per-SSE-event tool-call index, see the anthropic stream parser),
    that index is used for the shim instead of the enumerate position so
    parallel tool calls do not collapse onto index 0.
    """
    arguments = tc.arguments
    tool_index = index
    if isinstance(arguments, dict) and isinstance(arguments.get("_index"), int):
        tool_index = arguments["_index"]
    if isinstance(arguments, dict) and "_fragment" in arguments:
        arguments_str = arguments["_fragment"] or ""
    else:
        arguments_str = json.dumps(arguments) if arguments else "{}"
    return ChatCompletionMessageToolCall(
        id=tc.id,
        type="function",
        index=tool_index,
        function=Function(
            name=tc.name,
            arguments=arguments_str,
        ),
    )


def _usage_from_pkg(usage: Any) -> Optional[Usage]:
    if not usage:
        return None
    return Usage(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        prompt_cache_hit_tokens=getattr(usage, "prompt_cache_hit_tokens", None),
        cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", None),
        cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", None),
        prompt_tokens_details=getattr(usage, "prompt_tokens_details", None),
        completion_tokens_details=getattr(usage, "completion_tokens_details", None),
    )


def _response_shim(resp: Any, model: Optional[str] = None) -> ModelResponse:
    """Convert a package ``CompletionResponse`` into a litellm-shaped response."""
    finish_reason = resp.choices[0].finish_reason if resp.choices else None
    pkg_message = resp.choices[0].message if resp.choices else None
    message = Message(
        role="assistant",
        content=resp.text or None,
        reasoning_content=resp.reasoning or None,
        reasoning_redacted=bool(getattr(pkg_message, "reasoning_redacted", False)),
        provider_specific_fields=dict(resp.provider_specific_fields or {}),
    )
    message.tool_calls = [_tool_call_from_pkg(i, tc) for i, tc in enumerate(resp.tool_calls or [])]
    return ModelResponse(
        id=resp.id,
        model=resp.model or model,
        choices=[Choices(index=0, message=message, finish_reason=finish_reason)],
        usage=_usage_from_pkg(resp.usage),
        created=0,
    )


def _chunk_shim(chunk: Any, model: Optional[str] = None) -> StreamChunk:
    """Convert a package ``CompletionChunk`` into a litellm-shaped stream chunk."""
    delta = Delta(
        content=chunk.text or None,
        reasoning_content=chunk.reasoning or None,
    )
    # Honor a per-tool-call ``index`` (gemini parallel functionCall parts) and
    # fall back to the enumerate position for fragmented providers.
    delta.tool_calls = [
        _tool_call_from_pkg(
            getattr(tc, "index", None) if getattr(tc, "index", None) is not None else i,
            tc,
        )
        for i, tc in enumerate(chunk.tool_calls or [])
    ]
    # Forward provider round-trip metadata (Anthropic thinking blocks, OpenAI
    # Responses reasoning items, ...) onto the delta so
    # ``base_coder.consolidate_chunks`` persists it on the stored assistant
    # message for the next stateless turn.
    chunk_psf = getattr(chunk, "provider_specific_fields", None)
    if chunk_psf:
        delta.provider_specific_fields = dict(chunk_psf)
    return StreamChunk(
        model=model,
        choices=[StreamChoice(index=0, delta=delta, finish_reason=chunk.finish_reason)],
        usage=_usage_from_pkg(chunk.usage),
        created=0,
    )


def _accumulate_tool_call(
    tool_calls_dict: Dict[Any, Dict[str, Any]],
    tc: Optional[ChatCompletionMessageToolCall],
    state: Optional[Dict[str, Any]] = None,
) -> None:
    """Merge one delta tool-call into a keyed accumulation dict.

    Parallel tool calls are keyed by their ``id`` when the provider supplies one
    (OpenAI / Responses style), falling back to the delta ``index`` for providers
    that only increment a per-event index (anthropic / gemini).  Some providers
    (e.g. deepseek) reuse index0 across parallel calls and only distinguish them
    by the id announced on the first fragment, so the index -> key mapping in
    ``state`` lets later id-less fragments resolve to the right bucket instead of
    collapsing onto one call.
    """
    if tc is None:
        return

    function = tc.function
    if function is None:
        return

    if state is None:
        state = {}

    index_lookup = state.setdefault("index_lookup", {})
    last_key = state.get("last_key")
    index = tc.index

    if tc.id:
        key = ("id", tc.id)

        if index is not None:
            index_lookup[index] = key

        state["last_key"] = key
    elif index is not None and index in index_lookup:
        key = index_lookup[index]
    elif index is not None:
        key = ("index", index)
        index_lookup[index] = key
    elif last_key is not None:
        key = last_key
    else:
        key = ("slot", len(tool_calls_dict))

    entry = tool_calls_dict.setdefault(
        key,
        {
            "id": None,
            "name": None,
            "type": "function",
            "arguments": [],
            "provider_specific_fields": {},
            "_order": len(tool_calls_dict),
        },
    )
    entry["id"] = tc.id or entry["id"]
    entry["type"] = tc.type or entry["type"]
    entry["name"] = function.name or entry["name"]
    if function.arguments:
        entry["arguments"].append(function.arguments)

    psf = tc.provider_specific_fields
    if not psf:
        psf = getattr(function, "provider_specific_fields", None)
    if psf and isinstance(psf, dict):
        entry["provider_specific_fields"].update(psf)


def _finalize_tool_calls(
    tool_calls_dict: Dict[Any, Dict[str, Any]],
) -> List[ChatCompletionMessageToolCall]:
    """Build final tool-call shims from a keyed accumulation dict.

    Entries are ordered by first appearance (``_order``) so parallel calls keep
    the stream order even when their keys are ids rather than indices.
    """
    tool_calls: List[ChatCompletionMessageToolCall] = []
    for key in sorted(tool_calls_dict.keys(), key=lambda k: tool_calls_dict[k]["_order"]):
        data = tool_calls_dict[key]
        if not (data["id"] and data["name"]):
            continue
        function = Function(arguments="".join(data["arguments"]) or "{}", name=data["name"])
        params: Dict[str, Any] = {
            "id": data["id"],
            "function": function,
            "type": data["type"] or "function",
        }
        if data["provider_specific_fields"]:
            params["provider_specific_fields"] = data["provider_specific_fields"]
        tool_calls.append(ChatCompletionMessageToolCall(**params))
    return tool_calls


# ---------------------------------------------------------------------------
# The facade implementation
# ---------------------------------------------------------------------------


class _LiteLLMFacade:
    """Lazily-built implementation object behind :class:`LazyLiteLLM`.

    Holds litellm-compatible settings/attributes and the translation methods
    that delegate the actual HTTP work to :mod:`cecli.helpers.llms`.
    """

    #: litellm-compatible settings (accepted; most are no-ops after the swap).
    drop_params = True
    disable_streaming_logging = True
    suppress_debug_info = True
    set_verbose = False

    def __init__(self) -> None:
        self.model_cost: Dict[str, Dict[str, Any]] = {}
        self.utils = SimpleNamespace(_invalidate_model_cost_lowercase_map=lambda: None)
        self.types = SimpleNamespace(
            utils=SimpleNamespace(
                ModelResponse=ModelResponse,
                Choices=Choices,
                Message=Message,
                ChatCompletionMessageToolCall=ChatCompletionMessageToolCall,
                Function=Function,
                Delta=Delta,
            )
        )
        for name in _EXCEPTION_NAMES:
            setattr(self, name, globals()[name])

        # Top-level litellm-shaped classes (``litellm.ModelResponse`` etc.).
        for name in (
            "ModelResponse",
            "Choices",
            "Message",
            "Function",
            "ChatCompletionMessageToolCall",
            "Usage",
            "Delta",
            "StreamChoice",
            "StreamChunk",
        ):
            setattr(self, name, globals()[name])

    # -- completions ------------------------------------------------------

    async def acompletion(self, **kwargs: Any) -> Any:
        """Send a completion through ``cecli.helpers.llms.acompletion``.

        Returns a litellm-shaped :class:`ModelResponse` (non-stream) or an
        async generator of :class:`StreamChunk` (stream).
        """
        from cecli.helpers.llms import acompletion as dispatch

        model = kwargs.get("model")
        messages = kwargs.get("messages", [])
        stream = kwargs.get("stream", False)
        tools = kwargs.get("tools")
        api_base = kwargs.get("api_base")
        api_key = kwargs.get("api_key")

        extra_headers = dict(kwargs.get("extra_headers") or {})
        headers = kwargs.get("headers")
        if headers:
            extra_headers = {**headers, **extra_headers}

        passthrough: Dict[str, Any] = {}
        for key in (
            "temperature",
            "tool_choice",
            "extra_body",
            "prompt_cache_key",
            "stream_options",
        ):
            if kwargs.get(key) is not None:
                passthrough[key] = kwargs[key]

        # The model-config pipeline formatters (helpers.format_reasoning /
        # helpers.format_thinking) lift reasoning_effort/thinking OUT of
        # extra_body into top-level kwargs (models.py set_reasoning_effort /
        # set_thinking_tokens). Forward them on the same extra_body channel the
        # domain payload builders consume; a top-level value wins over an
        # extra_body copy (it is the post-format value).
        extra_body = dict(kwargs.get("extra_body") or {})

        for key in ("reasoning_effort", "thinking"):
            if kwargs.get(key) is not None:
                extra_body[key] = kwargs[key]

        if extra_body:
            passthrough["extra_body"] = extra_body

        max_tokens = kwargs.get("max_tokens") or kwargs.get("max_completion_tokens")
        if max_tokens:
            passthrough["max_tokens"] = max_tokens

        if stream:
            gen = await dispatch(
                model=model,
                messages=messages,
                stream=True,
                tools=tools,
                api_base=api_base,
                api_key=api_key,
                extra_headers=extra_headers,
                **passthrough,
            )
            return self._stream_with_errors(gen, model)

        try:
            resp = await dispatch(
                model=model,
                messages=messages,
                stream=False,
                tools=tools,
                api_base=api_base,
                api_key=api_key,
                extra_headers=extra_headers,
                **passthrough,
            )
        except httpx.TimeoutException as err:
            raise Timeout(str(err)) from err
        except httpx.HTTPStatusError as err:
            raise _translate_http_error(err) from err
        except httpx.HTTPError as err:
            raise APIConnectionError(str(err)) from err

        return _response_shim(resp, model)

    def completion(self, **kwargs: Any) -> Any:
        """Synchronous variant of :meth:`acompletion` (runs a fresh loop)."""
        return asyncio.run(self.acompletion(**kwargs))

    async def _stream_with_errors(self, gen: Any, model: Optional[str]) -> Any:
        """Wrap a package stream generator, translating httpx errors."""
        try:
            async for chunk in gen:
                yield _chunk_shim(chunk, model)
        except httpx.TimeoutException as err:
            raise Timeout(str(err)) from err
        except httpx.HTTPStatusError as err:
            raise _translate_http_error(err) from err
        except httpx.HTTPError as err:
            raise APIConnectionError(str(err)) from err

    def stream_chunk_builder(
        self, chunks: List[Any], messages: Optional[Any] = None, **kwargs: Any
    ) -> ModelResponse:
        """Reassemble streaming chunks into a single litellm-shaped response.

        Mirrors ``litellm.stream_chunk_builder``: text/reasoning are joined,
        tool calls are accumulated per call id (falling back to delta index), and finish_reason/usage
        come from the last chunk that carried them.
        """
        content_parts: List[str] = []
        reasoning_parts: List[str] = []
        tool_calls_dict: Dict[Any, Dict[str, Any]] = {}
        tool_state: Dict[str, Any] = {}
        finish_reason: Optional[str] = None
        usage: Optional[Usage] = None
        response_id: Optional[str] = None
        model: Optional[str] = None
        message_psf: Dict[str, Any] = {}

        for chunk in chunks or []:
            if chunk is None:
                continue

            if getattr(chunk, "usage", None) is not None:
                usage = _usage_from_pkg(chunk.usage)

            if not getattr(chunk, "choices", None):
                continue

            choice = chunk.choices[0]
            if getattr(choice, "finish_reason", None):
                finish_reason = choice.finish_reason

            if getattr(chunk, "id", None) and response_id is None:
                response_id = chunk.id
            if getattr(chunk, "model", None):
                model = chunk.model

            delta = getattr(choice, "delta", None)
            if delta is None:
                # Non-stream chunk (e.g. model_error_response): carry its message.
                message = getattr(choice, "message", None)
                if message is not None:
                    if getattr(message, "content", None):
                        content_parts.append(message.content)
                    reasoning_msg = getattr(message, "reasoning_content", None) or getattr(
                        message, "reasoning", None
                    )
                    if reasoning_msg:
                        reasoning_parts.append(reasoning_msg)
                    for tc in getattr(message, "tool_calls", None) or []:
                        _accumulate_tool_call(tool_calls_dict, tc, tool_state)
                continue

            if getattr(delta, "content", None):
                content_parts.append(delta.content)
            reasoning_delta = getattr(delta, "reasoning_content", None) or getattr(
                delta, "reasoning", None
            )
            if reasoning_delta:
                reasoning_parts.append(reasoning_delta)
            for tc in getattr(delta, "tool_calls", None) or []:
                _accumulate_tool_call(tool_calls_dict, tc, tool_state)

            delta_psf = getattr(delta, "provider_specific_fields", None)
            if delta_psf:
                for key, value in delta_psf.items():
                    if (
                        key in message_psf
                        and isinstance(message_psf[key], list)
                        and isinstance(value, list)
                    ):
                        message_psf[key].extend(value)
                    elif (
                        key in message_psf
                        and isinstance(message_psf[key], dict)
                        and isinstance(value, dict)
                    ):
                        # Merge dict-valued metadata (e.g. gemini per-call
                        # function_call_signatures) so parallel tool calls each
                        # keep their own signature across chunks.
                        message_psf[key].update(value)
                    else:
                        # Copy list values so the source chunk's delta is never
                        # mutated in place (aliasing it here corrupts the chunk
                        # stream and double-counts on any second aggregation).
                        message_psf[key] = list(value) if isinstance(value, list) else value

        message = Message(
            role="assistant",
            content="".join(content_parts) or None,
            tool_calls=_finalize_tool_calls(tool_calls_dict),
            reasoning_content="".join(reasoning_parts) or None,
            provider_specific_fields=message_psf,
        )
        return ModelResponse(
            id=response_id,
            model=model,
            choices=[Choices(index=0, message=message, finish_reason=finish_reason)],
            usage=usage,
            created=0,
        )

    def completion_cost(self, completion_response: Optional[Any] = None, **kwargs: Any) -> float:
        """Estimate cost from usage tokens and cecli's own model metadata.

        Mirrors ``base_coder.compute_costs_from_tokens`` so normalized usage
        (``prompt_tokens`` = full input including cache read/write) is billed
        with the cache discounts instead of the plain input price.
        """
        usage = getattr(completion_response, "usage", None)
        if not usage:
            return 0.0

        model = getattr(completion_response, "model", None) or kwargs.get("model")
        info = self.get_model_info(model) if model else {}
        input_cost = info.get("input_cost_per_token") or 0.0
        output_cost = info.get("output_cost_per_token") or 0.0
        cache_hit_cost = (
            info.get("input_cost_per_token_cache_hit")
            or info.get("cache_read_input_token_cost")
            or 0.0
        )
        prompt = usage.prompt_tokens or 0
        completion = usage.completion_tokens or 0
        cache_hit = (
            getattr(usage, "cache_read_input_tokens", None)
            or getattr(usage, "prompt_cache_hit_tokens", None)
            or 0
        )
        cache_write = getattr(usage, "cache_creation_input_tokens", None) or 0

        if cache_hit_cost:
            return (
                cache_hit * cache_hit_cost
                + (prompt - cache_hit) * input_cost
                + completion * output_cost
            )

        if cache_hit or cache_write:
            # Hard-coded Anthropic adjustments, no-ops for other providers
            # since their cache fields are zero.
            return (
                cache_write * input_cost * 1.25
                + cache_hit * input_cost * 0.10
                + (prompt - cache_hit) * input_cost
                + completion * output_cost
            )

        return prompt * input_cost + completion * output_cost

    # -- model metadata ---------------------------------------------------

    def get_model_info(self, model: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
        """Resolve model cost/context metadata from cecli's provider manager.

        The generic llm block (mode, ``supports_*`` flags, ...) is merged into
        ``Model.info`` by ``Model.__init__`` from the config pipeline, so this
        facade only contributes provider-managed info (costs, context windows).
        Returns ``{}`` for unknown models, matching the litellm fallback
        contract that ``ModelInfoManager.get_model_info`` relies on.
        """
        from cecli.helpers.model_providers import ModelProviderManager

        info: Dict[str, Any] = {}
        if not model:
            return info

        try:
            provider_info = ModelProviderManager().get_model_info(model) or {}
            info.update({k: v for k, v in provider_info.items() if v is not None})
        except Exception:
            pass

        return info

    def model_cost_items(self) -> List[Any]:
        """Return the accumulated model-cost entries (cecli's own metadata)."""
        return list(self.model_cost.items())

    # -- token helpers ----------------------------------------------------

    def encode(
        self, model: Optional[str] = None, text: Optional[str] = None, **kwargs: Any
    ) -> range:
        """Estimate tokens for ``text`` without loading a BPE tokenizer.

        tiktoken's cl100k_base/o200k_base encodings cost ~30-95MB of RSS the
        first time they are loaded, so we approximate instead: roughly one token
        per four ASCII characters (the classic rule of thumb), plus one token per
        non-ASCII character (CJK/emoji tokenize at about one token per char), and
        never fewer tokens than there are whitespace-delimited word/punctuation
        runs (dense code with short tokens is otherwise undercounted).

        The estimate lands within ~±30% of cl100k_base on code and prose, which
        is plenty for context-window checks, cost display, and file-size
        warnings.

        Returns a ``range`` whose length is the estimated token count; the
        individual values are dummy ids (callers only use ``len()``/iteration).
        """

        n = _estimate_token_count(text or "")

        return range(n)

    def token_counter(
        self, model: Optional[str] = None, messages: Optional[Any] = None, **kwargs: Any
    ) -> int:
        """Count tokens in a list of chat messages (or a single message dict)."""
        if isinstance(messages, dict):
            messages = [messages]

        total = 0
        for msg in messages or []:
            if isinstance(msg, dict):
                content = msg.get("content")
            else:
                content = getattr(msg, "content", None)

            if isinstance(content, str):
                total += len(self.encode(model=model, text=content))
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        total += len(self.encode(model=model, text=part["text"]))

        return total

    # -- environment validation --------------------------------------------

    def validate_environment(self, model: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
        """Return ``{keys_in_environment, missing_keys}`` for a model."""
        from cecli.helpers.model_providers import ModelProviderManager

        if not model:
            return {"keys_in_environment": True, "missing_keys": []}

        provider = model.split("/", 1)[0] if "/" in model else None
        envs: List[str] = []

        if provider:
            config = ModelProviderManager().get_provider_config(provider)
            if config:
                envs = list(config.get("api_key_env") or [])

        if not envs and provider:
            from cecli.helpers.llms.config import PROVIDER_DEFAULTS

            env = (PROVIDER_DEFAULTS.get(provider) or {}).get("api_key_env")
            if env:
                envs = [env]

        found = [env for env in envs if os.environ.get(env)]
        if found:
            return {"keys_in_environment": found, "missing_keys": []}

        return {"keys_in_environment": [], "missing_keys": envs}

    # -- audio -------------------------------------------------------------

    def transcription(
        self,
        model: Optional[str] = None,
        file: Optional[Any] = None,
        prompt: Optional[str] = None,
        language: Optional[str] = None,
        **kwargs: Any,
    ) -> SimpleNamespace:
        """Transcribe audio via OpenAI's audio transcriptions API."""
        api_key = os.environ.get("OPENAI_API_KEY")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        data = {"model": model or "whisper-1"}
        if prompt:
            data["prompt"] = prompt
        if language:
            data["language"] = language

        with httpx.Client(timeout=600) as client:
            resp = client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers=headers,
                data=data,
                files={"file": ("audio", file, "application/octet-stream")},
            )
            resp.raise_for_status()
            payload = resp.json()

        return SimpleNamespace(text=payload.get("text", ""))

    # -- model-cost registry (no-ops) --------------------------------------

    def add_known_models(
        self, model_cost_map: Optional[Dict[str, Any]] = None, **kwargs: Any
    ) -> None:
        """No-op kept for litellm API compatibility (costs live in cecli metadata)."""
        return None


# ---------------------------------------------------------------------------
# The lazy proxy
# ---------------------------------------------------------------------------


class LazyLiteLLM:
    """Proxy that builds the facade lazily on first attribute access."""

    _lazy_module = None

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        self._load_litellm()
        return getattr(self._lazy_module, name)

    def __dir__(self) -> List[str]:
        self._load_litellm()
        names = set(dir(type(self)))
        names.update(dir(self._lazy_module))
        return sorted(names)

    def _load_litellm(self) -> None:
        if self._lazy_module is not None:
            return
        self._lazy_module = _LiteLLMFacade()


litellm = LazyLiteLLM()

__all__ = ["litellm"]


# ---------------------------------------------------------------------------
# Token-count estimator (tiktoken-free)
# ---------------------------------------------------------------------------

_WORD_OR_PUNCT_RE = re.compile(r"\w+|[^\w\s]")
_NON_ASCII_RE = re.compile(r"[^\x00-\x7f]")


def _estimate_token_count(text: str) -> int:
    """Estimate the number of tokens in ``text`` without a BPE tokenizer.

    Uses the classic ~4 chars/token rule of thumb, lifted for non-ASCII text
    (CJK/emoji tokenize at roughly one token per character) and floored by the
    number of word/punctuation runs so dense code with many short tokens isn't
    undercounted.
    """

    if not text:
        return 0

    units = len(_WORD_OR_PUNCT_RE.findall(text))
    non_ascii = len(_NON_ASCII_RE.findall(text))

    return max(1, len(text) // 4, units) + non_ascii
