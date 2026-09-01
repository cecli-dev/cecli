"""Tests for ACP v2 data classes (models.py).

Tests JSON serialization, default values, and construction
of all major ACP types.
"""

from __future__ import annotations

from cecli.helpers.server.acp.models import (
    AgentCapabilities,
    AgentMessageChunk,
    AgentMessageUpdate,
    AgentThoughtChunk,
    AgentThoughtUpdate,
    ContentBlockResource,
    ContentBlockText,
    ImplementationInfo,
    InitializeParams,
    InitializeResult,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
    SessionCancelParams,
    SessionCapabilities,
    SessionCloseParams,
    SessionInfo,
    SessionListResult,
    SessionNewParams,
    SessionNewResult,
    SessionPromptParams,
    SessionPromptResult,
    SessionResumeParams,
    StateUpdate,
    ToolCallContentChunk,
    ToolCallUpdate,
    UserMessageChunk,
    UserMessageUpdate,
)


class TestJsonRpcModels:
    """Test core JSON-RPC envelope models."""

    def test_request_defaults(self):
        req = JsonRpcRequest()
        assert req.jsonrpc == "2.0"
        assert req.id is None
        assert req.method == ""
        assert req.params is None

    def test_request_with_values(self):
        req = JsonRpcRequest(method="initialize", id=1, params={"key": "val"})
        assert req.method == "initialize"
        assert req.id == 1
        assert req.params == {"key": "val"}

    def test_response_defaults(self):
        resp = JsonRpcResponse()
        assert resp.jsonrpc == "2.0"
        assert resp.id is None
        assert resp.result is None
        assert resp.error is None

    def test_response_success(self):
        resp = JsonRpcResponse(id=1, result={"ok": True})
        assert resp.id == 1
        assert resp.result == {"ok": True}
        assert resp.error is None

    def test_response_error(self):
        err = JsonRpcError(code=-32601, message="Method not found")
        resp = JsonRpcResponse(id=1, error=err)
        assert resp.error.code == -32601
        assert resp.error.message == "Method not found"

    def test_error_defaults(self):
        err = JsonRpcError(code=-32700, message="Parse error")
        assert err.code == -32700
        assert err.message == "Parse error"
        assert err.data is None

    def test_error_with_data(self):
        err = JsonRpcError(code=-32602, message="Invalid params", data={"field": "id"})
        assert err.data == {"field": "id"}


class TestImplementationInfo:
    """Test ImplementationInfo model."""

    def test_defaults(self):
        info = ImplementationInfo()
        assert info.name == ""
        assert info.version == ""
        assert info.title is None

    def test_with_values(self):
        info = ImplementationInfo(name="cecli", version="1.0.0", title="CECLI Agent")
        assert info.name == "cecli"
        assert info.version == "1.0.0"
        assert info.title == "CECLI Agent"


class TestContentBlocks:
    """Test content block models."""

    def test_text_block(self):
        block = ContentBlockText(text="hello")
        assert block.type == "text"
        assert block.text == "hello"

    def test_resource_block(self):
        block = ContentBlockResource(resource={"uri": "file:///test.txt", "text": "content"})
        assert block.type == "resource"
        assert block.resource["uri"] == "file:///test.txt"


class TestInitializeModels:
    """Test initialize-related models."""

    def test_initialize_params_defaults(self):
        params = InitializeParams()
        assert params.protocolVersion == 2
        assert params.capabilities is not None

    def test_initialize_result_defaults(self):
        result = InitializeResult()
        assert result.protocolVersion == 2
        assert result.capabilities is None
        assert result.authMethods == []

    def test_agent_capabilities(self):
        caps = AgentCapabilities(session=SessionCapabilities(), auth={})
        assert caps.session is not None
        assert caps.auth == {}


class TestSessionModels:
    """Test session lifecycle models."""

    def test_session_new_params(self):
        params = SessionNewParams(cwd="/home")
        assert params.cwd == "/home"
        assert params.mcpServers == []

    def test_session_new_result(self):
        result = SessionNewResult(sessionId="uuid-123")
        assert result.sessionId == "uuid-123"

    def test_session_info(self):
        info = SessionInfo(sessionId="uuid-123", cwd="/home", status="active")
        assert info.sessionId == "uuid-123"
        assert info.cwd == "/home"
        assert info.status == "active"

    def test_session_list_result(self):
        sessions = [SessionInfo(sessionId="s1"), SessionInfo(sessionId="s2")]
        result = SessionListResult(sessions=sessions)
        assert len(result.sessions) == 2
        assert result.sessions[0].sessionId == "s1"
        assert result.sessions[1].sessionId == "s2"
        assert result._meta is None

    def test_session_prompt_params(self):
        blocks = [ContentBlockText(text="hello")]
        params = SessionPromptParams(sessionId="s1", prompt=blocks)
        assert params.sessionId == "s1"
        assert len(params.prompt) == 1

    def test_session_prompt_result(self):
        result = SessionPromptResult()
        assert result is not None

    def test_cancel_params(self):
        params = SessionCancelParams(sessionId="s1")
        assert params.sessionId == "s1"

    def test_close_params(self):
        params = SessionCloseParams(sessionId="s1")
        assert params.sessionId == "s1"

    def test_resume_params(self):
        params = SessionResumeParams(sessionId="s1")
        assert params.sessionId == "s1"


class TestSessionUpdateVariants:
    """Test session update variant models."""

    def test_state_update_running(self):
        update = StateUpdate(state="running")
        assert update.sessionUpdate == "state_update"
        assert update.state == "running"
        assert update.stopReason is None

    def test_state_update_idle(self):
        update = StateUpdate(state="idle", stopReason="end_turn")
        assert update.state == "idle"
        assert update.stopReason == "end_turn"

    def test_user_message_update(self):
        update = UserMessageUpdate(messageId="msg-1", content=[ContentBlockText(text="hi")])
        assert update.sessionUpdate == "user_message"
        assert update.messageId == "msg-1"
        assert len(update.content) == 1

    def test_user_message_chunk(self):
        chunk = UserMessageChunk(messageId="msg-1", content=ContentBlockText(text="hi"))
        assert chunk.sessionUpdate == "user_message_chunk"

    def test_agent_message_update(self):
        update = AgentMessageUpdate(messageId="msg-1")
        assert update.sessionUpdate == "agent_message"

    def test_agent_message_chunk(self):
        chunk = AgentMessageChunk(messageId="msg-1", content=ContentBlockText(text="hello"))
        assert chunk.sessionUpdate == "agent_message_chunk"
        assert chunk.content.text == "hello"

    def test_agent_thought_update(self):
        update = AgentThoughtUpdate(messageId="thought-1")
        assert update.sessionUpdate == "agent_thought"

    def test_agent_thought_chunk(self):
        chunk = AgentThoughtChunk(messageId="thought-1", content=ContentBlockText(text="reasoning"))
        assert chunk.sessionUpdate == "agent_thought_chunk"
        assert chunk.content.text == "reasoning"

    def test_tool_call_update(self):
        update = ToolCallUpdate(
            toolCallId="tc-1", status="in_progress", title="Read file", kind="read"
        )
        assert update.sessionUpdate == "tool_call_update"
        assert update.toolCallId == "tc-1"
        assert update.status == "in_progress"
        assert update.title == "Read file"
        assert update.kind == "read"

    def test_tool_call_update_completed(self):
        update = ToolCallUpdate(
            toolCallId="tc-1", status="completed", content=[{"type": "text", "text": "done"}]
        )
        assert update.status == "completed"
        assert update.content == [{"type": "text", "text": "done"}]

    def test_tool_call_content_chunk(self):
        chunk = ToolCallContentChunk(toolCallId="tc-1", content={"type": "text", "text": "result"})
        assert chunk.sessionUpdate == "tool_call_content_chunk"
        assert chunk.content["text"] == "result"
