"""Tests for provider-safe MCP tool names.

Providers enforce ``^[A-Za-z0-9_-]{1,64}$`` on ``tools[].function.name``, so a
dotted MCP name such as ``browser.fetch`` is sanitized on the way to the model
and mapped back to the server's own name when the call comes back.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cecli.coders import Coder
from cecli.helpers import responses


def _tool(name):
    """Build a minimal OpenAI-style function tool dict."""
    return {
        "type": "function",
        "function": {"name": name, "description": "", "parameters": {}},
    }


def _call(name):
    return {
        "id": "call-1",
        "type": "function",
        "function": {"name": name, "arguments": "{}"},
    }


class TestSanitizeToolName:
    def test_dots_become_underscores(self):
        assert responses.sanitize_tool_name("browser.fetch") == "browser_fetch"

    def test_is_idempotent(self):
        once = responses.sanitize_tool_name("browser.persisted_session.list")

        assert responses.sanitize_tool_name(once) == once

    def test_honors_provider_length_limit(self):
        assert len(responses.sanitize_tool_name("a" * 200)) == 64


class TestRegisteredToolNames:
    def test_registered_name_maps_back(self):
        responses.register_tool_names([("browser", [_tool("browser.persisted_session.list")])])

        assert (
            responses.original_tool_name("browser_persisted_session_list")
            == "browser.persisted_session.list"
        )

    def test_unknown_name_is_unchanged(self):
        assert responses.original_tool_name("never_registered") == "never_registered"


class TestGetToolListSanitizesNames:
    def _coder(self, tools):
        return SimpleNamespace(
            mcp_tools=[("browser", tools)],
            registered_servers={"included": set(), "excluded": set()},
            registered_tools={"included": set(), "excluded": set()},
        )

    def test_dotted_names_are_sanitized_for_the_model(self):
        coder = self._coder([_tool("browser.fetch"), _tool("browser.persisted_session.list")])

        names = [t["function"]["name"] for t in Coder.get_tool_list(coder)]

        assert names == [
            "browser--browser_fetch",
            "browser--browser_persisted_session_list",
        ]

    def test_underscore_name_is_unchanged(self):
        coder = self._coder([_tool("brave_web_search")])

        names = [t["function"]["name"] for t in Coder.get_tool_list(coder)]

        assert names == ["browser--brave_web_search"]


class TestFindMcpServerForSanitizedCall:
    def test_sanitized_call_resolves_to_its_server(self):
        server = SimpleNamespace(name="browser")
        coder = SimpleNamespace(
            mcp_tools=[("browser", [_tool("browser.fetch")])],
            mcp_manager=[server],
        )
        tool_call = SimpleNamespace(
            id="call-1",
            type="function",
            function=SimpleNamespace(name="browser--browser_fetch"),
        )

        assert Coder._find_mcp_server_for_tool(coder, tool_call) is server


class TestCallToolMapsBackToAdvertisedName:
    """The name the model calls must reach the server unsanitized."""

    def _coder(self):
        coder = SimpleNamespace(mcp_tools=[("browser", [_tool("browser.fetch")])])
        responses.register_tool_names(coder.mcp_tools)

        return coder

    @pytest.mark.asyncio
    async def test_sanitized_name_is_mapped_back(self):
        coder = self._coder()
        session = MagicMock()
        session.call_tool = AsyncMock(return_value="ok")

        await Coder.call_mcp_tool_from_session(coder, session, _call("browser_fetch"))

        assert session.call_tool.await_args.kwargs["name"] == "browser.fetch"

    @pytest.mark.asyncio
    async def test_unsanitized_name_passes_through(self):
        coder = self._coder()
        session = MagicMock()
        session.call_tool = AsyncMock(return_value="ok")

        await Coder.call_mcp_tool_from_session(coder, session, _call("browser.fetch"))

        assert session.call_tool.await_args.kwargs["name"] == "browser.fetch"

    @pytest.mark.asyncio
    async def test_unknown_name_is_not_rewritten(self):
        coder = self._coder()
        session = MagicMock()
        session.call_tool = AsyncMock(return_value="ok")

        await Coder.call_mcp_tool_from_session(coder, session, _call("read_file"))

        assert session.call_tool.await_args.kwargs["name"] == "read_file"
