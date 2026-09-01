"""Unit tests for RemoveMcpTool.execute."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from cecli.tools.resource_manager import Tool as ResourceManagerTool


class DummyIO:
    """Mock IO object for testing."""

    def __init__(self):
        self.tool_error = Mock()
        self.tool_warning = Mock()
        self.tool_output = Mock()
        self.interrupt_event = Mock()


class DummyCoder:
    """Mock Coder object for testing."""

    def __init__(self):
        self.io = DummyIO()
        self.mcp_manager = Mock()
        self.mcp_manager.servers = []
        self.mcp_manager.connected_servers = {}
        self.coroutines = Mock()
        self.coroutines.interruptible = AsyncMock()

        self.interrupt_event = Mock()
        self.registered_servers = {"included": set(), "excluded": set()}
        self.agent_config = {"include_context_blocks": {"servers"}, "exclude_context_blocks": set()}


@pytest.fixture
def coder():
    """Provide a dummy coder for testing."""
    return DummyCoder()


@pytest.fixture
def mock_server():
    """Provide a mock MCP server."""
    server = Mock()
    server.name = "test-server"
    return server


class TestRemoveMcpTool:
    """Test cases for RemoveMcpTool."""

    @pytest.fixture(autouse=True)
    def _patch_global_exclusion(self):
        """Patch is_server_globally_excluded to prevent test isolation issues with AgentService."""
        with patch(
            "cecli.tools.resource_manager.is_server_globally_excluded",
            return_value=True,
        ):
            yield

    @pytest.mark.asyncio
    async def test_no_configured_servers(self, coder):
        """Test when no MCP servers are configured at all."""
        coder.mcp_manager.servers = []
        result = await ResourceManagerTool.execute(coder, remove_mcp=["test"])
        assert result.to_dict()["result"][0]["content"] == "No MCP servers are configured."

    @pytest.mark.asyncio
    async def test_server_not_found(self, coder, mock_server):
        """Test when requested server doesn't exist."""
        coder.mcp_manager.servers = [mock_server]
        coder.mcp_manager.connected_servers = {"existing": "server"}
        coder.mcp_manager.get_server.return_value = None
        result = await ResourceManagerTool.execute(coder, remove_mcp=["nonexistent"])
        assert "MCP server nonexistent does not exist." in str(result)

    @pytest.mark.asyncio
    async def test_all_servers_not_loaded(self, coder, mock_server):
        """Test when multiple servers exist but are not loaded."""
        coder.mcp_manager.servers = [mock_server]
        coder.mcp_manager.connected_servers = {}
        coder.mcp_manager.get_server.return_value = mock_server
        result = await ResourceManagerTool.execute(coder, remove_mcp=["test-server"])
        assert "Server test-server is not currently connected." in str(result)

    @pytest.mark.asyncio
    async def test_successful_removal(self, coder, mock_server):
        """Test successful server removal."""
        coder.mcp_manager.servers = [mock_server]
        coder.mcp_manager.connected_servers = {"test-server": mock_server}
        coder.mcp_manager.get_server.return_value = mock_server
        coder.coroutines.interruptible.return_value = (True, False)
        result = await ResourceManagerTool.execute(coder, remove_mcp=["test-server"])
        assert "Removed server: test-server" in str(result)

    @pytest.mark.asyncio
    async def test_removal_interrupted(self, coder, mock_server):
        """Test when removal is interrupted."""
        coder.mcp_manager.servers = [mock_server]
        coder.mcp_manager.connected_servers = {"test-server": mock_server}
        coder.mcp_manager.get_server.return_value = mock_server
        coder.coroutines.interruptible.return_value = (False, True)
        result = await ResourceManagerTool.execute(coder, remove_mcp=["test-server"])
        assert "Interrupted: test-server" in str(result)

    @pytest.mark.asyncio
    async def test_removal_failed(self, coder, mock_server):
        """Test when removal fails."""
        coder.mcp_manager.servers = [mock_server]
        coder.mcp_manager.connected_servers = {"test-server": mock_server}
        coder.mcp_manager.get_server.return_value = mock_server
        coder.coroutines.interruptible.return_value = (False, False)
        result = await ResourceManagerTool.execute(coder, remove_mcp=["test-server"])
        assert "Unable to remove server: test-server" in str(result)

    @pytest.mark.asyncio
    async def test_remove_all_servers(self, coder):
        """Test removing all servers with '*' wildcard."""
        server1 = Mock()
        server1.name = "server1"
        server2 = Mock()
        server2.name = "server2"
        coder.mcp_manager.servers = [server1, server2]
        coder.mcp_manager.connected_servers = {"server1": server1, "server2": server2}
        coder.mcp_manager.get_server.side_effect = lambda name: next(
            (s for s in [server1, server2] if s.name == name), None
        )
        coder.coroutines.interruptible.return_value = (True, False)
        result = await ResourceManagerTool.execute(coder, remove_mcp=["*"])
        assert "Removed server: server1" in str(result)
        assert "Removed server: server2" in str(result)

    @pytest.mark.asyncio
    async def test_mixed_results(self, coder):
        """Test mixed success/failure results."""
        server1 = Mock()
        server1.name = "server1"
        server2 = Mock()
        server2.name = "server2"
        coder.mcp_manager.servers = [server1, server2]
        coder.mcp_manager.connected_servers = {"server1": server1, "server2": server2}
        coder.mcp_manager.get_server.side_effect = lambda name: next(
            (s for s in [server1, server2] if s.name == name), None
        )
        call_count = 0

        async def mock_interruptible_func(*args, **kwargs):
            nonlocal call_count
            result = (True, False) if call_count == 0 else (False, False)
            call_count += 1
            return result

        coder.coroutines.interruptible.side_effect = mock_interruptible_func
        result = await ResourceManagerTool.execute(coder, remove_mcp=["server1", "server2"])
        assert "Removed server: server1" in str(result)
        assert "Unable to remove server: server2" in str(result)
