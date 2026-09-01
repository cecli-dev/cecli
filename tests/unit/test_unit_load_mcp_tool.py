"""Unit tests for load-mcp tool."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from cecli.tools.resource_manager import Tool as ResourceManagerTool


@pytest.fixture
def mock_mcp_manager():
    """Fixture for a mocked McpServerManager."""
    manager = MagicMock()
    manager.connected_servers = {}

    # Mock servers
    server1 = MagicMock()
    server1.name = "test-server"
    server1.config = {"enabled": True}

    server2 = MagicMock()
    server2.name = "server2"
    server2.config = {"enabled": True}

    server3 = MagicMock()
    server3.name = "server3"
    server3.config = {"enabled": False}

    manager.servers = [server1, server2, server3]

    def get_server_side_effect(name):
        if name == "test-server":
            return server1
        if name == "server2":
            return server2
        if name == "server3":
            return server3
        return None

    manager.get_server.side_effect = get_server_side_effect

    async def connect(server_name):
        manager.connected_servers[server_name] = "connected"
        return True, False  # (did_connect, interrupted)

    async def disconnect(server_name):
        if server_name in manager.connected_servers:
            del manager.connected_servers[server_name]
            return True, False
        return False, False

    manager.connect_server = AsyncMock(side_effect=connect)
    manager.disconnect_server = AsyncMock(side_effect=disconnect)
    manager.add_server = AsyncMock()
    return manager


@pytest.mark.asyncio
async def test_load_mcp_tool_success(mock_mcp_manager):
    """Test loading a single MCP server successfully."""

    # Mock the coder
    coder = MagicMock()
    coder.agent_config = {"include_context_blocks": {"servers"}, "exclude_context_blocks": set()}
    coder.mcp_manager = mock_mcp_manager
    coder.registered_servers = {"included": set(), "excluded": set()}

    # Mock interruptible to return (await coro, False)
    async def mock_interruptible(coro, event):
        return await coro

    coder.coroutines = MagicMock()
    coder.coroutines.interruptible.side_effect = mock_interruptible
    coder.interrupt_event = MagicMock()
    coder.registered_servers = {"included": set(), "excluded": set()}
    result = await ResourceManagerTool.execute(coder, load_mcp=["test-server"])

    assert "Loaded server: test-server" in str(result)
    mock_mcp_manager.connect_server.assert_awaited_once_with("test-server")


@pytest.mark.asyncio
async def test_load_mcp_tool_non_existent(mock_mcp_manager):
    """Test loading a non-existent MCP server."""

    coder = MagicMock()
    coder.agent_config = {"include_context_blocks": {"servers"}, "exclude_context_blocks": set()}
    coder.mcp_manager = mock_mcp_manager
    coder.registered_servers = {"included": set(), "excluded": set()}

    result = await ResourceManagerTool.execute(coder, load_mcp=["non-existent-server"])

    assert "MCP server non-existent-server does not exist." in str(result)
    mock_mcp_manager.connect_server.assert_not_awaited()


@pytest.mark.asyncio
async def test_load_mcp_tool_already_loaded(mock_mcp_manager):
    """Test loading an already loaded MCP server."""
    coder = MagicMock()
    coder.agent_config = {"include_context_blocks": {"servers"}, "exclude_context_blocks": set()}
    coder.mcp_manager = mock_mcp_manager
    coder.registered_servers = {"included": set(), "excluded": set()}
    # Pre-populate connected_servers
    server = mock_mcp_manager.get_server("test-server")
    coder.mcp_manager.connected_servers = {"test-server": server}

    result = await ResourceManagerTool.execute(coder, load_mcp=["test-server"])

    assert "Server already loaded: test-server" in str(result)
    mock_mcp_manager.connect_server.assert_not_awaited()


@pytest.mark.asyncio
async def test_load_mcp_tool_wildcard_and_duplicate_fix(mock_mcp_manager):
    """Test loading with wildcard and duplicate fix."""

    coder = MagicMock()
    coder.agent_config = {"include_context_blocks": {"servers"}, "exclude_context_blocks": set()}
    coder.mcp_manager = mock_mcp_manager
    coder.registered_servers = {"included": set(), "excluded": set()}

    # Mock interruptible to return (await coro, False)
    async def mock_interruptible(coro, event):
        return await coro

    coder.coroutines = MagicMock()
    coder.coroutines.interruptible.side_effect = mock_interruptible
    coder.interrupt_event = MagicMock()

    # Set up connected_servers: server1 is already connected
    server1 = mock_mcp_manager.get_server("test-server")
    coder.mcp_manager.connected_servers = {"test-server": server1}

    result = await ResourceManagerTool.execute(coder, load_mcp=["*"])

    # Check results
    # Wildcard expansion skips already-connected servers; no "already loaded" message is produced
    assert "Loaded server: server2" in str(result)
    # Non-enabled servers are filtered out silently by wildcard expansion

    # Verify connect_server was called only once for server2
    mock_mcp_manager.connect_server.assert_awaited_once_with("server2")
