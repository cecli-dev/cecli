from types import SimpleNamespace
from unittest.mock import Mock

from cecli.tools.utils.output import emit_execute_result_to_ui


def test_emit_execute_result_to_ui_skips_tui():
    io = Mock()
    coder = SimpleNamespace(tui=lambda: object(), io=io)
    emit_execute_result_to_ui(coder, "hello")
    io.tool_output.assert_not_called()


def test_emit_execute_result_to_ui_emits_body_for_headless():
    io = Mock()
    coder = SimpleNamespace(tui=lambda: None, io=io)
    emit_execute_result_to_ui(coder, "line one\nline two")
    io.tool_output.assert_called_once_with("line one\nline two")


def test_emit_execute_result_to_ui_truncates_long_output():
    io = Mock()
    coder = SimpleNamespace(tui=lambda: None, io=io)
    long_text = "\n".join(f"line {i}" for i in range(250))
    emit_execute_result_to_ui(coder, long_text, max_lines=200)
    emitted = io.tool_output.call_args[0][0]
    assert emitted.startswith("line 0")
    assert "… (50 more lines)" in emitted


def test_grep_process_response_emits_matches_to_ui(monkeypatch, tmp_path):
    from cecli.tools import grep

    sample = tmp_path / "example.txt"
    sample.write_text("hello ollama world\n")

    io = Mock()
    coder = SimpleNamespace(
        repo=SimpleNamespace(root=str(tmp_path)),
        io=io,
        verbose=False,
        root=str(tmp_path),
        tui=lambda: None,
    )

    monkeypatch.setattr(grep.Tool, "_find_search_tool", lambda: ("grep", "/usr/bin/grep"))

    result = grep.Tool.process_response(
        coder,
        {
            "searches": [
                {
                    "pattern": "ollama",
                    "file_glob": "*.txt",
                    "directory": ".",
                    "use_regex": False,
                    "case_insensitive": False,
                    "context_before": 0,
                    "context_after": 0,
                }
            ]
        },
    )

    assert "Matches for" in result
    emitted = [str(call.args[0]) for call in io.tool_output.call_args_list]
    assert any("ollama" in line for line in emitted)
