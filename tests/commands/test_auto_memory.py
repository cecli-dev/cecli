"""Tests for the /auto-memory command."""

from unittest.mock import MagicMock, patch

import pytest

from cecli.commands.auto_memory import AutoMemoryCommand


class _BoomCoder:
    """Coder that raises when ``auto_memory`` is assigned."""

    def __setattr__(self, name, value):
        if name == "auto_memory":
            raise Exception("boom")

        super().__setattr__(name, value)


@pytest.fixture
def mock_coder():
    coder = MagicMock()
    coder.auto_memory = True
    return coder


@pytest.fixture
def mock_io():
    return MagicMock()


class TestAutoMemoryCommand:
    @pytest.mark.asyncio
    async def test_execute_no_args_shows_status(self, mock_coder, mock_io):
        """Running with no arguments displays the current status."""
        with patch.object(AutoMemoryCommand, "_get_sub_agent_infos", return_value=[]):
            result = await AutoMemoryCommand.execute(mock_io, mock_coder, "")

        mock_io.tool_output.assert_any_call("Auto memory is ON for the current coder.")
        assert result == "Successfully executed auto-memory."

    @pytest.mark.asyncio
    async def test_execute_on_enables(self, mock_coder, mock_io):
        """'on' enables auto memory for the coder."""
        with patch.object(AutoMemoryCommand, "_get_sub_agent_infos", return_value=[]):
            result = await AutoMemoryCommand.execute(mock_io, mock_coder, "on")

        assert mock_coder.auto_memory is True
        mock_io.tool_output.assert_any_call(
            "Auto memory is now ON for the current coder and 0 sub-agent(s)."
        )
        assert result == "Successfully executed auto-memory."

    @pytest.mark.asyncio
    async def test_execute_off_disables(self, mock_coder, mock_io):
        """'off' disables auto memory for the coder."""
        with patch.object(AutoMemoryCommand, "_get_sub_agent_infos", return_value=[]):
            result = await AutoMemoryCommand.execute(mock_io, mock_coder, "off")

        assert mock_coder.auto_memory is False
        mock_io.tool_output.assert_any_call(
            "Auto memory is now OFF for the current coder and 0 sub-agent(s)."
        )
        assert result == "Successfully executed auto-memory."

    @pytest.mark.asyncio
    async def test_execute_invalid_arg(self, mock_coder, mock_io):
        """An unrecognised option shows usage and reports an error."""
        result = await AutoMemoryCommand.execute(mock_io, mock_coder, "maybe")

        mock_io.tool_error.assert_any_call("Usage: /auto-memory [on|off]")
        assert result == "Error: Expected 'on' or 'off', got 'maybe'"

    @pytest.mark.asyncio
    async def test_execute_on_propagates_to_sub_agents(self, mock_coder, mock_io):
        """'on' propagates the setting to every tracked sub-agent coder."""
        sub_info_1 = MagicMock()
        sub_info_1.coder = MagicMock()
        sub_info_2 = MagicMock()
        sub_info_2.coder = MagicMock()

        with patch.object(
            AutoMemoryCommand, "_get_sub_agent_infos", return_value=[sub_info_1, sub_info_2]
        ):
            result = await AutoMemoryCommand.execute(mock_io, mock_coder, "on")

        assert mock_coder.auto_memory is True
        assert sub_info_1.coder.auto_memory is True
        assert sub_info_2.coder.auto_memory is True
        mock_io.tool_output.assert_any_call(
            "Auto memory is now ON for the current coder and 2 sub-agent(s)."
        )
        assert result == "Successfully executed auto-memory."

    def test_get_completions(self, mock_coder, mock_io):
        """Completions offer on/off."""
        assert AutoMemoryCommand.get_completions(mock_io, mock_coder, "") == ["on", "off"]

    def test_get_help(self):
        """Help text documents usage."""
        help_text = AutoMemoryCommand.get_help()

        assert "/auto-memory" in help_text
        assert "on" in help_text
        assert "off" in help_text

    def test_show_status_with_sub_agents(self, mock_coder, mock_io):
        """Status lists each sub-agent and its current state."""
        sub_info = MagicMock()
        sub_info.name = "worker"
        sub_info.coder.uuid = "sub-uuid"
        sub_info.coder.auto_memory = False

        with patch.object(AutoMemoryCommand, "_get_sub_agent_infos", return_value=[sub_info]):
            AutoMemoryCommand._show_status(mock_io, mock_coder)

        mock_io.tool_output.assert_any_call("Auto memory is ON for the current coder.")
        mock_io.tool_output.assert_any_call("Sub-agents (1):")
        mock_io.tool_output.assert_any_call("  worker (sub-uuid): OFF")

    def test_set_auto_memory_propagates_to_sub_agents(self, mock_coder):
        """_set_auto_memory updates the coder and all sub-agents."""
        sub_info = MagicMock()
        sub_info.coder = MagicMock()

        with patch.object(AutoMemoryCommand, "_get_sub_agent_infos", return_value=[sub_info]):
            updated = AutoMemoryCommand._set_auto_memory(mock_coder, enabled=False)

        assert mock_coder.auto_memory is False
        assert sub_info.coder.auto_memory is False
        assert updated == [sub_info]

    def test_set_auto_memory_skips_failed_sub_agents(self, mock_coder):
        """Sub-agents that raise when updated are skipped, not fatal."""
        sub_info = MagicMock()
        sub_info.coder = _BoomCoder()

        with patch.object(AutoMemoryCommand, "_get_sub_agent_infos", return_value=[sub_info]):
            updated = AutoMemoryCommand._set_auto_memory(mock_coder, enabled=True)

        assert updated == []

    def test_get_sub_agent_infos_returns_sub_agents(self, mock_coder):
        """Sub-agent infos come from the coder's AgentService."""
        sub_info = MagicMock()

        with patch("cecli.commands.auto_memory.AgentService") as mock_service:
            mock_service.get_instance.return_value.sub_agents = {"sub-uuid": sub_info}

            infos = AutoMemoryCommand._get_sub_agent_infos(mock_coder)

        assert infos == [sub_info]

    def test_get_sub_agent_infos_returns_empty_on_error(self, mock_coder):
        """A failing AgentService lookup yields no sub-agent infos."""
        with patch(
            "cecli.commands.auto_memory.AgentService.get_instance",
            side_effect=RuntimeError("no service"),
        ):
            infos = AutoMemoryCommand._get_sub_agent_infos(mock_coder)

        assert infos == []
