"""Tests for ManageExtensions.format_output rendering."""

import json
from types import SimpleNamespace

from cecli.tools import manage_extensions


class DummyIO:
    def __init__(self):
        self.outputs = []
        self._last_type = None

    def tool_output(self, msg="", type=None, **kwargs):
        self.outputs.append(str(msg))
        self._last_type = type

    def tool_error(self, msg="", **kwargs):
        self.outputs.append(f"ERROR: {msg}")


class DummyCoder:
    def __init__(self):
        self.io = DummyIO()
        self.pretty = False
        self.verbose = False


def make_tool_response(args):
    return SimpleNamespace(
        id="test-id",
        type="function",
        function=SimpleNamespace(
            name="ManageExtensions",
            arguments=json.dumps(args),
        ),
    )


def render(coder, args):
    manage_extensions.Tool.format_output(
        coder,
        mcp_server=SimpleNamespace(name="Local"),
        tool_response=make_tool_response(args),
    )

    return "\n".join(coder.io.outputs)


def test_format_output_combines_short_options_and_puts_content_last():
    coder = DummyCoder()

    output = render(
        coder,
        {
            "action": "add",
            "type": "skill",
            "scope": "local",
            "name": "pdf",
            "apply_to": ["reviewer"],
            "config": {"name": "pdf"},
            "content": "line one\nline two\n",
        },
    )

    assert "Tool Call:" in output
    assert "action: add" in output
    assert "type: skill" in output
    assert "scope: local" in output
    assert "name: pdf" in output
    assert "apply_to: reviewer" in output
    assert 'config: {"name": "pdf"}' in output

    # Content is the largest field and must render after every short option.
    assert "content:" in output
    assert "line one" in output
    assert output.index("config:") < output.index("content:")
    assert output.index("line one") < output.index("line two")


def test_format_output_omits_absent_optional_fields():
    coder = DummyCoder()

    output = render(coder, {"action": "list", "type": "config"})

    assert "action: list" in output
    assert "type: config" in output
    assert "scope: local" in output
    assert "name:" not in output
    assert "apply_to:" not in output
    assert "content:" not in output


def test_format_output_reports_invalid_arguments():
    coder = DummyCoder()
    tool_response = SimpleNamespace(
        id="test-id",
        type="function",
        function=SimpleNamespace(name="ManageExtensions", arguments="{not json"),
    )

    manage_extensions.Tool.format_output(
        coder,
        mcp_server=SimpleNamespace(name="Local"),
        tool_response=tool_response,
    )

    assert any("Invalid Tool JSON" in output for output in coder.io.outputs)
