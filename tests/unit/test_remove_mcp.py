"""Unit tests for RemoveMcpTool.execute."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from cecli.tools.resource_manager import Tool as ResourceManagerTool


class DummyIO:
    """Mock IO object for testing."""

    def __init__(self):
        self.tool_error = MagicMock()
        self.tool_warning = MagicMock()
        self.tool_output = MagicMock()
        self.interrupt_event = MagicMock()


class DummyCoder:
    """Mock Coder object for testing."""

    def __init__(self):
        self.io = DummyIO()
        self.mcp_manager = MagicMock()
        self.mcp_manager.servers = []
        self.mcp_manager.connected_servers = {}
        self.coroutines = MagicMock()
        self.interrupt_event = MagicMock()
        self.registered_servers = {"included": set(), "excluded": set()}


@pytest.fixture
def coder():
    """Provide a dummy coder for testing."""
    return DummyCoder()


@pytest.fixture
def mock_server():
    """Provide a mock MCP server."""
    server = MagicMock()
    server.name = "test-server"
    return server


@pytest.mark.asyncio
async def test_remove_mcp_tool_success():
    """Test successful removal of an MCP server."""
    # Setup
    coder = MagicMock()
    coder.agent_config = {"include_context_blocks": {"servers"}, "exclude_context_blocks": set()}
    coder.mcp_manager = MagicMock()
    server = MagicMock()
    server.name = "test-server"
    coder.mcp_manager.get_server.return_value = server
    coder.mcp_manager.connected_servers = {"test-server": server}

    # Mock disconnect_server as an async function that returns (True, False)
    async def mock_disconnect(server_name):
        return True, False

    coder.mcp_manager.disconnect_server = AsyncMock(side_effect=mock_disconnect)

    # Mock the interruptible method to execute the coroutine directly without interruption
    async def mock_interruptible(coro, event):
        return await coro

    coder.coroutines = MagicMock()
    coder.coroutines.interruptible = mock_interruptible
    coder.interrupt_event = MagicMock()
    # Execute
    result = await ResourceManagerTool.execute(coder, remove_mcp=["test-server"])
    # Assertions
    assert "Removed server: test-server" in str(result)
    coder.mcp_manager.disconnect_server.assert_awaited_once_with("test-server")


@pytest.mark.asyncio
async def test_remove_mcp_tool_non_existent():
    """Test removing a non-existent MCP server."""
    # Setup
    coder = MagicMock()
    coder.agent_config = {"include_context_blocks": {"servers"}, "exclude_context_blocks": set()}
    coder.mcp_manager = MagicMock()
    # Create a mock server that exists (to bypass the 'no servers' check)
    existing_server = MagicMock()
    existing_server.name = "existing-server"
    coder.mcp_manager.servers = [existing_server]
    # But the one we're looking for doesn't exist
    coder.mcp_manager.get_server.return_value = None
    # Execute
    result = await ResourceManagerTool.execute(coder, remove_mcp=["non-existent-server"])
    # Assertions
    assert "MCP server non-existent-server does not exist." in str(result)


@pytest.mark.asyncio
async def test_remove_mcp_tool_not_connected():
    """Test removing a server that is not connected."""
    coder = MagicMock()
    coder.agent_config = {"include_context_blocks": {"servers"}, "exclude_context_blocks": set()}
    coder.mcp_manager = MagicMock()
    server = MagicMock()
    server.name = "test-server"
    coder.mcp_manager.servers = [server]
    coder.mcp_manager.get_server.return_value = server
    coder.mcp_manager.connected_servers = {}
    result = await ResourceManagerTool.execute(coder, remove_mcp=["test-server"])
    assert "Server test-server is not currently connected." in str(result)


@pytest.mark.asyncio
async def test_remove_mcp_tool_wildcard():
    """Test removing all servers with wildcard '*'."""
    coder = MagicMock()
    coder.agent_config = {"include_context_blocks": {"servers"}, "exclude_context_blocks": set()}
    coder.mcp_manager = MagicMock()
    server1 = MagicMock()
    server1.name = "server1"
    server2 = MagicMock()
    server2.name = "server2"
    coder.mcp_manager.servers = [server1, server2]
    coder.mcp_manager.connected_servers = {"server1": server1, "server2": server2}
    coder.mcp_manager.get_server.side_effect = lambda name: next(
        (s for s in [server1, server2] if s.name == name), None
    )

    # Mock disconnect_server as an async function that returns (True, False)
    async def mock_disconnect(server_name):
        return True, False

    coder.mcp_manager.disconnect_server = AsyncMock(side_effect=mock_disconnect)

    # Mock interruptible to execute the coroutine without interruption
    async def mock_interruptible(coro, event):
        return await coro

    coder.coroutines = MagicMock()
    coder.coroutines.interruptible = mock_interruptible
    coder.interrupt_event = MagicMock()
    result = await ResourceManagerTool.execute(coder, remove_mcp=["*"])
    assert "Removed server: server1" in str(result)
    assert "Removed server: server2" in str(result)


@pytest.mark.asyncio
async def test_remove_mcp_tool_interrupted():
    """Test when removal is interrupted."""
    coder = MagicMock()
    coder.agent_config = {"include_context_blocks": {"servers"}, "exclude_context_blocks": set()}
    coder.mcp_manager = MagicMock()
    server = MagicMock()
    server.name = "test-server"
    coder.mcp_manager.servers = [server]
    coder.mcp_manager.get_server.return_value = server
    coder.mcp_manager.connected_servers = {"test-server": server}

    async def mock_disconnect(server_name):
        return False, True

    coder.mcp_manager.disconnect_server = AsyncMock(side_effect=mock_disconnect)

    async def mock_interruptible(coro, event):
        return False, True

    coder.coroutines.interruptible = mock_interruptible
    coder.interrupt_event = MagicMock()
    result = await ResourceManagerTool.execute(coder, remove_mcp=["test-server"])
    assert "Interrupted: test-server" in str(result)


@pytest.mark.asyncio
async def test_remove_mcp_tool_failed():
    """Test when removal fails."""
    coder = MagicMock()
    coder.agent_config = {"include_context_blocks": {"servers"}, "exclude_context_blocks": set()}
    coder.mcp_manager = MagicMock()
    server = MagicMock()
    server.name = "test-server"
    coder.mcp_manager.servers = [server]
    coder.mcp_manager.get_server.return_value = server
    coder.mcp_manager.connected_servers = {"test-server": server}

    async def mock_disconnect(server_name):
        return False, False

    coder.mcp_manager.disconnect_server = AsyncMock(side_effect=mock_disconnect)

    async def mock_interruptible(coro, event):
        return await coro

    coder.coroutines.interruptible = mock_interruptible
    coder.interrupt_event = MagicMock()
    result = await ResourceManagerTool.execute(coder, remove_mcp=["test-server"])
    assert "Unable to remove server: test-server" in str(result)


@pytest.mark.asyncio
async def test_remove_mcp_tool_no_servers_configured():
    """Test when no MCP servers are configured at all."""
    coder = MagicMock()
    coder.agent_config = {"include_context_blocks": {"servers"}, "exclude_context_blocks": set()}
    coder.mcp_manager = MagicMock()
    coder.mcp_manager.servers = []
    result = await ResourceManagerTool.execute(coder, remove_mcp=["test"])
    assert result.to_dict()["result"][0]["content"] == "No MCP servers are configured."


@pytest.mark.asyncio
async def test_remove_mcp_tool_mixed_results():
    """Test mixed success/failure results."""
    coder = MagicMock()
    coder.agent_config = {"include_context_blocks": {"servers"}, "exclude_context_blocks": set()}
    coder.mcp_manager = MagicMock()
    server1 = MagicMock()
    server1.name = "server1"
    server2 = MagicMock()
    server2.name = "server2"
    coder.mcp_manager.servers = [server1, server2]
    coder.mcp_manager.connected_servers = {"server1": server1, "server2": server2}
    coder.mcp_manager.get_server.side_effect = lambda name: next(
        (s for s in [server1, server2] if s.name == name), None
    )
    call_count = 0

    async def mock_disconnect(server_name):
        nonlocal call_count
        result = (True, False) if call_count == 0 else (False, False)
        call_count += 1
        return result

    coder.mcp_manager.disconnect_server = AsyncMock(side_effect=mock_disconnect)

    async def mock_interruptible(coro, event):
        return await coro

    coder.coroutines.interruptible = mock_interruptible
    coder.interrupt_event = MagicMock()
    result = await ResourceManagerTool.execute(coder, remove_mcp=["server1", "server2"])
    assert "Removed server: server1" in str(result)
    assert "Unable to remove server: server2" in str(result)


@pytest.mark.asyncio
async def test_remove_mcp_tool_dictionary_iteration_fix():
    """Test that dictionary iteration bug is fixed - iterates over keys correctly."""
    coder = MagicMock()
    coder.agent_config = {"include_context_blocks": {"servers"}, "exclude_context_blocks": set()}
    coder.mcp_manager = MagicMock()
    server1 = MagicMock()
    server1.name = "server1"
    server2 = MagicMock()
    server2.name = "server2"
    coder.mcp_manager.servers = [server1, server2]
    coder.mcp_manager.connected_servers = {"server1": server1, "server2": server2}
    coder.mcp_manager.get_server.side_effect = lambda name: next(
        (s for s in [server1, server2] if s.name == name), None
    )

    async def mock_disconnect(server_name):
        return True, False

    coder.mcp_manager.disconnect_server = AsyncMock(side_effect=mock_disconnect)

    async def mock_interruptible(coro, event):
        return await coro

    coder.coroutines.interruptible = mock_interruptible
    coder.interrupt_event = MagicMock()
    result = await ResourceManagerTool.execute(coder, remove_mcp=["*"])
    # Should successfully remove both servers using dictionary keys
    assert "Removed server: server1" in str(result)
    assert "Removed server: server2" in str(result)
