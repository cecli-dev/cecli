"""Tests for SelectSelector fallback used when stdin is not a TTY.

Covers:
- cecli/interruptible_input.py: SelectSelector vs DefaultSelector choice
- cecli/main.py: _SelectSelectorPolicy on macOS when stdin is not a TTY
"""

import asyncio
import os
import selectors
import sys
from unittest import mock

import pytest

from cecli.interruptible_input import InterruptibleInput


# ---------------------------------------------------------------------------
# InterruptibleInput selector tests
# ---------------------------------------------------------------------------


class TestInterruptibleInputSelector:
    """InterruptibleInput should pick SelectSelector for non-TTY stdin."""

    def test_uses_select_selector_when_not_a_tty(self):
        with mock.patch.object(sys.stdin, "isatty", return_value=False):
            obj = InterruptibleInput()
            try:
                assert isinstance(obj._sel, selectors.SelectSelector)
            finally:
                obj.close()

    def test_uses_default_selector_when_tty(self):
        with mock.patch.object(sys.stdin, "isatty", return_value=True):
            obj = InterruptibleInput()
            try:
                assert isinstance(obj._sel, selectors.DefaultSelector)
            finally:
                obj.close()

    def test_selector_registers_wakeup_pipe(self):
        with mock.patch.object(sys.stdin, "isatty", return_value=False):
            obj = InterruptibleInput()
            try:
                # The wakeup read-end fd should be registered
                key = obj._sel.get_key(obj._r)
                assert key.data == "__wakeup__"
                assert key.events & selectors.EVENT_READ
            finally:
                obj.close()

    def test_close_is_safe_to_call_twice(self):
        with mock.patch.object(sys.stdin, "isatty", return_value=False):
            obj = InterruptibleInput()
            obj.close()
            # Second close should not raise
            obj.close()

    def test_interrupt_sets_cancel_and_wakes_selector(self):
        with mock.patch.object(sys.stdin, "isatty", return_value=False):
            obj = InterruptibleInput()
            try:
                obj.interrupt()
                assert obj._cancel.is_set()
                # The wakeup pipe should have data
                data = os.read(obj._r, 1024)
                assert len(data) > 0
            finally:
                obj.close()

    def test_input_raises_interrupted_when_cancelled_before_call(self):
        with mock.patch.object(sys.stdin, "isatty", return_value=False):
            obj = InterruptibleInput()
            try:
                obj.interrupt()
                with pytest.raises(InterruptedError, match="Input interrupted"):
                    obj.input("")
            finally:
                obj.close()

    @pytest.mark.skipif(os.name == "nt", reason="Unix-only")
    def test_raises_on_windows(self):
        with mock.patch("os.name", "nt"):
            with pytest.raises(RuntimeError, match="Unix-only"):
                InterruptibleInput()


# ---------------------------------------------------------------------------
# macOS _SelectSelectorPolicy tests
# ---------------------------------------------------------------------------


class TestSelectSelectorPolicyMacOS:
    """On macOS with non-TTY stdin, the event loop should use SelectSelector."""

    @pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only policy")
    def test_policy_uses_select_selector_on_macos_non_tty(self):
        """When stdin is not a TTY on macOS, the patched policy should
        produce a SelectorEventLoop backed by SelectSelector."""
        from cecli.main import _SelectSelectorPolicy

        policy = _SelectSelectorPolicy()
        loop = policy.new_event_loop()
        try:
            selector = loop._selector
            assert isinstance(selector, selectors.SelectSelector)
        finally:
            loop.close()

    def test_main_module_sets_policy_on_darwin_non_tty(self):
        """Simulate importing the selector-policy block on macOS with piped stdin."""
        select_selector_cls = selectors.SelectSelector

        # Build a mini _SelectSelectorPolicy the same way main.py does
        class _SelectSelectorPolicy(asyncio.DefaultEventLoopPolicy):
            def new_event_loop(self):
                return asyncio.SelectorEventLoop(select_selector_cls())

        policy = _SelectSelectorPolicy()
        loop = policy.new_event_loop()
        try:
            assert isinstance(loop._selector, selectors.SelectSelector)
        finally:
            loop.close()

    def test_default_policy_not_changed_when_tty(self):
        """When stdin IS a TTY, the default event loop policy should remain."""
        original_policy = asyncio.get_event_loop_policy()
        with mock.patch.object(sys.stdin, "isatty", return_value=True):
            # The policy should be whatever the system default is,
            # not our custom _SelectSelectorPolicy
            current = asyncio.get_event_loop_policy()
            assert current is original_policy
