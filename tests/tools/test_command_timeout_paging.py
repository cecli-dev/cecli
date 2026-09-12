"""Regression coverage for output paging when a command's timeout actually elapses."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import pytest_asyncio

from cecli.helpers import background_commands
from cecli.tools.command import Tool as CommandTool
from cecli.tools.resource_manager import Tool as ResourceManagerTool


@pytest_asyncio.fixture
async def elapsed_command(monkeypatch, tmp_path):
    """Keep process completion pending without starting a real process or worker thread."""
    coder = SimpleNamespace(
        root=str(tmp_path),
        io=Mock(_last_type=None),
        pretty=False,
        verbose=False,
        tui=None,
        mcp_manager=None,
        agent_config={},
        abs_fnames={str(tmp_path / "existing.py")},
        abs_read_only_fnames={str(tmp_path / "reference.txt")},
        abs_root_path=Mock(side_effect=lambda path: str(tmp_path / path)),
        local_agent_folder=Mock(side_effect=lambda path: f".cecli/agents/test-agent/{path}"),
        _add_file_to_context=Mock(),
        context_blocks_cache={},
        edit_allowed=False,
        interrupt_event=asyncio.Event(),
    )
    manager = background_commands.BackgroundCommandManager
    target = "bg_1_1234"
    process = Mock()
    popen = Mock(return_value=process)
    buffer = background_commands.CircularBuffer()
    get_all = Mock(wraps=buffer.get_all)
    monkeypatch.setattr(buffer, "get_all", get_all)
    monkeypatch.setattr(background_commands, "CircularBuffer", Mock(return_value=buffer))
    monkeypatch.setattr("subprocess.Popen", popen)
    start = Mock(return_value=target)
    stop = Mock()
    save = Mock(wraps=manager.save_paginated_output)
    monkeypatch.setattr(manager, "start_background_command", start)
    monkeypatch.setattr(manager, "stop_background_command", stop)
    monkeypatch.setattr(manager, "save_paginated_output", save)
    pending_tasks = []

    async def pending_wait(*args, **kwargs):
        pending_tasks.append(asyncio.current_task())
        await asyncio.get_running_loop().create_future()

    to_thread = Mock(side_effect=pending_wait)
    monkeypatch.setattr(asyncio, "to_thread", to_thread)

    async def execute(output, threshold=8, enabled=True):
        coder.large_file_token_threshold = threshold
        coder.context_management_enabled = enabled
        buffer.append(output)
        response = await CommandTool._execute_with_timeout(
            coder, "pending command", 0.001, use_pty=False
        )
        result = response.to_dict()
        assert result["errors"] == []
        assert len(result["result"]) == 1
        content = result["result"][0]["content"]
        assert "Command exceeded 0.001s timeout and is continuing in background." in content
        assert f"Command key: {target}" in content
        assert "completed within" not in content
        assert len(pending_tasks) == 1
        assert not pending_tasks[0].done()
        assert not coder.interrupt_event.is_set()
        to_thread.assert_called_once_with(process.wait)
        popen.assert_called_once()
        start.assert_called_once()
        assert start.call_args.kwargs["existing_process"] is process
        assert start.call_args.kwargs["existing_buffer"] is buffer
        assert start.call_args.kwargs["persist"] is True
        get_all.assert_called_once_with(clear=False)
        assert buffer.get_all() == output
        stop.assert_not_called()
        process.wait.assert_not_called()
        process.terminate.assert_not_called()
        process.kill.assert_not_called()
        return content

    try:
        yield SimpleNamespace(execute=execute, coder=coder, target=target, save=save)
    finally:
        for task in pending_tasks:
            task.cancel()

        await asyncio.gather(*pending_tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_elapsed_timeout_saves_pages_readable_without_adding_context(elapsed_command):
    output = "first line: café\nsecond line\n" * 3
    content = await elapsed_command.execute(output)
    coder = elapsed_command.coder
    target = elapsed_command.target
    page_size = int(coder.large_file_token_threshold * 3.5)
    expected_pages = [
        output[index : index + page_size] for index in range(0, len(output), page_size)
    ]

    assert output not in content
    assert f"Large Response ({len(output)} characters)" in content
    assert f"Output saved in {len(expected_pages)} pages." in content
    assert "ResourceManager" in content
    assert "not added to file context" in content
    assert "command_key::" not in content
    example = next(line for line in content.splitlines() if line.startswith('{"paging"'))
    assert json.loads(example) == {"paging": [{"target": target, "page": 1}]}
    elapsed_command.save.assert_called_once_with(
        output=output,
        command_key=target,
        page_size=page_size,
        abs_root_path_func=coder.abs_root_path,
        local_agent_folder_func=coder.local_agent_folder,
    )
    folder = Path(coder.abs_root_path(coder.local_agent_folder(target)))
    assert {path.name for path in folder.iterdir()} == {
        f"{page}.txt" for page in range(1, len(expected_pages) + 1)
    }
    saved_pages = [
        (folder / f"{page}.txt").read_text(encoding="utf-8")
        for page in range(1, len(expected_pages) + 1)
    ]
    assert saved_pages == expected_pages
    assert "".join(saved_pages) == output

    editable_before = coder.abs_fnames.copy()
    read_only_before = coder.abs_read_only_fnames.copy()
    for index in range(0, len(expected_pages), 3):
        batch = expected_pages[index : index + 3]
        response = await ResourceManagerTool.execute(
            coder,
            paging=[
                {"target": target, "page": page}
                for page in range(index + 1, index + len(batch) + 1)
            ],
        )
        result = response.to_dict()
        assert result["errors"] == []
        assert len(result["result"]) == len(batch)
        for item, expected in zip(result["result"], batch):
            assert item["content"].endswith(expected)

    assert coder.abs_fnames == editable_before
    assert coder.abs_read_only_fnames == read_only_before
    coder._add_file_to_context.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "threshold,length,paged", [(8, 35, False), (8, 36, True), (9, 38, False), (9, 39, True)]
)
async def test_elapsed_timeout_paging_uses_strict_rounded_threshold(
    elapsed_command, threshold, length, paged
):
    output = "x" * length
    content = await elapsed_command.execute(output, threshold=threshold)

    if paged:
        elapsed_command.save.assert_called_once()
        assert elapsed_command.save.call_args.kwargs["page_size"] == int(threshold * 3.5)
        assert "Large Response" in content
        assert output not in content
    else:
        elapsed_command.save.assert_not_called()
        assert f"Output captured so far:\n{output}\n" in content
        assert "Large Response" not in content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output,enabled", [("", True), ("small output\n", True), ("large output\n" * 100, False)]
)
async def test_elapsed_timeout_keeps_small_empty_or_unmanaged_output_inline(
    elapsed_command, output, enabled
):
    content = await elapsed_command.execute(output, enabled=enabled)

    assert f"Output captured so far:\n{output}\n" in content
    assert "Large Response" not in content
    elapsed_command.save.assert_not_called()
