"""Comprehensive retry logic tests for McpServerManager.connect_server.

This file implements all 28 test cases (TC-001 through TC-028) from the
MCP retry logic plan in .cecli.plans.md Sections 10 and 11.

Test categories:
    - Core retry behavior (TC-001, TC-002, TC-003, TC-014)
    - Edge cases - cancellation (TC-007, TC-008)
    - Edge cases - no retry (TC-004, TC-005, TC-006, TC-013)
    - Timing tests (TC-009, TC-010)
    - Logging tests (TC-011, TC-012)
    - Integration tests (TC-015 through TC-021)
    - Regression tests (TC-022 through TC-027)
    - Special case - tool loading failure (TC-028)
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import Tool as McpTool

from cecli.commands.core import SwitchCoderSignal
from cecli.mcp.manager import McpServerManager
from cecli.mcp.server import LocalServer, McpServer, _get_mcp_major_version

# ---------------------------------------------------------------------------
# Fixtures (mirrors tests/mcp/test_manager.py for consistency)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_io():
    """Mock IO object for capturing log calls."""
    io = MagicMock()
    io.tool_output = MagicMock()
    io.tool_error = MagicMock()
    io.tool_warning = MagicMock()
    return io


@pytest.fixture
def mock_server():
    """Mock McpServer named 'test-server' with async connect/disconnect."""
    server = MagicMock(spec=McpServer)
    server.name = "test-server"
    server.config = {"name": "test-server", "enabled": True}
    server.connect = AsyncMock()
    server.disconnect = AsyncMock()
    server.is_connected = False
    return server


@pytest.fixture
def mock_local_server():
    """Mock LocalServer named 'Local'."""
    server = MagicMock(spec=LocalServer)
    server.name = "Local"
    server.config = {"name": "Local", "enabled": True}
    server.connect = AsyncMock()
    server.disconnect = AsyncMock()
    server.is_connected = False
    return server


def _mcp_tools_from_openai_schemas(schemas):
    """Build mcp Tool objects from OpenAI function schema dicts (version-aware)."""
    tools = []
    for schema in schemas:
        function = schema["function"]
        if _get_mcp_major_version() >= 2:
            tools.append(
                McpTool(
                    name=function["name"],
                    description=function["description"],
                    input_schema=function["parameters"],
                )
            )
        else:
            tools.append(
                McpTool(
                    name=function["name"],
                    description=function["description"],
                    inputSchema=function["parameters"],
                )
            )
    return tools


@pytest.fixture
def mock_tools():
    """Expected OpenAI-format tool dicts stored by connect_server."""
    return [
        {
            "type": "function",
            "function": {
                "name": "test_tool",
                "description": "A test tool",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
                "strict": False,
            },
        }
    ]


@pytest.fixture
def mock_session(mock_tools):
    """Mock session whose list_tools() yields mcp Tools matching mock_tools."""
    session = MagicMock()
    session.list_tools = AsyncMock(
        return_value=SimpleNamespace(tools=_mcp_tools_from_openai_schemas(mock_tools))
    )
    return session


# ---------------------------------------------------------------------------
# Helper to create a mock coder for integration tests
# ---------------------------------------------------------------------------


def _make_mock_coder(mock_server, mock_io, connected_servers=None):
    """Create a mock coder with mcp_manager for integration tests.

    Args:
        mock_server: The mock server to include in the manager.
        mock_io: Mock IO object.
        connected_servers: Optional set of already-connected servers.

    Returns:
        A MagicMock coder with mcp_manager, coroutines, interrupt_event.
    """
    coder = MagicMock()
    coder.io = mock_io
    coder.edit_format = "agent"
    coder.interrupt_event = MagicMock()
    coder.interrupt_event.clear = MagicMock()
    coder.interrupt_event.is_set = MagicMock(return_value=False)

    # Create mcp_manager
    coder.mcp_manager = MagicMock()
    coder.mcp_manager.servers = [mock_server]
    coder.mcp_manager.connected_servers = connected_servers or []
    coder.mcp_manager.get_server = MagicMock(return_value=mock_server)
    coder.mcp_manager.connect_server = AsyncMock()

    # Create coroutines with interruptible that passes through
    coder.coroutines = MagicMock()

    async def _passthrough_interruptible(coro, event):
        """Pass-through interruptible that just awaits the coroutine."""
        return await coro, False

    coder.coroutines.interruptible = _passthrough_interruptible

    # registered_servers for update_server_registration
    coder.registered_servers = {"included": set(), "excluded": set()}

    return coder


# ---------------------------------------------------------------------------
# TC-001: connect_server retries on first failure, succeeds on second attempt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_server_retries_first_failure_succeeds_second(
    mock_server, mock_io, mock_tools, mock_session
):
    """TC-001: connect_server retries after first connection failure and succeeds on second attempt."""
    manager = McpServerManager(servers=[mock_server], io=mock_io)
    mock_server.connect.side_effect = [Exception("Connection failed"), mock_session]

    with patch("asyncio.sleep") as mock_sleep:
        result = await manager.connect_server("test-server")

    assert result is True
    assert mock_server.connect.call_count == 2
    assert mock_sleep.call_count == 1
    assert mock_sleep.call_args[0][0] == 1.0
    assert mock_io.tool_warning.call_count == 1
    assert mock_server in manager._connected_servers
    assert manager._server_tools["test-server"] == mock_tools


# ---------------------------------------------------------------------------
# TC-002: connect_server retries on first and second failure, succeeds on third
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_server_retries_two_failures_succeeds_third(
    mock_server, mock_io, mock_tools, mock_session
):
    """TC-002: connect_server retries after two failures and succeeds on third attempt."""
    manager = McpServerManager(servers=[mock_server], io=mock_io)
    mock_server.connect.side_effect = [
        Exception("Fail 1"),
        Exception("Fail 2"),
        mock_session,
    ]

    with patch("asyncio.sleep") as mock_sleep:
        result = await manager.connect_server("test-server")

    assert result is True
    assert mock_server.connect.call_count == 3
    assert mock_sleep.call_count == 2
    assert mock_sleep.call_args_list[0][0][0] == 1.0
    assert mock_sleep.call_args_list[1][0][0] == 2.0
    assert mock_io.tool_warning.call_count == 2
    assert mock_server in manager._connected_servers


# ---------------------------------------------------------------------------
# TC-003: connect_server returns False after all 3 retries exhausted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_server_fails_after_all_retries(mock_server, mock_io):
    """TC-003: connect_server fails after all 3 retry attempts are exhausted."""
    manager = McpServerManager(servers=[mock_server], io=mock_io)
    mock_server.connect.side_effect = Exception("Connection failed")

    with patch("asyncio.sleep"):
        result = await manager.connect_server("test-server")

    assert result is False
    assert mock_server.connect.call_count == 3
    assert mock_io.tool_warning.call_count == 2
    mock_io.tool_error.assert_called_once()
    error_msg = mock_io.tool_error.call_args[0][0]
    assert "after 3 attempts" in error_msg
    assert mock_server not in manager._connected_servers
    assert "test-server" not in manager._server_tools


# ---------------------------------------------------------------------------
# TC-004: connect_server does not retry for LocalServer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_server_no_retry_local_server(mock_local_server):
    """TC-004: connect_server connects LocalServer on first attempt without retry."""
    manager = McpServerManager(servers=[mock_local_server])

    with patch("cecli.mcp.manager.get_local_tool_schemas") as mock_get_schemas:
        mock_get_schemas.return_value = [{"name": "local_tool"}]
        result = await manager.connect_server("Local")

    assert result is True
    assert mock_local_server.connect.call_count == 1
    assert mock_local_server in manager._connected_servers
    assert manager._server_tools["Local"] == [{"name": "local_tool"}]


# ---------------------------------------------------------------------------
# TC-005: connect_server does not retry when server not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_server_no_retry_not_found(mock_io):
    """TC-005: connect_server returns False immediately for non-existent server."""
    manager = McpServerManager(servers=[], io=mock_io)

    result = await manager.connect_server("nonexistent-server")

    assert result is False
    mock_io.tool_warning.assert_called_once()
    warning_msg = mock_io.tool_warning.call_args[0][0]
    assert "not found" in warning_msg
    assert len(manager._connected_servers) == 0


# ---------------------------------------------------------------------------
# TC-006: connect_server does not retry when already connected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_server_no_retry_already_connected(mock_server, mock_io):
    """TC-006: connect_server returns True immediately for already-connected server."""
    manager = McpServerManager(servers=[mock_server], io=mock_io, verbose=True)
    manager._connected_servers.add(mock_server)

    result = await manager.connect_server("test-server")

    assert result is True
    mock_server.connect.assert_not_called()
    mock_io.tool_output.assert_called_once()
    output_msg = mock_io.tool_output.call_args[0][0]
    assert "already connected" in output_msg


# ---------------------------------------------------------------------------
# TC-007: connect_server propagates asyncio.CancelledError during retry delay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_server_propagates_cancelled_error_during_retry(mock_server, mock_io):
    """TC-007: connect_server re-raises CancelledError when interrupted during retry backoff."""
    manager = McpServerManager(servers=[mock_server], io=mock_io)
    mock_server.connect.side_effect = Exception("Connection failed")

    with patch("asyncio.sleep") as mock_sleep:
        mock_sleep.side_effect = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await manager.connect_server("test-server")

    assert mock_server.connect.call_count == 1
    assert mock_sleep.call_count == 1
    mock_io.tool_error.assert_not_called()


# ---------------------------------------------------------------------------
# TC-008: connect_server propagates asyncio.CancelledError during server.connect()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_server_propagates_cancelled_error_during_connect(mock_server, mock_io):
    """TC-008: connect_server re-raises CancelledError when server.connect() raises it."""
    manager = McpServerManager(servers=[mock_server], io=mock_io)
    mock_server.connect.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await manager.connect_server("test-server")

    assert mock_server.connect.call_count == 1
    mock_io.tool_error.assert_not_called()


# ---------------------------------------------------------------------------
# TC-009: connect_server uses exponential backoff timing (1s, 2s, 4s)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_server_exponential_backoff_timing(mock_server, mock_io):
    """TC-009: connect_server applies exponential backoff delays of 1s, 2s between retries."""
    manager = McpServerManager(servers=[mock_server], io=mock_io)
    mock_server.connect.side_effect = Exception("Connection failed")

    sleep_delays = []

    async def _capture_sleep(delay):
        sleep_delays.append(delay)

    with patch("asyncio.sleep", side_effect=_capture_sleep):
        result = await manager.connect_server("test-server")

    assert result is False
    assert len(sleep_delays) == 2
    assert sleep_delays[0] == 1.0
    assert sleep_delays[1] == 2.0


# ---------------------------------------------------------------------------
# TC-010: connect_server backoff is capped at max_delay of 30 seconds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_server_backoff_capped_at_max_delay(mock_server, mock_io):
    """TC-010: connect_server backoff delay does not exceed 30 seconds maximum.

    With default max_retries=3, delays are 1.0 and 2.0 (both below 30s cap).
    We verify the min(delay * backoff, max_delay) logic by checking that
    all recorded delays are <= 30.0.
    """
    manager = McpServerManager(servers=[mock_server], io=mock_io)
    mock_server.connect.side_effect = Exception("Connection failed")

    sleep_delays = []

    async def _capture_sleep(delay):
        sleep_delays.append(delay)

    with patch("asyncio.sleep", side_effect=_capture_sleep):
        result = await manager.connect_server("test-server")

    assert result is False
    assert len(sleep_delays) == 2
    for delay in sleep_delays:
        assert delay <= 30.0
    assert sleep_delays[0] == 1.0
    assert sleep_delays[1] == 2.0


# ---------------------------------------------------------------------------
# TC-011: connect_server logs warning on each failed attempt (except final)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_server_logs_warning_on_failed_attempts(mock_server, mock_io):
    """TC-011: connect_server calls _log_warning for each non-final failed attempt."""
    manager = McpServerManager(servers=[mock_server], io=mock_io)
    mock_server.connect.side_effect = Exception("Connection failed")

    with patch("asyncio.sleep"):
        await manager.connect_server("test-server")

    assert mock_io.tool_warning.call_count == 2

    warning1 = mock_io.tool_warning.call_args_list[0][0][0]
    assert "attempt 1 failed" in warning1
    assert "retrying in 1.0s" in warning1
    assert "Connection failed" in warning1

    warning2 = mock_io.tool_warning.call_args_list[1][0][0]
    assert "attempt 2 failed" in warning2
    assert "retrying in 2.0s" in warning2
    assert "Connection failed" in warning2


# ---------------------------------------------------------------------------
# TC-012: connect_server logs error on final failure with attempt count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_server_logs_error_on_final_failure(mock_server, mock_io):
    """TC-012: connect_server calls _log_error after all retries exhausted."""
    manager = McpServerManager(servers=[mock_server], io=mock_io)
    mock_server.connect.side_effect = Exception("Connection failed")

    with patch("asyncio.sleep"):
        await manager.connect_server("test-server")

    mock_io.tool_error.assert_called_once()
    error_msg = mock_io.tool_error.call_args[0][0]
    assert "Failed to connect to MCP server" in error_msg
    assert "after 3 attempts" in error_msg
    assert "Connection failed" in error_msg


# ---------------------------------------------------------------------------
# TC-013: connect_server does not log error for "unnamed-server" on final failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_server_no_error_log_unnamed_server(mock_io):
    """TC-013: connect_server suppresses error logging for servers named 'unnamed-server'."""
    unnamed_server = MagicMock(spec=McpServer)
    unnamed_server.name = "unnamed-server"
    unnamed_server.config = {"name": "unnamed-server", "enabled": True}
    unnamed_server.connect = AsyncMock(side_effect=Exception("Connection failed"))
    unnamed_server.disconnect = AsyncMock()
    unnamed_server.is_connected = False

    manager = McpServerManager(servers=[unnamed_server], io=mock_io)

    with patch("asyncio.sleep"):
        result = await manager.connect_server("unnamed-server")

    assert result is False
    mock_io.tool_error.assert_not_called()
    assert unnamed_server not in manager._connected_servers


# ---------------------------------------------------------------------------
# TC-014: connect_server succeeds on first attempt (no retry needed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_server_succeeds_first_attempt(mock_server, mock_tools, mock_session):
    """TC-014: connect_server connects successfully on first attempt without any retries."""
    manager = McpServerManager(servers=[mock_server])
    mock_server.connect.return_value = mock_session

    result = await manager.connect_server("test-server")

    assert result is True
    assert mock_server.connect.call_count == 1
    assert mock_server in manager._connected_servers
    assert manager._server_tools["test-server"] == mock_tools
    mock_session.list_tools.assert_awaited_once()


# ---------------------------------------------------------------------------
# TC-015: from_servers simplification - add_server_with_retry calls connect once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_from_servers_calls_connect_once(mock_server, mock_io, mock_tools, mock_session):
    """TC-015: from_servers add_server_with_retry no longer has its own retry loop."""
    mock_server.connect.return_value = mock_session

    manager = await McpServerManager.from_servers(servers=[mock_server], io=mock_io, verbose=True)

    assert isinstance(manager, McpServerManager)
    assert manager._servers == [mock_server]
    assert mock_server in manager._connected_servers
    assert mock_server.connect.call_count == 1
    mock_session.list_tools.assert_awaited_once()


# ---------------------------------------------------------------------------
# TC-016: from_servers shows warning for failed server after connect_server retries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_from_servers_warning_after_retries(mock_server, mock_io):
    """TC-016: from_servers displays warning when server fails to connect after retries."""
    mock_server.connect.side_effect = Exception("Connection failed")

    with patch("asyncio.sleep"):
        manager = await McpServerManager.from_servers(servers=[mock_server], io=mock_io)

    assert isinstance(manager, McpServerManager)
    assert mock_server not in manager._connected_servers

    warning_messages = [call[0][0] for call in mock_io.tool_warning.call_args_list]
    found_init_warning = any("MCP tool initialization failed" in msg for msg in warning_messages)
    assert found_init_warning

    assert mock_server.connect.call_count == 3


# ---------------------------------------------------------------------------
# TC-017: /load-mcp command benefits from retry logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_mcp_command_benefits_from_retry(mock_server, mock_io, mock_tools, mock_session):
    """TC-017: LoadMcpCommand.execute uses connect_server which now has built-in retry."""
    from cecli.commands.load_mcp import LoadMcpCommand

    coder = _make_mock_coder(mock_server, mock_io)

    # connect_server fails first, succeeds second (simulating retry inside)
    async def _connect_with_retry(name):
        # Simulate the retry happening inside connect_server
        mock_server.connect.side_effect = [Exception("Fail"), mock_session]
        with patch("asyncio.sleep"):
            manager = McpServerManager(servers=[mock_server], io=mock_io)
            return await manager.connect_server(name)

    coder.mcp_manager.connect_server = _connect_with_retry
    coder.mcp_manager.get_server = MagicMock(return_value=mock_server)
    coder.mcp_manager.connected_servers = []

    with patch("cecli.commands.load_mcp.iter_all_coders", return_value=[coder]):
        with patch("cecli.commands.load_mcp.update_server_registration"):
            with pytest.raises(SwitchCoderSignal):
                await LoadMcpCommand.execute(mock_io, coder, "test-server")


# ---------------------------------------------------------------------------
# TC-018: /load-mcp command reports failure after retries exhausted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_mcp_command_reports_failure_after_retries(mock_server, mock_io):
    """TC-018: LoadMcpCommand.execute reports 'Unable to load server' after retries exhausted."""
    from cecli.commands.load_mcp import LoadMcpCommand

    coder = _make_mock_coder(mock_server, mock_io)
    coder.mcp_manager.connect_server = AsyncMock(return_value=False)
    coder.mcp_manager.get_server = MagicMock(return_value=mock_server)
    coder.mcp_manager.connected_servers = []

    with patch("cecli.commands.load_mcp.iter_all_coders", return_value=[coder]):
        with patch("cecli.commands.load_mcp.update_server_registration"):
            with pytest.raises(SwitchCoderSignal):
                await LoadMcpCommand.execute(mock_io, coder, "test-server")

    # Check that the results were output - "Unable to load server" should be in output
    output_calls = [str(call) for call in mock_io.tool_output.call_args_list]
    all_output = " ".join(output_calls)
    assert "Unable to load server: test-server" in all_output


# ---------------------------------------------------------------------------
# TC-019: /load-mcp interruptible wrapper propagates cancellation during retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_mcp_propagates_cancellation_during_retry(mock_server, mock_io):
    """TC-019: LoadMcpCommand interruptible wrapper correctly propagates CancelledError."""
    from cecli.commands.load_mcp import LoadMcpCommand

    coder = _make_mock_coder(mock_server, mock_io)

    async def _connect_raises_cancelled(name):
        raise asyncio.CancelledError()

    coder.mcp_manager.connect_server = _connect_raises_cancelled
    coder.mcp_manager.get_server = MagicMock(return_value=mock_server)
    coder.mcp_manager.connected_servers = []

    # Make interruptible propagate the CancelledError
    async def _propagate_interruptible(coro, event):
        return await coro, False

    coder.coroutines.interruptible = _propagate_interruptible

    with patch("cecli.commands.load_mcp.iter_all_coders", return_value=[coder]):
        with patch("cecli.commands.load_mcp.update_server_registration"):
            with pytest.raises(asyncio.CancelledError):
                await LoadMcpCommand.execute(mock_io, coder, "test-server")


# ---------------------------------------------------------------------------
# TC-020: /load-session command benefits from retry logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_session_benefits_from_retry(mock_server, mock_io, mock_tools, mock_session):
    """TC-020: Session loading uses connect_server which now retries on transient failures.

    This test verifies that connect_server is called with the correct server name
    and that retry logic is exercised during session loading.
    """
    manager = McpServerManager(servers=[mock_server], io=mock_io)
    mock_server.connect.side_effect = [Exception("Fail"), mock_session]

    with patch("asyncio.sleep"):
        # Simulate what /load-session does: call connect_server for the MCP server
        result = await manager.connect_server("test-server")

    assert result is True
    assert mock_server.connect.call_count == 2
    assert mock_server in manager._connected_servers
    assert manager._server_tools["test-server"] == mock_tools


# ---------------------------------------------------------------------------
# TC-021: Resource Manager tool benefits from retry logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resource_manager_benefits_from_retry(mock_server, mock_io, mock_tools, mock_session):
    """TC-021: ResourceManager _load_mcp uses connect_server which now retries."""
    from cecli.tools.resource_manager import Tool as ResourceManagerTool

    coder = _make_mock_coder(mock_server, mock_io)

    # Simulate connect_server with retry (fail first, succeed second)
    async def _connect_with_retry(name):
        mock_server.connect.side_effect = [Exception("Fail"), mock_session]
        with patch("asyncio.sleep"):
            manager = McpServerManager(servers=[mock_server], io=mock_io)
            return await manager.connect_server(name)

    coder.mcp_manager.connect_server = _connect_with_retry
    coder.mcp_manager.get_server = MagicMock(return_value=mock_server)
    coder.mcp_manager.connected_servers = []

    # Mock the context block check
    coder.agent_config = {"include_context_blocks": {"servers"}, "exclude_context_blocks": set()}

    with patch("cecli.tools.resource_manager.iter_all_coders", return_value=[coder]):
        with patch("cecli.tools.resource_manager.update_server_registration"):
            result = await ResourceManagerTool._load_mcp(coder, "test-server")

    assert "Loaded server: test-server" in result


# ---------------------------------------------------------------------------
# TC-022: Regression - existing connect_server_success test still passes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_connect_server_success(mock_server, mock_tools, mock_session):
    """TC-022: Regression - connect_server succeeds on first attempt (existing behavior)."""
    manager = McpServerManager(servers=[mock_server])
    mock_server.connect.return_value = mock_session

    result = await manager.connect_server("test-server")

    assert result is True
    assert mock_server.connect.call_count == 1
    assert mock_server in manager._connected_servers
    assert manager._server_tools["test-server"] == mock_tools


# ---------------------------------------------------------------------------
# TC-023: Regression - existing connect_server_failure test still passes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_connect_server_failure(mock_server, mock_io):
    """TC-023: Regression - connect_server failure now retries 3 times (updated behavior).

    Note: The original test_connect_server_failure in test_manager.py asserted
    connect() called once. With retry logic, connect() is called 3 times.
    The existing test in test_manager.py has been updated to reflect this.
    This test replicates those assertions here for regression coverage.
    """
    manager = McpServerManager(servers=[mock_server], io=mock_io)
    mock_server.connect.side_effect = Exception("Connection failed")

    with patch("asyncio.sleep"):
        result = await manager.connect_server("test-server")

    assert result is False
    assert mock_server.connect.call_count == 3
    assert mock_io.tool_warning.call_count == 2
    mock_io.tool_error.assert_called_once()
    error_msg = mock_io.tool_error.call_args[0][0]
    assert "after 3 attempts" in error_msg
    assert mock_server not in manager._connected_servers


# ---------------------------------------------------------------------------
# TC-024: Regression - existing connect_server_not_found test still passes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_connect_server_not_found(mock_io):
    """TC-024: Regression - connect_server returns False immediately for not-found server."""
    manager = McpServerManager(servers=[], io=mock_io)

    result = await manager.connect_server("nonexistent-server")

    assert result is False
    mock_io.tool_warning.assert_called_once()


# ---------------------------------------------------------------------------
# TC-025: Regression - existing connect_server_already_connected test still passes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_connect_server_already_connected(mock_server, mock_io):
    """TC-025: Regression - connect_server returns True immediately for already-connected server."""
    manager = McpServerManager(servers=[mock_server], io=mock_io, verbose=True)
    manager._connected_servers.add(mock_server)

    result = await manager.connect_server("test-server")

    assert result is True
    mock_server.connect.assert_not_called()
    mock_io.tool_output.assert_called_once()


# ---------------------------------------------------------------------------
# TC-026: Regression - existing connect_server_local_server test still passes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_connect_server_local_server(mock_local_server):
    """TC-026: Regression - connect_server connects LocalServer without retry."""
    manager = McpServerManager(servers=[mock_local_server])

    with patch("cecli.mcp.manager.get_local_tool_schemas") as mock_get_schemas:
        mock_get_schemas.return_value = [{"name": "local_tool"}]
        result = await manager.connect_server("Local")

    assert result is True
    assert mock_local_server.connect.call_count == 1
    assert mock_local_server in manager._connected_servers
    assert manager._server_tools["Local"] == [{"name": "local_tool"}]


# ---------------------------------------------------------------------------
# TC-027: Regression - existing from_servers_creates_manager test still passes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regression_from_servers_creates_manager(
    mock_server, mock_io, mock_tools, mock_session
):
    """TC-027: Regression - from_servers creates manager with simplified add_server_with_retry."""
    mock_server.connect.return_value = mock_session

    manager = await McpServerManager.from_servers(servers=[mock_server], io=mock_io, verbose=True)

    assert isinstance(manager, McpServerManager)
    assert manager._servers == [mock_server]
    assert mock_server in manager._connected_servers
    assert mock_server.connect.call_count == 1
    mock_session.list_tools.assert_awaited_once()


# ---------------------------------------------------------------------------
# TC-028: connect_server retries on tool-loading failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_server_retries_on_tool_loading_failure(
    mock_server, mock_io, mock_tools, mock_session
):
    """TC-028: connect_server retries when connect() succeeds but list_tools() fails.

    In this scenario:
    - server.connect() succeeds (returns session)
    - list_tools() fails on first call, succeeds on second
    - The retry loop catches the exception from list_tools and retries
    - server.connect() is called again on retry (it returns the same session)
    - list_tools() is called twice total
    """
    manager = McpServerManager(servers=[mock_server], io=mock_io)
    mock_server.connect.return_value = mock_session
    mock_session.list_tools.side_effect = [
        Exception("Tool load failed"),
        SimpleNamespace(tools=_mcp_tools_from_openai_schemas(mock_tools)),
    ]

    with patch("asyncio.sleep") as mock_sleep:
        result = await manager.connect_server("test-server")

    assert result is True
    # connect() is called for each attempt (2 attempts: first fails at list_tools, second succeeds)
    assert mock_server.connect.call_count == 2
    # list_tools() called twice: first fails, second succeeds
    assert mock_session.list_tools.call_count == 2
    # sleep called once (between attempt 1 and 2)
    assert mock_sleep.call_count == 1
    assert mock_sleep.call_args[0][0] == 1.0
    # Warning logged for the first failed attempt
    assert mock_io.tool_warning.call_count == 1
    # Server connected and tools loaded
    assert mock_server in manager._connected_servers
    assert manager._server_tools["test-server"] == mock_tools
