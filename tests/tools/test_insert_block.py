from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cecli.helpers.hashline import hashline
from cecli.tools import edit_file


class DummyIO:
    def __init__(self):
        self.tool_error = Mock()
        self.tool_warning = Mock()
        self.tool_output = Mock()

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
    file_path.write_text("first line\nsecond line\n")
    coder = DummyCoder(tmp_path)
    coder.abs_fnames.add(str(file_path.resolve()))
    return coder, file_path


def test_position_top_succeeds_with_no_patterns(coder_with_file):
    coder, file_path = coder_with_file

    # Calculate hashline for line 1
    content = file_path.read_text()
    hashed_content = hashline(content)
    lines = hashed_content.splitlines()
    line1_hashline = lines[0]  # Index 0 is line 1
    # HashPos format: {4-char-hash}::content
    # Extract hash fragment from {hash}::content format
    hash_fragment = line1_hashline.split("::", 1)[0]  # Everything before "::"
    start_line = hash_fragment  # Just the hash fragment, no brackets

    result = edit_file.Tool.execute(
        coder,
        edits=[
            {
                "file_path": "example.txt",
                "operation": "insert",
                "text": "inserted line",
                "start_line": start_line,
            },
        ],
    )

    assert "Applied" in result.to_dict()["result"][0]["content"]
    lines = file_path.read_text().splitlines()
    # Insert places the new line after the anchor line
    assert lines[0] == "first line"
    assert lines[1] == "inserted line"
    assert lines[2] == "second line"
    coder.io.tool_error.assert_not_called()


def test_mutually_exclusive_parameters_raise(coder_with_file):
    coder, file_path = coder_with_file

    # Test with invalid hashline format (missing pipe)
    result = edit_file.Tool.execute(
        coder,
        edits=[
            {
                "file_path": "example.txt",
                "operation": "insert",
                "text": "new line",
                "start_line": "invalid_hashline",
            },
        ],
    )

    assert any("Invalid Edit" in e for e in result.to_dict()["errors"])
    assert "Invalid Edit - Review content ID bounds" in str(result)
    assert file_path.read_text().startswith("first line")
    coder.io.tool_error.assert_not_called()


def test_trailing_newline_preservation(coder_with_file):
    coder, file_path = coder_with_file
    # Calculate hashline for line 1
    content = file_path.read_text()
    hashed_content = hashline(content)
    lines = hashed_content.splitlines()
    line1_hashline = lines[0]  # Index 0 is line 1
    # HashPos format: {4-char-hash}::content
    # Extract hash fragment from {hash}::content format
    hash_fragment = line1_hashline.split("::", 1)[0]  # Everything before "::"
    start_line = hash_fragment  # Just the hash fragment, no brackets

    edit_file.Tool.execute(
        coder,
        edits=[
            {
                "file_path": "example.txt",
                "operation": "insert",
                "text": "inserted line",
                "start_line": start_line,
            },
        ],
    )

    content = file_path.read_text()
    # When inserting in middle of file with HashPos system,
    # trailing newlines should be preserved for insert operations
    # just like they are for other operations
    assert content.endswith(
        "\n"
    ), "HashPos insert operation should preserve trailing newlines when inserting in middle"
    coder.io.tool_error.assert_not_called()


def test_no_trailing_newline_preservation(coder_with_file):
    coder, file_path = coder_with_file

    content_without_trailing_newline = "first line\nsecond line"
    file_path.write_text(content_without_trailing_newline)

    # Calculate hashline for line 1
    content = file_path.read_text()
    hashed_content = hashline(content)
    lines = hashed_content.splitlines()
    line1_hashline = lines[0]  # Index 0 is line 1
    # HashPos format: {4-char-hash}::content
    # Extract hash fragment from {hash}::content format
    hash_fragment = line1_hashline.split("::", 1)[0]  # Everything before "::"
    start_line = hash_fragment  # Just the hash fragment, no brackets
    edit_file.Tool.execute(
        coder,
        edits=[
            {
                "file_path": "example.txt",
                "operation": "insert",
                "text": "inserted line",
                "start_line": start_line,
            },
        ],
    )

    content = file_path.read_text()
    # Note: hashline implementation respects original trailing newline
    # If original doesn't have trailing newline, result won't have one either
    assert not content.endswith("\n"), "Hashline implementation respects original trailing newline"
    coder.io.tool_error.assert_not_called()


def test_line_number_beyond_file_length_appends(coder_with_file):
    coder, file_path = coder_with_file
    # file_path has "first line\nsecond line\n" (2 lines)

    # Calculate hashline for line 2
    content = file_path.read_text()
    hashed_content = hashline(content)
    # Extract hash fragment for line 2
    # HashPos format: {4-char-hash}::content
    lines = hashed_content.splitlines()
    line2_hashline = lines[1]  # Index 1 is line 2 (0-indexed)
    # Extract hash fragment from {hash}::content format
    hash_fragment = line2_hashline.split("::", 1)[0]  # Everything before "::"
    start_line = hash_fragment  # Just the hash fragment, no brackets
    result = edit_file.Tool.execute(
        coder,
        edits=[
            {
                "file_path": "example.txt",
                "operation": "insert",
                "text": "appended line",
                "start_line": start_line,
            },
        ],
    )

    assert "Applied" in result.to_dict()["result"][0]["content"]
    content = file_path.read_text()
    assert content == "first line\nsecond line\nappended line\n"
    coder.io.tool_error.assert_not_called()


def test_line_number_beyond_file_length_appends_no_trailing_newline(coder_with_file):
    coder, file_path = coder_with_file
    file_path.write_text("first line\nsecond line")  # No trailing newline

    # Calculate hashline for line 2 (without trailing newline)
    content = file_path.read_text()
    hashed_content = hashline(content)
    # Extract hash fragment for line 2
    lines = hashed_content.splitlines()
    line2_hashline = lines[1]  # Index 1 is line 2 (0-indexed)
    # HashPos format: {4-char-hash}::content
    # Extract hash fragment from {hash}::content format
    hash_fragment = line2_hashline.split("::", 1)[0]  # Everything before "::"
    start_line = hash_fragment  # Just the hash fragment, no brackets

    edit_file.Tool.execute(
        coder,
        edits=[
            {
                "file_path": "example.txt",
                "operation": "insert",
                "text": "appended line",
                "start_line": start_line,
            },
        ],
    )
    content = file_path.read_text()
    # Insert respects the original trailing newline: no trailing newline in the result
    assert content == "first line\nsecond line\nappended line"
    coder.io.tool_error.assert_not_called()
