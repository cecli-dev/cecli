"""Regression tests for Command.format_output rendering.

format_output() prints the "Tool Call:" header before execute() runs, so it
must clearly communicate what execute() is about to do — including the case
where the LLM emits an empty/no-op call (no `command` and no
`background_key`/`action` pair). Without an explicit message, such a call
renders a header with a blank body, which looks identical (from the user's
perspective) to a genuine display bug where an auto-approved command call
fails to print its body at all.
"""

import json
from types import SimpleNamespace

import pytest

from cecli.tools import command


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

    def format_command_with_prefix(self, cmd):
        return cmd


def make_tool_response(args):
    return SimpleNamespace(
        id="test-id",
        type="function",
        function=SimpleNamespace(
            name="Command",
            arguments=json.dumps(args),
        ),
    )


def render(coder, args):
    command.Tool.format_output(
        coder,
        mcp_server=SimpleNamespace(name="Local"),
        tool_response=make_tool_response(args),
    )
    return "\n".join(coder.io.outputs)


def test_format_output_shows_command_text():
    coder = DummyCoder()
    output = render(coder, {"command": "echo hi"})
    assert "Tool Call:" in output
    assert "Command:" in output
    assert "echo hi" in output


def test_format_output_empty_args_shows_explicit_placeholder():
    """Regression test: an empty-args call (no command, no background_key/action)
    must not render a header with a silently blank body.

    Reproduces a real session where the model called `Command` with `{}` —
    execute() correctly rejects this ("'command' must be provided."), but the
    displayed panel showed nothing after the header, which was mistaken for
    a display bug (auto-approved commands failing to render their body).
    """
    coder = DummyCoder()
    output = render(coder, {})

    assert "Tool Call:" in output
    assert "no command provided" in output
    # Must not silently look identical to a "nothing rendered" panel.
    assert "Command:" not in output


def test_format_output_background_key_action_shown_without_command():
    coder = DummyCoder()
    output = render(coder, {"background_key": "bg-123", "action": "stop"})

    assert "Tool Call:" in output
    assert "Background Key:" in output
    assert "bg-123" in output
    assert "Action:" in output
    assert "stop" in output
    assert "no command provided" not in output


@pytest.mark.asyncio
async def test_execute_rejects_empty_args_matching_format_output_case():
    """execute() must actually reject the same empty-args shape that
    format_output flags, keeping the two code paths consistent."""

    class ExecCoder(DummyCoder):
        skip_cli_confirmations = True

        def __init__(self):
            super().__init__()
            self.agent_config = {}

    coder = ExecCoder()
    response = await command.Tool.execute(coder)
    result = response.to_dict()
    assert result["result"] == []
    assert "'command' must be provided." in result["errors"]
