"""
Tests for cecli/tools/delegate.py — Delegate tool execution.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestDelegateTool:
    """Tests for the Delegate tool (cecli.tools.delegate)."""

    @pytest.mark.asyncio
    async def test_empty_name_returns_error(self):
        """Missing name returns error string."""
        from cecli.tools.delegate import Tool

        result = await Tool.execute(None, delegations=[{"name": "", "prompt": "do it"}])
        errors = result.to_dict()["errors"]
        assert errors
        assert "name" in errors[0]

    @pytest.mark.asyncio
    async def test_empty_prompt_returns_error(self):
        """Missing prompt returns error string."""
        from cecli.tools.delegate import Tool

        result = await Tool.execute(None, delegations=[{"name": "reviewer", "prompt": ""}])
        errors = result.to_dict()["errors"]
        assert errors
        assert "prompt" in errors[0]

    @pytest.mark.asyncio
    async def test_both_empty_returns_name_error(self):
        """Both empty — name error comes first."""
        from cecli.tools.delegate import Tool

        result = await Tool.execute(None, delegations=[{"name": "", "prompt": ""}])
        errors = result.to_dict()["errors"]
        assert errors
        assert "name" in errors[0]

    @pytest.mark.asyncio
    async def test_valid_delegate_calls_spawn(self):
        """Valid params call AgentService.spawn with correct args."""
        from cecli.tools.delegate import Tool

        mock_coder = MagicMock()
        mock_coder.uuid = "parent-uuid"

        with patch("cecli.helpers.agents.service.AgentService") as MockService:
            mock_instance = MagicMock()
            # spawn returns (new_coder, info); info.coder.uuid is used in output
            mock_info = MagicMock()
            mock_info.coder.uuid = "child-uuid-123"
            mock_instance.spawn = AsyncMock(return_value=(MagicMock(), mock_info))
            MockService.get_instance.return_value = mock_instance

            result = await Tool.execute(
                mock_coder, delegations=[{"name": "reviewer", "prompt": "review this"}]
            )

            MockService.get_instance.assert_called_once_with(mock_coder)
            mock_instance.spawn.assert_called_once_with(
                "reviewer", "review this", parent=mock_coder, auto_reap=None
            )
            assert "agent started with id" in str(result)
            assert "child-uuid-123" in str(result)

    async def test_delegate_multiple_delegations(self):
        """Multiple delegations show correct dispatch count."""
        from cecli.tools.delegate import Tool

        mock_coder = MagicMock()
        mock_coder.uuid = "parent-uuid"

        with patch("cecli.helpers.agents.service.AgentService") as MockService:
            mock_instance = MagicMock()

            async def spawn_side_effect(name, prompt, parent=None, auto_reap=None):
                mock_info = MagicMock()
                mock_info.coder.uuid = f"{name}-uuid"
                return MagicMock(), mock_info

            mock_instance.spawn = AsyncMock(side_effect=spawn_side_effect)
            MockService.get_instance.return_value = mock_instance

            result = await Tool.execute(
                mock_coder,
                delegations=[
                    {"name": "agent1", "prompt": "task1"},
                    {"name": "agent2", "prompt": "task2"},
                ],
            )

            assert "2/2 dispatched" in str(result)
            assert "agent1" in str(result)
            assert "agent2" in str(result)

    @pytest.mark.asyncio
    async def test_delegate_spawn_error_returns_error_string(self):
        """Error from spawn returns error string."""
        from cecli.tools.delegate import Tool

        mock_coder = MagicMock()
        with patch("cecli.helpers.agents.service.AgentService") as MockService:
            mock_instance = MagicMock()
            mock_instance.spawn = AsyncMock(side_effect=ValueError("unknown agent"))
            MockService.get_instance.return_value = mock_instance

            result = await Tool.execute(mock_coder, delegations=[{"name": "ghost", "prompt": "x"}])
            errors = result.to_dict()["result"]
            assert errors

    async def test_delegate_runtime_error_returns_error_string(self):
        """RuntimeError from spawn returns error string."""
        from cecli.tools.delegate import Tool

        mock_coder = MagicMock()
        with patch("cecli.helpers.agents.service.AgentService") as MockService:
            mock_instance = MagicMock()
            mock_instance.spawn = AsyncMock(side_effect=RuntimeError("max reached"))
            MockService.get_instance.return_value = mock_instance

            result = await Tool.execute(
                mock_coder, delegations=[{"name": "reviewer", "prompt": "x"}]
            )
            errors = result.to_dict()["result"]
            assert errors

    async def test_unexpected_exception_caught(self):
        """Any other exception returns error string (doesn't propagate)."""
        from cecli.tools.delegate import Tool

        mock_coder = MagicMock()
        with patch("cecli.helpers.agents.service.AgentService") as MockService:
            mock_instance = MagicMock()
            mock_instance.spawn = AsyncMock(side_effect=Exception("unexpected"))
            MockService.get_instance.return_value = mock_instance

            result = await Tool.execute(
                mock_coder, delegations=[{"name": "reviewer", "prompt": "x"}]
            )
            errors = result.to_dict()["result"]
            assert errors

    @pytest.mark.asyncio
    async def test_persist_true_sets_auto_reap_false_spawn(self):
        """persist=True passes auto_reap=False to spawn for async delegations."""
        from cecli.tools.delegate import Tool

        mock_coder = MagicMock()
        mock_coder.uuid = "parent-uuid"

        with patch("cecli.helpers.agents.service.AgentService") as MockService:
            mock_instance = MagicMock()
            mock_info = MagicMock()
            mock_info.coder.uuid = "child-uuid-persist"
            mock_instance.spawn = AsyncMock(return_value=(MagicMock(), mock_info))
            MockService.get_instance.return_value = mock_instance

            result = await Tool.execute(
                mock_coder,
                delegations=[{"name": "reviewer", "prompt": "keep me", "persist": True}],
            )

            mock_instance.spawn.assert_called_once_with(
                "reviewer", "keep me", parent=mock_coder, auto_reap=False
            )
            assert "agent started with id" in str(result)

    @pytest.mark.asyncio
    async def test_persist_true_sets_auto_reap_false_invoke(self):
        """persist=True passes auto_reap=False to invoke for sync delegations."""
        from cecli.tools.delegate import Tool

        mock_coder = MagicMock()
        mock_coder.uuid = "parent-uuid"

        with patch("cecli.helpers.agents.service.AgentService") as MockService:
            mock_instance = MagicMock()
            mock_instance.invoke = AsyncMock(return_value="done")
            MockService.get_instance.return_value = mock_instance

            result = await Tool.execute(
                mock_coder,
                delegations=[
                    {"name": "reviewer", "prompt": "blocking", "persist": True, "async": False}
                ],
            )

            mock_instance.invoke.assert_called_once_with(
                "reviewer", "blocking", parent=mock_coder, auto_reap=False
            )
            assert "agent completed" in str(result)

    def test_schema_declares_working_dir(self):
        """The delegation schema accepts an optional per-agent working directory."""
        from cecli.tools.delegate import Tool

        item = Tool.SCHEMA["function"]["parameters"]["properties"]["delegations"]["items"]
        assert item["properties"]["working_dir"]["type"] == "string"

    @pytest.mark.asyncio
    async def test_working_dir_is_passed_to_spawn(self):
        """working_dir is passed as root for async delegations."""
        from cecli.tools.delegate import Tool

        mock_coder = MagicMock()
        mock_coder.uuid = "parent-uuid"

        with patch("cecli.helpers.agents.service.AgentService") as MockService:
            mock_instance = MagicMock()
            mock_info = MagicMock()
            mock_info.coder.uuid = "child-uuid"
            mock_instance.spawn = AsyncMock(return_value=(MagicMock(), mock_info))
            MockService.get_instance.return_value = mock_instance

            await Tool.execute(
                mock_coder,
                delegations=[
                    {
                        "name": "reviewer",
                        "prompt": "review",
                        "working_dir": "packages/api",
                    }
                ],
            )

            mock_instance.spawn.assert_awaited_once_with(
                "reviewer",
                "review",
                parent=mock_coder,
                auto_reap=None,
                root="packages/api",
            )

    @pytest.mark.asyncio
    async def test_working_dir_is_passed_to_invoke(self):
        """working_dir is passed as root for sync delegations."""
        from cecli.tools.delegate import Tool

        mock_coder = MagicMock()
        mock_coder.uuid = "parent-uuid"

        with patch("cecli.helpers.agents.service.AgentService") as MockService:
            mock_instance = MagicMock()
            mock_instance.invoke = AsyncMock(return_value="done")
            MockService.get_instance.return_value = mock_instance

            await Tool.execute(
                mock_coder,
                delegations=[
                    {
                        "name": "reviewer",
                        "prompt": "review",
                        "working_dir": "/tmp/project",
                        "async": False,
                    }
                ],
            )

            mock_instance.invoke.assert_awaited_once_with(
                "reviewer",
                "review",
                parent=mock_coder,
                auto_reap=None,
                root="/tmp/project",
            )

    def test_format_output_shows_working_dir(self):
        """format_output displays an explicit delegation working_dir."""
        from cecli.tools.delegate import Tool

        coder = MagicMock()
        coder.pretty = False
        coder.verbose = False
        tool_response = SimpleNamespace(
            function=SimpleNamespace(
                name="Delegate",
                arguments=json.dumps(
                    {
                        "delegations": [
                            {
                                "name": "reviewer",
                                "prompt": "review",
                                "working_dir": "packages/api",
                            }
                        ]
                    }
                ),
            )
        )

        with (
            patch("cecli.tools.delegate.tool_header"),
            patch("cecli.tools.delegate.tool_footer"),
            patch("cecli.tools.delegate.color_markers", return_value=("", "")),
        ):
            Tool.format_output(coder, mcp_server=MagicMock(), tool_response=tool_response)

        rendered = "\n".join(str(call.args[0]) for call in coder.io.tool_output.call_args_list)
        assert "working_dir: packages/api" in rendered
