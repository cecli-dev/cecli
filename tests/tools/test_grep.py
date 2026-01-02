import shutil
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cecli.tools import grep


@pytest.mark.skipif(shutil.which("rg") is None, reason="rg is required")
@pytest.mark.parametrize(
    "search_term",
    [
        "--pattern",
        "--pat tern",
        "-pattern",
        "--",
        "-- -test",
    ],
)
def test_dash_prefixed_pattern_is_searched_literally(search_term, tmp_path, monkeypatch):
    sample = tmp_path / "example.txt"
    sample.write_text(f"flag {search_term} should be found\n")

    coder = SimpleNamespace(
        repo=SimpleNamespace(root=str(tmp_path)),
        io=SimpleNamespace(
            tool_error=Mock(),
            tool_output=Mock(),
            tool_warning=Mock(),
        ),
        verbose=False,
        root=str(tmp_path),
        tui=lambda: None,
    )

    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("rg", shutil.which("rg")))

    result = grep.Tool.execute(
        coder,
        pattern=search_term,
        file_pattern="*.txt",
        directory=".",
        use_regex=False,
        case_insensitive=False,
        context_before=0,
        context_after=0,
    )

    assert "Found matches" in result
    assert search_term in result
    coder.io.tool_error.assert_not_called()
