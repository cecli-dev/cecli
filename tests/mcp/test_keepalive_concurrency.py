"""Concurrency tests for MCP keepalive task lifecycle."""

import asyncio

import pytest

from cecli.mcp.server import HttpBasedMcpServer
from tests.mcp.conftest import ServerStateInspector, _mock_transport_streams


class TestKeepaliveTaskLifecycle:
    """Test keepalive task creation, cancellation, and isolation."""

    @pytest.mark.asyncio
    async def test_keepalive_task_started_on_connect(self, http_based_server):
        """Keepalive task is started when server connects."""
        inspector = ServerStateInspector()
        server = http_based_server

        # Initially no task
        assert inspector.get_keepalive_task(server) is None
        assert not inspector.is_keepalive_running(server)

        # Connect server
        await server.connect()

        # Task should be created and running
        task = inspector.get_keepalive_task(server)
        assert task is not None
        assert isinstance(task, asyncio.Task)
        assert inspector.is_keepalive_running(server)

        # Cleanup
        await server.disconnect()

    @pytest.mark.asyncio
    async def test_keepalive_task_cancelled_on_disconnect(self, http_based_server):
        """Keepalive task is cancelled when server disconnects."""
        inspector = ServerStateInspector()
        server = http_based_server

        # Connect and verify task is running
        await server.connect()
        assert inspector.is_keepalive_running(server)
        task_before = inspector.get_keepalive_task(server)

        # Disconnect server
        await server.disconnect()

        # Task should be cancelled
        assert task_before.cancelled() or task_before.done()
        assert (
            inspector.get_keepalive_task(server) is None
            or inspector.get_keepalive_task(server).done()
        )
        assert not inspector.is_keepalive_running(server)

    @pytest.mark.asyncio
    async def test_multiple_connect_disconnect_cycles(self, http_based_server):
        """Server can handle multiple connect/disconnect cycles without task accumulation."""
        inspector = ServerStateInspector()
        server = http_based_server

        tasks_seen = []

        for i in range(3):
            await server.connect()
            assert inspector.is_keepalive_running(server)
            task = inspector.get_keepalive_task(server)
            tasks_seen.append(task)

            await server.disconnect()
            assert not inspector.is_keepalive_running(server)

        # All tasks should be done or cancelled
        for task in tasks_seen:
            assert task.done() or task.cancelled()

    @pytest.mark.asyncio
    async def test_keepalive_task_does_not_block_other_operations(
        self, http_based_server, running_mock_server
    ):
        """Keepalive task runs in background and doesn't block server operations."""
        inspector = ServerStateInspector()
        server = http_based_server

        # Connect and verify keepalive starts
        await server.connect()
        assert inspector.is_keepalive_running(server)

        # Perform other operations while keepalive runs
        # These should not be blocked by the keepalive task

        # Check connection status multiple times
        for _ in range(5):
            assert server.session is not None  # Local check
            await asyncio.sleep(0.01)

        # Change configuration (if supported)
        # This tests that the event loop is not blocked

        await asyncio.sleep(0.1)  # Let keepalive do its work

        # Verify we can still disconnect cleanly
        await server.disconnect()
        assert not inspector.is_keepalive_running(server)

    @pytest.mark.asyncio
    async def test_no_keepalive_task_when_disabled(self, http_server_config, mock_io):
        """No keepalive task is created when keepalive_interval is not specified."""
        # Remove keepalive_interval from config
        config = http_server_config.copy()
        config.pop("keepalive_interval", None)

        inspector = ServerStateInspector()
        server = HttpBasedMcpServer(config, io=mock_io)
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_transport = AsyncMock()
        mock_transport.__aenter__ = AsyncMock(return_value=_mock_transport_streams())
        server._create_transport = MagicMock(return_value=mock_transport)
        server._create_oauth_provider = AsyncMock(return_value=None)
        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session_class = MagicMock(return_value=mock_session)
        server._session_patch = patch("cecli.mcp.server.ClientSession", mock_session_class)
        server._session_patch.start()

        # Connect server
        await server.connect()

        # Should not have a keepalive task
        assert inspector.get_keepalive_task(server) is None
        assert not inspector.is_keepalive_running(server)

        await server.disconnect()
