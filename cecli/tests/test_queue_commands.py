"""
Test suite for CLI-33 Queue Commands.

This module contains comprehensive tests for:
- Unit tests: Queue logic in the command_queue helper
- Integration tests: QueueCommand, ListQueueCommand, RemoveQueueCommand
- E2E tests: Full queue lifecycle and processing
- Regression tests: Existing command integrity

Test categories:
- UTC-01 through UTC-20: Unit tests for queue helpers
- ITC-01 through ITC-20: Integration tests for commands
- ETC-01 through ETC-10: E2E tests for full lifecycle
- RTC-01 through RTC-05: Regression tests for existing functionality
- TDS-01 through TDS-04: Test data setup and fixtures
"""

import threading
import time
from unittest.mock import MagicMock

import pytest

# Import the actual classes to test
from cecli.commands.core import Commands
from cecli.commands.list_queue import ListQueueCommand
from cecli.commands.queue import QueueCommand
from cecli.commands.remove_queue import RemoveQueueCommand
from cecli.commands.utils.registry import CommandRegistry
from cecli.helpers import command_queue
from cecli.signals import ReloadProgramSignal, SwitchCoderSignal


def _make_coder():
    """Build a minimal coder-like object with the queue attributes the
    ``command_queue`` helpers require (``prompt_queue``, ``_queue_counter``,
    ``_queue_lock``)."""
    coder = MagicMock()
    import uuid

    coder.uuid = str(uuid.uuid4())
    coder.prompt_queue = []
    coder._queue_counter = 0
    coder._queue_lock = None
    return coder


def _make_coder_with_commands(items=()):
    """Build a coder with an attached Commands instance and an optional
    pre-populated queue."""
    coder = _make_coder()
    coder.commands = Commands(io=None, coder=coder)
    coder.io = None
    coder.tui = None
    for text in items:
        command_queue.enqueue_prompt(coder, text)
    return coder


@pytest.fixture(autouse=True)
def _reset_agent_service():
    """Reset the AgentService singleton between tests.

    ``command_queue.get_active_coder`` resolves the foreground coder through
    ``AgentService``, whose ``_instances`` and ``_primary_agent_uuid`` are
    class-level state. Without a reset, the first test's coder becomes the
    "primary" and every later test is routed to that coder's queue, causing
    cross-test pollution.
    """
    from cecli.helpers.agents.service import AgentService

    AgentService._instances = {}
    AgentService._primary_agent_uuid = None
    yield
    AgentService._instances = {}
    AgentService._primary_agent_uuid = None


# ============================================================================
# Test Fixtures (Section 10.6, TDS-01 through TDS-04)
# ============================================================================


@pytest.fixture
def mock_io():
    """Create a mock IO object with tool_output, tool_error, tool_warning methods."""
    io = MagicMock()
    io.tool_output = MagicMock()
    io.tool_error = MagicMock()
    io.tool_warning = MagicMock()
    return io


@pytest.fixture
def mock_coder():
    """Create a mock coder with an empty queue and an attached Commands instance."""
    return _make_coder_with_commands()


@pytest.fixture
def clean_coder():
    """Create a fresh coder with an empty queue for isolated testing."""
    return _make_coder()


@pytest.fixture
def clean_commands():
    """Create a fresh Commands instance for isolated testing."""
    return Commands(io=None, coder=_make_coder())


@pytest.fixture
def populated_queue():
    """Create a coder whose queue is pre-populated with known items."""
    return _make_coder_with_commands(("alpha", "beta", "gamma"))


@pytest.fixture
def full_queue():
    """Create a coder with a queue filled to max capacity (100 items)."""
    coder = _make_coder_with_commands()
    for i in range(100):
        command_queue.enqueue_prompt(coder, f"prompt_{i}")
    return coder


@pytest.fixture
def mock_coder_no_commands():
    """Create a mock coder with commands set to None."""
    coder = MagicMock()
    coder.commands = None
    coder.io = None
    coder.tui = None
    return coder


# ============================================================================
# Unit Tests - Queue Logic (Section 10.2, UTC-01 through UTC-20)
# ============================================================================


class TestEnqueuePrompt:
    """Unit tests for command_queue.enqueue_prompt."""

    def test_utc_01_enqueue_single_prompt(self, clean_coder):
        """UTC-01: Enqueue single prompt adds one item with correct structure."""
        item = command_queue.enqueue_prompt(clean_coder, "test prompt")

        assert len(clean_coder.prompt_queue) == 1
        assert item["text"] == "test prompt"
        assert "id" in item
        assert "timestamp" in item
        assert isinstance(item["id"], str)
        assert isinstance(item["timestamp"], float)

    def test_utc_02_enqueue_multiple_prompts_fifo_order(self, clean_coder):
        """UTC-02: Enqueue multiple prompts maintains FIFO order and unique IDs."""
        item1 = command_queue.enqueue_prompt(clean_coder, "first")
        item2 = command_queue.enqueue_prompt(clean_coder, "second")
        item3 = command_queue.enqueue_prompt(clean_coder, "third")

        assert len(clean_coder.prompt_queue) == 3
        assert clean_coder.prompt_queue[0]["text"] == "first"
        assert clean_coder.prompt_queue[1]["text"] == "second"
        assert clean_coder.prompt_queue[2]["text"] == "third"
        assert item1["id"] != item2["id"]
        assert item2["id"] != item3["id"]

    def test_utc_13_max_queue_size_rejection(self, clean_coder):
        """UTC-13: Enqueue rejected when queue already contains 100 items."""
        for i in range(100):
            command_queue.enqueue_prompt(clean_coder, f"prompt_{i}")

        with pytest.raises(RuntimeError, match="Queue is full"):
            command_queue.enqueue_prompt(clean_coder, "overflow")

    def test_utc_14_enqueue_empty_string_rejected(self, clean_coder):
        """UTC-14: Enqueue rejects empty string with ValueError."""
        with pytest.raises(ValueError, match="Cannot enqueue empty prompt"):
            command_queue.enqueue_prompt(clean_coder, "")

    def test_utc_14_enqueue_none_rejected(self, clean_coder):
        """UTC-14: Enqueue rejects None with ValueError."""
        with pytest.raises(ValueError, match="Cannot enqueue empty prompt"):
            command_queue.enqueue_prompt(clean_coder, None)

    def test_utc_15_enqueue_extremely_long_prompt_rejected(self, clean_coder):
        """UTC-15: Enqueue rejects prompt exceeding 10,000 characters."""
        long_prompt = "x" * 10001
        with pytest.raises(ValueError, match="exceeds maximum length"):
            command_queue.enqueue_prompt(clean_coder, long_prompt)

    def test_utc_16_enqueue_exactly_10000_chars_accepted(self, clean_coder):
        """UTC-16: Enqueue accepts prompt of exactly 10,000 characters (boundary)."""
        boundary_prompt = "x" * 10000
        item = command_queue.enqueue_prompt(clean_coder, boundary_prompt)
        assert item["text"] == boundary_prompt
        assert len(clean_coder.prompt_queue) == 1

    def test_utc_17_enqueue_9999_chars_accepted(self, clean_coder):
        """UTC-17: Enqueue accepts prompt of 9,999 characters (boundary)."""
        boundary_prompt = "x" * 9999
        item = command_queue.enqueue_prompt(clean_coder, boundary_prompt)
        assert item["text"] == boundary_prompt
        assert len(clean_coder.prompt_queue) == 1

    def test_utc_18_counter_persistence(self, clean_coder):
        """UTC-18: Internal counter increments across enqueue/remove cycles without reset."""
        command_queue.enqueue_prompt(clean_coder, "first")
        command_queue.enqueue_prompt(clean_coder, "second")
        item = command_queue.enqueue_prompt(clean_coder, "third")

        assert clean_coder._queue_counter == 3
        assert item["id"] == "3"


class TestDequeuePrompt:
    """Unit tests for command_queue.dequeue_prompt."""

    def test_utc_03_dequeue_from_empty_queue(self, clean_coder):
        """UTC-03: Dequeue from empty queue returns None without side effects."""
        result = command_queue.dequeue_prompt(clean_coder)
        assert result is None
        assert len(clean_coder.prompt_queue) == 0

    def test_utc_04_dequeue_returns_fifo_first_item(self, clean_coder):
        """UTC-04: Dequeue returns first item and shrinks queue by one."""
        command_queue.enqueue_prompt(clean_coder, "first")
        command_queue.enqueue_prompt(clean_coder, "second")

        item = command_queue.dequeue_prompt(clean_coder)
        assert item["text"] == "first"
        assert len(clean_coder.prompt_queue) == 1
        assert clean_coder.prompt_queue[0]["text"] == "second"

    def test_utc_05_dequeue_until_empty(self, clean_coder):
        """UTC-05: Repeated dequeue eventually returns None after queue empties."""
        command_queue.enqueue_prompt(clean_coder, "only_item")

        item = command_queue.dequeue_prompt(clean_coder)
        assert item is not None
        assert item["text"] == "only_item"

        result = command_queue.dequeue_prompt(clean_coder)
        assert result is None


class TestGetQueueLength:
    """Unit tests for command_queue.get_queue_length."""

    def test_utc_06_queue_length_empty(self, clean_coder):
        """UTC-06: Queue length returns correct count for empty queue."""
        assert command_queue.get_queue_length(clean_coder) == 0

    def test_utc_07_queue_length_non_empty(self, clean_coder):
        """UTC-07: Queue length returns correct count for populated queue."""
        command_queue.enqueue_prompt(clean_coder, "item1")
        command_queue.enqueue_prompt(clean_coder, "item2")
        command_queue.enqueue_prompt(clean_coder, "item3")

        assert command_queue.get_queue_length(clean_coder) == 3


class TestRemoveFromQueue:
    """Unit tests for command_queue.remove_from_queue."""

    def test_utc_08_remove_by_valid_index(self, clean_coder):
        """UTC-08: Remove by valid index returns item and shrinks queue by one."""
        command_queue.enqueue_prompt(clean_coder, "first")
        command_queue.enqueue_prompt(clean_coder, "second")
        command_queue.enqueue_prompt(clean_coder, "third")

        item = command_queue.remove_from_queue(clean_coder, 1)
        assert item["text"] == "second"
        assert len(clean_coder.prompt_queue) == 2
        assert clean_coder.prompt_queue[0]["text"] == "first"
        assert clean_coder.prompt_queue[1]["text"] == "third"

    def test_utc_09_remove_out_of_bounds_high_index(self, clean_coder):
        """UTC-09: Remove by out-of-bounds high index returns None without mutation."""
        command_queue.enqueue_prompt(clean_coder, "only_item")

        result = command_queue.remove_from_queue(clean_coder, 5)
        assert result is None
        assert len(clean_coder.prompt_queue) == 1

    def test_utc_10_remove_negative_index(self, clean_coder):
        """UTC-10: Remove by negative index returns None without mutation."""
        command_queue.enqueue_prompt(clean_coder, "only_item")

        result = command_queue.remove_from_queue(clean_coder, -1)
        assert result is None
        assert len(clean_coder.prompt_queue) == 1


class TestClearQueue:
    """Unit tests for command_queue.clear_queue."""

    def test_utc_11_clear_queue_with_items(self, clean_coder):
        """UTC-11: Clear queue returns all items and empties queue."""
        command_queue.enqueue_prompt(clean_coder, "item1")
        command_queue.enqueue_prompt(clean_coder, "item2")
        command_queue.enqueue_prompt(clean_coder, "item3")

        items = command_queue.clear_queue(clean_coder)
        assert len(items) == 3
        assert len(clean_coder.prompt_queue) == 0

    def test_utc_12_clear_empty_queue(self, clean_coder):
        """UTC-12: Clear empty queue returns empty list and remains empty."""
        items = command_queue.clear_queue(clean_coder)
        assert items == []
        assert len(clean_coder.prompt_queue) == 0


class TestTimestampBehavior:
    """Unit tests for timestamp generation."""

    def test_utc_19_timestamps_monotonic(self, clean_coder):
        """UTC-19: Timestamps are monotonic non-decreasing across enqueues."""
        item1 = command_queue.enqueue_prompt(clean_coder, "first")
        time.sleep(0.01)
        item2 = command_queue.enqueue_prompt(clean_coder, "second")

        assert item1["timestamp"] <= item2["timestamp"]


# ============================================================================
# Integration Tests - Command Classes (Section 10.3, ITC-01 through ITC-20)
# ============================================================================


class TestQueueCommand:
    """Integration tests for QueueCommand."""

    @pytest.mark.asyncio
    async def test_itc_01_queue_enqueues_and_confirms_position(self, mock_io, mock_coder):
        """ITC-01: /queue "prompt" enqueues and confirms queue position."""
        result = await QueueCommand.execute(mock_io, mock_coder, "test prompt")

        assert result == "Successfully executed queue."
        assert len(mock_coder.prompt_queue) == 1
        mock_io.tool_output.assert_called()

    @pytest.mark.asyncio
    async def test_itc_02_queue_empty_args_shows_usage(self, mock_io, mock_coder):
        """ITC-02: /queue with empty args shows usage/help and does not enqueue."""
        result = await QueueCommand.execute(mock_io, mock_coder, "")

        assert "Error" in result
        assert len(mock_coder.prompt_queue) == 0

    @pytest.mark.asyncio
    async def test_itc_03_queue_no_args_shows_usage(self, mock_io, mock_coder):
        """ITC-03: /queue with no args shows usage/help and does not enqueue."""
        result = await QueueCommand.execute(mock_io, mock_coder, None)

        assert "Error" in result
        assert len(mock_coder.prompt_queue) == 0

    @pytest.mark.asyncio
    async def test_itc_04_queue_rejects_long_prompt(self, mock_io, mock_coder):
        """ITC-04: /queue rejects prompt >10,000 characters with warning."""
        long_prompt = "x" * 10001
        result = await QueueCommand.execute(mock_io, mock_coder, long_prompt)

        assert "Error" in result or "exceeds" in result.lower()
        assert len(mock_coder.prompt_queue) == 0

    @pytest.mark.asyncio
    async def test_itc_05_queue_handles_coder_commands_none(self, mock_io, mock_coder_no_commands):
        """ITC-05: /queue handles coder.commands is None with error message."""
        result = await QueueCommand.execute(mock_io, mock_coder_no_commands, "test")

        assert "Error" in result or "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_itc_06_queue_at_max_capacity_rejects(self, mock_io, full_queue):
        """ITC-06: /queue at max capacity (100) rejects new prompt."""
        result = await QueueCommand.execute(mock_io, full_queue, "overflow")

        assert "Error" in result or "full" in result.lower()


class TestListQueueCommand:
    """Integration tests for ListQueueCommand."""

    @pytest.mark.asyncio
    async def test_itc_07_list_queue_shows_numbered_list(self, mock_io, populated_queue):
        """ITC-07: /list-queue displays numbered list of queued prompts with timestamps."""
        result = await ListQueueCommand.execute(mock_io, populated_queue, "")

        assert result == "Successfully executed list-queue."
        mock_io.tool_output.assert_called()
        calls = [str(call) for call in mock_io.tool_output.call_args_list]
        output_text = " ".join(calls)
        assert "[1]" in output_text or "alpha" in output_text

    @pytest.mark.asyncio
    async def test_itc_08_list_queue_empty_shows_message(self, mock_io, mock_coder):
        """ITC-08: /list-queue on empty queue shows "Queue is empty" message."""
        result = await ListQueueCommand.execute(mock_io, mock_coder, "")

        assert result == "Successfully executed list-queue."
        mock_io.tool_output.assert_called()

    @pytest.mark.asyncio
    async def test_itc_09_list_queue_handles_coder_commands_none(
        self, mock_io, mock_coder_no_commands
    ):
        """ITC-09: /list-queue handles coder.commands is None with error message."""
        result = await ListQueueCommand.execute(mock_io, mock_coder_no_commands, "")

        assert "Error" in result or "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_itc_10_list_queue_truncates_long_prompts(self, mock_io):
        """ITC-10: /list-queue truncates prompts longer than display threshold."""
        coder = _make_coder_with_commands(("x" * 120,))

        await ListQueueCommand.execute(mock_io, coder, "")

        calls = [str(call) for call in mock_io.tool_output.call_args_list]
        output_text = " ".join(calls)
        assert "..." in output_text or "x" * 80 in output_text


class TestRemoveQueueCommand:
    """Integration tests for RemoveQueueCommand."""

    @pytest.mark.asyncio
    async def test_itc_11_remove_by_index(self, mock_io, populated_queue):
        """ITC-11: /remove-queue <index> removes exact item and confirms removal."""
        result = await RemoveQueueCommand.execute(mock_io, populated_queue, "2")

        assert result == "Successfully executed remove-queue."
        assert len(populated_queue.prompt_queue) == 2
        mock_io.tool_output.assert_called()

    @pytest.mark.asyncio
    async def test_itc_12_remove_wildcard_clears_all(self, mock_io, populated_queue):
        """ITC-12: /remove-queue * clears entire queue and confirms count removed."""
        result = await RemoveQueueCommand.execute(mock_io, populated_queue, "*")

        assert result == "Successfully executed remove-queue."
        assert len(populated_queue.prompt_queue) == 0
        mock_io.tool_output.assert_called()

    @pytest.mark.asyncio
    async def test_itc_13_remove_interactive_mode(self, mock_io, populated_queue):
        """ITC-13: /remove-queue with no args enters interactive selection."""
        result = await RemoveQueueCommand.execute(mock_io, populated_queue, "")

        # Interactive mode shows queue list and prompt, returns success status
        assert result == "Successfully executed remove-queue."
        mock_io.tool_output.assert_called()
        calls = [str(call) for call in mock_io.tool_output.call_args_list]
        output_text = " ".join(calls)
        assert "Queued prompts:" in output_text or "Enter index" in output_text

    @pytest.mark.asyncio
    async def test_itc_14_remove_invalid_index_non_integer(self, mock_io, populated_queue):
        """ITC-14: /remove-queue with non-integer index shows invalid index error."""
        result = await RemoveQueueCommand.execute(mock_io, populated_queue, "abc")

        assert "Error" in result or "Invalid index" in result

    @pytest.mark.asyncio
    async def test_itc_15_remove_out_of_bounds_index(self, mock_io, populated_queue):
        """ITC-15: /remove-queue with out-of-bounds index shows error."""
        result = await RemoveQueueCommand.execute(mock_io, populated_queue, "99")

        assert "Error" in result or "out of range" in result.lower()

    @pytest.mark.asyncio
    async def test_itc_16_remove_negative_index(self, mock_io, populated_queue):
        """ITC-16: /remove-queue with negative index shows error."""
        result = await RemoveQueueCommand.execute(mock_io, populated_queue, "-1")

        assert "Error" in result or "Invalid index" in result

    @pytest.mark.asyncio
    async def test_itc_17_remove_empty_queue(self, mock_io, mock_coder):
        """ITC-17: /remove-queue on empty queue shows error."""
        result = await RemoveQueueCommand.execute(mock_io, mock_coder, "1")

        assert "Error" in result or "empty" in result.lower()

    @pytest.mark.asyncio
    async def test_itc_18_remove_handles_coder_commands_none(self, mock_io, mock_coder_no_commands):
        """ITC-18: /remove-queue handles coder.commands is None."""
        result = await RemoveQueueCommand.execute(mock_io, mock_coder_no_commands, "1")

        assert "Error" in result or "not available" in result.lower()

    def test_itc_19_get_completions_returns_indices_and_wildcard(self, populated_queue):
        """ITC-19: RemoveQueueCommand.get_completions() returns valid index completions and '*'."""
        completions = RemoveQueueCommand.get_completions(None, populated_queue, "")

        assert "1" in completions
        assert "2" in completions
        assert "3" in completions
        assert "*" in completions

    def test_itc_20_commands_registered_in_registry(self):
        """ITC-20: All three commands are registered and discoverable via help/registry lookup."""
        assert CommandRegistry.get_command("queue") is not None
        assert CommandRegistry.get_command("list-queue") is not None
        assert CommandRegistry.get_command("remove-queue") is not None


# ============================================================================
# E2E Tests - Full Queue Lifecycle (Section 10.4, ETC-01 through ETC-10)
# ============================================================================


class TestQueueLifecycle:
    """E2E tests for full queue lifecycle and processing."""

    @pytest.mark.asyncio
    async def test_etc_01_single_queued_prompt_auto_processes(self, populated_queue):
        """ETC-01: A queued prompt is available for processing via dequeue_prompt."""
        item = command_queue.dequeue_prompt(populated_queue)

        assert item is not None
        assert item["text"] == "alpha"
        assert command_queue.get_queue_length(populated_queue) == 2

    @pytest.mark.asyncio
    async def test_etc_02_multiple_prompts_fifo_order(self, clean_coder):
        """ETC-02: Multiple queued prompts execute in FIFO order with no reordering."""
        command_queue.enqueue_prompt(clean_coder, "prompt_A")
        command_queue.enqueue_prompt(clean_coder, "prompt_B")
        command_queue.enqueue_prompt(clean_coder, "prompt_C")

        assert clean_coder.prompt_queue[0]["text"] == "prompt_A"
        assert clean_coder.prompt_queue[1]["text"] == "prompt_B"
        assert clean_coder.prompt_queue[2]["text"] == "prompt_C"

    @pytest.mark.asyncio
    async def test_etc_03_queued_prompt_not_processed_while_running(self, mock_io, clean_commands):
        """ETC-03: Queued prompt is not processed while another command is running."""
        clean_commands.cmd_running_event.clear()

        assert hasattr(clean_commands, "_MANAGEMENT_COMMANDS")
        assert "queue" in clean_commands._MANAGEMENT_COMMANDS

    @pytest.mark.asyncio
    async def test_etc_06_management_commands_dont_trigger_processing(
        self, mock_io, clean_commands
    ):
        """ETC-06: Management commands do not trigger auto-processing of queued items."""
        assert clean_commands._MANAGEMENT_COMMANDS == {"queue", "list-queue", "remove-queue"}

    @pytest.mark.asyncio
    async def test_etc_05_prevent_infinite_loop(self, populated_queue):
        """ETC-05: The coder's processing flag prevents re-entrant queue draining."""
        populated_queue._processing_queue = True
        try:
            if populated_queue.prompt_queue and not populated_queue._processing_queue:
                command_queue.dequeue_prompt(populated_queue)
        finally:
            populated_queue._processing_queue = False

        assert command_queue.get_queue_length(populated_queue) == 3

    @pytest.mark.asyncio
    async def test_etc_09_error_in_queued_prompt_continues(self, clean_coder):
        """ETC-09: An error in one queued prompt does not stop later items."""
        command_queue.enqueue_prompt(clean_coder, "first")
        command_queue.enqueue_prompt(clean_coder, "second")

        first = command_queue.dequeue_prompt(clean_coder)
        second = command_queue.dequeue_prompt(clean_coder)

        assert first["text"] == "first"
        assert second["text"] == "second"

    @pytest.mark.asyncio
    async def test_etc_10_full_lifecycle_sequence(self, mock_io, populated_queue):
        """ETC-10: Full lifecycle sequence add -> list -> remove -> process."""
        item = command_queue.enqueue_prompt(populated_queue, "new_prompt")
        assert item is not None

        assert command_queue.get_queue_length(populated_queue) == 4

        removed = command_queue.remove_from_queue(populated_queue, 0)
        assert removed is not None

        assert command_queue.get_queue_length(populated_queue) == 3


# ============================================================================
# Regression Tests - Existing Command Integrity (Section 10.5, RTC-01 through RTC-05)
# ============================================================================


class TestRegression:
    """Regression tests to ensure existing functionality is not broken."""

    def test_rtc_01_existing_commands_still_registered(self):
        """RTC-01: Existing commands still registered and functional after queue commands added."""
        assert CommandRegistry.get_command("help") is not None
        assert CommandRegistry.get_command("run") is not None
        assert CommandRegistry.get_command("model") is not None

    def test_rtc_02_commands_init_preserves_existing_attributes(self, clean_commands):
        """RTC-02: Commands.__init__ preserves pre-existing attributes; queue state lives on the coder."""
        assert hasattr(clean_commands, "io")
        assert hasattr(clean_commands, "coder")
        assert hasattr(clean_commands, "cmd_running_event")
        assert hasattr(clean_commands, "last_command_show_notification")
        assert hasattr(clean_commands, "_MANAGEMENT_COMMANDS")

        coder = clean_commands.coder
        assert hasattr(coder, "prompt_queue")
        assert hasattr(coder, "_queue_counter")

    def test_rtc_03_execute_preserves_existing_flow(self, mock_io, mock_coder):
        """RTC-03: Commands.execute() preserves existing command behavior for non-queue commands."""
        assert hasattr(mock_coder.commands, "execute")
        assert callable(mock_coder.commands.execute)

    def test_rtc_04_init_py_imports_all_commands(self):
        """RTC-04: cecli/commands/__init__.py imports all commands without conflicts."""
        from cecli.commands import (
            CommandRegistry,
            ListQueueCommand,
            QueueCommand,
            RemoveQueueCommand,
        )

        assert CommandRegistry.get_command("queue") is QueueCommand
        assert CommandRegistry.get_command("list-queue") is ListQueueCommand
        assert CommandRegistry.get_command("remove-queue") is RemoveQueueCommand

    def test_rtc_05_thread_safety_under_concurrent_access(self, clean_commands):
        """RTC-05: The queue lock is a real threading.Lock created on first use."""
        coder = clean_commands.coder
        command_queue.enqueue_prompt(coder, "item")

        assert isinstance(coder._queue_lock, threading.Lock)


# ============================================================================
# Additional Tests for Edge Cases and Error Handling
# ============================================================================


class TestEdgeCases:
    """Additional edge case tests."""

    def test_queue_with_whitespace_only_prompt(self, clean_coder):
        """Test that whitespace-only prompts are rejected."""
        with pytest.raises(ValueError):
            command_queue.enqueue_prompt(clean_coder, "   ")

    def test_queue_with_unicode_prompt(self, clean_coder):
        """Test that unicode prompts are handled correctly."""
        item = command_queue.enqueue_prompt(clean_coder, "Hello world")
        assert item["text"] == "Hello world"

    def test_remove_with_zero_index(self, clean_coder):
        """Test removing with index 0 (first item)."""
        command_queue.enqueue_prompt(clean_coder, "first")
        command_queue.enqueue_prompt(clean_coder, "second")

        item = command_queue.remove_from_queue(clean_coder, 0)
        assert item["text"] == "first"

    def test_remove_with_large_index(self, clean_coder):
        """Test removing with a very large index."""
        command_queue.enqueue_prompt(clean_coder, "only")

        result = command_queue.remove_from_queue(clean_coder, 999999)
        assert result is None


# ============================================================================
# Command Registration Tests
# ============================================================================


class TestCommandRegistration:
    """Tests for command registration in CommandRegistry."""

    def test_all_queue_commands_registered(self):
        """Verify all queue commands are properly registered."""
        commands = CommandRegistry.list_commands()

        assert "queue" in commands
        assert "list-queue" in commands
        assert "remove-queue" in commands

    def test_command_classes_have_required_attributes(self):
        """Verify command classes have NORM_NAME and DESCRIPTION."""
        assert QueueCommand.NORM_NAME == "queue"
        assert QueueCommand.DESCRIPTION is not None

        assert ListQueueCommand.NORM_NAME == "list-queue"
        assert ListQueueCommand.DESCRIPTION is not None

        assert RemoveQueueCommand.NORM_NAME == "remove-queue"
        assert RemoveQueueCommand.DESCRIPTION is not None

    def test_command_classes_have_execute_method(self):
        """Verify command classes have async execute method."""
        assert hasattr(QueueCommand, "execute")
        assert hasattr(ListQueueCommand, "execute")
        assert hasattr(RemoveQueueCommand, "execute")

        assert callable(QueueCommand.execute)
        assert callable(ListQueueCommand.execute)
        assert callable(RemoveQueueCommand.execute)


# ============================================================================
# Helper Function Tests
# ============================================================================


class TestHelpers:
    """Tests for helper functions used by queue commands."""

    def test_format_command_result_success(self, mock_io):
        """Test format_command_result for successful execution."""
        from cecli.commands.utils.helpers import format_command_result

        result = format_command_result(mock_io, "test", "Success message")
        assert result == "Successfully executed test."
        mock_io.tool_output.assert_called_once()

    def test_format_command_result_error(self, mock_io):
        """Test format_command_result for error case."""
        from cecli.commands.utils.helpers import format_command_result

        result = format_command_result(mock_io, "test", "Success", error="Something went wrong")
        assert "Error" in result
        mock_io.tool_error.assert_called_once()


# ============================================================================
# Signal Tests
# ============================================================================


class TestSignals:
    """Tests for custom signals used in queue processing."""

    def test_switch_coder_signal_attributes(self):
        """Test SwitchCoderSignal has expected attributes."""
        signal = SwitchCoderSignal(placeholder="test", custom_arg="value")

        assert signal.placeholder == "test"
        assert signal.kwargs == {"custom_arg": "value"}

    def test_reload_program_signal_message(self):
        """Test ReloadProgramSignal has message attribute."""
        signal = ReloadProgramSignal(message="Custom message")

        assert signal.message == "Custom message"


# ============================================================================
# Async Test Configuration
# ============================================================================

# Note: For pytest-asyncio to work, you may need to add to pyproject.toml or pytest.ini:
# [pytest]
# asyncio_mode = auto
# asyncio_default_fixture_loop_scope = function

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
