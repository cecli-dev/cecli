from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cecli.tools import insert_block


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

    result = insert_block.Tool.execute(
        coder,
        file_path="example.txt",
        content="inserted line",
        position="top",
    )

    assert result.startswith("Successfully executed InsertBlock.")
    assert file_path.read_text().splitlines()[0] == "inserted line"
    coder.io.tool_error.assert_not_called()


def test_position_top_ignores_blank_patterns(coder_with_file):
    coder, file_path = coder_with_file

    result = insert_block.Tool.execute(
        coder,
        file_path="example.txt",
        content="inserted line",
        position="top",
        after_pattern="",
    )

    assert result.startswith("Successfully executed InsertBlock.")
    assert file_path.read_text().splitlines()[0] == "inserted line"
    coder.io.tool_error.assert_not_called()


def test_mutually_exclusive_parameters_raise(coder_with_file):
    coder, file_path = coder_with_file

    result = insert_block.Tool.execute(
        coder,
        file_path="example.txt",
        content="new line",
        position="top",
        after_pattern="first line",
    )

    assert result.startswith("Error: Must specify exactly one of")
    assert file_path.read_text().startswith("first line")
    coder.io.tool_error.assert_called()


def test_trailing_newline_preservation(coder_with_file):
    coder, file_path = coder_with_file
    insert_block.Tool.execute(
        coder,
        file_path="example.txt",
        content="inserted line",
        position="top",
    )

    content = file_path.read_text()
    assert content.endswith("\n"), "File should preserve trailing newline"
    coder.io.tool_error.assert_not_called()


def test_no_trailing_newline_preservation(coder_with_file):
    coder, file_path = coder_with_file

    content_without_trailing_newline = "first line\nsecond line"
    file_path.write_text(content_without_trailing_newline)

    insert_block.Tool.execute(
        coder,
        file_path="example.txt",
        content="inserted line",
        position="top",
    )

    content = file_path.read_text()
    assert not content.endswith("\n"), "File should preserve lack of trailing newline"
    coder.io.tool_error.assert_not_called()
