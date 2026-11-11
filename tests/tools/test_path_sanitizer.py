"""Tests for sanitize_file_path and resolve_paths."""

from unittest.mock import MagicMock
from cecli.tools.utils.helpers import sanitize_file_path, resolve_paths


def test_sanitize_file_path_plain():
    assert sanitize_file_path("foo/bar.txt") == "foo/bar.txt"
    assert sanitize_file_path("  foo/bar.txt  ") == "foo/bar.txt"
    assert sanitize_file_path('"foo/bar.txt"') == "foo/bar.txt"
    assert sanitize_file_path("'foo/bar.txt'") == "foo/bar.txt"
    assert sanitize_file_path("`foo/bar.txt`") == "foo/bar.txt"


def test_sanitize_file_path_tool_call_leaks():
    leaked = "doc/indicator/PBK_ADX_v1.0.pine_manual.md}<tool_call|><|channel>thought\\n<channel|><|tool_call>call:local--Yield{summary:'"
    assert sanitize_file_path(leaked) == "doc/indicator/PBK_ADX_v1.0.pine_manual.md"

    leaked_bracket = "doc/test.md<tool_call|>"
    assert sanitize_file_path(leaked_bracket) == "doc/test.md"

    leaked_pipe = "doc/test.md<|tool_call|>"
    assert sanitize_file_path(leaked_pipe) == "doc/test.md"

    leaked_channel = "doc/test.md<|channel>thought"
    assert sanitize_file_path(leaked_channel) == "doc/test.md"

    leaked_close = "doc/test.md</tool_call>"
    assert sanitize_file_path(leaked_close) == "doc/test.md"


def test_resolve_paths_uses_sanitized_path(tmp_path):
    coder = MagicMock()
    coder.root = str(tmp_path)
    coder.abs_root_path.side_effect = lambda p: str(tmp_path / p)
    coder.get_rel_fname.side_effect = lambda p: str(p).replace(str(tmp_path) + "\\", "").replace(str(tmp_path) + "/", "")

    leaked = "doc/test.md}<tool_call|>"
    abs_path, rel_path = resolve_paths(coder, leaked)

    assert "<tool_call" not in abs_path
    assert "test.md" in abs_path
    assert "}" not in abs_path
