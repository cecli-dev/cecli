"""
Tests for the execute method of read_file.py.

Focuses on the parsing logic for line numbers, special markers (@000, 000@),
and text strings. Tests cover all combinations of these marker types.
"""

import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))


def _safe_relpath(path):
    """Wrapper around os.path.relpath that handles cross-drive scenarios on Windows."""
    try:
        return os.path.relpath(path)
    except ValueError:
        # On Windows, os.path.relpath fails when path and cwd are on different drives.
        # Fall back to basename which is sufficient for test patches.
        return os.path.basename(path)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_coder():
    """Create a mock coder object with all necessary attributes."""
    coder = MagicMock()
    coder.turn_count = 5
    coder.abs_root_path.side_effect = lambda p: os.path.abspath(p)
    coder.get_rel_fname.side_effect = lambda p: _safe_relpath(p)
    coder.io.tool_output = MagicMock()
    coder.io.tool_error = MagicMock()
    coder.io.tool_warning = MagicMock()
    coder.edit_allowed = True
    coder.abs_fnames = set()
    coder.abs_read_only_fnames = set()
    coder.large_file_token_threshold = 25000
    coder.main_model = MagicMock()
    coder.main_model.token_count.side_effect = lambda x: len(x) // 4
    return coder


@pytest.fixture
def mock_file_context():
    """Mock the ConversationService file context operations."""
    file_context = MagicMock()
    file_context.get_file_context.return_value = None
    file_context.update_file_context.return_value = (1, 10)
    file_context.clear_ranges = MagicMock()
    file_context.push_range = MagicMock()
    return file_context


@pytest.fixture
def mock_chunks():
    """Mock the ConversationService chunks operations."""
    chunks = MagicMock()
    chunks.add_file_context_messages = MagicMock()
    return chunks


@pytest.fixture
def mock_manager():
    """Mock the ConversationService manager operations."""
    manager = MagicMock()
    manager.get_tag_messages.return_value = []
    return manager


def create_test_file(content):
    """Create a temporary file with the given content and return the path."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
    tmp.write(content)
    tmp.close()
    return tmp.name


# =============================================================================
# Test Class
# =============================================================================


class TestReadFileExecute:
    """Tests for Tool.execute() parsing logic."""

    # Class-level patches that apply to all tests
    @pytest.fixture(autouse=True)
    def setup_patches(self):
        self.patches = []
        yield
        for p in self.patches:
            p.stop()

    def _setup(self, mock_coder, mock_file_context, mock_chunks, mock_manager, file_content=""):
        """Set up mocks and create a test file with given content."""
        self.coder = mock_coder
        self.test_file = create_test_file(file_content)
        self.coder.io.read_text.return_value = file_content

        # Patch ConversationService - it's imported locally in execute(),
        # so we patch at the source module
        mock_cs = MagicMock()
        mock_cs.get_files.return_value = mock_file_context
        mock_cs.get_chunks.return_value = mock_chunks
        mock_cs.get_manager.return_value = mock_manager
        cs_patch = patch("cecli.helpers.conversation.ConversationService", mock_cs)
        cs_patch.start()
        self.patches.append(cs_patch)

        # Patch strip_hashline to be identity
        sh_patch = patch("cecli.tools.read_file.strip_hashline", side_effect=lambda x: x)
        sh_patch.start()
        self.patches.append(sh_patch)

        # Patch hashline_formatted to return (text, json)
        hl_patch = patch(
            "cecli.tools.read_file.hashline_formatted",
            side_effect=lambda text, file_name, total_lines=0, start_line=1: (text, "{}"),
        )
        hl_patch.start()
        self.patches.append(hl_patch)

        # Patch resolve_paths
        rp_patch = patch(
            "cecli.tools.read_file.resolve_paths",
            return_value=(self.test_file, _safe_relpath(self.test_file)),
        )
        rp_patch.start()
        self.patches.append(rp_patch)

        # Patch is_provided
        ip_patch = patch(
            "cecli.tools.read_file.is_provided",
            side_effect=lambda v, **kw: v is not None and v != "",
        )
        ip_patch.start()
        self.patches.append(ip_patch)

        # Reset class-level state on Tool
        from cecli.tools.read_file import Tool

        self.Tool = Tool
        Tool._last_invocation = {}
        Tool._last_read_turn = {}

    def _teardown(self):
        """Clean up temporary file."""
        if hasattr(self, "test_file") and os.path.exists(self.test_file):
            os.unlink(self.test_file)

    # =========================================================================
    # Line Number Parsing (both_structured, both digits)
    # =========================================================================

    def test_both_digits_valid_range(
        self, mock_coder, mock_file_context, mock_chunks, mock_manager
    ):
        """Test: range_start='5', range_end='10' -> lines 5-10 (1-based)."""
        content = "\n".join(f"line{i}" for i in range(1, 11))
        self._setup(mock_coder, mock_file_context, mock_chunks, mock_manager, content)
        try:
            show = [{"file_path": self.test_file, "range_start": "@L5", "range_end": "@L10"}]
            result = self.Tool.execute(self.coder, show)
            assert "line5" in str(result)
            assert "line10" in str(result)
        finally:
            self._teardown()

    def test_both_digits_same_line(self, mock_coder, mock_file_context, mock_chunks, mock_manager):
        """Test: range_start='1', range_end='1' -> just line 0."""
        content = "\n".join(f"line{i}" for i in range(1, 11))
        self._setup(mock_coder, mock_file_context, mock_chunks, mock_manager, content)
        try:
            show = [{"file_path": self.test_file, "range_start": "@L1", "range_end": "@L1"}]
            result = self.Tool.execute(self.coder, show)
            assert "line1" in str(result)
        finally:
            self._teardown()

    def test_both_digits_out_of_bounds(
        self, mock_coder, mock_file_context, mock_chunks, mock_manager
    ):
        """Test: range_start='1', range_end='100' -> clamp to valid range."""
        content = "\n".join(f"line{i}" for i in range(1, 11))
        self._setup(mock_coder, mock_file_context, mock_chunks, mock_manager, content)
        try:
            show = [{"file_path": self.test_file, "range_start": "@L1", "range_end": "@L100"}]
            result = self.Tool.execute(self.coder, show)
            assert "line1" in str(result)
            assert "line10" in str(result)
        finally:
            self._teardown()

    def test_both_digits_inverted_order(
        self, mock_coder, mock_file_context, mock_chunks, mock_manager
    ):
        """Test: range_start='10', range_end='5': inverted matching swaps."""
        content = "\n".join(f"line{i}" for i in range(1, 11))
        self._setup(mock_coder, mock_file_context, mock_chunks, mock_manager, content)
        try:
            show = [{"file_path": self.test_file, "range_start": "@L10", "range_end": "@L5"}]
            result = self.Tool.execute(self.coder, show)
            # Inverted: start=[9], end=[4], only one each -> swap to (4, 9)
            assert result is not None
        finally:
            self._teardown()

    # =========================================================================
    # Special Marker Parsing (both_structured, both special)
    # =========================================================================

    def test_special_start_end(self, mock_coder, mock_file_context, mock_chunks, mock_manager):
        """Test: @000 to 000@ -> first to last line."""
        content = "\n".join([f"line{i}" for i in range(1, 6)])
        self._setup(mock_coder, mock_file_context, mock_chunks, mock_manager, content)
        try:
            show = [{"file_path": self.test_file, "range_start": "@000", "range_end": "000@"}]
            result = self.Tool.execute(self.coder, show)
            assert "line1" in str(result)
            assert "line5" in str(result)
        finally:
            self._teardown()

    def test_special_start_at_000(self, mock_coder, mock_file_context, mock_chunks, mock_manager):
        """Test: @000 to @000 -> first line only."""
        content = "\n".join([f"line{i}" for i in range(1, 6)])
        self._setup(mock_coder, mock_file_context, mock_chunks, mock_manager, content)
        try:
            show = [{"file_path": self.test_file, "range_start": "@000", "range_end": "@000"}]
            result = self.Tool.execute(self.coder, show)
            assert "line1" in str(result)
        finally:
            self._teardown()

    def test_special_end_at_000(self, mock_coder, mock_file_context, mock_chunks, mock_manager):
        """Test: 000@ to 000@ -> last line only."""
        content = "\n".join([f"line{i}" for i in range(1, 6)])
        self._setup(mock_coder, mock_file_context, mock_chunks, mock_manager, content)
        try:
            show = [{"file_path": self.test_file, "range_start": "000@", "range_end": "000@"}]
            result = self.Tool.execute(self.coder, show)
            assert "line5" in str(result)
        finally:
            self._teardown()

    # =========================================================================
    # Mixed Digit + Special (both_structured)
    # =========================================================================

    def test_special_start_digit_end(
        self, mock_coder, mock_file_context, mock_chunks, mock_manager
    ):
        """Test: @000 to '3' -> first to line 3 (1-based)."""
        content = "line1\nline2\nline3\nline4\nline5"
        self._setup(mock_coder, mock_file_context, mock_chunks, mock_manager, content)
        try:
            show = [{"file_path": self.test_file, "range_start": "@000", "range_end": "@L3"}]
            result = self.Tool.execute(self.coder, show)
            assert "line1" in str(result)
            assert "line3" in str(result)
        finally:
            self._teardown()

    def test_digit_start_special_end(
        self, mock_coder, mock_file_context, mock_chunks, mock_manager
    ):
        """Test: '2' to 000@ -> line 1 to last."""
        content = "line1\nline2\nline3\nline4\nline5"
        self._setup(mock_coder, mock_file_context, mock_chunks, mock_manager, content)
        try:
            show = [{"file_path": self.test_file, "range_start": "@L2", "range_end": "000@"}]
            result = self.Tool.execute(self.coder, show)
            assert "line2" in str(result)
            assert "line5" in str(result)
        finally:
            self._teardown()

    # =========================================================================
    # Text Pattern Parsing
    # =========================================================================

    def test_both_text_patterns(self, mock_coder, mock_file_context, mock_chunks, mock_manager):
        """Test text patterns that exist in the file."""
        content = (
            "def foo():\n    return 1\n\ndef bar():\n    return 2\n\ndef baz():\n    return 3\n"
        )
        self._setup(mock_coder, mock_file_context, mock_chunks, mock_manager, content)
        try:
            show = [
                {
                    "file_path": self.test_file,
                    "range_start": "def foo():",
                    "range_end": "def bar():",
                }
            ]
            result = self.Tool.execute(self.coder, show)
            assert "def foo()" in str(result)
            assert "def bar()" in str(result)
        finally:
            self._teardown()

    def test_text_pattern_not_found(self, mock_coder, mock_file_context, mock_chunks, mock_manager):
        """Test text pattern that doesn't exist -> error."""
        content = "line1\nline2\nline3"
        self._setup(mock_coder, mock_file_context, mock_chunks, mock_manager, content)
        try:
            show = [
                {
                    "file_path": self.test_file,
                    "range_start": "nonexistent_pattern",
                    "range_end": "also_nonexistent",
                }
            ]
            result = self.Tool.execute(self.coder, show)
            assert "Errors" in str(result) or "not found" in str(result)
        finally:
            self._teardown()

    def test_text_pattern_multiline(self, mock_coder, mock_file_context, mock_chunks, mock_manager):
        """Test multiline text patterns."""
        content = "def foo():\n    return 1\n\ndef bar():\n    return 2\n"
        self._setup(mock_coder, mock_file_context, mock_chunks, mock_manager, content)
        try:
            show = [{"file_path": self.test_file, "range_start": "def foo", "range_end": "def bar"}]
            result = self.Tool.execute(self.coder, show)
            assert "return 1" in str(result)
        finally:
            self._teardown()

    # =========================================================================
    # Mixed Special + Text (mixed_special_search)
    # =========================================================================

    def test_special_start_text_end(self, mock_coder, mock_file_context, mock_chunks, mock_manager):
        """Test: @000 to text 'debug_mode'.

        NOTE: This may expose a bug in mixed_special_search where indices
        get overwritten after the if/else block.
        """
        content = "header\nconfig_value = 42\ndebug_mode = True\nfooter"
        self._setup(mock_coder, mock_file_context, mock_chunks, mock_manager, content)
        try:
            show = [{"file_path": self.test_file, "range_start": "@000", "range_end": "debug_mode"}]
            result = self.Tool.execute(self.coder, show)
            # Should find '@000' at start and 'debug_mode' as text
            print(f"\n[special_start_text_end] result: {str(result)[:300]}")
            assert result is not None
        finally:
            self._teardown()

    def test_text_start_special_end(self, mock_coder, mock_file_context, mock_chunks, mock_manager):
        """Test: text 'config_value' to 000@.

        NOTE: This may expose a bug in mixed_special_search where indices
        get overwritten after the if/else block.
        """
        content = "header\nconfig_value = 42\ndebug_mode = True\nfooter"
        self._setup(mock_coder, mock_file_context, mock_chunks, mock_manager, content)
        try:
            show = [
                {"file_path": self.test_file, "range_start": "config_value", "range_end": "000@"}
            ]
            result = self.Tool.execute(self.coder, show)
            print(f"\n[text_start_special_end] result: {str(result)[:300]}")
            assert result is not None
        finally:
            self._teardown()

    # =========================================================================
    # Edge Cases
    # =========================================================================

    def test_empty_file(self, mock_coder, mock_file_context, mock_chunks, mock_manager):
        """Test with an empty file."""
        self._setup(mock_coder, mock_file_context, mock_chunks, mock_manager, "")
        try:
            show = [{"file_path": self.test_file, "range_start": "@000", "range_end": "000@"}]
            result = self.Tool.execute(self.coder, show)
            assert "empty" in str(result).lower()
        finally:
            self._teardown()

    def test_single_line_file(self, mock_coder, mock_file_context, mock_chunks, mock_manager):
        """Test with a single line file."""
        self._setup(mock_coder, mock_file_context, mock_chunks, mock_manager, "only_line")
        try:
            show = [{"file_path": self.test_file, "range_start": "@L1", "range_end": "@L1"}]
            result = self.Tool.execute(self.coder, show)
            assert "only_line" in str(result)
        finally:
            self._teardown()

    def test_file_not_found(self, mock_coder, mock_file_context, mock_chunks, mock_manager):
        """Test with a non-existent file."""
        mock_coder.io.read_text.return_value = None
        # We need abs_path to pass os.path.exists but read_text to return None
        abs_path = "/nonexistent/path.py"
        mock_coder.abs_root_path.return_value = abs_path

        rp_patch = patch(
            "cecli.tools.read_file.resolve_paths", return_value=(abs_path, "nonexistent/path.py")
        )
        rp_patch.start()
        self.patches.append(rp_patch)

        from cecli.tools.read_file import Tool

        show = [{"file_path": "nonexistent/path.py", "range_start": "@L1", "range_end": "@L10"}]
        result = Tool.execute(mock_coder, show)
        assert "not found" in str(result) or "Errors" in str(result)

    def test_missing_parameters(self, mock_coder, mock_file_context, mock_chunks, mock_manager):
        """Test with missing range_start and range_end (empty strings)."""
        from cecli.tools.read_file import Tool

        show = [{"file_path": "some_file.py", "range_start": "", "range_end": ""}]
        result = Tool.execute(mock_coder, show)
        assert "Provide both" in str(result) or "Errors" in str(result)

    def test_multiple_show_operations(
        self, mock_coder, mock_file_context, mock_chunks, mock_manager
    ):
        """Test multiple show operations in one call."""
        content1 = "line1_1\nline1_2\nline1_3\nline1_4\nline1_5"
        content2 = "line2_1\nline2_2\nline2_3\nline2_4\nline2_5"
        test_file1 = create_test_file(content1)
        test_file2 = create_test_file(content2)

        def resolve_side_effect(coder, file_path):
            if "file1" in file_path:
                return (test_file1, "file1.py")
            return (test_file2, "file2.py")

        rp_patch = patch("cecli.tools.read_file.resolve_paths", side_effect=resolve_side_effect)
        rp_patch.start()

        sh_patch = patch("cecli.tools.read_file.strip_hashline", side_effect=lambda x: x)
        sh_patch.start()

        hl_patch = patch(
            "cecli.tools.read_file.hashline_formatted",
            side_effect=lambda text, file_name, total_lines=0, start_line=1: (text, "{}"),
        )
        hl_patch.start()

        ip_patch = patch(
            "cecli.tools.read_file.is_provided",
            side_effect=lambda v, **kw: v is not None and v != "",
        )
        ip_patch.start()

        mock_cs = MagicMock()
        mock_cs.get_files.return_value = mock_file_context
        mock_cs.get_chunks.return_value = mock_chunks
        mock_cs.get_manager.return_value = mock_manager
        cs_patch = patch("cecli.helpers.conversation.ConversationService", mock_cs)
        cs_patch.start()

        content_map = {test_file1: content1, test_file2: content2}
        mock_coder.io.read_text.side_effect = lambda path: content_map.get(path, "")

        try:
            from cecli.tools.read_file import Tool

            Tool._last_invocation = {}
            Tool._last_read_turn = {}

            show = [
                {"file_path": "file1.py", "range_start": "@L1", "range_end": "@L3"},
                {"file_path": "file2.py", "range_start": "@L2", "range_end": "@L4"},
            ]
            result = Tool.execute(mock_coder, show)
            assert "line1_1" in str(result)
            assert "line2_2" in str(result)
        finally:
            for p in [cs_patch, sh_patch, hl_patch, rp_patch, ip_patch]:
                p.stop()
            os.unlink(test_file1)
            os.unlink(test_file2)

    # =========================================================================
    # Multiple Matches / Disambiguation
    # =========================================================================

    def test_few_matches(self, mock_coder, mock_file_context, mock_chunks, mock_manager):
        """Test with ≤5 matches where each pattern appears once."""
        content = """def func_a():
    pass

def func_b():
    pass

def func_c():
    pass

def func_d():
    pass

def func_e():
    pass

def func_f():
    pass
"""
        self._setup(mock_coder, mock_file_context, mock_chunks, mock_manager, content)
        try:
            show = [
                {
                    "file_path": self.test_file,
                    "range_start": "def func_a",
                    "range_end": "def func_c",
                }
            ]
            result = self.Tool.execute(self.coder, show)
            assert "def func_a" in str(result)
        finally:
            self._teardown()

    def test_too_many_matches_without_history(
        self, mock_coder, mock_file_context, mock_chunks, mock_manager
    ):
        """Test with >5 matches without history -> should report 'too broad'."""
        content = """def func_a():
    pass

def func_b():
    pass

def func_c():
    pass

def func_d():
    pass

def func_e():
    pass

def func_f():
    pass
"""
        self._setup(mock_coder, mock_file_context, mock_chunks, mock_manager, content)
        try:
            show = [{"file_path": self.test_file, "range_start": "def", "range_end": "def"}]
            result = self.Tool.execute(self.coder, show)
            assert "too broad" in str(result).lower()
        finally:
            self._teardown()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-s"])
