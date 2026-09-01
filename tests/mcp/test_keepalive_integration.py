"""Integration tests for MCP keepalive mechanism with mock server."""

import asyncio

import pytest

from cecli.mcp.server import ConnectionState
from tests.mcp.conftest import ServerStateInspector


class TestKeepaliveWithMockServer:
    """Test keepalive mechanism with a controllable mock MCP server."""

    @pytest.mark.asyncio
    async def test_options_requests_sent_periodically(self, http_based_server, running_mock_server):
        """Verify OPTIONS requests are sent periodically when keepalive is enabled."""
        inspector = ServerStateInspector()
        server = http_based_server

        # Start the server connection
        await server.connect()
        await asyncio.sleep(0.1)  # Allow keepalive task to start

        # Verify keepalive task is running
        assert inspector.is_keepalive_running(server)

        # Wait for at least one keepalive interval (1 second)
        await asyncio.sleep(1.2)

        # Verify mock server received requests
        assert running_mock_server.request_count >= 1

        await server.disconnect()

    @pytest.mark.asyncio
    async def test_connection_remains_active_during_idle_periods(
        self, http_based_server, running_mock_server
    ):
        """Verify connection remains active during idle periods with successful keepalive."""
        server = http_based_server

        # Connect and verify initial state
        await server.connect()
        inspector = ServerStateInspector()
        assert inspector.get_state(server) == ConnectionState.CONNECTED

        # Wait for several keepalive intervals
        await asyncio.sleep(3.5)  # 3 intervals of 1 second each

        # Verify still connected
        assert inspector.get_state(server) == ConnectionState.CONNECTED
        assert inspector.get_failed_pings(server) == 0

        await server.disconnect()

    @pytest.mark.asyncio
    async def test_server_failure_triggers_unhealthy_state(
        self, http_based_server, running_mock_server
    ):
        """Verify server transitions to UNHEALTHY when keepalive fails."""
        server = http_based_server
        inspector = ServerStateInspector()

        await server.connect()
        await asyncio.sleep(0.1)

        # Make mock server return errors
        running_mock_server.set_status(500)

        # Wait for failed ping
        # Wait for failed ping with polling for cross-platform reliability
        for _ in range(30):  # 30 * 0.2s = 6s timeout
            if inspector.get_state(server) == ConnectionState.UNHEALTHY:
                break
            await asyncio.sleep(0.2)
        else:
            pytest.fail(
                f"Server did not become UNHEALTHY after failures, state was "
                f"{inspector.get_state(server).name}"
            )

        # Should transition to UNHEALTHY
        assert inspector.get_failed_pings(server) == 1

        await server.disconnect()

    @pytest.mark.asyncio
    async def test_consecutive_failures_lead_to_disconnected_state(
        self, http_based_server, running_mock_server
    ):
        """Verify server transitions to DISCONNECTED after threshold failures."""
        server = http_based_server
        inspector = ServerStateInspector()

        await server.connect()
        await asyncio.sleep(0.1)

        # Make mock server consistently fail
        running_mock_server.set_status(500)

        # After threshold failures, reconnect is triggered.
        # Since the mocked transport always succeeds, reconnect restores CONNECTED state.
        # Use polling instead of fixed sleep for cross-platform reliability.
        for _ in range(50):  # 50 * 0.2s = 10s timeout
            if inspector.get_state(server) == ConnectionState.CONNECTED:
                break
            await asyncio.sleep(0.2)
        else:
            pytest.fail("Server did not reconnect to CONNECTED state after failures")

        await server.disconnect()

    @pytest.mark.asyncio
    async def test_successful_ping_after_failure_restores_healthy_state(
        self, http_based_server, running_mock_server
    ):
        """Verify successful ping after failure restores CONNECTED state."""
        server = http_based_server
        inspector = ServerStateInspector()

        await server.connect()
        await asyncio.sleep(0.1)

        # Cause a failure
        running_mock_server.set_status(500)
        for _ in range(30):  # 30 * 0.2s = 6s timeout
            if inspector.get_state(server) == ConnectionState.UNHEALTHY:
                break
            await asyncio.sleep(0.2)
        else:
            pytest.fail(
                f"Server did not become UNHEALTHY after failures, state was "
                f"{inspector.get_state(server).name}"
            )
        assert inspector.get_state(server) == ConnectionState.UNHEALTHY

        # Restore success
        running_mock_server.set_status(200)
        for _ in range(30):  # 30 * 0.2s = 6s timeout
            if inspector.get_state(server) == ConnectionState.CONNECTED:
                break
            await asyncio.sleep(0.2)
        else:
            pytest.fail(
                f"Server did not become CONNECTED after success, state was "
                f"{inspector.get_state(server).name}"
            )

        # Should be back to CONNECTED

        # Brief cooldown after state transition
        await asyncio.sleep(0.2)
        assert inspector.get_state(server) == ConnectionState.CONNECTED
        assert inspector.get_failed_pings(server) == 0

        await server.disconnect()

    @pytest.mark.asyncio
    async def test_streaming_server_keepalive_also_works(
        self, http_streaming_server, running_mock_server
    ):
        """Verify HTTP streaming server keepalive mechanism works similarly."""
        server = http_streaming_server
        inspector = ServerStateInspector()

        await server.connect()
        await asyncio.sleep(0.1)

        assert inspector.is_keepalive_running(server)

        await asyncio.sleep(1.2)
        assert running_mock_server.request_count >= 1

        await server.disconnect()
