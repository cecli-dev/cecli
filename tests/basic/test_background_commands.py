"""
Tests for background command management functionality.
"""

import sys
import types


def _install_stubs():
    """Install stub modules to avoid import errors during testing."""
    if "subprocess" not in sys.modules:
        subprocess_module = types.ModuleType("subprocess")

        class _DummyPopen:
            def __init__(self, *args, **kwargs):
                self.returncode = None
                self.stdout = _DummyPipe()
                self.stderr = _DummyPipe()
                self.stdin = None

            def poll(self):
                return self.returncode

            def terminate(self):
                self.returncode = -1
                return None

            def kill(self):
                self.returncode = -2
                return None

            def wait(self, timeout=None):
                return self.returncode

        class _DummyPipe:
            def __init__(self):
                self.lines = []

            def readline(self):
                if self.lines:
                    return self.lines.pop(0)
                return ""

        subprocess_module.Popen = _DummyPopen
        subprocess_module.TimeoutExpired = Exception
        sys.modules["subprocess"] = subprocess_module


_install_stubs()

from cecli.helpers.background_commands import (  # noqa: E402
    BackgroundProcess,
    CircularBuffer,
)


def test_circular_buffer_basic_operations():
    """Test basic CircularBuffer operations: append, get_all, clear."""
    buffer = CircularBuffer(max_size=11)
    buffer.append("Hello")
    buffer.append(" ")
    buffer.append("World")

    assert buffer.get_all() == "Hello World"
    assert buffer.size() == 11

    buffer.clear()
    assert buffer.get_all() == ""
    assert buffer.size() == 0
    assert buffer.total_added == 0

    buffer.append("New")
    assert buffer.get_all() == "New"
    assert buffer.size() == 3


def test_circular_buffer_max_size():
    """Evict characters, even when overflow trims only part of an old chunk."""
    buffer = CircularBuffer(max_size=5)
    buffer.append("12345")
    assert buffer.get_all() == "12345"
    assert buffer.size() == 5

    buffer.append("67")
    assert buffer.get_all() == "34567"
    assert buffer.size() == 5

    buffer.append("89012")
    assert buffer.get_all() == "89012"
    assert buffer.size() == 5
    assert buffer.total_added == 12

    buffer.clear()
    for i in range(10):
        buffer.append(str(i))
        assert buffer.size() <= 5

    assert buffer.get_all() == "56789"


def test_circular_buffer_get_new_output():
    """Incremental positions include evicted characters, but output stays bounded."""
    buffer = CircularBuffer(max_size=10)
    buffer.append("Hello")
    buffer.append(" World")

    new_output, new_position = buffer.get_new_output(0)
    assert new_output == "ello World"
    assert new_position == 11

    buffer.append("!")
    new_output, new_position = buffer.get_new_output(new_position)
    assert new_output == "!"
    assert new_position == 12

    new_output, new_position = buffer.get_new_output(new_position)
    assert new_output == ""
    assert new_position == 12

    buffer.append("0123456789ABCDE")
    assert buffer.get_new_output(new_position) == ("56789ABCDE", 27)


def test_circular_buffer_oversized_append():
    """A single large chunk must not bypass the character limit."""
    buffer = CircularBuffer(max_size=4096)
    buffer.append("old output")
    text = "0123456789" * 10_000
    buffer.append(text)

    assert buffer.size() == 4096
    assert buffer.get_all() == text[-4096:]
    assert buffer.get_new_output(0) == (text[-4096:], len("old output") + len(text))


def test_circular_buffer_empty_append_preserves_full_buffer():
    buffer = CircularBuffer(max_size=3)
    buffer.append("abc")
    buffer.append("")

    assert buffer.get_all() == "abc"
    assert buffer.size() == 3
    assert buffer.total_added == 3


def test_circular_buffer_zero_capacity():
    buffer = CircularBuffer(max_size=0)
    buffer.append("discarded")
    buffer.append("")

    assert buffer.get_all() == ""
    assert buffer.size() == 0
    assert buffer.get_new_output(0) == ("", 9)


def test_circular_buffer_unicode_characters():
    """Capacity measures Python characters rather than encoded bytes."""
    buffer = CircularBuffer(max_size=3)
    buffer.append("aé中")
    buffer.append("🙂ß")

    assert buffer.get_all() == "中🙂ß"
    assert buffer.size() == 3
    assert buffer.get_new_output(0) == ("中🙂ß", 5)


def test_circular_buffer_get_all_clear_resets_accounting():
    buffer = CircularBuffer(max_size=3)
    buffer.append("abcde")

    assert buffer.get_all(clear=True) == "cde"
    assert buffer.size() == 0
    assert buffer.total_added == 0
    assert buffer.get_new_output(0) == ("", 0)

    buffer.append("xy")
    assert buffer.get_all() == "xy"
    assert buffer.size() == 2
    assert buffer.get_new_output(0) == ("xy", 2)


def test_background_process_basic():
    """Test basic BackgroundProcess functionality."""
    # Create a mock process

    class MockProcess:
        def __init__(self):
            self.returncode = None
            self.stdout = MockPipe(["Line 1\n", "Line 2\n"])
            self.stderr = MockPipe([])

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = -1
            return None

        def kill(self):
            self.returncode = -2
            return None

        def wait(self, timeout=None):
            return self.returncode

    class MockPipe:
        def __init__(self, lines):
            self.lines = lines

        def readline(self):
            if self.lines:
                return self.lines.pop(0)
            return ""

    # Create BackgroundProcess
    buffer = CircularBuffer(max_size=100)
    process = MockProcess()
    bg_process = BackgroundProcess("test command", process, buffer)

    # Give reader thread a moment to read output
    import time

    time.sleep(0.1)

    # Check output
    output = bg_process.get_output()
    assert "Line 1" in output
    assert "Line 2" in output

    # Check is_alive
    assert bg_process.is_alive() is True

    # Stop the process
    # Note: stop() calls terminate() which sets returncode = -1 in our mock
    success, output, exit_code = bg_process.stop()
    assert success is True
    assert exit_code == -1  # terminate() sets returncode to -1 in MockProcess
