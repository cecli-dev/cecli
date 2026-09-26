"""
Tests for cecli/helpers/io_proxy.py — IOProxy.
"""

import asyncio
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


class _NonTuiTarget:
    """Minimal non-TUI InputOutput stand-in: no ``output_queue`` attribute.

    IOProxy selects the TUI path with ``hasattr(target, "output_queue")``, and a
    bare MagicMock answers ``hasattr`` for every name, so a plain object is the
    only way to exercise the non-TUI branch.
    """

    def __init__(self):
        self.prompt_session = None
        self.get_input = AsyncMock(return_value="terminal text")
        self.confirm_ask = AsyncMock(return_value=True)
        self.never_prompts = set()
        self.group_responses = {}
        self.user_inputs = []

    def user_input(self, inp, log_only=True):
        self.user_inputs.append(inp)


class TestIOProxyNonTuiQueue:
    """Non-TUI IOProxy must consume queue-pushed input and confirmations."""

    @pytest.mark.asyncio
    async def test_get_input_returns_queued_text(self):
        from cecli.helpers import queues
        from cecli.helpers.io_proxy import IOProxy

        coder_uuid = "queued-text-uuid"
        target = _NonTuiTarget()
        coder = MagicMock()
        coder.uuid = coder_uuid
        proxy = IOProxy(target, coder)
        try:
            assert queues.push_coder_input(
                coder_uuid, {"text": "queued answer", "coder_uuid": coder_uuid}
            )
            result = await proxy.get_input(None, [], [], [])

            assert result == ("queued answer", coder_uuid)
            target.get_input.assert_not_called()
            assert target.user_inputs == ["queued answer"]
        finally:
            queues.unregister_coder_queue(coder_uuid)

    @pytest.mark.asyncio
    async def test_get_input_delivers_push_while_prompt_open(self):
        from cecli.helpers import queues
        from cecli.helpers.io_proxy import IOProxy

        coder_uuid = "queued-race-uuid"
        started = asyncio.Event()

        async def blocking_terminal(*args, **kwargs):
            started.set()
            await asyncio.sleep(30)
            return "terminal text"

        target = _NonTuiTarget()
        target.prompt_session = object()  # cancellable prompt_async path
        target.get_input = blocking_terminal
        coder = MagicMock()
        coder.uuid = coder_uuid
        proxy = IOProxy(target, coder)
        task = asyncio.create_task(proxy.get_input(None, [], [], []))
        try:
            await started.wait()
            # The queue waiter clears its wake event when it binds to the loop,
            # so push until delivery lands instead of betting on callback order.
            for _ in range(100):
                queues.push_coder_input(
                    coder_uuid, {"text": "pushed answer", "coder_uuid": coder_uuid}
                )
                try:
                    result = await asyncio.wait_for(asyncio.shield(task), timeout=0.05)
                    break
                except asyncio.TimeoutError:
                    continue
            else:
                raise AssertionError("queued input was never delivered")

            assert result == ("pushed answer", coder_uuid)
        finally:
            task.cancel()
            queues.unregister_coder_queue(coder_uuid)

    @pytest.mark.asyncio
    async def test_get_input_leaves_confirmations_for_confirm_ask(self):
        from cecli.helpers import queues
        from cecli.helpers.io_proxy import IOProxy

        coder_uuid = "queued-mixed-uuid"
        target = _NonTuiTarget()
        coder = MagicMock()
        coder.uuid = coder_uuid
        proxy = IOProxy(target, coder)
        try:
            assert queues.push_coder_input(
                coder_uuid, {"confirmed": True, "coder_uuid": coder_uuid}
            )
            # get_input must not swallow a confirmation it cannot use.
            assert await proxy.get_input(None, [], [], []) == ("terminal text", None)
            assert await proxy.confirm_ask("Proceed?") is True
        finally:
            queues.unregister_coder_queue(coder_uuid)

    @pytest.mark.asyncio
    async def test_confirm_ask_returns_queued_confirmation(self):
        from cecli.helpers import queues
        from cecli.helpers.io_proxy import IOProxy

        coder_uuid = "queued-confirm-uuid"
        target = _NonTuiTarget()
        coder = MagicMock()
        coder.uuid = coder_uuid
        proxy = IOProxy(target, coder)
        try:
            assert queues.push_coder_input(
                coder_uuid, {"confirmed": True, "coder_uuid": coder_uuid}
            )
            assert await proxy.confirm_ask("Proceed?") is True

            assert queues.push_coder_input(
                coder_uuid, {"confirmed": False, "coder_uuid": coder_uuid}
            )
            assert await proxy.confirm_ask("Proceed?") is False

            target.confirm_ask.assert_not_called()
        finally:
            queues.unregister_coder_queue(coder_uuid)
