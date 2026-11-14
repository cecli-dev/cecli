"""
Tests for the fix of `AttributeError: 'SubAgentCoder' object has no attribute 'original_kwargs'`.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSubAgentCoderOriginalKwargs:
    """Tests for SubAgentCoder original_kwargs attribute initialization."""

    @pytest.mark.asyncio
    async def test_sub_agent_coder_has_original_kwargs(self):
        """Test that SubAgentCoder instances have original_kwargs attribute initialized."""
        from cecli.coders.agent_coder import AgentCoder
        from cecli.coders.sub_agent_coder import SubAgentCoder

        # Create a mock AgentCoder to act as from_coder
        mock_coder = MagicMock(spec=AgentCoder)
        mock_coder.uuid = "parent-uuid"
        mock_coder.args = MagicMock()
        mock_coder.args.max_reflections = 3
        mock_coder.args.max_tool_calls = 25
        mock_coder.main_model = MagicMock()
        mock_coder.main_model.edit_format = "agent"
        mock_coder.io = MagicMock()
        mock_coder.root = "."
        mock_coder.primary_root = "."
        mock_coder.repo = None
        mock_coder.original_kwargs = {}

        with patch("cecli.helpers.agents.service.AgentService") as MockService:
            mock_instance = MagicMock()
            mock_info = MagicMock()
            mock_info.coder.uuid = "child-uuid-123"
            mock_instance.spawn = AsyncMock(return_value=(MagicMock(), mock_info))
            MockService.get_instance.return_value = mock_instance

            # Create SubAgentCoder using the create class method
            sub_agent = await SubAgentCoder.create(from_coder=mock_coder)

            # Assert original_kwargs attribute exists and is initialized
            assert hasattr(sub_agent, "original_kwargs")
            assert isinstance(sub_agent.original_kwargs, dict)

    @pytest.mark.asyncio
    async def test_delegate_tool_no_attribute_error(self):
        """Delegating to SubAgentCoder must not raise AttributeError for original_kwargs."""
        from cecli.tools.delegate import Tool as DelegateTool

        mock_coder = MagicMock()
        mock_coder.uuid = "parent-uuid"
        mock_coder.original_kwargs = {}

        with patch("cecli.helpers.agents.service.AgentService") as MockService:
            mock_instance = MagicMock()
            mock_info = MagicMock()
            mock_info.coder.uuid = "child-uuid-123"
            mock_instance.spawn = AsyncMock(return_value=(MagicMock(), mock_info))
            MockService.get_instance.return_value = mock_instance

            # Should not raise AttributeError for original_kwargs
            result = await DelegateTool.execute(
                mock_coder, delegations=[{"name": "reviewer", "prompt": "review this"}]
            )

            # Verify successful delegation
            assert "agent started with id" in str(result)
            assert "child-uuid-123" in str(result)

    def test_sub_agent_coder_direct_instantiation(self):
        """Direct construction initializes original_kwargs without manual assignment."""
        from cecli.coders.sub_agent_coder import SubAgentCoder

        coder = SubAgentCoder(main_model=MagicMock(), io=MagicMock())

        assert hasattr(coder, "original_kwargs")
        assert isinstance(coder.original_kwargs, dict)