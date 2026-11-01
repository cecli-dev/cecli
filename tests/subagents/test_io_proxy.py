"""
Tests for cecli/helpers/io_proxy.py — IOProxy.
"""

import asyncio
from types import SimpleNamespace
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


class _NonTuiIO:
    """Minimal non-TUI InputOutput stand-in (no ``output_queue``)."""

    def __init__(self, prompt_session=None):
        self.prompt_session = prompt_session
        self.never_prompts = set()
        self.group_responses = {}
        self.user_inputs = []
        self.num_user_asks = 0
        self.placeholder = None
        self.started = asyncio.Event()
        self.cleaned = False

    async def get_input(self, *args, **kwargs):
        self.started.set()
        try:
            await asyncio.sleep(30)
        finally:
            self.cleaned = True

    async def confirm_ask(self, *args, **kwargs):
        self.started.set()
        try:
            await asyncio.sleep(30)
        finally:
            self.cleaned = True

    def user_input(self, inp, log_only=True):
        self.user_inputs.append(inp)


def _non_tui_proxy(coder_uuid, prompt_session=None):
    from cecli.helpers.io_proxy import IOProxy

    target = _NonTuiIO(prompt_session)
    coder = MagicMock()
    coder.uuid = coder_uuid
    coder.skip_cli_confirmations = False
    return IOProxy(target, coder), target


class TestIOProxyNonTuiQueue:
    """Non-TUI IOProxy must consume queue-pushed input and confirmations."""

    @pytest.mark.asyncio
    async def test_get_input_returns_queued_text(self):
        from cecli.helpers import queues

        coder_uuid = "non-tui-text"
        proxy, target = _non_tui_proxy(coder_uuid)
        try:
            assert queues.push_coder_input(coder_uuid, {"text": "queued answer"})
            result = await asyncio.wait_for(proxy.get_input(None, [], [], []), timeout=1)

            assert result == ("queued answer", coder_uuid)
            assert target.user_inputs == ["queued answer"]
            assert not target.started.is_set()
        finally:
            queues.unregister_coder_queue(coder_uuid)

    @pytest.mark.asyncio
    async def test_get_input_falls_back_to_terminal(self):
        from cecli.helpers import queues
        from cecli.helpers.io_proxy import IOProxy

        coder_uuid = "non-tui-terminal"
        target = _NonTuiIO()
        target.get_input = AsyncMock(return_value="terminal text")
        coder = MagicMock()
        coder.uuid = coder_uuid
        proxy = IOProxy(target, coder)
        try:
            assert await proxy.get_input() == ("terminal text", None)
        finally:
            queues.unregister_coder_queue(coder_uuid)

    @pytest.mark.asyncio
    async def test_push_delivered_while_prompt_open(self):
        from cecli.helpers import queues

        coder_uuid = "non-tui-race"
        proxy, target = _non_tui_proxy(coder_uuid, prompt_session=object())
        task = asyncio.create_task(proxy.get_input(None, [], [], []))
        try:
            await asyncio.wait_for(target.started.wait(), timeout=1)
            assert queues.push_coder_input(coder_uuid, {"text": "pushed answer"})

            result = await asyncio.wait_for(task, timeout=1)
            assert result == ("pushed answer", coder_uuid)
            assert target.cleaned
        finally:
            task.cancel()
            queues.unregister_coder_queue(coder_uuid)

    @pytest.mark.asyncio
    async def test_text_is_delivered_behind_a_queued_confirmation(self):
        from cecli.helpers import queues

        coder_uuid = "non-tui-order-confirm-first"
        proxy, _ = _non_tui_proxy(coder_uuid, prompt_session=object())
        try:
            queues.push_coder_input(coder_uuid, {"confirmed": True})
            queues.push_coder_input(coder_uuid, {"text": "answer"})

            result = await asyncio.wait_for(proxy.get_input(None, [], [], []), timeout=1)

            assert result == ("answer", coder_uuid)
            assert queues.get_coder_queue(coder_uuid).qsize() == 1
        finally:
            queues.unregister_coder_queue(coder_uuid)

    @pytest.mark.asyncio
    async def test_confirmation_is_delivered_behind_queued_text(self):
        from cecli.helpers import queues

        coder_uuid = "non-tui-order-text-first"
        proxy, _ = _non_tui_proxy(coder_uuid, prompt_session=object())
        try:
            queues.push_coder_input(coder_uuid, {"text": "answer"})
            queues.push_coder_input(coder_uuid, {"confirmed": False})

            assert await asyncio.wait_for(proxy.confirm_ask("Proceed?"), timeout=1) is False
            assert queues.get_coder_queue(coder_uuid).qsize() == 1
        finally:
            queues.unregister_coder_queue(coder_uuid)

    @pytest.mark.asyncio
    async def test_get_input_leaves_confirmations_for_confirm_ask(self):
        from cecli.helpers import queues

        coder_uuid = "non-tui-leave-confirmation"
        proxy, target = _non_tui_proxy(coder_uuid, prompt_session=object())
        task = asyncio.create_task(proxy.get_input(None, [], [], []))
        try:
            await asyncio.wait_for(target.started.wait(), timeout=1)
            queues.push_coder_input(coder_uuid, {"confirmed": True})
            await asyncio.sleep(0.2)

            assert not task.done()
            assert queues.get_coder_queue(coder_uuid).qsize() == 1

            queues.push_coder_input(coder_uuid, {"text": "answer"})
            assert await asyncio.wait_for(task, timeout=1) == ("answer", coder_uuid)
            assert await proxy.confirm_ask("Proceed?") is True
        finally:
            task.cancel()
            queues.unregister_coder_queue(coder_uuid)

    @pytest.mark.asyncio
    async def test_confirm_ask_returns_queued_booleans(self):
        from cecli.helpers import queues

        coder_uuid = "non-tui-confirm-bools"
        proxy, target = _non_tui_proxy(coder_uuid)
        try:
            queues.push_coder_input(coder_uuid, {"confirmed": True})
            assert await proxy.confirm_ask("Proceed?") is True

            queues.push_coder_input(coder_uuid, {"confirmed": False})
            assert await proxy.confirm_ask("Proceed?") is False

            queues.push_coder_input(coder_uuid, {"confirmed": "no"})
            assert await proxy.confirm_ask("Proceed?") is False

            assert target.num_user_asks == 3
            assert not target.started.is_set()
        finally:
            queues.unregister_coder_queue(coder_uuid)

    @pytest.mark.asyncio
    async def test_confirm_ask_maps_special_responses(self):
        from cecli.helpers import queues

        coder_uuid = "non-tui-confirm-special"
        proxy, target = _non_tui_proxy(coder_uuid)
        group = SimpleNamespace(preference=None, show_group=True)
        try:
            queues.push_coder_input(coder_uuid, {"confirmed": "never"})
            assert await proxy.confirm_ask("Proceed?", subject="file.py") is False
            assert ("Proceed?", "file.py") in target.never_prompts

            queues.push_coder_input(coder_uuid, {"confirmed": "tweak"})
            assert await proxy.confirm_ask("Proceed?", allow_tweak=True) == "tweak"

            queues.push_coder_input(coder_uuid, {"confirmed": "all"})
            result = await proxy.confirm_ask("Proceed?", group=group, group_response="batch")
            assert result is True
            assert group.preference == "all"
            assert target.group_responses["batch"] is True

            queues.push_coder_input(coder_uuid, {"confirmed": "skip"})
            result = await proxy.confirm_ask("Proceed?", group=group, group_response="batch")
            assert result is False
            assert group.preference == "skip"
            assert target.group_responses["batch"] is False
        finally:
            queues.unregister_coder_queue(coder_uuid)

    @pytest.mark.asyncio
    async def test_unattended_coder_does_not_consume_queued_confirmation(self):
        from cecli.helpers import queues
        from cecli.helpers.io_proxy import IOProxy

        coder_uuid = "non-tui-unattended"
        target = _NonTuiIO()
        coder = MagicMock()
        coder.uuid = coder_uuid
        coder.skip_cli_confirmations = True
        proxy = IOProxy(target, coder)
        try:
            queues.push_coder_input(coder_uuid, {"confirmed": False})

            assert await proxy.confirm_ask("Proceed?") is True
            assert queues.get_coder_queue(coder_uuid).qsize() == 1
            assert not target.started.is_set()
        finally:
            queues.unregister_coder_queue(coder_uuid)

    @pytest.mark.asyncio
    async def test_prompt_draft_is_stashed_when_queue_preempts(self):
        from cecli.helpers import queues

        coder_uuid = "non-tui-draft"
        session = SimpleNamespace(
            app=SimpleNamespace(current_buffer=SimpleNamespace(text="half typed"))
        )
        proxy, target = _non_tui_proxy(coder_uuid, prompt_session=session)
        task = asyncio.create_task(proxy.get_input(None, [], [], []))
        try:
            await asyncio.wait_for(target.started.wait(), timeout=1)
            queues.push_coder_input(coder_uuid, {"text": "queued"})

            await asyncio.wait_for(task, timeout=1)
            assert target.placeholder == "half typed"
        finally:
            task.cancel()
            queues.unregister_coder_queue(coder_uuid)
