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
        searches=[
            {
                "pattern": search_term,
                "file_glob": "*.txt",
                "directory": ".",
                "use_regex": False,
                "case_insensitive": False,
                "context_before": 0,
                "context_after": 0,
            }
        ],
    )

    response_dict = result.to_dict()
    operations = response_dict["result"]
    assert len(operations) == 1
    op = operations[0]
    assert op["_"]["pattern"] == search_term
    assert op["_"]["error"] is None
    assert "total_files" in op["_"]
    assert isinstance(op["_"]["total_files"], int)
    coder.io.tool_error.assert_not_called()


@pytest.mark.skipif(shutil.which("powershell") is None, reason="powershell is required")
@pytest.mark.parametrize(
    "search_term",
    [
        "--pattern",
        "-pattern",
    ],
)
def test_powershell_dash_prefixed_pattern_is_searched_literally(search_term, tmp_path, monkeypatch):
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

    monkeypatch.setattr(
        grep.Tool, "_find_search_tool", lambda: ("powershell", shutil.which("powershell"))
    )

    result = grep.Tool.execute(
        coder,
        searches=[
            {
                "pattern": search_term,
                "file_glob": "*.txt",
                "directory": ".",
                "use_regex": False,
                "case_insensitive": False,
                "context_before": 0,
                "context_after": 0,
            }
        ],
    )

    response_dict = result.to_dict()
    operations = response_dict["result"]
    assert len(operations) == 1
    op = operations[0]
    assert op["_"]["pattern"] == search_term
    assert op["_"]["error"] is None
    assert op["_"]["total_files"] >= 1
    assert op["_"]["total_matches"] >= 1
    assert any("example.txt" in f["file"] for f in op["_"]["files"])
    coder.io.tool_error.assert_not_called()


@pytest.mark.skipif(shutil.which("powershell") is None, reason="powershell is required")
def test_powershell_counts_and_context(tmp_path, monkeypatch):
    sample = tmp_path / "sample.txt"
    sample.write_text("alpha\nbeta\nalpha\ngamma alpha\n")

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

    monkeypatch.setattr(
        grep.Tool, "_find_search_tool", lambda: ("powershell", shutil.which("powershell"))
    )

    result = grep.Tool.execute(
        coder,
        searches=[
            {
                "pattern": "alpha",
                "file_glob": "*.txt",
                "directory": ".",
                "use_regex": False,
                "case_insensitive": True,
                "context_before": 1,
                "context_after": 1,
            }
        ],
    )

    response_dict = result.to_dict()
    op = response_dict["result"][0]
    assert op["_"]["error"] is None
    assert op["_"]["total_matches"] >= 3
    file_entry = next(f for f in op["_"]["files"] if f["file"] == "sample.txt")
    assert file_entry["match_count"] >= 3
    coder.io.tool_error.assert_not_called()


def _grep_coder(root):
    return SimpleNamespace(
        repo=SimpleNamespace(root=str(root)),
        io=SimpleNamespace(tool_error=Mock(), tool_output=Mock(), tool_warning=Mock()),
        verbose=False,
        root=str(root),
        tui=lambda: None,
    )


@pytest.mark.skipif(shutil.which("rg") is None, reason="rg is required")
def test_matches_mode_is_compact_and_relative(tmp_path, monkeypatch):
    sample = tmp_path / "sample.txt"
    sample.write_text("alpha\nbeta\n" + "alpha" + "x" * 500 + "\nalpha\n")
    coder = _grep_coder(tmp_path)
    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("rg", shutil.which("rg")))

    result = grep.Tool.execute(
        coder, searches=[{"pattern": "alpha", "file_glob": "*.txt", "directory": "."}]
    )
    op = result.to_dict()["result"][0]
    content = op["content"]

    assert str(tmp_path) not in content
    assert "sample.txt: 3 match(es)" in content
    assert "1: alpha" in content
    assert "3: alpha" in content
    assert "(+" in content  # the 500-char line is capped
    assert all(len(line) <= grep.MAX_LINE_LENGTH + 40 for line in content.splitlines())

    assert op["_"]["mode"] == "matches"
    assert "file_glob" not in op["_"]  # echoed query params are dropped
    assert all("content" not in entry for entry in op["_"]["files"])
    coder.io.tool_error.assert_not_called()


@pytest.mark.skipif(shutil.which("rg") is None, reason="rg is required")
def test_files_mode_skips_content_pass(tmp_path, monkeypatch):
    sample = tmp_path / "sample.txt"
    sample.write_text("alpha\nbeta\nalpha\ngamma alpha\n")
    coder = _grep_coder(tmp_path)
    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("rg", shutil.which("rg")))

    result = grep.Tool.execute(
        coder,
        searches=[{"pattern": "alpha", "file_glob": "*.txt", "directory": ".", "mode": "files"}],
    )
    op = result.to_dict()["result"][0]
    content = op["content"]

    assert "sample.txt: 3" in content
    assert "1: alpha" not in content
    assert op["_"]["total_matches"] == 3
    coder.io.tool_error.assert_not_called()


@pytest.mark.skipif(shutil.which("rg") is None, reason="rg is required")
def test_invalid_mode_falls_back_to_matches(tmp_path, monkeypatch):
    sample = tmp_path / "sample.txt"
    sample.write_text("alpha\nbeta\n")
    coder = _grep_coder(tmp_path)
    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("rg", shutil.which("rg")))

    result = grep.Tool.execute(
        coder,
        searches=[{"pattern": "alpha", "file_glob": "*.txt", "directory": ".", "mode": "bogus"}],
    )
    op = result.to_dict()["result"][0]
    assert op["_"]["mode"] == "matches"
    assert "1: alpha" in op["content"]
    coder.io.tool_error.assert_not_called()


@pytest.mark.skipif(shutil.which("rg") is None, reason="rg is required")
def test_matches_mode_honors_context(tmp_path, monkeypatch):
    sample = tmp_path / "sample.txt"
    sample.write_text("alpha\nbeta\ngamma\n")
    coder = _grep_coder(tmp_path)
    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("rg", shutil.which("rg")))

    result = grep.Tool.execute(
        coder,
        searches=[
            {
                "pattern": "beta",
                "file_glob": "*.txt",
                "directory": ".",
                "context_before": 1,
                "context_after": 1,
            }
        ],
    )
    op = result.to_dict()["result"][0]
    content = op["content"]
    assert "2: beta" in content
    assert "1- alpha" in content
    assert "3- gamma" in content
    assert op["_"]["mode"] == "matches"
    coder.io.tool_error.assert_not_called()


@pytest.mark.skipif(shutil.which("rg") is None, reason="rg is required")
def test_history_files_are_excluded(tmp_path, monkeypatch):
    (tmp_path / "chat-history.md").write_text("needle\n")
    (tmp_path / "chat-history-search-replace-gold.txt").write_text("needle\n")
    (tmp_path / "notes.dev.history.md").write_text("needle\n")
    (tmp_path / "keep.txt").write_text("needle\n")
    coder = _grep_coder(tmp_path)
    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("rg", shutil.which("rg")))

    result = grep.Tool.execute(
        coder, searches=[{"pattern": "needle", "directory": ".", "mode": "files"}]
    )
    op = result.to_dict()["result"][0]
    files = [entry["file"] for entry in op["_"]["files"]]

    assert "keep.txt" in files
    assert all("chat-history" not in name for name in files)
    assert all("history.md" not in name for name in files)
    coder.io.tool_error.assert_not_called()
