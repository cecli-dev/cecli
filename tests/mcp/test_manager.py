import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import Tool as McpTool

from cecli.mcp.manager import McpServerManager
from cecli.mcp.server import LocalServer, McpServer, _get_mcp_major_version


@pytest.fixture
def mock_io():
    io = MagicMock()
    io.tool_output = MagicMock()
    io.tool_error = MagicMock()
    io.tool_warning = MagicMock()
    return io


@pytest.fixture
def mock_server():
    server = MagicMock(spec=McpServer)
    server.name = "test-server"
    server.config = {"name": "test-server", "enabled": True}
    server.connect = AsyncMock()
    server.disconnect = AsyncMock()
    server.is_connected = False
    return server


@pytest.fixture
def mock_local_server():
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


class TestMcpServerManager:
    def test_manager_init(self, mock_io):
        manager = McpServerManager(servers=[], io=mock_io, verbose=True)

        assert manager.io == mock_io
        assert manager.verbose is True
        assert manager._servers == []
        assert manager._server_tools == {}
        assert manager._connected_servers == set()

    def test_manager_servers_property(self, mock_server):
        manager = McpServerManager(servers=[mock_server])

        assert manager.servers == [mock_server]

    def test_manager_is_connected_false_initially(self):
        manager = McpServerManager(servers=[])

        assert manager.is_connected is False
        assert manager.connected_servers == []

    def test_manager_failed_servers(self, mock_server):
        manager = McpServerManager(servers=[mock_server])

        assert manager.failed_servers == [mock_server]

        # Add to connected set
        manager._connected_servers.add(mock_server)

        assert manager.failed_servers == []

    def test_get_server_found(self, mock_server):
        manager = McpServerManager(servers=[mock_server])

        result = manager.get_server("test-server")

        assert result is mock_server

    def test_get_server_not_found(self, mock_server):
        manager = McpServerManager(servers=[mock_server])

        result = manager.get_server("nonexistent-server")

        assert result is None

    @pytest.mark.asyncio
    async def test_connect_server_not_found(self, mock_io):
        manager = McpServerManager(servers=[], io=mock_io)

        result = await manager.connect_server("nonexistent-server")

        assert result is False
        mock_io.tool_warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_server_already_connected(self, mock_server, mock_io):
        manager = McpServerManager(servers=[mock_server], io=mock_io, verbose=True)
        manager._connected_servers.add(mock_server)

        result = await manager.connect_server("test-server")

        assert result is True
        mock_io.tool_output.assert_called_once()
        mock_server.connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_server_local_server(self, mock_local_server):
        manager = McpServerManager(servers=[mock_local_server])

        with patch("cecli.mcp.manager.get_local_tool_schemas") as mock_get_schemas:
            mock_get_schemas.return_value = [{"name": "local_tool"}]
            result = await manager.connect_server("Local")

            assert result is True
            mock_local_server.connect.assert_called_once()
            assert mock_local_server in manager._connected_servers
            assert manager._server_tools["Local"] == [{"name": "local_tool"}]

    @pytest.mark.asyncio
    async def test_connect_server_success(self, mock_server, mock_tools, mock_session):
        manager = McpServerManager(servers=[mock_server])
        mock_server.connect.return_value = mock_session

        result = await manager.connect_server("test-server")

        assert result is True
        mock_server.connect.assert_called_once()
        mock_session.list_tools.assert_awaited_once()
        assert mock_server in manager._connected_servers
        assert manager._server_tools["test-server"] == mock_tools

    @pytest.mark.asyncio
    async def test_connect_server_failure(self, mock_server, mock_io):
        manager = McpServerManager(servers=[mock_server], io=mock_io)
        mock_server.connect.side_effect = Exception("Connection failed")

        with patch("asyncio.sleep"):
            result = await manager.connect_server("test-server")

        assert result is False
        assert mock_server.connect.call_count == 3  # 1 initial + 2 retries
        assert mock_io.tool_warning.call_count == 2  # warnings for attempts 1 and 2
        mock_io.tool_error.assert_called_once()
        error_msg = mock_io.tool_error.call_args[0][0]
        assert "after 3 attempts" in error_msg
        assert mock_server not in manager._connected_servers

    @pytest.mark.asyncio
    async def test_disconnect_server_not_found(self, mock_io):
        manager = McpServerManager(servers=[], io=mock_io)

        result = await manager.disconnect_server("nonexistent-server")

        assert result is False
        mock_io.tool_warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_server_not_connected(self, mock_server, mock_io):
        manager = McpServerManager(servers=[mock_server], io=mock_io, verbose=True)

        result = await manager.disconnect_server("test-server")

        assert result is True
        mock_io.tool_output.assert_called_once()
        mock_server.disconnect.assert_not_called()

    @pytest.mark.asyncio
    async def test_disconnect_server_success(self, mock_server, mock_io):
        manager = McpServerManager(servers=[mock_server], io=mock_io, verbose=True)
        manager._connected_servers.add(mock_server)
        manager._server_tools["test-server"] = [{"name": "test_tool"}]

        result = await manager.disconnect_server("test-server")

        assert result is True
        mock_server.disconnect.assert_called_once()
        assert "test-server" not in manager._server_tools
        assert mock_server not in manager._connected_servers

    @pytest.mark.asyncio
    async def test_disconnect_all_no_servers(self, mock_io):
        manager = McpServerManager(servers=[], io=mock_io, verbose=True)

        await manager.disconnect_all()

        mock_io.tool_output.assert_called_once_with("MCP servers already disconnected")

    @pytest.mark.asyncio
    async def test_disconnect_all_multiple_servers(self, mock_server, mock_io):
        server1 = MagicMock(spec=McpServer)
        server1.name = "server1"
        server1.disconnect = AsyncMock()

        server2 = MagicMock(spec=McpServer)
        server2.name = "server2"
        server2.disconnect = AsyncMock()

        manager = McpServerManager(servers=[server1, server2], io=mock_io, verbose=True)
        manager._connected_servers.add(server1)
        manager._connected_servers.add(server2)
        manager._server_tools = {"server1": [], "server2": []}

        await manager.disconnect_all()

        server1.disconnect.assert_called_once()
        server2.disconnect.assert_called_once()
        assert manager._connected_servers == set()
        assert "server1" not in manager._server_tools
        assert "server2" not in manager._server_tools

    @pytest.mark.asyncio
    async def test_disconnect_all_cancelled_during_shutdown(self, mock_io):
        server1 = MagicMock(spec=McpServer)
        server1.name = "server1"
        started = asyncio.Event()

        async def blocking_disconnect():
            started.set()
            await asyncio.Event().wait()

        server1.disconnect = blocking_disconnect

        manager = McpServerManager(servers=[server1], io=mock_io, verbose=True)
        manager._connected_servers.add(server1)
        manager._server_tools = {"server1": []}

        # Simulate the task running disconnect_all being cancelled mid-gather
        # (e.g. by an anyio cancel scope during program shutdown).
        task = asyncio.create_task(manager.disconnect_all())
        await started.wait()
        task.cancel()

        # Should complete without raising CancelledError.
        assert await task is None

    @pytest.mark.asyncio
    async def test_add_server_success(self, mock_server, mock_io):
        manager = McpServerManager(servers=[], io=mock_io, verbose=True)

        result = await manager.add_server(mock_server, connect=False)

        assert result is True
        assert manager._servers == [mock_server]
        mock_io.tool_output.assert_called_once()
        mock_server.connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_server_duplicate_name(self, mock_server, mock_io):
        manager = McpServerManager(servers=[mock_server], io=mock_io)

        duplicate_server = MagicMock(spec=McpServer)
        duplicate_server.name = "test-server"

        result = await manager.add_server(duplicate_server)

        assert result is False
        mock_io.tool_warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_server_with_connect(self, mock_server, mock_io):
        manager = McpServerManager(servers=[], io=mock_io)

        # Mock connect_server to return True
        manager.connect_server = AsyncMock(return_value=True)

        result = await manager.add_server(mock_server, connect=True)

        assert result is True
        assert manager._servers == [mock_server]
        manager.connect_server.assert_called_once_with("test-server")

    def test_get_server_tools_found(self, mock_server):
        manager = McpServerManager(servers=[mock_server])
        tools = [{"name": "test_tool"}]
        manager._server_tools["test-server"] = tools

        result = manager.get_server_tools("test-server")

        assert result == tools

    def test_get_server_tools_not_found(self, mock_server):
        manager = McpServerManager(servers=[mock_server])

        result = manager.get_server_tools("nonexistent-server")

        assert result == []

    def test_all_tools_returns_copy(self, mock_server):
        manager = McpServerManager(servers=[mock_server])
        tools = {"test-server": [{"name": "test_tool"}]}
        manager._server_tools = tools

        result = manager.all_tools

        assert result == tools
        assert result is not tools  # Should be a copy

    @pytest.mark.asyncio
    async def test_from_servers_creates_manager(
        self, mock_server, mock_io, mock_tools, mock_session
    ):
        mock_server.connect.return_value = mock_session

        manager = await McpServerManager.from_servers(
            servers=[mock_server], io=mock_io, verbose=True
        )

        assert isinstance(manager, McpServerManager)
        assert manager._servers == [mock_server]
        assert mock_server in manager._connected_servers
        mock_server.connect.assert_called_once()
        mock_session.list_tools.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_from_servers_skips_disabled(self, mock_io):
        disabled_server = MagicMock(spec=McpServer)
        disabled_server.name = "disabled-server"
        disabled_server.config = {"name": "disabled-server", "enabled": False}
        disabled_server.connect = AsyncMock()

        manager = await McpServerManager.from_servers(servers=[disabled_server], io=mock_io)

        assert manager._servers == [disabled_server]
        assert disabled_server not in manager._connected_servers
        disabled_server.connect.assert_not_called()

    def test_manager_iteration(self, mock_server):
        manager = McpServerManager(servers=[mock_server])

        servers = list(manager)

        assert servers == [mock_server]
