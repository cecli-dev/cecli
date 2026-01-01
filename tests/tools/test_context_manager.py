"""Tests for the ContextManager tool."""

from unittest.mock import Mock

import pytest

from aider.tools.context_manager import Tool as ContextManagerTool
from aider.tools.utils.helpers import ToolError


class TestContextManagerTool:
    """Test suite for ContextManager tool."""

    def setup_method(self):
        """Set up a mock coder for each test."""
        self.coder = Mock()
        self.coder.abs_root_path = Mock(side_effect=lambda x: x)
        self.coder.get_rel_fname = Mock(side_effect=lambda x: x)
        self.coder.abs_fnames = set()
        self.coder.abs_read_only_fnames = set()
        self.coder.recently_removed = {}
        self.coder.io = Mock()
        self.coder.io.tool_output = Mock()
        self.coder.io.tool_error = Mock()
        self.coder._add_file_to_context = Mock(return_value="Viewed: test.py")

    def test_execute_with_valid_lists(self):
        """Test execute with proper list arguments."""
        result = ContextManagerTool.execute(
            self.coder,
            remove=["file1.py"],
            editable=["file2.py"],
            view=["file3.py"],
            create=["file4.py"],
        )
        assert "Removed: file1.py" in result
        assert "Made editable" in result
        assert "Viewed: test.py" in result
        assert "Created and made editable: file4.py" in result

    def test_execute_with_json_string_arrays(self):
        """Test execute with JSON string arrays that should be parsed."""
        # Simulate the LLM generating a JSON string for the view argument
        view_json = '["file1.py", "file2.py"]'
        ContextManagerTool.execute(self.coder, view=view_json)
        # The tool should parse the JSON string and treat it as a list
        # Since we mock _add_file_to_context to return "Viewed: test.py",
        # we need to check it was called twice
        assert self.coder._add_file_to_context.call_count == 2
        calls = self.coder._add_file_to_context.call_args_list
        assert calls[0][0][0] == "file1.py"
        assert calls[1][0][0] == "file2.py"

    def test_execute_with_empty_string(self):
        """Test execute with empty string argument."""
        # Empty string should be treated as empty list
        with pytest.raises(ToolError):
            ContextManagerTool.execute(self.coder, view="")

    def test_execute_with_malformed_json_string(self):
        """Test execute with a malformed JSON string that should be treated as a single file."""
        # A string that is not valid JSON should be treated as a single file path
        view_string = "file1.py"
        ContextManagerTool.execute(self.coder, view=view_string)
        self.coder._add_file_to_context.assert_called_once_with("file1.py", explicit=True)

    def test_execute_with_whitespace_string(self):
        """Test execute with whitespace-only string argument."""
        # Whitespace-only string should be treated as empty list
        with pytest.raises(ToolError):
            ContextManagerTool.execute(self.coder, view="   ")
        with pytest.raises(ToolError):
            ContextManagerTool.execute(self.coder, view="\t\n")

    def test_execute_with_single_json_string_element(self):
        """Test execute with a JSON string representing a single element (not array)."""
        # JSON string that is a single string (not array) should be wrapped in a list
        view_json = '"file1.py"'
        ContextManagerTool.execute(self.coder, view=view_json)
        self.coder._add_file_to_context.assert_called_once_with("file1.py", explicit=True)

    def test_execute_with_none_arguments(self):
        """Test execute with None arguments."""
        # Should raise ToolError because no operations specified
        with pytest.raises(ToolError):
            ContextManagerTool.execute(self.coder)

    def test_execute_with_empty_lists(self):
        """Test execute with empty lists."""
        with pytest.raises(ToolError):
            ContextManagerTool.execute(self.coder, remove=[], view=[])

    def test_parse_arg_helper(self):
        """Test the parse_arg behavior through execute method."""
        # Test with None
        with pytest.raises(ToolError):
            ContextManagerTool.execute(self.coder, view=None)

        # Test with list
        self.coder._add_file_to_context.reset_mock()
        ContextManagerTool.execute(self.coder, view=["test1.py", "test2.py"])
        assert self.coder._add_file_to_context.call_count == 2

        # Test with JSON string array
        self.coder._add_file_to_context.reset_mock()
        ContextManagerTool.execute(self.coder, view='["test1.py", "test2.py"]')
        assert self.coder._add_file_to_context.call_count == 2

        # Test with non-JSON string
        self.coder._add_file_to_context.reset_mock()
        ContextManagerTool.execute(self.coder, view="test1.py")
        self.coder._add_file_to_context.assert_called_once_with("test1.py", explicit=True)

        # Test with JSON string that's not an array
        self.coder._add_file_to_context.reset_mock()
        ContextManagerTool.execute(self.coder, view='"test1.py"')
        self.coder._add_file_to_context.assert_called_once_with("test1.py", explicit=True)

    def test_error_handling(self):
        """Test that errors are properly propagated."""
        self.coder._add_file_to_context.side_effect = Exception("Test error")
        result = ContextManagerTool.execute(self.coder, view=["test.py"])
        assert "Error viewing" in result
        self.coder.io.tool_error.assert_called()

    def test_json_string_with_escaped_quotes(self):
        """Test the specific case from the bug report: JSON string with escaped quotes."""
        # This simulates the exact tool call that caused the error:
        # {"view": "[\"aider/coders/base_coder.py\"]"}
        view_json = '["aider/coders/base_coder.py"]'
        ContextManagerTool.execute(self.coder, view=view_json)
        # Should parse as a single file, not as individual characters
        self.coder._add_file_to_context.assert_called_once_with(
            "aider/coders/base_coder.py", explicit=True
        )

        # Also test with multiple files
        self.coder._add_file_to_context.reset_mock()
        view_json = '["file1.py", "file2.py"]'
        ContextManagerTool.execute(self.coder, view=view_json)
        assert self.coder._add_file_to_context.call_count == 2
        calls = self.coder._add_file_to_context.call_args_list
        assert calls[0][0][0] == "file1.py"
        assert calls[1][0][0] == "file2.py"
