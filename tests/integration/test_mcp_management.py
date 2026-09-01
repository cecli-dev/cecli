"""Integration tests for MCP management tools."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from cecli.tools.resource_manager import Tool as ResourceManagerTool


class CoderMock:
    """Mock Coder object for integration testing."""

    def __init__(self):
        self.mcp_manager = MagicMock()
        self.mcp_manager.servers = []
        self.mcp_manager.connected_servers = {}
        self.mcp_manager.get_server.return_value = None
        self.mcp_manager.connect_server = AsyncMock(return_value=(True, False))
        self.mcp_manager.disconnect_server = AsyncMock(return_value=(True, False))
        self.coroutines = MagicMock()
        self.interrupt_event = MagicMock()
        self.registered_servers = {"included": set(), "excluded": set()}
        self.io = MagicMock()
        self.agent_config = {"include_context_blocks": {"servers"}}

    async def mock_interruptible(self, coro, event):
        """Mock interruptible that just executes the coroutine."""
        return await coro

    def add_server(self, name, enabled=True):
        """Add a mock server to the manager."""
        server = MagicMock()
        server.name = name
        server.config = {"enabled": enabled}
        self.mcp_manager.servers.append(server)
        original_get_server = self.mcp_manager.get_server.side_effect

        def get_server_side_effect(server_name):
            if server_name == name:
                return server
            if original_get_server:
                return original_get_server(server_name)
            return None

        self.mcp_manager.get_server.side_effect = get_server_side_effect


@pytest.fixture
def coder():
    """Provide a mock coder for integration testing."""
    return CoderMock()


@pytest.mark.asyncio
async def test_integration_load_and_remove_server(coder):
    """Test loading and then removing a server."""
    coder.add_server("integration-test-server")
    coder.coroutines.interruptible = coder.mock_interruptible

    # Load the server
    load_result = await ResourceManagerTool.execute(coder, load_mcp=["integration-test-server"])
    assert "Loaded server: integration-test-server" in str(load_result)

    # Mock the connected server for the remove tool
    coder.mcp_manager.connected_servers = {"integration-test-server": coder.mcp_manager.servers[0]}

    # Remove the server
    remove_result = await ResourceManagerTool.execute(coder, remove_mcp=["integration-test-server"])
    assert "Removed server: integration-test-server" in str(remove_result)


@pytest.mark.asyncio
async def test_integration_wildcard_load_and_remove(coder):
    """Test loading and removing all servers with a wildcard."""
    coder.add_server("server1")
    coder.add_server("server2")
    coder.add_server("server3", enabled=False)
    coder.coroutines.interruptible = coder.mock_interruptible

    # Load all enabled servers
    load_result = await ResourceManagerTool.execute(coder, load_mcp=["*"])
    assert "Loaded server: server1" in str(load_result)
    assert "Loaded server: server2" in str(load_result)
    # Non-enabled servers are filtered out silently by wildcard expansion

    # Mock the connected servers for the remove tool
    coder.mcp_manager.connected_servers = {
        "server1": coder.mcp_manager.servers[0],
        "server2": coder.mcp_manager.servers[1],
    }

    # Remove all connected servers
    remove_result = await ResourceManagerTool.execute(coder, remove_mcp=["*"])
    assert "Removed server: server1" in str(remove_result)
    assert "Removed server: server2" in str(remove_result)
