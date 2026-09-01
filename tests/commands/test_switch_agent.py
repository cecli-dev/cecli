from unittest.mock import MagicMock, patch

import pytest

from cecli.commands.switch_agent import SwitchAgentCommand


@pytest.fixture
def mock_coder():
    coder = MagicMock()
    coder.uuid = "primary-uuid"
    return coder


@pytest.fixture
def mock_io():
    io = MagicMock()
    io.output_queue = MagicMock()
    return io


@pytest.fixture
def mock_agent_service(mock_coder):
    with patch("cecli.commands.switch_agent.AgentService") as MockAgentService:
        agent_service_instance = MockAgentService.get_instance.return_value

        reviewer = MagicMock()
        reviewer.name = "reviewer"

        agent_service_instance.sub_agents = {
            "sub-uuid-1": reviewer,
        }
        agent_service_instance.foreground_uuid = None
        yield agent_service_instance


class TestSwitchAgentCommand:
    @pytest.mark.asyncio
    async def test_execute_switch_to_sub_agent_tui(self, mock_coder, mock_io, mock_agent_service):
        """Test switching to a sub-agent in TUI mode."""
        mock_io.output_queue.put = MagicMock()

        with patch("cecli.commands.switch_agent.hasattr", return_value=True):
            await SwitchAgentCommand.execute(mock_io, mock_coder, "reviewer")

        mock_io.output_queue.put.assert_called_once_with(
            {"type": "switch_agent", "uuid": "sub-uuid-1"}
        )

    @pytest.mark.asyncio
    async def test_execute_switch_to_primary_tui(self, mock_coder, mock_io, mock_agent_service):
        """Test switching back to the primary agent in TUI mode."""
        mock_agent_service.foreground_uuid = "sub-uuid-1"
        mock_io.output_queue.put = MagicMock()

        with patch("cecli.commands.switch_agent.hasattr", return_value=True):
            await SwitchAgentCommand.execute(mock_io, mock_coder, "primary")

        mock_io.output_queue.put.assert_called_once_with(
            {"type": "switch_agent", "uuid": "primary-uuid"}
        )

    @pytest.mark.asyncio
    async def test_execute_agent_not_found(self, mock_coder, mock_io, mock_agent_service):
        """Test error handling when agent is not found."""
        await SwitchAgentCommand.execute(mock_io, mock_coder, "non-existent-agent")
        mock_io.tool_error.assert_called_once_with("Error: Agent 'non-existent-agent' not found.")

    @pytest.mark.asyncio
    async def test_execute_switch_by_uuid_prefix_tui(self, mock_coder, mock_io, mock_agent_service):
        """Test switching to a sub-agent by first 3 UUID chars in TUI mode."""
        mock_io.output_queue.put = MagicMock()

        with patch("cecli.commands.switch_agent.hasattr", return_value=True):
            await SwitchAgentCommand.execute(mock_io, mock_coder, "sub")

        mock_io.output_queue.put.assert_called_once_with(
            {"type": "switch_agent", "uuid": "sub-uuid-1"}
        )

    def test_get_completions_on_primary(self, mock_coder, mock_io, mock_agent_service):
        """Test completions when the primary agent is active."""
        mock_agent_service.foreground_uuid = None
        completions = SwitchAgentCommand.get_completions(mock_io, mock_coder, "")
        assert "reviewer" in completions
        assert "primary" not in completions

    def test_get_completions_on_sub_agent(self, mock_coder, mock_io, mock_agent_service):
        """Test completions when a sub-agent is active."""
        mock_agent_service.foreground_uuid = "sub-uuid-1"
        completions = SwitchAgentCommand.get_completions(mock_io, mock_coder, "")
        assert "primary" in completions
        assert "reviewer" not in completions

    def test_get_completions_with_partial_arg(self, mock_coder, mock_io, mock_agent_service):
        """Test completions with a partial argument."""
        mock_agent_service.foreground_uuid = None
        completions = SwitchAgentCommand.get_completions(mock_io, mock_coder, "rev")
        assert completions == ["reviewer"]

    def test_get_completions_with_duplicate_names(self, mock_coder, mock_io, mock_agent_service):
        """Test completions include UUID prefixes when there are duplicate names."""
        # Add a second sub-agent with the same name
        second_reviewer = MagicMock()
        second_reviewer.name = "reviewer"
        mock_agent_service.sub_agents["sub-uuid-2"] = second_reviewer
        mock_agent_service.foreground_uuid = None
        completions = SwitchAgentCommand.get_completions(mock_io, mock_coder, "")
        assert "reviewer (sub)" in completions
        assert len([c for c in completions if c.startswith("reviewer")]) == 2
