"""Unit tests for cecli/helpers/queues.py — Global per-coder queue registry."""

from __future__ import annotations

import asyncio
import contextlib
import queue

from cecli.helpers import queues


class TestRegisterAndUnregister:
    """Tests for register_coder_queue and unregister_coder_queue."""

    def setup_method(self):
        """Clear the global registry before each test."""
        queues._per_coder_queues.clear()

    def test_register_new_queue(self):
        """Registering a new coder queue adds it to the global registry."""
        q = queue.Queue()
        queues.register_coder_queue("coder-1", q)
        assert queues._per_coder_queues["coder-1"] is q

    def test_register_replace_existing(self):
        """Registering an existing coder UUID replaces the old queue."""
        q1 = queue.Queue()
        q2 = queue.Queue()
        queues.register_coder_queue("coder-1", q1)
        queues.register_coder_queue("coder-1", q2)
        assert queues._per_coder_queues["coder-1"] is q2
        assert queues._per_coder_queues["coder-1"] is not q1

    def test_unregister_existing(self):
        """Unregistering an existing coder removes it from the registry."""
        q = queue.Queue()
        queues.register_coder_queue("coder-1", q)
        queues.unregister_coder_queue("coder-1")
        assert "coder-1" not in queues._per_coder_queues

    def test_unregister_nonexistent(self):
        """Unregistering a non-existent coder does not raise."""
        queues.unregister_coder_queue("does-not-exist")
        # No exception means success

    def test_multiple_coders(self):
        """Multiple coders can be registered simultaneously."""
        q1 = queue.Queue()
        q2 = queue.Queue()
        queues.register_coder_queue("coder-1", q1)
        queues.register_coder_queue("coder-2", q2)
        assert len(queues._per_coder_queues) == 2


class TestGetCoderQueue:
    """Tests for get_coder_queue."""

    def setup_method(self):
        queues._per_coder_queues.clear()

    def test_get_existing(self):
        """Getting an existing coder's queue returns the queue."""
        q = queue.Queue()
        queues.register_coder_queue("coder-1", q)
        assert queues.get_coder_queue("coder-1") is q

    def test_get_nonexistent(self):
        """Getting a non-existent coder returns None."""
        assert queues.get_coder_queue("does-not-exist") is None

    def test_get_after_unregister(self):
        """Getting a coder's queue after unregistering returns None."""
        q = queue.Queue()
        queues.register_coder_queue("coder-1", q)
        queues.unregister_coder_queue("coder-1")
        assert queues.get_coder_queue("coder-1") is None


class TestPushCoderInput:
    """Tests for push_coder_input."""

    def setup_method(self):
        queues._per_coder_queues.clear()

    def test_push_string_message(self):
        """Pushing a string message delivers it to the correct queue."""
        q = queue.Queue()
        queues.register_coder_queue("coder-1", q)
        result = queues.push_coder_input("coder-1", "hello")
        assert result is True
        assert q.get_nowait() == "hello"

    def test_push_dict_message(self):
        """Pushing a dict message delivers it to the correct queue."""
        q = queue.Queue()
        queues.register_coder_queue("coder-1", q)
        msg = {"text": "hello", "coder_uuid": "coder-1"}
        result = queues.push_coder_input("coder-1", msg)
        assert result is True
        assert q.get_nowait() == msg

    def test_push_to_nonexistent(self):
        """Pushing to a non-existent coder returns False."""
        result = queues.push_coder_input("does-not-exist", "hello")
        assert result is False

    def test_push_preserves_queue_order(self):
        """Multiple pushes preserve FIFO order."""
        q = queue.Queue()
        queues.register_coder_queue("coder-1", q)
        queues.push_coder_input("coder-1", "first")
        queues.push_coder_input("coder-1", "second")
        assert q.get_nowait() == "first"
        assert q.get_nowait() == "second"


class TestInputLoopLifecycle:
    """Tests for the input wake-state lifecycle across hot reloads."""

    def setup_method(self):
        """Reset the global input-loop state before each test."""
        queues._per_coder_queues.clear()
        queues._input_loop = None
        queues._input_wake = None

    def teardown_method(self):
        """Reset the global input-loop state after each test."""
        queues._per_coder_queues.clear()
        queues._input_loop = None
        queues._input_wake = None

    def test_wake_with_closed_loop_drops_stale_binding(self):
        """Waking after the bound loop closed must not raise, and resets state."""
        old_loop = asyncio.new_event_loop()
        old_loop.close()

        queues.set_input_loop(old_loop)

        queues.wake_input_waiters()  # Must not raise RuntimeError

        assert queues._input_loop is None
        assert queues._input_wake is None

    def test_push_after_closed_loop_delivers_but_does_not_crash(self):
        """Pushing input after a reload (closed loop) delivers and drops stale state."""
        q = queue.Queue()
        queues.register_coder_queue("coder-1", q)

        old_loop = asyncio.new_event_loop()
        old_loop.close()
        queues.set_input_loop(old_loop)

        result = queues.push_coder_input("coder-1", "hello")

        assert result is True
        assert q.get_nowait() == "hello"
        assert queues._input_loop is None
        assert queues._input_wake is None

    def test_wait_for_input_rebinds_after_closed_loop(self):
        """wait_for_input rebinds to the running loop after a hot reload."""

        async def run():
            old_loop = asyncio.new_event_loop()
            old_loop.close()
            queues.set_input_loop(old_loop)

            task = asyncio.create_task(queues.wait_for_input())
            await asyncio.sleep(0)

            assert queues._input_loop is not None
            assert not queues._input_loop.is_closed()

            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        asyncio.run(run())
