"""Integration tests for agent and subagent MCP management."""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
import pytest_asyncio

from cecli.coders.agent_coder import AgentCoder
from cecli.coders.sub_agent_coder import SubAgentCoder
from cecli.tools.resource_manager import Tool as ResourceManagerTool


@pytest.fixture
def mock_mcp_manager():
    """Fixture for a mocked McpServerManager."""
    manager = MagicMock()
    manager.connected_servers = {}

    # Mock servers
    server1 = MagicMock()
    server1.name = "test_server"
    server1.config = {"enabled": True}

    server2 = MagicMock()
    server2.name = "sub_test_server"
    server2.config = {"enabled": True}

    manager.servers = [server1, server2]

    def get_server_side_effect(name):
        if name == "test_server":
            return server1
        if name == "sub_test_server":
            return server2
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
    manager.add_server = AsyncMock()
    manager.add_server = AsyncMock()
    manager.add_server = AsyncMock()

    return manager


@pytest.fixture
def agent_coder(mock_mcp_manager):
    """Fixture for an AgentCoder with a mocked MCP manager."""
    # Reset AgentService class-level state to prevent test isolation issues
    from cecli.helpers.agents.service import AgentService

    AgentService._instances.clear()
    AgentService._uuid_coder_map.clear()
    AgentService._primary_agent_uuid = None

    with patch("cecli.coders.agent_coder.McpServerManager", return_value=mock_mcp_manager):
        coder = AgentCoder(
            main_model=MagicMock(),
            io=MagicMock(),
        )
        coder.mcp_manager = mock_mcp_manager
        coder.original_kwargs = {}
        coder.coroutines = Mock()

        async def mock_interruptible(coro, event):
            return await coro, False

        coder.coroutines.interruptible.side_effect = mock_interruptible
        coder.interrupt_event = Mock()
        return coder


@pytest_asyncio.fixture
async def sub_agent_coder(agent_coder):
    """Fixture for a SubAgentCoder."""
    # Fix: Use create() class method instead of direct instantiation
    sub_agent = await SubAgentCoder.create(from_coder=agent_coder)
    # Ensure sub_agent has the required mocks for tools
    sub_agent.coroutines = agent_coder.coroutines
    sub_agent.interrupt_event = agent_coder.interrupt_event
    yield sub_agent
    # Clean up AgentService state to prevent test isolation issues
    from cecli.helpers.agents.service import AgentService

    AgentService._uuid_coder_map.pop(sub_agent.uuid, None)
    AgentService._instances.pop(sub_agent.uuid, None)


@pytest.mark.asyncio
async def test_agent_can_load_mcp_server(agent_coder, mock_mcp_manager):
    """Verify an agent can load an MCP server."""
    server_name = "test_server"

    await ResourceManagerTool.execute(agent_coder, load_mcp=[server_name])

    mock_mcp_manager.connect_server.assert_called_once_with(server_name)
    assert server_name in mock_mcp_manager.connected_servers


@pytest.mark.asyncio
async def test_agent_can_remove_mcp_server(agent_coder, mock_mcp_manager):
    """Verify an agent can remove an MCP server."""
    server_name = "test_server"
    mock_mcp_manager.connected_servers[server_name] = "connected"

    await ResourceManagerTool.execute(agent_coder, remove_mcp=[server_name])

    mock_mcp_manager.disconnect_server.assert_called_once_with(server_name)
    assert server_name not in mock_mcp_manager.connected_servers


@pytest.mark.asyncio
async def test_sub_agent_can_load_mcp_server(sub_agent_coder, mock_mcp_manager):
    """Verify a subagent can load an MCP server."""
    server_name = "sub_test_server"

    await ResourceManagerTool.execute(sub_agent_coder, load_mcp=[server_name])

    mock_mcp_manager.connect_server.assert_called_once_with(server_name)
    assert server_name in mock_mcp_manager.connected_servers


@pytest.mark.asyncio
async def test_sub_agent_can_remove_mcp_server(sub_agent_coder, mock_mcp_manager):
    """Verify a subagent can remove an MCP server."""
    server_name = "sub_test_server"
    mock_mcp_manager.connected_servers[server_name] = "connected"

    await ResourceManagerTool.execute(sub_agent_coder, remove_mcp=[server_name])

    mock_mcp_manager.disconnect_server.assert_called_once_with(server_name)
    assert server_name not in mock_mcp_manager.connected_servers
