"""Tests for lowercase-normalized MCP server names.

MCP server names are normalized to lowercase at the registration source
(``McpServer`` construction, ``update_server_registration``, and the
load/remove-mcp include-set conversions) so that all per-coder filtering
comparisons can be plain exact matches.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cecli.coders import Coder
from cecli.coders.agent_coder import AgentCoder
from cecli.commands import SwitchCoderSignal
from cecli.commands.load_mcp import LoadMcpCommand
from cecli.commands.utils.helpers import (
    is_server_globally_excluded,
    update_server_registration,
)
from cecli.mcp.manager import McpServerManager
from cecli.mcp.server import LocalServer, McpServer


def _tool(name):
    """Build a minimal OpenAI-style function tool dict."""
    return {
        "type": "function",
        "function": {"name": name, "description": "", "parameters": {}},
    }


class TestMcpServerNameLowercasedAtSource:
    """McpServer names are lowercased at construction time."""

    def test_mcp_server_name_lowercased(self):
        assert McpServer({"name": "GitHub"}).name == "github"

    def test_local_server_name_lowercased(self):
        assert LocalServer({"name": "Local"}).name == "local"

    def test_default_name_stays_lowercase(self):
        assert McpServer({}).name == "unnamed-server"


class TestGetServerCaseInsensitive:
    """Manager lookups tolerate any case, matching normalized names."""

    def test_get_server_matches_any_case(self):
        server = McpServer({"name": "GitHub"})
        manager = McpServerManager(servers=[server])

        assert manager.get_server("GitHub") is server
        assert manager.get_server("github") is server
        assert manager.get_server("GITHUB") is server

    def test_get_server_missing_returns_none(self):
        manager = McpServerManager(servers=[McpServer({"name": "GitHub"})])

        assert manager.get_server("missing") is None


class TestUpdateServerRegistrationLowercases:
    """Registration writes lowercase names into the per-coder sets."""

    def test_include_lowercases(self):
        coder = SimpleNamespace(registered_servers={"included": set(), "excluded": set()})

        update_server_registration(coder, "GitHub", "include", force=True)

        assert coder.registered_servers["included"] == {"github"}
        assert coder.registered_servers["excluded"] == set()

    def test_exclude_lowercases(self):
        coder = SimpleNamespace(registered_servers={"included": set(), "excluded": set()})

        update_server_registration(coder, "GITHUB", "exclude", force=True)

        assert coder.registered_servers["excluded"] == {"github"}
        assert coder.registered_servers["included"] == set()

    def test_force_false_respects_opposing_set(self):
        coder = SimpleNamespace(registered_servers={"included": set(), "excluded": {"github"}})

        update_server_registration(coder, "GitHub", "include", force=False)

        assert coder.registered_servers["included"] == set()
        assert coder.registered_servers["excluded"] == {"github"}


class TestIsServerGloballyExcludedCaseInsensitive:
    """Global-exclusion checks match lowercase registered names."""

    def test_included_server_is_not_globally_excluded(self):
        coder = SimpleNamespace(registered_servers={"included": {"github"}, "excluded": set()})

        with patch("cecli.commands.utils.helpers.iter_all_coders", return_value=[coder]):
            assert is_server_globally_excluded(coder, "GitHub") is False

    def test_excluded_server_is_globally_excluded(self):
        coder = SimpleNamespace(registered_servers={"included": set(), "excluded": {"github"}})

        with patch("cecli.commands.utils.helpers.iter_all_coders", return_value=[coder]):
            assert is_server_globally_excluded(coder, "GITHUB") is True


def _manager_with_servers():
    """Manager with real servers named 'GitHub'/'Local' (normalized to lowercase)."""
    github = McpServer({"name": "GitHub"})
    local = McpServer({"name": "Local"})
    manager = McpServerManager(servers=[github, local])
    manager._server_tools = {
        "github": [_tool("list_issues")],
        "local": [_tool("read_file")],
    }
    manager._connected_servers = {github, local}
    return manager


class TestGetToolListExactMatchFiltering:
    """Per-coder filtering uses exact match on lowercase names."""

    def _coder(self, included=None, excluded=None):
        manager = _manager_with_servers()
        return SimpleNamespace(
            mcp_tools=list(manager.all_tools.items()),
            registered_servers={
                "included": set(included or []),
                "excluded": set(excluded or []),
            },
            registered_tools={"included": set(), "excluded": set()},
        )

    def test_include_list_keeps_only_matching_server(self):
        coder = self._coder(included=["github"])

        names = [t["function"]["name"] for t in Coder.get_tool_list(coder)]

        assert names == ["github--list_issues"]

    def test_empty_include_includes_all(self):
        coder = self._coder()

        names = [t["function"]["name"] for t in Coder.get_tool_list(coder)]

        assert set(names) == {"github--list_issues", "local--read_file"}

    def test_exclude_list_filters_by_lowercase(self):
        coder = self._coder(excluded=["github"])

        names = [t["function"]["name"] for t in Coder.get_tool_list(coder)]

        assert names == ["local--read_file"]


class TestGetServersContextExactMatchFiltering:
    """Servers context block classifies servers using exact lowercase match."""

    def _coder(self, included=None, excluded=None):
        return SimpleNamespace(
            use_enhanced_context=True,
            io=MagicMock(),
            mcp_manager=_manager_with_servers(),
            registered_servers={
                "included": set(included or []),
                "excluded": set(excluded or []),
            },
        )

    def test_include_list_marks_others_inactive(self):
        coder = self._coder(included=["github"])

        ctx = AgentCoder.get_servers_context(coder)

        assert "Active (1):" in ctx
        assert "- github" in ctx
        assert "Inactive (Filtered) (1):" in ctx
        assert "- local" in ctx

    def test_empty_include_lists_all_active(self):
        coder = self._coder()

        ctx = AgentCoder.get_servers_context(coder)

        assert "Active (2):" in ctx
        assert "Inactive (Filtered)" not in ctx


class TestLoadMcpCommandConversionLowercases:
    """Empty include sets are converted to lowercase connected names + 'local'."""

    @pytest.mark.asyncio
    async def test_empty_include_converted_to_lowercase(self):
        coder = MagicMock()
        coder.io = MagicMock()
        coder.edit_format = "agent"
        coder.interrupt_event = MagicMock()
        coder.interrupt_event.clear = MagicMock()
        coder.registered_servers = {"included": set(), "excluded": set()}

        github = MagicMock()
        github.name = "GitHub"
        github.config = {"enabled": True}
        local = MagicMock()
        local.name = "Local"
        local.config = {}

        coder.mcp_manager = MagicMock()
        coder.mcp_manager.servers = [github, local]
        coder.mcp_manager.connected_servers = [github, local]
        coder.mcp_manager.get_server = MagicMock(return_value=github)
        coder.mcp_manager.connect_server = AsyncMock(return_value=True)

        async def _passthrough(coro, event):
            return await coro, False

        coder.coroutines = MagicMock()
        coder.coroutines.interruptible = _passthrough

        with patch("cecli.commands.load_mcp.iter_all_coders", return_value=[coder]):
            with pytest.raises(SwitchCoderSignal):
                await LoadMcpCommand.execute(coder.io, coder, "GitHub")

        assert coder.registered_servers["included"] == {"github", "local"}


class TestLocalServerConnectedUnderLowercaseKey:
    """Connecting the Local server stores tools under the lowercase name."""

    @pytest.mark.asyncio
    async def test_connect_local_server_key_is_lowercase(self):
        local = LocalServer({"name": "Local"})
        manager = McpServerManager(servers=[local])

        with patch("cecli.mcp.manager.get_local_tool_schemas", return_value=[_tool("x")]):
            assert await manager.connect_server("Local") is True

        assert "local" in manager._server_tools
        assert "Local" not in manager._server_tools
