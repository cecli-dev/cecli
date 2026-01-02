from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cecli.tools import show_numbered_context


class DummyIO:
    def __init__(self):
        self.tool_error = Mock()
        self.tool_warning = Mock()
        self.tool_output = Mock()

    def read_text(self, path):
        return Path(path).read_text()

    def write_text(self, path, content):
        Path(path).write_text(content)


class DummyCoder:
    def __init__(self, root):
        self.root = str(root)
        self.repo = SimpleNamespace(root=str(root))
        self.io = DummyIO()

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
    file_path.write_text("alpha\nbeta\ngamma\n")
    coder = DummyCoder(tmp_path)
    return coder, file_path


def test_pattern_with_zero_line_number_is_allowed(coder_with_file):
    coder, file_path = coder_with_file

    result = show_numbered_context.Tool.execute(
        coder,
        file_path="example.txt",
        pattern="beta",
        line_number=0,
        context_lines=0,
    )

    assert "beta" in result
    assert "line 2" in result or "2 | beta" in result
    coder.io.tool_error.assert_not_called()


def test_empty_pattern_uses_line_number(coder_with_file):
    coder, file_path = coder_with_file

    result = show_numbered_context.Tool.execute(
        coder,
        file_path="example.txt",
        pattern="",
        line_number=2,
        context_lines=0,
    )

    assert "2 | beta" in result
    coder.io.tool_error.assert_not_called()


def test_conflicting_pattern_and_line_number_raise(coder_with_file):
    coder, file_path = coder_with_file

    result = show_numbered_context.Tool.execute(
        coder,
        file_path="example.txt",
        pattern="beta",
        line_number=2,
        context_lines=0,
    )

    assert result.startswith("Error: Provide exactly one of")
    coder.io.tool_error.assert_called()


def test_target_symbol_empty_string_treated_as_missing():
    from cecli.tools.utils import helpers
    from cecli.tools.utils.helpers import ToolError

    with pytest.raises(ToolError, match="Must specify either target_symbol or start_pattern"):
        helpers.determine_line_range(
            coder=SimpleNamespace(repo_map=None),  # repo_map not used in this path
            file_path="dummy",
            lines=["a", "b"],
            target_symbol="",
            start_pattern_line_index=None,
            end_pattern=None,
            line_count=1,
        )
