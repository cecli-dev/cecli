"""Normalized response objects (litellm-shaped).

These dataclasses are the stable output shape of :func:`cecli.helpers.llms.acompletion`
across all four API families. They intentionally mirror the litellm
``ModelResponse``/``ChatCompletionMessage`` surface that cecli consumes so the
``LazyLiteLLM`` swap in ``cecli/llm.py`` keeps the same public attribute shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]  # parsed JSON
    #: Provider-specific stream index (e.g. Gemini parallel functionCall parts
    #: streamed in separate SSE chunks get distinct indices so they do not
    #: collapse onto index 0 in the litellm shim). None for single-call chunks.
    index: Optional[int] = None


@dataclass
class Message:
    role: str
    content: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    reasoning_content: Optional[str] = None
    reasoning_redacted: bool = False
    provider_specific_fields: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Choice:
    index: int
    message: Message
    finish_reason: Optional[str] = None


@dataclass
class Usage:
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    # Provider cache/usage details preserved for token & cost logging
    # (deepseek/gemini cached tokens, anthropic cache_read/creation, openai details).
    prompt_cache_hit_tokens: Optional[int] = None
    cache_read_input_tokens: Optional[int] = None
    cache_creation_input_tokens: Optional[int] = None
    prompt_tokens_details: Optional[Dict[str, Any]] = None
    completion_tokens_details: Optional[Dict[str, Any]] = None


@dataclass
class CompletionResponse:
    id: Optional[str] = None
    model: Optional[str] = None
    choices: List[Choice] = field(default_factory=list)
    usage: Optional[Usage] = None
    provider_specific_fields: Dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        parts = [c.message.content or "" for c in self.choices if c.message.content]
        return "\n".join(parts)

    @property
    def reasoning(self) -> str:
        parts = [
            c.message.reasoning_content or "" for c in self.choices if c.message.reasoning_content
        ]
        return "\n".join(parts)

    @property
    def tool_calls(self) -> List[ToolCall]:
        calls: List[ToolCall] = []

        for c in self.choices:
            calls.extend(c.message.tool_calls)

        return calls


@dataclass
class CompletionChunk:
    """Normalized streaming chunk."""

    text: str = ""
    reasoning: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    finish_reason: Optional[str] = None
    usage: Optional[Usage] = None
    provider_specific_fields: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Parts model — the common underlying shape across all four API families
# ---------------------------------------------------------------------------
# Mirrors simonw/LLM's parts model (llm/parts.py): every native response is
# normalized into an ordered list of Parts on a PartsMessage, so chat,
# responses, gemini and messages all expose the SAME underlying shape and can
# round-trip provider metadata statelessly (send the entire conversation each
# turn). ``provider_metadata`` carries opaque provider data that must be echoed
# back on the next request (Anthropic thinking signatures, OpenAI Responses
# encrypted_content, Gemini thoughtSignature).


@dataclass
class Part:
    """Base class for all parts. The role lives on the enclosing PartsMessage."""

    provider_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TextPart(Part):
    text: str = ""


@dataclass
class ReasoningPart(Part):
    """Reasoning/thinking tokens.

    ``redacted=True, text=""`` is the opaque-reasoning marker: the provider
    reports reasoning happened but withholds the content (the token total lives
    on ``Usage.completion_tokens_details["reasoning_tokens"]``).
    """

    text: str = ""
    redacted: bool = False


@dataclass
class ToolCallPart(Part):
    """A request by the model to call a tool."""

    name: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)
    tool_call_id: Optional[str] = None
    server_executed: bool = False


@dataclass
class ToolResultPart(Part):
    """The result of a tool call."""

    name: str = ""
    output: str = ""
    tool_call_id: Optional[str] = None
    server_executed: bool = False
    exception: Optional[str] = None


@dataclass
class PartsMessage:
    """A single turn in the common conversation shape: role + ordered parts."""

    role: str
    parts: List[Part] = field(default_factory=list)
    provider_metadata: Dict[str, Any] = field(default_factory=dict)


def parts_message_to_message(pm: PartsMessage) -> Message:
    """Convert a PartsMessage into the litellm-shaped Message adapter.

    The parts model is the canonical shape produced by the domain normalizers;
    this adapter feeds cecli's existing litellm-shaped consumers
    (``litellm_compat`` / ``base_coder``) unchanged.
    """
    text = "\n".join(p.text for p in pm.parts if isinstance(p, TextPart) and p.text)
    reasoning = "\n".join(p.text for p in pm.parts if isinstance(p, ReasoningPart) and p.text)
    redacted = any(isinstance(p, ReasoningPart) and p.redacted for p in pm.parts)
    tool_calls = [
        ToolCall(
            id=p.tool_call_id or f"call_{i}",
            name=p.name,
            arguments=p.arguments,
        )
        for i, p in enumerate(pm.parts)
        if isinstance(p, ToolCallPart)
    ]
    return Message(
        role=pm.role,
        content=text or None,
        tool_calls=tool_calls,
        reasoning_content=reasoning or None,
        reasoning_redacted=redacted,
        provider_specific_fields=dict(pm.provider_metadata),
    )


__all__ = [
    "ToolCall",
    "Message",
    "Choice",
    "Usage",
    "CompletionResponse",
    "CompletionChunk",
    "Part",
    "TextPart",
    "ReasoningPart",
    "ToolCallPart",
    "ToolResultPart",
    "PartsMessage",
    "parts_message_to_message",
]
