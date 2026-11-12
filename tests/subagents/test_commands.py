"""
Tests for sub-agent commands: invoke_agent, spawn_agent, reap_agent.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSpawnAgentCommand:
    """Tests for SpawnAgentCommand."""

    @pytest.mark.asyncio
    async def test_no_args_shows_usage(self):
        """Empty args shows usage error."""
        from cecli.commands.spawn_agent import SpawnAgentCommand

        io = MagicMock()
        await SpawnAgentCommand.execute(io, None, "")

        io.tool_error.assert_called_once()
        assert "Usage" in io.tool_error.call_args[0][0]

    @pytest.mark.asyncio
    async def test_valid_name_calls_spawn(self):
        """Valid name calls agent_service.spawn."""
        from cecli.commands.spawn_agent import SpawnAgentCommand

        io = MagicMock()
        coder = MagicMock()

        with patch("cecli.helpers.agents.service.AgentService") as MockSvc:
            mock_instance = MagicMock()
            mock_instance.spawn = AsyncMock(return_value=(MagicMock(), MagicMock()))
            MockSvc.get_instance.return_value = mock_instance

            await SpawnAgentCommand.execute(io, coder, "reviewer")

        mock_instance.spawn.assert_called_once_with(
            "reviewer", None, parent=coder, auto_reap=False, independent=True
        )
        io.tool_output.assert_called_once()
        assert "spawned" in io.tool_output.call_args[0][0]

    @pytest.mark.asyncio
    async def test_value_error_shown(self):
        """ValueError shown via tool_error."""
        from cecli.commands.spawn_agent import SpawnAgentCommand

        io = MagicMock()
        coder = MagicMock()

        with patch("cecli.helpers.agents.service.AgentService") as MockSvc:
            mock_instance = MagicMock()
            mock_instance.spawn = AsyncMock(side_effect=ValueError("unknown"))
            MockSvc.get_instance.return_value = mock_instance

            await SpawnAgentCommand.execute(io, coder, "ghost")

        io.tool_error.assert_called()
        assert "unknown" in io.tool_error.call_args[0][0]


class TestReapAgentCommand:
    """Tests for ReapAgentCommand."""

    @pytest.mark.asyncio
    async def test_no_tui_shows_error(self):
        """No TUI and no active/foreground sub-agent shows the error."""
        from cecli.commands.reap_agent import ReapAgentCommand
        from cecli.helpers.agents.service import AgentService

        io = MagicMock()
        coder = MagicMock()
        coder.tui = None
        coder.parent_uuid = None

        mock_service = MagicMock()
        mock_service.foreground_uuid = None
        mock_service.sub_agents = {}

        with patch.object(AgentService, "get_instance", return_value=mock_service):
            await ReapAgentCommand.execute(io, coder, "")

        io.tool_error.assert_called_once()
        assert "No active" in io.tool_error.call_args[0][0]

    @pytest.mark.asyncio
    async def test_valid_reap_cleans_up(self):
        """Valid reap calls destroy_instances and _cleanup_sub_agent."""
        from cecli.commands.reap_agent import ReapAgentCommand
        from cecli.helpers.agents.service import AgentService

        io = MagicMock()

        mock_tui = MagicMock()
        mock_tui._get_visible_coder.return_value.uuid = "sub-uuid"

        coder = MagicMock()
        coder.tui = mock_tui

        mock_info = MagicMock()
        mock_info.coder.uuid = "sub-uuid"

        mock_service = MagicMock()
        mock_service.sub_agents = {"tester": mock_info}

        with patch.object(AgentService, "get_instance", return_value=mock_service):
            with patch(
                "cecli.helpers.conversation.service.ConversationService.destroy_instances"
            ) as MockDestroy:
                await ReapAgentCommand.execute(io, coder, "")

        MockDestroy.assert_called_once_with("sub-uuid")
        mock_service._cleanup_sub_agent.assert_called_once_with("sub-uuid")
        io.tool_output.assert_called_once()
        assert "reaped" in io.tool_output.call_args[0][0]

    @pytest.mark.asyncio
    async def test_uuid_not_found_shows_error(self):
        """Active UUID not in sub_agents shows error."""
        from cecli.commands.reap_agent import ReapAgentCommand
        from cecli.helpers.agents.service import AgentService

        io = MagicMock()

        mock_tui = MagicMock()
        mock_tui._get_visible_coder.return_value.uuid = "unknown-uuid"

        coder = MagicMock()
        coder.tui = mock_tui

        mock_service = MagicMock()
        mock_service.sub_agents = {}  # empty

        with patch.object(AgentService, "get_instance", return_value=mock_service):
            await ReapAgentCommand.execute(io, coder, "")

        io.tool_error.assert_called_once()
        assert "Could not find" in io.tool_error.call_args[0][0]

    @pytest.mark.asyncio
    async def test_no_tui_uses_foreground_agent(self):
        """Without a TUI, the service's foreground sub-agent is reaped."""
        from cecli.commands.reap_agent import ReapAgentCommand
        from cecli.helpers.agents.service import AgentService

        io = MagicMock()
        coder = MagicMock()
        coder.tui = None
        coder.parent_uuid = None

        mock_info = MagicMock()
        mock_info.coder.uuid = "sub-uuid"
        mock_info.name = "tester"

        mock_service = MagicMock()
        mock_service.foreground_uuid = "sub-uuid"
        mock_service.sub_agents = {"sub-uuid": mock_info}

        with patch.object(AgentService, "get_instance", return_value=mock_service):
            with patch(
                "cecli.helpers.conversation.service.ConversationService.destroy_instances"
            ) as MockDestroy:
                await ReapAgentCommand.execute(io, coder, "")

        MockDestroy.assert_called_once_with("sub-uuid")
        mock_service._cleanup_sub_agent.assert_called_once_with("sub-uuid")
        assert "tester" in io.tool_output.call_args[0][0]

    @pytest.mark.asyncio
    async def test_no_tui_inside_sub_agent_reaps_itself(self):
        """A bare reap run inside a sub-agent targets that sub-agent."""
        from cecli.commands.reap_agent import ReapAgentCommand
        from cecli.helpers.agents.service import AgentService

        io = MagicMock()
        coder = MagicMock()
        coder.tui = None
        coder.uuid = "sub-uuid"
        coder.parent_uuid = "primary-uuid"

        mock_info = MagicMock()
        mock_info.coder.uuid = "sub-uuid"
        mock_info.name = "tester"

        mock_service = MagicMock()
        mock_service.foreground_uuid = None
        mock_service.sub_agents = {"sub-uuid": mock_info}

        with patch.object(AgentService, "get_instance", return_value=mock_service):
            with patch(
                "cecli.helpers.conversation.service.ConversationService.destroy_instances"
            ) as MockDestroy:
                await ReapAgentCommand.execute(io, coder, "")

        MockDestroy.assert_called_once_with("sub-uuid")
        mock_service._cleanup_sub_agent.assert_called_once_with("sub-uuid")
