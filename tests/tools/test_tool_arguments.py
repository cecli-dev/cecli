"""Glued local-model tool JSON argument parsing."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cecli.coders.base_coder import Coder
from cecli.helpers.responses import (
    _repair_local_model_json_text,
    coerce_tool_structure,
    extract_tools_from_content_json,
    merge_glued_json_objects,
    parse_tool_arguments,
    try_join_char_split_json_array,
    try_parse_json_value,
)
from cecli.tools.grep import Tool as GrepTool
from cecli.tools.utils.helpers import ToolError, normalize_json_array


def test_parse_tool_arguments_merges_glued_objects_with_empty_fragments():
    raw = '{"limit": 15}{}{"path": "."}'
    assert parse_tool_arguments(raw) == {"limit": 15, "path": "."}


def test_parse_tool_arguments_merges_grep_style_glued_args():
    raw = (
        '{"limit": 15}{}{"searches": [{"file_pattern": "*.md", '
        '"pattern": "TODO|FIXME", "use_regex": true}]}'
    )
    out = parse_tool_arguments(raw)
    assert out["limit"] == 15
    assert out["searches"][0]["pattern"] == "TODO|FIXME"


def test_merge_glued_returns_none_for_non_object_chunks():
    assert merge_glued_json_objects(['["a"]', '{"b": 1}']) is None


def test_merge_glued_all_empty_chunks_returns_dict():
    """All-empty chunks should return an empty dict (no non-empty content to merge)."""
    result = merge_glued_json_objects(["{}", "{}"])
    assert result is not None
    assert result == {}


def test_merge_glued_single_empty_chunk_returns_dict():
    """A single empty object chunk should return an empty dict."""
    result = merge_glued_json_objects(["{}"])
    assert result is not None
    assert result == {}


def test_merge_glued_empty_string_chunks_returns_empty_dict():
    """Chunks that are empty strings are skipped, returning an empty merged dict."""
    result = merge_glued_json_objects(["", "", ""])
    # Empty strings are stripped to empty and skipped, leaving merged == {} -> returns {}
    assert result == {}


def test_expand_concatenated_json_merges_instead_of_splitting(monkeypatch):
    """Dogfood: DeepSeek ``{…}{}{…}`` must not become three tool calls."""

    class MiniCoder(Coder):
        def __init__(self):
            pass

    coder = MiniCoder.__new__(MiniCoder)
    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(
            name="ls",
            arguments='{"limit": 15}{}{"path": "."}',
        ),
    )
    expanded = coder._expand_concatenated_json([tool_call])
    assert len(expanded) == 1
    assert json.loads(expanded[0].function.arguments) == {"limit": 15, "path": "."}
    assert expanded[0].id == "call-1"


def test_grep_format_output_empty_searches_does_not_crash_tool_footer():
    coder = SimpleNamespace(
        io=SimpleNamespace(
            tool_error=Mock(), tool_output=Mock(), tool_warning=Mock(), _last_type=False
        ),
        verbose=False,
        pretty=False,
        tui=lambda: None,
    )
    tool_response = SimpleNamespace(
        function=SimpleNamespace(
            name="Grep",
            arguments='{"limit": 15}{}{"searches": []}',
        ),
    )
    GrepTool.format_output(
        coder,
        mcp_server=SimpleNamespace(name="Local"),
        tool_response=tool_response,
    )
    assert not coder.io.tool_error.called


def test_try_join_char_split_json_array_reconstructs_array():
    """Char-split JSON array should be joined back into a proper list."""
    items = ["[", "{", '"', "t", "a", "s", "k", '"', ":", " ", '"', "x", '"', "}", "]"]
    result = try_join_char_split_json_array(items)
    assert result == [{"task": "x"}]


def test_try_join_char_split_json_array_reconstructs_dict():
    """Char-split JSON object should be joined and wrapped in a list."""
    items = ["{", '"', "a", '"', ":", " ", "1", "}"]
    result = try_join_char_split_json_array(items)
    assert result == [{"a": 1}]


def test_try_join_char_split_json_array_too_few_items():
    """Less than 8 items should return None."""
    assert try_join_char_split_json_array(["{", "}"]) is None


def test_try_join_char_split_json_array_non_string_items():
    """Non-string items should return None."""
    assert try_join_char_split_json_array(["[", 1, "{", "}"]) is None


def test_try_join_char_split_json_array_does_not_start_with_brace():
    """Joined string not starting with [ or { should return None."""
    items = list('"hello"')  # A JSON string, not object/array
    assert try_join_char_split_json_array(items) is None


def test_try_join_char_split_json_array_invalid_json():
    """Joined string that is invalid JSON should return None."""
    items = ["{", '"', "a", '"', ":", " ", "b", "r", "o", "k", "e", "n", "}"]
    assert try_join_char_split_json_array(items) is None


def test_repair_local_model_json_text_newline_before_quote():
    """Repair colon-newline-quote breakage inside JSON."""
    broken = '"end_text":\n",'
    fixed = _repair_local_model_json_text(broken)
    assert '"end_text": "",' in fixed


def test_repair_local_model_json_text_newline_before_closing_brace():
    """Repair colon-newline-quote before closing brace."""
    broken = '"end_text":\n"}'
    fixed = _repair_local_model_json_text(broken)
    assert '"end_text": ""}' in fixed


def test_repair_local_model_json_text_valid_json_passes_through():
    """Valid JSON text should remain unchanged."""
    valid = '{"limit": 15, "path": "."}'
    assert _repair_local_model_json_text(valid) == valid


def test_normalize_json_array_actual_list_passthrough():
    """A proper list should pass through unchanged."""
    data = [{"pattern": "foo"}, {"pattern": "bar"}]
    result = normalize_json_array(data, param_name="searches")
    assert result == data


def test_normalize_json_array_char_split_input():
    """Char-split list should be joined back into a proper array."""
    items = ["[", "{", '"', "t", "a", "s", "k", '"', ":", " ", '"', "x", '"', "}", "]"]
    result = normalize_json_array(items, param_name="delegations")
    assert result == [{"task": "x"}]


def test_normalize_json_array_json_string_wrapping_array():
    """A JSON string containing an array should be parsed."""
    result = normalize_json_array('[{"a": 1}, {"b": 2}]', param_name="edits")
    assert result == [{"a": 1}, {"b": 2}]


def test_normalize_json_array_json_string_wrapping_dict():
    """A JSON string containing a dict should be wrapped in a list."""
    result = normalize_json_array('{"task": "hello"}', param_name="tasks")
    assert result == [{"task": "hello"}]


def test_normalize_json_array_empty_string_raises_tool_error():
    """An empty string should raise ToolError."""
    with pytest.raises(ToolError, match="array cannot be empty"):
        normalize_json_array("", param_name="items")


def test_normalize_json_array_empty_string_with_allow_empty():
    """An empty string with allow_empty=True should return empty list."""
    assert normalize_json_array("", param_name="items", allow_empty=True) == []


def test_normalize_json_array_invalid_json_string_raises_tool_error():
    """An invalid JSON string should raise ToolError."""
    with pytest.raises(ToolError, match="Invalid.*parameter JSON"):
        normalize_json_array("{broken", param_name="items")


def test_normalize_json_array_dict_input_wraps_in_list():
    """A bare dict should be wrapped in a list."""
    result = normalize_json_array({"task": "hello"}, param_name="tasks")
    assert result == [{"task": "hello"}]


def test_normalize_json_array_non_list_non_dict_raises():
    """A non-list, non-dict, non-string value should raise ToolError."""
    with pytest.raises(ToolError, match="must be an array"):
        normalize_json_array(42, param_name="items")


def test_normalize_json_array_empty_list_without_allow_empty_raises():
    """An empty list without allow_empty should raise ToolError."""
    with pytest.raises(ToolError, match="array cannot be empty"):
        normalize_json_array([], param_name="items")


def test_normalize_json_array_empty_list_with_allow_empty():
    """An empty list with allow_empty=True should pass through."""
    assert normalize_json_array([], param_name="items", allow_empty=True) == []


def test_extract_tools_from_content_json_with_arguments_key():
    """Standard tool calls with 'arguments' key should be extracted."""
    content = '{"name": "ls", "arguments": {"path": "."}}'
    result = extract_tools_from_content_json(content)
    assert result is not None
    assert len(result) == 1
    assert result[0].function.name == "ls"
    assert json.loads(result[0].function.arguments) == {"path": "."}


def test_extract_tools_from_content_json_with_parameters_key():
    """Tool calls with 'parameters' key should be extracted."""
    content = '{"name": "ls", "parameters": {"path": "."}}'
    result = extract_tools_from_content_json(content)
    assert result is not None
    assert len(result) == 1
    assert result[0].function.name == "ls"
    assert json.loads(result[0].function.arguments) == {"path": "."}


def test_extract_tools_from_content_json_with_params_key():
    """Tool calls with 'params' key should be extracted."""
    content = '{"name": "ls", "params": {"path": "."}}'
    result = extract_tools_from_content_json(content)
    assert result is not None
    assert len(result) == 1
    assert result[0].function.name == "ls"
    assert json.loads(result[0].function.arguments) == {"path": "."}


def test_extract_tools_from_content_json_array_with_parameters():
    """Array of tool calls with 'parameters' key should be extracted."""
    content = (
        '[{"name": "ls", "parameters": {"path": "."}},'
        ' {"name": "grep", "parameters": {"pattern": "foo"}}]'
    )
    result = extract_tools_from_content_json(content)
    assert result is not None
    assert len(result) == 2
    assert result[0].function.name == "ls"
    assert result[1].function.name == "grep"
    assert json.loads(result[1].function.arguments) == {"pattern": "foo"}


def test_parse_tool_arguments_truly_unparseable():
    """Truly unparsable JSON should return an empty dict."""
    inp = "this is not json at all!!!"
    result = parse_tool_arguments(inp)
    assert "@error" in result
    assert "Malformed JSON arguments" in result["@error"]


def test_parse_tool_arguments_empty_string():
    """Empty string should return an empty dict."""
    assert parse_tool_arguments("") == {}
    assert parse_tool_arguments("   ") == {}
    assert parse_tool_arguments(None) == {}


def test_try_parse_json_value_empty_text():
    """Empty text should return None."""
    assert try_parse_json_value("") is None
    assert try_parse_json_value("   ") is None


def test_parse_tool_arguments_uneven_glued_objects_with_list():
    """Glued objects where one chunk is a list should not merge (fallback)."""
    # This is a case that currently returns {} because the merge fails
    inp = '{"a": 1}{"b": 2}["c"]'
    result = parse_tool_arguments(inp)
    # The function tries to parse, failing on the mixed glued content
    assert "@error" in result
    assert "Could not merge glued JSON objects" in result["@error"]


def test_coerce_tool_structure_dict_value():
    """A single 'arguments' key wrapping a dict should be unwrapped."""
    assert coerce_tool_structure({"arguments": {"query": "x"}}) == {"query": "x"}


def test_coerce_tool_structure_json_string_value():
    """A single 'arguments' key holding a JSON-encoded string should be unwrapped."""
    assert coerce_tool_structure({"arguments": '{"query": "x"}'}) == {"query": "x"}


def test_coerce_tool_structure_parameters_key():
    """'parameters' and 'params' wrappers should also be unwrapped."""
    assert coerce_tool_structure({"parameters": {"path": "."}}) == {"path": "."}
    assert coerce_tool_structure({"params": {"path": "."}}) == {"path": "."}


def test_coerce_tool_structure_ignores_multi_key_dict():
    """A dict with other keys alongside 'arguments' is not a wrapper and is left alone."""
    wrapped = {"arguments": {"query": "x"}, "extra": 1}
    assert coerce_tool_structure(wrapped) is wrapped


def test_coerce_tool_structure_ignores_non_dict_values():
    """Non-dict (or unparsable) wrapper values are left alone."""
    assert coerce_tool_structure({"arguments": 5}) == {"arguments": 5}
    assert coerce_tool_structure({"arguments": ["a"]}) == {"arguments": ["a"]}
    assert coerce_tool_structure({"arguments": "not json"}) == {"arguments": "not json"}


def test_coerce_tool_structure_ignores_empty():
    """An empty dict is not a wrapper."""
    assert coerce_tool_structure({}) == {}


def test_parse_tool_arguments_unwraps_wire_format_wrapper():
    """A model mirroring the OpenAI wire format should still bind real params."""
    assert parse_tool_arguments('{"arguments": {"query": "repo:cecli"}}') == {"query": "repo:cecli"}


def test_parse_tool_arguments_unwraps_wire_format_string():
    """JSON-encoded string form of the wire-format wrapper should be unwrapped."""
    assert parse_tool_arguments('{"arguments": "{\\"query\\": \\"repo:cecli\\"}"}') == {
        "query": "repo:cecli"
    }


class _FakeMcpSession:
    """Minimal stand-in for an mcp ClientSession that records the call."""

    def __init__(self):
        self.calls = []

    async def call_tool(self, name=None, arguments=None):
        self.calls.append((name, arguments))
        return SimpleNamespace(content=[])


def _make_mini_coder():
    class MiniCoder(Coder):
        def __init__(self):
            pass

    return MiniCoder.__new__(MiniCoder)


async def test_call_mcp_tool_from_session_unwraps_arguments_key():
    """call_mcp_tool_from_session must unwrap a wire-format wrapper before session.call_tool."""
    coder = _make_mini_coder()
    session = _FakeMcpSession()
    tool_call = {
        "function": {
            "name": "github--search_code",
            "arguments": '{"arguments": "{\\"query\\": \\"repo:cecli\\"}"}',
        }
    }
    await coder.call_mcp_tool_from_session(session, tool_call)
    assert session.calls == [("github--search_code", {"query": "repo:cecli"})]


async def test_call_mcp_tool_from_session_passes_plain_params_through():
    """Normal params must pass through call_mcp_tool_from_session unchanged."""
    coder = _make_mini_coder()
    session = _FakeMcpSession()
    tool_call = {
        "function": {
            "name": "github--list_issues",
            "arguments": '{"owner": "cecli-dev", "repo": "cecli"}',
        }
    }
    await coder.call_mcp_tool_from_session(session, tool_call)
    assert session.calls == [("github--list_issues", {"owner": "cecli-dev", "repo": "cecli"})]
