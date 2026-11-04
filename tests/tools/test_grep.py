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
    assert "example.txt" in _files_from_content(op)
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
    assert "sample.txt" in _files_from_content(op)
    coder.io.tool_error.assert_not_called()


def _grep_coder(root):
    return SimpleNamespace(
        repo=SimpleNamespace(root=str(root)),
        io=SimpleNamespace(tool_error=Mock(), tool_output=Mock(), tool_warning=Mock()),
        verbose=False,
        root=str(root),
        tui=lambda: None,
    )


def _files_from_content(op):
    """Return the file paths listed in a rendered grep response."""
    files = set()
    for line in op["content"].splitlines():
        path, sep, rest = line.rpartition(": ")
        if sep and rest.split(" ", 1)[0].isdigit():
            files.add(path)
    return files


@pytest.mark.skipif(shutil.which("rg") is None, reason="rg is required")
@pytest.mark.parametrize(
    ("options", "expected_matches"),
    [({}, 3), ({"use_regex": True}, 3), ({"use_regex": False}, 1)],
)
def test_pipe_pattern_uses_regex_unless_explicitly_disabled(
    options, expected_matches, tmp_path, monkeypatch
):
    sample = tmp_path / "sample.txt"
    sample.write_text("alpha\nbeta\nalpha|beta\n")
    coder = _grep_coder(tmp_path)
    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("rg", shutil.which("rg")))

    search = {"pattern": "alpha|beta", "file_glob": "*.txt", "directory": "."}
    search.update(options)
    result = grep.Tool.execute(coder, searches=[search])
    op = result.to_dict()["result"][0]

    assert op["_"]["error"] is None
    assert op["_"]["total_matches"] == expected_matches
    coder.io.tool_error.assert_not_called()


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
    assert "files" not in op["_"]
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
def test_invalid_mode_is_rejected(tmp_path, monkeypatch):
    sample = tmp_path / "sample.txt"
    sample.write_text("alpha\nbeta\n")
    coder = _grep_coder(tmp_path)
    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("rg", shutil.which("rg")))

    result = grep.Tool.execute(
        coder,
        searches=[{"pattern": "alpha", "file_glob": "*.txt", "directory": ".", "mode": "bogus"}],
    )
    op = result.to_dict()["result"][0]
    assert op["_"]["mode"] == "bogus"
    assert "Invalid mode 'bogus'" in op["_"]["error"]
    assert "No matches found" not in op["content"]
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
    files = _files_from_content(op)

    assert "keep.txt" in files
    assert all("chat-history" not in name for name in files)
    assert all("history.md" not in name for name in files)
    coder.io.tool_error.assert_not_called()


@pytest.mark.skipif(shutil.which("rg") is None, reason="rg is required")
def test_regex_syntax_is_auto_detected(tmp_path, monkeypatch):
    sample = tmp_path / "sample.py"
    sample.write_text("def foo(x):\n    return x\n")
    coder = _grep_coder(tmp_path)
    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("rg", shutil.which("rg")))

    result = grep.Tool.execute(coder, searches=[{"pattern": "^def ", "directory": "."}])
    op = result.to_dict()["result"][0]

    assert op["_"]["regex"] is True
    assert op["_"]["total_matches"] == 1
    assert "def foo(x)" in op["content"]


@pytest.mark.skipif(shutil.which("rg") is None, reason="rg is required")
def test_literal_miss_retries_as_regex(tmp_path, monkeypatch):
    sample = tmp_path / "sample.txt"
    sample.write_text("alpha\nbeta\n")
    coder = _grep_coder(tmp_path)
    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("rg", shutil.which("rg")))

    result = grep.Tool.execute(coder, searches=[{"pattern": "(alpha)", "directory": "."}])
    op = result.to_dict()["result"][0]

    assert op["_"]["regex"] is True
    assert op["_"]["total_matches"] == 1
    assert "1: alpha" in op["content"]


@pytest.mark.skipif(shutil.which("rg") is None, reason="rg is required")
def test_empty_alternation_stays_literal(tmp_path, monkeypatch):
    sample = tmp_path / "sample.txt"
    sample.write_text("alpha\nbeta\nfoo||bar\n")
    coder = _grep_coder(tmp_path)
    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("rg", shutil.which("rg")))

    result = grep.Tool.execute(coder, searches=[{"pattern": "foo||bar", "directory": "."}])
    op = result.to_dict()["result"][0]

    assert op["_"]["regex"] is False
    assert op["_"]["total_matches"] == 1
    assert "3: foo||bar" in op["content"]


@pytest.mark.skipif(shutil.which("rg") is None, reason="rg is required")
def test_invalid_regex_retries_literal(tmp_path, monkeypatch):
    sample = tmp_path / "sample.txt"
    sample.write_text("foo(\nbar\n")
    coder = _grep_coder(tmp_path)
    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("rg", shutil.which("rg")))

    result = grep.Tool.execute(
        coder, searches=[{"pattern": "foo(", "directory": ".", "use_regex": True}]
    )
    op = result.to_dict()["result"][0]

    assert op["_"]["error"] is None
    assert op["_"]["regex"] is False
    assert op["_"]["total_matches"] == 1
    assert op["_"]["warnings"]


@pytest.mark.skipif(shutil.which("rg") is None, reason="rg is required")
def test_lookahead_retries_with_pcre2(tmp_path, monkeypatch):
    sample = tmp_path / "sample.txt"
    sample.write_text("foo123\nfoo\n")
    coder = _grep_coder(tmp_path)
    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("rg", shutil.which("rg")))

    result = grep.Tool.execute(
        coder,
        searches=[{"pattern": "foo(?=123)", "directory": ".", "use_regex": True}],
    )
    op = result.to_dict()["result"][0]

    assert op["_"]["error"] is None
    assert op["_"]["total_matches"] == 1
    assert "1: foo123" in op["content"]


@pytest.mark.skipif(shutil.which("rg") is None, reason="rg is required")
def test_backreference_retries_with_pcre2(tmp_path, monkeypatch):
    sample = tmp_path / "sample.txt"
    sample.write_text("aa\nab\n")
    coder = _grep_coder(tmp_path)
    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("rg", shutil.which("rg")))

    result = grep.Tool.execute(
        coder,
        searches=[{"pattern": r"(a)\1", "directory": ".", "use_regex": True}],
    )
    op = result.to_dict()["result"][0]

    assert op["_"]["error"] is None
    assert op["_"]["total_matches"] == 1
    assert "1: aa" in op["content"]


@pytest.mark.skipif(shutil.which("rg") is None, reason="rg is required")
def test_paths_with_digit_dash_segments_are_parsed(tmp_path, monkeypatch):
    (tmp_path / "proj-1-x" / "src").mkdir(parents=True)
    sample = tmp_path / "proj-1-x" / "src" / "main.py"
    sample.write_text("alpha\nalpha\n")
    root = tmp_path / "proj-1-x"
    coder = _grep_coder(root)
    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("rg", shutil.which("rg")))

    result = grep.Tool.execute(coder, searches=[{"pattern": "alpha", "directory": "."}])
    op = result.to_dict()["result"][0]

    assert op["_"]["total_matches"] == 2
    assert "src/main.py: 2 match(es)" in op["content"]


@pytest.mark.skipif(shutil.which("rg") is None, reason="rg is required")
def test_colon_in_path_is_parsed(tmp_path, monkeypatch):
    sample = tmp_path / "a:1:b.txt"
    sample.write_text("needle\n")
    coder = _grep_coder(tmp_path)
    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("rg", shutil.which("rg")))

    result = grep.Tool.execute(coder, searches=[{"pattern": "needle", "directory": "."}])
    op = result.to_dict()["result"][0]

    assert op["_"]["total_matches"] == 1
    assert "a:1:b.txt: 1 match(es)" in op["content"]


@pytest.mark.skipif(shutil.which("rg") is None, reason="rg is required")
def test_ripgrep_config_does_not_change_output_shape(tmp_path, monkeypatch):
    sample = tmp_path / "sample.txt"
    sample.write_text("alpha\n")
    config = tmp_path / "ripgreprc"
    config.write_text("--heading\n--color=always\n")
    monkeypatch.setenv("RIPGREP_CONFIG_PATH", str(config))
    coder = _grep_coder(tmp_path)
    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("rg", shutil.which("rg")))

    result = grep.Tool.execute(coder, searches=[{"pattern": "alpha", "directory": "."}])
    op = result.to_dict()["result"][0]

    assert op["_"]["total_matches"] == 1
    assert "sample.txt: 1 match(es)" in op["content"]


@pytest.mark.skipif(
    shutil.which("grep") is None or not grep._grep_supports_pcre(shutil.which("grep")),
    reason="grep with PCRE support is required",
)
def test_grep_regex_uses_pcre_when_available(tmp_path, monkeypatch):
    sample = tmp_path / "sample.txt"
    sample.write_text("foo123\nfoo\n")
    coder = _grep_coder(tmp_path)
    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("grep", shutil.which("grep")))

    result = grep.Tool.execute(
        coder,
        searches=[{"pattern": r"foo\d+", "directory": ".", "use_regex": True}],
    )
    op = result.to_dict()["result"][0]

    assert op["_"]["error"] is None
    assert op["_"]["total_matches"] == 1
    assert "1: foo123" in op["content"]


@pytest.mark.skipif(shutil.which("rg") is None, reason="rg is required")
def test_matches_mode_shows_truncation_marker(tmp_path, monkeypatch):
    sample = tmp_path / "sample.txt"
    sample.write_text("".join(f"alpha{i}\n" for i in range(15)))
    coder = _grep_coder(tmp_path)
    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("rg", shutil.which("rg")))

    result = grep.Tool.execute(coder, searches=[{"pattern": "alpha", "directory": "."}])
    op = result.to_dict()["result"][0]

    assert "showing 10 of 15 matches" in op["content"]
    assert "+5 more locations" in op["content"]
    assert "more locations: 11, 12, 13, 14, 15" in op["content"]


@pytest.mark.skipif(shutil.which("rg") is None, reason="rg is required")
def test_count_false_warns_about_capped_totals(tmp_path, monkeypatch):
    sample = tmp_path / "sample.txt"
    sample.write_text("".join("alpha\n" for _ in range(55)))
    coder = _grep_coder(tmp_path)
    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("rg", shutil.which("rg")))

    result = grep.Tool.execute(
        coder, searches=[{"pattern": "alpha", "directory": ".", "count": False}]
    )
    op = result.to_dict()["result"][0]

    assert op["_"]["total_matches"] == grep.MAX_LINE_NUMBERS
    assert "count capped at 50" in op["content"]
    assert any("count=false" in warning for warning in op["_"]["warnings"])


@pytest.mark.skipif(shutil.which("rg") is None, reason="rg is required")
def test_context_is_clamped_with_warning(tmp_path, monkeypatch):
    sample = tmp_path / "sample.txt"
    sample.write_text("alpha\nbeta\ngamma\n")
    coder = _grep_coder(tmp_path)
    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("rg", shutil.which("rg")))

    result = grep.Tool.execute(
        coder, searches=[{"pattern": "beta", "directory": ".", "context_before": 9}]
    )
    op = result.to_dict()["result"][0]

    assert any("clamped from 9 to 5" in warning for warning in op["_"]["warnings"])
    assert "clamped from 9 to 5" in op["content"]


@pytest.mark.skipif(shutil.which("rg") is None, reason="rg is required")
def test_comma_separated_globs_are_supported(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("needle\n")
    (tmp_path / "b.md").write_text("needle\n")
    (tmp_path / "c.txt").write_text("needle\n")
    coder = _grep_coder(tmp_path)
    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("rg", shutil.which("rg")))

    result = grep.Tool.execute(
        coder,
        searches=[{"pattern": "needle", "directory": ".", "file_glob": "*.py,*.md"}],
    )
    op = result.to_dict()["result"][0]

    assert op["_"]["total_matches"] == 2
    assert _files_from_content(op) == {"a.py", "b.md"}


@pytest.mark.skipif(shutil.which("rg") is None, reason="rg is required")
def test_zero_match_glob_gets_warning(tmp_path, monkeypatch):
    (tmp_path / "sample.py").write_text("needle\n")
    coder = _grep_coder(tmp_path)
    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("rg", shutil.which("rg")))

    result = grep.Tool.execute(
        coder,
        searches=[{"pattern": "needle", "directory": ".", "file_glob": "*.nope"}],
    )
    op = result.to_dict()["result"][0]

    assert op["_"]["total_matches"] == 0
    assert any("file_glob='*.nope'" in warning for warning in op["_"]["warnings"])


def test_empty_pattern_body_uses_label(tmp_path):
    coder = _grep_coder(tmp_path)
    result = grep.Tool.execute(coder, searches=[{"pattern": "", "directory": "."}])
    op = result.to_dict()["result"][0]

    assert op["content"].startswith("[<empty>]")
    assert op["_"]["error"]


@pytest.mark.skipif(shutil.which("grep") is None, reason="grep is required")
def test_grep_comma_separated_globs_are_supported(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("needle\n")
    (tmp_path / "b.md").write_text("needle\n")
    (tmp_path / "c.txt").write_text("needle\n")
    coder = _grep_coder(tmp_path)
    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("grep", shutil.which("grep")))

    result = grep.Tool.execute(
        coder,
        searches=[{"pattern": "needle", "directory": ".", "file_glob": "*.py,*.md"}],
    )
    op = result.to_dict()["result"][0]

    assert op["_"]["total_matches"] == 2
    assert _files_from_content(op) == {"a.py", "b.md"}
