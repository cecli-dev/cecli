"""
Tests for cecli/tools/finished.py — Finished tool sub-agent integration.
"""

from unittest.mock import MagicMock, patch

import pytest


class TestFinishedTool:
    """Tests for the Yield tool sub-agent behavior."""

    @pytest.mark.asyncio
    async def test_sets_agent_finished_on_coder(self):
        """Sets coder.agent_finished = True."""
        from cecli.tools._yield import Tool

        mock_coder = MagicMock()
        mock_coder.uuid = "test-uuid"
        mock_coder.parent_uuid = ""
        mock_coder.files_edited_by_tools = set()

        _ = await Tool.execute(mock_coder)

        assert mock_coder.agent_finished is True

    @pytest.mark.asyncio
    async def test_sub_agent_with_summary_updates_info(self):
        """Sub-agent with summary updates SubAgentInfo.summary and status."""
        from cecli.helpers.agents.service import AgentService, SubAgentStatus
        from cecli.tools._yield import Tool

        mock_coder = MagicMock()
        mock_coder.uuid = "sub-uuid"
        mock_coder.parent_uuid = "parent-uuid"
        mock_coder.files_edited_by_tools = set()
        mock_coder.turn_count = 0

        mock_info = MagicMock()
        mock_info.coder.uuid = "sub-uuid"
        mock_info.summary = None
        mock_info.status = SubAgentStatus.RUNNING

        mock_service = MagicMock()
        mock_service.sub_agents.values.return_value = [mock_info]

        with (
            patch.object(
                AgentService, "_instances", {"parent-uuid": mock_service, "sub-uuid": mock_service}
            ),
            patch.object(AgentService, "_primary_agent_uuid", None),
        ):
            _ = await Tool.execute(mock_coder, summary="done")

        assert mock_info.summary == "done"
        assert mock_info.status == SubAgentStatus.FINISHED

    @pytest.mark.asyncio
    async def test_sub_agent_without_summary(self):
        """Sub-agent without summary kwarg doesn't crash."""
        from cecli.tools._yield import Tool

        mock_coder = MagicMock()
        mock_coder.uuid = "sub-uuid"
        mock_coder.parent_uuid = "parent-uuid"
        mock_coder.files_edited_by_tools = set()

        result = await Tool.execute(mock_coder)
        assert result.to_dict()["result"][0]["content"] == "Yielded."

    @pytest.mark.asyncio
    async def test_non_sub_agent_skips_lookup(self):
        """Coder without parent_uuid skips sub-agent lookup."""
        from cecli.tools._yield import Tool

        mock_coder = MagicMock()
        mock_coder.uuid = "test-uuid"
        mock_coder.parent_uuid = ""
        mock_coder.files_edited_by_tools = set()

        result = await Tool.execute(mock_coder)
        assert result.to_dict()["result"][0]["content"] == "Yielded."

    @pytest.mark.asyncio
    async def test_unknown_parent_uuid_caught_gracefully(self):
        """Sub-agent with parent not in _instances is caught silently."""
        from cecli.helpers.agents.service import AgentService
        from cecli.tools._yield import Tool

        mock_coder = MagicMock()
        mock_coder.uuid = "sub-uuid"
        mock_coder.parent_uuid = "nonexistent-parent"
        mock_coder.files_edited_by_tools = set()
        mock_coder.turn_count = 0

        with (
            patch.object(AgentService, "_instances", {}),
            patch.object(AgentService, "_primary_agent_uuid", None),
        ):
            result = await Tool.execute(mock_coder, summary="done")
            assert "Summary: done" in str(result)

    async def test_returns_summary_in_response(self):
        """When summary provided, response includes it."""
        from cecli.tools._yield import Tool

        mock_coder = MagicMock()
        mock_coder.uuid = "test-uuid"
        mock_coder.parent_uuid = ""
        mock_coder.files_edited_by_tools = set()
        mock_coder.turn_count = 0

        result = await Tool.execute(mock_coder, summary="completed successfully")
        assert "Summary: completed successfully" in str(result)

    @pytest.mark.asyncio
    async def test_coder_is_none_returns_error(self):
        """When coder is None, returns error string."""
        from cecli.tools._yield import Tool

        result = await Tool.execute(None)
        errors = result.to_dict()["errors"]
        assert errors
