"""ACP v2 data classes.

All ACP v2 JSON structures represented as Python dataclasses, typed for
serialisability. Every field uses the exact names from the spec; ``_meta`` fields
are plain ``dict`` slots for extensibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Common / Base Types ────────────────────────────────────────


@dataclass
class JsonRpcRequest:
    """JSON-RPC 2.0 request."""

    jsonrpc: str = "2.0"
    id: int | str | None = None
    method: str = ""
    params: dict | None = None


@dataclass
class JsonRpcResponse:
    """JSON-RPC 2.0 success/error response."""

    jsonrpc: str = "2.0"
    id: int | str | None = None
    result: Any | None = None
    error: JsonRpcError | None = None


@dataclass
class JsonRpcError:
    """JSON-RPC 2.0 error object."""

    code: int
    message: str
    data: Any | None = None


@dataclass
class ImplementationInfo:
    """Agent implementation identification."""

    name: str = ""
    version: str = ""
    title: str | None = None


@dataclass
class ContentBlockText:
    """A text content block."""

    type: str = "text"
    text: str = ""
    _meta: dict | None = None


@dataclass
class ContentBlockResource:
    """A resource content block."""

    type: str = "resource"
    resource: dict = field(default_factory=dict)
    _meta: dict | None = None


ContentBlock = ContentBlockText | ContentBlockResource


# ── Initialize ─────────────────────────────────────────────────


@dataclass
class ClientCapabilities:
    """Capabilities sent by the Client in initialize."""

    _meta: dict | None = None


@dataclass
class SessionPromptCapabilities:
    """Nested under session.prompt."""

    image: dict | None = None
    audio: dict | None = None
    embeddedContext: dict | None = None


@dataclass
class SessionCapabilities:
    """Agent's session capabilities."""

    prompt: SessionPromptCapabilities | None = None
    mcp: dict | None = None
    delete: dict | None = None
    additionalDirectories: dict | None = None


@dataclass
class AgentCapabilities:
    """Capabilities returned by the Agent in initialize result."""

    session: SessionCapabilities | None = None
    auth: dict | None = None
    _meta: dict | None = None


@dataclass
class InitializeParams:
    """Parameters for initialize request."""

    protocolVersion: int = 2
    capabilities: ClientCapabilities = field(default_factory=ClientCapabilities)
    info: ImplementationInfo | None = None


@dataclass
class InitializeResult:
    """Result of initialize request."""

    protocolVersion: int = 2
    capabilities: AgentCapabilities | None = None
    info: ImplementationInfo | None = None
    authMethods: list[dict] = field(default_factory=list)


# ── Session Basics ─────────────────────────────────────────────


@dataclass
class SessionNewParams:
    """Parameters for session/new."""

    cwd: str = ""
    mcpServers: list[dict] = field(default_factory=list)


@dataclass
class SessionNewResult:
    """Result of session/new — sessionId maps to coder_uuid."""

    sessionId: str = ""


@dataclass
class SessionInfo:
    """Session info entry for session/list."""

    sessionId: str = ""
    cwd: str | None = None
    status: str = "active"
    _meta: dict | None = None


@dataclass
class SessionListResult:
    """Result of session/list."""

    sessions: list[SessionInfo] = field(default_factory=list)
    _meta: dict | None = None


# ── Prompt ─────────────────────────────────────────────────────


@dataclass
class SessionPromptParams:
    """Parameters for session/prompt."""

    sessionId: str = ""
    prompt: list[ContentBlock] = field(default_factory=list)


@dataclass
class SessionPromptResult:
    """Empty result — completion is reported via session/update notifications."""

    pass


# ── Session / Cancel ───────────────────────────────────────────


@dataclass
class SessionCancelParams:
    """Parameters for session/cancel (notification)."""

    sessionId: str = ""


@dataclass
class SessionCloseParams:
    """Parameters for session/close."""

    sessionId: str = ""


@dataclass
class SessionResumeParams:
    """Parameters for session/resume."""

    sessionId: str = ""


# ── Session / Update Variants ──────────────────────────────────


@dataclass
class UserMessageUpdate:
    """Echoes accepted user prompt back as agent-owned message."""

    sessionUpdate: str = "user_message"
    messageId: str = ""
    content: list[ContentBlock] | None = None
    _meta: dict | None = None


@dataclass
class UserMessageChunk:
    """Streaming user message chunk."""

    sessionUpdate: str = "user_message_chunk"
    messageId: str = ""
    content: ContentBlock | None = None
    _meta: dict | None = None


@dataclass
class AgentMessageUpdate:
    """Complete agent message."""

    sessionUpdate: str = "agent_message"
    messageId: str = ""
    content: list[ContentBlock] | None = None
    _meta: dict | None = None


@dataclass
class AgentMessageChunk:
    """Streaming agent text response chunk."""

    sessionUpdate: str = "agent_message_chunk"
    messageId: str = ""
    content: ContentBlock = field(default_factory=lambda: ContentBlockText(text=""))
    _meta: dict | None = None


@dataclass
class AgentThoughtUpdate:
    """Complete agent thought block."""

    sessionUpdate: str = "agent_thought"
    messageId: str = ""
    content: list[ContentBlock] | None = None
    _meta: dict | None = None


@dataclass
class AgentThoughtChunk:
    """Streaming agent thought chunk (reasoning content)."""

    sessionUpdate: str = "agent_thought_chunk"
    messageId: str = ""
    content: ContentBlock = field(default_factory=lambda: ContentBlockText(text=""))
    _meta: dict | None = None


@dataclass
class ToolCallUpdate:
    """Tool call lifecycle update."""

    sessionUpdate: str = "tool_call_update"
    toolCallId: str = ""
    title: str | None = None
    kind: str | None = None
    status: str | None = None  # "pending", "in_progress", "completed", "error"
    content: list[dict] | None = None
    _meta: dict | None = None


@dataclass
class ToolCallContentChunk:
    """Tool result content chunk."""

    sessionUpdate: str = "tool_call_content_chunk"
    toolCallId: str = ""
    content: dict | None = None
    _meta: dict | None = None


@dataclass
class StateUpdate:
    """Session state update."""

    sessionUpdate: str = "state_update"
    state: str = ""  # "running" | "idle" | "requires_action"
    stopReason: str | None = None
    _meta: dict | None = None


SessionUpdate = (
    UserMessageUpdate
    | UserMessageChunk
    | AgentMessageUpdate
    | AgentMessageChunk
    | AgentThoughtUpdate
    | AgentThoughtChunk
    | ToolCallUpdate
    | ToolCallContentChunk
    | StateUpdate
)
