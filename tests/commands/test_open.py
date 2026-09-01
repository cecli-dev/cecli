from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cecli.commands.open import OpenCommand


@pytest.fixture
def mock_coder():
    coder = MagicMock()
    coder.uuid = "primary-uuid"
    coder.tui = None
    return coder


@pytest.fixture
def mock_io():
    io = MagicMock()
    return io


@pytest.fixture
def mock_agent_service():
    with patch("cecli.commands.open.AgentService") as MockAgentService:
        agent_service = MockAgentService.get_instance.return_value
        MockAgentService.get_registry.return_value = {
            "ws:app": MagicMock(metadata={"root": "/abs/app"})
        }
        yield agent_service


class TestOpenCommand:
    @pytest.mark.asyncio
    async def test_execute_missing_args(self, mock_coder, mock_io):
        await OpenCommand.execute(mock_io, mock_coder, "")
        mock_io.tool_error.assert_called_once_with("Usage: /open <name> <path>")

    @pytest.mark.asyncio
    async def test_execute_invalid_path(self, mock_coder, mock_io):
        with patch("cecli.commands.open.register_workspace_subagents", return_value=[]):
            await OpenCommand.execute(mock_io, mock_coder, "app /no/such/path")

        open_path = Path("/no/such/path").expanduser()
        mock_io.tool_error.assert_called_once_with(
            f"Error: '{open_path}' is not a valid git repository or does not exist."
        )

    @pytest.mark.asyncio
    async def test_execute_success_non_tui(self, mock_coder, mock_io, mock_agent_service):
        info = MagicMock()
        info.coder.uuid = "sub-uuid-1"
        mock_agent_service.spawn = AsyncMock(return_value=(MagicMock(), info))

        with patch("cecli.commands.open.register_workspace_subagents", return_value=["ws:app"]):
            await OpenCommand.execute(mock_io, mock_coder, "app /abs/app")

        # spawn is non-blocking with no prompt; the sub-agent becomes the foreground agent.
        mock_agent_service.spawn.assert_awaited_once_with(
            "ws:app", prompt=None, parent=mock_coder, auto_reap=False, independent=True
        )
        assert mock_agent_service.foreground_uuid == "sub-uuid-1"
        mock_io.tool_output.assert_called_once_with(
            "Opened workspace sub-agent 'ws:app' rooted at /abs/app."
        )

    @pytest.mark.asyncio
    async def test_execute_success_tui(self, mock_coder, mock_io, mock_agent_service):
        tui = MagicMock()
        tui.get_keys_for.return_value = "<next_agent>"
        mock_coder.tui = MagicMock(return_value=tui)

        info = MagicMock()
        info.coder.uuid = "sub-uuid-1"
        mock_agent_service.spawn = AsyncMock(return_value=(MagicMock(), info))

        with patch("cecli.commands.open.register_workspace_subagents", return_value=["ws:app"]):
            await OpenCommand.execute(mock_io, mock_coder, "app /abs/app")

        tui.call_from_thread.assert_called_once_with(tui._switch_to_container, "sub-uuid-1")
        mock_io.tool_output.assert_called_once_with(
            "Opened workspace sub-agent 'ws:app' rooted at /abs/app. Switch with <next_agent>"
        )

    @pytest.mark.asyncio
    async def test_execute_ws_prefix(self, mock_coder, mock_io, mock_agent_service):
        info = MagicMock()
        info.coder.uuid = "sub-uuid-1"
        mock_agent_service.spawn = AsyncMock(return_value=(MagicMock(), info))

        with patch("cecli.commands.open.register_workspace_subagents", return_value=["ws:app"]):
            await OpenCommand.execute(mock_io, mock_coder, "ws:app /abs/app")

        mock_agent_service.spawn.assert_awaited_once_with(
            "ws:app", prompt=None, parent=mock_coder, auto_reap=False, independent=True
        )

    @pytest.mark.asyncio
    async def test_execute_spawn_error(self, mock_coder, mock_io, mock_agent_service):
        mock_agent_service.spawn = AsyncMock(side_effect=RuntimeError("boom"))

        with patch("cecli.commands.open.register_workspace_subagents", return_value=["ws:app"]):
            await OpenCommand.execute(mock_io, mock_coder, "app /abs/app")

        mock_io.tool_error.assert_called_once_with(
            "Error opening workspace sub-agent 'ws:app': boom"
        )

    def test_get_help(self):
        assert "(/open <name> <path>)" in OpenCommand.get_help()

    def test_get_completions(self):
        with patch("cecli.commands.open.AgentService") as MockAgentService:
            MockAgentService.get_registry.return_value = {
                "ws:app": MagicMock(),
                "worker": MagicMock(),
            }
            assert OpenCommand.get_completions(MagicMock(), MagicMock(), "") == ["ws:app"]
