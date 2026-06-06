"""EditText tool — double-encoded edits and format_output safety."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

from cecli.tools import edit_text
from cecli.tools.utils.base_tool import BaseTool


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


class _NoTrackTool(BaseTool):
    """Minimal tool mirroring EditText LIST_PARAMS + TRACK_INVOCATIONS=False."""

    NORM_NAME = "notrack"
    TRACK_INVOCATIONS = False
    LIST_PARAMS = ["edits"]
    SCHEMA = {
        "function": {
            "name": "NoTrack",
            "parameters": {
                "type": "object",
                "properties": {
                    "edits": {"type": "array"},
                },
                "required": ["edits"],
            },
        }
    }

    @classmethod
    def execute(cls, coder, edits=None, **kwargs):
        if not isinstance(edits, list):
            return f"edits type={type(edits).__name__}"
        return f"edits len={len(edits)}"


def test_list_params_normalized_when_track_invocations_disabled():
    coder = DummyCoder()
    edits_json = json.dumps(
        [{"file_path": "pubspec.yaml", "operation": "replace", "start_line": "@000", "end_line": "@000"}]
    )
    result = _NoTrackTool.process_response(coder, {"edits": edits_json})
    assert result == "edits len=1"


def test_format_output_accepts_edits_as_json_string():
    coder = DummyCoder()
    edits_json = json.dumps(
        [
            {
                "file_path": "pubspec.yaml",
                "operation": "replace",
                "start_line": "@000",
                "end_line": "@000",
                "text": "name: demo",
            }
        ]
    )
    args = json.dumps({"edits": edits_json})
    tool_response = SimpleNamespace(function=SimpleNamespace(name="EditText", arguments=args))

    edit_text.Tool.format_output(
        coder,
        mcp_server=SimpleNamespace(name="test"),
        tool_response=tool_response,
    )

    output_text = "\n".join(call.args[0] for call in coder.io.tool_output.call_args_list)
    assert "pubspec.yaml" in output_text
    coder.io.tool_error.assert_not_called()


def test_format_output_string_edits_does_not_crash():
    """Regression: iterating a JSON string used to raise AttributeError in format_output."""
    coder = DummyCoder()
    edits_json = json.dumps([{"file_path": "a.txt", "operation": "replace"}])
    tool_response = SimpleNamespace(
        function=SimpleNamespace(name="EditText", arguments=json.dumps({"edits": edits_json}))
    )

    edit_text.Tool.format_output(
        coder,
        mcp_server=SimpleNamespace(name="test"),
        tool_response=tool_response,
    )

    coder.io.tool_error.assert_not_called()
