"""Resilience tests for MCP keepalive mechanism."""

import asyncio
from unittest.mock import patch

import pytest

from cecli.mcp.server import ConnectionState
from tests.mcp.conftest import ServerStateInspector


class TestKeepaliveResilience:
    """Test keepalive mechanism resilience under various conditions."""

    @pytest.mark.asyncio
    async def test_temporary_disconnection_recovery(self, http_based_server, running_mock_server):
        """Verify server recovers from temporary disconnection."""
        inspector = ServerStateInspector()
        server = http_based_server

        await server.connect()
        await asyncio.sleep(0.1)

        # Simulate temporary disconnection
        running_mock_server.trigger_disconnect()
        await asyncio.sleep(1.2)  # Wait for failed ping

        # Should be UNHEALTHY after first failure
        assert inspector.get_state(server) == ConnectionState.UNHEALTHY
        assert inspector.get_failed_pings(server) == 1

        # Restore server
        running_mock_server.reset()
        running_mock_server.set_status(200)
        await asyncio.sleep(1.2)  # Wait for successful ping

        # Should recover to CONNECTED
        assert inspector.get_state(server) == ConnectionState.CONNECTED
        assert inspector.get_failed_pings(server) == 0

        await server.disconnect()

    @pytest.mark.asyncio
    async def test_slow_responses_handled_gracefully(self, http_based_server, running_mock_server):
        """Verify keepalive continues to function with slow server responses."""
        inspector = ServerStateInspector()
        server = http_based_server

        await server.connect()
        await asyncio.sleep(0.1)

        # Set delay longer than keepalive interval but not excessive
        running_mock_server.set_delay(0.8)  # 0.8s delay vs 1s interval

        # Wait for multiple intervals
        await asyncio.sleep(3.0)

        # Should still be functioning and task should be alive
        assert inspector.get_keepalive_task(server) is not None

        await server.disconnect()

    @pytest.mark.asyncio
    async def test_keepalive_jitter_prevents_timing_analysis(self, http_based_server):
        """Verify keepalive intervals incorporate jitter."""
        server = http_based_server
        sleep_durations = []

        original_sleep = asyncio.sleep

        async def mock_sleep(duration):
            sleep_durations.append(duration)
            await original_sleep(0)  # Yield to event loop

        await server.connect()

        with patch("asyncio.sleep", side_effect=mock_sleep):
            # Let keepalive loop run a few iterations
            await original_sleep(3.5)  # Use original sleep to avoid recording test's own wait

        await server.disconnect()

        # Verify we captured sleep durations
        assert len(sleep_durations) >= 2, f"Expected >= 2 sleep calls, got {len(sleep_durations)}"

        # Verify jitter exists - durations should not all be identical
        assert len(set(sleep_durations)) > 1, "Sleep durations should vary due to jitter"

        # Verify durations fall within +/-10% of configured interval
        interval = server.config.get("keepalive_interval", 1)
        for duration in sleep_durations:
            assert (
                0.9 * interval <= duration <= 1.1 * interval
            ), f"Duration {duration} outside +/-10% jitter range"

    @pytest.mark.asyncio
    async def test_reconnection_after_persistent_failure(
        self, http_based_server, running_mock_server
    ):
        """Verify keepalive handles persistent failures gracefully."""
        server = http_based_server
        server.config["keepalive_interval"] = 1
        running_mock_server.set_status(500)

        reconnect_delays = []

        original_sleep = asyncio.sleep

        async def mock_sleep(duration):
            reconnect_delays.append(duration)
            if duration > 0.5:
                await original_sleep(0)  # Yield to event loop
                return

        # Connect inside the patched section so keepalive's first asyncio.sleep
        # goes through the mock (instead of being a real 1s sleep)
        with patch("asyncio.sleep", side_effect=mock_sleep):
            await server.connect()
            # Yield control to the keepalive task multiple times
            for _ in range(200):
                await original_sleep(0)

        await server.disconnect()

        # Filter for reconnect delay calls (values between 0.5 and 301 seconds)
        delays = [d for d in reconnect_delays if 0.5 < d < 301]

        assert len(delays) >= 2, f"Expected >= 2 sleep calls, got {len(delays)}"

        # Verify delays are capped at max_delay (300s)
        for delay in delays:
            assert delay <= 300, f"Delay {delay} exceeds max_delay of 300"
