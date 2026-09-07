"""ResourceManager paging returns command output without adding context files."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from cecli.tools.resource_manager import Tool as ResourceManagerTool
from cecli.tools.utils.helpers import ToolError
from cecli.tools.utils.responses import ToolResponse


@pytest.fixture
def coder(tmp_path):
    return SimpleNamespace(
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
    )


@pytest.fixture
def operations(monkeypatch):
    """Record all context operations without causing filesystem or service side effects."""
    mocks = {}
    for name in (
        "_create",
        "_remove",
        "_view",
        "_editable",
        "_stop_command",
        "_load_skill",
        "_remove_skill",
        "_load_mcp",
        "_remove_mcp",
        "_list_mcp_servers",
    ):
        mock_type = AsyncMock if name in ("_load_mcp", "_remove_mcp", "_list_mcp_servers") else Mock
        mocks[name] = mock_type(return_value="operation completed")
        monkeypatch.setattr(ResourceManagerTool, name, mocks[name])

    return mocks


@pytest.mark.asyncio
@pytest.mark.parametrize("target,page", [("bg_1_1234", 1), ("bg_42_987654", 2)])
@pytest.mark.parametrize("content", ["first line\nsecond line: café\n", ""])
async def test_paging_returns_page_contents_without_adding_context(coder, target, page, content):
    page_path = Path(coder.abs_root_path(coder.local_agent_folder(f"{target}/{page}.txt")))
    page_path.parent.mkdir(parents=True)
    page_path.write_text(content, encoding="utf-8")
    editable_before = coder.abs_fnames.copy()
    read_only_before = coder.abs_read_only_fnames.copy()
    coder.abs_root_path.reset_mock()
    coder.local_agent_folder.reset_mock()

    response = await ResourceManagerTool.execute(coder, paging=[{"target": target, "page": page}])

    assert isinstance(response, ToolResponse)
    result = response.to_dict()
    assert result["errors"] == []
    assert len(result["result"]) == 1
    assert result["result"][0]["content"].endswith(content)
    coder.local_agent_folder.assert_called_with(f"{target}/{page}.txt")
    coder.abs_root_path.assert_any_call(f".cecli/agents/test-agent/{target}/{page}.txt")
    assert coder.abs_fnames == editable_before
    assert coder.abs_read_only_fnames == read_only_before
    coder._add_file_to_context.assert_not_called()


@pytest.mark.asyncio
async def test_missing_page_appends_response_error(coder):
    editable_before = coder.abs_fnames.copy()
    read_only_before = coder.abs_read_only_fnames.copy()

    response = await ResourceManagerTool.execute(coder, paging=[{"target": "bg_1_1234", "page": 1}])

    assert isinstance(response, ToolResponse)
    result = response.to_dict()
    assert result["result"] == []
    assert result["errors"]
    assert coder.abs_fnames == editable_before
    assert coder.abs_read_only_fnames == read_only_before
    coder._add_file_to_context.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "paging",
    [
        [],
        {"target": "bg_1_1234", "page": 1},
        "bg_1_1234/1.txt",
        1,
        False,
        [{}],
        [{"target": "bg_1_1234"}],
        [{"page": 1}],
        [{"target": "bg_1_1234", "page": 1, "extra": True}],
        [None],
        [[{"target": "bg_1_1234", "page": 1}]],
        [{"target": "bg_1_1234", "page": 1}] * 4,
    ],
)
async def test_invalid_paging_object_raises_before_operations(coder, operations, paging):
    with pytest.raises(ToolError):
        await ResourceManagerTool.execute(coder, paging=paging, create=["untouched.txt"])

    for operation in operations.values():
        operation.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target",
    [
        "",
        "bg_1",
        "bg_a_1234",
        "bg_1_abcd",
        "bg_-1_1234",
        "BG_1_1234",
        "prefix_bg_1_1234",
        "bg_1_1234_suffix",
        "bg_1_1234\n",
        "../bg_1_1234",
        "bg_1_1234/../../secret",
        1234,
        None,
        True,
    ],
)
async def test_invalid_paging_target_raises_before_operations(coder, operations, target):
    with pytest.raises(ToolError):
        await ResourceManagerTool.execute(
            coder, paging=[{"target": target, "page": 1}], create=["untouched.txt"]
        )

    for operation in operations.values():
        operation.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("page", [0, -1, 1.0, 1.5, "1", True, False, None, [], {}])
async def test_invalid_page_number_raises_before_operations(coder, operations, page):
    with pytest.raises(ToolError):
        await ResourceManagerTool.execute(
            coder, paging=[{"target": "bg_1_1234", "page": page}], create=["untouched.txt"]
        )

    for operation in operations.values():
        operation.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["add", "read_only"])
@pytest.mark.parametrize("alias", ["command_key::bg_1_1234/1.txt", "command_key::bg_1_1234"])
async def test_command_key_alias_rejected_before_any_operations(coder, operations, action, alias):
    kwargs = {
        "create": ["untouched.txt"],
        "remove": ["existing.py"],
        "add": ["aaa.py"],
        "read_only": ["aaa-reference.txt"],
        "stop": ["bg_2_1234"],
        "load_skill": ["test-skill"],
        "remove_skill": ["old-skill"],
        "load_mcp": ["test-server"],
        "remove_mcp": ["old-server"],
        "actions": ["list_mcp_servers"],
    }
    kwargs[action].append(alias)

    with pytest.raises(ToolError):
        await ResourceManagerTool.execute(coder, **kwargs)

    for operation in operations.values():
        operation.assert_not_called()

    coder._add_file_to_context.assert_not_called()


def test_paging_schema_requires_exact_target_and_positive_integer_page():
    parameters = ResourceManagerTool.SCHEMA["function"]["parameters"]
    paging = parameters["properties"]["paging"]

    assert paging["type"] == "array"
    assert paging["minItems"] == 1
    assert paging["maxItems"] == 3
    paging = paging["items"]
    assert paging["type"] == "object"
    assert set(paging["required"]) == {"target", "page"}
    assert paging["additionalProperties"] is False
    assert set(paging["properties"]) == {"target", "page"}
    assert paging["properties"]["target"]["type"] == "string"
    assert paging["properties"]["page"]["type"] == "integer"
    assert paging["properties"]["page"]["minimum"] == 1
    assert "pattern" not in paging["properties"]["target"]
    assert "bg_" in paging["properties"]["target"]["description"]
    assert "paging" not in parameters.get("required", [])


def test_format_output_shows_paging_target_and_page(coder):
    tool_response = SimpleNamespace(
        id="test-paging",
        type="function",
        function=SimpleNamespace(
            name="ResourceManager",
            arguments=json.dumps({"paging": [{"target": "bg_1_1234", "page": 7}]}),
        ),
    )

    ResourceManagerTool.format_output(coder, SimpleNamespace(name="Local"), tool_response)

    output = "\n".join(
        str(call.args[0]) for call in coder.io.tool_output.call_args_list if call.args
    )
    assert "bg_1_1234" in output
    assert "7" in output
    assert "pag" in output.lower()
    coder.io.tool_error.assert_not_called()


@pytest.mark.asyncio
async def test_three_pages_return_in_order_without_context_changes(coder):
    paging = [{"target": "bg_1_1234", "page": page} for page in (3, 1, 2)]
    contents = [f"unique content for page {item['page']}\n" for item in paging]
    for item, content in zip(paging, contents):
        path = Path(coder.abs_root_path(coder.local_agent_folder(f"bg_1_1234/{item['page']}.txt")))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    editable_before = coder.abs_fnames.copy()
    read_only_before = coder.abs_read_only_fnames.copy()
    response = await ResourceManagerTool.execute(coder, paging=paging)
    result = response.to_dict()

    assert result["errors"] == []
    assert len(result["result"]) == 3
    for item, content in zip(result["result"], contents):
        assert item["content"].endswith(content)

    assert coder.abs_fnames == editable_before
    assert coder.abs_read_only_fnames == read_only_before
    coder._add_file_to_context.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_later_entry_validated_before_reading_or_operations(coder, operations):
    paging = [{"target": "bg_1_1234", "page": 1}, {"target": "bg_1_1234", "page": False}]

    with pytest.raises(ToolError):
        await ResourceManagerTool.execute(coder, paging=paging, create=["untouched.txt"])

    coder.local_agent_folder.assert_not_called()
    coder.abs_root_path.assert_not_called()
    for operation in operations.values():
        operation.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("execution_path", ["foreground", "timeout"])
async def test_command_large_output_guidance_uses_paging_array(
    coder, monkeypatch, tmp_path, execution_path
):
    import asyncio

    from cecli.helpers import background_commands
    from cecli.tools import command

    coder.root = str(tmp_path)
    coder.large_file_token_threshold = 10
    coder.context_management_enabled = True
    coder.interrupt_event = asyncio.Event()
    manager = command.BackgroundCommandManager
    target = "bg_1_1234"
    output = "large command output\n" * 50
    save = Mock(return_value=("pages", ["1.txt", "2.txt"], ["command_key::old/1.txt"]))
    monkeypatch.setattr(manager, "save_paginated_output", save)
    monkeypatch.setattr(manager, "_generate_command_key", Mock(return_value=target))

    if execution_path == "foreground":
        monkeypatch.setattr(command, "run_cmd_subprocess", Mock(return_value=(0, output)))
        response = await command.Tool._execute_foreground(coder, "echo test")
    else:
        process = Mock()
        process.wait.return_value = 0
        monkeypatch.setattr("subprocess.Popen", Mock(return_value=process))
        monkeypatch.setattr(manager, "start_background_command", Mock(return_value=target))
        monkeypatch.setattr(manager, "stop_background_command", Mock())
        buffer = Mock()
        buffer.get_all.return_value = output
        monkeypatch.setattr(background_commands, "CircularBuffer", Mock(return_value=buffer))
        response = await command.Tool._execute_with_timeout(coder, "echo test", 30, use_pty=False)

    result = response.to_dict()
    assert result["errors"] == []
    content = result["result"][0]["content"]
    example = next(line for line in content.splitlines() if line.startswith('{"paging"'))
    assert json.loads(example) == {"paging": [{"target": target, "page": 1}]}
    assert "ResourceManager" in content
    assert "command_key::" not in content
    assert "not added to file context" in content
    save.assert_called_once()
    assert save.call_args.kwargs["output"] == output
    assert save.call_args.kwargs["command_key"] == target
