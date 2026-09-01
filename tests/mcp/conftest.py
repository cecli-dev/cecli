from typing import Any, AsyncGenerator, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest

# Allow short keepalive intervals in tests
import cecli.mcp.server as mcp_server
from cecli.mcp.server import HttpBasedMcpServer, HttpStreamingServer
from tests.mcp.mock_server import MockMcpServer

mcp_server.MIN_KEEPALIVE_INTERVAL = 1


@pytest.fixture
def mock_mcp_server() -> MockMcpServer:
    """Fixture providing a mock MCP server instance."""
    server = MockMcpServer()
    return server


@pytest.fixture
async def running_mock_server(mock_mcp_server) -> AsyncGenerator[MockMcpServer, None]:
    """Fixture providing a running mock MCP server."""
    await mock_mcp_server.start()
    yield mock_mcp_server
    await mock_mcp_server.stop()


@pytest.fixture
def http_server_config(running_mock_server) -> Dict[str, Any]:
    """Fixture providing a basic HTTP server configuration."""
    return {
        "name": "test-server",
        "url": f"http://{running_mock_server.host}:{running_mock_server.port}",
        "type": "http",
        "keepalive_interval": 1,  # 1 second for fast tests
        "headers": {},
        "enabled": True,
    }


@pytest.fixture
def http_streaming_server_config(running_mock_server) -> Dict[str, Any]:
    """Fixture providing an HTTP streaming server configuration."""
    return {
        "name": "test-streaming-server",
        "url": f"http://{running_mock_server.host}:{running_mock_server.port}",
        "type": "streamable_http",
        "keepalive_interval": 1,
        "headers": {},
        "enabled": True,
    }


@pytest.fixture
def mock_io():
    """Fixture providing a mock IO object."""
    io = MagicMock()
    io.tool_output = MagicMock()
    io.tool_error = MagicMock()
    io.tool_warning = MagicMock()
    return io


@pytest.fixture
def http_based_server(http_server_config, mock_io) -> HttpBasedMcpServer:
    """Fixture providing an HttpBasedMcpServer instance with mocked transport."""
    server = HttpBasedMcpServer(http_server_config, io=mock_io)
    # Mock transport layer: _create_transport needs to return an async context manager
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_transport = AsyncMock()
    mock_transport.__aenter__ = AsyncMock(return_value=_mock_transport_streams())
    server._create_transport = MagicMock(return_value=mock_transport)
    # Mock OAuth provider to avoid creating OAuth callback server
    server._create_oauth_provider = AsyncMock(return_value=None)
    # Mock ClientSession to avoid real MCP protocol communication
    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock()
    mock_session_class = MagicMock(return_value=mock_session)
    server._session_patch = patch("cecli.mcp.server.ClientSession", mock_session_class)
    server._session_patch.start()
    return server


@pytest.fixture
def http_streaming_server(http_streaming_server_config, mock_io) -> HttpStreamingServer:
    """Fixture providing an HttpStreamingServer instance."""
    server = HttpStreamingServer(http_streaming_server_config, io=mock_io)
    # Mock transport layer
    from unittest.mock import AsyncMock

    mock_transport = AsyncMock()
    mock_transport.__aenter__ = AsyncMock(return_value=_mock_transport_streams())
    server._create_transport = MagicMock(return_value=mock_transport)
    # Mock OAuth provider
    server._create_oauth_provider = AsyncMock(return_value=None)
    # Mock ClientSession to avoid real MCP protocol communication
    from unittest.mock import patch

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock()
    mock_session_class = MagicMock(return_value=mock_session)
    server._session_patch = patch("cecli.mcp.server.ClientSession", mock_session_class)
    server._session_patch.start()
    return server


# Test utilities for inspecting internal state
class ServerStateInspector:
    """Utility class to inspect internal state of HttpBasedMcpServer for testing."""

    @staticmethod
    def get_state(server: HttpBasedMcpServer):
        """Get the connection state of the server."""
        return server._state

    @staticmethod
    def get_failed_pings(server: HttpBasedMcpServer):
        """Get the number of failed pings."""
        return server._failed_pings

    @staticmethod
    def get_keepalive_task(server: HttpBasedMcpServer):
        """Get the keepalive task."""
        return server._keepalive_task

    @staticmethod
    def is_keepalive_running(server: HttpBasedMcpServer):
        """Check if the keepalive task is running."""
        task = server._keepalive_task
        return task is not None and not task.done()


@pytest.fixture
def server_inspector():
    """Fixture providing a server state inspector."""
    return ServerStateInspector()


def _mock_transport_streams():
    """Return transport streams matching the installed mcp SDK version.

    mcp SDK 1.x yields (read, write, session_id_getter); SDK 2.x yields
    (read, write).
    """
    mock_read = AsyncMock()
    mock_write = AsyncMock()

    if mcp_server._get_mcp_major_version() >= 2:
        return mock_read, mock_write

    return mock_read, mock_write, None
