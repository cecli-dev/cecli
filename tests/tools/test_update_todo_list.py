import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cecli.tools import update_todo_list
from cecli.tools.update_todo_list import (
    coerce_task_item,
    format_task_lines,
    normalize_task_items,
)
from cecli.tools.utils.helpers import ToolError, normalize_json_array


def test_normalize_json_array_parses_string():
    items = normalize_json_array('[{"task": "a", "done": false}]', param_name="tasks")
    assert len(items) == 1
    assert items[0]["task"] == "a"


def test_normalize_json_array_rejects_invalid_json():
    with pytest.raises(ToolError, match="Invalid tasks parameter JSON"):
        normalize_json_array("not json", param_name="tasks")


def test_format_task_lines_accepts_json_string():
    tasks_json = json.dumps(
        [
            {"task": "Draft roadmap items in docs/ROADMAP.md", "done": False},
            {"task": "Ship fix", "done": True},
        ]
    )
    done, remaining = format_task_lines(tasks_json)
    assert len(remaining) == 1
    assert "Draft roadmap" in remaining[0]
    assert len(done) == 1
    assert "Ship fix" in done[0]
    assert all(len(line) > 5 for line in remaining + done)


def test_normalize_task_items_does_not_split_characters():
    tasks_json = json.dumps([{"task": "Only one task", "done": False}])
    items = normalize_task_items(tasks_json)
    assert len(items) == 1
    assert items[0]["task"] == "Only one task"


def test_coerce_task_item_plain_string_starting_with_brace():
    item = coerce_task_item("{not valid json")
    assert item == {"task": "{not valid json", "done": False, "current": False}


class DummyIO:
    def __init__(self):
        self.tool_output = Mock()
        self.tool_error = Mock()
        self.tool_warning = Mock()


class DummyCoder:
    def __init__(self):
        self.io = DummyIO()
        self.pretty = False
        self.verbose = False


def test_format_output_accepts_tasks_as_json_string():
    coder = DummyCoder()
    args = json.dumps(
        {
            "tasks": (
                '[{"task": "Draft roadmap items", "done": false}, '
                '{"task": "Write tests", "done": true}]'
            )
        }
    )
    tool_response = SimpleNamespace(
        function=SimpleNamespace(name="UpdateTodoList", arguments=args)
    )

    update_todo_list.Tool.format_output(
        coder,
        mcp_server=SimpleNamespace(name="test"),
        tool_response=tool_response,
    )

    output_text = "\n".join(call.args[0] for call in coder.io.tool_output.call_args_list)
    assert "Draft roadmap items" in output_text
    assert "Write tests" in output_text
    assert output_text.count("○ ") == 1
    assert "○ Draft roadmap items" in output_text
    assert "✓ Write tests" in output_text
    coder.io.tool_error.assert_not_called()


def test_format_output_reports_invalid_tasks_json():
    coder = DummyCoder()
    args = json.dumps({"tasks": "not json"})
    tool_response = SimpleNamespace(
        function=SimpleNamespace(name="UpdateTodoList", arguments=args)
    )

    update_todo_list.Tool.format_output(
        coder,
        mcp_server=SimpleNamespace(name="test"),
        tool_response=tool_response,
    )

    coder.io.tool_error.assert_called_once()
    assert "Invalid tasks parameter JSON" in coder.io.tool_error.call_args.args[0]
