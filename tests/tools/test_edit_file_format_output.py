"""Regression tests for EditFile.format_output preview parity with execute.

format_output renders a live diff preview of an edit BEFORE execute applies
it. It must resolve the same start_line/end_line inputs that execute accepts;
otherwise a successful edit shows the user
"Preview Unavailable: Content ID Verification Failed" instead of a diff.

Regression cases: @L{num} line references, ``——<content>`` unique-prefix
references, delete operations, and ``@000`` empty-file markers.
"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cecli.tools import edit_file


class DummyIO:
    def __init__(self):
        self.tool_error = Mock()
        self.tool_warning = Mock()
        self.outputs = []
        self._last_type = False

    def tool_output(self, msg, type=None):
        self.outputs.append(str(msg))
        self._last_type = type

    def read_text(self, path):
        return Path(path).read_text()

    def write_text(self, path, content):
        Path(path).write_text(content)


class DummyChangeTracker:
    def __init__(self):
        self.calls = []

    def track_change(
        self, file_path, change_type, original_content, new_content, metadata, change_id=None
    ):
        self.calls.append(
            {
                "file_path": file_path,
                "change_type": change_type,
                "original_content": original_content,
                "new_content": new_content,
                "metadata": metadata,
                "change_id": change_id,
            }
        )

        return f"change-{len(self.calls)}"


class DummyCoder:
    def __init__(self, root):
        self.root = str(root)
        self.repo = SimpleNamespace(root=str(root))
        self.io = DummyIO()
        self.change_tracker = DummyChangeTracker()
        self.coder_edited_files = set()
        self.files_edited_by_tools = set()
        self.abs_read_only_fnames = set()
        self.abs_fnames = set()
        self.edit_allowed = True
        self.file_read_cache = set()
        self.verbose = False
        self.pretty = False
        self.agent_config = {"diff_colors": False}

    def abs_root_path(self, file_path):
        path = Path(file_path)
        if path.is_absolute():
            return str(path)
        return str((Path(self.root) / path).resolve())

    def get_rel_fname(self, abs_path):
        return str(Path(abs_path).resolve().relative_to(self.root))


@pytest.fixture
def coder_with_file(tmp_path):
    file_path = tmp_path / "example.txt"
    file_path.write_text(
        "def foo():\n"
        "    print('hello')\n"
        "    return 42\n"
        "\n"
        "\n"
        "def bar():\n"
        "    return foo()\n"
    )
    coder = DummyCoder(tmp_path)
    coder.abs_fnames.add(str(file_path.resolve()))
    return coder, file_path


def make_tool_response(edits, wrap_arguments=False):
    arguments = {"edits": edits}
    if wrap_arguments:
        # Some models mirror the OpenAI wire format and double-wrap the real
        # params under a single top-level "arguments" key.
        arguments = {"arguments": json.dumps(arguments)}
    return SimpleNamespace(
        id="test-id",
        type="function",
        function=SimpleNamespace(
            name="EditFile",
            arguments=json.dumps(arguments),
        ),
    )


def preview_output(coder, edits, wrap_arguments=False):
    """Run format_output (as base_coder does before execute) and capture output."""
    edit_file.Tool.format_output(
        coder,
        mcp_server=SimpleNamespace(name="Local"),
        tool_response=make_tool_response(edits, wrap_arguments=wrap_arguments),
    )
    return "\n".join(coder.io.outputs)


def assert_preview_shows_diff(coder, edits):
    output = preview_output(coder, edits)
    assert "Preview Unavailable" not in output
    assert "Cannot verify" not in output
    assert "@@" in output, f"expected a unified diff in preview output:\n{output}"


def test_format_output_resolves_at_l_references(coder_with_file):
    """@L{num} refs: execute succeeds and format_output previews a real diff."""
    coder, _ = coder_with_file
    edits = [
        {
            "file_path": "example.txt",
            "operation": "replace",
            "start_line": "@L2",
            "end_line": "@L3",
            "text": '    print("hello")  # edited',
        }
    ]

    assert_preview_shows_diff(coder, edits)

    result = edit_file.Tool.execute(coder, edits=edits)
    assert result.to_dict()["errors"] == []
    assert "Applied 1 edits" in result.to_dict()["result"][0]["content"]


def test_format_output_resolves_unique_prefix_references(coder_with_file):
    """``——<content>`` ReadFile-style refs preview correctly."""
    coder, _ = coder_with_file
    edits = [
        {
            "file_path": "example.txt",
            "operation": "replace",
            "start_line": "——    print('hello')",
            "end_line": "——    return 42",
            "text": '    print("hello")  # edited',
        }
    ]

    assert_preview_shows_diff(coder, edits)

    result = edit_file.Tool.execute(coder, edits=edits)
    assert result.to_dict()["errors"] == []


def test_format_output_resolves_at_l_delete(coder_with_file):
    """Delete operation with @L{num} refs previews correctly."""
    coder, file_path = coder_with_file
    edits = [
        {
            "file_path": "example.txt",
            "operation": "delete",
            "start_line": "@L2",
            "end_line": "@L2",
            "text": "",
        }
    ]

    assert_preview_shows_diff(coder, edits)

    result = edit_file.Tool.execute(coder, edits=edits)
    assert result.to_dict()["errors"] == []
    assert "print('hello')" not in file_path.read_text()


def test_format_output_resolves_at_000_for_empty_file(coder_with_file):
    """@000 markers on an empty file preview and apply cleanly."""
    coder, file_path = coder_with_file
    file_path.write_text("")
    edits = [
        {
            "file_path": "example.txt",
            "operation": "replace",
            "start_line": "@000",
            "end_line": "@000",
            "text": "hello\nworld",
        }
    ]

    output = preview_output(coder, edits)
    assert "Preview Unavailable" not in output

    result = edit_file.Tool.execute(coder, edits=edits)
    assert result.to_dict()["errors"] == []
    assert file_path.read_text() == "hello\nworld"


def test_format_output_mixed_selectors_in_batch(coder_with_file):
    """A batch mixing @L{num} and bare-content selectors previews each edit."""
    coder, _ = coder_with_file
    edits = [
        {
            "file_path": "example.txt",
            "operation": "replace",
            "start_line": "@L1",
            "end_line": "@L1",
            "text": "def foo():  # v2",
        },
        {
            "file_path": "example.txt",
            "operation": "replace",
            "start_line": "    return 42",
            "end_line": "    return 42",
            "text": "    return 7",
        },
    ]

    output = preview_output(coder, edits)
    assert "Preview Unavailable" not in output
    assert output.count("@@") >= 2

    result = edit_file.Tool.execute(coder, edits=edits)
    assert result.to_dict()["errors"] == []


def test_format_output_unwraps_double_wrapped_arguments(coder_with_file):
    """Double-wrapped {"arguments": "{\"edits\": [...]}"} previews a real diff.

    The execution path unwraps this via responses.parse_tool_arguments, so the
    preview (format_output) must resolve the same edits instead of rendering
    nothing.
    """
    coder, _ = coder_with_file
    edits = [
        {
            "file_path": "example.txt",
            "operation": "replace",
            "start_line": "@L2",
            "end_line": "@L3",
            "text": '    print("hello")  # edited',
        }
    ]

    output = preview_output(coder, edits, wrap_arguments=True)
    assert "Preview Unavailable" not in output
    assert "@@" in output, f"expected a unified diff in preview output:\n{output}"

    result = edit_file.Tool.execute(coder, edits=edits)
    assert result.to_dict()["errors"] == []
