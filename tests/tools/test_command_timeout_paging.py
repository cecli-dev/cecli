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
        large_file_token_threshold=8,
        context_management_enabled=True,
    )
    manager = background_commands.BackgroundCommandManager
    target = "bg_1_1234"
    process = Mock()
    popen = Mock(return_value=process)
    state = {"output": "", "buffer": None}

    real_buffer_cls = background_commands.PagedOutputBuffer

    def make_buffer(page_size=4096, pages_dir=None):
        buffer = real_buffer_cls(page_size=page_size, pages_dir=pages_dir)
        state["buffer"] = buffer
        if state["output"]:
            buffer.append(state["output"])
        return buffer

    monkeypatch.setattr(background_commands, "PagedOutputBuffer", make_buffer)
    monkeypatch.setattr("subprocess.Popen", popen)
    monkeypatch.setattr(manager, "_generate_command_key", Mock(return_value=target))
    start = Mock(return_value=target)
    stop = Mock()
    monkeypatch.setattr(manager, "start_background_command", start)
    monkeypatch.setattr(manager, "stop_background_command", stop)
    pending_tasks = []

    async def pending_wait(*args, **kwargs):
        pending_tasks.append(asyncio.current_task())
        await asyncio.get_running_loop().create_future()

    monkeypatch.setattr(asyncio, "to_thread", Mock(side_effect=pending_wait))

    async def execute(output, threshold=8, enabled=True):
        coder.large_file_token_threshold = threshold
        coder.context_management_enabled = enabled
        state["output"] = output
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
        popen.assert_called_once()
        start.assert_called_once()
        assert start.call_args.kwargs["existing_process"] is process
        assert start.call_args.kwargs["existing_buffer"] is state["buffer"]
        assert start.call_args.kwargs["persist"] is True
        assert start.call_args.kwargs["command_key"] == (target if enabled else None)
        stop.assert_not_called()
        process.wait.assert_not_called()
        process.terminate.assert_not_called()
        process.kill.assert_not_called()
        return content

    try:
        yield SimpleNamespace(execute=execute, coder=coder, target=target, state=state)
    finally:
        for task in pending_tasks:
            task.cancel()

        await asyncio.gather(*pending_tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_elapsed_timeout_pages_output_and_exposes_command_keys(elapsed_command):
    coder = elapsed_command.coder
    target = elapsed_command.target
    page_size = int(coder.large_file_token_threshold * 3.5)
    output = "first line: café\nsecond line\n" * 3
    content = await elapsed_command.execute(output)
    num_pages = len(output) // page_size

    assert num_pages >= 1
    assert output not in content
    assert f"Output paged to disk: {num_pages} page(s)." in content
    assert "ResourceManager" in content
    assert "not added to file context" in content
    assert "command_key::" not in content
    example = next(line for line in content.splitlines() if line.startswith('{"paging"'))
    assert json.loads(example) == {"paging": [{"target": target, "page": 1}]}

    folder = Path(coder.abs_root_path(coder.local_agent_folder(target)))
    assert {path.name for path in folder.iterdir()} == {
        f"{page}.txt" for page in range(1, num_pages + 1)
    }
    saved_pages = [
        (folder / f"{page}.txt").read_text(encoding="utf-8") for page in range(1, num_pages + 1)
    ]
    assert "".join(saved_pages) == output[: num_pages * page_size]

    editable_before = coder.abs_fnames.copy()
    read_only_before = coder.abs_read_only_fnames.copy()
    response = await ResourceManagerTool.execute(coder, paging=[{"target": target, "page": 1}])
    result = response.to_dict()
    assert result["errors"] == []
    assert result["result"][0]["content"].endswith(output[:page_size])
    assert coder.abs_fnames == editable_before
    assert coder.abs_read_only_fnames == read_only_before
    coder._add_file_to_context.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "threshold,length,paged", [(8, 27, False), (8, 28, True), (9, 30, False), (9, 31, True)]
)
async def test_elapsed_timeout_paging_triggers_at_page_size(
    elapsed_command, threshold, length, paged
):
    output = "x" * length
    content = await elapsed_command.execute(output, threshold=threshold)

    if paged:
        page_size = int(threshold * 3.5)
        assert "Output paged to disk: 1 page(s)." in content
        assert output not in content
        folder = Path(
            elapsed_command.coder.abs_root_path(
                elapsed_command.coder.local_agent_folder(elapsed_command.target)
            )
        )
        assert (folder / "1.txt").read_text(encoding="utf-8") == output[:page_size]
    else:
        assert f"Output captured so far:\n{output}\n" in content
        assert "Output paged to disk" not in content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output,enabled", [("", True), ("small output\n", True), ("large output\n" * 100, False)]
)
async def test_elapsed_timeout_keeps_small_empty_or_unmanaged_output_inline(
    elapsed_command, output, enabled
):
    content = await elapsed_command.execute(output, enabled=enabled)

    assert f"Output captured so far:\n{output}\n" in content
    assert "Output paged to disk" not in content
