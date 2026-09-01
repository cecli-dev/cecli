"""Configuration validation tests for MCP keepalive mechanism."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cecli.mcp.manager import McpServerManager
from cecli.mcp.server import HttpStreamingServer
from tests.mcp.conftest import ServerStateInspector, _mock_transport_streams


class TestKeepaliveConfigurationValidation:
    """Test keepalive_interval configuration validation."""

    @pytest.fixture
    def mock_io(self):
        io = MagicMock()
        io.tool_output = MagicMock()
        io.tool_error = MagicMock()
        io.tool_warning = MagicMock()
        return io

    @pytest.fixture
    def mock_manager(self, mock_io):
        return McpServerManager(servers=[], io=mock_io)

    def test_keepalive_interval_below_minimum_rejected(self, mock_manager):
        """Configuration with keepalive_interval < MIN_KEEPALIVE_INTERVAL is rejected."""
        config = {
            "name": "test-server",
            "url": "http://localhost:8000",
            "type": "streamable_http",
            "keepalive_interval": 1,  # Below minimum of 5
            "enabled": True,
        }
        with pytest.raises(ValueError, match="keepalive_interval"):
            mock_manager._validate_server_config(config)

    def test_keepalive_interval_above_maximum_rejected(self, mock_manager):
        """Configuration with keepalive_interval > MAX_KEEPALIVE_INTERVAL is rejected."""
        config = {
            "name": "test-server",
            "url": "http://localhost:8000",
            "type": "streamable_http",
            "keepalive_interval": 400,  # Above maximum of 300
            "enabled": True,
        }
        with pytest.raises(ValueError, match="keepalive_interval"):
            mock_manager._validate_server_config(config)

    def test_keepalive_interval_non_integer_rejected(self, mock_manager):
        """Configuration with non-integer keepalive_interval is rejected."""
        config = {
            "name": "test-server",
            "url": "http://localhost:8000",
            "type": "streamable_http",
            "keepalive_interval": 5.5,
            "enabled": True,
        }
        with pytest.raises(ValueError, match="keepalive_interval"):
            mock_manager._validate_server_config(config)

    def test_keepalive_interval_valid_accepted(self, mock_manager):
        """Configuration with valid keepalive_interval is accepted."""
        config = {
            "name": "test-server",
            "url": "http://localhost:8000",
            "type": "streamable_http",
            "keepalive_interval": 15,
            "enabled": True,
        }
        # Should not raise
        validated = mock_manager._validate_server_config(config)
        assert validated["keepalive_interval"] == 15

    def test_keepalive_disabled_when_not_specified(self, mock_manager):
        """Server without keepalive_interval does not start keepalive task."""
        config = {
            "name": "test-server",
            "url": "http://localhost:8000",
            "type": "streamable_http",
            "enabled": True,
        }
        validated = mock_manager._validate_server_config(config)
        assert "keepalive_interval" not in validated or validated.get("keepalive_interval") is None

    @pytest.mark.asyncio
    async def test_auth_header_included_in_keepalive_request(
        self, mock_manager, running_mock_server
    ):
        """Authentication headers from server config are included in OPTIONS requests."""
        config = {
            "name": "test-server",
            "url": f"http://{running_mock_server.host}:{running_mock_server.port}",
            "type": "streamable_http",
            "keepalive_interval": 5,
            "headers": {"Authorization": "Bearer test-token"},
            "enabled": True,
        }

        server = HttpStreamingServer(config, io=MagicMock())
        server._create_oauth_provider = AsyncMock()

        with (
            patch("cecli.mcp.server.ClientSession") as MockSession,
            patch("cecli.mcp.server.streamable_http_client") as mock_transport,
            patch("cecli.mcp.server._get_http_client_module") as mock_get_http_module,
        ):
            # Setup mock HTTP client module to capture constructor args
            mock_http_client = AsyncMock()
            mock_http_module = MagicMock()
            mock_http_module.AsyncClient = MagicMock(return_value=mock_http_client)
            mock_get_http_module.return_value = mock_http_module

            # Setup mock session
            mock_session = AsyncMock()
            mock_session.initialize = AsyncMock()
            MockSession.return_value = mock_session

            # Setup mock transport with version-appropriate stream tuple
            mock_transport.return_value = AsyncMock()
            mock_transport.return_value.__aenter__ = AsyncMock(
                return_value=_mock_transport_streams()
            )

            await server.connect()
            await asyncio.sleep(0.2)  # Allow keepalive to run

            # Verify keepalive task is running
            inspector = ServerStateInspector()
            assert inspector.is_keepalive_running(server)

            # Static headers mean no OAuth provider should be created
            server._create_oauth_provider.assert_not_awaited()

            # Verify AsyncClient was created with the auth headers (and no auth)
            mock_http_module.AsyncClient.assert_called_once()
            call_kwargs = mock_http_module.AsyncClient.call_args.kwargs
            assert (
                "headers" in call_kwargs
            ), f"Expected 'headers' in AsyncClient kwargs, got: {list(call_kwargs.keys())}"
            assert call_kwargs["headers"] == {
                "Authorization": "Bearer test-token"
            }, f"Expected auth header, got: {call_kwargs['headers']}"
            assert (
                call_kwargs["auth"] is None
            ), f"Expected no auth when static headers are set, got: {call_kwargs['auth']}"

            await server.disconnect()
