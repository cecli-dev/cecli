"""
Tests for the fix of `AttributeError: 'SubAgentCoder' object has no attribute 'original_kwargs'`.

Regression context (CLI-75):
- `Coder.create()` reads `from_coder.original_kwargs` when building a new coder
  (cecli/coders/base_coder.py, inside `create()`).
- Before the fix, `original_kwargs` was only assigned by `Coder.create()` AFTER
  construction, so any coder built by direct constructor call (e.g. SubAgentCoder
  via AgentService) lacked the attribute. Any later `create(from_coder=...)` —
  including the Delegate tool's spawn path in
  AgentService._create_sub_agent_coder() — raised AttributeError, which the
  Delegate tool reported as `failed: 'SubAgentCoder' object has no attribute
  'original_kwargs'`.
- The fix initializes `self.original_kwargs = {}` at the top of `Coder.__init__`;
  `Coder.create()` still overwrites it with the real kwargs afterwards.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cecli.coders.agent_coder import AgentCoder
from cecli.coders.sub_agent_coder import SubAgentCoder


@pytest.fixture(autouse=True)
def _reset_agent_service_state():
    """Keep AgentService class-level state isolated between tests."""
    from cecli.helpers.agents.service import AgentService

    AgentService._instances.clear()
    AgentService._uuid_coder_map.clear()
    AgentService._primary_agent_uuid = None
    yield
    AgentService._instances.clear()
    AgentService._uuid_coder_map.clear()
    AgentService._primary_agent_uuid = None


def _make_direct_agent_coder():
    """Build a real AgentCoder via direct construction, bypassing Coder.create().

    This mirrors the direct-instantiation path (as in
    tests/integration/test_agent_mcp_management.py) that used to produce coders
    without `original_kwargs`. No manual `original_kwargs` assignment is done
    here: the initialization under test must come from `Coder.__init__` itself.
    """
    mock_mcp_manager = MagicMock()
    mock_mcp_manager.connected_servers = {}
    with patch("cecli.coders.agent_coder.McpServerManager", return_value=mock_mcp_manager):
        coder = AgentCoder(main_model=MagicMock(), io=MagicMock())
    coder.mcp_manager = mock_mcp_manager
    return coder


class TestSubAgentCoderOriginalKwargs:
    """Regression tests for original_kwargs initialization (CLI-75)."""

    def test_sub_agent_coder_direct_instantiation_has_original_kwargs(self):
        """Directly constructed SubAgentCoder gets original_kwargs from Coder.__init__."""
        coder = SubAgentCoder(main_model=MagicMock(), io=MagicMock())

        assert hasattr(coder, "original_kwargs"), (
            "SubAgentCoder built by direct constructor call must have original_kwargs"
        )
        assert isinstance(coder.original_kwargs, dict)
        assert coder.original_kwargs == {}

    @pytest.mark.asyncio
    async def test_sub_agent_coder_create_has_original_kwargs(self):
        """Coder.create(from_coder=...) accepts a directly built parent (Delegate's path).

        AgentService._create_sub_agent_coder() calls
        Coder.create(from_coder=parent, edit_format="subagent", ...), which reads
        from_coder.original_kwargs. A directly constructed parent must therefore
        be usable as from_coder without raising AttributeError.
        """
        parent = _make_direct_agent_coder()
        # Precondition: the fix is present on the parent itself.
        assert isinstance(parent.original_kwargs, dict)

        sub_agent = await SubAgentCoder.create(from_coder=parent, edit_format="subagent")

        assert isinstance(sub_agent, SubAgentCoder)
        assert isinstance(sub_agent.original_kwargs, dict)
        # Coder.create() overwrites original_kwargs with the real constructor kwargs.
        assert "fnames" in sub_agent.original_kwargs

    @pytest.mark.asyncio
    async def test_delegate_tool_no_attribute_error(self):
        """DelegateTool.execute() completes without AttributeError for original_kwargs."""
        from cecli.tools.delegate import Tool as DelegateTool

        mock_coder = MagicMock()
        mock_coder.uuid = "parent-uuid"

        with patch("cecli.helpers.agents.service.AgentService") as MockService:
            mock_instance = MagicMock()
            mock_info = MagicMock()
            mock_info.coder.uuid = "child-uuid-123"
            mock_instance.spawn = AsyncMock(return_value=(MagicMock(), mock_info))
            MockService.get_instance.return_value = mock_instance

            result = await DelegateTool.execute(
                mock_coder,
                delegations=[{"name": "reviewer", "prompt": "review this"}],
            )

        assert "agent started with id" in str(result)
        assert "child-uuid-123" in str(result)