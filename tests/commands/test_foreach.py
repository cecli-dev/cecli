"""Tests for the /foreach command."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cecli.commands.foreach import ForeachCommand, safe_substitute


def test_safe_substitute():
    template = 'Delegate to worker: {"read_only": ["{file}"], "target": "doc/{filename}_manual.md"}'
    values = {
        "file": "pine_sources/PBK_Test.pine",
        "filename": "PBK_Test.pine",
        "stem": "PBK_Test",
    }
    result = safe_substitute(template, values)
    assert result == 'Delegate to worker: {"read_only": ["pine_sources/PBK_Test.pine"], "target": "doc/PBK_Test.pine_manual.md"}'


def test_parse_args_with_separator():
    raw = 'pine_sources/*.pine -u doc/indicator/{filename}_manual.md -c -n 5 :: Delegate to worker for {file}'
    parsed, template, err = ForeachCommand.parse_args(raw)

    assert parsed.pattern == "pine_sources/*.pine"
    assert parsed.unless_exists == "doc/indicator/{filename}_manual.md"
    assert parsed.clear is True
    assert parsed.limit == 5
    assert template == "Delegate to worker for {file}"


def test_parse_args_without_separator():
    raw = 'src/*.py -n 2 Add documentation for {stem}'
    parsed, template, err = ForeachCommand.parse_args(raw)

    assert parsed.pattern == "src/*.py"
    assert parsed.limit == 2
    assert parsed.clear is False
    assert template == "Add documentation for {stem}"


@pytest.mark.asyncio
async def test_execute_dry_run(tmp_path):
    # Setup test files
    src_dir = tmp_path / "pine_sources"
    src_dir.mkdir()
    (src_dir / "PBK_A.pine").write_text("// A", encoding="utf-8")
    (src_dir / "PBK_B.pine").write_text("// B", encoding="utf-8")

    io = MagicMock()
    coder = SimpleNamespace(root=str(tmp_path), run_one=AsyncMock())

    result = await ForeachCommand.execute(
        io,
        coder,
        "pine_sources/PBK_*.pine --dry-run :: Process {filename}"
    )

    assert "Dry-run completed" in result
    coder.run_one.assert_not_called()
    assert any("2 item(s) to process" in str(call) for call in io.tool_output.call_args_list)


@pytest.mark.asyncio
async def test_execute_unless_exists_skips_existing(tmp_path):
    src_dir = tmp_path / "pine_sources"
    doc_dir = tmp_path / "doc"
    src_dir.mkdir()
    doc_dir.mkdir()

    (src_dir / "PBK_A.pine").write_text("// A", encoding="utf-8")
    (src_dir / "PBK_B.pine").write_text("// B", encoding="utf-8")
    # PBK_A manual already exists
    (doc_dir / "PBK_A.pine_manual.md").write_text("# Manual A", encoding="utf-8")

    io = MagicMock()
    coder = SimpleNamespace(root=str(tmp_path), run_one=AsyncMock())

    result = await ForeachCommand.execute(
        io,
        coder,
        "pine_sources/PBK_*.pine -u doc/{filename}_manual.md :: Create manual for {file}"
    )

    assert "Successfully executed foreach" in result
    assert coder.run_one.call_count == 1
    assert any("Processed 1/1 item(s) (1 skipped)" in str(call) for call in io.tool_output.call_args_list)
    # Check that PBK_B was processed and PBK_A was skipped
    args, kwargs = coder.run_one.call_args
    assert "pine_sources/PBK_B.pine" in args[0]


@pytest.mark.asyncio
async def test_execute_clears_context_when_flag_present(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "item1.txt").write_text("1", encoding="utf-8")

    from cecli.tools.read_file import Tool as ReadFileTool

    ReadFileTool._last_invocation["x"] = {"start_idx": 0, "end_idx": 1}
    ReadFileTool._last_read_turn["x"] = 1
    ReadFileTool._special_marker_count["x"] = 2

    io = MagicMock()
    coder = SimpleNamespace(
        root=str(tmp_path),
        run_one=AsyncMock(),
        file_read_cache={"x"},
    )

    with patch("cecli.helpers.conversation.ConversationService.get_manager") as mock_get_manager, \
         patch("cecli.helpers.conversation.ConversationService.get_files") as mock_get_files:
        mock_manager = MagicMock()
        mock_get_manager.return_value = mock_manager
        mock_files = MagicMock()
        mock_get_files.return_value = mock_files

        result = await ForeachCommand.execute(
            io,
            coder,
            "src/*.txt -c :: Review {filename}"
        )

        assert mock_manager.clear_tag.call_count >= 1
        assert mock_files.reset.call_count >= 1
        assert coder.file_read_cache == set()
        assert ReadFileTool._last_invocation == {}
        assert ReadFileTool._last_read_turn == {}
        assert ReadFileTool._special_marker_count == {}
        assert coder.run_one.call_count == 1
