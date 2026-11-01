"""
Tests for cecli/helpers/io_proxy.py — IOProxy.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestIOProxy:
    """Tests for IOProxy facade."""

    def test_tool_output_injects_coder_uuid(self):
        """tool_output forwards with coder_uuid in kwargs."""
        from cecli.helpers.io_proxy import IOProxy

        target = MagicMock()
        coder = MagicMock()
        coder.uuid = "test-uuid-123"

        proxy = IOProxy(target, coder)
        proxy.tool_output("hello")

        target.tool_output.assert_called_once_with("hello", coder_uuid="test-uuid-123")

    def test_tool_output_preserves_existing_coder_uuid(self):
        """If coder_uuid already in kwargs, it's preserved."""
        from cecli.helpers.io_proxy import IOProxy

        target = MagicMock()
        coder = MagicMock()
        coder.uuid = "proxy-uuid"

        proxy = IOProxy(target, coder)
        proxy.tool_output("msg", coder_uuid="explicit-uuid")

        target.tool_output.assert_called_once_with("msg", coder_uuid="explicit-uuid")

    def test_tool_error_injects_coder_uuid(self):
        """tool_error forwards with coder_uuid."""
        from cecli.helpers.io_proxy import IOProxy

        target = MagicMock()
        coder = MagicMock()
        coder.uuid = "test-uuid"

        proxy = IOProxy(target, coder)
        proxy.tool_error("error message")

        target.tool_error.assert_called_once()
        _, kwargs = target.tool_error.call_args
        assert kwargs.get("coder_uuid") == "test-uuid"

    def test_tool_warning_injects_coder_uuid(self):
        """tool_warning forwards with coder_uuid."""
        from cecli.helpers.io_proxy import IOProxy

        target = MagicMock()
        coder = MagicMock()
        coder.uuid = "test-uuid"

        proxy = IOProxy(target, coder)
        proxy.tool_warning("warning")

        target.tool_warning.assert_called_once()
        _, kwargs = target.tool_warning.call_args
        assert kwargs.get("coder_uuid") == "test-uuid"

    def test_tool_success_injects_coder_uuid(self):
        """tool_success forwards with coder_uuid."""
        from cecli.helpers.io_proxy import IOProxy

        target = MagicMock()
        coder = MagicMock()
        coder.uuid = "test-uuid"

        proxy = IOProxy(target, coder)
        proxy.tool_success("success")

        target.tool_success.assert_called_once()
        _, kwargs = target.tool_success.call_args
        assert kwargs.get("coder_uuid") == "test-uuid"

    def test_stream_output_injects_coder_uuid(self):
        """stream_output forwards with coder_uuid."""
        from cecli.helpers.io_proxy import IOProxy

        target = MagicMock()
        coder = MagicMock()
        coder.uuid = "test-uuid"

        proxy = IOProxy(target, coder)
        proxy.stream_output("text", final=True)

        target.stream_output.assert_called_once_with(
            text="text", final=True, coder_uuid="test-uuid"
        )

    def test_assistant_output_injects_coder_uuid(self):
        """assistant_output forwards with coder_uuid."""
        from cecli.helpers.io_proxy import IOProxy

        target = MagicMock()
        coder = MagicMock()
        coder.uuid = "test-uuid"

        proxy = IOProxy(target, coder)
        proxy.assistant_output("response")

        target.assistant_output.assert_called_once_with(
            message="response", pretty=None, coder_uuid="test-uuid"
        )

    def test_nonexistent_method_forwarded(self):
        """Non-intercepted attributes forward to target."""
        from cecli.helpers.io_proxy import IOProxy

        target = MagicMock()
        coder = MagicMock()
        coder.uuid = "test-uuid"

        proxy = IOProxy(target, coder)
        proxy.some_random_method("arg")

        target.some_random_method.assert_called_once_with("arg")

    def test_coder_without_uuid(self):
        """Coder without uuid attr yields None for _coder_uuid."""
        from cecli.helpers.io_proxy import IOProxy

        target = MagicMock()

        class _CoderWithoutUUID:
            pass

        coder = _CoderWithoutUUID()  # no uuid attr

        proxy = IOProxy(target, coder)
        proxy.tool_output("hello")

        target.tool_output.assert_called_once_with("hello", coder_uuid=None)

    @pytest.mark.asyncio
    async def test_get_input_non_tui_returns_tuple(self):
        """Non-TUI mode (plain string) returns (str, None)."""
        from cecli.helpers.io_proxy import IOProxy

        target = MagicMock()
        target.get_input = AsyncMock(return_value="user text")

        coder = MagicMock()
        coder.uuid = "test-uuid"

        proxy = IOProxy(target, coder)
        result = await proxy.get_input()

        assert result == ("user text", None)

    @pytest.mark.asyncio
    async def test_get_input_matching_uuid_returns_tuple(self):
        """When target_uuid matches proxy's coder, returns tuple."""
        from cecli.helpers.io_proxy import IOProxy

        target = MagicMock()
        target.get_input = AsyncMock(return_value=("input", "test-uuid"))

        coder = MagicMock()
        coder.uuid = "test-uuid"

        proxy = IOProxy(target, coder)
        result = await proxy.get_input()

        assert result == ("input", "test-uuid")

    @pytest.mark.asyncio
    async def test_setattr_forwards_to_target(self):
        """Setting attributes forwards to target."""
        from cecli.helpers.io_proxy import IOProxy

        target = MagicMock()
        coder = MagicMock()
        coder.uuid = "test-uuid"

        proxy = IOProxy(target, coder)
        proxy.some_attr = "value"

        assert target.some_attr == "value"

    @pytest.mark.asyncio
    async def test_confirm_ask_auto_approves_unattended_coder(self):
        """A ``skip_cli_confirmations`` coder auto-approves without touching the target.

        Regression: unattended ``wf:``/``ws:`` workers used to forward the
        confirmation to the shared Textual IO and block on the input wake from a
        foreign event loop, freezing the interactive coder.
        """
        from cecli.helpers.io_proxy import IOProxy

        target = MagicMock()
        target.confirm_ask = AsyncMock(return_value=False)

        coder = MagicMock()
        coder.uuid = "test-uuid"
        coder.skip_cli_confirmations = True

        proxy = IOProxy(target, coder)
        result = await proxy.confirm_ask("Run tools?")

        assert result is True
        target.confirm_ask.assert_not_called()

    @pytest.mark.asyncio
    async def test_confirm_ask_forwards_for_interactive_coder(self):
        """An interactive coder forwards ``confirm_ask`` with coder_uuid injected."""
        from cecli.helpers.io_proxy import IOProxy

        target = MagicMock()
        target.confirm_ask = AsyncMock(return_value=True)

        coder = MagicMock()
        coder.uuid = "test-uuid"
        coder.skip_cli_confirmations = False

        proxy = IOProxy(target, coder)
        result = await proxy.confirm_ask("Run tools?")

        assert result is True
        target.confirm_ask.assert_awaited_once_with("Run tools?", coder_uuid="test-uuid")
